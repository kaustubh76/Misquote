import "@testing-library/jest-dom/vitest";

// Testing Library's own retry window, raised alongside `testTimeout`. `findBy*`
// defaults to 1s, which is the one that actually expires first when the machine
// is busy — the outer test timeout never gets a chance to be the reason.
import { configure } from "@testing-library/dom";
configure({ asyncUtilTimeout: 5_000 });

// A page's build-time artifact read is made to agree with its runtime fetch.
//
// `page.tsx` files call `readArtifact` from `@/lib/build-artifact`, which reads
// `public/artifacts` off disk with `node:fs`. `serveArtifacts` stubs `fetch` and
// cannot reach that, so a test overriding an artifact got the fixture from the
// fetch and the **committed file** from the prerender. The page paints the real
// data first, every readiness signal fires against that paint, and the
// assertions then race the override.
//
// In production the two are the same bytes by construction — the build reads the
// file the browser will request. This restores that invariant under test rather
// than asking each test to remember it, which two of them did not.
//
// Untouched when a test declares nothing: `prerenderedArtifact` returns
// undefined and the real read happens, so a page test still exercises the real
// artifacts, which is the property that makes these tests worth having.
import { vi } from "vitest";

vi.mock("@/lib/build-artifact", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/build-artifact")>();
  const { prerenderedArtifact, MISSING } = await import("@/test/harness");
  return {
    ...actual,
    readArtifact: <T>(name: string): T | undefined => {
      const declared = prerenderedArtifact(name);
      if (declared === MISSING) return undefined;
      if (declared !== undefined) return declared as T;
      return actual.readArtifact<T>(name);
    },
  };
});
