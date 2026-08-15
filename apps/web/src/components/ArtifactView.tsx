"use client";

import { useEffect, useState } from "react";
import { ErrorNotice } from "@/components/Refusal";
import { CardSkeleton } from "@/components/Skeleton";
import type { ArtifactError, Loaded } from "@/lib/artifacts";

/** How long a load may take before it is worth saying so. */
const ANNOUNCE_AFTER_MS = 200;

/**
 * The load-then-render-or-explain shape, once.
 *
 * ## Why the children are a function
 *
 * `children: (value: T) => ReactNode` is not a style preference. With a plain
 * `{children}` there is always a scope in which the artifact may or may not
 * have loaded, and the tempting thing to write there is `q?.windows ?? 20` — a
 * plausible literal standing in for a number nobody has fetched. That is
 * exactly what `/methods` shipped: a page arguing "a floor a UI could get wrong
 * is not a floor" while restating all four floors as constants.
 *
 * With a render prop there is no such scope. The value is only in hand once it
 * has loaded, so the fallback literal has nothing to fall back *from*. The
 * defect stops being a matter of discipline and becomes a type error.
 *
 * ## Why the live region is a sibling
 *
 * `aria-busy="true"` instructs assistive technology to defer processing changes
 * inside that subtree. A status region nested within the busy container is
 * therefore silent for exactly as long as it has something to say. It has to be
 * a sibling, rendered *before* it, and it has to exist in the first paint —
 * a live region inserted at the same moment as its text announces nothing.
 */
export function ArtifactView<T>({
  state,
  label,
  pending,
  skeletons = 1,
  error,
  className = "mt-10",
  children,
}: {
  state: Loaded<T> | null;
  /** A noun phrase: "the advantage report", "the readiness gates". */
  label: string;
  /**
   * An extra reason to keep waiting. The Overview passes
   * `index === null || agents === null`, because its cards arrive in a second
   * round after the index and unmounting the skeletons early left a bare hole
   * on the landing page.
   */
  pending?: boolean;
  skeletons?: number;
  error?: { title?: string; remedy?: React.ReactNode };
  className?: string;
  children: (value: T) => React.ReactNode;
}) {
  const busy = pending ?? state === null;
  const message = useLoadAnnouncement(busy, state, label);

  return (
    <>
      <p role="status" aria-live="polite" aria-atomic="true" className="visually-hidden">
        {message}
      </p>

      <div aria-busy={busy} className={className}>
        {busy && (
          <div className="grid gap-5">
            {Array.from({ length: skeletons }, (_, i) => (
              <CardSkeleton key={i} />
            ))}
          </div>
        )}

        {!busy && state && !state.ok && (
          <ErrorNotice
            title={error?.title ?? `Could not load ${label}`}
            detail={state.error.message}
            remedy={error?.remedy ?? remedyFor(state.error)}
          />
        )}

        {!busy && state?.ok && children(state.value)}
      </div>
    </>
  );
}

/**
 * What the status region says, and when.
 *
 * The "loading" message is delayed. A warm cache settles within a tick, and
 * announcing "Loading…" immediately followed by "Loaded." is chatter that
 * teaches people to ignore the region. A slow load — the only case where the
 * message earns its place — always crosses the threshold.
 *
 * Completion is announced either way. `ErrorNotice` is a `role="alert"` and
 * will be read on its own, but a *successful* load has nothing else to signal
 * that the wait is over.
 */
function useLoadAnnouncement<T>(
  busy: boolean,
  state: Loaded<T> | null,
  label: string,
): string {
  const [message, setMessage] = useState("");

  useEffect(() => {
    if (busy) {
      const timer = setTimeout(() => setMessage(`Loading ${label}…`), ANNOUNCE_AFTER_MS);
      return () => clearTimeout(timer);
    }
    if (state) {
      setMessage(state.ok ? `${sentence(label)} loaded.` : `${sentence(label)} could not be loaded.`);
    }
    return undefined;
  }, [busy, state, label]);

  return message;
}

function sentence(label: string): string {
  return label.charAt(0).toUpperCase() + label.slice(1);
}

/**
 * A remedy that matches the actual cause.
 *
 * This is where `ArtifactError.status` finally gets read. It was stored and
 * never used, and the honest options were to delete it or to use it; in a file
 * whose docstring is a twenty-five-line argument that causes must stay distinct
 * all the way to the surface, using it is the one consistent with the argument.
 */
function remedyFor(error: ArtifactError): React.ReactNode {
  switch (error.kind) {
    case "http":
      return error.status === 404 ? (
        <>
          Nothing has generated this file yet. Run{" "}
          <code className="font-mono text-xs">make artifacts</code>.
        </>
      ) : (
        <>The server returned {error.status}. The file may exist but be unreadable.</>
      );
    case "parse":
      return <>The file was served but is not JSON — it may have been half-written.</>;
    case "network":
      return (
        <>
          Serve the site over HTTP rather than opening it from disk — run{" "}
          <code className="font-mono text-xs">make web</code>.
        </>
      );
    default:
      return undefined;
  }
}
