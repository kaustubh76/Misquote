# The Assumption Sheet

**This file is a product surface, not a note.** It renders in the UI, one click from every quote.
Rule 6: every displayed number must trace to a chain query or to an entry on this sheet.
If it can't, it doesn't render.

Read this the way you'd read the footnotes of a fund factsheet — except these footnotes are the point.
A quote you can't argue with isn't honest, it's just confident.

---

## A1 · Our liquidity is small enough not to move the price we're replaying

`L_h ≤ ε · L_pool` with **ε = 1%**. Historical swap prices are treated as unperturbed by the
hypothetical position.

*Why it matters:* a replayed position large enough to change the pool price would change the very
swaps it claims to have earned fees on. The 1% cap keeps that effect below the noise floor. Quotes
that would breach ε are refused rather than rendered.

## A2 · Fees are pro-rated by liquidity share; JIT competition is not modeled

Fees credited to a hypothetical position are its share of the fee-generating swap, pro-rated by
liquidity. Just-in-time liquidity — a competitor minting a large position inside one block to capture
a specific large swap — is **not** modeled.

*Direction of the error:* this **overstates** our fees in the presence of JIT competition. It is the
one assumption on this sheet that flatters us, and it is disclosed for that reason.

## A3 · Every decision uses trailing data only

At each decision time `t`, every estimator has seen only events with timestamp `≤ t`.

*How it's enforced:* not by review. Estimators hard-assert on ingest and raise `LookAheadError` on any
event newer than the decision time, unconditionally, in both the live and the replay driver. The tape
itself cannot return future events — its accessor bounds the query with a SQL parameter, so there is
no in-memory future to leak. This is test **T3**, and it is code.

## A4 · MEV haircut of 10 bps per rebalance; gas at historical block prices

Every simulated rebalance is charged **10 bps of rebalanced notional** as an MEV haircut, plus gas at
the gas price prevailing in the historical block, plus modeled slippage against the pool's actual
liquidity at that moment.

*Why a flat 10 bps:* a sandwich's true cost depends on the searcher's inventory and the block
builder's ordering, neither of which is observable after the fact. A fixed, conservative, disclosed
number beats a precise-looking model of something unmeasurable. Fixed for the hackathon.

## A5 · Quotes are ranges, never point estimates

Every quote is a **P25–P75 range** over `K ≥ 20` rolling sub-windows and a **±25% perturbation of
(γ, κ)**.

*Why:* a single number implies a precision the data does not support. Display reads
"would have captured $150–$210 net", and the range widens honestly when the history is thin or the
parameter fit is poor. A quote engine that returns a point estimate is misquoting you — which is the
entire thesis of the product.

## A7 · The volatility estimator does two things the spec doesn't mention

**Added.** Spec §5.1 specifies "EWMA of 1-minute log-returns of pool price, half-life 6h, scaled to
per-√hour". The implementation adds two transforms, both of which change the number materially, so
both are disclosed here rather than buried in a docstring.

**Winsorising** clips each return at 5× the median absolute return. A thin-liquidity pool can print
one swap that moves price several percent and immediately reverts; left alone that single bar
dominates a six-hour EWMA and the agent widens its range for the rest of the day on the strength of
one trade. The threshold is median-based rather than standard-deviation-based on purpose — a
standard deviation would itself be inflated by the outlier it is meant to clip.

**Shrinkage toward a prior of σ = 0.02** with weight `n/(n+20)`. This is *not* a small correction: at
the 30-bar readiness threshold the published σ is only 41% of the way from the prior to the sample
estimate. It stops the first hour after a restart producing a confidently wrong volatility, at the
cost of biasing thin-sample estimates toward the prior. The prior itself implies roughly 190%
annualised, which is hot for BNB (typically 50–70%), so the standing bias is toward **wider** ranges.

**Irregular sampling is handled explicitly.** Bars exist only where a swap arrived, so consecutive
bars can be an hour apart. Each return is rescaled to its per-bar equivalent (`r/√span`) and the EWMA
decay ages by elapsed time (`decay^span`), because variance is additive in time. Without this a pool
trading once an hour reported *identical* volatility to one making the same moves every minute —
measured, not hypothesised.

## A8 · The κ estimator fits a form the data does not have

**Added.** Spec §5.2 fits `ln(rate) = ln A − κδ` — an exponential decay of swap frequency with tick
depth. For a random walk, excursion frequency decays as a **power law (δ⁻²)**, not exponentially.
Fitting an exponential to simulated Brownian data yields **r² ≈ 0.84**, which comfortably clears the
spec's own r² ≥ 0.5 gate while being the wrong functional form. So κ is not a stable parameter: its
value depends on which depth range happens to be bucketed.

There is a deeper mismatch. In Avellaneda–Stoikov, λ(δ) is the rate at which *an order you placed at
depth δ* gets hit. A liquidity provider places no order at a chosen depth; it is filled continuously
at every depth inside its range. So equation (2)'s second term may be substantially re-measuring
volatility rather than providing an independent fill-rate trade-off.

**Every card that uses κ shows its r² and whether the fallback was used.** We treat κ as a labelled
weak parameter rather than a measured one. The honest summary: the range width is driven mainly by
the volatility term, and the κ term is a disclosed approximation.

**Confirmed on real history, 17 Aug 2026 — the prediction above was exact.** Fitting κ on the 30-day
WBNB/USDT tape (252,923 swaps, no gaps) gives **κ = 3600.91 per log-price with r² = 0.847 over 8,096
swaps**, published as gap item **G-4**. That r² is *the same number this paragraph predicted pure
Brownian noise would produce*, to two decimal places. So the fit clears §5.2's r² ≥ 0.5 gate on real
data exactly as it would on data containing no information at all, which is the clearest possible
demonstration that **the r² is not evidence the functional form is right** — it is evidence only
that a straight line fits a decaying curve tolerably over a short range.

