"""commands.permissions — list + add/remove allow/deny/ask rules."""
from __future__ import annotations

import argparse
import sys

from . import render_verb_help
from ._list_helper import run_list
from ..writers import add_permission, remove_permission


def _run_mutate(rest: list[str], *, kind: str) -> int:
    parser = argparse.ArgumentParser(prog=f"cohrint-agent permissions {kind}")
    parser.add_argument("rule", help="Permission rule, e.g. 'Bash(npm *)'")
    parser.add_argument("--scope", choices=("global", "project"), default="global")
    ns = parser.parse_args(rest)
    result = add_permission(kind, ns.rule, scope=ns.scope)
    out = sys.stdout if result.ok else sys.stderr
    out.write(result.message + "\n")
    return 0 if result.ok else 2


def _run_remove(rest: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="cohrint-agent permissions remove")
    parser.add_argument("kind", choices=("allow", "deny", "ask"))
    parser.add_argument("rule")
    parser.add_argument("--scope", choices=("global", "project"), default="global")
    ns = parser.parse_args(rest)
    result = remove_permission(ns.kind, ns.rule, scope=ns.scope)
    out = sys.stdout if result.ok else sys.stderr
    out.write(result.message + "\n")
    return 0 if result.ok else 2


def run(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(render_verb_help("permissions"))
        return 0
    sub, rest = argv[0], argv[1:]
    if sub == "list":
        return run_list(
            "permissions",
            "permission",
            rest,
            empty_hint="No permission rules configured. Default mode applies.",
        )
    if sub in ("allow", "deny", "ask"):
        return _run_mutate(rest, kind=sub)
    if sub in ("remove", "rm"):
        return _run_remove(rest)
    sys.stderr.write(f"cohrint-agent permissions: unknown subcommand '{sub}'\n")
    print(render_verb_help("permissions"))
    return 2
