"""
test_enterprise_rbac.py — Enterprise RBAC + Multi-team Business Case Tests
===========================================================================

Suite ER: Validates the 32-person / 3-team enterprise use case:
  - Role hierarchy: owner > superadmin > ceo > admin > member > viewer
  - Budget policies CRUD (POST/PUT/DELETE /v1/admin/budget-policies)
  - Provider-scoped budgets
  - /v1/analytics/executive (ceo/superadmin/owner only)
  - /v1/cross-platform/developers returns team field
  - /v1/cross-platform/live returns agent_name, token_rate_per_sec, team
  - /v1/admin/developers/recommendations (admin+ only)
  - Role-based access enforcement (403 for insufficient roles)

Labels: ER.1 – ER.N
"""

import os
import sys
import uuid
import requests
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config.settings import API_URL, CI_API_KEY, CI_ORG_ID, CI_SECRET
from helpers.output import ok, fail, warn, info, section, chk, get_results

BASE    = API_URL
TIMEOUT = 20

# ── helpers ───────────────────────────────────────────────────────────────────

def _headers(key):
    return {"Authorization": f"Bearer {key}"}

def _api(method, path, key=None, **kwargs):
    h = _headers(key) if key else {}
    return getattr(requests, method)(
        f"{BASE}{path}", headers=h, timeout=TIMEOUT, **kwargs
    )

def skip_no_key():
    if not CI_API_KEY:
        warn("VANTAGE_CI_API_KEY not set — skipping authenticated tests")
        return True
    return False

def fresh_member_key(org_key, role="member", scope_team=None, email=None):
    """Invite a fresh member and return their API key."""
    payload = {
        "email":      email or f"test-{uuid.uuid4().hex[:8]}@example.com",
        "name":       "Test Member",
        "role":       role,
    }
    if scope_team:
        payload["scope_team"] = scope_team
    r = requests.post(
        f"{BASE}/v1/auth/members",
        headers=_headers(org_key),
        json=payload,
        timeout=TIMEOUT,
    )
    if r.status_code not in (200, 201):
        return None, r
    data = r.json()
    return data.get("api_key") or data.get("member", {}).get("api_key"), r

# ══════════════════════════════════════════════════════════════════════════════
# ER-A: Role hierarchy — access control enforcement
# ══════════════════════════════════════════════════════════════════════════════

def test_role_hierarchy():
    section("ER-A. Role Hierarchy — Access Control")

    if skip_no_key():
        return

    owner_key = CI_API_KEY

    # Invite a plain member
    member_key, r = fresh_member_key(owner_key, role="member")
    chk("ER-A.1 Invite member — HTTP 200/201", r.status_code in (200, 201), f"got {r.status_code}: {r.text[:120]}")

    if not member_key:
        warn("ER-A: Could not get member key — skipping role check tests")
        return

    # Member cannot access /v1/admin/budget-policies
    r2 = _api("get", "/v1/admin/budget-policies", key=member_key)
    chk("ER-A.2 member blocked from /v1/admin/budget-policies", r2.status_code == 403, f"got {r2.status_code}")

    # Member cannot access /v1/analytics/executive
    r3 = _api("get", "/v1/analytics/executive", key=member_key)
    chk("ER-A.3 member blocked from /v1/analytics/executive", r3.status_code == 403, f"got {r3.status_code}")

    # Member cannot access /v1/admin/developers/recommendations
    r4 = _api("get", "/v1/admin/developers/recommendations", key=member_key)
    chk("ER-A.4 member blocked from /v1/admin/developers/recommendations", r4.status_code == 403, f"got {r4.status_code}")

    # Owner can access all three
    r5 = _api("get", "/v1/admin/budget-policies", key=owner_key)
    chk("ER-A.5 owner can access /v1/admin/budget-policies", r5.status_code == 200, f"got {r5.status_code}: {r5.text[:120]}")

    r6 = _api("get", "/v1/analytics/executive", key=owner_key)
    chk("ER-A.6 owner can access /v1/analytics/executive", r6.status_code == 200, f"got {r6.status_code}: {r6.text[:120]}")

    # Invite an admin-role member
    admin_key, _ = fresh_member_key(owner_key, role="admin")
    if admin_key:
        r7 = _api("get", "/v1/admin/budget-policies", key=admin_key)
        chk("ER-A.7 admin can access /v1/admin/budget-policies", r7.status_code == 200, f"got {r7.status_code}: {r7.text[:120]}")

        r8 = _api("get", "/v1/analytics/executive", key=admin_key)
        chk("ER-A.8 admin blocked from /v1/analytics/executive (needs ceo+)", r8.status_code == 403, f"got {r8.status_code}")
    else:
        warn("ER-A.7-8: Could not get admin key — skipping")

    # Invite a ceo-role member
    ceo_key, _ = fresh_member_key(owner_key, role="ceo")
    if ceo_key:
        r9 = _api("get", "/v1/analytics/executive", key=ceo_key)
        chk("ER-A.9 ceo can access /v1/analytics/executive", r9.status_code == 200, f"got {r9.status_code}: {r9.text[:120]}")

        r10 = _api("get", "/v1/admin/budget-policies", key=ceo_key)
        chk("ER-A.10 ceo can access /v1/admin/budget-policies (admin+ route)", r10.status_code == 200, f"got {r10.status_code}: {r10.text[:120]}")
    else:
        warn("ER-A.9-10: Could not get ceo key — skipping")

    # Invite a superadmin-role member
    sa_key, _ = fresh_member_key(owner_key, role="superadmin")
    if sa_key:
        r11 = _api("get", "/v1/analytics/executive", key=sa_key)
        chk("ER-A.11 superadmin can access /v1/analytics/executive", r11.status_code == 200, f"got {r11.status_code}: {r11.text[:120]}")
    else:
        warn("ER-A.11: Could not get superadmin key — skipping")


