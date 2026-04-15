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
f470821 feat(enterprise): implement all P0/P1 gaps from business case analysis
8ec0ef7 chore: update GIT_MEMORY.md — all P1/P2 items complete, PR #60 ready for review
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

## PR #60 Status — Enterprise RBAC (feat/enterprise-rbac-multiuser)
All P0 + P1 gaps implemented. Ready for review + merge.

### Completed (this branch, 5 commits)
**Schema & Data Layer**
- migration/0015: business_unit/team/agent_name to otel_events; budget_policies enhancements
- migration/0016: developer_email + business_unit to events table; 6 compound indexes

**Backend Routes**
- auth.ts: full role hierarchy (owner>superadmin>ceo>admin>member>viewer); invite allowlist fixed; escalation guard; logAudit on PATCH
- executive.ts: GET /v1/analytics/executive (ceo+ only); UNION events+cross_platform_usage
- admin.ts: budget policies CRUD; GET /developers/recommendations; GET /budget-alerts?threshold_pct
- admin.ts: GET /audit-log now supports ?since, ?until, ?actor_role, ?resource_type, ?event_name
- analytics.ts: GET /business-units (spend per BU×team×provider); /teams COALESCE budget_policies
- crossplatform.ts: GET /active-developers (live presence); ?business_unit= filter on /developers
- events.ts: checkBudgetPolicy() enforcement at ingest; maybeSendBudgetAlert wired
- superadmin.ts: logAuditRaw on all 7 route handlers

**Frontend**
- app.html: Executive view (ceo+); budget alert sticky banner; + New Policy modal; Active Now card
- app.html: Members table Spend MTD + Rec columns; invite modal adds ceo/superadmin options
- cp-console.js: live feed 4-col grid (agent_name, team, tok/s); dev modal Recommendations section

**Tests**
- tests/suites/43_enterprise_rbac: 14 sections (ER-A through ER-N), 80+ checks

### No remaining outstanding items
