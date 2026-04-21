"""Tests for cohrint_agent.subcommands — argv dispatcher."""
from __future__ import annotations

import pytest

from cohrint_agent.commands import CATALOG, VERBS, render_catalog, render_verb_help
from cohrint_agent.subcommands import _ROUTES, dispatch, is_subcommand


class TestIsSubcommand:
    def test_no_args(self):
        assert not is_subcommand(["cohrint-agent"])

    def test_known_verb(self):
        for verb in VERBS:
            assert is_subcommand(["cohrint-agent", verb])

    def test_help_verb(self):
        assert is_subcommand(["cohrint-agent", "help"])
        assert is_subcommand(["cohrint-agent", "--help-verbs"])

    def test_prompt_not_claimed(self):
        # "fix the bug" should fall through to prompt mode
        assert not is_subcommand(["cohrint-agent", "fix the bug"])
        assert not is_subcommand(["cohrint-agent", "hello world"])

    def test_flag_not_claimed(self):
        assert not is_subcommand(["cohrint-agent", "--model"])
        assert not is_subcommand(["cohrint-agent", "-h"])


class TestDispatch:
    def test_no_args_prints_catalog(self, capsys):
        rc = dispatch(["cohrint-agent"])
        out = capsys.readouterr().out
        assert rc == 0
        assert "Verbs:" in out
        assert "models" in out

    def test_help_verb(self, capsys):
        rc = dispatch(["cohrint-agent", "help"])
        assert rc == 0
        assert "Verbs:" in capsys.readouterr().out

    def test_unknown_verb_is_error(self, capsys):
        rc = dispatch(["cohrint-agent", "nosuchverb"])
        assert rc == 2
        err = capsys.readouterr().err
        assert "unknown verb" in err
        assert "nosuchverb" in err

    def test_models_dispatch(self, capsys):
        rc = dispatch(["cohrint-agent", "models"])
        assert rc == 0
        assert "Supported models" in capsys.readouterr().out

    def test_mcp_help(self, capsys):
        rc = dispatch(["cohrint-agent", "mcp", "--help"])
        assert rc == 0
        assert "mcp" in capsys.readouterr().out.lower()


class TestCatalog:
    def test_routes_match_catalog(self):
        assert set(_ROUTES.keys()) == set(CATALOG.keys())

    def test_render_catalog_nonempty(self):
        text = render_catalog()
        assert "cohrint-agent" in text
        for verb in VERBS:
            assert verb in text

    def test_render_verb_help_known(self):
        for verb in VERBS:
            text = render_verb_help(verb)
            assert verb in text

    def test_render_verb_help_unknown(self):
        assert "unknown verb" in render_verb_help("does-not-exist")

    @pytest.mark.parametrize("verb", list(VERBS))
    def test_every_verb_has_spec(self, verb):
        spec = CATALOG[verb]
        assert spec.summary
        # Every verb must have at least one example for doc generation.
        assert spec.examples, f"{verb} has no examples"
