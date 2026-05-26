import { useEffect, useRef, useState } from "react";
import { Navigate, useNavigate, useParams } from "react-router-dom";
import { useSimStore } from "../store/simulation";
import { useSimulationSocket } from "../lib/useSimulationSocket";
import { useAuthStore } from "../store/auth";
import { api } from "../lib/api";

const SEVERITY_COLORS: Record<string, string> = {
  critical: "border-l-breach-accent text-breach-accent bg-red-950/10 shadow-[inset_0_0_10px_rgba(239,68,68,0.05)]",
  high: "border-l-orange-500 text-orange-400 bg-orange-950/10 shadow-[inset_0_0_10px_rgba(249,115,22,0.05)]",
  medium: "border-l-breach-yellow text-breach-yellow bg-yellow-950/10 shadow-[inset_0_0_10px_rgba(234,179,8,0.05)]",
  low: "border-l-breach-blue text-breach-blue bg-blue-950/10 shadow-[inset_0_0_10px_rgba(59,130,246,0.05)]",
};

interface Notification {
  kind: "success" | "error" | "info";
  message: string;
}

const NOTIFICATION_COLORS: Record<Notification["kind"], string> = {
  success: "bg-green-950/90 border-breach-green text-breach-green shadow-[0_0_15px_rgba(34,197,94,0.1)]",
  error: "bg-red-950/90 border-breach-accent text-breach-accent shadow-[0_0_15px_rgba(239,68,68,0.1)]",
  info: "bg-blue-950/90 border-breach-blue text-breach-blue shadow-[0_0_15px_rgba(59,130,246,0.1)]",
};

interface SessionData {
  id: string;
  scenario_id: string;
  host_user_id: string;
  status: string;
  mode: string;
}

