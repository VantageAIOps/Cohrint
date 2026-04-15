"""
test_superadmin_api.py — Superadmin endpoint tests
===================================================
Suite SA: Tests all 8 superadmin API endpoints.

Auth-rejection tests run always (no secret needed).
Authenticated data tests run only when SUPERADMIN_SECRET env var is set.

Labels: SA.1 - SA.N
"""

import os
import sys
import time
import requests
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config.settings import API_URL
from helpers.output import ok, fail, warn, info, section, chk, get_results

BASE = f"{API_URL}/v1/superadmin"
SECRET = os.environ.get("SUPERADMIN_SECRET", "")
AUTH_HEADERS = {"Authorization": f"Bearer {SECRET}"} if SECRET else {}
WRONG_HEADERS = {"Authorization": "Bearer crt_wrong_secret_test_12345"}
TIMEOUT = 20


# ── Helpers ───────────────────────────────────────────────────────────────────

def sa_get(path, headers=None, params=None):
    return requests.get(f"{BASE}{path}", headers=headers, params=params, timeout=TIMEOUT)


def sa_post(path, headers=None, json=None):
    return requests.post(f"{BASE}{path}", headers=headers, json=json, timeout=TIMEOUT)


def has_error_field(r) -> bool:
    try:
        return "error" in r.json()
    except Exception:
        return False


# ── SA-A: Auth rejection (no secret needed) ───────────────────────────────────

def test_auth_rejection():
    section("SA-A. Superadmin — Auth Rejection")

    # No credentials at all
    r = sa_post("/auth")
    chk("SA.1  POST /superadmin/auth → 403 without credentials",
        r.status_code == 403, f"got {r.status_code}")
    chk("SA.2  POST /superadmin/auth error field present (no creds)",
        has_error_field(r), f"body: {r.text[:120]}")

    # Wrong credentials
    r2 = sa_post("/auth", headers=WRONG_HEADERS)
    chk("SA.3  POST /superadmin/auth → 403 with wrong secret",
        r2.status_code == 403, f"got {r2.status_code}")

    # Stats endpoint — no credentials
    r3 = sa_get("/stats")
    chk("SA.4  GET /superadmin/stats → 403 without credentials",
        r3.status_code == 403, f"got {r3.status_code}")

    # Users endpoint — wrong credentials
    r4 = sa_get("/users", headers=WRONG_HEADERS)
    chk("SA.5  GET /superadmin/users → 403 with wrong secret",
        r4.status_code == 403, f"got {r4.status_code}")

    # Geography — no credentials
    r5 = sa_get("/geography")
    chk("SA.6  GET /superadmin/geography → 403 without credentials",
        r5.status_code == 403, f"got {r5.status_code}")

    # Features — wrong credentials
    r6 = sa_get("/features", headers=WRONG_HEADERS)
    chk("SA.7  GET /superadmin/features → 403 with wrong secret",
        r6.status_code == 403, f"got {r6.status_code}")

    # Traffic — no credentials
    r7 = sa_get("/traffic")
    chk("SA.8  GET /superadmin/traffic → 403 without credentials",
        r7.status_code == 403, f"got {r7.status_code}")

    # Storage — wrong credentials
    r8 = sa_get("/storage", headers=WRONG_HEADERS)
    chk("SA.9  GET /superadmin/storage → 403 with wrong secret",
        r8.status_code == 403, f"got {r8.status_code}")

    # Reset — no credentials
    r9 = sa_post("/reset", json={"target": "events", "mode": "soft", "confirm": "events-soft"})
    chk("SA.10 POST /superadmin/reset → 403 without credentials",
        r9.status_code == 403, f"got {r9.status_code}")


# ── SA-B: Reset validation (no auth, invalid request) ────────────────────────

