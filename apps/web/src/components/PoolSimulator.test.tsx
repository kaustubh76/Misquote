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
  ...over,
});

const flagship = {
  address: "0x3669",
  label: "PancakeSwap v3 WBNB/USDT 0.05%",
  quote_symbol: "WBNB",
  fee_pips: 500,
  tick_spacing: 10,
  lp_fee_share: 0.66,
  badged: true,
  tape: { swaps: 252923, first_ts: 1_755_000_000, last_ts: 1_758_000_000 },
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
  tape: { swaps: 85, first_ts: 1_755_000_000, last_ts: 1_758_000_000 },
  price_path: [],
  cells: [],
  bands: [],
  best_width_ticks: null,
  verdict: "no width has enough evidence on this pool",
};

const artifact = (pools = [flagship, equity]): SimulationArtifact => ({
  chain_id: 56,
  capital_quote: 0.1,
  width_ladder: [40, 80, 130, 200, 244, 400, 800],
  capital_ladder: [0.01, 0.1, 0.5, 2.0],
  a1_share: 0.01,
  path_points: 240,
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
