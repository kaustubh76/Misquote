# Agent Advantage Report

**Does hiring an agent beat doing the job yourself, and can we prove it?**

> **COUNTERFACTUAL — neither position was held.** Every position priced here is a replay, not a
> record. No capital was deployed. Published as assumption A6.

- **Tape:** `chain`
- **Capital per task:** 1 (quote token)
- **Tasks:** 4 · quotable 4 · withheld 0
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
| Earn — fees on a liquidity position | trading | 4.78 – 27.21% | -52.10 – -49.97% | **-64.29pp** | agent loses to DIY by 64.29pp, bands do not overlap |
| Protect — avoid being picked off by one-way flow | security | 9.38 – 14.94% | -24.16 – -23.85% | **-38.17pp** | agent loses to DIY by 38.17pp, bands do not overlap |
| Choose — which pool to provide liquidity to | security | -620.55 – -617.83% | -620.55 – -617.83% | **+0.00pp** | indistinguishable: +0.00pp is below the 0.10pp materiality floor |
| Route — which lending venue to supply to | trading | 1.90 – 1.92% | 1.71 – 1.92% | **-0.01pp** | indistinguishable: -0.01pp is below the 0.10pp materiality floor |

**Across all tasks:** no verdict (4 observations, need 30)

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

- **Worse on the quantity this task is named after** — fees earned: 0.00994223 vs 0.0175265 — worse

| | DIY | Agent |
|---|---|---|
| Net return P25–P75 | 4.78 – 27.21% | -52.10 – -49.97% |
| Median | 13.05% | -51.24% |
| In range | 6.6% | 6.1% |
| Fees | 0.0175 | 0.0099 |
| Realized convexity cost (upper bound on LVR) | 0.0177 | 0.0026 |
| Costs charged | 0.00 | 0.05 |
| Moves — mint / recentre / pull | 1 / 0 / 0 | 249 / 0 / 249 |
| Distinct results of 60 reported samples | 40 | 40 |

**agent loses to DIY by 64.29pp, bands do not overlap**

Bands overlap: **no**. Non-overlapping bands are what lets the difference be stated at all.

<details><summary><strong>Where this number comes from</strong></summary>

Over 31.0 days the agent minted **249** times, pulled **249** times and recentred **0** times.

**It never recentred.** Every action was a pull followed by a re-mint — 249 complete cycles, **8.0 per day** against `max_rebalances_per_day = 8`. The budget is spent entirely on coming back.

That ordering is deliberate and documented: `core/policy.py` gates re-entry and never exit, because *an agent forbidden to leave because it had run out of budget would be held inside exactly the flow the rule exists to escape*. The consequence on real flow is that a toxicity rule firing often enough exhausts the day's budget on exits, and the agent then cannot afford to return — which is why it was in range **6.1%** of the time while moving 498 times.

The cost of that is **4.7% of deployed capital** over the window, and fees covered **0.21x** of it. The baseline moved 1 time(s) and was charged 0.0008. The gap between the two columns is transaction cost, not strategy.

**So this task measures the parameters, not the idea.** Two open findings produce it, and neither was tuned to improve this number: **P-19**, which measures how often §3.4's imbalance arm fires and so how often the agent pulls, and **P-12**, which made the daily budget correctly persist across a pull and thereby exposed what that firing rate costs. Both are in [`REQUIREMENTS_MATRIX.md`](REQUIREMENTS_MATRIX.md), with **P-20** for this result itself.

</details>

### Protect — avoid being picked off by one-way flow

- **Category:** security · **Venue:** PancakeSwap v3 WBNB/USDT 0.05% · 0x36696169C63e42cd08ce11f5deeBbCeBae652050
- **Without an agent:** the same wide band, held through everything (withdrawal disabled)
- **With an agent:** Sentinel — withdraw on §3.4 toxicity, re-enter after m_clear
- **Metric:** net return on capital, P25–P75 (the cost of the withdrawals is charged in full)

