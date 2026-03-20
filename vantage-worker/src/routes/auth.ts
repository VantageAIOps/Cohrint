import { Hono } from 'hono';
import { Bindings, Variables } from '../types';
import { authMiddleware, adminOnly, sha256hex } from '../middleware/auth';
import { sendEmail, memberInviteEmail, keyRecoveryEmail } from '../lib/email';

const auth = new Hono<{ Bindings: Bindings; Variables: Variables }>();

// ── Helpers ───────────────────────────────────────────────────────────────────
function toSlug(input: string): string {
  return input
    .toLowerCase()
    .replace(/@.*/, '')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 24)
    || 'org';
}

function randomHex(bytes = 8): string {
  const arr = new Uint8Array(bytes);
  crypto.getRandomValues(arr);
  return Array.from(arr).map(b => b.toString(16).padStart(2, '0')).join('');
}

// ── POST /v1/auth/signup — public, creates org + owner key ───────────────────
auth.post('/signup', async (c) => {
  let body: { email?: string; name?: string; org?: string };
  try { body = await c.req.json(); }
  catch { return c.json({ error: 'Invalid JSON body' }, 400); }

  const email    = (body.email ?? '').trim().toLowerCase();
  const name     = (body.name  ?? '').trim();
  const orgInput = (body.org   ?? name ?? email).trim();

  if (!email || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
    return c.json({ error: 'Valid email is required' }, 400);
  }

  const existing = await c.env.DB.prepare(
    'SELECT id, api_key_hint FROM orgs WHERE email = ?'
  ).bind(email).first<{ id: string; api_key_hint: string }>();

  if (existing) {
    return c.json({
      error: 'An account with this email already exists.',
      hint:  `Your org ID is "${existing.id}". Check your original signup for the key, or use /v1/auth/recover.`,
    }, 409);
  }

  let orgId = toSlug(orgInput || email);
  const taken = await c.env.DB.prepare('SELECT id FROM orgs WHERE id = ?').bind(orgId).first();
  if (taken) orgId = `${orgId}-${randomHex(3)}`;

  const rawKey  = `vnt_${orgId}_${randomHex(16)}`;
  const keyHash = await sha256hex(rawKey);
  const keyHint = `${rawKey.slice(0, 12)}...`;

  await c.env.DB.prepare(`
    INSERT INTO orgs (id, api_key_hash, api_key_hint, name, email, plan, created_at)
    VALUES (?, ?, ?, ?, ?, 'free', unixepoch())
  `).bind(orgId, keyHash, keyHint, name || orgId, email).run();

  return c.json({
    ok:        true,
    api_key:   rawKey,
    org_id:    orgId,
    hint:      keyHint,
    dashboard: `https://vantageaiops.com/app.html?api_key=${rawKey}&org=${orgId}`,
  }, 201);
});

// ── POST /v1/auth/recover — public, sends recovery email ─────────────────────
auth.post('/recover', async (c) => {
  let body: { email?: string };
  try { body = await c.req.json(); }
  catch { return c.json({ error: 'Invalid JSON body' }, 400); }

  const email = (body.email ?? '').trim().toLowerCase();
  if (!email) return c.json({ error: 'email is required' }, 400);

  // Always return 200 — don't leak whether email exists
  const org = await c.env.DB.prepare(
    'SELECT id, name, api_key_hint FROM orgs WHERE email = ?'
  ).bind(email).first<{ id: string; name: string; api_key_hint: string }>();

  if (org) {
    // Generate a one-time recovery token (1-hour TTL) so user can get a new key directly
    const token   = randomHex(24);
    const kvKey   = `recover:${token}`;
    let redeemUrl = '';
    try {
      await c.env.KV.put(kvKey, JSON.stringify({ orgId: org.id, type: 'owner' }), { expirationTtl: 3600 });
      redeemUrl = `https://api.vantageaiops.com/v1/auth/recover/redeem?token=${token}`;
    } catch {
      // KV unavailable — email still sent without one-click redeem link
    }

    const { subject, html } = keyRecoveryEmail({
      orgId:      org.id,
      orgName:    org.name || org.id,
      keyHint:    org.api_key_hint || 'vnt_...',
      isOwner:    true,
      redeemUrl,
    });
    await sendEmail(c.env.RESEND_API_KEY, { to: email, subject, html });
  } else {
    // Check org_members table
    const member = await c.env.DB.prepare(
      'SELECT m.id, m.org_id, m.api_key_hint, o.name AS org_name FROM org_members m JOIN orgs o ON o.id = m.org_id WHERE m.email = ?'
    ).bind(email).first<{ id: string; org_id: string; api_key_hint: string; org_name: string }>();

    if (member) {
      const { subject, html } = keyRecoveryEmail({
        orgId:   member.org_id,
        orgName: member.org_name || member.org_id,
        keyHint: member.api_key_hint || 'vnt_...',
        isOwner: false,
      });
      await sendEmail(c.env.RESEND_API_KEY, { to: email, subject, html });
    }
  }

  return c.json({ ok: true, message: 'If an account exists for this email, recovery instructions have been sent.' });
});

