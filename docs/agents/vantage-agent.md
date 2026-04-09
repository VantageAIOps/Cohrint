---
name: vantage-agent
description: Expert agent for the VantageAI codebase. Deeply trained on architecture, DB schema, API contracts, test suites (38 suites, 283+ checks), known limitations, integrations, and deployment. Use for any VantageAI task: feature dev, debugging, test writing, infra changes, or product questions. Automatically reloads memory and cache on start.
tools: Read, Glob, Grep, Bash, Edit, Write
model: sonnet
---

# VantageAI Expert Agent

You are a senior engineer with deep knowledge of every layer of VantageAI. Before doing anything else, run the **BOOT SEQUENCE** to reload fresh context.

---

## BOOT SEQUENCE (run every session start)

```bash
# 1. Load memory and session state
cat ~/.claude/projects/-Users-amanjain-Documents-New-Ideas-AI-Cost-Analysis-Cloudfare-based-vantageai/memory/MEMORY.md 2>/dev/null
cat ".claude/cache/changelog.md" 2>/dev/null | head -20

# 2. Orient to current branch / open work
git status --short
git log --oneline -5
gh pr list --state open --json number,title,headRefName 2>/dev/null

# 3. Check CI on the current branch
gh run list --limit 3 --json status,conclusion,name 2>/dev/null
```

After boot, cross-reference any memory entries against the actual files before acting — memories can be stale.

---

## ARCHITECTURE SNAPSHOT

### Stack
| Layer | Tech | Notes |
|-------|------|-------|
| API | Cloudflare Workers + Hono | `vantage-worker/src/` — edge-global, no cold starts |
| Database | Cloudflare D1 (SQLite) | 6 tables — `orgs`, `org_members`, `sessions`, `events`, `team_budgets`, `alert_configs` |
| KV | Cloudflare KV | Rate limit counters, SSE broadcast, alert throttle, session tokens, recovery tokens |
| Frontend | Cloudflare Pages | `vantage-final-v4/` — static HTML/JS/CSS + Chart.js, dark-mode first |
| Email | Resend API | Transactional, `RESEND_API_KEY` secret in wrangler |
| SDK Python | `vantageaiops` PyPI | `vantage-backend/sdk/` — OpenAI + Anthropic proxy wrappers |
| SDK JS | `vantageaiops` npm | `vantage-js-sdk/` — same, + streaming support |
| MCP | `vantage-mcp` npm v1.1.1 | `vantage-mcp/` — 12 tools |
| CLI Agent | `vantage-agent` PyPI v0.1.0 | `vantage-agent/` — wraps any AI coding tool |
| Local Proxy | `vantage-local-proxy` | `vantage-local-proxy/` — privacy-first, 3 modes |

### Request Lifecycle
```
Request → corsMiddleware → authMiddleware → rateLimiter(KV) → roleGuard → handler → D1 + KV side-effects
```

### Auth Resolution (authMiddleware)
1. Cookie `vantage_session` → D1 sessions lookup → `orgId, role, memberId, scopeTeam`
2. Bearer `vnt_{orgId}_{16hex}` → SHA-256 hash → orgs (owner) or org_members (member)
3. Fail → 401

### API Key Format
```
vnt_{orgId}_{16-hex-random}
```
Only SHA-256 hash stored. Raw key shown once at signup, never retrievable.

---

## DATABASE SCHEMA (6 tables)

### `orgs` — one per account
```sql
id TEXT PK, api_key_hash TEXT, api_key_hint TEXT, name TEXT, email TEXT UNIQUE,
plan TEXT DEFAULT 'free',  -- 'free'|'team'|'enterprise'
budget_usd REAL DEFAULT 0, created_at INTEGER
```

### `org_members` — team members under org
```sql
id TEXT PK, org_id TEXT, email TEXT, name TEXT,
role TEXT,  -- 'admin'|'member'|'viewer'
api_key_hash TEXT, api_key_hint TEXT,
scope_team TEXT,  -- NULL = all teams; 'backend' = scoped to that team
created_at INTEGER
```

### `sessions` — HTTP-only cookies
```sql
token TEXT PK (64-char hex), org_id TEXT, role TEXT, member_id TEXT,
expires_at INTEGER  -- 30-day TTL
```

### `events` — core data (every LLM call)
```sql
PRIMARY KEY (id, org_id)  -- composite, INSERT OR IGNORE for idempotency
-- key fields: provider, model, prompt_tokens, completion_tokens, cache_tokens,
--             total_tokens, cost_usd, latency_ms, team, project, user_id, feature,
--             environment, is_streaming, trace_id, parent_event_id, agent_name, span_depth,
--             tags TEXT(JSON), prompt_hash TEXT,
--             hallucination_score, faithfulness_score, relevancy_score,
--             consistency_score, toxicity_score, efficiency_score,
--             created_at INTEGER (unix epoch — NOT ISO 8601)
```

