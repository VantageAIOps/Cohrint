"""
cli.py — Vantage Agent CLI with interactive REPL.

Usage:
  vantageai-agent                          # Start interactive REPL
  vantageai-agent "fix the bug in main.py" # One-shot prompt
  vantageai-agent --model claude-opus-4-6  # Use a specific model
"""
from __future__ import annotations

import argparse
import os
import sys

from rich.console import Console

from .anomaly import check_cost_anomaly
from .api_client import AgentClient, DEFAULT_MODEL
from .rate_limiter import wait_for_token, get_global_budget_used
from .cost_tracker import SessionCost
from .optimizer import optimize_prompt, OptimizationResult
from .permissions import PermissionManager
from .renderer import render_cost_summary, render_error
from .tracker import Tracker, TrackerConfig
from .tools import TOOL_MAP

console = Console()

BANNER = """
  [bold]Vantage Agent[/bold] [dim]v0.1.0[/dim]
  [dim]AI coding agent with per-tool permissions, cost tracking & optimization[/dim]
  [dim]Model: {model}  |  CWD: {cwd}[/dim]

  [dim]Commands:[/dim]
    [bold]/help[/bold]              Show commands
    [bold]/allow[/bold] Tool        Approve a tool (e.g. /allow Bash,Write,Edit)
    [bold]/allow all[/bold]         Approve all tools
    [bold]/tools[/bold]             Show tool approval status
    [bold]/cost[/bold]              Show session cost
    [bold]/optimize[/bold] on|off   Toggle prompt optimization
    [bold]/reset[/bold]             Reset permissions & history
    [bold]/model[/bold] name        Switch model
    [bold]/quit[/bold]              Exit
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Vantage Agent — AI coding assistant with cost tracking"
    )
    parser.add_argument("prompt", nargs="*", help="One-shot prompt (skip REPL)")
    parser.add_argument("--model", default=None, help=f"Model ID (default: {DEFAULT_MODEL})")
    parser.add_argument("--max-tokens", type=int, default=16384, help="Max output tokens")
    parser.add_argument("--cwd", default=None, help="Working directory")
    parser.add_argument("--system", default=None, help="Custom system prompt")
    parser.add_argument("--no-optimize", action="store_true", help="Disable prompt optimization")
    parser.add_argument("--api-key", default=None, help="Anthropic API key (or set ANTHROPIC_API_KEY)")
    parser.add_argument("--vantage-key", default=None, help="VantageAI dashboard API key for telemetry")
    parser.add_argument("--debug", action="store_true", help="Enable debug output")
    parser.add_argument(
        "--backend",
        choices=["api", "claude", "codex", "gemini"],
        default=None,
        help="Backend to use. Auto-detected if not set.",
    )
    parser.add_argument(
        "--resume",
        metavar="SESSION_ID",
        default=None,
        help="Resume a previous session by ID.",
    )
    return parser.parse_args()


def _build_client(args: argparse.Namespace) -> tuple[AgentClient, Tracker | None]:
    model = args.model or os.environ.get("VANTAGE_MODEL", DEFAULT_MODEL)
    cwd = args.cwd or os.getcwd()
    permissions = PermissionManager()
    cost = SessionCost(model=model)

    if args.api_key:
        os.environ["ANTHROPIC_API_KEY"] = args.api_key

    client = AgentClient(
        model=model,
        max_tokens=args.max_tokens,
        permissions=permissions,
        cost=cost,
        cwd=cwd,
        system_prompt=args.system,
        optimization=not args.no_optimize,
    )

    # Dashboard tracker
    tracker = None
    vantage_key = args.vantage_key or os.environ.get("VANTAGE_API_KEY", "")
    if vantage_key:
        tracker = Tracker(TrackerConfig(api_key=vantage_key, debug=args.debug))
        tracker.start()

    return client, tracker


def _handle_command(line: str, client: AgentClient) -> bool:
    """Handle /commands. Returns True if handled, False if it's a prompt."""
    stripped = line.strip()

    if stripped in ("/quit", "/exit", "/q"):
        return True  # Signal exit

    if stripped == "/help":
        console.print(BANNER.format(model=client.model, cwd=client.cwd))
        return True

    if stripped == "/tools":
        session, always = client.permissions.status()
        console.print("\n  [bold]Tool Permissions:[/bold]")
        all_tools = sorted(TOOL_MAP.keys())
        for t in all_tools:
            if t in always:
                console.print(f"    [green]✓ {t}[/green] [dim](always)[/dim]")
            elif t in session:
                console.print(f"    [yellow]✓ {t}[/yellow] [dim](this session)[/dim]")
            else:
                console.print(f"    [red]✗ {t}[/red] [dim](will prompt)[/dim]")
        console.print()
        return True

    if stripped.startswith("/allow"):
        parts = stripped.split(None, 1)
        if len(parts) < 2:
            console.print("  [dim]Usage: /allow Tool1,Tool2 or /allow all[/dim]")
            return True
        tool_names = [t.strip() for t in parts[1].split(",")]
        if tool_names == ["all"]:
            tool_names = list(TOOL_MAP.keys())
        unknown = [t for t in tool_names if t not in TOOL_MAP]
        if unknown:
            console.print(f"  [red]Unknown tools: {', '.join(unknown)}[/red]")
            console.print(f"  [dim]Available: {', '.join(sorted(TOOL_MAP.keys()))}[/dim]")
            return True
        client.permissions.approve(tool_names, always=True)
        console.print(f"  [green]✓ Approved: {', '.join(tool_names)}[/green]")
        return True

    if stripped == "/cost":
        c = client.cost
        render_cost_summary(
            model=c.model,
            input_tokens=c.total_input,
            output_tokens=c.total_output,
            cost_usd=c.total_cost_usd,
            prompt_count=c.prompt_count,
            session_cost=c.total_cost_usd,
        )
        return True

    if stripped == "/reset":
        client.permissions.reset()
        client.clear_history()
        client.cost = SessionCost(model=client.model)
        console.print("  [yellow]Reset: permissions, history, and cost cleared[/yellow]")
        return True

    if stripped.startswith("/optimize"):
        parts = stripped.split(None, 1)
        if len(parts) < 2:
            state = "on" if client.optimization else "off"
            console.print(f"  [dim]Optimization: {state}[/dim]")
            return True
        flag = parts[1].strip().lower()
        client.optimization = flag in ("on", "true", "1", "yes")
        console.print(f"  [green]Optimization: {'on' if client.optimization else 'off'}[/green]")
        return True

    if stripped.startswith("/model"):
        parts = stripped.split(None, 1)
        if len(parts) < 2:
            console.print(f"  [dim]Current model: {client.model}[/dim]")
            return True
        new_model = parts[1].strip()
        client.model = new_model
        client.cost.model = new_model
        console.print(f"  [green]Switched to {new_model}[/green]")
        return True

    if stripped.startswith("/"):
        console.print(f"  [red]Unknown command: {stripped.split()[0]}[/red]")
        return True

    return False


