# GIT_MEMORY.md — VantageAI
_Last updated: 2026-04-15_

## Current Branch
`fix/landing-page-positioning`

## Open PRs
| # | Title | Branch |
|---|-------|--------|
| 58 | fix(landing): remove algorithm exposure + reframe hero for enterprise buyers | fix/landing-page-positioning |

## Latest 15 Commits
```
4dd249f fix(landing): remove algo exposure, reframe hero for enterprise buyers
e0f7165 Merge pull request #57 from VantageAIOps/feat/claude-intelligence-customer-integration
34790d8 feat(trust): update security page with Claude Code hook architecture
077038a docs: update ADMIN_GUIDE + PRODUCT_STRATEGY with claude-intelligence architecture
a61a684 fix(claude-intelligence): address code review issues from PR #57
5a3a553 chore: update GIT_MEMORY.md for PR #57 state
bf893aa feat(claude-intelligence): full customer integration — track, setup, dashboard, npm package
3b2b249 docs: add GIT_HISTORY.md — complete 440-commit log with PR index and phase summary
99f4db4 Merge pull request #56 from VantageAIOps/fix/ui-finetune-dashboard
dea95d0 docs: comprehensive update — PRODUCT_STRATEGY v7.0, ADMIN_GUIDE +503 lines, docs.html new endpoints
2587b40 fix(ui): stack install-box commands vertically on mobile to prevent line breaks
e975937 chore: update GIT_MEMORY.md — PR #56 state, branch fix/ui-finetune-dashboard
b681a78 fix(ui): close modal via closeModal() on Escape/overlay to reset form fields
999fec8 fix(ui): dashboard polish — layout, UX, accessibility, mobile fixes
73c089f Merge pull request #55 from VantageAIOps/feat/free-tier-50k
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
- **PR #58** — landing page positioning fix + competitive analysis docs; awaiting review + merge
- After PR #58 merges: deploy frontend via `npx wrangler pages deploy ./vantage-final-v4 --project-name=vantageai`
- **PRODUCT_STRATEGY.md § 15** added: full palma.ai competitive teardown — read before any enterprise sales call
- **60-day roadmap items** tracked in TODO.md (competitive intelligence section, 2026-04-15): cost forecasting widget, chargeback reports, model switch advisor, GitHub Actions landing page, app-layer attribution, quality/cost tradeoff tooling