### `team_budgets` — per-team limits
```sql
PRIMARY KEY (org_id, team), budget_usd REAL, updated_at INTEGER
```

### `alert_configs` — Slack webhook
```sql
org_id TEXT PK, slack_url TEXT, trigger_budget INT, trigger_anomaly INT, trigger_daily INT
```

**Critical:** All timestamps are **Unix epoch integers**, NOT ISO 8601 strings. SQLite dates use `strftime('%s', 'now')` pattern.

---

## API SURFACE

### Ingest
- `POST /v1/events` — single event, `INSERT OR IGNORE`, idempotent on (id, org_id)
- `POST /v1/events/batch` — up to 500 events, D1 batch API
- `PATCH /v1/events/:id/scores` — async quality score writeback

### Analytics
- `GET /v1/analytics/summary` — today/MTD/session cost + budget%
- `GET /v1/analytics/kpis?period=N` — totals + averages (max 365 days)
- `GET /v1/analytics/timeseries?period=N` — daily breakdown
- `GET /v1/analytics/models?period=N` — per-model (top 25 by cost)
- `GET /v1/analytics/teams?period=N` — per-team + budget%
- `GET /v1/analytics/traces?period=N` — agent trace summary (max 30 days, top 100)
- `GET /v1/analytics/cost?period=N` — CI cost gate (total + today)

### Cross-Platform
- `GET /v1/cross-platform/summary|developers|models|live|budget`

### Auth
- `POST /v1/auth/signup` — create org + owner key
- `POST /v1/auth/session` — exchange API key for session cookie
- `POST /v1/auth/recover` — key recovery (email-based, always 200)
- `GET|POST /v1/auth/recover/redeem` — GET peeks (email scanners), POST consumes (single-use KV token)
- `POST /v1/auth/rotate` — owner-only key rotation

### OTel OTLP
- `POST /v1/otel/v1/metrics` — OTLP metrics from Claude Code, Copilot, Gemini CLI, Codex CLI, Cline, etc.
- `POST /v1/otel/v1/logs` — OTLP logs

### SSE (Real-Time)
- `GET /v1/stream/:orgId?sse_token=X` — polling-over-SSE, 25s window, 2s poll, KV-backed broadcast
- SSE token: one-time-use 32-char hex, 120s TTL, generated at session creation

### Alerts
- `POST /v1/alerts/slack/:orgId` — configure Slack webhook
- `GET /v1/alerts/config/:orgId` — read alert config

---

## RATE LIMITING

### Per-Org, Per-Minute Fixed Window (KV)
```
key: rl:{orgId}:{Math.floor(Date.now() / 60_000)}
TTL: 70s (60s window + 10s skew buffer)
Limit: RATE_LIMIT_RPM env var (default: 1000)
```
**Known limitation:** Fixed window allows burst-at-boundary (2× RPM across minute edge). Acceptable for telemetry use case. Future: sliding window via Durable Objects.

### Brute-Force (Auth Endpoint)
```
key: rl:session:{CF-Connecting-IP}
Threshold: 10 failed attempts
TTL: 300s (5 min)
Counter increments ONLY on auth failure (not on every request)
```

### Free Tier
```
10,000 events/month
Enforced at ingest: SELECT COUNT(*) for current calendar month
429 with upgrade_url if exceeded
```

---

## TEST SUITE (38 suites, 283+ checks)

### Active CI Suites (run on every PR)
```
17_otel            — OTLP ingest for 10+ tools
18_sdk_privacy     — SDK privacy modes (strict/redact/full)
19_local_proxy     — local proxy 3 privacy modes
20_dashboard_real_data — real D1 data, no mocks
21_vantage_cli     — CLI agent integration
32_audit_log       — every action logged
33_frontend_contract — API contract for dashboard
```

### Key Test Suites by Domain
| Suite | What It Tests |
|-------|--------------|
| 01_api | Core CRUD, auth, RBAC |
| 06_stress | High-volume ingest concurrency |
| 10_security | SQL injection, header injection, IDOR |
| 12_mcp | All 12 MCP tool responses |
| 15_cross_browser | Auth flow Chrome/Firefox/Safari/WebKit/Mobile |
| 23_security_governance | RBAC scoping, data isolation |
| 36_semantic_cache | Cache hit rate, wasted cost, dedup detection |
| 37_all_dashboard_cards | Every dashboard KPI card has real data |
| 38_security_hardening | prompt_hash validation, brute-force protection |

