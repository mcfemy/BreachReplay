import { useEffect, useState } from "react";
import { Navigate, useNavigate, useParams } from "react-router-dom";
import { api } from "../lib/api";

// ── Types ─────────────────────────────────────────────────────────────────────
interface ScenarioIntroData {
  id: string;
  title: string;
  description: string | null;
  incident_date: string | null;
  incident_duration_hours: number | null;
  industry_vertical: string | null;
  initial_access_vector: string | null;
  affected_asset_types: string[] | null;
  estimated_minutes: number;
  difficulty: string;
}

interface SessionData {
  id: string;
  scenario_id: string;
  host_user_id: string;
  status: string;
}

// ── Industry visual themes ────────────────────────────────────────────────────
const THEMES: Record<string, { gradient: string; accent: string; label: string }> = {
  healthcare: {
    gradient: [
      "radial-gradient(ellipse 70% 55% at 95% 5%,  rgba(30,64,175,0.5)  0%, transparent 65%)",
      "radial-gradient(ellipse 50% 40% at 5%  95%,  rgba(30,64,175,0.2)  0%, transparent 60%)",
    ].join(", "),
    accent: "#60a5fa",
    label: "HEALTHCARE SECTOR",
  },
  energy: {
    gradient: [
      "radial-gradient(ellipse 70% 55% at 5%  90%,  rgba(180,83,9,0.5)   0%, transparent 65%)",
      "radial-gradient(ellipse 50% 40% at 95% 5%,   rgba(180,83,9,0.2)   0%, transparent 60%)",
    ].join(", "),
    accent: "#fbbf24",
    label: "ENERGY & UTILITIES",
  },
  finance: {
    gradient:
      "radial-gradient(ellipse 70% 55% at 90% 10%, rgba(67,56,202,0.45)  0%, transparent 65%)",
    accent: "#818cf8",
    label: "FINANCIAL SERVICES",
  },
  government: {
    gradient:
      "radial-gradient(ellipse 70% 55% at 5%  90%,  rgba(6,78,59,0.45)   0%, transparent 65%)",
    accent: "#34d399",
    label: "GOVERNMENT & DEFENSE",
  },
  technology: {
    gradient: [
      "radial-gradient(ellipse 70% 55% at 5%  5%,   rgba(88,28,135,0.5)  0%, transparent 65%)",
      "radial-gradient(ellipse 50% 40% at 95% 95%,  rgba(88,28,135,0.2)  0%, transparent 60%)",
    ].join(", "),
    accent: "#c084fc",
    label: "TECHNOLOGY SECTOR",
  },
  retail: {
    gradient:
      "radial-gradient(ellipse 70% 55% at 90% 90%, rgba(157,23,77,0.4)   0%, transparent 65%)",
    accent: "#f472b6",
    label: "RETAIL & COMMERCE",
  },
  education: {
    gradient:
      "radial-gradient(ellipse 70% 55% at 50% 0%,  rgba(133,77,14,0.4)  0%, transparent 65%)",
    accent: "#facc15",
    label: "EDUCATION SECTOR",
  },
  other: {
    gradient:
      "radial-gradient(ellipse 60% 45% at 50% 50%, rgba(127,29,29,0.3)   0%, transparent 60%)",
    accent: "#f87171",
    label: "CRITICAL INFRASTRUCTURE",
  },
};

// ── Phase definitions ─────────────────────────────────────────────────────────
interface IntroPhase {
  type:
    | "logo"
    | "date"
    | "title"
    | "hook"
    | "vector"
    | "duration"
    | "impact"
    | "briefing"
    | "ready";
  heading?: string;
  subtext?: string;
  body?: string;
  holdMs: number;
}

