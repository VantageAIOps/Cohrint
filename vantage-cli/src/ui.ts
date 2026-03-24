import type { OptimizationResult } from "./optimizer.js";
import type { SessionState } from "./session.js";
import type { VantageEvents } from "./event-bus.js";

const isTTY = process.stdout.isTTY ?? false;

function ansi(code: string, text: string): string {
  return isTTY ? `\x1b[${code}m${text}\x1b[0m` : text;
}

export function dim(text: string): string {
  return ansi("2", text);
}

export function bold(text: string): string {
  return ansi("1", text);
}

export function green(text: string): string {
  return ansi("32", text);
}

export function yellow(text: string): string {
  return ansi("33", text);
}

export function red(text: string): string {
  return ansi("31", text);
}

export function cyan(text: string): string {
  return ansi("36", text);
}

export function gray(text: string): string {
  return ansi("90", text);
}

export function printBanner(): void {
  console.log("");
  console.log(bold(cyan("  VantageAI CLI")));
  console.log(dim("  Optimize prompts. Track costs. Use any AI agent."));
  console.log(dim("  Type /help for commands, /quit to exit."));
  console.log("");
}

export function printOptimization(result: OptimizationResult): void {
  if (result.savedTokens <= 0) return;
  const pct = result.savedPercent;
  const color = pct >= 20 ? green : pct >= 10 ? yellow : dim;
  console.log(
    color(
      `  Optimized: ${result.originalTokens} -> ${result.optimizedTokens} tokens ` +
        `(saved ${result.savedTokens}, -${pct}%)`
    )
  );
}

export function printCostSummary(
  cost: VantageEvents["cost:calculated"],
  session: SessionState
): void {
  const w = 30;
  const line = (label: string, value: string) =>
    `  ${dim(label.padEnd(20))} ${value}`;

  console.log("");
  console.log(dim("  +" + "-".repeat(w) + "+"));
  console.log(dim("  |") + bold("  Cost & Optimization ") + dim("      |"));
  console.log(dim("  +" + "-".repeat(w) + "+"));
  console.log(line("Model:", cost.model));
  console.log(line("Input tokens:", cost.inputTokens.toLocaleString()));
  console.log(line("Output tokens:", cost.outputTokens.toLocaleString()));
  console.log(line("Cost:", green(`$${cost.costUsd.toFixed(6)}`)));

  // Optimization data
  if (session.totalSavedTokens > 0) {
    const savedThisPrompt = session.history.length > 0
      ? session.history[session.history.length - 1]?.savedTokens ?? 0
      : 0;
    if (savedThisPrompt > 0) {
      console.log(line("Tokens saved:", green(`${savedThisPrompt} tokens`)));
    }
  }
  if (cost.savedUsd > 0) {
    console.log(line("Cost saved:", green(`$${cost.savedUsd.toFixed(6)}`)));
  }

  console.log(dim("  +" + "-".repeat(w) + "+"));

  // Session totals
  console.log(line("Session cost:", `$${session.totalCostUsd.toFixed(6)}`));
  if (session.totalSavedTokens > 0) {
    console.log(line("Session saved:", green(`${session.totalSavedTokens.toLocaleString()} tokens`)));
  }
  console.log(line("Prompts:", session.promptCount.toString()));
  console.log(dim("  +" + "-".repeat(w) + "+"));
  console.log("");
}

export interface CompareResult {
  agent: string;
  model: string;
  durationMs: number;
  outputTokens: number;
  costUsd: number;
  output: string;
}

export function printCompareTable(results: CompareResult[]): void {
  console.log("");
  console.log(bold("  Agent Comparison"));
  console.log(dim("  " + "-".repeat(70)));

  const header = `  ${"Agent".padEnd(12)} ${"Model".padEnd(22)} ${"Time".padEnd(10)} ${"Tokens".padEnd(10)} ${"Cost".padEnd(12)}`;
  console.log(bold(header));
  console.log(dim("  " + "-".repeat(70)));

  // Sort by cost ascending
  const sorted = [...results].sort((a, b) => a.costUsd - b.costUsd);

  for (let i = 0; i < sorted.length; i++) {
    const r = sorted[i];
    const prefix = i === 0 ? green("* ") : "  ";
    const timeStr = `${(r.durationMs / 1000).toFixed(1)}s`;
    const costStr = `$${r.costUsd.toFixed(6)}`;

    const line = `${prefix}${r.agent.padEnd(12)} ${r.model.padEnd(22)} ${timeStr.padEnd(10)} ${r.outputTokens.toString().padEnd(10)} ${costStr}`;
    console.log(i === 0 ? green(line) : line);
  }

  console.log(dim("  " + "-".repeat(70)));
  console.log("");
}

export function printSessionSummary(session: SessionState): void {
  console.log("");
  console.log(bold(cyan("  Session Summary")));
  console.log(dim("  " + "-".repeat(40)));
  console.log(`  Prompts:        ${session.promptCount}`);
  console.log(`  Input tokens:   ${session.totalInputTokens.toLocaleString()}`);
  console.log(`  Output tokens:  ${session.totalOutputTokens.toLocaleString()}`);
  console.log(`  Total cost:     ${green("$" + session.totalCostUsd.toFixed(6))}`);
  console.log(`  Tokens saved:   ${session.totalSavedTokens.toLocaleString()}`);
  console.log(`  Duration:       ${((Date.now() - session.startedAt) / 1000).toFixed(1)}s`);
  console.log(dim("  " + "-".repeat(40)));
  console.log("");
}

export function promptLine(agentName: string): string {
  return isTTY ? `${cyan("vantage")} ${dim(`[${agentName}]`)} ${dim(">")} ` : "> ";
}
