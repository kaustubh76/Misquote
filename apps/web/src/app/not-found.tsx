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
  "/advantage": "hiring an agent against doing the job yourself",
  "/methods": "how a quote is made, and what stops it being made",
  "/vectors": "the tick math, compared against Uniswap's own Solidity",
  "/assumptions": "every number here traces to one of these",
  "/registry": "ERC-8004 and ERC-8183, and what a hire costs",
  "/vetting": "the pools and addresses, read from chain",
  "/status": "the readiness gates, and what is not built",
};

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
      <h1 className="text-2xl font-semibold">No such page</h1>
      <p className="mt-3 max-w-[62ch] text-dim">
        This site is a static export: it contains exactly the pages listed below and
        nothing else, so a URL that is not one of them was never generated. No data is
        missing — the route simply does not exist.
      </p>

      <ul className="mt-8 grid list-none gap-3 p-0 sm:grid-cols-2">
        {ROUTES.map(({ href, label }) => (
          <li key={href}>
            <Link
              href={href}
              className="block rounded-md border border-line bg-panel p-4 no-underline hover:border-accent"
            >
              <span className="block text-md font-semibold text-ink">{label}</span>
              <span className="mt-1 block text-sm text-dim">{BLURB[href] ?? label}</span>
            </Link>
          </li>
        ))}
      </ul>

      <p className="mt-8 text-sm text-faint">
        Agent pages live at <code className="font-mono text-xs">/agent/&lt;name&gt;</code> —
        one per agent named in{" "}
        <code className="font-mono text-xs">artifacts/index.json</code>.
      </p>
    </>
  );
}
