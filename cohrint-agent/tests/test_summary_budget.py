"""
test_summary_budget.py — Regression tests for /summary and /budget REPL commands.

Guards:
  T-SUMMARY.1  — /summary shows optimization + cache savings + wasted cost
  T-DISPATCH.1 — unknown /command does NOT route to agent dispatch
  T-DISPATCH.2 — bare `/` prints help, not "Unknown command"
  T-BOUNDS.9   — NaN / Infinity values from kpis are coerced to 0
"""
from __future__ import annotations

import io
from unittest.mock import MagicMock, patch

import pytest
from rich.console import Console

from cohrint_agent.cost_tracker import SessionCost
from cohrint_agent.summary import (
    BudgetStatus,
    KpiSavings,
    _coerce_float,
    _coerce_int,
    render_budget,
    render_summary,
)


def _capture_console():
    buf = io.StringIO()
    return Console(file=buf, force_terminal=False, width=200), buf


# -------------------------- SessionCost savings ---------------------------

def test_session_accumulates_optimization_savings():
    cost = SessionCost(model="claude-sonnet-4-6")
    cost.record_optimization(100, 0.003)
    cost.record_optimization(250, 0.0075)
    assert cost.total_saved_tokens == 350
    assert 0.01 <= cost.total_saved_usd < 0.011


def test_session_ignores_nonpositive_savings():
    cost = SessionCost()
    cost.record_optimization(0, 0.0)
    cost.record_optimization(-50, 0.01)
    assert cost.total_saved_tokens == 0
    assert cost.total_saved_usd == 0.0


def test_session_clamps_negative_usd():
    cost = SessionCost()
    cost.record_optimization(100, -5.0)  # bogus negative from pricing edge
    assert cost.total_saved_tokens == 100
    assert cost.total_saved_usd == 0.0


# -------------------------- Coercion --------------------------------------

@pytest.mark.parametrize(
    "raw,expected",
    [
        (1.23, 1.23),
        ("2.5", 2.5),
        (None, 0.0),
        ("not-a-number", 0.0),
        (float("nan"), 0.0),
        (float("inf"), 0.0),
        (float("-inf"), 0.0),
    ],
)
def test_coerce_float(raw, expected):
    assert _coerce_float(raw) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [(42, 42), ("7", 7), ("3.9", 3), (None, 0), ("abc", 0), (-5, 0)],
)
def test_coerce_int(raw, expected):
    assert _coerce_int(raw) == expected


# -------------------------- render_summary --------------------------------

def test_summary_renders_session_and_savings_blocks():
    cost = SessionCost(model="claude-sonnet-4-6")
    cost.prompt_count = 3
    cost.total_input = 1500
    cost.total_output = 800
    cost.total_cost_usd = 0.0456
    cost.record_optimization(200, 0.012)
    kpis = KpiSavings(
        cache_savings_usd=0.05,
        cache_tokens_total=12345,
        cache_hit_rate_pct=37.5,
        duplicate_calls=4,
        wasted_cost_usd=0.008,
    )
    console, buf = _capture_console()
    render_summary(console, cost, kpis)
    out = buf.getvalue()
    # T-SUMMARY.1 checks
    assert "Session Summary" in out
    assert "3" in out  # prompt count
    assert "0.0456" in out
    assert "Optimization:" in out
    assert "200" in out
    assert "Cache:" in out
    assert "37.5%" in out
    assert "Wasted (dupes):" in out
    assert "4 duplicate calls" in out


def test_summary_omits_savings_block_when_nothing_to_report():
    cost = SessionCost(model="claude-sonnet-4-6")
    cost.prompt_count = 1
    console, buf = _capture_console()
    render_summary(console, cost, None)
    out = buf.getvalue()
    assert "Session Summary" in out
    assert "Savings" not in out
    assert "Optimization:" not in out


# -------------------------- render_budget ---------------------------------

def test_budget_under_60_green():
    console, buf = _capture_console()
    status = BudgetStatus(budget_usd=100.0, budget_pct=45.0, mtd_cost_usd=45.0)
    render_budget(console, status)
    out = buf.getvalue()
    assert "Monthly budget" in out
    assert "45.0%" in out
    assert "$55.00" in out
    assert "OVER BUDGET" not in out
    assert "80% threshold" not in out


def test_budget_over_80_prints_warning():
    console, buf = _capture_console()
    status = BudgetStatus(budget_usd=100.0, budget_pct=85.5, mtd_cost_usd=85.5)
    render_budget(console, status)
    out = buf.getvalue()
    assert "85.5%" in out
    assert "80% threshold exceeded" in out
    assert "OVER BUDGET" not in out


def test_budget_over_100_prints_red_warning():
    console, buf = _capture_console()
    status = BudgetStatus(budget_usd=100.0, budget_pct=120.0, mtd_cost_usd=120.0)
    render_budget(console, status)
    out = buf.getvalue()
    assert "OVER BUDGET" in out
    assert "exceeds monthly limit" in out


def test_budget_no_budget_set():
    console, buf = _capture_console()
    render_budget(console, BudgetStatus(budget_usd=0.0, budget_pct=0.0, mtd_cost_usd=0.0))
    assert "No budget set" in buf.getvalue()


def test_budget_no_key():
    console, buf = _capture_console()
    render_budget(console, None)
    assert "No API key configured" in buf.getvalue()


# -------------------------- fetch guards ----------------------------------

def test_fetch_kpis_refuses_http():
    from cohrint_agent.summary import fetch_kpis
    assert fetch_kpis("http://api.cohrint.com", "key") is None


def test_fetch_kpis_returns_none_without_key():
    from cohrint_agent.summary import fetch_kpis
    assert fetch_kpis("https://api.cohrint.com", None) is None
    assert fetch_kpis("https://api.cohrint.com", "") is None


def test_fetch_budget_refuses_http():
    from cohrint_agent.summary import fetch_budget
    assert fetch_budget("http://api.cohrint.com", "key") is None


# -------------------------- dispatcher (P7 / P10) -------------------------

def test_bare_slash_prints_help():
    """T-DISPATCH.2: `/` alone does not reach 'Unknown command'."""
    from cohrint_agent.cli import _handle_command

    client = MagicMock()
    client.model = "claude-sonnet-4-6"
    client.cwd = "/tmp"
    with patch("cohrint_agent.cli.console") as mock_console:
        assert _handle_command("/", client) is True
    printed = "".join(
        str(call.args[0]) for call in mock_console.print.call_args_list if call.args
    )
    assert "Cohrint Agent" in printed
    assert "Unknown command" not in printed


def test_unknown_command_stays_in_dispatcher():
    """T-DISPATCH.1: `/notatool` must not fall through to agent dispatch."""
    from cohrint_agent.cli import _handle_command

    client = MagicMock()
    with patch("cohrint_agent.cli.console") as mock_console:
        # Returns True means "handled" — REPL will NOT pass the line to client.send.
        assert _handle_command("/notatool", client) is True
    printed = "".join(
        str(call.args[0]) for call in mock_console.print.call_args_list if call.args
    )
    assert "Unknown command" in printed
    # Crucial: the dispatcher never called client.send for a slash command.
    client.send.assert_not_called()


def test_non_slash_input_is_not_a_command():
    """Plain prompts return False so the REPL forwards them to the model."""
    from cohrint_agent.cli import _handle_command

    client = MagicMock()
    assert _handle_command("hello world", client) is False
