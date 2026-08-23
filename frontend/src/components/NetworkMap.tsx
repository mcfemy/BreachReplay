import { colors, fonts, nodeStateColor, unknownNodeFill, type NodeState } from "../theme/tokens";
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
 *
 * Scan-reveal is a distinct "coming online" effect, not the infect-pulse.
 * Infect-pulse means the attacker is spreading along an edge the player
 * already sees; using it for unknown → known would paint a scan as an
 * infection event, and would skip the majority unknown → clean hosts.
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
/** Room below a node for the hostname label (`<text y={26}>`). */
const VIEWBOX_LABEL = 28;
export const CONTAIN_FLASH_MS = 150;
export const NODE_SHAKE_MS = 120;
export const INFECT_PULSE_MS = 700;
export const NODE_REVEAL_MS = 420;

function isInfected(state: NodeState | undefined): boolean {
  return state === "pulsing" || state === "compromised";
}

function edgeKey(edge: NetworkMapEdge, i: number): string {
  return `${edge.source}-${edge.target}-${i}`;
}

function viewBoxFor(nodes: NetworkMapNode[]): string {
  if (nodes.length === 0) return `0 0 ${VIEWBOX_PADDING * 2} ${VIEWBOX_PADDING * 2}`;
  const xs = nodes.map((n) => n.x);
  const ys = nodes.map((n) => n.y);
  const minX = Math.min(...xs) - VIEWBOX_PADDING;
  const minY = Math.min(...ys) - VIEWBOX_PADDING;
  const maxX = Math.max(...xs) + VIEWBOX_PADDING;
  const maxY = Math.max(...ys) + VIEWBOX_PADDING + VIEWBOX_LABEL;
  return `${minX} ${minY} ${Math.max(maxX - minX, 1)} ${Math.max(maxY - minY, 1)}`;
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
  const nodeById: Record<string, NetworkMapNode> = {};
  for (const n of nodes) nodeById[n.id] = n;
  const clickable = new Set(clickableNodeIds ?? []);
  const reduceMotion = prefersReducedMotion();

  const primedRef = useRef(false);
  const prevStatesRef = useRef<Record<string, NodeState>>(nodeStates);
  const prevEdgeKeysRef = useRef<Set<string>>(new Set());
  const [flashingIds, setFlashingIds] = useState<Set<string>>(() => new Set());
  const [shakingIds, setShakingIds] = useState<Set<string>>(() => new Set());
  const [revealingIds, setRevealingIds] = useState<Set<string>>(() => new Set());
  const [revealingEdgeKeys, setRevealingEdgeKeys] = useState<Set<string>>(() => new Set());
  const [spreads, setSpreads] = useState<SpreadPulse[]>([]);

  useEffect(() => {
    if (reduceMotion) {
      primedRef.current = true;
      prevStatesRef.current = nodeStates;
      prevEdgeKeysRef.current = new Set(edges.map(edgeKey));
      setFlashingIds(new Set());
      setShakingIds(new Set());
      setRevealingIds(new Set());
      setRevealingEdgeKeys(new Set());
      setSpreads([]);
      return;
    }
    if (!primedRef.current) {
      primedRef.current = true;
      prevStatesRef.current = nodeStates;
      prevEdgeKeysRef.current = new Set(edges.map(edgeKey));
      return;
    }

    const prev = prevStatesRef.current;
    const prevEdgeKeys = prevEdgeKeysRef.current;
    const newFlash: string[] = [];
    const newShake: string[] = [];
    const newReveal: string[] = [];
    const newSpreads: SpreadPulse[] = [];
    const newEdgeKeys: string[] = [];

    for (const [id, state] of Object.entries(nodeStates)) {
      const before = prev[id];
      if (state === "contained" && before && before !== "contained") {
        newFlash.push(id);
      }
      if (state === "compromised" && before && before !== "compromised") {
        newShake.push(id);
      }
      // Fog-of-war lift: unknown → any known state. Distinct from infect-pulse
      // (bleed along edges = live spread the player already has topology for).
      if (before === "unknown" && state !== "unknown") {
        newReveal.push(id);
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

    edges.forEach((edge, i) => {
      const key = edgeKey(edge, i);
      if (!prevEdgeKeys.has(key)) newEdgeKeys.push(key);
    });

    prevStatesRef.current = nodeStates;
    prevEdgeKeysRef.current = new Set(edges.map(edgeKey));

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
    if (newReveal.length) {
      setRevealingIds((cur) => {
        const next = new Set(cur);
        newReveal.forEach((id) => next.add(id));
        return next;
      });
      timers.push(
        window.setTimeout(() => {
          setRevealingIds((cur) => {
            const next = new Set(cur);
            newReveal.forEach((id) => next.delete(id));
            return next;
          });
        }, NODE_REVEAL_MS),
      );
    }
    if (newEdgeKeys.length) {
      setRevealingEdgeKeys((cur) => {
        const next = new Set(cur);
        newEdgeKeys.forEach((k) => next.add(k));
        return next;
      });
      timers.push(
        window.setTimeout(() => {
          setRevealingEdgeKeys((cur) => {
            const next = new Set(cur);
            newEdgeKeys.forEach((k) => next.delete(k));
            return next;
          });
        }, NODE_REVEAL_MS),
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
      viewBox={viewBoxFor(nodes)}
      className={className}
      role="img"
      aria-label="Network topology map"
    >
      <g>
        {edges.map((edge, i) => {
          const s = nodeById[edge.source];
          const t = nodeById[edge.target];
          if (!s || !t) return null;
          const key = edgeKey(edge, i);
          const revealing = revealingEdgeKeys.has(key);
          return (
            <line
              key={key}
              data-edge-reveal={revealing ? "true" : undefined}
              x1={s.x}
              y1={s.y}
              x2={t.x}
              y2={t.y}
              stroke={colors.dim}
              strokeOpacity={0.35}
              strokeWidth={1.5}
              className={revealing ? "animate-edge-in" : undefined}
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
          const revealing = revealingIds.has(node.id);

          return (
            <g
              key={node.id}
              data-testid={`node-${node.id}`}
              data-contain-flash={flashing ? "true" : undefined}
              data-shake={shaking ? "true" : undefined}
              data-revealing={revealing ? "true" : undefined}
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
              <g className={revealing ? "animate-node-reveal" : undefined}>
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
                  {revealing && (
                    <circle
                      r={14}
                      fill="none"
                      stroke={colors.phosphor}
                      strokeWidth={1.5}
                      className="animate-reveal-ring origin-center"
                      style={{ transformBox: "fill-box", transformOrigin: "center" }}
                    />
                  )}
                  <circle
                    r={11}
                    fill={isUnknown ? unknownNodeFill : state === "clean" ? colors.panel : color}
                    fillOpacity={isUnknown || state === "clean" ? 1 : 0.25}
                    stroke={color}
                    strokeWidth={isUnknown ? 2.25 : 2}
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
            </g>
          );
        })}
      </g>
    </svg>
  );
}
