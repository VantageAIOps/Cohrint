# Cohrint — Complete Git History
_Last updated: 2026-04-14 · 440 commits on main · 56 merged PRs_

---

## Summary by Phase

| Phase | Dates | PRs | What Was Built |
|-------|-------|-----|---------------|
| **Foundation** | Mar 18–19 | — | Cloudflare Worker, D1, SDK, session auth, SSE |
| **v2 Platform** | Mar 20–24 | #1–#12 | CI/CD, test infra, local proxy, OTel v1, CLI, token optimizer |
| **Hardening** | Mar 25–31 | #13–#21 | Bug sweeps, security fixes, recommendation engine |
| **v2 Features** | Apr 5–9 | #22–#45 | Audit log, agent wrapper, semantic cache, website overhaul, chatbot |
| **P2 Milestone** | Apr 10–14 | #46–#56 | Copilot adapter, Datadog exporter, Benchmark system, Cross-Platform console, free tier 50K, docs rewrite |

---

## PR Index (56 Merged)

| PR | Merged | Title |
|----|--------|-------|
| #56 | 2026-04-14 | fix(ui): dashboard polish — layout, UX, accessibility, mobile |
| #55 | 2026-04-14 | feat: free tier 50K + P2 security fixes |
| #54 | 2026-04-14 | feat/free-tier-50k (Amanjain98) |
| #53 | 2026-04-14 | fix/ci-signup-rate-limit |
| #52 | 2026-04-14 | fix/otel-developer-id-attribute |
| #51 | 2026-04-12 | feat/vega-chatbot — AI Spend Console cross-platform |
| #50 | 2026-04-12 | feat/vega-chatbot — Vega chatbot deploy |
| #49 | 2026-04-12 | fix/webkit-session-ci-warn |
| #48 | 2026-04-12 | fix/webkit-session-ci-warn (round 2) |
| #47 | 2026-04-10 | fix/webkit-session-ci-warn |
| #46 | 2026-04-10 | fix/webkit-session-ci-warn |
| #45 | 2026-04-09 | fix/webkit-session-ci-warn |
| #44 | 2026-04-09 | feat/semantic-cache-analytics |
| #43 | 2026-04-09 | feat/semantic-cache-analytics (Amanjain98) |
| #42 | 2026-04-09 | feat/semantic-cache-analytics (Amanjain98) |
| #41 | 2026-04-08 | feat/session-centric-integration |
| #40 | 2026-04-08 | feat/cleanup-mobile-otel |
| #39 | 2026-04-08 | fix/audit-log-event-names |
| #38 | 2026-04-08 | feat/vantage-agent-python |
| #37 | 2026-04-08 | chore/cli-dead-code-cleanup |
| #36 | 2026-04-08 | feat/vantage-agent-python (Amanjain98) |
| #35 | 2026-04-07 | fix/session-mode-tty-passthrough |
| #34 | 2026-04-07 | fix/audit-log-improvements |
| #33 | 2026-04-07 | fix/chart-date-accuracy |
| #32 | 2026-04-07 | chore/post-deploy-verify-workflow |
| #31 | 2026-04-07 | fix/dashboard-chart-timezone-cache |
| #30 | 2026-04-07 | fix/cli-ux-rendering-cache-tests |
| #29 | 2026-04-06 | fix/cli-ux-and-dynamic-versioning |
| #28 | 2026-04-06 | fix/zero-bugs-sweep |
| #27 | 2026-04-06 | fix/dashboard-token-usage-cache-savings |
| #26 | 2026-04-06 | feat/update-notifier-and-deprecation |
| #25 | 2026-04-06 | feat/claude-code-auto-tracking |
| #24 | 2026-04-06 | feat/enterprise-soc2-audit-log |
| #23 | 2026-04-05 | fix/connected-tools-widget |
| #22 | 2026-04-05 | fix/otel-live-feed-broadcast |
| #21 | 2026-03-31 | fix/ci-free-tier-limits |
| #20 | 2026-03-31 | fix/ci-rate-limit-bypass |
| #19 | 2026-03-28 | fix/ci-rate-limit-bypass (round 2) |
| #18 | 2026-03-28 | v2.9/recommendations-and-review-fixes |
| #17 | 2026-03-25 | fix/cli-critical-bugs |
| #16 | 2026-03-24 | fix/repo-backup-auth |
| #15 | 2026-03-24 | v2.8/auto-publish-ci |
| #14 | 2026-03-24 | v2.7/smart-session-optimization |
| #13 | 2026-03-24 | v2.6/docs-overhaul-collapsible-sidebar |
| #12 | 2026-03-24 | v2.5/security-governance-real-data |
| #11 | 2026-03-24 | v2.4/landing-page-v2-features |
| #10 | 2026-03-24 | v2.3/vantage-cli-stable |
| #9 | 2026-03-24 | v2.2/vantage-cli-agent-wrapper |
| #8 | 2026-03-24 | v2.1/dashboard-real-data-cleanup |
| #7 | 2026-03-24 | v2.1/privacy-mode-pricing-engine |
| #6 | 2026-03-23 | v2.0/cross-platform-otel-collector |
| #5 | 2026-03-23 | fix/traces-security-mcp-stats |
| #4 | 2026-03-23 | fix/traces-security-mcp-stats (round 2) |
| #3 | 2026-03-23 | fix/remove-auto-seed-data |
| #2 | 2026-03-23 | mcp/v1.1-fixes |
| #1 | 2026-03-23 | ci/pr-gate-workflow |

---

## Full Commit Log (440 commits, newest first)

### 2026-04-14 — P2 Completion + UI Polish

