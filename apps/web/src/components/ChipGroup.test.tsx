import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it } from "vitest";
import { ChipGroup, type Chip } from "./ChipGroup";

/**
 * The component was extracted so a second copy of the keyboard contract would
 * not have to be written — and then had no test of its own for three consumers.
 *
 * `ThemeToggle` has its arrow keys asserted; `ChipGroup` was covered only
 * through `/assumptions`, which exercises a click and one ArrowRight. Home,
 * End, ArrowLeft, ArrowUp, ArrowDown and both wraps were untested in the
 * component every filter on the site now shares.
 */
const OPTIONS: Chip<string>[] = [
  { value: "all", label: "All", meta: "11" },
  { value: "pass", label: "Passing", meta: "6" },
  { value: "unverified", label: "Unverified", meta: "5" },
];

function Harness({ initial = "all" }: { initial?: string }) {
  const [value, setValue] = useState(initial);
  return <ChipGroup label="Filter by verdict" options={OPTIONS} value={value} onChange={setValue} />;
}

const chips = () => screen.getAllByRole("radio");
const checked = () => chips().find((c) => c.getAttribute("aria-checked") === "true");
const tabbable = () => chips().filter((c) => c.getAttribute("tabIndex") !== "-1");

describe("the group announces one tab stop, and has one", () => {
  it("gives the tab stop to the selected option", () => {
    render(<Harness initial="pass" />);
    expect(tabbable()).toHaveLength(1);
    expect(tabbable()[0]).toHaveAccessibleName(/Passing/);
  });

  it("keeps a tab stop when the value matches no option", () => {
    // The latent failure: `tabIndex={selected ? 0 : -1}` gives every chip -1
    // when nothing matches, and the control becomes unreachable by keyboard
    // while looking entirely normal. One refactor away at any time.
    render(<Harness initial="a-value-that-does-not-exist" />);

    expect(chips().every((c) => c.getAttribute("aria-checked") === "false")).toBe(true);
    expect(tabbable()).toHaveLength(1);
  });
});

describe("moving is selecting, on every key APG names", () => {
  it("moves right and wraps", async () => {
    const user = userEvent.setup();
    render(<Harness initial="unverified" />);
    chips()[2]!.focus();

    await user.keyboard("{ArrowRight}");
    expect(checked()).toHaveAccessibleName(/All/);
    expect(document.activeElement).toBe(chips()[0]);
  });

  it("moves left and wraps", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    chips()[0]!.focus();

    await user.keyboard("{ArrowLeft}");
    expect(checked()).toHaveAccessibleName(/Unverified/);
    expect(document.activeElement).toBe(chips()[2]);
  });

  it("treats the vertical arrows as the horizontal ones", async () => {
    // Both axes, because a radiogroup's orientation is not declared here and a
    // reader pressing Down on a row of chips means the next one.
    const user = userEvent.setup();
    render(<Harness />);
    chips()[0]!.focus();

    await user.keyboard("{ArrowDown}");
    expect(checked()).toHaveAccessibleName(/Passing/);
    await user.keyboard("{ArrowUp}");
    expect(checked()).toHaveAccessibleName(/All/);
  });

  it("jumps to the ends with Home and End", async () => {
    const user = userEvent.setup();
    render(<Harness initial="pass" />);
    chips()[1]!.focus();

    await user.keyboard("{End}");
    expect(checked()).toHaveAccessibleName(/Unverified/);
    await user.keyboard("{Home}");
    expect(checked()).toHaveAccessibleName(/All/);
  });

  it("leaves keys it does not own to the page", async () => {
    // `preventDefault` on everything would eat Tab and trap the reader.
    const user = userEvent.setup();
    render(<Harness />);
    chips()[0]!.focus();

    await user.keyboard("{Tab}");
    expect(document.activeElement).not.toBe(chips()[0]);
  });
});

describe("the count is part of the name", () => {
  it("reads as one phrase, not a label and an orphan number", () => {
    // "Passing 6" is the useful thing to hear. A visually-hidden duplicate
    // would make it "Passing 6 6".
    render(<Harness />);
    expect(screen.getByRole("radio", { name: "Passing 6" })).toBeInTheDocument();
  });
});