function buildPhases(sc: ScenarioIntroData): IntroPhase[] {
  const phases: IntroPhase[] = [];

  phases.push({ type: "logo", holdMs: 1600 });

  const year = sc.incident_date
    ? new Date(sc.incident_date).getFullYear().toString()
    : null;
  const label = THEMES[sc.industry_vertical || "other"]?.label;
  if (year) {
    phases.push({ type: "date", heading: year, subtext: label, holdMs: 2500 });
  }

  phases.push({ type: "title", heading: sc.title, subtext: "THE INCIDENT", holdMs: 3200 });

  if (sc.description) {
    const sentences = sc.description.match(/[^.!?]+[.!?]+/g) || [];
    const hook = sentences.slice(0, 2).join(" ").trim();
    if (hook.length > 15) {
      phases.push({ type: "hook", body: hook, holdMs: 5000 });
    }
  }

  if (sc.initial_access_vector) {
    const v = sc.initial_access_vector.toLowerCase();
    const art = "aeiou".includes(v[0]) ? "an" : "a";
    phases.push({
      type: "vector",
      heading: `It started with ${art} ${v}.`,
      holdMs: 3000,
    });
  }

  if (sc.incident_duration_hours) {
    const h = sc.incident_duration_hours;
    const d =
      h >= 8760 ? `${Math.round(h / 8760)} year${Math.round(h / 8760) > 1 ? "s" : ""}` :
      h >= 720  ? `${Math.round(h / 720)} month${Math.round(h / 720) > 1 ? "s" : ""}` :
      h >= 168  ? `${Math.round(h / 168)} week${Math.round(h / 168) > 1 ? "s" : ""}` :
      h >= 24   ? `${Math.round(h / 24)} day${Math.round(h / 24) > 1 ? "s" : ""}` :
                  `${Math.round(h)} hour${Math.round(h) > 1 ? "s" : ""}`;
    phases.push({ type: "duration", heading: `For ${d},`, subtext: "no one knew.", holdMs: 3500 });
  }

  if (sc.affected_asset_types?.length) {
    phases.push({
      type: "impact",
      subtext: "COMPROMISED SYSTEMS",
      body: sc.affected_asset_types.map((s) => s.toUpperCase()).join("   ·   "),
      holdMs: 3500,
    });
  }

  phases.push({
    type: "briefing",
    body: "You are here because the world cannot afford\nanother incident like this.\n\nThis time — you are in the room when it happens.",
    holdMs: 4200,
  });

  phases.push({ type: "ready", holdMs: Infinity });

  return phases;
}

// ── Component ─────────────────────────────────────────────────────────────────
type PhaseState = "entering" | "holding" | "exiting";

