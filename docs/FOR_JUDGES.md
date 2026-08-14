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
make test                     # 359 tests, no network, ~70s
make showcase-demo            # replay both agents, write the cards
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

**375 tests: 359 offline, 16 against a live chain or a fork.**

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

- **No 30-day tape.** Free BSC endpoints cap `eth_getLogs` at ~2,000 blocks and
  refuse sustained request rates with 403 and `-32005` — all of them. The
  indexer is built, verified against real chain data, and idempotent; it needs a
  keyed RPC to finish a multi-day backfill.
- **κ is still a provisional default.** It is meant to be fitted on that tape and
  published as gap item G-4. Until then it traces to a stated basis rather than
  to data, and the go/no-go reports it amber.
- **No 24-hour testnet burn-in.** The loop is built and tested; nobody has run it
  unattended for a day.
- **Nothing has traded with real money**, and the go/no-go will not let it until
  the above are green.
- **Sentinel and Router agents, session keys, and the ERC-8183 hire flow** are
  not built. Grid is, and exists mainly to prove the engine is not a Warden
  harness with delusions of generality.

---

## The verification story, which is the point

Steps 1–7 were built, tested, and passing **156 tests**. Before starting Step 8,
three independent verification passes ran over that work. They found **23
defects**. Every single one passed the green suite.

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

- **ERC-8183 is not a "hire interface."** It is escrowed *Agentic Commerce*:
  `createJob` → `setBudget` → `fund`, plus an approve, plus settlement — three to
  four transactions and a mandatory evaluator, not one click.
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
