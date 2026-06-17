import { useQuery } from "@tanstack/react-query";
import { useParams, Link } from "react-router-dom";
import { axiosInstance } from "../lib/api";

interface CertVerification {
  valid: boolean;
  title: string;
  subtitle: string;
  tier: string;
  color: string;
  icon: string;
  desc: string;
  issued_to: string;
  issued_at: string;
  verify_token: string;
}

const TIER_STYLE: Record<string, { glow: string; bg: string; border: string; text: string; label: string }> = {
  bronze:   { glow: "rgba(205,127,50,0.3)",  bg: "rgba(205,127,50,0.08)",  border: "rgba(205,127,50,0.4)",   text: "#cd7f32", label: "Bronze Certification" },
  silver:   { glow: "rgba(192,192,192,0.3)", bg: "rgba(192,192,192,0.08)", border: "rgba(192,192,192,0.4)",  text: "#c0c0c0", label: "Silver Certification" },
  gold:     { glow: "rgba(255,215,0,0.3)",   bg: "rgba(255,215,0,0.08)",   border: "rgba(255,215,0,0.4)",    text: "#ffd700", label: "Gold Certification" },
  platinum: { glow: "rgba(229,228,226,0.3)", bg: "rgba(229,228,226,0.08)", border: "rgba(229,228,226,0.4)",  text: "#e8e8ff", label: "Platinum Certification" },
};

