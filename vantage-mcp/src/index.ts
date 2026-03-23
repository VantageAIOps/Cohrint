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
 *
 * Optimizer Tools:
 *   optimize_prompt       — compress a prompt to reduce token usage
 *   analyze_tokens        — count tokens and estimate cost for text
 *   estimate_costs        — compare costs across models
 *   compress_context      — compress conversation context within a token budget
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

// ── Helpers ───────────────────────────────────────────────────────────────────

/** Sanitise a number: NaN, Infinity, undefined → fallback. */
function safeNum(v: unknown, fallback = 0): number {
  const n = Number(v);
  return Number.isFinite(n) ? n : fallback;
}

/** Structured error log to stderr (machine-parseable, never leaks full key). */
function errorLog(context: string, err: unknown): void {
  const msg = err instanceof Error ? err.message : String(err);
  const ts = new Date().toISOString();
  const safe = msg.replace(new RegExp(API_KEY.slice(8), 'g'), '****');
  process.stderr.write(`[vantage-mcp] ${ts} ERROR ${context}: ${safe}\n`);
}

// ── API client ────────────────────────────────────────────────────────────────

async function api(path: string, opts: RequestInit = {}): Promise<unknown> {
  if (!API_KEY) throw new Error('VANTAGE_API_KEY is not set. Add it to your MCP config. Get a key at https://vantageaiops.com/signup.html');

  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      ...opts,
      signal: AbortSignal.timeout(15_000),
      headers: {
        'Authorization': `Bearer ${API_KEY}`,
        'X-Vantage-Org': ORG,
        'Content-Type': 'application/json',
        ...(opts.headers ?? {}),
      },
    });
  } catch (fetchErr) {
    const msg = fetchErr instanceof Error ? fetchErr.message : String(fetchErr);
    errorLog(`api ${path}`, fetchErr);
    if (msg.includes('abort') || msg.includes('timeout')) {
      throw new Error(`Request to VantageAI API timed out (${path}). Check your network connection.`);
    }
    throw new Error(`Cannot reach VantageAI API (${path}): ${msg.split('\n')[0]}`);
  }

  let body: unknown;
  try {
    body = await res.json();
  } catch {
    throw new Error(`VantageAI API returned invalid JSON (HTTP ${res.status} on ${path}).`);
  }
  if (!res.ok) throw new Error((body as { error?: string }).error ?? `HTTP ${res.status}`);
  return body;
}

// ── Token & Prompt Optimizer (works offline — no API key needed) ─────────────

// Per-1K-token pricing: { input, output } in USD
const MODEL_RATES: Record<string, { input: number; output: number; provider: string; tier: string }> = {
  // OpenAI
  'gpt-4o':           { input: 0.0025,  output: 0.01,    provider: 'openai',    tier: 'frontier' },
  'gpt-4o-mini':      { input: 0.00015, output: 0.0006,  provider: 'openai',    tier: 'mid' },
  'gpt-4-turbo':      { input: 0.01,    output: 0.03,    provider: 'openai',    tier: 'frontier' },
  'gpt-4':            { input: 0.03,    output: 0.06,    provider: 'openai',    tier: 'frontier' },
  'gpt-3.5-turbo':    { input: 0.0005,  output: 0.0015,  provider: 'openai',    tier: 'budget' },
  'o1':               { input: 0.015,   output: 0.06,    provider: 'openai',    tier: 'reasoning' },
  'o1-mini':          { input: 0.003,   output: 0.012,   provider: 'openai',    tier: 'reasoning' },
  'o3-mini':          { input: 0.0011,  output: 0.0044,  provider: 'openai',    tier: 'reasoning' },
  // Anthropic
  'claude-sonnet-4':  { input: 0.003,   output: 0.015,   provider: 'anthropic', tier: 'frontier' },
  'claude-3.5-sonnet':{ input: 0.003,   output: 0.015,   provider: 'anthropic', tier: 'frontier' },
  'claude-3-opus':    { input: 0.015,   output: 0.075,   provider: 'anthropic', tier: 'frontier' },
  'claude-3-haiku':   { input: 0.00025, output: 0.00125, provider: 'anthropic', tier: 'budget' },
  'claude-haiku-3.5': { input: 0.0008,  output: 0.004,   provider: 'anthropic', tier: 'mid' },
  // Google
  'gemini-2.0-flash': { input: 0.0001,  output: 0.0004,  provider: 'google',    tier: 'budget' },
  'gemini-1.5-pro':   { input: 0.00125, output: 0.005,   provider: 'google',    tier: 'frontier' },
  'gemini-1.5-flash': { input: 0.000075,output: 0.0003,  provider: 'google',    tier: 'budget' },
  // Meta / DeepSeek / Mistral
  'llama-3.3-70b':    { input: 0.00059, output: 0.00079, provider: 'meta',      tier: 'mid' },
  'deepseek-v3':      { input: 0.00027, output: 0.0011,  provider: 'deepseek',  tier: 'budget' },
  'deepseek-r1':      { input: 0.00055, output: 0.00219, provider: 'deepseek',  tier: 'reasoning' },
  'mistral-large':    { input: 0.002,   output: 0.006,   provider: 'mistral',   tier: 'frontier' },
  'mistral-small':    { input: 0.0002,  output: 0.0006,  provider: 'mistral',   tier: 'budget' },
};

