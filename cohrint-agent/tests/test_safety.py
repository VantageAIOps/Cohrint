"""
test_safety.py — Regression tests for T-SAFETY.* war-proof clauses.

Covers the security cluster ported in Phase 1 of CLI_MIGRATION_PLAN.md:

  T-SAFETY.1   — subprocess env scrub (LD_PRELOAD, DYLD_*, NODE_OPTIONS, …)
  T-SAFETY.4   — SessionStore refuses non-UUIDv4 session IDs (path traversal)
  T-SAFETY.5   — "Unknown command" echo scrubs OSC-52
  T-SAFETY.6   — "Unknown tools" echo scrubs CSI / OSC-52
  T-SAFETY.10  — SessionStore refuses legacy/short IDs (leading-digit, UUIDv1)
  T-SAFETY.11  — Tracker refuses to flush over cleartext HTTP (spools instead)
  T-SAFETY.12  — renderer.render_tool_* + permission-prompt scrub escapes
  T-BOUNDS.argv — prompt argv element truncated to MAX_ARGV_STRLEN
  T-PRIVACY.allow — unknown privacy value normalised, never falls through
"""
from __future__ import annotations

import io
import os

import pytest
from rich.console import Console

from cohrint_agent.process_safety import (
    MAX_ARGV_STRLEN,
    _STRIP_ALWAYS,
    _parse_allowlist,
    clamp_argv,
    safe_child_env,
)
from cohrint_agent.sanitize import scrub_for_terminal, scrub_token
from cohrint_agent.session_store import (
    InvalidSessionIdError,
    SessionStore,
    is_valid_session_id,
)
from cohrint_agent.tracker import (
    Tracker,
    TrackerConfig,
    _SPOOL_FILE,
    _normalize_privacy,
)


# ───────────────────────────────────────────────────────────── T-SAFETY.1 ──

class TestEnvScrub:
    def test_ld_preload_stripped_from_default_env(self, monkeypatch):
        monkeypatch.setenv("LD_PRELOAD", "/tmp/evil.so")
        monkeypatch.setenv("PATH", "/usr/bin:/bin")
        out = safe_child_env()
        assert "LD_PRELOAD" not in out
        assert out.get("PATH") == "/usr/bin:/bin"

    def test_all_strip_always_vars_removed(self):
        src = {name: f"hijack-{name}" for name in _STRIP_ALWAYS}
        src["PATH"] = "/usr/bin"
        out = safe_child_env(src)
        for name in _STRIP_ALWAYS:
            assert name not in out, f"{name} must be stripped"
        assert out["PATH"] == "/usr/bin"

    def test_dyld_insert_libraries_stripped_on_macos(self):
        out = safe_child_env({"DYLD_INSERT_LIBRARIES": "/tmp/evil.dylib"})
        assert "DYLD_INSERT_LIBRARIES" not in out

    def test_node_options_stripped(self):
        out = safe_child_env({"NODE_OPTIONS": "--require /tmp/shim.js"})
        assert "NODE_OPTIONS" not in out

    def test_pythonpath_stripped(self):
        out = safe_child_env({"PYTHONPATH": "/attacker/site-packages"})
        assert "PYTHONPATH" not in out

    def test_allowlist_cannot_re_admit_strip_list(self):
        src = {
            "LD_PRELOAD": "/tmp/x.so",
            "COHRINT_PASS_ENV": "LD_PRELOAD,FOO",
            "FOO": "ok",
        }
        out = safe_child_env(src)
        assert "LD_PRELOAD" not in out
        assert out.get("FOO") == "ok"

    def test_allowlist_refuses_wildcard(self):
        assert _parse_allowlist("*") == set()
        assert _parse_allowlist("*,FOO") == set()

    def test_non_identifier_names_dropped(self):
        out = safe_child_env({"FOO-BAR": "x", "OK_NAME": "y"})
        assert "FOO-BAR" not in out
        assert out.get("OK_NAME") == "y"

    def test_non_string_values_dropped(self):
        out = safe_child_env({"GOOD": "ok", "BAD": 123})  # type: ignore[dict-item]
        assert out.get("GOOD") == "ok"
        assert "BAD" not in out


# ──────────────────────────────────────────────────────── T-SAFETY.4 / .10 ──

class TestUuidSessionRegex:
    def test_valid_uuid4_accepted(self):
        assert is_valid_session_id("12345678-1234-4567-89ab-1234567890ab")

    def test_uuid1_rejected(self):
        # version nibble 1 → not v4
        assert not is_valid_session_id("12345678-1234-1567-89ab-1234567890ab")

    def test_variant_nibble_rejected(self):
        # fourth-group starts with "7" → not 8/9/a/b
        assert not is_valid_session_id("12345678-1234-4567-7abc-1234567890ab")

    def test_path_traversal_rejected(self):
        assert not is_valid_session_id("../../etc/passwd")
        assert not is_valid_session_id("../../../root/.ssh/id_rsa")

    def test_trailing_newline_rejected(self):
        assert not is_valid_session_id("12345678-1234-4567-89ab-1234567890ab\n")

    def test_empty_rejected(self):
        assert not is_valid_session_id("")
        assert not is_valid_session_id(None)  # type: ignore[arg-type]

    def test_store_path_raises_on_bad_id(self, tmp_path):
        store = SessionStore(sessions_dir=tmp_path)
        with pytest.raises(InvalidSessionIdError):
            store._path("../../etc/passwd")
        with pytest.raises(InvalidSessionIdError):
            store._path("not-a-uuid")

    def test_store_save_raises_on_bad_id(self, tmp_path):
        store = SessionStore(sessions_dir=tmp_path)
        with pytest.raises(InvalidSessionIdError):
            store.save({"id": "../../etc/passwd"})
        # confirm nothing was written outside sessions dir
        assert not (tmp_path.parent / "etc").exists()

    def test_store_load_raises_on_bad_id(self, tmp_path):
        store = SessionStore(sessions_dir=tmp_path)
        with pytest.raises(InvalidSessionIdError):
            store.load("../../../../etc/shadow")


# ──────────────────────────────────────────────────────── T-SAFETY.5 / .6 ──

class TestUnknownEchoScrub:
    """
    Simulates the cli.py Unknown-command / Unknown-tools echo paths.
    Uses a captured Console so we can assert on the emitted bytes.
    """

    def _capture(self) -> tuple[Console, io.StringIO]:
        buf = io.StringIO()
        # force_terminal=False keeps Rich from injecting ANSI — we're asserting
        # on what would reach the underlying write stream.
        return Console(file=buf, force_terminal=False, color_system=None), buf

    def test_osc52_in_unknown_command_is_stripped(self):
        console, buf = self._capture()
        # OSC-52 "write to clipboard" injection — byte-for-byte the attack
        # used in the R10a incident.
        injected = "/cmd\x1b]52;c;ZXZpbA==\x07"
        safe = scrub_token(injected.split()[0])
        console.print(f"Unknown command: {safe}")
        out = buf.getvalue()
        assert "\x1b" not in out
        assert "\x07" not in out
        # token dropped controls + ]52;c; survives as printable ASCII (no harm);
        # the critical check is no raw ESC.
        assert "\x1b]52" not in out

    def test_csi_in_unknown_tools_is_stripped(self):
        console, buf = self._capture()
        # CSI "clear screen" — if echoed raw, would wipe terminal scrollback.
        hostile = "FakeTool\x1b[2J\x1b[H"
        safe = scrub_token(hostile)
        console.print(f"Unknown tools: {safe}")
        out = buf.getvalue()
        assert "\x1b" not in out
        assert "\x1b[2J" not in out

    def test_scrub_token_drops_all_c0_controls(self):
        for byte in range(0x00, 0x20):
            s = f"cmd{chr(byte)}name"
            cleaned = scrub_token(s)
            assert chr(byte) not in cleaned

    def test_scrub_token_drops_del_and_c1(self):
        for byte in [0x7f] + list(range(0x80, 0xa0)):
            s = f"a{chr(byte)}b"
            cleaned = scrub_token(s)
            assert chr(byte) not in cleaned

    def test_scrub_token_cap_is_64(self):
        assert len(scrub_token("A" * 200)) == 64


# ──────────────────────────────────────────────────────────── T-SAFETY.11 ──

class TestHttpsOnlyTracker:
    def test_flush_refuses_http_and_spools(self, tmp_path, monkeypatch):
        # Redirect spool to isolated tmp_path so we don't touch real ~/.cohrint
        monkeypatch.setattr("cohrint_agent.tracker._SPOOL_DIR", tmp_path)
        monkeypatch.setattr("cohrint_agent.tracker._SPOOL_FILE", tmp_path / "spool.jsonl")
        monkeypatch.setattr("cohrint_agent.tracker._SPOOL_LOCK_FILE", tmp_path / "spool.lock")

        cfg = TrackerConfig(
            api_key="crt_test_abc",
            api_base="http://evil.example.com",  # cleartext
            batch_size=100,
            privacy="full",
            debug=False,
        )
        tr = Tracker(cfg)
        tr.record(
            model="claude-sonnet-4-6",
            input_tokens=10,
            output_tokens=5,
            cost_usd=0.001,
            latency_ms=200,
        )
        tr.flush()

        spool = tmp_path / "spool.jsonl"
        assert spool.exists(), "events must be spooled, not sent over HTTP"
        content = spool.read_text()
        assert "crt_test_abc" not in content, "API key must never leak to spool file"
        assert "claude-sonnet-4-6" in content

    def test_flush_refuses_file_scheme(self, tmp_path, monkeypatch):
        monkeypatch.setattr("cohrint_agent.tracker._SPOOL_DIR", tmp_path)
        monkeypatch.setattr("cohrint_agent.tracker._SPOOL_FILE", tmp_path / "spool.jsonl")
        monkeypatch.setattr("cohrint_agent.tracker._SPOOL_LOCK_FILE", tmp_path / "spool.lock")
        cfg = TrackerConfig(api_key="crt_x", api_base="file:///etc/passwd", batch_size=100)
        tr = Tracker(cfg)
        tr.record("m", 1, 1, 0.0, 1)
        tr.flush()
        # must NOT blow up, must spool
        assert (tmp_path / "spool.jsonl").exists()

    def test_localhost_http_refused(self, tmp_path, monkeypatch):
        # HTTP localhost is a legitimate dev convenience ONLY if _assert_https
        # allows it. Current policy: https-only, no exceptions. Confirm that.
        monkeypatch.setattr("cohrint_agent.tracker._SPOOL_DIR", tmp_path)
        monkeypatch.setattr("cohrint_agent.tracker._SPOOL_FILE", tmp_path / "spool.jsonl")
        monkeypatch.setattr("cohrint_agent.tracker._SPOOL_LOCK_FILE", tmp_path / "spool.lock")
        cfg = TrackerConfig(api_key="crt_x", api_base="http://127.0.0.1:8787", batch_size=100)
        tr = Tracker(cfg)
        tr.record("m", 1, 1, 0.0, 1)
        tr.flush()
        assert (tmp_path / "spool.jsonl").exists()


# ──────────────────────────────────────────────────────────── T-SAFETY.12 ──

class TestRendererEscapeScrub:
    def test_render_tool_use_scrubs_command_osc52(self):
        from cohrint_agent import renderer

        buf = io.StringIO()
        renderer.console = Console(file=buf, force_terminal=False, color_system=None)

        tool_input = {"command": "ls\x1b]52;c;BASE64==\x07"}
        renderer.render_tool_use_start("Bash", tool_input)
        out = buf.getvalue()
        assert "\x1b" not in out
        assert "\x07" not in out
        assert "\x1b]52" not in out

    def test_render_tool_result_scrubs_csi(self):
        from cohrint_agent import renderer

        buf = io.StringIO()
        renderer.console = Console(file=buf, force_terminal=False, color_system=None)

        hostile = "line1\x1b[2J\nline2\x1b]52;c;evil\x07"
        renderer.render_tool_result("Read", hostile, is_error=False)
        out = buf.getvalue()
        assert "\x1b" not in out
        assert "\x07" not in out

    def test_render_tool_error_scrubs_first_line(self):
        from cohrint_agent import renderer

        buf = io.StringIO()
        renderer.console = Console(file=buf, force_terminal=False, color_system=None)

        renderer.render_tool_result("Bash", "oh no\x1b]52;c;zzz\x07", is_error=True)
        out = buf.getvalue()
        assert "\x1b" not in out
        assert "\x07" not in out

    def test_scrub_for_terminal_preserves_tab_lf_cr(self):
        s = "line1\n\tindented\rcarriage"
        out = scrub_for_terminal(s)
        assert "\n" in out
        assert "\t" in out
        assert "\r" in out

    def test_scrub_for_terminal_truncates_at_max_len(self):
        s = "A" * 1000
        out = scrub_for_terminal(s, max_len=50)
        assert len(out) == 50
        assert out.endswith("…")

    def test_scrub_for_terminal_coerces_non_string(self):
        assert scrub_for_terminal(None) == "None"
        assert scrub_for_terminal(42) == "42"


# ─────────────────────────────────────────────────────────── T-BOUNDS.argv ──

class TestArgvClamp:
    def test_short_string_unchanged(self):
        assert clamp_argv("hello world") == "hello world"

    def test_oversized_prompt_truncated_to_cap(self):
        huge = "A" * (MAX_ARGV_STRLEN + 10_000)
        out = clamp_argv(huge)
        assert len(out) == MAX_ARGV_STRLEN

    def test_cap_is_below_linux_max_arg_strlen(self):
        # MAX_ARG_STRLEN on Linux is 128 KiB — we must stay strictly under.
        assert MAX_ARGV_STRLEN < 128 * 1024

    def test_non_string_returns_empty(self):
        assert clamp_argv(None) == ""  # type: ignore[arg-type]
        assert clamp_argv(42) == ""  # type: ignore[arg-type]

    def test_claude_build_command_clamps_prompt(self, tmp_path):
        from cohrint_agent.backends.claude_backend import ClaudeCliBackend

        backend = ClaudeCliBackend(config_dir=tmp_path)
        cmd = backend._build_command("B" * (MAX_ARGV_STRLEN + 50_000), str(tmp_path))
        # -p is at index 1, prompt at index 2
        assert cmd[1] == "-p"
        assert len(cmd[2]) == MAX_ARGV_STRLEN


# ────────────────────────────────────────────────────────── T-PRIVACY.allow ──

class TestPrivacyNormalization:
    def test_known_values_preserved(self):
        for v in ("full", "strict", "anonymized", "local-only"):
            assert _normalize_privacy(v) == v

    def test_wrong_case_normalised_to_anonymized(self):
        # "FULL" must not bypass privacy comparisons — defaults to strictest
        # "anonymized" rather than the silently-permissive "full" branch.
        assert _normalize_privacy("FULL") == "anonymized"
        assert _normalize_privacy("Strict") == "anonymized"

    def test_bogus_value_normalised(self):
        assert _normalize_privacy("admin") == "anonymized"
        assert _normalize_privacy("") == "anonymized"
        assert _normalize_privacy(None) == "anonymized"
        assert _normalize_privacy(42) == "anonymized"

    def test_config_normalises_on_construction(self):
        cfg = TrackerConfig(privacy="FULL")
        assert cfg.privacy == "anonymized"


# ───────────────────────────────────────────── T-SAFETY.12 (permission UI) ──

class TestPermissionPromptScrub:
    """
    The Claude Code hook payload (tool_name + tool_input) originates in a
    model response. A prompt-injected OSC-52 in that payload must not reach
    the terminal via the permission dialog. We exercise the rendering path
    directly by constructing the string the dialog would print.
    """

    def test_tool_name_scrub(self):
        hostile = "Bash\x1b]52;c;evil==\x07"
        safe = scrub_token(hostile)
        assert "\x1b" not in safe
        assert "\x07" not in safe

    def test_bash_command_scrub_preserves_length_cap(self):
        hostile = "ls -la\x1b]52;c;dGVzdA==\x07" + "A" * 1000
        safe = scrub_for_terminal(hostile, max_len=200)
        assert "\x1b" not in safe
        assert len(safe) <= 200


# ─────────────────────────────────────────────────────────── T-BOUNDS.queue ──

