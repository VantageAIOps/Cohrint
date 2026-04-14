/**
 * VantageAI — GitHub Copilot Metrics API Adapter
 *
 * Polls the GitHub Copilot Metrics API (GA Feb 2026) for per-developer usage
 * and upserts normalised records into cross_platform_usage.
 *
 * Endpoints (all require auth):
 *   POST   /v1/copilot/connect     — store GitHub org + PAT (encrypted in KV)
 *   DELETE /v1/copilot/connect     — remove connection
 *   GET    /v1/copilot/status      — connection status + last sync time
 *
 * Internal export:
 *   syncCopilotMetrics(env, orgId?) — called from cron; idempotent upsert
 *
 * Token storage:
 *   Tokens are AES-256-GCM encrypted and stored in KV under
 *   `copilot:token:<org_id>:<github_org>`. They are NEVER written to D1.
 *
 * Cost model:
 *   Copilot Business = $19/user/month ÷ 30 days = ~$0.6333/active-user/day.
 */

import { Hono } from 'hono';
import type { Bindings, Variables } from '../types';
import { authMiddleware } from '../middleware/auth';

const copilot = new Hono<{ Bindings: Bindings; Variables: Variables }>();

copilot.use('*', authMiddleware);

// ── Constants ────────────────────────────────────────────────────────────────

const SEAT_USD_PER_DAY = 19.0 / 30; // ~0.6333
const GITHUB_API_BASE  = 'https://api.github.com';

function kvTokenKey(orgId: string, githubOrg: string): string {
  return `copilot:token:${orgId}:${githubOrg}`;
}

function kvSyncGuardKey(orgId: string, githubOrg: string, day: string): string {
  return `copilot:last_sync:${orgId}:${githubOrg}:${day}`;
}

// ── AES-GCM helpers (Web Crypto — available in Cloudflare Workers) ───────────
//
// Key derivation: HKDF-SHA-256 from TOKEN_ENCRYPTION_SECRET (Worker secret) +
// orgId as salt. Falls back to a fixed salt when the secret is not set (dev/test
// only — production must set TOKEN_ENCRYPTION_SECRET via wrangler secret put).

async function deriveKey(orgId: string, secret?: string): Promise<CryptoKey> {
  const enc      = new TextEncoder();
  const keyMaterial = await crypto.subtle.importKey(
    'raw',
    enc.encode(secret ?? 'dev-insecure-fallback-set-TOKEN_ENCRYPTION_SECRET'),
    { name: 'HKDF' },
    false,
    ['deriveKey'],
  );
  return crypto.subtle.deriveKey(
    { name: 'HKDF', hash: 'SHA-256', salt: enc.encode(orgId), info: enc.encode('copilot-pat-v1') },
    keyMaterial,
    { name: 'AES-GCM', length: 256 },
    false,
    ['encrypt', 'decrypt'],
  );
}

