import { useEffect, useRef, useState, useCallback } from "react";
import { Navigate, useNavigate, useParams } from "react-router-dom";
import { useSimStore } from "../store/simulation";
import type { PressureInjection } from "../store/simulation";
import { useSimulationSocket } from "../lib/useSimulationSocket";
import { useAuthStore } from "../store/auth";
import { api } from "../lib/api";

// ── Severity styling ────────────────────────────────────────────────────────
const SEV_BORDER: Record<string, string> = {
  critical: "border-l-red-500 bg-red-950/20",
  high:     "border-l-orange-500 bg-orange-950/10",
  medium:   "border-l-yellow-500 bg-yellow-950/10",
  low:      "border-l-blue-500 bg-blue-950/10",
};
const SEV_BADGE: Record<string, string> = {
  critical: "bg-red-600 text-white animate-pulse",
  high:     "bg-orange-600 text-white",
  medium:   "bg-yellow-600 text-black",
  low:      "bg-blue-700 text-white",
};

// ── Pressure injection styling ───────────────────────────────────────────────
const INJ_ICON: Record<string, string> = {
  email: "✉",
  call:  "☎",
  news:  "📡",
  sms:   "💬",
  slack: "⚡",
};
const INJ_HEADER_COLOR: Record<string, string> = {
  email: "text-blue-300 border-blue-500/40 bg-blue-950/30",
  call:  "text-red-300 border-red-500/40 bg-red-950/30",
  news:  "text-yellow-300 border-yellow-500/40 bg-yellow-950/30",
  sms:   "text-green-300 border-green-500/40 bg-green-950/30",
  slack: "text-purple-300 border-purple-500/40 bg-purple-950/30",
};

// ── Countdown hook ───────────────────────────────────────────────────────────
function useCountdown(seconds: number | undefined, active: boolean): number | null {
  const [remaining, setRemaining] = useState<number | null>(seconds ?? null);
  useEffect(() => {
    if (!active || seconds == null) { setRemaining(null); return; }
    setRemaining(seconds);
    const interval = setInterval(() => {
      setRemaining((r) => {
        if (r == null || r <= 1) { clearInterval(interval); return 0; }
        return r - 1;
      });
    }, 1000);
    return () => clearInterval(interval);
  }, [seconds, active]);
  return remaining;
}

// ── Breaking news ticker items ───────────────────────────────────────────────
const TICKER_PHRASES = [
  "ACTIVE INCIDENT RESPONSE IN PROGRESS",
  "THREAT ACTOR PERSISTENCE DETECTED",
  "CRITICAL SYSTEMS AFFECTED — CONTAIN AND TRIAGE",
  "EXECUTIVE LEADERSHIP AWAITING STATUS UPDATE",
  "REGULATORY NOTIFICATION WINDOWS OPEN",
  "ALL HANDS — BREACH REPLAY WAR ROOM ACTIVE",
];

interface SessionData {
  id: string;
  scenario_id: string;
  host_user_id: string;
  status: string;
  mode: string;
}