// ── GET /v1/auth/recover/redeem — confirmation page (token NOT consumed here)
// Link scanners (Gmail, Outlook Safe Links) only follow GETs — they would
// consume a single-use token. So GET just checks the token is valid and
// redirects to a confirmation page. Only the subsequent POST actually rotates.
auth.get('/recover/redeem', async (c) => {
  const token = c.req.query('token') ?? '';
  const SITE  = 'https://vantageaiops.com';

  if (!token) {
    return c.redirect(`${SITE}/auth?recovery_error=missing_token`);
  }

  // Peek at the token (don't delete it yet)
  const raw = await c.env.KV.get(`recover:${token}`);
  if (!raw) {
    return c.redirect(`${SITE}/auth?recovery_error=expired`);
  }

  // Send to confirmation page — token still intact, ready for POST
  return c.redirect(`${SITE}/auth?confirm_token=${encodeURIComponent(token)}`);
});

// ── POST /v1/auth/recover/redeem — actually rotates the key (safe from scanners)
auth.post('/recover/redeem', async (c) => {
  let token = '';
  try {
    const body = await c.req.json() as { token?: string };
    token = (body.token ?? '').trim();
  } catch { /* fall through to error */ }

  if (!token) return c.json({ error: 'token is required' }, 400);

  const raw = await c.env.KV.get(`recover:${token}`);
  if (!raw) return c.json({ error: 'expired' }, 410);

  let payload: { orgId: string; type: string };
  try { payload = JSON.parse(raw); }
  catch { return c.json({ error: 'invalid' }, 400); }

  // Consume the token immediately (single-use)
  await c.env.KV.delete(`recover:${token}`);

  // Rotate the org owner key
  const newKey  = `vnt_${payload.orgId}_${randomHex(16)}`;
  const keyHash = await sha256hex(newKey);
  const keyHint = `${newKey.slice(0, 12)}...`;

  await c.env.DB.prepare(
    'UPDATE orgs SET api_key_hash = ?, api_key_hint = ? WHERE id = ?'
  ).bind(keyHash, keyHint, payload.orgId).run();

  return c.json({ ok: true, api_key: newKey, hint: keyHint });
});

// ── All member endpoints require auth ─────────────────────────────────────────

