/**
 * Cohrint — Datadog Metrics Exporter
 *
 * Pushes per-developer AI cost metrics from cross_platform_usage into an
 * org's own Datadog account. Additive — does not replace existing Datadog
 * dashboards; it simply adds cohrint.ai.* metrics to them.
 *
 * Endpoints (all require auth):
 *   POST   /v1/datadog/connect   — admin/owner only. Validate + store Datadog API key.
 *   DELETE /v1/datadog/connect   — admin/owner only. Remove connection.
 *   GET    /v1/datadog/status    — admin/owner only. Connection status + last_synced_at.
 *
 * Internal export:
 *   syncDatadogMetrics(env, orgId?) — called from cron. Idempotent daily push.
 *
 * Metrics pushed:
 *   cohrint.ai.cost_usd   — gauge, tags: provider, model, developer_id, org_id
 *   cohrint.ai.tokens     — gauge, tags: provider, model, developer_id, org_id
 *
 * Key storage:
 *   Datadog API keys are AES-256-GCM encrypted (same HKDF as copilot.ts)
 *   and stored in the datadog_connections table. Never logged, never plain.
 *
 * Idempotency:
 *   KV guard key: datadog:last_sync:{orgId}:{YYYY-MM-DD} (23 h TTL)
 *   Prevents double-push on same calendar day even across multiple cron ticks.
 */

import { Hono } from 'hono';
import type { Bindings, Variables } from '../types';
import { authMiddleware, hasRole } from '../middleware/auth';
import { withBreaker } from '../lib/circuit';

const datadog = new Hono<{ Bindings: Bindings; Variables: Variables }>();

datadog.use('*', authMiddleware);

// ── Constants ─────────────────────────────────────────────────────────────────

const ALLOWED_SITES = new Set([
  'datadoghq.com',
  'datadoghq.eu',
  'us3.datadoghq.com',
  'us5.datadoghq.com',
  'ap1.datadoghq.com',
]);

function kvSyncGuardKey(orgId: string, day: string): string {
  return `datadog:last_sync:${orgId}:${day}`;
}

// ── AES-GCM helpers — same HKDF pattern as copilot.ts ────────────────────────

async function deriveKey(orgId: string, secret?: string): Promise<CryptoKey> {
  if (!secret) throw new Error('TOKEN_ENCRYPTION_SECRET is not configured');
  const enc = new TextEncoder();
  const keyMaterial = await crypto.subtle.importKey(
    'raw',
    enc.encode(secret),
    { name: 'HKDF' },
    false,
    ['deriveKey'],
  );
  return crypto.subtle.deriveKey(
    { name: 'HKDF', hash: 'SHA-256', salt: enc.encode(orgId), info: enc.encode('datadog-api-key-v1') },
    keyMaterial,
    { name: 'AES-GCM', length: 256 },
    false,
    ['encrypt', 'decrypt'],
  );
}

async function encryptKey(plaintext: string, orgId: string, secret?: string): Promise<string> {
  const key = await deriveKey(orgId, secret);
  const iv  = crypto.getRandomValues(new Uint8Array(12));
  const buf = await crypto.subtle.encrypt(
    { name: 'AES-GCM', iv },
    key,
    new TextEncoder().encode(plaintext),
  );
  const out = new Uint8Array(12 + buf.byteLength);
  out.set(iv, 0);
  out.set(new Uint8Array(buf), 12);
  return btoa(String.fromCharCode(...out));
}

async function decryptKey(ciphertext: string, orgId: string, secret?: string): Promise<string> {
  const key      = await deriveKey(orgId, secret);
  const combined = Uint8Array.from(atob(ciphertext), c => c.charCodeAt(0));
  const buf = await crypto.subtle.decrypt(
    { name: 'AES-GCM', iv: combined.slice(0, 12) },
    key,
    combined.slice(12),
  );
  return new TextDecoder().decode(buf);
}

// ── Datadog types ─────────────────────────────────────────────────────────────

interface DatadogPoint {
  timestamp: number;
  value: number;
}

