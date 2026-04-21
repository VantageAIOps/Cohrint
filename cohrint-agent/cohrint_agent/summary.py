"""
summary.py — REPL /summary command.

Renders a Savings & Session block that combines:
  - In-memory session totals (prompts, tokens, cost)
  - Optimization savings (total_saved_tokens, total_saved_usd from SessionCost)
  - Cache savings + wasted cost pulled from /v1/analytics/kpis

Ports the JS path in cohrint-cli/src/index.ts:909-933. Every field coming back
from the dashboard is numerically coerced and clamped — the terminal never
sees a raw server-controlled string, so a compromised kpis endpoint cannot
inject escape sequences.

Guards regression test T-SUMMARY.1.
"""
from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass

from .update_check import _assert_https_api_base

_KPIS_MAX_BYTES = 128 * 1024
_TIMEOUT_SEC = 3.0


@dataclass
class KpiSavings:
    cache_savings_usd: float = 0.0
    cache_tokens_total: int = 0
    cache_hit_rate_pct: float = 0.0
    duplicate_calls: int = 0
    wasted_cost_usd: float = 0.0


def _coerce_float(value: object, *, lo: float = 0.0, hi: float = 1e12) -> float:
    try:
        v = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
    if v != v or v in (float("inf"), float("-inf")):
        return 0.0
    return max(lo, min(hi, v))


def _coerce_int(value: object, *, lo: int = 0, hi: int = 10**12) -> int:
    try:
        v = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        try:
            v = int(float(value))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return 0
    return max(lo, min(hi, v))


def fetch_kpis(
    api_base: str,
    api_key: str | None,
    *,
    timeout: float = _TIMEOUT_SEC,
) -> KpiSavings | None:
    """Fetch + validate /v1/analytics/kpis. Returns None on any failure."""
    if not api_key:
        return None
    if not _assert_https_api_base(api_base):
        return None
    url = api_base.rstrip("/") + "/v1/analytics/kpis"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "User-Agent": "cohrint-agent/summary",
        },
        method="GET",
    )
    try:
        ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            if getattr(resp, "status", 200) != 200:
                return None
            raw = resp.read(_KPIS_MAX_BYTES + 1)
            if len(raw) > _KPIS_MAX_BYTES:
                return None
            data = json.loads(raw.decode("utf-8", errors="strict"))
    except (urllib.error.URLError, urllib.error.HTTPError, ssl.SSLError):
        return None
    except (json.JSONDecodeError, UnicodeDecodeError, TimeoutError, OSError):
        return None
    except Exception:  # noqa: BLE001
        return None

    if not isinstance(data, dict):
        return None

    return KpiSavings(
        cache_savings_usd=_coerce_float(data.get("cache_savings_usd")),
        cache_tokens_total=_coerce_int(data.get("cache_tokens_total")),
        cache_hit_rate_pct=_coerce_float(data.get("cache_hit_rate_pct"), hi=100.0),
        duplicate_calls=_coerce_int(data.get("duplicate_calls")),
        wasted_cost_usd=_coerce_float(data.get("wasted_cost_usd")),
    )


@dataclass
class BudgetStatus:
    budget_usd: float = 0.0
    budget_pct: float = 0.0
    mtd_cost_usd: float = 0.0


def fetch_budget(
    api_base: str,
    api_key: str | None,
    *,
    timeout: float = _TIMEOUT_SEC,
) -> BudgetStatus | None:
    """Fetch + validate /v1/analytics/summary. Returns None on any failure."""
    if not api_key:
        return None
    if not _assert_https_api_base(api_base):
        return None
    url = api_base.rstrip("/") + "/v1/analytics/summary"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "User-Agent": "cohrint-agent/budget",
        },
        method="GET",
    )
    try:
        ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            if getattr(resp, "status", 200) != 200:
                return None
            raw = resp.read(_KPIS_MAX_BYTES + 1)
            if len(raw) > _KPIS_MAX_BYTES:
                return None
            data = json.loads(raw.decode("utf-8", errors="strict"))
    except (urllib.error.URLError, urllib.error.HTTPError, ssl.SSLError):
        return None
    except (json.JSONDecodeError, UnicodeDecodeError, TimeoutError, OSError):
        return None
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(data, dict):
        return None
    return BudgetStatus(
        budget_usd=_coerce_float(data.get("budget_usd")),
        budget_pct=_coerce_float(data.get("budget_pct"), hi=10_000.0),
        mtd_cost_usd=_coerce_float(data.get("mtd_cost_usd")),
    )


