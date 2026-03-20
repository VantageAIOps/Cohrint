"""
run_suite.py — Master test runner for VantageAI test suite
===========================================================
Developer notes:
  Runs all test modules in order and produces:
    • Colour-coded console output with per-suite pass/fail counts
    • JSON report  → tests/test-results/report.json
    • HTML report  → tests/test-results/report.html

  Test execution order (original suite 01-10):
    01 Signup          — auth/signup API + UI
    02 Signin          — auth/session API + UI
    03 Recovery        — key recovery flow
    04 Dashboard       — /app.html stability + all views
    05 API Coverage    — every endpoint (28 total)
    06 Members/Admin   — team management + admin
    07 Settings        — settings modal + homepage stability
    08 Onboarding      — new user full journey
    09 Concurrent      — load tests (takes ~60-90s)
    10 Stress          — production stress (takes ~2-3min)

  Extended suite (11-20) — targeting reported bugs:
    11 Navigation      — nav stability, ← home bug, sidebar links
    12 Data Loading    — KPI cards, charts, tables after ingest
    13 Auth Stability  — sign in → dashboard no blank page
    14 Settings/Profile— settings modal, API key hint, admin API
    15 Prod Endpoints  — all 28 endpoints with schema checks
    16 Multi-Client    — concurrent browsers, cross-org isolation
    17 Homepage        — landing page stability, SEO, mobile
    18 SSE Streaming   — live stream, reconnect, SSE delivery
    19 New User        — full onboarding E2E (landing → first event)
    20 Stress/Load     — 500-event bursts, 50 concurrent signups

  Flags:
    --fast          skip tests 09, 10, 20 (load/stress)
    --ui-only       only run UI/Playwright tests
    --api-only      skip Playwright tests
    --suite N       run only test_NN_*.py (e.g. --suite 12)
    --extended      run suites 11-20 (bug-targeted tests)
    --all           run all suites 01-20
    --no-report     skip writing HTML/JSON reports

Usage:
  cd /path/to/vantageai
  python tests/run_suite.py               # run suites 01-10
  python tests/run_suite.py --extended    # run suites 11-20 (bug fixes)
  python tests/run_suite.py --all         # run all 20 suites
  python tests/run_suite.py --suite 12    # run only test_12_data_loading.py
  python tests/run_suite.py --fast        # skip stress tests
  HEADLESS=0 python tests/run_suite.py --suite 13

Requirements:
  pip install requests playwright
  python -m playwright install chromium
"""

import os
import sys
import time
import subprocess
import argparse
from pathlib import Path

# ── Setup ─────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from logging_infra.structured_logger import get_logger
log = get_logger("suite.runner")

BOLD  = "\033[1m"
RESET = "\033[0m"
G     = "\033[32m✓\033[0m"
R     = "\033[31m✗\033[0m"
W     = "\033[33m⚠\033[0m"
B     = "\033[34mℹ\033[0m"

SUITE_FILES_ORIGINAL = [
    ("01", "test_01_signup.py",             "Signup (API + UI)"),
    ("02", "test_02_signin.py",             "Sign-in (API + UI)"),
    ("03", "test_03_recovery.py",           "Key Recovery"),
    ("04", "test_04_dashboard.py",          "Dashboard Stability"),
    ("05", "test_05_api_coverage.py",       "API Endpoint Coverage"),
    ("06", "test_06_members_admin.py",      "Members & Admin"),
    ("07", "test_07_settings_profile.py",   "Settings & Profile"),
    ("08", "test_08_new_user_onboarding.py","New User Onboarding"),
    ("09", "test_09_concurrent_load.py",    "Concurrent Load Tests"),
    ("10", "test_10_stress_production.py",  "Stress & Production"),
]

SUITE_FILES_EXTENDED = [
    ("11", "test_11_navigation.py",          "Navigation Stability (← home bug)"),
    ("12", "test_12_data_loading.py",        "Data Loading (KPI/chart/table)"),
    ("13", "test_13_ui_auth_stability.py",   "UI Auth Stability (blank page bug)"),
    ("14", "test_14_settings_profile.py",    "Settings & Profile (key hint, budget)"),
    ("15", "test_15_production_endpoints.py","Production Endpoints (all 28)"),
    ("16", "test_16_multi_client_concurrent.py","Multi-Client Concurrent"),
    ("17", "test_17_homepage_stability.py",  "Homepage Stability (SEO, mobile)"),
    ("18", "test_18_sse_streaming.py",       "SSE Live Stream"),
    ("19", "test_19_new_user_onboarding.py", "New User Onboarding E2E"),
    ("20", "test_20_stress_load.py",         "Stress & Load (burst, concurrent)"),
]

SUITE_FILES = SUITE_FILES_ORIGINAL + SUITE_FILES_EXTENDED

# Fast-skip suites (load/stress intensive)
SKIP_IN_FAST = {"09", "10", "20"}


