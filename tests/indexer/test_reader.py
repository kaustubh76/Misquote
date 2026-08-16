"""Endpoint selection, and the health check that tested the wrong thing.

`connect_all` used to keep every endpoint that answered `eth_chainId` with 56.
Measured on 16 Aug 2026, eight public BSC endpoints do exactly that and refuse
*every* `eth_getLogs` with -32005 — every bnbchain dataseed, both defibit hosts,
ninicoin. So the indexer's endpoint list could be populated entirely with nodes
that could never serve it, and the only symptom was P-10's tail: refused on
every request, for thirty-five minutes, looking exactly like a quiet pool.

A health check that passes on a capability nobody needs is the same defect as
V-11's toxicity arm wired to a literal zero. These tests exist to keep the check
pointed at the capability the caller actually uses.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from misquote.indexer import reader


@dataclass
class Node:
    """What one fake endpoint does when it is asked something."""

    chain_id: int | None = 56  # None: the host does not answer at all
    logs: bool = True  # False: answers for the chain, refuses every getLogs
    asked: list[dict] = field(default_factory=list)


def fake_web3(nodes: dict[str, Node]):
    """A stand-in for `Web3` that never opens a socket."""

    class Provider:
        def __init__(self, url, request_kwargs=None):
            self.url = url

    class Onion:
        def inject(self, *_args, **_kwargs) -> None:
            return None

    class Eth:
        def __init__(self, node: Node) -> None:
            self._node = node

        @property
        def chain_id(self) -> int:
            if self._node.chain_id is None:
                raise ConnectionError("unreachable")
            return self._node.chain_id

        @property
        def block_number(self) -> int:
            return 116_000_000

        def get_logs(self, params: dict):
            self._node.asked.append(params)
            if not self._node.logs:
                raise ValueError({"code": -32005, "message": "limit exceeded"})
            return []

    class FakeWeb3:
        HTTPProvider = Provider

        @staticmethod
        def to_checksum_address(address: str) -> str:
            return address

        def __init__(self, provider: Provider) -> None:
            node = nodes.get(provider.url)
            if node is None:
                raise ConnectionError(f"no such host: {provider.url}")
            self.eth = Eth(node)
            self.middleware_onion = Onion()

    return FakeWeb3


@pytest.fixture
def no_env(monkeypatch: pytest.MonkeyPatch):
    """The autouse network rail points BSC_RPC_URL at a black hole; most of
    these tests are about the public list, so take it out of the way."""
    monkeypatch.delenv("BSC_RPC_URL", raising=False)
    monkeypatch.delenv("BSC_TESTNET_RPC_URL", raising=False)


def install(monkeypatch: pytest.MonkeyPatch, nodes: dict[str, Node]) -> None:
    monkeypatch.setattr(reader, "Web3", fake_web3(nodes))
    monkeypatch.setitem(reader.PUBLIC_RPCS, 56, tuple(nodes))


# --- the probe --------------------------------------------------------------


def test_a_refused_getlogs_means_the_endpoint_does_not_serve_logs(monkeypatch, no_env) -> None:
    nodes = {"https://refuses": Node(logs=False)}
    install(monkeypatch, nodes)
    w3 = reader.Web3(reader.Web3.HTTPProvider("https://refuses"))
    assert reader.serves_logs(w3) is False


def test_an_empty_answer_means_it_does(monkeypatch, no_env) -> None:
    nodes = {"https://serves": Node(logs=True)}
    install(monkeypatch, nodes)
    w3 = reader.Web3(reader.Web3.HTTPProvider("https://serves"))
    assert reader.serves_logs(w3) is True


def test_the_probe_asks_for_exactly_one_block(monkeypatch, no_env) -> None:
    """Its whole justification is that it is nearly free. A probe that widened
    into a real query would spend the quota it exists to protect."""
    nodes = {"https://serves": Node(logs=True)}
    install(monkeypatch, nodes)
    reader.serves_logs(reader.Web3(reader.Web3.HTTPProvider("https://serves")))

    (asked,) = nodes["https://serves"].asked
    assert asked["fromBlock"] == asked["toBlock"], "the probe is scanning a range"
    assert asked["address"] == reader._PROBE_ADDRESS, "probing an address that holds logs"


# --- selection --------------------------------------------------------------


def test_an_endpoint_that_answers_for_the_chain_but_serves_no_logs_is_dropped(
    monkeypatch, no_env
) -> None:
    """The defect this file exists for. Both of these are chain 56 and only one
    of them can do the job."""
    nodes = {"https://serves": Node(logs=True), "https://dataseed": Node(logs=False)}
    install(monkeypatch, nodes)

    kept = reader.connect_all(56)
    assert len(kept) == 1
    assert nodes["https://dataseed"].asked, "the dropped endpoint was never probed"


def test_selecting_on_chain_id_alone_would_have_kept_it(monkeypatch, no_env) -> None:
    """The other half of the same story, so the test above is not passing for
    some unrelated reason: with the capability check off, the useless endpoint
    is kept — which is precisely what the old code did on every call."""
    nodes = {"https://serves": Node(logs=True), "https://dataseed": Node(logs=False)}
    install(monkeypatch, nodes)

    assert len(reader.connect_all(56, needs_logs=False)) == 2


def test_a_state_only_caller_is_not_charged_for_a_probe(monkeypatch, no_env) -> None:
    """`connect` serves the registry and the write path, which read state and
    never ask for a log. Rejecting a dataseed for a capability it is never asked
    for would be its own defect."""
    nodes = {"https://dataseed": Node(logs=False)}
    install(monkeypatch, nodes)

    reader.connect_all(56, needs_logs=False)
    assert nodes["https://dataseed"].asked == [], "probed an endpoint that needs no logs"


def test_the_wrong_chain_is_still_refused(monkeypatch, no_env) -> None:
    """An endpoint quietly serving another chain produces a complete,
    internally consistent, entirely wrong tape. That check predates this one and
    must survive it."""
    nodes = {"https://ethereum": Node(chain_id=1, logs=True)}
    install(monkeypatch, nodes)

    with pytest.raises(RuntimeError):
        reader.connect_all(56)


def test_nothing_serving_logs_says_so_by_name(monkeypatch, no_env) -> None:
    """ "no usable RPC" sent me looking at the network. The endpoints were
    reachable and fast; they just do not do this."""
    install(monkeypatch, {"https://dataseed": Node(logs=False)})

    with pytest.raises(RuntimeError, match="eth_getLogs"):
        reader.connect_all(56)


# --- saying which endpoints were dropped ------------------------------------


def test_each_rejection_is_reported_with_its_reason(monkeypatch, no_env) -> None:
    nodes = {
        "https://serves": Node(logs=True),
        "https://dataseed": Node(logs=False),
        "https://ethereum": Node(chain_id=1),
        "https://down": Node(chain_id=None),
    }
    install(monkeypatch, nodes)

    rejected: list[tuple[str, str]] = []
    kept = reader.connect_all(56, on_reject=lambda url, why: rejected.append((url, why)))

    assert len(kept) == 1
    assert dict(rejected).keys() == {"https://dataseed", "https://ethereum", "https://down"}
    assert "eth_getLogs" in dict(rejected)["https://dataseed"]
    assert "chain 1" in dict(rejected)["https://ethereum"]


def test_the_operators_own_endpoint_is_reported_when_it_is_dropped(monkeypatch) -> None:
    """A keyed BSC_RPC_URL that fails its probe still falls back to the public
    list, so the run works — and the operator is left believing their key is in
    use. They are entitled to hear that it was dropped."""
    monkeypatch.setenv("BSC_RPC_URL", "https://keyed.example")
    nodes = {"https://keyed.example": Node(logs=False), "https://serves": Node(logs=True)}
    monkeypatch.setattr(reader, "Web3", fake_web3(nodes))
    monkeypatch.setitem(reader.PUBLIC_RPCS, 56, ("https://serves",))

    rejected: list[tuple[str, str]] = []
    reader.connect_all(56, on_reject=lambda url, why: rejected.append((url, why)))

    assert rejected == [
        ("https://keyed.example", "answers for the chain but serves no eth_getLogs")
    ]


def test_preference_order_is_the_list_order(monkeypatch, no_env) -> None:
    """The public list is ordered by measurement — the endpoints that serve logs
    first, the burst-limited one after them. Selection must not reorder it."""
    nodes = {"https://first": Node(), "https://second": Node(), "https://third": Node()}
    install(monkeypatch, nodes)

    kept = reader.connect_all(56)
    assert [w3.eth._node for w3 in kept] == list(nodes.values())


# --- attributing a result to the endpoint that produced it -------------------


class Endpoint:
    """A `Web3` stand-in for `BscReader`, which only needs a provider name."""

    def __init__(self, url: str, *, fails: bool = False) -> None:
        self.provider = type("P", (), {"endpoint_uri": url})()
        self.fails = fails

    def work(self):
        if self.fails:
            raise RuntimeError("-32005 limit exceeded")
        return "ok"


@pytest.fixture
def instant(monkeypatch: pytest.MonkeyPatch):
    """`rpc_retry` backs off for real seconds; these tests are about counting."""
    monkeypatch.setattr(reader.time, "sleep", lambda _s: None)


def test_a_refusal_is_recorded_against_the_endpoint_that_refused(instant) -> None:
    """The instrument D-9 was read through could not do this, and the conclusion
    drawn from it named the wrong cause for two days."""
    dead, alive = Endpoint("https://dead", fails=True), Endpoint("https://alive")
    r = reader.BscReader([dead, alive])

    assert r._call(lambda w3: w3.work()) == "ok"
    assert r.attribution() == [("https://dead", 0, 1), ("https://alive", 1, 0)]


def test_an_endpoint_never_asked_does_not_appear(instant) -> None:
    """Reporting a zero against an endpoint that was never tried would read as
    "it refused everything" — the same over-reading, one layer down."""
    r = reader.BscReader([Endpoint("https://first"), Endpoint("https://never")])
    r._call(lambda w3: w3.work())

    assert r.attribution() == [("https://first", 1, 0)]


def test_every_endpoint_refusing_is_visible_as_such(instant) -> None:
    """The case that actually happened: nothing served, everything refused. The
    aggregate says "refused"; only this says there is nobody left to ask."""
    r = reader.BscReader([Endpoint("https://a", fails=True), Endpoint("https://b", fails=True)])

    with pytest.raises(RuntimeError):
        r._call(lambda w3: w3.work())

    assert r.attribution() == [("https://a", 0, 1), ("https://b", 0, 1)]
    assert all(served == 0 for _, served, _ in r.attribution())


def test_a_width_refusal_is_attributed_too(instant) -> None:
    """`RangeTooLarge` propagates rather than rotating, and it is still this
    host declining this query. Their caps differ — 5,000 on the two that serve
    logs, 50 on 1rpc, 25 on blockrazor — so which one declined is the thing
    worth knowing."""

    def too_wide(_w3):
        raise reader.RangeTooLarge("exceed maximum block range: 5000")

    r = reader.BscReader([Endpoint("https://narrow")])
    with pytest.raises(reader.RangeTooLarge):
        r._call(too_wide)

    assert r.attribution() == [("https://narrow", 0, 1)]
