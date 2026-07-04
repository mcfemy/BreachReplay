import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { axiosInstance } from "../lib/api";
import { parseUtc } from "../lib/utcDate";

// ── Live Breach Events Phase 4 — public events browser ──────────────────────
//
// Public, no-auth, no AppShell — mirrors GlobalIndexPage.tsx's shape for a
// screenshot-friendly public page (dark, monospace, minimal chrome). Fetches
// `GET /arena/events` — a NEW public listing endpoint added alongside this
// frontend work (backend/app/api/routes/arena.py). It didn't exist before:
// the only pre-existing listing route was `GET /admin/arena/events`
// (admin.py), which requires `require_admin` and can't serve a public browse
// page. The new route is deliberately minimal — read-only, no auth, reuses
// the exact same `arena_event_summary()` serializer the admin route and
// `GET /arena/events/{id}/status` already use, so all three never drift on
// shape (same precedent as `_COMPLETED_STATUSES`/`_compute_archetype_bucket`
// elsewhere in arena.py).

interface EventSummary {
  id: string;
  title: string;
  scenario_id: string | null;
  archetype_key: string;
  difficulty: "easy" | "medium" | "hard";
  seed: number;
  starts_at: string;
  ends_at: string;
  status: "scheduled" | "live" | "completed" | "cancelled";
  created_at: string;
}

const DIFF_COLOR: Record<string, string> = {
  easy: "text-green-400 border-green-500/40 bg-green-500/10",
  medium: "text-yellow-400 border-yellow-500/40 bg-yellow-500/10",
  hard: "text-red-400 border-red-500/40 bg-red-500/10",
};

const STATUS_META: Record<string, { label: string; color: string; dot: string }> = {
  scheduled: { label: "Upcoming", color: "text-cyan-400 border-cyan-500/40 bg-cyan-500/10", dot: "bg-cyan-400" },
  live: { label: "Live Now", color: "text-red-400 border-red-500/40 bg-red-500/10", dot: "bg-red-400 animate-pulse" },
  completed: { label: "Completed", color: "text-gray-400 border-gray-700 bg-gray-800/40", dot: "bg-gray-500" },
  cancelled: { label: "Cancelled", color: "text-gray-600 border-gray-800 bg-gray-900/40", dot: "bg-gray-700" },
};