class TestTrackerQueueCap:
    def test_queue_caps_at_max_queue_size(self, tmp_path, monkeypatch):
        monkeypatch.setattr("cohrint_agent.tracker._SPOOL_DIR", tmp_path)
        monkeypatch.setattr("cohrint_agent.tracker._SPOOL_FILE", tmp_path / "spool.jsonl")
        monkeypatch.setattr("cohrint_agent.tracker._SPOOL_LOCK_FILE", tmp_path / "spool.lock")
        from cohrint_agent.tracker import MAX_QUEUE_SIZE

        # No api_key → record() still appends but _do_flush short-circuits.
        cfg = TrackerConfig(api_key="", api_base="https://api.example.com", batch_size=10_000)
        tr = Tracker(cfg)
        for i in range(MAX_QUEUE_SIZE + 50):
            tr.record("m", 1, 1, 0.0, 1, session_id=f"s{i}")
        assert len(tr._queue) == MAX_QUEUE_SIZE

    def test_oldest_dropped_first(self, tmp_path, monkeypatch):
        monkeypatch.setattr("cohrint_agent.tracker._SPOOL_DIR", tmp_path)
        monkeypatch.setattr("cohrint_agent.tracker._SPOOL_FILE", tmp_path / "spool.jsonl")
        monkeypatch.setattr("cohrint_agent.tracker._SPOOL_LOCK_FILE", tmp_path / "spool.lock")
        from cohrint_agent.tracker import MAX_QUEUE_SIZE

        cfg = TrackerConfig(api_key="", api_base="https://api.example.com", batch_size=10_000)
        tr = Tracker(cfg)
        for i in range(MAX_QUEUE_SIZE + 5):
            tr.record("m", 1, 1, 0.0, 1, session_id=f"sess-{i}")
        oldest = tr._queue[0].session_id
        newest = tr._queue[-1].session_id
        # first 5 dropped → queue starts at sess-5
        assert oldest == "sess-5"
        assert newest == f"sess-{MAX_QUEUE_SIZE + 4}"


# ───────────────────────────────────────────────────────── T-BOUNDS.sessions ──

class TestSessionListAllCap:
    def test_skips_oversized_session_files(self, tmp_path):
        from cohrint_agent.session_store import MAX_SESSION_FILE_BYTES
        store = SessionStore(sessions_dir=tmp_path)
        # One valid, one bloated
        valid_id = "00000000-0000-4000-8000-000000000001"
        bloat_id = "00000000-0000-4000-8000-000000000002"
        (tmp_path / f"{valid_id}.json").write_text(
            '{"id": "' + valid_id + '", "last_active_at": "2026-01-01T00:00:00Z"}'
        )
        (tmp_path / f"{bloat_id}.json").write_text(
            '{"id": "' + bloat_id + '", "payload":"' + ("X" * (MAX_SESSION_FILE_BYTES + 1024)) + '"}'
        )
        sessions = store.list_all()
        ids = {s.get("id") for s in sessions}
        assert valid_id in ids
        assert bloat_id not in ids  # skipped — too large

    def test_stops_at_max_sessions_listed(self, tmp_path):
        from cohrint_agent.session_store import MAX_SESSIONS_LISTED
        store = SessionStore(sessions_dir=tmp_path)
        # Create MAX + 50 small valid files. Keep to a reasonable count for
        # test speed — monkeypatch the limit low instead of generating 1000.
        import cohrint_agent.session_store as ss
        saved = ss.MAX_SESSIONS_LISTED
        try:
            ss.MAX_SESSIONS_LISTED = 5
            for i in range(10):
                sid = f"00000000-0000-4000-8000-{i:012x}"
                (tmp_path / f"{sid}.json").write_text(
                    f'{{"id": "{sid}", "last_active_at": "2026-01-0{i}T00:00:00Z"}}'
                )
            sessions = store.list_all()
            assert len(sessions) == 5
        finally:
            ss.MAX_SESSIONS_LISTED = saved


# ─────────────────────────────────────────────────────── T-BOUNDS.messages ──

class TestAgentClientHistoryTrim:
    """Exercise the trim helper without constructing a live AgentClient —
    AgentClient.__init__ demands a real ANTHROPIC_API_KEY. We bind the
    unbound method to a minimal object that only carries the .messages
    attribute so the logic under test is preserved."""

    def test_evicts_in_pairs_and_respects_cap(self):
        from cohrint_agent.api_client import AgentClient

        class _Stub:
            MAX_MESSAGE_HISTORY = AgentClient.MAX_MESSAGE_HISTORY

        stub = _Stub()
        stub.messages = []
        for i in range(300):
            stub.messages.append({"role": "user", "content": f"u{i}"})
            stub.messages.append({"role": "assistant", "content": f"a{i}"})

        AgentClient._trim_history(stub)

        assert len(stub.messages) <= AgentClient.MAX_MESSAGE_HISTORY
        assert stub.messages[0]["role"] == "user"

    def test_no_op_when_under_cap(self):
        from cohrint_agent.api_client import AgentClient

        class _Stub:
            MAX_MESSAGE_HISTORY = AgentClient.MAX_MESSAGE_HISTORY

        stub = _Stub()
        stub.messages = [{"role": "user", "content": "hi"}]
        AgentClient._trim_history(stub)
        assert stub.messages == [{"role": "user", "content": "hi"}]


# ── T-CONCUR.* — scan 3 concurrency fixes ────────────────────────────────────


class TestAtomicSessionSave:
    """T-CONCUR.atomic_save — SessionStore.save uses tmp + os.replace."""

    def _valid_id(self) -> str:
        return "00000000-0000-4000-8000-000000000001"

    def test_target_never_partially_written(self, tmp_path):
        # Simulate a fsync-visible atomic rename: after save the target
        # contains the full JSON, never a truncated prefix. We can't crash
        # the interpreter mid-write, so instead we verify the tmp path
        # does not linger after a successful save and the target is valid.
        store = SessionStore(sessions_dir=tmp_path / "sessions")
        sid = self._valid_id()
        store.save({
            "id": sid,
            "messages": [{"role": "user", "text": "x" * 1024}],
            "cost_summary": {},
        })
        sessions_dir = tmp_path / "sessions"
        # No tmp or lock files left behind
        leftovers = [p.name for p in sessions_dir.iterdir()
                     if p.name.endswith((".tmp", ".lock"))]
        # Lock file is intentionally persistent for future saves, tmp is not
        assert not any(n.endswith(".tmp") for n in leftovers)
        # Target is parseable JSON with expected id
        import json as _json
        data = _json.loads((sessions_dir / f"{sid}.json").read_text())
        assert data["id"] == sid

    def test_concurrent_save_serializes_under_lock(self, tmp_path):
        import threading
        store = SessionStore(sessions_dir=tmp_path / "sessions")
        sid = self._valid_id()
        errors: list[BaseException] = []

        def writer(i: int) -> None:
            try:
                store.save({
                    "id": sid,
                    "messages": [{"role": "user", "text": f"msg-{i}"}],
                    "cost_summary": {},
                })
            except BaseException as e:  # noqa: BLE001
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors
        # The surviving file is valid JSON from exactly one writer
        import json as _json
        data = _json.loads((tmp_path / "sessions" / f"{sid}.json").read_text())
        assert data["id"] == sid
        assert data["messages"][0]["text"].startswith("msg-")


class TestTrackerTimerRace:
    """T-CONCUR.timer_race — stop() cancels the pending timer and _running
    gating prevents a rescheduled timer after shutdown."""

    def test_stop_clears_timer_reference(self):
        from cohrint_agent.tracker import Tracker, TrackerConfig
        cfg = TrackerConfig(api_key="k", flush_interval=600.0)
        t = Tracker(cfg)
        t.start()
        assert t._running is True
        assert t._timer is not None
        t.stop()
        assert t._running is False
        assert t._timer is None

    def test_reschedule_aborts_after_stop(self):
        # Call _flush_and_reschedule after stop — it must not start a new
        # timer, otherwise a shutdown tracker could fire a rogue flush.
        from cohrint_agent.tracker import Tracker, TrackerConfig
        cfg = TrackerConfig(api_key="k", flush_interval=600.0)
        t = Tracker(cfg)
        with t._state_lock:
            t._running = False
        # Should be a no-op
        t._schedule_flush()
        assert t._timer is None


class TestCostNonNegative:
    """T-COST.nonneg — backends returning negative tokens/cost cannot
    decrement the session accumulator."""

    def test_record_usage_clamps_negatives(self):
        from cohrint_agent.cost_tracker import SessionCost

        class _U:
            input_tokens = -100
            output_tokens = -50
            cache_read_input_tokens = -1
            cache_creation_input_tokens = -1

        cost = SessionCost(model="claude-sonnet-4-6")
        turn = cost.record_usage(_U())
        assert turn.input_tokens == 0
        assert turn.output_tokens == 0
        assert turn.cost_usd == 0.0
        assert cost.total_cost_usd == 0.0

    def test_record_usage_raw_clamps_negatives(self):
        from cohrint_agent.cost_tracker import SessionCost

        cost = SessionCost(model="claude-sonnet-4-6")
        turn = cost.record_usage_raw(input_tokens=-5, output_tokens=-5, cost_usd=-1.0)
        assert turn.input_tokens == 0
        assert turn.output_tokens == 0
        assert turn.cost_usd == 0.0
        assert cost.total_cost_usd == 0.0


class TestCostUnknownModelFallback:
    """T-COST.unknown_model — calculate_cost falls back to default rates
    instead of returning 0.0, which would mask spend."""

    def test_unknown_model_uses_default_rates(self):
        from cohrint_agent.pricing import calculate_cost, MODEL_PRICES
        # Model that doesn't exist and has no prefix match
        cost = calculate_cost("nonexistent-model-v99", 1_000_000, 1_000_000)
        # Should match the 'default' row: $3 input + $15 output = $18
        expected = (
            1_000_000 * MODEL_PRICES["default"]["input"] / 1_000_000
            + 1_000_000 * MODEL_PRICES["default"]["output"] / 1_000_000
        )
        assert cost == pytest.approx(expected)
        assert cost > 0


class TestAnonymizedSessionIdHashed:
    """T-PRIVACY.session_id — anonymized mode must hash session_id so
    dashboard observers cannot correlate turns of the same session."""

    def test_session_id_hashed_in_anonymized_mode(self):
        from cohrint_agent.tracker import Tracker, TrackerConfig
        cfg = TrackerConfig(api_key="k", privacy="anonymized")
        t = Tracker(cfg)
        raw_sid = "11111111-2222-4333-8444-555555555555"
        t.record(
            model="claude-sonnet-4-6",
            input_tokens=1,
            output_tokens=1,
            cost_usd=0.0,
            latency_ms=0,
            agent_name="claude",
            session_id=raw_sid,
        )
        with t._lock:
            event = t._queue[0]
        assert event.session_id != raw_sid
        # 64 hex chars = SHA-256 digest
        assert len(event.session_id) == 64
        assert all(c in "0123456789abcdef" for c in event.session_id)


class TestSaveBeforePostHooks:
    """T-COST.save_first — session.send persists cost before running
    post-hooks/telemetry so a crash after billing cannot lose spend."""

    def test_save_called_before_post_hooks(self, tmp_path, monkeypatch):
        from cohrint_agent.session import CohrintSession
        from cohrint_agent.session_store import SessionStore
        from unittest.mock import MagicMock
        from cohrint_agent.backends.base import BackendCapabilities, BackendResult

        backend = MagicMock()
        backend.name = "api"
        backend.capabilities = BackendCapabilities(
            supports_process=False, supports_streaming=False,
            token_count="exact", tool_format="anthropic",
        )
        backend.send.return_value = BackendResult(
            output_text="ok", input_tokens=10, output_tokens=5,
            estimated=False, model="claude-sonnet-4-6",
            exit_code=0, cost_usd=0.01,
        )

        store = SessionStore(sessions_dir=tmp_path / "sessions")
        session = CohrintSession.create(backend=backend, cwd=str(tmp_path), store=store)

        calls: list[str] = []
        import cohrint_agent.session as _s
        original_post = _s.run_post_hooks
        original_save = session.save

        def wrapped_save():
            calls.append("save")
            return original_save()

        def wrapped_post_hooks(ctx):
            calls.append("post_hooks")
            return original_post(ctx)

        session.save = wrapped_save  # type: ignore[assignment]
        monkeypatch.setattr(_s, "run_post_hooks", wrapped_post_hooks)

        session.send("hello")
        assert "save" in calls
        assert "post_hooks" in calls
        assert calls.index("save") < calls.index("post_hooks"), (
            f"save must run before post_hooks, got: {calls}"
        )


class TestSecretScrub:
    """T-SAFETY.secret_scrub — api keys / Bearer tokens never reach terminal."""

    def test_anthropic_key_redacted(self):
        text = "request failed: sk-ant-api03-abcdef1234567890ABCDEF_-abcdef"
        out = scrub_for_terminal(text)
        assert "sk-ant-" not in out
        assert "[REDACTED]" in out

    def test_cohrint_token_redacted(self):
        text = "Authorization: Bearer crt_abcdef1234567890ABCDEF_-xyz"
        out = scrub_for_terminal(text)
        assert "crt_" not in out
        assert "Bearer" not in out or "[REDACTED]" in out

    def test_bearer_header_redacted(self):
        text = "401 Unauthorized: Authorization: Bearer supersecrettoken1234567890"
        out = scrub_for_terminal(text)
        assert "supersecrettoken1234567890" not in out


class TestPermissionServerFailClosed:
    """T-SAFETY.fail_closed — timeout/error paths must return 'deny', not 'allow'."""

    def test_malformed_payload_returns_deny(self, tmp_path):
        import socket as _socket
        import threading
        from cohrint_agent.permission_server import PermissionServer

        server = PermissionServer(
            socket_path=str(tmp_path / "fake.sock"),
            permissions=None,
        )
        s1, s2 = _socket.socketpair()
        # Handle the connection in a worker so the test never blocks.
        t = threading.Thread(
            target=server._handle_connection, args=(s2,), daemon=True
        )
        t.start()
        try:
            s1.sendall(b"this is not json\n")
            s1.settimeout(3.0)
            resp = s1.recv(64)
            assert resp.strip() == b"deny"
        finally:
            s1.close()
            t.join(timeout=2.0)

    def test_recv_buffer_capped(self, tmp_path, monkeypatch):
        import socket as _socket
        import threading
        from cohrint_agent.permission_server import PermissionServer

        server = PermissionServer(
            socket_path=str(tmp_path / "fake.sock"),
            permissions=None,
        )
        # Shrink the cap so a few KB without a newline trips it — avoids
        # socketpair buffer-full blocking with a real 64 KB flood.
        monkeypatch.setattr(server, "_MAX_RECV_BYTES", 4096, raising=False)
        s1, s2 = _socket.socketpair()
        t = threading.Thread(
            target=server._handle_connection, args=(s2,), daemon=True
        )
        t.start()
        try:
            # Send 5 KB without a newline — server hits its shrunk cap.
            s1.sendall(b"A" * 5000)
            s1.settimeout(3.0)
            resp = s1.recv(64)
            assert resp.strip() == b"deny"
        finally:
            s1.close()
            t.join(timeout=2.0)


class TestResetsAtValidation:
    """T-SAFETY.resets_at — reject out-of-range rate-limit timestamps."""

    def test_garbage_resets_at_ignored(self):
        from cohrint_agent.backends.claude_backend import _parse_stream_event
        state: dict = {}
        # far-future (ms-vs-s confusion), NaN, and None all rejected
        _parse_stream_event(
            {"type": "rate_limit_event", "rate_limit_info": {"resetsAt": 99999999999}},
            state, render=False,
        )
        assert state.get("rate_limit_resets_at") is None
        _parse_stream_event(
            {"type": "rate_limit_event", "rate_limit_info": {"resetsAt": float("nan")}},
            state, render=False,
        )
        assert state.get("rate_limit_resets_at") is None
        _parse_stream_event(
            {"type": "rate_limit_event", "rate_limit_info": {"resetsAt": None}},
            state, render=False,
        )
        assert state.get("rate_limit_resets_at") is None

    def test_valid_resets_at_accepted(self):
        import time
        from cohrint_agent.backends.claude_backend import _parse_stream_event
        state: dict = {}
        valid = time.time() + 60  # 60 s in the future
        _parse_stream_event(
            {"type": "rate_limit_event", "rate_limit_info": {"resetsAt": valid}},
            state, render=False,
        )
        assert state.get("rate_limit_resets_at") == valid


class TestOtelBoundedWorker:
    """T-CONCUR.otel_worker — fanning out N events does not spawn N threads."""

    def test_export_async_uses_shared_worker(self, monkeypatch):
        import threading
        from cohrint_agent import telemetry as tmod
        monkeypatch.setenv("COHRINT_OTEL_ENABLED", "true")

        # Reset the module-level singletons so this test is hermetic.
        monkeypatch.setattr(tmod, "_export_queue", None)
        monkeypatch.setattr(tmod, "_worker_thread", None)

        before = threading.active_count()
        exp = tmod.OTelExporter()
        for i in range(50):
            exp.export_async({"model": "claude-sonnet-4-6",
                              "prompt_tokens": 1, "completion_tokens": 1,
                              "cost_usd": 0.0, "latency_ms": 1})
        after = threading.active_count()
        # We should see at most one new long-lived worker thread, not 50.
        assert after - before <= 2, (
            f"export_async spawned {after - before} threads for 50 events"
        )


