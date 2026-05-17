# =================== AIPass ====================
# Name: test_init_flow.py
# Description: Tests for aipass init_flow Phase 3
# Version: 1.0.0
# Created: 2026-04-16
# Modified: 2026-04-16
# =============================================

"""Tests for aipass init_flow module — Phase 3 (FPLAN-0188)."""

import json
from pathlib import Path
from typing import Generator
from unittest.mock import MagicMock, patch

import pytest

from aipass.aipass.apps.modules.init_flow import (
    TOTAL_STAGES,
    _get_last_completed_stage,
    _get_setup_progress,
    _save_stage,
    handle_command,
    print_help,
    print_introspection,
    run_init,
    stage_1_welcome,
    stage_2_system_detect,
    stage_3_doctor,
    stage_4_user_profile,
    stage_5_style_questions,
    stage_6_tool_choice,
    stage_7_docker_offer,
    stage_8_first_agent,
    stage_9_ping_sweep,
    stage_10_smoke_test,
    stage_11_handoff,
    stage_12_done,
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

    def test_no_args_shows_introspection(self, tmp_local_json) -> None:
        """'init' with no args calls print_introspection."""
        with patch("aipass.aipass.apps.modules.init_flow.print_introspection") as mock_intro:
            result = handle_command("init", [])
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
                    handle_command("init", ["/tmp/test-proj"])
        assert exc_info.value.code == 0
        mock_scaffold.assert_called_once_with(["/tmp/test-proj"])


# =============================================================================
# TestRunInit
# =============================================================================


@pytest.fixture(autouse=True)
def _bypass_preflight():
    """All TestRunInit tests run outside a real AIPass project — bypass the guard."""
    with patch("aipass.aipass.apps.modules.init_flow._preflight_check", return_value=None):
        yield


class TestRunInit:
    def _patch_all_stages(self):
        """Context manager that patches all 12 stage functions to no-ops."""
        stage_names = [
            "stage_1_welcome",
            "stage_2_system_detect",
            "stage_3_doctor",
            "stage_4_user_profile",
            "stage_5_style_questions",
            "stage_6_tool_choice",
            "stage_7_docker_offer",
            "stage_8_first_agent",
            "stage_9_ping_sweep",
            "stage_10_smoke_test",
            "stage_11_handoff",
            "stage_12_done",
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
        """non_interactive=True runs all 12 stages from fresh state."""
        patches = self._patch_all_stages()
        mocks = []
        ctx = __import__("contextlib").ExitStack()
        for p in patches:
            mocks.append(ctx.enter_context(p))
        with ctx:
            with patch("aipass.aipass.apps.modules.init_flow.json_handler"):
                with patch("aipass.aipass.apps.modules.init_flow.console"):
                    result = run_init(non_interactive=True)
        assert result == 0

    def test_keyboard_interrupt_pauses_gracefully(self, tmp_local_json) -> None:
        """KeyboardInterrupt during a stage returns 0 (resume later)."""
        with patch("aipass.aipass.apps.modules.init_flow.stage_1_welcome", side_effect=KeyboardInterrupt):
            with patch("aipass.aipass.apps.modules.init_flow.console"):
                with patch("aipass.aipass.apps.modules.init_flow.warning"):
                    result = run_init(non_interactive=False)
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
            stage_3_doctor=MagicMock(return_value={}),
            stage_4_user_profile=MagicMock(return_value={}),
            stage_5_style_questions=MagicMock(return_value={}),
            stage_6_tool_choice=MagicMock(return_value={}),
            stage_7_docker_offer=MagicMock(return_value={}),
            stage_8_first_agent=MagicMock(return_value={}),
            stage_9_ping_sweep=MagicMock(return_value={}),
            stage_10_smoke_test=MagicMock(return_value={}),
            stage_11_handoff=MagicMock(return_value={}),
            stage_12_done=MagicMock(return_value={}),
            warning=MagicMock(),
            console=MagicMock(),
        ):
            result = run_init(non_interactive=True)
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
            stage_3_doctor=MagicMock(return_value={}),
            stage_4_user_profile=stage_4_mock,
            stage_5_style_questions=MagicMock(return_value={}),
            stage_6_tool_choice=MagicMock(return_value={}),
            stage_7_docker_offer=MagicMock(return_value={}),
            stage_8_first_agent=MagicMock(return_value={}),
            stage_9_ping_sweep=MagicMock(return_value={}),
            stage_10_smoke_test=MagicMock(return_value={}),
            stage_11_handoff=MagicMock(return_value={}),
            stage_12_done=MagicMock(return_value={}),
            warning=MagicMock(),
            console=MagicMock(),
        ):
            run_init(non_interactive=True)
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
            detect_docker=MagicMock(return_value=True),
        ):
            result = stage_2_system_detect(non_interactive=True)
        assert result["os"] == "Linux"
        assert result["python"] == "3.12.0"
        assert result["shell"] == "bash"
        assert result["has_docker"] is True

    def test_stage_3_doctor_no_errors(self, tmp_local_json) -> None:
        """stage_3_doctor with 0 errors returns doctor_errors=0."""
        with patch(f"{_MOD}.console"):
            with patch("aipass.aipass.apps.modules.doctor.run_doctor", return_value=0):
                result = stage_3_doctor(non_interactive=True)
        assert result["doctor_errors"] == 0

    def test_stage_3_doctor_with_errors(self, tmp_local_json) -> None:
        """stage_3_doctor with errors emits warning but continues."""
        with patch(f"{_MOD}.console"):
            with patch(f"{_MOD}.warning"):
                with patch("aipass.aipass.apps.modules.doctor.run_doctor", return_value=2):
                    result = stage_3_doctor(non_interactive=True)
        assert result["doctor_errors"] == 2

    def test_stage_3_doctor_import_failure(self, tmp_local_json) -> None:
        """stage_3_doctor handles run_doctor exception gracefully."""
        with patch(f"{_MOD}.console"):
            with patch(f"{_MOD}.warning"):
                with patch("aipass.aipass.apps.modules.doctor.run_doctor", side_effect=Exception("fail")):
                    result = stage_3_doctor(non_interactive=True)
        assert result["doctor_errors"] == 0

    def test_stage_4_non_interactive_uses_default_name(self, tmp_local_json) -> None:
        """non_interactive=True sets name to 'User'."""
        mock_profile_mod = MagicMock()
        mock_profile_mod.get_user_profile.return_value = {
            f: None for f in ["name", "os", "shell", "preferred_cli", "install_method", "first_seen"]
        }
        with patch(f"{_MOD}.console"):
            with patch(f"{_MOD}.detect_os", return_value={"os_name": "Linux", "release": "6.0", "machine": "x86"}):
                with patch.dict("sys.modules", {"aipass.aipass.apps.modules.profile": mock_profile_mod}):
                    result = stage_4_user_profile(non_interactive=True)
        assert result["name"] == "User"

    def test_stage_4_name_override(self, tmp_local_json) -> None:
        """name_override parameter is used when provided."""
        mock_profile_mod = MagicMock()
        mock_profile_mod.get_user_profile.return_value = {
            f: None for f in ["name", "os", "shell", "preferred_cli", "install_method", "first_seen"]
        }
        with patch(f"{_MOD}.console"):
            with patch(f"{_MOD}.detect_os", return_value={"os_name": "Linux", "release": "6.0", "machine": "x86"}):
                with patch.dict("sys.modules", {"aipass.aipass.apps.modules.profile": mock_profile_mod}):
                    result = stage_4_user_profile(non_interactive=True, name_override="Alice")
        assert result["name"] == "Alice"

    def test_stage_5_non_interactive_returns_first_choice(self, tmp_local_json) -> None:
        """non_interactive=True selects first STYLE_CHOICES entry."""
        with patch(f"{_MOD}.console"):
            result = stage_5_style_questions(non_interactive=True)
        assert "style" in result
        assert result["style"] is not None

    def test_stage_5_style_override(self, tmp_local_json) -> None:
        """style_override is honoured when it's a valid choice."""
        from aipass.aipass.apps.modules.init_flow import STYLE_CHOICES

        override = STYLE_CHOICES[0]
        with patch(f"{_MOD}.console"):
            result = stage_5_style_questions(non_interactive=True, style_override=override)
        assert result["style"] == override

    def test_stage_6_non_interactive_defaults_to_claude(self, tmp_local_json) -> None:
        """non_interactive=True selects 'claude' as CLI."""
        mock_profile_mod = MagicMock()
        mock_profile_mod.get_user_profile.return_value = {}
        with patch(f"{_MOD}.console"):
            with patch.dict("sys.modules", {"aipass.aipass.apps.modules.profile": mock_profile_mod}):
                result = stage_6_tool_choice(non_interactive=True)
        assert result["cli"] == "claude"
        assert result["flag_variant"] == "default"

    def test_stage_6_cli_override(self, tmp_local_json) -> None:
        """cli_override sets the CLI choice."""
        mock_profile_mod = MagicMock()
        mock_profile_mod.get_user_profile.return_value = {}
        with patch(f"{_MOD}.console"):
            with patch.dict("sys.modules", {"aipass.aipass.apps.modules.profile": mock_profile_mod}):
                result = stage_6_tool_choice(non_interactive=True, cli_override="codex")
        assert result["cli"] == "codex"

    def test_stage_7_skipped_when_no_docker(self, tmp_local_json) -> None:
        """Docker offer is skipped when has_docker=False."""
        with patch(f"{_MOD}.console"):
            result = stage_7_docker_offer(non_interactive=False, has_docker=False)
        assert result["docker"] == "skipped"

    def test_stage_7_skipped_when_no_docker_flag(self, tmp_local_json) -> None:
        """Docker offer is skipped when no_docker=True."""
        with patch(f"{_MOD}.console"):
            result = stage_7_docker_offer(non_interactive=False, no_docker=True, has_docker=True)
        assert result["docker"] == "skipped"

    def test_stage_7_skipped_when_non_interactive(self, tmp_local_json) -> None:
        """Docker offer is skipped in non-interactive mode."""
        with patch(f"{_MOD}.console"):
            result = stage_7_docker_offer(non_interactive=True, has_docker=True)
        assert result["docker"] == "skipped"

    def test_stage_8_non_interactive_creates_my_agent(self, tmp_local_json) -> None:
        """non_interactive=True uses 'my-agent' as default name."""
        mock_proc = MagicMock(returncode=0)
        with patch(f"{_MOD}.console"):
            with patch(f"{_MOD}.subprocess.run", return_value=mock_proc):
                with patch(f"{_MOD}._resolve_package_dir", return_value=None):
                    result = stage_8_first_agent(non_interactive=True)
        assert result["agent_name"] == "my-agent"
        assert result["agent_path"] == "src/my-agent"

    def test_stage_8_drone_not_found(self, tmp_local_json) -> None:
        """FileNotFoundError from drone is handled gracefully."""
        with patch(f"{_MOD}.console"):
            with patch(f"{_MOD}.warning"):
                with patch(f"{_MOD}.subprocess.run", side_effect=FileNotFoundError):
                    result = stage_8_first_agent(non_interactive=True)
        assert "agent_name" in result

    def test_stage_9_ping_sweep_calls_sweep(self, tmp_local_json) -> None:
        """stage_9_ping_sweep calls sweep_all_branches and returns results."""
        mock_ps = MagicMock()
        mock_ps.sweep_all_branches.return_value = {"drone": "ack", "prax": "timeout"}
        mock_ps.sweep_summary.return_value = "1 ack / 1 timeout / 0 error"
        with patch(f"{_MOD}.console"):
            with patch.dict("sys.modules", {"aipass.aipass.apps.handlers.ping_sweep": mock_ps}):
                result = stage_9_ping_sweep(non_interactive=True)
        assert "ping_results" in result

    def test_stage_10_smoke_test_both_found(self, tmp_local_json) -> None:
        """smoke test passes when both drone and aipass are on PATH."""
        with patch(f"{_MOD}.console"):
            with patch(f"{_MOD}.shutil.which", return_value="/usr/bin/drone"):
                result = stage_10_smoke_test()
        assert result["drone"] == "/usr/bin/drone"

    def test_stage_10_smoke_test_missing(self, tmp_local_json) -> None:
        """Warnings emitted when binaries not found."""
        with patch(f"{_MOD}.console"):
            with patch(f"{_MOD}.warning"):
                with patch(f"{_MOD}.shutil.which", return_value=None):
                    result = stage_10_smoke_test()
        assert result["drone"] is None
        assert result["aipass"] is None

    def test_stage_11_default_variant_no_flag(self, tmp_local_json) -> None:
        """Default flag variant does not append --dangerously-skip-permissions."""
        with patch(f"{_MOD}.console"):
            result = stage_11_handoff(cli_choice="claude", flag_variant="default", non_interactive=True)
        assert "--dangerously-skip-permissions" not in result["handoff_command"]

    def test_stage_11_skip_permissions_variant(self, tmp_local_json) -> None:
        """skip-permissions variant appends the flag for claude."""
        with patch(f"{_MOD}.console"):
            result = stage_11_handoff(cli_choice="claude", flag_variant="skip-permissions", non_interactive=True)
        assert "--dangerously-skip-permissions" in result["handoff_command"]

    def test_stage_11_handoff_command_contains_path(self, tmp_local_json) -> None:
        """Handoff command includes the agent path."""
        with patch(f"{_MOD}.console"):
            result = stage_11_handoff(agent_path="src/mybot", non_interactive=True)
        assert "src/mybot" in result["handoff_command"]

    def test_stage_12_done_returns_empty(self, tmp_local_json) -> None:
        """stage_12_done returns {} and marks stage 12 complete."""
        with patch(f"{_MOD}.console"):
            result = stage_12_done()
        assert result == {}
        stored = json.loads(tmp_local_json.read_text())
        assert stored["setup_progress"]["last_completed_stage"] == 12
