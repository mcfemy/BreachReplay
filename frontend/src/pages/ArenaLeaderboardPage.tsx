import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { axiosInstance } from "../lib/api";
import { useAuthStore } from "../store/auth";

interface ArenaLeaderboardEntry {
  rank: number;
  user_id: string;
  display_name: string;
  arena_rating: number;
  arena_wins: number;
  arena_losses: number;
  arena_matches_played: number;
  is_current_user: boolean;
}

/**
 * Live Arena Mode (Phase I) leaderboard — ranked by ELO-style
 * arena_rating (app/services/arena_rating_service.py), distinct from the
 * XP-based GlobalLeaderboard (LeaderboardPage.tsx). Kept in the arena's own
 * dark/mono visual language (matching ArenaLobbyPage.tsx/ArenaMatchPage.tsx)
 * rather than the breach-* theme, since it's part of the arena mode's own
 * identity, not the broader training-platform chrome.
 */
export default function ArenaLeaderboardPage() {
  const navigate = useNavigate();
  const { user } = useAuthStore();

  const { data: entries = [], isLoading } = useQuery<ArenaLeaderboardEntry[]>({
    queryKey: ["arena-leaderboard"],
    queryFn: () => axiosInstance.get("/arena/leaderboard?limit=100").then((r) => r.data),
    staleTime: 30_000,
  });

  const winRate = (e: ArenaLeaderboardEntry) =>
    e.arena_matches_played > 0 ? Math.round((e.arena_wins / e.arena_matches_played) * 100) : 0;

  return (
    <div className="min-h-screen bg-gray-950 text-white font-mono">
      <div className="max-w-2xl mx-auto px-4 py-10">
        <div className="flex items-center gap-3 mb-8">
          <button onClick={() => navigate("/arena")} className="text-gray-500 hover:text-gray-300 text-xs">
            ← Arena
          </button>
          <span className="text-gray-700">|</span>
          <h1 className="text-xl font-black uppercase tracking-widest">🏆 Arena Leaderboard</h1>
        </div>
        <p className="text-gray-500 text-xs mb-8">
          Ranked by ELO-style rating across all Live Arena matches (PvP and vs-AI). Every player
          starts at 1200 — only players who've completed at least one match are listed.
        </p>

        {isLoading ? (
          <div className="flex justify-center py-16">
            <div className="w-6 h-6 border-2 border-cyan-500 border-t-transparent rounded-full animate-spin" />
          </div>
        ) : (
          <div className="space-y-1">
            {entries.map((entry) => {
              const isMe = entry.is_current_user || entry.user_id === user?.id;
              return (
                <div
                  key={entry.user_id}
                  className={`flex items-center gap-3 px-4 py-3 rounded-lg transition-all border ${
                    isMe ? "bg-cyan-500/10 border-cyan-500/30" : "bg-gray-900/60 border-gray-800 hover:border-gray-600"
                  }`}
                >
                  <div
                    className={`w-8 text-center text-sm font-black ${
                      entry.rank === 1
                        ? "text-yellow-400"
                        : entry.rank === 2
                        ? "text-gray-300"
                        : entry.rank === 3
                        ? "text-amber-600"
                        : "text-gray-600"
                    }`}
                  >
                    {entry.rank <= 3 ? ["🥇", "🥈", "🥉"][entry.rank - 1] : `#${entry.rank}`}
                  </div>

                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className={`text-sm font-bold truncate ${isMe ? "text-cyan-300" : "text-white"}`}>
                        {entry.display_name}
                        {isMe && <span className="ml-1 text-[9px] text-cyan-500 uppercase">(you)</span>}
                      </span>
                    </div>
                    <div className="text-[10px] text-gray-600">
                      {entry.arena_wins}W – {entry.arena_losses}L · {winRate(entry)}% win rate ·{" "}
                      {entry.arena_matches_played} matches
                    </div>
                  </div>

                  <div className="text-right">
                    <div className="text-lg font-black text-cyan-400">{entry.arena_rating}</div>
                    <div className="text-[9px] text-gray-600 uppercase tracking-widest">Rating</div>
                  </div>
                </div>
              );
            })}

            {entries.length === 0 && (
              <div className="text-center py-16 text-gray-600">
                <div className="text-4xl mb-3">⚔️</div>
                <p className="text-sm">No rated matches yet. Play one to get on the board.</p>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
