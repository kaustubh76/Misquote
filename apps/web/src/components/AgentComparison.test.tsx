import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AgentComparison, type ComparedAgent } from "./AgentComparison";
import type { AgentArtifact, AgentRef } from "@/lib/artifacts";

/**
 * Hand-built rather than read from disk, because the case that matters here —
 * two agents reporting in different units — is one no single run can produce.
 * The pool is a constant somebody can change, and `EQUITY_POOL` quotes in
 * tokenized Tesla shares.
 */
function compared(
  name: string,
  net: number,
  quote_symbol?: string,
): ComparedAgent {
  const ref = { name, slug: name.toLowerCase(), category: "Rebalancing", built: true } as AgentRef;
  const data = {
    agent: name,
    quote_symbol,
    replay: {
      net_quote: net,
      mints: 1,
      rebalances: 12,
      pulls: 1,
      in_range_fraction: 0.5,
    },
  } as unknown as AgentArtifact;
  return { ref, data };
}

const panel = () => screen.getByText(/one scale|different units/).closest("div")!;

describe("the unit on a shared scale", () => {
  it("writes it beside every net when the agents agree", () => {
    render(
      <AgentComparison
        agents={[compared("Warden", -186.74, "WBNB"), compared("Grid", -0.68, "WBNB")]}
      />,
    );

    expect(within(panel()).getByText(/-186\.74\s*WBNB/)).toBeInTheDocument();
    expect(within(panel()).getByText(/-0\.68\s*WBNB/)).toBeInTheDocument();
  });

  it("refuses to claim one scale when the agents disagree", () => {
    // Drawing WBNB and TSLAx on one axis is a category error rendered as a
    // ranking: the longer bar would read as the worse agent when the two
    // numbers cannot be subtracted, let alone compared.
    render(
      <AgentComparison
        agents={[compared("Warden", -186.74, "WBNB"), compared("Equity", -0.68, "TSLAx")]}
      />,
    );

    expect(screen.getByText(/different units, so the bars rank nothing/)).toBeInTheDocument();
    expect(screen.queryByText(/longest bar is the largest/)).toBeNull();

    // And no unit is asserted on the figures, since there is no shared one.
    expect(within(panel()).queryByText(/WBNB|TSLAx/)).toBeNull();
  });

  it("renders bare, on one scale, when no artifact says", () => {
    // The units do not disagree — nothing was recorded. That still permits the
    // comparison, because these came from one run; it does not permit a guess.
    render(<AgentComparison agents={[compared("Warden", -186.74), compared("Grid", -0.68)]} />);

    expect(screen.getByText(/longest bar is the largest/)).toBeInTheDocument();
    expect(within(panel()).getByText("-186.74")).toBeInTheDocument();
  });
});

describe("the caption does not assert a direction the data does not have", () => {
  it("says loss when every agent lost", () => {
    render(
      <AgentComparison
        agents={[compared("Warden", -186.74, "WBNB"), compared("Grid", -0.68, "WBNB")]}
      />,
    );
    expect(screen.getByText(/longest bar is the largest loss/)).toBeInTheDocument();
  });

  it("says gain when every agent gained", () => {
    // "Net loss" was written into the caption, and it read correctly for as
    // long as the 30-day chain tape — where all three lose — was the only one
    // anyone looked at. A synthetic run where all three profit captioned three
    // green bars "the largest loss".
    render(
      <AgentComparison
        agents={[compared("Warden", 300.2, "WBNB"), compared("Grid", 148.34, "WBNB")]}
      />,
    );
    expect(screen.getByText(/longest bar is the largest gain/)).toBeInTheDocument();
    expect(screen.queryByText(/loss/)).toBeNull();
  });

  it("claims neither when the agents disagree in sign", () => {
    // The longest bar is then the largest magnitude, which is neither.
    render(
      <AgentComparison
        agents={[compared("Warden", -186.74, "WBNB"), compared("Grid", 148.34, "WBNB")]}
      />,
    );
    expect(screen.getByText(/longest bar is the largest amount/)).toBeInTheDocument();
  });
});
