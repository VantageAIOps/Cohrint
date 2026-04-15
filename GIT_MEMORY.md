# GIT_MEMORY — Cohrint / VantageAI

_Last updated: 2026-04-15_

## Current Branch
`main`

## Open PRs
None

## Latest 15 Commits

| Hash | Message |
|------|---------|
| `ba1358a` | fix: deferred security issues — __Host- cookie prefix, IP-bound recovery token, scope_team validation, X-Forwarded-For fallback removal, cookie parser = safety, session audit log noise |
| `c300aec` | fix: security audit — C1 broken FK, C2 PATCH role escalation, C3 logout SameSite, H1 adminOnly on team members, H2 N+1 member query, H3 api_key in dashboard URL, L1 teams updated_at |
| `6cafb6b` | feat: mount /v1/teams router |
| `043a7f3` | feat: teams route — list/create/delete teams and list team members |
| `c95375e` | feat: enforce account-type constraints on signup + member invite |
| `b462c3d` | feat: populate accountType + teamId in auth middleware context |
| `0b8a5fe` | feat: add AccountType + teamId to Hono Variables |
| `977bde6` | feat: migration 0020 — team_id FK on org_members |
| `95fb503` | feat: migration 0019 — teams table for org sub-teams |
| `64fbe5a` | feat: migration 0018 — add account_type to orgs |
| `36d2725` | feat(rbac): scope analytics and cross-platform data to own records for member/viewer roles |
| `a78b1d8` | feat(rbac): superadmin budget control center |
| `278d9d7` | feat(rbac): role-based post-login routing + CEO dashboard isolation |
| `479c651` | fix(migration): add missing last_used_at column to 0017 org_members recreation |
| `02b707c` | fix(worker): replace dynamic imports of hasRole with static import |

## Recent Merged PRs

| Hash | Message |
|------|---------|
| `16e0bc3` | Merge PR #61 — chore/rebrand-cohrint |
| `995b312` | Merge feat/enterprise-rbac-multiuser into chore/rebrand-cohrint |
| `dc72e70` | Merge PR #60 — feat/enterprise-rbac-multiuser |
| `294d956` | Merge PR #59 — fix/landing-page-positioning |
| `f03f6d8` | Merge PR #58 — fix/landing-page-positioning |

## Package Versions

| Package | Version |
|---------|---------|
| `vantage-worker` | 1.0.0 |

## What Was Done This Session

### Account Hierarchy (individual / team / organization)
- **3 D1 migrations** applied to production (`vantage-events`):
  - `0018` — `account_type TEXT` on `orgs` (default `'organization'`, existing orgs unaffected)
  - `0019` — `teams` table with composite PK `(org_id, id)`, soft delete, `updated_at`
  - `0020` — `team_id TEXT` on `org_members` (no FK — composite PK not referenceable in SQLite; app-layer enforced)
- **New route**: `src/routes/teams.ts` — `GET/POST /v1/teams`, `DELETE /v1/teams/:id`, `GET /v1/teams/:id/members` (all adminOnly)
- **Auth middleware**: populates `accountType` + `teamId` in Hono context; collapsed double member query into single SELECT
- **Signup**: accepts `account_type` param, stored + returned in response
- **Member invite**: individual=blocked; team=member/viewer only; org=requires `team_id` validated against `teams`
- **PATCH /members/:id**: enforces `accountType` role restrictions

### Security Fixes
- `__Host-` cookie prefix in production (no `Domain=`, origin-bound); logout clears both new and legacy names
- Recovery token IP-bound (stored at generation, validated + consumed on mismatch at redeem)
- `scope_team` validated: max 64 chars, `[a-z0-9_-]` only
- `X-Forwarded-For` fallback removed from all rate-limit IP lookups (`CF-Connecting-IP` only)
- Cookie parser uses `indexOf('=')` — safe for base64 values
- Session auth: `auth.login` audit skipped for `/v1/audit-log` reads (matches API key path)
- Worker deployed: version `fc137c81` live at `api.cohrint.com`

## Outstanding Items
- **Rotate `CLOUDFLARE_API_TOKEN`** — token was shared in chat; go to dash.cloudflare.com/profile/api-tokens
- Smoke-test live endpoints: individual/team/org signup, team CRUD, member invite with `team_id`
- Write test suite in `tests/suites/` for account hierarchy routes (none exist yet)
- `toSlug()` inconsistency between `auth.ts` and `teams.ts` (cosmetic)
- `api_key_hint` could be restricted to owner/superadmin on member list (low priority)
