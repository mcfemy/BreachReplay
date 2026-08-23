import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import NetworkMap, { CONTAIN_FLASH_MS, NODE_SHAKE_MS, NODE_REVEAL_MS } from "./NetworkMap";
import { colors, unknownNodeFill, nodeStateColor } from "../theme/tokens";

const nodes = [
  { id: "h1", label: "CORP-WKS-22", x: 80, y: 60 },
  { id: "h2", label: "CORP-DC-01", x: 230, y: 60 },
];
const edges = [{ source: "h1", target: "h2" }];
const nodeStates = { h1: "clean" as const, h2: "compromised" as const };

describe("NetworkMap", () => {
  it("renders every node's label without crashing", () => {
    render(
      <NetworkMap nodes={nodes} edges={edges} nodeStates={nodeStates} />,
    );
    expect(screen.getByText("CORP-WKS-22")).toBeInTheDocument();
    expect(screen.getByText("CORP-DC-01")).toBeInTheDocument();
  });

  it("fires onNodeClick only for clickable nodes", async () => {
    const user = userEvent.setup();
    const onNodeClick = vi.fn();
    render(
      <NetworkMap
        nodes={nodes}
        edges={edges}
        nodeStates={nodeStates}
        clickableNodeIds={["h2"]}
        onNodeClick={onNodeClick}
      />,
    );

    // h2 is clickable — role="button", aria-label "Isolate CORP-DC-01"
    await user.click(screen.getByRole("button", { name: "Isolate CORP-DC-01" }));
    expect(onNodeClick).toHaveBeenCalledWith("h2");

    // h1 isn't in clickableNodeIds — no button role at all
    expect(screen.queryByRole("button", { name: /CORP-WKS-22/ })).not.toBeInTheDocument();
  });

  it("renders unknown NodeState as an unlabeled silhouette with a visible non-void fill", () => {
    render(
      <NetworkMap
        nodes={[{ id: "h1", label: "CORP-WKS-22", x: 80, y: 60 }]}
        edges={[]}
        nodeStates={{ h1: "unknown" }}
      />,
    );
    expect(screen.getByLabelText("Unknown host")).toBeInTheDocument();
    expect(screen.queryByText("CORP-WKS-22")).not.toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();

    const disc = screen.getByTestId("node-h1").querySelector("circle:last-of-type");
    expect(disc).toHaveAttribute("fill", unknownNodeFill);
    expect(disc).not.toHaveAttribute("fill", colors.void);
    expect(unknownNodeFill.toLowerCase()).not.toBe(colors.void.toLowerCase());
    expect(disc).toHaveAttribute("stroke", nodeStateColor.unknown);
    expect(disc).toHaveAttribute("stroke-dasharray", "3 3");
  });

  it("fits the viewBox to node bounds instead of originating at 0,0", () => {
    render(
      <NetworkMap
        nodes={nodes}
        edges={[]}
        nodeStates={{ h1: "unknown", h2: "unknown" }}
      />,
    );
    const svg = screen.getByRole("img", { name: "Network topology map" });
    const viewBox = svg.getAttribute("viewBox");
    expect(viewBox).toBeTruthy();
    const [minX, minY] = (viewBox as string).split(" ").map(Number);
    // Nodes sit at x=80,y=60 — a 0 0 origin would letterbox empty void
    // around the grid. The fitted box should start near those coords.
    expect(minX).toBeGreaterThan(0);
    expect(minY).toBeGreaterThanOrEqual(0);
    expect(minX).toBeLessThan(80);
  });
});

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

