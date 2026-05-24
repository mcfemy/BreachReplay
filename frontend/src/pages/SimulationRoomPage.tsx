import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useSimStore } from "../store/simulation";
import { useSimulationSocket } from "../lib/useSimulationSocket";
import { api } from "../lib/api";

const SEVERITY_COLORS: Record<string, string> = {
  critical: "border-l-breach-accent text-breach-accent",
  high: "border-l-orange-500 text-orange-400",
  medium: "border-l-breach-yellow text-breach-yellow",
  low: "border-l-breach-blue text-breach-blue",
};

interface Notification {
  kind: "success" | "error" | "info";
  message: string;
}

const NOTIFICATION_COLORS: Record<Notification["kind"], string> = {
  success: "bg-green-900/80 border-breach-green text-breach-green",
  error: "bg-red-900/80 border-breach-accent text-breach-accent",
  info: "bg-blue-900/80 border-breach-blue text-breach-blue",
};

export default function SimulationRoomPage() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const navigate = useNavigate();
  const { alerts, currentGate, isPaused, isComplete, chatMessages, setGate } = useSimStore();
  const { sendChat, startStream } = useSimulationSocket(sessionId!);
  const alertsEndRef = useRef<HTMLDivElement>(null);
  const chatInput = useRef<HTMLInputElement>(null);
  const [notification, setNotification] = useState<Notification | null>(null);

  // BUG-07: Reset stale simulation state when navigating to a new session
  useEffect(() => {
    useSimStore.getState().reset();
  }, [sessionId]);

  useEffect(() => {
    alertsEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [alerts]);

  function notify(kind: Notification["kind"], message: string) {
    setNotification({ kind, message });
    setTimeout(() => setNotification(null), 4000);
  }

  // BUG-06: Surface start errors in-component instead of failing silently
  async function handleStart() {
    try {
      await api.post(`/sessions/${sessionId}/start`, {});
      startStream();
    } catch (err: any) {
      notify("error", err.message || "Failed to start session");
    }
  }

  async function handleViewDebrief() {
    try {
      await api.post(`/sessions/${sessionId}/complete`, {});
      navigate(`/session/${sessionId}/debrief`);
    } catch (err: any) {
      notify("error", err.message || "Failed to complete session");
    }
  }

  async function submitDecision(optionIndex: number) {
    if (!currentGate) return;
    try {
      const result = await api.post<any>(`/sessions/${sessionId}/decisions`, {
        decision_gate_id: currentGate.gate_id,
        chosen_option_index: optionIndex,
      });
      setGate(null);
      // BUG-09: Replace blocking alert() with non-blocking in-component notification
      notify(
        result.is_correct ? "success" : "error",
        `${result.is_correct ? "CORRECT" : "WRONG"}: ${result.rationale}`
      );
    } catch (err: any) {
      notify("error", err.message || "Failed to submit decision");
    }
  }

  function handleChat(e: React.KeyboardEvent) {
    if (e.key === "Enter" && chatInput.current?.value) {
      sendChat(chatInput.current.value);
      chatInput.current.value = "";
    }
  }

  return (
    <div className="min-h-screen bg-breach-bg flex flex-col">
      {notification && (
        <div
          className={`fixed top-4 right-4 z-50 border rounded px-4 py-3 text-xs font-mono max-w-sm shadow-lg ${NOTIFICATION_COLORS[notification.kind]}`}
        >
          {notification.message}
        </div>
      )}

      <div className="border-b border-breach-border px-6 py-3 flex items-center justify-between">
        <div className="flex items-center gap-4">
          <span className="text-breach-accent font-bold text-sm uppercase tracking-widest">BREACH REPLAY</span>
          <span className="text-breach-muted text-xs">Session: {sessionId?.slice(0, 8)}...</span>
          {isComplete && (
            <span className="text-breach-green text-xs uppercase font-bold animate-pulse">SIMULATION COMPLETE</span>
          )}
        </div>
        {isComplete ? (
          <button
            onClick={handleViewDebrief}
            className="bg-breach-accent hover:bg-red-600 text-white px-4 py-1.5 rounded text-xs uppercase tracking-widest transition-colors font-bold animate-pulse shadow-[0_0_15px_rgba(239,68,68,0.5)]"
          >
            View Debrief Report
          </button>
        ) : (
          <button
            onClick={handleStart}
            className="bg-breach-green hover:bg-green-600 text-black px-4 py-1.5 rounded text-xs uppercase tracking-widest transition-colors font-bold"
          >
            Start Stream
          </button>
        )}
      </div>

      <div className="flex flex-1 overflow-hidden">
        <div className="flex-1 flex flex-col overflow-hidden">
          <div className="px-4 py-2 border-b border-breach-border">
            <span className="text-xs text-breach-muted uppercase tracking-wider">Alert Feed</span>
            <span className="text-xs text-breach-muted ml-4">{alerts.length} events</span>
          </div>
          <div className="flex-1 overflow-y-auto p-4 space-y-2 font-mono">
            {alerts.map((alert, i) => (
              <div
                key={i}
                className={`bg-breach-surface border border-breach-border border-l-4 px-3 py-2 rounded ${SEVERITY_COLORS[alert.severity] || ""}`}
              >
                <div className="flex items-center gap-3 mb-1">
                  <span className="text-xs opacity-60">{alert.timestamp}</span>
                  <span className="text-xs uppercase font-bold">{alert.severity}</span>
                  <span className="text-xs text-breach-muted">{alert.source_system}</span>
                  <span className="text-xs text-breach-muted">{alert.rule_id}</span>
                </div>
                <p className="text-xs text-breach-text">{alert.description}</p>
                {alert.raw_log && (
                  <p className="text-xs text-breach-muted mt-1 opacity-60 truncate">{alert.raw_log}</p>
                )}
              </div>
            ))}
            <div ref={alertsEndRef} />
          </div>
        </div>

        <div className="w-80 border-l border-breach-border flex flex-col">
          {isPaused && currentGate && (
            <div className="p-4 border-b border-breach-border bg-breach-surface">
              <div className="text-xs text-breach-accent uppercase tracking-wider font-bold mb-2">Decision Required</div>
              <p className="text-xs text-breach-text mb-4 leading-relaxed">{currentGate.context_summary}</p>
              <div className="space-y-2">
                {currentGate.options.map((opt) => (
                  <button
                    key={opt.index}
                    onClick={() => submitDecision(opt.index)}
                    className="w-full text-left bg-breach-bg border border-breach-border hover:border-breach-blue text-xs text-breach-text px-3 py-2 rounded transition-colors"
                  >
                    <span className="text-breach-muted mr-2">{String.fromCharCode(65 + opt.index)}.</span>
                    {opt.text}
                  </button>
                ))}
              </div>
            </div>
          )}

          <div className="flex-1 overflow-y-auto p-3 space-y-2">
            <div className="text-xs text-breach-muted uppercase tracking-wider mb-2">Team Chat</div>
            {chatMessages.map((msg, i) => (
              <div key={i} className="text-xs">
                <span className="text-breach-blue">{msg.user_id.slice(0, 8)}</span>
                <span className="text-breach-muted mx-1">›</span>
                <span className="text-breach-text">{msg.text}</span>
              </div>
            ))}
          </div>
          <div className="p-3 border-t border-breach-border">
            <input
              ref={chatInput}
              onKeyDown={handleChat}
              placeholder="Send message (Enter)"
              className="w-full bg-breach-bg border border-breach-border text-breach-text px-2 py-1.5 rounded text-xs focus:outline-none focus:border-breach-blue"
            />
          </div>
        </div>
      </div>
    </div>
  );
}
