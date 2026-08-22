import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  SOUND_STORAGE_KEY,
  isSoundEnabled,
  setSoundEnabled,
  playTick,
  playThud,
  playChime,
  unlockAudio,
  resetSoundForTests,
} from "./sound";

function mockAudioContext() {
  const oscillator = {
    type: "sine" as OscillatorType,
    frequency: { setValueAtTime: vi.fn(), exponentialRampToValueAtTime: vi.fn() },
    connect: vi.fn(),
    start: vi.fn(),
    stop: vi.fn(),
  };
  const gainNode = {
    gain: { setValueAtTime: vi.fn(), exponentialRampToValueAtTime: vi.fn() },
    connect: vi.fn(),
  };
  const instances: FakeAudioContext[] = [];

  class FakeAudioContext {
    state = "running";
    currentTime = 0;
    destination = {};
    resume = vi.fn().mockResolvedValue(undefined);
    createOscillator = vi.fn(() => ({ ...oscillator, frequency: { ...oscillator.frequency }, connect: vi.fn() }));
    createGain = vi.fn(() => ({ ...gainNode, gain: { ...gainNode.gain }, connect: vi.fn() }));
    constructor() {
      instances.push(this);
    }
  }

  vi.stubGlobal("AudioContext", FakeAudioContext);
  return { FakeAudioContext, instances, oscillator };
}

describe("sound", () => {
  beforeEach(() => {
    resetSoundForTests();
    localStorage.clear();
  });

  afterEach(() => {
    resetSoundForTests();
    vi.unstubAllGlobals();
  });

  it("is muted by default", () => {
    expect(isSoundEnabled()).toBe(false);
    expect(localStorage.getItem(SOUND_STORAGE_KEY)).toBeNull();
  });

  it("persists the toggle to localStorage", () => {
    setSoundEnabled(true);
    expect(localStorage.getItem(SOUND_STORAGE_KEY)).toBe("1");
    expect(isSoundEnabled()).toBe(true);
    setSoundEnabled(false);
    expect(localStorage.getItem(SOUND_STORAGE_KEY)).toBe("0");
    expect(isSoundEnabled()).toBe(false);
  });

  it("does not construct AudioContext or play when muted", () => {
    const { instances } = mockAudioContext();
    playTick();
    playThud();
    playChime();
    expect(instances).toHaveLength(0);
  });

  it("does not autoplay just because localStorage says enabled — needs a gesture unlock", () => {
    localStorage.setItem(SOUND_STORAGE_KEY, "1");
    const { instances } = mockAudioContext();
    playTick();
    expect(instances).toHaveLength(0);
  });

  it("plays after the user enables sound (toggle is a gesture)", () => {
    const { instances } = mockAudioContext();
    setSoundEnabled(true);
    expect(instances).toHaveLength(1);
    playTick();
    expect(instances[0].createOscillator).toHaveBeenCalled();
  });

  it("unlockAudio without enabling still does not play", () => {
    const { instances } = mockAudioContext();
    unlockAudio();
    playChime();
    expect(instances).toHaveLength(1);
    expect(instances[0].createOscillator).not.toHaveBeenCalled();
  });
});
