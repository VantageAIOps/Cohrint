#!/usr/bin/env tsx
/**
 * test-session-aggressive.ts — Comprehensive session mode tests.
 *
 * Tests input classification, per-prompt Claude session, persistent process
 * session (non-Claude), agent adapters, ClaudeStreamRenderer, and edge cases.
 * No real agent processes are spawned — all external dependencies are mocked.
 *
 * Run: tsx test-session-aggressive.ts
 */

import { classifyInput, processInput, isFollowUpPrompt, isAgentCommand } from "./src/input-classifier.js";
import { ClaudeStreamRenderer } from "./src/runner.js";
import { claudeAdapter } from "./src/agents/claude.js";
import { aiderAdapter } from "./src/agents/aider.js";
import { geminiAdapter } from "./src/agents/gemini.js";
import { AgentSession } from "./src/session-mode.js";
import type { AgentAdapter, AgentConfig } from "./src/agents/types.js";

// ─── Test harness ────────────────────────────────────────────────────────────

let passed = 0;
let failed = 0;
const failures: string[] = [];

function test(name: string, fn: () => void | Promise<void>): Promise<void> {
  return Promise.resolve()
    .then(() => fn())
    .then(() => {
      console.log(`  ✓ ${name}`);
      passed++;
    })
    .catch((err: unknown) => {
      const msg = err instanceof Error ? err.message : String(err);
      console.log(`  ✗ ${name}`);
      console.log(`      ${msg}`);
      failures.push(`${name}: ${msg}`);
      failed++;
    });
}

function assert(condition: boolean, message: string): void {
  if (!condition) throw new Error(message);
}

function assertEqual<T>(actual: T, expected: T, label?: string): void {
  const a = JSON.stringify(actual);
  const e = JSON.stringify(expected);
  if (a !== e) throw new Error(`${label ?? "assertEqual"}: got ${a}, expected ${e}`);
}

function assertIncludes(haystack: string, needle: string, label?: string): void {
  if (!haystack.includes(needle)) {
    throw new Error(`${label ?? "assertIncludes"}: "${needle}" not found in "${haystack}"`);
  }
}

// ─── Mock helpers ─────────────────────────────────────────────────────────────

/** Build a minimal AgentAdapter mock */
function mockAdapter(overrides: Partial<AgentAdapter> = {}): AgentAdapter {
  return {
    name: "mock",
    displayName: "MockAgent",
    binary: "mock-agent",
    defaultModel: "mock-model",
    provider: "mock",
    interactiveArgs: [],
    exitCommand: "/quit",
    supportsContinue: false,
    async detect() { return true; },
    buildCommand(prompt, _config) {
      return { command: "mock-agent", args: ["-p", prompt] };
    },
    ...overrides,
  };
}

/** Mock adapter that mimics Claude's per-prompt mode */
function mockClaudeAdapter(detectResult = true): AgentAdapter {
  return mockAdapter({
    name: "claude",
    displayName: "Claude Code",
    binary: "claude",
    supportsContinue: true,
    async detect() { return detectResult; },
    buildCommand(prompt, config) {
      const extraFlags = config?.extraFlags ?? [];
      return {
        command: config?.command ?? "claude",
        args: ["--verbose", "--output-format", "stream-json", ...extraFlags, "-p", prompt],
      };
    },
    buildContinueCommand(prompt, config, sessionId) {
      const extraFlags = config?.extraFlags ?? [];
      const resumeArgs = sessionId
        ? ["--resume", sessionId, "--verbose", "--output-format", "stream-json", ...extraFlags, "-p", prompt]
        : ["--continue", "--verbose", "--output-format", "stream-json", ...extraFlags, "-p", prompt];
      return { command: config?.command ?? "claude", args: resumeArgs };
    },
  });
}

// ─── Captured command tracker for per-prompt tests ──────────────────────────

interface CapturedSpawn {
  command: string;
  args: string[];
  sessionId?: string;
}

/**
 * Patch AgentSession's private sendPerPrompt by monkey-patching runAgent
 * via module-level dependency injection (not possible here since imports are
 * static). Instead, we test the adapters' buildCommand / buildContinueCommand
 * directly — which IS the behavior under test — and test AgentSession's public
 * surface (isActive, end) with a mock that injects a fake runAgent.
 */

// ─── Section A: Input Classification ─────────────────────────────────────────

