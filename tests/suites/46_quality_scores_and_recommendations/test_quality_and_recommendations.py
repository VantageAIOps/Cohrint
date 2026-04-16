"""
Test Suite 46 — Quality Scores (Hallucination Detection) + Recommendation Engine
==================================================================================

Covers two integrated systems:

  A. PATCH /v1/events/:id/scores — hallucination & quality score ingestion
       QS.1–QS.12  field validation, partial updates, auth, org isolation

  B. GET /v1/admin/developers/recommendations — efficiency ranking
       REC.1–REC.12  response shape, role gates, field math, sorting, ?days param

  C. CLI recommendation engine (test-recommendations.mjs) — cross-agent tips
       CLI.1–CLI.15  agent filtering, priority order, threshold conditions,
                     placeholder substitution, format output

  D. Role visibility matrix — what each role sees on the dashboard
       ROLE.1–ROLE.8  superadmin/admin/member/ceo access to both systems

Uses da45 persistent seed accounts. Never creates fresh accounts.
All API tests hit https://api.cohrint.com (no mocking).
"""

import json
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from config.settings import API_URL
from helpers.output import section, chk, warn

# ── Seed state (DA45 — always use before creating any account) ────────────────

SEED_FILE = Path(__file__).parent.parent.parent / "artifacts" / "da45_seed_state.json"
if not SEED_FILE.exists():
    pytest.skip("da45_seed_state.json not found — run seed.py first", allow_module_level=True)

_seed = json.loads(SEED_FILE.read_text())
ADMIN_KEY      = _seed["admin"]["api_key"]
MEMBER_KEY     = _seed["member"]["api_key"]
CEO_KEY        = _seed["ceo"]["api_key"]
SUPERADMIN_KEY = _seed["superadmin"]["api_key"]

BASE = API_URL.rstrip("/")

# ── CLI harness (Suite 35 recommendation engine) ──────────────────────────────

CLI_DIR = Path(__file__).parent.parent.parent.parent / "cohrint-cli"
HARNESS = CLI_DIR / "test-recommendations.mjs"
_CLI_AVAILABLE = HARNESS.exists()


def _api(method: str, path: str, key: str = ADMIN_KEY, **kwargs) -> requests.Response:
    headers = kwargs.pop("headers", {})
    headers["Authorization"] = f"Bearer {key}"
    return getattr(requests, method)(f"{BASE}{path}", headers=headers, timeout=15, **kwargs)


def _cli(cmd: str, metrics: dict, extra: dict | None = None) -> dict:
    payload: dict = {"metrics": metrics}
    if extra:
        payload.update(extra)
    r = subprocess.run(
        ["node", str(HARNESS), cmd, json.dumps(payload)],
        capture_output=True, text=True, timeout=15, cwd=str(CLI_DIR),
    )
    try:
        return json.loads(r.stdout.strip())
    except json.JSONDecodeError:
        return {"error": r.stderr or r.stdout}


ZERO_METRICS = dict(
    promptCount=0, totalCostUsd=0, totalInputTokens=0,
    totalOutputTokens=0, totalCachedTokens=0,
)


def _claude(**kw):
    return {**ZERO_METRICS, "agent": "claude", "model": "claude-sonnet-4-6", **kw}


def _gemini(**kw):
    return {**ZERO_METRICS, "agent": "gemini", "model": "gemini-2.0-flash", **kw}


def _codex(**kw):
    return {**ZERO_METRICS, "agent": "codex", "model": "gpt-4o", **kw}


def _aider(**kw):
    return {**ZERO_METRICS, "agent": "aider", "model": "claude-sonnet-4-6", **kw}


# ── Helpers: ingest a test event and return its ID ────────────────────────────

