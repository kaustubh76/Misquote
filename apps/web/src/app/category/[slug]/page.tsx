import type { Metadata } from "next";
import { CategoryView } from "./view";
import type { ScanArtifact } from "./view";
import type { AdvantageArtifact, AgentArtifact, IndexArtifact } from "@/lib/artifacts";
import { readArtifact } from "@/lib/build-artifact";
import { categoriesFrom, categoryBySlug } from "@/lib/categories";

/**
 * The four slugs come from the index, at build time.
 *
 * `output: "export"` ships exactly what this returns and nothing else, so a
 * category the emitter publishes and this misses is a page that 404s on the
 * built site while working in `next dev`. Derived from `index.json` for the
 * same reason `app/agent/[slug]/page.tsx` derives its own: a literal list here
 * is a second copy of a taxonomy that already exists, and the day one is
 * renamed the site would link to one and route to the other.
 */
function readIndex(): IndexArtifact | undefined {
  return readArtifact<IndexArtifact>("index.json");
}

export function generateStaticParams(): { slug: string }[] {
  return categoriesFrom(readIndex()?.agents).map((c) => ({ slug: c.slug }));
}

/**
 * A distinct title per category.
 *
 * `check-pages.mjs` fails when two routes share a `<title>`, and four pages
 * from one component is exactly the shape that produces four identical ones.
 */
export async function generateMetadata({
  params,
}: {
  params: Promise<{ slug: string }>;
}): Promise<Metadata> {
  const { slug } = await params;
  const category = categoryBySlug(slug, readIndex()?.agents);
  const name = category?.name ?? slug;

  return {
    title: `${name}: what it is judged on`,
    description: `${name} — the do-it-yourself baseline this category is measured against, the agent serving it, and what the comparison does and does not establish.`,
  };
}

export default async function Page({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const index = readIndex();

  /**
   * The cards themselves, read at build time.
   *
   * Without this the page prerenders its frame and nothing else — the agent
   * card arrives only after `loadAgents` runs in the browser, so a reader with
   * JavaScript off gets a heading, a source banner and a paragraph about the
   * registry. That is a page about a category that never says what the agent
   * did.
   *
   * The Overview makes the opposite trade deliberately, and says why: it fans
   * out over the whole index at runtime rather than baking four artifacts into
   * every build. Here there is exactly one artifact per page, so the trade goes
   * the other way. The client still fetches afterwards, so editing a JSON and
   * reloading still works.
   */
  const initialCards = Object.fromEntries(
    (categoryBySlug(slug, index?.agents)?.agents ?? []).flatMap((agent) => {
      const data = readArtifact<AgentArtifact>(`${agent.slug}.json`);
      return data ? [[agent.slug, data] as const] : [];
    }),
  );

  return (
    <CategoryView
      slug={slug}
      initialIndex={index}
      initialAdvantage={readArtifact<AdvantageArtifact>("advantage.json")}
      initialCards={initialCards}
      // `registry.json`'s third-party block, read here rather than fetched, so
      // the agents 8004scan holds for this category are in the prerendered
      // HTML. Optional chaining rather than a guard: a build with no scan
      // reading renders the rest of the page and the component refuses on its
      // own terms.
      initialScan={readArtifact<{ third_party?: ScanArtifact }>("registry.json")?.third_party}
    />
  );
}
