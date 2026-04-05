#!/usr/bin/env node
/**
 * CLI entry point for VantageAI Local Proxy.
 *
 * Usage:
 *   vantage-proxy                                # proxy mode (default)
 *   vantage-proxy scan                           # scan all local AI tool sessions
 *   vantage-proxy scan --tool claude-code         # scan specific tool
 *   vantage-proxy scan --since 2026-03-01         # filter by date
 *   vantage-proxy scan --json                     # output raw JSON
 *   vantage-proxy scan --push                     # scan + push to VantageAI API
 *   vantage-proxy --port 4891 --privacy strict    # proxy with options
 *   VANTAGE_API_KEY=vnt_... vantage-proxy
 */

import { readFile, writeFile } from "node:fs/promises";
import { homedir } from "node:os";
import { join } from "node:path";
import { startProxyServer } from "./proxy-server.js";
import { scanAll, ALL_SCANNERS } from "./scanners/index.js";
import type { PrivacyLevel } from "./privacy.js";
import type { ToolName, ScanResult } from "./scanners/types.js";

function parseArgs(): Record<string, string> {
  const args: Record<string, string> = {};
  const argv = process.argv.slice(2);
  for (let i = 0; i < argv.length; i++) {
    if (argv[i].startsWith("--")) {
      const key = argv[i].slice(2);
      const val = argv[i + 1] && !argv[i + 1].startsWith("--") ? argv[i + 1] : "true";
      args[key] = val;
      if (val !== "true") i++;
    } else if (!args._command) {
      args._command = argv[i];
    }
  }
  return args;
}

const args = parseArgs();
const command = args._command ?? "";

// ── SCAN command ─────────────────────────────────────────────────────────────

if (command === "scan") {
  runScan().catch((err) => {
    console.error("Scan failed:", err);
    process.exit(1);
  });
} else {
  // ── PROXY command (default) ──────────────────────────────────────────────

  const vantageApiKey = args["api-key"] ?? process.env.VANTAGE_API_KEY ?? "";
  if (!vantageApiKey) {
    console.error(`
ERROR: VANTAGE_API_KEY is required.

Set it via environment variable or --api-key flag:

  export VANTAGE_API_KEY=vnt_yourorg_abc123
  vantage-proxy

  # or
  vantage-proxy --api-key vnt_yourorg_abc123

Get your key at: https://vantageaiops.com/signup.html

TIP: Use "vantage-proxy scan" to scan local AI tool sessions (no API key needed).
`);
    process.exit(1);
  }

  const privacyLevel = (args["privacy"] ?? process.env.VANTAGE_PRIVACY ?? "strict") as PrivacyLevel;
  if (!["strict", "standard", "relaxed"].includes(privacyLevel)) {
    console.error(`Invalid privacy level: ${privacyLevel}. Use: strict | standard | relaxed`);
    process.exit(1);
  }

  startProxyServer({
    port: parseInt(args["port"] ?? process.env.VANTAGE_PROXY_PORT ?? "4891", 10),
    vantageApiKey,
    vantageApiBase: args["api-base"] ?? process.env.VANTAGE_API_BASE ?? "https://api.vantageaiops.com",
    privacy: {
      level: privacyLevel,
      redactModelNames: args["redact-models"] === "true",
    },
    team: args["team"] ?? process.env.VANTAGE_TEAM ?? "",
    environment: args["env"] ?? process.env.VANTAGE_ENV ?? "production",
    debug: args["debug"] === "true" || process.env.VANTAGE_DEBUG === "true",
    batchSize: parseInt(args["batch-size"] ?? "20", 10),
    flushInterval: parseInt(args["flush-interval"] ?? "5000", 10),
  });
}

// ── Scan implementation ──────────────────────────────────────────────────────