| Hash | Subject |
|------|---------|
| `99f4db4` | Merge pull request #56 from CohrintOps/fix/ui-finetune-dashboard |
| `dea95d0` | docs: comprehensive update — PRODUCT_STRATEGY v7.0, ADMIN_GUIDE +503 lines, docs.html new endpoints |
| `2587b40` | fix(ui): stack install-box commands vertically on mobile to prevent line breaks |
| `e975937` | chore: update GIT_MEMORY.md — PR #56 state, branch fix/ui-finetune-dashboard |
| `b681a78` | fix(ui): close modal via closeModal() on Escape/overlay to reset form fields |
| `999fec8` | fix(ui): dashboard polish — layout, UX, accessibility, mobile fixes |
| `5fcae70` | fix(ui): cross-platform tab layout + full data rendering implementation |
| `73c089f` | Merge pull request #55 from CohrintOps/feat/free-tier-50k |
| `bcf8362` | fix: eliminate benchmark N+1 query bomb + test quality fixes |
| `bc75328` | fix: post-audit security and correctness fixes (round 3) |
| `36e176f` | fix: remove dead kv_key column + surface Copilot/Datadog in connections panel |
| `a523720` | feat(tests+docs): add test suites 39-41 and document 10 new endpoints |
| `b13c87b` | fix(audit2): address 12 issues from second security + logic review |
| `80650db` | chore: update GIT_MEMORY.md for PR #55 state |
| `5fef2f9` | fix(security): address 14 audit findings across backend + frontend |
| `f8c0fa5` | docs(strategy): mark P2 tasks complete — Copilot adapter, report page, enterprise tier, benchmark schema, Datadog exporter |
| `a035691` | feat(p2): Copilot UI, report nav, benchmark schema, Datadog exporter |
| `5a49eca` | fix(security): address 8 code review issues in Copilot adapter + platform |
| `c92ec9f` | feat(p2): Copilot adapter, enterprise pricing, report page |
| `f88d064` | feat(trust): add trust.cohrint.com security page + P1 fixes |
| `8370400` | docs(strategy): v6.0 — competitive intel update + priority reorder |
| `3e42e59` | Merge pull request #54 from CohrintOps/feat/free-tier-50k |
| `0d2f499` | feat(pricing): raise free tier copy from 10K to 50K events/month |
| `c08f5c5` | Merge pull request #53 from CohrintOps/fix/ci-signup-rate-limit |
| `b64accc` | Merge pull request #52 from CohrintOps/fix/otel-developer-id-attribute |
| `ea242c7` | fix(auth): remove duplicate rate-limit block that bypassed CI bypass |

### 2026-04-13

| Hash | Subject |
|------|---------|
| `810309a` | fix(otel): recognize developer.id attribute for developer_id extraction |
| `8c323dc` | fix(ci): remove vantage-cli from publish workflow — directory has no package.json |

### 2026-04-12 — AI Spend Console + Vega Chatbot

| Hash | Subject |
|------|---------|
| `073d96d` | Merge pull request #51 from CohrintOps/feat/vega-chatbot |
| `5b7b56d` | fix(test): update test_unknown_model_uses_default_pricing for new contract |
| `a03916a` | fix(test): CL.25 use regex instead of tomllib for Python <3.11 compat |
| `bb21ee3` | fix(ci): resolve 4 CI failures — FC.07a, ON.7, CL.20, SC.6/7/8 |
| `7201810` | fix(breaking): update /developer/:email → :id across docs, suite 17, suite 37 |
| `a170d44` | docs: update spec + ADMIN_GUIDE with PR #51 decisions; add cspell config |
| `4a12d47` | fix(security): SRI, apiFetch isolation, api_base allowlist, SELECT *, last_error |
| `8d7fe73` | fix(security): audit fixes — email redaction, limit DoS, poll leak, test flaps |
| `7e31c93` | fix(api): self-service /developer/:id + legacy rows; add 7 missing tests |
| `237d927` | fix(ui): devDetailModal open via classList.add('active') to match closeModal pattern |
| `cbdbd42` | test(35): test_console_frontend.py — 10 contract tests for cross-platform routes |
| `fe9e85d` | test(35): conftest + test_trend.py — 12 tests for /trend endpoint |
| `55a1eea` | feat(scripts): add run-tests.sh with suite discovery, partial match, input validation |
| `de7a87c` | feat(ui): cp-console.js — full Cross-Platform tab implementation |
| `599ad60` | feat(ui): add Cross-Platform tab shell, modal element, nav wiring to app.html |
| `f55190` | feat(api): redact developer_email in /live for non-admin roles |
| `20a6ed0` | feat(api): /developer/:id replaces :email, developer_id in /developers, days validation backfill |
| `96e4b30` | feat(api): add /v1/cross-platform/trend with full calendar spine |
| `04b7fd0` | docs(spec): fix 6 re-audit issues — apiFetch exposure, developer_id migration, modal element, live poll tick, suite discovery |
| `a916c5b` | docs(spec): apply security + architecture audit fixes to AI Spend Console spec |
| `51f5e3d` | docs(spec): AI Spend Console MVP design — cross-platform dashboard tab |
| `2833b7c` | Merge pull request #50 from CohrintOps/feat/vega-chatbot |
| `e9dad11` | chore: schedule KV upload for 2026-04-13 in GIT_MEMORY |
| `bd121dd` | fix(chatbot): bundle all KV chunks into 1 write op instead of 117 |
| `13db719` | chore: update GIT_MEMORY.md — Vega chatbot PR #50 state |
| `219166b` | fix(chatbot): resolve 4 code-review issues |
| `1fbac63` | feat(chatbot): deploy Vega to Cloudflare Workers — live at vantage-chatbot.aman-lpucse.workers.dev |
| `6bd0086` | docs: add Vega chatbot implementation plan |
| `5b5bc36` | test(chatbot): 24 integration + unit tests for Vega |
| `52a7c12` | feat(chatbot): Vega frontend widget — safe DOM, textContent only |
| `6dcdffa` | feat(chatbot): doc chunks builder from docs.html |
| `befdd39` | feat(chatbot): chat + ticket handlers wired to Hono routes |
| `40cbe6c` | feat(chatbot): system prompt builder + KV rate limiter |
| `117c647` | feat(chatbot): knowledge lookup + output sanitizer |
| `9acecd1` | feat(chatbot): add 19-entry static knowledge base |
| `9158198` | feat(chatbot): scaffold Vega Worker with health endpoint |
| `857a001` | feat(dashboard): hold-to-reveal insight tooltips on all 31 cards |
| `c0813c7` | feat(frontend): hold-to-reveal card insight tooltip (4.5s hover) |
| `af09d35` | Merge pull request #49 from CohrintOps/fix/webkit-session-ci-warn |
| `bf16999` | fix(tests): patch vantage_agent.cli.auto_detect_backend not vantage_agent.backends |
| `dd8006e` | fix(cli): remove duplicate --version argument causing argparse conflict |
| `076e379` | feat(agent): add --version flag, docs upgrade/rollback section, bump to 0.2.4 |
| `a511803` | chore(agent): bump version to 0.2.3, update docs with Claude Max backend and permission tiers |
| `3e1b4f3` | fix(setup-wizard): skip wizard if permissions.json exists (returning user) |
| `efde568` | fix(cli): skip wizard when stdin not tty, guard EOFError on --backend claude startup |
| `4f84aca` | chore(vantage-agent): bump version to 0.2.0 |
| `e9183a3` | Merge pull request #48 from CohrintOps/fix/webkit-session-ci-warn |
| `98e0960` | chore: untrack egg-info dirs, awesome-claude-plugins, TODO.md + gitignore them |
| `fc7f6a9` | chore: gitignore egg-info dirs and scripts/pkg.sh |
| `f44ae7d` | fix(claude-backend): remove --no-session-persistence, add live integration tests |
| `1f82db5` | feat(vantage-agent): complete permission overhaul — ClaudeCliBackend, PreToolUse hook, tiered wizard |
| `82b5603` | test: session lifecycle, concurrent store, budget enforcement, history trim (TE1/2/5/6/8/9) |
| `658bbe2` | feat(cli): backend dispatch, permission server lifecycle, /tier command, wizard integration |
| `ac58243` | feat(claude-backend): stream-json subprocess, --resume history, exact cost extraction |
| `1417325` | feat(setup-wizard): tiered startup wizard, first-run detection, config.json |
| `e62889c` | feat(permission-server): Unix socket server, hook installer, settings merger |
| `8f3336c` | feat(permissions): add always_denied, audit_log, deny(), clear_session_approved(), config_dir param |
| `39c44ba` | fix(vantage-agent): resolve all pre-implementation flaws + document permission overhaul design |

