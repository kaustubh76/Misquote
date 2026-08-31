"""The ERC-8183 deployment's interface, recovered from bytecode rather than read.

`erc8183.py` models the hire flow in prose: `steps()` returns `Step` dataclasses
whose `call` field is a string. That is the right shape for pricing a sequence
and the wrong shape for sending one, and nothing here could send one because
there was no ABI anywhere in the repository.

## Why these names are derived and not copied

Altana's SDK publishes an ABI, and copying it would have been faster and would
have been the P-18 mistake. `aacp.py` recovered `TermixEscrow`'s dispatch table
from deployed bytecode and found that **none** of the seven calls the EIP
describes was present — right about the contract, and, as P-24 later showed,
partly wrong about the names it had probed for. So every signature below is
resolved against the PUSH4 selectors in the deployed implementation, and
`tests/registry/test_erc8183_abi.py` re-derives them on a live chain.

**That method paid immediately.** `steps()` models `submit(jobId, deliverable)`
— two arguments, the shape the EIP describes. The deployment's is
`submit(uint256,bytes32,bytes)`: **three**. A client built from the standard
would have encoded two words, hit a selector that does not exist, and reverted
with no revert string. It took 21,060 candidate signatures over 36 plausible
names to find, which is the same search `aacp.py` ran and the reason it is worth
running rather than trusting a table.

## Where the calls live, which is not where the EIP implies

Settlement is split across two contracts, and three calls appear on **both**:

    kernel   createJob setBudget fund claimRefund getJob jobCounter paymentToken
             submit complete reject
    router   registerJob settle getJob
             submit complete reject

`FOR_JUDGES.md` says settlement "goes through a separate EvaluatorRouter", which
is true of `settle` and not the whole truth: `complete` and `reject` are on the
kernel as well. Recorded as read, not tidied into the sentence we already had.

## What is deliberately not claimed

**64 of the kernel's 71 selectors and 58 of the router's 61 are unresolved**, and
they are counted rather than guessed — the rule `aacp.py` set when it resolved 21
of 65 and refused to name the other 44. Nothing here decodes a job's status into
a name, because `STATES` in `erc8183.py` is the EIP's list and no reading has
confirmed the deployment uses that ordering.
"""

from __future__ import annotations

import json

#: Signature -> selector, both carried so the naming can be re-derived rather
#: than trusted. The shape `aacp.ESCROW_INTERFACE` settled on after P-18.
KERNEL_INTERFACE: dict[str, str] = {
    "createJob(address,address,uint256,string,address)": "0x41528812",
    "setBudget(uint256,uint256,bytes)": "0xdd4ae9d4",
    "fund(uint256,uint256,bytes)": "0xd2e13f50",
    "submit(uint256,bytes32,bytes)": "0x9e63798d",
    "complete(uint256,bytes32,bytes)": "0xd75bbdf3",
    "reject(uint256,bytes32,bytes)": "0x41dd26f5",
    "claimRefund(uint256)": "0x5b7baf64",
    "getJob(uint256)": "0xbf22c457",
    "jobCounter()": "0x50355d76",
    "paymentToken()": "0x3013ce29",
}

ROUTER_INTERFACE: dict[str, str] = {
    "registerJob(uint256,address)": "0x51d5456d",
    "settle(uint256,bytes)": "0x39c2ebb9",
    "submit(uint256,bytes32,bytes)": "0x9e63798d",
    "complete(uint256,bytes32,bytes)": "0xd75bbdf3",
    "reject(uint256,bytes32,bytes)": "0x41dd26f5",
    "getJob(uint256)": "0xbf22c457",
}

#: Counted, not guessed. The other selectors are real functions this repository
#: has not identified, and saying "71 selectors, 7 named" is a different and more
#: honest claim than publishing seven and implying that is all of it.
KERNEL_SELECTORS_TOTAL = 71
KERNEL_SELECTORS_RESOLVED = 10
ROUTER_SELECTORS_TOTAL = 61
ROUTER_SELECTORS_RESOLVED = 6

#: How many candidate signatures were searched to resolve `submit`. Recorded for
#: the same reason `aacp.py` records 5,894: it is what makes "not present" a
#: measurement rather than a failure to think of the right name.
SIGNATURES_SEARCHED = 21_060

