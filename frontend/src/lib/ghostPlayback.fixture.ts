/**
 * Built-in ghost DTO for `/dev/ghost-playback` and unit tests — not a
 * production path. Shapes match PR #50 Daily map-state-only frames.
 */
import type { GhostDto, GhostMapFrame, GhostVerbEntry } from "./ghostPlayback";

const frames: GhostMapFrame[] = [
  {
    elapsed_seconds: 0,
    hosts: [
      { id: "h1", x: 80, y: 60, visibility: "unknown" },
      { id: "h2", x: 230, y: 60, visibility: "unknown" },
    ],
    edges: [],
  },
  {
    elapsed_seconds: 45,
    hosts: [
      {
        id: "h1",
        hostname: "CORP-WKS-22",
        role: "workstation",
        network_segment_id: "lan",
        compromise_level: "none",
        isolated: false,
        x: 80,
        y: 60,
      },
      {
        id: "h2",
        hostname: "CORP-DC-01",
        role: "domain_controller",
        network_segment_id: "dc",
        compromise_level: "foothold",
        isolated: false,
        x: 230,
        y: 60,
      },
    ],
    edges: [{ source: "h1", target: "h2" }],
  },
  {
    elapsed_seconds: 120,
    hosts: [
      {
        id: "h1",
        hostname: "CORP-WKS-22",
        role: "workstation",
        network_segment_id: "lan",
        compromise_level: "none",
        isolated: true,
        x: 80,
        y: 60,
      },
      {
        id: "h2",
        hostname: "CORP-DC-01",
        role: "domain_controller",
        network_segment_id: "dc",
        compromise_level: "admin",
        isolated: false,
        x: 230,
        y: 60,
      },
    ],
    edges: [{ source: "h1", target: "h2" }],
  },
];

const timeline: GhostVerbEntry[] = [
  { sequence_number: 0, verb: "scan_network", elapsed_seconds: 45, cost: 45 },
  { sequence_number: 1, verb: "isolate", elapsed_seconds: 120, cost: 20 },
];

export function sampleGhostDto(overrides: Partial<GhostDto> = {}): GhostDto {
  return {
    race_type: "daily",
    outcome: "contained",
    score: 800,
    score_pct: 80,
    duration_seconds: 120,
    containment_seconds: 120,
    scenario_title: "Fixture Breach",
    mode: "daily",
    player_label: "Ghost Runner",
    verb_timeline: timeline,
    map_frames: frames,
    ghost_run_id: "ghost-fixture-1",
    ...overrides,
  };
}

export { frames as sampleGhostFrames, timeline as sampleGhostTimeline };
