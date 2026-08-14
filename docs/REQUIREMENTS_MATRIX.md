# Requirements Matrix

Every complaint, conflict, and open question, with its status. `Readme.md` rule 1 says the spec wins
when code and spec conflict, and that conflicts get flagged rather than silently resolved. This file
is where they get flagged.

**No equation, parameter, or test in `WARDEN_SPEC_v1.0_FROZEN.md` is changed by anything below.**
Every entry is a conflict in the reuse manifest or in a premise, not in the math.

Status key: **OPEN** · **RESOLVED** · **ACCEPTED** (resolution agreed, implementation pending)

---

## D — spec-vs-reality conflicts

### D-1 · Fee pro-rating double-counts for a real position — ACCEPTED

Spec §6's replay loop credits fees "pro-rata by `L_h/(L_pool+L_h)`". For a *real* historical or live
position, the pool's `Swap` event carries a `liquidity` field that **already includes `L_h`**, so
dividing by `L_pool + L_h` counts our own liquidity twice and understates our share.

**Resolution.** Split the accounting rather than patch the formula.

- **LVR uses exact per-position curve math with no pro-rating at all.** Clamp the swap's price path
  to our range and evaluate the v3 bonding curve for a single position of liquidity `L_h`. This is
  not an approximation: it handles partial range crossings exactly, and `L_pool` never enters, so the
  double-counting question dissolves instead of being answered. Pro-rating is retained as a
  cross-check assertion for swaps that lie entirely inside the range.
- **Fees keep the spec's share formula**, behind an explicit `l_pool_includes_self` flag on the
  accountant: `True` for a real position (use `L_h/L_pool`), `False` for a hypothetical one (use the
  spec form). Default is the spec form, which is the conservative direction — it understates our fees.

Lands in: `packages/misquote/lvr/accountant.py` (Step 9).

### D-2 · "My own historical BSC positions" do not exist — ACCEPTED

Spec §6 specifies Showcase Mode as "my own historical BSC positions (Mission Control lineage —
auditable, on brand)".

**Verified state.** Wallet `0xE8A30d24BbA030D3e8a844bD1c4F6e1374EA6215` has a real, auditable BSC
mainnet record: 237 journal rows in `Stellar MIssion Control/data/journal/allocator_live.jsonl`
spanning 2026-06-08 → 2026-06-27, 83 swaps across 221 decision cycles, every row carrying a tx hash
and `nav_before`/`nav_after`. But it is **spot momentum trading executed via the `twak` CLI, not
liquidity provision.** There are zero concentrated-liquidity positions, and no
`NonfungiblePositionManager` interaction anywhere in the lineage. The showcase quote as specified
cannot be computed, because its input does not exist.

A stranger's wallet is explicitly forbidden by the same section.

**Resolution.** Showcase Mode is **counterfactual-only**: a hypothetical position replayed over the
target pool's real 30-day history, sized to the wallet's documented NAV from the journal (a real,
auditable number), and badged verbatim on the card:

> **COUNTERFACTUAL** — this position was not held. The pool history is real and the capital figure is
> real; the position is simulated. Assumptions →

This is published as assumption **A6**, an *addition* to A1–A5 rather than an edit to one. The
labeled synthetic borrower for the health story (spec §6) is unchanged.

**Why this preserves the spec's actual requirement.** §6's real deliverable is "same code path,
different input wallet". A counterfactual position and a live one both run through the same
`run_replay` with different inputs; the code path is identical, which is what T1–T4 and the L1
equivalence test verify. The false premise is the provenance sentence, not the architecture.

Recommended amendment to §6, for the record:

> ~~"my own historical BSC positions"~~ → **"a labeled counterfactual position on real pool history,
> sized to my documented NAV, plus one labeled synthetic borrower."**

### D-3 · The A-S core is a re-derivation, not a verbatim port — ACCEPTED

Spec §9 says PolyLambda's A-S quoting core is used "§3.1–3.2 verbatim, re-parameterized to ticks".
Three things make a literal copy wrong:

| | PolyLambda | Misquote |
|---|---|---|
| space | log-odds `X = ln(p/(1-p))` | log-price `y = ln P` |
| `k` | the A-S order-arrival parameter | called **κ** here |
| `kappa` | a jump-premium weight, unrelated | does not exist here |
| spread fn | `diffusion_spread_logit` returns the **total** spread | eq (2) already contains the ½ |

**Resolution.** Re-derive with identical equation shapes. On port, rename PolyLambda's `k` → `kappa`
and never port `jump_premium_logit` or `inventory_cap`, which are Polymarket-resolution artifacts
with no v3 analogue. **Do not halve twice** — `half_width_logprice` must return the half-width
directly. The hand-computed fixture test in Step 7 exists specifically to catch this.

### D-4 · Mission Control has no signing and no nonce management — ACCEPTED

