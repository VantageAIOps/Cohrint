import { Context, Next } from 'hono';
import { Bindings, Variables } from '../types';

// ── SHA-256 helper ────────────────────────────────────────────────────────────
export async function sha256hex(text: string): Promise<string> {
  const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
  return Array.from(new Uint8Array(buf)).map(b => b.toString(16).padStart(2, '0')).join('');
}

// ── Rate limiter (token bucket via KV) ───────────────────────────────────────
async function checkRateLimit(kv: KVNamespace, orgId: string, limitRpm: number): Promise<boolean> {
  const key   = `rl:${orgId}:${Math.floor(Date.now() / 60_000)}`;
  const raw   = await kv.get(key);
  const count = raw ? parseInt(raw, 10) : 0;
  if (count >= limitRpm) return false;
  kv.put(key, String(count + 1), { expirationTtl: 70 });
  return true;
}

// ── Auth middleware ───────────────────────────────────────────────────────────
// Key format: vnt_{orgId}_{randomHex}
// Lookup order:
//   1. orgs table         → role = 'owner', scopeTeam = null
//   2. org_members table  → role = member.role, scopeTeam = member.scope_team
export async function authMiddleware(
  c: Context<{ Bindings: Bindings; Variables: Variables }>,
  next: Next,
) {
  const authHeader = c.req.header('Authorization') ?? '';
  const apiKey = authHeader.startsWith('Bearer ') ? authHeader.slice(7).trim() : '';

  if (!apiKey || !apiKey.startsWith('vnt_')) {
    return c.json({ error: 'Missing or invalid API key. Expected: Bearer vnt_...' }, 401);
  }

  const parts  = apiKey.split('_');
  const orgId  = parts.length >= 3 ? parts[1] : '';

  if (!orgId) {
    return c.json({ error: 'Malformed API key — cannot extract org ID' }, 401);
  }

  const hash = await sha256hex(apiKey);

  // 1. Check owner key (orgs table)
  const org = await c.env.DB.prepare(
    'SELECT id, plan FROM orgs WHERE api_key_hash = ?'
  ).bind(hash).first<{ id: string; plan: string }>();

  if (org) {
    c.set('orgId',     org.id);
    c.set('role',      'owner');
    c.set('scopeTeam', null);
    c.set('memberId',  null);
  } else {
    // 2. Check member key (org_members table)
    const member = await c.env.DB.prepare(
      'SELECT id, org_id, role, scope_team FROM org_members WHERE api_key_hash = ?'
    ).bind(hash).first<{ id: string; org_id: string; role: string; scope_team: string | null }>();

    if (!member) {
      const isDevKey = c.env.ENVIRONMENT !== 'production';
      if (isDevKey) {
        // Dev convenience: auto-provision org on first use
        await c.env.DB.prepare(
          'INSERT OR IGNORE INTO orgs (id, api_key_hash, name, plan) VALUES (?, ?, ?, ?)'
        ).bind(orgId, hash, orgId, 'free').run();
        c.set('orgId',     orgId);
        c.set('role',      'owner');
        c.set('scopeTeam', null);
        c.set('memberId',  null);
      } else {
        return c.json({ error: 'API key not found. Sign up at vantageaiops.com' }, 401);
      }
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
