/**
 * Cohrint — OpenTelemetry Collector Endpoint (Multi-Platform)
 *
 * Receives OTLP HTTP/protobuf and HTTP/JSON from 7+ AI coding tools:
 *
 *   NATIVE OTEL SUPPORT:
 *   ├── Claude Code     (service.name = "claude-code")
 *   ├── GitHub Copilot  (service.name = "copilot-chat")
 *   ├── Gemini CLI      (service.name = "gemini-cli")
 *   ├── OpenAI Codex    (service.name = "codex-cli" or "codex")
 *   ├── Cline           (service.name = "cline")
 *   ├── OpenCode        (service.name = "opencode")
 *   └── Kiro            (service.name = "kiro")
 *
 *   AUTO-INSTRUMENTATION (custom API code):
 *   ├── OpenAI SDK      (opentelemetry-instrumentation-openai-v2)
 *   ├── Anthropic SDK   (GenAI semantic conventions)
 *   └── Vercel AI SDK   (built-in OTel)
 *
 * Endpoints:
 *   POST /v1/otel/v1/metrics   — OTLP metrics (HTTP/JSON or protobuf)
 *   POST /v1/otel/v1/logs      — OTLP logs/events (HTTP/JSON or protobuf)
 *   POST /v1/otel/v1/traces    — OTLP traces (HTTP/JSON, for future use)
 *
 * Auth:
 *   - Header: Authorization: Bearer crt_...  (Cohrint API key)
 *   - Or via OTEL_EXPORTER_OTLP_HEADERS env var on client side
 *
 * No latency added to the user's AI workflow — we're a telemetry SINK,
 * not in the request path.
 */

import { Hono } from 'hono';
import type { Bindings, Variables } from '../types';
import { estimateCostUsd } from '../lib/pricing';
import { createLogger } from '../lib/logger';

const otel = new Hono<{ Bindings: Bindings; Variables: Variables }>();

// ── Ingest hard caps (DoS + storage bloat protection) ──────────────────────
// Every field below is an upper bound; legitimate clients should never hit
// these. We truncate silently rather than rejecting — dropping a whole batch
// over one oversized attribute would be worse than storing a truncated value.
const OTEL_LIMITS = {
  MAX_BODY_BYTES:          5 * 1024 * 1024, // 5 MB per OTLP request
  MAX_RESOURCE_METRICS:    200,
  MAX_SCOPE_METRICS:       50,   // per resource
  MAX_METRICS:             200,  // per scope
  MAX_DATAPOINTS:          500,  // per metric
  MAX_ATTRS_PER_DP:        50,
  MAX_ATTR_KEY_CHARS:      128,
  MAX_ATTR_VALUE_CHARS:    4096,
  MAX_METRIC_VALUE:        1e12, // 1 trillion tokens is already absurd
} as const;

/** Bounded getAttr — truncates both key and string value. */
function capAttrString(s: string | null | undefined, max: number): string | undefined {
  if (s == null) return undefined;
  return s.length > max ? s.slice(0, max) : s;
}

/** Clamp a numeric metric value to a sane range; drop NaN/Infinity. */
function clampMetricValue(n: number): number {
  if (!Number.isFinite(n)) return 0;
  if (n < 0) return 0;
  return Math.min(n, OTEL_LIMITS.MAX_METRIC_VALUE);
}

/** Parse an OTLP timeUnixNano into a Date; reject malformed values. */
function parseOtelTimestamp(raw: string | number | undefined): Date {
  if (raw == null) return new Date();
  const s = String(raw);
  // OTLP nanos are 19-digit strings; also allow shorter integers for older SDKs.
  if (!/^\d{1,19}$/.test(s)) return new Date();
  try {
    const ms = Number(BigInt(s) / 1_000_000n);
    if (!Number.isFinite(ms)) return new Date();
    // Reject obvious garbage: before 2000-01-01 or after now + 1h.
    const floor = 946_684_800_000;
    const ceiling = Date.now() + 3600_000;
    if (ms < floor || ms > ceiling) return new Date();
    return new Date(ms);
  } catch {
    return new Date();
  }
}

// ── Types for OTLP JSON format ──────────────────────────────────────────────

interface OTLPResourceAttribute {
  key: string;
  value: { stringValue?: string; intValue?: string; doubleValue?: number; boolValue?: boolean };
}

interface OTLPResource {
  attributes: OTLPResourceAttribute[];
}

interface OTLPNumberDataPoint {
  attributes: OTLPResourceAttribute[];
  asInt?: string;
  asDouble?: number;
  startTimeUnixNano?: string;
  timeUnixNano?: string;
}

interface OTLPHistogramDataPoint {
  attributes: OTLPResourceAttribute[];
  count?: string;
  sum?: number;
  startTimeUnixNano?: string;
  timeUnixNano?: string;
}

interface OTLPMetric {
  name: string;
  unit?: string;
  sum?: { dataPoints: OTLPNumberDataPoint[]; isMonotonic?: boolean };
  histogram?: { dataPoints: OTLPHistogramDataPoint[] };
  gauge?: { dataPoints: OTLPNumberDataPoint[] };
}

interface OTLPScopeMetrics {
  scope?: { name?: string; version?: string };
  metrics: OTLPMetric[];
}

interface OTLPResourceMetrics {
  resource: OTLPResource;
  scopeMetrics: OTLPScopeMetrics[];
}

interface OTLPMetricsRequest {
  resourceMetrics: OTLPResourceMetrics[];
}

interface OTLPLogRecord {
  timeUnixNano?: string;
  severityText?: string;
  body?: { stringValue?: string; kvlistValue?: { values: OTLPResourceAttribute[] } };
  attributes: OTLPResourceAttribute[];
}