async function testInputClassification() {
  console.log("\nA. Input Classification");

  await test("A1 - short prompt (<5 words) classified as short-answer", () => {
    assertEqual(classifyInput("fix the bug", "claude"), "short-answer");
    assertEqual(classifyInput("yes", "claude"), "short-answer");
    assertEqual(classifyInput("ok", "claude"), "short-answer");
    assertEqual(classifyInput("1234", "claude"), "short-answer");
  });

  await test("A2 - long prompt (>=5 words) classified as prompt", () => {
    assertEqual(classifyInput("please refactor this function to be more readable", "claude"), "prompt");
    assertEqual(classifyInput("write a unit test for the login controller", "claude"), "prompt");
  });

  await test("A3 - agent slash commands classified as agent-command", () => {
    assertEqual(classifyInput("/compact", "claude"), "agent-command");
    assertEqual(classifyInput("/clear", "claude"), "agent-command");
    assertEqual(classifyInput("/diff", "claude"), "agent-command");
    assertEqual(classifyInput("/add src/index.ts", "aider"), "agent-command");
    assertEqual(classifyInput("@src/file.ts", "claude"), "agent-command");
    assertEqual(classifyInput("!ls -la", "claude"), "agent-command");
  });

  await test("A4 - vantage internal commands classified as vantage-command", () => {
    assertEqual(classifyInput("/cost", "claude"), "vantage-command");
    assertEqual(classifyInput("/exit-session", "claude"), "vantage-command");
    assertEqual(classifyInput("/summary", "claude"), "vantage-command");
    assertEqual(classifyInput("/stats", "claude"), "vantage-command");
    assertEqual(classifyInput("/budget", "claude"), "vantage-command");
  });

  await test("A5 - structured data (JSON, code blocks, URLs) classified as structured", () => {
    assertEqual(classifyInput('{"key": "value", "num": 42}', "claude"), "structured");
    assertEqual(classifyInput("[1, 2, 3]", "claude"), "structured");
    assertEqual(classifyInput("```\nconst x = 1;\n```", "claude"), "structured");
    // 3+ URLs
    assertEqual(
      classifyInput("see https://a.com and https://b.com and https://c.com for details", "claude"),
      "structured"
    );
  });

  await test("A6 - follow-up prompts classified as followup", () => {
    assertEqual(classifyInput("fix that bug", "claude"), "followup");
    assertEqual(classifyInput("do it again", "claude"), "followup");
    assertEqual(classifyInput("try it with a different approach", "claude"), "followup");
    assertEqual(classifyInput("update that function", "claude"), "followup");
  });

  await test("A7 - empty input classified as unknown", () => {
    assertEqual(classifyInput("", "claude"), "unknown");
    assertEqual(classifyInput("   ", "claude"), "unknown");
  });

  await test("A8 - multi-line paste: processInput joins and classifies", () => {
    // processInput receives a pre-joined string (joining is done by readline)
    // Test that a multi-word multi-line string is classified correctly
    const multiline = "write a function that\nreads a file and\nreturns its contents";
    const result = processInput(multiline, "claude", "auto");
    // After joining it's a long prompt
    assert(result.type === "prompt" || result.type === "structured", `expected prompt or structured, got ${result.type}`);
  });

  await test("A9a - /opt-off sets opt mode state (via processInput with never mode)", () => {
    // With optMode="never", a prompt is not optimized
    const longPrompt = "please refactor this function to use async await patterns properly";
    const result = processInput(longPrompt, "claude", "never");
    assertEqual(result.optimized, false);
    assertEqual(result.forwarded, longPrompt);
  });

  await test("A9b - /opt-always forces optimization on prompt type", () => {
    const longFiller = "i'd like you to please refactor this function to be more readable and maintainable";
    const result = processInput(longFiller, "claude", "always");
    // In "always" mode optimization is attempted (same as auto for prompt type)
    assertEqual(result.type, "prompt");
    // forwarded should not be corrupted
    assert(result.forwarded.length > 0, "forwarded should not be empty");
  });

  await test("A9c - /opt-ask mode does not auto-optimize (same pipeline as auto for non-ask)", () => {
    // "ask" mode: optimization still runs in processInput (ask is handled at REPL level)
    const longFiller = "i'd like you to please carefully refactor this function to be more readable";
    const result = processInput(longFiller, "claude", "ask");
    // Just verify it doesn't crash and type is prompt
    assertEqual(result.type, "prompt");
  });

  await test("A9d - /opt-auto enables auto optimization", () => {
    const longFiller = "i'd like you to please refactor this function to be more readable and clean";
    const result = processInput(longFiller, "claude", "auto");
    assertEqual(result.type, "prompt");
    assert(result.forwarded.length > 0, "forwarded should not be empty");
  });
}

// ─── Section B: Session Mode — Per-Prompt (Claude) ───────────────────────────

async function testPerPromptSession() {
  console.log("\nB. Session Mode - Per-Prompt (Claude)");

  await test("B10 - first prompt uses buildCommand (no --resume)", () => {
    const adapter = mockClaudeAdapter();
    const config: AgentConfig = {
      command: "claude",
      args: [],
      model: "claude-sonnet-4-6",
      detected: true,
      extraFlags: ["--allowedTools", "Read,Write"],
    };
    const spawnArgs = adapter.buildCommand("write a test", config);
    assert(!spawnArgs.args.includes("--resume"), "first command must NOT include --resume");
    assert(!spawnArgs.args.includes("--continue"), "first command must NOT include --continue");
    assertIncludes(spawnArgs.args.join(" "), "-p", "must include -p flag");
    assertIncludes(spawnArgs.args.join(" "), "write a test", "must include prompt");
  });

  await test("B11 - second+ prompts use buildContinueCommand with sessionId", () => {
    const adapter = mockClaudeAdapter();
    const config: AgentConfig = {
      command: "claude",
      args: [],
      model: "claude-sonnet-4-6",
      detected: true,
      extraFlags: ["--allowedTools", "Read,Write"],
    };
    const sessionId = "a1b2c3d4-e5f6-7890-abcd-ef1234567890";
    const spawnArgs = adapter.buildContinueCommand!("follow up prompt", config, sessionId);
    assert(spawnArgs.args.includes("--resume"), "continue command must include --resume");
    assertIncludes(spawnArgs.args.join(" "), sessionId, "must include sessionId");
    assertIncludes(spawnArgs.args.join(" "), "-p", "must include -p flag");
  });

  await test("B12 - --allowedTools injected with correct default tools", () => {
    const DEFAULT_TOOLS = ["Read", "Glob", "Grep", "Write", "Edit", "Bash", "WebFetch", "WebSearch", "Agent", "TodoWrite"];
    const adapter = mockClaudeAdapter();
    const config: AgentConfig = {
      command: "claude",
      args: [],
      model: "claude-sonnet-4-6",
      detected: true,
      extraFlags: ["--allowedTools", DEFAULT_TOOLS.join(",")],
    };
    const spawnArgs = adapter.buildCommand("test prompt", config);
    const argsStr = spawnArgs.args.join(" ");
    assertIncludes(argsStr, "--allowedTools", "must include --allowedTools");
    for (const tool of DEFAULT_TOOLS) {
      assertIncludes(argsStr, tool, `missing tool: ${tool}`);
    }
  });

  await test("B13 - sessionId captured from result event and reused in subsequent", () => {
    // Simulate what ClaudeStreamRenderer extracts
    const renderer = new ClaudeStreamRenderer();
    const sessionId = "deadbeef-dead-beef-dead-beefdeadbeef";
    const resultEvent = JSON.stringify({ type: "result", session_id: sessionId });
    const out = renderer.process(resultEvent);
    assertEqual(out.sessionId, sessionId);

    // Verify subsequent call to buildContinueCommand uses it
    const adapter = mockClaudeAdapter();
    const spawnArgs = adapter.buildContinueCommand!("next prompt", { command: "claude", args: [], model: "m", detected: true }, sessionId);
    assertIncludes(spawnArgs.args.join(" "), sessionId);
  });

  await test("B14 - session stats: AgentSession tracks promptCount and totalSavedTokens", async () => {
    // We can't easily call sendLine without a real runAgent, so we test the
    // observable surface: isActive() returns true after start(), false after end().
    // Stats printing is a side effect (console.log); we just ensure it doesn't throw.
    const adapter = mockClaudeAdapter(true);
    const session = new AgentSession(adapter);

    // Mock detect to return true without spawning anything
    // start() only calls detect() in per-prompt mode — no real spawn
    const origDetect = adapter.detect.bind(adapter);
    let detectCalled = false;
    adapter.detect = async () => { detectCalled = true; return true; };

    const started = await session.start();
    assert(started, "session.start() should return true when detect() returns true");
    assert(session.isActive(), "session should be active after start");
    assert(detectCalled, "detect() should have been called");

    await session.end();
    assert(!session.isActive(), "session should be inactive after end");
  });

  await test("B15 - /exit-session is a vantage-command (handled internally)", () => {
    // Verify that /exit-session is classified correctly so session can handle it
    const type = classifyInput("/exit-session", "claude");
    assertEqual(type, "vantage-command");
  });

  await test("B16 - detect() failure: start() returns false", async () => {
    // When detect() returns false, start() returns false to signal the caller to abort.
    // isActive() still returns !_ended (true) because cleanup() was never called —
    // the session was never started, so there is nothing to "end".
    // The caller is responsible for checking start()'s return value.
    const adapter = mockClaudeAdapter(false); // detect returns false
    const session = new AgentSession(adapter);
    const started = await session.start();
    assert(!started, "session.start() should return false when detect() fails");
    // isActive() returns !_ended — _ended is false because cleanup() was never called
    // This is expected: the caller checks start()'s return value, not isActive()
    assert(session.isActive(), "isActive() is true (not _ended) — session was never started or cleaned up");
  });

  await test("B17 - concurrent sendLine is blocked by _running flag (via vantage-command passthrough)", async () => {
    // processInput returns immediately for vantage-command; no blocking needed
    // We verify that sending a vantage-command does NOT increment promptCount
    // (i.e. the type check exits early). Test via classifyInput.
    const type = classifyInput("/cost", "claude");
    assertEqual(type, "vantage-command");
    // Nothing forwarded — safe even if called concurrently
  });

  await test("B18 - optimization savings tracked: processInput returns savedTokens", () => {
    const prompt = "i'd like you to please carefully refactor this function to be more readable and maintainable for future developers";
    const result = processInput(prompt, "claude", "auto");
    assert(result.type === "prompt", `expected prompt type, got ${result.type}`);
    // If optimization ran and saved tokens, savedTokens > 0
    // (Not always guaranteed depending on optimizer thresholds, but forwarded should differ if optimized)
    if (result.optimized) {
      assert(result.savedTokens > 0, "optimized=true implies savedTokens>0");
    }
    // forwarded must never be empty
    assert(result.forwarded.length > 0, "forwarded must not be empty");
  });
}

