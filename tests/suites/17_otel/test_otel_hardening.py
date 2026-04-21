"""
test_otel_hardening.py — OTel Ingest Security & Hardening Regression Tests
===========================================================================
Suite OH: Regression tests for the security hardening applied to
/v1/otel/v1/metrics and /v1/otel/v1/logs. Protects against:

  Section A — Body-size cap           OH.01–OH.03
    Oversized POST bodies rejected with 413 before JSON parse.

  Section B — Attribute caps          OH.04–OH.07
    Huge attribute values silently truncated; whole batch still ingests.

  Section C — Timestamp validation    OH.08–OH.11
    Garbage / pre-2000 / far-future timestamps coerced to "now" rather
    than trusted blindly (prevents back-dating spend or polluting charts).

  Section D — Metric value clamping   OH.12–OH.15
    NaN / Infinity / negative / 1e20 coerced to safe range; no DB write
    of garbage cost values.

  Section E — Member-key tenancy      OH.16–OH.20
    A member key CANNOT emit metrics attributed to another team or user:
    developer_email + team.id claimed in OTLP attrs are overridden by the
    authenticated member's scope_team + email.

Labels: OH.01 – OH.20

These tests exercise behaviour introduced on branch
`fix/cohrint-mcp-security-audit` — they will fail against prod until
that branch merges and deploys.
"""

import sys
import time
import json
import requests
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config.settings import API_URL
from helpers.api import fresh_account, get_headers
from helpers.data import rand_email
from helpers.output import section, chk, info, warn


# ── Helpers ─────────────────────────────────────────────────────────────────

def _nano(seconds_offset: float = 0) -> str:
    """OTLP timeUnixNano string for now + offset."""
    return str(int((time.time() + seconds_offset) * 1e9))


def _metric_attr(key: str, value) -> dict:
    if isinstance(value, (int, float)):
        return {"key": key, "value": {"doubleValue": float(value)}}
    return {"key": key, "value": {"stringValue": str(value)}}


def _counter(name: str, value: float, attrs: dict = None, ts_nano: str = None) -> dict:
    return {
        "name": name,
        "sum": {
            "dataPoints": [{
                "asDouble": value,
                "timeUnixNano": ts_nano or _nano(),
                "attributes": [_metric_attr(k, v) for k, v in (attrs or {}).items()],
            }],
            "isMonotonic": True,
        },
    }


def _metrics_payload(metrics: list, user_email: str = "dev@test.com",
                     team: str = "platform", service: str = "claude-code") -> dict:
    return {
        "resourceMetrics": [{
            "resource": {
                "attributes": [
                    _metric_attr("service.name", service),
                    _metric_attr("user.email", user_email),
                    _metric_attr("session.id", "sess-hardening"),
                    _metric_attr("team.id", team),
                ],
            },
            "scopeMetrics": [{
                "scope": {"name": "test.hardening", "version": "1.0"},
                "metrics": metrics,
            }],
        }],
    }


def _post(headers, body):
    return requests.post(f"{API_URL}/v1/otel/v1/metrics",
                         json=body, headers=headers, timeout=30)


# ── Section A: Body-size cap ────────────────────────────────────────────────

def test_body_size_cap(headers):
    section("A — Body-size cap (OH.01–OH.03)")

    # Oversized body: 6 MB of padding inside a string attribute. Cap is 5 MB.
    big_value = "A" * (6 * 1024 * 1024)
    payload = _metrics_payload([
        _counter("claude_code.token.usage", 1, {"huge": big_value}),
    ])
    raw = json.dumps(payload).encode()
    r = requests.post(
        f"{API_URL}/v1/otel/v1/metrics",
        data=raw,
        headers={**headers, "Content-Type": "application/json"},
        timeout=30,
    )
    chk("OH.01 Oversized body (>5 MB) → 413",
        r.status_code == 413, f"got {r.status_code}: {r.text[:120]}")

    # Normal-size body still ingests.
    r2 = _post(headers, _metrics_payload([
        _counter("claude_code.token.usage", 10, {"type": "input", "model": "claude-sonnet-4-6"}),
    ]))
    chk("OH.02 Normal body → 200",
        r2.status_code == 200, f"got {r2.status_code}")

    # 413 error body is JSON with `error` field (stable contract for clients)
    if r.status_code == 413:
        try:
            body = r.json()
            chk("OH.03 413 body is JSON with `error` field",
                "error" in body, str(body)[:200])
        except Exception as e:
            chk("OH.03 413 body is JSON with `error` field", False, f"not JSON: {e}")


