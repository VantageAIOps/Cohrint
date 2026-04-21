"""commands.hooks — list / add / remove hooks in settings.json."""
from __future__ import annotations

import argparse
import sys

from . import render_verb_help
from ._list_helper import run_list
from ..writers import VALID_HOOK_EVENTS, add_hook, remove_hook


def _run_add(rest: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="cohrint-agent hooks add")
    parser.add_argument("event", choices=VALID_HOOK_EVENTS)
    parser.add_argument("matcher", help="Tool-name pattern, e.g. 'Write|Edit' or '*'")
    parser.add_argument("command", help="Shell command to run")
    parser.add_argument("--scope", choices=("global", "project"), default="global")
    ns = parser.parse_args(rest)
    result = add_hook(ns.event, ns.matcher, ns.command, scope=ns.scope)
    out = sys.stdout if result.ok else sys.stderr
    out.write(result.message + "\n")
    return 0 if result.ok else 2


def _run_remove(rest: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="cohrint-agent hooks remove")
    parser.add_argument("event")
    parser.add_argument("matcher")
    parser.add_argument("--scope", choices=("global", "project"), default="global")
    ns = parser.parse_args(rest)
    result = remove_hook(ns.event, ns.matcher, scope=ns.scope)
    out = sys.stdout if result.ok else sys.stderr
    out.write(result.message + "\n")
    return 0 if result.ok else 2


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
    if sub == "add":
        return _run_add(rest)
    if sub in ("remove", "rm"):
        return _run_remove(rest)
    sys.stderr.write(f"cohrint-agent hooks: unknown subcommand '{sub}'\n")
    print(render_verb_help("hooks"))
    return 2
