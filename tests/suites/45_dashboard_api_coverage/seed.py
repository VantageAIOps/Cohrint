#!/usr/bin/env python3
"""
seed.py — One-time data seeder for Dashboard API Coverage (Suite 45)
======================================================================
Creates four persistent test accounts (admin/member/ceo/superadmin-equivalent),
seeds realistic events across models, and writes credentials to:

    tests/artifacts/da45_seed_state.json   ← machine-readable, loaded by tests
    tests/artifacts/da45_credentials.txt   ← human-readable login cards

BOTH files are gitignored (tests/artifacts/ is never committed).

Usage:
    python tests/suites/45_dashboard_api_coverage/seed.py

Re-running is safe — if state file already exists the script prints the saved
credentials and exits without creating new accounts (pass --force to reset).
"""

import argparse
import json
import random
import sys
import time
import uuid
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# Path bootstrap
# ---------------------------------------------------------------------------
TESTS_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(TESTS_ROOT))

from config.settings import API_URL, CI_SECRET
from helpers.data import rand_tag

ARTIFACTS_DIR = TESTS_ROOT / "artifacts"
STATE_FILE    = ARTIFACTS_DIR / "da45_seed_state.json"
CREDS_FILE    = ARTIFACTS_DIR / "da45_credentials.txt"

SITE_URL = "https://cohrint.com"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _headers(api_key: str) -> dict:
    return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}


def _signup(email: str, name: str, org: str) -> dict:
    hdrs = {"Content-Type": "application/json"}
    if CI_SECRET:
        hdrs["X-Vantage-CI"] = CI_SECRET
    for attempt in range(4):
        r = requests.post(f"{API_URL}/v1/auth/signup",
                          json={"email": email, "name": name, "org": org},
                          headers=hdrs, timeout=20)
        if r.status_code == 201:
            return r.json()
        if r.status_code == 429 and attempt < 3:
            time.sleep(2 ** attempt)
            continue
        raise RuntimeError(f"signup failed {r.status_code}: {r.text[:300]}")
    raise RuntimeError("signup failed after retries")


def _create_team(admin_key: str, name: str) -> str:
    """Create a team and return its team_id."""
    r = requests.post(
        f"{API_URL}/v1/teams",
        json={"name": name},
        headers=_headers(admin_key),
        timeout=20,
    )
    if r.status_code not in (200, 201):
        raise RuntimeError(f"create_team failed: {r.status_code} {r.text[:200]}")
    return r.json()["team_id"]


def _invite_member(admin_key: str, email: str, name: str, role: str,
                   team_id: str | None = None) -> dict:
    """Invite a member to the admin's org and return the response dict."""
    payload: dict = {"email": email, "name": name, "role": role}
    if team_id:
        payload["team_id"] = team_id
    r = requests.post(
        f"{API_URL}/v1/auth/members",
        json=payload,
        headers=_headers(admin_key),
        timeout=20,
    )
    if r.status_code not in (200, 201):
        raise RuntimeError(f"invite failed for {email} ({role}): {r.status_code} {r.text[:200]}")
    return r.json()


def _seed_event(api_key: str, model: str, cost: float, prompt: int, completion: int,
                streaming: bool = False, team: str | None = None,
                cache_read: int = 0, cache_write: int = 0) -> None:
    payload = {
        "event_id":          f"da45-seed-{uuid.uuid4().hex[:12]}",
        "provider":          "anthropic" if "claude" in model else "openai",
        "model":             model,
        "prompt_tokens":     prompt,
        "completion_tokens": completion,
        "cache_tokens":      cache_read,
        "total_cost_usd":    cost,
        "latency_ms":        random.randint(200, 3000),
        "environment":       "test",
        "agent_name":        "da45-seed",
    }
    if streaming:
        payload["streaming"] = True
    if team:
        payload["team"] = team
    if cache_read:
        payload["cache_read_input_tokens"] = cache_read
    if cache_write:
        payload["cache_creation_input_tokens"] = cache_write
    r = requests.post(f"{API_URL}/v1/events", json=payload,
                      headers=_headers(api_key), timeout=15)
    if r.status_code not in (200, 201, 202):
        print(f"  WARN: event ingest returned {r.status_code}: {r.text[:120]}")