// Filler phrases that add tokens but no meaning
const FILLER_PHRASES = [
  "i'd like you to", "i want you to", "i need you to",
  "would you mind", "could you please", "can you please",
  "please note that", "it is important to note that",
  "as an ai language model", "as a helpful assistant",
  "in order to", "for the purpose of", "with regard to",
  "in the context of", "it should be noted that",
  "please", "kindly", "basically", "essentially",
  "actually", "literally", "obviously", "clearly",
];

const FILLER_WORDS = /\b(the|and|or|but|in|on|at|to|for|of|with|by|an|a|is|are|was|were|be|been|being|have|has|had|do|does|did|will|would|could|should|may|might|must|can|shall|just|very|really|quite|rather|somewhat|pretty|fairly|bit)\b/gi;

/** Count tokens using word-level heuristic (matches GPT tokenizer ±10%). */
function countTokens(text: string): number {
  if (!text) return 0;
  // Count words + punctuation + special chars as separate tokens
  const words = text.split(/\s+/).filter(w => w.length > 0);
  // Longer words tend to be split into multiple tokens
  let count = 0;
  for (const w of words) {
    if (w.length <= 4) count += 1;
    else if (w.length <= 8) count += 1.3;
    else if (w.length <= 12) count += 1.8;
    else count += Math.ceil(w.length / 4);
  }
  return Math.ceil(count);
}

/** Smart prompt compression: remove filler, deduplicate, trim redundancy. */
function compressPrompt(prompt: string): string {
  let text = prompt;
  // Remove filler phrases (case-insensitive)
  for (const phrase of FILLER_PHRASES) {
    const escaped = phrase.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    text = text.replace(new RegExp(`\\b${escaped}\\b`, 'gi'), '');
  }
  // Remove duplicate consecutive sentences
  const sentences = text.split(/(?<=[.!?])\s+/);
  const unique: string[] = [];
  const seen = new Set<string>();
  for (const s of sentences) {
    const norm = s.toLowerCase().trim();
    if (norm && !seen.has(norm)) { seen.add(norm); unique.push(s); }
  }
  text = unique.join(' ');
  // Collapse whitespace
  return text.replace(/\s+/g, ' ').trim();
}

/** Calculate cost for a model. */
function calcCost(model: string, inputTokens: number, outputTokens: number) {
  const rates = MODEL_RATES[model] ?? MODEL_RATES['gpt-3.5-turbo'];
  const inputCost = (inputTokens / 1000) * rates.input;
  const outputCost = (outputTokens / 1000) * rates.output;
  return { inputCost, outputCost, totalCost: inputCost + outputCost };
}

