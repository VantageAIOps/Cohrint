# Account Hierarchy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `individual / team / organization` account types to the existing org model, introduce a proper `teams` table for org sub-teams, enforce per-type membership constraints, and expose team CRUD routes — without breaking any existing orgs or API keys.

**Architecture:** Three D1 migrations add `account_type` to `orgs`, a `teams` table, and a `team_id` FK on `org_members`. Auth middleware is extended to populate `accountType` and `teamId` in Hono context. A new `teams.ts` route file handles team CRUD. Signup and member-invite handlers enforce per-type constraints entirely in the application layer (D1/SQLite has no triggers).

**Tech Stack:** Cloudflare Workers (Hono v4), D1 SQLite, TypeScript strict, Wrangler CLI.

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `vantage-worker/migrations/0018_account_type.sql` | Create | Add `account_type` column to `orgs` |
| `vantage-worker/migrations/0019_teams_table.sql` | Create | New `teams` entity for org sub-teams |
| `vantage-worker/migrations/0020_member_team_fk.sql` | Create | Add `team_id` FK to `org_members` |
| `vantage-worker/src/types.ts` | Modify | Add `AccountType`, `teamId`, `accountType` to `Variables` |
| `vantage-worker/src/middleware/auth.ts` | Modify | Populate `accountType` + `teamId` in context |
| `vantage-worker/src/routes/auth.ts` | Modify | Enforce account-type constraints on signup + member invite |
| `vantage-worker/src/routes/teams.ts` | Create | CRUD: list/create/delete teams, list/invite team members |
| `vantage-worker/src/index.ts` | Modify | Mount `/v1/teams` router |

---

## Task 1: Migration — add `account_type` to `orgs`

**Files:**
- Create: `vantage-worker/migrations/0018_account_type.sql`

- [ ] **Step 1: Write the migration**

```sql
-- Migration 0018: Add account_type to orgs
-- Existing orgs default to 'organization' — no data migration needed.

ALTER TABLE orgs ADD COLUMN account_type TEXT NOT NULL DEFAULT 'organization'
  CHECK(account_type IN ('individual', 'team', 'organization'));
```

Save to `vantage-worker/migrations/0018_account_type.sql`.

- [ ] **Step 2: Apply locally**

```bash
cd vantage-worker
npx wrangler d1 execute vantage-events --local --file=migrations/0018_account_type.sql
```

Expected output: `✅ Applied migration` (no errors).

- [ ] **Step 3: Verify the column exists**

```bash
npx wrangler d1 execute vantage-events --local --command="PRAGMA table_info(orgs);"
```

Expected: a row with `name=account_type`, `type=TEXT`, `notnull=1`, `dflt_value='organization'`.

- [ ] **Step 4: Commit**

```bash
git add vantage-worker/migrations/0018_account_type.sql
git commit -m "feat: migration 0018 — add account_type to orgs"
```

---

## Task 2: Migration — `teams` table

**Files:**
- Create: `vantage-worker/migrations/0019_teams_table.sql`

- [ ] **Step 1: Write the migration**

```sql
-- Migration 0019: teams table for sub-teams within organization accounts

CREATE TABLE IF NOT EXISTS teams (
  id         TEXT NOT NULL,                              -- slug, e.g. "backend"
  org_id     TEXT NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
  name       TEXT NOT NULL,
  created_at INTEGER NOT NULL DEFAULT (unixepoch()),
  deleted_at INTEGER,                                    -- soft delete
  PRIMARY KEY (org_id, id)
);

CREATE INDEX IF NOT EXISTS idx_teams_org ON teams(org_id) WHERE deleted_at IS NULL;
```

Save to `vantage-worker/migrations/0019_teams_table.sql`.

- [ ] **Step 2: Apply locally**

```bash
npx wrangler d1 execute vantage-events --local --file=migrations/0019_teams_table.sql
```

Expected: no errors.

- [ ] **Step 3: Verify**

