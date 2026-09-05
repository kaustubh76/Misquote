# Demo video — shot list and narration

**Target: 2 min 30 s.** Screen recording plus voiceover. Every URL below is
live; nothing needs a wallet, a key, or a running backend. Read the narration
verbatim if you like — it is timed to the clicks.

Record at 1280×800 or wider. Dark theme reads better on projectors. Have one
browser tab open, cache warm — visit each URL once before recording so nothing
is waiting on a cold Render instance.

---

## Shot 1 · The name — 0:00–0:18

**Screen:** `https://misquote.vercel.app/` — the landing page, top of fold.

> "It's called Misquote because that's what every other marketplace does to
> you. Stars, counts, claims nobody can check.
>
> This one replays an agent's actual policy over thirty days of PancakeSwap
> history and quotes you a range instead. Every number on this site traces to
> chain state or to a published assumption — and where the evidence is thin, it
> says nothing at all."

*Do not scroll yet. Let the headline hold.*

## Shot 2 · It runs, with no wallet — 0:18–0:55

**Screen:** click **"Watch it run, no wallet"** → `/demo`, then click step 2.
The quote page arrives with the answer already on screen.

> "You don't need a wallet to check that. This is a recorded run against the
> real tape — the page arrives with the answer already computed.
>
> That's a P25 to P75 band, not a single number, because a single number would
> be a claim about a future nobody has. The banner says 'simulated' because it
> is: under this link no request is issued at all."

*Point the cursor at the band and at the simulation banner.*

## Shot 3 · The honest part — 0:55–1:30

**Screen:** `/advantage`.

> "Here's the question the whole thing turns on: does hiring an agent beat
> doing it yourself?
>
> Five tasks, same replay driver, same tape, same cost model on both sides —
> the only difference is the policy. Two of them the agent wins, with bands
> that don't overlap. One it loses badly, and we say so and explain why. Two are
> indistinguishable, and we call them that instead of rounding them into a win.
>
> The report refuses to declare an overall winner: five observations, and it
> won't call a rate on fewer than thirty."

*Scroll slowly through the verdict column. Do not skip the loss.*

## Shot 4 · Real money, real chain — 1:30–2:00

**Screen:** landing page → **"0.1 of a token escrowed on BSC mainnet and
reclaimed"** → `/registry#escrow`.

> "This isn't only replays. We escrowed a tenth of a token into a live ERC-8183
> job on BNB Smart Chain mainnet, and reclaimed it — both mined, both linked to
> BscScan here.
>
> Releasing it is what didn't happen. Submit needs an expiry beyond the
> seven-day dispute window and we asked for twelve hours. We measured that
> boundary across eight fork runs before we found the name of the error — and
> then found the vendor's own SDK enforcing exactly the same rule."

*Hover a BscScan link so the URL shows in the status bar.*

## Shot 5 · The checklist that says no — 2:00–2:30

**Screen:** `/status`.

> "And this is why I'd trust it. A go/no-go checklist that executes — not a
> document, a program. It gates broadcasting real money on mainnet, and it
> refuses to go green on anything nobody has checked.
>
> Right now it says NOT YET. Three gates are unverified, and below them is a
> ledger of everything this project advertises and does not have.
>
> The checklist says not yet — and that's the point. The only thing misquoted
> here is the name. Audit me."

*End on the not-built ledger, not on a logo.*

---

## If you have thirty seconds instead of two and a half

Shot 1, then Shot 3, then the last two sentences of Shot 5.

## What not to do

- Don't demo `/quote` against the live API on camera. It's a free Render
  instance that sleeps, and a real replay is ~75 minutes. The `/demo` path is
  recorded precisely so this never bites you.
- Don't skip the loss in Shot 3. It is the most persuasive thing on the site,
  and a judge who spots you skipping it discounts everything else.
- Don't claim `bag deploy` ran. It didn't. The agent runs and the CLI registered
  its identity; that's the claim, and it is enough.
