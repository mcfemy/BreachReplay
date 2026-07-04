import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { useParams, Link } from "react-router-dom";
import { axiosInstance } from "../lib/api";

// ── Public, no-auth Arena match replay page — Live Breach Events Phase 1 ────
// Mirrors CertificatePage.tsx's shape (public route, no AppShell, useQuery
// with retry:false, friendly not-found state) since that's the existing
// precedent for a public, unauthenticated, token-keyed page in this repo.
// Status badge colors/icons and the dark slate/cyan aesthetic are pulled
// directly from ArenaMatchPage.tsx / ArenaDebriefPage.tsx's conventions for
// attacker_won/defender_won/abandoned rather than inventing new ones.

interface PublicReplayEvent {
  sequence_number: number;
  actor: "attacker" | "defender" | null;
  action_type: string | null;
}

interface PublicReplayData {
  archetype_key: string;
  difficulty: string;
  mode: string;
  status: string;
  started_at: string | null;
  completed_at: string | null;
  action_count: number;
  attacker_label: string;
  defender_label: string;
  state: Record<string, unknown>;
  events: PublicReplayEvent[];
}

// Global Incident Response Index (Live Breach Events Phase 3) cross-link —
// same payload shape GlobalIndexPage.tsx reads, fetched here purely as a
// best-effort enhancement (see below: any failure/low-data case just hides
// the callout instead of touching the rest of the page).
interface GlobalIndexBucket {
  archetype_key?: string;
  total_matches: number;
  decisive_matches: number;
  abandoned_count: number;
  containment_rate: number;
  attacker_win_rate: number;
  avg_resolution_minutes: number | null;
}

interface GlobalIndexPayload {
  overall: GlobalIndexBucket;
  archetypes: GlobalIndexBucket[];
  generated_at: string;
  cache_ttl_seconds: number;
}

// Below this many decisive matches in the cohort, a "you beat X%" framing
// reads as noise rather than a signal — skip the callout entirely rather
// than headline a percentage computed from a handful of matches.
const MIN_DECISIVE_MATCHES_FOR_CALLOUT = 5;

const STATUS_STYLE: Record<string, { border: string; text: string; bg: string; icon: string; label: string }> = {
  attacker_won: { border: "border-red-500/50", text: "text-red-400", bg: "bg-red-500/10", icon: "💀", label: "Attacker Won" },
  defender_won: { border: "border-green-500/50", text: "text-green-400", bg: "bg-green-500/10", icon: "🛡️", label: "Defender Won" },
  abandoned: { border: "border-gray-600/50", text: "text-gray-400", bg: "bg-gray-600/10", icon: "⏹", label: "Abandoned" },
};

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function setMeta(name: string, content: string, attr: "name" | "property" = "name") {
  let el = document.head.querySelector<HTMLMetaElement>(`meta[${attr}="${name}"]`);
  if (!el) {
    el = document.createElement("meta");
    el.setAttribute(attr, name);
    document.head.appendChild(el);
  }
  el.setAttribute("content", content);
}

