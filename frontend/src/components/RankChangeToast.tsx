import { useEffect, useState } from "react";

interface RankChangeToastProps {
  before: number;
  after: number;
  delta: number;
  onDone?: () => void;
}

/**
 * Live Arena Mode (Phase I) post-match rank-change toast — same
 * bottom-right/animate-bounce-in convention as XPToast.tsx, shown once a
 * match's `match_complete` WS event carries a `rating_change` for the
 * current user (ArenaMatchPage.tsx wires this up).
 */
export default function RankChangeToast({ before, after, delta, onDone }: RankChangeToastProps) {
  const [visible, setVisible] = useState(true);

  useEffect(() => {
    const t = setTimeout(() => {
      setVisible(false);
      onDone?.();
    }, 4500);
    return () => clearTimeout(t);
  }, [onDone]);

  if (!visible) return null;

  const gained = delta >= 0;

  return (
    <div className="fixed bottom-6 right-6 z-50 flex flex-col gap-2 items-end pointer-events-none">
      <div
        className={`animate-bounce-in flex items-center gap-3 bg-gray-900 border rounded-xl px-4 py-3 shadow-2xl ${
          gained ? "border-cyan-500/40" : "border-orange-500/40"
        }`}
      >
        <span className="text-2xl">{gained ? "📈" : "📉"}</span>
        <div>
          <div className={`font-black text-lg ${gained ? "text-cyan-400" : "text-orange-400"}`}>
            {gained ? "+" : ""}
            {delta} Rating
          </div>
          <div className="text-gray-500 text-[10px] uppercase tracking-widest">
            {before} → {after}
          </div>
        </div>
      </div>
    </div>
  );
}
