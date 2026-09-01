# Misquote, for a judge with twenty minutes

**Every other marketplace misquotes you. This one shows its math — including the
parts that make it look worse.**

TermiX asks one question: *does hiring an agent on your marketplace beat doing
the job yourself, and can you prove it?* This document is the proof, and the
first thing it does is tell you what has **not** been proven.

---

## The thirty-second version

```bash
make setup                    # uv sync
make test                     # 2,276 tests, no network, ~35s
make showcase-demo            # replay the three LP agents, write their cards
make router-card              # and the fourth — Router reads a different tape
make web                      # http://localhost:3000
make go-no-go                 # the mainnet gate — it currently says NOT YET
```

`make go-no-go` is the one worth running first. It is a checklist that executes,
and it refuses to go green on anything nobody has checked.

**If you have twenty seconds rather than twenty minutes**, open
[`/demo`](https://misquote.vercel.app/demo) and take the guided run. It reaches a
P25–P75 range without a wallet, an API, or a funded anything — four steps, each a
real page carrying a simulation banner, ending on three mined chapel transactions
that are not simulated at all.

That page exists because the simulation layer behind it did not have one. It had
been complete, tested and deployed for weeks with nothing anywhere linking to it,
and the single fixture written for the flagship refusal **could not fire** —
`/quote` submitted below the scenario short-circuit, so a page displaying the word
*simulated* was talking to production. **P-31.**

Building it found something worse, and it is the reason the recording was insisted
on rather than assembled: **every quote the deployed site served was
`0.00% to 0.00%`.** A missing `capital_quote` became `0.0`, a division guard read
`if capital_quote > 0 else 0.0`, and every replay returned exactly zero — which the
engine published as a range and called sufficient. Found by running a real job on
the real tape and reading `distinct_returns: 1`. **P-32.**

---

## What is actually proven

Each of these is a test you can run, not a claim.

| Claim | How it is checked | Where |
|---|---|---|
| The tick math matches PancakeSwap's exactly | 19,546 answers recorded from the real Solidity at pinned commits, and replayed against ours on every commit — exact integer equality, no tolerance anywhere | `make vectors-verify`, published at `/vectors` |
| …and still matches freshly deployed Solidity | The same comparison, regenerated against a contract deployed to a local chain rather than read from disk | `make vectors-check` (needs foundry + anvil) |
| The replay cannot see the future | **T1**, bitwise: run twice, second run replaces every event after a cut with seeded noise, decision sequences compared with every float packed to its exact bits — plus a negative control proving tampering *does* change later decisions | `tests/replay/test_engine.py` |
| The live agent and the replay are the same policy | **L1**: the live driver, its own file and own loop, runs over a tape-backed chain source; decisions compared byte for byte | `tests/replay/test_l1_equivalence.py` |
| Our position math matches the real contracts | Mint through the real NonfungiblePositionManager on a BSC fork, compare amounts and principal to **one wei** | `make fork-diff` |
| Fees cannot exceed what the pool paid out | **T2**, with the protocol's 34% cut inside the bound | `tests/replay/test_engine.py` |
| A passive position agrees with direct computation | **T4**, to 1e-12 | same |
| Estimators physically refuse future data | **T3**, unconditional runtime guard in both drivers, no flag to disable | `tests/estimators/` |
| The kill switch stops a real mint | Against a live signer on a fork, not a stub | `tests/chain/test_position_lifecycle.py` |
| The engine runs agents it was not written for | Three policies — A-S market making, a fixed ladder, threshold de-risk — through one engine, one tape, one cost model, one accountant | `tests/agents/` |
| No gate is wired to nothing | Every toxicity arm is asserted to reach a non-zero value in a real run, and a threshold above its own ceiling refuses to construct | `tests/agents/test_sentinel.py` |
| The advantage report contains no typed-in numbers | The engine is re-run independently and **exact** equality demanded — not approximate | `tests/tearsheet/test_advantage.py` |
| The DIY baseline is not a different program | Both columns are one `ReplayDriver` with `policy=` swapped; same tape, same costs, same accountant | same |
| The sponsor's escrow is not ERC-8183 | Three EIP accessors revert on the live contract; `orders(bytes32)` answers, and its budget word matches TermiX's own published figure on 20 of 20 live orders | `tests/registry/test_termix_escrow_fork.py` |
| Every pool we quote was read, not assumed | All four recorded pools re-checked against chain — tokens, fee tier, spacing, factory, and `feeProtocol`, the field that decides what a fee is worth | `tests/chain/test_addresses.py` (chainfork) |
| We price a tokenized equity with no code changes | TSLAx/USDT — different fee tier, different spacing, different protocol fee | `tests/chain/test_equity_pool.py` |
| The agent can actually mint, recentre and withdraw | Real transactions on a forked BSC, including that a half-failed recentre leaves the wallet flat rather than stranded | `tests/chain/test_executor.py` |

**2324 tests: 2276 offline, 48 against a live chain or a fork.**

---

## What is assumed, and where it hurts

Every one of these is in [`ASSUMPTIONS.md`](ASSUMPTIONS.md), and every one makes
the headline number *worse* than it could have been.

- **Liquidity providers keep 66% of every fee.** PancakeSwap's protocol fee is on
  by default at 34% on this pool; Uniswap's is off. Reconstructing fees from swap
  volume — the natural way to write a replay engine — overstates LP earnings by
  **1.52×**, and that error lands directly on the headline APR. Read from
  `slot0.feeProtocol` and cross-checked per swap against the `Swap` event, which
  on Pancake reports the protocol's cut directly.
- **What we call adverse selection is an upper bound on it** (A10). Equation (3)
  is non-negative for every swap regardless of who traded, which is the tell that
  it is not really measuring adverse selection — on a round trip the position
  ends flat having collected two fees, and it still books a loss. Labelled
  *realized convexity cost (upper bound on LVR)*, never simply "LVR".
- **The fill-decay parameter fits the wrong functional form** (A8). Excursion
  frequency for a random walk decays as a power law; the spec fits an
  exponential, which scores r² ≈ 0.84 on pure Brownian data and so clears the
  spec's own r² ≥ 0.5 gate while being the wrong shape. Treated as a labelled
  weak parameter, with its r² on every card.
- **The optimal-spread equation prices no adverse selection at all** (A9). On a
  venue where the dominant flow is arbitrage, its widths are systematically too
  narrow. That is a gap in the model as applied, not a transcription error.
- **The A-S ↔ v3 mapping is a design heuristic, not an isomorphism.** Uniswap's
  own docs say range orders *approximate* limit orders; the literature
  characterises AMMs as market makers that do not update quotes. The earlier
  wording claimed more than that and was corrected.
- **The toxicity rule withdraws about once every four hours on pure noise, and
  every one of those is a false alarm** (P-7). On a driftless random walk there
  are no arbitrageurs by construction, yet §3.4's imbalance arm fired **16 times
  in 62 hours** — `|z| > 2.5` on **1.34%** of 44,802 samples, against **≈1.24%**
  predicted by the null. The estimator is behaving exactly as specified; whether
  `z_pull = 2.5` is the right threshold depends on how much genuine toxic flow
  the real tape carries, which synthetic data cannot answer. It is spec §8's own
  published value and we did **not** retune it to look better.

---

## The TermiX track, and the criterion we had recorded wrongly

TermiX asks for an **"Agent Advantage Report comparing at least three real tasks
run with and without an agent"**, weighting *trading, equities and security*
highest. The only note on that criterion anywhere in this repo said
*"80% = quality + proof → tearsheet"* — and it lived inside a drawing file, where
nothing ever checked it.

Finding the real one exposed something worse. **The "without an agent" baseline
had existed since Step 7 and was used only by tests.** `passive_policy` and
`passive_result` were both built, both correct, both invisible: `Tearsheet` had no
comparison field and the showcase never ran them. We computed the answer to the
judged question in a unit test and threw it away.

```bash
make advantage-demo      # every task, both ways, on a labelled synthetic tape
make go-no-go            # now gates on the report too, and says amber until it is real
```

**The baseline is not a different program.** Both columns are the same
`ReplayDriver` with `policy=` swapped — same tape, same cost model, same LVR
accountant, same quote machinery. The usual way to flatter an agent is to
implement its baseline separately and charge it differently; that is structurally
unavailable here, and a test asserts the consequence.

| Task | Without an agent | With an agent |
|---|---|---|
| **Earn** — fees on a position | mint once at the same width, never touch it | Warden |
| **Protect** — don't get picked off | *the same agent with its withdrawal ablated* | Sentinel |
| **Choose** — which pool to enter | pick the deepest pool | the §3.4 flow screen |

Three tasks sharing one baseline would be one task relabelled, so a test asserts
they are distinct — and task 2's baseline is an ablation rather than a
different strategy, so the comparison isolates the withdrawal decision and
nothing else.

**All three go against the agent**, and the table is generated from
`advantage.json` rather than typed, so it cannot drift from the artifact it
describes:

<!-- derived:advantage — regenerated by `make judges`; do not hand-edit -->
| Task | Tape | Capital | DIY | Agent | Δ median |
|---|---|---|---|---|---|
| Earn | `chain` | 1 | 4.78 – 27.21% | -52.10 – -49.97% | **-64.29pp** |
| Protect | `chain` | 1 | 9.38 – 14.94% | -24.16 – -23.85% | **-38.17pp** |
| Choose | `chain` | 0.03181 | -620.55 – -617.83% | -620.55 – -617.83% | **+0.00pp** |
| Route | `chain` | 1e+04 | 1.90 – 1.92% | 1.71 – 1.92% | **-0.01pp** |
<!-- /derived:advantage -->

Task 3 runs at a smaller position than the other two, and the table says so:
assumption A1 caps a position at 1% of pool liquidity, that ceiling belongs to
the *pool*, and the shallower of task 3's two venues binds it. Both of its
columns share the figure, so the delta is sound; the percentages are large
because the denominator is small.

**The reason the LP tasks lose is one mechanism, and it is not the strategies.**
Each task's own section derives it from that task's columns, and **P-20** has the
measurement: the agent never recentres — not once in seven days of instrumented
replay — and spends its entire daily budget on pulling out and re-entering, at
exactly `max_rebalances_per_day`. Once the budget is gone it cannot afford to
return, so it sits flat for the rest of the day. Gas, not strategy.

That is **P-7 with a price tag, confirmed on real flow by P-19**: §3.4's
imbalance rule fires often enough to consume the budget, and P-7 had already
measured it firing on a driftless random walk where every one of those
withdrawals is a false alarm by construction. We did not retune `z_pull`, and we
did not raise the rebalance budget. Both are spec §8's published values, and
moving a parameter because it produced an unflattering number is the fitting
this project exists to refuse.

Across every task the report **refuses to call a winner** — a handful of tasks are
three observations and `verdict()` will not call a rate on fewer than thirty.
That refusal is the honest headline; what carries the argument is each task's own
quote, where the sample is 20 sub-windows × 3 parameter perturbations.

**Equities: TSLAx/USDT.** Backed's xStocks trade on PancakeSwap, so a tokenized
equity is the same v3 pool the engine already prices — a fourth generality proof
after Grid and Sentinel, costing one address. Resolving it produced **P-8** — and then
P-8 turned out to be wrong, in a way worth reading. We published that the equity
pool reports `feeProtocol = 0`, LPs keeping the whole fee. It reports **3200**
against the flagship's **3400**: the reader took `slot0[2]`, `observationIndex`,
instead of `slot0[5]`. Index 2 held `0` on one pool and `101` on the other —
small plausible integers that neither reverted nor looked absurd, and `0` was
exactly the value that made the better story. The finding survives in kind (two
pools, one DEX, no constant right for both, so `fee_protocol` still has no
default) and not in degree. What caught it was two numbers in this repo
disagreeing on screen, so the badge now makes that comparison itself.

It is thin, and measuring it properly made "thin" look generous. Liquidity is a
stock; a replay needs flow. Three 5,000-block windows spread across thirty days
returned **0, 0 and 1 swaps** against the flagship's **473, 325 and 171** — three
orders of magnitude apart, and the equity figure rests on one trade. The tape
table above carries what each pool actually holds; the extrapolation that used to
sit here quoted a flagship figure that has since moved, which is the whole reason
these numbers are now generated rather than typed. So **there is no equity tape
and there will not be one**: `verdict(min_n=30)` would refuse it, and a month of
that pool cut into twenty sub-windows leaves single figures in each. The pool stays a *generality* proof — same code, different fee tier,
spacing and protocol fee — which is exactly what `test_equity_pool.py` asserts
and the whole of what it asserts. It is not a venue we can quote. It is also the
*only* xStocks v3 pool on BSC with real liquidity at all; NVDAx and AAPLx have no
pool at any tier, and the 1.00% TSLAx pool exists with zero liquidity and was
refused rather than quoted.

**A second real venue, because task 3 needed one.** "Which pool would you choose?"
used to be answered on two tapes from `synthetic_events()` — one deep and toxic
*by construction*, one shallow and balanced *by construction*. A task whose answer
is written into its own setup is not evidence, however carefully the rest of the
report is built. The second venue is now **WBNB/USDT at the 0.25% tier**,
`0x1401ff94…`, resolved through `factory.getPool` and read back: same pair, real
flow, **191× shallower** by median liquidity, and `feeProtocol = 3200` against the
flagship's 3400. Which of the two is the "deepest" is now measured from the tapes
rather than asserted by a label, and both tapes are clipped to the block range they
share so the comparison is about two pools and not about two months.

That protocol fee is **P-8 a third time**: three fee tiers of one pair on one DEX,
three different protocol cuts — 3300 at 0.01%, 3400 at 0.05%, 3200 at 0.25%. Any
constant is wrong for two of them, and the error lands on NetFeeAPR.

Provenance is now recorded **per task** rather than per report. The gate used to
read one top-level `source`, which a report with two real tasks and one constructed
one would pass while its header said `chain`. It names the task that is not real.

**Security: the sponsor's own escrow, verified — and then un-verified.** TermiX's
AACP builds on ERC-8004 and ERC-8183, and their `IdentityRegistry` is
`0x8004A169…a432`, **byte-identical to the contract this codebase already read**.
On that strength their `TermixEscrow` went into `JOB_ESCROW[56]`, with
`JOB_ESCROW_EVIDENCE` recording what was checked *and what was not* — an EIP-1967
proxy over 17,941 bytes, `settlementToken()` returning our own USDT, and the
caveat that **nobody had read an ERC-8183 job back out of it**.

Somebody has now, and **it is not an ERC-8183 escrow.** Its implementation's
dispatch table, recovered from the deployed bytecode, contains none of the seven
calls our hire flow models — not `createJob`, `setProvider`, `setBudget`, `fund`,
`submit`, `complete` or `reject` — across **5,894 candidate signatures**. It is
order-keyed: `orders(bytes32)`, `acceptOrder(bytes32)`. That is why
`jobs(uint256)` reverted; the interface differs, the call was never misspelled.

A job *was* read back, through the accessor that exists: `orders(bytes32)`
returns a 13-word struct whose budget word matches the figure TermiX's own public
explorer publishes for the same order on **20 of 20 live orders**, exactly. The
order's state is deliberately **not** decoded — no word separates their `SETTLED`
orders from their `PENDING_ACCEPT` ones — and 44 of 65 selectors are recorded as
unresolved rather than guessed.

`JOB_ESCROW` was empty for a while and `escrow_address(56)` raised. It is not empty now — a **different** contract, Altana's AgenticCommerce kernel, passed the same three-way check on both BSC networks with 56,632 jobs on it (P-24). The rule
that mapping states is *no entry without evidence*, and it is now applied to
itself: a real, fully-verified, well-behaved escrow that implements a different
interface is not an ERC-8183 escrow. The readings survive under
`FORMER_CANDIDATE_EVIDENCE`, because a rejected candidate is a result. The whole
finding is **P-18** in the requirements matrix, and it is asserted against the
live contract by `tests/registry/test_termix_escrow_fork.py` rather than by this
paragraph.

The escrow is also **upgradeable by its owner** — escrowed funds sit behind code
that can be replaced — which remains a property of the venue a marketplace
routing user money through it should disclose rather than discover.

**And the report is real now.** Both venues are indexed from chain over the same
the same blocks, and `make go-no-go` checks *coverage* rather than span, so an
interrupted backfill cannot pass it. The gate that blocked this track's core
requirement is green.

<!-- derived:tape — regenerated by `make judges`; do not hand-edit -->
| Pool | Swaps | Unbroken blocks read |
|---|---|---|
| PancakeSwap v3 WBNB/USDT 0.05% | 252,923 | 5,802,928 |
| PancakeSwap v3 WBNB/USDT 0.25% | 14,016 | 5,802,928 |
| PancakeSwap v3 TSLAx/USDT 0.25% | 85 | 814,193 |
<!-- /derived:tape -->

**What it says is that hiring the agent loses** on the liquidity tasks, against
positions minted once and never touched. Those numbers are in the table above,
and so is the reason — the report derives it from its own columns rather than
asserting it, and the worst task's figures are reproduced here:

<!-- derived:mechanism — regenerated by `make judges`; do not hand-edit -->
```
    MINT 249 · PULL 249 · RECENTRE 0
    8.0 pull-and-re-mint cycles per calendar day, against max_rebalances_per_day
    in range 6.1% of the window; gas alone 55% of capital annualised
```

<!-- /derived:mechanism -->

**It never recentres.** §3.4's imbalance arm fires on a large fraction of real
samples — **P-19** measures it — so the agent pulls; `decide()` gates re-entry
and never exit, on purpose;
P-12 made the daily budget correctly persist across a pull. Compose the three and
the whole budget goes on *coming back*, after which the agent cannot afford to
and sits flat. None of the three is a bug. The composition is, and it is **P-20**.

Nothing was retuned to improve the number. `z_pull` and `max_rebalances_per_day`
are the frozen spec's published values, and moving a parameter because it
produced an unflattering result is the fitting this project exists to refuse.

---

## The PancakeSwap track: what an LP actually gets from this

The criterion is "a real benefit to PancakeSwap traders or liquidity providers".
The benefit here is not the agents — it is the integration surface underneath
them, published at [`/venue`](../apps/web/src/app/venue/view.tsx) and generated
from `scripts/venue_report.py`.

PancakeSwap v3 is a Uniswap v3 fork, and *"it's a fork"* is where LP accounting
goes wrong. Every divergence below was found by a test that failed, and each one
is stated with the consequence for someone providing liquidity:

| divergence | what it costs an LP who misses it |
|---|---|
| The protocol takes **34%** of every fee by default (`slot0.feeProtocol` reads 3400 on our pool, 3200 on another) | Reconstructing fees from swap volume — the natural way to write a replay engine — **overstates LP earnings by 1.515×**, and the error lands squarely on the headline APR |
| Pools are deployed by a separate `PancakeV3PoolDeployer`, with a different init-code hash | Uniswap's `computeAddress` constants yield a **plausible address that is not the pool**. Resolve through `factory.getPool()`, always |
| The mint callback is `pancakeV3MintCallback`, not `uniswapV3MintCallback` | A direct pool call built against the Uniswap ABI **reverts** |
| BSC's USDT and USDC are **18 decimals**, not Ethereum's 6 | Every amount off by 10¹² |
| `MIN_TICK % 10 == 2`, so clamping to the tick grid yields ticks the pool rejects | A range that cannot be minted, discovered at transaction time |

Two of those are the reason this project's own numbers moved: **P-1** (the 34%
cut) and **P-6** (the deployer). Neither was in any documentation we could find;
both came out of a differential test against the real Solidity.

