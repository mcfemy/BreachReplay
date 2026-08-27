/**
 * Phase 4 — Ghost playback clock sync (pure helpers).
 *
 * Takes a server-controlled ghost DTO (PR #50) and a live-run elapsed
 * clock. No independent timer: at live time T the caller asks which map
 * frame and which verb-feed lines are visible. Duration mismatch is
 * handled by clamping — before the first frame → first frame; after the
 * last → last frame stays put.
 */
import type { FeedLine } from "./runFeed";
import { formatFeedClock } from "./runFeed";
import type { NodeState } from "../theme/tokens";
import type { NetworkMapEdge, NetworkMapNode } from "../components/NetworkMap";

export interface GhostVerbEntry {
  sequence_number: number;
  verb: string;
  elapsed_seconds: number;
  cost: number;
  /** Present only on scenario race DTOs — never used for Daily map-state. */
  target?: string | null;
}

export interface GhostUnknownHost {
  id: string;
  x: number;
  y: number;
  visibility: "unknown";
}

export interface GhostKnownHost {
  id: string;
  hostname: string;
  role: string;
  network_segment_id: string;
  compromise_level: "none" | "foothold" | "admin" | "domain_admin";
  isolated: boolean;
  x: number;
  y: number;
}

export type GhostHost = GhostUnknownHost | GhostKnownHost;

export interface GhostMapFrame {
  elapsed_seconds: number;
  hosts: GhostHost[];
  edges: { source: string; target: string }[];
}

/** Wire shape from GET /daily/ghost or GET /action-runs/public/ghost/{token}. */
export interface GhostDto {
  race_type: "daily" | "scenario";
  outcome: string;
  score: number;
  score_pct: number;
  duration_seconds: number;
  containment_seconds: number | null;
  scenario_title: string;
  mode: string;
  player_label: string;
  verb_timeline: GhostVerbEntry[];
  map_frames: GhostMapFrame[];
  ghost_run_id?: string;
  share_token?: string;
}

const VERB_FEED_LABEL: Record<string, string> = {
  scan_network: "Network scan complete.",
  query_logs: "Queried host logs.",
  isolate: "Host isolated.",
  image_disk: "Disk image captured.",
  interview_user: "User interview logged.",
  block_ip: "IP block issued.",
  reset_creds: "Credential reset issued.",
  escalate: "External notification sent.",
};

export function isGhostUnknownHost(h: GhostHost): h is GhostUnknownHost {
  return (h as GhostUnknownHost).visibility === "unknown";
}

/** Same mapping ActionConsole uses for live hosts → NodeState. */
export function ghostHostNodeState(h: GhostHost): NodeState {
  if (isGhostUnknownHost(h)) return "unknown";
  if (h.isolated) return "contained";
  if (h.compromise_level === "none") return "clean";
  if (h.compromise_level === "foothold") return "pulsing";
  return "compromised";
}

/**
 * Latest frame whose `elapsed_seconds <= liveElapsed`. Clamps to the first
 * frame when the live clock is still before any recorded state, and to the
 * last frame when the live run outlasts the ghost.
 */
export function selectMapFrame(
  frames: readonly GhostMapFrame[],
  liveElapsedSeconds: number,
): GhostMapFrame | null {
  if (frames.length === 0) return null;
  const sorted = [...frames].sort((a, b) => a.elapsed_seconds - b.elapsed_seconds);
  let chosen = sorted[0];
  for (const frame of sorted) {
    if (frame.elapsed_seconds <= liveElapsedSeconds) chosen = frame;
    else break;
  }
  return chosen;
}

export function frameToNetworkMap(frame: GhostMapFrame): {
  nodes: NetworkMapNode[];
  edges: NetworkMapEdge[];
  nodeStates: Record<string, NodeState>;
} {
  const nodes: NetworkMapNode[] = frame.hosts.map((h) => ({
    id: h.id,
    label: isGhostUnknownHost(h) ? "" : h.hostname,
    x: h.x,
    y: h.y,
  }));
  const edges: NetworkMapEdge[] = frame.edges.map((e) => ({
    source: e.source,
    target: e.target,
  }));
  const nodeStates: Record<string, NodeState> = {};
  for (const h of frame.hosts) nodeStates[h.id] = ghostHostNodeState(h);
  return { nodes, edges, nodeStates };
}

/**
 * Verb timeline entries that have already "fired" at the live clock,
 * rendered as AlertFeed lines with a Ghost: prefix. Independent list from
 * the live feed — same elapsed basis, not a shared timer.
 */
export function ghostVerbFeedLines(
  timeline: readonly GhostVerbEntry[],
  liveElapsedSeconds: number,
): FeedLine[] {
  return [...timeline]
    .filter((e) => e.elapsed_seconds <= liveElapsedSeconds)
    .sort((a, b) => a.sequence_number - b.sequence_number)
    .map((e) => {
      const label = VERB_FEED_LABEL[e.verb] ?? `${e.verb.replace(/_/g, " ")}.`;
      return {
        id: `ghost-verb-${e.sequence_number}`,
        ts: formatFeedClock(e.elapsed_seconds),
        text: `Ghost: ${label}`,
      };
    });
}
