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
make test                     # 659 tests, no network, ~35s
make showcase-demo            # replay all three agents, write the cards
make web                      # http://localhost:3000
make go-no-go                 # the mainnet gate — it currently says NOT YET
```

`make go-no-go` is the one worth running first. It is a checklist that executes,
and it refuses to go green on anything nobody has checked.

---

## What is actually proven

Each of these is a test you can run, not a claim.

| Claim | How it is checked | Where |
|---|---|---|
| The tick math matches PancakeSwap's exactly | 19,546 comparisons against the real Solidity, exact integer equality, zero mismatches | `make vectors-check` |
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
| We price a tokenized equity with no code changes | TSLAx/USDT — different fee tier, different spacing, different protocol fee | `tests/chain/test_equity_pool.py` |
| The agent can actually mint, recentre and withdraw | Real transactions on a forked BSC, including that a half-failed recentre leaves the wallet flat rather than stranded | `tests/chain/test_executor.py` |

**691 tests: 659 offline, 32 against a live chain or a fork.**

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
make advantage-demo      # three tasks, both ways, on a labelled synthetic tape
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
the three are distinct — and task 2's baseline is an ablation rather than a
different strategy, so the comparison isolates the withdrawal decision and
nothing else.

**One of the three goes against us, and it is the one we built for safety:**

| Task | DIY | Agent | Δ median |
|---|---|---|---|
| Earn | 5.63 – 26.05% | 36.88 – 38.72% | **+27.75pp** |
| **Protect** | **8.91 – 9.05%** | **7.13 – 7.31%** | **−1.77pp** |
| Choose | −1.87 – −1.36% | 35.76 – 38.31% | **+38.22pp** |

Sentinel loses to its own ablation. That is **P-7 with a price tag**: we had
already measured that §3.4's imbalance rule fires about once every four hours on
a driftless random walk — a tape with no informed flow in it by construction, so
every one of those withdrawals is a false alarm — and this is what those false
alarms cost. We did not retune `z_pull` to fix it; it is spec §8's published
value. Had *Protect* been scored against a passive position instead of against
the ablation, the loss would have been buried inside a difference of band width
and never attributed to the rule that caused it.

Across all three tasks the report **refuses to call a winner** — three tasks are
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
returned **0, 0 and 1 swaps** against the flagship's **473, 325 and 171** — about
384 swaps in a month against 372,000, and the equity figure rests on one trade.
So **there is no equity tape and there will not be one**: `verdict(min_n=30)`
would refuse it and cutting 384 swaps into twenty sub-windows leaves nineteen
each. The pool stays a *generality* proof — same code, different fee tier,
spacing and protocol fee — which is exactly what `test_equity_pool.py` asserts
and the whole of what it asserts. It is not a venue we can quote, and the
advantage report's third task says so rather than presenting constructed pools as
real ones. It is also the *only* xStocks v3 pool on BSC with real liquidity at
all; NVDAx and AAPLx have no pool at any tier, and the 1.00% TSLAx pool exists
with zero liquidity and was refused rather than quoted.

**Security: the sponsor's own escrow, verified rather than trusted.** TermiX's
AACP builds on ERC-8004 and ERC-8183 — and their `IdentityRegistry` is
`0x8004A169…a432`, **byte-identical to the contract this codebase already read**.
Their `TermixEscrow` is now in `JOB_ESCROW[56]`, but only with
`JOB_ESCROW_EVIDENCE` recording what was checked *and what was not*: it is an
EIP-1967 proxy over 17,941 bytes, `settlementToken()` returns our own USDT, and
**nobody has read an ERC-8183 job back out of it**, so it is a verified escrow
rather than a verified ERC-8183 escrow. It is also **upgradeable by its owner** —
escrowed funds sit behind code that can be replaced — which is a property of the
venue a marketplace routing user money through it should disclose rather than
discover.

**And the report is not yet "real".** It runs on a synthetic tape, badged on every
line. The keyed `BSC_RPC_URL` therefore blocks this track's core requirement, not
merely two amber gates.

---

## What is NOT done

Stated plainly, because a submission that hides its gaps is doing the thing this
project exists to argue against.

- **No 30-day tape — and the first reason we gave for it was wrong.** We recorded
  that free BSC endpoints "refuse a *rate*, not a *range*". Surveyed properly on
  16 Aug 2026, one request at a time, that is not what they do:

  | Of 22 public BSC endpoints | `eth_getLogs` |
  |---|---|
  | 8 (every bnbchain dataseed, both defibit, ninicoin) | **refused at any width**, including one block |
  | 3 (`blxrbdn`, `48.club`, `publicnode`) | served, capped at **5,000 blocks** |
  | 2 (`1rpc`, `blockrazor`) | served, capped at 50 and 25 blocks |
  | the rest | unreachable, wrong chain, or `eth_getLogs is not supported` |

  Two of our own three configured endpoints were in the first row, and the health
  check selected on `eth_chainId` — which all of them pass. So the indexer could
  hold a list of endpoints that could never serve it, and a tail refused on every
  request looks exactly like a tail working on a pool nobody trades. Written up
  as requirements-matrix **P-11**, together with the correction to the earlier
  claim; the original measurement is still in the document with its error marked,
  because deleting it would hide the more useful finding — *an instrument that
  cannot attribute its own result will be over-read.*

  A 30-day backfill is 1,152 requests at 5,000 blocks each, and still wants a
  keyed `BSC_RPC_URL`. A **live tail is one request per 37 minutes of chain**, so
  `make indexer-follow` accumulates real data today, on free endpoints, with no
  key. We cannot recover thirty days of *history*; we can accumulate it going
  forward. Nothing about that turns a short tape into a thirty-day claim, and
  the go/no-go still reports the tape amber until it spans 25 days.
- **κ is still a provisional default.** It is meant to be fitted on that tape and
  published as gap item G-4. Until then it traces to a stated basis rather than
  to data, and the go/no-go reports it amber.
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
- **Nothing has traded with real money**, and the go/no-go will not let it until
  the above are green.
- **Router agent, session keys, and the ERC-8183 hire flow** are not built.
  Warden, Grid and Sentinel are. Grid and Sentinel exist mainly to prove the
  engine is not a Warden harness with delusions of generality — and Sentinel
  earned its place by finding a rule that had never once fired (below).

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
- **The registry has 266,191 agents on BNB Chain**, more than any other chain by
  4×. That is the number every competitor will put on its landing page. On a
  random sample of 60 live agents, **33% clear every bar** we can check offline —
  and even that is a weaker test than the peer-reviewed **~4%** whose endpoints
  actually answer ([arXiv:2606.26028](https://arxiv.org/abs/2606.26028)).
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
| The policy, 486 lines, pure | `packages/misquote/core/policy.py` |
| Why look-ahead is structural | `packages/misquote/replay/tape.py` |
| The tests that carry the claim | `tests/replay/`, `tests/chain/` |