On top of that, every pool a listed agent touches carries a due-diligence badge
of **nine on-chain checks** with provenance ids — factory resolution, tick
spacing against the tier, protocol fee, decimals, initialisation, a mintable
range, liquidity depth, both tokens being contracts, and recorded values still
agreeing with chain. `make vet` refuses to clear what it cannot read.

## What is NOT done

Stated plainly, because a submission that hides its gaps is doing the thing this
project exists to argue against.

- **The 30-day tape exists, and the survey that said it could not is the reason
  it does.** This entry used to read *"No 30-day tape"*. It is now 252,923 swaps
  across 30.2 unbroken days, read from chain, with every block in the range
  recorded as fetched — `make status` reports it PASS.

  Getting it needed the endpoint survey that this section originally used to
  explain why the tape was unobtainable. Measured 16 Aug 2026, one request at a
  time:

  | Of 22 public BSC endpoints | `eth_getLogs` |
  |---|---|
  | 8 (every bnbchain dataseed, both defibit, ninicoin) | **refused at any width**, including one block |
  | 3 (`blxrbdn`, `48.club`, `publicnode`) | served, capped at **5,000 blocks** |
  | 2 (`1rpc`, `blockrazor`) | served, capped at 50 and 25 blocks |
  | the rest | unreachable, wrong chain, or `eth_getLogs is not supported` |

  Two of our own three configured endpoints were in the first row, and the
  health check selected on `eth_chainId` — which all of them pass. So the
  indexer held a list of endpoints that could never serve it, and a tail refused
  on every request looked exactly like a tail working on a pool nobody trades.
  Written up as requirements-matrix **P-11**; the original measurement is still
  in the document with its error marked, because deleting it would hide the more
  useful finding — *an instrument that cannot attribute its own result will be
  over-read.*

  Once the three endpoints that do serve logs were the ones being asked, a
  30-day backfill was 1,152 requests at 5,000 blocks each: measured at 1,151
  chunks, zero refused, 62 minutes, **no key**. The same read built the Venus
  rate tape — 159,956 accruals over seven days, 269 chunks, 29.6 minutes.

