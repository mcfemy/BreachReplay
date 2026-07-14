import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuthStore } from "../store/auth";
import LandingPageMarketing from "./LandingPageMarketing";

const TERMINAL_LINES = [
  { delay: 0,    color: "text-yellow-400", text: "[+0m]  VPN login from 185.220.101.34 — account: svc_backup — geo: RU" },
  { delay: 900,  color: "text-yellow-400", text: "[+4m]  Encoded PowerShell on CORP-WKS-22 — parent: outlook.exe" },
  { delay: 1800, color: "text-red-400",    text: "[+8m]  CRITICAL — Mimikatz detected on CORP-DC-01 (lsass.exe)" },
  { delay: 2700, color: "text-red-400",    text: "[+12m] New domain admin 'svc_update01' — no ticket on file" },
  { delay: 3600, color: "text-red-500",    text: "[+16m] RDP lateral movement: 14 hosts in 8 min from CORP-DC-01" },
  { delay: 4500, color: "text-red-600",    text: "[+24m] 40GB staged on FIN-SVR-04 → 162.244.80.235 (DarkSide C2)" },
  { delay: 5400, color: "text-red-600",    text: "[+36m] IT/OT firewall rule modified — VLAN 40 now ALLOW BIDIRECTIONAL" },
  { delay: 6300, color: "text-red-700 font-bold", text: "[+45m] RANSOMWARE DETONATING — 45 hosts — SCADA HMI going dark" },
];

function TerminalAnimation() {
  const [visibleLines, setVisibleLines] = useState<number[]>([]);
  const [gateVisible, setGateVisible] = useState(false);

  useEffect(() => {
    TERMINAL_LINES.forEach((line, i) => {
      setTimeout(() => setVisibleLines(prev => [...prev, i]), line.delay + 400);
    });
    setTimeout(() => setGateVisible(true), 7200);
  }, []);

  return (
    <div className="bg-gray-950 border border-gray-800 rounded-lg overflow-hidden shadow-2xl shadow-red-900/20">
      <div className="flex items-center gap-2 px-4 py-3 bg-gray-900 border-b border-gray-800">
        <div className="w-3 h-3 rounded-full bg-red-500/80" />
        <div className="w-3 h-3 rounded-full bg-yellow-500/80" />
        <div className="w-3 h-3 rounded-full bg-green-500/80" />
        <span className="ml-2 text-xs text-gray-500">breachreplay — colonial-pipeline-2021 — live simulation</span>
      </div>
      <div className="p-4 space-y-1 min-h-[260px] text-xs leading-relaxed">
        <div className="text-gray-500 mb-3">$ breach-replay run --scenario colonial-pipeline --mode multiplayer</div>
        {TERMINAL_LINES.map((line, i) => (
          <div
            key={i}
            className={`transition-all duration-300 ${line.color} ${visibleLines.includes(i) ? "opacity-100" : "opacity-0"}`}
          >
            {line.text}
          </div>
        ))}
        {gateVisible && (
          <div className="mt-4 border border-red-500/60 bg-red-950/30 rounded p-3 animate-pulse">
            <div className="text-red-400 font-bold mb-1">⚡ DECISION GATE — 25 seconds</div>
            <div className="text-gray-300">SCADA HMI screens going dark. Do you order a full pipeline shutdown?</div>
            <div className="flex gap-3 mt-2">
              <span className="px-2 py-1 border border-gray-600 rounded text-gray-400 cursor-pointer">A. Full shutdown</span>
              <span className="px-2 py-1 border border-gray-600 rounded text-gray-400 cursor-pointer">B. Keep running, verify manually</span>
              <span className="px-2 py-1 border border-red-500 rounded text-red-400 cursor-pointer">C. Surgical segment shutdown ✓</span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default function LandingPage() {
  const { token } = useAuthStore();
  const navigate = useNavigate();
  const scrollToPricing = () => document.getElementById("pricing")?.scrollIntoView({ behavior: "smooth" });

  useEffect(() => {
    if (token) navigate("/scenarios", { replace: true });
  }, [token, navigate]);

  return (
    <div className="min-h-screen bg-[#0a0e1a] text-gray-100 font-mono">

      {/* ── Nav ──────────────────────────────────────────────── */}
      <nav className="fixed top-0 left-0 right-0 z-50 border-b border-gray-800/60 bg-[#0a0e1a]/90 backdrop-blur-md">
        <div className="max-w-6xl mx-auto px-6 h-14 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="text-red-500 font-bold text-lg tracking-widest">BREACH</span>
            <span className="text-white font-bold text-lg tracking-widest">REPLAY</span>
          </div>
          <div className="flex items-center gap-6 text-sm">
            <button
              onClick={scrollToPricing}
              className="text-gray-400 hover:text-white transition-colors"
            >
              Pricing
            </button>
            <Link to="/login" className="text-gray-400 hover:text-white transition-colors">Sign in</Link>
            <Link to="/register" className="px-4 py-1.5 bg-red-600 hover:bg-red-500 text-white rounded transition-colors text-xs font-bold tracking-wider">
              START FREE
            </Link>
          </div>
        </div>
      </nav>

      {/* ── Hero ─────────────────────────────────────────────── */}
      <section className="pt-32 pb-20 px-6 max-w-6xl mx-auto">
        <div className="grid lg:grid-cols-2 gap-12 items-center">
          <div>
            <div className="inline-flex items-center gap-2 px-3 py-1 bg-red-950/50 border border-red-800/50 rounded-full text-red-400 text-xs mb-6">
              <span className="w-1.5 h-1.5 bg-red-500 rounded-full animate-pulse" />
              Based on real-world breaches. Updated as incidents happen.
            </div>
            <h1 className="text-4xl lg:text-5xl font-bold leading-tight mb-6">
              Your team's first breach
              <span className="text-red-500"> should be a simulation.</span>
            </h1>
            <p className="text-gray-400 text-lg leading-relaxed mb-8">
              Replay real cyberattacks — Colonial Pipeline, SolarWinds, MGM, NHS WannaCry — with your team. Real decision pressure. Real roles. Real consequences. No vendor fluff.
            </p>
            <div className="flex flex-wrap gap-4">
              <Link
                to="/register"
                className="px-6 py-3 bg-red-600 hover:bg-red-500 text-white font-bold rounded transition-colors tracking-wider text-sm"
              >
                START FREE — NO CARD NEEDED
              </Link>
              <button
                onClick={scrollToPricing}
                className="px-6 py-3 border border-gray-600 hover:border-gray-400 text-gray-300 hover:text-white font-bold rounded transition-colors text-sm"
              >
                ENTERPRISE PRICING →
              </button>
            </div>
            <div className="flex items-center gap-6 mt-8 text-xs text-gray-500">
              <span className="flex items-center gap-1.5"><span className="text-green-400">✓</span> Free forever for individuals</span>
              <span className="flex items-center gap-1.5"><span className="text-green-400">✓</span> Remote multiplayer</span>
              <span className="flex items-center gap-1.5"><span className="text-green-400">✓</span> NIST CSF mapped</span>
            </div>
          </div>
          <div className="lg:block">
            <TerminalAnimation />
          </div>
        </div>
      </section>

      <LandingPageMarketing />
    </div>
  );
}
