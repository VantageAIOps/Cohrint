import { Hono } from 'hono';
import { Bindings, Variables } from '../types';
import { authMiddleware, adminOnly, sha256hex } from '../middleware/auth';
import { sendEmail, memberInviteEmail, keyRecoveryEmail } from '../lib/email';
import { logAudit } from '../lib/audit';

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
  let body: { email?: string; name?: string; org?: string; account_type?: string };
  try { body = await c.req.json(); }
  catch { return c.json({ error: 'Invalid JSON body' }, 400); }

  const VALID_ACCOUNT_TYPES = ['individual', 'team', 'organization'] as const;
  const rawAccountType = body.account_type ?? 'organization';
  const accountType = (VALID_ACCOUNT_TYPES as readonly string[]).includes(rawAccountType)
    ? rawAccountType as 'individual' | 'team' | 'organization'
    : 'organization';

  // Rate limit signup: 30 per IP per hour (degrade gracefully if KV unavailable)
  // CI bypass: X-Cohrint-CI header with matching secret skips rate limiting (X-Vantage-CI accepted for backward compat)
  try {
    const ciBypass = c.req.header('X-Cohrint-CI') ?? c.req.header('X-Vantage-CI');
    const ciSecret = c.env.COHRINT_CI_SECRET ?? c.env.VANTAGE_CI_SECRET;
    if (!(ciBypass && ciSecret && ciBypass === ciSecret)) {
      const ip = c.req.header('CF-Connecting-IP') ?? 'unknown';
      const rlKey = `rl:signup:${ip}`;
      const count = parseInt(await c.env.KV.get(rlKey) ?? '0', 10);
      if (count >= 30) {
        return c.json({ error: 'Too many signup attempts. Try again later.' }, 429, { 'Retry-After': '3600' });
      }
      await c.env.KV.put(rlKey, String(count + 1), { expirationTtl: 3600 });
    }
  } catch { /* KV unavailable — allow signup to proceed */ }

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

  const rawKey  = `crt_${orgId}_${randomHex(16)}`;
  const keyHash = await sha256hex(rawKey);
  const keyHint = `${rawKey.slice(0, 12)}...`;

  await c.env.DB.prepare(`
    INSERT INTO orgs (id, api_key_hash, api_key_hint, name, email, plan, account_type, created_at)
    VALUES (?, ?, ?, ?, ?, 'free', ?, unixepoch())
  `).bind(orgId, keyHash, keyHint, name || orgId, email, accountType).run();

  return c.json({
    ok:           true,
    api_key:      rawKey,
    org_id:       orgId,
    account_type: accountType,
    hint:         keyHint,
    dashboard:    `https://cohrint.com/app.html?org=${orgId}`,
  }, 201);
});