// ── Pressure Injection Modal ─────────────────────────────────────────────────
function PressureModal({
  injection,
  onDismiss,
}: {
  injection: PressureInjection;
  onDismiss: () => void;
}) {
  const countdown = useCountdown(injection.countdown_seconds, true);
  const headerClass = INJ_HEADER_COLOR[injection.type] || "text-white border-slate-500 bg-slate-900";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm animate-in fade-in">
      {/* Red screen flash for calls */}
      {injection.type === "call" && (
        <div className="absolute inset-0 bg-red-900/20 animate-pulse pointer-events-none" />
      )}
      <div
        className={`relative w-full max-w-lg mx-4 border rounded-xl shadow-2xl overflow-hidden ${headerClass}`}
      >
        {/* Header bar */}
        <div className={`px-5 py-3 border-b ${headerClass} flex items-center justify-between`}>
          <div className="flex items-center gap-3">
            <span className="text-2xl">{INJ_ICON[injection.type] ?? "📌"}</span>
            <div>
              <div className="text-[10px] uppercase tracking-widest font-bold opacity-70">
                INCOMING {injection.type.toUpperCase()} — PRIORITY INTERRUPT
              </div>
              <div className="text-sm font-bold">{injection.from}</div>
            </div>
          </div>
          {countdown != null && countdown > 0 && (
            <div
              className={`text-2xl font-mono font-black tabular-nums ${
                countdown <= 10 ? "text-red-400 animate-pulse" : ""
              }`}
            >
              {countdown}s
            </div>
          )}
        </div>

        {/* Body */}
        <div className="px-5 py-4 bg-[#080c16]">
          {injection.subject && (
            <div className="text-xs text-slate-400 mb-1">
              <span className="text-slate-500">Subject: </span>
              <span className="font-bold text-slate-200">{injection.subject}</span>
            </div>
          )}
          <p className="text-sm text-slate-200 leading-relaxed whitespace-pre-line mt-2">
            {injection.body}
          </p>
        </div>

        {/* Dismiss */}
        <div className="px-5 py-3 bg-[#060810] border-t border-slate-700/50 flex justify-between items-center">
          <span className="text-[10px] text-slate-500 uppercase tracking-wider">
            This message requires your attention
          </span>
          <button
            onClick={onDismiss}
            className="bg-slate-700 hover:bg-slate-600 text-white px-4 py-1.5 rounded text-xs uppercase tracking-widest font-bold transition-colors"
          >
            Acknowledge
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Gate Countdown display ───────────────────────────────────────────────────
function GateTimer({ seconds }: { seconds: number | undefined }) {
  const remaining = useCountdown(seconds, true);
  if (remaining == null) return null;
  const urgent = remaining <= 15;
  return (
    <div
      className={`flex items-center gap-2 px-3 py-1.5 rounded border ${
        urgent
          ? "bg-red-950/40 border-red-500/60 text-red-400 animate-pulse"
          : "bg-slate-900/60 border-slate-600/40 text-slate-300"
      }`}
    >
      <span className="text-[10px] uppercase tracking-widest font-bold">Time Remaining</span>
      <span className="font-mono font-black text-lg tabular-nums">{remaining}s</span>
      {urgent && <span className="text-[10px] text-red-500 font-bold">CRITICAL</span>}
    </div>
  );
}

// ── Main Page ────────────────────────────────────────────────────────────────
export default function SimulationRoomPage() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const navigate = useNavigate();

  if (!sessionId) return <Navigate to="/scenarios" replace />;

  const { user } = useAuthStore();
  const {
    alerts,
    currentGate,
    activePressureInjection,
    setActivePressureInjection,
    isPaused,
    isComplete,
    chatMessages,
    participants,
    votes,
    reset,
  } = useSimStore();

  const [session, setSessionData] = useState<SessionData | null>(null);
  const [notification, setNotification] = useState<{ kind: "success" | "error" | "info"; message: string } | null>(null);
  const [selectedOption, setSelectedOption] = useState<number | null>(null);
  const [decisionResult, setDecisionResult] = useState<{
    is_correct: boolean; rationale: string; consequence_applied: string; correct_index: number;
  } | null>(null);
  const [injectorOpen, setInjectorOpen] = useState(false);
  const [injectDesc, setInjectDesc] = useState("");
  const [injectSev, setInjectSev] = useState("high");
  const [injectSrc, setInjectSrc] = useState("FACILITATOR");
  const [tickerIndex, setTickerIndex] = useState(0);
  const [screenFlash, setScreenFlash] = useState(false);

  const alertsEndRef = useRef<HTMLDivElement>(null);
  const chatEndRef = useRef<HTMLDivElement>(null);
  const chatInput = useRef<HTMLInputElement>(null);

  // Ticker rotation
  useEffect(() => {
    const id = setInterval(() => setTickerIndex((i) => (i + 1) % TICKER_PHRASES.length), 4000);
    return () => clearInterval(id);
  }, []);

  // Flash screen red when a CRITICAL alert arrives
  useEffect(() => {
    const last = alerts[alerts.length - 1];
    if (last?.severity === "critical") {
      setScreenFlash(true);
      setTimeout(() => setScreenFlash(false), 600);
    }
  }, [alerts.length]);

  const { sendChat, startStream, submitVote, submitCommandDecision, togglePause, injectAlert } =
    useSimulationSocket(sessionId, {
      onDecisionResult: (result) => {
        setSelectedOption(null);
        setDecisionResult(result);
        setTimeout(() => setDecisionResult(null), 7000);
        notify(result.is_correct ? "success" : "error",
          result.is_correct ? "CORRECT — " + result.rationale : "WRONG CALL — " + result.rationale);
      },
      onNotification: notify,
      onPressureInjection: () => {/* stored in zustand via socket hook */},
    });

  useEffect(() => { reset(); fetchSession(); }, [sessionId]);
  useEffect(() => { alertsEndRef.current?.scrollIntoView({ behavior: "smooth" }); }, [alerts.length]);
  useEffect(() => { chatEndRef.current?.scrollIntoView({ behavior: "smooth" }); }, [chatMessages.length]);

  async function fetchSession() {
    try {
      const data = await api.get<SessionData>(`/sessions/${sessionId}`);
      setSessionData(data);
      if (data.status === "waiting") navigate(`/session/${sessionId}/lobby`);
    } catch (e: any) { notify("error", e.message || "Failed to load session"); }
  }

  function notify(kind: "success" | "error" | "info", message: string) {
    setNotification({ kind, message });
    setTimeout(() => setNotification(null), 6000);
  }

  const myRole = participants.find((p) => p.user_id === user?.id)?.role || "soc_analyst";
  const isCommander = myRole === "incident_commander";
  const isHost = session?.host_user_id === user?.id;

  async function handleStart() {
    try {
      if (session?.status !== "active") await api.post(`/sessions/${sessionId}/start`, {});
      startStream();
    } catch (e: any) { notify("error", e.message || "Failed to start stream"); }
  }

  async function handleViewDebrief() {
    try {
      await api.post(`/sessions/${sessionId}/complete`, {});
      navigate(`/session/${sessionId}/debrief`);
    } catch (e: any) { notify("error", e.message || "Failed to finalize"); }
  }

  function handleVote(idx: number) { setSelectedOption(idx); submitVote(idx); }

  function handleLockIn() {
    if (!currentGate || selectedOption === null) return;
    submitCommandDecision(currentGate.gate_id, selectedOption);
  }

  function handleInjectSend() {
    if (!injectDesc.trim()) return;
    injectAlert({
      timestamp: new Date().toLocaleTimeString(),
      severity: injectSev,
      source_system: injectSrc,
      rule_id: "INJECT-99",
      description: injectDesc,
      raw_log: `FACILITATOR_INJECT [uid=${user?.id}]`,
    });
    setInjectDesc("");
    setInjectorOpen(false);
    notify("success", "Alert injected to all participants");
  }

  const handleChatKey = useCallback((e: React.KeyboardEvent) => {
    if (e.key === "Enter" && chatInput.current?.value) {
      sendChat(chatInput.current.value);
      chatInput.current.value = "";
    }
  }, [sendChat]);

  const totalVotes = Object.keys(votes).length;
  const votersForOption = (idx: number) => participants.filter((p) => votes[p.user_id] === idx);

  const NOTIF_CLS = {
    success: "bg-green-950/95 border-green-500 text-green-300",
    error:   "bg-red-950/95 border-red-500 text-red-300",
    info:    "bg-blue-950/95 border-blue-500 text-blue-300",
  };

  return (
    <div className="min-h-screen bg-[#040712] flex flex-col font-mono text-slate-200 overflow-hidden relative">

      {/* Full-screen red flash on CRITICAL alert */}
      {screenFlash && (
        <div className="fixed inset-0 z-[100] bg-red-600/20 pointer-events-none transition-opacity duration-300" />
      )}

      {/* Pressure Injection Modal */}
      {activePressureInjection && (
        <PressureModal
          injection={activePressureInjection}
          onDismiss={() => setActivePressureInjection(null)}
        />
      )}

      {/* Toast notification */}
      {notification && (
        <div className={`fixed top-4 right-4 z-40 border rounded-lg px-4 py-3 text-xs max-w-sm shadow-2xl border-l-4 leading-relaxed ${NOTIF_CLS[notification.kind]}`}>
          {notification.message}
        </div>
      )}

      {/* ── Breaking news ticker ────────────────────────────────── */}
      <div className="bg-red-900/80 border-b border-red-700 px-0 py-1 flex items-center overflow-hidden">
        <div className="bg-red-600 text-white text-[10px] font-black uppercase tracking-widest px-3 py-1 mr-3 shrink-0">
          LIVE
        </div>
        <div className="text-[11px] text-red-100 font-bold uppercase tracking-widest truncate animate-pulse">
          {TICKER_PHRASES[tickerIndex]}
        </div>
        <div className="ml-auto text-[10px] text-red-300 shrink-0 pr-3">
          {new Date().toLocaleTimeString()}
        </div>
      </div>

      {/* ── Top command bar ─────────────────────────────────────── */}
      <div className="border-b border-slate-800 bg-slate-950/90 backdrop-blur-md px-5 py-2.5 flex items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <span className="text-red-500 font-black text-sm uppercase tracking-widest">
            BREACH REPLAY
          </span>
          <span className="text-slate-600">|</span>
          <span className="text-slate-500 text-xs">Session {sessionId?.slice(0, 8)}</span>
          <span className="text-slate-600">|</span>

          {isComplete ? (
            <span className="bg-green-500/20 text-green-400 border border-green-500/40 px-2 py-0.5 rounded text-[10px] uppercase font-bold tracking-wider">
              COMPLETE
            </span>
          ) : isPaused && currentGate ? (
            <span className="bg-red-500/20 text-red-400 border border-red-500/60 px-2 py-0.5 rounded text-[10px] uppercase font-bold tracking-wider animate-pulse">
              ⚠ DECISION REQUIRED
            </span>
          ) : isPaused ? (
            <span className="bg-yellow-500/20 text-yellow-400 border border-yellow-500/40 px-2 py-0.5 rounded text-[10px] uppercase font-bold tracking-wider">
              PAUSED
            </span>
          ) : alerts.length > 0 ? (
            <span className="bg-blue-500/20 text-blue-400 border border-blue-500/40 px-2 py-0.5 rounded text-[10px] uppercase font-bold tracking-wider animate-pulse">
              ● STREAMING {alerts.length} EVENTS
            </span>
          ) : (
            <span className="text-slate-500 text-[10px] uppercase tracking-wider">STANDBY</span>
          )}
        </div>

        <div className="flex items-center gap-2">
          {isComplete ? (
            <button
              onClick={handleViewDebrief}
              className="bg-red-600 hover:bg-red-500 text-white px-4 py-1.5 rounded text-xs uppercase tracking-widest font-bold transition-colors"
            >
              View Debrief
            </button>
          ) : isHost && alerts.length === 0 ? (
            <button
              onClick={handleStart}
              className="bg-green-600 hover:bg-green-500 text-black px-5 py-1.5 rounded text-xs uppercase tracking-widest font-black transition-colors shadow-[0_0_20px_rgba(34,197,94,0.4)] animate-pulse"
            >
              INITIATE SIMULATION
            </button>
          ) : null}
        </div>
      </div>

      {/* ── Participant presence bar ────────────────────────────── */}
      <div className="bg-slate-950/70 border-b border-slate-800/60 px-5 py-1.5 flex items-center gap-3 overflow-x-auto">
        <span className="text-[9px] text-slate-600 uppercase tracking-wider shrink-0">WAR ROOM:</span>
        {participants.map((p) => {
          const isCMD = p.role === "incident_commander";
          const cls = isCMD
            ? "border-red-500/50 text-red-400 bg-red-950/20"
            : p.role === "forensic_analyst"
            ? "border-blue-500/50 text-blue-400 bg-blue-950/20"
            : p.role === "communications_lead"
            ? "border-yellow-500/50 text-yellow-400 bg-yellow-950/20"
            : "border-green-500/50 text-green-400 bg-green-950/20";
          return (
            <div
              key={p.user_id}
              className={`flex items-center gap-1.5 px-2 py-0.5 rounded border text-[9px] font-bold shrink-0 ${cls} ${
                p.online ? "opacity-100" : "opacity-30 line-through"
              }`}
            >
              <div className={`w-1.5 h-1.5 rounded-full ${p.online ? "bg-green-400 animate-pulse" : "bg-slate-600"}`} />
              {p.name.slice(0, 14)} [{p.role.replace(/_/g, " ").toUpperCase()}]
            </div>
          );
        })}
        {participants.length === 0 && (
          <span className="text-[9px] text-slate-600">No participants connected yet</span>
        )}
      </div>

      {/* ── Main 3-column layout ─────────────────────────────────── */}
      <div className="flex flex-1 overflow-hidden">

        {/* COL 1: Alert feed */}
        <div className="flex-1 flex flex-col overflow-hidden border-r border-slate-800">
          <div className="px-4 py-2 bg-slate-950/50 border-b border-slate-800 flex items-center justify-between shrink-0">
            <span className="text-[10px] text-slate-500 uppercase tracking-widest">
              SIEM / Threat Intelligence Feed
            </span>
            <span className="text-[10px] text-slate-600">{alerts.length} events</span>
          </div>

          <div className="flex-1 overflow-y-auto p-3 space-y-1.5">
            {alerts.map((alert, i) => (
              <div
                key={i}
                className={`border border-slate-800 border-l-4 px-3 py-2 rounded text-[11px] ${
                  SEV_BORDER[alert.severity] || "border-l-slate-600"
                } ${i === alerts.length - 1 ? "ring-1 ring-slate-600/40" : ""}`}
              >
                <div className="flex items-center gap-2 mb-1">
                  <span className={`text-[9px] font-black uppercase px-1.5 py-0.5 rounded ${SEV_BADGE[alert.severity] || "bg-slate-700 text-slate-300"}`}>
                    {alert.severity}
                  </span>
                  <span className="text-slate-500 text-[9px]">{alert.timestamp}</span>
                  <span className="text-slate-600 text-[9px]">·</span>
                  <span className="text-slate-400 text-[9px] font-bold uppercase">{alert.source_system}</span>
                  <span className="text-slate-600 text-[9px]">·</span>
                  <span className="text-slate-600 text-[9px]">{alert.rule_id}</span>
                </div>
                <p className="text-slate-200 leading-relaxed">{alert.description}</p>
                {alert.raw_log && (
                  <p className="text-[9px] text-slate-600 mt-1 truncate">
                    {alert.raw_log}
                  </p>
                )}
              </div>
            ))}

            {alerts.length === 0 && (
              <div className="flex flex-col items-center justify-center h-full py-20 text-slate-700">
                <div className="text-4xl mb-3">⚡</div>
                <p className="text-xs uppercase tracking-widest">Awaiting incident feed...</p>
                {isHost && (
                  <p className="text-[10px] text-slate-600 mt-2">
                    Click INITIATE SIMULATION above to begin
                  </p>
                )}
              </div>
            )}
            <div ref={alertsEndRef} />
          </div>
        </div>

        {/* COL 2: Decision gate + facilitator panel */}
        <div className="w-[420px] shrink-0 flex flex-col border-r border-slate-800 overflow-hidden">

          {/* Decision gate */}
          {isPaused && currentGate ? (
            <div className="border-b border-red-900/60 bg-red-950/10 p-4 shrink-0">
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2">
                  <div className="w-2.5 h-2.5 rounded-full bg-red-500 animate-ping" />
                  <span className="text-[10px] text-red-400 font-black uppercase tracking-widest">
                    TACTICAL DECISION REQUIRED
                  </span>
                </div>
                <GateTimer seconds={currentGate.countdown_seconds} />
              </div>

              {currentGate.urgency_level && (
                <div className="text-[9px] uppercase tracking-wider text-red-500 font-bold mb-2">
                  Urgency: {currentGate.urgency_level}
                </div>
              )}

              <div className="bg-[#08091a] border border-red-900/40 rounded p-3 mb-3 text-xs text-slate-200 leading-relaxed">
                {currentGate.context_summary}
              </div>

              <div className="space-y-2">
                {currentGate.options.map((opt) => {
                  const voters = votersForOption(opt.index);
                  const pct = totalVotes > 0 ? Math.round((voters.length / totalVotes) * 100) : 0;
                  const selected = selectedOption === opt.index;

                  return (
                    <button
                      key={opt.index}
                      onClick={() => handleVote(opt.index)}
                      className={`w-full text-left border rounded p-3 text-xs transition-all duration-200 relative overflow-hidden ${
                        selected
                          ? "border-blue-500/70 bg-blue-950/20 shadow-[0_0_12px_rgba(59,130,246,0.2)]"
                          : "border-slate-700/60 bg-slate-900/40 hover:border-slate-600"
                      }`}
                    >
                      {/* Vote bar background */}
                      <div
                        className="absolute inset-y-0 left-0 bg-blue-900/20 transition-all duration-500"
                        style={{ width: `${pct}%` }}
                      />
                      <div className="relative flex justify-between items-start gap-2">
                        <span className="leading-relaxed">
                          <span className="text-blue-400 font-bold mr-2">
                            {String.fromCharCode(65 + opt.index)}.
                          </span>
                          {opt.text}
                        </span>
                        <span className="text-[9px] font-black text-slate-400 shrink-0 bg-slate-900 px-1.5 py-0.5 rounded">
                          {pct}%
                        </span>
                      </div>
                      {voters.length > 0 && (
                        <div className="relative flex flex-wrap gap-1 mt-1.5">
                          {voters.map((v) => (
                            <span
                              key={v.user_id}
                              className="text-[8px] bg-blue-950/40 text-blue-400 border border-blue-800/40 px-1.5 py-0.5 rounded font-bold"
                            >
                              {v.name.slice(0, 12)}
                            </span>
                          ))}
                        </div>
                      )}
                    </button>
                  );
                })}
              </div>

              {isCommander ? (
                <div className="mt-3 pt-3 border-t border-red-900/40">
                  <button
                    onClick={handleLockIn}
                    disabled={selectedOption === null}
                    className="w-full bg-red-700 hover:bg-red-600 disabled:opacity-30 disabled:cursor-not-allowed text-white py-2 rounded text-xs uppercase tracking-widest font-black transition-colors shadow-[0_0_15px_rgba(239,68,68,0.3)]"
                  >
                    LOCK IN COMMAND DECISION
                  </button>
                  <p className="text-[8px] text-slate-600 text-center mt-1">
                    Final authority rests with Incident Commander
                  </p>
                </div>
              ) : (
                <p className="mt-3 text-center text-[10px] text-yellow-500 animate-pulse">
                  Your vote is cast. Awaiting Incident Commander...
                </p>
              )}
            </div>
          ) : null}

          {/* Decision result banner */}
          {decisionResult && !currentGate && (
            <div
              className={`p-4 border-b shrink-0 ${
                decisionResult.is_correct
                  ? "bg-green-950/20 border-green-800/40"
                  : "bg-red-950/20 border-red-800/40"
              }`}
            >
              <div className="flex items-center gap-2 mb-2">
                <span className={`text-lg ${decisionResult.is_correct ? "text-green-400" : "text-red-400"}`}>
                  {decisionResult.is_correct ? "✓" : "✗"}
                </span>
                <span className={`text-[10px] font-black uppercase tracking-widest ${decisionResult.is_correct ? "text-green-400" : "text-red-400"}`}>
                  {decisionResult.is_correct ? "CORRECT DECISION" : "WRONG CALL"}
                </span>
              </div>
              <p className="text-xs text-slate-300 leading-relaxed mb-2">{decisionResult.rationale}</p>
              <p className={`text-[10px] font-bold ${decisionResult.is_correct ? "text-green-400" : "text-red-400"}`}>
                Consequence: {decisionResult.consequence_applied}
              </p>
            </div>
          )}

          {/* Facilitator controls */}
          {(isCommander || isHost) && !isComplete && (
            <div className="p-4 border-b border-slate-800/60 bg-slate-950/30 shrink-0">
              <div className="flex items-center justify-between mb-3">
                <span className="text-[9px] text-slate-500 uppercase tracking-widest font-bold">
                  FACILITATOR CONSOLE
                </span>
                <button
                  onClick={togglePause}
                  className={`px-3 py-1 border rounded text-[9px] uppercase font-bold transition-colors ${
                    isPaused
                      ? "bg-yellow-950/40 border-yellow-600/50 text-yellow-400"
                      : "bg-green-950/40 border-green-600/50 text-green-400"
                  }`}
                >
                  {isPaused ? "Resume" : "Pause"} Stream
                </button>
              </div>

              {injectorOpen ? (
                <div className="space-y-2 bg-slate-900/60 rounded border border-slate-700/50 p-3">
                  <textarea
                    value={injectDesc}
                    onChange={(e) => setInjectDesc(e.target.value)}
                    placeholder="Describe the injected alert..."
                    rows={2}
                    className="w-full bg-[#060810] border border-slate-700 text-slate-200 text-xs p-2 rounded resize-none focus:outline-none focus:border-blue-500"
                  />
                  <div className="grid grid-cols-2 gap-2">
                    <select
                      value={injectSev}
                      onChange={(e) => setInjectSev(e.target.value)}
                      className="bg-[#060810] border border-slate-700 text-slate-300 text-xs p-1.5 rounded"
                    >
                      <option value="low">Low</option>
                      <option value="medium">Medium</option>
                      <option value="high">High</option>
                      <option value="critical">Critical</option>
                    </select>
                    <input
                      value={injectSrc}
                      onChange={(e) => setInjectSrc(e.target.value)}
                      placeholder="Source system"
                      className="bg-[#060810] border border-slate-700 text-slate-300 text-xs p-1.5 rounded"
                    />
                  </div>
                  <div className="flex gap-2">
                    <button
                      onClick={handleInjectSend}
                      className="flex-1 bg-blue-700 hover:bg-blue-600 text-white py-1.5 rounded text-[10px] uppercase font-bold"
                    >
                      Broadcast Alert
                    </button>
                    <button
                      onClick={() => setInjectorOpen(false)}
                      className="bg-slate-800 border border-slate-700 text-slate-400 px-3 py-1.5 rounded text-[10px] uppercase"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              ) : (
                <button
                  onClick={() => setInjectorOpen(true)}
                  className="w-full border border-dashed border-slate-700 hover:border-blue-500/50 text-slate-600 hover:text-blue-400 py-2 rounded text-[10px] uppercase tracking-widest font-bold transition-all"
                >
                  + Inject Facilitator Alert
                </button>
              )}
            </div>
          )}

          {/* Flex fill spacer when no gate */}
          <div className="flex-1" />
        </div>

        {/* COL 3: Tactical comms chat */}
        <div className="w-[300px] shrink-0 flex flex-col overflow-hidden">
          <div className="px-4 py-2 bg-slate-950/50 border-b border-slate-800 flex items-center justify-between shrink-0">
            <span className="text-[10px] text-slate-500 uppercase tracking-widest">Tactical Comms</span>
            <div className="w-1.5 h-1.5 rounded-full bg-green-400 animate-pulse" />
          </div>

          <div className="flex-1 overflow-y-auto p-3 space-y-2">
            {chatMessages.map((msg, i) => {
              const isAI = msg.role === "ai_facilitator";
              const isCMD = msg.role === "incident_commander";
              const cls = isAI ? "text-purple-400"
                : isCMD ? "text-red-400"
                : msg.role === "forensic_analyst" ? "text-blue-400"
                : msg.role === "communications_lead" ? "text-yellow-400"
                : "text-green-400";
              return (
                <div
                  key={i}
                  className={`border rounded p-2 text-[11px] ${
                    isAI
                      ? "bg-purple-950/30 border-purple-700/40"
                      : "bg-slate-900/40 border-slate-800/60"
                  }`}
                >
                  <div className="flex justify-between items-center mb-1">
                    <span className={`font-bold text-[9px] ${cls}`}>
                      {isAI ? "⚡ AI FACILITATOR" : (msg.name || msg.user_id.slice(0, 8)).toUpperCase()}
                      {!isAI && (
                        <span className="opacity-50 font-normal ml-1">
                          [{(msg.role || "analyst").replace(/_/g, " ").toUpperCase()}]
                        </span>
                      )}
                    </span>
                    <span className="text-[8px] text-slate-600">
                      {msg.ts ? new Date(msg.ts).toLocaleTimeString() : ""}
                    </span>
                  </div>
                  <p className={`leading-relaxed ${isAI ? "text-purple-200" : "text-slate-300"}`}>{msg.text}</p>
                </div>
              );
            })}
            {chatMessages.length === 0 && (
              <p className="text-[10px] text-slate-700 text-center pt-8 uppercase tracking-wider">
                Channel open — coordinate containment
              </p>
            )}
            <div ref={chatEndRef} />
          </div>

          <div className="p-3 border-t border-slate-800 bg-slate-950/40 shrink-0">
            <input
              ref={chatInput}
              onKeyDown={handleChatKey}
              placeholder="Type message, Enter to send..."
              className="w-full bg-[#060810] border border-slate-700 text-slate-200 text-xs px-3 py-2 rounded focus:outline-none focus:border-blue-500 transition-colors"
            />
            <p className="text-[8px] text-slate-700 mt-1 text-center uppercase tracking-wider">
              {myRole.replace(/_/g, " ").toUpperCase()} — {user?.email}
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
