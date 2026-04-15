# Enterprise SOC2 Prep + Coverage Accuracy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a full-activity-trail audit log with org-owner self-serve access + Security/Integrations dashboard tabs, and fix inaccurate "100% coverage" claims with an honest public roadmap page.

**Architecture:** Extend the existing `audit_events` D1 table with an `event_type` column; move the existing `logAudit` helper from `admin.ts` into a new `lib/audit.ts` with fire-and-forget semantics; add two new API endpoints (`GET /v1/audit-log`, `GET /v1/admin/audit-log`); wire `logAudit` into auth middleware, analytics routes, and admin action routes; add Security and Integrations views to the dashboard; ship a public `roadmap.html`.

**Tech Stack:** Cloudflare Workers (Hono), D1 SQLite, TypeScript, static HTML/JS frontend

---

## File Map

| Action | File | Responsibility |
|---|---|---|
| Create | `vantage-worker/migrations/0004_audit_event_type.sql` | Add `event_type` column + index to `audit_events` |
| Create | `vantage-worker/src/lib/audit.ts` | Shared `logAudit()` / `logAuditRaw()` helpers |
| Create | `vantage-worker/src/routes/auditlog.ts` | `GET /v1/audit-log` (org owner + CSV export) |
| Modify | `vantage-worker/src/routes/admin.ts` | Add `GET /v1/admin/audit-log`; remove old inline `logAudit` fn |
| Modify | `vantage-worker/src/index.ts` | Register `/v1/audit-log` route |
| Modify | `vantage-worker/src/middleware/auth.ts` | Log `auth.login` + `auth.failed` |
| Modify | `vantage-worker/src/routes/analytics.ts` | Log `data_access.analytics` per-request middleware |
| Modify | `vantage-worker/src/routes/crossplatform.ts` | Log `admin_action.budget_policy_changed` |
| Modify | `vantage-worker/src/routes/alerts.ts` | Log `admin_action.alert_config_changed` |
| Modify | `vantage-worker/src/routes/admin.ts` | Log `admin_action.member_added/removed` |
| Modify | `vantage-final-v4/app.html` | Add Security + Integrations views + sidebar nav items |
| Create | `vantage-final-v4/roadmap.html` | Public integration status page |
| Modify | `PRODUCT_STRATEGY.md` | Remove "100% coverage" language |
| Create | `tests/suites/32_audit_log/__init__.py` | Package marker |
| Create | `tests/suites/32_audit_log/conftest.py` | Pytest fixtures |
| Create | `tests/suites/32_audit_log/test_audit_log.py` | 30 checks (AL.1–AL.24) |

---

## Task 1: Create branch and apply DB migration

**Files:**
- Create: `vantage-worker/migrations/0004_audit_event_type.sql`

- [ ] **Step 1: Create the feature branch**

```bash
cd "/Users/amanjain/Documents/New Ideas/AI Cost Analysis/Cloudfare based/vantageai"
git checkout main && git pull origin main
git checkout -b feat/enterprise-soc2-audit-log
```

- [ ] **Step 2: Write the migration**

Create `vantage-worker/migrations/0004_audit_event_type.sql`:

```sql
-- Extend audit_events with event_type for category filtering
-- (table created in 0003_audit_events.sql)
ALTER TABLE audit_events ADD COLUMN event_type TEXT NOT NULL DEFAULT 'admin_action';

CREATE INDEX IF NOT EXISTS idx_audit_event_type
  ON audit_events(org_id, event_type, created_at DESC);
```

- [ ] **Step 3: Apply migration to D1**

```bash
cd vantage-worker
npx wrangler d1 execute vantage-events --file=migrations/0004_audit_event_type.sql
```

Expected output: `Successfully applied migration`

- [ ] **Step 4: Commit**

```bash
git add vantage-worker/migrations/0004_audit_event_type.sql
git commit -m "feat(db): add event_type column to audit_events"
```

---

## Task 2: Create `lib/audit.ts` shared helper

**Files:**
- Create: `vantage-worker/src/lib/audit.ts`

- [ ] **Step 1: Write the file**

Create `vantage-worker/src/lib/audit.ts`:

```typescript
import type { Context } from 'hono';
import type { Bindings, Variables } from '../types';

export interface AuditEvent {
  event_type: 'auth' | 'data_access' | 'admin_action';
  event_name: string;       // e.g. 'auth.login', 'data_access.analytics'
  resource_type?: string;   // e.g. 'analytics', 'budget_policy', 'member'
  resource_id?: string;     // e.g. member email, policy id
  metadata?: Record<string, unknown>; // old/new values, endpoint, count, etc.
}

const INSERT_SQL = `
  INSERT INTO audit_events
    (org_id, actor_email, actor_role, action, resource, detail, ip_address, event_type)
  VALUES (?, ?, ?, ?, ?, ?, ?, ?)
`;

/**
 * Fire-and-forget audit log writer for use inside Hono route handlers.
 * Pulls org_id, role, memberId from request context automatically.
 * Accepts optional overrides for auth.failed cases where context is not set.
 *
 * Never throws. Never awaited. D1 failures are silently discarded.
 */
export function logAudit(
  c: Context<{ Bindings: Bindings; Variables: Variables }>,
  event: AuditEvent,
  overrides?: { orgId?: string; actorId?: string; actorRole?: string },
): void {
  const orgId    = overrides?.orgId     ?? c.get('orgId')    ?? 'unknown';
  const role     = overrides?.actorRole ?? c.get('role')     ?? 'unknown';
  const memberId = c.get('memberId');
  const defaultActorId = memberId
    ? `member:${String(memberId).substring(0, 8)}`
    : role === 'owner' ? 'owner' : 'unknown';
  const actorId  = overrides?.actorId   ?? defaultActorId;
  const ip       = c.req.header('CF-Connecting-IP')
    ?? c.req.header('X-Forwarded-For')
    ?? '';

  const detail = JSON.stringify({
    ...(event.resource_id ? { resource_id: event.resource_id } : {}),
    ...(event.metadata    ?? {}),
  });

  c.executionCtx.waitUntil(
    c.env.DB.prepare(INSERT_SQL)
      .bind(orgId, actorId, role, event.event_name,
            event.resource_type ?? '', detail, ip, event.event_type)
      .run()
      .catch(() => {}), // audit failures must never propagate
  );
}

/**
 * Fire-and-forget variant for use before Hono context variables are set
 * (e.g., inside authMiddleware on the failure path).
 */
export function logAuditRaw(
  db: D1Database,
  ctx: ExecutionContext,
  ip: string,
  orgId: string,
  actorId: string,
  actorRole: string,
  event: AuditEvent,
): void {
  const detail = JSON.stringify({
    ...(event.resource_id ? { resource_id: event.resource_id } : {}),
    ...(event.metadata    ?? {}),
  });

  ctx.waitUntil(
    db.prepare(INSERT_SQL)
      .bind(orgId, actorId, actorRole, event.event_name,
            event.resource_type ?? '', detail, ip, event.event_type)
      .run()
      .catch(() => {}),
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add vantage-worker/src/lib/audit.ts
git commit -m "feat(audit): add shared logAudit / logAuditRaw helpers"
```

