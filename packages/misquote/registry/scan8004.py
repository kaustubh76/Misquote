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

## Two tiers, and what the key actually buys

Anonymous: `/api/v1/public`, **180 requests a minute and 20,000 a day**. Keyed:
`SCAN8004_API_KEY` unlocks `/api/v1` at **3,000 a minute and 3,000,000 a day**.
All four figures are read off `x-ratelimit-limit-minute` and
`x-ratelimit-limit-day` on live responses. The published documentation says 600
and 100,000 for the keyed tier and is wrong by 5x and 30x; this file was written
against a 10-a-minute anonymous tier that no longer exists either. Numbers here
are measurements. Re-measure before trusting them again.

**The key does not buy speed, and believing it did cost this module two hours a
run.** The rate ceiling moved 5x and the census did not get one second faster,
because the census was never rate-bound: 8004scan's `/agents` slows with offset
depth — a page at offset 0 answers in about 4 seconds and a page at offset
200,000 in about 40 — and a full BSC walk is 60 to 130 minutes depending on the
afternoon. Retries absorb the timeouts, so it does finish; it just never
finishes quickly. See `CENSUS_CONCURRENCY` for why adding workers makes it worse.

What the key buys is that **the index will answer aggregate and ranked questions
directly**. `x402_supported=true` returns a `total` of 66,489 in one request,
which is the same quantity `census()` spends 2,848 requests deriving. `search=`
names the agents in a category in about a second. `/feedbacks` becomes readable
at all, and every row on it embeds the agent it rates — so one 118-page walk
yields both an aggregate about the registry's reputation layer and a per-agent
index keyed by token id. Those are claims a walk cannot make, not a walk made
faster.

The catch is trap 4 below, and it is the reason `proven_count` exists: a filter
this API does not implement is *accepted and ignored*, and answers with the
whole population under the label you asked for.

A missing key degrades to *narrower*, and says which reading it took in `tier`
on every payload — it never degrades to a census-shaped number quietly computed
off a hundred rows.

## Four ways this API answers wrongly rather than failing

All four were found by probing it, and all four are silent, which is why each
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
4. **A filter it does not implement is accepted and ignored**, and the response
   carries the *whole population* under the label you asked for. `is_verified`,
   `has_feedback`, `protocol`, `supported_protocols` and `q` all return 284,712
   on BSC — the unfiltered count — with HTTP 200 and rows that look right
   because any 25 rows look right. `sort_by=star_count` and
   `sort_by=health_score` do the same to orderings: accepted, and answered
   newest-first. This is trap 1 generalised, and it is worse, because a wrong
   *chain* is visible in the rows while a wrong *denominator* is not. Guarded by
   `proven_count`, which publishes no share it has not shown the filter for —
   and unlike trap 1 the guard omits the number rather than raising, because a
   refused filter still has a baseline and a reason worth returning.

Every call is wrapped: an unreachable API produces `available: false` with the
reason, never a zero and never a count carried over from a previous run. That is
`vetting/read.py`'s rule — unknown does not become pass — applied to a
third-party source, where it matters more because the failure is somebody
else's to fix.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import json
import os
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx

#: Anonymous. No key, 180 requests a minute, `chainId`, `{data, meta}`.
PUBLIC_BASE = "https://8004scan.io/api/v1/public"

#: Keyed. 3,000 requests a minute, `chain_id`, `{items, total}`.
PRO_BASE = "https://8004scan.io/api/v1"

#: The key's name. Uppercase on purpose: `tests/test_env_template.py` matches
#: `^[A-Z][A-Z0-9_]{2,}$`, so a name carrying a lowercase suffix — the
#: `API_KEY_8004_pro` this was first handed as — is invisible to the guard that
#: keeps `.env.example` honest. An unguarded config name is one rename away from
#: silently reverting the whole surface to the anonymous tier.
KEY_ENV = "SCAN8004_API_KEY"

#: Sent on every request, to both tiers, and it is not cosmetic.
#:
#: `X-API-Key` alone under urllib's default `Python-urllib/3.x` gets HTTP 403
#: from 8004scan's edge; the same key with any browser-shaped agent gets 200.
#: httpx happens to send `python-httpx/...` and is let through — so every
#: reading this module has ever taken depended on a header nobody here chose,
#: and a caller reaching the same API from curl, urllib or a fixture would meet
#: a 403 that looks exactly like a rejected key. Pinned so the dependency is
#: declared rather than inherited.
USER_AGENT = "misquote/1.0 (+https://github.com/misquote; ERC-8004 cross-check)"

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
    #: Both measured off `x-ratelimit-limit-minute` / `-day` on live responses,
    #: never from the documentation, which says 600 and 100,000 for the keyed
    #: tier and is wrong by 5x and 30x respectively.
    requests_per_minute: int
    requests_per_day: int
    #: Whether a whole-population count may be *published* from this tier.
    #:
    #: Not a statement about speed, and it stopped being one when the anonymous
    #: limit turned out to be 180 requests a minute rather than the 10 this
    #: module was written against. At 180 a census is affordable, and it is
    #: still refused: the anonymous endpoint takes a different chain parameter,
    #: answers in a different envelope, and its `total` has never been checked
    #: against anything. `counted` is a claim about a population, and the tier
    #: that cannot support the claim must not produce the number.
    can_census: bool


def _anonymous_tier() -> Tier:
    """The tier with no key, built in one place.

    Two callers construct this — `tier()` when the environment holds no key, and
    `stats()`, which pins itself here whatever the environment says because
    `/stats` exists only under `/public`. Two construction sites for one tier is
    two places for a measured limit to go stale, and only one of them is on the
    path a test would notice.
    """
    return Tier(
        name="anonymous",
        base=PUBLIC_BASE,
        chain_param="chainId",
        headers={"User-Agent": USER_AGENT},
        requests_per_minute=180,
        requests_per_day=20_000,
        can_census=False,
    )


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
            headers={"X-API-Key": key, "User-Agent": USER_AGENT},
            requests_per_minute=3_000,
            requests_per_day=3_000_000,
            can_census=True,
        )
    return _anonymous_tier()


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


# ── the filters, and the proof that one applied ───────────────────────────────

#: How many rows are pulled alongside a filtered count purely to check that the
#: predicate holds on them.
#:
#: Not one. A single row satisfying `x402_supported=true` is also what an
#: unfiltered page produces about a quarter of the time, so one row proves
#: nothing at all. Twenty-five costs the same request and makes an accidental
#: pass vanishingly unlikely for every filter this module asks for.
PROOF_ROWS = 25

#: How far `filtered + complement` may miss the unfiltered baseline before the
#: pair is refused.
#:
#: Deliberately loose, and the looseness is the design. Measured: 66,489 +
#: 218,270 = 284,759 against a baseline of 284,712 read seconds earlier — 47
#: apart, because BSC mints agents continuously and the three requests are not
#: simultaneous. This is not calibrated to catch a filter that is slightly
#: wrong. It is calibrated so that a filter that was *ignored* cannot pass, and
#: an ignored filter misses by the size of the population — 218,270, not 47.
DRIFT_TOLERANCE = 5_000

