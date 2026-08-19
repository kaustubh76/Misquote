import type { Metadata } from "next";
import { VenueView, type VenueArtifact } from "./view";
import { readArtifact } from "@/lib/build-artifact";

export const metadata: Metadata = {
  title: "Where PancakeSwap is not Uniswap",
  description:
    "The cores are the same source. Every divergence below cost something before it was a paragraph.",
};

export default function VenuePage() {
  return <VenueView initial={readArtifact<VenueArtifact>("venue.json")} />;
}
