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

// ── LLM Cost Optimizer ───────────────────────────────────────────────────────

class LLMCostOptimizer {
  private readonly MODEL_RATES: Record<string, { input: number; output: number }> = {
    // OpenAI
    'gpt-4o':           { input: 0.0025,  output: 0.01 },
    'gpt-4o-mini':      { input: 0.00015, output: 0.0006 },
    'gpt-4-turbo':      { input: 0.01,    output: 0.03 },
    'gpt-4':            { input: 0.03,    output: 0.06 },
    'gpt-3.5-turbo':    { input: 0.0005,  output: 0.0015 },
    'o1':               { input: 0.015,   output: 0.06 },
    'o1-mini':          { input: 0.003,   output: 0.012 },
    'o3-mini':          { input: 0.0011,  output: 0.0044 },
    // Anthropic
    'claude-sonnet-4':  { input: 0.003,   output: 0.015 },
    'claude-3.5-sonnet':{ input: 0.003,   output: 0.015 },
    'claude-3-sonnet':  { input: 0.003,   output: 0.015 },
    'claude-3-opus':    { input: 0.015,   output: 0.075 },
    'claude-3-haiku':   { input: 0.00025, output: 0.00125 },
    'claude-haiku-3.5': { input: 0.0008,  output: 0.004 },
    // Google
    'gemini-2.0-flash': { input: 0.0001,  output: 0.0004 },
    'gemini-1.5-pro':   { input: 0.00125, output: 0.005 },
    'gemini-1.5-flash': { input: 0.000075,output: 0.0003 },
    'gemini-pro':       { input: 0.00025, output: 0.0005 },
    // Meta / DeepSeek / Mistral
    'llama-3.3-70b':    { input: 0.00059, output: 0.00079 },
    'deepseek-v3':      { input: 0.00027, output: 0.0011 },
    'deepseek-r1':      { input: 0.00055, output: 0.00219 },
    'mistral-large':    { input: 0.002,   output: 0.006 },
    'mistral-small':    { input: 0.0002,  output: 0.0006 },
  };

  private readonly FILLER_WORDS = /\b(the|and|or|but|in|on|at|to|for|of|with|by|an|a|is|are|was|were|be|been|being|have|has|had|do|does|did|will|would|could|should|may|might|must|can|shall)\b/gi;

  countTokens(text: string): number {
    const words = text.split(/\s+/).filter(w => w.length > 0);
    return Math.ceil(words.length * 1.3);
  }

  compressPrompt(prompt: string, compressionRate: number = 0.5): {
    originalText: string;
    compressedText: string;
    originalTokens: number;
    compressedTokens: number;
    compressionRatio: number;
    savingsPercentage: string;
  } {
    const originalTokens = this.countTokens(prompt);

    let compressed = prompt.replace(this.FILLER_WORDS, '').replace(/\s+/g, ' ').trim();

    const targetLength = Math.floor(prompt.length * compressionRate);
    if (compressed.length > targetLength) {
      compressed = compressed.substring(0, targetLength) + '...';
    }

    const compressedTokens = this.countTokens(compressed);
    const compressionRatio = originalTokens > 0 ? compressedTokens / originalTokens : 1;
    const savingsPct = originalTokens > 0
      ? ((originalTokens - compressedTokens) / originalTokens * 100).toFixed(1)
      : '0.0';

    return {
      originalText: prompt,
      compressedText: compressed,
      originalTokens,
      compressedTokens,
      compressionRatio,
      savingsPercentage: savingsPct + '%',
    };
  }

  estimateCost(model: string, tokens: number): number {
    const rates = this.MODEL_RATES[model] ?? this.MODEL_RATES['gpt-3.5-turbo'];
    return (tokens / 1000) * rates.input;
  }

