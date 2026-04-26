"""
delegate.py — exec-style passthrough to backend CLIs.

Used by `cohrint-agent exec <backend> ...` and by install/uninstall
subcommands that don't own state (e.g. `cohrint-agent mcp add` → `claude mcp add`).

We use ``os.execvpe`` rather than ``subprocess.run`` so:
- The child inherits our controlling TTY (needed for `claude mcp add` prompts,
  `gemini init` interactive flows, etc.).
- Signals (Ctrl-C, SIGTSTP) reach the child directly — no zombie parent.
- Exit code is the child's exit code; no double-wrapping.

Binaries resolve through ``process_safety.resolve_backend_binary`` so PATH
hijacking via a writable earlier entry is rejected at the gate.
"""
from __future__ import annotations

import os
import sys
from typing import Iterable, NoReturn

from .process_safety import resolve_backend_binary, safe_child_env

SUPPORTED_BACKENDS = ("claude", "codex", "gemini")


class DelegateError(RuntimeError):
    """Raised when a delegation request cannot be served (bad backend, missing binary)."""


def exec_backend(backend: str, args: Iterable[str]) -> NoReturn:
    """Replace this process with ``<backend> <args...>``.

    Never returns on success. Raises ``DelegateError`` if the backend is
    unknown or the binary cannot be resolved to a safe absolute path.
    """
    if backend not in SUPPORTED_BACKENDS:
        raise DelegateError(
            f"unknown backend '{backend}'. Supported: {', '.join(SUPPORTED_BACKENDS)}"
        )
    binary = resolve_backend_binary(backend)
    if binary is None:
        raise DelegateError(
            f"'{backend}' CLI not found on PATH (or binary has unsafe permissions). "
            f"Install it first: https://cohrint.com/docs#cli-reference"
        )
    argv = [binary, *list(args)]
    # execvpe replaces the process image — control does not return.
    os.execvpe(binary, argv, safe_child_env())


def exec_subcommand(backend: str, subcommand: str, extra: Iterable[str]) -> NoReturn:
    """Convenience: ``exec_backend(backend, [subcommand, *extra])``."""
    exec_backend(backend, [subcommand, *list(extra)])


def print_delegate_error(err: DelegateError) -> None:
    """Print a DelegateError to stderr in a consistent format."""
    sys.stderr.write(f"cohrint-agent: {err}\n")
