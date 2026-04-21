"""repl_completer — readline tab-completion + history for the interactive REPL.

Completion model is context-aware:
  <empty>           → nothing (don't flood the user)
  /<prefix>         → slash commands + `/<verb>` forms
  /<verb> <prefix>  → that verb's subcommands (from commands.CATALOG)
  /model <prefix>   → pricing.MODEL_PRICES
  /allow <prefix>   → TOOL_MAP keys + "all"
  /guardrails <..>  → action/kind keywords

Readline isn't available on Windows by default; we degrade silently.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


_HISTORY_PATH = Path(os.path.expanduser("~")) / ".cohrint-agent" / "repl_history"
_HISTORY_LEN = 1000


def _static_slash_commands() -> list[str]:
    """Hard-coded REPL slash commands (the ones _handle_command dispatches)."""
    return [
        "/help", "/quit", "/exit", "/q",
        "/tools", "/allow", "/cost", "/reset", "/reset-all",
        "/optimize", "/model", "/verbs", "/guardrails",
        "/tier", "/summary", "/budget",
    ]


def _verb_slash_commands() -> list[str]:
    from .commands import VERBS
    return [f"/{v}" for v in VERBS]


def _subcommand_tokens(verb: str) -> list[str]:
    """Extract first tokens from CATALOG[verb].subcommands keys.

    `commands.CATALOG` describes subcommands as e.g. ``"list [--backend X]"`` —
    we only want ``list``. Argument placeholders and flags are left out;
    completing `--flag` would be noisy here.
    """
    from .commands import CATALOG
    spec = CATALOG.get(verb)
    if spec is None:
        return []
    out: list[str] = []
    for key in spec.subcommands.keys():
        if not key:
            continue
        first = key.split()[0]
        # Drop placeholders like "<backend>" and flag-only keys.
        if first.startswith("<") or first.startswith("-"):
            continue
        if first not in out:
            out.append(first)
    return out


def _candidates_for_line(line: str) -> list[str]:
    """Return the full candidate set for the current buffer state."""
    left = line.lstrip()
    if not left:
        return []

    # Multi-word: we're past the verb. Branch on verb. ``split(None, 1)``
    # drops a trailing space entirely ("mcp ".split() == ["mcp"]), so we
    # pad rest with "" when the user has typed verb+space but no arg yet.
    if " " in left:
        parts = left.split(None, 1)
        first = parts[0]
        rest = parts[1] if len(parts) > 1 else ""
        # Strip leading slash if present.
        verb = first[1:] if first.startswith("/") else first

        if verb == "model":
            from .pricing import MODEL_PRICES
            return [m for m in sorted(MODEL_PRICES) if m != "default"]
        if verb == "allow":
            from .tools import TOOL_MAP
            return ["all", *sorted(TOOL_MAP.keys())]
        if verb == "guardrails":
            # `rest` tokens + whether user has typed a trailing space tell us
            # which slot we're filling: slot 1 = action (on/off/status),
            # slot 2 = kind.
            toks = rest.split()
            on_new_token = left.endswith(" ")
            at_slot = len(toks) + (1 if on_new_token else 0)
            if at_slot <= 1:
                return ["on", "off", "status"]
            return ["recommendation", "hallucination", "all"]
        if verb == "optimize":
            return ["on", "off"]

        # CLI-verb subcommands routed via /<verb>.
        return _subcommand_tokens(verb)

    # Single word so far. Offer slash commands + verb shortcuts.
    if left.startswith("/"):
        return sorted(set(_static_slash_commands() + _verb_slash_commands()))

    return []


def _make_completer():
    """Return a readline completer function.

    readline calls the function repeatedly with the same ``text`` and an
    increasing ``state`` index until the function returns None. We cache
    the candidate list between calls in the closure.
    """
    cache: dict[str, list[str]] = {"line": "", "matches": []}

    def completer(text: str, state: int):
        try:
            import readline
            line = readline.get_line_buffer()
        except Exception:  # noqa: BLE001
            return None

        if line != cache["line"]:
            all_candidates = _candidates_for_line(line)
            # Filter by current token prefix. Thanks to custom delims ('/' is
            # NOT a delim), ``text`` already includes the leading slash.
            cache["line"] = line
            cache["matches"] = [c for c in all_candidates if c.startswith(text)]

        matches = cache["matches"]
        if state < len(matches):
            return matches[state]
        return None

    return completer


def install() -> None:
    """Wire readline into the current process. Safe to call once per run.

    No-op if readline is unavailable (Windows without pyreadline3) or if the
    stream isn't a TTY. History file lives at ~/.cohrint-agent/repl_history,
    created with 0o600 on first write.
    """
    try:
        import readline
    except ImportError:
        return
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return

    # Keep '/' as part of the token so "/mc<TAB>" completes to "/mcp".
    readline.set_completer_delims(" \t\n")
    readline.set_completer(_make_completer())

    # libedit (macOS default) uses a different bind syntax than GNU readline.
    if "libedit" in getattr(readline, "__doc__", "") or "":
        readline.parse_and_bind("bind ^I rl_complete")
    else:
        readline.parse_and_bind("tab: complete")

    try:
        _HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        if _HISTORY_PATH.exists():
            readline.read_history_file(str(_HISTORY_PATH))
        readline.set_history_length(_HISTORY_LEN)
    except OSError:
        # Unwritable home dir shouldn't block the REPL — just skip history.
        return

    # Persist on normal exit. atexit runs even for Ctrl-D / KeyboardInterrupt
    # that propagates out of the REPL loop.
    import atexit

    def _save_history() -> None:
        try:
            readline.write_history_file(str(_HISTORY_PATH))
            # Restrict history to the owner — prompt text can contain secrets.
            try:
                os.chmod(_HISTORY_PATH, 0o600)
            except OSError:
                pass
        except OSError:
            pass

    atexit.register(_save_history)


__all__ = ["install"]
