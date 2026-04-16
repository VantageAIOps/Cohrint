"""
Test Suite 48 — Prompt Registry MVP
======================================

Tests versioned prompt templates with per-version cost tracking.

  A. Prompt CRUD   (PR.1–PR.10)  — create, read, update, soft-delete
  B. Versions      (PV.1–PV.8)   — version creation, uniqueness, content retrieval
  C. Usage         (PU.1–PU.5)   — POST /v1/prompts/usage cost attribution
  D. Analytics     (PA.1–PA.5)   — GET /v1/prompts/analytics/comparison
  E. Auth & Roles  (AR.1–AR.6)   — admin-only writes, member reads, unauth rejection

Uses da45 persistent seed accounts. Never creates fresh accounts.
All tests hit https://api.cohrint.com (no mocking).
"""

import json
import sys
import uuid
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

# Shared state across tests in session
_prompt_id: str | None = None
_version_id: str | None = None


def _api(method: str, path: str, key: str = ADMIN_KEY, **kwargs) -> requests.Response:
    headers = kwargs.pop("headers", {})
    headers["Authorization"] = f"Bearer {key}"
    return getattr(requests, method)(f"{BASE}{path}", headers=headers, timeout=15, **kwargs)


# ── A. Prompt CRUD ──────────────────────────────────────────────────────────────

class TestPromptCRUD:
    def test_PR01_create_prompt(self):
        """PR.1 — POST /v1/prompts creates a prompt."""
        global _prompt_id
        section("PR.1 — Create prompt")
        name = f"suite48-prompt-{uuid.uuid4().hex[:8]}"
        r = _api("post", "/v1/prompts", json={"name": name, "description": "Suite 48 test prompt"})
        chk("201 Created", r.status_code == 201)
        body = r.json()
        chk("id present", bool(body.get("id")))
        chk("name matches", body.get("name") == name)
        _prompt_id = body["id"]

    def test_PR02_create_with_initial_version(self):
        """PR.2 — Creating prompt with initial_version also creates version 1."""
        section("PR.2 — Create prompt with initial version")
        name = f"suite48-with-v1-{uuid.uuid4().hex[:8]}"
        r = _api("post", "/v1/prompts", json={
            "name": name,
            "initial_version": {
                "content": "You are a helpful assistant. Answer: {{query}}",
                "model": "claude-sonnet-4-6",
                "notes": "Initial version",
            }
        })
        chk("201", r.status_code == 201)
        body = r.json()
        chk("first_version present", body.get("first_version") is not None)
        chk("version_num=1", body["first_version"]["version_num"] == 1)

    def test_PR03_create_duplicate_name_409(self):
        """PR.3 — Duplicate name within org returns 409."""
        section("PR.3 — Duplicate name returns 409")
        assert _prompt_id, "Depends on PR.1"
        r1 = _api("get", f"/v1/prompts/{_prompt_id}")
        name = r1.json()["name"]
        r = _api("post", "/v1/prompts", json={"name": name})
        chk("409 Conflict", r.status_code == 409)

    def test_PR04_create_missing_name_400(self):
        """PR.4 — Missing name returns 400."""
        section("PR.4 — Missing name returns 400")
        r = _api("post", "/v1/prompts", json={"description": "no name"})
        chk("400", r.status_code == 400)

    def test_PR05_list_prompts(self):
        """PR.5 — GET /v1/prompts returns prompts list."""
        section("PR.5 — List prompts")
        r = _api("get", "/v1/prompts")
        chk("200", r.status_code == 200)
        body = r.json()
        chk("prompts array", isinstance(body.get("prompts"), list))

    def test_PR06_get_prompt_by_id(self):
        """PR.6 — GET /v1/prompts/:id returns prompt with versions."""
        section("PR.6 — Get prompt by id")
        assert _prompt_id, "Depends on PR.1"
        r = _api("get", f"/v1/prompts/{_prompt_id}")
        chk("200", r.status_code == 200)
        body = r.json()
        chk("id matches", body.get("id") == _prompt_id)
        chk("versions array", isinstance(body.get("versions"), list))

    def test_PR07_get_nonexistent_404(self):
        """PR.7 — Unknown ID returns 404."""
        section("PR.7 — 404 for unknown prompt")
        r = _api("get", f"/v1/prompts/{uuid.uuid4()}")
        chk("404", r.status_code == 404)

    def test_PR08_patch_prompt(self):
        """PR.8 — PATCH /v1/prompts/:id updates description."""
        section("PR.8 — Patch prompt")
        assert _prompt_id, "Depends on PR.1"
        r = _api("patch", f"/v1/prompts/{_prompt_id}", json={"description": "Updated description"})
        chk("200", r.status_code == 200)
        chk("updated=true", r.json().get("updated") is True)

    def test_PR09_delete_prompt_soft(self):
        """PR.9 — DELETE soft-deletes prompt; subsequent GET returns 404."""
        section("PR.9 — Soft delete")
        name = f"suite48-deleteme-{uuid.uuid4().hex[:8]}"
        created = _api("post", "/v1/prompts", json={"name": name})
        pid = created.json()["id"]
        r = _api("delete", f"/v1/prompts/{pid}")
        chk("200 deleted", r.status_code == 200)
        chk("deleted=true", r.json().get("deleted") is True)
        # GET should now 404
        r2 = _api("get", f"/v1/prompts/{pid}")
        chk("404 after delete", r2.status_code == 404)

    def test_PR10_delete_nonexistent_404(self):
        """PR.10 — DELETE nonexistent ID returns 404."""
        section("PR.10 — Delete nonexistent")
        r = _api("delete", f"/v1/prompts/{uuid.uuid4()}")
        chk("404", r.status_code == 404)


