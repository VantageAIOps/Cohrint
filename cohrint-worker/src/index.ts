/**
 * Cohrint — Cloudflare Worker
 *
 * Architecture:
 *   Workers  — globally distributed API (this file)
 *   D1       — SQLite events + org config (binding: DB)
 *   KV       — rate limiting + SSE pub/sub + alert throttling (binding: KV)
 *   Pages    — frontend at cohrint.com
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
 *   GET  /v1/teams                        (admin — list org teams)
 *   POST /v1/teams                        (admin — create team)
 *   DELETE /v1/teams/:id                  (admin — soft-delete team)
 *   GET  /v1/teams/:id/members            (admin — list team members)
 *   POST /v1/copilot/connect             (admin — store GitHub org + PAT encrypted in KV)
 *   DELETE /v1/copilot/connect           (admin — remove Copilot connection)
 *   GET  /v1/copilot/status              (list Copilot connections + last sync time)
 *   POST /v1/cache/lookup               (auth — find semantically similar cached response)
 *   POST /v1/cache/store                (auth — store prompt+response embedding)
 *   GET  /v1/cache/stats                (auth — hit rate, savings, recent entries)
 *   PATCH /v1/cache/config              (admin — update org cache config)
 *   DELETE /v1/cache/entries/:id        (admin — remove cache entry)
 *   GET  /v1/prompts                    (auth — list versioned prompt templates)
 *   POST /v1/prompts                    (admin — create prompt)
 *   GET  /v1/prompts/:id                (auth — prompt + all versions)
 *   PATCH /v1/prompts/:id               (admin — update prompt metadata)
 *   DELETE /v1/prompts/:id              (admin — soft delete)
 *   POST /v1/prompts/:id/versions       (admin — add version)
 *   GET  /v1/prompts/:id/versions/:vid  (auth — full version content)
 *   POST /v1/prompts/usage              (auth — attribute event to version)
 *   GET  /v1/prompts/analytics/comparison (auth — cost delta across versions)
 *
 * Cron Triggers:
 *   Every 10 min  — anomaly detection (Z-score cost spike alerts)
 *                 — GitHub Copilot Metrics sync (daily per-org KV guard, no-op if already ran today)
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
import { sessions }    from './routes/sessions';
import { copilot, syncCopilotMetrics } from './routes/copilot';
import { datadog, syncDatadogMetrics } from './routes/datadog';
import { benchmark, syncBenchmarkContributions } from './routes/benchmark';
import { executive } from './routes/executive';
import { teams }     from './routes/teams';
import { cache }     from './routes/cache';
import { prompts }   from './routes/prompts';
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
app.route('/v1/sessions',       sessions);  // OTel session rollup
app.route('/v1/copilot',        copilot);   // GitHub Copilot Metrics API adapter
app.route('/v1/datadog',        datadog);   // Datadog metrics exporter
app.route('/v1/benchmark',      benchmark); // Anonymized cross-company benchmarks
app.route('/v1/analytics/executive', executive); // CEO/superadmin unified dashboard
app.route('/v1/teams',              teams);      // Team CRUD (org accounts only)
app.route('/v1/cache',              cache);      // Semantic cache (Vectorize + Workers AI)
app.route('/v1/prompts',            prompts);    // Prompt registry + version cost tracking

// ── 404 fallback ──────────────────────────────────────────────────────────────
app.notFound((c) => c.json({
  error: 'Not found',
  docs:  'https://cohrint.com/docs.html',
}, 404));

// ── Global error handler ──────────────────────────────────────────────────────
app.onError((err, c) => {
  console.error('[vantageai]', err);
  const origin  = c.req.header('Origin') ?? '';
  const allowed = (c.env.ALLOWED_ORIGINS ?? '').split(',').map(s => s.trim()).filter(Boolean);
  const isAllowed = allowed.includes(origin) ||
    allowed.some(p => p.endsWith('*') && origin.startsWith(p.slice(0, -1)));
  // Per CORS spec, Access-Control-Allow-Origin: * is INVALID when credentials
  // are true. Only echo a concrete matching origin; otherwise omit CORS headers
  // entirely so the browser blocks the response (safer default for an error path).
  const headers: Record<string, string> = { 'Vary': 'Origin' };
  if (isAllowed && origin) {
    headers['Access-Control-Allow-Origin']      = origin;
    headers['Access-Control-Allow-Credentials'] = 'true';
  }
  return c.json({ error: 'Internal server error' }, 500, headers);
});

// ── Export with scheduled handler for cron-based anomaly detection ────────────
export default {
  fetch: app.fetch,
  async scheduled(event: ScheduledEvent, env: Bindings, ctx: ExecutionContext) {
    ctx.waitUntil((async () => {
      // ── Anomaly detection (every 10 min) ─────────────────────────────────
      try {
        const result = await runAnomalyDetection(env.DB, env.KV);
        console.log(`[anomaly-cron] checked=${result.checked} anomalies=${result.anomalies} alerts=${result.alerts_sent}`);
      } catch (err) {
        console.error('[anomaly-cron] Fatal error:', err);
      }

      // ── GitHub Copilot Metrics sync (daily — guarded by KV per-day key) ──
      // syncCopilotMetrics internally skips orgs already synced today,
      // so it's safe to attempt on every 10-min tick.
      try {
        const results = await syncCopilotMetrics(env);
        const synced  = results.filter(r => !r.skipped && !r.error);
        const errors  = results.filter(r => r.error);
        if (synced.length > 0 || errors.length > 0) {
          console.log(`[copilot-cron] synced=${synced.length} skipped=${results.filter(r => r.skipped).length} errors=${errors.length}`);
          for (const e of errors) {
            console.error(`[copilot-cron] ${e.github_org}: ${e.error}`);
          }
        }
      } catch (err) {
        console.error('[copilot-cron] Fatal error:', err);
      }

      // ── Datadog Metrics push (daily — guarded by KV per-day key) ─────────
      // syncDatadogMetrics internally skips orgs already pushed today,
      // so it's safe to call on every 10-min tick.
      try {
        const ddResults = await syncDatadogMetrics(env);
        const ddSynced  = ddResults.filter(r => !r.skipped && !r.error);
        const ddErrors  = ddResults.filter(r => r.error);
        if (ddSynced.length > 0 || ddErrors.length > 0) {
          console.log(`[datadog-cron] pushed=${ddSynced.length} skipped=${ddResults.filter(r => r.skipped).length} errors=${ddErrors.length}`);
          for (const e of ddErrors) {
            console.error(`[datadog-cron] org=${e.org_id}: ${e.error}`);
          }
        }
      } catch (err) {
        console.error('[datadog-cron] Fatal error:', err);
      }

      // ── Benchmark contributions (Sundays UTC only) ────────────────────────
      // syncBenchmarkContributions checks day-of-week internally and is a
      // no-op on non-Sunday ticks, so safe to call on every cron tick.
      try {
        await syncBenchmarkContributions(env);
      } catch (err) {
        console.error('[benchmark-cron] Fatal error:', err);
      }
    })());
  },
};
