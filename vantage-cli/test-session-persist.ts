#!/usr/bin/env tsx
/**
 * test-session-persist.ts — Harness for session persistence tests.
 * Tests P0-B: saving/loading agentSessionIds to/from disk.
 *
 * Usage:
 *   tsx test-session-persist.ts save   '{"claude":"abc-123","gemini":"def-456"}'
 *   tsx test-session-persist.ts load
 *   tsx test-session-persist.ts clear
 *   tsx test-session-persist.ts save-then-load '{"claude":"abc-123"}'
 */

import { saveSessionIds, loadSessionIds, clearSessionIds, getSessionDir } from "./src/session-persist.js";

const cmd  = process.argv[2] ?? "";
const arg1 = process.argv[3] ?? "";

switch (cmd) {
  case "save": {
    const data = JSON.parse(arg1) as Record<string, string>;
    saveSessionIds(data);
    console.log(JSON.stringify({ ok: true }));
    break;
  }

  case "load": {
    const loaded = loadSessionIds();
    console.log(JSON.stringify({ sessions: loaded }));
    break;
  }

  case "clear": {
    clearSessionIds();
    console.log(JSON.stringify({ ok: true }));
    break;
  }

  case "save-then-load": {
    const data = JSON.parse(arg1) as Record<string, string>;
    saveSessionIds(data);
    const loaded = loadSessionIds();
    console.log(JSON.stringify({ sessions: loaded }));
    break;
  }

  case "dir": {
    console.log(JSON.stringify({ dir: getSessionDir() }));
    break;
  }

  default:
    console.error("Usage: tsx test-session-persist.ts <save|load|clear|save-then-load|dir> [args...]");
    process.exit(1);
}