interface OTLPScopeLogs {
  logRecords: OTLPLogRecord[];
}

interface OTLPResourceLogs {
  resource: OTLPResource;
  scopeLogs: OTLPScopeLogs[];
}

interface OTLPLogsRequest {
  resourceLogs: OTLPResourceLogs[];
}

// ── Parsed record for storage ───────────────────────────────────────────────

interface ParsedOTelRecord {
  org_id: string;
  provider: string;       // 'claude_code' | 'copilot_chat' | 'gemini_cli' | 'openai_api' | 'anthropic_api'
  tool_type: string;      // 'coding_assistant' | 'cli' | 'api'
  source: 'otel';
  developer_email: string | null;
  developer_id: string | null;
  team: string | null;
  cost_center: string | null;
  agent_name: string | null;
  business_unit: string | null;
  model: string | null;
  input_tokens: number;
  output_tokens: number;
  cached_tokens: number;
  cache_creation_tokens: number;
  total_requests: number;
  cost_usd: number;
  session_id: string | null;
  terminal_type: string | null;
  lines_added: number;
  lines_removed: number;
  commits: number;
  pull_requests: number;
  active_time_s: number;
  ttft_ms: number | null;
  latency_ms: number | null;
  raw_metric_name: string;
  timestamp: string;
}

// Infer a best-guess model from the OTel service.name when no model attribute is present.
// Returns null if the service name gives no useful signal.
function inferModelFromServiceName(serviceName: string): string | null {
  const sn = serviceName.toLowerCase();
  if (sn.includes('claude'))  return 'claude-sonnet-4-6';
  if (sn.includes('copilot')) return 'gpt-4o';
  if (sn.includes('gemini'))  return 'gemini-1.5-pro';
  if (sn.includes('codex') || sn.includes('openai')) return 'gpt-4o';
  return null;
}

// ── Helpers ─────────────────────────────────────────────────────────────────

function getAttr(attrs: OTLPResourceAttribute[], key: string): string | null {
  const found = attrs.find(a => a.key === key);
  if (!found) return null;
  return found.value.stringValue ?? found.value.intValue ?? String(found.value.doubleValue ?? found.value.boolValue ?? '');
}

function getNumericValue(dp: OTLPNumberDataPoint): number {
  if (dp.asDouble !== undefined) return dp.asDouble;
  if (dp.asInt !== undefined) return parseInt(dp.asInt, 10);
  return 0;
}

function detectProvider(serviceName: string): { provider: string; tool_type: string } {
  const sn = serviceName.toLowerCase();
  // ── 7 Native OTel AI Coding Tools ──
  if (sn.includes('claude') || sn === 'claude-code')       return { provider: 'claude_code',  tool_type: 'coding_assistant' };
  if (sn.includes('copilot'))                               return { provider: 'copilot_chat', tool_type: 'coding_assistant' };
  if (sn.includes('gemini'))                                return { provider: 'gemini_cli',   tool_type: 'cli' };
  if (sn.includes('codex'))                                 return { provider: 'codex_cli',    tool_type: 'cli' };
  if (sn.includes('cline'))                                 return { provider: 'cline',        tool_type: 'coding_assistant' };
  if (sn.includes('opencode'))                              return { provider: 'opencode',     tool_type: 'cli' };
  if (sn.includes('kiro'))                                  return { provider: 'kiro',         tool_type: 'coding_assistant' };
  if (sn.includes('windsurf') || sn.includes('cascade'))    return { provider: 'windsurf',     tool_type: 'coding_assistant' };
  if (sn.includes('aider'))                                 return { provider: 'aider',        tool_type: 'cli' };
  if (sn.includes('roo'))                                   return { provider: 'roo_code',     tool_type: 'coding_assistant' };
  // ── Auto-instrumented API SDKs (GenAI semantic conventions) ──
  return { provider: 'custom_api', tool_type: 'api' };
}

function extractAuth(c: any): string | null {
  const authHeader = c.req.header('Authorization') ?? '';
  if (authHeader.startsWith('Bearer ')) return authHeader.slice(7);
  return null;
}

// KV-based rate limiter — mirrors auth.ts but for OTel ingest (higher limit: 3000 RPM)
async function otelRateLimit(kv: KVNamespace, orgId: string, limitRpm: number): Promise<boolean> {
  try {
    const key   = `rl:otel:${orgId}:${Math.floor(Date.now() / 60_000)}`;
    const raw   = await kv.get(key);
    const count = raw ? parseInt(raw, 10) : 0;
    if (count >= limitRpm) return false;
    await kv.put(key, String(count + 1), { expirationTtl: 70 });
  } catch { /* KV unavailable — allow through */ }
  return true;
}

interface OtelAuthCtx {
  orgId: string;
  /** null when the key is an owner key (unrestricted). Otherwise the member's scope_team (may still be null if member is org-wide). */
  memberScopeTeam: string | null;
  /** Set only for member keys. When set, OTel attributes claiming a different developer_email are rewritten. */
  memberEmail: string | null;
  isMember: boolean;
}

