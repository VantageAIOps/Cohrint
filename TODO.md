# Cohrint — TODO

Last updated: 2026-04-17

---

## 🔴 P0 — SEO & Migration (do before next deploy)

- [x] **Deploy vantageaiops.com redirect** — done via Cloudflare Single Redirect Rules (not Pages). Three rules created: apex, `/*` wildcard, and `www.vantageaiops.com/*`. All verified with curl — 301 → cohrint.com with path preserved. DNS: A record `192.0.2.1` (proxied) + CNAME `www` added.

- [ ] **Deploy cohrint Pages with new SEO changes**
  ```bash
  npx wrangler pages deploy vantage-final-v4 --project-name=cohrint
  ```

- [ ] **Search engine verification — Google Search Console**
  1. Go to search.google.com/search-console → Add Property → `https://cohrint.com`
  2. Download HTML verification file → replace `vantage-final-v4/google-site-verification.html`
  3. Update `<meta name="google-site-verification">` in `index.html` with real code
  4. Deploy → Verify → Submit `https://cohrint.com/sitemap.xml`

- [ ] **Search engine verification — Bing Webmaster Tools** (covers DuckDuckGo, Yahoo, Safari Spotlight)
  1. Go to bing.com/webmasters → Add Site → `https://cohrint.com`
  2. Download BingSiteAuth.xml → replace `vantage-final-v4/BingSiteAuth.xml`
  3. Update `<meta name="msvalidate.01">` in `index.html`
  4. Deploy → Verify → Submit sitemap

- [ ] **Search engine verification — Yandex Webmaster**
  1. Go to webmaster.yandex.com → Add site → `https://cohrint.com`
  2. Replace `vantage-final-v4/yandex-verification.html` with Yandex's file
  3. Update `<meta name="yandex-verification">` in `index.html`
  4. Deploy → Verify → Submit sitemap

- [ ] **Ping IndexNow after deploy** (notifies Bing + Yandex instantly)
  ```bash
  curl -X POST "https://api.indexnow.org/indexnow" \
    -H "Content-Type: application/json" \
    -d '{
      "host": "cohrint.com",
      "key": "70af20b77cca5851f1d94b24e39f4ce400a1966b08b8d0f08abc14e169ae120f",
      "keyLocation": "https://cohrint.com/70af20b77cca5851f1d94b24e39f4ce400a1966b08b8d0f08abc14e169ae120f.txt",
      "urlList": ["https://cohrint.com/","https://cohrint.com/docs","https://cohrint.com/calculator","https://cohrint.com/blog","https://cohrint.com/claude-code-cost","https://cohrint.com/gemini-cli-cost","https://cohrint.com/copilot-cost","https://cohrint.com/ai-coding-cost"]
    }'
  ```

- [ ] **Rename working directory: `vantageai/` → `cohrint/`**
  ```bash
  cd "/Users/amanjain/Documents/New Ideas/AI Cost Analysis/Cloudfare based"
  mv vantageai cohrint
  # Update any IDE workspace files, shell aliases, or scripts that reference the old path
  ```

- [x] **Fix Stop hook API key** — hook was using dead `vnt_...` key. Updated `~/.claude/settings.json` to `crt_...` key. Claude Code card will show Active after next session. ⚠️ Rotate the key that was shared in chat.
- [x] **Update all GitHub Actions workflows to cohrint naming** (done 2026-04-15, commit 5cca3f3)
  - Updated: `ci-test.yml`, `deploy.yml`, `deploy-worker.yml`, `cost-check.yml`, `ci-cross-browser.yml`
  - All URLs updated: `vantageaiops.com` → `cohrint.com`, `api.vantageaiops.com` → `api.cohrint.com`

