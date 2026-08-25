.DEFAULT_GOAL := help
.PHONY: help setup lint fmt test test-all vectors vectors-check vectors-verify vectors-report vet-addresses addresses fork-diff replay-tests showcase-demo go-no-go-fast indexer indexer-follow tape-slice warden showcase advantage advantage-demo advantage-auto advantage-short assumptions artifacts status registry vet tearsheet web web-build web-static web-test web-check clean go-no-go judges vetting venue diagram api api-config api-worker showcase-auto registry-survey registry-scan venus venus-verify erc8183-verify router router-card og

UV     ?= uv
POOL   ?= $(TARGET_POOL)
ENV    ?= testnet
N      ?= 2000
CHAIN  ?= 56
# How many registry ids `make registry-survey` reads. See the target.
SAMPLE ?= 400
# Passed through to `make registry-scan`. `SCAN_ARGS=--no-census` takes the
# one-page reading instead of counting the chain — an hour shorter, and
# labelled a sample rather than a population.
SCAN_ARGS ?=
# The indexed tape. `showcase-auto` uses it when it exists and falls back to the
# labelled synthetic path when it does not; the scripts default to the same file.
DB_PATH ?= data/misquote.db
# ...and it is passed to the scripts, not only tested by the branches above.
#
# `showcase-auto` and `advantage-auto` decide which branch to take by testing
# `DB_PATH`, and then invoked scripts that read their own `--db` default. So the
# variable chose a branch and the branch read a different file: point DB_PATH at
# an empty database and `showcase-auto` correctly says "no tape", then runs a
# full replay of the real one. A knob that appears to configure something and
# does not is worse than no knob.
# Forked workers for the replay pools. Deliberately below cpu_count — see the
# `showcase` target for what the default cost.
JOBS ?= 3
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
# How much Venus history `make venus` reads. Seven days is 269 chunks and about
# half an hour; the rate tape's binding constraint is the 24h window floor in
# replay/allocation.py, which seven days clears with margin.
VENUS_DAYS ?= 7
ROUTER_CAPITAL ?= 10000

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

tape-slice:  ## the deployable tape: the last N days of every verified pool
	# `data/misquote.db` is 245MB and gitignored, and Render deploys from a
	# checkout — so without this the API's tape and quote routes come up 503 on
	# every host that is not this laptop. Writes data/deploy/tape.db, which is
	# committed, and refuses if the slice would claim coverage it does not hold.
	$(UV) run python scripts/slice_tape.py

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
	# `--jobs` defaults to cpu_count inside the script, and that default killed
	# two four-hour runs on a 16GB machine: the 252,923-event tape is ~165MB
	# resident, eight forked workers hold ~1.4GB between them because Python's
	# refcounting defeats copy-on-write, and with a node toolchain already
	# resident this was simply the largest new allocator when the kernel went
	# looking. Both runs died at the last agent, before any card was written.
	#
	# Three workers cost ~0.6GB and still deliver most of the speedup — the pool
	# is memory-bandwidth bound rather than core bound, so eight were buying
	# about 3x anyway. `nice` so it yields rather than competes.
	$(UV) run nice -n 10 python -u scripts/showcase.py --jobs $(JOBS) --db $(DB_PATH)

showcase-demo:  ## same, on a clearly-labelled synthetic tape (no chain data needed)
	$(UV) run python -u scripts/showcase.py --synthetic 9000

showcase-auto:  ## the cards from the indexed tape when there is one, the labelled synthetic tape when there is not
	# One decision, made by the thing that can actually make it.
	#
	# This used to be a shell `if [ -s "$(DB_PATH)" ]` picking between two
	# targets. That is a **file size** test standing in for "is there a tape",
	# and the two answers diverge: a database holding a schema and no rows is
	# non-empty on disk and empty as a tape, so the branch announced "tape
	# found", ran the chain path, and `showcase.py` exited 1 — taking every
	# downstream artifact with it.
	#
	# The fallback is not a nicety. A card built from real flow and a card built
	# from a random walk must never be indistinguishable, so the synthetic path
	# stays, stays labelled, and stays the answer when there is no tape.
	$(UV) run nice -n 10 python -u scripts/showcase.py --jobs $(JOBS) --db $(DB_PATH) \
		--fallback-synthetic 9000

advantage:  ## hired agent vs doing it yourself, on the indexed tape
	$(UV) run python -u scripts/advantage.py --db $(DB_PATH)