```bash
npx wrangler d1 execute vantage-events --local --command="SELECT name FROM sqlite_master WHERE type='table' AND name='teams';"
```

Expected: one row with `name=teams`.

- [ ] **Step 4: Commit**

```bash
git add vantage-worker/migrations/0019_teams_table.sql
git commit -m "feat: migration 0019 — teams table for org sub-teams"
```

---

## Task 3: Migration — `team_id` FK on `org_members`

**Files:**
- Create: `vantage-worker/migrations/0020_member_team_fk.sql`

- [ ] **Step 1: Write the migration**

```sql
-- Migration 0020: Add team_id FK to org_members
-- team_id is NULL for standalone-team-account members.
-- For organization accounts, team_id points to teams(org_id, id).
-- scope_team (free-text) is preserved for backward compat.

ALTER TABLE org_members ADD COLUMN team_id TEXT
  REFERENCES teams(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_members_team
  ON org_members(team_id) WHERE team_id IS NOT NULL;
```

Save to `vantage-worker/migrations/0020_member_team_fk.sql`.

- [ ] **Step 2: Apply locally**

```bash
npx wrangler d1 execute vantage-events --local --file=migrations/0020_member_team_fk.sql
```

Expected: no errors.

- [ ] **Step 3: Verify**

```bash
npx wrangler d1 execute vantage-events --local --command="PRAGMA table_info(org_members);"
```

Expected: a row with `name=team_id`, `type=TEXT`, `notnull=0`.

- [ ] **Step 4: Commit**

```bash
git add vantage-worker/migrations/0020_member_team_fk.sql
git commit -m "feat: migration 0020 — team_id FK on org_members"
```

---

## Task 4: Update `types.ts`

**Files:**
- Modify: `vantage-worker/src/types.ts`

- [ ] **Step 1: Add `AccountType` and extend `Variables`**

Open `vantage-worker/src/types.ts`. Replace the `Variables` type:

```typescript
export type AccountType = 'individual' | 'team' | 'organization';

export type OrgRole = 'owner' | 'superadmin' | 'ceo' | 'admin' | 'member' | 'viewer';

export type Variables = {
  orgId:       string;
  role:        OrgRole;
  accountType: AccountType;   // individual | team | organization
  scopeTeam:   string | null; // legacy free-text team scope
  teamId:      string | null; // canonical FK to teams table (org accounts only)
  memberId:    string | null;
  memberEmail: string | null;
};
```

- [ ] **Step 2: Typecheck**

```bash
cd vantage-worker && npm run typecheck
```

Expected: errors only in `auth.ts` middleware where `accountType` and `teamId` are not yet set. That's expected — fix in Task 5.

- [ ] **Step 3: Commit**

```bash
git add vantage-worker/src/types.ts
git commit -m "feat: add AccountType + teamId to Hono Variables"
```

---

## Task 5: Update auth middleware to populate `accountType` + `teamId`

**Files:**
- Modify: `vantage-worker/src/middleware/auth.ts`

- [ ] **Step 1: Update session cookie path**

In `authMiddleware`, after `c.set('memberEmail', memberEmail)` (the session cookie branch, around line 78), add:

```typescript
// Resolve accountType for session
const orgMeta = await c.env.DB.prepare(
  'SELECT account_type FROM orgs WHERE id = ?'
).bind(session.org_id).first<{ account_type: string }>();
c.set('accountType', (orgMeta?.account_type ?? 'organization') as import('../types').AccountType);

// Resolve teamId if member has one
let teamId: string | null = null;
if (session.member_id) {
  const tm = await c.env.DB.prepare(
    'SELECT team_id FROM org_members WHERE id = ?'
  ).bind(session.member_id).first<{ team_id: string | null }>();
  teamId = tm?.team_id ?? null;
}
c.set('teamId', teamId);
```

- [ ] **Step 2: Update owner key path**

