import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import {
  PoolSimulator,
  type SimCell,
  type SimulationArtifact,
} from "./PoolSimulator";

/**
 * Two sizes of the same window, with the sublinearity the emitter measured.
 *
 * 0.1 earns 0.0100 and 0.5 earns 0.0497 — five times the capital, 4.97 times
 * the fees, and a lower rate. Those are the shape of the real numbers, and the
 * reason this component selects a cell instead of multiplying one.
 */
const cell = (over: Partial<SimCell> = {}): SimCell => ({
  width_ticks: 80,
  window: 0,
  capital_quote: 0.1,
  a1_ceiling_quote: 4.21,
  start_ts: 1_756_000_000,
  end_ts: 1_757_000_000,
  hours: 277.8,
  swaps: 4211,
  fee_apr: 0.31,
  convexity_cost_apr: 0.14,
  net_apr: 0.17,
  fees_quote: 0.0100,
  convexity_cost_quote: 0.0045,
  depth_quote: 421,
  tick_lower: -65380,
  tick_upper: -65220,
  mintable: true,
  not_mintable_why: "",
  ...over,
});

const flagship = {
  address: "0x3669",
  label: "PancakeSwap v3 WBNB/USDT 0.05%",
  quote_symbol: "WBNB",
  tick_spacing: 10,
  lp_fee_share: 0.66,
  tape: { swaps: 252923 },
  price_path: [
    { ts: 1_756_000_000, tick: -65340, price: 0.0012 },
    { ts: 1_756_500_000, tick: -65300, price: 0.00121 },
    { ts: 1_757_000_000, tick: -65360, price: 0.00119 },
  ],
  cells: [
    cell(),
    cell({
      capital_quote: 0.5,
      fees_quote: 0.0497,
      convexity_cost_quote: 0.0224,
      net_apr: 0.169,
    }),
    // A second window at the opening size, so the scrubber has somewhere to go.
    cell({
      window: 1,
      start_ts: 1_756_500_000,
      end_ts: 1_757_500_000,
      fees_quote: 0.0081,
      convexity_cost_quote: 0.0045,
      net_apr: 0.12,
    }),
  ],
  bands: [
    {
      width_ticks: 80,
      p25: 0.127,
      p50: 0.17,
      p75: 0.282,
      observations: 20,
      sufficient: true,
      note: "",
    },
  ],
  best_width_ticks: 80,
  verdict: "+/-80 ticks leads at the median, but its band overlaps +/-130",
};

/** The thin pool, which must refuse rather than show a small number. */
const equity = {
  ...flagship,
  address: "0x5E12",
  label: "PancakeSwap v3 TSLAx/USDT 0.25%",
  quote_symbol: "TSLAx",
  tape: { swaps: 85 },
  price_path: [],
  cells: [],
  bands: [],
  best_width_ticks: null,
  verdict: "no width has enough evidence on this pool",
};

const artifact = (pools = [flagship, equity]): SimulationArtifact => ({
  capital_quote: 0.1,
  width_ladder: [40, 80, 130, 200, 244, 400, 800],
  a1_share: 0.01,
  summary: { pools: pools.length, badged: 3, simulable: 1, refused: 1, cells: 3 },
  pools,
});

const draw = (data = artifact()) => render(<PoolSimulator data={data} />);

describe("the amount is chosen from sizes that were replayed", () => {
  it("offers only the sizes this pool has cells for", () => {
    draw();
    // 0.01 and 2.00 are on the ladder and have no cells here, so they are not
    // offered. A rung that refuses when pressed is a control that lied.
    expect(screen.getByRole("button", { name: "0.10" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "0.50" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "0.01" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "2.00" })).not.toBeInTheDocument();
  });

  it("shows the bigger size earning less than its multiple", async () => {
    // The whole reason capital is swept. Five times the capital, 4.97 times the
    // fees. A browser multiplying the smaller cell would have printed 0.02750
    // net — the dilution deleted, in the direction that flatters the larger
    // position. The replayed answer is 0.02730.
    draw();
    expect(document.body.textContent).toContain("0.00550");

    await userEvent.click(screen.getByRole("button", { name: "0.50" }));
    const said = document.body.textContent ?? "";
    expect(said).toContain("0.02730");
    expect(said, "this is the figure a multiplication would have produced").not.toContain(
      "0.02750"
    );
  });

  it("marks which size is selected", async () => {
    draw();
    const bigger = screen.getByRole("button", { name: "0.50" });
    expect(bigger).toHaveAttribute("aria-pressed", "false");

    await userEvent.click(bigger);
    expect(bigger).toHaveAttribute("aria-pressed", "true");
  });
});

