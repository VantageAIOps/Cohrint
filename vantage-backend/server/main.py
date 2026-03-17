"""
Vantage AI — Complete FastAPI Ingest + Analytics Server v1.0
"""
from __future__ import annotations
import asyncio, hashlib, logging, os, time
from contextlib import asynccontextmanager
from typing import Optional
from fastapi import FastAPI, HTTPException, Request, Depends, BackgroundTasks, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("vantage")

SUPABASE_URL  = os.getenv("SUPABASE_URL",  "https://oyljzpvwdfktrkeotmon.supabase.co")
SUPABASE_KEY  = os.getenv("SUPABASE_SERVICE_KEY", "")
ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY", "")
EVAL_ENABLED  = os.getenv("EVAL_ENABLED", "true").lower() == "true"
EVAL_SAMPLE   = float(os.getenv("EVAL_SAMPLE_RATE", "0.2"))

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
    logger.info("Vantage ready — DB:%s Eval:%s Model:claude-opus-4-6",
                "✓" if sb else "dev", EVAL_ENABLED)
    yield

app = FastAPI(title="Vantage AI API", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
security = HTTPBearer(auto_error=False)

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

class EventIn(BaseModel):
    event_id: str; timestamp: float; org_id: str = ""; environment: str = "production"
    provider: str = ""; model: str = ""; endpoint: str = ""; session_id: str = ""
    user_id: str = ""; feature: str = ""; project: str = ""; team: str = ""
    tags: dict = Field(default_factory=dict)
    latency_ms: float = 0; ttft_ms: float = 0; status_code: int = 200; error: Optional[str] = None
    usage_prompt_tokens: int = 0; usage_completion_tokens: int = 0
    usage_total_tokens: int = 0; usage_cached_tokens: int = 0; usage_system_prompt_tokens: int = 0
    cost_input_cost_usd: float = 0; cost_output_cost_usd: float = 0
    cost_total_cost_usd: float = 0; cost_cheapest_model: str = ""
    cost_cheapest_cost_usd: float = 0; cost_potential_saving_usd: float = 0
    request_preview: str = ""; response_preview: str = ""; system_preview: str = ""; prompt_hash: str = ""

class BatchIn(BaseModel):
    events: list[EventIn]; sdk_version: str = "unknown"

@app.get("/health")
async def health():
    return {"status":"ok","supabase":"connected" if get_supabase() else "dev","eval_enabled":EVAL_ENABLED,"eval_model":"claude-opus-4-6","ts":time.time()}

@app.post("/v1/events", status_code=202)
async def ingest(batch: BatchIn, bg: BackgroundTasks, org: str = Depends(require_org)):
    if not batch.events: return {"accepted":0}
    if len(batch.events) > 500: raise HTTPException(400,"Max 500 events/batch")
    for ev in batch.events: ev.org_id = org
    bg.add_task(_store_events, batch.events)
    if EVAL_ENABLED and ANTHROPIC_KEY:
        import random
        to_eval = [e for e in batch.events if random.random() < EVAL_SAMPLE]
        if to_eval: bg.add_task(_evaluate_batch, to_eval)
    return {"accepted":len(batch.events),"org_id":org,"sdk_version":batch.sdk_version}

@app.get("/v1/kpis/{org_id}")
async def kpis(org_id:str, days:int=Query(30,ge=1,le=365), org:str=Depends(require_org)):
    _chk(org,org_id); return await get_analytics().get_kpis(org_id,days)

@app.get("/v1/timeseries/{org_id}")
async def timeseries(org_id:str, days:int=Query(30,ge=1,le=365), granularity:str="day", org:str=Depends(require_org)):
    _chk(org,org_id); return await get_analytics().get_timeseries(org_id,days,granularity)

@app.get("/v1/models/{org_id}")
async def models(org_id:str, days:int=Query(30,ge=1,le=365), org:str=Depends(require_org)):
    _chk(org,org_id); return await get_analytics().get_model_breakdown(org_id,days)

@app.get("/v1/teams/{org_id}")
async def teams(org_id:str, days:int=Query(30,ge=1,le=365), org:str=Depends(require_org)):
    _chk(org,org_id); return await get_analytics().get_team_breakdown(org_id,days)

@app.get("/v1/projects/{org_id}")
async def projects(org_id:str, days:int=Query(30,ge=1,le=365), org:str=Depends(require_org)):
    _chk(org,org_id); return await get_analytics().get_project_breakdown(org_id,days)

@app.get("/v1/hallucination/{org_id}")
async def hallucination(org_id:str, days:int=Query(30,ge=1,le=365), org:str=Depends(require_org)):
    _chk(org,org_id); return await get_analytics().get_hallucination_report(org_id,days)

@app.get("/v1/efficiency/{org_id}")
async def efficiency(org_id:str, days:int=Query(30,ge=1,le=365), org:str=Depends(require_org)):
    _chk(org,org_id); return await get_analytics().get_efficiency_report(org_id,days)

@app.get("/v1/latency/{org_id}")
async def latency(org_id:str, days:int=Query(30,ge=1,le=365), org:str=Depends(require_org)):
    _chk(org,org_id); return await get_analytics().get_latency_report(org_id,days)

@app.get("/v1/chargeback/{org_id}")
async def chargeback(org_id:str, days:int=Query(30,ge=1,le=365), org:str=Depends(require_org)):
    _chk(org,org_id); return await get_analytics().get_chargeback_report(org_id,days)

@app.get("/v1/user/{org_id}/{user_id}")
async def user_report(org_id:str, user_id:str, days:int=Query(30,ge=1,le=365), org:str=Depends(require_org)):
    _chk(org,org_id); return await get_analytics().get_user_report(org_id,user_id,days)

async def _store_events(events: list[EventIn]):
    sb = get_supabase()
    if not sb: return
    rows = [ev.model_dump() for ev in events]
    try:
        for i in range(0,len(rows),100):
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
            R[key] = {"org_id":ev.org_id,"date":d,"model":ev.model,
                      "provider":ev.provider,"team":ev.team,"project":ev.project,
                      "request_count":0,"prompt_tokens":0,"completion_tokens":0,
                      "total_cost_usd":0.0,"error_count":0,"total_latency_ms":0.0}
        r = R[key]
        r["request_count"]     += 1
        r["prompt_tokens"]     += ev.usage_prompt_tokens
        r["completion_tokens"] += ev.usage_completion_tokens
        r["total_cost_usd"]    += ev.cost_total_cost_usd
        r["total_latency_ms"]  += ev.latency_ms
        if ev.status_code >= 400: r["error_count"] += 1
    try:
        vals = list(R.values())
        for i in range(0,len(vals),50):
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
                        {f"quality_{k}":v for k,v in scores.items()}
                    ).eq("event_id", ev.event_id).execute()
                    logger.debug("Eval %s hal=%.3f q=%.1f", ev.event_id[:8],
                                 scores.get("hallucination_score",0), scores.get("overall_quality",0))
            except Exception as e:
                logger.warning("Eval error %s: %s", ev.event_id[:8], e)
    await asyncio.gather(*[eval_one(ev) for ev in events])
