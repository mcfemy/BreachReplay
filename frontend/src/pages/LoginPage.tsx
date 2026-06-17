import { useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { api } from "../lib/api";
import { useAuthStore } from "../store/auth";

const API_BASE = import.meta.env.VITE_API_URL || "/api/v1";

function SocialButton({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <a
      href={href}
      className="flex items-center justify-center gap-3 w-full px-4 py-2.5 rounded border border-breach-border bg-white/5 hover:bg-white/10 text-white text-sm font-medium transition-colors"
    >
      {children}
    </a>
  );
}

type Step = "credentials" | "mfa";

export default function LoginPage() {
  const [step, setStep] = useState<Step>("credentials");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [mfaToken, setMfaToken] = useState("");
  const [mfaCode, setMfaCode] = useState("");
  const [ssoMode, setSsoMode] = useState(false);
  const [ssoDomain, setSsoDomain] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const { setAuth } = useAuthStore();
  const navigate = useNavigate();

  async function handleCredentials(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const data = await api.post<any>("/auth/login", { email, password });
      if (data.mfa_required) {
        setMfaToken(data.mfa_token);
        setStep("mfa");
      } else {
        setAuth(data.access_token, data.refresh_token, data.user);
        navigate("/scenarios");
      }
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function handleMfa(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const data = await api.post<{ access_token: string; refresh_token: string; user: any }>(
        "/auth/mfa/verify",
        { mfa_token: mfaToken, code: mfaCode.trim() }
      );
      setAuth(data.access_token, data.refresh_token, data.user);
      navigate("/scenarios");
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  function handleSsoSubmit(e: React.FormEvent) {
    e.preventDefault();
    const domain = ssoDomain.trim().toLowerCase();
    if (!domain) return;
    window.location.href = `${API_BASE}/auth/saml/init?domain=${encodeURIComponent(domain)}`;
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-breach-bg">
      <div className="w-full max-w-md">
        <div className="mb-8 text-center">
          <h1 className="text-3xl font-bold text-breach-accent tracking-widest uppercase">BREACH REPLAY</h1>
          <p className="text-breach-muted text-sm mt-2">Incident Response Training Platform</p>
        </div>

        {/* ── MFA step ── */}
        {step === "mfa" ? (
          <form onSubmit={handleMfa} className="bg-breach-surface border border-breach-border rounded p-8 space-y-4">
            <div className="text-center">
              <div className="text-3xl mb-2">🔐</div>
              <h2 className="text-breach-text text-sm uppercase tracking-wider font-semibold">Two-Factor Authentication</h2>
              <p className="text-xs text-breach-muted mt-1">Enter the 6-digit code from your authenticator app, or one of your 8-character backup codes.</p>
            </div>
            <div>
              <label className="block text-xs text-breach-muted uppercase tracking-wider mb-1">Code</label>
              <input
                type="text"
                inputMode="numeric"
                value={mfaCode}
                onChange={(e) => setMfaCode(e.target.value)}
                className="w-full bg-breach-bg border border-breach-border text-breach-text px-3 py-2 rounded text-sm focus:outline-none focus:border-breach-blue text-center tracking-widest text-lg"
                placeholder="000000"
                maxLength={8}
                autoFocus
                required
              />
            </div>
            {error && <p className="text-breach-accent text-xs">{error}</p>}
            <button
              type="submit"
              disabled={loading}
              className="w-full bg-breach-accent hover:bg-red-600 text-white py-2 rounded text-sm uppercase tracking-widest transition-colors disabled:opacity-50"
            >
              {loading ? "Verifying..." : "Verify"}
            </button>
            <button
              type="button"
              onClick={() => { setStep("credentials"); setError(""); setMfaCode(""); }}
              className="w-full text-xs text-breach-muted hover:text-breach-text transition-colors"
            >
              Back to sign in
            </button>
          </form>
        ) : (
          <form onSubmit={handleCredentials} className="bg-breach-surface border border-breach-border rounded p-8 space-y-4">
            <div>
              <label className="block text-xs text-breach-muted uppercase tracking-wider mb-1">Email</label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="w-full bg-breach-bg border border-breach-border text-breach-text px-3 py-2 rounded text-sm focus:outline-none focus:border-breach-blue"
                required
              />
            </div>
            <div>
              <label className="block text-xs text-breach-muted uppercase tracking-wider mb-1">Password</label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full bg-breach-bg border border-breach-border text-breach-text px-3 py-2 rounded text-sm focus:outline-none focus:border-breach-blue"
                required
              />
            </div>
            {error && <p className="text-breach-accent text-xs">{error}</p>}
            <button
              type="submit"
              disabled={loading}
              className="w-full bg-breach-accent hover:bg-red-600 text-white py-2 rounded text-sm uppercase tracking-widest transition-colors disabled:opacity-50"
            >
              {loading ? "Authenticating..." : "Access System"}
            </button>
            <div className="flex items-center gap-3 text-xs text-breach-muted">
              <Link to="/register" className="text-breach-blue hover:underline">Create account</Link>
              <span>·</span>
              <Link to="/forgot-password" className="hover:underline">Forgot password?</Link>
            </div>

            {/* Identity Provider SSO */}
            <div className="relative mt-2 mb-1">
              <div className="absolute inset-0 flex items-center">
                <div className="w-full border-t border-breach-border" />
              </div>
              <div className="relative flex justify-center text-xs">
                <span className="bg-breach-surface px-2 text-breach-muted">or continue with</span>
              </div>
            </div>

            <div className="space-y-2">
              <SocialButton href={`${API_BASE}/auth/google`}>
                <svg className="w-4 h-4 shrink-0" viewBox="0 0 24 24">
                  <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/>
                  <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/>
                  <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"/>
                  <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/>
                </svg>
                Continue with Google
              </SocialButton>

              <SocialButton href={`${API_BASE}/auth/microsoft`}>
                <svg className="w-4 h-4 shrink-0" viewBox="0 0 21 21">
                  <rect x="1" y="1" width="9" height="9" fill="#F25022"/>
                  <rect x="11" y="1" width="9" height="9" fill="#7FBA00"/>
                  <rect x="1" y="11" width="9" height="9" fill="#00A4EF"/>
                  <rect x="11" y="11" width="9" height="9" fill="#FFB900"/>
                </svg>
                Continue with Microsoft
              </SocialButton>

              <SocialButton href={`${API_BASE}/auth/github`}>
                <svg className="w-4 h-4 shrink-0 fill-current" viewBox="0 0 24 24">
                  <path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0 0 24 12c0-6.63-5.37-12-12-12z"/>
                </svg>
                Continue with GitHub
              </SocialButton>

              {/* Enterprise SSO (SAML) */}
              {!ssoMode ? (
                <button
                  type="button"
                  onClick={() => setSsoMode(true)}
                  className="flex items-center justify-center gap-3 w-full px-4 py-2.5 rounded border border-breach-border bg-white/5 hover:bg-white/10 text-white text-sm font-medium transition-colors"
                >
                  <svg className="w-4 h-4 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4" />
                  </svg>
                  Enterprise SSO
                </button>
              ) : (
                <form onSubmit={handleSsoSubmit} className="space-y-2">
                  <div>
                    <label className="block text-xs text-breach-muted uppercase tracking-wider mb-1">Work email domain</label>
                    <input
                      type="text"
                      value={ssoDomain}
                      onChange={(e) => setSsoDomain(e.target.value)}
                      placeholder="acme.com"
                      className="w-full bg-breach-bg border border-breach-border text-breach-text px-3 py-2 rounded text-sm focus:outline-none focus:border-breach-blue"
                      autoFocus
                    />
                  </div>
                  <div className="flex gap-2">
                    <button
                      type="submit"
                      className="flex-1 bg-breach-blue hover:bg-blue-600 text-white py-2 rounded text-sm font-medium transition-colors"
                    >
                      Continue with SSO
                    </button>
                    <button
                      type="button"
                      onClick={() => { setSsoMode(false); setSsoDomain(""); }}
                      className="px-3 py-2 rounded border border-breach-border text-breach-muted hover:text-breach-text text-sm transition-colors"
                    >
                      Cancel
                    </button>
                  </div>
                </form>
              )}
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