// Validate API key and return auth context (org + member scoping if applicable).
// Auth uses orgs.api_key_hash (owner) or org_members.api_key_hash (member).
async function resolveOrg(apiKey: string | null, db: D1Database): Promise<OtelAuthCtx | null> {
  if (!apiKey) return null;
  const encoder = new TextEncoder();
  const data = encoder.encode(apiKey);
  const hashBuffer = await crypto.subtle.digest('SHA-256', data);
  const hashArray = Array.from(new Uint8Array(hashBuffer));
  const hash = hashArray.map(b => b.toString(16).padStart(2, '0')).join('');

  // Check owner key first (unrestricted — can emit on behalf of any member)
  const org = await db.prepare('SELECT id FROM orgs WHERE api_key_hash = ?').bind(hash).first() as { id: string } | null;
  if (org) return { orgId: org.id, memberScopeTeam: null, memberEmail: null, isMember: false };

  // Check member key — enforce scope_team + email to prevent cross-team/user spoof.
  const member = await db.prepare(
    'SELECT org_id, scope_team, email FROM org_members WHERE api_key_hash = ?',
  ).bind(hash).first() as { org_id: string; scope_team: string | null; email: string | null } | null;
  if (!member) return null;
  return {
    orgId: member.org_id,
    memberScopeTeam: member.scope_team,
    memberEmail: member.email,
    isMember: true,
  };
}

// ── Metrics Endpoint ────────────────────────────────────────────────────────

