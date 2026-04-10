# VantageAI — TODO

Last updated: 2026-04-08

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

- [ ] **Audit public website for over-exposed features** — review vantageaiops.com and docs.html for any
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
