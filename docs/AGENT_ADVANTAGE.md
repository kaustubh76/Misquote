# Agent Advantage Report

**Does hiring an agent beat doing the job yourself, and can we prove it?**

> **COUNTERFACTUAL — neither position was held.** Every position priced here is a replay, not a
> record. No capital was deployed. Published as assumption A6.

- **Tape:** `chain`
- **Capital per task:** 1 (quote token)
- **Tasks:** 6 · quotable 5 · withheld 1
- **Categories:** equities, security, trading

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
| Earn — fees on a liquidity position | trading | 8.94 – 16.35% | 20.70 – 36.15% | **+17.21pp** | agent beats DIY by 17.21pp, bands do not overlap |
| Market-make — quote both sides of a range | trading | 8.94 – 16.35% | 19.50 – 31.90% | **+12.71pp** | agent beats DIY by 12.71pp, bands do not overlap |
| Protect — avoid being picked off by one-way flow | security | 9.39 – 14.94% | -55.19 – -52.84% | **-68.55pp** | agent loses to DIY by 68.55pp, bands do not overlap |
| Choose — which pool to provide liquidity to | security | 5.84 – 16.52% | 5.84 – 16.52% | **+0.00pp** | indistinguishable: +0.00pp is below the 0.10pp materiality floor |
| Equities — provide liquidity to a tokenized stock | equities | withheld | withheld | withheld | no verdict — 85 swaps spanning 4.1 days on PancakeSwap v3 TSLAx/USDT 0.25%. Assumption A5 requires 20 replay windows of at least 24h; this tape yields at most 4. It is the only tokenized-equity pool on BNB Chain with any liquidity — NVDAx and AAPLx have no v3 pool at any fee tier, and the 1.00% TSLAx pool has none. So the venue is real, our engine prices it, and there is not enough flow through it to quote. Withheld rather than estimated. |
| Route — which lending venue to supply to | trading | 1.90 – 1.92% | 1.71 – 1.92% | **-0.01pp** | indistinguishable: -0.01pp is below the 0.10pp materiality floor |

**Across all tasks:** no verdict (5 observations, need 30)

That refusal is deliberate and it is the honest headline. `verdict()` will
not call a rate on fewer than 30 observations, and three tasks are three
observations. What carries the argument is each task's own quote, where the
sample is 20 sub-windows × 3 parameter perturbations rather than one run.

## Task detail

### Earn — fees on a liquidity position

- **Category:** trading · **Venue:** PancakeSwap v3 WBNB/USDT 0.05% · 0x36696169C63e42cd08ce11f5deeBbCeBae652050
- **Without an agent:** mint once at the same width, never touch it (passive_policy)
- **With an agent:** Warden — Avellaneda–Stoikov recentring
- **Metric:** net return on capital (fees − realized convexity cost − costs), P25–P75

- **Better on the quantity this task is named after** — fees earned: 0.0578309 vs 0.0156938 — 3.7x better

| | DIY | Agent |
|---|---|---|
| Net return P25–P75 | 8.94 – 16.35% | 20.70 – 36.15% |
| Median | 13.26% | 30.47% |
| Decisions somebody had to make | 1 | 0 |
| Decisions made for you | 0 | 20 |
| Replay compute (ours, not yours) | 1,630s | 4,500s |
| Fee to hire | none | 0.000755 BNB |
| In range | 36.6% | 93.9% |
| Fees | 0.0157 | 0.0578 |
| Realized convexity cost (upper bound on LVR) | 0.0108 | 0.0231 |
| Costs charged | 0.00 | 0.02 |
| Moves — mint / recentre / pull | 1 / 0 / 0 | 1 / 19 / 0 |
| Distinct results of 60 reported samples | 20 | 24 |

**agent beats DIY by 17.21pp, bands do not overlap**

Bands overlap: **no**. Non-overlapping bands are what lets the difference be stated at all.

### Market-make — quote both sides of a range

- **Category:** trading · **Venue:** PancakeSwap v3 WBNB/USDT 0.05% · 0x36696169C63e42cd08ce11f5deeBbCeBae652050
- **Without an agent:** mint once at the same width, never touch it (passive_policy)
- **With an agent:** Grid — fixed rung ladder, requote when price leaves it
- **Metric:** net return on capital (fees − realized convexity cost − costs), P25–P75

- **Better on the quantity this task is named after** — time in range: 0.999975 vs 0.366401 — 2.7x better

