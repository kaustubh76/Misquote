"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Card, CardHeader } from "@/components/Card";
import { CategoryGlyph } from "@/components/CategoryGlyph";
import { Heading, Section } from "@/components/Heading";
import { Loadable } from "@/components/LoadingStatus";
import { Pill } from "@/components/Pill";
import { ErrorNotice } from "@/components/Refusal";
import { load, type IndexArtifact, type Loaded } from "@/lib/artifacts";
import { categoriesFrom } from "@/lib/categories";

/**
 * The four categories, side by side.
 *
 * This is a browse surface and it is deliberately not four cards linking to
 * four agent pages — that would be the Overview with different headings. What
 * it carries that no other page does is the *shape* of the marketplace: which
 * categories exist, that each holds exactly one agent today, and the reason no
 * third-party agent appears in any of them.
 *
 * That last part is the interesting content rather than a gap. The ~280,000
 * ERC-8004 agents this site indexes declare no category anywhere — not in the
 * survey, not on the card, not in `assess()` — so placing them in these four
 * buckets would mean classifying strangers' free text as though they had asked
 * us to. `scripts/registry_report.py::LISTING_KEYS` is a whitelist and
 * `tests/web/test_third_party_listings.py` asserts nothing outside it is
 * published, so that absence is guarded rather than accidental.
 */
export function CategoryIndexView({ initial }: { initial?: IndexArtifact }) {
  const [state, setState] = useState<Loaded<IndexArtifact> | null>(
    initial ? { ok: true, value: initial } : null,
  );

  useEffect(() => {
    let live = true;
    load<IndexArtifact>("index.json").then((next) => {
      if (live) setState(next);
    });
    return () => {
      live = false;
    };
  }, []);

  const index = state?.ok ? state.value : undefined;
  const categories = categoriesFrom(index?.agents);

  return (
    <Loadable loading={state === null} what="the categories" className="max-w-5xl">
      {/* The count is counted. It read "Four categories" beside a list built
          from `categoriesFrom(index?.agents)` — so the heading asserted the
          length of the thing rendered under it, and `lib/categories.ts` argues
          at length that this taxonomy is derived precisely so a fifth does not
          have to be found by hand in four places. */}
      <h1 className="text-3xl leading-[1.15] font-semibold text-balance">
        {categories.length > 0 ? `${categories.length} categories` : "Categories"}, and what each
        one is judged on
      </h1>
      <p className="mt-4 max-w-[62ch] text-md text-dim">
        A category here is a job you might hire for, and the claim attached to it
        is always the same shape: this policy, replayed over recorded history,
        against <strong className="text-ink">doing it yourself</strong>.
      </p>

      {state && !state.ok && (
        <ErrorNotice
          title="No index to read"
          detail={state.error.message}
          remedy={
            <>
              Nothing has generated the agent index yet. Run{" "}
              <code className="font-mono text-xs">make showcase-demo</code>.
            </>
          }
        />
      )}

      {categories.length > 0 && (
        <div className="mt-8 grid gap-5 sm:grid-cols-2">
          {categories.map((category) => (
            <Card key={category.slug} as="article">
              <CardHeader
                title={
                  <Link href={`/category/${category.slug}`} className="text-ink no-underline hover:underline">
                    {category.name}
                  </Link>
                }
                eyebrow={
                  <span className="flex items-center gap-2">
                    <CategoryGlyph slug={category.slug} />
                    <span>
                      {category.agents.length === 1
                        ? "one agent"
                        : `${category.agents.length} agents`}
                    </span>
                  </span>
                }
              />
              <ul className="m-0 list-none space-y-2 p-0">
                {category.agents.map((agent) => (
                  <li key={agent.slug} className="flex flex-wrap items-center gap-2">
                    <Link href={`/agent/${agent.slug}`} className="text-sm">
                      {agent.name}
                    </Link>
                    <Pill tone={agent.built ? "pass" : "none"}>
                      {agent.built ? "Built" : "Not built"}
                    </Pill>
                  </li>
                ))}
              </ul>
              <p className="mt-4 mb-0 text-sm">
                <Link href={`/category/${category.slug}`}>
                  What this category measures →
                </Link>
              </p>
            </Card>
          ))}
        </div>
      )}

      <Section
        title="Why no third-party agents appear here"
        className="mt-12"
        headingClassName="text-lg font-semibold"
      >
        <p className="mt-2 mb-0 max-w-[62ch] text-dim">
          ERC-8004 declares no category, so sorting{" "}
          <Link href="/registry">the agents we index</Link> into these is{" "}
          <strong className="text-ink">our</strong> reading of their words.
        </p>
        <p className="mt-3 mb-0 max-w-[62ch] text-dim">
          Shown as ours: every row names the term it matched on, and none carries
          a quote, because we do not have their policies.
        </p>
      </Section>

      {/* Counted, and gated on there being something to count.
          It asserted "One agent per category" in a heading and "exactly one
          agent today" in the body — while `lib/categories.ts:56-59` argues the
          opposite for the same data: "`agents` is a list even though every
          category currently holds exactly one — because 'one agent per
          category' is a fact about today's index, not a rule, and a page that
          assumed it would break silently when a second arrives."

          It also sat outside the `categories.length > 0` guard, so a build
          whose index failed to load rendered a claim about how many agents each
          category holds directly under a page showing no categories at all. */}
      {categories.length > 0 &&
        (() => {
          const most = Math.max(...categories.map((c) => c.agents.length));
          return (
            <>
              <Heading className="mt-10 mb-2 text-md font-semibold">
                {most === 1
                  ? "One agent per category is a fact, not a design"
                  : "How many agents a category holds is a fact, not a design"}
              </Heading>
              <p className="m-0 max-w-[62ch] text-sm text-dim">
                {most === 1
                  ? "Each of these holds exactly one agent today because exactly one was built for it."
                  : `The fullest of these holds ${most} today, because that is how many were built for it.`}{" "}
                The pages below are shaped for more, and a second arrival would
                appear beside the first rather than replacing it.
              </p>
            </>
          );
        })()}
    </Loadable>
  );
}
