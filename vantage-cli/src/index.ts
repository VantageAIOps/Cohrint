#!/usr/bin/env node

import { createInterface } from "node:readline";
import { loadConfig, configExists, type VantageConfig } from "./config.js";
import { runSetup } from "./setup.js";
import { getAgent, detectAll, ALL_AGENTS } from "./agents/registry.js";
import type { AgentAdapter } from "./agents/types.js";
import { optimizePrompt } from "./optimizer.js";
import { calculateCost, findCheapest, PRICES } from "./pricing.js";
import { countTokens } from "./optimizer.js";
import { bus } from "./event-bus.js";
import { Tracker } from "./tracker.js";
import { initSession, getSession } from "./session.js";
import { runAgent, runAgentBuffered } from "./runner.js";
import {
  printBanner,
  printOptimization,
  printCostSummary,
  printCompareTable,
  printSessionSummary,
  promptLine,
  bold,
  cyan,
  dim,
  green,
  yellow,
  red,
  type CompareResult,
} from "./ui.js";

const COST_TIMEOUT_MS = 2000;

// ---------------------------------------------------------------------------
// Arg parser
// ---------------------------------------------------------------------------

function parseArgs() {
  const args = process.argv.slice(2);
  const flags: Record<string, string> = {};
  const positional: string[] = [];
  for (let i = 0; i < args.length; i++) {
    if (args[i].startsWith("--")) {
      const key = args[i].slice(2);
      const val =
        args[i + 1] && !args[i + 1].startsWith("--") ? args[i + 1] : "true";
      flags[key] = val;
      if (val !== "true") i++;
    } else {
      positional.push(args[i]);
    }
  }
  return { flags, positional, prompt: positional.join(" ") };
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
  stream: boolean = true
): Promise<void> {
  bus.emit("prompt:submitted", {
    prompt,
    agent: agent.name,
    timestamp: Date.now(),
  });

  // Optimize prompt (skip for structured data like JSON, code, URL-heavy content)
  let finalPrompt = prompt;
  if (config.optimization.enabled && !looksLikeStructuredData(prompt)) {
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

  // Build and run command
  const spawnArgs = agent.buildCommand(finalPrompt);

  try {
    if (stream) {
      await runAgent(spawnArgs, agent.name);
    } else {
      await runAgentBuffered(spawnArgs, agent.name);
    }
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    console.error(red(`  Error running ${agent.displayName}: ${message}`));
    console.error(dim(`  Make sure '${agent.binary}' is installed and in your PATH.`));
  }
}

function waitForCost(): Promise<import("./event-bus.js").VantageEvents["cost:calculated"]> {
  return new Promise((resolve) => {
    bus.once("cost:calculated", resolve);
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

async function startRepl(config: VantageConfig): Promise<void> {
  printBanner();

  let currentAgent = getAgent(config.defaultAgent) ?? ALL_AGENTS[0];

  const rl = createInterface({
    input: process.stdin,
    output: process.stdout,
  });

  const prompt = () => {
    rl.question(promptLine(currentAgent.name), async (input) => {
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
            await executePrompt(agentPrompt, agent, config);
            try {
              const cost = await Promise.race([
                costPromise,
                new Promise<null>((resolve) => setTimeout(() => resolve(null), COST_TIMEOUT_MS)),
              ]);
              if (cost) {
                printCostSummary(cost, getSession());
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

        // Normal prompt — use current default agent
        const costPromise = waitForCost();
        await executePrompt(line, currentAgent, config);
        try {
          const cost = await Promise.race([
            costPromise,
            new Promise<null>((resolve) => setTimeout(() => resolve(null), COST_TIMEOUT_MS)),
          ]);
          if (cost) {
            printCostSummary(cost, getSession());
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
    });
  };

  const shutdown = async () => {
    rl.close();
    await tracker?.flush();
    printSessionSummary(getSession());
    process.exit(0);
  };

  // Handle Ctrl+C — async-safe shutdown
  rl.on("SIGINT", () => {
    shutdown().then(() => process.exit(0));
  });

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
  console.log(`  ${cyan("/default <agent>")}    Set default agent`);
  console.log(`  ${cyan("/help")}               Show this help`);
  console.log(`  ${cyan("/quit")}               Exit VantageAI CLI`);
  console.log("");
  console.log(dim("  Or just type a prompt to use the current default agent."));
  console.log("");
}

// ---------------------------------------------------------------------------
// Pipe mode: read from stdin
// ---------------------------------------------------------------------------

async function readStdin(): Promise<string> {
  const MAX_STDIN_BYTES = 1024 * 1024; // 1MB max prompt from pipe
  const chunks: Buffer[] = [];
  let totalBytes = 0;

  // Timeout: if nothing comes in 10 seconds, bail
  const timeout = setTimeout(() => {
    process.stdin.destroy();
  }, 10_000);

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
  const { flags, prompt: cliPrompt } = parseArgs();

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
    await executePrompt(cliPrompt, agent, config);
    try {
      const cost = await Promise.race([
        costPromise,
        new Promise<null>((resolve) => setTimeout(() => resolve(null), COST_TIMEOUT_MS)),
      ]);
      if (cost) {
        printCostSummary(cost, getSession());
      }
    } catch {
      // Cost may not be available
    }
    await tracker.flush();
    process.exit(0);
  }

  // Mode 2: Pipe mode
  if (!process.stdin.isTTY) {
    const stdinPrompt = await readStdin();
    if (!stdinPrompt) {
      console.error(dim("  No prompt provided. Usage: echo 'prompt' | vantage"));
      process.exit(1);
    }
    if (stdinPrompt) {
      const costPromise = waitForCost();
      await executePrompt(stdinPrompt, agent, config);
      try {
        const cost = await Promise.race([
          costPromise,
          new Promise<null>((resolve) => setTimeout(() => resolve(null), COST_TIMEOUT_MS)),
        ]);
        if (cost) {
          printCostSummary(cost, getSession());
        }
      } catch {
        // Cost may not be available
      }
    }
    await tracker.flush();
    process.exit(0);
  }

  // Mode 3: REPL
  await startRepl(config);
}

main().catch((err) => {
  console.error(red(`Fatal error: ${err instanceof Error ? err.message : String(err)}`));
  process.exit(1);
});

process.on("unhandledRejection", (reason) => {
  const msg = reason instanceof Error ? reason.message : String(reason);
  console.error(red(`  Unhandled error: ${msg}`));
  // Don't exit — let the REPL continue
});