export default function CertificatePage() {
  const { token } = useParams<{ token: string }>();

  const { data: cert, isLoading, isError } = useQuery<CertVerification>({
    queryKey: ["cert-verify", token],
    queryFn: () => axiosInstance.get(`/certs/verify/${token}`).then((r) => r.data),
    retry: false,
  });

  if (isLoading) {
    return (
      <div className="min-h-screen bg-[#0a0b0d] flex items-center justify-center">
        <div className="w-8 h-8 border-2 border-yellow-500 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (isError || !cert) {
    return (
      <div className="min-h-screen bg-[#0a0b0d] flex items-center justify-center p-6">
        <div className="text-center max-w-sm">
          <div className="text-5xl mb-4">❌</div>
          <h1 className="text-white text-xl font-black mb-2">Certificate Not Found</h1>
          <p className="text-gray-500 text-sm mb-6">This certificate link is invalid or may have been revoked.</p>
          <Link to="/" className="text-sm text-blue-400 hover:text-blue-300">← Back to BreachReplay</Link>
        </div>
      </div>
    );
  }

  const style = TIER_STYLE[cert.tier] || TIER_STYLE.bronze;
  const verifyUrl = window.location.href;
  const linkedInUrl = `https://www.linkedin.com/shareArticle?mini=true&url=${encodeURIComponent(verifyUrl)}&title=${encodeURIComponent(`I earned the ${cert.title} on BreachReplay`)}&summary=${encodeURIComponent(cert.desc)}`;
  const twitterUrl = `https://twitter.com/intent/tweet?text=${encodeURIComponent(`I just earned the "${cert.title}" certification on @BreachReplay — the world's first addictive cybersecurity training platform. Verify it: ${verifyUrl}`)}`;

  return (
    <div className="min-h-screen bg-[#0a0b0d] flex flex-col items-center justify-center p-6">
      {/* Certificate card */}
      <div className="w-full max-w-lg">
        {/* Glow effect behind card */}
        <div
          className="absolute inset-0 pointer-events-none"
          style={{ boxShadow: `0 0 120px 40px ${style.glow}`, borderRadius: "1.5rem", zIndex: 0 }}
        />

        <div
          className="relative z-10 rounded-2xl border p-8 text-center"
          style={{ background: style.bg, borderColor: style.border, boxShadow: `0 0 60px 0 ${style.glow}` }}
        >
          {/* BreachReplay branding */}
          <div className="flex items-center justify-center gap-2 mb-6">
            <span className="text-breach-accent font-black tracking-tight text-sm">BREACH</span>
            <span className="text-white font-black tracking-tight text-sm">REPLAY</span>
            <span className="text-gray-600 text-xs">· Verifiable Credential</span>
          </div>

          {/* Cert icon */}
          <div
            className="w-24 h-24 rounded-2xl flex items-center justify-center text-5xl mx-auto mb-5 border-2"
            style={{ borderColor: style.border, background: `${style.bg}` }}
          >
            {cert.icon}
          </div>

          {/* Tier badge */}
          <div
            className="inline-block text-[10px] font-black uppercase tracking-widest px-3 py-1 rounded-full mb-3"
            style={{ color: style.text, background: style.bg, border: `1px solid ${style.border}` }}
          >
            {style.label}
          </div>

          {/* Title */}
          <h1 className="text-2xl font-black text-white leading-tight mb-1">{cert.title}</h1>
          <p className="text-xs text-gray-500 mb-5">{cert.subtitle}</p>

          {/* Issued to */}
          <div
            className="rounded-xl p-4 mb-5 border"
            style={{ background: "rgba(255,255,255,0.03)", borderColor: "rgba(255,255,255,0.08)" }}
          >
            <div className="text-[10px] text-gray-600 uppercase tracking-widest mb-1">Awarded to</div>
            <div className="text-white font-black text-lg">{cert.issued_to}</div>
            <div className="text-[10px] text-gray-500 mt-1">
              Issued {new Date(cert.issued_at).toLocaleDateString("en-US", { month: "long", day: "numeric", year: "numeric" })}
            </div>
          </div>

          {/* Description */}
          <p className="text-xs text-gray-400 leading-relaxed mb-6">{cert.desc}</p>

          {/* Verification badge */}
          <div className="flex items-center justify-center gap-2 mb-6">
            <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-green-500/10 border border-green-500/30">
              <span className="text-green-400 text-sm">✓</span>
              <span className="text-green-400 text-[10px] font-bold">Verified Authentic</span>
            </div>
          </div>

          {/* Token */}
          <div className="text-[8px] text-gray-700 font-mono break-all mb-6">
            Credential ID: {cert.verify_token}
          </div>

          {/* Share buttons */}
          <div className="flex gap-3 justify-center flex-wrap">
            <a
              href={linkedInUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-blue-700 hover:bg-blue-600 text-white text-xs font-bold transition-colors"
            >
              <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
                <path d="M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433c-1.144 0-2.063-.926-2.063-2.065 0-1.138.92-2.063 2.063-2.063 1.14 0 2.064.925 2.064 2.063 0 1.139-.925 2.065-2.064 2.065zm1.782 13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.222 0h.003z"/>
              </svg>
              Share on LinkedIn
            </a>
            <a
              href={twitterUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-[#1DA1F2]/10 border border-[#1DA1F2]/30 text-[#1DA1F2] hover:bg-[#1DA1F2]/20 text-xs font-bold transition-colors"
            >
              <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
                <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-4.714-6.231-5.401 6.231H2.75l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/>
              </svg>
              Post on X
            </a>
            <button
              onClick={() => navigator.clipboard.writeText(verifyUrl)}
              className="px-4 py-2 rounded-lg bg-white/5 border border-white/10 text-gray-400 hover:text-white text-xs font-bold transition-colors"
            >
              Copy Link
            </button>
            <a
              href={`${import.meta.env.VITE_API_URL || '/api/v1'}/certs/download/${cert.verify_token}`}
              download
              className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-white/5 border border-white/10 text-gray-400 hover:text-white text-xs font-bold transition-colors"
            >
              ↓ Download PDF
            </a>
          </div>
        </div>

        {/* Footer */}
        <div className="text-center mt-6">
          <Link to="/" className="text-xs text-gray-700 hover:text-gray-400 transition-colors">
            Earn your certification at <span className="text-breach-accent font-bold">breachreplay.com</span>
          </Link>
        </div>
      </div>
    </div>
  );
}
