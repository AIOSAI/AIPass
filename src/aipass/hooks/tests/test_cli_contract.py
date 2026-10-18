# =================== AIPass ====================
# Name: test_cli_contract.py
# Version: 1.0.1
# Description: CLI contract tests for the claude flags session_boot invokes
# Branch: hooks
# Created: 2026-07-13
# Modified: 2026-10-17
# =============================================

"""Tests for apps/handlers/lifecycle/session_boot.py's claude CLI contract."""

# Probes the real `claude --help` so a phantom flag cannot ship mocked-green; skips without the binary.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that session_boot.py parses and imports
# seedgo: no-test-needed(stdlib) — subprocess.run and shutil.which themselves
# seedgo: no-test-needed(generated) — the full claude help text, upstream's output; only session_boot's flags pinned

import shutil
import subprocess

import pytest

_CLAUDE = shutil.which("claude")
_SKIP = pytest.mark.skipif(_CLAUDE is None, reason="claude binary not on PATH")


def _help_text(args: list[str]) -> str:
    assert _CLAUDE is not None
    result = subprocess.run(
        [_CLAUDE, *args, "--help"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=10,
    )
    return result.stdout + result.stderr


def _get_main_help() -> str:
    return _help_text([])


def _get_agents_help() -> str:
    return _help_text(["agents"])


def _get_daemon_help() -> str:
    return _help_text(["daemon"])


@_SKIP
class TestClaudeMainFlags:
    """Flags from `claude --help` that session_boot invokes."""

    def test_permission_mode(self):
        assert "--permission-mode" in _get_main_help()

    def test_continue(self):
        assert "--continue" in _get_main_help()

    def test_resume(self):
        assert "--resume" in _get_main_help()

    def test_p_flag(self):
        # The pair, not a bare "-p": that matches "--permission-mode" and cannot fail.
        h = _get_main_help()
        assert "-p, --print" in h

    def test_name_flag(self):
        h = _get_main_help()
        assert "-n, --name" in h


@_SKIP
class TestClaudeAgentsFlags:
    """Flags from `claude agents --help` that session_boot invokes."""

    def test_permission_mode(self):
        assert "--permission-mode" in _get_agents_help()

    def test_cwd(self):
        assert "--cwd" in _get_agents_help()

    def test_no_stop_subcommand(self):
        # The bare word, not "agents stop": that or-clause stayed green if a stop subcommand returned.
        h = _get_agents_help()
        assert "stop" not in h.lower()


_DAEMON_SWITCH = "CLAUDE_CODE_DISABLE_AGENT_VIEW"


def _daemon_surface_accounted_for(help_text: str, token: str) -> bool:
    """True when `token` is offered by the daemon CLI, or refused by the switch."""
    return token in help_text or _DAEMON_SWITCH in help_text


@_SKIP
class TestClaudeDaemonFlags:
    """Flags from `claude daemon --help` that session_boot invokes.

    CLAUDE_CODE_DISABLE_AGENT_VIEW disables `daemon`; each flag is present or refused by name, never silently gone.
    """

    def test_stop_subcommand(self):
        assert _daemon_surface_accounted_for(_get_daemon_help(), "stop")

    def test_any_flag(self):
        assert _daemon_surface_accounted_for(_get_daemon_help(), "--any")

    @pytest.mark.parametrize("token", ["stop", "--any"])
    def test_unexplained_absence_still_fails(self, token: str):
        """MUTATION-CHECK: the two tests above must not pass on ANY absence."""
        assert not _daemon_surface_accounted_for("Usage: claude daemon [options]\n  --verbose\n", token)
