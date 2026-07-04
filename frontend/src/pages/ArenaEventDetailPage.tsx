import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, axiosInstance } from "../lib/api";
import { useAuthStore } from "../store/auth";
import { parseUtc } from "../lib/utcDate";

// ── Live Breach Events Phase 4 — event detail / live status page ───────────
//
// Public, no-auth READ (GET /arena/events/{id}/status has no auth guard —
// see arena.py's Phase 4 section comment: an event's live leaderboard is
// deliberately public, "itself good shareable content" per the plan). The
// JOIN action, however, calls POST /arena/queue/join which IS auth-gated
// (get_current_user) — so this page renders fully for an anonymous visitor,
// but swaps the join button for a "log in to join" prompt if there's no
// token, rather than firing a call that would 401. There's no existing
// precedent elsewhere in this app for "public page, auth-gated action" (every
// other public page — PublicReplayPage, GlobalIndexPage — is pure read-only),
// so this is the first one; the pattern chosen is the simplest one that
// degrades gracefully.
//
// Polling: mirrors ArenaLobbyPage.tsx's pollRef/queuePollRef convention
// exactly (setInterval + useRef + cleanup on unmount) rather than
// react-query, per the plan's explicit instruction to reuse that convention
// for this page.

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

interface MatchSummary {
  id: string;
  mode: string;
  archetype_key: string;
  difficulty: string;
  status: string;
  attacker_user_id: string | null;
  defender_user_id: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string | null;
  event_id: string | null;
}

interface LeaderboardEntry {
  match_id: string;
  user_id: string | null;
  display_name: string;
  won: boolean;
  winner_role: "attacker" | "defender";
  resolution_seconds: number;
}

interface EventStatusResponse {
  event: EventSummary;
  joined_count: number;
  matches: MatchSummary[];
  leaderboard: LeaderboardEntry[];
}

interface QueueStatusResponse {
  status: "not_queued" | "waiting" | "matched";
  match_id: string | null;
  estimated_wait_seconds: number | null;
}

const _COMPLETED_MATCH_STATUSES = ["attacker_won", "defender_won", "abandoned"];

const STATUS_META: Record<string, { label: string; color: string; dot: string }> = {
  scheduled: { label: "Upcoming", color: "text-cyan-400 border-cyan-500/40 bg-cyan-500/10", dot: "bg-cyan-400" },
  live: { label: "Live Now", color: "text-red-400 border-red-500/40 bg-red-500/10", dot: "bg-red-400 animate-pulse" },
  completed: { label: "Completed", color: "text-gray-400 border-gray-700 bg-gray-800/40", dot: "bg-gray-500" },
  cancelled: { label: "Cancelled", color: "text-gray-600 border-gray-800 bg-gray-900/40", dot: "bg-gray-700" },
};

function pad(n: number) {
  return String(n).padStart(2, "0");
}

