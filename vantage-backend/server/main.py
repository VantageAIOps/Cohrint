"""
Vantage AI — FastAPI Ingest + Analytics Server v2.0
Fixes: rate limiting, SSE live stream, OpenTelemetry ingest, Slack alerts, event queue safety
"""
from __future__ import annotations
import asyncio, hashlib, json, logging, os, time
from collections import defaultdict
from contextlib import asynccontextmanager
from typing import Optional, AsyncGenerator
from fastapi import FastAPI, HTTPException, Request, Depends, BackgroundTasks, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("vantage")

SUPABASE_URL  = os.getenv("SUPABASE_URL",  "https://oyljzpvwdfktrkeotmon.supabase.co")
SUPABASE_KEY  = os.getenv("SUPABASE_SERVICE_KEY", "")
ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY", "")
EVAL_ENABLED  = os.getenv("EVAL_ENABLED", "true").lower() == "true"
EVAL_SAMPLE   = float(os.getenv("EVAL_SAMPLE_RATE", "0.2"))
SLACK_SIGNING = os.getenv("SLACK_SIGNING_SECRET", "")

# ── Rate limiter (token bucket, in-memory) ────────────────────────────────────
class _RateLimiter:
    """Per-API-key token bucket. Default: 1000 events/minute."""
    def __init__(self, rate: int = 1000, window: int = 60):
        self.rate   = rate
        self.window = window
        self._buckets: dict[str, tuple[float, int]] = {}

    def is_allowed(self, key: str) -> bool:
        now = time.time()
        if key not in self._buckets:
            self._buckets[key] = (now, self.rate - 1)
            return True
        reset_at, tokens = self._buckets[key]
        if now - reset_at >= self.window:
            self._buckets[key] = (now, self.rate - 1)
            return True
        if tokens > 0:
            self._buckets[key] = (reset_at, tokens - 1)
            return True
        return False

    def remaining(self, key: str) -> int:
        if key not in self._buckets:
            return self.rate
        reset_at, tokens = self._buckets[key]
        if time.time() - reset_at >= self.window:
            return self.rate
        return tokens

_limiter = _RateLimiter(rate=int(os.getenv("RATE_LIMIT_RPM", "1000")))

# ── SSE live-stream queues (per org) ─────────────────────────────────────────
_sse_queues: dict[str, list[asyncio.Queue]] = defaultdict(list)

async def _broadcast(org_id: str, payload: dict):
    """Push a JSON payload to all SSE subscribers for an org."""
    if org_id not in _sse_queues:
        return
    dead = []
    for q in _sse_queues[org_id]:
        try:
            q.put_nowait(json.dumps(payload))
        except asyncio.QueueFull:
            dead.append(q)
    for q in dead:
        try:
            _sse_queues[org_id].remove(q)
        except ValueError:
            pass

# ── Supabase + Analytics ──────────────────────────────────────────────────────
_sb = None
def get_supabase():
    global _sb
    if _sb is None and SUPABASE_KEY:
        try:
            from supabase import create_client
            _sb = create_client(SUPABASE_URL, SUPABASE_KEY)
            logger.info("Supabase connected ✓")
        except Exception as e:
            logger.error("Supabase error: %s", e)
    return _sb

_analytics = None
def get_analytics():
    global _analytics
    if _analytics is None:
        from server.analytics import AnalyticsEngine
        _analytics = AnalyticsEngine(get_supabase())
    return _analytics

@asynccontextmanager
async def lifespan(app: FastAPI):
    sb = get_supabase()
    logger.info("Vantage v2.0 ready — DB:%s Eval:%s RateLimit:%d/min",
                "✓" if sb else "dev", EVAL_ENABLED, _limiter.rate)
    yield

