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
0664316 fix(enterprise): P0 gaps — role allowlist, otel enriched fields, developer team
31d2a59 feat(enterprise): multi-team RBAC, CEO dashboard, budget policies, team attribution
54c3bdf chore: update GIT_MEMORY.md — PR #59 state, branch fix/landing-page-positioning
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
0b3cb76 chore: update GIT_MEMORY.md — PR #58 state
4dd249f fix(landing): remove algo exposure, reframe hero for enterprise buyers
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

## Outstanding Items (PR #60 — enterprise RBAC)

### Fixed this session (0664316)
- auth.ts: role allowlist now includes ceo/superadmin; privilege escalation guard added
- otel.ts: agent_name, team, business_unit extracted + stored in otel_events INSERT
- crossplatform.ts: /developer/:id returns team field
- tests/43: ER-I suite (role preservation + escalation block)

### Still outstanding (P1/P2)
- events.ts: no budget enforcement at event ingestion (block/throttle policies ignored)
- alerts.ts: hardcoded thresholds, budget_policies table not consulted
- analytics.ts: /v1/analytics/teams JOINs team_budgets only, not budget_policies
- Frontend: no CREATE/EDIT/DELETE UI for budget policies (Budgets tab read-only)
- Frontend: Members tab missing per-member spend/savings columns
- Frontend: no budget alert banner/toast at 80%/100%
- Frontend: no global team filter in Overview/Spend tabs
- Frontend: live feed renderCpLiveFeed missing agent_name, token_rate_per_sec, team columns
