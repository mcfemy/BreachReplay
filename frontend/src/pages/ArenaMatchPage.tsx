import { useEffect, useMemo, useRef, useState } from "react";
import { Navigate, useNavigate, useParams } from "react-router-dom";
import { api } from "../lib/api";
import { useAuthStore } from "../store/auth";
import { useArenaSocket } from "../lib/useArenaSocket";
import RankChangeToast from "../components/RankChangeToast";

// ── Types (mirror OrgState.to_dict() from org_simulation.py exactly) ───────
interface Host {
  id: string;
  hostname: string;
  role: string;
  network_segment_id: string;
  unpatched_cves: string[];
  edr_installed: boolean;
  compromise_level: "none" | "foothold" | "admin" | "domain_admin";
  isolated: boolean;
}

interface Segment {
  id: string;
  name: string;
  monitored: boolean;
  reachable_from: string[];
}

interface Credential {
  id: string;
  username: string;
  privilege: string;
  valid_on_host_ids: string[];
  harvested: boolean;
  disabled: boolean;
}

interface OrgStateDict {
  hosts: Host[];
  segments: Segment[];
  credentials: Credential[];
  detection_rules: unknown[];
  global_flags: Record<string, unknown>;
}

interface MatchDetail {
  id: string;
  mode: "pvp" | "human_defends_vs_ai" | "human_attacks_vs_ai";
  archetype_key: string;
  difficulty: string;
  status: string;
  attacker_user_id: string | null;
  defender_user_id: string | null;
  action_count: number;
  state: OrgStateDict;
}

// Attacker move catalog — mirrors org_simulation.py's ATTACKER_ACTION_TYPES
// and their documented payload shapes exactly (the "Action vocabulary"
// comment block above ATTACKER_ACTION_TYPES in org_simulation.py).
const ATTACKER_MOVES: { action_type: string; label: string; tactic: string; needs: string }[] = [
  { action_type: "discover_segment", label: "Scan Segment", tactic: "Discovery", needs: "segment_id" },
  { action_type: "discover_host", label: "Enumerate Host", tactic: "Discovery", needs: "host_id" },
  { action_type: "gain_foothold", label: "Gain Foothold", tactic: "Initial Access", needs: "host_id" },
  { action_type: "dump_credentials", label: "Dump Credentials", tactic: "Credential Access", needs: "host_id" },
  { action_type: "escalate_privilege", label: "Escalate Privilege", tactic: "Privilege Escalation", needs: "host_id" },
  { action_type: "lateral_move", label: "Lateral Movement", tactic: "Lateral Movement", needs: "credential+target" },
  { action_type: "deploy_impact", label: "Deploy Impact", tactic: "Impact", needs: "host_id" },
];

const COMPROMISE_COLOR: Record<string, string> = {
  none: "text-gray-600",
  foothold: "text-yellow-400",
  admin: "text-orange-400",
  domain_admin: "text-red-400",
};

const SEV_BORDER: Record<string, string> = {
  critical: "border-l-red-500 bg-red-950/20",
  high: "border-l-orange-500 bg-orange-950/10",
  medium: "border-l-yellow-500 bg-yellow-950/10",
  low: "border-l-blue-500 bg-blue-950/10",
};
const SEV_BADGE: Record<string, string> = {
  critical: "bg-red-600 text-white animate-pulse",
  high: "bg-orange-600 text-white",
  medium: "bg-yellow-600 text-black",
  low: "bg-blue-700 text-white",
};