describe("scaling up costs something, and the page says what", () => {
  it("compares two replayed sizes rather than one scaled", async () => {
    // The finding the sweep exists for. Without this line a reader pressing the
    // rungs watches the rate move and has no reason not to read it as noise.
    draw();
    await userEvent.click(screen.getByRole("button", { name: "0.50" }));

    const said = document.body.textContent ?? "";
    expect(said).toContain("The same window at");
    expect(said).toContain("0.10 WBNB");
    // 17.0% at the small size against 16.9% at the large one: 0.10pp.
    expect(said).toContain("0.10pp");
    expect(said).toContain("less");
    expect(said).toContain("Both figures are replayed");
  });

  it("says nothing at the smallest size, because there is nothing to compare", () => {
    draw();
    expect(document.body.textContent).not.toContain("The same window at");
  });

  it("stays quiet when the difference would print as zero", async () => {
    // The threshold is the precision the figure is shown at, not a number: a
    // line reading "0.00pp less" claims a difference while displaying its
    // absence. On the real flagship this fires at ±800, where the dilution is
    // 0.0079pp and genuinely nothing.
    const flat = {
      ...flagship,
      cells: [
        cell(),
        cell({ capital_quote: 0.5, fees_quote: 0.0497, net_apr: 0.17 }),
      ],
    };
    draw(artifact([flat]));
    await userEvent.click(screen.getByRole("button", { name: "0.50" }));

    expect(document.body.textContent).not.toContain("The same window at");
  });
});

describe("it says nobody is managing the position", () => {
  // The defect this page shipped with. `PoolAprEstimator` opens one range at the
  // window's start and holds it — nothing ages out, so the centre never moves —
  // and the page sat in the product nav between Quote and Hire saying nothing
  // about that. On an agent marketplace, silence reads as "this is what hiring
  // gets you", which is the one thing the figure is not.
  it("states it beside the figure, not only in the caveats", () => {
    draw();
    expect(screen.getByText(/Nobody is managing this position/)).toBeInTheDocument();
    expect(document.body.textContent).toContain("never recentred");
  });

  it("frames it as the baseline an agent has to beat, and links to where that is measured", () => {
    draw();
    const link = screen.getByRole("link", { name: /What recentring adds/ });
    expect(link).toHaveAttribute("href", "/advantage");
    // Not an apology: the sentence has to say what the number is for.
    expect(document.body.textContent).toContain("what doing it yourself looks like");
  });

  it("makes the agent case from the price path only when the price actually left", async () => {
    // The share outside the range is the case for recentring. Stating it when
    // the price never left would be selling rather than measuring — and a page
    // that argued one way regardless is the thing this project is named
    // against.
    const inside = {
      ...flagship,
      // Every sampled point sits inside -65380..-65220.
      price_path: [
        { ts: 1_756_000_000, tick: -65300, price: 0.0012 },
        { ts: 1_756_500_000, tick: -65290, price: 0.00121 },
        { ts: 1_757_000_000, tick: -65310, price: 0.00119 },
      ],
    };
    draw(artifact([inside]));

    expect(screen.getByText(/an unmanaged range was the right answer/)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /That gap is what an agent is for/ })).not.toBeInTheDocument();
  });

  it("makes it when the price did leave", () => {
    // The committed fixture's path runs to -65340, outside -65220 at the top.
    const outside = {
      ...flagship,
      price_path: [
        { ts: 1_756_000_000, tick: -65900, price: 0.0011 },
        { ts: 1_756_500_000, tick: -65950, price: 0.00109 },
        { ts: 1_757_000_000, tick: -66000, price: 0.00108 },
      ],
    };
    draw(artifact([outside]));

    expect(document.body.textContent).toContain("nothing moved it back");
    expect(
      screen.getByRole("link", { name: /That gap is what an agent is for/ })
    ).toHaveAttribute("href", "/advantage");
  });
});

describe("a width this pool would refuse is marked as one", () => {
  // The estimator snaps the centre to the spacing and takes `centre ± width`
  // without snapping the width, so a rung is on the grid only when
  // `width % spacing == 0`. The ladder is shared across pools with different
  // spacings, so /simulate was offering four widths the 0.25% pool rejects —
  // on a site whose /venue documents that revert as divergence five.
  const refused = "A position here could not be minted: its bounds are off this pool's 50-tick grid.";
  const offGrid = {
    ...flagship,
    tick_spacing: 50,
    cells: [
      cell({ width_ticks: 40, mintable: false, not_mintable_why: refused }),
      cell({ width_ticks: 200 }),
    ],
  };

  it("renders the emitter's reason rather than one written here", () => {
    draw(artifact([offGrid]));
    expect(screen.getByText(refused)).toBeInTheDocument();
  });

  it("keeps the measurement and qualifies only the claim about taking it", () => {
    draw(artifact([offGrid]));
    // The figures stay — the ladder is only a like-for-like comparison because
    // every pool is measured at the same widths.
    expect(document.body.textContent).toContain("0.00550");
    expect(document.body.textContent).toContain("not a position");
  });

  it("marks the rung itself, in its accessible name and not only its texture", () => {
    draw(artifact([offGrid]));
    expect(
      screen.getByRole("button", { name: /±40 ticks — not mintable on this pool/ })
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "±200 ticks" })).toBeInTheDocument();
  });

  it("says nothing when every width on the ladder is mintable", () => {
    draw();
    expect(screen.queryByText(/not mintable/)).not.toBeInTheDocument();
  });
});