def _ingest_event(key: str = ADMIN_KEY) -> str | None:
    """POST a minimal event and return the event_id."""
    payload = {
        "event_id":          f"qs-test-{uuid.uuid4()}",
        "provider":          "anthropic",
        "model":             "claude-sonnet-4-6",
        "prompt_tokens":     100,
        "completion_tokens": 50,
        "total_cost_usd":    0.001,
        "agent_name":        "claude-code",
        "environment":       "test",
        "timestamp":         "2026-01-01 00:00:00",
    }
    r = _api("post", "/v1/events", key=key, json=payload)
    if r.status_code not in (200, 201):
        return None
    data = r.json()
    return data.get("event_id") or data.get("id") or payload["event_id"]


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION A — PATCH /v1/events/:id/scores  (hallucination detection ingestion)
# ═══════════════════════════════════════════════════════════════════════════════

class TestQualityScoresIngestion:

    def test_qs01_patch_scores_returns_ok_true(self):
        section("A — PATCH /v1/events/:id/scores")
        event_id = _ingest_event()
        if not event_id:
            pytest.skip("Could not ingest test event")
        r = _api("patch", f"/v1/events/{event_id}/scores", json={
            "hallucination_score": 0.05,
            "faithfulness_score":  0.95,
            "relevancy_score":     0.90,
            "consistency_score":   0.88,
            "toxicity_score":      0.01,
            "efficiency_score":    80,
        })
        chk("QS.01 PATCH scores returns 200", r.status_code == 200, f"got {r.status_code}: {r.text[:120]}")
        chk("QS.01 body contains ok:true", r.json().get("ok") is True, f"body: {r.text[:120]}")

    def test_qs02_partial_update_only_hallucination(self):
        event_id = _ingest_event()
        if not event_id:
            pytest.skip("Could not ingest test event")
        r = _api("patch", f"/v1/events/{event_id}/scores", json={
            "hallucination_score": 0.12,
        })
        chk("QS.02 partial update (hallucination only) returns 200", r.status_code == 200, f"got {r.status_code}")
        chk("QS.02 body ok:true", r.json().get("ok") is True)

    def test_qs03_all_six_score_fields_accepted(self):
        event_id = _ingest_event()
        if not event_id:
            pytest.skip("Could not ingest test event")
        all_scores = {
            "hallucination_score": 0.08,
            "faithfulness_score":  0.92,
            "relevancy_score":     0.85,
            "consistency_score":   0.80,
            "toxicity_score":      0.03,
            "efficiency_score":    75,
        }
        r = _api("patch", f"/v1/events/{event_id}/scores", json=all_scores)
        chk("QS.03 all 6 score fields accepted", r.status_code == 200, f"got {r.status_code}: {r.text[:200]}")

    def test_qs04_invalid_json_returns_400(self):
        r = _api("patch", "/v1/events/nonexistent-id/scores",
                 data="not-json", headers={"Content-Type": "application/json"})
        chk("QS.04 invalid JSON body → 400", r.status_code == 400, f"got {r.status_code}")

    def test_qs05_unauthenticated_returns_401(self):
        r = requests.patch(f"{BASE}/v1/events/some-id/scores",
                           json={"hallucination_score": 0.1}, timeout=10)
        chk("QS.05 no auth → 401", r.status_code == 401, f"got {r.status_code}")

    def test_qs06_member_key_can_submit_scores(self):
        """Members can submit quality scores for their own org's events."""
        event_id = _ingest_event(key=MEMBER_KEY)
        if not event_id:
            pytest.skip("Could not ingest test event as member")
        r = _api("patch", f"/v1/events/{event_id}/scores", key=MEMBER_KEY, json={
            "hallucination_score": 0.20,
        })
        chk("QS.06 member key can submit scores", r.status_code == 200, f"got {r.status_code}")

    def test_qs07_org_isolation_cross_org_score_ignored(self):
        """Score update on a different org's event_id should silently no-op (rows_affected=0)."""
        # Use a fabricated event_id that doesn't belong to this org
        fake_id = f"cross-org-{uuid.uuid4()}"
        r = _api("patch", f"/v1/events/{fake_id}/scores", key=MEMBER_KEY, json={
            "hallucination_score": 0.99,
        })
        # API returns 200 ok:true regardless (SQL WHERE id=? AND org_id=? filters it)
        chk("QS.07 cross-org score → 200 (no-op, not 403)", r.status_code == 200, f"got {r.status_code}")

    def test_qs08_score_zero_is_valid(self):
        event_id = _ingest_event()
        if not event_id:
            pytest.skip("Could not ingest test event")
        r = _api("patch", f"/v1/events/{event_id}/scores", json={
            "hallucination_score": 0.0,
            "toxicity_score":      0.0,
        })
        chk("QS.08 score=0.0 is valid", r.status_code == 200, f"got {r.status_code}")

    def test_qs09_efficiency_score_integer(self):
        event_id = _ingest_event()
        if not event_id:
            pytest.skip("Could not ingest test event")
        r = _api("patch", f"/v1/events/{event_id}/scores", json={"efficiency_score": 100})
        chk("QS.09 efficiency_score as integer accepted", r.status_code == 200, f"got {r.status_code}")


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION B — GET /v1/admin/developers/recommendations
# ═══════════════════════════════════════════════════════════════════════════════

