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
