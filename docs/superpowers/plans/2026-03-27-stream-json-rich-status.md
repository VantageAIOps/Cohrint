# Stream-JSON Rich Status for Claude — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Parse Claude's `--output-format stream-json` to show rich terminal status (thinking, tool use, file operations) and use real API cost data instead of heuristic token counting.

**Architecture:** Add a `stream-parser.ts` module that processes newline-delimited JSON from Claude's stdout. The parser renders rich status lines to stderr (thinking, tool use with file paths) and streams text to stdout. The `result` event provides exact cost/token data from the API. Other agents continue using the plain text runner unchanged.

**Tech Stack:** TypeScript, zero npm dependencies, Claude Code stream-json protocol

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `vantage-cli/src/stream-parser.ts` | Create | Parse JSON lines, render rich status, extract cost |
| `vantage-cli/src/runner.ts` | Modify | Add `runAgentStreamJson()` function |
| `vantage-cli/src/agents/types.ts` | Modify | Add `supportsStreamJson?: boolean` flag |
| `vantage-cli/src/agents/claude.ts` | Modify | Add stream-json flags, set `supportsStreamJson: true` |
| `vantage-cli/src/index.ts` | Modify | Use stream-json runner when agent supports it |
| `vantage-cli/src/tracker.ts` | Modify | Skip heuristic cost when real data available |
| `vantage-cli/src/event-bus.ts` | Modify | Add `cost:real` and `agent:stream_mode` events |
| `tests/suites/21_vantage_cli/test_stream_parser.py` | Create | Source-code verification tests |

---

### Task 1: Create `stream-parser.ts`

**Files:**
- Create: `vantage-cli/src/stream-parser.ts`

- [ ] **Step 1: Create the stream parser module**

Create `vantage-cli/src/stream-parser.ts` with:

- A `TOOL_LABELS` map: `Read` -> "Reading file", `Edit` -> "Editing file", `Write` -> "Writing file", `Grep` -> "Searching code", `Glob` -> "Finding files", `Bash` -> "Running command", `Agent` -> "Running agent"
- A `StreamResult` interface: `{ model, inputTokens, outputTokens, cacheReadTokens, cacheCreationTokens, costUsd, durationMs, text }`
- A `StreamParser` class with:
  - `feed(chunk: Buffer)` — line-buffers input, parses complete JSON lines
  - `flush()` — processes remaining buffer, clears status
  - `getResult(): StreamResult | null` — returns parsed result event
  - `getText(): string` — returns accumulated text output
  - Private handlers for each event type:
    - `assistant` with `thinking` block -> show status "Thinking..."
    - `assistant` with `tool_use` block -> show status with tool label + file path/command detail
    - `assistant` with `text` block -> write text to stdout, clear status
    - `result` -> extract model, tokens, cost from `total_cost_usd`, `usage`, `modelUsage`
    - `system` with `api_retry` -> show "API retry (attempt N)..."
  - Status rendering: write to `process.stderr` with `\r\x1b[K` for clearing, no-op if not TTY
  - Path shortening: show last 2 segments (e.g., "src/index.ts" not full path)