- **Better on the quantity this task is named after** — realized convexity cost (upper bound on LVR): 0.000464581 vs 0.00854537 — 18.4x better

| | DIY | Agent |
|---|---|---|
| Net return P25–P75 | 9.38 – 14.94% | -24.16 – -23.85% |
| Median | 14.10% | -24.07% |
| In range | 100.0% | 9.5% |
| Fees | 0.0195 | 0.0017 |
| Realized convexity cost (upper bound on LVR) | 0.0085 | 0.0005 |
| Costs charged | 0.00 | 0.02 |
| Moves — mint / recentre / pull | 1 / 1 / 0 | 249 / 0 / 249 |
| Distinct results of 60 reported samples | 20 | 20 |

**agent loses to DIY by 38.17pp, bands do not overlap**

Bands overlap: **no**. Non-overlapping bands are what lets the difference be stated at all.

<details><summary><strong>Where this number comes from</strong></summary>

Over 31.0 days the agent minted **249** times, pulled **249** times and recentred **0** times.

**It never recentred.** Every action was a pull followed by a re-mint — 249 complete cycles, **8.0 per day** against `max_rebalances_per_day = 8`. The budget is spent entirely on coming back.

That ordering is deliberate and documented: `core/policy.py` gates re-entry and never exit, because *an agent forbidden to leave because it had run out of budget would be held inside exactly the flow the rule exists to escape*. The consequence on real flow is that a toxicity rule firing often enough exhausts the day's budget on exits, and the agent then cannot afford to return — which is why it was in range **9.5%** of the time while moving 498 times.

The cost of that is **2.0% of deployed capital** over the window, and fees covered **0.09x** of it. The baseline moved 2 time(s) and was charged 0.0015. The gap between the two columns is transaction cost, not strategy.

**So this task measures the parameters, not the idea.** Two open findings produce it, and neither was tuned to improve this number: **P-19**, which measures how often §3.4's imbalance arm fires and so how often the agent pulls, and **P-12**, which made the daily budget correctly persist across a pull and thereby exposed what that firing rate costs. Both are in [`REQUIREMENTS_MATRIX.md`](REQUIREMENTS_MATRIX.md), with **P-20** for this result itself.

</details>

### Choose — which pool to provide liquidity to

- **Category:** security · **Venue:** two venues: PancakeSwap v3 WBNB/USDT 0.05% · 0x36696169C63e42cd08ce11f5deeBbCeBae652050 vs PancakeSwap v3 WBNB/USDT 0.25% · 0x1401ff943D08a7E098328C1d3a9d388923B115D2 — depth and the flow screen chose the same one
- **Without an agent:** pick the deepest pool — PancakeSwap v3 WBNB/USDT 0.05% · 0x36696169C63e42cd08ce11f5deeBbCeBae652050, 84.0x the median liquidity (the obvious heuristic: more TVL is safer)
- **With an agent:** pick the pool whose flow is not one-way — PancakeSwap v3 WBNB/USDT 0.05% · 0x36696169C63e42cd08ce11f5deeBbCeBae652050, where §3.4's imbalance arm fires on 41.9% of samples against 42.8% on the other — which is the pool depth chose too
- **Metric:** net return on capital of the same agent on the chosen venue, P25–P75. Capital for this task is 0.03181, not the report's 1. A1's ceiling is eps x pool liquidity and therefore a property of the pool, and the shallower venue binds it — PancakeSwap v3 WBNB/USDT 0.05% · 0x36696169C63e42cd08ce11f5deeBbCeBae652050: 7.031 · PancakeSwap v3 WBNB/USDT 0.25% · 0x1401ff943D08a7E098328C1d3a9d388923B115D2: 0.06362 (at 0.5x margin). Both columns run at the same figure, because a comparison between two venues at two capitals is partly a comparison between two position sizes.