Spec §9 lists Mission Control as the source for "BSC RPC layer, wallet/signing, nonce mgmt, tx
retry". Verified: `src/ictbot/api/onchain.py` is **read-only and keyless** by design. Signing is
delegated to a `twak` CLI subprocess (`exec/twak_client.py`) and to the `bnbagent==0.3.5` SDK.
Searching the repo for `get_transaction_count`, `sign_transaction`, `send_raw_transaction`, and
`build_transaction` returns nothing.

**Resolution.** The signer to port is PolyLambda's `execution/testnet_chain.py::AmoySigner` — chain-id
guard evaluated before signing, a `_NONCE_RACE` classifier with a refetch-once outer loop, `_rpc_retry`
that never retries a revert, the web3 v6/v7 `raw_transaction` compatibility shim, and a receipt poller
that retries through rate limits. From Mission Control, port only the **read** path
(`_rpc_candidates` fallback chain, Multicall3 `aggregate3` batching, the Chainlink feed map) and the
ops layer (Telegram, Prometheus, the autouse safety fixtures).

### D-5 · Mission Control has no event indexer — ACCEPTED

Spec §9 lists "event indexer scaffolding" as a Mission Control component. It has none: no `get_logs`,
no `create_filter`, no `.db`, no SQL. What it has is a CoinMarketCap WebSocket harvest into JSON
files. PolyLambda does have a real indexer, but it is Envio HyperIndex — TypeScript over
Envio-managed Postgres.

**Resolution.** Net-new Python indexer over chunked `eth_getLogs` into SQLite (Step 8). Envio's actual
strength is many contracts and huge backfills, which is the ERC-8004 registry indexer's problem in
Step 17, not the single-pool tape's.

### D-6 · Vault Analyzer is not code — ACCEPTED

Spec §9 and `Readme.md` §6 list Vault Analyzer as the source for "metric/report generation patterns"
feeding `packages/tearsheet`. It is a methodology document
(`/Users/apple/Downloads/vault-analyzer-guide.md`: 5 hard gates, 10 scored parameters P1–P10, verdict
bands) plus a rendered artifact. There is no source code.

**Resolution.** `packages/tearsheet` ports Mission Control's `scripts/live_trades_matrix.py` (JSONL →
markdown with zero hand-entered numbers) and `scripts/session_report.py` (including
`_verdict(n, m, t, min_n=30)`, which refuses to call a result below a sample-size floor — that
function is the honest-numbers guarantee and survives the port unchanged). Vault Analyzer's
methodology goes to `vetting/`, where gates-before-scores is the right shape.

### D-7 · Altana session revoke is not available as a day-one kill switch — ACCEPTED

Spec §7 lists Altana session revoke as kill switch (a). Altana integration is unverified and lands in
Step 17.

**Resolution.** Until it exists, protection is kill switch (b), the local hard-stop, plus a
**dedicated hot wallet holding only the capped capital and gas**, so the blast radius is bounded by
construction rather than by a contract call. The runbook says this plainly rather than implying (a)
is live.

---

### D-8 · §3.4's imbalance rule is one-sided, and defends only one side — DEVIATED

§3.4 writes the condition as `imb_t > z_pull`, unsigned. Read literally, the pull fires when the pool
is being **bought** and never when it is being **sold**.

Adverse selection does not care which token the informed trader is taking. An arbitrageur draining
token0 picks the position off exactly as thoroughly as one draining token1; the sign of `imb_t` only
records which. A one-sided rule defends one side of the book and leaves the other open, and on a pool
whose price falls it would be silent throughout.

**Deviation.** Implemented as `|imb_t| > z_pull` in `policy.imbalance_toxic()`, and written down here
rather than resolved in silence. The cost is symmetric and small: with `z_pull = 2.5` and `M = 50`,
the two-sided rule fires on roughly twice as many samples as the one-sided one, all of them cases the
spec's own rationale — "the next pool flow is arbitrage" — plainly intends to cover.

---

## V — defects found by verification, and fixed

Three independent verification passes ran before Step 8: a dimensional analysis, a line-by-line
conformance audit against this spec, and a check of the quant claims against the primary literature
and the Pancake contracts against their source. **Every defect below passed the 156 tests that
existed at the time.** The suite checked that formulas were implemented; it never checked that they
were fed the right things.

### V-1 · κ was fitted per tick and consumed per log-price — **the worst one**

§5.2 fits `ln(rate) = ln A − κδ` with δ "in ticks", so κ is per tick. Equation (2) evaluates
`ln(1 + γ/κ)`, which is only meaningful if that ratio is dimensionless — requiring κ per log-price,
because `(2/γ)` must come out in the same units as the half-width. One tick is `ln(1.0001) ≈ 1e-4`,
so **the two differ by 10,000×**.

