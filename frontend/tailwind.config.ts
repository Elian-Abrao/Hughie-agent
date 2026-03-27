import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        bg:           "rgb(var(--bg) / <alpha-value>)",
        surface:      "rgb(var(--surface) / <alpha-value>)",
        surface2:     "rgb(var(--surface2) / <alpha-value>)",
        surface3:     "rgb(var(--surface3) / <alpha-value>)",
        border:       "rgb(var(--border) / <alpha-value>)",
        "border-2":   "rgb(var(--border-2) / <alpha-value>)",
        accent:       "rgb(var(--accent) / <alpha-value>)",
        "accent-h":   "rgb(var(--accent-h) / <alpha-value>)",
        "accent-dim": "rgb(var(--accent-dim) / <alpha-value>)",
        text:         "rgb(var(--text) / <alpha-value>)",
        strong:       "rgb(var(--text-strong) / <alpha-value>)",
        muted:        "rgb(var(--muted) / <alpha-value>)",
        "muted-2":    "rgb(var(--muted-2) / <alpha-value>)",
        "user-bg":    "rgb(var(--user-bg) / <alpha-value>)",
        "user-border":"rgb(var(--user-border) / <alpha-value>)",
        "tool-bg":    "rgb(var(--tool-bg) / <alpha-value>)",
        "tool-text":  "rgb(var(--tool-text) / <alpha-value>)",
      },
      fontFamily: {
        sans: ['"Inter"', "-apple-system", "BlinkMacSystemFont", '"Segoe UI"', "system-ui", "sans-serif"],
        mono: ['"JetBrains Mono"', '"Fira Code"', "Consolas", "monospace"],
      },
      animation: {
        blink:  "blink 0.9s step-start infinite",
        fadein: "fadein 0.15s ease-out",
        "spin-slow": "spin 1s linear infinite",
      },
      keyframes: {
        blink:  { "50%": { opacity: "0" } },
        fadein: { from: { opacity: "0", transform: "translateY(4px)" }, to: { opacity: "1", transform: "translateY(0)" } },
      },
    },
  },
  plugins: [],
} satisfies Config;
