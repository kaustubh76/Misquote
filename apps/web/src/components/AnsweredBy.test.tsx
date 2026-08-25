import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AnsweredBy } from "@/components/AnsweredBy";

describe("AnsweredBy", () => {
  it("says which source answered, in words rather than only in colour", () => {
    const { rerender } = render(<AnsweredBy source="live" />);
    expect(screen.getByText(/answered live/)).toBeInTheDocument();

    rerender(<AnsweredBy source="artifact" />);
    expect(screen.getByText(/recorded earlier/)).toBeInTheDocument();
  });

  it("distinguishes the two by shape as well, for a reader who cannot see tone", () => {
    // The dot is `aria-hidden`, so this reaches for it through the DOM rather
    // than through a query — the point being that the two states differ by
    // something other than a colour class.
    const { container, rerender } = render(<AnsweredBy source="live" />);
    const filled = container.querySelector("span[aria-hidden] , span[aria-hidden='true']");
    expect(filled?.className).toContain("bg-good");

    rerender(<AnsweredBy source="artifact" />);
    expect(container.querySelector("span[aria-hidden='true']")?.className).not.toContain("bg-good");
  });
});
