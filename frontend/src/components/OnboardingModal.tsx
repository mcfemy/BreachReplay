import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuthStore } from "../store/auth";

const STEPS = [
  {
    num: "01",
    title: "Pick a Scenario",
    desc: "Choose from Colonial Pipeline, SolarWinds, MGM Grand, Log4Shell — or upload your own post-mortem PDF.",
  },
  {
    num: "02",
    title: "Make Real-Time Decisions",
    desc: "Work through decision gates under time pressure with your team via live multiplayer WebSocket.",
  },
  {
    num: "03",
    title: "Get Claude AI Debrief",
    desc: "Receive a NIST/MITRE gap analysis + compliance certificate PDF your auditors will accept.",
  },
];

export default function OnboardingModal() {
  const user = useAuthStore((s) => s.user);
  const navigate = useNavigate();
  const [visible, setVisible] = useState(() => {
    if (!user) return false;
    return !localStorage.getItem("br_onboarded");
  });

  if (!visible) return null;

  function dismiss() {
    localStorage.setItem("br_onboarded", "1");
    setVisible(false);
  }

  function start() {
    dismiss();
    navigate("/scenarios");
  }

  return (
    <div className="fixed inset-0 bg-black/75 z-50 flex items-center justify-center p-4">
      <div className="bg-breach-surface border border-breach-border rounded-lg p-8 max-w-md w-full shadow-2xl">
        <div className="text-[10px] text-breach-accent uppercase tracking-widest font-black mb-2">
          Breach Replay
        </div>
        <h2 className="text-lg font-black text-breach-text tracking-tight mb-1">
          Welcome to BreachReplay
        </h2>
        <p className="text-xs text-breach-muted mb-6">
          The only cybersecurity training platform built from real breach data.
        </p>

        <div className="space-y-3 mb-7">
          {STEPS.map((s) => (
            <div
              key={s.num}
              className="flex gap-3 bg-breach-bg border border-breach-border/60 rounded p-3"
            >
              <span className="text-breach-accent font-black font-mono text-sm shrink-0 mt-0.5">
                {s.num}
              </span>
              <div>
                <div className="text-xs font-bold text-breach-text mb-0.5">{s.title}</div>
                <div className="text-[10px] text-breach-muted leading-relaxed">{s.desc}</div>
              </div>
            </div>
          ))}
        </div>

        <button
          onClick={start}
          className="w-full bg-breach-accent hover:bg-red-600 text-white py-2.5 rounded text-xs uppercase tracking-widest font-black transition-colors mb-3"
        >
          Start My First Simulation
        </button>
        <button
          onClick={dismiss}
          className="w-full text-[10px] text-breach-muted hover:text-breach-text transition-colors uppercase tracking-widest"
        >
          Skip for now
        </button>
      </div>
    </div>
  );
}
