"""
anomaly.py — Cost anomaly detection.

Flags prompts that cost >3x the session average.
Ported from vantage-cli/src/anomaly.ts.
"""
from __future__ import annotations

from rich.console import Console

console = Console()

MIN_AVG_COST = 0.001  # $0.001 minimum average before flagging


def check_cost_anomaly(
    current_cost: float,
    prior_total: float,
    prior_count: int,
) -> bool:
    """
    Check if current prompt cost is anomalously high.
    Returns True if anomaly detected.
    """
    if prior_count < 2 or prior_total <= 0:
        return False
    avg = prior_total / prior_count
    if avg < MIN_AVG_COST:
        return False
    if current_cost > avg * 3:
        console.print(
            f"  [yellow]⚠ Anomaly: this prompt cost ${current_cost:.4f} "
            f"— {current_cost / avg:.1f}x your session average[/yellow]"
        )
        return True
    return False
