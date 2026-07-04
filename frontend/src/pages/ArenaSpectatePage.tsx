import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { axiosInstance } from "../lib/api";
import { useArenaSpectatorSocket } from "../lib/useArenaSpectatorSocket";

// ── Live Breach Events Phase 5 — public spectator page ─────────────────────
//
// Public, no-auth, read-only variant of ArenaMatchPage.tsx. Deliberately
// does NOT read useAuthStore's token anywhere in this page's own logic
// (unlike ArenaEventDetailPage.tsx's join button, which degrades based on
// token presence) — a spectator connection has no participant identity at
// all, so there is nothing here that should ever branch on auth state.
//
// Connects via useArenaSpectatorSocket (a dedicated hook — see that file's
// header comment for why this isn't a `spectate` option bolted onto the
// existing participant-oriented useArenaSocket). Everything rendered here
// is deliberately coarser than either participant's own view of the SAME
// match: no host list, no hostnames/roles, no per-segment monitoring
// status, no credential/CVE detail, and absolutely no action-submission UI
// — a spectator submits nothing, so this page renders no buttons/forms for
// that at all (not even disabled ones).

const _COMPLETED_STATUSES = ["attacker_won", "defender_won", "abandoned"];

const STATUS_META: Record<string, { label: string; color: string; dot: string }> = {
  active: { label: "Live", color: "text-yellow-400 border-yellow-500/40 bg-yellow-500/10", dot: "bg-yellow-400 animate-pulse" },
  lobby: { label: "Waiting to start", color: "text-cyan-400 border-cyan-500/40 bg-cyan-500/10", dot: "bg-cyan-400" },
  attacker_won: { label: "Attacker Won", color: "text-red-400 border-red-500/50 bg-red-500/10", dot: "bg-red-400" },
  defender_won: { label: "Defender Won", color: "text-green-400 border-green-500/50 bg-green-500/10", dot: "bg-green-400" },
  abandoned: { label: "Abandoned", color: "text-gray-400 border-gray-600/50 bg-gray-600/10", dot: "bg-gray-500" },
};

const ACTOR_META: Record<string, { label: string; cls: string }> = {
  attacker: { label: "Attacker", cls: "text-red-400 border-red-500/30 bg-red-500/10" },
  defender: { label: "Defender", cls: "text-blue-400 border-blue-500/30 bg-blue-500/10" },
};

function TopBar({ eventId }: { eventId?: string }) {
  return (
    <div className="border-b border-gray-800 bg-gray-950/90 px-5 py-2.5 flex items-center justify-between gap-4">
      <Link to="/" className="text-cyan-500 font-black text-sm uppercase tracking-widest">
        BreachReplay
      </Link>
      <Link
        to={eventId ? `/arena/events/${eventId}` : "/arena/events"}
        className="text-[10px] px-2 py-0.5 rounded border border-gray-700 text-gray-400 hover:text-gray-200 hover:border-gray-500 font-bold uppercase tracking-wider transition-colors"
      >
        ← Back to Event
      </Link>
    </div>
  );
}

// One line of translated, redacted copy per spectator_action event — counts
// only, never the underlying host ids (see useArenaSpectatorSocket.ts's
// header comment for the redaction rationale).
function logLine(entry: { hostsNewlyCompromised: number; hostsNewlyIsolated: number }): string {
  const parts: string[] = [];
  if (entry.hostsNewlyCompromised > 0) {
    parts.push(`${entry.hostsNewlyCompromised} host${entry.hostsNewlyCompromised === 1 ? "" : "s"} newly compromised`);
  }
  if (entry.hostsNewlyIsolated > 0) {
    parts.push(`${entry.hostsNewlyIsolated} host${entry.hostsNewlyIsolated === 1 ? "" : "s"} isolated by the defender`);
  }
  return parts.length > 0 ? parts.join(" · ") : "Turn resolved — no visible change";
}

