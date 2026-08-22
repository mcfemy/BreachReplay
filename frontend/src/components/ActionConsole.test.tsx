import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ActionConsole from "./ActionConsole";
import { useAuthStore } from "../store/auth";
import { useRunSocket } from "../lib/useRunSocket";
import type { RunEndSummary } from "../lib/useRunSocket";
import { axiosInstance } from "../lib/api";
import { playChime, playTick, playThud } from "../lib/sound";

// Real WebSocket is out of scope for a smoke test — mock the hook's return
// value directly, same shape ActionConsole.tsx destructures off `run`.
// The module's real exported constants (VERB_COSTS, UNTARGETED_VERBS, ...)
// stay real via importOriginal, since ActionConsole imports those directly.
vi.mock("../lib/useRunSocket", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/useRunSocket")>();
  return { ...actual, useRunSocket: vi.fn() };
});

vi.mock("../lib/api", () => ({
  axiosInstance: { patch: vi.fn() },
  API_BASE: "http://test.invalid",
}));

vi.mock("../lib/sound", () => ({
  playTick: vi.fn(),
  playThud: vi.fn(),
  playChime: vi.fn(),
}));

const submitVerb = vi.fn();

// All 8 verbs "already seen" — the default fixture for every test below
// EXCEPT the coachmark-specific ones, so the existing tap-behavior tests
// don't get intercepted by a first-use coachmark they aren't testing for.
const ALL_VERBS_SEEN = [
  "scan_network", "query_logs", "isolate", "image_disk",
  "interview_user", "block_ip", "reset_creds", "escalate",
];

function baseRunState(overrides: Partial<ReturnType<typeof useRunSocket>> = {}) {
  return {
    connected: true,
    elapsedSeconds: 0,
    attackerClockSeconds: 30,
    capSeconds: 600,
    hosts: [],
    forensicsByHost: {},
    revealedIocs: [],
    credentialsByHost: {},
    edges: [],
    notificationParties: [],
    notifiedPartyIds: [],
    stagesFired: 0,
    totalStages: 4,
    isFinalReached: false,
    lastDelta: null,
    error: null,
    runEnd: null,
    submitVerb,
    ping: vi.fn(),
    ...overrides,
  };
}

