import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery, useMutation } from "@tanstack/react-query";
import { axiosInstance } from "../lib/api";
import XPToast from "../components/XPToast";

// ── Types ──────────────────────────────────────────────────────────────────────
interface Scenario {
  id: string;
  title: string;
  difficulty: string;
  industry_vertical: string | null;
  initial_access_vector: string | null;
  mitre_techniques: string[];
  description: string | null;
}

interface Move {
  tactic: string;
  technique_id: string;
  tool: string;
  description: string;
  stealth: number;
  impact: number;
  detection_risk: number;
  success_consequence: string;
  fail_consequence: string;
}

interface MoveResult {
  move_number: number;
  tactic: string;
  technique_id: string;
  tool: string;
  succeeded: boolean;
  detected: boolean;
  consequence: string;
  blue_team_response: string;
  stealth_score: number;
  stealth_delta: number;
  impact_score: number;
  impact_delta: number;
  phases_completed: string[];
  current_phase: string;
  suggested_next_phase: string;
  available_moves: Move[];
  session_status: string;
  outcome_message: string;
  final_score: number | null;
  xp_earned?: number;
  leveled_up?: boolean;
  new_tier?: { label: string };
  new_achievements?: string[];
  environment_state?: Record<string, boolean | string>;
}

interface Session {
  session_id: string;
  scenario_title: string;
  scenario_difficulty: string;
  initial_access_vector: string;
  mitre_techniques: string[];
  current_phase: string;
  stealth_score: number;
  impact_score: number;
  available_moves: Move[];
  objective: string;
  intel_brief: string;
  environment_state?: Record<string, boolean | string>;
}

// Human-readable labels for facts a Discovery move can reveal — keeps the raw
// backend keys (e.g. "unpatched_smb") out of the player-facing Intel panel.
const ENV_FACT_LABELS: Record<string, string> = {
  network_mapped: "Network topology mapped",
  unpatched_smb: "Unpatched SMB service found (MS17-010)",
  unpatched_print_spooler: "Unpatched Print Spooler found (CVE-2021-34527)",
  ad_path_mapped: "AD attack path mapped",
  protected_users_enabled: "Protected Users group status known",
};

type PageState = "selector" | "briefing" | "playing" | "endscreen";

const PHASE_LABELS: Record<string, string> = {
  initial_access: "Initial Access",
  execution: "Execution",
  persistence: "Persistence",
  privilege_escalation: "Privilege Escalation",
  defense_evasion: "Defense Evasion",
  credential_access: "Credential Access",
  discovery: "Discovery",
  lateral_movement: "Lateral Movement",
  collection: "Collection",
  exfiltration: "Exfiltration",
  impact: "Impact",
};

const PHASE_ORDER = Object.keys(PHASE_LABELS);

const DIFF_COLOR: Record<string, string> = {
  awareness: "text-green-400 border-green-400/30 bg-green-400/10",
  practitioner: "text-yellow-400 border-yellow-400/30 bg-yellow-400/10",
  expert: "text-red-400 border-red-400/30 bg-red-400/10",
};

// ── Sub-components ─────────────────────────────────────────────────────────────

function StealthBar({ value }: { value: number }) {
  const color = value > 60 ? "bg-green-500" : value > 30 ? "bg-yellow-500" : "bg-red-500";
  return (
    <div>
      <div className="flex justify-between text-xs mb-1">
        <span className="text-gray-500 uppercase tracking-widest">Stealth</span>
        <span className={value > 60 ? "text-green-400" : value > 30 ? "text-yellow-400" : "text-red-400 animate-pulse font-bold"}>
          {value}/100
        </span>
      </div>
      <div className="h-2 bg-gray-800 rounded-full overflow-hidden">
        <div className={`h-full rounded-full transition-all duration-700 ${color}`} style={{ width: `${value}%` }} />
      </div>
    </div>
  );
}

function ImpactBar({ value }: { value: number }) {
  return (
    <div>
      <div className="flex justify-between text-xs mb-1">
        <span className="text-gray-500 uppercase tracking-widest">Impact</span>
        <span className="text-purple-400">{value}/100</span>
      </div>
      <div className="h-2 bg-gray-800 rounded-full overflow-hidden">
        <div className="h-full rounded-full bg-purple-500 transition-all duration-700" style={{ width: `${value}%` }} />
      </div>
    </div>
  );
}

