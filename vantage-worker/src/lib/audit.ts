import type { Context } from 'hono';
import type { Bindings, Variables } from '../types';

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

/**
 * Fire-and-forget audit log writer for use inside Hono route handlers.
 * Pulls org_id, role, memberId from request context automatically.
 * Accepts optional overrides for auth.failed cases where context is not set.
 *
 * Never throws. Never awaited. D1 failures are silently discarded.
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
}

/**
 * Fire-and-forget variant for use before Hono context variables are set
 * (e.g., inside authMiddleware on the failure path).
 */
export function logAuditRaw(
  db: D1Database,
  ctx: ExecutionContext,
  ip: string,
  orgId: string,
  actorId: string,
  actorRole: string,
  event: AuditEvent,
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
}
