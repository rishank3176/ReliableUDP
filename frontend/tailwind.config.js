/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#07111f",
        panel: "#10192b",
        panel2: "#162338",
        line: "#2a3d5c",
        mist: "#d7e2f2",
        faint: "#93a4c0",
        accent: "#3ee0c5",
        good: "#3dd68c",
        warn: "#f0c36a",
        bad: "#ff7b8a",
      },
      fontFamily: {
        sans: ["Avenir Next", "Segoe UI", "Trebuchet MS", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      boxShadow: {
        card: "0 12px 40px rgba(0, 0, 0, 0.28)",
      },
    },
  },
  plugins: [],
};
