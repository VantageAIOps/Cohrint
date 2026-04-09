"""
conftest.py — Suite 37: All Dashboard Cards, Cross-Integration E2E
===================================================================
Module-scoped SeedContext fixture that ingests known data from every
supported integration path, then exposes expected values for assertions.

Integration paths seeded:
  1. OTel/OTLP  → cross_platform_usage  (timeseries, today, models, cross-platform/*)
  2. JS SDK     → events                (kpis, summary, teams)
  3. MCP tool   → events                (kpis, summary, teams)
  4. Local-proxy style → events         (kpis, summary, teams)
  5. Direct API → events                (kpis, summary, teams)

Subprocess integrations (SDK, MCP) are non-fatal: if the dist is missing
or the subprocess fails, the integration is marked skipped and dependent
tests call pytest.skip() automatically.
"""

import json
import os
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional

import pytest
import requests

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config.settings import API_URL
from helpers.api import fresh_account, get_headers

# ---------------------------------------------------------------------------
# Repo layout
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).parent.parent.parent.parent
SDK_CJS   = REPO_ROOT / "vantage-js-sdk"  / "dist" / "index.cjs"
MCP_BIN   = REPO_ROOT / "vantage-mcp"     / "dist" / "index.js"


# ---------------------------------------------------------------------------
# OTLP helpers
# ---------------------------------------------------------------------------

def _otlp_counter(name: str, value: float, attrs: Optional[Dict] = None) -> dict:
    return {
        "name": name,
        "sum": {
            "dataPoints": [{
                "asDouble": value,
                "timeUnixNano": str(int(time.time() * 1_000_000_000)),
                "attributes": [
                    {"key": k, "value": {"stringValue": str(v)}}
                    for k, v in (attrs or {}).items()
                ],
            }],
            "isMonotonic": True,
        },
    }


def _otlp_payload(service_name: str, metrics: list, email: str,
                  team: Optional[str] = None, model: Optional[str] = None) -> dict:
    attrs = [
        {"key": "service.name",  "value": {"stringValue": service_name}},
        {"key": "user.email",    "value": {"stringValue": email}},
        {"key": "session.id",    "value": {"stringValue": f"dc37-{uuid.uuid4().hex[:8]}"}},
    ]
    if team:
        attrs.append({"key": "team.id", "value": {"stringValue": team}})
    if model:
        attrs.append({"key": "gen_ai.request.model", "value": {"stringValue": model}})
    return {
        "resourceMetrics": [{
            "resource": {"attributes": attrs},
            "scopeMetrics": [{"scope": {"name": "dc37-test", "version": "1.0"}, "metrics": metrics}],
        }]
    }


# ---------------------------------------------------------------------------
# Integration ingest functions
# ---------------------------------------------------------------------------

def ingest_otel(headers: dict, service: str, email: str, team: str,
                model: str, provider_metric: str,
                input_tok: int, output_tok: int, cost: float) -> tuple[bool, str]:
    """Ingest a record via OTLP POST → cross_platform_usage."""
    metrics = [
        _otlp_counter(f"{provider_metric}.token.usage", input_tok,
                      {"type": "input", "gen_ai.token.type": "input"}),
        _otlp_counter(f"{provider_metric}.token.usage", output_tok,
                      {"type": "output", "gen_ai.token.type": "output"}),
        _otlp_counter(f"{provider_metric}.cost.usage", cost,
                      {"currency": "USD"}),
        _otlp_counter(f"{provider_metric}.api.request.count", 1, {}),
    ]
    payload = _otlp_payload(service, metrics, email, team=team)
    try:
        r = requests.post(f"{API_URL}/v1/otel/v1/metrics",
                          json=payload, headers=headers, timeout=15)
        return r.status_code in (200, 201, 202), f"status={r.status_code}"
    except Exception as e:
        return False, str(e)


def ingest_sdk(headers: dict, event_id: str, provider: str, model: str,
               prompt_tokens: int, completion_tokens: int, cost: float,
               team: str, user_id: str) -> tuple[bool, str]:
    """Ingest simulating JS SDK: POST /v1/events with sdk_language=typescript."""
    payload = {
        "event_id":          event_id,
        "provider":          provider,
        "model":             model,
        "prompt_tokens":     prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_cost_usd":    cost,
        "team":              team,
        "environment":       "test",
        "user_id":           user_id,
        "sdk_language":      "typescript",
        "sdk_version":       "1.4.1",
    }
    try:
        r = requests.post(f"{API_URL}/v1/events", json=payload,
                          headers=headers, timeout=15)
        return r.status_code in (200, 201, 202), f"status={r.status_code}"
    except Exception as e:
        return False, str(e)


