import { useEffect, useMemo, useState } from "react";
import { Navigate, useNavigate, useParams } from "react-router-dom";
import { api } from "../lib/api";
import { useAuthStore } from "../store/auth";

// ── Types (mirror OrgState.to_dict() from org_simulation.py exactly, same
// shapes ArenaMatchPage.tsx already declares) ───────────────────────────────
interface Host {
  id: string;
  hostname: string;
  role: string;
  network_segment_id: string;
  unpatched_cves: string[];
  edr_installed: boolean;
  compromise_level: "none" | "foothold" | "admin" | "domain_admin";
  isolated: boolean;
}

interface Segment {
  id: string;
  name: string;
  monitored: boolean;
  reachable_from: string[];
}

interface Credential {
  id: string;
  username: string;
  privilege: string;
  valid_on_host_ids: string[];
  harvested: boolean;
  disabled: boolean;
}

interface OrgStateDict {
  hosts: Host[];
  segments: Segment[];
  credentials: Credential[];
  detection_rules: unknown[];
  global_flags: Record<string, unknown>;
}

interface MatchDetail {
  id: string;
  mode: "pvp" | "human_defends_vs_ai" | "human_attacks_vs_ai";
  archetype_key: string;
  difficulty: string;
  status: string;
  attacker_user_id: string | null;
  defender_user_id: string | null;
  action_count: number;
  state: OrgStateDict;
  events: MatchEvent[];
}

interface MatchEvent {
  sequence_number: number;
  actor: "attacker" | "defender" | null;
  action_type: string | null;
  detected: boolean;
  alert: { severity: string; description: string; source_system: string; raw_log?: string } | null;
}

interface ExploreResponse {
  match_id: string;
  at_sequence_number: number;
  real_action_count: number;
  alternate_action: { sequence_number: number; actor: string; action_type: string; payload: Record<string, unknown> };
  state: OrgStateDict;
  events: MatchEvent[];
}

// Reuses the exact ATTACKER/DEFENDER move catalogs already built for the
// live match page — same action-type/payload-field-selection UI pattern,
// per the plan's "reuse the same action-type/payload-field-selection UI
// patterns already built in ArenaMatchPage.tsx" instruction.
const ATTACKER_MOVES: { action_type: string; label: string; needs: string }[] = [
  { action_type: "discover_segment", label: "Scan Segment", needs: "segment_id" },
  { action_type: "discover_host", label: "Enumerate Host", needs: "host_id" },
  { action_type: "gain_foothold", label: "Gain Foothold", needs: "host_id" },
  { action_type: "dump_credentials", label: "Dump Credentials", needs: "host_id" },
  { action_type: "escalate_privilege", label: "Escalate Privilege", needs: "host_id" },
  { action_type: "lateral_move", label: "Lateral Movement", needs: "credential+target" },
  { action_type: "deploy_impact", label: "Deploy Impact", needs: "host_id" },
];

const DEFENDER_MOVES: { action_type: string; label: string; needs: string }[] = [
  { action_type: "isolate_host", label: "Isolate Host", needs: "host_id" },
  { action_type: "disable_credential", label: "Disable Credential", needs: "credential_id" },
  { action_type: "patch_host", label: "Patch Host", needs: "host_id" },
  { action_type: "increase_monitoring", label: "Increase Monitoring", needs: "segment_id" },
  { action_type: "acknowledge", label: "Acknowledge", needs: "(none)" },
];

const COMPROMISE_COLOR: Record<string, string> = {
  none: "text-gray-600",
  foothold: "text-yellow-400",
  admin: "text-orange-400",
  domain_admin: "text-red-400",
};