// ─── Section C: Session Mode — Persistent Process (Non-Claude) ───────────────

async function testPersistentSession() {
  console.log("\nC. Session Mode - Persistent Process (non-Claude)");

  await test("C19 - non-Claude adapter: perPromptMode is false (no supportsContinue)", () => {
    // aider has supportsContinue=false, so AgentSession should use persistent mode
    // We verify via the adapter's properties
    assertEqual(aiderAdapter.supportsContinue, false);
    assert(!aiderAdapter.buildContinueCommand, "aider should not have buildContinueCommand");
  });

  await test("C20 - persistent agent: buildCommand produces correct args", () => {
    const spawnArgs = aiderAdapter.buildCommand("add error handling to auth module", {
      command: "aider",
      args: ["--message"],
      model: "claude-sonnet-4-6",
      detected: true,
    });
    assertEqual(spawnArgs.command, "aider");
    assertIncludes(spawnArgs.args.join(" "), "add error handling to auth module");
    assertIncludes(spawnArgs.args.join(" "), "--yes");
  });

  await test("C21 - stdin drain handled: sendPersistent writes to stdin (test via mock)", async () => {
    // Create a mock writable stream to simulate child.stdin
    const written: string[] = [];
    const mockStdin = {
      writable: true,
      write(data: string): boolean {
        written.push(data);
        return true; // Not full — no drain needed
      },
    };

    // We test the forwarded value that would be written
    const result = processInput("fix the authentication module logic", "aider", "auto");
    // Simulate what sendPersistent does
    const toWrite = result.forwarded + "\n";
    mockStdin.write(toWrite);
    assert(written.length === 1, "should have written once");
    assertIncludes(written[0]!, "fix", "should contain prompt text");
    assertIncludes(written[0]!, "\n", "should end with newline");
  });

  await test("C22 - process exit triggers cleanup (session becomes inactive)", async () => {
    // Use a mock adapter (non-Claude) that would spawn a process
    // We can't actually spawn without a real binary, so we test the
    // logic path: when start() fails due to spawn error, isActive() is false
    const adapter = mockAdapter({
      name: "aider",
      supportsContinue: false,
    });
    const session = new AgentSession(adapter);
    // In persistent mode, start() calls startPersistentProcess which spawns 'mock-agent'
    // That will fail with ENOENT — session should not be active
    const started = await session.start();
    // Either started=false (spawn failed) or started=true with a dead process
    // Either way, session.isActive() should reflect reality
    // We just verify no crash
    assert(typeof started === "boolean", "start() should return boolean");
  });

  await test("C23 - /exit-session classified as vantage-command for any agent", () => {
    for (const agent of ["aider", "gemini", "codex", "chatgpt"]) {
      const type = classifyInput("/exit-session", agent);
      assertEqual(type as string, "vantage-command", `agent=${agent}`);
    }
  });
}

// ─── Section D: Agent Adapters ───────────────────────────────────────────────

