#!/usr/bin/env node
/**
 * VantageAI MCP Server
 *
 * Exposes VantageAI as an MCP server so AI coding assistants
 * (Claude Desktop, Cursor, Windsurf, VS Code Copilot, Cline, etc.)
 * can track LLM costs and query analytics in real-time.
 *
 * Config:
 *   VANTAGE_API_KEY  — your vnt_... key (required)
 *   VANTAGE_ORG      — org id (auto-parsed from key if omitted)
 *   VANTAGE_API_BASE — default: https://api.vantageaiops.com
 *
 * Tools:
 *   track_llm_call        — ingest a single LLM event
 *   get_summary           — current spend, requests, top model
 *   get_kpis              — full KPI table
 *   get_model_breakdown   — cost + usage per model
 *   get_team_breakdown    — cost + usage per team
 *   check_budget          — budget status + % used
 *   get_traces            — recent agent traces
 *   get_cost_gate         — CI/CD budget gate check
 */

import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
  ListResourcesRequestSchema,
  ReadResourceRequestSchema,
} from '@modelcontextprotocol/sdk/types.js';

// ── Config ────────────────────────────────────────────────────────────────────

const API_KEY  = process.env.VANTAGE_API_KEY  ?? '';
const API_BASE = (process.env.VANTAGE_API_BASE ?? 'https://api.vantageaiops.com').replace(/\/+$/, '');
const ORG      = process.env.VANTAGE_ORG      ?? parseOrgFromKey(API_KEY);

function parseOrgFromKey(key: string): string {
  const parts = key.split('_');
  return parts.length >= 3 ? parts[1] : 'default';
}

// ── API client ────────────────────────────────────────────────────────────────

async function api(path: string, opts: RequestInit = {}): Promise<unknown> {
  if (!API_KEY) throw new Error('VANTAGE_API_KEY is not set. Add it to your MCP config.');

  const res = await fetch(`${API_BASE}${path}`, {
    ...opts,
    headers: {
      'Authorization': `Bearer ${API_KEY}`,
      'X-Vantage-Org': ORG,
      'Content-Type': 'application/json',
      ...(opts.headers ?? {}),
    },
  });

  const body = await res.json();
  if (!res.ok) throw new Error((body as { error?: string }).error ?? `HTTP ${res.status}`);
  return body;
}

// ── MCP Server ────────────────────────────────────────────────────────────────

const server = new Server(
  { name: 'vantage-mcp', version: '1.0.0' },
  { capabilities: { tools: {}, resources: {} } },
);

// ── Tool definitions ──────────────────────────────────────────────────────────

server.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: [
    {
      name: 'track_llm_call',
      description: 'Track an LLM API call — logs cost, tokens, latency, model, and team to VantageAI. Call this after every LLM completion.',
      inputSchema: {
        type: 'object',
        properties: {
          model:            { type: 'string', description: 'Model name, e.g. gpt-4o, claude-3-5-sonnet' },
          provider:         { type: 'string', description: 'Provider: openai | anthropic | google | mistral | cohere | other' },
          prompt_tokens:    { type: 'number', description: 'Number of input/prompt tokens' },
          completion_tokens:{ type: 'number', description: 'Number of output/completion tokens' },
          total_cost_usd:   { type: 'number', description: 'Total cost in USD (e.g. 0.0025)' },
          latency_ms:       { type: 'number', description: 'End-to-end latency in milliseconds' },
          team:             { type: 'string', description: 'Team or feature name for grouping (e.g. "backend", "search")' },
          environment:      { type: 'string', description: 'Environment: production | staging | development' },
          trace_id:         { type: 'string', description: 'Trace ID for grouping multi-step agent calls' },
          span_depth:       { type: 'number', description: 'Depth in agent call tree (0 = root)' },
          tags:             { type: 'object', description: 'Arbitrary key-value tags for filtering' },
        },
        required: ['model', 'provider', 'prompt_tokens', 'completion_tokens', 'total_cost_usd'],
      },
    },
    {
      name: 'get_summary',
      description: 'Get a high-level cost summary: total spend this month, number of requests, avg latency, top model, and budget status.',
      inputSchema: { type: 'object', properties: {} },
    },
    {
      name: 'get_kpis',
      description: 'Get detailed KPI metrics: MTD cost, daily cost, P50/P95 latency, efficiency score, error rate, active models and teams.',
      inputSchema: { type: 'object', properties: {} },
    },
    {
      name: 'get_model_breakdown',
      description: 'Get cost and usage breakdown per LLM model — useful for identifying expensive models or optimization opportunities.',
      inputSchema: {
        type: 'object',
        properties: {
          days: { type: 'number', description: 'Look-back window in days (default: 30)' },
        },
      },
    },
    {
      name: 'get_team_breakdown',
      description: 'Get cost and usage breakdown per team — useful for chargeback reporting or finding which feature drives the most spend.',
      inputSchema: {
        type: 'object',
        properties: {
          days: { type: 'number', description: 'Look-back window in days (default: 30)' },
        },
      },
    },
    {
      name: 'check_budget',
      description: 'Check current budget status — returns % of monthly budget used, remaining budget, and whether the org is over limit.',
      inputSchema: { type: 'object', properties: {} },
    },
    {
      name: 'get_traces',
      description: 'Get recent multi-step agent traces — shows the full call tree, per-span cost, and total trace cost.',
      inputSchema: {
        type: 'object',
        properties: {
          limit: { type: 'number', description: 'Number of traces to return (default: 10, max: 50)' },
        },
      },
    },
    {
      name: 'get_cost_gate',
      description: 'CI/CD cost gate — returns whether spend in the current period is within the configured budget. Use in CI pipelines before merging.',
      inputSchema: {
        type: 'object',
        properties: {
          period: { type: 'string', description: 'Period to check: today | week | month (default: today)' },
        },
      },
    },
  ],
}));

