"""Reading BSC: RPC selection, retry policy, and decoding pool events.

Two things are ported rather than invented, because both encode hard-won
knowledge about how public endpoints actually misbehave.

From PolyLambda's `execution/testnet_chain.py`: the retry classifier. Transient
failures — rate limits, gateway timeouts, connection resets — are retried with
exponential backoff. Deterministic failures are not in that list, so **a revert
raises immediately and is never retried.** Retrying a revert wastes the budget
and, worse, teaches you to ignore it.

From Mission Control's `api/onchain.py`: the endpoint fallback chain. Public BSC
endpoints rate-limit bursts and occasionally answer for the wrong chain, so the
reader tries a list and keeps the first that answers with the chain id it was
asked for.
"""

from __future__ import annotations

import os
import random
import time
from collections.abc import Callable, Iterable
from typing import Any

from web3 import Web3

from misquote.core.types import Event

# Transient: worth another attempt. A contract revert is deliberately absent,
# and so is anything shaped like a malformed request — those are answers, not
# failures, and retrying them just delays the diagnosis.
_TRANSIENT = (
    "429",
    "403",
    "401",
    "too many",
    "rate limit",
    "timed out",
    "timeout",
    "connection",
    "reset",
    "remote end",
    "502",
    "503",
    "504",
    "bad gateway",
    "gateway time",
    "service unavailable",
    "temporarily",
    "limit exceeded",
)

# A range too large is not transient, but it is recoverable by asking for less —
# the backfill halves its chunk and retries rather than giving up.
_RANGE_TOO_LARGE = ("range too large", "block range", "more than", "query returned more than")

DEFAULT_ATTEMPTS = 6

# Measured 16 Aug 2026, one request at a time, against the target pool.
#
# **Answering for chain 56 does not mean serving logs.** Every bnbchain
# dataseed, both defibit hosts and ninicoin answer `eth_chainId` and
# `eth_blockNumber` in milliseconds and refuse *every* `eth_getLogs` with
# -32005 "limit exceeded" — including a one-block query filtered to an address
# that holds no logs. Not a width cap, not pruning: they do not serve logs.
#
# Of 22 public endpoints surveyed, three did: the two below and publicnode.
# Asked for the identical 2,000-block range they returned identical answers —
# 73 logs, same transaction hashes, same data, same order — so rotating between
# them cannot blend two histories into one tape.
#
# Two more serve logs under a declared width, and are listed here for the day
# the ones below stop: 1rpc.io/bnb caps at 50 blocks, bsc.blockrazor.xyz at 25.
# Both are under the 134 blocks/request that keeping level with the head costs
# at one request a minute, so neither can sustain a tail on its own.
#
# Both log-serving endpoints declare the same 5,000-block ceiling — see
# `backfill.DEFAULT_CHUNK`.
PUBLIC_RPCS: dict[int, tuple[str, ...]] = {
    56: (
        # Serves logs, and does the work: latency tracked the response size
        # (6.5s for 2,000 blocks, 15.8s for 5,000), which is what a node doing
        # the query looks like.
        "https://bsc.rpc.blxrbdn.com",
        # Serves logs, but answered in ~41s regardless of width — including the
        # refusal, where there was nothing to compute. That is a queue in front
        # of the node, not work, and 41s is uncomfortably close to the 60s poll.
        # Second, so the tail meets it only when the first is down.
        "https://rpc-bsc.48.club",
        # Serves logs, but 403s under burst — it answered, refused, and answered
        # again inside four minutes.
        "https://bsc-rpc.publicnode.com",
        # State reads only, kept because eth_call is all most callers want.
        "https://bsc-dataseed.bnbchain.org",
        "https://bsc-dataseed1.defibit.io",
    ),
    # Chapel. Surveyed 18 Aug 2026, and it is worse than mainnet: of eleven
    # public testnet endpoints, **exactly one** serves `eth_getLogs`. Every
    # `data-seed-prebsc-*` host, `bsc-testnet.bnbchain.org` and
    # `bsc-testnet-dataseed.bnbchain.org` answer for chain 97 and refuse every
    # log query with the same "limit exceeded" as their mainnet counterparts.
    #
    # Both endpoints this list used to hold were in that group — one unreachable,
    # one log-refusing — so `connect_all(97)` raised and the testnet burn-in
    # could never have started. The capability probe from P-11 is what turned
    # that from a silent failure into a refusal naming the reason.
    #
    # **One working endpoint is no redundancy.** A tail or a burn-in on Chapel
    # stops entirely if this host does, and rotation has nowhere to go. Recorded
    # rather than designed around: the fix is a keyed testnet RPC, and the
    # burn-in is a 24-hour run rather than a permanent service.
    97: (
        "https://bsc-prebsc-dataseed.bnbchain.org",  # the only one that serves logs
        # State reads only — kept so `connect(97)` (registry, write path) still
        # has somewhere to go when the one above is down.
        "https://data-seed-prebsc-1-s1.bnbchain.org:8545",
        "https://bsc-testnet.bnbchain.org",
    ),
}

