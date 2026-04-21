"""commands.skills — list Claude skills + Codex rules."""
from __future__ import annotations

import sys

from . import render_verb_help
from ._list_helper import run_list


def run(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(render_verb_help("skills"))
        return 0
    sub, rest = argv[0], argv[1:]
    if sub == "list":
        return run_list("skills", "skill", rest, empty_hint="No skills installed.")
    sys.stderr.write(f"cohrint-agent skills: unknown subcommand '{sub}'\n")
    print(render_verb_help("skills"))
    return 2
