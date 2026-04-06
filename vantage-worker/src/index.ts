/**
 * VantageAI — Cloudflare Worker
 *
 * Architecture:
 *   Workers  — globally distributed API (this file)
 *   D1       — SQLite events + org config (binding: DB)
 *   KV       — rate limiting + SSE pub/sub + alert throttling (binding: KV)
 *   Pages    — frontend at vantageaiops.com
 *
 * Endpoints:
 *   GET  /health
 *   POST /v1/auth/signup             (public — create account + API key)
 *   POST /v1/events
 *   POST /v1/events/batch
 *   PATCH /v1/events/:id/scores
 *   GET  /v1/analytics/summary
 *   GET  /v1/analytics/kpis
 *   GET  /v1/analytics/timeseries
 *   GET  /v1/analytics/models
 *   GET  /v1/analytics/teams
 *   GET  /v1/analytics/traces
 *   GET  /v1/analytics/cost          (CI cost gate)
 *   GET  /v1/stream/:orgId           (SSE live stream)
 *   POST /v1/alerts/slack/:orgId
 *   POST /v1/alerts/slack/:orgId/test
 *   GET  /v1/alerts/:orgId
 *   POST /v1/auth/members            (admin — invite member, get scoped key)
 *   GET  /v1/auth/members            (admin — list members)
 *   PATCH /v1/auth/members/:id       (admin — update role or scope)
 *   DELETE /v1/auth/members/:id      (admin — revoke member key)
 *   GET  /v1/admin/overview          (admin — org-wide stats + teams + members)
 *   GET  /v1/admin/members/:id/usage (admin — usage for one member)
 *   GET  /v1/admin/team-budgets      (admin — list team budgets)
 *   PUT  /v1/admin/team-budgets/:team (admin — set team budget)
 *   DELETE /v1/admin/team-budgets/:team (admin — remove team budget)
 *   POST /v1/superadmin/auth            (superadmin — validate secret)
 *   GET  /v1/superadmin/stats           (superadmin — platform overview)
 *   GET  /v1/superadmin/users           (superadmin — signup + session activity)
 *   GET  /v1/superadmin/geography       (superadmin — country + colo breakdown)
 *   GET  /v1/superadmin/features        (superadmin — feature/model/provider usage)
 *   GET  /v1/superadmin/traffic         (superadmin — daily traffic timeseries)
 *   GET  /v1/superadmin/storage         (superadmin — DB table sizes + KV count)
 *   POST /v1/superadmin/reset           (superadmin — soft/hard reset storage)
 *   POST /v1/platform/pageview          (public — record frontend pageview)
 *   POST /v1/platform/session           (public — record session duration)
 *   POST /v1/optimizer/compress          (prompt compression)
 *   POST /v1/optimizer/analyze           (token count + cost estimate)
 *   POST /v1/optimizer/estimate          (cross-model cost comparison)
 *   GET  /v1/optimizer/stats             (optimizer usage stats)
 *   POST /v1/otel/v1/metrics             (OTLP metrics — Claude Code, Copilot, Gemini CLI)
 *   POST /v1/otel/v1/logs                (OTLP events — api_request, tool_result, etc.)
 *   POST /v1/otel/v1/traces              (OTLP traces — future)
 *
 * Cron Triggers:
 *   Every 10 min  — anomaly detection (Z-score cost spike alerts)
 */

import { Hono } from 'hono';
import { VERSION } from './_version';
import { Bindings, Variables } from './types';
import { corsMiddleware } from './middleware/cors';
import { auth }       from './routes/auth';
import { events }     from './routes/events';
import { analytics }  from './routes/analytics';
import { stream }     from './routes/stream';
import { alerts }     from './routes/alerts';
import { admin }      from './routes/admin';
import { superadmin } from './routes/superadmin';
import { platform }   from './routes/platform';
import { optimizer }  from './routes/optimizer';
import { otel }       from './routes/otel';
import { crossplatform } from './routes/crossplatform';
import { auditlog }    from './routes/auditlog';
import { runAnomalyDetection } from './lib/anomaly';

const app = new Hono<{ Bindings: Bindings; Variables: Variables }>();

// ── Global middleware ─────────────────────────────────────────────────────────
app.use('*', corsMiddleware);

// ── Health check (no auth) ────────────────────────────────────────────────────
const healthResponse = (c: any) => c.json({
  status:  'ok',
  service: 'vantage-api',
  version: VERSION,
  region:  (c.req.raw as Request & { cf?: { colo?: string } }).cf?.colo ?? 'unknown',
  ts:      new Date().toISOString(),
});
app.get('/health', healthResponse);
app.get('/v1/health', healthResponse);

// ── API routes ────────────────────────────────────────────────────────────────
app.route('/v1/auth',       auth);
app.route('/v1/events',     events);
app.route('/v1/analytics',  analytics);
app.route('/v1/stream',     stream);
app.route('/v1/alerts',     alerts);
app.route('/v1/admin',      admin);
app.route('/v1/superadmin', superadmin);
app.route('/v1/platform',   platform);
app.route('/v1/optimizer',  optimizer);
app.route('/v1/otel',       otel);      // OpenTelemetry collector (Claude Code, Copilot, Gemini CLI)
app.route('/v1/cross-platform', crossplatform); // Cross-platform cost dashboard API
app.route('/v1/audit-log',      auditlog);

// ── 404 fallback ──────────────────────────────────────────────────────────────
app.notFound((c) => c.json({
  error: 'Not found',
  docs:  'https://vantageaiops.com/docs.html',
}, 404));

// ── Global error handler ──────────────────────────────────────────────────────
app.onError((err, c) => {
  console.error('[vantageai]', err);
  const origin  = c.req.header('Origin') ?? '';
  const allowed = (c.env.ALLOWED_ORIGINS ?? '').split(',').map(s => s.trim());
  const isAllowed = allowed.includes('*') || allowed.includes(origin) ||
    allowed.some(p => p.endsWith('*') && origin.startsWith(p.slice(0, -1)));
  const corsOrigin = isAllowed ? origin : (allowed[0] ?? '*');
  return c.json({ error: 'Internal server error' }, 500, {
    'Access-Control-Allow-Origin':      corsOrigin,
    'Access-Control-Allow-Credentials': 'true',
    'Vary': 'Origin',
  });
});

// ── Export with scheduled handler for cron-based anomaly detection ────────────
export default {
  fetch: app.fetch,
  async scheduled(event: ScheduledEvent, env: Bindings, ctx: ExecutionContext) {
    ctx.waitUntil((async () => {
      try {
        const result = await runAnomalyDetection(env.DB, env.KV);
        console.log(`[anomaly-cron] checked=${result.checked} anomalies=${result.anomalies} alerts=${result.alerts_sent}`);
      } catch (err) {
        console.error('[anomaly-cron] Fatal error:', err);
      }
    })());
  },
};
