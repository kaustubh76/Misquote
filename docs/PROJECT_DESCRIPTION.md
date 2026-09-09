# Misquote — project description

Paste-ready text for a submission form. Three lengths; every figure traces to a
published artifact under `apps/web/public/artifacts/`, named in brackets where a
reader might want to check it.

---

## One line (~40 words)

Misquote is an agent marketplace for BNB Chain where a listing card is not a star
rating but a replay of that agent's own policy over real PancakeSwap v3 history —
quoted as a P25–P75 range, with the assumption sheet one click away.

---

## Short version (~150 words)

Every other agent marketplace misquotes you: star ratings, user counts, and
self-reported claims, none of them checkable. Misquote replaces the rating with
evidence. Each of its four agents is replayed over 252,923 real swaps read
straight from BSC, and its listing card carries the resulting P25–P75 range, the
costs, and the assumptions that produced it. The same engine runs each task a
second time with the agent switched off, so "does hiring beat doing it yourself"
is a measured number rather than a claim — and it publishes the losses: one of
the four agents loses its task by 68.55 percentage points, and the card says so.

Four agents are registered as ERC-8004 identities on BSC mainnet, a budget has
been escrowed and reclaimed through an ERC-8183 kernel with real money, and
session keys have been granted and revoked on chain. What has not been done is
listed on the site, not buried.

---

## Full description (~900 words)

**The problem.** Agent marketplaces rank agents the way app stores rank apps —
star ratings, install counts, and descriptions the agent's own author wrote. None
of that is checkable, and none of it answers the only question a buyer actually
has: if I hire this thing, am I better off than if I did the job myself? Misquote
is named after that defect. Every other marketplace misquotes you; this one shows
its math, including the parts that make it look worse.

**The core idea.** A listing card on Misquote is not a rating. It is a replay of
that agent's own decision policy over real chain history, and the headline is
always a **P25–P75 range** rather than a point estimate — "20.70% to 36.15%",
never "30%". One rule is enforced in code throughout: every displayed number must
trace to a chain query or to a published assumption, or it does not render at
all. The assumption sheet is one click from every figure.

**What you can actually do with it.** The site is a product, not a paper. `/demo`
walks a visitor to a real P25–P75 range in four steps with no wallet, no API key
and nothing funded. `/simulate` is the PancakeSwap deliverable: pick a pool, a
range width and a position size, and see what that position would have earned on
swaps that already happened — 1,400 pre-replayed positions behind it, and it
**refuses** sizes past 1% of pool depth rather than quoting a number it cannot
support. `/quote` takes a wallet address and replays each agent's policy against
that wallet's own position history. `/activate` connects a wallet and escrows a
budget against a job through the ERC-8183 kernel. `/status` renders the readiness
gate — a checklist that executes rather than one that is read.

**The data.** There is no third-party data API and no API key anywhere in the
pipeline. Pool events are read directly from BSC with `eth_getLogs` into SQLite:
252,923 swaps across 725.7 hours of the PancakeSwap v3 WBNB/USDT 0.05% pool, with
zero gaps and zero unread blocks in the covered range [`build.json`]. The schema
records which block ranges were actually *read*, separately from which contained
events — because a quiet window and an unfetched window both hold zero swaps, and
an interrupted backfill once passed a readiness check by exactly that confusion.

**The four agents**, one engine, four genuinely different policies:

- **Warden** (rebalancing) — Avellaneda–Stoikov reservation pricing and optimal
  spread mapped onto v3 tick ranges, with four independent gates. Quotes
  **20.70%–36.15%** annualised over 725.7h and 522,520 samples, in range 93.9% of
  the time. Beats the do-it-yourself baseline on **60 of 60** windows, by 17.21
  percentage points, with bands that do not overlap.
- **Grid** (market making) — a deliberately simple fixed ladder with three
  parameters, which exists to prove the engine is not a Warden harness. Quotes
  19.50%–31.90%; ahead by 12.71pp.
- **Sentinel** (health) — threshold de-risking. It **loses** its task by 68.55pp,
  and the card explains why with a measurement rather than an excuse: its pull
  threshold fires on 41.94% of real samples, so it spends its entire daily budget
  on pull/re-enter cycles and gas becomes most of the cost. The parameter was
  deliberately not retuned, because the spec governing it is frozen.
- **Router** (yield) — an optimal-switching boundary across Venus lending
  markets, reading a different tape entirely. Its edge came in at 0.01pp below
  the 0.10pp materiality floor, so the report calls it indistinguishable instead
  of a win.

**Proving the agent is worth hiring.** The Agent Advantage Report runs six tasks
both ways. Crucially, the baseline is not a separately written program that could
be quietly weakened — it is the *same* replay driver with `policy=` swapped, over
the same tape, cost model and accountant, and a test asserts it. Result: the
agent is ahead on 2, behind on 1, indistinguishable on 2, and one task is
**withheld** because the only tokenized-equity pool on BNB Chain with any
liquidity yields 4 replay windows where the methodology requires 20. The report
also refuses an overall verdict on 5 observations when its own floor is 30
[`advantage.json`].

**Verification.** The claims that matter are tests, not prose. A bitwise
look-ahead test runs the replay twice, replacing every event after a cut with
seeded noise, and compares decision sequences with every float packed to its
exact bits — plus a negative control proving that tampering *does* change
decisions. A second test runs the live agent driver, its own file and own loop,
over a tape-backed source and demands byte-identical decisions to the replay.
The tick math is checked against **19,546 vectors** recorded from real v3
Solidity at exact integer equality with no tolerance. Position math is compared
to the real contracts on a BSC fork to **one wei**. One finding from that work is
load-bearing: PancakeSwap takes a 34% protocol cut that Uniswap does not, so
reconstructing fees the obvious way overstates LP earnings by 1.515× — straight
onto the headline number.

**On chain.** Four agents hold ERC-8004 identities on BSC mainnet (323262,
323332–323334, plus a re-mint at 331592) and on testnet. A budget was escrowed
through an ERC-8183 kernel on mainnet with real money and reclaimed — job 56681
funded, `claimRefund` mined — and job 56718 has been funded and delivered into,
with `settle` unlocking after a seven-day dispute window. **The honest caveat: one
wallet was both client and provider, so this proves the escrow mechanics and
hires nobody.** Session keys are granted and revoked on chain, and of the four
caps advertised, **two are actually enforced** by that deployment — expiry and
one-transaction revoke; the allowlist and spend cap need a validator module that
no grant on that keystore carries. The site says so on the activation page.

**Stack.** Python 3.12 replay engine and indexer; Next.js 15 exported statically
to Vercel, so the whole site renders with every backend down; FastAPI plus a
queue worker on Render; a Node 22 A2A seller agent that returns wallet-signed
ERC-8183 quotes. 2,702 tests, of which 53 need a live chain or a fork.

**What is not done** is published as a ledger of six entries on the site itself,
and the readiness gate currently reads 18 pass, 0 fail, 4 unverified — verdict
**NOT YET**. Nothing has traded with real money; the flagship agent refuses to
sign on mainnet in code, not by convention. Under-claiming is the point: a
marketplace that cannot show you its own failures is the thing this project was
built to argue against.
