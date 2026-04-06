# VantageAI Git Memory

Fast reference for Claude Code sessions. Auto-refreshed by `/clean`. Replaces `git log` / `git blame` for most context lookups.

---

## Current Branch
`fix/cli-ux-rendering-cache-tests` → PR #30

---

## Open PRs

| PR | Branch | Title |
|----|--------|-------|
| #30 | fix/cli-ux-rendering-cache-tests | fix(cli+ci): live rendering, permission prompts, cache fixes, test barricades + suites 34+35 |

---

## Latest 15 Commits

```
cc45916  fix(tests+ci): fix 7 failing cli-unit-tests in PR gate
9848171  feat(ci): auto-include all new suites in barricades via exclusion-based default
8de03a9  refactor(tests): migrate all test harnesses from .mjs to tsx .ts
36cc5c6  fix(ci): add ci-test.yml PR barricade, fix YAML indentation, delete stale test-renderer.mjs
9b7ce92  refactor(cli+ci): TS harnesses import real production code; add test barricade; trim 3 redundant workflows
7ce362b  fix(cli): normalize agent name before condition evaluation in getRecommendations
0c255a5  fix(cli): fix 3 review issues — failure state leak, session savings bleed, sessionId regex
bb492d5  tests(cli): add suite 34 — stream renderer, cache layer, structured data guards (35 checks)
7171ec9  fix(cli): restore --verbose flag required by stream-json with --print
fad05e1  fix(cli): fix 3 cache/savings layer bugs — tracker queue, session accumulation, metrics agent
b4b267b  fix(cli): fix live rendering and permission prompts for claude agent
1bbe782  chore: refresh GIT_MEMORY.md with latest 15 commits
f3feba4  fix(ci): fix YAML syntax error in ci-version.yml (multiline bash string)
f647f3a  chore(release): bump vantage-cli to 2.2.3; refresh GIT_MEMORY.md
6245566  feat(cli): render Claude tool use live like Claude terminal
```

---

## Recent Merged PRs

| PR | Branch | Summary |
|----|--------|---------|
| #28 | fix/zero-bugs-sweep | Bug sweep across all packages; patch version bumps |
| #27 | fix/dashboard-token-usage-cache-savings | Dashboard: token usage, cache, savings display |
| #26 | feat/update-notifier-and-deprecation | Update notifier + deprecation warnings |
| #25 | feat/claude-code-auto-tracking | Auto-tracking for Claude Code CLI sessions |
| #24 | feat/enterprise-soc2-audit-log | SOC2 audit log — audit_log table + endpoints |

---

## Package Versions

| Package | npm name | Version |
|---------|----------|---------|
| vantage-cli | vantageai-cli | **2.2.3** |
| vantage-mcp | vantageaiops-mcp | 1.1.1 |
| vantage-js-sdk | vantageaiops | 1.0.1 |

---

## Outstanding Items (PR #30)

- [ ] Fix PC.23/PC.24 assertions: change `"supportsContinue" in content` → `"supportsContinue: true" in content`; rename test methods to drop `_no_` prefix
- [ ] Fix `optimizer.ts` JSDoc: still says "5-layer compression engine" (now 6 layers, Layer 0 = deduplicateSentences)
- [ ] Fix `ci-test.yml` GitHub API test suite workflow (new session request)
- [ ] Merge PR #30 once CI passes
