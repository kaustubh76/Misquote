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

    // Raised from the 5s/1s defaults, and it stays raised — but for one of the
    // two reasons it used to carry, because the other one is fixed.
    //
    // The mechanism was misdiagnosed. This said the harness "re-serialises"
    // the artifacts per request; it re-*read* them. `serveArtifacts` called
    // `readFileSync` on every fetch, so each of the eleven `/assumptions` tests
    // re-read 181,816 bytes synchronously on a worker thread vitest was also
    // running three other suites on, and every `findBy*` on that worker spent
    // its retry window waiting for a thread busy re-reading a file it already
    // had. `src/test/harness.tsx` memoises by filename now: eight consecutive
    // clean runs, about 20% faster, slowest single test 3.4s.
    //
    // That measurement then argued for dropping this to 8s, and dropping it was
    // wrong. The machine picked up unrelated load — 44 against 8 cores — and
    // seven tests blew an 8s ceiling that had been comfortable an hour earlier.
    // Which is the half of the original comment that was right all along: these
    // run while a `next build` runs, and contention is not something the suite
    // can fix from inside itself.
    //
    // So: the blocking is gone where it was caused, and the headroom stays for
    // the hazard it was actually protecting against. 15s still fails a
    // genuinely hung render; it just does not report a busy machine as a defect.
    testTimeout: 15_000,
  },
});
