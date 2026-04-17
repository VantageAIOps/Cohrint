/**
 * Circuit breaker for third-party API calls.
 *
 * Primary state: in-memory per Worker isolate (fast, per-region).
 * KV state: eventually-consistent hint to speed up cross-region convergence.
 *
 * 3-state: closed → open (after 5 failures in 60s) → half-open (after 30s cooldown)
 *
 * KV propagation note: KV is eventually consistent with ~60s global propagation.
 * This breaker is therefore per-region best-effort. During the propagation window
 * some regions may still call a failing service. This is acceptable — it is vastly
 * better than no breaker at all. Revisit with Durable Objects (Phase 6) if flapping.
 *
 * future_scale: Replace KV hint with Durable Object for strongly-consistent state.
 */

const FAILURE_THRESHOLD = 5;       // failures before opening
const FAILURE_WINDOW_MS = 60_000;  // rolling window
const COOLDOWN_MS       = 30_000;  // time before half-open attempt
const KV_TTL_SEC        = 30;      // KV hint TTL matches cooldown

type State = 'closed' | 'open' | 'half-open';

interface BreakerState {
  state:       State;
  failures:    number;
  windowStart: number;
  openAt:      number;
}

// In-memory state per service per isolate
const breakers = new Map<string, BreakerState>();

function getState(service: string): BreakerState {
  return breakers.get(service) ?? {
    state: 'closed', failures: 0, windowStart: Date.now(), openAt: 0,
  };
}

function setState(service: string, s: BreakerState): void {
  breakers.set(service, s);
}

/** Returns true if the call should be allowed to proceed. */
export async function allowRequest(
  service: string,
  kv: KVNamespace,
): Promise<boolean> {
  const s = getState(service);
  const now = Date.now();

  if (s.state === 'closed') {
    // Also check KV hint to pick up cross-region open signals
    const kvKey = `circuit:${service}:open`;
    try {
      const hint = await kv.get(kvKey);
      if (hint !== null) {
        setState(service, { ...s, state: 'open', openAt: now });
        return false;
      }
    } catch { /* KV unavailable — trust in-memory */ }
    return true;
  }

  if (s.state === 'open') {
    if (now - s.openAt >= COOLDOWN_MS) {
      setState(service, { ...s, state: 'half-open' });
      return true; // let one test request through
    }
    return false;
  }

  // half-open: let the single test request through
  return true;
}

/** Record a successful call — close the breaker. */
export async function recordSuccess(service: string, kv: KVNamespace): Promise<void> {
  const s = getState(service);
  if (s.state !== 'closed') {
    setState(service, { state: 'closed', failures: 0, windowStart: Date.now(), openAt: 0 });
    try { await kv.delete(`circuit:${service}:open`); } catch { /* best-effort */ }
  }
}

/** Record a failed call. Opens breaker if threshold exceeded. */
export async function recordFailure(
  service: string,
  kv: KVNamespace,
  metrics?: { writeDataPoint: (opts: Record<string, unknown>) => void },
): Promise<void> {
  const s = getState(service);
  const now = Date.now();

  // Reset window if expired
  const failures    = now - s.windowStart < FAILURE_WINDOW_MS ? s.failures + 1 : 1;
  const windowStart = now - s.windowStart < FAILURE_WINDOW_MS ? s.windowStart : now;

  if (failures >= FAILURE_THRESHOLD || s.state === 'half-open') {
    setState(service, { state: 'open', failures, windowStart, openAt: now });
    try {
      await kv.put(`circuit:${service}:open`, '1', { expirationTtl: KV_TTL_SEC });
    } catch { /* best-effort */ }
    if (metrics) {
      try {
        metrics.writeDataPoint({
          indexes: [service],
          blobs: ['circuit.short_circuited', `service=${service}`],
          doubles: [1],
        });
      } catch { /* WAE write is fire-and-forget */ }
    }
  } else {
    setState(service, { ...s, failures, windowStart });
  }
}

/**
 * Wrap a third-party call with the circuit breaker.
 * Returns the result on success, or null if breaker is open or call failed.
 */
export async function withBreaker<T>(
  service: string,
  kv: KVNamespace,
  fn: () => Promise<T>,
  metrics?: { writeDataPoint: (opts: Record<string, unknown>) => void },
): Promise<T | null> {
  if (!(await allowRequest(service, kv))) return null;
  try {
    const result = await fn();
    await recordSuccess(service, kv);
    return result;
  } catch {
    await recordFailure(service, kv, metrics);
    return null;
  }
}
