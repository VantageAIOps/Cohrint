/**
 * Cohrint — Anonymized Benchmark API
 *
 * Powers cross-company intelligence benchmarks.
 * Opt-in only. No org identifiers in public endpoints.
 * k-anonymity floor: cohorts with sample_size < 5 return 404.
 *
 * Endpoints:
 *   POST /v1/benchmark/contribute    — auth required; computes + upserts quarterly snapshot
 *   GET  /v1/benchmark/percentiles   — public; ?model=&metric= returns p25/p50/p75/p90
 *   GET  /v1/benchmark/summary       — public; available cohort+metric combos with sample sizes
 *
 * Cron: syncBenchmarkContributions(env) — called from scheduled handler (Sundays UTC only)
 */

import { Hono } from 'hono';
import type { Bindings, Variables } from '../types';
import { authMiddleware } from '../middleware/auth';

const benchmark = new Hono<{ Bindings: Bindings; Variables: Variables }>();

// ── Helpers ───────────────────────────────────────────────────────────────────

/** Returns the current quarter string, e.g. '2026-Q2'. */
function currentQuarter(): string {
  const now = new Date();
  const q = Math.ceil((now.getUTCMonth() + 1) / 3);
  return `${now.getUTCFullYear()}-Q${q}`;
}

/** Maps an org's member count to a size band. */
function sizeBand(memberCount: number): '1-10' | '11-50' | '51-200' | '201-1000' | '1000+' {
  if (memberCount <= 10)   return '1-10';
  if (memberCount <= 50)   return '11-50';
  if (memberCount <= 200)  return '51-200';
  if (memberCount <= 1000) return '201-1000';
  return '1000+';
}

/**
 * Computes p25/p50/p75/p90 from a sorted array of numbers.
 * Returns zeroes for empty arrays.
 */
function percentiles(sorted: number[]): { p25: number; p50: number; p75: number; p90: number } {
  if (sorted.length === 0) return { p25: 0, p50: 0, p75: 0, p90: 0 };
  const p = (pct: number): number => {
    const idx = (pct / 100) * (sorted.length - 1);
    const lo  = Math.floor(idx);
    const hi  = Math.ceil(idx);
    if (lo === hi) return sorted[lo];
    return sorted[lo] + (sorted[hi] - sorted[lo]) * (idx - lo);
  };
  return { p25: p(25), p50: p(50), p75: p(75), p90: p(90) };
}

/** Ensures a cohort row exists for the given band+industry, returns its id. */
async function ensureCohort(
  db: D1Database,
  band: string,
  industry: string,
): Promise<number> {
  // Upsert via INSERT OR IGNORE, then SELECT
  await db.prepare(`
    INSERT OR IGNORE INTO benchmark_cohorts (size_band, industry)
    VALUES (?, ?)
  `).bind(band, industry).run();

  const row = await db.prepare(`
    SELECT id FROM benchmark_cohorts WHERE size_band = ? AND industry = ?
  `).bind(band, industry).first<{ id: number }>();

  if (!row) throw new Error('Failed to resolve benchmark cohort');
  return row.id;
}

/**
 * Computes an org's contribution metrics for the current quarter and upserts
 * benchmark_snapshots. Tracks the org in benchmark_contributions for
 * deduplication. Safe to call repeatedly — idempotent per org/quarter.
 */
