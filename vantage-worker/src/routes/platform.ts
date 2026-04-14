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
      CREATE TABLE IF NOT EXISTS platform_pageviews (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT, page TEXT, referrer TEXT,
        created_at INTEGER NOT NULL DEFAULT (unixepoch())
      )
    `).run();

    await c.env.DB.prepare(`
      INSERT INTO platform_pageviews (session_id, page, referrer)
      VALUES (?, ?, ?)
    `).bind(session_id || null, page || null, referrer || null).run();
  } catch { /* best effort */ }

  return c.json({ ok: true });
});

// ── POST /v1/platform/session ────────────────────────────────────────────────
platform.post('/session', async (c) => {
  let body: { session_id?: string; org_id?: string; duration_sec?: number };
  try { body = await c.req.json(); }
  catch { return c.json({ ok: false }, 400); }

  const session_id   = (body.session_id   ?? '').slice(0, 64);
  const org_id       = (body.org_id       ?? '').slice(0, 64);
  const duration_sec = Math.min(Math.max(0, body.duration_sec ?? 0), 86_400);

  try {
    await c.env.DB.prepare(`
      CREATE TABLE IF NOT EXISTS platform_sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        org_id TEXT, session_id TEXT, duration_sec INTEGER DEFAULT 0,
        created_at INTEGER NOT NULL DEFAULT (unixepoch())
      )
    `).run();

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
        INSERT INTO platform_sessions (org_id, session_id, duration_sec)
        VALUES (?, ?, ?)
      `).bind(org_id || null, session_id || null, duration_sec).run();
    }
  } catch { /* best effort */ }

  return c.json({ ok: true });
});

// ── POST /v1/platform/report-signup ─────────────────────────────────────────
// Public, no auth. Accepts { email } and stores in KV. Idempotent.
platform.post('/report-signup', async (c) => {
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

  await c.env.KV.put(key, JSON.stringify({
    email,
    signed_up_at: new Date().toISOString(),
    source: 'report-page',
  }));

  return c.json({ ok: true });
});

export { platform };
