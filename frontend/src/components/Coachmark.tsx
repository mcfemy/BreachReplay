import { useLayoutEffect, useState } from "react";

interface CoachmarkProps {
  /** The element this coachmark points at — measured via getBoundingClientRect, not a layout child of it. */
  anchorEl: HTMLElement | null;
  /** What the anchored control does. */
  text: string;
  /** How to interact with it (tap-host / type-value / pick-party / no-target) — called out separately from `text` since it's a distinct fact, not prose. */
  targetingHint?: string;
  onDismiss: () => void;
}

/**
 * Reusable anchored tooltip/coachmark. Positions itself above a given DOM
 * element using a fixed-position bubble measured off that element's own
 * getBoundingClientRect — not a CSS-relative child of it, since the anchor
 * (a verb chip) sits inside a `overflow-auto`/`shrink-0` layout where a
 * relatively-positioned child could get clipped or pushed around. Renders
 * nothing until the anchor is measurable. Never places an invisible overlay
 * over the rest of the screen — only the bubble itself captures clicks — so
 * the console underneath stays fully interactive while this is showing.
 */
export default function Coachmark({ anchorEl, text, targetingHint, onDismiss }: CoachmarkProps) {
  const [position, setPosition] = useState<{ left: number; top: number } | null>(null);

  useLayoutEffect(() => {
    if (!anchorEl) {
      setPosition(null);
      return;
    }
    function measure() {
      const rect = anchorEl!.getBoundingClientRect();
      setPosition({ left: rect.left + rect.width / 2, top: rect.top });
    }
    measure();
    window.addEventListener("resize", measure);
    window.addEventListener("scroll", measure, true);
    return () => {
      window.removeEventListener("resize", measure);
      window.removeEventListener("scroll", measure, true);
    };
  }, [anchorEl]);

  if (!anchorEl || !position) return null;

  // Clamped so a chip near either screen edge never pushes the bubble
  // itself off-screen — the arrow below stays visually centered on the
  // bubble rather than tracking the unclamped anchor exactly, a deliberate
  // small imprecision over a fixed-width bubble near the viewport edge.
  const clampedLeft = Math.min(Math.max(position.left, 96), window.innerWidth - 96);

  return (
    <div
      role="tooltip"
      className="fixed z-50 pointer-events-auto"
      style={{ left: clampedLeft, top: position.top - 10, transform: "translate(-50%, -100%)" }}
    >
      <div className="max-w-[210px] bg-panel border border-phosphor/50 rounded-lg px-3 py-2.5 shadow-2xl">
        <p className="text-xs text-white leading-snug">{text}</p>
        {targetingHint && (
          <p className="text-[10px] font-term text-phosphor uppercase tracking-widest mt-1.5 leading-snug">
            {targetingHint}
          </p>
        )}
        <button
          onClick={onDismiss}
          className="mt-2 text-[10px] font-bold text-dim uppercase tracking-widest active:scale-95"
        >
          Got it
        </button>
      </div>
      <div className="w-2.5 h-2.5 bg-panel border-r border-b border-phosphor/50 rotate-45 mx-auto -mt-[5px]" />
    </div>
  );
}
