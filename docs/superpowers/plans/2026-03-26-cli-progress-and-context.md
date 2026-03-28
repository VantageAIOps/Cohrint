# CLI Progress Indicator & Conversation Context — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix two bugs in vantage-cli: (1) no progress indicator while agent is starting, (2) no conversation context between REPL prompts.

**Architecture:** Add a zero-dependency terminal spinner in `ui.ts` that activates on agent spawn and stops on first output. For context, extend `AgentAdapter` with a `supportsContinue` flag and `buildContinueCommand()` method so Claude (and future agents) can pass `--continue` to maintain conversation state across REPL prompts.

**Tech Stack:** TypeScript, Node.js `readline`, zero npm runtime dependencies

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `vantage-cli/src/ui.ts` | Modify | Add `createSpinner()` function |
| `vantage-cli/src/runner.ts` | Modify | Start/stop spinner around agent execution |
| `vantage-cli/src/agents/types.ts` | Modify | Add `supportsContinue` and `buildContinueCommand` to interface |
| `vantage-cli/src/agents/claude.ts` | Modify | Implement `--continue` support |
| `vantage-cli/src/agents/gemini.ts` | Modify | Implement `--continue` support |
| `vantage-cli/src/index.ts` | Modify | Track REPL prompt count, pass `continue` flag to `executePrompt` |
| `tests/suites/21_vantage_cli/test_cli_progress_context.py` | Create | Tests for spinner + context features |

---

### Task 1: Add Spinner to `ui.ts`

**Files:**
- Modify: `vantage-cli/src/ui.ts`

- [ ] **Step 1: Add `createSpinner()` function to `ui.ts`**

Add after the existing `promptLine()` function (line 136):

```typescript
export interface Spinner {
  stop(): void;
}

export function createSpinner(message: string = "Thinking"): Spinner {
  if (!isTTY) return { stop() {} }; // No spinner in non-TTY (pipe mode)

  const frames = ["\u28CB", "\u28D9", "\u28F9", "\u28F8", "\u28FC", "\u28F4", "\u28E6", "\u28E7", "\u28C7", "\u28CF"];
  let i = 0;
  let stopped = false;

  const interval = setInterval(() => {
    const frame = frames[i % frames.length];
    process.stderr.write(`\r${dim(`  ${frame} ${message}...`)}`);
    i++;
  }, 80);

  return {
    stop() {
      if (stopped) return;
      stopped = true;
      clearInterval(interval);
      process.stderr.write("\r\x1b[K"); // Clear the spinner line
    },
  };
}
```

Key details:
- Uses `process.stderr` so it doesn't pollute stdout (agent output goes to stdout)
- Returns a `Spinner` object with `stop()` — caller controls lifecycle
- No-op in non-TTY mode (pipe/redirect)
- `\r\x1b[K` clears the line completely when stopped

- [ ] **Step 2: Build and verify no TypeScript errors**

Run: `cd vantage-cli && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add vantage-cli/src/ui.ts
git commit -m "feat(cli): add terminal spinner utility for progress feedback"
```

---

### Task 2: Integrate Spinner into `runner.ts`

**Files:**
- Modify: `vantage-cli/src/runner.ts`

- [ ] **Step 1: Import `createSpinner` and add spinner lifecycle to `runAgent()`**

Add import at top of `runner.ts`:
```typescript
import { createSpinner } from "./ui.js";
```

In `runAgent()`, start the spinner before spawn and stop it on the first stdout chunk. Modify the function body — insert spinner start after the spawn try/catch block (after line 45), and stop it in the first `stdout.on("data")` callback:

Replace the `child.stdout?.on("data"` handler (lines 63-73) with:

