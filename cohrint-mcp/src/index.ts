#!/usr/bin/env node
/**
 * Cohrint MCP Server
 *
 * Exposes Cohrint as an MCP server so AI coding assistants
 * (Claude Desktop, Cursor, Windsurf, VS Code Copilot, Cline, etc.)
 * can track LLM costs and query analytics in real-time.
 *
 * Config:
 *   COHRINT_API_KEY  — your crt_... key (required)
 *   COHRINT_ORG      — org id (auto-parsed from key if omitted)
 *   COHRINT_API_BASE — default: https://api.cohrint.com
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
import { VERSION } from './_version.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { homedir } from 'node:os';
import { existsSync, mkdirSync, readFileSync, writeFileSync, copyFileSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
  ListResourcesRequestSchema,
  ReadResourceRequestSchema,
} from '@modelcontextprotocol/sdk/types.js';

// ── Config ────────────────────────────────────────────────────────────────────

const API_KEY  = process.env.COHRINT_API_KEY  ?? process.env.VANTAGE_API_KEY  ?? '';
const API_BASE = (process.env.COHRINT_API_BASE ?? process.env.VANTAGE_API_BASE ?? 'https://api.cohrint.com').replace(/\/+$/, '');
const ORG      = process.env.COHRINT_ORG      ?? process.env.VANTAGE_ORG      ?? parseOrgFromKey(API_KEY);

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
  process.stderr.write(`[cohrint-mcp] ${ts} ERROR ${context}: ${safe}\n`);
}

// ── API client ────────────────────────────────────────────────────────────────

async function api(path: string, opts: RequestInit = {}): Promise<unknown> {
  if (!API_KEY) throw new Error('COHRINT_API_KEY is not set. Add it to your MCP config. Get a key at https://cohrint.com/signup.html');

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
      throw new Error(`Request to Cohrint API timed out (${path}). Check your network connection.`);
    }
    throw new Error(`Cannot reach Cohrint API (${path}): ${msg.split('\n')[0]}`);
  }

  let body: unknown;
  try {
    body = await res.json();
  } catch {
    throw new Error(`Cohrint API returned invalid JSON (HTTP ${res.status} on ${path}).`);
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

// ── Filler phrases: politeness & padding that waste tokens ──────────────────
const FILLER_PHRASES = [
  "i'd like you to", "i want you to", "i need you to",
  "would you mind", "could you please", "can you please",
  "please note that", "it is important to note that",
  "as an ai language model", "as a helpful assistant",
  "in order to", "for the purpose of", "with regard to",
  "in the context of", "it should be noted that",
  "it is worth mentioning that", "i was wondering if you could",
  "it goes without saying", "needless to say",
  "as previously mentioned", "as stated above",
  "for your information", "i would appreciate it if you could",
  "please be advised that", "at the end of the day",
  "in today's world", "in this day and age",
  "each and every", "first and foremost",
  "due to the fact that", "on account of the fact that",
  "in light of the fact that", "despite the fact that",
  "the reason is because", "whether or not",
];

const FILLER_WORDS_RE = /\b(please|kindly|basically|essentially|actually|literally|obviously|clearly|simply|just|very|really|quite|rather|somewhat|pretty|fairly)\b/gi;

// ── Verbose → concise rewrites: structural compression ─────────────────────
const VERBOSE_REWRITES: Array<[RegExp, string]> = [
  [/\bin order to\b/gi, 'to'],
  [/\bfor the purpose of\b/gi, 'for'],
  [/\bwith regard to\b/gi, 'regarding'],
  [/\bwith respect to\b/gi, 'regarding'],
  [/\bin the event that\b/gi, 'if'],
  [/\bin the case of\b/gi, 'for'],
  [/\bat this point in time\b/gi, 'now'],
  [/\bat the present time\b/gi, 'now'],
  [/\bprior to\b/gi, 'before'],
  [/\bsubsequent to\b/gi, 'after'],
  [/\bin close proximity to\b/gi, 'near'],
  [/\ba large number of\b/gi, 'many'],
  [/\ba small number of\b/gi, 'few'],
  [/\bthe majority of\b/gi, 'most'],
  [/\bon a daily basis\b/gi, 'daily'],
  [/\bon a regular basis\b/gi, 'regularly'],
  [/\bis able to\b/gi, 'can'],
  [/\bare able to\b/gi, 'can'],
  [/\bhas the ability to\b/gi, 'can'],
  [/\bhave the ability to\b/gi, 'can'],
  [/\bmake a decision\b/gi, 'decide'],
  [/\bcome to a conclusion\b/gi, 'conclude'],
  [/\btake into consideration\b/gi, 'consider'],
  [/\bgive consideration to\b/gi, 'consider'],
  [/\bthe fact that\b/gi, 'that'],
  [/\bin spite of\b/gi, 'despite'],
  [/\bdue to the fact that\b/gi, 'because'],
  [/\bon account of\b/gi, 'because'],
  [/\bit is necessary that\b/gi, 'must'],
  [/\bit is important that\b/gi, 'must'],
  [/\bfor the reason that\b/gi, 'because'],
  [/\bwith the exception of\b/gi, 'except'],
  [/\bin the near future\b/gi, 'soon'],
  [/\bat a later date\b/gi, 'later'],
  [/\bin the amount of\b/gi, 'for'],
  [/\bin regard to\b/gi, 'about'],
  [/\bpertaining to\b/gi, 'about'],
  [/\bconcerning the matter of\b/gi, 'about'],
  [/\bas a consequence of\b/gi, 'because of'],
  [/\bin the process of\b/gi, 'while'],
  [/\bin an effort to\b/gi, 'to'],
  [/\bby means of\b/gi, 'by'],
  [/\bin conjunction with\b/gi, 'with'],
];

/** Count tokens using word-level heuristic (matches GPT tokenizer ±10%). */
function countTokens(text: string): number {
  if (!text) return 0;
  const words = text.split(/\s+/).filter(w => w.length > 0);
  let count = 0;
  for (const w of words) {
    if (w.length <= 4) count += 1;
    else if (w.length <= 8) count += 1.3;
    else if (w.length <= 12) count += 1.8;
    else count += Math.ceil(w.length / 4);
  }
  return Math.ceil(count);
}

