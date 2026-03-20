"""
cleanup.py — Standalone test artifact cleanup for VantageAI test suite
=======================================================================
Usage:
  python tests/cleanup.py [--dry-run] [--all]

Imports and calls infra.cleanup.run().
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from infra.cleanup import run

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="VantageAI test artifact cleanup")
    p.add_argument("--dry-run", action="store_true",
                   help="Show what would be removed without deleting")
    p.add_argument("--all", action="store_true",
                   help="Remove ALL artifacts regardless of age")
    args = p.parse_args()
    run(dry_run=args.dry_run, clean_all=args.all)
