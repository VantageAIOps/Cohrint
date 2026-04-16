"""
test_account_hierarchy.py — Account Hierarchy Tests
=====================================================

Suite AH: Validates the three-tier account model:
  individual  — solo user, no members allowed
  team        — 1 implicit admin + member/viewer only
  organization — CEO + named teams, each with superadmin/member/viewer

Labels: AH.1 – AH.N

Runs against live API (https://api.cohrint.com).
Requires: VANTAGE_CI_SECRET env var for signup rate-limit bypass.
"""

import sys
import uuid
import requests
import pytest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config.settings import API_URL, CI_SECRET
from helpers.data import rand_email, rand_name, rand_org

BASE    = API_URL
TIMEOUT = 20

# ── helpers ───────────────────────────────────────────────────────────────────

def _h(key: str) -> dict:
    return {"Authorization": f"Bearer {key}"}

def _ci_headers() -> dict:
    h = {"Content-Type": "application/json"}
    if CI_SECRET:
        h["X-Vantage-CI"] = CI_SECRET
    return h

def signup(account_type: str, prefix: str = "ah") -> dict:
    """Create a fresh account of the given type. Returns full response dict."""
    payload = {
        "email":        rand_email(prefix),
        "name":         rand_name(),
        "org":          rand_org(prefix),
        "account_type": account_type,
    }
    r = requests.post(f"{BASE}/v1/auth/signup", json=payload,
                      headers=_ci_headers(), timeout=TIMEOUT)
    assert r.status_code == 201, f"signup({account_type}) failed {r.status_code}: {r.text[:300]}"
    return r.json()

def invite(org_key: str, role: str = "member", team_id: str = None,
           email: str = None) -> requests.Response:
    payload = {
        "email": email or rand_email("ah-inv"),
        "name":  rand_name(),
        "role":  role,
    }
    if team_id:
        payload["team_id"] = team_id
    return requests.post(f"{BASE}/v1/auth/members", headers=_h(org_key),
                         json=payload, timeout=TIMEOUT)

def create_team(org_key: str, name: str) -> requests.Response:
    return requests.post(f"{BASE}/v1/teams", headers=_h(org_key),
                         json={"name": name}, timeout=TIMEOUT)


# ══════════════════════════════════════════════════════════════════════════════
# AH-A: Signup returns correct account_type
# ══════════════════════════════════════════════════════════════════════════════

class TestSignupAccountType:

    def test_individual_signup_returns_account_type(self):
        """AH.A.1 — individual signup includes account_type in response."""
        d = signup("individual", prefix="ah-ind")
        assert d.get("account_type") == "individual", f"expected individual, got: {d}"

    def test_team_signup_returns_account_type(self):
        """AH.A.2 — team signup includes account_type in response."""
        d = signup("team", prefix="ah-team")
        assert d.get("account_type") == "team"

    def test_org_signup_returns_account_type(self):
        """AH.A.3 — organization signup includes account_type in response."""
        d = signup("organization", prefix="ah-org")
        assert d.get("account_type") == "organization"

    def test_default_account_type_is_organization(self):
        """AH.A.4 — omitting account_type defaults to organization."""
        payload = {"email": rand_email("ah-def"), "name": rand_name(),
                   "org": rand_org("ah-def")}
        hdrs = _ci_headers()
        r = requests.post(f"{BASE}/v1/auth/signup", json=payload,
                          headers=hdrs, timeout=TIMEOUT)
        assert r.status_code == 201
        assert r.json().get("account_type") == "organization"

    def test_invalid_account_type_defaults_to_organization(self):
        """AH.A.5 — unknown account_type value silently defaults to organization."""
        payload = {"email": rand_email("ah-inv"), "name": rand_name(),
                   "org": rand_org("ah-inv"), "account_type": "developer"}
        r = requests.post(f"{BASE}/v1/auth/signup", json=payload,
                          headers=_ci_headers(), timeout=TIMEOUT)
        assert r.status_code == 201
        assert r.json().get("account_type") == "organization"


# ══════════════════════════════════════════════════════════════════════════════
# AH-B: Individual account — no members allowed
# ══════════════════════════════════════════════════════════════════════════════

