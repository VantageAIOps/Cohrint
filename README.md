# Cohrint

> **AI Cost Intelligence & Observability Platform** — real-time visibility into LLM spend, token efficiency, model performance, and cross-tool usage through a two-line SDK integration.

[![CI](https://github.com/cohrint/cohrint/actions/workflows/ci.yml/badge.svg)](https://github.com/cohrint/cohrint/actions)
[![License: Proprietary](https://img.shields.io/badge/license-proprietary-red.svg)](#license)
[![API](https://img.shields.io/badge/API-api.cohrint.com-blue)](https://api.cohrint.com/v1/health)
[![Dashboard](https://img.shields.io/badge/Dashboard-cohrint.com-green)](https://cohrint.com)

---

## Table of Contents

- [What is Cohrint?](#what-is-cohrint)
- [Features](#features)
- [Architecture](#architecture)
- [Repository Layout](#repository-layout)
- [Quick Start](#quick-start)
- [Development Setup](#development-setup)
- [Running Tests](#running-tests)
- [Deployment](#deployment)
- [Contributing](#contributing)
- [Documentation](#documentation)
- [Support](#support)

---

## What is Cohrint?

Cohrint gives engineering teams a single pane of glass over their AI spend across every tool their developers use — Claude, OpenAI, Gemini, GitHub Copilot, Cursor, Datadog, and more.

- **Two-line SDK integration** — wrap your existing OpenAI/Anthropic client, ship events transparently.
- **Privacy-first** — strict mode keeps prompts and responses on your machine; only metadata leaves.
- **Cross-platform** — one dashboard for all LLM tooling via OpenTelemetry-compatible collectors.
- **Semantic cache** — automatic cost savings on semantically equivalent prompts.
- **Budgets & alerts** — Slack notifications when team or org thresholds are crossed.

**Production**: [api.cohrint.com](https://api.cohrint.com) · [cohrint.com](https://cohrint.com)

---

## Features

| Category | Feature |
|---|---|
| **Ingest** | Python/JS SDKs, MCP server, CLI wrapper, local proxy, OTel collector |
| **Analytics** | Real-time spend, token efficiency, model/team breakdowns, trace DAG |
| **Optimization** | Semantic cache (Vectorize + BGE-small), prompt registry with A/B versions |
| **Governance** | RBAC (admin/member/ceo/superadmin), budgets, rate limits, audit log |
| **Integrations** | Claude Code, GitHub Copilot metrics, Datadog LLM observability, Slack |
| **Benchmarks** | Anonymized industry percentile rankings (k-anonymity ≥ 5 orgs) |

---

## Architecture

```
┌──────────── Clients ────────────┐
│ Python SDK · JS SDK · MCP · CLI │
│ Local Proxy · OTel · Browser UI │
└──────────────┬──────────────────┘
               │ HTTPS (Bearer crt_… / Session cookie)
               ▼
┌───────── Cloudflare Worker (Hono) ─────────┐
│  api.cohrint.com                           │
│  CORS → Auth → Rate Limit → Role Guard     │
│  events · analytics · cache · prompts      │
│  benchmark · audit · alerts · admin        │
└───────┬─────────────┬──────────────┬───────┘
        ▼             ▼              ▼
     D1 (SQLite)   KV (cache)   Vectorize (embeddings)
                                Workers AI (BGE-small)

┌───── Cloudflare Pages ─────┐
│  cohrint.com (static UI)   │
│  Chart.js + vanilla JS     │
└────────────────────────────┘
```

**Stack**

| Layer | Technology |
|---|---|
| API | Cloudflare Workers + Hono (TypeScript) |
| DB | Cloudflare D1 (SQLite) |
| Cache / Pub-Sub | Cloudflare KV |
| Vector Store | Cloudflare Vectorize |
| Embeddings | Workers AI (`@cf/baai/bge-small-en-v1.5`) |
| Frontend | Cloudflare Pages (static HTML/JS + Chart.js) |
| Email | Resend |
| Tests | Python 3.11+ pytest (live API, no mocks) |
| CI/CD | GitHub Actions → auto-deploy on merge to `main` |

---

## Repository Layout

```
Cohrint/
├── cohrint-worker/         # API (Cloudflare Worker, Hono, D1)
│   ├── src/                # Route handlers, middleware, services
│   ├── migrations/         # SQL migrations
│   └── schema.sql
├── cohrint-frontend/       # Static dashboard (cohrint.com)
│   ├── app.html            # Authenticated dashboard
│   ├── index.html          # Landing page
│   └── docs.html           # Public docs
├── cohrint-js-sdk/         # npm: cohrint (OpenAI + Anthropic wrappers)
├── cohrint-mcp/            # MCP server for Cursor/Windsurf/VS Code
├── cohrint-cli/            # CLI (agent wrapper + admin commands)
├── cohrint-local-proxy/    # Privacy-first local LLM gateway
├── cohrint-agent/          # Python agent tooling
├── cohrint-optimizer/      # Prompt optimizer service
├── cohrint-chatbot/        # Vega chatbot
├── tests/
│   └── suites/             # 40+ pytest suites (live integration tests)
├── docs/                   # Additional internal docs
├── scripts/                # Ops scripts
└── CLAUDE.md               # Rules for AI coding agents
```

---

## Quick Start

### Prerequisites

- **Node.js** ≥ 18
- **Python** ≥ 3.11 (for tests)
- **Cloudflare account** + `wrangler` CLI (`npm i -g wrangler`)
- **GitHub CLI** (`gh`) for PR workflows

### Get Running in 5 Minutes

```bash
# 1. Clone
git clone https://github.com/cohrint/cohrint.git
cd cohrint

# 2. Install worker deps
cd cohrint-worker && npm install && cd ..

# 3. Install root deps (wrangler)
npm install

# 4. Authenticate with Cloudflare
npx wrangler login

# 5. Start local worker + frontend
cd cohrint-worker && npm run dev       # terminal 1 — API on :8787
npm run dev                            # terminal 2 — frontend on :8788

# 6. Smoke test
curl http://localhost:8787/v1/health
```

Open http://localhost:8788 to see the dashboard.

---

## Development Setup

### Branching Workflow

**Never push to `main`.** Always:

```bash
git checkout -b feat/your-change      # or fix/, chore/, docs/
# … make changes …
git commit -m "feat: describe change"
git push -u origin feat/your-change
gh pr create --fill
```

CI runs typecheck + tests. Merge when green.

### Type-Checking

```bash
cd cohrint-worker && npm run typecheck
cd ../cohrint-cli && npm run build
cd ../cohrint-mcp && npm run build
```

### Working with the Database (D1)

Dates in SQLite diverge by table — **bind to match the column type** or SQLite silently coerces to `0` and filters return all rows:

- `INTEGER unixepoch` → `events`, `orgs`, `org_members`, `sessions`, `alert_log`, `platform_*`, `audit_events`, `alert_configs`, `team_budgets`
- `TEXT 'YYYY-MM-DD HH:MM:SS'` → `cross_platform_usage`, `otel_events`, `benchmark_snapshots`, `prompts`, `prompt_versions`, `semantic_cache_entries`, `copilot_connections`, `datadog_connections`

Always use **parameterized queries** — never concatenate user input into SQL.

### Test Seed Data (DA45)

Persistent test accounts live at `tests/artifacts/da45_seed_state.json` (gitignored). **Always load this state** before creating new accounts for dashboard/API testing.

```python
import json
from pathlib import Path
state = json.loads(Path("tests/artifacts/da45_seed_state.json").read_text())
admin_key = state["admin"]["api_key"]
```

Re-seed: `python tests/suites/45_dashboard_api_coverage/seed.py --force`

---

## Running Tests

Every PR needs tests in `tests/suites/` — no exceptions.

```bash
# Fast smoke tests
npm test

# Full suite
npm run test:all

# Core suites (pre-PR check)
python -m pytest \
  tests/suites/17_otel/ \
  tests/suites/18_sdk_privacy/ \
  tests/suites/19_local_proxy/ \
  tests/suites/20_dashboard_real_data/ \
  tests/suites/21_vantage_cli/ \
  tests/suites/32_audit_log/ \
  tests/suites/33_frontend_contract/ -v

# Production smoke
npm run test:smoke
```

Tests are **live** — they hit the real API. No mocking. Use the DA45 seed state to avoid creating throwaway accounts.

---

## Deployment

Production deploys automatically on merge to `main` via GitHub Actions.

**Manual deploy** (only when explicitly instructed):

```bash
# API
cd cohrint-worker && npx wrangler deploy

# Frontend
npx wrangler pages deploy ./cohrint-frontend --project-name=cohrint
```

**Never**: `git push --force origin main` · `wrangler delete` · `DROP TABLE` on production · skip CI hooks.

See [`cohrint-worker/DEPLOY.md`](cohrint-worker/DEPLOY.md) for the full runbook.

---

## Contributing

1. Read [`CLAUDE.md`](CLAUDE.md) for code rules and forbidden actions.
2. Branch → implement → add tests → PR → wait for CI → merge.
3. Use conventional commits: `feat:`, `fix:`, `chore:`, `docs:`, `refactor:`, `test:`.
4. Don't commit secrets (`.env`, API keys, `crt_*` tokens).
5. No fake or demo data — real API data or honest empty states only.

All API routes require auth (Bearer token or session cookie). SDK/CLI packages have **zero npm runtime dependencies** — keep it that way.

---

## Documentation

| Doc | Purpose |
|---|---|
| [`CLAUDE.md`](CLAUDE.md) | Rules and conventions for AI coding agents |
| [`cohrint-frontend/docs.html`](cohrint-frontend/docs.html) | Public-facing API docs |
| [`cohrint-worker/DEPLOY.md`](cohrint-worker/DEPLOY.md) | Deployment runbook |

### API Endpoints (summary)

- **Auth** — `/v1/auth/signup`, `/v1/auth/session`
- **Analytics** — `/v1/analytics/{summary,kpis,timeseries,models,teams,traces}`
- **Cross-platform** — `/v1/cross-platform/{summary,developers,models,live,budget}`
- **OTel ingest** — `/v1/otel/v1/{metrics,logs}`
- **Health** — `/v1/health`

Full reference: https://cohrint.com/docs.html

---

## Support

- **Issues**: https://github.com/cohrint/cohrint/issues
- **Security**: security@cohrint.com (please don't file public issues for vulnerabilities)
- **General**: hello@cohrint.com

---

## License

Proprietary — © Cohrint. All rights reserved. Internal code — not for public redistribution.