def run_repl(client: AgentClient, tracker: Tracker | None = None) -> None:
    """Interactive REPL."""
    console.print(BANNER.format(model=client.model, cwd=client.cwd))

    while True:
        try:
            console.print()
            line = console.input("[bold cyan]vantage>[/bold cyan] ")
        except (EOFError, KeyboardInterrupt):
            console.print("\n  [dim]Goodbye.[/dim]")
            break

        if not line.strip():
            continue

        # Handle /commands
        if line.strip().startswith("/"):
            if line.strip() in ("/quit", "/exit", "/q"):
                # Show final cost
                c = client.cost
                if c.prompt_count > 0:
                    render_cost_summary(
                        model=c.model,
                        input_tokens=c.total_input,
                        output_tokens=c.total_output,
                        cost_usd=c.total_cost_usd,
                        prompt_count=c.prompt_count,
                        session_cost=c.total_cost_usd,
                    )
                if tracker:
                    tracker.stop()
                console.print("  [dim]Goodbye.[/dim]")
                break
            _handle_command(line, client)
            continue

        # Send prompt to API
        try:
            # Rate-limit check
            if not wait_for_token():
                console.print("[yellow]Rate limit reached — waiting...[/yellow]")
            # Global budget guard
            budget = float(os.environ.get("VANTAGE_BUDGET_USD", "0"))
            if budget > 0 and get_global_budget_used() >= budget:
                console.print(f"[red]Global budget of ${budget:.2f} reached across all sessions.[/red]")
                continue
            prior_total = client.cost.total_cost_usd
            prior_count = client.cost.prompt_count - 1  # before this prompt
            client.send(line)
            # Show per-turn cost + anomaly check
            if client.cost.turns:
                last = client.cost.turns[-1]
                console.print(
                    f"  [dim]↳ {last.input_tokens + last.output_tokens:,} tokens · ${last.cost_usd:.4f}[/dim]"
                )
                check_cost_anomaly(last.cost_usd, prior_total, prior_count)
                if tracker:
                    tracker.record(
                        model=client.model,
                        input_tokens=last.input_tokens,
                        output_tokens=last.output_tokens,
                        cost_usd=last.cost_usd,
                        latency_ms=0,
                    )
        except KeyboardInterrupt:
            console.print("\n  [yellow]Interrupted[/yellow]")
        except Exception as e:
            render_error(str(e))