describe("the rate pair the estimator requires", () => {
  it("shows both terms of the subtraction, not only its answer", () => {
    // `estimators/pool_apr.py`: "every caller in this repository is expected to
    // render the pair". This page emitted both and rendered neither.
    draw();
    const said = document.body.textContent ?? "";
    expect(said).toContain("31.0%"); // fee_apr
    expect(said).toContain("14.0%"); // convexity_cost_apr
    expect(said).toContain("17.0%"); // net
  });
});

describe("how much each pool can take", () => {
  it("reads the ceilings off the cells rather than carrying its own", () => {
    // The finding /venue cannot state, because the ceilings are measured here.
    // Typed numbers would be a second opinion about the artifact, and would go
    // stale the first time the tape moved.
    const wide = { ...flagship, cells: [
      cell({ width_ticks: 40, a1_ceiling_quote: 2.1071 }),
      cell({ width_ticks: 800, a1_ceiling_quote: 41.3529 }),
    ] };
    const thin = { ...flagship, address: "0x1401", label: "PancakeSwap v3 WBNB/USDT 0.25%",
      cells: [
        cell({ width_ticks: 40, a1_ceiling_quote: 0.0128 }),
        cell({ width_ticks: 800, a1_ceiling_quote: 0.2518 }),
      ] };
    draw(artifact([wide, thin]));

    const said = document.body.textContent ?? "";
    expect(said).toContain("2.1071");
    expect(said).toContain("41.3529");
    // The one that carries the finding: the thin pool takes almost nothing.
    expect(said).toContain("0.0128");
    expect(said).toContain("0.2518");
  });

  it("says nothing when there is only one pool to compare", () => {
    // A capacity table of one row is a fact about a pool, not the comparison
    // the section exists to draw.
    draw(artifact([flagship]));
    expect(screen.queryByText(/How much each pool can actually take/)).not.toBeInTheDocument();
  });
});

describe("A1 refuses rather than clamps", () => {
  it("will not quote a position bigger than its share of the venue", () => {
    // 2 WBNB against a ceiling of 0.026 — the 0.25% pool's real shape.
    const tight = {
      ...flagship,
      cells: [cell({ capital_quote: 2, a1_ceiling_quote: 0.026, depth_quote: 2.6 })],
    };
    draw(artifact([tight]));

    expect(screen.getByText(/more than this range can absorb/)).toBeInTheDocument();
    expect(document.body.textContent).toContain("0.0260");
    // Named, so the refusal is checkable rather than a shrug.
    expect(document.body.textContent).toContain("1.0%");
  });

  it("says a clamped answer would be an answer to a different question", () => {
    const tight = {
      ...flagship,
      cells: [cell({ capital_quote: 2, a1_ceiling_quote: 0.026 })],
    };
    draw(artifact([tight]));
    expect(screen.getByText(/Refused rather than clamped/)).toBeInTheDocument();
  });
});

describe("a pool with no evidence gets no figure", () => {
  it("renders the engine's verdict rather than a zero", async () => {
    draw();
    await userEvent.selectOptions(
      screen.getByLabelText("Pool"),
      "0x5E12"
    );

    expect(
      screen.getByText("no width has enough evidence on this pool")
    ).toBeInTheDocument();
    expect(document.body.textContent).toContain("85");
    // No CostBars, no band, no path — nothing that looks like a result.
    expect(screen.queryByText(/fees earned/)).not.toBeInTheDocument();
  });

  it("says so in the selector too, before it is chosen", () => {
    draw();
    expect(
      within(screen.getByLabelText("Pool")).getByRole("option", {
        name: /TSLAx.*not simulable/,
      })
    ).toBeInTheDocument();
  });
});

describe("the window is one draw, and says so", () => {
  it("puts the band across every window beside the single one chosen", () => {
    draw();
    expect(document.body.textContent).toContain("one of 20");
    // The engine's verdict, verbatim, rather than a winner re-derived here.
    expect(
      screen.getByText("+/-80 ticks leads at the median, but its band overlaps +/-130")
    ).toBeInTheDocument();
  });

  it("moves to another replayed window rather than interpolating between them", async () => {
    draw();
    const scrubber = screen.getByRole("slider");
    expect(scrubber).toHaveAttribute("max", "1");

    // `fireEvent.change`, not arrow keys: jsdom does not implement a range
    // input's keyboard stepping, so `{ArrowRight}` moves nothing and the test
    // would pass by asserting the first window against itself.
    fireEvent.change(scrubber, { target: { value: "1" } });
    // Window 1's own fees minus its own cost, which is a cell and not a slide
    // between two of them.
    expect(document.body.textContent).toContain("0.00360");
  });
});

describe("the price path says where the range was", () => {
  it("describes itself for a reader who is not looking at it", () => {
    draw();
    const chart = screen.getByRole("img", { name: /Price over the window/ });
    // Grouped, the way `count()` formats every other figure on the site.
    expect(chart).toHaveAccessibleName(/-65,380/);
    expect(chart).toHaveAccessibleName(/-65,220/);
  });
});