# ── B. Versions ─────────────────────────────────────────────────────────────────

class TestVersions:
    def test_PV01_add_version(self):
        """PV.1 — POST /v1/prompts/:id/versions creates version."""
        global _version_id
        section("PV.1 — Add version")
        assert _prompt_id, "Depends on PR.1"
        r = _api("post", f"/v1/prompts/{_prompt_id}/versions", json={
            "content": "Analyze the following code and identify bugs:\n\n{{code}}",
            "model": "claude-sonnet-4-6",
            "notes": "First test version",
        })
        chk("201", r.status_code == 201)
        body = r.json()
        chk("version_num >= 1", body.get("version_num", 0) >= 1)
        chk("id present", bool(body.get("id")))
        _version_id = body["id"]

    def test_PV02_version_numbers_increment(self):
        """PV.2 — Sequential versions get incrementing numbers."""
        section("PV.2 — Version numbers increment")
        assert _prompt_id, "Depends on PR.1"
        r1 = _api("post", f"/v1/prompts/{_prompt_id}/versions", json={"content": "Version A content"})
        r2 = _api("post", f"/v1/prompts/{_prompt_id}/versions", json={"content": "Version B content"})
        chk("both 201", r1.status_code == 201 and r2.status_code == 201)
        chk("v2 > v1", r2.json()["version_num"] > r1.json()["version_num"])

    def test_PV03_version_missing_content_400(self):
        """PV.3 — Missing content returns 400."""
        section("PV.3 — Missing content")
        assert _prompt_id, "Depends on PR.1"
        r = _api("post", f"/v1/prompts/{_prompt_id}/versions", json={"notes": "no content"})
        chk("400", r.status_code == 400)

    def test_PV04_version_on_nonexistent_prompt_404(self):
        """PV.4 — Adding version to nonexistent prompt returns 404."""
        section("PV.4 — Version on nonexistent prompt")
        r = _api("post", f"/v1/prompts/{uuid.uuid4()}/versions", json={"content": "test"})
        chk("404", r.status_code == 404)

    def test_PV05_get_version_by_id(self):
        """PV.5 — GET /v1/prompts/:id/versions/:versionId returns full content."""
        section("PV.5 — Get version by id")
        assert _prompt_id and _version_id, "Depends on PV.1"
        r = _api("get", f"/v1/prompts/{_prompt_id}/versions/{_version_id}")
        chk("200", r.status_code == 200)
        body = r.json()
        chk("content present", bool(body.get("content")))
        chk("version_num present", "version_num" in body)
        chk("total_calls present", "total_calls" in body)

    def test_PV06_get_version_nonexistent_404(self):
        """PV.6 — Unknown version ID returns 404."""
        section("PV.6 — Unknown version 404")
        assert _prompt_id, "Depends on PR.1"
        r = _api("get", f"/v1/prompts/{_prompt_id}/versions/{uuid.uuid4()}")
        chk("404", r.status_code == 404)

    def test_PV07_get_prompt_shows_version_list(self):
        """PV.7 — GET /v1/prompts/:id shows versions with cost stats."""
        section("PV.7 — Prompt shows version list")
        assert _prompt_id, "Depends on PR.1"
        r = _api("get", f"/v1/prompts/{_prompt_id}")
        body = r.json()
        versions = body.get("versions", [])
        chk("at least one version", len(versions) >= 1)
        v = versions[0]
        chk("version has avg_cost_usd", "avg_cost_usd" in v)
        chk("version has total_calls", "total_calls" in v)

    def test_PV08_member_cannot_add_version(self):
        """PV.8 — Member cannot add versions (admin-only)."""
        section("PV.8 — Member cannot add version")
        assert _prompt_id, "Depends on PR.1"
        r = _api("post", f"/v1/prompts/{_prompt_id}/versions",
                 key=MEMBER_KEY, json={"content": "member attempt"})
        chk("403", r.status_code == 403)