- [ ] **Rename published npm/pypi packages to cohrint branding** ⚠️ breaking change — coordinate with users
  - `vantageaiops-mcp` → `cohrint-mcp`
  - `vantageaiops` (JS SDK) → `cohrint` or `@cohrint/sdk`
  - `vantageai-local-proxy` → `cohrint-local-proxy`
  - `@vantageaiops/claude-code` → `@cohrint/claude-code`
  - `vantageai-agent` (PyPI) → `cohrint-agent`
  - Steps:
    1. Publish new packages under cohrint names (bump minor version)
    2. `npm deprecate` old package names pointing users to new names
    3. Update `publish-packages.yml` package name references
    4. Update `repo-backup.yml` archive filename (`vantageai-backup` → `cohrint-backup`)
    5. Update `ci-pr-gate.yml`: `vantageai-agent` CLI install + help command
    6. Update any README / docs referencing old package names

- [ ] **Run full test suite — verify migration from vantageaiops.com → cohrint**
  ```bash
  # From the project root (after rename):
  python -m pytest tests/suites/17_otel/ tests/suites/18_sdk_privacy/ tests/suites/19_local_proxy/ tests/suites/20_dashboard_real_data/ tests/suites/21_vantage_cli/ tests/suites/32_audit_log/ tests/suites/33_frontend_contract/ -v
  ```
  Check for:
  - Any test fixtures or configs hardcoded to `vantageaiops.com` → update to `cohrint.com`
  - API base URL references in test configs → should point to `https://api.cohrint.com`
  - Any `vantageaiops` string in test files → grep and replace

---

## 📅 Scheduled — 2026-04-13 (run after midnight UTC)

> Vega chatbot PR #50 — final steps before merge. KV daily write limit resets at midnight UTC.

- [x] **Upload doc chunks to KV** (1 write op — optimized from 117):
  ```bash
  cd /path/to/vantageai/vantage-chatbot
  npx wrangler kv bulk put --namespace-id=3711f2ed67a04f7a981eb1ab33634313 knowledge/kv-upload.json
  ```

- [x] **Set VANTAGE_API_URL secret** (needed for server-side plan resolution):
  ```bash
  cd /path/to/vantageai/vantage-chatbot
  npx wrangler secret put VANTAGE_API_URL
  # Enter: https://api.cohrint.com
  ```

- [x] **Merge PR #50** once above two steps are done:
  ```bash
  gh pr merge 50 --repo CohrintOps/Cohrint --squash
  ```

---

## PR #55 — Post-merge follow-ups

- [ ] **Run migrations after PR #55 merges**
  ```bash
  cd vantage-worker && npx wrangler d1 migrations apply vantage-events --remote
  npx wrangler deploy
  npx wrangler pages deploy ../vantage-final-v4 --project-name=vantageai
  ```

- [ ] **Datadog connect UI in app.html** — backend fully implemented (`POST/DELETE /v1/datadog/connect`, `GET /v1/datadog/status`) but no frontend card exists in the Settings tab. Build a settings card matching the GitHub Copilot card: API key input, site dropdown (5 allowed sites), connect/disconnect, status badge, last_synced_at display. See `vantage-worker/src/routes/datadog.ts` for full contract.

- [ ] **Remove dead `kv_key` column from `copilot_connections`** — the cron always reconstructs the KV key via `kvTokenKey(orgId, githubOrg)` and never reads `copilot_connections.kv_key` from D1. The stored column is misleading — if the key derivation logic ever changes, the column silently diverges. Options: (a) drop the column in a new migration and remove the `kv_key` INSERT in `copilot.ts:464`, or (b) make the cron read `conn.kv_key` from D1 instead of recomputing it. Option (a) is simpler.
  ```sql
  -- migration 0014_drop_copilot_kv_key.sql
  ALTER TABLE copilot_connections DROP COLUMN kv_key;
  ```

- [ ] **Copilot connection: show sync status in dashboard cross-platform view** — once a Copilot integration is connected and syncing, users should see GitHub Copilot costs appear in the cross-platform cost breakdown. Verify `cross_platform_usage` rows with `provider='github-copilot'` surface in `GET /v1/cross-platform/summary` and the AI Spend Console tab. No code change likely needed — just a post-merge verification step.

