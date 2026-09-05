"""`.env.example` must name every variable the code actually reads.

This exists because the template had drifted, and drifted in the worst possible
direction: it asked for `WARDEN_PRIVATE_KEY` and `MISQUOTE_POSITION_CAP_USD`,
neither of which anything reads, while omitting `MISQUOTE_PRIVATE_KEY` and
`MISQUOTE_POSITION_CAP_QUOTE`, which the signer and the go/no-go do.

Someone filling that file in carefully, with real credentials, would have ended
up with a configuration that did nothing — and nothing would have said so. The
signer would report "no private key", having been handed one under a name it has
never looked for.

A config template is a promise about what the program reads. This is the test
that keeps the promise true.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EXAMPLE = REPO / ".env.example"

NAME = re.compile(r"^[A-Z][A-Z0-9_]{2,}$")


def _env_names_in(node: ast.AST) -> set[str]:
    """Every environment-variable name mentioned anywhere inside an access.

    Walked with the AST rather than matched with a regex, because the first
    version of this test used `os\\.environ\\.get\\("([A-Z_]+)"` and missed

        os.environ.get("BSC_RPC_URL" if chain_id == 56 else "BSC_TESTNET_RPC_URL")

    A detector that *under*-reports is the dangerous kind here: it would let a
    variable go missing from the template while reporting that none were.
    """
    return {
        child.value
        for child in ast.walk(node)
        if isinstance(child, ast.Constant)
        and isinstance(child.value, str)
        and NAME.match(child.value)
    }


def _variables_the_code_reads() -> set[str]:
    found: set[str] = set()
    for path in [*(REPO / "packages").rglob("*.py"), *(REPO / "scripts").glob("*.py")]:
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            # os.environ["X"] / os.environ.get(...) / os.getenv(...) / getenv(...)
            if isinstance(node, ast.Subscript) and _is_environ(node.value):
                found |= _env_names_in(node.slice)
            elif isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Attribute) and func.attr in ("get", "getenv"):
                    if func.attr == "getenv" or _is_environ(func.value):
                        found |= _env_names_in(node)
                elif isinstance(func, ast.Name) and func.id == "getenv":
                    found |= _env_names_in(node)
    return found - SYSTEM


#: Variables the operating system owns, which `.env.example` must not claim.
#:
#: `scripts/probe_studio.py` builds a deliberately minimal environment for the
#: subprocess it probes — `PATH` and nothing else that could authenticate it —
#: and reading `PATH` to do that is not this program asking to be configured.
#: Listing it in the template would invite someone to set it, which is the
#: opposite of the point.
SYSTEM = {"PATH", "HOME", "TMPDIR", "LANG", "SHELL", "USER"}


def _is_environ(node: ast.AST) -> bool:
    return isinstance(node, ast.Attribute) and node.attr == "environ"


def _variables_the_template_mentions() -> set[str]:
    text = EXAMPLE.read_text()
    # Assigned (`NAME=`) or explicitly listed as not wired to anything, which is
    # itself a claim worth making rather than a silence.
    assigned = set(re.findall(r"^([A-Z_][A-Z0-9_]*)=", text, re.M))
    documented = set(re.findall(r"^#\s*([A-Z_][A-Z0-9_]*)\s", text, re.M))
    return assigned | documented


def test_every_variable_the_code_reads_is_in_the_template() -> None:
    """The direction that silently breaks a real setup."""
    missing = sorted(_variables_the_code_reads() - _variables_the_template_mentions())
    assert not missing, (
        f".env.example does not mention {missing} — someone filling it in would "
        "produce a config the program ignores, and nothing would say so"
    )


def test_the_template_does_not_ask_for_things_nothing_reads() -> None:
    """The other direction: a name in the template is a promise it is read.

    Variables that exist for tooling outside `packages/` and `scripts/` are
    exempt by listing them here, with the reason — the point is that each
    exemption is a decision someone made, not an accident nobody noticed.
    """
    read_elsewhere = {
        # anvil forks from these; consumed by the Makefile and the fork tests.
        "BSC_FORK_RPC_URL",
        "BSC_ARCHIVE_RPC_URL",
        # Read by tests and by CLI defaults rather than by os.environ.
        "TARGET_POOL",
        "TARGET_CHAIN_ID",
        "CEX_FEED_URL",
        # Read by the web app in TypeScript, which this scanner does not parse.
        # `apps/web/src/lib/wagmi.ts` adds the WalletConnect connector only when
        # it is set, so it is wired — just not from Python.
        "NEXT_PUBLIC_WC_PROJECT_ID",
    }
    assigned = set(re.findall(r"^([A-Z_][A-Z0-9_]*)=", EXAMPLE.read_text(), re.M))
    orphans = sorted(assigned - _variables_the_code_reads() - read_elsewhere)
    assert not orphans, (
        f"{orphans} are assignable in .env.example but nothing reads them. Either "
        "wire them up, or move them to the 'not wired to anything' section so "
        "their absence is not mistaken for an omission"
    )


def test_the_dry_run_default_is_documented_as_the_default() -> None:
    """A missing config must refuse to trade, and the template must say so —
    it is the one line a reader most needs to trust."""
    text = EXAMPLE.read_text()
    assert "MISQUOTE_DRY_RUN=1" in text
    assert "never sign" in text or "refuses to trade" in text


def test_the_template_does_not_contain_a_filled_in_secret() -> None:
    """A template is copied; a template with a real key in it is a leak."""
    text = EXAMPLE.read_text()
    # `[^\S\n]` is horizontal whitespace only. `\s*` crosses newlines, so the
    # first version of this matched the `#` opening the next comment block and
    # reported a leak in an empty template.
    assert not re.search(r"^MISQUOTE_PRIVATE_KEY=[^\S\n]*\S", text, re.M)
    assert not re.search(r"0x[0-9a-fA-F]{64}", text), "a 32-byte hex key is in the template"


def test_the_secret_check_actually_detects_a_secret(tmp_path) -> None:
    """A guard nobody has seen fire is a guard nobody knows works.

    Both regexes in the test above were wrong on the first attempt — `\\s*` ate
    the newline and matched the next comment block — so the negative case is
    checked explicitly rather than inferred from the positive one passing.
    """
    leaked = "MISQUOTE_PRIVATE_KEY=0x" + "a" * 64 + "\n"
    assert re.search(r"^MISQUOTE_PRIVATE_KEY=[^\S\n]*\S", leaked, re.M)
    assert re.search(r"0x[0-9a-fA-F]{64}", leaked)

    empty = "MISQUOTE_PRIVATE_KEY=\n\n# next section\n"
    assert not re.search(r"^MISQUOTE_PRIVATE_KEY=[^\S\n]*\S", empty, re.M)
