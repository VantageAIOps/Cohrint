#!/usr/bin/env node

import { createInterface } from "node:readline";
import { VERSION } from "./_version.js";
import { loadConfig, configExists, saveConfig, type VantageConfig } from "./config.js";
import { runSetup } from "./setup.js";
import { getAgent, detectAll, ALL_AGENTS } from "./agents/registry.js";
import type { AgentAdapter } from "./agents/types.js";
import { AgentSession, isAgentCommand } from "./session-mode.js";
import { optimizePrompt } from "./optimizer.js";
import { calculateCost, findCheapest, PRICES } from "./pricing.js";
import { countTokens } from "./optimizer.js";
import { bus } from "./event-bus.js";
import { Tracker } from "./tracker.js";
import { initSession, getSession } from "./session.js";
import { runAgent, runAgentBuffered } from "./runner.js";
import { checkCostAnomaly } from "./anomaly.js";
import {
  printBanner,
  printOptimization,
  printCostSummary,
  printCompareTable,
  printSessionSummary,
  printTip,
  promptLine,
  bold,
  cyan,
  dim,
  green,
  yellow,
  red,
  type CompareResult,
} from "./ui.js";
import { getInlineTip, getRecommendations, formatRecommendations, type SessionMetrics } from "./recommendations.js";

const COST_TIMEOUT_MS = 5000;

// ---------------------------------------------------------------------------
// Dashboard helpers
// ---------------------------------------------------------------------------

function safeNum(v: unknown, fallback = 0): number {
  const n = Number(v);
  return Number.isFinite(n) ? n : fallback;
}

function checkAnomaly(cost: import("./event-bus.js").VantageEvents["cost:calculated"]): void {
  const sess = getSession();
  // Exclude the current prompt from the baseline (it's already added to totalCostUsd)
  const priorTotal = sess.totalCostUsd - cost.costUsd;
  const priorCount = sess.promptCount - 1;
  checkCostAnomaly(cost.costUsd, priorTotal, priorCount);
}

function buildSessionMetrics(): SessionMetrics {
  const sess = getSession();
  return {
    totalInputTokens: sess.totalInputTokens,
    totalOutputTokens: sess.totalOutputTokens,
    totalCachedTokens: sess.totalSavedTokens,
    promptCount: sess.promptCount,
    totalCostUsd: sess.totalCostUsd,
    sessionStartTime: sess.startedAt,
  };
}

function showInlineTip(): void {
  const tip = getInlineTip(buildSessionMetrics());
  if (tip) printTip(tip);
}