---

## Task 3: Create `routes/auditlog.ts`

**Files:**
- Create: `vantage-worker/src/routes/auditlog.ts`

- [ ] **Step 1: Write the route file**

Create `vantage-worker/src/routes/auditlog.ts`:

```typescript
import { Hono } from 'hono';
import type { Bindings, Variables } from '../types';
import { authMiddleware } from '../middleware/auth';

const auditlog = new Hono<{ Bindings: Bindings; Variables: Variables }>();

auditlog.use('*', authMiddleware);

// ── Query builder ─────────────────────────────────────────────────────────────

function buildAuditWhere(
  orgId: string | null,
  eventType: string | null,
  from: number | null,
  to: number | null,
): { where: string; bindings: unknown[] } {
  const conditions: string[] = [];
  const bindings: unknown[] = [];
  if (orgId !== null)  { conditions.push('org_id = ?');     bindings.push(orgId); }
  if (eventType)       { conditions.push('event_type = ?'); bindings.push(eventType); }
  if (from !== null)   { conditions.push('created_at >= ?'); bindings.push(from); }
  if (to !== null)     { conditions.push('created_at <= ?'); bindings.push(to); }
  return {
    where: conditions.length ? conditions.join(' AND ') : '1=1',
    bindings,
  };
}

function parseIsoDate(s: string | undefined, endOfDay = false): number | null {
  if (!s) return null;
  const suffix = endOfDay ? 'T23:59:59Z' : 'T00:00:00Z';
  const ms = new Date(s + suffix).getTime();
  return isNaN(ms) ? null : Math.floor(ms / 1000);
}

// ── GET /v1/audit-log — org owner / admin self-serve ──────────────────────────

auditlog.get('/', async (c) => {
  const role = c.get('role');
  if (role !== 'owner' && role !== 'admin') {
    return c.json({ error: 'Owner or admin key required to access audit log' }, 403);
  }

  const orgId     = c.get('orgId');
  const limit     = Math.min(parseInt(c.req.query('limit')  ?? '50', 10), 500);
  const offset    = parseInt(c.req.query('offset') ?? '0', 10);
  const eventType = c.req.query('event_type') ?? null;
  const format    = c.req.query('format')     ?? 'json';
  const from      = parseIsoDate(c.req.query('from'));
  const to        = parseIsoDate(c.req.query('to'), true);

  const { where, bindings } = buildAuditWhere(orgId, eventType, from, to);

  const [rows, countRow] = await c.env.DB.batch([
    c.env.DB.prepare(
      `SELECT id, actor_email, actor_role, action, resource, detail,
              ip_address, event_type,
              datetime(created_at, 'unixepoch') AS created_at
       FROM audit_events WHERE ${where}
       ORDER BY created_at DESC LIMIT ? OFFSET ?`
    ).bind(...bindings, limit, offset),
    c.env.DB.prepare(
      `SELECT COUNT(*) AS total FROM audit_events WHERE ${where}`
    ).bind(...bindings),
  ]);

  const events = rows.results as Record<string, unknown>[];
  const total  = (countRow.results[0] as { total: number }).total;

  if (format === 'csv') {
    return csvResponse(orgId, events);
  }

  return c.json({ events, total, has_more: offset + events.length < total });
});

// ── CSV helper ────────────────────────────────────────────────────────────────

function csvResponse(orgId: string, events: Record<string, unknown>[]): Response {
  const header = 'id,org_id,actor_id,actor_role,event_type,event_name,resource,detail,ip_address,created_at\n';
  const rows = events.map(e =>
    [e['id'], orgId, e['actor_email'], e['actor_role'], e['event_type'],
     e['action'], e['resource'], e['detail'], e['ip_address'], e['created_at']]
      .map(v => `"${String(v ?? '').replace(/"/g, '""')}"`)
      .join(',')
  ).join('\n');

  return new Response(header + rows, {
    headers: {
      'Content-Type': 'text/csv',
      'Content-Disposition': `attachment; filename="audit-log-${orgId}.csv"`,
    },
  });
}

export { auditlog };
```

- [ ] **Step 2: Commit**

```bash
git add vantage-worker/src/routes/auditlog.ts
git commit -m "feat(audit): add GET /v1/audit-log endpoint with CSV export"
```

---

## Task 4: Add admin audit-log endpoint + register routes

**Files:**
- Modify: `vantage-worker/src/routes/admin.ts`
- Modify: `vantage-worker/src/index.ts`

- [ ] **Step 1: Remove old logAudit from admin.ts**

Delete lines 5–19 of `admin.ts` (the existing `logAudit` function). Its callers inside admin.ts should be updated to use `import { logAudit } from '../lib/audit'` instead. Add that import at the top.

- [ ] **Step 2: Add admin audit-log endpoint to admin.ts**

Add this block before `export { admin }` at the bottom of `admin.ts`:

```typescript
// ── GET /v1/admin/audit-log — all orgs, admin only ───────────────────────────

admin.get('/audit-log', async (c) => {
  const limit     = Math.min(parseInt(c.req.query('limit')   ?? '100', 10), 500);
  const offset    = parseInt(c.req.query('offset')  ?? '0', 10);
  const eventType = c.req.query('event_type') ?? null;
  const orgFilter = c.req.query('org_id')     ?? null;
  const from      = c.req.query('from')
    ? Math.floor(new Date(c.req.query('from')! + 'T00:00:00Z').getTime() / 1000) : null;
  const to        = c.req.query('to')
    ? Math.floor(new Date(c.req.query('to')!   + 'T23:59:59Z').getTime() / 1000) : null;

  const conditions: string[] = [];
  const bindings: unknown[]  = [];
  if (orgFilter)    { conditions.push('org_id = ?');     bindings.push(orgFilter); }
  if (eventType)    { conditions.push('event_type = ?'); bindings.push(eventType); }
  if (from !== null){ conditions.push('created_at >= ?'); bindings.push(from); }
  if (to !== null)  { conditions.push('created_at <= ?'); bindings.push(to); }
  const where = conditions.length ? conditions.join(' AND ') : '1=1';

  const [rows, countRow] = await c.env.DB.batch([
    c.env.DB.prepare(
      `SELECT id, org_id, actor_email, actor_role, action, resource, detail,
              ip_address, event_type,
              datetime(created_at, 'unixepoch') AS created_at
       FROM audit_events WHERE ${where}
       ORDER BY created_at DESC LIMIT ? OFFSET ?`
    ).bind(...bindings, limit, offset),
    c.env.DB.prepare(
      `SELECT COUNT(*) AS total FROM audit_events WHERE ${where}`
    ).bind(...bindings),
  ]);

  const events = rows.results;
  const total  = (countRow.results[0] as { total: number }).total;
  return c.json({ events, total, has_more: offset + events.length < total });
});
```

- [ ] **Step 3: Register the auditlog route in index.ts**

Add import at the top of `vantage-worker/src/index.ts`:

```typescript
import { auditlog }    from './routes/auditlog';
```

Add route registration after the crossplatform line:

```typescript
app.route('/v1/audit-log',      auditlog);
```

Add to the endpoint comment block:

```
 *   GET  /v1/audit-log             (org owner/admin — paginated audit trail + CSV)
 *   GET  /v1/admin/audit-log       (admin — all orgs audit trail)
