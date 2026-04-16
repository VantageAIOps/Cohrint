import type { Env } from "./types";

const WINDOW_MS = 60 * 60 * 1000;
const MAX_MESSAGES = 20;

/**
 * Write-then-count rate limiter.
 *
 * KV has no atomic compare-and-swap, so a read-modify-write counter can be
 * bypassed under concurrent load. Instead we write a unique key per request
 * first, then count all keys for the current window. This means the limit can
 * be exceeded by at most (concurrency - 1) requests in a burst, but accumulated
 * usage is always counted correctly — far harder to exploit than a plain counter.
 *
 * For strict atomic limiting, migrate to a Durable Object counter.
 */
export async function checkRateLimit(
  orgId: string,
  env: Env
): Promise<{ allowed: boolean; remaining: number }> {
  const windowId = Math.floor(Date.now() / WINDOW_MS);
  const prefix = `rl:${orgId}:${windowId}:`;
  const ttl = Math.ceil(WINDOW_MS / 1000);

  // Write this request's unique slot first
  const reqKey = `${prefix}${crypto.randomUUID()}`;
  await env.VEGA_KV.put(reqKey, "1", { expirationTtl: ttl });

  // Count all slots for this org+window
  const { keys } = await env.VEGA_KV.list({ prefix });
  const count = keys.length;

  if (count > MAX_MESSAGES) {
    // Clean up the slot we just wrote so it doesn't inflate future counts
    await env.VEGA_KV.delete(reqKey);
    return { allowed: false, remaining: 0 };
  }

  return { allowed: true, remaining: Math.max(0, MAX_MESSAGES - count) };
}