async function encryptToken(plaintext: string, orgId: string, secret?: string): Promise<string> {
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

async function decryptToken(ciphertext: string, orgId: string, secret?: string): Promise<string> {
  const key      = await deriveKey(orgId, secret);
  const combined = Uint8Array.from(atob(ciphertext), c => c.charCodeAt(0));
  const buf = await crypto.subtle.decrypt(
    { name: 'AES-GCM', iv: combined.slice(0, 12) },
    key,
    combined.slice(12),
  );
  return new TextDecoder().decode(buf);
}

// ── GitHub API types ─────────────────────────────────────────────────────────

interface CopilotEditorModel {
  name: string;
  total_engaged_users: number;
  total_code_suggestions: number;
  total_code_acceptances: number;
  total_code_lines_suggested: number;
  total_code_lines_accepted: number;
}

interface CopilotEditor {
  name: string;
  total_engaged_users: number;
  models?: CopilotEditorModel[];
}

interface CopilotDayMetric {
  date: string;
  total_active_users: number;
  total_engaged_users: number;
  copilot_ide_code_completions?: {
    total_engaged_users: number;
    editors?: CopilotEditor[];
  };
}

interface CopilotSeatAssignee {
  login: string;
  id: number;
  email?: string;
}

interface CopilotSeatDetail {
  assignee: CopilotSeatAssignee;
  last_activity_at: string | null;
}

interface CopilotSeatsResponse {
  total_seats: number;
  seats: CopilotSeatDetail[];
}

// ── GitHub fetch helpers ─────────────────────────────────────────────────────

async function fetchCopilotMetrics(
  githubOrg: string,
  token: string,
  since?: string,
): Promise<CopilotDayMetric[]> {
  const qs  = since ? `?since=${since}` : '';
  const url = `${GITHUB_API_BASE}/orgs/${githubOrg}/copilot/metrics${qs}`;
  const resp = await fetch(url, {
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: 'application/vnd.github+json',
      'X-GitHub-Api-Version': '2022-11-28',
      'User-Agent': 'VantageAI/1.0',
    },
  });
  if (!resp.ok) {
    const body = await resp.text();
    throw new Error(`GitHub Copilot API ${resp.status}: ${body.slice(0, 300)}`);
  }
  return resp.json() as Promise<CopilotDayMetric[]>;
}

async function fetchCopilotSeats(
  githubOrg: string,
  token: string,
): Promise<CopilotSeatDetail[]> {
  const seats: CopilotSeatDetail[] = [];
  let page = 1;
  while (true) {
    const url  = `${GITHUB_API_BASE}/orgs/${githubOrg}/copilot/billing/seats?per_page=100&page=${page}`;
    const resp = await fetch(url, {
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
        'User-Agent': 'VantageAI/1.0',
      },
    });
    if (!resp.ok) break; // best-effort; metrics still work without seat details
    const body = await resp.json() as CopilotSeatsResponse;
    if (!body.seats?.length) break;
    seats.push(...body.seats);
    if (body.seats.length < 100) break;
    page++;
  }
  return seats;
}

// ── Crypto helper ────────────────────────────────────────────────────────────

async function stableDevId(orgId: string, githubOrg: string, login: string): Promise<string> {
  const buf = await crypto.subtle.digest(
    'SHA-256',
    new TextEncoder().encode(`${orgId}:${githubOrg}:${login}`),
  );
  return Array.from(new Uint8Array(buf))
    .map(b => b.toString(16).padStart(2, '0'))
    .join('')
    .slice(0, 32);
}

// ── Core sync function ───────────────────────────────────────────────────────

export interface SyncResult {
  github_org:    string;
  days_synced:   number;
  rows_upserted: number;
  skipped:       boolean;
  error?:        string;
}

/**
 * Syncs one (orgId, githubOrg) pair. Safe to call multiple times — idempotent
 * via INSERT OR REPLACE keyed on (org_id, developer_id, period_start, provider).
 * KV guard prevents re-running on the same calendar day (23 h TTL).
 */
