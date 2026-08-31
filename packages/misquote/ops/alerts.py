"""Telegram alerting, which does nothing at all unless it is configured.

`python-telegram-bot` has been in the `ops` extra since the project started and
nothing imported it. `.env.example` lists `TELEGRAM_BOT_TOKEN` and
`TELEGRAM_CHAT_IDS` under "NOT WIRED TO ANYTHING". This wires them.

## The default is silence, and that is the design

An alerting module that raises when unconfigured is one that takes the agent down
for the sake of telling somebody the agent is up. So `notify()` returns `False`
and does nothing when there is no token, and `configured()` says which case you
are in — because "sent nothing because nobody is listening" and "tried to send
and failed" are different facts, and a bare `False` would merge them.

## What it will not do

It does not retry, and it does not queue. A notifier that buffers alerts is a
second piece of state that can be wrong about the agent, and the journal is
already the durable record. If Telegram is down the alert is lost and
`notify()` says so — the kill file and the journal are what the operator is
actually relying on.

**Nothing here is on the decision path.** `notify()` is called after an action is
journalled, never before one is taken, so a hung HTTP request cannot delay a
withdrawal.
"""

from __future__ import annotations

import os

#: How long to wait on Telegram before giving up. Deliberately short: this runs
#: in the loop's thread pool, and an alert that blocks for thirty seconds is a
#: thirty-second hole in whatever else that thread was going to do.
TIMEOUT_S = 5.0


def configured() -> bool:
    """Is there a token and at least one chat to send to?

    Both, not either. A token with no chat ids sends nowhere, and reporting that
    as configured would make a silent notifier look like a working one.
    """
    return bool(os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_IDS"))


def chat_ids() -> tuple[str, ...]:
    raw = os.environ.get("TELEGRAM_CHAT_IDS", "")
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def notify(text: str, *, timeout: float = TIMEOUT_S) -> bool:
    """Send one message. `False` means nothing was delivered, for any reason.

    Returns rather than raises, because every call site is on a path where the
    agent has already done the thing worth telling somebody about. Failing to
    announce an action is not a reason to fail the action.
    """
    if not configured():
        return False
    if not text.strip():
        raise ValueError("refusing to send an empty alert")

    token = os.environ["TELEGRAM_BOT_TOKEN"]
    delivered = False
    try:
        import httpx
    except ImportError:  # pragma: no cover — httpx is a core dependency
        return False

    for chat in chat_ids():
        try:
            response = httpx.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat, "text": text[:4000], "disable_web_page_preview": True},
                timeout=timeout,
            )
            delivered = delivered or response.status_code == 200
        except Exception:  # noqa: BLE001 — a failed alert is not a failed agent
            continue
    return delivered


def why_silent() -> str:
    """One sentence for a status line, so an absence is legible rather than odd."""
    if configured():
        return f"Telegram configured for {len(chat_ids())} chat(s)."
    missing = [
        name for name in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_IDS") if not os.environ.get(name)
    ]
    return f"Telegram alerting is off: {' and '.join(missing)} unset. Nothing is queued."


__all__ = ["TIMEOUT_S", "chat_ids", "configured", "notify", "why_silent"]
