/**
 * Anomaly Detection — Cost Spike Alert
 *
 * Problem: A team accidentally puts an agent in an infinite loop at 2am. $500 in 10 minutes.
 *
 * Algorithm: Z-score on rolling 7-day hourly cost.
 *   z_score = (current_hour_cost - mean) / max(stdev, 0.001)
 *   anomaly if z_score > 3.0  (3-sigma threshold)
 *
 * Runs as a Cloudflare Cron Trigger every 10 minutes.
 * For each org with trigger_anomaly enabled:
 *   1. Query last 10 minutes of cost from D1
 *   2. Query rolling 7-day hourly cost history
 *   3. Compute Z-score
 *   4. If z_score > 3.0, fire Slack alert (throttled to 1 per hour per org)
 */

import { sendSlackMessage } from '../routes/alerts';

// ── Stats helpers ────────────────────────────────────────────────────────────

function mean(values: number[]): number {
  if (values.length === 0) return 0;
  return values.reduce((s, v) => s + v, 0) / values.length;
}

function stdev(values: number[]): number {
  if (values.length < 2) return 0;
  const m = mean(values);
  const variance = values.reduce((s, v) => s + (v - m) ** 2, 0) / (values.length - 1);
  return Math.sqrt(variance);
}

function zScore(current: number, historicalMean: number, historicalStd: number): number {
  return (current - historicalMean) / Math.max(historicalStd, 0.001);
}

// ── Core detection ───────────────────────────────────────────────────────────

interface AnomalyResult {
  orgId:       string;
  currentCost: number;
  meanCost:    number;
  stdCost:     number;
  zScore:      number;
  isAnomaly:   boolean;
  topModel:    string;
  topTeam:     string;
  eventCount:  number;
}

async function detectAnomalyForOrg(
  db: D1Database,
  orgId: string,
): Promise<AnomalyResult | null> {
  const now = Math.floor(Date.now() / 1000);
  const tenMinAgo  = now - 600;        // last 10 minutes
  const sevenDaysAgo = now - 7 * 86400; // 7-day window

  // 1. Current window cost (last 10 minutes)
  const current = await db.prepare(`
    SELECT COALESCE(SUM(cost_usd), 0) as cost,
           COUNT(*) as cnt,
           COALESCE(MAX(model), '') as top_model,
           COALESCE(MAX(team), '') as top_team
    FROM events
    WHERE org_id = ? AND created_at >= ?
  `).bind(orgId, tenMinAgo).first<{
    cost: number; cnt: number; top_model: string; top_team: string;
  }>();

  if (!current || current.cost === 0) return null; // no activity

  // 2. Historical hourly costs (7-day rolling window, grouped by hour)
  const history = await db.prepare(`
    SELECT (created_at / 3600) as hour_bucket,
           SUM(cost_usd) as hour_cost
    FROM events
    WHERE org_id = ? AND created_at >= ? AND created_at < ?
    GROUP BY hour_bucket
    ORDER BY hour_bucket
  `).bind(orgId, sevenDaysAgo, tenMinAgo).all<{
    hour_bucket: number; hour_cost: number;
  }>();

  const hourlyCosts = history.results?.map(r => r.hour_cost) ?? [];

  // Need at least 24 hours of data for meaningful Z-score
  if (hourlyCosts.length < 24) return null;

  // Normalize current 10-min cost to hourly rate for comparison
  const currentHourlyRate = current.cost * 6; // 10min → 1hr

  const m = mean(hourlyCosts);
  const s = stdev(hourlyCosts);
  const z = zScore(currentHourlyRate, m, s);

  // Find actual top model and team in the spike window
  const topModelRow = await db.prepare(`
    SELECT model, SUM(cost_usd) as cost
    FROM events
    WHERE org_id = ? AND created_at >= ?
    GROUP BY model ORDER BY cost DESC LIMIT 1
  `).bind(orgId, tenMinAgo).first<{ model: string; cost: number }>();

  const topTeamRow = await db.prepare(`
    SELECT team, SUM(cost_usd) as cost
    FROM events
    WHERE org_id = ? AND created_at >= ?
    GROUP BY team ORDER BY cost DESC LIMIT 1
  `).bind(orgId, tenMinAgo).first<{ team: string; cost: number }>();

  return {
    orgId,
    currentCost: current.cost,
    meanCost:    m,
    stdCost:     s,
    zScore:      z,
    isAnomaly:   z > 3.0,
    topModel:    topModelRow?.model ?? 'unknown',
    topTeam:     topTeamRow?.team ?? 'unknown',
    eventCount:  current.cnt,
  };
}