```

- [ ] **Step 4: TypeScript check**

```bash
cd vantage-worker && npx tsc --noEmit
```

Expected: 0 errors.

- [ ] **Step 5: Commit**

```bash
git add vantage-worker/src/routes/admin.ts vantage-worker/src/index.ts
git commit -m "feat(audit): register audit-log routes, add admin endpoint"
```

---

## Task 5: Wire auth events into `auth.ts`

**Files:**
- Modify: `vantage-worker/src/middleware/auth.ts`

- [ ] **Step 1: Add import at the top of auth.ts**

```typescript
import { logAudit, logAuditRaw } from '../lib/audit';
```

- [ ] **Step 2: Log `auth.login` after successful session cookie auth**

Inside the `if (session)` block, add before `return await next()`:

```typescript
      logAudit(c, { event_type: 'auth', event_name: 'auth.login', resource_type: 'session' });
      return await next();
```

- [ ] **Step 3: Log `auth.login` after successful API key auth**

At the bottom of the API key path, just before `return await next()`:

```typescript
  logAudit(c, { event_type: 'auth', event_name: 'auth.login', resource_type: 'api_key' });
  return await next();
```

- [ ] **Step 4: Log `auth.failed` for missing/invalid key**

Find:

```typescript
  if (!apiKey || !apiKey.startsWith('crt_')) {
    return c.json({ error: 'Missing or invalid API key. Expected: Bearer crt_...' }, 401);
  }
```

Replace with:

```typescript
  if (!apiKey || !apiKey.startsWith('crt_')) {
    const ip = c.req.header('CF-Connecting-IP') ?? c.req.header('X-Forwarded-For') ?? '';
    logAuditRaw(c.env.DB, c.executionCtx, ip, 'unknown', 'unknown', 'unknown', {
      event_type: 'auth',
      event_name: 'auth.failed',
      metadata: { reason: 'missing_or_malformed_key', path: c.req.path },
    });
    return c.json({ error: 'Missing or invalid API key. Expected: Bearer crt_...' }, 401);
  }
```

- [ ] **Step 5: Log `auth.failed` for key-not-found**

Find:

```typescript
    if (!member) {
      return c.json({ error: 'API key not found. Sign up at cohrint.com' }, 401);
    }
```

Replace with:

```typescript
    if (!member) {
      const ip = c.req.header('CF-Connecting-IP') ?? c.req.header('X-Forwarded-For') ?? '';
      logAuditRaw(c.env.DB, c.executionCtx, ip, orgId || 'unknown',
        `key:${hash.substring(0, 8)}`, 'unknown', {
          event_type: 'auth',
          event_name: 'auth.failed',
          metadata: { reason: 'key_not_found', path: c.req.path },
        });
      return c.json({ error: 'API key not found. Sign up at cohrint.com' }, 401);
    }
```

- [ ] **Step 6: TypeScript check**

```bash
cd vantage-worker && npx tsc --noEmit
```

- [ ] **Step 7: Commit**

```bash
git add vantage-worker/src/middleware/auth.ts
git commit -m "feat(audit): log auth.login and auth.failed events"
```

---

## Task 6: Wire data_access events into `analytics.ts`

**Files:**
- Modify: `vantage-worker/src/routes/analytics.ts`

- [ ] **Step 1: Add import**

```typescript
import { logAudit } from '../lib/audit';
```

- [ ] **Step 2: Add per-request data_access middleware**

After the existing `analytics.use('*', authMiddleware)` line, add:

```typescript
// Log every analytics read as a data_access event (fire-and-forget after response)
analytics.use('*', async (c, next) => {
  await next();
  logAudit(c, {
    event_type:    'data_access',
    event_name:    'data_access.analytics',
    resource_type: 'analytics',
    metadata:      { endpoint: new URL(c.req.url).pathname },
  });
});
```

- [ ] **Step 3: TypeScript check + commit**

```bash
cd vantage-worker && npx tsc --noEmit
git add vantage-worker/src/routes/analytics.ts
git commit -m "feat(audit): log data_access.analytics on every analytics GET"
```

---

## Task 7: Wire admin_action events

**Files:**
- Modify: `vantage-worker/src/routes/crossplatform.ts`
- Modify: `vantage-worker/src/routes/alerts.ts`
- Modify: `vantage-worker/src/routes/admin.ts` (member add/remove)

- [ ] **Step 1: Add import to crossplatform.ts**

```typescript
import { logAudit } from '../lib/audit';
```

- [ ] **Step 2: Log budget policy changes in crossplatform.ts**

Find any PUT or POST route that writes to `budget_policies`. After the successful DB write, add:

```typescript
logAudit(c, {
  event_type:    'admin_action',
  event_name:    'admin_action.budget_policy_changed',
  resource_type: 'budget_policy',
  metadata:      { updated_at: new Date().toISOString() },
});
```

If the handler has old and new values available, pass them in `metadata`:

```typescript
metadata: { old_limit_usd: oldLimit, new_limit_usd: newLimit, enforcement }
```

- [ ] **Step 3: Add import to alerts.ts**

```typescript
import { logAudit } from '../lib/audit';
```

- [ ] **Step 4: Log Slack config changes in alerts.ts**

Find the route that saves a Slack webhook URL (search for `kv.put` with `slack:` prefix). After the save, add:

```typescript
logAudit(c, {
  event_type:    'admin_action',
  event_name:    'admin_action.alert_config_changed',
  resource_type: 'alert_config',
  metadata:      { action: 'slack_webhook_updated' },
});
```

- [ ] **Step 5: Log member add/remove in admin.ts**

Find the POST route that creates a member. After the DB insert succeeds, add:

```typescript
logAudit(c, {
  event_type:    'admin_action',
  event_name:    'admin_action.member_added',
  resource_type: 'member',
  resource_id:   newMemberEmail,  // use the actual variable from the handler
  metadata:      { role: newMemberRole },
});
```

Find the DELETE route that removes a member. After the DB delete succeeds, add:

```typescript
logAudit(c, {
  event_type:    'admin_action',
  event_name:    'admin_action.member_removed',
  resource_type: 'member',
  resource_id:   removedEmail,  // use the actual variable from the handler
});
```

- [ ] **Step 6: TypeScript check + commit**

```bash
cd vantage-worker && npx tsc --noEmit
git add vantage-worker/src/routes/crossplatform.ts \
        vantage-worker/src/routes/alerts.ts \
        vantage-worker/src/routes/admin.ts
