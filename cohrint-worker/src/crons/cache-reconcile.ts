/**
 * T013 — Cache reconciliation cron.
 *
 * Runs daily at 02:00 UTC. Scans semantic_cache_entries created in the last
 * 24 hours that have a response_r2_key, verifies the R2 object exists, and
 * emits WAE `cache.reconciliation_drift` for each missing object.
 *
 * Lock key: "cache-reconcile" (KV, 2h TTL) — prevents duplicate runs.
 * Skips silently when CACHE_BUCKET binding is absent (local dev / no R2).
 */

import { Bindings } from '../types';
import { createLogger } from '../lib/logger';
import { emitMetric } from '../lib/metrics';

interface CacheEntryRow {
  id:              string;
  org_id:          string;
  response_r2_key: string;
  created_at:      string;
}

export async function runCacheReconcile(env: Bindings): Promise<void> {
  const log = createLogger('cache-reconcile-cron');

  if (!env.CACHE_BUCKET) {
    log.info('cache-reconcile: CACHE_BUCKET absent — skipping');
    return;
  }

  // semantic_cache_entries.created_at is TEXT "YYYY-MM-DD HH:MM:SS"
  const since = new Date(Date.now() - 24 * 60 * 60 * 1000)
    .toISOString()
    .replace('T', ' ')
    .slice(0, 19);

  const { results } = await env.DB
    .prepare(`
      SELECT id, org_id, response_r2_key, created_at
      FROM semantic_cache_entries
      WHERE response_r2_key IS NOT NULL
        AND created_at >= ?
      LIMIT 5000
    `)
    .bind(since)
    .all<CacheEntryRow>();

  if (results.length === 0) {
    log.info('cache-reconcile: no entries to check');
    return;
  }

  let missing = 0;
  let present = 0;
  let errored = 0;

  for (const entry of results) {
    try {
      const obj = await env.CACHE_BUCKET.head(entry.response_r2_key);
      if (obj === null) {
        missing++;
        emitMetric(env.METRICS, {
          event:  'cache.reconciliation_drift',
          orgId:  entry.org_id,
          values: { count: 1 },
          labels: { entry_id: entry.id },
        });
        log.warn('cache-reconcile: R2 object missing', {
          entry_id:        entry.id,
          org_id:          entry.org_id,
          response_r2_key: entry.response_r2_key,
        });
      } else {
        present++;
      }
    } catch (err) {
      errored++;
      log.error('cache-reconcile: R2 head failed', {
        err:             err instanceof Error ? err : new Error(String(err)),
        entry_id:        entry.id,
        response_r2_key: entry.response_r2_key,
      });
    }
  }

  log.info('cache-reconcile: complete', {
    checked: results.length,
    present,
    missing,
    errored,
  });
}