interface DatadogSeries {
  metric: string;
  type: number; // 1 = gauge
  points: DatadogPoint[];
  tags: string[];
}

interface DatadogPayload {
  series: DatadogSeries[];
}

// ── cross_platform_usage row (subset) ─────────────────────────────────────────

interface UsageRow {
  provider:        string;
  model:           string | null;
  developer_id:    string;
  cost_usd:        number;
  input_tokens:    number;
  output_tokens:   number;
  period_start:    string;
}

// ── Internal sync helpers ─────────────────────────────────────────────────────

function datadogApiBase(site: string): string {
  return `https://api.${site}`;
}

async function validateDatadogKey(apiKey: string, site: string): Promise<{ valid: boolean; error?: string }> {
  try {
    const resp = await fetch(`${datadogApiBase(site)}/api/v1/validate`, {
      headers: {
        'DD-API-KEY': apiKey,
        Accept: 'application/json',
      },
    });
    if (resp.ok) return { valid: true };
    if (resp.status === 403) return { valid: false, error: 'Invalid Datadog API key' };
    const body = await resp.text();
    return { valid: false, error: `Datadog validate returned ${resp.status}: ${body.slice(0, 200)}` };
  } catch (err: unknown) {
    return { valid: false, error: `Network error reaching ${site}: ${err instanceof Error ? err.message : String(err)}` };
  }
}

async function pushToDatadog(
  payload: DatadogPayload,
  apiKey: string,
  site: string,
): Promise<{ ok: boolean; error?: string }> {
  try {
    const resp = await fetch(`${datadogApiBase(site)}/api/v2/series`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'DD-API-KEY': apiKey,
      },
      body: JSON.stringify(payload),
    });
    if (resp.ok) return { ok: true };
    const body = await resp.text();
    return { ok: false, error: `Datadog /api/v2/series returned ${resp.status}: ${body.slice(0, 300)}` };
  } catch (err: unknown) {
    return { ok: false, error: err instanceof Error ? err.message : String(err) };
  }
}

// ── Core sync function ────────────────────────────────────────────────────────

export interface DatadogSyncResult {
  org_id:        string;
  series_pushed: number;
  skipped:       boolean;
  error?:        string;
}

/**
 * Sync one org: query last 24 h of cross_platform_usage and push to Datadog.
 * Idempotent via KV guard (23 h TTL per calendar day).
 */
