import { Link } from "react-router-dom";
import { useAuthStore } from "../store/auth";

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="bg-[#111827] border border-white/10 rounded-2xl p-8 mb-6">
      <h2 className="text-xl font-bold mb-4">{title}</h2>
      <div className="text-sm text-gray-400 leading-relaxed space-y-3">{children}</div>
    </div>
  );
}

export default function SecurityPage() {
  const { token } = useAuthStore();

  return (
    <div className="min-h-screen bg-[#0a0e1a] text-white">
      <nav className="border-b border-white/10 px-6 py-4 flex items-center justify-between">
        <Link to="/" className="text-lg font-bold font-mono tracking-tight">
          Breach<span className="text-red-500">Replay</span>
        </Link>
        <div className="flex items-center gap-4">
          {token ? (
            <Link to="/scenarios" className="text-sm text-gray-400 hover:text-white transition-colors">
              Scenarios
            </Link>
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

      <div className="max-w-3xl mx-auto px-6 py-20">
        <div className="mb-12">
          <h1 className="text-4xl font-bold mb-4">Security &amp; Trust</h1>
          <p className="text-lg text-gray-400">
            What BreachReplay does — and does not — do with your data, and how the platform is
            protected. We'd rather tell you the plain truth about where we are than overstate it.
          </p>
        </div>

        <Section title="Infrastructure">
          <p>
            BreachReplay runs on AWS (us-east-1). All traffic is served over HTTPS with TLS
            certificates issued by Let's Encrypt and renewed automatically. The application sends
            HSTS and standard hardened response headers (Content-Security-Policy,
            X-Content-Type-Options, X-Frame-Options, Referrer-Policy) on every response.
          </p>
          <p>
            The database and application containers run in an isolated private network segment;
            only the reverse proxy is exposed to the public internet.
          </p>
        </Section>

        <Section title="Account &amp; access security">
          <p>
            Passwords are never stored in plaintext — they're hashed with bcrypt. Sessions use
            short-lived JWT access tokens paired with server-side, rotating opaque refresh tokens,
            so a stolen refresh token can't be silently replayed indefinitely.
          </p>
          <p>
            Every API route enforces role-based access control (analyst / admin / CISO). Org-scoped
            data — including any private scenarios your team uploads — is only ever readable by
            members of that organization.
          </p>
        </Section>

        <Section title="How your data is used">
          <p>
            Documents you upload for scenario ingestion, and session transcripts generated during
            simulations, may be processed by Anthropic's Claude API to power AI-assisted scenario
            extraction and debrief grading. Under Anthropic's standard commercial API terms, data
            sent via the API is not used to train Anthropic's models.
          </p>
          <p>
            We use a small number of subprocessors to run the service: AWS (hosting and storage),
            Anthropic (AI processing described above), SendGrid (transactional email), and Stripe
            (billing, for Enterprise accounts only). We don't sell customer data, and we don't share
            your uploaded documents or simulation results with other customers or third parties for
            marketing purposes.
          </p>
        </Section>

        <Section title="Compliance mapping vs. our own certifications">
          <p>
            BreachReplay's debrief reports can map your team's decisions against frameworks like
            NIST SP 800-61, MITRE ATT&amp;CK, HIPAA, and SOC 2 — that's a feature for your compliance
            program, not a claim that BreachReplay itself holds those certifications.
          </p>
          <p>
            In the interest of being straightforward with security-minded buyers: BreachReplay has
            not yet completed a formal third-party audit (e.g., SOC 2 Type II). It's on our roadmap.
            If a signed security questionnaire or a specific attestation is a requirement for your
            evaluation, email us — we'll tell you exactly where we stand rather than guess.
          </p>
        </Section>

        <Section title="Reporting a vulnerability">
          <p>
            If you believe you've found a security issue, please email{" "}
            <a href="mailto:security@breachreplay.com" className="text-red-400 hover:text-red-300">
              security@breachreplay.com
            </a>{" "}
            with details. We ask that you give us a reasonable window to investigate and fix an
            issue before any public disclosure.
          </p>
        </Section>

        <p className="text-xs text-gray-600 mt-10">
          Questions about anything above? Email{" "}
          <a href="mailto:security@breachreplay.com" className="text-red-400 hover:text-red-300">
            security@breachreplay.com
          </a>
          .
        </p>
      </div>
    </div>
  );
}