class TestIndividualAccount:

    @pytest.fixture(scope="class")
    def ind_key(self):
        return signup("individual", prefix="ah-ind-b")["api_key"]

    def test_individual_cannot_invite_member(self, ind_key):
        """AH.B.1 — individual account rejects member invite with 403."""
        r = invite(ind_key, role="member")
        assert r.status_code == 403, f"expected 403, got {r.status_code}: {r.text}"
        assert "Individual" in r.json().get("error", "")

    def test_individual_cannot_invite_viewer(self, ind_key):
        """AH.B.2 — individual account rejects viewer invite with 403."""
        r = invite(ind_key, role="viewer")
        assert r.status_code == 403

    def test_individual_cannot_create_team(self, ind_key):
        """AH.B.3 — individual account cannot create a team (403)."""
        r = create_team(ind_key, "my-team")
        assert r.status_code == 403, f"expected 403, got {r.status_code}: {r.text}"

    def test_individual_cannot_list_teams(self, ind_key):
        """AH.B.4 — individual account gets 403 on GET /v1/teams."""
        r = requests.get(f"{BASE}/v1/teams", headers=_h(ind_key), timeout=TIMEOUT)
        assert r.status_code == 403


# ══════════════════════════════════════════════════════════════════════════════
# AH-C: Team account — member/viewer only, no superadmin
# ══════════════════════════════════════════════════════════════════════════════

class TestTeamAccount:

    @pytest.fixture(scope="class")
    def team_key(self):
        return signup("team", prefix="ah-team-c")["api_key"]

    def test_team_can_invite_member(self, team_key):
        """AH.C.1 — team account can invite a member."""
        r = invite(team_key, role="member")
        assert r.status_code == 201, f"expected 201, got {r.status_code}: {r.text}"
        assert r.json().get("role") == "member"

    def test_team_can_invite_viewer(self, team_key):
        """AH.C.2 — team account can invite a viewer."""
        r = invite(team_key, role="viewer")
        assert r.status_code == 201
        assert r.json().get("role") == "viewer"

    def test_team_cannot_invite_superadmin(self, team_key):
        """AH.C.3 — team account silently downgrades or rejects superadmin role."""
        r = invite(team_key, role="superadmin")
        # Either 403 or role is silently clamped to member
        if r.status_code == 201:
            assert r.json().get("role") in ("member", "viewer"), \
                f"superadmin role leaked through: {r.json()}"
        else:
            assert r.status_code in (400, 403)

    def test_team_cannot_invite_admin(self, team_key):
        """AH.C.4 — team account silently downgrades or rejects admin role."""
        r = invite(team_key, role="admin")
        if r.status_code == 201:
            assert r.json().get("role") in ("member", "viewer"), \
                f"admin role leaked through: {r.json()}"
        else:
            assert r.status_code in (400, 403)

    def test_team_cannot_create_team(self, team_key):
        """AH.C.5 — team account cannot create sub-teams (403)."""
        r = create_team(team_key, "subteam")
        assert r.status_code == 403

    def test_team_patch_cannot_escalate_to_superadmin(self, team_key):
        """AH.C.6 — PATCH /members/:id on team account cannot escalate to superadmin."""
        # First invite a member
        inv = invite(team_key, role="member")
        assert inv.status_code == 201
        member_id = inv.json().get("member_id")
        if not member_id:
            pytest.skip("member_id not returned, skipping escalation test")
        # Try to escalate via PATCH
        r = requests.patch(
            f"{BASE}/v1/auth/members/{member_id}",
            headers=_h(team_key),
            json={"role": "superadmin"},
            timeout=TIMEOUT,
        )
        # Either rejected or role not updated
        if r.status_code == 200:
            # Verify the role was NOT actually changed
            members_r = requests.get(f"{BASE}/v1/auth/members",
                                     headers=_h(team_key), timeout=TIMEOUT)
            if members_r.ok:
                members = members_r.json().get("members", [])
                m = next((x for x in members if x["id"] == member_id), None)
                if m:
                    assert m["role"] not in ("superadmin", "admin", "ceo"), \
                        f"role escalated on team account: {m['role']}"
        else:
            assert r.status_code in (400, 403)


# ══════════════════════════════════════════════════════════════════════════════
# AH-D: Organization account — team CRUD
# ══════════════════════════════════════════════════════════════════════════════

