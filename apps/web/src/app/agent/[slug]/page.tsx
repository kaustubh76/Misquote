import type { Metadata } from "next";
import { readArtifact } from "@/lib/build-artifact";
import { AgentDetail } from "@/components/AgentDetail";
import type { AdvantageArtifact, AgentArtifact } from "@/lib/artifacts";


/**
 * Slugs come from the generated index at build time.
 *
 * `output: "export"` has to know every dynamic route ahead of time, and the
 * authoritative list of agents is the one the Python emitter wrote — not a
 * literal here that could disagree with it. Read at build time only; the page
 * itself still fetches its artifact at runtime, so editing a JSON and reloading
 * still works.
 */
type IndexedAgent = { slug?: string; name?: string; category?: string };

/** One artifact, read at build time. Absent is a state, not a build failure. */

/** The generated index, read once at build time. */
function readAgents(): IndexedAgent[] {
  return readArtifact<{ agents?: IndexedAgent[] }>("index.json")?.agents ?? [];
}

/**
 * The tab says the agent's name, not the slug.
 *
 * This route is the one page that was already a server component, so it could
 * always have done this; it just never did, and shipped the site-wide title
 * like everything else.
 */
export async function generateMetadata({
  params,
}: {
  params: Promise<{ slug: string }>;
}): Promise<Metadata> {
  const { slug } = await params;
  const agent = readAgents().find((a) => a.slug === slug);
  const name = agent?.name ?? slug;
  return {
    title: name,
    description: agent?.category
      ? `${name} — ${agent.category}. What the policy would have earned, replayed over recorded pool history, with every assumption behind it.`
      : `${name}: a replay of the policy over recorded pool history.`,
  };
}

export function generateStaticParams() {
  const slugs = readAgents()
    .map((a) => a.slug)
    .filter((s): s is string => typeof s === "string" && s.length > 0);
  if (slugs.length > 0) return slugs.map((slug) => ({ slug }));

  // Never return an empty list: that would export zero agent pages and the
  // failure would look like a routing bug rather than a missing artifact.
  return [{ slug: "warden" }, { slug: "grid" }, { slug: "sentinel" }];
}

export default async function AgentPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  // The artifact, into the exported HTML. This route already read this
  // directory twice per page — for the slug list and for the tab title — and
  // threw the contents away, so the page that renders the most numbers on the
  // site exported none of them.
  //
  // The report comes with it. `advantage.json` answers the same question as
  // this card from a different run, and the two have disagreed by as much as a
  // sign; the card names the other answer now, and it has to do so in the
  // static HTML rather than only after a fetch, because the no-JS export is
  // where a disclosure is least likely to be noticed missing.
  return (
    <AgentDetail
      slug={slug}
      initial={readArtifact<AgentArtifact>(`${slug}.json`)}
      initialAdvantage={readArtifact<AdvantageArtifact>("advantage.json")}
    />
  );
}