export async function syncCopilotMetricsForOrg(
  env: Bindings,
  orgId: string,
  githubOrg: string,
): Promise<SyncResult> {
  const todayUtc  = new Date().toISOString().slice(0, 10);
  const guardKey  = kvSyncGuardKey(orgId, githubOrg, todayUtc);

  if (await env.KV.get(guardKey)) {
    return { github_org: githubOrg, days_synced: 0, rows_upserted: 0, skipped: true };
  }

  // Fetch + decrypt token BEFORE writing the guard. If decryption fails (e.g.
  // corrupt KV value), we must not lock out the next cron tick — the user may
  // re-connect and the new token should be retried immediately.
  const encryptedToken = await env.KV.get(kvTokenKey(orgId, githubOrg));
  if (!encryptedToken) {
    return { github_org: githubOrg, days_synced: 0, rows_upserted: 0, skipped: false, error: 'No token in KV' };
  }

  let token: string;
  try {
    token = await decryptToken(encryptedToken, orgId, env.TOKEN_ENCRYPTION_SECRET);
  } catch {
    return { github_org: githubOrg, days_synced: 0, rows_upserted: 0, skipped: false, error: 'Token decryption failed' };
  }

  // Guard is written after successful token validation. DELETE+INSERT is idempotent
  // so a missed sync day is recovered on the next calendar day's cron run.
  await env.KV.put(guardKey, '1', { expirationTtl: 23 * 3600 });

  const thirtyDaysAgo = new Date(Date.now() - 30 * 86400000).toISOString().slice(0, 10);

  let metrics: CopilotDayMetric[];
  try {
    metrics = await fetchCopilotMetrics(githubOrg, token, thirtyDaysAgo);
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err);
    await env.DB.prepare(
      `UPDATE copilot_connections
       SET status = 'error', last_error = ?, updated_at = datetime('now')
       WHERE org_id = ? AND github_org = ?`,
    ).bind(msg.slice(0, 500), orgId, githubOrg).run();
    return { github_org: githubOrg, days_synced: 0, rows_upserted: 0, skipped: false, error: msg };
  }

  const seats      = await fetchCopilotSeats(githubOrg, token);
  const loginEmail = new Map<string, string>();
  for (const s of seats) {
    if (s.assignee.email) loginEmail.set(s.assignee.login, s.assignee.email);
  }

  let rowsUpserted = 0;

  for (const day of metrics) {
    const date        = day.date;
    const activeUsers = day.total_active_users ?? 0;
    if (activeUsers === 0) continue;

    // Collect editor model names for that day
    const modelNames: string[] = [];
    let totalSuggestions = 0;
    let totalAcceptances = 0;
    for (const editor of day.copilot_ide_code_completions?.editors ?? []) {
      for (const model of editor.models ?? []) {
        if (!modelNames.includes(model.name)) modelNames.push(model.name);
        totalSuggestions += model.total_code_suggestions;
        totalAcceptances += model.total_code_acceptances;
      }
    }

    const rawData = JSON.stringify({
      date,
      total_active_users: activeUsers,
      total_engaged_users: day.total_engaged_users,
      suggestions: totalSuggestions,
      acceptances: totalAcceptances,
      github_org: githubOrg,
    });

    const periodStart = `${date} 00:00:00`;
    const periodEnd   = `${date} 23:59:59`;
    const modelName   = modelNames[0] ?? null;

    if (seats.length > 0) {
      // Total daily cost = activeUsers * SEAT_USD_PER_DAY. Distribute equally
      // across all seat holders so per-developer attribution sums correctly.
      // We can't know *which* specific developers were active on a given day
      // (the Metrics API only exposes total_active_users, not per-login), so
      // we spread the active cost proportionally across all seats.
      const costPerSeat = (activeUsers * SEAT_USD_PER_DAY) / seats.length;

      for (const seat of seats) {
        const login       = seat.assignee.login;
        const email       = loginEmail.get(login) ?? null;
        const developerId = await stableDevId(orgId, githubOrg, login);

        // DELETE existing row for this (org, dev, day, provider) then INSERT fresh
        await env.DB.prepare(
          `DELETE FROM cross_platform_usage
           WHERE org_id = ? AND developer_id = ? AND period_start = ? AND provider = 'github-copilot'`,
        ).bind(orgId, developerId, periodStart).run();

        await env.DB.prepare(
          `INSERT INTO cross_platform_usage
             (id, org_id, provider, tool_type, source,
              developer_id, developer_email,
              model, cost_usd,
              input_tokens, output_tokens, cached_tokens, total_requests,
              period_start, period_end, raw_data, synced_at, created_at)
           VALUES
             (lower(hex(randomblob(16))), ?, 'github-copilot', 'coding_assistant', 'billing_api',
              ?, ?,
              ?, ?,
              0, 0, 0, 1,
              ?, ?, ?, datetime('now'), datetime('now'))`,
        ).bind(
          orgId, developerId, email,
          modelName, costPerSeat,
          periodStart, periodEnd, rawData,
        ).run();

        rowsUpserted++;
      }
    } else {
      // Org-aggregate fallback row
      const developerId = await stableDevId(orgId, githubOrg, `__org__${githubOrg}`);

      await env.DB.prepare(
        `DELETE FROM cross_platform_usage
         WHERE org_id = ? AND developer_id = ? AND period_start = ? AND provider = 'github-copilot'`,
      ).bind(orgId, developerId, periodStart).run();

      await env.DB.prepare(
        `INSERT INTO cross_platform_usage
           (id, org_id, provider, tool_type, source,
            developer_id, developer_email,
            model, cost_usd,
            input_tokens, output_tokens, cached_tokens, total_requests,
            period_start, period_end, raw_data, synced_at, created_at)
         VALUES
           (lower(hex(randomblob(16))), ?, 'github-copilot', 'coding_assistant', 'billing_api',
            ?, NULL,
            ?, ?,
            0, 0, 0, ?,
            ?, ?, ?, datetime('now'), datetime('now'))`,
      ).bind(
        orgId, developerId,
        modelName, activeUsers * SEAT_USD_PER_DAY,
        activeUsers,
        periodStart, periodEnd, rawData,
      ).run();

      rowsUpserted++;
    }
  }

  // Mark connection active (guard was already written optimistically above)
  await env.DB.prepare(
    `UPDATE copilot_connections
     SET status = 'active', last_synced_at = datetime('now'), last_error = NULL, updated_at = datetime('now')
     WHERE org_id = ? AND github_org = ?`,
  ).bind(orgId, githubOrg).run();

  return { github_org: githubOrg, days_synced: metrics.length, rows_upserted: rowsUpserted, skipped: false };
}

