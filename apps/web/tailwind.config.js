/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        canvas: "var(--mh-canvas)",
        surface: {
          DEFAULT: "var(--mh-surface)",
          raised: "var(--mh-surface-raised)",
        },
        ink: {
          DEFAULT: "var(--mh-ink)",
          muted: "var(--mh-ink-muted)",
          faint: "var(--mh-ink-faint)",
          // legacy scale aliases → token ink for gradual migration
          50: "var(--mh-canvas)",
          100: "var(--mh-accent-soft)",
          200: "var(--mh-border)",
          300: "var(--mh-border-strong)",
          400: "var(--mh-ink-faint)",
          500: "var(--mh-ink-muted)",
          600: "var(--mh-ink-muted)",
          700: "var(--mh-ink)",
          800: "var(--mh-ink)",
          900: "var(--mh-ink)",
          950: "var(--mh-ink)",
        },
        accent: {
          DEFAULT: "var(--mh-accent)",
          soft: "var(--mh-accent-soft)",
          strong: "var(--mh-accent-strong)",
          fg: "var(--mh-accent-fg)",
        },
        warn: {
          DEFAULT: "var(--mh-warn)",
          soft: "var(--mh-warn-soft)",
        },
        danger: {
          DEFAULT: "var(--mh-danger)",
          soft: "var(--mh-danger-soft)",
        },
        ok: {
          DEFAULT: "var(--mh-ok)",
          soft: "var(--mh-ok-soft)",
        },
      },
      fontFamily: {
        display: ['"Fraunces"', "Georgia", "serif"],
        sans: ['"Sora"', "ui-sans-serif", "system-ui", "sans-serif"],
      },
      boxShadow: {
        panel: "var(--mh-shadow)",
      },
      keyframes: {
        rise: {
          "0%": { opacity: "0", transform: "translateY(6px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
      },
      animation: {
        rise: "rise 0.4s ease-out both",
      },
    },
  },
  plugins: [],
};