#: The only feedback threshold this module will ask for.
#:
#: `min_feedbacks=1` answers in about a second. `min_feedbacks=5` and
#: `min_feedbacks=100` each hang for roughly 94 seconds and come back with no
#: `total` at all — not an error, not a timeout we could retry into success,
#: just an envelope missing the one field the caller wanted. So asking above one
#: is a bug rather than a slow query, and `test_min_feedbacks_is_never_asked_
#: above_the_value_that_answers` holds it there.
MIN_FEEDBACKS_CEILING = 1

#: Parameters 8004scan accepts, ignores, and answers with the full population.
#:
#: Recorded rather than merely left out. An omitted parameter looks forgotten,
#: and the next reader — reasonably — adds it back, gets HTTP 200 and a page of
#: plausible rows, and publishes the whole chain under a label. Each of these
#: was probed against chain 56 and returned the unfiltered count.
IGNORED_PARAMS: dict[str, str] = {
    "has_feedback": "returns the full population — use min_feedbacks=1",
    "is_verified": (
        "returns the full population, which is why the census's `verified: 0` "
        "across 278,500 agents cannot be cross-checked by any means we have"
    ),
    "protocol": "returns the full population — no protocol filter is implemented",
    "supported_protocols": "returns the full population",
    "q": "returns the full population — the search parameter is `search`",
    "token_id": "on /feedbacks only; the filter that applies there is agent_id (a uuid)",
}

#: `sort_by` values the API accepts and does not act on. Both were answered with
#: a page byte-identical to no sort at all: newest first.
IGNORED_SORTS: dict[str, str] = {
    "star_count": "accepted, returns newest-first",
    "health_score": "accepted, returns newest-first",
}

#: The three that do sort, with `sort_order=desc`. One to nine seconds each.
WORKING_SORTS = ("total_score", "total_feedbacks", "created_at")


def _read_at() -> str:
    """When a reading was taken, on every payload that takes one.

    Absent from this module until the counts arrived, and its absence had a
    cost: a census walked over two hours and a filtered count taken now are two
    readings of one registry, and without timestamps nothing can say whether a
    gap between them is a finding or is six thousand agents minted in between.
    A disagreement with no interval attached is not publishable as either.
    """
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass(frozen=True)
class Filter:
    """One server-side predicate, and everything needed to prove it applied."""

    #: What the resulting share is called in the artifact.
    name: str
    #: The query parameters that select the set.
    params: dict[str, Any]
    #: Applied to returned rows. If a row fails it, the filter did not apply.
    predicate: Callable[[dict[str, Any]], bool]
    #: The parameters selecting the opposite set, where one exists. Without it
    #: only two of the three checks can run, and the payload says which.
    complement: dict[str, Any] | None = None
    #: Seconds this particular filter may take, because they do not cost the
    #: same. `x402_supported` answers in under a second; `min_feedbacks=1` was
    #: measured at 7.9s and 47.0s on two reads an hour apart, and the 30-second
    #: `TIMEOUT` that suits every other single read in this module turned the
    #: second of those into `available: false`. The degradation was correct and
    #: the ceiling was wrong: a filter that works and is merely slow should not
    #: be published as an API that did not answer.
    timeout: float = TIMEOUT
    #: Tries before the count is recorded as unavailable. One attempt against an
    #: erratically slow endpoint is a coin toss, and this one is cheap to repeat.
    attempts: int = 3


#: The filters this module asks for, each one proven before its share is used.
FILTERS: tuple[Filter, ...] = (
    Filter(
        name="x402_supported",
        params={"x402_supported": "true"},
        predicate=lambda r: bool(r.get("x402_supported")),
        complement={"x402_supported": "false"},
    ),
    Filter(
        name="with_feedback",
        params={"min_feedbacks": MIN_FEEDBACKS_CEILING},
        predicate=lambda r: int(r.get("total_feedbacks") or 0) >= MIN_FEEDBACKS_CEILING,
        timeout=120.0,
        # No complement: `max_feedbacks` is not implemented, and inventing one
        # would land in IGNORED_PARAMS territory — an accepted parameter
        # answering with the population.
    ),
)


def _prove(
    f: Filter,
    rows: list[dict[str, Any]],
    total: int | None,
    baseline: int,
    complement_total: int | None = None,
) -> dict[str, Any]:
    """Three checks over one filtered reading. Pure, so it is testable offline.

    Publishes `total` and `share` only if every applicable check passes. When
    one fails the two keys are **absent from the dict**, not zero and not None:
    a reader who does not check `applied` must not find a number there at all.

    That absence is what an exception would otherwise be for, and this file
    started with one — a `FilterIgnored` sibling to `ForeignChain`, on the
    argument that a caller who forgets to check `applied` should meet a raise
    rather than a share. It was written, documented, and never raised from
    anywhere, which `tests/test_no_dead_definitions.py` found and was right to.
    The reasoning survives and the class does not: `ForeignChain` raises because
    a wrong-chain page invalidates the *total beside it* and there is nothing
    partial to return, whereas a refused filter has a real payload to hand back
    — the baseline, the rows, and the reason. Omitting two keys from that is a
    stronger guarantee than an exception, because it cannot be caught and
    ignored.

    `applied` is deliberately a different word from `available`. `available:
    false` means 8004scan did not answer; `applied: false` means it answered and
    did not listen. Both refuse to publish, and conflating them would send a
    reader to check their network over a finding about the API's semantics.
    """
    checked = len(rows)
    satisfying = sum(1 for r in rows if f.predicate(r))
    out: dict[str, Any] = {
        "name": f.name,
        "params": dict(f.params),
        "baseline": baseline,
        "rows_checked": checked,
        "rows_satisfying": satisfying,
    }

    if total is None:
        return {**out, "applied": False, "reason": "8004scan returned no total for this filter"}

    out["differs_from_baseline"] = total != baseline

    if total == baseline:
        # The one honest ambiguity in this function, and it resolves against
        # publishing. A filter matching every agent on the chain would look
        # exactly like a filter that was ignored, and nothing in the response
        # separates the two. Refusing costs us a true share in a case that has
        # never occurred; publishing costs us the population mislabelled, which
        # is the defect this module is named after.
        return {
            **out,
            "applied": False,
            "reason": (
                f"8004scan returned {total:,} for {f.name}, which is the unfiltered "
                f"population. Either the filter was accepted and not applied, or it "
                f"matched every agent on the chain — the response does not "
                f"distinguish those, so no share is published."
            ),
        }

    if checked and satisfying != checked:
        return {
            **out,
            "applied": False,
            "reason": (
                f"{checked - satisfying} of {checked} rows returned for {f.name} do not "
                f"satisfy it. The total beside them describes some other set."
            ),
        }

    if complement_total is not None:
        out["complement_total"] = complement_total
        miss = (total + complement_total) - baseline
        out["sum_vs_baseline"] = miss
        out["growth_tolerance"] = DRIFT_TOLERANCE
        out["within_tolerance"] = abs(miss) <= DRIFT_TOLERANCE
        if not out["within_tolerance"]:
            return {
                **out,
                "applied": False,
                # Named, because the two causes call for opposite responses and
                # a bare "out of tolerance" cannot tell them apart: an ignored
                # filter is somebody else's API to fix, a table that moved is
                # ours to re-read.
                #
                # The discriminator is not the size of the miss. That was the
                # first attempt and it is wrong — an ignored *complement*
                # returns the population, so the pair misses by the filtered
                # total, which for x402 is 66,489 against a baseline of 284,712
                # and looks like nothing in particular. What is unambiguous is
                # that one of the two sides came back equal to the population,
                # which is a thing to test for rather than infer.
                "reason": (
                    f"{total:,} + {complement_total:,} misses the population of "
                    f"{baseline:,} by {miss:,}, over the {DRIFT_TOLERANCE:,} allowed for "
                    + (
                        "growth. One of the pair came back equal to the population "
                        "itself, so that side's filter was ignored."
                        if baseline in (total, complement_total)
                        else "growth between the three reads."
                    )
                ),
            }

    return {
        **out,
        "applied": True,
        "total": total,
        "share": round(total / baseline, 5) if baseline else None,
        "reason": None,
    }


