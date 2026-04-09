# GIT_MEMORY.md — VantageAI
_Last updated: 2026-04-09_

## Current Branch
`feat/semantic-cache-analytics`

## Open PRs
| # | Title | Branch |
|---|-------|--------|
| #44 | feat: website enterprise overhaul + security hardening | feat/semantic-cache-analytics |

## Latest 15 Commits
```
22de6c4 fix(tests): add missing pytest import to test_dashboard_real_data.py
500901c docs(security): internal security audit report 2026-04-09 — 9 findings, 3 high fixed
03a344c feat(security): HSTS+COOP+CORP headers, brute-force on /session, prompt_hash validation, demo seed SQL
71407ce feat(app): add Docs nav link + XSS-safe demo banner for demo org session
9d85fba feat(website): Phase 2 enterprise redesign — indigo palette, new hero copy, security section, nav
a75c7e9 feat(website): Phase 1 content — remove fake reviews, tool names, false claims; fix pricing CTAs
be7839b docs: remove Windsurf/Zed/JetBrains, redact pricing algorithm and MD5 from public docs
343da10 docs: add website enterprise overhaul design spec
85fb67b fix(cache-analytics): resolve 4 code review issues
856969b chore: update GIT_MEMORY.md — semantic cache analytics + PR #43 state
e8996c2 test(dr43): mark xfail pending analytics.ts timeseries production deploy
7e7bcca docs+fix: redact infra IDs, update docs, improve agent API key UX
2f6ef42 fix(ci): resolve 5 pre-existing test failures in CI
e091262 feat(suite-37): cross-integration E2E dashboard cards test suite + analytics.ts fix
90baabe refactor(otel): replace inline MODEL_PRICES with shared lib/pricing.ts import
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
| vantage-worker | 1.0.0 | Cloudflare |
| vantage-js-sdk | 1.0.1 | npm |
| vantage-mcp | 1.1.1 | npm |
| vantage-local-proxy | 1.0.2 | npm |
| vantage-agent (Python) | 0.1.0 | PyPI |

## Key Files Changed in PR #44 (vs main)
- `vantage-final-v4/index.html` — enterprise redesign: indigo palette, hero copy, fake reviews removed, comparison table, security section, pricing mailto CTAs
- `vantage-final-v4/docs.html` — Windsurf/Zed/JetBrains removed; pricing algo + MD5 redacted
- `vantage-final-v4/app.html` — Docs nav link + XSS-safe demo banner
- `vantage-final-v4/_headers` — HSTS, COOP, CORP, frame-ancestors added
- `vantage-final-v4/demo-seed.sql` — new: fixed 54-event demo org seed data
- `vantage-worker/src/routes/auth.ts` — brute-force rate limit on /v1/auth/session
- `vantage-worker/src/routes/events.ts` — prompt_hash hex format validation
- `docs/security-audit-2026-04-09.md` — new: internal security audit report

## Outstanding Items
- **PR #44 pending merge** — website overhaul + security (open)
- **Manual: demo seed** — generate SHA-256 of demo viewer key, run demo-seed.sql via wrangler d1 execute
- **Deploy after merge** — `npx wrangler deploy` + `npx wrangler pages deploy ./vantage-final-v4`
- **DR.43 xfail → pass** — timeseries test is now xpassing in prod; remove xfail marker after PR #44 merges
- **Deferred security** — localStorage cache (DEFER-001), CSP unsafe-inline (DEFER-002); see security-audit-2026-04-09.md
- **Pre-existing** — `test_sse_stream_after_otel_ingest` fixture error in suite 17 (api_key fixture missing)
- **Billing API connectors** (L3) — roadmap
- **Local file scanner** (L2) — roadmap
- **Browser extension** (L4) — roadmap
