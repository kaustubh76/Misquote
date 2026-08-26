import type { Metadata } from "next";
import { VenueView, type BadgeSurvey, type PoolsArtifact, type VenueArtifact } from "./view";
import { readArtifact } from "@/lib/build-artifact";

export const metadata: Metadata = {
  title: "Where PancakeSwap is not Uniswap",
  description:
    "The cores are the same source. Every divergence below cost something before it was a paragraph.",
};

export default function VenuePage() {
  // The badge survey comes with it. This page lists every pool the repository
  // has verified, `/vetting` checks the ones on mainnet, and the link between
  // them claimed all of them had passed.
  return (
    <VenueView
      initial={readArtifact<VenueArtifact>("venue.json")}
      initialBadges={readArtifact<BadgeSurvey>("vetting.json")}
      // Absent on a clean checkout: `make artifacts` does not build the ladder.
      initialPools={readArtifact<PoolsArtifact>("pools.json")}
    />
  );
}