def test_reset_validation():
    section("SA-B. Superadmin — Reset Input Validation")

    if not SECRET:
        warn("SA-B  SUPERADMIN_SECRET not set — skipping reset validation tests")
        return

    # Missing confirm field
    r = sa_post("/reset", headers=AUTH_HEADERS,
                json={"target": "events", "mode": "soft"})
    chk("SA.11 POST /superadmin/reset → 400 missing confirm field",
        r.status_code == 400, f"got {r.status_code}: {r.text[:100]}")

    # Wrong confirm value
    r2 = sa_post("/reset", headers=AUTH_HEADERS,
                 json={"target": "events", "mode": "soft", "confirm": "wrong"})
    chk("SA.12 POST /superadmin/reset → 400 wrong confirm value",
        r2.status_code == 400, f"got {r2.status_code}: {r2.text[:100]}")

    # Invalid target
    r3 = sa_post("/reset", headers=AUTH_HEADERS,
                 json={"target": "nonexistent", "mode": "soft", "confirm": "nonexistent-soft"})
    chk("SA.13 POST /superadmin/reset → 400 invalid target",
        r3.status_code == 400, f"got {r3.status_code}: {r3.text[:100]}")

    # Invalid mode
    r4 = sa_post("/reset", headers=AUTH_HEADERS,
                 json={"target": "events", "mode": "medium", "confirm": "events-medium"})
    chk("SA.14 POST /superadmin/reset → 400 invalid mode",
        r4.status_code == 400, f"got {r4.status_code}: {r4.text[:100]}")

    # Invalid JSON body
    r5 = requests.post(f"{BASE}/reset", headers={**AUTH_HEADERS, "Content-Type": "application/json"},
                       data="not-json", timeout=TIMEOUT)
    chk("SA.15 POST /superadmin/reset → 400 invalid JSON",
        r5.status_code == 400, f"got {r5.status_code}: {r5.text[:100]}")


# ── SA-C: Authenticated data endpoints ───────────────────────────────────────