In the `if (org)` branch (owner key match, around line 126), add after `c.set('memberEmail', null)`:

```typescript
c.set('accountType', (org.account_type ?? 'organization') as import('../types').AccountType);
c.set('teamId', null);
```

Update the `org` query to also fetch `account_type`:

```typescript
const org = await c.env.DB.prepare(
  'SELECT id, plan, account_type FROM orgs WHERE api_key_hash = ?'
).bind(hash).first<{ id: string; plan: string; account_type: string }>();
```

- [ ] **Step 3: Update member key path**

In the `else` branch (member key match), after `c.set('memberEmail', member.email ?? null)`:

```typescript
const orgMeta2 = await c.env.DB.prepare(
  'SELECT account_type FROM orgs WHERE id = ?'
).bind(member.org_id).first<{ account_type: string }>();
c.set('accountType', (orgMeta2?.account_type ?? 'organization') as import('../types').AccountType);
c.set('teamId', member.team_id ?? null);
```

Update the `member` query to also fetch `team_id`:

```typescript
const member = await c.env.DB.prepare(
  'SELECT id, org_id, role, scope_team, email, team_id FROM org_members WHERE api_key_hash = ?'
).bind(hash).first<{ id: string; org_id: string; role: string; scope_team: string | null; email: string | null; team_id: string | null }>();
```

- [ ] **Step 4: Typecheck**

```bash
cd vantage-worker && npm run typecheck
```

Expected: 0 errors.

- [ ] **Step 5: Commit**

```bash
git add vantage-worker/src/middleware/auth.ts
git commit -m "feat: populate accountType + teamId in auth middleware context"
```

---

## Task 6: Update signup + member-invite in `auth.ts`

**Files:**
- Modify: `vantage-worker/src/routes/auth.ts`

### Part A — Signup

- [ ] **Step 1: Accept `account_type` in signup body**

In `auth.post('/signup', ...)`, update the body type and add `account_type` parsing:

```typescript
let body: { email?: string; name?: string; org?: string; account_type?: string };
try { body = await c.req.json(); }
catch { return c.json({ error: 'Invalid JSON body' }, 400); }

const VALID_ACCOUNT_TYPES = ['individual', 'team', 'organization'] as const;
const rawAccountType = body.account_type ?? 'organization';
const accountType = VALID_ACCOUNT_TYPES.includes(rawAccountType as any)
  ? rawAccountType as 'individual' | 'team' | 'organization'
  : 'organization';
```

- [ ] **Step 2: Include `account_type` in the INSERT**

Replace the `INSERT INTO orgs` statement:

```typescript
await c.env.DB.prepare(`
  INSERT INTO orgs (id, api_key_hash, api_key_hint, name, email, plan, account_type, created_at)
  VALUES (?, ?, ?, ?, ?, 'free', ?, unixepoch())
`).bind(orgId, keyHash, keyHint, name || orgId, email, accountType).run();
```

- [ ] **Step 3: Include `account_type` in the signup response**

Add `account_type: accountType` to the response JSON:

```typescript
return c.json({
  ok:           true,
  api_key:      rawKey,
  org_id:       orgId,
  account_type: accountType,
  hint:         keyHint,
  dashboard:    `https://cohrint.com/app.html?api_key=${rawKey}&org=${orgId}`,
}, 201);
```

### Part B — Member invite constraints

- [ ] **Step 4: Enforce per-type constraints in `POST /v1/auth/members`**

At the top of the `auth.post('/members', ...)` handler, after `const orgId = c.get('orgId')`, add:

```typescript
// Reject member invites for individual accounts
const accountType = c.get('accountType');
if (accountType === 'individual') {
  return c.json({ error: 'Individual accounts cannot have team members.' }, 403);
}
```

- [ ] **Step 5: For `team` accounts, restrict assignable roles**

Still in `POST /v1/auth/members`, replace the `VALID_ROLES` array:

```typescript
// team accounts: only member/viewer (owner is implicit admin)
// organization accounts: superadmin/member/viewer
const VALID_ROLES = accountType === 'team'
  ? ['member', 'viewer']
  : ['viewer', 'member', 'superadmin', 'admin'];
