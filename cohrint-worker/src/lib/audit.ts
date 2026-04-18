import type { Context } from 'hono';
import type { Bindings, Variables } from '../types';
import { createLogger } from './logger';
import { R2Guard } from './r2-guard';

export interface AuditEvent {
  event_type: 'auth' | 'data_access' | 'admin_action';
  event_name: string;       // e.g. 'auth.login', 'data_access.analytics'
  resource_type?: string;   // e.g. 'analytics', 'budget_policy', 'member'
  resource_id?: string;     // e.g. member email, policy id
  metadata?: Record<string, unknown>; // old/new values, endpoint, count, etc.
}

const INSERT_SQL = `
  INSERT INTO audit_events
    (org_id, actor_email, actor_role, action, resource, detail, ip_address, event_type)
  VALUES (?, ?, ?, ?, ?, ?, ?, ?)
`;

// ── R2 helper ─────────────────────────────────────────────────────────────────

/**
 * T014 — Append-only audit log to R2.
 * Writes a JSON snapshot of the audit event to:
 *   audit/{orgId}/{YYYY-MM-DD}/{ulid}.json
 *
 * Non-fatal: R2 failures are logged as warnings and never propagate.
 * D1 remains the primary audit store; R2 is a tamper-evident backup.
 */
function writeAuditToR2(
  bucket: R2Bucket | undefined,
  kv: KVNamespace | undefined,
  ctx: ExecutionContext,
  orgId: string,
  actorId: string,
  actorRole: string,
  ip: string,
  event: AuditEvent,
  detail: string,
): void {
  if (!bucket || !kv) return;

  // Build a time-sortable key using date + timestamp-derived suffix
  const now = new Date();
  const date = now.toISOString().slice(0, 10); // YYYY-MM-DD
  // Use timestamp + random suffix as a cheap monotonic key (no ulid dependency)
  const suffix = `${now.getTime()}-${Math.random().toString(36).slice(2, 9)}`;
  const r2Key = `audit/${orgId}/${date}/${suffix}.json`;

  const payload = JSON.stringify({
    org_id:     orgId,
    actor_id:   actorId,
    actor_role: actorRole,
    event_type: event.event_type,
    event_name: event.event_name,
    resource_type: event.resource_type ?? '',
    detail,
    ip_address: ip,
    written_at: now.toISOString(),
  });

  ctx.waitUntil((async () => {
    try {
      const guard = new R2Guard(kv);
      const bytes = new TextEncoder().encode(payload).length;
      const allowed = await guard.canWrite(bytes);
      if (!allowed) {
        const log = createLogger('audit-r2', orgId);
        log.warn('audit: R2 monthly free-tier limit reached — skipping R2 backup');
        return;
      }
      await bucket.put(r2Key, payload, {
        httpMetadata: { contentType: 'application/json' },
      });
      guard.recordWrite(ctx, bytes);
    } catch (err) {
      const log = createLogger('audit-r2', orgId);
      log.warn('audit: R2 write failed (non-fatal)', { r2Key, err: err instanceof Error ? err : new Error(String(err)) });
    }
  })());
}

// ── logAudit ──────────────────────────────────────────────────────────────────

/**
 * Fire-and-forget audit log writer for use inside Hono route handlers.
 * Pulls org_id, role, memberId from request context automatically.
 * Accepts optional overrides for auth.failed cases where context is not set.
 *
 * Never throws. Never awaited. D1 failures are silently discarded.
 * T014: also writes to R2 (CACHE_BUCKET) as an append-only backup.
 */
export function logAudit(
  c: Context<{ Bindings: Bindings; Variables: Variables }>,
  event: AuditEvent,
  overrides?: { orgId?: string; actorId?: string; actorRole?: string },
): void {
  const orgId    = overrides?.orgId     ?? c.get('orgId')    ?? 'unknown';
  const role     = overrides?.actorRole ?? c.get('role')     ?? 'unknown';
  const memberId    = c.get('memberId');
  const memberEmail = c.get('memberEmail');
  const defaultActorId = memberEmail
    ?? (memberId
      ? `member:${String(memberId).substring(0, 8)}`
      : role === 'owner' ? 'owner' : 'unknown');
  const actorId = overrides?.actorId ?? defaultActorId;
  const ip       = c.req.header('CF-Connecting-IP')
    ?? c.req.header('X-Forwarded-For')
    ?? '';

  const detail = JSON.stringify({
    ...(event.resource_id ? { resource_id: event.resource_id } : {}),
    ...(event.metadata    ?? {}),
  });

  c.executionCtx.waitUntil(
    c.env.DB.prepare(INSERT_SQL)
      .bind(orgId, actorId, role, event.event_name,
            event.resource_type ?? '', detail, ip, event.event_type)
      .run()
      .catch(() => {}), // audit failures must never propagate
  );

  // T014 — dual-write to R2 (non-fatal)
  writeAuditToR2(c.env.CACHE_BUCKET, c.env.KV, c.executionCtx, orgId, actorId, role, ip, event, detail);
}

// ── logAuditRaw ───────────────────────────────────────────────────────────────

/**
 * Fire-and-forget variant for use before Hono context variables are set
 * (e.g., inside authMiddleware on the failure path).
 * T014: also writes to R2 when bucket is provided.
 */
export function logAuditRaw(
  db: D1Database,
  ctx: ExecutionContext,
  ip: string,
  orgId: string,
  actorId: string,
  actorRole: string,
  event: AuditEvent,
  bucket?: R2Bucket,
  kv?: KVNamespace,
): void {
  const detail = JSON.stringify({
    ...(event.resource_id ? { resource_id: event.resource_id } : {}),
    ...(event.metadata    ?? {}),
  });

  ctx.waitUntil(
    db.prepare(INSERT_SQL)
      .bind(orgId, actorId, actorRole, event.event_name,
            event.resource_type ?? '', detail, ip, event.event_type)
      .run()
      .catch(() => {}),
  );

  // T014 — dual-write to R2 (non-fatal, guard requires KV)
  writeAuditToR2(bucket, kv, ctx, orgId, actorId, actorRole, ip, event, detail);
}
