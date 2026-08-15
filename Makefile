.DEFAULT_GOAL := help
.PHONY: help setup lint fmt test test-all vectors vectors-check fork-diff replay-tests indexer indexer-follow warden showcase advantage advantage-demo advantage-short assumptions artifacts status registry vet tearsheet web web-build web-static web-test web-check clean go-no-go

UV     ?= uv
POOL   ?= $(TARGET_POOL)
ENV    ?= testnet
N      ?= 2000
CHAIN  ?= 56
FOLLOW_S ?= 3600
WARDEN_S ?= 600
# The advantage report cuts its tape into 20 overlapping sub-windows, each half
# the span, and refuses to quote a window shorter than the 24h policy horizon
# (ranges.MIN_WINDOW_HOURS). So the binding constraint is the tape's span in
# hours, not its event count. Measured, at the generator's ~25s mean gap:
#
#   N= 2000   span  13.8h   window  6.9h    0/20 usable
#   N= 6000   span  41.3h   window 20.6h    0/20 usable
#   N= 9000   span  62.2h   window 31.1h   20/20 usable
#
# The first committed report was withheld on all three tasks because it was
# generated below this line. 9,000 clears it with margin. The floor itself is
# not negotiable — we meet it, we do not lower it.
ADV_N  ?= 9000
# Deliberately below the floor: the same three tasks on 13.8h of history, which
# every one of them refuses to quote. Proof that the refusal is live machinery
# and not a story told about it.
ADV_SHORT_N ?= 2000

help:  ## show this help
	@grep -hE '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | awk -F':.*?## ' '{printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

setup:  ## install python + node + solidity deps
	$(UV) sync --all-extras
	@command -v pnpm >/dev/null && [ -f pnpm-workspace.yaml ] && pnpm install || true
	@scripts/setup_forge.sh

lint:  ## ruff check
	$(UV) run ruff check .
	$(UV) run ruff format --check .

fmt:  ## ruff autofix + format
	$(UV) run ruff check --fix .
	$(UV) run ruff format .

test:  ## fast suite — no network, no chain
	$(UV) run pytest

test-all:  ## everything including chainfork (needs anvil; see fork-diff)
	$(UV) run pytest -m ''

vectors:  ## differential-test against real v3 Solidity, then record the vectors
	$(UV) run python scripts/gen_vectors.py -n $(N)

vectors-check:  ## same comparison, writing nothing — the CI-shaped form
	$(UV) run python scripts/gen_vectors.py -n $(N) --check

fork-diff:  ## everything that needs a live chain or a fork
	$(UV) run pytest -m chainfork -v

replay-tests:  ## T1-T4 + L1 explicitly, against the committed 30d tape
	$(UV) run pytest tests/replay -m '' -v

indexer:  ## backfill the target pool. NEEDS A KEYED RPC. usage: make indexer POOL=0x...
	# 2,880 requests as fast as they will be served. Free endpoints refuse that
	# rate — measured: ~4 requests in 11s exhausts all three. Use indexer-follow
	# if you have no key.
	$(UV) run python -m misquote.indexer.backfill --pool $(POOL)

indexer-follow:  ## follow the pool forward at a rate free endpoints tolerate
	# The same read as the backfill at 1/60th the rate. Measured: 1 req/60s
	# sustains indefinitely, and BSC produces a 2,000-block chunk every ~15 min,
	# so this stays ahead of the chain without ever being refused. It cannot
	# recover history — only accumulate it going forward.
	$(UV) run python -m misquote.indexer.follow --seconds $(FOLLOW_S)

warden:  ## run the Warden against a live chain. It cannot sign: no chain executor exists.
	$(UV) run python -m misquote.agents.warden --chain $(CHAIN) --seconds $(WARDEN_S)

vet:  ## badge every listed pool from chain, and refuse to clear what it cannot read
	$(UV) run python -m misquote.vetting --chain $(CHAIN)

tearsheet:  ## journal -> docs/TEARSHEET.md, zero hand-entered numbers
	$(UV) run python -m misquote.tearsheet

clean:
	rm -rf .pytest_cache .ruff_cache htmlcov .coverage
	find . -name __pycache__ -type d -prune -exec rm -rf {} +

go-no-go:  ## the mainnet gate: runs every check and refuses to go green on an unverified one
	$(UV) run python scripts/go_no_go.py

go-no-go-fast:  ## same, without the test suites
	$(UV) run python scripts/go_no_go.py --fast

showcase:  ## replay the agents on the indexed tape and write the web artifacts
	$(UV) run python scripts/showcase.py

showcase-demo:  ## same, on a clearly-labelled synthetic tape (no chain data needed)
	$(UV) run python scripts/showcase.py --synthetic 9000

advantage:  ## hired agent vs doing it yourself, on the indexed tape
	$(UV) run python scripts/advantage.py

advantage-demo:  ## same, on a synthetic tape long enough to clear the 24h window floor
	$(UV) run python scripts/advantage.py --synthetic $(ADV_N)

advantage-short:  ## the same report on too little history — every task withheld
	$(UV) run python scripts/advantage.py --synthetic $(ADV_SHORT_N) \
		--out docs/AGENT_ADVANTAGE_SHORT.md \
		--artifact apps/web/public/artifacts/advantage_short.json

judges:  ## re-derive the measurable numbers in docs/FOR_JUDGES.md
	$(UV) run python scripts/sync_docs.py

assumptions:  ## docs/ASSUMPTIONS.md + REQUIREMENTS_MATRIX.md -> the linkable sheet
	$(UV) run python scripts/assumptions.py

status:  ## run every readiness gate and publish the result
	# Leading `-`: the gate exits 1 on NO GO and 2 on NOT YET, and NOT YET is
	# its current, correct answer. This target's job is to publish that verdict,
	# not to enforce it — `make go-no-go` is the one that enforces it, and its
	# exit code must keep meaning something.
	-$(UV) run python scripts/go_no_go.py --fast --json

registry:  ## ERC-8004 / ERC-8183 / AACP -> the registry artifact (offline by default)
	$(UV) run python scripts/registry_report.py

artifacts: showcase-demo advantage-demo advantage-short assumptions registry status  ## every artifact the site reads

web:  ## the front-end in dev mode, http://localhost:3000
	cd apps/web && pnpm dev

web-build:  ## static export -> apps/web/out (no node process needed to serve it)
	cd apps/web && pnpm build

web-static:  ## serve the export the way a judge with no toolchain would
	cd apps/web/out && python3 -m http.server 8080

web-test:  ## vitest: the component layer
	cd apps/web && pnpm test

web-check:  ## load the built site in a real browser: console errors + 390px overflow
	# Needs a browser: `cd apps/web && pnpm exec playwright install chromium`.
	# This is the only check that runs real layout, and it earns its keep — the
	# whole suite was green while every route but "/" fetched its artifacts from
	# a page-relative path and rendered an error state.
	cd apps/web && pnpm build
	cd apps/web/out && (python3 -m http.server 8099 & echo $$! > /tmp/misquote-web.pid) && sleep 2
	cd apps/web && node scripts/check-pages.mjs $(if $(SHOTS),--shots $(SHOTS),); \
		status=$$?; kill `cat /tmp/misquote-web.pid` 2>/dev/null; exit $$status
