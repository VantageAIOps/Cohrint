import type { Env } from "./types";

const WINDOW_MS = 60 * 60 * 1000;
const MAX_MESSAGES = 20;

export async function checkRateLimit(
  orgId: string,
  env: Env
): Promise<{ allowed: boolean; remaining: number }> {
  const key = `rl:${orgId}:${Math.floor(Date.now() / WINDOW_MS)}`;
  const raw = await env.VEGA_KV.get(key);
  const count = raw ? parseInt(raw, 10) : 0;

  if (count >= MAX_MESSAGES) {
    return { allowed: false, remaining: 0 };
  }

  await env.VEGA_KV.put(key, String(count + 1), {
    expirationTtl: Math.ceil(WINDOW_MS / 1000),
  });

  return { allowed: true, remaining: MAX_MESSAGES - count - 1 };
}
