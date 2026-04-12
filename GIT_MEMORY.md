# GIT_MEMORY.md — VantageAI
_Last updated: 2026-04-12_

## Current Branch
`feat/vega-chatbot`

## Open PRs
| # | Title | Branch |
|---|-------|--------|
| #50 | feat(chatbot): Vega AI assistant for dashboard | feat/vega-chatbot |

## Latest 15 Commits
```
219166b fix(chatbot): resolve 4 code-review issues
1fbac63 feat(chatbot): deploy Vega to Cloudflare Workers
6bd0086 docs: add Vega chatbot implementation plan
5b5bc36 test(chatbot): 24 integration + unit tests for Vega
52a7c12 feat(chatbot): Vega frontend widget — safe DOM, textContent only
6dcdffa feat(chatbot): doc chunks builder from docs.html
befdd39 feat(chatbot): chat + ticket handlers wired to Hono routes
40cbe6c feat(chatbot): system prompt builder + KV rate limiter
117c647 feat(chatbot): knowledge lookup + output sanitizer
9acecd1 feat(chatbot): add 19-entry static knowledge base
9158198 feat(chatbot): scaffold Vega Worker with health endpoint
857a001 feat(dashboard): hold-to-reveal insight tooltips on all 31 cards
c0813c7 feat(frontend): hold-to-reveal card insight tooltip (4.5s hover)
bf16999 fix(tests): patch vantage_agent.cli.auto_detect_backend
dd8006e fix(cli): remove duplicate --version argument causing argparse conflict
```

## Recent Merged PRs
```
f1cba2c PR #44 — feat/semantic-cache-analytics (cache analytics + security)
65d565e PR #43 — feat/semantic-cache-analytics
b7b98e6 PR #42 — feat/semantic-cache-analytics
a81313b PR #41 — feat/session-centric-integration
f0981a1 PR #40 — feat/cleanup-mobile-otel
```

## Package Versions
| Package | Version | Registry |
|---------|---------|----------|
| vantage-chatbot | 1.0.0 | Cloudflare Workers |
| vantage-mcp | 1.1.1 | npm |
| vantage-js-sdk | 1.0.1 | npm |
| vantage-local-proxy | 1.0.2 | npm |
| vantage-worker | 1.0.0 | internal |
| vantageai-agent | 0.2.4 | PyPI |
| claude-intelligence | 0.1.0 | internal |

## Outstanding Items

### PR #50 — before merge
- [ ] **2026-04-13** Upload KV doc chunks (optimized to 1 write op, daily limit reset):
  ```bash
  cd vantage-chatbot && npx wrangler kv bulk put --namespace-id=3711f2ed67a04f7a981eb1ab33634313 knowledge/kv-upload.json
  ```
  Note: chunks.json already built — no need to re-run build-chunks.js
- [ ] Set `VANTAGE_API_URL` secret: `cd vantage-chatbot && npx wrangler secret put VANTAGE_API_URL`
- [ ] Merge PR #50 → CI auto-deploys Worker + Pages

### Vega deployment details
- Production URL: `https://vantage-chatbot.aman-lpucse.workers.dev`
- KV namespace: `id=3711f2ed67a04f7a981eb1ab33634313`, `preview_id=8ad5c76d2e4b469096e2800dfa071948`
- Secrets set: `RESEND_API_KEY` ✓ | `VANTAGE_API_URL` — still needed
- Wrangler: v3.114.17 (v4 available — `npm install --save-dev wrangler@4` in vantage-chatbot/)

### Tech debt (carried over)
- [ ] DR.43 xfail marker — verify still needed (`pytest --runxfail`)
- [ ] `scripts/pkg.sh` untracked — commit or discard
- [ ] CA.D3.4 WebKit test: restore `warn` → `chk` after SameSite=None deploys

### Roadmap (not started)
- Sprint 1: L3 Billing API connectors (AWS Bedrock, Azure OpenAI, GCP Vertex)
- Sprint 2: Browser Extension MVP + SSO/SAML
- Sprint 3: Semantic cache fuzzy matching + Durable Objects rate limiter
- Sprint 4: Self-hosted / on-prem deployment

## Key Files
| File | Purpose |
|------|---------|
| `vantage-chatbot/src/chat.ts` | Chat handler — resolves plan server-side via session API |
| `vantage-chatbot/src/ratelimit.ts` | Write-then-count KV rate limiter (20 msg/hr/org) |
| `vantage-chatbot/knowledge/static.json` | 19 Q&A entries with plan_gate fields |
| `vantage-final-v4/widget/chatbot.js` | Vega widget — inline DOM ticket form, no window.prompt |
| `vantage-final-v4/app.html` | Dashboard — Vega widget injected, 31 hold-to-reveal cards |
| `vantage-worker/src/routes/auth.ts` | SameSite=None cookie fix |
| `vantage-final-v4/index.html` | Landing — tabbed feature grid (3×9 cards) |
| `tests/suites/34_vega_chatbot/` | 24 chatbot tests (all passing) |
| `PRODUCT_STRATEGY.md` | v4.0 enterprise rewrite |
| `ADMIN_GUIDE.md` | Internal dev guide — §19 runbook, §20 research |