EVENT_BATCH = [
    # (model, cost, prompt_tokens, completion_tokens, streaming, team, cache_read, cache_write)
    ("claude-sonnet-4-6", 0.012,  1800, 420, False, "backend",   500,   200),
    ("claude-sonnet-4-6", 0.008,  1200, 300, True,  "backend",   0,     0),
    ("claude-opus-4-6",   0.095,  3500, 900, False, "frontend",  1000,  300),
    ("claude-opus-4-6",   0.074,  2800, 700, True,  "frontend",  0,     0),
    ("claude-haiku-4-5",  0.001,   400, 120, False, "infra",     100,   50),
    ("claude-haiku-4-5",  0.002,   600, 180, True,  "infra",     0,     0),
    ("gpt-4o",            0.022,  2200, 550, False, "data",      0,     0),
    ("gpt-4o",            0.018,  1800, 450, True,  "data",      0,     0),
    ("gpt-4o-mini",       0.003,   800, 200, False, "mobile",    0,     0),
    ("gpt-4o-mini",       0.002,   600, 150, True,  "mobile",    0,     0),
    ("gemini-2.0-flash",  0.005,  1000, 250, False, "ml",        0,     0),
    ("gemini-1.5-pro",    0.015,  2000, 500, False, "ml",        300,   100),
    ("claude-sonnet-4-6", 0.019,  2400, 600, False, "backend",   800,   400),
    ("claude-sonnet-4-6", 0.011,  1600, 380, True,  "backend",   0,     0),
    ("claude-opus-4-6",   0.088,  3200, 800, False, "frontend",  1200,  500),
    ("gpt-4o",            0.031,  2800, 700, False, "data",      0,     0),
    ("claude-haiku-4-5",  0.001,   350, 100, False, "infra",     50,    20),
    ("gpt-4o-mini",       0.004,   900, 220, False, "mobile",    0,     0),
    ("claude-sonnet-4-6", 0.009,  1400, 320, True,  "product",   300,   100),
    ("gemini-2.0-flash",  0.007,  1200, 300, False, "product",   0,     0),
]


def seed_events(api_key: str, label: str = "admin") -> None:
    print(f"  Seeding {len(EVENT_BATCH)} events for {label}...")
    for ev in EVENT_BATCH:
        _seed_event(api_key, *ev)
        time.sleep(0.05)  # avoid rate limit
    time.sleep(1.5)  # propagation pause
    print(f"  ✓ {len(EVENT_BATCH)} events seeded")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def build_state(force: bool = False) -> dict:
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

    if not force and STATE_FILE.exists():
        state = json.loads(STATE_FILE.read_text())
        print(f"State file already exists ({STATE_FILE}). Use --force to re-seed.")
        return state

    tag = rand_tag(6)
    print(f"\n[da45-seed] Creating test org (tag={tag})\n")

    # --- Admin account (org owner, seeds events) ----------------------------
    print("1/4  Creating admin account (org owner)...")
    admin_data = _signup(
        email=f"da45-admin-{tag}@vantage-test.dev",
        name="DA45 Admin",
        org=f"DA45 TestOrg {tag}",
    )
    admin_key = admin_data["api_key"]
    org_id    = admin_data["org_id"]
    print(f"     ✓ admin key={admin_key[:12]}…  org={org_id}")

    # Seed rich event data under the admin key
    seed_events(admin_key, "admin")

    # --- Create a shared team for member invites ----------------------------
    print("    Creating shared team for member invites...")
    try:
        team_id = _create_team(admin_key, f"DA45 Engineering {tag}")
        print(f"     ✓ team_id={team_id}")
    except RuntimeError as e:
        # If team creation isn't required (solo plan), proceed without team_id
        team_id = None
        print(f"     WARN: team creation failed ({e}); inviting without team_id")

    # --- Member account ------------------------------------------------------
    print("2/4  Inviting member account...")
    member_resp = _invite_member(admin_key,
                                 email=f"da45-member-{tag}@vantage-test.dev",
                                 name="DA45 Member",
                                 role="member",
                                 team_id=team_id)
    member_id  = member_resp.get("id") or member_resp.get("member_id", "")
    member_key = member_resp.get("api_key", "")
    print(f"     ✓ member id={member_id}  key={member_key[:12] if member_key else 'n/a'}…")

    # Seed a few events under the member key too (for per-member usage tests)
    if member_key:
        print("     Seeding member events...")
        for ev in EVENT_BATCH[:5]:
            _seed_event(member_key, *ev)
        time.sleep(1)

    # --- CEO account ---------------------------------------------------------
    print("3/4  Inviting CEO account...")
    ceo_resp = _invite_member(admin_key,
                              email=f"da45-ceo-{tag}@vantage-test.dev",
                              name="DA45 CEO",
                              role="ceo",
                              team_id=team_id)
    ceo_id  = ceo_resp.get("id") or ceo_resp.get("member_id", "")
    ceo_key = ceo_resp.get("api_key", "")
    print(f"     ✓ ceo id={ceo_id}  key={ceo_key[:12] if ceo_key else 'n/a'}…")

    # --- Superadmin account --------------------------------------------------
    print("4/4  Inviting superadmin account...")
    sa_resp = _invite_member(admin_key,
                             email=f"da45-superadmin-{tag}@vantage-test.dev",
                             name="DA45 Superadmin",
                             role="superadmin",
                             team_id=team_id)
    sa_id  = sa_resp.get("id") or sa_resp.get("member_id", "")
    sa_key = sa_resp.get("api_key", "")
    print(f"     ✓ superadmin id={sa_id}  key={sa_key[:12] if sa_key else 'n/a'}…")

    state = {
        "tag":        tag,
        "org_id":     org_id,
        "team_id":    team_id,
        "seeded_at":  time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "events_count": len(EVENT_BATCH),
        "admin": {
            "role":    "admin",
            "email":   f"da45-admin-{tag}@vantage-test.dev",
            "name":    "DA45 Admin",
            "api_key": admin_key,
        },
        "member": {
            "role":    "member",
            "id":      member_id,
            "email":   f"da45-member-{tag}@vantage-test.dev",
            "name":    "DA45 Member",
            "api_key": member_key,
        },
        "ceo": {
            "role":    "ceo",
            "id":      ceo_id,
            "email":   f"da45-ceo-{tag}@vantage-test.dev",
            "name":    "DA45 CEO",
            "api_key": ceo_key,
        },
        "superadmin": {
            "role":    "superadmin",
            "id":      sa_id,
            "email":   f"da45-superadmin-{tag}@vantage-test.dev",
            "name":    "DA45 Superadmin",
            "api_key": sa_key,
        },
    }

    STATE_FILE.write_text(json.dumps(state, indent=2))
    print(f"\n✓ State saved → {STATE_FILE}")
    return state