def proven_count(
    f: Filter,
    baseline: int,
    chain_id: int = BSC_CHAIN_ID,
    t: Tier | None = None,
) -> dict[str, Any]:
    """One filtered count, fetched and proven. Two requests where a complement exists.

    An unreachable API produces `available: false` with the reason, never a zero
    — `vetting/read.py`'s rule, which the rest of this module already follows.
    """
    t = t or tier()

    def _page(extra: dict[str, Any], limit: int) -> tuple[list[dict[str, Any]], int | None]:
        params = {**_params(t, chain_id, limit, 0, False), **extra}
        last: Exception | None = None
        for attempt in range(f.attempts):
            try:
                with httpx.Client(
                    timeout=f.timeout, follow_redirects=True, headers=t.headers
                ) as client:
                    response = client.get(f"{t.base}/agents", params=params)
                    response.raise_for_status()
                    rows, total = _normalise(response.json())
            except ForeignChain:
                raise
            except Exception as error:  # noqa: BLE001 — retry, then give up
                last = error
                if attempt < f.attempts - 1:
                    time.sleep(1.5 * 2**attempt)
                continue
            _check_chain(rows, chain_id)
            return rows, total
        raise last if last else RuntimeError("no attempt was made")

    try:
        rows, total = _page(f.params, PROOF_ROWS)
        complement_total = None
        if f.complement is not None:
            # One row, not PROOF_ROWS: the complement is here to add back to the
            # population, and its own predicate is the negation of one already
            # checked. Paying for 25 rows to look at a number would be a request
            # spent on nothing.
            _, complement_total = _page(f.complement, 1)
    except Exception as error:  # noqa: BLE001 — any failure is "unavailable"
        return {
            "name": f.name,
            "available": False,
            "tier": t.name,
            "reason": f"8004scan did not answer for {f.name}: {type(error).__name__}: {error}",
        }

    return {"available": True, "tier": t.name, **_prove(f, rows, total, baseline, complement_total)}


