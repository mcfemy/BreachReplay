import { useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { api } from "../lib/api";
import { useAuthStore } from "../store/auth";

export default function RegisterPage() {
  const [form, setForm] = useState({ email: "", password: "", full_name: "" });
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const { setAuth } = useAuthStore();
  const navigate = useNavigate();

  function handleChange(e: React.ChangeEvent<HTMLInputElement>) {
    setForm((f) => ({ ...f, [e.target.name]: e.target.value }));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const data = await api.post<{ access_token: string; refresh_token: string; user: any }>("/auth/register", form);
      setAuth(data.access_token, data.refresh_token, data.user);
      navigate("/scenarios");
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-breach-bg">
      <div className="w-full max-w-md">
        <div className="mb-8 text-center">
          <h1 className="text-3xl font-bold text-breach-accent tracking-widest uppercase">BREACH REPLAY</h1>
          <p className="text-breach-muted text-sm mt-2">Incident Response Training Platform</p>
        </div>
        <form onSubmit={handleSubmit} className="bg-breach-surface border border-breach-border rounded p-8 space-y-4">
          <h2 className="text-breach-text text-sm uppercase tracking-wider font-semibold">Create Account</h2>
          <div>
            <label className="block text-xs text-breach-muted uppercase tracking-wider mb-1">Full Name</label>
            <input
              name="full_name"
              type="text"
              value={form.full_name}
              onChange={handleChange}
              className="w-full bg-breach-bg border border-breach-border text-breach-text px-3 py-2 rounded text-sm focus:outline-none focus:border-breach-blue"
              required
            />
          </div>
          <div>
            <label className="block text-xs text-breach-muted uppercase tracking-wider mb-1">Email</label>
            <input
              name="email"
              type="email"
              value={form.email}
              onChange={handleChange}
              className="w-full bg-breach-bg border border-breach-border text-breach-text px-3 py-2 rounded text-sm focus:outline-none focus:border-breach-blue"
              required
            />
          </div>
          <div>
            <label className="block text-xs text-breach-muted uppercase tracking-wider mb-1">Password</label>
            <input
              name="password"
              type="password"
              value={form.password}
              onChange={handleChange}
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
            {loading ? "Creating Account..." : "Create Account"}
          </button>
          <p className="text-center text-xs text-breach-muted">
            Already have an account?{" "}
            <Link to="/login" className="text-breach-blue hover:underline">
              Sign in
            </Link>
          </p>
        </form>
      </div>
    </div>
  );
}