# Event signatures. Computed rather than pasted, so a typo cannot silently match
# nothing — which would produce an empty tape that looks exactly like a quiet
# pool.
#
# **PancakeSwap's Swap event is not Uniswap's.** It carries two extra fields,
# `protocolFeesToken0` and `protocolFeesToken1`, so its topic0 is
# 0x19b47279... rather than Uniswap's 0xc42079f9.... Filtering on the Uniswap
# signature returns zero logs from a pool doing millions in volume, and nothing
# about that failure looks like a failure. Verified against the live target
# pool. (The core swap *math* is byte-identical to Uniswap's — it is only the
# event that differs.)
#
# The upside is substantial: the event states how much the protocol took on
# every swap, so the 34% cut in requirements-matrix P-1 is read from chain per
# swap rather than modelled from a governance parameter.
SWAP_SIG = "Swap(address,address,int256,int256,uint160,uint128,int24,uint128,uint128)"
MINT_SIG = "Mint(address,address,int24,int24,uint128,uint256,uint256)"
BURN_SIG = "Burn(address,int24,int24,uint128,uint256,uint256)"


def _topic(signature: str) -> str:
    """keccak of an event signature, as a 0x-prefixed lowercase hex string.

    `HexBytes.hex()` stopped including the 0x prefix in web3 7.x, and an
    unprefixed topic in a filter matches nothing without erroring.
    """
    return "0x" + Web3.keccak(text=signature).hex().removeprefix("0x").lower()


TOPIC_SWAP = _topic(SWAP_SIG)
TOPIC_MINT = _topic(MINT_SIG)
TOPIC_BURN = _topic(BURN_SIG)


class RangeTooLarge(RuntimeError):
    """The RPC refused the block span. Ask for less rather than giving up."""


def is_transient(error: Exception) -> bool:
    return any(marker in str(error).lower() for marker in _TRANSIENT)


def is_range_too_large(error: Exception) -> bool:
    return any(marker in str(error).lower() for marker in _RANGE_TOO_LARGE)


def rpc_retry(fn: Callable[..., Any], *args: Any, attempts: int = DEFAULT_ATTEMPTS, **kwargs: Any):
    """Call an RPC-touching thunk, retrying only what is worth retrying.

    Exponential backoff with jitter, capped at 20 seconds. A revert or any other
    deterministic error is not in `_TRANSIENT`, so it propagates on the first
    attempt.
    """
    last: Exception | None = None
    for attempt in range(max(1, attempts)):
        try:
            return fn(*args, **kwargs)
        except Exception as error:  # noqa: BLE001 — classified, then re-raised
            last = error
            if is_range_too_large(error):
                raise RangeTooLarge(str(error)) from error
            if attempt == attempts - 1 or not is_transient(error):
                raise
            time.sleep(min(2**attempt, 20) + random.random())
    raise last  # pragma: no cover — the loop returns or raises


def connect(chain_id: int, rpc_url: str | None = None, *, timeout: float = 20.0) -> Web3:
    """First endpoint that answers, and answers for the chain we asked about.

    An endpoint quietly serving a different chain is worse than one that is down:
    it produces a complete, internally consistent, entirely wrong tape.
    """
    env_key = "BSC_RPC_URL" if chain_id == 56 else "BSC_TESTNET_RPC_URL"
    candidates: Iterable[str] = (
        [rpc_url]
        if rpc_url
        else [url for url in (os.environ.get(env_key),) if url]
        + list(PUBLIC_RPCS.get(chain_id, ()))
    )

    from web3.middleware import ExtraDataToPOAMiddleware

    failures: list[str] = []
    for url in candidates:
        try:
            w3 = Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": timeout}))
            # BSC is proof-of-authority, so its blocks carry a 280-byte
            # `extraData` where the default validator expects 32. Without this,
            # `eth_getLogs` works fine and `eth_getBlock` raises — so the failure
            # appears only once you ask for a timestamp, which is well after the
            # point you would have thought the connection was healthy.
            w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
            actual = w3.eth.chain_id
            if actual == chain_id:
                return w3
            failures.append(f"{url}: serves chain {actual}, not {chain_id}")
        except Exception as error:  # noqa: BLE001
            failures.append(f"{url}: {type(error).__name__}")
    raise RuntimeError(f"no usable RPC for chain {chain_id}\n  " + "\n  ".join(failures))