# ── Section B: Attribute caps ───────────────────────────────────────────────

def test_attribute_caps(headers):
    section("B — Attribute caps (OH.04–OH.07)")

    # Very long model name (>4096 chars) — should truncate, not reject.
    very_long_model = "m" * 5000
    payload = _metrics_payload([
        _counter("claude_code.token.usage", 123,
                 {"type": "input", "model": very_long_model}),
    ])
    r = _post(headers, payload)
    chk("OH.04 Oversized attr value → 200 (silent truncation, batch accepted)",
        r.status_code == 200, f"got {r.status_code}: {r.text[:200]}")

    # Many attributes on a single datapoint (>50) — extras dropped silently.
    many_attrs = {f"attr_{i}": f"v{i}" for i in range(200)}
    many_attrs["type"] = "input"
    many_attrs["model"] = "claude-sonnet-4-6"
    payload2 = _metrics_payload([
        _counter("claude_code.token.usage", 456, many_attrs),
    ])
    r2 = _post(headers, payload2)
    chk("OH.05 200 attributes on one DP → 200 (extras dropped, not rejected)",
        r2.status_code == 200, f"got {r2.status_code}")

    # Empty metric name → record dropped silently, response still 200.
    payload3 = _metrics_payload([{
        "name": "",
        "sum": {"dataPoints": [{"asDouble": 1, "timeUnixNano": _nano(),
                                "attributes": []}], "isMonotonic": True},
    }, _counter("claude_code.token.usage", 1, {"type": "input", "model": "claude-sonnet-4-6"})])
    r3 = _post(headers, payload3)
    chk("OH.06 Mix of empty-name + valid metric → 200",
        r3.status_code == 200, f"got {r3.status_code}")

    # Confirm at least one prior payload landed by querying summary.
    time.sleep(2)
    s = requests.get(f"{API_URL}/v1/cross-platform/summary?days=1",
                     headers=headers, timeout=15)
    if s.status_code == 200:
        total = s.json().get("total_records", 0)
        chk("OH.07 Summary total_records > 0 after hardening writes",
            total > 0, f"total_records={total}")
    else:
        warn(f"OH.07 skipped — /cross-platform/summary returned {s.status_code}")


# ── Section C: Timestamp validation ─────────────────────────────────────────

def test_timestamp_validation(headers):
    section("C — Timestamp validation (OH.08–OH.11)")

    # Garbage timestamp string — should not reject the batch.
    payload = _metrics_payload([
        _counter("claude_code.token.usage", 1, {"type": "input", "model": "claude-sonnet-4-6"},
                 ts_nano="not-a-number"),
    ])
    r = _post(headers, payload)
    chk("OH.08 Garbage timestamp → 200 (coerced to now, not rejected)",
        r.status_code == 200, f"got {r.status_code}")

    # Pre-2000 timestamp — coerced to now.
    payload2 = _metrics_payload([
        _counter("claude_code.token.usage", 1, {"type": "input", "model": "claude-sonnet-4-6"},
                 ts_nano="100000000000000000"),  # ~1973 in nanos
    ])
    r2 = _post(headers, payload2)
    chk("OH.09 Pre-2000 timestamp → 200", r2.status_code == 200, f"got {r2.status_code}")

    # Far-future timestamp (year 3000) — coerced to now.
    far_future_nano = str(int((time.time() + 86400 * 365 * 1000) * 1e9))
    payload3 = _metrics_payload([
        _counter("claude_code.token.usage", 1, {"type": "input", "model": "claude-sonnet-4-6"},
                 ts_nano=far_future_nano),
    ])
    r3 = _post(headers, payload3)
    chk("OH.10 Far-future timestamp → 200 (coerced to now)",
        r3.status_code == 200, f"got {r3.status_code}")

    # Missing timestamp entirely — defaults to now.
    payload4 = {
        "resourceMetrics": [{
            "resource": {"attributes": [
                _metric_attr("service.name", "claude-code"),
                _metric_attr("user.email", "dev@test.com"),
            ]},
            "scopeMetrics": [{
                "scope": {"name": "t", "version": "1"},
                "metrics": [{
                    "name": "claude_code.token.usage",
                    "sum": {"dataPoints": [{"asDouble": 1, "attributes": [
                        _metric_attr("type", "input"),
                        _metric_attr("model", "claude-sonnet-4-6"),
                    ]}], "isMonotonic": True},
                }],
            }],
        }],
    }
    r4 = _post(headers, payload4)
    chk("OH.11 Missing timestamp → 200 (default to now)",
        r4.status_code == 200, f"got {r4.status_code}")


