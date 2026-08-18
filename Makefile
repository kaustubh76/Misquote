.DEFAULT_GOAL := help
.PHONY: help setup lint fmt test test-all vectors vectors-check vectors-verify vectors-report vet-addresses addresses fork-diff replay-tests showcase-demo go-no-go-fast indexer indexer-follow warden showcase advantage advantage-demo advantage-short assumptions artifacts status registry vet tearsheet web web-build web-static web-test web-check clean go-no-go judges vetting

UV     ?= uv
POOL   ?= $(TARGET_POOL)
ENV    ?= testnet
N      ?= 2000
CHAIN  ?= 56
FOLLOW_S ?= 3600
# Where `web-check` builds and serves from. Not `.next`, which `make web`
# is serving, and not `out/`, which `make web-build` writes.
WEB_CHECK_DIR ?= .next-check
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

indexer:  ## backfill the target pool. usage: make indexer POOL=0x...
	# 1,152 requests at 5,000 blocks for thirty days, and free endpoints serve
	# them: measured 16 Aug 2026, 1,151 chunks, zero refused, 62 minutes, no key.
	# The "NEEDS A KEYED RPC" this line used to carry was our own defect — two of
	# three configured endpoints served no logs at all, and the health check
	# tested chain id. See requirements-matrix P-11.
	#
	# Resumes from the ranges nobody has read, not from a cursor, so re-running
	# after a failure fills the holes rather than appending past them.
	$(UV) run python -u -m misquote.indexer.backfill --pool $(POOL)

indexer-follow:  ## follow the pool forward at a rate free endpoints tolerate
	# The same read as the backfill, one chunk per poll. BSC produces a
	# 5,000-block chunk every ~37 min and this asks once a minute, so it stays
	# ahead of the chain with room to spare and catches up from behind at ~4,800
	# blocks a poll. It cannot recover history — only accumulate it going
	# forward, and close a gap it left itself.
	#
	# Only three of 22 public endpoints serve eth_getLogs at all; the rest answer
	# for chain 56 and refuse every log query. `connect_all` probes for the
	# capability and prints the ones it skips.
	$(UV) run python -u -m misquote.indexer.follow --seconds $(FOLLOW_S)

warden:  ## run the Warden against a live chain. It records rather than signs, by choice.
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
	$(UV) run python -u scripts/showcase.py

showcase-demo:  ## same, on a clearly-labelled synthetic tape (no chain data needed)
	$(UV) run python -u scripts/showcase.py --synthetic 9000

advantage:  ## hired agent vs doing it yourself, on the indexed tape
	$(UV) run python -u scripts/advantage.py

advantage-demo:  ## same, on a synthetic tape long enough to clear the 24h window floor
	$(UV) run python -u scripts/advantage.py --synthetic $(ADV_N)

advantage-short:  ## the same report on too little history — every task withheld
	$(UV) run python -u scripts/advantage.py --synthetic $(ADV_SHORT_N) \
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

vetting:  ## republish the badges make vet left on disk as the site's artifact
	$(UV) run python scripts/vetting_report.py --chain $(CHAIN)

vet-addresses:  ## check every address in chain/addresses.py against chain, and record it
	# The reading half. Needs a reachable BSC RPC; `make addresses` republishes
	# whatever this leaves on disk and needs nothing.
	$(UV) run python scripts/verify_addresses.py --chain $(CHAIN) --out

addresses:  ## republish what vet-addresses recorded as the site's artifact
	$(UV) run python scripts/addresses_report.py --chain $(CHAIN)

vectors-verify:  ## replay the committed vectors and record what pytest said
	# The only thing allowed to claim the vectors were replayed, because it is
	# the only thing that watches the replay. Exits non-zero when it fails, so a
	# broken proof is not a quiet file change.
	$(UV) run python scripts/vectors_verify.py

vectors-report:  ## publish the vector corpus, and whatever replay was recorded
	# Reads files. Runs no test, deploys no contract, reaches no network — which
	# is what lets it sit inside `make artifacts`.
	$(UV) run python scripts/vectors_report.py

registry:  ## ERC-8004 / ERC-8183 / AACP -> the registry artifact (offline by default)
	$(UV) run python scripts/registry_report.py

# `assumptions` runs late, and the order is load-bearing. The sheet's
# `cited_by` is built by globbing every *other* artifact in the output
# directory, so an emitter that runs after it is invisible to it. Listed
# before them, the sheet only looked correct because the previous run's files
# were still on disk — on a clean checkout the citations would have been built
# from whatever happened to exist. `addresses` citing A1/P-6/P-8/V-10 is what
# surfaced it: the projection guard went red the moment that artifact appeared.
artifacts: showcase-demo advantage-demo advantage-short registry vetting addresses vectors-report assumptions status  ## every artifact the site reads

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
	# Builds into `$(WEB_CHECK_DIR)`, not `.next`, so this does not swap chunks
	# out from under a `make web` that is serving from the latter.
	#
	# **And serves the directory it just built**, which is the whole reason this
	# is a variable. Setting `distDir` moved the static export too: with the
	# default it lands in `out/`, and with an override it lands in the override.
	# For three commits this target built into `.next-check` and then served
	# `out/` — a build from before the override existed. It reported "every
	# route clean" against a site that had not been rebuilt in ninety minutes,
	# which is a worse failure than the one it was written to catch.
	cd apps/web && NEXT_DIST_DIR=$(WEB_CHECK_DIR) pnpm build
	# Fails loudly rather than serving a stale tree if the export moves again.
	test -f apps/web/$(WEB_CHECK_DIR)/index.html
	cd apps/web/$(WEB_CHECK_DIR) && (python3 -m http.server 8099 & echo $$! > /tmp/misquote-web.pid) && sleep 2
	cd apps/web && node scripts/check-pages.mjs $(if $(SHOTS),--shots $(SHOTS),); \
		status=$$?; kill `cat /tmp/misquote-web.pid` 2>/dev/null; exit $$status
