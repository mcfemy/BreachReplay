import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import AppShell from "./AppShell";
import { useAuthStore } from "../store/auth";

function renderShell() {
  return render(
    <MemoryRouter initialEntries={["/scenarios"]}>
      <Routes>
        <Route element={<AppShell />}>
          <Route path="/scenarios" element={<div>Page content</div>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

describe("AppShell", () => {
  beforeEach(() => {
    localStorage.setItem("br_onboarded", "1"); // suppress OnboardingModal overlay
    useAuthStore.setState({
      user: {
        id: "u1",
        email: "responder@example.com",
        full_name: "Test Responder",
        role: "user",
        organization_id: null,
        has_seen_console_intro: true,
        has_acknowledged_racing_notice: true,
        seen_verb_coachmarks: [],
      },
    });
  });

  it("renders the nav and the routed page content", () => {
    renderShell();
    expect(screen.getByText("Scenarios")).toBeInTheDocument();
    expect(screen.getByText("Daily Breach")).toBeInTheDocument();
    expect(screen.getByText("Arena")).toBeInTheDocument();
    expect(screen.getByText("Page content")).toBeInTheDocument();
  });

  it("opens the mobile nav drawer on hamburger tap", async () => {
    const user = userEvent.setup();
    const { container } = renderShell();
    expect(container.querySelector(".bg-black\\/60")).not.toBeInTheDocument();

    await user.click(screen.getByLabelText("Open menu"));
    expect(container.querySelector(".bg-black\\/60")).toBeInTheDocument();

    await user.click(screen.getByLabelText("Close menu"));
    expect(container.querySelector(".bg-black\\/60")).not.toBeInTheDocument();
  });

  it("sound toggle starts muted and persists on to localStorage", async () => {
    const user = userEvent.setup();
    renderShell();
    const toggles = screen.getAllByLabelText("Enable sound");
    expect(toggles.length).toBe(2);
    expect(localStorage.getItem("br_sound_enabled")).toBeNull();

    await user.click(toggles[0]);
    expect(localStorage.getItem("br_sound_enabled")).toBe("1");
    expect(screen.getAllByLabelText("Mute sound")).toHaveLength(2);
  });

  it("restores an enabled sound toggle from localStorage without autoplaying", () => {
    const ctor = vi.fn();
    vi.stubGlobal("AudioContext", ctor);
    localStorage.setItem("br_sound_enabled", "1");
    localStorage.setItem("br_onboarded", "1");
    renderShell();
    expect(screen.getAllByLabelText("Mute sound")).toHaveLength(2);
    expect(ctor).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
  });
});
