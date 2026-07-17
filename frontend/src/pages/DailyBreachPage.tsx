import { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { axiosInstance } from "../lib/api";
import XPToast from "../components/XPToast";
import ActionConsole from "../components/ActionConsole";
import type { RunEndSummary } from "../lib/useRunSocket";

// ── Daily Drill (spaced repetition on weak techniques) ──────────────────────
interface KnowledgeCheckQuestion {
  id: string;
  scenario_id: string | null;
  technique_id: string | null;
  nist_control_ref: string | null;
  question: string;
  options: string[];
}

interface KnowledgeCheckAttemptResult {
  is_correct: boolean;
  correct_index: number;
  explanation: string;
}

function DailyDrillSection() {
  const [selected, setSelected] = useState<number | null>(null);
  const [result, setResult] = useState<KnowledgeCheckAttemptResult | null>(null);

  const { data: check, isLoading, isError, refetch } = useQuery<KnowledgeCheckQuestion>({
    queryKey: ["knowledge-check-next"],
    queryFn: () => axiosInstance.get("/learning/knowledge-check/next").then((r) => r.data),
    retry: false,
  });

  const attemptMutation = useMutation({
    mutationFn: (chosen_index: number) =>
      axiosInstance
        .post(`/learning/knowledge-check/${check!.id}/attempt`, { chosen_index })
        .then((r) => r.data as KnowledgeCheckAttemptResult),
    onSuccess: (data) => setResult(data),
  });

  const handleSelect = (idx: number) => {
    if (result || attemptMutation.isPending) return;
    setSelected(idx);
    attemptMutation.mutate(idx);
  };

  const handleNext = () => {
    setSelected(null);
    setResult(null);
    refetch();
  };

  if (isError) return null;

  return (
    <div className="border border-gray-800 rounded-xl p-5 bg-gray-900/30 space-y-3">
      <div className="flex items-center justify-between">
        <div className="text-xs text-gray-500 uppercase tracking-widest">🎯 Daily Drill</div>
        <div className="text-[10px] text-gray-600">Spaced repetition on your weakest techniques</div>
      </div>

      {isLoading && <p className="text-xs text-gray-600">Loading a drill question...</p>}

      {check && !result && (
        <>
          <p className="text-sm text-gray-300 leading-relaxed">{check.question}</p>
          <div className="space-y-2">
            {check.options.map((opt, i) => (
              <button
                key={i}
                onClick={() => handleSelect(i)}
                disabled={attemptMutation.isPending}
                className={`w-full text-left px-3 py-2 rounded-lg border text-xs transition-colors ${
                  selected === i
                    ? "border-cyan-500/60 bg-cyan-500/10 text-cyan-200"
                    : "border-gray-700 hover:border-cyan-600/50 hover:bg-cyan-500/5 text-gray-300"
                }`}
              >
                <span className="inline-block w-5 h-5 rounded-full border border-gray-600 text-center text-[10px] leading-5 mr-2 font-bold">
                  {String.fromCharCode(65 + i)}
                </span>
                {opt}
              </button>
            ))}
          </div>
        </>
      )}

      {check && result && (
        <div
          className={`rounded-lg p-3 border ${
            result.is_correct ? "border-green-700/50 bg-green-950/30" : "border-red-700/50 bg-red-950/30"
          }`}
        >
          <p
            className={`text-xs font-bold uppercase tracking-widest mb-2 ${
              result.is_correct ? "text-green-400" : "text-red-400"
            }`}
          >
            {result.is_correct ? "✓ Correct" : "✗ Not quite"}
          </p>
          <p className="text-xs text-gray-300 leading-relaxed">{result.explanation}</p>
          <button
            onClick={handleNext}
            className="mt-3 w-full py-2 rounded-lg bg-cyan-600 hover:bg-cyan-500 text-black text-xs font-bold uppercase tracking-widest transition-colors"
          >
            Next Question
          </button>
        </div>
      )}
    </div>
  );
}

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
  // Set instead of (never alongside) my_attempt when today's challenge was
  // completed through the action console — a read-only RunEndSummary
  // reconstruction from the persisted ActionRun row, built fresh on every
  // /daily/today load (see backend's _reconstruct_daily_action_attempt).
  // xp_awarded/new_achievements are always 0/[] here — that celebration
  // already played once, live, at the run's actual completion.
  my_action_attempt: RunEndSummary | null;
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

// Action mode's own leaderboard — GET /daily/action-leaderboard/{id},
// ranked by action_runs.total_score. A DIFFERENT scale/table from the
// decision-gate LeaderboardEntry above (daily.py's own module docstring:
// "score on different scales and are never ranked against each other") —
// never mixed with it.
interface ActionLeaderboardEntry {
  rank: number;
  user_id: string;
  display_name: string;
  total_score: number;
  outcome: string;
  duration_seconds: number;
}

interface StreakData {
  current_streak: number;
  longest_streak: number;
  total_dailies_played: number;
  last_played_date: string | null;
  played_today: boolean;
}

type GamePhase = "lobby" | "playing" | "results";

// ── Helpers ────────────────────────────────────────────────────────────────────
const DIFF_COLOR: Record<string, string> = {
  awareness: "text-green-400 border-green-400/30 bg-green-400/10",
  practitioner: "text-yellow-400 border-yellow-400/30 bg-yellow-400/10",
  expert: "text-red-400 border-red-400/30 bg-red-400/10",
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

// ── Action-mode results (Phase 2 Item 5) ─────────────────────────────────────
// Separate from ResultsPanel above (which stays untouched for the legacy
// decision-gate DailyAttempt shape — score_breakdown/outcome don't exist on
// that path) rather than forcing both scoring models through one component.

function ActionResultsPanel({
  summary,
  challenge,
  leaderboard,
  onShare,
}: {
  summary: RunEndSummary;
  challenge: DailyChallenge;
  leaderboard: ActionLeaderboardEntry[];
  onShare: () => void;
}) {
  const outcomeColor =
    summary.outcome === "win" ? "text-green-400" :
    summary.outcome === "partial" ? "text-yellow-400" : "text-red-400";

  const streak: StreakData = {
    current_streak: summary.current_streak ?? 0,
    longest_streak: summary.longest_streak ?? 0,
    total_dailies_played: summary.total_dailies_played ?? 0,
    last_played_date: null,
    played_today: true,
  };

  const sb = summary.score_breakdown;

  return (
    <div className="space-y-6">
      {/* Score hero */}
      <div className="text-center py-8 border border-gray-800 rounded-xl bg-gray-900/50">
        <div className="text-xs text-gray-500 uppercase tracking-widest mb-2">Daily #{challenge.challenge_number} Result</div>
        <div className="text-7xl font-black text-white mb-1">{sb.total_score.toLocaleString()}</div>
        <div className={`text-xl font-bold uppercase tracking-widest ${outcomeColor}`}>{summary.outcome}</div>
        {summary.rank !== undefined && (
          <div className="mt-4 text-gray-400 text-sm">
            You ranked <span className="text-white font-bold">#{summary.rank}</span> today
          </div>
        )}
      </div>

      {/* Score breakdown */}
      <div className="border border-gray-800 rounded-xl p-5 space-y-3 bg-gray-900/30">
        <div className="text-xs text-gray-500 uppercase tracking-widest mb-3">Score Breakdown</div>
        <ScoreBar label="Evidence" value={sb.evidence_points} max={Math.max(sb.evidence_points, sb.evidence_total * 100, 1)} color="bg-cyan-500" />
        <ScoreBar label="Speed Bonus" value={sb.speed_bonus} max={Math.max(sb.speed_bonus, 1)} color="bg-purple-500" />
        <ScoreBar label="Total" value={sb.total_score} max={Math.max(sb.total_score, sb.outcome_base + sb.evidence_total * 100, 1)} color="bg-green-500" />
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

      {/* Action-mode leaderboard */}
      <div className="border border-gray-800 rounded-xl overflow-hidden">
        <div className="px-5 py-3 bg-gray-900 border-b border-gray-800 flex items-center justify-between">
          <span className="text-xs text-gray-400 uppercase tracking-widest">Today's Leaderboard</span>
          <span className="text-xs text-gray-600">{summary.total_attempts_today ?? challenge.total_attempts} played</span>
        </div>
        <div className="divide-y divide-gray-800/50">
          {leaderboard.slice(0, 10).map((entry) => (
            <div key={entry.user_id} className={`flex items-center gap-3 px-5 py-3 ${entry.rank <= 3 ? "bg-yellow-500/5" : ""}`}>
              <div className={`w-7 text-center font-bold text-sm ${entry.rank === 1 ? "text-yellow-400" : entry.rank === 2 ? "text-gray-300" : entry.rank === 3 ? "text-orange-400" : "text-gray-600"}`}>
                {entry.rank === 1 ? "🥇" : entry.rank === 2 ? "🥈" : entry.rank === 3 ? "🥉" : `#${entry.rank}`}
              </div>
              <div className="flex-1 text-sm text-gray-300">{entry.display_name}</div>
              <div className="text-sm font-bold text-white">{entry.total_score.toLocaleString()}</div>
              <div className="text-xs text-gray-600 uppercase">{entry.outcome}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function buildActionModeShareCard(challenge: DailyChallenge, summary: RunEndSummary): string {
  const streakTxt = (summary.current_streak ?? 0) > 1 ? `🔥 ${summary.current_streak}-day streak` : "";
  return [
    `🔐 BreachReplay Daily #${challenge.challenge_number}`,
    challenge.scenario_title,
    `Score: ${summary.score_breakdown.total_score.toLocaleString()} — ${summary.outcome.toUpperCase()}`,
    streakTxt,
    "breachreplay.com/daily",
  ].filter(Boolean).join("\n");
}

// ── Page ───────────────────────────────────────────────────────────────────────

interface DailyActionRunOut {
  run_id: string;
  daily_challenge_id: string;
  challenge_number: number;
  scenario_id: string;
  seed: number;
  mode: string;
  cap_seconds: number;
  resumed: boolean;
}

export default function DailyBreachPage() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [gamePhase, setGamePhase] = useState<GamePhase>("lobby");
  const [runId, setRunId] = useState<string | null>(null);
  const [result, setResult] = useState<RunEndSummary | null>(null);
  const [copied, setCopied] = useState(false);
  const [midnightCountdown, setMidnightCountdown] = useState(getCountdownToMidnight());
  const [xpToast, setXpToast] = useState<{ xp: number; achievements: string[] } | null>(null);

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

  // Legacy decision-gate leaderboard — kept for the (increasingly rare)
  // pre-rework DailyAttempt branch below.
  const { data: leaderboard } = useQuery<LeaderboardEntry[]>({
    queryKey: ["daily-leaderboard", challenge?.id],
    queryFn: () => axiosInstance.get(`/daily/leaderboard/${challenge!.id}`).then((r) => r.data),
    enabled: !!challenge?.id,
  });

  // Action mode's own leaderboard — different scale, never merged with the
  // one above (daily.py's own module docstring: "score on different scales
  // and are never ranked against each other").
  const { data: actionLeaderboard } = useQuery<ActionLeaderboardEntry[]>({
    queryKey: ["daily-action-leaderboard", challenge?.id],
    queryFn: () => axiosInstance.get(`/daily/action-leaderboard/${challenge!.id}`).then((r) => r.data),
    enabled: !!challenge?.id,
  });

  const handleStartGame = async () => {
    if (!challenge) return;
    try {
      const res = await axiosInstance.post<DailyActionRunOut>("/daily/action-run", {});
      setRunId(res.data.run_id);
      setGamePhase("playing");
    } catch (err: any) {
      alert(err.message);
    }
  };

  const handleGameComplete = useCallback((summary: RunEndSummary) => {
    setResult(summary);
    setGamePhase("results");
    if (summary.xp_awarded > 0) {
      setXpToast({ xp: summary.xp_awarded, achievements: summary.new_achievements });
    }
    qc.invalidateQueries({ queryKey: ["daily-today"] });
    qc.invalidateQueries({ queryKey: ["daily-streak"] });
    qc.invalidateQueries({ queryKey: ["daily-action-leaderboard", challenge?.id] });
  }, [qc, challenge?.id]);

  const handleShare = useCallback(() => {
    if (!challenge || !result) return;
    navigator.clipboard.writeText(buildActionModeShareCard(challenge, result)).then(() => {
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

  // Playing phase gets the full-height action console — no lobby chrome
  // around it, matching ActionConsolePage's own layout.
  if (gamePhase === "playing" && runId) {
    return (
      <div className="h-screen flex flex-col bg-gray-950">
        <div className="border-b border-gray-800 px-4 py-2 flex items-center justify-between shrink-0">
          <span className="text-xs text-gray-600 uppercase tracking-widest">Daily Breach #{challenge.challenge_number}</span>
          <span className="text-xs text-gray-600">{challenge.scenario_title}</span>
        </div>
        <div className="flex-1 min-h-0">
          <ActionConsole runId={runId} onComplete={handleGameComplete} />
        </div>
      </div>
    );
  }

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
              <span className="text-xs text-gray-500">8 min compressed run</span>
            </div>
          </div>

          {/* Daily Drill — optional spaced-repetition knowledge check, independent of game state */}
          <DailyDrillSection />

          {gamePhase === "results" && result ? (
            <ActionResultsPanel
              summary={result}
              challenge={challenge}
              leaderboard={actionLeaderboard || []}
              onShare={handleShare}
            />
          ) : challenge.already_played && challenge.my_action_attempt ? (
            // Action-mode completion, discovered on page load/reload rather
            // than lived through this session (result/gamePhase reset on
            // every mount) — same panel, backend-reconstructed data instead
            // of the live run.end payload.
            <ActionResultsPanel
              summary={challenge.my_action_attempt}
              challenge={challenge}
              leaderboard={actionLeaderboard || []}
              onShare={() => {
                navigator.clipboard.writeText(buildActionModeShareCard(challenge, challenge.my_action_attempt!)).then(() => {
                  setCopied(true);
                  setTimeout(() => setCopied(false), 2500);
                });
              }}
            />
          ) : challenge.already_played && challenge.my_attempt ? (
            // Legacy decision-gate completion (DailyAttempt row) from
            // before this rework shipped — kept working, unmodified.
            <ResultsPanel
              attempt={challenge.my_attempt}
              challenge={challenge}
              leaderboard={leaderboard || []}
              streak={streak || { current_streak: 0, longest_streak: 0, total_dailies_played: 0, last_played_date: null, played_today: false }}
              onShare={() => {
                navigator.clipboard.writeText(challenge.my_attempt!.share_card).then(() => {
                  setCopied(true);
                  setTimeout(() => setCopied(false), 2500);
                });
              }}
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
                  You have <span className="text-white font-bold">8 minutes</span> to scan, investigate, and
                  contain today's breach — the network map starts empty until you scan it.
                  Every second counts. Every wrong call costs you.
                </div>
                {challenge.initial_access_vector && (
                  <div className="text-xs text-gray-600">
                    <span className="text-gray-500">Initial access: </span>{challenge.initial_access_vector}
                  </div>
                )}
                <div className="flex items-center gap-4 text-xs text-gray-600 pt-1">
                  <span>🌍 {challenge.total_attempts} analysts played today</span>
                  <span>⏱ Max 8 minutes</span>
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

              {/* Today's action-mode leaderboard preview */}
              {actionLeaderboard && actionLeaderboard.length > 0 && (
                <div className="border border-gray-800 rounded-xl overflow-hidden">
                  <div className="px-4 py-3 bg-gray-900 border-b border-gray-800 text-xs text-gray-500 uppercase tracking-widest">
                    Top Analysts Today
                  </div>
                  {actionLeaderboard.slice(0, 5).map((e) => (
                    <div key={e.user_id} className="flex items-center gap-3 px-4 py-2.5 border-b border-gray-800/50 last:border-0">
                      <span className="text-sm w-6">{e.rank === 1 ? "🥇" : e.rank === 2 ? "🥈" : e.rank === 3 ? "🥉" : `#${e.rank}`}</span>
                      <span className="flex-1 text-sm text-gray-400">{e.display_name}</span>
                      <span className="text-sm font-bold text-white">{e.total_score.toLocaleString()}</span>
                    </div>
                  ))}
                </div>
              )}
            </>
          )}
        </div>

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
            achievements={xpToast.achievements}
            onDone={() => setXpToast(null)}
          />
        )}
      </div>
    </div>
  );
}
