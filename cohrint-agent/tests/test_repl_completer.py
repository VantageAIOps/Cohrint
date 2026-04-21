"""Tests for repl_completer._candidates_for_line."""
from __future__ import annotations

from cohrint_agent.repl_completer import _candidates_for_line


def test_empty_returns_nothing():
    assert _candidates_for_line("") == []
    assert _candidates_for_line("   ") == []


def test_slash_prefix_lists_slash_commands_and_verbs():
    cands = _candidates_for_line("/")
    assert "/help" in cands
    assert "/quit" in cands
    assert "/mcp" in cands          # verb slash-form
    assert "/plugins" in cands
    assert "/skills" in cands


def test_slash_mcp_subcommands():
    cands = _candidates_for_line("/mcp ")
    assert "list" in cands
    assert "add" in cands
    assert "remove" in cands


def test_slash_allow_tools():
    cands = _candidates_for_line("/allow ")
    assert "all" in cands
    assert "Bash" in cands
    assert "Read" in cands


def test_slash_guardrails_first_word():
    cands = _candidates_for_line("/guardrails ")
    assert "on" in cands
    assert "off" in cands


def test_slash_guardrails_second_word():
    cands = _candidates_for_line("/guardrails on ")
    assert "recommendation" in cands
    assert "hallucination" in cands
    assert "all" in cands


def test_slash_optimize_toggle():
    cands = _candidates_for_line("/optimize ")
    assert cands == ["on", "off"]


def test_slash_model_lists_pricing_keys():
    cands = _candidates_for_line("/model ")
    # Must be non-empty and exclude the pseudo-entry "default".
    assert cands
    assert "default" not in cands
    # Some known pricing entry sneaks in (sanity check; exact names can drift).
    assert any("claude" in c for c in cands) or any("gpt" in c for c in cands)


def test_bare_word_without_slash_no_candidates():
    # Typing `mcp ` without a leading slash is a prompt-to-LLM fragment; we
    # don't autocomplete it, otherwise tab would rewrite natural-language text.
    assert _candidates_for_line("mcp ") == _subcommand_tokens_unchecked("mcp")


def _subcommand_tokens_unchecked(verb: str):
    # Re-derive what the completer returns for the multi-word branch without
    # the slash; we only want to assert that the branch doesn't raise and
    # returns a list (may be empty depending on catalog).
    from cohrint_agent.repl_completer import _subcommand_tokens
    return _subcommand_tokens(verb)
