# Account Hierarchy Design

**Date:** 2026-04-15  
**Status:** Draft — pending user approval  
**Scope:** Multi-tier account model (individual / team / organization) with role-based access, proper team entities, and D1-native enforcement.

---

## 1. Problem

The current system has one account type (`orgs`) used for everything. There is no distinction between a solo user, a small team, and an enterprise with multiple sub-teams. The `scope_team` field on `org_members` is a free-text string — there is no real `teams` entity. Roles `ceo` and `superadmin` exist in the DB but are not tied to any structural constraint. The goal is to model three distinct account tiers while reusing the existing role + API key infrastructure.

---

## 2. Account Tiers

| Tier | Description | Members allowed |
|------|-------------|----------------|
| `individual` | Solo user. One person, one key. | None (owner only) |
| `team` | Small group. 1 admin + N members. | `member`, `viewer`; exactly 1 `admin` |
| `organization` | Enterprise. CEO + multiple named teams, each with super_admins + members. | `superadmin`, `member`, `viewer` per team; exactly 1 `owner` (CEO) |

No `developer` account type. No separate token prefixes per role — role is stored in the `org_members.role` column and derived at auth time.

---

## 3. Role Mapping (no changes to existing rank order)

```
owner (5) — org CEO or individual account owner
superadmin (4) — team lead within an organization
ceo (3) — DEPRECATED: was an alias, maps to owner going forward
admin (2) — team admin in a standalone team account
member (1) — standard user
viewer (0) — read-only
```

`ceo` role remains valid for backward compat but `owner` is canonical for top-of-org. New signups use `owner` only.

---

## 4. Schema Changes

### Migration 0018 — Add `account_type` to `orgs`

```sql
ALTER TABLE orgs ADD COLUMN account_type TEXT NOT NULL DEFAULT 'organization'
  CHECK(account_type IN ('individual', 'team', 'organization'));
```

All existing orgs default to `'organization'` — no data migration needed.

### Migration 0019 — Add `teams` table

```sql
CREATE TABLE IF NOT EXISTS teams (
  id         TEXT PRIMARY KEY,          -- slug: e.g. "backend", "ml-team"
  org_id     TEXT NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
  name       TEXT NOT NULL,
  created_at INTEGER NOT NULL DEFAULT (unixepoch()),
  deleted_at INTEGER,                   -- soft delete
  UNIQUE(org_id, id)
);
CREATE INDEX IF NOT EXISTS idx_teams_org ON teams(org_id);
```

### Migration 0020 — Add `team_id` FK to `org_members`

```sql
ALTER TABLE org_members ADD COLUMN team_id TEXT REFERENCES teams(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_members_team ON org_members(team_id) WHERE team_id IS NOT NULL;
```

`team_id` is NULL for standalone team accounts; set for org members assigned to a specific team. `scope_team` (the free-text string) is kept for backward compat but `team_id` is authoritative going forward.

---

## 5. Auth & Middleware Changes

### Signup (`POST /v1/auth/signup`)

Accept `account_type: 'individual' | 'team' | 'organization'` in the request body. Default: `'organization'` for backward compat.

- `individual`: set `account_type='individual'`, no member invite allowed
- `team`: set `account_type='team'`, owner gets `role='admin'` semantically (still stored as `owner` in `orgs`)
- `organization`: set `account_type='organization'`, owner is CEO

### Member invite (`POST /v1/auth/members`)

Enforce per-type constraints:

| Account type | Allowed member roles |
|---|---|
| `individual` | ❌ reject all invites |
| `team` | `member`, `viewer` only (owner/admin is implicit) |
| `organization` | `superadmin`, `member`, `viewer` + require `team_id` |

### Auth context

Add `accountType` and `teamId` to Hono context variables so route handlers can read them without extra DB queries.

```typescript
Variables: {
  orgId: string
  role: OrgRole
  accountType: 'individual' | 'team' | 'organization'
  teamId: string | null      // which team within an org this member belongs to
  scopeTeam: string | null   // legacy, preserved
  memberId: string | null
  memberEmail: string | null
}
```

---

## 6. New Routes

### `GET /v1/teams` — list teams in an org (admin+ only)
### `POST /v1/teams` — create a team (owner/superadmin only; org accounts only)
### `DELETE /v1/teams/:id` — soft-delete a team (owner only)
### `GET /v1/teams/:id/members` — list members of a specific team
### `POST /v1/teams/:id/members` — invite member to a specific team

These live in a new `src/routes/teams.ts` file.

---

## 7. Data Integrity Constraints (application layer)

SQLite D1 lacks deferrable constraints and triggers, so enforcement is in the application:

| Rule | Where enforced |
|---|---|
| `individual` has no `org_members` rows | Checked in `POST /v1/auth/members` |
| `team` has ≤ 1 `admin` (the owner is implicit) | Checked on invite + role update |
| `organization` members must have a `team_id` | Validated on invite |
| Soft-deleting a team nulls `team_id` on members (via FK `ON DELETE SET NULL`) | DB constraint |
| Cannot demote/remove peer or higher role | Already enforced in existing delete/patch handlers |

---

## 8. Backward Compatibility

- All existing orgs keep `account_type='organization'` — zero breakage
- `scope_team` string field kept; `team_id` added as the canonical FK
- Token format (`crt_<orgId>_<hex>`) unchanged — no separate token types
- Existing role values unchanged — no data migration on `org_members`
- `ceo` role accepted in CHECK constraint but not assigned to new members

---

## 9. What is NOT changing

- D1 database (no migration to Turso/Neon for now — D1 is sufficient until we hit 25M+ event rows per org)
- Token format or prefix
- Existing analytics/events routes
- `sessions` table structure
- Rate limiting logic

---

## 10. File Changelist

| File | Change |
|---|---|
| `vantage-worker/migrations/0018_account_type.sql` | New |
| `vantage-worker/migrations/0019_teams_table.sql` | New |
| `vantage-worker/migrations/0020_member_team_fk.sql` | New |
| `vantage-worker/src/types.ts` | Add `accountType`, `teamId` to Variables |
| `vantage-worker/src/middleware/auth.ts` | Populate `accountType` + `teamId` in context |
| `vantage-worker/src/routes/auth.ts` | Enforce per-type constraints on signup + member invite |
| `vantage-worker/src/routes/teams.ts` | New — CRUD for teams |
| `vantage-worker/src/index.ts` | Mount `/v1/teams` router |