describe("NetworkMap juice", () => {
  beforeEach(() => {
    stubReduceMotion(false);
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("pulses along an edge when a clean node becomes pulsing", () => {
    const { rerender } = render(
      <NetworkMap nodes={nodes} edges={edges} nodeStates={{ h1: "clean", h2: "clean" }} />,
    );
    expect(document.querySelector("[data-spreading]")).not.toBeInTheDocument();

    rerender(
      <NetworkMap nodes={nodes} edges={edges} nodeStates={{ h1: "pulsing", h2: "clean" }} />,
    );
    const pulse = document.querySelector("[data-spreading]");
    expect(pulse).toBeInTheDocument();
    expect(pulse).toHaveAttribute("data-from", "h1");
    expect(pulse).toHaveAttribute("data-to", "h2");
  });

  it("plays a coming-online reveal when unknown becomes known, not an infect-pulse", () => {
    const { rerender } = render(
      <NetworkMap
        nodes={nodes}
        edges={[]}
        nodeStates={{ h1: "unknown", h2: "unknown" }}
      />,
    );
    expect(screen.getByTestId("node-h1")).not.toHaveAttribute("data-revealing");

    rerender(
      <NetworkMap
        nodes={nodes}
        edges={edges}
        nodeStates={{ h1: "pulsing", h2: "clean" }}
      />,
    );
    expect(screen.getByTestId("node-h1")).toHaveAttribute("data-revealing", "true");
    expect(screen.getByTestId("node-h2")).toHaveAttribute("data-revealing", "true");
    // Scan-reveal is not infection spreading — bleed-pulse stays off.
    expect(document.querySelector("[data-spreading]")).not.toBeInTheDocument();
    expect(document.querySelector("[data-edge-reveal]")).toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(NODE_REVEAL_MS);
    });
    expect(screen.getByTestId("node-h1")).not.toHaveAttribute("data-revealing");
    expect(screen.getByTestId("node-h2")).not.toHaveAttribute("data-revealing");
  });

  it("reveals unknown → compromised without treating it as a live infect-pulse", () => {
    const { rerender } = render(
      <NetworkMap nodes={nodes} edges={edges} nodeStates={{ h1: "unknown", h2: "unknown" }} />,
    );
    rerender(
      <NetworkMap nodes={nodes} edges={edges} nodeStates={{ h1: "compromised", h2: "clean" }} />,
    );
    expect(screen.getByTestId("node-h1")).toHaveAttribute("data-revealing", "true");
    expect(screen.getByTestId("node-h1")).toHaveAttribute("data-shake", "true");
    expect(document.querySelector("[data-spreading]")).not.toBeInTheDocument();
  });

  it("flashes a contain ring when a node becomes contained", () => {
    const { rerender } = render(
      <NetworkMap nodes={nodes} edges={edges} nodeStates={{ h1: "pulsing", h2: "clean" }} />,
    );
    rerender(
      <NetworkMap nodes={nodes} edges={edges} nodeStates={{ h1: "contained", h2: "clean" }} />,
    );
    expect(screen.getByTestId("node-h1")).toHaveAttribute("data-contain-flash", "true");
    act(() => {
      vi.advanceTimersByTime(CONTAIN_FLASH_MS);
    });
    expect(screen.getByTestId("node-h1")).not.toHaveAttribute("data-contain-flash");
  });

  it("shakes a node when it becomes fully compromised", () => {
    const { rerender } = render(
      <NetworkMap nodes={nodes} edges={edges} nodeStates={{ h1: "pulsing", h2: "clean" }} />,
    );
    rerender(
      <NetworkMap nodes={nodes} edges={edges} nodeStates={{ h1: "compromised", h2: "clean" }} />,
    );
    expect(screen.getByTestId("node-h1")).toHaveAttribute("data-shake", "true");
    act(() => {
      vi.advanceTimersByTime(NODE_SHAKE_MS);
    });
    expect(screen.getByTestId("node-h1")).not.toHaveAttribute("data-shake");
  });

  it("skips pulse, ring, shake, and reveal when prefers-reduced-motion is set", () => {
    stubReduceMotion(true);
    const { rerender } = render(
      <NetworkMap nodes={nodes} edges={edges} nodeStates={{ h1: "unknown", h2: "clean" }} />,
    );
    rerender(
      <NetworkMap
        nodes={nodes}
        edges={edges}
        nodeStates={{ h1: "pulsing", h2: "contained" }}
      />,
    );
    expect(document.querySelector("[data-spreading]")).not.toBeInTheDocument();
    expect(screen.getByTestId("node-h1")).not.toHaveAttribute("data-revealing");
    expect(screen.getByTestId("node-h1")).not.toHaveAttribute("data-shake");
    expect(screen.getByTestId("node-h2")).not.toHaveAttribute("data-contain-flash");
  });
});
