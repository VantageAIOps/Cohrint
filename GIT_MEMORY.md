# GIT_MEMORY.md — VantageAI
_Last updated: 2026-04-09_

## Current Branch
`fix/webkit-session-ci-warn`

## Open PRs
| # | Title | Branch |
|---|-------|--------|
| #46 | fix: WebKit ITP warn + feature grid tabbed panels + PRODUCT_STRATEGY v4.0 | fix/webkit-session-ci-warn |

## Latest 15 Commits
```
80a2544 fix(agent): fix all 12 flaws in vantage-agent.md
451e099 feat(agent): add vantage-agent.md — expert agent for VantageAI codebase
e8ebab6 docs(strategy): rewrite PRODUCT_STRATEGY.md to enterprise v4.0
5744c8f feat(landing): replace static feature grid with tabbed panel system
8873cc8 fix(ci): downgrade WebKit session-reload check to warn until SameSite=None deploys
f1cba2c Merge pull request #44 from VantageAIOps/feat/semantic-cache-analytics
72e30e0 fix(auth): use SameSite=None for session cookie to fix Safari ITP
4e80bab fix(security): address 6 code review issues from PR #44
071b534 chore: update GIT_MEMORY.md — website overhaul PR #44 state
22de6c4 fix(tests): add missing pytest import to test_dashboard_real_data.py
500901c docs(security): internal security audit report 2026-04-09
03a344c feat(security): HSTS+COOP+CORP headers, brute-force on /session, prompt_hash validation
71407ce feat(app): add Docs nav link + XSS-safe demo banner for demo org session
9d85fba feat(website): Phase 2 enterprise redesign
a75c7e9 feat(website): Phase 1 content — remove fake reviews, fix pricing CTAs
```

## Recent Merged PRs
```
f1cba2c PR #44 — feat/semantic-cache-analytics (cache analytics + security hardening)
65d565e PR #43 — feat/semantic-cache-analytics
b7b98e6 PR #42 — feat/semantic-cache-analytics
a81313b PR #41 — feat/session-centric-integration
f0981a1 PR #40 — feat/cleanup-mobile-otel
```

## Package Versions
| Package | Version | Registry |
|---------|---------|----------|
| vantage-mcp | 1.1.1 | npm |
| vantage-js-sdk | 1.0.1 | npm |
| vantage-worker | 1.0.0 | internal |
| vantage-agent | 0.1.0 | PyPI |

## Outstanding Items

### Before/after merging PR #46
- [ ] Merge PR #46 → CI auto-deploys Worker + Pages
- [ ] After Worker deploys: restore CA.D3.4 `warn` → `chk` in `tests/suites/15_cross_browser/test_auth_cross_browser.py:121`
- [ ] Verify tabbed feature grid (`switchFeatPanel`) works on live site
- [ ] Demo seed: generate real SHA-256 for demo API key, replace placeholder in `scripts/demo-seed.sql`

### Tech debt
- [ ] DR.43 xfail marker — verify still needed (`pytest --runxfail`)
- [ ] Untracked: `scripts/pkg.sh` — commit or discard
- [ ] Untracked plan files in `docs/superpowers/plans/` — commit or discard

### Roadmap (not started)
- Sprint 1: L3 Billing API connectors (AWS Bedrock, Azure OpenAI, GCP Vertex)
- Sprint 2: Browser Extension MVP + SSO/SAML
- Sprint 3: Semantic cache fuzzy matching + sliding window rate limiter (Durable Objects)
- Sprint 4: Self-hosted / on-prem deployment

## Key Files
| File | Purpose |
|------|---------|
| `vantage-worker/src/routes/auth.ts` | SameSite=None cookie fix lives here |
| `vantage-final-v4/index.html` | Landing — tabbed feature grid (3×9 cards) |
| `vantage-final-v4/_headers` | CSP, HSTS, security headers |
| `tests/suites/15_cross_browser/` | CA.D3.4 downgraded to warn (WebKit ITP) |
| `tests/suites/38_security_hardening/` | New suite SH.1–SH.8 |
| `docs/agents/vantage-agent.md` | VantageAI expert agent skill |
| `PRODUCT_STRATEGY.md` | v4.0 enterprise rewrite (2026-04-09) |
| `scripts/demo-seed.sql` | Demo seed — placeholder key needs real SHA-256 |
| `ADMIN_GUIDE.md` | Internal dev guide — §19 runbook, §20 research |
