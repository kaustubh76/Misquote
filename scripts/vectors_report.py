"""Publish what is in `tests/core/vectors/`, and what — if anything — replayed it.

    python scripts/vectors_report.py

`docs/FOR_JUDGES.md` has always opened its proof table with *19,546 comparisons
against the real Solidity, exact integer equality, zero mismatches*. The website
has never said a word about it, which is the state `/vetting` was in one pass
ago: a real check, running, writing to a place nothing rendered.

## This script runs nothing

It compiles no Solidity, deploys to no chain, and executes no test. It reads
files. That is the same discipline `scripts/vetting_report.py` follows — `make
vet` does the chain reading, and the report republishes what it left behind —
and it is what lets this sit inside `make artifacts` without foundry, an anvil
or a network.

## Two blocks that must never be conflated

**`corpus`** is a projection: how many cases per function, the seed, the pinned
upstream commits, a digest per file. All of it is true of files on disk and all
of it is cheap to re-derive, so `tests/web/test_artifact_projections.py` asserts
the published copy still matches.

**`verification`** is the record of an execution. The vectors are Solidity's
recorded *answers*; whether this Python still reproduces them is a claim about a
test run. If no run has been recorded, the field says so and the page renders a
refusal — never a green number, and never silence.

Two different runs can verify, and they verify different things:

  - **replay** — `tests/core/test_vectors.py` against the committed answers.
    No network, no fork, no foundry. Runs on every commit inside `make test`.
  - **differential** — `make vectors-check`, which redeploys the Solidity and
    regenerates the whole comparison. Needs foundry and a local anvil.

`FOR_JUDGES.md` row 1 has been quoting the differential's headline while the
number a reader can actually see on disk is the corpus. They coincide by
construction — same seed, same n — and they mean different things, so they are
reported apart.

## `corpus_matches`, which is the mechanism that matters

A receipt records the digests it saw. This script re-digests the files as they
are now and compares. `make vectors` can regenerate the corpus at any moment,
and a receipt written before that ran is a statement about files that no longer
exist — the exact shape of every stale-artifact defect this repo has had. So the
comparison happens at publish time, and a receipt that no longer describes the
corpus is reported as stale rather than as a pass.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from misquote.tearsheet import provenance, vectors

REPO = Path(__file__).resolve().parents[1]
DEFAULT_OUT = REPO / "apps" / "web" / "public" / "artifacts" / "vectors.json"

#: Where `scripts/vectors_verify.py` leaves what it observed.
RECEIPT = REPO / "vetting" / "runs" / "vectors-replay.json"
#: Where `scripts/gen_vectors.py --check` leaves what it observed.
DIFFERENTIAL_RECEIPT = REPO / "vetting" / "runs" / "vectors-differential.json"

WITHHELD_REPLAY = (
    "no replay has been recorded — run `make vectors-verify`, which replays "
    "tests/core/test_vectors.py against the committed answers"
)
WITHHELD_DIFFERENTIAL = (
    "no differential run has been recorded — `make vectors-check` redeploys the "
    "reference Solidity and needs foundry and a local anvil"
)


def read_receipt(path: Path, current: dict[str, Any], withheld: str) -> dict[str, Any]:
    """A recorded run, checked against the corpus as it stands now.

    Absent, unreadable and stale are three different sentences and this returns
    three different answers. Collapsing them is how "we did not look" comes to
    look like "we looked and it was fine".

    `withheld` is a parameter because two runs read through here now and they
    have different remedies — one is a pytest replay, the other redeploys
    Solidity to an anvil. It was hardcoded to the replay's sentence, which would
    have told a reader with no differential receipt to run the wrong command.
    """
    if not path.is_file():
        return {"recorded": False, "reason": withheld}

    try:
        receipt = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        return {
            "recorded": False,
            "reason": f"{path.relative_to(REPO)} could not be read: {error}",
        }

    now = {g["group"]: g["sha256"] for g in current["groups"]}
    then = dict(receipt.get("digests", {}))
    moved = sorted(group for group in set(now) | set(then) if now.get(group) != then.get(group))

    return {
        **{k: v for k, v in receipt.items() if k != "digests"},
        "recorded": True,
        # Recomputed here, never copied from the receipt. A run cannot be
        # trusted to report whether it has since been invalidated.
        "corpus_matches": not moved,
        "corpus_moved": moved,
        "receipt": str(path.relative_to(REPO)),
    }


def build(
    out: Path,
    receipt: Path = RECEIPT,
    differential: Path = DIFFERENTIAL_RECEIPT,
) -> dict[str, Any]:
    corpus = vectors.corpus()
    return {
        "corpus": corpus,
        "verification": {
            "replay": read_receipt(receipt, corpus, WITHHELD_REPLAY),
            # Both through the same reader, so both get the same digest
            # re-check. This field was hardcoded to `{"recorded": False}` for as
            # long as nothing wrote a receipt — while `FOR_JUDGES.md` row 1 was
            # already quoting the differential's headline. The claim that makes
            # a fork comparison meaningful was asserted in a document and
            # refused on the page.
            "differential": read_receipt(differential, corpus, WITHHELD_DIFFERENTIAL),
        },
        "build": provenance.build_stamp(
            "python scripts/vectors_report.py",
            source="vector files on disk",
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--receipt", default=str(RECEIPT))
    parser.add_argument("--differential", default=str(DIFFERENTIAL_RECEIPT))
    args = parser.parse_args()

    out = Path(args.out)
    payload = build(out, Path(args.receipt), Path(args.differential))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")

    corpus = payload["corpus"]
    print(f"  corpus         {corpus['cases']:,} cases in {len(corpus['groups'])} groups")
    print(f"  pinned         {', '.join(p['name'] for p in corpus['pins']) or 'nothing'}")
    # Both verifications, not just the replay. The differential's line was never
    # printed because nothing could ever write its receipt, so the terminal
    # agreed with the page that there was only one check here.
    for name, run in payload["verification"].items():
        print(f"  {name:<14} {_line(run)}")
    print(f"  -> {out}")
    return 0


def _line(run: dict[str, Any]) -> str:
    if not run["recorded"]:
        return f"not recorded — {run['reason']}"
    if not run["corpus_matches"]:
        return f"STALE — these groups moved since: {run['corpus_moved']}"
    return f"{run.get('outcome')} — {run.get('summary_line')}"


if __name__ == "__main__":
    raise SystemExit(main())
