import { Hono } from 'hono';
import { Bindings, Variables } from '../types';

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
  const token = c.req.query('token') ?? '';
  if (!token.startsWith('vnt_')) {
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
      'Access-Control-Allow-Origin': '*',
      'X-Accel-Buffering':           'no',
    },
  });
});

export { stream };