advantage-demo:  ## same, on a synthetic tape long enough to clear the 24h window floor
	$(UV) run python -u scripts/advantage.py --synthetic $(ADV_N)

erc8183-verify:  ## check the published ERC-8183 deployment against chain, three ways
	# The sibling of `venus-verify`, and it had no target at all — the script
	# existed, five prose references pointed at it, and nothing ran it. Its
	# readings justify two mainnet escrow addresses, so they are worth being
	# reproducible by a command rather than by a path somebody remembers.
	$(UV) run python scripts/verify_erc8183.py --chain $(CHAIN) --out

venus-verify:  ## check every Venus market against chain, three ways, and record it
	# The gate for the whole Yield category. Exits non-zero below two verified
	# markets, because a router with one venue has nothing to choose between —
	# every decision would be "stay" and the switching boundary would never be
	# consulted. Router publishes a withheld card until this exits zero.
	$(UV) run python scripts/verify_venus.py --chain $(CHAIN) --out

venus:  ## backfill the Venus rate tape (every market in one request per chunk)
	# `eth_getLogs` takes an address array, so the whole whitelist is one round
	# trip per chunk rather than one per market. Measured: 159,956 accruals over
	# seven days in 269 chunks, 29.6 minutes, on free endpoints, no key.
	$(UV) run python -u -m misquote.indexer.venus_backfill --days $(VENUS_DAYS)

router:  ## run Router against the recorded rate tape. It records rather than signs, by choice.
	$(UV) run python -m misquote.agents.router --capital $(ROUTER_CAPITAL)

router-card:  ## replay Router and write the card the site reads
	# Its own emitter rather than a fourth entry in `showcase.py`: Router
	# replays a *rate* tape with a different driver and a different quote type,
	# and folding it in would make sixty LP window replays — hours — a
	# prerequisite for regenerating a card that takes under a second.
	$(UV) run python -u scripts/router_showcase.py --capital $(ROUTER_CAPITAL) --db $(DB_PATH)

advantage-auto:  ## the report from the indexed tape when there is one, the labelled synthetic tape when there is not
	# `artifacts` depended on `advantage-demo`, which is `--synthetic $(ADV_N)`
	# writing the *default* --out and --artifact. Those are the same two paths
	# the chain run writes. So the judged deliverable — tasks run both ways on
	# real BSC flow — was overwritten by a random walk every time anybody ran
	# `make artifacts`, and the report said `synthetic` honestly while sitting
	# where the chain one had been.
	#
	# The branch that replaced it tested `[ -s "$(DB_PATH)" ]` — a file size —
	# to decide something only the script can see. It now asks the script.
	$(UV) run python -u scripts/advantage.py --db $(DB_PATH) --fallback-synthetic $(ADV_N)

advantage-short:  ## the same report on too little history — every task withheld
	$(UV) run python -u scripts/advantage.py --synthetic $(ADV_SHORT_N) \
		--out docs/AGENT_ADVANTAGE_SHORT.md \
		--artifact apps/web/public/artifacts/advantage_short.json

judges:  ## re-derive the measurable numbers in docs/FOR_JUDGES.md
	$(UV) run python scripts/sync_docs.py

diagram:  ## the whole system on one canvas -> MISQUOTE_FLOW.excalidraw
	# Reads no chain and no database. The layout is authored; every list and
	# every floor on the canvas is read out of the repo at generation time, so
	# the map cannot drift from the code the way a drawing does. Deterministic:
	# re-running with nothing changed rewrites the same bytes, and it refuses to
	# write at all if two nodes overlap or an arrow crosses a box it does not
	# touch.
	$(UV) run python scripts/gen_flow_diagram.py

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

registry:  ## republish the recorded registry survey as the site's artifact
	# Reads no chain. `make registry-survey` does the reading; this publishes
	# what it left behind — the same split as `make vet` / `make vetting`.
	#
	# It used to run with no --sample, which defaults to 0, which means "survey
	# not requested" — so `make artifacts` overwrote a real survey with a
	# refusal and took the third-party listings with it.
	$(UV) run python scripts/registry_report.py

