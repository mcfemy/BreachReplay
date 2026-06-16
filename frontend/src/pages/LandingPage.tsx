import { useEffect, useState, useRef } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuthStore } from "../store/auth";

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

const SCENARIOS = [
  {
    title: "Colonial Pipeline",
    tag: "LIVE",
    tagColor: "bg-red-500",
    year: "2021",
    industry: "Energy / OT",
    difficulty: "Expert",
    minutes: 45,
    desc: "DarkSide ransomware. 5,500 miles of pipeline. 12 decision gates from VPN compromise to SCADA shutdown.",
    mitre: ["T1078", "T1003", "T1486", "T1490"],
  },
  {
    title: "SolarWinds Orion",
    tag: "NEW",
    tagColor: "bg-blue-600",
    year: "2020",
    industry: "Supply Chain",
    difficulty: "Expert",
    minutes: 60,
    desc: "Nation-state supply chain compromise. 18,000 organizations. Detecting a backdoor in your own monitoring tool.",
    mitre: ["T1195", "T1072", "T1078", "T1027"],
  },
  {
    title: "MGM Grand Cyberattack",
    tag: "NEW",
    tagColor: "bg-blue-600",
    year: "2023",
    industry: "Hospitality",
    difficulty: "Practitioner",
    minutes: 40,
    desc: "Social engineering → identity attack → $100M loss. ALPHV/Scattered Spider TTPs against Okta and Azure AD.",
    mitre: ["T1566", "T1078.004", "T1538", "T1498"],
  },
  {
    title: "Log4Shell Mass Exploitation",
    tag: "NEW",
    tagColor: "bg-blue-600",
    year: "2021",
    industry: "Technology",
    difficulty: "Practitioner",
    minutes: 35,
    desc: "Zero-day in the world's most popular logging library. Triage when your entire infrastructure is exposed.",
    mitre: ["T1190", "T1059", "T1105", "T1203"],
  },
  {
    title: "NHS WannaCry Ransomware",
    tag: "NEW",
    tagColor: "bg-blue-600",
    year: "2017",
    industry: "Healthcare",
    difficulty: "Practitioner",
    minutes: 40,
    desc: "WannaCry hits 80 NHS Trusts. MRI scanners down. A&E on paper. Blood results inaccessible. The kill switch changes everything.",
    mitre: ["T1190", "T1486", "T1570", "T1021"],
  },
];

