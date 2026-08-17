# The Assumption Sheet

**This file is a product surface, not a note.** It renders in the UI, one click from every quote.
`Readme.md` rule 6: every displayed number must trace to a chain query or to an entry on this sheet.
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

## A6 · Showcase Mode is a labeled counterfactual

**Added.** The showcase position **was not held.** The pool history is real, every swap traces to a
BscScan transaction, and the capital figure is real — it is the documented NAV from an auditable BSC
mainnet trading record (237 journal rows, 2026-06-08 → 2026-06-27, wallet
`0xE8A30d24BbA030D3e8a844bD1c4F6e1374EA6215`). But that record is spot trading, not liquidity
provision. **No historical LP position exists to replay**, so the position is simulated over real
history and badged **COUNTERFACTUAL** on the card.

*Why this is disclosed rather than quietly finessed:* the alternative was to imply a position history
that does not exist, on a product whose entire claim is that other marketplaces do exactly that. See
`REQUIREMENTS_MATRIX.md` D-2.

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
| Minimum half-width | w_min | **4 × tick spacing** | spec §8, anti-dust |
| MEV haircut | h | **10 bps** | A4 |
| Toxicity z-threshold | z_pull | **2.5** | spec §8 |
| Toxic samples to pull | m | **3** | spec §8 |
| Clear samples to re-enter | m_clear | **10** | spec §8 |
| Signal sample interval | Δs | **5s** | spec §8 |
| Replay sub-windows | K | **≥ 20** | A5 |
| Max rebalances per day | — | **8** | spec §8, gas discipline |
| Imbalance window | M | **50 swaps** | **G-1** — unspecified in spec, proposed here |
| Arbitrage round-trip cost | arb_cost_bps | **5 bps** | **G-2** — unspecified in spec, proposed here |
| InRange floor | N | **70%** | **G-3** — unspecified in spec, proposed here |
| σ estimator | — | EWMA of 1-min log returns, **6h half-life**, per-√hour | spec §5.1 |
| κ estimator | — | least squares on trailing **7d** swap depth buckets, refit daily | spec §5.2 |
| κ fallback trigger | — | **r² < 0.5** → κ_default, **labeled on the card** | spec §5.2 |

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
| Verified | 2026-08-13, block 115,653,558, by `scripts/verify_addresses.py` |

Every address the system points at was checked three ways on-chain — bytecode present, its interface
answers, and its answers agree with the other contracts' — rather than copied from documentation. Run
`uv run python scripts/verify_addresses.py --chain 56` to reproduce.

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

## What settles versus what is displayed

Two different numbers, deliberately.

**The marketplace floor** (spec §4.2) is what settles: `InRange% ≥ 70` over the window **and**
`fees − gas ≥ 0`. Binary, chain-checkable, no counterfactual, nothing to argue about.

**NetFeeAPR** (spec §4.1) is the honest performance display: fees minus realized LVR, gas, rebalance
slippage, and the MEV haircut, over capital, annualized — reported against a passive benchmark of the
same initial width never recentered over the same window, and secondarily against HODL 50/50
(labeled). It depends on a counterfactual, which is why it is displayed rather than settled.
