import { Context, Next } from 'hono';
import type { Bindings, Variables } from '../types';
import { emitMetric } from '../lib/metrics';

// Default limits (configurable via env vars in wrangler.toml)
const DEFAULT_KEY_RPM = 200;

/**
 * Per-API-key + per-org rate limit middleware.
 *
 * Checks both:
 *   rl:key:{keyHashPrefix8}:{minuteBucket} — per key, default 200 RPM
 *   rl:org:{orgId}:{minuteBucket}          — per org, default 1000 RPM
 *
 * Adds response headers:
 *   X-RateLimit-Limit-Key, X-RateLimit-Remaining-Key
 *   X-RateLimit-Limit-Org, X-RateLimit-Remaining-Org
 *
 * future_scale: Replace KV with Durable Object for accurate rolling windows.
 */
export async function perKeyRateLimit(
  c: Context<{ Bindings: Bindings; Variables: Variables }>,
  next: Next,
): Promise<void | Response> {
  const kv    = c.env.KV;
  const orgId = c.get('orgId');
  // apiKeyHashPrefix is not in Variables yet — derive from Authorization header
  const authHeader = c.req.header('Authorization') ?? '';
  const rawKey = authHeader.startsWith('Bearer ') ? authHeader.slice(7) : authHeader;
  // Use first 8 chars of raw key as prefix (not a security-sensitive operation; just bucketing)
  const keyPrefix = rawKey.slice(0, 8) || 'anon';

  const keyLimitRpm = parseInt(c.env.RATE_LIMIT_RPM ?? String(DEFAULT_KEY_RPM), 10);
  const orgLimitRpm = keyLimitRpm * 5; // org limit = 5× key limit
  const minuteBucket = Math.floor(Date.now() / 60_000);

  const keyKvKey = `rl:key:${keyPrefix}:${minuteBucket}`;
  const orgKvKey = `rl:org:${orgId}:${minuteBucket}`;

  // Read both counters in parallel
  const [keyRaw, orgRaw] = await Promise.all([
    kv.get(keyKvKey).catch(() => null),
    kv.get(orgKvKey).catch(() => null),
  ]);

  const keyCount = parseInt(keyRaw ?? '0', 10);
  const orgCount = parseInt(orgRaw ?? '0', 10);

  // Set rate limit headers (before checking — always informative)
  c.header('X-RateLimit-Limit-Key',      String(keyLimitRpm));
  c.header('X-RateLimit-Limit-Org',      String(orgLimitRpm));
  c.header('X-RateLimit-Remaining-Key',  String(Math.max(0, keyLimitRpm - keyCount - 1)));
  c.header('X-RateLimit-Remaining-Org',  String(Math.max(0, orgLimitRpm - orgCount - 1)));

  if (keyCount >= keyLimitRpm) {
    emitMetric(c.env.METRICS, { event: 'ratelimit.rejected', orgId });
    return c.json({ error: 'Per-key rate limit exceeded', retry_after_seconds: 60 }, 429);
  }
  if (orgCount >= orgLimitRpm) {
    emitMetric(c.env.METRICS, { event: 'ratelimit.rejected', orgId });
    return c.json({ error: 'Org rate limit exceeded', retry_after_seconds: 60 }, 429);
  }

  // Increment both counters (fire-and-forget, 70s TTL for the bucket)
  Promise.all([
    kv.put(keyKvKey, String(keyCount + 1), { expirationTtl: 70 }).catch(() => null),
    kv.put(orgKvKey, String(orgCount + 1), { expirationTtl: 70 }).catch(() => null),
  ]);

  return next();
}