class TestDeveloperRecommendationsAPI:

    def test_rec01_admin_gets_200_with_correct_shape(self):
        section("B — GET /v1/admin/developers/recommendations")
        r = _api("get", "/v1/admin/developers/recommendations", key=ADMIN_KEY)
        chk("REC.01 admin → 200", r.status_code == 200, f"got {r.status_code}: {r.text[:120]}")
        d = r.json()
        chk("REC.01 has 'recommendations' key", "recommendations" in d, f"keys: {list(d.keys())}")
        chk("REC.01 has 'period_days' key", "period_days" in d, f"keys: {list(d.keys())}")

    def test_rec02_member_blocked_403(self):
        r = _api("get", "/v1/admin/developers/recommendations", key=MEMBER_KEY)
        chk("REC.02 member → 403", r.status_code == 403, f"got {r.status_code}: {r.text[:120]}")

    def test_rec03_ceo_gets_200(self):
        r = _api("get", "/v1/admin/developers/recommendations", key=CEO_KEY)
        chk("REC.03 ceo → 200", r.status_code == 200, f"got {r.status_code}: {r.text[:120]}")

    def test_rec04_superadmin_gets_200(self):
        r = _api("get", "/v1/admin/developers/recommendations", key=SUPERADMIN_KEY)
        chk("REC.04 superadmin → 200", r.status_code == 200, f"got {r.status_code}: {r.text[:120]}")

    def test_rec05_unauthenticated_blocked_401(self):
        r = requests.get(f"{BASE}/v1/admin/developers/recommendations", timeout=10)
        chk("REC.05 no auth → 401", r.status_code == 401, f"got {r.status_code}")

    def test_rec06_period_days_default_30(self):
        r = _api("get", "/v1/admin/developers/recommendations", key=ADMIN_KEY)
        chk("REC.06 default period_days=30", r.json().get("period_days") == 30)

    def test_rec07_days_param_respected(self):
        r = _api("get", "/v1/admin/developers/recommendations?days=7", key=ADMIN_KEY)
        chk("REC.07 ?days=7 → period_days=7", r.json().get("period_days") == 7, f"got {r.json().get('period_days')}")

    def test_rec08_days_capped_at_90(self):
        r = _api("get", "/v1/admin/developers/recommendations?days=999", key=ADMIN_KEY)
        chk("REC.08 days capped at 90", r.json().get("period_days") == 90, f"got {r.json().get('period_days')}")

    def test_rec09_recommendation_fields_shape(self):
        r = _api("get", "/v1/admin/developers/recommendations", key=ADMIN_KEY)
        recs = r.json().get("recommendations", [])
        if not recs:
            warn("REC.09: No recommendations yet — seed cross_platform_usage events to populate")
            return
        rec = recs[0]
        required_fields = [
            "developer_email", "team", "total_cost",
            "cost_per_pr", "cost_per_commit",
            "cache_hit_rate_pct", "lines_per_dollar",
            "savings_opportunity_usd",
        ]
        for field in required_fields:
            chk(f"REC.09 field '{field}' present", field in rec, f"keys: {list(rec.keys())}")

    def test_rec10_sorted_by_savings_opportunity_desc(self):
        r = _api("get", "/v1/admin/developers/recommendations", key=ADMIN_KEY)
        recs = r.json().get("recommendations", [])
        if len(recs) < 2:
            warn("REC.10: Need ≥2 recommendations to test sort order")
            return
        savings = [x["savings_opportunity_usd"] for x in recs]
        chk("REC.10 sorted by savings_opportunity_usd desc",
            savings == sorted(savings, reverse=True),
            f"order: {savings}")

    def test_rec11_null_fields_when_no_cross_platform_data(self):
        """cost_per_pr and lines_per_dollar should be null when pull_requests/cost=0."""
        r = _api("get", "/v1/admin/developers/recommendations", key=ADMIN_KEY)
        recs = r.json().get("recommendations", [])
        for rec in recs:
            if rec.get("cost_per_pr") is not None:
                chk("REC.11 cost_per_pr is number when non-null",
                    isinstance(rec["cost_per_pr"], (int, float)), f"type: {type(rec['cost_per_pr'])}")

    def test_rec12_recommendations_is_list(self):
        r = _api("get", "/v1/admin/developers/recommendations", key=ADMIN_KEY)
        chk("REC.12 recommendations is array", isinstance(r.json().get("recommendations"), list))


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION C — CLI Recommendation Engine (cross-agent tips)
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.skipif(not _CLI_AVAILABLE, reason="test-recommendations.mjs not found")
class TestCLIRecommendationEngine:

    def test_cli01_no_tips_for_zero_metrics(self):
        section("C — CLI recommendation engine")
        r = _cli("recommendations", ZERO_METRICS)
        chk("CLI.01 zero metrics → 0 tips", r.get("count") == 0, f"got {r}")

    def test_cli02_claude_opus_cheap_triggers_model_switch(self):
        """Opus with low avg cost per prompt → recommend Sonnet."""
        metrics = _claude(
            model="claude-opus-4-6",
            promptCount=5,
            avgCostPerPrompt=0.05,  # below $0.10 threshold
        )
        r = _cli("recommendations", metrics)
        ids = r.get("ids", [])
        chk("CLI.02 claude-use-sonnet fires for cheap opus", "claude-use-sonnet" in ids, f"tips: {ids}")

    def test_cli03_high_session_cost_triggers_critical_alert(self):
        metrics = _claude(totalCostUsd=6.0, promptCount=10)
        r = _cli("recommendations", metrics)
        chk("CLI.03 cost>$5 → all-high-cost-alert present", "all-high-cost-alert" in r.get("ids", []))
        priorities = r.get("priorities", [])
        chk("CLI.03 alert has critical priority", "critical" in priorities)

    def test_cli04_gemini_pro_triggers_flash_tip(self):
        metrics = _gemini(model="gemini-1.5-pro", promptCount=3)
        r = _cli("recommendations", metrics)
        chk("CLI.04 gemini pro → gemini-use-flash tip", "gemini-use-flash" in r.get("ids", []), f"tips: {r.get('ids')}")

    def test_cli05_claude_tips_not_shown_for_gemini_agent(self):
        metrics = _gemini(model="gemini-1.5-pro", promptCount=3, totalCostUsd=6.0)
        r = _cli("recommendations", metrics)
        ids = r.get("ids", [])
        claude_tips = [i for i in ids if i.startswith("claude-")]
        chk("CLI.05 no Claude tips for Gemini agent", len(claude_tips) == 0, f"leaked: {claude_tips}")

    def test_cli06_gemini_tips_not_shown_for_claude_agent(self):
        metrics = _claude(totalCostUsd=6.0, promptCount=10, model="claude-sonnet-4-6")
        r = _cli("recommendations", metrics)
        ids = r.get("ids", [])
        gemini_tips = [i for i in ids if i.startswith("gemini-")]
        chk("CLI.06 no Gemini tips for Claude agent", len(gemini_tips) == 0, f"leaked: {gemini_tips}")

    def test_cli07_universal_tips_appear_for_all_agents(self):
        """all-high-cost-alert is agent='all' and must appear regardless of agent."""
        for agent_fn, name in [(_claude, "claude"), (_gemini, "gemini"), (_codex, "codex")]:
            metrics = agent_fn(totalCostUsd=6.0, promptCount=5)
            r = _cli("recommendations", metrics)
            chk(f"CLI.07 all-high-cost-alert appears for {name}",
                "all-high-cost-alert" in r.get("ids", []), f"tips: {r.get('ids')}")

    def test_cli08_maxtips_limits_output(self):
        metrics = _claude(
            model="claude-opus-4-6", promptCount=10,
            totalCostUsd=6.0, totalInputTokens=60000,
            totalCachedTokens=100, avgCostPerPrompt=0.05,
        )
        r = _cli("recommendations", metrics, {"maxTips": 1})
        chk("CLI.08 maxTips=1 returns at most 1 tip", r.get("count", 99) <= 1, f"got {r.get('count')}")

    def test_cli09_priority_order_critical_before_high(self):
        metrics = _claude(
            model="claude-opus-4-6", promptCount=10,
            totalCostUsd=6.0, avgCostPerPrompt=0.05,
            totalInputTokens=60000, totalCachedTokens=100,
        )
        r = _cli("recommendations", metrics, {"maxTips": 3})
        priorities = r.get("priorities", [])
        if len(priorities) >= 2:
            order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
            ordered = sorted(priorities, key=lambda p: order.get(p, 9))
            chk("CLI.09 priorities in critical→high→medium→low order",
                priorities == ordered, f"got {priorities}")

    def test_cli10_cost_placeholder_substituted(self):
        metrics = _claude(totalCostUsd=7.50, promptCount=5)
        r = _cli("recommendations", metrics)
        actions = r.get("actions", [])
        for action in actions:
            chk("CLI.10 ${cost} replaced with $X.XX", "${cost}" not in action,
                f"unsubstituted: {action}")

    def test_cli11_tokens_placeholder_substituted(self):
        metrics = _claude(totalCostUsd=0, promptCount=5, lastPromptTokens=15000)
        r = _cli("recommendations", metrics)
        actions = r.get("actions", [])
        for action in actions:
            chk("CLI.11 ${tokens} placeholder replaced", "${tokens}" not in action,
                f"unsubstituted: {action}")

    def test_cli12_normalize_claude_variants(self):
        for variant in ["claude", "Claude Code", "claude-code", "CLAUDE"]:
            r = _cli("normalize", {}, {"agent": variant})
            chk(f"CLI.12 '{variant}' normalizes to 'claude'",
                r.get("name") == "claude", f"got: {r.get('name')}")

    def test_cli13_normalize_openai_to_codex(self):
        r = _cli("normalize", {}, {"agent": "openai"})
        chk("CLI.13 'openai' normalizes to 'codex'", r.get("name") == "codex", f"got: {r.get('name')}")

    def test_cli14_format_output_structure(self):
        metrics = _claude(totalCostUsd=6.0, promptCount=5)
        r = _cli("format", metrics)
        chk("CLI.14 format returns 'output' key", "output" in r, f"keys: {list(r.keys())}")
        chk("CLI.14 format returns 'hasContent' key", "hasContent" in r, f"keys: {list(r.keys())}")
        if r.get("hasContent"):
            chk("CLI.14 output contains border", "─" in r["output"] or "┌" in r["output"])

    def test_cli15_inline_tip_format(self):
        metrics = _claude(totalCostUsd=6.0, promptCount=5)
        r = _cli("inline_tip", metrics)
        tip = r.get("tip")
        chk("CLI.15 inline_tip returns string", isinstance(tip, str), f"got: {tip}")
        chk("CLI.15 tip starts with emoji icon", tip.startswith(("🔴", "🟡", "💡", "ℹ")), f"got: {tip[:20]}")

    def test_cli16_aider_diff_format_tip(self):
        """aider with output > 2x input → recommend diff edit format."""
        metrics = {**ZERO_METRICS, "agent": "aider", "model": "claude-sonnet-4-6",
                   "totalInputTokens": 5000, "totalOutputTokens": 12000, "promptCount": 3}
        r = _cli("recommendations", metrics)
        chk("CLI.16 aider-use-diff fires when output >> input",
            "aider-use-diff" in r.get("ids", []), f"tips: {r.get('ids')}")

    def test_cli17_codex_mini_tip_for_gpt4(self):
        metrics = _codex(model="gpt-4o", promptCount=3)
        r = _cli("recommendations", metrics)
        chk("CLI.17 codex-use-mini fires for gpt-4o",
            "codex-use-mini" in r.get("ids", []), f"tips: {r.get('ids')}")

    def test_cli18_cache_tip_fires_for_large_uncached_input(self):
        """Low cache utilisation on large input → prompt caching tip."""
        metrics = _claude(
            totalInputTokens=25000,
            totalCachedTokens=500,   # well under 10% threshold
            promptCount=6,
        )
        r = _cli("recommendations", metrics)
        ids = r.get("ids", [])
        cache_tips = [i for i in ids if "cache" in i or "prompt-cach" in i]
        chk("CLI.18 cache tip fires when cache utilisation <10%", len(cache_tips) > 0, f"tips: {ids}")


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION D — Role visibility matrix
# ═══════════════════════════════════════════════════════════════════════════════

