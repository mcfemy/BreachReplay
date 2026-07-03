import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { useAuthStore } from "../store/auth";

// ── Types ──────────────────────────────────────────────────────────────────
type Mode = "pvp" | "human_defends_vs_ai" | "human_attacks_vs_ai";
type Difficulty = "easy" | "medium" | "hard";

interface Archetype {
  key: string;
  label: string;
  industry_vertical: string;
  difficulty: string;
  size: string;
}

// ORG_ARCHETYPES isn't exposed over the API (Phase A kept it a Python
// constant, not a DB-backed/listable resource) — mirroring its two known
// keys here as display metadata is the simplest option that doesn't
// require a new backend endpoint just for a picker. If a future phase adds
// a GET /arena/archetypes endpoint, swap this constant for a query.
const ARCHETYPES: Archetype[] = [
  { key: "small_healthcare", label: "Regional Clinic Network", industry_vertical: "Healthcare", difficulty: "Beginner org", size: "Small (8-10 hosts)" },
  { key: "energy_utility", label: "Regional Energy Utility", industry_vertical: "Energy / OT", difficulty: "Advanced org", size: "Large (12-15 hosts)" },
];

interface CreateMatchResponse {
  id: string;
  mode: Mode;
  archetype_key: string;
  difficulty: Difficulty;
  status: string;
  attacker_user_id: string | null;
  defender_user_id: string | null;
}

interface MatchSummary {
  id: string;
  mode: Mode;
  archetype_key: string;
  difficulty: Difficulty;
  status: string;
  attacker_user_id: string | null;
  defender_user_id: string | null;
}

const MODE_CARDS: { mode: Mode; icon: string; title: string; description: string }[] = [
  {
    mode: "pvp",
    icon: "⚔️",
    title: "PvP",
    description: "Face another human. One of you attacks the simulated org, the other defends it live — same seeded org, real bidirectional state.",
  },
  {
    mode: "human_defends_vs_ai",
    icon: "🛡️",
    title: "Defend vs AI Attacker",
    description: "You run the SOC. A deterministic AI attacker probes, escalates, and tries to deploy impact against your org — contain it before it wins.",
  },
  {
    mode: "human_attacks_vs_ai",
    icon: "🎯",
    title: "Attack vs AI Defender",
    description: "You're the intrusion. A deterministic AI defender bot reacts to your moves in real time — outmaneuver it before you're contained.",
  },
];

const DIFF_META: Record<Difficulty, { label: string; color: string; desc: string }> = {
  easy: { label: "Easy", color: "border-green-500/40 text-green-400 bg-green-500/10", desc: "Bot acts greedily and noisily — good for learning the mechanics." },
  medium: { label: "Medium", color: "border-yellow-500/40 text-yellow-400 bg-yellow-500/10", desc: "Balanced pacing — evaluates more of the org before acting." },
  hard: { label: "Hard", color: "border-red-500/40 text-red-400 bg-red-500/10", desc: "Bot plays near-optimally and reacts fast — a real test." },
};

type FlowState = "select" | "pvp_waiting" | "queue_waiting";

interface QueueStatusResponse {
  status: "not_queued" | "waiting" | "matched";
  match_id: string | null;
  estimated_wait_seconds: number | null;
}

