"""
vantage/server/analytics.py
----------------------------
Tier-aware analytics engine.

Individual  (1 user)        → personal usage, cost, model comparison
Team        (2-10 users)    → per-member breakdown + team rollup
Enterprise  (1000+ users)   → department/project/org-level + chargeback

All queries go through Supabase using the service-role key (bypasses RLS).
Dashboard calls these via /v1/analytics/* routes.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger("vantage.analytics")


class AnalyticsEngine:
    """Single entry point for all dashboard analytics queries."""

    def __init__(self, supabase_client):
        self.sb = supabase_client

    # ────────────────────────────────────────────────────────────────────────
    # KPI SUMMARY  (top cards on dashboard)
    # ────────────────────────────────────────────────────────────────────────
    async def get_kpis(self, org_id: str, days: int = 30) -> dict:
        """
        Returns the 8 top-level KPI cards:
        total_cost, tokens, requests, avg_latency, error_rate,
        avg_quality, avg_hallucination, potential_savings
        """
        rows = self._query_events(org_id, days, cols=[
            "cost_total_cost_usd", "usage_total_tokens", "latency_ms",
            "status_code", "quality_overall_quality",
            "quality_hallucination_score", "cost_potential_saving_usd",
            "ttft_ms",
        ])

        prev_rows = self._query_events(org_id, days * 2, cols=[
            "cost_total_cost_usd",
        ], end_days=days)

        n = len(rows)
        prev_n = len(prev_rows)
        if n == 0:
            return self._empty_kpis()

        total_cost    = sum(r["cost_total_cost_usd"]   or 0 for r in rows)
        total_tokens  = sum(r["usage_total_tokens"]    or 0 for r in rows)
        total_savings = sum(r["cost_potential_saving_usd"] or 0 for r in rows)
        avg_latency   = sum(r["latency_ms"]            or 0 for r in rows) / n
        errors        = sum(1 for r in rows if (r.get("status_code") or 200) >= 400)

        q_rows = [r for r in rows if (r.get("quality_overall_quality") or -1) >= 0]
        h_rows = [r for r in rows if (r.get("quality_hallucination_score") or -1) >= 0]
        avg_quality   = sum(r["quality_overall_quality"]     for r in q_rows) / len(q_rows) if q_rows else 0
        avg_halluc    = sum(r["quality_hallucination_score"] for r in h_rows) / len(h_rows) if h_rows else 0

        # WoW / period-over-period change
        prev_cost = sum(r["cost_total_cost_usd"] or 0 for r in prev_rows)
        cost_change_pct = ((total_cost - prev_cost) / prev_cost * 100) if prev_cost else 0

        # Efficiency score: 0-100
        cached_tokens = sum(r.get("usage_cached_tokens", 0) or 0 for r in rows)
        cache_rate    = cached_tokens / total_tokens if total_tokens else 0
        sys_tokens    = sum(r.get("usage_system_prompt_tokens", 0) or 0 for r in rows)
        sys_overhead  = sys_tokens / total_tokens if total_tokens else 0
        efficiency    = max(0, min(100, 100 - sys_overhead * 60 + cache_rate * 20))

        return {
            "total_cost_usd":      round(total_cost, 4),
            "total_tokens":        total_tokens,
            "total_requests":      n,
            "avg_latency_ms":      round(avg_latency, 1),
            "error_rate_pct":      round(errors / n * 100, 2),
            "avg_quality":         round(avg_quality, 2),
            "avg_hallucination":   round(avg_halluc * 100, 2),   # as percentage
            "potential_savings_usd": round(total_savings, 4),
            "efficiency_score":    round(efficiency, 1),
            "cache_hit_rate_pct":  round(cache_rate * 100, 1),
            "cost_change_pct":     round(cost_change_pct, 1),
            "evaluated_count":     len(q_rows),
            "period_days":         days,
        }

    # ────────────────────────────────────────────────────────────────────────
    # TIME SERIES  (charts)
    # ────────────────────────────────────────────────────────────────────────
    async def get_timeseries(self, org_id: str, days: int = 30,
                              granularity: str = "day") -> dict:
        rows = self._query_events(org_id, days, cols=[
            "timestamp", "cost_total_cost_usd", "usage_total_tokens",
            "latency_ms", "quality_hallucination_score",
            "quality_overall_quality", "status_code",
        ])

        buckets: dict[str, dict] = {}
        for r in rows:
            ts  = r.get("timestamp") or 0
            dt  = datetime.fromtimestamp(ts, tz=timezone.utc)
            key = dt.strftime("%Y-%m-%d") if granularity == "day" else dt.strftime("%Y-%m-%d %H:00")
            if key not in buckets:
                buckets[key] = {
                    "date": key, "cost": 0, "tokens": 0,
                    "requests": 0, "errors": 0,
                    "latency_sum": 0, "halluc_sum": 0, "halluc_n": 0,
                }
            b = buckets[key]
            b["cost"]      += r.get("cost_total_cost_usd") or 0
            b["tokens"]    += r.get("usage_total_tokens")  or 0
            b["requests"]  += 1
            b["latency_sum"] += r.get("latency_ms") or 0
            if (r.get("status_code") or 200) >= 400: b["errors"] += 1
            h = r.get("quality_hallucination_score") or -1
            if h >= 0:
                b["halluc_sum"] += h
                b["halluc_n"]   += 1

        series = []
        for key in sorted(buckets):
            b = buckets[key]
            n = b["requests"]
            series.append({
                "date":              b["date"],
                "cost_usd":          round(b["cost"], 4),
                "tokens":            b["tokens"],
                "requests":          n,
                "avg_latency_ms":    round(b["latency_sum"] / n, 1) if n else 0,
                "error_rate_pct":    round(b["errors"] / n * 100, 2) if n else 0,
                "avg_hallucination": round(b["halluc_sum"] / b["halluc_n"] * 100, 2) if b["halluc_n"] else None,
            })
        return {"series": series, "granularity": granularity}

    # ────────────────────────────────────────────────────────────────────────
    # MODEL BREAKDOWN
    # ────────────────────────────────────────────────────────────────────────
    async def get_model_breakdown(self, org_id: str, days: int = 30) -> list[dict]:
        rows = self._query_events(org_id, days, cols=[
            "model", "provider", "cost_total_cost_usd", "usage_total_tokens",
            "usage_prompt_tokens", "usage_completion_tokens", "usage_cached_tokens",
            "latency_ms", "ttft_ms", "status_code",
            "quality_overall_quality", "quality_hallucination_score",
            "cost_potential_saving_usd",
        ])
        return self._group_rows(rows, "model", extra_keys=["provider"])

    # ────────────────────────────────────────────────────────────────────────
    # TEAM BREAKDOWN (works for individual too — single team)
    # ────────────────────────────────────────────────────────────────────────
    async def get_team_breakdown(self, org_id: str, days: int = 30) -> dict:
        """
        Returns per-team stats + top model per team + top user per team.
        Scales from 1-user individual to 1000+ enterprise.
        """
        rows = self._query_events(org_id, days, cols=[
            "team", "user_id", "model", "project",
            "cost_total_cost_usd", "usage_total_tokens",
            "latency_ms", "status_code",
            "quality_overall_quality", "quality_hallucination_score",
            "cost_potential_saving_usd",
        ])

        # Group by team
        teams = self._group_rows(rows, "team")

        # Top model per team
        for team_name, team_data in teams.items():
            team_rows  = [r for r in rows if (r.get("team") or "untagged") == team_name]
            model_grp  = self._group_rows(team_rows, "model")
            user_grp   = self._group_rows(team_rows, "user_id")
            proj_grp   = self._group_rows(team_rows, "project")

            team_data["top_model"]    = max(model_grp.items(), key=lambda x: x[1]["cost"], default=("", {}))[0]
            team_data["top_user"]     = max(user_grp.items(),  key=lambda x: x[1]["cost"], default=("", {}))[0]
            team_data["project_count"]= len(proj_grp)
            team_data["models_used"]  = len(model_grp)
            team_data["cost_share_pct"] = 0  # filled below

        # Cost share per team
        total_cost = sum(t.get("cost", 0) for t in teams.values()) or 1
        for t in teams.values():
            t["cost_share_pct"] = round(t.get("cost", 0) / total_cost * 100, 1)

        return {
            "teams": teams,
            "total_teams": len(teams),
            "total_cost_usd": round(total_cost, 4),
        }

    # ────────────────────────────────────────────────────────────────────────
    # PROJECT / FEATURE BREAKDOWN
    # ────────────────────────────────────────────────────────────────────────
    async def get_project_breakdown(self, org_id: str, days: int = 30) -> dict:
        rows = self._query_events(org_id, days, cols=[
            "project", "feature", "team", "model",
            "cost_total_cost_usd", "usage_total_tokens",
            "latency_ms", "status_code",
            "quality_overall_quality", "quality_hallucination_score",
        ])
        return {
            "by_project": self._group_rows(rows, "project"),
            "by_feature":  self._group_rows(rows, "feature"),
        }

    # ────────────────────────────────────────────────────────────────────────
    # HALLUCINATION REPORT  (uses Claude Opus 4.6 scores)
    # ────────────────────────────────────────────────────────────────────────
    async def get_hallucination_report(self, org_id: str, days: int = 30) -> dict:
        rows = self._query_events(org_id, days, cols=[
            "model", "provider", "team", "project", "feature",
            "quality_hallucination_score", "quality_hallucination_type",
            "quality_hallucination_detail", "quality_factuality_score",
            "quality_overall_quality", "quality_evaluated_by",
        ], filter_evaluated=True)

        if not rows:
            return {"status": "no_evaluations_yet", "data": {}}

        total   = len(rows)
        flagged = [r for r in rows if (r.get("quality_hallucination_score") or 0) > 0.3]

        # By type
        type_counts: dict[str, int] = {}
        for r in rows:
            t = r.get("quality_hallucination_type") or "unknown"
            type_counts[t] = type_counts.get(t, 0) + 1

        # By model
        by_model = {}
        for r in rows:
            m = r.get("model") or "unknown"
            if m not in by_model:
                by_model[m] = {"total": 0, "flagged": 0, "score_sum": 0, "provider": r.get("provider","")}
            by_model[m]["total"]     += 1
            by_model[m]["score_sum"] += r.get("quality_hallucination_score") or 0
            if (r.get("quality_hallucination_score") or 0) > 0.3:
                by_model[m]["flagged"] += 1
        for m, v in by_model.items():
            v["hallucination_rate_pct"] = round(v["flagged"] / v["total"] * 100, 1)
            v["avg_score"]              = round(v["score_sum"] / v["total"], 4)
            del v["score_sum"]

        # By team
        by_team = {}
        for r in rows:
            t = r.get("team") or "untagged"
            if t not in by_team:
                by_team[t] = {"total": 0, "flagged": 0, "score_sum": 0}
            by_team[t]["total"]     += 1
            by_team[t]["score_sum"] += r.get("quality_hallucination_score") or 0
            if (r.get("quality_hallucination_score") or 0) > 0.3:
                by_team[t]["flagged"] += 1
        for v in by_team.values():
            v["hallucination_rate_pct"] = round(v["flagged"] / v["total"] * 100, 1)
            v["avg_score"]              = round(v["score_sum"] / v["total"], 4)
            del v["score_sum"]

        # Risk level
        overall_rate = len(flagged) / total
        risk_level = "low" if overall_rate < 0.05 else "medium" if overall_rate < 0.15 else "high"

        return {
            "total_evaluated":       total,
            "flagged_count":         len(flagged),
            "overall_rate_pct":      round(overall_rate * 100, 2),
            "risk_level":            risk_level,
            "by_type":               type_counts,
            "by_model":              by_model,
            "by_team":               by_team,
            "evaluated_by":          "claude-opus-4-6",
        }

    # ────────────────────────────────────────────────────────────────────────
    # EFFICIENCY REPORT
    # ────────────────────────────────────────────────────────────────────────
    async def get_efficiency_report(self, org_id: str, days: int = 30) -> dict:
        rows = self._query_events(org_id, days, cols=[
            "endpoint", "feature", "team", "model",
            "usage_prompt_tokens", "usage_completion_tokens",
            "usage_cached_tokens", "usage_system_prompt_tokens",
            "usage_total_tokens", "cost_total_cost_usd",
            "cost_potential_saving_usd", "prompt_hash",
            "quality_prompt_efficiency_score",
        ])

        if not rows:
            return {"total_waste_usd": 0, "recommendations": []}

        total_cost    = sum(r.get("cost_total_cost_usd") or 0 for r in rows)
        total_savings = sum(r.get("cost_potential_saving_usd") or 0 for r in rows)
        total_tokens  = sum(r.get("usage_total_tokens") or 0 for r in rows)
        cached        = sum(r.get("usage_cached_tokens") or 0 for r in rows)
        sys_tokens    = sum(r.get("usage_system_prompt_tokens") or 0 for r in rows)
        cache_rate    = cached / total_tokens if total_tokens else 0

        # System prompt waste per endpoint
        by_endpoint: dict[str, dict] = {}
        for r in rows:
            ep = r.get("endpoint") or r.get("feature") or "unknown"
            if ep not in by_endpoint:
                by_endpoint[ep] = {
                    "total_tokens": 0, "system_tokens": 0,
                    "cached_tokens": 0, "cost": 0,
                    "requests": 0, "unique_hashes": set(),
                }
            b = by_endpoint[ep]
            b["total_tokens"]   += r.get("usage_total_tokens") or 0
            b["system_tokens"]  += r.get("usage_system_prompt_tokens") or 0
            b["cached_tokens"]  += r.get("usage_cached_tokens") or 0
            b["cost"]           += r.get("cost_total_cost_usd") or 0
            b["requests"]       += 1
            ph = r.get("prompt_hash")
            if ph: b["unique_hashes"].add(ph)

        recommendations = []
        for ep, b in by_endpoint.items():
            sys_pct     = b["system_tokens"] / b["total_tokens"] * 100 if b["total_tokens"] else 0
            cache_opp   = len(b["unique_hashes"]) / b["requests"] if b["requests"] else 1
            hit_rate    = b["cached_tokens"] / b["total_tokens"] * 100 if b["total_tokens"] else 0
            monthly_cost = b["cost"] * 30 / max(days, 1)

            if sys_pct > 30:
                recommendations.append({
                    "type": "trim_system_prompt",
                    "endpoint": ep,
                    "message": f"System prompt is {sys_pct:.0f}% of tokens — recommend trimming to <500 tokens",
                    "estimated_saving_usd": round(monthly_cost * sys_pct / 100 * 0.5, 2),
                    "priority": "high" if sys_pct > 50 else "medium",
                })
            if cache_opp < 0.3 and hit_rate < 20 and b["requests"] > 50:
                recommendations.append({
                    "type": "enable_caching",
                    "endpoint": ep,
                    "message": f"High prompt repetition detected ({(1-cache_opp)*100:.0f}% repeated) — enable prompt caching",
                    "estimated_saving_usd": round(monthly_cost * 0.35, 2),
                    "priority": "high",
                })

            b["system_prompt_pct"]  = round(sys_pct, 1)
            b["cache_hit_rate_pct"] = round(hit_rate, 1)
            b["requests_per_hash"]  = round(b["requests"] / len(b["unique_hashes"]), 1) if b["unique_hashes"] else b["requests"]
            del b["unique_hashes"]

        recommendations.sort(key=lambda x: x["estimated_saving_usd"], reverse=True)

        return {
            "total_cost_usd":          round(total_cost, 4),
            "total_savings_available_usd": round(total_savings, 4),
            "savings_pct":             round(total_savings / total_cost * 100, 1) if total_cost else 0,
            "cache_hit_rate_pct":      round(cache_rate * 100, 1),
            "system_prompt_overhead_pct": round(sys_tokens / total_tokens * 100, 1) if total_tokens else 0,
            "by_endpoint":             by_endpoint,
            "recommendations":         recommendations[:10],
        }

    # ────────────────────────────────────────────────────────────────────────
    # LATENCY REPORT
    # ────────────────────────────────────────────────────────────────────────
    async def get_latency_report(self, org_id: str, days: int = 30) -> dict:
        rows = self._query_events(org_id, days, cols=[
            "model", "provider", "team", "latency_ms", "ttft_ms",
            "status_code", "usage_completion_tokens",
        ])

        if not rows: return {}

        def percentiles(values: list[float]) -> dict:
            s = sorted(values)
            n = len(s)
            return {
                "p50": round(s[int(n * 0.50)], 1),
                "p75": round(s[int(n * 0.75)], 1),
                "p95": round(s[int(n * 0.95)], 1),
                "p99": round(s[min(int(n * 0.99), n-1)], 1),
                "avg": round(sum(s) / n, 1),
            }

        all_lat   = [r["latency_ms"] for r in rows if r.get("latency_ms")]
        all_ttft  = [r["ttft_ms"]    for r in rows if r.get("ttft_ms")]

        by_model: dict[str, list] = {}
        for r in rows:
            m = r.get("model") or "unknown"
            if m not in by_model: by_model[m] = []
            if r.get("latency_ms"): by_model[m].append(r["latency_ms"])

        return {
            "overall":  percentiles(all_lat) if all_lat else {},
            "ttft":     percentiles(all_ttft) if all_ttft else {},
            "by_model": {m: percentiles(lats) for m, lats in by_model.items() if len(lats) >= 5},
        }

    # ────────────────────────────────────────────────────────────────────────
    # CHARGEBACK REPORT  (enterprise)
    # ────────────────────────────────────────────────────────────────────────
    async def get_chargeback_report(self, org_id: str, days: int = 30) -> list[dict]:
        """CFO-ready per-team/project cost attribution."""
        team_data = await self.get_team_breakdown(org_id, days)
        proj_data = await self.get_project_breakdown(org_id, days)

        rows = []
        for team, stats in team_data.get("teams", {}).items():
            rows.append({
                "team":            team,
                "cost_usd":        round(stats.get("cost", 0), 4),
                "requests":        stats.get("requests", 0),
                "tokens":          stats.get("tokens", 0),
                "cost_per_request": round(stats.get("cost", 0) / stats.get("requests", 1), 6),
                "avg_latency_ms":  stats.get("avg_latency_ms", 0),
                "avg_quality":     stats.get("avg_quality", 0),
                "avg_hallucination_pct": round(stats.get("avg_hallucination", 0) * 100, 2),
                "top_model":       stats.get("top_model", ""),
                "cost_share_pct":  stats.get("cost_share_pct", 0),
                "projects":        stats.get("project_count", 0),
            })

        rows.sort(key=lambda x: x["cost_usd"], reverse=True)
        return rows

    # ────────────────────────────────────────────────────────────────────────
    # USER-LEVEL REPORT  (individual tier)
    # ────────────────────────────────────────────────────────────────────────
    async def get_user_report(self, org_id: str, user_id: str, days: int = 30) -> dict:
        """Personal stats for individual developers."""
        rows = self._query_events(org_id, days, cols=[
            "model", "provider", "endpoint", "feature",
            "cost_total_cost_usd", "usage_total_tokens",
            "latency_ms", "quality_overall_quality",
            "quality_hallucination_score", "cost_potential_saving_usd",
        ], user_id=user_id)

        if not rows:
            return {"status": "no_data", "user_id": user_id}

        total_cost    = sum(r.get("cost_total_cost_usd") or 0 for r in rows)
        total_tokens  = sum(r.get("usage_total_tokens") or 0 for r in rows)
        total_savings = sum(r.get("cost_potential_saving_usd") or 0 for r in rows)

        by_model  = self._group_rows(rows, "model", extra_keys=["provider"])
        by_feature = self._group_rows(rows, "feature")

        top_model = max(by_model.items(), key=lambda x: x[1]["cost"], default=("", {}))[0]
        cheapest  = min(by_model.items(), key=lambda x: x[1]["cost_per_request"], default=("", {}))[0]

        return {
            "user_id":           user_id,
            "total_cost_usd":    round(total_cost, 4),
            "total_tokens":      total_tokens,
            "total_requests":    len(rows),
            "potential_savings": round(total_savings, 4),
            "top_model":         top_model,
            "cheapest_model":    cheapest,
            "by_model":          by_model,
            "by_feature":        by_feature,
        }

    # ────────────────────────────────────────────────────────────────────────
    # INTERNAL HELPERS
    # ────────────────────────────────────────────────────────────────────────
    def _query_events(
        self, org_id: str, days: int,
        cols: list[str], end_days: int = 0,
        user_id: Optional[str] = None,
        filter_evaluated: bool = False,
    ) -> list[dict]:
        try:
            q = (self.sb.table("ai_events")
                        .select(",".join(cols))
                        .eq("org_id", org_id)
                        .gte("timestamp", f"extract(epoch from now() - interval '{days} days')"))
            if end_days:
                q = q.lte("timestamp", f"extract(epoch from now() - interval '{end_days} days')")
            if user_id:
                q = q.eq("user_id", user_id)
            if filter_evaluated:
                q = q.gte("quality_hallucination_score", 0)
            result = q.limit(100_000).execute()
            return result.data or []
        except Exception as e:
            logger.error("Analytics query error: %s", e)
            return []

    def _group_rows(
        self, rows: list[dict], key: str,
        extra_keys: Optional[list[str]] = None,
    ) -> dict:
        groups: dict[str, dict] = {}
        for r in rows:
            k = str(r.get(key) or "untagged")
            if k not in groups:
                groups[k] = {
                    "cost": 0.0, "tokens": 0, "requests": 0,
                    "latency_sum": 0.0, "errors": 0,
                    "quality_sum": 0.0, "quality_n": 0,
                    "halluc_sum": 0.0,  "halluc_n": 0,
                    "savings_sum": 0.0,
                }
                if extra_keys:
                    for ek in extra_keys:
                        groups[k][ek] = r.get(ek, "")
            g = groups[k]
            g["cost"]        += r.get("cost_total_cost_usd")   or 0
            g["tokens"]      += r.get("usage_total_tokens")    or 0
            g["requests"]    += 1
            g["latency_sum"] += r.get("latency_ms")            or 0
            g["savings_sum"] += r.get("cost_potential_saving_usd") or 0
            if (r.get("status_code") or 200) >= 400: g["errors"] += 1
            q = r.get("quality_overall_quality") or -1
            if q >= 0:
                g["quality_sum"] += q
                g["quality_n"]   += 1
            h = r.get("quality_hallucination_score") or -1
            if h >= 0:
                g["halluc_sum"] += h
                g["halluc_n"]   += 1

        for k, g in groups.items():
            n = g["requests"] or 1
            g["avg_latency_ms"]      = round(g["latency_sum"] / n, 1)
            g["error_rate_pct"]      = round(g["errors"] / n * 100, 2)
            g["avg_quality"]         = round(g["quality_sum"] / g["quality_n"], 2) if g["quality_n"] else 0
            g["avg_hallucination_pct"] = round(g["halluc_sum"] / g["halluc_n"] * 100, 2) if g["halluc_n"] else 0
            g["potential_savings_usd"] = round(g["savings_sum"], 4)
            g["cost_per_request"]    = round(g["cost"] / n, 8)
            g["cost"]                = round(g["cost"], 4)
            del g["latency_sum"], g["errors"], g["quality_sum"], g["quality_n"]
            del g["halluc_sum"], g["halluc_n"], g["savings_sum"]

        return groups

    def _empty_kpis(self) -> dict:
        return {k: 0 for k in [
            "total_cost_usd","total_tokens","total_requests","avg_latency_ms",
            "error_rate_pct","avg_quality","avg_hallucination","potential_savings_usd",
            "efficiency_score","cache_hit_rate_pct","cost_change_pct","evaluated_count","period_days",
        ]}