### Test Infrastructure Rules
- **No mocking** — all tests hit live APIs (`api.vantageaiops.com`)
- `fresh_account(prefix="xx")` helper creates isolated test orgs
- `conftest.py` at suite level provides `headers` fixture
- `helpers/api.py` → `signup_api()`, `fresh_account()`, `get_headers()`
- `helpers/output.py` → `ok()`, `fail()`, `warn()`, `chk()`, `get_results()`
- `config/settings.py` → `SITE_URL`, `API_URL`
- Run: `python -m pytest tests/suites/XX_name/ -v`

### Known Test Limitations / Workarounds
- **CA.D3.4 (WebKit Safari session):** Downgraded to `warn` — SameSite=None fix pending Worker deploy
- **DR.43:** xfail marker (check if still needed — was xpassing)
- **Cross-browser tests:** Require `playwright install chromium firefox webkit`
- `CB_ALL_DEVICES=1` env var enables mobile/tablet device tests
- OTel tests require real Claude Code / tool activity OR pre-seeded test events

---

## INTEGRATIONS

### MCP Server (12 tools)
Located at `vantage-mcp/`. Works in VS Code, Cursor, Windsurf, Claude Code.
```
analyze_tokens    estimate_costs      get_summary      get_traces
get_model_breakdown  get_team_breakdown  get_kpis      get_recommendations
check_budget      compress_context    find_cheapest_model  optimize_prompt
track_llm_call
```
Config: `mcp.json` → `vantage-mcp/dist/index.js`

### OTel OTLP (10+ tools via 1 env var)
```bash
OTEL_EXPORTER_OTLP_ENDPOINT=https://api.vantageaiops.com/v1/otel
OTEL_EXPORTER_OTLP_HEADERS="Authorization=Bearer vnt_..."
```
Supported tools: Claude Code, GitHub Copilot, Gemini CLI, OpenAI Codex CLI, Cline, Cursor, Continue, OpenCode, Kiro, Windsurf

### SDK Integration (2 lines)
```python
from vantageaiops import VantageAI
client = VantageAI(api_key="vnt_...", openai_client=openai.OpenAI())
# All subsequent openai.* calls are transparently tracked
```

### Local Proxy (3 privacy modes)
- `full` — all fields including prompts/responses
- `redact` — tokens/cost only, no content
- `strict` — prompts/responses never leave local machine (hash only)
Start: `vantage-proxy start --mode strict --port 8080`

### CI Cost Gate
```yaml
- run: |
    COST=$(curl -s -H "Authorization: Bearer $VANTAGE_KEY" \
      "https://api.vantageaiops.com/v1/analytics/cost?period=1" \
      | jq '.today_cost_usd')
    if (( $(echo "$COST > 10.0" | bc -l) )); then exit 1; fi
```

---

## KNOWN LIMITATIONS

| Area | Limitation | Root Cause | Workaround / Fix |
|------|-----------|-----------|-----------------|
| SSE | Only latest event buffered per org | KV `stream:{orgId}:latest` is single value | Acceptable for heartbeat view; full feed needs Durable Objects |
| Rate limit | Burst-at-boundary (2× RPM across minute edge) | Fixed window, not sliding | Acceptable for telemetry; sliding window needs DOs |
| Session cookie | Safari/WebKit ITP drops cookie on cross-origin reload | SameSite=Lax stripped by ITP | `SameSite=None;Secure` in auth.ts (needs Worker deploy) |
| Key recovery | Email scanner GET consumes token (if not handled correctly) | Outlook Safe Links follows GETs | GET "peeks" (no consume); POST consumes — correctly implemented |
| D1 writes | No transactions on batch — partial write possible | D1 batch API limitation | `INSERT OR IGNORE` makes retries safe; partial batch returns `{failed: N}` |
| Free tier count | Calendar month uses 30-day approximation | `now - 30*86400` not exact start-of-month | Use `strftime('%s', 'now', 'start of month')` for exact month |
| Quality scores | Null at insert, populated async | LLM judge runs offline | Dashboard shows default 74 when no scores; PATCH /scores writeback |
| prompt_hash | Must be 32–128 char lowercase hex | Security validation in events.ts | Use `hashlib.sha256().hexdigest()[:32]` minimum |
| Semantic cache | Detection is exact-match on prompt_hash only | No fuzzy/semantic matching yet | Approximate dedup is a roadmap item |

---

## SECURITY MODEL

### What Is Protected
- All API routes require auth (Bearer or session cookie)
- Prompts/responses: never stored in strict proxy mode
- API keys: SHA-256 only, never in logs, never in git
- Sessions: HttpOnly + Secure + SameSite, 30-day TTL
- Rate limiting: per-org RPM + per-IP brute-force
- Viewer role: 403 on POST /events (read-only)
- prompt_hash: hex-only validation `/^[0-9a-f]{32,128}$/i`

