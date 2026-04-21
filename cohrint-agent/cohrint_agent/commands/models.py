"""
commands.models — list supported + unsupported models.

Source of truth: ``cohrint_agent.pricing.MODEL_PRICES``. That table drives
both cost computation and this listing, so a new model added to pricing
automatically appears here.
"""
from __future__ import annotations

import argparse
import sys

from rich.console import Console
from rich.table import Table

from ..pricing import MODEL_PRICES

console = Console()


# Models we route to but don't (yet) have live pricing rows for. Adding an
# entry here surfaces it under `cohrint-agent models --unsupported`.
UNSUPPORTED_MODELS: tuple[tuple[str, str, str], ...] = (
    # (model_id, backend, note)
    ("gemini-2.5-ultra",       "gemini", "announced, pricing TBD"),
    ("gpt-5",                  "codex",  "expected Q3 2026"),
    ("claude-sonnet-5",        "claude", "in internal preview"),
)


def _backend_of(model_id: str) -> str:
    lower = model_id.lower()
    if lower.startswith("claude"):
        return "claude"
    if lower.startswith("gpt") or lower.startswith("o1") or lower.startswith("o3"):
        return "codex"
    if lower.startswith("gemini"):
        return "gemini"
    if lower.startswith("llama") or lower.startswith("mistral") or lower.startswith("deepseek") or lower.startswith("grok"):
        return "api"
    return "api"


def _print_supported() -> None:
    table = Table(title="Supported models", show_header=True, header_style="bold")
    table.add_column("Model")
    table.add_column("Backend")
    table.add_column("$/1M in", justify="right")
    table.add_column("$/1M out", justify="right")
    table.add_column("$/1M cache", justify="right")

    for model_id, prices in sorted(MODEL_PRICES.items()):
        if model_id == "default":
            continue
        table.add_row(
            model_id,
            _backend_of(model_id),
            f"${prices['input']:.2f}",
            f"${prices['output']:.2f}",
            f"${prices['cache']:.2f}",
        )
    console.print(table)


def _print_unsupported() -> None:
    table = Table(title="Routable but not priced", show_header=True, header_style="bold")
    table.add_column("Model")
    table.add_column("Backend")
    table.add_column("Note", style="dim")
    for model_id, backend, note in UNSUPPORTED_MODELS:
        table.add_row(model_id, backend, note)
    console.print(table)
    console.print("\n[dim]Using one of these falls back to the 'default' price row (claude-sonnet-4-6 rates).[/dim]")


def _print_info(model_id: str) -> int:
    prices = MODEL_PRICES.get(model_id)
    if prices is None:
        # Try prefix match (consistent with pricing._resolve_model)
        for key in MODEL_PRICES:
            if model_id.startswith(key):
                prices = MODEL_PRICES[key]
                model_id = f"{model_id} (resolved → {key})"
                break
    if prices is None:
        console.print(f"[red]No pricing data for '{model_id}'.[/red]")
        console.print("Run `cohrint-agent models` to see the full supported list.")
        return 2

    console.print(f"[bold]{model_id}[/bold]")
    console.print(f"  backend:      {_backend_of(model_id)}")
    console.print(f"  input:        ${prices['input']:.4f}/1M tokens")
    console.print(f"  output:       ${prices['output']:.4f}/1M tokens")
    console.print(f"  cache read:   ${prices.get('cache_read', prices['cache']):.4f}/1M tokens")
    console.print(f"  cache write:  ${prices.get('cache_write', 0.0):.4f}/1M tokens")
    return 0


def run(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="cohrint-agent models",
        description="List supported models across all backends.",
    )
    parser.add_argument("--unsupported", action="store_true", help="Show models we route but don't price.")
    sub = parser.add_subparsers(dest="subcommand")
    info = sub.add_parser("info", help="Show detail for a specific model.")
    info.add_argument("model_id")

    ns = parser.parse_args(argv)

    if ns.subcommand == "info":
        return _print_info(ns.model_id)
    if ns.unsupported:
        _print_unsupported()
        return 0
    _print_supported()
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(run(sys.argv[1:]))
