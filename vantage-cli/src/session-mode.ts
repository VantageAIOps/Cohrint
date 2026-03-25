import { spawn, type ChildProcess } from "node:child_process";
import type { AgentAdapter, AgentConfig } from "./agents/types.js";
import { bus } from "./event-bus.js";
import { countTokens } from "./optimizer.js";
import { calculateCost } from "./pricing.js";
import { dim, green, red, yellow } from "./ui.js";
import { processInput, printOptStatus, type OptMode, type ProcessedInput } from "./input-classifier.js";

/**
 * Interactive session — agent process stays alive, stdin/stdout piped through.
 * Supports agent in-house commands (/compact, /clear, !shell, @file, etc.)
 */
export class AgentSession {
  private child: ChildProcess | null = null;
  private agentName: string;
  private model: string;
  private startedAt: number = 0;
  private totalInputTokens = 0;
  private totalOutputTokens = 0;
  private promptCount = 0;
  private _ended = false;
  private optMode: OptMode = "auto";
  private totalSavedTokens = 0;

  constructor(
    private agent: AgentAdapter,
    private config?: AgentConfig,
  ) {
    this.agentName = agent.name;
    this.model = config?.model || agent.defaultModel;
  }

  /** Start the agent in interactive mode. Returns true if started OK. */
  async start(): Promise<boolean> {
    const cmd = this.config?.command || this.agent.binary;
    const interactiveArgs = this.agent.interactiveArgs ?? [];

    console.log(dim(`  Starting ${this.agent.displayName} session...`));
    console.log(dim(`  Agent commands work: /compact, /clear, @file, !shell, /help`));
    console.log(dim(`  Type /exit-session to return to vantage REPL.`));
    console.log(dim(`  Optimization: auto (use /opt-off to disable, /opt-ask to confirm each)`));
    console.log("");

    this.startedAt = Date.now();
    this._ended = false;

    try {
      // stdin: pipe (we write to it), stdout: pipe (we read from it),
      // stderr: inherit (agent prompts like "Allow edit? (y/n)" show directly to user)
      this.child = spawn(cmd, interactiveArgs, {
        stdio: ["pipe", "pipe", "inherit"],
        env: { ...process.env, TERM: process.env.TERM || "xterm-256color" },
      });
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      console.error(red(`  Failed to start ${this.agent.displayName}: ${msg}`));
      return false;
    }

    if (!this.child.pid) {
      console.error(red(`  Failed to start ${this.agent.displayName} — no PID.`));
      this.child = null;
      return false;
    }

    this.child.stdout?.on("data", (chunk: Buffer) => {
      const ok = process.stdout.write(chunk);
      if (!ok) {
        this.child?.stdout?.pause();
        process.stdout.once("drain", () => this.child?.stdout?.resume());
      }
      this.totalOutputTokens += Math.ceil(chunk.length / 4);
    });

    // stderr is inherited — agent prompts (file approval, etc.) show directly
    // No need to listen for stderr data

    this.child.on("error", (err) => {
      if ((err as NodeJS.ErrnoException).code === "ENOENT") {
        console.error(red(`  '${cmd}' not found. Install it or check your PATH.`));
      } else {
        console.error(red(`  Session error: ${err.message}`));
      }
      this.cleanup();
    });

    // Use BOTH close and exit to ensure cleanup
    this.child.on("exit", () => this.cleanup());
    this.child.on("close", () => this.cleanup());

    return true;
  }

  /** Process and send a line to the agent's stdin */
  async sendLine(line: string): Promise<ProcessedInput | null> {
    if (!this.child?.stdin?.writable) {
      console.error(red("  Session not active."));
      return null;
    }

    // Handle optimization mode commands
    if (line.trim() === "/opt-on" || line.trim() === "/opt-auto") {
      this.optMode = "auto";
      console.log(green("  Optimization: auto (optimizes prompts >=5 words)"));
      return null; // Don't forward to agent
    }
    if (line.trim() === "/opt-off" || line.trim() === "/opt-never") {
      this.optMode = "never";
      console.log(yellow("  Optimization: off (all input passed through as-is)"));
      return null;
    }
    if (line.trim() === "/opt-ask") {
      this.optMode = "ask";
      console.log(yellow("  Optimization: ask (will confirm before optimizing)"));
      return null;
    }
    if (line.trim() === "/opt-always") {
      this.optMode = "always";
      console.log(green("  Optimization: always (optimizes everything including short inputs)"));
      return null;
    }

    // Process through smart pipeline
    const result = processInput(line, this.agentName, this.optMode);

    // For vantage commands, don't forward
    if (result.type === "vantage-command") return result;

    // Print optimization status
    printOptStatus(result);

    // Track stats
    this.promptCount++;
    this.totalInputTokens += result.forwarded.split(/\s+/).length;
    this.totalSavedTokens += result.savedTokens;

    // Forward to agent with backpressure handling
    const ok = this.child.stdin.write(result.forwarded + "\n");
    if (!ok) {
      await new Promise<void>((resolve) => {
        this.child?.stdin?.once("drain", resolve) ?? resolve();
      });
    }

    return result;
  }

  /** Check if session is running */
  isActive(): boolean {
    return this.child !== null && !this.child.killed && !this._ended;
  }

  /** End the session gracefully */
  async end(): Promise<void> {
    if (!this.child || this._ended) return;

    const exitCmd = this.agent.exitCommand ?? "/quit";
    if (this.child.stdin?.writable) {
      this.child.stdin.write(exitCmd + "\n");
    }

    // Wait for close with timeout
    await new Promise<void>((resolve) => {
      const timeout = setTimeout(() => {
        if (this.child && !this.child.killed) {
          this.child.kill("SIGTERM");
          setTimeout(() => {
            if (this.child && !this.child.killed) this.child.kill("SIGKILL");
          }, 2000);
        }
        resolve();
      }, 3000);

      // Use once() to avoid listener accumulation
      if (this.child) {
        this.child.once("close", () => {
          clearTimeout(timeout);
          resolve();
        });
      } else {
        clearTimeout(timeout);
        resolve();
      }
    });

    this.cleanup();
  }

  private cleanup(): void {
    if (this._ended) return;
    this._ended = true;
    this.printSessionStats();
    this.child = null;
  }

  private printSessionStats(): void {
    const duration = Date.now() - this.startedAt;
    if (duration < 100) return; // Don't print stats for instant failures
    const cost = calculateCost(this.model, this.totalInputTokens, this.totalOutputTokens);

    console.log("");
    console.log(dim("  +----- Session Ended -----+"));
    console.log(`  ${dim("Agent:")}           ${this.agent.displayName}`);
    console.log(`  ${dim("Duration:")}         ${(duration / 1000).toFixed(0)}s`);
    console.log(`  ${dim("Prompts:")}          ${this.promptCount}`);
    if (this.totalSavedTokens > 0) {
      console.log(`  ${dim("Tokens saved:")}     ${green(this.totalSavedTokens.toString())}`);
    }
    console.log(`  ${dim("Est. cost:")}        ${green("$" + cost.toFixed(6))}`);
    console.log(dim("  +---------------------------+"));
    console.log("");

    bus.emit("agent:completed", {
      agent: this.agentName,
      exitCode: 0,
      outputText: "",
      durationMs: duration,
    });
  }
}

// Re-export for backward compatibility
export { isAgentCommand } from "./input-classifier.js";