```

- [ ] **Step 6: For `organization` accounts, require `team_id`**

After the `scopeTeam` line, add:

```typescript
const rawTeamId = (body as any).team_id?.trim() || null;
let teamId: string | null = null;
if (accountType === 'organization') {
  if (!rawTeamId) {
    return c.json({ error: 'organization accounts require a team_id when inviting members.' }, 400);
  }
  // Verify team exists and belongs to this org
  const team = await c.env.DB.prepare(
    'SELECT id FROM teams WHERE id = ? AND org_id = ? AND deleted_at IS NULL'
  ).bind(rawTeamId, orgId).first<{ id: string }>();
  if (!team) {
    return c.json({ error: `Team '${rawTeamId}' not found in this org.` }, 404);
  }
  teamId = rawTeamId;
}
```

Update the body type at the top of the handler:
```typescript
let body: { email?: string; name?: string; role?: string; scope_team?: string; team_id?: string };
```

- [ ] **Step 7: Include `team_id` in the member INSERT**

Replace the `INSERT INTO org_members` statement:

```typescript
await c.env.DB.prepare(`
  INSERT INTO org_members (id, org_id, email, name, role, api_key_hash, api_key_hint, scope_team, team_id, created_at)
  VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, unixepoch())
`).bind(memberId, orgId, email, name || null, role, keyHash, keyHint, scopeTeam, teamId).run();
```

- [ ] **Step 8: Typecheck**

```bash
cd vantage-worker && npm run typecheck
```

Expected: 0 errors.

- [ ] **Step 9: Commit**

```bash
git add vantage-worker/src/routes/auth.ts
git commit -m "feat: enforce account-type constraints on signup + member invite"
```

---

## Task 7: Create `teams.ts` route

**Files:**
- Create: `vantage-worker/src/routes/teams.ts`

- [ ] **Step 1: Write the route file**

Create `vantage-worker/src/routes/teams.ts`:

```typescript
import { Hono } from 'hono';
import { Bindings, Variables } from '../types';
import { authMiddleware, adminOnly } from '../middleware/auth';
import { logAudit } from '../lib/audit';

const teams = new Hono<{ Bindings: Bindings; Variables: Variables }>();

function randomHex(bytes = 8): string {
  const arr = new Uint8Array(bytes);
  crypto.getRandomValues(arr);
  return Array.from(arr).map(b => b.toString(16).padStart(2, '0')).join('');
}

function toSlug(input: string): string {
  return input
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 32) || 'team';
}

// All team routes require auth
teams.use('*', authMiddleware);

// ── GET /v1/teams — list teams in this org ────────────────────────────────────
teams.get('/', async (c) => {
  const orgId       = c.get('orgId');
  const accountType = c.get('accountType');

  if (accountType !== 'organization') {
    return c.json({ error: 'Teams only exist on organization accounts.' }, 403);
  }

  const { results } = await c.env.DB.prepare(`
    SELECT id, name, datetime(created_at, 'unixepoch') AS created_at
    FROM teams
    WHERE org_id = ? AND deleted_at IS NULL
    ORDER BY created_at ASC
  `).bind(orgId).all();

  return c.json({ teams: results });
});

