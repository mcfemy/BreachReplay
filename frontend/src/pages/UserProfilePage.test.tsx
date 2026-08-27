import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import UserProfilePage from "./UserProfilePage";

vi.mock("../lib/api", () => ({
  axiosInstance: {
    get: vi.fn(),
    post: vi.fn(),
    patch: vi.fn(),
  },
  api: { get: vi.fn() },
}));

vi.mock("../store/auth", () => ({
  useAuthStore: (sel?: (s: { user: { role: string } | null }) => unknown) => {
    const state = { user: { role: "analyst" } };
    return sel ? sel(state) : state;
  },
}));

import { axiosInstance } from "../lib/api";
import { api } from "../lib/api";

const PROFILE = {
  id: "user-1",
  email: "analyst@example.com",
  full_name: "Test Analyst",
  role: "analyst",
  xp_total: 2500,
  career_tier: { key: "soc_analyst", label: "SOC Analyst", color: "#3b82f6", min_xp: 1000 },
  tier_progress: {
    current_tier: { key: "soc_analyst", label: "SOC Analyst", color: "#3b82f6", min_xp: 1000 },
    next_tier: { key: "incident_responder", label: "Incident Responder", color: "#8b5cf6", min_xp: 5000 },
    xp_in_tier: 1500,
    xp_to_next: 2500,
    tier_range: 4000,
    progress_pct: 37,
  },
  global_rank: 42,
  response_index: 1245,
  achievements: [],
  unlocked_count: 0,
  total_achievements: 10,
  recent_xp: [],
  stats: { total_sessions: 3, avg_score: 72.5 },
  member_since: "2026-01-01T00:00:00",
};

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <UserProfilePage />
    </QueryClientProvider>,
  );
}

describe("UserProfilePage — Response Index", () => {
  beforeEach(() => {
    vi.mocked(axiosInstance.get).mockImplementation((url: string) => {
      if (url === "/profile/me") return Promise.resolve({ data: PROFILE });
      if (url === "/certs/mine") return Promise.resolve({ data: { certs: [], newly_issued: [] } });
      if (url === "/auth/mfa/status") return Promise.resolve({ data: { mfa_enabled: false } });
      if (url === "/users/me/public-profile") {
        return Promise.resolve({
          data: { public_display_handle: null, arena_profile_public: false },
        });
      }
      return Promise.reject(new Error(`unexpected GET ${url}`));
    });
    vi.mocked(api.get).mockResolvedValue({
      technique_mastery: {},
      nist_mastery: {},
      weakest_techniques: [],
    });
  });

  it("displays the player's response_index from profile/me", async () => {
    renderPage();
    expect(await screen.findByTestId("profile-response-index")).toHaveTextContent("1245");
  });
});
