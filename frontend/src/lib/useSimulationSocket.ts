import { useEffect, useRef, useCallback } from "react";
import { useSimStore } from "../store/simulation";

const WS_BASE = import.meta.env.VITE_WS_URL || "ws://localhost:8000";

interface SocketOptions {
  onDecisionResult?: (result: {
    decision_gate_id: string;
    is_correct: boolean;
    rationale: string;
    consequence_applied: string;
    correct_index: number;
  }) => void;
  onNotification?: (kind: "success" | "error" | "info", message: string) => void;
}

export function useSimulationSocket(sessionId: string, options?: SocketOptions) {
  const ws = useRef<WebSocket | null>(null);
  const {
    addAlert,
    setGate,
    setComplete,
    addChat,
    setParticipants,
    upsertParticipant,
    setVotes,
    clearVotes,
    setPaused,
  } = useSimStore();

  const optionsRef = useRef(options);
  useEffect(() => {
    optionsRef.current = options;
  }, [options]);

  useEffect(() => {
    const socket = new WebSocket(`${WS_BASE}/ws/session/${sessionId}`);
    ws.current = socket;

    // First message must be an auth frame — token is never put in the URL (BR-SEC-01)
    socket.onopen = () => {
      const accessToken = localStorage.getItem("br_token") ?? "";
      socket.send(JSON.stringify({ type: "auth", token: accessToken }));
    };

    socket.onmessage = (event) => {
      const msg = JSON.parse(event.data);
      switch (msg.type) {
        case "alert":
          addAlert(msg.payload);
          break;
        case "alert_injected":
          addAlert(msg.payload);
          if (optionsRef.current?.onNotification) {
            optionsRef.current.onNotification("info", `🚨 Facilitator injected alert: ${msg.payload.description}`);
          }
          break;
        case "decision_gate":
          setGate(msg);
          clearVotes();
          break;
        case "simulation_complete":
          setComplete();
          break;
        case "error":
          if (optionsRef.current?.onNotification) {
            optionsRef.current.onNotification("error", msg.data?.detail || "Simulation error");
          }
          break;
        case "chat":
          addChat({ user_id: msg.user_id, name: msg.name, role: msg.role, text: msg.text });
          break;
        case "presence_update":
          setParticipants(msg.participants || []);
          break;
        case "vote_update":
          {
            const votesMap: Record<string, number> = {};
            if (Array.isArray(msg.votes)) {
              msg.votes.forEach((v: { user_id: string; chosen_index: number }) => {
                votesMap[v.user_id] = v.chosen_index;
              });
            }
            setVotes(votesMap);
          }
          break;
        case "simulation_paused":
          setPaused(true);
          break;
        case "simulation_resumed":
          setPaused(false);
          break;
        case "participant_joined":
          upsertParticipant({ user_id: msg.user_id, name: msg.name, role: msg.role, online: true });
          break;
        case "decision_result":
          setGate(null);
          clearVotes();
          if (optionsRef.current?.onDecisionResult) {
            optionsRef.current.onDecisionResult({
              decision_gate_id: msg.decision_gate_id,
              is_correct: msg.is_correct,
              rationale: msg.rationale,
              consequence_applied: msg.consequence_applied,
              correct_index: msg.correct_index,
            });
          }
          break;
        default:
          break;
      }
    };

    return () => {
      socket.close();
    };
  }, [sessionId, addAlert, setGate, setComplete, addChat, setParticipants, upsertParticipant, setVotes, clearVotes, setPaused]);

  const send = (payload: unknown) => {
    if (ws.current?.readyState === WebSocket.OPEN) {
      ws.current.send(JSON.stringify(payload));
    }
  };

  const sendChat = useCallback((text: string) => {
    send({ type: "chat", text });
  }, []);

  const startStream = useCallback(() => {
    send({ type: "stream_alerts" });
  }, []);

  const ping = useCallback(() => {
    send({ type: "ping" });
  }, []);

  const submitVote = useCallback((optionIndex: number) => {
    send({ type: "submit_vote", chosen_option_index: optionIndex });
  }, []);

  const submitCommandDecision = useCallback((gateId: string, optionIndex: number) => {
    send({ type: "submit_command_decision", decision_gate_id: gateId, chosen_option_index: optionIndex });
  }, []);

  const togglePause = useCallback(() => {
    send({ type: "toggle_simulation_pause" });
  }, []);

  const injectAlert = useCallback((alertPayload: unknown) => {
    send({ type: "inject_alert", alert: alertPayload });
  }, []);

  return {
    sendChat,
    startStream,
    ping,
    submitVote,
    submitCommandDecision,
    togglePause,
    injectAlert,
  };
}

