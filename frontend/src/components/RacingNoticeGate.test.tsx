import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { useEffect } from "react";
import { RacingNoticeDialog, useRacingNotice } from "./RacingNoticeGate";
import { useAuthStore } from "../store/auth";

vi.mock("../lib/api", () => ({
  axiosInstance: { patch: vi.fn() },
  api: { patch: vi.fn() },
  API_BASE: "http://test.invalid",
}));

import { axiosInstance } from "../lib/api";

function Harness() {
  const { ensureAcknowledged, dialog } = useRacingNotice();
  useEffect(() => {
    (window as unknown as { __ensure: typeof ensureAcknowledged }).__ensure = ensureAcknowledged;
  }, [ensureAcknowledged]);
  return (
    <>
      <button type="button" onClick={() => void ensureAcknowledged()}>
        start
      </button>
      {dialog}
    </>
  );
}

describe("RacingNoticeDialog", () => {
  it("renders title and actions when open", () => {
    render(
      <MemoryRouter>
        <RacingNoticeDialog open onConfirm={() => {}} onCancel={() => {}} />
      </MemoryRouter>,
    );
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText(/Racing & sharing/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Got it/i })).toBeInTheDocument();
  });
});

describe("useRacingNotice", () => {
  beforeEach(() => {
    vi.mocked(axiosInstance.patch).mockReset();
    useAuthStore.setState({
      user: {
        id: "u1",
        email: "u@example.com",
        full_name: "User",
        role: "analyst",
        organization_id: null,
        has_seen_console_intro: true,
        seen_verb_coachmarks: [],
        has_acknowledged_racing_notice: false,
      },
      token: "tok",
      refreshToken: null,
    });
  });

  it("shows notice once, then persists acknowledgment and skips on second call", async () => {
    vi.mocked(axiosInstance.patch).mockResolvedValue({
      data: { has_acknowledged_racing_notice: true },
    });

    render(
      <MemoryRouter>
        <Harness />
      </MemoryRouter>,
    );

    await userEvent.click(screen.getByRole("button", { name: /start/i }));
    expect(await screen.findByRole("dialog")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /Got it/i }));

    await waitFor(() => {
      expect(axiosInstance.patch).toHaveBeenCalledWith("/auth/me", {
        has_acknowledged_racing_notice: true,
      });
    });

    useAuthStore.setState((s) => ({
      user: s.user ? { ...s.user, has_acknowledged_racing_notice: true } : s.user,
    }));

    await userEvent.click(screen.getByRole("button", { name: /start/i }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("cancel returns false without patching", async () => {
    render(
      <MemoryRouter>
        <Harness />
      </MemoryRouter>,
    );

    await userEvent.click(screen.getByRole("button", { name: /start/i }));
    await screen.findByRole("dialog");
    await userEvent.click(screen.getByRole("button", { name: /Cancel/i }));
    await waitFor(() => {
      expect(axiosInstance.patch).not.toHaveBeenCalled();
    });
  });
});
