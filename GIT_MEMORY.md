# GIT_MEMORY — Cohrint / VantageAI

_Last updated: 2026-04-16_

## Current Branch
`feat/semantic-cache-and-prompt-registry` — PR #65 open, awaiting merge.

## Open PRs
| PR | Title | Branch |
|----|-------|--------|
| #65 | feat: semantic cache (Vectorize + Workers AI) + prompt registry MVP | feat/semantic-cache-and-prompt-registry |

## Latest 15 Commits
| SHA | Message |
|-----|---------|
| `9ead355` | Fix 3 code-review issues: bind order, route shadowing, COALESCE defaults |
| `b9fa9b0` | feat: semantic cache (Vectorize + Workers AI) + prompt registry MVP |
| `d04ab96` | Merge pull request #64 from VantageAIOps/fix/code-review-issues |
| `97d7229` | Fix 4 remaining code-review issues: N+1 budget queries, IP token bypass, cache suppression, MCP URIs |
| `9dcbd68` | Fix 6 code-review issues: key hint, privilege escalation, batch budget, seed event_id, cache prefix, calcCost |
| `52b1a0a` | Fix 5 code-review issues: Infinity validation, token double-count, cache suppression, empty_reason, QS.07 test |
| `06e7603` | Fix 15 hallucination detection and recommendation engine bugs |
| `0cdef5c` | Add Suite 46: quality scores + recommendation engine tests (47 checks) |
| `a1c73aa` | Rename vantage-track.js → cohrint-track.js across all installers |
| `547b564` | Fix setup_claude_hook to install cohrint-track.js consistently |
| `7213a81` | Add missing package.json for cohrint-cli (rebranded from vantageai-cli) |
| `bf1881c` | Merge PR #63 — Fix stale vantageaiops references |
| `160e6aa` | Fix test suite failures across suites 17, 33, 35, 40 |
| `cfc826b` | Fix code review issues: CORS wildcard, state migration, BU cost field, benchmark UX, seed CI header |
| `93cbbd8` | Add da45 seed script + fix test shape assertions |

## Recent Merged PRs
| PR | Title |
|----|-------|
| #64 | Fix 11 code-review issues: security, budget enforcement, cost accuracy, test correctness |
| #63 | Fix stale vantageaiops references (CORS, hook env vars, drop claude-code publish) |
| #62 | SEO verification + account hierarchy + cohrint rebrand |
| #61 | chore: rebrand VantageAI → Cohrint + security fixes |
| #60 | feat(enterprise): multi-team RBAC, CEO dashboard, budget policies, team attribution |

## Package Versions
| Package | Path | Version |
|---------|------|---------|
| cohrint-cli | cohrint-cli/package.json | 1.0.0 |
| cohrint-mcp | cohrint-mcp/package.json | (check file) |
| cohrint-js-sdk | cohrint-js-sdk/package.json | (check file) |

## Outstanding Items
- **PR #65 pending merge** — semantic cache + prompt registry MVP
- **Pre-deploy step for PR #65**: `wrangler vectorize create cohrint-semantic-cache --dimensions=384 --metric=cosine` + `wrangler d1 migrations apply vantage-events --remote`
- **GitHub Actions billing**: All CI jobs failing — resolve at GitHub Settings → Billing & plans
- **Branch cleanup**: Delete `fix/code-review-issues` (already merged)
- **P3 complete**: semantic cache ✅ + prompt registry ✅ (both in PR #65)
- **Next P3 tasks**: Design partner CTO outreach, n8n deploy on Railway, SOC2 prep
- **Next P4 tasks**: Agent trace DAG visualization, public benchmark dashboard
