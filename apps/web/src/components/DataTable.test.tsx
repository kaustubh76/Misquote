import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { DataTable } from "./DataTable";

/**
 * The note column is asserted by its class, which needs defending.
 *
 * jsdom performs no layout: every element reports zero width, so "this text is
 * cut off at 1280px" is not observable here and never will be. What *is*
 * observable is the single declaration that causes it — `white-space: nowrap`
 * on a cell holding a sentence — and that is what these check. The rendered
 * result is verified where it can be: by `make web-check`, which loads the
 * built page in a real browser, and by looking at the screenshot it writes.
 */
const rows = [
  { label: "approve", value: "client", note: "the escrow pulls the budget on fund(); without this it reverts" },
  { label: "fund", value: "client", note: "Open -> Funded; the money is now escrowed" },
];

const noteCell = (name: RegExp | string) => {
  const region = screen.getByRole("region", { name });
  const row = within(region).getAllByRole("row")[1]!;
  return within(row).getAllByRole("cell")[1]!;
};

describe("a third column of prose is not a third column of figures", () => {
  it("lets prose wrap", () => {
    render(
      <DataTable
        caption="The ERC-8183 job lifecycle"
        columns={["Call", "Signed by", "Why"]}
        notes="prose"
        rows={rows}
      />,
    );
    const cell = noteCell(/job lifecycle/);

    // The defect: every row on /registry lost its ending at 1280px, cut
    // mid-clause with no ellipsis, so it read as a complete-if-odd sentence.
    // The first row lost "reverts" — the consequence, and the whole reason the
    // row is on the page.
    expect(cell.className).not.toContain("whitespace-nowrap");
    // Tabular figures and right alignment both exist to line numbers up under
    // one another. Neither helps a sentence, and both go with the nowrap.
    expect(cell.className).not.toContain("tabular");
    expect(cell.className).not.toContain("text-right");
    expect(cell).toHaveTextContent("reverts");
  });

  it("keeps figures on one line, which is what the third column was built for", () => {
    render(
      <DataTable
        caption="Agent against baseline"
        columns={["Metric", "Warden", "Doing it yourself"]}
        rows={[{ label: "fees", value: "865.43", note: "1,220,001,498" }]}
      />,
    );
    const cell = noteCell(/Agent against baseline/);

    // `ComparisonTable` is the caller this form exists for. A long integer
    // breaking across two lines stops a column of numbers being a column.
    expect(cell.className).toContain("whitespace-nowrap");
    expect(cell.className).toContain("tabular");
  });

  it("defaults to figures, so no existing caller changes meaning", () => {
    render(
      <DataTable caption="Default" columns={["a", "b", "c"]} rows={[{ label: "x", value: "1", note: "2" }]} />,
    );
    expect(noteCell("Default").className).toContain("whitespace-nowrap");
  });
});

describe("the two-column form is unaffected", () => {
  it("still sets its note as a quiet annotation rather than a peer", () => {
    // Two columns label themselves — "fees | 865.43" needs no header — and the
    // note there is provenance, not a second measurement.
    render(
      <DataTable
        caption="How the quote was constructed"
        rows={[{ label: "observations", value: "60", note: "20 windows × 3 perturbations" }]}
      />,
    );
    const cell = noteCell(/How the quote/);
    expect(cell.className).toContain("text-faint");
    expect(cell.className).not.toContain("tabular");
  });
});