- **κ has been fitted.** This bullet said "still a provisional default" for a
  round after it stopped being true. It was fitted on the 30-day tape on 17 Aug
  2026 — **3,600.91 per log-price, r² = 0.847 over 8,096 swaps** — and the
  go/no-go's `no provisional constants` gate now compares that constant against
  the κ the card independently fitted and fails if they disagree by more than
  10%. See A8 and matrix G-4. A8 is unchanged on the part that matters: the
  exponential is still the wrong functional form, and an r² of 0.85 is what pure
  Brownian noise produces, so the fit is a measurement rather than a
  vindication.
- **Warden can broadcast on chapel now, and mainnet is refused in code.** This
  bullet said `make warden` "is still wired to the recording executor", and the
  ledger's evidence was that `__main__.py` does not import `ChainExecutor`. Both
  true; the reason underneath was narrower than either. `main` had **no `Web3` in
  scope at all** — `build_source` returns a `BscReader` built from a list of
  endpoints and never exposed one — so this was a plumbing gap wearing a
  capability's clothes, the same shape as the hire flow's "nothing here can
  sign" (P-28).

  `build_executor` now constructs the signer, the position manager and the
  executor behind **three gates whose default is refuse**: `--broadcast` must be
  passed, the chain must be chapel (mainnet raises, it is not a flag), and
  `MISQUOTE_DRY_RUN` must be `0`, which also triggers
  `assert_signs_for_operator`. Everything downstream was already wired —
  `reconcile()` adopts the real position the moment it is handed an executor with
  `observe()`.