export default function ScenarioCinematicIntroPage() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const navigate = useNavigate();

  if (!sessionId) return <Navigate to="/scenarios" replace />;

  const [scenario, setScenario] = useState<ScenarioIntroData | null>(null);
  const [loading, setLoading] = useState(true);
  const [phases, setPhases] = useState<IntroPhase[]>([]);
  const [phaseIdx, setPhaseIdx] = useState(0);
  const [phaseState, setPhaseState] = useState<PhaseState>("entering");

  useEffect(() => {
    (async () => {
      try {
        const session = await api.get<SessionData>(`/sessions/${sessionId}`);
        const sc = await api.get<ScenarioIntroData>(`/scenarios/${session.scenario_id}`);
        setScenario(sc);
        setPhases(buildPhases(sc));
      } catch {
        navigate(`/session/${sessionId}`);
      } finally {
        setLoading(false);
      }
    })();
  }, [sessionId]);

  useEffect(() => {
    if (!phases.length || phaseIdx >= phases.length) return;
    const phase = phases[phaseIdx];

    if (phase.type === "ready") {
      setPhaseState("holding");
      return;
    }

    let t1: ReturnType<typeof setTimeout>;
    let t2: ReturnType<typeof setTimeout>;
    let t3: ReturnType<typeof setTimeout>;

    t1 = setTimeout(() => {
      setPhaseState("holding");
      t2 = setTimeout(() => {
        setPhaseState("exiting");
        t3 = setTimeout(() => {
          setPhaseIdx((i) => i + 1);
          setPhaseState("entering");
        }, 500);
      }, phase.holdMs);
    }, 700);

    return () => {
      clearTimeout(t1);
      clearTimeout(t2);
      clearTimeout(t3);
    };
  }, [phaseIdx, phases]);

  function handleBegin() {
    navigate(`/session/${sessionId}`);
  }

  if (loading) {
    return (
      <div className="min-h-screen bg-[#040712] flex items-center justify-center">
        <span className="text-red-500 text-xs font-mono uppercase tracking-widest animate-pulse">
          Preparing briefing...
        </span>
      </div>
    );
  }

  if (!scenario || !phases.length) {
    return <Navigate to={`/session/${sessionId}`} replace />;
  }

  const phase = phases[Math.min(phaseIdx, phases.length - 1)];
  const theme = THEMES[scenario.industry_vertical || "other"];
  const isReady = phase.type === "ready";

  const textCls =
    phaseState === "entering"
      ? "opacity-0 translate-y-5 transition-all duration-700"
      : phaseState === "holding"
      ? "opacity-100 translate-y-0 transition-all duration-700"
      : "opacity-0 -translate-y-3 transition-all duration-500";

  const progressPhases = phases.filter((p) => p.type !== "ready");

  return (
    <div
      className="min-h-screen flex flex-col items-center justify-center relative overflow-hidden font-mono select-none"
      style={{ background: `${theme.gradient}, #040712` }}
    >
      {/* CRT scanline texture */}
      <div
        className="absolute inset-0 pointer-events-none"
        style={{
          opacity: 0.025,
          backgroundImage:
            "repeating-linear-gradient(0deg, transparent, transparent 2px, rgba(255,255,255,1) 2px, rgba(255,255,255,1) 3px)",
        }}
      />

      {/* Corner vignette */}
      <div
        className="absolute inset-0 pointer-events-none"
        style={{
          background:
            "radial-gradient(ellipse 85% 85% at 50% 50%, transparent 30%, rgba(0,0,0,0.88) 100%)",
        }}
      />

      {/* Ambient accent glow at bottom */}
      <div
        className="absolute bottom-0 left-0 right-0 h-40 pointer-events-none"
        style={{
          background: `linear-gradient(to top, ${theme.accent}08, transparent)`,
        }}
      />

      {/* Skip button */}
      {!isReady && (
        <button
          onClick={handleBegin}
          className="absolute top-5 right-6 text-[10px] text-slate-700 hover:text-slate-400 uppercase tracking-widest transition-colors z-10 font-mono"
        >
          Skip intro →
        </button>
      )}

      {/* ── Stage ──────────────────────────────────────────────────── */}
      <div className="relative z-10 w-full max-w-2xl mx-auto px-8 text-center">

        {/* LOGO */}
        {phase.type === "logo" && (
          <div className={textCls}>
            <div
              className="text-[11px] tracking-[0.7em] uppercase font-black mb-3"
              style={{ color: theme.accent }}
            >
              BREACH REPLAY
            </div>
            <div className="text-[9px] tracking-[0.4em] uppercase text-slate-700">
              INCIDENT RESPONSE SIMULATION
            </div>
          </div>
        )}

        {/* YEAR */}
        {phase.type === "date" && (
          <div className={textCls}>
            <div
              className="font-black leading-none text-white/90 mb-4 tabular-nums"
              style={{
                fontSize: "clamp(80px, 16vw, 130px)",
                textShadow: `0 0 80px ${theme.accent}50, 0 0 20px ${theme.accent}25`,
              }}
            >
              {phase.heading}
            </div>
            <div
              className="text-xs tracking-[0.55em] uppercase font-bold"
              style={{ color: theme.accent }}
            >
              {phase.subtext}
            </div>
          </div>
        )}

        {/* TITLE */}
        {phase.type === "title" && (
          <div className={textCls}>
            <div
              className="text-[9px] tracking-[0.55em] uppercase font-bold mb-6"
              style={{ color: theme.accent }}
            >
              {phase.subtext}
            </div>
            <div
              className="font-black text-white leading-tight"
              style={{
                fontSize: "clamp(28px, 5vw, 52px)",
                textShadow: "0 0 40px rgba(255,255,255,0.12)",
              }}
            >
              {phase.heading}
            </div>
          </div>
        )}

        {/* HOOK — first sentences of description */}
        {phase.type === "hook" && (
          <div className={textCls}>
            <div
              className="text-xl text-slate-200 leading-loose font-light italic"
              style={{ textShadow: `0 0 60px ${theme.accent}25` }}
            >
              "{phase.body}"
            </div>
          </div>
        )}

        {/* VECTOR — how it started */}
        {phase.type === "vector" && (
          <div className={textCls}>
            <div className="text-2xl md:text-3xl font-bold text-white leading-relaxed">
              {phase.heading}
            </div>
          </div>
        )}

        {/* DURATION */}
        {phase.type === "duration" && (
          <div className={`${textCls} space-y-2`}>
            <div className="text-3xl md:text-4xl font-black text-white">{phase.heading}</div>
            <div
              className="text-3xl md:text-4xl font-black"
              style={{ color: theme.accent }}
            >
              {phase.subtext}
            </div>
          </div>
        )}

        {/* IMPACT — affected systems */}
        {phase.type === "impact" && (
          <div className={textCls}>
            <div className="text-[9px] tracking-[0.5em] uppercase text-slate-600 mb-7 font-bold">
              {phase.subtext}
            </div>
            <div className="text-sm font-bold text-slate-300 tracking-widest leading-loose">
              {phase.body}
            </div>
          </div>
        )}

        {/* BRIEFING — moral weight */}
        {phase.type === "briefing" && (
          <div className={textCls}>
            <div className="text-lg md:text-xl text-slate-300 leading-loose whitespace-pre-line italic font-light">
              {phase.body}
            </div>
          </div>
        )}

        {/* READY — begin button */}
        {phase.type === "ready" && (
          <div className={`${textCls} flex flex-col items-center gap-8`}>
            <div className="text-[9px] tracking-[0.55em] uppercase text-slate-600">
              SCENARIO BRIEFING COMPLETE
            </div>

            <div
              className="font-black text-white leading-snug"
              style={{ fontSize: "clamp(22px, 4vw, 38px)" }}
            >
              {scenario.title}
            </div>

            <div className="flex items-center gap-5 text-[10px] text-slate-500 uppercase tracking-wider">
              <span>{scenario.difficulty}</span>
              <span className="text-slate-700">·</span>
              <span>{scenario.estimated_minutes} min</span>
              <span className="text-slate-700">·</span>
              <span style={{ color: theme.accent }}>{theme.label}</span>
            </div>

            <button
              onClick={handleBegin}
              className="px-14 py-4 text-sm font-black uppercase tracking-[0.4em] text-black rounded-sm transition-all duration-300 hover:scale-105 hover:brightness-110 active:scale-95"
              style={{
                background: theme.accent,
                boxShadow: `0 0 50px ${theme.accent}65, 0 0 100px ${theme.accent}25`,
              }}
            >
              BEGIN SIMULATION
            </button>

            <div className="text-[8px] text-slate-700 uppercase tracking-widest">
              Real decisions. Real pressure. No infrastructure harmed.
            </div>
          </div>
        )}
      </div>

      {/* ── Phase progress dots ───────────────────────────────────── */}
      {!isReady && (
        <div className="absolute bottom-8 left-1/2 -translate-x-1/2 flex items-center gap-2">
          {progressPhases.map((_, i) => (
            <div
              key={i}
              className="h-[2px] rounded-full transition-all duration-500"
              style={{
                width: i === phaseIdx ? "22px" : "5px",
                background:
                  i < phaseIdx
                    ? theme.accent
                    : i === phaseIdx
                    ? theme.accent
                    : "rgba(255,255,255,0.08)",
                opacity: i <= phaseIdx ? 1 : 0.3,
              }}
            />
          ))}
        </div>
      )}

      {/* Breach Replay watermark */}
      <div
        className="absolute bottom-4 right-6 text-[8px] tracking-widest uppercase font-mono"
        style={{ color: `${theme.accent}30` }}
      >
        BREACH REPLAY
      </div>
    </div>
  );
}
