import { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { axiosInstance } from "../lib/api";
import XPToast from "../components/XPToast";

// ── Types ──────────────────────────────────────────────────────────────────────
interface DailyChallenge {
  id: string;
  challenge_number: number;
  challenge_date: string;
  scenario_id: string;
  scenario_title: string;
  scenario_difficulty: "awareness" | "practitioner" | "expert";
  scenario_industry: string | null;
  initial_access_vector: string | null;
  gates_count: number;
  total_attempts: number;
  already_played: boolean;
  my_attempt: {
    score: number;
    rank: number | null;
    decisions_correct: number;
    decisions_total: number;
    time_taken_seconds: number;
    share_card: string;
  } | null;
}

interface LeaderboardEntry {
  rank: number;
  user_id: string;
  display_name: string;
  score: number;
  decisions_correct: number;
  decisions_total: number;
  time_taken_seconds: number | null;
}

interface StreakData {
  current_streak: number;
  longest_streak: number;
  total_dailies_played: number;
  last_played_date: string | null;
  played_today: boolean;
}

interface ScenarioContent {
  challenge_id: string;
  challenge_number: number;
  scenario_id: string;
  title: string;
  difficulty: string;
  time_limit_seconds: number;
  alert_sequence: Alert[];
  decision_tree: Gate[];
  pressure_injections: PressureInjection[];
}

interface Alert {
  timestamp: string;
  severity: string;
  source_system: string;
  rule_id: string;
  description: string;
  raw_log: string;
}

interface Gate {
  id: string;
  trigger_timestamp: string;
  countdown_seconds: number;
  context_summary: string;
  options: { text: string; consequence_if_chosen: string }[];
  correct_index: number;
  rationale: string;
  nist_control_ref: string;
  mitre_technique: string;
}

interface PressureInjection {
  id: string;
  trigger_timestamp: string;
  type: string;
  from: string;
  subject: string;
  body: string;
  countdown_seconds: number;
}

type GamePhase = "lobby" | "briefing" | "playing" | "results";

// ── Helpers ────────────────────────────────────────────────────────────────────
const DIFF_COLOR: Record<string, string> = {
  awareness: "text-green-400 border-green-400/30 bg-green-400/10",
  practitioner: "text-yellow-400 border-yellow-400/30 bg-yellow-400/10",
  expert: "text-red-400 border-red-400/30 bg-red-400/10",
};

const SEVERITY_COLOR: Record<string, string> = {
  critical: "border-l-red-500 bg-red-500/5",
  high: "border-l-orange-500 bg-orange-500/5",
  medium: "border-l-yellow-500 bg-yellow-500/5",
  low: "border-l-blue-500 bg-blue-500/5",
};

function formatTime(seconds: number) {
  const m = Math.floor(seconds / 60).toString().padStart(2, "0");
  const s = (seconds % 60).toString().padStart(2, "0");
  return `${m}:${s}`;
}

function getCountdownToMidnight(): number {
  const now = new Date();
  const midnight = new Date();
  midnight.setUTCHours(24, 0, 0, 0);
  return Math.floor((midnight.getTime() - now.getTime()) / 1000);
}

// ── Sub-components ─────────────────────────────────────────────────────────────

function StreakBadge({ streak }: { streak: StreakData }) {
  return (
    <div className="flex items-center gap-4">
      <div className="text-center">
        <div className="text-2xl font-black text-orange-400">
          {streak.current_streak > 0 ? "🔥" : "💤"} {streak.current_streak}
        </div>
        <div className="text-xs text-gray-500 uppercase tracking-widest">day streak</div>
      </div>
      <div className="w-px h-10 bg-gray-700" />
      <div className="text-center">
        <div className="text-2xl font-black text-purple-400">{streak.longest_streak}</div>
        <div className="text-xs text-gray-500 uppercase tracking-widest">best streak</div>
      </div>
      <div className="w-px h-10 bg-gray-700" />
      <div className="text-center">
        <div className="text-2xl font-black text-cyan-400">{streak.total_dailies_played}</div>
        <div className="text-xs text-gray-500 uppercase tracking-widest">total played</div>
      </div>
    </div>
  );
}

function CountdownClock({ seconds }: { seconds: number }) {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  return (
    <span className="font-mono text-cyan-400">
      {String(h).padStart(2, "0")}:{String(m).padStart(2, "0")}:{String(s).padStart(2, "0")}
    </span>
  );
}

function ScoreBar({ label, value, max, color }: { label: string; value: number; max: number; color: string }) {
  const pct = Math.round((value / max) * 100);
  return (
    <div>
      <div className="flex justify-between text-xs text-gray-400 mb-1">
        <span>{label}</span>
        <span>{value.toLocaleString()} / {max.toLocaleString()}</span>
      </div>
      <div className="h-2 bg-gray-800 rounded-full overflow-hidden">
        <div className={`h-full rounded-full transition-all duration-1000 ${color}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function ResultsPanel({
  attempt,
  challenge,
  leaderboard,
  streak,
  onShare,
}: {
  attempt: NonNullable<DailyChallenge["my_attempt"]>;
  challenge: DailyChallenge;
  leaderboard: LeaderboardEntry[];
  streak: StreakData;
  onShare: () => void;
}) {
  const pct = Math.round((attempt.decisions_correct / attempt.decisions_total) * 100);
  const rating =
    pct === 100 ? "PERFECT" :
    pct >= 80 ? "EXCELLENT" :
    pct >= 60 ? "GOOD" :
    pct >= 40 ? "NEEDS WORK" : "CRITICAL GAPS";

  const ratingColor =
    pct === 100 ? "text-green-400" :
    pct >= 80 ? "text-cyan-400" :
    pct >= 60 ? "text-yellow-400" :
    pct >= 40 ? "text-orange-400" : "text-red-400";

  return (
    <div className="space-y-6">
      {/* Score hero */}
      <div className="text-center py-8 border border-gray-800 rounded-xl bg-gray-900/50">
        <div className="text-xs text-gray-500 uppercase tracking-widest mb-2">Daily #{challenge.challenge_number} Result</div>
        <div className="text-7xl font-black text-white mb-1">{attempt.score.toLocaleString()}</div>
        <div className={`text-xl font-bold uppercase tracking-widest ${ratingColor}`}>{rating}</div>
        {attempt.rank && (
          <div className="mt-4 text-gray-400 text-sm">
            You ranked <span className="text-white font-bold">#{attempt.rank}</span> globally
          </div>
        )}
        <div className="mt-2 text-gray-400 text-sm">
          {attempt.decisions_correct}/{attempt.decisions_total} correct ·{" "}
          {formatTime(attempt.time_taken_seconds)}
        </div>
      </div>

      {/* Score breakdown */}
      <div className="border border-gray-800 rounded-xl p-5 space-y-3 bg-gray-900/30">
        <div className="text-xs text-gray-500 uppercase tracking-widest mb-3">Score Breakdown</div>
        <ScoreBar label="Accuracy" value={attempt.decisions_correct * 100} max={attempt.decisions_total * 100} color="bg-cyan-500" />
        <ScoreBar label="Speed Bonus" value={attempt.score - attempt.decisions_correct * 100} max={attempt.decisions_total * 75} color="bg-purple-500" />
        <ScoreBar label="Total" value={attempt.score} max={1250} color="bg-green-500" />
      </div>

      {/* Streak */}
      <div className="border border-gray-800 rounded-xl p-5 bg-gray-900/30">
        <div className="text-xs text-gray-500 uppercase tracking-widest mb-4">Your Streak</div>
        <StreakBadge streak={streak} />
      </div>

      {/* Share */}
      <button
        onClick={onShare}
        className="w-full py-4 rounded-xl bg-gradient-to-r from-cyan-500 to-purple-600 hover:from-cyan-400 hover:to-purple-500 text-white font-bold text-lg transition-all active:scale-95"
      >
        📋 Copy Result & Share
      </button>

      {/* Leaderboard */}
      <div className="border border-gray-800 rounded-xl overflow-hidden">
        <div className="px-5 py-3 bg-gray-900 border-b border-gray-800 flex items-center justify-between">
          <span className="text-xs text-gray-400 uppercase tracking-widest">Today's Leaderboard</span>
          <span className="text-xs text-gray-600">{challenge.total_attempts} played</span>
        </div>
        <div className="divide-y divide-gray-800/50">
          {leaderboard.slice(0, 10).map((entry) => (
            <div key={entry.user_id} className={`flex items-center gap-3 px-5 py-3 ${entry.rank <= 3 ? "bg-yellow-500/5" : ""}`}>
              <div className={`w-7 text-center font-bold text-sm ${entry.rank === 1 ? "text-yellow-400" : entry.rank === 2 ? "text-gray-300" : entry.rank === 3 ? "text-orange-400" : "text-gray-600"}`}>
                {entry.rank === 1 ? "🥇" : entry.rank === 2 ? "🥈" : entry.rank === 3 ? "🥉" : `#${entry.rank}`}
              </div>
              <div className="flex-1 text-sm text-gray-300">{entry.display_name}</div>
              <div className="text-sm font-bold text-white">{entry.score.toLocaleString()}</div>
              <div className="text-xs text-gray-600">{entry.decisions_correct}/{entry.decisions_total}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ── Main Game Component ────────────────────────────────────────────────────────

function DailyGame({
  content,
  onComplete,
}: {
  content: ScenarioContent;
  onComplete: (decisions: any[], timeTaken: number) => void;
}) {
  const [phase, setPhase] = useState<"alerts" | "gate">("alerts");
  const [currentAlertIndex, setCurrentAlertIndex] = useState(0);
  const [currentGateIndex, setCurrentGateIndex] = useState(0);
  const [countdown, setCountdown] = useState(content.decision_tree[0]?.countdown_seconds || 60);
  const [totalTime, setTotalTime] = useState(0);
  const [decisions, setDecisions] = useState<any[]>([]);
  const [selectedOption, setSelectedOption] = useState<number | null>(null);
  const [showResult, setShowResult] = useState(false);
  const [activePressure, setActivePressure] = useState<PressureInjection | null>(null);
  const [shownPressures, setShownPressures] = useState<Set<string>>(new Set());
  const [choiceResult, setChoiceResult] = useState<{ correct: boolean; rationale: string; consequence: string } | null>(null);

  const gates = content.decision_tree;
  const alerts = content.alert_sequence;
  const pressures = content.pressure_injections;

  const currentGate = gates[currentGateIndex];

  // Global time counter
  useEffect(() => {
    const interval = setInterval(() => setTotalTime((t) => t + 1), 1000);
    return () => clearInterval(interval);
  }, []);

  // Pressure injection trigger
  useEffect(() => {
    if (!currentGate) return;
    pressures.forEach((p) => {
      if (!shownPressures.has(p.id) && p.trigger_timestamp === currentGate.trigger_timestamp) {
        setActivePressure(p);
        setShownPressures((s) => new Set([...s, p.id]));
        setTimeout(() => setActivePressure(null), 8000);
      }
    });
  }, [currentGateIndex, currentGate, pressures, shownPressures]);

  // Gate countdown
  useEffect(() => {
    if (phase !== "gate" || showResult) return;
    if (countdown <= 0) {
      handleChoice(-1); // time expired = wrong answer
      return;
    }
    const t = setTimeout(() => setCountdown((c) => c - 1), 1000);
    return () => clearTimeout(t);
  }, [countdown, phase, showResult]);

  // Move through alerts then go to gate
  useEffect(() => {
    if (phase !== "alerts") return;
    if (currentAlertIndex >= alerts.length) {
      setPhase("gate");
      return;
    }
    const delay = currentAlertIndex === 0 ? 600 : 1200;
    const t = setTimeout(() => setCurrentAlertIndex((i) => i + 1), delay);
    return () => clearTimeout(t);
  }, [currentAlertIndex, alerts.length, phase]);

  const handleChoice = useCallback((optionIndex: number) => {
    if (showResult || !currentGate) return;
    const start = currentGate.countdown_seconds - countdown;
    const responseTime = Math.max(1, start);
    const isCorrect = optionIndex === currentGate.correct_index;
    const consequence =
      optionIndex === -1
        ? "Time expired — decision made for you by default protocol."
        : isCorrect
        ? currentGate.options[optionIndex]?.consequence_if_chosen || ""
        : currentGate.options[optionIndex]?.consequence_if_chosen || "";

    setSelectedOption(optionIndex);
    setChoiceResult({ correct: isCorrect, rationale: currentGate.rationale, consequence });
    setShowResult(true);

    const newDecision = {
      gate_id: currentGate.id,
      chosen_index: optionIndex,
      correct_index: currentGate.correct_index,
      is_correct: isCorrect,
      response_time_seconds: responseTime,
    };

    const updatedDecisions = [...decisions, newDecision];
    setDecisions(updatedDecisions);

    setTimeout(() => {
      setShowResult(false);
      setSelectedOption(null);
      setChoiceResult(null);

      const nextGate = currentGateIndex + 1;
      if (nextGate >= gates.length) {
        onComplete(updatedDecisions, totalTime);
      } else {
        setCurrentGateIndex(nextGate);
        setCountdown(gates[nextGate].countdown_seconds);
        setPhase("alerts");
        setCurrentAlertIndex(0);
      }
    }, 3500);
  }, [showResult, currentGate, countdown, decisions, currentGateIndex, gates, totalTime, onComplete]);

  return (
    <div className="max-w-2xl mx-auto space-y-4">
      {/* Header bar */}
      <div className="flex items-center justify-between text-xs text-gray-500">
        <span>Gate {currentGateIndex + 1} / {gates.length}</span>
        <span className="font-mono text-gray-400">{formatTime(content.time_limit_seconds - totalTime)}</span>
        <span>{decisions.filter((d) => d.is_correct).length} correct</span>
      </div>
      <div className="h-1 bg-gray-800 rounded-full overflow-hidden">
        <div
          className="h-full bg-gradient-to-r from-cyan-500 to-purple-500 transition-all"
          style={{ width: `${((currentGateIndex) / gates.length) * 100}%` }}
        />
      </div>

      {/* Pressure injection overlay */}
      {activePressure && (
        <div className="border border-red-500/50 bg-red-500/10 rounded-xl p-4 animate-pulse">
          <div className="flex items-start gap-3">
            <span className="text-xl">{activePressure.type === "email" ? "📧" : activePressure.type === "call" ? "📞" : activePressure.type === "news" ? "📰" : "💬"}</span>
            <div className="flex-1 min-w-0">
              <div className="text-xs text-red-400 font-bold uppercase tracking-widest mb-1">INCOMING {activePressure.type.toUpperCase()}</div>
              <div className="text-sm text-gray-300 font-semibold">{activePressure.from}</div>
              {activePressure.subject && <div className="text-xs text-gray-400 mt-0.5">"{activePressure.subject}"</div>}
              <div className="text-xs text-gray-400 mt-1 line-clamp-2">{activePressure.body}</div>
            </div>
          </div>
        </div>
      )}

      {/* Alert feed */}
      {phase === "alerts" && (
        <div className="space-y-2">
          <div className="text-xs text-gray-600 uppercase tracking-widest">Incoming alerts</div>
          {alerts.slice(0, currentAlertIndex).map((alert, i) => (
            <div key={i} className={`border-l-2 px-3 py-2 rounded-r-lg text-xs ${SEVERITY_COLOR[alert.severity] || "border-l-gray-700 bg-gray-900/30"}`}>
              <div className="flex items-center gap-2 mb-1">
                <span className={`uppercase font-bold text-[10px] ${alert.severity === "critical" ? "text-red-400" : alert.severity === "high" ? "text-orange-400" : alert.severity === "medium" ? "text-yellow-400" : "text-blue-400"}`}>
                  {alert.severity}
                </span>
                <span className="text-gray-600">{alert.source_system}</span>
                <span className="text-gray-700 font-mono">{alert.timestamp}</span>
              </div>
              <div className="text-gray-300">{alert.description}</div>
              <div className="mt-1 font-mono text-[10px] text-gray-600 truncate">{alert.raw_log}</div>
            </div>
          ))}
        </div>
      )}

      {/* Decision gate */}
      {phase === "gate" && currentGate && !showResult && (
        <div className="border border-gray-700 rounded-xl overflow-hidden">
          {/* Countdown */}
          <div className={`px-4 py-2 flex items-center justify-between ${countdown <= 15 ? "bg-red-500/20 border-b border-red-500/30" : "bg-gray-900 border-b border-gray-800"}`}>
            <span className="text-xs text-gray-400 uppercase tracking-widest">Decide Now</span>
            <span className={`font-mono font-bold text-lg ${countdown <= 15 ? "text-red-400 animate-pulse" : countdown <= 30 ? "text-yellow-400" : "text-white"}`}>
              {formatTime(countdown)}
            </span>
          </div>

          {/* Situation */}
          <div className="p-4 border-b border-gray-800 bg-gray-900/50">
            <p className="text-sm text-gray-300 leading-relaxed">{currentGate.context_summary}</p>
          </div>

          {/* Options */}
          <div className="p-4 space-y-3">
            {currentGate.options.map((opt, i) => (
              <button
                key={i}
                onClick={() => handleChoice(i)}
                className="w-full text-left px-4 py-3 rounded-lg border border-gray-700 hover:border-cyan-500/50 hover:bg-cyan-500/5 text-sm text-gray-300 transition-all active:scale-[0.98] group"
              >
                <span className="inline-block w-6 h-6 rounded-full border border-gray-600 group-hover:border-cyan-500 text-center text-xs leading-6 mr-2 font-bold">
                  {String.fromCharCode(65 + i)}
                </span>
                {opt.text}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Result reveal */}
      {phase === "gate" && showResult && choiceResult && (
        <div className={`border rounded-xl p-5 ${choiceResult.correct ? "border-green-500/50 bg-green-500/10" : "border-red-500/50 bg-red-500/10"}`}>
          <div className={`text-lg font-bold mb-2 ${choiceResult.correct ? "text-green-400" : "text-red-400"}`}>
            {choiceResult.correct ? "✅ Correct Call" : "❌ Wrong Call"}
          </div>
          <p className="text-sm text-gray-300 mb-3">{choiceResult.consequence}</p>
          <div className="border-t border-gray-700 pt-3">
            <div className="text-xs text-gray-500 uppercase tracking-widest mb-1">NIST Rationale</div>
            <p className="text-xs text-gray-400">{choiceResult.rationale}</p>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Page ───────────────────────────────────────────────────────────────────────

export default function DailyBreachPage() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [gamePhase, setGamePhase] = useState<GamePhase>("lobby");
  const [scenarioContent, setScenarioContent] = useState<ScenarioContent | null>(null);
  const [result, setResult] = useState<any>(null);
  const [copied, setCopied] = useState(false);
  const [midnightCountdown, setMidnightCountdown] = useState(getCountdownToMidnight());
  const [xpToast, setXpToast] = useState<{ xp: number; leveledUp: boolean; newTierLabel: string | null; achievements: string[] } | null>(null);

  // Countdown to next daily
  useEffect(() => {
    const t = setInterval(() => setMidnightCountdown(getCountdownToMidnight()), 1000);
    return () => clearInterval(t);
  }, []);

  const { data: challenge, isLoading } = useQuery<DailyChallenge>({
    queryKey: ["daily-today"],
    queryFn: () => axiosInstance.get("/daily/today").then((r) => r.data),
  });

  const { data: streak } = useQuery<StreakData>({
    queryKey: ["daily-streak"],
    queryFn: () => axiosInstance.get("/daily/streak").then((r) => r.data),
  });

  const { data: leaderboard } = useQuery<LeaderboardEntry[]>({
    queryKey: ["daily-leaderboard", challenge?.id],
    queryFn: () => axiosInstance.get(`/daily/leaderboard/${challenge!.id}`).then((r) => r.data),
    enabled: !!challenge?.id,
  });

  const submitMutation = useMutation({
    mutationFn: (payload: any) => axiosInstance.post("/daily/attempt", payload).then((r) => r.data),
    onSuccess: (data) => {
      setResult(data);
      setGamePhase("results");
      if (data.xp_earned) {
        setXpToast({
          xp: data.xp_earned,
          leveledUp: !!data.leveled_up,
          newTierLabel: data.new_tier?.label ?? null,
          achievements: data.new_achievements ?? [],
        });
      }
      qc.invalidateQueries({ queryKey: ["daily-today"] });
      qc.invalidateQueries({ queryKey: ["daily-streak"] });
      qc.invalidateQueries({ queryKey: ["daily-leaderboard", challenge?.id] });
    },
  });

  const handleStartGame = async () => {
    if (!challenge) return;
    const res = await axiosInstance.get(`/daily/scenario/${challenge.id}`);
    setScenarioContent(res.data);
    setGamePhase("playing");
  };

  const handleGameComplete = useCallback((decisions: any[], timeTaken: number) => {
    if (!challenge) return;
    submitMutation.mutate({
      daily_challenge_id: challenge.id,
      decisions,
      time_taken_seconds: timeTaken,
    });
  }, [challenge, submitMutation]);

  const handleShare = useCallback(() => {
    const card = result?.share_card || challenge?.my_attempt?.share_card || "";
    navigator.clipboard.writeText(card).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2500);
    });
  }, [result, challenge]);

  if (isLoading) {
    return (
      <div className="min-h-screen bg-gray-950 flex items-center justify-center">
        <div className="text-gray-600 text-sm">Loading today's breach...</div>
      </div>
    );
  }

  if (!challenge) {
    return (
      <div className="min-h-screen bg-gray-950 flex items-center justify-center">
        <div className="text-red-400 text-sm">Failed to load today's challenge.</div>
      </div>
    );
  }

  const myAttempt = result
    ? { ...challenge.my_attempt, score: result.score, rank: result.rank, decisions_correct: result.decisions_correct, decisions_total: result.decisions_total, time_taken_seconds: result.time_taken_seconds, share_card: result.share_card }
    : challenge.my_attempt;

  const effectiveStreak: StreakData = result
    ? { current_streak: result.current_streak, longest_streak: result.longest_streak, total_dailies_played: result.total_dailies_played, last_played_date: null, played_today: true }
    : streak || { current_streak: 0, longest_streak: 0, total_dailies_played: 0, last_played_date: null, played_today: false };

  return (
    <div className="min-h-screen bg-gray-950 text-white">
      {/* Top nav */}
      <div className="border-b border-gray-800 px-4 py-3 flex items-center justify-between">
        <button onClick={() => navigate("/scenarios")} className="text-gray-500 hover:text-gray-300 text-sm transition-colors">
          ← Back
        </button>
        <div className="text-xs text-gray-600 uppercase tracking-widest">BreachReplay Daily</div>
        <div className="text-xs text-gray-600">
          <CountdownClock seconds={midnightCountdown} /> until next
        </div>
      </div>

      <div className="max-w-2xl mx-auto px-4 py-8">
        {/* Playing phase */}
        {gamePhase === "playing" && scenarioContent && (
          <DailyGame content={scenarioContent} onComplete={handleGameComplete} />
        )}

        {/* Lobby / Results */}
        {(gamePhase === "lobby" || gamePhase === "results") && (
          <div className="space-y-6">
            {/* Challenge header */}
            <div className="text-center space-y-2">
              <div className="text-xs text-gray-600 uppercase tracking-[0.3em]">Daily Breach #{challenge.challenge_number}</div>
              <h1 className="text-3xl font-black text-white">{challenge.scenario_title}</h1>
              <div className="flex items-center justify-center gap-3 flex-wrap">
                <span className={`text-xs px-2 py-1 rounded border font-bold uppercase ${DIFF_COLOR[challenge.scenario_difficulty]}`}>
                  {challenge.scenario_difficulty}
                </span>
                {challenge.scenario_industry && (
                  <span className="text-xs text-gray-500 border border-gray-800 px-2 py-1 rounded">
                    {challenge.scenario_industry.toUpperCase()}
                  </span>
                )}
                <span className="text-xs text-gray-500">{challenge.gates_count} decision gates · 10 min</span>
              </div>
            </div>

            {/* Already played — show results */}
            {(challenge.already_played || gamePhase === "results") && myAttempt ? (
              <ResultsPanel
                attempt={myAttempt as any}
                challenge={challenge}
                leaderboard={leaderboard || []}
                streak={effectiveStreak}
                onShare={handleShare}
              />
            ) : (
              <>
                {/* Streak */}
                {streak && (
                  <div className="border border-gray-800 rounded-xl p-5 bg-gray-900/30">
                    <div className="text-xs text-gray-500 uppercase tracking-widest mb-4">Your Stats</div>
                    <StreakBadge streak={streak} />
                  </div>
                )}

                {/* Challenge brief */}
                <div className="border border-gray-800 rounded-xl p-5 bg-gray-900/30 space-y-3">
                  <div className="text-xs text-gray-500 uppercase tracking-widest">Mission Brief</div>
                  <div className="text-sm text-gray-400 leading-relaxed">
                    You have <span className="text-white font-bold">10 minutes</span> and{" "}
                    <span className="text-white font-bold">{challenge.gates_count} decision gates</span> to respond to today's breach.
                    Every second counts. Every wrong call cascades.
                  </div>
                  {challenge.initial_access_vector && (
                    <div className="text-xs text-gray-600">
                      <span className="text-gray-500">Initial access: </span>{challenge.initial_access_vector}
                    </div>
                  )}
                  <div className="flex items-center gap-4 text-xs text-gray-600 pt-1">
                    <span>🌍 {challenge.total_attempts} analysts played today</span>
                    <span>⏱ Max 10 minutes</span>
                    <span>🎯 One shot</span>
                  </div>
                </div>

                {/* CTA */}
                <button
                  onClick={handleStartGame}
                  className="w-full py-5 rounded-xl bg-gradient-to-r from-red-600 to-orange-500 hover:from-red-500 hover:to-orange-400 text-white font-black text-xl tracking-wide transition-all active:scale-95 shadow-lg shadow-red-900/30"
                >
                  🚨 RESPOND NOW
                </button>

                <p className="text-center text-xs text-gray-700">
                  You get one attempt. Results are permanent. New breach drops at midnight UTC.
                </p>

                {/* Today's leaderboard preview */}
                {leaderboard && leaderboard.length > 0 && (
                  <div className="border border-gray-800 rounded-xl overflow-hidden">
                    <div className="px-4 py-3 bg-gray-900 border-b border-gray-800 text-xs text-gray-500 uppercase tracking-widest">
                      Top Analysts Today
                    </div>
                    {leaderboard.slice(0, 5).map((e) => (
                      <div key={e.user_id} className="flex items-center gap-3 px-4 py-2.5 border-b border-gray-800/50 last:border-0">
                        <span className="text-sm w-6">{e.rank === 1 ? "🥇" : e.rank === 2 ? "🥈" : e.rank === 3 ? "🥉" : `#${e.rank}`}</span>
                        <span className="flex-1 text-sm text-gray-400">{e.display_name}</span>
                        <span className="text-sm font-bold text-white">{e.score.toLocaleString()}</span>
                      </div>
                    ))}
                  </div>
                )}
              </>
            )}
          </div>
        )}

        {/* Copy toast */}
        {copied && (
          <div className="fixed bottom-6 left-1/2 -translate-x-1/2 bg-green-500 text-black font-bold px-6 py-3 rounded-full text-sm shadow-lg">
            ✓ Copied to clipboard
          </div>
        )}

        {/* XP toast */}
        {xpToast && (
          <XPToast
            xp={xpToast.xp}
            leveledUp={xpToast.leveledUp}
            newTierLabel={xpToast.newTierLabel ?? undefined}
            achievements={xpToast.achievements}
            onDone={() => setXpToast(null)}
          />
        )}
      </div>
    </div>
  );
}
