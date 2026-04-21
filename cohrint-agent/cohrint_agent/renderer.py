"""
renderer.py — Live terminal rendering for streaming API responses and tool use.
"""
from __future__ import annotations

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text

from .sanitize import scrub_for_terminal, scrub_token

console = Console()


def render_text_delta(text: str) -> None:
    """Print streaming text delta (raw, no buffering)."""
    console.print(text, end="", highlight=False)


def render_text_complete(full_text: str) -> None:
    """After streaming completes, render the full text with markdown."""
    # The text was already streamed character by character,
    # so just add a newline for spacing.
    console.print()


def render_tool_use_start(tool_name: str, tool_input: dict) -> None:
    """Show that a tool is being invoked."""
    # scrub_* guards T-SAFETY.5/6/12: prompt-injected tool_input or tool_name
    # from Claude must not embed OSC-52 / CSI escapes in echoed terminal output.
    console.print()
    safe_name = scrub_token(tool_name)
    if tool_name == "Bash":
        cmd = scrub_for_terminal(tool_input.get("command", ""), max_len=150)
        console.print(f"  [dim]⚙ Bash:[/dim] {cmd}")
    elif tool_name == "Read":
        console.print(f"  [dim]⚙ Read:[/dim] {scrub_for_terminal(tool_input.get('file_path', ''))}")
    elif tool_name == "Write":
        fp = scrub_for_terminal(tool_input.get("file_path", ""))
        console.print(f"  [dim]⚙ Write:[/dim] {fp}")
    elif tool_name == "Edit":
        fp = scrub_for_terminal(tool_input.get("file_path", ""))
        console.print(f"  [dim]⚙ Edit:[/dim] {fp}")
    elif tool_name == "Glob":
        console.print(f"  [dim]⚙ Glob:[/dim] {scrub_for_terminal(tool_input.get('pattern', ''))}")
    elif tool_name == "Grep":
        pattern = scrub_for_terminal(tool_input.get("pattern", ""))
        path = scrub_for_terminal(tool_input.get("path", "."))
        console.print(f"  [dim]⚙ Grep:[/dim] {pattern} in {path}")
    else:
        console.print(f"  [dim]⚙ {safe_name}[/dim]")


def render_tool_result(tool_name: str, result: str, is_error: bool = False) -> None:
    """Show a brief tool result."""
    safe_name = scrub_token(tool_name)
    lines = result.strip().splitlines()
    preview_lines = 8

    if is_error:
        first = scrub_for_terminal(lines[0]) if lines else "(empty)"
        console.print(f"  [red]✗ {safe_name} error:[/red] {first}")
        return

    if len(lines) <= preview_lines:
        for line in lines:
            console.print(f"  [dim]│[/dim] {scrub_for_terminal(line)}")
    else:
        for line in lines[:preview_lines]:
            console.print(f"  [dim]│[/dim] {scrub_for_terminal(line)}")
        console.print(f"  [dim]│ ... ({len(lines)} lines total)[/dim]")
    console.print()


def render_thinking(text: str) -> None:
    """Show thinking/reasoning output."""
    console.print(f"  [dim italic]💭 {text[:200]}{'...' if len(text) > 200 else ''}[/dim italic]")


def render_cost_summary(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cost_usd: float,
    prompt_count: int,
    session_cost: float,
) -> None:
    """Print cost summary box."""
    console.print()
    console.print("  [dim]+----- Cost Summary -----+[/dim]")
    console.print(f"  [dim]Model:[/dim]             {model}")
    console.print(f"  [dim]Input tokens:[/dim]      {input_tokens:,}")
    console.print(f"  [dim]Output tokens:[/dim]     {output_tokens:,}")
    console.print(f"  [dim]Cost:[/dim]              [green]${cost_usd:.4f}[/green]")
    console.print(f"  [dim]Session total:[/dim]     [green]${session_cost:.4f}[/green]")
    console.print(f"  [dim]Prompts:[/dim]           {prompt_count}")
    console.print("  [dim]+-------------------------+[/dim]")
    console.print()


def render_permission_denied(tool_name: str) -> None:
    """Show that a tool was denied by the user."""
    console.print(f"  [red]✗ {tool_name} denied by user[/red]")


def render_error(msg: str) -> None:
    """Show an error message. Scrubs control chars + API keys (T-SAFETY.secret_scrub).

    SDK exception strings occasionally embed request/response headers,
    including ``Authorization: Bearer …``. Unconditionally running them
    through the scrubber prevents those from reaching the terminal.
    """
    from .sanitize import scrub_for_terminal
    console.print(f"  [red bold]Error:[/red bold] {scrub_for_terminal(msg)}")


def render_cost_summary_v2(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cost_usd: float,
    prompt_count: int,
    session_cost: float,
    token_count_confidence: str = "exact",   # "exact" | "estimated" | "free_tier"
    is_subscription: bool = False,
) -> None:
    """Print cost summary with confidence labels.

    - exact: no prefix, no label
    - estimated: ~ prefix + (estimated) label
    - free_tier: ~ prefix + (free tier) label
    - is_subscription: appends (subscription) regardless of confidence
    """
    prefix = "~" if token_count_confidence in ("estimated", "free_tier") else ""

    if token_count_confidence == "free_tier":
        cost_label = f"{prefix}$0.00 (free tier)"
        session_label = f"{prefix}$0.00 (free tier)"
    elif is_subscription:
        cost_label = f"{prefix}${cost_usd:.4f} (subscription)"
        session_label = f"{prefix}${session_cost:.4f} (subscription)"
    elif token_count_confidence == "estimated":
        cost_label = f"{prefix}${cost_usd:.4f} (estimated)"
        session_label = f"{prefix}${session_cost:.4f} (estimated)"
    else:
        cost_label = f"${cost_usd:.4f}"
        session_label = f"${session_cost:.4f}"

    console.print()
    console.print("  [dim]+----- Cost Summary -----+[/dim]")
    console.print(f"  [dim]Model:[/dim]             {model}")
    console.print(f"  [dim]Input tokens:[/dim]      {input_tokens:,}")
    console.print(f"  [dim]Output tokens:[/dim]     {output_tokens:,}")
    console.print(f"  [dim]Cost:[/dim]              [green]{cost_label}[/green]")
    console.print(f"  [dim]Session total:[/dim]     [green]{session_label}[/green]")
    console.print(f"  [dim]Prompts:[/dim]           {prompt_count}")
    console.print("  [dim]+-------------------------+[/dim]")
    console.print()