### 2026-04-10

| Hash | Subject |
|------|---------|
| `7124bd4` | chore(todo): add competitive moat — hide proprietary features from public website |
| `139fae3` | Merge pull request #47 from CohrintOps/fix/webkit-session-ci-warn |
| `21e421f` | feat(benchmark): add benchmark opt-in toggle to settings page |
| `0c27110` | feat(free-tier): raise free tier limit from 10K to 50K events/month |
| `4e5fdb1` | Merge pull request #46 from CohrintOps/fix/webkit-session-ci-warn |
| `19081d9` | docs(agent): sync vantage-agent.md v2 fixes to docs/agents/ |
| `4f1b91a` | docs: add 10-year war room strategy, agent reference, and task dependency graph |

### 2026-04-09 — Enterprise Redesign + Security Audit

| Hash | Subject |
|------|---------|
| `b25ec3b` | chore: update GIT_MEMORY.md — PR #46 state, vantage-agent, PRODUCT_STRATEGY v4.0 |
| `80a2544` | fix(agent): fix all 12 flaws in vantage-agent.md |
| `451e099` | feat(agent): add vantage-agent.md — expert agent for Cohrint codebase |
| `e8ebab6` | docs(strategy): rewrite PRODUCT_STRATEGY.md to enterprise v4.0 |
| `5744c8f` | feat(landing): replace static feature grid with tabbed panel system |
| `98afa0b` | Merge pull request #45 from CohrintOps/fix/webkit-session-ci-warn |
| `8873cc8` | fix(ci): downgrade WebKit session-reload check to warn until SameSite=None deploys |
| `8d7f0d1` | fix(ci): downgrade WebKit session-reload check to warn until SameSite=None deploys |
| `f1cba2c` | Merge pull request #44 from CohrintOps/feat/semantic-cache-analytics |
| `72e3001` | fix(auth): use SameSite=None for session cookie to fix Safari ITP |
| `4e80bab` | fix(security): address 6 code review issues from PR #44 |
| `071b534` | chore: update GIT_MEMORY.md — website overhaul PR #44 state |
| `22de6c4` | fix(tests): add missing pytest import to test_dashboard_real_data.py |
| `500901c` | docs(security): internal security audit report 2026-04-09 — 9 findings, 3 high fixed |
| `03a344c` | feat(security): HSTS+COOP+CORP headers, brute-force on /session, prompt_hash validation, demo seed SQL |
| `71407ce` | feat(app): add Docs nav link + XSS-safe demo banner for demo org session |
| `9d85fba` | feat(website): Phase 2 enterprise redesign — indigo palette, new hero copy, security section, nav Request Access |
| `a75c7e9` | feat(website): Phase 1 content — remove fake reviews, tool names, false claims; fix pricing CTAs |
| `be7839b` | docs: remove Windsurf/Zed/JetBrains, redact pricing algorithm and MD5 from public docs |
| `343da10` | docs: add website enterprise overhaul design spec |
| `65d565e` | Merge pull request #43 from CohrintOps/feat/semantic-cache-analytics |
| `85fb67b` | fix(cache-analytics): resolve 4 code review issues |
| `856969b` | chore: update GIT_MEMORY.md — semantic cache analytics + PR #43 state |
| `e8996c2` | test(dr43): mark xfail pending analytics.ts timeseries production deploy |
| `7e7bcca` | docs+fix: redact infra IDs, update docs, improve agent API key UX |
| `2f6ef42` | fix(ci): resolve 5 pre-existing test failures in CI |
| `e091262` | feat(suite-37): cross-integration E2E dashboard cards test suite + analytics.ts fix |
| `b7b98e6` | Merge pull request #42 from Amanjain98/feat/semantic-cache-analytics |
| `90baabe` | refactor(otel): replace inline MODEL_PRICES with shared lib/pricing.ts import |
| `1a3860a` | fix(tests): add conftest.py + fix fresh_account usage in 36_semantic_cache |
| `6d955fb` | feat(semantic-cache): Phase 1+2 — cache analytics KPIs + exact-match dedup detection |
| `f7a86e9` | fix(docs): remove remaining TypeScript syntax from plain script tag |

### 2026-04-08 — Python Agent + Session-Centric Integration

