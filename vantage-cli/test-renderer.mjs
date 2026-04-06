#!/usr/bin/env node
/**
 * test-renderer.mjs — Unit test harness for ClaudeStreamRenderer logic.
 * Called by pytest suite 34.
 *
 * Usage:
 *   node test-renderer.mjs process   <json-event>
 *   node test-renderer.mjs process_pair <use-event> <result-event>
 *
 * Returns JSON to stdout.
 */

// ── Inline renderer (mirrors runner.ts ClaudeStreamRenderer) ──────────────
const TOOL_BULLET = "\u23FA";
const RESULT_PREFIX = "\u23BF";
const MAX_RESULT_LINES = 10;
const MAX_PREVIEW = 70;

function formatToolInput(name, input) {
  const s = (v) => (typeof v === "string" ? v : JSON.stringify(v));
  let preview;
  switch (name) {
    case "Bash":
      preview = s(input["command"] ?? "").replace(/\s+/g, " ").trim();
      break;
    case "Write":
    case "Read":
    case "Edit":
    case "MultiEdit":
      preview = s(input["file_path"] ?? "");
      break;
    case "Grep":
      preview = s(input["pattern"] ?? "") + (input["path"] ? ` in ${s(input["path"])}` : "");
      break;
    case "Glob":
      preview = s(input["pattern"] ?? "");
      break;
    case "Agent":
      preview = s(input["description"] ?? input["prompt"] ?? "");
      break;
    case "WebFetch":
      preview = s(input["url"] ?? "");
      break;
    case "WebSearch":
      preview = s(input["query"] ?? "");
      break;
    default: {
      const first = Object.entries(input)[0];
      preview = first ? `${first[0]}=${s(first[1])}` : "";
    }
  }
  return preview.length > MAX_PREVIEW
    ? preview.slice(0, MAX_PREVIEW - 1) + "\u2026"
    : preview;
}

function isValidSessionId(sid) {
  return typeof sid === "string" && /^[0-9a-f-]{36}$/i.test(sid);
}

class ClaudeStreamRenderer {
  pendingTools = new Map(); // tool_use_id → tool name

  process(line) {
    if (!line.trim()) return {};
    try {
      const obj = JSON.parse(line);

      if (obj["type"] === "assistant") {
        const content = obj["message"]?.["content"];
        if (!content?.length) return {};

        const displayParts = [];
        const tokenParts = [];

        for (const block of content) {
          if (block["type"] === "text") {
            const t = String(block["text"] ?? "");
            if (t) { displayParts.push(t); tokenParts.push(t); }
          } else if (block["type"] === "tool_use") {
            const toolName = String(block["name"] ?? "Tool");
            const toolId   = String(block["id"]   ?? "");
            const input    = block["input"] ?? {};
            const preview  = formatToolInput(toolName, input);
            displayParts.push(`\n${TOOL_BULLET} ${toolName}(${preview})\n`);
            if (toolId) this.pendingTools.set(toolId, toolName);
          }
        }

        const display   = displayParts.join("");
        const tokenText = tokenParts.join("");
        return display ? { display, tokenText: tokenText || undefined } : {};
      }

      if (obj["type"] === "tool_result") {
        const toolId = String(obj["tool_use_id"] ?? "");
        this.pendingTools.delete(toolId);

        const raw = obj["content"];
        let resultText = "";
        if (typeof raw === "string") {
          resultText = raw;
        } else if (Array.isArray(raw)) {
          resultText = raw
            .filter((b) => b["type"] === "text")
            .map((b) => String(b["text"] ?? ""))
            .join("");
        }

        if (!resultText.trim()) return {};

        const lines = resultText.split("\n");
        const shown    = lines.slice(0, MAX_RESULT_LINES);
        const overflow = lines.length - MAX_RESULT_LINES;

        const indented = shown
          .map((l, i) => (i === 0 ? `  ${RESULT_PREFIX}  ${l}` : `     ${l}`))
          .join("\n");
        const suffix = overflow > 0
          ? `\n     \u2026 +${overflow} lines (ctrl+o to expand)` : "";

        return { display: `${indented}${suffix}\n` };
      }

      if (obj["type"] === "result" || obj["type"] === "system") {
        const sid = obj["session_id"];
        if (isValidSessionId(sid)) return { sessionId: sid };
        return {};
      }

      return {};
    } catch {
      // Non-JSON — pass through as-is
      return { display: line + "\n", tokenText: line + "\n" };
    }
  }
}

// ── Dispatch ──────────────────────────────────────────────────────────────
const cmd  = process.argv[2];
const arg1 = process.argv[3] ?? "";
const arg2 = process.argv[4] ?? "";

const r = new ClaudeStreamRenderer();

if (cmd === "process") {
  const result = r.process(arg1);
  console.log(JSON.stringify(result));
} else if (cmd === "process_pair") {
  // Process use event (registers tool), then result event
  r.process(arg1);
  const result = r.process(arg2);
  // Expose result display under "result_display" key for test clarity
  console.log(JSON.stringify({ result_display: result.display ?? "" }));
} else {
  console.log(JSON.stringify({ error: "unknown command", usage: "process|process_pair" }));
}