def render_budget(console, status: BudgetStatus | None) -> None:
    """Print /budget output — matches cohrint-cli index.ts:238-252."""
    console.print()
    if status is None:
        console.print("  [yellow]No API key configured — set COHRINT_API_KEY.[/yellow]")
        console.print()
        return
    if status.budget_usd <= 0:
        console.print("  [yellow]No budget set. Configure in dashboard → Settings.[/yellow]")
        console.print()
        return
    # Threshold colors match the Node implementation exactly:
    # > 85%: red, > 60%: yellow, else green.
    if status.budget_pct > 85:
        color = "red"
    elif status.budget_pct > 60:
        color = "yellow"
    else:
        color = "green"
    remaining = status.budget_usd - status.mtd_cost_usd
    console.print("  [bold]Budget Status[/bold]")
    console.print(f"  [dim]Monthly budget:[/dim] ${status.budget_usd:.2f}")
    console.print(f"  [dim]MTD spend:[/dim]      ${status.mtd_cost_usd:.4f}")
    console.print(f"  [dim]Used:[/dim]           [{color}]{status.budget_pct:.1f}%[/{color}]")
    if remaining > 0:
        console.print(f"  [dim]Remaining:[/dim]      [green]${remaining:.2f}[/green]")
    else:
        console.print("  [dim]Remaining:[/dim]      [red]OVER BUDGET[/red]")
    # 80% warning (not a color threshold — separate advisory line).
    if status.budget_pct >= 100:
        console.print("\n  [red]⚠ OVER BUDGET — spending exceeds monthly limit![/red]")
    elif status.budget_pct >= 80:
        console.print("\n  [yellow]⚠ Budget warning — 80% threshold exceeded[/yellow]")
    console.print()


def render_summary(console, cost, kpis: KpiSavings | None) -> None:
    """Print the Savings & Session block to the given rich Console."""
    console.print()
    console.print("  [bold]Session Summary[/bold]")
    console.print(f"  [dim]Model:[/dim] {cost.model}")
    console.print(
        f"  [dim]Prompts:[/dim] {cost.prompt_count}"
        f"  [dim]Tokens:[/dim] {cost.total_input + cost.total_output:,}"
        f"  [dim]Cost:[/dim] ${cost.total_cost_usd:.4f}"
    )

    has_opt = cost.total_saved_tokens > 0 or cost.total_saved_usd > 0
    has_cache = bool(kpis) and (
        kpis.cache_savings_usd > 0
        or kpis.cache_tokens_total > 0
        or kpis.cache_hit_rate_pct > 0
    )
    has_waste = bool(kpis) and (kpis.duplicate_calls > 0 or kpis.wasted_cost_usd > 0)

    if not (has_opt or has_cache or has_waste):
        console.print()
        return

    console.print("  [dim]" + ("-" * 45) + "[/dim]")
    console.print("  [bold]Savings[/bold]")
    if has_opt:
        console.print(
            f"  [dim]Optimization:[/dim] [green]${cost.total_saved_usd:.4f}[/green]"
            f" · [green]{cost.total_saved_tokens:,}[/green] tokens"
        )
    if has_cache:
        console.print(
            f"  [dim]Cache:[/dim] [green]${kpis.cache_savings_usd:.4f}[/green]"
            f" · [green]{kpis.cache_tokens_total:,}[/green] tokens"
            f" ([green]{kpis.cache_hit_rate_pct:.1f}%[/green] hit)"
        )
    if has_waste:
        console.print(
            f"  [dim]Wasted (dupes):[/dim] [yellow]${kpis.wasted_cost_usd:.4f}[/yellow]"
            f" · {kpis.duplicate_calls} duplicate calls"
        )
    console.print()
