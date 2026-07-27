/**
 * Guided first-run, screen 1 — shown once ever per account, before the map
 * appears on a player's genuine first Action Console run (gated by
 * User.has_seen_console_intro, see ActionConsole.tsx). In-fiction handover
 * framing, not a tutorial modal: no bullet list, no "here's how this
 * works" — just the SOC's voice and the first move. Deliberately static
 * (no phased reveal like ScenarioCinematicIntroPage.tsx's tabletop intro)
 * and styled with the console's own terminal palette (theme/tokens.ts),
 * not OnboardingModal.tsx's app-shell palette — this is a screen inside
 * the console, not a marketing step.
 */
export default function ConsolePreBrief({ onDismiss }: { onDismiss: () => void }) {
  return (
    <div className="flex flex-col h-full bg-void text-white font-body items-center justify-center px-6 text-center">
      <p className="font-term text-[11px] uppercase tracking-[0.3em] text-phosphor mb-4">
        Shift Handover
      </p>
      <p className="text-base leading-relaxed text-white/90 max-w-sm mb-2">
        Graveyard flagged it and logged off — you're up.
      </p>
      <p className="text-base leading-relaxed text-white/90 max-w-sm mb-8">
        Something's already inside, and nobody's confirmed how far it's gotten.
        Console's live. Start with a scan.
      </p>
      <button
        onClick={onDismiss}
        className="px-6 py-3 rounded-lg bg-phosphor text-void font-bold text-sm uppercase tracking-widest active:scale-95"
      >
        Scan the network
      </button>
    </div>
  );
}