otel.post('/v1/metrics', async (c) => {
  const startMs = Date.now();

  // Auth
  const apiKey = extractAuth(c);
  const auth = await resolveOrg(apiKey, c.env.DB);
  if (!auth) {
    return c.json({ error: 'Invalid or missing API key. Set OTEL_EXPORTER_OTLP_HEADERS="Authorization=Bearer crt_YOUR_KEY"' }, 401);
  }
  const orgId = auth.orgId;

  // Rate limit: 3000 OTel ingest requests per minute per org
  const otelRpm = parseInt(c.env.RATE_LIMIT_RPM ?? '1000', 10) * 3;
  const allowed = await otelRateLimit(c.env.KV, orgId, otelRpm);
  if (!allowed) {
    const retryAt = Math.ceil(Date.now() / 60_000) * 60;
    c.header('Retry-After', String(retryAt - Math.floor(Date.now() / 1000)));
    return c.json({ error: 'Rate limit exceeded', retry_after: retryAt }, 429);
  }

  // Body-size guard — reject oversized payloads before JSON parse so a
  // malicious client can't pin CPU parsing 100MB of nested JSON.
  const contentLength = Number(c.req.header('content-length') ?? 0);
  if (Number.isFinite(contentLength) && contentLength > OTEL_LIMITS.MAX_BODY_BYTES) {
    return c.json({ error: `Body too large (max ${OTEL_LIMITS.MAX_BODY_BYTES} bytes)` }, 413);
  }

  // Parse OTLP JSON body
  let body: OTLPMetricsRequest;
  try {
    body = await c.req.json<OTLPMetricsRequest>();
  } catch {
    return c.json({ error: 'Invalid OTLP JSON body' }, 400);
  }

  const records: ParsedOTelRecord[] = [];

  const resourceMetrics = (body.resourceMetrics ?? []).slice(0, OTEL_LIMITS.MAX_RESOURCE_METRICS);
  for (const rm of resourceMetrics) {
    const resAttrs = rm.resource?.attributes ?? [];
    const serviceName = getAttr(resAttrs, 'service.name') ?? 'unknown';
    const { provider, tool_type } = detectProvider(serviceName);

    // Extract user identity from resource attributes
    let developerEmail = getAttr(resAttrs, 'user.email');
    const developerId = getAttr(resAttrs, 'developer.id') ?? getAttr(resAttrs, 'user.account_uuid') ?? getAttr(resAttrs, 'user.account_id') ?? getAttr(resAttrs, 'user.id');
    const sessionId = getAttr(resAttrs, 'session.id');
    const terminalType = getAttr(resAttrs, 'terminal.type');
    let team          = getAttr(resAttrs, 'team.id') ?? getAttr(resAttrs, 'department');
    const costCenter   = getAttr(resAttrs, 'cost_center');
    const agentName    = getAttr(resAttrs, 'agent_name') ?? getAttr(resAttrs, 'gen_ai.agent.name') ?? serviceName;
    const businessUnit = getAttr(resAttrs, 'business_unit') ?? getAttr(resAttrs, 'cost_center');

    // Member-key tenancy enforcement: a member key MUST NOT emit metrics
    // attributed to another user or team. Override the claimed attributes with
    // the authenticated member's identity rather than rejecting the batch
    // (SDKs emit in bulk — one mis-tagged attr shouldn't drop the whole flush).
    if (auth.isMember) {
      if (auth.memberEmail) developerEmail = auth.memberEmail;
      if (auth.memberScopeTeam) team = auth.memberScopeTeam;
    }

    const scopeMetrics = (rm.scopeMetrics ?? []).slice(0, OTEL_LIMITS.MAX_SCOPE_METRICS);
    for (const sm of scopeMetrics) {
      const metrics = (sm.metrics ?? []).slice(0, OTEL_LIMITS.MAX_METRICS);
      for (const metric of metrics) {
        // Reject records with no metric name — they're garbage that would pollute analytics.
        if (!metric.name) continue;
        const dataPoints = (metric.sum?.dataPoints ?? metric.gauge?.dataPoints ?? []).slice(0, OTEL_LIMITS.MAX_DATAPOINTS);
        const histPoints = (metric.histogram?.dataPoints ?? []).slice(0, OTEL_LIMITS.MAX_DATAPOINTS);

        for (const dp of dataPoints) {
          const metricAttrs = (dp.attributes ?? []).slice(0, OTEL_LIMITS.MAX_ATTRS_PER_DP);
          // Model resolution: metric attrs → resource attrs → service.name inference
          const model = capAttrString(
            getAttr(metricAttrs, 'model')
              ?? getAttr(metricAttrs, 'gen_ai.request.model')
              ?? getAttr(resAttrs, 'gen_ai.request.model')
              ?? getAttr(resAttrs, 'model')
              ?? inferModelFromServiceName(serviceName),
            OTEL_LIMITS.MAX_ATTR_VALUE_CHARS,
          ) ?? null;
          const tokenType = capAttrString(getAttr(metricAttrs, 'type') ?? getAttr(metricAttrs, 'gen_ai.token.type'), 64);
          const value = clampMetricValue(getNumericValue(dp));
          const ts = parseOtelTimestamp(dp.timeUnixNano).toISOString();

          const record: ParsedOTelRecord = {
            org_id: orgId,
            provider,
            tool_type,
            source: 'otel',
            developer_email: developerEmail,
            developer_id: developerId,
            team,
            cost_center: costCenter,
            agent_name: agentName,
            business_unit: businessUnit,
            model,
            input_tokens: 0,
            output_tokens: 0,
            cached_tokens: 0,
            cache_creation_tokens: 0,
            total_requests: 0,
            cost_usd: 0,
            session_id: sessionId,
            terminal_type: terminalType,
            lines_added: 0,
            lines_removed: 0,
            commits: 0,
            pull_requests: 0,
            active_time_s: 0,
            ttft_ms: null,
            latency_ms: null,
            raw_metric_name: metric.name,
            timestamp: ts,
          };

          // Route metric to correct field
          // Supports: Claude Code, Copilot, Gemini CLI, Codex CLI, Cline,
          //           OpenCode, Kiro, Windsurf, Aider, Roo Code,
          //           and GenAI semantic conventions (OpenAI/Anthropic auto-instrumentation)
          switch (metric.name) {
            // ── Token usage (all platforms) ──
            case 'claude_code.token.usage':
            case 'gemini_cli.token.usage':
            case 'gen_ai.client.token.usage':    // GenAI conventions (Copilot, Codex, auto-instrumented SDKs)
            case 'codex.token.usage':            // Codex CLI
            case 'cline.token.usage':            // Cline
              if (tokenType === 'input') record.input_tokens = value;
              else if (tokenType === 'output') record.output_tokens = value;
              else if (tokenType === 'cacheRead' || tokenType === 'cache') record.cached_tokens = value;
              else if (tokenType === 'cacheCreation') record.cache_creation_tokens = value;
              else if (tokenType === 'thought') record.input_tokens += value; // Gemini thinking tokens
              else if (tokenType === 'tool') record.input_tokens += value;    // Gemini tool tokens
              break;

            // ── Cost (tools that emit USD cost directly) ──
            case 'claude_code.cost.usage':
            case 'codex.cost.usage':
              record.cost_usd = value;
              break;

            // ── Lines of code (Claude Code, Codex) ──
            case 'claude_code.lines_of_code.count':
            case 'codex.lines_of_code.count':
              if (tokenType === 'added') record.lines_added = value;
              else if (tokenType === 'removed') record.lines_removed = value;
              break;

            // ── Commits and PRs (Claude Code, Codex) ──
            case 'claude_code.commit.count':
            case 'codex.commit.count':
              record.commits = value;
              break;
            case 'claude_code.pull_request.count':
            case 'codex.pull_request.count':
              record.pull_requests = value;
              break;

            // ── Active time (Claude Code) ──
            case 'claude_code.active_time.total':
              record.active_time_s = value;
              break;

            // ── Session count (all tools) ──
            case 'claude_code.session.count':
            case 'copilot_chat.session.count':
            case 'gemini_cli.session.count':
            case 'codex.session.count':
            case 'cline.session.count':
              // Session start — record exists as-is
              break;

            // ── Tool calls (all tools that report them) ──
            case 'copilot_chat.tool.call.count':
            case 'gemini_cli.tool.call.count':
            case 'codex.tool.call.count':
            case 'cline.tool.call.count':
              record.total_requests = value;
              break;

            // ── Agent turns (Copilot) ──
            case 'copilot_chat.agent.turn.count':
              record.total_requests = value;
              break;

            // ── API request counts ──
            case 'gemini_cli.api.request.count':
            case 'codex.api.request.count':
              record.total_requests = value;
              break;

            // ── File operations (Gemini CLI) ──
            case 'gemini_cli.file.operation.count':
              break;

            // ── Context compression (Gemini CLI) ──
            case 'gemini_cli.chat_compression':
              break;

            // ── Code edit decisions (Claude Code) ──
            case 'claude_code.code_edit_tool.decision':
              break;

            default:
              // Unknown metric — still store it for future analysis
              // but only if it looks like a token/cost metric
              if (metric.name.includes('token') || metric.name.includes('cost')) {
                record.input_tokens = value; // best-effort
              } else {
                continue;
              }
          }

          records.push(record);
        }

        // Handle histogram data points (token usage from Copilot, duration metrics)
        for (const hp of histPoints) {
          const histAttrs = (hp.attributes ?? []).slice(0, OTEL_LIMITS.MAX_ATTRS_PER_DP);
          const model = capAttrString(
            getAttr(histAttrs, 'gen_ai.request.model') ?? getAttr(histAttrs, 'model'),
            OTEL_LIMITS.MAX_ATTR_VALUE_CHARS,
          ) ?? null;
          const tokenType = capAttrString(getAttr(histAttrs, 'gen_ai.token.type') ?? getAttr(histAttrs, 'type'), 64);
          const ts = parseOtelTimestamp(hp.timeUnixNano).toISOString();

          if (metric.name === 'gen_ai.client.token.usage' && hp.sum !== undefined) {
            const record: ParsedOTelRecord = {
              org_id: orgId, provider, tool_type, source: 'otel',
              developer_email: developerEmail, developer_id: developerId,
              team, cost_center: costCenter, agent_name: agentName, business_unit: businessUnit, model,
              input_tokens: tokenType === 'input' ? hp.sum : 0,
              output_tokens: tokenType === 'output' ? hp.sum : 0,
              cached_tokens: 0, cache_creation_tokens: 0, total_requests: 0, cost_usd: 0,
              session_id: sessionId, terminal_type: terminalType,
              lines_added: 0, lines_removed: 0, commits: 0, pull_requests: 0,
              active_time_s: 0, ttft_ms: null, latency_ms: null,
              raw_metric_name: metric.name, timestamp: ts,
            };
            records.push(record);
          }

          if (metric.name === 'gen_ai.client.operation.duration' && hp.sum !== undefined) {
            const record: ParsedOTelRecord = {
              org_id: orgId, provider, tool_type, source: 'otel',
              developer_email: developerEmail, developer_id: developerId,
              team, cost_center: costCenter, agent_name: agentName, business_unit: businessUnit, model,
              input_tokens: 0, output_tokens: 0, cached_tokens: 0,
              cache_creation_tokens: 0, total_requests: 0, cost_usd: 0,
              session_id: sessionId, terminal_type: terminalType,
              lines_added: 0, lines_removed: 0, commits: 0, pull_requests: 0,
              active_time_s: 0, ttft_ms: null,
              latency_ms: hp.sum * 1000, // seconds → ms
              raw_metric_name: metric.name, timestamp: ts,
            };
            records.push(record);
          }

          if (metric.name === 'copilot_chat.time_to_first_token' && hp.sum !== undefined) {
            const record: ParsedOTelRecord = {
              org_id: orgId, provider, tool_type, source: 'otel',
              developer_email: developerEmail, developer_id: developerId,
              team, cost_center: costCenter, agent_name: agentName, business_unit: businessUnit, model,
              input_tokens: 0, output_tokens: 0, cached_tokens: 0,
              cache_creation_tokens: 0, total_requests: 0, cost_usd: 0,
              session_id: sessionId, terminal_type: terminalType,
              lines_added: 0, lines_removed: 0, commits: 0, pull_requests: 0,
              active_time_s: 0, ttft_ms: hp.sum * 1000, latency_ms: null,
              raw_metric_name: metric.name, timestamp: ts,
            };
            records.push(record);
          }
        }
      }
    }
  }

  // Auto-calculate cost when only tokens are provided (no separate cost metric)
  for (const r of records) {
    if (r.cost_usd === 0 && (r.input_tokens > 0 || r.output_tokens > 0)) {
      r.cost_usd = estimateCostUsd(r.model, r.input_tokens, r.output_tokens, r.cached_tokens, r.cache_creation_tokens);
    }
    if (!r.model && (r.input_tokens > 0 || r.output_tokens > 0)) {
      createLogger(c.get('requestId') ?? 'unknown', orgId).warn('otel model_missing — cost recorded as $0', { provider: r.provider, metric: r.raw_metric_name });
    }
  }

  // Batch insert into D1
  if (records.length > 0) {
    const usageStmt = c.env.DB.prepare(`
      INSERT INTO cross_platform_usage (
        org_id, provider, tool_type, source, developer_id, developer_email,
        team, cost_center, model, input_tokens, output_tokens, cached_tokens,
        cache_creation_tokens, cost_usd, session_id, terminal_type,
        lines_added, lines_removed, commits, pull_requests, active_time_s,
        ttft_ms, latency_ms, period_start, period_end, raw_data, created_at_unix
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CAST(strftime('%s', 'now') AS INTEGER))
    `);

    const batch = records.map(r => usageStmt.bind(
      r.org_id, r.provider, r.tool_type, r.source,
      r.developer_id, r.developer_email, r.team, r.cost_center,
      r.model, r.input_tokens, r.output_tokens, r.cached_tokens,
      r.cache_creation_tokens, r.cost_usd, r.session_id, r.terminal_type,
      r.lines_added, r.lines_removed, r.commits, r.pull_requests,
      r.active_time_s, r.ttft_ms, r.latency_ms,
      r.timestamp, r.timestamp, JSON.stringify({ metric: r.raw_metric_name }),
    ));

    // Merge records by (session_id, model, developer_email) before inserting into
    // otel_events so that per-metric data points (tokens + explicit cost sent as
    // separate counters) appear as a single row in the /live feed.
    const mergeKey = (r: ParsedOTelRecord) =>
      `${r.session_id ?? ''}|${r.model ?? ''}|${r.developer_email ?? ''}`;
    const mergeMap = new Map<string, ParsedOTelRecord>();
    for (const r of records) {
      if (r.input_tokens === 0 && r.output_tokens === 0 && r.cost_usd === 0) continue;
      const key = mergeKey(r);
      const existing = mergeMap.get(key);
      if (!existing) {
        mergeMap.set(key, { ...r });
      } else {
        existing.input_tokens  += r.input_tokens;
        existing.output_tokens += r.output_tokens;
        existing.cached_tokens += r.cached_tokens;
        existing.cache_creation_tokens += r.cache_creation_tokens;
        // Prefer explicit cost over auto-estimated cost (max wins)
        if (r.cost_usd > existing.cost_usd) existing.cost_usd = r.cost_usd;
      }
    }
    // Re-run auto-cost on merged records in case merging cleared explicit cost
    for (const r of mergeMap.values()) {
      if (r.cost_usd === 0 && (r.input_tokens > 0 || r.output_tokens > 0)) {
        r.cost_usd = estimateCostUsd(r.model, r.input_tokens, r.output_tokens, r.cached_tokens, r.cache_creation_tokens);
      }
    }
    const tokenRecords = [...mergeMap.values()];
    const eventStmt = c.env.DB.prepare(`
      INSERT INTO otel_events (
        org_id, provider, session_id, developer_email, event_name,
        model, cost_usd, tokens_in, tokens_out, duration_ms, timestamp, raw_attrs,
        agent_name, team, business_unit
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `);
    for (const r of tokenRecords) {
      batch.push(eventStmt.bind(
        r.org_id, r.provider, r.session_id, r.developer_email,
        r.raw_metric_name, r.model, r.cost_usd,
        r.input_tokens, r.output_tokens, r.latency_ms ?? 0,
        r.timestamp, JSON.stringify({ metric: r.raw_metric_name, source: 'otel_metrics' }),
        r.agent_name, r.team, r.business_unit,
      ));
    }

    try {
      await c.env.DB.batch(batch);
    } catch (err) {
      createLogger(c.get('requestId') ?? 'unknown', orgId).error('otel D1 batch insert failed', { err: err instanceof Error ? err : new Error(String(err)) });
      return c.json({ error: 'Failed to store metrics' }, 500);
    }

    // Upsert session rollup — one row per unique session_id in this batch
    const sessionUpserts = new Map<string, {
      provider: string; developer_email: string; team: string; model: string;
      input_tokens: number; output_tokens: number; cached_tokens: number; cost_usd: number;
      timestamp: string;
    }>();
    for (const r of tokenRecords) {
      if (!r.session_id) continue;
      const existing = sessionUpserts.get(r.session_id);
      if (existing) {
        existing.input_tokens  += r.input_tokens  ?? 0;
        existing.output_tokens += r.output_tokens ?? 0;
        existing.cached_tokens += r.cached_tokens ?? 0;
        existing.cost_usd      += r.cost_usd      ?? 0;
      } else {
        sessionUpserts.set(r.session_id, {
          provider:        r.provider        ?? '',
          developer_email: r.developer_email ?? '',
          team:            r.team            ?? '',
          model:           r.model           ?? '',
          input_tokens:    r.input_tokens    ?? 0,
          output_tokens:   r.output_tokens   ?? 0,
          cached_tokens:   r.cached_tokens   ?? 0,
          cost_usd:        r.cost_usd        ?? 0,
          timestamp:       r.timestamp,
        });
      }
    }
    if (sessionUpserts.size > 0) {
      const sessionBatch = [...sessionUpserts.entries()].map(([sessionId, s]) =>
        c.env.DB.prepare(`
          INSERT INTO otel_sessions
            (org_id, session_id, provider, developer_email, team, model,
             input_tokens, output_tokens, cached_tokens, cost_usd, event_count,
             first_seen_at, last_seen_at)
          VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
          ON CONFLICT (org_id, session_id) DO UPDATE SET
            input_tokens  = input_tokens  + excluded.input_tokens,
            output_tokens = output_tokens + excluded.output_tokens,
            cached_tokens = cached_tokens + excluded.cached_tokens,
            cost_usd      = cost_usd      + excluded.cost_usd,
            event_count   = event_count   + 1,
            last_seen_at  = excluded.last_seen_at
        `).bind(
          orgId, sessionId, s.provider, s.developer_email, s.team, s.model,
          s.input_tokens, s.output_tokens, s.cached_tokens, s.cost_usd,
          s.timestamp, s.timestamp,
        )
      );
      try {
        await c.env.DB.batch(sessionBatch);
      } catch (err) {
        createLogger(c.get('requestId') ?? 'unknown', orgId).warn('otel session upsert failed (non-critical)', { err: err instanceof Error ? err : new Error(String(err)) });
      }
    }

    // Invalidate analytics cache for this org (all prefixes including team-scoped variants)
    try {
      const prefixes = [`analytics:summary:${orgId}:`, `analytics:kpis:${orgId}:`, `analytics:timeseries:${orgId}:`];
      await Promise.all(prefixes.map(async (p) => {
        const listed = await c.env.KV.list({ prefix: p });
        if (listed.keys.length > 0) await Promise.all(listed.keys.map(k => c.env.KV.delete(k.name)));
      }));
    } catch { /* best-effort */ }

    // Broadcast all token records to KV circular buffer for SSE live feed
    for (const r of tokenRecords) {
      try {
        const seqno = Date.now();
        const streamEv = {
          seqno,
          ts: seqno,
          provider: r.provider,
          cost_usd: r.cost_usd,
          model: r.model,
          tokens: (r.input_tokens ?? 0) + (r.output_tokens ?? 0),
        };
        await c.env.KV.put(`stream:${orgId}:latest`, JSON.stringify(streamEv), { expirationTtl: 60 });
        const bufKey = `stream:${orgId}:buf`;
        const rawBuf = await c.env.KV.get(bufKey);
        const buf: typeof streamEv[] = rawBuf ? JSON.parse(rawBuf) : [];
        buf.unshift(streamEv);
        if (buf.length > 25) buf.length = 25;
        await c.env.KV.put(bufKey, JSON.stringify(buf), { expirationTtl: 300 });
      } catch {
        // KV unavailable — event still in D1, SSE broadcast skipped
      }
    }
  }

  const elapsed = Date.now() - startMs;
  createLogger(c.get('requestId') ?? 'unknown', orgId).info('otel metrics ingested', { count: records.length, ms: elapsed });

  // OTLP success response (spec: partialSuccess with rejectedDataPoints = 0 means full success)
  return c.json({ partialSuccess: { rejectedDataPoints: 0 } }, 200);
});

