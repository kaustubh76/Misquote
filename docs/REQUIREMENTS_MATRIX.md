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

## G — gaps in the frozen spec (values proposed and published)

The spec leaves these unspecified. Each proposed value is published in `ASSUMPTIONS.md` and rendered
in the UI, so a reader can disagree with the number without having to reverse-engineer it.

| ID | Symbol | Where | Value | Rationale |
|---|---|---|---|---|
| **G-1** | `M` | §3.4, trailing swap count for the imbalance z-score | **50** | Long enough for a stable z-score on a busy pool, short enough to react within minutes. |
| **G-2** | `arb_cost_bps` | §3.4, toxicity threshold | **5 bps** | BSC gas plus a CEX taker fee, the round-trip cost an arbitrageur must clear. |
| **G-3** | `N` | §4.2, InRange% floor for the bonded instrument | **70%** | Binary and chain-checkable, per §4.2's requirement that the floor need no counterfactual. |

---

## Readme §8 · D1 checklist

| Item | Status |
|---|---|
| Prize split verified in BNB Discord | **OPEN** |
| ERC-8004 registry population counted on BscScan (decision rule: <~15 real agents → demote third-party auto-cards to a plain "registry view") | **OPEN** |
| ERC-8183 hire call invoked from an external script | **OPEN** |
| Agent Studio CLI hello-world deployed | **OPEN** |
| Mission Control micropayment discrepancy (49 vs 75) | **RESOLVED — use 75 (242 logged)** |

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