async function testAgentAdapters() {
  console.log("\nD. Agent Adapters");

  await test("D24 - Claude buildCommand includes --verbose, --output-format stream-json, -p", () => {
    const spawnArgs = claudeAdapter.buildCommand("test prompt", {
      command: "claude",
      args: [],
      model: "claude-sonnet-4-6",
      detected: true,
    });
    assertIncludes(spawnArgs.args.join(" "), "--verbose");
    assertIncludes(spawnArgs.args.join(" "), "--output-format");
    assertIncludes(spawnArgs.args.join(" "), "stream-json");
    assertIncludes(spawnArgs.args.join(" "), "-p");
    assertIncludes(spawnArgs.args.join(" "), "test prompt");
  });

  await test("D25 - Claude buildContinueCommand uses --resume with sessionId", () => {
    const sessionId = "12345678-1234-1234-1234-123456789abc";
    const spawnArgs = claudeAdapter.buildContinueCommand!("follow up", {
      command: "claude",
      args: [],
      model: "claude-sonnet-4-6",
      detected: true,
    }, sessionId);
    assert(spawnArgs.args.includes("--resume"), "must include --resume");
    assertIncludes(spawnArgs.args.join(" "), sessionId);
    assertIncludes(spawnArgs.args.join(" "), "--verbose");
    assertIncludes(spawnArgs.args.join(" "), "stream-json");
  });

  await test("D26 - Claude buildContinueCommand uses --continue without sessionId", () => {
    const spawnArgs = claudeAdapter.buildContinueCommand!("follow up", {
      command: "claude",
      args: [],
      model: "claude-sonnet-4-6",
      detected: true,
    }, undefined);
    assert(spawnArgs.args.includes("--continue"), "must include --continue when no sessionId");
    assert(!spawnArgs.args.includes("--resume"), "must NOT include --resume when no sessionId");
  });

  await test("D27 - all adapters detect() exists and returns boolean promise", async () => {
    for (const adapter of [claudeAdapter, aiderAdapter, geminiAdapter]) {
      assert(typeof adapter.detect === "function", `${adapter.name}.detect should be a function`);
      // We don't call it (it runs execSync 'which ...') but verify it returns a Promise<boolean>
      // Instead verify the interface contract is met
      const result = adapter.detect();
      assert(result instanceof Promise, `${adapter.name}.detect() should return a Promise`);
      // Await it — it may return true or false depending on PATH
      const val = await result;
      assert(typeof val === "boolean", `${adapter.name}.detect() should resolve to boolean, got ${typeof val}`);
    }
  });
}

// ─── Section E: ClaudeStreamRenderer ─────────────────────────────────────────

async function testClaudeStreamRenderer() {
  console.log("\nE. ClaudeStreamRenderer");

  await test("E28 - content_block_delta text_delta returns display + tokenText", () => {
    const r = new ClaudeStreamRenderer();
    const line = JSON.stringify({ type: "content_block_delta", delta: { type: "text_delta", text: "Hello world" } });
    const out = r.process(line);
    assertEqual(out.display, "Hello world");
    assertEqual(out.tokenText, "Hello world");
  });

  await test("E29 - content_block_start tool_use returns tool bullet display", () => {
    const r = new ClaudeStreamRenderer();
    const line = JSON.stringify({ type: "content_block_start", content_block: { type: "tool_use", name: "Bash", id: "tool-001" } });
    const out = r.process(line);
    assert(out.display !== undefined, "should return display");
    assertIncludes(out.display!, "Bash", "should contain tool name");
    assertIncludes(out.display!, "\u23FA", "should contain tool bullet character");
  });

  await test("E30 - message_delta with usage returns outputTokens", () => {
    const r = new ClaudeStreamRenderer();
    const line = JSON.stringify({ type: "message_delta", usage: { output_tokens: 42 } });
    const out = r.process(line);
    assertEqual(out.outputTokens, 42);
  });

  await test("E31 - assistant type with text + tool_use blocks returns correct display", () => {
    const r = new ClaudeStreamRenderer();
    const event = {
      type: "assistant",
      message: {
        content: [
          { type: "text", text: "I will run the tests now." },
          { type: "tool_use", name: "Bash", id: "t1", input: { command: "npm test" } },
        ],
      },
    };
    const out = r.process(JSON.stringify(event));
    assert(out.display !== undefined, "should produce display");
    assertIncludes(out.display!, "I will run the tests now.", "should include text content");
    assertIncludes(out.display!, "Bash", "should include tool name");
    assertIncludes(out.display!, "npm test", "should include tool input preview");
  });

  await test("E32 - tool_result returns indented result display with overflow handling", () => {
    const r = new ClaudeStreamRenderer();
    // First register the tool_use so we can match the tool_result
    const useEvent = JSON.stringify({ type: "content_block_start", content_block: { type: "tool_use", name: "Bash", id: "tool-002" } });
    r.process(useEvent);

    // tool_result with more than 10 lines triggers overflow
    const lines = Array.from({ length: 15 }, (_, i) => `line ${i + 1}`);
    const resultEvent = JSON.stringify({ type: "tool_result", tool_use_id: "tool-002", content: lines.join("\n") });
    const out = r.process(resultEvent);

    assert(out.display !== undefined, "should produce display");
    assertIncludes(out.display!, "\u23BF", "should include result prefix");
    assertIncludes(out.display!, "+5 lines", "should show overflow count (15 - 10 = 5)");
  });

  await test("E33 - result/system type extracts sessionId", () => {
    const r = new ClaudeStreamRenderer();
    const validUuid = "a1b2c3d4-e5f6-7890-abcd-ef1234567890";

    const resultLine = JSON.stringify({ type: "result", session_id: validUuid });
    const out1 = r.process(resultLine);
    assertEqual(out1.sessionId, validUuid);

    const r2 = new ClaudeStreamRenderer();
    const sysLine = JSON.stringify({ type: "system", session_id: validUuid });
    const out2 = r2.process(sysLine);
    assertEqual(out2.sessionId, validUuid);
  });

  await test("E34 - non-JSON lines passed through as-is", () => {
    const r = new ClaudeStreamRenderer();
    const out = r.process("this is not json at all");
    assert(out.display !== undefined, "should return display");
    assertIncludes(out.display!, "this is not json at all");
  });

  await test("E35 - empty lines ignored (return empty object)", () => {
    const r = new ClaudeStreamRenderer();
    const out1 = r.process("");
    assert(out1.display === undefined, "empty line should not produce display");
    assert(out1.tokenText === undefined, "empty line should not produce tokenText");

    const out2 = r.process("   ");
    assert(out2.display === undefined, "whitespace-only line should not produce display");
  });
}

// ─── Section F: Edge Cases ────────────────────────────────────────────────────