/**
 * Sync all active Copilot connections for an optional orgId filter.
 * Entry point called from the scheduled handler in index.ts.
 */
export async function syncCopilotMetrics(
  env: Bindings,
  orgId?: string,
): Promise<SyncResult[]> {
  const stmt = orgId
    ? env.DB.prepare(
        `SELECT org_id, github_org FROM copilot_connections WHERE org_id = ? AND status != 'paused'`,
      ).bind(orgId)
    : env.DB.prepare(
        `SELECT org_id, github_org FROM copilot_connections WHERE status != 'paused'`,
      );

  const rows = await stmt.all<{ org_id: string; github_org: string }>();
  const results: SyncResult[] = [];
  for (const conn of rows.results ?? []) {
    results.push(await syncCopilotMetricsForOrg(env, conn.org_id, conn.github_org));
  }
  return results;
}

// ── POST /connect ─────────────────────────────────────────────────────────────

copilot.post('/connect', async (c) => {
  const orgId = c.get('orgId');
  const role  = c.get('role');

  if (role !== 'owner' && role !== 'admin') {
    return c.json({ error: 'Forbidden — admin or owner required' }, 403);
  }

  let body: unknown;
  try { body = await c.req.json(); } catch { return c.json({ error: 'Invalid JSON body' }, 400); }

  if (
    typeof body !== 'object' || body === null ||
    typeof (body as Record<string, unknown>).github_org !== 'string' ||
    typeof (body as Record<string, unknown>).token !== 'string'
  ) {
    return c.json({ error: 'Required fields: github_org (string), token (string)' }, 400);
  }

  const { github_org: githubOrg, token } = body as { github_org: string; token: string };

  if (!/^[a-zA-Z0-9-]{1,39}$/.test(githubOrg)) {
    return c.json({ error: 'Invalid github_org — must be 1–39 alphanumeric/hyphen chars' }, 400);
  }
  if (!/^(ghp_|github_pat_)[A-Za-z0-9_]{20,}$/.test(token)) {
    return c.json({ error: 'token must be a GitHub PAT (ghp_* or github_pat_*). ghs_* service tokens are not supported.' }, 400);
  }

  // Validate token + org access against GitHub API
  const testResp = await fetch(
    `${GITHUB_API_BASE}/orgs/${githubOrg}/copilot/billing`,
    {
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
        'User-Agent': 'VantageAI/1.0',
      },
    },
  );

  if (testResp.status === 401) return c.json({ error: 'GitHub token is invalid or expired' }, 400);
  if (testResp.status === 403) return c.json({ error: 'Token lacks manage_billing:copilot scope' }, 400);
  if (testResp.status === 404) return c.json({ error: `Org '${githubOrg}' not found or Copilot not enabled` }, 404);
  if (!testResp.ok) return c.json({ error: `GitHub API returned ${testResp.status} — try again later` }, 502);

  // Encrypt + store in KV; never write plaintext token to D1
  const encrypted = await encryptToken(token, orgId, c.env.TOKEN_ENCRYPTION_SECRET);
  const kvKey     = kvTokenKey(orgId, githubOrg);
  await c.env.KV.put(kvKey, encrypted);

  await c.env.DB.prepare(
    `INSERT INTO copilot_connections (org_id, github_org, kv_key, status, updated_at)
     VALUES (?, ?, ?, 'active', datetime('now'))
     ON CONFLICT(org_id, github_org) DO UPDATE SET
       kv_key = excluded.kv_key, status = 'active',
       last_error = NULL, updated_at = datetime('now')`,
  ).bind(orgId, githubOrg, kvKey).run();

  return c.json({
    connected:  true,
    github_org: githubOrg,
    message:    'Connection saved. Metrics sync daily via the scheduled cron.',
  }, 201);
});

