import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEffect } from "react";
import DailyBreachPage from "./DailyBreachPage";
import { axiosInstance } from "../lib/api";
import { sampleGhostDto } from "../lib/ghostPlayback.fixture";

vi.mock("../lib/api", () => ({
  axiosInstance: { get: vi.fn(), post: vi.fn() },
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
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

const RUN_END = {
  action_run_id: "ar-finished",
  outcome: "contained" as const,
  score_breakdown: {
    outcome: "contained" as const,
    total_score: 500,
    outcome_base: 400,
    evidence_points: 100,
    evidence_found: 1,
    evidence_total: 2,
    speed_bonus: 0,
    penalty_total: 0,
    penalties: [] as { type: string }[],
    collateral: [] as { host_id: string; hostname: string; weight: number }[],
    collateral_penalty: 0,
    notifications: [],
    notification_points: 0,
    notification_penalty: 0,
    score_pct: 50,
  },
  xp_awarded: 50,
  new_achievements: [] as string[],
  techniques_encountered: [],
  daily_challenge_id: "chal-1",
  challenge_number: 42,
  rank: 2,
  current_streak: 3,
  longest_streak: 7,
  total_dailies_played: 10,
  total_attempts_today: 5,
  avg_score_today: 400,
};

vi.mock("../components/ActionConsole", () => ({
  default: ({ onComplete }: { onComplete?: (s: typeof RUN_END) => void }) => {
    useEffect(() => {
      onComplete?.(RUN_END);
    }, [onComplete]);
    return <div>Action Console Stub</div>;
  },
}));

const CHALLENGE = {
  id: "chal-1",
  challenge_number: 42,
  challenge_date: "2026-08-10",
  scenario_id: "scn-1",
  scenario_title: "Colonial Pipeline",
  scenario_difficulty: "practitioner" as const,
  scenario_industry: "energy",
  initial_access_vector: "VPN credential reuse",
  gates_count: 5,
  total_attempts: 12,
  already_played: false,
  my_attempt: null,
};

const STREAK = {
  current_streak: 3,
  longest_streak: 7,
  total_dailies_played: 10,
  last_played_date: "2026-08-09",
  played_today: false,
};

function renderPage(initial = "/daily") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[initial]}>
        <Routes>
          <Route path="/daily" element={<DailyBreachPage />} />
          <Route path="/race/:runId" element={<div data-testid="race-dest">Race room</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("DailyBreachPage — Race a ghost", () => {
  beforeEach(() => {
    startGhostRace.mockReset();
    startGhostRace.mockResolvedValue({
      run_id: "race-run-1",
      action_run_id: "race-run-1",
      scenario_id: "scn-1",
      seed: 99,
      mode: "scenario",
      cap_seconds: 600,
      ghost: { ...sampleGhostDto(), ghost_run_id: "ghost-above" },
    });

    vi.mocked(axiosInstance.get).mockImplementation((url: string) => {
      if (url === "/daily/today") return Promise.resolve({ data: CHALLENGE });
      if (url === "/daily/streak") return Promise.resolve({ data: STREAK });
      if (url.startsWith("/daily/leaderboard/")) return Promise.resolve({ data: [] });
      if (url.startsWith("/daily/action-leaderboard/")) return Promise.resolve({ data: [] });
      if (url === "/learning/knowledge-check/next") return Promise.reject(new Error("none due"));
      if (url === "/daily/ghost") {
        return Promise.resolve({
          data: { ...sampleGhostDto(), ghost_run_id: "ghost-above", race_type: "daily" },
        });
      }
      return Promise.reject(new Error(`unexpected GET ${url}`));
    });
    vi.mocked(axiosInstance.post).mockResolvedValue({
      data: {
        run_id: "run-1",
        daily_challenge_id: CHALLENGE.id,
        challenge_number: CHALLENGE.challenge_number,
        scenario_id: CHALLENGE.scenario_id,
        seed: 1,
        mode: "daily",
        cap_seconds: 480,
        resumed: false,
      },
    });
  });

  it("after finish, offers Race a ghost and starts POST /action-runs/race", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByText("🚨 RESPOND NOW"));

    expect(await screen.findByTestId("daily-race-ghost")).toBeInTheDocument();
    await user.click(screen.getByTestId("daily-race-ghost"));

    await waitFor(() =>
      expect(startGhostRace).toHaveBeenCalledWith({ ghost_run_id: "ghost-above" }),
    );
    expect(await screen.findByTestId("race-dest")).toBeInTheDocument();
  });

  it("hides Race a ghost when GET /daily/ghost has no neighbor", async () => {
    vi.mocked(axiosInstance.get).mockImplementation((url: string) => {
      if (url === "/daily/today") return Promise.resolve({ data: CHALLENGE });
      if (url === "/daily/streak") return Promise.resolve({ data: STREAK });
      if (url.startsWith("/daily/leaderboard/")) return Promise.resolve({ data: [] });
      if (url.startsWith("/daily/action-leaderboard/")) return Promise.resolve({ data: [] });
      if (url === "/learning/knowledge-check/next") return Promise.reject(new Error("none due"));
      if (url === "/daily/ghost") return Promise.reject(Object.assign(new Error("not found"), { response: { status: 404 } }));
      return Promise.reject(new Error(`unexpected GET ${url}`));
    });

    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByText("🚨 RESPOND NOW"));

    expect(await screen.findByTestId("daily-race-ghost-unavailable")).toBeInTheDocument();
    expect(screen.queryByTestId("daily-race-ghost")).not.toBeInTheDocument();
  });
});