async function showDashboardSummary(config: VantageConfig): Promise<void> {
  if (!config.vantageApiKey) {
    console.log(yellow("  No API key configured. Run setup or set VANTAGE_API_KEY."));
    return;
  }
  try {
    const base = config.vantageApiBase || "https://api.vantageaiops.com";
    const headers = {
      "Authorization": `Bearer ${config.vantageApiKey}`,
      "Content-Type": "application/json",
    };

    // Fetch summary + kpis in parallel
    const [summaryRes, kpisRes] = await Promise.all([
      fetch(`${base}/v1/analytics/summary`, { headers, signal: AbortSignal.timeout(10000) }),
      fetch(`${base}/v1/analytics/kpis?period=30`, { headers, signal: AbortSignal.timeout(10000) }),
    ]);

    const summary = summaryRes.ok ? await summaryRes.json().catch(() => null) as Record<string, unknown> | null : null;
    const kpis = kpisRes.ok ? await kpisRes.json().catch(() => null) as Record<string, unknown> | null : null;

    console.log("");
    console.log(bold(cyan("  Dashboard Summary")));
    console.log(dim("  " + "-".repeat(45)));

    if (summary) {
      const todayCost = Number(summary.today_cost_usd ?? 0);
      const mtdCost = Number(summary.mtd_cost_usd ?? 0);
      const todayReqs = Number(summary.today_requests ?? 0);
      const budgetPct = Number(summary.budget_pct ?? 0);
      const budgetUsd = Number(summary.budget_usd ?? 0);

      console.log(`  ${dim("Today spend:")}    ${green("$" + todayCost.toFixed(4))}`);
      console.log(`  ${dim("MTD spend:")}      $${mtdCost.toFixed(4)}`);
      console.log(`  ${dim("Today requests:")} ${todayReqs}`);
      if (budgetUsd > 0) {
        const color = budgetPct > 85 ? red : budgetPct > 60 ? yellow : green;
        console.log(`  ${dim("Budget:")}         ${color(budgetPct + "%")} of $${budgetUsd}`);
      }
    }

    if (kpis) {
      const totalCost = Number(kpis.total_cost_usd ?? 0);
      const totalTokens = Number(kpis.total_tokens ?? 0);
      const totalReqs = Number(kpis.total_requests ?? 0);
      const avgLatency = Number(kpis.avg_latency_ms ?? 0);
      const effScore = Number(kpis.efficiency_score ?? 0);

      console.log(`  ${dim("30d spend:")}      $${totalCost.toFixed(4)}`);
      console.log(`  ${dim("30d tokens:")}     ${totalTokens.toLocaleString()}`);
      console.log(`  ${dim("30d requests:")}   ${totalReqs.toLocaleString()}`);
      console.log(`  ${dim("Avg latency:")}    ${avgLatency.toFixed(0)}ms`);
      console.log(`  ${dim("Efficiency:")}     ${effScore}/100`);
    }

    // Local session stats
    const session = getSession();
    if (session.promptCount > 0) {
      console.log(dim("  " + "-".repeat(45)));
      console.log(`  ${dim("Local session:")}  ${session.promptCount} prompts, $${session.totalCostUsd.toFixed(4)}`);
      if (session.totalSavedTokens > 0) {
        console.log(`  ${dim("Tokens saved:")}   ${green(session.totalSavedTokens.toLocaleString())}`);
      }
    }

    console.log(dim("  " + "-".repeat(45)));
    console.log("");
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    if (msg.includes("timeout") || msg.includes("abort")) {
      console.error(red("  Dashboard request timed out. Check your network or API endpoint."));
    } else {
      console.error(red(`  Failed to fetch dashboard: ${msg}`));
    }
  }
}

