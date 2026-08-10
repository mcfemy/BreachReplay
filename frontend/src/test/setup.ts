// Registers jest-dom's matchers (toBeInTheDocument, toHaveTextContent, ...)
// on Vitest's own `expect`, typed via the /vitest subpath — see
// @testing-library/jest-dom's docs for why this differs from the plain
// `@testing-library/jest-dom` import used under Jest.
import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// RTL doesn't auto-cleanup outside Jest's global afterEach convention.
afterEach(() => {
  cleanup();
  localStorage.clear();
});

// jsdom has no matchMedia implementation; NetworkMap.tsx reads
// `window.matchMedia('(prefers-reduced-motion: reduce)')` on every render.
if (!window.matchMedia) {
  window.matchMedia = (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  }) as unknown as MediaQueryList;
}