def run_oneshot(client: AgentClient, prompt: str, tracker: Tracker | None = None) -> None:
    """One-shot mode: send prompt, print result, exit."""
    try:
        # Rate-limit check
        if not wait_for_token():
            console.print("[yellow]Rate limit reached — waiting...[/yellow]")
        # Global budget guard
        budget = float(os.environ.get("VANTAGE_BUDGET_USD", "0"))
        if budget > 0 and get_global_budget_used() >= budget:
            console.print(f"[red]Global budget of ${budget:.2f} reached across all sessions.[/red]")
            return
        client.send(prompt)
        c = client.cost
        render_cost_summary(
            model=c.model,
            input_tokens=c.total_input,
            output_tokens=c.total_output,
            cost_usd=c.total_cost_usd,
            prompt_count=c.prompt_count,
            session_cost=c.total_cost_usd,
        )
        if tracker and c.turns:
            last = c.turns[-1]
            tracker.record(
                model=client.model,
                input_tokens=last.input_tokens,
                output_tokens=last.output_tokens,
                cost_usd=last.cost_usd,
                latency_ms=0,
            )
            tracker.stop()
    except KeyboardInterrupt:
        console.print("\n  [yellow]Interrupted[/yellow]")
    except Exception as e:
        render_error(str(e))
        sys.exit(1)


def _print_summary() -> None:
    """Print aggregated cost summary across all sessions."""
    from .session_store import SessionStore
    store = SessionStore()
    sessions = store.list_all()
    if not sessions:
        console.print("  [dim]No sessions found.[/dim]")
        return
    total = store.total_cost_usd()
    console.print(f"\n  [bold]Sessions:[/bold] {len(sessions)}  |  [bold]Total cost:[/bold] ${total:.4f}\n")
    for s in sessions[:10]:
        sid = s.get("id", "?")[:8]
        backend = s.get("backend", "?")
        cost = s.get("cost_summary", {}).get("total_cost_usd", 0.0)
        msgs = len(s.get("messages", []))
        ts = s.get("last_active_at", "")[:16]
        console.print(f"  {sid}  [dim]{backend:8s}[/dim]  {msgs // 2:3d} turns  [green]${cost:.4f}[/green]  {ts}")
    console.print()


def main() -> None:
    # Handle `vantageai-agent summary` before argparse (avoids positional arg conflict)
    if len(sys.argv) > 1 and sys.argv[1] == "summary":
        _print_summary()
        return

    args = parse_args()

    # Show backend in banner
    if args.backend:
        console.print(f"  [dim]backend:[/dim] {args.backend}")
    elif args.resume:
        console.print(f"  [dim]resuming session:[/dim] {args.resume[:8]}...")

    try:
        client, tracker = _build_client(args)
    except ValueError as e:
        render_error(str(e))
        sys.exit(1)

    prompt = " ".join(args.prompt) if args.prompt else ""

    if prompt:
        run_oneshot(client, prompt, tracker)
    elif sys.stdin.isatty():
        run_repl(client, tracker)
    else:
        # Pipe mode: read stdin
        prompt = sys.stdin.read().strip()
        if prompt:
            run_oneshot(client, prompt, tracker)


if __name__ == "__main__":
    main()