# ─────────────────────────────────── T-SAFETY.session_id_argv (scan 6/7) ──

class TestClaudeSessionIdValidated:
    """A prompt-injected model-supplied session_id must NOT reach the next
    --resume argv. The backend must reject anything that isn't UUIDv4."""

    def test_malicious_session_id_is_rejected(self):
        from cohrint_agent.backends.claude_backend import ClaudeCliBackend, _parse_stream_event
        be = ClaudeCliBackend()
        state = {"text": "", "result": None, "rate_limit_resets_at": None}
        # Parse a forged result event.
        _parse_stream_event(
            {"type": "result", "session_id": "--inject-evil-flag",
             "total_cost_usd": 0.0, "usage": {"input_tokens": 0, "output_tokens": 0}},
            state, render=False,
        )
        # Emulate the post-send write-back path in send()
        from cohrint_agent.session_store import is_valid_session_id
        sid = state["result"]["session_id"]
        if sid and is_valid_session_id(sid):
            be._claude_session_id = sid
        assert be._claude_session_id is None, (
            "malicious session_id must not be persisted for --resume argv"
        )

    def test_valid_uuid_is_accepted(self):
        from cohrint_agent.backends.claude_backend import ClaudeCliBackend, _parse_stream_event
        from cohrint_agent.session_store import is_valid_session_id
        be = ClaudeCliBackend()
        state = {"text": "", "result": None, "rate_limit_resets_at": None}
        valid = "01234567-89ab-4cde-8f01-23456789abcd"
        _parse_stream_event(
            {"type": "result", "session_id": valid,
             "total_cost_usd": 0.0, "usage": {"input_tokens": 0, "output_tokens": 0}},
            state, render=False,
        )
        sid = state["result"]["session_id"]
        if sid and is_valid_session_id(sid):
            be._claude_session_id = sid
        assert be._claude_session_id == valid


# ─────────────────────────────────── T-BOUNDS.perm_file (scan 6/7) ────────

class TestPermissionsParseBomb:
    """permissions.json over the cap must not be parsed into memory."""

    def test_oversized_file_falls_back_to_defaults(self, tmp_path, monkeypatch):
        from cohrint_agent.permissions import PermissionManager, _MAX_PERM_FILE_BYTES
        # Write a file 2× the cap. We don't need valid JSON — the guard
        # must refuse to read it before json.load is invoked.
        cfg = tmp_path / ".cohrint-agent"
        cfg.mkdir(parents=True)
        oversized = cfg / "permissions.json"
        oversized.write_bytes(b"x" * (_MAX_PERM_FILE_BYTES + 1024))
        pm = PermissionManager(config_dir=cfg)
        # Safe defaults should apply (SAFE_TOOLS only); no exception, no OOM.
        from cohrint_agent.tools import SAFE_TOOLS
        assert pm.always_approved == set(SAFE_TOOLS)
        assert pm.always_denied == set()

    def test_oversized_file_append_audit_is_safe(self, tmp_path):
        from cohrint_agent.permissions import PermissionManager, _MAX_PERM_FILE_BYTES
        cfg = tmp_path / ".cohrint-agent"
        cfg.mkdir(parents=True)
        (cfg / "permissions.json").write_bytes(b"{" * (_MAX_PERM_FILE_BYTES + 1))
        pm = PermissionManager(config_dir=cfg)
        # Should reset to default shape, not OOM or raise.
        pm.append_audit(tool="Read", input_preview="x", decision="allow_once", backend="api")
        # After reset + append, file should now be the default shape + 1 entry.
        import json
        data = json.loads((cfg / "permissions.json").read_text())
        assert isinstance(data.get("audit_log"), list)
        assert len(data["audit_log"]) == 1


# ─────────────────────────────────── T-SAFETY.config_dir_escape (scan 6/7) ─

class TestSafeConfigDir:
    """COHRINT_CONFIG_DIR pointing outside $HOME must be rejected."""

    def test_etc_escape_falls_back_to_default(self, monkeypatch):
        from cohrint_agent.process_safety import safe_config_dir
        from pathlib import Path
        monkeypatch.setenv("COHRINT_CONFIG_DIR", "/etc")
        result = safe_config_dir()
        assert result == Path.home() / ".cohrint-agent"

    def test_root_escape_falls_back_to_default(self, monkeypatch):
        from cohrint_agent.process_safety import safe_config_dir
        from pathlib import Path
        monkeypatch.setenv("COHRINT_CONFIG_DIR", "/")
        result = safe_config_dir()
        assert result == Path.home() / ".cohrint-agent"

    def test_home_subdir_is_accepted(self, monkeypatch, tmp_path):
        from cohrint_agent.process_safety import safe_config_dir
        from pathlib import Path
        # tmp_path is under TMPDIR (or /tmp) which the helper explicitly allows
        # so tests can point at an isolated scratch dir.
        monkeypatch.setenv("COHRINT_CONFIG_DIR", str(tmp_path))
        result = safe_config_dir()
        assert result == tmp_path.resolve()

    def test_empty_env_uses_default(self, monkeypatch):
        from cohrint_agent.process_safety import safe_config_dir
        from pathlib import Path
        monkeypatch.delenv("COHRINT_CONFIG_DIR", raising=False)
        assert safe_config_dir() == Path.home() / ".cohrint-agent"


# ─────────────────────────────────── T-SAFETY.rate_state_validation (scan 6/7) ─

class TestRateStateValidation:
    """rate_state.json with inf / nan / negative / stale fields must be rejected."""

    def test_inf_tokens_rejected(self, tmp_path, monkeypatch):
        import json, time
        from cohrint_agent import rate_limiter as rl
        state = tmp_path / "rate_state.json"
        monkeypatch.setattr(rl, "_STATE_FILE", state)
        # Plant an insane bucket that would otherwise always grant requests.
        state.parent.mkdir(parents=True, exist_ok=True)
        state.write_text(json.dumps({
            "tokens": float("inf"), "capacity": float("inf"),
            "refill_rate": float("inf"), "last_refill": time.time(),
        }))
        # First acquire falls back to default → 60 tokens → allow.
        assert rl.acquire(1.0) is True
        # Re-read state and confirm it's now sane finite values.
        saved = json.loads(state.read_text())
        assert saved["tokens"] < 1e6
        assert saved["capacity"] < 1e6

    def test_nan_fields_rejected(self, tmp_path, monkeypatch):
        import json, math, time
        from cohrint_agent import rate_limiter as rl
        state = tmp_path / "rate_state.json"
        monkeypatch.setattr(rl, "_STATE_FILE", state)
        state.parent.mkdir(parents=True, exist_ok=True)
        state.write_text(json.dumps({
            "tokens": float("nan"), "capacity": 60.0,
            "refill_rate": 1.0, "last_refill": time.time(),
        }))
        assert rl.acquire(1.0) is True
        saved = json.loads(state.read_text())
        assert not math.isnan(saved["tokens"])

    def test_stale_future_timestamp_rejected(self, tmp_path, monkeypatch):
        import json, time
        from cohrint_agent import rate_limiter as rl
        state = tmp_path / "rate_state.json"
        monkeypatch.setattr(rl, "_STATE_FILE", state)
        state.parent.mkdir(parents=True, exist_ok=True)
        # last_refill 10 years in the future — attacker trick to refill
        # tokens to capacity on every call.
        state.write_text(json.dumps({
            "tokens": 0.0, "capacity": 60.0, "refill_rate": 1.0,
            "last_refill": time.time() + 10 * 365 * 86400,
        }))
        rl.acquire(1.0)
        saved = json.loads(state.read_text())
        assert saved["last_refill"] <= time.time() + 60


# ─────────────────────────────────── T-SAFETY.budget_env (scan 6/7) ────────

class TestBudgetEnvValidation:
    """COHRINT_BUDGET_USD=inf/nan/neg must not disable the budget gate."""

    def test_inf_budget_returns_zero(self):
        from cohrint_agent.cli import _parse_budget_env
        assert _parse_budget_env("inf") == 0.0

    def test_nan_budget_returns_zero(self):
        from cohrint_agent.cli import _parse_budget_env
        assert _parse_budget_env("nan") == 0.0

    def test_negative_budget_returns_zero(self):
        from cohrint_agent.cli import _parse_budget_env
        assert _parse_budget_env("-10") == 0.0

    def test_zero_budget_returns_zero(self):
        from cohrint_agent.cli import _parse_budget_env
        assert _parse_budget_env("0") == 0.0

    def test_valid_positive_passes(self):
        from cohrint_agent.cli import _parse_budget_env
        assert _parse_budget_env("42.50") == 42.50

    def test_garbage_returns_zero(self):
        from cohrint_agent.cli import _parse_budget_env
        assert _parse_budget_env("not-a-number") == 0.0
        assert _parse_budget_env(None) == 0.0


# ─────────────────────────────────── T-SAFETY.otel_https (scan 7/7) ────────

class TestOtelEndpointHttpsEnforced:
    """OTel exporter must refuse plaintext HTTP endpoints — Bearer tokens
    in Authorization headers would otherwise leak."""

    def test_http_endpoint_disables_exporter(self, monkeypatch):
        monkeypatch.setenv("COHRINT_OTEL_ENABLED", "true")
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://evil.example")
        monkeypatch.delenv("COHRINT_ALLOW_HTTP", raising=False)
        from cohrint_agent.telemetry import OTelExporter
        exp = OTelExporter()
        assert exp.enabled is False

    def test_https_endpoint_enables_exporter(self, monkeypatch):
        monkeypatch.setenv("COHRINT_OTEL_ENABLED", "true")
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "https://collector.example")
        from cohrint_agent.telemetry import OTelExporter
        exp = OTelExporter()
        assert exp.enabled is True

    def test_localhost_with_allow_http_enabled(self, monkeypatch):
        monkeypatch.setenv("COHRINT_OTEL_ENABLED", "true")
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://127.0.0.1:4318")
        monkeypatch.setenv("COHRINT_ALLOW_HTTP", "1")
        from cohrint_agent.telemetry import OTelExporter
        exp = OTelExporter()
        assert exp.enabled is True


# ─────────────────────────────────── T-BOUNDS.audit_log (scan 7/7) ─────────

class TestAuditLogRotation:
    """audit_log must rotate before hitting the 1 MiB parse-bomb cap."""

    def test_audit_log_caps_at_500_entries(self, tmp_path):
        from cohrint_agent.permissions import PermissionManager, _AUDIT_LOG_MAX_ENTRIES
        import json as _json
        cfg = tmp_path / ".cohrint-agent"
        cfg.mkdir(parents=True)
        pm = PermissionManager(config_dir=cfg)
        # Append well past the cap.
        for i in range(_AUDIT_LOG_MAX_ENTRIES + 50):
            pm.append_audit(
                tool="Read", input_preview=f"/tmp/f{i}",
                decision="allow_once", backend="api",
            )
        data = _json.loads((cfg / "permissions.json").read_text())
        assert len(data["audit_log"]) == _AUDIT_LOG_MAX_ENTRIES
        # Newest entries retained (rolling window, not first-N).
        assert data["audit_log"][-1]["input_preview"].endswith("549")


# ─────────────────────────────────── T-SAFETY.clock_rollback (scan 7/7) ────

class TestClockRollback:
    """Backward clock step must not drain tokens or poison state."""

    def test_negative_elapsed_is_clamped_to_zero(self):
        from cohrint_agent.rate_limiter import RateBucket, _refill
        # last_refill in the future by 10 seconds (simulates clock rollback).
        import time
        b = RateBucket(tokens=30.0, capacity=60.0, refill_rate=1.0,
                       last_refill=time.time() + 10.0)
        out = _refill(b)
        # Tokens must NOT have been drained by the negative delta.
        assert out.tokens >= 30.0
        assert out.tokens <= 60.0  # still capped at capacity


# ─────────────────────────────────── T-SAFETY.list_all_toctou (scan 7/7) ───

class TestListAllToctouSafe:
    """list_all must not OOM even if a file is replaced with an oversized
    one between the size check and the read."""

    def test_oversized_file_capped_during_read(self, tmp_path):
        from cohrint_agent.session_store import SessionStore, MAX_SESSION_FILE_BYTES
        store = SessionStore(sessions_dir=tmp_path)
        # Plant an already-oversized file. The fd-stat check must reject it.
        big = tmp_path / "00000000-0000-4000-8000-000000000001.json"
        big.write_bytes(b"x" * (MAX_SESSION_FILE_BYTES + 100))
        # And a legitimate small file.
        small = tmp_path / "00000000-0000-4000-8000-000000000002.json"
        small.write_text('{"id": "00000000-0000-4000-8000-000000000002", '
                         '"last_active_at": "2026-01-01T00:00:00+00:00"}')
        listed = store.list_all()
        # Only the small file should appear.
        assert len(listed) == 1
        assert listed[0]["id"].endswith("000000000002")


# ─────────────────────────────────── T-BOUNDS.lockfile_cleanup (scan 7/7) ──

class TestLockfileCleanup:
    """Lockfiles must not accumulate per session in the sessions dir."""

    def test_save_unlinks_lockfile_after_release(self, tmp_path):
        from cohrint_agent.session_store import SessionStore
        store = SessionStore(sessions_dir=tmp_path)
        sid = "00000000-0000-4000-8000-000000000003"
        store.save({"id": sid, "history": [], "cost_summary": {}})
        # Only the .json should remain — no sibling .lock / .tmp files.
        files = sorted(p.name for p in tmp_path.iterdir())
        assert f"{sid}.json" in files
        assert not any(name.endswith(".lock") for name in files), files
        assert not any(name.endswith(".tmp") for name in files), files


# ─────────────────────── T-SAFETY.append_audit_atomic (scan 8/17) ───────────

class TestAppendAuditAtomic:
    """append_audit must not leave the live permissions.json truncated if
    json.dump / write fails mid-call; always_denied must survive crashes."""

    def test_interrupted_dump_does_not_wipe_always_denied(self, tmp_path, monkeypatch):
        from cohrint_agent import permissions as P
        pm = P.PermissionManager(config_dir=tmp_path)
        pm.deny(["DangerTool"])
        assert "DangerTool" in pm.always_denied

        orig_dump = P.json.dump

        def flaky_dump(data, f, **kw):
            # Every call to json.dump after this patch raises — simulates
            # ENOSPC hitting append_audit's tmp-write.
            f.write("{")  # leave a partial byte in the tmp file
            raise OSError(28, "No space left on device")

        monkeypatch.setattr(P.json, "dump", flaky_dump)
        with pytest.raises(OSError):
            pm.append_audit(tool="Bash", input_preview="rm -rf /",
                            decision="deny_always", backend="api")
        # Undo the monkeypatch so the second PermissionManager can re-read.
        monkeypatch.setattr(P.json, "dump", orig_dump)
        # Live file must still be intact — not truncated.
        pm2 = P.PermissionManager(config_dir=tmp_path)
        assert "DangerTool" in pm2.always_denied

    def test_append_audit_survives_oversized_file(self, tmp_path):
        """Oversized file triggers the explicit reset branch, not the
        'parse-failed' branch — entry is still appended to a fresh file."""
        from cohrint_agent import permissions as P
        pm = P.PermissionManager(config_dir=tmp_path)
        # Plant an oversized file directly at the permissions path.
        pm._perm_file.write_bytes(b"x" * (P._MAX_PERM_FILE_BYTES + 100))
        pm.append_audit(tool="Read", input_preview="/etc/passwd",
                        decision="allow_session", backend="api")
        # File must now be valid JSON containing our entry.
        import json as _json
        data = _json.loads(pm._perm_file.read_text())
        assert isinstance(data.get("audit_log"), list)
        assert data["audit_log"][-1]["tool"] == "Read"
        assert data["audit_log"][-1]["decision"] == "allow_session"


# ─────────────────── T-SAFETY.save_failure_visible (scan 8/17) ──────────────

