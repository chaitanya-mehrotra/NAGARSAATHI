import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: { "/api": process.env.API_PROXY_TARGET || "http://127.0.0.1:8000" },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./tests/setup.ts"],
    restoreMocks: true,
    include: ["tests/**/*.test.ts", "tests/**/*.test.tsx"],
  },
});
