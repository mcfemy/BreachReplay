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

  it("appends revealed IOC descriptions from lastDelta only when the IOC host is known-tier", () => {
    const lines = appendFeedLines({
      prevStagesFired: 0,
      stagesFired: 0,
      prevHosts: [known({})],
      hosts: [known({})],
      lastDeltaChanged: true,
      lastDelta: {
        revealed_iocs: [
          { rule_id: "r1", host_id: "h1", description: "Suspicious outbound DNS" },
        ],
      },
      elapsedSeconds: 3,
    });
    expect(lines).toEqual([
      { id: "ioc-r1", ts: "0:03", text: "Suspicious outbound DNS" },
    ]);
  });

  it("never names an unknown-tier host, even if a hostname is stuffed on the silhouette", () => {
    const unknownWithName = {
      id: "h9",
      x: 0,
      y: 0,
      visibility: "unknown" as const,
      hostname: "SECRET-DC-01",
      isolated: true,
      compromise_level: "domain_admin" as const,
    };
    const lines = appendFeedLines({
      prevStagesFired: 0,
      stagesFired: 1,
      prevHosts: [unknownWithName as HostSummary],
      hosts: [unknownWithName as HostSummary],
      lastDeltaChanged: true,
      lastDelta: {
        revealed_iocs: [
          {
            rule_id: "secret",
            host_id: "h9",
            description: "SECRET-DC-01 is the domain controller",
          },
        ],
        isolated: true,
      },
      elapsedSeconds: 9,
    });
    expect(lines.map((l) => l.text)).toEqual(["Lateral movement detected."]);
    expect(lines.some((l) => l.text.includes("SECRET-DC-01"))).toBe(false);
    expect(lines.some((l) => l.text.includes("h9"))).toBe(false);
  });
});
