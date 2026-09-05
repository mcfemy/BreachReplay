/**
 * Phase 3 juice — three Web Audio oscillator cues (spec §1 / §5).
 * No asset files. Muted by default. AudioContext is created only after a
 * user gesture (the AppShell toggle, or the first pointerdown once sound
 * is already enabled) so nothing autoplays on load.
 *
 * Cues wired from ActionConsole:
 *   tick  — remaining response budget first drops to ≤ 60s (clock pressure)
 *   thud  — isolate / correct block_ip / correct reset_creds (containment
 *           or a resolved targeted action)
 *   chime — run.end with contained / contained_at_cost (success only)
 *
 * Cues wired from ArenaMatchPage (same helpers — mute/unlock shared):
 *   tick  — not wired: Arena has no player-facing countdown; the Phase H
 *           `_MAX_MATCH_ACTIONS` turn-budget cap is a silent server fallback
 *   thud  — defender isolate_host / disable_credential decision_result
 *   chime — match_complete when THIS human's side won (not on a loss)
 */
export const SOUND_STORAGE_KEY = "br_sound_enabled";

let ctx: AudioContext | null = null;
let unlocked = false;
let unlockListenerAttached = false;

function AudioContextCtor(): typeof AudioContext | undefined {
  if (typeof window === "undefined") return undefined;
  return window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
}

export function isSoundEnabled(): boolean {
  try {
    return localStorage.getItem(SOUND_STORAGE_KEY) === "1";
  } catch {
    return false;
  }
}

export function setSoundEnabled(enabled: boolean): void {
  localStorage.setItem(SOUND_STORAGE_KEY, enabled ? "1" : "0");
  if (enabled) unlockAudio();
}

export function unlockAudio(): void {
  const Ctor = AudioContextCtor();
  if (!Ctor) return;
  if (!ctx) ctx = new Ctor();
  unlocked = true;
  if (ctx.state === "suspended") void ctx.resume();
}

/** First pointerdown after load unlocks the context if sound is already on. */
export function installSoundUnlockListener(): () => void {
  if (typeof window === "undefined" || unlockListenerAttached) return () => {};
  unlockListenerAttached = true;
  const onGesture = () => {
    if (isSoundEnabled()) unlockAudio();
  };
  window.addEventListener("pointerdown", onGesture, { once: true });
  return () => {
    window.removeEventListener("pointerdown", onGesture);
    unlockListenerAttached = false;
  };
}

function canPlay(): boolean {
  return isSoundEnabled() && unlocked && ctx !== null;
}

function playTone(opts: {
  frequency: number;
  duration: number;
  type: OscillatorType;
  gain: number;
  slideTo?: number;
}): void {
  if (!canPlay() || !ctx) return;
  const now = ctx.currentTime;
  const osc = ctx.createOscillator();
  const gain = ctx.createGain();
  osc.type = opts.type;
  osc.frequency.setValueAtTime(opts.frequency, now);
  if (opts.slideTo !== undefined) {
    osc.frequency.exponentialRampToValueAtTime(Math.max(opts.slideTo, 1), now + opts.duration);
  }
  gain.gain.setValueAtTime(opts.gain, now);
  gain.gain.exponentialRampToValueAtTime(0.001, now + opts.duration);
  osc.connect(gain);
  gain.connect(ctx.destination);
  osc.start(now);
  osc.stop(now + opts.duration);
}

export function playTick(): void {
  playTone({ frequency: 920, duration: 0.045, type: "square", gain: 0.035 });
}

export function playThud(): void {
  playTone({ frequency: 90, duration: 0.14, type: "sine", gain: 0.18, slideTo: 40 });
}

export function playChime(): void {
  playTone({ frequency: 523.25, duration: 0.16, type: "sine", gain: 0.08 });
  playTone({ frequency: 659.25, duration: 0.22, type: "sine", gain: 0.07 });
}

/** Test hook — drops the in-memory context so each spec starts muted/locked. */
export function resetSoundForTests(): void {
  ctx = null;
  unlocked = false;
  unlockListenerAttached = false;
}
