import { Hono } from 'hono';
import { Bindings, Variables } from '../types';
import { authMiddleware, adminOnly } from '../middleware/auth';
import { nowUnix } from '../lib/db-dates';

// Bump this whenever a meaningful dashboard version ships to production.
const LATEST_VERSION = 'v1.4.0';

const CHANGELOG: Array<{ version: string; date: string; summary: string }> = [
  { version: 'v1.4.0', date: '2025-04-18', summary: 'Semantic cache (R2), prompt registry, OTel metrics, team management, CEO executive dashboard, anomaly detection, audit log' },
  { version: 'v1.3.0', date: '2025-02-15', summary: 'Cross-platform analytics, GitHub Copilot connector, Datadog export, benchmark leaderboard' },
  { version: 'v1.2.0', date: '2024-12-01', summary: 'Budget policies, alert notifications, agent traces, member invites, API key scoping' },
  { version: 'v1.0.0', date: '2024-10-01', summary: 'Initial release: LLM cost tracking, KPI dashboard, model breakdown, real-time streaming' },
];

const versions = new Hono<{ Bindings: Bindings; Variables: Variables }>();

versions.use('*', authMiddleware, adminOnly);

versions.get('/', async (c) => {
  const orgId = c.get('orgId');

  const row = await c.env.DB.prepare(
    'SELECT current_version, upgraded_at FROM org_versions WHERE org_id = ?'
  ).bind(orgId).first<{ current_version: string; upgraded_at: number | null }>();

  const currentVersion = row?.current_version ?? 'v1.0.0';

  return c.json({
    current_version: currentVersion,
    latest_version: LATEST_VERSION,
    can_upgrade: currentVersion !== LATEST_VERSION,
    upgraded_at: row?.upgraded_at ?? null,
    changelog: CHANGELOG,
  });
});

versions.post('/upgrade', async (c) => {
  const orgId = c.get('orgId');
  const now = nowUnix();

  await c.env.DB.prepare(`
    INSERT INTO org_versions (org_id, current_version, upgraded_at)
    VALUES (?, ?, ?)
    ON CONFLICT (org_id) DO UPDATE SET current_version = excluded.current_version, upgraded_at = excluded.upgraded_at
  `).bind(orgId, LATEST_VERSION, now).run();

  return c.json({ upgraded: true, version: LATEST_VERSION, upgraded_at: now });
});

export { versions };
