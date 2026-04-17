import { Hono } from 'hono';
import type { Bindings, Variables } from '../types';
import { authMiddleware, hasRole } from '../middleware/auth';
import { logAudit } from '../lib/audit';

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
  if (orgId !== null)  { conditions.push('org_id = ?');      bindings.push(orgId); }
  if (eventType)       { conditions.push('event_type = ?');  bindings.push(eventType); }
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

// ── GET / — org owner / admin self-serve ──────────────────────────────────────

auditlog.get('/', async (c) => {
  const role = c.get('role');
  if (!hasRole(role, 'admin')) {
    return c.json({ error: 'Owner or admin key required to access audit log' }, 403);
  }

  const orgId     = c.get('orgId');
  const limit     = Math.max(1, Math.min(parseInt(c.req.query('limit') ?? '50', 10), 500));
  const offset    = Math.max(0, parseInt(c.req.query('offset') ?? '0', 10));
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
       ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?`
    ).bind(...bindings, limit, offset),
    c.env.DB.prepare(
      `SELECT COUNT(*) AS total FROM audit_events WHERE ${where}`
    ).bind(...bindings),
  ]);

  const events = rows.results as Record<string, unknown>[];
  const total  = (countRow.results?.[0] as { total: number } | undefined)?.total ?? 0;

  if (format === 'csv') {
    logAudit(c, {
      event_type:    'data_access',
      event_name:    'audit_log.exported',
      resource_type: 'audit_log',
      metadata:      { rows: events.length, event_type: eventType ?? 'all', from: c.req.query('from'), to: c.req.query('to') },
    });
    return csvResponse(orgId, events);
  }

  return c.json({ events, total, has_more: offset + events.length < total });
});

// ── GET /verify — compare D1 row against R2 backup ───────────────────────────

auditlog.get('/verify', async (c) => {
  const role = c.get('role');
  if (!hasRole(role, 'admin')) {
    return c.json({ error: 'Admin or above required' }, 403);
  }

  const orgId = c.get('orgId');
  const id    = c.req.query('id');
  if (!id) return c.json({ error: 'id query param required' }, 400);

  // Fetch D1 row
  const row = await c.env.DB
    .prepare(`SELECT id, org_id, actor_email, actor_role, action, resource, detail,
                     ip_address, event_type,
                     datetime(created_at, 'unixepoch') AS created_at
              FROM audit_events WHERE id = ? AND org_id = ?`)
    .bind(id, orgId)
    .first<Record<string, unknown>>();

  if (!row) return c.json({ error: 'audit event not found' }, 404);

  if (!c.env.CACHE_BUCKET) {
    return c.json({ consistent: null, id, reason: 'R2 not available — cannot verify' });
  }

  // R2 key format: audit/{orgId}/{YYYY-MM-DD}/{timestamp-rand}.json
  // We list objects under audit/{orgId}/ and find one whose JSON matches the row id.
  // For a targeted lookup we scan the day prefix derived from created_at.
  const createdAt = String(row['created_at'] ?? '');
  const dayPrefix = createdAt.slice(0, 10); // YYYY-MM-DD
  const prefix    = `audit/${orgId}/${dayPrefix}/`;

  let consistent = false;
  let r2Found    = false;
  try {
    const listed = await c.env.CACHE_BUCKET.list({ prefix, limit: 1000 });
    for (const obj of listed.objects) {
      const r2Obj = await c.env.CACHE_BUCKET.get(obj.key);
      if (!r2Obj) continue;
      const r2Data = await r2Obj.json<Record<string, unknown>>();
      // Match on event_name + detail (id is not written to R2, but detail + actor are unique enough)
      if (
        r2Data['event_name'] === row['action'] &&
        r2Data['detail']     === row['detail'] &&
        r2Data['actor_id']   === (row['actor_email'] ?? '') &&
        r2Data['actor_role'] === row['actor_role']
      ) {
        r2Found    = true;
        consistent = true;
        break;
      }
    }
  } catch (err) {
    console.warn('[audit/verify] R2 list/get failed', err);
    return c.json({ consistent: null, id, reason: 'R2 read error' });
  }

  if (!r2Found) {
    // Could be a pre-T014 event or the day prefix differs; report as unverifiable
    return c.json({ consistent: false, id, reason: 'No matching R2 object found for this event' });
  }

  return c.json({ consistent, id });
});

// ── GET /export — admin+ CSV export with date range ──────────────────────────

auditlog.get('/export', async (c) => {
  const role = c.get('role');
  if (!hasRole(role, 'admin')) {
    return c.json({ error: 'Admin or above required' }, 403);
  }

  const orgId     = c.get('orgId');
  const format    = c.req.query('format') ?? 'csv';
  const eventType = c.req.query('event_type') ?? null;
  const from      = parseIsoDate(c.req.query('from'));
  const to        = parseIsoDate(c.req.query('to'), true);

  const { where, bindings } = buildAuditWhere(orgId, eventType, from, to);

  const result = await c.env.DB
    .prepare(
      `SELECT id, actor_email, actor_role, action, resource, detail,
              ip_address, event_type,
              datetime(created_at, 'unixepoch') AS created_at
       FROM audit_events WHERE ${where}
       ORDER BY created_at DESC, id DESC LIMIT 10000`
    )
    .bind(...bindings)
    .all<Record<string, unknown>>();

  const events = result.results;

  logAudit(c, {
    event_type:    'data_access',
    event_name:    'audit_log.exported',
    resource_type: 'audit_log',
    metadata:      { rows: events.length, format, event_type: eventType ?? 'all', from: c.req.query('from'), to: c.req.query('to') },
  });

  if (format === 'json') {
    return c.json({ events, total: events.length });
  }

  // Default: CSV
  return csvResponse(orgId, events);
});

// ── CSV helper ────────────────────────────────────────────────────────────────

function csvResponse(orgId: string, events: Record<string, unknown>[]): Response {
  const header = 'id,org_id,actor_email,actor_role,event_type,action,resource,detail,ip_address,created_at\n';
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
