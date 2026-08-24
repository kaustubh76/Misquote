"""8004scan: a second, independent count of the ERC-8004 registry.

This repository already counts BSC's agent population itself, on chain, by
binary search on `ownerOf` — `totalSupply()` reverts on the proxy. That number
is in `data/registry_survey.json` and it is the one the cards are built from.

8004scan (by AltLayer) indexes the same registries and publishes the same
population through a REST API. **It is carried alongside our own reading, never
in place of it**, for the reason `chain/venus.py` gives about
`vUSDT.underlying()`: two counts arrived at by different methods either agree,
which is evidence, or they disagree, which is a finding. A single number
repeated is neither.

They disagree, and the artifact says so rather than picking the flattering one.

## What it can say that a chain read cannot

The registry stores identity. It does not store whether anybody has ever used an
agent. 8004scan aggregates feedback, scores, protocol support and x402
capability across chains, which is the half of "is this agent real" that
`ownerOf` cannot answer — and which is the half a marketplace claiming to
replace star ratings with evidence has to engage with rather than ignore.

## Two tiers, and the key changes what may honestly be claimed

Anonymous: `/api/v1/public`, 10 requests a minute. At that rate the only
affordable reading is a *sample*, and the cheapest sample the API will serve is
its default page — the hundred newest agents on the chain. That page is not a
sample of the registry. The recorded one held 18 distinct descriptions across
100 rows and zero agents with any feedback, because a hundred consecutive mints
are usually one platform's batch. Shares computed off it describe that batch.

Keyed: `SCAN8004_API_KEY` unlocks `/api/v1`, **600 requests a minute and 100,000
a day** (measured off the `x-ratelimit-limit-*` response headers, not the docs).
278,353 BSC agents at 100 a page is 2,784 requests. So with a key the answer
stops being a sample at all: `census()` counts every agent on the chain and the
shares it reports need no confidence interval, because nothing was inferred.
`sampled: 100 of 278,353` becomes `counted: 278,353 of 278,353`, which is a
different claim rather than a better-worded one.

**Budget an hour, not the ten minutes the request count suggests.** A short
burst sustains ~460 rows/s, and that number does not survive contact with 2,784
of them: the first full run took 68 minutes. The rate limit is not what binds —
that run never came near it — 8004scan's own latency is, and it is erratic
rather than merely high. See `CENSUS_ATTEMPTS` for what the first run lost by
being paced to the optimistic figure.

A missing key therefore degrades to *narrower*, and says which reading it took
in `tier` on every payload — it never degrades to a census-shaped number quietly
computed off a hundred rows.

## Three ways this API answers wrongly rather than failing

All three were found by probing it, and all three are silent, which is why each
one is asserted here rather than trusted:

1. **The two tiers do not share a parameter name.** `/api/v1` filters on
   `chain_id`; `/api/v1/public` filters on `chainId`. Passing the wrong one is
   not an error — the keyed endpoint ignores `chainId` and cheerfully returns
   Base and Abstract agents, which would land in the artifact labelled BSC. So
   the chain of every row is checked against the chain that was asked for.
2. **`limit` above 100 returns an empty page**, not a 400 and not a clamped
   page. A caller asking for 500 gets `items: []` and, without this clamp, would
   record a population of zero as though the chain were empty.
3. **The envelopes differ.** Keyed answers `{items, total, limit, offset}`;
   anonymous answers `{data, meta: {pagination: {total}}}`. Normalised in one
   place so no caller has to know which tier it got.

Every call is wrapped: an unreachable API produces `available: false` with the
reason, never a zero and never a count carried over from a previous run. That is
`vetting/read.py`'s rule — unknown does not become pass — applied to a
third-party source, where it matters more because the failure is somebody
else's to fix.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
from collections import Counter
from dataclasses import dataclass
from typing import Any

import httpx

#: Anonymous. No key, 10 requests a minute, `chainId`, `{data, meta}`.
PUBLIC_BASE = "https://8004scan.io/api/v1/public"

#: Keyed. 600 requests a minute, `chain_id`, `{items, total}`.
PRO_BASE = "https://8004scan.io/api/v1"

#: The key's name. Uppercase on purpose: `tests/test_env_template.py` matches
#: `^[A-Z][A-Z0-9_]{2,}$`, so a name carrying a lowercase suffix — the
#: `API_KEY_8004_pro` this was first handed as — is invisible to the guard that
#: keeps `.env.example` honest. An unguarded config name is one rename away from
#: silently reverting the whole surface to the anonymous tier.
KEY_ENV = "SCAN8004_API_KEY"

#: The largest page either tier will actually serve. Asking for more returns an
#: empty page rather than an error — see the module docstring, trap 2.
MAX_LIMIT = 100

TIMEOUT = 30.0

BSC_CHAIN_ID = 56


@dataclass(frozen=True)
class Tier:
    """Which of the two APIs this process is entitled to, and how it differs."""

    name: str
    base: str
    chain_param: str
    headers: dict[str, str]
    requests_per_minute: int
    #: Whether a whole-population read is affordable at this rate. Ten requests
    #: a minute is 4.6 hours for BSC, which is not a build step.
    can_census: bool


def tier() -> Tier:
    """The tier this process can reach, decided by the environment alone."""
    # Spelled out rather than read through `KEY_ENV`, because
    # `tests/test_env_template.py` walks the AST for string *constants* inside
    # an `os.environ` access and a variable there reads as no variable at all —
    # the template guard would pass while the template said nothing. The two
    # spellings are held in step by `test_the_key_the_module_names_is_the_key_it_reads`.
    key = (os.environ.get("SCAN8004_API_KEY") or "").strip()
    if key:
        return Tier(
            name="keyed",
            base=PRO_BASE,
            chain_param="chain_id",
            headers={"X-API-Key": key},
            requests_per_minute=600,
            can_census=True,
        )
    return Tier(
        name="anonymous",
        base=PUBLIC_BASE,
        chain_param="chainId",
        headers={},
        requests_per_minute=10,
        can_census=False,
    )


class ForeignChain(RuntimeError):
    """A page came back holding agents from a chain nobody asked for.

    Raised rather than filtered. A page that answers about the wrong chain means
    the filter did not apply, so the `total` alongside it is the wrong total too
    — dropping the foreign rows would keep the wrong denominator and produce a
    number that looks like BSC and is not.
    """


def _normalise(payload: Any) -> tuple[list[dict[str, Any]], int | None]:
    """One page, in whichever envelope the tier that served it uses."""
    if not isinstance(payload, dict):
        raise ValueError(f"8004scan returned {type(payload).__name__}, not an object")
    if "items" in payload:  # keyed
        return list(payload.get("items") or []), payload.get("total")
    rows = list(payload.get("data") or [])  # anonymous
    total = ((payload.get("meta") or {}).get("pagination") or {}).get("total")
    return rows, total


def _check_chain(rows: list[dict[str, Any]], chain_id: int) -> None:
    strays = sorted({r.get("chain_id") for r in rows} - {chain_id})
    if strays:
        raise ForeignChain(
            f"asked 8004scan for chain {chain_id} and it also returned {strays}. "
            "The chain filter did not apply, so neither these rows nor the total "
            "beside them describe the chain requested."
        )


def _params(t: Tier, chain_id: int, limit: int, offset: int, ascending: bool) -> dict[str, Any]:
    params: dict[str, Any] = {
        t.chain_param: chain_id,
        "limit": min(limit, MAX_LIMIT),
        "offset": offset,
    }
    if ascending:
        # Paging a 278,000-row table newest-first shifts every row toward the
        # tail while the walk is in progress: agents get counted twice and
        # others never appear. Ascending order appends new agents past the end
        # instead, so the prefix a census walks is stable. Measured, on the run
        # that established the rest of this pacing: 72 BSC agents minted during
        # 68 minutes of walking — small, and small is not zero over 2,784 pages.
        # `sort_order=asc` is the parameter that works — `sort`, `sort_by`,
        # `order` and `order_by` are all accepted and all ignored.
        params["sort_order"] = "asc"
    return params


def _get(path: str, params: dict[str, Any] | None = None, t: Tier | None = None) -> Any:
    t = t or tier()
    with httpx.Client(timeout=TIMEOUT, follow_redirects=True, headers=t.headers) as client:
        response = client.get(f"{t.base}{path}", params=params or {})
        response.raise_for_status()
        return response.json()


def population(chain_id: int = BSC_CHAIN_ID) -> dict[str, Any]:
    """8004scan's agent count for a chain, and the registry it indexes.

    The registry address is returned so a caller can check it against
    `erc8004.IDENTITY_REGISTRY`. If the two indexed different contracts the
    counts would not be comparable at all, and comparing them anyway would be a
    worse error than not comparing them.
    """
    t = tier()
    try:
        rows, total = _normalise(_get("/agents", _params(t, chain_id, 1, 0, False), t))
        _check_chain(rows, chain_id)
    except Exception as error:  # noqa: BLE001 — any failure is "unavailable"
        return {
            "available": False,
            "tier": t.name,
            "reason": f"8004scan /agents did not answer: {type(error).__name__}: {error}",
        }

    if total is None:
        return {"available": False, "tier": t.name, "reason": "8004scan returned no total"}

    return {
        "available": True,
        "tier": t.name,
        "chain_id": chain_id,
        "population": int(total),
        # The contract 8004scan says these agents live in. Compared against ours
        # by the caller.
        "contract_address": (rows[0].get("contract_address") if rows else None),
    }


# ── the signals a page carries, counted the same way whether 100 rows or 278,353 ──


class _Signals:
    """Running counts over agent rows, holding no rows.

    A census sees 278,353 records and needs none of them afterwards, so nothing
    is accumulated but counters and two digest sets. Descriptions are counted by
    8-byte digest rather than by text for the same reason — the question is how
    many distinct ones there are, and the strings themselves would be the
    largest thing in the process by an order of magnitude.
    """

    def __init__(self) -> None:
        self.rows = 0
        self.verified = 0
        self.with_feedback = 0
        self.with_score = 0
        self.x402 = 0
        self.starred = 0
        self.described = 0
        self.feedbacks = 0
        self.descriptions: set[bytes] = set()
        self.owners: set[str] = set()
        self.protocols: Counter[str] = Counter()

    def add(self, rows: list[dict[str, Any]]) -> None:
        for r in rows:
            self.rows += 1
            if r.get("is_verified"):
                self.verified += 1
            feedbacks = int(r.get("total_feedbacks") or 0)
            if feedbacks > 0:
                self.with_feedback += 1
                self.feedbacks += feedbacks
            if float(r.get("total_score") or 0) > 0:
                self.with_score += 1
            if r.get("x402_supported"):
                self.x402 += 1
            if int(r.get("star_count") or 0) > 0:
                self.starred += 1
            text = (r.get("description") or "").strip()
            if text:
                self.described += 1
            self.descriptions.add(hashlib.blake2b(text.encode(), digest_size=8).digest())
            owner = (r.get("owner_address") or "").lower()
            if owner:
                self.owners.add(owner)
            for protocol in r.get("supported_protocols") or ():
                self.protocols[str(protocol)] += 1

    def as_dict(self) -> dict[str, Any]:
        return {
            "verified": self.verified,
            "with_feedback": self.with_feedback,
            "with_score": self.with_score,
            "x402_supported": self.x402,
            "starred": self.starred,
            "described": self.described,
            "distinct_descriptions": len(self.descriptions),
            "distinct_owners": len(self.owners),
            "feedbacks_claimed": self.feedbacks,
            "protocols": dict(sorted(self.protocols.items(), key=lambda kv: -kv[1])),
        }


def sample(chain_id: int = BSC_CHAIN_ID, limit: int = MAX_LIMIT) -> dict[str, Any]:
    """One page of agents, reduced to the signals a marketplace would rank on.

    This is what the anonymous tier can afford, and its `ordering` field is the
    important one: these are the *newest* agents on the chain, not a draw from
    it. Shares computed here describe the most recent hundred registrations and
    are labelled `sampled` rather than `counted` so they cannot be read as a
    statement about the population. With a key, `census()` answers the question
    this function can only gesture at.
    """
    t = tier()
    try:
        rows, _ = _normalise(_get("/agents", _params(t, chain_id, limit, 0, False), t))
        _check_chain(rows, chain_id)
    except Exception as error:  # noqa: BLE001
        return {
            "available": False,
            "tier": t.name,
            "reason": f"8004scan /agents did not answer: {type(error).__name__}: {error}",
        }

    if not rows:
        return {"available": False, "tier": t.name, "reason": "8004scan returned an empty page"}

    signals = _Signals()
    signals.add(rows)
    return {
        "available": True,
        "tier": t.name,
        "chain_id": chain_id,
        "sampled": signals.rows,
        **signals.as_dict(),
        "ordering": "8004scan's default, which is newest first",
        "note": (
            "A page, not a draw. These are the newest registrations on the chain, "
            "which arrive in platform-sized batches — so every share here is a "
            "share of that batch. Set SCAN8004_API_KEY and the census counts the "
            "whole chain instead."
        ),
    }


# ── the census ────────────────────────────────────────────────────────────────

#: How many pages are in flight at once. Measured: 32 in flight sustains ~460
#: rows/s in a short burst at about 280 requests a minute, comfortably under the
#: keyed tier's 600. Held there rather than raised after the first full run,
#: which confirmed the ceiling is 8004scan's per-request latency and not our
#: rate — it finished with 500 of 600 requests a minute unused. More in flight
#: would only deepen the queue that was already timing pages out; the fix was a
#: ceiling those requests could survive, not more of them.
CENSUS_CONCURRENCY = 24

#: Attempts per page before the page is recorded as a hole. A page that never
#: arrives must subtract from `counted` and clear `complete`, never quietly
#: shrink the totals.
#:
#: Five, not three, and the backoff is exponential rather than linear, because
#: the first full BSC run lost 762 of 2,784 pages — 76,200 agents — and the
#: cause was not what the retry was built for. There were no 429s and no
#: throttling: 96 sampled requests at this concurrency spent 500 of the 600
#: requests a minute unused and still timed out 24 times. 8004scan's `/agents`
#: is simply slow and erratically so — measured p50 15.3s, p90 30.2s, and
#: single reads at deep offsets ranging 3.5s to 95.3s with no relation to depth.
#: Three tries 1.5s apart against a 30-second ceiling is not a retry policy for
#: that; it is the same request three times inside one slow window.
CENSUS_ATTEMPTS = 5

#: Seconds a census page may take. Deliberately far above `TIMEOUT`, which
#: governs the single reads where 30 seconds is a reasonable wait: the ceiling
#: that lost a quarter of the first census was that same 30 seconds applied to
#: a request whose 90th percentile sits on top of it.
CENSUS_TIMEOUT = 150.0

#: The repair pass runs narrow. If pages failed because the server was queuing
#: two dozen of our requests at once, asking for the stragglers two dozen at a
#: time again is the same experiment.
REPAIR_CONCURRENCY = 4


async def _census(chain_id: int, page_size: int) -> dict[str, Any]:
    t = tier()
    if not t.can_census:
        return {
            "available": False,
            "tier": t.name,
            "reason": (
                f"a census needs the keyed tier: {t.requests_per_minute} requests a "
                f"minute would take about {278_000 / MAX_LIMIT / t.requests_per_minute / 60:.1f} "
                f"hours for BSC. Set {KEY_ENV}."
            ),
        }

    limit = min(page_size, MAX_LIMIT)
    signals = _Signals()
    #: offset -> why it never arrived. A count of holes says the census is
    #: incomplete; the reasons say whether that is 8004scan being slow, us
    #: asking wrongly, or the index having moved underneath the walk — and only
    #: the first of those is somebody else's to fix.
    failed: dict[int, str] = {}
    lock = asyncio.Lock()

    async with httpx.AsyncClient(
        timeout=CENSUS_TIMEOUT, headers=t.headers, follow_redirects=True
    ) as c:

        async def page(offset: int) -> None:
            for attempt in range(CENSUS_ATTEMPTS):
                try:
                    r = await c.get(
                        f"{t.base}/agents", params=_params(t, chain_id, limit, offset, True)
                    )
                    r.raise_for_status()
                    rows, _ = _normalise(r.json())
                    _check_chain(rows, chain_id)
                except ForeignChain:
                    raise  # a wrong-chain page is a bug, not a blip. Do not retry it.
                except Exception as error:  # noqa: BLE001
                    if attempt == CENSUS_ATTEMPTS - 1:
                        async with lock:
                            failed[offset] = f"{type(error).__name__}: {error}"
                        return
                    # Exponential. Linear backoff against a server whose slow
                    # window is minutes long just spends the attempts inside it.
                    await asyncio.sleep(2.0 * 2**attempt)
                    continue
                async with lock:
                    failed.pop(offset, None)
                    signals.add(rows)
                return

        try:
            first = await c.get(f"{t.base}/agents", params=_params(t, chain_id, 1, 0, True))
            first.raise_for_status()
            head, at_start = _normalise(first.json())
            _check_chain(head, chain_id)
        except Exception as error:  # noqa: BLE001
            return {
                "available": False,
                "tier": t.name,
                "reason": f"8004scan /agents did not answer: {type(error).__name__}: {error}",
            }

        if not at_start:
            return {"available": False, "tier": t.name, "reason": "8004scan returned no total"}

        offsets = list(range(0, int(at_start), limit))
        semaphore = asyncio.Semaphore(CENSUS_CONCURRENCY)

        async def guarded(offset: int) -> None:
            async with semaphore:
                await page(offset)

        # `return_exceptions=True` rather than letting the first ForeignChain
        # propagate: a bare `gather` raises immediately while its siblings are
        # still in flight, and the `async with` below it would then close the
        # client out from under two dozen live requests. Collected instead, and
        # the first wrong-chain page still ends the census — it just ends it
        # after the walk has stopped rather than during it.
        outcomes = await asyncio.gather(*(guarded(o) for o in offsets), return_exceptions=True)
        for outcome in outcomes:
            if isinstance(outcome, ForeignChain):
                return {"available": False, "tier": t.name, "reason": str(outcome)}
            if isinstance(outcome, BaseException):
                raise outcome

        # The repair pass. Every page that exhausted its attempts is asked for
        # again, four at a time instead of twenty-four — the stragglers are the
        # ones that lost a race for the server's attention, so the repair stops
        # competing with itself. Cheap by construction: it runs over what failed,
        # which on a healthy run is nothing at all.
        if failed:
            stragglers = sorted(failed)
            repair = asyncio.Semaphore(REPAIR_CONCURRENCY)

            async def repaired(offset: int) -> None:
                async with repair:
                    await page(offset)

            outcomes = await asyncio.gather(
                *(repaired(o) for o in stragglers), return_exceptions=True
            )
            for outcome in outcomes:
                if isinstance(outcome, ForeignChain):
                    return {"available": False, "tier": t.name, "reason": str(outcome)}
                if isinstance(outcome, BaseException):
                    raise outcome

        try:
            last = await c.get(f"{t.base}/agents", params=_params(t, chain_id, 1, 0, True))
            last.raise_for_status()
            _, at_end = _normalise(last.json())
        except Exception:  # noqa: BLE001
            at_end = None

    counted = signals.rows
    return {
        "available": True,
        "tier": t.name,
        "chain_id": chain_id,
        "counted": counted,
        # Read before the walk and after it. Ascending order means the agents
        # minted in between land past the offsets this pass asked for, so the
        # gap is growth rather than a miss — but it is reported instead of
        # averaged away, because `counted` is a count of a moving population and
        # saying so is the whole difference between a census and a claim.
        "population_at_start": int(at_start),
        "population_at_end": (int(at_end) if at_end is not None else None),
        "minted_during_the_walk": (int(at_end) - int(at_start) if at_end is not None else None),
        "pages_failed": len(failed),
        "agents_missed": len(failed) * limit,
        # Why, and not only how many. An incomplete census is publishable; an
        # incomplete census that cannot say what went wrong is a number nobody
        # can act on — the reader cannot tell a slow afternoon from a broken
        # reader, and the two call for opposite responses.
        "failure_reasons": dict(Counter(failed.values()).most_common()),
        "failed_offsets": sorted(failed)[:20],
        "complete": not failed and counted >= int(at_start),
        **signals.as_dict(),
        "ordering": (
            "ascending, so the pages already walked do not shift while the chain "
            "keeps minting — measured at 72 new BSC agents during a 68-minute walk"
        ),
        "note": (
            "Every agent the index holds for this chain, counted — not sampled. "
            "The shares carry no confidence interval because nothing was inferred: "
            "`counted` is the denominator. What it cannot say is whether 8004scan's "
            "index is itself complete, which is why our own on-chain count is "
            "published beside it and the two are reconciled rather than merged."
        ),
    }


def census(chain_id: int = BSC_CHAIN_ID, page_size: int = MAX_LIMIT) -> dict[str, Any]:
    """Count every agent the index holds for a chain. Needs the keyed tier.

    Ten minutes for BSC's 278,000. Refuses on the anonymous tier rather than
    silently returning a smaller reading under the same key names — a caller
    reading `counted` must never be handed a number that counted a hundred rows.
    """
    return asyncio.run(_census(chain_id, page_size))


def feedback_reach(chain_id: int = BSC_CHAIN_ID) -> dict[str, Any]:
    """How many feedbacks the chain's registry has recorded, from the other end.

    `census()` already sums `total_feedbacks` across agents. This asks the
    `/feedbacks` collection for its own total, which is a different query over a
    different table, and the two are published together for the reason the whole
    module exists: agreement is evidence, disagreement is a finding.

    Each feedback row carries `transaction_hash` and `block_number`, so unlike a
    star rating the count is anchored to something a reader can check.
    """
    t = tier()
    if t.name != "keyed":
        return {
            "available": False,
            "tier": t.name,
            "reason": f"/feedbacks is on the keyed tier only. Set {KEY_ENV}.",
        }
    try:
        payload = _get("/feedbacks", {"chain_id": chain_id, "limit": 1}, t)
        rows, total = _normalise(payload)
        _check_chain(rows, chain_id)
    except Exception as error:  # noqa: BLE001
        return {
            "available": False,
            "tier": t.name,
            "reason": f"8004scan /feedbacks did not answer: {type(error).__name__}: {error}",
        }
    if total is None:
        return {"available": False, "tier": t.name, "reason": "8004scan returned no total"}
    row = rows[0] if rows else {}
    return {
        "available": True,
        "tier": t.name,
        "chain_id": chain_id,
        "feedbacks": int(total),
        "anchored": bool(row.get("transaction_hash")),
        "example_transaction_hash": row.get("transaction_hash"),
        "example_block_number": row.get("block_number"),
        "note": (
            "Counted from the feedback table rather than summed off the agents. "
            "Every row names the transaction that wrote it, so the count is "
            "checkable on chain — which is what separates it from a star rating."
        ),
    }


def stats() -> dict[str, Any]:
    """The platform's own cross-chain totals, for context only.

    Explicitly not comparable to our BSC count — it spans every chain 8004scan
    indexes. Carried because `daily_new_agents` is the number that makes the
    population figure legible: a registry growing by five figures a day is a
    different object from one that grew to that size over a year.

    Pinned to the anonymous base whatever tier is configured: `/stats` exists
    only under `/public`, and the keyed base answers it `404 Not Found`.
    """
    anonymous = Tier("anonymous", PUBLIC_BASE, "chainId", {}, 10, can_census=False)
    try:
        payload = _get("/stats", None, anonymous)
    except Exception as error:  # noqa: BLE001
        return {"available": False, "reason": f"8004scan /stats did not answer: {error}"}

    data = payload.get("data") or {}
    return {
        "available": True,
        "total_agents_all_chains": data.get("total_agents"),
        "total_feedbacks_all_chains": data.get("total_feedbacks"),
        "daily_new_agents_all_chains": data.get("daily_new_agents"),
        "average_feedback_score": data.get("average_feedback_score"),
    }
