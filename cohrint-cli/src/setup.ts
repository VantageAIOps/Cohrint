import { createInterface } from "readline";
import { DEFAULT_CONFIG, saveConfig, type VantageConfig } from "./config.js";
import { detectAll } from "./agents/registry.js";
import { bold, cyan, dim, green, red } from "./ui.js";

function ask(rl: ReturnType<typeof createInterface>, question: string): Promise<string> {
  return new Promise((resolve) => {
    rl.question(question, (answer) => {
      resolve(answer.trim());
    });
  });
}

export async function runSetup(
  existingRl?: ReturnType<typeof createInterface>
): Promise<VantageConfig> {
  // Reuse the caller's readline if provided (REPL /setup path) so we don't
  // open a second interface on process.stdin. Only close the interface in
  // the finally if we own it (first-run path, no REPL yet).
  const rl = existingRl ?? createInterface({
    input: process.stdin,
    output: process.stdout,
  });
  const ownsRl = existingRl === undefined;

  try {
    console.log("");
    console.log(bold(cyan("  Welcome to Cohrint CLI")));
    console.log(dim("  Let's set up your configuration.\n"));
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

    const apiKey = await ask(
      rl,
      "  Cohrint API key (Enter to skip): "
    );

    console.log("");
    console.log(dim("  Privacy levels:"));
    console.log(dim("    full       - send prompts + responses for analytics"));
    console.log(dim("    anonymized - send only metrics (token counts, costs)"));
    console.log(dim("    local-only - no data sent, local tracking only"));
    const privacyAnswer = await ask(
      rl,
      "  Privacy level? (full/anonymized/local-only) [anonymized]: "
    );
    const privacy = ["full", "anonymized", "local-only"].includes(privacyAnswer)
      ? privacyAnswer
      : "anonymized";

    const config: VantageConfig = {
      ...DEFAULT_CONFIG,
      defaultAgent,
      vantageApiKey: apiKey,
      privacy,
    };

    saveConfig(config);

    console.log("");
    console.log(green("  Configuration saved to ~/.vantage/config.json"));
    console.log(dim(`  Run 'cohrint' to start the REPL, or 'cohrint "your prompt"' for one-shot mode.\n`));

    return config;
  } finally {
    // Only close the readline if we created it here. If the caller passed
    // one in, closing it would end stdin for their REPL.
    if (ownsRl) rl.close();
  }
}
