import { describe, it, expect } from "vitest";
import {
  frameToNetworkMap,
  ghostHostNodeState,
  ghostVerbFeedLines,
  selectMapFrame,
  type GhostMapFrame,
} from "./ghostPlayback";
import { sampleGhostDto, sampleGhostFrames, sampleGhostTimeline } from "./ghostPlayback.fixture";

const frames = sampleGhostFrames;
const timeline = sampleGhostTimeline;

describe("selectMapFrame", () => {
  it("returns null for an empty frame list", () => {
    expect(selectMapFrame([], 30)).toBeNull();
  });

  it("picks the latest frame at or before the live elapsed clock", () => {
    expect(selectMapFrame(frames, 0)?.elapsed_seconds).toBe(0);
    expect(selectMapFrame(frames, 44)?.elapsed_seconds).toBe(0);
    expect(selectMapFrame(frames, 45)?.elapsed_seconds).toBe(45);
    expect(selectMapFrame(frames, 100)?.elapsed_seconds).toBe(45);
    expect(selectMapFrame(frames, 120)?.elapsed_seconds).toBe(120);
  });

  it("holds the last frame when the live run outlasts the ghost", () => {
    expect(selectMapFrame(frames, 999)?.elapsed_seconds).toBe(120);
  });

  it("clamps to the first frame when the live clock is before any frame", () => {
    const late: GhostMapFrame[] = [{ ...frames[1] }];
    expect(selectMapFrame(late, 0)?.elapsed_seconds).toBe(45);
  });
});

describe("ghostVerbFeedLines", () => {
  it("returns only verbs whose elapsed_seconds is at or before the live clock", () => {
    expect(ghostVerbFeedLines(timeline, 0)).toEqual([]);
    expect(ghostVerbFeedLines(timeline, 44)).toEqual([]);
    const atScan = ghostVerbFeedLines(timeline, 45);
    expect(atScan).toHaveLength(1);
    expect(atScan[0].text).toBe("Ghost: Network scan complete.");
    expect(atScan[0].ts).toBe("0:45");

    const later = ghostVerbFeedLines(timeline, 200);
    expect(later).toHaveLength(2);
    expect(later[1].text).toBe("Ghost: Host isolated.");
  });

  it("advances independently of map frames but on the same elapsed basis", () => {
    expect(selectMapFrame(frames, 45)?.elapsed_seconds).toBe(45);
    expect(ghostVerbFeedLines(timeline, 45).map((l) => l.id)).toEqual(["ghost-verb-0"]);
    expect(ghostVerbFeedLines(timeline, 119).map((l) => l.id)).toEqual(["ghost-verb-0"]);
    expect(ghostVerbFeedLines(timeline, 120).map((l) => l.id)).toEqual([
      "ghost-verb-0",
      "ghost-verb-1",
    ]);
  });
});

describe("frameToNetworkMap / ghostHostNodeState", () => {
  it("maps unknown / isolated / compromise to NetworkMap NodeStates", () => {
    expect(ghostHostNodeState(frames[0].hosts[0])).toBe("unknown");
    const known = frameToNetworkMap(frames[1]);
    expect(known.nodeStates.h1).toBe("clean");
    expect(known.nodeStates.h2).toBe("pulsing");
    expect(known.nodes.find((n) => n.id === "h1")?.label).toBe("CORP-WKS-22");
    const contained = frameToNetworkMap(frames[2]);
    expect(contained.nodeStates.h1).toBe("contained");
    expect(contained.nodeStates.h2).toBe("compromised");
  });

  it("sampleGhostDto is a valid Daily-shaped DTO", () => {
    const dto = sampleGhostDto();
    expect(dto.race_type).toBe("daily");
    expect(dto.map_frames.length).toBe(3);
  });
});
