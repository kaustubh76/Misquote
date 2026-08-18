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
export interface Route {
  href: string;
  label: string;
}

export const ROUTES: readonly Route[] = [
  { href: "/", label: "Overview" },
  { href: "/venue", label: "Venue" },
  { href: "/advantage", label: "Advantage" },
  { href: "/methods", label: "Methods" },
  { href: "/vectors", label: "Vectors" },
  { href: "/assumptions", label: "Assumptions" },
  { href: "/registry", label: "Registry" },
  { href: "/vetting", label: "Vetting" },
  { href: "/status", label: "Status" },
] as const;