export default function ArenaMatchPage() {
  const { matchId } = useParams<{ matchId: string }>();
  const navigate = useNavigate();
  const { user } = useAuthStore();

  const [match, setMatch] = useState<MatchDetail | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [notification, setNotification] = useState<{ kind: "success" | "error" | "info"; message: string } | null>(null);
  const [executing, setExecuting] = useState<string | null>(null);
  const [rankToastDismissed, setRankToastDismissed] = useState(false);

  // Selections for multi-field attacker moves
  const [selectedSegment, setSelectedSegment] = useState<string>("");
  const [selectedHost, setSelectedHost] = useState<string>("");
  const [selectedCredential, setSelectedCredential] = useState<string>("");
  const [selectedTargetHost, setSelectedTargetHost] = useState<string>("");

  function notify(kind: "success" | "error" | "info", message: string) {
    setNotification({ kind, message });
    setTimeout(() => setNotification(null), 5000);
  }

  const {
    connected,
    alerts,
    currentGate,
    lastActionResult,
    lastDecisionResult,
    lastDefenderActionResult,
    matchComplete,
    sendAttackerAction,
    sendDefenderAction,
  } = useArenaSocket(matchId ?? "", { onNotification: notify });

  async function fetchMatch() {
    if (!matchId) return;
    try {
      const data = await api.get<MatchDetail>(`/arena/matches/${matchId}`);
      setMatch(data);
    } catch (e: any) {
      setLoadError(e.message || "Failed to load match");
    }
  }

  useEffect(() => {
    fetchMatch();
  }, [matchId]);

  // Refresh full match/org state after any action result so host/segment/
  // credential lists (used to build subsequent action payloads) stay
  // current — the WS events carry alerts/gates/results, not the full
  // OrgState, so REST is the source of truth for "what can I click next."
  useEffect(() => {
    if (lastActionResult || lastDecisionResult || lastDefenderActionResult) {
      fetchMatch();
      setExecuting(null);
    }
  }, [lastActionResult, lastDecisionResult, lastDefenderActionResult]);

  useEffect(() => {
    if (matchComplete) fetchMatch();
  }, [matchComplete]);

  const role: "attacker" | "defender" | null = useMemo(() => {
    if (!match || !user) return null;
    if (match.attacker_user_id === user.id) return "attacker";
    if (match.defender_user_id === user.id) return "defender";
    return null;
  }, [match, user]);

  // Guard placed after all hooks (not before) so hooks are always called in
  // the same order every render, regardless of whether the route actually
  // supplies a matchId — moving this earlier would violate the Rules of
  // Hooks even though the current route wiring always provides one.
  if (!matchId) return <Navigate to="/arena" replace />;

  if (loadError) {
    return (
      <div className="min-h-screen bg-gray-950 text-white flex items-center justify-center px-4">
        <div className="text-center">
          <div className="text-4xl mb-3">⚠</div>
          <p className="text-red-400 mb-4">{loadError}</p>
          <button onClick={() => navigate("/arena")} className="text-xs text-gray-500 hover:text-gray-300">
            ← Back to Arena Lobby
          </button>
        </div>
      </div>
    );
  }

  if (!match) {
    return (
      <div className="min-h-screen bg-gray-950 flex items-center justify-center">
        <div className="text-gray-600 text-sm">Loading match...</div>
      </div>
    );
  }

  const hosts = match.state.hosts || [];
  const segments = match.state.segments || [];
  const credentials = match.state.credentials || [];
  const status = matchComplete?.status || match.status;
  const isComplete = ["attacker_won", "defender_won", "abandoned"].includes(status);

  function handleAttackerExecute(actionType: string) {
    let payload: Record<string, unknown> = {};
    if (actionType === "discover_segment") {
      if (!selectedSegment) return notify("error", "Select a segment first");
      payload = { segment_id: selectedSegment };
    } else if (actionType === "lateral_move") {
      if (!selectedCredential || !selectedTargetHost) return notify("error", "Select a credential and target host");
      payload = { credential_id: selectedCredential, target_host_id: selectedTargetHost };
    } else {
      if (!selectedHost) return notify("error", "Select a host first");
      payload = { host_id: selectedHost };
    }
    setExecuting(actionType);
    sendAttackerAction(actionType, payload);
  }

  function handleDefenderGateOption(opt: { response_action_type?: string; host_id?: string; credential_id?: string; segment_id?: string }) {
    if (!opt.response_action_type) return;
    const payload: Record<string, unknown> = {};
    if (opt.host_id) payload.host_id = opt.host_id;
    if (opt.credential_id) payload.credential_id = opt.credential_id;
    if (opt.segment_id) payload.segment_id = opt.segment_id;
    sendDefenderAction(opt.response_action_type, payload);
  }

  // Phase J: free-form SOC console actions, usable at any time (not gated
  // behind a decision gate) — same WS message shape as the gate-driven
  // path above, just invoked directly from the persistent console panel.
  function handleDefenderFreeAction(actionType: string, payload: Record<string, unknown>) {
    sendDefenderAction(actionType, payload);
  }

  const NOTIF_CLS = {
    success: "bg-green-950/95 border-green-500 text-green-300",
    error: "bg-red-950/95 border-red-500 text-red-300",
    info: "bg-blue-950/95 border-blue-500 text-blue-300",
  };

  return (
    <div className="min-h-screen bg-[#040712] flex flex-col font-mono text-slate-200">
      {notification && (
        <div className={`fixed top-4 right-4 z-40 border rounded-lg px-4 py-3 text-xs max-w-sm shadow-2xl border-l-4 leading-relaxed ${NOTIF_CLS[notification.kind]}`}>
          {notification.message}
        </div>
      )}

      {/* Phase I: rank-change toast — matchComplete.rating_change is already
          scoped to THIS connection's side (attacker's socket only ever gets
          the attacker's own change, defender's socket only its own), so no
          extra user-id filtering is needed here. */}
      {matchComplete?.rating_change && !rankToastDismissed && (
        <RankChangeToast
          before={matchComplete.rating_change.before}
          after={matchComplete.rating_change.after}
          delta={matchComplete.rating_change.delta}
          onDone={() => setRankToastDismissed(true)}
        />
      )}

      {/* Top bar */}
      <div className="border-b border-slate-800 bg-slate-950/90 px-5 py-2.5 flex items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <button onClick={() => navigate("/arena")} className="text-slate-500 hover:text-slate-300 text-xs">
            ← Arena
          </button>
          <span className="text-slate-600">|</span>
          <span className="text-cyan-500 font-black text-sm uppercase tracking-widest">⚔️ Live Arena</span>
          <span className="text-slate-600">|</span>
          <span className="text-slate-500 text-xs">Match {matchId.slice(0, 8)}</span>
          <span className="text-slate-600">|</span>
          <span className="text-xs text-slate-500 uppercase">{match.mode.replace(/_/g, " ")} · {match.difficulty}</span>
        </div>
        <div className="flex items-center gap-3">
          <span className={`text-[10px] px-2 py-0.5 rounded border font-bold uppercase tracking-wider ${
            connected ? "border-green-500/40 text-green-400 bg-green-500/10" : "border-gray-700 text-gray-500"
          }`}>
            {connected ? "● Connected" : "○ Connecting..."}
          </span>
          {role && (
            <span className={`text-[10px] px-2 py-0.5 rounded border font-bold uppercase tracking-wider ${
              role === "attacker" ? "border-red-500/40 text-red-400 bg-red-500/10" : "border-blue-500/40 text-blue-400 bg-blue-500/10"
            }`}>
              You: {role}
            </span>
          )}
          <span className={`text-[10px] px-2 py-0.5 rounded border font-bold uppercase tracking-wider ${
            isComplete
              ? status === "attacker_won"
                ? "border-red-500/50 text-red-400 bg-red-500/10"
                : status === "defender_won"
                ? "border-green-500/50 text-green-400 bg-green-500/10"
                : "border-gray-600/50 text-gray-400 bg-gray-600/10"
              : "border-yellow-500/40 text-yellow-400 bg-yellow-500/10 animate-pulse"
          }`}>
            {status.replace(/_/g, " ")}
          </span>
        </div>
      </div>

      {/* Match complete banner — Phase K: real entrance instead of an instant
          hard-swap. animate-bounce-in gives the whole banner a pop-in; the
          status-conditional impact-flash/contained-glow layers a brief
          red/green pulse on top for the win/loss moment specifically, since
          this is the single highest-payoff emotional beat in the match. */}
      {isComplete && (
        <div className={`animate-bounce-in px-5 py-4 border-b ${
          status === "attacker_won"
            ? "bg-red-950/30 border-red-800/40 animate-impact-flash"
            : status === "defender_won"
            ? "bg-green-950/30 border-green-800/40 animate-contained-glow"
            : "bg-gray-900/30 border-gray-700/40"
        }`}>
          <div className="max-w-3xl mx-auto text-center">
            <div className="text-3xl mb-1">{status === "attacker_won" ? "💀" : status === "defender_won" ? "🛡️" : "⏹"}</div>
            <h2 className={`text-lg font-black uppercase tracking-widest ${
              status === "attacker_won" ? "text-red-400" : status === "defender_won" ? "text-green-400" : "text-gray-400"
            }`}>
              Match Complete — {status.replace(/_/g, " ")}
            </h2>
            <p className="text-xs text-slate-500 mt-1">
              {status === "attacker_won"
                ? "Impact was deployed. The attacker achieved their objective."
                : status === "defender_won"
                ? "The defender contained every foothold before impact, or held the line for the full turn budget. Blue team wins."
                : "The match was abandoned before either side reached a decisive outcome."}
            </p>
            <div className="flex items-center justify-center gap-3 mt-3">
              <button
                onClick={() => navigate("/arena")}
                className="text-xs px-4 py-2 rounded bg-cyan-700 hover:bg-cyan-600 text-white font-bold uppercase tracking-wider transition-colors"
              >
                Back to Arena Lobby
              </button>
              <button
                onClick={() => navigate(`/arena/match/${matchId}/debrief`)}
                className="text-xs px-4 py-2 rounded bg-purple-700 hover:bg-purple-600 text-white font-bold uppercase tracking-wider transition-colors"
              >
                🕸 View Debrief / Explore Alternate Choices
              </button>
            </div>
          </div>
        </div>
      )}

      {!role && (
        <div className="px-5 py-3 text-center text-xs text-yellow-500 bg-yellow-950/10 border-b border-yellow-900/30">
          You are not a participant in this match (spectator mode is out of scope for v1).
        </div>
      )}

      {/* Main content */}
      <div className="flex-1 flex overflow-hidden">
        {role === "attacker" && !isComplete && (
          <AttackerView
            hosts={hosts}
            segments={segments}
            credentials={credentials}
            selectedSegment={selectedSegment}
            setSelectedSegment={setSelectedSegment}
            selectedHost={selectedHost}
            setSelectedHost={setSelectedHost}
            selectedCredential={selectedCredential}
            setSelectedCredential={setSelectedCredential}
            selectedTargetHost={selectedTargetHost}
            setSelectedTargetHost={setSelectedTargetHost}
            onExecute={handleAttackerExecute}
            executing={executing}
            lastActionResult={lastActionResult}
            lastDefenderActionResult={lastDefenderActionResult}
          />
        )}

        {role === "defender" && !isComplete && (
          <DefenderView
            hosts={hosts}
            segments={segments}
            credentials={credentials}
            alerts={alerts}
            currentGate={currentGate}
            lastDecisionResult={lastDecisionResult}
            onOption={handleDefenderGateOption}
            onFreeAction={handleDefenderFreeAction}
          />
        )}

        {isComplete && (
          <div className="flex-1 flex flex-col items-center justify-center p-10 gap-6">
            <OrgSummary hosts={hosts} segments={segments} />
          </div>
        )}
      </div>
    </div>
  );
}

