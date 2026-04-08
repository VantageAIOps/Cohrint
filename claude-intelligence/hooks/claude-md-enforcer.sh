#!/bin/bash
# After every Edit/Write: check if a CLAUDE.md exceeded 100 lines.
# If so, emit a systemMessage so Claude summarizes it immediately.

INPUT=$(cat)
FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path // ""' 2>/dev/null)

# Only act on CLAUDE.md files
if [[ "$FILE" != *"CLAUDE.md" ]]; then
  exit 0
fi

# Count lines (handle missing file gracefully)
LINE_COUNT=$(wc -l < "$FILE" 2>/dev/null | tr -d ' ')
if [ -z "$LINE_COUNT" ] || [ "$LINE_COUNT" -le 100 ]; then
  exit 0
fi

# Emit message to trigger Claude summarization
echo "{\"systemMessage\": \"CLAUDE.md at '$FILE' has $LINE_COUNT lines (limit: 100). Summarize and rewrite it to stay under 100 lines. Keep all critical rules, commands, and conventions — just compress verbose explanations into bullet points.\"}"