# ══════════════════════════════════════════════════════════════════════════════
# ER-B: Budget policies CRUD
# ══════════════════════════════════════════════════════════════════════════════

def test_budget_policies_crud():
    section("ER-B. Budget Policies CRUD")

    if skip_no_key():
        return

    key = CI_API_KEY

    # List — starts empty or has some policies (must return 200 with policies array)
    r = _api("get", "/v1/admin/budget-policies", key=key)
    chk("ER-B.1 GET /v1/admin/budget-policies returns 200", r.status_code == 200, f"got {r.status_code}: {r.text[:120]}")
    chk("policies" in (r.json() if r.status_code == 200 else {}),
        "ER-B.2 Response contains 'policies' array", r.text[:80])

    # Create — org-level policy
    r2 = _api("post", "/v1/admin/budget-policies", key=key, json={
        "scope": "org",
        "monthly_limit_usd": 5000,
        "enforcement": "alert",
    })
    chk("ER-B.3 POST org-level policy returns 201", r2.status_code in (200, 201), f"got {r2.status_code}: {r2.text[:120]}")
    org_policy_id = (r2.json().get("id") if r2.status_code in (200, 201) else None)

    # Create — team-level policy (Claude team)
    r3 = _api("post", "/v1/admin/budget-policies", key=key, json={
        "scope": "team",
        "scope_target": "claude-team",
        "monthly_limit_usd": 2000,
        "alert_threshold_80": True,
        "enforcement": "alert",
    })
    chk("ER-B.4 POST team-scoped policy (claude-team)", r3.status_code in (200, 201), f"got {r3.status_code}: {r3.text[:120]}")
    team_policy_id = (r3.json().get("id") if r3.status_code in (200, 201) else None)

    # Create — provider-scoped budget (Claude Code tool)
    r4 = _api("post", "/v1/admin/budget-policies", key=key, json={
        "scope": "provider",
        "scope_target": "claude_code",
        "monthly_limit_usd": 3000,
        "enforcement": "alert",
    })
    chk("ER-B.5 POST provider-scoped policy (claude_code)", r4.status_code in (200, 201), f"got {r4.status_code}: {r4.text[:120]}")
    provider_policy_id = (r4.json().get("id") if r4.status_code in (200, 201) else None)

    # Create — developer-scoped
    r5 = _api("post", "/v1/admin/budget-policies", key=key, json={
        "scope": "developer",
        "scope_target": "alice@example.com",
        "monthly_limit_usd": 500,
        "enforcement": "alert",
    })
    chk("ER-B.6 POST developer-scoped policy", r5.status_code in (200, 201), f"got {r5.status_code}: {r5.text[:120]}")
    dev_policy_id = (r5.json().get("id") if r5.status_code in (200, 201) else None)

    # Create — team_provider combo
    r6 = _api("post", "/v1/admin/budget-policies", key=key, json={
        "scope": "team_provider",
        "scope_target": "gemini-team",
        "provider_target": "gemini_cli",
        "monthly_limit_usd": 1500,
        "enforcement": "alert",
    })
    chk("ER-B.7 POST team_provider combo policy", r6.status_code in (200, 201), f"got {r6.status_code}: {r6.text[:120]}")

    # Validation — missing scope_target for team scope
    r7 = _api("post", "/v1/admin/budget-policies", key=key, json={
        "scope": "team",
        "monthly_limit_usd": 100,
    })
    chk("ER-B.8 POST team scope without scope_target → 400", r7.status_code == 400, f"got {r7.status_code}")

    # Validation — invalid scope
    r8 = _api("post", "/v1/admin/budget-policies", key=key, json={
        "scope": "invalid_scope",
        "monthly_limit_usd": 100,
    })
    chk("ER-B.9 POST invalid scope → 400", r8.status_code == 400, f"got {r8.status_code}")

    # Update — change monthly limit
    if team_policy_id:
        r9 = _api("put", f"/v1/admin/budget-policies/{team_policy_id}", key=key, json={
            "monthly_limit_usd": 2500,
        })
        chk("ER-B.10 PUT update team policy limit", r9.status_code == 200, f"got {r9.status_code}: {r9.text[:80]}")

    # Update — non-existent ID
    r10 = _api("put", "/v1/admin/budget-policies/nonexistent-id-xyz", key=key, json={
        "monthly_limit_usd": 100,
    })
    chk("ER-B.11 PUT non-existent policy → 404", r10.status_code == 404, f"got {r10.status_code}")

    # Delete — provider policy
    if provider_policy_id:
        r11 = _api("delete", f"/v1/admin/budget-policies/{provider_policy_id}", key=key)
        chk("ER-B.12 DELETE provider policy", r11.status_code == 200, f"got {r11.status_code}: {r11.text[:80]}")

        # Confirm deleted — PUT should return 404
        r12 = _api("put", f"/v1/admin/budget-policies/{provider_policy_id}", key=key,
                   json={"monthly_limit_usd": 999})
        chk("ER-B.13 PUT after DELETE → 404", r12.status_code == 404, f"got {r12.status_code}")

    # Cleanup remaining test policies
    for pid in [org_policy_id, team_policy_id, dev_policy_id]:
        if pid:
            _api("delete", f"/v1/admin/budget-policies/{pid}", key=key)


