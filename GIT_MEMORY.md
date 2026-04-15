# GIT_MEMORY.md — VantageAI
_Last updated: 2026-04-15_

## Current Branch
`fix/landing-page-positioning`

## Open PRs
| # | Title | Branch |
|---|-------|--------|
| 59 | fix(ui): landing page polish + dashboard chart/layout fixes | fix/landing-page-positioning |

## Latest 15 Commits
```
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
0b3cb76 chore: update GIT_MEMORY.md — PR #58 state, branch fix/landing-page-positioning
4dd249f fix(landing): remove algo exposure, reframe hero for enterprise buyers
e0f7165 Merge pull request #57 from VantageAIOps/feat/claude-intelligence-customer-integration
34790d8 feat(trust): update security page with Claude Code hook architecture
077038a docs: update ADMIN_GUIDE + PRODUCT_STRATEGY with claude-intelligence architecture
```

## Recent Merged PRs
| PR | Title | Branch |
|----|-------|--------|
| #57 | feat(claude-intelligence): customer integration — setup subcommand, dashboard connect flow, npm package | feat/claude-intelligence-customer-integration |
| #56 | fix(ui): dashboard polish — layout, UX, accessibility, mobile | fix/ui-finetune-dashboard |
| #55 | feat: P1+P2 sprint — trust page, Copilot adapter, enterprise pricing, report | feat/free-tier-50k |
| #54 | feat(pricing): raise free tier from 10K to 50K events/month | feat/free-tier-50k |
| #53 | fix(auth): remove duplicate rate-limit block that bypassed CI bypass | fix/ci-signup-rate-limit |

## Package Versions
| Package | npm name | Version |
|---------|----------|---------|
| vantage-mcp | vantageaiops-mcp | 1.1.1 |
| vantage-js-sdk | vantageaiops | 1.0.1 |
| claude-intelligence | @vantageaiops/claude-code | 1.0.0 |

## Outstanding Items
- **PR #59** open — all CI checks passing (API Tests still running); ready to merge
- After PR #59 merges: deploy frontend `npx wrangler pages deploy ./vantage-final-v4 --project-name=vantageai` + backend `npx wrangler deploy`
- Set up Cloudflare Email Routing: `sales@vantageaiops.com` → real inbox
- **60-day roadmap** (TODO.md): cost forecasting widget, chargeback report export, model switch advisor, GitHub Actions cost gate landing page, app-layer attribution, quality/cost tradeoff tooling
- **PRODUCT_STRATEGY.md §15**: full palma.ai competitive teardown — read before enterprise sales calls
