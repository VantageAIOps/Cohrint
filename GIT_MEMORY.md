# GIT_MEMORY — Cohrint / VantageAI

_Last updated: 2026-04-17_

## Current Branch
`feat/cost-forecasting-widget` — PR #70 open, in progress.

## Open PRs
| PR | Title | Branch |
|----|-------|--------|
| #70 | feat: cost forecasting widget (projected_month_end_usd, daily_avg_cost_usd, days_until_budget_exhausted) | feat/cost-forecasting-widget |

## Latest 15 Commits
| SHA | Message |
|-----|---------|
| `234c876` | fix(audit): full audit sprint — security, RBAC, date-type bugs, dead code |
| `0aedeef` | Merge pull request #67 from VantageAIOps/fix/dashboard-role-visibility-and-date-bugs |
| `10fdae1` | feat: suite 51 — Playwright + API dashboard role visibility tests (49 checks) |
| `2c6e9fe` | fix: add nav() guard for integrations view (non-admin redirect to overview) |
| `b1fcc6f` | fix: replace unix timestamps with text dates across all analytics routes |
| _(commits from PRs #65/#66 below)_ | |
| — | feat: agent trace DAG visualization + public benchmark dashboard (PR #66) |
| — | feat: semantic cache (Vectorize + Workers AI) + prompt registry MVP (PR #65) |
| `9ead355` | Fix 3 code-review issues: bind order, route shadowing, COALESCE defaults |
| `b9fa9b0` | feat: semantic cache (Vectorize + Workers AI) + prompt registry MVP |
| `d04ab96` | Merge pull request #64 from VantageAIOps/fix/code-review-issues |
| `97d7229` | Fix 4 remaining code-review issues: N+1 budget queries, IP token bypass, cache suppression, MCP URIs |
| `9dcbd68` | Fix 6 code-review issues: key hint, privilege escalation, batch budget, seed event_id, cache prefix, calcCost |
| `52b1a0a` | Fix 5 code-review issues: Infinity validation, token double-count, cache suppression, empty_reason, QS.07 test |
| `06e7603` | Fix 15 hallucination detection and recommendation engine bugs |

## Recent Merged PRs
| PR | Title |
|----|-------|
| #67 | fix: full security/RBAC audit, date-type bug fixes, dead code removal |
| #66 | feat: agent trace DAG visualization + public benchmark dashboard |
| #65 | feat: semantic cache (Vectorize + Workers AI) + prompt registry MVP |
| #64 | Fix 11 code-review issues: security, budget enforcement, cost accuracy, test correctness |
| #63 | Fix stale vantageaiops references (CORS, hook env vars, drop claude-code publish) |
| #62 | SEO verification + account hierarchy + cohrint rebrand |
| #61 | chore: rebrand VantageAI → Cohrint + security fixes |
| #60 | feat(enterprise): multi-team RBAC, CEO dashboard, budget policies, team attribution |

## Package Versions
| Package | Path | Version |
|---------|------|---------|
| cohrint-cli | cohrint-cli/package.json | 2.2.4 |
| cohrint-mcp | cohrint-mcp/package.json | 1.1.1 |
| cohrint-js-sdk | cohrint-js-sdk/package.json | 1.0.1 |

## Outstanding Items
- **PR #70 open** — cost forecasting widget: `projected_month_end_usd`, `daily_avg_cost_usd`, `days_until_budget_exhausted`
- **API key rotation needed** — rotate any keys that were logged during the `vnt_...` → `crt_...` prefix fix period
- **vantageaiops.com redirect** — live via Cloudflare rules → cohrint.com (no code action needed)
- **Stop hook API key** — fixed: `vnt_...` → `crt_...` prefix (PR #67)
- **Branch cleanup** — delete merged branches: `fix/dashboard-role-visibility-and-date-bugs`, `feat/semantic-cache-and-prompt-registry`, `feat/agent-trace-dag`
- **Next tasks**:
  - Chargeback report export (CSV/PDF per team, per billing period)
  - Model switch advisor (recommend cheaper model when quality delta < threshold)
  - Merge PR #70 after CI passes