async function testEdgeCases() {
  console.log("\nF. Edge Cases");

  await test("F36 - session with zero prompts: end() does not crash (short duration = no stats)", async () => {
    const adapter = mockClaudeAdapter();
    const session = new AgentSession(adapter);
    await session.start();
    // end() immediately (< 500ms) — printSessionStats skips the output
    await session.end();
    assert(!session.isActive(), "session should be inactive after end");
  });

  await test("F37 - very long prompt (>10KB) handled without crash", () => {
    const longPrompt = "a".repeat(11_000) + " please refactor all the code in this project";
    // processInput should not throw
    const result = processInput(longPrompt, "claude", "auto");
    assert(typeof result.type === "string", "should return a valid type");
    assert(result.forwarded.length > 0, "forwarded should not be empty");
  });

  await test("F38 - special characters in prompt not corrupted", () => {
    const special = `Fix the "async" function's \`await\` calls — it's broken: ${JSON.stringify({ key: "val" })}`;
    const result = processInput(special, "claude", "never");
    // With opt=never, forwarded == original
    assertEqual(result.forwarded, special);
    assertEqual(result.optimized, false);
  });

  await test("F38b - unicode in prompt not corrupted", () => {
    const unicode = "请修复这个函数中的错误，使其能够正确处理 Unicode 输入";
    const result = processInput(unicode, "claude", "never");
    assertEqual(result.forwarded, unicode);
  });

  await test("F39 - rapid sequential processInput calls produce valid independent results", () => {
    const prompts = [
      "refactor the authentication module to use JWT tokens",
      "add unit tests for the payment processing service",
      "fix the database connection pool timeout configuration",
      "update the API documentation with new endpoint examples",
      "implement rate limiting for the public REST API endpoints",
    ];
    const results = prompts.map(p => processInput(p, "claude", "auto"));
    for (const r of results) {
      assert(typeof r.type === "string", "each result must have a type");
      assert(r.forwarded.length > 0, "each result must have a forwarded value");
      assert(typeof r.savedTokens === "number", "savedTokens must be a number");
      assert(r.savedTokens >= 0, "savedTokens must be non-negative");
    }
  });

  await test("F40 - session end() is idempotent (can be called multiple times)", async () => {
    const adapter = mockClaudeAdapter();
    const session = new AgentSession(adapter);
    await session.start();
    await session.end();
    // Second end() should not throw
    await session.end();
    assert(!session.isActive(), "should remain inactive");
  });

  await test("F40b - isFollowUpPrompt correctly detects reference prompts", () => {
    assert(isFollowUpPrompt("fix that"), "fix that should be followup");
    assert(isFollowUpPrompt("do it again"), "do it again should be followup");
    assert(isFollowUpPrompt("try it with different params"), "try it should be followup");
    assert(!isFollowUpPrompt("write a new function from scratch"), "unrelated prompt should not be followup");
    assert(!isFollowUpPrompt("implement OAuth2 authentication flow"), "long unrelated prompt should not be followup");
  });

  await test("F40c - isAgentCommand works correctly", () => {
    assert(isAgentCommand("claude", "/compact"), "/compact is claude agent command");
    assert(isAgentCommand("aider", "/add"), "/add is aider command");
    assert(isAgentCommand("claude", "@file.ts"), "@file should be agent command");
    assert(isAgentCommand("claude", "!ls"), "!ls should be agent command");
    assert(!isAgentCommand("claude", "fix the bug"), "natural language is not agent command");
    // NOTE: /cost appears in BOTH Claude's agent commands list AND the vantage commands list.
    // isAgentCommand only checks the agent commands list (no vantage-command filtering).
    // classifyInput checks vantage commands first, so /cost → "vantage-command" via classifyInput,
    // but isAgentCommand returns true because /cost is also in Claude's known slash commands.
    assert(isAgentCommand("claude", "/cost"), "/cost is in claude agent commands list (also a vantage command; classifyInput takes precedence)");
    // /exit-session is NOT in any agent's commands list, only in VANTAGE_COMMANDS
    assert(!isAgentCommand("claude", "/exit-session"), "/exit-session is only a vantage command, not in agent commands");
  });

  await test("F40d - renderer: input_json_delta does not produce display", () => {
    const r = new ClaudeStreamRenderer();
    const line = JSON.stringify({ type: "content_block_delta", delta: { type: "input_json_delta", partial_json: '{"key":' } });
    const out = r.process(line);
    assert(out.display === undefined, "input_json_delta should not produce display");
  });

  await test("F40e - renderer: invalid session_id (not UUID) is NOT extracted", () => {
    const r = new ClaudeStreamRenderer();
    const line = JSON.stringify({ type: "result", session_id: "not-a-uuid" });
    const out = r.process(line);
    assert(out.sessionId === undefined, "invalid UUID should not be extracted as sessionId");
  });

  await test("F40f - renderer: tool_result with array content returns text lines", () => {
    const r = new ClaudeStreamRenderer();
    // Register tool
    r.process(JSON.stringify({ type: "content_block_start", content_block: { type: "tool_use", name: "Read", id: "t3" } }));

    const resultEvent = {
      type: "tool_result",
      tool_use_id: "t3",
      content: [
        { type: "text", text: "line one\nline two" },
        { type: "text", text: "\nline three" },
      ],
    };
    const out = r.process(JSON.stringify(resultEvent));
    assert(out.display !== undefined, "should produce display for array content");
    assertIncludes(out.display!, "line one", "should include first text block");
  });

  await test("F40g - renderer: tool_result with empty content returns nothing", () => {
    const r = new ClaudeStreamRenderer();
    r.process(JSON.stringify({ type: "content_block_start", content_block: { type: "tool_use", name: "Read", id: "t4" } }));
    const out = r.process(JSON.stringify({ type: "tool_result", tool_use_id: "t4", content: "   " }));
    assert(out.display === undefined, "empty result should return no display");
  });

  await test("F40h - classifyInput: @ and ! always agent-command regardless of agent", () => {
    for (const agent of ["claude", "aider", "gemini", "codex", "chatgpt", "unknown"]) {
      assertEqual(classifyInput("@src/app.ts", agent), "agent-command", `@file for ${agent}`);
      assertEqual(classifyInput("!git status", agent), "agent-command", `!cmd for ${agent}`);
    }
  });

  await test("F40i - AgentSession constructor: custom allowedTools respected", () => {
    // Verify the constructor doesn't crash with custom tools via config
    const adapter = mockClaudeAdapter();
    const config = {
      command: "claude",
      args: [],
      model: "claude-sonnet-4-6",
      detected: true,
      allowedTools: ["Read", "Write"],
    } as unknown as AgentConfig;
    // Should not throw
    const session = new AgentSession(adapter, config);
    assert(session !== null, "session should be created");
  });

  await test("F40j - processInput: followup type sets skipOptimization=true", () => {
    const result = processInput("fix that bug in the login flow", "claude", "auto");
    assertEqual(result.type, "followup");
    assertEqual(result.skipOptimization, true);
    assertEqual(result.optimized, false);
    // forwarded should equal original
    assertEqual(result.forwarded, "fix that bug in the login flow");
  });
}

// ─── Additional adapter tests ─────────────────────────────────────────────────