Two things follow, and they point in opposite directions, so both are published:

- **The default is better than it was.** It is now derived from the pool it is used on rather than
  from an order-of-magnitude guess, and the guess was **low by 7.2×** — a low κ widens the range, so
  every quote produced before this was wider than the pool's own fill behaviour supports.
- **It is no more trustworthy as a parameter.** Nothing here rescues the functional form, and the
  deeper mismatch above — that an LP places no order at a chosen depth — is untouched by having
  measured the wrong thing more carefully.

## A9 · Equation (2) prices no adverse selection

**Added.** Baseline Avellaneda–Stoikov assumes the mid is an exogenous martingale and that fill
intensity is uninformed — there is no adverse-selection term anywhere in the optimal-spread formula.
On a venue where the dominant flow is arbitrage, which spec §3.4 explicitly identifies, this means
the widths equation (2) produces are systematically **too narrow**: they price inventory risk and
fill rate, but never the cost of being picked off.

The toxicity pull (§3.4) and the realized-LVR accounting (§4) address this after the fact rather than
in the width itself. Alongside A2, this is the second assumption on this sheet that does not flatter
us.

## A10 · What we call LVR is an upper bound on it

**Added.** Spec equation (3) computes `LVR_k = −(Δy_k + P_k·Δx_k)` and it is
non-negative for *every* swap, regardless of who traded or why. That guarantee is
the tell: a real adverse-selection measure would distinguish an informed
arbitrageur from a noise trader, and this one cannot, because it assumes the
post-swap **pool** price is fair.

The consequence is concrete. On a round trip `P₀ → P₁ → P₀` the position ends
exactly where it started and collected two fees, yet equation (3) books a loss on
both legs. So in a churny pool the figure folds reversion round trips into what it
calls adverse selection and **overstates** it.

We report it anyway, because it is model-free, it is computed per swap with a
`tx` you can open on BscScan, and it errs against us rather than for us. But it is
labelled **"realized convexity cost (upper bound on LVR)"** and never simply
"LVR". Where a CEX price is available — which §3.4 already fetches for the
toxicity signal — a second series measured against that price is LVR proper and
can take either sign.

## A11 · Fees are prorated by how much of a swap happened inside the range

**Added.** Uniswap v3 accrues fees to whichever ticks are active as price sweeps
through them. A swap that starts inside our range and exits it should pay us for
the part that was inside and nothing for the part that was not.

The implementation prorates by the fraction of the price move (in √P space) that
fell within the position's bounds. That is exact when the pool's active liquidity
is constant across the swap and an approximation when the swap crosses ticks
where other positions start or end. The error is bounded by how much liquidity
changes mid-swap and, on the deepest pool on BSC, is small — but it is an
approximation and is named as one.

The protocol's share is *not* approximated: Pancake's Swap event reports the
exact amount it took, so that part is read from chain per swap.

## A12 · Router quotes a realized rate, never a quoted one

**Added.** Venus exposes `supplyRatePerBlock()`, a per-block mantissa. Turning it into an APR needs a
blocks-per-year constant, and **that constant is not readable from chain**: the market's own
`interestRateModel()` reverts on `blocksPerYear()`, `getBlocksPerYear()`, `blocksOrSecondsPerYear()`
and `isTimeBased()` alike, and the Comptroller is an EIP-2535 diamond whose reverts prove nothing
about what it implements.

Measured on vUSDT, 21 Aug 2026, mantissa 308,220,494:

| assumed blocks/year | implied supply APR |
|---|---|
| 10,512,000 — Venus's documented 3-second blocks | **0.324%** |
| 31,536,000 — one second | 0.972% |
| 42,048,000 — 0.75 s | 1.296% |
| 70,080,000 — 0.45 s | **2.160%** |

A **6.67× spread**, entirely from a constant, landing on the number a yield router sorts by.

So Router does not read a rate. It differences the `borrowIndex` accumulator between two accruals,
which needs no constant at all — only two block timestamps the indexer already fetches:

```
growth      = borrowIndex₁ / borrowIndex₀ − 1
utilisation = totalBorrowsPrior / (cashPrior + totalBorrowsPrior)
supply_apr  = growth × utilisation × (1 − reserveFactor) × SECONDS_PER_YEAR / dt
```

**The two methods agree, and that is the check.** Realized supply APR measured across four window
widths on vUSDT: 2.1583% (500 blocks), 2.1599% (2,000), 2.1594% (4,000), 2.1590% (4,999) — stable to
within 0.002pp across a tenfold change in window, against a consistently measured **0.450 s/block**.
The realized 2.159% and the quoted-at-0.45s 2.160% agree to three decimal places, which is what makes
either trustworthy and which constant is right. The estimator's own test replays 172 real
`AccrueInterest` logs and gets 2.1554%.

*What is assumed rather than measured:* that the trailing window is informative about the next
interval. A rate is not a constant, and the estimate is backward-looking by construction.

## A13 · The switching boundary is myopic break-even, widened by a stated margin

**Added.** The optimal boundary under a mean-reverting rate spread is strictly wider than break-even:
paying to chase an edge that is about to close is a real loss, and the option to move later has value.
Solving that free boundary needs a model of the spread this repository has not fitted and cannot fit
honestly on a seven-day tape.

So Router compares the edge against `cost × (1 + switch_cost_margin)`, annualised over a stated
horizon, and additionally requires the edge to persist for `persistence_samples` consecutive samples.
Both are a **stated approximation** of that widening, not a derivation of it — the same shape as A9,
which records that equation (2) prices no adverse selection.

