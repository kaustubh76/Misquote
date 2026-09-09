# Submission checklist

Freeze **5 Sep 2026**, submit **9 Sep 2026**. This file exists because nothing
in the repository listed what a submission form actually asks for — the D1
checklist tracks build decisions, `make go-no-go` gates a mainnet broadcast, and
the not-built ledger records gaps. None of them is a packing list, so the things
a form wants were spread across three documents and a drawing.

Kept short and kept accurate. An item is ticked only when the thing exists.

## What a judge is given

| | |
|---|---|
| Live site | https://misquote.vercel.app — static export, Vercel, built from `main` |
| Guided run, no wallet | https://misquote.vercel.app/demo — one click to a P25–P75 range |
| **The PancakeSwap deliverable** | https://misquote.vercel.app/simulate — pick a pool, a range width and an amount, and see what that position would have earned on swaps that already happened. 1,400 replayed positions; no wallet, no backend, nothing signed |
| Live API | https://misquote-api.onrender.com — free plan, **sleeps when idle**, first request can take ~50s |
| Live agent | https://misquote-agent.onrender.com — the BNB Agent Studio seller agent, A2A card at `/.well-known/agent-card.json` |
| Repository | this one; `docs/FOR_JUDGES.md` is the entry point |
| Twenty-second path | `/demo` → step 2 arrives with the answer on screen |
| Twenty-second path, PancakeSwap | `/simulate` → press **2.00** and watch the rate fall, then switch to the 0.25% pool and watch it refuse the size |

## Deployed addresses

**BNB Smart Chain (56)**

| Role | Address |
|---|---|
| ERC-8004 identity registry | `0x8004A169FB4a3325136EB29fA0ceB6D2e539a432` |
| ERC-8183 kernel | `0xEa4DAa3100A767e86FDed867729ae7446476EBA6` |
| ERC-8183 EvaluatorRouter | `0x51895229E12F9876011789B04f8698af06cCD6DA` |
| ERC-8183 OptimisticPolicy | `0x9C01845705b3078Aa2e8cfF7520a6376FD766dE5` |
| Payment token | `0xcE24439F2D9C6a2289F741120FE202248B666666` |
| Altana keystore | `0x6572427ED530BadcF7375Cf9A4709D8d2b0E7E0a` |

**Chapel testnet (97)** — identity registry
`0x8004A818BFB912233c491871b3d84c89A494BD9e`, keystore
`0x6b8361C29d05D498b1a12B54A37310f94171E94A`. Our four agents hold ids
**1927–1930**.

None of the ERC-8183 or ERC-8004 contracts are ours. They are third-party
deployments this project reads and transacts against, and every address above
was verified on chain before it was written down — see `vetting/addresses/`.

## Transactions a judge can open

| What | Where |
|---|---|
| Escrow funded, BSC mainnet | job 56681, `fund` `0xbc225eb7…a692` |
| Escrow refunded, BSC mainnet | `claimRefund` `0xfb77c53e…7c35`, status 1 → 5, 0.1 token returned |
| Session key granted and revoked | three mined chapel transactions, `vetting/identity/session-keys-97.json` |
| ERC-8004 identities, BSC **mainnet** | ids 323262, 323332–323334, 331592, `vetting/identity/56.json` — the record `go_no_go` reads, because it is the stronger claim and the one TermiX's explorer indexes |
| ERC-8004 identities, chapel | ids 1927–1930, `vetting/identity/97.json` |
| Escrow submitted, BSC mainnet | job 56718, `submit` — `settle` opens 13 Sep after the dispute window |

**One wallet was both client and provider on both jobs.** These transactions
prove the escrow mechanics — money in, money back, a delivery recorded — and they
hire nobody. `go_no_go` has said so in its detail line throughout; this table
presented them without the caveat, which is the claim arriving before the
qualifier rather than with it.

## Track deliverables

- [x] **BNB main track** — four agent categories at equal depth, each with a
      card built from a replay over 30 days of chain history, each runnable as a
      live process (`make warden|grid|sentinel|router`) and each with a journal.
- [x] **TermiX** — Agent Advantage Report, **six** tasks on a chain tape, five
      of them quotable and one withheld, distinct baselines.
      `docs/AGENT_ADVANTAGE.md`. **The agent wins two with non-overlapping bands,
      loses one, and ties two** below the materiality floor — which is the report
      doing its job. Equities is withheld rather than estimated: the only
      tokenized-equity pool on BNB Chain with liquidity yields four replay
      windows where A5 requires twenty. The report also refuses an overall
      verdict on five observations against its own floor of thirty. This line
      has now undercounted the task list twice — four, then five — because it is
      typed and the report is generated; `go_no_go`'s `agent advantage report`
      gate reads the artifact, and this sentence should be read as commentary on
      it rather than as the count.
- [x] **TermiX, the other half** — hiring is a thing this site does, not a thing
      it describes. `/activate` escrows a budget against a job through the
      ERC-8183 kernel from the reader's own wallet, one call at a time, with the
      agent as provider. `check_escrow_flow` gates it: funded on mainnet,
      reclaimed, settled — amber today on the third.
