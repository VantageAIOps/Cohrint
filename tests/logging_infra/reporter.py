"""
reporter.py — Test run reporter for VantageAI test suite
=========================================================
Collects test results across all test modules and writes:
  1. A colour-coded summary to stdout
  2. A machine-readable JSON report  → test-results/report.json
  3. A human-readable HTML report    → test-results/report.html

Usage (called by run_suite.py after all tests finish):
  from logging_infra.reporter import TestReporter

  r = TestReporter()
  r.record("test_01_signup", "Signup with valid email", passed=True, duration_ms=320)
  r.record("test_02_signin", "Sign-in with wrong key",  passed=False,
           detail="Expected 401, got 200")
  r.finish()       # prints summary + writes files

Individual test files can also feed results:
  r.record(suite, label, passed, detail="", duration_ms=None)
"""

import json
import time
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

OUTPUT_DIR = Path(__file__).parent.parent / "test-results"

# ── ANSI ─────────────────────────────────────────────────────────────────────
G = "\033[32m✓\033[0m"
R = "\033[31m✗\033[0m"
W = "\033[33m⚠\033[0m"
B = "\033[34mℹ\033[0m"
BOLD  = "\033[1m"
RESET = "\033[0m"


class TestReporter:
    def __init__(self, run_label: Optional[str] = None):
        self.run_label  = run_label or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.started_at = time.monotonic()
        self.entries    = []   # list of dicts

    def record(self, suite: str, label: str, passed: bool,
               detail: str = "", duration_ms: Optional[int] = None,
               skipped: bool = False):
        self.entries.append({
            "suite":       suite,
            "label":       label,
            "passed":      passed,
            "skipped":     skipped,
            "detail":      detail,
            "duration_ms": duration_ms,
        })

    # ── Aggregation ──────────────────────────────────────────────────────────
    @property
    def passed(self):  return sum(1 for e in self.entries if e["passed"] and not e["skipped"])
    @property
    def failed(self):  return sum(1 for e in self.entries if not e["passed"] and not e["skipped"])
    @property
    def skipped(self): return sum(1 for e in self.entries if e["skipped"])
    @property
    def total(self):   return len(self.entries)

    def suites(self):
        seen = {}
        for e in self.entries:
            seen.setdefault(e["suite"], {"passed": 0, "failed": 0, "skipped": 0})
            if e["skipped"]:   seen[e["suite"]]["skipped"] += 1
            elif e["passed"]:  seen[e["suite"]]["passed"]  += 1
            else:              seen[e["suite"]]["failed"]  += 1
        return seen

    # ── Console summary ──────────────────────────────────────────────────────
    def print_summary(self):
        elapsed = round((time.monotonic() - self.started_at) * 1000)
        print(f"\n{'═'*66}")
        print(f"  {BOLD}Test Run: {self.run_label}{RESET}")
        print(f"{'═'*66}")

        for suite, counts in self.suites().items():
            icon = G if counts["failed"] == 0 else R
            print(f"  {icon}  {suite:40s}  "
                  f"{counts['passed']} passed  "
                  f"{counts['failed']} failed  "
                  f"{counts['skipped']} skipped")

        print(f"{'─'*66}")
        status_icon = G if self.failed == 0 else R
        print(f"  {status_icon}  {BOLD}TOTAL: {self.passed} passed  "
              f"{self.failed} failed  {self.skipped} skipped  "
              f"({self.total} tests, {elapsed}ms){RESET}")
        print(f"{'═'*66}\n")

        if self.failed:
            print(f"  {R}  Failed tests:")
            for e in self.entries:
                if not e["passed"] and not e["skipped"]:
                    print(f"      • [{e['suite']}] {e['label']}")
                    if e["detail"]:
                        print(f"        └─ {e['detail']}")
            print()

    # ── JSON report ──────────────────────────────────────────────────────────
    def write_json(self):
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        out = {
            "run":      self.run_label,
            "passed":   self.passed,
            "failed":   self.failed,
            "skipped":  self.skipped,
            "total":    self.total,
            "suites":   self.suites(),
            "entries":  self.entries,
        }
        path = OUTPUT_DIR / "report.json"
        path.write_text(json.dumps(out, indent=2))
        return path

    # ── HTML report ──────────────────────────────────────────────────────────
    def write_html(self):
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        rows = ""
        for e in self.entries:
            if e["skipped"]:
                status, cls = "SKIP", "skip"
            elif e["passed"]:
                status, cls = "PASS", "pass"
            else:
                status, cls = "FAIL", "fail"
            dur = f"{e['duration_ms']}ms" if e["duration_ms"] else "—"
            detail = f"<br><small style='color:#888'>{e['detail']}</small>" if e["detail"] else ""
            rows += (f"<tr class='{cls}'>"
                     f"<td>{e['suite']}</td>"
                     f"<td>{e['label']}{detail}</td>"
                     f"<td class='status'>{status}</td>"
                     f"<td>{dur}</td>"
                     f"</tr>\n")

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>VantageAI Test Report — {self.run_label}</title>
<style>
  body {{ font-family: -apple-system, monospace; background: #0d1318; color: #e8edf2; margin: 0; padding: 20px }}
  h1 {{ color: #00d4a1; font-size: 18px; margin-bottom: 4px }}
  .stats {{ color: #6b7b8a; font-size: 13px; margin-bottom: 20px }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px }}
  th {{ background: #121920; color: #6b7b8a; padding: 8px 12px; text-align: left; border-bottom: 1px solid rgba(255,255,255,.07) }}
  td {{ padding: 7px 12px; border-bottom: 1px solid rgba(255,255,255,.04) }}
  tr.pass {{ background: rgba(0,212,161,.04) }}
  tr.fail {{ background: rgba(248,113,113,.06) }}
  tr.skip {{ background: rgba(245,158,11,.04) }}
  .status {{ font-family: monospace; font-size: 11px; font-weight: 600 }}
  tr.pass .status {{ color: #00d4a1 }}
  tr.fail .status {{ color: #f87171 }}
  tr.skip .status {{ color: #f59e0b }}
  small {{ opacity: .7 }}
</style>
</head>
<body>
<h1>VantageAI Test Report</h1>
<div class="stats">
  Run: {self.run_label} &nbsp;|&nbsp;
  <span style="color:#00d4a1">{self.passed} passed</span> &nbsp;
  <span style="color:#f87171">{self.failed} failed</span> &nbsp;
  <span style="color:#f59e0b">{self.skipped} skipped</span> &nbsp;
  ({self.total} total)
</div>
<table>
<thead><tr><th>Suite</th><th>Test</th><th>Status</th><th>Duration</th></tr></thead>
<tbody>
{rows}
</tbody>
</table>
</body>
</html>"""
        path = OUTPUT_DIR / "report.html"
        path.write_text(html)
        return path

    def finish(self):
        self.print_summary()
        json_path = self.write_json()
        html_path = self.write_html()
        print(f"  {B}  Reports written:")
        print(f"       JSON: {json_path}")
        print(f"       HTML: {html_path}\n")
        return self.failed == 0