export default function ArenaLobbyPage() {
  const navigate = useNavigate();
  const { user } = useAuthStore();

  const [flow, setFlow] = useState<FlowState>("select");
  const [mode, setMode] = useState<Mode | null>(null);
  const [difficulty, setDifficulty] = useState<Difficulty>("medium");
  const [archetypeKey, setArchetypeKey] = useState<string>(ARCHETYPES[0].key);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // PvP waiting-room state
  const [opponentUserId, setOpponentUserId] = useState("");
  const [pendingMatch, setPendingMatch] = useState<MatchSummary | null>(null);
  const [copied, setCopied] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Phase I: matchmaking queue waiting-room state
  const [queueEstimatedWait, setQueueEstimatedWait] = useState<number | null>(null);
  const queuePollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
      if (queuePollRef.current) clearInterval(queuePollRef.current);
    };
  }, []);

  async function handleCreateMatch() {
    if (!mode) return;
    setError(null);
    setCreating(true);
    try {
      // Manual-invite path (Phase F design, still supported): POST
      // /arena/matches is the only way to set defender_user_id directly, and
      // it always creates a brand-new match — there's no "join an existing
      // match by id" endpoint. So this path only works if the creator
      // already knows their opponent's user id and supplies it as
      // defender_user_id up front (arena.py's create_match explicitly
      // allows this: pvp mode accepts both ids as long as the current user
      // is one of them). If left blank, we fall back to "create match,
      // opponent TBD" and poll GET /arena/matches/{id} until someone
      // attaches. Phase I's handleJoinQueue (the "Quick Match" button)
      // solves the same problem without needing to know a user id at all,
      // via POST /arena/queue/join — this manual path stays for
      // invite-a-specific-friend use cases.
      const body: Record<string, unknown> = { mode, archetype_key: archetypeKey, difficulty };
      if (mode === "pvp" && opponentUserId.trim()) {
        body.defender_user_id = opponentUserId.trim();
      }
      const data = await api.post<CreateMatchResponse>("/arena/matches", body);

      if (mode === "pvp") {
        if (data.defender_user_id) {
          // Opponent already attached at creation time — go straight in.
          navigate(`/arena/match/${data.id}`);
          return;
        }
        setPendingMatch({
          id: data.id,
          mode: data.mode,
          archetype_key: data.archetype_key,
          difficulty: data.difficulty,
          status: data.status,
          attacker_user_id: data.attacker_user_id,
          defender_user_id: data.defender_user_id,
        });
        setFlow("pvp_waiting");
        pollRef.current = setInterval(async () => {
          try {
            const m = await api.get<MatchSummary>(`/arena/matches/${data.id}`);
            setPendingMatch(m);
            if (m.defender_user_id && m.attacker_user_id) {
              if (pollRef.current) clearInterval(pollRef.current);
              navigate(`/arena/match/${data.id}`);
            }
          } catch {
            // transient — keep polling
          }
        }, 2500);
      } else {
        navigate(`/arena/match/${data.id}`);
      }
    } catch (e: any) {
      setError(e.message || "Failed to create match");
    } finally {
      setCreating(false);
    }
  }

  function handleCopyInvite() {
    if (!pendingMatch) return;
    // There's no join-by-link endpoint (see the design note above
    // handleCreateMatch) — the match id itself, plus your own user id, is
    // what an opponent's client actually needs to pair up via a future
    // "create with defender_user_id" call. Copying the raw match id is the
    // honest version of "share this match ID" the plan explicitly allows.
    navigator.clipboard.writeText(pendingMatch.id);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  function handleCancelWait() {
    if (pollRef.current) clearInterval(pollRef.current);
    setPendingMatch(null);
    setFlow("select");
  }

  // Phase I: "Quick Match" — auto-pair with any other waiting human via the
  // matchmaking queue, instead of needing to already know an opponent's
  // user id (the only PvP pairing path before this phase).
  async function handleJoinQueue() {
    setError(null);
    setFlow("queue_waiting");
    try {
      const data = await api.post<QueueStatusResponse>("/arena/queue/join", {});
      if (data.status === "matched" && data.match_id) {
        navigate(`/arena/match/${data.match_id}`);
        return;
      }
      setQueueEstimatedWait(data.estimated_wait_seconds);
      queuePollRef.current = setInterval(async () => {
        try {
          const s = await api.get<QueueStatusResponse>("/arena/queue/status");
          if (s.status === "matched" && s.match_id) {
            if (queuePollRef.current) clearInterval(queuePollRef.current);
            navigate(`/arena/match/${s.match_id}`);
          } else {
            setQueueEstimatedWait(s.estimated_wait_seconds);
          }
        } catch {
          // transient — keep polling
        }
      }, 3000);
    } catch (e: any) {
      setError(e.message || "Failed to join matchmaking queue");
      setFlow("select");
    }
  }

  async function handleCancelQueue() {
    if (queuePollRef.current) clearInterval(queuePollRef.current);
    setFlow("select");
    try {
      await api.delete("/arena/queue/leave");
    } catch {
      // best-effort — the entry will just sit unmatched until it would
      // otherwise be paired; nothing destructive happens either way.
    }
  }

  // ── PvP waiting room ───────────────────────────────────────────────────
  if (flow === "pvp_waiting" && pendingMatch) {
    return (
      <div className="min-h-screen bg-gray-950 text-white flex items-center justify-center px-4">
        <div className="max-w-lg w-full border border-gray-800 rounded-xl p-8 text-center">
          <div className="text-5xl mb-4">⚔️</div>
          <h1 className="text-2xl font-black mb-2">Waiting for an opponent</h1>
          <p className="text-gray-500 text-sm mb-6">
            You're the attacker in this match, seat unfilled. Send your opponent this match ID —
            they'll need it (plus your user ID, below) to start a match paired with you.
            Once a defender is attached, this screen advances automatically.
          </p>

          <div className="flex items-center gap-2 bg-gray-900 border border-gray-800 rounded-lg p-3 mb-3">
            <code className="flex-1 text-xs text-cyan-400 truncate text-left">{pendingMatch.id}</code>
            <button
              onClick={handleCopyInvite}
              className="shrink-0 text-xs px-3 py-1.5 rounded bg-gray-800 hover:bg-gray-700 text-white font-bold transition-colors"
            >
              {copied ? "Copied!" : "Copy"}
            </button>
          </div>
          <p className="text-[10px] text-gray-600 mb-4">
            Your user ID (share this too): <span className="text-gray-400 font-mono">{user?.id}</span>
          </p>

          <div className="flex items-center justify-center gap-2 text-xs text-yellow-500 mb-6">
            <div className="w-2 h-2 rounded-full bg-yellow-500 animate-ping" />
            Waiting for defender to join...
          </div>

          <button
            onClick={handleCancelWait}
            className="text-xs text-gray-500 hover:text-gray-300 transition-colors"
          >
            Cancel and pick a different mode
          </button>
        </div>
      </div>
    );
  }

  // ── Phase I: matchmaking queue waiting room ────────────────────────────
  if (flow === "queue_waiting") {
    return (
      <div className="min-h-screen bg-gray-950 text-white flex items-center justify-center px-4">
        <div className="max-w-lg w-full border border-gray-800 rounded-xl p-8 text-center">
          <div className="text-5xl mb-4">🔎</div>
          <h1 className="text-2xl font-black mb-2">Finding an opponent...</h1>
          <p className="text-gray-500 text-sm mb-6">
            You'll be paired with the next human who joins the queue — attacker/defender roles are
            assigned randomly, and the target organization is a random archetype. This screen
            advances automatically the moment you're matched.
          </p>

          <div className="flex items-center justify-center gap-2 text-xs text-cyan-400 mb-2">
            <div className="w-2 h-2 rounded-full bg-cyan-400 animate-ping" />
            Waiting in queue...
          </div>
          {queueEstimatedWait !== null && (
            <p className="text-[10px] text-gray-600 mb-6">
              Estimated wait: ~{queueEstimatedWait}s
            </p>
          )}

          <button
            onClick={handleCancelQueue}
            className="text-xs text-gray-500 hover:text-gray-300 transition-colors"
          >
            Leave queue
          </button>
        </div>
      </div>
    );
  }

  // ── Mode / difficulty / archetype selector ─────────────────────────────
  return (
    <div className="min-h-screen bg-gray-950 text-white">
      <div className="max-w-4xl mx-auto px-4 py-10">
        <div className="text-center mb-10">
          <div className="text-5xl mb-4">⚔️</div>
          <h1 className="text-4xl font-black text-white mb-3">Live Arena</h1>
          <p className="text-gray-400 text-lg max-w-xl mx-auto">
            A real, deterministic simulated org — attacker and defender both act against the SAME
            live state. No scripted outcomes, no repeat matches.
          </p>
          <button
            onClick={() => navigate("/arena/leaderboard")}
            className="mt-4 text-xs text-yellow-500 hover:text-yellow-400 font-bold uppercase tracking-widest transition-colors"
          >
            🏆 View Arena Leaderboard
          </button>
        </div>

        {error && (
          <div className="border border-red-500/40 bg-red-500/10 rounded-lg p-3 mb-6 text-sm text-red-300">
            ⚠ {error}
          </div>
        )}

        {/* Mode cards */}
        <div className="grid gap-4 md:grid-cols-3 mb-8">
          {MODE_CARDS.map((card) => (
            <div
              key={card.mode}
              onClick={() => setMode(card.mode)}
              className={`border rounded-xl p-5 cursor-pointer transition-all group ${
                mode === card.mode
                  ? "border-cyan-500 bg-cyan-500/10 shadow-[0_0_20px_rgba(34,211,238,0.15)]"
                  : "border-gray-800 hover:border-gray-600"
              }`}
            >
              <div className="text-3xl mb-3">{card.icon}</div>
              <h3 className={`text-sm font-bold mb-2 ${mode === card.mode ? "text-cyan-300" : "text-white"}`}>
                {card.title}
              </h3>
              <p className="text-xs text-gray-500 leading-relaxed">{card.description}</p>
            </div>
          ))}
        </div>

        {mode && (
          <div className="space-y-6">
            {/* Difficulty picker — only relevant for AI modes */}
            {mode !== "pvp" && (
              <div>
                <div className="text-xs text-gray-600 uppercase tracking-widest mb-2">
                  AI {mode === "human_defends_vs_ai" ? "Attacker" : "Defender"} Difficulty
                </div>
                <div className="grid grid-cols-3 gap-3">
                  {(["easy", "medium", "hard"] as Difficulty[]).map((d) => (
                    <button
                      key={d}
                      onClick={() => setDifficulty(d)}
                      className={`border rounded-lg p-3 text-left transition-all ${
                        difficulty === d ? DIFF_META[d].color : "border-gray-800 text-gray-500 hover:border-gray-600"
                      }`}
                    >
                      <div className="text-xs font-bold uppercase mb-1">{DIFF_META[d].label}</div>
                      <div className="text-[10px] opacity-80 leading-relaxed">{DIFF_META[d].desc}</div>
                    </button>
                  ))}
                </div>
              </div>
            )}

            {/* Phase I: Quick Match — auto-pair via the matchmaking queue,
                no need to already know an opponent's user id. */}
            {mode === "pvp" && (
              <button
                onClick={handleJoinQueue}
                className="w-full py-3 rounded-lg border border-cyan-500/50 bg-cyan-500/10 hover:bg-cyan-500/20 text-cyan-300 font-bold text-sm uppercase tracking-wider transition-colors"
              >
                🔎 Quick Match — Auto-Pair With Next Available Opponent
              </button>
            )}

            {/* Opponent id — PvP manual-invite fallback, for when you already
                know who you want to play (e.g. a friend). Leaving this
                blank falls back to "create match, opponent TBD" and a
                waiting screen. */}
            {mode === "pvp" && (
              <div>
                <div className="text-xs text-gray-600 uppercase tracking-widest mb-2 flex items-center gap-2">
                  <span className="flex-1 border-t border-gray-800" />
                  <span>or invite by user ID</span>
                  <span className="flex-1 border-t border-gray-800" />
                </div>
                <div className="text-xs text-gray-600 uppercase tracking-widest mb-2">
                  Opponent User ID <span className="text-gray-700 normal-case">(optional — leave blank to wait for one)</span>
                </div>
                <input
                  value={opponentUserId}
                  onChange={(e) => setOpponentUserId(e.target.value)}
                  placeholder="Paste the defender's user ID if you already have it"
                  className="w-full bg-gray-900 border border-gray-800 text-white text-sm px-3 py-2.5 rounded-lg focus:outline-none focus:border-cyan-500 transition-colors"
                />
                <p className="text-[10px] text-gray-700 mt-1">
                  You'll be the attacker. Your own user ID is {user?.id} — share it with whoever you want to invite.
                </p>
              </div>
            )}

            {/* Archetype picker */}
            <div>
              <div className="text-xs text-gray-600 uppercase tracking-widest mb-2">Target Organization</div>
              <div className="grid gap-3 md:grid-cols-2">
                {ARCHETYPES.map((a) => (
                  <button
                    key={a.key}
                    onClick={() => setArchetypeKey(a.key)}
                    className={`border rounded-lg p-4 text-left transition-all ${
                      archetypeKey === a.key
                        ? "border-cyan-500 bg-cyan-500/5"
                        : "border-gray-800 hover:border-gray-600"
                    }`}
                  >
                    <div className="text-sm font-bold text-white mb-1">{a.label}</div>
                    <div className="text-[10px] text-gray-500 uppercase tracking-wider">
                      {a.industry_vertical} · {a.size} · {a.difficulty}
                    </div>
                  </button>
                ))}
              </div>
            </div>

            <button
              onClick={handleCreateMatch}
              disabled={creating}
              className="w-full py-4 rounded-xl bg-cyan-600 hover:bg-cyan-500 disabled:opacity-50 disabled:cursor-not-allowed text-white font-black text-lg tracking-wide transition-all active:scale-[0.98]"
            >
              {creating
                ? "Spinning up simulated org..."
                : mode === "pvp"
                ? "⚔️ Create Match & Invite Opponent"
                : "⚔️ Enter the Arena"}
            </button>
          </div>
        )}

        <p className="text-center text-[10px] text-gray-700 mt-8">
          Signed in as {user?.email} — every match is seeded and fully reproducible.
        </p>
      </div>
    </div>
  );
}
