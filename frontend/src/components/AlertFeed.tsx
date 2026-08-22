import { useTypewriterLines } from "../lib/typewriter";
import type { FeedLine } from "../lib/runFeed";

/**
 * Action Console incident feed — teaser-style typewriter over lines
 * derived from existing run state (see runFeed.ts). role="log" so screen
 * readers get new rows without us inventing a second live region.
 */
export default function AlertFeed({ lines }: { lines: FeedLine[] }) {
  const visibleChars = useTypewriterLines(lines);

  if (lines.length === 0) return null;

  return (
    <div
      role="log"
      aria-label="Incident feed"
      aria-live="polite"
      className="shrink-0 max-h-[5.5rem] overflow-y-auto font-term text-[10px] space-y-1 bg-panel/50 border-b border-white/5 px-4 py-2"
    >
      {lines.map((line) => {
        const n = visibleChars[line.id] ?? 0;
        if (!n) return null;
        return (
          <div key={line.id} data-testid="feed-line">
            <span className="text-dim">[{line.ts}]</span>{" "}
            <span className="text-gray-300">{line.text.slice(0, n)}</span>
          </div>
        );
      })}
    </div>
  );
}
