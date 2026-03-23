/**
 * VantageAI — OpenTelemetry Collector Endpoint (Multi-Platform)
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
 *   - Header: Authorization: Bearer vnt_...  (VantageAI API key)
 *   - Or via OTEL_EXPORTER_OTLP_HEADERS env var on client side
 *
 * No latency added to the user's AI workflow — we're a telemetry SINK,
 * not in the request path.
 */

import { Hono } from 'hono';
import type { Bindings, Variables } from '../types';

const otel = new Hono<{ Bindings: Bindings; Variables: Variables }>();

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

// ── Pricing table ($ per 1M tokens) ─────────────────────────────────────────
// Used to calculate cost_usd when tools only send token counts (no cost metric)

const MODEL_PRICES: Record<string, { input: number; output: number; cache: number }> = {
  'claude-opus-4-6':      { input: 15.00, output: 75.00, cache: 1.50  },
  'claude-sonnet-4-6':    { input: 3.00,  output: 15.00, cache: 0.30  },
  'claude-haiku-4-5':     { input: 0.80,  output: 4.00,  cache: 0.08  },
  'claude-3-5-sonnet':    { input: 3.00,  output: 15.00, cache: 0.30  },
  'claude-3-haiku':       { input: 0.25,  output: 1.25,  cache: 0.03  },
  'gpt-4o':               { input: 2.50,  output: 10.00, cache: 1.25  },
  'gpt-4o-mini':          { input: 0.15,  output: 0.60,  cache: 0.075 },
  'o1':                   { input: 15.00, output: 60.00, cache: 7.50  },
  'o3-mini':              { input: 1.10,  output: 4.40,  cache: 0.55  },
  'gemini-2.0-flash':     { input: 0.10,  output: 0.40,  cache: 0.025 },
  'gemini-1.5-pro':       { input: 1.25,  output: 5.00,  cache: 0.31  },
  'gemini-1.5-flash':     { input: 0.075, output: 0.30,  cache: 0.018 },
};

