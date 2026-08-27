import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import PublicActionReplayPage from "./PublicActionReplayPage";
import { axiosInstance } from "../lib/api";
import { sampleGhostDto } from "../lib/ghostPlayback.fixture";

vi.mock("../lib/api", () => ({
  axiosInstance: { get: vi.fn(), post: vi.fn() },
  API_BASE: "http://test.invalid",
}));

const startGhostRace = vi.fn();
vi.mock("../lib/ghostRace", async () => {
  const actual = await vi.importActual<typeof import("../lib/ghostRace")>("../lib/ghostRace");
  return {
    ...actual,
    startGhostRace: (...args: unknown[]) => startGhostRace(...args),
  };
});

vi.mock("../store/auth", () => ({
  useAuthStore: (sel: (s: { token: string | null }) => unknown) =>
    sel({ token: mockToken }),
}));

let mockToken: string | null = "authed-token";

const REPLAY = {
  outcome: "contained" as const,
  score: 800,
  score_pct: 80,
  duration_seconds: 90,
  scenario_title: "Colonial Pipeline Replay",
  mode: "scenario" as const,
  player_label: "Responder",
  timeline: [
    { sequence_number: 0, verb: "scan_network", elapsed_seconds: 45, cost: 45 },
    { sequence_number: 1, verb: "isolate", elapsed_seconds: 65, cost: 20 },
  ],
  hosts: [
    { id: "unknown-1", x: 80, y: 60, visibility: "unknown" as const },
    {
      id: "known-1",
      hostname: "CORP-WKS-22",
      role: "workstation",
      network_segment_id: "lan",
      compromise_level: "none" as const,
      isolated: true,
      x: 230,
      y: 60,
    },
  ],
  edges: [],
  techniques_encountered: [],
};

function renderPage(token = "tok123", initialPath?: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const entry = initialPath ?? `/r/${token}`;
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[entry]}>
        <Routes>
          <Route path="/r/:shareToken" element={<PublicActionReplayPage />} />
          <Route path="/login" element={<div data-testid="login-page">Login</div>} />
          <Route path="/race/:runId" element={<div data-testid="race-dest">Race</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("PublicActionReplayPage — Race this run", () => {
  beforeEach(() => {
    mockToken = "authed-token";
    startGhostRace.mockReset();
    startGhostRace.mockResolvedValue({
      run_id: "race-run-9",
      action_run_id: "race-run-9",
      scenario_id: "scn-1",
      seed: 42,
      mode: "scenario",
      cap_seconds: 600,
      ghost: { ...sampleGhostDto(), share_token: "tok123", race_type: "scenario" },
    });
    vi.mocked(axiosInstance.get).mockResolvedValue({ data: REPLAY });
  });

  it("shows Race this run and starts a race when authenticated", async () => {
    const user = userEvent.setup();
    renderPage();
    expect(await screen.findByTestId("race-this-run")).toBeInTheDocument();
    await user.click(screen.getByTestId("race-this-run"));
    await waitFor(() =>
      expect(startGhostRace).toHaveBeenCalledWith({ share_token: "tok123" }),
    );
    expect(await screen.findByTestId("race-dest")).toBeInTheDocument();
  });

  it("sends unauthenticated visitors to login with next back to race", async () => {
    mockToken = null;
    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByTestId("race-this-run"));
    expect(await screen.findByTestId("login-page")).toBeInTheDocument();
    expect(startGhostRace).not.toHaveBeenCalled();
  });
});
