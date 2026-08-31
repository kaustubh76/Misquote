import { OverviewView } from "./view";
import { readArtifact } from "@/lib/build-artifact";
import { entryOf, type EvidenceEntry } from "@/components/EvidenceRail";
import type { AgentArtifact, IndexArtifact } from "@/lib/artifacts";

/**
 * A server component, so the landing page exists in the exported HTML.
 *
 * `next.config.ts` gives as the reason for `output: "export"` that the page this
 * replaced "rendered identically when every server behind it was down". That
 * property did not survive the rewrite: every view is `"use client"` and fetches
 * after mount, so the built `index.html` was a heading, one paragraph, a link
 * and a footer. The nav offered eight routes and every one of them was a title
 * over a spinner.
 *
 * This route matters more than the others because it is the only way to reach
 * `/agent/[slug]`. That page is not in `lib/routes.ts` and so is not in the nav;
 * its only links are the agent cards below, which are client-rendered. Server-
 * rendering the agent detail and not this page would have prerendered something
 * unreachable — a fix visible to nobody it was for.
 *
 * The body stays a client component: it holds `useState`, `useEffect` and the
 * agent fan-out, and splitting the file is what lets the shell be a server
 * component at all — the same split `advantage`, `methods`, `registry`,
 * `status`, `vectors`, `venue` and `vetting` already have for `metadata`.
 */

/**
 * The evidence figures, read once at build time.
 *
 * Numbers, not artifacts. `OverviewView` is a client component, so everything
 * passed to it is serialised into the flight payload of every build — and
 * `assumptions.json` alone is 130KB. Reading each file here and handing over a
 * formatted count keeps that payload to a handful of short strings while still
 * putting the figures in the exported HTML, which is the point: a reader with
 * JavaScript off gets the map of the argument, not a row of empty cards.
 *
 * Not every evidence route has a figure, and the ones that do not are absent
 * from this map rather than present-and-null. `/tape` is the case: its subject
 * is a live database, it has no artifact, and `EvidenceRail` reads the
 * difference. A key here means "this route leads with a number"; no key means
 * "it does not"; a key whose value is null means "it should have and the file
 * would not read".
 *
 * Each figure is the one its own page leads with, and none of them is computed
 * twice — `summary` blocks are written by the emitters that write the pages.
 * A file that will not parse yields `null` and renders as a route with no
 * number, because a missing artifact is not a count of zero.
 */
function evidence(): Record<string, EvidenceEntry | null> {
  const advantage = readArtifact<{ summary?: { tasks?: number } }>("advantage.json");
  const assumptions = readArtifact<{ entries?: unknown[] }>("assumptions.json");
  const vectors = readArtifact<{ corpus?: { cases?: number } }>("vectors.json");
  const venue = readArtifact<{ divergences?: unknown[] }>("venue.json");
  const vetting = readArtifact<{ summary?: { checks?: number } }>("vetting.json");
  const status = readArtifact<{ summary?: { pass?: number; total?: number } }>("status.json");
  const warden = readArtifact<{ floors?: Record<string, unknown> }>("warden.json");

  return {
    "/advantage": entryOf(advantage?.summary?.tasks, "tasks, each done both ways"),
    "/methods": entryOf(
      warden?.floors ? Object.keys(warden.floors).length : undefined,
      "floors that stop a number printing",
    ),
    "/assumptions": entryOf(assumptions?.entries?.length, "assumptions, each citable"),
    "/vectors": entryOf(vectors?.corpus?.cases, "cases against the real Solidity"),
    "/venue": entryOf(venue?.divergences?.length, "places this is not Uniswap"),
    "/vetting": entryOf(vetting?.summary?.checks, "checks read from chain"),
    "/status": entryOf(
      status?.summary?.total,
      status?.summary?.pass === undefined
        ? "readiness gates"
        : `readiness gates, ${status.summary.pass} passing`,
    ),
  };
}

/**
 * The agent cards, read at build time so they are in the exported HTML.
 *
 * `view.tsx` used to argue against this: "baking three more artifacts into
 * every build to save one round trip is a worse trade than the round trip."
 * That was true while the ledger sat below the cards, because the page had
 * 1,100 words of prerendered substance either way and the cards arriving a beat
 * later cost nothing a reader would notice.
 *
 * Removing the ledger flipped it. Without these, `/` renders the words
 * "Loading agent cards." and nothing else about the product — a marketplace
 * whose static HTML contains no agents. The round trip is no longer buying a
 * smaller build, it is buying an empty landing page, and `check-pages.mjs`
 * measures exactly that with its no-JS floor.
 *
 * Still not `assumptions.json`-shaped: the four agent artifacts are a few KB
 * each against that file's 130KB, which is the size the original note was
 * guarding against and the reason `evidence()` above passes counts rather than
 * documents.
 */
function agentCards(index: IndexArtifact | undefined) {
  if (!index) return undefined;
  return index.agents.map((a) => ({
    slug: a.slug,
    name: a.name,
    artifact: readArtifact<AgentArtifact>(`${a.slug}.json`),
  }));
}

export default function OverviewPage() {
  const index = readArtifact<IndexArtifact>("index.json");
  return (
    <OverviewView
      initialIndex={index}
      initialAgents={agentCards(index)}
      evidence={evidence()}
    />
  );
}
