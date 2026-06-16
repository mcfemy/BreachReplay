import { useEffect, useState } from "react";

interface XPToastProps {
  xp: number;
  leveledUp?: boolean;
  newTierLabel?: string;
  achievements?: string[];
  onDone?: () => void;
}

export default function XPToast({ xp, leveledUp, newTierLabel, achievements = [], onDone }: XPToastProps) {
  const [visible, setVisible] = useState(true);

  useEffect(() => {
    const t = setTimeout(() => {
      setVisible(false);
      onDone?.();
    }, leveledUp ? 4500 : 2800);
    return () => clearTimeout(t);
  }, [leveledUp, onDone]);

  if (!visible) return null;

  return (
    <div className="fixed bottom-6 right-6 z-50 flex flex-col gap-2 items-end pointer-events-none">
      {/* XP award */}
      <div className="animate-bounce-in flex items-center gap-2 bg-gray-900 border border-yellow-500/40 rounded-xl px-4 py-3 shadow-2xl">
        <span className="text-yellow-400 text-xl">⭐</span>
        <div>
          <div className="text-yellow-400 font-black text-lg">+{xp.toLocaleString()} XP</div>
          <div className="text-gray-500 text-[10px] uppercase tracking-widest">Experience earned</div>
        </div>
      </div>

      {/* Level up */}
      {leveledUp && newTierLabel && (
        <div className="animate-bounce-in flex items-center gap-2 bg-gradient-to-r from-purple-900/80 to-pink-900/80 border border-purple-400/50 rounded-xl px-4 py-3 shadow-2xl">
          <span className="text-2xl">🎖️</span>
          <div>
            <div className="text-white font-black text-sm">TIER UP!</div>
            <div className="text-purple-300 text-xs font-bold">{newTierLabel}</div>
          </div>
        </div>
      )}

      {/* Achievement unlocks */}
      {achievements.slice(0, 2).map((key) => (
        <div key={key} className="animate-bounce-in flex items-center gap-2 bg-gray-900 border border-green-500/40 rounded-xl px-4 py-3 shadow-2xl">
          <span className="text-green-400 text-lg">🏅</span>
          <div>
            <div className="text-green-400 font-bold text-xs">Achievement Unlocked</div>
            <div className="text-gray-300 text-[10px] uppercase tracking-wide">{key.replace(/_/g, " ")}</div>
          </div>
        </div>
      ))}
    </div>
  );
}