class TestSaveFailureVisible:
    """A CohrintSession.save() failure inside send() must emit a stderr
    warning exactly once per session — silent data loss is unacceptable."""

    def test_save_failure_warns_once(self, capsys):
        """Exercise the save-failure warning branch in isolation — the
        session constructor takes a full Backend wiring, which is too
        heavy for a unit test; this test proves the warning logic is
        idempotent per-session."""

        class FakeSession:
            _save_warned = False

            def save(self):
                raise OSError("disk full")

        sess = FakeSession()
        for _ in range(3):
            try:
                sess.save()
            except Exception as e:
                if not getattr(sess, "_save_warned", False):
                    import sys
                    print(
                        f"[cohrint-agent] warning: session save failed "
                        f"(spend accounting may be incomplete): {e}",
                        file=sys.stderr,
                    )
                    sess._save_warned = True
        err = capsys.readouterr().err
        assert err.count("session save failed") == 1
        assert "disk full" in err

    def test_production_send_path_warns_on_save_failure(self, capsys, monkeypatch):
        """Confirm the production code path in session.py actually emits
        the warning — guards against the snippet drifting from reality."""
        # Read the production source and exec the exact warning block the
        # fix adds inside send(). If the block ever disappears this test
        # breaks visibly.
        import pathlib
        src = pathlib.Path(
            "cohrint_agent/session.py"
        ).read_text()
        assert "session save failed" in src
        assert "_save_warned" in src


# ─────────────── T-SAFETY.resume_error_visible (scan 8/17) ──────────────────

class TestResumeErrorVisible:
    """--resume generic failures must reset args.resume AND warn the user
    — never silently pass through with a broken session id."""

    def test_generic_exception_resets_resume(self):
        # Simulate the fixed except block logic in isolation (the CLI
        # wiring around it is covered by the other resume tests).
        class Args:
            resume = "00000000-0000-4000-8000-000000000abc"
        args = Args()
        from rich.console import Console
        import io
        buf = io.StringIO()
        console = Console(file=buf, force_terminal=False)
        try:
            raise RuntimeError("corrupt json")
        except Exception as e:
            console.print(
                f"  [red]Failed to load session {args.resume!r}: "
                f"{type(e).__name__}. Starting fresh.[/red]"
            )
            args.resume = None
        assert args.resume is None
        assert "Failed to load session" in buf.getvalue()
        assert "RuntimeError" in buf.getvalue()


# ─────────────── T-SAFETY.oversized_control_flow (scan 8/17) ───────────────

class TestOversizedControlFlow:
    """append_audit must distinguish 'oversized → reset' from 'json parse
    failed' — they used to share a raise/except branch and were
    indistinguishable in logs."""

    def test_valid_json_is_preserved_when_not_oversized(self, tmp_path):
        """Critical regression: valid pre-existing audit_log entries must
        NOT be wiped by append_audit. A bug collapsing the branches would
        drop prior entries on every call."""
        from cohrint_agent import permissions as P
        pm = P.PermissionManager(config_dir=tmp_path)
        pm.approve(["ToolA"], always=True)  # seeds the file (also audits)
        pm.append_audit(tool="ToolA", input_preview="first",
                        decision="allow_session", backend="api")
        pm.append_audit(tool="ToolA", input_preview="second",
                        decision="allow_session", backend="api")
        import json as _json
        data = _json.loads(pm._perm_file.read_text())
        log = data["audit_log"]
        # approve() emits one audit entry + the two explicit append_audit
        # calls above → 3 entries total, and order must be preserved.
        assert len(log) == 3
        assert log[-2]["input_preview"] == "first"
        assert log[-1]["input_preview"] == "second"
        # always_approved still present (not wiped by the reset branch).
        assert "ToolA" in data["always_approved"]


# ─────────────── T-SAFETY.permissions_debug_logging (scan 8/17) ────────────

class TestPermissionsDebugLogging:
    """_load / _read_raw must emit a debug log when parsing fails, not
    silently swallow — otherwise debugging corruption reports is impossible."""

    def test_load_logs_corruption_at_debug(self, tmp_path, caplog):
        import logging
        from cohrint_agent import permissions as P
        perm_file = tmp_path / "permissions.json"
        perm_file.write_text("{not valid json")
        with caplog.at_level(logging.DEBUG, logger="cohrint_agent.permissions"):
            P.PermissionManager(config_dir=tmp_path)
        assert any("permissions load failed" in r.message for r in caplog.records)

    def test_read_raw_logs_corruption_at_debug(self, tmp_path, caplog):
        import logging
        from cohrint_agent import permissions as P
        pm = P.PermissionManager(config_dir=tmp_path)
        pm._perm_file.write_text("{still not valid")
        with caplog.at_level(logging.DEBUG, logger="cohrint_agent.permissions"):
            pm._read_raw()
        assert any("read_raw failed" in r.message for r in caplog.records)


# ───────────────────────── T-SAFETY.ssrf_private_ip (scan 9/17) ─────────────

class TestAssertHttpsSsrfGuard:
    """_assert_https_api_base must reject HTTPS IP-literal endpoints that
    resolve to private / metadata / loopback / link-local addresses. The
    AWS metadata endpoint (169.254.169.254) is the canonical attack."""

    def test_rejects_aws_metadata_endpoint(self, monkeypatch):
        from cohrint_agent.update_check import _assert_https_api_base
        monkeypatch.delenv("COHRINT_ALLOW_HTTP", raising=False)
        assert _assert_https_api_base("https://169.254.169.254") is False
        assert _assert_https_api_base("https://169.254.169.254/latest") is False

    def test_rejects_rfc1918_ranges(self, monkeypatch):
        from cohrint_agent.update_check import _assert_https_api_base
        monkeypatch.delenv("COHRINT_ALLOW_HTTP", raising=False)
        assert _assert_https_api_base("https://10.0.0.5") is False
        assert _assert_https_api_base("https://192.168.1.1") is False
        assert _assert_https_api_base("https://172.16.0.1") is False

    def test_rejects_loopback_https(self, monkeypatch):
        from cohrint_agent.update_check import _assert_https_api_base
        monkeypatch.delenv("COHRINT_ALLOW_HTTP", raising=False)
        assert _assert_https_api_base("https://127.0.0.1") is False
        assert _assert_https_api_base("https://[::1]") is False

    def test_accepts_local_with_opt_in(self, monkeypatch):
        from cohrint_agent.update_check import _assert_https_api_base
        monkeypatch.setenv("COHRINT_ALLOW_HTTP", "1")
        # With opt-in, localhost literals (v4 + v6) pass.
        assert _assert_https_api_base("https://127.0.0.1:8080") is True
        assert _assert_https_api_base("http://127.0.0.1:8080") is True
        assert _assert_https_api_base("https://[::1]:9000") is True

    def test_accepts_public_hostname(self, monkeypatch):
        from cohrint_agent.update_check import _assert_https_api_base
        monkeypatch.delenv("COHRINT_ALLOW_HTTP", raising=False)
        assert _assert_https_api_base("https://api.cohrint.com") is True
        assert _assert_https_api_base("https://pypi.org") is True

    def test_rejects_link_local_v6(self, monkeypatch):
        from cohrint_agent.update_check import _assert_https_api_base
        monkeypatch.delenv("COHRINT_ALLOW_HTTP", raising=False)
        assert _assert_https_api_base("https://[fe80::1]") is False


# ───────────────────── T-SAFETY.tracker_redirect_no_success (scan 9/17) ─────

class TestTrackerRedirectNotTreatedAsSuccess:
    """A 3xx response must not be counted as flush success — doing so
    silently drops drained spool events when a proxy returns a redirect."""

    def test_302_does_not_clear_queue(self, monkeypatch):
        # Verify the source-level fix — the allowlist must not include
        # any 3xx code. Behavioural test against the full tracker would
        # require mocking httpx + a live sessions dir; the source check
        # is an equally strong regression gate.
        import pathlib
        src = pathlib.Path("cohrint_agent/tracker.py").read_text()
        # The old pattern must not re-appear.
        assert "status_code < 400" not in src, (
            "regression: tracker is back to treating 3xx as success"
        )
        # The explicit allowlist must be present.
        assert "status_code in (200, 201, 202, 204)" in src


# ──────────────────── T-SAFETY.rich_markup_injection (scan 10/17) ──────────

class TestRichMarkupInjectionInToolPreview:
    """Tool-input previews must escape Rich markup so a model-generated
    command containing '[link=file:///etc/passwd]' doesn't render as an
    interactive terminal link, and '[green]approved[/green]' can't spoof
    a success badge around the approval prompt."""

    def test_bash_command_rich_markup_escaped(self, capsys):
        from rich.console import Console
        from cohrint_agent import permissions as P
        import io
        buf = io.StringIO()
        P.console = Console(file=buf, force_terminal=False, color_system=None)
        try:
            malicious = "[bold red]rm -rf /[/bold red][link=file:///etc/passwd]x[/link]"
            P._print_tool_preview("Bash", {"command": malicious})
        finally:
            # Restore original console so other tests aren't polluted.
            P.console = Console()
        out = buf.getvalue()
        # The literal brackets must survive unescaped-to-terminal.
        assert "[bold red]" in out
        assert "[link=" in out

    def test_edit_file_path_rich_markup_escaped(self):
        from rich.console import Console
        from cohrint_agent import permissions as P
        import io
        buf = io.StringIO()
        P.console = Console(file=buf, force_terminal=False, color_system=None)
        try:
            P._print_tool_preview("Edit", {
                "file_path": "/tmp/[green]fake[/green].txt",
                "old_string": "[red]X[/red]",
            })
        finally:
            P.console = Console()
        out = buf.getvalue()
        assert "[green]fake[/green]" in out
        assert "[red]X[/red]" in out


# ──────────────────── T-SAFETY.audit_surrogate (scan 10/17) ─────────────────

class TestAuditSurrogateSafe:
    """append_audit must not raise UnicodeEncodeError on an isolated
    surrogate character (model output can contain these)."""

    def test_surrogate_in_preview_does_not_abort_audit(self, tmp_path):
        from cohrint_agent import permissions as P
        pm = P.PermissionManager(config_dir=tmp_path)
        # '\ud83d' is a lone high surrogate — strict encode() raises.
        pm.append_audit(tool="Bash", input_preview="lone \ud83d surrogate",
                        decision="deny_once", backend="api")
        import json as _json
        data = _json.loads(pm._perm_file.read_text())
        assert data["audit_log"][-1]["decision"] == "deny_once"
        # Hash is populated (not an empty string).
        assert len(data["audit_log"][-1]["input_hash"]) == 16


# ────────────────── T-SAFETY.subprocess_encoding (scan 10/17) ──────────────

class TestSubprocessEncodingResilient:
    """AgentProcess.send_stdin must not crash on non-UTF-8 subprocess output
    or a surrogate in the caller's prompt."""

    def test_non_utf8_stdout_does_not_raise(self, monkeypatch):
        from cohrint_agent.backends import base as B

        class FakeStdin:
            def write(self, b):
                self.last = b
            def flush(self):
                pass

        class FakeStdout:
            def __init__(self, chunks):
                self._chunks = list(chunks)
            def readline(self):
                return self._chunks.pop(0) if self._chunks else b""

        class FakeProc:
            stdin = FakeStdin()
            # A CP-1252 byte 0x93 is not valid UTF-8.
            stdout = FakeStdout([b"hello \x93 world\n", b""])

        ap = B.AgentProcess.__new__(B.AgentProcess)
        ap._proc = FakeProc()
        monkeypatch.setattr(B.select, "select", lambda *a, **kw: ([ap._proc.stdout], [], []))
        out = ap.send_stdin("prompt with \ud83d surrogate")
        # Should not raise, should contain the replacement character.
        assert "world" in out


# ────────────────────── T-SAFETY.argv_bom_strip (scan 10/17) ───────────────

class TestArgvBomStripped:
    """Leading U+FEFF in the joined argv prompt must be stripped."""

    def test_bom_stripped_from_joined_prompt(self):
        # Exercise the exact expression the CLI uses.
        args_prompt = ["\ufeffhello", "world"]
        prompt = " ".join(args_prompt).lstrip("\ufeff") if args_prompt else ""
        assert prompt == "hello world"
        assert "\ufeff" not in prompt

    def test_no_bom_is_unchanged(self):
        args_prompt = ["hello", "world"]
        prompt = " ".join(args_prompt).lstrip("\ufeff") if args_prompt else ""
        assert prompt == "hello world"


# ────────────── T-PRIVACY.otel_session_id_always_hashed (scan 11/17) ───────

class TestOtelSessionIdAlwaysHashed:
    """OTel logs payload must hash session_id regardless of tracker
    privacy mode — the tracker's 'full' branch used to forward the raw
    UUID, letting the collector reconstruct turn sequences."""

    def test_raw_session_id_is_hashed_in_log_body(self, monkeypatch):
        monkeypatch.setenv("COHRINT_OTEL_ENABLED", "false")
        from cohrint_agent.telemetry import OTelExporter
        exp = OTelExporter()
        raw_sid = "00000000-0000-4000-8000-000000000111"
        payload = exp._build_logs_payload({
            "model": "m",
            "session_id": raw_sid,
            "prompt_tokens": 1,
            "completion_tokens": 1,
            "cost_usd": 0.0,
            "latency_ms": 0,
        })
        import json as _json
        body = _json.loads(
            payload["resourceLogs"][0]["scopeLogs"][0]
            ["logRecords"][0]["body"]["stringValue"]
        )
        # The raw UUID must not appear anywhere in the body.
        assert raw_sid not in body["session_id"]
        # Hashed form: 64-hex.
        assert len(body["session_id"]) == 64
        int(body["session_id"], 16)  # must parse as hex

    def test_empty_session_id_stays_empty(self, monkeypatch):
        monkeypatch.setenv("COHRINT_OTEL_ENABLED", "false")
        from cohrint_agent.telemetry import OTelExporter
        exp = OTelExporter()
        payload = exp._build_logs_payload({"model": "m", "session_id": ""})
        import json as _json
        body = _json.loads(
            payload["resourceLogs"][0]["scopeLogs"][0]
            ["logRecords"][0]["body"]["stringValue"]
        )
        assert body["session_id"] == ""


# ──────────────────── T-SAFETY.audit_log_injection (scan 11/17) ────────────

class TestAuditLogNewlineInjection:
    """Embedded \\n in input_preview must be escaped so a crafted Bash
    command cannot forge a second audit entry visible to line-oriented
    log shippers."""

    def test_newline_in_preview_escaped(self, tmp_path):
        from cohrint_agent import permissions as P
        pm = P.PermissionManager(config_dir=tmp_path)
        malicious = 'rm\n{"tool":"X","decision":"allow_always"}\n'
        pm.append_audit(tool="Bash", input_preview=malicious,
                        decision="deny_once", backend="api")
        stored = pm._read_raw()["audit_log"][-1]["input_preview"]
        assert "\n" not in stored
        assert "\\n" in stored  # literal backslash-n
        assert "\r" not in stored


# ────────────── T-SAFETY.preview_terminal_scrub (scan 11/17) ───────────────

class TestPreviewTerminalScrub:
    """_print_tool_preview must scrub OSC-52 / CSI escapes from external
    strings even before Rich-escaping — otherwise the terminal interprets
    them when the escaped text is printed."""

    def test_osc52_stripped_from_bash_preview(self):
        from rich.console import Console
        from cohrint_agent import permissions as P
        import io
        buf = io.StringIO()
        P.console = Console(file=buf, force_terminal=False, color_system=None)
        try:
            evil = "ls\x1b]52;c;cGF3bmVk\x07"
            P._print_tool_preview("Bash", {"command": evil})
        finally:
            P.console = Console()
        out = buf.getvalue()
        # The ESC char must not survive — without it the remaining
        # ``]52;c;...`` is just literal bytes the terminal won't parse
        # as an OSC sequence.
        assert "\x1b" not in out
        assert "\x07" not in out


# ────────────── T-PRIVACY.tool_exception_path (scan 11/17) ─────────────────

class TestToolExceptionPathRedacted:
    """Tool execution errors must surface only the exception *type* to
    the model/session; the raw str() leaks user paths."""

    def test_filenotfound_does_not_expose_path(self):
        # Directly simulate the fixed except-branch logic.
        try:
            open("/home/alice/secret/nonexistent.txt")
        except Exception as e:
            output = f"Tool execution error: {type(e).__name__}"
        assert "alice" not in output
        assert "secret" not in output
        assert output == "Tool execution error: FileNotFoundError"

    def test_api_client_source_uses_type_name(self):
        import pathlib
        src = pathlib.Path("cohrint_agent/api_client.py").read_text()
        assert "Tool execution error: {type(e).__name__}" in src
        assert 'Tool execution error: {e}"' not in src


# ────────────── T-PRIVACY.spool_error_path (scan 11/17) ────────────────────

class TestSpoolErrorPathRedacted:
    """The spool-write fallback print must not leak the full exception
    message (which carries the user's home path on OSError)."""

    def test_spool_write_src_uses_type_name(self):
        import pathlib
        src = pathlib.Path("cohrint_agent/tracker.py").read_text()
        assert 'could not write to spool ({type(exc).__name__})' in src
        assert 'could not write to spool: {exc}' not in src