// ── POST /v1/auth/recover — public, sends recovery email ─────────────────────
auth.post('/recover', async (c) => {
  // Rate limit recovery: 5 per IP per hour (degrade gracefully if KV unavailable)
  try {
    const ip = c.req.header('CF-Connecting-IP') ?? 'unknown';
    const rlKey = `rl:recover:${ip}`;
    const count = parseInt(await c.env.KV.get(rlKey) ?? '0', 10);
    if (count >= 5) {
      return c.json({ error: 'Too many recovery attempts. Try again later.' }, 429, { 'Retry-After': '3600' });
    }
    await c.env.KV.put(rlKey, String(count + 1), { expirationTtl: 3600 });
  } catch { /* KV unavailable — allow recovery to proceed */ }

  let body: { email?: string };
  try { body = await c.req.json(); }
  catch { return c.json({ error: 'Invalid JSON body' }, 400); }

  const email = (body.email ?? '').trim().toLowerCase();
  if (!email) return c.json({ error: 'email is required' }, 400);

  // Always return 200 — don't leak whether email exists
  // Wrap entire lookup+send in try/catch so a D1 schema/connectivity issue
  // never turns into a 500 (recovery endpoint must be resilient).
  let resolvedOrgId = 'unknown';
  try {
    const org = await c.env.DB.prepare(
      'SELECT id, name, api_key_hint FROM orgs WHERE email = ?'
    ).bind(email).first<{ id: string; name: string; api_key_hint: string }>();

    if (org) {
      resolvedOrgId = org.id;
      // Generate a one-time recovery token (1-hour TTL) so user can get a new key directly.
      // Token is bound to the requesting IP — redeemable only from the same IP within 1 hour.
      const token     = randomHex(24);
      const kvKey     = `recover:${token}`;
      const requestIp = c.req.header('CF-Connecting-IP') ?? 'unknown';
      let redeemUrl = '';
      try {
        await c.env.KV.put(kvKey, JSON.stringify({ orgId: org.id, type: 'owner', ip: requestIp }), { expirationTtl: 3600 });
        redeemUrl = `https://api.cohrint.com/v1/auth/recover/redeem?token=${token}`;
      } catch {
        // KV unavailable — email still sent without one-click redeem link
      }

      const { subject, html } = keyRecoveryEmail({
        orgId:      org.id,
        orgName:    org.name || org.id,
        keyHint:    org.api_key_hint || 'crt_...',
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
        resolvedOrgId = member.org_id;
        const { subject, html } = keyRecoveryEmail({
          orgId:   member.org_id,
          orgName: member.org_name || member.org_id,
          keyHint: member.api_key_hint || 'crt_...',
          isOwner: false,
        });
        await sendEmail(c.env.RESEND_API_KEY, { to: email, subject, html });
      }
    }
    // Audit log: recovery attempted
    logAudit(c, {
      event_type:    'auth',
      event_name:    'auth.account_recovery_attempted',
      resource_type: 'member',
      resource_id:   email,
    }, { orgId: resolvedOrgId });
  } catch (err) {
    console.error('[recover] D1/email error — returning 200 to avoid leaking info', err);
    // Still return 200 — don't expose internal errors to caller
  }

  return c.json({ ok: true, message: 'If an account exists for this email, recovery instructions have been sent.' });
});

// ── GET /v1/auth/recover/redeem — confirmation page (token NOT consumed here)
// Link scanners (Gmail, Outlook Safe Links) only follow GETs — they would
// consume a single-use token. So GET just checks the token is valid and
// redirects to a confirmation page. Only the subsequent POST actually rotates.
auth.get('/recover/redeem', async (c) => {
  const token = c.req.query('token') ?? '';
  const SITE  = 'https://cohrint.com';
  const wantsJson = (c.req.header('Accept') ?? '').includes('application/json');

  if (!token) {
    if (wantsJson) return c.json({ error: 'missing_token' }, 400);
    return c.redirect(`${SITE}/auth?recovery_error=missing_token`);
  }

  // Peek at the token (don't delete it yet)
  const raw = await c.env.KV.get(`recover:${token}`);
  if (!raw) {
    if (wantsJson) return c.json({ error: 'expired' }, 404);
    return c.redirect(`${SITE}/auth?recovery_error=expired`);
  }

  if (wantsJson) return c.json({ ok: true, token_valid: true });
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

  let payload: { orgId: string; type: string; ip?: string };
  try { payload = JSON.parse(raw); }
  catch { return c.json({ error: 'invalid' }, 400); }

  if (!payload.orgId || typeof payload.orgId !== 'string' || !payload.type || payload.type !== 'owner') {
    return c.json({ error: 'invalid' }, 400);
  }

  // IP check with attempt throttle — mismatches are logged and tracked but the token
  // is NOT immediately burned. NAT/proxy rotation can legitimately change the egress IP
  // between issue and redeem, so hard-burning on first mismatch permanently locks out
  // valid users with no recovery path. Instead, allow up to 3 attempts from different
  // IPs before consuming the token as a brute-force circuit-breaker.
  const redeemIp = c.req.header('CF-Connecting-IP') ?? 'unknown';
  if (payload.ip && payload.ip !== 'unknown' && payload.ip !== redeemIp) {
    const attemptKey = `recover-attempt:${token}`;
    const attempts = parseInt(await c.env.KV.get(attemptKey) ?? '0', 10) + 1;
    console.warn('[cohrint] recover/redeem IP mismatch — issued from', payload.ip, 'redeemed from', redeemIp, `(attempt ${attempts})`);
    if (attempts >= 3) {
      await c.env.KV.delete(`recover:${token}`);
      await c.env.KV.delete(attemptKey);
      return c.json({ error: 'expired' }, 410);
    }
    await c.env.KV.put(attemptKey, String(attempts), { expirationTtl: 3600 });
    return c.json({ error: 'ip_mismatch' }, 403);
  }

  // Consume the token immediately (single-use)
  await c.env.KV.delete(`recover:${token}`);

  // Rotate the org owner key
  const newKey  = `crt_${payload.orgId}_${randomHex(16)}`;
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
  const accountType = c.get('accountType');

  // Individual accounts cannot have members
  if (accountType === 'individual') {
    return c.json({ error: 'Individual accounts cannot have team members.' }, 403);
  }

  let body: { email?: string; name?: string; role?: string; scope_team?: string; team_id?: string };
  try { body = await c.req.json(); }
  catch { return c.json({ error: 'Invalid JSON body' }, 400); }

  const email     = (body.email ?? '').trim().toLowerCase();
  const name      = (body.name  ?? '').trim();
  // team accounts: only member/viewer (owner is implicit admin)
  // organization accounts: all roles up to owner
  const VALID_ROLES = accountType === 'team'
    ? ['member', 'viewer']
    : ['viewer', 'member', 'admin', 'ceo', 'superadmin'];
  const inviterRole = c.get('role') as string;
  const { hasRole: hr } = await import('../middleware/auth');
  const requestedRole = body.role ?? 'member';
  // Allow if: requested role is valid AND inviter's role >= requested role
  const role = (VALID_ROLES.includes(requestedRole) && hr(inviterRole, requestedRole as import('../types').OrgRole))
    ? requestedRole
    : 'member';
  const scopeTeam = body.scope_team?.trim() || null;

  // For organization accounts, require and validate team_id
  const rawTeamId = body.team_id?.trim() || null;
  let inviteTeamId: string | null = null;
  if (accountType === 'organization') {
    if (!rawTeamId) {
      return c.json({ error: 'organization accounts require a team_id when inviting members.' }, 400);
    }
    const team = await c.env.DB.prepare(
      'SELECT id FROM teams WHERE id = ? AND org_id = ? AND deleted_at IS NULL'
    ).bind(rawTeamId, orgId).first<{ id: string }>();
    if (!team) {
      return c.json({ error: `Team '${rawTeamId}' not found in this org.` }, 404);
    }
    inviteTeamId = rawTeamId;
  }

  if (!email || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
    return c.json({ error: 'Valid email is required' }, 400);
  }

  const existing = await c.env.DB.prepare(
    'SELECT id FROM org_members WHERE org_id = ? AND email = ?'
  ).bind(orgId, email).first();
  if (existing) return c.json({ error: `${email} is already a member of this org` }, 409);

  const memberId = randomHex(8);
  const rawKey   = `crt_${orgId}_${randomHex(16)}`;
  const keyHash  = await sha256hex(rawKey);
  const keyHint  = `${rawKey.slice(0, 12)}...`;

  await c.env.DB.prepare(`
    INSERT INTO org_members (id, org_id, email, name, role, api_key_hash, api_key_hint, scope_team, team_id, created_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, unixepoch())
  `).bind(memberId, orgId, email, name || null, role, keyHash, keyHint, scopeTeam, inviteTeamId).run();

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

  logAudit(c, {
    event_type:    'admin_action',
    event_name:    'admin_action.member_added',
    resource_type: 'member',
    resource_id:   email,
    metadata:      { role, scope_team: scopeTeam ?? null, key_hint: keyHint },
  });

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
    SELECT id, email, name, role, api_key_hint, scope_team, team_id,
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
  if (body.role) {
    const patchAccountType = c.get('accountType');
    const VALID_ROLES = patchAccountType === 'team'
      ? ['member', 'viewer']
      : ['viewer', 'member', 'admin', 'ceo', 'superadmin'];
    const updaterRole = c.get('role') as string;
    const { hasRole: hr } = await import('../middleware/auth');
    // Can only assign roles up to your own level
    if (!VALID_ROLES.includes(body.role) || !hr(updaterRole, body.role as import('../types').OrgRole)) {
      return c.json({ error: 'Insufficient privilege to assign that role.' }, 403);
    }
    updates.push('role = ?'); params.push(body.role);
  }
  if ('scope_team' in body) {
    const st = body.scope_team ?? null;
    // Validate: max 64 chars, alphanumeric/hyphen/underscore only (matches team slug format)
    if (st !== null && (st.length > 64 || !/^[a-z0-9_-]+$/i.test(st))) {
      return c.json({ error: 'scope_team must be ≤64 chars and contain only letters, numbers, hyphens, underscores.' }, 400);
    }
    updates.push('scope_team = ?'); params.push(st);
  }
  if (updates.length === 0) return c.json({ error: 'Provide role or scope_team to update.' }, 400);

  params.push(memberId, orgId);
  await c.env.DB.prepare(
    `UPDATE org_members SET ${updates.join(', ')} WHERE id = ? AND org_id = ?`
  ).bind(...params).run();

  logAudit(c, {
    event_type:    'admin_action',
    event_name:    'admin_action.member_updated',
    resource_type: 'member',
    resource_id:   memberId,
    metadata:      {
      updated_fields: updates,
      new_role:       body.role ?? null,
      new_scope_team: 'scope_team' in body ? (body.scope_team ?? null) : undefined,
    },
  });

  return c.json({ ok: true });
});

// ── DELETE /v1/auth/members/:id — revoke member key (admin/owner only) ───────
auth.delete('/members/:id', authMiddleware, adminOnly, async (c) => {
  const orgId      = c.get('orgId');
  const memberId   = c.req.param('id');
  const callerRole = c.get('role') as string;

  const removed = await c.env.DB.prepare(
    'SELECT email, role FROM org_members WHERE id = ? AND org_id = ?'
  ).bind(memberId, orgId).first<{ email: string; role: string }>();

  if (removed) {
    const ROLE_RANK: Record<string, number> = { viewer: 0, member: 1, admin: 2, ceo: 3, superadmin: 4, owner: 5 };
    const callerRank = ROLE_RANK[callerRole] ?? -1;
    const targetRank = ROLE_RANK[removed.role] ?? -1;
    if (targetRank >= callerRank) {
      return c.json({ error: 'Cannot remove a peer or higher-privileged member' }, 403);
    }
  }

  await c.env.DB.prepare(
    'DELETE FROM org_members WHERE id = ? AND org_id = ?'
  ).bind(memberId, orgId).run();

  logAudit(c, {
    event_type:    'admin_action',
    event_name:    'admin_action.member_removed',
    resource_type: 'member',
    resource_id:   removed?.email ?? memberId,
    metadata:      { role: removed?.role ?? 'unknown' },
  });

  return c.json({ ok: true });
});

// ── POST /v1/auth/members/:id/rotate — regenerate a member's key ──────────────
auth.post('/members/:id/rotate', authMiddleware, adminOnly, async (c) => {
  const orgId    = c.get('orgId');
  const memberId = c.req.param('id');

  const callerRole = c.get('role') as string;

  const member = await c.env.DB.prepare(
    'SELECT email, name, role, scope_team FROM org_members WHERE id = ? AND org_id = ?'
  ).bind(memberId, orgId).first<{ email: string; name: string; role: string; scope_team: string | null }>();
  if (!member) return c.json({ error: 'Member not found' }, 404);

  const ROLE_RANK: Record<string, number> = { viewer: 0, member: 1, admin: 2, ceo: 3, superadmin: 4, owner: 5 };
  const callerRank = ROLE_RANK[callerRole] ?? -1;
  const targetRank = ROLE_RANK[member.role] ?? -1;
  if (targetRank >= callerRank) {
    return c.json({ error: 'Cannot rotate key for a peer or higher-privileged member' }, 403);
  }

  const rawKey  = `crt_${orgId}_${randomHex(16)}`;
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
    sendEmail(c.env.RESEND_API_KEY, { to: member.email, subject: `[Cohrint] Your API key has been rotated`, html: rotateHtml })
  );

  logAudit(c, {
    event_type:    'admin_action',
    event_name:    'key.rotated',
    resource_type: 'member',
    resource_id:   member.email,
    metadata:      { role: member.role, scope_team: member.scope_team ?? null, key_hint: keyHint },
  });

  return c.json({
    ok:        true,
    api_key:   rawKey,
    hint:      keyHint,
    email_sent: !!c.env.RESEND_API_KEY,
    note:      'Old key is immediately revoked. New key shown here once.',
  });
});

