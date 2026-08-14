import { describe, expect, it } from "vitest";
import { amount, EMPTY, fraction, pct, signOf, signed } from "./format";

describe("missing values never acquire a judgement", () => {
  // The bug: `net > 0 ? "pos" : "neg"`. `undefined > 0` is false, so the else
  // branch ran and a placeholder dash was painted in the loss colour — the page
  // said "this lost money" when it meant "this number is absent".
  it.each([undefined, null, NaN, Infinity, -Infinity, "12", {}])(
    "signOf(%s) is 'none', not 'neg'",
    (v) => {
      expect(signOf(v)).toBe("none");
    },
  );

  it("distinguishes zero from missing", () => {
    expect(signOf(0)).toBe("zero");
    expect(signOf(-0)).toBe("zero");
    expect(signOf(-0.01)).toBe("neg");
    expect(signOf(0.01)).toBe("pos");
  });

  it.each([amount, pct, fraction, signed])("%o renders absent values as an em dash", (fn) => {
    expect(fn(undefined)).toBe(EMPTY);
    expect(fn(null)).toBe(EMPTY);
    expect(fn(NaN)).toBe(EMPTY);
  });
});

describe("signs survive greyscale", () => {
  it("prints an explicit sign character", () => {
    expect(signed(27.7524, 2, "pp")).toBe("+27.75pp");
    expect(signed(-1.77, 2, "pp")).toBe("−1.77pp");
    expect(signed(0, 2, "pp")).toBe("±0.00pp");
  });
});

describe("precision matches the claim", () => {
  it("does not print six decimals of a dollar amount", () => {
    // The old page's `num(v, 6)` rendered 865.430184 for a fee total.
    expect(amount(865.43018362)).toBe("865.43");
  });

  it("keeps percentages in percentage points", () => {
    expect(pct(37.74221223169183)).toBe("37.74%");
  });

  it("converts fractions to percentages", () => {
    expect(fraction(0.5956)).toBe("59.6%");
  });
});