// ── Tool handlers ─────────────────────────────────────────────────────────────

server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args = {} } = request.params;

  try {
    switch (name) {

      case 'track_llm_call': {
        const event = {
          event_id: `mcp-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
          ...args,
          org_id: ORG,
        };
        await api('/v1/events', { method: 'POST', body: JSON.stringify(event) });
        return {
          content: [{
            type: 'text',
            text: `✅ Tracked: ${args.model} | ${args.prompt_tokens}→${args.completion_tokens} tokens | $${Number(args.total_cost_usd).toFixed(4)} | ${args.latency_ms ? `${args.latency_ms}ms` : 'no latency recorded'}`,
          }],
        };
      }

      case 'get_summary': {
        const data = await api('/v1/analytics/summary') as Record<string, unknown>;
        const lines = [
          `📊 **VantageAI Summary** (org: ${ORG})`,
          ``,
          `| Metric | Value |`,
          `|--------|-------|`,
          `| MTD Spend | $${Number(data.mtd_cost ?? 0).toFixed(2)} |`,
          `| Today | $${Number(data.today_cost ?? 0).toFixed(2)} |`,
          `| Requests | ${Number(data.total_requests ?? 0).toLocaleString()} |`,
          `| Avg Latency | ${Number(data.avg_latency_ms ?? 0).toFixed(0)}ms |`,
          `| Top Model | ${data.top_model ?? 'N/A'} |`,
          `| Budget Used | ${data.budget_pct != null ? `${Number(data.budget_pct).toFixed(1)}%` : 'No budget set'} |`,
          ``,
          `🔗 [View dashboard](https://vantageaiops.com/app.html)`,
        ];
        return { content: [{ type: 'text', text: lines.join('\n') }] };
      }

      case 'get_kpis': {
        const data = await api('/v1/analytics/kpis') as Record<string, unknown>[];
        const rows = data.map((r) =>
          `| ${r.label} | ${r.value} | ${r.delta != null ? (Number(r.delta) >= 0 ? `+${r.delta}` : r.delta) : '—'} |`
        );
        const text = [
          `📈 **KPIs** (org: ${ORG})`,
          ``,
          `| Metric | Value | Δ |`,
          `|--------|-------|---|`,
          ...rows,
        ].join('\n');
        return { content: [{ type: 'text', text }] };
      }

      case 'get_model_breakdown': {
        const days = args?.days ?? 30;
        const data = await api(`/v1/analytics/models?days=${days}`) as Record<string, unknown>[];
        const rows = data.map((r) =>
          `| ${r.model} | $${Number(r.total_cost).toFixed(4)} | ${Number(r.requests).toLocaleString()} | ${Number(r.avg_latency_ms ?? 0).toFixed(0)}ms |`
        );
        const text = [
          `🤖 **Model Breakdown** (last ${days} days)`,
          ``,
          `| Model | Cost | Requests | Avg Latency |`,
          `|-------|------|----------|-------------|`,
          ...rows,
        ].join('\n');
        return { content: [{ type: 'text', text }] };
      }

      case 'get_team_breakdown': {
        const days = args?.days ?? 30;
        const data = await api(`/v1/analytics/teams?days=${days}`) as Record<string, unknown>[];
        const rows = data.map((r) =>
          `| ${r.team || '(untagged)'} | $${Number(r.total_cost).toFixed(4)} | ${Number(r.requests).toLocaleString()} |`
        );
        const text = [
          `👥 **Team Breakdown** (last ${days} days)`,
          ``,
          `| Team | Cost | Requests |`,
          `|------|------|----------|`,
          ...rows,
        ].join('\n');
        return { content: [{ type: 'text', text }] };
      }

      case 'check_budget': {
        const data = await api('/v1/analytics/summary') as Record<string, unknown>;
        const pct = Number(data.budget_pct ?? 0);
        const mtd = Number(data.mtd_cost ?? 0);
        const budget = Number(data.budget_usd ?? 0);
        const status = budget === 0 ? '⚪ No budget set'
          : pct >= 100 ? '🚨 OVER BUDGET'
          : pct >= 80  ? '⚠️ Approaching limit'
          : '✅ Within budget';
        const text = [
          `💰 **Budget Status** (org: ${ORG})`,
          ``,
          `${status}`,
          ``,
          `| | |`,
          `|-|-|`,
          `| MTD Spend | $${mtd.toFixed(2)} |`,
          `| Budget | ${budget ? `$${budget.toFixed(2)}` : 'Not set'} |`,
          `| Used | ${budget ? `${pct.toFixed(1)}%` : '—'} |`,
          `| Remaining | ${budget ? `$${Math.max(0, budget - mtd).toFixed(2)}` : '—'} |`,
        ].join('\n');
        return { content: [{ type: 'text', text }] };
      }

      case 'get_traces': {
        const limit = Math.min(Number(args?.limit ?? 10), 50);
        const data = await api(`/v1/analytics/traces?limit=${limit}`) as Record<string, unknown>[];
        if (!data.length) {
          return { content: [{ type: 'text', text: 'No traces found. Make sure to pass `trace_id` when calling `track_llm_call`.' }] };
        }
        const rows = data.map((t) =>
          `| ${String(t.trace_id).slice(0, 16)}… | ${t.span_count} spans | $${Number(t.total_cost).toFixed(4)} | ${t.root_model ?? 'N/A'} |`
        );
        const text = [
          `🔍 **Recent Agent Traces** (last ${limit})`,
          ``,
          `| Trace ID | Spans | Total Cost | Root Model |`,
          `|----------|-------|------------|------------|`,
          ...rows,
        ].join('\n');
        return { content: [{ type: 'text', text }] };
      }

      case 'get_cost_gate': {
        const period = args?.period ?? 'today';
        const data = await api(`/v1/analytics/cost?period=${period}`) as Record<string, unknown>;
        const passed = data.within_budget as boolean;
        const text = [
          `🚦 **CI Cost Gate** — ${passed ? '✅ PASSED' : '❌ FAILED'}`,
          ``,
          `| | |`,
          `|-|-|`,
          `| Period | ${period} |`,
          `| Spend | $${Number(data.cost ?? 0).toFixed(4)} |`,
          `| Budget | $${Number(data.budget ?? 0).toFixed(2)} |`,
          `| Status | ${passed ? 'Within budget' : '**Over budget — block merge**'} |`,
        ].join('\n');
        return { content: [{ type: 'text', text }] };
      }

      default:
        throw new Error(`Unknown tool: ${name}`);
    }
  } catch (err) {
    return {
      content: [{ type: 'text', text: `❌ Error: ${(err as Error).message}` }],
      isError: true,
    };
  }
});