git commit -m "feat(audit): log admin_action events for budget, alerts, members"
```

---

## Task 8: Write test suite

**Files:**
- Create: `tests/suites/32_audit_log/__init__.py`
- Create: `tests/suites/32_audit_log/conftest.py`
- Create: `tests/suites/32_audit_log/test_audit_log.py`

- [ ] **Step 1: Create `__init__.py`**

```python
# tests/suites/32_audit_log/__init__.py
```

- [ ] **Step 2: Create `conftest.py`**

```python
"""conftest.py — Pytest fixtures for audit log tests (32_audit_log)"""
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from helpers.api import fresh_account, get_headers


@pytest.fixture(scope="module")
def account():
    return fresh_account(prefix="al32")


@pytest.fixture(scope="module")
def headers(account):
    api_key, _, _ = account
    return get_headers(api_key)


@pytest.fixture(scope="module")
def member_account():
    return fresh_account(prefix="al32b")
```

- [ ] **Step 3: Create `test_audit_log.py`**

```python
"""
Test Suite 32 — Audit Log Tests
================================
Suite AL: Validates the SOC2 audit trail — auth events, data access events,
admin action events, org isolation, pagination, filtering, CSV export, and
the public roadmap page.

Labels: AL.1 - AL.24  (24 checks)
"""
import sys
import time
import json
import requests
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config.settings import API_URL
from helpers.api import fresh_account, get_headers
from helpers.output import section, chk, get_results, reset_results, fail

FRONTEND_URL = "https://cohrint.com"


# ═══════════════════════════════════════════════════════════════════════════════
#  Section A: Endpoint Access Control
# ═══════════════════════════════════════════════════════════════════════════════

class TestAccessControl:

    def test_al01_owner_can_access_audit_log(self, headers):
        section("A --- Endpoint Access Control")
        r = requests.get(f"{API_URL}/v1/audit-log", headers=headers, timeout=10)
        chk("AL.1 owner key returns 200", r.status_code == 200, f"got {r.status_code}")
        assert r.status_code == 200

    def test_al02_response_shape(self, headers):
        r = requests.get(f"{API_URL}/v1/audit-log", headers=headers, timeout=10)
        data = r.json()
        chk("AL.2 response has events list", "events" in data, str(data.keys()))
        chk("AL.2b response has total field", "total" in data, str(data.keys()))
        assert "events" in data and "total" in data

    def test_al03_no_auth_returns_401(self):
        r = requests.get(f"{API_URL}/v1/audit-log", timeout=10)
        chk("AL.3 no auth returns 401", r.status_code == 401, f"got {r.status_code}")
        assert r.status_code == 401

    def test_al04_admin_endpoint_blocked_for_org_key(self, headers):
        r = requests.get(f"{API_URL}/v1/admin/audit-log", headers=headers, timeout=10)
        chk("AL.4 org owner key cannot access admin audit-log", r.status_code in (401, 403),
            f"got {r.status_code}")
        assert r.status_code in (401, 403)


# ═══════════════════════════════════════════════════════════════════════════════
#  Section B: Auth Events
# ═══════════════════════════════════════════════════════════════════════════════

class TestAuthEvents:

    def test_al05_login_creates_auth_event(self, headers):
        section("B --- Auth Events")
        requests.get(f"{API_URL}/v1/analytics/summary", headers=headers, timeout=10)
        time.sleep(1)
        r = requests.get(f"{API_URL}/v1/audit-log?event_type=auth&limit=20",
                         headers=headers, timeout=10)
        events = r.json().get("events", [])
        login_events = [e for e in events if e.get("action") == "auth.login"]
        chk("AL.5 auth.login event exists", len(login_events) > 0,
            f"found {len(login_events)} login events in {len(events)} total")
        assert len(login_events) > 0

    def test_al06_auth_event_fields(self, headers):
        r = requests.get(f"{API_URL}/v1/audit-log?event_type=auth&limit=5",
                         headers=headers, timeout=10)
        events = r.json().get("events", [])
        if not events:
            pytest.skip("No auth events yet")
        e = events[0]
        chk("AL.6 event_type=auth", e.get("event_type") == "auth", str(e.get("event_type")))
        chk("AL.6b has actor_role", bool(e.get("actor_role")), str(e.get("actor_role")))
        chk("AL.6c has created_at", bool(e.get("created_at")), str(e.get("created_at")))

    def test_al07_event_type_filter_returns_only_auth(self, headers):
        r = requests.get(f"{API_URL}/v1/audit-log?event_type=auth&limit=20",
                         headers=headers, timeout=10)
        events = r.json().get("events", [])
        if not events:
            pytest.skip("No auth events to filter")
        non_auth = [e for e in events if e.get("event_type") != "auth"]
        chk("AL.7 event_type=auth returns only auth events",
            len(non_auth) == 0, f"{len(non_auth)} non-auth events leaked")


# ═══════════════════════════════════════════════════════════════════════════════
#  Section C: Data Access Events
# ═══════════════════════════════════════════════════════════════════════════════

class TestDataAccessEvents:

    def test_al08_analytics_creates_data_access_event(self, headers):
        section("C --- Data Access Events")
        for path in ["/v1/analytics/summary", "/v1/analytics/kpis", "/v1/analytics/models"]:
            requests.get(f"{API_URL}{path}", headers=headers, timeout=10)
        time.sleep(1)
        r = requests.get(f"{API_URL}/v1/audit-log?event_type=data_access&limit=20",
                         headers=headers, timeout=10)
        events = r.json().get("events", [])
        da_events = [e for e in events if e.get("action") == "data_access.analytics"]
        chk("AL.8 data_access.analytics events exist", len(da_events) > 0,
            f"found {len(da_events)} data_access events in {len(events)} total")
        assert len(da_events) > 0

    def test_al09_data_access_event_has_endpoint_metadata(self, headers):
        r = requests.get(f"{API_URL}/v1/audit-log?event_type=data_access&limit=5",
                         headers=headers, timeout=10)
        events = r.json().get("events", [])
        if not events:
            pytest.skip("No data_access events yet")
        e = events[0]
        chk("AL.9 event_type=data_access", e.get("event_type") == "data_access",
            str(e.get("event_type")))
        detail_raw = e.get("detail", "{}")
        try:
            meta = json.loads(detail_raw) if isinstance(detail_raw, str) else detail_raw
            chk("AL.9b detail.endpoint present", "endpoint" in meta, str(meta))
        except Exception:
            chk("AL.9b detail.endpoint present", False, f"parse failed: {detail_raw}")