describe("ActionConsole", () => {
  beforeEach(() => {
    submitVerb.mockClear();
    vi.mocked(playTick).mockClear();
    vi.mocked(playThud).mockClear();
    vi.mocked(playChime).mockClear();
    vi.mocked(axiosInstance.patch).mockReset();
    useAuthStore.setState({
      user: {
        id: "u1",
        email: "responder@example.com",
        full_name: "Test Responder",
        role: "user",
        organization_id: null,
        has_seen_console_intro: true, // skip the pre-brief overlay
        seen_verb_coachmarks: ALL_VERBS_SEEN,
      },
    });
    vi.mocked(useRunSocket).mockReturnValue(baseRunState());
  });

  it("renders the verb chip bar and unknown-state nodes on the pre-scan map", () => {
    vi.mocked(useRunSocket).mockReturnValue(
      baseRunState({
        hosts: [
          { id: "h1", x: 80, y: 60, visibility: "unknown" },
          { id: "h2", x: 230, y: 60, visibility: "unknown" },
        ],
      }),
    );
    render(<ActionConsole runId="run-1" />);
    expect(screen.getByText("Scan Network")).toBeInTheDocument();
    expect(screen.getByText("Block IP")).toBeInTheDocument();
    expect(screen.queryByText(/No hosts identified yet/i)).not.toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Network topology map" })).toBeInTheDocument();
    expect(screen.getAllByLabelText("Unknown host")).toHaveLength(2);
    // Legend is complete — every NodeState, not the old 2-of-4 subset.
    for (const state of ["unknown", "clean", "pulsing", "compromised", "contained"]) {
      expect(screen.getByText(state)).toBeInTheDocument();
    }
    // Leak-safety: unknown tier must not surface a hostname.
    expect(screen.queryByText("CORP-WKS-22")).not.toBeInTheDocument();
  });

  it("submits the untargeted scan_network verb immediately on tap", async () => {
    const user = userEvent.setup();
    render(<ActionConsole runId="run-1" />);
    await user.click(screen.getByText("Scan Network"));
    expect(submitVerb).toHaveBeenCalledWith("scan_network");
  });

  it("shows a party picker on Escalate, never the warranted answer", async () => {
    vi.mocked(useRunSocket).mockReturnValue(
      baseRunState({ notificationParties: [{ id: "cisa", party_name: "CISA" }] }),
    );
    const user = userEvent.setup();
    render(<ActionConsole runId="run-1" />);
    await user.click(screen.getByText("Escalate"));
    expect(screen.getByText("CISA")).toBeInTheDocument();
    // The picker must never render "warranted" content — that's the
    // player's own judgment call, not something the UI hands them.
    expect(screen.queryByText(/warranted/i)).not.toBeInTheDocument();
  });

  it("submits escalate with the tapped party's id", async () => {
    vi.mocked(useRunSocket).mockReturnValue(
      baseRunState({ notificationParties: [{ id: "cisa", party_name: "CISA" }] }),
    );
    const user = userEvent.setup();
    render(<ActionConsole runId="run-1" />);
    await user.click(screen.getByText("Escalate"));
    await user.click(screen.getByText("CISA"));
    expect(submitVerb).toHaveBeenCalledWith("escalate", "cisa");
  });

  it("submits escalate immediately, no picker, on a scenario with no notification matrix", async () => {
    // baseRunState()'s default notificationParties is already [] — the
    // matrix-less-scenario case (verb_engine's own fallback path on PR
    // #25's review finding: escalate must not become a dead verb, or the
    // picker a dead end, on a scenario nobody's authored a matrix for yet).
    const user = userEvent.setup();
    render(<ActionConsole runId="run-1" />);
    await user.click(screen.getByText("Escalate"));
    expect(submitVerb).toHaveBeenCalledWith("escalate");
    // No picker opened — nothing besides the verb chip bar itself should
    // show "who do you notify?".
    expect(screen.queryByText(/who do you notify/i)).not.toBeInTheDocument();
  });

  it("disables an already-notified party in the picker", async () => {
    vi.mocked(useRunSocket).mockReturnValue(
      baseRunState({
        notificationParties: [{ id: "cisa", party_name: "CISA" }],
        notifiedPartyIds: ["cisa"],
      }),
    );
    const user = userEvent.setup();
    render(<ActionConsole runId="run-1" />);
    await user.click(screen.getByText("Escalate"));
    expect(screen.getByText("CISA").closest("button")).toBeDisabled();
  });

  describe("per-verb coachmarks", () => {
    it("shows a coachmark with the verb's own targeting-mode text on first use, and doesn't submit yet", async () => {
      useAuthStore.setState({
        user: {
          id: "u1",
          email: "responder@example.com",
          full_name: "Test Responder",
          role: "user",
          organization_id: null,
          has_seen_console_intro: true,
          seen_verb_coachmarks: [], // nothing seen yet
        },
      });
      const user = userEvent.setup();
      render(<ActionConsole runId="run-1" />);

      // query_logs is host-targeted — its coachmark must say "tap a host",
      // not block_ip/reset_creds' "type a value" or escalate's "pick who".
      await user.click(screen.getByText("Query Logs"));
      const tooltip = screen.getByRole("tooltip");
      expect(tooltip).toHaveTextContent("Pulls log data from a host. May reveal indicators of compromise.");
      expect(tooltip).toHaveTextContent("Tap a host on the map to target it.");

      // Neither the verb's submit nor its target-select UI has fired yet —
      // the coachmark intercepts the tap until dismissed.
      expect(submitVerb).not.toHaveBeenCalled();
      expect(screen.queryByText(/tap a host on the map$/i)).not.toBeInTheDocument();
    });

    it("persists the dismissed verb via PATCH /auth/me and then proceeds with the original tap", async () => {
      useAuthStore.setState({
        user: {
          id: "u1",
          email: "responder@example.com",
          full_name: "Test Responder",
          role: "user",
          organization_id: null,
          has_seen_console_intro: true,
          seen_verb_coachmarks: [],
        },
      });
      vi.mocked(axiosInstance.patch).mockResolvedValue({
        data: { seen_verb_coachmarks: ["scan_network"] },
      });
      const user = userEvent.setup();
      render(<ActionConsole runId="run-1" />);

      await user.click(screen.getByText("Scan Network"));
      expect(submitVerb).not.toHaveBeenCalled();

      await user.click(screen.getByText("Got it"));
      expect(axiosInstance.patch).toHaveBeenCalledWith("/auth/me", {
        seen_verb_coachmarks: ["scan_network"],
      });
      // scan_network is untargeted — dismissing its coachmark submits it
      // immediately, same as an already-seen verb would.
      expect(submitVerb).toHaveBeenCalledWith("scan_network");
      expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
    });

    it("never re-shows a coachmark for a verb already in seen_verb_coachmarks", async () => {
      const user = userEvent.setup();
      render(<ActionConsole runId="run-1" />); // default fixture: ALL_VERBS_SEEN
      await user.click(screen.getByText("Scan Network"));
      expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
      expect(submitVerb).toHaveBeenCalledWith("scan_network");
    });
  });

  describe("sound cues", () => {
    it("does not fire cues on mount", () => {
      render(<ActionConsole runId="run-1" />);
      expect(playTick).not.toHaveBeenCalled();
      expect(playThud).not.toHaveBeenCalled();
      expect(playChime).not.toHaveBeenCalled();
    });

    it("thuds when lastDelta reports isolation", () => {
      const { rerender } = render(<ActionConsole runId="run-1" />);
      vi.mocked(useRunSocket).mockReturnValue(
        baseRunState({ lastDelta: { isolated: true, host_id: "h1" } }),
      );
      rerender(<ActionConsole runId="run-1" />);
      expect(playThud).toHaveBeenCalledTimes(1);
    });

    it("thuds when lastDelta reports a correct targeted action", () => {
      const { rerender } = render(<ActionConsole runId="run-1" />);
      vi.mocked(useRunSocket).mockReturnValue(
        baseRunState({ lastDelta: { correct: true } }),
      );
      rerender(<ActionConsole runId="run-1" />);
      expect(playThud).toHaveBeenCalledTimes(1);
    });

    it("does not thud on an incorrect guess", () => {
      const { rerender } = render(<ActionConsole runId="run-1" />);
      vi.mocked(useRunSocket).mockReturnValue(
        baseRunState({ lastDelta: { correct: false } }),
      );
      rerender(<ActionConsole runId="run-1" />);
      expect(playThud).not.toHaveBeenCalled();
    });

    it("ticks once when remaining budget first drops to 60s", () => {
      const { rerender } = render(<ActionConsole runId="run-1" />);
      expect(playTick).not.toHaveBeenCalled();
      vi.mocked(useRunSocket).mockReturnValue(
        baseRunState({ attackerClockSeconds: 540, capSeconds: 600 }),
      );
      rerender(<ActionConsole runId="run-1" />);
      expect(playTick).toHaveBeenCalledTimes(1);
      vi.mocked(useRunSocket).mockReturnValue(
        baseRunState({ attackerClockSeconds: 550, capSeconds: 600 }),
      );
      rerender(<ActionConsole runId="run-1" />);
      expect(playTick).toHaveBeenCalledTimes(1);
    });

    it("does not tick when there is no response-budget cap", () => {
      vi.mocked(useRunSocket).mockReturnValue(
        baseRunState({ attackerClockSeconds: 90, capSeconds: 0 }),
      );
      render(<ActionConsole runId="run-1" />);
      expect(playTick).not.toHaveBeenCalled();
    });

    it("chimes when the run ends contained", () => {
      const { rerender } = render(<ActionConsole runId="run-1" />);
      vi.mocked(useRunSocket).mockReturnValue(baseRunState({ runEnd: stubRunEnd("contained") }));
      rerender(<ActionConsole runId="run-1" />);
      expect(playChime).toHaveBeenCalledTimes(1);
    });

    it("chimes when the run ends contained_at_cost", () => {
      const { rerender } = render(<ActionConsole runId="run-1" />);
      vi.mocked(useRunSocket).mockReturnValue(
        baseRunState({ runEnd: stubRunEnd("contained_at_cost") }),
      );
      rerender(<ActionConsole runId="run-1" />);
      expect(playChime).toHaveBeenCalledTimes(1);
    });

    it("does not chime when the run ends breached", () => {
      const { rerender } = render(<ActionConsole runId="run-1" />);
      vi.mocked(useRunSocket).mockReturnValue(baseRunState({ runEnd: stubRunEnd("breached") }));
      rerender(<ActionConsole runId="run-1" />);
      expect(playChime).not.toHaveBeenCalled();
    });
  });
});

function stubRunEnd(outcome: RunEndSummary["outcome"]): RunEndSummary {
  return {
    action_run_id: "run-1",
    outcome,
    score_breakdown: {
      outcome,
      outcome_base: 800,
      evidence_points: 0,
      evidence_found: 0,
      evidence_total: 0,
      speed_bonus: 0,
      penalty_total: 0,
      penalties: [],
      collateral: [],
      collateral_penalty: 0,
      notifications: [],
      notification_points: 0,
      notification_penalty: 0,
      total_score: 800,
      score_pct: 80,
    },
    xp_awarded: 0,
    new_achievements: [],
    techniques_encountered: [],
  };
}
