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

// The only verb apply_verb accepts with no target at all — Phase 3 moved
// "escalate" out of this list (see PARTY_TARGETED_VERBS below).
export const UNTARGETED_VERBS: Verb[] = ["scan_network"];
// Verbs whose target is a host id — pick by tapping the map.
export const HOST_TARGETED_VERBS: Verb[] = ["query_logs", "isolate", "image_disk", "interview_user"];
// Verbs whose target is a free-text string the player read in a revealed
// log/credential (never a host id) — block_ip's IP comes from a revealed
// raw_log, reset_creds's username from a revealed interview_user credential.
export const TEXT_TARGETED_VERBS: Verb[] = ["block_ip", "reset_creds"];
// Phase 3 — "escalate"'s target is a party id picked from
// RunSocketState.notificationParties, a third distinct targeting mode:
// not a host, not free text, a fixed picklist known from run start.
export const PARTY_TARGETED_VERBS: Verb[] = ["escalate"];

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

// verb_engine.public_notification_parties' shape — Phase 3. Deliberately
// just {id, party_name}: `warranted`/`basis`/`rationale`/`source_reference`
// are the answer to the judgment call escalate exists to test, so the
// server never sends them ahead of time (same leak-safety discipline as
// hidden_iocs — see that function's own docstring).
export interface NotificationParty {
  id: string;
  party_name: string;
}

// One entry from a run.end summary's score_breakdown.notifications —
// unlike NotificationParty above, this is post-run only (same
// leak-safety boundary as CollateralHost below) and DOES carry
// `warranted`, since the run is over and there's nothing left to spoil.
export interface NotificationOutcome {
  party_id: string;
  party_name: string;
  warranted: boolean;
  notified: boolean;
}

// Diegetic tool output (verb_engine.py's tool_output module) — attached to
// almost every verb's delta as `delta.tool_output` (escalate/isolate/
// block_ip/reset_creds have `command: null`, since those are action-log
// entries or a real console action, not something typed into a shell).
// Server-rendered only: leak-safety and real-syntax discipline both live
// in backend/app/services/tool_output.py, never re-derived or templated
// here — this interface exists purely to type what's already in the delta.
export interface ToolOutput {
  tool: string;
  command: string | null;
  output: string;
}

// Proportionate Response's 5-state outcome (verb_engine.determine_outcome),
// graded on two axes: was the final target stopped, and how much collateral
// did it cost. Replaces the old "win" | "loss" | "partial" — see
// backend/app/services/verb_engine.py's determine_outcome docstring.
export type RunOutcome =
  | "contained"
  | "contained_at_cost"
  | "overreacted"
  | "breached_spread_limited"
  | "breached";

// Shared display text for the 5 states — headline copy, not a buried
// percentage (spec section 5). Every surface that shows a run's outcome
// (ActionConsole's RunDebrief, DailyBreachPage's ActionResultsPanel/
// leaderboard/share card) reads from this one map rather than each
// inventing its own formatting of the raw enum string.
export const OUTCOME_LABELS: Record<RunOutcome, string> = {
  contained: "Contained",
  contained_at_cost: "Contained at Cost",
  overreacted: "Overreacted",
  breached_spread_limited: "Breached — Spread Limited",
  breached: "Breached",
};

// One unnecessarily-isolated host in the post-run collateral breakdown
// (verb_engine._collateral_hosts / compute_score's "collateral" key).
// Deliberately absent from every mid-run message — only ever present in
// run.end, per the leak-safety constraint (see RunEndSummary below).
export interface CollateralHost {
  host_id: string;
  hostname: string;
  weight: number;
}

export interface ScoreBreakdown {
  outcome: RunOutcome;
  outcome_base: number;
  evidence_points: number;
  evidence_found: number;
  evidence_total: number;
  speed_bonus: number;
  penalty_total: number;
  penalties: { type: string; [key: string]: unknown }[];
  collateral: CollateralHost[];
  collateral_penalty: number;
  // Phase 3 — parallel to evidence_points/evidence_found above, additive
  // into total_score, never affecting `outcome` (see
  // verb_engine.compute_score's docstring on why this is one axis, not a
  // second UI-surfaced score).
  notifications: NotificationOutcome[];
  notification_points: number;
  notification_penalty: number;
  total_score: number;
  score_pct: number;
}

// One entry from a run.end summary's techniques_encountered —
// action_run_store.ActionRunStore._techniques_encountered_summary's shape.
// Deliberately just {technique_id, name, description}: the incident
// narrative/source citation/scenario list are the full Dossier page's
// content (GET /dossier/me, TECHNIQUE_DOSSIER), not this per-run summary's.
export interface EncounteredTechnique {
  technique_id: string;
  name: string;
  description: string;
}

// build_run_end_event's summary — finalize()'s dict, plus (mode="daily"
// only) record_daily_action_run_result's carry-over fields merged in.
// `outcome`/`score_breakdown.collateral` only ever appear here, in the
// single post-run summary — never in run.resync/state.delta/stage.advance,
// which is what makes collateral leak-safe (see verb_engine.compute_score's
// docstring): a live player can't infer which unrevealed hosts are
// collateral before the run ends.
export interface RunEndSummary {
  action_run_id: string;
  outcome: RunOutcome;
  score_breakdown: ScoreBreakdown;
  xp_awarded: number;
  new_achievements: string[];
  // Every stage.mitre_technique that fired THIS run (verb_engine.RunState.
  // encountered_technique_ids), regardless of auth — present even for an
  // unauthenticated teaser run, though only an authenticated run's
  // encounters also persist to GET /dossier/me.
  techniques_encountered: EncounteredTechnique[];
  daily_challenge_id?: string;
  challenge_number?: number;
  rank?: number;
  current_streak?: number;
  longest_streak?: number;
  total_dailies_played?: number;
  total_attempts_today?: number;
  avg_score_today?: number;
}

