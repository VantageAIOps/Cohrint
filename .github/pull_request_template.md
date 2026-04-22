## What changed

<!-- One sentence. What does this PR do? -->

## Why

<!-- Link to issue, spec section, or customer request that motivated this. -->

## Type

- [ ] `feat` — new feature
- [ ] `fix` — bug fix
- [ ] `chore` — dependency, config, tooling
- [ ] `docs` — documentation only
- [ ] `refactor` — no behaviour change
- [ ] `test` — tests only

## Checklist

- [ ] TypeScript check passes (`cd cohrint-worker && npm run typecheck`)
- [ ] Tests added or updated in `tests/suites/`
- [ ] No secrets or API keys in committed files
- [ ] No fake/demo data — real API data or honest empty states only
- [ ] SQLite date bindings are correct (INTEGER unixepoch vs TEXT per table)
- [ ] DB migrations are backwards-compatible (no DROP, no NOT NULL without default)

## Test evidence

<!-- Paste CI link, curl output, or screenshot. PRs without evidence may be blocked. -->

## Migrations

- [ ] No DB changes
- [ ] Migration file added at `cohrint-worker/migrations/`
- [ ] Migration tested on staging before merge to production
