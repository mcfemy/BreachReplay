import { describe, it, expect, beforeEach } from "vitest";
import {
  clearRaceGhost,
  loadRaceGhost,
  safeAuthNext,
  stashRaceGhost,
} from "./ghostRace";
import { sampleGhostDto } from "./ghostPlayback.fixture";

describe("ghostRace helpers", () => {
  beforeEach(() => {
    sessionStorage.clear();
  });

  it("stashes and loads a ghost DTO by run id", () => {
    const ghost = sampleGhostDto();
    stashRaceGhost("run-a", ghost);
    expect(loadRaceGhost("run-a")?.scenario_title).toBe(ghost.scenario_title);
    clearRaceGhost("run-a");
    expect(loadRaceGhost("run-a")).toBeNull();
  });

  it("safeAuthNext only allows same-origin relative paths", () => {
    expect(safeAuthNext("/r/tok?race=1")).toBe("/r/tok?race=1");
    expect(safeAuthNext("//evil.com")).toBeNull();
    expect(safeAuthNext("https://evil.com")).toBeNull();
    expect(safeAuthNext(null)).toBeNull();
  });
});