# ══════════════════════════════════════════════════════════════════════════════
# ER-C: Executive endpoint response shape
# ══════════════════════════════════════════════════════════════════════════════

def test_executive_endpoint():
    section("ER-C. Executive Endpoint")

    if skip_no_key():
        return

    key = CI_API_KEY

    r = _api("get", "/v1/analytics/executive?days=30", key=key)
    chk("ER-C.1 GET /v1/analytics/executive returns 200", r.status_code == 200, f"got {r.status_code}: {r.text[:200]}")

    if r.status_code != 200:
        return

    d = r.json()

    # Required top-level keys
    for field in ["org", "totals", "by_team", "by_provider", "top_developers",
                  "budget_policies", "member_roles", "period_days", "generated_at"]:
        chk(f"ER-C.2 Response contains '{field}'", field in d, str(list(d.keys())))

    # Org shape
    org = d.get("org", {})
    for f in ["name", "plan", "budget_usd", "mtd_cost_usd"]:
        chk(f"ER-C.3 org.{f} present", f in org, str(list(org.keys())))

    # Totals shape
    totals = d.get("totals", {})
    chk("total_cost_usd" in totals, "ER-C.4 totals.total_cost_usd present")
    chk("savings_opportunity_usd" in totals, "ER-C.5 totals.savings_opportunity_usd present")

    # by_team entries have by_provider
    teams = d.get("by_team", [])
    if teams:
        t = teams[0]
        for f in ["team", "cost", "by_provider"]:
            chk(f"ER-C.6 by_team[0].{f} present", f in t, str(list(t.keys())))
        chk("budget_pct" in t, "ER-C.7 by_team[0].budget_pct present")

    # top_developers
    devs = d.get("top_developers", [])
    if devs:
        dev = devs[0]
        for f in ["developer_email", "team", "cost", "pull_requests"]:
            chk(f"ER-C.8 top_developers[0].{f} present", f in dev, str(list(dev.keys())))

    # Days parameter
    chk("ER-C.9 period_days = 30", d.get("period_days") == 30)

    # Test 7-day and 90-day variants
    r2 = _api("get", "/v1/analytics/executive?days=7", key=key)
    chk("ER-C.10 executive?days=7 returns 200", r2.status_code == 200, f"got {r2.status_code}")

    r3 = _api("get", "/v1/analytics/executive?days=90", key=key)
    chk("ER-C.11 executive?days=90 returns 200", r3.status_code == 200, f"got {r3.status_code}")


