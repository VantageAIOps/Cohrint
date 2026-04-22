"""
cli.py — Cohrint Agent CLI with interactive REPL.

Usage:
  cohrint-agent                          # Start interactive REPL
  cohrint-agent "fix the bug in main.py" # One-shot prompt
  cohrint-agent --model claude-opus-4-6  # Use a specific model
"""
from __future__ import annotations

import argparse
import os
import sys

from pathlib import Path

from rich.console import Console
from rich.prompt import Prompt

from . import __version__
from .anomaly import check_cost_anomaly
from .api_client import AgentClient, DEFAULT_MODEL
from .backends import auto_detect_backend
from .rate_limiter import wait_for_token, get_global_budget_used
from .cost_tracker import SessionCost
from .optimizer import optimize_prompt, OptimizationResult
from .permission_server import PermissionServer, install_hook_script
from .permissions import PermissionManager
from .renderer import render_cost_summary, render_error
from .setup_wizard import needs_setup, run_setup_wizard, apply_tier, get_config, write_config
from .tracker import Tracker, TrackerConfig
from .tools import TOOL_MAP
from .sanitize import scrub_token
from .update_check import check_for_update, DEFAULT_API_BASE

console = Console()


def _parse_budget_env(raw: str | None) -> float:
    """Parse COHRINT_BUDGET_USD safely. Reject NaN/inf/negative/zero.

    bare float() accepts ``"inf"``/``"nan"`` which silently disable the
    budget gate: ``nan > 0`` is False and ``inf`` is never exceeded. We
    require a finite, strictly positive, sanely-bounded number — anything
    else falls back to 0 (gate inert, same as if unset).
    """
    import math
    try:
        v = float(raw) if raw is not None else 0.0
    except (ValueError, TypeError):
        return 0.0
    if math.isnan(v) or math.isinf(v):
        return 0.0
    if not (0.0 < v < 1e9):
        return 0.0
    return v

BANNER = """
  [bold]Cohrint Agent[/bold] [dim]v{version}[/dim]
  [dim]AI coding agent with per-tool permissions, cost tracking & optimization[/dim]
  [dim]Model: {model}  |  CWD: {cwd}[/dim]
  [dim]Optimization: {optimization}  |  Guardrails: {guardrails}[/dim]

  [dim]REPL commands:[/dim]
    [bold]/help[/bold]              Show commands
    [bold]/allow[/bold] Tool        Approve a tool (e.g. /allow Bash,Write,Edit)
    [bold]/allow all[/bold]         Approve all tools
    [bold]/tools[/bold]             Show tool approval status
    [bold]/cost[/bold]              Show session cost
    [bold]/optimize[/bold] on|off   Toggle prompt optimization
    [bold]/tier[/bold]              Change tool permission tier
    [bold]/reset[/bold]             Reset permissions & history
    [bold]/model[/bold] name        Switch model
    [bold]/guardrails[/bold] on|off Toggle recommendation + hallucination guardrails
    [bold]/verbs[/bold]             Show all verbs (mcp/skills/agents/…)
    [bold]/quit[/bold]              Exit

  [dim]Shell verbs — also invokable in REPL as `/<verb> …` or `cohrint-agent <verb>`:[/dim]
{verbs}
  [dim]Run `cohrint-agent help` for full catalog.[/dim]
"""


_HEDGE_PHRASES = (
    "i don't know", "i do not know", "i'm not sure", "i am not sure",
    "i can't verify", "i cannot verify", "i can't confirm", "i cannot confirm",
    "i'm unable to verify", "i am unable to verify", "i cannot guarantee",
    "doesn't exist", "does not exist", "isn't a real", "is not a real",
    "no such", "not a valid", "not an actual", "fabricat", "hallucin",
    "i don't have access", "i do not have access", "i recommend verifying",
    "please verify", "you should verify", "i'd recommend checking",
    "i would recommend checking", "i suggest verifying", "check the official",
    "refer to the official", "consult the documentation",
)