# ── C. Usage Recording ──────────────────────────────────────────────────────────

class TestUsage:
    def test_PU01_record_usage(self):
        """PU.1 — POST /v1/prompts/usage records event attribution."""
        section("PU.1 — Record usage")
        assert _version_id, "Depends on PV.1"
        event_id = str(uuid.uuid4())
        r = _api("post", "/v1/prompts/usage", json={
            "version_id": _version_id,
            "event_id": event_id,
            "cost_usd": 0.0042,
            "prompt_tokens": 150,
            "completion_tokens": 80,
        })
        chk("201", r.status_code == 201)
        chk("recorded=true", r.json().get("recorded") is True)

    def test_PU02_usage_updates_version_stats(self):
        """PU.2 — Recorded usage increments version total_calls."""
        section("PU.2 — Usage updates stats")
        assert _version_id and _prompt_id, "Depends on PV.1"
        before = _api("get", f"/v1/prompts/{_prompt_id}/versions/{_version_id}").json()
        calls_before = before.get("total_calls", 0)
        _api("post", "/v1/prompts/usage", json={
            "version_id": _version_id,
            "event_id": str(uuid.uuid4()),
            "cost_usd": 0.002,
            "prompt_tokens": 100,
            "completion_tokens": 50,
        })
        after = _api("get", f"/v1/prompts/{_prompt_id}/versions/{_version_id}").json()
        chk("total_calls incremented", after.get("total_calls", 0) > calls_before)

    def test_PU03_usage_missing_fields_400(self):
        """PU.3 — Missing version_id or event_id returns 400."""
        section("PU.3 — Usage missing fields")
        r = _api("post", "/v1/prompts/usage", json={"event_id": str(uuid.uuid4())})
        chk("400", r.status_code == 400)

    def test_PU04_usage_nonexistent_version_404(self):
        """PU.4 — Unknown version_id returns 404."""
        section("PU.4 — Nonexistent version")
        r = _api("post", "/v1/prompts/usage", json={
            "version_id": str(uuid.uuid4()),
            "event_id": str(uuid.uuid4()),
        })
        chk("404", r.status_code == 404)

    def test_PU05_member_can_record_usage(self):
        """PU.5 — Member role can record usage (SDK use case)."""
        section("PU.5 — Member records usage")
        assert _version_id, "Depends on PV.1"
        r = _api("post", "/v1/prompts/usage", key=MEMBER_KEY, json={
            "version_id": _version_id,
            "event_id": str(uuid.uuid4()),
            "cost_usd": 0.001,
        })
        chk("201", r.status_code == 201)


