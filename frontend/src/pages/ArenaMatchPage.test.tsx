import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import ArenaMatchPage from "./ArenaMatchPage";
import { useAuthStore } from "../store/auth";
import { useArenaSocket } from "../lib/useArenaSocket";
import { api } from "../lib/api";
import {
  playChime,
  playThud,
  playTick,
  resetSoundForTests,
  setSoundEnabled,
  SOUND_STORAGE_KEY,
} from "../lib/sound";

vi.mock("../lib/useArenaSocket", () => ({
  useArenaSocket: vi.fn(),
}));

vi.mock("../lib/api", () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  axiosInstance: { get: vi.fn(), post: vi.fn() },
  API_BASE: "http://test.invalid",
}));

// Spy wrappers around the real helpers so call sites are assertable while
// mute/unlock still run through sound.ts (same path production uses).
vi.mock("../lib/sound", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/sound")>();
  return {
    ...actual,
    playTick: vi.fn(actual.playTick),
    playThud: vi.fn(actual.playThud),
    playChime: vi.fn(actual.playChime),
  };
});

const MATCH = {
  id: "match-1",
  mode: "human_defends_vs_ai" as const,
  archetype_key: "flat_smb",
  difficulty: "medium",
  status: "active",
  attacker_user_id: null as string | null,
  defender_user_id: "defender-1" as string | null,
  action_count: 3,
  state: {
    hosts: [
      {
        id: "h1",
        hostname: "CORP-WKS-01",
        role: "workstation",
        network_segment_id: "seg1",
        unpatched_cves: [] as string[],
        edr_installed: false,
        compromise_level: "foothold" as const,
        isolated: false,
      },
    ],
    segments: [{ id: "seg1", name: "Corp LAN", monitored: true, reachable_from: [] as string[] }],
    credentials: [],
    detection_rules: [],
    global_flags: {},
  },
};

function baseSocketState(overrides: Partial<ReturnType<typeof useArenaSocket>> = {}) {
  return {
    connected: true,
    alerts: [],
    currentGate: null,
    lastActionResult: null,
    lastDecisionResult: null,
    lastDefenderActionResult: null,
    matchComplete: null,
    sendAttackerAction: vi.fn(),
    sendDefenderAction: vi.fn(),
    ping: vi.fn(),
    ...overrides,
  };
}

function mockAudioContext() {
  const instances: { createOscillator: ReturnType<typeof vi.fn> }[] = [];
  class FakeAudioContext {
    state = "running";
    currentTime = 0;
    destination = {};
    resume = vi.fn().mockResolvedValue(undefined);
    createOscillator = vi.fn(() => ({
      type: "sine",
      frequency: { setValueAtTime: vi.fn(), exponentialRampToValueAtTime: vi.fn() },
      connect: vi.fn(),
      start: vi.fn(),
      stop: vi.fn(),
    }));
    createGain = vi.fn(() => ({
      gain: { setValueAtTime: vi.fn(), exponentialRampToValueAtTime: vi.fn() },
      connect: vi.fn(),
    }));
    constructor() {
      instances.push(this);
    }
  }
  vi.stubGlobal("AudioContext", FakeAudioContext);
  return { instances };
}

function tree() {
  return (
    <MemoryRouter initialEntries={["/arena/match/match-1"]}>
      <Routes>
        <Route path="/arena/match/:matchId" element={<ArenaMatchPage />} />
        <Route path="/arena" element={<div>Arena Lobby</div>} />
      </Routes>
    </MemoryRouter>
  );
}

function setSocket(overrides: Partial<ReturnType<typeof useArenaSocket>>) {
  vi.mocked(useArenaSocket).mockReturnValue(baseSocketState(overrides));
}

