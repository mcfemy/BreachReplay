import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate, useParams, Link, useSearchParams } from "react-router-dom";
import { API_BASE, axiosInstance } from "../lib/api";
import NetworkMap from "../components/NetworkMap";
import { colors, type NodeState } from "../theme/tokens";
import {
  OUTCOME_LABELS,
  isUnknownHost,
  type HostSummary,
  type RunOutcome,
} from "../lib/useRunSocket";
import { useAuthStore } from "../store/auth";
import { startGhostRace } from "../lib/ghostRace";

// Public, no-auth Action Console run replay — GET /r/{token}.
// Loading / 404 / OG-tag shape is borrowed from PublicReplayPage.tsx
// (Arena's existing public page) and CertificatePage.tsx. The body is
// NOT SessionReplayScrubber: that component expects correct_choice /
// nist_ref / explanation from the decision-gate tree, which Action
// Console runs do not have. Timeline here is the redacted verb log
// (verb + clock, no targets). The map is the same known/unknown
// rendering ActionConsole already uses, read-only (no clickableNodeIds).
//
// Phase 4 — "Race this run" starts POST /action-runs/race with this
// share_token (auth required). Unauthenticated visitors are sent to
// login/register with ?next= back here + autoRace=1.

interface PublicTimelineEntry {
  sequence_number: number;
  verb: string;
  elapsed_seconds: number;
  cost: number;
}

interface PublicTechnique {
  technique_id: string;
  name: string;
  description: string;
}

interface PublicActionReplay {
  outcome: RunOutcome;
  score: number;
  score_pct: number;
  duration_seconds: number;
  scenario_title: string;
  mode: "daily" | "scenario";
  player_label: string;
  timeline: PublicTimelineEntry[];
  hosts: HostSummary[];
  edges: { source: string; target: string }[];
  techniques_encountered: PublicTechnique[];
}

const MODE_LABEL: Record<PublicActionReplay["mode"], string> = {
  daily: "Daily Breach",
  scenario: "Scenario",
};

const OUTCOME_COLOR: Record<RunOutcome, string> = {
  contained: colors.contain,
  contained_at_cost: colors.phosphor,
  overreacted: colors.bleed,
  breached_spread_limited: colors.phosphor,
  breached: colors.bleed,
};

function setMeta(name: string, content: string, attr: "name" | "property" = "name") {
  let el = document.head.querySelector<HTMLMetaElement>(`meta[${attr}="${name}"]`);
  if (!el) {
    el = document.createElement("meta");
    el.setAttribute(attr, name);
    document.head.appendChild(el);
  }
  el.setAttribute("content", content);
}