function KillChain({ phases, current }: { phases: string[]; current: string }) {
  return (
    <div className="flex gap-1 flex-wrap">
      {PHASE_ORDER.map((p) => {
        const done = phases.includes(p);
        const active = p === current;
        return (
          <div
            key={p}
            className={`text-[10px] px-2 py-0.5 rounded border font-mono transition-all ${
              done
                ? "border-purple-500/50 bg-purple-500/20 text-purple-300"
                : active
                ? "border-red-500 bg-red-500/20 text-red-300 animate-pulse"
                : "border-gray-800 text-gray-700"
            }`}
          >
            {PHASE_LABELS[p]?.split(" ")[0]}
          </div>
        );
      })}
    </div>
  );
}

function IntelPanel({ facts }: { facts: Record<string, boolean | string> }) {
  const keys = Object.keys(facts);
  return (
    <div>
      <div className="text-xs text-gray-600 uppercase tracking-widest mb-2">Intel Gathered</div>
      {keys.length === 0 ? (
        <p className="text-[11px] text-gray-700">
          Nothing confirmed yet — run Discovery moves to learn facts about the target that unlock later moves.
        </p>
      ) : (
        <div className="space-y-1">
          {keys.map((k) => (
            <div key={k} className="flex items-start gap-1.5 text-[11px] text-gray-400">
              <span className="text-green-500">✓</span>
              <span>{ENV_FACT_LABELS[k] || k}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function MoveCard({ move, onExecute, executing }: { move: Move; onExecute: () => void; executing: boolean }) {
  const [expanded, setExpanded] = useState(false);
  const detectionPct = Math.round(move.detection_risk * 100);

  return (
    <div className="border border-gray-800 rounded-xl overflow-hidden hover:border-gray-600 transition-colors group">
      <div
        className="p-4 cursor-pointer"
        onClick={() => setExpanded(!expanded)}
      >
        <div className="flex items-start gap-3">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-1 flex-wrap">
              <span className="text-sm font-bold text-white">{move.tactic}</span>
              <span className="text-[10px] font-mono text-gray-600 border border-gray-800 px-1 rounded">{move.technique_id}</span>
            </div>
            <div className="text-xs text-gray-500 mb-2">{move.tool}</div>
            <p className="text-xs text-gray-400 leading-relaxed">{move.description}</p>
          </div>
        </div>

        {/* Stats row */}
        <div className="flex items-center gap-4 mt-3 text-xs">
          <div className="flex items-center gap-1">
            <span className="text-gray-600">Stealth:</span>
            <span className={`font-bold ${move.stealth >= 8 ? "text-green-400" : move.stealth >= 5 ? "text-yellow-400" : "text-red-400"}`}>
              {move.stealth}/10
            </span>
          </div>
          <div className="flex items-center gap-1">
            <span className="text-gray-600">Impact:</span>
            <span className={`font-bold ${move.impact >= 8 ? "text-purple-400" : "text-gray-300"}`}>{move.impact}/10</span>
          </div>
          <div className="flex items-center gap-1">
            <span className="text-gray-600">Detection risk:</span>
            <span className={`font-bold ${detectionPct >= 50 ? "text-red-400" : detectionPct >= 25 ? "text-yellow-400" : "text-green-400"}`}>
              {detectionPct}%
            </span>
          </div>
          <button
            className="ml-auto text-gray-600 group-hover:text-gray-400 transition-colors"
            onClick={(e) => { e.stopPropagation(); setExpanded(!expanded); }}
          >
            {expanded ? "▲" : "▼"}
          </button>
        </div>
      </div>

      {/* Expanded details */}
      {expanded && (
        <div className="border-t border-gray-800 px-4 pb-4 pt-3 space-y-2 bg-gray-900/50">
          <div className="text-[11px]">
            <span className="text-green-500 font-bold">✓ If succeeds: </span>
            <span className="text-gray-400">{move.success_consequence}</span>
          </div>
          <div className="text-[11px]">
            <span className="text-red-500 font-bold">✗ If fails: </span>
            <span className="text-gray-400">{move.fail_consequence}</span>
          </div>
        </div>
      )}

      {/* Execute button */}
      <div className="border-t border-gray-800 px-4 py-3 bg-gray-900/30">
        <button
          onClick={(e) => { e.stopPropagation(); onExecute(); }}
          disabled={executing}
          className="w-full py-2 rounded-lg bg-red-600/80 hover:bg-red-600 disabled:opacity-50 disabled:cursor-not-allowed text-white text-xs font-bold uppercase tracking-wider transition-all active:scale-[0.98]"
        >
          {executing ? "Executing..." : `⚡ Execute — ${move.tactic}`}
        </button>
      </div>
    </div>
  );
}

function MoveResultPanel({ result, onContinue }: { result: MoveResult; onContinue: () => void }) {
  return (
    <div className={`border rounded-xl overflow-hidden ${result.session_status === "caught" ? "border-red-500/50" : result.session_status === "success" ? "border-green-500/50" : result.succeeded ? "border-purple-500/50" : "border-orange-500/50"}`}>
      {/* Status header */}
      <div className={`px-5 py-4 ${result.session_status === "caught" ? "bg-red-500/15" : result.session_status === "success" ? "bg-green-500/15" : result.succeeded ? "bg-purple-500/10" : "bg-orange-500/10"}`}>
        <div className="flex items-center gap-3">
          <span className="text-2xl">
            {result.session_status === "caught" ? "🚨" : result.session_status === "success" ? "🏆" : result.succeeded ? "✅" : "❌"}
          </span>
          <div>
            <div className={`font-black text-lg ${result.session_status === "caught" ? "text-red-400" : result.session_status === "success" ? "text-green-400" : result.succeeded ? "text-purple-300" : "text-orange-300"}`}>
              {result.session_status === "caught"
                ? "OPERATION BURNED"
                : result.session_status === "success"
                ? "MISSION COMPLETE"
                : result.succeeded
                ? "MOVE SUCCEEDED"
                : "MOVE FAILED"}
            </div>
            <div className="text-xs text-gray-500">{result.tactic} · {result.technique_id}</div>
          </div>
        </div>
      </div>

      <div className="p-5 space-y-4">
        {/* Consequence */}
        <div>
          <div className="text-xs text-gray-600 uppercase tracking-widest mb-1">Outcome</div>
          <p className="text-sm text-gray-300">{result.consequence}</p>
        </div>

        {/* Blue team response */}
        {result.detected && (
          <div className="border border-red-500/30 bg-red-500/5 rounded-lg p-3">
            <div className="text-xs text-red-500 uppercase tracking-widest mb-1 font-bold">🔵 Blue Team Response</div>
            <p className="text-sm text-gray-300">{result.blue_team_response}</p>
          </div>
        )}
        {!result.detected && (
          <div className="border border-green-500/20 bg-green-500/5 rounded-lg p-3">
            <div className="text-xs text-green-500 uppercase tracking-widest mb-1">🔵 Blue Team</div>
            <p className="text-sm text-gray-400">{result.blue_team_response}</p>
          </div>
        )}

        {/* Score deltas */}
        <div className="flex gap-4">
          <div className="flex-1 text-center border border-gray-800 rounded-lg p-3">
            <div className="text-xs text-gray-500 mb-1">Stealth</div>
            <div className={`text-xl font-bold ${result.stealth_delta < 0 ? "text-red-400" : "text-green-400"}`}>
              {result.stealth_delta > 0 ? "+" : ""}{result.stealth_delta}
            </div>
            <div className="text-xs text-gray-600">{result.stealth_score}/100 remaining</div>
          </div>
          <div className="flex-1 text-center border border-gray-800 rounded-lg p-3">
            <div className="text-xs text-gray-500 mb-1">Impact</div>
            <div className={`text-xl font-bold ${result.impact_delta > 0 ? "text-purple-400" : "text-gray-600"}`}>
              {result.impact_delta > 0 ? "+" : ""}{result.impact_delta}
            </div>
            <div className="text-xs text-gray-600">{result.impact_score}/100 total</div>
          </div>
        </div>

        {/* End game */}
        {result.outcome_message && (
          <div className="border border-gray-700 rounded-lg p-4 text-center">
            <p className="text-sm text-gray-300 mb-2">{result.outcome_message}</p>
            {result.final_score != null && (
              <div className="text-4xl font-black text-white">{result.final_score.toLocaleString()} pts</div>
            )}
          </div>
        )}

        <button
          onClick={onContinue}
          className="w-full py-3 rounded-lg bg-gray-800 hover:bg-gray-700 text-white text-sm font-bold transition-all"
        >
          {result.session_status !== "active" ? "View Summary" : "Continue Attack →"}
        </button>
      </div>
    </div>
  );
}

// ── Page ───────────────────────────────────────────────────────────────────────

export default function RedTeamPage() {
  const navigate = useNavigate();
  const [pageState, setPageState] = useState<PageState>("selector");
  const [session, setSession] = useState<Session | null>(null);
  const [currentPhase, setCurrentPhase] = useState("initial_access");
  const [phasesCompleted, setPhasesCompleted] = useState<string[]>([]);
  const [stealthScore, setStealthScore] = useState(100);
  const [impactScore, setImpactScore] = useState(0);
  const [availableMoves, setAvailableMoves] = useState<Move[]>([]);
  const [executingMove, setExecutingMove] = useState<string | null>(null);
  const [lastResult, setLastResult] = useState<MoveResult | null>(null);
  const [sessionStatus, setSessionStatus] = useState("active");
  const [moveLog, setMoveLog] = useState<MoveResult[]>([]);
  const [blueAlerts, setBlueAlerts] = useState<string[]>([]);
  const [xpToast, setXpToast] = useState<{ xp: number; leveledUp: boolean; newTierLabel: string | null; achievements: string[] } | null>(null);
  const [moveError, setMoveError] = useState<string | null>(null);
  const [environmentState, setEnvironmentState] = useState<Record<string, boolean | string>>({});

  const { data: scenarios, isLoading } = useQuery<Scenario[]>({
    queryKey: ["redteam-scenarios"],
    queryFn: () => axiosInstance.get("/redteam/scenarios").then((r) => r.data),
  });

  const startMutation = useMutation({
    mutationFn: (scenario_id: string) =>
      axiosInstance.post("/redteam/sessions", { scenario_id }).then((r) => r.data),
    onSuccess: (data) => {
      setSession(data);
      setAvailableMoves(data.available_moves || []);
      setCurrentPhase(data.current_phase);
      setEnvironmentState(data.environment_state || {});
      setPageState("briefing");
    },
  });

  const moveMutation = useMutation({
    mutationFn: ({ tactic, phase }: { tactic: string; phase: string }) =>
      axiosInstance
        .post(`/redteam/sessions/${session!.session_id}/move`, {
          session_id: session!.session_id,
          phase,
          tactic,
        })
        .then((r) => r.data),
    onSuccess: (data: MoveResult) => {
      setExecutingMove(null);
      setMoveError(null);
      setLastResult(data);
      setStealthScore(data.stealth_score);
      setImpactScore(data.impact_score);
      setPhasesCompleted(data.phases_completed);
      setCurrentPhase(data.current_phase);
      setEnvironmentState(data.environment_state || {});
      setMoveLog((prev) => [...prev, data]);
      if (data.detected) {
        setBlueAlerts((prev) => [...prev, data.blue_team_response]);
      }
      if (data.session_status !== "active") {
        setSessionStatus(data.session_status);
        if (data.xp_earned) {
          setXpToast({
            xp: data.xp_earned,
            leveledUp: !!data.leveled_up,
            newTierLabel: data.new_tier?.label ?? null,
            achievements: data.new_achievements ?? [],
          });
        }
      }
    },
    onError: (err: Error) => {
      setExecutingMove(null);
      setMoveError(err.message || "Move failed — try again.");
    },
  });

  const handleExecuteMove = (move: Move) => {
    if (!session || executingMove) return;
    setMoveError(null);
    setExecutingMove(move.tactic);
    moveMutation.mutate({ tactic: move.tactic, phase: currentPhase });
  };

  const handleContinueAfterResult = () => {
    if (!lastResult) return;
    if (lastResult.session_status !== "active") {
      setPageState("endscreen");
    } else {
      setCurrentPhase(lastResult.suggested_next_phase || lastResult.current_phase);
      setAvailableMoves(lastResult.available_moves || []);
      setLastResult(null);
    }
  };

  // Phase nav
  const handleSwitchPhase = (phase: string) => {
    if (lastResult) return;
    setCurrentPhase(phase);
    axiosInstance.get(`/redteam/sessions/${session!.session_id}`).then((r) => {
      const moves = r.data.available_moves || [];
      setEnvironmentState(r.data.environment_state || {});
      // Filter by phase from backend response - re-fetch
      axiosInstance.get("/redteam/scenarios").then(() => {
        // available moves are phase-specific; use what backend said
        setAvailableMoves(moves);
      });
    });
  };

  if (isLoading) {
    return (
      <div className="min-h-screen bg-gray-950 flex items-center justify-center">
        <div className="text-gray-600 text-sm">Loading scenarios...</div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-950 text-white">
      {/* Nav */}
      <div className="border-b border-gray-800 px-4 py-3 flex items-center justify-between">
        <button onClick={() => navigate("/scenarios")} className="text-gray-500 hover:text-gray-300 text-sm transition-colors">
          ← Back
        </button>
        <div className="text-xs text-red-500 uppercase tracking-[0.3em] font-bold">⚠ Red Team Mode</div>
        <div className="text-xs text-gray-700">Attack Simulation</div>
      </div>

      {/* SCENARIO SELECTOR */}
      {pageState === "selector" && (
        <div className="max-w-3xl mx-auto px-4 py-10">
          <div className="text-center mb-10">
            <div className="text-5xl mb-4">🔴</div>
            <h1 className="text-4xl font-black text-white mb-3">Red Team Mode</h1>
            <p className="text-gray-400 text-lg max-w-xl mx-auto">
              Switch sides. Play the attacker. Choose your target, select your TTPs, and execute the breach — while a live blue team AI responds to every move you make.
            </p>
          </div>

          <div className="grid gap-4">
            {(scenarios || []).map((s) => (
              <div
                key={s.id}
                className="border border-gray-800 rounded-xl p-5 hover:border-red-500/40 transition-all cursor-pointer group"
                onClick={() => startMutation.mutate(s.id)}
              >
                <div className="flex items-start gap-4">
                  <div className="flex-1">
                    <div className="flex items-center gap-3 mb-2 flex-wrap">
                      <h3 className="text-lg font-bold text-white group-hover:text-red-300 transition-colors">{s.title}</h3>
                      <span className={`text-xs px-2 py-0.5 rounded border font-bold uppercase ${DIFF_COLOR[s.difficulty] || DIFF_COLOR.practitioner}`}>
                        {s.difficulty}
                      </span>
                    </div>
                    {s.description && <p className="text-sm text-gray-500 mb-3 line-clamp-2">{s.description}</p>}
                    <div className="flex items-center gap-3 flex-wrap text-xs text-gray-600">
                      {s.industry_vertical && <span>🏭 {s.industry_vertical}</span>}
                      {s.initial_access_vector && <span>🎯 {s.initial_access_vector}</span>}
                      <span>🔧 {(s.mitre_techniques || []).slice(0, 4).join(" · ")}</span>
                    </div>
                  </div>
                  <div className="text-red-600 group-hover:text-red-400 transition-colors text-xl">▶</div>
                </div>
              </div>
            ))}
          </div>

          {startMutation.isPending && (
            <div className="text-center mt-6 text-gray-500 text-sm">Initialising operation...</div>
          )}
        </div>
      )}

      {/* BRIEFING */}
      {pageState === "briefing" && session && (
        <div className="max-w-2xl mx-auto px-4 py-10">
          <div className="border border-red-500/30 rounded-xl overflow-hidden">
            <div className="bg-red-500/10 px-6 py-5 border-b border-red-500/20">
              <div className="text-xs text-red-500 uppercase tracking-widest font-bold mb-2">OPERATION BRIEF — CLASSIFIED</div>
              <h2 className="text-2xl font-black text-white">Target: {session.scenario_title}</h2>
            </div>
            <div className="p-6 space-y-4">
              <div className="font-mono text-sm text-gray-300 whitespace-pre-line leading-relaxed">
                {session.intel_brief}
              </div>
              <div className="border-t border-gray-800 pt-4">
                <div className="text-xs text-gray-600 uppercase tracking-widest mb-2">Your Objective</div>
                <p className="text-gray-300 text-sm">{session.objective}</p>
              </div>
              <div className="border-t border-gray-800 pt-4">
                <div className="text-xs text-gray-600 uppercase tracking-widest mb-3">Rules of Engagement</div>
                <ul className="text-sm text-gray-400 space-y-1">
                  <li>• Stealth drops every time you're detected — hit 0 and the operation is burned</li>
                  <li>• Impact rises with every successful objective achieved</li>
                  <li>• Blue team AI responds dynamically to your every move</li>
                  <li>• You choose your own attack path through the MITRE kill chain</li>
                  <li>• Max impact + max stealth = highest score</li>
                </ul>
              </div>
              <button
                onClick={() => {
                  setPageState("playing");
                  setAvailableMoves(session.available_moves);
                }}
                className="w-full py-4 rounded-xl bg-red-600 hover:bg-red-500 text-white font-black text-lg tracking-wide transition-all active:scale-95"
              >
                🔴 BEGIN OPERATION
              </button>
            </div>
          </div>
        </div>
      )}

      {/* PLAYING */}
      {pageState === "playing" && session && (
        <div className="flex h-[calc(100vh-53px)]">
          {/* Left: HUD */}
          <div className="w-64 border-r border-gray-800 p-4 flex flex-col gap-4 overflow-y-auto bg-gray-950/80 shrink-0">
            <div>
              <div className="text-xs text-gray-600 uppercase tracking-widest mb-1 font-bold">{session.scenario_title}</div>
            </div>

            <StealthBar value={stealthScore} />
            <ImpactBar value={impactScore} />

            <div>
              <div className="text-xs text-gray-600 uppercase tracking-widest mb-2">Kill Chain</div>
              <KillChain phases={phasesCompleted} current={currentPhase} />
            </div>

            <IntelPanel facts={environmentState} />

            {/* Phase switcher */}
            <div>
              <div className="text-xs text-gray-600 uppercase tracking-widest mb-2">Switch Phase</div>
              <div className="space-y-1">
                {PHASE_ORDER.map((p) => (
                  <button
                    key={p}
                    onClick={() => handleSwitchPhase(p)}
                    className={`w-full text-left text-xs px-2 py-1.5 rounded transition-colors ${
                      p === currentPhase
                        ? "bg-red-500/20 text-red-300 font-bold"
                        : phasesCompleted.includes(p)
                        ? "text-purple-400 hover:bg-purple-500/10"
                        : "text-gray-600 hover:text-gray-400 hover:bg-gray-800"
                    }`}
                  >
                    {phasesCompleted.includes(p) ? "✓ " : ""}{PHASE_LABELS[p]}
                  </button>
                ))}
              </div>
            </div>

            {/* Blue team alerts */}
            {blueAlerts.length > 0 && (
              <div>
                <div className="text-xs text-red-500 uppercase tracking-widest mb-2 font-bold">🔵 Blue Team Alerts</div>
                <div className="space-y-2">
                  {blueAlerts.slice(-3).map((a, i) => (
                    <div key={i} className="text-[10px] text-gray-500 border border-red-900/30 bg-red-900/10 rounded p-2">
                      {a}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Move log */}
            {moveLog.length > 0 && (
              <div>
                <div className="text-xs text-gray-600 uppercase tracking-widest mb-2">Move Log</div>
                <div className="space-y-1">
                  {moveLog.slice(-6).reverse().map((m, i) => (
                    <div key={i} className="flex items-center gap-1.5 text-[10px]">
                      <span>{m.succeeded ? "✅" : "❌"}{m.detected ? "👁" : ""}</span>
                      <span className="text-gray-600 truncate">{m.tactic}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* Right: main area */}
          <div className="flex-1 overflow-y-auto p-6">
            {/* Move result */}
            {lastResult ? (
              <MoveResultPanel result={lastResult} onContinue={handleContinueAfterResult} />
            ) : (
              <div className="max-w-2xl mx-auto space-y-4">
                <div className="flex items-center justify-between mb-4">
                  <div>
                    <div className="text-xs text-gray-600 uppercase tracking-widest">Current Phase</div>
                    <h2 className="text-xl font-bold text-red-400">{PHASE_LABELS[currentPhase] || currentPhase}</h2>
                  </div>
                  <div className="text-xs text-gray-600">{availableMoves.length} moves available</div>
                </div>

                {moveError && (
                  <div className="border border-red-500/40 bg-red-500/10 rounded-lg p-3 flex items-center justify-between gap-3">
                    <p className="text-sm text-red-300">⚠ {moveError}</p>
                    <button
                      onClick={() => { setPageState("selector"); setSession(null); setMoveLog([]); setBlueAlerts([]); setStealthScore(100); setImpactScore(0); setLastResult(null); setSessionStatus("active"); setMoveError(null); }}
                      className="shrink-0 text-xs px-3 py-1.5 rounded-lg border border-red-500/40 text-red-300 hover:bg-red-500/20 transition-colors"
                    >
                      New Operation
                    </button>
                  </div>
                )}

                {availableMoves.length === 0 ? (
                  <div className="text-center py-12 text-gray-600">
                    <div className="text-4xl mb-3">🔍</div>
                    <p className="text-sm">No moves loaded for this phase.</p>
                    <p className="text-xs mt-1">Switch to another phase or complete a move first.</p>
                  </div>
                ) : (
                  <div className="space-y-4">
                    {availableMoves.map((move) => (
                      <MoveCard
                        key={move.tactic}
                        move={move}
                        onExecute={() => handleExecuteMove(move)}
                        executing={executingMove === move.tactic}
                      />
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      )}

      {/* END SCREEN */}
      {pageState === "endscreen" && (
        <div className="max-w-lg mx-auto px-4 py-16 text-center">
          <div className="text-6xl mb-6">
            {sessionStatus === "success" ? "🏆" : sessionStatus === "caught" ? "🚨" : "⏱"}
          </div>
          <h1 className={`text-4xl font-black mb-3 ${sessionStatus === "success" ? "text-green-400" : sessionStatus === "caught" ? "text-red-400" : "text-yellow-400"}`}>
            {sessionStatus === "success" ? "OPERATION SUCCESS" : sessionStatus === "caught" ? "OPERATION BURNED" : "OPERATION ENDED"}
          </h1>
          <p className="text-gray-400 mb-8">
            {sessionStatus === "success"
              ? "Maximum impact achieved. The target is compromised."
              : sessionStatus === "caught"
              ? "Blue team burned your operation. Stealth reached zero."
              : "The operation has concluded."}
          </p>

          <div className="grid grid-cols-3 gap-4 mb-8">
            <div className="border border-gray-800 rounded-xl p-4">
              <div className="text-2xl font-black text-white">{stealthScore}</div>
              <div className="text-xs text-gray-600 mt-1">Stealth Remaining</div>
            </div>
            <div className="border border-gray-800 rounded-xl p-4">
              <div className="text-2xl font-black text-purple-400">{impactScore}</div>
              <div className="text-xs text-gray-600 mt-1">Impact Score</div>
            </div>
            <div className="border border-gray-800 rounded-xl p-4">
              <div className="text-2xl font-black text-cyan-400">{moveLog.length}</div>
              <div className="text-xs text-gray-600 mt-1">Moves Made</div>
            </div>
          </div>

          <div className="space-y-3">
            <button
              onClick={() => { setPageState("selector"); setSession(null); setMoveLog([]); setBlueAlerts([]); setStealthScore(100); setImpactScore(0); setLastResult(null); setSessionStatus("active"); }}
              className="w-full py-4 rounded-xl bg-red-600 hover:bg-red-500 text-white font-black text-lg transition-all active:scale-95"
            >
              🔴 Run Another Operation
            </button>
            <button
              onClick={() => navigate("/scenarios")}
              className="w-full py-3 rounded-xl border border-gray-700 hover:border-gray-500 text-gray-300 text-sm font-bold transition-all"
            >
              Back to Scenario Library
            </button>
          </div>
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
  );
}