// ── POST /v1/auth/demo — issue a short-lived demo session ────────────────────
// Public — no body required. Reads DEMO_API_KEY server-side (never exposed to
// client), validates it against orgs/org_members, and issues a 1-hour session
// cookie. Returns 503 when the secret is unset so the frontend can fall back
// to the signup CTA.
auth.post('/demo', async (c) => {
  const demoKey = (c.env.DEMO_API_KEY ?? '').trim();
  if (!demoKey) {
    return c.json({ error: 'Demo unavailable' }, 503);
  }

  // Light brute-force guard (per-IP) so this endpoint can't be abused to
  // fabricate many session rows.
  try {
    const ip    = c.req.header('CF-Connecting-IP') ?? 'unknown';
    const rlKey = `rl:demo:${ip}`;
    const count = parseInt(await c.env.KV.get(rlKey) ?? '0', 10);
    if (count >= 30) {
      return c.json({ error: 'Too many demo sessions. Try again later.' }, 429, { 'Retry-After': '300' });
    }
    await c.env.KV.put(rlKey, String(count + 1), { expirationTtl: 300 });
  } catch { /* KV unavailable — allow request */ }

  const hash = await sha256hex(demoKey);

  let orgId: string;
  let role: string;
  let memberId: string | null = null;

  const org = await c.env.DB.prepare(
    'SELECT id FROM orgs WHERE api_key_hash = ?'
  ).bind(hash).first<{ id: string }>();
  if (org) {
    orgId = org.id;
    role  = 'viewer'; // Force-downgrade demo sessions to viewer regardless of the underlying key's role
  } else {
    const member = await c.env.DB.prepare(
      'SELECT id, org_id FROM org_members WHERE api_key_hash = ?'
    ).bind(hash).first<{ id: string; org_id: string }>();
    if (!member) {
      console.error('[auth/demo] DEMO_API_KEY set but does not resolve to any org/member');
      return c.json({ error: 'Demo unavailable' }, 503);
    }
    orgId    = member.org_id;
    role     = 'viewer';
    memberId = member.id;
  }

  const tokenBytes = new Uint8Array(32);
  crypto.getRandomValues(tokenBytes);
  const token = Array.from(tokenBytes).map(b => b.toString(16).padStart(2, '0')).join('');

  const DEMO_TTL_SEC = 3600; // 1 hour
  const expiresAt    = Math.floor(Date.now() / 1000) + DEMO_TTL_SEC;

  await c.env.DB.prepare(`
    INSERT INTO sessions (token, org_id, role, member_id, expires_at)
    VALUES (?, ?, ?, ?, ?)
  `).bind(token, orgId, role, memberId, expiresAt).run();

  const isProd = (c.env.ENVIRONMENT ?? 'production') === 'production';
  const cookieParts = isProd
    ? [
        `__Host-cohrint_session=${token}`,
        `Path=/`,
        `HttpOnly`,
        `SameSite=None`,
        `Max-Age=${DEMO_TTL_SEC}`,
        `Secure`,
      ]
    : [
        `cohrint_session=${token}`,
        `Path=/`,
        `HttpOnly`,
        `Max-Age=${DEMO_TTL_SEC}`,
        `SameSite=Lax`,
      ];

  const res = c.json({ ok: true, role, expires_at: expiresAt });
  (await res).headers.set('Set-Cookie', cookieParts.join('; '));
  return res;
});