---

## Engineering

- [ ] **Website docs page** — needs update + currently failing (broken content/links)
- [x] **CLI implementation** — completed (vantage-agent Python, session layer, rate limiting, OTel exporter)
- [x] **Website mobile** — responsive layout fixes applied (commit 8474462)
- [ ] **GitHub test workflow** — fix failing CI workflow
- [ ] **Backend-architecture review** — audit all integrations against the new session-centric design:
  - [ ] MCP (`vantage-mcp`)
  - [ ] Local proxy (`vantage-local-proxy`)
  - [ ] OTel integration
- [x] **Dead code cleanup** — vantage-cli TS remnant removed (PR #37, commit chore/cli-dead-code-cleanup)
- [x] **Folder consolidation** — vantage-cli dir removed, TS-dependent test suites rewritten

---

## Claude Intelligence Package

> **PARKED** — revisit once specialist agents and core product are stable.

- [x] **Build `claude-intelligence` plug-and-play package** — initial scaffold done (commit c3b3896)
  - [ ] Inventory all current assets: `.claude/` settings, plugins, hooks, skills, agents, MCP config
  - [ ] Bundle skills (`/clean`, `/deploy`, `/fix-issue`, `/pr-review`, agents, rules)
  - [ ] Extend install.sh to handle skills, rules, MCP config
  - [ ] Document what gets installed and how to configure per-project
  - [ ] Decide: personal use only vs. publishable for other devs

---

## Vantage-Trained Specialist Agents

- [ ] **Build 5 specialist agents trained on Vantage platform context:**
  - [ ] **Product Manager agent** — knows product strategy, roadmap, user personas, pricing, competitive landscape. Handles feature scoping, PRD writing, prioritization.
  - [ ] **Team Lead agent** — knows codebase architecture, PR workflow, branch strategy, coding standards. Reviews plans, assigns work, enforces quality gates.
  - [ ] **Developer agent** — knows full stack (Cloudflare Workers, Python vantage-agent, frontend, SDK). Implements features end-to-end following CLAUDE.md conventions.
  - [ ] **CI/CD Expert agent** — knows GitHub Actions workflows, Wrangler deploy, test suites, npm/pypi publish pipeline. Owns deploy safety, rollback, and workflow fixes.
  - [ ] **Testing Infra Owner agent** — knows pytest suites, test patterns, live API gating, coverage requirements. Writes and maintains all tests in `tests/suites/`.
- [ ] **Feed each agent:** CLAUDE.md, PRODUCT_STRATEGY.md, ADMIN_GUIDE.md, design specs, GIT_MEMORY.md, skills, hooks
- [ ] **Package as reusable agent definitions** (compatible with claude-intelligence package above)

---

## Access & People

- [ ] **GitHub access** — grant repo access to Akshay Thite

---

## Business

- [ ] **Market comparison** — research and document competitive landscape
- [ ] **Sales channel integration** — identify and set up sales channels
- [ ] **Company registration** — pending legal/admin setup

---

## Competitive Moat — Website & Marketing

- [ ] **Audit public website for over-exposed features** — review cohrint.com and docs.html for any
  proprietary capabilities that competitors (Helicone, LangSmith, Datadog) could directly copy from reading
  the public page alone. Flag everything that should be gated.

- [ ] **Hide or gate specialised edge features from public pages:**
  - Semantic cache similarity threshold mechanics (implementation detail — show savings, not how)
  - OTel field path ingestion schema (exact attribute names, batch format internals)
  - Benchmark cohort bucketing logic (company size + industry grouping methodology)
  - Vendor negotiation data model (what signals we track for renewal intelligence)
  - Quality scoring dimensions (6-dimension scoring weights and LLM-judge prompts)
  - Agent trace DAG reconstruction algorithm (span_depth + parent_event_id traversal)
  - Privacy mode exact data stripping rules (what fields are zeroed in strict vs redact)

- [ ] **Define two-tier messaging strategy:**
  - **Public page** — outcome-first messaging only ("save 40% on AI spend", "per-developer ROI in one view").
    No implementation details. No architecture diagrams showing internal pipeline stages.
  - **Post-signup / customer dashboard** — full feature documentation, integration guides, API reference.
    Gated behind auth. This is where the deep technical detail lives.

- [ ] **Move technical docs behind auth wall** — docs.html currently public. Move advanced integration
  docs (OTel schema, SDK internals, MCP tool list, local proxy modes) to `/app/docs` (authenticated).
  Keep only getting-started + high-level overview public.

- [ ] **Remove or obscure from public comparison table** — any row that reveals a specific internal
  capability not yet shipped by competitors. Showing "Semantic Cache ✅" is fine; showing the cosine
  similarity threshold and embedding model is not.

- [ ] **Watermark / track design partner docs** — any detailed architecture docs or roadmap slides
  shared with design partner CTOs should have org-specific watermarks so leaks are traceable.

---

## Competitive Intelligence — palma.ai vs Cohrint (2026-04-15)

> Full analysis: see PRODUCT_STRATEGY.md § 15 — Competitive Analysis & Future Scope

### Immediate (≤ 2 weeks)
- [x] **Reframe hero copy** — changed from "Real-time cost visibility..." to "Know what your AI bill will be before it arrives — and cut it." (done 2026-04-15)
- [x] **ADMIN_GUIDE v2.0** — full rewrite with 14 ASCII UML diagrams, new sections for semantic cache, prompt registry, benchmark dashboard, RBAC guards (2026-04-17)
- [x] **PRODUCT_STRATEGY v8.0** — Section 15 restructured as Competitive Strategy, Section 5 updated with P3 features, task plan updated (2026-04-17)
- [ ] **DPA / SOC 2 roadmap visible on Enterprise tier** — move "SOC 2 in progress — DPA available now" from pricing footnotes to Enterprise hero. Procurement won't move without compliance docs.
- [ ] **Remove engineering keywords from landing page** — ongoing; review quarterly. No algorithm names, no internal field names, no exact thresholds.

### 30-day scope
- [x] **Cost forecasting widget** — `projected_month_end_usd`, `daily_avg_cost_usd`, `days_until_budget_exhausted` added to `/v1/analytics/summary`. Two new KPI cards on dashboard (color-coded runway). 11 tests in suite 52. PR #70.
- [ ] **Chargeback report export** — Monthly PDF/CSV per team: cost center, total spend, event count, model breakdown. Opens VP Finance as a deal champion. First mover in this category.
- [ ] **Model switch advisor** — Use existing 24-LLM price table + per-team usage data to surface: "Switching X% of Team B's requests to a cheaper model saves $Y/month." Requires quality-score correlation. palma cannot offer this (model-agnostic by design).
- [ ] **GitHub Actions cost gate — dedicated landing page** — `/integrations/github-actions` with concrete example and copy-pasteable config. Unique feature, no competitor has documented it. Organic distribution opportunity.

### 60-day scope
- [ ] **Application-layer cost attribution** — per-endpoint, per-customer cost tracking (e.g., "/summarize costs $0.08/call, customer ABC costs $0.43/month"). Neither palma nor Helicone/Langfuse reach the application layer.
- [ ] **Quality vs. cost tradeoff tooling** — connect existing quality scores (hallucination, faithfulness) to model pricing. Show cost-per-quality-unit. Unique positioning: not just "cheapest model" but "best model for the price at this quality threshold."
- [ ] **Vendor negotiation intelligence** — "At your growth rate you qualify for Anthropic volume discounts in 6 weeks." Zero competitors touch this. Requires usage trend extrapolation + published volume tier data.
- [ ] **Audit log → compliance report generator** — formatted audit reports for SOC 2 / DORA evidence packages. Enterprise compliance teams need formatted output, not raw CSV exports.
