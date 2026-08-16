import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import DossierPage from "./DossierPage";
import { api } from "../lib/api";

vi.mock("../lib/api", () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  axiosInstance: { get: vi.fn(), post: vi.fn() },
  API_BASE: "http://test.invalid",
}));

const DOSSIER = {
  techniques: {
    T1078: {
      technique_id: "T1078",
      name: "Valid Accounts",
      tactic: "Initial Access",
      description: "Adversaries authenticate using legitimate, stolen credentials.",
      incident_narrative: "DarkSide got in through a single legacy VPN account.",
      source_reference: "CISA AA21-131A; MITRE ATT&CK T1078",
      scenarios: ["colonial_pipeline"],
      encountered: true,
      encounter_count: 3,
      first_encountered_at: "2026-01-01T00:00:00Z",
      last_encountered_at: "2026-01-02T00:00:00Z",
    },
    T1003: {
      technique_id: "T1003",
      name: "OS Credential Dumping",
      tactic: "Credential Access",
      description: "Adversaries extract stored credentials directly from memory or disk.",
      incident_narrative: "",
      source_reference: "",
      scenarios: ["colonial_pipeline"],
      encountered: false,
      encounter_count: 0,
      first_encountered_at: null,
      last_encountered_at: null,
    },
  },
  total_techniques: 2,
  encountered_count: 1,
};

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <DossierPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("DossierPage", () => {
  beforeEach(() => {
    vi.mocked(api.get).mockResolvedValue(DOSSIER);
  });

  it("fetches from /dossier/me and renders the fill state", async () => {
    renderPage();
    expect(await screen.findByText("1/2 entries")).toBeInTheDocument();
    expect(api.get).toHaveBeenCalledWith("/dossier/me");
  });

  it("shows full content for an encountered technique", async () => {
    renderPage();
    expect(await screen.findByText("Valid Accounts")).toBeInTheDocument();
    expect(screen.getByText("Adversaries authenticate using legitimate, stolen credentials.")).toBeInTheDocument();
    expect(screen.getByText("DarkSide got in through a single legacy VPN account.")).toBeInTheDocument();
    expect(screen.getByText("Encountered 3×")).toBeInTheDocument();
  });

  it("shows a locked placeholder for an unencountered technique, with no description leaked", async () => {
    renderPage();
    expect(await screen.findByText("OS Credential Dumping")).toBeInTheDocument();
    expect(screen.queryByText("Adversaries extract stored credentials directly from memory or disk.")).not.toBeInTheDocument();
  });

  it("groups techniques under their tactic heading", async () => {
    renderPage();
    expect(await screen.findByText("Initial Access")).toBeInTheDocument();
    expect(screen.getByText("Credential Access")).toBeInTheDocument();
  });

  it("shows an error state when the fetch fails", async () => {
    vi.mocked(api.get).mockRejectedValue(new Error("network error"));
    renderPage();
    expect(await screen.findByText("Could not load your dossier.")).toBeInTheDocument();
  });
});
