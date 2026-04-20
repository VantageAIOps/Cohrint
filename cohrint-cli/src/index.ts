#!/usr/bin/env node
import { createInterface } from "readline";
import { VERSION } from "./_version.js";
import {
  loadConfig,
  configExists,
  DEFAULT_CONFIG,
  type VantageConfig,
} from "./config.js";
import { runSetup } from "./setup.js";
import { ALL_AGENTS, getAgent, detectAll } from "./agents/registry.js";
import {
  printBanner,
  printCostSummary,
  printCompareTable,
  printSessionSummary,
  printOptimization,
  printTip,
  promptLine,
  bold,
  cyan,
  dim,
  green,
  yellow,
  red,
  type CostData,
} from "./ui.js";
import { optimizePrompt } from "./optimizer.js";
import { looksLikeStructuredData } from "./classify.js";
import { countTokens } from "./optimizer.js";
import { calculateCost } from "./pricing.js";
import { bus } from "./event-bus.js";
import { Tracker } from "./tracker.js";
import { initSession, getSession } from "./session.js";
import { runAgent, runAgentBuffered, cancelActiveAgent, hasActiveAgent, type PermissionDenial } from "./runner.js";
import {
  loadState,
  saveState,
  clearState,
  migrateOldSessions,
  withStateLock,
} from "./session-persist.js";
import { checkCostAnomaly } from "./anomaly.js";
import {
  getRecommendations,
  getInlineTip,
  formatRecommendations,
  type SessionMetrics,
} from "./recommendations.js";
import {
  sanitizeModelFlag,
  sanitizeSystemFlag,
  parseIntBounded,
  assertHttpsApiBase,
  safeFetchJson,
} from "./sanitize.js";

const COST_TIMEOUT_MS = 5000;
const COST_LISTEN_MS = 600_000;

// Dashboard/budget fields are sourced from an external API and may arrive as
// strings like "N/A" or non-numeric JSON. Number("N/A") returns NaN, and
// NaN.toFixed() returns "NaN" — printing that is misleading, so coerce to 0.
function _finiteOr(n: unknown, fallback: number): number {
  const v = typeof n === "number" ? n : Number(n);
  return Number.isFinite(v) ? v : fallback;
}

function checkAnomaly(cost: CostData): void {
  const sess = getSession();
  const priorTotal = sess.totalCostUsd - cost.costUsd;
  const priorCount = sess.promptCount - 1;
  checkCostAnomaly(cost.costUsd, priorTotal, priorCount);
}

let _activeAgentName = "";