// ── Logs/Events Endpoint ────────────────────────────────────────────────────

otel.post('/v1/logs', async (c) => {
  const apiKey = extractAuth(c);
  const auth = await resolveOrg(apiKey, c.env.DB);
  if (!auth) {
    return c.json({ error: 'Invalid or missing API key' }, 401);
  }
  const orgId = auth.orgId;

  // Rate limit: shared OTel bucket with /v1/metrics
  const otelRpm = parseInt(c.env.RATE_LIMIT_RPM ?? '1000', 10) * 3;
  const allowed = await otelRateLimit(c.env.KV, orgId, otelRpm);
  if (!allowed) {
    const retryAt = Math.ceil(Date.now() / 60_000) * 60;
    c.header('Retry-After', String(retryAt - Math.floor(Date.now() / 1000)));
    return c.json({ error: 'Rate limit exceeded', retry_after: retryAt }, 429);
  }

  const contentLength = Number(c.req.header('content-length') ?? 0);
  if (Number.isFinite(contentLength) && contentLength > OTEL_LIMITS.MAX_BODY_BYTES) {
    return c.json({ error: `Body too large (max ${OTEL_LIMITS.MAX_BODY_BYTES} bytes)` }, 413);
  }

  let body: OTLPLogsRequest;
  try {
    body = await c.req.json<OTLPLogsRequest>();
  } catch {
    return c.json({ error: 'Invalid OTLP JSON body' }, 400);
  }

  let eventCount = 0;

  for (const rl of body.resourceLogs ?? []) {
    const resAttrs = rl.resource?.attributes ?? [];
    const serviceName = getAttr(resAttrs, 'service.name') ?? 'unknown';
    const { provider } = detectProvider(serviceName);
    let developerEmail    = getAttr(resAttrs, 'user.email');
    const developerId     = getAttr(resAttrs, 'developer.id') ?? getAttr(resAttrs, 'user.account_uuid') ?? getAttr(resAttrs, 'user.id');
    const sessionId       = getAttr(resAttrs, 'session.id');
    let logTeam           = getAttr(resAttrs, 'team.id') ?? getAttr(resAttrs, 'department');
    const logAgentName    = getAttr(resAttrs, 'agent_name') ?? getAttr(resAttrs, 'gen_ai.agent.name') ?? serviceName;
    const logBusinessUnit = getAttr(resAttrs, 'business_unit') ?? getAttr(resAttrs, 'cost_center');

    // Member-key tenancy enforcement (same as metrics route).
    if (auth.isMember) {
      if (auth.memberEmail) developerEmail = auth.memberEmail;
      if (auth.memberScopeTeam) logTeam = auth.memberScopeTeam;
    }

    for (const sl of rl.scopeLogs ?? []) {
      for (const log of sl.logRecords ?? []) {
        const logAttrs = (log.attributes ?? []).slice(0, OTEL_LIMITS.MAX_ATTRS_PER_DP);
        const eventName = capAttrString(getAttr(logAttrs, 'event.name'), 128) ?? 'unknown';
        const model = capAttrString(
          getAttr(logAttrs, 'model') ?? getAttr(logAttrs, 'gen_ai.request.model'),
          OTEL_LIMITS.MAX_ATTR_VALUE_CHARS,
        );
        const costUsd = clampMetricValue(parseFloat(getAttr(logAttrs, 'cost_usd') ?? '0'));
        const inputTokens = clampMetricValue(parseInt(getAttr(logAttrs, 'input_tokens') ?? '0', 10));
        const outputTokens = clampMetricValue(parseInt(getAttr(logAttrs, 'output_tokens') ?? '0', 10));
        const cacheReadTokens = clampMetricValue(parseInt(getAttr(logAttrs, 'cache_read_tokens') ?? '0', 10));
        const durationMs = clampMetricValue(parseFloat(getAttr(logAttrs, 'duration_ms') ?? '0'));
        const ts = parseOtelTimestamp(log.timeUnixNano).toISOString();

        // Store api_request events as usage records (most valuable)
        if (eventName === 'api_request' || eventName === 'claude_code.api_request') {
          const stmt = c.env.DB.prepare(`
            INSERT INTO cross_platform_usage (
              org_id, provider, tool_type, source, developer_id, developer_email,
              team, cost_center, model, input_tokens, output_tokens, cached_tokens,
              cache_creation_tokens, cost_usd, session_id, terminal_type,
              lines_added, lines_removed, commits, pull_requests, active_time_s,
              ttft_ms, latency_ms, period_start, period_end, raw_data, created_at_unix
            ) VALUES (?, ?, ?, 'otel', ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, 0, 0, 0, 0, 0, ?, ?, ?, ?, ?, CAST(strftime('%s', 'now') AS INTEGER))
          `);
          try {
            await stmt.bind(
              orgId, provider, 'coding_assistant', developerId, developerEmail,
              getAttr(resAttrs, 'team.id'), getAttr(resAttrs, 'cost_center'),
              model, inputTokens, outputTokens, cacheReadTokens, costUsd,
              sessionId, getAttr(resAttrs, 'terminal.type'),
              null, durationMs, ts, ts,
              JSON.stringify({ event: eventName, attrs: Object.fromEntries(logAttrs.map(a => [a.key, a.value.stringValue ?? a.value.intValue ?? a.value.doubleValue])) }),
            ).run();
            eventCount++;
          } catch (err) {
            createLogger(c.get('requestId') ?? 'unknown', orgId).error('otel/logs insert failed', { err: err instanceof Error ? err : new Error(String(err)) });
          }
        }

        // Store all events in a separate lightweight event log for audit/debugging
        try {
          // Cap raw_attrs to 16KB so one abusive client can't bloat the DB.
          const rawAttrs = JSON.stringify(Object.fromEntries(
            logAttrs.map(a => [
              capAttrString(a.key, OTEL_LIMITS.MAX_ATTR_KEY_CHARS) ?? '',
              typeof a.value.stringValue === 'string'
                ? capAttrString(a.value.stringValue, OTEL_LIMITS.MAX_ATTR_VALUE_CHARS)
                : (a.value.intValue ?? a.value.doubleValue),
            ]),
          )).slice(0, 16384);
          await c.env.DB.prepare(`
            INSERT INTO otel_events (
              org_id, provider, session_id, developer_email, event_name,
              model, cost_usd, tokens_in, tokens_out, duration_ms, timestamp, raw_attrs,
              agent_name, team, business_unit
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
          `).bind(
            orgId, provider, sessionId, developerEmail, eventName,
            model, costUsd, inputTokens, outputTokens, durationMs, ts,
            rawAttrs,
            logAgentName, logTeam, logBusinessUnit,
          ).run();
          eventCount++;
        } catch {
          // otel_events table may not exist yet — non-critical
        }

        // Broadcast api_request events to KV circular buffer for SSE live feed
        if (eventName === 'api_request' || eventName === 'claude_code.api_request') {
          try {
            const seqno = Date.now();
            const streamEv = {
              seqno,
              ts: seqno,
              provider,
              cost_usd: costUsd,
              model,
              tokens: inputTokens + outputTokens,
            };
            await c.env.KV.put(`stream:${orgId}:latest`, JSON.stringify(streamEv), { expirationTtl: 60 });
            const bufKey = `stream:${orgId}:buf`;
            const rawBuf = await c.env.KV.get(bufKey);
            const buf: typeof streamEv[] = rawBuf ? JSON.parse(rawBuf) : [];
            buf.unshift(streamEv);
            if (buf.length > 25) buf.length = 25;
            await c.env.KV.put(bufKey, JSON.stringify(buf), { expirationTtl: 300 });
          } catch {
            // KV unavailable — non-critical
          }
        }
      }
    }
  }

  createLogger(c.get('requestId') ?? 'unknown', orgId).info('otel logs ingested', { count: eventCount });
  return c.json({ partialSuccess: {} }, 200);
});

