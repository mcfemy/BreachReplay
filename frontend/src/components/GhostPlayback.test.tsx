import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen, act } from "@testing-library/react";
import GhostPlayback from "./GhostPlayback";
import { sampleGhostDto } from "../lib/ghostPlayback.fixture";
import { NODE_REVEAL_MS } from "./NetworkMap";

function stubReduceMotion(reduce: boolean) {
  window.matchMedia = ((query: string) =>
    ({
      matches: query.includes("prefers-reduced-motion") ? reduce : false,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }) as unknown as MediaQueryList);
}

describe("GhostPlayback", () => {
  beforeEach(() => {
    stubReduceMotion(false);
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders the frame matching the live elapsed clock", () => {
    const ghost = sampleGhostDto();
    const { rerender } = render(<GhostPlayback ghost={ghost} elapsedSeconds={10} />);

    // Fixture t=0 frame: both hosts unknown → two "Unknown host" labels
    expect(screen.getAllByLabelText("Unknown host")).toHaveLength(2);
    expect(screen.queryByText("CORP-WKS-22")).not.toBeInTheDocument();
    expect(screen.getByTestId("ghost-playback")).toHaveAttribute("data-elapsed", "10");

    rerender(<GhostPlayback ghost={ghost} elapsedSeconds={45} />);
    expect(screen.getByText("CORP-WKS-22")).toBeInTheDocument();
    expect(screen.getByText("CORP-DC-01")).toBeInTheDocument();
  });

  it("advances the ghost feed on the same elapsed clock without its own timer", () => {
    const ghost = sampleGhostDto();
    const { rerender } = render(<GhostPlayback ghost={ghost} elapsedSeconds={0} />);
    expect(screen.queryByText(/Ghost: Network scan/)).not.toBeInTheDocument();

    rerender(<GhostPlayback ghost={ghost} elapsedSeconds={45} />);
    act(() => {
      vi.runAllTimers();
    });
    expect(screen.getByText(/Ghost: Network scan complete/)).toBeInTheDocument();
    expect(screen.queryByText(/Ghost: Host isolated/)).not.toBeInTheDocument();

    rerender(<GhostPlayback ghost={ghost} elapsedSeconds={120} />);
    act(() => {
      vi.runAllTimers();
    });
    expect(screen.getByText(/Ghost: Host isolated/)).toBeInTheDocument();
  });

  it("holds the final map when live elapsed exceeds the ghost duration", () => {
    const ghost = sampleGhostDto();
    render(<GhostPlayback ghost={ghost} elapsedSeconds={500} />);
    expect(screen.getByText("CORP-WKS-22")).toBeInTheDocument();
    expect(screen.getByTestId("node-h1")).toBeInTheDocument();
  });

  it("skips reveal juice under prefers-reduced-motion (same as NetworkMap)", () => {
    stubReduceMotion(true);
    const ghost = sampleGhostDto();
    const { rerender } = render(<GhostPlayback ghost={ghost} elapsedSeconds={0} />);
    rerender(<GhostPlayback ghost={ghost} elapsedSeconds={45} />);
    act(() => {
      vi.advanceTimersByTime(NODE_REVEAL_MS);
    });
    expect(screen.getByTestId("node-h1")).not.toHaveAttribute("data-revealing");
    expect(screen.getByText(/Ghost: Network scan complete/)).toBeInTheDocument();
  });
});
