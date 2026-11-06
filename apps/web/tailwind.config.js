/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: {
          50: "#f4f7fb",
          100: "#e6edf6",
          200: "#c9d7ea",
          300: "#9bb4d1",
          400: "#6a8fb5",
          500: "#4a7199",
          600: "#38597a",
          700: "#2e4863",
          800: "#273c52",
          900: "#223345",
          950: "#15202c",
        },
        accent: {
          DEFAULT: "#0f766e",
          soft: "#ccfbf1",
          strong: "#115e59",
        },
        warn: {
          DEFAULT: "#b45309",
          soft: "#ffedd5",
        },
        danger: {
          DEFAULT: "#b91c1c",
          soft: "#fee2e2",
        },
      },
      fontFamily: {
        display: ['"Source Serif 4"', "Georgia", "serif"],
        sans: ['"IBM Plex Sans"', "ui-sans-serif", "system-ui", "sans-serif"],
      },
      boxShadow: {
        panel: "0 1px 0 rgba(34,51,69,0.06), 0 12px 32px rgba(21,32,44,0.08)",
      },
      keyframes: {
        rise: {
          "0%": { opacity: "0", transform: "translateY(8px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        pulseSoft: {
          "0%, 100%": { opacity: "1" },
          "50%": { opacity: "0.55" },
        },
      },
      animation: {
        rise: "rise 0.45s ease-out both",
        "pulse-soft": "pulseSoft 1.8s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};
