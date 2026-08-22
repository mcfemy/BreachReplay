import { colors, fonts, nodeStateColor, type NodeState } from "../theme/tokens";
import { prefersReducedMotion } from "../lib/typewriter";
import { useEffect, useRef, useState } from "react";

/**
 * The signature visual element (BREACHREPLAY_GAME_OVERHAUL_SPEC.md section
 * 1): a live network topology map where compromise bleeds from node to
 * node in `bleed` red and containment snaps nodes to `contain` green. Pure
 * SVG — no dependencies, no video/canvas — so it's cheap enough to reuse
 * across the Phase 1 teaser, Daily Breach, scenarios, and share cards
 * (Phases 2–4).
 *
 * Juice (spec §1 motion rules) is derived from nodeStates transitions —
 * no extra props, no backend events. Skipped under prefers-reduced-motion.
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
export const CONTAIN_FLASH_MS = 150;
export const NODE_SHAKE_MS = 120;
export const INFECT_PULSE_MS = 700;

function isInfected(state: NodeState | undefined): boolean {
  return state === "pulsing" || state === "compromised";
}

interface SpreadPulse {
  key: string;
  source: NetworkMapNode;
  target: NetworkMapNode;
}

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
  const reduceMotion = prefersReducedMotion();

  const primedRef = useRef(false);
  const prevStatesRef = useRef<Record<string, NodeState>>(nodeStates);
  const [flashingIds, setFlashingIds] = useState<Set<string>>(() => new Set());
  const [shakingIds, setShakingIds] = useState<Set<string>>(() => new Set());
  const [spreads, setSpreads] = useState<SpreadPulse[]>([]);

  useEffect(() => {
    if (reduceMotion) {
      primedRef.current = true;
      prevStatesRef.current = nodeStates;
      setFlashingIds(new Set());
      setShakingIds(new Set());
      setSpreads([]);
      return;
    }
    if (!primedRef.current) {
      primedRef.current = true;
      prevStatesRef.current = nodeStates;
      return;
    }

    const prev = prevStatesRef.current;
    const newFlash: string[] = [];
    const newShake: string[] = [];
    const newSpreads: SpreadPulse[] = [];

    for (const [id, state] of Object.entries(nodeStates)) {
      const before = prev[id];
      if (state === "contained" && before && before !== "contained") {
        newFlash.push(id);
      }
      if (state === "compromised" && before && before !== "compromised") {
        newShake.push(id);
      }
      if (isInfected(state) && before && before !== "unknown" && !isInfected(before) && before !== "contained") {
        const origin = nodeById[id];
        if (!origin) continue;
        edges.forEach((edge, i) => {
          const otherId = edge.source === id ? edge.target : edge.target === id ? edge.source : null;
          if (!otherId) return;
          const other = nodeById[otherId];
          if (!other) return;
          newSpreads.push({
            key: `${id}-${otherId}-${i}-${state}`,
            source: origin,
            target: other,
          });
        });
      }
    }

    prevStatesRef.current = nodeStates;

    const timers: number[] = [];
    if (newFlash.length) {
      setFlashingIds((cur) => {
        const next = new Set(cur);
        newFlash.forEach((id) => next.add(id));
        return next;
      });
      timers.push(
        window.setTimeout(() => {
          setFlashingIds((cur) => {
            const next = new Set(cur);
            newFlash.forEach((id) => next.delete(id));
            return next;
          });
        }, CONTAIN_FLASH_MS),
      );
    }
    if (newShake.length) {
      setShakingIds((cur) => {
        const next = new Set(cur);
        newShake.forEach((id) => next.add(id));
        return next;
      });
      timers.push(
        window.setTimeout(() => {
          setShakingIds((cur) => {
            const next = new Set(cur);
            newShake.forEach((id) => next.delete(id));
            return next;
          });
        }, NODE_SHAKE_MS),
      );
    }
    if (newSpreads.length) {
      setSpreads((cur) => [...cur, ...newSpreads]);
      timers.push(
        window.setTimeout(() => {
          const keys = new Set(newSpreads.map((s) => s.key));
          setSpreads((cur) => cur.filter((s) => !keys.has(s.key)));
        }, INFECT_PULSE_MS),
      );
    }
    return () => timers.forEach(clearTimeout);
    // nodeById is rebuilt each render from `nodes`; edges/nodeStates are the signal.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nodeStates, edges, reduceMotion]);

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
        {spreads.map((pulse) => (
          <line
            key={pulse.key}
            data-spreading="true"
            data-from={pulse.source.id}
            data-to={pulse.target.id}
            x1={pulse.source.x}
            y1={pulse.source.y}
            x2={pulse.target.x}
            y2={pulse.target.y}
            pathLength={100}
            stroke={colors.bleed}
            strokeWidth={2.5}
            strokeLinecap="round"
            fill="none"
            strokeDasharray="14 86"
            className="animate-infect-pulse pointer-events-none"
          />
        ))}
      </g>
      <g>
        {nodes.map((node) => {
          const state: NodeState = nodeStates[node.id] ?? "clean";
          const color = nodeStateColor[state];
          const isClickable = clickable.has(node.id);
          const isUnknown = state === "unknown";
          const isPulsing = state === "pulsing" && !reduceMotion;
          const label = isUnknown ? "Unknown host" : node.label;
          const flashing = flashingIds.has(node.id);
          const shaking = shakingIds.has(node.id);

          return (
            <g
              key={node.id}
              data-testid={`node-${node.id}`}
              data-contain-flash={flashing ? "true" : undefined}
              data-shake={shaking ? "true" : undefined}
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
              <g className={shaking ? "animate-node-shake" : undefined}>
                {isPulsing && <circle r={16} fill={color} opacity={0.35} className="animate-ping" />}
                {flashing && (
                  <circle
                    r={14}
                    fill="none"
                    stroke={colors.contain}
                    strokeWidth={2.5}
                    className="animate-contain-ring origin-center"
                    style={{ transformBox: "fill-box", transformOrigin: "center" }}
                  />
                )}
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
            </g>
          );
        })}
      </g>
    </svg>
  );
}
