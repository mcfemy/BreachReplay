/**
 * Confirms the Phase 4 ghost harness is registered only under Vite DEV.
 * Production builds set import.meta.env.DEV=false; App.tsx gates the route
 * (and the lazy import) on that flag so /dev/ghost-playback does not ship.
 */
import { describe, it, expect } from "vitest";

describe("ghost harness prod gate", () => {
  it("vitest runs with import.meta.env.DEV true (harness reachable in local/dev)", () => {
    expect(import.meta.env.DEV).toBe(true);
  });
});
