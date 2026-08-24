import Link from "next/link";
import { Pill, statusTone } from "@/components/Pill";
import { count } from "@/lib/format";

/**
 * The two integrations, and the fact that they are different kinds of thing.
 *
 * This site is built on PancakeSwap and submitted to the TermiX track, and the
 * front end distinguished neither — because it barely mentioned either. The
 * venue reached a reader only as a label inside a provenance banner; the track
 * as one conditional section at the bottom of `/registry`.
 *
 * They are not the same kind of integration, and a reader arriving from one of
 * them should not have to work out which half is theirs:
 *
 *   - The **venue** is the substrate. Every number on every other page sits on
 *     it, so the interesting content is where the fork is not the original —
 *     each divergence a defect this project hit, with a cost and a test.
 *   - The **track** is a requirement. Standards citizenship plus one judged
 *     deliverable, so the interesting content is what was verified, what was
 *     not, and what the gate says today.
 *
 * Which is why the two cards are not symmetrical in what they show. The venue
 * card counts divergences; the track card carries a verdict pill. Making them
 * look alike would flatten exactly the distinction they exist to draw.
 *
 * Every figure is read. `divergences` is the artifact's array length, the gate
 * status is `status.json`'s own string — a page whose subject is "we checked
 * rather than assumed" cannot open with two typed numbers.
 */
export function Integrations({
  venue,
  divergences,
  gate,
}: {
  /** The venue's own name, from `venue.json`. Absent when it has not been generated. */
  venue?: string;
  divergences?: number;
  /** The judged deliverable's gate, verbatim from `status.json`. */
  gate?: { status: string; detail: string };
}) {
  // Nothing to route to. Rendering an empty pair of cards would claim two
  // integrations exist and say nothing about either.
  if (venue === undefined && gate === undefined) return null;

  return (
    <div className="grid gap-4 sm:grid-cols-2">
      {venue !== undefined && (
        <Link
          href="/venue"
          className="surface surface-hover group rounded-lg border border-glass-line bg-glass p-5 no-underline"
        >
          <p className="m-0 font-mono text-[0.6875rem] tracking-wide text-faint uppercase">
            The venue
          </p>
          <p className="mt-1 mb-0 text-base font-semibold text-ink group-hover:text-accent">
            {venue}
          </p>
          <p className="mt-2 mb-0 text-sm text-dim">
            Every number here sits on it.{" "}
            {divergences !== undefined && (
              <>
                {count(divergences)} places it is not Uniswap, each with a test.
              </>
            )}
          </p>
        </Link>
      )}

      {gate !== undefined && (
        <Link
          href="/registry"
          className="surface surface-hover group rounded-lg border border-glass-line bg-glass p-5 no-underline"
        >
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <p className="m-0 font-mono text-[0.6875rem] tracking-wide text-faint uppercase">
                The track
              </p>
              <p className="mt-1 mb-0 text-base font-semibold text-ink group-hover:text-accent">
                TermiX
              </p>
            </div>
            {/* The verdict, not a decoration. The deliverable is amber and the
                card says so in the first screen rather than three pages in —
                a track card that only advertised would be the thing this
                project argues against. */}
            <Pill tone={statusTone(gate.status)}>{gate.status}</Pill>
          </div>
          <p className="mt-2 mb-0 text-sm text-dim">
            One judged deliverable, plus ERC-8004 and ERC-8183 citizenship.{" "}
            {gate.detail}.
          </p>
        </Link>
      )}
    </div>
  );
}