# Far enough behind the tip that an unsettled block is never the reason a probe
# fails, close enough that no endpoint can call it history.
_PROBE_DEPTH = 20

# An address that holds no logs, so a healthy node answers `[]` immediately.
_PROBE_ADDRESS = "0x0000000000000000000000000000000000000000"


def serves_logs(w3: Web3) -> bool:
    """Will this endpoint answer an `eth_getLogs` at all?

    One block, filtered to an address with no logs. A node that serves logs
    returns `[]` in a few milliseconds; a node that does not refuses, and the
    refusal is the answer we came for.

    The cheapness is only sound because the refusal was measured **not** to
    depend on the response. The hosts that refuse, refuse this exact query too —
    empty, one block, no matches. Had they been refusing on result size instead,
    an empty probe is the one query they would gladly serve, every one of them
    would have passed, and this would be a check that cannot fail. That is the
    same shape as V-11, and it is worth the two extra requests it took to rule
    out.
    """
    try:
        block = int(w3.eth.block_number) - _PROBE_DEPTH
        w3.eth.get_logs(
            {
                "fromBlock": block,
                "toBlock": block,
                "address": Web3.to_checksum_address(_PROBE_ADDRESS),
            }  # type: ignore[arg-type]
        )
    except Exception:  # noqa: BLE001 — any refusal is a refusal
        return False
    return True


def connect_all(
    chain_id: int,
    *,
    timeout: float = 20.0,
    needs_logs: bool = True,
    on_reject: Callable[[str, str], None] | None = None,
) -> list[Web3]:
    """Every endpoint that answers for this chain **and can do the job**, in
    preference order.

    A long backfill will exhaust any one public endpoint's rate limit — they
    return 403 rather than 429, and no amount of backoff persuades them. Having
    somewhere else to go is the only thing that actually works.

    `needs_logs` defaults to true because all three callers here index events,
    and because selecting on chain id alone is what produced P-10. Eight public
    BSC endpoints answer `eth_chainId` and serve no logs whatsoever; picking one
    of those gave a tail that refused every request forever while looking like a
    quiet pool. The health check has to test the capability the caller will
    actually use, not the cheapest one available.

    `on_reject(url, reason)` reports each endpoint dropped and why. Callers with
    a console pass a printer: an endpoint silently missing from the rotation is
    how a run ends up slower than it should be with nothing to point at — and if
    the endpoint dropped is the operator's own configured `BSC_RPC_URL`, they
    are entitled to hear about it rather than wonder why their key seems unused.
    """
    from web3.middleware import ExtraDataToPOAMiddleware

    urls: list[str] = []
    env = os.environ.get("BSC_RPC_URL" if chain_id == 56 else "BSC_TESTNET_RPC_URL")
    if env:
        urls.append(env)
    urls.extend(PUBLIC_RPCS.get(chain_id, ()))

    out: list[Web3] = []
    for url in urls:
        try:
            w3 = Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": timeout}))
            w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
            actual = w3.eth.chain_id
        except Exception as error:  # noqa: BLE001 — an unreachable endpoint is just one fewer
            if on_reject:
                on_reject(url, type(error).__name__)
            continue
        if actual != chain_id:
            if on_reject:
                on_reject(url, f"serves chain {actual}, not {chain_id}")
            continue
        if needs_logs and not serves_logs(w3):
            if on_reject:
                on_reject(url, "answers for the chain but serves no eth_getLogs")
            continue
        out.append(w3)

    if not out:
        what = "that serves eth_getLogs" if needs_logs else "usable"
        raise RuntimeError(f"no RPC for chain {chain_id} {what}")
    return out


