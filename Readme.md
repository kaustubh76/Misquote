<div align="center">

# Misquote

**Every other marketplace misquotes you. This one shows its math.**

An agent marketplace for BNB Chain where a listing card is not a star rating —
it is a replay of that agent's own policy over real chain history, quoted as a
P25–P75 range.

[**Live site**](https://misquote.vercel.app) ·
[**20-second demo**](https://misquote.vercel.app/demo) ·
[**PancakeSwap simulator**](https://misquote.vercel.app/simulate) ·
[**Readiness gate**](https://misquote.vercel.app/status)

</div>

---

> **Judging this? Start with [`docs/FOR_JUDGES.md`](docs/FOR_JUDGES.md).** It
> leads with what is proven and what is not, and `make go-no-go` is a checklist
> that executes rather than a checklist that is read.

---

## What this is

Agent marketplaces run on misquotes — star ratings, install counts, and claims
the agent's own author wrote. None of it is checkable, and none of it answers
the buyer's only question: *am I better off hiring this than doing it myself?*

Misquote answers it by measurement. Four agents are replayed over real
PancakeSwap v3 and Venus history, and every task is run a second time with the
agent switched off — through the **same** replay driver with `policy=` swapped,
so the baseline cannot be quietly weakened. One rule holds everywhere: every
number on the site traces to a chain query or to a published assumption, or it
does not render.

It publishes its losses. One of the four agents loses its task by 68.55
percentage points, and its card measures why rather than hiding it.

## Try it without installing anything

| | |
|---|---|
| [`/demo`](https://misquote.vercel.app/demo) | Four steps to a P25–P75 range. No wallet, no API key, nothing funded. |
| [`/simulate`](https://misquote.vercel.app/simulate) | Pick a pool, a range width and a size; see what that position earned on swaps that already happened. 1,400 pre-replayed positions — and it refuses sizes past 1% of pool depth. |
| [`/quote`](https://misquote.vercel.app/quote) | Paste a wallet; each agent's policy is replayed against its real position history. |
| [`/advantage`](https://misquote.vercel.app/advantage) | Every task, run with the agent and without it. |
| [`/status`](https://misquote.vercel.app/status) | The readiness gate, rendered. It currently says **NOT YET**. |

## The four agents

One engine, one tape, one cost model, one LVR accountant — four genuinely
different policies.

| Agent | Category | Quote | vs. doing it yourself |
|---|---|---|---|
| **Warden** | Rebalancing | 20.70%–36.15% | **+17.21pp**, wins 60 of 60 windows |
| **Grid** | Market making | 19.50%–31.90% | **+12.71pp**, bands do not overlap |
| **Sentinel** | Health | −56.14%–−52.84% | **−68.55pp** — it loses, and says why |
| **Router** | Yield | net over 125h | −0.01pp, below the materiality floor |

Warden is Avellaneda–Stoikov reservation pricing and optimal spread mapped onto
v3 tick ranges. Grid is a deliberately simple three-parameter ladder, there to
prove the engine is not a Warden harness. Sentinel is threshold de-risking whose
pull rule fires on 41.94% of real samples — the measured cause of its loss, left
untuned because the spec governing it is frozen. Router switches between Venus
lending markets and reads a different tape entirely.

## Quick start

```bash
make setup          # uv sync
make test           # the offline suite, no network
make showcase-demo  # replay the three LP agents, write their cards
make router-card    # and the fourth
make web            # http://localhost:3000
make go-no-go       # the gate — it currently says NOT YET
```

`make go-no-go` is the one worth running first.

## How the numbers are held honest

| Claim | How it is checked |
|---|---|
| The replay cannot see the future | **T1**, bitwise: run twice, the second run replacing every post-cut event with seeded noise, floats compared at exact bits — plus a negative control proving tampering *does* change decisions |
| The live agent and the replay are one policy | **L1**: the live driver, its own file and own loop, over a tape-backed source, compared byte for byte |
| The tick math is PancakeSwap's | 19,546 vectors recorded from the real Solidity, exact integer equality, no tolerance |
| Position math matches the contracts | Mint through the real NonfungiblePositionManager on a BSC fork, compared to **one wei** |
| The DIY baseline is not a different program | Both columns are one `ReplayDriver` with `policy=` swapped, and a test asserts it |

One finding is load-bearing: PancakeSwap takes a **34% protocol cut** that
Uniswap does not, so reconstructing fees the obvious way overstates LP earnings
by **1.515×** — straight onto the headline APR.

## What is on chain

ERC-8004 identities on BSC mainnet (`323262`, `323332`–`323334`, and a re-mint
at `331592`) and on chapel. An ERC-8183 budget escrowed on mainnet with real
money and reclaimed — job 56681 funded, `claimRefund` mined — and job 56718
funded and delivered into. Altana session keys granted and revoked on chapel.

Two caveats the site states itself: **one wallet was both client and provider**
on those jobs, so they prove the escrow mechanics and hire nobody; and of the
four session-key caps, **two are enforced** by that deployment — expiry and
one-transaction revoke — while the allowlist and spend cap need a validator
module no grant on that keystore carries.

## What is not done

Six entries, generated from
[`tearsheet/ledger.py`](packages/misquote/tearsheet/ledger.py) and rendered at
[`/status`](https://misquote.vercel.app/status). Nothing has traded with real
money: the flagship agent refuses to sign on mainnet **in code**, not by
convention. Under-claiming is the point — a marketplace that cannot show you its
own failures is the thing this project was built to argue against.

## Repo layout

```
misquote/
├── packages/misquote/        # one installed package
│   ├── core/                 # A-S math: reservation price, spread, ticks
│   ├── estimators/           # sigma EWMA, kappa fit, gas medians (trailing-only)
│   ├── lvr/                  # realized-LVR accountant
│   ├── replay/               # the no-look-ahead replay engine
│   ├── indexer/              # BSC events: swaps, mints, burns
│   ├── chain/                # RPC, signer, position manager, executor
│   ├── registry/             # ERC-8004 + ERC-8183 hire + TermiX auth
│   ├── sessions/             # Altana caps subset: grant/inspect/revoke
│   ├── vetting/              # nine on-chain checks and the fork proofs
│   ├── api/                  # FastAPI: artifacts, quotes, metrics
│   ├── tearsheet/            # ledger -> metrics -> report generator
│   └── agents/               # warden, grid, sentinel, router
├── apps/web/                 # Next.js front-end, exported statically
├── studio/                   # the A2A seller agent (Node)
├── vetting/                  # badge records, address readings, the forge lab
└── ops/                      # runbook, pinned Solidity deps, the KILL file
```

## Docs

| | |
|---|---|
| [`docs/FOR_JUDGES.md`](docs/FOR_JUDGES.md) | The entry point. What is proven, and what is not. |
| [`docs/PROJECT_DESCRIPTION.md`](docs/PROJECT_DESCRIPTION.md) | The project in one page, at three lengths. |
| [`docs/AGENT_ADVANTAGE.md`](docs/AGENT_ADVANTAGE.md) | Every task, with and without the agent. |
| [`docs/ASSUMPTIONS.md`](docs/ASSUMPTIONS.md) | The published assumption sheet. |
| [`docs/PANCAKESWAP_FINDINGS.md`](docs/PANCAKESWAP_FINDINGS.md) | Six ways v3 differs from Uniswap's, and what each costs. |
| [`docs/WARDEN_SPEC_v1.0_FROZEN.md`](docs/WARDEN_SPEC_v1.0_FROZEN.md) | The frozen spec governing Warden and the engine. |
| [`docs/REQUIREMENTS_MATRIX.md`](docs/REQUIREMENTS_MATRIX.md) | Every review complaint, and its status. |
| [`docs/BUILD_PLAN.md`](docs/BUILD_PLAN.md) | How this was built: phases, definitions of done, the cut order. |

## Environment

**[`.env.example`](.env.example) is the list.** Copy it to `.env` and fill in
what you need; every variable in it is one the code reads, and every variable
the code reads is in it — [`tests/test_env_template.py`](tests/test_env_template.py)
walks the AST for `os.environ` accesses and fails if the two sets differ.

Two worth knowing before you start:

- **`MISQUOTE_DRY_RUN`** defaults to on. Every chain write prints what it would
  send and sends nothing until `MISQUOTE_DRY_RUN=0` is set on that one command.
  It does not belong in `.env`.
- **`MISQUOTE_API_BASE`** is where the live API is. Unset, `make artifacts`
  keeps whatever base is already published rather than blanking it.

`make warden CHAIN=56` runs the agent against BSC mainnet. It **records and
cannot spend**: `--broadcast` is refused on chain 56 in
`agents/warden/__main__.py`, in code rather than by convention.

---

<div align="center">

*The only thing misquoted here is the name. Audit me.*

</div>