app = FastAPI(title="Vantage AI API", version="2.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
security = HTTPBearer(auto_error=False)

# ── Auth ──────────────────────────────────────────────────────────────────────
async def require_org(request: Request, creds: Optional[HTTPAuthorizationCredentials] = Depends(security)) -> str:
    raw = creds.credentials if creds else request.headers.get("X-API-Key")
    if not raw:
        raise HTTPException(401, "Missing API key")
    sb = get_supabase()
    if not sb:
        if raw.startswith("vnt_"):
            parts = raw.split("_")
            return parts[1] if len(parts) >= 3 else "dev"
        raise HTTPException(401, "Invalid key")
    key_hash = hashlib.sha256(raw.encode()).hexdigest()
    try:
        res = sb.table("api_keys").select("org_id,revoked").eq("key_hash", key_hash).single().execute()
        if not res.data or res.data.get("revoked"):
            raise HTTPException(401, "Invalid or revoked key")
        asyncio.create_task(_touch_key(key_hash))
        return res.data["org_id"]
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("Auth error: %s", e)
        raise HTTPException(401, "Auth failed")

async def _touch_key(kh: str):
    try:
        sb = get_supabase()
        if sb: sb.table("api_keys").update({"last_used_at": "now()"}).eq("key_hash", kh).execute()
    except: pass

def _chk(token_org: str, req_org: str):
    if token_org != req_org:
        raise HTTPException(403, "Access denied")

# ── Models ────────────────────────────────────────────────────────────────────
class EventIn(BaseModel):
    event_id: str; timestamp: float; org_id: str = ""; environment: str = "production"
    provider: str = ""; model: str = ""; endpoint: str = ""; session_id: str = ""
    user_id: str = ""; feature: str = ""; project: str = ""; team: str = ""
    tags: dict = Field(default_factory=dict)
    latency_ms: float = 0; ttft_ms: float = 0; status_code: int = 200
    error: Optional[str] = None
    # streaming metadata
    is_streaming: bool = False; stream_chunks: int = 0
    usage_prompt_tokens: int = 0; usage_completion_tokens: int = 0
    usage_total_tokens: int = 0; usage_cached_tokens: int = 0
    usage_system_prompt_tokens: int = 0
    cost_input_cost_usd: float = 0; cost_output_cost_usd: float = 0
    cost_total_cost_usd: float = 0; cost_cheapest_model: str = ""
    cost_cheapest_cost_usd: float = 0; cost_potential_saving_usd: float = 0
    request_preview: str = ""; response_preview: str = ""
    system_preview: str = ""; prompt_hash: str = ""
    # agent trace fields
    parent_event_id: Optional[str] = None; agent_name: str = ""
    trace_id: str = ""; span_depth: int = 0

class BatchIn(BaseModel):
    events: list[EventIn]; sdk_version: str = "unknown"
    sdk_language: str = "python"

class SlackConfigIn(BaseModel):
    webhook_url: str
    channel: str = "#ai-alerts"
    events: list[str] = Field(default_factory=lambda: ["budget_breach","anomaly","quality_drop"])
    budget_threshold_usd: float = 0.0
    enabled: bool = True

class BudgetAlertIn(BaseModel):
    name: str; threshold_usd: float; window: str = "month"
    team: str = ""; feature: str = ""; notify_slack: bool = False
    notify_email: str = ""

# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "version": "2.0.0",
        "supabase": "connected" if get_supabase() else "dev",
        "eval_enabled": EVAL_ENABLED,
        "eval_model": "claude-opus-4-6",
        "features": ["sse", "rate_limiting", "otel", "streaming", "agent_traces"],
        "ts": time.time(),
    }

# ── Ingest (with rate limiting + SSE broadcast) ───────────────────────────────
@app.post("/v1/events", status_code=202)
async def ingest(batch: BatchIn, bg: BackgroundTasks,
                 request: Request, org: str = Depends(require_org)):
    if not batch.events:
        return {"accepted": 0}
    if len(batch.events) > 500:
        raise HTTPException(400, "Max 500 events per batch")

    # Rate limit check
    if not _limiter.is_allowed(org):
        raise HTTPException(
            429,
            detail="Rate limit exceeded. Max 1000 events/minute per org.",
            headers={
                "Retry-After": "60",
                "X-RateLimit-Limit": str(_limiter.rate),
                "X-RateLimit-Remaining": "0",
            },
        )

    for ev in batch.events:
        ev.org_id = org
    bg.add_task(_store_events, batch.events)

    if EVAL_ENABLED and ANTHROPIC_KEY:
        import random
        to_eval = [e for e in batch.events if random.random() < EVAL_SAMPLE]
        if to_eval:
            bg.add_task(_evaluate_batch, to_eval)

    # Broadcast summary to SSE subscribers
    bg.add_task(_broadcast, org, {
        "type": "events",
        "count": len(batch.events),
        "total_cost": sum(e.cost_total_cost_usd for e in batch.events),
        "models": list({e.model for e in batch.events if e.model}),
        "ts": time.time(),
    })

    return {
        "accepted": len(batch.events),
        "org_id": org,
        "sdk_version": batch.sdk_version,
        "sdk_language": batch.sdk_language,
        "rate_limit_remaining": _limiter.remaining(org),
    }

