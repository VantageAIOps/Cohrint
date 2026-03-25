import { Hono } from 'hono';
import { Bindings, Variables } from '../types';

async function sha256hex(data: string): Promise<string> {
  const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(data));
  return Array.from(new Uint8Array(buf)).map(b => b.toString(16).padStart(2, '0')).join('');
}

const stream = new Hono<{ Bindings: Bindings; Variables: Variables }>();

/**
 * GET /v1/stream/:org_id?token=vnt_...
 *
 * Server-Sent Events endpoint.
 * Workers can't hold persistent connections like Node.js, so we use a
 * polling-over-SSE pattern:
 *   1. Send the last stored event from KV immediately
 *   2. Poll KV every 2s for new events, send each as SSE data
 *   3. Send a :ping comment every 20s to keep the connection alive
 *   4. Close after 25s (Workers free-tier wall-clock limit is 30s)
 *   5. Client reconnects automatically (EventSource spec + our JS code)
 *
 * This gives ~live updates every 2s with zero extra infrastructure.
 */
stream.get('/:orgId', async (c) => {
  const orgId = c.req.param('orgId');

  // Auth via query param (EventSource API can't set headers)
  // Accept either:
  //   ?sse_token=<short-lived 32-hex token>  — browser/dashboard (session-based auth)
  //   ?token=vnt_...                          — SDK / direct API callers
  const sseToken = c.req.query('sse_token') ?? '';
  const token    = c.req.query('token') ?? '';

  if (sseToken) {
    // Look up short-lived token in KV; delete on use (one-time)
    const val = await c.env.KV.get(`sse:${orgId}:${sseToken}`);
    if (!val) {
      return c.json({ error: 'Invalid or expired sse_token' }, 401);
    }
    await c.env.KV.delete(`sse:${orgId}:${sseToken}`);
  } else if (token.startsWith('vnt_')) {
    // Validate API key against DB (same pattern as authMiddleware)
    const hash = await sha256hex(token);
    const org = await c.env.DB.prepare(
      'SELECT id FROM orgs WHERE api_key_hash = ?'
    ).bind(hash).first<{ id: string }>();
    const member = org ? null : await c.env.DB.prepare(
      'SELECT org_id FROM org_members WHERE api_key_hash = ?'
    ).bind(hash).first<{ org_id: string }>();
    const resolvedOrg = org?.id ?? member?.org_id;
    if (!resolvedOrg || resolvedOrg !== orgId) {
      return c.json({ error: 'Invalid API key or org mismatch' }, 401);
    }
  } else {
    return c.json({ error: 'Missing token query param' }, 401);
  }

  const encoder = new TextEncoder();

  const { readable, writable } = new TransformStream<Uint8Array, Uint8Array>();
  const writer = writable.getWriter();

  const write = (data: string) => writer.write(encoder.encode(data));
  const sendEvent = (payload: string) => write(`data: ${payload}\n\n`);
  const sendPing  = () => write(':ping\n\n');

  // Run the polling loop in background (don't await)
  (async () => {
    try {
      let lastTs = 0;
      const deadline = Date.now() + 25_000; // 25s max

      while (Date.now() < deadline) {
        const raw = await c.env.KV.get(`stream:${orgId}:latest`);
        if (raw) {
          try {
            const ev = JSON.parse(raw) as { ts: number };
            if (ev.ts > lastTs) {
              lastTs = ev.ts;
              await sendEvent(raw);
            }
          } catch { /* ignore parse errors */ }
        } else {
          await sendPing();
        }

        // Wait 2s between polls
        await new Promise(r => setTimeout(r, 2000));

        // Ping every ~20s to keep connection alive through proxies
        if ((Date.now() % 20_000) < 2000) await sendPing();
      }

      // Close gracefully — client will reconnect automatically
      await writer.close();
    } catch {
      await writer.abort();
    }
  })();

  return new Response(readable, {
    headers: {
      'Content-Type':                'text/event-stream',
      'Cache-Control':               'no-cache',
      'Connection':                  'keep-alive',
      'Access-Control-Allow-Origin': c.req.header('Origin') || 'https://vantageaiops.com',
      'X-Accel-Buffering':           'no',
    },
  });
});

export { stream };