// ── POST /v1/auth/members — invite a member (admin/owner only) ────────────────
auth.post('/members', authMiddleware, adminOnly, async (c) => {
  const orgId = c.get('orgId');
  let body: { email?: string; name?: string; role?: string; scope_team?: string };
  try { body = await c.req.json(); }
  catch { return c.json({ error: 'Invalid JSON body' }, 400); }

  const email     = (body.email ?? '').trim().toLowerCase();
  const name      = (body.name  ?? '').trim();
  const role      = ['admin', 'member', 'viewer'].includes(body.role ?? '') ? body.role! : 'member';
  const scopeTeam = body.scope_team?.trim() || null;

  if (!email || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
    return c.json({ error: 'Valid email is required' }, 400);
  }

  const existing = await c.env.DB.prepare(
    'SELECT id FROM org_members WHERE org_id = ? AND email = ?'
  ).bind(orgId, email).first();
  if (existing) return c.json({ error: `${email} is already a member of this org` }, 409);

  const memberId = randomHex(8);
  const rawKey   = `vnt_${orgId}_${randomHex(16)}`;
  const keyHash  = await sha256hex(rawKey);
  const keyHint  = `${rawKey.slice(0, 12)}...`;

  await c.env.DB.prepare(`
    INSERT INTO org_members (id, org_id, email, name, role, api_key_hash, api_key_hint, scope_team, created_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, unixepoch())
  `).bind(memberId, orgId, email, name || null, role, keyHash, keyHint, scopeTeam).run();

  // Get org name for the invite email
  const org = await c.env.DB.prepare('SELECT name, email FROM orgs WHERE id = ?')
    .bind(orgId).first<{ name: string; email: string }>();

  // Send invite email (fire-and-forget, non-blocking)
  const { subject, html } = memberInviteEmail({
    invitedBy: org?.email ?? 'your admin',
    orgId,
    orgName:   org?.name  ?? orgId,
    role,
    scopeTeam,
    apiKey:    rawKey,
    keyHint,
  });
  c.executionCtx.waitUntil(
    sendEmail(c.env.RESEND_API_KEY, { to: email, subject, html })
  );

  return c.json({
    ok:         true,
    member_id:  memberId,
    api_key:    rawKey,
    hint:       keyHint,
    email,
    role,
    scope_team: scopeTeam,
    email_sent: !!c.env.RESEND_API_KEY,
    note:       c.env.RESEND_API_KEY
      ? 'Invite email sent. Key also shown here — store securely.'
      : 'No email configured. Share this key with the member — it will not be shown again.',
  }, 201);
});

// ── GET /v1/auth/members — list members (admin/owner only) ───────────────────
auth.get('/members', authMiddleware, adminOnly, async (c) => {
  const orgId = c.get('orgId');
  const { results } = await c.env.DB.prepare(`
    SELECT id, email, name, role, api_key_hint, scope_team,
           datetime(created_at, 'unixepoch') AS created_at
    FROM org_members WHERE org_id = ? ORDER BY created_at ASC
  `).bind(orgId).all();
  return c.json({ members: results });
});

// ── PATCH /v1/auth/members/:id — update role or scope (admin/owner only) ─────
auth.patch('/members/:id', authMiddleware, adminOnly, async (c) => {
  const orgId    = c.get('orgId');
  const memberId = c.req.param('id');
  let body: { role?: string; scope_team?: string | null };
  try { body = await c.req.json(); }
  catch { return c.json({ error: 'Invalid JSON body' }, 400); }

  const updates: string[] = [];
  const params: unknown[] = [];
  if (body.role && ['admin', 'member', 'viewer'].includes(body.role)) {
    updates.push('role = ?'); params.push(body.role);
  }
  if ('scope_team' in body) {
    updates.push('scope_team = ?'); params.push(body.scope_team ?? null);
  }
  if (updates.length === 0) return c.json({ error: 'Provide role or scope_team to update.' }, 400);

  params.push(memberId, orgId);
  await c.env.DB.prepare(
    `UPDATE org_members SET ${updates.join(', ')} WHERE id = ? AND org_id = ?`
  ).bind(...params).run();
  return c.json({ ok: true });
});

// ── DELETE /v1/auth/members/:id — revoke member key (admin/owner only) ───────
auth.delete('/members/:id', authMiddleware, adminOnly, async (c) => {
  const orgId    = c.get('orgId');
  const memberId = c.req.param('id');
  await c.env.DB.prepare(
    'DELETE FROM org_members WHERE id = ? AND org_id = ?'
  ).bind(memberId, orgId).run();
  return c.json({ ok: true });
});

