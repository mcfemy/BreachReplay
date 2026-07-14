/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        breach: {
          bg: "#0a0e1a",
          surface: "#111827",
          border: "#1f2937",
          accent: "#ef4444",
          green: "#22c55e",
          yellow: "#eab308",
          blue: "#3b82f6",
          text: "#f9fafb",
          muted: "#6b7280",
        },
        // Phase 1+ design tokens (BREACHREPLAY_GAME_OVERHAUL_SPEC.md section 1).
        // Mirrors frontend/src/theme/tokens.ts — additive, doesn't touch `breach` above.
        void: "#0B0F14",
        panel: "#121A23",
        phosphor: "#FFB454",
        bleed: "#E5484D",
        contain: "#3DD68C",
        dim: "#8A97A5",
      },
      fontFamily: {
        mono: ["JetBrains Mono", "Fira Code", "Consolas", "monospace"],
        display: ["Space Grotesk", "sans-serif"],
        term: ["IBM Plex Mono", "monospace"],
        body: ["Inter", "sans-serif"],
      },
      keyframes: {
        "bounce-in": {
          "0%": { transform: "scale(0.3) translateY(12px)", opacity: "0" },
          "60%": { transform: "scale(1.05) translateY(0)", opacity: "1" },
          "80%": { transform: "scale(0.98)" },
          "100%": { transform: "scale(1)" },
        },
        "host-flash": {
          "0%": { backgroundColor: "rgba(250, 204, 21, 0.35)" },
          "100%": { backgroundColor: "rgba(250, 204, 21, 0)" },
        },
        "impact-flash": {
          "0%": { backgroundColor: "rgba(239, 68, 68, 0.45)" },
          "100%": { backgroundColor: "rgba(239, 68, 68, 0)" },
        },
        "contained-glow": {
          "0%": { boxShadow: "0 0 0 rgba(34, 197, 94, 0)" },
          "30%": { boxShadow: "0 0 32px rgba(34, 197, 94, 0.55)" },
          "100%": { boxShadow: "0 0 0 rgba(34, 197, 94, 0)" },
        },
      },
      animation: {
        "bounce-in": "bounce-in 450ms cubic-bezier(0.34, 1.56, 0.64, 1)",
        "host-flash": "host-flash 1000ms ease-out",
        "impact-flash": "impact-flash 900ms ease-out",
        "contained-glow": "contained-glow 1400ms ease-out",
      },
    },
  },
  plugins: [],
};