// ── POST /v1/auth/session — exchange API key for a session cookie ─────────────
// Public — no authMiddleware. Caller sends { api_key }; we validate, create
// a 30-day session row in D1, and set an HTTP-only cookie.
auth.post('/session', async (c) => {
  // Brute-force protection: 10 failed attempts per IP per 5-minute window
  let rlKey: string | null = null;
  try {
    const ip = c.req.header('CF-Connecting-IP') ?? 'unknown';
    rlKey = `rl:session:${ip}`;
    const count = parseInt(await c.env.KV.get(rlKey) ?? '0', 10);
    if (count >= 10) {
      return c.json({ error: 'Too many attempts. Try again later.' }, 429, { 'Retry-After': '300' });
    }
  } catch { /* KV unavailable — allow request to proceed */ }

  let body: { api_key?: string };
  try { body = await c.req.json(); }
  catch { return c.json({ error: 'Invalid JSON body' }, 400); }

  const apiKey = (body.api_key ?? '').trim();
  if (!apiKey.startsWith('vnt_') && !apiKey.startsWith('crt_')) {
    return c.json({ error: 'Invalid API key format — must start with vnt_ or crt_' }, 400);
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
      // Increment failed-attempt counter only on auth failure
      if (rlKey) {
        try {
          const cur = parseInt(await c.env.KV.get(rlKey) ?? '0', 10);
          await c.env.KV.put(rlKey, String(cur + 1), { expirationTtl: 300 });
        } catch { /* KV unavailable */ }
      }
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

  // Set HTTP-only cookie.
  // Production: __Host- prefix enforces Secure + Path=/ + no Domain= (origin-bound,
  // not leaked to subdomains). SameSite=None is required because the API
  // (api.cohrint.com) and frontend (cohrint.com) are different origins.
  // Non-prod: plain name + SameSite=Lax so cookie works on localhost without Secure.
  const isProd = (c.env.ENVIRONMENT ?? 'production') === 'production';
  const cookieParts = isProd
    ? [
        `__Host-cohrint_session=${token}`,
        `Path=/`,
        `HttpOnly`,
        `SameSite=None`,
        `Max-Age=${30 * 86_400}`,
        `Secure`,
      ]
    : [
        `cohrint_session=${token}`,
        `Path=/`,
        `HttpOnly`,
        `Max-Age=${30 * 86_400}`,
        `SameSite=Lax`,
      ];

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
    'SELECT name, email, plan, budget_usd, api_key_hint, created_at, account_type FROM orgs WHERE id = ?'
  ).bind(orgId).first<{ name: string; email: string; plan: string; budget_usd: number; api_key_hint: string; created_at: number; account_type: string }>();

  let memberInfo: { name: string | null; email: string | null } | null = null;
  if (memberId) {
    memberInfo = await c.env.DB.prepare(
      'SELECT name, email FROM org_members WHERE id = ? AND org_id = ?'
    ).bind(memberId, orgId).first<{ name: string | null; email: string | null }>() ?? null;
  }

  // Generate a short-lived SSE token (32 hex chars = 16 random bytes)
  const sseTokenBytes = new Uint8Array(16);
  crypto.getRandomValues(sseTokenBytes);
  const sseToken = Array.from(sseTokenBytes).map(b => b.toString(16).padStart(2, '0')).join('');

  // Store in KV with 1-hour TTL — reusable across reconnects within the session.
  // If KV write fails (e.g. free tier limit), return null sse_token so the
  // client knows SSE is unavailable instead of getting a phantom token.
  let sseTokenFinal: string | null = sseToken;
  try {
    await c.env.KV.put(`sse:${orgId}:${sseToken}`, '1', { expirationTtl: 3600 });
  } catch {
    sseTokenFinal = null; // KV unavailable — SSE disabled for this session
  }

  return c.json({
    authenticated: true,
    org_id:       orgId,
    role,
    account_type: org?.account_type ?? 'organization',
    member_id: memberId,
    // Top-level convenience fields (tests expect these)
    email:        memberId ? (memberInfo?.email ?? org?.email) : org?.email,
    api_key_hint: org?.api_key_hint ?? null,
    org: {
      name:         org?.name,
      email:        org?.email,
      plan:         org?.plan ?? 'free',
      budget_usd:   org?.budget_usd ?? 0,
      api_key_hint: org?.api_key_hint ?? null,
      account_type: org?.account_type ?? 'organization',
      created_at:   org?.created_at ? new Date(org.created_at * 1000).toISOString() : null,
    },
    member: memberInfo,
    sse_token: sseTokenFinal,
    sse_url:   sseTokenFinal
      ? `https://api.cohrint.com/v1/stream/${orgId}?sse_token=${sseTokenFinal}`
      : null,
  });
});