// ── POST /v1/auth/members/:id/rotate — regenerate a member's key ──────────────
auth.post('/members/:id/rotate', authMiddleware, adminOnly, async (c) => {
  const orgId    = c.get('orgId');
  const memberId = c.req.param('id');

  const member = await c.env.DB.prepare(
    'SELECT email, name, role, scope_team FROM org_members WHERE id = ? AND org_id = ?'
  ).bind(memberId, orgId).first<{ email: string; name: string; role: string; scope_team: string | null }>();
  if (!member) return c.json({ error: 'Member not found' }, 404);

  const rawKey  = `vnt_${orgId}_${randomHex(16)}`;
  const keyHash = await sha256hex(rawKey);
  const keyHint = `${rawKey.slice(0, 12)}...`;

  await c.env.DB.prepare(
    'UPDATE org_members SET api_key_hash = ?, api_key_hint = ? WHERE id = ? AND org_id = ?'
  ).bind(keyHash, keyHint, memberId, orgId).run();

  // Email the new key
  const org = await c.env.DB.prepare('SELECT name FROM orgs WHERE id = ?')
    .bind(orgId).first<{ name: string }>();
  const { html: rotateHtml } = memberInviteEmail({
    invitedBy: 'your admin (key rotated)',
    orgId,
    orgName:   org?.name ?? orgId,
    role:      member.role,
    scopeTeam: member.scope_team,
    apiKey:    rawKey,
    keyHint,
  });
  c.executionCtx.waitUntil(
    sendEmail(c.env.RESEND_API_KEY, { to: member.email, subject: `[VantageAI] Your API key has been rotated`, html: rotateHtml })
  );

  return c.json({
    ok:        true,
    api_key:   rawKey,
    hint:      keyHint,
    email_sent: !!c.env.RESEND_API_KEY,
    note:      'Old key is immediately revoked. New key shown here once.',
  });
});

// ── POST /v1/auth/session — exchange API key for a session cookie ─────────────
// Public — no authMiddleware. Caller sends { api_key }; we validate, create
// a 30-day session row in D1, and set an HTTP-only cookie.
auth.post('/session', async (c) => {
  let body: { api_key?: string };
  try { body = await c.req.json(); }
  catch { return c.json({ error: 'Invalid JSON body' }, 400); }

  const apiKey = (body.api_key ?? '').trim();
  if (!apiKey.startsWith('vnt_')) {
    return c.json({ error: 'Invalid API key format — must start with vnt_' }, 400);
  }

  const hash = await sha256hex(apiKey);

  // Resolve org + role from orgs or org_members table
  let orgId: string;
  let role: string;
  let memberId: string | null = null;

  const org = await c.env.DB.prepare(
    'SELECT id FROM orgs WHERE api_key_hash = ?'
  ).bind(hash).first<{ id: string }>();

  if (org) {
    orgId = org.id;
    role  = 'owner';
  } else {
    const member = await c.env.DB.prepare(
      'SELECT id, org_id, role FROM org_members WHERE api_key_hash = ?'
    ).bind(hash).first<{ id: string; org_id: string; role: string }>();

    if (!member) {
      return c.json({ error: 'Invalid API key' }, 401);
    }
    orgId    = member.org_id;
    role     = member.role;
    memberId = member.id;
  }

  // Generate a 64-char session token
  const tokenBytes = new Uint8Array(32);
  crypto.getRandomValues(tokenBytes);
  const token = Array.from(tokenBytes).map(b => b.toString(16).padStart(2, '0')).join('');

  const expiresAt = Math.floor(Date.now() / 1000) + 30 * 86_400; // 30 days

  await c.env.DB.prepare(`
    INSERT INTO sessions (token, org_id, role, member_id, expires_at)
    VALUES (?, ?, ?, ?, ?)
  `).bind(token, orgId, role, memberId, expiresAt).run();

  // Set HTTP-only cookie
  const isProd = (c.env.ENVIRONMENT ?? 'production') === 'production';
  const cookieParts = [
    `vantage_session=${token}`,
    `Path=/`,
    `HttpOnly`,
    `SameSite=Lax`,
    `Max-Age=${30 * 86_400}`,
  ];
  if (isProd) cookieParts.push(`Secure`, `Domain=vantageaiops.com`);

  const res = c.json({ ok: true, org_id: orgId, role, expires_at: expiresAt });
  (await res).headers.set('Set-Cookie', cookieParts.join('; '));
  return res;
});

