import Link from "next/link";
import { count } from "@/lib/format";
import { routesIn } from "@/lib/routes";

/**
 * The seven evidence routes, each carrying one figure out of its own artifact.
 *
 * The landing page used to end at the not-built ledger, so the half of this
 * site that exists to be checked — seven pages of tick math, venue divergences,
 * pool badges, assumptions and gates — was reachable only through a nav band a
 * reader had no reason to look at. A marketplace that argues its numbers are
 * auditable should say what there is to audit on the page that makes the claim.
 *
 * Every figure is read from the artifact at build time by `app/page.tsx` and
 * arrives here as a number. That is the constraint the component is shaped
 * around: it cannot compute, cannot round differently from the page it points
 * at, and cannot render a route whose figure is missing as a zero. `entry` is
 * `null` for anything the build could not read, and a null renders the route
 * with its description and no number at all — the same rule the rest of the
 * site follows, one screen from where it is stated.
 */
export interface EvidenceEntry {
  /** The route's own headline figure, already formatted. */
  figure: string;
  /** What the figure counts, in the words its own page uses. */
  of: string;
}

export function EvidenceRail({
  entries,
}: {
  entries: Record<string, EvidenceEntry | null>;
}) {
  // `routesIn` rather than a second filter over ROUTES: the nav already
  // reads the groups through it, and two definitions of "the evidence routes"
  // is how one of them comes to be missing a page.
  const routes = routesIn("evidence");

  return (
    <ul className="m-0 grid list-none gap-3 p-0 sm:grid-cols-2 lg:grid-cols-3">
      {routes.map((route) => {
        const entry = entries[route.href] ?? null;
        return (
          <li key={route.href}>
            <Link
              href={route.href}
              className="surface surface-hover flex h-full flex-col justify-between gap-3 rounded-lg border border-glass-line bg-glass p-4 no-underline"
            >
              <span className="font-mono text-xs tracking-widest text-faint uppercase">
                {route.label}
              </span>
              {entry ? (
                <span className="flex items-baseline gap-2">
                  <span className="tabular text-xl font-semibold text-ink">
                    {entry.figure}
                  </span>
                  <span className="min-w-0 text-xs text-dim">{entry.of}</span>
                </span>
              ) : (
                /* Not a zero and not a dash in the figure slot. An artifact
                   this build could not read is not a count of nothing, and the
                   whole argument of the page above is that those are different
                   claims. */
                <span className="text-xs text-faint">
                  Its artifact was not readable at build time.
                </span>
              )}
            </Link>
          </li>
        );
      })}
    </ul>
  );
}

/** The figure for a route, or null when the artifact was missing a field. */
export function entryOf(figure: number | undefined, of: string): EvidenceEntry | null {
  return typeof figure === "number" && Number.isFinite(figure)
    ? { figure: count(figure), of }
    : null;
}