function CountdownClock({ targetIso }: { targetIso: string }) {
  const [remainingMs, setRemainingMs] = useState(() => parseUtc(targetIso).getTime() - Date.now());

  useEffect(() => {
    const t = setInterval(() => setRemainingMs(parseUtc(targetIso).getTime() - Date.now()), 1000);
    return () => clearInterval(t);
  }, [targetIso]);

  if (remainingMs <= 0) {
    return <span className="text-cyan-400 animate-pulse">Starting any moment...</span>;
  }

  const totalSeconds = Math.floor(remainingMs / 1000);
  const days = Math.floor(totalSeconds / 86400);
  const hours = Math.floor((totalSeconds % 86400) / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;

  return (
    <span className="font-mono text-3xl sm:text-4xl font-black text-cyan-400 tracking-wide">
      {days > 0 && `${days}d `}
      {pad(hours)}:{pad(minutes)}:{pad(seconds)}
    </span>
  );
}

function formatLocal(iso: string): string {
  return parseUtc(iso).toLocaleString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function TopBar() {
  return (
    <div className="border-b border-gray-800 bg-gray-950/90 px-5 py-2.5 flex items-center justify-between gap-4">
      <Link to="/" className="text-cyan-500 font-black text-sm uppercase tracking-widest">
        BreachReplay
      </Link>
      <Link
        to="/arena/events"
        className="text-[10px] px-2 py-0.5 rounded border border-gray-700 text-gray-400 hover:text-gray-200 hover:border-gray-500 font-bold uppercase tracking-wider transition-colors"
      >
        ← All Events
      </Link>
    </div>
  );
}

export default function ArenaEventDetailPage() {
  const { eventId } = useParams<{ eventId: string }>();
  const navigate = useNavigate();
  const { token, user } = useAuthStore();

  const [data, setData] = useState<EventStatusResponse | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [loading, setLoading] = useState(true);

  const [joinFlow, setJoinFlow] = useState<"idle" | "waiting" | "error">("idle");
  const [joinError, setJoinError] = useState<string | null>(null);
  const [estimatedWait, setEstimatedWait] = useState<number | null>(null);

  const statusPollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const queuePollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  async function fetchStatus() {
    if (!eventId) return;
    try {
      const resp = await axiosInstance.get<EventStatusResponse>(`/arena/events/${eventId}/status`);
      setData(resp.data);
      setNotFound(false);
    } catch (err: any) {
      if (err?.response?.status === 404) setNotFound(true);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    fetchStatus();
    // Poll every 4s — matches ArenaLobbyPage's Quick Match cadence. A live
    // event's joined_count/leaderboard changes as matches resolve, and this
    // same endpoint opportunistically drains the AI-fallback queue once the
    // join window closes (see arena.py docstring), so polling here also
    // helps that happen promptly for anyone with this page open.
    statusPollRef.current = setInterval(fetchStatus, 4000);
    return () => {
      if (statusPollRef.current) clearInterval(statusPollRef.current);
      if (queuePollRef.current) clearInterval(queuePollRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [eventId]);

  async function handleJoin() {
    if (!eventId) return;
    setJoinError(null);
    setJoinFlow("waiting");
    try {
      const resp = await api.post<QueueStatusResponse>(
        `/arena/queue/join?event_id=${encodeURIComponent(eventId)}`,
        {}
      );
      if (resp.status === "matched" && resp.match_id) {
        navigate(`/arena/match/${resp.match_id}`);
        return;
      }
      setEstimatedWait(resp.estimated_wait_seconds);
      queuePollRef.current = setInterval(async () => {
        try {
          const s = await api.get<QueueStatusResponse>("/arena/queue/status");
          if (s.status === "matched" && s.match_id) {
            if (queuePollRef.current) clearInterval(queuePollRef.current);
            navigate(`/arena/match/${s.match_id}`);
          } else {
            setEstimatedWait(s.estimated_wait_seconds);
          }
        } catch {
          // transient — keep polling
        }
      }, 3000);
    } catch (e: any) {
      setJoinError(e.message || "Failed to join this event's queue");
      setJoinFlow("error");
    }
  }

  async function handleLeaveQueue() {
    if (queuePollRef.current) clearInterval(queuePollRef.current);
    setJoinFlow("idle");
    try {
      await api.delete("/arena/queue/leave");
    } catch {
      // best-effort, same as ArenaLobbyPage's handleCancelQueue
    }
  }

  if (loading) {
    return (
      <div className="min-h-screen bg-gray-950 flex items-center justify-center">
        <div className="w-8 h-8 border-2 border-cyan-500 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (notFound || !data) {
    return (
      <div className="min-h-screen bg-gray-950 text-white flex flex-col">
        <TopBar />
        <div className="flex-1 flex items-center justify-center p-6">
          <div className="text-center max-w-sm">
            <div className="text-5xl mb-4">⚠</div>
            <h1 className="text-xl font-black mb-2">Event Not Found</h1>
            <p className="text-gray-500 text-sm mb-6">
              This Live Breach Event doesn't exist or has been removed.
            </p>
            <Link to="/arena/events" className="text-sm text-cyan-400 hover:text-cyan-300">
              ← View all events
            </Link>
          </div>
        </div>
      </div>
    );
  }

  const { event, joined_count, matches, leaderboard } = data;
  const statusMeta = STATUS_META[event.status] ?? STATUS_META.scheduled;

  // Has the current authed user already got a match under this event?
  const myMatch = user
    ? matches.find((m) => m.attacker_user_id === user.id || m.defender_user_id === user.id)
    : undefined;
  const myMatchIsLive = myMatch && !_COMPLETED_MATCH_STATUSES.includes(myMatch.status);

  const decisiveMatches = matches.filter((m) => m.status === "attacker_won" || m.status === "defender_won").length;

  return (
    <div className="min-h-screen bg-gray-950 text-white flex flex-col">
      <TopBar />
      <div className="flex-1 overflow-y-auto px-4 py-10">
        <div className="max-w-2xl mx-auto space-y-8">
          {/* Header */}
          <div className="text-center">
            <span
              className={`inline-flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-widest border rounded px-2 py-1 mb-4 ${statusMeta.color}`}
            >
              <span className={`w-1.5 h-1.5 rounded-full ${statusMeta.dot}`} />
              {statusMeta.label}
            </span>
            <h1 className="text-2xl sm:text-3xl font-black text-white mb-2">{event.title}</h1>
            <p className="text-xs text-gray-500 uppercase tracking-wider">
              {event.archetype_key.replace(/_/g, " ")} · {event.difficulty} difficulty
            </p>
            <p className="text-xs text-gray-600 mt-1">
              {formatLocal(event.starts_at)} — {formatLocal(event.ends_at)} (your local time)
            </p>
          </div>

          {/* Scheduled: countdown */}
          {event.status === "scheduled" && (
            <div className="text-center border border-gray-800 rounded-xl p-8 bg-gray-900/40">
              <div className="text-[10px] text-gray-500 uppercase tracking-widest mb-3">Starts In</div>
              <CountdownClock targetIso={event.starts_at} />
              <p className="text-xs text-gray-600 mt-4">{joined_count} player{joined_count !== 1 ? "s" : ""} already joined</p>
            </div>
          )}

          {/* Live: joined count + leaderboard */}
          {event.status === "live" && (
            <div className="border border-red-500/30 rounded-xl p-6 bg-red-500/5 text-center">
              <div className="text-4xl font-black text-red-400">{joined_count}</div>
              <div className="text-[10px] text-gray-500 uppercase tracking-widest mt-1">Players Joined</div>
              <div className="text-xs text-gray-500 mt-3">{decisiveMatches} of {matches.length} matches resolved</div>
            </div>
          )}

          {/* Completed: recap */}
          {event.status === "completed" && (
            <div className="border border-gray-800 rounded-xl p-6 bg-gray-900/40 text-center">
              <div className="text-4xl font-black text-gray-300">{joined_count}</div>
              <div className="text-[10px] text-gray-500 uppercase tracking-widest mt-1">Players Took Part</div>
              <div className="text-xs text-gray-500 mt-3">{decisiveMatches} of {matches.length} matches resolved</div>
            </div>
          )}

          {event.status === "cancelled" && (
            <div className="border border-gray-800 rounded-xl p-6 bg-gray-900/40 text-center text-gray-500 text-sm">
              This event has been cancelled.
            </div>
          )}

          {/* Leaderboard — live or completed only (matches the plan's "once
              status is live" framing; also shown once completed since a
              finished event's leaderboard is exactly the kind of shareable
              recap this phase is for). */}
          {(event.status === "live" || event.status === "completed") && (
            <div className="border border-gray-800 rounded-xl bg-gray-900/40 overflow-hidden">
              <div className="px-5 py-3 border-b border-gray-800">
                <h2 className="text-xs font-bold uppercase tracking-widest text-gray-400">
                  🏆 Fastest Wins
                </h2>
              </div>
              {leaderboard.length === 0 ? (
                <p className="text-xs text-gray-600 text-center py-8">
                  No matches have resolved yet — check back shortly.
                </p>
              ) : (
                <div className="divide-y divide-gray-800/60">
                  {leaderboard.map((entry, i) => (
                    <div key={entry.match_id} className="flex items-center gap-3 px-5 py-3 text-xs">
                      <span className="w-6 text-gray-600 font-mono">{i + 1}</span>
                      <span className="flex-1 font-semibold text-gray-200 truncate">{entry.display_name}</span>
                      <span
                        className={`text-[9px] font-bold uppercase tracking-widest px-1.5 py-0.5 rounded border ${
                          entry.winner_role === "attacker"
                            ? "text-red-400 border-red-500/30 bg-red-500/10"
                            : "text-green-400 border-green-500/30 bg-green-500/10"
                        }`}
                      >
                        {entry.winner_role}
                      </span>
                      <span className="text-gray-500 font-mono w-16 text-right">
                        {Math.round(entry.resolution_seconds)}s
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Join panel — only meaningful while an event can still be joined */}
          {(event.status === "scheduled" || event.status === "live") && (
            <div className="border border-cyan-500/30 rounded-xl p-6 bg-cyan-500/5 text-center">
              {!token ? (
                <>
                  <p className="text-sm text-gray-300 mb-4">Log in to join this event's matchmaking queue.</p>
                  <Link
                    to="/login"
                    className="inline-block px-6 py-2.5 rounded-lg bg-cyan-600 hover:bg-cyan-500 text-white font-bold text-sm uppercase tracking-wider transition-colors"
                  >
                    Log In to Join
                  </Link>
                </>
              ) : myMatchIsLive && myMatch ? (
                <>
                  <p className="text-sm text-gray-300 mb-4">You're already in this event's match.</p>
                  <button
                    onClick={() => navigate(`/arena/match/${myMatch.id}`)}
                    className="px-6 py-2.5 rounded-lg bg-cyan-600 hover:bg-cyan-500 text-white font-bold text-sm uppercase tracking-wider transition-colors"
                  >
                    ⚔️ Go To Your Match
                  </button>
                </>
              ) : myMatch ? (
                <p className="text-sm text-gray-500">
                  You already played this event ({myMatch.status.replace(/_/g, " ")}).
                </p>
              ) : joinFlow === "waiting" ? (
                <>
                  <div className="flex items-center justify-center gap-2 text-xs text-cyan-400 mb-2">
                    <div className="w-2 h-2 rounded-full bg-cyan-400 animate-ping" />
                    Waiting for an opponent...
                  </div>
                  {estimatedWait !== null && (
                    <p className="text-[10px] text-gray-600 mb-4">Estimated wait: ~{estimatedWait}s</p>
                  )}
                  <button
                    onClick={handleLeaveQueue}
                    className="text-xs text-gray-500 hover:text-gray-300 transition-colors"
                  >
                    Leave queue
                  </button>
                </>
              ) : (
                <>
                  <p className="text-sm text-gray-300 mb-4">
                    Join the queue now — you'll be paired with another player (or an AI opponent once the window
                    closes) at this event's fixed seed and difficulty.
                  </p>
                  {joinError && <p className="text-xs text-red-400 mb-3">{joinError}</p>}
                  <button
                    onClick={handleJoin}
                    className="px-6 py-2.5 rounded-lg bg-cyan-600 hover:bg-cyan-500 text-white font-bold text-sm uppercase tracking-wider transition-colors"
                  >
                    ⚔️ Join This Event
                  </button>
                </>
              )}
            </div>
          )}

          <div className="text-center pb-6">
            <Link to="/arena/events" className="text-xs text-gray-700 hover:text-gray-400 transition-colors">
              ← View all Live Breach Events
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}