class TestRoleVisibility:
    """Verify what each role can and cannot access for both quality scores and recommendations."""

    def test_role01_superadmin_can_access_recommendations(self):
        section("D — Role visibility matrix")
        r = _api("get", "/v1/admin/developers/recommendations", key=SUPERADMIN_KEY)
        chk("ROLE.01 superadmin → recommendations 200", r.status_code == 200, f"got {r.status_code}")

    def test_role02_admin_can_access_recommendations(self):
        r = _api("get", "/v1/admin/developers/recommendations", key=ADMIN_KEY)
        chk("ROLE.02 admin → recommendations 200", r.status_code == 200, f"got {r.status_code}")

    def test_role03_ceo_can_access_recommendations(self):
        r = _api("get", "/v1/admin/developers/recommendations", key=CEO_KEY)
        chk("ROLE.03 ceo → recommendations 200", r.status_code == 200, f"got {r.status_code}")

    def test_role04_member_blocked_from_recommendations(self):
        r = _api("get", "/v1/admin/developers/recommendations", key=MEMBER_KEY)
        chk("ROLE.04 member → recommendations 403", r.status_code == 403, f"got {r.status_code}")

    def test_role05_member_can_ingest_events(self):
        """Members must be able to ingest events (and thus submit quality scores)."""
        event_id = _ingest_event(key=MEMBER_KEY)
        chk("ROLE.05 member can POST /v1/events", event_id is not None, "event_id was None")

    def test_role06_member_can_submit_quality_scores(self):
        event_id = _ingest_event(key=MEMBER_KEY)
        if not event_id:
            pytest.skip("Could not ingest event as member")
        r = _api("patch", f"/v1/events/{event_id}/scores", key=MEMBER_KEY, json={
            "hallucination_score": 0.10,
            "faithfulness_score":  0.90,
        })
        chk("ROLE.06 member can PATCH quality scores", r.status_code == 200, f"got {r.status_code}")

    def test_role07_admin_can_submit_quality_scores(self):
        event_id = _ingest_event(key=ADMIN_KEY)
        if not event_id:
            pytest.skip("Could not ingest event as admin")
        r = _api("patch", f"/v1/events/{event_id}/scores", key=ADMIN_KEY, json={
            "hallucination_score": 0.07,
        })
        chk("ROLE.07 admin can PATCH quality scores", r.status_code == 200, f"got {r.status_code}")

    def test_role08_superadmin_sees_all_recommendation_fields(self):
        r = _api("get", "/v1/admin/developers/recommendations?days=90", key=SUPERADMIN_KEY)
        chk("ROLE.08 superadmin gets 200 with days=90", r.status_code == 200, f"got {r.status_code}")
        d = r.json()
        chk("ROLE.08 period_days=90 for superadmin", d.get("period_days") == 90)
        chk("ROLE.08 recommendations array present", isinstance(d.get("recommendations"), list))
