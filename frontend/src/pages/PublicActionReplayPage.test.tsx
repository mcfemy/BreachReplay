import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import PublicActionReplayPage from "./PublicActionReplayPage";
import { axiosInstance } from "../lib/api";

vi.mock("../lib/api", () => ({
  axiosInstance: { get: vi.fn() },
  API_BASE: "http://test.invalid",
}));

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
  techniques_encountered: [
    {
      technique_id: "T1078",
      name: "Valid Accounts",
      description: "Adversaries authenticate using legitimate, stolen credentials.",
    },
  ],
};

function renderPage(token = "tok123") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[`/r/${token}`]}>
        <Routes>
          <Route path="/r/:shareToken" element={<PublicActionReplayPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("PublicActionReplayPage", () => {
  beforeEach(() => {
    vi.mocked(axiosInstance.get).mockReset();
  });

  it("renders the redacted replay: outcome, score, map, verbs, techniques — no targets", async () => {
    vi.mocked(axiosInstance.get).mockResolvedValue({ data: REPLAY });
    renderPage();

    expect(await screen.findByText("Colonial Pipeline Replay")).toBeInTheDocument();
    expect(screen.getByText("CONTAINED")).toBeInTheDocument();
    expect(screen.getByText("800")).toBeInTheDocument();
    expect(screen.getByText("Responder")).toBeInTheDocument();
    expect(screen.getByText("scan network")).toBeInTheDocument();
    expect(screen.getByText("isolate")).toBeInTheDocument();
    expect(screen.getByText("Valid Accounts")).toBeInTheDocument();
    expect(screen.getByText("CORP-WKS-22")).toBeInTheDocument();

    expect(axiosInstance.get).toHaveBeenCalledWith("/action-runs/public/replay/tok123");
    const ogImage = document.head.querySelector('meta[property="og:image"]');
    expect(ogImage?.getAttribute("content")).toBe(
      "http://test.invalid/action-runs/public/replay/tok123/card.png",
    );
    expect(document.head.querySelector('meta[name="twitter:card"]')?.getAttribute("content")).toBe(
      "summary_large_image",
    );
    // Targets never belong on this page — the DTO doesn't have them, and
    // the timeline renderer must not invent a slot for them.
    expect(screen.queryByText(/203\.0\.113/)).not.toBeInTheDocument();
    expect(screen.queryByText(/incident_narrative/i)).not.toBeInTheDocument();
  });

  it("shows the Arena-parallel not-found state for a 404 token", async () => {
    vi.mocked(axiosInstance.get).mockRejectedValue(new Error("Replay not found"));
    renderPage("missing");
    expect(await screen.findByText("Replay Not Found")).toBeInTheDocument();
    expect(screen.getByText(/doesn't exist or hasn't finished yet/i)).toBeInTheDocument();
  });
});