async function runScan(): Promise<void> {
  const toolFilter = args["tool"] as ToolName | undefined;
  const tools = toolFilter ? [toolFilter] : undefined;
  const jsonOutput = args["json"] === "true";
  const pushToApi = args["push"] === "true";
  const since = args["since"];
  const until = args["until"];
  const limit = args["limit"] ? parseInt(args["limit"], 10) : undefined;

  if (!jsonOutput) {
    console.log("\n  VantageAI Local File Scanner");
    console.log("  Scanning local AI tool sessions...\n");

    // Show which tools we're looking for
    const scanners = tools
      ? ALL_SCANNERS.filter((s) => tools.includes(s.name))
      : ALL_SCANNERS;
    for (const s of scanners) {
      process.stdout.write(`  Checking ${s.displayName.padEnd(15)} `);
      const found = await s.detect();
      console.log(found ? "FOUND" : "not found");
    }
    console.log();
  }

  const result = await scanAll({ tools, since, until, limit });

  if (jsonOutput) {
    console.log(JSON.stringify(result, null, 2));
    return;
  }

  printScanReport(result);

  // Push to VantageAI API if requested
  if (pushToApi) {
    const apiKey = args["api-key"] ?? process.env.VANTAGE_API_KEY ?? "";
    if (!apiKey) {
      console.error("\n  ERROR: --push requires VANTAGE_API_KEY to be set.\n");
      process.exit(1);
    }
    await pushScanResults(result, apiKey, args["api-base"] ?? process.env.VANTAGE_API_BASE ?? "https://api.vantageaiops.com");
  }
}

function printScanReport(result: ScanResult): void {
  const { totals, byTool, toolsFound, errors, durationMs } = result;

  if (toolsFound.length === 0) {
    console.log("  No AI tool session data found on this machine.\n");
    console.log("  Supported tools:");
    for (const s of ALL_SCANNERS) {
      console.log(`    - ${s.displayName}: ${s.description}`);
    }
    console.log();
    return;
  }

  // Header
  console.log("  ┌─────────────────────────────────────────────────────────────┐");
  console.log("  │                    SCAN RESULTS                             │");
  console.log("  ├─────────────────────────────────────────────────────────────┤");
  console.log(`  │  Tools found:     ${toolsFound.join(", ").padEnd(41)}│`);
  console.log(`  │  Total sessions:  ${String(totals.totalSessions).padEnd(41)}│`);
  console.log(`  │  Total turns:     ${String(totals.totalTurns).padEnd(41)}│`);
  console.log(`  │  Total tokens:    ${formatTokens(totals.totalInputTokens + totals.totalOutputTokens).padEnd(41)}│`);
  console.log(`  │  Total cost:      $${totals.totalCostUsd.toFixed(4).padEnd(40)}│`);
  console.log(`  │  Scan time:       ${durationMs}ms${" ".repeat(Math.max(0, 38 - String(durationMs).length))}│`);
  console.log("  └─────────────────────────────────────────────────────────────┘");
  console.log();

  // Per-tool breakdown
  console.log("  Per-tool breakdown:");
  console.log("  ─────────────────────────────────────────────────────────────");

  for (const [toolName, summary] of Object.entries(byTool)) {
    const scanner = ALL_SCANNERS.find((s) => s.name === toolName);
    const displayName = scanner?.displayName ?? toolName;
    console.log(`\n  ${displayName}`);
    console.log(`    Sessions:    ${summary.sessions}`);
    console.log(`    Turns:       ${summary.turns}`);
    console.log(`    Input:       ${formatTokens(summary.inputTokens)} tokens`);
    console.log(`    Output:      ${formatTokens(summary.outputTokens)} tokens`);
    console.log(`    Cost:        $${summary.costUsd.toFixed(4)}`);
    console.log(`    Models:      ${summary.models.join(", ")}`);
    console.log(`    Date range:  ${summary.oldestSession.slice(0, 10)} → ${summary.newestSession.slice(0, 10)}`);
  }

  // Top 10 most expensive sessions
  const topSessions = result.sessions
    .filter((s) => s.totalCostUsd > 0)
    .sort((a, b) => b.totalCostUsd - a.totalCostUsd)
    .slice(0, 10);

  if (topSessions.length > 0) {
    console.log("\n\n  Top 10 most expensive sessions:");
    console.log("  ─────────────────────────────────────────────────────────────");
    console.log("  Tool           Model                Cost     Turns  Date");
    console.log("  ─────────────────────────────────────────────────────────────");
    for (const s of topSessions) {
      const tool = s.tool.padEnd(15);
      const model = s.model.padEnd(20).slice(0, 20);
      const cost = `$${s.totalCostUsd.toFixed(4)}`.padEnd(9);
      const turns = String(s.turnCount).padEnd(6);
      const date = s.startedAt.slice(0, 10);
      console.log(`  ${tool} ${model} ${cost} ${turns} ${date}`);
    }
  }

  // Errors
  if (errors.length > 0) {
    console.log("\n  Warnings:");
    for (const e of errors) {
      console.log(`    [${e.tool}] ${e.file ? e.file + ": " : ""}${e.error}`);
    }
  }

  console.log();
}

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

