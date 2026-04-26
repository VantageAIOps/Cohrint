"""
tui.py — questionary wrappers with a non-TTY fallback.

Every interactive helper here checks ``sys.stdin.isatty()`` and ``sys.stdout.isatty()``
first; if either is piped/redirected (CI, `cohrint-agent X | grep`, etc.) we
return a non-interactive default instead of trying to drive the terminal.

questionary raises ``NoConsoleScreenBufferError`` / ``EOFError`` on non-TTY
stdin — catching at this layer keeps callers free of try/except noise.
"""
from __future__ import annotations

import sys
from typing import Iterable, Sequence


def is_tty() -> bool:
    """True iff both stdin and stdout are real terminals."""
    try:
        return sys.stdin.isatty() and sys.stdout.isatty()
    except (AttributeError, ValueError):
        # pytest capture gives us a non-isatty object; treat as non-TTY.
        return False


def select_one(
    message: str,
    choices: Sequence[str],
    *,
    default: str | None = None,
) -> str | None:
    """Prompt the user to pick one item from ``choices``.

    Returns the selected string, or ``None`` if the user cancelled (Ctrl-C,
    Esc, EOF). On non-TTY we return ``default`` if supplied, else the first
    choice; this keeps pipelines unblocked without silently making decisions
    for the user when they ARE interactive.
    """
    if not choices:
        return None
    if not is_tty():
        return default if default is not None else choices[0]
    try:
        import questionary
    except ImportError:
        # Degrade to first-choice if questionary unavailable; keeps the CLI
        # usable if someone downgraded deps.
        return default if default is not None else choices[0]
    try:
        answer = questionary.select(
            message,
            choices=list(choices),
            default=default,
        ).ask()
    except (KeyboardInterrupt, EOFError):
        return None
    return answer if isinstance(answer, str) else None


def confirm(
    message: str,
    *,
    default: bool = False,
) -> bool:
    """Yes/no prompt. Non-TTY returns ``default``."""
    if not is_tty():
        return default
    try:
        import questionary
    except ImportError:
        return default
    try:
        answer = questionary.confirm(message, default=default).ask()
    except (KeyboardInterrupt, EOFError):
        return False
    return bool(answer) if answer is not None else False


def multiselect(
    message: str,
    choices: Sequence[str],
) -> list[str]:
    """Pick zero or more items. Non-TTY returns empty list."""
    if not choices or not is_tty():
        return []
    try:
        import questionary
    except ImportError:
        return []
    try:
        answer = questionary.checkbox(message, choices=list(choices)).ask()
    except (KeyboardInterrupt, EOFError):
        return []
    return list(answer) if answer else []


def autocomplete(
    message: str,
    choices: Iterable[str],
    *,
    default: str = "",
) -> str | None:
    """Free-text prompt with tab-completion. Non-TTY falls through to raw input."""
    choices_list = list(choices)
    if not is_tty():
        return default or None
    try:
        import questionary
    except ImportError:
        return default or None
    try:
        answer = questionary.autocomplete(
            message,
            choices=choices_list,
            default=default,
        ).ask()
    except (KeyboardInterrupt, EOFError):
        return None
    return answer if isinstance(answer, str) else None