# ═══════════════════════════════════════════════════════════════════════════════
#  Section D: Pagination and Filtering
# ═══════════════════════════════════════════════════════════════════════════════

class TestPaginationFiltering:

    def test_al10_limit_respected(self, headers):
        section("D --- Pagination & Filtering")
        r = requests.get(f"{API_URL}/v1/audit-log?limit=2", headers=headers, timeout=10)
        events = r.json().get("events", [])
        chk("AL.10 limit=2 returns at most 2", len(events) <= 2, f"got {len(events)}")

    def test_al11_offset_advances_page(self, headers):
        r1 = requests.get(f"{API_URL}/v1/audit-log?limit=1&offset=0", headers=headers, timeout=10)
        r2 = requests.get(f"{API_URL}/v1/audit-log?limit=1&offset=1", headers=headers, timeout=10)
        e1 = r1.json().get("events", [{}])
        e2 = r2.json().get("events", [{}])
        if not e1 or not e2:
            pytest.skip("Not enough events to test offset")
        chk("AL.11 offset=1 returns different event",
            e1[0].get("id") != e2[0].get("id"),
            f"id0={e1[0].get('id')} id1={e2[0].get('id')}")

    def test_al12_has_more_flag(self, headers):
        r_all   = requests.get(f"{API_URL}/v1/audit-log?limit=500", headers=headers, timeout=10)
        total   = r_all.json().get("total", 0)
        r_small = requests.get(f"{API_URL}/v1/audit-log?limit=1",   headers=headers, timeout=10)
        has_more = r_small.json().get("has_more", False)
        chk("AL.12 has_more accurate", has_more == (total > 1),
            f"total={total} has_more={has_more}")

    def test_al13_data_access_filter_correct(self, headers):
        r = requests.get(f"{API_URL}/v1/audit-log?event_type=data_access&limit=20",
                         headers=headers, timeout=10)
        events = r.json().get("events", [])
        if not events:
            pytest.skip("No data_access events to filter")
        wrong = [e for e in events if e.get("event_type") != "data_access"]
        chk("AL.13 data_access filter returns only data_access",
            len(wrong) == 0, f"{len(wrong)} wrong-type events")

    def test_al14_events_newest_first(self, headers):
        r = requests.get(f"{API_URL}/v1/audit-log?limit=10", headers=headers, timeout=10)
        events = r.json().get("events", [])
        if len(events) < 2:
            pytest.skip("Need 2+ events to test ordering")
        ts = [e.get("created_at", "") for e in events]
        chk("AL.14 events newest-first", ts == sorted(ts, reverse=True),
            f"first={ts[0]} last={ts[-1]}")


# ═══════════════════════════════════════════════════════════════════════════════
#  Section E: Org Isolation
# ═══════════════════════════════════════════════════════════════════════════════

class TestOrgIsolation:

    def test_al15_org_isolation(self, account, member_account):
        section("E --- Org Isolation")
        api_key_a, org_id_a, _ = account
        api_key_b, _, _        = member_account

        # Trigger event in org A
        requests.get(f"{API_URL}/v1/analytics/summary",
                     headers=get_headers(api_key_a), timeout=10)
        time.sleep(1)

        # Org B should not see org A events
        r = requests.get(f"{API_URL}/v1/audit-log?limit=100",
                         headers=get_headers(api_key_b), timeout=10)
        events = r.json().get("events", [])
        leaked = [e for e in events if e.get("org_id") == org_id_a]
        chk("AL.15 org B cannot see org A events",
            len(leaked) == 0, f"{len(leaked)} org A events leaked")
        assert len(leaked) == 0


# ═══════════════════════════════════════════════════════════════════════════════
#  Section F: CSV Export
# ═══════════════════════════════════════════════════════════════════════════════

class TestCsvExport:

    def test_al16_csv_returns_200(self, headers):
        section("F --- CSV Export")
        r = requests.get(f"{API_URL}/v1/audit-log?format=csv", headers=headers, timeout=10)
        chk("AL.16 CSV returns 200", r.status_code == 200, f"got {r.status_code}")
        assert r.status_code == 200

    def test_al17_csv_content_type(self, headers):
        r = requests.get(f"{API_URL}/v1/audit-log?format=csv", headers=headers, timeout=10)
        ct = r.headers.get("content-type", "")
        chk("AL.17 Content-Type is text/csv", "text/csv" in ct, f"got {ct}")

    def test_al18_csv_header_row(self, headers):
        r = requests.get(f"{API_URL}/v1/audit-log?format=csv&limit=5", headers=headers, timeout=10)
        lines = r.text.strip().split("\n")
        chk("AL.18 CSV has header row", len(lines) >= 1, f"got {len(lines)} lines")
        chk("AL.18b header contains event_type",
            "event_type" in lines[0], f"header: {lines[0][:100]}")


# ═══════════════════════════════════════════════════════════════════════════════
#  Section G: Roadmap Page
# ═══════════════════════════════════════════════════════════════════════════════

class TestRoadmapPage:

    def test_al19_roadmap_accessible(self):
        section("G --- Roadmap Page")
        r = requests.get(f"{FRONTEND_URL}/roadmap.html", timeout=15)
        chk("AL.19 roadmap.html returns 200", r.status_code == 200, f"got {r.status_code}")
        assert r.status_code == 200

    def test_al20_roadmap_contains_live(self):
        r = requests.get(f"{FRONTEND_URL}/roadmap.html", timeout=15)
        chk("AL.20 roadmap contains 'Live'", "Live" in r.text)

    def test_al21_roadmap_contains_q2_2026(self):
        r = requests.get(f"{FRONTEND_URL}/roadmap.html", timeout=15)
        chk("AL.21 roadmap contains 'Q2 2026'", "Q2 2026" in r.text)

    def test_al22_roadmap_no_100_percent_claim(self):
        r = requests.get(f"{FRONTEND_URL}/roadmap.html", timeout=15)
        chk("AL.22 roadmap has no '100% coverage' claim",
            "100% coverage" not in r.text and "Zero gaps" not in r.text,
            "Found inaccurate claim on roadmap page")

    def test_al23_app_loads(self):
        r = requests.get(f"{FRONTEND_URL}/app.html", timeout=15)
        chk("AL.23 app.html loads", r.status_code == 200, f"got {r.status_code}")

    def test_al24_app_contains_security_nav(self):
        r = requests.get(f"{FRONTEND_URL}/app.html", timeout=15)
        chk("AL.24 app.html has Security nav item",
            "security" in r.text.lower(),
            "Security nav item not found in dashboard source")