*The consequence, published rather than hidden — and corrected twice:*

This paragraph used to restate Router's result in prose, and was wrong within a
day, twice. First it said the boundary was **never** crossed with a 16.4-day
break-even — an artefact of two unmeasured cost constants (**P-25**). Then it
said the agent enters once and never switches, which stopped being true the
moment the rate tape grew from seven days to sixteen and the venues changed
leadership.

So the numbers are no longer here. The judges' brief carries them in a block
regenerated by `make judges` from the card itself, and the card is
Router's own card. What this assumption is *about* does
not move: the boundary is myopic break-even widened by a published margin, the
edge must persist, and a move must clear a cooldown and a daily budget.

Lowering the margin until the agent trades would still be the fitting this project exists to refuse.
Correcting a constant that was never measured is the opposite of that, and the direction it moved
the result is not evidence either way.

## A14 · What a venue switch costs, and where each part of it comes from

**Added.** Router's hurdle is `(2 x gas + notional x fee) x (1 + margin)`, annualised over the stated
horizon. Every input is a reading or a labelled fallback:

| input | value | source |
|---|---|---|
| swap fee | **1 bp** | `fee()` on the verified PancakeSwap USDT/USDC 0.01% pool, `0x92b7807b…3121` |
| gas units | 250,000 | **stated**, not measured — a Compound-fork `mint`/`redeem` writes far less state than a v3 burn-collect-mint, and measuring it needs a transaction this project will not send |
| gas price | 0.05 gwei | `eth_gasPrice`, through the indexer's endpoint rotation; falls back to the measured prevailing rate and says so |
| BNB in dollars | 607.31 | the swap tape's last observation of the verified WBNB/USDT pool — gas is priced in BNB and this agent's books are in dollars, and something has to bridge them |

The card carries the resulting `basis` string and a `derived` flag, so a reader can tell a measured
cost from a fallback one. `SwitchCost` has **no default constructor**: the two defaults it used to
have decided every figure Router published.

*What is assumed rather than measured:* the gas-unit count, and that a $10,000 swap on a pool holding
3.7e28 of liquidity moves the price by less than the fee — true by a wide margin here, and it would
stop being true on a thin pair.

## A6 · Showcase Mode is a labeled counterfactual

**Added.** The showcase position **was not held.** The pool history is real, every swap traces to a
BscScan transaction, and the capital figure is real — it is the documented NAV from an auditable BSC
mainnet trading record (237 journal rows, 2026-06-08 → 2026-06-27, wallet
`0xE8A30d24BbA030D3e8a844bD1c4F6e1374EA6215`). But that record is spot trading, not liquidity
provision. **No historical LP position exists to replay**, so the position is simulated over real
history and badged **COUNTERFACTUAL** on the card.

*Why this is disclosed rather than quietly finessed:* the alternative was to imply a position history
that does not exist, on a product whose entire claim is that other marketplaces do exactly that. See
D-2.

The synthetic borrower used for the health story is separately and clearly labeled as synthetic.

---

## Parameters

Every value the policy uses, with its default. Values marked ★ are user-selectable; the rest are
fixed and published.

| Parameter | Symbol | Default | Source |
|---|---|---|---|
| Risk aversion ★ | γ | **0.8** (conservative) | spec §8; selectable {0.4, 0.8, 1.5} |
| Replay liquidity cap | ε | **1%** | A1 |
| Recenter drift threshold | θ | **0.5** × half-width | spec §8 |
| Rebalance cooldown | τ_cool | **2h** | spec §8, anti-churn |
| Minimum half-width (dust) | w_min | **4 × tick spacing** | spec §8, anti-dust |
| Minimum half-width (volatility) | — | **σ√T at the InRange floor** → 1.4395σ, 72 ticks on the flagship | **A18** — derived from N below, not chosen |
| Maximum half-width | `w_max_price_band` | **±25% of price** (2,231 ticks) | **A18** — σ√T overstates a reverting excursion |
| MEV haircut | h | **10 bps** | A4 |
| Toxicity z-threshold (fallback) | z_pull | **2.5** | spec §8 — used for the first 2,000 readings only |
| Toxicity z-threshold (operative) | `z_pull_quantile` | **95th percentile of trailing \|z\|** | **A16** — the spec's constant fires on 41.94% of real samples |
| Toxic samples to pull | m | **3** | spec §8 |
| Clear samples to re-enter | m_clear | **10** | spec §8 |
| Signal sample interval | Δs | **5s** | spec §8 |
| Replay sub-windows | K | **≥ 20** | A5 |
| Max rebalances per day | — | **8** | spec §8, gas discipline |
| Max re-entries per day | `max_reentries_per_day` | **24** | **A16** — returning from a pull is not the churn §8's cap was written against (P-20) |
| Imbalance window | M | **50 swaps** | **G-1** — unspecified in spec, proposed here |
| Arbitrage round-trip cost | arb_cost_bps | **5 bps** | **G-2** — unspecified in spec, proposed here |
| InRange floor | N | **70%** | **G-3** — unspecified in spec, proposed here; **A18** also derives w_min from it |
| σ estimator | — | EWMA of 1-min log returns, **6h half-life**, per-√hour | spec §5.1 |
| κ estimator | — | least squares on trailing **7d** swap depth buckets, refit daily | spec §5.2 |
| κ fallback trigger | — | **r² < 0.5** → κ_default, **labeled on the card** | spec §5.2 |

