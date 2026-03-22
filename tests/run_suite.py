"""
run_suite.py — VantageAI test suite runner (CI/CD only)
=======================================================
Discovers suites from tests/suites/NN_category/test_*.py
Runs each file as a subprocess, streams output, writes artifacts.

Usage (via GitHub Actions — not run locally):
  python tests/run_suite.py [flags]

Flags:
  --category NAME   Run only suites in suites/NN_NAME/ (e.g. 01_api)
  --suite ID        Run specific suite number prefix (e.g. 09)
  --fast            Skip stress (06_*), load (07_*), latency (08_*)
  --no-browser      Skip UI suites (02_ui, 13_dashboard)
  --integrations    Include integration suites (11_integrations, 12_mcp)
  --security        Include security + rate-limiting suites
  --superadmin      Include superadmin suite (14_superadmin)
  --cross-browser   Include cross-browser suite (15_cross_browser)
  --all             Run everything
  --no-report       Skip writing summary artifact
  --clean           Run cleanup before starting
"""

import os
import sys
import json
import time
import subprocess
import argparse
from pathlib import Path
from datetime import datetime, timezone

# ── Setup ─────────────────────────────────────────────────────────────────────
TESTS_ROOT = Path(__file__).parent
sys.path.insert(0, str(TESTS_ROOT))

try:
    from config.settings import ARTIFACTS_DIR, SITE_URL, API_URL
except Exception:
    ARTIFACTS_DIR = Path(os.environ.get("VANTAGE_TEST_ARTIFACTS_DIR",
                                        str(TESTS_ROOT / "artifacts")))
    SITE_URL = os.environ.get("VANTAGE_SITE_URL", "https://vantageaiops.com")
    API_URL  = os.environ.get("VANTAGE_API_URL",  "https://api.vantageaiops.com")

try:
    from infra.structured_logger import get_logger
    log = get_logger("suite.runner")
except Exception:
    class _NullLogger:
        def info(self, *a, **kw): pass
        def warn(self, *a, **kw): pass
        def error(self, *a, **kw): pass
    log = _NullLogger()

BOLD  = "\033[1m"
RESET = "\033[0m"
G     = "\033[32m✓\033[0m"
R     = "\033[31m✗\033[0m"
W     = "\033[33m⚠\033[0m"
B     = "\033[34mℹ\033[0m"

SUITES_DIR = TESTS_ROOT / "suites"

# Category groupings
CAT_DEFAULT      = {"01_api", "02_ui", "03_user_individual", "04_user_team", "05_user_org"}
CAT_HEAVY        = {"06_stress", "07_load", "08_latency"}
CAT_SECURITY_RL  = {"09_rate_limiting", "10_security"}
CAT_INTEGRATIONS = {"11_integrations", "12_mcp"}
CAT_DASHBOARD    = {"13_dashboard"}
CAT_SUPERADMIN    = {"14_superadmin"}
CAT_CROSS_BROWSER = {"15_cross_browser"}
CAT_BROWSER       = {"02_ui", "13_dashboard"}


def discover_suites(filter_categories=None):
    """
    Discover all test files under tests/suites/NN_category/test_*.py
    Returns sorted list of (category_dir, filepath) tuples.
    """
    if not SUITES_DIR.exists():
        return []

    suites = []
    for cat_dir in sorted(SUITES_DIR.iterdir()):
        if not cat_dir.is_dir():
            continue
        cat_name = cat_dir.name

        if filter_categories is not None and cat_name not in filter_categories:
            continue

        for test_file in sorted(cat_dir.glob("test_*.py")):
            suites.append((cat_name, test_file))

    return suites


def run_suite_file(filepath: Path, pythonpath: str) -> dict:
    """Run a single test file as a subprocess. Streams output to terminal."""
    env = {**os.environ, "PYTHONPATH": pythonpath}
    t0 = time.monotonic()

    proc = subprocess.run(
        [sys.executable, str(filepath)],
        env=env,
        capture_output=False,  # stream directly to terminal
        text=True,
    )
    ms = round((time.monotonic() - t0) * 1000)
    return {
        "file":        str(filepath.relative_to(TESTS_ROOT)),
        "category":    filepath.parent.name,
        "returncode":  proc.returncode,
        "duration_ms": ms,
        "passed":      proc.returncode == 0,
    }


