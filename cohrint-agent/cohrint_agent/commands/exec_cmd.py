"""commands.exec_cmd — raw passthrough to a backend CLI."""
from __future__ import annotations

import sys

from . import render_verb_help
from ..delegate import DelegateError, SUPPORTED_BACKENDS, exec_backend, print_delegate_error


def run(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(render_verb_help("exec"))
        return 0
    backend, rest = argv[0], argv[1:]
    if backend not in SUPPORTED_BACKENDS:
        sys.stderr.write(
            f"cohrint-agent exec: unknown backend '{backend}'. "
            f"Supported: {', '.join(SUPPORTED_BACKENDS)}\n"
        )
        return 2
    try:
        exec_backend(backend, rest)  # noreturn on success
    except DelegateError as e:
        print_delegate_error(e)
        return 127
    return 0  # unreachable, keeps type-checker happy