- **No 24-hour burn-in — but the loop has run, and the executor is proven.**
  `make warden` runs the real policy against real BSC state and writes a real
  journal; verified at 139 decisions over fifteen minutes, 0 polls refused.
  `chain/executor.py` mints, recentres and withdraws through the verified
  NonfungiblePositionManager, and **nine tests exercise it against a forked BSC
  with real transactions** — including that a recentre which cannot open leaves
  the wallet flat rather than stranded, and that a withdrawal reaches the wallet
  rather than stopping at `tokensOwed`. What is missing is a funded wallet and
  the decision to use it: `make warden` is still wired to the recording
  executor, and the go/no-go is the gate for changing that.
- **The agent loses to the passive baseline, and we now know why.**
  `docs/AGENT_ADVANTAGE.md` reports −64.29pp on Earn and −38.17pp on Protect.
  That is the honest headline and it is not being softened here.

  The cause is a calibration mismatch, measured this round on the 30-day tape.
  Spec §3.4 pulls the quote when `|z| > 2.5` over a 50-swap window, and that
  threshold is sensible **under the statistic's own null** — each swap's
  direction an independent fair coin. Real BSC flow is not that. Over 252,874
  samples the **median `|z|` is 2.179**, and the spec's threshold fires on
  **41.94%** of them. A rule meant for exceptional adverse selection is
  triggered by ordinary conditions, the position is withdrawn 94% of the time,
  and the re-entry cost is charged on every one of 249 round trips. That is the
  loss.

  **We are not moving the parameter.** The spec is frozen, and moving a number
  because it produced an unflattering result is the fitting this project exists
  to refuse. The threshold stays at 2.5, the report keeps saying the agent
  loses, and the measured distribution is published as **P-23** so the next
  person can decide the spec question with data instead of a null. What a
  calibrated threshold would be is recorded there and deliberately not
  implemented.

