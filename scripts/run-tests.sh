#!/usr/bin/env bash
# run-tests.sh — VantageAI local test runner
# Usage: scripts/run-tests.sh [--suite NAME] [--file FILE] [--test EXPR] [-- PYTEST_ARGS]
set -euo pipefail

SUITES=()
FILES=()
TEST_NAME=""
EXTRA_ARGS=()
PARSING_EXTRA=0

validate_arg() {
  local val="$1" flag="$2"
  if [[ ! "$val" =~ ^[a-zA-Z0-9_-]+$ ]]; then
    echo "ERROR: Invalid value for $flag: '$val' (alphanumeric, underscore, hyphen only)" >&2
    exit 1
  fi
}

while [[ $# -gt 0 ]]; do
  if [[ $PARSING_EXTRA -eq 1 ]]; then
    EXTRA_ARGS+=("$1"); shift; continue
  fi
  case "$1" in
    --suite) validate_arg "$2" "--suite"; SUITES+=("$2"); shift 2 ;;
    --file)  validate_arg "$2" "--file";  FILES+=("$2");  shift 2 ;;
    --test)  validate_arg "$2" "--test";  TEST_NAME="$2"; shift 2 ;;
    --help|-h)
      echo "Usage: scripts/run-tests.sh [--suite NAME] [--file FILE] [--test EXPR] [-- ARGS]"
      echo ""
      echo "  --suite  Partial or exact suite name (e.g. '35' or '35_cross_platform_console')"
      echo "  --file   Test file within suite, without .py extension"
      echo "  --test   pytest -k filter expression"
      echo "  --       All following args are passed to pytest verbatim"
      echo ""
      echo "Examples:"
      echo "  scripts/run-tests.sh"
      echo "  scripts/run-tests.sh --suite 35"
      echo "  scripts/run-tests.sh --suite 35 --file test_trend"
      echo "  scripts/run-tests.sh --suite 35 --test test_trend_7d_window -- -v -x"
      exit 0 ;;
    --) PARSING_EXTRA=1; shift ;;
    *)  echo "ERROR: Unknown argument: $1 (use --help for usage)" >&2; exit 1 ;;
  esac
done

SUITE_BASE="tests/suites"
if [[ ! -d "$SUITE_BASE" ]]; then
  echo "ERROR: Cannot find $SUITE_BASE — run from project root" >&2
  exit 1
fi

mapfile -t ALL_SUITES < <(ls -d "$SUITE_BASE"/[0-9]*/ 2>/dev/null | xargs -n1 basename | sort)

resolve_suite() {
  local pattern="$1"
  local matches=()
  for s in "${ALL_SUITES[@]}"; do
    [[ "$s" == "$pattern" || "$s" == *"$pattern"* ]] && matches+=("$s")
  done
  if [[ ${#matches[@]} -eq 0 ]]; then
    echo "ERROR: --suite '$pattern' matched no suites. Available: ${ALL_SUITES[*]}" >&2; exit 1
  fi
  if [[ ${#matches[@]} -gt 1 ]]; then
    echo "ERROR: --suite '$pattern' is ambiguous — matches: ${matches[*]}. Be more specific." >&2; exit 1
  fi
  echo "${matches[0]}"
}

CMD=(python -m pytest)

if [[ ${#SUITES[@]} -eq 0 ]]; then
  for s in "${ALL_SUITES[@]}"; do CMD+=("$SUITE_BASE/$s/"); done
else
  for pattern in "${SUITES[@]}"; do
    resolved=$(resolve_suite "$pattern")
    if [[ ${#FILES[@]} -gt 0 ]]; then
      for f in "${FILES[@]}"; do CMD+=("$SUITE_BASE/$resolved/${f%.py}.py"); done
    else
      CMD+=("$SUITE_BASE/$resolved/")
    fi
  done
fi

[[ -n "$TEST_NAME" ]] && CMD+=(-k "$TEST_NAME")
[[ ${#EXTRA_ARGS[@]} -gt 0 ]] && CMD+=("${EXTRA_ARGS[@]}")

echo "Running: ${CMD[*]}"
echo ""
"${CMD[@]}"
