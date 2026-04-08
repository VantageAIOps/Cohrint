#!/bin/bash
# Auto-format and lint files after Claude edits them
# Runs after every Edit/Write tool use

FILE="$1"

if [ -z "$FILE" ]; then
  exit 0
fi

EXTENSION="${FILE##*.}"

case "$EXTENSION" in
  js|jsx|ts|tsx)
    # Format with Prettier if available
    if command -v npx &> /dev/null && [ -f "node_modules/.bin/prettier" ]; then
      npx prettier --write "$FILE" 2>/dev/null
    fi
    # Lint with ESLint if available
    if command -v npx &> /dev/null && [ -f "node_modules/.bin/eslint" ]; then
      npx eslint --fix "$FILE" 2>/dev/null
    fi
    ;;
  py)
    # Format with ruff (preferred) or black
    if command -v ruff &> /dev/null; then
      ruff format "$FILE" 2>/dev/null
      ruff check --fix "$FILE" 2>/dev/null
    elif command -v black &> /dev/null; then
      black "$FILE" 2>/dev/null
    fi
    ;;
  go)
    if command -v gofmt &> /dev/null; then
      gofmt -w "$FILE" 2>/dev/null
    fi
    ;;
  rs)
    if command -v rustfmt &> /dev/null; then
      rustfmt "$FILE" 2>/dev/null
    fi
    ;;
esac

exit 0