async function showBudgetStatus(config: VantageConfig): Promise<void> {
  if (!config.vantageApiKey) {
    console.log(yellow("  No API key configured."));
    return;
  }
  try {
    const base = config.vantageApiBase || "https://api.vantageaiops.com";
    const res = await fetch(`${base}/v1/analytics/summary`, {
      headers: { "Authorization": `Bearer ${config.vantageApiKey}` },
      signal: AbortSignal.timeout(10000),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json().catch(() => null) as Record<string, unknown> | null;
    if (!data) throw new Error("Invalid JSON response from API");

    const budgetUsd = Number(data.budget_usd ?? 0);
    const budgetPct = Number(data.budget_pct ?? 0);
    const mtdCost = Number(data.mtd_cost_usd ?? 0);

    console.log("");
    if (budgetUsd <= 0) {
      console.log(yellow("  No budget set. Configure in dashboard → Settings."));
    } else {
      const remaining = budgetUsd - mtdCost;
      const color = budgetPct > 85 ? red : budgetPct > 60 ? yellow : green;
      console.log(bold("  Budget Status"));
      console.log(`  ${dim("Monthly budget:")} $${budgetUsd.toFixed(2)}`);
      console.log(`  ${dim("MTD spend:")}      $${mtdCost.toFixed(4)}`);
      console.log(`  ${dim("Used:")}           ${color(budgetPct.toFixed(1) + "%")}`);
      console.log(`  ${dim("Remaining:")}      ${remaining > 0 ? green("$" + remaining.toFixed(2)) : red("OVER BUDGET")}`);

      // Budget alerts
      if (budgetPct >= 100) {
        console.log(red("\n  ⚠ OVER BUDGET — spending exceeds monthly limit!"));
      } else if (budgetPct >= 80) {
        console.log(yellow("\n  ⚠ Budget warning — 80% threshold exceeded"));
      }
    }
    console.log("");
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    if (msg.includes("timeout") || msg.includes("abort")) {
      console.error(red("  Budget request timed out. Check your network or API endpoint."));
    } else {
      console.error(red(`  Failed to fetch budget: ${msg}`));
    }
  }
}

// ---------------------------------------------------------------------------
// Arg parser
// ---------------------------------------------------------------------------

/**
 * Known vantage flags consumed locally. All other --flags are forwarded to the agent.
 * Add to this list to prevent a flag from leaking into the agent command.
 */
const VANTAGE_FLAGS = new Set([
  "agent", "no-optimize", "timeout", "model", "system",
  "debug", "paste-delay",
]);

function parseArgs() {
  const args = process.argv.slice(2);
  const flags: Record<string, string> = {};
  const agentFlags: string[] = []; // unknown flags forwarded verbatim to the agent
  const positional: string[] = [];
  for (let i = 0; i < args.length; i++) {
    if (args[i].startsWith("--")) {
      const key = args[i].slice(2);
      const val =
        args[i + 1] && !args[i + 1].startsWith("--") ? args[i + 1] : "true";
      if (VANTAGE_FLAGS.has(key)) {
        flags[key] = val;
      } else {
        // Unknown flag — forward to agent (e.g. --web-search, --memory, --permissions)
        agentFlags.push(args[i]);
        if (val !== "true") agentFlags.push(val);
      }
      if (val !== "true") i++;
    } else {
      positional.push(args[i]);
    }
  }
  return { flags, agentFlags, positional, prompt: positional.join(" ") };
}

// ---------------------------------------------------------------------------
// Core execution logic
// ---------------------------------------------------------------------------

function looksLikeStructuredData(text: string): boolean {
  // Skip optimization for JSON, code blocks, URLs-heavy content
  const trimmed = text.trim();
  if (trimmed.startsWith("{") || trimmed.startsWith("[")) return true; // JSON
  if (trimmed.startsWith("```")) return true; // code block
  if ((text.match(/https?:\/\//g) || []).length > 2) return true; // URL-heavy
  if ((text.match(/[{}()\[\];=<>]/g) || []).length > text.length * 0.1) return true; // code-like
  return false;
}

async function executePrompt(
  prompt: string,
  agent: AgentAdapter,
  config: VantageConfig,
  stream: boolean = true,
  continueConversation: boolean = false,
  sessionId?: string,
  noOptimize: boolean = false,
  extraFlags: string[] = [],
  timeoutMs?: number,
): Promise<string | undefined> {
  bus.emit("prompt:submitted", {
    prompt,
    agent: agent.name,
    timestamp: Date.now(),
  });

  // Optimize prompt (skip for structured data, or when --no-optimize is set)
  let finalPrompt = prompt;
  if (!noOptimize && config.optimization.enabled && !looksLikeStructuredData(prompt)) {
    const result = optimizePrompt(prompt);
    if (result.savedTokens > 0) {
      finalPrompt = result.optimized;
      bus.emit("prompt:optimized", {
        original: result.original,
        optimized: result.optimized,
        savedTokens: result.savedTokens,
        savedPercent: result.savedPercent,
      });
      printOptimization(result);
    }
  }

  // Build command — use continue if this is a follow-up prompt
  const agentConfig = extraFlags.length > 0 ? { extraFlags } as import("./agents/types.js").AgentConfig : undefined;
  const useContinue = continueConversation && agent.supportsContinue && agent.buildContinueCommand;
  const spawnArgs = useContinue
    ? agent.buildContinueCommand!(finalPrompt, agentConfig, sessionId)
    : agent.buildCommand(finalPrompt, agentConfig);

  try {
    const result = stream
      ? await runAgent(spawnArgs, agent.name, timeoutMs)
      : await runAgentBuffered(spawnArgs, agent.name, timeoutMs);
    return result.sessionId;
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    console.error(red(`  Error running ${agent.displayName}: ${message}`));
    console.error(dim(`  Make sure '${agent.binary}' is installed and in your PATH.`));
    return undefined;
  }
}

function waitForCost(): Promise<import("./event-bus.js").VantageEvents["cost:calculated"] | null> {
  return new Promise((resolve) => {
    let settled = false;
    const handler = (data: import("./event-bus.js").VantageEvents["cost:calculated"]) => {
      if (!settled) {
        settled = true;
        resolve(data);
      }
    };
    bus.once("cost:calculated", handler);
    // Auto-remove the listener after the cost timeout so it never leaks.
    setTimeout(() => {
      if (!settled) {
        settled = true;
        bus.off("cost:calculated", handler);
        resolve(null);
      }
    }, COST_TIMEOUT_MS);
  });
}

// ---------------------------------------------------------------------------
// Compare mode: run prompt across multiple agents
// ---------------------------------------------------------------------------

async function runCompare(
  prompt: string,
  config: VantageConfig
): Promise<void> {
  const detected = await detectAll();
  const available = detected.filter((d) => d.detected);

  if (available.length < 2) {
    console.log(yellow("  Need at least 2 agents installed for /compare."));
    return;
  }

  console.log(dim(`  Running prompt across ${available.length} agents...\n`));

  const results: CompareResult[] = [];

  // Run agents sequentially to avoid terminal interleaving
  for (const { agent } of available) {
    console.log(dim(`  Running ${agent.displayName}...`));
    const spawnArgs = agent.buildCommand(prompt);
    try {
      const result = await runAgentBuffered(spawnArgs, agent.name);
      const model = agent.defaultModel;
      const outputTokens = countTokens(result.stdout);
      const inputTokens = countTokens(prompt);
      const costUsd = calculateCost(model, inputTokens, outputTokens);

      results.push({
        agent: agent.name,
        model,
        durationMs: result.durationMs,
        outputTokens,
        costUsd,
        output: result.stdout.slice(0, 500),
      });
    } catch {
      console.log(red(`  ${agent.displayName} failed.`));
    }
  }

  printCompareTable(results);
}

// ---------------------------------------------------------------------------
// REPL mode
// ---------------------------------------------------------------------------

async function startRepl(config: VantageConfig, replFlags: Record<string, string> = {}): Promise<void> {
  printBanner();

  let currentAgent = getAgent(config.defaultAgent) ?? ALL_AGENTS[0];
  let activeSession: AgentSession | null = null;

  // Track per-agent prompt count and session ID for --resume support
  const agentPromptCount = new Map<string, number>();
  const agentSessionIds = new Map<string, string>();

  const rl = createInterface({
    input: process.stdin,
    output: process.stdout,
  });

  rl.on("error", (err) => {
    // Ignore EPIPE and EIO — these happen when terminal closes
    if ((err as NodeJS.ErrnoException).code === "EPIPE" || (err as NodeJS.ErrnoException).code === "EIO") return;
    console.error(red(`  Terminal error: ${err.message}`));
  });

  // Multi-line paste detection: buffer lines that arrive rapidly, then join on pause.
  // Configurable via --paste-delay <ms> flag or VANTAGE_PASTE_DELAY env var (default 80ms).
  const PASTE_DELAY_MS = replFlags["paste-delay"]
    ? Number(replFlags["paste-delay"])
    : Number(process.env.VANTAGE_PASTE_DELAY) || 80;
  let pasteBuffer: string[] = [];
  let pasteTimer: ReturnType<typeof setTimeout> | null = null;
  let handleLine: ((combined: string) => void) | null = null;

  function onLineReceived(raw: string) {
    pasteBuffer.push(raw);
    if (pasteTimer) clearTimeout(pasteTimer);
    pasteTimer = setTimeout(() => {
      const combined = pasteBuffer.join("\n").trim();
      pasteBuffer = [];
      pasteTimer = null;
      if (handleLine) handleLine(combined);
    }, PASTE_DELAY_MS);
  }

  const prompt = () => {
    process.stdout.write(promptLine(currentAgent.name));
    handleLine = async (input: string) => {
      const line = input.trim();

      if (!line) {
        prompt();
        return;
      }

      try {
        // Special commands
        if (line === "/quit" || line === "/exit" || line === "/q") {
          await shutdown();
          return;
        }

        if (line === "/help") {
          printHelp();
          prompt();
          return;
        }

        if (line === "/cost") {
          const session = getSession();
          printSessionSummary(session);
          prompt();
          return;
        }

        if (line === "/summary" || line === "/stats") {
          await showDashboardSummary(config);
          prompt();
          return;
        }

        if (line === "/budget") {
          await showBudgetStatus(config);
          prompt();
          return;
        }

        if (line === "/tips") {
          const metrics = buildSessionMetrics();
          const tips = getRecommendations(metrics);
          if (tips.length > 0) {
            console.log(formatRecommendations(tips));
          } else {
            console.log(dim("  No recommendations yet — keep prompting!"));
          }
          prompt();
          return;
        }

        if (line === "/setup") {
          // Close REPL readline to avoid stdin conflict with setup's readline
          rl.close();
          try {
            const newConfig = await runSetup();
            // Update config in-place so all references see new values
            Object.assign(config, newConfig);
            // Reinitialize tracker with new config
            if (tracker) tracker.stop();
            tracker = new Tracker({
              apiKey: config.vantageApiKey,
              apiBase: config.vantageApiBase,
              batchSize: config.tracking.batchSize,
              flushInterval: config.tracking.flushInterval,
              privacy: config.privacy,
              debug: false,
            });
            if (config.tracking.enabled) tracker.start();
            // Update current agent if changed
            const newAgent = getAgent(config.defaultAgent);
            if (newAgent) currentAgent = newAgent;
            console.log(green("  Config reloaded. REPL restarting...\n"));
          } catch (err) {
            const msg = err instanceof Error ? err.message : String(err);
            console.error(red(`  Setup failed: ${msg}`));
          }
          // Restart REPL with fresh readline
          await startRepl(config);
          return;
        }

        if (line === "/session" || line.startsWith("/session ")) {
          const sessionAgent = line.includes(" ")
            ? getAgent(line.split(" ")[1]) ?? currentAgent
            : currentAgent;

          activeSession = new AgentSession(sessionAgent);
          const started = await activeSession.start();

          if (!started || !activeSession.isActive()) {
            activeSession = null;
            prompt();
            return;
          }

          // Enter session sub-REPL with proper termination guard
          let sessionExiting = false;
          const sessionPrompt = () => {
            if (sessionExiting || !activeSession?.isActive()) {
              // Session ended (agent crashed or exited) — return to main REPL
              if (!sessionExiting) {
                sessionExiting = true;
                activeSession = null;
                console.log(dim("  Session ended. Returned to VantageAI REPL."));
              }
              prompt();
              return;
            }
            // Print newline before prompt — ensures we're on a fresh line even if
            // the agent's last output didn't include a trailing newline
            process.stdout.write("\n" + cyan(`  ${sessionAgent.name}> `));
            handleLine = async (sessionInput: string) => {
              try {
                const sLine = sessionInput.trim();
                if (!sLine) { sessionPrompt(); return; }

                if (sLine === "/exit-session" || sLine === "/exit") {
                  sessionExiting = true;
                  await activeSession?.end();
                  activeSession = null;
                  console.log(dim("  Returned to VantageAI REPL."));
                  prompt();
                  return;
                }

                if (activeSession?.isActive()) {
                  const processed = await activeSession.sendLine(sLine);
                  if (processed?.type === "vantage-command") {
                    // Handle vantage commands internally
                    const cmd = sLine.trim().toLowerCase();
                    if (cmd === "/cost" || cmd === "/summary" || cmd === "/stats") {
                      await showDashboardSummary(config);
                    } else if (cmd === "/budget") {
                      await showBudgetStatus(config);
                    } else if (cmd === "/help") {
                      printSessionHelp();
                    }
                  }
                  // Use setImmediate to let stdout drain before re-prompting
                  setImmediate(sessionPrompt);
                } else {
                  sessionExiting = true;
                  activeSession = null;
                  console.log(dim("  Session ended unexpectedly. Returned to VantageAI REPL."));
                  prompt();
                }
              } catch (err) {
                const msg = err instanceof Error ? err.message : String(err);
                console.error(red(`  Session error: ${msg}`));
                if (activeSession?.isActive()) {
                  sessionPrompt();
                } else {
                  sessionExiting = true;
                  activeSession = null;
                  prompt();
                }
              }
            };
          };

          sessionPrompt();
          return;
        }

        if (line.startsWith("/default ")) {
          const name = line.slice(9).trim();
          const agent = getAgent(name);
          if (agent) {
            currentAgent = agent;
            console.log(green(`  Default agent set to ${agent.displayName}`));
          } else {
            console.log(red(`  Unknown agent: ${name}`));
            console.log(dim(`  Available: ${ALL_AGENTS.map((a) => a.name).join(", ")}`));
          }
          prompt();
          return;
        }

        if (line.startsWith("/compare ")) {
          const comparePrompt = line.slice(9).trim();
          if (comparePrompt) {
            await runCompare(comparePrompt, config);
          } else {
            console.log(yellow("  Usage: /compare <prompt>"));
          }
          prompt();
          return;
        }

        // Agent prefix commands: /claude, /gemini, /codex, /aider, /chatgpt, etc.
        const agentPrefixMatch = line.match(/^\/(\w+)\s+([\s\S]+)$/);
        if (agentPrefixMatch) {
          const [, agentName, rawAgentPrompt] = agentPrefixMatch;
          const agentPrompt = rawAgentPrompt.trim();
          const agent = getAgent(agentName);
          if (agent && agentPrompt) {
            const costPromise = waitForCost();
            const count = agentPromptCount.get(agent.name) ?? 0;
            const sid = await executePrompt(agentPrompt, agent, config, true, count > 0, agentSessionIds.get(agent.name));
            agentPromptCount.set(agent.name, count + 1);
            if (sid) { agentSessionIds.set(agent.name, sid); } else { agentSessionIds.delete(agent.name); }
            try {
              const cost = await Promise.race([
                costPromise,
                new Promise<null>((resolve) => setTimeout(() => resolve(null), COST_TIMEOUT_MS)),
              ]);
              if (cost) {
                printCostSummary(cost, getSession());
                checkAnomaly(cost);
                showInlineTip();
              }
            } catch {
              // Cost calculation may not fire for all agents
            }
          } else if (!agent) {
            console.log(red(`  Unknown agent: ${agentName}`));
          }
          prompt();
          return;
        }

        // Switch agent without prompt (just /claude, /gemini, etc.)
        const switchMatch = line.match(/^\/(\w+)$/);
        if (switchMatch) {
          const agent = getAgent(switchMatch[1]);
          if (agent) {
            currentAgent = agent;
            console.log(green(`  Switched to ${agent.displayName}`));
          }
          prompt();
          return;
        }

        // Detect agent commands used outside session mode
        if (line.startsWith("/") && !line.startsWith("/compare") && !line.startsWith("/default")) {
          const cmd = line.split(/\s/)[0].toLowerCase();
          if (isAgentCommand(currentAgent.name, line)) {
            console.log(yellow(`  '${cmd}' is a ${currentAgent.displayName} command.`));
            console.log(dim(`  Use /session to start an interactive session with agent commands.`));
            prompt();
            return;
          }
        }

        // Normal prompt — use current default agent
        const costPromise = waitForCost();
        const count = agentPromptCount.get(currentAgent.name) ?? 0;
        const sid = await executePrompt(line, currentAgent, config, true, count > 0, agentSessionIds.get(currentAgent.name));
        agentPromptCount.set(currentAgent.name, count + 1);
        // Always update the session ID map — clear stale ID if sid is undefined so
        // the next prompt doesn't try to resume a session that no longer applies
        if (sid) {
          agentSessionIds.set(currentAgent.name, sid);
        } else {
          agentSessionIds.delete(currentAgent.name);
        }
        try {
          const cost = await Promise.race([
            costPromise,
            new Promise<null>((resolve) => setTimeout(() => resolve(null), COST_TIMEOUT_MS)),
          ]);
          if (cost) {
            printCostSummary(cost, getSession());
            checkAnomaly(cost);
            showInlineTip();
          }
        } catch {
          // Cost calculation may not fire for all agents
        }

        prompt();
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        console.error(red(`  Error: ${msg}`));
        prompt();
      }
    };
  };

  const shutdown = async () => {
    // Cancel any pending paste timer to prevent it firing after REPL closes
    if (pasteTimer) {
      clearTimeout(pasteTimer);
      pasteTimer = null;
    }
    if (pasteBuffer.length > 0) {
      console.warn(`[vantage] Discarded ${pasteBuffer.length} buffered lines on exit`);
      pasteBuffer = [];
    }
    // Clean up active session first
    if (activeSession?.isActive()) {
      await activeSession.end().catch(() => {});
      activeSession = null;
    }
    rl.close();
    await tracker?.flush().catch(() => {});
    printSessionSummary(getSession());
    process.exit(0);
  };

  // Wire readline 'line' events through paste-detection buffer
  rl.on("line", onLineReceived);

  // Handle Ctrl+C, SIGTERM, and SIGHUP — clean up session + tracker before exit
  rl.on("SIGINT", () => { shutdown().catch(() => process.exit(1)); });
  process.on("SIGTERM", () => { shutdown().catch(() => process.exit(1)); });
  process.on("SIGHUP", () => { shutdown().catch(() => process.exit(1)); });

  prompt();
}

function printHelp(): void {
  console.log("");
  console.log(bold("  VantageAI CLI Commands"));
  console.log(dim("  " + "-".repeat(50)));
  console.log(`  ${cyan("/claude <prompt>")}    Run prompt with Claude Code`);
  console.log(`  ${cyan("/gemini <prompt>")}    Run prompt with Gemini CLI`);
  console.log(`  ${cyan("/codex <prompt>")}     Run prompt with Codex CLI`);
  console.log(`  ${cyan("/aider <prompt>")}     Run prompt with Aider`);
  console.log(`  ${cyan("/chatgpt <prompt>")}   Run prompt with ChatGPT CLI`);
  console.log(`  ${cyan("/compare <prompt>")}   Compare all agents side by side`);
  console.log(`  ${cyan("/cost")}               Show session cost summary`);
  console.log(`  ${cyan("/summary")}              Dashboard summary (spend, tokens, budget)`);
  console.log(`  ${cyan("/budget")}               Check budget status and alerts`);
  console.log(`  ${cyan("/tips")}                Show cost-saving recommendations`);
  console.log(`  ${cyan("/session [agent]")}   Start interactive session (supports /compact, /clear, @file, !shell)`);
  console.log(`  ${cyan("/exit-session")}      Return to VantageAI REPL from session`);
  console.log(`  ${cyan("/default <agent>")}    Set default agent`);
  console.log(`  ${cyan("/setup")}              Run setup wizard (API key, agent, privacy)`);
  console.log(`  ${cyan("/help")}               Show this help`);
  console.log(`  ${cyan("/quit")}               Exit VantageAI CLI`);
  console.log("");
  console.log(dim("  Or just type a prompt to use the current default agent."));
  console.log("");
}

function printSessionHelp(): void {
  console.log("");
  console.log(bold("  Session Commands"));
  console.log(dim("  " + "-".repeat(55)));
  console.log(bold("  Optimization:"));
  console.log(`  ${cyan("/opt-auto")}          Optimize prompts ≥5 words (default)`);
  console.log(`  ${cyan("/opt-off")}           Disable optimization entirely`);
  console.log(`  ${cyan("/opt-ask")}           Ask before each optimization`);
  console.log(`  ${cyan("/opt-always")}        Optimize everything`);
  console.log(bold("  Dashboard:"));
  console.log(`  ${cyan("/cost")}              Show session cost & savings`);
  console.log(`  ${cyan("/summary")}           Dashboard stats from API`);
  console.log(`  ${cyan("/budget")}            Budget status & alerts`);
  console.log(bold("  Session:"));
  console.log(`  ${cyan("/exit-session")}      Return to VantageAI REPL`);
  console.log(`  ${cyan("/help")}              Show this help`);
  console.log("");
  console.log(dim("  Agent commands pass through directly:"));
  console.log(dim("    /compact, /clear, /diff, /mcp, @file, !shell, y, n, 1, 2, paths"));
  console.log("");
  console.log(dim("  The agent's stderr is inherited — file approval prompts,"));
  console.log(dim("  git confirmations, and MCP dialogs show directly to you."));
  console.log("");
}

// ---------------------------------------------------------------------------
// Pipe mode: read from stdin
// ---------------------------------------------------------------------------

async function readStdin(): Promise<string> {
  const MAX_STDIN_BYTES = 1024 * 1024; // 1MB max prompt from pipe
  const chunks: Buffer[] = [];
  let totalBytes = 0;

  // Timeout: configurable via VANTAGE_STDIN_TIMEOUT (ms), default 30s
  const stdinTimeoutMs = Number(process.env.VANTAGE_STDIN_TIMEOUT) || 30_000;
  const timeout = setTimeout(() => {
    process.stdin.destroy();
  }, stdinTimeoutMs);

  try {
    for await (const chunk of process.stdin) {
      const buf = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
      totalBytes += buf.length;
      if (totalBytes > MAX_STDIN_BYTES) {
        clearTimeout(timeout);
        console.error(dim("  Warning: prompt truncated at 1MB"));
        break;
      }
      chunks.push(buf);
    }
  } catch {
    // stdin destroyed by timeout or encoding error
  }
  clearTimeout(timeout);

  if (chunks.length === 0) return "";
  return Buffer.concat(chunks).toString("utf-8").trim();
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

let tracker: Tracker | null = null;

async function main(): Promise<void> {
  const { flags, agentFlags, prompt: cliPrompt } = parseArgs();

  // Load or create config
  let config: VantageConfig;
  if (configExists()) {
    config = loadConfig();
  } else {
    // Check if we're in a pipe — skip setup wizard
    if (!process.stdin.isTTY) {
      config = loadConfig(); // Returns defaults
    } else {
      config = await runSetup();
    }
  }

  // Override agent from flag
  const agentName = flags.agent ?? config.defaultAgent;
  const agent = getAgent(agentName) ?? ALL_AGENTS[0];

  // Build extra flags for the agent from named flags + unknown passthrough flags
  const extraAgentFlags: string[] = [...agentFlags];
  if (flags.model) extraAgentFlags.push("--model", flags.model);
  if (flags.system) extraAgentFlags.push("--system", flags.system);
  const noOptimize = flags["no-optimize"] === "true";
  const timeoutMs = flags.timeout ? Number(flags.timeout) : undefined;

  // Initialize session and tracker
  initSession();

  tracker = new Tracker({
    apiKey: config.vantageApiKey,
    apiBase: config.vantageApiBase,
    batchSize: config.tracking.batchSize,
    flushInterval: config.tracking.flushInterval,
    privacy: config.privacy,
    debug: flags.debug === "true",
  });

  if (config.tracking.enabled) {
    tracker.start();
  }

  // Mode 1: One-shot with CLI prompt
  if (cliPrompt) {
    const costPromise = waitForCost();
    await executePrompt(cliPrompt, agent, config, true, false, undefined, noOptimize, extraAgentFlags, timeoutMs);
    try {
      const cost = await Promise.race([
        costPromise,
        new Promise<null>((resolve) => setTimeout(() => resolve(null), COST_TIMEOUT_MS)),
      ]);
      if (cost) {
        printCostSummary(cost, getSession());
        checkAnomaly(cost);
        showInlineTip();
      }
    } catch {
      // Cost may not be available
    }
    // Wait for tracker to drain before exit to avoid dropped events
    await tracker.flush().catch(() => {});
    await new Promise<void>((resolve) => setTimeout(resolve, 2000));
    process.exit(0);
  }

  // Mode 2: Pipe mode
  if (!process.stdin.isTTY) {
    const stdinPrompt = await readStdin();
    if (!stdinPrompt || stdinPrompt.trim() === "") {
      process.exit(0);
    }
    if (stdinPrompt) {
      const costPromise = waitForCost();
      await executePrompt(stdinPrompt, agent, config, true, false, undefined, noOptimize, extraAgentFlags, timeoutMs);
      try {
        const cost = await Promise.race([
          costPromise,
          new Promise<null>((resolve) => setTimeout(() => resolve(null), COST_TIMEOUT_MS)),
        ]);
        if (cost) {
          printCostSummary(cost, getSession());
          checkAnomaly(cost);
          showInlineTip();
        }
      } catch {
        // Cost may not be available
      }
    }
    await tracker.flush().catch(() => {});
    await new Promise<void>((resolve) => setTimeout(resolve, 2000));
    process.exit(0);
  }

  // Mode 3: REPL
  await startRepl(config, flags);
}

function isNewerVersion(latest: string, current: string): boolean {
  const parse = (v: string) => v.split('.').map(Number);
  const [lMaj, lMin, lPat] = parse(latest);
  const [cMaj, cMin, cPat] = parse(current);
  if (lMaj !== cMaj) return lMaj > cMaj;
  if (lMin !== cMin) return lMin > cMin;
  return lPat > cPat;
}

async function checkForUpdate(): Promise<void> {
  try {
    const current = VERSION;
    const res = await fetch("https://registry.npmjs.org/vantageai-cli/latest",
      { signal: AbortSignal.timeout(2000) });
    if (!res.ok) return;
    const data = await res.json().catch(() => null);
    if (!data || typeof data !== 'object') return;
    const version = (data as { version?: string }).version;
    if (!version) return;
    if (isNewerVersion(version, current)) {
      console.error(yellow(`\n  Update available: vantageai-cli ${current} → ${version}`));
      console.error(dim(`  Run: npm install -g vantageai-cli\n`));
    }
  } catch { /* silent — never block the CLI */ }
}

main().catch((err) => {
  console.error(red(`Fatal error: ${err instanceof Error ? err.message : String(err)}`));
  process.exit(1);
});

// Fire-and-forget — does not block startup
checkForUpdate();

process.on("unhandledRejection", (reason) => {
  const msg = reason instanceof Error ? reason.message : String(reason);
  console.error(red(`  Unhandled error: ${msg}`));
  // In non-interactive mode, exit — can't recover without a REPL
  if (!process.stdin.isTTY) {
    process.exit(1);
  }
});
