# Agent Advantage Report

**Does hiring an agent beat doing the job yourself, and can we prove it?**

> **COUNTERFACTUAL — neither position was held.** Every position priced here is a replay, not a
> record. No capital was deployed. Published as assumption A6.

- **Tape:** `synthetic`
- **Capital per task:** 1 (quote token)
- **Tasks:** 4 · quotable 0 · withheld 4
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
| Earn — fees on a liquidity position | trading | withheld | withheld | withheld | no verdict — baseline: 0 usable replays, assumption A5 requires 20; 60 window(s) were shorter than the 24h policy horizon; agent: 0 usable replays, assumption A5 requires 20; 60 window(s) were shorter than the 24h policy horizon |
| Market-make — quote both sides of a range | trading | withheld | withheld | withheld | no verdict — baseline: 0 usable replays, assumption A5 requires 20; 60 window(s) were shorter than the 24h policy horizon; agent: 0 usable replays, assumption A5 requires 20; 60 window(s) were shorter than the 24h policy horizon |
| Protect — avoid being picked off by one-way flow | security | withheld | withheld | withheld | no verdict — baseline: 0 usable replays, assumption A5 requires 20; 60 window(s) were shorter than the 24h policy horizon; agent: 0 usable replays, assumption A5 requires 20; 60 window(s) were shorter than the 24h policy horizon |
| Choose — which pool to provide liquidity to | security | withheld | withheld | withheld | no verdict — baseline: 0 usable replays, assumption A5 requires 20; 60 window(s) were shorter than the 24h policy horizon; agent: 0 usable replays, assumption A5 requires 20; 60 window(s) were shorter than the 24h policy horizon |

**Across all tasks:** no verdict (0 observations, need 30)

That refusal is deliberate and it is the honest headline. `verdict()` will
not call a rate on fewer than 30 observations, and three tasks are three
observations. What carries the argument is each task's own quote, where the
sample is 20 sub-windows × 3 parameter perturbations rather than one run.

## Task detail

### Earn — fees on a liquidity position

- **Category:** trading · **Venue:** PancakeSwap v3 WBNB/USDT 0.05% · 0x36696169C63e42cd08ce11f5deeBbCeBae652050 (synthetic tape)
- **Without an agent:** mint once at the same width, never touch it (passive_policy)
- **With an agent:** Warden — Avellaneda–Stoikov recentring
- **Metric:** net return on capital (fees − realized convexity cost − costs), P25–P75

- **Worse on the quantity this task is named after** — fees earned: 0.000323538 vs 0.000323538 — worse

**No verdict.** baseline: 0 usable replays, assumption A5 requires 20; 60 window(s) were shorter than the 24h policy horizon; agent: 0 usable replays, assumption A5 requires 20; 60 window(s) were shorter than the 24h policy horizon

### Market-make — quote both sides of a range

- **Category:** trading · **Venue:** PancakeSwap v3 WBNB/USDT 0.05% · 0x36696169C63e42cd08ce11f5deeBbCeBae652050 (synthetic tape)
- **Without an agent:** mint once at the same width, never touch it (passive_policy)
- **With an agent:** Grid — fixed rung ladder, requote when price leaves it
- **Metric:** net return on capital (fees − realized convexity cost − costs), P25–P75

- **Better on the quantity this task is named after** — time in range: 0.999697 vs 0.781972 — 1.3x better

**No verdict.** baseline: 0 usable replays, assumption A5 requires 20; 60 window(s) were shorter than the 24h policy horizon; agent: 0 usable replays, assumption A5 requires 20; 60 window(s) were shorter than the 24h policy horizon

### Protect — avoid being picked off by one-way flow

- **Category:** security · **Venue:** PancakeSwap v3 WBNB/USDT 0.05% · 0x36696169C63e42cd08ce11f5deeBbCeBae652050 (synthetic tape)
- **Without an agent:** the same wide band, held through everything (withdrawal disabled)
- **With an agent:** Sentinel — withdraw on §3.4 toxicity, re-enter after m_clear
- **Metric:** net return on capital, P25–P75 (the cost of the withdrawals is charged in full)

- **Better on the quantity this task is named after** — realized convexity cost (upper bound on LVR): 0.00186109 vs 0.0031666 — 1.7x better

**No verdict.** baseline: 0 usable replays, assumption A5 requires 20; 60 window(s) were shorter than the 24h policy horizon; agent: 0 usable replays, assumption A5 requires 20; 60 window(s) were shorter than the 24h policy horizon

### Choose — which pool to provide liquidity to

- **Category:** security · **Venue:** two venues: a one-way venue (synthetic) vs a balanced venue (synthetic)
- **Without an agent:** pick the deepest pool — a one-way venue (synthetic), 4.0x the median liquidity (the obvious heuristic: more TVL is safer)
- **With an agent:** pick the pool whose flow is not one-way — a balanced venue (synthetic), where §3.4's imbalance arm fires on 0.7% of samples against 96.3% on the other
- **Metric:** net return on capital of the same agent on the chosen venue, P25–P75

**No verdict.** baseline: 0 usable replays, assumption A5 requires 20; 60 window(s) were shorter than the 24h policy horizon; agent: 0 usable replays, assumption A5 requires 20; 60 window(s) were shorter than the 24h policy horizon

## What would make this stronger

- **A chain tape.** This run is `synthetic`, so nothing below rests on
  anything that happened. A synthetic tape can show the machinery runs; it
  cannot support a claim about a venue. Run `make advantage` against an
  indexed pool for a report that can.
- **A verdict.** Three tasks is three observations, and `tearsheet.verdict`
  refuses below thirty. The report says *no verdict* across all tasks and
  means it; the per-task bands are what it will stand behind.
- Every assumption behind these numbers is in [`ASSUMPTIONS.md`](ASSUMPTIONS.md);
  every deviation from the frozen spec, with its arithmetic, is in
  [`REQUIREMENTS_MATRIX.md`](REQUIREMENTS_MATRIX.md).

