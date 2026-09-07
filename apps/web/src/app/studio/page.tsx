import type { Metadata } from "next";
import { StudioView, type StudioArtifact } from "./view";
import { readArtifact } from "@/lib/build-artifact";

// A server component, so the title and the whole standing record reach the
// prerendered HTML. Only the negotiate button needs JavaScript, and its absence
// leaves a recorded envelope on the page rather than a gap — the same shape
// `/activate` uses for its capability read.
export const metadata: Metadata = {
  title: "Native on the BNB Agent Studio",
  description:
    "A seller agent scaffolded by the Agent Studio CLI, deployed, carrying an ERC-8004 identity the CLI minted, and signing ERC-8183 quotes you can check without our help.",
};

export default function Page() {
  return <StudioView initial={readArtifact<StudioArtifact>("studio.json")} />;
}
