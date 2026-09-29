# =================== AIPass ====================
# Name: test_handoff_platform.py
# Description: Tests for handoff_platform handler
# Version: 1.1.5
# Created: 2026-05-12
# Modified: 2026-09-29
# =============================================

"""Tests for apps/handlers/handoff_platform/__init__.py and the handoff module it drives."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that apps/handlers/handoff_platform/__init__.py parses and imports
# seedgo: no-test-needed(constant) — IS_WINDOWS, IS_MACOS, IS_LINUX read sys.platform once at import

from __future__ import annotations

import os
import shlex
import subprocess
from unittest.mock import MagicMock, patch

import pytest

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
from aipass.aipass.apps.modules.handoff import handle_command

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

    def test_returns_cd_and_cli(self, tmp_path) -> None:
        """Manual command includes cd and CLI invocation."""
        proj = str(tmp_path / "proj")
        result = build_manual_command("claude", "hello", proj)
        assert f"cd {proj}" in result
        assert "claude" in result
        assert "hello" in result

    def test_escapes_quotes_in_prompt(self, tmp_path) -> None:
        """Double quotes in prompt are escaped."""
        result = build_manual_command("claude", 'say "hi"', str(tmp_path))
        assert '\\"hi\\"' in result

    def test_skip_permissions_in_manual(self, tmp_path) -> None:
        """Manual command includes flag when skip-permissions."""
        result = build_manual_command("claude", "test", str(tmp_path), "skip-permissions")
        assert "--dangerously-skip-permissions" in result


# =============================================================================
# TestReturnPathBreadcrumb
# =============================================================================


class TestReturnPathBreadcrumb:
    """Tests for return_path_breadcrumb()."""

    def test_returns_cd_and_continue(self, tmp_path) -> None:
        """Breadcrumb is `cd <cwd> && claude --continue`.

        Mutant: `f"cd {cwd} && claude --continue"` -> `f"cd . && claude --continue"` reddens this test.
        """
        proj = str(tmp_path / "proj")
        assert return_path_breadcrumb(proj) == f"cd {proj} && claude --continue"

    def test_uses_continue_not_resume(self, tmp_path) -> None:
        """Uses --continue, never --resume <id> — session stores are per-directory,
        so a bare --resume hint (no cwd) fails from anywhere else."""
        result = return_path_breadcrumb(str(tmp_path / "somewhere"))
        assert "--continue" in result
        assert "--resume" not in result

    def test_reflects_the_given_cwd(self, tmp_path) -> None:
        """Different cwd values are reflected verbatim in the breadcrumb."""
        cwd = str(tmp_path / "a" / "b" / "c")
        assert f"cd {cwd} " in return_path_breadcrumb(cwd)


# =============================================================================
# TestFindTerminalEmulator (tested via launch_terminal internals)
# =============================================================================


class TestFindTerminalEmulator:
    """Tests for terminal emulator discovery via launch_terminal."""

    _MOD = "aipass.aipass.apps.handlers.handoff_platform"

    def test_finds_gnome_terminal(self, tmp_path, capsys: pytest.CaptureFixture[str]) -> None:
        """Gnome-terminal is found and used by launch_terminal.

        Mutant: "Opened your agent" confirmation not printed -> red.
        """
        with patch(
            f"{self._MOD}.shutil.which",
            side_effect=lambda x: "/usr/bin/gnome-terminal" if x == "gnome-terminal" else None,
        ):
            with patch(f"{self._MOD}.subprocess.Popen") as mock_popen:
                result = launch_terminal("claude", "test", str(tmp_path))
        assert result is True
        assert "gnome-terminal" in str(mock_popen.call_args)
        out, _err = capsys.readouterr()
        assert "Opened your agent in a new terminal window." in out

    def test_finds_xterm_as_fallback(self, tmp_path, capsys: pytest.CaptureFixture[str]) -> None:
        """Xterm is found when earlier emulators are absent.

        Mutant: "Opened your agent" confirmation not printed -> red.
        """
        with patch(
            f"{self._MOD}.shutil.which",
            side_effect=lambda x: "/usr/bin/xterm" if x == "xterm" else None,
        ):
            with patch(f"{self._MOD}.subprocess.Popen") as mock_popen:
                result = launch_terminal("claude", "test", str(tmp_path))
        assert result is True
        assert "xterm" in str(mock_popen.call_args)
        out, _err = capsys.readouterr()
        assert "Opened your agent in a new terminal window." in out

    def test_returns_false_when_nothing_found(self, tmp_path) -> None:
        """Returns False when no terminal emulator is on PATH."""
        with patch(f"{self._MOD}.shutil.which", return_value=None):
            assert launch_terminal("claude", "test", str(tmp_path)) is False

    def test_finds_konsole(self, tmp_path, capsys: pytest.CaptureFixture[str]) -> None:
        """Konsole is found when available and earlier options are not.

        Mutant: "Opened your agent" confirmation not printed -> red.
        """

        def _konsole_only(name: str) -> str | None:
            """Return path only for konsole."""
            if name == "konsole":
                return "/usr/bin/konsole"
            return None

        with patch(f"{self._MOD}.shutil.which", side_effect=_konsole_only):
            with patch(f"{self._MOD}.subprocess.Popen") as mock_popen:
                result = launch_terminal("claude", "test", str(tmp_path))
        assert result is True
        assert "konsole" in str(mock_popen.call_args)
        out, _err = capsys.readouterr()
        assert "Opened your agent in a new terminal window." in out

    def test_finds_xfce4_terminal(self, tmp_path, capsys: pytest.CaptureFixture[str]) -> None:
        """Xfce4-terminal is found when available.

        Mutant: "Opened your agent" confirmation not printed -> red.
        """

        def _xfce4_only(name: str) -> str | None:
            """Return path only for xfce4-terminal."""
            if name == "xfce4-terminal":
                return "/usr/bin/xfce4-terminal"
            return None

        with patch(f"{self._MOD}.shutil.which", side_effect=_xfce4_only):
            with patch(f"{self._MOD}.subprocess.Popen") as mock_popen:
                result = launch_terminal("claude", "test", str(tmp_path))
        assert result is True
        assert "xfce4-terminal" in str(mock_popen.call_args)
        out, _err = capsys.readouterr()
        assert "Opened your agent in a new terminal window." in out


# =============================================================================
# TestLaunchTerminal
# =============================================================================


class TestLaunchTerminal:
    """Tests for launch_terminal()."""

    def test_returns_false_when_no_emulator(self, tmp_path) -> None:
        """Returns False when no terminal emulator is found."""
        with patch("aipass.aipass.apps.handlers.handoff_platform._find_terminal_emulator", return_value=None):
            assert launch_terminal("claude", "test", str(tmp_path)) is False

    def test_gnome_terminal_launches(self, tmp_path, capsys: pytest.CaptureFixture[str]) -> None:
        """Returns True when gnome-terminal Popen succeeds.

        Mutant: "Opened your agent" confirmation not printed -> red.
        """
        with patch(
            "aipass.aipass.apps.handlers.handoff_platform._find_terminal_emulator", return_value="gnome-terminal"
        ):
            with patch("aipass.aipass.apps.handlers.handoff_platform.subprocess.Popen"):
                assert launch_terminal("claude", "test", str(tmp_path)) is True
        out, _err = capsys.readouterr()
        assert "Opened your agent in a new terminal window." in out

    def test_xfce4_terminal_launches(self, tmp_path, capsys: pytest.CaptureFixture[str]) -> None:
        """Returns True when xfce4-terminal Popen succeeds.

        Mutant: "Opened your agent" confirmation not printed -> red.
        """
        with patch(
            "aipass.aipass.apps.handlers.handoff_platform._find_terminal_emulator", return_value="xfce4-terminal"
        ):
            with patch("aipass.aipass.apps.handlers.handoff_platform.subprocess.Popen"):
                assert launch_terminal("claude", "test", str(tmp_path)) is True
        out, _err = capsys.readouterr()
        assert "Opened your agent in a new terminal window." in out

    def test_konsole_launches(self, tmp_path, capsys: pytest.CaptureFixture[str]) -> None:
        """Returns True when konsole Popen succeeds.

        Mutant: "Opened your agent" confirmation not printed -> red.
        """
        with patch("aipass.aipass.apps.handlers.handoff_platform._find_terminal_emulator", return_value="konsole"):
            with patch("aipass.aipass.apps.handlers.handoff_platform.subprocess.Popen"):
                assert launch_terminal("claude", "test", str(tmp_path)) is True
        out, _err = capsys.readouterr()
        assert "Opened your agent in a new terminal window." in out

    def test_xterm_launches(self, tmp_path, capsys: pytest.CaptureFixture[str]) -> None:
        """Returns True when xterm Popen succeeds.

        Mutant: "Opened your agent" confirmation not printed -> red.
        """
        with patch("aipass.aipass.apps.handlers.handoff_platform._find_terminal_emulator", return_value="xterm"):
            with patch("aipass.aipass.apps.handlers.handoff_platform.subprocess.Popen"):
                assert launch_terminal("claude", "test", str(tmp_path)) is True
        out, _err = capsys.readouterr()
        assert "Opened your agent in a new terminal window." in out

    def test_unknown_terminal_returns_false(self, tmp_path) -> None:
        """Returns False for an unrecognized terminal emulator."""
        with patch("aipass.aipass.apps.handlers.handoff_platform._find_terminal_emulator", return_value="unknown-term"):
            assert launch_terminal("claude", "test", str(tmp_path)) is False

    def test_oserror_returns_false(self, tmp_path) -> None:
        """Returns False when Popen raises OSError."""
        with patch(
            "aipass.aipass.apps.handlers.handoff_platform._find_terminal_emulator", return_value="gnome-terminal"
        ):
            with patch("aipass.aipass.apps.handlers.handoff_platform.subprocess.Popen", side_effect=OSError("fail")):
                assert launch_terminal("claude", "test", str(tmp_path)) is False


# =============================================================================
# TestLaunchTmux
# =============================================================================


def _path_with(monkeypatch, tmp_path, *names: str) -> None:
    """PATH holds only a tmp bin dir with these executables, so shutil.which answers from it."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    for name in names:
        exe = bin_dir / (name + (".exe" if os.name == "nt" else ""))
        exe.write_text("", encoding="utf-8")
        exe.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir))