// ── Alert formatting ─────────────────────────────────────────────────────────

function formatAnomalyAlert(result: AnomalyResult): Record<string, unknown> {
  const severity = result.zScore > 5.0 ? '🔴 CRITICAL' :
                   result.zScore > 4.0 ? '🟠 HIGH' : '🟡 WARNING';

  const projectedHour = (result.currentCost * 6).toFixed(2);

  return {
    text: `${severity} Cost anomaly detected for org ${result.orgId}`,
    blocks: [
      {
        type: 'header',
        text: { type: 'plain_text', text: `${severity} Cost Spike Detected` },
      },
      {
        type: 'section',
        fields: [
          { type: 'mrkdwn', text: `*Org:*\n${result.orgId}` },
          { type: 'mrkdwn', text: `*Z-Score:*\n${result.zScore.toFixed(1)} (threshold: 3.0)` },
          { type: 'mrkdwn', text: `*Last 10 min:*\n$${result.currentCost.toFixed(2)} (${result.eventCount} calls)` },
          { type: 'mrkdwn', text: `*Projected hourly:*\n$${projectedHour}/hr` },
          { type: 'mrkdwn', text: `*Normal avg:*\n$${result.meanCost.toFixed(2)}/hr ± $${result.stdCost.toFixed(2)}` },
          { type: 'mrkdwn', text: `*Top model:*\n${result.topModel}` },
        ],
      },
      {
        type: 'section',
        text: {
          type: 'mrkdwn',
          text: result.topTeam !== 'unknown'
            ? `*Team:* ${result.topTeam} — <https://vantageaiops.com/app.html|View dashboard →>`
            : `<https://vantageaiops.com/app.html|View dashboard →>`,
        },
      },
      {
        type: 'context',
        elements: [{
          type: 'mrkdwn',
          text: `Detected at ${new Date().toISOString()} · VantageAI Anomaly Detection`,
        }],
      },
    ],
  };
}

// ── Cron handler ─────────────────────────────────────────────────────────────

export async function runAnomalyDetection(
  db: D1Database,
  kv: KVNamespace,
): Promise<{ checked: number; anomalies: number; alerts_sent: number }> {
  let checked = 0, anomalies = 0, alertsSent = 0;

  // Get all orgs with anomaly alerts enabled
  const configs = await db.prepare(`
    SELECT ac.org_id, ac.slack_url
    FROM alert_configs ac
    WHERE ac.trigger_anomaly = 1 AND ac.slack_url IS NOT NULL
  `).all<{ org_id: string; slack_url: string }>();

  if (!configs.results?.length) {
    return { checked: 0, anomalies: 0, alerts_sent: 0 };
  }

  for (const cfg of configs.results) {
    checked++;

    try {
      const result = await detectAnomalyForOrg(db, cfg.org_id);
      if (!result || !result.isAnomaly) continue;

      anomalies++;

      // Throttle: 1 anomaly alert per org per hour
      const throttleKey = `alert:${cfg.org_id}:anomaly`;
      const alreadySent = await kv.get(throttleKey);
      if (alreadySent) continue;

      // Send Slack alert
      const payload = formatAnomalyAlert(result);
      const sent = await sendSlackMessage(cfg.slack_url, payload);

      if (sent) {
        alertsSent++;
        // Throttle for 1 hour
        await kv.put(throttleKey, JSON.stringify({
          z_score: result.zScore,
          cost: result.currentCost,
          detected_at: new Date().toISOString(),
        }), { expirationTtl: 3600 });

        // Also store in KV for dashboard visibility
        await kv.put(`anomaly:${cfg.org_id}:latest`, JSON.stringify(result), {
          expirationTtl: 86400, // visible for 24 hours
        });
      }
    } catch (err) {
      console.error(`[anomaly] Error checking org ${cfg.org_id}:`, err);
    }
  }

  return { checked, anomalies, alerts_sent: alertsSent };
}
