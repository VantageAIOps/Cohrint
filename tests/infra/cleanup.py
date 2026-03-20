"""
cleanup.py — Remove stale test artifacts, logs, __pycache__, empty dirs.
Called automatically by run_suite.py at the start of each run.
Also usable as a standalone: python tests/infra/cleanup.py [--dry-run] [--all]
"""

import os
import sys
import shutil
import argparse
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from config.settings import ARTIFACTS_DIR, ARTIFACT_MAX_AGE_DAYS
except Exception:
    ARTIFACTS_DIR = Path(os.environ.get("VANTAGE_TEST_ARTIFACTS_DIR",
                                        str(Path(__file__).parent.parent / "artifacts")))
    ARTIFACT_MAX_AGE_DAYS = int(os.environ.get("VANTAGE_ARTIFACT_MAX_AGE_DAYS", "7"))

TESTS_ROOT = Path(__file__).parent.parent

B = "\033[34mℹ\033[0m"
W = "\033[33m⚠\033[0m"
G = "\033[32m✓\033[0m"


def cleanup_old_artifacts(dry_run=False, clean_all=False):
    """Remove artifact subdirs older than ARTIFACT_MAX_AGE_DAYS."""
    if not ARTIFACTS_DIR.exists():
        print(f"  {B}  Artifacts dir does not exist: {ARTIFACTS_DIR}")
        return 0

    cutoff = datetime.now() - timedelta(days=ARTIFACT_MAX_AGE_DAYS)
    removed = 0

    for item in sorted(ARTIFACTS_DIR.iterdir()):
        if not item.is_dir():
            # Remove stale individual files (e.g. old .jsonl, .json, .html)
            if clean_all or item.stat().st_mtime < cutoff.timestamp():
                if dry_run:
                    print(f"  {W}  [dry-run] Would remove file: {item}")
                else:
                    item.unlink(missing_ok=True)
                    print(f"  {G}  Removed file: {item.name}")
                removed += 1
            continue

        # For directories, check mtime
        try:
            mtime = item.stat().st_mtime
            age = datetime.now() - datetime.fromtimestamp(mtime)
        except OSError:
            continue

        if clean_all or age.days >= ARTIFACT_MAX_AGE_DAYS:
            if dry_run:
                print(f"  {W}  [dry-run] Would remove dir: {item}")
            else:
                shutil.rmtree(item, ignore_errors=True)
                print(f"  {G}  Removed artifact dir: {item.name}")
            removed += 1

    return removed


def cleanup_pycache(root: Path, dry_run=False):
    """Remove all __pycache__ and .pyc files under root."""
    removed = 0

    for pycache_dir in root.rglob("__pycache__"):
        if pycache_dir.is_dir():
            if dry_run:
                print(f"  {W}  [dry-run] Would remove: {pycache_dir}")
            else:
                shutil.rmtree(pycache_dir, ignore_errors=True)
                print(f"  {G}  Removed: {pycache_dir.relative_to(root)}")
            removed += 1

    for pyc_file in root.rglob("*.pyc"):
        if pyc_file.is_file():
            if dry_run:
                print(f"  {W}  [dry-run] Would remove: {pyc_file}")
            else:
                pyc_file.unlink(missing_ok=True)
            removed += 1

    return removed


def cleanup_empty_dirs(root: Path, dry_run=False):
    """Remove empty directories (bottom-up so nested empties are caught)."""
    removed = 0

    # Walk bottom-up
    for dirpath, dirnames, filenames in os.walk(str(root), topdown=False):
        d = Path(dirpath)
        if d == root:
            continue
        try:
            # Empty = no files and no subdirs remaining
            if not any(d.iterdir()):
                if dry_run:
                    print(f"  {W}  [dry-run] Would remove empty dir: {d}")
                else:
                    d.rmdir()
                    print(f"  {G}  Removed empty dir: {d.relative_to(root)}")
                removed += 1
        except (OSError, ValueError):
            pass

    return removed


def run(dry_run=False, clean_all=False):
    """Run full cleanup."""
    print(f"\n  {B}  Running cleanup (dry_run={dry_run}, clean_all={clean_all})")

    n1 = cleanup_old_artifacts(dry_run=dry_run, clean_all=clean_all)
    n2 = cleanup_pycache(TESTS_ROOT, dry_run=dry_run)
    n3 = cleanup_empty_dirs(TESTS_ROOT, dry_run=dry_run)

    total = n1 + n2 + n3
    label = "[dry-run] Would remove" if dry_run else "Removed"
    print(f"  {G}  Cleanup done — {label} {total} items "
          f"({n1} artifact dirs/files, {n2} pycache, {n3} empty dirs)\n")
    return total


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="VantageAI test artifact cleanup")
    p.add_argument("--dry-run", action="store_true",
                   help="Show what would be removed without deleting")
    p.add_argument("--all", action="store_true",
                   help="Remove ALL artifacts regardless of age")
    args = p.parse_args()
    run(dry_run=args.dry_run, clean_all=args.all)