// ── Phase K: shared host-change-flash tracker ───────────────────────────────
// Both AttackerView's "Org Intel" panel and DefenderView's "SOC Console"
// panel render the same host-row shape (Phase J duplication, left as-is) —
// this hook is the one small piece of logic worth sharing between them: it
// diffs each host's compromise_level/isolated against what was rendered last
// time and returns a Set of host ids that just changed, so either view can
// slap a `animate-host-flash` class on that row for ~1s.
function useHostChangeFlash(hosts: Host[]): Set<string> {
  const prevRef = useRef<Record<string, { compromise_level: string; isolated: boolean }>>({});
  const [flashed, setFlashed] = useState<Set<string>>(new Set());

  useEffect(() => {
    const prev = prevRef.current;
    const changed = new Set<string>();
    for (const h of hosts) {
      const before = prev[h.id];
      if (before && (before.compromise_level !== h.compromise_level || before.isolated !== h.isolated)) {
        changed.add(h.id);
      }
    }
    // Update the snapshot immediately (not just on cleanup) so the next
    // diff compares against this render's values.
    prevRef.current = Object.fromEntries(
      hosts.map((h) => [h.id, { compromise_level: h.compromise_level, isolated: h.isolated }])
    );
    if (changed.size > 0) {
      setFlashed(changed);
      const t = setTimeout(() => setFlashed(new Set()), 1000);
      return () => clearTimeout(t);
    }
  }, [hosts]);

  return flashed;
}