- **The gate did not run the linter or the component suite, and now does.**
  `make go-no-go` had fifteen checks, three shelling out to pytest and one to a
  browser build — and it ran neither `ruff` nor the 405 vitest tests that hold
  the artifact field contract, the prose rendering and the dead-export scan.
  There is no CI file in this repository either, so both ran only when somebody
  remembered. They are gates now (`lint`, `web component suite`), skipped by
  `--fast` for the same reason the browser pass is: `make status` writes
  `/status` from the fast pass and should not shell out to node.

- **All four agents can now be run as processes, not just replayed.** `Readme.md`
  §1 commits to four agents at equal depth and the replay engine has put three
  policies through one engine since Step 7 — but the *live* driver hardcoded
  Warden's policy, so `make grid` and `make sentinel` did not exist. `Engine`
  already exposed a `policy=` seam; `WardenLive` simply never passed it through.
  One line, and the claim is now true of the process list as well as the replay.
  The journal is per-agent for the same reason — it was `warden.jsonl` for
  everybody, which would have merged three agents' decisions into one file the
  tearsheet reads as one agent's record.

- **Metrics, a heartbeat and alerting exist.** `prometheus-client` and
  `python-telegram-bot` had been declared in an `ops` extra since the project
  started, installed, and imported nowhere — with `tests/test_layering.py`
  guarding pure layers against code that was never written. `/metrics` serves an
  exposition or a **501 naming the missing extra**, never an empty body: a
  scraper cannot tell an uninstalled client from an idle agent. The heartbeat is
  a **timestamp rather than a boolean**, because a hung process stops updating
  either one and only the clock says how long ago. Telegram returns `False`
  silently when unconfigured, because a notifier that raises takes the agent down
  to announce that the agent is up.

  **No PnL, fee APR or position value is exported**, and that is the deliberate
  part. Those are computed once by the replay accountant with their assumptions
  attached; a second derivation reachable by a different path is how two numbers
  in one system come to disagree, which is P-8's shape and has already happened
  here twice.

- **Nothing has traded with real money**, and the go/no-go will not let it until
  the above are green.
- **Why TermiX's dashboard reads zero, which is the answer to the obvious
  question.** Four agents are registered and owned, and their platform shows
  *0 agents, 0 requests, 0 orders*. Three separate reasons, only one of which is
  fixable by registering harder:

  1. **TermiX has no testnet.** Their production config, read live at
     `platform-backend.prod.termix.live/api/v1/config/contracts`, returns
     `chainId: 56`. Our four sit in `0x8004A818…BD9e` on chapel — a different
     contract on a chain their backend has no base URL for. This repository
     *already knew*: `registry/aacp.py` carries the comment "there is no chain
     97 entry because there is no testnet deployment", and
     `tests/registry/test_aacp.py` enumerates 97 by name as a chain that raises.
     Chapel was chosen anyway. Recorded here rather than quietly corrected.
  2. **Their explorer would have found us on mainnet, with no platform flow at
     all.** It indexes the registry, not their own sign-up funnel — the gap
     between the two counts below is indexing lag. So mainnet registration is
     sufficient to appear there, and it is deferred rather than blocked.

     **That was an inference, and it has since been run.** Four
     `register(string)` calls on chain 56 moved the authenticated read from
     `0 items` to `3 items`, and the answer came back *narrower* than the claim
     above: sufficient for an identity minted to the wallet that authenticates,
     and not for one transferred to it. The second table below is that result,
     both halves of it.

     These two numbers were **typed** here, as 304,790 against 304,927. The
     endpoint had no constant and no function anywhere in this repository, so
     nobody — us included — could re-derive them, and by the time anyone looked
     again the first had moved by more than fifteen thousand. That is the defect
     this project is named after, in the document that exists to disclose it.
     Generated now, from `aacp.fetch_explorer_agents`:

<!-- derived:explorer — regenerated by `make judges`; do not hand-edit -->
| | |
|---|---|
| agents TermiX's explorer indexes | **325,200** |
| endpoint | `/api/v1/explorer/agents`, public, no credentials |
| the registry's own high-water id, read in the same build | 325,338 (+138) |
| what the gap is | their indexing lag behind the registry, not a sign-up funnel |
| fields returned and deliberately not published | onTimeRate, passRate, reputationScore |
<!-- /derived:explorer -->

     Registering four agents on that same registry, and asking the same
     authenticated endpoint before and after:

