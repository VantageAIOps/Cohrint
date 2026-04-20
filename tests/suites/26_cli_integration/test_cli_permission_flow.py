"""
Test Suite 26b — cohrint-cli Permission Flow (source-structure verification)
============================================================================
Verifies the TypeScript patterns that implement interactive permission prompts
in `cohrint-cli/src/index.ts`:

- Denial capture via claude's stream-json `permission_denials` array
- Interactive y/a/n prompt via `askToolPermission`
- Permission input routing bypasses the REPL handler
  (prevents the "n" answer from being re-submitted as a new user prompt)
- Stale-session path falls through to permission handling
- Retry only when the user grants a NEW tool (no redundant claude call)
- One-shot (-p) and stdin non-interactive modes surface denials on stderr

Labels: CI-PERM.1 – CI-PERM.8
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from helpers.output import section, chk, get_results, reset_results

ROOT = Path(__file__).parent.parent.parent.parent
CLI_SRC = ROOT / "cohrint-cli" / "src" / "index.ts"
RUNNER_SRC = ROOT / "cohrint-cli" / "src" / "runner.ts"


def idx() -> str:
    return CLI_SRC.read_text()


def runner() -> str:
    return RUNNER_SRC.read_text()


class TestPermissionFlow:
    def test_ci_perm_01_permission_denials_captured_from_stream_json(self):
        section("CI-PERM — Permission flow in cohrint-cli")
        src = runner()
        chk(
            "CI-PERM.1 runner captures permission_denials from claude stream-json",
            'obj["permission_denials"]' in src and "capturedDenials.push" in src,
        )
        assert 'obj["permission_denials"]' in src
        assert "capturedDenials.push" in src

    def test_ci_perm_02_ask_tool_permission_function(self):
        src = idx()
        chk(
            "CI-PERM.2 askToolPermission function exists with y/a/n contract",
            "async function askToolPermission" in src
            and '"yes"' in src
            and '"always"' in src
            and '"no"' in src,
        )
        assert "async function askToolPermission" in src

    def test_ci_perm_03_permission_resolver_isolated_from_repl(self):
        src = idx()
        chk(
            "CI-PERM.3 permission input bypasses REPL handler via _permissionResolver",
            "_permissionResolver" in src
            and "_isAwaitingPermission" in src
            and "_feedPermissionInput" in src,
        )
        assert "_permissionResolver" in src
        assert "_isAwaitingPermission" in src

    def test_ci_perm_04_onlinereceived_routes_to_permission(self):
        src = idx()
        chk(
            "CI-PERM.4 onLineReceived short-circuits when awaiting permission",
            "function onLineReceived" in src
            and "_isAwaitingPermission()" in src
            and "_feedPermissionInput" in src,
        )
        assert "function onLineReceived" in src
        assert "_isAwaitingPermission()" in src

    def test_ci_perm_05_stale_session_falls_through(self):
        src = idx()
        # The stale-session handler must NOT early-return; it should update `result`
        # and fall through to the permission-denial block.
        chk(
            "CI-PERM.5 stale-session path reassigns `result` (no early return)",
            "result = await executePrompt(" in src
            and "useContinue = false" in src
            and "useSessionId = undefined" in src,
        )
        assert "useContinue = false" in src
        assert "useSessionId = undefined" in src

    def test_ci_perm_06_retry_only_when_granted_new_tool(self):
        src = idx()
        chk(
            "CI-PERM.6 retry gated by `grantedNew`, not allowlist size",
            "grantedNew" in src and "if (grantedNew)" in src,
        )
        assert "grantedNew" in src
        assert "if (grantedNew)" in src

    def test_ci_perm_07_oneshot_surfaces_denials(self):
        src = idx()
        chk(
            "CI-PERM.7 one-shot mode warns on stderr and exits non-zero on denial",
            "oneShot.permissionDenials.length > 0" in src
            and "process.exit(oneShot.permissionDenials.length > 0 ? 2 : 0)" in src,
        )
        assert "oneShot.permissionDenials.length > 0" in src
        assert "process.exit(oneShot.permissionDenials.length > 0 ? 2 : 0)" in src

    def test_ci_perm_08_stdin_mode_surfaces_denials(self):
        src = idx()
        chk(
            "CI-PERM.8 stdin mode warns on stderr and exits non-zero on denial",
            "stdinRun.permissionDenials.length > 0" in src
            and "process.exit(stdinRun.permissionDenials.length > 0 ? 2 : 0)" in src,
        )
        assert "stdinRun.permissionDenials.length > 0" in src
        assert "process.exit(stdinRun.permissionDenials.length > 0 ? 2 : 0)" in src


if __name__ == "__main__":
    reset_results()
    pytest.main([__file__, "-v"])
    r = get_results()
    print(f"\n{r['passed']}/{r['total']} passed")