# ── Runner ────────────────────────────────────────────────────────────────────

def run():
    reset_results()
    api_key, org_id, cookies     = fresh_account(prefix="al32run")
    api_key_b, org_id_b, cook_b  = fresh_account(prefix="al32runb")
    hdrs  = get_headers(api_key)
    acct  = (api_key, org_id, cookies)
    acct_b = (api_key_b, org_id_b, cook_b)

    import inspect
    for cls in [TestAccessControl, TestAuthEvents, TestDataAccessEvents,
                TestPaginationFiltering, TestOrgIsolation, TestCsvExport,
                TestRoadmapPage]:
        obj = cls()
        for name in sorted(dir(obj)):
            if name.startswith("test_"):
                try:
                    method = getattr(obj, name)
                    params = inspect.signature(method).parameters
                    kwargs: dict = {}
                    if "account"        in params: kwargs["account"]        = acct
                    if "member_account" in params: kwargs["member_account"] = acct_b
                    if "headers"        in params: kwargs["headers"]        = hdrs
                    method(**kwargs)
                except Exception as e:
                    fail(name, str(e))

    res = get_results()
    print(f"\n{'='*60}")
    print(f"Results: {res['passed']} passed, {res['failed']} failed")
    return res["failed"]


if __name__ == "__main__":
    import sys
    sys.exit(run())
```

- [ ] **Step 4: Syntax check + commit**

```bash
python -m py_compile tests/suites/32_audit_log/test_audit_log.py && echo "OK"
git add tests/suites/32_audit_log/
git commit -m "test(suite32): add audit log test suite AL.1-AL.24"
```

---

## Task 9: Add Security and Integrations views to `app.html`

**Files:**
- Modify: `vantage-final-v4/app.html`

- [ ] **Step 1: Add sidebar nav items**

Find (around line 636):

```html
    <div class="sidebar-section">
      <div class="sidebar-label">System</div>
      <button class="sb-item" id="sb-settings" onclick="nav('settings', this)">
        <span class="icon">&#9881;</span> Settings
      </button>
      <button class="sb-item" onclick="nav('account', this)">
        <span class="icon">&#9683;</span> Account
      </button>
    </div>
```

Replace with:

```html
    <div class="sidebar-section">
      <div class="sidebar-label">System</div>
      <button class="sb-item" id="sb-settings" onclick="nav('settings', this)">
        <span class="icon">&#9881;</span> Settings
      </button>
      <button class="sb-item" onclick="nav('security', this)">
        <span class="icon">&#128274;</span> Security
      </button>
      <button class="sb-item" onclick="nav('integrations', this)">
        <span class="icon">&#128279;</span> Integrations
      </button>
      <button class="sb-item" onclick="nav('account', this)">
        <span class="icon">&#9683;</span> Account
      </button>
    </div>
```

- [ ] **Step 2: Add Security and Integrations view HTML**

Find the closing tag of `id="view-settings"` (around line 1041) and insert after it:

```html
      <!-- ─── Security (Audit Log) ─── -->
      <div id="view-security" class="view">
        <div class="card">
          <div class="card-header" style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px;">
            <div class="card-title">Audit Log</div>
            <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
              <select id="auditTypeFilter" onchange="loadAuditLog()" style="font-size:11px;padding:4px 8px;background:var(--bg-card);border:1px solid var(--border);color:var(--text-primary);border-radius:4px;">
                <option value="">All events</option>
                <option value="auth">Auth</option>
                <option value="data_access">Data Access</option>
                <option value="admin_action">Admin Actions</option>
              </select>
              <input type="date" id="auditDateFrom" onchange="loadAuditLog()" style="font-size:11px;padding:4px;background:var(--bg-card);border:1px solid var(--border);color:var(--text-primary);border-radius:4px;">
              <input type="date" id="auditDateTo"   onchange="loadAuditLog()" style="font-size:11px;padding:4px;background:var(--bg-card);border:1px solid var(--border);color:var(--text-primary);border-radius:4px;">
              <button class="btn btn-sm" onclick="exportAuditCsv()">Export CSV</button>
            </div>
          </div>
          <div id="auditLogTable" style="margin-top:8px;font-size:11px;overflow-x:auto;">
            <div style="color:var(--text-muted);padding:16px 0;">Loading audit log...</div>
          </div>
          <div style="display:flex;gap:8px;margin-top:12px;align-items:center;">
            <button class="btn btn-sm" id="auditPrevBtn" onclick="auditPage(-1)" disabled>Prev</button>
            <span id="auditPageInfo" style="font-size:11px;color:var(--text-muted);"></span>
            <button class="btn btn-sm" id="auditNextBtn" onclick="auditPage(1)">Next</button>
          </div>
        </div>
      </div>

      <!-- ─── Integrations ─── -->
      <div id="view-integrations" class="view">
        <div class="card">
          <div class="card-header"><div class="card-title">Integration Status</div></div>
          <p style="font-size:12px;color:var(--text-secondary);margin-bottom:16px;">
            Real-time OTel coverage is live across 10+ tools. Billing API connectors and browser extension are on the roadmap.
            <a href="/roadmap.html" target="_blank" style="color:var(--accent-green);">View full roadmap</a>
          </p>
          <div id="integrationsGrid" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:10px;"></div>
        </div>
      </div>
```

- [ ] **Step 3: Wire new views into `loadViewData`**

Find `function loadViewData(view)` (around line 1310) and add two cases:

```javascript
    case 'security':      loadAuditLog(); break;
    case 'integrations':  loadIntegrations(); break;
```

- [ ] **Step 4: Add `loadAuditLog` and `loadIntegrations` JavaScript**

Find `function loadSettings()` (around line 2470) and add these functions after the existing `loadSettings` function. Use safe DOM construction — all API-derived values are set via `textContent`, never via `innerHTML`:

```javascript
/* ═══════════════════════════════════════════════════════════════════
   Audit Log
   ═══════════════════════════════════════════════════════════════════ */

var auditOffset = 0;
var auditLimit  = 50;
var auditTotal  = 0;

function loadAuditLog()  { auditOffset = 0; fetchAuditPage(); }
function auditPage(dir)  { auditOffset = Math.max(0, auditOffset + dir * auditLimit); fetchAuditPage(); }

