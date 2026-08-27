import { Link } from "react-router-dom";
import { useAuthStore } from "../store/auth";

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="mb-10">
      <h2 className="text-lg font-bold text-white mb-3">{title}</h2>
      <div className="text-sm text-gray-400 leading-relaxed space-y-3">{children}</div>
    </div>
  );
}

export default function PrivacyPolicyPage() {
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
            <Link to="/login" className="text-sm text-gray-400 hover:text-white transition-colors">
              Sign in
            </Link>
          )}
        </div>
      </nav>

      <div className="max-w-3xl mx-auto px-6 py-20">
        <h1 className="text-4xl font-bold mb-2">Privacy Policy</h1>
        <p className="text-sm text-gray-600 mb-12">Last updated: August 27, 2026</p>

        <Section title="1. What we collect">
          <p>
            Account information (name, email, organization), authentication data (hashed passwords,
            OAuth identifiers if you sign in via a third-party provider), and content you create in
            the product: simulation session transcripts, decisions made during exercises, uploaded
            breach documents (Enterprise private scenario uploads), and debrief results.
          </p>
          <p>
            We also collect basic usage/telemetry (pages visited, feature usage, error logs) to
            operate and improve the service.
          </p>
        </Section>

        <Section title="2. How we use it">
          <p>
            To operate the platform: authenticate you, run simulations, generate AI-assisted
            debrief reports, maintain leaderboards/rankings you opt into, and process billing for
            Enterprise accounts. We do not sell your personal data or your organization's uploaded
            content to third parties.
          </p>
        </Section>

        <Section title="3. Third parties we share data with (subprocessors)">
          <p>
            <span className="text-gray-300 font-medium">Anthropic</span> — breach documents and
            session content may be sent to Anthropic's Claude API to power scenario ingestion and
            AI-assisted debrief grading. Anthropic's commercial API terms state API inputs are not
            used to train their models.
          </p>
          <p>
            <span className="text-gray-300 font-medium">Amazon Web Services (AWS)</span> — hosting,
            database, and document storage.
          </p>
          <p>
            <span className="text-gray-300 font-medium">Stripe</span> — payment processing for
            Enterprise subscriptions. We do not store raw card numbers ourselves.
          </p>
          <p>
            <span className="text-gray-300 font-medium">SendGrid</span> — transactional email
            (password resets, session debrief notices, team invitations, and — if you have not
            opted out — beat-notification emails when another player beats your shared or
            leaderboard-visible run in ghost racing).
          </p>
        </Section>

        <Section title="4. Data isolation for Enterprise organizations">
          <p>
            Private scenarios and org-scoped data uploaded under an Enterprise organization account
            are only accessible to members of that organization and BreachReplay staff performing
            support or maintenance — never to other customers.
          </p>
        </Section>

        <Section title="5. Public / opt-in sharing features">
          <p>
            Some features are explicitly public by design and require opt-in: sharing a match replay
            link, setting a public display handle and profile, and appearing on public leaderboards
            or aggregate statistics pages. Anything shared this way is intentionally visible to
            anyone with the link, or (for aggregate stats) shown in anonymized/aggregated form. You
            can opt out of public profile visibility at any time from account settings.
          </p>
          <p>
            <span className="text-gray-300 font-medium">Action Console share links</span> — when you
            mint a share link for a completed run, we generate an opaque token URL (for example{" "}
            <code className="text-gray-500">/r/…</code>) that exposes a redacted replay of that run
            (outcome, score, timing, map state, and verb timeline — not hidden targets or seed).
            Anyone with the link can view the replay and, if they have an account, race against your
            recorded run as a &quot;ghost.&quot;
          </p>
          <p>
            <span className="text-gray-300 font-medium">Ghost racing</span> — you can race another
            player&apos;s recorded run on the same scenario seed (from Daily Breach or a share
            link). Your live run is separate from theirs; we compare containment times after the
            race. Racing or sharing for the first time shows an in-product notice explaining this
            behavior.
          </p>
          <p>
            <span className="text-gray-300 font-medium">Beat-notification emails</span> — if another
            player beats your run in a ghost race, we may email you at your account address with
            their public display label (or a generic label if none is set) and how much faster they
            contained the breach. This is a single email category; you can opt out at any time via
            the unsubscribe link in the email or by visiting{" "}
            <code className="text-gray-500">/api/v1/unsubscribe?token=…</code> with your personal
            unsubscribe token. Opting out does not delete your account or stop other transactional
            emails (password resets, invitations).
          </p>
        </Section>

        <Section title="6. Data retention">
          <p>
            We retain account and session data for as long as your account is active. You can
            request deletion of your account and associated personal data at any time by emailing{" "}
            <a href="mailto:privacy@breachreplay.com" className="text-red-400 hover:text-red-300">
              privacy@breachreplay.com
            </a>
            . Enterprise customers with compliance/audit-log retention requirements can configure
            longer retention horizons for training records as part of their plan.
          </p>
        </Section>

        <Section title="7. Your rights">
          <p>
            Depending on where you live, you may have rights to access, correct, export, or delete
            your personal data. Contact{" "}
            <a href="mailto:privacy@breachreplay.com" className="text-red-400 hover:text-red-300">
              privacy@breachreplay.com
            </a>{" "}
            to exercise any of these rights.
          </p>
        </Section>

        <Section title="8. Changes to this policy">
          <p>
            We'll update the date at the top of this page when this policy changes, and for material
            changes we'll make a reasonable effort to notify account holders by email.
          </p>
        </Section>

        <Section title="9. Contact">
          <p>
            Questions about this policy: {" "}
            <a href="mailto:privacy@breachreplay.com" className="text-red-400 hover:text-red-300">
              privacy@breachreplay.com
            </a>
          </p>
        </Section>
      </div>
    </div>
  );
}
