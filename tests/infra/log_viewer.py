"""
log_viewer.py — CLI log viewer and filter for VantageAI test logs
=================================================================
Purpose:
  Makes it easy to inspect structured JSON logs from test runs and
  production (if logs are piped through).

Usage:
  # Tail logs in pretty mode:
  python tests/infra/log_viewer.py --tail

  # Filter by level:
  python tests/infra/log_viewer.py --level ERROR

  # Filter by logger name:
  python tests/infra/log_viewer.py --logger test.auth_stability

  # Show only failed test assertions:
  python tests/infra/log_viewer.py --level ERROR --since 1h

  # Count errors by logger:
  python tests/infra/log_viewer.py --count

  # Show slowest requests:
  python tests/infra/log_viewer.py --slowest 10

  # Parse from file:
  python tests/infra/log_viewer.py --file tests/artifacts/run.jsonl

Developer notes:
  Log lines are newline-delimited JSON (NDJSON / JSON Lines format).
  Set VANTAGE_LOG_FILE=tests/artifacts/run.jsonl in your environment
  to capture all logs from a test run to a file.

  Then use this viewer to analyse:
    python tests/infra/log_viewer.py --file tests/artifacts/run.jsonl --level ERROR

  To stream live logs from production Cloudflare Workers:
    wrangler tail vantage-api --format json | python tests/infra/log_viewer.py --stdin
"""

import sys
import os
import json
import argparse
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, List

# ANSI colours
_COLOURS = {
    "DEBUG":    "\033[90m",
    "INFO":     "\033[32m",
    "WARN":     "\033[33m",
    "ERROR":    "\033[31m",
    "CRITICAL": "\033[35m",
    "RESET":    "\033[0m",
    "BOLD":     "\033[1m",
    "DIM":      "\033[2m",
}

# Default log file — use artifacts dir from env or fallback
_DEFAULT_ARTIFACTS = Path(os.environ.get(
    "VANTAGE_TEST_ARTIFACTS_DIR",
    str(Path(__file__).parent.parent / "artifacts")
))
DEFAULT_LOG_FILE = _DEFAULT_ARTIFACTS / "run.jsonl"


def parse_args():
    p = argparse.ArgumentParser(
        description="VantageAI log viewer — filter and inspect structured JSON logs"
    )
    p.add_argument("--file",    type=str,  default=str(DEFAULT_LOG_FILE),
                   help="Path to NDJSON log file")
    p.add_argument("--stdin",   action="store_true",
                   help="Read from stdin (pipe from wrangler tail)")
    p.add_argument("--tail",    action="store_true",
                   help="Tail the log file (like tail -f)")
    p.add_argument("--level",   type=str,  default=None,
                   choices=["DEBUG", "INFO", "WARN", "ERROR", "CRITICAL"],
                   help="Minimum log level to show")
    p.add_argument("--logger",  type=str,  default=None,
                   help="Filter by logger name prefix (e.g. test.auth)")
    p.add_argument("--since",   type=str,  default=None,
                   help="Show logs since duration ago (e.g. 1h, 30m, 1d)")
    p.add_argument("--count",   action="store_true",
                   help="Show count of log lines per logger/level")
    p.add_argument("--slowest", type=int,  default=None,
                   help="Show N slowest requests by duration_ms")
    p.add_argument("--no-color", action="store_true",
                   help="Disable ANSI colours")
    p.add_argument("--json",    action="store_true",
                   help="Output as JSON lines (no formatting)")
    return p.parse_args()


def parse_since(since: str) -> Optional[datetime]:
    """Parse relative time strings like '1h', '30m', '1d' into a datetime cutoff."""
    if not since:
        return None
    unit  = since[-1].lower()
    value = int(since[:-1])
    delta = {
        "m": timedelta(minutes=value),
        "h": timedelta(hours=value),
        "d": timedelta(days=value),
    }.get(unit)
    if delta is None:
        print(f"Unknown time unit '{unit}' — use m/h/d", file=sys.stderr)
        return None
    return datetime.now(timezone.utc) - delta


def format_entry(entry: dict, no_color: bool = False) -> str:
    level  = entry.get("level", "INFO")
    ts     = entry.get("ts", "")[:23]  # Trim microseconds
    logger = entry.get("logger", "")
    msg    = entry.get("msg", "")
    ctx    = entry.get("context", {})
    dur    = entry.get("duration_ms")
    err    = entry.get("error")

    colour = "" if no_color else _COLOURS.get(level, "")
    reset  = "" if no_color else _COLOURS["RESET"]
    dim    = "" if no_color else _COLOURS["DIM"]

    dur_str = f" [{dur}ms]" if dur is not None else ""
    ctx_str = (" " + " ".join(f"{dim}{k}={reset}{v}" for k, v in ctx.items())) if ctx else ""
    err_str = f"\n    {colour}↳ {err[:200]}{reset}" if err else ""

    return (f"{colour}[{level[:4]}]{reset} "
            f"{dim}{ts[11:]}{reset} "
            f"{dim}{logger}:{reset} "
            f"{msg}{dur_str}{ctx_str}{err_str}")