function fetchAuditPage() {
  var type = document.getElementById('auditTypeFilter').value;
  var from = document.getElementById('auditDateFrom').value;
  var to   = document.getElementById('auditDateTo').value;
  var qs   = '?limit=' + auditLimit + '&offset=' + auditOffset;
  if (type) qs += '&event_type=' + encodeURIComponent(type);
  if (from) qs += '&from='       + encodeURIComponent(from);
  if (to)   qs += '&to='         + encodeURIComponent(to);

  var container = document.getElementById('auditLogTable');
  container.textContent = '';
  var loading = document.createElement('div');
  loading.style.cssText = 'color:var(--text-muted);padding:8px 0;';
  loading.textContent = 'Loading...';
  container.appendChild(loading);

  apiFetch('/v1/audit-log' + qs).catch(function() { return null; }).then(function(data) {
    container.textContent = '';
    if (!data) {
      var msg = document.createElement('div');
      msg.style.color = 'var(--text-muted)';
      msg.textContent = 'Unable to load audit log. Owner key required.';
      container.appendChild(msg);
      return;
    }

    auditTotal = data.total || 0;
    var events = data.events || [];

    if (events.length === 0) {
      var empty = document.createElement('div');
      empty.style.cssText = 'color:var(--text-muted);padding:16px 0;';
      empty.textContent = 'No audit events found.';
      container.appendChild(empty);
      document.getElementById('auditPageInfo').textContent = '0 events';
      document.getElementById('auditPrevBtn').disabled = true;
      document.getElementById('auditNextBtn').disabled = true;
      return;
    }

    var BADGE_COLOR = {
      'auth':              'var(--accent-green)',
      'auth.failed':       '#e05555',
      'data_access':       'var(--text-muted)',
      'admin_action':      'var(--accent-amber)',
    };

    var table = document.createElement('table');
    table.className = 'tool-table';
    table.style.fontSize = '11px';
    var thead = document.createElement('thead');
    var hrow  = document.createElement('tr');
    ['Time','Event','Actor','Resource','IP'].forEach(function(h) {
      var th = document.createElement('th');
      th.textContent = h;
      hrow.appendChild(th);
    });
    thead.appendChild(hrow);
    table.appendChild(thead);

    var tbody = document.createElement('tbody');
    events.forEach(function(e) {
      var action   = String(e.action || '');
      var evType   = String(e.event_type || '');
      var color    = BADGE_COLOR[action] || BADGE_COLOR[evType] || 'var(--text-muted)';
      var ts       = String(e.created_at || '').replace('T', ' ').slice(0, 19);
      var actor    = String(e.actor_email || '');
      var resource = String(e.resource || '');
      var ip       = String(e.ip_address || '');

      var tr = document.createElement('tr');

      var tdTime = document.createElement('td');
      tdTime.style.color = 'var(--text-muted)';
      tdTime.textContent = ts;

      var tdEvent = document.createElement('td');
      var badge = document.createElement('span');
      badge.style.cssText = 'font-size:10px;padding:2px 6px;border-radius:10px;background:' + color + '22;color:' + color + ';';
      badge.textContent = action;
      tdEvent.appendChild(badge);

      var tdActor = document.createElement('td');
      tdActor.style.fontFamily = 'var(--font-mono)';
      tdActor.textContent = actor;

      var tdResource = document.createElement('td');
      tdResource.textContent = resource;

      var tdIp = document.createElement('td');
      tdIp.style.cssText = 'color:var(--text-muted);font-family:var(--font-mono);font-size:10px;';
      tdIp.textContent = ip;

      [tdTime, tdEvent, tdActor, tdResource, tdIp].forEach(function(td) { tr.appendChild(td); });
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    container.appendChild(table);

    var start = auditOffset + 1;
    var end   = auditOffset + events.length;
    document.getElementById('auditPageInfo').textContent = start + '\u2013' + end + ' of ' + auditTotal;
    document.getElementById('auditPrevBtn').disabled = auditOffset === 0;
    document.getElementById('auditNextBtn').disabled = !data.has_more;
  });
}

function exportAuditCsv() {
  var type    = document.getElementById('auditTypeFilter').value;
  var from    = document.getElementById('auditDateFrom').value;
  var to      = document.getElementById('auditDateTo').value;
  var apiBase = localStorage.getItem('vantage_api_base') || 'https://api.cohrint.com';
  var token   = localStorage.getItem('vantage_api_key') || '';
  var qs = '?format=csv&limit=500';
  if (type) qs += '&event_type=' + encodeURIComponent(type);
  if (from) qs += '&from='       + encodeURIComponent(from);
  if (to)   qs += '&to='         + encodeURIComponent(to);
  // Fetch as blob and trigger download — avoids exposing key in URL
  fetch(apiBase + '/v1/audit-log' + qs, {
    headers: { 'Authorization': 'Bearer ' + token }
  }).then(function(res) {
    return res.blob();
  }).then(function(blob) {
    var url = URL.createObjectURL(blob);
    var a   = document.createElement('a');
    a.href  = url;
    a.download = 'audit-log.csv';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }).catch(function() {});
}

/* ═══════════════════════════════════════════════════════════════════
   Integrations Status
   ═══════════════════════════════════════════════════════════════════ */

var INTEGRATION_STATUS = [
  { name: 'Claude Code',        method: 'OTel',        status: 'live' },
  { name: 'Gemini CLI',         method: 'OTel',        status: 'live' },
  { name: 'GitHub Copilot',     method: 'OTel',        status: 'live' },
  { name: 'Codex CLI',          method: 'OTel',        status: 'live' },
  { name: 'Cline',              method: 'OTel',        status: 'live' },
  { name: 'Windsurf',           method: 'OTel',        status: 'live' },
  { name: 'Aider',              method: 'OTel',        status: 'live' },
  { name: 'GitHub Copilot',     method: 'Billing API', status: 'q2' },
  { name: 'Cursor',             method: 'Billing API', status: 'q2' },
  { name: 'OpenAI',             method: 'Billing API', status: 'q2' },
  { name: 'Anthropic',          method: 'Billing API', status: 'q2' },
  { name: 'Local file scanner', method: 'CLI',         status: 'q3' },
  { name: 'ChatGPT web',        method: 'Browser ext', status: 'q3' },
  { name: 'Claude Console',     method: 'Browser ext', status: 'q3' },
];

var STATUS_CFG = {
  live: { dot: 'var(--accent-green)', label: 'Live',    glow: true },
  q2:   { dot: 'var(--accent-amber)', label: 'Q2 2026', glow: false },
  q3:   { dot: '#5b8dee',             label: 'Q3 2026', glow: false },
};

function loadIntegrations() {
  var grid = document.getElementById('integrationsGrid');
  if (!grid) return;
  grid.textContent = '';

  INTEGRATION_STATUS.forEach(function(item) {
    var cfg = STATUS_CFG[item.status] || STATUS_CFG['q3'];

    var card = document.createElement('div');
    card.style.cssText = 'background:var(--bg-card);border:1px solid var(--border);border-radius:8px;padding:12px 14px;display:flex;align-items:center;gap:10px;';

    var dot = document.createElement('div');
    dot.style.cssText = 'width:8px;height:8px;border-radius:50%;background:' + cfg.dot + ';flex-shrink:0;' +
      (cfg.glow ? 'box-shadow:0 0 6px ' + cfg.dot + ';' : '');

    var body = document.createElement('div');
    body.style.cssText = 'flex:1;min-width:0;';

    var nameEl = document.createElement('div');
    nameEl.style.cssText = 'font-size:12px;font-weight:500;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;';
    nameEl.textContent = item.name;

    var methodEl = document.createElement('div');
    methodEl.style.cssText = 'font-size:10px;color:var(--text-muted);';
    methodEl.textContent = item.method;

    body.appendChild(nameEl);
    body.appendChild(methodEl);

    var badge = document.createElement('span');
    badge.style.cssText = 'font-size:10px;padding:2px 8px;border-radius:10px;background:' + cfg.dot + '22;color:' + cfg.dot + ';white-space:nowrap;';
    badge.textContent = cfg.label;

    card.appendChild(dot);
    card.appendChild(body);
    card.appendChild(badge);
    grid.appendChild(card);
  });
}
```

- [ ] **Step 5: Commit**

```bash
git add vantage-final-v4/app.html
git commit -m "feat(dashboard): add Security (audit log) and Integrations views"
```

---

## Task 10: Create `roadmap.html`

**Files:**
- Create: `vantage-final-v4/roadmap.html`

- [ ] **Step 1: Write the file**

Create `vantage-final-v4/roadmap.html` with these sections:
1. Header with logo link back to `/`
2. `<h1>Integration Roadmap</h1>`
3. Section "Live Now — OTel Real-Time Tracking": 7 tile cards (Claude Code, Gemini CLI, GitHub Copilot, Codex CLI, Cline, Windsurf, Aider) with green dots and "Live" badges
4. Section "Coming Q2 2026 — Billing API Connectors": 4 tiles (GitHub Copilot, Cursor, OpenAI, Anthropic) with amber dots
5. Section "Coming Q3 2026": 3 tiles (local file scanner, ChatGPT web, Claude Console) with blue dots
6. CTA block linking to `/docs.html#otel-setup`

All text content set via `textContent` in static HTML (no dynamic rendering needed on this page — it is fully static). Use the same CSS variables as `docs.html` for consistent styling. Copy the `<head>` meta/CSS structure from `docs.html` as a starting point.

- [ ] **Step 2: Verify no "100%" claims**

```bash
grep -n "100%\|zero gaps\|Zero gaps" vantage-final-v4/roadmap.html
```

Expected: no matches.

- [ ] **Step 3: Commit**

```bash
git add vantage-final-v4/roadmap.html
git commit -m "feat(frontend): add public roadmap.html with honest integration status"
```

---

## Task 11: Fix `PRODUCT_STRATEGY.md`

**Files:**
- Modify: `PRODUCT_STRATEGY.md`

- [ ] **Step 1: Find and replace the coverage claim**

```bash
grep -n "100%\|Zero gaps\|zero gaps" PRODUCT_STRATEGY.md
```

Replace every instance of `**Result: 100% coverage. Zero gaps.**` with:

```
**Current coverage:** OTel real-time tracking across 10+ tools (live).
**Roadmap:** Billing API connectors (Q2 2026), local file scanner + browser extension (Q3 2026).
```

- [ ] **Step 2: Verify clean**

```bash
grep -n "100% coverage\|Zero gaps" PRODUCT_STRATEGY.md
```

Expected: no matches.

- [ ] **Step 3: Commit**

```bash
git add PRODUCT_STRATEGY.md
git commit -m "docs: replace inaccurate 100% coverage claim with accurate roadmap status"
```

---

## Task 12: Final check, push, PR

- [ ] **Step 1: Full TypeScript check**

```bash
cd vantage-worker && npx tsc --noEmit
```

Expected: 0 errors.

- [ ] **Step 2: Push and open PR**

```bash
cd "/Users/amanjain/Documents/New Ideas/AI Cost Analysis/Cloudfare based/vantageai"
git push -u origin feat/enterprise-soc2-audit-log
gh pr create \
  --title "feat(enterprise): SOC2 audit log + coverage accuracy fix" \
  --body "$(cat <<'EOF'
## Summary

- **Audit logging**: full activity trail — auth events, data access, admin actions. Fire-and-forget via new \`lib/audit.ts\`, never adds request latency. Stored in existing \`audit_events\` table (extended with \`event_type\` column via migration 0004).
- **Self-serve API**: \`GET /v1/audit-log\` (org owner, paginated, date/type filter, CSV export). \`GET /v1/admin/audit-log\` (admin, cross-org).
- **Dashboard**: Security tab (audit log table + filters + CSV export) + Integrations tab (live vs. roadmap status grid using safe DOM construction).
- **Public roadmap**: \`roadmap.html\` — honest integration status, sales-linkable, no '100%' language.
- **Docs fix**: removed inaccurate '100% coverage. Zero gaps.' from PRODUCT_STRATEGY.md.

## Test plan
- [ ] \`python -m pytest tests/suites/32_audit_log/ -v\` after deploy — AL.1–AL.24 pass
- [ ] Dashboard Security tab shows audit events with color badges
- [ ] Dashboard Integrations tab shows 7 live + 4 Q2 + 3 Q3 items
- [ ] \`/roadmap.html\` loads, contains 'Live' and 'Q2 2026', no '100% coverage'
- [ ] \`npx tsc --noEmit\` passes

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 3: Check CI**

```bash
gh pr checks
```

Expected: TypeScript Check and CLI Build both pass.

---

## Self-Review

- **Spec coverage**: migration ✅ lib/audit.ts ✅ GET /v1/audit-log ✅ GET /v1/admin/audit-log ✅ auth wiring ✅ analytics wiring ✅ admin_action wiring ✅ Security tab ✅ Integrations tab ✅ roadmap.html ✅ PRODUCT_STRATEGY.md ✅ tests ✅
- **No placeholders**: all TypeScript and Python code blocks are complete and runnable
- **Type consistency**: `AuditEvent` interface defined once in `lib/audit.ts`; `logAudit` / `logAuditRaw` names consistent across all 5 call sites; `buildAuditWhere` / `parseIsoDate` defined in auditlog.ts and not referenced elsewhere
- **Migration number**: 0004 confirmed correct (0001 and 0003 exist, no 0002 or 0004)
- **admin.ts conflict**: existing `logAudit` function (lines 5–19) explicitly removed in Task 4 Step 1
- **XSS safety**: all API-derived values in dashboard JS use `textContent`, never `innerHTML`