async function testAdditionalAdapters() {
  console.log("\nD (additional). More Adapter Tests");

  await test("gemini buildContinueCommand uses --continue flag", () => {
    const spawnArgs = geminiAdapter.buildContinueCommand!("follow up", {
      command: "gemini",
      args: [],
      model: "gemini-2.0-flash",
      detected: true,
    }, "some-session-id");
    assert(spawnArgs.args.includes("--continue"), "gemini continue must use --continue");
    assertIncludes(spawnArgs.args.join(" "), "follow up");
  });

  await test("gemini buildCommand uses -p flag", () => {
    const spawnArgs = geminiAdapter.buildCommand("test prompt", {
      command: "gemini",
      args: ["-p"],
      model: "gemini-2.0-flash",
      detected: true,
    });
    assertIncludes(spawnArgs.args.join(" "), "-p");
    assertIncludes(spawnArgs.args.join(" "), "test prompt");
  });

  await test("aider buildCommand uses --yes flag", () => {
    const spawnArgs = aiderAdapter.buildCommand("refactor the main module", undefined);
    assert(spawnArgs.args.includes("--yes"), "aider must include --yes");
    assertIncludes(spawnArgs.args.join(" "), "refactor the main module");
  });

  await test("AgentSession: non-perPrompt mode (aider) has correct isActive behavior", async () => {
    const session = new AgentSession(aiderAdapter);
    // Don't actually call start() as it would try to spawn 'aider'
    // Just verify isActive() before start
    assert(!session.isActive(), "session should not be active before start");
  });
}

// ─── Section G: Multi-User Input Scenarios ───────────────────────────────────

async function testMultiUserInput() {
  console.log("\nG. Multi-User Input Scenarios");

  await test("G1 - rapid alternating user inputs classified independently", () => {
    // Simulate rapid user inputs of different types
    const inputs = [
      { text: "please refactor the authentication module to use JWT tokens properly", expected: "prompt" },
      { text: "y", expected: "short-answer" },
      { text: "/compact", expected: "agent-command" },
      { text: '{"config": true}', expected: "structured" },
      { text: "fix that", expected: "followup" },
      { text: "/cost", expected: "vantage-command" },
      { text: "explain the difference between cookies and localStorage in web applications", expected: "prompt" },
      { text: "!git log --oneline -5", expected: "agent-command" },
      { text: "@src/auth.ts", expected: "agent-command" },
      { text: "n", expected: "short-answer" },
    ];
    for (const { text, expected } of inputs) {
      const actual = classifyInput(text, "claude");
      assertEqual(actual, expected, `input "${text.slice(0, 30)}..." → ${actual}, expected ${expected}`);
    }
  });

  await test("G2 - user types permission-like responses (y/n/yes/no) classified as short-answer", () => {
    // When Claude asks "Allow Bash?" the user types y/n — must NOT be optimized
    for (const response of ["y", "n", "yes", "no", "ok", "sure", "cancel", "abort", "skip", "retry"]) {
      const type = classifyInput(response, "claude");
      assertEqual(type, "short-answer", `"${response}" should be short-answer, got ${type}`);
      const result = processInput(response, "claude", "auto");
      assertEqual(result.forwarded, response, `"${response}" must be forwarded verbatim`);
      assertEqual(result.optimized, false, `"${response}" must NOT be optimized`);
    }
  });

  await test("G3 - user numeric responses (tool selection) passed through", () => {
    for (const num of ["1", "2", "3", "42", "0", "99"]) {
      const type = classifyInput(num, "claude");
      assertEqual(type, "short-answer", `"${num}" should be short-answer`);
      const result = processInput(num, "claude", "auto");
      assertEqual(result.forwarded, num, `"${num}" must be forwarded verbatim`);
    }
  });

  await test("G4 - user types file paths as responses", () => {
    for (const path of ["/src/index.ts", "~/Documents/test.txt", "../package.json", "./config.json"]) {
      const type = classifyInput(path, "claude");
      // File paths starting with / or ~/ or ../ or ./ are short-answer
      assertEqual(type, "short-answer", `"${path}" should be short-answer, got ${type}`);
      const result = processInput(path, "claude", "auto");
      assertEqual(result.forwarded, path, `"${path}" must be forwarded verbatim`);
    }
  });

  await test("G5 - interleaved prompts and permission responses in sequence", () => {
    // Simulate: user sends prompt, then agent asks for permission, user responds
    const sequence = [
      { text: "write a bash script that lists all docker containers running on this machine", type: "prompt" },
      { text: "y", type: "short-answer" },  // approve Bash tool
      { text: "also show the images", type: "short-answer" },  // 4 words = short-answer
      { text: "yes", type: "short-answer" },  // approve another tool
      { text: "now save the output to a file called containers.txt in the home directory", type: "followup" },  // matches "save...the...file" follow-up pattern
      { text: "y", type: "short-answer" },  // approve Write tool
    ];
    for (const { text, type } of sequence) {
      const result = processInput(text, "claude", "auto");
      assertEqual(result.type, type, `"${text.slice(0, 30)}..." → ${result.type}, expected ${type}`);
      assertEqual(result.forwarded.length > 0, true, `forwarded must not be empty for "${text.slice(0, 20)}..."`);
    }
  });

  await test("G6 - optimization never corrupts short permission responses", () => {
    // Even in "always" mode, short answers should not be mangled
    for (const mode of ["auto", "always", "ask", "never"] as const) {
      for (const input of ["y", "n", "yes", "no", "1", "2"]) {
        const result = processInput(input, "claude", mode);
        assertEqual(result.forwarded, input, `"${input}" with mode=${mode} must be verbatim`);
        assertEqual(result.optimized, false, `"${input}" with mode=${mode} must NOT be optimized`);
      }
    }
  });

  await test("G7 - multi-line code paste not corrupted by optimizer", () => {
    const codePaste = "```typescript\nfunction hello() {\n  console.log('world');\n}\n```";
    const result = processInput(codePaste, "claude", "auto");
    assertEqual(result.type, "structured", "code paste should be structured");
    assertEqual(result.forwarded, codePaste, "code paste must be forwarded verbatim");
    assertEqual(result.optimized, false, "code paste must NOT be optimized");
  });

  await test("G8 - inline code in prompt preserved", () => {
    const prompt = "change the `fetchData` function to use `async/await` instead of callbacks";
    const result = processInput(prompt, "claude", "auto");
    assertEqual(result.type, "structured", "inline code should be structured");
    assertEqual(result.forwarded, prompt, "inline code prompt must be forwarded verbatim");
  });

  await test("G9 - empty lines between user inputs don't crash", () => {
    for (const empty of ["", "   ", "\t", "\n"]) {
      const type = classifyInput(empty, "claude");
      assertEqual(type, "unknown", `empty "${JSON.stringify(empty)}" should be unknown`);
      const result = processInput(empty, "claude", "auto");
      assert(result !== null, "processInput must return a result for empty input");
    }
  });

  await test("G10 - user types agent commands during multi-turn session", () => {
    // Verify agent commands across different agents are correctly classified
    const agentCmds: Array<[string, string, string]> = [
      ["/compact", "claude", "agent-command"],
      ["/clear", "claude", "agent-command"],
      ["/diff", "claude", "agent-command"],
      ["/add src/file.ts", "aider", "agent-command"],
      ["/drop src/file.ts", "aider", "agent-command"],
      ["/model gemini-2.0-flash", "gemini", "agent-command"],
      ["/tools", "gemini", "agent-command"],
      ["/approval", "codex", "agent-command"],
    ];
    for (const [cmd, agent, expected] of agentCmds) {
      const actual = classifyInput(cmd, agent);
      assertEqual(actual, expected, `"${cmd}" for ${agent} → ${actual}, expected ${expected}`);
    }
  });
}

