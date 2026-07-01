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
      },
      fontFamily: {
        mono: ["JetBrains Mono", "Fira Code", "Consolas", "monospace"],
      },
      keyframes: {
        "bounce-in": {
          "0%": { transform: "scale(0.3) translateY(12px)", opacity: "0" },
          "60%": { transform: "scale(1.05) translateY(0)", opacity: "1" },
          "80%": { transform: "scale(0.98)" },
          "100%": { transform: "scale(1)" },
        },
      },
      animation: {
        "bounce-in": "bounce-in 450ms cubic-bezier(0.34, 1.56, 0.64, 1)",
      },
    },
  },
  plugins: [],
};
