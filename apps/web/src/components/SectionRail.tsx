/**
 * In-page links for a page that does not fit on a screen.
 *
 * `src/components/AgentDetail.tsx` is 575 lines and renders five sections; a
 * judge deep-linking to a tearsheet arrives at the top of all of them with no
 * indication that the provenance block they were sent for is four screens
 * down. This is that page's own table of contents.
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
          <li key={item.id}>
            <a
              href={`#${item.id}`}
              className="inline-block rounded-full border border-glass-line bg-glass px-3 py-1 font-mono text-xs tracking-wide text-dim no-underline transition-colors hover:border-brand-line hover:text-brand"
            >
              {item.label}
            </a>
          </li>
        ))}
      </ul>
    </nav>
  );
}
