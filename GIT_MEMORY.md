# GIT_MEMORY.md — VantageAI
_Last updated: 2026-04-09_

## Current Branch
`feat/semantic-cache-analytics`

## Open PRs
| # | Title | Branch |
|---|-------|--------|
| #43 | feat: semantic cache analytics + cross-integration E2E dashboard tests + CI fixes | feat/semantic-cache-analytics |

## Latest 15 Commits
```
e8996c2 test(dr43): mark xfail pending analytics.ts timeseries production deploy
7e7bcca docs+fix: redact infra IDs, update docs, improve agent API key UX
2f6ef42 fix(ci): resolve 5 pre-existing test failures in CI
e091262 feat(suite-37): cross-integration E2E dashboard cards test suite + analytics.ts fix
90baabe refactor(otel): replace inline MODEL_PRICES with shared lib/pricing.ts import
1a3860a fix(tests): add conftest.py + fix fresh_account usage in 36_semantic_cache
6d955fb feat(semantic-cache): Phase 1+2 — cache analytics KPIs + exact-match dedup detection
f7a86e9 fix(docs): remove remaining TypeScript syntax from plain script tag
5935d9d fix(docs): update CLI path 3 to Python agent, fix hook link and JS syntax
d61cbce fix(docs): correct D1 database name vantageai-db → vantage-events
43a65f2 ci: reduce GitHub Actions usage to stay within 2,000 min/month free tier
e5f98fb fix(deploy): use custom_domain route binding
a81313b Merge pull request #41 from Amanjain98/feat/session-centric-integration
8de13bd test(suite-34): add Gemini CLI + Codex CLI session rollup tests
760f742 chore: update GIT_MEMORY.md
```

## Recent Merged PRs
| PR | Branch |
|----|--------|
| #41 | feat/session-centric-integration |
| #40 | feat/cleanup-mobile-otel |
| #39 | fix/audit-log-event-names |
| #38 | feat/vantage-agent-python |
| #37 | chore/cli-dead-code-cleanup |

## Package Versions
| Package | Version | Registry |
|---------|---------|---------|
| vantage-mcp | 1.1.1 | npm |
| vantage-local-proxy | 1.0.2 | npm |
| vantage-agent (Python) | 0.1.0 | PyPI |

## Key Files Changed in PR #43 (vs main)
- `vantage-worker/src/routes/analytics.ts` — timeseries/today/models now query cross_platform_usage; semantic cache KPIs added
- `vantage-worker/src/routes/events.ts` — prompt_hash dedup detection (KV-backed)
- `vantage-worker/src/lib/pricing.ts` — shared MODEL_PRICES (new file)
- `tests/suites/36_semantic_cache/` — Phase 1+2 cache analytics tests
- `tests/suites/37_all_dashboard_cards/` — 90-test cross-integration E2E suite
- `tests/suites/20_dashboard_real_data/` — DR.43 xfail (timeseries fix pending deploy)
- `ADMIN_GUIDE.md` — infra IDs redacted
- `PRODUCT_STRATEGY.md` — delivery history updated; completed items marked DONE
- `vantage-agent/vantage_agent/api_client.py` — interactive API key setup on first run
- `.github/workflows/ci-test.yml` — pip install -e vantage-agent added

## Outstanding Items
- **Deploy analytics.ts fix** — timeseries/today/models querying wrong table in prod (DR.43 is xfail until deployed)
- **vantage-cli test harnesses missing** — test-session-persist.ts, test-renderer.ts, test-agent-config.ts, test-recommendations.ts; suites 35_cli_agent + 35_recommendations fail until created
- **Stale assertions** — suites 22 (LP16/17), 23 (SG35-38), 24 (DC09/14) need HTML/docs updates
- **Billing API connectors** (L3) — roadmap
- **Local file scanner** (L2) — roadmap
- **Browser extension** (L4) — roadmap
