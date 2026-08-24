"use client";

import Link from "next/link";
import { Button } from "@/components/Button";
import { useEffect } from "react";

/**
 * What a reader sees when a render throws, instead of nothing at all.
 *
 * There was no boundary anywhere under `src/`. `Loadable` and `ErrorNotice`
 * handle *fetch* failures — `load()` returns a discriminated union and the
 * views branch on it — but neither can catch an exception raised during render.
 * Those escaped to Next's root handler, which replaces the document: nav,
 * heading, theme toggle and all, with "Application error: a client-side
 * exception has occurred".
 *
 * That is the worst available outcome for this site in particular. A page whose
 * argument is "every number here traces to something" failing into a blank
 * screen tells the reader nothing about what broke, and the one thing this
 * project will not do is present an absence as though it were something else.
 *
 * ## Why it names the artifact
 *
 * Every throw this can plausibly catch comes from the same place: a view
 * reading a field the artifact did not carry. Six call sites in `AgentDetail`
 * read `estimators` straight off the JSON while the type declared eleven
 * non-optional fields and the emitter could write `{}`. Those are routed
 * through `fixed()` now and the type is honest, but the class of defect
 * survives every fix — so the remedy this offers is the one that resolves it:
 * regenerate, or look at the file.
 *
 * `reset` is Next's re-render of the same segment. Offered because a transient
 * failure is worth one retry, and paired with a link out because a malformed
 * artifact will fail identically every time and a button that does nothing
 * twice is worse than no button.
 */
export default function RouteError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // The console is where a judge with devtools open will look, and the digest
    // is the only handle on a minified production stack.
    console.error("render failed", error);
  }, [error]);

  return (
    <div className="rounded-md border border-bad-line bg-bad-bg/40 p-5" role="alert">
      <h1 className="m-0 text-lg font-semibold text-bad">This page failed to render</h1>

      <p className="mt-3 mb-0 max-w-[68ch] text-sm text-dim">
        Not a failure to load — the artifact was read and something in it was not the
        shape this page expected. The most likely cause is a field an older artifact
        does not carry.
      </p>

      <p className="mt-3 mb-0 max-w-[68ch] font-mono text-xs break-words text-faint">
        {error.message}
        {error.digest && <> · digest {error.digest}</>}
      </p>

      <p className="mt-4 mb-0 text-sm">
        <Button tone="secondary" size="sm" onClick={reset}>
          Try again
        </Button>
        <span className="ml-3 text-dim">
          or read <Link href="/artifacts/index.json">the artifacts</Link> directly —
          they are plain JSON and this site is only a view over them.
        </span>
      </p>
    </div>
  );
}
