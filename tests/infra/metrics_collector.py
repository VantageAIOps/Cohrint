"""
metrics_collector.py — Real-time metrics collection for VantageAI test suite
=============================================================================
Purpose:
  Collects and aggregates performance metrics across test runs:
    • Request latency percentiles (p50, p95, p99)
    • Error rates per endpoint
    • Throughput (requests/second)
    • Data consistency checks
    • Cross-run comparison (trending)

Usage:
  from infra.metrics_collector import MetricsCollector

  mc = MetricsCollector("test_sla")
  mc.record_request("POST /v1/events", 245, ok=True, status=201)
  mc.record_request("GET /v1/analytics/summary", 380, ok=True, status=200)
  mc.finish()   # prints summary table + writes to metrics.jsonl

Data written to:
  artifacts/{run}/metrics.jsonl  — one JSON line per test run
"""

import sys
import os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import json
import time
import statistics
import threading
from datetime import datetime, timezone
from typing import Optional, Dict, List

try:
    from config.settings import ARTIFACTS_DIR
    OUTPUT_DIR = ARTIFACTS_DIR
except Exception:
    OUTPUT_DIR = Path(os.environ.get("VANTAGE_TEST_ARTIFACTS_DIR",
                                     str(Path(__file__).parent.parent / "artifacts")))