  estimateCostDetailed(model: string, inputTokens: number, outputTokens: number): {
    inputCost: number; outputCost: number; totalCost: number;
  } {
    const rates = this.MODEL_RATES[model] ?? this.MODEL_RATES['gpt-3.5-turbo'];
    const inputCost = (inputTokens / 1000) * rates.input;
    const outputCost = (outputTokens / 1000) * rates.output;
    return { inputCost, outputCost, totalCost: inputCost + outputCost };
  }

  get modelNames(): string[] {
    return Object.keys(this.MODEL_RATES);
  }
}

const optimizer = new LLMCostOptimizer();

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

    // ── Optimizer tools ────────────────────────────────────────────────────────
    {
      name: 'optimize_prompt',
      description: 'Compress a prompt to reduce token usage while preserving meaning. Removes filler words and trims to a target compression rate.',
      inputSchema: {
        type: 'object',
        properties: {
          prompt: { type: 'string', description: 'The prompt text to optimize' },
          compression_rate: {
            type: 'number',
            description: 'Target compression rate between 0.1 and 1.0 (default: 0.5)',
            minimum: 0.1,
            maximum: 1.0,
          },
        },
        required: ['prompt'],
      },
    },
    {
      name: 'analyze_tokens',
      description: 'Analyze token count and estimated cost for a given text and model.',
      inputSchema: {
        type: 'object',
        properties: {
          text: { type: 'string', description: 'The text to analyze' },
          model: {
            type: 'string',
            description: 'Model to price against (default: gpt-3.5-turbo)',
            enum: ['gpt-4o', 'gpt-4o-mini', 'gpt-4-turbo', 'gpt-4', 'gpt-3.5-turbo', 'o1', 'o1-mini', 'o3-mini', 'claude-sonnet-4', 'claude-3.5-sonnet', 'claude-3-opus', 'claude-3-haiku', 'claude-haiku-3.5', 'gemini-2.0-flash', 'gemini-1.5-pro', 'gemini-1.5-flash', 'llama-3.3-70b', 'deepseek-v3', 'deepseek-r1', 'mistral-large', 'mistral-small'],
          },
        },
        required: ['text'],
      },
    },
    {
      name: 'estimate_costs',
      description: 'Estimate costs for a prompt across all supported models — useful for choosing the cheapest option.',
      inputSchema: {
        type: 'object',
        properties: {
          prompt: { type: 'string', description: 'The prompt to estimate costs for' },
          completion_tokens: {
            type: 'number',
            description: 'Expected number of completion/output tokens (default: 100)',
          },
        },
        required: ['prompt'],
      },
    },
    {
      name: 'compress_context',
      description: 'Compress a conversation message list to fit within a token budget, keeping the most recent messages and summarizing older ones.',
      inputSchema: {
        type: 'object',
        properties: {
          messages: {
            type: 'array',
            description: 'Array of conversation messages',
            items: {
              type: 'object',
              properties: {
                role: { type: 'string', enum: ['user', 'assistant', 'system'] },
                content: { type: 'string' },
              },
              required: ['role', 'content'],
            },
          },
          max_tokens: {
            type: 'number',
            description: 'Maximum token budget for the compressed context (default: 4000)',
          },
        },
        required: ['messages'],
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
        const days = args?.days ?? 30;
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
        const days = args?.days ?? 30;
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
        const limit = Math.min(Number(args?.limit ?? 10), 50);
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

      // ── Optimizer tool handlers ───────────────────────────────────────────

      case 'optimize_prompt': {
        const prompt = args.prompt as string;
        if (!prompt) throw new Error('prompt is required');
        const rate = Number(args.compression_rate ?? 0.5);
        const result = optimizer.compressPrompt(prompt, rate);
        return {
          content: [{
            type: 'text',
            text: JSON.stringify({
              success: true,
              original_prompt: result.originalText,
              optimized_prompt: result.compressedText,
              original_tokens: result.originalTokens,
              compressed_tokens: result.compressedTokens,
              compression_ratio: result.compressionRatio,
              savings_percentage: result.savingsPercentage,
            }, null, 2),
          }],
        };
      }

      case 'analyze_tokens': {
        const text = args.text as string;
        if (!text) throw new Error('text is required');
        const model = (args.model as string) || 'gpt-3.5-turbo';
        const tokenCount = optimizer.countTokens(text);
        const cost = optimizer.estimateCost(model, tokenCount);
        return {
          content: [{
            type: 'text',
            text: JSON.stringify({
              success: true,
              text_length: text.length,
              token_count: tokenCount,
              model,
              estimated_cost: `$${cost.toFixed(6)}`,
              cost_breakdown: {
                tokens: tokenCount,
                rate_per_1k: `$${(cost * 1000 / Math.max(tokenCount, 1)).toFixed(6)}`,
                total: `$${cost.toFixed(6)}`,
              },
            }, null, 2),
          }],
        };
      }

      case 'estimate_costs': {
        const estPrompt = args.prompt as string;
        if (!estPrompt) throw new Error('prompt is required');
        const completionTokens = Number(args.completion_tokens ?? 100);
        const promptTokens = optimizer.countTokens(estPrompt);
        const totalTokens = promptTokens + completionTokens;

        const comparisons = optimizer.modelNames.map((m) => {
          const detail = optimizer.estimateCostDetailed(m, promptTokens, completionTokens);
          return {
            model: m,
            input_cost: `$${detail.inputCost.toFixed(6)}`,
            output_cost: `$${detail.outputCost.toFixed(6)}`,
            total_cost: `$${detail.totalCost.toFixed(6)}`,
          };
        });

        return {
          content: [{
            type: 'text',
            text: JSON.stringify({
              success: true,
              prompt_tokens: promptTokens,
              completion_tokens: completionTokens,
              total_tokens: totalTokens,
              comparisons,
            }, null, 2),
          }],
        };
      }

      case 'compress_context': {
        const messages = args.messages as Array<{ role: string; content: string }>;
        if (!messages || !Array.isArray(messages)) throw new Error('messages array is required');
        const maxTokens = Number(args.max_tokens ?? 4000);

        const compressed: Array<{ role: string; content: string }> = [];
        let usedTokens = 0;
        const skippedMessages: Array<{ role: string; content: string }> = [];

        // Walk from newest to oldest, keep messages that fit
        for (let i = messages.length - 1; i >= 0; i--) {
          const msg = messages[i];
          const msgTokens = optimizer.countTokens(msg.content);
          if (usedTokens + msgTokens <= maxTokens) {
            compressed.unshift(msg);
            usedTokens += msgTokens;
          } else {
            // Collect all remaining older messages for summary
            for (let j = 0; j <= i; j++) {
              skippedMessages.push(messages[j]);
            }
            break;
          }
        }

        // If we skipped messages, prepend a summary message
        if (skippedMessages.length > 0) {
          const summaryText = `[Summarized ${skippedMessages.length} earlier message(s): ` +
            skippedMessages.map(m => `${m.role}: ${m.content.slice(0, 60)}${m.content.length > 60 ? '...' : ''}`).join(' | ') +
            ']';
          const summaryTokens = optimizer.countTokens(summaryText);
          if (usedTokens + summaryTokens <= maxTokens) {
            compressed.unshift({ role: 'system', content: summaryText });
            usedTokens += summaryTokens;
          }
        }

        return {
          content: [{
            type: 'text',
            text: JSON.stringify({
              success: true,
              original_messages: messages.length,
              compressed_messages: compressed.length,
              total_tokens: usedTokens,
              max_tokens: maxTokens,
              compression_ratio: messages.length > 0 ? compressed.length / messages.length : 1,
              messages: compressed,
            }, null, 2),
          }],
        };
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

main().catch((err) => {
  process.stderr.write(`[vantage-mcp] Fatal: ${err.message}\n`);
  process.exit(1);
});
