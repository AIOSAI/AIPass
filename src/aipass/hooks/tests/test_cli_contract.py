"""CLI contract tests — verify flags/subcommands our code invokes actually exist.

Probes `claude --help` and `claude agents --help` at test time. Skips cleanly
when the binary is absent. Catches phantom subcommands (like the former
`claude agents stop`) before they ship as mocked-green.
"""

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
        # The short and long spelling on one measured line, not "either is
        # somewhere in the text": a bare "-p" matches "--permission-mode" and
        # the or-clause could not fail while any flag starting with p existed.
        h = _get_main_help()
        assert "-p, --print" in h

    def test_name_flag(self):
        # Same shape. A bare "-n" matched every "\n"-free option line that
        # happened to contain it; the pair is what session_boot actually types.
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
        # Measured 2026-09-08: the word "stop" appears nowhere in
        # `claude agents --help`. The old or-clause could not fail - the second
        # half ("agents stop" absent) held even when the first half broke, so
        # the day a stop subcommand reappeared this test would still be green.
        h = _get_agents_help()
        assert "stop" not in h.lower()


_DAEMON_SWITCH = "CLAUDE_CODE_DISABLE_AGENT_VIEW"


def _daemon_surface_accounted_for(help_text: str, token: str) -> bool:
    """True when `token` is offered by the daemon CLI, or refused by the switch.

    Args:
        help_text: Output of `claude daemon --help`.
        token: The flag or subcommand session_boot invokes.

    Returns:
        Whether the surface is accounted for — present, or absent for the one
        documented reason. An unexplained absence answers False.
    """
    return token in help_text or _DAEMON_SWITCH in help_text


@_SKIP
class TestClaudeDaemonFlags:
    """Flags from `claude daemon --help` that session_boot invokes.

    Two worlds since 2026-09-01. @devpulse set CLAUDE_CODE_DISABLE_AGENT_VIEW=1
    fleet-wide (commit b22af969) to close the second-brain incident, and that
    switch disables the whole `daemon` subcommand — the settings value beats a
    shell override, measured. So session_boot's `claude daemon stop --any` is
    dead code under the switch (devpulse's hardening item 2, plan-only until
    Patrick asks) and live without it.

    The invariant across both: the surface session_boot invokes is either
    THERE, or refused by name. What must never happen is a flag going missing
    with no explanation — that is the phantom-subcommand class this file was
    written to catch, and asserting the flag unconditionally would have
    reported exactly that when the truth was a deliberate switch.
    """

    def test_stop_subcommand(self):
        assert _daemon_surface_accounted_for(_get_daemon_help(), "stop")

    def test_any_flag(self):
        assert _daemon_surface_accounted_for(_get_daemon_help(), "--any")

    @pytest.mark.parametrize("token", ["stop", "--any"])
    def test_unexplained_absence_still_fails(self, token: str):
        """MUTATION-CHECK: the two tests above must not pass on ANY absence.

        A daemon help text that simply stopped listing the flags — a rename, an
        upstream removal — has to fail, or the pair above degrades into a test
        that asserts nothing.
        """
        assert not _daemon_surface_accounted_for("Usage: claude daemon [options]\n  --verbose\n", token)


@_SKIP
class TestAgentsStopDoesNotExist:
    """Regression: `claude agents stop <id>` must NOT be a valid command."""

    def test_agents_rejects_stop_arg(self):
        assert _CLAUDE is not None
        result = subprocess.run(
            [_CLAUDE, "agents", "stop", "test-id"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 1
        # The measured line, 2026-09-08:
        #   error: too many arguments for 'agents'. Expected 0 arguments but got 2.
        # The old or-clause fell through to "error", which any failure prints -
        # including a stop subcommand that existed and errored for its own
        # reasons, which is precisely the regression this class exists to catch.
        assert "too many arguments for 'agents'" in result.stderr