KERNEL_ABI = json.loads("""[
  {"name":"createJob","type":"function","stateMutability":"nonpayable",
   "inputs":[{"name":"provider","type":"address"},{"name":"evaluator","type":"address"},
             {"name":"expiredAt","type":"uint256"},{"name":"description","type":"string"},
             {"name":"hook","type":"address"}],
   "outputs":[{"type":"uint256"}]},
  {"name":"setBudget","type":"function","stateMutability":"nonpayable",
   "inputs":[{"name":"jobId","type":"uint256"},{"name":"amount","type":"uint256"},
             {"name":"optParams","type":"bytes"}],
   "outputs":[]},
  {"name":"fund","type":"function","stateMutability":"nonpayable",
   "inputs":[{"name":"jobId","type":"uint256"},{"name":"expectedBudget","type":"uint256"},
             {"name":"optParams","type":"bytes"}],
   "outputs":[]},
  {"name":"submit","type":"function","stateMutability":"nonpayable",
   "inputs":[{"name":"jobId","type":"uint256"},{"name":"deliverable","type":"bytes32"},
             {"name":"optParams","type":"bytes"}],
   "outputs":[]},
  {"name":"claimRefund","type":"function","stateMutability":"nonpayable",
   "inputs":[{"name":"jobId","type":"uint256"}],"outputs":[]},
  {"name":"jobCounter","type":"function","stateMutability":"view",
   "inputs":[],"outputs":[{"type":"uint256"}]},
  {"name":"paymentToken","type":"function","stateMutability":"view",
   "inputs":[],"outputs":[{"type":"address"}]}
]""")

ROUTER_ABI = json.loads("""[
  {"name":"registerJob","type":"function","stateMutability":"nonpayable",
   "inputs":[{"name":"jobId","type":"uint256"},{"name":"policy","type":"address"}],
   "outputs":[]},
  {"name":"settle","type":"function","stateMutability":"nonpayable",
   "inputs":[{"name":"jobId","type":"uint256"},{"name":"evidence","type":"bytes"}],
   "outputs":[]}
]""")

#: The ERC-20 the kernel pulls a budget through. Minimal on purpose: this
#: repository does not need a token's name to approve a spend, and a fuller ABI
#: would invite reading fields nobody has verified on this particular token.
ERC20_ABI = json.loads("""[
  {"name":"approve","type":"function","stateMutability":"nonpayable",
   "inputs":[{"name":"spender","type":"address"},{"name":"amount","type":"uint256"}],
   "outputs":[{"type":"bool"}]},
  {"name":"allowance","type":"function","stateMutability":"view",
   "inputs":[{"name":"owner","type":"address"},{"name":"spender","type":"address"}],
   "outputs":[{"type":"uint256"}]},
  {"name":"balanceOf","type":"function","stateMutability":"view",
   "inputs":[{"name":"account","type":"address"}],"outputs":[{"type":"uint256"}]},
  {"name":"decimals","type":"function","stateMutability":"view",
   "inputs":[],"outputs":[{"type":"uint8"}]}
]""")

#: `getJob` is deliberately **not** in `KERNEL_ABI`.
#:
#: It answers — the selector is present on both contracts — but its return shape
#: is a struct this repository has not decoded, and web3 needs the output types
#: to build a call. Declaring a plausible tuple would produce confidently wrong
#: field names, which is `aacp.ORDER_STATE_IS_UNDECODED` all over again: TermiX's
#: `orders(bytes32)` returned thirteen well-formed words and only one of them was
#: ever confirmed against an independent source.
#:
#: `hire.py` reads a job through the raw selector and publishes the words, so a
#: reader gets the bytes rather than a labelling nobody checked.
JOB_STRUCT_IS_UNDECODED = True


def selector_for(signature: str) -> str:
    """The 4-byte selector, computed. Never read from the tables above.

    They carry it so a reader can check; computing it here means the two can be
    compared, which is the only reason recording a derivable value is worth
    anything.
    """
    from eth_utils import keccak

    return "0x" + keccak(text=signature)[:4].hex()


__all__ = [
    "ERC20_ABI",
    "JOB_STRUCT_IS_UNDECODED",
    "KERNEL_ABI",
    "KERNEL_INTERFACE",
    "KERNEL_SELECTORS_RESOLVED",
    "KERNEL_SELECTORS_TOTAL",
    "ROUTER_ABI",
    "ROUTER_INTERFACE",
    "ROUTER_SELECTORS_RESOLVED",
    "ROUTER_SELECTORS_TOTAL",
    "SIGNATURES_SEARCHED",
    "selector_for",
]