// ── DELETE /connect ───────────────────────────────────────────────────────────

copilot.delete('/connect', async (c) => {
  const orgId = c.get('orgId');
  const role  = c.get('role');

  if (role !== 'owner' && role !== 'admin') {
    return c.json({ error: 'Forbidden — admin or owner required' }, 403);
  }

  // github_org is passed as a query param — DELETE bodies are non-standard
  // and may be stripped by intermediate HTTP stacks.
  const githubOrg = c.req.query('github_org') ?? '';
  if (!githubOrg) {
    return c.json({ error: 'Required query param: github_org' }, 400);
  }

  await c.env.KV.delete(kvTokenKey(orgId, githubOrg));

  const result = await c.env.DB.prepare(
    `DELETE FROM copilot_connections WHERE org_id = ? AND github_org = ?`,
  ).bind(orgId, githubOrg).run();

  if (result.meta.changes === 0) return c.json({ error: 'Connection not found' }, 404);

  return c.json({ disconnected: true, github_org: githubOrg });
});

// ── GET /status ───────────────────────────────────────────────────────────────

copilot.get('/status', async (c) => {
  const orgId = c.get('orgId');
  const role  = c.get('role');
  const isAdmin = role === 'owner' || role === 'admin';

  const rows = await c.env.DB.prepare(
    `SELECT github_org, status, last_synced_at, last_error, created_at
     FROM copilot_connections WHERE org_id = ?
     ORDER BY created_at DESC`,
  ).bind(orgId).all<{
    github_org:     string;
    status:         string;
    last_synced_at: string | null;
    last_error:     string | null;
    created_at:     string;
  }>();

  // Strip last_error for non-admin members — it may contain GitHub API fragments
  const connections = (rows.results ?? []).map(r => ({
    github_org:     r.github_org,
    status:         r.status,
    last_synced_at: r.last_synced_at,
    created_at:     r.created_at,
    ...(isAdmin ? { last_error: r.last_error } : {}),
  }));

  return c.json({ connections });
});

export { copilot };