| Hash | Subject |
|------|---------|
| `5935d9d` | fix(docs): update CLI path 3 to Python agent, fix hook link and JS syntax |
| `d61cbce` | fix(docs): correct D1 database name vantageai-db → vantage-events |
| `43a65f2` | ci: reduce GitHub Actions usage to stay within 2,000 min/month free tier |
| `e5f98fb` | fix(deploy): use custom_domain route binding to eliminate Zone:Workers Routes auth error |
| `a81313b` | Merge pull request #41 from Amanjain98/feat/session-centric-integration |
| `8de13bd` | test(suite-34): add Gemini CLI + Codex CLI session rollup tests |
| `760f742` | chore: update GIT_MEMORY.md — session-centric integration + PR #41 |
| `5fb4f1d` | test: add suites 34 (otel sessions) and 35 (local-proxy resume) |
| `3780bc7` | feat(worker): add otel_sessions rollup table and GET /v1/sessions endpoint |
| `0ab85b9` | feat(local-proxy): add --resume and --session-id flags for session continuity |
| `ca61eeb` | feat(mcp): add session_id to track_llm_call for session correlation |
| `6337a70` | docs: add implementation plan for backend session-centric integration |
| `66c0939` | docs: add backend session-centric audit spec (MCP + local-proxy + OTel) |
| `f0981a1` | Merge pull request #40 from Amanjain98/feat/cleanup-mobile-otel |
| `3f66796` | fix(rate_limiter): add fcntl file lock for true cross-process safety |
| `4651ac9` | test(local-proxy): add 13 tests for SessionStore covering save/load/listAll |
| `0e20530` | test(api_client): fix retry tests to mock messages.stream not messages.create |
| `c3b3896` | feat: add claude-intelligence plug-and-play package |
| `c3edb04` | feat(vantage-agent): Phase 6 — token-bucket rate limiting + exponential backoff |
| `c2b066b` | feat(local-proxy): add session persistence to ~/.vantage/sessions/ |
| `6f9cfa2` | chore: remove vantage-cli dir + rewrite remaining TS-dependent test suites |
| `7eaeb95` | feat(vantage-agent): add non-blocking OTel metrics/logs exporter |
| `84744621` | fix(frontend): update docs CLI references + add mobile responsive breakpoints |
| `d97e292` | Merge pull request #39 from Amanjain98/fix/audit-log-event-names |
| `73e9fbf` | Merge pull request #38 from Amanjain98/feat/vantage-agent-python |
| `e147536` | Merge pull request #37 from Amanjain98/chore/cli-dead-code-cleanup |
| `43ffe1a` | chore: resolve merge conflict — accept deletion of vantage-cli TS files |
| `f41fda0` | test(suite-31): replace vantage-cli JS harness with Python pricing in functional E2E |
| `8f128bd` | test(suites): rewrite vantage-cli test suites for Python vantage-agent |
| `356388d` | ci: remove vantage-cli references from ci-test.yml |
| `0da5724` | fix(audit): align event_name values with test expectations + add data_access logging |
| `c37eb1f` | ci: retrigger checks with updated CI workflow |
| `c7bb167` | ci: replace vantage-cli jobs with vantageai-agent Python tests |
| `b040d65` | test(cli): add 19 CLI tests + update design doc with implementation status |
| `11dd49c` | chore: rename package + command to vantageai-agent, publish 0.1.0 to PyPI |
| `1605776` | ci: fix PyPI version detection to use JSON API instead of pip index |
| `1dd9b99` | docs(vantage-agent): add README, complete pyproject.toml metadata, add PyPI publish to CI |
| `9afb61f` | feat(cli): add --backend flag, --resume, and summary subcommand |
| `f29ddff` | feat: add ToolRegistry, render_cost_summary_v2 with confidence labels, backend tests |
| `aed2181` | feat: add hook pipeline, VantageSession, SessionStore, backend abstraction (claude/codex/gemini/api) |
| `f6ab1fa` | fix: resolve 5 pre-existing bugs (optimizer, tracker anonymized/provider/flush, pricing unification) |
| `7b85562` | docs: add multi-backend cost intelligence implementation plan (14 tasks, 7 phases) |
| `6102810` | Merge pull request #36 from Amanjain98/feat/vantage-agent-python |
| `b1ce92d` | feat(frontend): scope UI to claude/codex/gemini — defer other agents |
| `72d1c5b` | docs: add multi-backend cost intelligence layer design spec |

### 2026-04-07 — Dashboard + Audit + CLI