def _detect_hedge(text: str) -> bool:
    """Return True if the response contains hallucination-avoidance language."""
    lower = text.lower()
    return any(phrase in lower for phrase in _HEDGE_PHRASES)


def _verb_summary_lines() -> str:
    """Render one line per verb from the catalog — shown in the REPL banner."""
    from .commands import CATALOG
    lines: list[str] = []
    for spec in CATALOG.values():
        lines.append(f"    [bold]{spec.name:<12}[/bold] {spec.summary}")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Cohrint Agent — AI coding assistant with cost tracking"
    )
    parser.add_argument("prompt", nargs="*", help="One-shot prompt (skip REPL)")
    parser.add_argument("--model", default=None, help=f"Model ID (default: {DEFAULT_MODEL})")
    parser.add_argument("--max-tokens", type=int, default=16384, help="Max output tokens")
    parser.add_argument("--cwd", default=None, help="Working directory")
    parser.add_argument("--system", default=None, help="Custom system prompt")
    parser.add_argument("--no-optimize", action="store_true", help="Disable prompt optimization")
    parser.add_argument("--api-key", default=None, help="Anthropic API key (or set ANTHROPIC_API_KEY)")
    parser.add_argument("--cohrint-key", default=None, help="Cohrint dashboard API key for telemetry")
    parser.add_argument("--debug", action="store_true", help="Enable debug output")
    parser.add_argument("--version", action="version", version=f"cohrint-agent {__version__}")
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


def _detect_backend(api_key: str | None, requested_backend: str | None) -> str:
    """Determine which backend to use. Returns 'api' or 'claude' (or other CLI)."""
    if requested_backend:
        return requested_backend
    effective_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
    if effective_key:
        return "api"
    try:
        detected = auto_detect_backend()
        return detected
    except RuntimeError:
        return "api"  # will fail naturally in AgentClient with helpful message


def _handle_tier_command(
    permissions: PermissionManager,
    config_dir: Path | None = None,
) -> None:
    """Handle /tier REPL command — show tier menu, apply selection."""
    run_setup_wizard(permissions=permissions, config_dir=config_dir)


class _ClaudeCliClient:
    """Thin wrapper around ClaudeCliBackend with same interface as AgentClient."""

    def __init__(self, backend, permissions, perm_server, model, cost, cwd):
        from .backends.claude_backend import ClaudeCliBackend
        self.backend: ClaudeCliBackend = backend
        self.permissions = permissions
        self.perm_server = perm_server
        self.model = model
        self.cost = cost
        self.cwd = cwd
        self.optimization = True

    def send(self, prompt: str, no_optimize: bool = False) -> str:
        actual_prompt = prompt
        # Run optimization silently — results stored for post-response display
        self._last_opt_result: object = None

        if self.optimization and not no_optimize:
            opt = optimize_prompt(prompt)
            actual_prompt = opt.optimized
            self._last_opt_result = opt

        from .guardrails import get_settings as _get_gs, system_preamble as _preamble
        _gs = _get_gs()
        _active = [k for k, v in (("hallucination", _gs.hallucination), ("recommendation", _gs.recommendation)) if v]
        self._last_guardrail_active = _active
        if _active:
            preamble = _preamble()
            if preamble:
                actual_prompt = preamble + "\n\n" + actual_prompt

        # Pre-send: show what the optimizer stripped — only emits when there
        # were real savings, so clean prompts stay visually quiet.
        from .renderer import render_optimization_preview
        if isinstance(self._last_opt_result, OptimizationResult):
            render_optimization_preview(self._last_opt_result, self.model)

        result = self.backend.send(prompt=actual_prompt, history=[], cwd=self.cwd)
        self.cost.record_usage_raw(
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            cost_usd=result.cost_usd,
            cache_read_tokens=getattr(result, "cache_read_tokens", 0),
        )
        return result.output_text

    def clear_history(self) -> None:
        self.backend._claude_session_id = None

    def stop(self) -> None:
        self.perm_server.stop()
        self.permissions.clear_session_approved()