// ── Shared logout helper ──────────────────────────────────────────────────────
function cookieValue(header: string, name: string): string | null {
  for (const part of header.split(';')) {
    const trimmed = part.trim();
    const eq = trimmed.indexOf('=');
    if (eq === -1) continue;
    if (trimmed.slice(0, eq) === name) return trimmed.slice(eq + 1) || null;
  }
  return null;
}

async function destroySession(
  db: D1Database,
  cookieHeader: string,
): Promise<void> {
  const token = cookieValue(cookieHeader, '__Host-cohrint_session')
    ?? cookieValue(cookieHeader, 'cohrint_session');
  if (token) {
    await db.prepare('DELETE FROM sessions WHERE token = ?').bind(token).run();
  }
}

function clearCookieHeader(isProd: boolean): string[] {
  // Clear both __Host- (new) and plain (legacy) names so clients transitioning
  // between versions are fully logged out.
  if (isProd) {
    return [
      '__Host-cohrint_session=; Path=/; HttpOnly; Max-Age=0; SameSite=None; Secure',
      'cohrint_session=; Path=/; HttpOnly; Max-Age=0; SameSite=None; Secure; Domain=cohrint.com',
    ];
  }
  return ['cohrint_session=; Path=/; HttpOnly; Max-Age=0; SameSite=Lax'];
}

