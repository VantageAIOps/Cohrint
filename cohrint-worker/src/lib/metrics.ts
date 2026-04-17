// Typed WAE emission helper.
// METRICS binding declared in wrangler.toml as [[analytics_engine_datasets]].
// Emits: events.accepted, events.duplicate, events.free_tier_rejected,
//        events.d1_error, cache.hit, cache.miss, ratelimit.rejected

export type MetricEvent =
  | 'events.accepted'
  | 'events.duplicate'
  | 'events.free_tier_rejected'
  | 'events.d1_error'
  | 'cache.hit'
  | 'cache.miss'
  | 'ratelimit.rejected'
  | 'circuit.short_circuited';

interface MetricPayload {
  event: MetricEvent;
  orgId?: string;
  labels?: Record<string, string>;
  values?: Record<string, number>;
}

export function emitMetric(dataset: AnalyticsEngineDataset | undefined, payload: MetricPayload): void {
  if (!dataset) return; // graceful noop when binding absent (local dev)
  try {
    dataset.writeDataPoint({
      indexes: [payload.orgId ?? ''],
      blobs: [payload.event, ...(payload.labels ? Object.entries(payload.labels).map(([k,v]) => `${k}=${v}`) : [])],
      doubles: payload.values ? Object.values(payload.values) : [],
    });
  } catch {
    // WAE writes are fire-and-forget; never throw
  }
}
