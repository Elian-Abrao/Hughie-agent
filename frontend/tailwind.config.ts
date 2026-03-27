import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        bg:           "#09090f",
        surface:      "#0f0f1c",
        surface2:     "#151528",
        surface3:     "#1c1c35",
        border:       "#1e1e38",
        "border-2":   "#2a2a48",
        accent:       "#7c6af7",
        "accent-h":   "#9a8bff",
        "accent-dim": "#25205a",
        muted:        "#505070",
        "muted-2":    "#7878a0",
        "user-bg":    "#101d10",
        "user-border":"#213521",
        "tool-bg":    "#0d0d22",
        "tool-text":  "#8888cc",
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