export default function ArenaSpectatePage() {
  const { eventId, matchId } = useParams<{ eventId: string; matchId: string }>();
  const [eventTitle, setEventTitle] = useState<string | null>(null);

  const { connected, match, initialView, log, matchComplete, closeReason } = useArenaSpectatorSocket(matchId ?? "");

  // Best-effort only: this page must render fully off the WS connection
  // alone (public/no-auth, per the plan), so a failed/slow event-title
  // fetch just leaves the header a little less specific — never blocks or
  // gates anything below.
  useEffect(() => {
    if (!eventId) return;
    axiosInstance
      .get(`/arena/events/${eventId}/status`)
      .then((resp) => setEventTitle(resp.data?.event?.title ?? null))
      .catch(() => {});
  }, [eventId]);

  const status = matchComplete?.status ?? match?.status ?? null;
  const isComplete = status ? _COMPLETED_STATUSES.includes(status) : false;
  const statusMeta = status ? STATUS_META[status] ?? STATUS_META.active : null;

  const totals = log.reduce(
    (acc, e) => ({
      compromised: acc.compromised + e.hostsNewlyCompromised,
      isolated: acc.isolated + e.hostsNewlyIsolated,
    }),
    { compromised: 0, isolated: 0 }
  );

  if (!matchId) {
    return (
      <div className="min-h-screen bg-gray-950 text-white flex flex-col">
        <TopBar eventId={eventId} />
        <div className="flex-1 flex items-center justify-center text-gray-500 text-sm">No match specified.</div>
      </div>
    );
  }

  if (closeReason === "match_not_found") {
    return (
      <div className="min-h-screen bg-gray-950 text-white flex flex-col">
        <TopBar eventId={eventId} />
        <div className="flex-1 flex items-center justify-center p-6">
          <div className="text-center max-w-sm">
            <div className="text-5xl mb-4">⚠</div>
            <h1 className="text-xl font-black mb-2">Match Not Found</h1>
            <p className="text-gray-500 text-sm">This match doesn't exist or is no longer available.</p>
          </div>
        </div>
      </div>
    );
  }

  if (closeReason === "not_spectatable") {
    return (
      <div className="min-h-screen bg-gray-950 text-white flex flex-col">
        <TopBar eventId={eventId} />
        <div className="flex-1 flex items-center justify-center p-6">
          <div className="text-center max-w-sm">
            <div className="text-5xl mb-4">🔒</div>
            <h1 className="text-xl font-black mb-2">Not Spectatable</h1>
            <p className="text-gray-500 text-sm">
              This match isn't part of a Live Breach Event, so it can't be spectated.
            </p>
          </div>
        </div>
      </div>
    );
  }

  if (!match) {
    return (
      <div className="min-h-screen bg-gray-950 text-white flex flex-col">
        <TopBar eventId={eventId} />
        <div className="flex-1 flex items-center justify-center">
          <div className="text-gray-600 text-sm">Connecting to match...</div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#040712] flex flex-col font-mono text-slate-200">
      <TopBar eventId={eventId} />

      {/* Header bar — connection status + match status, mirrors
          ArenaMatchPage.tsx's top-bar badge convention. */}
      <div className="border-b border-slate-800 bg-slate-950/90 px-5 py-2.5 flex items-center justify-between gap-4 flex-wrap">
        <div className="flex items-center gap-3">
          <span className="text-cyan-500 font-black text-sm uppercase tracking-widest">👁 Spectating</span>
          <span className="text-slate-600">|</span>
          <span className="text-slate-500 text-xs">{eventTitle ?? "Live Breach Event"}</span>
          <span className="text-slate-600">|</span>
          <span className="text-xs text-slate-500 uppercase">{match.mode.replace(/_/g, " ")} · {match.difficulty}</span>
        </div>
        <div className="flex items-center gap-3">
          <span className={`text-[10px] px-2 py-0.5 rounded border font-bold uppercase tracking-wider ${
            connected ? "border-green-500/40 text-green-400 bg-green-500/10" : "border-gray-700 text-gray-500"
          }`}>
            {connected ? "● Connected" : "○ Disconnected"}
          </span>
          {statusMeta && (
            <span className={`text-[10px] px-2 py-0.5 rounded border font-bold uppercase tracking-wider inline-flex items-center gap-1.5 ${statusMeta.color}`}>
              <span className={`w-1.5 h-1.5 rounded-full ${statusMeta.dot}`} />
              {statusMeta.label}
            </span>
          )}
        </div>
      </div>

      {/* Match-complete banner — same styling family as
          ArenaMatchPage.tsx's, minus the debrief/back-to-lobby buttons
          (a spectator isn't a participant, so those destinations don't
          apply — a spectator just goes back to the event). */}
      {isComplete && status && (
        <div className={`animate-bounce-in px-5 py-4 border-b ${
          status === "attacker_won"
            ? "bg-red-950/30 border-red-800/40"
            : status === "defender_won"
            ? "bg-green-950/30 border-green-800/40"
            : "bg-gray-900/30 border-gray-700/40"
        }`}>
          <div className="max-w-2xl mx-auto text-center">
            <div className="text-3xl mb-1">{status === "attacker_won" ? "💀" : status === "defender_won" ? "🛡️" : "⏹"}</div>
            <h2 className={`text-lg font-black uppercase tracking-widest ${
              status === "attacker_won" ? "text-red-400" : status === "defender_won" ? "text-green-400" : "text-gray-400"
            }`}>
              Match Complete — {status.replace(/_/g, " ")}
            </h2>
            <div className="mt-4">
              <Link
                to={eventId ? `/arena/events/${eventId}` : "/arena/events"}
                className="text-xs px-4 py-2 rounded bg-cyan-700 hover:bg-cyan-600 text-white font-bold uppercase tracking-wider transition-colors inline-block"
              >
                ← Back to Event
              </Link>
            </div>
          </div>
        </div>
      )}

      {/* Main content: coarse initial view + running redacted log. No org
          map, no host list, no action buttons — deliberately less detail
          than either participant's own view of this same match. */}
      <div className="flex-1 overflow-y-auto p-6">
        <div className="max-w-2xl mx-auto space-y-6">
          {/* Coarse org shape */}
          <div className="border border-slate-800 rounded-xl p-5 bg-slate-900/30">
            <div className="text-xs text-slate-500 uppercase tracking-widest mb-3 font-bold">Org Shape (Coarse View)</div>
            <div className="grid grid-cols-2 gap-4 mb-4">
              <div className="text-center border border-slate-800 rounded-lg p-3">
                <div className="text-2xl font-black text-white">{initialView?.host_count ?? "—"}</div>
                <div className="text-[10px] text-slate-500 mt-1 uppercase tracking-wider">Total Hosts</div>
              </div>
              <div className="text-center border border-slate-800 rounded-lg p-3">
                <div className="text-2xl font-black text-white">{initialView?.segment_count ?? "—"}</div>
                <div className="text-[10px] text-slate-500 mt-1 uppercase tracking-wider">Network Segments</div>
              </div>
            </div>
            {initialView && initialView.segments.length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {initialView.segments.map((s) => (
                  <span key={s.id} className="text-[10px] text-slate-400 border border-slate-800 rounded px-2 py-1">
                    {s.name}
                  </span>
                ))}
              </div>
            )}
            <p className="text-[10px] text-slate-600 mt-3 leading-relaxed">
              This is deliberately less detail than either the attacker or defender sees in this match — no
              hostnames, roles, or monitoring status are shown to spectators.
            </p>
          </div>

          {/* Running tallies */}
          <div className="grid grid-cols-2 gap-4">
            <div className="border border-red-900/30 bg-red-950/10 rounded-xl p-4 text-center">
              <div className="text-2xl font-black text-red-400">{totals.compromised}</div>
              <div className="text-[10px] text-slate-500 mt-1 uppercase tracking-wider">Hosts Compromised So Far</div>
            </div>
            <div className="border border-blue-900/30 bg-blue-950/10 rounded-xl p-4 text-center">
              <div className="text-2xl font-black text-blue-400">{totals.isolated}</div>
              <div className="text-[10px] text-slate-500 mt-1 uppercase tracking-wider">Hosts Isolated So Far</div>
            </div>
          </div>

          {/* Live redacted action log */}
          <div className="border border-slate-800 rounded-xl bg-slate-900/30 overflow-hidden">
            <div className="px-5 py-3 border-b border-slate-800 flex items-center justify-between">
              <span className="text-xs font-bold uppercase tracking-widest text-slate-400">Live Feed</span>
              <span className="text-[10px] text-slate-600">{log.length} event{log.length === 1 ? "" : "s"}</span>
            </div>
            {log.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-16 text-slate-700">
                <div className="text-3xl mb-3">👁</div>
                <p className="text-xs uppercase tracking-widest">Awaiting the first move...</p>
              </div>
            ) : (
              <div className="divide-y divide-slate-800/60 max-h-[420px] overflow-y-auto">
                {[...log].reverse().map((entry) => {
                  const actor = ACTOR_META[entry.actor] ?? { label: entry.actor, cls: "text-slate-400 border-slate-700 bg-slate-800/30" };
                  return (
                    <div key={entry.sequence_number} className="px-5 py-3 flex items-center gap-3 text-xs">
                      <span className="w-8 text-slate-600 font-mono">#{entry.sequence_number}</span>
                      <span className={`text-[9px] font-bold uppercase tracking-widest px-1.5 py-0.5 rounded border shrink-0 ${actor.cls}`}>
                        {actor.label}
                      </span>
                      <span className="flex-1 text-slate-300">{logLine(entry)}</span>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