| Hash | Subject |
|------|---------|
| `407665f` | docs: update ADMIN_GUIDE with Python agent feature comparison + 43 rendering tests |
| `ce8b70e` | feat(vantage-agent): port pricing, recommendations, classifier from TS CLI |
| `b0df8fd` | feat: consolidate CLI into single Python package, remove vantage-cli |
| `ecd753e` | feat(vantage-agent): merge vantage-cli features into Python agent |
| `9d8789e` | test(vantage-agent): add 60 integration tests covering full CLI functionality |
| `c79941c` | chore(cli): remove dead code — session-mode.ts, input-classifier.ts |
| `6022d96` | feat(vantage-agent): Python AI coding agent with API-direct tool execution |
| `d1568ea` | Merge pull request #35 from Amanjain98/fix/session-mode-tty-passthrough |
| `6b570eb` | fix(cli): implement /resume and /history commands, fix as-never type assertion |
| `682eed4` | feat(cli): add session persistence, permission passthrough, streaming deltas, and agent config reading |
| `690c46a` | fix(cli): use inherited stdout/stderr in session mode for real TTY passthrough |
| `cd78184` | Merge pull request #34 from Amanjain98/fix/audit-log-improvements |
| `0120dae` | fix(audit): concise event names + richer metadata, remove noisy data_access spam |
| `3bdd31b` | Merge pull request #33 from Amanjain98/fix/chart-date-accuracy |
| `c2a4431` | feat(dashboard): add Today — Hourly Spend bar chart |
| `4e9b2b4` | fix(dashboard): align all date windows to UTC midnight for accurate charts |
| `aae0a58` | Merge pull request #32 from Amanjain98/chore/post-deploy-verify-workflow |
| `1153a7e` | Merge pull request #31 from Amanjain98/fix/dashboard-chart-timezone-cache |
| `a45f98c` | fix(worker): invalidate team-scoped analytics cache keys on event ingest |
| `d171b61` | fix(ci): restore credential scanning on every PR via dedicated secret-scan job |
| `516ee8b` | fix(tests): exclude post-deploy suites from PR gate default run |
| `88f851b` | chore(ci): add post-deploy-verify workflow for deployment-dependent tests |
| `b954023` | Merge pull request #30 from Amanjain98/fix/cli-ux-rendering-cache-tests |
| `5f3252e` | fix(tests): accept 404 on AL.6 admin audit-log (route disabled = access blocked) |
| `af9e1e9` | fix(tests): accept 404 on AL.6 admin audit-log (route disabled = access blocked) |
| `ec2c697` | fix(dashboard): correct timezone date parsing + full cache invalidation |
| `c9dee61` | fix(worker): return 403 on /v1/admin/audit-log for org keys (AL.6) |
| `e97ec43` | fix(tests): use mock claude in pipe mode tests instead of skipping |
| `fc2d5f0` | fix(tests+ci): skip pipe mode tests without API key, build mcp+proxy in CI |
| `b0052f3` | fix(cli+tests): fix cost summary not shown in pipe mode + missing conftest fixtures |
| `9285cad` | fix(cli): apply TTY-aware stdin to runAgentBuffered |
| `4ae80b2` | fix(worker): fix SP.6-8, PE.6b, PE.7b, XP.62c backend failures |
| `8c91181` | fix(ci): add pytest to tests/requirements.txt |
| `971c904` | fix(tests+ci): fix PC.23/24 assertions, optimizer JSDoc, CLI build in ci-test.yml |
| `cc45916` | fix(tests+ci): fix 7 failing cli-unit-tests in PR gate |
| `984817` | feat(ci): auto-include all new suites in barricades via exclusion-based default |
| `8de03a9` | refactor(tests): migrate all test harnesses from .mjs to tsx .ts |
| `36cc561` | fix(ci): add ci-test.yml PR barricade, fix YAML indentation, delete stale test-renderer.mjs |
| `9b7ce92` | refactor(cli+ci): TS harnesses import real production code; add test barricade; trim 3 redundant workflows |
| `7ce362b` | fix(cli): normalize agent name before condition evaluation in getRecommendations |
| `0c255a5` | fix(cli): fix 3 review issues — failure state leak, session savings bleed, sessionId regex |
| `bb492d5` | tests(cli): add suite 34 — stream renderer, cache layer, structured data guards (35 checks) |

### 2026-04-06 — Zero-Bug Sweep + Claude Code Auto-Tracking + Audit Log

| Hash | Subject |
|------|---------|
| `7171ec9` | fix(cli): restore --verbose flag required by stream-json with --print |
| `fad05e1` | fix(cli): fix 3 cache/savings layer bugs — tracker queue, session accumulation, metrics agent |
| `b4b267b` | fix(cli): fix live rendering and permission prompts for claude agent |
| `1bbe782` | chore: refresh GIT_MEMORY.md with latest 15 commits |
| `f3feba4` | fix(ci): fix YAML syntax error in ci-version.yml (multiline bash string) |
| `f647f3a` | chore(release): bump vantage-cli to 2.2.3; refresh GIT_MEMORY.md |
| `5826556` | Merge pull request #29 from Amanjain98/fix/cli-ux-and-dynamic-versioning |
| `6245566` | feat(cli): render Claude tool use live like Claude terminal |
| `96afe9f` | fix(cli): fix 6 review issues — TS error, sessionId, timeouts, sleep, pkg-lock, structured-data |
| `2ee4719` | fix(cli): fix crash vectors, permission prompts, context loss, and update check |
| `d1df291` | fix(cli): fix multi-turn, optimizer code safety, anomaly detection, and session tracking |
| `88a8472` | fix(cli): fix 15 bugs across session-mode, tracker, runner, index, optimizer |
| `9dfa0cb` | fix(cli): fix SIGTERM race, anomaly avg, token count, and stream end listener |
| `7599574` | fix(cli): fix multi-turn conversation context loss after 1-2 prompts |
| `59bf7cf` | fix(versions): eliminate all hardcoded version strings across 5 packages |
| `1600a51` | fix(cli): show tokens/cost saved in session summary; fix session mode savings |
| `d9c4328` | fix(cli): fix session mode REPL prompt appearing mid-response |
| `16a2c19` | fix(cli): suppress stdin warning when running interactively |
| `d303774` | fix(cli): fix multi-turn conversation context loss (duplicate) |
| `d3a4caf` | Merge pull request #28 from Amanjain98/fix/zero-bugs-sweep |
| `45fd91c` | chore(release): bump patch versions for bug-fix release |
| `dfce416` | fix(otel-realtime): fix all critical + high OTel pipeline and live feed gaps |
| `0757335` | fix(sweep5): 4 bugs from cross-component audit |
| `6391463` | fix(sweep4): 31 bugs across all 6 components |
| `4769c6a` | fix(audit): store real member email in actor_email column |
| `6a28255` | fix(sweep3): 13 more bugs from third scan |
| `637eb3c` | fix(sweep2): 8 more bugs from second scan |
| `a12dd1a` | fix(sweep): fix 7 confirmed bugs found in zero-bugs scan |
| `3ba275b` | fix(data-integrity): remove fake data, wire integrations view to real API |
| `c7cb0bb` | Merge pull request #27 from Amanjain98/fix/dashboard-token-usage-cache-savings |
| `e0e52e0` | feat(tests): add suite 33 frontend contract + fix 2 backend data bugs |
| `9b91737` | feat(resilience): offline detection, API cache, skeleton loaders, rate limiting |
| `47d72c5` | fix(dashboard): fix session fields, trend arrows, SSE URL, spelling |
| `fca5022` | fix(dashboard): fix second wave of field mismatches and phantom columns |
| `6c41821` | fix(dashboard): fix all API field mismatches across every view |
| `9e987d9` | fix(dashboard): fix field name mismatches causing zero spend and empty chart |
| `5462312` | fix(dashboard): add Token Usage and Cache Savings KPI cards to overview |
| `a50cb8c` | Merge pull request #26 from Amanjain98/feat/update-notifier-and-deprecation |
| `c4d6374` | feat(cli): add update notifier + auto-deprecate old versions on publish |
| `c8a380d` | Merge pull request #25 from Amanjain98/feat/claude-code-auto-tracking |
| `f72ed4e` | docs: update Claude Code section with auto-tracking guide + ADMIN_GUIDE §23 |
| `4a83e74` | fix(proxy): improve pushScanResults error handling and type safety |
| `2a124a4` | Merge pull request #24 from Amanjain98/feat/enterprise-soc2-audit-log |
| `7fc554c` | fix(ci): replace time.sleep with wait_for_url in WebKit session-persistence test |
| `c8b0d9f` | fix(audit): prevent auth.login noise on audit-log reads, stable sort, fix WebKit CI |
| `e076b2e` | fix(tracking): fix dirToSlug algorithm + include cacheCreationTokens in total_tokens |
| `00ff8f0` | test(suite32): rewrite audit log tests — 42 checks, every event type triggered and verified live |
| `cf0842d` | fix(proxy): fix pushScanResults — correct endpoint, event_id, dedup per turn |
| `b56fb28` | docs: replace inaccurate 100% coverage claim with accurate roadmap status |
| `2a61218` | feat(frontend): add public roadmap.html with honest integration status |
| `c1d00c2` | feat(dashboard): add Security (audit log) and Integrations views |
| `ed56489` | test(suite32): add audit log test suite AL.1-AL.24 |
| `41682cd` | feat(audit): log admin_action events for budget, alerts, members |
| `8ac30b6` | feat(audit): log data_access.analytics on every analytics GET |
| `23d57a1` | feat(audit): log auth.login and auth.failed events |
| `d137436` | feat(audit): import logAudit in admin.ts |
| `1c002a1` | feat(audit): register audit-log routes, add admin endpoint |
| `da4f4f3` | fix(audit): enforce limit lower bound of 1 |
| `2438c4f` | feat(audit): add GET /v1/audit-log endpoint with CSV export |
| `ff7de4f` | feat(audit): add shared logAudit / logAuditRaw helpers |
| `8022648` | feat(db): add event_type column to audit_events |
| `055e1ed` | docs: add enterprise SOC2 prep + coverage accuracy design spec |

