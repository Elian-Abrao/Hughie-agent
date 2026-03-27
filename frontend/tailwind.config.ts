import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        bg: "#0f0f0f",
        surface: "#1a1a1a",
        surface2: "#242424",
        border: "#2e2e2e",
        accent: "#7c6af7",
        "accent-dim": "#3d3465",
        muted: "#6b6b6b",
        "user-bg": "#1e2d1e",
        "user-border": "#2d4a2d",
        "tool-bg": "#1a1a2e",
        "tool-text": "#8888cc",
      },
      animation: {
        blink: "blink 0.8s step-start infinite",
        spin: "spin 0.7s linear infinite",
      },
      keyframes: {
        blink: { "50%": { opacity: "0" } },
      },
      fontFamily: {
        sans: [
          "-apple-system",
          "BlinkMacSystemFont",
          '"Segoe UI"',
          "system-ui",
          "sans-serif",
        ],
        mono: ['"JetBrains Mono"', '"Fira Code"', "monospace"],
      },
    },
  },
  plugins: [],
} satisfies Config;