def parse_args():
    p = argparse.ArgumentParser(
        description="VantageAI test suite runner (CI/CD only)"
    )
    p.add_argument("--category", type=str, default=None,
                   help="Run only suites in suites/NN_NAME/ (e.g. 01_api)")
    p.add_argument("--suite", type=str, default=None,
                   help="Run specific suite number prefix (e.g. 09)")
    p.add_argument("--fast", action="store_true",
                   help="Skip stress (06_*), load (07_*), latency (08_*)")
    p.add_argument("--no-browser", action="store_true",
                   help="Skip UI suites (02_ui, 13_dashboard)")
    p.add_argument("--integrations", action="store_true",
                   help="Include integration suites (11_integrations, 12_mcp)")
    p.add_argument("--security", action="store_true",
                   help="Include security + rate-limiting suites (09, 10)")
    p.add_argument("--superadmin", action="store_true",
                   help="Include superadmin suite (14_superadmin)")
    p.add_argument("--cross-browser", action="store_true",
                   help="Include cross-browser suite (15_cross_browser — needs all engines)")
    p.add_argument("--all", action="store_true",
                   help="Run everything")
    p.add_argument("--no-report", action="store_true",
                   help="Skip writing summary artifact")
    p.add_argument("--clean", action="store_true",
                   help="Run cleanup before starting")
    return p.parse_args()


def build_category_filter(args):
    """Determine which categories to run based on flags."""
    if args.suite:
        # --suite prefix matches categories starting with that prefix
        return None  # Handled separately

    if args.all:
        return None  # All categories

    # Build from flags
    cats = set(CAT_DEFAULT)

    if not args.fast:
        pass  # Default doesn't include heavy; fast = default minus nothing extra

    # --fast: run default but label it; heavy still excluded by default
    # Actually --fast means same as default (heavy tests excluded by default)

    if args.security:
        cats.update(CAT_SECURITY_RL)

    if args.integrations:
        cats.update(CAT_INTEGRATIONS)

    if args.superadmin:
        cats.update(CAT_SUPERADMIN)

    if getattr(args, 'cross_browser', False):
        cats.update(CAT_CROSS_BROWSER)

    if not args.no_browser:
        cats.update(CAT_DASHBOARD)  # 13_dashboard included unless --no-browser

    if args.no_browser:
        cats -= CAT_BROWSER

    # Heavy suites only if explicitly requested via --all
    # (neither --fast nor default includes them)

    if args.category:
        # Filter to only the specified category
        return {args.category}

    return cats


def write_summary(suite_results, elapsed_ms, run_label, output_dir):
    """Write JSON summary of suite run."""
    output_dir.mkdir(parents=True, exist_ok=True)
    passed  = sum(1 for r in suite_results if r.get("passed") is True)
    failed  = sum(1 for r in suite_results if r.get("passed") is False)
    skipped = sum(1 for r in suite_results if r.get("passed") is None)

    summary = {
        "run":         run_label,
        "passed":      passed,
        "failed":      failed,
        "skipped":     skipped,
        "total":       len(suite_results),
        "duration_ms": elapsed_ms,
        "suites":      suite_results,
    }
    path = output_dir / "suite_summary.json"
    path.write_text(json.dumps(summary, indent=2))
    return path