/** Find the cheapest model for given token counts. */
function findCheapest(inputTokens: number, outputTokens: number) {
  let best = { model: '', totalCost: Infinity, provider: '' };
  for (const [model, rates] of Object.entries(MODEL_RATES)) {
    const total = (inputTokens / 1000) * rates.input + (outputTokens / 1000) * rates.output;
    if (total < best.totalCost) best = { model, totalCost: total, provider: rates.provider };
  }
  return best;
}

/** Generate optimization tips for a prompt. */
function getOptimizationTips(prompt: string): string[] {
  const tips: string[] = [];
  const tokens = countTokens(prompt);
  const compressed = compressPrompt(prompt);
  const compressedTokens = countTokens(compressed);
  const saved = tokens - compressedTokens;

  if (saved > 10) tips.push(`Remove filler words/phrases to save ~${saved} tokens (${Math.round(saved/tokens*100)}%)`);
  if (prompt.length > 2000) tips.push('Consider breaking into smaller, focused prompts instead of one large one');
  if (/```[\s\S]{500,}```/.test(prompt)) tips.push('Large code blocks detected — consider referencing files instead of inlining');
  if ((prompt.match(/\n/g) || []).length > 30) tips.push('Many newlines — compact formatting can save tokens');
  if (/(.{50,})\1/.test(prompt)) tips.push('Repeated content detected — deduplicate to save tokens');
  if (tokens > 4000) tips.push('Prompt > 4000 tokens — consider using a cheaper model for this task (gemini-2.0-flash, deepseek-v3)');
  if (tokens < 100) tips.push('Short prompt — already efficient');
  return tips;
}

// ── MCP Server ────────────────────────────────────────────────────────────────