function formatLocal(iso: string): string {
  return parseUtc(iso).toLocaleString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function timeUntil(iso: string, now: number): string {
  const diffMs = parseUtc(iso).getTime() - now;
  if (diffMs <= 0) return "starting now";
  const mins = Math.floor(diffMs / 60000);
  if (mins < 60) return `in ${mins}m`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `in ${hours}h ${mins % 60}m`;
  const days = Math.floor(hours / 24);
  return `in ${days}d ${hours % 24}h`;
}

function EventCard({ event, now }: { event: EventSummary; now: number }) {
  const statusMeta = STATUS_META[event.status] ?? STATUS_META.scheduled;
  return (
    <Link
      to={`/arena/events/${event.id}`}
      className="block border border-gray-800 hover:border-cyan-500/50 bg-gray-900/40 hover:bg-gray-900/70 rounded-xl p-5 transition-all"
    >
      <div className="flex items-start justify-between gap-3 mb-3">
        <h3 className="text-sm font-bold text-white leading-snug">{event.title}</h3>
        <span
          className={`shrink-0 flex items-center gap-1.5 text-[9px] font-bold uppercase tracking-widest border rounded px-2 py-1 ${statusMeta.color}`}
        >
          <span className={`w-1.5 h-1.5 rounded-full ${statusMeta.dot}`} />
          {statusMeta.label}
        </span>
      </div>
      <div className="flex flex-wrap items-center gap-2 mb-3">
        <span className="text-[10px] text-gray-500 uppercase tracking-wider">
          {event.archetype_key.replace(/_/g, " ")}
        </span>
        <span
          className={`text-[9px] font-bold uppercase tracking-widest border rounded px-1.5 py-0.5 ${
            DIFF_COLOR[event.difficulty] ?? DIFF_COLOR.medium
          }`}
        >
          {event.difficulty}
        </span>
      </div>
      <div className="text-xs text-gray-400">{formatLocal(event.starts_at)}</div>
      {event.status === "scheduled" && (
        <div className="text-[10px] text-cyan-500 font-bold mt-1">{timeUntil(event.starts_at, now)}</div>
      )}
    </Link>
  );
}

function TopBar() {
  return (
    <div className="border-b border-gray-800 bg-gray-950/90 px-5 py-2.5 flex items-center justify-between gap-4">
      <Link to="/" className="text-cyan-500 font-black text-sm uppercase tracking-widest">
        BreachReplay
      </Link>
      <span className="text-[10px] px-2 py-0.5 rounded border border-red-500/40 text-red-400 bg-red-500/10 font-bold uppercase tracking-wider flex items-center gap-1.5">
        <span className="w-1.5 h-1.5 rounded-full bg-red-400 animate-pulse" />
        Live Breach Events
      </span>
    </div>
  );
}

type FilterTab = "all" | "live" | "scheduled" | "completed";

export default function ArenaEventsPage() {
  const [filter, setFilter] = useState<FilterTab>("all");
  const [now, setNow] = useState(() => Date.now());

  // Refresh relative "starts in Xh Ym" text every 30s — no need for a
  // per-second ticker on a browse/list page (the detail page's countdown is
  // where a real to-the-second clock matters).
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 30_000);
    return () => clearInterval(t);
  }, []);

  useEffect(() => {
    document.title = "Live Breach Events — BreachReplay";
  }, []);

  const { data: events, isLoading, isError } = useQuery<EventSummary[]>({
    queryKey: ["arena-events"],
    queryFn: () => axiosInstance.get("/arena/events").then((r) => r.data),
    retry: false,
    refetchInterval: 30_000,
  });

  const live = (events ?? []).filter((e) => e.status === "live");
  const upcoming = (events ?? [])
    .filter((e) => e.status === "scheduled")
    .sort((a, b) => parseUtc(a.starts_at).getTime() - parseUtc(b.starts_at).getTime());
  const past = (events ?? [])
    .filter((e) => e.status === "completed" || e.status === "cancelled")
    .sort((a, b) => parseUtc(b.starts_at).getTime() - parseUtc(a.starts_at).getTime());

  const sections: { key: FilterTab; label: string; items: EventSummary[] }[] = [
    { key: "live", label: `Live Now (${live.length})`, items: live },
    { key: "scheduled", label: `Upcoming (${upcoming.length})`, items: upcoming },
    { key: "completed", label: `Past Events (${past.length})`, items: past },
  ];

  const visibleSections = filter === "all" ? sections : sections.filter((s) => s.key === filter);

  return (
    <div className="min-h-screen bg-gray-950 text-white flex flex-col">
      <TopBar />
      <div className="flex-1 overflow-y-auto px-4 py-10">
        <div className="max-w-4xl mx-auto">
          <div className="text-center mb-10">
            <div className="text-5xl mb-4">🔴</div>
            <h1 className="text-3xl sm:text-4xl font-black text-white mb-3">Live Breach Events</h1>
            <p className="text-gray-400 text-sm max-w-xl mx-auto">
              Scheduled, synchronized live Arena matches — everyone plays the identical seed at the same time and
              watches a shared leaderboard tick as matches resolve.
            </p>
          </div>

          <div className="flex items-center justify-center gap-2 mb-8 flex-wrap">
            {(["all", "live", "scheduled", "completed"] as FilterTab[]).map((f) => (
              <button
                key={f}
                onClick={() => setFilter(f)}
                className={`text-[10px] font-bold uppercase tracking-widest px-3 py-1.5 rounded border transition-colors ${
                  filter === f
                    ? "border-cyan-500 bg-cyan-500/10 text-cyan-300"
                    : "border-gray-800 text-gray-500 hover:border-gray-600"
                }`}
              >
                {f === "all" ? "All" : f === "scheduled" ? "Upcoming" : f === "live" ? "Live" : "Past"}
              </button>
            ))}
          </div>

          {isLoading && (
            <div className="flex items-center justify-center py-20">
              <div className="w-8 h-8 border-2 border-cyan-500 border-t-transparent rounded-full animate-spin" />
            </div>
          )}

          {isError && (
            <div className="border border-red-500/40 bg-red-500/10 rounded-lg p-4 text-sm text-red-300 text-center">
              Couldn't load Live Breach Events right now.
            </div>
          )}

          {!isLoading && !isError && (events ?? []).length === 0 && (
            <p className="text-center text-sm text-gray-500 py-16">
              No Live Breach Events scheduled yet — check back soon.
            </p>
          )}

          {!isLoading &&
            !isError &&
            visibleSections.map(
              (section) =>
                section.items.length > 0 && (
                  <div key={section.key} className="mb-10">
                    <h2 className="text-xs font-bold uppercase tracking-widest text-gray-500 mb-3">
                      {section.label}
                    </h2>
                    <div className="grid gap-3 sm:grid-cols-2">
                      {section.items.map((event) => (
                        <EventCard key={event.id} event={event} now={now} />
                      ))}
                    </div>
                  </div>
                )
            )}

          {!isLoading &&
            !isError &&
            (events ?? []).length > 0 &&
            visibleSections.every((s) => s.items.length === 0) && (
              <p className="text-center text-sm text-gray-500 py-16">No events in this view.</p>
            )}

          <div className="text-center pt-4">
            <Link to="/arena" className="text-xs text-gray-700 hover:text-gray-400 transition-colors">
              ← Back to Live Arena
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}
