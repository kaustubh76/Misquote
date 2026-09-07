# The BNB Agent Studio half, and the UX built for it

*Written 7 Sep 2026, two days before submission. Every figure here is read from
`apps/web/public/artifacts/studio.json` or from a record under
`vetting/identity/`, and every one of them is regenerable by a named command.*

---

## 1. The finding this report exists for

The Agent Studio work was in the worst state a piece of work can be in: **more
built than the project claimed, and invisible to anyone looking.**

`packages/misquote/tearsheet/ledger.py` published, and `/status` rendered:

> The ERC-8183 interface and x402 self-funding do not [exist], and `bag deploy`
> has not run.

The first clause was false when it was written down and had been false for days.
`studio/misquoterouter/app/agent/src/` is **2,208 lines of tracked TypeScript**
implementing an ERC-8183 seller on the vendor's own SDK — `sellerCore.ts` is 507
of them, `signing.ts` another 300 — and the agent has been serving both skills at
`misquote-agent.onrender.com` the whole time.

Meanwhile the words "Agent Studio" appeared in the UI in exactly two places: one
inline link in the hero pointing at a raw `agent-card.json`, and a ledger card
explaining what had *not* been built. A judge assessing the track this project's
main entry answers had nowhere to land.

### Why the guard did not catch it

This is the more useful half of the finding. `tests/web/test_ledger.py::
test_ledger_entries_still_describe_reality` exists precisely to fail when a
ledger entry stops being true. It parses the entry's `evidence` string and checks
the claim in it.

That entry's evidence was:

```
packages/misquote/agents/router/ — no studio.py
```

Which is **still true**, and is about something else entirely — Router's own
module, not the scaffold's interfaces. The guard was verifying a fact nobody
disputed while the sentence beside it went stale. A check pointed one level away
from its own subject reports green forever.

The entry is now two, and both point at what would actually change:

| Entry | Evidence |
|---|---|
| Agent Studio deployment | `vetting/identity/ — no studio-deploy.json` |
| The Studio agent's x402 self-funding | `studio/…/app/agent/src/ — no x402Buyer.ts` |

`x402Buyer.ts` is the filename the scaffold's **own comment** in `unifiedMain.ts`
names for that path. Splitting was the point rather than tidiness: one piece of
evidence covering three claims let two of them come true silently, which is what
happened.

---

## 2. What is actually built

### 2.1 The seller agent

| | |
|---|---|
| Location | `studio/misquoterouter/` — 23 tracked files, 2,208 lines of agent source |
| Scaffolded by | `@bnbagent/studio-cli` 0.0.13 (`bag init`), 39 versions published |
| Runtime | AgentCore; A2A protocol 0.3.0, JSON-RPC transport |
| Live at | `https://misquote-agent.onrender.com` |
| `bag doctor` | 14 pass · 7 warn · **0 fail** |

Two skills, both fixed code and neither reachable by the model:

- **`negotiate`** — rule-based price clamp, then an EIP-191 signature. The price
  is fixed in `studio.toml` and clamped to `[min, max]` before signing. *The
  model never prices.*
- **`notify_funded`** — verifies the funded job on chain, ACKs at once, then runs
  the LLM work and `submit` in the background. The buyer reads the deliverable
  back from the chain.

All signing lives in `signing.ts` and is never exposed as an LLM-callable tool.
That is a vendor-imposed invariant in `AGENTS.md` and the code holds it.

### 2.2 The identity

`bag erc8004 register` — the vendor's CLI, not `scripts/register_identity.py` —
minted **ERC-8004 identity 2102** on chapel (chain 97), owned by
`0xdEaF6a18…3e29`.

Read back independently rather than taken on the CLI's word: `ownerOf(2102)` is
the scaffold wallet and the `tokenURI` is a `data:` URI whose `services[]`
endpoint resolves to the running agent. The CLI's own `.studio/audit-log.jsonl`
carries the submitted/confirmed pair, and that log is the one artifact in this
story written by the vendor's tool rather than by us.