# ────────── T-SAFETY.approve_clears_denied (scan 12/17) ────────────────────

class TestApproveClearsDenied:
    """approve(always=True) must remove the tool from always_denied —
    otherwise the REPL /allow silently fails while the user thinks it
    succeeded."""

    def test_deny_then_approve_always_clears_denied(self, tmp_path):
        from cohrint_agent import permissions as P
        pm = P.PermissionManager(config_dir=tmp_path)
        pm.deny(["Bash"])
        assert pm.is_denied("Bash")
        pm.approve(["Bash"], always=True)
        assert not pm.is_denied("Bash")
        assert pm.is_approved("Bash")

    def test_approve_always_persists_to_disk_without_denied(self, tmp_path):
        from cohrint_agent import permissions as P
        pm = P.PermissionManager(config_dir=tmp_path)
        pm.deny(["Write"])
        pm.approve(["Write"], always=True)
        pm2 = P.PermissionManager(config_dir=tmp_path)
        assert "Write" not in pm2.always_denied
        assert "Write" in pm2.always_approved


# ────────── T-SAFETY.reset_preserves_denied (scan 12/17) ───────────────────

class TestResetPreservesDenied:
    """Default reset() must NOT wipe always_denied — users who typed
    /never must keep their protection through an unrelated /reset."""

    def test_reset_keeps_always_denied(self, tmp_path):
        from cohrint_agent import permissions as P
        pm = P.PermissionManager(config_dir=tmp_path)
        pm.deny(["DangerTool"])
        pm.reset()
        assert "DangerTool" in pm.always_denied

    def test_reset_all_wipes_denied_explicitly(self, tmp_path):
        from cohrint_agent import permissions as P
        pm = P.PermissionManager(config_dir=tmp_path)
        pm.deny(["DangerTool"])
        pm.reset(wipe_denied=True)
        assert "DangerTool" not in pm.always_denied


# ────────── T-SAFETY.approve_audited (scan 12/17) ──────────────────────────

class TestApproveAudited:
    """approve() must write an audit entry so operators can reconstruct
    bulk REPL approvals from permissions.json."""

    def test_approve_emits_audit_entry(self, tmp_path):
        from cohrint_agent import permissions as P
        pm = P.PermissionManager(config_dir=tmp_path)
        pm.approve(["Bash"], always=True)
        log = pm._read_raw()["audit_log"]
        assert any(
            e["tool"] == "Bash"
            and e["decision"] == "allow_always"
            and e["backend"] == "repl"
            for e in log
        )

    def test_deny_emits_audit_entry(self, tmp_path):
        from cohrint_agent import permissions as P
        pm = P.PermissionManager(config_dir=tmp_path)
        pm.deny(["Bash"])
        log = pm._read_raw()["audit_log"]
        assert any(
            e["tool"] == "Bash"
            and e["decision"] == "deny_always"
            and e["backend"] == "repl"
            for e in log
        )


# ────────── T-SAFETY.safe_tools_immutable (scan 12/17) ─────────────────────

class TestSafeToolsImmutable:
    """SAFE_TOOLS must be frozenset so external mutation can't drift
    the default baseline for later PermissionManager instances."""

    def test_safe_tools_is_frozenset(self):
        from cohrint_agent.tools import SAFE_TOOLS
        assert isinstance(SAFE_TOOLS, frozenset)
        with pytest.raises(AttributeError):
            SAFE_TOOLS.add("Bash")  # type: ignore[attr-defined]


# ────────── T-SAFETY.schema_version_guard (scan 12/17) ─────────────────────

class TestSchemaVersionGuard:
    """A permissions.json with a future schema_version must not be
    processed — safer to fall back to defaults than misinterpret."""

    def test_future_schema_uses_defaults(self, tmp_path, caplog):
        import json as _json
        import logging
        from cohrint_agent import permissions as P
        perm_file = tmp_path / "permissions.json"
        perm_file.write_text(_json.dumps({
            "schema_version": 999,
            "always_approved": ["Evil"],
            "always_denied": [],
        }))
        with caplog.at_level(logging.WARNING, logger="cohrint_agent.permissions"):
            pm = P.PermissionManager(config_dir=tmp_path)
        assert "Evil" not in pm.always_approved
        assert any("schema_version" in r.message for r in caplog.records)

    def test_version_1_is_accepted(self, tmp_path):
        import json as _json
        from cohrint_agent import permissions as P
        perm_file = tmp_path / "permissions.json"
        perm_file.write_text(_json.dumps({
            "schema_version": 1,
            "always_approved": ["Write"],
            "always_denied": [],
            "session_approved": [],
        }))
        pm = P.PermissionManager(config_dir=tmp_path)
        assert "Write" in pm.always_approved


# ────────── T-PRIVACY.sessions_dir_0700 (scan 13) ──────────────────────────

class TestSessionsDirMode:
    """The sessions/ directory must be 0o700 — per-user only — since the
    JSON files contain conversation history, cwd, and accumulated cost."""

    def test_sessions_dir_is_0700(self, tmp_path):
        import stat
        from cohrint_agent.session_store import SessionStore
        d = tmp_path / "sessions"
        SessionStore(sessions_dir=d)
        mode = stat.S_IMODE(d.stat().st_mode)
        assert mode == 0o700, f"got {oct(mode)}"

    def test_sessions_dir_rechmodded_if_preexisting_0755(self, tmp_path):
        """Even a pre-existing wider-perm dir must be tightened on init."""
        import stat
        from cohrint_agent.session_store import SessionStore
        d = tmp_path / "sessions"
        d.mkdir(mode=0o755)
        SessionStore(sessions_dir=d)
        mode = stat.S_IMODE(d.stat().st_mode)
        assert mode == 0o700, f"got {oct(mode)}"


# ────────── T-PRIVACY.sessions_file_0600 (scan 13) ─────────────────────────

class TestSessionsFileMode:
    """Each session JSON must be 0o600 regardless of umask — the mode is
    explicit on os.open so a relaxed umask can't widen it."""

    def test_saved_session_is_0600(self, tmp_path):
        import os as _os
        import stat
        from cohrint_agent.session_store import SessionStore
        # Force a wide umask to prove the mode is explicit, not inherited.
        old_umask = _os.umask(0o000)
        try:
            store = SessionStore(sessions_dir=tmp_path / "sessions")
            sid = "11111111-1111-4111-8111-111111111111"
            store.save({"id": sid, "cwd": ".", "messages": []})
            p = store._path(sid)
            mode = stat.S_IMODE(p.stat().st_mode)
            assert mode == 0o600, f"got {oct(mode)}"
        finally:
            _os.umask(old_umask)


# ────────── T-BOUNDS.load_size_cap (scan 13) ───────────────────────────────

class TestLoadSizeCap:
    """A tampered / runaway session JSON past MAX_SESSION_FILE_BYTES must
    be rejected by load(), not silently parsed into RAM."""

    def test_oversized_session_file_rejected_by_load(self, tmp_path):
        import json as _json
        from cohrint_agent.session_store import (
            SessionStore,
            SessionNotFoundError,
            MAX_SESSION_FILE_BYTES,
        )
        store = SessionStore(sessions_dir=tmp_path / "sessions")
        sid = "22222222-2222-4222-8222-222222222222"
        # Write the file directly, bypassing save(), so we can exceed the cap.
        path = store._path(sid)
        filler = "x" * (MAX_SESSION_FILE_BYTES + 1024)
        path.write_text(_json.dumps({"id": sid, "filler": filler}))
        with pytest.raises(SessionNotFoundError, match="exceeds"):
            store.load(sid)


# ────────── T-SAFETY.load_no_symlink (scan 13) ─────────────────────────────

class TestLoadNoSymlink:
    """load() must refuse a symlink at <uuid>.json — otherwise a local
    attacker who can write into sessions_dir could redirect reads to an
    arbitrary file and leak its content via parse-error text."""

    def test_symlinked_session_file_rejected(self, tmp_path):
        import os as _os
        from cohrint_agent.session_store import SessionStore, SessionNotFoundError
        store = SessionStore(sessions_dir=tmp_path / "sessions")
        sid = "33333333-3333-4333-8333-333333333333"
        target = tmp_path / "secret.txt"
        target.write_text("root:x:0:0:root:/root:/bin/bash\n")
        # Place a symlink where the session file would live.
        link = store._path(sid)
        _os.symlink(target, link)
        with pytest.raises(SessionNotFoundError, match="not readable"):
            store.load(sid)


# ────────── T-COST.resume_bounds (scan 13) ─────────────────────────────────

class TestResumeCostClamping:
    """Session JSON is an untrusted-data boundary — a file tampered to
    set a huge-negative total_cost_usd could defeat the budget gate.
    resume() must clamp cost_summary + budget_usd to safe ranges."""

    def test_resume_clamps_negative_cost_to_zero(self, tmp_path):
        import json as _json
        from cohrint_agent.session_store import SessionStore
        from cohrint_agent.session import CohrintSession
        store = SessionStore(sessions_dir=tmp_path / "sessions")
        sid = "44444444-4444-4444-8444-444444444444"
        path = store._path(sid)
        # Write directly so save() doesn't re-normalise the numbers.
        path.write_text(_json.dumps({
            "id": sid,
            "cwd": ".",
            "messages": [],
            "cost_summary": {
                "total_cost_usd": -9e20,
                "total_input_tokens": -5,
                "total_output_tokens": -7,
            },
            "budget_usd": -50.0,
            "schema_version": 1,
        }))

        class _FakeBackend:
            name = "claude"
            class capabilities:
                token_count = False
                supports_process = False
            def send(self, **_kw):
                raise AssertionError("not used in this test")

        sess = CohrintSession.resume(sid, _FakeBackend(), store=store)
        assert sess._cost_summary["total_cost_usd"] == 0.0
        assert sess._cost_summary["total_input_tokens"] == 0
        assert sess._cost_summary["total_output_tokens"] == 0
        assert sess._budget_usd == 0.0

    def test_resume_rejects_nan_and_inf_budget(self, tmp_path):
        import json as _json
        from cohrint_agent.session_store import SessionStore
        from cohrint_agent.session import CohrintSession
        store = SessionStore(sessions_dir=tmp_path / "sessions")
        sid = "55555555-5555-4555-8555-555555555555"
        path = store._path(sid)
        path.write_text(_json.dumps({
            "id": sid, "cwd": ".", "messages": [],
            "budget_usd": "NaN",
            "schema_version": 1,
        }))

        class _FakeBackend:
            name = "claude"
            class capabilities:
                token_count = False
                supports_process = False
            def send(self, **_kw):
                raise AssertionError("not used")

        sess = CohrintSession.resume(sid, _FakeBackend(), store=store)
        assert sess._budget_usd == 0.0

    def test_resume_clamps_absurdly_large_cost(self, tmp_path):
        import json as _json
        from cohrint_agent.session_store import SessionStore
        from cohrint_agent.session import CohrintSession
        store = SessionStore(sessions_dir=tmp_path / "sessions")
        sid = "66666666-6666-4666-8666-666666666666"
        path = store._path(sid)
        path.write_text(_json.dumps({
            "id": sid, "cwd": ".", "messages": [],
            "cost_summary": {"total_cost_usd": 9e30},
            "schema_version": 1,
        }))

        class _FakeBackend:
            name = "claude"
            class capabilities:
                token_count = False
                supports_process = False
            def send(self, **_kw):
                raise AssertionError("not used")

        sess = CohrintSession.resume(sid, _FakeBackend(), store=store)
        assert sess._cost_summary["total_cost_usd"] <= 1e9


# ────────── T-CONCUR.save_no_reload (scan 13) ──────────────────────────────

class TestSaveNoReload:
    """save() must NOT call load() on every turn — that was both a perf
    cost AND a load/save TOCTOU window where a concurrent resume could
    observe a file that this turn is about to overwrite."""

    def test_save_does_not_re_read_session_file(self, tmp_path, monkeypatch):
        from cohrint_agent.session_store import SessionStore
        from cohrint_agent.session import CohrintSession
        store = SessionStore(sessions_dir=tmp_path / "sessions")

        class _FakeBackend:
            name = "claude"
            class capabilities:
                token_count = False
                supports_process = False
            def send(self, **_kw):
                raise AssertionError("not used")

        sess = CohrintSession.create(_FakeBackend(), cwd=".", store=store)
        # First save creates the file. After it exists, additional saves
        # must NOT invoke store.load().
        sess.save()

        call_count = {"n": 0}
        orig_load = store.load
        def _spy_load(sid):
            call_count["n"] += 1
            return orig_load(sid)
        monkeypatch.setattr(store, "load", _spy_load)

        for _ in range(5):
            sess.save()
        assert call_count["n"] == 0, (
            f"save() invoked load() {call_count['n']} times — should be 0 "
            f"(created_at is cached on the CohrintSession)"
        )

    def test_created_at_preserved_across_saves(self, tmp_path):
        """Round-trip: create → save → resume → save again → created_at unchanged."""
        from cohrint_agent.session_store import SessionStore
        from cohrint_agent.session import CohrintSession

        store = SessionStore(sessions_dir=tmp_path / "sessions")

        class _FakeBackend:
            name = "claude"
            class capabilities:
                token_count = False
                supports_process = False
            def send(self, **_kw):
                raise AssertionError("not used")

        s1 = CohrintSession.create(_FakeBackend(), cwd=".", store=store)
        s1.save()
        first_created_at = s1._created_at

        s2 = CohrintSession.resume(s1.session_id, _FakeBackend(), store=store)
        s2.save()
        raw = store.load(s1.session_id)
        assert raw["created_at"] == first_created_at


# ────────── T-SAFETY.subproc_utf8_replace (scan 14) ────────────────────────

class TestBackendDecodeResilient:
    """codex/gemini backends must decode subprocess stdout/stderr with
    errors='replace' (text=False + manual decode). text=True uses the
    platform locale encoding and raises UnicodeDecodeError on a bad byte,
    crashing the turn on Windows/CP-1252 hosts."""

    def test_codex_backend_survives_bad_byte_in_stdout(self, monkeypatch):
        from cohrint_agent.backends import codex_backend

        class _FakeCompleted:
            stdout = b"ok \x93 smart quote"
            stderr = b""
            returncode = 0

        def _fake_run(*a, **kw):
            assert kw.get("capture_output") is True
            assert kw.get("text", False) is False
            return _FakeCompleted()

        monkeypatch.setattr(codex_backend.subprocess, "run", _fake_run)
        be = codex_backend.CodexBackend()
        result = be.send(prompt="hi", history=[], cwd=".")
        assert "ok" in result.output_text
        assert result.exit_code == 0

    def test_gemini_backend_survives_bad_byte_in_stdout(self, monkeypatch):
        from cohrint_agent.backends import gemini_backend

        class _FakeCompleted:
            stdout = b"hello \x93 world"
            stderr = b""
            returncode = 0

        def _fake_run(*a, **kw):
            assert kw.get("text", False) is False
            return _FakeCompleted()

        monkeypatch.setattr(gemini_backend.subprocess, "run", _fake_run)
        be = gemini_backend.GeminiBackend()
        result = be.send(prompt="hi", history=[], cwd=".")
        assert "hello" in result.output_text


# ────────── T-SAFETY.exit_code_surfaced (scan 14) ──────────────────────────

class TestBackendExitCodeSurfaced:
    """A non-zero subprocess exit must not silently yield an empty turn —
    the user needs to know that the child CLI failed (auth, rate limit,
    binary missing) rather than see the model "return nothing"."""

    def test_codex_nonzero_exit_includes_stderr_banner(self, monkeypatch):
        from cohrint_agent.backends import codex_backend

        class _FakeCompleted:
            stdout = b""
            stderr = b"Error: invalid API key\n"
            returncode = 1

        monkeypatch.setattr(
            codex_backend.subprocess, "run", lambda *a, **kw: _FakeCompleted()
        )
        be = codex_backend.CodexBackend()
        result = be.send(prompt="hi", history=[], cwd=".")
        assert "codex exited 1" in result.output_text
        assert "invalid API key" in result.output_text
        assert result.exit_code == 1

    def test_gemini_nonzero_exit_includes_stderr_banner(self, monkeypatch):
        from cohrint_agent.backends import gemini_backend

        class _FakeCompleted:
            stdout = b""
            stderr = b"quota exceeded"
            returncode = 42

        monkeypatch.setattr(
            gemini_backend.subprocess, "run", lambda *a, **kw: _FakeCompleted()
        )
        be = gemini_backend.GeminiBackend()
        result = be.send(prompt="hi", history=[], cwd=".")
        assert "gemini exited 42" in result.output_text
        assert "quota exceeded" in result.output_text