class EndpointStats:
    def __init__(self, name: str):
        self.name       = name
        self.latencies: List[float] = []
        self.statuses:  List[int]   = []
        self.errors:    List[str]   = []
        self.lock       = threading.Lock()

    def record(self, ms: float, status: int, error: Optional[str] = None):
        with self.lock:
            self.latencies.append(ms)
            self.statuses.append(status)
            if error:
                self.errors.append(error)

    def summary(self) -> dict:
        with self.lock:
            if not self.latencies:
                return {"name": self.name, "count": 0}
            sorted_lats = sorted(self.latencies)
            n           = len(sorted_lats)
            total       = len(self.statuses)
            errors      = sum(1 for s in self.statuses if s >= 400)
            return {
                "name":        self.name,
                "count":       n,
                "p50_ms":      round(sorted_lats[n // 2]),
                "p95_ms":      round(sorted_lats[int(0.95 * n)]),
                "p99_ms":      round(sorted_lats[int(0.99 * n)]),
                "avg_ms":      round(statistics.mean(self.latencies)),
                "min_ms":      round(min(self.latencies)),
                "max_ms":      round(max(self.latencies)),
                "error_count": errors,
                "error_rate":  round(errors / max(total, 1) * 100, 1),
                "status_codes": dict(
                    sorted(
                        {str(s): self.statuses.count(s) for s in set(self.statuses)}.items()
                    )
                ),
            }


class MetricsCollector:
    def __init__(self, suite_name: str):
        self.suite_name   = suite_name
        self.started_at   = time.monotonic()
        self.ts           = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        self.endpoints: Dict[str, EndpointStats] = {}
        self._lock        = threading.Lock()

    def _get_endpoint(self, name: str) -> EndpointStats:
        with self._lock:
            if name not in self.endpoints:
                self.endpoints[name] = EndpointStats(name)
            return self.endpoints[name]

    def record_request(self, endpoint: str, duration_ms: float,
                       ok: bool = True, status: int = 200,
                       error: Optional[str] = None):
        """
        Record a single HTTP request.

        Args:
            endpoint:    e.g. "POST /v1/events" or "GET /v1/analytics/summary"
            duration_ms: round-trip time in milliseconds
            ok:          True if request succeeded (2xx)
            status:      HTTP status code
            error:       Optional error message if request failed
        """
        ep = self._get_endpoint(endpoint)
        ep.record(duration_ms, status, error if not ok else None)

    def all_latencies(self) -> List[float]:
        all_lats = []
        for ep in self.endpoints.values():
            all_lats.extend(ep.latencies)
        return all_lats

    def global_summary(self) -> dict:
        lats = self.all_latencies()
        if not lats:
            return {"count": 0}
        sorted_lats = sorted(lats)
        n = len(sorted_lats)
        total_errors = sum(
            ep.summary().get("error_count", 0)
            for ep in self.endpoints.values()
        )
        return {
            "count":       n,
            "p50_ms":      round(sorted_lats[n // 2]),
            "p95_ms":      round(sorted_lats[int(0.95 * n)]),
            "p99_ms":      round(sorted_lats[int(0.99 * n)]),
            "avg_ms":      round(statistics.mean(lats)),
            "total_errors": total_errors,
            "error_rate":  round(total_errors / max(n, 1) * 100, 1),
        }

    def print_table(self):
        """Print a formatted metrics table to stdout."""
        BOLD  = "\033[1m"
        RESET = "\033[0m"
        G     = "\033[32m"
        R     = "\033[31m"
        Y     = "\033[33m"

        elapsed = round((time.monotonic() - self.started_at) * 1000)
        gs = self.global_summary()

        print(f"\n  {'─'*70}")
        print(f"  {BOLD}Metrics: {self.suite_name}{RESET}  [{elapsed}ms total]")
        print(f"  {'─'*70}")
        print(f"  {'Endpoint':<40} {'n':>5} {'p50':>6} {'p95':>6} {'err%':>6}")
        print(f"  {'─'*70}")

        for ep in sorted(self.endpoints.values(), key=lambda x: x.name):
            s = ep.summary()
            if s["count"] == 0:
                continue
            err_col = f"{R}{s['error_rate']:5.1f}%{RESET}" if s["error_rate"] > 0 else f"{G}  0.0%{RESET}"
            p50_col = f"{Y}{s['p50_ms']:5d}ms{RESET}" if s["p50_ms"] > 1000 else f"{s['p50_ms']:5d}ms"
            print(f"  {s['name']:<40} {s['count']:>5} {p50_col} {s['p95_ms']:5d}ms {err_col}")

        print(f"  {'─'*70}")
        err_col_g = f"{R}{gs['error_rate']:5.1f}%{RESET}" if gs.get("error_rate", 0) > 0 else "  0.0%"
        print(f"  {BOLD}{'TOTAL':<40} {gs.get('count',0):>5} {gs.get('p50_ms',0):5d}ms "
              f"{gs.get('p95_ms',0):5d}ms {err_col_g}{RESET}")
        print(f"  {'─'*70}\n")

    def write_jsonl(self, path: Optional[Path] = None):
        """Append this run's metrics to metrics.jsonl."""
        out_path = path or (OUTPUT_DIR / "metrics.jsonl")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "ts":        self.ts,
            "suite":     self.suite_name,
            "summary":   self.global_summary(),
            "endpoints": [ep.summary() for ep in self.endpoints.values()],
        }
        with open(out_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
        return out_path

    def finish(self) -> dict:
        """Print table + write JSONL. Returns global summary dict."""
        self.print_table()
        self.write_jsonl()
        return self.global_summary()


# ── Convenience decorator ─────────────────────────────────────────────────
def track_request(collector: MetricsCollector, endpoint: str):
    """
    Decorator that records HTTP request metrics automatically.

    Usage:
        mc = MetricsCollector("test_sla")

        @track_request(mc, "GET /v1/analytics/summary")
        def fetch_summary(key):
            return requests.get(f"{API_URL}/v1/analytics/summary",
                                headers=get_headers(key))

        r = fetch_summary(my_key)
    """
    def decorator(fn):
        def wrapper(*args, **kwargs):
            t0 = time.monotonic()
            result = None
            try:
                result = fn(*args, **kwargs)
                ms = round((time.monotonic() - t0) * 1000)
                if hasattr(result, "status_code"):
                    collector.record_request(endpoint, ms,
                                             ok=result.ok,
                                             status=result.status_code)
                else:
                    collector.record_request(endpoint, ms, ok=True, status=200)
            except Exception as e:
                ms = round((time.monotonic() - t0) * 1000)
                collector.record_request(endpoint, ms, ok=False, status=0,
                                         error=str(e))
                raise
            return result
        return wrapper
    return decorator
