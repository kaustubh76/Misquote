# Runbook

What to do, in the order you would need it. Every procedure here is written from
what the code does; where the code refuses to decide something, this file decides
it and says so.

`Readme.md` §2 has claimed `ops/` holds "deploy scripts, monitoring, runbooks"
since the beginning, and it held `forge_deps.txt`. The monitoring is real now —
`packages/misquote/ops/` has metrics, a heartbeat and alerting — which is what
made the absence of this file worth fixing: **a metric nobody has written a
response to is a number, not an operation.**

---

## 1. Stop a live agent

```bash
touch ops/KILL
```

Two independent paths enforce it, and the redundancy is deliberate:

- `chain/signer.py::check_kill_switch` runs **immediately before broadcast**,
  inside the signer, so no caller can route around it. A kill switch that lives
  in the event loop only works while the event loop is healthy.
- `WardenLoop._watch_kill_file` polls **once a second** — the decision cadence is
  the agent's convenience, the kill switch is yours — and fires a Telegram
  notification if one is configured.

Resume with `rm ops/KILL`.

> **The interlock nobody had written down.** `make go-no-go` **FAILs** while
> `ops/KILL` exists (`check_no_kill_file_present`). So "stopped" and "passing the
> go-live gate" are mutually exclusive states, by design. If you are stopping an
> agent to investigate and then running the gate, expect a red that is your own
> kill file, and do not remove it to make the gate green.

---

## 2. The heartbeat is stale

`ops/heartbeat.py` records **a timestamp, not a boolean** — a hung process stops
updating either one, and only the clock says how long ago.

```python
beat.stale_for()      # seconds since the last completed cycle; inf if never
beat.is_stale(bound)  # you supply the bound
```

**`is_stale` takes the bound from the caller and the module refuses to hardcode
one**, because how long is too long depends on the poll cadence. This file
supplies it:

| cadence | value | so |
|---|---|---|
| decision | 5s (spec §8 Δs) | a beat per cycle |
| chain poll | 60s (`live_source.DEFAULT_POLL_SECONDS`, matrix D-9) | the real floor |
| **treat as stale after** | **5 minutes** | five poll intervals; below that you are alerting on a slow endpoint |

`stale_for()` returning `inf` means it has **never beaten** — the agent has not
completed a cycle, which is a different state from a hung one and usually means
`source.prime()` failed at boot.

Not to be confused with the **job queue's** `worker.heartbeat_ts` in
`ops/jobs.py`: that answers *is a worker draining quote jobs*, this answers *is
the agent still deciding*.

---

## 3. `/metrics` returns 501

It means `prometheus-client` is not installed, **not** that the agent is idle.
The route refuses rather than serving an empty exposition precisely because a
scraper cannot tell those apart.

```bash
uv sync --extra ops     # or --all-extras
```

Two things that surprise people:

- **`PROMETHEUS_PORT` is read at import.** Changing it needs a process restart,
  and the value is the *agent loop's own* exporter — `make api` already serves
  `/metrics` for the API process. Unset (the default) starts nothing, which is
  right when the API is running beside the agent.
- **No PnL, fee APR or position value is exported**, deliberately. Those are
  computed once by the replay accountant with their assumptions attached. A
  second derivation reachable by a different path is how two numbers in one
  system come to disagree — P-8, twice.

---

## 4. No alert arrived

**Absence of a Telegram message is not evidence of health.** The journal is.

`ops/alerts.py` needs **both** `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_IDS`; a
token with no chat ids sends nowhere and is reported as unconfigured. `notify()`
returns `False` and never raises — a notifier that raises takes the agent down to
announce that the agent is up — and it **does not retry and does not queue**. If
Telegram is down the alert is lost.

```bash
python -c "from misquote.ops import alerts; print(alerts.why_silent())"
```

Alerts fire after the fact, never before an action: kill-file stop, executed
action, failed action. So an alert is a receipt, not a control.

---

## 5. Before anything touches mainnet

```bash
make go-no-go            # the full gate
make go-no-go-fast       # skips seven; see below
```

- `MISQUOTE_POSITION_CAP_QUOTE` **must be set** — the gate FAILs when it is
  unset, deliberately, rather than defaulting to a number nobody chose.
- `--fast` skips the offline suite, the replay invariants, lint, both web suites
  and the chain suite. **`make status` publishes from the fast pass**, so a green
  `/status` is not a green gate.
- Amber is not green. Every UNVERIFIED is something nobody checked, not something
  that passed.

---

## 6. Burn-in evidence

`check_burn_in` measures the **longest unbroken run** in each agent's journal,
not the span of the file. The journal is append-only, so span would count two
ten-minute runs a day apart as 25 hours — it did, until it was fixed.

- Reads every `*.jsonl` in `$MISQUOTE_JOURNAL_DIR` (default `data/journal/`), one
  per agent, and gates on the **Warden**; the others are reported.
- A gap over 15 minutes splits a run. That is fifteen poll intervals.
- A journal recording **chain 56 is refused**: this gate is the *testnet*
  burn-in.

```bash
make warden CHAIN=97 WARDEN_S=86400     # 24h, records rather than signs
make journal                            # publish journals into the artifact
```

---

## 7. Deploy

`render.yaml` is the source of truth. Three things to know before debugging a
deployed instance:

- It serves the committed **31MB tape slice** (`data/deploy/tape.db`), not the
  245MB indexed tape, which is gitignored.
- **`POST /quote` writes to ephemeral storage. The queue is lost on restart.**
  A job that vanished did not fail; its disk did.
- The worker (`python -m misquote.ops.worker`) runs inside the same service.
  Locally that is `sh scripts/serve.sh` or `make serve` — `make api` starts
  uvicorn **only**, so a local API with no worker accepts quotes and never
  drains them.

---

## 8. Enable a broadcast

Three independent refusals, and the default of all three is no:

1. `--broadcast` on the command.
2. The chain must be **chapel**. Mainnet raises in code (`BROADCAST_CHAIN = 97`),
   not by convention — it is not a flag you can pass.
3. `MISQUOTE_DRY_RUN=0`, **on that one command and never in `.env`**. It also
   triggers `assert_signs_for_operator`, so the key must match a declared
   address.

```bash
MISQUOTE_DRY_RUN=0 make warden CHAIN=97 BROADCAST=--broadcast
MISQUOTE_DRY_RUN=0 make session-keys
MISQUOTE_DRY_RUN=0 make hire
MISQUOTE_DRY_RUN=0 make identity-register BROADCAST=--broadcast
```

**Nothing loads `.env`.** Export it: `set -a && . ./.env && set +a`.

`make termix-login` is the exception that proves the rule: it signs a *message*,
which spends nothing, so `MISQUOTE_DRY_RUN` does not cover it and `--authenticate`
is the guard instead.

---

## 9. Things that are not on `PATH`

Both fail soft and late, which is worse than failing loudly:

```bash
export PATH="$HOME/.foundry/bin:$PATH"   # forge, anvil — make vet-prove, make vectors
export PATH="$HOME/.local/bin:$PATH"     # uv — every make target
```

`scripts/setup_forge.sh` exits **0** with a warning when `forge` is missing, and
`proof.available()` uses `shutil.which`. So a machine with foundry installed but
not exported reports "no toolchain" and skips the proofs.