export async function computeAndUpsertContribution(
  db: D1Database,
  orgId: string,
): Promise<{ contributed: boolean; reason?: string }> {
  // 1. Verify opt-in
  const org = await db.prepare(`
    SELECT benchmark_opt_in, plan FROM orgs WHERE id = ?
  `).bind(orgId).first<{ benchmark_opt_in: number; plan: string }>();

  if (!org || org.benchmark_opt_in !== 1) {
    return { contributed: false, reason: 'not_opted_in' };
  }

  // 2. Derive cohort dimensions
  // Member count for size band
  const memberRow = await db.prepare(`
    SELECT COUNT(*) AS cnt FROM org_members WHERE org_id = ?
  `).bind(orgId).first<{ cnt: number }>();
  const memberCount = memberRow?.cnt ?? 1;
  const band = sizeBand(memberCount);

  // Industry defaults to 'tech' unless set on org (column may not exist on older rows)
  let industry: string = 'tech';
  try {
    const indRow = await db.prepare(
      'SELECT industry FROM orgs WHERE id = ?'
    ).bind(orgId).first<{ industry: string | null }>();
    if (indRow?.industry && ['tech','finance','healthcare','other'].includes(indRow.industry)) {
      industry = indRow.industry;
    }
  } catch { /* column doesn't exist yet — default to tech */ }

  const cohortId = await ensureCohort(db, band, industry);
  const quarter  = currentQuarter();

  // 3. Compute per-model cost/token from cross_platform_usage (current quarter)
  // Quarter → date range: Q1=Jan–Mar, Q2=Apr–Jun, Q3=Jul–Sep, Q4=Oct–Dec
  const [year, qPart] = quarter.split('-');
  const qNum = parseInt(qPart.replace('Q', ''), 10);
  const qStartMonth = String((qNum - 1) * 3 + 1).padStart(2, '0');
  const qStart = `${year}-${qStartMonth}-01 00:00:00`;
  // Exclusive upper bound — next quarter's first day — so historic quarters
  // don't accumulate future data if the cron re-runs after quarter rollover.
  const qEndYear  = qNum === 4 ? String(parseInt(year, 10) + 1) : year;
  const qEndMonth = String(qNum === 4 ? 1 : qNum * 3 + 1).padStart(2, '0');
  const qEnd = `${qEndYear}-${qEndMonth}-01 00:00:00`;

  const modelRows = await db.prepare(`
    SELECT
      model,
      SUM(cost_usd) AS total_cost,
      SUM(input_tokens + output_tokens) AS total_tokens,
      SUM(cached_tokens) AS cached_tokens_sum,
      SUM(input_tokens + output_tokens + COALESCE(cached_tokens, 0)) AS gross_tokens
    FROM cross_platform_usage
    WHERE org_id = ?
      AND created_at >= ? AND created_at < ?
      AND model IS NOT NULL
      AND input_tokens > 0
    GROUP BY model
  `).bind(orgId, qStart, qEnd).all<{
    model: string;
    total_cost: number;
    total_tokens: number;
    cached_tokens_sum: number;
    gross_tokens: number;
  }>();

  // Per-developer monthly cost (for cost_per_dev_month metric)
  const devRow = await db.prepare(`
    SELECT
      COUNT(DISTINCT developer_email) AS dev_count,
      SUM(cost_usd)                  AS total_cost
    FROM cross_platform_usage
    WHERE org_id = ? AND created_at >= ? AND created_at < ? AND developer_email IS NOT NULL
  `).bind(orgId, qStart, qEnd).first<{ dev_count: number; total_cost: number }>();

  // Cache hit rate (cached_tokens / gross_tokens across all usage)
  const cacheRow = await db.prepare(`
    SELECT
      SUM(COALESCE(cached_tokens, 0)) AS cached,
      SUM(input_tokens + output_tokens + COALESCE(cached_tokens, 0)) AS gross
    FROM cross_platform_usage
    WHERE org_id = ? AND created_at >= ? AND created_at < ?
  `).bind(orgId, qStart, qEnd).first<{ cached: number; gross: number }>();

  // 4. Build a list of {snapshotId, orgValue} pairs to record contribution
  type MetricValue = { metricName: string; model: string | null; value: number };
  const metricValues: MetricValue[] = [];

  // cost_per_token per model
  for (const r of modelRows.results ?? []) {
    if (r.total_tokens > 0 && r.total_cost > 0) {
      metricValues.push({
        metricName: 'cost_per_token',
        model: r.model,
        value: r.total_cost / r.total_tokens,
      });
    }
  }

  // cost_per_dev_month
  const devCount = devRow?.dev_count ?? 0;
  const totalCost = devRow?.total_cost ?? 0;
  if (devCount > 0 && totalCost > 0) {
    // Quarterly total → monthly average
    metricValues.push({
      metricName: 'cost_per_dev_month',
      model: null,
      value: (totalCost / devCount) / 3,
    });
  }

  // cache_hit_rate (0–1)
  const grossTokens = cacheRow?.gross ?? 0;
  const cachedTokens = cacheRow?.cached ?? 0;
  if (grossTokens > 0) {
    metricValues.push({
      metricName: 'cache_hit_rate',
      model: null,
      value: cachedTokens / grossTokens,
    });
  }

  if (metricValues.length === 0) {
    return { contributed: false, reason: 'no_usage_data' };
  }

  // 5. For each metric, load all existing org contributions to this cohort/quarter/metric
  //    so we can recompute percentiles including this org's value.
  for (const mv of metricValues) {
    // Upsert the snapshot row (ensures it exists, sample_size will be updated below)
    await db.prepare(`
      INSERT INTO benchmark_snapshots (cohort_id, quarter, metric_name, model, sample_size)
      VALUES (?, ?, ?, ?, 0)
      ON CONFLICT (cohort_id, quarter, metric_name, COALESCE(model, '')) DO NOTHING
    `).bind(cohortId, quarter, mv.metricName, mv.model).run();

    const snap = await db.prepare(`
      SELECT id FROM benchmark_snapshots
      WHERE cohort_id = ? AND quarter = ? AND metric_name = ?
        AND COALESCE(model, '') = COALESCE(?, '')
    `).bind(cohortId, quarter, mv.metricName, mv.model).first<{ id: number }>();

    if (!snap) continue;

    const snapId = snap.id;

    // Upsert contribution record (idempotent)
    await db.prepare(`
      INSERT OR IGNORE INTO benchmark_contributions (org_id, snapshot_id, contributed_at)
      VALUES (?, ?, datetime('now'))
    `).bind(orgId, snapId).run();

    // Re-gather all contributing orgs' metric values in a single GROUP BY query
    // to avoid an N+1 round-trip per contributor.
    const orgValues: number[] = [];

    if (mv.metricName === 'cost_per_token' && mv.model) {
      const rows = await db.prepare(`
        SELECT cpu.org_id,
               SUM(cpu.cost_usd) AS c,
               SUM(cpu.input_tokens + cpu.output_tokens) AS t
        FROM cross_platform_usage cpu
        INNER JOIN benchmark_contributions bc ON bc.org_id = cpu.org_id
        WHERE bc.snapshot_id = ?
          AND cpu.model = ? AND cpu.created_at >= ? AND cpu.created_at < ?
          AND cpu.input_tokens > 0
        GROUP BY cpu.org_id
      `).bind(snapId, mv.model, qStart, qEnd).all<{ org_id: string; c: number; t: number }>();
      for (const r of (rows.results ?? [])) {
        if (r.t > 0 && r.c > 0) { const v = r.c / r.t; if (isFinite(v)) orgValues.push(v); }
      }
    } else if (mv.metricName === 'cost_per_dev_month') {
      const rows = await db.prepare(`
        SELECT cpu.org_id,
               COUNT(DISTINCT cpu.developer_email) AS d,
               SUM(cpu.cost_usd) AS c
        FROM cross_platform_usage cpu
        INNER JOIN benchmark_contributions bc ON bc.org_id = cpu.org_id
        WHERE bc.snapshot_id = ?
          AND cpu.created_at >= ? AND cpu.created_at < ?
          AND cpu.developer_email IS NOT NULL
        GROUP BY cpu.org_id
      `).bind(snapId, qStart, qEnd).all<{ org_id: string; d: number; c: number }>();
      for (const r of (rows.results ?? [])) {
        if (r.d > 0 && r.c > 0) { const v = (r.c / r.d) / 3; if (isFinite(v)) orgValues.push(v); }
      }
    } else if (mv.metricName === 'cache_hit_rate') {
      const rows = await db.prepare(`
        SELECT cpu.org_id,
               SUM(COALESCE(cpu.cached_tokens, 0)) AS ca,
               SUM(cpu.input_tokens + cpu.output_tokens + COALESCE(cpu.cached_tokens, 0)) AS g
        FROM cross_platform_usage cpu
        INNER JOIN benchmark_contributions bc ON bc.org_id = cpu.org_id
        WHERE bc.snapshot_id = ?
          AND cpu.created_at >= ? AND cpu.created_at < ?
        GROUP BY cpu.org_id
      `).bind(snapId, qStart, qEnd).all<{ org_id: string; ca: number; g: number }>();
      for (const r of (rows.results ?? [])) {
        if (r.g > 0) { const v = r.ca / r.g; if (isFinite(v)) orgValues.push(v); }
      }
    }

    orgValues.sort((a, b) => a - b);
    const { p25, p50, p75, p90 } = percentiles(orgValues);

    await db.prepare(`
      UPDATE benchmark_snapshots
      SET p25 = ?, p50 = ?, p75 = ?, p90 = ?, sample_size = ?, updated_at = datetime('now')
      WHERE id = ?
    `).bind(p25, p50, p75, p90, orgValues.length, snapId).run();
  }

  return { contributed: true };
}