def test_authenticated_endpoints():
    section("SA-C. Superadmin — Authenticated Data Endpoints")

    if not SECRET:
        warn("SA-C  SUPERADMIN_SECRET not set — skipping authenticated endpoint tests")
        info("      Set SUPERADMIN_SECRET env var in CI secrets to enable these checks")
        return

    # POST /auth — success
    r = sa_post("/auth", headers=AUTH_HEADERS)
    chk("SA.16 POST /superadmin/auth → 200 with correct secret",
        r.status_code == 200, f"got {r.status_code}: {r.text[:100]}")
    if r.ok:
        d = r.json()
        chk("SA.17 POST /superadmin/auth response has ok field",
            d.get("ok") is True, f"got: {d}")

    # GET /stats
    r2 = sa_get("/stats", headers=AUTH_HEADERS, params={"period": "7"})
    chk("SA.18 GET /superadmin/stats → 200",
        r2.status_code == 200, f"got {r2.status_code}: {r2.text[:120]}")
    if r2.ok:
        d2 = r2.json()
        chk("SA.19 GET /superadmin/stats has orgs + events fields",
            "orgs" in d2 and "events" in d2,
            f"keys: {list(d2.keys())}")
        chk("SA.20 GET /superadmin/stats has period_days field",
            "period_days" in d2, f"keys: {list(d2.keys())}")

    # GET /users
    r3 = sa_get("/users", headers=AUTH_HEADERS, params={"period": "7"})
    chk("SA.21 GET /superadmin/users → 200",
        r3.status_code == 200, f"got {r3.status_code}: {r3.text[:120]}")
    if r3.ok:
        d3 = r3.json()
        chk("SA.22 GET /superadmin/users has signups + daily_signups",
            "signups" in d3 and "daily_signups" in d3,
            f"keys: {list(d3.keys())}")

    # GET /geography
    r4 = sa_get("/geography", headers=AUTH_HEADERS, params={"period": "7"})
    chk("SA.23 GET /superadmin/geography → 200",
        r4.status_code == 200, f"got {r4.status_code}: {r4.text[:120]}")
    if r4.ok:
        d4 = r4.json()
        chk("SA.24 GET /superadmin/geography has countries + colos",
            "countries" in d4 and "colos" in d4,
            f"keys: {list(d4.keys())}")

    # GET /features
    r5 = sa_get("/features", headers=AUTH_HEADERS, params={"period": "7"})
    chk("SA.25 GET /superadmin/features → 200",
        r5.status_code == 200, f"got {r5.status_code}: {r5.text[:120]}")
    if r5.ok:
        d5 = r5.json()
        chk("SA.26 GET /superadmin/features has features + models + providers",
            "features" in d5 and "models" in d5 and "providers" in d5,
            f"keys: {list(d5.keys())}")

    # GET /traffic
    r6 = sa_get("/traffic", headers=AUTH_HEADERS, params={"period": "7"})
    chk("SA.27 GET /superadmin/traffic → 200",
        r6.status_code == 200, f"got {r6.status_code}: {r6.text[:120]}")
    if r6.ok:
        d6 = r6.json()
        chk("SA.28 GET /superadmin/traffic has api_traffic + page_traffic",
            "api_traffic" in d6 and "page_traffic" in d6,
            f"keys: {list(d6.keys())}")

    # GET /storage
    r7 = sa_get("/storage", headers=AUTH_HEADERS)
    chk("SA.29 GET /superadmin/storage → 200",
        r7.status_code == 200, f"got {r7.status_code}: {r7.text[:120]}")
    if r7.ok:
        d7 = r7.json()
        chk("SA.30 GET /superadmin/storage has db_tables + kv_keys_approx",
            "db_tables" in d7 and "kv_keys_approx" in d7,
            f"keys: {list(d7.keys())}")
        chk("SA.31 GET /superadmin/storage db_tables is a dict",
            isinstance(d7.get("db_tables"), dict),
            f"type: {type(d7.get('db_tables'))}")

    # POST /reset — soft reset KV (safe operation, clears rate-limit keys)
    r8 = sa_post("/reset", headers=AUTH_HEADERS,
                 json={"target": "kv", "mode": "soft", "confirm": "kv-soft"})
    chk("SA.32 POST /superadmin/reset kv-soft → 200",
        r8.status_code == 200, f"got {r8.status_code}: {r8.text[:120]}")
    if r8.ok:
        d8 = r8.json()
        chk("SA.33 POST /superadmin/reset response has ok + results fields",
            d8.get("ok") is True and "results" in d8,
            f"got: {d8}")

    # GET /stats period boundary
    r9 = sa_get("/stats", headers=AUTH_HEADERS, params={"period": "400"})
    chk("SA.34 GET /superadmin/stats period capped at 365",
        r9.status_code == 200 and r9.json().get("period_days", 0) <= 365,
        f"period_days: {r9.json().get('period_days') if r9.ok else r9.status_code}")


# ── SA-D: Response shape + CORS ───────────────────────────────────────────────

def test_response_shape():
    section("SA-D. Superadmin — Response Shape & Headers")

    # All 403 responses must have JSON error field
    endpoints = [
        ("GET",  "/stats"),
        ("GET",  "/users"),
        ("GET",  "/geography"),
        ("GET",  "/features"),
        ("GET",  "/traffic"),
        ("GET",  "/storage"),
    ]
    for i, (method, path) in enumerate(endpoints, 35):
        if method == "GET":
            r = sa_get(path)
        else:
            r = sa_post(path)
        chk(f"SA.{i}  {method} /superadmin{path} error response has JSON error field",
            has_error_field(r), f"status={r.status_code} body={r.text[:80]}")


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    info(f"Superadmin base URL : {BASE}")
    info(f"Authenticated tests : {'ENABLED' if SECRET else 'DISABLED (set SUPERADMIN_SECRET)'}")
    print()

    test_auth_rejection()
    test_reset_validation()
    test_authenticated_endpoints()
    test_response_shape()

    results = get_results()
    passed  = results["passed"]
    failed  = results["failed"]
    warned  = results["warned"]
    total   = passed + failed

    print()
    print(f"{'='*55}")
    print(f"  Superadmin Suite: {passed}/{total} passed  |  {warned} warnings")
    print(f"{'='*55}")

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
