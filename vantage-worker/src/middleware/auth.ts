import { Context, Next } from 'hono';
import { Bindings, Variables } from '../types';
import { logAudit, logAuditRaw } from '../lib/audit';

// ── SHA-256 helper ────────────────────────────────────────────────────────────
export async function sha256hex(text: string): Promise<string> {
  const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
  return Array.from(new Uint8Array(buf)).map(b => b.toString(16).padStart(2, '0')).join('');
}

// ── Rate limiter (token bucket via KV, with graceful degradation) ────────────
async function checkRateLimit(kv: KVNamespace, orgId: string, limitRpm: number): Promise<boolean> {
  try {
    const key   = `rl:${orgId}:${Math.floor(Date.now() / 60_000)}`;
    const raw   = await kv.get(key);
    const count = raw ? parseInt(raw, 10) : 0;
    if (count >= limitRpm) return false;
    kv.put(key, String(count + 1), { expirationTtl: 70 });
  } catch {
    // KV unavailable or quota exceeded — allow request through
  }
  return true;
}

// ── Cookie parser helper ──────────────────────────────────────────────────────
function parseCookie(header: string, name: string): string | null {
  for (const part of header.split(';')) {
    const [k, v] = part.trim().split('=');
    if (k === name) return v ?? null;
  }
  return null;
}

// ── Auth middleware ───────────────────────────────────────────────────────────
// Lookup order:
//   1. Session cookie (vantage_session)  → dashboard UI
//   2. Authorization: Bearer vnt_...     → SDK / API
export async function authMiddleware(
  c: Context<{ Bindings: Bindings; Variables: Variables }>,
  next: Next,
) {
  // ── 1. Session cookie auth ────────────────────────────────────────────────
  const cookieHeader = c.req.header('Cookie') ?? '';
  const sessionToken = parseCookie(cookieHeader, 'vantage_session');

  if (sessionToken) {
    const session = await c.env.DB.prepare(
      'SELECT org_id, role, member_id FROM sessions WHERE token = ? AND expires_at > unixepoch()'
    ).bind(sessionToken).first<{ org_id: string; role: string; member_id: string | null }>();

    if (session) {
      let scopeTeam: string | null = null;
      if (session.member_id) {
        const m = await c.env.DB.prepare(
          'SELECT scope_team FROM org_members WHERE id = ?'
        ).bind(session.member_id).first<{ scope_team: string | null }>();
        scopeTeam = m?.scope_team ?? null;
      }
      c.set('orgId',     session.org_id);
      c.set('role',      session.role);
      c.set('scopeTeam', scopeTeam);
      c.set('memberId',  session.member_id);

      const rpm     = parseInt(c.env.RATE_LIMIT_RPM ?? '1000', 10);
      const allowed = await checkRateLimit(c.env.KV, session.org_id, rpm);
      if (!allowed) {
        const retryAt = Math.ceil(Date.now() / 60_000) * 60;
        c.header('Retry-After', String(retryAt - Math.floor(Date.now() / 1000)));
        return c.json({ error: 'Rate limit exceeded', retry_after: retryAt }, 429);
      }
      logAudit(c, { event_type: 'auth', event_name: 'auth.login', resource_type: 'session' });
      return await next();
    }
    // Expired / invalid session — fall through to API key check
  }

  // ── 2. Bearer API key auth ────────────────────────────────────────────────
  const authHeader = c.req.header('Authorization') ?? '';
  const apiKey = authHeader.startsWith('Bearer ') ? authHeader.slice(7).trim() : '';

  if (!apiKey || !apiKey.startsWith('vnt_')) {
    const ip = c.req.header('CF-Connecting-IP') ?? c.req.header('X-Forwarded-For') ?? '';
    logAuditRaw(c.env.DB, c.executionCtx, ip, 'unknown', 'unknown', 'unknown', {
      event_type: 'auth',
      event_name: 'auth.failed',
      metadata: { reason: 'missing_or_malformed_key', path: c.req.path },
    });
    return c.json({ error: 'Missing or invalid API key. Expected: Bearer vnt_...' }, 401);
  }

  const parts = apiKey.split('_');
  const orgId = parts.length >= 3 ? parts[1] : '';

  if (!orgId) {
    return c.json({ error: 'Malformed API key — cannot extract org ID' }, 401);
  }

  const hash = await sha256hex(apiKey);

  // 2a. Check owner key (orgs table)
  const org = await c.env.DB.prepare(
    'SELECT id, plan FROM orgs WHERE api_key_hash = ?'
  ).bind(hash).first<{ id: string; plan: string }>();

  if (org) {
    c.set('orgId',     org.id);
    c.set('role',      'owner');
    c.set('scopeTeam', null);
    c.set('memberId',  null);
  } else {
    // 2b. Check member key (org_members table)
    const member = await c.env.DB.prepare(
      'SELECT id, org_id, role, scope_team FROM org_members WHERE api_key_hash = ?'
    ).bind(hash).first<{ id: string; org_id: string; role: string; scope_team: string | null }>();

    if (!member) {
      const ip = c.req.header('CF-Connecting-IP') ?? c.req.header('X-Forwarded-For') ?? '';
      logAuditRaw(c.env.DB, c.executionCtx, ip, orgId || 'unknown',
        `key:${hash.substring(0, 8)}`, 'unknown', {
          event_type: 'auth',
          event_name: 'auth.failed',
          metadata: { reason: 'key_not_found', path: c.req.path },
        });
      return c.json({ error: 'API key not found. Sign up at vantageaiops.com' }, 401);
    } else {
      c.set('orgId',     member.org_id);
      c.set('role',      member.role);
      c.set('scopeTeam', member.scope_team ?? null);
      c.set('memberId',  member.id);
    }
  }

  // Rate limit (keyed to org, shared across all members)
  const rpm     = parseInt(c.env.RATE_LIMIT_RPM ?? '1000', 10);
  const allowed = await checkRateLimit(c.env.KV, c.get('orgId'), rpm);
  if (!allowed) {
    const retryAt = Math.ceil(Date.now() / 60_000) * 60;
    c.header('Retry-After', String(retryAt - Math.floor(Date.now() / 1000)));
    c.header('X-RateLimit-Limit', String(rpm));
    c.header('X-RateLimit-Remaining', '0');
    return c.json({ error: 'Rate limit exceeded', retry_after: retryAt }, 429);
  }

  logAudit(c, { event_type: 'auth', event_name: 'auth.login', resource_type: 'api_key' });
  return await next();
}

// ── Admin-only guard — call after authMiddleware ──────────────────────────────
export async function adminOnly(
  c: Context<{ Bindings: Bindings; Variables: Variables }>,
  next: Next,
) {
  const role = c.get('role');
  if (role !== 'owner' && role !== 'admin') {
    return c.json({ error: 'Admin access required' }, 403);
  }
  return await next();
}
