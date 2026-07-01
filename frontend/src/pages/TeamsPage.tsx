import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { axiosInstance } from "../lib/api";
import { useAuthStore } from "../store/auth";

interface MemberOut {
  user_id: string;
  full_name: string | null;
  email: string;
  role: string;
  xp_total: number;
  career_tier: string;
  joined_at: string;
}

interface TeamOut {
  id: string;
  name: string;
  organization_id: string;
  total_xp: number;
  member_count: number;
  created_at: string;
  members: MemberOut[];
}

interface LeaderboardEntry {
  rank: number;
  team_id: string;
  team_name: string;
  total_xp: number;
  member_count: number;
}

const TIER_COLORS: Record<string, string> = {
  recruit: "text-breach-muted",
  analyst: "text-breach-blue",
  specialist: "text-green-400",
  expert: "text-yellow-400",
  elite: "text-breach-accent",
  legend: "text-purple-400",
};

const RANK_BADGE = (rank: number) => {
  if (rank === 1) return "🥇";
  if (rank === 2) return "🥈";
  if (rank === 3) return "🥉";
  return `#${rank}`;
};

export default function TeamsPage() {
  const qc = useQueryClient();
  const currentUserId = useAuthStore((s) => s.user?.id);
  const currentUserRole = useAuthStore((s) => s.user?.role);
  const isOrgAdmin = currentUserRole === "admin" || currentUserRole === "ciso";
  const [view, setView] = useState<"teams" | "leaderboard">("teams");
  const [newTeamName, setNewTeamName] = useState("");
  const [createError, setCreateError] = useState("");
  const [expandedTeam, setExpandedTeam] = useState<string | null>(null);
  const [joinError, setJoinError] = useState<Record<string, string>>({});
  const [leaveError, setLeaveError] = useState<Record<string, string>>({});
  const [inviteEmail, setInviteEmail] = useState<Record<string, string>>({});
  const [inviteMsg, setInviteMsg] = useState<Record<string, string>>({});
  const [assignTarget, setAssignTarget] = useState<string | null>(null);
  const [assignTechnique, setAssignTechnique] = useState<Record<string, string>>({});
  const [assignDueDate, setAssignDueDate] = useState<Record<string, string>>({});
  const [assignMsg, setAssignMsg] = useState<Record<string, string>>({});

  const { data: teams = [], isLoading: teamsLoading } = useQuery<TeamOut[]>({
    queryKey: ["teams"],
    queryFn: async () => (await axiosInstance.get("/teams/")).data,
    refetchInterval: 15000,
  });

  const { data: leaderboard = [], isLoading: lbLoading } = useQuery<LeaderboardEntry[]>({
    queryKey: ["team-leaderboard"],
    queryFn: async () => (await axiosInstance.get("/teams/leaderboard")).data,
    enabled: view === "leaderboard",
  });

  const createMutation = useMutation({
    mutationFn: async (name: string) => (await axiosInstance.post("/teams/", { name })).data,
    onSuccess: () => {
      setNewTeamName("");
      setCreateError("");
      qc.invalidateQueries({ queryKey: ["teams"] });
      qc.invalidateQueries({ queryKey: ["team-leaderboard"] });
    },
    onError: (err: any) => setCreateError(err?.message || "Failed to create team"),
  });

  const joinMutation = useMutation({
    mutationFn: async (teamId: string) => (await axiosInstance.post(`/teams/${teamId}/join`)).data,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["teams"] });
      qc.invalidateQueries({ queryKey: ["team-leaderboard"] });
    },
    onError: (err: any, teamId) => setJoinError(prev => ({ ...prev, [teamId]: err?.response?.data?.detail || "Failed to join team" })),
  });

  const leaveMutation = useMutation({
    mutationFn: async (teamId: string) => (await axiosInstance.post(`/teams/${teamId}/leave`)).data,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["teams"] });
      qc.invalidateQueries({ queryKey: ["team-leaderboard"] });
    },
    onError: (err: any, teamId) => setLeaveError(prev => ({ ...prev, [teamId]: err?.response?.data?.detail || "Failed to leave team" })),
  });

  const syncMutation = useMutation({
    mutationFn: async (teamId: string) => (await axiosInstance.post(`/teams/${teamId}/sync-xp`)).data,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["teams"] }),
  });

  const assignMutation = useMutation({
    mutationFn: async ({ teamId, targetTechniqueId, dueDate }: { teamId: string; targetTechniqueId: string; dueDate: string }) =>
      (await axiosInstance.post("/admin/assignments", {
        team_id: teamId,
        target_technique_id: targetTechniqueId,
        due_date: dueDate ? new Date(dueDate).toISOString() : null,
      })).data,
    onSuccess: (_data, { teamId }) => {
      setAssignMsg((prev) => ({ ...prev, [teamId]: "Training assigned to team." }));
      setAssignTechnique((prev) => ({ ...prev, [teamId]: "" }));
      setAssignDueDate((prev) => ({ ...prev, [teamId]: "" }));
    },
    onError: (err: any, { teamId }) =>
      setAssignMsg((prev) => ({ ...prev, [teamId]: err?.response?.data?.detail || err?.message || "Failed to assign training" })),
  });

  const inviteMutation = useMutation({
    mutationFn: async ({ teamId, email }: { teamId: string; email: string }) =>
      (await axiosInstance.post(`/teams/${teamId}/invite`, { email })).data,
    onSuccess: (data, { teamId }) => {
      setInviteMsg(prev => ({ ...prev, [teamId]: data.message }));
      setInviteEmail(prev => ({ ...prev, [teamId]: "" }));
    },
    onError: (err: any, { teamId }) =>
      setInviteMsg(prev => ({ ...prev, [teamId]: err?.response?.data?.detail || "Failed to send invite" })),
  });

  const handleCreate = (e: React.FormEvent) => {
    e.preventDefault();
    const name = newTeamName.trim();
    if (!name) return;
    createMutation.mutate(name);
  };

  return (
    <div className="min-h-screen bg-breach-bg text-breach-text p-6">
      <div className="max-w-5xl mx-auto space-y-6">

        {/* Header */}
        <div className="border-b border-breach-border pb-5 flex items-start justify-between gap-4">
          <div>
            <div className="flex items-center gap-3 mb-1">
              <span className="text-2xl">👥</span>
              <h1 className="text-lg font-bold uppercase tracking-widest">Team Mode</h1>
            </div>
            <p className="text-xs text-breach-muted">
              Compete with colleagues — team XP is the sum of all member contributions
            </p>
          </div>
          <div className="flex gap-2">
            <button
              onClick={() => setView("teams")}
              className={`px-3 py-1.5 rounded text-xs font-bold uppercase tracking-widest transition-colors ${
                view === "teams"
                  ? "bg-breach-accent/10 text-breach-accent border border-breach-accent/30"
                  : "border border-breach-border text-breach-muted hover:text-breach-text"
              }`}
            >
              Teams
            </button>
            <button
              onClick={() => setView("leaderboard")}
              className={`px-3 py-1.5 rounded text-xs font-bold uppercase tracking-widest transition-colors ${
                view === "leaderboard"
                  ? "bg-breach-accent/10 text-breach-accent border border-breach-accent/30"
                  : "border border-breach-border text-breach-muted hover:text-breach-text"
              }`}
            >
              Leaderboard
            </button>
          </div>
        </div>

        {view === "teams" && (
          <>
            {/* Create Team Form */}
            <div className="bg-breach-surface border border-breach-border rounded p-5 space-y-3">
              <div className="text-[10px] text-breach-muted uppercase tracking-widest font-bold">Create New Team</div>
              <form onSubmit={handleCreate} className="flex gap-3">
                <input
                  value={newTeamName}
                  onChange={(e) => setNewTeamName(e.target.value)}
                  placeholder="e.g. SOC Alpha Squad"
                  maxLength={100}
                  className="flex-1 bg-breach-bg border border-breach-border rounded px-3 py-2 text-sm text-breach-text placeholder-breach-muted/50 focus:border-breach-blue focus:outline-none"
                />
                <button
                  type="submit"
                  disabled={!newTeamName.trim() || createMutation.isPending}
                  className="bg-breach-accent hover:bg-red-600 disabled:bg-breach-accent/40 text-white px-5 py-2 rounded text-xs uppercase tracking-widest font-bold transition-colors"
                >
                  {createMutation.isPending ? "Creating..." : "Create"}
                </button>
              </form>
              {createError && (
                <p className="text-xs text-red-400">{createError}</p>
              )}
            </div>

            {/* Teams List */}
            {teamsLoading ? (
              <div className="text-xs text-breach-muted p-6 text-center">Loading teams...</div>
            ) : teams.length === 0 ? (
              <div className="bg-breach-surface border border-dashed border-breach-border rounded p-10 text-center">
                <div className="text-4xl mb-3">🤝</div>
                <p className="text-xs font-bold text-breach-text uppercase tracking-wider mb-1">No Teams Yet</p>
                <p className="text-xs text-breach-muted max-w-sm mx-auto">Create your org's first team above — your colleagues can join and compete together.</p>
              </div>
            ) : (
              <div className="space-y-4">
                {teams.map((team) => {
                  const isExpanded = expandedTeam === team.id;
                  return (
                    <div key={team.id} className="bg-breach-surface border border-breach-border rounded overflow-hidden">
                      <div
                        className="p-5 flex items-center justify-between cursor-pointer hover:bg-breach-bg/40 transition-colors"
                        onClick={() => setExpandedTeam(isExpanded ? null : team.id)}
                      >
                        <div className="flex items-center gap-4">
                          <div className="w-8 h-8 bg-breach-accent/10 border border-breach-accent/20 rounded-full flex items-center justify-center text-breach-accent font-black text-sm">
                            {team.name[0].toUpperCase()}
                          </div>
                          <div>
                            <div className="font-bold text-sm text-breach-text">{team.name}</div>
                            <div className="text-[10px] text-breach-muted">{team.member_count} member{team.member_count !== 1 ? "s" : ""}</div>
                          </div>
                        </div>
                        <div className="flex items-center gap-4">
                          <div className="text-right">
                            <div className="text-xs font-mono font-bold text-green-400">{team.total_xp.toLocaleString()} XP</div>
                            <div className="text-[9px] text-breach-muted uppercase tracking-wider">Team Total</div>
                          </div>
                          <div className="flex gap-2">
                            <div className="flex flex-col items-end gap-1">
                              <button
                                onClick={(e) => { e.stopPropagation(); joinMutation.mutate(team.id); }}
                                disabled={joinMutation.isPending}
                                className="text-[10px] bg-breach-blue/10 border border-breach-blue/30 text-breach-blue px-2 py-1 rounded uppercase font-bold tracking-wider hover:bg-breach-blue/20 transition-colors"
                              >
                                Join
                              </button>
                              {joinError[team.id] && (
                                <span className="text-[9px] text-red-400">{joinError[team.id]}</span>
                              )}
                            </div>
                            <button
                              onClick={(e) => { e.stopPropagation(); syncMutation.mutate(team.id); }}
                              disabled={syncMutation.isPending}
                              className="text-[10px] bg-breach-surface border border-breach-border text-breach-muted px-2 py-1 rounded uppercase font-bold tracking-wider hover:text-breach-text transition-colors"
                              title="Sync team XP from member totals"
                            >
                              ↻
                            </button>
                          </div>
                          <span className="text-breach-muted text-xs">{isExpanded ? "▲" : "▼"}</span>
                        </div>
                      </div>

                      {isExpanded && team.members.length > 0 && (
                        <div className="border-t border-breach-border">
                          <div className="px-5 py-3 text-[9px] text-breach-muted uppercase tracking-widest font-bold bg-breach-bg/40">Members</div>
                          <div className="divide-y divide-breach-border/50">
                            {[...team.members]
                              .sort((a, b) => b.xp_total - a.xp_total)
                              .map((m, idx) => (
                                <div key={m.user_id} className="px-5 py-3 flex items-center justify-between">
                                  <div className="flex items-center gap-3">
                                    <span className="text-[10px] text-breach-muted font-mono w-4">{idx + 1}</span>
                                    <div>
                                      <div className="text-xs font-bold text-breach-text">{m.full_name || m.email}</div>
                                      <div className="flex items-center gap-2 mt-0.5">
                                        <span className={`text-[9px] uppercase font-bold tracking-wider ${TIER_COLORS[m.career_tier] ?? "text-breach-muted"}`}>
                                          {m.career_tier}
                                        </span>
                                        {m.role === "captain" && (
                                          <span className="text-[9px] bg-yellow-500/10 text-yellow-400 border border-yellow-500/20 px-1 py-px rounded uppercase font-bold tracking-widest">
                                            Captain
                                          </span>
                                        )}
                                      </div>
                                    </div>
                                  </div>
                                  <div className="flex items-center gap-3">
                                    <span className="text-xs font-mono font-bold text-breach-text">{m.xp_total.toLocaleString()} XP</span>
                                    {m.user_id === currentUserId && (
                                      <div className="flex flex-col items-end gap-0.5">
                                        <button
                                          onClick={() => leaveMutation.mutate(team.id)}
                                          className="text-[9px] text-breach-muted hover:text-red-400 uppercase tracking-wider transition-colors"
                                        >
                                          Leave
                                        </button>
                                        {leaveError[team.id] && (
                                          <span className="text-[9px] text-red-400">{leaveError[team.id]}</span>
                                        )}
                                      </div>
                                    )}
                                  </div>
                                </div>
                              ))}
                          </div>
                          {/* Invite form — visible to team members only */}
                          {team.members.some(m => m.user_id === currentUserId) && (
                            <div className="px-5 py-3 border-t border-breach-border/50 bg-breach-bg/20">
                              <div className="text-[9px] text-breach-muted uppercase tracking-widest font-bold mb-2">Invite Colleague</div>
                              <div className="flex gap-2">
                                <input
                                  type="email"
                                  placeholder="colleague@company.com"
                                  value={inviteEmail[team.id] || ""}
                                  onChange={e => setInviteEmail(prev => ({ ...prev, [team.id]: e.target.value }))}
                                  className="flex-1 bg-breach-bg border border-breach-border rounded px-3 py-1.5 text-xs text-breach-text placeholder-breach-muted/50 focus:border-breach-blue focus:outline-none"
                                />
                                <button
                                  onClick={() => {
                                    const email = inviteEmail[team.id]?.trim();
                                    if (email) inviteMutation.mutate({ teamId: team.id, email });
                                  }}
                                  disabled={!inviteEmail[team.id]?.trim() || inviteMutation.isPending}
                                  className="bg-breach-blue/10 border border-breach-blue/30 text-breach-blue px-3 py-1.5 rounded text-[10px] uppercase font-bold tracking-wider hover:bg-breach-blue/20 transition-colors disabled:opacity-40"
                                >
                                  Invite
                                </button>
                              </div>
                              {inviteMsg[team.id] && (
                                <p className={`text-[9px] mt-1.5 ${inviteMsg[team.id].startsWith("Invite sent") ? "text-green-400" : "text-red-400"}`}>
                                  {inviteMsg[team.id]}
                                </p>
                              )}
                            </div>
                          )}
                          {/* Assign Training — visible to team captains and org admins only */}
                          {(isOrgAdmin || team.members.some(m => m.user_id === currentUserId && m.role === "captain")) && (
                            <div className="px-5 py-3 border-t border-breach-border/50 bg-breach-bg/20">
                              {assignTarget === team.id ? (
                                <div className="space-y-2">
                                  <div className="text-[9px] text-breach-muted uppercase tracking-widest font-bold mb-1">Assign Training — MITRE Technique</div>
                                  <div className="flex gap-2">
                                    <input
                                      type="text"
                                      placeholder="e.g. T1003"
                                      value={assignTechnique[team.id] || ""}
                                      onChange={e => setAssignTechnique(prev => ({ ...prev, [team.id]: e.target.value }))}
                                      maxLength={50}
                                      className="flex-1 bg-breach-bg border border-breach-border rounded px-3 py-1.5 text-xs text-breach-text placeholder-breach-muted/50 focus:border-breach-blue focus:outline-none"
                                    />
                                    <input
                                      type="date"
                                      value={assignDueDate[team.id] || ""}
                                      onChange={e => setAssignDueDate(prev => ({ ...prev, [team.id]: e.target.value }))}
                                      className="bg-breach-bg border border-breach-border rounded px-2 py-1.5 text-xs text-breach-text focus:border-breach-blue focus:outline-none"
                                    />
                                    <button
                                      onClick={() => {
                                        const technique = assignTechnique[team.id]?.trim();
                                        if (!technique) return;
                                        assignMutation.mutate({ teamId: team.id, targetTechniqueId: technique, dueDate: assignDueDate[team.id] || "" });
                                      }}
                                      disabled={!assignTechnique[team.id]?.trim() || assignMutation.isPending}
                                      className="bg-breach-accent hover:bg-red-600 disabled:bg-breach-accent/40 text-white px-3 py-1.5 rounded text-[10px] uppercase font-bold tracking-wider transition-colors"
                                    >
                                      Assign
                                    </button>
                                    <button
                                      onClick={() => setAssignTarget(null)}
                                      className="text-[10px] text-breach-muted hover:text-breach-text uppercase tracking-wider px-2"
                                    >
                                      Cancel
                                    </button>
                                  </div>
                                  {assignMsg[team.id] && (
                                    <p className={`text-[9px] ${assignMsg[team.id].startsWith("Training assigned") ? "text-green-400" : "text-red-400"}`}>
                                      {assignMsg[team.id]}
                                    </p>
                                  )}
                                </div>
                              ) : (
                                <button
                                  onClick={() => setAssignTarget(team.id)}
                                  className="text-[10px] bg-yellow-500/10 border border-yellow-500/30 text-yellow-400 px-3 py-1.5 rounded uppercase font-bold tracking-wider hover:bg-yellow-500/20 transition-colors"
                                >
                                  🎯 Assign Training
                                </button>
                              )}
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </>
        )}

        {view === "leaderboard" && (
          <div className="space-y-3">
            <div className="text-[10px] text-breach-muted uppercase tracking-widest font-bold">Org Team Rankings</div>
            {lbLoading ? (
              <div className="text-xs text-breach-muted p-6 text-center">Loading leaderboard...</div>
            ) : leaderboard.length === 0 ? (
              <div className="text-center py-12 text-xs text-breach-muted">No teams yet — be the first to create one!</div>
            ) : (
              <div className="space-y-2">
                {leaderboard.map((entry) => (
                  <div
                    key={entry.team_id}
                    className={`bg-breach-surface border rounded p-4 flex items-center justify-between transition-colors ${
                      entry.rank <= 3
                        ? "border-yellow-500/30 bg-yellow-500/5"
                        : "border-breach-border"
                    }`}
                  >
                    <div className="flex items-center gap-4">
                      <span className="text-xl w-8 text-center font-bold">
                        {RANK_BADGE(entry.rank)}
                      </span>
                      <div>
                        <div className="font-bold text-sm text-breach-text">{entry.team_name}</div>
                        <div className="text-[10px] text-breach-muted">{entry.member_count} members</div>
                      </div>
                    </div>
                    <div className="text-right">
                      <div className="text-sm font-mono font-bold text-green-400">{entry.total_xp.toLocaleString()}</div>
                      <div className="text-[9px] text-breach-muted uppercase tracking-wider">XP</div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