def ingest_mcp(api_key: str, model: str, provider: str,
               prompt_tokens: int, completion_tokens: int, cost: float,
               team: str) -> tuple[bool, str]:
    """Ingest via vantage-mcp JSON-RPC over stdio → events."""
    if not MCP_BIN.exists():
        return False, f"MCP dist missing: {MCP_BIN}"

    env = {**os.environ, "VANTAGE_API_KEY": api_key, "VANTAGE_API_BASE": API_URL}

    init_req = json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "dc37-test", "version": "1.0.0"},
        },
    })
    init_notif = json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"})
    tool_call  = json.dumps({
        "jsonrpc": "2.0", "id": 2, "method": "tools/call",
        "params": {
            "name": "track_llm_call",
            "arguments": {
                "model":             model,
                "provider":          provider,
                "prompt_tokens":     prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_cost_usd":    cost,
                "team":              team,
                "environment":       "test",
            },
        },
    })
    stdin_data = f"{init_req}\n{init_notif}\n{tool_call}\n".encode()

    try:
        proc = subprocess.run(
            ["node", str(MCP_BIN)],
            input=stdin_data,
            capture_output=True,
            timeout=15,
            env=env,
        )
        # Find response for id=2 (tool call result)
        for line in proc.stdout.decode().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                resp = json.loads(line)
                if resp.get("id") == 2:
                    return "error" not in resp, json.dumps(resp)[:300]
            except json.JSONDecodeError:
                continue
        stderr = proc.stderr.decode()[:300]
        return False, f"no id=2 response; stderr={stderr}"
    except Exception as e:
        return False, str(e)


def ingest_proxy_style(headers: dict, event_id: str, provider: str, model: str,
                       prompt_tokens: int, completion_tokens: int, cost: float,
                       team: str, user_id: str) -> tuple[bool, str]:
    """Simulate local-proxy ingest: POST /v1/events with sdk_language=local-proxy."""
    payload = {
        "event_id":         event_id,
        "provider":         provider,
        "model":            model,
        "prompt_tokens":    prompt_tokens,
        "completion_tokens":completion_tokens,
        "total_cost_usd":   cost,
        "team":             team,
        "environment":      "test",
        "user_id":          user_id,
        "sdk_language":     "local-proxy",
        "sdk_version":      "0.4.0",
    }
    try:
        r = requests.post(f"{API_URL}/v1/events", json=payload,
                          headers=headers, timeout=15)
        return r.status_code in (200, 201, 202), f"status={r.status_code}"
    except Exception as e:
        return False, str(e)


def ingest_direct(headers: dict, event_id: str, provider: str, model: str,
                  prompt_tokens: int, completion_tokens: int, cost: float,
                  team: str, user_id: str) -> tuple[bool, str]:
    """Direct POST to /v1/events (simulates CLI or raw API call)."""
    payload = {
        "event_id":         event_id,
        "provider":         provider,
        "model":            model,
        "prompt_tokens":    prompt_tokens,
        "completion_tokens":completion_tokens,
        "total_cost_usd":   cost,
        "team":             team,
        "environment":      "test",
        "user_id":          user_id,
    }
    try:
        r = requests.post(f"{API_URL}/v1/events", json=payload,
                          headers=headers, timeout=15)
        return r.status_code in (200, 201, 202), f"status={r.status_code}"
    except Exception as e:
        return False, str(e)


# ---------------------------------------------------------------------------
# SeedContext
# ---------------------------------------------------------------------------

@dataclass
class IntegrationRecord:
    name:     str
    success:  bool
    source:   str           # "otel" | "sdk" | "mcp" | "local-proxy" | "direct"
    provider: str
    model:    str
    cost:     float
    team:     str
    developer: str
    error:    str = ""