// ── POST /v1/teams — create a team (admin+ only) ──────────────────────────────
teams.post('/', adminOnly, async (c) => {
  const orgId       = c.get('orgId');
  const accountType = c.get('accountType');

  if (accountType !== 'organization') {
    return c.json({ error: 'Teams can only be created on organization accounts.' }, 403);
  }

  let body: { name?: string; id?: string };
  try { body = await c.req.json(); }
  catch { return c.json({ error: 'Invalid JSON body' }, 400); }

  const name = (body.name ?? '').trim();
  if (!name) return c.json({ error: 'name is required' }, 400);

  let teamId = body.id ? toSlug(body.id) : toSlug(name);

  // Ensure uniqueness within org
  const existing = await c.env.DB.prepare(
    'SELECT id FROM teams WHERE org_id = ? AND id = ? AND deleted_at IS NULL'
  ).bind(orgId, teamId).first();
  if (existing) teamId = `${teamId}-${randomHex(3)}`;

  await c.env.DB.prepare(`
    INSERT INTO teams (id, org_id, name, created_at)
    VALUES (?, ?, ?, unixepoch())
  `).bind(teamId, orgId, name).run();

  logAudit(c, {
    event_type:    'admin_action',
    event_name:    'admin_action.team_created',
    resource_type: 'team',
    resource_id:   teamId,
    metadata:      { name },
  });

  return c.json({ ok: true, team_id: teamId, name }, 201);
});

// ── DELETE /v1/teams/:id — soft-delete a team (admin+ only) ──────────────────
teams.delete('/:id', adminOnly, async (c) => {
  const orgId  = c.get('orgId');
  const teamId = c.req.param('id');

  const team = await c.env.DB.prepare(
    'SELECT id, name FROM teams WHERE org_id = ? AND id = ? AND deleted_at IS NULL'
  ).bind(orgId, teamId).first<{ id: string; name: string }>();

  if (!team) return c.json({ error: 'Team not found' }, 404);

  await c.env.DB.prepare(
    'UPDATE teams SET deleted_at = unixepoch() WHERE org_id = ? AND id = ?'
  ).bind(orgId, teamId).run();

  logAudit(c, {
    event_type:    'admin_action',
    event_name:    'admin_action.team_deleted',
    resource_type: 'team',
    resource_id:   teamId,
    metadata:      { name: team.name },
  });

  return c.json({ ok: true });
});

// ── GET /v1/teams/:id/members — list members of a team ───────────────────────
teams.get('/:id/members', async (c) => {
  const orgId  = c.get('orgId');
  const teamId = c.req.param('id');

  const team = await c.env.DB.prepare(
    'SELECT id FROM teams WHERE org_id = ? AND id = ? AND deleted_at IS NULL'
  ).bind(orgId, teamId).first();
  if (!team) return c.json({ error: 'Team not found' }, 404);

  const { results } = await c.env.DB.prepare(`
    SELECT id, email, name, role, api_key_hint,
           datetime(created_at, 'unixepoch') AS created_at
    FROM org_members
    WHERE org_id = ? AND team_id = ?
    ORDER BY created_at ASC
  `).bind(orgId, teamId).all();

  return c.json({ team_id: teamId, members: results });
});

export { teams };
```

- [ ] **Step 2: Typecheck**

```bash
cd vantage-worker && npm run typecheck
```

Expected: 0 errors.

- [ ] **Step 3: Commit**

```bash
git add vantage-worker/src/routes/teams.ts
git commit -m "feat: teams route — list/create/delete teams and list team members"
```

---

## Task 8: Mount teams router in `index.ts`

**Files:**
- Modify: `vantage-worker/src/index.ts`

- [ ] **Step 1: Add import**

After the `import { executive }` line, add:

```typescript
import { teams } from './routes/teams';
```

- [ ] **Step 2: Mount the route**

After `app.route('/v1/analytics/executive', executive);`, add:

```typescript
app.route('/v1/teams', teams);
```

- [ ] **Step 3: Add to the JSDoc endpoint list at the top of `index.ts`**

In the JSDoc comment block, add these lines after the `/v1/analytics/executive` entry:

```
 *   GET  /v1/teams                      (admin — list org teams)
 *   POST /v1/teams                      (admin — create team)
 *   DELETE /v1/teams/:id                (admin — soft-delete team)
 *   GET  /v1/teams/:id/members          (admin — list team members)
