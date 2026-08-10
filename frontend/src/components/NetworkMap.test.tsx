import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import NetworkMap from "./NetworkMap";

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
    // TEMP: verifying the CI gate blocks on a frontend test failure —
    // reverted in the very next commit.
    expect(true).toBe(false);
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
});
