#!/bin/bash
# Pre-commit quality gate — runs TypeScript check + linter + tests
# Blocks commit if anything fails.

set -e

# TypeScript check
if [ -f "tsconfig.json" ]; then
  echo "Running TypeScript check..."
  npx tsc --noEmit || exit 2
fi

# Lint staged JS/TS files
if command -v npx &> /dev/null && [ -f "package.json" ]; then
  STAGED_JS=$(git diff --cached --name-only | grep -E '\.(js|jsx|ts|tsx)$' || true)
  if [ -n "$STAGED_JS" ] && [ -f "node_modules/.bin/eslint" ]; then
    echo "Running ESLint on staged files..."
    npx eslint $STAGED_JS 2>/dev/null || exit 2
  fi
fi

# Node.js tests
if [ -f "package.json" ] && grep -q '"test"' package.json; then
  echo "Running npm test..."
  npm test -- --silent 2>/dev/null || exit 2
fi

# Python projects
if [ -f "pyproject.toml" ] || [ -f "setup.py" ]; then
  STAGED_PY=$(git diff --cached --name-only | grep '\.py$' || true)
  if command -v ruff &> /dev/null && [ -n "$STAGED_PY" ]; then
    echo "Running ruff check..."
    ruff check $STAGED_PY 2>/dev/null || exit 2
  fi
  if command -v pytest &> /dev/null; then
    echo "Running pytest..."
    pytest --quiet -x 2>/dev/null || exit 2
  fi
fi

echo "All pre-commit checks passed!"
exit 0