# ── SSE live stream ───────────────────────────────────────────────────────────
@app.get("/v1/stream/{org_id}")
async def live_stream(org_id: str, org: str = Depends(require_org)):
    """Server-Sent Events endpoint. Dashboard connects here for real-time updates."""
    _chk(org, org_id)
    q: asyncio.Queue = asyncio.Queue(maxsize=100)
    _sse_queues[org_id].append(q)

    async def generator() -> AsyncGenerator[str, None]:
        try:
            yield f"data: {json.dumps({'type':'connected','org_id':org_id,'ts':time.time()})}\n\n"
            while True:
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=25)
                    yield f"data: {msg}\n\n"
                except asyncio.TimeoutError:
                    yield f"data: {json.dumps({'type':'ping','ts':time.time()})}\n\n"
        finally:
            try:
                _sse_queues[org_id].remove(q)
            except ValueError:
                pass

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )

# ── OpenTelemetry OTLP/HTTP ingest ────────────────────────────────────────────
@app.post("/v1/traces", status_code=202)
async def ingest_otel(request: Request, bg: BackgroundTasks, org: str = Depends(require_org)):
    """Accept OTLP/HTTP JSON traces and convert to VantageEvents."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON body")

    events = _convert_otel(body, org)
    if events:
        bg.add_task(_store_events, events)
        bg.add_task(_broadcast, org, {
            "type": "otel_traces", "count": len(events), "ts": time.time()
        })
    return {"accepted": len(events), "source": "otlp"}

def _convert_otel(body: dict, org_id: str) -> list[EventIn]:
    """Convert OTLP JSON resourceSpans to EventIn list."""
    events = []
    try:
        for rs in body.get("resourceSpans", []):
            for ss in rs.get("scopeSpans", []):
                for span in ss.get("spans", []):
                    attrs = {a["key"]: a.get("value", {}).get("stringValue", "")
                             for a in span.get("attributes", [])}
                    model    = attrs.get("gen_ai.request.model", attrs.get("llm.model", ""))
                    provider = attrs.get("gen_ai.system", "unknown")
                    if not model:
                        continue
                    start_ns = int(span.get("startTimeUnixNano", 0))
                    end_ns   = int(span.get("endTimeUnixNano",   0))
                    lat_ms   = (end_ns - start_ns) / 1e6 if end_ns > start_ns else 0

                    events.append(EventIn(
                        event_id=span.get("spanId", "") or f"otel_{time.time()}",
                        timestamp=start_ns / 1e9,
                        org_id=org_id,
                        provider=provider,
                        model=model,
                        endpoint=attrs.get("http.route", "/otel"),
                        latency_ms=lat_ms,
                        status_code=200 if span.get("status", {}).get("code") != "ERROR" else 500,
                        usage_prompt_tokens=int(attrs.get("gen_ai.usage.prompt_tokens", 0)),
                        usage_completion_tokens=int(attrs.get("gen_ai.usage.completion_tokens", 0)),
                        trace_id=span.get("traceId", ""),
                        parent_event_id=span.get("parentSpanId") or None,
                        tags={"source": "otlp"},
                    ))
    except Exception as e:
        logger.warning("OTEL conversion error: %s", e)
    return events

# ── Slack webhook config ──────────────────────────────────────────────────────
@app.post("/v1/alerts/slack/{org_id}", status_code=201)
async def configure_slack(org_id: str, config: SlackConfigIn, org: str = Depends(require_org)):
    _chk(org, org_id)
    sb = get_supabase()
    if sb:
        try:
            sb.table("slack_configs").upsert({
                "org_id": org_id,
                "webhook_url": config.webhook_url,
                "channel": config.channel,
                "events": config.events,
                "budget_threshold_usd": config.budget_threshold_usd,
                "enabled": config.enabled,
                "updated_at": "now()",
            }).execute()
        except Exception as e:
            logger.warning("Slack config save error: %s", e)
    return {"configured": True, "channel": config.channel}

@app.post("/v1/alerts/slack/{org_id}/test")
async def test_slack(org_id: str, org: str = Depends(require_org)):
    _chk(org, org_id)
    sb = get_supabase()
    webhook_url = ""
    if sb:
        try:
            res = sb.table("slack_configs").select("webhook_url").eq("org_id", org_id).single().execute()
            webhook_url = res.data.get("webhook_url", "") if res.data else ""
        except: pass
    if not webhook_url:
        raise HTTPException(404, "No Slack webhook configured for this org")
    ok = await _send_slack(webhook_url, {
        "text": "✅ *Vantage AI* — Test alert from your dashboard. Slack integration is working!",
        "username": "Vantage AI", "icon_emoji": ":bar_chart:",
    })
    return {"sent": ok}

async def _send_slack(webhook_url: str, payload: dict) -> bool:
    try:
        import urllib.request as ur
        data = json.dumps(payload).encode()
        req  = ur.Request(webhook_url, data=data, headers={"Content-Type": "application/json"}, method="POST")
        with ur.urlopen(req, timeout=5): pass
        return True
    except Exception as e:
        logger.warning("Slack send error: %s", e)
        return False

async def _maybe_alert_slack(org_id: str, event_type: str, message: str):
    sb = get_supabase()
    if not sb: return
    try:
        res = sb.table("slack_configs").select("*").eq("org_id", org_id).eq("enabled", True).single().execute()
        if not res.data: return
        cfg = res.data
        if event_type not in cfg.get("events", []):
            return
        await _send_slack(cfg["webhook_url"], {
            "text": message, "username": "Vantage AI", "icon_emoji": ":bar_chart:",
            "channel": cfg.get("channel", "#ai-alerts"),
        })
    except: pass

# ── Budget alerts ─────────────────────────────────────────────────────────────
@app.post("/v1/budgets/{org_id}", status_code=201)
async def create_budget(org_id: str, alert: BudgetAlertIn, org: str = Depends(require_org)):
    _chk(org, org_id)
    sb = get_supabase()
    if sb:
        sb.table("budget_rules").insert({
            "org_id": org_id, "name": alert.name,
            "threshold_usd": alert.threshold_usd, "window": alert.window,
            "team": alert.team, "feature": alert.feature,
            "notify_slack": alert.notify_slack, "notify_email": alert.notify_email,
        }).execute()
    return {"created": True}

# ── Analytics endpoints ───────────────────────────────────────────────────────
@app.get("/v1/kpis/{org_id}")
async def kpis(org_id: str, days: int = Query(30, ge=1, le=365), org: str = Depends(require_org)):
    _chk(org, org_id); return await get_analytics().get_kpis(org_id, days)

@app.get("/v1/timeseries/{org_id}")
async def timeseries(org_id: str, days: int = Query(30, ge=1, le=365),
                     granularity: str = "day", org: str = Depends(require_org)):
    _chk(org, org_id); return await get_analytics().get_timeseries(org_id, days, granularity)

@app.get("/v1/models/{org_id}")
async def models(org_id: str, days: int = Query(30, ge=1, le=365), org: str = Depends(require_org)):
    _chk(org, org_id); return await get_analytics().get_model_breakdown(org_id, days)

@app.get("/v1/teams/{org_id}")
async def teams(org_id: str, days: int = Query(30, ge=1, le=365), org: str = Depends(require_org)):
    _chk(org, org_id); return await get_analytics().get_team_breakdown(org_id, days)

@app.get("/v1/projects/{org_id}")
async def projects(org_id: str, days: int = Query(30, ge=1, le=365), org: str = Depends(require_org)):
    _chk(org, org_id); return await get_analytics().get_project_breakdown(org_id, days)

@app.get("/v1/hallucination/{org_id}")
async def hallucination(org_id: str, days: int = Query(30, ge=1, le=365), org: str = Depends(require_org)):
    _chk(org, org_id); return await get_analytics().get_hallucination_report(org_id, days)

@app.get("/v1/efficiency/{org_id}")
async def efficiency(org_id: str, days: int = Query(30, ge=1, le=365), org: str = Depends(require_org)):
    _chk(org, org_id); return await get_analytics().get_efficiency_report(org_id, days)

@app.get("/v1/latency/{org_id}")
async def latency(org_id: str, days: int = Query(30, ge=1, le=365), org: str = Depends(require_org)):
    _chk(org, org_id); return await get_analytics().get_latency_report(org_id, days)

@app.get("/v1/chargeback/{org_id}")
async def chargeback(org_id: str, days: int = Query(30, ge=1, le=365), org: str = Depends(require_org)):
    _chk(org, org_id); return await get_analytics().get_chargeback_report(org_id, days)

@app.get("/v1/user/{org_id}/{user_id}")
async def user_report(org_id: str, user_id: str, days: int = Query(30, ge=1, le=365),
                      org: str = Depends(require_org)):
    _chk(org, org_id); return await get_analytics().get_user_report(org_id, user_id, days)

# ── Agent traces ──────────────────────────────────────────────────────────────
@app.get("/v1/traces/{org_id}")
async def get_traces(org_id: str, days: int = Query(7, ge=1, le=90),
                     limit: int = Query(50, ge=1, le=200), org: str = Depends(require_org)):
    """Return agent trace trees grouped by trace_id."""
    _chk(org, org_id)
    sb = get_supabase()
    if not sb:
        return {"traces": []}
    try:
        cutoff = time.time() - days * 86400
        res = sb.table("ai_events") \
            .select("event_id,trace_id,parent_event_id,model,provider,agent_name,latency_ms,cost_total_cost_usd,timestamp,status_code") \
            .eq("org_id", org_id) \
            .gte("timestamp", cutoff) \
            .neq("trace_id", "") \
            .order("timestamp", desc=True) \
            .limit(limit) \
            .execute()
        return {"traces": _build_trace_trees(res.data or [])}
    except Exception as e:
        logger.warning("Traces error: %s", e)
        return {"traces": []}

def _build_trace_trees(rows: list) -> list:
    by_trace: dict[str, list] = defaultdict(list)
    for row in rows:
        by_trace[row.get("trace_id", "")].append(row)
    result = []
    for trace_id, spans in list(by_trace.items())[:20]:
        total_cost = sum(s.get("cost_total_cost_usd", 0) for s in spans)
        total_lat  = sum(s.get("latency_ms", 0) for s in spans)
        result.append({
            "trace_id": trace_id,
            "spans": spans,
            "span_count": len(spans),
            "total_cost_usd": total_cost,
            "total_latency_ms": total_lat,
            "models": list({s.get("model","") for s in spans if s.get("model")}),
            "started_at": min(s.get("timestamp", 0) for s in spans),
        })
    return sorted(result, key=lambda x: x["started_at"], reverse=True)

# ── Storage helpers ───────────────────────────────────────────────────────────
async def _store_events(events: list[EventIn]):
    sb = get_supabase()
    if not sb: return
    rows = [ev.model_dump() for ev in events]
    try:
        for i in range(0, len(rows), 100):
            sb.table("ai_events").upsert(rows[i:i+100]).execute()
        await _rollup(events)
    except Exception as e:
        logger.error("Store error: %s", e)

async def _rollup(events: list[EventIn]):
    sb = get_supabase()
    if not sb: return
    from datetime import datetime as dt
    R: dict = {}
    for ev in events:
        d   = dt.fromtimestamp(ev.timestamp).strftime("%Y-%m-%d")
        key = f"{ev.org_id}|{d}|{ev.model}|{ev.provider}|{ev.team}"
        if key not in R:
            R[key] = {"org_id": ev.org_id, "date": d, "model": ev.model,
                      "provider": ev.provider, "team": ev.team, "project": ev.project,
                      "request_count": 0, "prompt_tokens": 0, "completion_tokens": 0,
                      "total_cost_usd": 0.0, "error_count": 0, "total_latency_ms": 0.0,
                      "streaming_count": 0}
        r = R[key]
        r["request_count"]     += 1
        r["prompt_tokens"]     += ev.usage_prompt_tokens
        r["completion_tokens"] += ev.usage_completion_tokens
        r["total_cost_usd"]    += ev.cost_total_cost_usd
        r["total_latency_ms"]  += ev.latency_ms
        if ev.status_code >= 400: r["error_count"] += 1
        if ev.is_streaming:       r["streaming_count"] += 1
    try:
        vals = list(R.values())
        for i in range(0, len(vals), 50):
            sb.table("usage_daily").upsert(vals[i:i+50]).execute()
    except Exception as e:
        logger.warning("Rollup error: %s", e)

async def _evaluate_batch(events: list[EventIn]):
    from vantage.analysis.hallucination import evaluate_response
    sem = asyncio.Semaphore(3)
    async def eval_one(ev: EventIn):
        if not ev.request_preview or not ev.response_preview: return
        if ev.usage_completion_tokens < 20: return
        async with sem:
            try:
                scores = await evaluate_response(
                    user_query=ev.request_preview, ai_response=ev.response_preview,
                    model=ev.model, system_prompt=ev.system_preview, anthropic_key=ANTHROPIC_KEY)
                sb = get_supabase()
                if sb:
                    sb.table("ai_events").update(
                        {f"quality_{k}": v for k, v in scores.items()}
                    ).eq("event_id", ev.event_id).execute()
            except Exception as e:
                logger.warning("Eval error %s: %s", ev.event_id[:8], e)
    await asyncio.gather(*[eval_one(ev) for ev in events])
