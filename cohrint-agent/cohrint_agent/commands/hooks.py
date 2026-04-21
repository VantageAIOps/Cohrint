"""commands.hooks — list hooks declared in settings.json files."""
from __future__ import annotations

import sys

from . import render_verb_help
from ._list_helper import run_list


def run(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(render_verb_help("hooks"))
        return 0
    sub, rest = argv[0], argv[1:]
    if sub == "list":
        return run_list(
            "hooks",
            "hook",
            rest,
            empty_hint="No hooks configured. See https://cohrint.com/docs#hooks.",
        )
    sys.stderr.write(f"cohrint-agent hooks: unknown subcommand '{sub}'\n")
    print(render_verb_help("hooks"))
    return 2