Key design:
- Status lines go to stderr (don't pollute stdout)
- Text output goes to stdout (normal response)
- Non-JSON lines fall through as plain text (graceful degradation)
- No-op in non-TTY mode (pipe/redirect)

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd vantage-cli && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add vantage-cli/src/stream-parser.ts
git commit -m "feat(cli): add stream-json parser for rich Claude status"
```

---

### Task 2: Add Events to Event Bus

**Files:**
- Modify: `vantage-cli/src/event-bus.ts`

- [ ] **Step 1: Add `cost:real` and `agent:stream_mode` event types**

In `event-bus.ts`, add after `"cost:calculated"` (after line 33):

```typescript
  "cost:real": {
    agent: string;
    model: string;
    inputTokens: number;
    outputTokens: number;
    costUsd: number;
    durationMs: number;
  };
  "agent:stream_mode": {
    agent: string;
  };
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd vantage-cli && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add vantage-cli/src/event-bus.ts
git commit -m "feat(cli): add cost:real and agent:stream_mode events"
```

---

### Task 3: Add `runAgentStreamJson()` to Runner

**Files:**
- Modify: `vantage-cli/src/runner.ts`

- [ ] **Step 1: Add imports and new function**

Add import after line 4:
```typescript
import { StreamParser, type StreamResult } from "./stream-parser.js";
```

Add interface after `RunResult` (after line 10):
```typescript
export interface RunStreamResult extends RunResult {
  streamResult: StreamResult | null;
}
```

Add `runAgentStreamJson` function at end of file. It's similar to `runAgent` but:
- Uses `StreamParser` instead of raw stdout piping
- Emits `agent:stream_mode` after spawn
- Emits `cost:real` on close if result has cost data
- Calls `parser.feed(chunk)` on stdout data instead of `process.stdout.write(chunk)`
- Calls `parser.flush()` on close and error
- Returns `RunStreamResult` with `streamResult` from parser
- No spinner needed (parser handles status display)

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd vantage-cli && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add vantage-cli/src/runner.ts
git commit -m "feat(cli): add runAgentStreamJson for rich status rendering"
```

---

### Task 4: Update Tracker to Use Real Cost Data

**Files:**
- Modify: `vantage-cli/src/tracker.ts`

- [ ] **Step 1: Add `expectRealCost` flag and listeners**

Add flag after `lastPromptText` (line 37):
```typescript
  private expectRealCost = false;
```

Add listener in `setupListeners()` for `agent:stream_mode`:
```typescript
    bus.on("agent:stream_mode", () => {
      this.expectRealCost = true;
    });
```

Wrap the existing `agent:completed` handler's cost emission in a guard:
```typescript
    bus.on("agent:completed", (data) => {
      if (this.expectRealCost) {
        // Skip heuristic — real cost will arrive via cost:real
        return;
      }
      // ... existing heuristic code unchanged ...
    });
```

Add `cost:real` listener that re-emits as `cost:calculated`:
```typescript
    bus.on("cost:real", (data) => {
      this.expectRealCost = false;
      const savedCost = this.lastSavedTokens > 0
        ? calculateCost(data.model, this.lastSavedTokens, 0) : 0;
      this.lastSavedTokens = 0;

      bus.emit("cost:calculated", {
        agent: data.agent,
        model: data.model,
        inputTokens: data.inputTokens,
        outputTokens: data.outputTokens,
        costUsd: data.costUsd,
        savedUsd: savedCost,
      });

      // Enqueue dashboard event with real data
      this.enqueue({
        event_id: randomUUID(),
        provider: this.resolveProvider(data.agent),
        model: data.model,
        prompt_tokens: data.inputTokens,
        completion_tokens: data.outputTokens,
        total_tokens: data.inputTokens + data.outputTokens,
        total_cost_usd: data.costUsd,
        latency_ms: data.durationMs,
        environment: "production",
        agent_name: data.agent,
        team: "",
      });
    });
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd vantage-cli && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add vantage-cli/src/tracker.ts
git commit -m "feat(cli): use real API cost from stream-json, skip heuristic"
```

---

### Task 5: Update Claude Adapter with Stream-JSON Flags

**Files:**
- Modify: `vantage-cli/src/agents/types.ts`
- Modify: `vantage-cli/src/agents/claude.ts`

- [ ] **Step 1: Add `supportsStreamJson` to interface**

In `types.ts`, add after `supportsContinue` (line 12):
```typescript
  /** Whether this agent supports --output-format stream-json */
  supportsStreamJson?: boolean;
```

- [ ] **Step 2: Update Claude adapter**

In `claude.ts`, set `supportsStreamJson: true` and update both `buildCommand` and `buildContinueCommand` to include `--verbose --output-format stream-json`:

`buildCommand`:
```typescript
  buildCommand(prompt: string, config?: AgentConfig): SpawnArgs {
    const cmd = config?.command || "claude";
    return {
      command: cmd,
      args: ["--verbose", "--output-format", "stream-json", "-p", prompt],
    };
  },
```

`buildContinueCommand`:
```typescript
  buildContinueCommand(prompt: string, config?: AgentConfig): SpawnArgs {
    const cmd = config?.command || "claude";
    const extraArgs = config?.args?.filter(a => a !== "-p") ?? [];
    return {
      command: cmd,
      args: ["--continue", "--verbose", "--output-format", "stream-json", ...extraArgs, "-p", prompt],
    };
  },
```

- [ ] **Step 3: Verify TypeScript compiles**

Run: `cd vantage-cli && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 4: Commit**

```bash
git add vantage-cli/src/agents/types.ts vantage-cli/src/agents/claude.ts
git commit -m "feat(cli): enable stream-json for Claude adapter"
```

---

### Task 6: Wire Stream-JSON into executePrompt()

**Files:**
- Modify: `vantage-cli/src/index.ts`

- [ ] **Step 1: Update import**

Replace import at line 15:
```typescript
import { runAgent, runAgentBuffered, runAgentStreamJson } from "./runner.js";
```

- [ ] **Step 2: Update executePrompt try block**

Replace the try block in `executePrompt()` (around line 267-272):

```typescript
  try {
    if (stream && agent.supportsStreamJson) {
      await runAgentStreamJson(spawnArgs, agent.name);
    } else if (stream) {
      await runAgent(spawnArgs, agent.name);
    } else {
      await runAgentBuffered(spawnArgs, agent.name);
    }
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    console.error(red(`  Error running ${agent.displayName}: ${message}`));
    console.error(dim(`  Make sure '${agent.binary}' is installed and in your PATH.`));
  }
```

- [ ] **Step 3: Verify TypeScript compiles**

Run: `cd vantage-cli && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 4: Manual test**

Run: `cd vantage-cli && npx tsx src/index.ts`
Type a prompt and verify:
- Rich status appears (Thinking..., tool use with file names)
- Response text streams normally to stdout
- Cost summary shows real API cost data
- Optimization stats still work

- [ ] **Step 5: Commit**

```bash
git add vantage-cli/src/index.ts
git commit -m "feat(cli): wire stream-json runner into REPL for Claude"
```

---

### Task 7: Add Tests

**Files:**
- Create: `tests/suites/21_vantage_cli/test_stream_parser.py`

- [ ] **Step 1: Write source-code verification tests**

Follow the project's `section()`/`chk()` pattern. Target 25+ checks covering:
- stream-parser.ts: exports StreamParser class, StreamResult interface, TOOL_LABELS, feed/flush/getResult/getText methods, handles assistant/tool_result/result/system types, writes to stderr, clears with \x1b[K, no-op for non-TTY
- runner.ts: imports StreamParser, exports runAgentStreamJson and RunStreamResult, emits cost:real and agent:stream_mode
- event-bus.ts: has cost:real and agent:stream_mode event types
- types.ts: has supportsStreamJson field
- claude.ts: has supportsStreamJson: true, --output-format, stream-json, --verbose
- index.ts: imports runAgentStreamJson, checks supportsStreamJson
- tracker.ts: has expectRealCost flag, listens for cost:real and agent:stream_mode
- Other adapters: gemini/codex/aider/chatgpt do NOT have supportsStreamJson
- TypeScript compilation: npx tsc --noEmit returns 0

- [ ] **Step 2: Commit**

```bash
git add tests/suites/21_vantage_cli/test_stream_parser.py
git commit -m "test(cli): add tests for stream-json parser and integration"
```

---

### Task 8: Build, Test, Verify

- [ ] **Step 1: Build**

Run: `cd vantage-cli && npm run build`
Expected: Clean build

- [ ] **Step 2: Run new tests**

Run: `python tests/suites/21_vantage_cli/test_stream_parser.py`
Expected: 25+ checks pass, 0 failures

- [ ] **Step 3: Run existing tests for regressions**

Run: `python tests/suites/21_vantage_cli/test_cli_progress_context.py`
Expected: 25 checks still pass

- [ ] **Step 4: TypeScript check**

Run: `cd vantage-cli && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 5: Commit**

```bash
git commit --allow-empty -m "build(cli): stream-json rich status feature complete"
```