/**
 * Called from the scheduled cron (Sundays UTC only).
 * Iterates all opted-in orgs and computes their benchmark contributions.
 */
export async function syncBenchmarkContributions(env: Bindings): Promise<void> {
  const day = new Date().getUTCDay(); // 0 = Sunday
  if (day !== 0) return;

  const { results: orgs } = await env.DB.prepare(`
    SELECT id FROM orgs WHERE benchmark_opt_in = 1
  `).all<{ id: string }>();

  for (const org of orgs ?? []) {
    try {
      const result = await computeAndUpsertContribution(env.DB, org.id);
      if (result.contributed) {
        console.log(`[benchmark-cron] org=${org.id} contributed`);
      } else {
        console.log(`[benchmark-cron] org=${org.id} skipped reason=${result.reason}`);
      }
    } catch (err) {
      console.error(`[benchmark-cron] org=${org.id} error:`, err);
    }
  }
}

// ── Routes ────────────────────────────────────────────────────────────────────

/**
 * POST /v1/benchmark/contribute
 * Auth required. Computes and upserts benchmark snapshot for the calling org.
 * No-op if org has benchmark_opt_in = 0.
 */
benchmark.post('/contribute', authMiddleware, async (c) => {
  const orgId = c.get('orgId');
  const role  = c.get('role');
  // Restrict to owner/admin — any authenticated member triggering this causes
  // an O(N contributors) re-aggregation loop; a viewer should not be able to
  // initiate that workload.
  if (role !== 'owner' && role !== 'admin') {
    return c.json({ error: 'Forbidden — admin or owner required' }, 403);
  }
  const result = await computeAndUpsertContribution(c.env.DB, orgId);
  if (!result.contributed) {
    return c.json({ ok: false, reason: result.reason ?? 'skipped' }, 200);
  }
  return c.json({ ok: true }, 200);
});

