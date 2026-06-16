import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuthStore } from "../store/auth";
import { axiosInstance } from "../lib/api";

const FREE_FEATURES = [
  "Solo play on all public scenarios",
  "Remote multiplayer (up to 4 players)",
  "Basic AI debrief report",
  "Community leaderboard",
  "Colonial Pipeline, SolarWinds, MGM & Log4Shell scenarios",
];

const ENTERPRISE_FEATURES = [
  "Everything in Free",
  "Team analytics dashboard",
  "Compliance export — NIST, HIPAA, SOC 2, CMMC",
  "Private scenario upload (your own breaches)",
  "Completion certificates (shareable PDF)",
  "Multiplayer up to 8 players",
  "Benchmark comparison vs industry peers",
  "Priority support (4-hour SLA)",
  "SSO / SAML for enterprise identity",
];

export default function PricingPage() {
  const { token } = useAuthStore();
  const navigate = useNavigate();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function handleEnterpriseCheckout() {
    if (!token) {
      navigate("/register?next=pricing");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const r = await axiosInstance.post<{ checkout_url: string }>("/billing/create-checkout");
      window.location.href = r.data.checkout_url;
    } catch (e: any) {
      const msg = e?.response?.data?.detail;
      if (msg === "Already on Enterprise tier") {
        navigate("/settings");
      } else if (msg === "Billing not configured") {
        setError("Billing is being set up. Email sales@breachreplay.com to get started.");
      } else {
        setError("Something went wrong. Try again or email sales@breachreplay.com");
      }
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen bg-[#0a0e1a] text-white">
      {/* Nav */}
      <nav className="border-b border-white/10 px-6 py-4 flex items-center justify-between">
        <Link to="/" className="text-lg font-bold font-mono tracking-tight">
          Breach<span className="text-red-500">Replay</span>
        </Link>
        <div className="flex items-center gap-4">
          {token ? (
            <>
              <Link to="/scenarios" className="text-sm text-gray-400 hover:text-white transition-colors">
                Scenarios
              </Link>
              <Link to="/settings" className="text-sm text-gray-400 hover:text-white transition-colors">
                Settings
              </Link>
            </>
          ) : (
            <>
              <Link to="/login" className="text-sm text-gray-400 hover:text-white transition-colors">
                Sign in
              </Link>
              <Link
                to="/register"
                className="text-sm bg-red-600 hover:bg-red-500 text-white px-4 py-2 rounded-lg transition-colors"
              >
                Get started free
              </Link>
            </>
          )}
        </div>
      </nav>

      <div className="max-w-4xl mx-auto px-6 py-20">
        <div className="text-center mb-16">
          <h1 className="text-4xl font-bold mb-4">Simple, transparent pricing</h1>
          <p className="text-lg text-gray-400 max-w-xl mx-auto">
            Start free. Upgrade when your team needs compliance exports, private scenarios, and
            benchmark data.
          </p>
        </div>

        <div className="grid md:grid-cols-2 gap-8">
          {/* Free tier */}
          <div className="bg-[#111827] border border-white/10 rounded-2xl p-8">
            <div className="mb-6">
              <span className="text-xs font-semibold text-gray-400 uppercase tracking-wider">Free</span>
              <div className="mt-2">
                <span className="text-4xl font-bold">$0</span>
                <span className="text-gray-400 ml-1">/forever</span>
              </div>
              <p className="text-sm text-gray-400 mt-2">
                For individuals and teams who want to train without budget approval.
              </p>
            </div>

            <ul className="space-y-3 mb-8">
              {FREE_FEATURES.map((f) => (
                <li key={f} className="flex items-start gap-3 text-sm text-gray-300">
                  <span className="text-green-400 mt-0.5 shrink-0">✓</span>
                  <span>{f}</span>
                </li>
              ))}
            </ul>

            <Link
              to={token ? "/scenarios" : "/register"}
              className="block w-full text-center bg-white/10 hover:bg-white/15 text-white font-semibold py-3 rounded-xl transition-colors"
            >
              {token ? "Go to Scenarios" : "Start free"}
            </Link>
          </div>

          {/* Enterprise tier */}
          <div className="bg-[#111827] border border-red-500/40 rounded-2xl p-8 relative">
            <div className="absolute -top-3 left-8">
              <span className="bg-red-600 text-white text-xs font-bold px-3 py-1 rounded-full">
                RECOMMENDED FOR TEAMS
              </span>
            </div>

            <div className="mb-6">
              <span className="text-xs font-semibold text-red-400 uppercase tracking-wider">Enterprise</span>
              <div className="mt-2">
                <span className="text-4xl font-bold">Custom</span>
                <span className="text-gray-400 ml-1">/year</span>
              </div>
              <p className="text-sm text-gray-400 mt-2">
                For security teams that need compliance evidence, analytics, and private scenario upload.
              </p>
            </div>

            <ul className="space-y-3 mb-8">
              {ENTERPRISE_FEATURES.map((f) => (
                <li key={f} className="flex items-start gap-3 text-sm text-gray-300">
                  <span className="text-red-400 mt-0.5 shrink-0">✓</span>
                  <span>{f}</span>
                </li>
              ))}
            </ul>

            {error && (
              <p className="text-sm text-red-400 mb-4 bg-red-500/10 border border-red-500/20 rounded-lg px-4 py-3">
                {error}
              </p>
            )}

            <button
              onClick={handleEnterpriseCheckout}
              disabled={loading}
              className="block w-full text-center bg-red-600 hover:bg-red-500 disabled:opacity-50 text-white font-semibold py-3 rounded-xl transition-colors"
            >
              {loading ? "Loading…" : "Get Enterprise Access"}
            </button>

            <p className="text-xs text-gray-500 text-center mt-3">
              Annual contract · Cancel anytime · Net-30 invoicing available
            </p>
          </div>
        </div>

        {/* FAQ */}
        <div className="mt-20">
          <h2 className="text-2xl font-bold text-center mb-10">Common questions</h2>
          <div className="grid md:grid-cols-2 gap-6">
            {[
              {
                q: "What counts as a 'team'?",
                a: "Any group of people sharing an organization account. Enterprise pricing is per organization, not per seat — your whole IR team is covered.",
              },
              {
                q: "Can we upload our own breach data?",
                a: "Yes — Enterprise includes private scenario upload. Send us a post-mortem PDF and our AI pipeline converts it into a playable simulation visible only to your team.",
              },
              {
                q: "What compliance frameworks are covered?",
                a: "NIST CSF, NIST SP 800-61, HIPAA, SOC 2, CMMC, FedRAMP, and NERC CIP. Each decision gate maps to specific controls and can be exported as audit evidence.",
              },
              {
                q: "Is there a free trial of Enterprise?",
                a: "Yes — email sales@breachreplay.com and we'll set up a 14-day trial. No credit card required.",
              },
              {
                q: "Who uses BreachReplay?",
                a: "CISOs, SOC teams, and IR consultants who want to run tabletop exercises that feel like the real thing — not slideshow walkthroughs.",
              },
              {
                q: "Do you offer MSSP white-labeling?",
                a: "Yes — managed security providers can white-label the platform for client delivery. Contact us to discuss MSSP pricing.",
              },
            ].map(({ q, a }) => (
              <div key={q} className="bg-[#111827] border border-white/10 rounded-xl p-6">
                <h3 className="font-semibold text-white mb-2">{q}</h3>
                <p className="text-sm text-gray-400 leading-relaxed">{a}</p>
              </div>
            ))}
          </div>
        </div>

        {/* CTA */}
        <div className="mt-20 text-center">
          <p className="text-gray-400 text-sm">
            Questions? Email{" "}
            <a href="mailto:sales@breachreplay.com" className="text-red-400 hover:text-red-300">
              sales@breachreplay.com
            </a>{" "}
            or{" "}
            <a href="mailto:support@breachreplay.com" className="text-red-400 hover:text-red-300">
              support@breachreplay.com
            </a>
          </p>
        </div>
      </div>
    </div>
  );
}
