import { defineConfig, mergeConfig } from "vitest/config";
import viteConfig from "./vite.config.ts";

// Merges the real vite.config.ts (so tests see the same @vitejs/plugin-react
// setup the app itself builds with) rather than duplicating plugin config
// here and risking the two drifting apart.
export default mergeConfig(
  viteConfig,
  defineConfig({
    test: {
      environment: "jsdom",
      setupFiles: ["./src/test/setup.ts"],
      css: true,
    },
  }),
);
