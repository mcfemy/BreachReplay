import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ActionConsole from "./ActionConsole";
import { useAuthStore } from "../store/auth";
import { useRunSocket } from "../lib/useRunSocket";

// Real WebSocket is out of scope for a smoke test — mock the hook's return
// value directly, same shape ActionConsole.tsx destructures off `run`.
// The module's real exported constants (VERB_COSTS, UNTARGETED_VERBS, ...)
// stay real via importOriginal, since ActionConsole imports those directly.
vi.mock("../lib/useRunSocket", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/useRunSocket")>();
  return { ...actual, useRunSocket: vi.fn() };
});

const submitVerb = vi.fn();

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
    useAuthStore.setState({
      user: {
        id: "u1",
        email: "responder@example.com",
        full_name: "Test Responder",
        role: "user",
        organization_id: null,
        has_seen_console_intro: true, // skip the pre-brief overlay
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
});
