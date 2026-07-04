import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { axiosInstance } from "../lib/api";

// ── Public, no-auth "Global Incident Response Index" — Live Breach Events
// Phase 3 ─────────────────────────────────────────────────────────────────
// Mirrors PublicReplayPage.tsx's shape for a public, unauthenticated,
// screenshot-friendly page: no AppShell/sidebar, useQuery + axiosInstance,
// loading/error states, OG/Twitter meta tags injected via useEffect. Three
// modes driven entirely by the URL (no client-side mode switcher UI, so the
// page stays link-shareable and screenshot-stable):
//   - overview:  /global-index                       — the full cohort
//   - scenario:  /global-index?scenario={scenario_id} — one ingested incident
//   - archetype: /global-index?archetype={archetype_key} — one Arena archetype
// scenario and archetype pull from two entirely separate backend endpoints
// (GET /scenarios/public/stats/{scenario_id} reads SimulationSession;
// GET /arena/public/stats/global-index reads ArenaMatch) — see this repo's
// backend/app/api/routes/scenarios.py and arena.py docstrings for why those
// were kept as two routes instead of one bolted-together shape.

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

interface ScenarioStats {
  scenario_id: string;
  title: string;
  total_sessions: number;
  rated_sessions: number;
  success_threshold: number;
  success_rate: number;
  avg_decision_accuracy: number | null;
  avg_team_score: number | null;
  generated_at: string;
  cache_ttl_seconds: number;
}

function pct(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return `${(n * 100).toFixed(1)}%`;
}