# ══════════════════════════════════════════════════════════════════════════════
# ER-D: Developer list includes team field
# ══════════════════════════════════════════════════════════════════════════════

def test_developers_team_field():
    section("ER-D. /v1/cross-platform/developers includes team field")

    if skip_no_key():
        return

    key = CI_API_KEY

    r = _api("get", "/v1/cross-platform/developers?days=30", key=key)
    chk("ER-D.1 GET /v1/cross-platform/developers returns 200", r.status_code == 200, f"got {r.status_code}: {r.text[:120]}")

    if r.status_code != 200:
        return

    d = r.json()
    chk("developers" in d, "ER-D.2 Response contains 'developers' array",
        str(list(d.keys())))
    chk("team_filter" in d, "ER-D.3 Response contains 'team_filter' field",
        str(list(d.keys())))

    devs = d.get("developers", [])
    if devs:
        dev = devs[0]
        chk("team" in dev, "ER-D.4 developer entry has 'team' field",
            f"keys: {list(dev.keys())}")

    # Team filter param passes through correctly
    r2 = _api("get", "/v1/cross-platform/developers?days=30&team=claude-team", key=key)
    chk("ER-D.5 ?team=claude-team filter param accepted", r2.status_code == 200, f"got {r2.status_code}")
    if r2.status_code == 200:
        d2 = r2.json()
        chk("ER-D.6 team_filter echoed back in response", d2.get("team_filter") == "claude-team", str(d2.get("team_filter")))


# ══════════════════════════════════════════════════════════════════════════════
# ER-E: Live feed includes agent_name + token_rate_per_sec + team
# ══════════════════════════════════════════════════════════════════════════════

def test_live_feed_enriched():
    section("ER-E. /v1/cross-platform/live — enriched fields")

    if skip_no_key():
        return

    key = CI_API_KEY

    r = _api("get", "/v1/cross-platform/live?limit=10", key=key)
    chk("ER-E.1 GET /v1/cross-platform/live returns 200", r.status_code == 200, f"got {r.status_code}: {r.text[:120]}")

    if r.status_code != 200:
        return

    d = r.json()
    chk("events" in d, "ER-E.2 Response contains 'events' array")
    chk("is_stale" in d, "ER-E.3 Response contains 'is_stale' flag")

    events = d.get("events", [])
    if events:
        e = events[0]
        # New enriched fields must be present (may be null but must exist as keys)
        for field in ["agent_name", "token_rate_per_sec", "team", "tokens_in", "tokens_out"]:
            chk(f"ER-E.4 event has '{field}' field", field in e, f"keys: {list(e.keys())}")

        # token_rate_per_sec is numeric when duration_ms > 0, else null
        rate = e.get("token_rate_per_sec")
        chk("ER-E.5 token_rate_per_sec is null or numeric", rate is None or isinstance(rate, (int, float)), str(rate))
    else:
        warn("ER-E.4-5: No events returned — cannot validate event shape")


