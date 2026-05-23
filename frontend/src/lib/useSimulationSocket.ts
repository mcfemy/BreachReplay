import { useEffect, useRef, useCallback } from "react";
import { useSimStore } from "../store/simulation";

const WS_BASE = import.meta.env.VITE_WS_URL || "ws://localhost:8000";

export function useSimulationSocket(sessionId: string, userId: string) {
  const ws = useRef<WebSocket | null>(null);
  const { addAlert, setGate, setComplete, addChat } = useSimStore();

  useEffect(() => {
    const socket = new WebSocket(`${WS_BASE}/ws/session/${sessionId}?user_id=${userId}`);
    ws.current = socket;

    socket.onmessage = (event) => {
      const msg = JSON.parse(event.data);
      switch (msg.type) {
        case "alert":
          addAlert(msg.payload);
          break;
        case "decision_gate":
          setGate(msg);
          break;
        case "simulation_complete":
          setComplete();
          break;
        case "chat":
          addChat({ user_id: msg.user_id, text: msg.text });
          break;
        default:
          break;
      }
    };

    return () => {
      socket.close();
    };
  }, [sessionId, userId]);

  const sendChat = useCallback((text: string) => {
    ws.current?.send(JSON.stringify({ type: "chat", text }));
  }, []);

  const startStream = useCallback(() => {
    ws.current?.send(JSON.stringify({ type: "stream_alerts" }));
  }, []);

  const ping = useCallback(() => {
    ws.current?.send(JSON.stringify({ type: "ping" }));
  }, []);

  return { sendChat, startStream, ping };
}
