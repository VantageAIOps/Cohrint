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


def render_thinking(text: str, max_chars: int = 500) -> None:
    """Show thinking/reasoning output.

    Extended-thinking blocks can run for thousands of chars, so we cap the
    preview. The cut falls on the nearest whitespace before ``max_chars``
    so the truncated line doesn't end mid-word — the old hard 200-char
    slice produced cliffhangers like "...never i..." in the terminal.
    """
    snippet = text.strip()
    if len(snippet) <= max_chars:
        console.print(f"  [dim italic]💭 {snippet}[/dim italic]")
        return
    cut = snippet.rfind(" ", 0, max_chars)
    # If the text has no whitespace within the window (pathological — one
    # giant token), fall back to the hard cap so we still emit something.
    if cut < max_chars // 2:
        cut = max_chars
    trimmed = snippet[:cut].rstrip(" ,;:.!?")
    console.print(f"  [dim italic]💭 {trimmed}…[/dim italic]")


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


def render_optimization_preview(result, model: str | None) -> None:
    """Pre-send block: show the user the header stats + the actual
    optimized prompt text (in dim) before dispatch to the model.

    We intentionally do NOT render the algorithmic change list
    (``result.changes``) — exposing which internal layers ran
    ("removed filler phrases: …", "rewrote verbose phrases …") leaks
    optimizer internals and clutters the screen. Showing the
    compressed prompt text itself is far more informative and visually
    cleaner.

    Silent when there were no savings — clean prompts shouldn't be
    penalised with a noisy 0-line banner.
    """
    from .optimizer import OptimizationResult, estimated_cost_saved
    if not isinstance(result, OptimizationResult):
        return
    if result.saved_tokens <= 0:
        return

    cost_saved = estimated_cost_saved(result, model)
    header = (
        f"  [dim]⚡ Optimized {result.original_tokens}→{result.optimized_tokens} tokens "
        f"({result.saved_percent}% saved · ${cost_saved:.4f} saved)[/dim]"
    )
    console.print()
    console.print(header)

    # Show the optimized prompt text in dim, preceded by a visual
    # indent rail. Cap at ~600 chars so a multi-KB prompt doesn't
    # dominate the pre-send view — we cut on a word boundary to avoid
    # the "hallucin…" style mid-word truncation from earlier UX.
    preview = result.optimized.strip()
    max_chars = 600
    if len(preview) > max_chars:
        cut = preview.rfind(" ", 0, max_chars)
        if cut < max_chars // 2:
            cut = max_chars
        preview = preview[:cut].rstrip(" ,;:.!?") + "…"

    # Scrub once, then render line-by-line so multi-paragraph prompts
    # still look structured (each line gets its own dim rail).
    safe = scrub_for_terminal(preview, max_len=max_chars + 2)
    for line in safe.splitlines() or [""]:
        console.print(f"  [dim]│ {line}[/dim]")


class _WaitingSpinner:
    """Live spinner shown between a prompt dispatch and the first backend
    event (subprocess boot + first-token latency). Stays tight: single
    line, dim colour, elapsed-seconds counter so users can tell the CLI
    is alive without distracting from the answer that follows.

    Usage:
        with make_waiting_spinner("Thinking"):
            event = backend.get_first_event()  # blocks 1-3s
            # spinner auto-clears on __exit__; callers may also call
            # stop_immediate() to clear *before* printing first output.
    """

    def __init__(self, label: str) -> None:
        self._label = label
        self._status = None
        self._started = False
        self._start_time: float | None = None

    def __enter__(self) -> "_WaitingSpinner":
        import time
        self._start_time = time.monotonic()
        # console.is_terminal is False in pipes / CI / tests — skip the
        # live status in that case so ANSI escapes don't leak into logs.
        if console.is_terminal:
            try:
                self._status = console.status(
                    f"[dim]⏳ {self._label}…[/dim]", spinner="dots"
                )
                self._status.__enter__()
                self._started = True
            except Exception:
                self._status = None
        return self

    def stop_immediate(self) -> None:
        """Clear the spinner now (before the exiting `with` fires). Safe
        to call multiple times — idempotent after first stop."""
        if self._started and self._status is not None:
            try:
                self._status.__exit__(None, None, None)
            except Exception:
                pass
            self._started = False
            self._status = None

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.stop_immediate()


def make_waiting_spinner(label: str = "Thinking") -> _WaitingSpinner:
    """Return a context-manager spinner that fills the silent gap between
    prompt send and first backend output. Auto-no-op in non-TTY."""
    return _WaitingSpinner(label)


def render_assistant_header(label: str) -> None:
    """Stage marker printed just before the assistant's streamed text begins.

    Mirrors the `── <Name> ──` separators Claude Code / Codex use to split
    thinking, tool calls, and the final answer.
    """
    safe = scrub_token(label or "assistant")
    display = {
        "claude": "Claude",
        "api": "Claude",
        "codex": "Codex",
        "gemini": "Gemini",
    }.get(safe, safe)
    console.print()
    console.print(f"  [bold cyan]── {display} ──────────────────────────────────[/bold cyan]")


def render_cohrint_analysis(
    *,
    optimization,
    model: str | None,
    guardrail_hedge_detected: bool,
    guardrail_active: list[str],
    anomaly_line: str | None,
    recommendation: str | None,
    turn_input_tokens: int,
    turn_output_tokens: int,
    turn_cost_usd: float,
    session_cost_usd: float,
    cache_saved_usd: float = 0.0,
    cache_read_tokens: int = 0,
) -> None:
    """Post-response analysis block — shown once Claude's answer is complete.

    Aggregates the three cohrint signals (optimization savings, hallucination
    guardrail result, cost anomaly) plus the recommendation tip into a single
    aligned block. Every row is optional: we only emit rows backed by real
    data so quiet turns stay visually quiet.
    """
    from .optimizer import OptimizationResult, estimated_cost_saved
    lines: list[str] = []

    if isinstance(optimization, OptimizationResult) and optimization.saved_tokens > 0:
        cost_saved = estimated_cost_saved(optimization, model)
        lines.append(
            f"⚡ Tokens saved:      {optimization.saved_tokens} "
            f"({optimization.saved_percent}%)"
        )
        lines.append(f"💰 Cost saved:        ${cost_saved:.4f}")

    if cache_saved_usd > 0:
        lines.append(
            f"🗂  Cache saved:       ${cache_saved_usd:.4f} "
            f"({cache_read_tokens:,} tokens)"
        )

    if "hallucination" in guardrail_active:
        if guardrail_hedge_detected:
            lines.append(
                "🛡 Hallucination:     model declined to fabricate — verify independently"
            )
        else:
            lines.append(
                "🛡 Hallucination:     no hedge detected — double-check facts, APIs, paths"
            )

    if anomaly_line:
        lines.append(f"⚠ Anomaly:           {scrub_for_terminal(anomaly_line, max_len=160)}")

    if recommendation:
        lines.append(f"💡 Recommendation:    {scrub_for_terminal(recommendation, max_len=160)}")

    total_turn_tokens = turn_input_tokens + turn_output_tokens
    lines.append(
        f"↳ {total_turn_tokens:,} tokens · ${turn_cost_usd:.4f} this turn · "
        f"session ${session_cost_usd:.4f}"
    )

    console.print()
    console.print("  [dim]── Cohrint analysis ───────────────────────────[/dim]")
    for line in lines:
        console.print(f"  [dim]{line}[/dim]")


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