export default function ArenaDebriefPage() {
  const { matchId } = useParams<{ matchId: string }>();
  const navigate = useNavigate();
  const { user } = useAuthStore();

  const [match, setMatch] = useState<MatchDetail | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  // Timeline selection: which real action's sequence_number is the
  // "diverge here" point.
  const [selectedSeq, setSelectedSeq] = useState<number | null>(null);
  const [altActor, setAltActor] = useState<"attacker" | "defender">("defender");
  const [altActionType, setAltActionType] = useState<string>("");
  const [selSegment, setSelSegment] = useState("");
  const [selHost, setSelHost] = useState("");
  const [selCredential, setSelCredential] = useState("");
  const [selTargetHost, setSelTargetHost] = useState("");

  const [exploring, setExploring] = useState(false);
  const [exploreError, setExploreError] = useState<string | null>(null);
  const [exploreResult, setExploreResult] = useState<ExploreResponse | null>(null);

  useEffect(() => {
    if (!matchId) return;
    api
      .get<MatchDetail>(`/arena/matches/${matchId}`)
      .then(setMatch)
      .catch((e: any) => setLoadError(e.message || "Failed to load match"));
  }, [matchId]);

  const role: "attacker" | "defender" | null = useMemo(() => {
    if (!match || !user) return null;
    if (match.attacker_user_id === user.id) return "attacker";
    if (match.defender_user_id === user.id) return "defender";
    return null;
  }, [match, user]);

  if (!matchId) return <Navigate to="/arena" replace />;

  if (loadError) {
    return (
      <div className="min-h-screen bg-gray-950 text-white flex items-center justify-center px-4">
        <div className="text-center">
          <div className="text-4xl mb-3">⚠</div>
          <p className="text-red-400 mb-4">{loadError}</p>
          <button onClick={() => navigate("/arena")} className="text-xs text-gray-500 hover:text-gray-300">
            ← Back to Arena Lobby
          </button>
        </div>
      </div>
    );
  }

  if (!match) {
    return (
      <div className="min-h-screen bg-gray-950 flex items-center justify-center">
        <div className="text-gray-600 text-sm">Loading match history...</div>
      </div>
    );
  }

  const isComplete = ["attacker_won", "defender_won", "abandoned"].includes(match.status);
  const hosts = match.state.hosts || [];
  const segments = match.state.segments || [];
  const credentials = match.state.credentials || [];
  const reachableHosts = hosts.filter((h) => !h.isolated);
  const harvestedCreds = credentials.filter((c) => c.harvested && !c.disabled);
  const moveCatalog = altActor === "attacker" ? ATTACKER_MOVES : DEFENDER_MOVES;

  function buildAlternatePayload(): Record<string, unknown> | null {
    if (altActionType === "discover_segment" || altActionType === "increase_monitoring") {
      if (!selSegment) return null;
      return { segment_id: selSegment };
    }
    if (altActionType === "lateral_move") {
      if (!selCredential || !selTargetHost) return null;
      return { credential_id: selCredential, target_host_id: selTargetHost };
    }
    if (altActionType === "disable_credential") {
      if (!selCredential) return null;
      return { credential_id: selCredential };
    }
    if (altActionType === "acknowledge") {
      return {};
    }
    // gain_foothold / dump_credentials / escalate_privilege / deploy_impact / isolate_host / patch_host
    if (!selHost) return null;
    return { host_id: selHost };
  }

  async function runExplore() {
    if (selectedSeq === null || !altActionType) {
      setExploreError("Select a divergence point and an alternate action first.");
      return;
    }
    const payload = buildAlternatePayload();
    if (payload === null) {
      setExploreError("Fill in the required target field(s) for this action.");
      return;
    }
    setExploring(true);
    setExploreError(null);
    try {
      const result = await api.post<ExploreResponse>(`/arena/matches/${matchId}/explore`, {
        at_sequence_number: selectedSeq,
        alternate_action: { actor: altActor, action_type: altActionType, payload },
      });
      setExploreResult(result);
    } catch (e: any) {
      setExploreError(e.message || "Exploration failed");
    } finally {
      setExploring(false);
    }
  }

  return (
    <div className="min-h-screen bg-[#040712] flex flex-col font-mono text-slate-200">
      {/* Top bar — mirrors ArenaMatchPage.tsx's conventions */}
      <div className="border-b border-slate-800 bg-slate-950/90 px-5 py-2.5 flex items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <button onClick={() => navigate("/arena")} className="text-slate-500 hover:text-slate-300 text-xs">
            ← Arena
          </button>
          <span className="text-slate-600">|</span>
          <button onClick={() => navigate(`/arena/match/${matchId}`)} className="text-slate-500 hover:text-slate-300 text-xs">
            Match View
          </button>
          <span className="text-slate-600">|</span>
          <span className="text-cyan-500 font-black text-sm uppercase tracking-widest">🕸 Multiverse Debrief</span>
          <span className="text-slate-600">|</span>
          <span className="text-slate-500 text-xs">Match {matchId.slice(0, 8)}</span>
        </div>
        <span className={`text-[10px] px-2 py-0.5 rounded border font-bold uppercase tracking-wider ${
          match.status === "attacker_won" ? "border-red-500/50 text-red-400 bg-red-500/10" : "border-green-500/50 text-green-400 bg-green-500/10"
        }`}>
          {match.status.replace(/_/g, " ")}
        </span>
      </div>

      {!isComplete && (
        <div className="px-5 py-3 text-center text-xs text-yellow-500 bg-yellow-950/10 border-b border-yellow-900/30">
          This match hasn't completed yet — the debrief/exploration view is only meaningful once a match is over.
        </div>
      )}

      {!role && (
        <div className="px-5 py-3 text-center text-xs text-yellow-500 bg-yellow-950/10 border-b border-yellow-900/30">
          You are not a participant in this match.
        </div>
      )}

      <div className="flex-1 overflow-y-auto p-6">
        <div className="max-w-5xl mx-auto space-y-6">
          {/* ── Real action-log timeline ── */}
          <div className="bg-[#090d16]/60 border border-slate-800 rounded-lg p-5">
            <div className="flex items-center justify-between mb-4 border-b border-slate-800 pb-3">
              <div>
                <span className="text-[10px] text-cyan-500 uppercase tracking-widest font-extrabold block mb-1">
                  Real Action Log
                </span>
                <h3 className="text-sm font-bold uppercase tracking-wider text-slate-200">
                  What Actually Happened ({match.events.length} actions)
                </h3>
              </div>
              <span className="text-[10px] text-slate-600">Click an action to explore an alternate choice at that point</span>
            </div>

            {match.events.length === 0 ? (
              <p className="text-xs text-slate-600 text-center py-6">No actions were recorded in this match.</p>
            ) : (
              <div className="space-y-1.5">
                {match.events.map((ev) => {
                  const isAttacker = ev.actor === "attacker";
                  const isSelected = selectedSeq === ev.sequence_number;
                  return (
                    <button
                      key={ev.sequence_number}
                      onClick={() => {
                        setSelectedSeq(ev.sequence_number);
                        setExploreResult(null);
                        setExploreError(null);
                        setAltActor(ev.actor === "attacker" ? "attacker" : "defender");
                        setAltActionType("");
                        setSelSegment("");
                        setSelHost("");
                        setSelCredential("");
                        setSelTargetHost("");
                      }}
                      className={`w-full text-left flex items-center gap-3 border rounded px-3 py-2 transition-all ${
                        isSelected
                          ? "border-cyan-500 bg-cyan-950/20 ring-1 ring-cyan-500/40"
                          : "border-slate-800 hover:border-slate-600"
                      }`}
                    >
                      <span className="text-[10px] text-slate-600 w-8 shrink-0">#{ev.sequence_number}</span>
                      <span
                        className={`text-[9px] font-black uppercase px-1.5 py-0.5 rounded shrink-0 ${
                          isAttacker ? "bg-red-600/80 text-white" : "bg-blue-600/80 text-white"
                        }`}
                      >
                        {ev.actor ?? "unknown"}
                      </span>
                      <span className="text-xs text-slate-300 flex-1 truncate">
                        {(ev.action_type ?? "—").replace(/_/g, " ")}
                      </span>
                      {ev.detected && (
                        <span className="text-[9px] text-orange-400 uppercase font-bold shrink-0">detected</span>
                      )}
                      {ev.alert && (
                        <span className="text-[10px] text-slate-500 truncate max-w-[220px] shrink-0 hidden md:inline">
                          {ev.alert.description}
                        </span>
                      )}
                    </button>
                  );
                })}
              </div>
            )}
          </div>

          {/* ── Alternate-choice builder + result ── */}
          {isComplete && selectedSeq !== null && (
            <div className="bg-[#090d16]/60 border border-purple-900/40 rounded-lg p-5">
              <div className="mb-4 border-b border-purple-900/30 pb-3">
                <span className="text-[10px] text-purple-400 uppercase tracking-widest font-extrabold block mb-1">
                  Alternate Timeline Builder
                </span>
                <h3 className="text-sm font-bold uppercase tracking-wider text-slate-200">
                  What if, at step #{selectedSeq}, this had happened instead?
                </h3>
                <p className="text-[10px] text-slate-600 mt-1">
                  This replaces the real action at step #{selectedSeq} and drops everything that happened after it —
                  the rest of the real match no longer applies once history diverges here. Nothing about the real
                  match is changed by exploring this.
                </p>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="space-y-3">
                  <div>
                    <label className="text-[10px] text-gray-600 uppercase block mb-1">Acting side</label>
                    <div className="flex gap-2">
                      {(["attacker", "defender"] as const).map((side) => (
                        <button
                          key={side}
                          onClick={() => {
                            setAltActor(side);
                            setAltActionType("");
                          }}
                          className={`flex-1 text-xs uppercase font-bold tracking-wider py-1.5 rounded border ${
                            altActor === side
                              ? side === "attacker"
                                ? "bg-red-600/80 border-red-500 text-white"
                                : "bg-blue-600/80 border-blue-500 text-white"
                              : "border-gray-800 text-gray-500 hover:border-gray-600"
                          }`}
                        >
                          {side}
                        </button>
                      ))}
                    </div>
                  </div>

                  <div>
                    <label className="text-[10px] text-gray-600 uppercase block mb-1">Alternate action</label>
                    <select
                      value={altActionType}
                      onChange={(e) => setAltActionType(e.target.value)}
                      className="w-full bg-gray-950 border border-gray-800 text-gray-300 text-xs p-1.5 rounded"
                    >
                      <option value="">— select —</option>
                      {moveCatalog.map((m) => (
                        <option key={m.action_type} value={m.action_type}>
                          {m.label} (needs {m.needs})
                        </option>
                      ))}
                    </select>
                  </div>

                  <div className="grid grid-cols-2 gap-2">
                    <div>
                      <label className="text-[10px] text-gray-600 uppercase block mb-1">Segment</label>
                      <select
                        value={selSegment}
                        onChange={(e) => setSelSegment(e.target.value)}
                        className="w-full bg-gray-950 border border-gray-800 text-gray-300 text-xs p-1.5 rounded"
                      >
                        <option value="">— select —</option>
                        {segments.map((s) => (
                          <option key={s.id} value={s.id}>{s.name}</option>
                        ))}
                      </select>
                    </div>
                    <div>
                      <label className="text-[10px] text-gray-600 uppercase block mb-1">Host</label>
                      <select
                        value={selHost}
                        onChange={(e) => setSelHost(e.target.value)}
                        className="w-full bg-gray-950 border border-gray-800 text-gray-300 text-xs p-1.5 rounded"
                      >
                        <option value="">— select —</option>
                        {(altActor === "attacker" ? reachableHosts : hosts).map((h) => (
                          <option key={h.id} value={h.id}>{h.hostname}</option>
                        ))}
                      </select>
                    </div>
                    <div>
                      <label className="text-[10px] text-gray-600 uppercase block mb-1">Credential</label>
                      <select
                        value={selCredential}
                        onChange={(e) => setSelCredential(e.target.value)}
                        className="w-full bg-gray-950 border border-gray-800 text-gray-300 text-xs p-1.5 rounded"
                      >
                        <option value="">— select —</option>
                        {(altActor === "attacker" ? harvestedCreds : credentials).map((c) => (
                          <option key={c.id} value={c.id}>{c.username}</option>
                        ))}
                      </select>
                    </div>
                    <div>
                      <label className="text-[10px] text-gray-600 uppercase block mb-1">Target host (lateral move)</label>
                      <select
                        value={selTargetHost}
                        onChange={(e) => setSelTargetHost(e.target.value)}
                        className="w-full bg-gray-950 border border-gray-800 text-gray-300 text-xs p-1.5 rounded"
                      >
                        <option value="">— select —</option>
                        {reachableHosts.map((h) => (
                          <option key={h.id} value={h.id}>{h.hostname}</option>
                        ))}
                      </select>
                    </div>
                  </div>

                  {exploreError && <p className="text-[11px] text-red-400">{exploreError}</p>}

                  <button
                    onClick={runExplore}
                    disabled={exploring || !altActionType}
                    className="w-full py-2 rounded-lg bg-purple-600/80 hover:bg-purple-600 disabled:opacity-40 text-white text-xs font-bold uppercase tracking-wider transition-all active:scale-[0.98]"
                  >
                    {exploring ? "Computing alternate timeline..." : "🕸 Explore This Branch"}
                  </button>
                </div>

                {/* ── Alternate timeline result panel — clearly distinct from real history ── */}
                <div className="border border-purple-800/40 bg-purple-950/10 rounded p-4">
                  <div className="text-[10px] text-purple-400 uppercase tracking-widest font-bold mb-2">
                    Alternate Timeline (Computed, Not Real)
                  </div>
                  {!exploreResult ? (
                    <p className="text-[11px] text-slate-600 py-6 text-center">
                      Build an alternate action on the left and click "Explore This Branch" to see the diverged outcome.
                    </p>
                  ) : (
                    <div className="space-y-3">
                      <p className="text-[10px] text-slate-500">
                        Diverged at step #{exploreResult.at_sequence_number} of {exploreResult.real_action_count} real actions
                        — real history after this point is dropped in this branch.
                      </p>
                      <div>
                        <div className="text-[9px] text-gray-600 uppercase tracking-widest mb-1">Hosts in this branch</div>
                        <div className="space-y-1 max-h-48 overflow-y-auto">
                          {exploreResult.state.hosts.map((h) => (
                            <div key={h.id} className={`text-[10px] border rounded px-2 py-1 ${h.isolated ? "border-purple-900/50 opacity-60" : "border-purple-900/50"}`}>
                              <div className="flex justify-between">
                                <span className="text-slate-300 truncate">{h.hostname}</span>
                                <span className={COMPROMISE_COLOR[h.compromise_level]}>{h.compromise_level}</span>
                              </div>
                              <div className="text-slate-600">{h.role}{h.isolated ? " · ISOLATED" : ""}</div>
                            </div>
                          ))}
                        </div>
                      </div>
                      {exploreResult.state.global_flags?.impact_deployed !== undefined && (
                        <p className="text-[10px] text-purple-300">
                          impact_deployed: {String(exploreResult.state.global_flags.impact_deployed)}
                        </p>
                      )}
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