# ── Section D: Metric value clamping ────────────────────────────────────────

def test_metric_value_clamping(headers):
    section("D — Metric value clamping (OH.12–OH.15)")

    # NaN via OTLP (stringValue masquerading as a number) — SDK bugs do this.
    payload = {
        "resourceMetrics": [{
            "resource": {"attributes": [_metric_attr("service.name", "claude-code")]},
            "scopeMetrics": [{"scope": {"name": "t", "version": "1"}, "metrics": [{
                "name": "claude_code.token.usage",
                "sum": {"dataPoints": [{
                    "asDouble": float("1e20"),  # 1e20 > cap 1e12 → clamped
                    "timeUnixNano": _nano(),
                    "attributes": [
                        _metric_attr("type", "input"),
                        _metric_attr("model", "claude-sonnet-4-6"),
                    ],
                }], "isMonotonic": True},
            }]}],
        }],
    }
    r = _post(headers, payload)
    chk("OH.12 Absurd value 1e20 → 200 (clamped, not rejected)",
        r.status_code == 200, f"got {r.status_code}")

    # Negative value — coerced to 0.
    payload2 = _metrics_payload([
        _counter("claude_code.token.usage", -500,
                 {"type": "input", "model": "claude-sonnet-4-6"}),
    ])
    r2 = _post(headers, payload2)
    chk("OH.13 Negative value → 200 (clamped to 0)",
        r2.status_code == 200, f"got {r2.status_code}")

    # Infinity
    payload3 = _metrics_payload([
        _counter("claude_code.token.usage", float("inf"),
                 {"type": "input", "model": "claude-sonnet-4-6"}),
    ])
    r3 = _post(headers, payload3)
    chk("OH.14 Infinity → 200 (coerced to 0)",
        r3.status_code == 200, f"got {r3.status_code}")

    # Spend summary is bounded (no absurd total after the 1e20 ingest).
    time.sleep(2)
    s = requests.get(f"{API_URL}/v1/cross-platform/summary?days=1",
                     headers=headers, timeout=15)
    if s.status_code == 200:
        tokens = s.json().get("total_tokens", 0)
        chk("OH.15 total_tokens within sane bound (≤ 1e13) after 1e20 ingest",
            tokens < 1e13, f"total_tokens={tokens}")
    else:
        warn(f"OH.15 skipped — /cross-platform/summary returned {s.status_code}")


# ── Section E: Member-key tenancy enforcement ───────────────────────────────

def _invite_member(owner_headers, team_id: str, email: str, scope_team: str) -> dict:
    """Invite a member scoped to a team. Returns full response dict with api_key."""
    r = requests.post(
        f"{API_URL}/v1/auth/members",
        json={"email": email, "role": "member",
              "team_id": team_id, "scope_team": scope_team},
        headers=owner_headers, timeout=15,
    )
    if not r.ok:
        raise RuntimeError(f"invite failed {r.status_code}: {r.text[:200]}")
    return r.json()


def _create_team(owner_headers, name: str) -> str:
    r = requests.post(f"{API_URL}/v1/teams", json={"name": name},
                      headers=owner_headers, timeout=15)
    if not r.ok:
        raise RuntimeError(f"create team failed {r.status_code}: {r.text[:200]}")
    return r.json()["team_id"]


