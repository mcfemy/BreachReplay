/**
 * Design tokens — BREACHREPLAY_GAME_OVERHAUL_SPEC.md section 1 ("Visual
 * direction"). Ground truth for the palette/type used by the Phase 1
 * teaser and every surface that adopts the new look as it's touched
 * (deliberately NOT a big-bang restyle of the whole app — see the spec).
 */

export const colors = {
  void: "#0B0F14", // page background (blue-black, not pure black)
  panel: "#121A23", // cards, consoles
  phosphor: "#FFB454", // primary accent: amber CRT phosphor — buttons, active states, score
  bleed: "#E5484D", // compromise, spreading infection, attacker clock
  contain: "#3DD68C", // contained hosts, correct calls
  dim: "#8A97A5", // secondary text, timestamps
} as const;

export const fonts = {
  display: "'Space Grotesk', sans-serif", // headlines, scores, the dare on the landing page
  mono: "'IBM Plex Mono', monospace", // terminal/data: alert feed, action console, logs, timestamps
  body: "'Inter', sans-serif", // everything else
} as const;

/** Node states for NetworkMap — see frontend/src/components/NetworkMap.tsx. */
export type NodeState = "clean" | "pulsing" | "compromised" | "contained";

export const nodeStateColor: Record<NodeState, string> = {
  clean: colors.dim,
  pulsing: colors.bleed,
  compromised: colors.bleed,
  contained: colors.contain,
};