const PRICING = [
  {
    name: "Free",
    price: "$0",
    period: "forever",
    color: "border-slate-700",
    badge: null,
    cta: "Start free",
    ctaLink: "/register",
    ctaStyle: "bg-slate-700 hover:bg-slate-600 text-white",
    features: [
      "Access to all public scenarios",
      "Solo & remote multiplayer",
      "Post-simulation debrief",
      "NIST/MITRE decision mapping",
      "Completion certificates",
      "Up to 3 custom documents",
    ],
    missing: ["Team analytics dashboard", "Private scenario library", "Compliance evidence export", "SSO / SAML", "Priority support"],
  },
  {
    name: "Enterprise",
    price: "Custom",
    period: "per team / year",
    color: "border-red-500",
    badge: "Most popular for CISOs",
    cta: "Get Enterprise Access",
    ctaLink: "/pricing",
    ctaStyle: "bg-red-600 hover:bg-red-500 text-white",
    features: [
      "Everything in Free",
      "Unlimited team members",
      "Team compliance analytics & readiness score",
      "Private scenario library",
      "Ingest your own breach documents (PDF/DOCX)",
      "Compliance evidence export (CSV/PDF)",
      "NIST CSF / SOC 2 / ISO 27001 mapping",
      "SSO / SAML (coming soon)",
      "Dedicated onboarding & support",
      "Custom SLA",
    ],
    missing: [],
  },
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
  const pricingRef = useRef<HTMLDivElement>(null);

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
              onClick={() => pricingRef.current?.scrollIntoView({ behavior: "smooth" })}
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
                onClick={() => pricingRef.current?.scrollIntoView({ behavior: "smooth" })}
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

      {/* ── Social proof bar ─────────────────────────────────── */}
      <section className="border-y border-gray-800/60 py-6 px-6">
        <div className="max-w-6xl mx-auto flex flex-wrap items-center justify-center gap-8 text-xs text-gray-500">
          <span>BUILT FOR TEAMS THAT TAKE IR SERIOUSLY</span>
          {["Fortune 500 Security Teams", "MSSPs", "Government Agencies", "Healthcare SOCs", "Financial Institutions"].map(t => (
            <span key={t} className="px-3 py-1 border border-gray-800 rounded text-gray-600">{t}</span>
          ))}
        </div>
      </section>

      {/* ── How it works ─────────────────────────────────────── */}
      <section className="py-24 px-6 max-w-6xl mx-auto">
        <div className="text-center mb-16">
          <h2 className="text-3xl font-bold mb-4">Run your first tabletop in under 5 minutes</h2>
          <p className="text-gray-400 max-w-xl mx-auto">No facilitators. No slide decks. No scheduling chaos. Just pick a scenario and go.</p>
        </div>
        <div className="grid md:grid-cols-3 gap-8">
          {[
            {
              step: "01",
              title: "Choose a breach",
              desc: "Pick from our library of real incidents — Colonial Pipeline, SolarWinds, MGM, and more. Or ingest your own breach document.",
              icon: "📂",
            },
            {
              step: "02",
              title: "Assign roles to your team",
              desc: "Incident Commander, Forensic Analyst, Communications Lead, Legal & Compliance, Network Engineer. Invite anyone — anywhere in the world.",
              icon: "👥",
            },
            {
              step: "03",
              title: "Live simulation begins",
              desc: "Real alerts fire in sequence. Pressure injections interrupt: board members, FBI liaisons, journalists. Your team makes time-pressured decisions together.",
              icon: "⚡",
            },
          ].map(item => (
            <div key={item.step} className="relative p-6 border border-gray-800 rounded-lg hover:border-gray-600 transition-colors">
              <div className="text-5xl mb-4">{item.icon}</div>
              <div className="text-red-500 text-xs font-bold mb-2">STEP {item.step}</div>
              <h3 className="text-lg font-bold mb-3">{item.title}</h3>
              <p className="text-gray-400 text-sm leading-relaxed">{item.desc}</p>
            </div>
          ))}
        </div>
      </section>

      {/* ── Scenarios ────────────────────────────────────────── */}
      <section className="py-24 px-6 bg-gray-950/50">
        <div className="max-w-6xl mx-auto">
          <div className="flex items-end justify-between mb-12">
            <div>
              <h2 className="text-3xl font-bold mb-3">Scenario library</h2>
              <p className="text-gray-400">Every scenario is built from real incident reports, CISA advisories, and SEC 8-K filings.</p>
            </div>
            <Link to="/register" className="text-red-400 hover:text-red-300 text-sm transition-colors hidden md:block">
              View all →
            </Link>
          </div>
          <div className="grid md:grid-cols-2 gap-6">
            {SCENARIOS.map(s => (
              <div key={s.title} className="border border-gray-800 rounded-lg p-6 hover:border-gray-600 transition-colors group">
                <div className="flex items-start justify-between mb-4">
                  <div>
                    <div className="flex items-center gap-2 mb-2">
                      <span className={`text-xs px-2 py-0.5 rounded font-bold ${s.tagColor} text-white`}>{s.tag}</span>
                      <span className="text-xs text-gray-500">{s.year}</span>
                    </div>
                    <h3 className="text-lg font-bold group-hover:text-red-400 transition-colors">{s.title}</h3>
                  </div>
                  <div className="text-right text-xs text-gray-500">
                    <div>{s.industry}</div>
                    <div className="mt-1">{s.minutes} min</div>
                  </div>
                </div>
                <p className="text-gray-400 text-sm leading-relaxed mb-4">{s.desc}</p>
                <div className="flex flex-wrap gap-2">
                  {s.mitre.map(t => (
                    <span key={t} className="text-xs px-2 py-0.5 bg-gray-900 border border-gray-700 rounded text-gray-500">{t}</span>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── Multiplayer callout ───────────────────────────────── */}
      <section className="py-24 px-6 max-w-6xl mx-auto">
        <div className="grid lg:grid-cols-2 gap-12 items-center">
          <div>
            <h2 className="text-3xl font-bold mb-6">
              Train your entire team.<br />
              <span className="text-red-500">Anywhere in the world.</span>
            </h2>
            <p className="text-gray-400 leading-relaxed mb-8">
              Remote multiplayer is built in — not bolted on. One person creates a session, shares the link, and your global team is running a live incident simulation in under 60 seconds.
            </p>
            <div className="space-y-4">
              {[
                { role: "Incident Commander", desc: "Leads containment. Locks decisions. Owns the timeline." },
                { role: "Forensic Analyst", desc: "Analyzes host captures. Attributes TTPs. Uncovers the kill chain." },
                { role: "Communications Lead", desc: "Drafts stakeholder messages under time pressure and media scrutiny." },
                { role: "Legal & Compliance", desc: "Advises on disclosure obligations, regulatory timelines, and ransom legality." },
                { role: "Network Engineer", desc: "Executes firewall rules, isolations, and OT/IT segmentation decisions." },
              ].map(r => (
                <div key={r.role} className="flex gap-3">
                  <div className="w-1 bg-red-500/40 rounded-full flex-shrink-0" />
                  <div>
                    <div className="text-sm font-bold text-red-400">{r.role}</div>
                    <div className="text-xs text-gray-500">{r.desc}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>
          <div className="space-y-4">
            {/* Fake live session preview */}
            <div className="border border-gray-800 rounded-lg p-4 bg-gray-950/50">
              <div className="text-xs text-gray-500 mb-3">LIVE SESSION — Colonial Pipeline 2021</div>
              <div className="space-y-2">
                {[
                  { name: "J. Okafor", role: "Incident Commander", status: "online", color: "bg-red-500" },
                  { name: "M. Chen", role: "Forensic Analyst", status: "online", color: "bg-blue-500" },
                  { name: "S. Patel", role: "Communications Lead", status: "online", color: "bg-green-500" },
                  { name: "A. Williams", role: "Legal & Compliance", status: "online", color: "bg-yellow-500" },
                  { name: "T. Nguyen", role: "Network Engineer", status: "typing...", color: "bg-purple-500" },
                ].map(p => (
                  <div key={p.name} className="flex items-center gap-3">
                    <div className={`w-2 h-2 rounded-full ${p.color}`} />
                    <span className="text-sm text-gray-300 flex-1">{p.name}</span>
                    <span className="text-xs text-gray-600">{p.role}</span>
                    <span className="text-xs text-green-500">{p.status}</span>
                  </div>
                ))}
              </div>
            </div>
            <div className="border border-red-900/40 rounded-lg p-4 bg-red-950/20">
              <div className="text-xs text-red-400 font-bold mb-1">⚡ PRESSURE INJECTION — 30s</div>
              <div className="text-sm text-gray-300 mb-1">CEO — Sarah Chen &lt;s.chen@colpipe.com&gt;</div>
              <div className="text-xs text-gray-500">"Are we paying the ransom?? I need to know right now. Board is calling every 5 minutes."</div>
            </div>
          </div>
        </div>
      </section>

      {/* ── Pricing ──────────────────────────────────────────── */}
      <section ref={pricingRef} className="py-24 px-6 bg-gray-950/50">
        <div className="max-w-4xl mx-auto">
          <div className="text-center mb-16">
            <h2 className="text-3xl font-bold mb-4">Simple, honest pricing</h2>
            <p className="text-gray-400">Individuals are free forever. Enterprises get analytics, private scenarios, and compliance exports.</p>
          </div>
          <div className="grid md:grid-cols-2 gap-6">
            {PRICING.map(plan => (
              <div key={plan.name} className={`relative border-2 ${plan.color} rounded-lg p-8`}>
                {plan.badge && (
                  <div className="absolute -top-3 left-1/2 -translate-x-1/2 px-3 py-1 bg-red-600 text-white text-xs font-bold rounded-full">
                    {plan.badge}
                  </div>
                )}
                <div className="mb-6">
                  <div className="text-xs text-gray-500 mb-1">{plan.name.toUpperCase()}</div>
                  <div className="flex items-end gap-2">
                    <span className="text-4xl font-bold">{plan.price}</span>
                    <span className="text-gray-500 text-sm mb-1">/ {plan.period}</span>
                  </div>
                </div>
                <a
                  href={plan.ctaLink}
                  className={`block text-center py-3 rounded font-bold text-sm tracking-wider mb-8 transition-colors ${plan.ctaStyle}`}
                >
                  {plan.cta.toUpperCase()}
                </a>
                <div className="space-y-3">
                  {plan.features.map(f => (
                    <div key={f} className="flex items-start gap-2 text-sm">
                      <span className="text-green-400 flex-shrink-0 mt-0.5">✓</span>
                      <span className="text-gray-300">{f}</span>
                    </div>
                  ))}
                  {plan.missing.map(f => (
                    <div key={f} className="flex items-start gap-2 text-sm">
                      <span className="text-gray-700 flex-shrink-0 mt-0.5">—</span>
                      <span className="text-gray-700">{f}</span>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── Final CTA ────────────────────────────────────────── */}
      <section className="py-24 px-6">
        <div className="max-w-2xl mx-auto text-center">
          <h2 className="text-3xl font-bold mb-4">
            The next breach is a matter of when, not if.
          </h2>
          <p className="text-gray-400 mb-8 leading-relaxed">
            The Colonial Pipeline team had no simulated playbook for a ransomware-OT crossover event. Your team can.
          </p>
          <Link
            to="/register"
            className="inline-block px-8 py-4 bg-red-600 hover:bg-red-500 text-white font-bold rounded text-sm tracking-widest transition-colors"
          >
            START YOUR FIRST SIMULATION — FREE
          </Link>
          <div className="mt-6 text-xs text-gray-600">
            No credit card. No sales call. Ready in 60 seconds.
          </div>
        </div>
      </section>

      {/* ── Footer ───────────────────────────────────────────── */}
      <footer className="border-t border-gray-800 py-10 px-6">
        <div className="max-w-6xl mx-auto flex flex-col md:flex-row items-center justify-between gap-4 text-xs text-gray-600">
          <div className="flex items-center gap-2">
            <span className="text-red-500 font-bold">BREACH</span>
            <span className="text-white font-bold">REPLAY</span>
            <span className="ml-4">© 2026 BreachReplay. All rights reserved.</span>
          </div>
          <div className="flex gap-6">
            <a href="mailto:hello@breachreplay.com" className="hover:text-gray-400 transition-colors">Contact</a>
            <Link to="/login" className="hover:text-gray-400 transition-colors">Sign in</Link>
            <Link to="/register" className="hover:text-gray-400 transition-colors">Register</Link>
          </div>
        </div>
      </footer>
    </div>
  );
}
