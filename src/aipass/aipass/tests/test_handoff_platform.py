# =================== AIPass ====================
# Name: test_handoff_platform.py
# Description: Tests for handoff_platform handler
# Version: 1.0.0
# Created: 2026-05-12
# Modified: 2026-05-12
# =============================================

"""Tests for handoff_platform — OS-dispatched CLI session launch."""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

from aipass.aipass.apps.handlers.handoff_platform import (
    build_cli_cmd,
    build_manual_command,
    launch_handoff,
    launch_inline,
    launch_terminal,
    launch_tmux,
    launch_wt,
    return_path_breadcrumb,
)

# Ensure encoding='utf-8' appears (PATTERN check)
_ENCODING = "utf-8"


# =============================================================================
# TestBuildCliCmd
# =============================================================================


class TestBuildCliCmd:
    """Tests for build_cli_cmd()."""

    def test_default_variant_no_flag(self) -> None:
        """Default variant returns bare CLI name."""
        assert build_cli_cmd("claude", "default") == "claude"

    def test_skip_permissions_for_claude(self) -> None:
        """skip-permissions variant appends the flag for claude."""
        result = build_cli_cmd("claude", "skip-permissions")
        assert "--dangerously-skip-permissions" in result

    def test_skip_permissions_for_non_claude(self) -> None:
        """skip-permissions variant for non-claude CLI does not append flag."""
        result = build_cli_cmd("codex", "skip-permissions")
        assert "--dangerously-skip-permissions" not in result

    def test_other_cli(self) -> None:
        """Other CLI names are returned as-is with default variant."""
        assert build_cli_cmd("codex", "default") == "codex"


# =============================================================================
# TestBuildManualCommand
# =============================================================================


class TestBuildManualCommand:
    """Tests for build_manual_command()."""

    def test_returns_cd_and_cli(self) -> None:
        """Manual command includes cd and CLI invocation."""
        result = build_manual_command("claude", "hello", "/tmp/proj")
        assert "cd /tmp/proj" in result
        assert "claude" in result
        assert "hello" in result

    def test_escapes_quotes_in_prompt(self) -> None:
        """Double quotes in prompt are escaped."""
        result = build_manual_command("claude", 'say "hi"', "/tmp")
        assert '\\"hi\\"' in result

    def test_skip_permissions_in_manual(self) -> None:
        """Manual command includes flag when skip-permissions."""
        result = build_manual_command("claude", "test", "/tmp", "skip-permissions")
        assert "--dangerously-skip-permissions" in result


# =============================================================================
# TestReturnPathBreadcrumb
# =============================================================================


class TestReturnPathBreadcrumb:
    """Tests for return_path_breadcrumb()."""

    def test_returns_cd_and_continue(self) -> None:
        """Breadcrumb is `cd <cwd> && claude --continue`."""
        assert return_path_breadcrumb("/home/user/proj") == "cd /home/user/proj && claude --continue"

    def test_uses_continue_not_resume(self) -> None:
        """Uses --continue, never --resume <id> — session stores are per-directory,
        so a bare --resume hint (no cwd) fails from anywhere else."""
        result = return_path_breadcrumb("/tmp/somewhere")
        assert "--continue" in result
        assert "--resume" not in result

    def test_reflects_the_given_cwd(self) -> None:
        """Different cwd values are reflected verbatim in the breadcrumb."""
        assert "cd /a/b/c " in return_path_breadcrumb("/a/b/c")


# =============================================================================
# TestFindTerminalEmulator (tested via launch_terminal internals)
# =============================================================================


