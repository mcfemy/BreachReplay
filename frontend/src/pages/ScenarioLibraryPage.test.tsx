import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import ScenarioLibraryPage from "./ScenarioLibraryPage";
import { api, axiosInstance } from "../lib/api";

// Covers both this page's own `api.get("/scenarios?...")` fetch and the
// nested FreshIncidentTicker's `axiosInstance.get("/scenarios/recent")` —
// both resolve to the same "../lib/api" module.
vi.mock("../lib/api", () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  axiosInstance: { get: vi.fn(), post: vi.fn() },
  API_BASE: "http://test.invalid",
}));

const SCENARIOS = [
  {
    id: "scn-1",
    title: "Colonial Pipeline",
    industry_vertical: "energy",
    difficulty: "practitioner",
    estimated_minutes: 10,
    source_type: "cisa",
    source_reference: null,
    mitre_techniques: ["T1078"],
    regulatory_frameworks: null,
    play_count: 120,
    avg_score: 72,
  },
];

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <ScenarioLibraryPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("ScenarioLibraryPage", () => {
  beforeEach(() => {
    vi.mocked(api.get).mockResolvedValue(SCENARIOS);
    vi.mocked(axiosInstance.get).mockResolvedValue({ data: [] }); // /scenarios/recent
  });

  it("loads and renders the scenario list", async () => {
    renderPage();
    expect(await screen.findByText("Colonial Pipeline")).toBeInTheDocument();
  });

  it("launches a scenario via POST /action-runs on click", async () => {
    vi.mocked(api.post).mockResolvedValue({ run_id: "run-1" });
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByText("Launch Simulation →"));

    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith("/action-runs", { scenario_id: "scn-1" }),
    );
  });
});
