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
    (move only when delta > gas+slippage). A **second agent**, scaffolded by the
    Agent Studio CLI, is deployed and serves the ERC-8183 seller interface —
    `/studio` renders the signed quote it returns. `bag deploy` itself is the
    one part still not done, and it is on the ledger.
- **Agent Studio native:** the marketplace indexes the ERC-8004 registry for
  third-party agents (see D1 decision rule, §8), and **all four of our agents are
  registered on both networks** — chapel ids 1927-1930 and **mainnet ids 323262,
  323332-323334 and 331592** — owned by the operator, each card byte-identical
  to the one `cards.py` builds and each passing `erc8004.assess()` as
  *substantive*, which is the same bar the survey holds third parties to.
  `vetting/identity/56.json` is the reading the go/no-go prefers, because it is
  the stronger claim and the one TermiX's explorer indexes; `97.json` is the
  chapel one. `make identity-verify` re-derives either from chain. There are two
  Wardens on mainnet and that is a measurement, not a slip — TermiX attributes an
  agent to the wallet that *minted* it rather than the one that owns it now, so
  the transferred registration stayed invisible and a re-mint was the test.

  **The ERC-8183 hire is built and has moved real money.** This bullet said the
  interfaces were "not built" and that "nobody here has created, funded,
  submitted or settled a job" long after all but the last of those had happened
  — job 746 on chapel, then **56681 on BSC mainnet funded with 0.1 of the
  payment token and reclaimed by `claimRefund`**, then 56718 funded and
  submitted. `settle` is the one call still unproven outside a fork; it reverts
  `NotDecided()` until the OptimisticPolicy's seven-day window runs. The `hire`
  entry in `index.json`'s `not_built` block is the authority on that last call
  and on nothing wider, and `check_escrow_flow` in the go/no-go now reads it off
  the artifact rather than leaving it to a sentence here.

  This sentence has now been wrong in both directions. It claimed both as done
  when neither was; it was then corrected to "planned, not built" against the
  ledger's text rather than against the chain, which under-claimed a registration
  that already existed. The chain is the authority, and it says four.
- **Activation:** Altana session keys, caps subset ONLY (allowlist, spend cap,
  expiry, Keystore, one-tx revoke). No b402, no Altana-escrow flows.
- **Proof:** Settlement Ledger (chain-state metrics only) → auto-generated
  **Agent Advantage Tearsheet**: 4 tasks run both ways (Earn — fees on a
  liquidity position · Protect — avoid being picked off by one-way flow · Choose
  — which pool to provide liquidity to · Route — which lending venue to supply
  to), outputs attached.