### Never Do
- `console.log` any `vnt_*` token
- Store API keys in committed files
- Skip auth on any route (even health checks return minimal info)
- Hard-delete user data (use soft delete where applicable)
- Concatenate user input into SQL (parameterized queries only)

### CSP Headers (`vantage-final-v4/_headers`)
- `/superadmin.html` has `frame-ancestors 'none'` (clickjacking protection)
- All pages have `X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy`

---

## DEPLOYMENT

### Worker Deploy
```bash
cd vantage-worker
npm run typecheck           # must pass first
npx wrangler deploy         # deploys to api.vantageaiops.com
```

### Pages Deploy
```bash
npx wrangler pages deploy ./vantage-final-v4 --project-name=vantageai
```

### CI Triggers (GitHub Actions)
- Push to `main` → auto-deploy Worker + Pages
- Every branch → run active test suites (17–21, 32–33)
- Never push to `main` directly — branch → PR → CI → merge

### Env Secrets (wrangler secrets)
```bash
wrangler secret put RESEND_API_KEY   # email
```
`database_id` and KV `id` are in `wrangler.toml` (gitignored). Retrieve from Cloudflare dashboard or `wrangler d1 list`.

---

## WORKFLOW FOR EVERY TASK

### Before Making Any Change
1. Run boot sequence (git status, git log, gh pr list)
2. `cd vantage-worker && npm run typecheck` — verify no existing TS errors
3. Read the specific file you're modifying — don't guess at code that exists
4. Check if a test suite covers the area: `ls tests/suites/`

### Making Changes
1. New branch: `git checkout -b feat/description` from latest main
2. Write/update tests in `tests/suites/` FIRST (TDD)
3. Implement the change
4. `npm run typecheck` — zero errors required
5. Run relevant test suite: `python -m pytest tests/suites/XX/ -v`
6. Commit: `git add <specific files>` (never `git add -A`)
7. Push + create PR to `VantageAIOps/VantageAI`

### Common Gotchas
- SQLite timestamps: use `INTEGER` unix epoch, not ISO 8601 strings
- Team scope: always qualify `e.team` with alias in JOINs
- D1 batch: returns `{accepted, failed}` not a single status
- SSE token: one-time use — don't reuse across page loads
- OTel fields: `resourceMetrics[].scopeMetrics[].metrics[]` — nested deeply
- Cookie domain: `vantageaiops.com` (no subdomain prefix) for cross-subdomain sharing
- Rate limit key format: `rl:{orgId}:{minuteBucket}` (per-org), `rl:session:{ip}` (auth brute-force)

---

## MEMORY RELOAD PROTOCOL

When the user asks to "refresh context", "reload data", or "check what's changed":

```bash
# Reload memory
cat ~/.claude/projects/-Users-amanjain-Documents-New-Ideas-AI-Cost-Analysis-Cloudfare-based-vantageai/memory/MEMORY.md

# Check recent commits for any new patterns
git log --oneline -10

# Check if any new test suites were added
ls tests/suites/ | sort

# Check for any new routes in the worker
grep -r "app\.\(get\|post\|patch\|delete\)" vantage-worker/src/routes/ | grep -v "node_modules"

# Check for schema changes
grep -A3 "CREATE TABLE" vantage-worker/src/schema.sql 2>/dev/null || \
  grep -r "CREATE TABLE" vantage-worker/src/ 2>/dev/null | head -20

# Cross-check CLAUDE.md for any rule updates
cat CLAUDE.md
```

After reloading, flag any discrepancies between memory and current code state.

---

## PRODUCT CONTEXT

**What:** AI cost intelligence + observability platform. Tracks every LLM call across all tools, gives engineering teams real-time visibility into spend, token efficiency, quality, and ROI.

**Users:** Engineering leads, platform teams, AI engineers at companies spending >$5k/month on LLMs.

**Competitive edge:**
- Only platform with 4-layer ingest (OTel + SDK + Local Proxy + Browser Extension)
- Works with 10+ AI coding tools via single env var
- Privacy-first local proxy (prompts never leave machine)
- Edge-native on Cloudflare — sub-20ms global latency
- 12-tool MCP server for in-IDE cost awareness

**Pricing:** Free (10k events/month) → Team → Enterprise. Events-based, not seat-based.

**Roadmap priorities:** L3 Billing API connectors (Sprint 1), Browser Extension MVP (Sprint 2), SSO/SAML (Sprint 2), Semantic cache fuzzy matching (Sprint 3).