class TestLaunchTmux:
    """Tests for launch_tmux()."""

    def test_returns_false_when_tmux_not_found(self, tmp_path, monkeypatch) -> None:
        """Returns False when tmux is not on PATH.

        Mutant: `if not shutil.which("tmux"):` -> `if False:` reddens this test.
        """
        _path_with(monkeypatch, tmp_path)
        with patch("aipass.aipass.apps.handlers.handoff_platform.subprocess.run") as mock_run:
            assert launch_tmux("claude", "test", str(tmp_path)) is False
        mock_run.assert_not_called()

    def test_success_returns_true(self, tmp_path, monkeypatch, capsys: pytest.CaptureFixture[str]) -> None:
        """Returns True when tmux commands succeed.

        Mutant: "tmux attach" instruction not printed -> red.
        """
        _path_with(monkeypatch, tmp_path, "tmux")
        with patch("aipass.aipass.apps.handlers.handoff_platform.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            assert launch_tmux("claude", "test", str(tmp_path)) is True
        out, _err = capsys.readouterr()
        assert "tmux attach -t" in out

    def test_called_process_error_returns_false(self, tmp_path, monkeypatch) -> None:
        """Returns False when tmux new-session fails."""
        _path_with(monkeypatch, tmp_path, "tmux")
        with patch(
            "aipass.aipass.apps.handlers.handoff_platform.subprocess.run",
            side_effect=[MagicMock(), subprocess.CalledProcessError(1, "tmux")],
        ):
            assert launch_tmux("claude", "test", str(tmp_path)) is False

    def test_timeout_returns_false(self, tmp_path, monkeypatch) -> None:
        """Returns False when tmux command times out."""
        _path_with(monkeypatch, tmp_path, "tmux")
        with patch(
            "aipass.aipass.apps.handlers.handoff_platform.subprocess.run",
            side_effect=[MagicMock(), subprocess.TimeoutExpired("tmux", 10)],
        ):
            assert launch_tmux("claude", "test", str(tmp_path)) is False


# =============================================================================
# TestLaunchWt
# =============================================================================


class TestLaunchWt:
    """Tests for launch_wt()."""

    def test_returns_false_when_wt_not_found(self, tmp_path, monkeypatch) -> None:
        """Returns False when wt.exe is not on PATH.

        Mutant: `if not shutil.which("wt"):` -> `if False:` reddens this test.
        """
        _path_with(monkeypatch, tmp_path)
        with patch("aipass.aipass.apps.handlers.handoff_platform.subprocess.run") as mock_run:
            assert launch_wt("claude", "test", str(tmp_path)) is False
        mock_run.assert_not_called()

    def test_success_returns_true(self, tmp_path, monkeypatch) -> None:
        """Returns True when wt.exe runs successfully."""
        _path_with(monkeypatch, tmp_path, "wt")
        with patch("aipass.aipass.apps.handlers.handoff_platform.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            assert launch_wt("claude", "test", str(tmp_path)) is True

    def test_called_process_error_returns_false(self, tmp_path, monkeypatch) -> None:
        """Returns False when wt.exe fails."""
        _path_with(monkeypatch, tmp_path, "wt")
        with patch(
            "aipass.aipass.apps.handlers.handoff_platform.subprocess.run",
            side_effect=subprocess.CalledProcessError(1, "wt"),
        ):
            assert launch_wt("claude", "test", str(tmp_path)) is False

    def test_timeout_returns_false(self, tmp_path, monkeypatch) -> None:
        """Returns False when wt.exe times out."""
        _path_with(monkeypatch, tmp_path, "wt")
        with patch(
            "aipass.aipass.apps.handlers.handoff_platform.subprocess.run",
            side_effect=subprocess.TimeoutExpired("wt", 15),
        ):
            assert launch_wt("claude", "test", str(tmp_path)) is False


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

    ``launch_inline`` ends in ``execvp`` (process replacement), so every test hands
    in three recorders for which, chdir and execvp through its seam and patches
    nothing of os or shutil (fleet green leg 4): a real chdir or execvp would move
    the run or replace the test process itself.
    """

    @staticmethod
    def _launch(proj: str, prompt: str = "hello", which=None, **kwargs) -> tuple[MagicMock, MagicMock]:
        """Run launch_inline on recorders; return the (chdir, execvp) recorders."""
        chdir, execvp = MagicMock(), MagicMock()
        launch_inline("claude", prompt, proj, which=which or _inline_which(), chdir=chdir, execvp=execvp, **kwargs)
        return chdir, execvp

    def test_returns_without_exec_when_cli_not_found(self, tmp_path) -> None:
        """No CLI on PATH — logs and returns, never touches chdir/execvp."""
        chdir, execvp = self._launch(str(tmp_path / "proj"), which=_inline_which(cli_path=None))
        chdir.assert_not_called()
        execvp.assert_not_called()

    def test_chdirs_into_cwd_before_exec(self, tmp_path) -> None:
        """Changes into the target cwd before exec'ing the wrapper shell."""
        proj = str(tmp_path / "proj")
        order = MagicMock()
        launch_inline("claude", "hello", proj, which=_inline_which(), chdir=order.chdir, execvp=order.execvp)
        assert [c[0] for c in order.mock_calls] == ["chdir", "execvp"]
        order.chdir.assert_called_once_with(proj)

    def test_execs_shell_wrapper_not_cli_directly(self, tmp_path) -> None:
        """execvp is called with the shell, not the CLI binary — the CLI is embedded in -c."""
        _, execvp = self._launch(str(tmp_path / "proj"))
        execvp.assert_called_once()
        shell_arg, argv = execvp.call_args[0]
        assert shell_arg == "/bin/bash"
        assert argv[0] == "/bin/bash"
        assert argv[1] == "-c"

    def test_shell_command_includes_cli_invocation_and_prompt(self, tmp_path) -> None:
        """The exec'd shell command runs the resolved CLI path with the prompt."""
        _, execvp = self._launch(str(tmp_path / "proj"), prompt="hello world")
        _, argv = execvp.call_args[0]
        shell_cmd = argv[2]
        assert "/usr/bin/claude" in shell_cmd
        assert "hello world" in shell_cmd

    def test_shell_command_includes_breadcrumb_after_cli(self, tmp_path) -> None:
        """Breadcrumb (cd + claude --continue) prints via printf after the CLI invocation.

        The breadcrumb holds spaces and `&&`, so the command must end with it as one
        shell-quoted word: unquoted, the shell runs `cd <proj>` and `claude --continue`
        itself instead of printing them.
        Mutant (fleet green leg 5): `shlex.quote(breadcrumb)` -> `breadcrumb` -> red at the endswith assert.
        """
        proj = str(tmp_path / "proj")
        _, execvp = self._launch(proj)
        _, argv = execvp.call_args[0]
        shell_cmd = argv[2]
        breadcrumb = return_path_breadcrumb(proj)
        assert shell_cmd.endswith(f"printf '\\n%s\\n' {shlex.quote(breadcrumb)}")
        assert breadcrumb in shell_cmd
        cli_idx = shell_cmd.index("/usr/bin/claude")
        breadcrumb_idx = shell_cmd.index(breadcrumb)
        assert cli_idx < breadcrumb_idx, "breadcrumb must print after the CLI invocation, not before"

    def test_falls_back_to_sh_when_bash_missing(self, tmp_path) -> None:
        """Uses sh (resolved via which) when bash isn't on PATH."""
        _, execvp = self._launch(str(tmp_path / "proj"), which=_inline_which(bash_path=None))
        shell_arg = execvp.call_args[0][0]
        assert shell_arg == "/usr/bin/sh"

    def test_falls_back_to_bin_sh_literal_when_neither_found(self, tmp_path) -> None:
        """Uses the hardcoded /bin/sh fallback when neither bash nor sh resolve via which."""
        _, execvp = self._launch(str(tmp_path / "proj"), which=_inline_which(bash_path=None, sh_path=None))
        shell_arg = execvp.call_args[0][0]
        assert shell_arg == "/bin/sh"

    def test_skip_permissions_variant_included_in_shell_command(self, tmp_path) -> None:
        """flag_variant is honored — the skip-permissions flag appears in the exec'd command."""
        _, execvp = self._launch(str(tmp_path / "proj"), flag_variant="skip-permissions")
        _, argv = execvp.call_args[0]
        assert "--dangerously-skip-permissions" in argv[2]

    def test_prompt_with_special_chars_is_shell_quoted(self, tmp_path) -> None:
        """A prompt containing shell metacharacters is safely quoted, not interpolated raw."""
        _, execvp = self._launch(str(tmp_path / "proj"), prompt="hi $(whoami) && rm -rf /")
        _, argv = execvp.call_args[0]
        shell_cmd = argv[2]
        # shlex.join quotes the whole argv — the dangerous substring must appear
        # wrapped in quotes, not as bare, executable shell syntax.
        assert "'hi $(whoami) && rm -rf /'" in shell_cmd


# =============================================================================
# TestLaunchHandoff
# =============================================================================


class TestLaunchHandoff:
    """Tests for launch_handoff() dispatch logic."""

    def test_unix_tries_terminal_first(self, tmp_path) -> None:
        """On unix, tries launch_terminal before launch_tmux."""
        with patch("aipass.aipass.apps.handlers.handoff_platform.launch_terminal", return_value=True) as mock_term:
            with patch("aipass.aipass.apps.handlers.handoff_platform.launch_tmux") as mock_tmux:
                launched, cmd = launch_handoff("claude", "test", str(tmp_path), platform_override="unix")
        assert launched is True
        mock_term.assert_called_once()
        mock_tmux.assert_not_called()
        assert "claude" in cmd

    def test_unix_falls_back_to_tmux(self, tmp_path) -> None:
        """On unix, falls back to tmux when terminal fails."""
        with patch("aipass.aipass.apps.handlers.handoff_platform.launch_terminal", return_value=False):
            with patch("aipass.aipass.apps.handlers.handoff_platform.launch_tmux", return_value=True) as mock_tmux:
                launched, cmd = launch_handoff("claude", "test", str(tmp_path), platform_override="unix")
        assert launched is True
        mock_tmux.assert_called_once()

    def test_unix_fallback_returns_false(self, tmp_path) -> None:
        """On unix, returns False when both terminal and tmux fail."""
        with patch("aipass.aipass.apps.handlers.handoff_platform.launch_terminal", return_value=False):
            with patch("aipass.aipass.apps.handlers.handoff_platform.launch_tmux", return_value=False):
                launched, cmd = launch_handoff("claude", "test", str(tmp_path), platform_override="unix")
        assert launched is False
        assert "claude" in cmd

    def test_windows_tries_wt(self, tmp_path) -> None:
        """On windows, tries launch_wt."""
        with patch("aipass.aipass.apps.handlers.handoff_platform.launch_wt", return_value=True) as mock_wt:
            launched, cmd = launch_handoff("claude", "test", str(tmp_path), platform_override="windows")
        assert launched is True
        mock_wt.assert_called_once()

    def test_windows_fallback(self, tmp_path) -> None:
        """On windows, returns False when wt fails."""
        with patch("aipass.aipass.apps.handlers.handoff_platform.launch_wt", return_value=False):
            launched, cmd = launch_handoff("claude", "test", str(tmp_path), platform_override="windows")
        assert launched is False
        assert "claude" in cmd

    def test_manual_command_always_populated(self, tmp_path) -> None:
        """Manual command is always returned regardless of launch success."""
        home = str(tmp_path)
        with patch("aipass.aipass.apps.handlers.handoff_platform.launch_terminal", return_value=False):
            with patch("aipass.aipass.apps.handlers.handoff_platform.launch_tmux", return_value=False):
                _, cmd = launch_handoff("claude", "start", home, platform_override="unix")
        assert f"cd {home}" in cmd
        assert "claude" in cmd
        assert "start" in cmd


class TestHandoffCommandRefusal:
    """The `aipass handoff launch` refusal seam.

    Lives here rather than in a file of its own: the test-write gate refuses new
    test files, and this is the existing home of handoff coverage. Added
    2026-09-07 (FPLAN-0492 wave 6) -- canary's sweep named handoff.py:152 as a
    refusal that exited 0, and it had NO test at all, so nothing pinned either
    the old outcome or the new one.
    """

    def test_unknown_cli_refuses_non_zero(self) -> None:
        """An unrecognised CLI launches nothing, so it cannot exit 0.

        Note the invocation: the refusal is reachable only through `--cli <bad>`.
        A bare positional is discarded by _parse_launch_args, which leaves the
        default 'claude' in place and launches normally.
        """
        with patch("aipass.aipass.apps.modules.handoff.error") as err:
            with patch("aipass.aipass.apps.modules.handoff.do_handoff") as did:
                with pytest.raises(SystemExit) as exc:
                    handle_command("handoff", ["launch", "--cli", "banana"])

        assert exc.value.code == 1
        did.assert_not_called()
        assert "banana" in err.call_args[0][0]

    def test_known_cli_still_launches(self, tmp_path) -> None:
        """The counterfactual: a valid CLI is unaffected by the refusal seam.

        Mutant: `elif args[i] == "--cwd"` -> `"--cwdx"` (--cwd never read) -> red.
        Mutant: `elif args[i] == "--flag"` -> `"--flagx"` (--flag never read) -> red.
        """
        argv = ["launch", "--cli", "claude", "--cwd", str(tmp_path), "--flag", "skip-permissions"]
        with patch("aipass.aipass.apps.modules.handoff.do_handoff") as did:
            assert handle_command("handoff", argv) is True

        did.assert_called_once_with(cli="claude", cwd=str(tmp_path), flag_variant="skip-permissions")