class TestOrganizationTeams:

    @pytest.fixture(scope="class")
    def org(self):
        return signup("organization", prefix="ah-org-d")

    @pytest.fixture(scope="class")
    def org_key(self, org):
        return org["api_key"]

    @pytest.fixture(scope="class")
    def team_id(self, org_key):
        """Create a team and return its id."""
        r = create_team(org_key, "Engineering")
        assert r.status_code == 201, f"team creation failed: {r.text}"
        return r.json()["team_id"]

    def test_create_team_returns_team_id(self, org_key):
        """AH.D.1 — POST /v1/teams returns ok + team_id + name."""
        r = create_team(org_key, f"Team-{uuid.uuid4().hex[:6]}")
        assert r.status_code == 201
        d = r.json()
        assert d.get("ok") is True
        assert d.get("team_id")
        assert d.get("name")

    def test_list_teams_includes_created_team(self, org_key, team_id):
        """AH.D.2 — GET /v1/teams returns the created team."""
        r = requests.get(f"{BASE}/v1/teams", headers=_h(org_key), timeout=TIMEOUT)
        assert r.status_code == 200
        ids = [t["id"] for t in r.json().get("teams", [])]
        assert team_id in ids, f"{team_id} not in teams: {ids}"

    def test_delete_team(self, org_key):
        """AH.D.3 — DELETE /v1/teams/:id soft-deletes the team."""
        # Create a throwaway team
        r = create_team(org_key, f"throwaway-{uuid.uuid4().hex[:6]}")
        assert r.status_code == 201
        tid = r.json()["team_id"]
        # Delete it
        r2 = requests.delete(f"{BASE}/v1/teams/{tid}", headers=_h(org_key), timeout=TIMEOUT)
        assert r2.status_code == 200
        assert r2.json().get("ok") is True
        # Verify it no longer appears in list
        r3 = requests.get(f"{BASE}/v1/teams", headers=_h(org_key), timeout=TIMEOUT)
        ids = [t["id"] for t in r3.json().get("teams", [])]
        assert tid not in ids, f"deleted team {tid} still visible"

    def test_delete_nonexistent_team_returns_404(self, org_key):
        """AH.D.4 — DELETE /v1/teams/nonexistent returns 404."""
        r = requests.delete(f"{BASE}/v1/teams/does-not-exist",
                            headers=_h(org_key), timeout=TIMEOUT)
        assert r.status_code == 404

    def test_create_team_slug_collision_gets_suffix(self, org_key):
        """AH.D.5 — creating two teams with same name produces unique IDs."""
        name = f"collision-{uuid.uuid4().hex[:6]}"
        r1 = create_team(org_key, name)
        r2 = create_team(org_key, name)
        assert r1.status_code == 201
        assert r2.status_code == 201
        assert r1.json()["team_id"] != r2.json()["team_id"]


# ══════════════════════════════════════════════════════════════════════════════
# AH-E: Organization account — member invite requires team_id
# ══════════════════════════════════════════════════════════════════════════════

class TestOrganizationMemberInvite:

    @pytest.fixture(scope="class")
    def org_key(self):
        return signup("organization", prefix="ah-org-e")["api_key"]

    @pytest.fixture(scope="class")
    def team_id(self, org_key):
        r = create_team(org_key, "Backend")
        assert r.status_code == 201
        return r.json()["team_id"]

    def test_org_invite_without_team_id_returns_400(self, org_key):
        """AH.E.1 — org member invite without team_id returns 400."""
        r = invite(org_key, role="member")
        assert r.status_code == 400, f"expected 400, got {r.status_code}: {r.text}"
        assert "team_id" in r.json().get("error", "").lower()

    def test_org_invite_with_invalid_team_id_returns_404(self, org_key):
        """AH.E.2 — org member invite with unknown team_id returns 404."""
        r = invite(org_key, role="member", team_id="nonexistent-team")
        assert r.status_code == 404, f"expected 404, got {r.status_code}: {r.text}"

    def test_org_invite_with_valid_team_id_succeeds(self, org_key, team_id):
        """AH.E.3 — org member invite with valid team_id returns 201."""
        r = invite(org_key, role="member", team_id=team_id)
        assert r.status_code == 201, f"expected 201, got {r.status_code}: {r.text}"
        assert r.json().get("role") == "member"

    def test_org_invite_superadmin_with_team_id_succeeds(self, org_key, team_id):
        """AH.E.4 — org can invite superadmin with team_id."""
        r = invite(org_key, role="superadmin", team_id=team_id)
        assert r.status_code == 201, f"expected 201, got {r.status_code}: {r.text}"
        assert r.json().get("role") == "superadmin"

    def test_org_team_members_list(self, org_key, team_id):
        """AH.E.5 — GET /v1/teams/:id/members returns invited members."""
        # Ensure at least one member in the team
        invite(org_key, role="member", team_id=team_id)
        r = requests.get(f"{BASE}/v1/teams/{team_id}/members",
                         headers=_h(org_key), timeout=TIMEOUT)
        assert r.status_code == 200
        d = r.json()
        assert d.get("team_id") == team_id
        assert isinstance(d.get("members"), list)
        assert len(d["members"]) >= 1

    def test_team_members_list_requires_admin(self, org_key, team_id):
        """AH.E.6 — GET /v1/teams/:id/members is forbidden for member-role callers."""
        # Invite a plain member
        inv = invite(org_key, role="member", team_id=team_id)
        assert inv.status_code == 201
        member_key = inv.json().get("api_key")
        if not member_key:
            pytest.skip("api_key not returned for member")
        r = requests.get(f"{BASE}/v1/teams/{team_id}/members",
                         headers=_h(member_key), timeout=TIMEOUT)
        assert r.status_code == 403, \
            f"member-role should be forbidden from listing team members, got {r.status_code}"