```typescript
    const spinner = createSpinner("Thinking");
    let firstChunk = true;

    child.stdout?.on("data", (chunk: Buffer) => {
      if (firstChunk) {
        spinner.stop();
        firstChunk = false;
      }
      totalBytes += chunk.length;
      if (totalBytes <= MAX_OUTPUT_BYTES) {
        chunks.push(chunk);
      }
      const ok = process.stdout.write(chunk);
      if (!ok) {
        child.stdout?.pause();
        process.stdout.once("drain", () => child.stdout?.resume());
      }
    });
```

Also stop the spinner on error and timeout. In the `child.on("error")` handler (line 79), add `spinner.stop()` before `reject()`. In the timeout block (line 50), add `spinner.stop()` before `child.kill()`.

Updated error handler:
```typescript
    child.on("error", (err) => {
      clearTimeout(timer);
      spinner.stop();
      if ((err as NodeJS.ErrnoException).code === "ENOENT") {
        reject(new Error(`'${spawnArgs.command}' not found. Install it or check your PATH.`));
      } else {
        reject(new Error(`Agent process error: ${err.message}`));
      }
    });
```

Updated timeout block:
```typescript
    const timer = setTimeout(() => {
      timedOut = true;
      spinner.stop();
      child.kill("SIGTERM");
      setTimeout(() => { if (!child.killed) child.kill("SIGKILL"); }, grace);
    }, timeoutMs);
```

Also stop spinner on close in case no stdout was received:
```typescript
    child.on("close", (code) => {
      clearTimeout(timer);
      spinner.stop();
      // ... rest of existing handler
    });
```

- [ ] **Step 2: Build and verify no TypeScript errors**

Run: `cd vantage-cli && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 3: Manual test — run vantage CLI and verify spinner appears**

Run: `cd vantage-cli && npx tsx src/index.ts`
Type a prompt and verify:
- Spinner animation appears immediately after pressing Enter
- Spinner disappears when agent starts responding
- Agent output streams normally after spinner stops

- [ ] **Step 4: Commit**

```bash
git add vantage-cli/src/runner.ts
git commit -m "feat(cli): show spinner while waiting for agent response"
```

---

### Task 3: Extend `AgentAdapter` Interface for Conversation Context

**Files:**
- Modify: `vantage-cli/src/agents/types.ts`

- [ ] **Step 1: Add `supportsContinue` and `buildContinueCommand` to `AgentAdapter`**

Replace the full `types.ts` content:

```typescript
export interface AgentAdapter {
  name: string;
  displayName: string;
  binary: string;
  defaultModel: string;
  provider: string;
  /** Args for interactive mode (no -p flag) — used by /session */
  interactiveArgs?: string[];
  /** Command to exit the agent's interactive session */
  exitCommand?: string;
  /** Whether this agent supports --continue for conversation context */
  supportsContinue?: boolean;
  detect(): Promise<boolean>;
  buildCommand(prompt: string, config?: AgentConfig): SpawnArgs;
  /** Build command that continues a previous conversation. Falls back to buildCommand if not supported. */
  buildContinueCommand?(prompt: string, config?: AgentConfig): SpawnArgs;
}

export interface AgentConfig {
  command: string;
  args: string[];
  model: string;
  detected: boolean;
}

export interface SpawnArgs {
  command: string;
  args: string[];
  env?: Record<string, string>;
}
```

- [ ] **Step 2: Build and verify no TypeScript errors**

Run: `cd vantage-cli && npx tsc --noEmit`
Expected: No errors (new fields are optional, so existing adapters still compile)

- [ ] **Step 3: Commit**

```bash
git add vantage-cli/src/agents/types.ts
git commit -m "feat(cli): extend AgentAdapter with conversation continue support"
```

---

### Task 4: Implement `--continue` in Claude Adapter

**Files:**
- Modify: `vantage-cli/src/agents/claude.ts`

- [ ] **Step 1: Add `supportsContinue` and `buildContinueCommand` to Claude adapter**

Replace the full `claude.ts` content:

```typescript
import { execSync } from "node:child_process";
import type { AgentAdapter, AgentConfig, SpawnArgs } from "./types.js";

