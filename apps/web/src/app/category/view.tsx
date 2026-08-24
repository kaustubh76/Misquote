"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Card, CardHeader } from "@/components/Card";
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
      <h1 className="text-3xl leading-[1.15] font-semibold text-balance">
        Four categories, and what each one is judged on
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
                eyebrow={category.agents.length === 1 ? "one agent" : `${category.agents.length} agents`}
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
          This site indexes the ERC-8004 registry and lists what it finds on{" "}
          <Link href="/registry">the registry page</Link>. None of those agents
          declares a category — not on its card, not in the survey, nowhere in
          the standard. Sorting them into these four would mean reading strangers&rsquo;
          free-text descriptions and deciding on their behalf what they are for,
          and the result would be <strong className="text-ink">our</strong>{" "}
          classification presented as theirs.
        </p>
        <p className="mt-3 mb-0 max-w-[62ch] text-dim">
          So they are listed where the evidence supports listing them, with what
          each one actually says about itself, and they are absent from here.
        </p>
      </Section>

      <Heading className="mt-10 mb-2 text-md font-semibold">
        One agent per category is a fact, not a design
      </Heading>
      <p className="m-0 max-w-[62ch] text-sm text-dim">
        Each of these holds exactly one agent today because exactly one was
        built for it. The pages below are shaped for more, and a second arrival
        would appear beside the first rather than replacing it.
      </p>
    </Loadable>
  );
}