def counts(chain_id: int = BSC_CHAIN_ID) -> dict[str, Any]:
    """Every share the census derives by walking, asked of the index directly.

    Four requests where the walk is 2,848 and two hours. What makes them
    publishable is not that they are cheap — a wrong number arrives just as fast
    — it is `proven_count`: each carries the rows that satisfy its own predicate
    and, where one exists, the complement that adds back to the population. A
    filter this API accepted and ignored yields `applied: false` and no share.

    Carried *alongside* the census rather than replacing it, for the reason this
    whole module exists: two readings that agree are evidence and two that
    disagree are a finding. They disagree. `registry_report._counts_cross_check`
    publishes the gap without resolving it.
    """
    t = tier()
    if t.name != "keyed":
        return {
            "available": False,
            "tier": t.name,
            "reason": f"the filtered counts are on the keyed tier only. Set {KEY_ENV}.",
        }

    baseline_read = population(chain_id)
    if not baseline_read.get("available"):
        return {
            "available": False,
            "tier": t.name,
            "reason": (
                "the unfiltered population is the denominator every filtered count is "
                f"proven against, and it did not answer: {baseline_read.get('reason')}"
            ),
        }

    baseline = int(baseline_read["population"])
    filters = {f.name: proven_count(f, baseline, chain_id, t) for f in FILTERS}

    return {
        "available": True,
        "tier": t.name,
        "chain_id": chain_id,
        "read_at": _read_at(),
        # Counted so the cost is legible beside the census's 2,848. One request
        # for the baseline, one per filter, one more per complement.
        "requests": 1 + sum(1 + (f.complement is not None) for f in FILTERS),
        "baseline": baseline,
        "filters": filters,
        "refused": sorted(n for n, c in filters.items() if not c.get("applied")),
        "note": (
            "Shares 8004scan reported, not shares we derived — each published only "
            "after its filter was shown to have actually applied."
        ),
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

#: How many pages are in flight at once.
#:
#: Held at 24 across two rate-limit regimes, and the second one is the
#: interesting evidence. When the keyed ceiling turned out to be 3,000 requests
#: a minute rather than the 600 this file assumed, the obvious move was to raise
#: this — five times the headroom, five times the workers. Measured instead:
#: 48 pages at 24 in flight lost none; the same 48 at 64 in flight lost 19 and
#: took longer in wall-clock. Concurrency is not the free variable here. Every
#: extra worker joins a queue in front of a server whose per-request latency is
#: already the binding constraint, and deepening that queue converts slow pages
#: into timed-out ones.
#:
#: So the pro key bought no census speed at all, and the honest place to record
#: that is next to the constant somebody will otherwise raise again.
CENSUS_CONCURRENCY = 24

#: Attempts per page before the page is recorded as a hole. A page that never
#: arrives must subtract from `counted` and clear `complete`, never quietly
#: shrink the totals.
#:
#: Five, not three, and the backoff is exponential rather than linear, because
#: the first full BSC run lost 762 of 2,784 pages — 76,200 agents — and the
#: cause was not what the retry was built for. There were no 429s and no
#: throttling: 96 sampled requests at this concurrency spent all but a fraction
#: of the minute's allowance unused and still timed out 24 times. 8004scan's
#: `/agents` is simply slow, and slow in proportion to offset — re-measured
#: since at p50 4.1s over the first 4,800 rows against p50 39.1s at offset
#: 200,000. Three tries 1.5s apart against a 30-second ceiling is not a retry
#: policy for that; it is the same request three times inside one slow window.
#:
#: With five attempts and exponential backoff, 48 pages at each end of the table
#: lost **none**. That is what makes the walk publishable despite taking two
#: hours: it is slow, and it is complete.
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
        # The reason is spelled out rather than computed, and that is a
        # correction. This used to divide the population by the tier's rate and
        # print the hours — "4.6 hours for BSC", back when the anonymous tier
        # was believed to answer 10 requests a minute. It answers 180. The same
        # arithmetic on the true number prints "0.3 hours", which turns a
        # refusal into an advertisement: a reader is told a census is twenty
        # minutes away and that we declined to take it. Nothing would have
        # failed. A refusal whose stated reason evaporates when a constant is
        # corrected was never the real reason, and the real one does not
        # involve time at all.
        return {
            "available": False,
            "tier": t.name,
            "reason": (
                "a census needs the keyed tier, and not because of the rate. The "
                "anonymous endpoint takes a different chain parameter, answers in a "
                "different envelope, and its `total` has never been checked against "
                "anything we can verify — so a count taken there would be a claim "
                f"about a population this tier cannot support. Set {KEY_ENV}."
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
        "read_at": _read_at(),
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
            "Every agent the index holds for this chain, counted — not sampled, so "
            "no confidence interval. Whether the index itself is complete is a "
            "different question, answered by our own count beside it."
        ),
    }


def census(chain_id: int = BSC_CHAIN_ID, page_size: int = MAX_LIMIT) -> dict[str, Any]:
    """Count every agent the index holds for a chain. Needs the keyed tier.

    **Sixty to a hundred and thirty minutes** for BSC's 278,000, depending on
    the afternoon — 2,848 pages whose cost rises with offset. This docstring
    said "ten minutes" for the life of the file, which was the request count
    divided by the rate limit and never a measurement of anything.

    Most of what it derives can now be asked for directly: see `counts()`, which
    answers `x402_supported` and `with_feedback` in one request each and proves
    the filter applied. What has no substitute is the rest — distinct owners,
    distinct descriptions, the protocol histogram — because 8004scan implements
    no filter for any of them. That, and not speed, is why this is kept.

    Refuses on the anonymous tier rather than silently returning a smaller
    reading under the same key names — a caller reading `counted` must never be
    handed a number that counted a hundred rows.
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
            "Counted from the feedback table itself. Every row names the "
            "transaction that wrote it, so the count is checkable on chain."
        ),
    }


# ── the chain-wide ranking, and the proof that the sort applied ──────────────

LEADERBOARD_N = 10

BSC_TESTNET_CHAIN_ID = 97


#: Our four agents' names, for the collision check. Read from `cards` rather
#: than typed, so renaming an agent cannot leave this checking the old name.
def _our_agent_names() -> tuple[str, ...]:
    from misquote.registry import cards

    names = getattr(cards, "AGENT_NAMES", None)
    if names:
        return tuple(names)
    return ("Warden", "Grid", "Sentinel", "Router")


def _prove_sorted(key: str, rows: list[dict[str, Any]], unsorted_head: list[Any]) -> dict[str, Any]:
    """Did 8004scan actually order these, or hand back the default page?

    Two of its sort keys are accepted and ignored — `star_count` and
    `health_score` both answer with the newest-first page unchanged, which is a
    ranking that looks exactly like a ranking. So a leaderboard is not published
    because a sort parameter was sent. It is published when the values come back
    non-increasing **and** the head differs from the head the same query returns
    unsorted.

    Either check alone is insufficient. Monotonicity passes trivially when every
    value is zero, which describes most of this registry; a differing head could
    be the table having moved between two reads.

    Pure, so the whole decision is testable without a network.
    """
    values = [row.get(key) for row in rows]
    numeric = [float(v or 0) for v in values]
    monotone = all(a >= b for a, b in zip(numeric, numeric[1:], strict=False))
    head = [row.get("token_id") for row in rows]
    differs = head[: len(unsorted_head)] != unsorted_head[: len(head)]

    out = {
        "key": key,
        "monotone": monotone,
        "differs_from_unsorted_head": differs,
        "head_values": numeric[:3],
    }
    if not monotone:
        return {**out, "sorted": False, "reason": f"{key} came back rising: {numeric[:5]}"}
    if not differs:
        return {
            **out,
            "sorted": False,
            "reason": (
                f"sort_by={key} returned the same head as no sort at all, which is what "
                f"this API does with a sort key it does not implement — see IGNORED_SORTS."
            ),
        }
    return {**out, "sorted": True, "reason": None, "rows": rows}


def leaderboard(chain_id: int = BSC_CHAIN_ID, n: int = LEADERBOARD_N) -> dict[str, Any]:
    """The top of this registry by the index's own evidence, with the sort proven.

    Answers what a category page cannot: who is at the top of the whole chain,
    and what does the top look like? The answer is worth publishing partly
    because it is unflattering — the most-rated agents on BSC are celebrity-named
    cards, which is a fact about what feedback counts measure here.

    Three requests: one unsorted head to compare against, one per working sort.
    """
    t = tier()
    if t.name != "keyed":
        return {
            "available": False,
            "tier": t.name,
            "reason": f"ranked queries are on the keyed tier only. Set {KEY_ENV}.",
        }

    def _rows(extra: dict[str, Any]) -> list[dict[str, Any]]:
        params = {**_params(t, chain_id, n, 0, False), **extra}
        rows, _ = _normalise(_get("/agents", params, t))
        _check_chain(rows, chain_id)
        return rows

    try:
        baseline_rows = _rows({})
    except Exception as error:  # noqa: BLE001
        return {
            "available": False,
            "tier": t.name,
            "reason": f"8004scan did not answer the unsorted head: {type(error).__name__}: {error}",
        }

    unsorted_head = [r.get("token_id") for r in baseline_rows]
    by: dict[str, Any] = {}
    for key in ("total_score", "total_feedbacks"):
        try:
            rows = _rows({"sort_by": key, "sort_order": "desc"})
        except Exception as error:  # noqa: BLE001
            by[key] = {"sorted": False, "reason": f"{type(error).__name__}: {error}"}
            continue
        proof = _prove_sorted(key, rows, unsorted_head)
        if proof.pop("rows", None) is not None:
            proof["rows"] = [_scan_listing(r, f"sort_by={key}", t.base) for r in rows]
        by[key] = proof

    return {
        "available": True,
        "tier": t.name,
        "chain_id": chain_id,
        "read_at": _read_at(),
        "by": by,
        "note": (
            "8004scan's numbers and 8004scan's ordering. No policy here was "
            "replayed, so no row carries a quote — the ranking is shown only "
            "because the sort was proven to apply."
        ),
    }


def ours_as_indexed(owner_address: str, chain_id: int = BSC_TESTNET_CHAIN_ID) -> dict[str, Any]:
    """Our own four, as an index nobody here controls records them.

    `owner_address` is a parameter and not a constant, and that is the design
    rather than a convenience. The record on disk is `vetting/identity/97.json`;
    if the address queried here were a literal, this function would be checking
    a constant against a file free to disagree with it, and the "independent
    corroboration" would corroborate a hardcoded string.

    Two requests: the chain's population, so the owner filter can be proven, and
    the owner's page.
    """
    t = tier()
    if t.name != "keyed":
        return {
            "available": False,
            "tier": t.name,
            "reason": f"the owner filter is on the keyed tier only. Set {KEY_ENV}.",
        }

    owner = (owner_address or "").lower()
    if not owner:
        return {"available": False, "reason": "no owner address was given to look up"}

    try:
        base_rows, baseline = _normalise(_get("/agents", _params(t, chain_id, 1, 0, False), t))
        _check_chain(base_rows, chain_id)
        rows, total = _normalise(
            _get("/agents", {**_params(t, chain_id, 50, 0, False), "owner_address": owner}, t)
        )
        _check_chain(rows, chain_id)
    except Exception as error:  # noqa: BLE001
        return {
            "available": False,
            "tier": t.name,
            "reason": f"8004scan did not answer for {owner}: {type(error).__name__}: {error}",
        }

    owner_filter = Filter(
        name="owner_address",
        params={"owner_address": owner},
        predicate=lambda r: (r.get("owner_address") or "").lower() == owner,
    )
    proof = _prove(owner_filter, rows, total, int(baseline or 0))

    indexed = (rows[0].get("contract_address") or "").lower() if rows else ""
    return {
        "available": True,
        "tier": t.name,
        "chain_id": chain_id,
        "read_at": _read_at(),
        "owner": owner,
        "population": baseline,
        "filter_proof": proof,
        # Checked for the reason `population()` checks it: if the index and this
        # repository are reading different contracts, the comparison below is
        # meaningless rather than merely unflattering.
        "indexed_contract": indexed or None,
        "agents": [_scan_listing(r, f"owner_address={owner}", t.base) for r in rows],
        "note": (
            "Our four registrations, read back from an index we do not run. The "
            "artifact has always carried what we recorded ourselves; this is the same "
            "four agents according to somebody else."
        ),
    }


def name_collisions(
    names: tuple[str, ...] | None = None, chain_id: int = BSC_CHAIN_ID
) -> dict[str, Any]:
    """Who else on BSC mainnet is called what we called ours.

    Four requests, and the cheapest strong claim available here: `search=Warden`
    returns two other agents named Warden, owned by strangers. A marketplace
    whose users hire by name is quoting the wrong agent, and this is that
    demonstrated rather than asserted.

    Names are matched exactly rather than by the fuzzy `search`, so a collision
    means a collision and not a stem.
    """
    t = tier()
    if t.name != "keyed":
        return {
            "available": False,
            "tier": t.name,
            "reason": f"search is on the keyed tier only. Set {KEY_ENV}.",
        }

    out: dict[str, Any] = {}
    for name in names or _our_agent_names():
        try:
            rows, total = _normalise(
                _get("/agents", {**_params(t, chain_id, 25, 0, False), "search": name}, t)
            )
            _check_chain(rows, chain_id)
        except Exception as error:  # noqa: BLE001
            out[name] = {"available": False, "reason": f"{type(error).__name__}: {error}"}
            continue

        exact = [r for r in rows if (r.get("name") or "").strip().lower() == name.lower()]
        out[name] = {
            "available": True,
            "search_returned": total,
            "exactly_this_name": len(exact),
            "owners": sorted({(r.get("owner_address") or "").lower() for r in exact}),
            "agents": [_scan_listing(r, name, t.base) for r in exact],
        }

    return {
        "available": True,
        "tier": t.name,
        "chain_id": chain_id,
        "read_at": _read_at(),
        "names": out,
        "note": (
            "A name is not an identity: these carry our names and are owned by "
            "addresses that are not ours. Every row here is keyed by token id."
        ),
    }


# ── the four categories, filled with agents that are actually on BSC ─────────

#: What to search 8004scan for, per marketplace category.
#:
#: Keyed by the category names `index.json` publishes — *Rebalancing · Market
#: making · Health · Yield* — and `test_the_needles_cover_the_categories_the_
#: index_publishes` holds the two in step. `apps/web/src/lib/categories.ts`
#: makes the argument for why the taxonomy is derived rather than declared, and
#: this does not redeclare it: what is new here is which *words* find agents in
#: each category on somebody else's index, which is a fact about 8004scan's
#: corpus and lives nowhere else.
#:
#: Each needle was run against chain 56 before being written down. `grid`
#: returns 12 agents and `market maker` returns 4, which is thin — and thin is
#: published rather than padded with a broader needle that would fill the page
#: with agents that are not grid traders.
CATEGORY_NEEDLES: dict[str, tuple[str, ...]] = {
    "Rebalancing": ("rebalance", "lp range", "liquidity range", "reposition"),
    "Market making": ("grid", "market maker", "market making", "spread"),
    "Health": ("health factor", "liquidation", "collateral ratio", "de-risk"),
    "Yield": ("yield", "apr", "lending", "venus"),
}

#: How many agents a category publishes.
CATEGORY_LIMIT = 8

#: How many of those one address may own.
#:
#: A rendering rule, not a judgement about quality, and the distinction matters
#: because this file refuses to make the second kind. Measured: ranked purely by
#: the index's evidence, all eight published Rebalancing agents came from one
#: address — `BORT Yield Weaver #10907`, `BORT Liquidity Bloom #10966` and six
#: more, a batch of rarity-tiered cards sharing a description template, an
#: identical score of about 12.09, and zero feedbacks between them.
#:
#: Nothing in that is dishonest and nothing about it is useful either. It is the
#: same defect `_listing`'s "every `step`-th, not the first N" comment describes:
#: a ranking that is correct and clusters, presented as a survey. `LISTING_LIMIT`
#: bounds how many rows are shown for the same reason.
#:
#: What is suppressed is counted and published, because a category thinned by
#: this rule and a category that is genuinely thin must not look alike.
CATEGORY_MAX_PER_OWNER = 2

#: Rows requested per needle. Above `CATEGORY_LIMIT` on purpose: `search` is
#: fuzzy and a share of every page is dropped by `_matches`, so asking for
#: exactly the number wanted would return fewer.
CATEGORY_FETCH = 25

CATEGORY_TIMEOUT = 45.0
CATEGORY_ATTEMPTS = 3

#: The keys a third-party row from 8004scan may carry.
#:
#: **Deliberately not `registry_report.LISTING_KEYS`, and that whitelist is not
#: widened.** The two encode different claims and a single list cannot hold both.
#:
#: `LISTING_KEYS` says: this is what a registration claims and what *our own*
#: reading of it found, and it carries no performance figure of any kind,
#: because we do not have this agent's policy and cannot replay it. Widening it
#: to admit a score would delete that guarantee for the on-chain listings too.
#:
#: This says something else: here is what a *named third-party index* publishes
#: about this agent. The numbers are 8004scan's, they are not ours, and they are
#: prefixed `scan_` so that no grep of any artifact can mistake one for a figure
#: this project measured — and so that the substring blocklist in
#: `tests/web/test_third_party_listings.py` still fires if one of these is ever
#: moved under `identity.agents`.
#:
#: `attributed_to` is mandatory on every row. A third-party number with no
#: source on the same row is a number this site is asserting.
SCAN_LISTING_KEYS = frozenset(
    {
        "token_id",
        "name",
        "description",
        "owner_address",
        "created_at",
        "attributed_to",
        "matched_on",
        "x402_supported",
        "supported_protocols",
        "scan_total_score",
        "scan_total_feedbacks",
        "scan_average_score",
        "scan_rank",
        "scan_network_rank",
    }
)


def _matches(row: dict[str, Any], needle: str) -> bool:
    """Does this row actually contain the word it was returned for?

    `search` is fuzzy, and the evidence is unambiguous: `search=liquidity` and
    `search=liquidation` both return 311 agents on BSC with an identical head.
    It is matching a stem, so a category built from `liquidation` would list
    every agent whose description says *liquidity* — and the first two rows of
    that page are `sus.agent` and `ChainIntel Ai`.

    So the needle is checked against the text rather than trusted to the query.
    A row that does not contain it is dropped and counted as dropped, because a
    quiet drop and a category that is genuinely thin look identical.
    """
    haystack = f"{row.get('name') or ''} {row.get('description') or ''}".lower()
    return needle.lower() in haystack


def _scan_listing(row: dict[str, Any], needle: str, attributed_to: str) -> dict[str, Any]:
    """One third-party agent, as an index describes it and nobody else.

    Every number here is 8004scan's, and every one of them is prefixed so it
    cannot be read as ours. There is no quote and there will not be one: our
    four agents carry a P25-P75 band replayed over real history, and a stranger's
    agent gets none, because we do not have its policy. Inventing one, or
    borrowing a rating, is exactly the misquote this project is named after.
    """
    return {
        "token_id": str(row.get("token_id") or ""),
        "name": row.get("name"),
        "description": row.get("description"),
        "owner_address": (row.get("owner_address") or "").lower() or None,
        "created_at": row.get("created_at"),
        "matched_on": needle,
        "attributed_to": attributed_to,
        "x402_supported": bool(row.get("x402_supported")),
        "supported_protocols": list(row.get("supported_protocols") or ()),
        "scan_total_score": float(row.get("total_score") or 0.0),
        "scan_total_feedbacks": int(row.get("total_feedbacks") or 0),
        "scan_average_score": float(row.get("average_score") or 0.0),
        "scan_rank": row.get("rank"),
        "scan_network_rank": row.get("network_rank"),
    }


def category_agents(
    category: str,
    chain_id: int = BSC_CHAIN_ID,
    limit: int = CATEGORY_LIMIT,
) -> dict[str, Any]:
    """Real BSC agents for one marketplace category, ranked by the index's evidence.

    One request per needle, about a second each. Rows that do not contain their
    own needle are dropped by `_matches` and counted; what survives is
    deduplicated by token id and ordered by how much evidence 8004scan holds for
    it — feedback count first, then score, then age.

    **The ranking is done here, over rows this process is holding.** It does not
    use `sort_by`, and that is deliberate rather than incidental: a server-side
    ordering has to be proven to have applied, because two of 8004scan's sort
    keys are accepted and ignored. A sort over rows already in memory needs no
    such proof — the values are right there. `leaderboard()` is where the
    server's ordering is relied on, and it proves it.
    """
    needles = CATEGORY_NEEDLES.get(category)
    if not needles:
        return {
            "available": False,
            "category": category,
            "reason": (
                f"no search needles are recorded for {category!r}. The four this "
                f"marketplace publishes are {sorted(CATEGORY_NEEDLES)}."
            ),
        }

    t = tier()
    if t.name != "keyed":
        return {
            "available": False,
            "category": category,
            "tier": t.name,
            "reason": f"category search is on the keyed tier only. Set {KEY_ENV}.",
        }

    attributed_to = t.base
    found: dict[str, dict[str, Any]] = {}
    dropped = 0
    searched: dict[str, Any] = {}

    for needle in needles:
        params = {**_params(t, chain_id, CATEGORY_FETCH, 0, False), "search": needle}
        rows: list[dict[str, Any]] | None = None
        for attempt in range(CATEGORY_ATTEMPTS):
            try:
                with httpx.Client(
                    timeout=CATEGORY_TIMEOUT, follow_redirects=True, headers=t.headers
                ) as client:
                    response = client.get(f"{t.base}/agents", params=params)
                    response.raise_for_status()
                    rows, total = _normalise(response.json())
                _check_chain(rows, chain_id)
                searched[needle] = {"returned": len(rows), "total": total}
                break
            except ForeignChain:
                raise
            except Exception as error:  # noqa: BLE001
                if attempt == CATEGORY_ATTEMPTS - 1:
                    # One needle failing is not the category failing. Recorded
                    # so a thin category can be told from a partly-unread one.
                    searched[needle] = {"error": f"{type(error).__name__}: {error}"}
                    rows = None
                else:
                    time.sleep(1.5 * 2**attempt)

        for row in rows or ():
            if not _matches(row, needle):
                dropped += 1
                continue
            listing = _scan_listing(row, needle, attributed_to)
            if listing["token_id"] and listing["token_id"] not in found:
                found[listing["token_id"]] = listing

    ranked = sorted(
        found.values(),
        key=lambda r: (-r["scan_total_feedbacks"], -r["scan_total_score"], r["created_at"] or ""),
    )

    shown: list[dict[str, Any]] = []
    per_owner: Counter[str] = Counter()
    crowded_out = 0
    for row in ranked:
        owner = row.get("owner_address") or ""
        if owner and per_owner[owner] >= CATEGORY_MAX_PER_OWNER:
            crowded_out += 1
            continue
        per_owner[owner] += 1
        shown.append(row)
        if len(shown) >= limit:
            break

    return {
        "available": True,
        "tier": t.name,
        "chain_id": chain_id,
        "category": category,
        "read_at": _read_at(),
        "needles": list(needles),
        "searched": searched,
        "matched": len(found),
        "dropped_not_matching": dropped,
        "crowded_out_by_owner_cap": crowded_out,
        "max_per_owner": CATEGORY_MAX_PER_OWNER,
        "distinct_owners_matched": len({r.get("owner_address") for r in found.values()}),
        "agents": shown,
        "attributed_to": attributed_to,
        "note": (
            "Agents 8004scan holds for this category, ranked on their own evidence. "
            "Every number on a row is theirs; none of these policies was replayed "
            "here, so none carries a quote."
        ),
    }


def categories(chain_id: int = BSC_CHAIN_ID) -> dict[str, Any]:
    """All four, each answering for itself."""
    return {name: category_agents(name, chain_id) for name in CATEGORY_NEEDLES}


# ── the feedback table: one walk, two products ────────────────────────────────

#: How many /feedbacks pages are in flight at once.
#:
#: Eight rather than the census's 24, and the difference is the table rather
#: than caution. /feedbacks is 11,717 rows on BSC — 118 pages, every one of them
#: at a shallow offset, answering in one to nine seconds. The census's queue
#: exists because /agents at offset 200,000 takes forty; nothing here goes deep
#: enough to need it, and eight finishes in minutes.
FEEDBACK_CONCURRENCY = 8

FEEDBACK_ATTEMPTS = 3

FEEDBACK_TIMEOUT = 60.0

#: The largest `feedback_uri` this module will decode.
#:
#: Per row, and there are 11,717 of them, which is what makes it a different
#: cap from `erc8004.MAX_CARD_BYTES` — that one guards a few hundred cards
#: fetched one at a time and can afford 256KB each. 16KB is comfortably above
#: every method blob observed and far below what an adversarial row could cost
#: multiplied by the table.
MAX_FEEDBACK_URI_BYTES = 16 * 1024

_DATA_URI_PREFIXES = ("data:application/json;base64,", "data:application/json,")


def _decode_feedback_uri(uri: str) -> tuple[dict[str, Any] | None, str]:
    """Decode a `data:` feedback URI. Returns `(payload, reason-it-failed)`.

    **Nothing here fetches anything, ever, and that is the whole design.**

    `erc8004._assert_fetchable` exists because a registry card's URI is chosen
    by a stranger, and following it turns a read into a server-side request
    forgery primitive aimed at whatever network this runs on. A feedback URI is
    that same primitive multiplied by 11,717: one attacker-chosen URL per row,
    walked automatically, on a schedule, by a build. The guards that make a
    card fetch defensible do not survive that multiplication.

    So a scheme other than `data:` is not fetched carefully — it is counted as
    undecodable and the reason says which scheme it was. The count is the
    finding: on a 1,500-row sample, 1,493 URIs decoded to nothing at all and the
    seven that did came from a single prober.
    """
    if not uri:
        return None, "no feedback_uri"
    if not uri.startswith("data:"):
        scheme = uri.split(":", 1)[0][:12] if ":" in uri else "no scheme"
        return None, f"not a data: URI ({scheme})"
    if len(uri) > MAX_FEEDBACK_URI_BYTES:
        return None, f"over the {MAX_FEEDBACK_URI_BYTES}-byte cap"
    prefix = next((p for p in _DATA_URI_PREFIXES if uri.startswith(p)), None)
    if prefix is None:
        return None, "a data: URI, but not JSON"
    body = uri[len(prefix) :]
    try:
        raw = base64.b64decode(body, validate=True) if "base64" in prefix else body.encode()
    except (ValueError, binascii.Error):
        return None, "not base64"
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None, "not JSON"
    if not isinstance(payload, dict):
        return None, f"JSON, but a {type(payload).__name__} rather than an object"
    return payload, ""


class _FeedbackGraph:
    """Running counts over feedback rows, holding no rows.

    Same rule as `_Signals`, for the same reason: 11,717 records are read and
    none of them are needed afterwards. What is kept is counters, two identity
    sets bounded by the distinct counts, and a per-agent index whose size is
    bounded by the number of agents anyone has ever rated — which the registry
    itself says is a few hundred.
    """

    #: How many transaction hashes are retained per agent. The point of keeping
    #: any is that a reader can check one; keeping every hash for an agent with
    #: 108 feedbacks would inflate the artifact to prove the same thing.
    HASHES_PER_AGENT = 3

    #: How many rater addresses are retained per agent, beside the full count.
    #:
    #: Both, because they answer different questions and only one of them is
    #: bounded. "How many distinct addresses rated this agent" is the number a
    #: hiring decision turns on — three raters and thirty feedbacks is a
    #: different object from thirty raters — and it must be exact. The addresses
    #: themselves are there so a reader can go and look, and five is enough to
    #: look. Keeping all of them cost 352KB across 547 agents, which is the
    #: `LISTING_LIMIT` lesson repeating: an artifact this page fetches
    #: client-side cannot carry every row it counted.
    RATERS_PER_AGENT = 5

    def __init__(self) -> None:
        self.rows = 0
        self.anchored = 0
        self.with_comment = 0
        self.revoked = 0
        self.uris_decoded = 0
        self.declaring_a_method = 0
        self.declaring_known_defects = 0
        self.raters: Counter[str] = Counter()
        self.rated: Counter[str] = Counter()
        self.tags: Counter[str] = Counter()
        self.methods: Counter[str] = Counter()
        self.decode_failures: Counter[str] = Counter()
        self.parse_status: Counter[str] = Counter()
        self.by_agent: dict[str, dict[str, Any]] = {}

    def add(self, rows: list[dict[str, Any]]) -> None:
        for r in rows:
            self.rows += 1
            if r.get("transaction_hash"):
                self.anchored += 1
            if (r.get("comment") or "").strip():
                self.with_comment += 1
            if r.get("is_revoked"):
                self.revoked += 1
            self.parse_status[str((r.get("parse_status") or {}).get("status") or "none")] += 1

            rater = (r.get("user_address") or (r.get("user") or {}).get("address") or "").lower()
            if rater:
                self.raters[rater] += 1

            for tag in (r.get("tag1"), r.get("tag2")):
                if tag:
                    self.tags[str(tag)] += 1

            payload, failure = _decode_feedback_uri(r.get("feedback_uri") or "")
            method: dict[str, Any] = {}
            if payload is None:
                self.decode_failures[failure] += 1
            else:
                self.uris_decoded += 1
                method = payload.get("method") if isinstance(payload.get("method"), dict) else {}
                if method:
                    self.declaring_a_method += 1
                    self.methods[str(method.get("measuredBy") or "unnamed")] += 1
                    if method.get("knownDefects"):
                        self.declaring_known_defects += 1

            # The join, and it costs nothing: every row embeds the agent it
            # rates. Without this the uuid on the row would have to be resolved
            # against a second full /agents walk, because 8004scan publishes no
            # per-agent endpoint and the uuid is not the token id.
            agent = r.get("agent") or {}
            token_id = str(agent.get("token_id") or "")
            if not token_id:
                continue
            self.rated[token_id] += 1
            entry = self.by_agent.setdefault(
                token_id,
                {
                    "token_id": token_id,
                    "name": agent.get("name"),
                    "rows": 0,
                    "distinct_raters": 0,
                    "raters": [],
                    "tags": {},
                    "transaction_hashes": [],
                    "declared_methods": [],
                    "latest_block": None,
                },
            )
            entry["rows"] += 1
            if rater:
                seen = entry.setdefault("_raters", set())
                if rater not in seen:
                    seen.add(rater)
                    entry["distinct_raters"] = len(seen)
                    if len(entry["raters"]) < self.RATERS_PER_AGENT:
                        entry["raters"].append(rater)
            for tag in (r.get("tag1"), r.get("tag2")):
                if tag:
                    entry["tags"][str(tag)] = entry["tags"].get(str(tag), 0) + 1
            tx = r.get("transaction_hash")
            if tx and len(entry["transaction_hashes"]) < self.HASHES_PER_AGENT:
                entry["transaction_hashes"].append(tx)
            block = r.get("block_number")
            if block is not None:
                entry["latest_block"] = max(entry["latest_block"] or 0, int(block))
            if method and method not in entry["declared_methods"]:
                entry["declared_methods"].append(method)

    #: Tags kept per agent. The histogram is one platform's fixed vocabulary
    #: repeated across every row it wrote, so the long tail is the same six
    #: words again rather than information.
    TAGS_PER_AGENT = 6

    def agents(self) -> dict[str, dict[str, Any]]:
        """The per-agent index, with the accumulator's scratch set dropped.

        `_raters` is a set used to keep `distinct_raters` exact while the walk
        runs. It is not JSON-serialisable and it is not the reader's business,
        so it never leaves this method.
        """
        return {
            token_id: {
                **{k: v for k, v in entry.items() if not k.startswith("_") and k != "tags"},
                "tags": dict(
                    sorted(entry["tags"].items(), key=lambda kv: -kv[1])[: self.TAGS_PER_AGENT]
                ),
            }
            for token_id, entry in self.by_agent.items()
        }

    def as_dict(self) -> dict[str, Any]:
        top = self.raters.most_common(5)
        return {
            "distinct_raters": len(self.raters),
            "distinct_rated_agents": len(self.rated),
            "anchored": self.anchored,
            "with_comment": self.with_comment,
            "revoked": self.revoked,
            "uris_decoded": self.uris_decoded,
            "declaring_a_method": self.declaring_a_method,
            "declaring_known_defects": self.declaring_known_defects,
            "top_rater_rows": top[0][1] if top else 0,
            "top_rater_share": round(top[0][1] / self.rows, 5) if top and self.rows else None,
            "top_five_rater_share": (
                round(sum(n for _, n in top) / self.rows, 5) if top and self.rows else None
            ),
            "tags": dict(self.tags.most_common(20)),
            "methods": dict(self.methods.most_common(10)),
            "decode_failures": dict(self.decode_failures.most_common()),
            "parse_status": dict(self.parse_status.most_common()),
        }


async def _feedback_walk(chain_id: int) -> dict[str, Any]:
    t = tier()
    if t.name != "keyed":
        return {
            "available": False,
            "tier": t.name,
            "reason": f"/feedbacks is on the keyed tier only. Set {KEY_ENV}.",
        }

    graph = _FeedbackGraph()
    failed: dict[int, str] = {}
    lock = asyncio.Lock()

    async with httpx.AsyncClient(
        timeout=FEEDBACK_TIMEOUT, headers=t.headers, follow_redirects=True
    ) as c:

        async def page(offset: int) -> None:
            params = {"chain_id": chain_id, "limit": MAX_LIMIT, "offset": offset}
            for attempt in range(FEEDBACK_ATTEMPTS):
                try:
                    r = await c.get(f"{t.base}/feedbacks", params=params)
                    r.raise_for_status()
                    rows, _ = _normalise(r.json())
                    _check_chain(rows, chain_id)
                except ForeignChain:
                    raise
                except Exception as error:  # noqa: BLE001
                    if attempt == FEEDBACK_ATTEMPTS - 1:
                        async with lock:
                            failed[offset] = f"{type(error).__name__}: {error}"
                        return
                    await asyncio.sleep(1.5 * 2**attempt)
                    continue
                async with lock:
                    failed.pop(offset, None)
                    graph.add(rows)
                return

        try:
            head = await c.get(f"{t.base}/feedbacks", params={"chain_id": chain_id, "limit": 1})
            head.raise_for_status()
            first, total = _normalise(head.json())
            _check_chain(first, chain_id)
        except Exception as error:  # noqa: BLE001
            return {
                "available": False,
                "tier": t.name,
                "reason": f"8004scan /feedbacks did not answer: {type(error).__name__}: {error}",
            }

        if total is None:
            return {"available": False, "tier": t.name, "reason": "8004scan returned no total"}

        semaphore = asyncio.Semaphore(FEEDBACK_CONCURRENCY)

        async def guarded(offset: int) -> None:
            async with semaphore:
                await page(offset)

        outcomes = await asyncio.gather(
            *(guarded(o) for o in range(0, int(total), MAX_LIMIT)), return_exceptions=True
        )
        for outcome in outcomes:
            if isinstance(outcome, ForeignChain):
                return {"available": False, "tier": t.name, "reason": str(outcome)}
            if isinstance(outcome, BaseException):
                raise outcome

    return {
        "available": True,
        "tier": t.name,
        "chain_id": chain_id,
        "read_at": _read_at(),
        # Both, always. Every share below divides by `rows` — what was actually
        # walked — and never by `total_reported`, so an incomplete walk reports
        # honest shares of a smaller reading rather than shares of a number it
        # did not reach. Publishing the pair is what lets a reader see coverage
        # instead of taking it on trust.
        "rows": graph.rows,
        "total_reported": int(total),
        "pages_failed": len(failed),
        "failure_reasons": dict(Counter(failed.values()).most_common()),
        "complete": not failed and graph.rows >= int(total),
        **graph.as_dict(),
        "by_agent": graph.agents(),
        "note": (
            "Who does the rating, counted from the feedback table itself — walked, "
            "not sampled, so no confidence interval."
        ),
    }


def feedback_graph(chain_id: int = BSC_CHAIN_ID) -> dict[str, Any]:
    """Walk every feedback the index holds for a chain. One pass, two products.

    **(a)** An aggregate about the registry's reputation layer: how many
    addresses produced it, how concentrated it is, how many rows carry a comment
    or a declared measurement method, and what 8004scan's own row-level parser
    says about its own data.

    **(b)** A per-agent index keyed by token id, because every row embeds the
    agent it rates. That is the half a marketplace can actually use: a card can
    say *fourteen feedbacks from three addresses, here are the transactions*
    rather than showing a star.

    About 118 pages and a few minutes for BSC, all at shallow offsets — this
    table does not have /agents' deep-offset pathology.
    """
    return asyncio.run(_feedback_walk(chain_id))


def stats() -> dict[str, Any]:
    """The platform's own cross-chain totals, for context only.

    Explicitly not comparable to our BSC count — it spans every chain 8004scan
    indexes. Carried because `daily_new_agents` is the number that makes the
    population figure legible: a registry growing by five figures a day is a
    different object from one that grew to that size over a year.

    Pinned to the anonymous base whatever tier is configured: `/stats` exists
    only under `/public`, and the keyed base answers it `404 Not Found`.
    """
    anonymous = _anonymous_tier()
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