def main():
    args = parse_args()
    start_time = time.monotonic()
    run_label  = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Optional cleanup
    if args.clean:
        try:
            from infra.cleanup import run as cleanup_run
            cleanup_run()
        except Exception as e:
            print(f"  {W}  Cleanup error (non-fatal): {e}")

    print(f"\n{'═'*66}")
    print(f"  {BOLD}VantageAI Test Suite Runner{RESET}")
    print(f"  Run:   {run_label}")
    print(f"  Site:  {SITE_URL}")
    print(f"  API:   {API_URL}")
    print(f"{'═'*66}\n")

    # ── Determine categories to run ──────────────────────────────────────────
    category_filter = build_category_filter(args)

    if args.fast:
        print(f"  {W}  --fast: skipping stress/load/latency suites\n")
        if category_filter:
            category_filter -= CAT_HEAVY
        # else --all overrides, include everything

    if args.no_browser:
        print(f"  {W}  --no-browser: skipping UI/Playwright suites\n")

    # ── Discover suites ───────────────────────────────────────────────────────
    all_suites = discover_suites(filter_categories=category_filter)

    if args.suite:
        # Filter by suite number prefix
        prefix = args.suite.zfill(2)
        all_suites = [(cat, fp) for cat, fp in all_suites
                      if cat.startswith(prefix)]
        if not all_suites:
            print(f"  {R}  No suites found matching prefix '{args.suite}'")
            print(f"      Available categories in {SUITES_DIR}:")
            for cat_dir in sorted(SUITES_DIR.iterdir()):
                if cat_dir.is_dir():
                    print(f"        {cat_dir.name}")
            sys.exit(1)

    if not all_suites:
        print(f"  {W}  No test files discovered under {SUITES_DIR}")
        print(f"      Flags: all={args.all}, fast={args.fast}, "
              f"security={args.security}, integrations={args.integrations}")
        sys.exit(0)

    print(f"  {B}  Discovered {len(all_suites)} test file(s):\n")
    for cat, fp in all_suites:
        print(f"      {cat}/{fp.name}")
    print()

    # ── Set up artifact directory ─────────────────────────────────────────────
    run_dir = ARTIFACTS_DIR / run_label.replace(":", "-")
    run_dir.mkdir(parents=True, exist_ok=True)

    # PYTHONPATH must include tests/ directory so imports work
    pythonpath = str(TESTS_ROOT)
    if "PYTHONPATH" in os.environ:
        pythonpath = f"{os.environ['PYTHONPATH']}{os.pathsep}{pythonpath}"

    # ── Run suites ────────────────────────────────────────────────────────────
    suite_results = []
    current_cat   = None

    for cat, filepath in all_suites:
        # Print category header on category change
        if cat != current_cat:
            current_cat = cat
            print(f"\n{'━'*66}")
            print(f"  Category: {cat}")
            print(f"{'━'*66}")

        print(f"\n  Running: {filepath.name}")
        log.info("Starting suite file", category=cat, file=filepath.name)

        if not filepath.exists():
            print(f"  {W}  {filepath.name} not found — skipping")
            suite_results.append({
                "category":    cat,
                "file":        str(filepath.relative_to(TESTS_ROOT)),
                "passed":      None,
                "duration_ms": 0,
            })
            continue

        result = run_suite_file(filepath, pythonpath)
        result["category"] = cat
        suite_results.append(result)

        icon   = G if result["passed"] else R
        status = "PASSED" if result["passed"] else "FAILED"
        print(f"\n  {icon}  {filepath.name} {status} in {result['duration_ms']}ms")
        log.info("Suite file completed",
                 category=cat, file=filepath.name,
                 status=status, duration_ms=result["duration_ms"])

    # ── Final summary ──────────────────────────────────────────────────────────
    elapsed = round((time.monotonic() - start_time) * 1000)
    passed  = sum(1 for r in suite_results if r.get("passed") is True)
    failed  = sum(1 for r in suite_results if r.get("passed") is False)
    skipped = sum(1 for r in suite_results if r.get("passed") is None)

    print(f"\n{'═'*66}")
    print(f"  {BOLD}Final Results — {run_label}{RESET}")
    print(f"{'═'*66}")

    for r in suite_results:
        if r.get("passed") is True:
            icon = G
        elif r.get("passed") is False:
            icon = R
        else:
            icon = W
        dur  = f"{r['duration_ms']}ms" if r.get("duration_ms") else "skipped"
        rel  = Path(r.get("file", "?")).name
        cat  = r.get("category", "?")
        print(f"  {icon}  {cat}/{rel:<48} {dur}")

    overall = G if failed == 0 else R
    print(f"{'─'*66}")
    print(f"  {overall}  {BOLD}{passed} passed  {failed} failed  "
          f"{skipped} skipped  ({len(suite_results)} files, {elapsed}ms){RESET}")
    print(f"{'═'*66}\n")

    # ── Reports ────────────────────────────────────────────────────────────────
    if not args.no_report:
        try:
            summary_path = write_summary(suite_results, elapsed, run_label, run_dir)
            print(f"  {B}  Suite summary: {summary_path}")

            # Also write to legacy location for backward compat
            legacy_dir = TESTS_ROOT / "test-results"
            legacy_dir.mkdir(exist_ok=True)
            legacy_path = write_summary(suite_results, elapsed, run_label, legacy_dir)
            print(f"  {B}  Legacy summary: {legacy_path}")
        except Exception as e:
            print(f"  {W}  Could not write report: {e}")

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