async function pushScanResults(
  result: ScanResult,
  apiKey: string,
  apiBase: string,
): Promise<void> {
  console.log("  Pushing scan results to VantageAI...");

  // Load dedup state — skip turns already uploaded
  const stateFile = join(homedir(), ".claude", "vantage-state.json");
  let uploadedIds: Set<string> = new Set();
  try {
    const raw = await readFile(stateFile, "utf-8");
    const state = JSON.parse(raw) as { uploadedIds?: string[] };
    uploadedIds = new Set(state.uploadedIds ?? []);
  } catch {
    // First run — state file doesn't exist yet
  }

  // Build one event per assistant turn (per message, not per session)
  const events: Record<string, unknown>[] = [];
  for (const s of result.sessions) {
    for (let i = 0; i < s.messages.length; i++) {
      const m = s.messages[i];
      const eventId = `${s.sessionId}-${m.timestamp}-${i}`;
      if (uploadedIds.has(eventId)) continue;

      events.push({
        event_id:          eventId,
        provider:          s.provider,
        model:             m.model,
        prompt_tokens:     m.inputTokens,
        completion_tokens: m.outputTokens,
        cache_tokens:      m.cacheReadTokens,
        total_tokens:      m.inputTokens + m.outputTokens,
        total_cost_usd:    m.costUsd,
        environment:       "local",
        agent_name:        "claude-code",
        timestamp:         m.timestamp,
        tags:              { tool: s.tool, scanner: "local-file", session: s.sessionId },
      });
    }
  }

  if (events.length === 0) {
    console.log("  Nothing new to upload — all sessions already pushed.\n");
    return;
  }

  console.log(`  Uploading ${events.length} new turns (${result.sessions.length} sessions)...`);

  // Send in batches of 500 (API max)
  const newIds: string[] = [];
  for (let i = 0; i < events.length; i += 500) {
    const batch = events.slice(i, i + 500);
    try {
      const res = await fetch(`${apiBase}/v1/events/batch`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${apiKey}`,
        },
        body: JSON.stringify({
          events: batch,
          sdk_version: "1.0.0",
          sdk_language: "local-scanner",
        }),
      });
      if (res.ok) {
        newIds.push(...batch.map((e) => e.event_id as string));
        console.log(`  Batch ${Math.floor(i / 500) + 1}: ${batch.length} turns → ${res.status}`);
      } else {
        const err = await res.text();
        console.error(`  Batch ${Math.floor(i / 500) + 1} failed: ${res.status} ${err}`);
      }
    } catch (err) {
      console.error(`  Network error on batch ${Math.floor(i / 500) + 1}: ${err}`);
    }
  }

  // Save updated dedup state
  const updated = [...uploadedIds, ...newIds];
  await writeFile(stateFile, JSON.stringify({ uploadedIds: updated, lastUploadAt: new Date().toISOString() }, null, 2));
  console.log(`  Done — uploaded ${newIds.length} turns. State saved to ${stateFile}\n`);
}