class BscReader:
    """The read path: block timestamps, pool logs, pool state.

    Holds several endpoints and rotates when one starts refusing. A 30-day
    backfill at BSC's 0.45s block time is nearly three thousand requests, which
    is more than any single free endpoint will serve in a row.
    """

    def __init__(
        self,
        w3: Web3 | list[Web3],
        *,
        confirmations: int = 15,
        pace_seconds: float = 0.0,
    ) -> None:
        self._endpoints = list(w3) if isinstance(w3, list) else [w3]
        self._current = 0
        self.confirmations = confirmations
        self.pace_seconds = pace_seconds
        self._last_call = 0.0
        self._block_ts: dict[int, int] = {}
        self.rotations = 0
        # Per endpoint, not just in total. `rotations` counts that *something*
        # moved and never which host served what, so a measurement taken through
        # this reader cannot attribute its own result: "6 of 6 succeeded" reads
        # as a fact about the endpoint list when it is a fact about whichever
        # endpoint answered. That is how P-11's wrong cause got into the
        # requirements matrix and stayed there for two days looking measured.
        self.served: dict[str, int] = {}
        self.refused: dict[str, int] = {}

    @property
    def w3(self) -> Web3:
        return self._endpoints[self._current]

    @staticmethod
    def _name(w3: Web3) -> str:
        """Whatever identifies this endpoint in a report."""
        return str(getattr(w3.provider, "endpoint_uri", None) or w3.provider)

    def attribution(self) -> list[tuple[str, int, int]]:
        """(endpoint, served, refused) for every endpoint that was asked
        anything, in the order they were configured.

        Printed by `follow`'s summary. An endpoint that refuses everything is
        visible here in one line, which is the whole point: the alternative is
        inferring it from an aggregate that cannot show it.
        """
        return [
            (name, self.served.get(name, 0), self.refused.get(name, 0))
            for name in (self._name(w3) for w3 in self._endpoints)
            if name in self.served or name in self.refused
        ]

    def _rotate(self) -> bool:
        """Move to the next endpoint. False if there is only one."""
        if len(self._endpoints) < 2:
            return False
        self._current = (self._current + 1) % len(self._endpoints)
        self.rotations += 1
        return True

    def _call(self, fn_of_w3: Callable[[Web3], Any]) -> Any:
        """Run an RPC call, rotating endpoints if this one gives up on us."""
        if self.pace_seconds:
            wait = self.pace_seconds - (time.monotonic() - self._last_call)
            if wait > 0:
                time.sleep(wait)

        attempts_per_endpoint = 2
        last: Exception | None = None
        for _ in range(len(self._endpoints)):
            # Read before the call, because a failure rotates and `self.w3`
            # would then name the endpoint that is about to be tried next
            # rather than the one that just refused.
            name = self._name(self.w3)
            try:
                result = rpc_retry(lambda: fn_of_w3(self.w3), attempts=attempts_per_endpoint)
                self._last_call = time.monotonic()
                self.served[name] = self.served.get(name, 0) + 1
                return result
            except RangeTooLarge:
                # This endpoint declined this width. It is still a refusal by
                # this host, and which host declined is exactly the thing worth
                # knowing when their caps differ.
                self.refused[name] = self.refused.get(name, 0) + 1
                raise
            except Exception as error:  # noqa: BLE001
                self.refused[name] = self.refused.get(name, 0) + 1
                last = error
                if not is_transient(error) or not self._rotate():
                    raise
        raise last  # pragma: no cover

    # --- blocks ------------------------------------------------------------

    def head_block(self) -> int:
        return int(self._call(lambda w3: w3.eth.block_number))

    def safe_head(self) -> int:
        """The newest block we are willing to treat as settled.

        BSC reorgs are shallow but real. Indexing to the literal head means the
        tape can contain events that later cease to exist, and the replay engine
        has no way to notice.
        """
        return max(0, self.head_block() - self.confirmations)

    def block_timestamp(self, number: int) -> int:
        if number not in self._block_ts:
            block = self._call(lambda w3: w3.eth.get_block(number))
            self._block_ts[number] = int(block["timestamp"])
        return self._block_ts[number]

    def prime_timestamps(self, numbers: Iterable[int]) -> None:
        """Fetch the block timestamps a batch of logs will need.

        One `eth_getBlockByNumber` per distinct block rather than per log: a busy
        pool puts many swaps in one block, and the naive version turns a
        2,000-block chunk into thousands of round trips.
        """
        for number in sorted(set(numbers) - set(self._block_ts)):
            self.block_timestamp(number)

    # --- logs --------------------------------------------------------------

    def raw_logs(self, pool: str, from_block: int, to_block: int) -> list[dict[str, Any]]:
        """Every Swap, Mint and Burn for one pool in a block range.

        One filter for all three topics, so a chunk is one round trip rather
        than three.
        """
        if to_block < from_block:
            return []
        params = {
            "address": Web3.to_checksum_address(pool),
            "fromBlock": from_block,
            "toBlock": to_block,
            "topics": [[TOPIC_SWAP, TOPIC_MINT, TOPIC_BURN]],
        }
        return list(self._call(lambda w3: w3.eth.get_logs(params)))

    def events(self, pool: str, from_block: int, to_block: int) -> list[Event]:
        """Decoded, timestamped, and in chain order.

        Most BSC endpoints return `blockTimestamp` on each log, which matters a
        great deal: without it every distinct block needs its own
        `eth_getBlockByNumber`, and at BSC's 0.45s block time a 30-day backfill
        touches roughly a hundred thousand blocks — hours of round trips to
        recover data the log already carried. Endpoints that omit it fall back to
        the cache below.
        """
        logs = self.raw_logs(pool, from_block, to_block)
        self.prime_timestamps(
            int(log["blockNumber"]) for log in logs if "blockTimestamp" not in log
        )

        out: list[Event] = []
        for log in logs:
            decoded = self.decode(log)
            if decoded is not None:
                out.append(decoded)
        out.sort(key=lambda e: e.key)
        return out

    def _timestamp_of(self, log: dict[str, Any], block: int) -> int:
        """Prefer the timestamp the log already carries; fetch only if absent."""
        raw = log.get("blockTimestamp")
        if raw is None:
            return self.block_timestamp(block)
        value = int(raw, 16) if isinstance(raw, str) else int(raw)
        self._block_ts[block] = value
        return value

    def decode(self, log: dict[str, Any]) -> Event | None:
        """One raw log -> one `Event`, or None if it is not one of ours."""
        topics = [_hex(t) for t in log["topics"]]
        topic0 = topics[0] if topics else ""

        data = log["data"]
        raw = bytes(data) if isinstance(data, bytes | bytearray) else bytes.fromhex(data[2:])
        block = int(log["blockNumber"])

        common = {
            "block": block,
            "log_index": int(log["logIndex"]),
            "ts": self._timestamp_of(log, block),
            "tx": _hex(log["transactionHash"]),
        }

        if topic0 == TOPIC_SWAP:
            # Pancake's layout: amount0, amount1, sqrtPriceX96, liquidity, tick,
            # protocolFeesToken0, protocolFeesToken1. The last two are the extra
            # fields Uniswap does not have, and they are how much the protocol
            # took out of this swap's fee before LPs saw any of it.
            return Event(
                **common,
                kind="swap",
                amount0=_int256(raw, 0),
                amount1=_int256(raw, 1),
                sqrt_price_x96=_uint(raw, 2),
                liquidity=_uint(raw, 3),
                tick=_int256(raw, 4),
                protocol_fee0=_uint(raw, 5),
                protocol_fee1=_uint(raw, 6),
            )

        if topic0 == TOPIC_MINT:
            # Mint's non-indexed data is (sender, amount, amount0, amount1);
            # owner and both ticks are indexed.
            return Event(
                **common,
                kind="mint",
                amount0=_uint(raw, 2),
                amount1=_uint(raw, 3),
                sqrt_price_x96=0,
                liquidity=_uint(raw, 1),
                tick=0,
                tick_lower=_int_topic(topics[2]),
                tick_upper=_int_topic(topics[3]),
            )

        if topic0 == TOPIC_BURN:
            return Event(
                **common,
                kind="burn",
                amount0=_uint(raw, 1),
                amount1=_uint(raw, 2),
                sqrt_price_x96=0,
                liquidity=_uint(raw, 0),
                tick=0,
                tick_lower=_int_topic(topics[2]),
                tick_upper=_int_topic(topics[3]),
            )

        return None


