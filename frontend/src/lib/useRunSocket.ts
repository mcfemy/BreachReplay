import { useEffect, useRef, useState, useCallback } from "react";
import { WS_BASE } from "./config";

// ── Wire-shape types ─────────────────────────────────────────────────────────
// Mirrors the EXACT dict shapes emitted by backend/app/websocket/handlers.py's
// action_run_ws_handler + backend/app/websocket/manager.py's
// build_run_resync_event / build_state_delta_event / build_clock_tick_event /
// build_stage_advance_event / build_run_end_event, and
// backend/app/services/verb_engine.py's per-verb delta shapes. Do not invent
// fields the backend doesn't actually send.

export const VERB_COSTS = {
  query_logs: 30,
  scan_network: 45,
  isolate: 20,
  image_disk: 90,
  interview_user: 60,
  block_ip: 15,
  reset_creds: 40,
  escalate: 0,
} as const;

export type Verb = keyof typeof VERB_COSTS;

// The two verbs apply_verb accepts with no target at all.
export const UNTARGETED_VERBS: Verb[] = ["scan_network", "escalate"];
// Verbs whose target is a host id — pick by tapping the map.
export const HOST_TARGETED_VERBS: Verb[] = ["query_logs", "isolate", "image_disk", "interview_user"];
// Verbs whose target is a free-text string the player read in a revealed
// log/credential (never a host id) — block_ip's IP comes from a revealed
// raw_log, reset_creds's username from a revealed interview_user credential.
export const TEXT_TARGETED_VERBS: Verb[] = ["block_ip", "reset_creds"];

// verb_engine._host_summary's shape. Never includes unpatched_cves/
// edr_installed (image_disk-only forensics, kept separate below) or
// anything not earned yet.
export interface HostSummary {
  id: string;
  hostname: string;
  role: string;
  network_segment_id: string;
  compromise_level: "none" | "foothold" | "admin" | "domain_admin";
  isolated: boolean;
}

export interface HostForensics {
  unpatched_cves: string[];
  edr_installed: boolean;
}

// IOCPlacement.to_dict()'s shape.
export interface RevealedIoc {
  host_id: string;
  description: string;
  severity: string;
  source_system: string;
  rule_id: string;
  raw_log: string;
}

export interface RevealedCredential {
  credential_id: string;
  username: string;
  privilege: string;
}

export interface RunEdge {
  source: string;
  target: string;
}

export interface ScoreBreakdown {
  outcome: string;
  outcome_base: number;
  evidence_points: number;
  evidence_found: number;
  evidence_total: number;
  speed_bonus: number;
  penalty_total: number;
  penalties: { type: string; [key: string]: unknown }[];
  total_score: number;
  score_pct: number;
}

// build_run_end_event's summary — finalize()'s dict, plus (mode="daily"
// only) record_daily_action_run_result's carry-over fields merged in.
export interface RunEndSummary {
  action_run_id: string;
  outcome: "win" | "loss" | "partial";
  score_breakdown: ScoreBreakdown;
  xp_awarded: number;
  new_achievements: string[];
  daily_challenge_id?: string;
  challenge_number?: number;
  rank?: number;
  current_streak?: number;
  longest_streak?: number;
  total_dailies_played?: number;
  total_attempts_today?: number;
  avg_score_today?: number;
}

interface RunSocketState {
  connected: boolean;
  elapsedSeconds: number;
  attackerClockSeconds: number;
  capSeconds: number;
  hosts: HostSummary[];
  forensicsByHost: Record<string, HostForensics>;
  revealedIocs: RevealedIoc[];
  credentialsByHost: Record<string, RevealedCredential[]>;
  edges: RunEdge[];
  stagesFired: number;
  totalStages: number;
  isFinalReached: boolean;
  error: string | null;
  runEnd: RunEndSummary | null;
}

const INITIAL_STATE: RunSocketState = {
  connected: false,
  elapsedSeconds: 0,
  attackerClockSeconds: 0,
  capSeconds: 0,
  hosts: [],
  forensicsByHost: {},
  revealedIocs: [],
  credentialsByHost: {},
  edges: [],
  stagesFired: 0,
  totalStages: 0,
  isFinalReached: false,
  error: null,
  runEnd: null,
};

function mergeIocs(existing: RevealedIoc[], incoming: RevealedIoc[]): RevealedIoc[] {
  const merged = [...existing];
  for (const ioc of incoming) {
    if (!merged.some((m) => m.host_id === ioc.host_id && m.rule_id === ioc.rule_id)) {
      merged.push(ioc);
    }
  }
  return merged;
}

function upsertHost(hosts: HostSummary[], id: string, patch: Partial<HostSummary>): HostSummary[] {
  const idx = hosts.findIndex((h) => h.id === id);
  if (idx === -1) return hosts; // not revealed yet — nothing to patch, stays hidden
  const next = [...hosts];
  next[idx] = { ...next[idx], ...patch };
  return next;
}

/**
 * Action console WS hook for /ws/run/{run_id} (Phase 2 Item 5). Structurally
 * mirrors useArenaSocket.ts (self-contained returned state, not
 * zustand-coupled): same auth-frame-first handshake, same message-type
 * switch pattern, targeting the action-run route's distinct contract:
 *   client -> server: action.submit {verb, target?} / ping
 *   server -> client: run.resync / state.delta / clock.tick /
 *                     stage.advance / run.end / error (system) / pong
 */
