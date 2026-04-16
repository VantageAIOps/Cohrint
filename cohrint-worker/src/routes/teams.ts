import { Hono } from 'hono';
import { Bindings, Variables } from '../types';
import { authMiddleware, adminOnly } from '../middleware/auth';
import { logAudit } from '../lib/audit';

const teams = new Hono<{ Bindings: Bindings; Variables: Variables }>();

function randomHex(bytes = 8): string {
  const arr = new Uint8Array(bytes);
  crypto.getRandomValues(arr);
  return Array.from(arr).map(b => b.toString(16).padStart(2, '0')).join('');
}

function toSlug(input: string): string {
  return input
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 32) || 'team';
}

// All team routes require auth
teams.use('*', authMiddleware);

// ── GET /v1/teams — list teams in this org ────────────────────────────────────
teams.get('/', async (c) => {
  const orgId       = c.get('orgId');
  const accountType = c.get('accountType');

  if (accountType !== 'organization') {
    return c.json({ error: 'Teams only exist on organization accounts.' }, 403);
  }

  const { results } = await c.env.DB.prepare(`
    SELECT id, name, datetime(created_at, 'unixepoch') AS created_at
    FROM teams
    WHERE org_id = ? AND deleted_at IS NULL
    ORDER BY created_at ASC
  `).bind(orgId).all();

  return c.json({ teams: results });
});

// ── POST /v1/teams — create a team (admin+ only) ──────────────────────────────
teams.post('/', adminOnly, async (c) => {
  const orgId       = c.get('orgId');
  const accountType = c.get('accountType');

  if (accountType !== 'organization') {
    return c.json({ error: 'Teams can only be created on organization accounts.' }, 403);
  }

  let body: { name?: string; id?: string };
  try { body = await c.req.json(); }
  catch { return c.json({ error: 'Invalid JSON body' }, 400); }

  const name = (body.name ?? '').trim();
  if (!name) return c.json({ error: 'name is required' }, 400);

  let teamId = body.id ? toSlug(body.id) : toSlug(name);

  // Ensure uniqueness within org
  const existing = await c.env.DB.prepare(
    'SELECT id FROM teams WHERE org_id = ? AND id = ? AND deleted_at IS NULL'
  ).bind(orgId, teamId).first();
  if (existing) teamId = `${teamId}-${randomHex(3)}`;

  await c.env.DB.prepare(`
    INSERT INTO teams (id, org_id, name, created_at)
    VALUES (?, ?, ?, unixepoch())
  `).bind(teamId, orgId, name).run();

  logAudit(c, {
    event_type:    'admin_action',
    event_name:    'admin_action.team_created',
    resource_type: 'team',
    resource_id:   teamId,
    metadata:      { name },
  });

  return c.json({ ok: true, team_id: teamId, name }, 201);
});

// ── DELETE /v1/teams/:id — soft-delete a team (admin+ only) ──────────────────
teams.delete('/:id', adminOnly, async (c) => {
  const orgId  = c.get('orgId');
  const teamId = c.req.param('id');

  const team = await c.env.DB.prepare(
    'SELECT id, name FROM teams WHERE org_id = ? AND id = ? AND deleted_at IS NULL'
  ).bind(orgId, teamId).first<{ id: string; name: string }>();

  if (!team) return c.json({ error: 'Team not found' }, 404);

  await c.env.DB.prepare(
    'UPDATE teams SET deleted_at = unixepoch() WHERE org_id = ? AND id = ?'
  ).bind(orgId, teamId).run();

  logAudit(c, {
    event_type:    'admin_action',
    event_name:    'admin_action.team_deleted',
    resource_type: 'team',
    resource_id:   teamId,
    metadata:      { name: team.name },
  });

  return c.json({ ok: true });
});

// ── GET /v1/teams/:id/members — list members of a team (admin+ only) ─────────
teams.get('/:id/members', adminOnly, async (c) => {
  const orgId  = c.get('orgId');
  const teamId = c.req.param('id');

  const team = await c.env.DB.prepare(
    'SELECT id FROM teams WHERE org_id = ? AND id = ? AND deleted_at IS NULL'
  ).bind(orgId, teamId).first();
  if (!team) return c.json({ error: 'Team not found' }, 404);

  const { results } = await c.env.DB.prepare(`
    SELECT id, email, name, role, api_key_hint,
           datetime(created_at, 'unixepoch') AS created_at
    FROM org_members
    WHERE org_id = ? AND team_id = ?
    ORDER BY created_at ASC
  `).bind(orgId, teamId).all();

  return c.json({ team_id: teamId, members: results });
});

// ── POST /v1/teams/:id/members — invite member directly to a team ─────────────
teams.post('/:id/members', adminOnly, async (c) => {
  const orgId       = c.get('orgId');
  const accountType = c.get('accountType');
  const teamId      = c.req.param('id');

  if (accountType !== 'organization') {
    return c.json({ error: 'Team member invite only available on organization accounts.' }, 403);
  }

  const team = await c.env.DB.prepare(
    'SELECT id, name FROM teams WHERE org_id = ? AND id = ? AND deleted_at IS NULL'
  ).bind(orgId, teamId).first<{ id: string; name: string }>();
  if (!team) return c.json({ error: 'Team not found' }, 404);

  let body: { email?: string; name?: string; role?: string };
  try { body = await c.req.json(); }
  catch { return c.json({ error: 'Invalid JSON body' }, 400); }

  const email = (body.email ?? '').trim().toLowerCase();
  if (!email) return c.json({ error: 'email is required' }, 400);

  const VALID_ROLES = ['superadmin', 'member', 'viewer'] as const;
  type ValidRole = typeof VALID_ROLES[number];
  const role = (body.role ?? 'member') as ValidRole;
  if (!VALID_ROLES.includes(role)) {
    return c.json({ error: `role must be one of: ${VALID_ROLES.join(', ')}` }, 400);
  }

  const existing = await c.env.DB.prepare(
    'SELECT id FROM org_members WHERE org_id = ? AND email = ?'
  ).bind(orgId, email).first();
  if (existing) return c.json({ error: 'Member with this email already exists' }, 409);

  const memberId  = `mem_${randomHex(12)}`;
  const rawKey    = `crt_${orgId}_${randomHex(24)}`;
  const keyHash   = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(rawKey))
    .then(b => Array.from(new Uint8Array(b)).map(x => x.toString(16).padStart(2, '0')).join(''));
  const keyHint   = rawKey.slice(-4);
  const memberName = (body.name ?? '').trim() || email.split('@')[0];

  await c.env.DB.prepare(`
    INSERT INTO org_members (id, org_id, email, name, role, api_key_hash, api_key_hint, team_id, created_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, unixepoch())
  `).bind(memberId, orgId, email, memberName, role, keyHash, keyHint, teamId).run();

  logAudit(c, {
    event_type:    'admin_action',
    event_name:    'admin_action.member_invited',
    resource_type: 'member',
    resource_id:   memberId,
    metadata:      { email, role, team_id: teamId },
  });

  return c.json({ ok: true, member_id: memberId, email, role, team_id: teamId, api_key: rawKey }, 201);
});

export { teams };