<!-- derived:termix_listing — regenerated by `make judges`; do not hand-edit -->
| | |
|---|---|
| the question | Is registering on ERC-8004 mainnet sufficient to appear on TermiX? |
| before | `/api/v1/agents` answered: 0 item(s) — four identities on chapel (97); none on mainnet |
| after | `/api/v1/agents` answered: 3 item(s) — four identities on mainnet (56), all owned by the operator |
| asked as | `0x0c501EE1924bfb91a028DB4BcD68f4861B0Ff6eE`, authenticated over SIWE |
| what it cost | 0.000147926 BNB of gas, no protocol fee |
| listed | grid `323332`, router `323334`, sentinel `323333` |
| not listed | warden `323262` — minted by a delegate, then transferred |
| indexing lag ruled out | their index reached 323,517, past our highest id 323,334, and the absence survived |
| what it means | sufficient for an identity **minted** to the wallet that authenticates; not for one transferred to it |
<!-- /derived:termix_listing -->
  3. **"Orders" is not downstream of registration at all.** TermiX's orders are
     keyed by `chainOrderId`, a bytes32 minted by their own platform, held in a
     separate escrow per settlement currency. There is no path from an ERC-8004
     identity to an order id. That counter moves when somebody hires an agent
     through the ERC-8183 flow, which needs five signed client transactions and
     real USDC and is on the not-built ledger.

  **Their authenticated API is built, and it confirms the point rather than
  fixing it.** This said the listing side was "blocked on a wallet-signed nonce
  exchanged for a session JWT" — three claims, all false, and written up as
  **P-29**. The nonce exchange is SIWE and its endpoints were never private: their
  API answers `401` for *every* unmatched path under `/api/v1/`, so a GET probe
  cannot tell protected from nonexistent, and every look that used one concluded
  the surface was closed. A POST distinguishes them, because the public endpoints
  validate their fields first.

  `make termix-login` now completes the exchange as the operator and reads the
  half that needs a token. It answers **`0 items`** — asked as ourselves, with a
  credential, from the endpoint their own dashboard reads. The three reasons above
  are unchanged; what has changed is that the first of them is now a reading
  rather than an inference. The token is never written to disk, and a test asserts
  the evidence file holds no token, no refresh token, no signature and no nonce.