def _build_client(args: argparse.Namespace):
    model = args.model or os.environ.get("COHRINT_MODEL", DEFAULT_MODEL)
    cwd = args.cwd or os.getcwd()
    from .process_safety import safe_config_dir
    config_dir = safe_config_dir()
    permissions = PermissionManager(config_dir=config_dir)
    cost = SessionCost(model=model)

    if args.api_key:
        os.environ["ANTHROPIC_API_KEY"] = args.api_key

    backend_name = _detect_backend(
        api_key=args.api_key,
        requested_backend=getattr(args, "backend", None),
    )

    # Dashboard tracker
    tracker = None
    cohrint_key = args.cohrint_key or os.environ.get("COHRINT_API_KEY", "")
    if cohrint_key:
        tracker = Tracker(TrackerConfig(api_key=cohrint_key, debug=args.debug))
        tracker.start()
    # Stash on the client so /summary can reach the dashboard without re-parsing args.
    _stash_key = cohrint_key or None

    if backend_name == "claude":
        # First-run wizard for Claude CLI backend (only if stdin is a tty)
        if needs_setup(config_dir=config_dir) and sys.stdin.isatty():
            try:
                run_setup_wizard(permissions=permissions, config_dir=config_dir)
            except (EOFError, KeyboardInterrupt):
                apply_tier(2, permissions)  # safe default: Read/Glob/Grep/Edit/Write
        # Start permission server. Use a private mode-0700 run dir under
        # the config directory instead of a world-writable /tmp path —
        # /tmp/cohrint-perm-<PID>.sock is guessable from `ps` and lets any
        # local user pre-place a symlink to hijack the bind (T-SAFETY.tmp_path).
        run_dir = config_dir / "run"
        run_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            os.chmod(run_dir, 0o700)
        except OSError:
            pass
        sock_path = str(run_dir / f"perm-{os.getpid()}.sock")
        perm_server = PermissionServer(socket_path=sock_path, permissions=permissions)
        perm_server.start()
        # Build ClaudeCliBackend
        from .backends.claude_backend import ClaudeCliBackend
        backend = ClaudeCliBackend(
            model=model,
            config_dir=config_dir,
            permission_server=perm_server,
        )
        backend.prepare_session_settings(pid=os.getpid())
        client = _ClaudeCliClient(
            backend=backend,
            permissions=permissions,
            perm_server=perm_server,
            model=model,
            cost=cost,
            cwd=cwd,
        )
        client._cohrint_key = _stash_key  # type: ignore[attr-defined]
        return client, tracker

    if backend_name not in (None, "api"):
        console.print(f"  [yellow]Backend '{backend_name}' selected. Note: this backend has limited tool-use support.[/yellow]")

    client = AgentClient(
        model=model,
        max_tokens=args.max_tokens,
        permissions=permissions,
        cost=cost,
        cwd=cwd,
        system_prompt=args.system,
        optimization=not args.no_optimize,
    )
    client._cohrint_key = _stash_key  # type: ignore[attr-defined]

    return client, tracker


