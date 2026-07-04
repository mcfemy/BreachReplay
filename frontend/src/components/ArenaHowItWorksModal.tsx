interface ArenaHowItWorksModalProps {
  open: boolean;
  onClose: () => void;
}

const STEPS = [
  {
    num: "01",
    title: "Real-Time, Not Turns",
    desc: "The attacker acts on a live clock, whether you're watching or not. Alerts arrive as your SIEM detects them — not every move gets caught, so a quiet feed doesn't mean nothing's happening.",
  },
  {
    num: "02",
    title: "Three Ways to Play",
    desc: "PvP (human vs human, same live org), Defend vs AI Attacker (you run the SOC), or Attack vs AI Defender (you're the intrusion) — pick a mode and difficulty on the lobby screen.",
  },
  {
    num: "03",
    title: "You Have Full Control",
    desc: "As defender, you're not stuck waiting for a prompt — use the SOC Console to isolate hosts, disable credentials, patch CVEs, or increase segment monitoring at any time.",
  },
  {
    num: "04",
    title: "How a Match Ends",
    desc: "The attacker wins by deploying impact on two compromised hosts. The defender wins by fully containing every compromised host — or simply by surviving long enough.",
  },
];

export default function ArenaHowItWorksModal({ open, onClose }: ArenaHowItWorksModalProps) {
  if (!open) return null;

  return (
    <div className="fixed inset-0 bg-black/75 z-50 flex items-center justify-center p-4">
      <div className="bg-gray-950 border border-gray-800 rounded-xl p-8 max-w-md w-full shadow-2xl">
        <div className="text-[10px] text-cyan-500 uppercase tracking-widest font-black mb-2">
          Live Arena
        </div>
        <h2 className="text-lg font-black text-white tracking-tight mb-1">How Arena Works</h2>
        <p className="text-xs text-gray-500 mb-6">
          A real, deterministic simulated org — no scripted outcomes, no repeat matches.
        </p>

        <div className="space-y-3 mb-7">
          {STEPS.map((s) => (
            <div key={s.num} className="flex gap-3 bg-gray-900/60 border border-gray-800 rounded p-3">
              <span className="text-cyan-500 font-black font-mono text-sm shrink-0 mt-0.5">{s.num}</span>
              <div>
                <div className="text-xs font-bold text-white mb-0.5">{s.title}</div>
                <div className="text-[10px] text-gray-500 leading-relaxed">{s.desc}</div>
              </div>
            </div>
          ))}
        </div>

        <button
          onClick={onClose}
          className="w-full bg-cyan-600 hover:bg-cyan-500 text-white py-2.5 rounded text-xs uppercase tracking-widest font-black transition-colors"
        >
          Got It — Let's Go
        </button>
      </div>
    </div>
  );
}