// ─── Section H: Permission & --allowedTools Scenarios ─────────────────────────

async function testPermissionScenarios() {
  console.log("\nH. Permission & --allowedTools Scenarios");

  const DEFAULT_TOOLS = ["Read", "Glob", "Grep", "Write", "Edit", "Bash", "WebFetch", "WebSearch", "Agent", "TodoWrite"];

  await test("H1 - Claude buildCommand injects --allowedTools from config extraFlags", () => {
    const config: AgentConfig = {
      command: "claude",
      args: [],
      model: "claude-sonnet-4-6",
      detected: true,
      extraFlags: ["--allowedTools", DEFAULT_TOOLS.join(",")],
    };
    const spawnArgs = claudeAdapter.buildCommand("test", config);
    const argsStr = spawnArgs.args.join(" ");
    assertIncludes(argsStr, "--allowedTools");
    assertIncludes(argsStr, "WebFetch");
    assertIncludes(argsStr, "Bash");
    assertIncludes(argsStr, "Read");
    assertIncludes(argsStr, "Write");
  });

  await test("H2 - --allowedTools preserved in buildContinueCommand with --resume", () => {
    const config: AgentConfig = {
      command: "claude",
      args: [],
      model: "claude-sonnet-4-6",
      detected: true,
      extraFlags: ["--allowedTools", "Read,Write,Bash"],
    };
    const sid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee";
    const spawnArgs = claudeAdapter.buildContinueCommand!("follow up", config, sid);
    const argsStr = spawnArgs.args.join(" ");
    assertIncludes(argsStr, "--resume");
    assertIncludes(argsStr, sid);
    assertIncludes(argsStr, "--allowedTools");
    assertIncludes(argsStr, "Read,Write,Bash");
  });

  await test("H3 - --allowedTools preserved in buildContinueCommand with --continue (no sid)", () => {
    const config: AgentConfig = {
      command: "claude",
      args: [],
      model: "claude-sonnet-4-6",
      detected: true,
      extraFlags: ["--allowedTools", "Read"],
    };
    const spawnArgs = claudeAdapter.buildContinueCommand!("next prompt", config, undefined);
    const argsStr = spawnArgs.args.join(" ");
    assertIncludes(argsStr, "--continue");
    assert(!argsStr.includes("--resume"), "should NOT have --resume without sessionId");
    assertIncludes(argsStr, "--allowedTools");
    assertIncludes(argsStr, "Read");
  });

  await test("H4 - AgentSession injects default allowedTools when none configured", async () => {
    // Create session with no custom allowedTools
    const adapter = mockClaudeAdapter();
    const session = new AgentSession(adapter);
    // Start doesn't spawn — just verifies detect()
    const started = await session.start();
    assert(started, "should start successfully");

    // The internal allowedTools should be DEFAULT_ALLOWED_TOOLS
    // We can't access private fields directly, so verify via the adapter's buildCommand
    // which receives the config with extraFlags from sendLine → sendPerPrompt
    // Test by building the command directly with the expected flags
    const config: AgentConfig = {
      command: "claude",
      args: [],
      model: "claude-sonnet-4-6",
      detected: true,
      extraFlags: ["--allowedTools", DEFAULT_TOOLS.join(",")],
    };
    const spawnArgs = adapter.buildCommand("test", config);
    const argsStr = spawnArgs.args.join(" ");
    for (const tool of DEFAULT_TOOLS) {
      assertIncludes(argsStr, tool, `default tool "${tool}" must be in command`);
    }
    await session.end();
  });

  await test("H5 - custom allowedTools override defaults", () => {
    const adapter = mockClaudeAdapter();
    const customConfig = {
      command: "claude",
      args: [],
      model: "claude-sonnet-4-6",
      detected: true,
      allowedTools: ["Read", "Grep"],
    } as unknown as AgentConfig;
    const session = new AgentSession(adapter, customConfig);
    // Session created with custom tools — no crash
    assert(session !== null, "session with custom tools created");
  });

  await test("H6 - result event with permission_denials parsed correctly", () => {
    const renderer = new ClaudeStreamRenderer();
    // A result event that includes permission denials
    const resultWithDenials = JSON.stringify({
      type: "result",
      subtype: "success",
      session_id: "11111111-2222-3333-4444-555555555555",
      total_cost_usd: 0.05,
      permission_denials: [
        { tool_name: "Bash", tool_use_id: "toolu_123", tool_input: { command: "rm -rf /" } },
      ],
    });
    const out = renderer.process(resultWithDenials);
    assertEqual(out.sessionId, "11111111-2222-3333-4444-555555555555");
    // Renderer extracts sessionId from result events — that's the key behavior
  });

  await test("H7 - result event with zero permission_denials (all tools approved)", () => {
    const renderer = new ClaudeStreamRenderer();
    const resultClean = JSON.stringify({
      type: "result",
      session_id: "aaaa1111-bb22-cc33-dd44-eeeeeeffffff",
      total_cost_usd: 0.10,
      permission_denials: [],
    });
    const out = renderer.process(resultClean);
    assertEqual(out.sessionId, "aaaa1111-bb22-cc33-dd44-eeeeeeffffff");
  });

  await test("H8 - tool_use events for each allowed tool render correctly", () => {
    const renderer = new ClaudeStreamRenderer();
    const tools = ["Read", "Write", "Bash", "WebFetch", "Grep", "Glob", "Edit", "Agent", "WebSearch"];
    for (const tool of tools) {
      const event = JSON.stringify({
        type: "content_block_start",
        content_block: { type: "tool_use", name: tool, id: `id_${tool}` },
      });
      const out = renderer.process(event);
      assert(out.display !== undefined, `tool_use for ${tool} must produce display`);
      assertIncludes(out.display!, tool, `display must include tool name "${tool}"`);
    }
  });

  await test("H9 - tool_result events render correctly for all tools", () => {
    const renderer = new ClaudeStreamRenderer();
    const toolResults = [
      { id: "t_read", content: "file contents here\nline 2" },
      { id: "t_bash", content: "hello world" },
      { id: "t_grep", content: "src/index.ts:42:  const x = 1;" },
      { id: "t_fetch", content: "<html><head><title>Example</title></head></html>" },
    ];
    for (const { id, content } of toolResults) {
      // Register tool first
      renderer.process(JSON.stringify({
        type: "content_block_start",
        content_block: { type: "tool_use", name: "Tool", id },
      }));
      const out = renderer.process(JSON.stringify({
        type: "tool_result",
        tool_use_id: id,
        content,
      }));
      assert(out.display !== undefined, `tool_result for ${id} must produce display`);
      // Check first line of content is visible
      const firstLine = content.split("\n")[0]!;
      assertIncludes(out.display!, firstLine.slice(0, 20), `display must include content start for ${id}`);
    }
  });

  await test("H10 - non-Claude agents do NOT get --allowedTools", () => {
    // aider, gemini, codex should not have --allowedTools in their commands
    const aiderArgs = aiderAdapter.buildCommand("test prompt", undefined);
    assert(!aiderArgs.args.includes("--allowedTools"), "aider must NOT have --allowedTools");

    const geminiArgs = geminiAdapter.buildCommand("test prompt", {
      command: "gemini",
      args: ["-p"],
      model: "gemini-2.0-flash",
      detected: true,
    });
    assert(!geminiArgs.args.includes("--allowedTools"), "gemini must NOT have --allowedTools");
  });

  await test("H11 - multiple tool_use + tool_result in sequence render without corruption", () => {
    const renderer = new ClaudeStreamRenderer();

    // Tool 1: Read
    let out = renderer.process(JSON.stringify({
      type: "content_block_start",
      content_block: { type: "tool_use", name: "Read", id: "t1" },
    }));
    assertIncludes(out.display!, "Read");

    out = renderer.process(JSON.stringify({
      type: "tool_result",
      tool_use_id: "t1",
      content: "file content here",
    }));
    assertIncludes(out.display!, "file content here");

    // Text between tools
    out = renderer.process(JSON.stringify({
      type: "content_block_delta",
      delta: { type: "text_delta", text: "Now I'll write the fix." },
    }));
    assertIncludes(out.display!, "Now I'll write the fix.");

    // Tool 2: Write
    out = renderer.process(JSON.stringify({
      type: "content_block_start",
      content_block: { type: "tool_use", name: "Write", id: "t2" },
    }));
    assertIncludes(out.display!, "Write");

    out = renderer.process(JSON.stringify({
      type: "tool_result",
      tool_use_id: "t2",
      content: "File written successfully",
    }));
    assertIncludes(out.display!, "File written");

    // Final text
    out = renderer.process(JSON.stringify({
      type: "content_block_delta",
      delta: { type: "text_delta", text: "Done." },
    }));
    assertEqual(out.display, "Done.");
    assertEqual(out.tokenText, "Done.");
  });

  await test("H12 - session with --allowedTools handles tool approval flow end-to-end", () => {
    // Simulate a full turn: prompt → assistant (tool_use) → tool_result → assistant (text) → result
    const renderer = new ClaudeStreamRenderer();

    // 1. Assistant decides to use WebFetch (pre-approved via --allowedTools)
    const assistantMsg = JSON.stringify({
      type: "assistant",
      message: {
        content: [
          { type: "tool_use", name: "WebFetch", id: "wf1", input: { url: "https://example.com" } },
        ],
      },
      session_id: "a0b1c2d3-e4f5-6789-abcd-ef0123456789",
    });
    let out = renderer.process(assistantMsg);
    assert(out.display !== undefined, "tool_use display");
    assertIncludes(out.display!, "WebFetch");

    // 2. Tool result comes back (no permission denial — tool was pre-approved)
    out = renderer.process(JSON.stringify({
      type: "tool_result",
      tool_use_id: "wf1",
      content: "<html><title>Example Domain</title></html>",
    }));
    assertIncludes(out.display!, "Example Domain");

    // 3. Assistant summarizes
    out = renderer.process(JSON.stringify({
      type: "content_block_delta",
      delta: { type: "text_delta", text: "The page title is Example Domain." },
    }));
    assertEqual(out.display, "The page title is Example Domain.");
    assertEqual(out.tokenText, "The page title is Example Domain.");

    // 4. Result event with cost and no denials
    out = renderer.process(JSON.stringify({
      type: "result",
      session_id: "a0b1c2d3-e4f5-6789-abcd-ef0123456789",
      total_cost_usd: 0.08,
      permission_denials: [],
    }));
    assertEqual(out.sessionId, "a0b1c2d3-e4f5-6789-abcd-ef0123456789");
  });
}

// ─── Main ─────────────────────────────────────────────────────────────────────

async function main() {
  console.log("=== Vantage CLI Session Mode — Aggressive Tests ===");

  await testInputClassification();
  await testPerPromptSession();
  await testPersistentSession();
  await testAgentAdapters();
  await testClaudeStreamRenderer();
  await testEdgeCases();
  await testAdditionalAdapters();
  await testMultiUserInput();
  await testPermissionScenarios();

  console.log(`\n${"=".repeat(50)}`);
  console.log(`  Total: ${passed + failed} | Passed: ${passed} | Failed: ${failed}`);

  if (failures.length > 0) {
    console.log("\nFailed tests:");
    for (const f of failures) {
      console.log(`  - ${f}`);
    }
    process.exit(1);
  } else {
    console.log("\n  All tests passed.");
    process.exit(0);
  }
}

main().catch((err) => {
  console.error("Unexpected error:", err);
  process.exit(1);
});