*A note on `arb_cost_bps`.* It is the **arbitrageur's** round-trip cost in §3.4's toxicity test, and
it is numerically the same 5.0 that P-25 removed from Router's cost model. The two are unrelated:
one is what an arbitrageur pays to pick off a range, the other was a swap fee copied from the wrong
pool. Router's fee is **1 bp**, read from the pool it actually swaps through.

### Router's parameters

Published for the same reason the table above is: Router's card renders every one of these, and
rule 6 says a displayed number must trace to a chain query or to an entry on this sheet. It did not,
for a whole round.

| Parameter | Field | Default | Source |
|---|---|---|---|
| Horizon ★ | `horizon_hours` | **168h** | how long capital is committed; the hurdle is amortised over it |
| Cost margin | `switch_cost_margin` | **1.0** | **A13** — the stated stand-in for a free-boundary solve |
| Persistence | `persistence_samples` | **3** | **A13**; mirrors `m_toxic`'s streak shape |
| Switch cooldown | `cooldown_s` | **21,600** (6h) | anti-churn — and **not** the 2h `τ_cool` above |
| Max switches/day | `max_switches_per_day` | **4** | gas discipline — and **not** the 8 above |
| Rate sample floor | `min_apr_samples` | **30** | the same floor `verdict(min_n=30)` sets |
| Market share cap | `eps_market_share` | **1%** | **A1**'s analogue, on supplied base |

| Cost input | Field | Value | Source |
|---|---|---|---|
| Swap fee | `slippage_bps` | **1 bp** | **A14** — `fee()` on the verified USDT/USDC 0.01% pool |
| Gas per transaction | `gas_quote` | derived | **A14** — gas units × `eth_gasPrice` × BNB/USD |
| Gas units | — | **250,000** | **A14**, stated not measured — measuring needs a transaction nothing here will send |
| Fell back? | `derived` | on the card | **A14** — a fallback says so rather than passing as a reading |

### Estimator fits

Each rendered quote carries its actual fitted values in the tearsheet appendix: σ, κ, the κ fit's r²,
and whether the κ fallback was used. **A quote computed with a fallback κ says so on the card.**

---

## Target pool

