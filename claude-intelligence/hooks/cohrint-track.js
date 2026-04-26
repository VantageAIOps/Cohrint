#!/usr/bin/env node
'use strict';
/**
 * cohrint-track.js — Claude Code cost tracker
 *
 * Reads Claude Code session files from ~/.claude/projects/ and posts token
 * usage + estimated cost to Cohrint for cross-project cost visibility.
 *
 * Setup (one-time): run the setup_claude_hook tool in the Cohrint MCP server.
 *
 * Or manually:
 *   1. Get a free API key at https://cohrint.com
 *   2. Set COHRINT_API_KEY in your shell profile
 *   3. Add this script as a Stop hook in ~/.claude/settings.json
 *
 * Environment variables:
 *   COHRINT_API_KEY   — required; your Cohrint API key
 *   COHRINT_API_BASE  — optional; default https://api.cohrint.com
 *   COHRINT_TEAM      — optional; tag events with a team name
 *   COHRINT_PROJECT   — optional; tag events with a project name
 *   COHRINT_FEATURE   — optional; tag events with a feature name
 *
 * This script is silent on errors — it will never break Claude Code.
 */

const { readdir, readFile, writeFile } = require('node:fs/promises');
const { join } = require('node:path');
const { homedir } = require('node:os');

const API_KEY  = process.env.COHRINT_API_KEY  ?? '';
const API_BASE = normalizeApiBase(process.env.COHRINT_API_BASE ?? 'https://api.cohrint.com');

