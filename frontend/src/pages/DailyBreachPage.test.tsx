import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import DailyBreachPage from "./DailyBreachPage";
import { axiosInstance } from "../lib/api";

// Real HTTP is out of scope for a smoke test — axiosInstance is the one
// module every data call in this page goes through.
vi.mock("../lib/api", () => ({
  axiosInstance: { get: vi.fn(), post: vi.fn() },
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  API_BASE: "http://test.invalid",
}));

// ActionConsole opens a real WebSocket (see its own test file) — irrelevant
// to this page's own "load challenge, start run" smoke coverage.
vi.mock("../components/ActionConsole", () => ({
  default: () => <div>Action Console Stub</div>,
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

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <DailyBreachPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("DailyBreachPage", () => {
  beforeEach(() => {
    vi.mocked(axiosInstance.get).mockImplementation((url: string) => {
      if (url === "/daily/today") return Promise.resolve({ data: CHALLENGE });
      if (url === "/daily/streak") return Promise.resolve({ data: STREAK });
      if (url.startsWith("/daily/leaderboard/")) return Promise.resolve({ data: [] });
      if (url.startsWith("/daily/action-leaderboard/")) return Promise.resolve({ data: [] });
      if (url === "/learning/knowledge-check/next") return Promise.reject(new Error("none due"));
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

  it("loads today's challenge and shows the respond CTA", async () => {
    renderPage();
    expect(await screen.findByText("Colonial Pipeline")).toBeInTheDocument();
    expect(screen.getByText("🚨 RESPOND NOW")).toBeInTheDocument();
  });

  it("starts a run via POST /daily/action-run on RESPOND NOW", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByText("🚨 RESPOND NOW"));

    await waitFor(() =>
      expect(axiosInstance.post).toHaveBeenCalledWith("/daily/action-run", {}),
    );
    expect(await screen.findByText("Action Console Stub")).toBeInTheDocument();
  });
});
