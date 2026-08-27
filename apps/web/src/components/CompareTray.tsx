"use client";

/*
 * `initial` on a motion component server-renders its own start frame as an
 * inline style, so a `<m.div initial={{ opacity: 0 }}>` wrapping prose ships
 * `style="opacity:0"` in the static export and stays there for a reader with
 * JavaScript off — invisibly, because `innerText` ignores opacity and every
 * no-JS floor in scripts/check-pages.mjs would still pass.
 *
 * This component is safe to animate for one specific reason: it renders nothing
 * at all until an effect has read `localStorage`, so it has no prerendered
 * prose to hide. That is the test for anything else on this site that wants
 * `m.*` — if it is in the static HTML, its entrance belongs in globals.css
 * behind `@supports (animation-timeline: view())` instead.
 *
 * `strict` on LazyMotion is what enforces the bundle choice: it makes `motion.*`
 * throw and `m.*` the only way in, so nobody quietly pulls the full package in
 * for one fade.
 */

import {
  AnimatePresence,
  domAnimation,
  LazyMotion,
  m,
  MotionConfig,
} from "motion/react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { ComparisonTable } from "@/components/ComparisonTable";
import { Refusal } from "@/components/Refusal";
import {
  load,
  loadAgents,
  type AgentArtifact,
  type IndexArtifact,
  type Loaded,
} from "@/lib/artifacts";
import {
  COMPARE_KEY,
  readCompare,
  storeCompare,
  toggleCompare,
} from "@/lib/compare";

/**
 * Two agents, side by side, kept across pages.
 *
 * Mounted once in `app/layout.tsx` **after** `<main>`, for two reasons. It stays
 * out of the tab order ahead of the content, which is what the skip link exists
 * to fix; and it stays outside every per-page render, so
 * `headings.test.tsx`'s document-order heading walk never sees a tray heading
 * appearing between a page's `h1` and its cards.
 *
 * ## It refuses to compare an allocation agent with an LP one
 *
 * `app/view.tsx` already excludes Router from the Overview's chart, keyed on the
 * artifact's own `kind`, and says why on the page: *"They supply to a lending
 * market rather than providing liquidity, so there is no in-range fraction and
 * no adverse-selection cost to compare — and a zero in those columns would read
 * as a claim rather than an absence."*
 *
 * That argument does not weaken on a surface built for comparing; it gets
 * sharper. `ComparisonTable`'s rows include `in range` and `adverse selection`,
 * and `RouterArtifact` has neither field — so a mixed pair would render em
 * dashes under row labels asserting those metrics exist. The tray refuses the
 * pair and says which two things are not comparable.
 *
 * ## Nothing until mounted
 *
 * The selection lives in `localStorage`, which the server cannot see. Rendering
 * a guess would make the server's output disagree with the client's, so this
 * renders `null` until `mounted` — the same guard `ThemeToggle` uses, for the
 * same reason.
 */