export function useRunSocket(runId: string) {
  const ws = useRef<WebSocket | null>(null);
  const [state, setState] = useState<RunSocketState>(INITIAL_STATE);

  useEffect(() => {
    setState(INITIAL_STATE);
    const socket = new WebSocket(`${WS_BASE}/ws/run/${runId}`);
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
        case "run.resync":
          // build_run_resync_event: {elapsed_seconds, attacker_clock_seconds,
          // cap_seconds, hosts, revealed_iocs, edges} — hosts/revealed_iocs/
          // edges are everything this player has already earned (empty on a
          // fresh run), restoring exactly what a reconnect should show.
          setState((s) => ({
            ...s,
            elapsedSeconds: msg.elapsed_seconds,
            attackerClockSeconds: msg.attacker_clock_seconds,
            capSeconds: msg.cap_seconds,
            hosts: msg.hosts as HostSummary[],
            revealedIocs: msg.revealed_iocs as RevealedIoc[],
            edges: msg.edges as RunEdge[],
          }));
          break;

        case "state.delta": {
          // verb_engine.apply_verb's per-verb delta shape — distinguished by
          // which keys are present, matching apply_verb's own branches.
          const delta = msg.delta as Record<string, unknown>;
          setState((s) => {
            if (Array.isArray(delta.nodes)) {
              // scan_network
              return {
                ...s,
                hosts: delta.nodes as HostSummary[],
                edges: (delta.edges as RunEdge[]) ?? s.edges,
              };
            }
            if (Array.isArray(delta.revealed_iocs)) {
              // query_logs or image_disk
              const hostId = delta.host_id as string;
              let hosts = s.hosts;
              let forensicsByHost = s.forensicsByHost;
              if (delta.forensics) {
                forensicsByHost = { ...forensicsByHost, [hostId]: delta.forensics as HostForensics };
              }
              return {
                ...s,
                hosts,
                forensicsByHost,
                revealedIocs: mergeIocs(s.revealedIocs, delta.revealed_iocs as RevealedIoc[]),
              };
            }
            if (Array.isArray(delta.credentials)) {
              // interview_user
              const hostId = delta.host_id as string;
              return {
                ...s,
                credentialsByHost: { ...s.credentialsByHost, [hostId]: delta.credentials as RevealedCredential[] },
              };
            }
            if (typeof delta.isolated === "boolean") {
              // isolate
              return { ...s, hosts: upsertHost(s.hosts, delta.host_id as string, { isolated: true }) };
            }
            if (typeof delta.correct === "boolean") {
              // block_ip / reset_creds — only block_ip's correct guess
              // isolates a host; reset_creds's target is a credential, not
              // a host on the map.
              if (delta.correct && delta.host_id) {
                return { ...s, hosts: upsertHost(s.hosts, delta.host_id as string, { isolated: true }) };
              }
              return s;
            }
            // escalate_used: no host/IOC/edge change, nothing to merge.
            return s;
          });
          break;
        }

        case "clock.tick":
          // build_clock_tick_event: {elapsed_seconds, attacker_clock_seconds}
          setState((s) => ({
            ...s,
            elapsedSeconds: msg.elapsed_seconds,
            attackerClockSeconds: msg.attacker_clock_seconds,
          }));
          break;

        case "stage.advance":
          // build_stage_advance_event: {stages_fired, total_stages,
          // is_final_reached, newly_compromised_hosts}. newly_compromised_hosts
          // is _public_host_state's redacted {id, compromise_level, isolated}
          // shape — only merged into a host this player has already revealed
          // (upsertHost is a no-op otherwise), so an attacker stage firing on
          // a host the player hasn't found yet stays invisible until they
          // scan/query it, same fog-of-war contract every delta enforces.
          setState((s) => {
            let hosts = s.hosts;
            for (const h of (msg.newly_compromised_hosts as { id: string; compromise_level: string; isolated: boolean }[])) {
              hosts = upsertHost(hosts, h.id, { compromise_level: h.compromise_level as HostSummary["compromise_level"], isolated: h.isolated });
            }
            return {
              ...s,
              hosts,
              stagesFired: msg.stages_fired,
              totalStages: msg.total_stages,
              isFinalReached: msg.is_final_reached,
            };
          });
          break;

        case "run.end":
          // build_run_end_event: {type: "run.end", ...summary, server_time}
          setState((s) => ({ ...s, runEnd: msg as RunEndSummary }));
          break;

        case "error":
          // build_system_event("error", {detail}) -> {type:"error", data:{detail}}
          setState((s) => ({ ...s, error: msg.data?.detail || "Action run error" }));
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
  }, [runId]);

  const send = (payload: unknown) => {
    if (ws.current?.readyState === WebSocket.OPEN) {
      ws.current.send(JSON.stringify(payload));
    }
  };

  const submitVerb = useCallback((verb: Verb, target?: string) => {
    send({ type: "action.submit", verb, target });
  }, []);

  const ping = useCallback(() => {
    send({ type: "ping" });
  }, []);

  return {
    ...state,
    submitVerb,
    ping,
  };
}
