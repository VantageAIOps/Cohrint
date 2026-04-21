"""commands.init_cmd — append-safe project scaffold.

Creates a cohrint-managed block in CLAUDE.md between
``<!-- cohrint:begin -->`` / ``<!-- cohrint:end -->`` markers. Subsequent
runs update just that block, leaving everything else untouched.
"""
from __future__ import annotations

import argparse
import sys

from . import render_verb_help
from ..writers import init_project


def run(argv: list[str]) -> int:
    if any(a in ("-h", "--help", "help") for a in argv):
        print(render_verb_help("init"))
        return 0
    parser = argparse.ArgumentParser(prog="cohrint-agent init", add_help=False)
    parser.add_argument("--force", action="store_true", help="Overwrite an existing cohrint block")
    ns = parser.parse_args(argv)
    result = init_project(force=ns.force)
    out = sys.stdout if result.ok else sys.stderr
    out.write(result.message + "\n")
    return 0 if result.ok else 2