| | DIY | Agent |
|---|---|---|
| Net return P25–P75 | 8.94 – 16.35% | 19.50 – 31.90% |
| Median | 13.26% | 25.97% |
| Decisions somebody had to make | 1 | 0 |
| Decisions made for you | 0 | 13 |
| Replay compute (ours, not yours) | 1,630s | 5,437s |
| Fee to hire | none | 0.000755 BNB |
| In range | 36.6% | 100.0% |
| Fees | 0.0157 | 0.0484 |
| Realized convexity cost (upper bound on LVR) | 0.0108 | 0.0202 |
| Costs charged | 0.00 | 0.01 |
| Moves — mint / recentre / pull | 1 / 0 / 0 | 1 / 12 / 0 |
| Distinct results of 60 reported samples | 20 | 60 |

**agent beats DIY by 12.71pp, bands do not overlap**

Bands overlap: **no**. Non-overlapping bands are what lets the difference be stated at all.

### Protect — avoid being picked off by one-way flow

- **Category:** security · **Venue:** PancakeSwap v3 WBNB/USDT 0.05% · 0x36696169C63e42cd08ce11f5deeBbCeBae652050
- **Without an agent:** the same wide band, held through everything (withdrawal disabled)
- **With an agent:** Sentinel — withdraw on §3.4 toxicity, re-enter after m_clear
- **Metric:** net return on capital, P25–P75 (the cost of the withdrawals is charged in full)

- **Better on the quantity this task is named after** — realized convexity cost (upper bound on LVR): 0.00479899 vs 0.00854626 — 1.8x better

| | DIY | Agent |
|---|---|---|
| Net return P25–P75 | 9.39 – 14.94% | -55.19 – -52.84% |
| Median | 14.10% | -54.45% |
| Decisions somebody had to make | 2 | 0 |
| Decisions made for you | 0 | 1191 |
| Replay compute (ours, not yours) | 5,709s | 5,902s |
| Fee to hire | none | 0.000755 BNB |
| In range | 100.0% | 87.0% |
| Fees | 0.0195 | 0.0166 |
| Realized convexity cost (upper bound on LVR) | 0.0085 | 0.0048 |
| Costs charged | 0.00 | 0.05 |
| Moves — mint / recentre / pull | 1 / 1 / 0 | 596 / 0 / 595 |
| Distinct results of 60 reported samples | 20 | 20 |

**agent loses to DIY by 68.55pp, bands do not overlap**

Bands overlap: **no**. Non-overlapping bands are what lets the difference be stated at all.

<details><summary><strong>Where this number comes from</strong></summary>

Over 31.0 days the agent minted **596** times, pulled **595** times and recentred **0** times.

**It never recentred.** Every action was a pull followed by a re-mint — 595 complete cycles, **19.2 per day** against `max_rebalances_per_day = 8`. The budget is spent entirely on coming back.

That ordering is deliberate and documented: `core/policy.py` gates re-entry and never exit, because *an agent forbidden to leave because it had run out of budget would be held inside exactly the flow the rule exists to escape*. The consequence on real flow is that a toxicity rule firing often enough exhausts the day's budget on exits, and the agent then cannot afford to return — which is why it was in range **87.0%** of the time while moving 1191 times.

The cost of that is **5.4% of deployed capital** over the window, and fees covered **0.31x** of it. The baseline moved 2 time(s) and was charged 0.0015. The gap between the two columns is transaction cost, not strategy.

**So this task measures the parameters, not the idea.** Two open findings produce it, and neither was tuned to improve this number: **P-19**, which measures how often §3.4's imbalance arm fires and so how often the agent pulls, and **P-12**, which made the daily budget correctly persist across a pull and thereby exposed what that firing rate costs. Both are in [`REQUIREMENTS_MATRIX.md`](REQUIREMENTS_MATRIX.md), with **P-20** for this result itself.

</details>

### Choose — which pool to provide liquidity to

- **Category:** security · **Venue:** two venues: PancakeSwap v3 WBNB/USDT 0.05% · 0x36696169C63e42cd08ce11f5deeBbCeBae652050 vs PancakeSwap v3 WBNB/USDT 0.25% · 0x1401ff943D08a7E098328C1d3a9d388923B115D2 — depth and the flow screen chose the same one
- **Without an agent:** pick the deepest pool — PancakeSwap v3 WBNB/USDT 0.05% · 0x36696169C63e42cd08ce11f5deeBbCeBae652050, 84.0x the median liquidity (the obvious heuristic: more TVL is safer)
- **With an agent:** pick the pool whose flow is not one-way — PancakeSwap v3 WBNB/USDT 0.05% · 0x36696169C63e42cd08ce11f5deeBbCeBae652050, where §3.4's imbalance arm fires on 41.9% of samples against 42.9% on the other — which is the pool depth chose too
- **Metric:** net return on capital of the same agent on the chosen venue, P25–P75. Capital for this task is 0.03181, not the report's 1. A1's ceiling is eps x pool liquidity and therefore a property of the pool, and the shallower venue binds it — PancakeSwap v3 WBNB/USDT 0.05% · 0x36696169C63e42cd08ce11f5deeBbCeBae652050: 7.031 · PancakeSwap v3 WBNB/USDT 0.25% · 0x1401ff943D08a7E098328C1d3a9d388923B115D2: 0.06362 (at 0.5x margin). Both columns run at the same figure, because a comparison between two venues at two capitals is partly a comparison between two position sizes.