describe("ArenaMatchPage sound cues", () => {
  beforeEach(() => {
    resetSoundForTests();
    localStorage.clear();
    vi.mocked(playTick).mockClear();
    vi.mocked(playThud).mockClear();
    vi.mocked(playChime).mockClear();
    vi.mocked(api.get).mockResolvedValue(MATCH);
    useAuthStore.setState({
      user: {
        id: "defender-1",
        email: "blue@example.com",
        full_name: "Blue Team",
        role: "user",
        organization_id: null,
        has_seen_console_intro: true,
        seen_verb_coachmarks: [],
        has_acknowledged_racing_notice: true,
      },
      token: "tok",
      refreshToken: "ref",
    });
    setSocket({});
  });

  afterEach(() => {
    resetSoundForTests();
    vi.unstubAllGlobals();
  });

  it("does not fire cues on mount", async () => {
    render(tree());
    await screen.findByText("⚔️ Live Arena");
    expect(playTick).not.toHaveBeenCalled();
    expect(playThud).not.toHaveBeenCalled();
    expect(playChime).not.toHaveBeenCalled();
  });

  it("thuds when isolate_host decision_result lands", async () => {
    const { rerender } = render(tree());
    await screen.findByText("⚔️ Live Arena");

    setSocket({
      lastDecisionResult: {
        decision_gate_id: null,
        is_correct: true,
        rationale: "Isolate Host applied.",
        consequence_applied: "isolate_host executed against the live org state.",
        correct_index: null,
        action_type: "isolate_host",
        payload: { host_id: "h1" },
        sequence_number: 4,
      },
    });
    rerender(tree());

    expect(playThud).toHaveBeenCalledTimes(1);
    expect(playChime).not.toHaveBeenCalled();
  });

  it("thuds when disable_credential decision_result lands", async () => {
    const { rerender } = render(tree());
    await screen.findByText("⚔️ Live Arena");

    setSocket({
      lastDecisionResult: {
        decision_gate_id: null,
        is_correct: true,
        rationale: "Disable Credential applied.",
        consequence_applied: "disable_credential executed against the live org state.",
        correct_index: null,
        action_type: "disable_credential",
        payload: { credential_id: "c1" },
        sequence_number: 5,
      },
    });
    rerender(tree());

    expect(playThud).toHaveBeenCalledTimes(1);
  });

  it("does not thud on non-containment defender actions", async () => {
    const { rerender } = render(tree());
    await screen.findByText("⚔️ Live Arena");

    setSocket({
      lastDecisionResult: {
        decision_gate_id: null,
        is_correct: true,
        rationale: "Increase Monitoring applied.",
        consequence_applied: "increase_monitoring executed against the live org state.",
        correct_index: null,
        action_type: "increase_monitoring",
        payload: { segment_id: "seg1" },
        sequence_number: 6,
      },
    });
    rerender(tree());

    expect(playThud).not.toHaveBeenCalled();
  });

  it("chimes when a defending human wins", async () => {
    const { rerender } = render(tree());
    await screen.findByText("⚔️ Live Arena");

    setSocket({ matchComplete: { status: "defender_won", sequence_number: 12 } });
    rerender(tree());

    await waitFor(() => expect(playChime).toHaveBeenCalledTimes(1));
  });

  it("chimes when an attacking human wins", async () => {
    vi.mocked(api.get).mockResolvedValue({
      ...MATCH,
      mode: "human_attacks_vs_ai",
      attacker_user_id: "attacker-1",
      defender_user_id: null,
    });
    useAuthStore.setState({
      user: {
        id: "attacker-1",
        email: "red@example.com",
        full_name: "Red Team",
        role: "user",
        organization_id: null,
        has_seen_console_intro: true,
        seen_verb_coachmarks: [],
        has_acknowledged_racing_notice: true,
      },
    });

    const { rerender } = render(tree());
    await screen.findByText("⚔️ Live Arena");

    setSocket({ matchComplete: { status: "attacker_won", sequence_number: 12 } });
    rerender(tree());

    await waitFor(() => expect(playChime).toHaveBeenCalledTimes(1));
  });

  it("does not chime when the human loses", async () => {
    const { rerender } = render(tree());
    await screen.findByText("⚔️ Live Arena");

    setSocket({ matchComplete: { status: "attacker_won", sequence_number: 12 } });
    rerender(tree());

    await screen.findByText(/Match Complete/i);
    expect(playChime).not.toHaveBeenCalled();
  });

  it("does not chime on abandon", async () => {
    const { rerender } = render(tree());
    await screen.findByText("⚔️ Live Arena");

    setSocket({ matchComplete: { status: "abandoned", sequence_number: 3 } });
    rerender(tree());

    await screen.findByText(/Match Complete/i);
    expect(playChime).not.toHaveBeenCalled();
  });

  it("never calls playTick — Arena has no player-facing clock pressure cue", async () => {
    const { rerender } = render(tree());
    await screen.findByText("⚔️ Live Arena");

    setSocket({
      lastDecisionResult: {
        decision_gate_id: null,
        is_correct: true,
        rationale: "Isolate Host applied.",
        consequence_applied: "isolate_host executed.",
        correct_index: null,
        action_type: "isolate_host",
        sequence_number: 4,
      },
      matchComplete: { status: "defender_won", sequence_number: 12 },
    });
    rerender(tree());

    await waitFor(() => expect(playChime).toHaveBeenCalled());
    expect(playTick).not.toHaveBeenCalled();
  });

  it("respects muted state — cue helpers are invoked but produce no audio", async () => {
    const { instances } = mockAudioContext();
    expect(localStorage.getItem(SOUND_STORAGE_KEY)).toBeNull();

    const { rerender } = render(tree());
    await screen.findByText("⚔️ Live Arena");

    setSocket({
      lastDecisionResult: {
        decision_gate_id: null,
        is_correct: true,
        rationale: "Isolate Host applied.",
        consequence_applied: "isolate_host executed.",
        correct_index: null,
        action_type: "isolate_host",
        sequence_number: 4,
      },
    });
    rerender(tree());

    expect(playThud).toHaveBeenCalledTimes(1);
    expect(instances).toHaveLength(0);
  });

  it("plays audio after sound is enabled (toggle unlocks the shared context)", async () => {
    const { instances } = mockAudioContext();
    setSoundEnabled(true);

    const { rerender } = render(tree());
    await screen.findByText("⚔️ Live Arena");

    setSocket({
      lastDecisionResult: {
        decision_gate_id: null,
        is_correct: true,
        rationale: "Isolate Host applied.",
        consequence_applied: "isolate_host executed.",
        correct_index: null,
        action_type: "isolate_host",
        sequence_number: 4,
      },
    });
    rerender(tree());

    expect(playThud).toHaveBeenCalledTimes(1);
    expect(instances.length).toBeGreaterThan(0);
    expect(instances[0].createOscillator).toHaveBeenCalled();
  });
});