// ── Resources ─────────────────────────────────────────────────────────────────

server.setRequestHandler(ListResourcesRequestSchema, async () => ({
  resources: [
    {
      uri: 'vantage://dashboard',
      name: 'VantageAI Dashboard',
      description: 'Live cost analytics dashboard',
      mimeType: 'text/plain',
    },
    {
      uri: 'vantage://docs',
      name: 'VantageAI Docs',
      description: 'SDK integration guides and API reference',
      mimeType: 'text/plain',
    },
    {
      uri: 'vantage://config',
      name: 'Current MCP Config',
      description: 'Active API key, org, and base URL',
      mimeType: 'text/plain',
    },
  ],
}));

server.setRequestHandler(ReadResourceRequestSchema, async (request) => {
  const { uri } = request.params;

  switch (uri) {
    case 'vantage://dashboard':
      return { contents: [{ uri, mimeType: 'text/plain', text: 'Dashboard: https://vantageaiops.com/app.html' }] };

    case 'vantage://docs':
      return { contents: [{ uri, mimeType: 'text/plain', text: 'Docs: https://vantageaiops.com/docs.html' }] };

    case 'vantage://config':
      return {
        contents: [{
          uri,
          mimeType: 'text/plain',
          text: [
            `API Base : ${API_BASE}`,
            `Org      : ${ORG}`,
            `API Key  : ${API_KEY ? `${API_KEY.slice(0, 8)}${'*'.repeat(Math.max(0, API_KEY.length - 8))}` : '(not set)'}`,
          ].join('\n'),
        }],
      };

    default:
      throw new Error(`Unknown resource: ${uri}`);
  }
});

// ── Start ─────────────────────────────────────────────────────────────────────

async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
  // MCP servers must not write to stdout — use stderr for logs
  process.stderr.write('[vantage-mcp] Server started\n');
}

main().catch((err) => {
  process.stderr.write(`[vantage-mcp] Fatal: ${err.message}\n`);
  process.exit(1);
});