| | DIY | Agent |
|---|---|---|
| Net return P25–P75 | -620.55 – -617.83% | -620.55 – -617.83% |
| Median | -619.71% | -619.71% |
| In range | 6.1% | 6.1% |
| Fees | 0.0003 | 0.0003 |
| Realized convexity cost (upper bound on LVR) | 0.0001 | 0.0001 |
| Costs charged | 0.02 | 0.02 |
| Moves — mint / recentre / pull | 249 / 0 / 249 | 249 / 0 / 249 |
| Distinct results of 60 reported samples | 40 | 40 |

**indistinguishable: +0.00pp is below the 0.10pp materiality floor**

Bands overlap: **yes**. Overlapping bands mean the two are not distinguishable at this sample size, however far apart the medians sit — which is precisely why this product publishes ranges rather than a single number.

<details><summary><strong>Where this number comes from</strong></summary>

Over 31.0 days the agent minted **249** times, pulled **249** times and recentred **0** times.

**It never recentred.** Every action was a pull followed by a re-mint — 249 complete cycles, **8.0 per day** against `max_rebalances_per_day = 8`. The budget is spent entirely on coming back.

That ordering is deliberate and documented: `core/policy.py` gates re-entry and never exit, because *an agent forbidden to leave because it had run out of budget would be held inside exactly the flow the rule exists to escape*. The consequence on real flow is that a toxicity rule firing often enough exhausts the day's budget on exits, and the agent then cannot afford to return — which is why it was in range **6.1%** of the time while moving 498 times.

**This is a finding about the pool, not about the agent.** The position is 0.03181 because that is what assumption A1 permits on the shallower of the two venues — A1's ceiling is `eps x pool_liquidity` and therefore a property of the pool, and a quote that breaches it is *refused rather than rendered*. Transaction costs, however, are fixed per action and do not shrink with the position.

So at the largest size this venue's own liquidity allows, fixed costs exceed any plausible fee income by **50x**. That is the due-diligence answer to *which pool should I provide liquidity to*: **not this one, at any size it can support.** The percentage is large and negative because it is a small denominator, and both columns share it, which is why the delta is still sound.

The cost of that is **50.1% of deployed capital** over the window, and fees covered **0.02x** of it. The baseline moved 498 time(s) and was charged 0.0159. The gap between the two columns is transaction cost, not strategy.

**So this task measures the parameters, not the idea.** Two open findings produce it, and neither was tuned to improve this number: **P-19**, which measures how often §3.4's imbalance arm fires and so how often the agent pulls, and **P-12**, which made the daily budget correctly persist across a pull and thereby exposed what that firing rate costs. Both are in [`REQUIREMENTS_MATRIX.md`](REQUIREMENTS_MATRIX.md), with **P-20** for this result itself.

</details>

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
| In range | 0.0% | 0.0% |
| Fees | 0.0000 | 0.0000 |
| Realized convexity cost (upper bound on LVR) | 0.0000 | 0.0000 |
| Costs charged | 0.02 | 1.03 |
| Moves — mint / recentre / pull | 0 / 0 / 0 | 0 / 0 / 0 |
| Distinct results of 60 reported samples | 0 | 0 |

**indistinguishable: -0.01pp is below the 0.10pp materiality floor**

Bands overlap: **yes**. Overlapping bands mean the two are not distinguishable at this sample size, however far apart the medians sit — which is precisely why this product publishes ranges rather than a single number.

<details><summary><strong>Where this number comes from</strong></summary>

Over 17.0 days the agent minted **0** times, pulled **0** times and recentred **0** times.

The cost of that is **0.0% of deployed capital** over the window, and fees covered **0.00x** of it. The baseline moved 1 time(s) and was charged 0.0152. The gap between the two columns is transaction cost, not strategy.

**So this task measures the parameters, not the idea.** Two open findings produce it, and neither was tuned to improve this number: **P-19**, which measures how often §3.4's imbalance arm fires and so how often the agent pulls, and **P-12**, which made the daily budget correctly persist across a pull and thereby exposed what that firing rate costs. Both are in [`REQUIREMENTS_MATRIX.md`](REQUIREMENTS_MATRIX.md), with **P-20** for this result itself.

</details>

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