const VALID_METRICS = new Set(['cost_per_token', 'cost_per_dev_month', 'cache_hit_rate']);

/**
 * GET /v1/benchmark/percentiles?metric=cost_per_token&model=gpt-4o
 * Public — no auth. Returns p25/p50/p75/p90 aggregated across all cohorts.
 * Returns 404 if sample_size < 5 (k-anonymity floor).
 */
benchmark.get('/percentiles', async (c) => {
  const metric = c.req.query('metric');
  const model  = c.req.query('model') ?? null;

  if (!metric || !VALID_METRICS.has(metric)) {
    return c.json({
      error: `metric must be one of: ${[...VALID_METRICS].join(', ')}`,
    }, 400);
  }

  // Aggregate across all cohorts for the latest quarter that has sufficient data
  // Returns the most recent quarter with sample_size >= 5.
  const row = await c.env.DB.prepare(`
    SELECT
      bs.quarter,
      SUM(bs.sample_size)    AS total_sample,
      -- Weighted median approximation: use sample_size-weighted average of percentiles
      -- (true percentile merging requires individual values; this is a safe approximation)
      SUM(bs.p25 * bs.sample_size) / SUM(bs.sample_size) AS p25,
      SUM(bs.p50 * bs.sample_size) / SUM(bs.sample_size) AS p50,
      SUM(bs.p75 * bs.sample_size) / SUM(bs.sample_size) AS p75,
      SUM(bs.p90 * bs.sample_size) / SUM(bs.sample_size) AS p90
    FROM benchmark_snapshots bs
    WHERE bs.metric_name = ?
      AND COALESCE(bs.model, '') = COALESCE(?, '')
      AND bs.sample_size >= 5
    GROUP BY bs.quarter
    HAVING MIN(bs.sample_size) >= 5
    ORDER BY bs.quarter DESC
    LIMIT 1
  `).bind(metric, model).first<{
    quarter: string;
    total_sample: number;
    p25: number;
    p50: number;
    p75: number;
    p90: number;
  }>();

  if (!row || row.total_sample < 5) {
    return c.json({ error: 'Insufficient data' }, 404);
  }

  return c.json({
    metric,
    model:       model ?? null,
    quarter:     row.quarter,
    sample_size: row.total_sample,
    p25:  Math.round(row.p25  * 1e8) / 1e8,
    p50:  Math.round(row.p50  * 1e8) / 1e8,
    p75:  Math.round(row.p75  * 1e8) / 1e8,
    p90:  Math.round(row.p90  * 1e8) / 1e8,
  });
});

/**
 * GET /v1/benchmark/summary
 * Public — no auth. Returns available metric+model combos with sample sizes.
 * Only includes entries with sample_size >= 5.
 */
benchmark.get('/summary', async (c) => {
  const rows = await c.env.DB.prepare(`
    SELECT
      bs.metric_name,
      bs.model,
      bs.quarter,
      SUM(bs.sample_size) AS sample_size,
      COUNT(DISTINCT bs.cohort_id) AS cohort_count
    FROM benchmark_snapshots bs
    WHERE bs.sample_size >= 5
    GROUP BY bs.metric_name, bs.model, bs.quarter
    ORDER BY bs.quarter DESC, bs.metric_name, bs.model
  `).all<{
    metric_name: string;
    model: string | null;
    quarter: string;
    sample_size: number;
    cohort_count: number;
  }>();

  return c.json({
    available: (rows.results ?? []).map(r => ({
      metric:       r.metric_name,
      model:        r.model ?? null,
      quarter:      r.quarter,
      sample_size:  r.sample_size,
      cohort_count: r.cohort_count,
    })),
  });
});

export { benchmark };
