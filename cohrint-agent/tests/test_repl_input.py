"""Tests for repl_input.py — multi-line prompt reader used by the REPL.

The old REPL read one line per Enter — a multi-line paste submitted every
line as its own prompt, spawning a backend roundtrip per fragment. These
tests cover the aggregation rules that replace that behaviour:

  - blank first line → empty string (ignored by the REPL loop)
  - single line → returned as-is
  - triple-quote block → multi-line body until closing \"\"\"
  - trailing-backslash continuation → join lines until no trailing backslash
  - EOF mid-block → partial content still returned, not lost

The actual terminal I/O (prompt_toolkit, bracketed paste) is a separate
concern covered by integration tests — unit tests here inject a fake line
source so they stay deterministic.
"""
from __future__ import annotations

import pytest
from cohrint_agent.repl_input import aggregate_lines


def _make_source(lines):
    """Return a line_source that yields the given lines in order, raising
    EOFError after exhaustion — matches real input() semantics."""
    it = iter(lines)

    def source(_prompt_text: str) -> str:
        try:
            return next(it)
        except StopIteration:
            raise EOFError

    return source


class TestAggregateLines:
    def test_blank_line_returns_empty(self):
        src = _make_source([""])
        assert aggregate_lines(src) == ""

    def test_single_line_returns_as_is(self):
        src = _make_source(["fix the bug"])
        assert aggregate_lines(src) == "fix the bug"

    def test_line_with_embedded_newlines_preserved(self):
        # Simulates bracketed-paste where the whole paste arrives as one
        # input() call containing \n characters.
        pasted = "first line\nsecond line\nthird line"
        src = _make_source([pasted])
        assert aggregate_lines(src) == pasted

    def test_triple_quote_block_single_line(self):
        # """hello""" → "hello"
        src = _make_source(['"""hello"""'])
        assert aggregate_lines(src) == "hello"

    def test_triple_quote_block_multiline(self):
        src = _make_source([
            '"""first',
            'second',
            'third"""',
        ])
        assert aggregate_lines(src) == "first\nsecond\nthird"

    def test_triple_quote_empty_body(self):
        src = _make_source([
            '"""',
            'body',
            '"""',
        ])
        assert aggregate_lines(src) == "body"

    def test_backslash_continuation(self):
        src = _make_source([
            "line one \\",
            "line two \\",
            "line three",
        ])
        assert aggregate_lines(src) == "line one \nline two \nline three"

    def test_backslash_continuation_terminates_on_eof(self):
        # Ctrl-D mid-continuation must still return what we have, not crash
        # or return None (would quit the REPL unexpectedly).
        src = _make_source(["line one \\"])
        assert aggregate_lines(src) == "line one "

    def test_triple_quote_terminates_on_eof(self):
        src = _make_source([
            '"""first',
            'second',
        ])
        assert aggregate_lines(src) == "first\nsecond"

    def test_first_line_eof_returns_none(self):
        # User hit Ctrl-D on an empty prompt — signals quit.
        src = _make_source([])
        assert aggregate_lines(src) is None

    def test_first_line_ctrl_c_returns_none(self):
        def source(_):
            raise KeyboardInterrupt
        assert aggregate_lines(source) is None

    def test_slash_command_single_line(self):
        # /quit and friends must remain single-line — no accidental
        # multi-line aggregation.
        src = _make_source(["/quit"])
        assert aggregate_lines(src) == "/quit"

    def test_sanitizes_nothing_in_content(self):
        # aggregate_lines is plain text — scrubbing is the renderer's job,
        # not the aggregator's. This test locks that boundary in.
        src = _make_source(["\x1b]52;c;OSC52\x07 passthrough"])
        assert aggregate_lines(src) == "\x1b]52;c;OSC52\x07 passthrough"
