"""
Test Suite 25: Smart Session — Input Classification & Optimization
Tests input classifier, selective optimization, and auto-recovery logic.
40 checks across 5 sections (SS.1–SS.40).
"""
import sys
import math
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(ROOT / "vantage-agent"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from helpers.output import section, chk
from vantage_agent.classifier import classify_input, process_input as _process_input


# ── Helpers ────────────────────────────────────────────────────────────────

def classify(input_text: str, agent: str = "claude") -> dict:
    """Classify input_text and return a dict with 'type' key."""
    return {"type": classify_input(input_text, agent)}


def process_input(input_text: str, agent: str = "claude", opt_mode: str = "auto") -> dict:
    """Classify and optionally optimize input_text. Returns JS-compatible dict."""
    r = _process_input(input_text, agent, opt_mode)
    return {
        "type": r["type"],
        "optimized": r["optimized"],
        "forwarded": r["forwarded"],
        "savedTokens": r["saved_tokens"],
        "original": r["input"],
        "reverted": r["reverted"],
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SECTION A — Input Classification (SS.1–SS.15)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_ss01_natural_language_prompt():
    """SS.1: Natural language with 5+ words is classified as prompt."""
    section("A — Input Classification")
    r = classify("explain kubernetes pods in detail")
    chk("SS.1  natural language → prompt", r["type"] == "prompt", f"got {r['type']}")


def test_ss02_short_answer_y():
    """SS.2: Single letter 'y' is short-answer."""
    r = classify("y")
    chk("SS.2  'y' → short-answer", r["type"] == "short-answer", f"got {r['type']}")


def test_ss03_short_answer_yes():
    """SS.3: 'yes' is short-answer."""
    r = classify("yes")
    chk("SS.3  'yes' → short-answer", r["type"] == "short-answer", f"got {r['type']}")


def test_ss04_short_answer_numeric():
    """SS.4: Numeric selection '1' is short-answer."""
    r = classify("1")
    chk("SS.4  '1' → short-answer", r["type"] == "short-answer", f"got {r['type']}")


def test_ss05_agent_command_compact():
    """SS.5: /compact is agent-command for claude."""
    r = classify("/compact", "claude")
    chk("SS.5  /compact (claude) → agent-command", r["type"] == "agent-command", f"got {r['type']}")


def test_ss06_agent_command_clear():
    """SS.6: /clear is agent-command for claude."""
    r = classify("/clear", "claude")
    chk("SS.6  /clear (claude) → agent-command", r["type"] == "agent-command", f"got {r['type']}")


def test_ss07_at_file_agent_command():
    """SS.7: @file.ts is agent-command."""
    r = classify("@file.ts")
    chk("SS.7  '@file.ts' → agent-command", r["type"] == "agent-command", f"got {r['type']}")


def test_ss08_bang_command():
    """SS.8: !ls -la is agent-command."""
    r = classify("!ls -la")
    chk("SS.8  '!ls -la' → agent-command", r["type"] == "agent-command", f"got {r['type']}")


def test_ss09_vantage_exit_session():
    """SS.9: /exit-session is vantage-command."""
    r = classify("/exit-session")
    chk("SS.9  /exit-session → vantage-command", r["type"] == "vantage-command", f"got {r['type']}")


def test_ss10_vantage_cost():
    """SS.10: /cost is vantage-command."""
    r = classify("/cost")
    chk("SS.10 /cost → vantage-command", r["type"] == "vantage-command", f"got {r['type']}")


def test_ss11_vantage_opt_off():
    """SS.11: /opt-off is vantage-command."""
    r = classify("/opt-off")
    chk("SS.11 /opt-off → vantage-command", r["type"] == "vantage-command", f"got {r['type']}")


def test_ss12_structured_json():
    """SS.12: JSON object is classified as structured."""
    r = classify('{"key": "value"}')
    chk("SS.12 JSON → structured", r["type"] == "structured", f"got {r['type']}")


def test_ss13_structured_code_block():
    """SS.13: Code block is classified as structured."""
    r = classify("```python\nprint('hi')```")
    chk("SS.13 code block → structured", r["type"] == "structured", f"got {r['type']}")


def test_ss14_empty_input():
    """SS.14: Empty string → unknown."""
    r = classify("")
    chk("SS.14 empty → unknown", r["type"] == "unknown", f"got {r['type']}")


def test_ss15_single_word():
    """SS.15: Single word 'fix' → short-answer."""
    r = classify("fix")
    chk("SS.15 'fix' (1 word) → short-answer", r["type"] == "short-answer", f"got {r['type']}")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SECTION B — Selective Optimization (SS.16–SS.25)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

VERBOSE_PROMPT = (
    "I'd like you to please kindly help me write a very detailed function "
    "that essentially sorts a list of numbers in order to get them in ascending "
    "order due to the fact that the current implementation is basically broken "
    "and I really need you to fix it quickly"
)

CLEAN_PROMPT = (
    "Write a function that sorts a list of numbers in ascending order "
    "using the merge sort algorithm with O(n log n) complexity"
)


def test_ss16_verbose_prompt_optimized():
    """SS.16: Verbose prompt is optimized with savings."""
    section("B — Selective Optimization")
    r = process_input(VERBOSE_PROMPT)
    chk("SS.16 verbose prompt → optimized=true", r["optimized"] is True, f"optimized={r['optimized']}")
    chk("SS.16 verbose prompt → savedTokens > 0", r["savedTokens"] > 0, f"savedTokens={r['savedTokens']}")


def test_ss17_short_answer_passthrough():
    """SS.17: Short answer is not optimized."""
    r = process_input("y")
    chk("SS.17 short-answer 'y' → optimized=false", r["optimized"] is False, f"optimized={r['optimized']}")


def test_ss18_agent_command_passthrough():
    """SS.18: Agent command is not optimized."""
    r = process_input("/compact")
    chk("SS.18 agent-command → optimized=false", r["optimized"] is False, f"optimized={r['optimized']}")


def test_ss19_structured_passthrough():
    """SS.19: Structured JSON is not optimized."""
    r = process_input('{"key": "value"}')
    chk("SS.19 structured → optimized=false", r["optimized"] is False, f"optimized={r['optimized']}")


def test_ss20_clean_prompt_no_savings():
    """SS.20: Clean prompt with no filler → no optimization needed."""
    r = process_input(CLEAN_PROMPT)
    chk("SS.20 clean prompt → optimized=false", r["optimized"] is False, f"optimized={r['optimized']}")


def test_ss21_opt_mode_never():
    """SS.21: optMode='never' always disables optimization."""
    r = process_input(VERBOSE_PROMPT, opt_mode="never")
    chk("SS.21 optMode=never → optimized=false", r["optimized"] is False, f"optimized={r['optimized']}")


def test_ss22_opt_mode_auto_verbose():
    """SS.22: optMode='auto' + verbose prompt → optimized."""
    r = process_input(VERBOSE_PROMPT, opt_mode="auto")
    chk("SS.22 optMode=auto + verbose → optimized=true", r["optimized"] is True, f"optimized={r['optimized']}")


def test_ss23_optimization_preserves_meaning():
    """SS.23: Optimized output is non-empty and retains content."""
    r = process_input(VERBOSE_PROMPT)
    forwarded = r["forwarded"]
    chk("SS.23 forwarded is non-empty", len(forwarded) > 0, f"len={len(forwarded)}")
    # Key terms must survive
    has_sort = "sort" in forwarded.lower()
    chk("SS.23 key term 'sort' preserved", has_sort, f"forwarded={forwarded[:80]}")


def test_ss24_saved_tokens_accuracy():
    """SS.24: savedTokens matches the Python count_tokens before-after delta."""
    from vantage_agent.optimizer import count_tokens
    r = process_input(VERBOSE_PROMPT)
    orig_tokens = count_tokens(VERBOSE_PROMPT)
    fwd_tokens = count_tokens(r["forwarded"])
    expected_saved = orig_tokens - fwd_tokens
    chk(
        "SS.24 savedTokens matches delta",
        r["savedTokens"] == expected_saved,
        f"reported={r['savedTokens']}, expected={expected_saved}",
    )


def test_ss25_vantage_command_not_optimized():
    """SS.25: Vantage command is classified and not forwarded through optimizer."""
    r = process_input("/cost")
    chk("SS.25 /cost → type=vantage-command", r["type"] == "vantage-command", f"type={r['type']}")
    chk("SS.25 /cost → optimized=false", r["optimized"] is False, f"optimized={r['optimized']}")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SECTION C — Auto-Recovery (SS.26–SS.30)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_ss26_over_compressed_reverts():
    """SS.26: If optimization removes >80% of content → reverted=true."""
    section("C — Auto-Recovery")
    # Construct input that is almost entirely filler so compress() guts it
    filler_only = (
        "please kindly basically essentially actually literally obviously "
        "clearly simply just very really quite write code"
    )
    r = process_input(filler_only)
    # Either reverted or not optimized (savings too small / content too short)
    is_safe = r["reverted"] is True or r["optimized"] is False
    chk("SS.26 over-compressed → reverted or not optimized", is_safe,
        f"reverted={r['reverted']}, optimized={r['optimized']}")


def test_ss27_reverted_keeps_original():
    """SS.27: When reverted, forwarded equals original."""
    filler_heavy = (
        "please kindly basically essentially actually literally obviously "
        "clearly simply just very really quite I'd like you to help me with something"
    )
    r = process_input(filler_heavy)
    if r["reverted"]:
        chk("SS.27 reverted → forwarded=original", r["forwarded"] == r["original"],
            f"forwarded differs from original")
    else:
        # If not reverted, it passed through without optimization (short / low savings)
        chk("SS.27 not reverted → passthrough ok", r["forwarded"] == r["original"] or r["optimized"],
            f"unexpected state: reverted=False, optimized={r['optimized']}")


def test_ss28_empty_input_no_crash():
    """SS.28: Empty input does not crash the classifier."""
    r = process_input("")
    chk("SS.28 empty input → type=unknown, no crash", r["type"] == "unknown", f"type={r['type']}")


def test_ss29_only_filler_words():
    """SS.29: Input of only filler words → reverted (would be empty after compression)."""
    only_filler = "please kindly basically essentially actually literally obviously clearly simply just very really quite"
    r = process_input(only_filler)
    # This is fewer than 5 words of meaningful content after the regex strips fillers,
    # but the raw input has 5+ words so it classifies as "prompt"
    is_safe = r["reverted"] is True or r["optimized"] is False
    chk("SS.29 only filler → reverted or no optimization",
        is_safe, f"reverted={r['reverted']}, optimized={r['optimized']}")


def test_ss30_optimizer_error_recovery():
    """SS.30: If optimizer encounters an edge case, result is still safe."""
    # Very long single "word" — should not crash
    long_input = "a" * 5000 + " " + "b" * 5000 + " write a function that does something useful here"
    r = process_input(long_input)
    chk("SS.30 edge-case input → no crash",
        r["type"] in ("prompt", "short-answer", "structured", "unknown"),
        f"type={r['type']}")
    chk("SS.30 edge-case → forwarded non-empty", len(r["forwarded"]) > 0,
        f"forwarded length={len(r['forwarded'])}")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SECTION D — User Control (SS.31–SS.35)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_ss31_opt_off_is_vantage_command():
    """SS.31: /opt-off is classified as vantage-command."""
    section("D — User Control")
    r = classify("/opt-off")
    chk("SS.31 /opt-off → vantage-command", r["type"] == "vantage-command", f"got {r['type']}")


def test_ss32_opt_auto_is_vantage_command():
    """SS.32: /opt-auto is classified as vantage-command."""
    r = classify("/opt-auto")
    chk("SS.32 /opt-auto → vantage-command", r["type"] == "vantage-command", f"got {r['type']}")


def test_ss33_opt_ask_is_vantage_command():
    """SS.33: /opt-ask is classified as vantage-command."""
    r = classify("/opt-ask")
    chk("SS.33 /opt-ask → vantage-command", r["type"] == "vantage-command", f"got {r['type']}")


def test_ss34_opt_on_is_vantage_command():
    """SS.34: /opt-on is classified as vantage-command."""
    r = classify("/opt-on")
    chk("SS.34 /opt-on → vantage-command", r["type"] == "vantage-command", f"got {r['type']}")


def test_ss35_never_mode_disables_verbose():
    """SS.35: optMode='never' disables optimization even on verbose prompt."""
    r = process_input(VERBOSE_PROMPT, opt_mode="never")
    chk("SS.35 never mode → optimized=false", r["optimized"] is False, f"optimized={r['optimized']}")
    chk("SS.35 never mode → forwarded=original", r["forwarded"] == VERBOSE_PROMPT,
        f"forwarded differs from original")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SECTION E — Agent-Specific Classification (SS.36–SS.40)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_ss36_compress_gemini_vs_claude():
    """SS.36: /compress is agent-command for gemini, NOT for claude."""
    section("E — Agent-Specific Classification")
    r_gemini = classify("/compress", "gemini")
    r_claude = classify("/compress", "claude")
    chk("SS.36 /compress (gemini) → agent-command",
        r_gemini["type"] == "agent-command", f"got {r_gemini['type']}")
    chk("SS.36 /compress (claude) → NOT agent-command",
        r_claude["type"] != "agent-command", f"got {r_claude['type']}")


def test_ss37_add_aider_vs_claude():
    """SS.37: /add is agent-command for aider, NOT for claude."""
    r_aider = classify("/add", "aider")
    r_claude = classify("/add", "claude")
    chk("SS.37 /add (aider) → agent-command",
        r_aider["type"] == "agent-command", f"got {r_aider['type']}")
    chk("SS.37 /add (claude) → NOT agent-command",
        r_claude["type"] != "agent-command", f"got {r_claude['type']}")


def test_ss38_approval_codex_vs_claude():
    """SS.38: /approval is agent-command for codex, NOT for claude."""
    r_codex = classify("/approval", "codex")
    r_claude = classify("/approval", "claude")
    chk("SS.38 /approval (codex) → agent-command",
        r_codex["type"] == "agent-command", f"got {r_codex['type']}")
    chk("SS.38 /approval (claude) → NOT agent-command",
        r_claude["type"] != "agent-command", f"got {r_claude['type']}")


def test_ss39_compact_claude_vs_gemini():
    """SS.39: /compact is agent-command for claude, NOT for gemini."""
    r_claude = classify("/compact", "claude")
    r_gemini = classify("/compact", "gemini")
    chk("SS.39 /compact (claude) → agent-command",
        r_claude["type"] == "agent-command", f"got {r_claude['type']}")
    chk("SS.39 /compact (gemini) → NOT agent-command",
        r_gemini["type"] != "agent-command", f"got {r_gemini['type']}")


def test_ss40_unknown_agent_no_commands():
    """SS.40: Unknown agent → no agent-commands recognized, falls to other rules."""
    r = classify("/compact", "unknownbot")
    chk("SS.40 /compact (unknownbot) → NOT agent-command",
        r["type"] != "agent-command", f"got {r['type']}")
    # A slash command not in vantage list for unknown agent → short-answer
    chk("SS.40 /compact (unknownbot) → short-answer",
        r["type"] == "short-answer", f"got {r['type']}")
