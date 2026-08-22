import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import NetworkMap from "../components/NetworkMap";
import LandingPageMarketing from "./LandingPageMarketing";
import { teaserApi, stashTeaserToken, type TeaserStartResponse } from "../lib/teaser";
import { useTypewriterLines } from "../lib/typewriter";
import type { NodeState } from "../theme/tokens";

/**
 * Phase 1 — No-auth landing teaser (BREACHREPLAY_GAME_OVERHAUL_SPEC.md
 * section 3). Replaces the marketing hero at `/` with a playable,
 * zero-auth, 60-second slice of the Colonial Pipeline breach. The existing
 * LandingPage.tsx is untouched and still fully functional — rolling back
 * is a one-line change in App.tsx (swap the `/` route's element back).
 * Below the fold, this renders the exact same LandingPageMarketing used by
 * LandingPage.tsx, so enterprise buyers (pricing/security/SSO) still land
 * on familiar content.
 */

type Phase = "loading" | "playing" | "resolved" | "error";

export default function TeaserLandingPage() {
  const navigate = useNavigate();
  const [phase, setPhase] = useState<Phase>("loading");
  const [payload, setPayload] = useState<TeaserStartResponse | null>(null);
  const [nodeStates, setNodeStates] = useState<Record<string, NodeState>>({});
  const [secondsLeft, setSecondsLeft] = useState(60);
  const [consequenceText, setConsequenceText] = useState("");
  const [endCardText, setEndCardText] = useState("");
  const [wasCorrect, setWasCorrect] = useState(false);
  const answeredRef = useRef(false);
  const alertItems = (payload?.alert_lines ?? []).map((line, i) => ({
    id: `${line.timestamp}-${i}`,
    text: line.text,
  }));
  const visibleAlertChars = useTypewriterLines(alertItems);

  const scrollToPricing = () => document.getElementById("pricing")?.scrollIntoView({ behavior: "smooth" });

  useEffect(() => {
    let cancelled = false;
    teaserApi
      .start()
      .then((data) => {
        if (cancelled) return;
        setPayload(data);
        setNodeStates(data.node_states);
        setSecondsLeft(data.countdown_seconds);
        setPhase("playing");
      })
      .catch(() => {
        if (!cancelled) setPhase("error");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const handleAnswer = useCallback(
    async (nodeId: string) => {
      if (!payload || answeredRef.current) return;
      answeredRef.current = true;
      try {
        const result = await teaserApi.answer(payload.teaser_token, nodeId);
        setNodeStates((prev) => ({ ...prev, ...result.node_states }));
        setConsequenceText(result.consequence_text);
        setEndCardText(result.end_card_text);
        setWasCorrect(result.correct);
        setPhase("resolved");
      } catch {
        setPhase("error");
      }
    },
    [payload]
  );

  // 60-second hard cap, enforced client-side; on timeout, auto-submit the
  // last offered choice so the run still resolves (and still records a
  // teaser_decided/teaser_completed pair for the funnel) instead of
  // stalling forever.
  useEffect(() => {
    if (phase !== "playing") return;
    if (secondsLeft <= 0) {
      const choices = payload?.decision.node_choices ?? [];
      if (choices.length) void handleAnswer(choices[choices.length - 1]);
      return;
    }
    const t = window.setTimeout(() => setSecondsLeft((s) => s - 1), 1000);
    return () => clearTimeout(t);
  }, [phase, secondsLeft, payload, handleAnswer]);

  const handleSignup = () => {
    if (payload) stashTeaserToken(payload.teaser_token);
    navigate("/register");
  };

  if (phase === "loading") {
    return (
      <div className="min-h-screen bg-void flex items-center justify-center">
        <div className="w-8 h-8 border-2 border-phosphor border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (phase === "error" || !payload) {
    return (
      <div className="min-h-screen bg-void text-gray-200 flex flex-col items-center justify-center gap-4 px-6 text-center">
        <p className="font-body">Couldn't load the breach simulation right now.</p>
        <Link to="/register" className="px-6 py-3 bg-phosphor text-void font-bold rounded text-sm">
          Skip to sign up free
        </Link>
      </div>
    );
  }

  const minutes = Math.floor(secondsLeft / 60);
  const seconds = secondsLeft % 60;
  const clockLabel = `${minutes}:${seconds.toString().padStart(2, "0")}`;

  return (
    <div className="min-h-screen bg-void text-gray-100 font-body">
      {/* ── Nav — enterprise links stay reachable from the teaser too ── */}
      <nav className="border-b border-white/10 bg-void/90 backdrop-blur-md sticky top-0 z-50">
        <div className="max-w-3xl mx-auto px-4 h-14 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="text-bleed font-display font-bold text-base tracking-widest">BREACH</span>
            <span className="text-white font-display font-bold text-base tracking-widest">REPLAY</span>
          </div>
          <div className="flex items-center gap-4 text-xs">
            <button onClick={scrollToPricing} className="text-dim hover:text-white transition-colors">
              Pricing
            </button>
            <Link to="/security" className="text-dim hover:text-white transition-colors hidden sm:inline">
              Security
            </Link>
            <Link to="/login" className="text-dim hover:text-white transition-colors">
              Sign in
            </Link>
          </div>
        </div>
      </nav>

      {/* ── Teaser hero ──────────────────────────────────────── */}
      <section className="pt-8 pb-6 px-4 max-w-3xl mx-auto text-center">
        <h1 className="font-display text-2xl sm:text-4xl font-bold leading-tight mb-4 text-white">
          {payload.headline}
        </h1>
        {phase === "playing" && (
          <div className="font-term text-phosphor text-3xl font-bold tabular-nums" aria-live="polite">
            {clockLabel}
          </div>
        )}
      </section>

      {/* ── Network map — the input, not a button list ──────────── */}
      <section className="px-4 max-w-3xl mx-auto mb-4">
        <div className="bg-panel border border-white/10 rounded-lg p-3">
          <NetworkMap
            nodes={payload.nodes}
            edges={payload.edges}
            nodeStates={nodeStates}
            clickableNodeIds={phase === "playing" ? payload.decision.node_choices : []}
            onNodeClick={handleAnswer}
            className="w-full h-auto max-h-[320px]"
          />
        </div>
      </section>

      {/* ── Alert feed ───────────────────────────────────────── */}
      <section className="px-4 max-w-xl mx-auto mb-6">
        <div className="font-term text-xs space-y-1.5 bg-panel/50 border border-white/5 rounded-lg p-3">
          {payload.alert_lines.map((line, i) => {
            const shown = line.text.slice(0, visibleAlertChars[`${line.timestamp}-${i}`] ?? 0);
            if (!shown) return null;
            return (
              <div key={line.timestamp}>
                <span className="text-dim">[{line.timestamp}]</span>{" "}
                <span className="text-gray-300">{shown}</span>
              </div>
            );
          })}
        </div>
      </section>

      {/* ── Decision gate ────────────────────────────────────── */}
      {phase === "playing" && (
        <section className="px-4 max-w-xl mx-auto mb-10 text-center">
          <div className="bg-bleed/10 border border-bleed/40 rounded-lg p-4">
            <p className="font-term text-xs text-bleed font-bold mb-1 tracking-wide">⚡ DECISION GATE</p>
            <p className="text-sm text-gray-200">{payload.decision.trigger_alert}</p>
            <p className="text-xs text-dim mt-2">Tap a host on the map to isolate it.</p>
          </div>
        </section>
      )}

      {/* ── End card ─────────────────────────────────────────── */}
      {phase === "resolved" && (
        <section className="px-4 max-w-xl mx-auto mb-16 text-center">
          <div
            className={`rounded-lg p-5 border ${
              wasCorrect ? "border-contain/40 bg-contain/10" : "border-bleed/40 bg-bleed/10"
            }`}
          >
            <p
              className={`font-display text-lg font-bold mb-2 ${wasCorrect ? "text-contain" : "text-bleed"}`}
            >
              {wasCorrect ? "CONTAINED" : "BREACH SPREADING"}
            </p>
            <p className="text-sm text-gray-200 mb-4">{consequenceText}</p>
            <p className="text-sm text-dim mb-6">{endCardText}</p>
            <button
              onClick={handleSignup}
              className="px-8 py-3 bg-phosphor hover:bg-amber-400 text-void font-bold rounded text-sm tracking-wide transition-colors"
            >
              PLAY THE FULL BREACH FREE
            </button>
          </div>
        </section>
      )}

      <LandingPageMarketing />
    </div>
  );
}