export default function SimulationRoomPage() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const navigate = useNavigate();

  if (!sessionId) {
    return <Navigate to="/scenarios" replace />;
  }
  const { user } = useAuthStore();
  const {
    alerts,
    currentGate,
    isPaused,
    isComplete,
    chatMessages,
    participants,
    votes,
    reset,
  } = useSimStore();

  const [session, setSessionData] = useState<SessionData | null>(null);
  const [notification, setNotification] = useState<Notification | null>(null);
  const [selectedOption, setSelectedOption] = useState<number | null>(null);

  // Injector state
  const [injectDescription, setInjectDescription] = useState("");
  const [injectSeverity, setInjectSeverity] = useState("high");
  const [injectSource, setInjectSource] = useState("FACILITATOR");
  const [showInjectPanel, setShowInjectPanel] = useState(false);

  const alertsEndRef = useRef<HTMLDivElement>(null);
  const chatEndRef = useRef<HTMLDivElement>(null);
  const chatInput = useRef<HTMLInputElement>(null);

  // Establish real-time multiplayer WebSocket triggers
  const {
    sendChat,
    startStream,
    submitVote,
    submitCommandDecision,
    togglePause,
    injectAlert,
  } = useSimulationSocket(sessionId, {
    onDecisionResult: (result) => {
      setSelectedOption(null);
      notify(
        result.is_correct ? "success" : "error",
        `${result.is_correct ? "CORRECT DECISION LOCKED IN" : "INCORRECT DECISION LOCKED IN"}: ${
          result.rationale
        }`
      );
    },
    onNotification: (kind, message) => {
      notify(kind, message);
    },
  });

  // BUG-07: Reset stale state and load session details
  useEffect(() => {
    reset();
    fetchSessionDetails();
  }, [sessionId]);

  useEffect(() => {
    alertsEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [alerts]);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chatMessages]);

  async function fetchSessionDetails() {
    try {
      const data = await api.get<SessionData>(`/sessions/${sessionId}`);
      setSessionData(data);
      if (data.status === "waiting") {
        navigate(`/session/${sessionId}/lobby`);
      }
    } catch (err: any) {
      notify("error", err.message || "Failed to load session data");
    }
  }

  function notify(kind: Notification["kind"], message: string) {
    setNotification({ kind, message });
    setTimeout(() => setNotification(null), 5000);
  }

  // Determine who I am
  const myParticipant = participants.find((p) => p.user_id === user?.id);
  const myRole = myParticipant?.role || "soc_analyst";
  const isCommander = myRole === "incident_commander";
  const isHost = session?.host_user_id === user?.id;

  async function handleStart() {
    try {
      if (session?.status !== "active") {
        await api.post(`/sessions/${sessionId}/start`, {});
      }
      startStream();
    } catch (err: any) {
      notify("error", err.message || "Failed to start simulation alert stream");
    }
  }

  async function handleViewDebrief() {
    try {
      await api.post(`/sessions/${sessionId}/complete`, {});
      navigate(`/session/${sessionId}/debrief`);
    } catch (err: any) {
      notify("error", err.message || "Failed to finalize simulation and generate debrief");
    }
  }

  function handleCastVote(optionIndex: number) {
    setSelectedOption(optionIndex);
    submitVote(optionIndex);
  }

  function handleLockIn() {
    if (!currentGate || selectedOption === null) return;
    submitCommandDecision(currentGate.gate_id, selectedOption);
  }

  function handleSendInjectAlert() {
    if (!injectDescription.trim()) return;
    const payload = {
      timestamp: new Date().toLocaleTimeString(),
      severity: injectSeverity,
      source_system: injectSource,
      rule_id: "INJECT-MAPPED-99",
      description: injectDescription,
      raw_log: `FACILITATOR_MANUAL_INJECT [operator_id=${user?.id}]`,
    };
    injectAlert(payload);
    setInjectDescription("");
    setShowInjectPanel(false);
    notify("success", "Custom security inject broadcasted to operations roster!");
  }

  function handleChat(e: React.KeyboardEvent) {
    if (e.key === "Enter" && chatInput.current?.value) {
      sendChat(chatInput.current.value);
      chatInput.current.value = "";
    }
  }

  // Calculate vote metrics for each option
  const totalVotes = Object.keys(votes).length;
  const getVotesForOption = (idx: number) => {
    return participants.filter((p) => votes[p.user_id] === idx);
  };

  return (
    <div className="min-h-screen bg-breach-bg flex flex-col font-mono text-breach-text">
      {notification && (
        <div
          className={`fixed top-4 right-4 z-50 border rounded-lg px-4 py-3 text-xs max-w-md shadow-2xl backdrop-blur-md transition-all duration-300 border-l-4 leading-relaxed ${
            NOTIFICATION_COLORS[notification.kind]
          }`}
        >
          {notification.message}
        </div>
      )}

      {/* Header bar */}
      <div className="border-b border-breach-border bg-breach-surface/80 backdrop-blur-md px-6 py-3 flex items-center justify-between">
        <div className="flex items-center gap-4">
          <span className="text-breach-accent font-extrabold text-sm uppercase tracking-widest animate-pulse">
            BREACH REPLAY // IR WORKSTATION
          </span>
          <span className="text-breach-muted text-xs">|</span>
          <span className="text-breach-muted text-xs">Session: {sessionId?.slice(0, 8)}...</span>
          {isComplete ? (
            <span className="bg-breach-green/20 text-breach-green border border-breach-green/40 px-2 py-0.5 rounded text-[10px] uppercase font-bold tracking-wider animate-pulse">
              SIMULATION COMPLETE
            </span>
          ) : isPaused ? (
            <span className="bg-breach-yellow/20 text-breach-yellow border border-breach-yellow/40 px-2 py-0.5 rounded text-[10px] uppercase font-bold tracking-wider">
              OPERATIONS PAUSED
            </span>
          ) : (
            <span className="bg-breach-blue/20 text-breach-blue border border-breach-blue/40 px-2 py-0.5 rounded text-[10px] uppercase font-bold tracking-wider animate-pulse">
              LIVE FIRES STREAMING
            </span>
          )}
        </div>
        <div className="flex gap-3">
          {isComplete ? (
            <button
              onClick={handleViewDebrief}
              className="bg-breach-accent hover:bg-red-600 text-white px-4 py-1.5 rounded text-xs uppercase tracking-widest transition-colors font-bold shadow-[0_0_15px_rgba(239,68,68,0.4)] hover:scale-105"
            >
              View Debrief Report
            </button>
          ) : isHost && alerts.length === 0 ? (
            <button
              onClick={handleStart}
              className="bg-breach-green hover:bg-green-600 text-black px-4 py-1.5 rounded text-xs uppercase tracking-widest transition-colors font-bold shadow-[0_0_15px_rgba(34,197,94,0.3)] hover:scale-105"
            >
              Start Alert Stream
            </button>
          ) : null}
        </div>
      </div>

      {/* Floating Team Presence Bar */}
      <div className="bg-slate-950/60 border-b border-breach-border px-6 py-2 flex items-center justify-between gap-4">
        <div className="text-[10px] text-breach-muted uppercase tracking-wider">
          Operations Desks Connection Status:
        </div>
        <div className="flex flex-wrap gap-2.5">
          {participants.map((p) => {
            const isCommanderDesk = p.role === "incident_commander";
            const roleColor = isCommanderDesk
              ? "text-red-400 border-red-500/40 bg-red-950/20"
              : p.role === "forensic_analyst"
              ? "text-blue-400 border-blue-500/40 bg-blue-950/20"
              : p.role === "communications_lead"
              ? "text-yellow-400 border-yellow-500/40 bg-yellow-950/20"
              : p.role === "soc_analyst"
              ? "text-green-400 border-green-500/40 bg-green-950/20"
              : "text-slate-400 border-slate-500/40 bg-slate-950/40";

            return (
              <div
                key={p.user_id}
                title={`${p.name} - ${p.online ? "Online" : "Offline"}`}
                className={`flex items-center gap-1.5 px-2.5 py-0.5 rounded border text-[10px] font-bold ${roleColor} ${
                  p.online ? "opacity-100" : "opacity-40 line-through"
                }`}
              >
                <div
                  className={`w-1.5 h-1.5 rounded-full ${
                    p.online ? "bg-breach-green animate-pulse" : "bg-slate-600"
                  }`}
                />
                <span>
                  {p.name.slice(0, 15)} [{p.role.replace("_", " ").toUpperCase()}]
                </span>
              </div>
            );
          })}
        </div>
      </div>

      {/* Workstation layout */}
      <div className="flex flex-1 overflow-hidden">
        {/* Left Side: Real-Time Cyber Alert Feed */}
        <div className="flex-1 flex flex-col overflow-hidden bg-[#060810]">
          <div className="px-4 py-2.5 border-b border-breach-border bg-slate-950/30 flex items-center justify-between">
            <span className="text-xs text-breach-muted uppercase tracking-wider">
              🚨 Active Cyber Threat Alert Feed
            </span>
            <span className="text-xs text-breach-muted">{alerts.length} threats logged</span>
          </div>
          <div className="flex-1 overflow-y-auto p-4 space-y-2 font-mono">
            {alerts.map((alert, i) => (
              <div
                key={i}
                className={`bg-breach-surface/60 border border-breach-border border-l-4 px-4 py-2.5 rounded-md hover:border-breach-border/80 transition-colors ${
                  SEVERITY_COLORS[alert.severity] || ""
                }`}
              >
                <div className="flex items-center gap-3 mb-1.5 text-[10px]">
                  <span className="text-breach-muted">{alert.timestamp}</span>
                  <span className="text-xs uppercase font-extrabold tracking-wider">{alert.severity}</span>
                  <span className="text-breach-muted">›</span>
                  <span className="text-breach-muted uppercase font-bold">{alert.source_system}</span>
                  <span className="text-breach-muted">›</span>
                  <span className="text-breach-muted font-bold">{alert.rule_id}</span>
                </div>
                <p className="text-xs text-breach-text leading-relaxed">{alert.description}</p>
                {alert.raw_log && (
                  <p className="text-[10px] text-breach-muted mt-1.5 opacity-50 bg-slate-950/40 px-2 py-1 rounded truncate">
                    LOG_DECRYPTION: {alert.raw_log}
                  </p>
                )}
              </div>
            ))}
            {alerts.length === 0 && (
              <div className="h-full flex flex-col items-center justify-center text-breach-muted">
                <svg className="w-8 h-8 mb-2 animate-bounce" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M13 10V3L4 14h7v7l9-11h-7z" />
                </svg>
                <span className="text-xs uppercase tracking-wider">Awaiting threat operations kickoff...</span>
              </div>
            )}
            <div ref={alertsEndRef} />
          </div>
        </div>

        {/* Right Side: Command Console & Decisions Desk */}
        <div className="w-[450px] border-l border-breach-border flex flex-col bg-breach-surface/40 backdrop-blur-md">
          {/* Active Decision Gate Card */}
          {isPaused && currentGate ? (
            <div className="p-5 border-b border-breach-border bg-slate-900/30">
              <div className="flex items-center gap-2 mb-2">
                <span className="w-2 h-2 rounded-full bg-breach-accent animate-ping" />
                <span className="text-xs text-breach-accent uppercase tracking-widest font-extrabold">
                  Tactical Decision Required
                </span>
              </div>
              <p className="text-xs text-breach-text mb-4 leading-relaxed bg-[#0b0f19] p-3 rounded border border-breach-border/60">
                {currentGate.context_summary}
              </p>
              <div className="space-y-2">
                {currentGate.options.map((opt) => {
                  const optionVoters = getVotesForOption(opt.index);
                  const isOptionSelectedByMe = selectedOption === opt.index;
                  const optionPercentage =
                    totalVotes > 0 ? Math.round((optionVoters.length / totalVotes) * 100) : 0;

                  return (
                    <div
                      key={opt.index}
                      onClick={() => handleCastVote(opt.index)}
                      className={`w-full text-left bg-slate-950/40 border p-3 rounded cursor-pointer transition-all duration-300 relative group overflow-hidden ${
                        isOptionSelectedByMe
                          ? "border-breach-blue bg-blue-950/10 shadow-[0_0_12px_rgba(59,130,246,0.15)]"
                          : "border-breach-border hover:border-breach-muted"
                      }`}
                    >
                      <div className="flex justify-between items-start gap-4 mb-2">
                        <div className="text-xs text-breach-text leading-relaxed">
                          <span className="text-breach-blue font-bold mr-2">
                            {String.fromCharCode(65 + opt.index)}.
                          </span>
                          {opt.text}
                        </div>
                        <div className="text-[10px] text-breach-muted font-bold block bg-slate-900 px-1.5 py-0.5 rounded border border-breach-border/60">
                          {optionPercentage}%
                        </div>
                      </div>

                      {/* Vote badges presence bar */}
                      <div className="flex flex-wrap gap-1.5 items-center mt-2.5">
                        {optionVoters.map((v) => (
                          <span
                            key={v.user_id}
                            className="bg-breach-blue/15 text-breach-blue border border-breach-blue/30 px-2 py-0.5 rounded text-[9px] font-bold"
                          >
                            {v.name.slice(0, 12)}
                          </span>
                        ))}
                      </div>
                    </div>
                  );
                })}
              </div>

              {/* Commander specific action trigger */}
              {isCommander ? (
                <div className="mt-4 border-t border-breach-border/50 pt-4">
                  <button
                    onClick={handleLockIn}
                    disabled={selectedOption === null}
                    className="w-full bg-breach-accent hover:bg-red-600 disabled:opacity-40 text-white py-2 rounded text-xs uppercase tracking-widest font-bold transition-all duration-300 shadow-[0_0_15px_rgba(239,68,68,0.2)]"
                  >
                    Lock In Command Decision
                  </button>
                  <p className="text-[9px] text-breach-muted text-center mt-1.5">
                    * Final command authority is locked to the Incident Commander desk.
                  </p>
                </div>
              ) : (
                <div className="mt-3 text-center">
                  <span className="text-[10px] text-breach-yellow animate-pulse">
                    Cast your analyst vote. Awaiting Incident Commander to lock decision...
                  </span>
                </div>
              )}
            </div>
          ) : null}

          {/* Commander Facilitator Control Panel (only visible to commander or host) */}
          {(isCommander || isHost) && !isComplete && (
            <div className="p-5 border-b border-breach-border bg-slate-950/20">
              <div className="flex items-center justify-between gap-4 mb-4">
                <span className="text-xs text-breach-muted uppercase tracking-widest font-bold">
                  🛠️ Facilitator Console
                </span>
                <button
                  onClick={togglePause}
                  className={`px-3 py-1.5 border rounded text-[10px] uppercase font-bold transition-colors ${
                    isPaused
                      ? "bg-breach-yellow/20 border-breach-yellow text-breach-yellow"
                      : "bg-breach-green/20 border-breach-green text-breach-green"
                  }`}
                >
                  {isPaused ? "Resume Stream" : "Pause Stream"}
                </button>
              </div>

              {/* Security Alert Inject form */}
              {showInjectPanel ? (
                <div className="space-y-3 p-3.5 bg-slate-950/50 rounded border border-breach-border">
                  <div>
                    <label className="block text-[9px] text-breach-muted uppercase tracking-wider mb-1">
                      Inject Description
                    </label>
                    <textarea
                      value={injectDescription}
                      onChange={(e) => setInjectDescription(e.target.value)}
                      placeholder="Malicious beaconing / ransomware note log..."
                      rows={2}
                      className="w-full bg-breach-bg border border-breach-border text-breach-text text-xs p-2 rounded focus:outline-none focus:border-breach-blue"
                    />
                  </div>
                  <div className="grid grid-cols-2 gap-2">
                    <div>
                      <label className="block text-[9px] text-breach-muted uppercase tracking-wider mb-1">
                        Severity
                      </label>
                      <select
                        value={injectSeverity}
                        onChange={(e) => setInjectSeverity(e.target.value)}
                        className="w-full bg-breach-bg border border-breach-border text-breach-text text-xs p-1.5 rounded"
                      >
                        <option value="low">Low</option>
                        <option value="medium">Medium</option>
                        <option value="high">High</option>
                        <option value="critical">Critical</option>
                      </select>
                    </div>
                    <div>
                      <label className="block text-[9px] text-breach-muted uppercase tracking-wider mb-1">
                        Source
                      </label>
                      <input
                        value={injectSource}
                        onChange={(e) => setInjectSource(e.target.value)}
                        className="w-full bg-breach-bg border border-breach-border text-breach-text text-xs p-1.5 rounded"
                      />
                    </div>
                  </div>
                  <div className="flex gap-2">
                    <button
                      onClick={handleSendInjectAlert}
                      className="flex-1 bg-breach-blue hover:bg-blue-600 text-white py-1.5 rounded text-[10px] uppercase font-bold"
                    >
                      Broadcast Inject
                    </button>
                    <button
                      onClick={() => setShowInjectPanel(false)}
                      className="bg-breach-surface border border-breach-border text-breach-muted px-3 py-1.5 rounded text-[10px] uppercase"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              ) : (
                <button
                  onClick={() => setShowInjectPanel(true)}
                  className="w-full border border-dashed border-breach-border hover:border-breach-blue text-breach-muted hover:text-breach-blue py-2 rounded text-xs uppercase font-bold transition-all duration-300"
                >
                  + Inject Facilitator Alert
                </button>
              )}
            </div>
          )}

          {/* Live Operations Chat */}
          <div className="flex-1 flex flex-col overflow-hidden">
            <div className="px-4 py-2 border-b border-breach-border bg-slate-950/20 flex justify-between items-center">
              <span className="text-xs text-breach-muted uppercase tracking-wider">
                🗣️ Tactical Comms Chat
              </span>
              <span className="text-[10px] text-breach-muted">active lane</span>
            </div>
            <div className="flex-grow overflow-y-auto p-4 space-y-3">
              {chatMessages.map((msg, i) => {
                const isCmd = msg.role === "incident_commander";
                const roleColor = isCmd
                  ? "text-red-400"
                  : msg.role === "forensic_analyst"
                  ? "text-blue-400"
                  : msg.role === "communications_lead"
                  ? "text-yellow-400"
                  : msg.role === "soc_analyst"
                  ? "text-green-400"
                  : "text-slate-400";

                return (
                  <div key={i} className="text-xs bg-[#0b0f19]/30 p-2 rounded border border-breach-border/40">
                    <div className="flex justify-between items-center mb-1 text-[9px]">
                      <span className={`font-bold ${roleColor}`}>
                        {msg.name || msg.user_id.slice(0, 8)}{" "}
                        <span className="opacity-70 font-normal">
                          [{msg.role?.replace("_", " ").toUpperCase() || "ANALYST"}]
                        </span>
                      </span>
                      <span className="text-[8px] text-breach-muted">
                        {msg.ts ? new Date(msg.ts).toLocaleTimeString() : ""}
                      </span>
                    </div>
                    <span className="text-breach-text leading-relaxed">{msg.text}</span>
                  </div>
                );
              })}
              <div ref={chatEndRef} />
            </div>
            <div className="p-3 border-t border-breach-border bg-slate-950/20">
              <input
                ref={chatInput}
                onKeyDown={handleChat}
                placeholder="Coordinate containment playbook... (Enter)"
                className="w-full bg-[#0a0d17] border border-breach-border text-breach-text px-3 py-2 rounded text-xs focus:outline-none focus:border-breach-blue focus:shadow-[0_0_10px_rgba(59,130,246,0.15)] transition-all"
              />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
