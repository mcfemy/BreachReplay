import { useEffect, useRef, useState } from "react";
import { WS_BASE } from "./config";

// ── Live Breach Events Phase 5 — spectator WS hook ──────────────────────────
//
// Deliberately a SEPARATE hook from useArenaSocket.ts, not a `spectate?:
// boolean` option bolted onto it. Reasoning (see the plan's frontend bullet
// for this phase): useArenaSocket's entire onmessage switch (alert/
// decision_gate/decision_result/action_result/defender_action_result) is
// built around messages arena_ws_handler sends to an authenticated
// attacker/defender socket — arena_spectator_ws_handler (backend/app/
// websocket/handlers.py) sends NONE of those. A spectator only ever
// receives `spectator_init` (once, on connect) and `spectator_action` (one
// per action, redacted via _build_spectator_action_event), plus the generic
// `pong`. Reusing useArenaSocket would mean adding two spectator-only cases
// to a switch full of cases that can never fire for this connection, and —
// more importantly — the auth handshake itself differs: this hook's onopen
// sends {"type": "spectate"} with NO token, and never touches
// localStorage's br_token at all (unlike useArenaSocket's onopen, which
// always reads it). A shared hook would need a branch in the single
// highest-risk line (what gets sent as the first frame) — cleaner to keep
// that a completely separate, minimal connect path.
//
// Wire shapes mirrored EXACTLY from arena_spectator_ws_handler +
// _build_spectator_action_event + _spectator_initial_view (verified by
// reading backend/app/websocket/handlers.py and
// backend/app/api/routes/arena.py directly, not guessed):
//
//   server -> client (spectator only):
//     {type: "spectator_init", match: {...}, state: {segment_count,
//       segments: [{id, name}], host_count}, server_time}
//     {type: "spectator_action", sequence_number, actor,
//       hosts_newly_compromised: string[] (opaque host ids),
//       hosts_newly_isolated: string[] (opaque host ids),
//       match_completed: bool, match_status: string, server_time}
//     {type: "pong"}
//
//   client -> server: {type: "spectate"} (first frame only), {type: "ping"}
//
// Redaction note: hosts_newly_compromised/hosts_newly_isolated are id
// ARRAYS on the wire, but this hook only ever exposes their .length to
// consumers (see SpectatorLogEntry below) — never the raw ids — since a
// spectator has no hostname/role mapping to resolve them against anyway
// (per _spectator_initial_view's docstring) and this app must not attempt
// to cross-reference them from elsewhere to "unredact" them client-side.

export interface SpectatorMatchSummary {
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

export interface SpectatorInitialView {
  segment_count: number;
  segments: { id: string; name: string }[];
  host_count: number;
}

export interface SpectatorLogEntry {
  sequence_number: number;
  actor: string;
  hostsNewlyCompromised: number;
  hostsNewlyIsolated: number;
  server_time: string;
}

export interface SpectatorMatchComplete {
  status: string;
  sequence_number: number;
}

// Distinguishes WHY the socket closed, for a friendlier message than a bare
// "disconnected" — mirrors the two close codes arena_spectator_ws_handler's
// caller (app/main.py's websocket_arena / the handler itself) actually uses.
export type SpectatorCloseReason = "match_not_found" | "not_spectatable" | "closed" | null;

interface SpectatorSocketState {
  connected: boolean;
  match: SpectatorMatchSummary | null;
  initialView: SpectatorInitialView | null;
  log: SpectatorLogEntry[];
  matchComplete: SpectatorMatchComplete | null;
  closeReason: SpectatorCloseReason;
}

const INITIAL_STATE: SpectatorSocketState = {
  connected: false,
  match: null,
  initialView: null,
  log: [],
  matchComplete: null,
  closeReason: null,
};

export function useArenaSpectatorSocket(matchId: string) {
  const ws = useRef<WebSocket | null>(null);
  const [state, setState] = useState<SpectatorSocketState>(INITIAL_STATE);

  useEffect(() => {
    if (!matchId) return;
    setState(INITIAL_STATE);
    const socket = new WebSocket(`${WS_BASE}/ws/arena/${matchId}`);
    ws.current = socket;

    socket.onopen = () => {
      // No auth frame, no token read — a spectator connection is anonymous
      // by design (see app/main.py's websocket_arena: this branch does zero
      // JWT verification). Sending {"type": "auth", ...} here would be the
      // wrong handshake entirely for this path.
      socket.send(JSON.stringify({ type: "spectate" }));
      setState((s) => ({ ...s, connected: true }));
    };

    socket.onclose = (event) => {
      // 4004: match not found. 4003: match.event_id is None (not a Live
      // Event match, so not spectatable) — both closes happen before
      // arena_spectator_ws_handler ever sends spectator_init, so a
      // reason is only meaningful when nothing else has come through yet.
      setState((s) => ({
        ...s,
        connected: false,
        closeReason:
          s.closeReason ?? (event.code === 4004 ? "match_not_found" : event.code === 4003 ? "not_spectatable" : "closed"),
      }));
    };

    socket.onmessage = (event) => {
      const msg = JSON.parse(event.data);
      switch (msg.type) {
        case "spectator_init":
          setState((s) => ({
            ...s,
            match: msg.match as SpectatorMatchSummary,
            initialView: msg.state as SpectatorInitialView,
          }));
          break;

        case "spectator_action": {
          const entry: SpectatorLogEntry = {
            sequence_number: msg.sequence_number,
            actor: msg.actor,
            hostsNewlyCompromised: Array.isArray(msg.hosts_newly_compromised) ? msg.hosts_newly_compromised.length : 0,
            hostsNewlyIsolated: Array.isArray(msg.hosts_newly_isolated) ? msg.hosts_newly_isolated.length : 0,
            server_time: msg.server_time,
          };
          setState((s) => ({
            ...s,
            log: [...s.log, entry],
            matchComplete: msg.match_completed
              ? { status: msg.match_status, sequence_number: msg.sequence_number }
              : s.matchComplete,
          }));
          break;
        }

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

  return state;
}
