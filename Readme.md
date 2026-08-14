# MISQUOTE

**Every other marketplace misquotes you. This one shows its math.**

Agent marketplace for BNB Chain (Smart Money Era hackathon) with four quant-grade
agents, a personal quote engine that replays agent policies on real position
history, and an auto-generated Agent Advantage Tearsheet. The name is the thesis:
agent marketplaces run on misquotes — star ratings, user counts, unverifiable
claims. Misquote is the anti-misquote: every number traces to chain state or a
published assumption, every quote is a P25-P75 range with the assumption sheet
one click away. Built solo, in public. Audit me.

---

> **Judging this? Start with [`docs/FOR_JUDGES.md`](docs/FOR_JUDGES.md).** It
> leads with what is proven and what is not, and `make go-no-go` is a checklist
> that executes rather than a checklist that is read.

---

## 0. Read this first (Claude Code operating rules)

1. **The spec is frozen.** `docs/WARDEN_SPEC_v1.0_FROZEN.md` governs the Warden
   and the replay engine. Equations, parameters, tests T1–T4, and assumptions
   A1–A5 are non-negotiable. If code and spec conflict, the spec wins; flag it.
2. **No scope additions.** Any "should we also add X" goes into
   `docs/SUNDAY_REVIEW.md` as a one-line note. Never implemented same-day.
3. **Cut order is pre-agreed** (see §7). Never propose cutting NEVER-CUT items.
4. **Tests before trust.** The replay engine's look-ahead guards (T1–T4) are
   implemented as pytest tests before the engine is considered working.
5. **Reuse first.** §6 names the source repos/components to port. Do not
   greenfield what the manifest says to port.
6. **Every displayed number** must trace to a chain query or an entry in the
   published assumption sheet. If it can't, it doesn't render.

## 1. What this is (60 seconds)

- **Surface:** landing with one input ("What do you want handled?") → routes to
  one of four categories → agent cards that are live mini-tearsheets → one-click
  activation with visible caps and one-tx revoke.
- **Kill-shot:** the **Personal Quote Engine**. Default = Showcase Mode (my own
  historical positions, auditable, + one labeled synthetic borrower). Connected
  wallet with positions → personalized quote. Output is always a **P25–P75
  range** ("would have captured $150–$210 net"), assumptions one click away.
- **Agents (equal depth, four categories):**
  - **Warden** (Rebalancing, flagship) — Avellaneda-Stoikov mapped to Pancake v3
    ranges; metric: fee APR net of realized LVR vs passive. Own infra.
  - **Grid** — discretized market maker (A-S, fixed rungs, inventory-aware
    requoting); metric: spread capture bps, fill rate. Own infra.
  - **Sentinel** (Health) — threshold de-risk live; Hawkes intensity as
    dashboard early-warning only; backtest = labeled appendix. Own infra.
  - **Router** (Yield) — whitelist APR router, optimal-switching boundary
    (move only when delta > gas+slippage). **Deployed via BNB Agent Studio CLI**
    (native-citizenship proof).
- **Agent Studio native:** all four register ERC-8004 identities + ERC-8183
  hire interfaces. The marketplace also indexes the ERC-8004 registry for
  third-party agents (see D1 decision rule, §8).
- **Activation:** Altana session keys, caps subset ONLY (allowlist, spend cap,
  expiry, Keystore, one-tx revoke). No b402, no Altana-escrow flows.
- **Proof:** Settlement Ledger (chain-state metrics only) → auto-generated
  **Agent Advantage Tearsheet**: 3 tasks run both ways (large swap · LP week ·
  pool due diligence), outputs attached.