export async function syncDatadogMetricsForOrg(
  env: Bindings,
  orgId: string,
): Promise<DatadogSyncResult> {
  const todayUtc = new Date().toISOString().slice(0, 10);
  const guardKey = kvSyncGuardKey(orgId, todayUtc);

  if (await env.KV.get(guardKey)) {
    return { org_id: orgId, series_pushed: 0, skipped: true };
  }

  // Load connection BEFORE writing the guard. If decryption fails, we must not
  // lock out the next cron tick — the user may reconnect and retry immediately.
  const conn = await env.DB.prepare(
    `SELECT encrypted_api_key, datadog_site FROM datadog_connections
     WHERE org_id = ? AND status != 'paused' LIMIT 1`,
  ).bind(orgId).first<{ encrypted_api_key: string; datadog_site: string }>();

  if (!conn) {
    return { org_id: orgId, series_pushed: 0, skipped: true };
  }

  let apiKey: string;
  try {
    apiKey = await decryptKey(conn.encrypted_api_key, orgId, env.TOKEN_ENCRYPTION_SECRET);
  } catch {
    return { org_id: orgId, series_pushed: 0, skipped: false, error: 'API key decryption failed' };
  }

  // Guard written after successful decryption — if decrypt failed we want the
  // next cron tick to retry (e.g. after the user reconnects with a valid key).
  await env.KV.put(guardKey, '1', { expirationTtl: 23 * 3600 });

  // Last 24 h of cross_platform_usage, aggregated per developer/provider/model
  const since = new Date(Date.now() - 24 * 3600 * 1000)
    .toISOString().replace('T', ' ').replace(/\.\d+Z$/, '');

  const rows = await env.DB.prepare(
    `SELECT provider,
            model,
            developer_id,
            COALESCE(SUM(cost_usd), 0)                    AS cost_usd,
            COALESCE(SUM(input_tokens), 0)                 AS input_tokens,
            COALESCE(SUM(output_tokens), 0)                AS output_tokens,
            MAX(period_start)                              AS period_start
     FROM cross_platform_usage
     WHERE org_id = ? AND created_at >= ?
     GROUP BY provider, model, developer_id`,
  ).bind(orgId, since).all<UsageRow>();

  const data = rows.results ?? [];
  if (data.length === 0) {
    // No data — still mark synced so we don't hammer on empty orgs
    return { org_id: orgId, series_pushed: 0, skipped: false };
  }

  // Build Datadog series
  const series: DatadogSeries[] = [];

  for (const row of data) {
    const ts = Math.floor(new Date(row.period_start.replace(' ', 'T') + 'Z').getTime() / 1000);
    const tags = [
      `provider:${row.provider}`,
      `org_id:${orgId}`,
      `developer_id:${row.developer_id}`,
      ...(row.model ? [`model:${row.model}`] : []),
    ];

    series.push({
      metric: 'cohrint.ai.cost_usd',
      type: 1,
      points: [{ timestamp: ts, value: Number(row.cost_usd) }],
      tags,
    });

    const totalTokens = Number(row.input_tokens) + Number(row.output_tokens);
    if (totalTokens > 0) {
      series.push({
        metric: 'cohrint.ai.tokens',
        type: 1,
        points: [{ timestamp: ts, value: totalTokens }],
        tags,
      });
    }
  }

  // Datadog recommends ≤ 1000 series per request; batch if needed
  const BATCH_SIZE = 1000;
  let totalPushed = 0;

  for (let i = 0; i < series.length; i += BATCH_SIZE) {
    const batch = series.slice(i, i + BATCH_SIZE);
    // Wrap push with circuit breaker — null means breaker is open (Datadog unreachable)
    const result = await withBreaker('datadog', env.KV, () => pushToDatadog({ series: batch }, apiKey, conn.datadog_site));

    if (result === null) {
      const errMsg = 'Datadog API unavailable (circuit breaker open)';
      await env.DB.prepare(
        `UPDATE datadog_connections
         SET status = 'error', last_error = ?, updated_at = datetime('now')
         WHERE org_id = ?`,
      ).bind(errMsg.slice(0, 500), orgId).run();
      return { org_id: orgId, series_pushed: totalPushed, skipped: false, error: errMsg };
    }

    if (!result.ok) {
      const errMsg = result.error ?? 'Unknown push error';
      await env.DB.prepare(
        `UPDATE datadog_connections
         SET status = 'error', last_error = ?, updated_at = datetime('now')
         WHERE org_id = ?`,
      ).bind(errMsg.slice(0, 500), orgId).run();
      return { org_id: orgId, series_pushed: totalPushed, skipped: false, error: errMsg };
    }

    totalPushed += batch.length;
  }

  await env.DB.prepare(
    `UPDATE datadog_connections
     SET status = 'active', last_synced_at = datetime('now'), last_error = NULL, updated_at = datetime('now')
     WHERE org_id = ?`,
  ).bind(orgId).run();

  return { org_id: orgId, series_pushed: totalPushed, skipped: false };
}

/**
 * Sync all active Datadog connections. Called from the scheduled cron handler.
 * Pass orgId to scope to a single org (e.g. on-demand trigger).
 */
export async function syncDatadogMetrics(
  env: Bindings,
  orgId?: string,
): Promise<DatadogSyncResult[]> {
  const stmt = orgId
    ? env.DB.prepare(
        `SELECT org_id FROM datadog_connections WHERE org_id = ? AND status != 'paused'`,
      ).bind(orgId)
    : env.DB.prepare(
        `SELECT org_id FROM datadog_connections WHERE status != 'paused'`,
      );

  const rows = await stmt.all<{ org_id: string }>();
  const results: DatadogSyncResult[] = [];

  for (const row of rows.results ?? []) {
    results.push(await syncDatadogMetricsForOrg(env, row.org_id));
  }

  return results;
}