export const claudeAdapter: AgentAdapter = {
  name: "claude",
  displayName: "Claude Code",
  binary: "claude",
  defaultModel: "claude-sonnet-4-6",
  provider: "anthropic",
  interactiveArgs: [],
  exitCommand: "/quit",
  supportsContinue: true,

  async detect(): Promise<boolean> {
    try {
      execSync("which claude", { stdio: "ignore", timeout: 5000 });
      return true;
    } catch {
      return false;
    }
  },

  buildCommand(prompt: string, config?: AgentConfig): SpawnArgs {
    const cmd = config?.command || "claude";
    const baseArgs = config?.args ?? ["-p"];
    return {
      command: cmd,
      args: [...baseArgs, prompt],
    };
  },

  buildContinueCommand(prompt: string, config?: AgentConfig): SpawnArgs {
    const cmd = config?.command || "claude";
    return {
      command: cmd,
      args: ["--continue", "-p", prompt],
    };
  },
};
```

Key detail: `--continue` tells Claude Code to resume the most recent conversation. This is exactly what we want for REPL follow-up prompts.

- [ ] **Step 2: Build and verify no TypeScript errors**

Run: `cd vantage-cli && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add vantage-cli/src/agents/claude.ts
git commit -m "feat(cli): add --continue support to Claude adapter"
```

---

### Task 5: Implement `--continue` in Gemini Adapter

**Files:**
- Modify: `vantage-cli/src/agents/gemini.ts`

- [ ] **Step 1: Add `supportsContinue` and `buildContinueCommand` to Gemini adapter**

Replace the full `gemini.ts` content:

```typescript
import { execSync } from "node:child_process";
import type { AgentAdapter, AgentConfig, SpawnArgs } from "./types.js";

