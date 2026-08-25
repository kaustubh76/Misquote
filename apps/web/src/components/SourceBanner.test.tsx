import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { SourceBanner } from "@/components/SourceBanner";

describe("SourceBanner", () => {
  it("names the pool when there is one", () => {
    render(<SourceBanner source="chain" pool="WBNB/USDT 0.05%" />);
    expect(screen.getByText(/Replayed over indexed history for/)).toBeInTheDocument();
    expect(screen.getByText("WBNB/USDT 0.05%")).toBeInTheDocument();
  });

  it("does not dangle a preposition when there is no single pool to name", () => {
    // `/advantage` is the caller: four tasks across two PancakeSwap pools and a
    // Venus lending market, so there is no one pool, and it rendered
    // "…indexed history for . No position was held."
    render(<SourceBanner source="chain" />);
    expect(screen.getByText(/Replayed over indexed history\. No position was held\./)).toBeInTheDocument();
    expect(screen.queryByText(/history for\s*\./)).not.toBeInTheDocument();
  });

  it("says a synthetic tape is synthetic before anything else", () => {
    render(<SourceBanner source="synthetic" />);
    expect(screen.getByText(/Synthetic tape — not chain data/)).toBeInTheDocument();
    expect(screen.queryByText(/indexed history/)).not.toBeInTheDocument();
  });
});
