#!/usr/bin/env tsx
/**
 * test-renderer.ts — Test harness for ClaudeStreamRenderer.
 * Imports the real production class via tsx — no logic duplication.
 *
 * Usage:
 *   tsx test-renderer.ts process      <json-event>
 *   tsx test-renderer.ts process_pair <use-event> <result-event>
 */

import { ClaudeStreamRenderer } from "./src/runner.js";

const cmd  = process.argv[2] ?? "";
const arg1 = process.argv[3] ?? "";
const arg2 = process.argv[4] ?? "";

const r = new ClaudeStreamRenderer();

if (cmd === "process") {
  const result = r.process(arg1);
  console.log(JSON.stringify(result));

} else if (cmd === "process_pair") {
  r.process(arg1);                      // register the tool_use
  const result = r.process(arg2);       // process the tool_result
  console.log(JSON.stringify({ result_display: result.display ?? "" }));

} else {
  console.log(JSON.stringify({ error: `unknown command: ${cmd}` }));
  process.exit(1);
}
