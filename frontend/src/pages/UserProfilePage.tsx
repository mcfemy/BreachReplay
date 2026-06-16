import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { axiosInstance } from "../lib/api";
import { useAuthStore } from "../store/auth";

interface CareerTier {
  key: string;
  label: string;
  color: string;
  min_xp: number;
}

interface Achievement {
  key: string;
  title: string;
  desc: string;
  icon: string;
  xp_bonus: number;
  unlocked: boolean;
}

interface Cert {
  id: string;
  cert_key: string;
  title: string;
  subtitle: string;
  tier: string;
  color: string;
  icon: string;
  desc: string;
  criteria_display: string;
  issued_at: string;
  verify_url: string;
  verify_token: string;
}

interface ProfileData {
  id: string;
  email: string;
  full_name: string | null;
  role: string;
  xp_total: number;
  career_tier: CareerTier;
  tier_progress: {
    current_tier: CareerTier;
    next_tier: CareerTier | null;
    xp_in_tier: number;
    xp_to_next: number;
    tier_range: number;
    progress_pct: number;
  };
  global_rank: number;
  achievements: Achievement[];
  unlocked_count: number;
  total_achievements: number;
  recent_xp: Array<{ amount: number; source_type: string; description: string; created_at: string }>;
  stats: { total_sessions: number; avg_score: number };
  member_since: string;
}

const SOURCE_ICON: Record<string, string> = {
  scenario: "⚡",
  daily: "🔐",
  redteam: "🔴",
  achievement: "🏅",
  bonus: "⭐",
};

const TIER_ICONS: Record<string, string> = {
  recruit: "🔰",
  soc_analyst: "🔵",
  incident_responder: "🟣",
  threat_hunter: "🟡",
  security_architect: "🔴",
  ciso: "💎",
};

const CERT_TIER_LABEL: Record<string, string> = {
  bronze: "Bronze",
  silver: "Silver",
  gold: "Gold",
  platinum: "Platinum",
};

const CERT_TIER_STYLE: Record<string, { bg: string; text: string; border: string }> = {
  bronze:   { bg: "rgba(205,127,50,0.12)",  text: "#cd7f32", border: "rgba(205,127,50,0.35)" },
  silver:   { bg: "rgba(192,192,192,0.12)", text: "#c0c0c0", border: "rgba(192,192,192,0.35)" },
  gold:     { bg: "rgba(255,215,0,0.12)",   text: "#ffd700", border: "rgba(255,215,0,0.35)" },
  platinum: { bg: "rgba(229,228,226,0.12)", text: "#e8e8ff", border: "rgba(229,228,226,0.35)" },
};

const CAREER_LADDER = [
  { key: "recruit", label: "Recruit", min: 0 },
  { key: "soc_analyst", label: "SOC Analyst", min: 1000 },
  { key: "incident_responder", label: "Incident Responder", min: 5000 },
  { key: "threat_hunter", label: "Threat Hunter", min: 15000 },
  { key: "security_architect", label: "Security Architect", min: 40000 },
  { key: "ciso", label: "CISO", min: 100000 },
];