function minutes(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return `${Math.round(n)}m`;
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

function StatTile({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div className="bg-[#090d16]/60 border border-slate-800 rounded-lg px-4 py-5 text-center">
      <div className={`text-4xl sm:text-5xl font-black leading-none ${color}`}>{value}</div>
      <div className="text-[10px] text-slate-500 uppercase tracking-widest font-bold mt-2">{label}</div>
    </div>
  );
}

function ArchetypeTable({ archetypes, highlight }: { archetypes: GlobalIndexBucket[]; highlight?: string }) {
  if (archetypes.length === 0) {
    return <p className="text-xs text-slate-600 text-center py-6">No arena matches recorded yet.</p>;
  }
  return (
    <div className="space-y-1.5">
      {archetypes.map((a) => {
        const isHighlighted = highlight && a.archetype_key === highlight;
        return (
          <Link
            key={a.archetype_key}
            to={`/global-index?archetype=${encodeURIComponent(a.archetype_key ?? "")}`}
            className={`flex flex-wrap items-center gap-x-4 gap-y-1 rounded px-3 py-2.5 border transition-colors ${
              isHighlighted
                ? "border-cyan-500/60 bg-cyan-500/10"
                : "border-slate-800 hover:border-slate-700 hover:bg-slate-900/40"
            }`}
          >
            <span className="text-xs font-bold uppercase tracking-wider text-slate-200 flex-1 min-w-[140px]">
              {(a.archetype_key ?? "unknown").replace(/_/g, " ")}
            </span>
            <span className="text-[10px] text-green-400 font-bold w-24 text-right">
              {pct(a.containment_rate)} <span className="text-slate-600 font-normal">contained</span>
            </span>
            <span className="text-[10px] text-red-400 font-bold w-24 text-right">
              {pct(a.attacker_win_rate)} <span className="text-slate-600 font-normal">breached</span>
            </span>
            <span className="text-[10px] text-slate-500 w-20 text-right">{a.total_matches} matches</span>
          </Link>
        );
      })}
    </div>
  );
}

function TopBar() {
  return (
    <div className="border-b border-slate-800 bg-slate-950/90 px-5 py-2.5 flex items-center justify-between gap-4">
      <Link to="/" className="text-cyan-500 font-black text-sm uppercase tracking-widest">
        BreachReplay
      </Link>
      <span className="text-[10px] px-2 py-0.5 rounded border border-cyan-500/40 text-cyan-400 bg-cyan-500/10 font-bold uppercase tracking-wider flex items-center gap-1.5">
        <span className="w-1.5 h-1.5 rounded-full bg-cyan-400 animate-pulse" />
        Global Incident Response Index
      </span>
    </div>
  );
}

function NotFoundState({ heading, message }: { heading: string; message: string }) {
  return (
    <div className="min-h-screen bg-[#040712] flex flex-col font-mono text-slate-200">
      <TopBar />
      <div className="flex-1 flex items-center justify-center p-6">
        <div className="text-center max-w-sm">
          <div className="text-5xl mb-4">⚠</div>
          <h1 className="text-white text-xl font-black mb-2">{heading}</h1>
          <p className="text-gray-500 text-sm mb-6">{message}</p>
          <Link to="/global-index" className="text-sm text-cyan-400 hover:text-cyan-300">
            ← View the full Global Index
          </Link>
        </div>
      </div>
    </div>
  );
}

function LoadingState() {
  return (
    <div className="min-h-screen bg-[#040712] flex items-center justify-center">
      <div className="w-8 h-8 border-2 border-cyan-500 border-t-transparent rounded-full animate-spin" />
    </div>
  );
}

export default function GlobalIndexPage() {
  const [searchParams] = useSearchParams();
  const scenarioId = searchParams.get("scenario");
  const archetypeKey = searchParams.get("archetype");
  const mode: "scenario" | "archetype" | "overview" = scenarioId ? "scenario" : archetypeKey ? "archetype" : "overview";

  const {
    data: globalIndex,
    isLoading: globalIndexLoading,
    isError: globalIndexError,
  } = useQuery<GlobalIndexPayload>({
    queryKey: ["global-index"],
    queryFn: () => axiosInstance.get("/arena/public/stats/global-index").then((r) => r.data),
    retry: false,
    enabled: mode !== "scenario",
    staleTime: 60_000,
  });

  const {
    data: scenarioStats,
    isLoading: scenarioLoading,
    isError: scenarioError,
  } = useQuery<ScenarioStats>({
    queryKey: ["scenario-public-stats", scenarioId],
    queryFn: () => axiosInstance.get(`/scenarios/public/stats/${scenarioId}`).then((r) => r.data),
    retry: false,
    enabled: mode === "scenario" && !!scenarioId,
  });

  const archetypeBucket =
    mode === "archetype" ? globalIndex?.archetypes.find((a) => a.archetype_key === archetypeKey) : undefined;

  // Best-effort client-side OG/Twitter tags — same caveat as PublicReplayPage:
  // a plain Vite SPA with no SSR/prerender, so this mainly helps JS-executing
  // unfurlers and sets the tab title/description for viewers themselves.
  useEffect(() => {
    let title = "Global Incident Response Index — BreachReplay";
    let description =
      "How the world is doing against real breach archetypes — live containment and attacker win rates from Live Arena Mode.";

    if (mode === "scenario" && scenarioStats) {
      title = `${scenarioStats.title} — Global Incident Response Index`;
      description = `${pct(scenarioStats.success_rate)} of defenders worldwide successfully contained "${scenarioStats.title}" (${scenarioStats.total_sessions} sessions played).`;
    } else if (mode === "archetype" && archetypeBucket) {
      const label = (archetypeBucket.archetype_key ?? archetypeKey ?? "").replace(/_/g, " ");
      title = `${label} — Global Incident Response Index`;
      description = `${pct(archetypeBucket.containment_rate)} containment rate across ${archetypeBucket.total_matches} arena matches worldwide on ${label}.`;
    } else if (mode === "overview" && globalIndex) {
      description = `${pct(globalIndex.overall.containment_rate)} global containment rate across ${globalIndex.overall.total_matches} arena matches worldwide.`;
    }

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
  }, [mode, scenarioStats, archetypeBucket, globalIndex, archetypeKey]);

  // ── Scenario-focused mode ──────────────────────────────────────────────
  if (mode === "scenario") {
    if (scenarioLoading) return <LoadingState />;
    if (scenarioError || !scenarioStats) {
      return (
        <NotFoundState
          heading="Incident Not Found"
          message="This incident doesn't exist, isn't public yet, or has been removed."
        />
      );
    }

    const noData = scenarioStats.rated_sessions === 0;

    return (
      <div className="min-h-screen bg-[#040712] flex flex-col font-mono text-slate-200">
        <TopBar />
        <div className="flex-1 overflow-y-auto p-6">
          <div className="max-w-2xl mx-auto space-y-8">
            <div className="text-center pt-4">
              <span className="text-[10px] text-cyan-500 uppercase tracking-widest font-extrabold block mb-2">
                This Incident
              </span>
              <h1 className="text-lg sm:text-xl font-bold uppercase tracking-wider text-slate-100">
                {scenarioStats.title}
              </h1>
            </div>

            {noData ? (
              <div className="text-center py-10">
                <p className="text-slate-500 text-sm">
                  No one has completed this incident yet — be the first to test your defenses.
                </p>
              </div>
            ) : (
              <>
                <div className="text-center">
                  <div className="text-6xl sm:text-7xl font-black leading-none text-green-400">
                    {pct(scenarioStats.success_rate)}
                  </div>
                  <p className="text-sm text-slate-400 mt-3">
                    of defenders worldwide successfully contained this incident
                  </p>
                  <p className="text-[11px] text-slate-600 mt-1">
                    {scenarioStats.rated_sessions} rated of {scenarioStats.total_sessions} sessions played · success ={" "}
                    {Math.round(scenarioStats.success_threshold * 100)}%+ decision accuracy
                  </p>
                </div>

                <div className="grid grid-cols-2 gap-4">
                  <StatTile
                    label="Avg Decision Accuracy"
                    value={pct(scenarioStats.avg_decision_accuracy)}
                    color="text-cyan-400"
                  />
                  <StatTile
                    label="Avg Team Score"
                    value={scenarioStats.avg_team_score != null ? String(Math.round(scenarioStats.avg_team_score)) : "—"}
                    color="text-slate-300"
                  />
                </div>
              </>
            )}

            <div className="text-center pb-6">
              <Link to="/global-index" className="text-xs text-cyan-400 hover:text-cyan-300">
                ← View the full Global Incident Response Index
              </Link>
            </div>
          </div>
        </div>
      </div>
    );
  }

  // ── Archetype-focused mode ─────────────────────────────────────────────
  if (mode === "archetype") {
    if (globalIndexLoading) return <LoadingState />;
    if (globalIndexError || !globalIndex) {
      return (
        <NotFoundState heading="Index Unavailable" message="Couldn't load the Global Incident Response Index right now." />
      );
    }

    if (!archetypeBucket || archetypeBucket.total_matches === 0) {
      return (
        <div className="min-h-screen bg-[#040712] flex flex-col font-mono text-slate-200">
          <TopBar />
          <div className="flex-1 flex items-center justify-center p-6">
            <div className="text-center max-w-sm">
              <p className="text-slate-500 text-sm mb-6">
                No arena matches recorded yet for "{(archetypeKey ?? "").replace(/_/g, " ")}".
              </p>
              <Link to="/global-index" className="text-sm text-cyan-400 hover:text-cyan-300">
                ← View the full Global Index
              </Link>
            </div>
          </div>
        </div>
      );
    }

    return (
      <div className="min-h-screen bg-[#040712] flex flex-col font-mono text-slate-200">
        <TopBar />
        <div className="flex-1 overflow-y-auto p-6">
          <div className="max-w-2xl mx-auto space-y-8">
            <div className="text-center pt-4">
              <span className="text-[10px] text-cyan-500 uppercase tracking-widest font-extrabold block mb-2">
                This Archetype
              </span>
              <h1 className="text-lg sm:text-xl font-bold uppercase tracking-wider text-slate-100">
                {(archetypeBucket.archetype_key ?? "").replace(/_/g, " ")}
              </h1>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <StatTile label="Containment Rate" value={pct(archetypeBucket.containment_rate)} color="text-green-400" />
              <StatTile label="Attacker Win Rate" value={pct(archetypeBucket.attacker_win_rate)} color="text-red-400" />
            </div>

            <p className="text-[11px] text-slate-600 text-center">
              {archetypeBucket.total_matches} matches played · {archetypeBucket.abandoned_count} abandoned · avg
              resolution {minutes(archetypeBucket.avg_resolution_minutes)}
            </p>

            <div className="bg-[#090d16]/60 border border-slate-800 rounded-lg p-5">
              <span className="text-[10px] text-cyan-500 uppercase tracking-widest font-extrabold block mb-3">
                All Archetypes
              </span>
              <ArchetypeTable archetypes={globalIndex.archetypes} highlight={archetypeBucket.archetype_key} />
            </div>

            <div className="text-center pb-6">
              <Link to="/global-index" className="text-xs text-cyan-400 hover:text-cyan-300">
                ← View the full Global Incident Response Index
              </Link>
            </div>
          </div>
        </div>
      </div>
    );
  }

  // ── Overview mode ───────────────────────────────────────────────────────
  if (globalIndexLoading) return <LoadingState />;
  if (globalIndexError || !globalIndex) {
    return (
      <NotFoundState heading="Index Unavailable" message="Couldn't load the Global Incident Response Index right now." />
    );
  }

  const { overall } = globalIndex;

  return (
    <div className="min-h-screen bg-[#040712] flex flex-col font-mono text-slate-200">
      <TopBar />
      <div className="flex-1 overflow-y-auto p-6">
        <div className="max-w-2xl mx-auto space-y-8">
          <div className="text-center pt-4">
            <span className="text-[10px] text-cyan-500 uppercase tracking-widest font-extrabold block mb-2">
              Global Incident Response Index
            </span>
            <h1 className="text-xl sm:text-2xl font-black uppercase tracking-wide text-slate-100 mb-2">
              How The World Is Doing
            </h1>
            <p className="text-xs text-slate-500">
              {overall.total_matches} Live Arena matches played worldwide · updated every{" "}
              {Math.max(1, Math.round(globalIndex.cache_ttl_seconds / 60))} min
            </p>
          </div>

          {overall.total_matches === 0 ? (
            <p className="text-slate-500 text-sm text-center py-10">
              No arena matches recorded yet. Be the first to make history.
            </p>
          ) : (
            <>
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-4">
                <StatTile label="Containment Rate" value={pct(overall.containment_rate)} color="text-green-400" />
                <StatTile label="Attacker Win Rate" value={pct(overall.attacker_win_rate)} color="text-red-400" />
                <StatTile
                  label="Avg Resolution"
                  value={minutes(overall.avg_resolution_minutes)}
                  color="text-cyan-400"
                />
              </div>

              <div className="bg-[#090d16]/60 border border-slate-800 rounded-lg p-5">
                <span className="text-[10px] text-cyan-500 uppercase tracking-widest font-extrabold block mb-3">
                  By Archetype
                </span>
                <ArchetypeTable archetypes={globalIndex.archetypes} />
              </div>
            </>
          )}

          <div className="text-center pb-6">
            <Link to="/" className="text-xs text-gray-700 hover:text-gray-400 transition-colors">
              Play your own match at <span className="text-cyan-500 font-bold">breachreplay.com</span>
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}
