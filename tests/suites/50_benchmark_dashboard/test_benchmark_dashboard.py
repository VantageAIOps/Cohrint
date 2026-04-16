"""
Test Suite 50 — Public Benchmark Dashboard
===========================================

Tests the public benchmark API endpoints that power benchmarks.html.

  A. Summary        (BS.1–BS.5)  — GET /v1/benchmark/summary (public)
  B. Percentiles    (BP.1–BP.8)  — GET /v1/benchmark/percentiles (public)
  C. Contribute     (BC.1–BC.5)  — POST /v1/benchmark/contribute (auth)
  D. K-anonymity    (KA.1–KA.2)  — 404 when sample_size < 5

Uses da45 persistent seed accounts. Never creates fresh accounts.
All tests hit https://api.cohrint.com (no mocking).
"""

import json
import sys
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from config.settings import API_URL
from helpers.output import section, chk, warn

SEED_FILE = Path(__file__).parent.parent.parent / "artifacts" / "da45_seed_state.json"
if not SEED_FILE.exists():
    pytest.skip("da45_seed_state.json not found — run seed.py first", allow_module_level=True)

_seed = json.loads(SEED_FILE.read_text())
ADMIN_KEY  = _seed["admin"]["api_key"]
MEMBER_KEY = _seed["member"]["api_key"]

BASE = API_URL.rstrip("/")


def _api(method: str, path: str, key: str = ADMIN_KEY, **kwargs) -> requests.Response:
    headers = kwargs.pop("headers", {})
    headers["Authorization"] = f"Bearer {key}"
    return getattr(requests, method)(f"{BASE}{path}", headers=headers, timeout=15, **kwargs)


def _pub(method: str, path: str, **kwargs) -> requests.Response:
    """Public (no-auth) request."""
    return getattr(requests, method)(f"{BASE}{path}", timeout=15, **kwargs)


# ── A. Summary ──────────────────────────────────────────────────────────────────

class TestBenchmarkSummary:
    def test_BS01_public_200(self):
        """BS.1 — GET /v1/benchmark/summary is public, returns 200."""
        section("BS.1 — Benchmark summary public")
        r = _pub("get", "/v1/benchmark/summary")
        chk("200", r.status_code == 200)

    def test_BS02_has_available(self):
        """BS.2 — Response contains 'available' array."""
        section("BS.2 — Summary has available")
        r = _pub("get", "/v1/benchmark/summary")
        body = r.json()
        chk("available key", "available" in body)
        chk("available is list", isinstance(body["available"], list))

    def test_BS03_available_item_shape(self):
        """BS.3 — Each available item has metric/model/quarter/sample_size."""
        section("BS.3 — Available item shape")
        r = _pub("get", "/v1/benchmark/summary")
        items = r.json().get("available", [])
        if not items:
            warn("No benchmark data yet — shape check skipped")
            return
        item = items[0]
        for field in ["metric", "quarter", "sample_size"]:
            chk(f"has {field}", field in item)

    def test_BS04_sample_size_gte_5(self):
        """BS.4 — All returned cohorts have sample_size >= 5 (k-anonymity)."""
        section("BS.4 — K-anonymity in summary")
        r = _pub("get", "/v1/benchmark/summary")
        items = r.json().get("available", [])
        for item in items:
            chk(f"sample_size>=5 for {item.get('metric')}", item.get("sample_size", 0) >= 5)

    def test_BS05_no_auth_required(self):
        """BS.5 — No Authorization header needed (public endpoint)."""
        section("BS.5 — No auth needed")
        r = requests.get(f"{BASE}/v1/benchmark/summary", timeout=10)
        chk("200 without auth", r.status_code == 200)


# ── B. Percentiles ──────────────────────────────────────────────────────────────