# ══════════════════════════════════════════════════════════════════════════════
# ER-F: Developer recommendations endpoint
# ══════════════════════════════════════════════════════════════════════════════

def test_developer_recommendations():
    section("ER-F. /v1/admin/developers/recommendations")

    if skip_no_key():
        return

    key = CI_API_KEY

    r = _api("get", "/v1/admin/developers/recommendations?days=30", key=key)
    chk("ER-F.1 GET recommendations returns 200", r.status_code == 200, f"got {r.status_code}: {r.text[:120]}")

    if r.status_code != 200:
        return

    d = r.json()
    chk("recommendations" in d, "ER-F.2 Response contains 'recommendations' array",
        str(list(d.keys())))
    chk("period_days" in d, "ER-F.3 Response contains 'period_days'")

    recs = d.get("recommendations", [])
    if recs:
        rec = recs[0]
        for field in ["developer_email", "team", "total_cost",
                      "cache_hit_rate_pct", "savings_opportunity_usd"]:
            chk(f"ER-F.4 recommendation has '{field}'", field in rec, f"keys: {list(rec.keys())}")
    else:
        warn("ER-F.4: No recommendations yet — ingest events with developer_email to populate")

    # Sorted by savings_opportunity_usd desc
    if len(recs) >= 2:
        chk("ER-F.5 Recommendations sorted by savings_opportunity_usd desc", recs[0]["savings_opportunity_usd"] >= recs[-1]["savings_opportunity_usd"])

    # Non-admin cannot access
    member_key, _ = fresh_member_key(key, role="member")
    if member_key:
        r2 = _api("get", "/v1/admin/developers/recommendations", key=member_key)
        chk("ER-F.6 member blocked from /v1/admin/developers/recommendations", r2.status_code == 403, f"got {r2.status_code}")


# ══════════════════════════════════════════════════════════════════════════════
# ER-G: Team-scoped member visibility
# ══════════════════════════════════════════════════════════════════════════════

def test_team_scoped_member():
    section("ER-G. Team-scoped member can only see their team's data")

    if skip_no_key():
        return

    key = CI_API_KEY

    # Invite a team-scoped member
    scoped_key, r = fresh_member_key(key, role="member", scope_team="claude-team")
    chk("ER-G.1 Invite team-scoped member", r.status_code in (200, 201), f"got {r.status_code}: {r.text[:120]}")

    if not scoped_key:
        warn("ER-G: Could not get scoped member key")
        return

    # Scoped member can call analytics (returns only their team's data)
    r2 = _api("get", "/v1/analytics/summary", key=scoped_key)
    chk("ER-G.2 Scoped member can access /v1/analytics/summary", r2.status_code == 200, f"got {r2.status_code}: {r2.text[:120]}")

    if r2.status_code == 200:
        s = r2.json()
        # scope_team echoed back in response (or as part of session)
        chk("scope_team" in s or "today_cost_usd" in s,
            "ER-G.3 Summary returns (scope_team echoed or data returned)",
            str(list(s.keys())))

    # Scoped member blocked from executive endpoint
    r3 = _api("get", "/v1/analytics/executive", key=scoped_key)
    chk("ER-G.4 Team-scoped member blocked from executive endpoint", r3.status_code == 403, f"got {r3.status_code}")


# ══════════════════════════════════════════════════════════════════════════════
# ER-H: Budget policy validation edge cases
# ══════════════════════════════════════════════════════════════════════════════

