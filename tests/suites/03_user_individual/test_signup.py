"""
test_signup.py — Individual user signup tests
=============================================
Suite SU: Tests all signup scenarios, validation, and response format.
Labels: SU.1 - SU.N
"""

import sys
import requests
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config.settings import API_URL
from helpers.data import rand_email, rand_org, rand_name, rand_tag
from helpers.output import ok, fail, warn, info, section, chk, get_results


def test_valid_signup():
    section("SU. Signup — Valid Cases")

    email = rand_email("su")
    name  = rand_name()
    org   = rand_org("su")

    r = requests.post(f"{API_URL}/v1/auth/signup",
                      json={"email": email, "name": name, "org": org}, timeout=15)
    chk("SU.1  Valid signup → 201", r.status_code == 201,
        f"got {r.status_code}: {r.text[:100]}")

    if r.status_code == 201:
        d = r.json()
        chk("SU.2  Response has api_key",  "api_key" in d)
        chk("SU.3  Response has org_id",   "org_id"  in d)
        chk("SU.4  Response has hint",     "hint"    in d)
        chk("SU.5  api_key starts vnt_",   d.get("api_key", "").startswith("vnt_"),
            f"got: {d.get('api_key', '')[:15]}")
        chk("SU.6  api_key length > 20",   len(d.get("api_key", "")) > 20)
        chk("SU.7  org_id is non-empty",   bool(d.get("org_id", "")))
        chk("SU.8  hint does NOT expose full key",
            d.get("hint", "") != d.get("api_key", ""),
            "hint should be partial key, not full key")
        return d.get("api_key"), email
    else:
        fail("SU.2  Skipping downstream checks")
        for i in range(3, 9):
            fail(f"SU.{i}  Skipping")
        return None, email


def test_duplicate_signup(email):
    section("SU. Signup — Duplicate Email")

    if not email:
        warn("SU.9  No email to test duplicate — skipping")
        return

    r = requests.post(f"{API_URL}/v1/auth/signup",
                      json={"email": email, "name": rand_name(), "org": rand_org()},
                      timeout=15)
    chk("SU.9  Duplicate email → 409", r.status_code == 409,
        f"got {r.status_code}: {r.text[:100]}")

    if r.status_code == 409:
        try:
            d = r.json()
            chk("SU.10 409 response has error field", "error" in d or "message" in d)
        except Exception:
            warn("SU.10 409 response is not JSON")


def test_missing_fields():
    section("SU. Signup — Missing Fields")

    # Missing all fields
    r = requests.post(f"{API_URL}/v1/auth/signup", json={}, timeout=15)
    chk("SU.11 Empty body → 400", r.status_code in (400, 422),
        f"got {r.status_code}")

    # Missing email
    r2 = requests.post(f"{API_URL}/v1/auth/signup",
                       json={"name": rand_name(), "org": rand_org()}, timeout=15)
    chk("SU.12 Missing email → 400", r2.status_code in (400, 422),
        f"got {r2.status_code}")

    # Missing org
    r3 = requests.post(f"{API_URL}/v1/auth/signup",
                       json={"email": rand_email(), "name": rand_name()}, timeout=15)
    chk("SU.13 Missing org → 400/201", r3.status_code in (400, 201, 422),
        f"got {r3.status_code}")

    # Non-JSON body
    r4 = requests.post(f"{API_URL}/v1/auth/signup",
                       data="not json", headers={"Content-Type": "application/json"},
                       timeout=15)
    chk("SU.14 Invalid JSON → 400", r4.status_code in (400, 422),
        f"got {r4.status_code}")


def test_email_format():
    section("SU. Signup — Email Format Validation")

    invalid_emails = [
        ("not-an-email",        "SU.15"),
        ("@nodomain.com",       "SU.16"),
        ("no-at-sign",          "SU.17"),
        ("spaces in@email.com", "SU.18"),
    ]

    for email_val, label in invalid_emails:
        r = requests.post(f"{API_URL}/v1/auth/signup",
                          json={"email": email_val, "name": rand_name(), "org": rand_org()},
                          timeout=15)
        chk(f"{label} Invalid email '{email_val[:20]}' → 400/422",
            r.status_code in (400, 422),
            f"got {r.status_code}")


def test_org_uniqueness():
    section("SU. Signup — Org Name Uniqueness")

    org_name = rand_org("uniq")

    # First signup with this org
    r1 = requests.post(f"{API_URL}/v1/auth/signup",
                       json={"email": rand_email("uniq1"), "name": rand_name(), "org": org_name},
                       timeout=15)
    if r1.status_code != 201:
        warn(f"SU.19 Could not create first org '{org_name}' ({r1.status_code})")
        return

    # Second signup with same org → 409 or 400
    r2 = requests.post(f"{API_URL}/v1/auth/signup",
                       json={"email": rand_email("uniq2"), "name": rand_name(), "org": org_name},
                       timeout=15)
    chk("SU.19 Duplicate org name → 409/400",
        r2.status_code in (400, 409),
        f"got {r2.status_code}: {r2.text[:100]}")


def main():
    section("Suite SU — Individual User Signup Tests")
    info(f"API: {API_URL}")

    api_key, email = test_valid_signup()
    test_duplicate_signup(email)
    test_missing_fields()
    test_email_format()
    test_org_uniqueness()

    results = get_results()
    info(f"Results: {results['passed']} passed, {results['failed']} failed, "
         f"{results['warned']} warned")
    sys.exit(0 if results["failed"] == 0 else 1)


if __name__ == "__main__":
    main()
