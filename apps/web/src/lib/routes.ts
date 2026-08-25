/**
 * Every page this site has, in the order the nav shows them.
 *
 * One list, in a module with no `"use client"`, because two consumers need it
 * from opposite sides of the boundary: `Nav.tsx` is a client component, and
 * `app/not-found.tsx` is a server one.
 *
 * That boundary is the reason this file exists rather than an export on `Nav`.
 * Importing a *value* out of a `"use client"` module into a server component
 * does not give you the value — it gives a client-reference proxy, and the
 * failure is at prerender rather than at typecheck:
 *
 *     TypeError: g.LINKS.map is not a function
 *     Error occurred prerendering page "/methods"
 *
 * Before there was one list there were two, and they drifted: the 404 named six
 * routes against the nav's eight, omitting `/vectors` and `/vetting` — the two
 * newest — directly under the sentence "this site contains exactly the pages
 * listed below and nothing else". A reader who mistyped `/vetting` was told the
 * site has no such page, by the one page whose job is to say what it does have.
 */
/**
 * Which band of the nav a route belongs to.
 *
 * `product` is what someone came to do — look at the agents, get a quote, hire
 * one, browse the registry. `evidence` is how any of it is checked. The split
 * exists because the flat list stopped working: eleven routes fitted a single
 * strip at 1280px and thirteen do not, and the honest ordering was never
 * alphabetical or chronological anyway — a reader wanting a quote and a reader
 * auditing the tick math are doing different things.
 */
export type RouteGroup = "product" | "evidence";

export interface Route {
  href: string;
  label: string;
  group: RouteGroup;
}

export const ROUTES: readonly Route[] = [
  { href: "/", label: "Overview", group: "product" },
  { href: "/quote", label: "Quote", group: "product" },
  { href: "/activate", label: "Activate", group: "product" },
  { href: "/category", label: "Categories", group: "product" },
  { href: "/registry", label: "Registry", group: "product" },
  { href: "/advantage", label: "Advantage", group: "evidence" },
  { href: "/methods", label: "Methods", group: "evidence" },
  { href: "/assumptions", label: "Assumptions", group: "evidence" },
  { href: "/vectors", label: "Vectors", group: "evidence" },
  { href: "/venue", label: "Venue", group: "evidence" },
  { href: "/vetting", label: "Vetting", group: "evidence" },
  { href: "/tape", label: "Tape", group: "evidence" },
  { href: "/status", label: "Status", group: "evidence" },
] as const;

/** The routes in one band, in the order the nav shows them. */
export function routesIn(group: RouteGroup): readonly Route[] {
  return ROUTES.filter((route) => route.group === group);
}