def _handle_command(line: str, client: AgentClient) -> bool:
    """Handle /commands. Returns True if handled, False if it's a prompt."""
    stripped = line.strip()

    if stripped in ("/quit", "/exit", "/q"):
        return True  # Signal exit

    # Bare "/" prints help — avoids "Unknown command: /" dead-end (T-DISPATCH.2).
    if stripped in ("/", "/help"):
        from .guardrails import get_settings as _gs
        _g = _gs()
        _guardrail_state = "on" if (_g.recommendation and _g.hallucination) else "partial/off"
        console.print(BANNER.format(
            version=__version__, model=client.model, cwd=client.cwd,
            verbs=_verb_summary_lines(),
            optimization="on" if client.optimization else "off",
            guardrails=_guardrail_state,
        ))
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
            safe_unknown = ", ".join(scrub_token(t) for t in unknown)
            console.print(f"  [red]Unknown tools: {safe_unknown}[/red]")
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
        client.permissions.reset()  # preserves always_denied by default
        client.clear_history()
        client.cost = SessionCost(model=client.model)
        console.print(
            "  [yellow]Reset: approvals, history, and cost cleared "
            "(always-denied tools preserved; use /reset-all to also clear those)[/yellow]"
        )
        return True

    if stripped == "/reset-all":
        client.permissions.reset(wipe_denied=True)
        client.clear_history()
        client.cost = SessionCost(model=client.model)
        console.print(
            "  [yellow]Reset-all: permissions (incl. denied), history, and cost cleared[/yellow]"
        )
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
            # Bare `/model` opens a TUI picker grouped by backend. On non-TTY
            # (piped/scripted REPL) we fall through to a flat print instead.
            from .pricing import MODEL_PRICES
            from .tui import is_tty, select_one
            if is_tty():
                choices = [m for m in sorted(MODEL_PRICES) if m != "default"]
                picked = select_one(
                    f"Current: {client.model}. Pick a model:",
                    choices,
                    default=client.model if client.model in choices else None,
                )
                if picked and picked != client.model:
                    client.model = picked
                    client.cost = SessionCost(model=picked)
                    console.print(f"  [green]Switched to {picked}[/green]")
                return True
            console.print(f"  [dim]Current model: {client.model}[/dim]")
            console.print("  [dim]Supported: run `cohrint-agent models` to list all.[/dim]")
            return True
        new_model = parts[1].strip()
        client.model = new_model
        client.cost = SessionCost(model=new_model)
        console.print(f"  [green]Switched to {new_model}[/green]")
        console.print("  [dim]Cost tracking reset for new model[/dim]")
        return True

    if stripped == "/verbs":
        from .commands import render_catalog
        console.print(render_catalog())
        return True

    if stripped.startswith("/guardrails"):
        from .guardrails import get_settings, set_kind
        parts = stripped.split()
        if len(parts) == 1:
            s = get_settings()
            console.print(
                f"  [dim]guardrails:[/dim] "
                f"recommendation=[{'green' if s.recommendation else 'red'}]{s.recommendation}[/], "
                f"hallucination=[{'green' if s.hallucination else 'red'}]{s.hallucination}[/]"
            )
            return True
        action = parts[1].lower()
        kind = parts[2] if len(parts) >= 3 else "all"
        if action not in ("on", "off"):
            console.print("  [red]Usage: /guardrails [on|off] [recommendation|hallucination|all][/red]")
            return True
        try:
            set_kind(kind, enabled=(action == "on"))
            console.print(f"  [green]guardrails {action} ({kind})[/green]")
        except ValueError as e:
            console.print(f"  [red]{e}[/red]")
        return True

    if stripped == "/tier":
        from .process_safety import safe_config_dir
        config_dir = safe_config_dir()
        _handle_tier_command(client.permissions, config_dir=config_dir)
        return True

    if stripped == "/summary":
        from .summary import fetch_kpis, render_summary
        api_base = os.environ.get("COHRINT_API_BASE", "https://api.cohrint.com")
        api_key = getattr(client, "_cohrint_key", None) or os.environ.get("COHRINT_API_KEY") or None
        kpis = fetch_kpis(api_base, api_key) if api_key else None
        render_summary(console, client.cost, kpis)
        return True

    if stripped == "/budget":
        from .summary import fetch_budget, render_budget
        api_base = os.environ.get("COHRINT_API_BASE", "https://api.cohrint.com")
        api_key = getattr(client, "_cohrint_key", None) or os.environ.get("COHRINT_API_KEY") or None
        status = fetch_budget(api_base, api_key) if api_key else None
        render_budget(console, status)
        return True

    if stripped.startswith("/"):
        # Route /<verb> [...args] to the same subcommand modules that power
        # `cohrint-agent <verb>`. Keeps one source of truth for verb output
        # and avoids duplicating per-verb REPL handlers.
        from .commands import VERBS
        from .subcommands import dispatch as _verb_dispatch
        parts = stripped[1:].split()
        if parts and parts[0] in VERBS:
            try:
                _verb_dispatch(["cohrint-agent", *parts])
            except SystemExit:
                # argparse inside verb modules calls sys.exit on --help / bad
                # args. Swallow so the REPL keeps running.
                pass
            except Exception as e:  # noqa: BLE001 — verb crash must not kill REPL
                console.print(f"  [red]/{parts[0]} failed: {e}[/red]")
            return True

        # Dispatcher gate (T-DISPATCH.1): unknown slash commands never fall
        # through to agent/prompt dispatch — they terminate here.
        # scrub_token guards T-SAFETY.5/6/12: OSC-52 in "/...\x1b]52;..." must
        # not be echoed verbatim.
        safe_cmd = scrub_token(stripped.split()[0])
        console.print(f"  [red]Unknown command: {safe_cmd}[/red]")
        return True

    return False


