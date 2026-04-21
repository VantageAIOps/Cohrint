"""commands.plugins — list Claude Code plugins. Gemini/Codex have no plugins."""
from __future__ import annotations

import sys

from . import render_verb_help
from ._list_helper import run_list


def run(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(render_verb_help("plugins"))
        return 0
    sub, rest = argv[0], argv[1:]
    if sub == "list":
        return run_list(
            "plugins",
            "plugin",
            rest,
            empty_hint="No plugins enabled. (Codex and Gemini have no plugin concept.)",
        )
    sys.stderr.write(f"cohrint-agent plugins: unknown subcommand '{sub}'\n")
    print(render_verb_help("plugins"))
    return 2
