import { describe, it, expect, beforeEach } from "vitest";
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
});
