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
    const { subject, html } = keyRecoveryEmail({
      orgId:   org.id,
      orgName: org.name || org.id,
      keyHint: org.api_key_hint || 'vnt_...',
      isOwner: true,
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
