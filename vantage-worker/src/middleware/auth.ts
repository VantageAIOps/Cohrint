import { Context, Next } from 'hono';
import { Bindings, Variables } from '../types';

// ── SHA-256 helper ────────────────────────────────────────────────────────────
async function sha256hex(text: string): Promise<string> {
  const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
  return Array.from(new Uint8Array(buf)).map(b => b.toString(16).padStart(2, '0')).join('');
}

// ── Rate limiter (token bucket via KV) ───────────────────────────────────────
async function checkRateLimit(kv: KVNamespace, orgId: string, limitRpm: number): Promise<boolean> {
  const key   = `rl:${orgId}:${Math.floor(Date.now() / 60_000)}`;
  const raw   = await kv.get(key);
  const count = raw ? parseInt(raw, 10) : 0;
  if (count >= limitRpm) return false;
  // Increment — fire-and-forget, 70s TTL covers the full minute + buffer
  kv.put(key, String(count + 1), { expirationTtl: 70 });
  return true;
}

// ── Auth middleware ───────────────────────────────────────────────────────────
export async function authMiddleware(
  c: Context<{ Bindings: Bindings; Variables: Variables }>,
  next: Next,
) {
  const authHeader = c.req.header('Authorization') ?? '';
  const apiKey = authHeader.startsWith('Bearer ') ? authHeader.slice(7).trim() : '';

  if (!apiKey || !apiKey.startsWith('vnt_')) {
    return c.json({ error: 'Missing or invalid API key. Expected: Bearer vnt_...' }, 401);
  }

  // Parse org from key: vnt_{orgId}_{random}
  const parts = apiKey.split('_');
  const orgId = parts.length >= 3 ? parts[1] : '';

  if (!orgId) {
    return c.json({ error: 'Malformed API key — cannot extract org ID' }, 401);
  }

  // Verify key exists in D1 (check hash)
  const hash = await sha256hex(apiKey);
  const org  = await c.env.DB.prepare('SELECT id, plan FROM orgs WHERE api_key_hash = ?')
    .bind(hash)
    .first<{ id: string; plan: string }>();

  if (!org) {
    // Auto-provision org on first use (development convenience)
    // In production, replace this with a hard rejection
    const isDevKey = c.env.ENVIRONMENT !== 'production';
    if (isDevKey) {
      await c.env.DB.prepare(
        'INSERT OR IGNORE INTO orgs (id, api_key_hash, name, plan) VALUES (?, ?, ?, ?)'
      ).bind(orgId, hash, orgId, 'free').run();
    } else {
      return c.json({ error: 'API key not found. Sign up at vantageai.pages.dev' }, 401);
    }
  }

  // Rate limit
  const rpm = parseInt(c.env.RATE_LIMIT_RPM ?? '1000', 10);
  const allowed = await checkRateLimit(c.env.KV, orgId, rpm);
  if (!allowed) {
    const retryAt = Math.ceil(Date.now() / 60_000) * 60;
    c.header('Retry-After', String(retryAt - Math.floor(Date.now() / 1000)));
    c.header('X-RateLimit-Limit', String(rpm));
    c.header('X-RateLimit-Remaining', '0');
    return c.json({ error: 'Rate limit exceeded', retry_after: retryAt }, 429);
  }

  c.set('orgId', orgId);
  await next();
}