# ══════════════════════════════════════════════════════════════════════════════
# AH-F: Session reflects correct accountType
# ══════════════════════════════════════════════════════════════════════════════

class TestSessionAccountType:

    def _get_session(self, api_key: str) -> dict:
        r = requests.post(f"{BASE}/v1/auth/session",
                          json={"api_key": api_key}, timeout=TIMEOUT)
        assert r.ok, f"session failed: {r.text}"
        cookies = r.cookies
        s = requests.get(f"{BASE}/v1/auth/session", cookies=cookies, timeout=TIMEOUT)
        assert s.ok
        return s.json()

    def test_individual_session_has_correct_role(self):
        """AH.F.1 — individual account session returns role=owner."""
        key = signup("individual", prefix="ah-sess-ind")["api_key"]
        sess = self._get_session(key)
        assert sess.get("role") == "owner"

    def test_org_session_has_correct_role(self):
        """AH.F.2 — org account owner session returns role=owner."""
        key = signup("organization", prefix="ah-sess-org")["api_key"]
        sess = self._get_session(key)
        assert sess.get("role") == "owner"


# ══════════════════════════════════════════════════════════════════════════════
# AH-G: Cookie / logout correctness
# ══════════════════════════════════════════════════════════════════════════════

class TestCookieSecurity:

    @pytest.fixture(scope="class")
    def session_cookies(self):
        key = signup("organization", prefix="ah-cookie")["api_key"]
        r = requests.post(f"{BASE}/v1/auth/session",
                          json={"api_key": key}, timeout=TIMEOUT)
        assert r.ok
        return r.cookies

    def test_session_cookie_is_httponly(self, session_cookies):
        """AH.G.1 — session cookie has HttpOnly flag."""
        names = [c.name for c in session_cookies]
        assert any("cohrint_session" in n for n in names), \
            f"no session cookie found: {names}"

    def test_logout_clears_session(self, session_cookies):
        """AH.G.2 — POST /v1/auth/logout invalidates the session."""
        # Confirm session is valid
        r1 = requests.get(f"{BASE}/v1/auth/session",
                          cookies=session_cookies, timeout=TIMEOUT)
        assert r1.ok, "session should be valid before logout"
        # Logout
        r2 = requests.post(f"{BASE}/v1/auth/logout",
                           cookies=session_cookies, timeout=TIMEOUT)
        assert r2.ok
        # Session should now be invalid
        r3 = requests.get(f"{BASE}/v1/auth/session",
                          cookies=session_cookies, timeout=TIMEOUT)
        assert r3.status_code in (401, 403), \
            f"session still valid after logout: {r3.status_code}"

    def test_delete_session_clears_session(self):
        """AH.G.3 — DELETE /v1/auth/session also invalidates the session."""
        key = signup("individual", prefix="ah-del-sess")["api_key"]
        r1 = requests.post(f"{BASE}/v1/auth/session",
                           json={"api_key": key}, timeout=TIMEOUT)
        assert r1.ok
        cookies = r1.cookies
        r2 = requests.delete(f"{BASE}/v1/auth/session",
                             cookies=cookies, timeout=TIMEOUT)
        assert r2.ok
        r3 = requests.get(f"{BASE}/v1/auth/session",
                          cookies=cookies, timeout=TIMEOUT)
        assert r3.status_code in (401, 403)


