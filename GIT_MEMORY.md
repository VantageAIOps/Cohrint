# GIT_MEMORY.md — VantageAI
_Last updated: 2026-04-15_

## Current Branch
`feat/enterprise-rbac-multiuser`

## Open PRs
| # | Title | Branch |
|---|-------|--------|
| 60 | feat(enterprise): multi-team RBAC, CEO dashboard, budget policies, team attribution | feat/enterprise-rbac-multiuser |
| 59 | fix(ui): landing page polish + dashboard chart/layout fixes | fix/landing-page-positioning |

## Latest 15 Commits
```
629635e feat(enterprise): P1/P2 gaps — budget enforcement, policy CRUD UI, live feed, alerts
6974fab chore: update GIT_MEMORY.md — PR #60 P0 fixes, outstanding P1/P2 items
0664316 fix(enterprise): P0 gaps — role allowlist, otel enriched fields, developer team
31d2a59 feat(enterprise): multi-team RBAC, CEO dashboard, budget policies, team attribution
54c3bdf chore: update GIT_MEMORY.md — PR #59 state
08a1cb3 fix(dashboard+auth): 9 remaining issues from rescan
249f655 fix(dashboard+auth): 11 crash/flow fixes from full audit
c69136d fix(dashboard): stale donut legend on empty period + mobile flex breakpoint
ba0aa10 fix(dashboard): 75/25 split layout for spend trend + donut cards
2e72278 fix(dashboard): reduce Tool Cost Share donut size + proper alignment
c4380ba fix(dashboard): chart proportions, connected tools stale dates, vega bot overlap
f8028ff fix(landing): fix footer wrapping on mobile
d394858 fix(landing): strip security implementation details + replace gmail with sales email
30df133 fix(landing): fix orphaned </div> + grammatically incomplete subheadline
93c6ea4 docs: add VantageAI guidebook v1.1 (PDF + DOCX)
```

## Recent Merged PRs
- #57 feat/claude-intelligence-customer-integration
- #56 fix/ui-finetune-dashboard
- #55 feat/free-tier-50k
- #54 feat/free-tier-50k
- #53 fix/ci-signup-rate-limit

## Package Versions
| Package | Version |
|---------|---------|
| vantage-worker | 1.0.0 |
| vantage-js-sdk | 1.0.1 |
| vantage-mcp | 1.1.1 |

## PR #60 — Enterprise RBAC Feature (feat/enterprise-rbac-multiuser)

### All items completed
- Role hierarchy: owner > superadmin > ceo > admin > member > viewer (ROLE_RANK)
- auth.ts: role allowlist fixed (ceo/superadmin no longer silently downgraded)
- auth.ts: privilege escalation guard on invite + PATCH member
- otel.ts: agent_name, team, business_unit extracted + stored in otel_events
- crossplatform.ts: /developer/:id returns team field; /live returns agent_name, team, token_rate_per_sec
- executive.ts: GET /v1/analytics/executive (ceo/superadmin/owner only)
- admin.ts: budget policies CRUD (POST/PUT/DELETE /v1/admin/budget-policies)
- admin.ts: GET /v1/admin/developers/recommendations
- events.ts: checkBudgetPolicy() — block/throttle enforcement at event ingestion
- events.ts: maybeSendBudgetAlert() wired after each insert
- analytics.ts: /teams COALESCE team_budgets + budget_policies for budget_pct
- app.html: executive dashboard view (ceo+ only in sidebar)
- app.html: budget alert sticky banner at 80%/100% spend
- app.html: + New Policy button + create/edit/delete modal in Budgets tab
- cp-console.js: live feed 4-column grid with agent_name, team, tok/s rate
- tests/43_enterprise_rbac: 9 sections, 55+ checks including ER-I escalation guard

### No outstanding items — ready for PR review + merge