This is a **fifth** identity, distinct from the four `register_identity.py`
minted on mainnet (323262, 323332-4, 331592). `/registry` says so rather than
folding it into that table, which would have been the neatest available lie.

### 2.3 The commerce configuration

From `studio.toml`, quoted rather than summarised:

| | |
|---|---|
| Price | 0.1 `$U`, clamped to `[0, 0.2]` |
| Currency | `0xc70B8741…5565` |
| Quote TTL | 900s |
| Evaluator | `uma_oov3` |
| Public faces | `["A2A"]` — no x402/MPP sibling route |
| Auto-settle | off |

---

## 3. The check that makes it worth anything

`make studio-negotiate` calls the live agent and checks what comes back against
constants this repository derived independently.

**Verdict: PASS, 4 of 4**, recorded in `vetting/identity/studio-negotiation.json`.

| Check | What it compares |
|---|---|
| The signer holds the identity's key | `provider_sig` recovers to `0xdEaF6a18…3e29`, the wallet owning identity 2102 |
| The signature binds to the kernel we verified | `verifyingContract` is `erc8183.JOB_ESCROW[97]` |
| The quote is denominated in the kernel's own token | `currency` is `erc8183.PAYMENT_TOKEN[97]` |
| The chain matches the registered identity | signed for chain 97 |

**Why three of these are not our own word.** `JOB_ESCROW[97]` and
`PAYMENT_TOKEN[97]` were recovered by `erc8183_abi.py` searching **21,060
candidate signatures** against deployed bytecode, weeks before this scaffold
existed. The vendor's SDK and that archaeology arriving at the same values is
corroboration between two paths that never consulted each other. Either alone is
a claim.

One detail worth stating because it is documented nowhere: the agent signs the
negotiation hash **as a hex string**, not as 32 bytes. Recovering the other
encoding returns a plausible-looking wrong address. The record and the page both
say which encoding answered.

---

## 4. The UX, and the decisions in it

### 4.1 Shape

`/studio`, in the nav's `product` band after Registry. Five sections behind a
`SectionRail`:

1. **Ask it for a quote** — the interaction, first
2. **The agent itself** — card, skills, commerce config
3. **An identity the vendor's CLI minted** — provenance and the audit log
4. **The CLI, and what it turned out to offer**
5. **What this does not prove**

### 4.2 Why the button is at the top

It is the only thing on the page a reader can disprove in ten seconds, and it is
not our claim. Press it and a *different* agent — deployed separately, holding a
key this site cannot sign with — returns a quote it signed. The page shows the
signature beside the address it recovers to, and the identity that address owns,
one block apart so a reader does not have to hold two values in their head.

A marketplace arguing that other marketplaces cannot be checked should lead with
the thing on it that checks hardest.

### 4.3 The proxy, which is not a design choice

The agent sends **no `Access-Control-Allow-Origin`** on either its card or its
JSON-RPC root. Verified by preflight before any code was written. A browser
cannot call it: the request goes out, the agent answers, and the browser discards
the reply before any handler sees it.

So `POST`-shaped work happens through `GET /studio/negotiate` in
`packages/misquote/api/studio.py`. It is a thin forwarder — it does not
interpret, cache, or judge the quote — and it **refuses to expose
`notify_funded`**, which spends the agent's gas and LLM credit and must not be
triggerable by a stranger pressing a button.

### 4.4 Live, with a recorded fallback — and the bug that found

The page renders a recorded envelope from the artifact until the button is
pressed, then swaps in the live one. `AnsweredBy` labels which is on screen:
*answered live* or *recorded earlier*. Never both at once.

Building this surfaced a real defect. `api/studio.py` originally returned **502**
for a seller that answers without a signed envelope. But `lib/api.ts` folds
**every 5xx** into the artifact fallback and treats only a non-5xx `detail` body
as terminal — so the recorded envelope would have rendered as though the live
call had merely been slow. That is precisely the substitution this project is
named after, and it would have shipped.

