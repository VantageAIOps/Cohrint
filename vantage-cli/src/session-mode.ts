import { spawn, type ChildProcess } from "node:child_process";
import type { AgentAdapter, AgentConfig } from "./agents/types.js";
import { bus } from "./event-bus.js";
import { countTokens } from "./optimizer.js";
import { calculateCost } from "./pricing.js";
import { dim, green, red } from "./ui.js";

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
    console.log("");

    this.startedAt = Date.now();
    this._ended = false;

    try {
      this.child = spawn(cmd, interactiveArgs, {
        stdio: ["pipe", "pipe", "pipe"],
        env: { ...process.env },
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
      process.stdout.write(chunk);
      this.totalOutputTokens += Math.ceil(chunk.length / 4);
    });

    this.child.stderr?.on("data", (chunk: Buffer) => {
      process.stderr.write(chunk);
    });

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

  /** Send a line to the agent's stdin */
  sendLine(line: string): boolean {
    if (!this.child?.stdin?.writable) {
      console.error(red("  Session not active."));
      return false;
    }

    this.promptCount++;
    this.totalInputTokens += countTokens(line);

    // Check backpressure
    const ok = this.child.stdin.write(line + "\n");
    if (!ok) {
      // Drain will resume — not a fatal error, just slow
      this.child.stdin.once("drain", () => {});
    }
    return true;
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

/** Known agent in-house commands — these get passed through, NOT handled by vantage */
const AGENT_COMMANDS: Record<string, string[]> = {
  claude: ["/compact", "/clear", "/diff", "/help", "/status", "/review", "/simplify",
           "/theme", "/model", "/memory", "/hooks", "/permissions", "/doctor", "/login",
           "/logout", "/config", "/cost", "/vim", "/terminal-setup", "/btw"],
  gemini: ["/clear", "/compress", "/chat", "/help", "/stats", "/model", "/tools", "/memory",
           "/restore", "/search", "/mcp"],
  aider: ["/clear", "/help", "/add", "/drop", "/ls", "/diff", "/undo", "/commit",
          "/run", "/test", "/model", "/map", "/tokens", "/settings", "/reset",
          "/architect", "/ask", "/code", "/voice"],
  codex: ["/clear", "/help", "/model", "/approval"],
  chatgpt: ["/clear", "/help", "/model", "/system"],
};

/** Check if a command is an agent in-house command */
export function isAgentCommand(agentName: string, input: string): boolean {
  const trimmed = input.trim();
  if (trimmed.startsWith("/")) {
    const cmd = trimmed.split(/\s/)[0].toLowerCase();
    const agentCmds = AGENT_COMMANDS[agentName] || [];
    if (agentCmds.includes(cmd)) return true;
  }
  if (trimmed.startsWith("@")) return true;
  if (trimmed.startsWith("!")) return true;
  return false;
}
