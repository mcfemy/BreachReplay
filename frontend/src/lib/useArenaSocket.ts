import { useEffect, useRef, useState, useCallback } from "react";
import { WS_BASE } from "./config";

// ── Wire-shape types ─────────────────────────────────────────────────────────
// Mirrors the EXACT dict shapes emitted by backend/app/websocket/handlers.py's
// arena_ws_handler + backend/app/websocket/manager.py's build_alert_event /
// build_decision_gate_event / build_system_event helpers. Do not invent
// fields here that the backend doesn't actually send — see
// docs/plans/live-arena-mode.md Phase F's "reuse the EXACT WS event shapes"
// constraint.

export interface ArenaAlert {
  timestamp: string;
  severity: string;
  source_system: string;
  rule_id: string;
  description: string;
  raw_log?: string;
}

// build_decision_gate_event's options carry {index, text} always, plus
// (arena-only) response_action_type + whichever id field(s) that action
// needs — see manager.py's _DECISION_GATE_OPTION_PASSTHROUGH_FIELDS. Never
// present for scripted-scenario gates, always present for arena gates
// offered by _build_arena_decision_gate in handlers.py.
export interface ArenaDecisionGateOption {
  index: number;
  text: string;
  response_action_type?: string;
  host_id?: string;
  credential_id?: string;
  segment_id?: string;
}

export interface ArenaDecisionGate {
  gate_id: string;
  context_summary: string;
  options: ArenaDecisionGateOption[];
}

// The inline dict handlers.py sends for defender_action confirmations
// (see _notify_arena_action_result's "else" branch) — same field family as
// scripted decision_result, plus action_type/payload/sequence_number.
export interface ArenaDecisionResult {
  decision_gate_id: string | null;
  is_correct: boolean;
  rationale: string;
  consequence_applied: string;
  correct_index: number | null;
  action_type?: string;
  payload?: Record<string, unknown>;
  sequence_number?: number;
}

export interface ArenaActionResult {
  action_type: string;
  sequence_number: number;
  detected: boolean;
}

export interface ArenaDefenderActionResult {
  action_type: string;
  payload: Record<string, unknown>;
  sequence_number: number;
}

export interface ArenaMatchComplete {
  status: string;
  sequence_number: number;
}

interface ArenaSocketOptions {
  onNotification?: (kind: "success" | "error" | "info", message: string) => void;
}

interface ArenaSocketState {
  connected: boolean;
  alerts: ArenaAlert[];
  currentGate: ArenaDecisionGate | null;
  lastActionResult: ArenaActionResult | null;
  lastDecisionResult: ArenaDecisionResult | null;
  lastDefenderActionResult: ArenaDefenderActionResult | null;
  matchComplete: ArenaMatchComplete | null;
}

const INITIAL_STATE: ArenaSocketState = {
  connected: false,
  alerts: [],
  currentGate: null,
  lastActionResult: null,
  lastDecisionResult: null,
  lastDefenderActionResult: null,
  matchComplete: null,
};

/**
 * Live Arena Mode WS hook for /ws/arena/{match_id}. Structurally mirrors
 * useSimulationSocket.ts (same auth-frame-first handshake, same
 * message-type switch pattern) but targets the arena route's distinct
 * message contract:
 *   client -> server: attacker_action / defender_action / ping
 *   server -> client: alert / decision_gate / decision_result /
 *                     action_result (system) / defender_action_result (system) /
 *                     match_complete (system) / error (system) / pong (system)
 */
export function useArenaSocket(matchId: string, options?: ArenaSocketOptions) {
  const ws = useRef<WebSocket | null>(null);
  const [state, setState] = useState<ArenaSocketState>(INITIAL_STATE);

  const optionsRef = useRef(options);
  useEffect(() => {
    optionsRef.current = options;
  }, [options]);

  useEffect(() => {
    setState(INITIAL_STATE);
    const socket = new WebSocket(`${WS_BASE}/ws/arena/${matchId}`);
    ws.current = socket;

    // First message must be an auth frame — token is never put in the URL (BR-SEC-01)
    socket.onopen = () => {
      const accessToken = localStorage.getItem("br_token") ?? "";
      socket.send(JSON.stringify({ type: "auth", token: accessToken }));
      setState((s) => ({ ...s, connected: true }));
    };

    socket.onclose = () => {
      setState((s) => ({ ...s, connected: false }));
    };

    socket.onmessage = (event) => {
      const msg = JSON.parse(event.data);
      switch (msg.type) {
        case "alert":
          // build_alert_event: {type, index, total, payload, server_time}
          setState((s) => ({ ...s, alerts: [...s.alerts, msg.payload as ArenaAlert] }));
          break;

        case "decision_gate":
          // build_decision_gate_event: {type, gate_id, context_summary, options, server_time}
          setState((s) => ({
            ...s,
            currentGate: {
              gate_id: msg.gate_id,
              context_summary: msg.context_summary,
              options: msg.options || [],
            },
          }));
          break;

        case "decision_result":
          // Inline dict from _notify_arena_action_result's defender_action branch
          setState((s) => ({
            ...s,
            currentGate: null,
            lastDecisionResult: {
              decision_gate_id: msg.decision_gate_id,
              is_correct: msg.is_correct,
              rationale: msg.rationale,
              consequence_applied: msg.consequence_applied,
              correct_index: msg.correct_index,
              action_type: msg.action_type,
              payload: msg.payload,
              sequence_number: msg.sequence_number,
            },
          }));
          break;

        case "action_result":
          // build_system_event("action_result", {action_type, sequence_number, detected})
          setState((s) => ({ ...s, lastActionResult: msg.data as ArenaActionResult }));
          break;

        case "defender_action_result":
          // build_system_event("defender_action_result", {action_type, payload, sequence_number})
          setState((s) => ({ ...s, lastDefenderActionResult: msg.data as ArenaDefenderActionResult }));
          if (optionsRef.current?.onNotification) {
            optionsRef.current.onNotification("info", "The SOC reacted to your last move.");
          }
          break;

        case "match_complete":
          // build_system_event("match_complete", {status, sequence_number})
          setState((s) => ({ ...s, matchComplete: msg.data as ArenaMatchComplete }));
          break;

        case "error":
          if (optionsRef.current?.onNotification) {
            optionsRef.current.onNotification("error", msg.data?.detail || "Arena match error");
          }
          break;

        case "pong":
          break;

        default:
          break;
      }
    };

    return () => {
      socket.close();
    };
  }, [matchId]);

  const send = (payload: unknown) => {
    if (ws.current?.readyState === WebSocket.OPEN) {
      ws.current.send(JSON.stringify(payload));
    }
  };

  const sendAttackerAction = useCallback((actionType: string, payload: Record<string, unknown> = {}) => {
    send({ type: "attacker_action", action_type: actionType, payload });
  }, []);

  const sendDefenderAction = useCallback((actionType: string, payload: Record<string, unknown> = {}) => {
    send({ type: "defender_action", action_type: actionType, payload });
  }, []);

  const ping = useCallback(() => {
    send({ type: "ping" });
  }, []);

  return {
    ...state,
    sendAttackerAction,
    sendDefenderAction,
    ping,
  };
}
