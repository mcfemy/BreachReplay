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

export default function TermsOfServicePage() {
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
        <h1 className="text-4xl font-bold mb-2">Terms of Service</h1>
        <p className="text-sm text-gray-600 mb-12">Last updated: August 27, 2026</p>

        <Section title="1. Acceptance of terms">
          <p>
            By creating an account or using BreachReplay, you agree to these Terms. If you're
            accepting on behalf of an organization, you're confirming you have authority to bind
            that organization.
          </p>
        </Section>

        <Section title="2. The service">
          <p>
            BreachReplay is a training platform that converts real-world breach disclosures into
            interactive incident-response simulations, including solo, multiplayer, and live
            attacker-vs-defender ("Arena") modes, along with AI-assisted debrief and compliance
            mapping reports. It is a training and educational tool — it does not provide legal,
            compliance, or security-certification advice, and debrief scoring does not constitute
            an official audit finding.
          </p>
          <p>
            The Action Console lets you complete timed breach runs (Daily Breach, scenarios, and
            practice modes). Completed runs can be shared via public replay links, and other players
            can race your recorded run as a ghost on the same seed. Ghost racing compares
            containment times; share links and leaderboard placement make your run visible to
            others as described in our{" "}
            <Link to="/privacy" className="text-red-400 hover:text-red-300">
              Privacy Policy
            </Link>
            .
          </p>
        </Section>

        <Section title="3. Accounts">
          <p>
            You're responsible for keeping your account credentials confidential and for activity
            that happens under your account. Tell us right away at{" "}
            <a href="mailto:support@breachreplay.com" className="text-red-400 hover:text-red-300">
              support@breachreplay.com
            </a>{" "}
            if you suspect unauthorized access.
          </p>
        </Section>

        <Section title="4. Acceptable use">
          <p>
            Don't use BreachReplay to: attempt to access another organization's private data or
            scenarios; disrupt the service (including automated abuse of Arena matchmaking or
            spectator connections); upload content you don't have the right to share; or use the
            platform to develop or test actual malicious tooling against real systems.
          </p>
          <p>
            When you share a run link or race another player's ghost, you agree that your display
            label and run outcome may be shown to that player and, if they beat your time, that we
            may email you a beat notification (see the Privacy Policy for opt-out). Do not use share
            links or ghost racing to harass other users.
          </p>
        </Section>

        <Section title="5. Subscriptions &amp; billing">
          <p>
            Free tier accounts have no payment obligation. Enterprise subscriptions are billed
            through Stripe on the cadence shown at checkout (currently annual), auto-renew unless
            cancelled, and are subject to the then-current pricing shown on our Pricing page.
            Cancelling stops future renewal but does not retroactively refund the current term
            unless required by law or agreed in writing.
          </p>
        </Section>

        <Section title="6. Your content">
          <p>
            You retain ownership of documents and data you upload. You grant us a license to
            process that content solely to operate the service for you (including sending it to
            subprocessors described in our{" "}
            <Link to="/privacy" className="text-red-400 hover:text-red-300">
              Privacy Policy
            </Link>
            ). Public scenarios sourced from public breach disclosures (e.g., CISA/SEC filings)
            remain attributed to their original public source.
          </p>
        </Section>

        <Section title="7. Disclaimers">
          <p>
            The service is provided "as is." Simulated scenarios, AI-generated debrief content, and
            compliance-framework mappings are provided for training purposes and are not a
            substitute for professional legal, compliance, or security advice, and do not guarantee
            any specific audit or certification outcome.
          </p>
        </Section>

        <Section title="8. Limitation of liability">
          <p>
            To the maximum extent permitted by law, BreachReplay will not be liable for indirect,
            incidental, or consequential damages arising from use of the service. Our total
            liability for any claim is limited to the amount you paid us in the 12 months before
            the claim arose.
          </p>
        </Section>

        <Section title="9. Termination">
          <p>
            You can stop using the service and close your account at any time. We may suspend or
            terminate accounts that violate these Terms, including the acceptable-use section
            above.
          </p>
        </Section>

        <Section title="10. Changes">
          <p>
            We may update these Terms as the product evolves. We'll update the date above, and for
            material changes we'll make a reasonable effort to notify account holders by email.
          </p>
        </Section>

        <Section title="11. Contact">
          <p>
            Questions about these Terms:{" "}
            <a href="mailto:support@breachreplay.com" className="text-red-400 hover:text-red-300">
              support@breachreplay.com
            </a>
          </p>
        </Section>
      </div>
    </div>
  );
}
