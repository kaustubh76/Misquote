import type { Metadata } from "next";
import { SimulateView } from "./view";
import type { SimulationArtifact } from "@/components/PoolSimulator";
import { readArtifact } from "@/lib/build-artifact";

export const metadata: Metadata = {
  title: "Simulate a PancakeSwap position",
  description:
    "Pick a pool, a range width and an amount, and see what that position would have earned on swaps that already happened.",
};

export default function SimulatePage() {
  // Seeded from disk, so the first paint carries figures rather than a spinner.
  // `next.config.ts` records why that matters and how few routes hold it: every
  // view here is `"use client"` and fetches after mount, so a route that does
  // not read the artifact at build time has no numbers in the exported HTML.
  return <SimulateView initial={readArtifact<SimulationArtifact>("simulation.json")} />;
}