def test_budget_policy_validation():
    section("ER-H. Budget Policy Validation")

    if skip_no_key():
        return

    key = CI_API_KEY

    # Zero monthly limit rejected
    r = _api("post", "/v1/admin/budget-policies", key=key, json={
        "scope": "org",
        "monthly_limit_usd": 0,
    })
    chk("ER-H.1 Zero monthly_limit_usd → 400", r.status_code == 400, f"got {r.status_code}")

    # Negative limit rejected
    r2 = _api("post", "/v1/admin/budget-policies", key=key, json={
        "scope": "org",
        "monthly_limit_usd": -100,
    })
    chk("ER-H.2 Negative monthly_limit_usd → 400", r2.status_code == 400, f"got {r2.status_code}")

    # Invalid enforcement value
    r3 = _api("post", "/v1/admin/budget-policies", key=key, json={
        "scope": "org",
        "monthly_limit_usd": 1000,
        "enforcement": "yolo",
    })
    chk("ER-H.3 Invalid enforcement → 400", r3.status_code == 400, f"got {r3.status_code}")

    # team_provider scope without provider_target
    r4 = _api("post", "/v1/admin/budget-policies", key=key, json={
        "scope": "team_provider",
        "scope_target": "claude-team",
        "monthly_limit_usd": 500,
    })
    chk("ER-H.4 team_provider without provider_target → 400", r4.status_code == 400, f"got {r4.status_code}")

    # Malformed JSON body
    resp = requests.post(
        f"{BASE}/v1/admin/budget-policies",
        headers={**_headers(key), "Content-Type": "application/json"},
        data="not json",
        timeout=TIMEOUT,
    )
    chk("ER-H.5 Non-JSON body → 400", resp.status_code == 400, f"got {resp.status_code}")


# ══════════════════════════════════════════════════════════════════════════════
# ER-I: Role invite preservation — ceo/superadmin not silently downgraded
# ══════════════════════════════════════════════════════════════════════════════

def test_role_invite_preservation():
    section("ER-I. Invited role is preserved (no silent downgrade)")

    if skip_no_key():
        return

    key = CI_API_KEY

    for role in ["ceo", "superadmin", "admin", "member", "viewer"]:
        email = f"test-{uuid.uuid4().hex[:8]}@example.com"
        r = requests.post(
            f"{BASE}/v1/auth/members",
            headers=_headers(key),
            json={"email": email, "name": "Role Test", "role": role},
            timeout=TIMEOUT,
        )
        chk(f"ER-I.1 Invite role={role} returns 201", r.status_code in (200, 201), f"got {r.status_code}: {r.text[:120]}")
        if r.status_code in (200, 201):
            returned_role = r.json().get("role")
            chk(f"ER-I.2 Returned role={role} not downgraded", returned_role == role,
                f"expected '{role}', got '{returned_role}'")

    # Admin cannot escalate to superadmin
    admin_key, _ = fresh_member_key(key, role="admin")
    if admin_key:
        escalate_email = f"test-{uuid.uuid4().hex[:8]}@example.com"
        r_esc = requests.post(
            f"{BASE}/v1/auth/members",
            headers=_headers(admin_key),
            json={"email": escalate_email, "name": "Escalation Test", "role": "superadmin"},
            timeout=TIMEOUT,
        )
        if r_esc.status_code in (200, 201):
            returned_role = r_esc.json().get("role")
            chk("ER-I.3 Admin cannot invite superadmin (must downgrade to admin or less)",
                returned_role != "superadmin",
                f"role escalation succeeded — got '{returned_role}'")
        else:
            chk("ER-I.3 Admin cannot invite superadmin (rejected)", True)
    else:
        warn("ER-I.3: Could not get admin key — skipping escalation check")


# ══════════════════════════════════════════════════════════════════════════════
# Runner
# ══════════════════════════════════════════════════════════════════════════════

def run_all():
    print("\n" + "═" * 60)
    print("  Enterprise RBAC + Multi-Team Business Case Tests")
    print("═" * 60)

    test_role_hierarchy()
    test_budget_policies_crud()
    test_executive_endpoint()
    test_developers_team_field()
    test_live_feed_enriched()
    test_developer_recommendations()
    test_team_scoped_member()
    test_budget_policy_validation()
    test_role_invite_preservation()

    results = get_results()
    print(f"\n{'═'*60}")
    print(f"  Passed: {results['passed']}  Failed: {results['failed']}  "
          f"Warned: {results['warned']}  Skipped: {results['skipped']}")
    print("═" * 60 + "\n")
    return results["failed"] == 0


if __name__ == "__main__":
    ok_result = run_all()
    sys.exit(0 if ok_result else 1)