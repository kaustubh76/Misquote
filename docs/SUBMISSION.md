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
| Live API | https://misquote-api.onrender.com — free plan, **sleeps when idle**, first request can take ~50s |
| Repository | this one; `docs/FOR_JUDGES.md` is the entry point |
| Twenty-second path | `/demo` → step 2 arrives with the answer on screen |

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
| Four ERC-8004 identities | chapel ids 1927–1930, `vetting/identity/97.json` |

## Track deliverables

- [x] **BNB main track** — four agent categories at equal depth, each with a
      card built from a replay over 30 days of chain history, each runnable as a
      live process (`make warden|grid|sentinel|router`) and each with a journal.
- [x] **TermiX** — Agent Advantage Report, four tasks on a chain tape, all
      quotable, distinct baselines. `docs/AGENT_ADVANTAGE.md`. **The agent loses
      three of four**, which is the report doing its job.
- [x] **PancakeSwap** — the venue divergence readings and the nine-check pool
      badges. `/venue`, `/vetting`.
- [~] **Altana** — expiry and revoke proven on chain; the allowlist and spend
      cap are not, and the ledger says so.

## Not done, and disclosed

The five entries on the not-built ledger, rendered at `/status` and listed in
`docs/FOR_JUDGES.md` under *What is NOT done*. The two that matter most:

- **Releasing an escrowed job on mainnet.** `fund` and `claimRefund` are mined;
  `submit`/`settle` need an expiry beyond the 7-day dispute window, so doing it
  on chain locks the budget for over a week.
- **Agent Studio deployment.** The CLI installs and was probed
  (`vetting/identity/studio-probe.json`); deploying hands a wallet key to the
  vendor, which is a custody decision nobody has made.

## Open before submission

- [ ] **Demo video.** Not started. The one thing on this list with no artifact
      behind it at all.
- [ ] **`make go-no-go` re-run in full.** The published verdict is from 31 Aug,
      `--fast`, non-mainnet — six of fifteen gates skipped.
- [ ] **D1 checklist reconciled.** `Readme.md` §8 and
      `docs/REQUIREMENTS_MATRIX.md` disagree on two of five rows.
- [ ] **Studio agent on Render.** Declared in `render.yaml` beside the API, and
      the blueprint's own build and start commands were rehearsed against a
      clean `git archive` of what is published — install, build and serve all
      pass. One step remains: uploading the keystore as a Render secret file,
      with `WALLET_PASSWORD` in the dashboard. See `docs/DEPLOY_AWS.md`.
- [ ] **`bag deploy` itself.** Down from five blockers to two. Running the agent
      is not the same claim as deploying it through the vendor's CLI, and only
      the second is the native-citizenship proof.
- [ ] **WalletConnect project id.** `NEXT_PUBLIC_WC_PROJECT_ID` is wired and
      unset; until it is set, only browser-extension wallets can connect and no
      phone can.