export default function PublicReplayPage() {
  const { shareToken } = useParams<{ shareToken: string }>();

  const { data: replay, isLoading, isError } = useQuery<PublicReplayData>({
    queryKey: ["public-replay", shareToken],
    queryFn: () => axiosInstance.get(`/arena/public/replay/${shareToken}`).then((r) => r.data),
    retry: false,
    enabled: !!shareToken,
  });

  // Best-effort "you beat X% of defenders/attackers" cross-link into the
  // Global Incident Response Index. Fetched lazily (only once the replay is
  // known and decisive) and never blocking/erroring the rest of the page —
  // queryKey matches GlobalIndexPage.tsx's so the two pages share one cache
  // entry when both are visited in the same session.
  const { data: globalIndex } = useQuery<GlobalIndexPayload>({
    queryKey: ["global-index"],
    queryFn: () => axiosInstance.get("/arena/public/stats/global-index").then((r) => r.data),
    retry: false,
    enabled: !!replay && (replay.status === "attacker_won" || replay.status === "defender_won"),
    staleTime: 60_000,
  });

  const archetypeStats = globalIndex?.archetypes.find((a) => a.archetype_key === replay?.archetype_key);
  const showCohortCallout =
    !!replay &&
    !!archetypeStats &&
    archetypeStats.decisive_matches >= MIN_DECISIVE_MATCHES_FOR_CALLOUT &&
    (replay.status === "attacker_won" || replay.status === "defender_won");

  // Best-effort client-side Open Graph / Twitter Card tags — this is a plain
  // Vite SPA with no SSR/prerender path, so most link-unfurl bots (which
  // don't execute JS) won't see these. Solving that properly needs an SSR or
  // prerender layer, which is explicitly out of scope for this phase per the
  // plan — this is the best a client-only page can do, and still helps for
  // any unfurler that does render JS, plus sets the tab title/description.
  useEffect(() => {
    if (!replay) return;
    const title = `${replay.attacker_label} vs ${replay.defender_label} — BreachReplay Arena Replay`;
    const description = `${replay.archetype_key} · ${replay.difficulty} difficulty · ${
      STATUS_STYLE[replay.status]?.label ?? replay.status.replace(/_/g, " ")
    } · ${replay.action_count} actions`;
    document.title = title;
    setMeta("description", description);
    setMeta("og:title", title, "property");
    setMeta("og:description", description, "property");
    setMeta("og:type", "website", "property");
    setMeta("twitter:card", "summary");
    setMeta("twitter:title", title);
    setMeta("twitter:description", description);
    return () => {
      document.title = "BreachReplay";
    };
  }, [replay]);

  if (isLoading) {
    return (
      <div className="min-h-screen bg-[#040712] flex items-center justify-center">
        <div className="w-8 h-8 border-2 border-cyan-500 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (isError || !replay) {
    return (
      <div className="min-h-screen bg-[#040712] flex items-center justify-center p-6 font-mono">
        <div className="text-center max-w-sm">
          <div className="text-5xl mb-4">⚠</div>
          <h1 className="text-white text-xl font-black mb-2">Replay Not Found</h1>
          <p className="text-gray-500 text-sm mb-6">
            This replay doesn't exist or hasn't finished yet.
          </p>
          <Link to="/" className="text-sm text-cyan-400 hover:text-cyan-300">← Back to BreachReplay</Link>
        </div>
      </div>
    );
  }

  const style = STATUS_STYLE[replay.status] || {
    border: "border-slate-600/50",
    text: "text-slate-400",
    bg: "bg-slate-600/10",
    icon: "•",
    label: replay.status.replace(/_/g, " "),
  };

  return (
    <div className="min-h-screen bg-[#040712] flex flex-col font-mono text-slate-200">
      {/* Top bar */}
      <div className="border-b border-slate-800 bg-slate-950/90 px-5 py-2.5 flex items-center justify-between gap-4">
        <Link to="/" className="text-cyan-500 font-black text-sm uppercase tracking-widest">
          BreachReplay
        </Link>
        <span className={`text-[10px] px-2 py-0.5 rounded border font-bold uppercase tracking-wider ${style.border} ${style.text} ${style.bg}`}>
          {style.icon} {replay.status.replace(/_/g, " ")}
        </span>
      </div>

      <div className="flex-1 overflow-y-auto p-6">
        <div className="max-w-3xl mx-auto space-y-6">
          {/* Summary */}
          <div className="bg-[#090d16]/60 border border-slate-800 rounded-lg p-5">
            <div className="mb-4 border-b border-slate-800 pb-3">
              <span className="text-[10px] text-cyan-500 uppercase tracking-widest font-extrabold block mb-1">
                Arena Match Replay
              </span>
              <h1 className="text-lg font-bold uppercase tracking-wider text-slate-100">
                {replay.archetype_key.replace(/_/g, " ")}
              </h1>
              <p className="text-xs text-slate-500 mt-1">
                {replay.difficulty} difficulty · {replay.mode.replace(/_/g, " ")}
              </p>
            </div>

            <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-4">
              <div>
                <div className="text-[9px] text-slate-600 uppercase tracking-widest mb-1">Attacker</div>
                <div className="text-sm font-bold text-red-400">{replay.attacker_label}</div>
              </div>
              <div>
                <div className="text-[9px] text-slate-600 uppercase tracking-widest mb-1">Defender</div>
                <div className="text-sm font-bold text-blue-400">{replay.defender_label}</div>
              </div>
              <div>
                <div className="text-[9px] text-slate-600 uppercase tracking-widest mb-1">Actions</div>
                <div className="text-sm font-bold text-slate-200">{replay.action_count}</div>
              </div>
              <div>
                <div className="text-[9px] text-slate-600 uppercase tracking-widest mb-1">Outcome</div>
                <div className={`text-sm font-bold ${style.text}`}>{style.label}</div>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-4 text-xs text-slate-500">
              <div>
                <span className="text-slate-600 uppercase text-[9px] tracking-widest block mb-0.5">Started</span>
                {formatDate(replay.started_at)}
              </div>
              <div>
                <span className="text-slate-600 uppercase text-[9px] tracking-widest block mb-0.5">Completed</span>
                {formatDate(replay.completed_at)}
              </div>
            </div>
          </div>

          {/* Global Incident Response Index cross-link */}
          {showCohortCallout && archetypeStats && (
            <div className="bg-[#090d16]/60 border border-cyan-500/30 rounded-lg p-5 text-center">
              <p className="text-lg font-black text-cyan-300">
                {replay.status === "attacker_won"
                  ? `You beat ${(archetypeStats.attacker_win_rate * 100).toFixed(0)}% of defenders on this archetype.`
                  : `You beat ${(archetypeStats.containment_rate * 100).toFixed(0)}% of attackers on this archetype.`}
              </p>
              <p className="text-[11px] text-slate-500 mt-1.5">
                Based on {archetypeStats.decisive_matches} decisive matches worldwide on{" "}
                {replay.archetype_key.replace(/_/g, " ")}.
              </p>
              <Link
                to={`/global-index?archetype=${encodeURIComponent(replay.archetype_key)}`}
                className="inline-block mt-3 text-xs text-cyan-400 hover:text-cyan-300 font-bold uppercase tracking-wider"
              >
                See the full Global Incident Response Index →
              </Link>
            </div>
          )}

          {/* Timeline */}
          <div className="bg-[#090d16]/60 border border-slate-800 rounded-lg p-5">
            <div className="mb-4 border-b border-slate-800 pb-3">
              <span className="text-[10px] text-cyan-500 uppercase tracking-widest font-extrabold block mb-1">
                Action Timeline
              </span>
              <h2 className="text-sm font-bold uppercase tracking-wider text-slate-200">
                {replay.events.length} actions
              </h2>
            </div>

            {replay.events.length === 0 ? (
              <p className="text-xs text-slate-600 text-center py-6">No actions were recorded in this match.</p>
            ) : (
              <div className="space-y-1.5">
                {replay.events.map((ev) => {
                  const isAttacker = ev.actor === "attacker";
                  return (
                    <div
                      key={ev.sequence_number}
                      className="w-full flex items-center gap-3 border border-slate-800 rounded px-3 py-2"
                    >
                      <span className="text-[10px] text-slate-600 w-8 shrink-0">#{ev.sequence_number}</span>
                      <span
                        className={`text-[9px] font-black uppercase px-1.5 py-0.5 rounded shrink-0 ${
                          isAttacker ? "bg-red-600/80 text-white" : "bg-blue-600/80 text-white"
                        }`}
                      >
                        {ev.actor ?? "unknown"}
                      </span>
                      <span className="text-xs text-slate-300 flex-1 truncate">
                        {(ev.action_type ?? "—").replace(/_/g, " ")}
                      </span>
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          <div className="text-center pb-6">
            <Link to="/" className="text-xs text-gray-700 hover:text-gray-400 transition-colors">
              Play your own match at <span className="text-breach-accent font-bold">breachreplay.com</span>
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}
