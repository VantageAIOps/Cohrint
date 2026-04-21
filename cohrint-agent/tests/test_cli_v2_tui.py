"""Tests for cohrint_agent.tui — non-TTY fallback behaviour."""
from __future__ import annotations

from cohrint_agent.tui import autocomplete, confirm, is_tty, multiselect, select_one


class TestIsTty:
    def test_pytest_capture_is_not_tty(self):
        # pytest replaces stdin with a non-isatty object → should be False
        assert is_tty() is False


class TestSelectOneNonTty:
    def test_empty_choices_returns_none(self):
        assert select_one("pick", []) is None

    def test_default_returned_when_supplied(self):
        assert select_one("pick", ["a", "b", "c"], default="b") == "b"

    def test_first_choice_when_no_default(self):
        assert select_one("pick", ["a", "b", "c"]) == "a"

    def test_default_wins_even_if_not_in_choices(self):
        # Non-TTY: we don't validate the default against choices; caller's risk.
        assert select_one("pick", ["a"], default="z") == "z"


class TestConfirmNonTty:
    def test_returns_default_false(self):
        assert confirm("sure?") is False

    def test_returns_default_true(self):
        assert confirm("sure?", default=True) is True


class TestMultiselectNonTty:
    def test_returns_empty_list(self):
        assert multiselect("pick", ["a", "b"]) == []

    def test_empty_choices_returns_empty(self):
        assert multiselect("pick", []) == []


class TestAutocompleteNonTty:
    def test_returns_default_when_set(self):
        assert autocomplete("type:", ["a", "b"], default="b") == "b"

    def test_returns_none_when_no_default(self):
        assert autocomplete("type:", ["a", "b"]) is None