function normalizeApiBase(raw) {
  const trimmed = String(raw).replace(/\/+$/, '');
  if (/^https:\/\//i.test(trimmed)) return trimmed;
  if (/^http:\/\/(127\.0\.0\.1|localhost)(:\d+)?(\/|$)/i.test(trimmed)) return trimmed;
  // Silent fallback — the hook must never crash Claude Code. Downgrade to the
  // default endpoint rather than refusing to run, but log to stderr once.
  process.stderr.write(
    `[cohrint-track] refusing non-https COHRINT_API_BASE; using default.\n`
  );
  return 'https://api.cohrint.com';
}
const TEAM     = process.env.COHRINT_TEAM     ?? null;
const PROJECT  = process.env.COHRINT_PROJECT  ?? null;
const FEATURE  = process.env.COHRINT_FEATURE  ?? null;

const STATE_FILE = join(homedir(), '.claude', 'cohrint-state.json');

// Token prices per million (USD). input/output/cache = read rate, cacheWrite = creation rate.
const PRICES = {
  'claude-opus-4-6':    { input: 15.00, output: 75.00, cache: 1.50,  cacheWrite: 18.75 },
  'claude-sonnet-4-6':  { input:  3.00, output: 15.00, cache: 0.30,  cacheWrite:  3.75 },
  'claude-haiku-4-5':   { input:  0.80, output:  4.00, cache: 0.08,  cacheWrite:  1.00 },
  'claude-3-5-sonnet':  { input:  3.00, output: 15.00, cache: 0.30,  cacheWrite:  3.75 },
  'claude-3-haiku':     { input:  0.25, output:  1.25, cache: 0.03,  cacheWrite:  0.31 },
  'gpt-4o':             { input:  2.50, output: 10.00, cache: 1.25,  cacheWrite:  2.50 },
  'gpt-4o-mini':        { input:  0.15, output:  0.60, cache: 0.075, cacheWrite:  0.15 },
  'o1':                 { input: 15.00, output: 60.00, cache: 7.50,  cacheWrite: 15.00 },
  'o3-mini':            { input:  1.10, output:  4.40, cache: 0.55,  cacheWrite:  1.10 },
  'gemini-2.0-flash':   { input:  0.10, output:  0.40, cache: 0.025, cacheWrite:  0.10 },
  'gemini-1.5-pro':     { input:  1.25, output:  5.00, cache: 0.31,  cacheWrite:  1.25 },
  'gemini-1.5-flash':   { input: 0.075, output:  0.30, cache: 0.018, cacheWrite:  0.075 },
};

function lookupPrice(model) {
  if (!model) return null;
  if (PRICES[model]) return PRICES[model];
  const lower = model.toLowerCase();
  const key = Object.keys(PRICES).find(k => lower.includes(k) || k.includes(lower));
  return key ? PRICES[key] : null;
}

function calcCost(model, inputTokens, outputTokens, cacheRead, cacheWrite) {
  const p = lookupPrice(model) ?? { input: 3, output: 15, cache: 0.3, cacheWrite: 3.75 };
  // Anthropic's input_tokens already excludes cache_creation_input_tokens but includes cache_read_input_tokens.
  // Only subtract cacheRead to get the non-cached regular input portion.
  const regularInput = Math.max(0, inputTokens - cacheRead);
  return (regularInput  / 1e6) * p.input
       + (cacheRead     / 1e6) * p.cache
       + (cacheWrite    / 1e6) * p.cacheWrite
       + (outputTokens  / 1e6) * p.output;
}

async function loadState() {
  try {
    const raw = await readFile(STATE_FILE, 'utf-8');
    return JSON.parse(raw);
  } catch (err) {
    if (err.code === 'ENOENT') return { uploadedIds: [] };
    process.stderr.write(`[cohrint-track] WARN: state read error: ${err}\n`);
    return { uploadedIds: [] };
  }
}

async function saveState(state) {
  try {
    if (state.uploadedIds && state.uploadedIds.length > 50000) {
      state.uploadedIds = state.uploadedIds.slice(-50000);
    }
    await writeFile(STATE_FILE, JSON.stringify(state, null, 2));
  } catch (err) {
    process.stderr.write(`[cohrint-track] WARN: state write failed: ${err}\n`);
  }
}

async function findProjectFiles(cwd) {
  const slug = cwd.replace(/[^a-zA-Z0-9]/g, '-');
  const dir = join(homedir(), '.claude', 'projects', slug);
  try {
    const entries = await readdir(dir, { withFileTypes: true });
    return entries
      .filter(e => e.isFile() && e.name.endsWith('.jsonl'))
      .map(e => join(dir, e.name));
  } catch {
    return [];
  }
}

async function parseNewMessages(filePath, uploadedIds) {
  let content;
  try { content = await readFile(filePath, 'utf-8'); } catch { return []; }

  const events = [];
  const lines = content.split('\n').filter(l => l.trim());

  for (let i = 0; i < lines.length; i++) {
    let entry;
    try { entry = JSON.parse(lines[i]); } catch { continue; }
    if (entry.type !== 'assistant' || !entry.message?.usage) continue;

    const usage   = entry.message.usage;
    const model   = entry.message.model ?? 'unknown';
    const sid     = entry.sessionId ?? 'unknown';
    const msgUuid = entry.uuid ?? `${sid}-${i}`;
    const eventId = `${sid}-${msgUuid}`;
    if (uploadedIds.has(eventId)) continue;

    const inputTokens  = usage.input_tokens ?? 0;
    const cacheWrite   = usage.cache_creation_input_tokens ?? 0;
    const outputTokens = usage.output_tokens ?? 0;
    const cacheRead    = usage.cache_read_input_tokens ?? 0;

    events.push({
      eventId,
      timestamp: entry.timestamp ?? new Date().toISOString(),
      model,
      inputTokens,
      outputTokens,
      cacheRead,
      cacheWrite,
      payload: {
        event_id:          eventId,
        provider:          'anthropic',
        model,
        prompt_tokens:     inputTokens,
        completion_tokens: outputTokens,
        cache_tokens:      cacheRead,
        total_tokens:      inputTokens + outputTokens,
        total_cost_usd:    calcCost(model, inputTokens, outputTokens, cacheRead, cacheWrite),
        environment:       'local',
        agent_name:        'claude-code',
        timestamp:         entry.timestamp ?? new Date().toISOString(),
        tags:              { tool: 'claude-code', hook: 'stop' },
        team:              TEAM,
        project:           PROJECT,
        feature:           FEATURE,
      },
    });
  }
  return events;
}

/** Build OTLP JSON metrics payload for Cross-Platform Console visibility */
function buildOtelPayload(events) {
  const nowNano = String(Date.now() * 1_000_000);

  // Group by model for per-model datapoints
  const byModel = {};
  for (const e of events) {
    if (!byModel[e.model]) byModel[e.model] = { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 };
    byModel[e.model].input     += e.inputTokens;
    byModel[e.model].output    += e.outputTokens;
    byModel[e.model].cacheRead += e.cacheRead;
    byModel[e.model].cacheWrite += e.cacheWrite;
  }

  const dataPoints = [];
  for (const [model, totals] of Object.entries(byModel)) {
    for (const [type, count] of [
      ['input',  totals.input],
      ['output', totals.output],
      ['cache_read',  totals.cacheRead],
      ['cache_write', totals.cacheWrite],
    ]) {
      if (count === 0) continue;
      dataPoints.push({
        attributes: [
          { key: 'gen_ai.token.type', value: { stringValue: type } },
          { key: 'model',             value: { stringValue: model } },
        ],
        asInt: String(count),
        timeUnixNano: nowNano,
      });
    }
  }

  const resourceAttrs = [
    { key: 'service.name', value: { stringValue: 'claude-code' } },
  ];
  if (TEAM)    resourceAttrs.push({ key: 'team.id',    value: { stringValue: TEAM } });
  if (PROJECT) resourceAttrs.push({ key: 'project.id', value: { stringValue: PROJECT } });

  return {
    resourceMetrics: [{
      resource: { attributes: resourceAttrs },
      scopeMetrics: [{
        scope: { name: 'claude-code', version: '1.0' },
        metrics: [{
          name: 'gen_ai.client.token.usage',
          sum: { dataPoints, isMonotonic: true },
        }],
      }],
    }],
  };
}

async function main() {
  if (!API_KEY) return; // No key = silent no-op

  const state = await loadState();
  const uploadedIds = new Set(state.uploadedIds ?? []);

  const files = await findProjectFiles(process.cwd());
  if (!files.length) return;

  const allNew = [];
  for (const f of files) {
    const msgs = await parseNewMessages(f, uploadedIds);
    allNew.push(...msgs);
  }
  if (!allNew.length) return;

  const ac = new AbortController();
  const timer = setTimeout(() => ac.abort(), 8000);

  try {
    // 1. Post events to /v1/events/batch
    const res = await fetch(`${API_BASE}/v1/events/batch`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${API_KEY}` },
      body: JSON.stringify({
        events: allNew.map(e => e.payload),
        sdk_version: 'hook-1.0',
        sdk_language: 'node-hook',
      }),
      signal: ac.signal,
    });

    if (res.ok) {
      // Update dedup state
      state.uploadedIds = [...(state.uploadedIds ?? []), ...allNew.map(e => e.eventId)];
      state.lastUploadAt = new Date().toISOString();
      await saveState(state);

      // 2. Emit OTel metrics so events appear in Cross-Platform Console
      // Own timeout — fire-and-forget but capped so a hung server can't keep
      // the hook process alive past Claude Code's exit.
      const otelAc = new AbortController();
      const otelTimer = setTimeout(() => otelAc.abort(), 5000);
      const otelPayload = buildOtelPayload(allNew);
      fetch(`${API_BASE}/v1/otel/v1/metrics`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${API_KEY}` },
        body: JSON.stringify(otelPayload),
        signal: otelAc.signal,
      })
        .catch(() => {})
        .finally(() => clearTimeout(otelTimer));

      // 3. Provide feedback on successful upload
      const totalCost = allNew.reduce((s, e) => s + (e.payload.total_cost_usd ?? 0), 0);
      process.stderr.write(
        `[cohrint-track] Tracked ${allNew.length} event(s) — $${totalCost.toFixed(4)} — https://cohrint.com\n`
      );
    }
  } catch {
    // Silent — timeout or network error, never break Claude Code
  } finally {
    clearTimeout(timer);
  }
}

main().catch(() => {}).finally(() => process.exit(0));
