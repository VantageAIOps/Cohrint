#!/usr/bin/env node
'use strict';
/**
 * vantage-track.js — Claude Code cost tracker
 *
 * Reads Claude Code session files from ~/.claude/projects/ and posts token
 * usage + estimated cost to VantageAI for cross-project cost visibility.
 *
 * Setup:
 *   1. Get a free API key at https://vantageaiops.com
 *   2. Set VANTAGE_API_KEY in your shell profile, OR
 *      run install.sh and enter the key when prompted
 *
 * This script is silent on errors — it will never break Claude Code.
 */

const { readdir, readFile, writeFile } = require('node:fs/promises');
const { join } = require('node:path');
const { homedir } = require('node:os');

// Set VANTAGE_API_KEY in your environment — see Setup above
const API_KEY  = process.env.VANTAGE_API_KEY ?? '';
const API_BASE = process.env.VANTAGE_API_BASE ?? 'https://api.vantageaiops.com';
const STATE_FILE = join(homedir(), '.claude', 'vantage-state.json');

// Token prices per million (USD) — update as Anthropic pricing changes
const PRICES = {
  'claude-opus-4-6':   { input: 15.00, output: 75.00, cache: 1.50 },
  'claude-sonnet-4-6': { input:  3.00, output: 15.00, cache: 0.30 },
  'claude-haiku-4-5':  { input:  0.80, output:  4.00, cache: 0.08 },
};

function calcCost(model, inputTokens, outputTokens, cacheRead, cacheWrite) {
  const key = Object.keys(PRICES).find(k => model.includes(k) || k.includes(model));
  const p = key ? PRICES[key] : { input: 3, output: 15, cache: 0.3 };
  return (inputTokens  / 1e6) * p.input
       + (cacheRead    / 1e6) * p.cache
       + (cacheWrite   / 1e6) * p.cache
       + (outputTokens / 1e6) * p.output;
}

function dirToSlug(dir) {
  return dir.replace(/[^a-zA-Z0-9]/g, '-');
}

async function loadState() {
  try {
    const raw = await readFile(STATE_FILE, 'utf-8');
    return JSON.parse(raw);
  } catch (err) {
    if (err.code !== 'ENOENT') process.stderr.write(`[vantage-track] WARN: state read error: ${err}\n`);
    return { uploadedIds: [] };
  }
}

async function saveState(state) {
  try {
    // Cap at 50,000 IDs to prevent unbounded growth
    if (state.uploadedIds && state.uploadedIds.length > 50000) {
      state.uploadedIds = state.uploadedIds.slice(-50000);
    }
    await writeFile(STATE_FILE, JSON.stringify(state, null, 2));
  } catch (err) {
    process.stderr.write(`[vantage-track] WARN: state write failed: ${err}\n`);
  }
}

async function findProjectFiles(cwd) {
  const slug = dirToSlug(cwd);
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
      payload: {
        event_id:          eventId,
        provider:          'anthropic',
        model,
        prompt_tokens:     inputTokens,
        completion_tokens: outputTokens,
        cache_tokens:      cacheRead,
        total_tokens:      inputTokens + outputTokens + cacheWrite,
        total_cost_usd:    calcCost(model, inputTokens, outputTokens, cacheRead, cacheWrite),
        environment:       'local',
        agent_name:        'claude-code',
        timestamp:         entry.timestamp ?? new Date().toISOString(),
        tags:              { tool: 'claude-code', hook: 'stop' },
      },
    });
  }
  return events;
}

async function main() {
  if (!API_KEY) return; // No key = no-op

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
  const timer = setTimeout(() => ac.abort(), 5000);
  try {
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
      state.uploadedIds = [...(state.uploadedIds ?? []), ...allNew.map(e => e.eventId)];
      state.lastUploadAt = new Date().toISOString();
      await saveState(state);
    }
  } catch {
    // Silent — timeout or network error, never break Claude Code
  } finally {
    clearTimeout(timer);
  }
}

main().catch(() => {}).finally(() => process.exit(0));