export function CompareTray() {
  const [mounted, setMounted] = useState(false);
  const [slugs, setSlugs] = useState<string[]>([]);
  const [index, setIndex] = useState<IndexArtifact | undefined>();
  const [cards, setCards] = useState<
    { slug: string; result: Loaded<AgentArtifact> }[]
  >([]);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    setMounted(true);
    setSlugs(readCompare());
  }, []);

  // Another tab changed the selection. Cheap to support and confusing to omit:
  // two windows of the same site disagreeing about what is being compared is
  // the sort of thing a reader blames on the site rather than on the tab.
  useEffect(() => {
    const onStorage = (event: StorageEvent) => {
      if (event.key === COMPARE_KEY) setSlugs(readCompare());
    };
    const onLocal = () => setSlugs(readCompare());
    window.addEventListener("storage", onStorage);
    // `storage` fires only in *other* tabs. Without a same-tab event the tray
    // and the buttons on the page you are looking at drift apart.
    window.addEventListener("misquote:compare", onLocal);
    return () => {
      window.removeEventListener("storage", onStorage);
      window.removeEventListener("misquote:compare", onLocal);
    };
  }, []);

  useEffect(() => {
    if (!mounted || slugs.length === 0) return;
    let live = true;
    (async () => {
      const idx = index
        ? { ok: true as const, value: index }
        : await load<IndexArtifact>("index.json");
      if (!live || !idx.ok) return;
      setIndex(idx.value);

      const refs = idx.value.agents.filter((a) => slugs.includes(a.slug));
      const loaded = await loadAgents(refs);
      if (live) setCards(loaded);
    })();
    return () => {
      live = false;
    };
    // `index` is intentionally not a dependency: it is a cache, and including
    // it would refetch the cards the moment it is first set.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mounted, slugs.join(",")]);

  const remove = useCallback((slug: string) => {
    setSlugs((prev) => {
      const next = toggleCompare(prev, slug);
      storeCompare(next);
      window.dispatchEvent(new Event("misquote:compare"));
      return next;
    });
  }, []);

  // Not an early return any more. The tray unmounts the moment the last agent
  // is cleared, and an unmounted component cannot animate its own exit — so the
  // panel became a child of `AnimatePresence` and this became a flag. `mounted`
  // still gates the first paint: the selection lives in `localStorage`, and
  // rendering it before the effect reads it is a hydration mismatch.
  const showing = mounted && slugs.length > 0;

  const named = slugs.map((slug) => ({
    slug,
    name: index?.agents.find((a) => a.slug === slug)?.name ?? slug,
    data: cards.find((c) => c.slug === slug)?.result,
  }));

  const loaded = named
    .filter((n) => n.data?.ok)
    .map((n) => ({
      ...n,
      value: (n.data as { ok: true; value: AgentArtifact }).value,
    }));

  const kinds = new Set(
    loaded.map((n) => (n.value as unknown as { kind?: string }).kind ?? "lp")
  );
  const mixed = kinds.size > 1;
  const ready = loaded.length === 2 && !mixed;
  // Destructured rather than indexed: `loaded[0]` is `T | undefined` under
  // `noUncheckedIndexedAccess`, and asserting past that with `!` would be
  // claiming the length check above is a proof the compiler can see.
  const [left, right] = loaded;

  return (
    <LazyMotion features={domAnimation} strict>
      {/* The `@media (prefers-reduced-motion)` block in globals.css cannot
          reach an animation the library drives from JavaScript — it forces
          `animation-duration`, and there is no CSS animation here to force.
          `reducedMotion="user"` is the equivalent switch on this side of the
          boundary, and without it the one animation on the site that a reader
          cannot opt out of would be a bar sliding up over their content. */}
      <MotionConfig reducedMotion="user">
        <AnimatePresence>
          {showing && (
            <m.div
              key="tray"
              role="region"
              aria-label="Compare tray"
              // Transform only, so the bar composites instead of relaying out the
              // fixed strip on every frame. `--motion-enter` decelerates hard at
              // the end: the tray arrives and settles rather than sliding to a
              // stop.
              initial={{ y: "100%" }}
              animate={{ y: 0 }}
              exit={{ y: "100%" }}
              transition={{ duration: 0.42, ease: [0.16, 1, 0.3, 1] }}
              className="fixed inset-x-0 bottom-0 z-40 border-t border-glass-line bg-glass backdrop-blur"
            >
              <div className="mx-auto max-w-6xl px-5 py-3">
                <div className="flex flex-wrap items-center gap-3">
                  <span className="font-mono text-xs tracking-widest text-faint uppercase">
                    Comparing
                  </span>

                  <ul className="flex min-w-0 flex-wrap items-center gap-2">
                    {named.map((entry) => (
                      <li key={entry.slug}>
                        <span className="inline-flex items-center gap-1.5 rounded-full border border-brand-line bg-brand-bg px-2.5 py-1 text-sm text-brand">
                          {entry.name}
                          <button
                            type="button"
                            onClick={() => remove(entry.slug)}
                            aria-label={`Remove ${entry.name} from the comparison`}
                            className="rounded-full px-1 leading-none hover:text-ink"
                          >
                            ×
                          </button>
                        </span>
                      </li>
                    ))}
                  </ul>

                  {ready && (
                    <button
                      type="button"
                      onClick={() => setOpen((v) => !v)}
                      aria-expanded={open}
                      className="rounded-md border border-transparent bg-brand px-3 py-1.5 text-sm font-medium text-brand-ink transition-opacity hover:opacity-90"
                    >
                      {open ? "Hide" : "Compare"}
                    </button>
                  )}

                  {/* Named, because `Loadable` already owns an unnamed `role="status"`
                  on most pages and two anonymous voices is one too many. */}
                  <p
                    role="status"
                    aria-label="Comparison state"
                    className="m-0 text-xs text-faint"
                  >
                    {mixed
                      ? "not comparable"
                      : slugs.length < 2
                      ? "pick one more"
                      : loaded.length < 2
                      ? "loading"
                      : ""}
                  </p>
                </div>

                {mixed && (
                  <div className="mt-3 max-h-[40vh] overflow-y-auto">
                    <Refusal
                      title="These two are not comparable"
                      // The same correction `app/view.tsx` carries, in the component
                      // that says it to a reader who has just tried the comparison.
                      // "One of these supplies to a lending market" described the
                      // allocation agent by the venue it happened to hold; it
                      // chooses between venues, PancakeSwap ranges among them, and
                      // prices adverse selection for every range it considers. What
                      // makes the comparison impossible is narrower and permanent:
                      // it holds no range of its own, so the columns here measure a
                      // position it does not take.
                      reason="One of these holds a range and the other chooses which venue to put capital in. An allocation agent has no range of its own, so there is no in-range fraction to report and the rows below would be blank — and a blank under a row labelled 'in range' reads as a measurement that came out empty rather than one that does not exist."
                      floor="Compare two liquidity agents, or read the allocation card on its own."
                    />
                  </div>
                )}

                {open && ready && left && right && (
                  <div className="mt-3 max-h-[45vh] overflow-y-auto">
                    <ComparisonTable
                      caption={`${left.name} against ${right.name}`}
                      agentLabel={left.name}
                      baselineLabel={right.name}
                      agent={sideOf(left.value)}
                      baseline={sideOf(right.value)}
                      unit={left.value.quote_symbol}
                    />
                    <p className="mt-2 mb-0 text-xs text-faint">
                      Both replayed over the same tape.{" "}
                      <Link href="/methods">How a quote is made →</Link>
                    </p>
                  </div>
                )}
              </div>
            </m.div>
          )}
        </AnimatePresence>
      </MotionConfig>
    </LazyMotion>
  );
}

/**
 * An agent card's replay, in the shape `ComparisonTable` reads.
 *
 * The field names differ between artifacts — `warden.json` spells them
 * `in_range_fraction` and `lvr_quote_upper_bound`, `advantage.json` spells the
 * same quantities `in_range` and `lvr_upper_bound` — which is why each caller
 * adapts its own shape rather than the component guessing.
 */
function sideOf(data: AgentArtifact) {
  const r = data.replay;
  const q = data.quote_detail;
  return {
    p25: q?.p25,
    p50: q?.p50,
    p75: q?.p75,
    inRange: r?.in_range_fraction,
    fees: r?.fees_quote,
    lvrUpperBound: r?.lvr_quote_upper_bound,
    costs: r?.costs_quote,
    moves: r ? r.mints + r.rebalances + r.pulls : undefined,
  };
}
