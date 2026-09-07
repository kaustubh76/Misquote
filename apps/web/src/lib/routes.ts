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
  // Second, deliberately. The simulation layer shipped with no entry point at
  // all — the only affordance in the UI was the button that *leaves* one — so a
  // visitor had to know `?scenario=` existed and guess a fixture name. A feature
  // nobody can find is one nobody built.
  { href: "/demo", label: "Demo", group: "product" },
  { href: "/category", label: "Agents", group: "product" },
  { href: "/quote", label: "Quote", group: "product" },
  // Beside `/quote` rather than in the evidence band, and that placement is the
  // argument. The PancakeSwap deliverable lived entirely inside `/venue`, which
  // is a document about `slot0` layout and init-code hashes — correct, and not
  // where somebody asking "should I provide liquidity here" arrives. This is
  // the same kind of thing `/quote` is: an answer about money, for a person who
  // has some.
  { href: "/simulate", label: "Simulate", group: "product" },
  // "Activate" is what the page does to a key. "Hire" is what a visitor came
  // to do, and it is the verb the whole site is built around — it appeared in
  // the nav nowhere, on the tab that performs it.
  { href: "/activate", label: "Hire", group: "product" },
  { href: "/registry", label: "Registry", group: "product" },
  // Last in the product band, and it earns the slot the way `/demo` earned
  // second: the BNB Agent Studio work — a scaffolded seller agent, deployed,
  // holding an ERC-8004 identity the vendor's own CLI minted — was reachable
  // from one inline link in the hero and from nowhere else. A judge assessing
  // the track this project's main entry answers had no page to land on.
  { href: "/studio", label: "Studio", group: "product" },
  { href: "/advantage", label: "Advantage", group: "evidence" },
  { href: "/methods", label: "Methods", group: "evidence" },
  { href: "/assumptions", label: "Assumptions", group: "evidence" },
  // "Vectors" named the data structure, not the claim. 19,546 answers
  // differentially tested against real PancakeSwap Solidity at exact integer
  // equality is probably the most credible artifact here, and it was labelled
  // like a math library in the tenth slot of a scrolling nav.
  { href: "/vectors", label: "Tick math", group: "evidence" },
  { href: "/venue", label: "Venue", group: "evidence" },
  { href: "/vetting", label: "Vetting", group: "evidence" },
  { href: "/tape", label: "Tape", group: "evidence" },
  { href: "/status", label: "Status", group: "evidence" },
] as const;

/** The routes in one band, in the order the nav shows them. */
export function routesIn(group: RouteGroup): readonly Route[] {
  return ROUTES.filter((route) => route.group === group);
}
