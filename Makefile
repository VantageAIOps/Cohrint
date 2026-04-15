# Cohrint — Developer Makefile
# Provides consistent commands for local dev and CI/CD
#
# Usage:
#   make test           — run fast API tests (no browser required)
#   make test-all       — run all suites including UI tests
#   make test-suite N=4 — run a single suite (e.g. suite 04)
#   make test-ci        — run the subset used in GitHub Actions CI
#   make deploy         — deploy frontend to Cloudflare Pages
#   make deploy-worker  — deploy API Worker to Cloudflare Workers
#   make install        — install all dev dependencies

PYTHON    ?= python3
PIP       ?= pip3
TESTS_DIR  = tests

.PHONY: install test test-all test-suite test-ci test-smoke deploy deploy-worker lint

## Install all development dependencies
install:
	npm ci
	cd vantage-worker && npm ci
	$(PIP) install requests structlog
	@echo "Optional: pip install playwright && python -m playwright install chromium"

## Run API-only test suites (no browser — fast, for local dev)
test:
	$(PYTHON) $(TESTS_DIR)/run_suite.py --fast --no-report

## Run all suites including extended (11-21), skip stress
test-all:
	$(PYTHON) $(TESTS_DIR)/run_suite.py --all --fast --no-report

## Run a specific suite: make test-suite N=04
test-suite:
	$(PYTHON) $(TESTS_DIR)/run_suite.py --suite $(N) --no-report

## Run the CI test subset (suites 01-10 + 21, skip load/stress, no browser)
test-ci:
	HEADLESS=1 $(PYTHON) $(TESTS_DIR)/run_suite.py --fast --no-report

## Quick smoke test — verify API and frontend are live
test-smoke:
	@echo "Checking API health..."
	@curl -sf https://api.cohrint.com/v1/health | python3 -c "import sys,json; d=json.load(sys.stdin); print('✅ API:', d.get('status','ok'))" || echo "❌ API unreachable"
	@echo "Checking frontend..."
	@curl -sf -o /dev/null -w "✅ Frontend: HTTP %{http_code}\n" https://cohrint.com/ || echo "❌ Frontend unreachable"

## Deploy frontend to Cloudflare Pages
deploy:
	npx wrangler pages deploy ./vantage-final-v4 --project-name=cohrint --branch=main

## Deploy API Worker to Cloudflare Workers
deploy-worker:
	cd vantage-worker && npm run deploy

## TypeScript type check
lint:
	cd vantage-worker && npm run typecheck
