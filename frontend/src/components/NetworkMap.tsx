import { colors, fonts, nodeStateColor, type NodeState } from "../theme/tokens";

/**
 * The signature visual element (BREACHREPLAY_GAME_OVERHAUL_SPEC.md section
 * 1): a live network topology map where compromise bleeds from node to
 * node in `bleed` red and containment snaps nodes to `contain` green. Pure
 * SVG — no dependencies, no video/canvas — so it's cheap enough to reuse
 * across the Phase 1 teaser, Daily Breach, scenarios, and share cards
 * (Phases 2–4).
 */

export interface NetworkMapNode {
  id: string;
  label: string;
  x: number;
  y: number;
}

export interface NetworkMapEdge {
  source: string;
  target: string;
}

interface NetworkMapProps {
  nodes: NetworkMapNode[];
  edges: NetworkMapEdge[];
  nodeStates: Record<string, NodeState>;
  /** Node ids that respond to clicks — the map is the input, not a button list. */
  clickableNodeIds?: string[];
  onNodeClick?: (nodeId: string) => void;
  className?: string;
}

const VIEWBOX_PADDING = 50;

export default function NetworkMap({
  nodes,
  edges,
  nodeStates,
  clickableNodeIds,
  onNodeClick,
  className,
}: NetworkMapProps) {
  const maxX = Math.max(...nodes.map((n) => n.x), 0) + VIEWBOX_PADDING;
  const maxY = Math.max(...nodes.map((n) => n.y), 0) + VIEWBOX_PADDING;
  const nodeById: Record<string, NetworkMapNode> = {};
  for (const n of nodes) nodeById[n.id] = n;
  const clickable = new Set(clickableNodeIds ?? []);
  const reduceMotion =
    typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

  return (
    <svg
      viewBox={`0 0 ${maxX} ${maxY}`}
      className={className}
      role="img"
      aria-label="Network topology map"
    >
      <g>
        {edges.map((edge, i) => {
          const s = nodeById[edge.source];
          const t = nodeById[edge.target];
          if (!s || !t) return null;
          return (
            <line
              key={`${edge.source}-${edge.target}-${i}`}
              x1={s.x}
              y1={s.y}
              x2={t.x}
              y2={t.y}
              stroke={colors.dim}
              strokeOpacity={0.35}
              strokeWidth={1.5}
            />
          );
        })}
      </g>
      <g>
        {nodes.map((node) => {
          const state: NodeState = nodeStates[node.id] ?? "clean";
          const color = nodeStateColor[state];
          const isClickable = clickable.has(node.id);
          const isUnknown = state === "unknown";
          const isPulsing = state === "pulsing" && !reduceMotion;
          const label = isUnknown ? "Unknown host" : node.label;

          return (
            <g
              key={node.id}
              transform={`translate(${node.x}, ${node.y})`}
              onClick={isClickable ? () => onNodeClick?.(node.id) : undefined}
              onKeyDown={
                isClickable
                  ? (e) => {
                      if (e.key === "Enter" || e.key === " ") onNodeClick?.(node.id);
                    }
                  : undefined
              }
              role={isClickable ? "button" : undefined}
              tabIndex={isClickable ? 0 : undefined}
              aria-label={isClickable ? `Isolate ${node.label}` : label}
              style={{ cursor: isClickable ? "pointer" : "default", outline: "none" }}
            >
              {isPulsing && <circle r={16} fill={color} opacity={0.35} className="animate-ping" />}
              <circle
                r={11}
                fill={isUnknown ? colors.void : state === "clean" ? colors.panel : color}
                fillOpacity={isUnknown || state === "clean" ? 1 : 0.25}
                stroke={color}
                strokeWidth={2}
                strokeDasharray={isUnknown ? "3 3" : undefined}
                className={isClickable ? "transition-opacity hover:opacity-70" : undefined}
              />
              {!isUnknown && node.label ? (
                <text
                  y={26}
                  textAnchor="middle"
                  fontFamily={fonts.mono}
                  fontSize={10}
                  fill={colors.dim}
                >
                  {node.label}
                </text>
              ) : null}
            </g>
          );
        })}
      </g>
    </svg>
  );
}
