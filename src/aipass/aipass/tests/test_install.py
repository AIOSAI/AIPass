# =================== AIPass ====================
# Name: test_install.py
# Description: Tests for aipass install — one-command bootstrap (DPLAN-0233)
# Version: 1.0.0
# Created: 2026-07-05
# Modified: 2026-07-05
# =============================================

"""Tests for the aipass install module (DPLAN-0233)."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from aipass.aipass.apps.modules.install import (
    DEFAULT_HOME,
    TOTAL_STEPS,
    _ask_permission_mode,
    _build_install_prompt,
    _clone_repo,
    _end_in_chat,
    _looks_like_aipass_tree,
    _print_next_steps,
    _resolve_home,
    _run_setup,
    handle_command,
    print_help,
    print_introspection,
    run_chat_only,
    run_install,
)

_MOD = "aipass.aipass.apps.modules.install"


class TestLooksLikeAipassTree:
    """Detecting whether a directory already holds an AIPass source tree."""

    def test_setup_sh_present(self, tmp_path: Path) -> None:
        """A directory with setup.sh reads as an AIPass tree."""
        (tmp_path / "setup.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
        assert _looks_like_aipass_tree(tmp_path) is True

    def test_registry_present(self, tmp_path: Path) -> None:
        """A directory with a *_REGISTRY.json reads as an AIPass tree."""
        (tmp_path / "MYPROJ_REGISTRY.json").write_text("{}", encoding="utf-8")
        assert _looks_like_aipass_tree(tmp_path) is True

    def test_empty_dir(self, tmp_path: Path) -> None:
        """An empty directory is not an AIPass tree."""
        assert _looks_like_aipass_tree(tmp_path) is False

    def test_missing_dir(self, tmp_path: Path) -> None:
        """A non-existent path is not an AIPass tree."""
        assert _looks_like_aipass_tree(tmp_path / "nope") is False


class TestResolveHome:
    """Resolving the install home from flags, env, and defaults."""

    def test_here_returns_cwd(self, tmp_path: Path) -> None:
        """--here resolves to the current working directory."""
        with patch(f"{_MOD}.Path.cwd", return_value=tmp_path):
            assert _resolve_home(None, here=True, non_interactive=False) == tmp_path.resolve()

    def test_explicit_path(self, tmp_path: Path) -> None:
        """An explicit --path is expanded and resolved."""
        target = tmp_path / "tools" / "aipass"
        assert _resolve_home(str(target), here=False, non_interactive=False) == target.resolve()

    def test_non_interactive_defaults(self) -> None:
        """With no AIPASS_HOME, non-interactive falls back to DEFAULT_HOME."""
        with patch.dict("os.environ", {"AIPASS_HOME": ""}, clear=False):
            assert _resolve_home(None, here=False, non_interactive=True) == DEFAULT_HOME.resolve()

    def test_uses_valid_env(self, tmp_path: Path) -> None:
        """A valid AIPASS_HOME pointing at a real tree is honoured."""
        (tmp_path / "setup.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
        with patch.dict("os.environ", {"AIPASS_HOME": str(tmp_path)}, clear=False):
            assert _resolve_home(None, here=False, non_interactive=True) == tmp_path.resolve()

    def test_ignores_invalid_env(self, tmp_path: Path) -> None:
        """An AIPASS_HOME that is not an AIPass tree is ignored for the default."""
        with patch.dict("os.environ", {"AIPASS_HOME": str(tmp_path)}, clear=False):
            assert _resolve_home(None, here=False, non_interactive=True) == DEFAULT_HOME.resolve()


class TestCloneRepo:
    """Fetching the framework into the home via git clone."""

    def test_dry_run_no_subprocess(self, tmp_path: Path) -> None:
        """Dry-run reports success without shelling out."""
        with patch(f"{_MOD}.subprocess.run") as run:
            assert _clone_repo(tmp_path / "home", dry_run=True) is True
            run.assert_not_called()

    def test_refuses_non_empty_dir(self, tmp_path: Path) -> None:
        """A non-empty target is refused rather than clobbered."""
        (tmp_path / "existing.txt").write_text("x", encoding="utf-8")
        with patch(f"{_MOD}.subprocess.run") as run:
            assert _clone_repo(tmp_path, dry_run=False) is False
            run.assert_not_called()

    def test_missing_git(self, tmp_path: Path) -> None:
        """Absent git means clone fails cleanly without calling subprocess."""
        with patch(f"{_MOD}.shutil.which", return_value=None), patch(f"{_MOD}.subprocess.run") as run:
            assert _clone_repo(tmp_path / "home", dry_run=False) is False
            run.assert_not_called()

    def test_success(self, tmp_path: Path) -> None:
        """A zero-exit git clone returns success."""
        with (
            patch(f"{_MOD}.shutil.which", return_value="/usr/bin/git"),
            patch(f"{_MOD}.subprocess.run", return_value=MagicMock(returncode=0)) as run,
        ):
            assert _clone_repo(tmp_path / "home", dry_run=False) is True
            run.assert_called_once()

    def test_nonzero_exit(self, tmp_path: Path) -> None:
        """A non-zero git clone exit reports failure."""
        with (
            patch(f"{_MOD}.shutil.which", return_value="/usr/bin/git"),
            patch(f"{_MOD}.subprocess.run", return_value=MagicMock(returncode=1)),
        ):
            assert _clone_repo(tmp_path / "home", dry_run=False) is False


class TestRunSetup:
    """Running the repo setup.sh."""

    def test_dry_run_no_subprocess(self, tmp_path: Path) -> None:
        """Dry-run reports success without running setup.sh."""
        (tmp_path / "setup.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
        with patch(f"{_MOD}.subprocess.run") as run:
            assert _run_setup(tmp_path, dry_run=True) is True
            run.assert_not_called()

    def test_missing_script(self, tmp_path: Path) -> None:
        """A missing setup.sh reports failure."""
        assert _run_setup(tmp_path, dry_run=False) is False

    def test_success(self, tmp_path: Path) -> None:
        """A zero-exit setup.sh returns success."""
        (tmp_path / "setup.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
        with patch(f"{_MOD}.subprocess.run", return_value=MagicMock(returncode=0)) as run:
            assert _run_setup(tmp_path, dry_run=False) is True
            run.assert_called_once()

    def test_no_symlink_flag_forwarded(self, tmp_path: Path) -> None:
        """--no-symlink passes through to setup.sh (#660)."""
        (tmp_path / "setup.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
        with patch(f"{_MOD}.subprocess.run", return_value=MagicMock(returncode=0)) as run:
            assert _run_setup(tmp_path, dry_run=False, no_symlink=True) is True
        argv = run.call_args[0][0]
        assert "--no-symlink" in argv
        assert "--force-symlink" not in argv

    def test_force_symlink_flag_forwarded(self, tmp_path: Path) -> None:
        """--force-symlink passes through to setup.sh (#660)."""
        (tmp_path / "setup.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
        with patch(f"{_MOD}.subprocess.run", return_value=MagicMock(returncode=0)) as run:
            assert _run_setup(tmp_path, dry_run=False, force_symlink=True) is True
        argv = run.call_args[0][0]
        assert "--force-symlink" in argv

    def test_symlink_flags_absent_by_default(self, tmp_path: Path) -> None:
        """No symlink flags forwarded unless requested (#660)."""
        (tmp_path / "setup.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
        with patch(f"{_MOD}.subprocess.run", return_value=MagicMock(returncode=0)) as run:
            assert _run_setup(tmp_path, dry_run=False) is True
        argv = run.call_args[0][0]
        assert "--no-symlink" not in argv
        assert "--force-symlink" not in argv


class TestRunInstall:
    """The four-step orchestrator."""

    def test_dry_run_is_side_effect_free(self) -> None:
        """Dry-run walks all steps and touches no subprocess."""
        with patch(f"{_MOD}.subprocess.run") as run:
            rc = run_install(non_interactive=True, dry_run=True)
        assert rc == 0
        run.assert_not_called()

    def test_aborts_when_clone_fails(self, tmp_path: Path) -> None:
        """A failed fetch aborts before the setup step runs."""
        home = tmp_path / "AIPass"
        with (
            patch(f"{_MOD}._resolve_home", return_value=home),
            patch(f"{_MOD}._clone_repo", return_value=False),
            patch(f"{_MOD}._run_setup") as setup,
        ):
            rc = run_install(non_interactive=True, dry_run=False)
        assert rc == 1
        setup.assert_not_called()

    def test_full_happy_path(self, tmp_path: Path) -> None:
        """Clone + setup + verify + owner check + next-steps returns success."""
        home = tmp_path / "AIPass"
        with (
            patch(f"{_MOD}._resolve_home", return_value=home),
            patch(f"{_MOD}.is_throwaway_path", return_value=False),
            patch(f"{_MOD}._clone_repo", return_value=True),
            patch(f"{_MOD}._run_setup", return_value=True),
            patch(f"{_MOD}._verify_binaries", return_value={"drone": "/x/drone", "aipass": "/x/aipass"}),
            patch(f"{_MOD}._check_and_fix_owner"),
            patch(f"{_MOD}._end_in_chat") as nxt,
        ):
            rc = run_install(non_interactive=True, dry_run=False)
        assert rc == 0
        nxt.assert_called_once()


class TestHandleCommand:
    """Command routing for `aipass install`."""

    def test_ignores_other_commands(self) -> None:
        """A non-install command is not handled here."""
        assert handle_command("doctor", []) is False

    def test_help(self) -> None:
        """--help is handled without exiting."""
        assert handle_command("install", ["--help"]) is True

    def test_info(self) -> None:
        """--info is handled without exiting."""
        assert handle_command("install", ["--info"]) is True

    def test_runs_and_exits(self) -> None:
        """A run request calls run_install and exits with its code."""
        with patch(f"{_MOD}.run_install", return_value=0) as run:
            with pytest.raises(SystemExit) as exc:
                handle_command("install", ["--dry-run", "--non-interactive"])
        assert exc.value.code == 0
        run.assert_called_once()

    def test_passes_path_flag(self) -> None:
        """--path and --non-interactive are threaded into run_install."""
        target = str(Path.home() / "custom-aipass-home")
        with patch(f"{_MOD}.run_install", return_value=0) as run:
            with pytest.raises(SystemExit):
                handle_command("install", ["--path", target, "--non-interactive"])
        _, kwargs = run.call_args
        assert kwargs["path"] == target
        assert kwargs["non_interactive"] is True

    def test_passes_no_chat_flag(self) -> None:
        """--no-chat is threaded into run_install."""
        with patch(f"{_MOD}.run_install", return_value=0) as run:
            with pytest.raises(SystemExit):
                handle_command("install", ["--no-chat"])
        _, kwargs = run.call_args
        assert kwargs["no_chat"] is True

    def test_chat_only_routes_to_run_chat_only(self) -> None:
        """--chat-only routes to run_chat_only instead of run_install."""
        with (
            patch(f"{_MOD}.run_chat_only", return_value=0) as chat_only,
            patch(f"{_MOD}.run_install") as install,
        ):
            with pytest.raises(SystemExit) as exc:
                handle_command("install", ["--chat-only", "--here"])
        assert exc.value.code == 0
        chat_only.assert_called_once()
        install.assert_not_called()
        assert chat_only.call_args.kwargs["here"] is True


class TestBuildInstallPrompt:
    """Authored first prompt for the post-install @aipass chat."""

    def test_includes_home(self, tmp_path: Path) -> None:
        """Prompt mentions the install home directory."""
        prompt = _build_install_prompt(tmp_path, {"drone": "/x/drone", "aipass": "/x/aipass"})
        assert str(tmp_path) in prompt

    def test_includes_verified_bins(self) -> None:
        """Verified binary paths appear in the prompt."""
        prompt = _build_install_prompt(Path("/h"), {"drone": "/x/drone", "aipass": "/x/aipass"})
        assert "/x/drone" in prompt
        assert "/x/aipass" in prompt

    def test_omits_none_bins(self) -> None:
        """Binaries that weren't found are omitted, not shown as None."""
        prompt = _build_install_prompt(Path("/h"), {"drone": None, "aipass": "/x/aipass"})
        assert "None" not in prompt
        assert "/x/aipass" in prompt

    def test_ends_with_question(self) -> None:
        """Prompt ends by asking what to explore."""
        prompt = _build_install_prompt(Path("/h"), {})
        assert "?" in prompt


class TestEndInChat:
    """The Step 4 welcome-chat ending — TTY-gated, no project creation."""

    _BINS = {"drone": "/x/drone", "aipass": "/x/aipass"}

    def test_tty_launches_inline(self) -> None:
        """Interactive TTY launches the @aipass concierge with the install prompt."""
        home = Path("/fake/AIPass")
        with (
            patch(f"{_MOD}.sys.stdin") as mock_stdin,
            patch(f"{_MOD}._ask_permission_mode", return_value="default"),
            patch("aipass.aipass.apps.handlers.handoff_platform.launch_inline") as mock_launch,
        ):
            mock_stdin.isatty.return_value = True
            _end_in_chat(home, self._BINS, dry_run=False, no_chat=False)
        mock_launch.assert_called_once()
        prompt_arg = mock_launch.call_args[0][1]
        assert "Fresh AIPass install" in prompt_arg

    def test_permission_choice_threads_into_launch(self) -> None:
        """Choosing bypass permissions launches claude with the skip-permissions variant."""
        home = Path("/fake/AIPass")
        with (
            patch(f"{_MOD}.sys.stdin") as mock_stdin,
            patch(f"{_MOD}._ask_permission_mode", return_value="skip-permissions"),
            patch("aipass.aipass.apps.handlers.handoff_platform.launch_inline") as mock_launch,
        ):
            mock_stdin.isatty.return_value = True
            _end_in_chat(home, self._BINS, dry_run=False, no_chat=False)
        assert mock_launch.call_args[0][3] == "skip-permissions"

    def test_no_tty_skips_launch(self) -> None:
        """Non-TTY skips the chat launch."""
        home = Path("/fake/AIPass")
        with (
            patch(f"{_MOD}.sys.stdin") as mock_stdin,
            patch("aipass.aipass.apps.handlers.handoff_platform.launch_inline") as mock_launch,
        ):
            mock_stdin.isatty.return_value = False
            _end_in_chat(home, self._BINS, dry_run=False, no_chat=False)
        mock_launch.assert_not_called()

    def test_no_chat_skips_launch_even_on_tty(self) -> None:
        """--no-chat skips the launch even when the shell is interactive."""
        home = Path("/fake/AIPass")
        with (
            patch(f"{_MOD}.sys.stdin") as mock_stdin,
            patch("aipass.aipass.apps.handlers.handoff_platform.launch_inline") as mock_launch,
        ):
            mock_stdin.isatty.return_value = True
            _end_in_chat(home, self._BINS, dry_run=False, no_chat=True)
        mock_launch.assert_not_called()

    def test_dry_run_skips_launch(self) -> None:
        """Dry-run announces the launch but never calls it."""
        home = Path("/fake/AIPass")
        with (
            patch(f"{_MOD}.sys.stdin") as mock_stdin,
            patch("aipass.aipass.apps.handlers.handoff_platform.launch_inline") as mock_launch,
        ):
            mock_stdin.isatty.return_value = True
            _end_in_chat(home, self._BINS, dry_run=True, no_chat=False)
        mock_launch.assert_not_called()


class TestAskPermissionMode:
    """The launch-mode selector shown before the concierge chat."""

    def test_choice_2_is_bypass(self) -> None:
        """Typing 2 selects the skip-permissions launch variant."""
        with patch(f"{_MOD}._prompt", return_value="2"):
            assert _ask_permission_mode() == "skip-permissions"

    def test_enter_defaults_to_accept_edits(self) -> None:
        """Enter (the prompt default) keeps the plain launch."""
        with patch(f"{_MOD}._prompt", return_value="1"):
            assert _ask_permission_mode() == "default"

    def test_garbage_defaults_to_accept_edits(self) -> None:
        """Anything that isn't 2 keeps the safe default."""
        with patch(f"{_MOD}._prompt", return_value="yes please"):
            assert _ask_permission_mode() == "default"

    def test_ctrl_c_defaults_to_accept_edits(self) -> None:
        """Ctrl-C / EOF at the selector keeps the safe default, no raise."""
        with patch(f"{_MOD}._prompt", side_effect=KeyboardInterrupt):
            assert _ask_permission_mode() == "default"


class TestPrintNextSteps:
    """The installed banner shown before the welcome chat."""

    def test_runs_without_error(self, tmp_path: Path) -> None:
        """Renders without raising for a real path."""
        _print_next_steps(tmp_path)


class TestRunChatOnly:
    """setup.sh's tail calls into `aipass install --chat-only` for this."""

    def test_resolves_home_and_ends_in_chat(self, tmp_path: Path) -> None:
        """Resolves the already-built home and hands off to _end_in_chat."""
        with (
            patch(f"{_MOD}._resolve_home", return_value=tmp_path),
            patch(f"{_MOD}._verify_binaries", return_value={"drone": "/x/drone", "aipass": "/x/aipass"}),
            patch(f"{_MOD}._end_in_chat") as end_chat,
        ):
            rc = run_chat_only(non_interactive=True, here=True)
        assert rc == 0
        end_chat.assert_called_once()
        assert end_chat.call_args[0][0] == tmp_path

    def test_dry_run_skips_binary_verification(self, tmp_path: Path) -> None:
        """Dry-run doesn't shell out to verify binaries."""
        with (
            patch(f"{_MOD}._resolve_home", return_value=tmp_path),
            patch(f"{_MOD}._verify_binaries") as verify,
            patch(f"{_MOD}._end_in_chat"),
        ):
            rc = run_chat_only(non_interactive=True, dry_run=True)
        assert rc == 0
        verify.assert_not_called()

    def test_cancelled_returns_1(self, tmp_path: Path) -> None:
        """Ctrl-C during home resolution is reported, not raised."""
        with (
            patch(f"{_MOD}._resolve_home", side_effect=KeyboardInterrupt),
            patch(f"{_MOD}._end_in_chat") as end_chat,
        ):
            rc = run_chat_only(non_interactive=True)
        assert rc == 1
        end_chat.assert_not_called()


class TestSmoke:
    """Help/introspection render and constants hold."""

    def test_print_help_runs(self) -> None:
        """print_help renders without error."""
        print_help()

    def test_print_introspection_runs(self) -> None:
        """print_introspection renders without error."""
        print_introspection()

    def test_total_steps_constant(self) -> None:
        """The install flow advertises four steps."""
        assert TOTAL_STEPS == 4


# ---------------------------------------------------------------------------
# Throwaway-path gate (#688)
# ---------------------------------------------------------------------------


class TestThrowawayGate:
    """Install refuses throwaway homes unless --force-global-home."""

    def test_refuses_tmp_home(self, tmp_path) -> None:
        """run_install returns 1 when home resolves to a temp path."""
        with (
            patch(
                "aipass.aipass.apps.modules.install._resolve_home",
                return_value=tmp_path,
            ),
            patch("aipass.aipass.apps.modules.install.sys.argv", ["aipass", "install"]),
        ):
            result = run_install(non_interactive=True)
        assert result == 1

    def test_force_flag_overrides(self, tmp_path) -> None:
        """--force-global-home lets a temp home proceed past the gate."""
        with (
            patch(
                "aipass.aipass.apps.modules.install._resolve_home",
                return_value=tmp_path,
            ),
            patch(
                "aipass.aipass.apps.modules.install.sys.argv",
                ["aipass", "install", "--force-global-home"],
            ),
            patch(
                "aipass.aipass.apps.modules.install._looks_like_aipass_tree",
                return_value=True,
            ),
            patch(
                "aipass.aipass.apps.modules.install._run_setup",
                return_value=True,
            ),
            patch(
                "aipass.aipass.apps.modules.install._verify_binaries",
                return_value={"drone": "x", "aipass": "x"},
            ),
            patch("aipass.aipass.apps.modules.install._end_in_chat"),
            patch("aipass.aipass.apps.modules.install._check_and_fix_owner"),
        ):
            result = run_install(non_interactive=True)
        assert result == 0


# ---------------------------------------------------------------------------
# _check_and_fix_owner tests (DPLAN-0239 P5)
# ---------------------------------------------------------------------------


class TestCheckAndFixOwner:
    """Tests for install-time owner/identity check+fix retro-trigger."""

    def test_clean_check_skips_fix(self, tmp_path) -> None:
        from aipass.aipass.apps.modules.install import _check_and_fix_owner

        mock_proc = MagicMock(returncode=0, stdout="", stderr="")
        with patch(
            "aipass.aipass.apps.modules.install.subprocess.run",
            return_value=mock_proc,
        ) as mock_run:
            _check_and_fix_owner(tmp_path)
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert "--check" in args

    def test_issues_trigger_fix(self, tmp_path) -> None:
        from aipass.aipass.apps.modules.install import _check_and_fix_owner

        check_proc = MagicMock(returncode=1, stdout="", stderr="")
        fix_proc = MagicMock(returncode=0, stdout="", stderr="")
        with patch(
            "aipass.aipass.apps.modules.install.subprocess.run",
            side_effect=[check_proc, fix_proc],
        ) as mock_run:
            _check_and_fix_owner(tmp_path)
        assert mock_run.call_count == 2
        fix_args = mock_run.call_args_list[1][0][0]
        assert "--fix" in fix_args

    def test_drone_not_found_is_silent(self, tmp_path) -> None:
        from aipass.aipass.apps.modules.install import _check_and_fix_owner

        with patch(
            "aipass.aipass.apps.modules.install.subprocess.run",
            side_effect=FileNotFoundError("drone"),
        ):
            _check_and_fix_owner(tmp_path)

    def test_timeout_is_silent(self, tmp_path) -> None:
        import subprocess as _sp

        from aipass.aipass.apps.modules.install import _check_and_fix_owner

        with patch(
            "aipass.aipass.apps.modules.install.subprocess.run",
            side_effect=_sp.TimeoutExpired("drone", 30),
        ):
            _check_and_fix_owner(tmp_path)