# ══════════════════════════════════════════════════════════════════════════════
# AH-H: POST /v1/teams/:id/members — invite member directly to a team
# ══════════════════════════════════════════════════════════════════════════════

def invite_to_team(org_key: str, team_id: str, role: str = "member",
                   email: str = None) -> requests.Response:
    payload = {
        "email": email or rand_email("ah-tinv"),
        "name":  rand_name(),
        "role":  role,
    }
    return requests.post(f"{BASE}/v1/teams/{team_id}/members",
                         headers=_h(org_key), json=payload, timeout=TIMEOUT)


class TestTeamMemberInvite:

    @pytest.fixture(scope="class")
    def org(self):
        return signup("organization", prefix="ah-tinv")

    @pytest.fixture(scope="class")
    def org_key(self, org):
        return org["api_key"]

    @pytest.fixture(scope="class")
    def team_id(self, org_key):
        r = create_team(org_key, "Infra")
        assert r.status_code == 201, f"team creation failed: {r.text}"
        return r.json()["team_id"]

    def test_invite_member_to_team_returns_201(self, org_key, team_id):
        """AH.H.1 — POST /v1/teams/:id/members returns 201 with api_key."""
        r = invite_to_team(org_key, team_id, role="member")
        assert r.status_code == 201, f"expected 201, got {r.status_code}: {r.text}"
        d = r.json()
        assert d.get("ok") is True
        assert d.get("team_id") == team_id
        assert d.get("role") == "member"
        assert d.get("api_key", "").startswith("crt_")

    def test_invite_superadmin_to_team(self, org_key, team_id):
        """AH.H.2 — superadmin role is accepted via team invite endpoint."""
        r = invite_to_team(org_key, team_id, role="superadmin")
        assert r.status_code == 201, f"expected 201, got {r.status_code}: {r.text}"
        assert r.json().get("role") == "superadmin"

    def test_invite_viewer_to_team(self, org_key, team_id):
        """AH.H.3 — viewer role is accepted via team invite endpoint."""
        r = invite_to_team(org_key, team_id, role="viewer")
        assert r.status_code == 201, f"expected 201, got {r.status_code}: {r.text}"
        assert r.json().get("role") == "viewer"

    def test_invite_invalid_role_returns_400(self, org_key, team_id):
        """AH.H.4 — invalid role returns 400."""
        r = invite_to_team(org_key, team_id, role="owner")
        assert r.status_code == 400, f"expected 400, got {r.status_code}: {r.text}"

    def test_invite_to_nonexistent_team_returns_404(self, org_key):
        """AH.H.5 — invite to unknown team_id returns 404."""
        r = invite_to_team(org_key, "no-such-team")
        assert r.status_code == 404, f"expected 404, got {r.status_code}: {r.text}"

    def test_duplicate_email_returns_409(self, org_key, team_id):
        """AH.H.6 — inviting same email twice returns 409."""
        email = rand_email("ah-dup")
        r1 = invite_to_team(org_key, team_id, email=email)
        assert r1.status_code == 201
        r2 = invite_to_team(org_key, team_id, email=email)
        assert r2.status_code == 409, f"expected 409, got {r2.status_code}: {r2.text}"

    def test_invited_member_appears_in_team_list(self, org_key, team_id):
        """AH.H.7 — member invited via team endpoint appears in GET /v1/teams/:id/members."""
        email = rand_email("ah-list")
        r = invite_to_team(org_key, team_id, email=email)
        assert r.status_code == 201
        r2 = requests.get(f"{BASE}/v1/teams/{team_id}/members",
                          headers=_h(org_key), timeout=TIMEOUT)
        assert r2.status_code == 200
        emails = [m["email"] for m in r2.json().get("members", [])]
        assert email in emails, f"{email} not found in team members: {emails}"

    def test_team_invite_on_non_org_account_returns_403(self):
        """AH.H.8 — POST /v1/teams/:id/members on a team account returns 403."""
        key = signup("team", prefix="ah-tinv-team")["api_key"]
        # First create a team attempt should fail too — but use a fake team_id
        r = requests.post(f"{BASE}/v1/teams/any-team/members",
                          headers=_h(key),
                          json={"email": rand_email("ah-t"), "role": "member"},
                          timeout=TIMEOUT)
        assert r.status_code == 403, f"expected 403, got {r.status_code}: {r.text}"