def parse_args():
    p = argparse.ArgumentParser(description="VantageAI test suite runner")
    p.add_argument("--fast",      action="store_true",
                   help="Skip load & stress tests (09, 10, 20)")
    p.add_argument("--suite",     type=str, default=None,
                   help="Run only suite N (e.g. 12 or 4)")
    p.add_argument("--extended",  action="store_true",
                   help="Run extended suites 11-20 (bug-targeted tests)")
    p.add_argument("--all",       action="store_true",
                   help="Run all suites 01-20")
    p.add_argument("--no-report", action="store_true",
                   help="Skip HTML/JSON report generation")
    return p.parse_args()


def run_suite_file(filename: str) -> dict:
    """Run a single test file as a subprocess and capture its output."""
    path = ROOT / filename
    env  = {**os.environ, "PYTHONPATH": str(ROOT.parent)}
    t0   = time.monotonic()
    proc = subprocess.run(
        [sys.executable, str(path)],
        env=env,
        capture_output=False,   # let output stream directly to terminal
        text=True,
    )
    ms   = round((time.monotonic() - t0) * 1000)
    return {
        "file":      filename,
        "returncode": proc.returncode,
        "duration_ms": ms,
        "passed":     proc.returncode == 0,
    }


def main():
    args = parse_args()
    start_time = time.monotonic()

    print(f"\n{'═'*66}")
    print(f"  {BOLD}VantageAI Test Suite{RESET}")
    print(f"  Site:  https://vantageaiops.com")
    print(f"  API:   https://api.vantageaiops.com")
    print(f"{'═'*66}\n")

    # Filter suites
    if args.all:
        suites = SUITE_FILES
    elif args.extended:
        suites = SUITE_FILES_EXTENDED
    else:
        suites = SUITE_FILES_ORIGINAL

    if args.fast:
        suites = [(n, f, l) for n, f, l in suites if n not in SKIP_IN_FAST]
        print(f"  {W}  --fast: skipping load/stress suites {SKIP_IN_FAST}\n")

    if args.suite:
        target = args.suite.zfill(2)
        suites = [(n, f, l) for n, f, l in SUITE_FILES if n == target]
        if not suites:
            available = [n for n, _, _ in SUITE_FILES]
            print(f"  {R}  Suite '{args.suite}' not found. Available: {', '.join(available)}")
            sys.exit(1)

    suite_results = []
    for num, filename, label in suites:
        print(f"\n{'━'*66}")
        print(f"  Suite {num}: {label}")
        print(f"{'━'*66}")
        log.info("Starting suite", suite=num, label=label)

        path = ROOT / filename
        if not path.exists():
            print(f"  {W}  {filename} not found — skipping")
            suite_results.append({"num": num, "label": label, "passed": None, "duration_ms": 0})
            continue

        result = run_suite_file(filename)
        result["num"] = num
        result["label"] = label
        suite_results.append(result)

        icon = G if result["passed"] else R
        status = "PASSED" if result["passed"] else "FAILED"
        print(f"\n  {icon}  Suite {num} {status} in {result['duration_ms']}ms")
        log.info("Suite completed", suite=num, status=status, duration_ms=result["duration_ms"])

    # ── Final summary ─────────────────────────────────────────────────────────
    elapsed = round((time.monotonic() - start_time) * 1000)
    passed  = sum(1 for r in suite_results if r.get("passed") is True)
    failed  = sum(1 for r in suite_results if r.get("passed") is False)
    skipped = sum(1 for r in suite_results if r.get("passed") is None)

    print(f"\n{'═'*66}")
    print(f"  {BOLD}Final Results{RESET}")
    print(f"{'═'*66}")
    for r in suite_results:
        if r.get("passed") is True:
            icon = G
        elif r.get("passed") is False:
            icon = R
        else:
            icon = W
        dur = f"{r['duration_ms']}ms" if r.get("duration_ms") else "skipped"
        print(f"  {icon}  Suite {r['num']}: {r['label']:<38} {dur}")

    overall = G if failed == 0 else R
    print(f"{'─'*66}")
    print(f"  {overall}  {BOLD}{passed} suites passed  {failed} failed  "
          f"{skipped} skipped  ({elapsed}ms total){RESET}")
    print(f"{'═'*66}\n")

    # ── Reports ───────────────────────────────────────────────────────────────
    if not args.no_report:
        try:
            import json
            from pathlib import Path as P
            out_dir = ROOT / "test-results"
            out_dir.mkdir(exist_ok=True)
            summary = {
                "run":      time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "passed":   passed,
                "failed":   failed,
                "skipped":  skipped,
                "total":    len(suite_results),
                "duration_ms": elapsed,
                "suites":   suite_results,
            }
            json_path = out_dir / "suite_summary.json"
            json_path.write_text(json.dumps(summary, indent=2))
            print(f"  {B}  Suite summary: {json_path}")
        except Exception as e:
            print(f"  {W}  Could not write report: {e}")

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