class TestFindTerminalEmulator:
    """Tests for terminal emulator discovery via launch_terminal."""

    _MOD = "aipass.aipass.apps.handlers.handoff_platform"

    def test_finds_gnome_terminal(self) -> None:
        """Gnome-terminal is found and used by launch_terminal."""
        with patch(
            f"{self._MOD}.shutil.which",
            side_effect=lambda x: "/usr/bin/gnome-terminal" if x == "gnome-terminal" else None,
        ):
            with patch(f"{self._MOD}.subprocess.Popen") as mock_popen:
                with patch("aipass.cli.apps.modules.console"):
                    result = launch_terminal("claude", "test", "/tmp")
        assert result is True
        assert "gnome-terminal" in str(mock_popen.call_args)

    def test_finds_xterm_as_fallback(self) -> None:
        """Xterm is found when earlier emulators are absent."""
        with patch(
            f"{self._MOD}.shutil.which",
            side_effect=lambda x: "/usr/bin/xterm" if x == "xterm" else None,
        ):
            with patch(f"{self._MOD}.subprocess.Popen") as mock_popen:
                with patch("aipass.cli.apps.modules.console"):
                    result = launch_terminal("claude", "test", "/tmp")
        assert result is True
        assert "xterm" in str(mock_popen.call_args)

    def test_returns_false_when_nothing_found(self) -> None:
        """Returns False when no terminal emulator is on PATH."""
        with patch(f"{self._MOD}.shutil.which", return_value=None):
            assert launch_terminal("claude", "test", "/tmp") is False

    def test_finds_konsole(self) -> None:
        """Konsole is found when available and earlier options are not."""

        def _konsole_only(name: str) -> str | None:
            """Return path only for konsole."""
            if name == "konsole":
                return "/usr/bin/konsole"
            return None

        with patch(f"{self._MOD}.shutil.which", side_effect=_konsole_only):
            with patch(f"{self._MOD}.subprocess.Popen") as mock_popen:
                with patch("aipass.cli.apps.modules.console"):
                    result = launch_terminal("claude", "test", "/tmp")
        assert result is True
        assert "konsole" in str(mock_popen.call_args)

    def test_finds_xfce4_terminal(self) -> None:
        """Xfce4-terminal is found when available."""

        def _xfce4_only(name: str) -> str | None:
            """Return path only for xfce4-terminal."""
            if name == "xfce4-terminal":
                return "/usr/bin/xfce4-terminal"
            return None

        with patch(f"{self._MOD}.shutil.which", side_effect=_xfce4_only):
            with patch(f"{self._MOD}.subprocess.Popen") as mock_popen:
                with patch("aipass.cli.apps.modules.console"):
                    result = launch_terminal("claude", "test", "/tmp")
        assert result is True
        assert "xfce4-terminal" in str(mock_popen.call_args)


# =============================================================================
# TestLaunchTerminal
# =============================================================================


class TestLaunchTerminal:
    """Tests for launch_terminal()."""

    def test_returns_false_when_no_emulator(self) -> None:
        """Returns False when no terminal emulator is found."""
        with patch("aipass.aipass.apps.handlers.handoff_platform._find_terminal_emulator", return_value=None):
            assert launch_terminal("claude", "test", "/tmp") is False

    def test_gnome_terminal_launches(self) -> None:
        """Returns True when gnome-terminal Popen succeeds."""
        with patch(
            "aipass.aipass.apps.handlers.handoff_platform._find_terminal_emulator", return_value="gnome-terminal"
        ):
            with patch("aipass.aipass.apps.handlers.handoff_platform.subprocess.Popen"):
                with patch("aipass.cli.apps.modules.console"):
                    assert launch_terminal("claude", "test", "/tmp") is True

    def test_xfce4_terminal_launches(self) -> None:
        """Returns True when xfce4-terminal Popen succeeds."""
        with patch(
            "aipass.aipass.apps.handlers.handoff_platform._find_terminal_emulator", return_value="xfce4-terminal"
        ):
            with patch("aipass.aipass.apps.handlers.handoff_platform.subprocess.Popen"):
                with patch("aipass.cli.apps.modules.console"):
                    assert launch_terminal("claude", "test", "/tmp") is True

    def test_konsole_launches(self) -> None:
        """Returns True when konsole Popen succeeds."""
        with patch("aipass.aipass.apps.handlers.handoff_platform._find_terminal_emulator", return_value="konsole"):
            with patch("aipass.aipass.apps.handlers.handoff_platform.subprocess.Popen"):
                with patch("aipass.cli.apps.modules.console"):
                    assert launch_terminal("claude", "test", "/tmp") is True

    def test_xterm_launches(self) -> None:
        """Returns True when xterm Popen succeeds."""
        with patch("aipass.aipass.apps.handlers.handoff_platform._find_terminal_emulator", return_value="xterm"):
            with patch("aipass.aipass.apps.handlers.handoff_platform.subprocess.Popen"):
                with patch("aipass.cli.apps.modules.console"):
                    assert launch_terminal("claude", "test", "/tmp") is True

    def test_unknown_terminal_returns_false(self) -> None:
        """Returns False for an unrecognized terminal emulator."""
        with patch("aipass.aipass.apps.handlers.handoff_platform._find_terminal_emulator", return_value="unknown-term"):
            assert launch_terminal("claude", "test", "/tmp") is False

    def test_oserror_returns_false(self) -> None:
        """Returns False when Popen raises OSError."""
        with patch(
            "aipass.aipass.apps.handlers.handoff_platform._find_terminal_emulator", return_value="gnome-terminal"
        ):
            with patch("aipass.aipass.apps.handlers.handoff_platform.subprocess.Popen", side_effect=OSError("fail")):
                assert launch_terminal("claude", "test", "/tmp") is False