- **Vetting Layer:** every pool a listed agent touches gets a due-diligence
  badge; findings ship a PoC that executes on a mainnet fork ("they flag, we
  prove"). Free tools are the honest benchmark, not human audit prices.

Prize targets: BNB main track (primary, pending prize-split verification),
TermiX podium, PancakeSwap, Altana XP (passive via caps subset).

## 2. Repo layout (monorepo)

```
misquote/
├── README.md                     # this file — the working brief
├── MISQUOTE_FLOW.excalidraw      # the whole system on one canvas (`make diagram`)
├── docs/
│   ├── WARDEN_SPEC_v1.0_FROZEN.md
│   ├── REQUIREMENTS_MATRIX.md    # every review complaint → status
│   ├── ASSUMPTIONS.md            # the published assumption sheet (renders in UI)
│   └── SUNDAY_REVIEW.md          # scope parking lot
├── packages/misquote/            # one installed package; every path below is inside it
│   ├── core/                     # A-S math: reservation price, spread, ticks
│   ├── estimators/               # σ EWMA, κ fit, gas medians (trailing-only)
│   ├── lvr/                      # realized-LVR accountant (spec §4, eq. 3)
│   ├── replay/                   # no-look-ahead replay engine (spec §6)
│   ├── indexer/                  # BSC events: swaps/mints/burns/liquidations
│   ├── chain/                    # RPC, signer, position manager, executor
│   ├── registry/                 # ERC-8004 + ERC-8183 hire + TermiX auth
│   ├── sessions/                 # Altana caps subset: grant/inspect/revoke
│   ├── vetting/                  # nine on-chain checks + the fork proofs
│   ├── api/                      # FastAPI: artifacts, quotes, /metrics
│   ├── ops/                      # metrics, heartbeat, alerts, the job queue
│   ├── tearsheet/                # ledger → metrics → report generator
│   └── agents/
│       ├── warden/               # flagship (spec-governed)
│       ├── grid/                 # Market making
│       ├── sentinel/             # Health
│       └── router/               # Yield: allocation policy
├── apps/
│   └── web/                      # Next.js front-end (landing/cards/quotes/panel)
├── vetting/                      # badge records, address readings, the forge lab
└── ops/
    ├── RUNBOOK.md                # what to do when something is wrong
    ├── forge_deps.txt            # pinned commits for the vendored Solidity
    └── KILL                      # absent, and its presence stops every broadcast
```

Two corrections, because this tree was wrong in ways worth naming rather than
quietly fixing. Everything under `packages/` is really under
`packages/misquote/` — the paths listed here were not importable. And `ops/` was
described as holding "deploy scripts, monitoring, runbooks" while holding one
pinned-dependency list; the monitoring lives in `packages/misquote/ops/`, which
this tree did not mention at all, and the runbook now exists. Deploy is
`render.yaml` and `scripts/serve.sh`, at the root.

## 3. Stack

- **Agents/backend:** Python 3.12 (ports from PolyLambda + Mission Control),
  `web3.py`, asyncio loops; SQLite for hackathon persistence (Postgres only if
  it hurts).
- **Front-end:** Next.js + Tailwind ✅ (`apps/web`, React + TypeScript, vitest).
  ~~wagmi/viem, RainbowKit connect~~ — **not built, and not currently needed.**
  The page reads precomputed JSON artifacts and never imports a wallet library,
  which is what lets `make web-static` serve the whole thing from
  `python3 -m http.server` with every backend process down — the state a demo is
  most likely to find them in. A wallet connect returns only when there is a
  personalised quote to connect *for*. Corrected 15 Aug 2026.
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
8. `agents/router` — **built.** Venus venue, realized-APR estimator, switching
   boundary. The Agent Studio *deployment* is separate and is on the ledger.
9. `agents/sentinel` — threshold mode + alerting. **Built** (threshold mode; no
   alerting yet). It paid for itself immediately: its primary signal is §3.4's
   swap-imbalance z-score, which the engine had been passing as a hardcoded
   `0.0`, so the rule had never fired. See **V-11** in the requirements matrix.
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
  revoke → agent tx fails. **Partly met, and the split is the point.** The
  grant/revoke round trip is done on chapel with three mined transactions —
  `initialRegisterKey`, `registerKey`, `revokeKey`, with `isValidKey` reading
  true and then false — recorded in `vetting/identity/session-keys-97.json` and
  rendered on `/activate`.

  This said **Not met**, on the grounds that "no Altana module has been verified
  on either network". That was a claim about `vetting/addresses/`: the SDK
  published `keyStore` and `keyStoreController` for both chains all along, in
  the same package `JOB_ESCROW` was verified from. **P-27.**

  What is **not** met is the caps. The keystore enforces the expiry and the
  revoke; the allowlist and the spend cap belong to a `validator` module nobody
  here has read, and every grant on this deployment carries `validator = 0x0`.
  So `VALIDATOR_MODULE` is empty for the reason `SESSION_KEY_MODULE` used to be,
  there is still no Hire button, and `/activate` says which two of the four caps
  are real.
- **registry:** our 4 agents resolvable via ERC-8004 read; hire callable via
  ERC-8183 from the web app. **Not met** — see above. The registry *read* path
  is built and surveys 280,287 agent ids; the write path has never been run.
- **tearsheet:** report generated from ledger with zero hand-entered numbers.
- **web:** an external tester completes land → quote → activate → revoke with
  no dead end and no instruction. **Partly met, and it is the only bullet here
  that never had a verdict written against it** — which is itself the finding.

  The arc now runs, from `/demo`: land → a recorded wallet → a real replay's
  P25–P75 range → the three mined chapel transactions on `/activate`. The last
  step is deliberately *not* simulated; walking to real receipts is better
  evidence than miming a grant beside them.

  Two qualifications. Steps two and three are **simulated**, banner-marked, and
  recorded from a real job on the real tape — a live run needs a warm worker and
  tens of minutes. And "no instruction" is not met for a visitor who arrives
  with a BSC position of their own: they still paste an address and wait.

  What made this worth doing was not the missing page. The simulation layer had
  been complete, tested and deployed for weeks with **nothing linking to it**,
  and the one fixture written for the flagship refusal could not fire at all —
  `/quote` submitted below the scenario short-circuit, so a page showing the
  simulation banner talked to production. **P-31.**

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
- [x] ERC-8004 registry population counted — **on chain, not on BscScan**, by
      binary search on `ownerOf` because `totalSupply()` reverts on this proxy.
      **272,322 agent ids resolve**, growing ~1,100/hour, against the `< ~15`
      the decision rule was written around. The rule therefore resolves the
      other way: auto-cards are viable, and third-party agents are listed on
      `/registry`. What the count does *not* say is how many are real — the
      first survey puts **90% resolvable and declaring themselves active, and
      30% naming an endpoint you could call**. See **P-21**.
- [x] ERC-8183 hire call **not** invoked. `TermixEscrow` implements none of the
      calls, across 5,894 candidate signatures (**P-18**) — but a different
      contract does: Altana's AgenticCommerce kernel passed the same three-way
      check on both BSC networks, with 56,632 jobs on mainnet, so `JOB_ESCROW`
      now carries two verified addresses and `escrow_address()` returns them
      (**P-24**). What is still not invoked is the **write** path, which needs a
      signer.
- [x] ERC-8183 hire call invoked from an external script successfully — **and
      there were permissioning surprises, which is the useful half.**
      `scripts/hire_agent.py` (`make hire`) mined `approve`, `createJob` and
      `setBudget` on chapel; job 746 reads back with our client, provider,
      evaluator and budget. Seven revert selectors came out of it, none in any
      ABI, each isolated by varying one argument at a time and three then matched
      to a name: the **hook is mandatory** (`address(0)` reverts
      `HookRequired()`, and only the EvaluatorRouter is accepted, against an EIP
      that calls it an optional extension), `expiredAt` is an absolute timestamp
      with a ceiling, and the evaluator may not be zero. `fund` has since mined on **BSC
      mainnet** — job 56681, 0.1 of the payment token in, and `claimRefund`
      brought it back out. This entry said the token was owner-minted and the
      signer held none; it trades on PancakeSwap, and
      `scripts/buy_payment_token.py` is the code that closed it. What is still
      open is release: `submit` needs an expiry beyond the seven-day dispute
      window and the run asked for twelve hours. See **P-28** and
      `registry/hire.py`.
- [ ] Agent Studio CLI hello-world deployed. More than a hello-world exists and
      the box is still unticked, which is the honest state. The scaffold at
      `studio/misquoterouter` is deployed, `bag erc8004 register` minted it
      identity **2102** on chapel, and its ERC-8183 `negotiate` returns an
      EIP-191-signed quote whose signature recovers to that identity's owner and
      whose verifying contract is `erc8183.JOB_ESCROW[97]` — checked by
      `make studio-negotiate` and rendered on `/studio`. The router *path* is
      answered by `agents/router/policy.py`; only the deployment is open. The blocker is not
      what was recorded here for weeks: `studio.bnbchain.org` is dead and the
      package's declared repository 404s, but `@bnbagent/studio-cli` installs
      from npm and `bag` offers `erc8004`, `erc8183` and `x402` subcommands —
      probed and dated in `vetting/identity/studio-probe.json`. What is open is a
      deployment through `bag deploy` itself, which takes bnb, aws or azure. The
      custody objection recorded here applied to one flag combination and not to
      the tool — `--destination self` and `--wallet-kind turnkey` move no signing
      key at all. The agent runs at `misquote-agent.onrender.com` with ERC-8004
      identity 2102 registered by the CLI; what has not happened is the CLI
      deploying it.
- [ ] Mission Control micropayment discrepancy (49 vs 75) resolved; correct
      number recorded in `docs/REQUIREMENTS_MATRIX.md` before any card renders.

## 9. Environment

**[`.env.example`](.env.example) is the list.** Copy it to `.env` and fill in
what you need; every variable in it is one the code reads, and every variable
the code reads is in it — [`tests/test_env_template.py`](tests/test_env_template.py)
walks the AST for `os.environ` accesses and fails if the two sets differ.

This section used to carry its own copy of that list, and the copy was wrong in
the way an unguarded copy always goes wrong: `WALLET_KEYSTORE_PATH` and
`ALTANA_*` were read by nothing, and `DB_PATH=./misquote.db` named a path that
is not the default (`data/misquote.db`). A second list is a second thing to keep
true, and this one was not being kept.

Two that are worth knowing before you start:

- **`MISQUOTE_DRY_RUN`** defaults to on. Every chain write prints what it would
  send and sends nothing until `MISQUOTE_DRY_RUN=0` is set on that one command.
  It does not belong in `.env`.
- **`MISQUOTE_API_BASE`** is where the live API is. Unset, `make artifacts`
  keeps whatever base is already published rather than blanking it — see the
  `api-config` target for why that is not the obvious behaviour.

Run: `make artifacts` (every JSON the site reads) · `make replay-tests` ·
`make web` · `make status` — Makefile targets are part of Phase 1 deliverables.

`make warden CHAIN=56` runs the agent against BSC mainnet. It **records and
cannot spend**: `--broadcast` is refused on chain 56 in
`agents/warden/__main__.py`, in code rather than by convention, so the 24-hour
burn-in behind the `/status` gate is a day of reading and deciding with signing
impossible.

Two corrections live in that sentence. This paragraph used to say the command
had never worked, because `misquote.agents.warden` had no `__main__.py` — it has
one, and `tests/web/test_ledger.py` asserts every `python -m` target in the
Makefile imports and is executable. And the command itself was published
everywhere as `make warden ENV=testnet`: `ENV` was a Makefile variable
referenced by nothing, while the target passes `--chain $(CHAIN)`, which
defaults to 56. It said testnet and ran mainnet.

What remains not built is **signing** on mainnet, which is a different claim and
is recorded as such in `packages/misquote/tearsheet/ledger.py` and rendered on
[`/status`](apps/web/src/app/status/page.tsx).

## 10. The pitch (for the repo header and the demo)

> Agent marketplaces run on misquotes — stars, counts, claims nobody can check.
> **Misquote** replays every agent's policy on your actual positions and quotes
> you an honest range instead — then lets you hire with visible caps and
> one-click revoke, and proves the advantage in a tearsheet generated from
> chain state. The only thing misquoted here is the name. Audit me.

Demo opener (use verbatim): "It's called Misquote because that's what every
other marketplace does to you."