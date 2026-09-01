# Requirements Matrix

Every complaint, conflict, and open question, with its status. The README rule 1 says the spec wins
when code and spec conflict, and that conflicts get flagged rather than silently resolved. This file
is where they get flagged.

**No equation, parameter, or test in the frozen spec is changed by anything below.**
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

Lands in: the LVR accountant (Step 9).

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
retry". Verified: its on-chain module is **read-only and keyless** by design. Signing is
delegated to a `twak` CLI subprocess and to the `bnbagent==0.3.5` SDK.
Searching the repo for `get_transaction_count`, `sign_transaction`, `send_raw_transaction`, and
`build_transaction` returns nothing.

**Resolution.** The signer to port is PolyLambda's `AmoySigner` — chain-id
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

Spec §9 and the README §6 list Vault Analyzer as the source for "metric/report generation patterns"
feeding `packages/tearsheet`. It is a methodology document
(its guide: 5 hard gates, 10 scored parameters P1–P10, verdict
bands) plus a rendered artifact. There is no source code.

**Resolution.** `packages/tearsheet` ports Mission Control's trade matrix script (JSONL →
markdown with zero hand-entered numbers) and its session report (including
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

### D-9 · The spec's sampling interval is impossible on a free endpoint — DEVIATED

§8 sets **Δs = 5 seconds**. A live source that asked the chain for logs on every sample would issue
twelve `eth_getLogs` a minute, and that is well past what any free BSC endpoint will serve.

**Measured against the target pool, in 2,000-block windows** — a fifteen-minute slice of chain,
nothing resembling a backfill:

| Cadence | Result |
|---|---|
| ~4 requests in 11 seconds | **`-32005 limit exceeded`**, all three endpoints exhausted, 3 rotations |
| 1 request every 60 seconds | **6 of 6 succeeded, zero rotations** |

The endpoints do not object to the *range*. They object to the *rate*.

> **Corrected 16 Aug 2026 — see P-11.** The table is what was observed; the sentence under it is a
> conclusion the observation could not support. `BscReader` rotates endpoints silently and reports
> only a rotation count, so "all three endpoints exhausted" and "6 of 6 succeeded" are both really
> statements about *whichever endpoint happened to answer*. Measured per-endpoint two days later, two
> of the three in that list refuse `eth_getLogs` at **any** rate and **any** width, including a
> one-block query — so the successful six were very likely all served by the one endpoint that works,
> and the rate was never the whole story. The deviation below still stands: two clocks are the right
> design, and the cost it names is real. It is the causal claim that was over-read.

**Deviation.** The live source keeps two clocks: the **decision clock** ticks at Δs and drives
the policy, and the **poll clock** governs how often we may ask the chain anything (60s by default).
Between polls, `events_since` returns nothing and `head()` returns the last head actually observed —
not an interpolation. A source that filled the gap would make the agent look responsive while feeding
it fiction, and a replay of that journal would be a replay of the fiction.

**What it costs.** §3.4's "m consecutive samples" now spans `m × poll_seconds` of wall time rather
than `m × 5s` — three minutes rather than fifteen seconds at the defaults. The toxicity rule
therefore reacts more slowly than the frozen spec describes. The cause is an endpoint quota, not a
design preference, and a keyed RPC removes it.

**What it unblocks, and what it does not.** The same measurement splits an item this project had been
treating as one blocked thing:

- **A 30-day backfill is 2,880 requests** as fast as they will be served. At the rate that works,
  that is two days of wall clock. Still blocked on a keyed `BSC_RPC_URL`.
- **A live tail is one request per fifteen minutes of chain.** `misquote.indexer.follow` polls once a
  minute — fifteen times faster than the chain produces a chunk, and an order of magnitude inside the
  quota. **That works today, on free endpoints, with no key.**

So we cannot recover thirty days of *history* without a key, but we can accumulate real chain data
*going forward* starting now. Nothing about that turns a two-hour tape into a thirty-day claim, and
the go/no-go still reports the tape amber until it spans 25 days.

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
The unit tests assert the round trip, the plausibility band, and that the unconverted
value is still absurd — so the bug cannot return quietly.

### V-2 · `κ_default` was an invented number — **fitted and published as G-4, 17 Aug 2026**

§5.2 says "fall back to `κ_default` and label it"; the §8 parameter table has no κ row at all. The
implementation used 50.0, an unpublished number that was the dominant driver of range width whenever
the fallback path was taken — a direct breach of the README rule 6.

**Resolution.** Renamed `PROVISIONAL_KAPPA_PER_LOGPRICE` with its basis stated in the source. Step 8
fits κ on 30 days of the target pool's real history and publishes the measured value as **G-4** with
its r². A default derived from the pool it will be used on is defensible; a round number is not.

**Closed 17 Aug 2026.** The constant is now `FITTED_KAPPA_PER_LOGPRICE = 3600.91`, measured on the
30-day tape at r² = 0.847 over 8,096 swaps — see **G-4**. The placeholder was **low by 7.2×**. The
gate that guarded this used to grep the source for the identifier `PROVISIONAL_KAPPA_PER_LOGPRICE`,
which meant a rename would have cleared it without fitting anything; it now compares the published
constant against the κ a chain-sourced card actually fitted, and fails on more than 10% divergence.
A gate a rename can satisfy is not a gate.

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

**Resolution.** The imbalance estimator computes `z = Σs / √(Σs²)` over the trailing M swaps, where
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

The policy tested `imb_t > z_pull`; the engine's streak logic tested `|imb_t| > z_pull`. On one-way
*selling* The policy would call the pool clean while the engine reset the `clear_streak` that governs
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

### V-14 · A Venus market must be one the Comptroller owns, not one that answers — **21 Aug 2026**

Cited by the Venus reader's `names the comptroller`, `is listed by the comptroller` and
`symbol agrees` checks.

A contract that answers `symbol()` and `comptroller()` is not thereby a market of that Comptroller —
it is a contract that answers. The affirmative test is membership in `getAllMarkets()`, and it is
the **only** one available here: Venus's Unitroller is an EIP-2535 diamond that dispatches per
facet, so a revert proves nothing about what it implements. `supplyCaps(address)` reverts with
`Diamond: Function does not exist` on a contract that plainly has supply caps.

So the survey asks three things that must agree: the market names the Unitroller, the Unitroller
lists the market, and the symbol matches what was recorded. Any single one of those can be produced
by a plausible impostor; all three together require actually being the deployment.

### V-15 · The underlying is the one this repository verified from the other direction — **21 Aug 2026**

Cited by `underlying agrees with the address table`.

`vUSDT.underlying()` returns `0x55d398326f99059fF775485246999027B3197955`, byte-identical to
`USDT_MAINNET` in the address table — an address verified months earlier, from the PancakeSwap
side, as token0 of the flagship pool. Two chains of reasoning that started in different places
landing on the same twenty bytes is a different quality of evidence from one chain repeated, and it
is the same argument the AACP reader records for the ERC-8004 identity registry.

### V-16 · A vToken's decimals are not its underlying's — **21 Aug 2026**

Cited by `vToken decimals agree`.

Venus vTokens are **8** decimals; BSC's USDT and USDC are **18**. `exchangeRateStored` is scaled by
both, so conflating them misprices a position by ten orders of magnitude. Recorded per market and
checked against chain rather than derived, for the same reason `PoolRef` records `dec0`/`dec1`
rather than assuming Ethereum's six.

### V-17 · A market that has never accrued, or holds nothing, is not routable — **21 Aug 2026**

Cited by `has accrued interest` and `has cash to supply into`.

`borrowIndex() == 0` is a market that has never accrued; `getCash() == 0` is one with nothing to
supply into. Both answer every getter and would pass a shallower check. Measured on Venus's own
list: `vBUSD` and `vSXP` return `supplyRatePerBlock() == 0`, so an argmax over an unfiltered
whitelist routes into a deprecated market on a tie. Liveness is a gate on entering the whitelist,
not an input to the policy.

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

### P-32 · Every quote the site served was `0.00% to 0.00%`, and the engine called it sufficient — **31 Aug 2026**

Found by refusing to fabricate a demo fixture. The plan said record a real job rather than assemble
one from the published cards; the real job came back with **`p25 = p50 = p75 = 0.0`** and
`distinct_returns: 1` — 24 replays over **3,035,494 events** of the real 30-day tape, every one
returning the identical number.

**The chain, four links, each individually reasonable:**

1. `/quote`'s "Replay this pool" sends `{pool}` and nothing else.
2. The quote route forwards `payload.get("capital_quote")` — `None`.
3. The job runner did `float(params.get("capital_quote") or 0.0)`. `None` became **0.0**.
4. The range replay did `fraction = r.net_quote / capital_quote if capital_quote > 0 else 0.0`.

Every return is therefore exactly `0.0`, the percentiles of a constant are that constant, and
`sufficient=True` publishes it. **The flagship flow — the Personal Quote Engine, the thing
the README §1 calls the kill-shot — answered every hire with a zero range that looked like an
answer.** On the deployed site, to anyone who pressed the button.

**Why it survived.** Every guard that should have caught it was pointed elsewhere. `A1` refuses a
position that breaches the liquidity ceiling. `A5` refuses too few windows, too few observations, too
short a window. `verdict()` refuses to call a rate on fewer than thirty. None of them asks whether the
*denominator* is real, and `distinct_returns` — which was computed, carried on the `Quote`, and
serialised into the job result — is guarded by **nothing**. The one field that named the symptom was
published beside the wrong answer.

**The shape, for the third time this week.** `if capital_quote > 0 else 0.0` is a guard that returns
a **plausible value** instead of refusing, and it is silent in exactly the case it should be loudest.
P-30 was `estimate_gas` measuring the caught branch of a `try/catch` and an ERC-721 recipient with no
receiver; P-31 was a browser assertion on an interaction that never fired. Each one reports its own
inability to produce an answer *as* an answer. Zero is the most dangerous default there is, because it
is a number.

**Fixed in two places, and the split is the point.**

- **The engine refuses.** `capital_quote <= 0` now returns `sufficient=False` with its reason, in the
  same shape as the A1 branch directly above it. A default *inside* The engine would make it quietly
  quote a size nobody asked for, which is the same defect wearing better clothes.
- **The job defaults**, to `DEFAULT_CAPITAL_QUOTE` — the unit the published cards already use. That is
  the caller that knows what capital means to it, and a hire naming only a pool should get the
  marketplace's own unit rather than an error.

The range tests pin all three cases: zero refused, negative refused (`> 0` meant `-1`
took the same silent branch), and a positive capital still dividing plainly.

*The lesson worth keeping:* a division guard is a refusal wearing a conditional. `x / y if y > 0 else
0.0` reads as defensive and is an assertion that zero is the right answer when the input is missing —
and on a site whose argument is that every number traces to something, the number with nothing behind
it is the one that gets published.

### P-31 · A simulation layer that was complete, deployed, and could not fire — **31 Aug 2026**

The scenario module is 161 lines of carefully-argued simulation: a scenario short-circuits above
`apiBase()` so no request is issued, it can only ever be labelled `simulated`, its refusals are
terminal, and it is never default and never sticky. Three fixtures were committed. All three are
**served in production** — fetched off `misquote.vercel.app`, all 200.

**Nothing linked to any of it.** The only affordance in the entire UI was the button that *leaves* a
simulation. To reach the feature you had to know `?scenario=` existed and then guess one of three
names printed on no page, in no README, and in no judge document. Commit `c651036` touched
the root layout for the banner mount and nothing else in the UI; the follow-up added browser assertions
and still no way in.

That is the fifth instance of this repository's recurring defect — built and wired to no reader,
after `PAYMENT_TOKEN`, `aacp.verify()`, `erc8183.render()` and `fetch_live_contracts`. But two things
underneath it were worse.

**1. The flagship fixture was dead code.** `quote-thin-tape` records the refusal the feature exists
to expose — *"the most important thing this site does"*, per its own `why`. `scenarioResponse` was
reachable from exactly one place, `loadLive`, and `/quote` does not read, it **posts**:
The quote view called `apiBase()` and then a raw `fetch`, **below** the short-circuit. Its only
key, `"POST /quote"`, reached `loadLive` in one unit test and nowhere else.

The consequence is worse than an unused file. Under `?scenario=quote-thin-tape` the page rendered the
simulation banner and then issued a **real request to the live API** — a page saying *simulated*
while talking to production, which is precisely what the four rules exist to prevent.

**2. The guard passed vacuously.** The browser check listed that route as
`["/quote/", "quote-thin-tape", null]` — needle `null`, so the refusal text was never asserted. What
it did assert, beneath a comment reading `// The load-bearing one.`, was that **zero** requests
reached the API. That held trivially, *because nothing was ever submitted*.

This is **P-30 in a new place**: a check reporting its own inability to run as a pass. The pattern
now has four instances — `try/catch` plus `estimate_gas`, an ERC-721 recipient with no receiver,
`read_job`'s `any(word != 0)`, and a browser assertion on an interaction that never fires. The tell
is the same each time: *the check cannot distinguish "the claim is false" from "I did not run".*

**Fixed.** `postLive` carries the same short-circuit for submissions, with the same ordering above
`apiBase()`; `/quote`'s enqueue and its job read both go through it, and `apiBase` is no longer
imported by that page at all — which is the property, stated as an import. The browser gate now
**types an address and clicks Replay** before asserting, so "reached the API 0 times" means
something. And `/demo` renders the fixture list off disk, so a state that exists is advertised and
one that is deleted is not.

**What a happy path cost, and why it was recorded rather than written.** No completed quote result
existed anywhere on disk. The fixture is a real job against the real 30-day tape: the API's own
estimate was 24 replays over 3,035,494 events, and it was run rather than assembled from the cards.
A demo whose headline number was invented would be the thing this project is named after, on the page
built to show the product working.

*The lesson worth keeping:* a feature with no entry point and a test that cannot fail are the same
mistake at two altitudes — something that looks present and is not exercised. The question that finds
both is "what would break if this were deleted?"

### P-30 · Two ways for a proof to fail silently, and both report the finding as false — **31 Aug 2026**

Building the `mintable-range` proof-of-concept produced two failures worth more than the proof. The
mint reverted twice, and **neither time did anything crash**. The proof runner published
`held: false` with a straight face, `/vetting` rendered it, and the reading was indistinguishable
from *the pool will not accept a position at these bounds* — a badge check failing, on a pool the
badge had passed.

A proof harness that cannot tell "the claim is false" from "my harness is broken" is worse than no
harness, because it produces confident negatives.

**1. A v3 position is an ERC-721, and the prover is its recipient.**

`mint(params)` hands the position NFT to `params.recipient`. The prover contract is `msg.sender`, so
`recipient` is `address(this)` — and a contract that does not implement `onERC721Received` is
rejected by the transfer. The mint reverts.

It reverts with **empty return data**. `catch Error(string memory reason)` never fires, only
`catch (bytes memory)` does, and the most honest thing the contract can say is "no reason given".

What isolated it was running the *identical* parameters from an EOA: same pool, same bounds, same
amounts, same approvals, same deadline — `estimate_gas` returned 396,833 and the receipt came back
`status: 1`. The only difference between the two calls was who was being handed the token.

**2. `estimate_gas` measures the caught path of a `try/catch`.**

The second failure survived the fix, and it is the more general one.

`proveMintable` wraps the mint in `try/catch` — correctly, because a revert *is* the answer and the
answer has to reach the event rather than the transaction. But `build_transaction` without an
explicit gas limit calls `estimate_gas`, and estimation runs the function: the inner call fails, the
catch fires, the function returns cheaply, and **the estimate is the cost of the failing branch**.

Send with that estimate and the EVM's 63/64 rule hands the inner call almost nothing. It runs out of
gas. The catch fires. The estimate was correct.

The loop is closed, self-fulfilling and perfectly stable — it does not flake, it fails the same way
every time, which is exactly what makes it read as a finding. And out-of-gas produces the same empty
return data as a bare `revert()`, so it is indistinguishable from defect 1.

*Fixed:* `MINT_GAS = 1_500_000`, passed explicitly, with the reasoning at the call site and a test
asserting the mint is never sent on an estimate.

**The shape both share.** A guard that catches failure will catch its own failure to run, and report
it in the same field. `try/catch` around the thing under test, `catch` around a missing dependency, a
timeout around a call that was never made — each one turns "this did not work" into "this is false".
The repository already had one of these: `read_job`'s first existence test was
`any(int(w, 16) for w in words)`, which is true for every id that never existed because the ABI head
offsets are non-zero (P-28).

*The lesson worth keeping:* when a proof reports a negative, the first question is whether the proof
ran. Both defects here were found by asking it — the EOA comparison for the first, and "what does an
estimate of a catch measure" for the second — and neither would have been found by reading the code,
because the code was right in both cases.

### P-29 · A closed API, concluded from a 401 that every path returns — **31 Aug 2026**

The fourth instance of one defect. P-24: *"no verified deployment exists"*. P-27: *"no session-key
module has been verified"*. P-28: *"nothing here can sign"*. And now:

> Blocked on a wallet-signed nonce exchanged for a session JWT, **which is the same signing path the
> 24h burn-in needs and which does not exist yet.**

**Three claims, all false.**

**1. It is not the burn-in's path.** `check_burn_in` reads timestamps out of a JSONL journal. It
never touches a signer, a key or a signature. The two items were recorded as one blocker on a
resemblance — both involve a wallet — and nothing checked it.

**2. Signing was a wrapper gap.** `BscSigner.__slots__` carries `account`; it is a `LocalAccount`,
and `sign_message(encode_defunct(...))` has worked since the file was written. What was missing was a
method. `encode_defunct` appeared nowhere in the repository, which is what made "does not exist yet"
feel true — the absence of a *wrapper* reads exactly like the absence of a *capability*.

**3. The endpoints were never private**, and the reason nobody noticed is worth more than the
finding. Their API returns `401 UNAUTHORIZED` for **any** unmatched path under `/api/v1/`:

| probe | result |
|---|---|
| `GET /api/v1/auth/nonce` | `401` |
| `GET /api/v1/definitely-not-a-real-endpoint-xyz` | `401` |
| `GET /api/v1/zzz/qqq` | `401` |

So a GET probe cannot distinguish *protected* from *nonexistent*, and every reconnaissance that used
one concluded the auth surface was closed. **POST separates them**, because the public endpoints
validate their fields before authorising anything:

| probe | result |
|---|---|
| `POST /api/v1/auth/nonce {}` | `400 walletAddress: Required` |
| `POST /api/v1/auth/wallet {}` | `400 walletAddress: Required` |
| `POST /api/v1/auth/refresh {}` | `400 refreshToken: Required` |

An error code that is uniform across a namespace carries no information about that namespace. Reading
one as though it did is the same mistake as reading `jobs(uint256)` reverting as "the accessors are
named something else" (P-18) — a negative result with one explanation assumed and others unchecked.

**It is SIWE, and the message is theirs.** `/auth/nonce` returns EIP-4361 — a nonce, a domain, a
chainId, a ten-minute `expiresAt`, and the exact `message` string. The authenticator signs
**that string verbatim**. Reconstructing a SIWE message from its parts is the standard way to produce
a signature that recovers to the correct address and still fails verification: one character of
whitespace, one field ordering, one timestamp rounded differently.

**The exchange completes.** `make termix-login` gets a nonce, signs it as the operator, and receives
an access token and a refresh token. `/api/v1/agents` — `401` unauthenticated — answers. The record
in the recorded authentication carries **no credential**, and a test asserts it holds
no token, no refresh token, no signature and no nonce; `Session.evidence()` has no field that could
hold one, so recording more would take a visible code change rather than an attribute access.

**What closing it revealed is that the item was mis-titled.** The entry's `what` was *"listing our
agents on TermiX's own platform, **and** any authenticated read of their order book"* — two things
joined by an *and*, of which auth only ever gated the second. The authenticated read now works and
returns **`0 items`**: asked as ourselves, with a token, from the endpoint their own dashboard reads.
Their backend is chain 56 only and the four agents are on chapel, so they are invisible to it by
construction. That was already published on `/registry` as an inference from the public explorer; it
is now a reading from the authenticated side, which is a stronger claim about the same fact.

*The lesson worth keeping:* a uniform error is not evidence. When every path in a namespace answers
identically, the answer is about the namespace's middleware and not about the path — and the way to
find out is to change the *method*, not the path.

### P-28 · The hire flow was blocked on an ABI, and the ledger said it was blocked on signing — **29 Aug 2026**

The `ERC-8183 hire flow` ledger entry gave its blocker as:

> escrowing a job means signing five client transactions and moving real USDT, and **nothing here
> can sign**

That was false when it was written. The signer signs, and the identity module broadcast
**six chapel transactions** whose hashes were already recorded and rendered on
`/registry`. What was actually missing was an **ABI** — there was no calldata builder for
`createJob`, `setBudget` or `fund` anywhere in `packages/`.

The difference is not pedantry. *"We cannot sign"* names a capability nobody has, and the response is
to wait. *"We have no ABI"* names a file nobody wrote, and the response is to read a dispatch table.
The entry pointed at a gate that was already open.

**Recovering the interface immediately paid for the method.** The recovered ABI table resolves every
signature against the PUSH4 selectors in the deployed implementation rather than copying Altana's
published ABI — the technique the AACP reader used for P-18, run forwards. `submit` did not resolve under
the EIP's shape. It took **21,060 candidate signatures** over 36 names to find:

    EIP / erc8183.steps()   submit(jobId, deliverable)          two arguments
    the deployment          submit(uint256,bytes32,bytes)       three

A client built from the standard encodes two words, hits a selector that does not exist, and reverts
with **no reason string** — on transaction six of seven, after the money is escrowed.

**Then it ran.** `make hire` against chapel: `approve`, `createJob` and `setBudget` mined; job **746**
reads back with our client, provider, evaluator and a 1e18 budget, recorded.

**Four permissioning surprises, which is what the README §8's D1 box asked about.** None is in any
ABI — `createJob` reverts with bare four-byte selectors — so each was isolated by varying one argument
at a time, then matched to a name by preimage search where possible. Where both methods answered they
agreed, and that agreement is the evidence:

| selector | isolated behaviour | name |
|---|---|---|
| `0x55c45de1` | hook is `address(0)` | `HookRequired()` |
| `0x1a5d3d5f` | hook is any other contract, or an EOA | unresolved |
| `0xd92e233d` | evaluator is `address(0)` | unresolved |
| `0xf7a0748c` | `expiredAt` zero or in the past | unresolved |
| `0xb40b2a0e` | `expiredAt` too far ahead | `ExpiryTooLong()` |
| `0xff97b861` | `fund()` with a zero budget | `ZeroBudget()` |
| `0xc94463e3` | `registerJob`, every policy argument | unresolved |

**The hook is the surprise.** The EIP treats it as an optional extension point and `steps()` recorded
it as one. On this deployment `address(0)` — the natural way to say *no hook* — reverts, and so does
the kernel itself, the OptimisticPolicy, and an EOA. **Only the EvaluatorRouter is accepted.** Three
of the seven are named; the other four are recorded by selector with their observed behaviour, because
a name that has not been confirmed is a guess that will later be quoted.

**Two steps did not mine, and neither closes with code.**

- **`fund` cannot be exercised at any price.** The deployment's payment token is owner-minted:
  `mint(address,uint256)` reverts `Ownable: caller is not the owner`, there is no faucet among its
  **59 selectors**, and the signer's balance is 0. So the escrow half of ERC-8183 is unreachable from
  here, and the ledger says so rather than reporting a zero-budget job as a completed hire.
- **`registerJob` reverts for every policy argument tried**, including the OptimisticPolicy the
  deployment publishes. That is consistent with the hook having registered the job already — which
  would make step 3 of `steps()` a no-op here — but it is an **inference from a revert**, and nothing
  has read a registration back out to confirm it. Recorded as an inference.

**A third defect, caught by the read path.** `read_job`'s first existence test was
`any(int(word, 16) for word in words)`, which is **true for every id that has never existed**: an
unknown job returns thirteen words of which two are non-zero, and those two are `0x20` and `0x160` —
the ABI head offsets every dynamic-struct return carries. This is **P-18's trap in a new costume**;
there it was thirteen zero words for an order in the wrong settlement book, here it is a well-formed
answer for a job that was never created. Existence is now the requested id coming back in word 1,
which is also the only field in the struct confirmed by agreement: ask for 743, get `0x2e7`.

*The lesson worth keeping:* a blocker recorded one level too high stops the work that would clear it.
"Nothing here can sign" and "nothing here has an ABI for this contract" have the same consequence
today and completely different next actions.

### P-27 · The session-key refusal was a search of our own output directory, reported as a search of the world — **29 Aug 2026**

The session-key module kept `SESSION_KEY_MODULE` empty and said why, in a docstring headed *"Why
there is no address here"*:

> our own recorded address files hold
> — nothing session-key shaped — because nobody has run the three-way check against an Altana
> session-key module

Every clause is true. The inference is not. `SEARCHED` named three files, **all of them this
repository's own output**, and the module concluded from their contents that no session-key
module had been verified anywhere. A search list containing only your own artifacts can only
ever tell you what you already knew.

The Altana SDK publishes the addresses — chains 1, 56, 97 and
8453 — and the ABI alongside them. **That is the same package, at the same
version, that `JOB_ESCROW` was verified from.** This repository had already read
`ERC8183_ADDRESSES` out of it and never opened the file beside it.

**This is P-24 repeating, one module over**, and P-24's own closing line is the diagnosis:
*"no verified deployment exists" and "we have not verified a deployment" are different
sentences.* The lesson was written down and did not generalise, because it was recorded as a
fact about ERC-8183 rather than as a habit about search.

**Every check passed, both chains.** The session-key verifier, the same three ways
the ERC-8183 verifier looks:

| | chain 56 | chain 97 |
|---|---|---|
| keyStore | 8,756 bytes | 8,756 |
| keyStoreController | 3,609 bytes | 3,609 |
| `getKeys` / `isValidKey` / `getPublicKey` | answer | answer |
| `getRegistrationFeeInWei()` | 726,868,274,705,776 wei | 725,716,783,448,241 |
| keyStore ≠ keyStoreController | yes | yes |

Byte-identical code sizes across the two chains, so what was exercised on chapel is not a
different contract from the one on 56.

**Four corrections that only running it could produce.** Each is a revert message or a chain
reading, not a reading of the SDK:

1. **There is no `approve`.** `grant_plan()` returned `approve` then `grant`, on the reasoning
   that a spend cap needs its token approved to the module. The fee is native BNB paid as the
   call's `value`, and the spend cap is not an allowance to this contract at all. A demo built
   from the old plan sends an `approve` to a contract that never pulls a token.
2. **`registerKey` reverts on a fresh wallet** — `KeyStore: account not bootstrapped`. The first
   key goes through `initialRegisterKey`. So the count of two was right and both reasons for it
   were wrong.
3. **The root key must not expire** — `initialRegisterKey` with any non-zero expiry reverts
   `KeyStore: root key must not expire`. This also explains a live chapel key reading
   `expiry_ts: 0` and `valid: true` at once: not an expired key still working, a root key doing
   what the contract requires. Zero is *no expiry*, so an accidental zero is an unbounded grant
   rather than a dead one, and `grant_call` refuses it.
4. **The grant and the revoke are on different contracts.** `registerKey` on the
   keyStoreController, `revokeKey` on the keyStore. Nothing about the caps subset predicts that.

**The registration fee is not a constant.** Three reads minutes apart returned
723,464,592,130,675 / 725,716,783,448,241 / 726,868,274,705,776. A page rendering a cached
figure quotes a price the chain will not honour, which is this project's own name, on the
activation page. `registration_fee()` is read per grant and the docstring says why.

**Proven, not described.** `make session-keys` granted a key on chapel, read it back live,
revoked it, and read it back dead — three mined transactions in
recorded on chapel, `isValidKey` true then false. That is the README §5's
definition of done for activation, and it is the first evidence on this site that a grant is
bounded *and* reversible rather than merely enumerated.

**What is still not built, and it is the more interesting half.** The keystore enforces the
**expiry** and **revocation**. It does not enforce the **allowlist** or the **spend cap**: those
would live in a `validator` module's `metadata`, and every grant observed on this deployment —
ours and other people's, read off chain — carries `validator = 0x0` and empty metadata. So
`VALIDATOR_MODULE` is empty for exactly the reason `SESSION_KEY_MODULE` used to be, to the same
bar, and `SessionKeyWriter.grant` refuses to send a capped-looking grant unless the caller
passes `allow_unenforced_caps=True`. Two of the four caps are real; a page rendering four would
be the misquote.

*The lesson worth keeping:* a refusal is only as good as its search list, and a search list made
of your own artifacts is not a search. `SEARCHED` now names the SDK first.

### P-26 · Three thresholds were numbers correct for quantities they were not applied to — **25 Aug 2026**

Prompted by an audit against the PancakeSwap track's criterion — *"the agent must deliver a real
benefit to PancakeSwap traders or liquidity providers"* — which the published cards did not meet:
Warden **−64.31pp** against a passive baseline, Sentinel **−37.07pp**, Grid's **+13.35pp**
unclaimable because its bands overlap.

Reviewing P-17, P-20 and P-23 together makes them one defect wearing three hats. Each is a constant
chosen against a distribution or a unit that is not the one it governs — the same shape as **V-1**,
where kappa's per-tick and per-log-price readings differed by 10,000x. That is a correctness class,
not a tuning class, and it is the reason this reverses P-23's "flag it, do not tune it".

**1. `z_pull = 2.5` gates a statistic that is not N(0,1).** P-23 measured it: median `|z|` **2.179**,
firing on **41.94%** of samples. The estimator's own docstring states the statistic is a permutation
null bounded by `sqrt(M)` and *"not N(0,1) in small samples"*. A threshold chosen as though it were
is not a strict reading of the spec — it is an arithmetic error the spec happens to contain.

*Fixed:* the operative threshold is the trailing **95th percentile of `|z|`**, measured on the same
pool by the same estimator over the policy's own `window_hours`. `z_pull` remains the fallback for
the first 2,000 readings. Recorded in `Observation.swap_imbalance_threshold` and on every decision.
Published as **A16**.

*Why this is not what P-23 refused:* the quantile is of the **input** distribution and never sees an
outcome — not fees, not gas, not LVR, not the position. It calibrates identically on a tape where
the agent loses. Fitting a parameter to a result would look nothing like this.

**2. `w_min = 4 x tick_spacing` is 0.795 sigmas of a 24-hour move.** P-17 established that equation
(2) returns 2.86–4.75 ticks against a floor of 40, so the floor set the width and the model
contributed nothing. What P-17 did not compute is what that floor *is* in the units that matter: at
the measured sigma it is **0.795 sigmas** over the horizon, and the probability a driftless walk
never leaves such a band is **18.5%**. The measured in-range fraction was 6.1%. The floor was not a
conservative choice; it was a band the price leaves four times in five.

*Fixed:* the floor is derived by inverting the two-sided first-passage series at G-3's published
in-range floor — **1.4395 sigmas at 70%** — and capped at +/-25% of price, because `sigma*sqrt(T)`
is a random-walk excursion and reverting flow produces a large sigma while going nowhere. Published
as **A18**. No new constant: the multiplier is a function of a number already on the assumption
sheet.

**3. One budget was pricing two behaviours.** P-20 found re-entry refused on 90.2% of HOLD
decisions. The cause is that `reentry_affordable` spent `max_rebalances_per_day`, so every return
from a defensive pull consumed a recentre the agent then could not make.

*Fixed:* `PositionState.reentries_today` and `Params.max_reentries_per_day = 24`. Both counters
still survive a pull, so the property the single counter existed to protect — that neither limit can
be reset by leaving and coming back — is kept, and now tested for both.

**Also fixed, found while doing the above:** `ranges.perturbations` documented perturbing
"(gamma, kappa)" and scaled **only gamma**, because kappa is estimated and `Params` had nowhere to
hold a perturbation of it. So A5's parameter sweep was half-missing for Warden and entirely inert
for Grid and Sentinel, which read neither — the mechanism behind P-17's "20/20 windows identical".
`Params.kappa_scale` supplies the missing half and `quote(policy_factory=...)` lets an agent be
perturbed in its own parameters.

*Still true after all of this:* equation (2) still returns 2.88 ticks and is still dominated by the
floor. A9 remains open — the equation prices no adverse selection — and widening the floor does not
close it. What changed is that the floor is now derived from a published quantity instead of hiding
a known defect behind an unrelated constant.

### P-25 · Router's entire published behaviour was a statement about two constants nobody measured — **22 Aug 2026**

`replay/allocation.SwitchCost` shipped as two bare literals:

```python
gas_quote: float = 0.30
slippage_bps: float = 5.0
```

Neither had a source. `slippage_bps` was numerically identical to
`replay/driver.CostModel.slippage_bps` — an estimate for a **WBNB/USDT** recentre — while its
docstring claimed to be *"the full pool fee for swapping one underlying into the other"*. **There was
no USDT/USDC pool anywhere in this repository**, so no fee tier was ever consulted. The constant
simply wore the argument.

PancakeSwap runs USDT/USDC at the **0.01% tier** — `0x92b7807bF19b7Dddf89b706143896d05228f3121`,
verified three ways on 22 Aug 2026: 22,962 bytes of bytecode, `fee()` = 100, `tickSpacing()` = 1,
and a `factory()` equal to the one the address table verified independently. **One basis point, not
five**, and roughly ten times the depth of the 0.05% pool.

`gas_quote = 0.30` was worse. `core/types.DEFAULT_GAS_QUOTE = 3.0e-5` exists, and
the live source derives it live as `REBALANCE_GAS_UNITS * eth_gasPrice / 1e18`. Neither
was used. 250,000 gas units at BSC's measured 0.05 gwei, with BNB read from the indexed WBNB/USDT
pool at $607.31, is **$0.0076** — about **forty times** less than the literal.

**What those two numbers decided.** Everything — the hurdle, whether the agent ever supplied, and
the published quote:

| | before | after |
|---|---|---|
| round-trip hurdle | 5.84% | **1.06%** |
| entries / switches | 0 / 0 | it supplies, and moves when the edge clears |
| published quote | 0.00% – 0.00% | a real return on supplied capital |
| vs parking | *"beats parking by 3.90pp"* | **indistinguishable** |

The "after" column is deliberately unquantified beyond the hurdle. An earlier version of this table
carried eight exact figures and **six of them were stale within a day** — the rate tape grew from
seven days to sixteen, the venues changed leadership, and the annualisation gate added in the same
round flipped the published quote between a period figure and an annual one. The live numbers are in
the derived block in the judges' brief, regenerated by `make judges` from the card. A matrix entry is
a record of *what was wrong and why*; it is not a second place to keep the current figures.

The card said Router never supplied, and gave a 16-day break-even as the reason. Both were
artefacts. The agent had been priced out of its own market by a fee copied from a different pair.

**A third input compounded it.** `_move_cost` charged the full pool fee on *every* move, including
`park_policy`'s single ENTER — and entering vUSDT from a dollar position that is already USDT swaps
nothing. That phantom fee was 5.0 of the baseline's 5.6 total cost, so **roughly nine tenths of the
advertised 3.90pp advantage was a charge the baseline would never have paid**.
`replay/driver._move_cost` has carried the equivalent branch since P-18; this one had none.

**Resolution.** `SwitchCost` has **no defaults** — constructing one without inputs raises, naming
this finding. `SwitchCost.from_venue()` takes the fee from the verified pool's own `fee_pips`, gas
from a unit count times a gas price, and a native-token price to bridge BNB into dollars; every
result carries a `basis` string and a `derived` flag, and the card publishes both. The cost model
is the IO half that fetches them — gas price through the indexer's endpoint rotation, BNB/USD from
the swap tape's last observation of the pool this project already verifies and indexes.

**This is P-13 in a new venue, and the sentence P-13 ends with applies unchanged:** *"the quote it
produced was a statement about this constant rather than about the strategy."* The lesson that did
not transfer is that a cost model is not boilerplate to copy between agents — it is the thing being
measured, and every field of it needs a reading behind it or a label saying there is not.

*Related:* the same round found the driver sizing markets from `rows[-1]` — the **last** accrual on
the tape — so a window replayed on day one was sized by a market measured on day seven. A
look-ahead leak, in the project whose central claim is that look-ahead is structurally impossible.
The allocation tests now fails against that implementation.

### P-24 · There was a verified ERC-8183 deployment the whole time, and nobody had looked — **21 Aug 2026**

The ERC-8183 reader kept `JOB_ESCROW` empty on the stated grounds that *"the EIP is Draft and
lists no reference deployment addresses at all"*. Every word of that is true, and it was the wrong
question. The EIP publishes none; **the ecosystem does**. The Altana SDK ships an
`ERC8183_ADDRESSES` table with a kernel, an EvaluatorRouter, an OptimisticPolicy, a registry and a
payment token for BSC mainnet *and* testnet, and this repository had never read it.

One field in that table was independently checkable and checked out immediately: the `registry`
entry is byte-identical to `erc8004.IDENTITY_REGISTRY` on **both** chains — an address arrived at
here from the PancakeSwap side, months earlier. That is a reason to look, not a reason to believe,
so the ERC-8183 verifier looked, the same three ways the Venus verifier does.

**Every check passed, on both chains.**

| | chain 56 | chain 97 |
|---|---|---|
| kernel bytecode | 130 bytes (proxy) | 130 bytes |
| EvaluatorRouter / OptimisticPolicy | 130 / 4,413 bytes | 130 / 4,413 |
| payment token | 2,007 bytes | 2,007 |
| `jobCounter()` | **56,632** | 581 |
| `disputeWindow()` | 604,800s (7 days) | 86,400s (1 day) |
| kernel's `paymentToken()` vs the table | agrees | agrees |
| table's `registry` vs the ERC-8004 reader | byte-identical | byte-identical |

**56,632 jobs** is the number that separates this from the previous candidate. P-18's finding stands
without amendment — `TermixEscrow` is a real, USDT-settling escrow that implements none of ERC-8183
— but the conclusion drawn *from* it, that no verified deployment existed anywhere, was a claim
about our own search rather than about the chain.

**Three corrections to `steps()`, which had modelled the EIP rather than a deployment:**

1. **There is no `setProvider`.** The provider is an argument to `createJob`. This module's own
   docstring had already deduced that from TermiX's bytecode and never followed it through to the
   sequence. `steps(provider_known_at_creation=False)` now raises instead of pricing a shape the
   deployment does not support.
2. **Settlement is on a second contract.** `registerJob` and `settle` live on the EvaluatorRouter,
   not the kernel. A client sending all seven transactions to one address reverts on the third.
3. **The accessors are `jobCounter()` / `getJob(uint256)`**, not `nextJobId()` / `jobs(uint256)`.
   P-18 probed for the second pair and found neither — right about the contract, and partly wrong
   about the names.

The published transaction count therefore moves from **six to seven**, five of them the client's,
and it is still derived from `len(steps())` rather than written down.

**What did not change.** Nothing here signs. The hire button still does not exist and the ledger
entry still discloses it — escrowing a job means five signed transactions moving real USDT, which is
the same gate that keeps `make warden` on the recording executor.

*The lesson worth keeping:* the refusal was correct and the reason attached to it was not. "No
verified deployment exists" and "we have not verified a deployment" are different sentences, and
this file had been publishing the first while only the second was supported.

### P-23 · The toxicity threshold was calibrated against a null that real flow violates, and it is why the agent loses — **21 Aug 2026**

The advantage report reports the Warden **losing** to a passive baseline on both tasks where
the two differ: −64.29pp on Earn, −38.17pp on Protect. The proximate cause is visible in the card —
the agent is in range **6.1%** of samples and makes 249 mints against 249 pulls. It opens a position
and closes it again almost every step, and the costs of doing that are the loss.

The question worth asking is *why the pull fires that often*, and the answer is a calibration
mismatch rather than a coding defect.

Spec §3.4's second arm is `|imb_t| > z_pull`, with `z_pull = 2.5` over `M = 50` swaps.
The imbalance estimator computes `z = Σs / sqrt(Σs²)`, which is standardised **under a
permutation null**: each swap's direction an independent fair coin, magnitudes held as observed.
Under that null `|z| > 2.5` is a rare event, and 2.5 reads as a sensible threshold.

**Measured on the 30-day chain tape — 252,874 samples with a ready estimator:**

| statistic | value |
|---|---|
| median \|z\| | **2.179** |
| p75 | 3.190 |
| p90 | 3.905 |
| p95 | 4.264 |
| p99 | 4.801 |
| ceiling, sqrt(M) | 7.071 |

| threshold | fires on |
|---|---|
| \|z\| > 2.0 | 54.41% of samples |
| **\|z\| > 2.5 (the spec's)** | **41.94%** |
| \|z\| > 3.0 | 29.46% |
| \|z\| > 3.5 | 17.68% |
| \|z\| > 4.0 | 8.49% |
| \|z\| > 5.0 | 0.51% |

The median sample sits essentially **on** the threshold. Real AMM order flow is persistently
one-way over fifty-swap windows — it trends — so the fair-coin null badly understates the variance
of `Σs`, and a threshold chosen against that null classifies ordinary conditions as toxic. The rule
intended to catch exceptional adverse selection fires on nearly half of all market conditions, the
position spends 94% of its life withdrawn, and the re-entry cost is charged every time.

**Resolution: superseded by P-26 (25 Aug 2026).** The reasoning below stands as the record of what
was decided on 21 Aug and why. What changed is the classification, not the discipline: `z_pull` is
not a parameter that produced an unflattering result, it is a constant applied to a distribution it
does not describe — the V-1 class. The threshold is now a quantile of the measured distribution, and
the quantile is blind to outcomes. The original resolution follows.

**Original resolution: flag it, do not tune it.** The README rule 1 freezes the spec — *"if code and spec
conflict, the spec wins; flag it"* — and the judges' brief states the stronger rule that moving a
parameter because it produced an unflattering result is the fitting this project exists to refuse.
So `z_pull` stays at 2.5, the agent keeps losing in the published report, and **this is the
explanation rather than an excuse**: the loss is real, and its cause is a threshold whose null does
not describe the data.

What a calibrated threshold would look like is recorded here and **not** implemented: the table
above says `|z| > 4.0` is the 8.5% tail and `|z| > 4.8` the 1% tail. Choosing between them is a spec
change, which is a decision for the spec's owner and not for the run that noticed.

*Related:* **V-11** — the same arm had never fired at all before Sentinel was built, because the
engine passed a hardcoded `0.0`. It went from never firing to firing 42% of the time, and neither
state was ever measured against the tape until now.

### P-22 · The yield number every lending frontend quotes depends on a constant that is not on chain — **21 Aug 2026**

Building Router's venue model meant reading a supply APR off Venus. The obvious source is
`supplyRatePerBlock()`, which returns a per-block mantissa — and converting that to an annual figure
needs blocks-per-year.

**That constant is not readable from the chain.** Probed on vUSDT's own interest rate model
(`0x2cf0E211c99dfD28892cF80d142Aa27a9042dbf4`): `blocksPerYear()`, `getBlocksPerYear()`,
`blocksOrSecondsPerYear()` and `isTimeBased()` **all revert**. The Comptroller cannot answer either,
and its reverts are not evidence — `supplyCaps(address)` fails with `Diamond: Function does not
exist`, because the Unitroller is EIP-2535 and dispatches per facet.

So the number is a choice, and the choice moves the answer by more than six-fold:

| assumed blocks/year | implied supply APR (mantissa 308,220,494) |
|---|---|
| 10,512,000 — Venus's own documented 3-second blocks | **0.324%** |
| 31,536,000 — one second | 0.972% |
| 42,048,000 — 0.75 s | 1.296% |
| 70,080,000 — 0.45 s | **2.160%** |

**Resolution.** Do not read a rate; difference an accumulator. `borrowIndex` is monotone and every
other input — `cashPrior`, `interestAccumulated`, `totalBorrows` — is inside the `AccrueInterest` log
itself, so a realized rate can be recomputed from the tape with no constant at all and no chain state
re-read. Implemented in the APR estimator, published as **A12**.

**And the two methods agree, which is what makes either one trustworthy.** Realized supply APR across
four window widths on vUSDT: 2.1583% / 2.1599% / 2.1594% / 2.1590% — stable to 0.002pp across a
tenfold change in window — against a measured **0.450 s/block**, consistent to three decimals across
every window. The realized figure and the quoted-at-0.45s figure agree; Venus's documented 3-second
constant understates the rate by 6.67×.

Two decoding traps were met on the same reads and are recorded with it:

- **`vBNB.underlying()` returns zero bytes, not `address(0)`.** The market holds native BNB and the
  getter does not exist on it. A tolerant decoder maps it to the zero address and carries on.
  the Venus verifier's `_decode` raises instead.
- **Several `uint256` getters return 96 bytes, not 32.** `getCash()`, `supplyRatePerBlock()` and
  `exchangeRateStored()` each returned three words where the ABI declares one, while `borrowIndex()`,
  `totalBorrows()` and `reserveFactorMantissa()` returned one. The value is word 0 in every case,
  cross-checked against the accrual logs. Asserting `len == 32` would refuse three live getters;
  indexing by an unchecked position is **P-8** all over again.

### P-21 · D1 was decided against a number nobody had read, and the survey that would have read it was gated on a key it did not need — **20 Aug 2026**

The README carries an open decision item, D1:

> ERC-8004 registry population counted on BscScan. Decision rule: **< ~15 real agents** →
> third-party auto-cards demote immediately to a plain "registry view" and the narrative is
> "day-one marketplace for a day-one ecosystem."

Nobody counted. Measured on BSC mainnet by binary search on `ownerOf` — `totalSupply()` reverts,
because the registry is a 130-byte proxy and not `ERC721Enumerable`:

| | |
|---|---|
| agent ids the registry resolves | **272,322** |
| what D1 was written around | < ~15 |
| growth observed while working on this | ~1,100 per hour, across three measurements 70 minutes apart |

The rule was not wrong to exist; it was never evaluated. A "day-one ecosystem" narrative was one
unchecked assumption away from shipping beside a registry holding a quarter of a million
registrations.

**Two defects kept the number unread.**

*The survey was gated on `BSC_RPC_URL`.* The registry report returned `surveyed: false` with the
reason *"no BSC_RPC_URL configured — no registry read was attempted"* whenever the key was unset,
which was always. The refusal was correct in shape and wrong in precondition: the survey reads
`tokenURI` and `ownerOf`, which are `eth_call`, and every free BSC endpoint serves those. It is
`eth_getLogs` the free endpoints ration — P-11 — and this makes none. So the registry went
unsurveyed for the life of the project over a key it did not need, while `/registry` rendered an
honest refusal that nobody had cause to question. It now falls back to `PUBLIC_RPCS`, the same list
the indexer and the address verifier already walk.

*The sample was drawn from the front of the registry.* `rng.sample(range(1, sample * 20), sample)`
— at the documented `--sample 40`, ids **1 to 800**. Against a population of 272,322 that is the
oldest **0.3%**, and the oldest registrations are exactly the ones most likely to differ: the
deployer's own tests, and the earliest adopters. It would have reported a share about the registry
that was a share about its first fortnight. The bound is measured first now
(`erc8004.highest_agent_id`) and the draw spans it.

**What the first survey found.** 40 ids spanning 19,659–266,043, at block 117,023,742:

| | | |
|---|---|---|
| card resolves | 36 / 40 | 90% |
| declares itself active | 36 / 40 | 90% |
| card is on chain (`data:` URI) | 24 / 40 | 60% |
| **describes a service** | **12 / 40** | **30%** |
| **substantive** | **12 / 40** | **30%** |
| looks like a placeholder | 0 / 40 | 0% |

Nine in ten registrations resolve and declare themselves active. **Three in ten name an endpoint you
could actually call.** The gap between those two numbers is the whole finding: `declares_active` is
a self-report and costs nothing, and a registry that is 90% "active" and 30% callable is exactly the
kind of number a marketplace would otherwise print as "270,000+ agents".

`placeholders: 0` is not a clean bill of health — the heuristic catches repetition, and the junk
here is not repetitive. Sampled agent 19,659 is named `"57560"` and its description is a 69-digit
integer. `assess()` still refuses it, on the endpoint clause rather than the placeholder one, which
is the right answer reached by a different route than expected.

**What was built on it.** D1's rule says auto-cards are viable above ~15 agents and 272,322 clears
it, so third-party agents are now listed on `/registry` — and the listing is deliberately not shaped
like our own agent cards. Ours carry a P25–P75 range replayed from thirty days of chain history. A
third party's cannot: we do not have its policy, so there is nothing to replay. Every listing says
so on its face — *"No quote — we cannot replay a policy we do not have"* — and
a test asserts against the artifact that no field on a listing is
performance-shaped, using a whitelist so a field nobody thought of is refused by default.

That refusal is the point of the surface. The gap it leaves is where every other marketplace puts a
star rating.

### P-20 · The agent spends its whole daily budget leaving, and cannot afford to come back — **20 Aug 2026**

The first Agent Advantage Report generated from real chain data, and the headline is that hiring the
agent **loses 64 percentage points** to doing nothing:

| task | DIY | agent | delta |
|---|---|---|---|
| Earn | +4.78% to +27.21% | −52.10% to −49.97% | **−64.29pp** |
| Protect | +9.38% to +14.94% | −24.16% to −23.85% | **−38.17pp** |
| Choose | −620.55% to −617.83% | identical | +0.00pp |

Every number is real and none of them is a measurement of agents. From the artifact's own columns,
Earn, on 1.0 of capital over 30.2 days:

| | moves | in range | fees | costs |
|---|---|---|---|---|
| DIY (passive) | 1 | 6.6% | 0.0175 | **0.0008** |
| Warden | **498** | 6.1% | 0.0099 | **0.0466** |

The entire gap is transaction cost. **The first guess about why was wrong**, and instrumenting a
replay rather than reasoning from the aggregate is what caught it.

**The wrong answer.** P-17 established that the A-S half-width never escapes the anti-dust floor, so
the band is `w_min = 4 × tick_spacing` = ±0.401% on the flagship. A band that narrow against 17%
annualised volatility should be escaped constantly, forcing recentre after recentre — 498 moves in
30 days looked like exactly that.

**The measurement.** Seven days of the real tape, with the policy instrumented to record every
decision's gate terms:

    MINT 65 · PULL 65 · RECENTRE 0
    16 actions/day steady state = 8 pull-and-re-mint cycles, exactly max_rebalances_per_day
    re-entry blocked on 108,933 of 120,830 HOLD decisions = 90.2% of samples
    in_range 5.18%   costs 0.0129 over 7d on capital 1.0   fees 0.21x costs

**It never recentres. Not once in seven days.** The band width is not the mechanism, because the
recentring path is never taken. When the agent *is* in market, R1, R2 and R3 each decline a recentre
about 6,100 times apiece — drift, economics and budget all saying no.

**What actually happens** is three documented behaviours composing into one they do not describe:

1. **P-19** — §3.4's imbalance arm fires on **41.9%** of real samples, so the agent pulls constantly.
2. **`decide()` gates re-entry and never exit**, deliberately, and says so: *"an agent forbidden to
   exit because it had run out of budget would be held inside exactly the flow the rule exists to
   escape, and that is the one outcome worse than churning."* Leaving is free and always permitted.
3. **P-12** made the daily budget correctly persist across a pull — closing a real defect, where the
   counter used to reset on every re-entry.

Compose them and the day's eight actions are consumed entirely by *coming back*. Once spent, the
agent cannot afford to re-enter and sits flat until tomorrow. It is out of market **90%** of the
month, not because it is chasing price, but because it cannot pay to return. Gas alone is **67% of
capital annualised** while fees cover **0.21×** of it.

**None of the three is a bug, and that is the point.** P-12's fix was right; the asymmetric budget is
right and the comment defending it is correct; P-19's firing rate is the frozen spec's own `z_pull`.
The defect is in the composition, and it is invisible in any of the three read alone — which is why
it took a real tape and an instrumented replay rather than a code review.

**What was *not* done about it.** `z_pull` was not retuned and `max_rebalances_per_day` was not
raised. Both are spec section 8's published values, the spec is frozen, and moving a parameter
because it produced an unflattering number is the fitting this project exists to refuse. The report
publishes the number **and derives it**, in a section computed from the comparison's own fields with
no literals.

**What the report now shows.** `moves` is decomposed into mint / recentre / pull, because 498 reads
as a busy agent while 249 / 0 / 249 reads as an agent spending its budget on exits — different
findings, and only the second is what the tape says. And `distinct_returns` is published for the
first time: P-17 created it so a reader could see A5's ±25% (γ, κ) perturbation collapse when the
floor discards both parameters, and the deliverable the track judges had never carried it.

**Task 3 is a finding about a pool, not about an agent.** Its −620% band is A1's ceiling forcing the
position to 0.0318 — the ceiling is `eps × pool_liquidity`, a property of the venue — while
transaction costs stay fixed per action. At the largest size the 0.25% tier's own liquidity permits,
fixed costs exceed plausible fee income by a factor of fifty. That is the due-diligence answer to
*which pool should I provide liquidity to*: **not that one, at any size it can support.** Both
columns share the capital, so the delta remains sound.

### P-19 · On real flow, §3.4's imbalance screen does not separate two venues — **19 Aug 2026**

Task 3 of the advantage report asks whether screening a pool before entering it beats picking the
deepest one. Answering it on real data required a second real venue (WBNB/USDT 0.25%,
`0x1401ff94…`), and the first thing the second venue produced was a measurement of the screen itself.

**Section 3.4's imbalance arm, at the spec's own `z_pull = 2.5`, fires on:**

| venue | median liquidity | imbalance fires on |
|---|---|---|
| WBNB/USDT 0.05% (flagship) | 1.29e24 | **41.9%** of samples |
| WBNB/USDT 0.25% (wide) | 1.54e22 — **84× shallower** | **42.8%** of samples |

Two pools that differ by two orders of magnitude in depth, on the same pair over the same 30 days,
and the screen cannot tell them apart — 0.9 percentage points, in the direction that makes the
*deeper* pool look marginally cleaner. So the agent's due-diligence rule picks the same pool the
naive "more TVL is safer" heuristic picks, and task 3's honest answer is that screening bought
nothing here.

**This is P-7 again, on real flow rather than synthetic.** P-7 found the rule withdrawing roughly
once every four hours on a driftless random walk — `|z| > 2.5` on 1.34% of 44,802 samples against
≈1.24% predicted by the null — and concluded the threshold's suitability "depends on how much
genuine toxic flow the real tape carries, which synthetic data cannot answer." The real tape answers
it: **42%, on both venues.** A screen that fires on two samples in five is not selecting; it is
describing BSC.

**What was *not* done about it.** `z_pull` was not retuned. It is spec section 8's published value,
the spec is frozen, and moving a threshold because it produced an uninteresting result is precisely
the fitting this project exists to refuse. The number is published instead, on the task it affects.

**What the report does with it.** Task 3 states that both rules chose the same venue, and the delta
is exactly zero rather than a difference manufactured by handing the agent whichever pool depth did
not take — which is what the code did before this, and which would have reported an advantage that
was an artefact of the setup. The two columns are now each chosen by the rule that names them:
depth by `venue_depth`, the screen by the same `ImbalanceEstimator` Sentinel withdraws on.

**Two other things the second venue exposed**, both of which would have rendered a confident number:

- **A1 refused it outright.** A1's ceiling is `eps x pool_liquidity` and therefore a property of the
  *pool*. At the report's default capital the wide tier breached on **564 mints**, and A1 says such a
  quote is *refused rather than rendered* — so task 3 would have published nothing at all. Both
  columns now run at a capital derived from the binding venue's ceiling
  (`core.liquidity.capital_for_liquidity_cap`, the exact inverse of the cap branch), and the report
  records it **per task**: one report-level `capital_quote` described task 3 wrongly while looking
  authoritative.
- **The protocol fee differs again.** 3200 on the wide tier against 3400 on the flagship — P-8 a
  third time, three tiers of one pair, three different cuts. Each venue carries its own `PoolMeta`,
  because running both through one would credit the wide pool's liquidity providers with 66% of a
  fee they keep 68% of.

### P-18 · The one ERC-8183 escrow we had verified does not implement ERC-8183 — **19 Aug 2026**

The ERC-8183 reader shipped with `JOB_ESCROW` deliberately empty: the EIP is Draft, publishes no
reference deployments, and BNB's own SDK is testnet-only. It gained exactly one entry — TermiX's
`TermixEscrow` on BSC mainnet — on evidence that was real and, it turns out, entirely circumstantial:

| checked | result |
|---|---|
| bytecode present | EIP-1967 proxy, 170 bytes; implementation `0xbc8225ee…1e854` holds 17,941 |
| `settlementToken()` | `0x55d3…7955` — our `USDT_MAINNET`, and token0 of the flagship pool |
| identity registry | `0x8004A169…a432` — byte-identical to the ERC-8004 registry we already read |
| live config drift | zero mismatches across 16 addresses |
| **the job interface itself** | **never exercised** — and the evidence said so, in those words |

**Every row above is still true.** None of them is about ERC-8183.

**What the last row was hiding.** The recorded evidence noted that `nextJobId()`, `jobCount()` and
`jobs(uint256)` all revert, and read that as *"the accessors are named something else"*. They are
not. The implementation's dispatch table was recovered from the deployed bytecode — PUSH4 selectors,
resolved by keccak — and **none of the seven calls `steps()` models is present**: not `createJob`,
`setProvider`, `setBudget`, `fund`, `submit`, `complete` or `reject`, across **5,894 candidate
signatures** (every 0-, 1-, 2- and 3-argument shape over the eight common ABI types, plus the EIP's
own five-argument `createJob`).

What is there is an **order-keyed escrow**: `orders(bytes32)`, `acceptOrder(bytes32)`,
`protocolFeeBps()`, `feeRecipient()`, `reputation()`. Jobs are identified by a `bytes32` order id,
not the EIP's `uint256` jobId. That single fact explains every revert we had recorded — the calls
were never misspelled, the interface is different.

**A job was read back, and it agrees.** TermiX's `/api/v1/explorer/jobs` is public and needs no
credentials. `orders(bytes32)` returns a 13-word struct for a live order id, and word 3 is the
budget in 18 decimals: it matched the figure their own explorer publishes for the same order on
**20 of 20** live orders, exactly. That agreement with an independent source is what makes this a
decode rather than a plausible reading of arbitrary bytes.

**What is deliberately still not decoded.** No word in the struct separates their `SETTLED` orders
from their `PENDING_ACCEPT` ones — word 8 reads `4` on both — so this codebase does not claim to read
an order's state, and `ORDER_STATE_IS_UNDECODED` asserts that rather than leaving it as a comment.
21 of 65 selectors resolved; the other 44 are **counted, not guessed**.

**Resolution.** `JOB_ESCROW` was emptied and `escrow_address(56)` raised. It carries two entries again — a different contract entirely, verified three ways on both chains. See P-24. The rule that
mapping states — *no entry without evidence* — is now applied to itself: it is for verified **ERC-8183**
job escrows, and a real, well-behaved, fully-verified escrow that implements a different interface is
not one. The readings are kept under `FORMER_CANDIDATE_EVIDENCE`, because a rejected candidate is a
result and deleting it would erase the correction along with the claim. What the contract *is* now
lives in the AACP reader's `ESCROW_INTERFACE`, recorded as signature→selector pairs so the naming can
be re-derived rather than trusted.

**Verified by tests that run against the live contract**, not by the paragraph above:
A fork test asserts the three EIP accessors revert, that
`orders(bytes32)` answers, that the budget agrees with the explorer on every published order, and
that the USDT escrow returns an empty struct for a USDC order — the trap being that an unknown order
id returns thirteen zero words rather than reverting, so a caller pointed at the wrong settlement
book gets a confident, well-formed, entirely fictional order with a budget of zero.

**What this costs and what it buys.** The `/registry` page loses an escrow address, and the hire flow
goes back to publishing a refusal. `steps()` is unaffected: it describes what ERC-8183 requires, and
that description was never a claim about this contract. The transaction count still stands as the
answer to every competitor's one-click Hire button — it is now, accurately, a statement about the
standard rather than about a deployment.

> **Superseded in part, 22 Aug 2026 — see P-24 and P-25.** Two things above are no longer current,
> and the finding they rest on is. `TermixEscrow` still implements none of ERC-8183; that stands
> without amendment. What changed is the conclusion drawn from it. A *different* contract — Altana's
> AgenticCommerce kernel — passed the same three-way check on both BSC networks, so `/registry` does
> not publish a refusal and `JOB_ESCROW` is not empty. And the count is **seven**, not six: checked
> against a deployment rather than read off the Draft EIP, the flow has no `setProvider`, settles on
> a separate EvaluatorRouter, and needs a `registerJob` nobody had modelled. This paragraph is left
> as written because the reasoning was sound on the evidence it had, and deleting it would hide the
> more useful lesson — *"no verified deployment exists"* and *"we have not verified one"* are
> different sentences.

### P-17 · The Avellaneda–Stoikov half-width never reaches the anti-dust floor — **18 Aug 2026**

Correcting σ (P-15) should have widened every range by 3.6×. It changed the width by **nothing**, and
finding out why is the most consequential result of this project so far.

Spec §3.2 sets `w_t = max(w_min, round_to_spacing(δ*/ln 1.0001))` with `w_min = 4 × tick_spacing = 40
ticks`. Equation (2)'s δ*, at the volatility measured on the 30-day tape (17.0% annualised) and the
κ fitted for G-4:

| γ (the published risk dial) | equation (2) | width used |
|---|---|---|
| 0.2 | 2.86 ticks | 40 (floor) |
| 0.5 | 2.97 ticks | 40 (floor) |
| 0.8 (default) | 3.09 ticks | 40 (floor) |
| 2.0 | 3.57 ticks | 40 (floor) |
| 5.0 | 4.75 ticks | 40 (floor) |

**The floor binds across the entire published parameter range, by a factor of 8 to 14.** Equation (2)
only overtakes it above **σ ≈ 0.09 per √hour — 849% annualised**. That is not a market this pool has.

So the range half-width — the thing the flagship agent exists to compute, and the headline of the
A-S ↔ v3 mapping — is set by an anti-dust constant, and the model's contribution is discarded.

**G-4 made it worse, and that is worth stating plainly.** With the provisional κ = 500 the model
produced **20.3 ticks**: still under the floor, but within a factor of two of it. Fitting κ properly
raised it to 3600.9, which *shrinks* the `ln(1 + γ/κ)` term and drops δ* to **3.09 ticks**. Measuring
the parameter more carefully moved the model further from mattering.

**And it hollows out A5's parameter spread.** A5 builds half the quote's range by perturbing (γ, κ)
±25%, counting each window three times. If the floor discards both parameters, those three replays
are one replay. Measured on the tape:

| agent | windows where all three perturbations are identical | distinct returns of 60 |
|---|---|---|
| Grid | **20 / 20** | 20 |
| Sentinel | **20 / 20** | 20 |
| Warden | 17 / 20 | 23 |

Grid and Sentinel read neither γ nor κ — Grid's own docstring says "No Avellaneda–Stoikov, no sigma,
no kappa" — so for them the perturbation is inert by construction and **60 reported samples are 20
results counted three times**, against an A5 floor of 20. Warden keeps a little: the width is floored,
but γ still moves the range *centre* through equation (1), which changes the outcome in 3 windows of
20.

**Resolution, in two parts.** `Quote` now carries `distinct_returns` beside `samples`, so the
difference is published rather than inferred — `samples` still counts replays because that is what
A5's floor is written against. The larger question is not a code fix: **A9 already records that
equation (2) prices no adverse selection and is systematically too narrow on an arbitrage-dominated
venue.** This is the quantitative form of that assumption. The honest reading is that on this pool,
at this tick spacing, Warden's range width is a dust floor with a model attached, and the card should
not imply otherwise.

### P-16 · Equation (3) clamps the holdings *and* the price; only one of those is right — **fixed 18 Aug 2026**

With costs and σ corrected, LVR is the largest term in the quote, so it was worth checking against
something that is not itself. Fees had already been verified this way and agreed to 0.0e+00; LVR had
`closed_form_lvr`, which is a genuinely independent derivation — but it only covers the case where
**both endpoints are in range**, and Warden runs narrow ranges and leaves them constantly.

Spec §3 distinguishes two prices, and it is easy to miss because the clamped value is right there:

> "the position's holdings change by (Δx_k, Δy_k) **along the bonding curve**. The rebalancing
> benchmark executes the same Δx_k **at the post-swap price P_k**."

The *holdings* stop at the range edge — that is what clamping is for, and it is worth a great deal
(P-3). The *valuation* is at the market price the swap ended at, which on a swap that leaves the
range is beyond the edge. `absorb` used `self._price(s1)`, the clamped sqrt price, for both — so it
understated the arbitrageur's edge on exactly the swaps that carried price out of the position.

**Measured before claiming, and the measurement mattered.** A constructed 600-tick single swap shows
the difference as **11×**, which would have been an alarming headline. On the real 30-day tape it is:

| range | ratio | boundary-crossing swaps |
|---|---|---|
| ±60 ticks | **1.04×** | 73 of 40,000 |
| ±400 ticks | **1.00×** | 0 |

A pool this liquid does not move 600 ticks in one swap. So: a real deviation from the frozen spec,
worth about **4%** of LVR on a narrow range and nothing on a wide one. Both halves are the finding —
the constructed case would have justified far more alarm than the data supports.

**And it inflated a published number.** This repository has recorded that *"LVR range-clamping is
worth up to 134× on a narrow range"*. That ratio was measured through the bug: understating the
clamped figure inflates the clamped-versus-naive comparison. With equation (3)'s actual post-swap
price the honest figures are:

| range | 500-tick move | 2,000-tick move |
|---|---|---|
| ±60 ticks | 4.4× | **16.9×** |
| ±400 ticks | 1.0× | 2.8× |

Clamping the holdings is still worth a great deal on the narrow ranges this agent runs. It is worth
**up to ~17×, not 134×**, and the test that guarded it asserted `> 50` — a threshold only reachable
with the bug in place.

**The general lesson, and it is the fourth time today.** T4 was named for a check it does not perform;
`closed_form_lvr` performs a real check but only over the regime the agent is rarely in; and the
clamping test's threshold was calibrated against a defect. A test can be honest, well-named and
green while covering the case that does not matter.

### P-15 · The volatility estimator threw away three quarters of the variance — **fixed 18 Aug 2026**

Once P-13 and P-14 stopped costs from dominating, **LVR became the largest term in the quote** — about
eight times fee income — which made it worth asking whether its inputs were right. The card reported
`sigma_per_sqrt_hour = 0.00045`, which annualises to **4.2%**. BNB does not have 4.2% volatility.

Computed directly from the same 30-day tape, using the estimator's own one-minute bucketing:

| | σ per √hour | annualised | share of returns clipped |
|---|---|---|---|
| raw | 0.00218 | **20.4%** | — |
| **as shipped** (`5 × median |r|`) | 0.00060 | **5.6%** | **27.8%** |
| clip at p99 | 0.00181 | 17.0% | 1.0% |
| clip at p99.9 | 0.00205 | 19.2% | 0.1% |

**An outlier filter that discards 27.8% of the sample is not containing outliers.** It is reshaping
the distribution, and σ sets the range half-width in equations (1) and (2) — so ranges were built on
a volatility roughly **3.6× too low**, which is the most likely explanation for Warden sitting in
range only 6.1% of the time on real flow.

**Why the threshold was wrong, and it is the κ-units mistake in a new place.** The rule was
`5 × median absolute return`, ported unchanged from PolyLambda, where it clips **logit returns of
probabilities** in prediction markets. The sigma estimator says so in its own header: *"the EWMA
recursion, the winsorising, and the shrinkage toward a prior are unchanged, because they were doing
the right thing already."* Nobody measured whether they were. On a busy AMM pool most one-minute bars
barely move while a few move a lot, so the **median absolute return is 128× below the RMS** and
`5 × median` lands near the middle of the sample rather than out in its tail. A statistic calibrated
on one distribution, applied unchanged to another — exactly V-1's shape, where κ was fitted per tick
and consumed per log-price.

**This one is ours, not the spec's.** §5.1 specifies "EWMA of 1-minute log-returns of pool price,
half-life 6h, scaled to per-√hour" and says **nothing about winsorising**. The rule is an addition
beyond the spec, so both its existence and its threshold are ours to justify.

**Resolution.** Clip at a **quantile** rather than at a multiple of a scale statistic. A quantile
clips the fraction it names on any distribution, which is what an outlier filter is supposed to
promise; a multiple of the median only does so on distributions shaped like the one it was tuned on.
`WINSOR_QUANTILE = 0.99` removes 1.0% of observations and reads 17.0% annualised on this tape. The
original concern the comment names — one thin-pool print that reverts and then dominates a six-hour
EWMA — is still met, because that print is in the top 1%.

A test caught a flaw in the first version: `int(n × q)` lands on the largest element itself for small
samples, so a 21-return sample clipped nothing. The usual quantile index is `(n − 1) × q`.

### P-14 · The position was never the size we divided by, and A1 was a clamp — **fixed 18 Aug 2026**

Grid earned **0.164 of token1 on "1,000 of capital" over thirty days**. Chasing that number rather
than accepting it found P-13's cost model, and underneath it two more.

**`_size` never split the capital.** It passed `capital_quote` as *both* token amounts and let
`get_liquidity_for_amounts` take whichever bound. On USDT/WBNB that is 1,000 USDT beside 1,000 WBNB —
**$1,000 beside $613,000** — so the cheap leg bound, the curve pulled 1.63 WBNB alongside it, and the
position deployed **~2,000 USDT of value while every return was divided by 1,000**. The docstring
said *"split the capital the way the curve will hold it at this price."* Nothing split anything.

**A1 was a clamp, not a refusal.** Its published text is unambiguous — *"quotes that would breach ε
are **refused rather than rendered**"* — and the driver clamped liquidity to 1% of the pool and
published the quote anyway. Measured against the target pool's real liquidity, A1's ceiling is:

| range | largest position A1 permits |
|---|---|
| ±20 ticks | **1.03 WBNB** (~$631) |
| ±60 ticks | **3.09 WBNB** (~$1,892) |
| ±1000 ticks | **50.26 WBNB** (~$30,810) |

So the default of 1,000 breached A1 in **every range this pool supports**, and nothing said so —
not the number, not the note beside it. `DEFAULT_CAPITAL_QUOTE` is now **1.0**, which fits the
narrowest range with margin, and a breach refuses with its count rather than clamping.

**The two bugs concealed each other.** Passing the amounts wrongly happened to size a ~$1,000
position, which sat under the cap; so the sizing defect kept the A1 defect invisible, and fixing the
first exposed the second. Neither could have been found by reading either one alone.

**Fifth instance of the rule, and L1 has caught three of them.** `_size` existed identically in
`ReplayDriver` **and** `WardenLive`; correcting one diverged the drivers and L1 failed on the next
run. It is `core.liquidity.liquidity_for_capital` now — after the position bookkeeping (V-?), the
trailing fee window, the action cap (P-12) and the gas constant (P-13).

**What this changes about the published quote.** With sizing, costs and A1 all correct, the numbers
stop being artefacts of a constant and start describing the strategy: on a synthetic 9,000-swap tape
Warden reports fees 0.0028 against **LVR 0.0209** — adverse selection exceeding fee income by roughly
eight times, which is what the LVR literature predicts for passive liquidity and what the previous
cost model had buried entirely.

### P-13 · The published quote was a statement about a constant — **fixed 17 Aug 2026**

Chasing why Grid earned 0.164 of token1 while paying 26.0 in costs led somewhere worse than P-12's
churn. **Assumption A4 describes a cost model the replay driver did not implement**, and A4 is not an
internal note — it is in the sheet a judge is invited to audit:

> "10 bps of **rebalanced notional** … plus gas at the gas price **prevailing in the historical
> block** … plus modeled slippage against the pool's **actual liquidity at that moment**"

| A4 promises | the driver did | factor |
|---|---|---|
| 10 bps of the rebalanced notional | 10 bps of the **whole position** | position ÷ notional |
| gas at the historical block's price | hardcoded `gas_quote = 0.5` | **16,667×** |
| slippage vs the pool's actual liquidity | flat 5 bps of the whole position | — |

**The gas figure is the sharpest.** The live source computes exactly this quantity from the
chain — `REBALANCE_GAS_UNITS * eth_gasPrice / 1e18` — and at BSC's prevailing 0.05 gwei that is
600,000 × 5e7 / 1e18 = **3.0e-5 BNB, about two cents**. The constant claimed in its own comment to be
a "trailing median gas × price". Nothing had measured it.

**The notional is the more interesting one.** `Engine._inventory` already computes A4's base —
`abs(value0 - value1) / 2`, *"half the imbalance, not the whole position"*, in its own comment — and
hands it to the policy as `rebalance_notional_quote`, where **R2 uses it to decide whether a move
pays for itself**. The driver then charged that same move against `capital_quote`. So the gate
deciding whether to move and the ledger charging for it were reading different numbers, and on a
well-centred position they differ by orders of magnitude.

**Why it survived.** Both errors run *pessimistic*. A project whose entire thesis is "we publish the
number that makes us look worse" is the least likely thing in the world to interrogate a number that
is unflatteringly large — and the docstring's "deliberately conservative" supplied a ready
explanation for any figure that looked too harsh. **Being wrong in the conservative direction is
still being wrong**, and it is the harder direction to notice, because every incentive that normally
catches an error is pointing the other way.

**Two guards fired during the fix, and both were right.**

*L1 went red.* The gas constant lived in `CostModel` **and** in `chain.source.TapeChainSource`, so
correcting one changed what the two drivers charged for the same move. That is the **fourth** time
the answer has been *one constant, both readers* — and the first time the tripwire caught it inside a
single test run rather than weeks later. It now lives in the core types as `DEFAULT_GAS_QUOTE`.

*A cost test went red, and it was right.* The first fix used A4's imbalance base for **every** move.
But a flat position has `value0 == value1 == 0`, so A4's formula reads zero there and **every opening
mint would have been slippage-free**. Entering swaps roughly half the capital into the other token;
adjusting swaps only the drift. The cost of entering is not the cost of adjusting.

**Recorded, not fixed.** A4 also promises gas "prevailing in the historical block". The swap tape has
no gas column — the schema never had one — so a replay charges *today's* gas for a move made three
weeks ago. Indexing per-block gas prices would close it. Written down rather than quietly meeting the
weaker standard and calling A4 satisfied.

### P-12 · The agent left and came back 2,585 times, and nothing counted — **fixed 17 Aug 2026**

The first quote ever produced from the 30-day chain tape, and it is not a quote of anything anyone
would run:

| | mint | recentre | pull | costs | fees | net | quote |
|---|---|---|---|---|---|---|---|
| Warden | **2,585** | **0** | **2,584** | 5,170.00 | 0.234 | −5,169.83 | −6,851% |
| Sentinel | 1,761 | 0 | 1,760 | 3,522.00 | 0.044 | −3,521.97 | −4,488% |
| Grid | 1 | 12 | 0 | 26.00 | 0.164 | −25.90 | −33.7% |

A pull-and-return every seventeen minutes for a month, spending **5.2× the deployed capital** on gas,
slippage and the MEV haircut to earn 0.234 of token1. Grid never pulls and looks ordinary, which is
what pointed at the pull path rather than at the cost model — and the arithmetic confirms the costs
are correct *for the number of actions*: 2,585 × (0.5 gas + 0.5 slippage + 1.0 MEV) = 5,170 exactly.
The action **count** was the defect.

**Synthetic data could not have found this.** P-7 measured §3.4's toxicity rule firing 16 times in 62
hours on a driftless random walk — 0.26/hour, every one a false positive. Real BSC flow fires it at
**3.6/hour, roughly fourteen times as often.** The rule is behaving as specified; the specification
never considered how often "as specified" would be.

**Two causes, both invisible until a tape was busy enough.**

*The daily budget reset on every return.* `apply_decision` set `rebalances_today = 0` whenever
`current.in_market` was false — which is true of every re-entry after a pull. The PULL branch three
lines above deliberately carries the count forward and says so: *"an agent cannot reset its own daily
limit by pulling and re-minting."* The very next action discarded it. **The comment described a
defence the code did not provide.** `token_id` cannot be the discriminator, because PULL nulls it and
should — on chain the NFT really is burned. `last_rebalance_ts` is what survives, and is zero only on
a position nothing has ever acted on.

*Nothing bounded the return at all.* §3.4 caps rebalances and is silent on how often a position may
leave and come back, so the re-entry path checked only `clear_streak >= m_clear` and `not toxic`.

**And the live loop had already noticed.** The Warden loop caps `actions_executed` at
8/day; the replay engine had no cap whatever. So the replay was pricing **5,169 actions where the
live agent would have performed 240** — the two drivers were not running the same agent in any
economic sense, and the published quote described behaviour the live agent would refuse. **L1 cannot
see this**: L1 compares decisions, and the cap sat above the decision layer in one driver and nowhere
in the other. This is the third time the fix has been *move the thing into the shared layer rather
than maintain it twice*, which is now a rule rather than an observation.

**Resolution.** The budget lives in the policy, below both drivers, and is **deliberately
asymmetric: it gates coming back, never leaving.** An agent that cannot afford to re-enter sits flat,
which is safe and costs nothing. An agent forbidden to *exit* because it had spent its budget would
be held inside precisely the flow the rule exists to escape — the one outcome worse than churning. A
test asserts a pull is still granted at ten times the daily cap.

**Deviation, recorded rather than resolved:** §3.4 does not authorise a re-entry budget. It is
imposed because the spec is silent and the silence costs 5.2× capital on real flow, and because the
live loop had already imposed its own version unilaterally. The spec-faithful reading is the one in
the table above.

### P-11 · Two of our three endpoints could never serve logs, and the health check said they were fine — **fixed 16 Aug 2026**

P-10 gave the tail a voice, and it spent the next day using it: four consecutive refusals on the same
2,000-block range, backing off to fifteen minutes, having advanced **not one block in twenty-four
hours**. P-10 records the cause as quota drained by concurrent anvil forks. That was wrong, and the
backoff hid it — by the time the counter-evidence arrived it looked like confirmation.

**Three measurements, one request at a time, each ruling out an explanation:**

| Question | Measurement | Rules out |
|---|---|---|
| Is it the rate? | `eth_blockNumber` answered instantly by the endpoint refusing `eth_getLogs`, same connection | a rate limit |
| Is it the depth? | identical refusal at the head and 178,000 blocks back | pruning / historical depth |
| Is it the width? | a **one-block** query refused | a range cap |

None of them. `eth_getLogs` is unavailable to us on those hosts — not rationed, not capped, absent.

**Surveying 22 public BSC endpoints, three serve logs:**

| Endpoint | `eth_chainId` | `eth_getLogs` |
|---|---|---|
| `bsc.rpc.blxrbdn.com` | 56 | **serves**, ≤5,000 blocks |
| `rpc-bsc.48.club` | 56 | **serves**, ≤5,000 blocks |
| `bsc-rpc.publicnode.com` | 56 | **serves**, 403s under burst |
| 4× `bsc-dataseed*.bnbchain.org`, 2× `defibit.io`, `ninicoin.io` | 56 | **`-32005` at every width** |
| `1rpc.io/bnb` | 56 | serves, declared cap **50 blocks** |
| `bsc.blockrazor.xyz` | 56 | serves, declared cap **25 blocks** |
| `meowrpc.com` | 56 | `eth_getLogs is not supported` |

The last two are usable and still useless for this: keeping level with the head costs 8,000 blocks an
hour, which at one request a minute is **134 blocks a request**. A 50-block cap cannot sustain a tail
whatever the poll rate.

**Which makes the defect ours.** `connect_all` kept every endpoint answering `eth_chainId` with 56 —
and all eight of the log-refusing hosts do, in milliseconds. Two of our three configured endpoints
could never do the job the module exists for, and the health check could not tell, because it tested
the cheapest capability rather than the one the caller was about to use. **A tail refused on every
request is indistinguishable from a tail working perfectly on a pool nobody is trading.**

This is V-11's shape exactly: a gate that cannot fail, passing, while the thing it was meant to
protect is broken. V-11 was a toxicity arm fed a literal `0.0`; this is a health check fed the wrong
question.

**Before adding the two new endpoints, they had to agree.** The reader rotates on failure, so one
range can come from one host and the next from another, and two hosts disagreeing about a block would
produce a tape blended from two histories with nothing downstream able to notice. Asked for an
identical 2,000-block range all three returned **73 logs, identical transaction hashes, identical
data, identical order**.

**The fix.** `serves_logs(w3)` — one block, one address that holds no logs, so a healthy node answers
`[]` in milliseconds. `connect_all(..., needs_logs=True)` filters on it; `connect`, which serves the
registry and the write path, still selects on chain id and is not charged for a probe it does not
need. `on_reject(url, why)` reports every dropped endpoint, so an operator whose own keyed
`BSC_RPC_URL` fails the probe hears about it rather than wondering why their key seems unused.

**The probe is cheap only because the refusal was measured not to depend on the response.** The
refusing hosts refuse this exact empty one-block query too. Had they been refusing on result size, an
empty probe is the query they would most gladly serve, all eight would have passed, and this would be
one more check that cannot fail. Two extra requests to rule that out, and they were the two that
mattered.

**Two numbers found on the way.** Both log-serving endpoints declare a **5,000-block ceiling**
(5,000 served, 10,000 refused with `exceed maximum block range: 5000`), so `DEFAULT_CHUNK` moves from
2,000 — never a measured limit, just what the old set tolerated — to 5,000: the same history for 40%
of the requests, and requests are the rationed thing. And `blxrbdn` goes ahead of `48.club`, whose
latency was **~41s regardless of width, refusals included**; a fixed 41s with nothing to compute is a
queue in front of a node, not work, and it sits uncomfortably close to a 60s poll.

**Verified live:** 4 polls, 0 refused, 214 real swaps, both dead endpoints skipped by name.

**And on Chapel it is worse — surveyed 18 Aug 2026, of eleven public testnet endpoints exactly
one serves `eth_getLogs`.** Every `data-seed-prebsc-*` host, `bsc-testnet.bnbchain.org` and
`bsc-testnet-dataseed.bnbchain.org` answer for chain 97 and refuse every log query with the same
"limit exceeded". `https://bsc-prebsc-dataseed.bnbchain.org` is the only one that does not.

Both endpoints `PUBLIC_RPCS[97]` held were in that group — one unreachable, one log-refusing — so
**the 24-hour testnet burn-in could never have started**, and before the capability probe existed it
would have failed as a tail that polled forever and wrote nothing. It now refuses at connect time
and names the reason. Worth stating plainly: **one working endpoint is no redundancy.** A burn-in on
Chapel stops entirely if that host does, and rotation has nowhere to go. That is a reason to want a
keyed testnet RPC, not a reason to pretend the risk is absent.

**And then the thing it was blocking, done.** A 30-day backfill of the target pool, on free
endpoints, with `BSC_RPC_URL` unset:

| | |
|---|---|
| chunks | **1,151**, zero refused, zero rotations |
| wall clock | **3,737s** (62 minutes) |
| written | **251,194 swaps**, 5,553 mints, 6,544 burns |
| coverage | **one unbroken run**, 110,495,529 → 116,254,249 — 29.99 days |

The two measures agree — `30.0d between the two ends` and `30.0d read` — which is what a tape with
no holes in it looks like, and the first time this project has been able to say that rather than
assume it. The readiness gate now reports **PASS: 251,194 swaps, 30.0 unbroken days read from
chain**, and the go/no-go's top blocker, recorded since Step 8 as "needs a keyed `BSC_RPC_URL`",
was never about the key.

**The general form, and it is the third instance:** *a measurement that cannot attribute its own
result will be over-read.* `BscReader` rotates silently and reports only a rotation count, so D-9's
"all three endpoints exhausted / 6 of 6 succeeded" was really a statement about whichever endpoint
happened to answer — and the six successes were very likely all served by the one endpoint that
works. The instrument could not see the thing that mattered, so the conclusion drawn from it named
the wrong cause, and that wrong cause sat in this document for two days looking measured.

### P-10 · The tail could not tell you it was failing, and the endpoints are shared

Left `misquote.indexer.follow` running unattended to accumulate a real tape. Thirty-five minutes
later it had written **a zero-byte log and advanced not one block**.

Two defects, and the second is the one that hid the first.

**The endpoints are a shared, exhaustible resource across *tools*, not just across copies of this
process.** anvil forks from the same public nodes and proxies *every* state read to them, so running
the chain-fork suite — thirteen tests, a minute of mints and burns — exhausts the `eth_getLogs` quota
and leaves the tail refused with `-32005` for as long as it takes to refill. Measured directly
afterwards: `safe_head()` answered fine, and a 2,000-block `eth_getLogs` on the very next range came
back refused.

> **That diagnosis was wrong — see P-11.** The two observations are real and so is the anvil
> contention, but they do not add up to the conclusion. `safe_head()` answering while `eth_getLogs`
> refuses is not evidence of a drained quota; it is evidence that the endpoint serves one method and
> not the other, which is exactly what it turned out to be. The refusal was permanent, not
> refilling, and no amount of waiting would have fixed it. Backing off was still the right thing to
> build — it is what let the tail survive a day of this without hammering anyone — but it also made
> the counter-evidence arrive slowly enough to look like confirmation.

**And `follow` printed only on success.** Its progress line was inside
`if result["events"] or result["primed"]`, so a tail refused on every single poll produced *no
output at all* — indistinguishable from a tail working perfectly on a pool nobody was trading. The
same shape as the `LiveChainSource.status()` counters, which exist for exactly this reason; the tail's
own progress output had never been given the same treatment.

**Fixed.** A refusal now prints, with a running count of consecutive refusals, and the poll interval
**backs off** (×2, capped at 15 minutes) rather than hammering a node whose quota refills with time
rather than with persistence. Recovery prints too, so a tail that comes back says so. The summary
names the anvil interaction explicitly, because "wait for the quota to refill" is not guessable from
`-32005`.

Two tests: one asserts the word REFUSED reaches the output, one asserts a 0.3-second window admits
fewer than twelve attempts rather than thirty.

**The general form, and it has now cost this project twice:** a process whose failure mode is silence
is worse than one that stops. The first instance was the engine reporting toxicity rates of zero
before it had a verdict; this is the second.

### P-9 · The live loop had two execution paths — **fixed 16 Aug 2026**

Building the chain executor made a latent design problem concrete, and the fix needed the executor to
exist before it was safe to attempt.

**What was wrong.** `WardenLive.step()` called the executor and *then* applied the decision, which is
correct on its own. But `WardenLoop` kept a **second** path: `_decide_forever` called `step()` — which
had already executed — and *also* queued the same decision for `_execute_forever`, which called its
own `executor_call`. Three consequences:

- **Every decision was acted on twice**, unless one of the two executors was inert. In production it
  was: `WardenLive` held a `SimulatedExecutor` and `executor_call` held a `RecordingExecutor`, so
  nothing broke *because nothing could act*. Wiring a real executor to either would have broken it.
- **Failure did not roll back.** `_execute_forever` journalled `failed:` and left the engine alone,
  because `step()` had already committed the position.
- **The loop's safety machinery governed the inert path.** `max_actions_per_day` reads
  `stats.actions_executed`, incremented only on the queue path — so actions performed inside `step()`
  were never counted against the cap. Same for the staleness drop.

**The constraint that shaped the fix.** `Engine.set_position` rebuilds the `LvrAccountant`, and the
next `engine.step` observes that position — so deferring execution by even one sample changes the
observation feeding the policy, and **L1's byte-for-byte fingerprint** with it. The split therefore
happens *below* `step()`, which keeps its exact previous behaviour:

| | |
|---|---|
| `decide(t)` | observe, ingest, decide. Executes nothing, applies nothing. |
| `perform(d)` | execute, **then** apply — and only on success. |
| `step(t)` | `decide` + `perform`, unchanged. What `run_until` and L1 use. |

The loop uses the halves; every synchronous caller uses `step`. L1 was run after each edit rather
than at the end, and stayed green throughout.

**A consequence worth publishing rather than engineering away:** the loop's decisions can now diverge
from a replay's, because a replay assumes execution is instantaneous and always succeeds. A live
agent whose transaction takes three minutes to confirm genuinely does not hold the position yet. That
is reality, not a defect, and L1 continues to compare the *policy*, which is what it always claimed.

**Partial failure is now a distinct outcome.** A recentre closes before it opens, so a failure between
the legs leaves the wallet flat and solvent — but left the engine believing it held a range that no
longer existed, and it would never re-mint because it thought it was already in.
`PositionClosedNotReopened` carries the dead token id; `_execute` catches it, puts the engine flat to
match the chain, and re-raises so the loop still journals the failure.

**And the agent now asks the chain what it holds.** `ChainExecutor.observe()` enumerates the wallet's
NFPM tokens — Pancake's manager is `ERC721Enumerable`, `supportsInterface(0x780e9d63)` verified on
mainnet rather than inferred from Uniswap's ABI — and returns the live position in *this* pool,
matched on `(token0, token1, fee)` because the same pair runs at four tiers. Without it a restart
believes it holds nothing, mints a second position, and orphans the first: capital in the pool with
no fee accounting, no rebalancing and no kill switch pointed at it. That single failure is what made
an unattended 24-hour run unsafe.

**It refuses when the answer is ambiguous.** A wallet holding *two* live positions in one pool cannot
say which is the agent's, and adopting one would leave the other unmanaged — so `observe()` raises
and names them both. Found by test ordering: the fork suite's earlier tests left positions behind and
the third one adopted the wrong one.

**Also, while the fork suite ran:** a pruned upstream node (`missing trie node`) now reports as a
**skip** rather than a failure, naming `BSC_ARCHIVE_RPC_URL`. A suite that is intermittently red for a
reason nobody can fix teaches people to ignore it being red for a real one.

### P-8 · Two pools on the same DEX, two different protocol fees — **corrected 15 Aug 2026**

> **This item was published wrong, by us, and the correction is more useful than the original.**
> The first version claimed TSLAx/USDT reports `feeProtocol = 0` — that LPs keep the entire fee on
> that venue. They keep 68%. The reader took **`slot0[2]`**, which is `observationIndex`, instead of
> **`slot0[5]`**, which is `feeProtocol`.

**P-1** established that PancakeSwap takes 34% of every fee on our WBNB/USDT pool, where Uniswap's is
off by default, and that reconstructing fees from volume overstates LP earnings by **1.52×**.

Resolving a tokenized-equity venue for the equities category turned up the other half of that lesson.
Read correctly:

| Pool | raw `slot0[5]` | decoded | LP keeps | Effective fee |
|---|---|---|---|---|
| WBNB/USDT 0.05% | 222,825,800 | **3400** | 66% | 0.033% |
| TSLAx/USDT 0.25% | 209,718,400 | **3200** | 68% | 0.170% |

Pancake packs the field as `fee0 | (fee1 << 16)`, both `uint16`, so 222,825,800 is 3400 twice and
209,718,400 is 3200 twice.

**The finding survives in kind, not in degree.** Two pools on one DEX really do charge different
protocol fees, so no constant is right for both and `PoolMeta.fee_protocol` still has **no default**.
But it is 34% against 32%, not 34% against nothing, and the dramatic version was an artefact.

**Why it survived.** Index 2 held `101` on the flagship and `0` on the equity pool — small, plausible
integers. Nothing reverted, nothing looked absurd, and `0` was *exactly* the value that made an
interesting story. A wrong number that confirms a thesis gets less scrutiny than a wrong number that
contradicts one, which is the general lesson and the uncomfortable one.

**What caught it.** Not a test — two numbers in the same repository disagreeing. The new pool badge
printed `feeProtocol 100` for a pool the address table records as `3400`, and the discrepancy was
visible only because both were on screen at once. So the badge reader now performs that comparison
itself: **"recorded values match chain"** fails when a constant in this repo no longer matches what
the chain returns. A constant nobody re-reads is a constant that rots.

**The equities venue is thin, and that is stated rather than smoothed over.** TSLAx/USDT 0.25% is the
*only* xStocks v3 pool on BSC with usable liquidity (1.58e18). NVDAx and AAPLx are bridged to BSC and
have **no v3 pool at any fee tier**. The 1.00% TSLAx/USDT pool exists with **zero** liquidity — a
pool on paper, correctly refused by the discovery script's liquidity floor rather than quoted.

**Thin was generous — measured 16 Aug 2026, it barely trades at all.** Liquidity is a stock; what a
replay needs is flow. Three 5,000-block windows spread across the last thirty days, both pools, same
request:

| Window | TSLAx/USDT 0.25% | WBNB/USDT 0.05% |
|---|---|---|
| 30 days ago | **0 swaps** | 473 |
| 15 days ago | **0 swaps** | 325 |
| 1 day ago | **1 swap** | 171 |
| implied | ~13/day, **~384 over 30 days** | ~12,400/day, ~372,000 over 30 days |

Roughly a thousandfold apart, and the equity figure rests entirely on a single trade. **So there is
no equity tape, and there will not be one.** A 30-day history of ~384 swaps cannot support a
P25–P75 quote: `verdict(min_n=30)` would refuse it, correctly, and cutting it into the ≥20
sub-windows the range replay requires leaves ~19 swaps each.

**What survives, and what does not.** The pool remains a *generality* proof — different fee tier,
different tick spacing, different protocol fee, priced by the same code with no changes, which is
what the equity-pool test asserts and all it asserts. What does not survive is any
suggestion that the equities category can be covered by *quoting* this venue. The advantage report's
third task stays on constructed pools until a second **liquid** pool is indexed, and it says so
rather than presenting a synthetic comparison as a real one. This was the stop condition written
down before the check was run: if no v3 pool has real liquidity, stop and report it rather than quote
a dead pool.

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
| "Hiring is 3–4 transactions" | **Close, and now exact.** With the provider passed at creation (so `setProvider` is not needed), the client's path to escrowed is **four transactions**: ERC-20 `approve` → `createJob(provider, evaluator, expiredAt, description, hook)` → `setBudget(jobId, amount)` → `fund(jobId)`. Settlement adds the provider's `submit(jobId, deliverable)` and the evaluator's `settle(jobId, evidence)` — on the EvaluatorRouter, not the kernel — so **seven transactions end to end**. See P-24; this paragraph said six and `complete()` until the sequence was checked against a deployment rather than read off the Draft EIP. `createJob` takes a **mandatory `evaluator`** which cannot be zero, and only that evaluator may `complete` or `reject`. ERC-2771 meta-transactions are an **optional extension, not core**, so nothing in the core interface batches these away. |
| "Who is the evaluator" is an open question | **Answered, two ways.** The EIP itself permits `evaluator = client` "when there is no third-party attester". BNB's SDK instead extends ERC-8183 with **UMA's Optimistic Oracle**: undisputed jobs settle fast, challenges escalate to UMA's Data Verification Mechanism. For Misquote the criterion should be **G-3's InRange% floor**, which §4.2 already requires to be binary and chain-checkable *without a counterfactual* — which is exactly the property an optimistic oracle needs to adjudicate a challenge cheaply. |
| "<~15 real agents → demote to registry view" | **Wrong by four orders of magnitude, and the real finding is better.** BNB Chain has **266,191** ERC-8004 agents, more than any chain by 4×. But only about **4% expose a working endpoint**, and after removing Sybil-flagged feedback **77.9% of rated BSC agents had no valid feedback left** — 29,444 reviews from **76 unique reviewers** (arXiv:2606.26028). **Invert the rule**: resolve each `agentURI`, rank by what responds, and decline to display on-chain reputation credulously — saying why, on the card. That is this product's thesis with independent evidence attached. Agent0 subgraphs already index ERC-8004 on BNB Chain, so discovery is a query. |
| `bnbagent==0.3.5` | **Stale.** Current is **0.4.2** under an explicit breaking-changes warning. Do not pin a June API for a September submission. |
| `studio.bnbchain.org/install` | **Dead — DNS does not resolve.** Two rival CLIs both called `bag`; the npm `@bnbagent/studio-cli` is current, the PyPI `bnbagent-studio` is stale. |
| Altana caps subset: allowlist, spend cap, expiry, Keystore, one-tx revoke | **Partly verified.** Budget, expiry, keystore issuance and explicit revoke are confirmed in the official CLI. **The allowlist and the "one-tx" characterisation are not** — the allowlist we were thinking of lives in `X402Signer`. Altana also cannot perform the generic ERC-8004 registration signature. Claim only what is demonstrated. |

---

## G — gaps in the frozen spec (values proposed and published)

The spec leaves these unspecified. Each proposed value is published in the assumption sheet and rendered
in the UI, so a reader can disagree with the number without having to reverse-engineer it.

| ID | Symbol | Where | Value | Rationale |
|---|---|---|---|---|
| **G-1** | `M` | §3.4, trailing swap count for the imbalance z-score | **50** | Long enough for a stable z-score on a busy pool, short enough to react within minutes. |
| **G-2** | `arb_cost_bps` | §3.4, toxicity threshold | **5 bps** | BSC gas plus a CEX taker fee, the round-trip cost an arbitrageur must clear. |
| **G-3** | `N` | §4.2, InRange% floor for the bonded instrument | **70%** | Binary and chain-checkable, per §4.2's requirement that the floor need no counterfactual. |
| **G-4** | `κ_default` | §5.2, referenced but never given a value | **3600.91 /log-price** (0.36007 /tick) | Fitted 17 Aug 2026 on the 30-day WBNB/USDT tape: 252,923 real swaps, coverage one unbroken run, **r² = 0.847 over 8,096 swaps**. The placeholder was 500 — **low by 7.2×**, and a low κ is a *wide* range, so every earlier quote was wider than this pool's own fill behaviour supports. **Read the r² with A8 open:** A8 records that this exponential form scores r² ≈ 0.84 on pure Brownian data, so 0.847 is indistinguishable from the null and is not evidence the form is right. Derived from the pool it is used on, which beats a round number, and still a weak parameter fitted with the wrong functional form. See V-2. |

---

## Readme §8 · D1 checklist

| Item | Status |
|---|---|
| Prize split verified in BNB Discord | **PARTLY RESOLVED.** Main track **$30,000 USDT**, TermiX partner track **$10,000 USDT**, Altana 50,000 XP, PancakeSwap 1,000 CAKE — all from BNB Chain's own announcement. The **$6K/$3K/$1K** placement split on the architecture board is still **unverified** and should not be repeated. |
| ERC-8004 registry population counted on BscScan (decision rule: <~15 real agents → demote third-party auto-cards to a plain "registry view") | **RESOLVED — 266,191 agents; rule inverted.** Answered in the E table above and left reading OPEN here for weeks, which is its own small lesson: a checklist kept in a second place goes stale in the second place. |
| ERC-8183 hire call invoked from an external script | **STILL OPEN, and narrowed.** The escrow is now verified on chain (the AACP reader, matrix E) and `JOB_ESCROW[56]` carries it with evidence. But nobody has read a job back out of it — `nextJobId()`, `jobCount()` and `jobs(uint256)` all revert — so this is a verified escrow, not a verified ERC-8183 escrow, and the item stays open until a job round-trips on a fork. |
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

1. **"With and without an agent" was computed and thrown away.** The policy's `passive_policy` and
   the replay driver's `passive_result` had existed since Step 7 and were used *only* by `tests/`.
   `Tearsheet` had no comparison field; the showcase emitter never ran the baseline. The answer to
   the judged question was a unit-test fixture. Now the advantage emitter and
   the advantage tearsheet, with a test that re-runs the engine and demands **exact** equality so
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

Source of truth is Mission Control's receipt log: **242 records, 75 `settled`,
167 `failed`**, spanning 2026-06-12 → 2026-06-27 across `/x402/v1/dex/search` (240) and
`/x402/v3/cryptocurrency/quotes/latest` (2). The 167 non-settled are paid-endpoint HTTP errors,
logged and never pruned.

Both numbers were correct when written — the discrepancy is a snapshot artifact, not a data error.
Settled count by cutoff: **42** through 06-20, **61** through 06-21, **75** through 06-22 (final).
That repo's that repo's README and its submission note say 49 because they were frozen at hackathon
submission time; its `pitch/` documents all say "75 settled (242 logged)" and are correct.

**Misquote uses 75 settled of 242 logged.** Per the README rule 6, no card renders this number until
it appears here, which it now does.
