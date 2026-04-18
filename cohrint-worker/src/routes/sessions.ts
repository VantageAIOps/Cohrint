import { Hono } from 'hono';
import { Bindings, Variables } from '../types';
import { authMiddleware, hasRole } from '../middleware/auth';
import { createLogger } from '../lib/logger';

const sessions = new Hono<{ Bindings: Bindings; Variables: Variables }>();

sessions.use('*', authMiddleware);

// ── GET /v1/sessions ──────────────────────────────────────────────────────────
sessions.get('/', async (c) => {
  const orgId: string  = c.get('orgId');
  const role           = c.get('role') as string;
  const memberEmail    = c.get('memberEmail') as string | undefined;
  const isPrivileged   = hasRole(role, 'admin');

  const limit         = Math.min(parseInt(c.req.query('limit') ?? '20', 10), 100);
  const provider      = c.req.query('provider');
  const developerEmail = c.req.query('developer_email');
  const from          = c.req.query('from');

  // Validate from param: must be YYYY-MM-DD or YYYY-MM-DD HH:MM:SS (TEXT column)
  if (from && !/^\d{4}-\d{2}-\d{2}( \d{2}:\d{2}:\d{2})?$/.test(from)) {
    return c.json({ error: 'from must be YYYY-MM-DD or YYYY-MM-DD HH:MM:SS' }, 400);
  }

  const conditions: string[] = ['org_id = ?'];
  const params: (string | number)[] = [orgId];

  if (provider)        { conditions.push('provider = ?');        params.push(provider); }
  // Non-admins are scoped to their own sessions only
  if (isPrivileged) {
    if (developerEmail) { conditions.push('developer_email = ?'); params.push(developerEmail); }
  } else {
    conditions.push('developer_email = ?');
    params.push(memberEmail ?? '');
  }
  if (from)            { conditions.push('last_seen_at >= ?');   params.push(from); }

  const where = conditions.join(' AND ');

  try {
    const result = await c.env.DB.prepare(`
      SELECT session_id, provider, developer_email, team, model,
             input_tokens, output_tokens, cached_tokens, cost_usd,
             event_count, first_seen_at, last_seen_at
      FROM otel_sessions
      WHERE ${where}
      ORDER BY last_seen_at DESC
      LIMIT ?
    `).bind(...params, limit).all();

    const countResult = await c.env.DB.prepare(`
      SELECT COUNT(*) as total FROM otel_sessions WHERE ${where}
    `).bind(...params).first<{ total: number }>();

    return c.json({
      sessions: result.results,
      total: countResult?.total ?? 0,
    });
  } catch (err) {
    createLogger(c.get('requestId'), c.get('orgId')).error('sessions query failed', { err: err instanceof Error ? err : new Error(String(err)) });
    return c.json({ error: 'Failed to query sessions' }, 500);
  }
});

export { sessions };