def read_log_file(path: Path, since: Optional[datetime]) -> List[dict]:
    entries = []
    if not path.exists():
        return entries
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if since:
                        ts = datetime.fromisoformat(entry.get("ts", "").replace("Z", "+00:00"))
                        if ts < since:
                            continue
                    entries.append(entry)
                except (json.JSONDecodeError, ValueError):
                    pass
    except Exception as e:
        print(f"Error reading log file: {e}", file=sys.stderr)
    return entries


def filter_entries(entries: List[dict], level: Optional[str],
                   logger: Optional[str]) -> List[dict]:
    LEVEL_NUMS = {"DEBUG": 10, "INFO": 20, "WARN": 30, "ERROR": 40, "CRITICAL": 50}
    min_level  = LEVEL_NUMS.get(level, 0) if level else 0
    return [
        e for e in entries
        if LEVEL_NUMS.get(e.get("level", "INFO"), 20) >= min_level
        and (not logger or e.get("logger", "").startswith(logger))
    ]


def show_count(entries: List[dict], no_color: bool):
    """Show counts grouped by logger + level."""
    BOLD = "" if no_color else _COLOURS["BOLD"]
    RESET = "" if no_color else _COLOURS["RESET"]

    from collections import Counter
    counts = Counter(
        (e.get("logger", "?"), e.get("level", "?"))
        for e in entries
    )
    print(f"\n  {BOLD}Log counts:{RESET}")
    print(f"  {'Logger':<40} {'Level':<10} {'Count':>6}")
    print(f"  {'─'*60}")
    for (logger, level), count in sorted(counts.items()):
        colour = "" if no_color else _COLOURS.get(level, "")
        reset  = RESET
        print(f"  {logger:<40} {colour}{level:<10}{reset} {count:>6}")
    print()


def show_slowest(entries: List[dict], n: int, no_color: bool):
    """Show the N slowest requests by duration_ms."""
    BOLD  = "" if no_color else _COLOURS["BOLD"]
    RESET = "" if no_color else _COLOURS["RESET"]
    WARN  = "" if no_color else _COLOURS["WARN"]

    timed = [e for e in entries if e.get("duration_ms") is not None]
    timed.sort(key=lambda e: e.get("duration_ms", 0), reverse=True)
    print(f"\n  {BOLD}Slowest {n} requests:{RESET}")
    print(f"  {'Duration':>10}  {'Logger':<30}  Message")
    print(f"  {'─'*60}")
    for e in timed[:n]:
        dur = e.get("duration_ms", 0)
        colour = WARN if dur > 1000 else ""
        print(f"  {colour}{dur:>8}ms{RESET}  {e.get('logger', ''):<30}  {e.get('msg', '')[:50]}")
    print()


def tail_file(path: Path, level: Optional[str], logger: Optional[str],
              no_color: bool, json_mode: bool):
    """Tail a log file (like tail -f) with filtering."""
    print(f"Tailing {path} ... (Ctrl+C to stop)", file=sys.stderr)
    last_pos = 0
    try:
        while True:
            try:
                with open(path, encoding="utf-8") as f:
                    f.seek(last_pos)
                    new_lines = f.readlines()
                    last_pos  = f.tell()
            except FileNotFoundError:
                time.sleep(0.5)
                continue

            for line in new_lines:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                filtered = filter_entries([entry], level, logger)
                if filtered:
                    if json_mode:
                        print(line)
                    else:
                        print(format_entry(entry, no_color))
            time.sleep(0.25)

    except KeyboardInterrupt:
        print("\nStopped.", file=sys.stderr)


def main():
    args = parse_args()

    if args.stdin:
        # Read from stdin (e.g. wrangler tail | python log_viewer.py --stdin)
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            filtered = filter_entries([entry], args.level, args.logger)
            if filtered:
                if args.json:
                    print(line)
                else:
                    print(format_entry(entry, args.no_color))
        return

    log_path = Path(args.file)
    since    = parse_since(args.since) if args.since else None

    if args.tail:
        tail_file(log_path, args.level, args.logger, args.no_color, args.json)
        return

    entries  = read_log_file(log_path, since)
    filtered = filter_entries(entries, args.level, args.logger)

    if not filtered:
        msg = "No log entries found"
        if since:
            msg += f" since {args.since} ago"
        if args.level:
            msg += f" at level {args.level}+"
        if args.logger:
            msg += f" for logger '{args.logger}'"
        print(msg)
        return

    if args.count:
        show_count(filtered, args.no_color)
        return

    if args.slowest:
        show_slowest(filtered, args.slowest, args.no_color)
        return

    for entry in filtered:
        if args.json:
            print(json.dumps(entry, default=str))
        else:
            print(format_entry(entry, args.no_color))


if __name__ == "__main__":
    main()
