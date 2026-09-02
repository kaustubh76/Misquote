#!/usr/bin/env python3
"""What the BNB Agent Studio actually offers, read rather than assumed.

The ledger parked this work item on *"the vendor's own site does not resolve and
their package's declared repository returns 404"*. Both halves are true. Neither
is a reason the CLI cannot be installed, and nobody had checked whether it
could: `@bnbagent/studio-cli` has been on npm the whole time.

That is the third work item in this repository parked on a blocker that did not
survive being checked, and the pattern is always the same — a reading taken once
and then quoted forward as though it had been re-taken. So this writes a **dated
record** with status codes in it, and the ledger cites the record instead of a
sentence.

## What this refuses to do

It installs the CLI and asks it what it can do. It does not deploy, does not
authenticate, does not read `.env`, and passes no key to anything. Deployment
through this vendor reportedly hands a wallet key to their Secrets Manager,
which is a decision about custody rather than a step in a probe, and it is not
this script's to make.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import tempfile
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
RECORD = REPO / "vetting" / "identity" / "studio-probe.json"

#: The subcommands worth asking about, and every one of them is asked the same
#: harmless question. `erc8183` is here because the vendor models the very calls
#: this repository could not complete — its help lists `submit` and `settle`,
#: which are exactly the two that revert on job 56681.
SUBCOMMANDS = ("erc8004", "erc8183", "x402", "deploy", "wallet", "doctor", "recipe")

PACKAGE = "@bnbagent/studio-cli"
REGISTRY = f"https://registry.npmjs.org/{PACKAGE}"

#: Every host the specification and the ledger name, checked together so the
#: record says which of them answered rather than which one somebody remembered.
ENDPOINTS = {
    "install_page": "https://studio.bnbchain.org/install",
    "product_page": "https://www.bnbchain.org/en/bnb-agent-studio",
    "declared_repository": "https://github.com/bnb-chain/bnbagent-studio",
}


def _http(url: str) -> dict[str, Any]:
    """Status code or the failure, never a verdict."""
    request = urllib.request.Request(url, method="GET", headers={"User-Agent": "misquote-probe"})
    try:
        with urllib.request.urlopen(request, timeout=20) as answer:  # noqa: S310 — fixed https
            return {"url": url, "status": answer.status, "reachable": True}
    except urllib.error.HTTPError as error:
        return {"url": url, "status": error.code, "reachable": True}
    except Exception as error:  # noqa: BLE001 — the failure is the reading
        return {"url": url, "status": None, "reachable": False, "error": f"{type(error).__name__}: {error}"}


def _dns(host: str) -> dict[str, Any]:
    try:
        return {"host": host, "resolves": True, "addresses": sorted({a[4][0] for a in socket.getaddrinfo(host, None)})}
    except socket.gaierror as error:
        return {"host": host, "resolves": False, "error": str(error)}


def _npm() -> dict[str, Any]:
    """The package the dead install page was supposed to hand you."""
    answer = _http(REGISTRY)
    if answer["status"] != 200:
        return {"published": False, **answer}
    with urllib.request.urlopen(REGISTRY, timeout=30) as body:  # noqa: S310 — fixed https
        data = json.loads(body.read())
    latest = data.get("dist-tags", {}).get("latest")
    return {
        "published": True,
        "name": data.get("name"),
        "latest": latest,
        "versions": len(data.get("versions", {})),
        "declared_repository": (data.get("repository") or {}).get("url"),
        "homepage": data.get("homepage"),
        "license": data.get("license"),
        "description": (data.get("description") or "")[:200],
    }


def _install_and_ask(version: str, timeout: int = 300) -> dict[str, Any]:
    """Install into a scratch directory and ask the CLI what it does.

    Nothing here is run beyond `--help`. A probe that authenticates is not a
    probe.
    """
    npm = shutil.which("npm")
    if npm is None:
        return {"installed": False, "reason": "npm is not on PATH"}

    with tempfile.TemporaryDirectory(prefix="studio-probe-") as scratch:
        install = subprocess.run(  # noqa: S603 — fixed argv, no shell
            [npm, "install", "--no-audit", "--no-fund", "--prefix", scratch, f"{PACKAGE}@{version}"],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=scratch,
        )
        if install.returncode != 0:
            return {
                "installed": False,
                "reason": (install.stderr or install.stdout).strip()[:600],
            }

        root = Path(scratch) / "node_modules" / PACKAGE.replace("/", os.sep)
        manifest = json.loads((root / "package.json").read_text()) if (root / "package.json").is_file() else {}
        binaries = manifest.get("bin") or {}

        def ask(executable: Path, argv: list[str]) -> dict[str, Any]:
            try:
                asked = subprocess.run(  # noqa: S603 — fixed argv, no shell
                    [str(executable), *argv, "--help"],
                    capture_output=True,
                    text=True,
                    timeout=60,
                    cwd=scratch,
                    # A probe that inherits the operator's environment is a probe
                    # that can authenticate by accident. Only PATH goes in.
                    env={"PATH": os.environ.get("PATH", ""), "NO_COLOR": "1", "CI": "1", "HOME": scratch},
                )
                return {"exit": asked.returncode, "help": (asked.stdout or asked.stderr).strip()[:4000]}
            except Exception as error:  # noqa: BLE001 — a CLI that will not answer is the reading
                return {"exit": None, "error": f"{type(error).__name__}: {error}"}

        helped: dict[str, Any] = {}
        for name in sorted(binaries):
            executable = Path(scratch) / "node_modules" / ".bin" / name
            if not executable.exists():
                continue
            helped[name] = ask(executable, [])
            for sub in SUBCOMMANDS:
                helped[f"{name} {sub}"] = ask(executable, [sub])

        return {
            "installed": True,
            "version": manifest.get("version"),
            "binaries": sorted(binaries),
            "dependencies": sorted(manifest.get("dependencies") or {}),
            "help": helped,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=RECORD)
    parser.add_argument("--skip-install", action="store_true", help="endpoints only")
    args = parser.parse_args()

    npm_data = _npm()
    print(f"npm {PACKAGE}  published={npm_data.get('published')}  latest={npm_data.get('latest')}")

    endpoints = {name: _http(url) for name, url in ENDPOINTS.items()}
    for name, answer in endpoints.items():
        print(f"  {name:22} {answer.get('status') or answer.get('error', '')}")

    dns = _dns("studio.bnbchain.org")
    print(f"  dns studio.bnbchain.org  resolves={dns['resolves']}")

    cli: dict[str, Any] = {"installed": False, "reason": "skipped"}
    if not args.skip_install and npm_data.get("published"):
        cli = _install_and_ask(str(npm_data.get("latest")))
        print(f"  cli installed={cli.get('installed')}  binaries={cli.get('binaries')}")

    record = {
        "read_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "subject": "BNB Agent Studio",
        "package": npm_data,
        "endpoints": endpoints,
        "dns": dns,
        "cli": cli,
        # The distinction the ledger got wrong, stated as the record's own claim.
        "installable": bool(cli.get("installed")),
        "install_page_reachable": bool(endpoints["install_page"].get("reachable")),
        "deployed": False,
        "why_not_deployed": (
            "This probe installs the CLI and reads its help. It does not deploy: "
            "deployment through this vendor reportedly hands a wallet key to their "
            "Secrets Manager, which is a custody decision rather than a probe step."
        ),
    }
    args.out.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    print(f"  -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