### 2026-04-05 — Connected Tools + OTel Live Feed

| Hash | Subject |
|------|---------|
| `c331103` | Merge pull request #23 from Amanjain98/fix/connected-tools-widget |
| `6aee175` | Merge pull request #22 from Amanjain98/fix/otel-live-feed-broadcast |
| `447cb6e` | fix(dashboard): show connected tools from otel_sources and billing_connections |
| `702604` | test(suites 26+27): add SSE live stream tests for CLI and SDK integrations |
| `b5eec1a` | test(otel): add SSE/KV broadcast test that would have caught the live feed gap |
| `3d37689` | fix(otel): broadcast token events to KV so they appear in SSE live feed |

### 2026-03-31

| Hash | Subject |
|------|---------|
| `f58c587` | Merge pull request #20 from Amanjain98/fix/ci-rate-limit-bypass |
| `a2b39fd` | chore: merge main — apply slim PR gate + weekly CI schedule |
| `bc3ccd7` | Merge pull request #21 from Amanjain98/fix/ci-free-tier-limits |
| `f26c397` | fix(ci): slim PR gate to fast jobs only + weekly nightly schedule |

### 2026-03-28 — Recommendations + CI Hardening

| Hash | Subject |
|------|---------|
| `6f66bee` | feat(cli): extract session ID via stream-json for reliable --resume context |
| `ae3295b` | chore(cli): bump version to 2.2.0 |
| `0329188` | fix(cli): use --resume with session ID for reliable context |
| `f08fb72` | Merge pull request #19 from Amanjain98/fix/ci-rate-limit-bypass |
| `970fdb1` | fix: restore retry loop in signup_api (lost during rebase) |
| `f2e02d0` | fix: graceful degradation when KV rate limit quota exceeded |
| `52d02b8` | fix: use correct API endpoints in cost-check workflow |
| `667b414` | feat: update docs page SEO for AI coding tool cost intelligence |
| `537b0e0` | feat: reposition landing page as AI coding tool cost intelligence |
| `a3003e7` | fix(cli): support multi-line paste input in REPL |
| `d1d37e0` | fix: remove accidentally staged superpowers files |
| `6db62d5` | fix: add CI bypass for signup rate limiting + increase limit to 30/hr |
| `2983e10` | ci: trigger fresh PR gate with CI account secrets |
| `cb21825` | Merge pull request #18 from Amanjain98/v2.9/recommendations-and-review-fixes |
| `00c829a` | test: update all frontend test suites for new dashboard design |
| `27bad4a` | fix: address code review findings in new dashboard |
| `c4bc696` | feat: rebuild app.html as dark industrial command center dashboard |
| `b6dc701` | fix: reuse pre-seeded CI account to avoid signup rate limits |
| `64cffd0` | fix: address code review findings — preserve config args + increment after success |
| `144df30` | test(cli): add source-code verification tests for spinner and conversation context |
| `72778f2` | feat: wire conversation context into REPL and executePrompt() |
| `4c3bb1f` | feat(cli): implement --continue support in Gemini adapter |
| `2331873` | feat(cli): implement --continue support in Claude adapter |
| `2240d3d` | feat(cli): extend AgentAdapter interface with optional --continue support |
| `fd147b8` | feat: add spinner to ui.ts and integrate into runner.ts |
| `9fbd76e` | feat(cli): show spinner while waiting for agent response |
| `a0a2df3` | feat(cli): add terminal spinner utility for progress feedback |

### 2026-03-25 — Live Recommendation Engine

| Hash | Subject |
|------|---------|
| `f3bc750` | fix: strict TypeScript errors in recommendations.ts |
| `cee81f5` | fix: address 5 code review findings from multi-agent review |
| `26ba50d` | feat: agent-aware live recommendation engine |
| `2b04c47` | fix: address 5 code review findings (duplicate) |
| `5990552` | feat: agent-aware live recommendation engine (duplicate) |
| `9246ed4` | Merge pull request #17 from Amanjain98/fix/cli-critical-bugs |

### 2026-03-24 — v2 Full Feature Set