function formatClock(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${s.toString().padStart(2, "0")}`;
}

function verbLabel(verb: string): string {
  return verb.replace(/_/g, " ");
}

function hasMapPosition(h: HostSummary): h is HostSummary & { x: number; y: number } {
  return typeof (h as { x?: unknown }).x === "number" && typeof (h as { y?: unknown }).y === "number";
}

function hostNodeState(h: HostSummary): NodeState {
  // Same rules as ActionConsole.hostNodeState — unknown silhouette /
  // isolated contained / foothold pulsing / else compromised. Duplicated
  // rather than exported so a public page never grows a click handler
  // dependency on the live console.
  if (isUnknownHost(h)) return "unknown";
  if (h.isolated) return "contained";
  if (h.compromise_level === "none") return "clean";
  if (h.compromise_level === "foothold") return "pulsing";
  return "compromised";
}

export default function PublicActionReplayPage() {
  const { shareToken } = useParams<{ shareToken: string }>();
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const token = useAuthStore((s) => s.token);
  const [raceBusy, setRaceBusy] = useState(false);
  const [raceError, setRaceError] = useState<string | null>(null);

  const { data: replay, isLoading, isError } = useQuery<PublicActionReplay>({
    queryKey: ["public-action-replay", shareToken],
    queryFn: () =>
      axiosInstance.get(`/action-runs/public/replay/${shareToken}`).then((r) => r.data),
    retry: false,
    enabled: !!shareToken,
  });

  useEffect(() => {
    if (!replay) return;
    const title = `${replay.scenario_title} — ${OUTCOME_LABELS[replay.outcome]} — BreachReplay`;
    const description = `${replay.player_label} · ${MODE_LABEL[replay.mode]} · ${replay.score.toLocaleString()} pts · ${formatClock(replay.duration_seconds)}`;
    document.title = title;
    setMeta("description", description);
    setMeta("og:title", title, "property");
    setMeta("og:description", description, "property");
    setMeta("og:type", "website", "property");
    const image = `${API_BASE}/action-runs/public/replay/${shareToken}/card.png`;
    setMeta("og:image", image, "property");
    setMeta("twitter:card", "summary_large_image");
    setMeta("twitter:title", title);
    setMeta("twitter:description", description);
    setMeta("twitter:image", image);
    return () => {
      document.title = "BreachReplay";
    };
  }, [replay, shareToken]);

  const beginRace = async () => {
    if (!shareToken) return;
    setRaceBusy(true);
    setRaceError(null);
    try {
      const started = await startGhostRace({ share_token: shareToken });
      navigate(`/race/${started.run_id}`);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Could not start race";
      setRaceError(message);
      setRaceBusy(false);
    }
  };

  // After login/register with ?next=/r/TOKEN?race=1
  useEffect(() => {
    if (!shareToken || !token) return;
    if (searchParams.get("race") !== "1") return;
    const next = new URLSearchParams(searchParams);
    next.delete("race");
    setSearchParams(next, { replace: true });
    void beginRace();
    // intentionally once when race=1 + authed
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [shareToken, token]);

  const handleRaceClick = () => {
    if (!shareToken) return;
    if (!token) {
      const next = encodeURIComponent(`/r/${shareToken}?race=1`);
      navigate(`/login?next=${next}`);
      return;
    }
    void beginRace();
  };

  if (isLoading) {
    return (
      <div className="min-h-screen bg-void flex items-center justify-center">
        <div className="w-8 h-8 border-2 border-phosphor border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (isError || !replay) {
    return (
      <div className="min-h-screen bg-void flex items-center justify-center p-6 font-term">
        <div className="text-center max-w-sm">
          <div className="text-5xl mb-4">⚠</div>
          <h1 className="text-white text-xl font-black mb-2">Replay Not Found</h1>
          <p className="text-dim text-sm mb-6">
            This replay doesn't exist or hasn't finished yet.
          </p>
          <Link to="/" className="text-sm text-phosphor hover:text-white">
            ← Back to BreachReplay
          </Link>
        </div>
      </div>
    );
  }

  const nodes = replay.hosts.filter(hasMapPosition).map((h) => ({
    id: h.id,
    label: isUnknownHost(h) ? "" : h.hostname,
    x: h.x,
    y: h.y,
  }));
  const nodeStates: Record<string, NodeState> = {};
  for (const h of replay.hosts) {
    nodeStates[h.id] = hostNodeState(h);
  }
  const outcomeColor = OUTCOME_COLOR[replay.outcome] ?? colors.dim;

  return (
    <div className="min-h-screen bg-void flex flex-col font-term text-white">
      <div className="border-b border-white/10 bg-panel/90 px-5 py-2.5 flex items-center justify-between gap-4">
        <Link to="/" className="text-phosphor font-black text-sm uppercase tracking-widest">
          BreachReplay
        </Link>
        <span className="text-[10px] px-2 py-0.5 rounded border border-white/15 text-dim uppercase tracking-wider">
          {MODE_LABEL[replay.mode]}
        </span>
      </div>

      <div className="flex-1 overflow-y-auto p-6">
        <div className="max-w-3xl mx-auto space-y-6">
          <div className="bg-panel/80 border border-white/10 rounded-lg p-5">
            <p className="text-[10px] text-phosphor uppercase tracking-widest font-extrabold mb-1">
              Action Console Replay
            </p>
            <h1 className="text-lg font-display font-bold uppercase tracking-wider text-white mb-4">
              {replay.scenario_title}
            </h1>
            <p className="font-display text-3xl font-black mb-4" style={{ color: outcomeColor }}>
              {OUTCOME_LABELS[replay.outcome].toUpperCase()}
            </p>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
              <div>
                <div className="text-[9px] text-dim uppercase tracking-widest mb-1">Score</div>
                <div className="text-sm font-bold">{replay.score.toLocaleString()}</div>
                <div className="text-[10px] text-dim">{replay.score_pct}% </div>
              </div>
              <div>
                <div className="text-[9px] text-dim uppercase tracking-widest mb-1">Duration</div>
                <div className="text-sm font-bold">{formatClock(replay.duration_seconds)}</div>
              </div>
              <div>
                <div className="text-[9px] text-dim uppercase tracking-widest mb-1">Player</div>
                <div className="text-sm font-bold">{replay.player_label}</div>
              </div>
              <div>
                <div className="text-[9px] text-dim uppercase tracking-widest mb-1">Verbs</div>
                <div className="text-sm font-bold">{replay.timeline.length}</div>
              </div>
            </div>

            <div className="mt-5 space-y-2">
              <button
                type="button"
                onClick={handleRaceClick}
                disabled={raceBusy}
                data-testid="race-this-run"
                className="w-full py-3 rounded-lg border border-phosphor/40 bg-phosphor/10 hover:bg-phosphor/20 text-phosphor font-bold text-sm uppercase tracking-wider transition-all active:scale-95 disabled:opacity-50"
              >
                {raceBusy ? "Starting race…" : "Race this run"}
              </button>
              <p className="text-center text-[10px] text-dim">
                Start a live run on the same seed while this ghost plays beside you.
                {!token ? " Sign in required." : ""}
              </p>
              {raceError && (
                <p className="text-center text-xs text-bleed" role="alert">{raceError}</p>
              )}
            </div>
          </div>

          {nodes.length > 0 && (
            <div className="bg-panel/80 border border-white/10 rounded-lg p-5">
              <p className="text-[10px] text-phosphor uppercase tracking-widest font-extrabold mb-3">
                Final map
              </p>
              <NetworkMap
                nodes={nodes}
                edges={replay.edges}
                nodeStates={nodeStates}
                className="w-full h-64"
              />
            </div>
          )}

          <div className="bg-panel/80 border border-white/10 rounded-lg p-5">
            <p className="text-[10px] text-phosphor uppercase tracking-widest font-extrabold mb-3">
              Verb timeline
            </p>
            {replay.timeline.length === 0 ? (
              <p className="text-xs text-dim text-center py-6">No verbs were recorded in this run.</p>
            ) : (
              <div className="space-y-1.5">
                {replay.timeline.map((entry) => (
                  <div
                    key={entry.sequence_number}
                    className="w-full flex items-center gap-3 border border-white/10 rounded px-3 py-2"
                  >
                    <span className="text-[10px] text-dim w-8 shrink-0">#{entry.sequence_number}</span>
                    <span className="text-xs uppercase tracking-wider flex-1">{verbLabel(entry.verb)}</span>
                    <span className="text-[10px] text-dim">{formatClock(entry.elapsed_seconds)}</span>
                  </div>
                ))}
              </div>
            )}
          </div>

          {replay.techniques_encountered.length > 0 && (
            <div className="bg-panel/80 border border-white/10 rounded-lg p-5">
              <p className="text-[10px] text-phosphor uppercase tracking-widest font-extrabold mb-3">
                Techniques encountered
              </p>
              <ul className="space-y-2">
                {replay.techniques_encountered.map((t) => (
                  <li key={t.technique_id}>
                    <p className="text-sm text-white font-bold">{t.name}</p>
                    <p className="text-xs text-dim">{t.description}</p>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
