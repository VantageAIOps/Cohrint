/**
 * Platform tracking — lightweight public endpoints.
 * Called from the frontend to record pageviews and session events.
 * No auth required; data is intentionally minimal (no PII).
 *
 * POST /v1/platform/pageview  { page, referrer, session_id }
 * POST /v1/platform/session   { session_id, org_id?, duration_sec }
 * POST /v1/platform/request   (called internally from middleware, not frontend)
 */

import { Hono } from 'hono';
import { Bindings, Variables } from '../types';

const platform = new Hono<{ Bindings: Bindings; Variables: Variables }>();

// ── POST /v1/platform/pageview ───────────────────────────────────────────────
platform.post('/pageview', async (c) => {
  let body: { page?: string; referrer?: string; session_id?: string };
  try { body = await c.req.json(); }
  catch { return c.json({ ok: false }, 400); }

  const page       = (body.page       ?? '').slice(0, 200);
  const referrer   = (body.referrer   ?? '').slice(0, 200);
  const session_id = (body.session_id ?? '').slice(0, 64);

  // Best-effort insert; never fail the caller
  try {
    await c.env.DB.prepare(`
      INSERT INTO platform_pageviews (session_id, page, referrer)
      VALUES (?, ?, ?)
    `).bind(session_id || null, page || null, referrer || null).run();
  } catch { /* best effort */ }

  return c.json({ ok: true });
});

// ── POST /v1/platform/session ────────────────────────────────────────────────
platform.post('/session', async (c) => {
  // org_id is intentionally NOT accepted from the caller — this is a public
  // endpoint and accepting caller-supplied org_id would allow anyone to spoof
  // session attribution for any org.
  let body: { session_id?: string; duration_sec?: number };
  try { body = await c.req.json(); }
  catch { return c.json({ ok: false }, 400); }

  const session_id   = (body.session_id   ?? '').slice(0, 64);
  const duration_sec = Math.min(Math.max(0, body.duration_sec ?? 0), 86_400);

  try {
    // Upsert: update duration if session already recorded, else insert
    const existing = await c.env.DB.prepare(
      'SELECT id FROM platform_sessions WHERE session_id = ?'
    ).bind(session_id).first<{ id: number }>();

    if (existing) {
      await c.env.DB.prepare(
        'UPDATE platform_sessions SET duration_sec = ? WHERE session_id = ?'
      ).bind(duration_sec, session_id).run();
    } else {
      await c.env.DB.prepare(`
        INSERT INTO platform_sessions (session_id, duration_sec)
        VALUES (?, ?)
      `).bind(session_id || null, duration_sec).run();
    }
  } catch { /* best effort */ }

  return c.json({ ok: true });
});

// ── POST /v1/platform/report-signup ─────────────────────────────────────────
// Public, no auth. Accepts { email } and stores in KV. Idempotent.
// Rate limited: max 5 signups per IP per hour to prevent KV exhaustion.
platform.post('/report-signup', async (c) => {
  // IP-based rate limit — 5 attempts per hour per IP
  const ip      = c.req.header('CF-Connecting-IP') ?? 'unknown';
  const ipKey   = `report-signup:ip:${ip}`;
  const ipCount = parseInt(await c.env.KV.get(ipKey) ?? '0', 10);
  if (ipCount >= 5) return c.json({ ok: false, error: 'rate_limited' }, 429);

  let body: { email?: unknown };
  try { body = await c.req.json(); }
  catch { return c.json({ ok: false, error: 'invalid_json' }, 400); }

  const raw = body.email;
  if (typeof raw !== 'string') return c.json({ ok: false, error: 'email_required' }, 400);

  const email = raw.trim().toLowerCase().slice(0, 320);

  // Basic RFC-5322-ish validation
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(email)) {
    return c.json({ ok: false, error: 'invalid_email' }, 400);
  }

  const key = `report-signup:${email}`;

  // Idempotent — if already signed up, return ok silently
  const existing = await c.env.KV.get(key);
  if (existing) return c.json({ ok: true });

  // Increment IP counter (1-hour window) and store signup
  await Promise.all([
    c.env.KV.put(ipKey, String(ipCount + 1), { expirationTtl: 3600 }),
    c.env.KV.put(key, JSON.stringify({
      email,
      signed_up_at: new Date().toISOString(),
      source: 'report-page',
    }), { expirationTtl: 365 * 24 * 3600 }), // 1 year retention
  ]);

  return c.json({ ok: true });
});

export { platform };
