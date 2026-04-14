# GIT_MEMORY.md — VantageAI
_Last updated: 2026-04-14_

## Current Branch
`fix/ui-finetune-dashboard`

## Open PRs
| # | Title | Branch |
|---|-------|--------|
| 56 | fix(ui): dashboard polish — layout, UX, accessibility, mobile | fix/ui-finetune-dashboard |

## Latest 15 Commits
```
b681a78 fix(ui): close modal via closeModal() on Escape/overlay to reset form fields
999fec8 fix(ui): dashboard polish — layout, UX, accessibility, mobile fixes
73c089f Merge pull request #55 from VantageAIOps/feat/free-tier-50k
bcf8362 fix: eliminate benchmark N+1 query bomb + test quality fixes
bc75328 fix: post-audit security and correctness fixes (round 3)
36e176f fix: remove dead kv_key column + surface Copilot/Datadog in connections panel
a523720 feat(tests+docs): add test suites 39-41 and document 10 new endpoints
b13c87b fix(audit2): address 12 issues from second security + logic review
80650db chore: update GIT_MEMORY.md for PR #55 state
5fef2f9 fix(security): address 14 audit findings across backend + frontend
f8c0fa5 docs(strategy): mark P2 tasks complete
a035691 feat(p2): Copilot UI, report nav, benchmark schema, Datadog exporter
5a49eca fix(security): address 8 code review issues in Copilot adapter + platform
c92ec9f feat(p2): Copilot adapter, enterprise pricing, report page
f88d064 feat(trust): add trust.vantageaiops.com security page + P1 fixes
```

## Recent Merged PRs
```
73c089f Merge PR #55 — feat/free-tier-50k (raise free tier 10K→50K events/month)
3e42e59 Merge PR #54 — feat/free-tier-50k
c08f5c5 Merge PR #53 — fix/ci-signup-rate-limit
b64accc Merge PR #52 — fix/otel-developer-id-attribute
073d96d Merge PR #51 — feat/vega-chatbot
```

## Package Versions
| Package | Version |
|---------|---------|
| vantage-worker | 1.0.0 |
| vantage-js-sdk | 1.0.1 |
| vantage-mcp | 1.1.1 |
| vantage-cli | (no package.json found) |

## Key Files
- `vantage-worker/src/index.ts` — Hono router, all route registrations
- `vantage-worker/src/routes/` — events, auth, analytics, cross-platform, benchmark, copilot, datadog
- `vantage-final-v4/app.html` — main dashboard SPA
- `vantage-final-v4/index.html` — marketing landing page
- `tests/suites/` — 17-41 active pytest suites (283+ checks)
- `migrations/` — D1 SQLite migrations 0001-0014

## Outstanding Items
- **PR #56** open: modal UX, SSE teardown, budget KPI exceeded state, nav link fixes, mobile CSS. Code reviewed; 1 fix pushed (closeModal on Escape/overlay).
- **Migration 0014** (`DROP COLUMN kv_key`): needs staging D1 verify before production apply
- **Datadog UI card** in app.html Settings tab: backend complete, frontend card not yet added
- **Deploy after PR #56 merges**: `npx wrangler deploy` + `npx wrangler pages deploy ./vantage-final-v4 --project-name=vantageai`
- Free tier copy raised 10K→50K (merged PR #55); `terms.html` may still reference old 10K limit — verify before next release
