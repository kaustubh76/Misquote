import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./vitest.setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],

    // Raised from the 5s/1s defaults.
    //
    // Every page test renders a real view against the real artifacts, and the
    // harness re-serialises them per request — `assumptions.json` alone is 80KB
    // of JSON stringified on each fetch. That is fast in isolation and not fast
    // when a `next build` is running on the same machine, which is exactly when
    // these run. Two different tests flaked that way in one session, each
    // passing on every rerun.
    //
    // A flake is worse than a slow test: it teaches people to rerun rather than
    // to read. These bounds still fail a genuinely hung render, they just stop
    // reporting a busy CPU as a defect.
    testTimeout: 15_000,
  },
});
