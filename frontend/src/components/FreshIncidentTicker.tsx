import { useQuery } from "@tanstack/react-query";
import { useNavigate, Link } from "react-router-dom";
import { api, axiosInstance } from "../lib/api";
import { parseUtc } from "../lib/utcDate";

// ── Live Breach Events Phase 2 — Fresh Incident Ticker ──────────────────────
// "Breaking news" strip surfacing the newest approved, non-private scenarios
// so users see "new real incident, be among the first to play it" the moment
// they land on the library. Uses React Query with a 5min staleTime (matches
// the weekly ingestion cadence per the plan) even though the surrounding
// ScenarioLibraryPage still uses plain useState/useEffect for its own fetch —
// see PublicReplayPage.tsx for this codebase's existing useQuery convention
// (axiosInstance + queryKey array) that this component follows.

interface RecentScenario {
  id: string;
  title: string;
  source_type: string;
  source_reference: string | null;
  industry_vertical: string | null;
  created_at: string;
}

const SOURCE_ICON: Record<string, string> = {
  cisa: "🛰",
  sec_8k: "📄",
  hhs: "🏥",
  verizon_dbir: "📊",
  private: "🔒",
  manual: "✍",
};

function timeAgo(iso: string): string {
  // Backend serializes created_at (a naive UTC datetime column) without a
  // timezone suffix — new Date() would otherwise parse it as local time,
  // skewing "time ago" by the viewer's UTC offset. parseUtc() (lib/utcDate.ts)
  // was extracted from this exact logic for reuse by the Phase 4 event pages.
  const diffMs = Date.now() - parseUtc(iso).getTime();
  const minutes = Math.floor(diffMs / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days}d ago`;
  const weeks = Math.floor(days / 7);
  return `${weeks}w ago`;
}

export default function FreshIncidentTicker() {
  const navigate = useNavigate();

  const { data: scenarios } = useQuery<RecentScenario[]>({
    queryKey: ["scenarios-recent"],
    queryFn: () => axiosInstance.get("/scenarios/recent").then((r) => r.data),
    staleTime: 5 * 60 * 1000, // 5 minutes — matches weekly ingestion cadence
  });

  // Deep-link behavior: this app has no standalone /scenario/:id detail
  // route (scenarios are only ever browsed as cards in ScenarioLibraryPage's
  // grid, then launched directly into a session). So the truest "deep-link
  // into the scenario" this app supports is the same action the library
  // cards' "Launch Simulation" button performs — start a solo session and
  // jump straight into it. That keeps the ticker's click behavior consistent
  // with the rest of the page rather than inventing a new navigation target.
  async function launch(scenarioId: string) {
    try {
      const session = await api.post<{ id: string }>("/sessions", {
        scenario_id: scenarioId,
        mode: "solo",
      });
      navigate(`/session/${session.id}/intro`);
    } catch (err: any) {
      alert(err.message);
    }
  }

  if (!scenarios || scenarios.length === 0) return null;

  return (
    <div className="mb-6 flex items-center gap-3 overflow-x-auto bg-breach-surface border border-breach-border rounded-lg px-3 py-2.5">
      <span className="shrink-0 flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-widest text-breach-accent border border-breach-accent/40 bg-breach-accent/10 rounded px-2 py-1">
        <span className="w-1.5 h-1.5 rounded-full bg-breach-accent animate-pulse" />
        Breaking
      </span>
      <div className="flex items-center gap-2 overflow-x-auto">
        {scenarios.map((s) => (
          <div
            key={s.id}
            className="shrink-0 flex items-center gap-2 bg-breach-bg hover:bg-breach-border/40 border border-breach-border hover:border-breach-blue rounded-full pl-3 pr-1.5 py-1.5 transition-colors"
          >
            <button onClick={() => launch(s.id)} title={`Play ${s.title}`} className="flex items-center gap-2">
              <span className="text-[9px] font-bold uppercase tracking-widest text-breach-green bg-breach-green/10 border border-breach-green/30 rounded px-1.5 py-0.5">
                New
              </span>
              <span className="text-xs" aria-hidden>
                {SOURCE_ICON[s.source_type] ?? "⚡"}
              </span>
              <span className="text-xs font-medium text-breach-text max-w-[220px] truncate">{s.title}</span>
              <span className="text-[10px] text-breach-muted">{timeAgo(s.created_at)}</span>
            </button>
            <Link
              to={`/global-index?scenario=${encodeURIComponent(s.id)}`}
              title="See how the world is doing against this incident"
              className="shrink-0 text-[9px] font-bold uppercase tracking-widest text-breach-blue hover:text-breach-text border-l border-breach-border pl-1.5 ml-0.5"
            >
              Global Stats →
            </Link>
          </div>
        ))}
      </div>
    </div>
  );
}