function estimateCostUsd(model: string | null, inputTokens: number, outputTokens: number, cachedTokens: number): number {
  if (!model) return 0;
  // Exact match first, then fuzzy
  let price = MODEL_PRICES[model];
  if (!price) {
    const lower = model.toLowerCase();
    const key = Object.keys(MODEL_PRICES).find(k => lower.includes(k) || k.includes(lower));
    if (key) price = MODEL_PRICES[key];
  }
  if (!price) return 0;
  const uncached = Math.max(0, inputTokens - cachedTokens);
  const inputCost = (uncached / 1e6) * price.input + (cachedTokens / 1e6) * price.cache;
  const outputCost = (outputTokens / 1e6) * price.output;
  return inputCost + outputCost;
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

// Validate API key and return org_id
// Auth uses orgs.api_key_hash (owner) or org_members.api_key_hash (member)
async function resolveOrg(apiKey: string | null, db: D1Database): Promise<string | null> {
  if (!apiKey) return null;
  const encoder = new TextEncoder();
  const data = encoder.encode(apiKey);
  const hashBuffer = await crypto.subtle.digest('SHA-256', data);
  const hashArray = Array.from(new Uint8Array(hashBuffer));
  const hash = hashArray.map(b => b.toString(16).padStart(2, '0')).join('');

  // Check owner key first
  const org = await db.prepare('SELECT id FROM orgs WHERE api_key_hash = ?').bind(hash).first() as { id: string } | null;
  if (org) return org.id;

  // Check member key
  const member = await db.prepare('SELECT org_id FROM org_members WHERE api_key_hash = ?').bind(hash).first() as { org_id: string } | null;
  return member?.org_id ?? null;
}

// ── Metrics Endpoint ────────────────────────────────────────────────────────

otel.post('/v1/metrics', async (c) => {
  const startMs = Date.now();

  // Auth
  const apiKey = extractAuth(c);
  const orgId = await resolveOrg(apiKey, c.env.DB);
  if (!orgId) {
    return c.json({ error: 'Invalid or missing API key. Set OTEL_EXPORTER_OTLP_HEADERS="Authorization=Bearer vnt_YOUR_KEY"' }, 401);
  }

  // Parse OTLP JSON body
  let body: OTLPMetricsRequest;
  try {
    body = await c.req.json<OTLPMetricsRequest>();
  } catch {
    return c.json({ error: 'Invalid OTLP JSON body' }, 400);
  }

  const records: ParsedOTelRecord[] = [];

  for (const rm of body.resourceMetrics ?? []) {
    const resAttrs = rm.resource?.attributes ?? [];
    const serviceName = getAttr(resAttrs, 'service.name') ?? 'unknown';
    const { provider, tool_type } = detectProvider(serviceName);

    // Extract user identity from resource attributes
    const developerEmail = getAttr(resAttrs, 'user.email');
    const developerId = getAttr(resAttrs, 'user.account_uuid') ?? getAttr(resAttrs, 'user.account_id') ?? getAttr(resAttrs, 'user.id');
    const sessionId = getAttr(resAttrs, 'session.id');
    const terminalType = getAttr(resAttrs, 'terminal.type');
    const team = getAttr(resAttrs, 'team.id') ?? getAttr(resAttrs, 'department');
    const costCenter = getAttr(resAttrs, 'cost_center');

    for (const sm of rm.scopeMetrics ?? []) {
      for (const metric of sm.metrics ?? []) {
        const dataPoints = metric.sum?.dataPoints ?? metric.gauge?.dataPoints ?? [];
        const histPoints = metric.histogram?.dataPoints ?? [];

        for (const dp of dataPoints) {
          const metricAttrs = dp.attributes ?? [];
          const model = getAttr(metricAttrs, 'model') ?? getAttr(metricAttrs, 'gen_ai.request.model');
          const tokenType = getAttr(metricAttrs, 'type') ?? getAttr(metricAttrs, 'gen_ai.token.type');
          const value = getNumericValue(dp);
          const ts = dp.timeUnixNano ? new Date(parseInt(dp.timeUnixNano) / 1e6).toISOString() : new Date().toISOString();

          const record: ParsedOTelRecord = {
            org_id: orgId,
            provider,
            tool_type,
            source: 'otel',
            developer_email: developerEmail,
            developer_id: developerId,
            team,
            cost_center: costCenter,
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
          const histAttrs = hp.attributes ?? [];
          const model = getAttr(histAttrs, 'gen_ai.request.model') ?? getAttr(histAttrs, 'model');
          const tokenType = getAttr(histAttrs, 'gen_ai.token.type') ?? getAttr(histAttrs, 'type');
          const ts = hp.timeUnixNano ? new Date(parseInt(hp.timeUnixNano) / 1e6).toISOString() : new Date().toISOString();

          if (metric.name === 'gen_ai.client.token.usage' && hp.sum !== undefined) {
            const record: ParsedOTelRecord = {
              org_id: orgId, provider, tool_type, source: 'otel',
              developer_email: developerEmail, developer_id: developerId,
              team, cost_center: costCenter, model,
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
              team, cost_center: costCenter, model,
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
              team, cost_center: costCenter, model,
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
      r.cost_usd = estimateCostUsd(r.model, r.input_tokens, r.output_tokens, r.cached_tokens);
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
        ttft_ms, latency_ms, period_start, period_end, raw_data
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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

    // Also insert token/cost records into otel_events for /live feed
    const tokenRecords = records.filter(r => r.input_tokens > 0 || r.output_tokens > 0 || r.cost_usd > 0);
    const eventStmt = c.env.DB.prepare(`
      INSERT INTO otel_events (
        org_id, provider, session_id, developer_email, event_name,
        model, cost_usd, tokens_in, tokens_out, duration_ms, timestamp, raw_attrs
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `);
    for (const r of tokenRecords) {
      batch.push(eventStmt.bind(
        r.org_id, r.provider, r.session_id, r.developer_email,
        r.raw_metric_name, r.model, r.cost_usd,
        r.input_tokens, r.output_tokens, r.latency_ms ?? 0,
        r.timestamp, JSON.stringify({ metric: r.raw_metric_name, source: 'otel_metrics' }),
      ));
    }

    try {
      await c.env.DB.batch(batch);
    } catch (err) {
      console.error('[otel] D1 batch insert error:', err);
      return c.json({ error: 'Failed to store metrics' }, 500);
    }
  }

  const elapsed = Date.now() - startMs;
  console.log(`[otel] ingested ${records.length} metric records in ${elapsed}ms from org=${orgId}`);

  // OTLP success response
  return c.json({ partialSuccess: {} }, 200);
});

// ── Logs/Events Endpoint ────────────────────────────────────────────────────

otel.post('/v1/logs', async (c) => {
  const apiKey = extractAuth(c);
  const orgId = await resolveOrg(apiKey, c.env.DB);
  if (!orgId) {
    return c.json({ error: 'Invalid or missing API key' }, 401);
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
    const developerEmail = getAttr(resAttrs, 'user.email');
    const developerId = getAttr(resAttrs, 'user.account_uuid') ?? getAttr(resAttrs, 'user.id');
    const sessionId = getAttr(resAttrs, 'session.id');

    for (const sl of rl.scopeLogs ?? []) {
      for (const log of sl.logRecords ?? []) {
        const logAttrs = log.attributes ?? [];
        const eventName = getAttr(logAttrs, 'event.name') ?? 'unknown';
        const model = getAttr(logAttrs, 'model') ?? getAttr(logAttrs, 'gen_ai.request.model');
        const costUsd = parseFloat(getAttr(logAttrs, 'cost_usd') ?? '0');
        const inputTokens = parseInt(getAttr(logAttrs, 'input_tokens') ?? '0', 10);
        const outputTokens = parseInt(getAttr(logAttrs, 'output_tokens') ?? '0', 10);
        const cacheReadTokens = parseInt(getAttr(logAttrs, 'cache_read_tokens') ?? '0', 10);
        const durationMs = parseFloat(getAttr(logAttrs, 'duration_ms') ?? '0');
        const ts = log.timeUnixNano
          ? new Date(parseInt(log.timeUnixNano) / 1e6).toISOString()
          : new Date().toISOString();

        // Store api_request events as usage records (most valuable)
        if (eventName === 'api_request' || eventName === 'claude_code.api_request') {
          const stmt = c.env.DB.prepare(`
            INSERT INTO cross_platform_usage (
              org_id, provider, tool_type, source, developer_id, developer_email,
              team, cost_center, model, input_tokens, output_tokens, cached_tokens,
              cache_creation_tokens, cost_usd, session_id, terminal_type,
              lines_added, lines_removed, commits, pull_requests, active_time_s,
              ttft_ms, latency_ms, period_start, period_end, raw_data
            ) VALUES (?, ?, ?, 'otel', ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, 0, 0, 0, 0, 0, ?, ?, ?, ?, ?)
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
            console.error('[otel/logs] Insert error:', err);
          }
        }

        // Store all events in a separate lightweight event log for audit/debugging
        try {
          await c.env.DB.prepare(`
            INSERT INTO otel_events (
              org_id, provider, session_id, developer_email, event_name,
              model, cost_usd, tokens_in, tokens_out, duration_ms, timestamp, raw_attrs
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
          `).bind(
            orgId, provider, sessionId, developerEmail, eventName,
            model, costUsd, inputTokens, outputTokens, durationMs, ts,
            JSON.stringify(Object.fromEntries(logAttrs.map(a => [a.key, a.value.stringValue ?? a.value.intValue ?? a.value.doubleValue]))),
          ).run();
          eventCount++;
        } catch {
          // otel_events table may not exist yet — non-critical
        }
      }
    }
  }

  console.log(`[otel/logs] ingested ${eventCount} events from org=${orgId}`);
  return c.json({ partialSuccess: {} }, 200);
});

// ── Traces Endpoint (placeholder for future GenAI tracing) ──────────────────

otel.post('/v1/traces', async (c) => {
  // Accept and acknowledge — we'll implement trace storage in Phase 2
  return c.json({ partialSuccess: {} }, 200);
});

export { otel };