const server = new Server(
  { name: 'vantage-mcp', version: '1.1.0' },
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

    // ── Optimizer tools (work offline — no API key needed) ─────────────────────
    {
      name: 'optimize_prompt',
      description: 'Optimize a prompt to reduce token usage and cost. Removes filler words/phrases, deduplicates sentences, and provides specific optimization tips. Works offline — no API key needed.',
      inputSchema: {
        type: 'object',
        properties: {
          prompt: { type: 'string', description: 'The prompt text to optimize' },
          model: { type: 'string', description: 'Target model for cost estimate (default: gpt-4o)' },
        },
        required: ['prompt'],
      },
    },
    {
      name: 'analyze_tokens',
      description: 'Count tokens, estimate cost, find the cheapest model, and get optimization tips for any text. Works offline — no API key needed.',
      inputSchema: {
        type: 'object',
        properties: {
          text: { type: 'string', description: 'The text to analyze' },
          model: { type: 'string', description: 'Model to price against (default: gpt-4o)' },
          output_tokens: { type: 'number', description: 'Expected output tokens for cost calc (default: same as input)' },
        },
        required: ['text'],
      },
    },
    {
      name: 'estimate_costs',
      description: 'Compare costs for a prompt across all 22 supported models (OpenAI, Anthropic, Google, Meta, DeepSeek, Mistral). Sorted cheapest first with savings vs most expensive. Works offline — no API key needed.',
      inputSchema: {
        type: 'object',
        properties: {
          prompt: { type: 'string', description: 'The prompt to estimate costs for' },
          completion_tokens: { type: 'number', description: 'Expected output tokens (default: same as input)' },
        },
        required: ['prompt'],
      },
    },
    {
      name: 'compress_context',
      description: 'Compress a conversation to fit within a token budget. Keeps recent messages, summarizes older ones. Useful before sending to LLM to save costs. Works offline.',
      inputSchema: {
        type: 'object',
        properties: {
          messages: {
            type: 'array',
            description: 'Array of {role, content} messages',
            items: {
              type: 'object',
              properties: {
                role: { type: 'string', enum: ['user', 'assistant', 'system'] },
                content: { type: 'string' },
              },
              required: ['role', 'content'],
            },
          },
          max_tokens: { type: 'number', description: 'Maximum token budget (default: 4000)' },
        },
        required: ['messages'],
      },
    },
    {
      name: 'find_cheapest_model',
      description: 'Find the cheapest model for your use case. Specify input/output tokens and optional tier (frontier/mid/budget/reasoning). Works offline.',
      inputSchema: {
        type: 'object',
        properties: {
          input_tokens: { type: 'number', description: 'Number of input tokens' },
          output_tokens: { type: 'number', description: 'Number of output tokens' },
          tier: { type: 'string', description: 'Filter by tier: frontier | mid | budget | reasoning (optional)' },
          provider: { type: 'string', description: 'Filter by provider: openai | anthropic | google | meta | deepseek | mistral (optional)' },
        },
        required: ['input_tokens', 'output_tokens'],
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
        const model = String(args.model ?? '').trim();
        const provider = String(args.provider ?? '').trim();
        if (!model) throw new Error('model is required (e.g. "gpt-4o", "claude-sonnet-4")');
        if (!provider) throw new Error('provider is required (e.g. "openai", "anthropic")');

        const promptTokens = safeNum(args.prompt_tokens, 0);
        const completionTokens = safeNum(args.completion_tokens, 0);
        const totalCost = safeNum(args.total_cost_usd, 0);
        const latency = safeNum(args.latency_ms);
        const spanDepth = safeNum(args.span_depth, 0);

        const event: Record<string, unknown> = {
          event_id: `mcp-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
          model,
          provider,
          prompt_tokens: promptTokens,
          completion_tokens: completionTokens,
          total_cost_usd: totalCost,
          ...(latency > 0 ? { latency_ms: latency } : {}),
          ...(args.team ? { team: String(args.team).slice(0, 100) } : {}),
          ...(args.environment ? { environment: String(args.environment).slice(0, 50) } : {}),
          ...(args.trace_id ? { trace_id: String(args.trace_id).slice(0, 256) } : {}),
          ...(spanDepth > 0 ? { span_depth: spanDepth } : {}),
          ...(args.tags && typeof args.tags === 'object' ? { tags: args.tags } : {}),
        };
        await api('/v1/events', { method: 'POST', body: JSON.stringify(event) });
        return {
          content: [{
            type: 'text',
            text: `✅ Tracked: ${model} | ${promptTokens}→${completionTokens} tokens | $${totalCost.toFixed(4)} | ${latency > 0 ? `${latency}ms` : 'no latency recorded'}`,
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
          `| MTD Spend | $${Number(data.mtd_cost_usd ?? 0).toFixed(4)} |`,
          `| Today Spend | $${Number(data.today_cost_usd ?? 0).toFixed(4)} |`,
          `| Today Requests | ${Number(data.today_requests ?? 0).toLocaleString()} |`,
          `| Today Tokens | ${Number(data.today_tokens ?? 0).toLocaleString()} |`,
          `| Session Spend (30 min) | $${Number(data.session_cost_usd ?? 0).toFixed(4)} |`,
          `| Budget Used | ${Number(data.budget_pct ?? 0) > 0 ? `${Number(data.budget_pct).toFixed(1)}%` : 'No budget set'} |`,
          `| Plan | ${data.plan ?? 'free'} |`,
          ``,
          `🔗 [View dashboard](https://vantageaiops.com/app.html)`,
        ];
        return { content: [{ type: 'text', text: lines.join('\n') }] };
      }

      case 'get_kpis': {
        const data = await api('/v1/analytics/kpis') as Record<string, unknown>;
        const rows = [
          `| Total Cost (MTD) | $${Number(data.total_cost_usd ?? 0).toFixed(4)} |`,
          `| Total Tokens | ${Number(data.total_tokens ?? 0).toLocaleString()} |`,
          `| Total Requests | ${Number(data.total_requests ?? 0).toLocaleString()} |`,
          `| Avg Latency | ${Number(data.avg_latency_ms ?? 0).toFixed(0)}ms |`,
          `| Efficiency Score | ${data.efficiency_score ?? 'N/A'} |`,
          `| Streaming Requests | ${Number(data.streaming_requests ?? 0).toLocaleString()} |`,
        ];
        const text = [
          `📈 **KPIs** (org: ${ORG})`,
          ``,
          `| Metric | Value |`,
          `|--------|-------|`,
          ...rows,
        ].join('\n');
        return { content: [{ type: 'text', text }] };
      }

      case 'get_model_breakdown': {
        const days = Math.min(Math.max(1, safeNum(args?.days, 30)), 365);
        const resp = await api(`/v1/analytics/models?period=${days}`) as { models: Record<string, unknown>[] };
        const models = resp.models ?? [];
        const rows = models.map((r) =>
          `| ${r.model} | ${r.provider} | $${Number(r.cost_usd).toFixed(4)} | ${Number(r.requests).toLocaleString()} | ${Number(r.avg_latency_ms ?? 0).toFixed(0)}ms |`
        );
        const text = [
          `🤖 **Model Breakdown** (last ${days} days)`,
          ``,
          `| Model | Provider | Cost | Requests | Avg Latency |`,
          `|-------|----------|------|----------|-------------|`,
          ...(rows.length ? rows : ['| No data yet | | | | |']),
        ].join('\n');
        return { content: [{ type: 'text', text }] };
      }

      case 'get_team_breakdown': {
        const days = Math.min(Math.max(1, safeNum(args?.days, 30)), 365);
        const resp = await api(`/v1/analytics/teams?period=${days}`) as { teams: Record<string, unknown>[] };
        const teams = resp.teams ?? [];
        const rows = teams.map((r) =>
          `| ${r.team || '(untagged)'} | $${Number(r.cost_usd).toFixed(4)} | ${Number(r.requests).toLocaleString()} |`
        );
        const text = [
          `👥 **Team Breakdown** (last ${days} days)`,
          ``,
          `| Team | Cost | Requests |`,
          `|------|------|----------|`,
          ...(rows.length ? rows : ['| No data yet | | |']),
        ].join('\n');
        return { content: [{ type: 'text', text }] };
      }

      case 'check_budget': {
        const data = await api('/v1/analytics/summary') as Record<string, unknown>;
        const pct = Number(data.budget_pct ?? 0);
        const mtd = Number(data.mtd_cost_usd ?? 0);
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
        const limit = Math.min(Math.max(1, safeNum(args?.limit, 10)), 50);
        const resp = await api(`/v1/analytics/traces?period=7`) as { traces: Record<string, unknown>[] };
        const traces = (resp.traces ?? []).slice(0, limit);
        if (!traces.length) {
          return { content: [{ type: 'text', text: 'No traces found. Make sure to pass `trace_id` when calling `track_llm_call`.' }] };
        }
        const rows = traces.map((t) =>
          `| ${String(t.trace_id).slice(0, 16)}… | ${t.spans} spans | $${Number(t.cost ?? 0).toFixed(4)} | ${t.name ?? 'N/A'} |`
        );
        const text = [
          `🔍 **Recent Agent Traces** (last ${traces.length})`,
          ``,
          `| Trace ID | Spans | Total Cost | Agent |`,
          `|----------|-------|------------|-------|`,
          ...rows,
        ].join('\n');
        return { content: [{ type: 'text', text }] };
      }

      case 'get_cost_gate': {
        const periodArg = String(args?.period ?? 'today');
        const days = periodArg === 'today' ? 1 : periodArg === 'week' ? 7 : 30;
        const [costData, summary] = await Promise.all([
          api(`/v1/analytics/cost?period=${days}`) as Promise<Record<string, number>>,
          api('/v1/analytics/summary') as Promise<Record<string, number>>,
        ]);
        const spend = periodArg === 'today'
          ? Number((costData as Record<string, number>).today_cost_usd ?? 0)
          : Number((costData as Record<string, number>).total_cost_usd ?? 0);
        const budget = Number((summary as Record<string, number>).budget_usd ?? 0);
        const passed = budget === 0 || spend <= budget;
        const text = [
          `🚦 **CI Cost Gate** — ${passed ? '✅ PASSED' : '❌ FAILED'}`,
          ``,
          `| | |`,
          `|-|-|`,
          `| Period | ${periodArg} |`,
          `| Spend | $${spend.toFixed(4)} |`,
          `| Budget | ${budget ? `$${budget.toFixed(2)}` : 'Not set'} |`,
          `| Status | ${passed ? 'Within budget' : '**Over budget — block merge**'} |`,
        ].join('\n');
        return { content: [{ type: 'text', text }] };
      }

      // ── Optimizer tool handlers (work offline — no API key needed) ────────

      case 'optimize_prompt': {
        const prompt = typeof args.prompt === 'string' ? args.prompt : '';
        if (!prompt.trim()) throw new Error('prompt is required — pass a non-empty string to optimize');
        const model = (args.model as string) || 'gpt-4o';
        const originalTokens = countTokens(prompt);
        const compressed = compressPrompt(prompt);
        const compressedTokens = countTokens(compressed);
        const saved = originalTokens - compressedTokens;
        const tips = getOptimizationTips(prompt);
        const costBefore = calcCost(model, originalTokens, originalTokens);
        const costAfter = calcCost(model, compressedTokens, compressedTokens);
        const cheapest = findCheapest(compressedTokens, compressedTokens);

        const lines = [
          `🔧 **Prompt Optimizer** (${model})`,
          ``,
          `| Metric | Before | After | Saved |`,
          `|--------|--------|-------|-------|`,
          `| Tokens | ${originalTokens} | ${compressedTokens} | ${saved} (${originalTokens > 0 ? Math.round(saved/originalTokens*100) : 0}%) |`,
          `| Est. cost | $${costBefore.totalCost.toFixed(6)} | $${costAfter.totalCost.toFixed(6)} | $${(costBefore.totalCost - costAfter.totalCost).toFixed(6)} |`,
          ``,
          ...(saved > 0 ? [`**Optimized prompt:**`, '```', compressed, '```', ''] : ['✅ Prompt is already efficient — no filler detected.', '']),
          ...(tips.length > 0 ? ['**Tips:**', ...tips.map(t => `- ${t}`), ''] : []),
          `💡 Cheapest model for this prompt: **${cheapest.model}** (${cheapest.provider}) at $${cheapest.totalCost.toFixed(6)}`,
        ];
        return { content: [{ type: 'text', text: lines.join('\n') }] };
      }

      case 'analyze_tokens': {
        const text = typeof args.text === 'string' ? args.text : '';
        if (!text.trim()) throw new Error('text is required — pass a non-empty string to analyze');
        const model = (typeof args.model === 'string' && args.model) || 'gpt-4o';
        const inputTokens = countTokens(text);
        const outputTokens = safeNum(args.output_tokens, inputTokens);
        const cost = calcCost(model, inputTokens, outputTokens);
        const cheapest = findCheapest(inputTokens, outputTokens);
        const tips = getOptimizationTips(text);

        const lines = [
          `📊 **Token Analysis**`,
          ``,
          `| Metric | Value |`,
          `|--------|-------|`,
          `| Characters | ${text.length.toLocaleString()} |`,
          `| Input tokens | ${inputTokens.toLocaleString()} |`,
          `| Output tokens (est.) | ${outputTokens.toLocaleString()} |`,
          `| Model | ${model} |`,
          `| Input cost | $${cost.inputCost.toFixed(6)} |`,
          `| Output cost | $${cost.outputCost.toFixed(6)} |`,
          `| **Total cost** | **$${cost.totalCost.toFixed(6)}** |`,
          ``,
          `💡 Cheapest alternative: **${cheapest.model}** at $${cheapest.totalCost.toFixed(6)} (save $${(cost.totalCost - cheapest.totalCost).toFixed(6)})`,
          ...(tips.length > 0 ? ['', '**Optimization tips:**', ...tips.map(t => `- ${t}`)] : []),
        ];
        return { content: [{ type: 'text', text: lines.join('\n') }] };
      }

      case 'estimate_costs': {
        const estPrompt = typeof args.prompt === 'string' ? args.prompt : '';
        if (!estPrompt.trim()) throw new Error('prompt is required — pass a non-empty string to estimate costs');
        const inputTokens = countTokens(estPrompt);
        const outputTokens = safeNum(args.completion_tokens, inputTokens);

        const comparisons = Object.entries(MODEL_RATES)
          .map(([model, rates]) => {
            const inCost = (inputTokens / 1000) * rates.input;
            const outCost = (outputTokens / 1000) * rates.output;
            return { model, provider: rates.provider, tier: rates.tier, inputCost: inCost, outputCost: outCost, totalCost: inCost + outCost };
          })
          .sort((a, b) => a.totalCost - b.totalCost);

        const cheapest = comparisons[0];
        const mostExpensive = comparisons[comparisons.length - 1];
        const maxSaving = mostExpensive.totalCost - cheapest.totalCost;

        const rows = comparisons.map((c, i) =>
          `| ${i === 0 ? '⭐' : ''} ${c.model} | ${c.provider} | ${c.tier} | $${c.totalCost.toFixed(6)} | ${i === 0 ? '—' : `+$${(c.totalCost - cheapest.totalCost).toFixed(6)}`} |`
        );

        const lines = [
          `💰 **Cost Comparison** (${inputTokens} in + ${outputTokens} out tokens)`,
          ``,
          `| Model | Provider | Tier | Total Cost | vs Cheapest |`,
          `|-------|----------|------|------------|-------------|`,
          ...rows,
          ``,
          `**Best value:** ${cheapest.model} (${cheapest.provider}) — $${cheapest.totalCost.toFixed(6)}`,
          `**Max savings:** $${maxSaving.toFixed(6)} by switching from ${mostExpensive.model} to ${cheapest.model}`,
        ];
        return { content: [{ type: 'text', text: lines.join('\n') }] };
      }

      case 'compress_context': {
        const messages = args.messages;
        if (!messages || !Array.isArray(messages)) throw new Error('messages is required — pass an array of {role, content} objects');
        const maxTokens = safeNum(args.max_tokens, 4000);

        // Sanitise: filter out non-object entries and coerce content to string
        const safeMsgs = messages
          .filter((m: unknown): m is { role: string; content: string } =>
            m != null && typeof m === 'object' && 'content' in (m as Record<string, unknown>))
          .map((m: { role?: unknown; content?: unknown }) => ({
            role: String(m.role ?? 'user'),
            content: String(m.content ?? ''),
          }));

        const totalBefore = safeMsgs.reduce((s, m) => s + countTokens(m.content), 0);
        const compressed: Array<{ role: string; content: string }> = [];
        let usedTokens = 0;
        const skipped: Array<{ role: string; content: string }> = [];

        for (let i = safeMsgs.length - 1; i >= 0; i--) {
          const msg = safeMsgs[i];
          const msgTokens = countTokens(msg.content);
          if (usedTokens + msgTokens <= maxTokens) {
            compressed.unshift(msg);
            usedTokens += msgTokens;
          } else {
            for (let j = 0; j <= i; j++) skipped.push(safeMsgs[j]);
            break;
          }
        }

        if (skipped.length > 0) {
          const summaryText = `[Context summary: ${skipped.length} earlier messages covering: ` +
            skipped.map(m => m.content.slice(0, 40).replace(/\n/g, ' ')).join('; ') + ']';
          const summaryTokens = countTokens(summaryText);
          if (usedTokens + summaryTokens <= maxTokens) {
            compressed.unshift({ role: 'system', content: summaryText });
            usedTokens += summaryTokens;
          }
        }

        const lines = [
          `🗜️ **Context Compression**`,
          ``,
          `| Metric | Value |`,
          `|--------|-------|`,
          `| Original messages | ${safeMsgs.length} |`,
          `| Compressed messages | ${compressed.length} |`,
          `| Tokens before | ${totalBefore} |`,
          `| Tokens after | ${usedTokens} |`,
          `| Token budget | ${maxTokens} |`,
          `| Tokens saved | ${totalBefore - usedTokens} (${totalBefore > 0 ? Math.round((totalBefore - usedTokens)/totalBefore*100) : 0}%) |`,
          ...(skipped.length > 0 ? [`| Messages summarized | ${skipped.length} |`] : []),
        ];
        return {
          content: [
            { type: 'text', text: lines.join('\n') },
            { type: 'text', text: JSON.stringify({ messages: compressed }, null, 2) },
          ],
        };
      }

      case 'find_cheapest_model': {
        const inputTokens = safeNum(args.input_tokens, 1000);
        const outputTokens = safeNum(args.output_tokens, 500);
        const tierFilter = args.tier as string | undefined;
        const providerFilter = args.provider as string | undefined;

        const filtered = Object.entries(MODEL_RATES)
          .filter(([, r]) => !tierFilter || r.tier === tierFilter)
          .filter(([, r]) => !providerFilter || r.provider === providerFilter)
          .map(([model, rates]) => {
            const inCost = (inputTokens / 1000) * rates.input;
            const outCost = (outputTokens / 1000) * rates.output;
            return { model, provider: rates.provider, tier: rates.tier, totalCost: inCost + outCost };
          })
          .sort((a, b) => a.totalCost - b.totalCost);

        if (!filtered.length) {
          return { content: [{ type: 'text', text: `No models found matching tier=${tierFilter ?? 'any'}, provider=${providerFilter ?? 'any'}` }] };
        }

        const top3 = filtered.slice(0, 3);
        const lines = [
          `🏆 **Cheapest Models** (${inputTokens} in + ${outputTokens} out tokens${tierFilter ? `, tier: ${tierFilter}` : ''}${providerFilter ? `, provider: ${providerFilter}` : ''})`,
          ``,
          `| Rank | Model | Provider | Tier | Cost |`,
          `|------|-------|----------|------|------|`,
          ...top3.map((m, i) => `| ${i + 1} | **${m.model}** | ${m.provider} | ${m.tier} | $${m.totalCost.toFixed(6)} |`),
          ``,
          `**Recommendation:** Use **${top3[0].model}** (${top3[0].provider}) at $${top3[0].totalCost.toFixed(6)} per call`,
        ];
        return { content: [{ type: 'text', text: lines.join('\n') }] };
      }

      default:
        throw new Error(`Unknown tool: ${name}`);
    }
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    errorLog(`tool/${name}`, err);
    return {
      content: [{ type: 'text', text: `❌ Error: ${message}` }],
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
  if (!API_KEY) {
    process.stderr.write('[vantage-mcp] WARNING: VANTAGE_API_KEY is not set. Tools will fail until a key is provided.\n');
    process.stderr.write('[vantage-mcp] Get your key at: https://vantageaiops.com/signup.html\n');
  } else {
    process.stderr.write(`[vantage-mcp] org=${ORG} api=${API_BASE}\n`);
  }
  const transport = new StdioServerTransport();
  await server.connect(transport);
  process.stderr.write('[vantage-mcp] Server started\n');
}

// Catch unhandled errors so the server never silently dies
process.on('uncaughtException', (err) => {
  errorLog('uncaughtException', err);
  // Don't exit — keep the server alive for remaining tool calls
});
process.on('unhandledRejection', (reason) => {
  errorLog('unhandledRejection', reason);
});

main().catch((err) => {
  process.stderr.write(`[vantage-mcp] Fatal: ${err.message}\n`);
  process.exit(1);
});