Fed the per-tick value, `γ/κ` was 16 instead of 0.0016; the fill term stopped being a correction and
became the whole answer. `decide()` returned a half-width of **35,450 ticks — a ±3,363% price band**,
a position spanning 33× in price in each direction. Effectively full-range, earning almost nothing
while claiming to be concentrated liquidity, and a positive finite number that would have minted
without reverting.

**This is a contradiction inside the frozen spec**, not only in the implementation: §5.2 and §3.2
cannot both be read literally. It is the first conflict recorded here that lives in the math rather
than in the reuse manifest.

**Resolution.** `KappaFit` carries `kappa_per_tick` (as §5.2 measures it, published in the appendix)
and `kappa_per_logprice` (what the policy consumes), with one named conversion between them.
`tests/core/test_units.py` asserts the round trip, the plausibility band, and that the unconverted
value is still absurd — so the bug cannot return quietly.

### V-2 · `κ_default` was an invented number — **provisional pending Step 8**

§5.2 says "fall back to `κ_default` and label it"; the §8 parameter table has no κ row at all. The
implementation used 50.0, an unpublished number that was the dominant driver of range width whenever
the fallback path was taken — a direct breach of `Readme.md` rule 6.

**Resolution.** Renamed `PROVISIONAL_KAPPA_PER_LOGPRICE` with its basis stated in the source. Step 8
fits κ on 30 days of the target pool's real history and publishes the measured value as **G-4** with
its r². A default derived from the pool it will be used on is defensible; a round number is not.

### V-3 · `float("nan")` made every `Decision` unequal to itself — **would have blocked T1**

On the CEX-feed-down path the toxicity terms carried `float("nan")`. `Decision` is frozen and
hashable specifically so test **T1** can compare decision sequences bitwise, and NaN is not equal to
itself: twenty calls to `decide()` on one identical `Observation` produced twenty mutually unequal,
mutually unhashable objects. **T1 could never have passed on any decision taken while the feed was
down**, and T1 is the week-2 protected item. Now a `-1.0` sentinel, unambiguous because a gap is a
magnitude.

### V-4 · R2 tested absolute fees where §3.3 asks for fee *gain*

The gate computed `fees(target) > cost` rather than `fees(target) − fees(current) > cost`. That is
strictly weaker: it authorises rebalances the spec forbids, spending gas, slippage and a 10 bps MEV
haircut when the current range is already earning nearly as much. R2 is the economic gate — the
optimal-stopping threshold the spec is careful to justify — so this was the most consequential of the
policy-logic deviations. `Observation` now carries both fee rates and the target liquidity.

### V-5 · The MEV haircut was charged on position value, not rebalanced notional

Assumption A4 says 10 bps **of rebalanced notional**. A recentre swaps only enough to restore target
composition, typically a fraction of the position, so charging the full value overstated the cost
several-fold. Conservative in direction, but not what the published assumption says — and the
assumption sheet is a promise about how numbers were made.

### V-6 · Rounding: `w_t` floored, and `c_t` rounded twice

§3.2 says `round_to_spacing`; the code floored, making every range systematically narrower — average
4.4 ticks, up to a full spacing, always toward more rebalancing and more gas. §3.1 names the same
operation for the centre, but the code rounded to an integer tick and *then* to the grid, which
disagrees with a single `round_to_spacing` on **4.95% of inputs**, each by a full spacing. Both now
use one shared `_round_to_spacing`.

### V-7 · `q` was undefined in practice — the spec contradicts itself

§2 gives a formula yielding `[−0.5, +0.5]` and states the range is `[−1, 1]`. A position entirely in
token0 gives 0.5 under the formula, 1 under the stated range. Since `q` multiplies straight into
equation (1), the two readings skew the centre by a factor of two. **The stated range wins**, being
the testable claim: `q = (v0 − v1)/(v0 + v1)`.

### V-8 · The σ estimator compressed silence into volatility

Bars were appended only when a swap arrived, so an hour with no trades became a single one-minute
return. Measured: identical price oscillations arriving every minute and every six hours produced
**exactly the same σ**, though the six-hourly series is √360 less volatile per unit time. Returns are
now rescaled to per-bar magnitude and the EWMA decay ages by elapsed time. Disclosed as **A7**.

### V-9 · Two tests asserted nothing

`assert fit.kappa > 0.0 or fit.is_fallback` — both branches of `fit_kappa` return something positive,
so the left disjunct was unconditionally true and the assertion could not fail for any input. Its
fixture produced exactly the per-tick κ that yields a 35,000-tick range.

`assert got == pytest.approx(expected, abs=10)` on a 10-tick grid — a tolerance equal to the largest
possible disagreement, which made the assertion vacuous. It computed the spec's answer, the code
floored, and the tolerance swallowed the difference. **It was the only test standing between the
codebase and V-6.**

Also missing entirely: anything pinning σ's per-√hour scale factor (changing `√60` to `√3600` left
the suite green while every range width changed), and any test connecting an estimator's output to
the policy's input — which is the single gap that made V-1 invisible.

