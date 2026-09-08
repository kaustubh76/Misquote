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

## Shot 2 · It runs, with no wallet — 0:18–0:46

**Screen:** click **"Watch it run, no wallet"** → `/demo`, then click step 2.
The quote page arrives with the answer already on screen.

> "You don't need a wallet to check that. This is a recorded run against the
> real tape — the page arrives with the answer already computed. That's a P25 to
> P75 band, not a single number, because a single number would be a claim about
> a future nobody has. The banner says 'simulated' because it is: under this
> link no request is issued at all."

*Point the cursor at the band and at the simulation banner.*

**This shot used to be nine seconds longer** and used them explaining why a band
is not a point. Shot 3 makes that argument better by letting a viewer change one
input and watch the number move, so the explanation moved there and the seconds
went with it.

## Shot 3 · What it would have paid you — 0:46–1:11

**Screen:** `/simulate`, from the nav. The page arrives on the flagship pool at
±40 ticks with a figure already on it.

> "That's a quote about an agent. This is the same engine pointed at the
> question an LP actually arrives with: what would this have paid *me*.
>
> Pick a pool, a width, and an amount. Fourteen hundred positions, all replayed
> over two hundred and fifty thousand real swaps — so nothing here is signed,
> nothing is held, and it cannot cost anybody anything."

*Click **2.00**.*

> "Twice the size. And notice the rate went **down** — nought point four seven
> of a percentage point, on every unit. A bigger position takes a smaller share
> of each swap's fee, and almost every yield page you will ever see multiplies
> instead, which quietly flatters the larger position. We measured it rather
> than scaled it, which is why there are five sizes and not a text box."

*Switch the pool to **WBNB/USDT 0.25%** and click **2.00** again — it refuses.*

> "And here it just says no. Two BNB is more than that range can absorb — it
> holds 1.28 BNB of depth, so the ceiling is 0.0128. It refuses rather than
> clamping, because a position big enough to move the price it is paid at can't
> be quoted from history it would have changed. Go wider and the ceiling rises.
> That's a capacity answer, and a fee APR cannot give you one."

*Do not scroll past the refusal. It is the shot.*

## Shot 4 · The honest part — 1:11–1:43

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

## Shot 5 · Real money, real chain — 1:43–2:07

**Screen:** landing page → **"0.1 of a token escrowed on BSC mainnet and
reclaimed"** → `/registry#escrow`.

> "This isn't only replays. We escrowed a tenth of a token into a live ERC-8183
> job on BNB Smart Chain mainnet and reclaimed it — both mined, both linked to
> BscScan here. Then we did it again and got further: job 56718 is funded and
> delivered into, with `submit` mined on mainnet.
>
> The first one couldn't reach submit, and the reason is the interesting part.
> It needs an expiry beyond the seven-day dispute window and we asked for
> twelve hours. We measured that boundary across eight fork runs before we found
> the name of the error — and then found the vendor's own SDK enforcing exactly
> the same rule.
>
> What's left is settle, and it's a wait: the dispute window closes on the
> thirteenth. If we miss it the budget is still recoverable, which we rehearsed
> on a fork rather than assumed.
>
> And none of that is a recording you have to take my word for. Same seven
> calls, from your wallet, on the Hire tab."

*Hover a BscScan link so the URL shows in the status bar, then click **Hire** in
the nav.* On `/activate`, the escrow sits above the session key: pick an agent
in **Who delivers**, and the stepper offers one call — the next one — with every
other row saying what it is waiting for or who signs it.

> "Hiring Warden means the money is escrowed to Warden, not to me. Which costs
> me `submit` — that's the provider's signature, and this page won't offer me a
> button that would revert. Five calls I can send, two I can't, and it says
> which is which before I sign anything."

*Do not send a transaction here unless the wallet is funded and the run is
rehearsed — `make prove-escrow` is the fork rehearsal.*

## Shot 6 · The checklist that says no — 2:07–2:30

**Screen:** `/status`.

> "And this is why I'd trust it. A go/no-go checklist that executes — not a
> document, a program. Twenty-one gates, run against mainnet, and it refuses to
> go green on anything nobody has checked.
>
> Below it is a ledger of everything this project advertises and does not have —
> including the one that matters most here: this has never signed a trade with
> real money, and the checklist is what stands in front of that.
>
> The only thing misquoted here is the name. Audit me."

**Read the verdict off the page rather than from this script.** It has been
NOT YET for the whole of this project's life and the number of ambers has been
falling: three, then one — a 24h unattended burn-in on BSC mainnet that was
still counting when this was written. Say what the page says when you record.
If every gate is green, the sentence is *"twenty-one of twenty-one, and the
not-built ledger is still five items long"* — the ledger is the honest part
either way, and it is what the shot ends on.

*End on the not-built ledger, not on a logo.*

---

## If you have thirty seconds instead of two and a half

**The name**, then **the honest part**, then the last two sentences of **the
checklist that says no**.

By name and not by number, deliberately. This read "Shot 1, then Shot 3, then
Shot 5" until a sixth shot was inserted in the middle and every number after the
second one silently began pointing at the wrong thing — which is a footgun in a
document somebody reads while recording.

## If the thirty seconds are for the PancakeSwap track

**The name**, then **what it would have paid you** — and in that shot, spend the
time on the refusal rather than on the earnings. Any marketplace can show you a
number. Being told that two BNB is more than the range can absorb, with the
depth it was measured against, is the part nothing else does.

## What not to do

- Don't demo `/simulate` against a cold Render instance expecting the pool
  lookup on `/venue` to answer — that one is the only PancakeSwap control that
  needs the API. `/simulate` itself reads a published artifact and needs nothing
  running, which is why it is safe to click on camera.
- Don't demo `/quote` against the live API on camera. It's a free Render
  instance that sleeps, and a real replay is ~75 minutes. The `/demo` path is
  recorded precisely so this never bites you.
- Don't skip the loss in **the honest part**. It is the most persuasive thing on the site,
  and a judge who spots you skipping it discounts everything else.
- Don't claim `bag deploy` ran. It didn't. The agent runs and the CLI registered
  its identity; that's the claim, and it is enough.