- [x] **PancakeSwap** — the venue divergence readings and the nine-check pool
      badges. `/venue`, `/vetting`. The findings are written up for filing
      upstream in `docs/PANCAKESWAP_FINDINGS.md` — six ways v3 differs from
      Uniswap's, each with what it costs to get wrong, one of them a bug we
      shipped ourselves.
- [~] **Altana** — expiry and revoke proven on chain; the allowlist and spend
      cap are not, and the ledger says so.

## Not done, and disclosed

The six entries on the not-built ledger, rendered at `/status` and listed in
`docs/FOR_JUDGES.md` under *What is NOT done*. The two that matter most:

- **Releasing an escrowed job on mainnet.** `fund` and `claimRefund` are mined;
  `submit`/`settle` need an expiry beyond the 7-day dispute window, so doing it
  on chain locks the budget for over a week.
- **Agent Studio deployment.** The agent runs at
  `misquote-agent.onrender.com` with ERC-8004 identity 2102 registered by the
  CLI itself. What has not happened is `bag deploy`, which takes bnb, aws or
  azure. The custody objection once recorded here applied to one flag
  combination, not to the tool.

## One thing due after submission

**Settle job 56718 on or after 13 Sep 2026, 08:01 UTC.** `submit` mined on
mainnet; `settle` reverts `NotDecided()` until the OptimisticPolicy's seven-day
dispute window has run. Expiry is 14 Sep 08:00 UTC, so there is a 24-hour
window, and judging runs to 23 Sep.

```
set -a; . ./.env; set +a
MISQUOTE_DRY_RUN=0 \
MISQUOTE_SIGNER_ADDRESS=0x0c501EE1924bfb91a028DB4BcD68f4861B0Ff6eE \
BSC_RPC_URL=https://bsc-dataseed.bnbchain.org \
  uv run python scripts/hire_mainnet.py --settle 56718
```

If it is missed, `claimRefund` recovers the 0.1 token after **14 Sep 08:00
UTC**:

```
MISQUOTE_DRY_RUN=0 uv run python scripts/claim_refund.py --job 56718
```

That used to read "the same path job 56681 took, already proven", which was a
weaker claim than it looked. 56681 was funded and never submitted; 56718 has
been *delivered into*, and whether this deployment lets a client reclaim a
budget after a delivery nobody decided on is a different question about the
contract. It is rehearsed rather than assumed now —
`vetting/identity/refund-fork-56718.json`, a fork of mainnet at the real block
with only the clock moved: the claim is **refused** before expiry, and after it
the job goes 2 → 5 and the full 0.1 comes back.


## Keeping the marketplace evidence current during judging

Judging runs to **23 Sep**, and the TermiX block on `/registry` is counters read
off somebody else's server. Nothing expires on our side — the site is a static
export — but the reading ages, so the page now prints **when** it was taken and
computes "N ago" against the reader's own clock rather than publishing an age
that freezes at build time.

To re-date it, at any point, without committing anything:

```
uv run python scripts/termix_activity.py --out    # re-reads, sends nothing
make registry                                     # republishes the block
```

The bare script with no action flag is read-only by construction — `--save`,
`--quote`, `--brief` and `--buy` each have their own flag precisely so that
none of the three that commit money can be reached by accident.

Two things a judge will find unfinished, both deliberate and both stated on the
page: `activeOrders` is 0 because it counts orders a **provider has accepted**
and ours is waiting on the seller, and the sponsored bounty is `DRAFT` because
funding it is a spend nobody has authorised.

## Open before submission

- [ ] **Demo video.** Not recorded. The script is written —
      `docs/DEMO_SCRIPT.md` — shot by shot, with verbatim narration timed to
      2:30 and every URL live. It needs a screen recording and a voice.
- [~] **`make go-no-go` re-run in full.** The published verdict in
      `artifacts/status.json` is a non-`--fast` run with nothing skipped: 18
      pass, 0 fail, 4 unverified, **NOT YET**. It is *not* a `--mainnet` run —
      `status.json` says `"mainnet": false`, and `signer` and `position cap`
      both report "not checked — this run is not --mainnet". This entry was
      ticked and claimed mainnet for as long as it has existed, which is the
      same defect it was written to warn about, one level up: an item that
      describes its own verdict wrongly is worse than one left open.
- [x] **D1 checklist reconciled.** The ERC-8183 row disagreed because the matrix
      recorded a blocker one level too high — "no job can be read back", when the
      accessors it named were simply the wrong names. Both now say resolved, with
      `settle` as the single open call. The Agent Studio row is open in both.
- [x] **Studio agent on Render.** Live at https://misquote-agent.onrender.com,
      serving its A2A card with its own public address in it.
- [ ] **`bag deploy` itself.** Down from five blockers to two. Running the agent
      is not the same claim as deploying it through the vendor's CLI, and only
      the second is the native-citizenship proof.
- [ ] **WalletConnect project id.** `NEXT_PUBLIC_WC_PROJECT_ID` is wired and
      unset; until it is set, only browser-extension wallets can connect and no
      phone can.