// ── GET /v1/auth/session — return current session info ───────────────────────
auth.get('/session', authMiddleware, async (c) => {
  const orgId    = c.get('orgId');
  const role     = c.get('role');
  const memberId = c.get('memberId');

  const org = await c.env.DB.prepare(
    'SELECT name, email, plan, budget_usd, api_key_hint, created_at FROM orgs WHERE id = ?'
  ).bind(orgId).first<{ name: string; email: string; plan: string; budget_usd: number; api_key_hint: string; created_at: number }>();

  let memberInfo: { name: string | null; email: string | null } | null = null;
  if (memberId) {
    memberInfo = await c.env.DB.prepare(
      'SELECT name, email FROM org_members WHERE id = ?'
    ).bind(memberId).first<{ name: string | null; email: string | null }>() ?? null;
  }

  // Generate a short-lived SSE token (32 hex chars = 16 random bytes)
  const sseTokenBytes = new Uint8Array(16);
  crypto.getRandomValues(sseTokenBytes);
  const sseToken = Array.from(sseTokenBytes).map(b => b.toString(16).padStart(2, '0')).join('');

  // Store in KV with 120-second TTL — one-time use, consumed by stream.ts
  // If KV write fails (e.g. free tier limit), return null sse_token so the
  // client knows SSE is unavailable instead of getting a phantom token.
  let sseTokenFinal: string | null = sseToken;
  try {
    await c.env.KV.put(`sse:${orgId}:${sseToken}`, '1', { expirationTtl: 120 });
  } catch {
    sseTokenFinal = null; // KV unavailable — SSE disabled for this session
  }

  return c.json({
    authenticated: true,
    org_id:   orgId,
    role,
    member_id: memberId,
    org: {
      name:         org?.name,
      email:        org?.email,
      plan:         org?.plan ?? 'free',
      budget_usd:   org?.budget_usd ?? 0,
      api_key_hint: org?.api_key_hint ?? null,
      created_at:   org?.created_at ? new Date(org.created_at * 1000).toISOString() : null,
    },
    member: memberInfo,
    sse_token: sseTokenFinal,
    sse_url:   sseTokenFinal
      ? `https://api.vantageaiops.com/v1/stream/${orgId}?sse_token=${sseTokenFinal}`
      : null,
  });
});

// ── DELETE /v1/auth/session — logout, destroy session cookie ─────────────────
auth.delete('/session', async (c) => {
  const cookieHeader = c.req.header('Cookie') ?? '';
  const token = cookieHeader.split(';').map(s => s.trim())
    .find(s => s.startsWith('vantage_session='))?.split('=')[1];

  if (token) {
    await c.env.DB.prepare('DELETE FROM sessions WHERE token = ?').bind(token).run();
  }

  const res = c.json({ ok: true });
  const isProdLogout = (c.env.ENVIRONMENT ?? 'production') === 'production';
  const clearCookie = isProdLogout
    ? 'vantage_session=; Path=/; HttpOnly; Max-Age=0; SameSite=Lax; Secure; Domain=vantageaiops.com'
    : 'vantage_session=; Path=/; HttpOnly; Max-Age=0; SameSite=Lax';
  (await res).headers.set('Set-Cookie', clearCookie);
  return res;
});

// ── POST /v1/auth/rotate — rotate the org owner key ──────────────────────────
auth.post('/rotate', authMiddleware, async (c) => {
  const orgId = c.get('orgId');
  const role  = c.get('role');
  if (role !== 'owner') return c.json({ error: 'Only the org owner can rotate the root key' }, 403);

  const rawKey  = `vnt_${orgId}_${randomHex(16)}`;
  const keyHash = await sha256hex(rawKey);
  const keyHint = `${rawKey.slice(0, 12)}...`;

  await c.env.DB.prepare(
    'UPDATE orgs SET api_key_hash = ?, api_key_hint = ? WHERE id = ?'
  ).bind(keyHash, keyHint, orgId).run();

  return c.json({
    ok:      true,
    api_key: rawKey,
    hint:    keyHint,
    note:    'Your previous key is immediately revoked. Update it everywhere before closing this response.',
  });
});

export { auth };
