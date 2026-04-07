#!/usr/bin/env tsx
/**
 * test-agent-config.ts — Harness for agent config reading tests.
 * Tests P1-B: reading native agent config files for model/MCP detection.
 *
 * Usage:
 *   tsx test-agent-config.ts read-claude-model
 *   tsx test-agent-config.ts read-claude-mcp
 *   tsx test-agent-config.ts read-claude-permissions
 *   tsx test-agent-config.ts build-command '{"permissionMode":"acceptEdits","allowedTools":["Read","Edit"]}'
 *   tsx test-agent-config.ts build-continue '{"permissionMode":"auto"}' 'session-uuid'
 */

import { claudeAdapter } from "./src/agents/claude.js";
import { readClaudeConfig } from "./src/agent-config.js";

const cmd  = process.argv[2] ?? "";
const arg1 = process.argv[3] ?? "";
const arg2 = process.argv[4] ?? "";

switch (cmd) {
  case "read-claude-model": {
    const config = readClaudeConfig();
    console.log(JSON.stringify({ model: config?.model ?? null }));
    break;
  }

  case "read-claude-mcp": {
    const config = readClaudeConfig();
    const servers = config?.mcpServers ? Object.keys(config.mcpServers) : [];
    console.log(JSON.stringify({ mcpServers: servers }));
    break;
  }

  case "read-claude-permissions": {
    const config = readClaudeConfig();
    console.log(JSON.stringify({ permissions: config?.permissions ?? null }));
    break;
  }

  case "build-command": {
    const overrides = JSON.parse(arg1) as { permissionMode?: string; allowedTools?: string[] };
    const extraFlags: string[] = [];
    if (overrides.permissionMode) {
      extraFlags.push("--permission-mode", overrides.permissionMode);
    }
    if (overrides.allowedTools?.length) {
      extraFlags.push("--allowedTools", overrides.allowedTools.join(","));
    }
    const result = claudeAdapter.buildCommand("test prompt", { extraFlags } as never);
    console.log(JSON.stringify({ command: result.command, args: result.args }));
    break;
  }

  case "build-continue": {
    const overrides = JSON.parse(arg1) as { permissionMode?: string };
    const extraFlags: string[] = [];
    if (overrides.permissionMode) {
      extraFlags.push("--permission-mode", overrides.permissionMode);
    }
    const sessionId = arg2 || undefined;
    const result = claudeAdapter.buildContinueCommand!("test prompt", { extraFlags } as never, sessionId);
    console.log(JSON.stringify({ command: result.command, args: result.args }));
    break;
  }

  default:
    console.error("Usage: tsx test-agent-config.ts <read-claude-model|read-claude-mcp|build-command|build-continue> [args...]");
    process.exit(1);
}
