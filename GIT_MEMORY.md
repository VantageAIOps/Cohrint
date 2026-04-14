# GIT_MEMORY.md — VantageAI
_Last updated: 2026-04-14_

## Current Branch
`feat/claude-intelligence-customer-integration`

## Open PRs
| # | Title | Branch |
|---|-------|--------|
| 57 | feat(claude-intelligence): customer integration — setup subcommand, dashboard connect flow, npm package | feat/claude-intelligence-customer-integration |

## Latest 15 Commits
```
bf893aa feat(claude-intelligence): full customer integration — track, setup, dashboard, npm package
3b2b249 docs: add GIT_HISTORY.md — complete 440-commit log with PR index and phase summary
dea95d0 docs: comprehensive update — PRODUCT_STRATEGY v7.0, ADMIN_GUIDE +503 lines, docs.html new endpoints
2587b40 fix(ui): stack install-box commands vertically on mobile to prevent line breaks
e975937 chore: update GIT_MEMORY.md — PR #56 state, branch fix/ui-finetune-dashboard
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
```

## Recent Merged PRs
| PR | Branch |
|----|--------|
| #55 | feat/free-tier-50k |
| #54 | feat/free-tier-50k |
| #53 | fix/ci-signup-rate-limit |
| #52 | fix/otel-developer-id-attribute |
| #51 | feat/vega-chatbot |

## Package Versions
| Package | npm name | Version |
|---------|----------|---------|
| vantage-mcp | vantageaiops-mcp | 1.1.1 |
| vantage-js-sdk | vantageaiops | 1.0.1 |
| claude-intelligence | @vantageaiops/claude-code | 1.0.0 (new, pending publish) |

## Outstanding Items
- **PR #57** — claude-intelligence customer integration awaiting review + merge
- Task #1 (Explore project context) and #2 (Build trust.vantageaiops.com security page) pending — unrelated to PR #57
- After PR #57 merges: bump `@vantageaiops/claude-code` version to trigger CI publish to npm
