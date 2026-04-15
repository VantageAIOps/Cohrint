import { Context, Next } from 'hono';
import { Bindings, Variables, OrgRole } from '../types';
import { logAudit, logAuditRaw } from '../lib/audit';

// ── Role hierarchy ────────────────────────────────────────────────────────────
// Higher index = higher privilege
const ROLE_RANK: Record<OrgRole, number> = {
  viewer:     0,
  member:     1,
  admin:      2,
  ceo:        3,
  superadmin: 4,
  owner:      5,
};

/** Returns true if `role` meets or exceeds the required minimum role. */
export function hasRole(role: string, minimum: OrgRole): boolean {
  return (ROLE_RANK[role as OrgRole] ?? -1) >= ROLE_RANK[minimum];
}

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
    await kv.put(key, String(count + 1), { expirationTtl: 70 });
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
//   1. Session cookie (cohrint_session)  → dashboard UI
//   2. Authorization: Bearer crt_...     → SDK / API
export async function authMiddleware(
  c: Context<{ Bindings: Bindings; Variables: Variables }>,
  next: Next,
) {
  // ── 1. Session cookie auth ────────────────────────────────────────────────
  const cookieHeader = c.req.header('Cookie') ?? '';
  const sessionToken = parseCookie(cookieHeader, 'cohrint_session')
    ?? parseCookie(cookieHeader, 'vantage_session');

  if (sessionToken) {
    const session = await c.env.DB.prepare(
      'SELECT org_id, role, member_id FROM sessions WHERE token = ? AND expires_at > unixepoch()'
    ).bind(sessionToken).first<{ org_id: string; role: string; member_id: string | null }>();

    if (session) {
      let scopeTeam: string | null = null;
      let memberEmail: string | null = null;
      if (session.member_id) {
        const m = await c.env.DB.prepare(
          'SELECT scope_team, email FROM org_members WHERE id = ?'
        ).bind(session.member_id).first<{ scope_team: string | null; email: string | null }>();
        scopeTeam   = m?.scope_team ?? null;
        memberEmail = m?.email ?? null;
      }
      c.set('orgId',       session.org_id);
      c.set('role',        (session.role as OrgRole) || 'member');
      c.set('scopeTeam',   scopeTeam);
      c.set('memberId',    session.member_id);
      c.set('memberEmail', memberEmail);

      // Resolve accountType for session
      const orgMeta = await c.env.DB.prepare(
        'SELECT account_type FROM orgs WHERE id = ?'
      ).bind(session.org_id).first<{ account_type: string }>();
      c.set('accountType', (orgMeta?.account_type ?? 'organization') as import('../types').AccountType);

      // Resolve teamId if member has one
      let sessionTeamId: string | null = null;
      if (session.member_id) {
        const tm = await c.env.DB.prepare(
          'SELECT team_id FROM org_members WHERE id = ?'
        ).bind(session.member_id).first<{ team_id: string | null }>();
        sessionTeamId = tm?.team_id ?? null;
      }
      c.set('teamId', sessionTeamId);

      const rpm     = parseInt(c.env.RATE_LIMIT_RPM ?? '1000', 10);
      const allowed = await checkRateLimit(c.env.KV, session.org_id, rpm);
      if (!allowed) {
        const retryAt = Math.ceil(Date.now() / 60_000) * 60;
        c.header('Retry-After', String(retryAt - Math.floor(Date.now() / 1000)));
        return c.json({ error: 'Rate limit exceeded', retry_after: retryAt }, 429);
      }
      logAudit(c, { event_type: 'auth', event_name: 'auth.login', resource_type: 'session',
        metadata: { method: 'session', ua: (c.req.header('User-Agent') ?? '').slice(0, 80) } });
      return await next();
    }
    // Expired / invalid session — fall through to API key check
  }

  // ── 2. Bearer API key auth ────────────────────────────────────────────────
  const authHeader = c.req.header('Authorization') ?? '';
  const apiKey = authHeader.startsWith('Bearer ') ? authHeader.slice(7).trim() : '';

  if (!apiKey || (!apiKey.startsWith('vnt_') && !apiKey.startsWith('crt_'))) {
    const ip = c.req.header('CF-Connecting-IP') ?? c.req.header('X-Forwarded-For') ?? '';
    logAuditRaw(c.env.DB, c.executionCtx, ip, 'unknown', 'unknown', 'unknown', {
      event_type: 'auth',
      event_name: 'auth.failed',
      metadata: { reason: 'missing_or_malformed_key', path: c.req.path },
    });
    return c.json({ error: 'Missing or invalid API key. Expected: Bearer crt_...' }, 401);
  }

  const parts = apiKey.split('_');
  const orgId = parts.length >= 3 ? parts[1] : '';

  if (!orgId) {
    return c.json({ error: 'Malformed API key — cannot extract org ID' }, 401);
  }

  const hash = await sha256hex(apiKey);

  // 2a. Check owner key (orgs table)
  const org = await c.env.DB.prepare(
    'SELECT id, plan, account_type FROM orgs WHERE api_key_hash = ?'
  ).bind(hash).first<{ id: string; plan: string; account_type: string }>();

  if (org) {
    c.set('orgId',       org.id);
    c.set('role',        'owner' as OrgRole);
    c.set('accountType', (org.account_type ?? 'organization') as import('../types').AccountType);
    c.set('scopeTeam',   null);
    c.set('teamId',      null);
    c.set('memberId',    null);
    c.set('memberEmail', null);
  } else {
    // 2b. Check member key (org_members table)
    const member = await c.env.DB.prepare(
      'SELECT id, org_id, role, scope_team, email, team_id FROM org_members WHERE api_key_hash = ?'
    ).bind(hash).first<{ id: string; org_id: string; role: string; scope_team: string | null; email: string | null; team_id: string | null }>();

    if (!member) {
      const ip = c.req.header('CF-Connecting-IP') ?? c.req.header('X-Forwarded-For') ?? '';
      logAuditRaw(c.env.DB, c.executionCtx, ip, orgId || 'unknown',
        `key:${hash.substring(0, 8)}`, 'unknown', {
          event_type: 'auth',
          event_name: 'auth.failed',
          metadata: { reason: 'key_not_found', path: c.req.path },
        });
      return c.json({ error: 'API key not found. Sign up at cohrint.com' }, 401);
    } else {
      c.set('orgId',       member.org_id);
      c.set('role',        (member.role as OrgRole) || 'member');
      c.set('scopeTeam',   member.scope_team ?? null);
      c.set('teamId',      member.team_id ?? null);
      c.set('memberId',    member.id);
      c.set('memberEmail', member.email ?? null);

      const orgMeta2 = await c.env.DB.prepare(
        'SELECT account_type FROM orgs WHERE id = ?'
      ).bind(member.org_id).first<{ account_type: string }>();
      c.set('accountType', (orgMeta2?.account_type ?? 'organization') as import('../types').AccountType);
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

  // Don't log auth.login for audit-log reads — it would shift offset pagination
  if (!c.req.path.startsWith('/v1/audit-log')) {
    logAudit(c, { event_type: 'auth', event_name: 'auth.login', resource_type: 'api_key',
      metadata: { method: 'api_key', role: c.get('role'), ua: (c.req.header('User-Agent') ?? '').slice(0, 80) } });
  }
  return await next();
}

// ── Role guards — call after authMiddleware ───────────────────────────────────

/** Allows: owner, superadmin, ceo, admin */
export async function adminOnly(
  c: Context<{ Bindings: Bindings; Variables: Variables }>,
  next: Next,
) {
  if (!hasRole(c.get('role'), 'admin')) {
    return c.json({ error: 'Admin access required' }, 403);
  }
  return await next();
}

/** Allows: owner, superadmin, ceo only */
export async function executiveOnly(
  c: Context<{ Bindings: Bindings; Variables: Variables }>,
  next: Next,
) {
  if (!hasRole(c.get('role'), 'ceo')) {
    return c.json({ error: 'Executive access required (ceo or above)' }, 403);
  }
  return await next();
}

/** Allows: owner, superadmin only */
export async function superadminOnly(
  c: Context<{ Bindings: Bindings; Variables: Variables }>,
  next: Next,
) {
  if (!hasRole(c.get('role'), 'superadmin')) {
    return c.json({ error: 'Superadmin access required' }, 403);
  }
  return await next();
}