- **The four agents are registered on ERC-8004, and the wallet that owns them is
  declared.** `Readme.md` has said all four "register ERC-8004 identities" since
  before any of them existed. Until this pass the registry package could only
  read: `IDENTITY_ABI` was four `view` functions and no registration call
  existed anywhere in `packages/`. The marketplace that surveyed four hundred
  agents in that registry, counted how few resolve, and published the interval
  had never appeared in it — which made the survey a thing done *to* other
  people.

  It is now four rows on chapel, owned by
  [`0x0c501EE1924bfb91a028DB4BcD68f4861B0Ff6eE`](https://testnet.bscscan.com/address/0x0c501EE1924bfb91a028DB4BcD68f4861B0Ff6eE),
  and `/registry` carries the first transaction links this site has ever
  published. Everything here before them was a *reading* of chain state, which
  has to be trusted to have been taken honestly; a transaction hash is a
  third-party-hosted record of an action, checkable without this page's
  cooperation.

  **Two transactions per agent, and the shape is the point.** The wallet holding
  a key on the build machine is a burn-in wallet, not the address this project
  publishes as its own. So each agent is registered by the signer and handed
  over with `safeTransferFrom`. The alternative was putting the submission key
  on a laptop that runs `make`; this way the mint and the handover are
  separately visible, so "that address owns these agents" needs nothing from us.

  **The cards carry what a listing actually reads.** They were registered and
  handed over before anyone had looked at what an indexer renders, so the first
  version had no `image` (a blank avatar beside every agent that has one) and no
  `registrations` back-reference (a card that, found on its own, could be about
  anybody). `setAgentURI` is owner-only, so correcting them after the handover
  needed the operator's key — the exact cost of completing a card *after*
  transferring it rather than before. Four more transactions; the ordering for
  anything future is register → setAgentURI → transfer.

  **The cards are held to our own bar.** `erc8004.assess()` is what decides
  whether a *stranger's* listing counts as substantive on `/registry`, and
  `scripts/register_identity.py --verify-only` re-reads our four from chain and
  runs the same function over them — not a copy of its rules, which would drift.
  A registration of ours that fails our own test is recorded as a FAIL. The
  cards are `data:` URIs, so they resolve by construction rather than for as
  long as this project pays for a domain.

  **What this is not.** Chapel, not mainnet — though the registry proxy on both
  chains forwards to the *same* implementation address
  (`erc8004.IDENTITY_IMPLEMENTATION`, read from the EIP-1967 slot on each), so
  what passed here is not a different contract from the one on 56. And a row in
  a registry proves nothing on its own: agent 1000's tokenURI is the literal
  string `user-8abd198e`. That is exactly why `assess()` exists, and why being
  registered is reported beside what the card actually contains rather than
  instead of it.

  `tests/registry/test_cards.py`, `tests/registry/test_identity.py`,
  `make go-no-go` (the `agent identities` gate).

- **The signer gate stopped ending on a manual step.** It read "a key is set;
  verify by hand that it is not a main wallet" — a checklist whose last
  instruction is a human, in front of the only code that can spend anything.
  `MISQUOTE_OPERATOR_ADDRESS` now declares who the project is and
  `MISQUOTE_SIGNER_ADDRESS` declares which wallet holds the key, and
  `check_signer_configured` compares the key against the declaration instead of
  asking.

  It reports **amber**, and that is the honest colour rather than an unfinished
  setup: the burn-in wallet signed, the operator did not, and a delegate
  spending is a weaker claim than the operator spending. A key matching *neither*
  declaration is still a hard refusal — `chain/signer.py` will not construct
  once `MISQUOTE_DRY_RUN=0`. The escape hatch is a second declaration, never an
  absent one.

- **Session keys are half built, and the half that closed was closed by
  looking.** This said they were not built at all, because "no Altana session-key
  module has been verified on either network". That was a statement about our own
  `vetting/addresses/` directory — `@altananetwork/sdk@0.8.0` publishes
  `keyStore` and `keyStoreController` for both BSC networks, in the same package,
  at the same version, that `JOB_ESCROW` was verified from. Nobody here had
  opened the file next to the one we had already read.

  **That is P-24 happening again, one module over**, and it is written up as
  **P-27**. The lesson had been recorded as a fact about ERC-8183 rather than as
  a habit about search, so it did not generalise.

  `make session-keys-verify` ran the same three-way check on both chains and
  every check passed; `make session-keys` then granted a key on chapel, read it
  back live, revoked it, and read it back dead. Three mined transactions,
  `isValidKey` true then false, in `vetting/identity/session-keys-97.json` and on
  `/activate`. Everything else on this site is a *reading* of chain state, which
  has to be trusted to have been taken honestly; this is the second thing here
  that is a transaction hash instead.

  Running it corrected four things no amount of reading the SDK would have: there
  is no ERC-20 `approve` in the flow, `registerKey` reverts on a fresh wallet
  (`KeyStore: account not bootstrapped`), the root key that fixes that **must not
  expire**, and the grant and revoke live on two different contracts.

  **What is not built is the caps, and that is the more interesting half.** The
  keystore enforces the expiry and revocation. The allowlist and the spend cap
  belong to a `validator` module, and every grant on this deployment — ours and
  other people's, read off chain — carries `validator = 0x0` and empty metadata.
  So two of the four caps are enforced and two are enforced by nothing.
  `VALIDATOR_MODULE` is empty for exactly the reason `SESSION_KEY_MODULE` used to
  be, `SessionKeyWriter.grant` refuses to send a capped-looking grant without an
  explicit `allow_unenforced_caps=True`, and there is still no Hire button. A
  page offering four caps over a key the chain bounds by one would be this
  project's own name, on the page about bounded authority.

- **The ERC-8183 hire flow** is not built. **Router now is** —
  the fourth category, and with it all four the main track asks for at equal
  depth.

  Router is worth a sentence about *why* it was cut and what building it cost,
  because the ledger entry naming it said the reason plainly: it was the only
  one of the four that needed a second venue model. That venue model is
  `chain/venus.py` — two Venus dollar markets, each verified three ways — and
  `estimators/apr.py`, which does not read a rate at all. It differences the
  `borrowIndex` accumulator, because Venus's own `supplyRatePerBlock()` needs a
  blocks-per-year constant that **is not readable from chain** and whose
  plausible values span **6.67×** (**P-22**, **A12**).

  What Router then found is the honest kind of answer, and it took two goes to
  get there. It **supplies, and then mostly declines to churn** — the figures
  below are read from its card rather than retyped, because every one of them
  has been wrong in a document at least once:

<!-- derived:router — regenerated by `make judges`; do not hand-edit -->
| | |
|---|---|
| Tape | 250h across 2 Venus markets and 2 PancakeSwap v3 ranges |
| Net return on supplied capital | **0.03% – 0.03%** (over 125h, not annualised) |
| Best realized rate seen | 2.98% |
| Round-trip hurdle | 1.06% |
| Largest gap between venues | 1.07% |
| Moves | 1 enter · 1 switch · 0 exit |
| Held the better-paying venue | 68% of samples |
| Earned / cost | 6.15 against 1.0304 |
| Commitment before entry repays a round trip | 2.5 days |
| vs parking in the best venue | indistinguishable: -0.00pp is below the 0.1pp materiality floor |
| At a size the ranges can take | **0.11% – 0.55%** on 1,705, 250 of 251 samples inside a PancakeSwap range |
<!-- /derived:router -->

  The first version of this card said Router **never supplied**, and gave a
  16-day break-even as the reason. That was wrong, and wrong in the way this
  project is named after: the hurdle was built from a gas figure forty times
  BSC's real cost and a swap fee copied from a WBNB/USDT pool rather than read
  from the USDT/USDC pool a stablecoin router actually uses. Both are readings
  now — the fee from the verified 0.01% pool, the gas from `eth_gasPrice`, and
  BNB priced from the tape this project already indexes. The agent had been
  priced out of its own market by a constant. See **P-25** and **A14**.

  Grid and Sentinel still exist mainly to prove the engine is not a Warden
  harness with delusions of generality — and Sentinel earned its place by
  finding a rule that had never once fired (below). Router extends that argument
  further than either: it is a different *venue*, not a different policy.

- **The ERC-8183 blocker moved, and it is worth recording which way.** This
  repository's `registry/erc8183.py` says the EIP "lists no reference deployment
  addresses at all". That is still true of the EIP — but Altana's SDK ships
  `ERC8183_ADDRESSES` with deployed addresses for BSC mainnet **and** testnet,
  and the `registry` entry in that table is byte-identical to this repository's
  own `IDENTITY_REGISTRY` on **both** chains. The real kernel's interface also
  differs from what our `steps()` models: there is no `setProvider` (the
  provider is a `createJob` argument — which our own docstring had already
  deduced), settlement goes through a separate EvaluatorRouter, and the
  accessors are `jobCounter()` / `getJob(uint256)`, not the `nextJobId()` /
  `jobs(uint256)` we probed for. Recorded, not built: pointing a hire button at
  an address we have not verified ourselves is the thing this project is named
  after, and verifying it is a separate piece of work.

---

## The verification story, which is the point

Steps 1–7 were built, tested, and passing **156 tests**. Before starting Step 8,
three independent verification passes ran over that work. They found **23
defects**. Every single one passed the green suite.

### The one a third agent found

Spec §3.4 defines toxic flow with two conditions joined by `or`: a CEX–DEX gap,
**or** a swap-imbalance z-score past a threshold. The engine passed a literal
`0.0` for that z-score on every sample. The second arm could never fire; `z_pull`
and `M` were parameters that traced to nothing; the branch was unreachable code.
Its unit test passed the whole time, because it handed the policy a z-score
directly and never asked whether anything computed one.

**Warden could not find this.** It reaches the same pull through either arm, so a
dead arm looks like a quiet one. Grid ignores health entirely. Sentinel's primary
signal *is* that z-score — and it never withdrew, once, on any tape.

That is the argument for building a third agent, stated concretely: each policy
leans on a different part of the engine, and the engine only learns which of its
parts are wired when something puts weight on them.

Fixing it exposed two more. The policy tested `imb > z_pull` and the engine
tested `|imb| > z_pull`, so on one-way *selling* an agent could be held out of the
market by a condition its own policy said was not happening — two rules where
there should have been one, invisible while the value was always zero. And the
synthetic tape turned out not to be a **possible history**: every swap had the
pool receiving token0 and paying token1 while price random-walked both ways,
which no AMM can produce. It read as fifty consecutive sells, and Warden pulled.
The estimator was right and the fixture was wrong — and the fixture had also been
hiding a wrong T2 bound, which multiplied every fee by price unconditionally and
was correct only because the input token was always the same one.

Two would have been serious:

**κ was fitted in one unit and consumed in another.** Spec §5.2 fits the decay
against a distance in *ticks*; equation (2) needs it per *log-price*. The two
differ by 10,000×. Fed the per-tick value, `decide()` returned a half-width of
**35,450 ticks — a ±3,363% price band**. Effectively full-range, earning almost
nothing while calling itself concentrated liquidity, and a positive finite number
that would have minted without reverting. This is a contradiction *inside the
frozen spec*, not only in the port.

**A `float("nan")` made every `Decision` unequal to itself** on the CEX-feed-down
path. `Decision` is hashable precisely so T1 can compare sequences bitwise, and
NaN is not equal to itself — twenty calls on one identical input produced twenty
mutually unequal objects. T1 could never have passed there.

The suite that missed both checked *relationships* — wider with volatility,
tighter with κ — and relationships hold perfectly well when every value is off by
four orders of magnitude. Two tests were also doing nothing at all: one asserted
`fit.kappa > 0.0 or fit.is_fallback`, where both branches return something
positive; the other compared a grid-rounded width with a tolerance equal to the
grid quantum.

All 23 are in [`REQUIREMENTS_MATRIX.md`](REQUIREMENTS_MATRIX.md) with their
arithmetic. Later steps found more the same way — a slippage bound that could
never pass, a transaction that reverted in silence, a gate wired to nothing, a
quote that annualised eight hours by multiplying by a thousand.

**A marketplace that claims its numbers survive checking should be able to show
the checking.**

---

## Three external claims we checked rather than repeated

- **ERC-8183 is not a "hire interface."** It is escrowed *Agentic Commerce*. With
  the provider named at creation, the client's path to escrowed is **four
  transactions** — `approve` → `createJob` → `setBudget` → `fund` — and
  settlement adds the provider's `submit` and the evaluator's `complete`, so
  **six end to end**. The `evaluator` is mandatory and cannot be zero; only it
  may complete or reject. ERC-2771 meta-transactions are an optional extension,
  not core, so nothing batches these away. It is not one click.
- **And it is not on mainnet.** We had written "live on both BSC networks" in our
  own verified-facts table. It is wrong: BNB Chain's announcement says the SDK is
  live on **testnet**, with "mainnet coming soon", and the EIP is Draft with **no
  reference deployments listed**. Corrected 15 Aug 2026. A marketplace that
  shipped a mainnet hire button against an address nobody had seen would be doing
  the precise thing this project is named after.
- **The registry is enormous, and mostly not callable.** Its population is the
  number every competitor will put on a landing page; the row under it is the one
  that matters. Read from chain and regenerated with the document, because it
  grows by roughly a thousand registrations an hour:

<!-- derived:registry — regenerated by `make judges`; do not hand-edit -->
| | |
|---|---|
| agent ids the registry resolves | **280,287** |
| sampled | 400, spanning ids 123–280,280; 24 published as cards |
| card resolves | 369 / 400 (92%) · 95% CI 89%–94% |
| declares itself active | 361 / 400 (90%) · 95% CI 87%–93% |
| **describes a service** | **143 / 400 (36%) · 95% CI 31%–41%** |
| **substantive** | **139 / 400 (35%) · 95% CI 30%–40%** |
<!-- /derived:registry -->

  Nine in ten registrations resolve and declare themselves active; three in ten
  name an endpoint you could call. `active` is a self-report and costs nothing.
  Even our bar is weaker than the peer-reviewed **~4%** whose endpoints actually
  answer ([arXiv:2606.26028](https://arxiv.org/abs/2606.26028)), and **P-21** has
  the method — including the sampling bias that would have measured the registry's
  oldest 0.3% and reported it as the whole.
- **On-chain reputation is deliberately not displayed.** The same study found
  that after removing Sybil-flagged feedback, **77.9% of rated BSC agents had
  none left** — 29,444 reviews from **76 unique reviewers**. There is no
  `reputation_score` function in this codebase, and a test asserts its absence.
  A rating computed from that would look precise and mean nothing, which is the
  misquote this project is named after.

---

## Where to look

| | |
|---|---|
| The claim, frozen | [`WARDEN_SPEC_v1.0_FROZEN.md`](WARDEN_SPEC_v1.0_FROZEN.md) |
| Every deviation, with arithmetic | [`REQUIREMENTS_MATRIX.md`](REQUIREMENTS_MATRIX.md) |
| Every assumption, published | [`ASSUMPTIONS.md`](ASSUMPTIONS.md) |
| The policy, 871 lines, pure | `packages/misquote/core/policy.py` |
| Why look-ahead is structural | `packages/misquote/replay/tape.py` |
| The tests that carry the claim | `tests/replay/`, `tests/chain/` |