# --- ABI word decoding ------------------------------------------------------
#
# Hand-decoded rather than via `contract.events`, because that path needs a full
# ABI object per pool and silently skips logs it cannot match. Here an unknown
# topic returns None explicitly and a malformed word raises.


def _hex(value: Any) -> str:
    """Any hex-ish RPC value -> a 0x-prefixed lowercase string.

    `HexBytes.hex()` includes the 0x prefix in web3 6.x and omits it in 7.x, so
    comparing its output directly against a computed topic silently stops
    matching on an upgrade.
    """
    raw = value.hex() if hasattr(value, "hex") else str(value)
    return "0x" + raw.removeprefix("0x").lower()


def _word(raw: bytes, index: int) -> bytes:
    start = index * 32
    end = start + 32
    if len(raw) < end:
        raise ValueError(f"log data has {len(raw)} bytes, needed {end} for word {index}")
    return raw[start:end]


def _uint(raw: bytes, index: int) -> int:
    return int.from_bytes(_word(raw, index), "big")


def _int256(raw: bytes, index: int) -> int:
    """Two's-complement signed decode. Swap amounts and ticks are both signed."""
    value = int.from_bytes(_word(raw, index), "big")
    return value - (1 << 256) if value >= (1 << 255) else value


def _int_topic(topic: Any) -> int:
    """An indexed int24, which arrives padded to a full word."""
    hexed = topic.hex() if hasattr(topic, "hex") else str(topic)
    value = int(hexed, 16)
    return value - (1 << 256) if value >= (1 << 255) else value
