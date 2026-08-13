.DEFAULT_GOAL := help
.PHONY: help setup lint fmt test test-all vectors vectors-check fork-diff replay-tests indexer warden showcase tearsheet web clean

UV     ?= uv
POOL   ?= $(TARGET_POOL)
ENV    ?= testnet
N      ?= 2000

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

indexer:  ## backfill + follow the target pool. usage: make indexer POOL=0x...
	$(UV) run python -m misquote.indexer.backfill --pool $(POOL)
	$(UV) run python -m misquote.indexer.follow --pool $(POOL)

warden:  ## run the Warden loop. usage: make warden ENV=testnet|mainnet
	$(UV) run python -m misquote.agents.warden --env $(ENV)

showcase:  ## replay -> apps/web/public/artifacts/showcase.json
	$(UV) run python -m misquote.replay.driver --showcase

tearsheet:  ## journal -> docs/TEARSHEET.md, zero hand-entered numbers
	$(UV) run python -m misquote.tearsheet.render

web:  ## next.js dev server
	pnpm --filter web dev

clean:
	rm -rf .pytest_cache .ruff_cache htmlcov .coverage
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
