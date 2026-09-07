import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { HirePrice } from "@/components/HirePrice";

/**
 * The marketplace had no price on it anywhere, which is a strange thing for a
 * marketplace. It still does not quote per agent — the buyer sets the escrow —
 * and these assert that the arrangement is stated rather than a figure invented.
 */

afterEach(cleanup);

describe("what hiring costs", () => {
  it("states the opening escrow as a token amount, not as wei", () => {
    render(<HirePrice terms={{ opening_budget: 1e17, budget_decimals: 18, fee_bnb: 0.000755007 }} />);
    expect(screen.getByText("0.1")).toBeInTheDocument();
    expect(screen.getByText(/0\.000755 BNB/)).toBeInTheDocument();
  });

  // Eighteen decimals of integer are past what a double holds exactly, and this
  // is a money figure on a storefront.
  it("divides on a bigint rather than a float", () => {
    render(<HirePrice terms={{ opening_budget: 1e18, budget_decimals: 18 }} />);
    expect(screen.getByText("1")).toBeInTheDocument();
  });

  it("renders nothing rather than a guess when neither figure is known", () => {
    const { container } = render(<HirePrice terms={{}} />);
    expect(container).toBeEmptyDOMElement();
    const bare = render(<HirePrice />);
    expect(bare.container).toBeEmptyDOMElement();
  });

  it("shows the half it has when the other is missing", () => {
    render(<HirePrice terms={{ opening_budget: null, budget_decimals: 18, fee_bnb: 0.0007 }} />);
    expect(screen.getByText(/0\.000700 BNB/)).toBeInTheDocument();
    expect(screen.queryByText(/an escrow you set/)).not.toBeInTheDocument();
  });

  it("points at the page that performs the hire", () => {
    render(<HirePrice terms={{ opening_budget: 1e17, budget_decimals: 18 }} />);
    // next/link normalises the trailing slash away in this environment; the
    // route is what matters, not the spelling.
    expect(
      screen.getByRole("link", { name: /What that pays for/ }).getAttribute("href"),
    ).toMatch(/^\/activate\/?$/);
  });
});
