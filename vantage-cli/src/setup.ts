import { createInterface, type Interface as ReadlineInterface } from "node:readline";
import { detectAll } from "./agents/registry.js";
import { type VantageConfig, DEFAULT_CONFIG, saveConfig } from "./config.js";
import { bold, cyan, green, red, dim } from "./ui.js";

function ask(rl: ReadlineInterface, question: string): Promise<string> {
  return new Promise((resolve) => {
    rl.question(question, (answer) => {
      resolve(answer.trim());
    });
  });
}

export async function runSetup(): Promise<VantageConfig> {
  const rl = createInterface({
    input: process.stdin,
    output: process.stdout,
  });

  console.log("");
  console.log(bold(cyan("  Welcome to VantageAI CLI")));
  console.log(dim("  Let's set up your configuration.\n"));

  // Detect installed agents
  console.log(bold("  Detecting AI agents...\n"));
  const detected = await detectAll();
  const available: string[] = [];

  for (const { agent, detected: found } of detected) {
    const icon = found ? green("  [x]") : red("  [ ]");
    const status = found ? "" : dim(" (not found)");
    console.log(`${icon} ${agent.displayName}${status}`);
    if (found) {
      available.push(agent.name);
    }
  }
  console.log("");

  if (available.length === 0) {
    console.log(
      red("  No AI agents detected. Install at least one (claude, codex, gemini, aider, chatgpt-cli).")
    );
    console.log(dim("  Using 'claude' as default. You can change this later in ~/.vantage/config.json\n"));
  }

  // Ask default agent
  let defaultAgent = "claude";
  if (available.length > 0) {
    const agentList = available.join(", ");
    const answer = await ask(
      rl,
      `  Default agent? (${agentList}) [${available[0]}]: `
    );
    defaultAgent = answer || available[0];
    if (!available.includes(defaultAgent)) {
      console.log(dim(`  '${defaultAgent}' not detected, using ${available[0]}`));
      defaultAgent = available[0];
    }
  }

  // Ask API key
  const apiKey = await ask(
    rl,
    "  VantageAI API key (Enter to skip): "
  );

  // Ask privacy level
  console.log("");
  console.log(dim("  Privacy levels:"));
  console.log(dim("    full       - send prompts + responses for analytics"));
  console.log(dim("    anonymized - send only metrics (token counts, costs)"));
  console.log(dim("    local-only - no data sent, local tracking only"));
  const privacyAnswer = await ask(
    rl,
    "  Privacy level? (full/anonymized/local-only) [anonymized]: "
  );
  const privacy = (["full", "anonymized", "local-only"].includes(privacyAnswer)
    ? privacyAnswer
    : "anonymized") as VantageConfig["privacy"];

  rl.close();

  // Build and save config
  const config: VantageConfig = {
    ...DEFAULT_CONFIG,
    defaultAgent,
    vantageApiKey: apiKey,
    privacy,
  };

  saveConfig(config);

  console.log("");
  console.log(green("  Configuration saved to ~/.vantage/config.json"));
  console.log(dim("  Run 'vantage' to start the REPL, or 'vantage \"your prompt\"' for one-shot mode.\n"));

  return config;
}