| | DIY | Agent |
|---|---|---|
| Net return P25–P75 | 5.84 – 16.52% | 5.84 – 16.52% |
| Median | 7.22% | 7.22% |
| Decisions somebody had to make | 15 | 0 |
| Decisions made for you | 0 | 15 |
| Replay compute (ours, not yours) | 5,551s | 5,551s |
| Fee to hire | none | 0.000755 BNB |
| In range | 98.4% | 98.4% |
| Fees | 0.0017 | 0.0017 |
| Realized convexity cost (upper bound on LVR) | 0.0007 | 0.0007 |
| Costs charged | 0.00 | 0.00 |
| Moves — mint / recentre / pull | 1 / 14 / 0 | 1 / 14 / 0 |
| Distinct results of 60 reported samples | 24 | 24 |

**indistinguishable: +0.00pp is below the 0.10pp materiality floor**

Bands overlap: **yes**. Overlapping bands mean the two are not distinguishable at this sample size, however far apart the medians sit — which is precisely why this product publishes ranges rather than a single number.

### Equities — provide liquidity to a tokenized stock

- **Category:** equities · **Venue:** PancakeSwap v3 TSLAx/USDT 0.25% · 0x5E12d6EdB2b7D5330e474ea2D2694A3b3E35d492
- **Without an agent:** mint once at the same width, never touch it (passive_policy)
- **With an agent:** Warden — Avellaneda–Stoikov recentring
- **Metric:** net return on capital (fees − realized convexity cost − costs), P25–P75

**No verdict.** 85 swaps spanning 4.1 days on PancakeSwap v3 TSLAx/USDT 0.25%. Assumption A5 requires 20 replay windows of at least 24h; this tape yields at most 4. It is the only tokenized-equity pool on BNB Chain with any liquidity — NVDAx and AAPLx have no v3 pool at any fee tier, and the 1.00% TSLAx pool has none. So the venue is real, our engine prices it, and there is not enough flow through it to quote. Withheld rather than estimated.

### Route — which lending venue to supply to

- **Category:** trading · **Venue:** Venus Core Pool (BSC) — vUSDT and vUSDC, verified three ways
- **Without an agent:** supply to the highest-rate venue once and never move (park_policy)
- **With an agent:** Router - move only when the rate edge clears the round-trip cost
- **Metric:** net return on supplied capital (realized yield - switch costs), P25-P75, over a 168h stated holding period. Capital for this task is $10,000 of stablecoin, not the report's figure — that one is denominated in WBNB and means nothing to a lending market.

- **Worse on the quantity this task is named after** — moves made (best rate seen 2.98%, hurdle 1.06%, break-even at 2 days): 2 vs 1 — worse

| | DIY | Agent |
|---|---|---|
| Net return P25–P75 | 1.90 – 1.92% | 1.71 – 1.92% |
| Median | 1.91% | 1.90% |
| Decisions somebody had to make | 1 | 0 |
| Decisions made for you | 0 | 2 |
| Replay compute (ours, not yours) | 3s | 3s |
| Fee to hire | none | 0.000755 BNB |
| Costs charged | 0.02 | 1.03 |

**indistinguishable: -0.01pp is below the 0.10pp materiality floor**

Bands overlap: **yes**. Overlapping bands mean the two are not distinguishable at this sample size, however far apart the medians sit — which is precisely why this product publishes ranges rather than a single number.

## What would make this stronger

- **A longer tape, and a second month.** Thirty days is one regime. The
  caveat that used to sit here — that free BSC endpoints refuse a multi-day
  backfill, so the word *real* had not been earned — is no longer true and
  has been removed: both venues are indexed from chain over the same
  5,802,928 blocks, and `make go-no-go` checks the coverage rather than the
  span. What a keyed `BSC_RPC_URL` buys now is speed, not honesty.
- **A verdict.** Three tasks is three observations, and `tearsheet.verdict`
  refuses below thirty. The report says *no verdict* across all tasks and
  means it; the per-task bands are what it will stand behind.
- Every assumption behind these numbers is in [`ASSUMPTIONS.md`](ASSUMPTIONS.md);
  every deviation from the frozen spec, with its arithmetic, is in
  [`REQUIREMENTS_MATRIX.md`](REQUIREMENTS_MATRIX.md).