| | |
|---|---|
| Pool | PancakeSwap v3 **WBNB/USDT, 0.05% fee tier** |
| Chain | BSC mainnet (56) |
| Address | [`0x36696169C63e42cd08ce11f5deeBbCeBae652050`](https://bscscan.com/address/0x36696169C63e42cd08ce11f5deeBbCeBae652050) |
| token0 / token1 | USDT `0x55d3…7955` / WBNB `0xbb4C…095c`, **both 18 decimals** |
| Tick spacing | 10 → `w_min` = **40 ticks** |
| Verified | 2026-08-13, block 115,653,558, against chain |

Every address the system points at was checked three ways on-chain — bytecode present, its interface
answers, and its answers agree with the other contracts' — rather than copied from documentation. Run
`make vet-addresses CHAIN=56` to reproduce.

**Note on decimals.** BSC's USDT is an 18-decimal token, unlike Ethereum's 6-decimal USDT. The value
is read from `decimals()` rather than assumed, because assuming 6 would misprice every position by
twelve orders of magnitude.

### The protocol fee: an LP does not keep 0.05%

**PancakeSwap's protocol fee is on by default. Uniswap's is not.** Read from this pool's `slot0` on
2026-08-13: `feeProtocol = 3400` in both directions, so **the protocol takes 34% and liquidity
providers keep 66%.**

| | |
|---|---|
| Nominal fee tier | 0.05% |
| Protocol share | 34% |
| **What an LP actually earns** | **0.033%** |

Every fee number this product displays is computed on 0.033%, not 0.05%. Reconstructing fees from
swap volume times the fee tier — the natural way to write a replay engine, and what most analytics
do — overstates LP earnings by a factor of **1.52**, and that error lands directly on NetFeeAPR,
which is the headline figure on every card. The value is settable per pool by governance, so it is
read from chain rather than hardcoded, and fee growth read from `feeGrowthInside` is already net of
it (the two paths must not both apply the deduction).

**Testnet mirror.** Burn-in runs on chapel's **WBNB/BUSD 0.05%** pool
([`0xEF15…d11d`](https://testnet.bscscan.com/address/0xEF1509b7feF4a7dFc94c45Fe9AF2028CA083d11d)),
not WBNB/USDT: chapel's WBNB/USDT pool at this tier exists but was initialized at `MAX_TICK` and
never seeded, so it holds zero liquidity. The mirror shares the fee tier, and therefore the tick
spacing and `w_min`, so a range computed on chapel is structurally the range that will be computed on
mainnet.

*Why this pool:* deepest BSC v3 pool, so the κ fit in §5.2 has the best chance of clearing its r² ≥ 0.5
bar on real data, and the swap stream is dense enough for the toxicity imbalance signal to mean
something. The CEX leg for the gap signal is Binance `bnbusdt@bookTicker`, a public WebSocket with no
API key.

**Non-goal, recorded deliberately:** Warden does **not** stake positions into MasterChefV3 for CAKE
emissions. Staking transfers NFT ownership and adds a withdrawal path that complicates the kill
switch, and emission rewards would contaminate the "fee APR net of realized LVR" metric with a number
that isn't a fee.

---

## A15 · An interactive quote runs fewer windows than a published card

**Added.** The quote path defaults to **20** rolling sub-windows, and every card on
this site is quoted at that budget. A quote requested from `/quote` runs **8**.

*Why:* the measured cost of the full budget on the 30-day WBNB/USDT tape is 60 replays of ~125,700
events each — **4.6 hours** for the four agents the showcase runs, recorded in `quote()`'s own
docstring. A surface where a stranger can ask for a replay cannot spend that per request, and the
alternative to a smaller budget is not a faster quote, it is no quote at all.

*Direction of the error:* **toward refusing**, which is the safe direction. Fewer windows means
fewer observations against the same floors — `MIN_SAMPLES` and the 30-observation verdict floor do
not move — so a reduced run is more likely to be withheld and, when it does quote, quotes a **wider**
P25–P75 than the full budget would. It cannot manufacture a narrow range out of a thin one.

*How you can tell:* every interactive result carries `interactive_budget: true` and the window count
it actually ran. The published cards do not, because they did not. The two are different
measurements and must not be compared without that flag being read — a reduced range next to a full
one looks like disagreement between the agents when it is disagreement between the budgets.

*What does not change:* the windows themselves, the perturbations, the floors, and every assumption
above. This entry is about how many times the same arithmetic is run, not about the arithmetic.

## A16 · The imbalance pull is calibrated to its own distribution, not to 2.5

**Changed.** Spec §3.4's second arm fires when `|z| > z_pull`, with §8 setting `z_pull = 2.5`. That
reads like a two-and-a-half-sigma event. It is not one, and the estimator's own docstring says why:
`z = Σs / √Σs²` is a **permutation-null statistic bounded by √M**, not a normal score. Under that
null it is not N(0,1) in small samples, so a threshold chosen as though it were is a number correct
for a quantity that is not the one it is applied to.

*What it cost:* measured over 252,874 samples of the flagship pool, the median `|z|` is **2.179** —
so the rule fires on **41.94%** of samples, and on **42.8%** of a pool eighty-four times shallower
(P-19, P-23). A screen that fires on two samples in five is not selecting; it is describing BSC.
Downstream, Warden withdrew and re-minted 249 times in 30 days, held a position 6.1% of the window,
and paid gas equal to 55% of deployed capital.

*The change:* the threshold is now the **trailing quantile of `|z|` measured on the same pool by the
same estimator** — `z_pull_quantile`, default the 95th percentile — over a window equal to the
policy's own `window_hours`. `z_pull` remains the fallback for the first 2,000 readings, so the
spec's number still traces to something and the rule is defined from the first sample. The reading
and the bar it was judged against are both recorded on every decision.

*Why this is not tuning:* the quantile is of the **input** distribution and is blind to outcomes. It
never sees fees, gas, LVR, or the position; the same calibration runs on a tape where the agent
loses money. Calibrating a threshold against results is the thing P-23 refuses, and it would look
nothing like this. This is the same class of correction as V-1, where κ's per-tick and per-log-price
readings differed by 10,000×.

*Direction of the error:* **toward holding the position**. A quantile threshold fires less often than
one set below the median, so the agent withdraws less. That is a real exposure change and it is the
point: the previous behaviour was not caution, it was a gate reading noise as signal.

## A18 · The volatility floor is capped at a ±25% band

**Added.** The range's width floor is now derived from `σ√T` at the published in-range floor (see the
parameter table). `σ√T` is a **random-walk** excursion, and flow that oscillates rather than trends
has a large per-√hour σ while going nowhere — the same reversion that makes A10 an upper bound rather
than an estimate. Left uncapped the floor answers a 40-tick oscillation with a **4,330-tick** range.

*The cap:* `w_max_price_band = 0.25`, so no more than ±25% of price, which is 2,231 ticks. Past that
a band is not a concentrated-liquidity position in any meaningful sense — it earns a passive
position's fee density while still paying to be rebalanced — so the strategy has nothing left to say
and the width stops growing.

*Where it binds:* on oscillating tapes, and **not** on the flagship pool, where the floor is 72 ticks
against a ceiling of 2,231.

## A19 · The width has a ceiling as well as a floor, and κ chooses between them

**Added.** A18 derives the narrowest range that can hold G-3's in-range floor. This is the same
derivation read at the other end, and it exists because the floor turned out not to be what was
setting the width.

*What it cost:* equation (2)'s half-width is dominated by κ, and κ is not stable to within an order
of magnitude. Fitted on the flagship pool it is **3,600.91** per log-price over the 30-day tape and
about **7** over a 40,000-swap slice of the *same pool* — a 500× swing that moves the half-width from
**3.1 ticks to 1,353**. A8 already records that the estimator fits a functional form the data does
not have; this is that defect setting the position rather than only being disclosed on the card.

On the real tape the consequence was a range of **±14.45% opened against a pool that moved 11.6% for
the whole month**. The position never left it, never had cause to recentre, sat in range 100% of the
time, and earned **2.4× less in fees than the passive baseline it had become** — 0.00727 against
0.01753. An agent that has turned into its own benchmark is not a rebalancing agent.

*The ceiling:* `sigmas_for_inrange(0.99)` — **2.807σ** of a horizon move, against the floor's
1.4395σ at 70%. Between those two widths, widening buys measurable in-range time. Past the ceiling it
does not: the position already has the time, and the only thing a wider band changes is that each
swap pays it less. `IN_RANGE_SATURATION` is that 0.99, and like the floor it is read through the
same inversion rather than chosen as a tick count.

*What this is not:* a cap on κ, or a correction to it. κ still chooses the width — the band is where
its choice is economically meaningful. On the flagship pool the band is **130 to 240 ticks**, and κ's
500× swing moves the width by 1.8× inside it instead of 34× outside it.

*Direction of the error:* **toward narrower ranges**, so toward more time out of range and more
recentring. That is the opposite of A18's direction, and the two are meant to bracket rather than
agree — a floor that only ever widened would have no way to be wrong.

## A17 · A withdrawal has to pay for itself, the way a recentre does

**Added.** Spec §3.3's gate R2 refuses a recentre unless the expected fee gain clears gas, slippage
and the MEV haircut. Nothing asked the same question of §3.4's withdrawal, so the toxicity arm could
cycle the position at whatever rate the daily budget allowed.

*What it cost:* on the 30-day chain tape, after A16 and A18 put the position in range 76% of the
time, Warden made **653 pull-and-return round trips** — costing **9.6% of deployed capital** against
**4.8%** of fees earned. The round trips, not the strategy, were the loss. Raising the re-entry
budget (A16) made this worse rather than better, which is what identified it: 653 over 30.2 days is
21.6 a day against a cap of 24, so the agent churned up to exactly whatever it was allowed.

*The test:* leaving saves the larger of two estimates, because §3.4's two arms know different things.

- The **CEX-gap arm leads** and carries a magnitude: a gap of `g` against a position worth `V` is
  arbitraged for about `V·g`, and that is knowable before any of it happens. Judging this arm by
  trailing realized LVR would refuse the pull precisely when the signal is doing its job.
- The **fallback and imbalance arms lag** and carry no magnitude at all, so the only honest yardstick
  is the bleed already measured: `(lvr_rate − fee_rate)` over the `m_clear` samples a re-entry needs.

Against that, a full exit now and a full entry later. The MEV haircut falls on the whole position
rather than A4's rebalanced notional, because a pull unwinds all of it.

*Why this does not contradict the exit being unconditional.* The decision rule argues the
budget "gates coming back, never leaving", since an agent forbidden to exit is held inside the flow
the rule exists to escape. That reasoning stands and no budget is consulted on the way out. A budget
refuses on an allowance already spent, which says nothing about the danger; this refuses only when
the pool is not measurably costing more than it pays. If flow is genuinely toxic the bleed is large,
the gate opens on the first sample, and nothing is held anywhere. What it blocks is the speculative
pull — signal fired, pool not actually hurting.

*Direction of the error:* **toward staying in the market.** That is a real exposure change, and A10
is what makes it conservative rather than dangerous: `lvr_rate` is an *upper bound* on adverse
selection, so the bleed this compares against is overstated and the gate opens **sooner** than a
truer measure would open it.

## A20 · A position is not opened while sigma is still the prior

**Added.** The width is chosen once and never re-examined — R1 asks whether the centre
drifted, R2 whether a move pays, R3 about cooldown, R4 about toxicity, and **nothing
asks whether the width is still right**. Because R1's threshold is `theta * w`, an
over-wide range raises its own bar against the recentre that would correct it. So the
opening sizing is effectively permanent, and it was being made on the first sample of
the tape.

On that sample `sigma` is not an estimate. The shrinkage step returns the
prior outright before any returns exist, and A7 records that prior as roughly 190%
annualised against BNB's typical 50–70%. This pool's realized sigma is about **17%**, so
the prior is **11x too hot**, and equation (2) is evaluated against it.

*Measured consequence:* the agent opened at **±14.45% on a pool that moved 11.6% for the
entire month**, sat in range 100% of the time, never moved again, and earned 0.00727 in
fees against a fixed 200-tick ladder's 0.04836 — **6.7x less**, while being
indistinguishable from the passive baseline it exists to beat.

*The gate:* `sigma_confidence` — the shrinkage weight `n / (n + 20)`, surfaced on the
`Observation` — must reach `min_sigma_confidence` (0.9, so 180 one-minute bars, about
three hours) before a position may be opened. Deliberately **not** `sigma.ready`, which
is a bar count: at the readiness threshold the weight is only 0.6, so a "ready" sigma is
still 40% prior.

*Kappa is deliberately not in this gate, and the first version of it was backwards.* The
intuition was that a fallback kappa makes the width a constant, so a fallback should
block the open. The arithmetic says the opposite: the fallback **is** the published fit,
3,600.91, at which equation (2) returns about 3 ticks — under the A18 floor, so the
floor sets the width and the result is the well-behaved case. The ±14.45% range came
from kappa ≈ 7, which is `is_fallback=False`: a genuine fit on a slice, clearing
r² ≥ 0.5, wrong by 500x. Blocking on the flag would have refused the safe case and
admitted the dangerous one. A19's ceiling is what actually bounds kappa.

*It applies to `passive_policy` too.* The benchmark calls the same `target_range`, so it
was opening at the same prior-sized width — which cut the baseline's own fees from
0.01753 to 0.00697. A comparison is only worth making if both sides are sized by one
rule.

## A23 · The width band, measured — and not separated

**Measured 26 Aug 2026.** A18 derives a width floor by inverting the first-passage
series at G-3's in-range floor (1.4395σ, ~130 ticks on the flagship) and A19 a ceiling
at 99% in-range (2.807σ, ~244). Both were published as derivations and carried as
**provisional**, because a derivation against a proxy — in-range time — is not evidence
about the thing that matters, which is net return.

The ladder has now been run on the 30-day tape, 20 rolling windows per width, net of
the protocol's cut and net of the realized convexity cost:

| half-width | P25 | P50 | P75 | windows |
|---|---|---|---|---|
| 40 | 8.49% | 15.46% | 30.86% | 20 |
| **80** | 12.66% | **17.03%** | 28.17% | 20 |
| 130 | 10.14% | 16.28% | 23.25% | 20 |
| 200 | 8.96% | 15.63% | 19.82% | 20 |
| 244 | 9.84% | 14.83% | 17.89% | 20 |
| 400 | 11.86% | 13.40% | 17.83% | 20 |
| 800 | 7.31% | 10.73% | 11.51% | 20 |

**The verdict is a refusal, and it is the honest one:** ±80 leads at the median and its
P25–P75 band overlaps ±130, so *it has not been shown to be better*. Every adjacent
pair on this ladder overlaps. At 20 windows this tape cannot separate widths, and
saying otherwise on the strength of a median ordering is exactly the misquote a band
exists to prevent.

*What can be said.* The medians decline monotonically from 80 outward — 17.03, 16.28,
15.63, 14.83, 13.40, 10.73 — and 40 sits below 80 at 15.46, so the curve has a hump
rather than a trend. And P75 falls steeply with width (30.86% → 11.51%) while P25 does
not, which is the variance a narrow range buys: more time out of range, and a longer
tail when it is in.

*What this does to A18 and A19.* Neither is refuted; neither is confirmed as optimal.
The derived band [130, 244] sits inside the measured ladder and its medians are within
the leader's band. **They stop being "provisional pending measurement" and become
"measured, not separated"** — which is a weaker claim than the derivation implied and a
stronger one than nothing. The floor's original job — stopping a range 0.795σ wide that
a random walk leaves 81% of the time — is unaffected, and 40 ticks scoring a *lower*
median than 80 with the widest band on the ladder is consistent with it.

*Cost of the measurement, recorded because it was nearly not made:* the first
implementation rebuilt its trailing window on every event, O(n²) against windows
holding 126,000 swaps. That is ~16 billion operations per window and it ran 100 minutes
without finishing. A deque and a bisect took the same run to **340 seconds**.

## A21 · A pool's fee APR is a property of a position, not of the pool

**Added.** Every venue this project quotes until now has a rate that belongs to the
venue: a Venus market pays every supplier the same. A concentrated-liquidity pool does
not. Two LPs in the same pool at the same moment earn different returns because they
chose different widths — narrow earns dense fees and leaves the range, wide earns thin
fees and stays.

So **"the APR of pool X" is not a well-formed quantity**, and a surface printing one is
quoting something that does not exist. The pool-APR estimator therefore cannot be
constructed without a width, carries `reference_width_ticks` on every result, and puts
it in the rendered label. A caller who wants "the pool's yield" has to say which
position they mean.

*What it is measured on:* realized LP fees over a trailing window, net of the
protocol's actual per-swap cut, divided by the capital a position of that width
deploys. The fee arithmetic is the accountant's — reused rather than restated,
because that is the one calculation this repository has already got wrong twice (P-1's
1.515x overstatement, P-8's `slot0[2]` for `slot0[5]`).

*Reported with its cost, never without.* `fit()` returns the realized convexity cost
from the same window beside the fee APR, and `net_apr` is a property over the two
rather than a stored third measurement. A fee APR published alone is the gross number
every other venue quotes, which is exactly what A10 exists to prevent.

*A position dilutes itself.* An LP earns `L_self / (L_pool + L_self)` of each swap's
fee, so a larger position is a larger share of its own denominator and its rate falls
with size — 8.7158% at one unit of capital against 8.7145% at four, on the same flow.
That is not rounding; it is the reason A1 caps a replayed position at 1% of pool
liquidity, and an estimator reporting perfect invariance would be one that had dropped
the self-term.

*Floor:* below **30 swaps** in the window the estimator is not ready and publishes no
verdict. TSLAx/USDT has 85 swaps across the entire 30-day tape; a number from a handful
of them would turn "we have no idea" into a figure someone can sort a table by.

## A22 · Pools are compared as bands, and only when the vetting layer clears them

**Added.** The pools report answers *which pool, how wide* — and the shape of
that answer is constrained twice over.

*Bands, not a leaderboard.* Every figure is a **P25–P75 range over rolling windows**
carrying its observation count (A5), using the replay's own `MIN_SAMPLES` and
`MIN_WINDOW_HOURS` floors so a pool refused here is refused on the same evidence
standard a quote is. Two widths whose ranges overlap are reported as *"not separated at
this sample size"* — the sentence the advantage report already uses — rather than
ranked. A sorted column of point estimates is the exact shape of the thing this project
is named against.

*Badged pools only.* A row publishes a ranking only where `vetting/badges/<pool>.json`
says `safe_to_provide`. **An absent badge is a refusal, not a pass**: the whole argument
of the vetting layer is that a pool nobody checked is a pool nobody should be steered
into, and defaulting the other way would quietly invert it.

*What "underserved" means here.* Volume says a pool is busy; busy and underserved are
different. An LP's return is proportional to **fee income per unit of liquidity**, so
that is the field the comparison rests on — the same flow spread over less depth pays
each unit more. Reported beside volume, swap count and tick crossings rather than
instead of them.

*The width ladder* spans 40 to 800 ticks and deliberately brackets A18's derived floor
and A19's ceiling at both ends. A sweep that cannot disagree with the derivation it is
checking is not a check.

## A24 · A pool's rate and a lending rate are not in the same numéraire

**Added 26 Aug 2026.** Router keeps its books in dollars. Every pool this repository has
badged is quoted in **WBNB** or **TSLAx** — there is no dollar-denominated pool on the
list — so the moment a PancakeSwap range became a venue Router could choose, the card
began ranking a BNB-denominated fee rate against a dollar supply rate.

Three quantities cross that boundary and they are not alike:

*The rate itself* is a ratio of two figures in the same units and is carried across
unconverted. Fees and capital are both measured in the pool's quote token at the same
instant, so the quotient is numéraire-free to first order.

*The sizes are not.* `supplied_base_quote` is the denominator of A1's ceiling and is
compared directly against a dollar notional, so it is converted with
the last swap on the verified WBNB/USDT pool,
the same reading the cost model already uses. `PoolVenue` **requires** the price and
raises without it. There is deliberately no default: P-25 is the record of what a
silently mixed BNB-and-dollars figure costs, and a default of `1.0` is that bug wearing
a nicer face. The price used is published on the card as `quote_price_quote`.

*The principal is the part no conversion fixes.* A supplied dollar earns a dollar rate
and stays a dollar. A range earns a rate measured in the pool's quote token and holds
two assets whose value moves with the price. These are different products, and no
arithmetic makes the two numbers interchangeable. So the card states it in words beside
the table rather than leaving a reader to infer that the larger figure is the better one
— which is the difference between a comparison and a misquote.

A consequence worth stating: because a pool's net figure is fees minus a convexity cost
that A10 publishes as an **upper bound**, it is a *lower* bound rather than a point
estimate, and it can fall below −100% when a short window's adverse selection is
annualised. `VenueQuote.apr_is_lower_bound` carries that distinction, and the −100% floor
— correct for a rate differenced out of an accumulator — is applied only to the point
estimates it was written for. Ranking a lower bound against a point estimate is
conservative, which is the safe direction, and the asymmetry is disclosed rather than
quietly evened out.

## A25 · A1 is refused at the decision, not counted after the position exists

**Added 26 Aug 2026.** A1 says a replayed position large enough to move the price it is
replayed against is fiction rather than a backtest. Router has enforced this by counting
breaches into `a1_capped` and having `allocation_quote_from_results` refuse the whole
quote afterwards.

That is the right refusal in the wrong place. Router's notional cap
— eps times the venue's size — has existed and been unit-tested since the policy was
written and **nothing ever called it**. The gate only ever fired once the capital was
already committed, which makes it a gate structurally unable to prevent anything: the
same defect the allocation layer records this repository as having shipped twice.

It never bound because every venue was a Venus market holding hundreds of millions, and
one percent of that is far more than this agent routes. A concentrated-liquidity range is
the case that exposes it. Depth over ±80 ticks of the flagship pool measures about
**$218k**, so A1's ceiling is about **$2.2k** against a **$10,000** notional — over by
four and a half times, and the 0.25% pool at ±400 is over by sixty-four.

`decide_router` now drops a venue that cannot absorb the notional before ranking, and a
held position that has *outgrown* its venue exits — ahead of the "nothing is measurable,
so stay put" branch, because that branch is right about an unmeasured venue and wrong
about one measured as too small. The counter survives as the backstop the gate cannot
be: depth is measured per sample, and no gate at entry can prevent a venue shrinking
afterwards.

Two consequences are deliberate. Declining for size is **not** the same as the venue
paying nothing, so the journal records `reason_a1_no_venue_can_absorb` separately and the
card can say the yield was there and the size was not. And a pool can pay well and still
be refused for being too shallow to take the position — which, at this notional, is
exactly what both badged pools do.

## A26 · A monotonic book pays a pool position; the trailing window only quotes it

**Added 27 Aug 2026.** Router shows a venue one number and pays a held position a
different one, and keeping those apart is the whole reason a replay is not marking
its own homework. The APR estimator differences Venus's `borrowIndex` — an
accumulator the chain maintains — while `TrailingAprEstimator` supplies the rate
the policy ranks on. A pool has no accumulator on chain, and the first version of
`PoolVenue.accrue` reached for the nearest thing to hand: the totals of its own
**trailing window**.

Those do not accumulate. A window that slides an hour gains an hour of swaps and
drops an hour of swaps, so the difference between two samples is
(entering − leaving) — mean-zero over a long hold, not the interval's earnings.
Flooring it at zero, on the argument that a window rolling backwards is "the
window moving, not a loss", kept only the positive half of a mean-zero series.
Holding the flagship at ±80 for 120 hours paid **109.8% annualised** where the
same estimator quoted **23.40%**, and the error grew with the holding period
rather than staying put — the signature of a ratchet rather than a rate.

So a pool position is paid from **its own book**. The range is fixed when the
position opens — the spacing-aligned centre and the width chosen at that moment,
sized the way the estimator sizes it — and an
`LvrAccountant` absorbs every swap since, `l_pool_includes_self=False`, so the
position is diluted by its own liquidity. `total_fees` and `total_lvr` only grow,
so differencing them is the interval and nothing else. The replay driver has
held a real range this way since it was written; this is that, behind the venue
seam.

Two consequences are deliberate. **The range is not re-centred under the holder**:
an LP who opened at ±80 around one tick still holds that range when the price
moves, and re-deriving the centre each sample is precisely how the window's drift
leaked into the payment. And **a losing interval is charged**: a concentrated
range really can give up more than it earns — that is what the convexity cost is,
and A10 publishes it as an upper bound because it is real. An accrual that cannot
go negative describes a position that only ever gains.

Nothing published carried the error. At the notional Router is quoted on, A1
refuses every badged range (A25), so no pool was ever held and the pool
contribution to `gross_yield_quote` was zero. It would have become wrong at the
first notional small enough to open a position — which is exactly what this
repository then went on to publish, so it was fixed first.

## What settles versus what is displayed

Two different numbers, deliberately.

**The marketplace floor** (spec §4.2) is what settles: `InRange% ≥ 70` over the window **and**
`fees − gas ≥ 0`. Binary, chain-checkable, no counterfactual, nothing to argue about.

**NetFeeAPR** (spec §4.1) is the honest performance display: fees minus realized LVR, gas, rebalance
slippage, and the MEV haircut, over capital, annualized — reported against a passive benchmark of the
same initial width never recentered over the same window, and secondarily against HODL 50/50
(labeled). It depends on a counterfactual, which is why it is displayed rather than settled.
