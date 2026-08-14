import { readFileSync } from "node:fs";
import { join } from "node:path";
import { AgentDetail } from "@/components/AgentDetail";

/**
 * Slugs come from the generated index at build time.
 *
 * `output: "export"` has to know every dynamic route ahead of time, and the
 * authoritative list of agents is the one the Python emitter wrote — not a
 * literal here that could disagree with it. Read at build time only; the page
 * itself still fetches its artifact at runtime, so editing a JSON and reloading
 * still works.
 */
export function generateStaticParams() {
  const path = join(process.cwd(), "public", "artifacts", "index.json");
  try {
    const index = JSON.parse(readFileSync(path, "utf8")) as {
      agents?: { slug?: string }[];
    };
    const slugs = (index.agents ?? [])
      .map((a) => a.slug)
      .filter((s): s is string => typeof s === "string" && s.length > 0);
    if (slugs.length > 0) return slugs.map((slug) => ({ slug }));
  } catch {
    /* fall through */
  }
  // Never return an empty list: that would export zero agent pages and the
  // failure would look like a routing bug rather than a missing artifact.
  return [{ slug: "warden" }, { slug: "grid" }, { slug: "sentinel" }];
}

export default async function AgentPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  return <AgentDetail slug={slug} />;
}
