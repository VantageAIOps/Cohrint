# GIT_MEMORY.md — VantageAI
_Last updated: 2026-04-14_

## Current Branch
`feat/free-tier-50k`

## Open PRs
| # | Title | Branch |
|---|-------|--------|
| #55 | feat: P1+P2 sprint — trust page, Copilot adapter, enterprise pricing, report | feat/free-tier-50k |

## Latest 15 Commits
```
5fef2f9 fix(security): address 14 audit findings across backend + frontend
f8c0fa5 docs(strategy): mark P2 tasks complete — Copilot adapter, report page, enterprise tier, benchmark schema, Datadog exporter
a035691 feat(p2): Copilot UI, report nav, benchmark schema, Datadog exporter
5a49eca fix(security): address 8 code review issues in Copilot adapter + platform
c92ec9f feat(p2): Copilot adapter, enterprise pricing, report page
f88d064 feat(trust): add trust.vantageaiops.com security page + P1 fixes
8370400 docs(strategy): v6.0 — competitive intel update + priority reorder
0d2f499 feat(pricing): raise free tier copy from 10K to 50K events/month
ea242c7 fix(auth): remove duplicate rate-limit block that bypassed CI bypass
810309a fix(otel): recognize developer.id attribute for developer_id extraction
8c323dc fix(ci): remove vantage-cli from publish workflow — directory has no package.json
073d96d Merge pull request #51 from VantageAIOps/feat/vega-chatbot
5b7b56d fix(test): update test_unknown_model_uses_default_pricing for new contract
a03916a fix(test): CL.25 use regex instead of tomllib for Python <3.11 compat
bb21ee3 fix(ci): resolve 4 CI failures — FC.07a, ON.7, CL.20, SC.6/7/8
```

## Recent Merged PRs
```
073d96d PR #51 — feat/vega-chatbot (Vega AI assistant — final merge)
2833b7c PR #50 — feat/vega-chatbot
af09d35 PR #49 — fix/webkit-session-ci-warn
e9183a3 PR #48 — fix/webkit-session-ci-warn
139fae3 PR #47 — fix/webkit-session-ci-warn
```

## Package Versions
| Package | Version | Registry |
|---------|---------|----------|
| vantage-worker | 1.0.0 | Cloudflare Workers (api.vantageaiops.com) |
| vantage-js-sdk | 1.0.1 | npm |
| vantage-mcp | 1.1.1 | npm |
| vantage-local-proxy | 1.0.2 | npm |

## PR #55 — What's in it

### New routes (vantage-worker/src/routes/)
| File | Endpoints | Notes |
|------|-----------|-------|
| `copilot.ts` | POST/DELETE/GET /v1/copilot/connect, /status | HKDF-encrypted PAT in KV, daily cron |
| `benchmark.ts` | POST /v1/benchmark/contribute, GET /percentiles, /summary | k-anon floor ≥5, Sunday cron |
| `datadog.ts` | POST/DELETE /v1/datadog/connect, GET /status, sync | HKDF-encrypted key in D1, daily cron |
| `platform.ts` | POST /report-signup (added), /pageview, /session | IP rate-limit 5/hr |

### New migrations
| File | Tables |
|------|--------|
| `0009_copilot_connections.sql` | copilot_connections |
| `0010_platform_tables.sql` | platform_pageviews, platform_sessions |
| `0011_benchmark_snapshots.sql` | benchmark_cohorts, benchmark_snapshots, benchmark_contributions |
| `0012_datadog_connections.sql` | datadog_connections |
| `0013_schema_fixes.sql` | DROP platform_sessions.org_id; add session/copilot/datadog indexes |
| `0014_drop_copilot_kv_key.sql` | DROP kv_key column from copilot_connections |

### New/modified frontend
| File | Change |
|------|--------|
| `trust.html` + `trust-site/index.html` | Security/trust page for enterprise clients |
| `report.html` | "State of AI Coding Spend 2026" email-gated landing page |
| `signup.html` | Enterprise tier added |
| `app.html` | GitHub Copilot connect/disconnect card in settings |
| `index.html` | Report link in nav + footer; fake testimonials removed |
| `docs.html` | 8 doc fixes |

## Outstanding Items

### After PR #55 merges
- [ ] Run `cd vantage-worker && npx wrangler d1 migrations apply vantage-events --remote`
      (applies migrations 0009, 0010, 0011, 0012, 0013, 0014)
- [ ] Deploy worker: `cd vantage-worker && npx wrangler deploy`
- [ ] Deploy frontend: `npx wrangler pages deploy ./vantage-final-v4 --project-name=vantageai`
- [ ] Confirm trust.vantageaiops.com is live and serving trust-site/index.html

### Next P2/P3 tasks (PRODUCT_STRATEGY.md)
- [ ] Email 20 CTOs — design partner outreach (manual)
- [ ] Write + post Show HN (8am ET Tue/Wed)
- [ ] Decide brand/domain (vantageai.com vs vantageaiops.com)
- [ ] Semantic cache layer (Cloudflare Workers + Vectorize)
- [ ] Deploy n8n on Railway (onboarding drip)

### Known TOCTOU (low priority — accepted)
- platform.ts /report-signup IP rate limit uses read-then-write pattern; KV
  has no atomic compare-and-swap. Burst window is small enough to accept.

### Tech debt (carried over)
- [ ] DR.43 xfail marker — verify still needed (`pytest --runxfail`)
- [ ] CA.D3.4 WebKit test: restore `warn` → `chk` after SameSite=None deploys

## Key Files
| File | Purpose |
|------|---------|
| `vantage-worker/src/routes/copilot.ts` | GitHub Copilot Metrics API adapter |
| `vantage-worker/src/routes/benchmark.ts` | Anonymized benchmark data routes + cron |
| `vantage-worker/src/routes/datadog.ts` | Datadog metrics exporter |
| `vantage-worker/src/routes/platform.ts` | Public tracking + report signup |
| `vantage-final-v4/app.html` | Dashboard — Copilot card in settings |
| `vantage-final-v4/report.html` | "State of AI Coding Spend 2026" landing |
| `vantage-final-v4/trust.html` | Enterprise security/trust page |
| `trust-site/index.html` | Standalone deploy for trust.vantageaiops.com |
| `PRODUCT_STRATEGY.md` | v6.0 — competitive analysis, prioritized task list |
| `ADMIN_GUIDE.md` | Internal dev guide — §19 runbook, §20 research |
