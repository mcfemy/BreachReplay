import { useState, useEffect } from "react";
import { Link, useSearchParams, useNavigate } from "react-router-dom";
import { axiosInstance as api } from "../lib/api";

type Stage = "request" | "confirm" | "done";

export default function ResetPasswordPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const token = params.get("token");

  const [stage, setStage] = useState<Stage>(token ? "confirm" : "request");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  useEffect(() => {
    if (token) setStage("confirm");
  }, [token]);

  async function handleRequest(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await api.post("/auth/forgot-password", { email });
      setMessage("Check your email — a reset link is on its way.");
    } catch {
      setError("No account found with that email.");
    } finally {
      setLoading(false);
    }
  }

  async function handleConfirm(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    if (password !== confirm) {
      setError("Passwords do not match.");
      return;
    }
    if (password.length < 8) {
      setError("Password must be at least 8 characters.");
      return;
    }
    setLoading(true);
    try {
      await api.post("/auth/reset-password", { token, new_password: password });
      setStage("done");
    } catch {
      setError("Reset link is invalid or expired. Request a new one.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen bg-[#0a0e1a] flex items-center justify-center px-4">
      <div className="w-full max-w-md">
        <div className="text-center mb-8">
          <Link to="/" className="inline-block">
            <span className="text-2xl font-bold text-white font-mono tracking-tight">
              Breach<span className="text-red-500">Replay</span>
            </span>
          </Link>
        </div>

        <div className="bg-[#111827] border border-white/10 rounded-xl p-8">
          {stage === "request" && (
            <>
              <h1 className="text-xl font-semibold text-white mb-1">Reset your password</h1>
              <p className="text-sm text-gray-400 mb-6">Enter your email and we'll send a reset link.</p>

              {message ? (
                <div className="bg-green-500/10 border border-green-500/30 rounded-lg p-4 text-green-400 text-sm">
                  {message}
                </div>
              ) : (
                <form onSubmit={handleRequest} className="space-y-4">
                  <div>
                    <label className="block text-sm text-gray-400 mb-1">Email</label>
                    <input
                      type="email"
                      required
                      value={email}
                      onChange={(e) => setEmail(e.target.value)}
                      placeholder="you@company.com"
                      className="w-full bg-[#0a0e1a] border border-white/10 rounded-lg px-4 py-3 text-white placeholder-gray-600 focus:outline-none focus:border-red-500/50 text-sm font-mono"
                    />
                  </div>
                  {error && <p className="text-red-400 text-sm">{error}</p>}
                  <button
                    type="submit"
                    disabled={loading}
                    className="w-full bg-red-600 hover:bg-red-500 disabled:opacity-50 text-white font-semibold py-3 rounded-lg transition-colors text-sm"
                  >
                    {loading ? "Sending…" : "Send Reset Link"}
                  </button>
                </form>
              )}
            </>
          )}

          {stage === "confirm" && (
            <>
              <h1 className="text-xl font-semibold text-white mb-1">Choose a new password</h1>
              <p className="text-sm text-gray-400 mb-6">Pick something strong — you'll be managing real IR decisions.</p>

              <form onSubmit={handleConfirm} className="space-y-4">
                <div>
                  <label className="block text-sm text-gray-400 mb-1">New password</label>
                  <input
                    type="password"
                    required
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder="Min 8 characters"
                    className="w-full bg-[#0a0e1a] border border-white/10 rounded-lg px-4 py-3 text-white placeholder-gray-600 focus:outline-none focus:border-red-500/50 text-sm font-mono"
                  />
                </div>
                <div>
                  <label className="block text-sm text-gray-400 mb-1">Confirm password</label>
                  <input
                    type="password"
                    required
                    value={confirm}
                    onChange={(e) => setConfirm(e.target.value)}
                    placeholder="Repeat password"
                    className="w-full bg-[#0a0e1a] border border-white/10 rounded-lg px-4 py-3 text-white placeholder-gray-600 focus:outline-none focus:border-red-500/50 text-sm font-mono"
                  />
                </div>
                {error && <p className="text-red-400 text-sm">{error}</p>}
                <button
                  type="submit"
                  disabled={loading}
                  className="w-full bg-red-600 hover:bg-red-500 disabled:opacity-50 text-white font-semibold py-3 rounded-lg transition-colors text-sm"
                >
                  {loading ? "Resetting…" : "Reset Password"}
                </button>
              </form>
            </>
          )}

          {stage === "done" && (
            <div className="text-center space-y-4">
              <div className="w-12 h-12 bg-green-500/10 rounded-full flex items-center justify-center mx-auto">
                <svg className="w-6 h-6 text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                </svg>
              </div>
              <h1 className="text-xl font-semibold text-white">Password updated</h1>
              <p className="text-sm text-gray-400">Your new password is set. You can now log in.</p>
              <button
                onClick={() => navigate("/login")}
                className="w-full bg-red-600 hover:bg-red-500 text-white font-semibold py-3 rounded-lg transition-colors text-sm"
              >
                Go to Login
              </button>
            </div>
          )}

          {stage !== "done" && (
            <p className="text-center text-sm text-gray-500 mt-6">
              Remember your password?{" "}
              <Link to="/login" className="text-red-400 hover:text-red-300">
                Sign in
              </Link>
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