function CertCard({ cert }: { cert: Cert }) {
  const style = CERT_TIER_STYLE[cert.tier] || CERT_TIER_STYLE.bronze;
  const verifyUrl = `${window.location.origin}/cert/${cert.verify_token}`;
  const linkedInUrl = `https://www.linkedin.com/shareArticle?mini=true&url=${encodeURIComponent(verifyUrl)}&title=${encodeURIComponent(`I earned the ${cert.title} on BreachReplay`)}&summary=${encodeURIComponent(cert.desc)}`;

  return (
    <div
      className="rounded-xl p-4 border flex flex-col gap-3 transition-all hover:scale-[1.01]"
      style={{ background: style.bg, borderColor: style.border }}
    >
      {/* Header */}
      <div className="flex items-start gap-3">
        <div
          className="w-11 h-11 rounded-lg flex items-center justify-center text-2xl shrink-0"
          style={{ background: style.bg, border: `1px solid ${style.border}` }}
        >
          {cert.icon}
        </div>
        <div className="flex-1 min-w-0">
          <div className="font-bold text-xs text-white leading-tight">{cert.title}</div>
          <div className="text-[9px] text-gray-400 leading-tight mt-0.5">{cert.subtitle}</div>
          <span
            className="inline-block mt-1 text-[8px] font-black uppercase tracking-widest px-1.5 py-0.5 rounded"
            style={{ color: style.text, background: style.bg, border: `1px solid ${style.border}` }}
          >
            {CERT_TIER_LABEL[cert.tier] || cert.tier}
          </span>
        </div>
      </div>

      {/* Footer */}
      <div className="flex items-center justify-between gap-2 pt-1 border-t border-white/5">
        <span className="text-[9px] text-gray-500">
          Issued {new Date(cert.issued_at).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}
        </span>
        <div className="flex gap-2">
          <a
            href={verifyUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="text-[9px] font-bold px-2 py-1 rounded border transition-colors hover:text-white"
            style={{ borderColor: style.border, color: style.text }}
          >
            Verify
          </a>
          <a
            href={linkedInUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="text-[9px] font-bold px-2 py-1 rounded bg-blue-600 text-white hover:bg-blue-500 transition-colors"
          >
            Share
          </a>
        </div>
      </div>
    </div>
  );
}

export default function UserProfilePage() {
  const { user: authUser } = useAuthStore();
  const queryClient = useQueryClient();

  const { data: profile, isLoading } = useQuery<ProfileData>({
    queryKey: ["my-profile"],
    queryFn: () => axiosInstance.get("/profile/me").then((r) => r.data),
  });

  const { data: certsData, isLoading: certsLoading } = useQuery<{ certs: Cert[]; newly_issued: Cert[] }>({
    queryKey: ["my-certs"],
    queryFn: () => axiosInstance.get("/certs/mine").then((r) => r.data),
  });

  const checkCerts = useMutation({
    mutationFn: () => axiosInstance.post("/certs/check").then((r) => r.data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["my-certs"] }),
  });

  if (isLoading) {
    return (
      <div className="min-h-screen bg-breach-bg flex items-center justify-center">
        <div className="w-8 h-8 border-2 border-yellow-500 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (!profile) return (
    <div className="min-h-screen bg-breach-bg p-6 flex items-center justify-center text-breach-muted">
      Could not load profile.
    </div>
  );

  const tp = profile.tier_progress;
  const unlocked = profile.achievements.filter((a) => a.unlocked);
  const locked = profile.achievements.filter((a) => !a.unlocked);
  const certs = certsData?.certs ?? [];

  return (
    <div className="min-h-screen bg-breach-bg p-6">
      <div className="max-w-4xl mx-auto space-y-6">

        {/* Hero: career tier + XP */}
        <div className="bg-breach-surface border border-breach-border rounded-xl p-6">
          <div className="flex items-start gap-6">
            <div
              className="w-20 h-20 rounded-xl flex items-center justify-center text-4xl shrink-0 border-2"
              style={{ borderColor: profile.career_tier.color || "#6b7280", background: `${profile.career_tier.color || "#6b7280"}15` }}
            >
              {TIER_ICONS[profile.career_tier.key] || "🔰"}
            </div>

            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-3 mb-1 flex-wrap">
                <h1 className="text-xl font-black text-breach-text">{profile.full_name || profile.email.split("@")[0]}</h1>
                <span
                  className="text-xs font-bold px-2 py-0.5 rounded-full uppercase tracking-wider"
                  style={{ color: profile.career_tier.color || "#6b7280", background: `${profile.career_tier.color || "#6b7280"}20`, border: `1px solid ${profile.career_tier.color || "#6b7280"}40` }}
                >
                  {profile.career_tier.label || "Recruit"}
                </span>
                {authUser?.role === "admin" && (
                  <span className="text-xs font-bold px-2 py-0.5 rounded-full uppercase tracking-wider bg-purple-500/20 text-purple-400 border border-purple-500/30">
                    Admin
                  </span>
                )}
              </div>
              <div className="text-breach-muted text-sm mb-4">{profile.email}</div>

              {/* XP bar */}
              <div className="mb-3">
                <div className="flex justify-between text-xs mb-1.5">
                  <span className="text-yellow-400 font-bold">{(profile.xp_total || 0).toLocaleString()} XP</span>
                  {tp.next_tier ? (
                    <span className="text-breach-muted">{tp.xp_to_next.toLocaleString()} XP to {tp.next_tier.label}</span>
                  ) : (
                    <span className="text-yellow-400 font-black">MAX TIER — CISO</span>
                  )}
                </div>
                <div className="h-3 bg-gray-800 rounded-full overflow-hidden">
                  <div
                    className="h-full rounded-full transition-all duration-700"
                    style={{
                      width: `${tp.progress_pct}%`,
                      background: `linear-gradient(90deg, ${profile.career_tier.color || "#6b7280"}, ${tp.next_tier?.color || profile.career_tier.color || "#6b7280"})`,
                    }}
                  />
                </div>
              </div>

              <div className="flex flex-wrap gap-6 text-xs">
                <div><span className="text-breach-muted">Global Rank </span><span className="text-white font-bold">#{profile.global_rank}</span></div>
                <div><span className="text-breach-muted">Achievements </span><span className="text-white font-bold">{profile.unlocked_count}/{profile.total_achievements}</span></div>
                <div><span className="text-breach-muted">Certs </span><span className="text-white font-bold">{certs.length}</span></div>
                <div><span className="text-breach-muted">Sessions </span><span className="text-white font-bold">{profile.stats.total_sessions}</span></div>
                <div><span className="text-breach-muted">Avg Score </span><span className="text-white font-bold">{profile.stats.avg_score}%</span></div>
              </div>
            </div>
          </div>
        </div>

        {/* ── Certifications ──────────────────────────────────────────────── */}
        <div className="bg-breach-surface border border-breach-border rounded-xl p-4">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h2 className="text-xs font-bold text-breach-muted uppercase tracking-widest">Verifiable Certifications</h2>
              <p className="text-[9px] text-gray-600 mt-0.5">Shareable credentials — click "Share" to post to LinkedIn</p>
            </div>
            <button
              onClick={() => checkCerts.mutate()}
              disabled={checkCerts.isPending}
              className="text-[10px] font-bold px-3 py-1.5 rounded border border-breach-border text-breach-muted hover:text-breach-text hover:border-breach-accent/40 transition-all disabled:opacity-50"
            >
              {checkCerts.isPending ? "Checking…" : "Check for new certs"}
            </button>
          </div>

          {certsLoading ? (
            <div className="flex justify-center py-6">
              <div className="w-6 h-6 border-2 border-yellow-500 border-t-transparent rounded-full animate-spin" />
            </div>
          ) : certs.length === 0 ? (
            <div className="text-center py-8">
              <div className="text-3xl mb-2">🎓</div>
              <div className="text-xs text-breach-muted mb-1">No certifications yet</div>
              <div className="text-[10px] text-gray-600">Complete scenarios, build streaks, and earn XP to unlock verifiable credentials</div>
            </div>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {certs.map((cert) => <CertCard key={cert.id} cert={cert} />)}
            </div>
          )}

          {/* Available certs teaser (locked) */}
          {certs.length > 0 && certs.length < 8 && (
            <div className="mt-4 pt-4 border-t border-breach-border">
              <div className="text-[9px] text-gray-600 mb-2 uppercase tracking-widest">Available to Earn</div>
              <div className="flex flex-wrap gap-2">
                {["ir_fundamentals","certified_analyst","red_team_operator","ransomware_defender","daily_champion","critical_infra_defender","supply_chain_expert","elite_operator"]
                  .filter(key => !certs.find(c => c.cert_key === key))
                  .map(key => (
                    <span key={key} className="text-[9px] px-2 py-1 rounded bg-breach-bg border border-breach-border text-gray-500">
                      🔒 {key.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase())}
                    </span>
                  ))
                }
              </div>
            </div>
          )}
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Achievements */}
          <div className="lg:col-span-2 space-y-4">
            {unlocked.length > 0 && (
              <div className="bg-breach-surface border border-breach-border rounded-xl p-4">
                <h2 className="text-xs font-bold text-breach-muted uppercase tracking-widest mb-3">Unlocked — {unlocked.length}</h2>
                <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                  {unlocked.map((a) => (
                    <div key={a.key} className="flex items-start gap-2 p-3 rounded-lg bg-green-500/5 border border-green-500/20">
                      <span className="text-xl shrink-0">{a.icon}</span>
                      <div className="min-w-0">
                        <div className="text-xs font-bold text-green-300 leading-tight">{a.title}</div>
                        <div className="text-[9px] text-gray-500 leading-tight mt-0.5">{a.desc}</div>
                        {a.xp_bonus > 0 && <div className="text-[9px] text-yellow-500 mt-1">+{a.xp_bonus} XP</div>}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            <div className="bg-breach-surface border border-breach-border rounded-xl p-4">
              <h2 className="text-xs font-bold text-breach-muted uppercase tracking-widest mb-3">Locked — {locked.length}</h2>
              {locked.length === 0 ? (
                <p className="text-xs text-yellow-400 font-bold">🏆 All achievements unlocked!</p>
              ) : (
                <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                  {locked.map((a) => (
                    <div key={a.key} className="flex items-start gap-2 p-3 rounded-lg bg-breach-bg border border-breach-border opacity-50">
                      <span className="text-xl grayscale shrink-0">{a.icon}</span>
                      <div className="min-w-0">
                        <div className="text-xs font-bold text-gray-500 leading-tight">{a.title}</div>
                        <div className="text-[9px] text-gray-600 leading-tight mt-0.5">{a.desc}</div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* Right column */}
          <div className="space-y-4">
            <div className="bg-breach-surface border border-breach-border rounded-xl p-4">
              <h2 className="text-xs font-bold text-breach-muted uppercase tracking-widest mb-3">Recent XP</h2>
              {profile.recent_xp.length === 0 ? (
                <p className="text-xs text-breach-muted">No XP yet. Complete a training activity!</p>
              ) : (
                <div className="space-y-2.5">
                  {profile.recent_xp.map((tx, i) => (
                    <div key={i} className="flex items-start gap-2">
                      <span className="text-sm mt-0.5 shrink-0">{SOURCE_ICON[tx.source_type] || "⭐"}</span>
                      <div className="flex-1 min-w-0">
                        <div className="text-[10px] text-breach-text leading-tight">{tx.description}</div>
                        <div className="text-[9px] text-breach-muted">{new Date(tx.created_at).toLocaleDateString()}</div>
                      </div>
                      <span className="text-xs font-bold text-yellow-400 shrink-0">+{tx.amount}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div className="bg-breach-surface border border-breach-border rounded-xl p-4">
              <h2 className="text-xs font-bold text-breach-muted uppercase tracking-widest mb-3">Career Ladder</h2>
              <div className="space-y-1.5">
                {CAREER_LADDER.map((tier) => {
                  const isNow = profile.career_tier.key === tier.key;
                  const done = (profile.xp_total || 0) >= tier.min;
                  return (
                    <div key={tier.key} className={`flex items-center gap-2 px-2 py-1.5 rounded text-xs ${isNow ? "bg-yellow-500/10 border border-yellow-500/30" : done ? "" : "opacity-30"}`}>
                      <span className={done ? "" : "grayscale"}>{TIER_ICONS[tier.key]}</span>
                      <span className={isNow ? "text-yellow-300 font-bold" : done ? "text-breach-text" : "text-gray-600"}>{tier.label}</span>
                      <span className="ml-auto text-[9px] text-breach-muted">{tier.min.toLocaleString()} XP</span>
                      {isNow && <span className="text-[8px] text-yellow-500 font-black uppercase">NOW</span>}
                      {done && !isNow && <span className="text-[8px] text-green-500">✓</span>}
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