// ── Traces Endpoint ──────────────────────────────────────────────────────────

otel.post('/v1/traces', async (c) => {
  const apiKey = extractAuth(c);
  const auth = await resolveOrg(apiKey, c.env.DB);
  if (!auth) {
    return c.json({ error: 'Invalid or missing API key' }, 401);
  }
  const orgId = auth.orgId;
  const contentLength = Number(c.req.header('content-length') ?? 0);
  if (Number.isFinite(contentLength) && contentLength > OTEL_LIMITS.MAX_BODY_BYTES) {
    return c.json({ error: `Body too large (max ${OTEL_LIMITS.MAX_BODY_BYTES} bytes)` }, 413);
  }

  let body: {
    resourceSpans?: Array<{
      resource?: OTLPResource;
      scopeSpans?: Array<{
        spans?: Array<{
          traceId?: string;
          spanId?: string;
          parentSpanId?: string;
          name?: string;
          startTimeUnixNano?: string;
          endTimeUnixNano?: string;
          status?: { code?: number };
          attributes?: OTLPResourceAttribute[];
        }>;
      }>;
    }>;
  };

  try {
    body = await c.req.json();
  } catch {
    return c.json({ error: 'Invalid OTLP JSON body' }, 400);
  }

  const stmts = [];
  let spanCount = 0;

  for (const rs of body.resourceSpans ?? []) {
    for (const ss of rs.scopeSpans ?? []) {
      for (const span of ss.spans ?? []) {
        if (spanCount >= 100) break; // max 100 spans per request

        const startMs = span.startTimeUnixNano
          ? Number(BigInt(span.startTimeUnixNano) / 1_000_000n)
          : Date.now();
        const endMs = span.endTimeUnixNano
          ? Number(BigInt(span.endTimeUnixNano) / 1_000_000n)
          : startMs;

        stmts.push(c.env.DB.prepare(`
          INSERT OR IGNORE INTO otel_traces (
            id, org_id, trace_id, span_id, parent_span_id,
            operation_name, start_time_ms, end_time_ms, duration_ms,
            status, attributes, created_at
          ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        `).bind(
          crypto.randomUUID(),
          orgId,
          span.traceId ?? null,
          span.spanId ?? null,
          span.parentSpanId ?? null,
          span.name ?? 'unknown',
          startMs,
          endMs,
          endMs - startMs,
          span.status?.code === 2 ? 'error' : 'ok',
          JSON.stringify(span.attributes ?? []),
          new Date().toISOString().replace('T', ' ').replace(/\.\d+Z$/, ''),
        ));
        spanCount++;
      }
    }
  }

  if (stmts.length > 0) {
    try {
      await c.env.DB.batch(stmts);
    } catch (err) {
      createLogger(c.get('requestId') ?? 'unknown', orgId).error('otel/traces D1 batch insert failed (non-fatal)', { err: err instanceof Error ? err : new Error(String(err)) });
    }
  }

  createLogger(c.get('requestId') ?? 'unknown', orgId).info('otel traces ingested', { count: spanCount });
  return c.json({ partialSuccess: { rejectedSpans: 0 } }, 200);
});

export { otel };