// ── Attacker view (RedTeamPage-style: raw slate/gray/red Tailwind) ─────────
function AttackerView({
  hosts, segments, credentials,
  selectedSegment, setSelectedSegment,
  selectedHost, setSelectedHost,
  selectedCredential, setSelectedCredential,
  selectedTargetHost, setSelectedTargetHost,
  onExecute, executing, lastActionResult, lastDefenderActionResult,
}: {
  hosts: Host[]; segments: Segment[]; credentials: Credential[];
  selectedSegment: string; setSelectedSegment: (v: string) => void;
  selectedHost: string; setSelectedHost: (v: string) => void;
  selectedCredential: string; setSelectedCredential: (v: string) => void;
  selectedTargetHost: string; setSelectedTargetHost: (v: string) => void;
  onExecute: (actionType: string) => void;
  executing: string | null;
  lastActionResult: { action_type: string; sequence_number: number; detected: boolean } | null;
  lastDefenderActionResult: { action_type: string; payload: Record<string, unknown>; sequence_number: number } | null;
}) {
  const reachableHosts = hosts.filter((h) => !h.isolated);
  const harvestedCreds = credentials.filter((c) => c.harvested && !c.disabled);
  const flashedHosts = useHostChangeFlash(hosts);

  return (
    <div className="flex flex-1 overflow-hidden">
      {/* Left: Intel panel */}
      <div className="w-72 border-r border-gray-800 p-4 overflow-y-auto shrink-0 bg-gray-950/80">
        <div className="text-xs text-gray-600 uppercase tracking-widest mb-3 font-bold">Org Intel</div>

        <div className="mb-4">
          <div className="text-[10px] text-gray-600 uppercase tracking-widest mb-1">Segments</div>
          <div className="space-y-1">
            {segments.map((s) => (
              <div key={s.id} className="text-[11px] text-gray-400 flex justify-between border border-gray-800 rounded px-2 py-1">
                <span>{s.name}</span>
                <span className={s.monitored ? "text-red-400" : "text-gray-600"}>{s.monitored ? "monitored" : "unmonitored"}</span>
              </div>
            ))}
          </div>
        </div>

        <div className="mb-4">
          <div className="text-[10px] text-gray-600 uppercase tracking-widest mb-1">Hosts ({hosts.length})</div>
          <div className="space-y-1">
            {hosts.map((h) => (
              <div
                key={h.id}
                className={`text-[10px] border rounded px-2 py-1 ${h.isolated ? "border-gray-800 opacity-40" : "border-gray-800"} ${flashedHosts.has(h.id) ? "animate-host-flash" : ""}`}
              >
                <div className="flex justify-between">
                  <span className="text-gray-300 truncate">{h.hostname}</span>
                  <span className={COMPROMISE_COLOR[h.compromise_level]}>{h.compromise_level}</span>
                </div>
                <div className="text-gray-700">{h.role}{h.isolated ? " · ISOLATED" : ""}{h.edr_installed ? " · EDR" : ""}</div>
              </div>
            ))}
          </div>
        </div>

        <div>
          <div className="text-[10px] text-gray-600 uppercase tracking-widest mb-1">Harvested Credentials</div>
          {harvestedCreds.length === 0 ? (
            <p className="text-[10px] text-gray-700">None yet — dump_credentials on a compromised host.</p>
          ) : (
            <div className="space-y-1">
              {harvestedCreds.map((c) => (
                <div key={c.id} className="text-[10px] text-gray-400 border border-gray-800 rounded px-2 py-1">
                  {c.username} ({c.privilege})
                </div>
              ))}
            </div>
          )}
        </div>

        {lastDefenderActionResult && (
          <div className="mt-4 border border-blue-900/40 bg-blue-950/10 rounded p-2">
            <div className="text-[9px] text-blue-400 uppercase tracking-widest font-bold mb-1">🔵 SOC Reacted</div>
            <p className="text-[10px] text-gray-400">{lastDefenderActionResult.action_type.replace(/_/g, " ")}</p>
          </div>
        )}
      </div>

      {/* Right: move list */}
      <div className="flex-1 overflow-y-auto p-6">
        <div className="max-w-2xl mx-auto space-y-4">
          <div className="flex items-center justify-between mb-2">
            <h2 className="text-lg font-bold text-red-400">Attacker Moves</h2>
            {lastActionResult && (
              <span className={`text-xs ${lastActionResult.detected ? "text-red-400" : "text-green-400"}`}>
                Last: {lastActionResult.action_type.replace(/_/g, " ")} {lastActionResult.detected ? "— DETECTED" : "— undetected"}
              </span>
            )}
          </div>

          {/* Target selectors */}
          <div className="grid grid-cols-2 gap-3 border border-gray-800 rounded-lg p-3 bg-gray-900/30">
            <div>
              <label className="text-[10px] text-gray-600 uppercase block mb-1">Segment</label>
              <select
                value={selectedSegment}
                onChange={(e) => setSelectedSegment(e.target.value)}
                className="w-full bg-gray-950 border border-gray-800 text-gray-300 text-xs p-1.5 rounded"
              >
                <option value="">— select —</option>
                {segments.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
              </select>
            </div>
            <div>
              <label className="text-[10px] text-gray-600 uppercase block mb-1">Host</label>
              <select
                value={selectedHost}
                onChange={(e) => setSelectedHost(e.target.value)}
                className="w-full bg-gray-950 border border-gray-800 text-gray-300 text-xs p-1.5 rounded"
              >
                <option value="">— select —</option>
                {reachableHosts.map((h) => <option key={h.id} value={h.id}>{h.hostname}</option>)}
              </select>
            </div>
            <div>
              <label className="text-[10px] text-gray-600 uppercase block mb-1">Credential (for lateral move)</label>
              <select
                value={selectedCredential}
                onChange={(e) => setSelectedCredential(e.target.value)}
                className="w-full bg-gray-950 border border-gray-800 text-gray-300 text-xs p-1.5 rounded"
              >
                <option value="">— select —</option>
                {harvestedCreds.map((c) => <option key={c.id} value={c.id}>{c.username}</option>)}
              </select>
            </div>
            <div>
              <label className="text-[10px] text-gray-600 uppercase block mb-1">Target host (for lateral move)</label>
              <select
                value={selectedTargetHost}
                onChange={(e) => setSelectedTargetHost(e.target.value)}
                className="w-full bg-gray-950 border border-gray-800 text-gray-300 text-xs p-1.5 rounded"
              >
                <option value="">— select —</option>
                {reachableHosts.map((h) => <option key={h.id} value={h.id}>{h.hostname}</option>)}
              </select>
            </div>
          </div>

          <div className="space-y-3">
            {ATTACKER_MOVES.map((move) => (
              <div key={move.action_type} className="border border-gray-800 rounded-xl p-4 hover:border-gray-600 transition-colors">
                <div className="flex items-center justify-between">
                  <div>
                    <div className="text-sm font-bold text-white">{move.label}</div>
                    <div className="text-[10px] text-gray-600">{move.tactic} · needs {move.needs}</div>
                  </div>
                  <button
                    onClick={() => onExecute(move.action_type)}
                    disabled={executing === move.action_type}
                    className="py-2 px-4 rounded-lg bg-red-600/80 hover:bg-red-600 disabled:opacity-50 text-white text-xs font-bold uppercase tracking-wider transition-all active:scale-[0.98]"
                  >
                    {executing === move.action_type ? "Executing..." : "⚡ Execute"}
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Defender view (SimulationRoomPage-style: slate/blue Tailwind) ──────────
function DefenderView({
  hosts, segments, credentials,
  alerts, currentGate, lastDecisionResult, onOption, onFreeAction,
}: {
  hosts: Host[]; segments: Segment[]; credentials: Credential[];
  alerts: { timestamp: string; severity: string; source_system: string; rule_id: string; description: string; raw_log?: string }[];
  currentGate: { gate_id: string; context_summary: string; options: { index: number; text: string; response_action_type?: string; host_id?: string; credential_id?: string; segment_id?: string }[] } | null;
  lastDecisionResult: { is_correct: boolean; rationale: string; consequence_applied: string; action_type?: string } | null;
  onOption: (opt: { response_action_type?: string; host_id?: string; credential_id?: string; segment_id?: string }) => void;
  onFreeAction: (actionType: string, payload: Record<string, unknown>) => void;
}) {
  const enabledHarvestedCreds = credentials.filter((c) => c.harvested && !c.disabled);
  const flashedHosts = useHostChangeFlash(hosts);

  return (
    <div className="flex flex-1 overflow-hidden">
      {/* Left: SOC Console — persistent org visibility + free-form actions,
          modeled directly on AttackerView's "Org Intel" panel so the
          defender has the same ambient awareness the attacker does. */}
      <div className="w-72 border-r border-slate-800 p-4 overflow-y-auto shrink-0 bg-slate-950/80">
        <div className="text-xs text-slate-500 uppercase tracking-widest mb-3 font-bold">SOC Console</div>

        <div className="mb-4">
          <div className="text-[10px] text-slate-500 uppercase tracking-widest mb-1">Segments</div>
          <div className="space-y-1">
            {segments.map((s) => (
              <div key={s.id} className="text-[11px] border border-slate-800 rounded px-2 py-1">
                <div className="flex justify-between">
                  <span className="text-slate-300">{s.name}</span>
                  <span className={s.monitored ? "text-blue-400" : "text-slate-600"}>{s.monitored ? "monitored" : "unmonitored"}</span>
                </div>
                {!s.monitored && (
                  <button
                    onClick={() => onFreeAction("increase_monitoring", { segment_id: s.id })}
                    className="mt-1 w-full text-[9px] uppercase tracking-wider font-bold py-1 rounded bg-blue-700/70 hover:bg-blue-600 text-white transition-colors"
                  >
                    Increase Monitoring
                  </button>
                )}
              </div>
            ))}
          </div>
        </div>

        <div className="mb-4">
          <div className="text-[10px] text-slate-500 uppercase tracking-widest mb-1">Hosts ({hosts.length})</div>
          <div className="space-y-1">
            {hosts.map((h) => (
              <div
                key={h.id}
                className={`text-[10px] border rounded px-2 py-1 ${h.isolated ? "border-slate-800 opacity-40" : "border-slate-800"} ${flashedHosts.has(h.id) ? "animate-host-flash" : ""}`}
              >
                <div className="flex justify-between">
                  <span className="text-slate-300 truncate">{h.hostname}</span>
                  <span className={COMPROMISE_COLOR[h.compromise_level]}>{h.compromise_level}</span>
                </div>
                <div className="text-slate-600">
                  {h.role}{h.isolated ? " · ISOLATED" : ""}{h.edr_installed ? " · EDR" : ""}
                  {h.unpatched_cves.length > 0 ? ` · ${h.unpatched_cves.length} CVE${h.unpatched_cves.length === 1 ? "" : "s"}` : ""}
                </div>
                <div className="flex gap-1 mt-1">
                  <button
                    onClick={() => onFreeAction("isolate_host", { host_id: h.id })}
                    disabled={h.isolated}
                    className="flex-1 text-[9px] uppercase tracking-wider font-bold py-1 rounded bg-red-800/70 hover:bg-red-700 disabled:opacity-30 disabled:hover:bg-red-800/70 text-white transition-colors"
                  >
                    Isolate
                  </button>
                  {h.unpatched_cves.length > 0 && (
                    <button
                      onClick={() => onFreeAction("patch_host", { host_id: h.id })}
                      className="flex-1 text-[9px] uppercase tracking-wider font-bold py-1 rounded bg-emerald-800/70 hover:bg-emerald-700 text-white transition-colors"
                    >
                      Patch
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>

        <div>
          <div className="text-[10px] text-slate-500 uppercase tracking-widest mb-1">Harvested Credentials</div>
          {enabledHarvestedCreds.length === 0 ? (
            <p className="text-[10px] text-slate-700">None harvested yet (or all disabled).</p>
          ) : (
            <div className="space-y-1">
              {enabledHarvestedCreds.map((c) => (
                <div key={c.id} className="text-[10px] border border-slate-800 rounded px-2 py-1">
                  <div className="flex justify-between text-slate-300">
                    <span>{c.username}</span>
                    <span className="text-slate-500">{c.privilege}</span>
                  </div>
                  <button
                    onClick={() => onFreeAction("disable_credential", { credential_id: c.id })}
                    className="mt-1 w-full text-[9px] uppercase tracking-wider font-bold py-1 rounded bg-blue-700/70 hover:bg-blue-600 text-white transition-colors"
                  >
                    Disable
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Alert feed */}
      <div className="flex-1 flex flex-col overflow-hidden border-r border-slate-800">
        <div className="px-4 py-2 bg-slate-950/50 border-b border-slate-800 flex items-center justify-between shrink-0">
          <span className="text-[10px] text-slate-500 uppercase tracking-widest">SIEM Feed — Live Arena</span>
          <span className="text-[10px] text-slate-600">{alerts.length} events</span>
        </div>
        <div className="flex-1 overflow-y-auto p-3 space-y-1.5">
          {alerts.map((alert, i) => (
            <div key={i} className={`animate-bounce-in border border-slate-800 border-l-4 px-3 py-2 rounded text-[11px] ${SEV_BORDER[alert.severity] || "border-l-slate-600"}`}>
              <div className="flex items-center gap-2 mb-1">
                <span className={`text-[9px] font-black uppercase px-1.5 py-0.5 rounded ${SEV_BADGE[alert.severity] || "bg-slate-700 text-slate-300"}`}>
                  {alert.severity}
                </span>
                <span className="text-slate-500 text-[9px]">{alert.timestamp}</span>
                <span className="text-slate-600 text-[9px]">·</span>
                <span className="text-slate-400 text-[9px] font-bold uppercase">{alert.source_system}</span>
              </div>
              <p className="text-slate-200 leading-relaxed">{alert.description}</p>
              {alert.raw_log && <p className="text-[9px] text-slate-600 mt-1 truncate">{alert.raw_log}</p>}
            </div>
          ))}
          {alerts.length === 0 && (
            <div className="flex flex-col items-center justify-center h-full py-20 text-slate-700">
              <div className="text-4xl mb-3">⚡</div>
              <p className="text-xs uppercase tracking-widest">Awaiting attacker activity...</p>
            </div>
          )}
        </div>
      </div>

      {/* Decision gate / result panel */}
      <div className="w-[420px] shrink-0 flex flex-col overflow-hidden">
        {currentGate ? (
          <div className="border-b border-red-900/60 bg-red-950/10 p-4 shrink-0">
            <div className="flex items-center gap-2 mb-3">
              <div className="w-2.5 h-2.5 rounded-full bg-red-500 animate-ping" />
              <span className="text-[10px] text-red-400 font-black uppercase tracking-widest">Tactical Decision Required</span>
            </div>
            <div className="bg-[#08091a] border border-red-900/40 rounded p-3 mb-3 text-xs text-slate-200 leading-relaxed">
              {currentGate.context_summary}
            </div>
            <div className="space-y-2">
              {currentGate.options.map((opt) => (
                <button
                  key={opt.index}
                  onClick={() => onOption(opt)}
                  className="w-full text-left border border-slate-700/60 bg-slate-900/40 hover:border-blue-500/70 hover:bg-blue-950/20 rounded p-3 text-xs transition-all"
                >
                  <span className="text-blue-400 font-bold mr-2">{String.fromCharCode(65 + opt.index)}.</span>
                  {opt.text}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="p-4 border-b border-slate-800/60 text-center text-[10px] text-slate-600 uppercase tracking-wider">
            No active decision gate
          </div>
        )}

        {lastDecisionResult && !currentGate && (
          <div className={`p-4 border-b shrink-0 ${lastDecisionResult.is_correct ? "bg-green-950/20 border-green-800/40" : "bg-red-950/20 border-red-800/40"}`}>
            <div className="flex items-center gap-2 mb-2">
              <span className={`text-lg ${lastDecisionResult.is_correct ? "text-green-400" : "text-red-400"}`}>✓</span>
              <span className="text-[10px] font-black uppercase tracking-widest text-green-400">Response Applied</span>
            </div>
            <p className="text-xs text-slate-300 leading-relaxed mb-2">{lastDecisionResult.rationale}</p>
            <p className="text-[10px] font-bold text-green-400">{lastDecisionResult.consequence_applied}</p>
          </div>
        )}

        <div className="flex-1" />
      </div>
    </div>
  );
}

function OrgSummary({ hosts, segments }: { hosts: Host[]; segments: Segment[] }) {
  const compromised = hosts.filter((h) => h.compromise_level !== "none").length;
  const isolated = hosts.filter((h) => h.isolated).length;
  return (
    <div className="max-w-lg w-full grid grid-cols-3 gap-4">
      <div className="border border-gray-800 rounded-xl p-4 text-center">
        <div className="text-2xl font-black text-white">{hosts.length}</div>
        <div className="text-xs text-gray-600 mt-1">Total Hosts</div>
      </div>
      <div className="border border-gray-800 rounded-xl p-4 text-center">
        <div className="text-2xl font-black text-red-400">{compromised}</div>
        <div className="text-xs text-gray-600 mt-1">Compromised</div>
      </div>
      <div className="border border-gray-800 rounded-xl p-4 text-center">
        <div className="text-2xl font-black text-blue-400">{isolated}</div>
        <div className="text-xs text-gray-600 mt-1">Isolated by Defender</div>
      </div>
      <div className="col-span-3 text-center text-[10px] text-gray-700 mt-2">
        {segments.length} network segment{segments.length === 1 ? "" : "s"} in this org.
      </div>
    </div>
  );
}
