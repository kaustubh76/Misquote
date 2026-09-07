import Link from "next/link";
import type { Metadata } from "next";
import { ROUTES } from "@/lib/routes";

export const metadata: Metadata = { title: "No such page" };

/**
 * What each route is for. Keyed by href, and the *routes* come from `ROUTES`.
 *
 * This was a second hand-maintained list of the site's pages, and it drifted to
 * six against eight — omitting `/vectors` and `/vetting`, the two newest — while
 * the page around it said "exactly the pages listed below and nothing else". A
 * reader who mistyped `/vetting` was told the site has no such page, on the one
 * page whose entire job is to say what the site does have.
 *
 * A missing blurb degrades to the route's own nav label rather than dropping
 * the entry, so a route added to `ROUTES` appears here whether or not anyone
 * remembers this map.
 */
const BLURB: Record<string, string> = {
  "/": "every agent that exists, and everything advertised that does not",
  "/quote": "your own positions, checked against the tape before anything is queued",
  "/activate": "what hiring an agent would cost you, and why there is no button",
  "/category": "the four jobs you can hire for, and what each is judged on",
  "/venue": "where PancakeSwap is not Uniswap, and what each difference cost",
  "/advantage": "hiring an agent against doing the job yourself",
  "/methods": "how a quote is made, and what stops it being made",
  "/vectors": "the tick math, compared against Uniswap's own Solidity",
  "/assumptions": "every number here traces to one of these",
  "/registry": "ERC-8004 and ERC-8183, and what a hire costs",
  "/studio": "A seller agent on the BNB Agent Studio, and the quote it signs",
  "/vetting": "the pools and addresses, read from chain",
  "/tape": "the swaps every quote here was replayed over, and the gaps in them",
  "/status": "the readiness gates, and what is not built",
};

/* `/tape` was the one route of thirteen with no entry, so its card rendered
   "Tape" twice — the label as the heading and the label again as the blurb.
   The degrade-to-label branch is deliberate and stays; it was covering a gap
   rather than doing its job. `tests/web/test_route_lists_agree.py` keeps
   `ROUTES` and this file's source list in step, but it has nothing to say
   about a map that is merely incomplete. */

/**
 * A 404 that belongs to this site.
 *
 * Next's stock error page injects its own `body{color:#000;background:#fff}`,
 * which ignores the token palette *and* the `data-theme` the boot script pinned
 * — so a reader who chose Light on a dark OS got a black page, and vice versa.
 * It is also `100vh` flex-centred, which pushes the nav off screen, and it
 * offers no way back.
 *
 * Being a route rather than a special case means it renders inside the layout:
 * same nav, same palette, same theme. It also exports its own title, which is
 * the first page on the site to have one that is not the site's.
 *
 * One deployment caveat worth keeping: this emits `out/404.html`, which real
 * static hosts serve for an unknown path. `python3 -m http.server` — what
 * `make web-static` runs — does not know that convention and will serve its own
 * plain-text page instead. That is a property of the server, not a bug here.
 */
export default function NotFound() {
  return (
    <>
      <h1 className="text-3xl leading-[1.15] font-semibold text-balance">No such page</h1>
      <p className="mt-3 max-w-[62ch] text-dim">
        A static export contains exactly the pages below and nothing else. No data is
        missing — this route was never generated.
      </p>

      <ul className="mt-8 grid list-none gap-3 p-0 sm:grid-cols-2">
        {ROUTES.map(({ href, label }) => (
          <li key={href}>
            <Link
              href={href}
              className="surface surface-hover block rounded-md border border-glass-line bg-glass p-4 no-underline"
            >
              <span className="block text-md font-semibold text-ink">{label}</span>
              <span className="mt-1 block text-sm text-dim">{BLURB[href] ?? label}</span>
            </Link>
          </li>
        ))}
      </ul>

      <p className="mt-8 text-sm text-faint">
        Agent pages live at <code className="font-mono text-xs">/agent/&lt;name&gt;</code>,
        one per agent on the overview.
      </p>
    </>
  );
}
