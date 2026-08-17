import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ActionConsole from "./ActionConsole";
import { useAuthStore } from "../store/auth";
import { useRunSocket } from "../lib/useRunSocket";
import { axiosInstance } from "../lib/api";

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

  it("renders the verb chip bar and the empty-map fog-of-war message", () => {
    render(<ActionConsole runId="run-1" />);
    expect(screen.getByText("Scan Network")).toBeInTheDocument();
    expect(screen.getByText("Block IP")).toBeInTheDocument();
    expect(screen.getByText(/No hosts identified yet/i)).toBeInTheDocument();
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
});
