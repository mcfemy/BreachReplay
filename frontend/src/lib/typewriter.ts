import { useEffect, useRef, useState } from "react";

/**
 * Shared typewriter used by the Phase 1 teaser alert feed and the Action
 * Console incident feed (spec §1 / §5: ~20ms/char, staggered lines,
 * skipped entirely under prefers-reduced-motion).
 */
export const TYPEWRITER_MS_PER_CHAR = 20;
export const ALERT_LINE_STAGGER_MS = 550;

export function prefersReducedMotion(): boolean {
  return typeof window !== "undefined" && !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
}

export interface TypewriterLine {
  id: string;
  text: string;
}

/**
 * Types each newly-seen line. Lines already in flight are left alone, so
 * a growing feed (Action Console) doesn't restart older rows. A full list
 * arriving at once (teaser) still staggers line-by-line.
 *
 * Returns visible character counts keyed by line id. Missing/0 means the
 * line has not started yet and should not render.
 */
export function useTypewriterLines(lines: readonly TypewriterLine[]): Record<string, number> {
  const [visibleChars, setVisibleChars] = useState<Record<string, number>>({});
  const startedRef = useRef(new Set<string>());
  const reduceMotion = prefersReducedMotion();
  const signature = lines.map((l) => l.id).join("\0");

  useEffect(() => {
    if (reduceMotion) {
      const all: Record<string, number> = {};
      for (const line of lines) {
        all[line.id] = line.text.length;
        startedRef.current.add(line.id);
      }
      setVisibleChars(all);
      return;
    }

    const newcomers = lines.filter((line) => !startedRef.current.has(line.id));
    const timers: number[] = [];
    newcomers.forEach((line, i) => {
      startedRef.current.add(line.id);
      const lineStart = i * ALERT_LINE_STAGGER_MS;
      for (let c = 0; c <= line.text.length; c++) {
        timers.push(
          window.setTimeout(() => {
            setVisibleChars((prev) => ({ ...prev, [line.id]: c }));
          }, lineStart + c * TYPEWRITER_MS_PER_CHAR),
        );
      }
    });
    return () => timers.forEach(clearTimeout);
    // `signature` is the id list; `lines` is read for the matching texts.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [signature, reduceMotion]);

  return visibleChars;
}