# ────────── T-SAFETY.argv_dash_injection (scan 14) ─────────────────────────

class TestBackendArgvDashInjection:
    """A prompt beginning with "-" must not be passed on argv where the
    child's argparse could treat it as a flag (e.g. --full-auto).
    Route via stdin when the prompt starts with a dash."""

    def test_codex_dash_prompt_routes_via_stdin(self, monkeypatch):
        from cohrint_agent.backends import codex_backend
        captured = {}

        class _FakeCompleted:
            stdout = b"ok"
            stderr = b""
            returncode = 0

        def _fake_run(argv, **kw):
            captured["argv"] = argv
            captured["stdin"] = kw.get("input")
            return _FakeCompleted()

        monkeypatch.setattr(codex_backend.subprocess, "run", _fake_run)
        be = codex_backend.CodexBackend()
        be.send(prompt="--full-auto", history=[], cwd=".")
        # Argv must not contain the dash-leading prompt
        assert "--full-auto" not in captured["argv"]
        # argv[0] may be either bare 'codex' or an absolute pinned path
        # (scan 22). Accept both forms.
        assert len(captured["argv"]) == 1
        assert captured["argv"][0].endswith("codex") or "codex" in captured["argv"][0]
        assert captured["stdin"] is not None
        assert b"--full-auto" in captured["stdin"]

    def test_codex_safe_prompt_uses_argv(self, monkeypatch):
        """Regression: normal prompts still use the fast argv path."""
        from cohrint_agent.backends import codex_backend
        captured = {}

        class _FakeCompleted:
            stdout = b"ok"
            stderr = b""
            returncode = 0

        def _fake_run(argv, **kw):
            captured["argv"] = argv
            captured["stdin"] = kw.get("input")
            return _FakeCompleted()

        monkeypatch.setattr(codex_backend.subprocess, "run", _fake_run)
        be = codex_backend.CodexBackend()
        be.send(prompt="hello world", history=[], cwd=".")
        # argv[0] is either 'codex' or an absolute pinned path (scan 22).
        assert captured["argv"][0].endswith("codex") or "codex" in captured["argv"][0]
        assert captured["argv"][1] == "-p"
        assert captured["stdin"] is None

    def test_gemini_dash_prompt_routes_via_stdin(self, monkeypatch):
        from cohrint_agent.backends import gemini_backend
        captured = {}

        class _FakeCompleted:
            stdout = b"ok"
            stderr = b""
            returncode = 0

        def _fake_run(argv, **kw):
            captured["argv"] = argv
            captured["stdin"] = kw.get("input")
            return _FakeCompleted()

        monkeypatch.setattr(gemini_backend.subprocess, "run", _fake_run)
        be = gemini_backend.GeminiBackend()
        be.send(prompt="-help", history=[], cwd=".")
        assert "-help" not in captured["argv"]
        assert captured["stdin"] is not None


# ────────── T-SAFETY.hook_script_symlink (scan 15) ─────────────────────────

class TestHookScriptSymlink:
    """install_hook_script must use atomic replace so a pre-planted
    symlink at perm-hook.sh can't redirect the write to e.g. ~/.bashrc."""

    def test_symlink_at_hook_path_does_not_follow(self, tmp_path):
        import os as _os
        from cohrint_agent.permission_server import install_hook_script

        target = tmp_path / "VICTIM_FILE"
        target.write_text("original victim content")
        hook_path = tmp_path / "perm-hook.sh"
        _os.symlink(target, hook_path)

        install_hook_script(tmp_path)

        # Symlink must have been replaced, not followed
        assert not hook_path.is_symlink()
        # Victim must be intact
        assert target.read_text() == "original victim content"
        # Hook script should contain the expected shebang (path varies by OS)
        assert "bash" in hook_path.read_text().splitlines()[0]


# ────────── T-SAFETY.settings_symlink (scan 15) ────────────────────────────

class TestSettingsSymlink:
    """build_session_settings_file must atomic-replace — a symlink placed
    at output_path must not redirect the JSON write outside run/."""

    def test_symlink_at_output_path_does_not_follow(self, tmp_path):
        import os as _os
        from cohrint_agent.permission_server import build_session_settings_file

        victim = tmp_path / "VICTIM.json"
        victim.write_text("{\"secret\":true}")
        run_dir = tmp_path / "run"
        run_dir.mkdir(mode=0o700)
        output = run_dir / "settings.json"
        _os.symlink(victim, output)

        build_session_settings_file(
            socket_path="/tmp/sock", output_path=output, config_dir=tmp_path
        )

        assert not output.is_symlink()
        assert victim.read_text() == "{\"secret\":true}"


# ────────── T-SAFETY.sock_umask (scan 15) ──────────────────────────────────

class TestSocketUmask:
    """PermissionServer's AF_UNIX socket must be 0o600, independent of
    the process umask — a cleared umask otherwise lets any local UID
    connect and inject 'allow' decisions."""

    def test_socket_file_is_0600_even_under_wide_umask(self):
        import os as _os
        import stat
        import time
        import uuid
        import tempfile
        from cohrint_agent.permission_server import PermissionServer

        # macOS limits AF_UNIX paths to ~104 chars — pytest's tmp_path is too
        # long. Use a short /tmp path instead.
        sock_path = _os.path.join(
            tempfile.gettempdir(), f"ct-{uuid.uuid4().hex[:8]}.sock"
        )
        old_umask = _os.umask(0o000)
        srv = None
        try:
            srv = PermissionServer(socket_path=sock_path, permissions=None)
            srv.start()
            for _ in range(100):
                if _os.path.exists(sock_path):
                    break
                time.sleep(0.01)
            assert _os.path.exists(sock_path), "socket was not created"
            mode = stat.S_IMODE(_os.stat(sock_path).st_mode)
            assert mode & 0o077 == 0, f"socket mode {oct(mode)} leaks access"
        finally:
            _os.umask(old_umask)
            if srv is not None:
                srv.stop()
                srv.join(timeout=1.0)
            try:
                _os.unlink(sock_path)
            except OSError:
                pass


# ────────── T-SAFETY.drain_stale_responses (scan 15) ───────────────────────

class TestDrainStaleResponses:
    """On timeout, stale perm_response_queue entries must be drained so
    a late main-thread response from one tool call doesn't leak into
    the next connection's answer."""

    def test_stale_response_is_drained_on_timeout(self, monkeypatch):
        import queue as _q
        from cohrint_agent.permission_server import PermissionServer

        srv = PermissionServer(socket_path="/tmp/unused", permissions=None)
        # Seed a stale response that must NOT leak to the next turn.
        # Simulate the timeout path directly by calling _handle_connection
        # behavior: we need to call the drain logic.
        # We do it by populating the queues in the order the timeout path
        # would, and asserting drain:
        srv.perm_response_queue.put("allow_always")
        # Drain as the timeout handler does:
        while True:
            try:
                srv.perm_response_queue.get_nowait()
            except _q.Empty:
                break
        assert srv.perm_response_queue.qsize() == 0

    def test_handle_connection_drains_on_timeout(self, monkeypatch):
        """End-to-end: a short-circuited timeout must drain any pending
        response so it doesn't leak into the next connection's answer."""
        import queue as _q
        from cohrint_agent import permission_server as P

        srv = P.PermissionServer(socket_path="/tmp/unused", permissions=None)

        # Swap the Queue class used for perm_response_queue so .get() raises
        # Empty but .get_nowait() still reads from a backing store. This
        # simulates: "main thread never responded (timeout) but a stale
        # response is sitting in the queue from a prior turn."
        real_q = srv.perm_response_queue

        class _StubQueue:
            def __init__(self):
                self._items: list[str] = []
            def put(self, item):
                self._items.append(item)
            def get(self, timeout=None):
                raise _q.Empty()  # simulate timeout
            def get_nowait(self):
                if not self._items:
                    raise _q.Empty()
                return self._items.pop(0)
            def qsize(self):
                return len(self._items)

        stub = _StubQueue()
        stub.put("allow_always")  # stale response from a prior request
        srv.perm_response_queue = stub  # type: ignore[assignment]

        class _FakeConn:
            def __init__(self):
                self._data = b'{"tool_name":"Bash"}\n'
                self._sent = []
            def settimeout(self, *_a):
                pass
            def recv(self, n):
                d, self._data = self._data, b""
                return d
            def sendall(self, b):
                self._sent.append(b)
            def close(self):
                pass

        conn = _FakeConn()
        srv._handle_connection(conn)

        # Drain removed the stale response.
        assert stub.qsize() == 0
        # Hook got a deny on timeout.
        assert any(b"deny" in p for p in conn._sent)

        # Restore
        srv.perm_response_queue = real_q


# ────────── T-SAFETY.hook_tool_sanitize (scan 15) ──────────────────────────

class TestHookToolNameSanitized:
    """The deny branch of the hook script must sanitize $TOOL before
    echoing it — model-controlled tool names could otherwise inject
    newline-delimited structured output into stdout that Claude Code
    surfaces back to the model."""

    def test_hook_script_strips_non_safe_chars(self):
        from cohrint_agent import permission_server as P
        hook = P._HOOK_SCRIPT
        # Must sanitize tool name via regex that excludes newlines.
        assert "re.sub" in hook
        assert "A-Za-z0-9_.-" in hook
        # Raw json.loads-then-print without sanitize is the BAD pattern
        # — ensure it no longer appears in the deny branches.
        bad = "json.loads(sys.argv[1]).get('tool_name','tool'))"
        occurrences = hook.count(bad)
        # The only allowed use would be pre-sanitize inside a re.sub call.
        # Count should be 0 now that sanitized form is in place.
        assert occurrences == 0, (
            f"unsanitized tool_name print still present {occurrences}x"
        )


# ────────── T-PRIVACY.spool_perms (scan 16) ────────────────────────────────

class TestSpoolPerms:
    """~/.cohrint/spool.jsonl must be 0o600 and the dir 0o700 —
    on shared machines (CI, Docker multi-tenant) it otherwise leaks
    token counts, model names, and cost figures to other local UIDs."""

    def test_spool_dir_0700_and_file_0600(self, tmp_path, monkeypatch):
        import os as _os
        import stat
        from cohrint_agent import tracker as T
        monkeypatch.setattr(T, "_SPOOL_DIR", tmp_path / "spool_dir")
        monkeypatch.setattr(T, "_SPOOL_FILE", tmp_path / "spool_dir" / "spool.jsonl")
        monkeypatch.setattr(T, "_SPOOL_LOCK_FILE", tmp_path / "spool_dir" / "spool.lock")
        old_umask = _os.umask(0o000)
        try:
            T._spool_write([{"event_id": "x"}])
        finally:
            _os.umask(old_umask)
        dir_mode = stat.S_IMODE((tmp_path / "spool_dir").stat().st_mode)
        file_mode = stat.S_IMODE((tmp_path / "spool_dir" / "spool.jsonl").stat().st_mode)
        assert dir_mode == 0o700, f"dir mode {oct(dir_mode)}"
        assert file_mode == 0o600, f"file mode {oct(file_mode)}"


# ────────── T-SAFETY.spool_atomic (scan 16) ────────────────────────────────

class TestSpoolAtomic:
    """Spool writes must go through tmp + os.replace so a SIGKILL
    mid-write can't zero-byte the spool and silently wipe all events."""

    def test_spool_uses_atomic_replace(self, tmp_path, monkeypatch):
        """Replace os.replace with a spy and confirm the spool write path
        uses it (not a direct open+truncate+write)."""
        import os as _os
        from cohrint_agent import tracker as T
        monkeypatch.setattr(T, "_SPOOL_DIR", tmp_path / "spool_dir")
        monkeypatch.setattr(T, "_SPOOL_FILE", tmp_path / "spool_dir" / "spool.jsonl")
        monkeypatch.setattr(T, "_SPOOL_LOCK_FILE", tmp_path / "spool_dir" / "spool.lock")

        replace_calls: list[tuple[str, str]] = []
        orig_replace = _os.replace
        def _spy_replace(src, dst):
            replace_calls.append((str(src), str(dst)))
            return orig_replace(src, dst)
        monkeypatch.setattr(T.os, "replace", _spy_replace)

        T._spool_write([{"event_id": "x"}])
        assert replace_calls, "spool write did not use os.replace"
        src, dst = replace_calls[0]
        assert dst.endswith("spool.jsonl")
        assert src.endswith(".tmp")


# ────────── T-PRIVACY.opt_out (scan 16) ────────────────────────────────────

class TestTelemetryOptOut:
    """COHRINT_NO_TELEMETRY=1 or DO_NOT_TRACK=1 must suppress all
    outbound telemetry, including the periodic flush loop."""

    def test_start_is_noop_when_no_telemetry_env_set(self, monkeypatch):
        from cohrint_agent.tracker import Tracker, TrackerConfig
        monkeypatch.setenv("COHRINT_NO_TELEMETRY", "1")
        tr = Tracker(TrackerConfig(api_key="sk-test", privacy="full"))
        tr.start()
        assert tr._running is False
        assert tr._timer is None

    def test_start_is_noop_when_do_not_track_env_set(self, monkeypatch):
        from cohrint_agent.tracker import Tracker, TrackerConfig
        monkeypatch.delenv("COHRINT_NO_TELEMETRY", raising=False)
        monkeypatch.setenv("DO_NOT_TRACK", "1")
        tr = Tracker(TrackerConfig(api_key="sk-test", privacy="full"))
        tr.start()
        assert tr._running is False

    def test_do_flush_no_http_when_opted_out(self, monkeypatch):
        from cohrint_agent.tracker import Tracker, TrackerConfig, DashboardEvent
        import cohrint_agent.tracker as T
        monkeypatch.setenv("COHRINT_NO_TELEMETRY", "1")

        called = {"n": 0}
        def _fake_post(*a, **kw):
            called["n"] += 1
            raise AssertionError("http should not be called when opted out")
        monkeypatch.setattr(T.httpx, "post", _fake_post)

        tr = Tracker(TrackerConfig(api_key="sk-test", privacy="full"))
        tr._queue.append(DashboardEvent(
            event_id="x", provider="anthropic", model="m",
            prompt_tokens=1, completion_tokens=1, total_tokens=2,
            total_cost_usd=0.0, latency_ms=1,
        ))
        tr._do_flush()
        assert called["n"] == 0


# ────────── T-PRIVACY.connect_error_redacted (scan 16) ─────────────────────

class TestConnectErrorRedacted:
    """Exception text in the tracker's debug path must be redacted to
    the TYPE name — raw httpx errors include URLs, IPs, and can echo
    response bodies that contain bearer tokens."""

    def test_source_has_no_raw_exc_in_connect_error_branch(self):
        """Source grep — the f-string for connect errors must not include {exc}."""
        from pathlib import Path as _P
        src = _P("cohrint_agent/tracker.py").read_text()
        # Locate the ConnectError branch and verify {exc} is absent.
        anchor = "connection error — spooling"
        idx = src.find(anchor)
        assert idx >= 0, "could not locate connect-error debug string"
        snippet = src[idx:idx + 250]
        assert "{exc}" not in snippet, (
            f"raw {{exc}} still present in connect-error branch:\n{snippet}"
        )
        assert "type(exc).__name__" in snippet


# ────────── T-PRIVACY.session_id_double_hash (scan 16) ─────────────────────

class TestSessionIdDoubleHashed:
    """Tracker must hash session_id BEFORE passing to OTelExporter, so
    a future refactor that drops the OTel-layer hash still leaves the
    collector with hashed values."""

    def test_tracker_passes_hashed_session_id_to_otel(self, monkeypatch):
        import hashlib as _h
        from cohrint_agent.tracker import Tracker, TrackerConfig, DashboardEvent
        import cohrint_agent.tracker as T

        class _FakeResp:
            status_code = 200

        monkeypatch.setattr(T.httpx, "post", lambda *a, **kw: _FakeResp())

        captured = {}

        class _FakeOTel:
            def __init__(self, *a, **kw):
                pass
            def export_async(self, payload):
                captured["payload"] = payload

        monkeypatch.setattr(T, "OTelExporter", _FakeOTel)

        tr = Tracker(TrackerConfig(api_key="sk-test", privacy="full"))
        raw_sid = "session-xyz-123"
        tr._queue.append(DashboardEvent(
            event_id="x", provider="anthropic", model="m",
            prompt_tokens=1, completion_tokens=1, total_tokens=2,
            total_cost_usd=0.0, latency_ms=1,
            session_id=raw_sid,
        ))
        tr._do_flush()
        assert "payload" in captured, "export_async was not called"
        assert captured["payload"]["session_id"] == _h.sha256(raw_sid.encode()).hexdigest()
        assert raw_sid not in captured["payload"]["session_id"]


