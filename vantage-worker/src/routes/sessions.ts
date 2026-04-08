import { Hono } from 'hono';
import { Bindings, Variables } from '../types';
import { authMiddleware } from '../middleware/auth';

const sessions = new Hono<{ Bindings: Bindings; Variables: Variables }>();

sessions.use('*', authMiddleware);

// ── GET /v1/sessions ──────────────────────────────────────────────────────────
sessions.get('/', async (c) => {
  const orgId: string = c.get('orgId');

  const limit         = Math.min(parseInt(c.req.query('limit')          ?? '20', 10), 100);
  const provider      = c.req.query('provider');
  const developerEmail = c.req.query('developer_email');
  const from          = c.req.query('from'); // ISO date string filter on last_seen_at

  const conditions: string[] = ['org_id = ?'];
  const params: (string | number)[] = [orgId];

  if (provider)        { conditions.push('provider = ?');        params.push(provider); }
  if (developerEmail)  { conditions.push('developer_email = ?'); params.push(developerEmail); }
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
    console.error('[sessions] query error:', err);
    return c.json({ error: 'Failed to query sessions' }, 500);
  }
});

export { sessions };