def run_repl(client: AgentClient, tracker: Tracker | None = None) -> None:
    """Interactive REPL."""
    # Tab-completion + history. No-op on non-TTY / missing readline.
    from .repl_completer import install as _install_completer
    _install_completer()

    from .guardrails import get_settings as _gs
    _g = _gs()
    _guardrail_state = "on" if (_g.recommendation and _g.hallucination) else "partial/off"
    console.print(BANNER.format(
        version=__version__, model=client.model, cwd=client.cwd,
        verbs=_verb_summary_lines(),
        optimization="on" if client.optimization else "off",
        guardrails=_guardrail_state,
    ))

    from .repl_input import read_prompt
    while True:
        console.print()
        line = read_prompt()
        # read_prompt returns None on Ctrl-D / Ctrl-C with empty buffer —
        # signals quit. Empty string means "user pressed Enter on blank"
        # — re-prompt silently without spending a backend turn.
        if line is None:
            console.print("\n  [dim]Goodbye.[/dim]")
            break
        if not line.strip():
            continue

        # Nudge: a bare single-word CLI verb (`mcp`, `plugins`, …) is almost
        # never a real prompt — redirect before we spend tokens on the LLM.
        _stripped_line = line.strip()
        if " " not in _stripped_line and not _stripped_line.startswith("/"):
            from .commands import VERBS as _VERBS
            if _stripped_line in _VERBS:
                console.print(
                    f"  [dim]Did you mean [bold]/{_stripped_line}[/bold]? "
                    f"(bare verbs aren't auto-dispatched; prefix with `/`)[/dim]"
                )
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
            budget = _parse_budget_env(os.environ.get("COHRINT_BUDGET_USD", "0"))
            if budget > 0 and get_global_budget_used() >= budget:
                console.print(f"[red]Global budget of ${budget:.2f} reached across all sessions.[/red]")
                continue
            # Capture the completed-prompt state BEFORE send() increments
            # prompt_count inside SessionCost.record_prompt(). Any offset
            # here (e.g. `- 1`) delays anomaly detection by one full turn.
            prior_total = client.cost.total_cost_usd
            prior_count = client.cost.prompt_count
            response_text = client.send(line)
            # ── Post-response: Cohrint analysis block ─────────────────────
            # Aggregates optimization savings, hallucination guardrail,
            # anomaly detection, recommendation tip, and per-turn / session
            # cost into one uniformly-rendered block via renderer.py.
            if client.cost.turns:
                last = client.cost.turns[-1]

                from .anomaly import check_cost_anomaly_structured
                _anomaly = check_cost_anomaly_structured(last.cost_usd, prior_total, prior_count)
                anomaly_line = (
                    f"${_anomaly.current_cost:.4f} this turn vs "
                    f"${_anomaly.avg_cost:.4f} avg ({_anomaly.ratio:.1f}x)"
                ) if _anomaly.detected else None

                _active = getattr(client, "_last_guardrail_active", [])
                recommendation: str | None = None
                if "recommendation" in _active:
                    try:
                        from .recommendations import SessionMetrics, get_inline_tip
                        _total_count = prior_count + 1
                        _total_cost = prior_total + last.cost_usd
                        _tip = get_inline_tip(SessionMetrics(
                            prompt_count=_total_count,
                            total_cost_usd=_total_cost,
                            total_input_tokens=last.input_tokens,
                            total_output_tokens=last.output_tokens,
                            total_cached_tokens=0,
                            agent="claude",
                            model=client.model,
                            last_prompt_cost_usd=last.cost_usd,
                            last_prompt_tokens=last.input_tokens + last.output_tokens,
                            avg_cost_per_prompt=_total_cost / _total_count if _total_count else 0.0,
                        ))
                        if _tip:
                            recommendation = _tip.lstrip("💡").strip().split(chr(10))[0]
                    except Exception:
                        pass

                from .renderer import render_cohrint_analysis
                from .pricing import cache_read_savings
                _cache_saved_usd = cache_read_savings(client.model, last.cache_read_tokens)
                render_cohrint_analysis(
                    optimization=getattr(client, "_last_opt_result", None),
                    model=client.model,
                    guardrail_hedge_detected=(
                        "hallucination" in _active and bool(response_text)
                        and _detect_hedge(response_text)
                    ),
                    guardrail_active=_active,
                    anomaly_line=anomaly_line,
                    recommendation=recommendation,
                    turn_input_tokens=last.input_tokens,
                    turn_output_tokens=last.output_tokens,
                    turn_cost_usd=last.cost_usd,
                    session_cost_usd=client.cost.total_cost_usd,
                    cache_saved_usd=_cache_saved_usd,
                    cache_read_tokens=last.cache_read_tokens,
                )
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
        budget = _parse_budget_env(os.environ.get("COHRINT_BUDGET_USD", "0"))
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
    # Process-wide umask 0o077 — every mkdir / file creation defaults to
    # owner-only perms so the brief window between mkdir(mode=0o700) and
    # the follow-up chmod on shared CI runners doesn't expose session/
    # permissions files (T-SAFETY.umask_default, scan 18).
    os.umask(0o077)

    # Install a SIGTERM handler so `docker stop`, `systemctl stop`, and
    # CI timeouts get the same graceful-exit path as Ctrl+C instead of
    # killing the process with billed-but-unsaved spend in flight
    # (T-SAFETY.sigterm_graceful). We convert SIGTERM into SystemExit so
    # the existing try/except/finally chain gets to run tracker.stop().
    import signal as _signal
    def _term_handler(_signum, _frame):
        raise SystemExit(130)
    try:
        _signal.signal(_signal.SIGTERM, _term_handler)
    except (ValueError, OSError):
        # Not on main thread / not supported on this platform — skip.
        pass

    # Handle `cohrint-agent summary` before argparse (avoids positional arg conflict)
    if len(sys.argv) == 2 and sys.argv[1] == "summary":
        _print_summary()
        return

    # Dispatch verb subcommands (mcp, skills, agents, models, hooks, etc.)
    # BEFORE argparse so they don't collide with the prompt-positional arg.
    # A user typing `cohrint-agent "fix the bug"` still hits the prompt path —
    # dispatcher only claims known verbs. Catalog: cohrint_agent.commands.CATALOG
    from .subcommands import dispatch, is_subcommand
    if is_subcommand(sys.argv):
        raise SystemExit(dispatch(sys.argv))

    args = parse_args()

    # Upgrade check (P1). Runs synchronously with a 2 s per-endpoint cap so the
    # min_supported_version gate can block startup. Any failure is silent —
    # offline / proxy / DNS errors must never break `cohrint-agent`.
    try:
        _api_base = os.environ.get("COHRINT_API_BASE", DEFAULT_API_BASE)
        _cohrint_key = args.cohrint_key or os.environ.get("COHRINT_API_KEY") or None
        check_for_update(
            current=__version__,
            api_base=_api_base,
            api_key=_cohrint_key,
        )
    except SystemExit:
        # Forced upgrade gate fired — propagate up.
        raise
    except Exception:  # noqa: BLE001
        pass

    # S5: Validate --resume session backend matches available backend
    if args.resume:
        from .session_store import (
            SessionStore,
            SessionNotFoundError,
            InvalidSessionIdError,
        )
        from .backends import auto_detect_backend
        try:
            _store = SessionStore()
            _session_data = _store.load(args.resume)
            _session_backend = _session_data.get("backend", "")
            try:
                _available_backend = args.backend or auto_detect_backend()
            except Exception:
                _available_backend = None
            if _session_backend and _available_backend and _session_backend != _available_backend:
                # Prior backend differs from current — the stored history
                # won't be replayed into the new backend's process, so the
                # user should know they're starting cold (T-SAFETY.backend_mismatch).
                console.print(
                    f"  [yellow]Warning: session was created with backend "
                    f"'{_session_backend}' but '{_available_backend}' is active. "
                    f"Prior conversation history will not be replayed — "
                    f"starting a fresh session.[/yellow]"
                )
                args.resume = None
        except InvalidSessionIdError:
            # T-SAFETY.4 / T-SAFETY.10: refuse non-UUIDv4 IDs rather than
            # letting path-traversal or legacy formats reach the filesystem.
            console.print(
                "  [red]--resume session ID must be a UUIDv4 — ignoring.[/red]"
            )
            args.resume = None
        except SessionNotFoundError:
            console.print(f"  [red]Session {args.resume!r} not found.[/red]")
            args.resume = None
        except Exception as e:
            # Any other failure (corrupt JSON, perms) must still clear
            # args.resume — otherwise the broken ID flows into the backend
            # and surfaces as a confusing downstream error
            # (T-SAFETY.resume_error_visible).
            console.print(
                f"  [red]Failed to load session {args.resume!r}: "
                f"{type(e).__name__}. Starting fresh.[/red]"
            )
            args.resume = None

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

    # Strip a leading U+FEFF BOM from argv-mode prompts. Windows /
    # PowerShell piping will sometimes inject a UTF-8 BOM into argv[1];
    # shipping it to the LLM as data is harmless but it also pollutes the
    # audit log preview and confuses some prompt classifiers
    # (T-SAFETY.argv_bom_strip).
    prompt = " ".join(args.prompt).lstrip("\ufeff") if args.prompt else ""

    if prompt:
        run_oneshot(client, prompt, tracker)
    elif sys.stdin.isatty():
        run_repl(client, tracker)
    else:
        # Pipe mode: cap at 1 MiB (matches Node MAX_STDIN_BYTES). Unbounded
        # sys.stdin.read() on a 500 MB pipe would allocate 500 MB before
        # doing anything — guards T-BOUNDS.stdin / SPEC F1.6.
        MAX_STDIN_BYTES = 1 * 1024 * 1024
        raw = sys.stdin.buffer.read(MAX_STDIN_BYTES + 1)
        if len(raw) > MAX_STDIN_BYTES:
            console.print(
                "  [yellow]Warning: stdin exceeded 1 MiB — truncated.[/yellow]"
            )
            raw = raw[:MAX_STDIN_BYTES]
        prompt = raw.decode("utf-8", errors="replace").strip()
        if prompt:
            run_oneshot(client, prompt, tracker)


if __name__ == "__main__":
    main()
