# Agent Advantage Report

**Does hiring an agent beat doing the job yourself, and can we prove it?**

> **COUNTERFACTUAL — neither position was held.** Every position priced here is a replay, not a
> record. No capital was deployed. Published as assumption A6.

- **Tape:** `synthetic`
- **Capital per task:** 1 (quote token)
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
| Earn — fees on a liquidity position | trading | -2.50 – -0.63% | -2.48 – -2.24% | **-1.28pp** | agent loses to DIY by 1.28pp at the median, but the P25-P75 bands overlap — not separated at this sample size |
| Protect — avoid being picked off by one-way flow | security | -0.85 – -0.82% | -1.52 – -1.41% | **-0.57pp** | agent loses to DIY by 0.57pp, bands do not overlap |
| Choose — which pool to provide liquidity to | security | -1.50 – -1.23% | -2.48 – -2.20% | **-0.91pp** | agent loses to DIY by 0.91pp, bands do not overlap |

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
| Net return P25–P75 | -2.50 – -0.63% | -2.48 – -2.24% |
| Median | -1.02% | -2.30% |
| In range | 1.9% | 10.4% |
| Fees | 0.0005 | 0.0028 |
| Realized convexity cost (upper bound on LVR) | 0.0040 | 0.0209 |
| Costs charged | 0.00 | 0.02 |
| Moves | 1 | 64 |

**agent loses to DIY by 1.28pp at the median, but the P25-P75 bands overlap — not separated at this sample size**

Bands overlap: **yes**. Overlapping bands mean the two are not distinguishable at this sample size, however far apart the medians sit — which is precisely why this product publishes ranges rather than a single number.

### Protect — avoid being picked off by one-way flow

- **Category:** security · **Venue:** PancakeSwap v3 WBNB/USDT 0.05% (synthetic tape)
- **Without an agent:** the same wide band, held through everything (withdrawal disabled)
- **With an agent:** Sentinel — withdraw on §3.4 toxicity, re-enter after m_clear
- **Metric:** net return on capital, P25–P75 (the cost of the withdrawals is charged in full)

| | DIY | Agent |
|---|---|---|
| Net return P25–P75 | -0.85 – -0.82% | -1.52 – -1.41% |
| Median | -0.84% | -1.41% |
| In range | 24.3% | 11.1% |
| Fees | 0.0005 | 0.0002 |
| Realized convexity cost (upper bound on LVR) | 0.0043 | 0.0018 |
| Costs charged | 0.00 | 0.02 |
| Moves | 1 | 64 |

**agent loses to DIY by 0.57pp, bands do not overlap**

Bands overlap: **no**. Non-overlapping bands are what lets the difference be stated at all.

### Choose — which pool to provide liquidity to

- **Category:** security · **Venue:** two venues: deeper-but-one-way vs shallower-but-balanced
- **Without an agent:** pick the deepest pool (the obvious heuristic: more TVL is safer)
- **With an agent:** pick the pool whose flow is not one-way (§3.4 imbalance screen)
- **Metric:** net return on capital of the same agent on the chosen venue, P25–P75

| | DIY | Agent |
|---|---|---|
| Net return P25–P75 | -1.50 – -1.23% | -2.48 – -2.20% |
| Median | -1.34% | -2.26% |
| In range | 2.1% | 10.0% |
| Fees | 0.0002 | 0.0027 |
| Realized convexity cost (upper bound on LVR) | 0.0042 | 0.0202 |
| Costs charged | 0.02 | 0.02 |
| Moves | 48 | 64 |

**agent loses to DIY by 0.91pp, bands do not overlap**

Bands overlap: **no**. Non-overlapping bands are what lets the difference be stated at all.

## What would make this stronger

- **A real tape.** These runs are labelled above. Free BSC endpoints refuse a
  multi-day backfill — six hours of the target pool dies in 11 seconds with
  `-32005 limit exceeded` — so the report needs a keyed `BSC_RPC_URL` before
  the word *real* in the track's requirement is earned.
- Every assumption behind these numbers is in [`ASSUMPTIONS.md`](ASSUMPTIONS.md);
  every deviation from the frozen spec, with its arithmetic, is in
  [`REQUIREMENTS_MATRIX.md`](REQUIREMENTS_MATRIX.md).