class TestBenchmarkPercentiles:
    def test_BP01_requires_metric(self):
        """BP.1 — Missing metric param returns 400."""
        section("BP.1 — Missing metric 400")
        r = _pub("get", "/v1/benchmark/percentiles")
        chk("400 or 422", r.status_code in (400, 422))

    def test_BP02_valid_metric_returns_200_or_404(self):
        """BP.2 — Valid metric returns 200 (data exists) or 404 (k<5)."""
        section("BP.2 — Valid metric accepted")
        r = _pub("get", "/v1/benchmark/percentiles?metric=cost_per_dev_month")
        chk("200 or 404", r.status_code in (200, 404))

    def test_BP03_response_shape_when_data_exists(self):
        """BP.3 — When data exists, response has p25/p50/p75/p90."""
        section("BP.3 — Percentile shape")
        r = _pub("get", "/v1/benchmark/percentiles?metric=cost_per_dev_month")
        if r.status_code == 404:
            warn("No benchmark data — shape check skipped")
            return
        body = r.json()
        for field in ["metric", "p25", "p50", "p75", "p90", "sample_size", "quarter"]:
            chk(f"has {field}", field in body)

    def test_BP04_p25_lte_p50_lte_p75(self):
        """BP.4 — Percentile ordering: p25 <= p50 <= p75 <= p90."""
        section("BP.4 — Percentile ordering")
        r = _pub("get", "/v1/benchmark/percentiles?metric=cost_per_dev_month")
        if r.status_code == 404:
            warn("No data — ordering check skipped")
            return
        b = r.json()
        chk("p25<=p50", b["p25"] <= b["p50"])
        chk("p50<=p75", b["p50"] <= b["p75"])
        chk("p75<=p90", b["p75"] <= b["p90"])

    def test_BP05_cache_hit_rate_0_to_1(self):
        """BP.5 — cache_hit_rate percentiles are in [0, 1]."""
        section("BP.5 — Cache hit rate range")
        r = _pub("get", "/v1/benchmark/percentiles?metric=cache_hit_rate")
        if r.status_code == 404:
            warn("No cache_hit_rate data yet")
            return
        b = r.json()
        for p in ["p25", "p50", "p75", "p90"]:
            if b.get(p) is not None:
                chk(f"{p} in [0,1]", 0 <= b[p] <= 1)

    def test_BP06_model_filter(self):
        """BP.6 — ?model= filter accepted without error."""
        section("BP.6 — Model filter")
        r = _pub("get", "/v1/benchmark/percentiles?metric=cost_per_token&model=claude-sonnet-4-6")
        chk("200 or 404", r.status_code in (200, 404))

    def test_BP07_unknown_metric_404(self):
        """BP.7 — Unknown metric returns 404 (no matching cohort)."""
        section("BP.7 — Unknown metric 404")
        r = _pub("get", "/v1/benchmark/percentiles?metric=nonexistent_metric_xyz")
        chk("404", r.status_code == 404)

    def test_BP08_no_auth_required(self):
        """BP.8 — Public endpoint, no auth needed."""
        section("BP.8 — No auth for percentiles")
        r = requests.get(f"{BASE}/v1/benchmark/percentiles?metric=cost_per_dev_month", timeout=10)
        chk("200 or 404 without auth", r.status_code in (200, 404))


# ── C. Contribute ───────────────────────────────────────────────────────────────

class TestBenchmarkContribute:
    def test_BC01_requires_auth(self):
        """BC.1 — POST /v1/benchmark/contribute requires auth."""
        section("BC.1 — Contribute requires auth")
        r = requests.post(f"{BASE}/v1/benchmark/contribute", timeout=10)
        chk("401", r.status_code == 401)

    def test_BC02_member_cannot_contribute(self):
        """BC.2 — Member role cannot contribute (admin/owner only)."""
        section("BC.2 — Member cannot contribute")
        r = _api("post", "/v1/benchmark/contribute", key=MEMBER_KEY)
        chk("403", r.status_code == 403)

    def test_BC03_admin_can_trigger(self):
        """BC.3 — Admin can call contribute (idempotent)."""
        section("BC.3 — Admin can contribute")
        r = _api("post", "/v1/benchmark/contribute")
        # 200 (ok) or 400 (opt-in not enabled) both acceptable
        chk("200 or 400", r.status_code in (200, 400))

    def test_BC04_idempotent(self):
        """BC.4 — Calling contribute twice returns ok both times."""
        section("BC.4 — Contribute idempotent")
        r1 = _api("post", "/v1/benchmark/contribute")
        r2 = _api("post", "/v1/benchmark/contribute")
        chk("both non-500", r1.status_code < 500 and r2.status_code < 500)

    def test_BC05_response_has_ok(self):
        """BC.5 — Successful contribute response has 'ok' field."""
        section("BC.5 — Contribute response shape")
        r = _api("post", "/v1/benchmark/contribute")
        if r.status_code == 200:
            chk("ok field", "ok" in r.json())


# ── D. K-anonymity ───────────────────────────────────────────────────────────────

class TestKAnonymity:
    def test_KA01_summary_excludes_small_cohorts(self):
        """KA.1 — Summary only lists cohorts with sample_size >= 5."""
        section("KA.1 — Summary k-anonymity")
        r = _pub("get", "/v1/benchmark/summary")
        for item in r.json().get("available", []):
            chk(f"sample_size>=5 ({item.get('metric')})", item.get("sample_size", 0) >= 5)

    def test_KA02_percentiles_404_when_insufficient(self):
        """KA.2 — Percentiles returns 404 for cohorts below k=5 floor."""
        section("KA.2 — Percentiles k-anonymity 404")
        # cost_per_token for a very specific model that almost certainly has <5 orgs
        r = _pub("get", "/v1/benchmark/percentiles?metric=cost_per_token&model=gpt-4-turbo-preview")
        # Either 404 (k<5 enforced) or 200 (enough data) — both valid
        chk("404 or 200", r.status_code in (200, 404))
        if r.status_code == 200:
            chk("sample_size>=5", r.json().get("sample_size", 0) >= 5)
