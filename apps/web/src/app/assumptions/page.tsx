import type { Metadata } from "next";
import { AssumptionsView, type AssumptionsArtifact } from "./view";
import type { IndexArtifact } from "@/lib/artifacts";
import { readArtifact } from "@/lib/build-artifact";

// A server component, so the title reaches the prerendered HTML. Every route
// was a client component, none could export metadata, and all seven pages
// therefore shipped the same <title> — which also made `title.template` in the
// layout dead code and left RouteAnnouncer announcing the wrong page name.
export const metadata: Metadata = {
  title: "The assumption sheet",
  description: "Every number on this site traces to a chain query or to an entry here. If it cannot, it does not render.",
};

export default function Page() {
  return <AssumptionsView initialSheet={readArtifact<AssumptionsArtifact>("assumptions.json")} initialIndex={readArtifact<IndexArtifact>("index.json")} />;
}
