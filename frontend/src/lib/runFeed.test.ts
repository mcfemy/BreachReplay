import { describe, expect, it } from "vitest";
import { appendFeedLines, formatFeedClock } from "./runFeed";
import type { HostSummary } from "./useRunSocket";

const known = (
  overrides: Partial<{ id: string; hostname: string; compromise_level: "none" | "foothold" | "admin"; isolated: boolean }>,
): HostSummary => ({
  id: "h1",
  hostname: "CORP-WKS-22",
  role: "workstation",
  network_segment_id: "lan",
  compromise_level: "none",
  isolated: false,
  ...overrides,
});

describe("runFeed", () => {
  it("formats the elapsed clock like the teaser timestamps", () => {
    expect(formatFeedClock(0)).toBe("0:00");
    expect(formatFeedClock(75)).toBe("1:15");
  });

  it("emits a generic lateral-movement line when stagesFired increases", () => {
    const lines = appendFeedLines({
      prevStagesFired: 0,
      stagesFired: 1,
      prevHosts: [],
      hosts: [],
      lastDeltaChanged: false,
      lastDelta: null,
      elapsedSeconds: 12,
    });
    expect(lines).toEqual([
      { id: "stage-1", ts: "0:12", text: "Lateral movement detected." },
    ]);
  });

  it("names a known host on isolate / compromise, never an unknown silhouette", () => {
    const unknown: HostSummary = { id: "h9", x: 0, y: 0, visibility: "unknown" };
    const lines = appendFeedLines({
      prevStagesFired: 0,
      stagesFired: 0,
      prevHosts: [unknown, known({ isolated: false, compromise_level: "none" })],
      hosts: [
        unknown,
        known({ isolated: true, compromise_level: "foothold" }),
      ],
      lastDeltaChanged: false,
      lastDelta: null,
      elapsedSeconds: 5,
    });
    expect(lines.map((l) => l.text)).toEqual([
      "CORP-WKS-22 isolated.",
      "CORP-WKS-22 showing signs of compromise.",
    ]);
    expect(lines.some((l) => l.text.toLowerCase().includes("unknown"))).toBe(false);
  });

  it("appends revealed IOC descriptions from lastDelta", () => {
    const lines = appendFeedLines({
      prevStagesFired: 0,
      stagesFired: 0,
      prevHosts: [],
      hosts: [],
      lastDeltaChanged: true,
      lastDelta: {
        revealed_iocs: [{ rule_id: "r1", description: "Suspicious outbound DNS" }],
      },
      elapsedSeconds: 3,
    });
    expect(lines).toEqual([
      { id: "ioc-r1", ts: "0:03", text: "Suspicious outbound DNS" },
    ]);
  });
});