// ── DELETE /v1/auth/session — logout, destroy session cookie ─────────────────
auth.delete('/session', async (c) => {
  await destroySession(c.env.DB, c.req.header('Cookie') ?? '');
  const isProd = (c.env.ENVIRONMENT ?? 'production') === 'production';
  const res = await c.json({ ok: true });
  for (const val of clearCookieHeader(isProd)) {
    res.headers.append('Set-Cookie', val);
  }
  return res;
});

// ── POST /v1/auth/logout — alias for DELETE /session (tests + convenience) ───
auth.post('/logout', async (c) => {
  await destroySession(c.env.DB, c.req.header('Cookie') ?? '');
  const isProd = (c.env.ENVIRONMENT ?? 'production') === 'production';
  const res = await c.json({ ok: true });
  for (const val of clearCookieHeader(isProd)) {
    res.headers.append('Set-Cookie', val);
  }
  return res;
});

// ── POST /v1/auth/rotate — rotate the org owner key ──────────────────────────
auth.post('/rotate', authMiddleware, async (c) => {
  const orgId = c.get('orgId');
  const role  = c.get('role');
  if (role !== 'owner') return c.json({ error: 'Only the org owner can rotate the root key' }, 403);

  const rawKey  = `crt_${orgId}_${randomHex(16)}`;
  const keyHash = await sha256hex(rawKey);
  const keyHint = `${rawKey.slice(0, 12)}...`;

  await c.env.DB.prepare(
    'UPDATE orgs SET api_key_hash = ?, api_key_hint = ? WHERE id = ?'
  ).bind(keyHash, keyHint, orgId).run();

  logAudit(c, {
    event_type:    'admin_action',
    event_name:    'key.rotated',
    resource_type: 'org',
    metadata:      { key_hint: keyHint, scope: 'owner' },
  });

  return c.json({
    ok:      true,
    api_key: rawKey,
    hint:    keyHint,
    note:    'Your previous key is immediately revoked. Update it everywhere before closing this response.',
  });
});

export { auth };
