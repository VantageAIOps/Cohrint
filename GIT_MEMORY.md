# VantageAI Git Memory

Fast reference for Claude Code sessions. Auto-refreshed by `/clean`. Replaces `git log` / `git blame` for most context lookups.

---

## Current Branch
`fix/cli-ux-and-dynamic-versioning` → PR #29 (OPEN)

---

## Open PRs

| # | Title | Branch |
|---|-------|--------|
| 29 | feat(cli): live tool rendering + 9 UX/stability fixes + dynamic versioning | fix/cli-ux-and-dynamic-versioning |

---

## Latest 15 Commits

```
6245566  feat(cli): render Claude tool use live like Claude terminal
96afe9f  fix(cli): fix 6 review issues — TS error, sessionId, timeouts, sleep, pkg-lock, structured-data
2ee4719  fix(cli): fix crash vectors, permission prompts, context loss, and update check
d1df291  fix(cli): fix multi-turn, optimizer code safety, anomaly detection, and session tracking
88a8472  fix(cli): fix 15 bugs across session-mode, tracker, runner, index, optimizer
9dfa0cb  fix(cli): fix SIGTERM race, anomaly avg, token count, and stream end listener
7599574  fix(cli): fix multi-turn conversation context loss after 1-2 prompts
59bf7cf  fix(versions): eliminate all hardcoded version strings across 5 packages
1600a51  fix(cli): show tokens/cost saved in session summary; fix session mode savings
d9c4328  fix(cli): fix session mode REPL prompt appearing mid-response
16a2c19  fix(cli): suppress stdin warning when running interactively
d3a4caf  Merge pull request #28 from Amanjain98/fix/zero-bugs-sweep
45fd91c  chore(release): bump patch versions for bug-fix release
dfce416  fix(otel-realtime): fix all critical + high OTel pipeline and live feed gaps
0757335  fix(sweep5): 4 bugs from cross-component audit
```

---

## Recent Merged PRs

| PR | Branch | Summary |
|----|--------|---------|
| #28 | fix/zero-bugs-sweep | Bug sweep across all packages; patch version bumps |
| #27 | fix/dashboard-token-usage-cache-savings | Dashboard: token usage, cache, savings display |
| #26 | feat/update-notifier-and-deprecation | Update notifier + deprecation warnings |
| #25 | feat/claude-code-auto-tracking | Auto-tracking for Claude Code CLI sessions |
| #24 | feat/enterprise-soc2-audit-log | SOC2 audit log — `audit_log` table + endpoints |

---

## Package Versions

| Package | npm name | Version | Notes |
|---------|----------|---------|-------|
| vantage-cli | vantageai-cli | **2.2.3** | CLI wrapper — pending publish on PR merge |
| vantage-mcp | vantageaiops-mcp | 1.1.1 | MCP server (cost tools + optimizer) |
| vantage-js-sdk | vantageaiops | 1.0.1 | JS/TS SDK, zero deps |
| vantage-local-proxy | vantageai-local-proxy | 1.0.2 | Local HTTP proxy + file scanners |
| vantage-worker | — | 1.0.0 | Cloudflare Worker API (not on npm) |

Publish is automatic on merge to main via `publish-packages.yml` — compares local vs registry version.

---

## Key Changes in PR #29 (by file)

| File | Change |
|------|--------|
| `vantage-cli/src/runner.ts` | `ClaudeStreamRenderer` — renders `⏺ Tool(input)` + `⎿ result` live |
| `vantage-cli/src/session-mode.ts` | sessionId capture from JSON stream; INITIAL_TIMEOUT 5s→30s |
| `vantage-cli/src/index.ts` | Removed 2s flush sleep; Bug 3 checks in `looksLikeStructuredData` |
| `vantage-cli/src/tracker.ts` | Removed SIGTERM/SIGINT handlers; relies on `beforeExit` |
| `vantage-cli/src/anomaly.ts` | Fixed average cost (exclude current prompt) |
| `vantage-cli/src/optimizer.ts` | Safety fix for empty/null input |
| All 5 packages | `gen-version` prebuild hook → `src/_version.ts` from `package.json` |

---

## Important Files

| File | Purpose |
|------|---------|
| `vantage-cli/src/runner.ts` | One-shot + buffered agent execution |
| `vantage-cli/src/session-mode.ts` | Interactive session REPL |
| `vantage-cli/src/index.ts` | Entry point: mode detection (one-shot/pipe/REPL) |
| `vantage-cli/src/tracker.ts` | Event → API telemetry flush |
| `vantage-cli/src/ui.ts` | Terminal UI helpers (Spinner, colors) |
| `vantage-worker/src/` | Cloudflare Worker routes + D1 queries |
| `tests/suites/` | pytest suites (17–21, 32–33 active; 34 needed for PR #29) |
| `GIT_MEMORY.md` | This file — refreshed by `/clean` |

---

## Outstanding Items

- [ ] Tests in `tests/suites/34_cli_session/` for PR #29 (sessionId capture, looksLikeStructuredData, flush exit time)
- [ ] Merge PR #29 → triggers auto-publish of `vantageai-cli@2.2.3`
- [ ] Update `GIT_MEMORY.md` after merge (run `/clean`)