export const geminiAdapter: AgentAdapter = {
  name: "gemini",
  displayName: "Gemini CLI",
  binary: "gemini",
  defaultModel: "gemini-2.0-flash",
  provider: "google",
  interactiveArgs: [],
  exitCommand: "/quit",
  supportsContinue: true,

  async detect(): Promise<boolean> {
    try {
      execSync("which gemini", { stdio: "ignore", timeout: 5000 });
      return true;
    } catch {
      return false;
    }
  },

  buildCommand(prompt: string, config?: AgentConfig): SpawnArgs {
    const cmd = config?.command || "gemini";
    const baseArgs = config?.args ?? ["-p"];
    return {
      command: cmd,
      args: [...baseArgs, prompt],
    };
  },

  buildContinueCommand(prompt: string, config?: AgentConfig): SpawnArgs {
    const cmd = config?.command || "gemini";
    return {
      command: cmd,
      args: ["--continue", "-p", prompt],
    };
  },
};
```

- [ ] **Step 2: Build and verify no TypeScript errors**

Run: `cd vantage-cli && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add vantage-cli/src/agents/gemini.ts
git commit -m "feat(cli): add --continue support to Gemini adapter"
```

---

### Task 6: Wire Conversation Context into REPL and `executePrompt()`

**Files:**
- Modify: `vantage-cli/src/index.ts`

- [ ] **Step 1: Add `continueConversation` parameter to `executePrompt()`**

Update the `executePrompt` function signature and body (around line 232) to accept a `continueConversation` flag:

```typescript
async function executePrompt(
  prompt: string,
  agent: AgentAdapter,
  config: VantageConfig,
  stream: boolean = true,
  continueConversation: boolean = false
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

  // Build command — use continue if this is a follow-up prompt
  const useContinue = continueConversation && agent.supportsContinue && agent.buildContinueCommand;
  const spawnArgs = useContinue
    ? agent.buildContinueCommand!(finalPrompt)
    : agent.buildCommand(finalPrompt);

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
```

- [ ] **Step 2: Track prompt count per agent in REPL and pass `continueConversation`**

In `startRepl()`, add a prompt counter map after `let activeSession` (line 337):

```typescript
  // Track per-agent prompt count for --continue support
  const agentPromptCount = new Map<string, number>();
```

Then update the "Normal prompt" block (around line 585) to increment and pass the flag:

```typescript
        // Normal prompt — use current default agent
        const costPromise = waitForCost();
        const count = agentPromptCount.get(currentAgent.name) ?? 0;
        agentPromptCount.set(currentAgent.name, count + 1);
        await executePrompt(line, currentAgent, config, true, count > 0);
```

And update the "Agent prefix commands" block (around line 534) similarly:

```typescript
        if (agentPrefixMatch) {
          const [, agentName, rawAgentPrompt] = agentPrefixMatch;
          const agentPrompt = rawAgentPrompt.trim();
          const agent = getAgent(agentName);
          if (agent && agentPrompt) {
            const costPromise = waitForCost();
            const count = agentPromptCount.get(agent.name) ?? 0;
            agentPromptCount.set(agent.name, count + 1);
            await executePrompt(agentPrompt, agent, config, true, count > 0);
```

- [ ] **Step 3: Build and verify no TypeScript errors**

Run: `cd vantage-cli && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 4: Manual test — verify conversation context works**

Run: `cd vantage-cli && npx tsx src/index.ts`
Test this sequence:
1. Type: `What are the 3 primary colors?`
2. Wait for response
3. Type: `Can you list them in reverse order?`
4. Verify: Agent references the previous answer (primary colors) instead of saying "I don't have context"

- [ ] **Step 5: Commit**

```bash
git add vantage-cli/src/index.ts
git commit -m "feat(cli): wire --continue for conversation context in REPL"
```

---

### Task 7: Add Tests

**Files:**
- Create: `tests/suites/21_vantage_cli/test_cli_progress_context.py`

- [ ] **Step 1: Read existing test patterns**

Read `tests/suites/21_vantage_cli/test_vantage_cli.py` and `tests/suites/21_vantage_cli/conftest.py` to understand the test helpers and patterns used.

- [ ] **Step 2: Write tests for spinner and context features**

Create `tests/suites/21_vantage_cli/test_cli_progress_context.py` with tests covering:
- Spinner function exists and exports correctly in ui.ts
- Spinner uses stderr (not stdout) to avoid polluting agent output
- Spinner clears line on stop
- Spinner no-ops in non-TTY mode
- Runner imports and uses createSpinner
- Runner calls spinner.stop() on first chunk, error, timeout, and close
- Claude adapter has supportsContinue: true
- Claude adapter has buildContinueCommand with --continue flag
- Gemini adapter has supportsContinue: true and --continue
- AgentAdapter interface has new optional fields
- index.ts tracks agentPromptCount and passes continueConversation
- Aider/Codex/ChatGPT adapters unchanged (no supportsContinue)
- TypeScript compiles without errors
- Pipe mode suppresses spinner (no spinner frames in stderr)

Target: 20+ checks, 0 failures.

- [ ] **Step 3: Commit**

```bash
git add tests/suites/21_vantage_cli/test_cli_progress_context.py
git commit -m "test(cli): add tests for spinner and conversation context"
```

---

### Task 8: Build, Run Tests, Final Verification

- [ ] **Step 1: Build the CLI**

Run: `cd vantage-cli && npm run build`
Expected: Clean build, no errors

- [ ] **Step 2: Run the new test suite**

Run: `python tests/suites/21_vantage_cli/test_cli_progress_context.py`
Expected: All checks pass (20+ checks, 0 failures)

- [ ] **Step 3: Run existing CLI tests to verify no regressions**

Run: `python -m pytest tests/suites/21_vantage_cli/ -v`
Expected: All existing tests still pass

- [ ] **Step 4: Run TypeScript type check**

Run: `cd vantage-cli && npm run typecheck`
Expected: No errors

- [ ] **Step 5: Final commit with build artifacts**

```bash
git add -A vantage-cli/dist/
git commit -m "build(cli): rebuild dist after spinner + context features"
```
