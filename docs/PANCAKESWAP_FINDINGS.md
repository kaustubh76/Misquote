# Six ways PancakeSwap v3 is not Uniswap v3, and what each costs

Written to be filed, not to be marketed. Every number below was read off BNB
Smart Chain and is reproducible from this repository; each has a test behind it
that fails if the reading stops being true.

We are not affiliated with PancakeSwap. We wrote a replay engine against v3
pools, got several of these wrong first, and are writing them down because the
next person will get them wrong the same way.

**Pools referenced**

| | address | fee | spacing | `feeProtocol` |
|---|---|---|---|---|
| WBNB/USDT 0.05% | `0x36696169C63e42cd08ce11f5deeBbCeBae652050` | 500 | 10 | **3400** |
| WBNB/USDT 0.25% | `0x1401ff943D08a7E098328C1d3a9d388923B115D2` | 2500 | 50 | **3200** |
| TSLAx/USDT 0.25% | `0x5E12d6EdB2b7D5330e474ea2D2694A3b3E35d492` | 2500 | 50 | **3200** |

**What we have actually sent you.** One transaction: a v2
`swapExactETHForTokens`,
[`0x63a1b95c…78f2`](https://bscscan.com/tx/0x63a1b95c219806110e3970794df9a537e677272a1b9ed8992fa82d0dbe0878f2),
0.0003 BNB for 0.2058 of an ERC-8183 payment token, block 119,322,218. No
liquidity position; nothing here has minted one on mainnet. The findings below
come from reading your contracts and replaying your pools, not from providing
into them.

---

## 1. `feeProtocol` is `slot0[2]`, and we read `slot0[5]` for weeks

This one is ours to admit, and it is the reason for the rest of the list.

We read `slot0`, took index 5, got a small plausible integer, and published
**`fee_protocol = 0`** — concluding LPs keep the whole fee. Index 5 is
`observationCardinalityNext`. Index 2 is `feeProtocol`. Both hold small
integers, so nothing looked wrong.

It surfaced because two of our own numbers disagreed, not because anything
raised an error. `feeProtocol` packs two `uint16`: `fee0 | (fee1 << 16)`. The
flagship reads **222,825,800**, which is 3400 in both halves.

**Cost if wrong:** you believe LPs keep 100% of fees when they keep 66%.

## 2. There is no single correct `feeProtocol` constant — not even per pair

The same pair, three tiers, three values:

- WBNB/USDT **0.01%** → 3300 (LPs keep 67%)
- WBNB/USDT **0.05%** → 3400 (LPs keep **66%**)
- WBNB/USDT **0.25%** → 3200 (LPs keep 68%)

Anyone who hardcodes a protocol fee — even one derived correctly from a single
pool — is wrong on the pool next door. Read `slot0.feeProtocol` per pool, per
call.

**Cost if wrong:** a 2pp error in LP share, silently, on some pools and not
others.

## 3. Uniswap's fee model overstates PancakeSwap LP earnings by 1.515×

Follows from 1 and 2, and it is the one that reaches a headline. Uniswap v3's
protocol fee is **off unless governance turns it on**; PancakeSwap's is on by
default. Reconstructing fees from swap volume — the natural way to write a
replay engine — gives LPs the whole fee.

`1 / 0.66 = 1.5151…`

**Cost if wrong:** every APR you publish is overstated by roughly half again.
This moved our own headline number when we fixed it.

## 4. `MIN_TICK` is not a multiple of any PancakeSwap tick spacing

`887272 % 10 = 2`. The tiers are `100→1`, `500→10`, `2500→50`, `10000→200`, and
**there is no 3000 → 60 tier** — the most-used tier on Uniswap does not exist
here.

So a range clamped to the tick extreme lands on a tick the pool will not accept,
and the mint reverts having spent the gas. A width copied from a Uniswap example
assumes a spacing that is not there.

**Cost if wrong:** a reverted mint, at the moment you are trying to enter.

## 5. The `Swap` event has nine parameters, not seven

Uniswap: `topic0 = 0xc42079f9…`, seven parameters.
PancakeSwap: `topic0 = 0x19b47279…`, nine — the extra two are
`protocolFeesToken0` and `protocolFeesToken1`.

Filter on the Uniswap signature and you get **zero logs** from a pool doing
millions in volume. Not an error — an empty result, which is worse.

The two extra fields are the honest fix for finding 3: rather than modelling the
protocol's cut, read what it actually took, per swap.

**Cost if wrong:** an indexer that silently returns nothing.

## 6. Two more, briefly

**The pool address is not derivable with Uniswap's constants.** PancakeSwap
deploys through a separate `PancakeV3PoolDeployer` with a different init-code
hash, so `computeAddress` yields a well-formed address that is not the pool.
Resolve through `factory.getPool()`, always.

**The mint callback is `pancakeV3MintCallback`**, not `uniswapV3MintCallback`; a
direct pool call built against the Uniswap ABI reverts.

**The router keeps `deadline` inside the params struct**, where SwapRouter02
dropped it. The wrong calldata shape costs **23,000 gas** and reverts with empty
data — which looks like nothing at all. Check the selector, not the docs.

---

## How to check any of this

```
make vet                      # nine checks per pool, read from chain
make venue                    # the divergence table above, regenerated
make fork-parity              # the half that is *not* a divergence
```

That last one is the counterpart to this list. Six libraries — `TickMath`,
`SqrtPriceMath`, `FullMath`, `FixedPoint128`, `Tick`, `LiquidityAmounts` — are
token-identical between your v3 and Uniswap's: the SPDX header changes, prettier
rewraps a few ternaries, one import path is rewritten, and the arithmetic is the
same program. That is worth stating as loudly as the six divergences, because it
is what makes them a short list rather than a rewrite.

The per-pool badges are in `vetting/badges/`, the constants in
`packages/misquote/chain/addresses.py`, and check 9 —
`recorded-matches-chain` — exists specifically so finding 1 cannot recur: it
re-reads the chain and fails if a recorded constant has drifted.

## What we are not claiming

These are integration findings, not a security disclosure — nothing here is a
vulnerability in PancakeSwap's contracts. The contracts are behaving as
designed; the errors are all in code written *against* them by people
generalising from Uniswap, ourselves first among them.

Five of our nine pool checks have no executable proof-of-concept, and finding 1
and finding 2 are carried by two of those five. They are readings — a pool
either reports 3400 or it does not — and no transaction demonstrates a reading.

## Where this goes

A document that stays in our own repository benefits nobody it is about. Two
places, and the first is the one that matters:

- **Contracts and integration behaviour** — an issue per finding, or one issue
  linking to this file, at
  <https://github.com/pancakeswap/pancake-v3-contracts/issues>. Findings 1, 2, 4
  and 5 are about what the deployed contracts return and are reproducible from a
  fork with no permission needed.
- **Developer documentation** — <https://developer.pancakeswap.finance/contracts/v3/>
  is where a reader arrives believing v3 is Uniswap v3 with a different address.
  Findings 1, 3 and 5 are documentation gaps as much as anything.

A summary to paste, which is the whole argument in three lines:

> Integrating PancakeSwap v3 from a Uniswap v3 codebase, we hit six divergences
> that produce plausible wrong numbers rather than errors. `feeProtocol` is
> `slot0[2]` and not `slot0[5]`; it differs between tiers of the same pair, so
> no constant is right; assuming Uniswap's zero overstates LP fee income by
> 1.515×; `MIN_TICK % 10 == 2`, so the usual full-range mint reverts; and the
> `Swap` event carries nine parameters, not seven, so a Uniswap ABI decodes it
> silently wrong. Each with the reading, how to reproduce it, and what it costs:
> <link to this file>

Not a security disclosure and not filed as one — see the section above. If any
of it is already known and documented somewhere we did not find, that is a
finding about the documentation and we would rather hear it than be right.
