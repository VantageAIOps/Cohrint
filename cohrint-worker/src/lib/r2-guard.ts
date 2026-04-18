/**
 * R2 free-tier write guard.
 *
 * Cloudflare R2 free tier (per month):
 *   - 10 GB storage
 *   - 1,000,000 Class A ops (PUT / POST / LIST / DELETE)
 *   - 10,000,000 Class B ops (GET / HEAD) — reads are cheap, not tracked here
 *
 * This guard tracks two KV counters per calendar month:
 *   r2:ops:{YYYY-MM}   — Class A write operation count (TTL 40 days)
 *   r2:bytes:{YYYY-MM} — cumulative bytes written (TTL 40 days)
 *
 * Thresholds are set at 80% of free tier so there is headroom before billing
 * kicks in even if counters drift slightly due to KV eventual consistency.
 *
 * Usage:
 *   const guard = new R2Guard(env.KV);
 *   if (await guard.canWrite(estimatedBytes)) {
 *     await bucket.put(key, body);
 *     guard.recordWrite(ctx, actualBytes); // fire-and-forget
 *   }
 */

// 80 % of free-tier limits
const MAX_OPS_PER_MONTH   = 800_000;
const MAX_BYTES_PER_MONTH = 8 * 1024 * 1024 * 1024; // 8 GiB
const KV_TTL_SECONDS      = 40 * 24 * 60 * 60;      // 40 days

function monthKey(suffix: 'ops' | 'bytes'): string {
  const now = new Date();
  const ym  = `${now.getUTCFullYear()}-${String(now.getUTCMonth() + 1).padStart(2, '0')}`;
  return `r2:${suffix}:${ym}`;
}

export class R2Guard {
  private kv: KVNamespace;

  constructor(kv: KVNamespace) {
    this.kv = kv;
  }

  /**
   * Returns true when both monthly op count and byte count are within limits.
   * On any KV error, allows the write (fail-open keeps cache/audit working).
   */
  async canWrite(estimatedBytes: number): Promise<boolean> {
    try {
      const [opsStr, bytesStr] = await Promise.all([
        this.kv.get(monthKey('ops')),
        this.kv.get(monthKey('bytes')),
      ]);
      const ops   = opsStr   ? parseInt(opsStr,   10) : 0;
      const bytes = bytesStr ? parseInt(bytesStr, 10) : 0;
      return ops < MAX_OPS_PER_MONTH && (bytes + estimatedBytes) < MAX_BYTES_PER_MONTH;
    } catch {
      return true; // fail-open
    }
  }

  /**
   * Increments monthly counters after a successful write.
   * Fire-and-forget via ctx.waitUntil so it never blocks the response.
   */
  recordWrite(ctx: ExecutionContext, actualBytes: number): void {
    ctx.waitUntil(this._increment(actualBytes));
  }

  private async _increment(bytes: number): Promise<void> {
    try {
      const [opsStr, bytesStr] = await Promise.all([
        this.kv.get(monthKey('ops')),
        this.kv.get(monthKey('bytes')),
      ]);
      const newOps   = (opsStr   ? parseInt(opsStr,   10) : 0) + 1;
      const newBytes = (bytesStr ? parseInt(bytesStr, 10) : 0) + bytes;
      await Promise.all([
        this.kv.put(monthKey('ops'),   String(newOps),   { expirationTtl: KV_TTL_SECONDS }),
        this.kv.put(monthKey('bytes'), String(newBytes), { expirationTtl: KV_TTL_SECONDS }),
      ]);
    } catch {
      // counter drift is acceptable; never throw from a fire-and-forget path
    }
  }

  /** Returns current month's counters for the superadmin storage endpoint. */
  async stats(): Promise<{ ops: number; bytes: number; ops_limit: number; bytes_limit: number }> {
    try {
      const [opsStr, bytesStr] = await Promise.all([
        this.kv.get(monthKey('ops')),
        this.kv.get(monthKey('bytes')),
      ]);
      return {
        ops:         opsStr   ? parseInt(opsStr,   10) : 0,
        bytes:       bytesStr ? parseInt(bytesStr, 10) : 0,
        ops_limit:   MAX_OPS_PER_MONTH,
        bytes_limit: MAX_BYTES_PER_MONTH,
      };
    } catch {
      return { ops: 0, bytes: 0, ops_limit: MAX_OPS_PER_MONTH, bytes_limit: MAX_BYTES_PER_MONTH };
    }
  }
}
