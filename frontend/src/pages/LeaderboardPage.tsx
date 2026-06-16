import { useQuery } from "@tanstack/react-query";
import { axiosInstance } from "../lib/api";
import { useAuthStore } from "../store/auth";

interface LeaderboardEntry {
  rank: number;
  user_id: string;
  display_name: string;
  xp_total: number;
  career_tier: { key: string; label: string; color: string };
  achievements_count: number;
}

const TIER_ICONS: Record<string, string> = {
  recruit: "🔰",
  soc_analyst: "🔵",
  incident_responder: "🟣",
  threat_hunter: "🟡",
  security_architect: "🔴",
  ciso: "💎",
};

export default function LeaderboardPage() {
  const { user } = useAuthStore();

  const { data: entries = [], isLoading } = useQuery<LeaderboardEntry[]>({
    queryKey: ["leaderboard"],
    queryFn: () => axiosInstance.get("/profile/leaderboard?limit=100").then((r) => r.data),
    staleTime: 60_000,
  });

  const myEntry = entries.find((e) => e.display_name === (user?.full_name || user?.email?.split("@")[0]));

  return (
    <div className="min-h-screen bg-breach-bg p-6">
      <div className="max-w-2xl mx-auto">
        {/* Header */}
        <div className="mb-8">
          <h1 className="text-xl font-black text-breach-text uppercase tracking-widest">Global Leaderboard</h1>
          <p className="text-breach-muted text-xs mt-1">Ranked by total XP earned across all training activities</p>
        </div>

        {/* Top 3 podium */}
        {entries.length >= 3 && (
          <div className="flex items-end justify-center gap-2 mb-8">
            {/* 2nd */}
            <div className="flex flex-col items-center">
              <div className="text-2xl mb-1">{TIER_ICONS[entries[1]?.career_tier?.key] || "🔵"}</div>
              <div className="w-20 bg-gray-700 rounded-t-lg pt-4 pb-2 px-2 text-center">
                <div className="text-[10px] text-gray-400 font-bold">#2</div>
                <div className="text-xs text-white font-bold truncate">{entries[1]?.display_name}</div>
                <div className="text-[9px] text-yellow-400">{(entries[1]?.xp_total || 0).toLocaleString()} XP</div>
              </div>
            </div>
            {/* 1st */}
            <div className="flex flex-col items-center">
              <div className="text-3xl mb-1">👑</div>
              <div className="w-24 bg-gradient-to-b from-yellow-500/30 to-gray-700 rounded-t-lg pt-6 pb-2 px-2 text-center border-t border-yellow-500/50">
                <div className="text-[10px] text-yellow-400 font-black">#1</div>
                <div className="text-xs text-white font-bold truncate">{entries[0]?.display_name}</div>
                <div className="text-[9px] text-yellow-400">{(entries[0]?.xp_total || 0).toLocaleString()} XP</div>
              </div>
            </div>
            {/* 3rd */}
            <div className="flex flex-col items-center">
              <div className="text-2xl mb-1">{TIER_ICONS[entries[2]?.career_tier?.key] || "🔵"}</div>
              <div className="w-20 bg-gray-800 rounded-t-lg pt-2 pb-2 px-2 text-center">
                <div className="text-[10px] text-gray-400 font-bold">#3</div>
                <div className="text-xs text-white font-bold truncate">{entries[2]?.display_name}</div>
                <div className="text-[9px] text-yellow-400">{(entries[2]?.xp_total || 0).toLocaleString()} XP</div>
              </div>
            </div>
          </div>
        )}

        {/* Full list */}
        {isLoading ? (
          <div className="flex justify-center py-16">
            <div className="w-6 h-6 border-2 border-yellow-500 border-t-transparent rounded-full animate-spin" />
          </div>
        ) : (
          <div className="space-y-1">
            {entries.map((entry) => {
              const isMe = entry.user_id === user?.id;
              return (
                <div
                  key={entry.user_id}
                  className={`flex items-center gap-3 px-4 py-3 rounded-lg transition-all ${
                    isMe
                      ? "bg-yellow-500/10 border border-yellow-500/30"
                      : "bg-breach-surface border border-breach-border hover:border-breach-blue/30"
                  }`}
                >
                  {/* Rank */}
                  <div className={`w-8 text-center text-sm font-black ${
                    entry.rank === 1 ? "text-yellow-400" :
                    entry.rank === 2 ? "text-gray-300" :
                    entry.rank === 3 ? "text-amber-600" : "text-breach-muted"
                  }`}>
                    {entry.rank <= 3 ? ["🥇","🥈","🥉"][entry.rank - 1] : `#${entry.rank}`}
                  </div>

                  {/* Tier icon */}
                  <span className="text-lg">{TIER_ICONS[entry.career_tier?.key] || "🔰"}</span>

                  {/* Name + tier */}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className={`text-sm font-bold truncate ${isMe ? "text-yellow-300" : "text-breach-text"}`}>
                        {entry.display_name}
                        {isMe && <span className="ml-1 text-[9px] text-yellow-500 uppercase">(you)</span>}
                      </span>
                    </div>
                    <div className="text-[10px] text-breach-muted">{entry.career_tier?.label || "Recruit"}</div>
                  </div>

                  {/* Achievements */}
                  <div className="text-[10px] text-breach-muted text-right">
                    <div className="text-breach-text font-bold">{(entry.xp_total || 0).toLocaleString()} XP</div>
                    <div>{entry.achievements_count} badges</div>
                  </div>
                </div>
              );
            })}

            {entries.length === 0 && (
              <div className="text-center py-16 text-breach-muted">
                <div className="text-4xl mb-3">🏆</div>
                <p className="text-sm">No one's on the board yet. Be first.</p>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
