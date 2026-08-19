import { OverviewView } from "./view";
import { readArtifact } from "@/lib/build-artifact";
import type { BuildArtifact, IndexArtifact } from "@/lib/artifacts";

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

export default function OverviewPage() {
  return (
    <OverviewView
      initialIndex={readArtifact<IndexArtifact>("index.json")}
      initialBuild={readArtifact<BuildArtifact>("build.json")}
    />
  );
}