### V-10 · No validation on `Observation`, and an unmintable clamp

A negative `T_t` silently inverted the inventory skew: excess token0 would push the range *up*,
making the position a keener buyer of what it already held too much of, producing a plausible range
on the wrong side of the market with no exception and no NaN. `Observation` now validates on
construction.

`target_range` clamped bounds to `MIN_TICK`/`MAX_TICK`, which are **not multiples of any Pancake tick
spacing** (`887272 % 10 == 2`), so a clamped bound was a tick the pool rejects and the mint would
revert. It also broke the symmetry R1 measures drift against. The width now shrinks instead, and a
price pinned against the edge — which is exactly what chapel's unseeded WBNB/USDT pool looks like —
raises `AssumptionViolated` rather than quoting an unmintable position.

### V-11 · §3.4's imbalance arm was wired to nothing — **found by building a third agent**

Spec §3.4 defines toxicity as two conditions joined by `or`:

    TOXIC iff  |g_t| > fee_tier + arb_cost_bps  for m consecutive samples,
           or  imb_t > z_pull

`Engine._observe` passed a literal `0.0` for `swap_imbalance_z` on every sample. So the second arm
could never fire, `z_pull = 2.5` and `M = 50` (**G-1**) were parameters that traced to nothing, and
the policy's imbalance branch was unreachable code. In replay the CEX feed is always `None`, so the
*only* live arm was the on-chain LVR-vs-fees fallback — the one §3.4 itself calls the fallback.

The unit test for that branch passed the entire time, because it handed the policy a z-score
directly. Nothing tested that anything ever computed one.

**Why a third agent found it.** Warden reaches the same pull through either arm, so a dead arm is
invisible to it; Grid ignores health entirely. Sentinel's *primary* signal is this z-score, and it
never withdrew. An agent that consults a signal among many cannot tell a quiet signal from a broken
one; an agent that consults it first finds out immediately.

**Resolution.** `estimators/imbalance.py` computes `z = Σs / √(Σs²)` over the trailing M swaps, where
`s` is signed quote volume taken straight from `amount1` — the event's own sign convention, so there
is no direction to reconstruct and nothing to get backwards. Under the null that each swap's
direction is a fair coin with its magnitude as observed, `E[Σs] = 0` and `Var[Σs] = Σs²`, so this is
the standardised statistic. It is bounded by `√M`, which at M = 50 is **7.07**, and `z_pull = 2.5`
corresponds to **34 of the last 50 swaps going one way** (`18/√50 = 2.546`; 33/17 gives 2.263 and
does not fire).

`Params` now **refuses to construct** when `z_pull >= √M`, which is the same defect wearing a
different hat: a threshold above its own ceiling reads as configured and never fires. Two dead gates
have now shipped, both found by accident; this one is structural.

### V-12 · The policy and the engine applied *different* toxicity rules

`policy.py` tested `imb_t > z_pull`; `engine.py`'s streak logic tested `|imb_t| > z_pull`. On one-way
*selling* the policy would call the pool clean while the engine reset the `clear_streak` that governs
re-entry — an agent held out of the market by a condition its own policy said was not happening.

Neither was wrong about the value. There were two rules. Invisible while V-11 kept the value at zero.

Now one function, `policy.imbalance_toxic()`, which both read — the same fix as `gap_condition_holds`,
for the same reason.

### V-13 · The synthetic tape was not a possible history

Every synthetic swap carried `amount0 = +size, amount1 = −size` — the pool receiving token0 and
paying out token1, on **every single trade** — while the tick random-walked in both directions. No
AMM can produce that: a swap the pool receives token0 for must push price *down*.

It survived because nothing read the signs directionally. The LVR accountant forms deltas from the
price path by design (**P-2**), and the fee window only checks which side is positive to know which
token the fee is in. The moment V-11 was fixed, the tape read as fifty consecutive sells — a
permanently maximally-toxic pool, `z = −7.07` — and Warden pulled. The estimator was right; the
fixture was wrong.

**It had also been hiding a wrong test.** T2's ceiling multiplied every swap's fee by price
unconditionally, which is correct only when the input token is always token0. On a tape where price
moves both ways, the token1 legs were shrunk by the price itself — **≈613×** at tick −64180 — and the
ceiling collapsed to **0.421** against **0.743** of correctly credited fees, a 1.76× false failure.
The engine had it right; T2's hand-computed bound did not. Fixed to convert only the token0 legs.

Direction is now derived from the price move, and the fee is taken in whichever token came in. The
zero-move case alternates rather than drawing, so fixing the signs left the price path bit-identical
and every changed number traces to the signs alone.

**A one-directional test fixture is worth naming as a class of defect.** It cannot exercise any rule
that depends on direction, and it makes every such rule look like it passes.

---

## P — protocol and domain findings

