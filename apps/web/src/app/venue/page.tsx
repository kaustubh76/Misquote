import type { Metadata } from "next";
import { VenueView } from "./view";

export const metadata: Metadata = {
  title: "Where PancakeSwap is not Uniswap",
  description:
    "The cores are the same source. Every divergence below cost something before it was a paragraph.",
};

export default function VenuePage() {
  return <VenueView />;
}