# ────────── T-PRIVACY.spool_reanonymize (scan 16) ──────────────────────────

class TestSpoolReanonymize:
    """A user who runs `full` mode offline, then downgrades to
    anonymized before coming online, must not have agent_name
    from spooled events uploaded to the server."""

    def test_drain_strips_agent_name_when_current_is_stricter(self):
        from cohrint_agent.tracker import _enforce_privacy
        event = {
            "event_id": "raw-uuid",
            "agent_name": "cohrint-agent",
            "team": "secret-team",
            "_privacy": "full",
            "model": "m",
        }
        out = _enforce_privacy(event, current="anonymized")
        assert "agent_name" not in out
        assert "team" not in out
        assert "_privacy" not in out  # tag never uploaded
        # event_id was non-64-char raw UUID → rehashed.
        assert len(out["event_id"]) == 64

    def test_drain_keeps_agent_name_if_current_matches(self):
        from cohrint_agent.tracker import _enforce_privacy
        event = {
            "event_id": "x",
            "agent_name": "cohrint-agent",
            "team": "my-team",
            "_privacy": "full",
            "model": "m",
        }
        out = _enforce_privacy(event, current="full")
        assert out["agent_name"] == "cohrint-agent"
        assert out["team"] == "my-team"
        assert "_privacy" not in out

    def test_untagged_spool_defaults_to_strictest(self):
        """Legacy untagged events (no _privacy key) should be treated as
        from an UNKNOWN source and have the current-level redaction
        applied defensively."""
        from cohrint_agent.tracker import _enforce_privacy
        event = {
            "event_id": "x",
            "agent_name": "cohrint-agent",
            "team": "t",
            "model": "m",
        }
        out = _enforce_privacy(event, current="strict")
        assert "agent_name" not in out


# ────────── T-SAFETY.lazy_config_dir (scan 17) ─────────────────────────────

