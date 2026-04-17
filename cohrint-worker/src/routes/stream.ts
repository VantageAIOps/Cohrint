import { Hono } from 'hono';
import { Bindings, Variables } from '../types';
import { createLogger } from '../lib/logger';

async function sha256hex(data: string): Promise<string> {
  const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(data));
  return Array.from(new Uint8Array(buf)).map(b => b.toString(16).padStart(2, '0')).join('');
}

const stream = new Hono<{ Bindings: Bindings; Variables: Variables }>();

/**
 * GET /v1/stream/:org_id?token=crt_...
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
  //   ?token=crt_...                          — SDK / direct API callers
  const sseToken = c.req.query('sse_token') ?? '';
  const token    = c.req.query('token') ?? '';

  if (sseToken) {
    // Look up token in KV — reusable for 1 hour (not one-time use)
    const val = await c.env.KV.get(`sse:${orgId}:${sseToken}`);
    if (!val) {
      return c.json({ error: 'Invalid or expired sse_token' }, 401);
    }
    // Token stays in KV until its TTL expires — allows reconnects without re-auth
  } else if (token.startsWith('vnt_') || token.startsWith('crt_')) {
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

  // Run the polling loop in background (don't await)
  (async () => {
    try {
      let lastSeqno = 0;
      let lastDataSent = Date.now();
      const deadline = Date.now() + 50_000; // 50s max (well within CF streaming limits)

      while (Date.now() < deadline) {
        try {
          // Read circular buffer (StreamEvent[], newest first, max 25 items)
          const bufRaw = await c.env.KV.get(`stream:${orgId}:buf`);
          if (bufRaw) {
            const buf = JSON.parse(bufRaw) as Array<{ seqno: number; [k: string]: unknown }>;
            const newEvents = lastSeqno > 0
              ? buf.filter(e => e.seqno > lastSeqno)
              : buf.slice(0, 1); // first poll: only the most recent event
            if (newEvents.length > 0) {
              for (const ev of [...newEvents].reverse()) { // send oldest-first
                await sendEvent(JSON.stringify(ev));
              }
              lastSeqno = newEvents[0].seqno; // newEvents[0] is newest
              lastDataSent = Date.now();
            }
          } else {
            // Fallback 1: legacy 'latest' key during transition
            const raw = await c.env.KV.get(`stream:${orgId}:latest`);
            if (raw) {
              try {
                const ev = JSON.parse(raw) as { seqno?: number; ts?: number };
                const seq = ev.seqno ?? ev.ts ?? 0;
                if (seq > lastSeqno) {
                  lastSeqno = seq;
                  await sendEvent(raw);
                  lastDataSent = Date.now();
                }
              } catch { /* ignore parse errors */ }
            } else if (lastSeqno === 0) {
              // Fallback 2: KV propagation lag — query D1 otel_events on first connection
              try {
                const row = await c.env.DB.prepare(
                  `SELECT provider, model, cost_usd,
                          tokens_in + tokens_out AS total_tokens, timestamp
                   FROM otel_events WHERE org_id = ?
                   ORDER BY timestamp DESC LIMIT 1`
                ).bind(orgId).first<Record<string, unknown>>();
                if (row) {
                  const seqno = Date.now();
                  lastSeqno = seqno;
                  await sendEvent(JSON.stringify({
                    seqno, ts: seqno,
                    provider: row.provider,
                    model:    row.model,
                    cost_usd: row.cost_usd,
                    tokens:   row.total_tokens,
                  }));
                  lastDataSent = Date.now();
                }
              } catch { /* D1 also unavailable — keep alive until KV catches up */ }
            }
          }
        } catch (kvErr) {
          createLogger(c.get('requestId') ?? 'unknown').error('stream KV read failed', { err: kvErr instanceof Error ? kvErr : new Error(String(kvErr)) });
          // Send an error SSE event and close cleanly rather than aborting
          try { await write('event: error\ndata: {"error":"stream_unavailable"}\n\n'); } catch { /* ignore */ }
          await writer.close();
          return;
        }

        // Heartbeat: keep connection alive if no data sent in 5s
        if (Date.now() - lastDataSent > 5000) {
          await write(': keep-alive\n\n');
          lastDataSent = Date.now();
        }

        // Wait 2s between polls
        await new Promise(r => setTimeout(r, 2000));
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
      'Access-Control-Allow-Origin': (() => {
        const origin = c.req.header('Origin') ?? '';
        const allowed = (c.env.ALLOWED_ORIGINS ?? 'https://cohrint.com').split(',').map((s: string) => s.trim());
        return allowed.some((a: string) => a === '*' || a === origin || (a.includes('*') && new RegExp('^' + a.replace('*', '.*') + '$').test(origin)))
          ? origin
          : (allowed.find((a: string) => !a.includes('*')) ?? 'https://cohrint.com');
      })(),
      'X-Accel-Buffering':           'no',
    },
  });
});

export { stream };