| Hash | Subject |
|------|---------|
| `89a1727` | feat: add browser tab favicon (green dot logo) |
| `254ae00` | fix: cross-browser test — filter Google Fonts download errors in CI |
| `7696b65` | fix: complete all 16 remaining security vulnerabilities |
| `b200c72` | fix: competitive intelligence protection + security hardening |
| `b5f64e2` | fix: UI bugs — light theme code colors, sidebar, accessibility, XSS |
| `e384d2a` | fix: CLI critical bugs + security hardening + comprehensive test suites |
| `d9e35df` | Merge pull request #16 from Amanjain98/fix/repo-backup-auth |
| `4789e97` | fix: repo backup — detect PAT type, diagnose 404, clear error messages |
| `aa45a75` | Merge pull request #15 from Amanjain98/v2.8/auto-publish-ci |
| `c47f285` | feat: auto-publish CI workflow + bump vantageai-cli to v2.1.0 |
| `55b659c` | Merge pull request #14 from Amanjain98/v2.7/smart-session-optimization |
| `0a60899` | Merge pull request #13 from Amanjain98/v2.6/docs-overhaul-collapsible-sidebar |
| `84fc197` | fix: session stderr inherit for agent prompts + /mcp passthrough + honest gaps |
| `1d551ad` | feat: smart session optimization — classify, optimize, recover |
| `f7cc1b9` | feat: docs overhaul — collapsible sidebar, 3-path quickstart, 40 tough tests |
| `f8d2fe2` | Merge pull request #12 from Amanjain98/v2.5/security-governance-real-data |
| `d89008` | feat: security & governance — real data, audit logging, 40 tests |
| `1a72ffb` | Merge pull request #11 from Amanjain98/v2.4/landing-page-v2-features |
| `a4dc788` | test: add 35 landing page content tests (suite 22) |
| `6e16e60` | feat: update landing page with all v2 features + interactive demo |
| `813e142` | Merge pull request #10 from Amanjain98/v2.3/vantage-cli-stable |
| `dd543df` | feat: add /session mode for agent in-house commands + fix review issues |
| `dab4166` | fix: resolve 3 CRITICAL + 3 HIGH issues from code review |
| `45caf70` | fix: tracker sends correct EventIn format + add /summary, /budget, anomaly detection |
| `3c4326d` | fix: harden vantage-cli for stability — no hangs, no crashes, clear errors |
| `6c8ad72` | Merge pull request #9 from Amanjain98/v2.2/vantage-cli-agent-wrapper |
| `39bf0fb` | feat: vantage-cli agent wrapper + security fixes + CI + docs |
| `138abae` | feat: add 33 CLI tests + update ADMIN_GUIDE with vantage-cli docs |
| `29ddcaa` | feat: add vantage-cli — transparent AI agent wrapper with prompt optimization |
| `6f06540` | feat: rewrite token optimizer with real compression (5-layer engine) |
| `113e4b0` | Merge pull request #8 from Amanjain98/v2.1/dashboard-real-data-cleanup |
| `25d3b76` | feat: add 42 dashboard real-data tests + update ADMIN_GUIDE docs |
| `0e7e815` | feat: remove all fake data from dashboard — real API data only |
| `74e3975` | fix: trace chart crash + merge Token Analytics into All AI Spend |
| `047ec95` | Merge pull request #7 from Amanjain98/v2.1/privacy-mode-pricing-engine |
| `79ed55d` | feat: add 83 tests + update docs for privacy mode, pricing engine, local proxy |
| `d4e7907` | feat: add comprehensive 8-phase AI consumption analysis prompt |
| `c68e69c` | fix: add missing conftest.py for OTel test fixtures (headers/emails) |
| `b8d1603` | feat: SDK privacy mode + OTel pricing engine + local proxy + SQLite date fixes |

### 2026-03-23 — Initial v2 + CI/CD Foundation

| Hash | Subject |
|------|---------|
| `7acc2c2` | Merge pull request #6 from Amanjain98/v2.0/cross-platform-otel-collector |
| `7e052e0` | fix: auth reload loop + cross-platform cookie auth |
| `0224e98` | feat: cross-platform OTel collector + live AI spend dashboard (v2) |
| `2f21b0d` | Merge pull request #5 from Amanjain98/fix/traces-security-mcp-stats |
| `a902ad6` | feat: MCP stress tests (84 checks) + harden server + CI gate |
| `152e09a` | fix: dashboard test selectors + run ALL test suites (no skipping) |
| `aff80a9` | feat: add optimizer/anomaly tools to MCP docs + anomaly detection test |
| `9a4ab05` | Merge pull request #4 from Amanjain98/fix/traces-security-mcp-stats |
| `e3dfba6` | fix: remove fake VS Code extension — VS Code uses MCP, not extension |
| `6ff0776` | feat: default to light theme, dark mode opt-in |
| `1e40176` | feat: consistent dark/light theme across all pages |
| `a758e93` | fix: unblock test suite from flaky env-tests DNS failures |
| `0479818` | feat: add anomaly detection as landing page feature |
| `7963403` | feat: landing page — add optimizer, hallucination, recommendations, MCP features |
| `cc65c92` | fix: traces view uses real API, security view shows real data only |
| `73e8431` | Merge pull request #3 from Amanjain98/fix/remove-auto-seed-data |
| `62fd305` | Merge pull request #2 from Amanjain98/mcp/v1.1-fixes |
| `2e81e2f` | fix: remove all auto-generated fake/seed data from dashboard |
| `18afebd` | feat: enhance MCP optimizer — works as default token/prompt optimizer |
| `09114ee` | feat: MCP server v1.1.0 — fix bugs, add 24 models, improve docs |
| `16e3f7d` | Merge pull request #1 from Amanjain98/ci/pr-gate-workflow |
| `9bbb42c` | fix: add contents:read permission to cost-check workflow |
| `de2a29d` | fix: handle navigation context destruction in visual consistency tests |
| `184b9d1` | fix: remove ref_name from cross-browser artifact names (invalid / char on PRs) |
| `37ef31b` | fix: preview deploy config + skip Playwright when Chromium not installed |
| `bf3753d` | ci: add PR gate workflow — require CI pass before merge to main |
| `b26b76c` | fix: resolve dashboard reliance, visual consistency, and org admin test failures |
| `9f6d6e6` | fix: remove auth gate from docs page — fixes Safari redirect loop |
| `2821468` | fix: dashboard shows real API data, fix MCP module format, enhance docs |
| `ee97d1d` | fix: resolve CI test suite + cross-browser failures and add OG image |
| `109a550` | fix: resolve all test suite failures from CI run 23410567245 |
| `a9150c8` | fix: resolve all API test failures from CI run 23410332144 |
| `8aab622` | fix: resolve all cross-browser CI failures from run 23410206336 |
| `bbedf01` | fix: resolve cross-browser test failures + add CI failure summaries |
| `0420626` | fix: add /v1/health alias so CI health checks pass |
| `3c4579b` | fix: resolve cross-browser test failures (Safari CORS, auth redirect, headers) |
| `1bb4ade` | feat: anomaly detection — Z-score cost spike alerts via cron trigger |
| `5609d17` | fix: disable auto-popup of seed data generator on app load |