### P-1 · PancakeSwap takes 34% of every fee, and the spec never mentions it

Read from the target pool's `slot0` on 2026-08-13: `feeProtocol = 3400` in both directions.
**Liquidity providers keep 66%**, so the effective fee is **0.033%, not 0.05%**. Uniswap v3 defaults
this to zero; Pancake sets it at `initialize()` and subtracts it *before* the fee-growth accumulators
update.

Reconstructing fees from `Swap` events × fee tier — the natural way to write the replay engine —
**overstates LP earnings by 1.52×**, landing directly on NetFeeAPR, the headline number on every
card, and on the R2 gate. `PoolMeta.fee_protocol` has no default, so a pool cannot be constructed
without stating it. Fee growth read from `feeGrowthInside` is already net; the two paths must not
both deduct. Test T2's conservation bound must include the factor or it is 1.52× too loose to catch
the error it exists for.

### P-2 · Swap event amounts are gross of the fee

Forming `(Δx, Δy)` from raw event amounts computes `LVR_k − fee_k`, which loses equation (3)'s `≥ 0`
guarantee and double-counts against `F` in equation (4). Strip the fee first; the post-swap
`sqrtPriceX96` is already fee-exclusive and is the correct `P_k`. Lands in Step 9.

### P-3 · LVR needs range clamping, worth up to 53×

Without clamping both price endpoints to `[P_l, P_u]`, a swap crossing the range entirely overstates
LVR by 3× typically and **53×** in the measured worst case. Above `P_u` the position holds zero
token0 — nothing left to pick off — and the benchmark has also sold out. Since Warden runs narrow
ranges by design this is the common case, not a corner. This is what D-1's clamped-curve approach
already prescribes; the magnitude is recorded so it is never treated as a rounding detail.

### P-4 · Equation (3) is an upper bound on LVR, not a model-free measurement

It is guaranteed non-negative for every swap regardless of counterparty, which is the tell that it is
not measuring adverse selection: it assumes the post-swap **pool** price is fair. On a round trip
`P₀→P₁→P₀` the LP is flat and collected two fees, yet equation (3) books a loss. It therefore
overstates LVR in churny pools by folding in reversion round trips.

**Resolution.** The tearsheet labels it *realized convexity cost (upper bound on LVR)*. Since §3.4
already computes the CEX gap, a second series measured against `P_cex` — which is LVR proper and can
be either sign — costs almost nothing and is strictly more honest. Also: the canonical LVR paper
contains no per-swap formula, so equation (3) is this spec's own (correct) discretisation and should
be presented as such rather than attributed.

### P-5 · The isomorphism claim is stronger than the literature supports — **docs**

§1 says a v3 position **"is"** a pair of limit orders and calls the mapping an **"isomorphism"**.
Uniswap's own documentation says range orders *"approximate"* limit orders and rules out stops
entirely. Milionis et al. characterise AMMs as market makers who *"do not proactively update their
price quotes"*, which is the negation of the A-S mechanism. Inventory is a deterministic function of
price rather than a controlled state, and the payoff is concave for every CFMM.

