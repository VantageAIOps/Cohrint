"""
sanitize.py — Terminal-output scrub.

Any server-origin, user-origin, or subprocess-origin string that reaches the
terminal must go through ``scrub_for_terminal()`` first. Otherwise a crafted
payload such as ``"\\x1b]52;c;BASE64\\x07"`` (OSC-52 "write to clipboard")
would be executed by the emulator when we echo it back — e.g. inside
``Unknown command: /...`` or when forwarding a child's stderr.

Guards regression tests: T-SAFETY.5, T-SAFETY.6, T-SAFETY.12.
"""
from __future__ import annotations

import re

# Strip C0 + C1 control bytes and DEL.
#   0x00-0x08, 0x0b, 0x0c, 0x0e-0x1f  (keep TAB 0x09, LF 0x0a, CR 0x0d)
#   0x7f (DEL)
#   0x80-0x9f (C1)
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")

# Length cap — matches the printable-ASCII contract in update_check. A single
# "name" or "message" never legitimately exceeds 500 printable characters on
# a terminal line; beyond that we truncate with an ellipsis marker.
_MAX_LEN = 500

# Secrets that must never reach the terminal: Anthropic keys, Cohrint tokens,
# OpenAI keys, and Bearer auth headers that SDKs sometimes include verbatim
# in error strings (T-SAFETY.secret_scrub).
_SECRET_PATTERNS = [
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}"),
    re.compile(r"crt_[A-Za-z0-9_\-]{20,}"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9_\-\.]{20,}", re.IGNORECASE),
    re.compile(r"Authorization:\s*Bearer\s+\S+", re.IGNORECASE),
]


def _redact_secrets(text: str) -> str:
    for pat in _SECRET_PATTERNS:
        text = pat.sub("[REDACTED]", text)
    return text


def scrub_for_terminal(value: object, *, max_len: int = _MAX_LEN) -> str:
    """Return a safe echoable string — no ESC, no C0/C1 controls, capped length.

    - Non-strings are coerced with ``str()`` first.
    - Tabs, LFs, and CRs are preserved (genuine line-breakers in multi-line echo).
    - Everything else in the control-character bands is removed outright.
    - Known secret patterns (sk-ant-*, crt_*, Bearer …) are redacted.
    """
    text = value if isinstance(value, str) else str(value)
    cleaned = _CONTROL_RE.sub("", text)
    cleaned = _redact_secrets(cleaned)
    if len(cleaned) > max_len:
        cleaned = cleaned[: max_len - 1] + "…"
    return cleaned


def scrub_token(value: object, *, max_len: int = 64) -> str:
    """Short-form scrubber for single-word tokens (command names, tool names)."""
    text = value if isinstance(value, str) else str(value)
    # Reject anything outside printable ASCII for the short-form variant —
    # command names never need UTF-8 and control chars must not leak here.
    cleaned = "".join(c for c in text if 0x20 <= ord(c) <= 0x7E)
    return cleaned[:max_len]
