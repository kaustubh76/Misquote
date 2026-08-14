# Agent Advantage Report

**Does hiring an agent beat doing the job yourself, and can we prove it?**

> **COUNTERFACTUAL — neither position was held.** Every position priced here is a replay, not a
> record. No capital was deployed. Published as assumption A6.

- **Tape:** `synthetic`
- **Capital per task:** 1,000 (quote token)
- **Tasks:** 3 · quotable 3 · withheld 0
- **Categories:** security, trading

## The claim this report is allowed to make

The baseline is **not a different program**. Every column runs through the
same `ReplayDriver`, the same tape, the same cost model, the same LVR
accountant and the same quote machinery. The only thing that differs is the
function that returns a `Decision`. Swap `policy=` and everything else is
held fixed by construction — which is why the usual way of flattering an
agent, by charging its baseline differently, is not available here.

## Results

| Task | Category | DIY (P25–P75) | Agent (P25–P75) | Δ median | Verdict |
|---|---|---|---|---|---|
| Earn — fees on a liquidity position | trading | 5.63 – 26.05% | 36.88 – 38.72% | **+27.75pp** | agent beats DIY by 27.75pp, bands do not overlap |
| Protect — avoid being picked off by one-way flow | security | 8.91 – 9.05% | 7.13 – 7.31% | **-1.77pp** | agent loses to DIY by 1.77pp, bands do not overlap |
| Choose — which pool to provide liquidity to | security | -1.87 – -1.36% | 35.76 – 38.31% | **+38.22pp** | agent beats DIY by 38.22pp, bands do not overlap |

**Across all tasks:** no verdict (3 observations, need 30)

That refusal is deliberate and it is the honest headline. `verdict()` will
not call a rate on fewer than 30 observations, and three tasks are three
observations. What carries the argument is each task's own quote, where the
sample is 20 sub-windows × 3 parameter perturbations rather than one run.

## Task detail

### Earn — fees on a liquidity position

- **Category:** trading · **Venue:** PancakeSwap v3 WBNB/USDT 0.05% (synthetic tape)
- **Without an agent:** mint once at the same width, never touch it (passive_policy)
- **With an agent:** Warden — Avellaneda–Stoikov recentring
- **Metric:** net return on capital (fees − realized convexity cost − costs), P25–P75

| | DIY | Agent |
|---|---|---|
| Net return P25–P75 | 5.63 – 26.05% | 36.88 – 38.72% |
| Median | 9.99% | 37.74% |
| In range | 2.4% | 59.6% |
| Fees | 32.1231 | 865.4302 |
| Realized convexity cost (upper bound on LVR) | 0.0107 | 0.2497 |
| Costs charged | 2.00 | 80.00 |
| Moves | 1 | 56 |

**agent beats DIY by 27.75pp, bands do not overlap**

Bands overlap: **no**. Non-overlapping bands are what lets the difference be stated at all.

### Protect — avoid being picked off by one-way flow

- **Category:** security · **Venue:** PancakeSwap v3 WBNB/USDT 0.05% (synthetic tape)
- **Without an agent:** the same wide band, held through everything (withdrawal disabled)
- **With an agent:** Sentinel — withdraw on §3.4 toxicity, re-enter after m_clear
- **Metric:** net return on capital, P25–P75 (the cost of the withdrawals is charged in full)

| | DIY | Agent |
|---|---|---|
| Net return P25–P75 | 8.91 – 9.05% | 7.13 – 7.31% |
| Median | 9.00% | 7.22% |
| In range | 100.0% | 98.4% |
| Fees | 186.1808 | 181.4964 |
| Realized convexity cost (upper bound on LVR) | 0.0547 | 0.0533 |
| Costs charged | 4.00 | 32.00 |
| Moves | 2 | 30 |

**agent loses to DIY by 1.77pp, bands do not overlap**

Bands overlap: **no**. Non-overlapping bands are what lets the difference be stated at all.

### Choose — which pool to provide liquidity to

- **Category:** security · **Venue:** two venues: deeper-but-one-way vs shallower-but-balanced
- **Without an agent:** pick the deepest pool (the obvious heuristic: more TVL is safer)
- **With an agent:** pick the pool whose flow is not one-way (§3.4 imbalance screen)
- **Metric:** net return on capital of the same agent on the chosen venue, P25–P75

| | DIY | Agent |
|---|---|---|
| Net return P25–P75 | -1.87 – -1.36% | 35.76 – 38.31% |
| Median | -1.52% | 36.71% |
| In range | 2.5% | 53.3% |
| Fees | 40.5360 | 786.8051 |
| Realized convexity cost (upper bound on LVR) | 0.0738 | 0.2381 |
| Costs charged | 68.00 | 76.00 |
| Moves | 68 | 51 |

**agent beats DIY by 38.22pp, bands do not overlap**

Bands overlap: **no**. Non-overlapping bands are what lets the difference be stated at all.

## What would make this stronger

- **A real tape.** These runs are labelled above. Free BSC endpoints refuse a
  multi-day backfill — six hours of the target pool dies in 11 seconds with
  `-32005 limit exceeded` — so the report needs a keyed `BSC_RPC_URL` before
  the word *real* in the track's requirement is earned.
- Every assumption behind these numbers is in [`ASSUMPTIONS.md`](ASSUMPTIONS.md);
  every deviation from the frozen spec, with its arithmetic, is in
  [`REQUIREMENTS_MATRIX.md`](REQUIREMENTS_MATRIX.md).