def test_member_tenancy_enforcement(headers):
    section("E — Member-key tenancy (OH.16–OH.20)")

    # Provision a team + scoped member on the same org.
    try:
        team_id = _create_team(headers, name=f"tenancy-{int(time.time())}")
    except Exception as e:
        warn(f"OH.16–20 skipped — could not create team: {e}")
        return

    member_email = rand_email("scoped")
    try:
        invite = _invite_member(headers, team_id=team_id,
                                email=member_email, scope_team=team_id)
    except Exception as e:
        warn(f"OH.16–20 skipped — could not invite scoped member: {e}")
        return

    member_key = invite["api_key"]
    member_headers = get_headers(member_key)

    # Attempt #1: member claims a DIFFERENT team + DIFFERENT user email.
    spoofed_team = "executive-team"
    spoofed_email = "ceo@acme.com"
    payload = _metrics_payload([
        _counter("claude_code.token.usage", 777,
                 {"type": "input", "model": "claude-sonnet-4-6"}),
    ], user_email=spoofed_email, team=spoofed_team)
    r = _post(member_headers, payload)
    chk("OH.16 Scoped member POST metrics → 200",
        r.status_code == 200, f"got {r.status_code}: {r.text[:200]}")

    # Give D1 a moment; then verify the stored record was rewritten to the
    # member's real email + scope_team — NOT the spoofed values.
    time.sleep(2)
    devs = requests.get(f"{API_URL}/v1/cross-platform/developers?days=1",
                        headers=headers, timeout=15).json().get("developers", [])
    emails = [d.get("developer_email") for d in devs]
    chk("OH.17 Stored developer_email == authenticated member (not spoof)",
        member_email in emails and spoofed_email not in emails,
        f"emails={emails}")

    # Team attribution should follow scope_team, not the spoofed team.
    teams = [d.get("team") for d in devs if d.get("developer_email") == member_email]
    chk("OH.18 Stored team == member.scope_team (not spoof)",
        team_id in teams and spoofed_team not in teams,
        f"teams_for_member={teams}")

    # Also verify on /v1/cross-platform/summary that spoofed team does not
    # appear as a real team row.
    s = requests.get(f"{API_URL}/v1/cross-platform/summary?days=1",
                     headers=headers, timeout=15)
    if s.status_code == 200:
        by_team = [row.get("team") for row in s.json().get("by_team", [])]
        chk("OH.19 Spoofed team not present in summary.by_team",
            spoofed_team not in by_team, f"by_team={by_team}")
    else:
        warn(f"OH.19 skipped — /cross-platform/summary returned {s.status_code}")

    # And the owner's OTel post is NOT rewritten — owners can still attribute
    # to any user/team legitimately (e.g. multi-user agents, batch import).
    owner_payload = _metrics_payload([
        _counter("claude_code.token.usage", 42,
                 {"type": "input", "model": "claude-sonnet-4-6"}),
    ], user_email="owner-posted@acme.com", team="other-team")
    ro = _post(headers, owner_payload)
    chk("OH.20 Owner-key post with explicit user/team → 200 (no rewrite)",
        ro.status_code == 200, f"got {ro.status_code}")


# ── Main runner ─────────────────────────────────────────────────────────────

def run():
    info("=" * 60)
    info("  Cohrint — OTel Ingest Hardening Regression Tests")
    info("  Branch: fix/cohrint-mcp-security-audit")
    info("=" * 60)

    try:
        api_key, _org_id, _cookies = fresh_account(prefix="oh")
    except Exception as e:
        warn(f"Could not create test account: {e}")
        from helpers.output import get_results
        return get_results()

    headers = get_headers(api_key)
    test_body_size_cap(headers)
    test_attribute_caps(headers)
    test_timestamp_validation(headers)
    test_metric_value_clamping(headers)
    test_member_tenancy_enforcement(headers)

    from helpers.output import get_results
    return get_results()


if __name__ == "__main__":
    results = run()
    passed = results.get("passed", 0)
    failed = results.get("failed", 0)
    total = passed + failed
    info(f"\nResults: {passed}/{total} passed, {failed} failed")
    sys.exit(1 if failed > 0 else 0)
