# GIT_MEMORY — VantageAI

_Last updated: 2026-04-08_

## Current Branch
`feat/session-centric-integration`

## Open PRs
| # | Title | Branch |
|---|-------|--------|
| #41 | feat: session-centric integration (MCP + local-proxy + OTel) | feat/session-centric-integration |

## Latest 15 Commits
```
5fb4f1d test: add suites 34 (otel sessions) and 35 (local-proxy resume)
3780bc7 feat(worker): add otel_sessions rollup table and GET /v1/sessions endpoint
0ab85b9 feat(local-proxy): add --resume and --session-id flags for session continuity
ca61eeb feat(mcp): add session_id to track_llm_call for session correlation
6337a70 docs: add implementation plan for backend session-centric integration
66c0939 docs: add backend session-centric audit spec (MCP + local-proxy + OTel)
3f66796 fix(rate_limiter): add fcntl file lock for true cross-process safety
4651ac9 test(local-proxy): add 13 tests for SessionStore covering save/load/listAll
0e20530 test(api_client): fix retry tests to mock messages.stream not messages.create
c3b3896 feat: add claude-intelligence plug-and-play package
c3edb04 feat(vantage-agent): Phase 6 — token-bucket rate limiting + exponential backoff
c2b066b feat(local-proxy): add session persistence to ~/.vantage/sessions/
6f9cfa2 chore: remove vantage-cli dir + rewrite remaining TS-dependent test suites
7eaeb95 feat(vantage-agent): add non-blocking OTel metrics/logs exporter
8474462 fix(frontend): update docs CLI references + add mobile responsive breakpoints
```

## Recent Merged PRs
| PR | Description |
|----|-------------|
| #39 | fix(audit-log): align event_name values with test expectations |
| #38 | feat(vantage-agent): Python CLI agent (phases 1-5) |
| #37 | chore: cli-dead-code-cleanup — remove vantage-cli TS |
| #36 | feat(vantage-agent): earlier Python agent work |

## Package Versions
| Package | Version | Notes |
|---------|---------|-------|
| `vantageaiops-mcp` | 1.1.1 | Added session_id to track_llm_call (PR #41) |
| `vantageai-local-proxy` | 1.0.2 | Added --resume/--session-id flags (PR #41) |
| `vantage-worker` | 1.0.0 | Added otel_sessions table + GET /v1/sessions (PR #41) |
| `vantageai-agent` (Python) | 0.1.0 | Full session model, rate limiting, OTel exporter |

## Key Files & Purposes
- `vantage-worker/src/routes/otel.ts` — OTel ingestion + session upsert (new in PR #41)
- `vantage-worker/src/routes/sessions.ts` — GET /v1/sessions endpoint (new in PR #41)
- `vantage-worker/migrations/0006_otel_sessions.sql` — must apply to prod after merge
- `vantage-local-proxy/src/session-store.ts` — SessionStore with loadSync
- `vantage-local-proxy/src/proxy-server.ts` — StatsQueue with resume support
- `vantage-local-proxy/src/cli.ts` — --resume, --session-id flags
- `vantage-mcp/src/index.ts` — MCP tools server
- `vantage-agent/` — Python CLI agent (vantageai-agent)
- `vantage-final-v4/` — Static frontend (docs.html JS bug + CLI refs fixed today)
- `tests/suites/` — pytest suites 17-21, 32-35
- `docs/superpowers/specs/` — Architecture specs
- `docs/superpowers/plans/` — Implementation plans

## Outstanding Items (from TODO.md)
- [ ] GitHub CI test workflow — still failing
- [ ] GitHub access for Akshay Thite
- [ ] 5 specialist agents (PM, Team Lead, Dev, CI/CD, Testing)
- [ ] Business: market comparison, sales channels, company registration
- [ ] claude-intelligence sub-tasks — PARKED
- [x] Website docs page — JS syntax fix + CLI refs updated
- [x] Backend-architecture review — PR #41 open
- [x] CLI implementation — vantage-agent Python complete
- [x] Website mobile — responsive fixes applied
- [x] Dead code cleanup — vantage-cli TS removed

## Post-Merge Action Required (PR #41)
```bash
npx wrangler d1 execute vantageai-db --remote --file=migrations/0006_otel_sessions.sql
# Then verify:
python -m pytest tests/suites/34_otel_sessions/ -v
```
