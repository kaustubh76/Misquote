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
make test                     # 395 tests, no network, ~45s
make showcase-demo            # replay all three agents, write the cards
make web                      # http://localhost:8080
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

**411 tests: 395 offline, 16 against a live chain or a fork.**

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

---

## What is NOT done

Stated plainly, because a submission that hides its gaps is doing the thing this
project exists to argue against.

- **No 30-day tape.** Free BSC endpoints cap `eth_getLogs` and refuse sustained
  request rates — all of them. This is measured, not assumed: asking for **six
  hours** of the target pool (47,979 blocks) across three rotating endpoints at
  0.15s pacing dies after **11 seconds** with `-32005 limit exceeded`, before
  writing a single row. Thirty days is 5.76M blocks. The indexer is built,
  verified against real chain data, and idempotent — its cursor advances with its
  rows, so a re-run resumes — but it needs a keyed RPC to finish.
- **κ is still a provisional default.** It is meant to be fitted on that tape and
  published as gap item G-4. Until then it traces to a stated basis rather than
  to data, and the go/no-go reports it amber.
- **No 24-hour testnet burn-in.** The loop is built and tested; nobody has run it
  unattended for a day.
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
| The policy, 454 lines, pure | `packages/misquote/core/policy.py` |
| Why look-ahead is structural | `packages/misquote/replay/tape.py` |
| The tests that carry the claim | `tests/replay/`, `tests/chain/` |