// ── POST /connect ─────────────────────────────────────────────────────────────

datadog.post('/connect', async (c) => {
  const orgId = c.get('orgId');
  const role  = c.get('role');

  if (!hasRole(role, 'admin')) {
    return c.json({ error: 'Forbidden — admin or owner required' }, 403);
  }

  let body: unknown;
  try { body = await c.req.json(); } catch { return c.json({ error: 'Invalid JSON body' }, 400); }

  if (
    typeof body !== 'object' || body === null ||
    typeof (body as Record<string, unknown>).api_key !== 'string'
  ) {
    return c.json({ error: 'Required: api_key (string). Optional: site (string)' }, 400);
  }

  const { api_key, site } = body as { api_key: string; site?: unknown };

  const datadogSite = typeof site === 'string' ? site : 'datadoghq.com';

  if (!ALLOWED_SITES.has(datadogSite)) {
    return c.json({
      error: `Unsupported Datadog site. Allowed: ${[...ALLOWED_SITES].join(', ')}`,
    }, 400);
  }

  // Validate API key against Datadog before storing
  const validation = await validateDatadogKey(api_key, datadogSite);
  if (!validation.valid) {
    return c.json({ error: validation.error ?? 'Invalid Datadog API key' }, 400);
  }

  const encrypted = await encryptKey(api_key, orgId, c.env.TOKEN_ENCRYPTION_SECRET);

  await c.env.DB.prepare(
    `INSERT INTO datadog_connections (org_id, encrypted_api_key, datadog_site, status, updated_at)
     VALUES (?, ?, ?, 'active', datetime('now'))
     ON CONFLICT(org_id) DO UPDATE SET
       encrypted_api_key = excluded.encrypted_api_key,
       datadog_site      = excluded.datadog_site,
       status            = 'active',
       last_error        = NULL,
       updated_at        = datetime('now')`,
  ).bind(orgId, encrypted, datadogSite).run();

  return c.json({
    connected:    true,
    datadog_site: datadogSite,
    message:      'Connection saved. Metrics sync daily via the scheduled cron.',
  }, 201);
});

// ── DELETE /connect ───────────────────────────────────────────────────────────

datadog.delete('/connect', async (c) => {
  const orgId = c.get('orgId');
  const role  = c.get('role');

  if (!hasRole(role, 'admin')) {
    return c.json({ error: 'Forbidden — admin or owner required' }, 403);
  }

  const result = await c.env.DB.prepare(
    `DELETE FROM datadog_connections WHERE org_id = ?`,
  ).bind(orgId).run();

  if (result.meta.changes === 0) {
    return c.json({ error: 'No Datadog connection found for this org' }, 404);
  }

  return c.json({ disconnected: true });
});

// ── GET /status ───────────────────────────────────────────────────────────────

datadog.get('/status', async (c) => {
  const orgId   = c.get('orgId');
  const role    = c.get('role');
  const isAdmin = hasRole(role, 'admin');

  if (!isAdmin) {
    return c.json({ error: 'Forbidden — admin or owner required' }, 403);
  }

  const row = await c.env.DB.prepare(
    `SELECT datadog_site, status, last_synced_at, last_error, created_at
     FROM datadog_connections WHERE org_id = ? LIMIT 1`,
  ).bind(orgId).first<{
    datadog_site:    string;
    status:          string;
    last_synced_at:  string | null;
    last_error:      string | null;
    created_at:      string;
  }>();

  if (!row) {
    return c.json({ connected: false });
  }

  return c.json({
    connected:      true,
    datadog_site:   row.datadog_site,
    status:         row.status,
    last_synced_at: row.last_synced_at,
    last_error:     row.last_error,
    created_at:     row.created_at,
  });
});

export { datadog };
