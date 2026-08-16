import type { Metadata } from "next";
import { VectorsView } from "./view";

export const metadata: Metadata = {
  title: "The tick math, against the real Solidity",
  description:
    "Every vector recorded from Uniswap's own libraries, and whether this Python still reproduces them.",
};

export default function VectorsPage() {
  return <VectorsView />;
}