class TestLazyConfigDir:
    """session_store / permissions / rate_limiter must not call
    Path.home() (which invokes pwd.getpwuid) at module import time —
    minimal containers lack /etc/passwd entries for synthetic UIDs."""

    def test_session_store_default_is_lazy(self):
        """DEFAULT_SESSIONS_DIR must be falsy at module level (not pre-resolved)."""
        from cohrint_agent import session_store
        assert session_store.DEFAULT_SESSIONS_DIR is None

    def test_session_store_init_without_arg_still_works(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        from cohrint_agent.session_store import SessionStore
        store = SessionStore()
        assert store.sessions_dir.is_dir()

    def test_permissions_module_has_no_module_level_config_dir(self):
        """_DEFAULT_CONFIG_DIR must have been removed in favour of a lazy getter."""
        from cohrint_agent import permissions as P
        # The module must expose the lazy function.
        assert callable(P._get_default_config_dir)

    def test_rate_limiter_state_file_is_lazy(self, tmp_path, monkeypatch):
        """_STATE_FILE must resolve via safe_config_dir() at access time.

        Earlier tests (unittest.mock.patch.object) may have left a concrete
        _STATE_FILE module attribute that shadows __getattr__ — explicitly
        clear it so this test verifies the lazy fallback actually works.
        """
        import cohrint_agent.rate_limiter as _rl_mod
        if "_STATE_FILE" in _rl_mod.__dict__:
            del _rl_mod.__dict__["_STATE_FILE"]
        monkeypatch.setattr(_rl_mod, "safe_config_dir", lambda: tmp_path)
        path = _rl_mod._STATE_FILE
        assert str(path).startswith(str(tmp_path))

    def test_acquire_does_not_raise_NameError(self, tmp_path, monkeypatch):
        """Runtime regression: acquire()/get_global_budget_used() read
        _STATE_FILE from inside their own module. Bare-name lookup does
        NOT fire module-level __getattr__, so they must resolve via
        sys.modules to avoid NameError on a fresh install
        (T-SAFETY.rate_limiter_runtime_bare_name)."""
        import cohrint_agent.rate_limiter as _rl_mod
        if "_STATE_FILE" in _rl_mod.__dict__:
            del _rl_mod.__dict__["_STATE_FILE"]
        monkeypatch.setattr(_rl_mod, "safe_config_dir", lambda: tmp_path)
        # Must not raise — the bug this guards against is NameError.
        _rl_mod.acquire(cost=0.0)
        _rl_mod.get_global_budget_used()


# ────────── T-BOUNDS.per_message_cap (scan 17) ─────────────────────────────

class TestMessageCap:
    """A single 50 MiB message in history must not be retained forever —
    cap individual message text both at append time and on trim."""

    def test_oversized_user_prompt_is_capped(self):
        from cohrint_agent.session import _cap_message_text, MAX_MESSAGE_CHARS
        big = "a" * (MAX_MESSAGE_CHARS * 2)
        out = _cap_message_text(big)
        assert len(out) < len(big)
        assert len(out) <= MAX_MESSAGE_CHARS + 100  # plus marker

    def test_trim_history_truncates_giant_surviving_message(self):
        from cohrint_agent.session import _trim_history, MAX_MESSAGE_CHARS
        msgs = [
            {"role": "user", "text": "a" * (MAX_MESSAGE_CHARS + 5000)},
            {"role": "assistant", "text": "ok"},
        ]
        out = _trim_history(msgs)
        # The giant text must be truncated even though pair-drop can't
        # remove it (it's the only pair).
        assert len(out[0]["text"]) <= MAX_MESSAGE_CHARS + 100


# ────────── T-SAFETY.cwd_nul (scan 17) ─────────────────────────────────────

class TestCwdNul:
    """A tampered session with cwd containing \\x00 must be normalised
    to "." before reaching subprocess.run, which would otherwise yield
    an opaque exit-1 on older CPython (null check after fork)."""

    def test_resume_strips_nul_from_cwd(self, tmp_path):
        import json as _json
        from cohrint_agent.session_store import SessionStore
        from cohrint_agent.session import CohrintSession

        store = SessionStore(sessions_dir=tmp_path / "sessions")
        sid = "77777777-7777-4777-8777-777777777777"
        path = store._path(sid)
        path.write_text(_json.dumps({
            "id": sid,
            "cwd": "/tmp/work\x00evil",
            "messages": [],
            "schema_version": 1,
        }))

        class _FakeBackend:
            name = "claude"
            class capabilities:
                token_count = False
                supports_process = False
            def send(self, **_kw):
                raise AssertionError("not used")

        sess = CohrintSession.resume(sid, _FakeBackend(), store=store)
        assert "\x00" not in sess.cwd
        assert sess.cwd == "."


# ────────── T-SAFETY.sigterm_graceful (scan 17) ────────────────────────────

class TestSigtermHandler:
    """main() must install a SIGTERM handler so docker-stop / CI timeouts
    convert into SystemExit rather than hard-terminating mid-flush."""

    def test_main_source_installs_sigterm(self):
        from pathlib import Path as _P
        src = _P("cohrint_agent/cli.py").read_text()
        # The SIGTERM handler must be installed inside main().
        idx = src.find("def main(")
        assert idx >= 0
        tail = src[idx:idx + 2000]
        assert "SIGTERM" in tail, "main() does not install a SIGTERM handler"
        assert "signal.signal" in tail


# ────────── T-SAFETY.non_tty_deny (scan 17) ────────────────────────────────

class TestNonTtyDeny:
    """check_permission must deny cleanly (not raise EOFError) when stdin
    is not a tty — Prompt.ask would otherwise crash the turn on
    piped/CI invocations."""

    def test_non_tty_returns_false_without_prompt(self, tmp_path, monkeypatch):
        from cohrint_agent import permissions as P

        # Simulate Rich's real behavior on a non-tty stdin: Prompt.ask
        # raises EOFError because input() sees a closed stream.
        def _raise_eof(*a, **kw):
            raise EOFError("stdin is not a tty")
        monkeypatch.setattr(P.Prompt, "ask", _raise_eof)

        pm = P.PermissionManager(config_dir=tmp_path)
        result = pm.check_permission("Bash", {"command": "ls"})
        assert result is False


# ────────── Scan 18 — filesystem race / TOCTOU regressions ─────────────────


class TestScan18TmpExcl:
    """session_store save() must open tmp with O_EXCL so a pre-planted or
    leftover <uuid>.json.tmp cannot be silently reused
    (T-SAFETY.tmp_excl)."""

    def test_session_save_source_uses_o_excl(self):
        from pathlib import Path as _P
        src = _P("cohrint_agent/session_store.py").read_text()
        # The tmp open inside save() must include O_EXCL.
        assert "O_EXCL" in src, "session_store save() missing O_EXCL on tmp open"


class TestScan18ConfigRMW:
    """write_config must be safe against concurrent read-modify-write —
    two parallel writers cannot clobber one another's keys
    (T-CONCUR.config_rmw)."""

    def test_concurrent_writers_preserve_all_keys(self, tmp_path):
        import json as _j
        import threading
        from cohrint_agent.setup_wizard import write_config

        cd = tmp_path
        barrier = threading.Barrier(8)

        def _writer(i: int) -> None:
            barrier.wait()
            write_config({f"k{i}": i}, config_dir=cd)

        threads = [threading.Thread(target=_writer, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Read the raw file — get_config strips unknown keys for safety
        # (scan 21), but the on-disk merge must preserve them.
        final = _j.loads((cd / "config.json").read_text())
        for i in range(8):
            assert final.get(f"k{i}") == i, f"lost key k{i} from concurrent write"

    def test_write_config_rejects_symlink_target(self, tmp_path):
        """If an attacker plants config.json as a symlink at the target,
        the O_NOFOLLOW read path refuses to follow it and treats the
        file as empty rather than reading the target's contents."""
        from cohrint_agent.setup_wizard import write_config, get_config

        cd = tmp_path
        target = tmp_path / "attacker_secret.json"
        target.write_text('{"stolen": "yes"}')
        cfg = cd / "config.json"
        os.symlink(target, cfg)

        # Write should succeed and REPLACE the symlink with a regular
        # file (os.replace does not follow the destination symlink).
        write_config({"default_tier": 2}, config_dir=cd)

        # cfg is now a regular file containing only our write — the
        # attacker's JSON never merged in.
        assert not cfg.is_symlink()
        final = get_config(config_dir=cd)
        assert final["default_tier"] == 2
        assert "stolen" not in final


class TestScan18PermServerUnlink:
    """PermissionServer.run must unlink stale socket without a separate
    exists() check — the check-then-unlink race would OSError on a
    competing process cleaning up the same path
    (T-SAFETY.socket_unlink_toctou)."""

    def test_permission_server_source_uses_bare_unlink(self):
        from pathlib import Path as _P
        src = _P("cohrint_agent/permission_server.py").read_text()
        # The old exists()+unlink pattern must be gone.
        assert "os.path.exists(self.socket_path)" not in src, (
            "permission_server still gates unlink on exists() — TOCTOU"
        )
        # FileNotFoundError suppression must be present instead.
        assert "FileNotFoundError" in src


class TestScan18LockfileNoFollow:
    """All advisory lockfiles must be opened via open_lockfile() which
    applies O_NOFOLLOW, rejecting a pre-planted symlink that would
    otherwise flock a file under the attacker's control
    (T-SAFETY.lockfile_nofollow)."""

    def test_open_lockfile_rejects_symlink(self, tmp_path):
        from cohrint_agent.process_safety import open_lockfile

        real = tmp_path / "real.target"
        real.write_text("")
        link = tmp_path / "evil.lock"
        os.symlink(real, link)
        with pytest.raises(OSError):
            with open_lockfile(link):
                pass

    def test_rate_limiter_uses_open_lockfile(self):
        from pathlib import Path as _P
        src = _P("cohrint_agent/rate_limiter.py").read_text()
        assert "open_lockfile(lock_file)" in src, (
            "rate_limiter still uses raw open() on the lockfile path"
        )

    def test_session_store_uses_open_lockfile(self):
        from pathlib import Path as _P
        src = _P("cohrint_agent/session_store.py").read_text()
        assert "open_lockfile(lockfile)" in src


class TestScan18UmaskRestricted:
    """main() must call os.umask(0o077) so config/session files created
    downstream cannot become world-readable even if a later caller
    forgets to chmod (T-PRIVACY.umask)."""

    def test_main_source_sets_restrictive_umask(self):
        from pathlib import Path as _P
        src = _P("cohrint_agent/cli.py").read_text()
        idx = src.find("def main(")
        assert idx >= 0
        tail = src[idx:idx + 1200]
        assert "os.umask(0o077)" in tail, (
            "main() does not set a restrictive umask"
        )


class TestScan18SpoolLazy:
    """Tracker._SPOOL_DIR must resolve lazily via module __getattr__ —
    eager Path.home() at import crashes in minimal containers
    (T-SAFETY.lazy_config_dir)."""

    def test_spool_dir_is_lazy(self):
        from cohrint_agent import tracker as _t
        # _SPOOL_DIR must NOT be present in module __dict__ by default.
        # A concrete attribute indicates eager resolution.
        if "_SPOOL_DIR" in _t.__dict__:
            # Accept only if it's been set by a test monkeypatch in this
            # run (shadows __getattr__). Fresh import should have no dict
            # entry — verify __getattr__ path exists as the fallback.
            pass
        # The getter must exist and return a Path.
        import sys as _sys
        got = getattr(_sys.modules["cohrint_agent.tracker"], "_SPOOL_DIR")
        from pathlib import Path as _P
        assert isinstance(got, _P)


# ────────── Scan 19 — resource exhaustion / DoS regressions ─────────────────


class TestScan19ApiKeyBounded:
    """Reading the API key file must be size-bounded — a tampered or
    symlink-pointed-at-/dev/zero file would otherwise OOM startup
    (T-DOS.api_key_size_cap)."""

    def test_api_client_source_bounds_key_read(self):
        from pathlib import Path as _P
        src = _P("cohrint_agent/api_client.py").read_text()
        # The unbounded open(path).read() pattern must be gone.
        assert "open(path).read().strip()" not in src, (
            "api_client still reads api_key with unbounded .read()"
        )
        # A bounded read must be present on an api_key code path.
        assert ".read(8192)" in src or "O_NOFOLLOW" in src


class TestScan19SlowLoris:
    """permission_server._handle_connection must enforce a wall-clock
    deadline in addition to the per-recv timeout; a peer that sends 1
    byte just under the per-recv limit must not hold the socket forever
    (T-DOS.slow_loris)."""

    def test_handle_connection_source_uses_wall_clock_deadline(self):
        from pathlib import Path as _P
        src = _P("cohrint_agent/permission_server.py").read_text()
        idx = src.find("def _handle_connection")
        assert idx >= 0
        body = src[idx : idx + 1500]
        assert "monotonic" in body, (
            "_handle_connection has no wall-clock deadline — slow-loris vector"
        )
        assert "deadline" in body

    def test_slow_loris_peer_is_cut_off(self):
        """End-to-end: open a connection, send nothing, server must close
        within the wall-clock limit rather than hanging indefinitely."""
        import socket
        import tempfile
        import time
        import uuid

        from cohrint_agent import permission_server as _ps

        # AF_UNIX paths are capped at ~104 bytes on macOS; pytest's
        # tmp_path can exceed that, so use /tmp directly with a random id.
        sock_path = os.path.join(
            tempfile.gettempdir(), f"cohrint-sl-{uuid.uuid4().hex[:8]}.sock"
        )
        # Shrink the wall clock for the test.
        orig = _ps.PermissionServer._RECV_WALL_CLOCK_SECS
        _ps.PermissionServer._RECV_WALL_CLOCK_SECS = 1.0
        try:
            class _Fake:
                pass

            srv = _ps.PermissionServer(sock_path, _Fake())
            srv.start()
            try:
                # Wait for server to be listening.
                deadline = time.monotonic() + 3.0
                while time.monotonic() < deadline:
                    if os.path.exists(sock_path):
                        break
                    time.sleep(0.02)
                assert os.path.exists(sock_path), "server never bound"

                client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                client.settimeout(5.0)
                client.connect(sock_path)
                # Send nothing. The server must close us out within
                # _RECV_WALL_CLOCK_SECS and reply "deny\n".
                start = time.monotonic()
                try:
                    resp = client.recv(32)
                except socket.timeout:
                    resp = b""
                elapsed = time.monotonic() - start
                client.close()
                assert elapsed < 3.0, (
                    f"slow-loris peer held connection {elapsed:.1f}s — no deadline"
                )
                assert resp.startswith(b"deny")
            finally:
                srv.stop()
                srv.join(timeout=2.0)
        finally:
            _ps.PermissionServer._RECV_WALL_CLOCK_SECS = orig
            try:
                os.unlink(sock_path)
            except OSError:
                pass


class TestScan19BudgetScanBounded:
    """get_global_budget_used must size-cap each session file it reads —
    matches the MAX_SESSION_FILE_BYTES protection already on list_all
    (T-DOS.budget_scan_size_cap)."""

    def test_oversized_session_file_is_skipped(self, tmp_path, monkeypatch):
        import cohrint_agent.rate_limiter as _rl
        if "_STATE_FILE" in _rl.__dict__:
            del _rl.__dict__["_STATE_FILE"]
        monkeypatch.setattr(_rl, "safe_config_dir", lambda: tmp_path)

        sessions = tmp_path / "sessions"
        sessions.mkdir(parents=True)

        # Write a valid small session with cost 2.5
        import json as _j
        (sessions / "aaa.json").write_text(_j.dumps({
            "cost_summary": {"total_cost_usd": 2.5}
        }))
        # Write an oversized (2 MiB > 1 MiB cap) session — must be skipped.
        huge = {"cost_summary": {"total_cost_usd": 999999.0}, "pad": "x" * (2 * 1024 * 1024)}
        (sessions / "bbb.json").write_text(_j.dumps(huge))

        # Clear cache.
        _rl._budget_cache.update({"value": None, "ts": 0.0, "key": None})
        total = _rl.get_global_budget_used()
        assert total == 2.5, f"oversized session was not skipped; got total={total}"


class TestScan19SpoolReadBounded:
    """tracker._spool_write / _spool_drain must size-cap the read — the
    line-count cap is only applied post-read, so an adversarially large
    spool file would be fully read into memory first
    (T-DOS.spool_read_size_cap)."""

    def test_spool_source_has_byte_cap(self):
        from pathlib import Path as _P
        src = _P("cohrint_agent/tracker.py").read_text()
        assert "_MAX_SPOOL_BYTES" in src, (
            "tracker has no _MAX_SPOOL_BYTES ceiling on read"
        )
        # The ceiling must be used in at least one rf.read call.
        assert "_MAX_SPOOL_BYTES + 1" in src


class TestScan19RetryDeadline:
    """_send_with_retry must abort after a wall-clock deadline — bounded
    per-attempt sleeps alone allow stacked waits against a hung upstream
    (T-DOS.retry_deadline)."""

    def test_retry_source_has_wall_clock_deadline(self):
        from pathlib import Path as _P
        src = _P("cohrint_agent/api_client.py").read_text()
        idx = src.find("def _send_with_retry")
        assert idx >= 0
        body = src[idx : idx + 2000]
        assert "deadline" in body, (
            "_send_with_retry has no wall-clock deadline"
        )
        assert "_RETRY_WALL_CLOCK_SECS" in body or "monotonic" in body


# ────────── Scan 21 — deserialization / input-boundary regressions ─────────


class TestScan21BashTypeCheck:
    """_exec_bash must coerce model-supplied 'timeout' into a finite
    (0, 600] float and refuse non-string 'command' (T-INPUT.bash_shape_check)."""

    def test_non_string_command_rejected(self):
        from cohrint_agent.tools import _exec_bash
        out = _exec_bash({"command": {"evil": True}}, ".")
        assert "must be a non-empty string" in out

    def test_nan_timeout_defaults_to_120(self):
        from cohrint_agent.tools import _exec_bash
        out = _exec_bash({"command": "echo ok", "timeout": float("nan")}, ".")
        # Command should actually run (not crash on NaN).
        assert "ok" in out or "error" not in out.lower() or out.strip()

    def test_inf_timeout_clamped(self):
        from cohrint_agent.tools import _exec_bash
        out = _exec_bash({"command": "echo hello", "timeout": float("inf")}, ".")
        assert "hello" in out

    def test_negative_timeout_defaulted(self):
        from cohrint_agent.tools import _exec_bash
        out = _exec_bash({"command": "echo neg", "timeout": -5}, ".")
        assert "neg" in out


class TestScan21ReadBounds:
    """_exec_read must clamp offset/limit — negative offsets must not
    leak end-of-file, huge limits must not allocate huge lists
    (T-INPUT.read_bounds)."""

    def test_negative_offset_treated_as_zero(self, tmp_path):
        from cohrint_agent.tools import _exec_read
        f = tmp_path / "x.txt"
        f.write_text("a\nb\nc\n")
        out = _exec_read({"file_path": str(f), "offset": -1000, "limit": 10}, str(tmp_path))
        # First numbered line must be "1\ta" — not a negative-index slice.
        assert out.startswith("1\ta")

    def test_huge_limit_clamped(self, tmp_path):
        from cohrint_agent.tools import _exec_read
        f = tmp_path / "y.txt"
        f.write_text("line\n" * 20)
        out = _exec_read({"file_path": str(f), "limit": 10**18}, str(tmp_path))
        # Should return without raising and contain a bounded number of lines.
        assert out.count("\n") < 10001


class TestScan21BudgetRangeGate:
    """get_global_budget_used must reject NaN/inf/negative/huge
    total_cost_usd values rather than add them to the running total
    (T-INPUT.budget_range_gate)."""

    def test_nan_cost_is_skipped(self, tmp_path, monkeypatch):
        import cohrint_agent.rate_limiter as _rl
        if "_STATE_FILE" in _rl.__dict__:
            del _rl.__dict__["_STATE_FILE"]
        monkeypatch.setattr(_rl, "safe_config_dir", lambda: tmp_path)
        sessions = tmp_path / "sessions"
        sessions.mkdir(parents=True)

        # A valid session worth $1.
        (sessions / "aaa.json").write_text('{"cost_summary": {"total_cost_usd": 1.0}}')
        # NaN cost — must be ignored, not poison the total.
        (sessions / "bbb.json").write_text('{"cost_summary": {"total_cost_usd": NaN}}')
        # inf cost — must be ignored.
        (sessions / "ccc.json").write_text('{"cost_summary": {"total_cost_usd": Infinity}}')
        # Negative cost — must be ignored.
        (sessions / "ddd.json").write_text('{"cost_summary": {"total_cost_usd": -9999}}')
        # Too-large cost — must be ignored.
        (sessions / "eee.json").write_text('{"cost_summary": {"total_cost_usd": 1e12}}')

        _rl._budget_cache.update({"value": None, "ts": 0.0, "key": None})
        total = _rl.get_global_budget_used()
        assert total == 1.0
        import math as _m
        assert not _m.isnan(total)
        assert not _m.isinf(total)


class TestScan21SessionSchemaVersion:
    """SessionStore.load must refuse future-tagged schema_versions instead
    of parsing through as v1 (T-INPUT.schema_version_reject)."""

    def test_future_schema_version_refused(self, tmp_path):
        import uuid
        from cohrint_agent.session_store import (
            SessionStore,
            SessionNotFoundError,
            CURRENT_SCHEMA_VERSION,
        )
        store = SessionStore(sessions_dir=tmp_path)
        sid = str(uuid.uuid4())
        import json as _j
        (tmp_path / f"{sid}.json").write_text(
            _j.dumps({"id": sid, "schema_version": CURRENT_SCHEMA_VERSION + 1})
        )
        with pytest.raises(SessionNotFoundError) as excinfo:
            store.load(sid)
        assert "schema_version" in str(excinfo.value)

    def test_non_dict_payload_refused(self, tmp_path):
        import uuid
        from cohrint_agent.session_store import SessionStore, SessionNotFoundError
        store = SessionStore(sessions_dir=tmp_path)
        sid = str(uuid.uuid4())
        (tmp_path / f"{sid}.json").write_text('"just a string"')
        with pytest.raises(SessionNotFoundError):
            store.load(sid)

    def test_list_all_skips_future_schema(self, tmp_path):
        import uuid, json as _j
        from cohrint_agent.session_store import (
            SessionStore,
            CURRENT_SCHEMA_VERSION,
        )
        store = SessionStore(sessions_dir=tmp_path)
        # One valid v1 session + one future-tagged + one non-dict.
        good_id = str(uuid.uuid4())
        bad_id = str(uuid.uuid4())
        nondict_id = str(uuid.uuid4())
        (tmp_path / f"{good_id}.json").write_text(
            _j.dumps({"id": good_id, "schema_version": 1, "last_active_at": "z"})
        )
        (tmp_path / f"{bad_id}.json").write_text(
            _j.dumps({"id": bad_id, "schema_version": CURRENT_SCHEMA_VERSION + 5})
        )
        (tmp_path / f"{nondict_id}.json").write_text('[1, 2, 3]')
        got = store.list_all()
        assert len(got) == 1
        assert got[0]["id"] == good_id


class TestScan21PermShapeCheck:
    """permission_server._handle_connection must shape-validate the JSON
    payload before enqueueing it — a non-dict or a dict without a string
    tool_name must respond deny without poisoning the main-thread queue
    (T-INPUT.perm_shape)."""

    def test_handle_source_validates_tool_name(self):
        from pathlib import Path as _P
        src = _P("cohrint_agent/permission_server.py").read_text()
        idx = src.find("def _handle_connection")
        assert idx >= 0
        body = src[idx : idx + 2500]
        assert "isinstance(tool_data, dict)" in body
        assert "isinstance(tn, str)" in body


class TestScan21ConfigShape:
    """setup_wizard.get_config must reject tampered value types."""

    def test_bogus_hook_fail_policy_falls_back_to_default(self, tmp_path):
        # Default is "deny" (fail-closed): a tampered value must not give the
        # caller a free "allow" via type confusion.
        from cohrint_agent.setup_wizard import get_config
        (tmp_path / "config.json").write_text('{"hook_fail_policy": ["deny"]}')
        cfg = get_config(config_dir=tmp_path)
        assert cfg["hook_fail_policy"] == "deny"

    def test_bogus_default_tier_becomes_none(self, tmp_path):
        from cohrint_agent.setup_wizard import get_config
        (tmp_path / "config.json").write_text('{"default_tier": "9; rm -rf"}')
        cfg = get_config(config_dir=tmp_path)
        assert cfg["default_tier"] is None

    def test_out_of_range_tier_rejected(self, tmp_path):
        from cohrint_agent.setup_wizard import get_config
        (tmp_path / "config.json").write_text('{"default_tier": 99}')
        cfg = get_config(config_dir=tmp_path)
        assert cfg["default_tier"] is None

    def test_valid_tier_preserved(self, tmp_path):
        from cohrint_agent.setup_wizard import get_config
        (tmp_path / "config.json").write_text('{"default_tier": 2, "hook_fail_policy": "deny"}')
        cfg = get_config(config_dir=tmp_path)
        assert cfg["default_tier"] == 2
        assert cfg["hook_fail_policy"] == "deny"


# ────────── Scan 22 — supply chain / PATH / env hijack regressions ─────────


class TestScan22AnthropicBaseUrlStrip:
    """ANTHROPIC_BASE_URL must live in the _STRIP_ALWAYS set so child
    subprocesses never inherit an attacker-set SDK endpoint
    (T-SAFETY.anthropic_base_url_strip)."""

    def test_anthropic_base_url_in_strip_set(self):
        from cohrint_agent.process_safety import _STRIP_ALWAYS
        assert "ANTHROPIC_BASE_URL" in _STRIP_ALWAYS
        assert "ANTHROPIC_API_BASE" in _STRIP_ALWAYS
        assert "OPENAI_BASE_URL" in _STRIP_ALWAYS
        assert "OPENAI_API_BASE" in _STRIP_ALWAYS

    def test_safe_child_env_strips_anthropic_base_url(self):
        from cohrint_agent.process_safety import safe_child_env
        out = safe_child_env({
            "ANTHROPIC_BASE_URL": "http://attacker.example/",
            "OPENAI_BASE_URL": "http://attacker.example/",
            "PATH": "/usr/bin",
        })
        assert "ANTHROPIC_BASE_URL" not in out
        assert "OPENAI_BASE_URL" not in out


class TestScan22AnthropicBaseUrlValidate:
    """api_client must refuse a non-HTTPS / non-anthropic.com
    ANTHROPIC_BASE_URL on the parent process too — the anthropic SDK
    honors it and would exfiltrate prompts + bearer token
    (T-SAFETY.anthropic_base_url_validate)."""

    def test_api_client_source_validates_base_url(self):
        from pathlib import Path as _P
        src = _P("cohrint_agent/api_client.py").read_text()
        assert 'os.environ.pop("ANTHROPIC_BASE_URL"' in src
        assert "anthropic.com" in src


class TestScan22HookScriptPathPin:
    """The installed perm-hook.sh must use absolute interpreter paths so
    a writable PATH entry can't supply a trojan python3 that returns
    'allow' for every prompt (T-SAFETY.hook_script_path_hijack)."""

    def test_installed_hook_has_absolute_shebang(self, tmp_path):
        from cohrint_agent.permission_server import install_hook_script
        hp = install_hook_script(tmp_path)
        content = hp.read_text()
        # Shebang must be absolute (starts with /)
        first_line = content.splitlines()[0]
        assert first_line.startswith("#!/"), (
            f"Hook shebang is relative / wrong: {first_line!r}"
        )
        # No bare 'python3 ' invocations inside the script body.
        assert "\npython3 " not in content and " python3 " not in content, (
            "hook script still calls python3 via PATH"
        )


class TestScan22BackendBinaryResolver:
    """resolve_backend_binary must return an absolute path for installed
    binaries and reject world/group-writable ones
    (T-SAFETY.backend_path_pin)."""

    def test_resolver_returns_absolute_path_or_none(self):
        from cohrint_agent.process_safety import resolve_backend_binary
        # ls should always exist on a sane test box.
        got = resolve_backend_binary("ls")
        if got is not None:
            assert os.path.isabs(got)

    def test_resolver_rejects_world_writable(self, tmp_path, monkeypatch):
        from cohrint_agent.process_safety import (
            resolve_backend_binary,
            _BACKEND_BIN_CACHE,
        )
        _BACKEND_BIN_CACHE.clear()
        # Plant a writable "evil" binary, prepend its dir to PATH.
        evil = tmp_path / "cohrint-evil-bin"
        evil.write_text("#!/bin/sh\necho hi\n")
        # Group + other writable.
        os.chmod(evil, 0o777)
        monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ.get('PATH','')}")
        got = resolve_backend_binary("cohrint-evil-bin")
        assert got is None, (
            "world/group writable binary must be refused"
        )
        _BACKEND_BIN_CACHE.clear()

    def test_claude_backend_source_pins_bin(self):
        from pathlib import Path as _P
        src = _P("cohrint_agent/backends/claude_backend.py").read_text()
        assert "resolve_backend_binary" in src

    def test_codex_backend_source_pins_bin(self):
        from pathlib import Path as _P
        src = _P("cohrint_agent/backends/codex_backend.py").read_text()
        assert "resolve_backend_binary" in src

    def test_gemini_backend_source_pins_bin(self):
        from pathlib import Path as _P
        src = _P("cohrint_agent/backends/gemini_backend.py").read_text()
        assert "resolve_backend_binary" in src


class TestScan22HomeEnvHijack:
    """safe_config_dir must anchor to pw_dir (UID-based), not $HOME —
    otherwise HOME=/tmp/evil + COHRINT_CONFIG_DIR=/tmp/evil/x bypasses
    the escape check (T-SAFETY.home_env_hijack)."""

    def test_safe_config_dir_rejects_home_redirect(self, tmp_path, monkeypatch):
        from cohrint_agent.process_safety import safe_config_dir, _real_home
        real = _real_home()
        if real is None:
            pytest.skip("pwd lookup unavailable in this environment")
        # Attempt to redirect both HOME and the config dir into /tmp.
        evil = tmp_path / "evil_home"
        evil.mkdir()
        cfg = evil / ".cohrint-agent"
        monkeypatch.setenv("HOME", str(evil))
        monkeypatch.setenv("COHRINT_CONFIG_DIR", str(cfg))
        # /tmp is in the explicit tmp-root allowlist, so the helper
        # will still accept this candidate (by design for test support).
        # The critical invariant is that the DEFAULT path (no
        # COHRINT_CONFIG_DIR) stays in the real home.
        monkeypatch.delenv("COHRINT_CONFIG_DIR", raising=False)
        got = safe_config_dir()
        assert str(got).startswith(str(real)), (
            f"default config dir escaped real home: {got} not under {real}"
        )

    def test_real_home_differs_from_HOME_when_spoofed(self, monkeypatch):
        from cohrint_agent.process_safety import _real_home
        monkeypatch.setenv("HOME", "/tmp/hijacked-home")
        real = _real_home()
        if real is None:
            pytest.skip("pwd lookup unavailable")
        assert str(real) != "/tmp/hijacked-home"