- **Vetting Layer:** every pool a listed agent touches gets a due-diligence
  badge; findings ship a PoC that executes on a mainnet fork ("they flag, we
  prove"). Free tools are the honest benchmark, not human audit prices.

Prize targets: BNB main track (primary, pending prize-split verification),
TermiX podium, PancakeSwap, Altana XP (passive via caps subset).

## 2. Repo layout (monorepo)

```
misquote/
├── README.md                     # this file — the working brief
├── docs/
│   ├── WARDEN_SPEC_v1.0_FROZEN.md
│   ├── REQUIREMENTS_MATRIX.md    # every review complaint → status
│   ├── ASSUMPTIONS.md            # the published assumption sheet (renders in UI)
│   └── SUNDAY_REVIEW.md          # scope parking lot
├── packages/
│   ├── core/                     # A-S math: reservation price, spread, ticks
│   ├── estimators/               # σ EWMA, κ fit, gas medians (trailing-only)
│   ├── lvr/                      # realized-LVR accountant (spec §4, eq. 3)
│   ├── replay/                   # no-look-ahead replay engine (spec §6)
│   ├── indexer/                  # BSC events: swaps/mints/burns/liquidations
│   ├── registry/                 # ERC-8004 read/registration + ERC-8183 hire
│   ├── sessions/                 # Altana caps subset: grant/inspect/revoke
│   └── tearsheet/                # ledger → metrics → report generator
├── agents/
│   ├── warden/                   # flagship (spec-governed)
│   ├── grid/
│   ├── sentinel/
│   └── router/                   # Agent Studio CLI project (separate deploy)
├── apps/
│   └── web/                      # Next.js front-end (landing/cards/quotes/panel)
├── vetting/                      # fork-lab checks + badge generator
└── ops/                          # deploy scripts, monitoring, runbooks
```

## 3. Stack

- **Agents/backend:** Python 3.11 (ports from PolyLambda + Mission Control),
  `web3.py`, asyncio loops; SQLite for hackathon persistence (Postgres only if
  it hurts).
- **Front-end:** Next.js + Tailwind, wagmi/viem, RainbowKit connect.
- **Chain:** BSC mainnet + testnet; PancakeSwap v3 (Uniswap v3 math),
  Venus/Lista reads; NonfungiblePositionManager for LP ops.
- **Fork lab:** Foundry (anvil mainnet forks) for vetting PoCs.
- **No custom Solidity on the critical path.** ERC-8004/8183 are existing
  standard contracts we call; activation caps are Altana's contracts. Custom
  contracts only as clearly-flagged stretch.

## 4. Build order (mirrors the gates — do not reorder)

**Phase 0 — D1 verifications (before code):** see §8. Output: three answers
written into `docs/REQUIREMENTS_MATRIX.md`.

**Phase 1 (→ Gate 1, Aug 19): Warden live + activation**
1. `packages/core` + `packages/estimators` — port A-S math and estimators from
   PolyLambda per manifest. Unit tests against spec equations (1), (2).
2. `packages/indexer` v0 — pool swap/tick stream for one target v3 pool.
3. `agents/warden` — policy loop (R1–R4 + toxicity pull), v3 position manager,
   kill switches. 24h testnet burn-in, then **mainnet Aug 15, capped capital**.
4. `packages/sessions` — Altana grant/inspect/revoke wired to activation.
5. `agents/grid` — rung ladder on the same core.
6. `packages/registry` — ERC-8004 identity + ERC-8183 interface registration
   for both live agents.

**Phase 2 (→ Gate 2, Aug 26): quote engine + remaining categories**
7. `packages/lvr` + `packages/replay` — **the week's protected item.** T1–T4
   as pytest before feature work counts. Showcase quotes precomputed from my
   historical positions.
8. `agents/router` — 2-day version, deployed via Agent Studio CLI.
9. `agents/sentinel` — threshold mode + alerting.
10. `packages/tearsheet` — ledger + report generator skeleton.
11. Registry indexer view per D1 decision rule.

**Phase 3 (→ Gate 3, Sep 2): the front-end war**
12. `apps/web` — landing sentence, category pages, tearsheet cards, quote UX
    (ranges + assumption sheet), compare tray, session panel with revoke,
    evaluator path. Zero new backend below the UI line.
13. `vetting/` badges if schedule green.

**Phase 4 (→ Freeze Sep 5):** run the 3 tearsheet tasks for real, demo video,
hardening, README-for-judges. Submit by Sep 9.

## 5. Definitions of done (per component)

- **core/estimators:** equations (1)/(2) reproduced against hand-computed
  fixtures; estimators provably trailing-only (timestamp asserts).
- **warden:** spec §10 acceptance list, verbatim.
- **replay:** T1 (shuffle-future, bitwise), T2 (fee conservation), T3
  (timestamp asserts), T4 (passive self-consistency ≤ 1 bp) all green on one
  real pool's 30-day history.
- **sessions:** grant → visible in Keystore → agent tx through session →
  revoke → agent tx fails. Demonstrated on testnet, scripted.
- **registry:** our 4 agents resolvable via ERC-8004 read; hire callable via
  ERC-8183 from the web app.
- **tearsheet:** report generated from ledger with zero hand-entered numbers.
- **web:** an external tester completes land → quote → activate → revoke with
  no dead end and no instruction.

## 6. Reuse manifest (port, don't greenfield)

| From | What | Into |
|---|---|---|
| PolyLambda | A-S quoting core, inventory tracking | `packages/core` |
| PolyLambda | σ EWMA, intensity fit, sim event loop | `packages/estimators`, `packages/replay` |
| Mission Control | BSC RPC/signing/nonce/retry, alerting, indexer scaffold | `agents/*`, `packages/indexer`, `ops/` |
| Vault Analyzer | metric/report generation patterns | `packages/tearsheet` |

## 7. Cut order & never-cut (pre-agreed; anti-2am clause)

**Cut in this order if a gate slips:** 1) compare tray · 2) Hawkes dashboard
signal · 3) vetting badges · 4) third-party auto-cards.
**NEVER CUT:** Warden · Showcase Mode · replay engine (with tests) · activation
caps · the tearsheet.

## 8. D1 checklist (open items — answer before Phase 1)

- [ ] Prize split verified in BNB Discord (page says $30K = total pool).
- [ ] ERC-8004 registry population counted on BscScan. Decision rule: **< ~15
      real agents → third-party auto-cards demote immediately to a plain
      "registry view"** and the narrative is "day-one marketplace for a day-one
      ecosystem."
- [ ] ERC-8183 hire call invoked from an external script successfully (no
      permissioning surprises).
- [ ] Agent Studio CLI hello-world deployed (answers the router path).
- [ ] Mission Control micropayment discrepancy (49 vs 75) resolved; correct
      number recorded in `docs/REQUIREMENTS_MATRIX.md` before any card renders.

## 9. Environment

```
BSC_RPC_URL=            # mainnet
BSC_TESTNET_RPC_URL=
WALLET_KEYSTORE_PATH=   # never a raw key in env
TARGET_POOL=            # Pancake v3 pool address (Warden)
CEX_FEED_URL=           # toxicity signal; on-chain fallback if unset
ALTANA_*=               # session key config
DB_PATH=./misquote.db
```

Run: `make indexer` · `make warden ENV=testnet` · `make replay-tests` ·
`make web` — Makefile targets are part of Phase 1 deliverables.

## 10. The pitch (for the repo header and the demo)

> Agent marketplaces run on misquotes — stars, counts, claims nobody can check.
> **Misquote** replays every agent's policy on your actual positions and quotes
> you an honest range instead — then lets you hire with visible caps and
> one-click revoke, and proves the advantage in a tearsheet generated from
> chain state. The only thing misquoted here is the name. Audit me.

Demo opener (use verbatim): "It's called Misquote because that's what every
other marketplace does to you."