# ── D. Analytics ────────────────────────────────────────────────────────────────

class TestAnalytics:
    def test_PA01_comparison_requires_prompt_id(self):
        """PA.1 — comparison endpoint requires prompt_id param."""
        section("PA.1 — comparison requires prompt_id")
        r = _api("get", "/v1/prompts/analytics/comparison")
        chk("400", r.status_code == 400)

    def test_PA02_comparison_nonexistent_prompt_404(self):
        """PA.2 — Unknown prompt_id returns 404."""
        section("PA.2 — comparison 404")
        r = _api("get", f"/v1/prompts/analytics/comparison?prompt_id={uuid.uuid4()}")
        chk("404", r.status_code == 404)

    def test_PA03_comparison_shape(self):
        """PA.3 — Comparison returns prompt + versions with cost_delta."""
        section("PA.3 — Comparison shape")
        assert _prompt_id, "Depends on PR.1"
        r = _api("get", f"/v1/prompts/analytics/comparison?prompt_id={_prompt_id}")
        chk("200", r.status_code == 200)
        body = r.json()
        chk("prompt present", "prompt" in body)
        chk("versions array", isinstance(body.get("versions"), list))

    def test_PA04_comparison_cost_delta_on_v1(self):
        """PA.4 — First version has cost_delta_pct=null (no prior version)."""
        section("PA.4 — v1 delta is null")
        assert _prompt_id, "Depends on PR.1"
        r = _api("get", f"/v1/prompts/analytics/comparison?prompt_id={_prompt_id}")
        versions = r.json().get("versions", [])
        if versions:
            chk("v1 delta null", versions[0].get("cost_delta_pct") is None)

    def test_PA05_member_can_read_comparison(self):
        """PA.5 — Member can read analytics comparison."""
        section("PA.5 — Member reads comparison")
        assert _prompt_id, "Depends on PR.1"
        r = _api("get", f"/v1/prompts/analytics/comparison?prompt_id={_prompt_id}", key=MEMBER_KEY)
        chk("200", r.status_code == 200)


# ── E. Auth & Roles ─────────────────────────────────────────────────────────────

class TestAuthRoles:
    def test_AR01_unauth_list_rejected(self):
        """AR.1 — Unauth GET /v1/prompts returns 401."""
        r = requests.get(f"{BASE}/v1/prompts", timeout=10)
        chk("401", r.status_code == 401)

    def test_AR02_unauth_create_rejected(self):
        """AR.2 — Unauth POST /v1/prompts returns 401."""
        r = requests.post(f"{BASE}/v1/prompts", json={"name": "x"}, timeout=10)
        chk("401", r.status_code == 401)

    def test_AR03_member_can_list(self):
        """AR.3 — Member can list prompts."""
        r = _api("get", "/v1/prompts", key=MEMBER_KEY)
        chk("200", r.status_code == 200)

    def test_AR04_member_cannot_create(self):
        """AR.4 — Member cannot create prompt."""
        r = _api("post", "/v1/prompts", key=MEMBER_KEY, json={"name": f"member-{uuid.uuid4().hex[:6]}"})
        chk("403", r.status_code == 403)

    def test_AR05_member_cannot_delete(self):
        """AR.5 — Member cannot delete prompt."""
        assert _prompt_id, "Depends on PR.1"
        r = _api("delete", f"/v1/prompts/{_prompt_id}", key=MEMBER_KEY)
        chk("403", r.status_code == 403)

    def test_AR06_member_cannot_patch(self):
        """AR.6 — Member cannot patch prompt."""
        assert _prompt_id, "Depends on PR.1"
        r = _api("patch", f"/v1/prompts/{_prompt_id}", key=MEMBER_KEY, json={"description": "hack"})
        chk("403", r.status_code == 403)