// A `state.delta` message's raw delta, verb-agnostic — see
// verb_engine.apply_verb's per-verb shapes. Exposed as-is (not pre-parsed
// into a union) so ActionConsole can react generically: any delta
// carrying a string `host_id` came from a verb whose result belongs on
// that host's drawer (query_logs/isolate/image_disk/interview_user, and
// block_ip's correct-guess case), and any delta carrying a boolean
// `correct` is a free-text verb's (block_ip/reset_creds) guess result,
// whether or not it also carries a host_id. `tool_output` is present on
// every one of the 8 verbs' deltas — typed separately here since it's the
// one field every branch shares, unlike the rest of this intentionally
// loosely-typed bag.
type LastDelta = (Record<string, unknown> & { tool_output?: ToolOutput }) | null;

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
  notificationParties: NotificationParty[];
  notifiedPartyIds: string[];
  stagesFired: number;
  totalStages: number;
  isFinalReached: boolean;
  error: string | null;
  runEnd: RunEndSummary | null;
  lastDelta: LastDelta;
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
  notificationParties: [],
  notifiedPartyIds: [],
  stagesFired: 0,
  totalStages: 0,
  isFinalReached: false,
  lastDelta: null,
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
          // cap_seconds, hosts, revealed_iocs, edges, notification_parties}
          // — hosts/revealed_iocs/edges are everything this player has
          // already earned (empty on a fresh run), restoring exactly what a
          // reconnect should show. notification_parties is different in
          // kind: a static per-scenario list known from t=0, not
          // progressively earned, so it's populated even on a fresh run.
          setState((s) => ({
            ...s,
            elapsedSeconds: msg.elapsed_seconds,
            attackerClockSeconds: msg.attacker_clock_seconds,
            capSeconds: msg.cap_seconds,
            hosts: msg.hosts as HostSummary[],
            revealedIocs: msg.revealed_iocs as RevealedIoc[],
            edges: msg.edges as RunEdge[],
            notificationParties: (msg.notification_parties ?? []) as NotificationParty[],
            notifiedPartyIds: (msg.notified_party_ids ?? []) as string[],
          }));
          break;

        case "state.delta": {
          // verb_engine.apply_verb's per-verb delta shape — distinguished by
          // which keys are present, matching apply_verb's own branches.
          const delta = msg.delta as Record<string, unknown>;
          setState((s) => {
            // `lastDelta` is attached to every branch below (including the
            // escalate/no-op fallthrough) — ActionConsole reacts to it
            // generically (any `host_id` opens that host's drawer; any
            // `correct` surfaces a block_ip/reset_creds result) rather than
            // this hook needing to know what the UI does with it.
            if (Array.isArray(delta.nodes)) {
              // scan_network
              return {
                ...s,
                hosts: delta.nodes as HostSummary[],
                edges: (delta.edges as RunEdge[]) ?? s.edges,
                lastDelta: delta,
              };
            }
            // Checked BEFORE the generic revealed_iocs branch below:
            // block_ip's correct-guess delta carries `correct`/`host_id`
            // AND (as of the resync-parity fix) its own `revealed_iocs`
            // entry in the SAME delta — a superset of the query_logs/
            // image_disk shape. Handling it here, not falling into that
            // branch, is what keeps the isolation update from being
            // silently dropped (the generic branch below never isolates).
            if (typeof delta.correct === "boolean") {
              // block_ip / reset_creds — only block_ip's correct guess
              // isolates a host; reset_creds's target is a credential, not
              // a host on the map.
              if (delta.correct && delta.host_id) {
                const hosts = upsertHost(s.hosts, delta.host_id as string, { isolated: true });
                const revealedIocs = Array.isArray(delta.revealed_iocs)
                  ? mergeIocs(s.revealedIocs, delta.revealed_iocs as RevealedIoc[])
                  : s.revealedIocs;
                return { ...s, hosts, revealedIocs, lastDelta: delta };
              }
              return { ...s, lastDelta: delta };
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
                lastDelta: delta,
              };
            }
            if (Array.isArray(delta.credentials)) {
              // interview_user
              const hostId = delta.host_id as string;
              return {
                ...s,
                credentialsByHost: { ...s.credentialsByHost, [hostId]: delta.credentials as RevealedCredential[] },
                lastDelta: delta,
              };
            }
            if (typeof delta.isolated === "boolean") {
              // isolate
              return { ...s, hosts: upsertHost(s.hosts, delta.host_id as string, { isolated: true }), lastDelta: delta };
            }
            if (typeof delta.party_id === "string") {
              // escalate (Phase 3) — accumulates into notifiedPartyIds the
              // same way scan_network accumulates into hosts, so the party
              // picker can grey out/hide a party once notified (mirroring
              // the server's own once-per-party rejection) instead of
              // letting the player tap it again and learn only from an
              // error string.
              return {
                ...s,
                notifiedPartyIds: s.notifiedPartyIds.includes(delta.party_id)
                  ? s.notifiedPartyIds
                  : [...s.notifiedPartyIds, delta.party_id],
                lastDelta: delta,
              };
            }
            // No host/IOC/edge/party change — nothing to merge.
            return { ...s, lastDelta: delta };
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
