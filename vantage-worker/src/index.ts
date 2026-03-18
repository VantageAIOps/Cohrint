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
 */

import { Hono } from 'hono';
import { Bindings, Variables } from './types';
import { corsMiddleware } from './middleware/cors';
import { events }    from './routes/events';
import { analytics } from './routes/analytics';
import { stream }    from './routes/stream';
import { alerts }    from './routes/alerts';

const app = new Hono<{ Bindings: Bindings; Variables: Variables }>();

// ── Global middleware ─────────────────────────────────────────────────────────
app.use('*', corsMiddleware);

// ── Health check (no auth) ────────────────────────────────────────────────────
app.get('/health', (c) => c.json({
  status:  'ok',
  service: 'vantage-api',
  version: '1.0.0',
  region:  (c.req.raw as Request & { cf?: { colo?: string } }).cf?.colo ?? 'unknown',
  ts:      new Date().toISOString(),
}));

// ── API routes ────────────────────────────────────────────────────────────────
app.route('/v1/events',    events);
app.route('/v1/analytics', analytics);
app.route('/v1/stream',    stream);
app.route('/v1/alerts',    alerts);

// ── 404 fallback ──────────────────────────────────────────────────────────────
app.notFound((c) => c.json({
  error: 'Not found',
  docs:  'https://vantageaiops.com/docs.html',
}, 404));

// ── Global error handler ──────────────────────────────────────────────────────
app.onError((err, c) => {
  console.error('[vantage-worker]', err);
  return c.json({ error: 'Internal server error' }, 500);
});

export default app;
