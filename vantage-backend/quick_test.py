"""
quick_test.py
=============
Run this after starting the server to verify the full pipeline works.

    python3 quick_test.py

Tests:
  1. Server health check
  2. SDK init + mock event capture
  3. Hallucination scorer (if ANTHROPIC_API_KEY set)
  4. Pricing calculations
  5. Efficiency scorer
"""

import asyncio
import json
import os
import sys
import time
import urllib.request
import urllib.error

# ── Config ─────────────────────────────────────────────────────────────────────
SERVER   = os.getenv("VANTAGE_INGEST_URL", "http://localhost:8000").rstrip("/v1/events").rstrip("/")
API_KEY  = os.getenv("VANTAGE_API_KEY", "crt_test_key")
ANTH_KEY = os.getenv("ANTHROPIC_API_KEY", "")

PASS = "\033[92m✓\033[0m"
FAIL = "\033[91m✗\033[0m"
WARN = "\033[93m⚠\033[0m"

def ok(msg): print(f"  {PASS} {msg}")
def fail(msg): print(f"  {FAIL} {msg}")
def warn(msg): print(f"  {WARN} {msg}")
def header(msg): print(f"\n\033[1m{msg}\033[0m")


# ── Test 1: Server health ──────────────────────────────────────────────────────
header("1. Server health")
try:
    with urllib.request.urlopen(f"{SERVER}/health", timeout=5) as r:
        data = json.loads(r.read())
        if data.get("status") == "ok":
            ok(f"Server running at {SERVER}")
        else:
            fail(f"Unexpected response: {data}")
except Exception as e:
    fail(f"Cannot reach server: {e}")
    print(f"\n  → Start the server first:\n    cd server && uvicorn main:app --reload --port 8000")
    sys.exit(1)


# ── Test 2: SDK — pricing + efficiency ────────────────────────────────────────
header("2. SDK: Pricing + Efficiency")
try:
    sys.path.insert(0, "sdk")
    from vantage.models.pricing import calculate_cost, find_cheapest_alternative, MODELS
    from vantage.analysis.efficiency import compute_efficiency

    # Pricing
    inp, out, total = calculate_cost("gpt-4o", 1000, 500)
    ok(f"GPT-4o cost: ${total:.6f} (in=${inp:.6f}, out={out:.6f})")

    alt = find_cheapest_alternative("gpt-4o", 1000, 500)
    if alt:
        ok(f"Cheapest alt: {alt.name} at ${alt.cost:.6f} (saves {(1-alt.cost/total)*100:.0f}%)")

    # Efficiency
    report = compute_efficiency(
        prompt_tokens=2000, completion_tokens=400,
        system_prompt_tokens=1200, cached_tokens=0,
        model="gpt-4o", provider="openai",
        latency_ms=1200, total_cost_usd=total,
    )
    ok(f"Efficiency score: {report.score}/100 (grade {report.grade})")
    if report.issues:
        for issue in report.issues:
            warn(f"  Issue: {issue}")
    ok(f"Estimated saving if optimised: {report.estimated_saving_pct}%")

except Exception as e:
    fail(f"SDK import error: {e}")
    import traceback; traceback.print_exc()


# ── Test 3: Mock event ingest ──────────────────────────────────────────────────
header("3. Event ingest")
try:
    event = {
        "event_id":          "test-" + str(int(time.time())),
        "timestamp":         time.time(),
        "org_id":            "test-org",
        "provider":          "openai",
        "model":             "gpt-4o",
        "agent":             "cursor",
        "team":              "engineering",
        "project":           "chatbot",
        "latency_ms":        843.2,
        "ttft_ms":           210.5,
        "prompt_tokens":     1240,
        "completion_tokens": 380,
        "total_tokens":      1620,
        "cached_tokens":     0,
        "system_prompt_tokens": 520,
        "total_cost_usd":    0.004250,
        "cheapest_model":    "gemini-1.5-flash",
        "potential_saving_usd": 0.003980,
        "request_preview":   "Explain the transformer architecture in detail",
        "response_preview":  "The transformer architecture consists of...",
        "tags":              {"user_id": "dev@test.com", "feature": "docs"},
    }

    payload = json.dumps({"events": [event], "sdk_version": "0.2.0"}).encode()
    req = urllib.request.Request(
        f"{SERVER}/v1/events",
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {API_KEY}",
        },
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        resp = json.loads(r.read())
        ok(f"Event ingested: {resp}")
except urllib.error.HTTPError as e:
    body = e.read().decode()
    if e.code == 401:
        warn(f"Auth failed (401) — expected if using test key without real Supabase key: {body}")
    else:
        fail(f"HTTP {e.code}: {body}")
except Exception as e:
    fail(f"Ingest error: {e}")


# ── Test 4: Hallucination scoring ──────────────────────────────────────────────
header("4. Hallucination scoring (Claude Opus 4.6)")
if not ANTH_KEY:
    warn("ANTHROPIC_API_KEY not set — skipping hallucination test")
    warn("Set it to enable: export ANTHROPIC_API_KEY=sk-ant-...")
else:
    async def test_hallucination():
        sys.path.insert(0, "sdk")
        from vantage.analysis.hallucination import evaluate_response, _heuristic_scores

        # Test heuristic fallback (no API call)
        scores = _heuristic_scores(
            "What is the capital of France?",
            "The capital of France is Paris, which has been the capital since..."
        )
        ok(f"Heuristic scores: hall={scores['hallucination_score']:.2f} "
           f"relevance={scores['relevance_score']:.2f} quality={scores['overall_quality']:.1f}/10")

        # Test with real Opus 4.6
        try:
            scores = await evaluate_response(
                user_query   = "What year was Python first released?",
                ai_response  = "Python was first released in 1991 by Guido van Rossum.",
                model        = "gpt-4o",
                anthropic_key = ANTH_KEY,
            )
            ok(f"Opus 4.6 eval: hall={scores['hallucination_score']:.2f} "
               f"quality={scores['overall_quality']:.1f}/10 "
               f"evaluated_by={scores['evaluated_by']}")
        except Exception as e:
            warn(f"Opus 4.6 eval error: {e}")

    asyncio.run(test_hallucination())


# ── Summary ────────────────────────────────────────────────────────────────────
print("\n\033[1m─── Summary ───\033[0m")
print(f"  Server:     {SERVER}")
print(f"  Swagger UI: {SERVER}/docs")
print(f"  Dashboard:  https://vantageai.aman-lpucse.workers.dev/app.html")
print(f"  Hallucination scoring: {'enabled ✓' if ANTH_KEY else 'disabled (set ANTHROPIC_API_KEY)'}")
print()
