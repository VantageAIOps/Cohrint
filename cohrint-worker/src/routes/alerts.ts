import { Hono } from 'hono';
import { Bindings, Variables } from '../types';
import { authMiddleware, adminOnly } from '../middleware/auth';
import { logAudit } from '../lib/audit';

const alerts = new Hono<{ Bindings: Bindings; Variables: Variables }>();

alerts.use('*', authMiddleware);

// NOTE on URL shape: the legacy routes include `/:orgId` in the path but the
// handlers always read orgId from the authenticated context (c.get('orgId')),
// so the URL segment is decorative and cannot be used to access another org's
// config. We keep the `/:orgId` shape for backwards compatibility with the
// frontend and external callers.

// Validate that a URL has protocol=https and hostname exactly === hooks.slack.com.
// Prevents bypasses like https://hooks.slack.com.evil.com/... which pass a naive
// startsWith('https://hooks.slack.com/') check.
function isValidSlackWebhook(raw: unknown): boolean {
  if (typeof raw !== 'string') return false;
  try {
    const u = new URL(raw);
    return u.protocol === 'https:' && u.hostname === 'hooks.slack.com';
  } catch {
    return false;
  }
}

// ── POST /v1/alerts/slack/:orgId — save webhook URL (admin only) ─────────────
alerts.post('/slack/:orgId', adminOnly, async (c) => {
  const orgId = c.get('orgId');
  const body  = await c.req.json<{
    webhook_url:      string;
    trigger_budget?:  boolean;
    trigger_anomaly?: boolean;
    trigger_daily?:   boolean;
  }>();

  if (!isValidSlackWebhook(body.webhook_url)) {
    return c.json({ error: 'Invalid Slack webhook URL' }, 400);
  }

  await c.env.DB.prepare(`
    INSERT INTO alert_configs (org_id, slack_url, trigger_budget, trigger_anomaly, trigger_daily, updated_at)
    VALUES (?, ?, ?, ?, ?, unixepoch())
    ON CONFLICT(org_id) DO UPDATE SET
      slack_url        = excluded.slack_url,
      trigger_budget   = excluded.trigger_budget,
      trigger_anomaly  = excluded.trigger_anomaly,
      trigger_daily    = excluded.trigger_daily,
      updated_at       = excluded.updated_at
  `).bind(
    orgId,
    body.webhook_url,
    body.trigger_budget  !== false ? 1 : 0,
    body.trigger_anomaly !== false ? 1 : 0,
    body.trigger_daily   !== false ? 1 : 0,
  ).run();

  // Cache in KV for fast lookup during event ingest (best-effort — D1 is the source of truth)
  try { await c.env.KV.put(`slack:${orgId}`, body.webhook_url, { expirationTtl: 3600 }); }
  catch { /* KV write limit reached — cached only in D1 */ }

  logAudit(c, {
    event_type:    'admin_action',
    event_name:    'admin_action.alert_config_changed',
    resource_type: 'alert_config',
  });

  return c.json({ ok: true });
});

// ── POST /v1/alerts/slack/:orgId/test — send a test message (admin only) ─────
alerts.post('/slack/:orgId/test', adminOnly, async (c) => {
  const orgId = c.get('orgId');

  const cfg = await c.env.DB.prepare(
    'SELECT slack_url FROM alert_configs WHERE org_id = ?'
  ).bind(orgId).first<{ slack_url: string }>();

  if (!cfg?.slack_url) {
    return c.json({ error: 'No Slack webhook configured for this org' }, 404);
  }

  const sent = await sendSlackMessage(cfg.slack_url, {
    text: '✅ *Cohrint* — test alert from your workspace. Webhooks are working!',
    blocks: [{
      type: 'section',
      text: {
        type: 'mrkdwn',
        text: '*✅ Cohrint — Test Alert*\nYour Slack integration is working correctly.\nYou\'ll receive alerts here when budget thresholds or anomalies are detected.',
      },
    }],
  });

  if (!sent) return c.json({ error: 'Failed to deliver message to Slack' }, 502);
  return c.json({ ok: true, message: 'Test message sent' });
});

// ── GET /v1/alerts/:orgId — get current config ───────────────────────────────
alerts.get('/:orgId', async (c) => {
  const orgId = c.get('orgId');
  const cfg   = await c.env.DB.prepare(
    'SELECT slack_url, trigger_budget, trigger_anomaly, trigger_daily, updated_at FROM alert_configs WHERE org_id = ?'
  ).bind(orgId).first();

  return c.json(cfg ?? { slack_url: null });
});

// ── GET /v1/alerts/:orgId/anomaly — latest anomaly detection result ───────────
alerts.get('/:orgId/anomaly', async (c) => {
  const orgId = c.get('orgId');

  // Check KV for latest anomaly result (stored by cron)
  const latest = await c.env.KV.get(`anomaly:${orgId}:latest`);
  if (!latest) {
    return c.json({ anomaly: false, message: 'No anomalies detected in the last 24 hours' });
  }

  try {
    const result = JSON.parse(latest);
    return c.json({ anomaly: true, ...result });
  } catch {
    return c.json({ anomaly: false });
  }
});

// ── Shared Slack sender ───────────────────────────────────────────────────────
export async function sendSlackMessage(
  webhookUrl: string,
  payload: Record<string, unknown>,
): Promise<boolean> {
  try {
    const res = await fetch(webhookUrl, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify(payload),
    });
    return res.ok;
  } catch {
    return false;
  }
}

// ── Budget alert helper (called from event ingest pipeline) ──────────────────
export async function maybeSendBudgetAlert(
  db: D1Database,
  kv: KVNamespace,
  orgId: string,
  mtdCost: number,
  budgetUsd: number,
): Promise<void> {
  if (!budgetUsd) return;

  const pct = (mtdCost / budgetUsd) * 100;
  let alertType: string | null = null;
  if (pct >= 100) alertType = 'budget_100';
  else if (pct >= 80) alertType = 'budget_80';
  if (!alertType) return;

  // Throttle: only fire once per hour per alert type
  const throttleKey = `alert:${orgId}:${alertType}`;
  const alreadySent = await kv.get(throttleKey);
  if (alreadySent) return;

  const slackUrl = await kv.get(`slack:${orgId}`)
    ?? (await db.prepare('SELECT slack_url FROM alert_configs WHERE org_id = ?').bind(orgId).first<{ slack_url: string }>())?.slack_url;
  if (!slackUrl) return;

  const emoji = pct >= 100 ? '🚨' : '⚠️';
  await sendSlackMessage(slackUrl, {
    text: `${emoji} Cohrint budget alert for org ${orgId}`,
    blocks: [{
      type: 'section',
      text: {
        type: 'mrkdwn',
        text: `${emoji} *Budget Alert — ${Math.round(pct)}% used*\nOrg *${orgId}* has spent *$${mtdCost.toFixed(2)}* of *$${budgetUsd.toFixed(2)}* this month.\n<https://cohrint.com/app.html|View dashboard →>`,
      },
    }],
  });

  // Throttle for 1 hour
  await kv.put(throttleKey, '1', { expirationTtl: 3600 });
}

export { alerts };
