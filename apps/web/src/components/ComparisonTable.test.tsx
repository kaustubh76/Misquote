import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { COMPARISON_ROWS, ComparisonTable, type Side } from "./ComparisonTable";

const agent: Side = {
  p25: 36.88,
  p50: 37.74,
  p75: 38.72,
  inRange: 0.94,
  fees: 865.43,
  lvrUpperBound: 402.11,
  costs: 118.2,
  moves: 56,
};

const baseline: Side = {
  p25: 5.63,
  p50: 9.99,
  p75: 26.05,
  inRange: 0.61,
  fees: 512.08,
  lvrUpperBound: 388.7,
  costs: 41.5,
  moves: 3,
};

function rowHeaders(): string[] {
  const region = screen.getByRole("region", { name: /agent against baseline/i });
  return within(region)
    .getAllByRole("rowheader")
    .map((th) => th.textContent ?? "");
}

describe("the comparison shows the same rows on every page that shows a comparison", () => {
  it("renders every row, in order", () => {
    render(
      <ComparisonTable
        caption="Agent against baseline"
        agentLabel="Warden"
        baselineLabel="Doing it yourself"
        agent={agent}
        baseline={baseline}
      />,
    );

    expect(rowHeaders()).toEqual([...COMPARISON_ROWS]);
  });

  it("keeps the cost row", () => {
    // The specific regression. `/advantage` had this row and `/agent/[slug]`
    // did not, so the agent page compared fees, costs and return — the three
    // that flatter the agent — while the number that does not was thirty lines
    // below in a different table. Named on its own so a failure says which row
    // went missing rather than printing two seven-item arrays to diff by eye.
    render(
      <ComparisonTable
        caption="Agent against baseline"
        agentLabel="Warden"
        baselineLabel="Doing it yourself"
        agent={agent}
        baseline={baseline}
      />,
    );

    expect(rowHeaders()).toContain("adverse selection (upper bound)");
  });

  it("labels which column is the agent and which is the baseline", () => {
    // Three columns of bare numbers, with the headers visually hidden, is how
    // the second figure ends up unattributed — a reader sees "37.74% 9.99%"
    // and has to guess. `DataTable` shows the header row for three columns.
    render(
      <ComparisonTable
        caption="Agent against baseline"
        agentLabel="Warden"
        baselineLabel="Hold and never move"
        agent={agent}
        baseline={baseline}
      />,
    );

    const region = screen.getByRole("region", { name: /agent against baseline/i });
    expect(within(region).getByRole("columnheader", { name: "Warden" })).toBeInTheDocument();
    expect(
      within(region).getByRole("columnheader", { name: "Hold and never move" }),
    ).toBeInTheDocument();
  });
});

describe("a withheld quote", () => {
  it("renders missing percentiles as an em dash, never as zero", () => {
    // A withheld quote has no p25/p50/p75 at all. Rendering `0.00%` there would
    // state that the agent measured a flat return, which is a different claim
    // from "we declined to say" — and it is the claim that reads as a loss.
    render(
      <ComparisonTable
        caption="Agent against baseline"
        agentLabel="Warden"
        baselineLabel="Doing it yourself"
        agent={{ ...agent, p25: undefined, p50: undefined, p75: undefined }}
        baseline={baseline}
      />,
    );

    const region = screen.getByRole("region", { name: /agent against baseline/i });
    const median = within(region)
      .getByRole("rowheader", { name: "median return" })
      .closest("tr")!;

    expect(within(median).getAllByRole("cell")[0]).toHaveTextContent("—");
    expect(within(median).getAllByRole("cell")[0]).not.toHaveTextContent("0.00");
    // The baseline half is unaffected: one side withholding does not blank the
    // other, or the table would say less than it knows.
    expect(within(median).getAllByRole("cell")[1]).toHaveTextContent("9.99");
  });
});

describe("the unit the money rows are in", () => {
  const rowHeadersWith = (unit?: string) => {
    render(
      <ComparisonTable
        caption="Agent against baseline"
        agentLabel="Warden"
        baselineLabel="Doing it yourself"
        agent={agent}
        baseline={baseline}
        unit={unit}
      />,
    );
    return [...screen.getAllByRole("rowheader")].map((el) => el.textContent);
  };

  it("puts it on the label, not in six cells", () => {
    // `fees`, `adverse selection` and `costs` are amounts; the label is where a
    // reader looks to find out what a column of numbers means, and repeating
    // `WBNB` in every cell of a two-column table reads worse than stating it.
    expect(rowHeadersWith("WBNB")).toEqual([
      "median return",
      "P25 – P75",
      "in range",
      "fees (WBNB)",
      "adverse selection (upper bound) (WBNB)",
      "costs (WBNB)",
      "moves",
    ]);
  });

  it("leaves the rows that are not money alone", () => {
    // A percentage in WBNB is a unit error printed as a label. `median return`
    // and `in range` are percentages and `moves` is a count.
    const headers = rowHeadersWith("WBNB");
    for (const row of ["median return", "P25 – P75", "in range", "moves"]) {
      expect(headers).toContain(row);
    }
  });

  it("says nothing when the artifact does not say", () => {
    expect(rowHeadersWith()).toEqual([...COMPARISON_ROWS]);
  });
});
