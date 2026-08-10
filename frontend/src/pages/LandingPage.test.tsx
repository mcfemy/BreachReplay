import { describe, it, expect, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import LandingPage from "./LandingPage";
import { useAuthStore } from "../store/auth";

describe("LandingPage", () => {
  beforeEach(() => {
    // No token — otherwise the page's own useEffect redirects to /scenarios.
    useAuthStore.setState({ token: null, user: null });
  });

  it("renders the marketing hero and nav without crashing", () => {
    render(
      <MemoryRouter>
        <LandingPage />
      </MemoryRouter>,
    );
    expect(screen.getByText(/should be a simulation\./)).toBeInTheDocument();
    expect(screen.getByText("START FREE — NO CARD NEEDED")).toBeInTheDocument();
    // LandingPageMarketing renders its own "Sign in" link further down the
    // page too — this only needs to confirm at least one nav link rendered.
    expect(screen.getAllByText("Sign in").length).toBeGreaterThan(0);
  });
});
