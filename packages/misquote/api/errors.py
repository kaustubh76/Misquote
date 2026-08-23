"""One shape for every refusal this service makes.

A 404 that says "Not Found" tells a reader nothing they can act on. Every
refusal here carries four things instead: what was asked for, the command that
would make it available, what *is* available, and a note distinguishing an
absence from an error. `service.py` already produced that shape by hand at two
call sites; this is the same shape with one implementation, so the twentieth
route cannot invent a nineteenth variant of it.

The status codes carry meaning and are not interchangeable:

- **404** — the thing does not exist, or nobody has generated it. Both are
  absences, and neither is an empty result.
- **409** — the request is well-formed and the evidence cannot support it. This
  is the *quote refusal*: not a failure, an answer. It is the one status a
  client must never retry and must never paper over with a cached value.
- **501** — the route is real and the capability is not. Used where a contract
  address has not been verified: a 404 would say the endpoint does not exist,
  which is the wrong claim.
- **503** — transient. An emitter mid-write, an RPC that did not answer. Retry
  is the correct response.

`detail` is a dict rather than a string on purpose: `apps/web/src/lib/artifacts.ts`
reads `remedy` out of it and renders it, so a refusal that collapsed into prose
would lose the one field the UI acts on.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException


def refuse(
    status: int,
    *,
    error: str,
    remedy: str,
    available: list[str] | None = None,
    note: str | None = None,
) -> HTTPException:
    """Build a refusal. Returned rather than raised, so the call site reads `raise`.

    `available` is omitted rather than sent empty: an empty list reads as "these
    are the options, and there are none", which is a different claim from "the
    set of options is not meaningful for this route".
    """
    detail: dict[str, Any] = {"error": error, "remedy": remedy}
    if available is not None:
        detail["available"] = available
    if note is not None:
        detail["note"] = note
    return HTTPException(status_code=status, detail=detail)
