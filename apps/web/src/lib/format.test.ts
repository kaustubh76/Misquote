import { describe, expect, it } from "vitest";
import { EMPTY, amount, fixed, fraction, money, pct, signOf, signed } from "./format";

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

describe("a figure carries the unit it is denominated in", () => {
  it("attaches the unit to a value that exists", () => {
    // `-186.74` was on the front page unlabelled, and a reader supplies
    // dollars. `*_quote` is token1, which on this pool is WBNB — so it is
    // roughly a hundred thousand dollars, not a hundred and eighty-seven.
    // ASCII hyphen, not U+2212: `amount()` delegates to `toLocaleString`,
    // which emits one, while `signed()` writes the typographic minus itself.
    // The two disagree; pinned here as the current fact rather than wished away.
    expect(money(-186.742015, "WBNB")).toBe("-186.74 WBNB");
  });

  it("never attaches a unit to a value that does not exist", () => {
    // "— WBNB" would give a unit to a measurement that was not taken. Every
    // absent-value path collapses to the em dash alone.
    expect(money(undefined, "WBNB")).toBe(EMPTY);
    expect(money(null, "WBNB")).toBe(EMPTY);
    expect(money(NaN, "WBNB")).toBe(EMPTY);
    expect(money(Infinity, "WBNB")).toBe(EMPTY);
  });

  it("renders bare when the artifact does not say what the unit is", () => {
    // Artifacts written before the emitter carried `quote_symbol` genuinely do
    // not know. Bare is honest; a default would be the project's own failure.
    expect(money(-186.742015)).toBe("-186.74");
    expect(money(-186.742015, undefined)).toBe("-186.74");
  });

  it("separates figure from unit with a non-breaking space", () => {
    // So `186.74 WBNB` cannot wrap onto two lines, leaving a bare number at the
    // end of one — which is the defect this function exists to remove.
    expect(money(186.74, "WBNB")).not.toContain(" WBNB");
    expect(money(186.74, "WBNB")).toContain(" WBNB");
  });
});

describe("a bare parameter, to a fixed number of decimals", () => {
  it("does not group thousands", () => {
    // κ per log-price is 3600.907. `amount()` renders it "3,600.91" — a comma
    // the artifact does not have, in a field a reader compares against the JSON.
    expect(fixed(3600.9070575659784, 2)).toBe("3600.91");
    expect(fixed(3600.9070575659784, 2)).not.toContain(",");
  });

  it("renders an absent parameter as the em dash rather than throwing", () => {
    // The defect: six call sites wrote `e.sigma_per_sqrt_hour.toFixed(6)` on a
    // block the emitter can write as `{}`. There is no error boundary deep
    // enough to make that a subtree failure — it took the whole route.
    expect(fixed(undefined, 6)).toBe(EMPTY);
    expect(fixed(null, 6)).toBe(EMPTY);
    expect(fixed(NaN, 4)).toBe(EMPTY);
  });

  it("keeps the decimals a small parameter needs", () => {
    // σ per √hour is 4.5e-4. At two decimals it reads 0.00 — which is not the
    // value and not an absence either.
    expect(fixed(0.00045053116084847397, 6)).toBe("0.000451");
  });
});

describe("a small amount is not rounded to nothing", () => {
  it("keeps two significant figures below one", () => {
    // Sentinel's whole chart, at the capital basis that landed this week:
    // fees 0.00024111, adverse selection 0.00181907, costs 0.00379389. At two
    // fixed places every one of them printed 0.00 — and `CostBars` captioned
    // itself "scaled against 0.00 WBNB, the largest component". A denominator
    // of zero, under bars drawn from real ratios.
    expect(amount(0.00024111)).toBe("0.00024");
    expect(amount(0.00181907)).toBe("0.0018");
    expect(amount(0.00379389)).toBe("0.0038");
    expect(money(0.00379389, "WBNB")).toBe("0.0038 WBNB");
  });

  it("still refuses six decimals of a large figure", () => {
    // The defect this function was written for, which must survive the fix.
    // `num(v, 6)` rendered a fee total as 865.430184 — six decimals of
    // precision the number does not have.
    expect(amount(865.43018362)).toBe("865.43");
    expect(amount(-186.742015)).toBe("-186.74");
  });

  it("honours an explicit larger precision", () => {
    // `fixed()` covers bare parameters, but a caller asking `amount` for more
    // places must still get them — the rule only ever adds, never removes.
    expect(amount(0.5, 4)).toBe("0.5000");
    expect(amount(0.00024111, 6)).toBe("0.000241");
  });

  it("stops before the float noise", () => {
    // Past eight places the digits are an artefact of binary floating point,
    // not a reading. A number too small to show is still not shown as zero:
    // it is shown at the cap.
    expect(amount(1e-12).length).toBeLessThanOrEqual("0.00000000".length);
    expect(amount(0)).toBe("0.00");
  });
});