The two codes are now chosen against that behaviour:

| Condition | Status | Effect |
|---|---|---|
| Agent asleep (host scales to zero) | **503** | Falls back to the recording, labelled as one — the right answer to "it is asleep" |
| Agent answered, not with an envelope | **409** | Terminal. No substitution. The reader is told the seller disagreed |

### 4.5 Discovery

The hero's bare link to an `agent-card.json` now points at `/studio` and says
what a reader gets by following it. `/registry`'s "our own agents" section names
the fifth identity and links out.

### 4.6 What the guards had to say

Four of them, each correct:

- **`900` collided** with `maxWidth: 900` in the Open Graph card. That file is
  excluded from the hardcoded-number scan rather than 900 added to
  `UNDISTINCTIVE` — the set is global, 900 is a plausible figure for a page to
  smuggle, and one file that renders no data is the smaller hole.
- **Four fields carry inline markdown.** Three go through `Prose`, as the
  ledger's do. `agent.skills[].description` deliberately does **not**: it is read
  live off an agent card at call time, so `Prose` would let whatever that
  endpoint returns place a link on our page. Same rule as the third-party
  listings.
- **The route needed a screenshot and a no-JS needle.** The needle is
  `bag deploy` — the sentence separating an agent we host from one the CLI
  deployed, which is the admission a rewrite would soften.
- **`Nav.test.tsx` and `check-pages.mjs`** both keep independent route lists and
  both had to be told.

### 4.7 Measured

- `make web-check`: `/studio` clean in both themes at 1280 and 390, **zero
  horizontal overflow**, no console errors, no dead links, 19 distinct titles.
- **7,498 characters render with JavaScript disabled** — the entire standing
  record, including the recorded envelope and the not-done list. Only the live
  button needs JS.
- 6 vitest cases covering the recorded floor, the live swap, the refusal path,
  the signer/owner identity, the not-done list, and the never-called refusal.

---

## 5. What this does not prove

Carried in the ledger's shape, because the honest half is the half a judge
checks.

| | |
|---|---|
| **`bag deploy` itself** | The agent runs on Render, on infrastructure we operate. `bag deploy` takes bnb, aws or azure and none has been used. Running the agent is not the claim; the CLI deploying it is. Five CRITICAL items in `docs/DEPLOY_AWS.md`. |
| **x402 self-funding** | `protocols = ["A2A"]`, one face published. `x402Buyer.ts` has never been generated. The Pieverse LLM credit does top itself up, which is a different mechanism. |
| **A delivery driven through this agent** | `negotiate` has been called and checked four ways. `notify_funded` needs a job funded against the agent's own quote, and the scaffold wallet holds no payment token on chapel. The escrow half is proven elsewhere in this repository — by our own signer, not by this agent. |

---

## 6. Commands

```
make studio-negotiate   # call the live agent, check its signature four ways
make studio             # republish the record as the site's artifact (offline)
make probe-studio       # re-read what the CLI offers (installs, deploys nothing)
```

`make artifacts` runs `studio` in the chain. Only `studio-negotiate` needs a
network, and it spends nothing.

---

## 7. Files

| Path | Role |
|---|---|
| `scripts/studio_negotiate.py` | Calls the agent, recovers the signer, cross-checks against `erc8183.py` |
| `scripts/studio_report.py` | Offline republisher → `artifacts/studio.json` |
| `packages/misquote/api/studio.py` | The CORS proxy, and the two status codes |
| `apps/web/src/app/studio/{page,view}.tsx` | The route |
| `apps/web/src/app/studio/view.test.tsx` | 6 cases |
| `vetting/identity/studio-negotiation.json` | The dated reading |
| `vetting/identity/studio-local-run.json` | The deployment and the registration |
| `vetting/identity/studio-probe.json` | The CLI's capability surface, dated |
