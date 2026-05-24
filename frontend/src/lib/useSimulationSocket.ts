import { useEffect, useRef, useCallback } from "react";
import { useSimStore } from "../store/simulation";

const WS_BASE = import.meta.env.VITE_WS_URL || "ws://localhost:8000";

export function useSimulationSocket(sessionId: string) {
  const ws = useRef<WebSocket | null>(null);
  const { addAlert, setGate, setComplete, addChat } = useSimStore();

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
  }, [sessionId]);

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