### 2026-03-22

| Hash | Subject |
|------|---------|
| `ebffee8` | feat: integrate AI Token Optimizer from Vantage-AI-Optimizer repo |
| `5598557` | docs: add interactive Excalidraw architecture diagrams to admin guide |
| `96c5b52` | feat: cross-browser compatibility test suite + CI workflow |
| `7eccea2` | feat: superadmin platform + CI/CD promote fixes |

### 2026-03-20 — Infrastructure Foundation

| Hash | Subject |
|------|---------|
| `de67035` | feat: restructure test infra into category-based suites + admin guide |
| `a129a09` | fix: resolve 3 bugs causing GitHub Actions to fail continuously |
| `b15dced` | fix: retry CF Pages/Worker deploy on 504 gateway timeout (4 attempts, exponential backoff) |
| `dd2c234` | feat: full branching CI/CD — backup, branch protection, comprehensive test suites |
| `b211f12` | feat: dark/light theme toggle + version branching CI/CD strategy |
| `1555a1a` | fix: RBAC test key staleness + analytics/teams ambiguous column |
| `9cd6cd9` | feat: CI/CD test pipeline + fix recover 500 + contact us section |
| `570da78` | fix: treat null sse_token as warning in tests (KV daily limit) |
| `dd19d6a` | fix: handle Cloudflare KV daily write limit (free tier error 10048) |
| `eabe734` | fix: correct sidebar nav selectors in test_04_dashboard.py |
| `29ed052` | fix: wrap KV.put in recovery token generation with try/catch |
| `a60ed53` | fix: make KV operations resilient + fix worker routing for api.cohrint.com |
| `5f5c5ef` | fix: filter console noise in tests + fix test_04 selectors |
| `4e72549` | feat: test suite 21 + CSP fix for Cloudflare Insights beacon |
| `d211c5f` | fix: syntax error in loadMembersView broke all nav buttons |
| `b96342f` | fix: move FORCE_JAVASCRIPT_ACTIONS_TO_NODE24 to top-level workflow env |
| `65eca7e` | fix: upgrade GitHub Actions to Node.js 24 |
| `88502b4` | fix: add root package-lock.json + cache node_modules in Pages deploy |
| `eac211f` | fix: Cloudflare deploy config + TypeScript errors in vantageai-api |
| `d399fcc` | fix: unify brand name to Cohrint everywhere |
| `f519970` | fix: stability — SW network-first, browser logger, account/settings bugs |
| `74d0243` | fix: account view, settings view, duplicate dashboard button |
| `e4a05bb` | feat: comprehensive test suite (tests/11-20) + logging infrastructure |

### 2026-03-19 — Auth + Session System

| Hash | Subject |
|------|---------|
| `edba8ea` | fix: protect recovery token from email link scanners (Gmail/Outlook) |
| `06447b0` | feat: one-time recovery token — click email link to get new key instantly |
| `f252f33` | fix: add api.cohrint.com to CSP connect-src + fix nav button timeout |
| `99d76b2` | fix: bump SDK to v0.3.1, add User-Agent header, add full E2E test suite |
| `5f2504d` | fix: accept all SDK field name variants in event ingest + E2E test suite |
| `a379e4b` | fix: prevent Worker crashes from killing CORS headers on errors |
| `19a3802` | fix: prevent nav auth button flash by hiding until session check completes |
| `30f1843` | fix: add Sign in link to signup nav, fix auth redirect loop guard, fix demo label |
| `d9c6b0f` | fix: add Sign in + Sign up to homepage nav, detect session state |
| `27136c6` | fix: make signup option prominent on auth page |
| `5414baa` | fix: break auth↔app infinite redirect loop |
| `a99e2c2` | feat: ship JS/TS SDK docs + fix SSE real-time auth with short-lived sse_token |
| `c559642` | fix: remove redirect loops in _redirects |
| `84d0822` | feat: replace localStorage auth with server-side session cookies |
| `63e8f36` | fix: remove Supabase auth, add API-key auth + working settings/notifications |
| `9c9b7f7` | fix: privacy/terms pages, package names, free tier limit + upgrade UX |
| `6d3b574` | feat: ship 5 product gaps + TypeScript SDK + Python SDK v0.3.0 |

### 2026-03-18 — Initial Commit

| Hash | Subject |
|------|---------|
| `e444c45` | Updated code |
| `98df16e` | feat: Cloudflare Worker backend (D1 + KV + SSE) |
| `44bc324` | fix: dashboard and calculator not loading |
| `b404331` | chore: standardise all URLs to vantageai.pages.dev |
| `c347694` | fix: resolve nav() hoisting bug + 6 other audit-found issues |
| `4f0fe42` | fix: close all 10 product gaps (SSE, traces, Slack, PWA, CI cost gate, queue warnings) |
| `3ee29b8` | Add TypeScript/JS SDK and update UI with multi-language support |
| `5e6e1ab` | Add Cloudflare Pages + VS Code integration |
| `7b9669c` | Add product strategy doc and improve landing/dashboard UI |
| `64aafd9` | Initial commit: Cohrint project |

---

## Stats

| Metric | Count |
|--------|-------|
| Total commits (main) | 440 |
| Merged PRs | 56 |
| Test suites shipped | 41 |
| Test checks | 283+ |
| D1 migrations | 14 |
| DB tables | 18 |
| API routes (files) | 17 |
| Days of development | 27 (Mar 18 – Apr 14, 2026) |
