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
  if (role !== 'owner' && role !== 'admin') {
    return c.json({ error: 'Owner or admin key required to access audit log' }, 403);
  }

  const orgId     = c.get('orgId');
  const limit     = Math.max(1, Math.min(parseInt(c.req.query('limit') ?? '50', 10), 500));
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
       ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?`
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
