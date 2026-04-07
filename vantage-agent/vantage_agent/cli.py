"""
cli.py — Vantage Agent CLI with interactive REPL.

Usage:
  vantage-agent                          # Start interactive REPL
  vantage-agent "fix the bug in main.py" # One-shot prompt
  vantage-agent --model claude-opus-4-6  # Use a specific model
"""
from __future__ import annotations

import argparse
import os
import sys

from rich.console import Console

from .api_client import AgentClient, DEFAULT_MODEL
from .cost_tracker import SessionCost
from .permissions import PermissionManager
from .renderer import render_cost_summary, render_error
from .tools import TOOL_MAP

console = Console()

BANNER = """
  [bold]Vantage Agent[/bold] [dim]v0.1.0[/dim]
  [dim]AI coding agent with per-tool permissions & cost tracking[/dim]
  [dim]Model: {model}  |  CWD: {cwd}[/dim]

  [dim]Commands:[/dim]
    [bold]/help[/bold]          Show commands
    [bold]/allow[/bold] Tool    Approve a tool (e.g. /allow Bash,Write)
    [bold]/tools[/bold]         Show tool approval status
    [bold]/cost[/bold]          Show session cost
    [bold]/reset[/bold]         Reset permissions & history
    [bold]/model[/bold] name    Switch model
    [bold]/quit[/bold]          Exit
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
    return parser.parse_args()


def _build_client(args: argparse.Namespace) -> AgentClient:
    model = args.model or os.environ.get("VANTAGE_MODEL", DEFAULT_MODEL)
    cwd = args.cwd or os.getcwd()
    permissions = PermissionManager()
    cost = SessionCost(model=model)

    return AgentClient(
        model=model,
        max_tokens=args.max_tokens,
        permissions=permissions,
        cost=cost,
        cwd=cwd,
        system_prompt=args.system,
    )


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


def run_repl(client: AgentClient) -> None:
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
                console.print("  [dim]Goodbye.[/dim]")
                break
            _handle_command(line, client)
            continue

        # Send prompt to API
        try:
            client.send(line)
            # Show per-turn cost
            if client.cost.turns:
                last = client.cost.turns[-1]
                console.print(
                    f"  [dim]↳ {last.input_tokens + last.output_tokens:,} tokens · ${last.cost_usd:.4f}[/dim]"
                )
        except KeyboardInterrupt:
            console.print("\n  [yellow]Interrupted[/yellow]")
        except Exception as e:
            render_error(str(e))


def run_oneshot(client: AgentClient, prompt: str) -> None:
    """One-shot mode: send prompt, print result, exit."""
    try:
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
    except KeyboardInterrupt:
        console.print("\n  [yellow]Interrupted[/yellow]")
    except Exception as e:
        render_error(str(e))
        sys.exit(1)


def main() -> None:
    args = parse_args()

    try:
        client = _build_client(args)
    except ValueError as e:
        render_error(str(e))
        sys.exit(1)

    prompt = " ".join(args.prompt) if args.prompt else ""

    if prompt:
        run_oneshot(client, prompt)
    elif sys.stdin.isatty():
        run_repl(client)
    else:
        # Pipe mode: read stdin
        prompt = sys.stdin.read().strip()
        if prompt:
            run_oneshot(client, prompt)


if __name__ == "__main__":
    main()
