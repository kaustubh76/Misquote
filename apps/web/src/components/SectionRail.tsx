/**
 * In-page links for a page that does not fit on a screen.
 *
 * A judge deep-linking to a long route arrives at the top of it with no
 * indication that the block they were sent for is four screens down.
 *
 * Four call sites now — both halves of `/agent/[slug]`, `/vetting` and
 * `/registry` — so this is no longer "that page's table of contents". The
 * threshold is whether a reader can lose a section: `/advantage` and `/status`
 * have two each, both reachable in a screen, and a two-pill rail is chrome
 * rather than navigation.
 *
 * No line count here on purpose. This docstring used to cite one, `/registry`
 * quoted it back to justify itself, and by then the file had grown past it —
 * one number restated in two places, wrong in both.
 *
 * Two decisions worth stating.
 *
 * It is **not** `position: sticky`. A pinned second bar under a header that is
 * already two rows would take a third of a 390px viewport, and it would need
 * the measured overflow-fade machinery `src/components/Nav.tsx` carries for
 * exactly that reason. Wrapping costs a reader one scroll back to the top and
 * costs this file nothing.
 *
 * It is **not** inside `<header>`, and that one is load-bearing rather than
 * tidy. `apps/web/scripts/check-pages.mjs` finds the current route's nav pill
 * by querying `header nav[aria-label] ul` and taking the first list with an
 * `[aria-current]` in it. A second labelled nav inside the header would be
 * found first, contain no `aria-current`, and report "no nav link marked
 * aria-current" on every agent route.
 */
export function SectionRail({
  label,
  items,
}: {
  label: string;
  items: { id: string; label: string }[];
}) {
  return (
    <nav aria-label={label} className="mt-4 mb-8">
      <ul className="m-0 flex list-none flex-wrap gap-1.5 p-0">
        {items.map((item) => (
          <li key={item.id} className="min-w-0">
            <a
              href={`#${item.id}`}
              className="inline-block max-w-full rounded-full border border-glass-line bg-glass px-3 py-1 font-mono text-xs tracking-wide break-words text-dim no-underline transition-colors hover:border-brand-line hover:text-brand"
            >
              {item.label}
            </a>
          </li>
        ))}
      </ul>
    </nav>
  );
}
