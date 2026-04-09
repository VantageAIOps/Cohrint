# Suite 37 — All Dashboard Cards, Cross-Integration E2E

**Date:** 2026-04-09  
**Status:** Approved → Implementing  
**Labels:** DC.1 – DC.90

---

## Problem

Suite 20 (`20_dashboard_real_data`) validates that API endpoints return correct schemas. It does not verify that **every dashboard card reflects accurate aggregated data from all five ingestion paths**: OTel, JS SDK, MCP tool, local-proxy, and direct API. A regression like timeseries querying the wrong table (the bug fixed in this session) would not be caught.

---

## Goal

One mega-suite that seeds known data from each integration, then asserts every dashboard card shows the correct combined totals, fields, and cross-source aggregation.

---

## Data Architecture

```
POST /v1/otel/v1/metrics  →  cross_platform_usage  →  timeseries, today, models, cross-platform/*
POST /v1/events           →  events                →  kpis, summary, teams, traces
```

Both tables must be seeded to cover all cards.

---

## Seed Strategy

A single module-scoped `seeded` fixture creates one fresh account, then ingests:

| # | Integration | Method | Table | Provider | Model | Cost | Team | Developer |
|---|---|---|---|---|---|---|---|---|
| 1 | OTel (claude_code) | POST /v1/otel/v1/metrics (OTLP) | cross_platform_usage | claude_code | claude-sonnet-4-6 | $0.025 | backend | otel1@dc.test |
| 2 | OTel (openai via gen_ai) | POST /v1/otel/v1/metrics (OTLP) | cross_platform_usage | openai_api | gpt-4o | $0.015 | frontend | otel2@dc.test |
| 3 | JS SDK | node subprocess → vantage-js-sdk | events | openai | gpt-4o | $0.010 | frontend | sdk@dc.test |
| 4 | MCP tool | vantage-mcp JSON-RPC subprocess | events | anthropic | claude-3-5-haiku | $0.008 | backend | mcp@dc.test |
| 5 | Local proxy | POST /v1/events (sdk_language=local-proxy) | events | openai | gpt-4o-mini | $0.006 | data | proxy@dc.test |
| 6 | Direct API | POST /v1/events | events | anthropic | claude-3-5-sonnet | $0.012 | data | direct@dc.test |

Expected totals:
- `cross_platform_usage`: $0.040 (OTel rows 1+2)
- `events`: $0.036 (rows 3+4+5+6)

If a subprocess integration (SDK, MCP) is unavailable (missing dist/), it is marked `skipped` in SeedContext and dependent assertions use `pytest.skip()`.

---

## Test Sections (9 classes, 90 tests)

| Section | Class | Labels | Cards Covered |
|---|---|---|---|
| A | TestOverviewKPICards | DC.1–DC.15 | Total Spend, Costliest Tool, Active Devs, Budget, Token Usage, Cache Savings, Daily Spend Chart, Tool Comparison, Live Feed |
| B | TestSpendAnalysisCards | DC.16–DC.28 | Period Spend, Top Model, Total Reqs, Avg Cost, Spend Trend Chart, Model Table |
| C | TestTodayHourlyChart | DC.29–DC.34 | Hourly spend chart |
| D | TestCostByModelTable | DC.35–DC.42 | Cost by model table (cross_platform_usage backed) |
| E | TestCostByTeam | DC.43–DC.50 | Team pie chart and teams per-card |
| F | TestDeveloperCards | DC.51–DC.60 | Developer list, drill-down |
| G | TestCrossPlatformSource | DC.61–DC.72 | by_source breakdown, connections, budget |
| H | TestAdminAuditCards | DC.73–DC.82 | Admin overview, audit log |
| I | TestConsistencyAssertions | DC.83–DC.90 | Cross-endpoint total consistency, regression guards |

---

## Key Consistency Assertions (Section I)

These are the regression guards that would have caught the timeseries/events bug:

- Timeseries sum ≈ cross-platform/summary total (±1%) — the fixed bug
- analytics/today total ≤ analytics/timeseries today value
- analytics/models covers only OTel-sourced models
- events table powers kpis, cross_platform_usage powers timeseries — no overlap
- 5 integration sources appear in at least one response each

---

## Files

```
tests/suites/37_all_dashboard_cards/
  __init__.py
  conftest.py                   ← SeedContext, 6 integration ingest helpers
  test_all_dashboard_cards.py   ← 9 classes, ~90 test methods
```

---

## Integration Helper Design

```
ingest_otel(api_key, api_url, ...)         → direct OTLP POST
ingest_sdk(api_key, api_url, ...)          → node subprocess, vantage-js-sdk/dist/index.cjs
ingest_mcp(api_key, api_url, ...)          → JSON-RPC over stdio, vantage-mcp/dist/index.js
ingest_proxy_style(api_key, api_url, ...)  → POST /v1/events, sdk_language=local-proxy
ingest_direct(api_key, api_url, ...)       → POST /v1/events
```

Subprocesses have a 15s timeout. Failures are non-fatal (test skipped, not failed).

---

## TDD Cycle

1. Write test file (all assertions against expected SeedContext values)
2. Run — RED: seeded account is fresh, no data yet → assertions fail
3. Confirm each test fails for the right reason (no data, not wrong schema)
4. Implement conftest.py seed fixture
5. Run — GREEN: all assertions pass against seeded data
6. Refactor helpers if needed, keep green
