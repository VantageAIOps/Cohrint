/**
 * Distributed cron lock via KV.
 *
 * Prevents duplicate cron executions when Cloudflare restarts a Worker
 * under a running cron tick. KV is eventually consistent with ~60s global
 * propagation, so this is best-effort (not strongly consistent).
 *
 * Usage:
 *   const lock = await acquireLock(env.KV, 'copilot-sync', 300);
 *   if (!lock) return; // another instance holds the lock
 *   try { await doWork(); } finally { await lock.release(); }
 *
 * future_scale: Replace with Durable Object for strongly-consistent state.
 */

const LOCK_PREFIX = 'cronlock:';

export interface CronLock {
  release(): Promise<void>;
}

/**
 * Try to acquire a named cron lock for `ttlSec` seconds.
 * Returns null if lock is held by another instance.
 */
export async function acquireLock(
  kv: KVNamespace,
  name: string,
  ttlSec = 300,
): Promise<CronLock | null> {
  const key = `${LOCK_PREFIX}${name}`;
  const owner = crypto.randomUUID();

  // Check if already locked
  const existing = await kv.get(key);
  if (existing !== null) return null;

  // Write our owner token
  await kv.put(key, owner, { expirationTtl: ttlSec });

  // Re-read to confirm we won (best-effort eventual consistency check)
  const confirmed = await kv.get(key);
  if (confirmed !== owner) return null;

  return {
    release: async () => {
      try {
        // Only delete if we still own it
        const current = await kv.get(key);
        if (current === owner) await kv.delete(key);
      } catch { /* best-effort */ }
    },
  };
}
