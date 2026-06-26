import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        surface: "#0a1221",
        card: "#0f1a2f",
        border: "#22304c",
        accent: "#f4c95d",
        success: "#39d98a",
        danger: "#ff6b6b",
        skyline: "#4fb3ff",
      },
      boxShadow: {
        glow: "0 20px 60px rgba(79, 179, 255, 0.16)",
      },
      backgroundImage: {
        hero:
          "radial-gradient(circle at top, rgba(79,179,255,0.22), transparent 34%), radial-gradient(circle at 80% 0%, rgba(244,201,93,0.18), transparent 26%), linear-gradient(180deg, #08101d 0%, #0b1528 45%, #08101d 100%)",
      },
    },
  },
  plugins: [],
};

export default config;