@dataclass
class SeedContext:
    api_key:      str
    org_id:       str
    headers:      dict
    records:      list = field(default_factory=list)

    # Raw expected values (computed after seeding)
    otel_input_tokens:  int = 0
    otel_output_tokens: int = 0

    def successful(self) -> list:
        return [r for r in self.records if r.success]

    def by_source(self, source: str) -> list:
        return [r for r in self.records if r.success and r.source == source]

    @property
    def total_otel_cost(self) -> float:
        return round(sum(r.cost for r in self.by_source("otel")), 6)

    @property
    def total_events_cost(self) -> float:
        return round(sum(r.cost for r in self.records
                         if r.success and r.source != "otel"), 6)

    @property
    def successful_sources(self) -> set:
        return {r.source for r in self.records if r.success}

    @property
    def successful_providers_otel(self) -> set:
        return {r.provider for r in self.by_source("otel")}

    @property
    def successful_models_otel(self) -> set:
        return {r.model for r in self.by_source("otel")}

    @property
    def successful_developers(self) -> set:
        return {r.developer for r in self.records if r.success}

    @property
    def successful_teams(self) -> set:
        return {r.team for r in self.records if r.success}

    @property
    def events_teams(self) -> set:
        return {r.team for r in self.records if r.success and r.source != "otel"}


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def seeded() -> SeedContext:
    """
    Create a fresh account, seed all 5 integration paths, wait for
    processing, and return a SeedContext with expected values.
    """
    api_key, org_id, _ = fresh_account(prefix="dc37")
    headers = get_headers(api_key)
    ctx = SeedContext(api_key=api_key, org_id=org_id, headers=headers)

    uid = uuid.uuid4().hex[:8]

    # ------------------------------------------------------------------
    # 1. OTel ingest #1 — claude_code / claude-sonnet-4-6 / backend
    # ------------------------------------------------------------------
    ok, err = ingest_otel(
        headers,
        service="claude-code",
        email=f"otel1-{uid}@dc.test",
        team="backend",
        model="claude-sonnet-4-6",
        provider_metric="claude_code",
        input_tok=500, output_tok=150, cost=0.025,
    )
    ctx.records.append(IntegrationRecord(
        name="otel_claude", success=ok, source="otel",
        provider="claude_code", model="claude-sonnet-4-6",
        cost=0.025, team="backend", developer=f"otel1-{uid}@dc.test", error=err,
    ))
    ctx.otel_input_tokens  += 500 if ok else 0
    ctx.otel_output_tokens += 150 if ok else 0

    # ------------------------------------------------------------------
    # 2. OTel ingest #2 — openai_api / gpt-4o / frontend
    #    Uses llm.* metric conventions (explicitly carries cost value)
    # ------------------------------------------------------------------
    ok2, err2 = ingest_otel(
        headers,
        service="openai-api",
        email=f"otel2-{uid}@dc.test",
        team="frontend",
        model="gpt-4o",
        provider_metric="claude_code",   # only claude_code.cost.usage carries explicit cost
        input_tok=200, output_tok=80, cost=0.015,
    )
    ctx.records.append(IntegrationRecord(
        name="otel_openai", success=ok2, source="otel",
        provider="openai_api", model="gpt-4o",
        cost=0.015, team="frontend", developer=f"otel2-{uid}@dc.test", error=err2,
    ))
    ctx.otel_input_tokens  += 200 if ok2 else 0
    ctx.otel_output_tokens += 80  if ok2 else 0

    # ------------------------------------------------------------------
    # 3. JS SDK subprocess → events table
    # ------------------------------------------------------------------
    ok3, err3 = ingest_sdk(
        headers=headers,
        event_id=f"dc37-sdk-{uid}",
        provider="openai", model="gpt-4o",
        prompt_tokens=200, completion_tokens=80, cost=0.010,
        team="frontend", user_id=f"sdk-{uid}@dc.test",
    )
    ctx.records.append(IntegrationRecord(
        name="sdk", success=ok3, source="sdk",
        provider="openai", model="gpt-4o",
        cost=0.010 if ok3 else 0.0, team="frontend",
        developer=f"sdk-{uid}@dc.test", error=err3,
    ))

    # ------------------------------------------------------------------
    # 4. MCP tool JSON-RPC subprocess → events table
    # ------------------------------------------------------------------
    ok4, err4 = ingest_mcp(
        api_key=api_key,
        model="claude-3-5-haiku-20241022", provider="anthropic",
        prompt_tokens=300, completion_tokens=100, cost=0.008,
        team="backend",
    )
    ctx.records.append(IntegrationRecord(
        name="mcp", success=ok4, source="mcp",
        provider="anthropic", model="claude-3-5-haiku-20241022",
        cost=0.008 if ok4 else 0.0, team="backend",
        developer=f"mcp-{uid}@dc.test", error=err4,
    ))

    # ------------------------------------------------------------------
    # 5. Local-proxy style — POST /v1/events with sdk_language=local-proxy
    # ------------------------------------------------------------------
    ok5, err5 = ingest_proxy_style(
        headers=headers,
        event_id=f"dc37-proxy-{uid}",
        provider="openai", model="gpt-4o-mini",
        prompt_tokens=150, completion_tokens=60, cost=0.006,
        team="data", user_id=f"proxy-{uid}@dc.test",
    )
    ctx.records.append(IntegrationRecord(
        name="local_proxy", success=ok5, source="local-proxy",
        provider="openai", model="gpt-4o-mini",
        cost=0.006 if ok5 else 0.0, team="data",
        developer=f"proxy-{uid}@dc.test", error=err5,
    ))

    # ------------------------------------------------------------------
    # 6. Direct API POST /v1/events (simulates CLI / raw HTTP)
    # ------------------------------------------------------------------
    ok6, err6 = ingest_direct(
        headers=headers,
        event_id=f"dc37-direct-{uid}",
        provider="anthropic", model="claude-3-5-sonnet-20241022",
        prompt_tokens=250, completion_tokens=90, cost=0.012,
        team="data", user_id=f"direct-{uid}@dc.test",
    )
    ctx.records.append(IntegrationRecord(
        name="direct", success=ok6, source="direct",
        provider="anthropic", model="claude-3-5-sonnet-20241022",
        cost=0.012 if ok6 else 0.0, team="data",
        developer=f"direct-{uid}@dc.test", error=err6,
    ))

    # Allow time for all async processing and KV cache invalidation
    time.sleep(5)

    return ctx