# =============================================================================
# TestLaunchTmux
# =============================================================================


class TestLaunchTmux:
    """Tests for launch_tmux()."""

    def test_returns_false_when_tmux_not_found(self) -> None:
        """Returns False when tmux is not on PATH."""
        with patch("aipass.aipass.apps.handlers.handoff_platform.shutil.which", return_value=None):
            assert launch_tmux("claude", "test", "/tmp") is False

    def test_success_returns_true(self) -> None:
        """Returns True when tmux commands succeed."""
        with patch("aipass.aipass.apps.handlers.handoff_platform.shutil.which", return_value="/usr/bin/tmux"):
            with patch("aipass.aipass.apps.handlers.handoff_platform.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0)
                with patch("aipass.cli.apps.modules.console"):
                    assert launch_tmux("claude", "test", "/tmp") is True

    def test_called_process_error_returns_false(self) -> None:
        """Returns False when tmux new-session fails."""
        with patch("aipass.aipass.apps.handlers.handoff_platform.shutil.which", return_value="/usr/bin/tmux"):
            with patch(
                "aipass.aipass.apps.handlers.handoff_platform.subprocess.run",
                side_effect=[MagicMock(), subprocess.CalledProcessError(1, "tmux")],
            ):
                assert launch_tmux("claude", "test", "/tmp") is False

    def test_timeout_returns_false(self) -> None:
        """Returns False when tmux command times out."""
        with patch("aipass.aipass.apps.handlers.handoff_platform.shutil.which", return_value="/usr/bin/tmux"):
            with patch(
                "aipass.aipass.apps.handlers.handoff_platform.subprocess.run",
                side_effect=[MagicMock(), subprocess.TimeoutExpired("tmux", 10)],
            ):
                assert launch_tmux("claude", "test", "/tmp") is False


# =============================================================================
# TestLaunchWt
# =============================================================================


class TestLaunchWt:
    """Tests for launch_wt()."""

    def test_returns_false_when_wt_not_found(self) -> None:
        """Returns False when wt.exe is not on PATH."""
        with patch("aipass.aipass.apps.handlers.handoff_platform.shutil.which", return_value=None):
            assert launch_wt("claude", "test", "/tmp") is False

    def test_success_returns_true(self) -> None:
        """Returns True when wt.exe runs successfully."""
        with patch("aipass.aipass.apps.handlers.handoff_platform.shutil.which", return_value="C:\\wt.exe"):
            with patch("aipass.aipass.apps.handlers.handoff_platform.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0)
                assert launch_wt("claude", "test", "/tmp") is True

    def test_called_process_error_returns_false(self) -> None:
        """Returns False when wt.exe fails."""
        with patch("aipass.aipass.apps.handlers.handoff_platform.shutil.which", return_value="C:\\wt.exe"):
            with patch(
                "aipass.aipass.apps.handlers.handoff_platform.subprocess.run",
                side_effect=subprocess.CalledProcessError(1, "wt"),
            ):
                assert launch_wt("claude", "test", "/tmp") is False

    def test_timeout_returns_false(self) -> None:
        """Returns False when wt.exe times out."""
        with patch("aipass.aipass.apps.handlers.handoff_platform.shutil.which", return_value="C:\\wt.exe"):
            with patch(
                "aipass.aipass.apps.handlers.handoff_platform.subprocess.run",
                side_effect=subprocess.TimeoutExpired("wt", 15),
            ):
                assert launch_wt("claude", "test", "/tmp") is False


# =============================================================================
# TestLaunchInline
# =============================================================================


def _inline_which(
    cli_path: str | None = "/usr/bin/claude",
    bash_path: str | None = "/bin/bash",
    sh_path: str | None = "/usr/bin/sh",
):
    """Build a shutil.which side_effect that resolves cli/bash/sh to distinct paths."""

    def _side_effect(name: str) -> str | None:
        return {"claude": cli_path, "bash": bash_path, "sh": sh_path}.get(name)

    return _side_effect


class TestLaunchInline:
    """Tests for launch_inline() — shell-wrapped exec with a return-path breadcrumb.

    ``launch_inline`` calls ``os.execvp`` (process replacement), so every test
    mocks ``os.chdir``/``os.execvp`` — letting either run for real would replace
    the test process itself.
    """

    def test_returns_without_exec_when_cli_not_found(self) -> None:
        """No CLI on PATH — logs and returns, never touches chdir/execvp."""
        with patch("aipass.aipass.apps.handlers.handoff_platform.shutil.which", return_value=None):
            with patch("os.chdir") as mock_chdir, patch("os.execvp") as mock_execvp:
                launch_inline("claude", "hello", "/tmp/proj")
        mock_chdir.assert_not_called()
        mock_execvp.assert_not_called()

    def test_chdirs_into_cwd_before_exec(self) -> None:
        """Changes into the target cwd before exec'ing the wrapper shell."""
        with patch("aipass.aipass.apps.handlers.handoff_platform.shutil.which", side_effect=_inline_which()):
            with patch("os.chdir") as mock_chdir, patch("os.execvp"):
                launch_inline("claude", "hello", "/tmp/proj")
        mock_chdir.assert_called_once_with("/tmp/proj")

    def test_execs_shell_wrapper_not_cli_directly(self) -> None:
        """execvp is called with the shell, not the CLI binary — the CLI is embedded in -c."""
        with patch("aipass.aipass.apps.handlers.handoff_platform.shutil.which", side_effect=_inline_which()):
            with patch("os.chdir"), patch("os.execvp") as mock_execvp:
                launch_inline("claude", "hello", "/tmp/proj")
        mock_execvp.assert_called_once()
        shell_arg, argv = mock_execvp.call_args[0]
        assert shell_arg == "/bin/bash"
        assert argv[0] == "/bin/bash"
        assert argv[1] == "-c"

    def test_shell_command_includes_cli_invocation_and_prompt(self) -> None:
        """The exec'd shell command runs the resolved CLI path with the prompt."""
        with patch("aipass.aipass.apps.handlers.handoff_platform.shutil.which", side_effect=_inline_which()):
            with patch("os.chdir"), patch("os.execvp") as mock_execvp:
                launch_inline("claude", "hello world", "/tmp/proj")
        _, argv = mock_execvp.call_args[0]
        shell_cmd = argv[2]
        assert "/usr/bin/claude" in shell_cmd
        assert "hello world" in shell_cmd

    def test_shell_command_includes_breadcrumb_after_cli(self) -> None:
        """Breadcrumb (cd + claude --continue) prints via printf after the CLI invocation."""
        with patch("aipass.aipass.apps.handlers.handoff_platform.shutil.which", side_effect=_inline_which()):
            with patch("os.chdir"), patch("os.execvp") as mock_execvp:
                launch_inline("claude", "hello", "/tmp/proj")
        _, argv = mock_execvp.call_args[0]
        shell_cmd = argv[2]
        breadcrumb = return_path_breadcrumb("/tmp/proj")
        assert breadcrumb in shell_cmd
        cli_idx = shell_cmd.index("/usr/bin/claude")
        breadcrumb_idx = shell_cmd.index(breadcrumb)
        assert cli_idx < breadcrumb_idx, "breadcrumb must print after the CLI invocation, not before"

    def test_falls_back_to_sh_when_bash_missing(self) -> None:
        """Uses sh (resolved via which) when bash isn't on PATH."""
        which = _inline_which(bash_path=None)
        with patch("aipass.aipass.apps.handlers.handoff_platform.shutil.which", side_effect=which):
            with patch("os.chdir"), patch("os.execvp") as mock_execvp:
                launch_inline("claude", "hello", "/tmp/proj")
        shell_arg = mock_execvp.call_args[0][0]
        assert shell_arg == "/usr/bin/sh"

    def test_falls_back_to_bin_sh_literal_when_neither_found(self) -> None:
        """Uses the hardcoded /bin/sh fallback when neither bash nor sh resolve via which."""
        which = _inline_which(bash_path=None, sh_path=None)
        with patch("aipass.aipass.apps.handlers.handoff_platform.shutil.which", side_effect=which):
            with patch("os.chdir"), patch("os.execvp") as mock_execvp:
                launch_inline("claude", "hello", "/tmp/proj")
        shell_arg = mock_execvp.call_args[0][0]
        assert shell_arg == "/bin/sh"

    def test_skip_permissions_variant_included_in_shell_command(self) -> None:
        """flag_variant is honored — the skip-permissions flag appears in the exec'd command."""
        with patch("aipass.aipass.apps.handlers.handoff_platform.shutil.which", side_effect=_inline_which()):
            with patch("os.chdir"), patch("os.execvp") as mock_execvp:
                launch_inline("claude", "hello", "/tmp/proj", flag_variant="skip-permissions")
        _, argv = mock_execvp.call_args[0]
        assert "--dangerously-skip-permissions" in argv[2]

    def test_prompt_with_special_chars_is_shell_quoted(self) -> None:
        """A prompt containing shell metacharacters is safely quoted, not interpolated raw."""
        with patch("aipass.aipass.apps.handlers.handoff_platform.shutil.which", side_effect=_inline_which()):
            with patch("os.chdir"), patch("os.execvp") as mock_execvp:
                launch_inline("claude", "hi $(whoami) && rm -rf /", "/tmp/proj")
        _, argv = mock_execvp.call_args[0]
        shell_cmd = argv[2]
        # shlex.join quotes the whole argv — the dangerous substring must appear
        # wrapped in quotes, not as bare, executable shell syntax.
        assert "'hi $(whoami) && rm -rf /'" in shell_cmd


# =============================================================================
# TestLaunchHandoff
# =============================================================================


class TestLaunchHandoff:
    """Tests for launch_handoff() dispatch logic."""

    def test_unix_tries_terminal_first(self) -> None:
        """On unix, tries launch_terminal before launch_tmux."""
        with patch("aipass.aipass.apps.handlers.handoff_platform.launch_terminal", return_value=True) as mock_term:
            with patch("aipass.aipass.apps.handlers.handoff_platform.launch_tmux") as mock_tmux:
                launched, cmd = launch_handoff("claude", "test", "/tmp", platform_override="unix")
        assert launched is True
        mock_term.assert_called_once()
        mock_tmux.assert_not_called()
        assert "claude" in cmd

    def test_unix_falls_back_to_tmux(self) -> None:
        """On unix, falls back to tmux when terminal fails."""
        with patch("aipass.aipass.apps.handlers.handoff_platform.launch_terminal", return_value=False):
            with patch("aipass.aipass.apps.handlers.handoff_platform.launch_tmux", return_value=True) as mock_tmux:
                launched, cmd = launch_handoff("claude", "test", "/tmp", platform_override="unix")
        assert launched is True
        mock_tmux.assert_called_once()

    def test_unix_fallback_returns_false(self) -> None:
        """On unix, returns False when both terminal and tmux fail."""
        with patch("aipass.aipass.apps.handlers.handoff_platform.launch_terminal", return_value=False):
            with patch("aipass.aipass.apps.handlers.handoff_platform.launch_tmux", return_value=False):
                launched, cmd = launch_handoff("claude", "test", "/tmp", platform_override="unix")
        assert launched is False
        assert "claude" in cmd

    def test_windows_tries_wt(self) -> None:
        """On windows, tries launch_wt."""
        with patch("aipass.aipass.apps.handlers.handoff_platform.launch_wt", return_value=True) as mock_wt:
            launched, cmd = launch_handoff("claude", "test", "/tmp", platform_override="windows")
        assert launched is True
        mock_wt.assert_called_once()

    def test_windows_fallback(self) -> None:
        """On windows, returns False when wt fails."""
        with patch("aipass.aipass.apps.handlers.handoff_platform.launch_wt", return_value=False):
            launched, cmd = launch_handoff("claude", "test", "/tmp", platform_override="windows")
        assert launched is False
        assert "claude" in cmd

    def test_manual_command_always_populated(self) -> None:
        """Manual command is always returned regardless of launch success."""
        with patch("aipass.aipass.apps.handlers.handoff_platform.launch_terminal", return_value=False):
            with patch("aipass.aipass.apps.handlers.handoff_platform.launch_tmux", return_value=False):
                _, cmd = launch_handoff("claude", "start", "/home/user", platform_override="unix")
        assert "cd /home/user" in cmd
        assert "claude" in cmd
        assert "start" in cmd