```

- [ ] **Step 4: Typecheck**

```bash
cd vantage-worker && npm run typecheck
```

Expected: 0 errors.

- [ ] **Step 5: Commit**

```bash
git add vantage-worker/src/index.ts
git commit -m "feat: mount /v1/teams router"
```

---

## Task 9: Apply migrations to production D1

- [ ] **Step 1: Apply all three migrations to remote D1**

```bash
cd vantage-worker
npx wrangler d1 execute vantage-events --remote --file=migrations/0018_account_type.sql
npx wrangler d1 execute vantage-events --remote --file=migrations/0019_teams_table.sql
npx wrangler d1 execute vantage-events --remote --file=migrations/0020_member_team_fk.sql
```

Expected: each command prints `✅ Applied migration` with no errors.

- [ ] **Step 2: Verify production schema**

```bash
npx wrangler d1 execute vantage-events --remote --command="PRAGMA table_info(orgs);" 
npx wrangler d1 execute vantage-events --remote --command="SELECT name FROM sqlite_master WHERE type='table' AND name='teams';"
npx wrangler d1 execute vantage-events --remote --command="PRAGMA table_info(org_members);"
```

Expected:
- `orgs` has `account_type` column
- `teams` table exists
- `org_members` has `team_id` column

- [ ] **Step 3: Deploy the worker**

```bash
npx wrangler deploy
```

Expected: `✅ Deployed` with the new worker version.

---

## Task 10: Smoke-test the full flow

- [ ] **Step 1: Test individual signup**

```bash
curl -s -X POST https://api.cohrint.com/v1/auth/signup \
  -H 'Content-Type: application/json' \
  -d '{"email":"solo@example.com","name":"Solo User","account_type":"individual"}' | jq .
```

Expected: `{ "ok": true, "account_type": "individual", "api_key": "crt_..." }`

- [ ] **Step 2: Verify individual can't invite members**

```bash
# Use the api_key from Step 1
curl -s -X POST https://api.cohrint.com/v1/auth/members \
  -H 'Authorization: Bearer <api_key_from_step_1>' \
  -H 'Content-Type: application/json' \
  -d '{"email":"other@example.com"}' | jq .
```

Expected: `{ "error": "Individual accounts cannot have team members." }` with HTTP 403.

- [ ] **Step 3: Test organization signup + team creation**

```bash
# Signup as org
curl -s -X POST https://api.cohrint.com/v1/auth/signup \
  -H 'Content-Type: application/json' \
  -d '{"email":"ceo@acme.com","name":"Acme Corp","account_type":"organization"}' | jq .

# Create a team (use api_key from above)
curl -s -X POST https://api.cohrint.com/v1/teams \
  -H 'Authorization: Bearer <org_api_key>' \
  -H 'Content-Type: application/json' \
  -d '{"name":"Backend Team"}' | jq .
```

Expected: `{ "ok": true, "team_id": "backend-team", "name": "Backend Team" }`

- [ ] **Step 4: Invite a member to the team**

```bash
curl -s -X POST https://api.cohrint.com/v1/auth/members \
  -H 'Authorization: Bearer <org_api_key>' \
  -H 'Content-Type: application/json' \
  -d '{"email":"dev@acme.com","role":"member","team_id":"backend-team"}' | jq .
```

Expected: `{ "ok": true, "member_id": "...", "api_key": "crt_..." }`

- [ ] **Step 5: Verify org can't invite without team_id**

```bash
curl -s -X POST https://api.cohrint.com/v1/auth/members \
  -H 'Authorization: Bearer <org_api_key>' \
  -H 'Content-Type: application/json' \
  -d '{"email":"other@acme.com","role":"member"}' | jq .
```

Expected: `{ "error": "organization accounts require a team_id when inviting members." }` with HTTP 400.

- [ ] **Step 6: Commit smoke-test results (no code changes — just note in git log)**

```bash
git commit --allow-empty -m "chore: account hierarchy smoke-tested on production"
```
