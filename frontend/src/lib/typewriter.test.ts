import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  ALERT_LINE_STAGGER_MS,
  TYPEWRITER_MS_PER_CHAR,
  prefersReducedMotion,
  useTypewriterLines,
} from "./typewriter";

function stubMatchMedia(reduce: boolean) {
  window.matchMedia = ((query: string) =>
    ({
      matches: query.includes("prefers-reduced-motion") ? reduce : false,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }) as unknown as MediaQueryList);
}

describe("typewriter", () => {
  beforeEach(() => {
    stubMatchMedia(false);
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("prefersReducedMotion reads the media query", () => {
    stubMatchMedia(true);
    expect(prefersReducedMotion()).toBe(true);
    stubMatchMedia(false);
    expect(prefersReducedMotion()).toBe(false);
  });

  it("reveals characters progressively, then does not restart older lines", () => {
    const { result, rerender } = renderHook(
      ({ lines }) => useTypewriterLines(lines),
      { initialProps: { lines: [{ id: "a", text: "abcd" }] } },
    );

    expect(result.current.a ?? 0).toBe(0);
    act(() => {
      vi.advanceTimersByTime(TYPEWRITER_MS_PER_CHAR * 2);
    });
    expect(result.current.a).toBe(2);

    act(() => {
      vi.advanceTimersByTime(TYPEWRITER_MS_PER_CHAR * 2);
    });
    expect(result.current.a).toBe(4);

    rerender({ lines: [{ id: "a", text: "abcd" }, { id: "b", text: "xy" }] });
    expect(result.current.a).toBe(4);
    expect(result.current.b ?? 0).toBe(0);
    act(() => {
      vi.advanceTimersByTime(TYPEWRITER_MS_PER_CHAR);
    });
    expect(result.current.b).toBe(1);
    expect(result.current.a).toBe(4);
  });

  it("staggers a batch of new lines", () => {
    const { result } = renderHook(() =>
      useTypewriterLines([
        { id: "a", text: "aa" },
        { id: "b", text: "bb" },
      ]),
    );

    act(() => {
      vi.advanceTimersByTime(TYPEWRITER_MS_PER_CHAR * 2);
    });
    expect(result.current.a).toBe(2);
    expect(result.current.b ?? 0).toBe(0);

    act(() => {
      vi.advanceTimersByTime(ALERT_LINE_STAGGER_MS);
    });
    expect(result.current.b).toBeGreaterThan(0);
  });

  it("shows every line fully at once when reduced-motion is set", () => {
    stubMatchMedia(true);
    const { result } = renderHook(() =>
      useTypewriterLines([
        { id: "a", text: "hello" },
        { id: "b", text: "world" },
      ]),
    );
    expect(result.current.a).toBe(5);
    expect(result.current.b).toBe(5);
  });
});