def write_credentials(state: dict) -> None:
    """Write a human-readable credentials card."""
    lines = [
        "=" * 64,
        "  Dashboard Credentials — Suite 45 Test Accounts",
        "  !! NEVER COMMIT THIS FILE !!  (gitignored)",
        "=" * 64,
        f"  Org ID   : {state['org_id']}",
        f"  Tag      : {state['tag']}",
        f"  Seeded   : {state['seeded_at']}  ({state['events_count']} events)",
        f"  Dashboard: {SITE_URL}",
        "",
    ]

    role_order = ["admin", "ceo", "superadmin", "member"]
    for role in role_order:
        acc = state.get(role)
        if not acc:
            continue
        lines += [
            "-" * 64,
            f"  ROLE: {acc['role'].upper()}",
            f"  Name   : {acc['name']}",
            f"  Email  : {acc['email']}",
            f"  API Key: {acc['api_key']}",
            "",
            f"  Login URL:",
            f"    {SITE_URL}/?api_key={acc['api_key']}",
            "",
            f"  curl check:",
            f"    curl -H 'Authorization: Bearer {acc['api_key']}' \\",
            f"         {API_URL}/v1/analytics/kpis",
            "",
        ]

    lines += [
        "=" * 64,
        "  What each role sees",
        "  --------------------",
        "  SUPERADMIN : full dashboard + all admin tabs + cross-platform",
        "  CEO        : full dashboard + spend + members read + benchmarks",
        "  ADMIN      : full dashboard + spend + members + settings",
        "  MEMBER     : overview + cross-platform only (no spend/members)",
        "=" * 64,
    ]

    CREDS_FILE.write_text("\n".join(lines) + "\n")
    print(f"✓ Credentials → {CREDS_FILE}")


def print_summary(state: dict) -> None:
    print("\n" + "=" * 64)
    print("  DA45 Seed Summary")
    print("=" * 64)
    for role in ("admin", "ceo", "superadmin", "member"):
        acc = state.get(role, {})
        key = acc.get("api_key", "")
        print(f"  {role:12s} {acc.get('email','')}")
        print(f"             key={key[:20]}…")
    print(f"\n  Dashboard : {SITE_URL}")
    print(f"  State file: {STATE_FILE}")
    print(f"  Creds file: {CREDS_FILE}")
    print("=" * 64 + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed DA45 dashboard test data")
    parser.add_argument("--force", action="store_true",
                        help="Re-create accounts even if state file exists")
    args = parser.parse_args()

    state = build_state(force=args.force)
    write_credentials(state)
    print_summary(state)


if __name__ == "__main__":
    main()
