"""
repl_input.py — Multi-line prompt reader used by the Cohrint Agent REPL.

Design
------

The REPL used to call ``console.input()`` once per Enter. A multi-line paste
therefore fragmented into N separate prompts — each of which triggered its
own LLM roundtrip — producing the garbled transcript you saw in issue
#agent-cli-ux-redesign. This module replaces that with a single aggregation
step that understands three multi-line syntaxes:

  1. *Bracketed paste* (handled at the I/O layer by prompt_toolkit): the
     whole paste arrives as **one** string with embedded ``\\n`` characters.
     The aggregator passes it through unchanged.
  2. *Triple-quote block* — user types ``\"\"\"`` to open a multi-line
     block; everything until the closing ``\"\"\"`` (or EOF) is the prompt.
  3. *Backslash continuation* — user ends a line with ``\\`` to indicate
     "more is coming". The aggregator keeps reading and joins on newline
     until a line has no trailing backslash.

I/O is abstracted via a ``line_source`` callable — the pure aggregation
logic is unit-tested without touching the terminal. The REPL installs
``read_prompt`` which wires a prompt_toolkit session (for bracketed-paste
support + history) or a ``console.input`` fallback on non-TTY.
"""
from __future__ import annotations

from typing import Callable, Optional

LineSource = Callable[[str], str]

_TRIPLE = '"""'
_CONT_SUFFIX = "\\"


def aggregate_lines(line_source: LineSource) -> Optional[str]:
    """Return the user's full prompt — possibly multi-line.

    ``line_source(prompt_text)`` returns one line (Enter-terminated, no
    trailing newline) or raises ``EOFError`` / ``KeyboardInterrupt`` on
    end-of-input.

    Semantics:
      - First-line EOF / Ctrl-C with empty buffer → ``None`` (REPL quits).
      - Blank first line → ``""`` (REPL ignores and re-prompts).
      - Line starting with ``\"\"\"`` opens a block; content up to the
        next ``\"\"\"`` or EOF is the body.
      - Line ending with a bare ``\\`` triggers continuation mode; the
        backslash is stripped and a newline joins continued lines. EOF
        inside a continuation still returns the accumulated body —
        partial > lost.
      - Otherwise the single line is returned as-is (supports
        bracketed-paste, where ``line`` itself may contain ``\\n``).

    The aggregator deliberately does not sanitize content — terminal
    escape scrubbing happens downstream at render time so log/replay
    paths still see the original bytes.
    """
    try:
        first = line_source("cohrint> ")
    except (EOFError, KeyboardInterrupt):
        return None

    if first.startswith(_TRIPLE):
        return _read_triple_block(first, line_source)
    if first.endswith(_CONT_SUFFIX) and not first.endswith("\\\\"):
        return _read_backslash_block(first, line_source)
    return first


def _read_triple_block(first: str, line_source: LineSource) -> str:
    """Handle triple-quote multi-line block, starting with ``first``."""
    # Same-line open+close: """foo""" → foo
    body_first = first[len(_TRIPLE):]
    if body_first.endswith(_TRIPLE):
        return body_first[: -len(_TRIPLE)]

    parts: list[str] = [body_first]
    while True:
        try:
            nxt = line_source("... ")
        except (EOFError, KeyboardInterrupt):
            # Partial block — return what we have rather than losing it.
            break
        if nxt.endswith(_TRIPLE):
            parts.append(nxt[: -len(_TRIPLE)])
            break
        parts.append(nxt)

    # Drop leading/trailing empty segments produced by `"""\n...\n"""`
    if parts and parts[0] == "":
        parts = parts[1:]
    if parts and parts[-1] == "":
        parts = parts[:-1]
    return "\n".join(parts)


def _read_backslash_block(first: str, line_source: LineSource) -> str:
    """Handle trailing-backslash continuation, starting with ``first``."""
    parts: list[str] = [first[: -len(_CONT_SUFFIX)]]
    while True:
        try:
            nxt = line_source("... ")
        except (EOFError, KeyboardInterrupt):
            break
        if nxt.endswith(_CONT_SUFFIX) and not nxt.endswith("\\\\"):
            parts.append(nxt[: -len(_CONT_SUFFIX)])
            continue
        parts.append(nxt)
        break
    return "\n".join(parts)


# ── Terminal-backed reader ────────────────────────────────────────────
#
# Public entry point wired into cli.run_repl(). Uses prompt_toolkit on TTYs
# (bracketed paste + history + tab-completion already installed elsewhere)
# and falls back to rich's ``console.input`` otherwise.


_pt_session = None  # lazy: don't import prompt_toolkit in non-TTY / pipe mode


def _get_pt_session():
    global _pt_session
    if _pt_session is not None:
        return _pt_session
    try:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.history import InMemoryHistory
    except ImportError:
        return None
    # InMemoryHistory keeps ↑/↓ recall scoped to the current session — we
    # deliberately do NOT persist prompt history to disk: the transcript
    # would then leak across users on shared machines (T-SAFETY.history_leak).
    _pt_session = PromptSession(history=InMemoryHistory())
    return _pt_session


def _pt_line_source(prompt_text: str) -> str:
    """Read one line via prompt_toolkit — gets bracketed-paste capture
    and keeps prompt history navigable with ↑/↓."""
    session = _get_pt_session()
    if session is None:  # dependency missing — fall through to raw input()
        return input(prompt_text)
    return session.prompt(prompt_text)


def _console_line_source(prompt_text: str) -> str:
    """Fallback when prompt_toolkit is unavailable or stdin is non-TTY."""
    from rich.console import Console
    return Console().input(prompt_text)


def read_prompt() -> Optional[str]:
    """REPL front-door: return the user's next prompt (possibly multi-line)
    or ``None`` if they quit with Ctrl-D on an empty line.

    The caller decides what to do with an empty string — ``cli.run_repl``
    re-prompts silently so an accidental Enter doesn't burn a backend turn.
    """
    import sys
    try:
        is_tty = sys.stdin.isatty() and sys.stdout.isatty()
    except (AttributeError, ValueError):
        is_tty = False
    source = _pt_line_source if is_tty else _console_line_source
    return aggregate_lines(source)