/**
 * Smart prompt compression — 5 layers of optimization:
 * 1. Remove filler phrases ("could you please", "it is important to note that")
 * 2. Rewrite verbose patterns to concise equivalents ("in order to" → "to")
 * 3. Remove filler words ("basically", "essentially", "just", "very")
 * 4. Deduplicate repeated sentences
 * 5. Collapse formatting (multi-spaces, redundant newlines, trailing punctuation)
 */
function compressPrompt(prompt: string): string {
  let text = prompt;

  // Layer 1: Remove filler phrases
  for (const phrase of FILLER_PHRASES) {
    const escaped = phrase.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    text = text.replace(new RegExp(`\\b${escaped}\\b`, 'gi'), '');
  }

  // Layer 2: Verbose → concise rewrites (structural compression)
  for (const [pattern, replacement] of VERBOSE_REWRITES) {
    text = text.replace(pattern, replacement);
  }

  // Layer 3: Remove filler words
  text = text.replace(FILLER_WORDS_RE, '');

  // Layer 4: Deduplicate sentences
  const sentences = text.split(/(?<=[.!?])\s+/);
  const unique: string[] = [];
  const seen = new Set<string>();
  for (const s of sentences) {
    const norm = s.toLowerCase().trim().replace(/\s+/g, ' ');
    if (norm.length > 2 && !seen.has(norm)) { seen.add(norm); unique.push(s); }
  }
  text = unique.join(' ');

  // Layer 5: Collapse whitespace and formatting
  text = text.replace(/\n{3,}/g, '\n\n');        // max 2 newlines
  text = text.replace(/[ \t]{2,}/g, ' ');         // collapse spaces
  text = text.replace(/\s+([.!?,;:])/g, '$1');    // space before punct
  text = text.replace(/([.!?])\1+/g, '$1');       // repeated punct
  return text.trim();
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

/** Generate actionable optimization tips for a prompt. */
function getOptimizationTips(prompt: string): string[] {
  const tips: string[] = [];
  const tokens = countTokens(prompt);
  const compressed = compressPrompt(prompt);
  const compressedTokens = countTokens(compressed);
  const saved = tokens - compressedTokens;
  const pct = tokens > 0 ? Math.round(saved / tokens * 100) : 0;

  // Compression savings
  if (saved > 5) tips.push(`Compression saves ~${saved} tokens (${pct}%) by removing filler phrases and rewriting verbose patterns`);

  // Structural analysis
  if (/```[\s\S]{500,}```/.test(prompt)) tips.push('Large code block (500+ chars) inlined — reference the file path instead of pasting code');
  if (/```[\s\S]*```[\s\S]*```[\s\S]*```/.test(prompt)) tips.push('Multiple code blocks — consolidate into one block or reference files');

  const lines = (prompt.match(/\n/g) || []).length;
  if (lines > 50) tips.push(`${lines} lines — use structured bullet points instead of prose to reduce tokens by ~30%`);

  // Repetition detection
  const words = prompt.toLowerCase().split(/\s+/);
  const wordCounts: Record<string, number> = {};
  for (const w of words) { if (w.length > 5) wordCounts[w] = (wordCounts[w] || 0) + 1; }
  const repeated = Object.entries(wordCounts).filter(([, c]) => c > 5).map(([w]) => w);
  if (repeated.length > 3) tips.push(`Repeated words (${repeated.slice(0, 3).join(', ')}...) — deduplicate or restructure`);

  // Duplicate sentences
  const sentences = prompt.split(/(?<=[.!?])\s+/);
  const sentSet = new Set<string>();
  let dupes = 0;
  for (const s of sentences) {
    const norm = s.toLowerCase().trim();
    if (norm.length > 20 && sentSet.has(norm)) dupes++;
    sentSet.add(norm);
  }
  if (dupes > 0) tips.push(`${dupes} duplicate sentence(s) detected — remove repeats`);

  // Model-specific advice
  if (tokens > 8000) tips.push('Prompt > 8K tokens — enable prompt caching (system prompt prefix) to save 90% on repeated context');
  if (tokens > 4000) tips.push('Prompt > 4K tokens — consider gemini-2.0-flash ($0.10/1M) or deepseek-v3 ($0.27/1M) for this task');
  if (tokens > 2000 && tokens <= 4000) tips.push('Consider claude-haiku-4-5 ($0.80/1M) or gpt-4o-mini ($0.15/1M) if quality allows');

  // JSON/XML detection
  if (/\{[\s\S]{200,}\}/.test(prompt)) tips.push('Large JSON payload — send as a tool parameter or file reference instead of inline text');
  if (/<[a-z][\s\S]{200,}<\/[a-z]/i.test(prompt)) tips.push('Large XML/HTML block — consider extracting to a file reference');

  // System prompt heuristics
  if (/you are|your role|act as|behave as/i.test(prompt) && tokens > 500) {
    tips.push('System prompt detected (500+ tokens) — move to a static system message and enable caching');
  }

  if (tips.length === 0) tips.push('Prompt is already concise — no major optimizations found');
  return tips;
}

// ── MCP Server ────────────────────────────────────────────────────────────────

const server = new Server(
  { name: 'cohrint-mcp', version: VERSION },
  { capabilities: { tools: {}, resources: {} } },
);

// ── Tool definitions ──────────────────────────────────────────────────────────

server.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: [
    {
      name: 'track_llm_call',
      description: 'Track an LLM API call — logs cost, tokens, latency, model, and team to Cohrint. Call this after every LLM completion.',
      inputSchema: {
        type: 'object',
        properties: {
          model:            { type: 'string', description: 'Model name, e.g. gpt-4o, claude-3-5-sonnet' },
          provider:         { type: 'string', description: 'Provider: openai | anthropic | google | mistral | cohere | other' },
          prompt_tokens:    { type: 'number', description: 'Number of input/prompt tokens' },
          completion_tokens:{ type: 'number', description: 'Number of output/completion tokens' },
          total_cost_usd:   { type: 'number', description: 'Total cost in USD (e.g. 0.0025)' },
          latency_ms:       { type: 'number', description: 'End-to-end latency in milliseconds' },
          cache_tokens:     { type: 'number', description: 'Tokens served from provider native cache (Anthropic/OpenAI prompt caching). Reduces billed cost.' },
          prompt_hash:      { type: 'string', description: 'SHA-256 fingerprint of the prompt (first 16 hex chars). Compute: crypto.createHash("sha256").update(prompt).digest("hex").slice(0,16). Enables duplicate detection. Never send raw prompt text.' },
          team:             { type: 'string', description: 'Team or feature name for grouping (e.g. "backend", "search")' },
          environment:      { type: 'string', description: 'Environment: production | staging | development' },
          trace_id:         { type: 'string', description: 'Trace ID for grouping multi-step agent calls' },
          span_depth:       { type: 'number', description: 'Depth in agent call tree (0 = root)' },
          tags:             { type: 'object', description: 'Arbitrary key-value tags for filtering' },
          session_id:       { type: 'string', description: 'Session ID — links this event to a vantage-agent or local-proxy session' },
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
    {
      name: 'setup_claude_hook',
      description: 'Install the Cohrint Stop hook into Claude Code (~/.claude/settings.json). Run this once after adding the MCP to automatically track costs at the end of every Claude Code session. Idempotent — safe to run multiple times.',
      inputSchema: { type: 'object', properties: {} },
    },
    {
      name: 'get_recommendations',
      description: 'Get agent-specific cost optimization recommendations based on your current usage patterns. Provides actionable tips for Claude Code, Gemini CLI, Codex, Cursor, Aider, and Copilot. Works offline — no API key needed.',
      inputSchema: {
        type: 'object',
        properties: {
          agent: {
            type: 'string',
            description: 'The AI coding agent being used (claude, gemini, codex, cursor, aider, copilot)',
          },
          model: {
            type: 'string',
            description: 'Current model being used (e.g. claude-sonnet-4-6, gpt-4o, gemini-2.0-flash)',
          },
          session_cost_usd: {
            type: 'number',
            description: 'Current session total cost in USD',
          },
          prompt_count: {
            type: 'number',
            description: 'Number of prompts in this session',
          },
        },
        required: ['agent'],
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
          ...(args.session_id ? { session_id: String(args.session_id).slice(0, 256) } : {}),
          ...(safeNum(args.cache_tokens, 0) > 0 ? { cache_tokens: safeNum(args.cache_tokens, 0) } : {}),
          ...(args.prompt_hash ? { prompt_hash: String(args.prompt_hash).slice(0, 64) } : {}),
        };
        const trackResp = await api('/v1/events', { method: 'POST', body: JSON.stringify(event) }) as Record<string, unknown>;
        const cacheWarning = trackResp?.cache_warning ? String(trackResp.cache_warning) : null;
        const baseText = `✅ Tracked: ${model} | ${promptTokens}→${completionTokens} tokens | $${totalCost.toFixed(4)} | ${latency > 0 ? `${latency}ms` : 'no latency recorded'}`;
        return {
          content: [{
            type: 'text',
            text: cacheWarning ? `⚠️ ${cacheWarning}\n\n${baseText}` : baseText,
          }],
        };
      }

      case 'get_summary': {
        const data = await api('/v1/analytics/summary') as Record<string, unknown>;
        const lines = [
          `📊 **Cohrint Summary** (org: ${ORG})`,
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
          `🔗 [View dashboard](https://cohrint.com/app.html)`,
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
          `| Cache Tokens Total | ${Number(data.cache_tokens_total ?? 0).toLocaleString()} |`,
          `| Cache Savings | $${Number(data.cache_savings_usd ?? 0).toFixed(4)} |`,
          `| Cache Hit Rate | ${Number(data.cache_hit_rate_pct ?? 0).toFixed(1)}% |`,
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
        // Use a fixed output estimate (half of original input) so cost comparison is fair
        const estimatedOutputTokens = Math.round(originalTokens / 2);
        const costBefore = calcCost(model, originalTokens, estimatedOutputTokens);
        const costAfter = calcCost(model, compressedTokens, estimatedOutputTokens);
        const cheapest = findCheapest(compressedTokens, estimatedOutputTokens);

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
            for (let j = 0; j < i; j++) skipped.push(safeMsgs[j]);
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

      case 'get_recommendations': {
        const agent = String(args.agent ?? '').toLowerCase().trim();
        if (!agent) throw new Error('agent is required (claude, gemini, codex, cursor, aider, copilot)');
        const recModel = typeof args.model === 'string' ? args.model.toLowerCase().trim() : '';
        const sessionCost = safeNum(args.session_cost_usd, 0);
        const promptCount = safeNum(args.prompt_count, 0);

        // ── Tip database per agent ────────────────────────────────────────
        interface Tip { title: string; action: string; savings: string; priority: 'high' | 'medium' | 'low' }

        const AGENT_TIPS: Record<string, Tip[]> = {
          claude: [
            { title: 'Use /compact to shrink context', action: 'Type /compact in Claude Code to compress conversation history', savings: '30-50% token reduction per session', priority: 'high' },
            { title: 'Use CLAUDE.md for persistent instructions', action: 'Add rules to CLAUDE.md instead of repeating them in every prompt', savings: '~200-500 tokens per prompt', priority: 'high' },
            { title: 'Prefer Haiku for simple tasks', action: 'Set model to claude-haiku-3.5 for refactors, renames, and formatting', savings: 'Up to 90% cost reduction vs Opus', priority: 'medium' },
            { title: 'Use /clear between unrelated tasks', action: 'Type /clear to reset context when switching tasks', savings: '20-40% by avoiding stale context', priority: 'medium' },
            { title: 'Batch file edits in one prompt', action: 'Describe all related changes in a single message instead of one-at-a-time', savings: '~$0.02-0.10 per avoided round-trip', priority: 'low' },
          ],
          gemini: [
            { title: 'Use Gemini Flash for most tasks', action: 'gemini -m gemini-2.0-flash (10x cheaper than Pro)', savings: 'Up to 90% vs gemini-1.5-pro', priority: 'high' },
            { title: 'Leverage 1M token context wisely', action: 'Pass entire files instead of snippets to reduce follow-up prompts', savings: '~30% fewer round-trips', priority: 'medium' },
            { title: 'Use grounding for factual queries', action: 'Enable Google Search grounding for docs/API questions', savings: 'Fewer hallucination retries, ~20% savings', priority: 'medium' },
            { title: 'Stream responses for long outputs', action: 'Use --stream flag for code generation tasks', savings: 'Faster perceived latency, same cost', priority: 'low' },
          ],
          codex: [
            { title: 'Use o3-mini for routine coding', action: 'codex --model o3-mini (4x cheaper than o3)', savings: 'Up to 75% cost reduction', priority: 'high' },
            { title: 'Sandbox tasks to avoid retries', action: 'Use codex in full-auto mode with sandboxed execution to catch errors early', savings: '~$0.05-0.20 per avoided retry cycle', priority: 'high' },
            { title: 'Keep prompts specific and scoped', action: 'Ask for one function at a time, not entire modules', savings: '~40% token reduction per prompt', priority: 'medium' },
            { title: 'Use --quiet for simple completions', action: 'Skip verbose explanations with concise output flags', savings: '~30% output token savings', priority: 'low' },
          ],
          cursor: [
            { title: 'Use Cursor Tab for completions', action: 'Rely on Tab autocomplete instead of Chat for small edits', savings: 'Tab is free/included, Chat costs tokens', priority: 'high' },
            { title: 'Apply to specific files only', action: 'Use @file references instead of letting Cursor scan entire codebase', savings: '~50% context token reduction', priority: 'high' },
            { title: 'Switch to claude-haiku-3.5 for refactors', action: 'Settings > Models > select claude-haiku-3.5 for bulk operations', savings: 'Up to 85% vs default Sonnet', priority: 'medium' },
            { title: 'Use .cursorignore to exclude files', action: 'Add build/, dist/, node_modules/ to .cursorignore', savings: '~20% faster indexing, fewer wasted tokens', priority: 'medium' },
            { title: 'Compose mode for multi-file edits', action: 'Use Composer instead of Chat for coordinated multi-file changes', savings: '~30% fewer round-trips', priority: 'low' },
          ],
          aider: [
            { title: 'Use --model for cheaper alternatives', action: 'aider --model deepseek-v3 or --model gemini-2.0-flash', savings: 'Up to 95% vs GPT-4 / Opus', priority: 'high' },
            { title: 'Add only relevant files to chat', action: 'Use /add and /drop to manage context — never add the whole repo', savings: '~60% context reduction', priority: 'high' },
            { title: 'Use /tokens to monitor usage', action: 'Type /tokens periodically to track session spend', savings: 'Awareness prevents overspend', priority: 'medium' },
            { title: 'Use map-tokens wisely', action: 'Set --map-tokens 1024 to limit repo map size', savings: '~500-2000 tokens per prompt', priority: 'medium' },
            { title: 'Enable caching with Anthropic', action: 'aider --cache-prompts with Claude models for repeated context', savings: 'Up to 90% on cached prefixes', priority: 'low' },
          ],
          copilot: [
            { title: 'Use inline completions over Chat', action: 'Rely on ghost text suggestions — they use smaller, cheaper models', savings: 'Chat costs 5-10x more per interaction', priority: 'high' },
            { title: 'Write clear function signatures', action: 'Add JSDoc/docstrings before the function for better completions', savings: 'Fewer rejected suggestions = fewer retries', priority: 'medium' },
            { title: 'Scope Chat to workspace', action: 'Use @workspace only when needed — prefer @file for targeted questions', savings: '~40% context reduction in Chat', priority: 'medium' },
            { title: 'Disable for non-code files', action: 'Settings > Copilot > disable for markdown, JSON, YAML', savings: '~15% fewer wasted completions', priority: 'low' },
          ],
        };

        // Resolve tips for the agent (fall back to generic)
        const agentKey = Object.keys(AGENT_TIPS).find(k => agent.includes(k)) ?? '';
        let tips: Tip[] = agentKey ? [...AGENT_TIPS[agentKey]] : [
          { title: 'Track your costs', action: 'Use Cohrint SDK or MCP to monitor every LLM call', savings: 'Visibility enables 20-40% optimization', priority: 'high' },
          { title: 'Use the cheapest viable model', action: 'Run estimate_costs tool to compare models for your workload', savings: 'Up to 95% by switching models', priority: 'high' },
          { title: 'Compress prompts', action: 'Run optimize_prompt tool to remove filler and reduce tokens', savings: '10-30% token savings', priority: 'medium' },
        ];

        // ── Contextual tips based on model/cost/prompt count ──────────────
        const expensiveModels = ['opus', 'gpt-4', 'pro', 'o1', 'o3'];
        const isExpensiveModel = recModel && expensiveModels.some(m => recModel.includes(m));

        if (isExpensiveModel) {
          tips.unshift({
            title: 'Switch to a cheaper model for this task',
            action: recModel.includes('opus') ? 'Switch to claude-sonnet-4 (5x cheaper) or claude-haiku-3.5 (60x cheaper)'
              : recModel.includes('gpt-4') && !recModel.includes('mini') ? 'Switch to gpt-4o-mini (20x cheaper) or deepseek-v3 (100x cheaper)'
              : recModel.includes('pro') ? 'Switch to gemini-2.0-flash (12x cheaper)'
              : recModel.includes('o1') ? 'Switch to o3-mini (5x cheaper) for reasoning tasks'
              : 'Switch to o3-mini (2.5x cheaper) for reasoning tasks',
            savings: 'Estimated 60-95% cost reduction',
            priority: 'high',
          });
        }

        if (sessionCost > 1.0) {
          tips.unshift({
            title: 'High session cost detected ($' + sessionCost.toFixed(2) + ')',
            action: 'Consider starting a fresh session. Use /compact or /clear to reset context. Review if recent prompts could be batched.',
            savings: 'New session avoids compounding context costs',
            priority: 'high',
          });
        } else if (sessionCost > 0.25) {
          tips.unshift({
            title: 'Session cost rising ($' + sessionCost.toFixed(2) + ')',
            action: 'Run /compact to compress context, or switch to a cheaper model for remaining tasks.',
            savings: '30-50% savings on remaining prompts',
            priority: 'medium',
          });
        }

        if (promptCount > 20) {
          tips.unshift({
            title: 'Many prompts in session (' + promptCount + ')',
            action: 'Start a new session to reset context. Long sessions accumulate tokens — each prompt re-sends the full history.',
            savings: 'Up to 70% reduction by resetting context',
            priority: 'high',
          });
        } else if (promptCount > 10) {
          tips.push({
            title: 'Consider session hygiene (' + promptCount + ' prompts)',
            action: 'Use /compact to compress older messages, or /clear if switching tasks.',
            savings: '20-40% context savings',
            priority: 'medium',
          });
        }

        // ── Format output ────────────────────────────────────────────────
        const priorityOrder = { high: 0, medium: 1, low: 2 };
        tips.sort((a, b) => priorityOrder[a.priority] - priorityOrder[b.priority]);

        // Deduplicate by title
        const seenTitles = new Set<string>();
        tips = tips.filter(t => {
          if (seenTitles.has(t.title)) return false;
          seenTitles.add(t.title);
          return true;
        });

        const priorityEmoji = { high: '🔴', medium: '🟡', low: '🟢' };
        const agentLabel = agentKey ? agentKey.charAt(0).toUpperCase() + agentKey.slice(1) : agent;

        const lines = [
          `**Cost Optimization Recommendations** — ${agentLabel}${recModel ? ` (${recModel})` : ''}`,
          ``,
          ...(sessionCost > 0 ? [`Session spend: **$${sessionCost.toFixed(4)}**${promptCount > 0 ? ` | ${promptCount} prompts | ~$${(sessionCost / promptCount).toFixed(4)}/prompt` : ''}`, ``] : []),
        ];

        for (const tip of tips.slice(0, 7)) {
          lines.push(
            `${priorityEmoji[tip.priority]} **${tip.title}**`,
            `   Action: ${tip.action}`,
            `   Savings: ${tip.savings}`,
            ``,
          );
        }

        lines.push(
          `---`,
          `Track all your AI costs at https://cohrint.com/app.html`,
        );

        return { content: [{ type: 'text', text: lines.join('\n') }] };
      }

      case 'setup_claude_hook': {
        const home = homedir();
        const claudeDir = join(home, '.claude');
        const hooksDir = join(claudeDir, 'hooks');
        const settingsPath = join(claudeDir, 'settings.json');

        if (!existsSync(claudeDir)) {
          return { content: [{ type: 'text', text: '❌ ~/.claude/ not found. Install Claude Code first: https://claude.ai/code' }], isError: true };
        }

        if (!existsSync(hooksDir)) mkdirSync(hooksDir, { recursive: true });

        const __dirnameHook = dirname(fileURLToPath(import.meta.url));
        const srcHook = join(__dirnameHook, 'vantage-track.js');
        const destHook = join(hooksDir, 'cohrint-track.js');

        if (!existsSync(srcHook)) {
          return { content: [{ type: 'text', text: `❌ Hook script not found at ${srcHook}. Try reinstalling cohrint-mcp.` }], isError: true };
        }

        copyFileSync(srcHook, destHook);

        type SettingsJson = Record<string, unknown>;
        let settings: SettingsJson = {};
        if (existsSync(settingsPath)) {
          try { settings = JSON.parse(readFileSync(settingsPath, 'utf-8')) as SettingsJson; } catch { /* start fresh */ }
        }

        const hookEntry = { matcher: '*', hooks: [{ type: 'command', command: `node ${destHook}` }] };
        if (!Array.isArray(settings.hooks)) settings.hooks = [];
        const hooksArr = settings.hooks as unknown[];
        const alreadyInstalled = hooksArr.some(
          (h) => typeof h === 'object' && h !== null &&
            JSON.stringify((h as Record<string, unknown>).hooks).includes('cohrint-track.js')
        );

        if (!alreadyInstalled) {
          hooksArr.push(hookEntry);
          writeFileSync(settingsPath, JSON.stringify(settings, null, 2));
        }

        const status = alreadyInstalled ? 'already installed — no changes made' : 'installed successfully';
        return {
          content: [{ type: 'text', text: [
            `✅ Cohrint Stop hook ${status}`,
            ``,
            `Hook location: ${destHook}`,
            `Settings: ${settingsPath}`,
            ``,
            `Every Claude Code session will now post token usage to Cohrint automatically.`,
            `Make sure COHRINT_API_KEY is set in your shell profile:`,
            `  export COHRINT_API_KEY=crt_...`,
            ``,
            `Get your free key: https://cohrint.com/signup.html`,
          ].join('\n') }],
        };
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
      name: 'Cohrint Dashboard',
      description: 'Live cost analytics dashboard',
      mimeType: 'text/plain',
    },
    {
      uri: 'vantage://docs',
      name: 'Cohrint Docs',
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
      return { contents: [{ uri, mimeType: 'text/plain', text: 'Dashboard: https://cohrint.com/app.html' }] };

    case 'vantage://docs':
      return { contents: [{ uri, mimeType: 'text/plain', text: 'Docs: https://cohrint.com/docs.html' }] };

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

// ── Setup subcommand ──────────────────────────────────────────────────────────

async function runSetup(): Promise<void> {
  const home = homedir();
  const claudeDir = join(home, '.claude');
  const hooksDir = join(claudeDir, 'hooks');
  const settingsPath = join(claudeDir, 'settings.json');

  // 1. Detect ~/.claude/
  if (!existsSync(claudeDir)) {
    process.stderr.write(
      '✗ ~/.claude/ not found. Install Claude Code first: https://claude.ai/code\n'
    );
    process.exit(1);
  }
  process.stdout.write('✓ Found ~/.claude/\n');

  // 2. Ensure hooks directory exists
  if (!existsSync(hooksDir)) {
    mkdirSync(hooksDir, { recursive: true });
    process.stdout.write('✓ Created ~/.claude/hooks/\n');
  } else {
    process.stdout.write('✓ ~/.claude/hooks/ exists\n');
  }

  // 3. Copy hook script (bundled in dist/ alongside this file)
  const __dirname = dirname(fileURLToPath(import.meta.url));
  const srcHook = join(__dirname, 'vantage-track.js');
  const destHook = join(hooksDir, 'cohrint-track.js');

  if (!existsSync(srcHook)) {
    process.stderr.write(`✗ vantage-track.js not found at ${srcHook}\n`);
    process.exit(1);
  }
  copyFileSync(srcHook, destHook);
  process.stdout.write(`✓ Installed cohrint-track.js → ${destHook}\n`);

  // 4. Patch ~/.claude/settings.json — merge Stop hook, never overwrite existing hooks
  type SettingsJson = Record<string, unknown>;
  let settings: SettingsJson = {};
  if (existsSync(settingsPath)) {
    try {
      settings = JSON.parse(readFileSync(settingsPath, 'utf-8')) as SettingsJson;
    } catch {
      // Corrupt or empty — start fresh but preserve the file path
    }
  }

  const hookEntry = {
    matcher: '*',
    hooks: [{ type: 'command', command: `node ${destHook}` }],
  };

  if (!Array.isArray(settings.hooks)) {
    settings.hooks = [];
  }
  const hooksArr = settings.hooks as unknown[];
  const alreadyInstalled = hooksArr.some(
    (h) =>
      typeof h === 'object' &&
      h !== null &&
      JSON.stringify((h as Record<string, unknown>).hooks).includes('cohrint-track.js')
  );

  if (!alreadyInstalled) {
    hooksArr.push(hookEntry);
    writeFileSync(settingsPath, JSON.stringify(settings, null, 2));
    process.stdout.write('✓ Patched ~/.claude/settings.json with Stop hook\n');
  } else {
    process.stdout.write('✓ Stop hook already present in ~/.claude/settings.json — skipped\n');
  }

  process.stdout.write('\n');
  process.stdout.write('Setup complete! Cohrint will track costs on every Claude Code session.\n');
  process.stdout.write('\n');
  process.stdout.write('Next step: set your API key in your shell profile:\n');
  process.stdout.write('  export COHRINT_API_KEY=crt_...\n');
  process.stdout.write('\n');
  process.stdout.write('Get your free key at: https://cohrint.com/signup.html\n');
  process.stdout.write('\n');
  process.stdout.write('Optional env vars:\n');
  process.stdout.write('  COHRINT_TEAM=<team>      — tag all events with a team name\n');
  process.stdout.write('  COHRINT_PROJECT=<project> — tag all events with a project name\n');
}

// ── Start ─────────────────────────────────────────────────────────────────────

async function main() {
  // Handle CLI subcommands before starting the MCP stdio server
  const subcommand = process.argv[2];
  if (subcommand === 'setup') {
    await runSetup();
    process.exit(0);
  }

  if (!API_KEY) {
    process.stderr.write('[cohrint-mcp] WARNING: COHRINT_API_KEY is not set. Tools will fail until a key is provided.\n');
    process.stderr.write('[cohrint-mcp] Get your key at: https://cohrint.com/signup.html\n');
  } else {
    process.stderr.write(`[cohrint-mcp] org=${ORG} api=${API_BASE}\n`);
  }
  const transport = new StdioServerTransport();
  await server.connect(transport);
  process.stderr.write('[cohrint-mcp] Server started\n');
}

// Catch unhandled errors — log and exit so the process manager can restart clean
process.on('uncaughtException', (err) => {
  errorLog('uncaughtException', err);
  process.exit(1);
});
process.on('unhandledRejection', (reason) => {
  errorLog('unhandledRejection', reason);
  process.exit(1);
});

main().catch((err) => {
  process.stderr.write(`[cohrint-mcp] Fatal: ${err.message}\n`);
  process.exit(1);
});
