"""
structured_logger.py — Structured JSON logging infrastructure for Cohrint
============================================================================
Purpose:
  Central logging layer used by both the test suite and (eventually) the
  production Cloudflare Worker / FastAPI server.  Every log entry is a
  newline-delimited JSON object so it can be:
    - Streamed to stdout and parsed by any log aggregator (Datadog, Logtail,
      Cloudflare Logpush, etc.)
    - Written to a rotating .jsonl file for local development debugging
    - Filtered, searched, and counted with `jq`

Log entry schema:
  {
    "ts":       "2026-03-19T14:23:01.123Z",   // ISO-8601 UTC
    "level":    "INFO",                        // DEBUG | INFO | WARN | ERROR | CRITICAL
    "logger":   "auth.signup",                // dotted name of the logger
    "msg":      "Signup succeeded",
    "context":  { ... },                      // arbitrary key-value pairs
    "duration_ms": 142,                       // optional — latency of the operation
    "error":    null,                         // optional — exception repr
    "test":     "test_signup_valid_email"     // optional — test name (set in test mode)
  }

Usage:
  from logging_infra.structured_logger import get_logger

  log = get_logger("auth.signup")
  log.info("Signup succeeded", email=email, org_id=org_id, duration_ms=128)
  log.error("Signup failed", email=email, status=r.status_code, error=str(e))

  # As context manager for automatic duration tracking:
  with log.timer("POST /v1/auth/signup"):
      r = requests.post(...)
"""

import os
import sys
import json
import time
import logging
import traceback
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# ── Configuration ─────────────────────────────────────────────────────────────
LOG_LEVEL   = os.environ.get("VANTAGE_LOG_LEVEL", "INFO").upper()
LOG_FILE    = os.environ.get("VANTAGE_LOG_FILE", "")        # empty → stdout only
LOG_FORMAT  = os.environ.get("VANTAGE_LOG_FORMAT", "json")  # json | pretty
LOG_TEST    = os.environ.get("VANTAGE_TEST_NAME", "")       # set by test runner

LEVELS = {"DEBUG": 10, "INFO": 20, "WARN": 30, "ERROR": 40, "CRITICAL": 50}

# ── Internal file writer ──────────────────────────────────────────────────────
_lock        = threading.Lock()
_file_handle = None

def _get_file():
    global _file_handle
    if _file_handle is None and LOG_FILE:
        p = Path(LOG_FILE)
        p.parent.mkdir(parents=True, exist_ok=True)
        _file_handle = open(p, "a", buffering=1, encoding="utf-8")
    return _file_handle

# ── ANSI colour for pretty mode ───────────────────────────────────────────────
_COLOURS = {
    "DEBUG":    "\033[90m",
    "INFO":     "\033[32m",
    "WARN":     "\033[33m",
    "ERROR":    "\033[31m",
    "CRITICAL": "\033[35m",
}
_RESET = "\033[0m"

# ── Core writer ───────────────────────────────────────────────────────────────
def _write(entry: dict):
    with _lock:
        if LOG_FORMAT == "pretty":
            colour = _COLOURS.get(entry["level"], "")
            ctx    = " ".join(f"{k}={v}" for k, v in entry.get("context", {}).items())
            dur    = f" [{entry['duration_ms']}ms]" if entry.get("duration_ms") else ""
            err    = f"\n  ↳ {entry['error']}" if entry.get("error") else ""
            line   = (f"{colour}[{entry['level'][:4]}]{_RESET} "
                      f"{entry['ts'][11:23]} "
                      f"{entry['logger']}: {entry['msg']}{dur}"
                      f"{(' ' + ctx) if ctx else ''}{err}")
        else:
            line = json.dumps(entry, default=str)

        print(line, flush=True)
        fh = _get_file()
        if fh:
            fh.write(json.dumps(entry, default=str) + "\n")
            fh.flush()


# ── Timer context manager ─────────────────────────────────────────────────────
class _Timer:
    def __init__(self, logger: "VantageLogger", label: str, level="INFO", **ctx):
        self._log   = logger
        self._label = label
        self._level = level
        self._ctx   = ctx
        self._start = None

    def __enter__(self):
        self._start = time.monotonic()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        dur = round((time.monotonic() - self._start) * 1000)
        if exc_type is None:
            self._log._emit(self._level, f"{self._label} completed",
                            duration_ms=dur, **self._ctx)
        else:
            self._log._emit("ERROR", f"{self._label} failed",
                            duration_ms=dur, error=repr(exc_val), **self._ctx)
        return False  # don't suppress exceptions


# ── VantageLogger ─────────────────────────────────────────────────────────────
class VantageLogger:
    """
    Structured JSON logger.  Create one per module/component:
        log = VantageLogger("auth.signup")
    """

    def __init__(self, name: str):
        self.name = name

    def _emit(self, level: str, msg: str,
              duration_ms: Optional[int] = None,
              error: Optional[str] = None,
              **ctx):
        if LEVELS.get(level, 0) < LEVELS.get(LOG_LEVEL, 20):
            return
        entry = {
            "ts":      datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "level":   level,
            "logger":  self.name,
            "msg":     msg,
            "context": ctx or {},
        }
        if duration_ms is not None:
            entry["duration_ms"] = duration_ms
        if error is not None:
            entry["error"] = error
        if LOG_TEST:
            entry["test"] = LOG_TEST
        _write(entry)

    def debug(self, msg: str, **ctx):    self._emit("DEBUG",    msg, **ctx)
    def info(self, msg: str, **ctx):     self._emit("INFO",     msg, **ctx)
    def warn(self, msg: str, **ctx):     self._emit("WARN",     msg, **ctx)
    def error(self, msg: str, **ctx):    self._emit("ERROR",    msg, **ctx)
    def critical(self, msg: str, **ctx): self._emit("CRITICAL", msg, **ctx)

    def exception(self, msg: str, exc: Exception, **ctx):
        """Log at ERROR level with full traceback in the error field."""
        self._emit("ERROR", msg,
                   error=traceback.format_exc(),
                   exc_type=type(exc).__name__,
                   **ctx)

    def timer(self, label: str, level="INFO", **ctx) -> _Timer:
        """
        Context manager that logs duration on exit.

        with log.timer("POST /v1/auth/session", key_prefix="crt_abc"):
            r = requests.post(...)
        """
        return _Timer(self, label, level=level, **ctx)

    def request(self, method: str, url: str, status: int,
                duration_ms: int, **ctx):
        """Convenience method for HTTP request logging."""
        level = "ERROR" if status >= 500 else ("WARN" if status >= 400 else "INFO")
        self._emit(level, f"{method} {url}",
                   status=status, duration_ms=duration_ms, **ctx)


# ── Module-level convenience ──────────────────────────────────────────────────
_loggers: dict[str, VantageLogger] = {}

def get_logger(name: str) -> VantageLogger:
    """Return (or create) a named logger.  Thread-safe."""
    if name not in _loggers:
        with _lock:
            if name not in _loggers:
                _loggers[name] = VantageLogger(name)
    return _loggers[name]
