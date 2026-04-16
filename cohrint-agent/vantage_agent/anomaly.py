"""
anomaly.py — Cost anomaly detection.

Returns a structured AnomalyResult instead of printing directly.
The caller decides how to render it.
"""
from __future__ import annotations

from dataclasses import dataclass

MIN_AVG_COST = 0.001  # $0.001 minimum average before flagging


@dataclass
class AnomalyResult:
    detected: bool
    current_cost: float
    avg_cost: float
    ratio: float


def check_cost_anomaly_structured(
    current_cost: float,
    prior_total: float,
    prior_count: int,
) -> AnomalyResult:
    """
    Check if current prompt cost is anomalously high (>3x session average).
    Returns AnomalyResult — does NOT print side effects.
    """
    if prior_count < 2 or prior_total <= 0:
        return AnomalyResult(detected=False, current_cost=current_cost, avg_cost=0.0, ratio=0.0)
    avg = prior_total / prior_count
    if avg < MIN_AVG_COST:
        return AnomalyResult(detected=False, current_cost=current_cost, avg_cost=avg, ratio=0.0)
    ratio = current_cost / avg
    return AnomalyResult(
        detected=ratio > 3.0,
        current_cost=current_cost,
        avg_cost=avg,
        ratio=ratio,
    )


# ---------------------------------------------------------------------------
# Legacy shim — keeps existing callers and tests working
# ---------------------------------------------------------------------------
from rich.console import Console as _Console

_console = _Console()


def check_cost_anomaly(current_cost: float, prior_total: float, prior_count: int) -> bool:
    """Legacy interface: prints directly and returns bool. Use check_cost_anomaly_structured instead."""
    result = check_cost_anomaly_structured(current_cost, prior_total, prior_count)
    if result.detected:
        _console.print(
            f"  [yellow]⚠ Anomaly: this prompt cost ${result.current_cost:.4f} "
            f"— {result.ratio:.1f}x your session average[/yellow]"
        )
    return result.detected
