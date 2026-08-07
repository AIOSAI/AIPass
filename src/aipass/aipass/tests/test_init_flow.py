# =================== AIPass ====================
# Name: test_init_flow.py
# Description: Tests for aipass init_flow Phase 3
# Version: 1.0.0
# Created: 2026-04-16
# Modified: 2026-07-04
# =============================================

"""Tests for aipass init_flow module — Phase 3 (FPLAN-0188)."""

import json
from pathlib import Path
from typing import Generator
from unittest.mock import MagicMock, patch

import pytest

from aipass.aipass.apps.modules.init_flow import (
    AIPASS_SPECIFIC_STAGES,
    TEMPLATE_AIPASS,
    TEMPLATE_CHOICES,
    TEMPLATE_EMPTY,
    TOTAL_STAGES,
    _get_last_completed_stage,
    _get_setup_progress,
    _handle_init_update,
    _save_stage,
    handle_command,
    print_help,
    print_introspection,
    run_init,
    stage_1_welcome,
    stage_2_system_detect,
    stage_3_user_profile,
    stage_4_style_questions,
    stage_5_tool_choice,
    stage_6_first_agent,
    stage_7_ping_sweep,
    stage_8_smoke_test,
    stage_9_handoff,
    stage_10_done,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def tmp_local_json(tmp_path: Path) -> Generator[Path, None, None]:
    """Patch _get_local_json_path to return a temp path."""
    local_json = tmp_path / ".trinity" / "local.json"
    local_json.parent.mkdir(parents=True)
    with patch("aipass.aipass.apps.modules.init_flow._get_local_json_path", return_value=local_json):
        yield local_json


@pytest.fixture
def tmp_local_json_with_progress(tmp_local_json: Path) -> Path:
    """Pre-populate local.json with setup_progress at stage 3."""
    data = {
        "setup_progress": {
            "last_completed_stage": 3,
            "stages": {"1": {}, "2": {}, "3": {}},
        }
    }
    tmp_local_json.write_text(json.dumps(data))
    return tmp_local_json


# =============================================================================
# TestGetSetupProgress
# =============================================================================


class TestGetSetupProgress:
    def test_returns_defaults_when_no_file(self, tmp_local_json) -> None:
        """Returns default progress dict when local.json absent."""
        result = _get_setup_progress()
        assert result["last_completed_stage"] == 0
        assert result["stages"] == {}

    def test_reads_existing_progress(self, tmp_local_json_with_progress) -> None:
        """Returns stored progress when setup_progress key exists."""
        result = _get_setup_progress()
        assert result["last_completed_stage"] == 3

    def test_returns_defaults_on_missing_key(self, tmp_local_json) -> None:
        """Returns defaults when local.json has no setup_progress key."""
        tmp_local_json.write_text(json.dumps({"user": {}}))
        result = _get_setup_progress()
        assert result["last_completed_stage"] == 0

    def test_handles_corrupt_file(self, tmp_local_json) -> None:
        """Returns defaults on corrupt JSON."""
        tmp_local_json.write_text("BAD JSON")
        result = _get_setup_progress()
        assert result["last_completed_stage"] == 0


# =============================================================================
# TestGetLastCompletedStage
# =============================================================================


class TestGetLastCompletedStage:
    def test_returns_zero_on_fresh_state(self, tmp_local_json) -> None:
        """Returns 0 when no stages have been completed."""
        assert _get_last_completed_stage() == 0

    def test_returns_stage_number(self, tmp_local_json_with_progress) -> None:
        """Returns the last_completed_stage value from progress."""
        assert _get_last_completed_stage() == 3


# =============================================================================
# TestSaveStage
# =============================================================================


class TestSaveStage:
    def test_saves_stage_data(self, tmp_local_json) -> None:
        """Stage data is written to setup_progress.stages."""
        _save_stage(1, {"foo": "bar"})
        stored = json.loads(tmp_local_json.read_text())
        assert stored["setup_progress"]["last_completed_stage"] == 1
        assert stored["setup_progress"]["stages"]["1"]["foo"] == "bar"

    def test_save_increments_last_completed(self, tmp_local_json) -> None:
        """last_completed_stage advances after each save."""
        _save_stage(1, {})
        _save_stage(2, {})
        stored = json.loads(tmp_local_json.read_text())
        assert stored["setup_progress"]["last_completed_stage"] == 2

    def test_preserves_existing_stages(self, tmp_local_json_with_progress: Path) -> None:
        """Earlier stage data is not overwritten when saving a later stage."""
        _save_stage(4, {"new": "data"})
        stored = json.loads(tmp_local_json_with_progress.read_text())
        assert "1" in stored["setup_progress"]["stages"]
        assert "4" in stored["setup_progress"]["stages"]

    def test_timestamps_stage(self, tmp_local_json) -> None:
        """Saved stage includes a 'timestamp' field."""
        _save_stage(1, {})
        stored = json.loads(tmp_local_json.read_text())
        assert "timestamp" in stored["setup_progress"]["stages"]["1"]


# =============================================================================
# TestPrintIntrospection
# =============================================================================


class TestPrintIntrospection:
    def test_not_started(self, tmp_local_json) -> None:
        """No error when setup not started."""
        with patch("aipass.aipass.apps.modules.init_flow.console"):
            print_introspection()

    def test_in_progress(self, tmp_local_json_with_progress) -> None:
        """No error when setup is in progress."""
        with patch("aipass.aipass.apps.modules.init_flow.console"):
            print_introspection()

    def test_complete(self, tmp_local_json) -> None:
        """No error when setup is complete."""
        data = {"setup_progress": {"last_completed_stage": TOTAL_STAGES, "stages": {}}}
        tmp_local_json.write_text(json.dumps(data))
        with patch("aipass.aipass.apps.modules.init_flow.console"):
            print_introspection()


# =============================================================================
# TestPrintHelp
# =============================================================================


class TestPrintHelp:
    def test_does_not_raise(self) -> None:
        """print_help runs without error."""
        with patch("aipass.aipass.apps.modules.init_flow.console"):
            print_help()

    def test_calls_console_print(self) -> None:
        """print_help outputs via console.print."""
        with patch("aipass.aipass.apps.modules.init_flow.console") as mock_console:
            print_help()
        assert mock_console.print.called


# =============================================================================
# TestHandleCommand
# =============================================================================


class TestHandleCommand:
    def test_wrong_command_returns_false(self) -> None:
        """Non-init commands are not handled."""
        assert handle_command("doctor", []) is False
        assert handle_command("profile", ["set", "name", "X"]) is False

    def test_no_args_shows_help(self, tmp_local_json) -> None:
        """'init' with no args calls print_help (not introspection banner)."""
        with patch("aipass.aipass.apps.modules.init_flow.print_help") as mock_help:
            result = handle_command("init", [])
        assert result is True
        mock_help.assert_called_once()

    def test_info_flag_calls_introspection(self, tmp_local_json) -> None:
        """--info flag calls print_introspection."""
        with patch("aipass.aipass.apps.modules.init_flow.print_introspection") as mock_intro:
            result = handle_command("init", ["--info"])
        assert result is True
        mock_intro.assert_called_once()

    def test_help_flag(self) -> None:
        """--help flag routes to print_help."""
        with patch("aipass.aipass.apps.modules.init_flow.print_help") as mock_help:
            result = handle_command("init", ["--help"])
        assert result is True
        mock_help.assert_called_once()

    def test_h_flag(self) -> None:
        """-h routes to print_help."""
        with patch("aipass.aipass.apps.modules.init_flow.print_help") as mock_help:
            result = handle_command("init", ["-h"])
        assert result is True
        mock_help.assert_called_once()

    def test_run_subcommand_calls_run_init(self, tmp_local_json) -> None:
        """'init run' routes to run_init."""
        with patch("aipass.aipass.apps.modules.init_flow._preflight_check", return_value=None):
            with patch("aipass.aipass.apps.modules.init_flow.run_init", return_value=0) as mock_run:
                with pytest.raises(SystemExit) as exc_info:
                    handle_command("init", ["run"])
        assert exc_info.value.code == 0
        mock_run.assert_called_once()

    def test_positional_args_treated_as_scaffold_target(self, tmp_local_json) -> None:
        """Positional args are treated as target path for scaffold."""
        with patch("aipass.aipass.apps.modules.init_flow._preflight_check", return_value=None):
            with patch("aipass.aipass.apps.modules.init_flow._handle_init_scaffold", return_value=0) as mock_scaffold:
                with pytest.raises(SystemExit) as exc_info:
                    handle_command("init", ["test-proj"])
        assert exc_info.value.code == 0
        mock_scaffold.assert_called_once_with(["test-proj"])


# =============================================================================
# TestRunInit
# =============================================================================


@pytest.fixture(autouse=True)
def _bypass_preflight():
    """All TestRunInit tests run outside a real AIPass project — bypass the guard."""
    with patch("aipass.aipass.apps.modules.init_flow._preflight_check", return_value=None):
        yield


class TestRunInit:
    @pytest.fixture(autouse=True)
    def _isolate_cwd(self, tmp_path, monkeypatch):
        """Avoid _guard_init rejecting the real cwd when it has .trinity/."""
        monkeypatch.chdir(tmp_path)

    def _patch_all_stages(self):
        """Context manager that patches all 10 stage functions to no-ops."""
        stage_names = [
            "stage_1_welcome",
            "stage_2_system_detect",
            "stage_3_user_profile",
            "stage_4_style_questions",
            "stage_5_tool_choice",
            "stage_6_first_agent",
            "stage_7_ping_sweep",
            "stage_8_smoke_test",
            "stage_9_handoff",
            "stage_10_done",
        ]
        patches = [patch(f"aipass.aipass.apps.modules.init_flow.{name}", return_value={}) for name in stage_names]
        return patches

    def test_already_complete_returns_zero(self, tmp_local_json) -> None:
        """Returns 0 immediately when all stages already done."""
        data = {"setup_progress": {"last_completed_stage": TOTAL_STAGES, "stages": {}}}
        tmp_local_json.write_text(json.dumps(data))
        with patch("aipass.aipass.apps.modules.init_flow.console"):
            result = run_init(non_interactive=True)
        assert result == 0

    def test_non_interactive_runs_all_stages(self, tmp_local_json) -> None:
        """non_interactive=True with aipass_framework runs all 10 stages."""
        patches = self._patch_all_stages()
        mocks = []
        ctx = __import__("contextlib").ExitStack()
        for p in patches:
            mocks.append(ctx.enter_context(p))
        with ctx:
            with patch("aipass.aipass.apps.modules.init_flow.json_handler"):
                with patch("aipass.aipass.apps.modules.init_flow.console"):
                    result = run_init(non_interactive=True, template=TEMPLATE_AIPASS)
        assert result == 0

    def test_keyboard_interrupt_pauses_gracefully(self, tmp_local_json) -> None:
        """KeyboardInterrupt during a stage returns 0 (resume later)."""
        with patch("aipass.aipass.apps.modules.init_flow.stage_1_welcome", side_effect=KeyboardInterrupt):
            with patch("aipass.aipass.apps.modules.init_flow.console"):
                with patch("aipass.aipass.apps.modules.init_flow.warning"):
                    result = run_init(non_interactive=False, template=TEMPLATE_EMPTY)
        assert result == 0

    def test_stage_error_continues(self, tmp_local_json) -> None:
        """Exception in a stage is logged and execution continues."""
        call_count = {"n": 0}

        def boom_once(*args, **kwargs):
            """Raise RuntimeError on first call, return {} on subsequent calls."""
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("stage failure")
            return {}

        _MOD = "aipass.aipass.apps.modules.init_flow"
        with patch.multiple(
            _MOD,
            stage_1_welcome=MagicMock(side_effect=boom_once),
            stage_2_system_detect=MagicMock(return_value={}),
            stage_3_user_profile=MagicMock(return_value={}),
            stage_4_style_questions=MagicMock(return_value={}),
            stage_5_tool_choice=MagicMock(return_value={}),
            stage_6_first_agent=MagicMock(return_value={}),
            stage_7_ping_sweep=MagicMock(return_value={}),
            stage_8_smoke_test=MagicMock(return_value={}),
            stage_9_handoff=MagicMock(return_value={}),
            stage_10_done=MagicMock(return_value={}),
            warning=MagicMock(),
            console=MagicMock(),
        ):
            result = run_init(non_interactive=True, template=TEMPLATE_AIPASS)
        assert result == 0

    def test_resumes_from_last_completed(self, tmp_local_json_with_progress: Path) -> None:
        """Skips stages already completed (stages 1-3 in fixture)."""
        stage_1_mock = MagicMock(return_value={})
        stage_4_mock = MagicMock(return_value={})
        _MOD = "aipass.aipass.apps.modules.init_flow"
        with patch.multiple(
            _MOD,
            stage_1_welcome=stage_1_mock,
            stage_2_system_detect=MagicMock(return_value={}),
            stage_3_user_profile=MagicMock(return_value={}),
            stage_4_style_questions=stage_4_mock,
            stage_5_tool_choice=MagicMock(return_value={}),
            stage_6_first_agent=MagicMock(return_value={}),
            stage_7_ping_sweep=MagicMock(return_value={}),
            stage_8_smoke_test=MagicMock(return_value={}),
            stage_9_handoff=MagicMock(return_value={}),
            stage_10_done=MagicMock(return_value={}),
            warning=MagicMock(),
            console=MagicMock(),
        ):
            run_init(non_interactive=True, template=TEMPLATE_AIPASS)
        stage_1_mock.assert_not_called()
        stage_4_mock.assert_called_once()


# =============================================================================
# TestStages
# =============================================================================

_MOD = "aipass.aipass.apps.modules.init_flow"


class TestStages:
    """Unit tests for individual stage functions (non-interactive paths)."""

    def test_stage_1_welcome_returns_dict(self, tmp_local_json) -> None:
        """stage_1_welcome runs and returns {}."""
        with patch(f"{_MOD}.console"):
            result = stage_1_welcome()
        assert result == {}
        stored = json.loads(tmp_local_json.read_text())
        assert stored["setup_progress"]["last_completed_stage"] == 1

    def test_stage_2_system_detect_returns_system_data(self, tmp_local_json) -> None:
        """stage_2_system_detect returns dict with os/python/shell keys."""
        with patch.multiple(
            _MOD,
            console=MagicMock(),
            detect_python=MagicMock(return_value={"version": "3.12.0", "ok": True}),
            detect_git=MagicMock(return_value={"found": True, "version": "2.43"}),
            detect_shell=MagicMock(return_value={"name": "bash", "path": "/bin/bash"}),
            detect_os=MagicMock(return_value={"os_name": "Linux", "release": "6.0", "machine": "x86"}),
            detect_ram=MagicMock(return_value={"total_gb": 16.0, "ok": True, "warning": False}),
            detect_cpu=MagicMock(return_value={"count": 8}),
            detect_install_method=MagicMock(return_value="pip"),
            detect_tmux=MagicMock(return_value=True),
            detect_wt=MagicMock(return_value=False),
        ):
            result = stage_2_system_detect(non_interactive=True)
        assert result["os"] == "Linux"
        assert result["python"] == "3.12.0"
        assert result["shell"] == "bash"

    def test_stage_3_non_interactive_uses_default_name(self, tmp_local_json) -> None:
        """non_interactive=True sets name to 'User'."""
        mock_profile_mod = MagicMock()
        mock_profile_mod.get_user_profile.return_value = {
            f: None for f in ["name", "os", "shell", "preferred_cli", "install_method", "first_seen"]
        }
        with patch(f"{_MOD}.console"):
            with patch(f"{_MOD}.detect_os", return_value={"os_name": "Linux", "release": "6.0", "machine": "x86"}):
                with patch.dict("sys.modules", {"aipass.aipass.apps.modules.profile": mock_profile_mod}):
                    result = stage_3_user_profile(non_interactive=True)
        assert result["name"] == "User"

    def test_stage_3_name_override(self, tmp_local_json) -> None:
        """name_override parameter is used when provided."""
        mock_profile_mod = MagicMock()
        mock_profile_mod.get_user_profile.return_value = {
            f: None for f in ["name", "os", "shell", "preferred_cli", "install_method", "first_seen"]
        }
        with patch(f"{_MOD}.console"):
            with patch(f"{_MOD}.detect_os", return_value={"os_name": "Linux", "release": "6.0", "machine": "x86"}):
                with patch.dict("sys.modules", {"aipass.aipass.apps.modules.profile": mock_profile_mod}):
                    result = stage_3_user_profile(non_interactive=True, name_override="user")
        assert result["name"] == "user"

    def test_stage_4_non_interactive_returns_first_choice(self, tmp_local_json) -> None:
        """non_interactive=True selects first STYLE_CHOICES entry."""
        with patch(f"{_MOD}.console"):
            result = stage_4_style_questions(non_interactive=True)
        assert "style" in result
        assert result["style"] is not None

    def test_stage_4_style_override(self, tmp_local_json) -> None:
        """style_override is honoured when it's a valid choice."""
        from aipass.aipass.apps.modules.init_flow import STYLE_CHOICES

        override = STYLE_CHOICES[0]
        with patch(f"{_MOD}.console"):
            result = stage_4_style_questions(non_interactive=True, style_override=override)
        assert result["style"] == override

    def test_stage_5_non_interactive_defaults_to_claude(self, tmp_local_json) -> None:
        """non_interactive=True selects 'claude' as CLI."""
        mock_profile_mod = MagicMock()
        mock_profile_mod.get_user_profile.return_value = {}
        with patch(f"{_MOD}.console"):
            with patch.dict("sys.modules", {"aipass.aipass.apps.modules.profile": mock_profile_mod}):
                result = stage_5_tool_choice(non_interactive=True)
        assert result["cli"] == "claude"
        assert result["flag_variant"] == "default"

    def test_stage_5_cli_override(self, tmp_local_json) -> None:
        """cli_override sets the CLI choice."""
        mock_profile_mod = MagicMock()
        mock_profile_mod.get_user_profile.return_value = {}
        with patch(f"{_MOD}.console"):
            with patch.dict("sys.modules", {"aipass.aipass.apps.modules.profile": mock_profile_mod}):
                result = stage_5_tool_choice(non_interactive=True, cli_override="codex")
        assert result["cli"] == "codex"

    def test_stage_5_claude_present_no_prompt(self, tmp_local_json) -> None:
        """When claude is on PATH, no install prompt is shown."""
        mock_profile_mod = MagicMock()
        mock_profile_mod.get_user_profile.return_value = {}
        with patch(f"{_MOD}.console"):
            with patch(f"{_MOD}.shutil.which", return_value="/usr/bin/claude"):
                with patch.dict("sys.modules", {"aipass.aipass.apps.modules.profile": mock_profile_mod}):
                    with patch(f"{_MOD}._handle_missing_claude") as mock_handle:
                        result = stage_5_tool_choice(non_interactive=True)
        mock_handle.assert_not_called()
        assert result["cli"] == "claude"

    @patch(f"{_MOD}._choose", return_value="default")
    @patch(f"{_MOD}._install_claude_code", return_value=True)
    @patch(f"{_MOD}._prompt", return_value="Y")
    @patch(f"{_MOD}.shutil.which", return_value=None)
    @patch(f"{_MOD}.console")
    def test_stage_5_claude_missing_interactive_yes(
        self, _con, _which, _prompt, mock_install, _choose, tmp_local_json
    ) -> None:
        """Missing claude + interactive + yes → installer invoked."""
        mock_profile_mod = MagicMock()
        mock_profile_mod.get_user_profile.return_value = {}
        with patch.dict("sys.modules", {"aipass.aipass.apps.modules.profile": mock_profile_mod}):
            result = stage_5_tool_choice(non_interactive=False, cli_override="claude")
        mock_install.assert_called_once()
        assert result["cli"] == "claude"

    @patch(f"{_MOD}._choose", return_value="default")
    @patch(f"{_MOD}._install_claude_code")
    @patch(f"{_MOD}._prompt", return_value="n")
    @patch(f"{_MOD}.shutil.which", return_value=None)
    @patch(f"{_MOD}.console")
    def test_stage_5_claude_missing_interactive_no(
        self, _con, _which, _prompt, mock_install, _choose, tmp_local_json
    ) -> None:
        """Missing claude + interactive + no → no install, continues."""
        mock_profile_mod = MagicMock()
        mock_profile_mod.get_user_profile.return_value = {}
        with patch.dict("sys.modules", {"aipass.aipass.apps.modules.profile": mock_profile_mod}):
            result = stage_5_tool_choice(non_interactive=False, cli_override="claude")
        mock_install.assert_not_called()
        assert result["cli"] == "claude"

    @patch(f"{_MOD}.warning")
    @patch(f"{_MOD}._install_claude_code")
    @patch(f"{_MOD}.shutil.which", return_value=None)
    @patch(f"{_MOD}.console")
    def test_stage_5_claude_missing_non_interactive_warns(
        self, _con, _which, mock_install, mock_warn, tmp_local_json
    ) -> None:
        """Missing claude + non-interactive → warning, no install."""
        mock_profile_mod = MagicMock()
        mock_profile_mod.get_user_profile.return_value = {}
        with patch.dict("sys.modules", {"aipass.aipass.apps.modules.profile": mock_profile_mod}):
            result = stage_5_tool_choice(non_interactive=True)
        mock_install.assert_not_called()
        mock_warn.assert_called_once()
        assert result["cli"] == "claude"

    def test_stage_6_non_interactive_creates_my_agent(self, tmp_local_json) -> None:
        """non_interactive=True uses 'my_agent' as default name."""
        mock_proc = MagicMock(returncode=0)
        with patch(f"{_MOD}.console"):
            with patch(f"{_MOD}.subprocess.run", return_value=mock_proc):
                with patch(f"{_MOD}._resolve_package_dir", return_value=None):
                    result = stage_6_first_agent(non_interactive=True)
        assert result["agent_name"] == "my_agent"
        assert result["agent_path"] == "src/my_agent"

    def test_stage_6_drone_not_found(self, tmp_local_json) -> None:
        """FileNotFoundError from drone is handled gracefully."""
        with patch(f"{_MOD}.console"):
            with patch(f"{_MOD}.warning"):
                with patch(f"{_MOD}.subprocess.run", side_effect=FileNotFoundError):
                    result = stage_6_first_agent(non_interactive=True)
        assert "agent_name" in result

    def test_stage_7_ping_sweep_calls_sweep(self, tmp_local_json) -> None:
        """stage_7_ping_sweep calls sweep_all_branches and returns results."""
        mock_ps = MagicMock()
        mock_ps.sweep_all_branches.return_value = {"drone": "ack", "prax": "timeout"}
        mock_ps.sweep_summary.return_value = "1 ack / 1 timeout / 0 error"
        with patch(f"{_MOD}.console"):
            with patch.dict("sys.modules", {"aipass.aipass.apps.handlers.ping_sweep": mock_ps}):
                result = stage_7_ping_sweep(non_interactive=True)
        assert "ping_results" in result

    def test_stage_8_smoke_test_both_found(self, tmp_local_json) -> None:
        """smoke test passes when both drone and aipass are on PATH."""
        with patch(f"{_MOD}.console"):
            with patch(f"{_MOD}.shutil.which", return_value="/usr/bin/drone"):
                result = stage_8_smoke_test()
        assert result["drone"] == "/usr/bin/drone"

    def test_stage_8_smoke_test_missing(self, tmp_local_json) -> None:
        """Warnings emitted when binaries not found."""
        with patch(f"{_MOD}.console"):
            with patch(f"{_MOD}.warning"):
                with patch(f"{_MOD}.shutil.which", return_value=None):
                    result = stage_8_smoke_test()
        assert result["drone"] is None
        assert result["aipass"] is None

    def test_stage_9_default_variant_no_flag(self, tmp_local_json) -> None:
        """Default flag variant does not append --dangerously-skip-permissions."""
        with patch(f"{_MOD}.console"):
            result = stage_9_handoff(cli_choice="claude", flag_variant="default", non_interactive=True)
        assert "--dangerously-skip-permissions" not in result["handoff_command"]

    def test_stage_9_skip_permissions_variant(self, tmp_local_json) -> None:
        """skip-permissions variant appends the flag for claude."""
        with patch(f"{_MOD}.console"):
            result = stage_9_handoff(cli_choice="claude", flag_variant="skip-permissions", non_interactive=True)
        assert "--dangerously-skip-permissions" in result["handoff_command"]

    def test_stage_9_handoff_command_contains_path(self, tmp_local_json) -> None:
        """Handoff command includes the agent path."""
        with patch(f"{_MOD}.console"):
            result = stage_9_handoff(agent_path="src/mybot", non_interactive=True)
        assert "src/mybot" in result["handoff_command"]

    def test_stage_9_non_interactive_no_spawn(self, tmp_local_json) -> None:
        """Non-interactive stage 9 prints the command but never spawns a session."""
        with (
            patch(f"{_MOD}.console"),
            patch("aipass.aipass.apps.modules.handoff.do_handoff") as mock_handoff,
        ):
            result = stage_9_handoff(non_interactive=True)
        mock_handoff.assert_not_called()
        assert result["launched"] is False
        assert result["handoff_command"]

    def test_stage_10_done_returns_empty(self, tmp_local_json) -> None:
        """stage_10_done returns {} and marks stage 10 complete."""
        with patch(f"{_MOD}.console"):
            result = stage_10_done()
        assert result == {}
        stored = json.loads(tmp_local_json.read_text())
        assert stored["setup_progress"]["last_completed_stage"] == 10


# =============================================================================
# TestProviderGaps — provider-manifest surfacing, decoupled from the doctor stage
# =============================================================================


class TestProviderGaps:
    """Provider gaps reach the init report without running the full doctor."""

    def test_collect_provider_gaps_reports_missing(self) -> None:
        """Non-pass manifest results are collected; run_doctor is never called."""
        from aipass.aipass.apps.modules import doctor
        from aipass.aipass.apps.modules.init_flow import _collect_provider_gaps

        gap = MagicMock(glyph="WARN", label="hooks", detail="wire the hook")
        passing = MagicMock(glyph=doctor.GLYPH_PASS, label="env", detail="")
        with patch.object(doctor, "_check_provider_manifest", return_value=[gap, passing]):
            with patch.object(doctor, "run_doctor") as mock_run:
                gaps = _collect_provider_gaps()
        assert gaps == {"hooks": "wire the hook"}
        mock_run.assert_not_called()

    def test_collect_provider_gaps_swallows_errors(self) -> None:
        """A failing manifest check degrades to an empty dict, not a crash."""
        from aipass.aipass.apps.modules import doctor
        from aipass.aipass.apps.modules.init_flow import _collect_provider_gaps

        with patch.object(doctor, "_check_provider_manifest", side_effect=RuntimeError("boom")):
            with patch(f"{_MOD}.logger"):
                gaps = _collect_provider_gaps()
        assert gaps == {}

    def test_init_report_includes_provider_gaps(self, tmp_path: Path) -> None:
        """_write_init_report embeds provider gaps + action when the manifest reports them."""
        from aipass.aipass.apps.modules.init_flow import _write_init_report

        agent_dir = tmp_path / "src" / "bot"
        agent_dir.mkdir(parents=True)
        with patch(f"{_MOD}._collect_provider_gaps", return_value={"hooks": "missing"}):
            _write_init_report(str(agent_dir), {"agent_name": "BOT"})
        report = json.loads((agent_dir / "dropbox" / "init_report.json").read_text())
        assert report["provider_gaps"] == {"hooks": "missing"}
        assert "provider_action" in report

    def test_init_report_omits_provider_gaps_when_clean(self, tmp_path: Path) -> None:
        """No provider keys are written when the manifest is fully satisfied."""
        from aipass.aipass.apps.modules.init_flow import _write_init_report

        agent_dir = tmp_path / "src" / "bot"
        agent_dir.mkdir(parents=True)
        with patch(f"{_MOD}._collect_provider_gaps", return_value={}):
            _write_init_report(str(agent_dir), {"agent_name": "BOT"})
        report = json.loads((agent_dir / "dropbox" / "init_report.json").read_text())
        assert "provider_gaps" not in report
        assert "provider_action" not in report


# =============================================================================
# init_update_registry_sync: subprocess_sync
# =============================================================================


_MOD_UPDATE = "aipass.aipass.apps.modules.init_flow"


class TestInitUpdateRegistrySync:
    """Tests for owner/identity check+fix in _handle_init_update (DPLAN-0239 P5)."""

    def test_clean_check_prints_ok(self, tmp_path: Path) -> None:
        """Clean --check (exit 0) prints 'Owner/identity OK.' and skips --fix."""
        check_proc = MagicMock(returncode=0, stdout="", stderr="")
        with (
            patch(
                "aipass.aipass.apps.handlers.init.bootstrap.update_project",
                return_value={"updated_files": [], "already_current": []},
            ),
            # Subject here is the sync-registry branch; git-auth provisioning
            # (which needs a real project on disk) has its own suite below.
            patch(f"{_MOD_UPDATE}._run_git_auth_provisioning", return_value=0),
            patch(f"{_MOD_UPDATE}.subprocess.run", return_value=check_proc) as mock_run,
            patch(f"{_MOD_UPDATE}.console"),
            patch(f"{_MOD_UPDATE}.success") as mock_success,
            patch(f"{_MOD_UPDATE}.json_handler"),
        ):
            rc = _handle_init_update([str(tmp_path)])
        assert rc == 0
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert "--check" in args
        ok_calls = [c for c in mock_success.call_args_list if "Owner/identity OK" in str(c)]
        assert len(ok_calls) == 1

    def test_issues_trigger_fix(self, tmp_path: Path) -> None:
        """Non-zero --check triggers --fix; success prints reconciled."""
        check_proc = MagicMock(returncode=1, stdout="", stderr="")
        fix_proc = MagicMock(returncode=0, stdout="", stderr="")
        with (
            patch(
                "aipass.aipass.apps.handlers.init.bootstrap.update_project",
                return_value={"updated_files": [], "already_current": []},
            ),
            # Subject here is the sync-registry branch; git-auth provisioning
            # (which needs a real project on disk) has its own suite below.
            patch(f"{_MOD_UPDATE}._run_git_auth_provisioning", return_value=0),
            patch(
                f"{_MOD_UPDATE}.subprocess.run",
                side_effect=[check_proc, fix_proc],
            ) as mock_run,
            patch(f"{_MOD_UPDATE}.console"),
            patch(f"{_MOD_UPDATE}.success") as mock_success,
            patch(f"{_MOD_UPDATE}.warning"),
            patch(f"{_MOD_UPDATE}.json_handler"),
        ):
            rc = _handle_init_update([str(tmp_path)])
        assert rc == 0
        assert mock_run.call_count == 2
        fix_args = mock_run.call_args_list[1][0][0]
        assert "--fix" in fix_args
        reconciled = [c for c in mock_success.call_args_list if "reconciled" in str(c)]
        assert len(reconciled) == 1

    def test_fix_failure_degrades_silently(self, tmp_path: Path) -> None:
        """Non-zero --fix exit degrades gracefully (no crash)."""
        check_proc = MagicMock(returncode=1, stdout="", stderr="")
        fix_proc = MagicMock(returncode=1, stdout="", stderr="")
        with (
            patch(
                "aipass.aipass.apps.handlers.init.bootstrap.update_project",
                return_value={"updated_files": [], "already_current": []},
            ),
            # Subject here is the sync-registry branch; git-auth provisioning
            # (which needs a real project on disk) has its own suite below.
            patch(f"{_MOD_UPDATE}._run_git_auth_provisioning", return_value=0),
            patch(
                f"{_MOD_UPDATE}.subprocess.run",
                side_effect=[check_proc, fix_proc],
            ),
            patch(f"{_MOD_UPDATE}.console"),
            patch(f"{_MOD_UPDATE}.warning"),
            patch(f"{_MOD_UPDATE}.json_handler"),
        ):
            rc = _handle_init_update([str(tmp_path)])
        assert rc == 0

    def test_sync_missing_drone_degrades_silently(self, tmp_path: Path) -> None:
        """FileNotFoundError (no drone binary) degrades gracefully."""
        with (
            patch(
                "aipass.aipass.apps.handlers.init.bootstrap.update_project",
                return_value={"updated_files": [], "already_current": []},
            ),
            # Subject here is the sync-registry branch; git-auth provisioning
            # (which needs a real project on disk) has its own suite below.
            patch(f"{_MOD_UPDATE}._run_git_auth_provisioning", return_value=0),
            patch(f"{_MOD_UPDATE}.subprocess.run", side_effect=FileNotFoundError("drone not found")),
            patch(f"{_MOD_UPDATE}.console"),
            patch(f"{_MOD_UPDATE}.json_handler"),
        ):
            rc = _handle_init_update([str(tmp_path)])
        assert rc == 0

    def test_sync_timeout_degrades_silently(self, tmp_path: Path) -> None:
        """subprocess.TimeoutExpired degrades gracefully."""
        import subprocess as _sp

        with (
            patch(
                "aipass.aipass.apps.handlers.init.bootstrap.update_project",
                return_value={"updated_files": [], "already_current": []},
            ),
            # Subject here is the sync-registry branch; git-auth provisioning
            # (which needs a real project on disk) has its own suite below.
            patch(f"{_MOD_UPDATE}._run_git_auth_provisioning", return_value=0),
            patch(f"{_MOD_UPDATE}.subprocess.run", side_effect=_sp.TimeoutExpired(cmd="drone", timeout=30)),
            patch(f"{_MOD_UPDATE}.console"),
            patch(f"{_MOD_UPDATE}.json_handler"),
        ):
            rc = _handle_init_update([str(tmp_path)])
        assert rc == 0


class TestInitUpdateGitAuth:
    """Tests for git-auth provisioning wired into `aipass init update` (DPLAN-0281 P2)."""

    @staticmethod
    def _project(root: Path, citizen_class: str = "builder") -> None:
        """Write a minimal external project whose owner is one flip from git."""
        (root / "DEMO_REGISTRY.json").write_text(
            json.dumps(
                {
                    "metadata": {"id": "abc-123"},
                    "branches": [{"name": "VERA", "path": "src/demo/vera", "owner": True}],
                }
            ),
            encoding="utf-8",
        )
        passport = root / "src" / "demo" / "vera" / ".trinity" / "passport.json"
        passport.parent.mkdir(parents=True)
        passport.write_text(
            json.dumps(
                {
                    "branch_info": {"branch_name": "VERA"},
                    "identity": {"citizen_class": citizen_class},
                    "citizenship": {"registry_id": "abc-123"},
                }
            ),
            encoding="utf-8",
        )

    def test_update_provisions_git_auth_after_sync(self, tmp_path: Path) -> None:
        """The class flip lands, and it runs AFTER sync-registry (which may migrate it)."""
        self._project(tmp_path)
        with (
            patch(
                "aipass.aipass.apps.handlers.init.bootstrap.update_project",
                return_value={"updated_files": [], "already_current": []},
            ),
            patch(f"{_MOD_UPDATE}.subprocess.run", return_value=MagicMock(returncode=0, stdout="", stderr="")),
            patch(f"{_MOD_UPDATE}.console"),
            patch(f"{_MOD_UPDATE}.success") as mock_success,
            patch(f"{_MOD_UPDATE}.json_handler"),
        ):
            rc = _handle_init_update([str(tmp_path)])

        assert rc == 0
        passport = json.loads(
            (tmp_path / "src" / "demo" / "vera" / ".trinity" / "passport.json").read_text(encoding="utf-8")
        )
        assert passport["identity"]["citizen_class"] == "manager"
        assert any("Verified against all four" in str(c) for c in mock_success.call_args_list)

    def test_update_reports_honest_no_op(self, tmp_path: Path) -> None:
        """An already-provisioned owner is reported as nothing to repair, not as a repair."""
        self._project(tmp_path, citizen_class="manager")
        with (
            patch(
                "aipass.aipass.apps.handlers.init.bootstrap.update_project",
                return_value={"updated_files": [], "already_current": []},
            ),
            patch(f"{_MOD_UPDATE}.subprocess.run", return_value=MagicMock(returncode=0, stdout="", stderr="")),
            patch(f"{_MOD_UPDATE}.console"),
            patch(f"{_MOD_UPDATE}.success") as mock_success,
            patch(f"{_MOD_UPDATE}.json_handler"),
        ):
            rc = _handle_init_update([str(tmp_path)])

        assert rc == 0
        assert any("nothing to repair" in str(c) for c in mock_success.call_args_list)

    def test_refusal_exits_nonzero_and_names_the_fix(self, tmp_path: Path) -> None:
        """No citizen marked owner — update refuses instead of guessing one."""
        (tmp_path / "DEMO_REGISTRY.json").write_text(
            json.dumps({"metadata": {"id": "abc-123"}, "branches": [{"name": "VERA", "path": "src/demo/vera"}]}),
            encoding="utf-8",
        )
        with (
            patch(
                "aipass.aipass.apps.handlers.init.bootstrap.update_project",
                return_value={"updated_files": [], "already_current": []},
            ),
            patch(f"{_MOD_UPDATE}.subprocess.run", return_value=MagicMock(returncode=0, stdout="", stderr="")),
            patch(f"{_MOD_UPDATE}.console"),
            patch(f"{_MOD_UPDATE}.success"),
            patch(f"{_MOD_UPDATE}.cli_error") as mock_error,
            patch(f"{_MOD_UPDATE}.json_handler"),
        ):
            rc = _handle_init_update([str(tmp_path)])

        assert rc == 1
        assert any('"owner": true' in str(c) for c in mock_error.call_args_list)

    def test_dry_run_skips_the_scaffold_refresh_and_writes_nothing(self, tmp_path: Path) -> None:
        """--dry-run touches nothing: no scaffold refresh, no sync-registry, no writes."""
        self._project(tmp_path)
        passport_path = tmp_path / "src" / "demo" / "vera" / ".trinity" / "passport.json"
        before = passport_path.read_text(encoding="utf-8")

        with (
            patch("aipass.aipass.apps.handlers.init.bootstrap.update_project") as mock_update,
            patch(f"{_MOD_UPDATE}.subprocess.run") as mock_run,
            patch(f"{_MOD_UPDATE}.console"),
            patch(f"{_MOD_UPDATE}.success") as mock_success,
            patch(f"{_MOD_UPDATE}.json_handler"),
        ):
            rc = _handle_init_update([str(tmp_path), "--dry-run"])

        assert rc == 0
        mock_update.assert_not_called()
        mock_run.assert_not_called()
        assert passport_path.read_text(encoding="utf-8") == before
        assert any("would repair" in str(c) for c in mock_success.call_args_list)


# =============================================================================
# TestTemplateSelector
# =============================================================================


class TestTemplateSelector:
    """Tests for the template selector in aipass init."""

    @staticmethod
    def _stage_patches():
        """Return patches for all 10 stage functions as no-ops."""
        stage_names = [
            "stage_1_welcome",
            "stage_2_system_detect",
            "stage_3_user_profile",
            "stage_4_style_questions",
            "stage_5_tool_choice",
            "stage_6_first_agent",
            "stage_7_ping_sweep",
            "stage_8_smoke_test",
            "stage_9_handoff",
            "stage_10_done",
        ]
        return {name: MagicMock(return_value={}) for name in stage_names}

    def test_empty_project_default_skips_agent_and_ping(self, tmp_local_json) -> None:
        """empty project (default) = no scaffold; framework-only stages 6,7 skipped; 9,10 run."""
        mocks = self._stage_patches()
        with patch.multiple(_MOD, console=MagicMock(), warning=MagicMock(), **mocks):
            result = run_init(non_interactive=True, template=TEMPLATE_EMPTY)
        assert result == 0
        for name in (
            "stage_1_welcome",
            "stage_2_system_detect",
            "stage_3_user_profile",
            "stage_4_style_questions",
            "stage_5_tool_choice",
            "stage_8_smoke_test",
            "stage_9_handoff",
            "stage_10_done",
        ):
            assert mocks[name].called, f"{name} should have been called"
        for name in ("stage_6_first_agent", "stage_7_ping_sweep"):
            assert not mocks[name].called, f"{name} should NOT have been called"

    def test_aipass_framework_runs_full_scaffold(self, tmp_local_json) -> None:
        """aipass_framework = full scaffold + all 10 stages."""
        mocks = self._stage_patches()
        with patch.multiple(_MOD, console=MagicMock(), warning=MagicMock(), **mocks):
            with patch(
                "aipass.aipass.apps.handlers.init.bootstrap.init_project",
                return_value={},
            ):
                result = run_init(non_interactive=True, template=TEMPLATE_AIPASS)
        assert result == 0
        for name in mocks:
            assert mocks[name].called, f"{name} should have been called"

    def test_list_flag_shows_catalog(self) -> None:
        """aipass init --list shows the catalog (not swallowed into run)."""
        with patch(f"{_MOD}.console") as mock_console:
            result = handle_command("init", ["--list"])
        assert result is True
        printed = " ".join(str(c) for c in mock_console.print.call_args_list)
        for t in TEMPLATE_CHOICES:
            assert t in printed

    def test_template_flag_form_works(self, tmp_local_json) -> None:
        """aipass init run --template aipass_framework passes template to run_init."""
        with patch(f"{_MOD}.run_init", return_value=0) as mock_run:
            with pytest.raises(SystemExit):
                handle_command("init", ["run", "--template", TEMPLATE_AIPASS])
        mock_run.assert_called_once()
        _, kwargs = mock_run.call_args
        assert kwargs["template"] == TEMPLATE_AIPASS

    def test_positional_template_routes_to_run_init(self, tmp_local_json) -> None:
        """aipass init aipass_framework routes to run_init with template."""
        with patch(f"{_MOD}.run_init", return_value=0) as mock_run:
            with pytest.raises(SystemExit):
                handle_command("init", [TEMPLATE_AIPASS])
        mock_run.assert_called_once()
        _, kwargs = mock_run.call_args
        assert kwargs["template"] == TEMPLATE_AIPASS

    def test_positional_path_still_works(self, tmp_local_json) -> None:
        """Non-template positional args still route to scaffold."""
        with patch(f"{_MOD}._preflight_check", return_value=None):
            with patch(f"{_MOD}._handle_init_scaffold", return_value=0) as mock_scaffold:
                with pytest.raises(SystemExit):
                    handle_command("init", ["test-proj"])
        mock_scaffold.assert_called_once_with(["test-proj"])

    def test_pip_hints_say_clone(self, tmp_local_json) -> None:
        """in-product hints say clone/setup.sh, not pip."""
        with patch(f"{_MOD}.console"):
            with patch(f"{_MOD}.warning") as mock_warn:
                with patch(f"{_MOD}.shutil.which", return_value=None):
                    stage_8_smoke_test()
        for call in mock_warn.call_args_list:
            msg = call[0][0].lower()
            assert "setup.sh" in msg
            assert "pip" not in msg

    def test_empty_template_stage9_gets_cwd_as_agent_path(self, tmp_local_json) -> None:
        """Empty template sets agent_path='.' so stage 9 hands off from CWD."""
        mocks = self._stage_patches()
        with patch.multiple(_MOD, console=MagicMock(), warning=MagicMock(), **mocks):
            run_init(non_interactive=True, template=TEMPLATE_EMPTY)
        stage_9_call = mocks["stage_9_handoff"].call_args
        assert stage_9_call is not None
        agent_path_arg = stage_9_call[0][2] if len(stage_9_call[0]) > 2 else stage_9_call[1].get("agent_path", "")
        assert agent_path_arg == "."

    def test_non_tty_forces_non_interactive(self, tmp_local_json) -> None:
        """When stdin is not a TTY, run_init auto-forces non_interactive (no crash)."""
        mocks = self._stage_patches()
        with (
            patch.multiple(_MOD, console=MagicMock(), warning=MagicMock(), **mocks),
            patch("sys.stdin") as mock_stdin,
        ):
            mock_stdin.isatty.return_value = False
            rc = run_init(non_interactive=False, template=TEMPLATE_EMPTY)
        assert rc == 0

    def test_aipass_specific_stages_constant(self) -> None:
        """AIPASS_SPECIFIC_STAGES contains exactly {6, 7} — stages 9/10 run for ALL templates."""
        assert AIPASS_SPECIFIC_STAGES == {6, 7}