**Resolution.** Reframe §1 as a **design heuristic**, matching the tone §3.3 already uses ("no
pretending it's the exact QVI solution"). Costs no code. The correct reference for optimal v3
provision is Cartea, Drissi & Monga, *SIAM J. Financial Mathematics* 15(3), 2024
([arXiv:2309.08431](https://arxiv.org/abs/2309.08431)), which derives closed-form range boundaries
and reuses none of A-S's equations.

### P-8 · Two pools on the same DEX, two different protocol fees — read it, never model it

**P-1** established that PancakeSwap takes 34% of every fee on our WBNB/USDT pool
(`slot0.feeProtocol = 3400`), where Uniswap's is off by default, and that reconstructing fees from
volume overstates LP earnings by **1.52×**.

Resolving a tokenized-equity venue for the TermiX track's equities category turned up the other half
of that lesson. **TSLAx/USDT 0.25%** (`0x5E12d6EdB2b7D5330e474ea2D2694A3b3E35d492`, read via
`scripts/find_equity_pool.py`) reports **`feeProtocol = 0`**. Same DEX, same factory, same
contracts — and LPs keep the **entire** fee.

| Pool | `feeProtocol` | LP keeps | Effective fee |
|---|---|---|---|
| WBNB/USDT 0.05% | **3400** | 66% | 0.033% |
| TSLAx/USDT 0.25% | **0** | 100% | 0.250% |

So the protocol fee is not a property of PancakeSwap; it is a property of **the pool**. Either
constant would have been wrong somewhere: hardcoding Pancake's 3400 understates LP earnings on the
equity pool by a third, and hardcoding Uniswap's 0 overstates them by 1.52× on the flagship. This is
why `PoolMeta.fee_protocol` was given **no default** and must be supplied — a decision that cost one
line and has now been load-bearing twice, in opposite directions.

**The equities venue is thin, and that is stated rather than smoothed over.** TSLAx/USDT 0.25% is the
*only* xStocks v3 pool on BSC with usable liquidity (1.58e18). NVDAx and AAPLx are bridged to BSC and
have **no v3 pool at any fee tier**. The 1.00% TSLAx/USDT pool exists with **zero** liquidity — a
pool on paper, correctly refused by the discovery script's liquidity floor rather than quoted.

### P-7 · The toxicity rule's false-positive rate is measurable, and it is not zero

Once V-11 made §3.4's imbalance arm fire at all, it became possible to ask how often it fires when
there is **nothing to catch**. A synthetic driftless random walk contains no informed flow by
construction — there are no arbitrageurs on it — so every pull it produces is a false positive.

Over **9,000 swaps spanning 62.2 hours**, 44,802 samples:

| | |
|---|---|
| Pulls | **16**, one every **3.9 hours** |
| Which arm | **16 of 16 imbalance**; the realized-LVR arm never fired |
| Samples with \|z\| > 2.5 | **599 — 1.34%** |
| Expected under the null | **≈1.24%** (two-sided, standard normal) |
| Max \|z\| observed | **3.11**, against a ceiling of √50 = **7.07** |

Measured 1.34% against a predicted 1.24% is the estimator behaving exactly as specified. **The
estimator is not the question; the parameter is.** `z_pull = 2.5` is spec §8's published value, and
at a 5-second cadence over a rolling 50-swap window it costs a withdrawal roughly every four hours
on pure noise — gas spent, and the position out of the market, for flow that was never toxic.

**Not changed.** Retuning a frozen-spec parameter because its measured behaviour is inconvenient is
the opposite of what this matrix is for. It is published instead, and the number an operator needs in
order to disagree is right here: whether 2.5 is right depends on the ratio of genuine toxic episodes
to noise on the *real* tape, which a synthetic random walk cannot tell us. It is one more thing the
30-day backfill would settle.

That the rule fires 16 times and the LVR arm zero is itself informative: the on-chain fallback
compares *realized* quantities and so trails the damage, which is precisely why §3.4 calls it the
fallback and why Sentinel's docstring names "withdraws late" as a failure mode before the numbers do.

**And it now has a price.** The Agent Advantage Report's *Protect* task is an ablation — Sentinel
against Sentinel with its withdrawal disabled, same band, same reanchoring, one decision different —
and on the same driftless tape the withdrawing agent **loses by 1.77 percentage points**
(7.13–7.31% against 8.91–9.05%, bands not overlapping). That is this measurement expressed as money:
withdrawals that were all false positives, paying gas and forgoing fees for flow that was never
toxic.

Published rather than tuned away, and it is the reason the ablation is the right baseline: had
*Protect* been scored against a passive position instead, the loss would have been buried inside a
difference of band width and never attributed to the rule that caused it. **A marketplace selling a
risk agent would not run this comparison.** The result is a property of a driftless random walk with
no informed flow in it; on a tape that contains real toxicity the sign may well reverse, and that is
one more thing the 30-day backfill would settle.

### P-6 · Confirmed correct — worth recording, since Week 2 rests on it

- Equations (1) and (2) are **Avellaneda–Stoikov (2008) Eqs. 29 and 30 transcribed exactly**, and the
  ½ is right — Eq. 30 gives the *total* spread. This is the detail most implementations get wrong.
- **Pancake's core math is byte-identical to Uniswap v3-core** (TickMath, SqrtPriceMath, SwapMath,
  Tick, Position, FullMath), so differential-testing against Uniswap is valid for Pancake.
- Fee tiers **100→1, 500→10, 2500→50, 10000→200**, and no 3000→60, confirmed from the factory
  constructor.
- Equation (3)'s sign convention is correct and the **post-swap price is required** — substituting
  the pre-swap price makes every swap look profitable for the LP.
- **MasterChefV3 takes ERC-721 ownership on stake**, so direct NFPM calls revert and kill switch (b)
  would silently fail on a staked position. Our never-stake non-goal is validated.
- **Pancake derives pool addresses from a separate `PancakeV3PoolDeployer` with a different init code
  hash**, so Uniswap's `computeAddress` constants give wrong addresses. We resolve via
  `factory.getPool()` over RPC and must keep doing so.
- Pancake's pool **callbacks are renamed** (`pancakeV3MintCallback`), so calling pools directly with
  Uniswap-named callbacks reverts. Go through NPM and the Router.

Citation corrections for the tearsheet: the Cartea–Jaimungal–Penalva page references are doubtful and
that book's market-making chapter uses a linear-quadratic framework that is **not** the A-S formula,
so cite Avellaneda–Stoikov 2008 Eqs. 29/30 directly; and arXiv:2106.12033 has no author "Fritschi".

---

## E — external facts, verified from primary sources

| Claim in the docs | Verdict |
|---|---|
| Submission Sep 4 | **Wrong — it is Sep 9.** Build 5 Aug – 9 Sep, judging 9–23 Sep, winners 5 Nov. The frozen spec said Sep 9 all along. |
| "$30K = total pool" | **Partly wrong.** $30K is BNB Chain's main track; total is **$40,000+** — TermiX $10K (split unverified), PancakeSwap 1,000 CAKE, Altana 50,000 XP. |
| ERC-8004 is an agent identity registry | **Correct but incomplete.** Draft EIP, live on BSC mainnet (`0x8004A169…`) and testnet (`0x8004A818…`). It is **three** registries; identity is an ERC-721 whose descriptive metadata lives **off-chain** at `agentURI`, so indexing yields IDs and URIs, not agent cards. Do not build on the Validation registry — still under active revision. |
| ERC-8183 is a "hire interface" | **Mischaracterised.** It is **Agentic Commerce**: an escrowed job protocol, six states (`Open → Funded → Submitted → Completed \| Rejected \| Expired`). There is no `hire()`. See the corrected transaction count below. |
| ~~ERC-8183 is "live on both BSC networks"~~ | **Wrong, and it was our own claim — corrected 15 Aug 2026.** BNB Chain's own announcement says BNBAgent SDK "is now live on BNB Chain **testnet**, where developers can experiment with the full workflow today", with "**mainnet coming soon**". The EIP is **Draft** (created Feb 2026) and lists **no reference deployment addresses at all**. Building against a mainnet address we had never seen would have been the exact failure this project is named after. Testnet only, and no address is published — so the hire flow ships dry-run and unsigned until one is verified. |
| "Hiring is 3–4 transactions" | **Close, and now exact.** With the provider passed at creation (so `setProvider` is not needed), the client's path to escrowed is **four transactions**: ERC-20 `approve` → `createJob(provider, evaluator, expiredAt, description, hook)` → `setBudget(jobId, amount)` → `fund(jobId)`. Settlement adds the provider's `submit(jobId, deliverable)` and the evaluator's `complete(jobId)`, so **six transactions end to end**. `createJob` takes a **mandatory `evaluator`** which cannot be zero, and only that evaluator may `complete` or `reject`. ERC-2771 meta-transactions are an **optional extension, not core**, so nothing in the core interface batches these away. |
| "Who is the evaluator" is an open question | **Answered, two ways.** The EIP itself permits `evaluator = client` "when there is no third-party attester". BNB's SDK instead extends ERC-8183 with **UMA's Optimistic Oracle**: undisputed jobs settle fast, challenges escalate to UMA's Data Verification Mechanism. For Misquote the criterion should be **G-3's InRange% floor**, which §4.2 already requires to be binary and chain-checkable *without a counterfactual* — which is exactly the property an optimistic oracle needs to adjudicate a challenge cheaply. |
| "<~15 real agents → demote to registry view" | **Wrong by four orders of magnitude, and the real finding is better.** BNB Chain has **266,191** ERC-8004 agents, more than any chain by 4×. But only about **4% expose a working endpoint**, and after removing Sybil-flagged feedback **77.9% of rated BSC agents had no valid feedback left** — 29,444 reviews from **76 unique reviewers** (arXiv:2606.26028). **Invert the rule**: resolve each `agentURI`, rank by what responds, and decline to display on-chain reputation credulously — saying why, on the card. That is this product's thesis with independent evidence attached. Agent0 subgraphs already index ERC-8004 on BNB Chain, so discovery is a query. |
| `bnbagent==0.3.5` | **Stale.** Current is **0.4.2** under an explicit breaking-changes warning. Do not pin a June API for a September submission. |
| `studio.bnbchain.org/install` | **Dead — DNS does not resolve.** Two rival CLIs both called `bag`; the npm `@bnbagent/studio-cli` is current, the PyPI `bnbagent-studio` is stale. |
| Altana caps subset: allowlist, spend cap, expiry, Keystore, one-tx revoke | **Partly verified.** Budget, expiry, keystore issuance and explicit revoke are confirmed in the official CLI. **The allowlist and the "one-tx" characterisation are not** — the allowlist we were thinking of lives in `X402Signer`. Altana also cannot perform the generic ERC-8004 registration signature. Claim only what is demonstrated. |

---

## G — gaps in the frozen spec (values proposed and published)

The spec leaves these unspecified. Each proposed value is published in `ASSUMPTIONS.md` and rendered
in the UI, so a reader can disagree with the number without having to reverse-engineer it.

| ID | Symbol | Where | Value | Rationale |
|---|---|---|---|---|
| **G-1** | `M` | §3.4, trailing swap count for the imbalance z-score | **50** | Long enough for a stable z-score on a busy pool, short enough to react within minutes. |
| **G-2** | `arb_cost_bps` | §3.4, toxicity threshold | **5 bps** | BSC gas plus a CEX taker fee, the round-trip cost an arbitrageur must clear. |
| **G-3** | `N` | §4.2, InRange% floor for the bonded instrument | **70%** | Binary and chain-checkable, per §4.2's requirement that the floor need no counterfactual. |
| **G-4** | `κ_default` | §5.2, referenced but never given a value | *pending Step 8* | Will be the value fitted on 30 days of the target pool's real history, published with its r². Held as `PROVISIONAL_KAPPA_PER_LOGPRICE = 500` until then, and labelled as provisional on every card that uses it. See V-2. |

---

## Readme §8 · D1 checklist

| Item | Status |
|---|---|
| Prize split verified in BNB Discord | **PARTLY RESOLVED.** Main track **$30,000 USDT**, TermiX partner track **$10,000 USDT**, Altana 50,000 XP, PancakeSwap 1,000 CAKE — all from BNB Chain's own announcement. The **$6K/$3K/$1K** placement split on the architecture board is still **unverified** and should not be repeated. |
| ERC-8004 registry population counted on BscScan (decision rule: <~15 real agents → demote third-party auto-cards to a plain "registry view") | **RESOLVED — 266,191 agents; rule inverted.** Answered in the E table above and left reading OPEN here for weeks, which is its own small lesson: a checklist kept in a second place goes stale in the second place. |
| ERC-8183 hire call invoked from an external script | **STILL OPEN, and narrowed.** The escrow is now verified on chain (`registry/aacp.py`, matrix E) and `JOB_ESCROW[56]` carries it with evidence. But nobody has read a job back out of it — `nextJobId()`, `jobCount()` and `jobs(uint256)` all revert — so this is a verified escrow, not a verified ERC-8183 escrow, and the item stays open until a job round-trips on a fork. |
| Agent Studio CLI hello-world deployed | **OPEN** |
| Mission Control micropayment discrepancy (49 vs 75) | **RESOLVED — use 75 (242 logged)** |

### The TermiX track criterion we had recorded was wrong — corrected 15 Aug 2026

The only note on TermiX's judging anywhere in this repo lived inside
`STUDIO_TERMINAL_v3_FINAL.excalidraw:3780`: *"TERMIX: 80% = quality + proof → tearsheet"*. It is not
the criterion, and being buried in a drawing meant nothing ever checked it.

From BNB Chain's own announcement, the actual requirement:

> **$10,000 USDT.** *"Does hiring an agent on your marketplace beat doing the job yourself, and can
> you prove it?"* Entrants must provide an **"Agent Advantage Report comparing at least three real
> tasks run with and without an agent"**, with **"depth in trading, equities, and security
> categories"** weighted highest.

Three things follow, and none of them were true when this was found:

1. **"With and without an agent" was computed and thrown away.** `core/policy.py:passive_policy` and
   `replay/driver.py:passive_result` had existed since Step 7 and were used *only* by `tests/`.
   `Tearsheet` had no comparison field; `scripts/showcase.py` never ran the baseline. The answer to
   the judged question was a unit-test fixture. Now `scripts/advantage.py` and
   `tearsheet/advantage.py`, with a test that re-runs the engine and demands **exact** equality so
   no figure can be a literal.
2. **Three agents on one task is not three tasks.** Warden, Grid and Sentinel are three approaches
   to one job. The report's three tasks have three genuinely different baselines — mint-and-forget,
   the same agent with its withdrawal ablated, and pick-the-deepest-pool — and a test asserts they
   are distinct, because three tasks sharing a baseline is one task relabelled.
3. **"Real" tasks need a real tape.** Ours is synthetic and badged as such. The keyed `BSC_RPC_URL`
   therefore blocks the track's core requirement, not merely two amber gates.

**Equities** was a category we could not claim at all until xStocks turned out to trade on
PancakeSwap — see **P-8** for the venue and the protocol-fee finding it produced.

### The 49-vs-75 resolution

Source of truth is `Stellar MIssion Control/data/x402/receipts.json`: **242 records, 75 `settled`,
167 `failed`**, spanning 2026-06-12 → 2026-06-27 across `/x402/v1/dex/search` (240) and
`/x402/v3/cryptocurrency/quotes/latest` (2). The 167 non-settled are paid-endpoint HTTP errors,
logged and never pruned.

Both numbers were correct when written — the discrepancy is a snapshot artifact, not a data error.
Settled count by cutoff: **42** through 06-20, **61** through 06-21, **75** through 06-22 (final).
That repo's `README.md:35` and `SUBMISSION.md:57` say 49 because they were frozen at hackathon
submission time; its `pitch/` documents all say "75 settled (242 logged)" and are correct.

**Misquote uses 75 settled of 242 logged.** Per `Readme.md` rule 6, no card renders this number until
it appears here, which it now does.
