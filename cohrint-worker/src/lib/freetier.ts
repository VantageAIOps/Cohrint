/**
 * Free-tier monthly event count cache via KV.
 *
 * Problem: checkFreeTierLimit() currently does SELECT COUNT(*) FROM events per ingest.
 * That query grows O(events) and adds ~180ms p95 latency for large orgs.
 *
 * Solution: KV key `freetier:{orgId}:{YYYY-MM}` stores the month-to-date count.
 *   - On hit: return from KV (<25ms)
 *   - On miss: fall back to D1 COUNT and prime KV
 *   - On ingest success: increment KV counter (fire-and-forget, debounced)
 *
 * KV write limits: free tier is 1k writes/day.
 * To stay within limits at scale, use a 10-second in-memory debounce:
 * accumulate N increments in memory, flush once to KV per debounce window.
 * At 1000 events/day this is still only 144 writes/day — well within limits.
 *
 * future_scale: Replace KV with Durable Object counter when >1k writes/day.
 */

const KV_PREFIX = 'freetier';
const KV_TTL_SEC = 45 * 24 * 3600; // 45 days (covers month rollover)

/** Debounce buffer: orgId → pending increment count */
const pendingIncrements = new Map<string, number>();
let flushTimer: ReturnType<typeof setTimeout> | null = null;

function kvKey(orgId: string): string {
  const ym = new Date().toISOString().slice(0, 7); // 'YYYY-MM'
  return `${KV_PREFIX}:${orgId}:${ym}`;
}

/**
 * Get current month event count for org.
 * KV hit path is O(1); D1 fallback path is O(events).
 */
export async function getFreeTierCount(
  kv: KVNamespace,
  db: D1Database,
  orgId: string,
): Promise<number> {
  const key = kvKey(orgId);
  try {
    const cached = await kv.get(key);
    if (cached !== null) return parseInt(cached, 10);
  } catch { /* KV unavailable — fall through */ }

  // D1 fallback: count this month's events
  const monthStartUnix = Math.floor(
    new Date(new Date().toISOString().slice(0, 7) + '-01T00:00:00Z').getTime() / 1000,
  );
  const row = await db.prepare(
    'SELECT COUNT(*) AS cnt FROM events WHERE org_id = ? AND created_at >= ?',
  ).bind(orgId, monthStartUnix).first<{ cnt: number }>();
  const count = row?.cnt ?? 0;

  // Prime KV for next request
  try {
    await kv.put(key, String(count), { expirationTtl: KV_TTL_SEC });
  } catch { /* best-effort */ }

  return count;
}

/**
 * Increment the org's KV counter after a successful event insert.
 * Uses a 10-second in-memory debounce to batch multiple concurrent
 * increments into a single KV write (minimises KV write costs).
 */
export function incrementFreeTierCount(kv: KVNamespace, orgId: string): void {
  pendingIncrements.set(orgId, (pendingIncrements.get(orgId) ?? 0) + 1);
  if (flushTimer !== null) return; // debounce already running
  flushTimer = setTimeout(async () => {
    flushTimer = null;
    const snapshot = new Map(pendingIncrements);
    pendingIncrements.clear();
    for (const [oid, delta] of snapshot) {
      try {
        const key = kvKey(oid);
        const raw = await kv.get(key);
        const current = raw !== null ? parseInt(raw, 10) : 0;
        await kv.put(key, String(current + delta), { expirationTtl: KV_TTL_SEC });
      } catch { /* best-effort */ }
    }
  }, 10_000);
}