function buildSessionMetrics(): SessionMetrics {
  const sess = getSession();
  const agent = _activeAgentName ? getAgent(_activeAgentName) : undefined;
  return {
    totalInputTokens: sess.totalInputTokens,
    totalOutputTokens: sess.totalOutputTokens,
    totalCachedTokens: sess.totalSavedTokens,
    promptCount: sess.promptCount,
    totalCostUsd: sess.totalCostUsd,
    sessionStartTime: sess.startedAt,
    agent: _activeAgentName || undefined,
    model: agent?.defaultModel,
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
  const base = config.vantageApiBase || DEFAULT_CONFIG.vantageApiBase;
  if (!assertHttpsApiBase(base)) {
    console.log(red("  Refusing to send API key to non-HTTPS endpoint."));
    return;
  }
  try {
    const headers: Record<string, string> = {
      Authorization: `Bearer ${config.vantageApiKey}`,
      "Content-Type": "application/json",
    };
    const [summaryRes, kpisRes] = await Promise.all([
      fetch(`${base}/v1/analytics/summary`, {
        headers,
        signal: AbortSignal.timeout(10000),
      }),
      fetch(`${base}/v1/analytics/kpis?period=30`, {
        headers,
        signal: AbortSignal.timeout(10000),
      }),
    ]);
    const summary = summaryRes.ok ? await safeFetchJson(summaryRes) : null;
    const kpis = kpisRes.ok ? await safeFetchJson(kpisRes) : null;

    console.log("");
    console.log(bold(cyan("  Dashboard Summary")));
    console.log(dim("  " + "-".repeat(45)));

    if (summary) {
      const s = summary as Record<string, unknown>;
      const todayCost = _finiteOr(s.today_cost_usd, 0);
      const mtdCost = _finiteOr(s.mtd_cost_usd, 0);
      const todayReqs = _finiteOr(s.today_requests, 0);
      const budgetPct = _finiteOr(s.budget_pct, 0);
      const budgetUsd = _finiteOr(s.budget_usd, 0);
      console.log(`  ${dim("Today spend:")}    ${green("$" + todayCost.toFixed(4))}`);
      console.log(`  ${dim("MTD spend:")}      $${mtdCost.toFixed(4)}`);
      console.log(`  ${dim("Today requests:")} ${todayReqs}`);
      if (budgetUsd > 0) {
        const color = budgetPct > 85 ? red : budgetPct > 60 ? yellow : green;
        console.log(`  ${dim("Budget:")}         ${color(budgetPct + "%")} of $${budgetUsd}`);
      }
    }
    if (kpis) {
      const k = kpis as Record<string, unknown>;
      const totalCost = _finiteOr(k.total_cost_usd, 0);
      const totalTokens = _finiteOr(k.total_tokens, 0);
      const totalReqs = _finiteOr(k.total_requests, 0);
      const avgLatency = _finiteOr(k.avg_latency_ms, 0);
      const effScore = _finiteOr(k.efficiency_score, 0);
      console.log(`  ${dim("30d spend:")}      $${totalCost.toFixed(4)}`);
      console.log(`  ${dim("30d tokens:")}     ${totalTokens.toLocaleString()}`);
      console.log(`  ${dim("30d requests:")}   ${totalReqs.toLocaleString()}`);
      console.log(`  ${dim("Avg latency:")}    ${avgLatency.toFixed(0)}ms`);
      console.log(`  ${dim("Efficiency:")}     ${effScore}/100`);
    }

    const session = getSession();
    if (session.promptCount > 0) {
      console.log(dim("  " + "-".repeat(45)));
      console.log(
        `  ${dim("Local session:")}  ${session.promptCount} prompts, $${session.totalCostUsd.toFixed(4)}`
      );
      if (session.totalSavedTokens > 0) {
        console.log(
          `  ${dim("Tokens saved:")}   ${green(session.totalSavedTokens.toLocaleString())}`
        );
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
  const base = config.vantageApiBase || DEFAULT_CONFIG.vantageApiBase;
  if (!assertHttpsApiBase(base)) {
    console.log(red("  Refusing to send API key to non-HTTPS endpoint."));
    return;
  }
  try {
    const res = await fetch(`${base}/v1/analytics/summary`, {
      headers: { Authorization: `Bearer ${config.vantageApiKey}` },
      signal: AbortSignal.timeout(10000),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await safeFetchJson(res);
    if (!data) throw new Error("Invalid JSON response from API");
    const d = data as Record<string, unknown>;
    const budgetUsd = _finiteOr(d.budget_usd, 0);
    const budgetPct = _finiteOr(d.budget_pct, 0);
    const mtdCost = _finiteOr(d.mtd_cost_usd, 0);

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
      console.log(
        `  ${dim("Remaining:")}      ${remaining > 0 ? green("$" + remaining.toFixed(2)) : red("OVER BUDGET")}`
      );
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

const VANTAGE_FLAGS = new Set([
  "agent",
  "no-optimize",
  "timeout",
  "model",
  "system",
  "debug",
  "paste-delay",
]);

interface ParsedArgs {
  flags: Record<string, string>;
  agentFlags: string[];
  positional: string[];
  prompt: string;
}

function parseArgs(): ParsedArgs {
  const args = process.argv.slice(2);
  const flags: Record<string, string> = {};
  const agentFlags: string[] = [];
  const positional: string[] = [];

  for (let i = 0; i < args.length; i++) {
    if (args[i].startsWith("--")) {
      const key = args[i].slice(2);
      const val =
        args[i + 1] && !args[i + 1].startsWith("--") ? args[i + 1] : "true";
      if (VANTAGE_FLAGS.has(key)) {
        flags[key] = val;
      } else {
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

interface ExecuteResult {
  sessionId?: string;
  costUsd?: number;
  permissionDenials: PermissionDenial[];
  staleSession?: boolean;
  notLoggedIn?: boolean;
  exitCode?: number;
  crashed?: boolean;
}

function printNotLoggedIn(agent: (typeof ALL_AGENTS)[0]): void {
  console.log("");
  console.log(yellow(`  ⚠ ${agent.displayName} is not logged in.`));
  console.log(dim(`    Run '${agent.binary}' in a separate terminal to authenticate, then retry.`));
  console.log("");
}

async function executePrompt(
  prompt: string,
  agent: (typeof ALL_AGENTS)[0],
  config: VantageConfig,
  stream = true,
  continueConversation = false,
  sessionId?: string,
  noOptimize = false,
  extraFlags: string[] = [],
  timeoutMs?: number
): Promise<ExecuteResult> {
  bus.emit("prompt:submitted", {
    prompt,
    agent: agent.name,
    timestamp: Date.now(),
  });

  let finalPrompt = prompt;
  if (
    !noOptimize &&
    config.optimization.enabled &&
    !looksLikeStructuredData(prompt)
  ) {
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

  // Copy caller-owned array — don't mutate. The stale-session retry path calls
  // executePrompt twice with the same currentFlags array; mutating it would
  // append --permission-mode / --allowedTools twice on the second call.
  const mergedFlags = [...extraFlags];
  if (agent.name === "claude") {
    const agentCfg = config.agents?.["claude"];
    const permMode = agentCfg?.["permissionMode"];
    const allowedTools = agentCfg?.["allowedTools"];
    if (permMode) mergedFlags.push("--permission-mode", permMode);
    if (allowedTools?.length) mergedFlags.push("--allowedTools", allowedTools.join(","));
  }

  const agentConfig = mergedFlags.length > 0 ? { extraFlags: mergedFlags } : undefined;
  const useContinue =
    continueConversation && agent.supportsContinue && agent.buildContinueCommand;
  const spawnArgs = useContinue
    ? agent.buildContinueCommand!(finalPrompt, agentConfig, sessionId)
    : agent.buildCommand(finalPrompt, agentConfig);

  try {
    const result = stream
      ? await runAgent(spawnArgs, agent.name, timeoutMs)
      : await runAgentBuffered(spawnArgs, agent.name, timeoutMs);
    return {
      sessionId: result.sessionId,
      costUsd: result.costUsd,
      permissionDenials: result.permissionDenials,
      staleSession: result.staleSession,
      notLoggedIn: result.notLoggedIn,
      exitCode: result.exitCode,
      crashed: result.exitCode !== 0,
    };
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    console.error(red(`  Error running ${agent.displayName}: ${message}`));
    console.error(dim(`  Make sure '${agent.binary}' is installed and in your PATH.`));
    return { permissionDenials: [], crashed: true, exitCode: 1 };
  }
}

let _permissionResolver: ((line: string) => void) | null = null;

function _isAwaitingPermission(): boolean {
  return _permissionResolver !== null;
}

function _feedPermissionInput(line: string): void {
  const r = _permissionResolver;
  if (r) {
    _permissionResolver = null;
    r(line);
  }
}

function _sanitizeForTerminal(s: string, max: number): string {
  // Strip ESC, CSI, and other control chars (C0 + DEL + C1) to prevent a
  // compromised subprocess from injecting ANSI escapes via tool metadata.
  const cleaned = s.replace(/[\x00-\x1f\x7f-\x9f]/g, "");
  return cleaned.length > max ? cleaned.slice(0, max) + "…" : cleaned;
}

async function askToolPermission(
  toolName: string,
  toolInput: Record<string, unknown>,
  _rl: ReturnType<typeof createInterface>
): Promise<"yes" | "always" | "no"> {
  const safeName = _sanitizeForTerminal(String(toolName), 60);
  const MAX_KEY = 20;
  const MAX_VAL = 50;
  const MAX_PREVIEW = 200;
  let preview = Object.entries(toolInput)
    .map(([k, v]) => {
      const safeKey = _sanitizeForTerminal(String(k), MAX_KEY);
      const raw = typeof v === "string" ? v : JSON.stringify(v);
      const safeVal = _sanitizeForTerminal(String(raw ?? ""), MAX_VAL);
      return `${safeKey}=${safeVal}`;
    })
    .join(", ");
  if (preview.length > MAX_PREVIEW) preview = preview.slice(0, MAX_PREVIEW) + "…";

  return new Promise((resolve) => {
    const ask = () => {
      process.stdout.write(
        yellow(`\n  ⚠ Claude wants to use ${safeName}(${preview})\n`)
      );
      process.stdout.write(`    ${dim("[y]es once  [a]lways  [n]o")}: `);
      _permissionResolver = (line: string) => {
        const answer = line.trim().toLowerCase();
        if (answer === "a" || answer === "always") return resolve("always");
        if (answer === "y" || answer === "yes") return resolve("yes");
        if (answer === "n" || answer === "no" || answer === "") return resolve("no");
        process.stdout.write(dim(`    Please answer y, a, or n.\n`));
        ask();
      };
    };
    ask();
  });
}

async function executeWithPermissions(
  prompt: string,
  agent: (typeof ALL_AGENTS)[0],
  config: VantageConfig,
  stream: boolean,
  continueConversation: boolean,
  sessionId: string | undefined,
  noOptimize: boolean,
  extraFlags: string[],
  timeoutMs: number | undefined,
  allowedTools: Set<string>,
  rl: ReturnType<typeof createInterface>,
  clearSession?: () => void
): Promise<{ sessionId?: string; costUsd?: number; notLoggedIn?: boolean; exitCode?: number; crashed?: boolean }> {
  let currentFlags = [...extraFlags];
  if (allowedTools.size > 0) {
    currentFlags = [...currentFlags, "--allowedTools", [...allowedTools].join(",")];
  }

  let result = await executePrompt(
    prompt,
    agent,
    config,
    stream,
    continueConversation,
    sessionId,
    noOptimize,
    currentFlags,
    timeoutMs
  );

  if (result.notLoggedIn) {
    printNotLoggedIn(agent);
    return { notLoggedIn: true };
  }

  let useContinue = continueConversation;
  let useSessionId = sessionId;
  if (result.staleSession && useContinue) {
    clearSession?.();
    console.log(dim("  Session expired — starting fresh"));
    useContinue = false;
    useSessionId = undefined;
    result = await executePrompt(
      prompt, agent, config, stream, useContinue, useSessionId,
      noOptimize, currentFlags, timeoutMs
    );
    if (result.notLoggedIn) {
      printNotLoggedIn(agent);
      return { notLoggedIn: true };
    }
  }

  if (result.permissionDenials.length > 0) {
    const retryTools = new Set<string>(allowedTools);
    let grantedNew = false;
    for (const denial of result.permissionDenials) {
      const answer = await askToolPermission(denial.toolName, denial.toolInput, rl);
      if (answer === "always") {
        if (!allowedTools.has(denial.toolName)) grantedNew = true;
        allowedTools.add(denial.toolName);
        retryTools.add(denial.toolName);
      } else if (answer === "yes") {
        if (!retryTools.has(denial.toolName)) grantedNew = true;
        retryTools.add(denial.toolName);
      }
    }
    if (grantedNew) {
      const retryFlags = [...extraFlags, "--allowedTools", [...retryTools].join(",")];
      const retryResult = await executePrompt(
        prompt,
        agent,
        config,
        stream,
        useContinue,
        useSessionId,
        noOptimize,
        retryFlags,
        timeoutMs
      );
      return {
        sessionId: retryResult.sessionId,
        costUsd: retryResult.costUsd,
        exitCode: retryResult.exitCode,
        crashed: retryResult.crashed,
      };
    }
  }

  return {
    sessionId: result.sessionId,
    costUsd: result.costUsd,
    exitCode: result.exitCode,
    crashed: result.crashed,
  };
}

function waitForCost(): Promise<CostData | null> {
  return new Promise((resolve) => {
    let settled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const handler = (data: CostData) => {
      if (!settled) {
        settled = true;
        if (timer) {
          clearTimeout(timer);
          timer = null;
        }
        resolve(data);
      }
    };
    bus.once("cost:calculated", handler);
    timer = setTimeout(() => {
      if (!settled) {
        settled = true;
        bus.off("cost:calculated", handler);
        resolve(null);
      }
    }, COST_LISTEN_MS);
  });
}

async function runCompare(prompt: string, config: VantageConfig): Promise<void> {
  const detected = await detectAll();
  const available = detected.filter((d) => d.detected);
  if (available.length < 2) {
    console.log(yellow("  Need at least 2 agents installed for /compare."));
    return;
  }
  console.log(dim(`  Running prompt across ${available.length} agents...\n`));
  const results = [];
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

async function startRepl(
  config: VantageConfig,
  replFlags: Record<string, string> = {}
): Promise<void> {
  printBanner();
  let currentAgent = getAgent(config.defaultAgent) ?? ALL_AGENTS[0];
  _activeAgentName = currentAgent.name;

  migrateOldSessions();
  const state = loadState();
  const agentSessionIds = new Map(Object.entries(state.sessionIds));
  const agentPromptCount = new Map<string, number>();
  const allowedTools = new Set(state.allowedTools);

  for (const agent of agentSessionIds.keys()) {
    agentPromptCount.set(agent, 1);
  }

  function persistState() {
    const ids: Record<string, string> = {};
    for (const [k, v] of agentSessionIds) ids[k] = v;
    // Merge under lock with on-disk state so a racing CLI instance's writes
    // aren't silently clobbered. Unknown agents from other processes are
    // preserved; only agents touched by THIS process are overwritten.
    withStateLock(() => {
      const onDisk = loadState();
      const mergedIds: Record<string, string> = { ...onDisk.sessionIds, ...ids };
      const mergedTools = new Set<string>([...onDisk.allowedTools, ...allowedTools]);
      saveState({ sessionIds: mergedIds, allowedTools: [...mergedTools] });
    });
  }

  const rl = createInterface({
    input: process.stdin,
    output: process.stdout,
  });

  rl.on("error", (err: NodeJS.ErrnoException) => {
    if (err.code === "EPIPE" || err.code === "EIO") return;
    console.error(red(`  Terminal error: ${err.message}`));
  });

  const PASTE_DELAY_MS = replFlags["paste-delay"]
    ? parseIntBounded(replFlags["paste-delay"], 80, 0, 60_000)
    : parseIntBounded(process.env.VANTAGE_PASTE_DELAY, 80, 0, 60_000);

  let pasteBuffer: string[] = [];
  let pasteTimer: ReturnType<typeof setTimeout> | null = null;
  let handleLine: ((input: string) => void) | null = null;

  function onLineReceived(raw: string) {
    if (_isAwaitingPermission()) {
      _feedPermissionInput(raw);
      return;
    }
    pasteBuffer.push(raw);
    if (pasteTimer) clearTimeout(pasteTimer);
    pasteTimer = setTimeout(() => {
      const combined = pasteBuffer.join("\n").trim();
      pasteBuffer = [];
      pasteTimer = null;
      if (handleLine) {
        handleLine(combined);
      } else if (combined) {
        // Re-entry guard dropped this line. Surface it so the user knows
        // the REPL isn't frozen — their input just raced a running agent.
        process.stdout.write(
          `\n${dim("  [input discarded: agent still running — resend when prompt returns]")}\n`
        );
      }
    }, PASTE_DELAY_MS);
  }

  const prompt = () => {
    process.stdout.write(promptLine(currentAgent.name));
    handleLine = async (input: string) => {
      // Re-entry guard: clear handler before awaiting so a concurrent
      // stdin burst (paste timer firing mid-await) can't double-spawn.
      handleLine = null;
      const line = input.trim();
      if (!line) {
        prompt();
        return;
      }
      try {
        if (line === "/quit" || line === "/exit" || line === "/q") {
          await shutdown();
          return;
        }
        if (line === "/help") {
          printHelp();
          prompt();
          return;
        }
        if (line === "/login") {
          printNotLoggedIn(currentAgent);
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
        if (line === "/reset") {
          agentSessionIds.clear();
          agentPromptCount.clear();
          allowedTools.clear();
          clearState();
          console.log(dim("  Session reset. All allowed tools cleared."));
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
        if (line === "/agents") {
          const detected = await detectAll();
          for (const { agent, detected: found } of detected) {
            const status = found ? green("✓") : dim("✗");
            console.log(`  ${status} ${agent.displayName.padEnd(16)} ${dim(agent.name)}`);
          }
          prompt();
          return;
        }
        if (line === "/setup") {
          // Pause line events during setup so runSetup's `rl.question` calls
          // receive input directly instead of being intercepted by our
          // line handler. runSetup reuses this rl — it must not be closed.
          rl.removeListener("line", onLineReceived);
          try {
            const newConfig = await runSetup(rl);
            Object.assign(config, newConfig);
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
            const newAgent = getAgent(config.defaultAgent);
            if (newAgent) {
              currentAgent = newAgent;
              _activeAgentName = newAgent.name;
            }
            console.log(green("  Config reloaded.\n"));
          } catch (err) {
            const msg = err instanceof Error ? err.message : String(err);
            console.error(red(`  Setup failed: ${msg}`));
          }
          // Re-attach the line listener and resume the prompt in-place,
          // avoiding a recursive startRepl call and duplicate signal handlers.
          rl.on("line", onLineReceived);
          prompt();
          return;
        }
        if (line === "/status") {
          const session = getSession();
          console.log("");
          console.log(`  ${dim("Agent:")}    ${currentAgent.displayName}`);
          console.log(`  ${dim("Prompts:")} ${session.promptCount}`);
          console.log(`  ${dim("Cost:")}     $${session.totalCostUsd.toFixed(4)}`);
          if (allowedTools.size > 0) {
            console.log(`  ${dim("Allowed tools:")} ${[...allowedTools].join(", ")}`);
          }
          console.log("");
          prompt();
          return;
        }
        if (line.startsWith("/default ")) {
          const name = line.slice(9).trim();
          const agent = getAgent(name);
          if (agent) {
            currentAgent = agent;
            _activeAgentName = agent.name;
            console.log(green(`  Default agent set to ${agent.displayName}`));
          } else {
            console.log(red(`  Unknown agent: ${name}`));
            console.log(
              dim(`  Available: ${ALL_AGENTS.map((a) => a.name).join(", ")}`)
            );
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

        const agentPrefixMatch = line.match(/^\/(\w+)\s+([\s\S]+)$/);
        if (agentPrefixMatch) {
          const [, agentName, rawAgentPrompt] = agentPrefixMatch;
          const agentPrompt = rawAgentPrompt.trim();
          const agent = getAgent(agentName);
          if (agent && agentPrompt) {
            const costPromise2 = waitForCost();
            const count2 = agentPromptCount.get(agent.name) ?? 0;
            const { sessionId: sid2, notLoggedIn: notLoggedIn2 } = await executeWithPermissions(
              agentPrompt,
              agent,
              config,
              true,
              count2 > 0,
              agentSessionIds.get(agent.name),
              false,
              [],
              undefined,
              allowedTools,
              rl,
              () => { agentSessionIds.delete(agent.name); persistState(); }
            );
            if (notLoggedIn2) {
              prompt();
              return;
            }
            agentPromptCount.set(agent.name, count2 + 1);
            if (sid2) {
              agentSessionIds.set(agent.name, sid2);
            } else {
              agentSessionIds.delete(agent.name);
            }
            persistState();
            try {
              const cost = await Promise.race([
                costPromise2,
                new Promise<null>((resolve) =>
                  setTimeout(() => resolve(null), COST_TIMEOUT_MS)
                ),
              ]);
              if (cost) {
                printCostSummary(cost, getSession());
                checkAnomaly(cost);
                showInlineTip();
              }
            } catch {}
          } else if (!agent) {
            console.log(red(`  Unknown agent: ${agentName}`));
          }
          prompt();
          return;
        }

        const switchMatch = line.match(/^\/([\w-]+)$/);
        if (switchMatch) {
          const agent = getAgent(switchMatch[1]);
          if (agent) {
            currentAgent = agent;
            _activeAgentName = agent.name;
            console.log(green(`  Switched to ${agent.displayName}`));
          } else {
            console.log(red(`  Unknown command: /${switchMatch[1]}`));
            console.log(dim(`  Type /help for commands, or /<agent> to switch agents.`));
          }
          prompt();
          return;
        }

        if (line.startsWith("/")) {
          const cmdRaw = line.slice(1).split(/\s/)[0];
          // Reflecting raw user input into the terminal is an OSC/CSI escape
          // vector. Keep only printable ASCII and cap to 32 chars.
          const cmdName = cmdRaw.replace(/[^\x20-\x7e]/g, "").slice(0, 32);
          console.log(red(`  Unknown command: /${cmdName}`));
          console.log(dim(`  Type /help for commands.`));
          prompt();
          return;
        }

        const costPromise = waitForCost();
        const count = agentPromptCount.get(currentAgent.name) ?? 0;
        const { sessionId: sid, notLoggedIn: notLoggedInDefault } = await executeWithPermissions(
          line,
          currentAgent,
          config,
          true,
          count > 0,
          agentSessionIds.get(currentAgent.name),
          false,
          [],
          undefined,
          allowedTools,
          rl,
          () => { agentSessionIds.delete(currentAgent.name); persistState(); }
        );
        if (notLoggedInDefault) {
          prompt();
          return;
        }
        agentPromptCount.set(currentAgent.name, count + 1);
        if (sid) {
          agentSessionIds.set(currentAgent.name, sid);
        } else {
          agentSessionIds.delete(currentAgent.name);
        }
        persistState();
        try {
          const cost = await Promise.race([
            costPromise,
            new Promise<null>((resolve) =>
              setTimeout(() => resolve(null), COST_TIMEOUT_MS)
            ),
          ]);
          if (cost) {
            printCostSummary(cost, getSession());
            checkAnomaly(cost);
            showInlineTip();
          }
        } catch {}
        prompt();
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        console.error(red(`  Error: ${msg}`));
        prompt();
      }
    };
  };

  const shutdown = async () => {
    if (pasteTimer) {
      clearTimeout(pasteTimer);
      pasteTimer = null;
    }
    if (pasteBuffer.length > 0) {
      console.warn(`[vantage] Discarded ${pasteBuffer.length} buffered lines on exit`);
      pasteBuffer = [];
    }
    rl.close();
    await tracker?.flush().catch(() => {});
    printSessionSummary(getSession());
    process.exit(0);
  };

  rl.on("line", onLineReceived);
  let sigintGraceTimer: NodeJS.Timeout | null = null;
  rl.on("SIGINT", () => {
    if (hasActiveAgent()) {
      cancelActiveAgent();
      console.log(dim("\n  ⏹ Interrupted. Press Ctrl-C again or type /quit to exit."));
      return;
    }
    if (sigintGraceTimer) {
      clearTimeout(sigintGraceTimer);
      sigintGraceTimer = null;
      shutdown().catch(() => process.exit(1));
      return;
    }
    console.log(dim("  (Press Ctrl-C again to exit, or type /quit)"));
    sigintGraceTimer = setTimeout(() => { sigintGraceTimer = null; }, 2000);
    try { rl.prompt(true); } catch {}
  });
  // Use once() so that re-entering this function (e.g. future refactors)
  // does not stack duplicate listeners. These are process-level signals that
  // should only be handled once per process lifetime.
  process.once("SIGTERM", () => {
    shutdown().catch(() => process.exit(1));
  });
  process.once("SIGHUP", () => {
    shutdown().catch(() => process.exit(1));
  });

  prompt();
}

function printHelp(): void {
  console.log("");
  console.log(bold("  Cohrint Commands"));
  console.log(dim("  " + "-".repeat(50)));
  console.log(`  ${cyan("/cost")}               Show cost summary`);
  console.log(`  ${cyan("/agents")}             List available agents`);
  console.log(`  ${cyan("/default <agent>")}    Set default agent`);
  console.log(`  ${cyan("/compare <prompt>")}   Compare agents side by side`);
  console.log(`  ${cyan("/summary")}            Dashboard summary (spend, tokens, budget)`);
  console.log(`  ${cyan("/budget")}             Check budget status and alerts`);
  console.log(`  ${cyan("/tips")}               Show cost-saving recommendations`);
  console.log(`  ${cyan("/status")}             Show current agent, cost, allowed tools`);
  console.log(`  ${cyan("/reset")}              Clear session & allowed tools`);
  console.log(`  ${cyan("/login")}              Show agent login instructions`);
  console.log(`  ${cyan("/setup")}              Run setup wizard`);
  console.log(`  ${cyan("/help")}               Show this help`);
  console.log(`  ${cyan("/quit")}               Exit`);
  console.log("");
  console.log(dim("  Agent shorthand:"));
  console.log(dim("    /claude <prompt>   Send to specific agent"));
  console.log("");
  console.log(dim("  Tips:"));
  console.log(dim("    Prompts are auto-optimized to save tokens."));
  console.log(dim("    Tool permissions are asked on first use."));
  console.log("");
}

async function readStdin(): Promise<string> {
  const MAX_STDIN_BYTES = 1024 * 1024;
  const chunks: Buffer[] = [];
  let totalBytes = 0;
  const stdinTimeoutMs = parseIntBounded(
    process.env.VANTAGE_STDIN_TIMEOUT,
    30000,
    1_000,
    10 * 60 * 1000,
  );
  const timeout = setTimeout(() => {
    process.stdin.destroy();
  }, stdinTimeoutMs);
  try {
    for await (const chunk of process.stdin) {
      const buf = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk as string);
      totalBytes += buf.length;
      if (totalBytes > MAX_STDIN_BYTES) {
        clearTimeout(timeout);
        console.error(dim("  Warning: prompt truncated at 1MB"));
        break;
      }
      chunks.push(buf);
    }
  } catch {}
  clearTimeout(timeout);
  if (chunks.length === 0) return "";
  return Buffer.concat(chunks).toString("utf-8").trim();
}

let tracker: Tracker | null = null;

function printCliHelp(): void {
  console.log("");
  console.log(bold("  cohrint") + dim(" — unified CLI for Claude, Codex, and Gemini"));
  console.log("");
  console.log("  " + bold("Usage:"));
  console.log("    cohrint [--agent <name>] [--model <m>] [--timeout <ms>] [--no-optimize] [--debug] [prompt...]");
  console.log("    cohrint                    " + dim("# launch interactive REPL"));
  console.log("    echo 'hi' | cohrint        " + dim("# pipe stdin as prompt"));
  console.log("");
  console.log("  " + bold("Flags:"));
  console.log("    --agent <name>      Agent to use (claude, codex, gemini, ...)");
  console.log("    --model <name>      Override model (forwarded to agent)");
  console.log("    --system <text>     System prompt (forwarded to agent)");
  console.log("    --timeout <ms>      Kill agent after N milliseconds");
  console.log("    --no-optimize       Skip prompt optimization");
  console.log("    --debug             Emit [vantage] diagnostic output");
  console.log("    --paste-delay <ms>  Delay between pasted lines in REPL");
  console.log("    --version, -v       Print version and exit");
  console.log("    --help, -h          Show this help and exit");
  console.log("");
  console.log("  " + bold("REPL commands:") + " /help, /cost, /agents, /default, /summary, /budget, /tips, /status, /reset, /login, /setup, /quit");
  console.log("");
}

async function main(): Promise<void> {
  const rawArgs = process.argv.slice(2);
  if (rawArgs.includes("--version") || rawArgs.includes("-v")) {
    console.log(VERSION);
    process.exit(0);
  }
  if (rawArgs.includes("--help") || rawArgs.includes("-h")) {
    printCliHelp();
    process.exit(0);
  }

  const { flags, agentFlags, prompt: cliPrompt } = parseArgs();

  let config: VantageConfig;
  if (configExists()) {
    config = loadConfig();
  } else {
    if (!process.stdin.isTTY) {
      config = loadConfig();
    } else {
      config = await runSetup();
    }
  }

  const agentName = flags.agent ?? config.defaultAgent;
  const agent = getAgent(agentName) ?? ALL_AGENTS[0];
  _activeAgentName = agent.name;

  const extraAgentFlags = [...agentFlags];
  const safeModel = sanitizeModelFlag(flags.model);
  const safeSystem = sanitizeSystemFlag(flags.system);
  if (safeModel) extraAgentFlags.push("--model", safeModel);
  if (safeSystem) extraAgentFlags.push("--system", safeSystem);

  const noOptimize = flags["no-optimize"] === "true";
  const timeoutMs = parseIntBounded(flags.timeout, 0, 1, 24 * 60 * 60 * 1000) || undefined;

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

  if (cliPrompt) {
    const costPromise = waitForCost();
    const oneShot = await executePrompt(
      cliPrompt,
      agent,
      config,
      true,
      false,
      undefined,
      noOptimize,
      extraAgentFlags,
      timeoutMs
    );
    if (oneShot.notLoggedIn) {
      printNotLoggedIn(agent);
      await tracker.flush().catch(() => {});
      process.exit(1);
    }
    if (oneShot.permissionDenials.length > 0) {
      console.error(
        yellow(
          `\n  ⚠ ${oneShot.permissionDenials.length} tool call(s) denied. Re-run with --allowedTools or use REPL for interactive approval.`
        )
      );
      for (const d of oneShot.permissionDenials) {
        console.error(dim(`    - ${d.toolName}`));
      }
    }
    try {
      const cost = await Promise.race([
        costPromise,
        new Promise<null>((resolve) =>
          setTimeout(() => resolve(null), COST_TIMEOUT_MS)
        ),
      ]);
      if (cost) {
        printCostSummary(cost, getSession());
        checkAnomaly(cost);
        showInlineTip();
      }
    } catch {}
    await tracker.flush().catch(() => {});
    // Deregister beforeExit + interval so a stray wake-up can't flush again.
    tracker.stop();
    // Exit codes: permission denials = 2; agent crashed = the agent's
    // own exit code (or 1 if we couldn't spawn). Silent success-on-crash
    // would break CI pipelines that chain on `cohrint && deploy`.
    if (oneShot.permissionDenials.length > 0) process.exit(2);
    if (oneShot.crashed) process.exit(oneShot.exitCode || 1);
    process.exit(0);
  }

  if (!process.stdin.isTTY) {
    const stdinPrompt = await readStdin();
    if (!stdinPrompt || stdinPrompt.trim() === "") {
      process.exit(0);
    }
    const costPromise = waitForCost();
    const stdinRun = await executePrompt(
      stdinPrompt,
      agent,
      config,
      true,
      false,
      undefined,
      noOptimize,
      extraAgentFlags,
      timeoutMs
    );
    if (stdinRun.notLoggedIn) {
      printNotLoggedIn(agent);
      await tracker.flush().catch(() => {});
      tracker.stop();
      process.exit(1);
    }
    if (stdinRun.permissionDenials.length > 0) {
      console.error(
        yellow(
          `\n  ⚠ ${stdinRun.permissionDenials.length} tool call(s) denied. Re-run with --allowedTools or use REPL for interactive approval.`
        )
      );
      for (const d of stdinRun.permissionDenials) {
        console.error(dim(`    - ${d.toolName}`));
      }
    }
    try {
      const cost = await Promise.race([
        costPromise,
        new Promise<null>((resolve) =>
          setTimeout(() => resolve(null), COST_TIMEOUT_MS)
        ),
      ]);
      if (cost) {
        printCostSummary(cost, getSession());
        checkAnomaly(cost);
        showInlineTip();
      }
    } catch {}
    await tracker.flush().catch(() => {});
    tracker.stop();
    if (stdinRun.permissionDenials.length > 0) process.exit(2);
    if (stdinRun.crashed) process.exit(stdinRun.exitCode || 1);
    process.exit(0);
  }

  await startRepl(config, flags);
}

function isNewerVersion(latest: string, current: string): boolean {
  // Strip any pre-release suffix (e.g., "2.2.5-beta.1" → "2.2.5") before
  // comparing. Non-numeric parts cause Number() to return NaN and silently
  // break all comparisons.
  const clean = (v: string) => v.split("-")[0];
  const parse = (v: string) => clean(v).split(".").map(Number);
  const parts = [parse(latest), parse(current)];
  // Bail out if either version failed to parse.
  if (parts.some((p) => p.some((n) => !Number.isFinite(n)))) return false;
  const [lMaj, lMin, lPat] = parts[0];
  const [cMaj, cMin, cPat] = parts[1];
  if (lMaj !== cMaj) return lMaj > cMaj;
  if (lMin !== cMin) return lMin > cMin;
  return lPat > cPat;
}

async function checkForUpdate(): Promise<void> {
  try {
    const current = VERSION;
    const res = await fetch("https://registry.npmjs.org/cohrint-cli/latest", {
      signal: AbortSignal.timeout(2000),
    });
    if (!res.ok) return;
    const data = await safeFetchJson(res, 256 * 1024);
    if (!data || typeof data !== "object") return;
    const version = (data as Record<string, unknown>).version;
    if (typeof version !== "string" || !version) return;
    // Reject anything that's not strict semver-ish. A MITM'd or poisoned npm
    // registry response could return "1.2.3\x1b]52;c;payload\x07" — the shell
    // would interpret the OSC 52 escape as a clipboard-write. Keep only the
    // characters a real npm version can contain.
    if (!/^[A-Za-z0-9._\-+]{1,64}$/.test(version)) return;
    if (isNewerVersion(version, current)) {
      console.error(
        yellow(`\n  Update available: cohrint-cli ${current} → ${version}`)
      );
      console.error(dim(`  Run: npm install -g cohrint-cli\n`));
    }
  } catch {}
}

main().catch((err: unknown) => {
  console.error(
    red(`Fatal error: ${err instanceof Error ? err.message : String(err)}`)
  );
  process.exit(1);
});

checkForUpdate();

process.on("unhandledRejection", (reason: unknown) => {
  const msg = reason instanceof Error ? reason.message : String(reason);
  console.error(red(`  Unhandled error: ${msg}`));
  if (!process.stdin.isTTY) {
    process.exit(1);
  }
});