registry-scan:  ## read 8004scan and record a second, independent count of the same registry
	# Alongside our own on-chain count, never instead of it. Ours comes from
	# binary search on `ownerOf` because `totalSupply()` reverts on the proxy;
	# theirs from an indexer. They disagree by about 3.6%, both are published
	# with the method named, and the gap is not resolved — nothing here can say
	# which is right, and picking the larger is the misquote.
	#
	# With SCAN8004_API_KEY exported this is a **census**: all 278,353 BSC agents
	# at 100 a page, so the artifact says `counted: 278,353 of 278,353` and the
	# shares carry no confidence interval, because nothing was inferred. Budget
	# an hour — the first full run took 68 minutes, and it is 8004scan's latency
	# that sets that, not the rate limit, which it never came close to. It also asks how many of
	# those agents anyone has ever left feedback on, which is the half of "is
	# this agent real" that `ownerOf` cannot answer.
	#
	# Without the key it still works at 10 requests a minute, and still splits
	# reading from publishing the way `--sample` does — but the only page it can
	# afford is the newest hundred, which is one platform's latest batch rather
	# than a draw from the registry. That reading is published under `sample`,
	# never `census`, and `tier` on every payload says which one answered.
	# `--no-census` takes the fast reading deliberately.
	#
	# Nothing here loads .env; export it, as with BSC_RPC_URL.
	$(UV) run python -u scripts/registry_report.py --scan $(SCAN_ARGS)

registry-survey:  ## read the ERC-8004 registry and record a sample. usage: make registry-survey SAMPLE=400
	# ~2.2s per agent against free endpoints: 400 ids is about fifteen minutes,
	# once, and it buys an interval worth publishing — at n=40 a 30% share spans
	# 18-46%, which is a different claim from "30%".
	$(UV) run python -u scripts/registry_report.py --sample $(SAMPLE)

venue:  ## PancakeSwap as an integration: where the fork is not the original (offline)
	$(UV) run python scripts/venue_report.py

# `assumptions` runs late, and the order is load-bearing. The sheet's
# `cited_by` is built by globbing every *other* artifact in the output
# directory, so an emitter that runs after it is invisible to it. Listed
# before them, the sheet only looked correct because the previous run's files
# were still on disk — on a clean checkout the citations would have been built
# from whatever happened to exist. `addresses` citing A1/P-6/P-8/V-10 is what
# surfaced it: the projection guard went red the moment that artifact appeared.
artifacts: showcase-auto router-card advantage-auto advantage-short registry venue vetting addresses vectors-report api-config assumptions judges status  ## every artifact the site reads
	# `judges` sits second-to-last on purpose: it derives its blocks from the
	# artifacts above it, and `status` runs the go/no-go gate — which now
	# checks the document is current, so it has to see the synced version.

api-config:  ## publish where the live API is, as apps/web/public/artifacts/api.json
	# Reads MISQUOTE_API_BASE. Unset publishes `base: null`, which is the honest
	# default: the export works with no backend, and a client that finds null must
	# not fall back to the site origin.
	$(UV) run python scripts/emit_api_config.py

api-worker:  ## drain the quote job queue (a replay is hours, not seconds)
	# Its own process, and not a thread inside the API: `ranges.quote()` keeps
	# per-run state in a module-level dict and raises if entered twice, and
	# `fork_map` must fork from a single-threaded parent. Run more of these for
	# more concurrency; each claims under BEGIN IMMEDIATE.
	$(UV) run python -m misquote.ops.worker

api:  ## the artifact API in dev mode, http://localhost:8000
	# The one command that runs the service had never been in this file: it
	# existed only in `service.py`'s docstring and in `render.yaml`'s
	# `startCommand`, so the deployed spelling was the only spelling anything
	# checked. `tests/api/test_app.py` asserts the module path here matches the
	# one Render runs.
	$(UV) run uvicorn misquote.api.service:app --reload --port 8000

web:  ## the front-end in dev mode, http://localhost:3000
	cd apps/web && pnpm dev

og:  ## regenerate the social card -> apps/web/public/opengraph-image.png
	# `src/app/opengraph-image.tsx` is the source; this is the copy the metadata
	# points at, and it exists only because the generated route exports without
	# a file extension and `make web-static` serves it as octet-stream.
	#
	# Deterministic: the same tree renders the same bytes, so a stale card shows
	# up as a diff rather than as a mystery. Same reason `public/artifacts/` is
	# committed.
	cd apps/web && NEXT_DIST_DIR=.next-og pnpm build >/dev/null
	cp apps/web/.next-og/card/opengraph-image apps/web/public/opengraph-image.png
	rm -rf apps/web/.next-og
	@echo "  -> apps/web/public/opengraph-image.png"

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
