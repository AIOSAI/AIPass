# =================== AIPass ====================
# Name: test_init_flow.py
# Description: Tests for aipass init_flow Phase 3
# Version: 1.3.0
# Created: 2026-04-16
# Modified: 2026-10-27
# =============================================

"""Tests for apps/modules/init_flow.py and the handlers it drives."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that every stage function and helper in init_flow.py parses and imports
# seedgo: no-test-needed(documentation) — that the public stage_* functions carry docstrings

import json
from pathlib import Path
from typing import Generator
from unittest.mock import MagicMock, patch

import pytest

from aipass.aipass.apps.handlers.init.bootstrap import init_project
from aipass.aipass.apps.modules import doctor
from aipass.aipass.apps.modules.init_flow import (
    AIPASS_SPECIFIC_STAGES,
    STYLE_CHOICES,
    TEMPLATE_AIPASS,
    TEMPLATE_CHOICES,
    TEMPLATE_EMPTY,
    TOTAL_STAGES,
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


_POLICY_MOD = "aipass.aipass.apps.modules.init_flow"


@pytest.fixture
def tmp_local_json(tmp_path: Path) -> Generator[Path, None, None]:
    """Patch _get_local_json_path to return a temp path."""
    local_json = tmp_path / ".trinity" / "local.json"
    local_json.parent.mkdir(parents=True)
    with patch("aipass.aipass.apps.modules.init_flow._get_local_json_path", return_value=local_json):
        yield local_json


@pytest.fixture
def real_policy_resolver() -> None:
    """Opt a test out of the autouse policy redirect below, so the REAL resolver runs.

    Only for tests that reach the resolver through stage_1_welcome(dry_run=True):
    the dry run prints the resolved path and writes nothing, and they stand in a
    tmp_path project, so the real resolver cannot put a policy anywhere live.
    """
    return None


@pytest.fixture(autouse=True)
def test_write_policy_stays_in_tmp(tmp_path: Path, request: pytest.FixtureRequest) -> Generator[Path, None, None]:
    """No test in this file stamps a test-write policy into the real tree.

    A stray .aipass/test_write_policy.json shadows the live one: @hooks' gate reads
    the nearest copy first. Tests that patch the path themselves still win.
    """
    policy = tmp_path / "policy-home" / ".aipass" / "test_write_policy.json"
    if "real_policy_resolver" in request.fixturenames:
        yield policy
        return
    with patch(f"{_POLICY_MOD}._get_test_write_policy_path", return_value=policy):
        yield policy


@pytest.fixture
def tmp_local_json_with_progress(tmp_local_json: Path) -> Path:
    """Pre-populate local.json with setup_progress at stage 3."""
    data = {
        "setup_progress": {
            "last_completed_stage": 3,
            "stages": {"1": {}, "2": {}, "3": {}},
        }
    }
    tmp_local_json.write_text(json.dumps(data), encoding="utf-8")
    return tmp_local_json


def _info_line(capsys: pytest.CaptureFixture[str]) -> str:
    """Run `aipass init --info` through the command; return stdout, whitespace folded."""
    assert handle_command("init", ["--info"]) is True
    out, _err = capsys.readouterr()
    return " ".join(out.split())


class TestGetSetupProgress:
    """The progress reader, read through `aipass init --info`, the door that shows it."""

    def test_returns_defaults_when_no_file(self, tmp_local_json, capsys: pytest.CaptureFixture[str]) -> None:
        """No progress file reads as not started, and nothing is created by reading."""
        assert "Setup not started" in _info_line(capsys)
        assert not tmp_local_json.exists()

    def test_reads_existing_progress(self, tmp_local_json_with_progress, capsys: pytest.CaptureFixture[str]) -> None:
        """Stored progress is read back: stage 3 of the fixture is what the door reports."""
        assert f"stage 3/{TOTAL_STAGES} completed." in _info_line(capsys)

    def test_returns_defaults_on_missing_key(self, tmp_local_json, capsys: pytest.CaptureFixture[str]) -> None:
        """A file with no setup_progress key reads as not started, not as an error."""
        tmp_local_json.write_text(json.dumps({"user": {}}), encoding="utf-8")
        printed = _info_line(capsys)
        assert "Setup not started" in printed
        assert "In progress" not in printed

    def test_handles_corrupt_file(self, tmp_local_json, capsys: pytest.CaptureFixture[str]) -> None:
        """Corrupt JSON reads as not started, and the user is told the file is unreadable.

        Answered silently, the next saved stage replaces the unread progress unseen.
        Mutant: the unreadable-file warning() sent to logger.warning instead reddens this.
        """
        tmp_local_json.write_text("BAD JSON", encoding="utf-8")
        assert handle_command("init", ["--info"]) is True

        out, err = capsys.readouterr()
        assert "Setup not started" in out
        assert "Init progress file unreadable" in err
        assert "local.json" in err


class TestGetLastCompletedStage:
    """The last completed stage decides where `aipass init run` starts; read through the command."""

    @staticmethod
    def _first_stage_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> int:
        """Run `aipass init run` (empty template) with every stage stubbed; return the first stage called."""
        monkeypatch.chdir(tmp_path)
        names = [
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
        stubs = {name: MagicMock(return_value={}) for name in names}
        with (
            patch.multiple("aipass.aipass.apps.modules.init_flow", **stubs),
            pytest.raises(SystemExit),
        ):
            handle_command("init", ["run", "--template", TEMPLATE_EMPTY])
        return next(i for i, name in enumerate(names, start=1) if stubs[name].called)

    def test_returns_zero_on_fresh_state(self, tmp_local_json, tmp_path, monkeypatch) -> None:
        """Nothing completed: the run starts at stage 1."""
        assert self._first_stage_run(tmp_path, monkeypatch) == 1

    def test_returns_stage_number(self, tmp_local_json_with_progress, tmp_path, monkeypatch) -> None:
        """Three completed in the fixture: the run starts at stage 4."""
        assert self._first_stage_run(tmp_path, monkeypatch) == 4


class TestSaveStage:
    """The progress save, reached through the public stages that call it."""

    def test_saves_stage_data(self, tmp_local_json) -> None:
        """Stage data is written to setup_progress.stages."""
        stage_4_style_questions(non_interactive=True, style_override="just-exploring")
        stored = json.loads(tmp_local_json.read_text(encoding="utf-8"))
        assert stored["setup_progress"]["last_completed_stage"] == 4
        assert stored["setup_progress"]["stages"]["4"]["style"] == "just-exploring"

    def test_save_increments_last_completed(self, tmp_local_json) -> None:
        """last_completed_stage advances after each save."""
        stage_4_style_questions(non_interactive=True)
        stage_10_done()
        stored = json.loads(tmp_local_json.read_text(encoding="utf-8"))
        assert stored["setup_progress"]["last_completed_stage"] == 10

    def test_preserves_existing_stages(self, tmp_local_json_with_progress: Path) -> None:
        """Earlier stage data is not overwritten when saving a later stage."""
        stage_4_style_questions(non_interactive=True)
        stored = json.loads(tmp_local_json_with_progress.read_text(encoding="utf-8"))
        assert "1" in stored["setup_progress"]["stages"]
        assert "4" in stored["setup_progress"]["stages"]

    def test_unreadable_progress_is_replaced_by_the_saved_stage(self, tmp_local_json) -> None:
        """A progress file that is not JSON is replaced by a fresh record holding the stage.

        Mutant: _save_stage's None guard removed -> red by the escaping AttributeError on None.get, not by the assert.
        Mutant: guard turned into a plain return -> red by the assert on the file.
        """
        tmp_local_json.write_text("{not json", encoding="utf-8")
        stage_10_done()
        text = tmp_local_json.read_text(encoding="utf-8")
        assert text != "{not json"
        stored = json.loads(text)
        assert stored["setup_progress"]["last_completed_stage"] == 10
        assert "10" in stored["setup_progress"]["stages"]

    def test_timestamps_stage(self, tmp_local_json) -> None:
        """Saved stage includes a 'timestamp' field."""
        stage_10_done()
        stored = json.loads(tmp_local_json.read_text(encoding="utf-8"))
        assert "timestamp" in stored["setup_progress"]["stages"]["10"]

    def test_stamps_test_write_policy_in_hooks_shape(self, tmp_local_json, capsys: pytest.CaptureFixture[str]) -> None:
        """A fresh init stamps the policy in the exact shape @hooks' reader validates.

        agent_test_writing is the STRING "off" (a boolean is REFUSED), allow is an
        array, block_test_edits a bool.
        """
        policy = tmp_local_json.parent.parent / ".aipass" / "test_write_policy.json"
        with patch(
            "aipass.aipass.apps.modules.init_flow._get_test_write_policy_path",
            return_value=policy,
        ):
            stage_1_welcome()

        assert "Test-write policy stamped (gate off)" in capsys.readouterr().out
        stored = json.loads(policy.read_text(encoding="utf-8"))
        assert stored["agent_test_writing"] == "off"
        assert not isinstance(stored["agent_test_writing"], bool)
        assert stored["allow"] == []
        assert stored["block_test_edits"] is False

    @staticmethod
    def _dry_run_policy_target(capsys: pytest.CaptureFixture[str]) -> str:
        """Run stage 1 as a dry run; return where it says it would stamp, whitespace folded out."""
        capsys.readouterr()
        stage_1_welcome(dry_run=True)
        printed = "".join(capsys.readouterr().out.split())
        marker = "wouldstamptest-writepolicyat"
        assert marker in printed
        return printed.split(marker, 1)[1]

    def test_policy_path_is_the_registry_root_not_cwd(
        self, tmp_path, monkeypatch, real_policy_resolver, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The policy belongs to the project: a run from a subdirectory must not fork it.

        @hooks' gate reads the nearest policy first, so a second one shadows it.
        Mutant: `registry.parent / ".aipass"` -> `Path.cwd() / ".aipass"` reddens this.
        """
        project = tmp_path / "project"
        (project / "src" / "aipass" / "aipass").mkdir(parents=True)
        (project / "PROJECT_REGISTRY.json").write_text('{"branches": []}', encoding="utf-8")
        monkeypatch.chdir(project / "src" / "aipass" / "aipass")
        monkeypatch.delenv("AIPASS_REGISTRY", raising=False)

        target = self._dry_run_policy_target(capsys)

        assert target == "".join(str(project / ".aipass" / "test_write_policy.json").split())
        assert not (project / ".aipass").exists()

    def test_policy_path_falls_back_to_cwd_on_a_fresh_install(
        self, tmp_path, monkeypatch, real_policy_resolver, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """No registry yet means a fresh install: cwd IS the project root there (stage 1 dry run)."""
        fresh = tmp_path / "fresh"
        fresh.mkdir()
        monkeypatch.chdir(fresh)
        monkeypatch.delenv("AIPASS_REGISTRY", raising=False)
        with patch(f"{_MOD}.find_registry", return_value=None):
            target = self._dry_run_policy_target(capsys)

        assert target == "".join(str(fresh / ".aipass" / "test_write_policy.json").split())
        assert not (fresh / ".aipass").exists()

    def test_stage_1_writes_no_policy_outside_the_project(self, tmp_local_json, tmp_path) -> None:
        """The door that leaked: stage 1 stamps only where the resolver points."""
        before = {p for p in Path.cwd().glob(".aipass/*")}

        stage_1_welcome()

        assert {p for p in Path.cwd().glob(".aipass/*")} == before

    def test_test_write_policy_is_never_clobbered(self, tmp_local_json, capsys: pytest.CaptureFixture[str]) -> None:
        """An existing policy may hold a deliberate flip — init must not repeal it (through stage 1)."""
        policy = tmp_local_json.parent.parent / ".aipass" / "test_write_policy.json"
        policy.parent.mkdir(parents=True, exist_ok=True)
        local_ruling = '{"agent_test_writing": "on", "allow": ["canary"]}'
        policy.write_text(local_ruling, encoding="utf-8")

        with patch(
            "aipass.aipass.apps.modules.init_flow._get_test_write_policy_path",
            return_value=policy,
        ):
            stage_1_welcome()

        assert policy.read_text(encoding="utf-8") == local_ruling
        assert "Test-write policy stamped" not in capsys.readouterr().out

    def test_write_goes_through_the_json_service(self, tmp_local_json) -> None:
        """The progress write routes through the fleet service, not a hand-rolled writer.

        Asserting the service is CALLED stops a second writer creeping back in.
        """
        with patch(
            "aipass.aipass.apps.modules.init_flow.json_handler.write_json",
            return_value=True,
        ) as mock_write:
            stage_4_style_questions(non_interactive=True, style_override="just-exploring")

        mock_write.assert_called_once()
        written_path, written_data = mock_write.call_args[0][0], mock_write.call_args[0][1]
        assert Path(written_path) == tmp_local_json
        assert written_data["setup_progress"]["stages"]["4"]["style"] == "just-exploring"

    def test_failed_write_raises_instead_of_answering_false(self, tmp_local_json) -> None:
        """A lost init stage must not look identical to a saved one.

        The service answers False; callers expect OSError, so False becomes one.
        The trigger is patched where init_flow imports it at fire time, so no event
        reaches the real bus.
        Mutant: the fired event renamed "profile_write_failed" -> "file_deleted" reddens this.
        """
        with (
            patch(
                "aipass.aipass.apps.modules.init_flow.json_handler.write_json",
                return_value=False,
            ),
            patch("aipass.trigger.apps.modules.core.trigger") as mock_trigger,
        ):
            with pytest.raises(OSError):
                stage_10_done()

        mock_trigger.fire.assert_called_once_with(
            "profile_write_failed", path=str(tmp_local_json), reason="write_failure_cleanup"
        )


class TestPrintIntrospection:
    def test_not_started(self, tmp_local_json, capsys: pytest.CaptureFixture[str]) -> None:
        """Stage 0 prints the not-started line and the command that starts it.

        Mutant: the line cut to "Setup not started." reddens this.
        """
        print_introspection()
        out, _err = capsys.readouterr()
        assert "Setup not started. Run: aipass init run" in " ".join(out.split())

    def test_in_progress(self, tmp_local_json_with_progress, capsys: pytest.CaptureFixture[str]) -> None:
        """A part-done setup prints the stage reached and where it resumes.

        Mutant: "resume from stage {last}" in place of {last + 1} reddens this.
        """
        print_introspection()
        out, _err = capsys.readouterr()
        printed = " ".join(out.split())
        assert f"stage 3/{TOTAL_STAGES} completed." in printed
        assert "resume from stage 4" in printed

    def test_complete(self, tmp_local_json, capsys: pytest.CaptureFixture[str]) -> None:
        """A finished setup reports completion through success(), not a stage line.

        Mutant: `last > TOTAL_STAGES` in place of `>=` reddens this.
        """
        data = {"setup_progress": {"last_completed_stage": TOTAL_STAGES, "stages": {}}}
        tmp_local_json.write_text(json.dumps(data), encoding="utf-8")
        with patch("aipass.aipass.apps.modules.init_flow.success") as mock_success:
            print_introspection()
        out, _err = capsys.readouterr()
        assert mock_success.call_args[0][0] == "Setup complete."
        assert "In progress:" not in out


class TestPrintHelp:
    def test_calls_console_print(self, capsys: pytest.CaptureFixture[str]) -> None:
        """print_help outputs via console.print.

        Mutant: the "init update --dry-run" usage line renamed to --preview reddens this.
        """
        print_help()
        out, _err = capsys.readouterr()
        assert "aipass init update --dry-run" in out


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

    def test_run_subcommand_calls_run_init(
        self, tmp_local_json: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, isolate_profile_store: Path
    ) -> None:
        """'init run --name --style' routes to run_init, and the two flags land.

        Stages 3 and 4 run for real against temp stores. "just-exploring" is not the
        non-interactive default, so a dropped --style cannot pass by luck.
        Mutant: `name = _flag_value("--name")` -> `name = None` reddens this.
        Mutant: `style = _flag_value("--style")` -> `style = None` reddens this.
        """
        monkeypatch.chdir(tmp_path)
        stubbed = {
            name: MagicMock(return_value={})
            for name in (
                "stage_1_welcome",
                "stage_2_system_detect",
                "stage_5_tool_choice",
                "stage_6_first_agent",
                "stage_7_ping_sweep",
                "stage_8_smoke_test",
                "stage_9_handoff",
                "stage_10_done",
            )
        }
        with (
            patch.multiple("aipass.aipass.apps.modules.init_flow", **stubbed),
            patch("aipass.aipass.apps.modules.profile.json_handler.log_operation"),
            pytest.raises(SystemExit) as exc_info,
        ):
            run_args = ["run", "--non-interactive", "--template", TEMPLATE_EMPTY]
            handle_command("init", [*run_args, "--name", "Ada", "--style", "just-exploring"])
        assert exc_info.value.code == 0
        stored = json.loads((isolate_profile_store / "user_profile.json").read_text(encoding="utf-8"))
        assert stored["profile"]["name"] == "Ada"
        progress = json.loads(tmp_local_json.read_text(encoding="utf-8"))["setup_progress"]["stages"]
        assert progress["3"]["name"] == "Ada"
        assert progress["4"]["style"] == "just-exploring"

    def test_positional_args_treated_as_scaffold_target(self, tmp_local_json) -> None:
        """Positional args are treated as target path for scaffold."""
        with patch("aipass.aipass.apps.modules.init_flow._preflight_check", return_value=None):
            with patch("aipass.aipass.apps.modules.init_flow._handle_init_scaffold", return_value=0) as mock_scaffold:
                with pytest.raises(SystemExit) as exc_info:
                    handle_command("init", ["test-proj"])
        assert exc_info.value.code == 0
        mock_scaffold.assert_called_once_with(["test-proj"])

    def test_a_target_is_scaffolded_from_inside_an_agent_branch(self, tmp_path, monkeypatch) -> None:
        """The branch guard reads the target, so `init <target>` works from a citizen's seat."""
        seat = tmp_path / "seat"
        (seat / ".trinity").mkdir(parents=True)
        (seat / ".trinity" / "passport.json").write_text("{}", encoding="utf-8")
        monkeypatch.chdir(seat)
        with patch("aipass.aipass.apps.modules.init_flow._handle_init_scaffold", return_value=0) as mock_scaffold:
            with pytest.raises(SystemExit) as exc_info:
                handle_command("init", [str(tmp_path / "proj")])
        assert exc_info.value.code == 0
        mock_scaffold.assert_called_once_with([str(tmp_path / "proj")])

    def test_a_flag_after_the_target_is_refused_and_nothing_is_scaffolded(self, tmp_path, capsys) -> None:
        with pytest.raises(SystemExit) as exc_info:
            handle_command("init", [str(tmp_path / "demo"), "--dry-run"])

        assert exc_info.value.code == 1
        _out, err = capsys.readouterr()
        assert "takes no flags (got --dry-run)" in " ".join(err.split())
        assert not (tmp_path / "demo").exists()


@pytest.fixture(autouse=True)
def _bypass_preflight():
    """All TestRunInit tests run outside a real AIPass project — bypass the guard."""
    with patch("aipass.aipass.apps.modules.init_flow._preflight_check", return_value=None):
        yield


_MOD_RUN = "aipass.aipass.apps.modules.init_flow"


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
        tmp_local_json.write_text(json.dumps(data), encoding="utf-8")
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
            with patch("aipass.aipass.apps.modules.init_flow.json_handler", autospec=True):
                result = run_init(non_interactive=True, template=TEMPLATE_AIPASS)
        assert result == 0

    def test_keyboard_interrupt_pauses_gracefully(self, tmp_local_json, capsys: pytest.CaptureFixture[str]) -> None:
        """Ctrl-C during a stage pauses with a resume hint and exits 130, never 0.

        Exit 0 would let `aipass init run && next-step` go on after the user stopped it.
        Mutant: the paused `return 130` put back to `return 0` reddens this.
        """
        with (
            patch("aipass.aipass.apps.modules.init_flow.stage_1_welcome", side_effect=KeyboardInterrupt),
            pytest.raises(SystemExit) as exit_info,
        ):
            handle_command("init", ["run", "--template", TEMPLATE_EMPTY])

        assert exit_info.value.code == 130
        _out, err = capsys.readouterr()
        assert "Paused at stage 1. Run 'aipass init run' to resume." in err

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
        ):
            run_init(non_interactive=True, template=TEMPLATE_AIPASS)
        stage_1_mock.assert_not_called()
        stage_4_mock.assert_called_once()

    @staticmethod
    def _paused_after_stage_5(tmp_local_json: Path, tmp_path: Path) -> None:
        """A framework run paused after stage 5: its scaffold registry is in cwd, the cli choice saved."""
        (tmp_path / "DEMO_REGISTRY.json").write_text("{}", encoding="utf-8")
        stages = {str(n): {"status": "done", "timestamp": "t"} for n in range(1, 6)}
        stages["5"].update({"cli": "codex", "flag_variant": "skip-permissions"})
        data = {"setup_progress": {"last_completed_stage": 5, "stages": stages}}
        tmp_local_json.write_text(json.dumps(data), encoding="utf-8")

    def test_resume_is_not_refused_by_its_own_registry(self, tmp_local_json, tmp_path) -> None:
        """The registry stage 4 wrote does not make the pre-flight refuse the resume."""
        self._paused_after_stage_5(tmp_local_json, tmp_path)
        later = ("stage_6_first_agent", "stage_7_ping_sweep", "stage_8_smoke_test", "stage_9_handoff", "stage_10_done")
        with (
            patch.multiple(_MOD_RUN, warning=MagicMock(), **{name: MagicMock(return_value={}) for name in later}),
            patch(f"{_MOD_RUN}._preflight_check", return_value="Already inside an AIPass project"),
        ):
            assert run_init(non_interactive=True, template=TEMPLATE_AIPASS) == 0

    def test_resume_keeps_the_saved_cli_choice(self, tmp_local_json, tmp_path) -> None:
        """Stage 9 hands off with the cli picked at stage 5 before the pause, not the default."""
        self._paused_after_stage_5(tmp_local_json, tmp_path)
        handoff = MagicMock(return_value={})
        with patch.multiple(
            _MOD_RUN,
            warning=MagicMock(),
            stage_6_first_agent=MagicMock(return_value={}),
            stage_7_ping_sweep=MagicMock(return_value={}),
            stage_8_smoke_test=MagicMock(return_value={}),
            stage_9_handoff=handoff,
            stage_10_done=MagicMock(return_value={}),
        ):
            run_init(non_interactive=True, template=TEMPLATE_AIPASS)
        assert handoff.call_args.args[:2] == ("codex", "skip-permissions")


_MOD = "aipass.aipass.apps.modules.init_flow"


class TestStages:
    """Unit tests for individual stage functions (non-interactive paths)."""

    def test_stage_1_welcome_returns_dict(self, tmp_local_json) -> None:
        """stage_1_welcome runs and returns {}."""
        result = stage_1_welcome()
        assert result == {}
        stored = json.loads(tmp_local_json.read_text(encoding="utf-8"))
        assert stored["setup_progress"]["last_completed_stage"] == 1

    def test_stage_2_system_detect_returns_system_data(self, tmp_local_json) -> None:
        """stage_2_system_detect returns dict with os/python/shell keys."""
        with patch.multiple(
            _MOD,
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
            result = stage_2_system_detect()
        assert result["os"] == "Linux"
        assert result["python"] == "3.12.0"
        assert result["shell"] == "bash"

    def test_stage_3_non_interactive_uses_default_name(self, tmp_local_json) -> None:
        """non_interactive=True sets name to 'User'."""
        mock_profile_mod = MagicMock()
        mock_profile_mod.get_user_profile.return_value = {
            f: None for f in ["name", "os", "shell", "preferred_cli", "install_method", "first_seen"]
        }
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
        with patch(f"{_MOD}.detect_os", return_value={"os_name": "Linux", "release": "6.0", "machine": "x86"}):
            with patch.dict("sys.modules", {"aipass.aipass.apps.modules.profile": mock_profile_mod}):
                result = stage_3_user_profile(non_interactive=True, name_override="user")
        assert result["name"] == "user"

    def test_stage_4_non_interactive_returns_first_choice(self, tmp_local_json) -> None:
        """non_interactive=True selects first STYLE_CHOICES entry.

        Mutant: STYLE_CHOICES[0] -> STYLE_CHOICES[1] in the non-interactive branch -> red.
        """
        result = stage_4_style_questions(non_interactive=True)
        assert result["style"] == "building-my-own-project"

    def test_stage_4_style_override(self, tmp_local_json) -> None:
        """style_override is honoured when it's a valid choice."""
        override = STYLE_CHOICES[0]
        result = stage_4_style_questions(non_interactive=True, style_override=override)
        assert result["style"] == override

    def test_stage_5_non_interactive_defaults_to_claude(self, tmp_local_json) -> None:
        """non_interactive=True selects 'claude' as CLI."""
        mock_profile_mod = MagicMock()
        mock_profile_mod.get_user_profile.return_value = {}
        with patch.dict("sys.modules", {"aipass.aipass.apps.modules.profile": mock_profile_mod}):
            result = stage_5_tool_choice(non_interactive=True)
        assert result["cli"] == "claude"
        assert result["flag_variant"] == "default"

    def test_stage_5_cli_override(self, tmp_local_json) -> None:
        """cli_override sets the CLI choice."""
        mock_profile_mod = MagicMock()
        mock_profile_mod.get_user_profile.return_value = {}
        with patch.dict("sys.modules", {"aipass.aipass.apps.modules.profile": mock_profile_mod}):
            result = stage_5_tool_choice(non_interactive=True, cli_override="codex")
        assert result["cli"] == "codex"

    def test_stage_5_claude_present_no_prompt(self, tmp_local_json, tools_on_path) -> None:
        """When claude is on PATH, no install prompt is shown. PATH holds a claude stub."""
        mock_profile_mod = MagicMock()
        mock_profile_mod.get_user_profile.return_value = {}
        tools_on_path("claude")
        with patch.dict("sys.modules", {"aipass.aipass.apps.modules.profile": mock_profile_mod}):
            with patch(f"{_MOD}._handle_missing_claude") as mock_handle:
                result = stage_5_tool_choice(non_interactive=True)
        mock_handle.assert_not_called()
        assert result["cli"] == "claude"

    @patch(f"{_MOD}._choose", return_value="default")
    @patch(f"{_MOD}._install_claude_code", return_value=True)
    @patch(f"{_MOD}._prompt", return_value="Y")
    def test_stage_5_claude_missing_interactive_yes(
        self, _prompt, mock_install, _choose, tmp_local_json, tools_on_path
    ) -> None:
        """Missing claude + interactive + yes → installer invoked. PATH is an empty directory."""
        tools_on_path()
        mock_profile_mod = MagicMock()
        mock_profile_mod.get_user_profile.return_value = {}
        with patch.dict("sys.modules", {"aipass.aipass.apps.modules.profile": mock_profile_mod}):
            result = stage_5_tool_choice(non_interactive=False, cli_override="claude")
        mock_install.assert_called_once()
        assert result["cli"] == "claude"

    @patch(f"{_MOD}._choose", return_value="default")
    @patch(f"{_MOD}._install_claude_code")
    @patch(f"{_MOD}._prompt", return_value="n")
    def test_stage_5_claude_missing_interactive_no(
        self, mock_prompt, mock_install, _choose, tmp_local_json, tools_on_path
    ) -> None:
        """Missing claude + interactive + no → asked, no install, continues. PATH is an empty directory.

        Mutant: claude never counted missing -> red at the prompt assert; "nothing installed"
        alone is also passed by a stage that never asks.
        """
        tools_on_path()
        mock_profile_mod = MagicMock()
        mock_profile_mod.get_user_profile.return_value = {}
        with patch.dict("sys.modules", {"aipass.aipass.apps.modules.profile": mock_profile_mod}):
            result = stage_5_tool_choice(non_interactive=False, cli_override="claude")
        mock_prompt.assert_called_once()
        mock_install.assert_not_called()
        assert result["cli"] == "claude"

    @patch(f"{_MOD}.warning")
    @patch(f"{_MOD}._install_claude_code")
    def test_stage_5_claude_missing_non_interactive_warns(
        self, mock_install, mock_warn, tmp_local_json, tools_on_path
    ) -> None:
        """Missing claude + non-interactive → warning, no install. PATH is an empty directory."""
        tools_on_path()
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
        with patch(f"{_MOD}.subprocess.run", return_value=mock_proc):
            with patch(f"{_MOD}._resolve_package_dir", return_value=None):
                result = stage_6_first_agent(non_interactive=True)
        assert result["agent_name"] == "my_agent"
        assert result["agent_path"] == "src/my_agent"

    def test_stage_6_drone_not_found(self, tmp_local_json) -> None:
        """FileNotFoundError from drone is handled gracefully."""
        with patch(f"{_MOD}.warning"):
            with patch(f"{_MOD}.subprocess.run", side_effect=FileNotFoundError):
                result = stage_6_first_agent(non_interactive=True)
        assert "agent_name" in result

    def test_stage_7_ping_sweep_calls_sweep(self, tmp_local_json) -> None:
        """stage_7_ping_sweep calls sweep_all_branches and returns results."""
        mock_ps = MagicMock()
        mock_ps.sweep_all_branches.return_value = {"drone": "ack", "prax": "timeout"}
        mock_ps.sweep_summary.return_value = "1 ack / 1 timeout / 0 error"
        with patch.dict("sys.modules", {"aipass.aipass.apps.handlers.ping_sweep": mock_ps}):
            result = stage_7_ping_sweep()
        assert "ping_results" in result

    def test_stage_8_smoke_test_both_found(self, tmp_local_json, tools_on_path) -> None:
        """smoke test reports where drone and aipass sit on PATH (stubs in a tmp directory).

        Compared as Path objects, by parent and stem: Windows gives the stub a PATHEXT suffix.
        """
        bin_dir = tools_on_path("drone", "aipass")
        result = stage_8_smoke_test()
        for name in ("drone", "aipass"):
            found = result[name]
            assert found is not None, f"{name} not found on PATH"
            assert (Path(found).parent, Path(found).stem) == (bin_dir, name)

    def test_stage_8_smoke_test_missing(self, tmp_local_json, tools_on_path) -> None:
        """Warnings emitted when binaries not found. PATH is an empty directory."""
        tools_on_path()
        with patch(f"{_MOD}.warning"):
            result = stage_8_smoke_test()
        assert result["drone"] is None
        assert result["aipass"] is None

    def test_stage_9_default_variant_no_flag(self, tmp_local_json) -> None:
        """Default flag variant does not append --dangerously-skip-permissions."""
        result = stage_9_handoff(cli_choice="claude", flag_variant="default", non_interactive=True)
        assert "--dangerously-skip-permissions" not in result["handoff_command"]

    def test_stage_9_skip_permissions_variant(self, tmp_local_json) -> None:
        """skip-permissions variant appends the flag for claude."""
        result = stage_9_handoff(cli_choice="claude", flag_variant="skip-permissions", non_interactive=True)
        assert "--dangerously-skip-permissions" in result["handoff_command"]

    def test_stage_9_handoff_command_contains_path(self, tmp_local_json) -> None:
        """Handoff command includes the agent path."""
        result = stage_9_handoff(agent_path="src/mybot", non_interactive=True)
        assert "src/mybot" in result["handoff_command"]

    def test_stage_9_non_interactive_no_spawn(self, tmp_local_json) -> None:
        """Non-interactive stage 9 prints the command but never spawns a session."""
        with patch("aipass.aipass.apps.modules.handoff.do_handoff") as mock_handoff:
            result = stage_9_handoff(non_interactive=True)
        mock_handoff.assert_not_called()
        assert result["launched"] is False
        assert result["handoff_command"]

    def test_stage_10_done_returns_empty(self, tmp_local_json) -> None:
        """stage_10_done returns {} and marks stage 10 complete."""
        result = stage_10_done()
        assert result == {}
        stored = json.loads(tmp_local_json.read_text(encoding="utf-8"))
        assert stored["setup_progress"]["last_completed_stage"] == 10


class TestProviderGaps:
    """Provider gaps reach the init report without running the full doctor."""

    @staticmethod
    def _report_from_stage_10(tmp_path: Path) -> dict:
        """Run the public stage 10 for an agent under tmp_path; return the init report it dropped."""
        agent_dir = tmp_path / "src" / "bot"
        agent_dir.mkdir(parents=True)
        stage_10_done(accumulated={"agent_path": str(agent_dir), "agent_name": "BOT"})
        return json.loads((agent_dir / "dropbox" / "init_report.json").read_text(encoding="utf-8"))

    def test_collect_provider_gaps_reports_missing(self, tmp_local_json, tmp_path: Path) -> None:
        """Only non-pass manifest results reach the report; run_doctor is never called."""
        gap = MagicMock(glyph="WARN", label="hooks", detail="wire the hook")
        passing = MagicMock(glyph=doctor.GLYPH_PASS, label="env", detail="")
        with patch.object(doctor, "check_provider_manifest", return_value=[gap, passing]):
            with patch.object(doctor, "run_doctor") as mock_run:
                report = self._report_from_stage_10(tmp_path)
        assert report["provider_gaps"] == {"hooks": "wire the hook"}
        mock_run.assert_not_called()

    def test_collect_provider_gaps_swallows_errors(self, tmp_local_json, tmp_path: Path) -> None:
        """A failing manifest check still drops the report, with no gaps claimed, not a crash."""
        with patch.object(doctor, "check_provider_manifest", side_effect=RuntimeError("boom")):
            with patch(f"{_MOD}.logger"):
                report = self._report_from_stage_10(tmp_path)
        assert report["agent_name"] == "BOT"
        assert "provider_gaps" not in report

    def test_init_report_includes_provider_gaps(self, tmp_local_json, tmp_path: Path) -> None:
        """The init report embeds provider gaps + action when the manifest reports them."""
        gap = MagicMock(glyph="WARN", label="hooks", detail="missing")
        with patch.object(doctor, "check_provider_manifest", return_value=[gap]):
            report = self._report_from_stage_10(tmp_path)
        assert report["provider_gaps"] == {"hooks": "missing"}
        assert "provider_action" in report

    def test_init_report_omits_provider_gaps_when_clean(self, tmp_local_json, tmp_path: Path) -> None:
        """No provider keys are written when the manifest is fully satisfied."""
        passing = MagicMock(glyph=doctor.GLYPH_PASS, label="env", detail="")
        with patch.object(doctor, "check_provider_manifest", return_value=[passing]):
            report = self._report_from_stage_10(tmp_path)
        assert "provider_gaps" not in report
        assert "provider_action" not in report


_MOD_UPDATE = "aipass.aipass.apps.modules.init_flow"
# The owner check runs in install's _check_and_fix_owner, so its lines print through install's success.
_MOD_INSTALL = "aipass.aipass.apps.modules.install"


def _init_update(args: list[str]) -> int:
    """Run `aipass init update <args>` through the command and return its exit code.

    The command's router ends in sys.exit with the handler's answer, so the
    code a shell sees is read off the SystemExit, not the private handler.
    """
    with pytest.raises(SystemExit) as exit_info:
        handle_command("init", ["update", *args])
    code = exit_info.value.code
    assert isinstance(code, int)
    return code


class TestInitUpdateRegistrySync:
    """Tests for owner/identity check+fix in `aipass init update`.

    Git-auth provisioning is stubbed: it needs a real project on disk and has its own suite below.
    """

    def test_clean_check_prints_ok(self, tmp_path: Path) -> None:
        """Clean --check (exit 0) prints 'Owner/identity OK.' and skips --fix."""
        check_proc = MagicMock(returncode=0, stdout="", stderr="")
        with (
            patch(
                "aipass.aipass.apps.handlers.init.bootstrap.update_project",
                return_value={"updated_files": [], "already_current": []},
            ),
            patch(f"{_MOD_UPDATE}._run_git_auth_provisioning", return_value=0),
            patch(f"{_MOD_UPDATE}.subprocess.run", return_value=check_proc) as mock_run,
            patch(f"{_MOD_INSTALL}.success") as mock_success,
            patch(f"{_MOD_UPDATE}.json_handler", autospec=True),
        ):
            rc = _init_update([str(tmp_path)])
        assert rc == 0
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert "--check" in args
        assert mock_run.call_args.kwargs["cwd"] == str(tmp_path)
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
            patch(f"{_MOD_UPDATE}._run_git_auth_provisioning", return_value=0),
            patch(
                f"{_MOD_UPDATE}.subprocess.run",
                side_effect=[check_proc, fix_proc],
            ) as mock_run,
            patch(f"{_MOD_INSTALL}.success") as mock_success,
            patch(f"{_MOD_INSTALL}.warning"),
            patch(f"{_MOD_UPDATE}.json_handler", autospec=True),
        ):
            rc = _init_update([str(tmp_path)])
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
            patch(f"{_MOD_UPDATE}._run_git_auth_provisioning", return_value=0),
            patch(
                f"{_MOD_UPDATE}.subprocess.run",
                side_effect=[check_proc, fix_proc],
            ),
            patch(f"{_MOD_UPDATE}.warning"),
            patch(f"{_MOD_UPDATE}.json_handler", autospec=True),
        ):
            rc = _init_update([str(tmp_path)])
        assert rc == 0

    def test_sync_missing_drone_degrades_silently(self, tmp_path: Path) -> None:
        """FileNotFoundError (no drone binary) degrades gracefully."""
        with (
            patch(
                "aipass.aipass.apps.handlers.init.bootstrap.update_project",
                return_value={"updated_files": [], "already_current": []},
            ),
            patch(f"{_MOD_UPDATE}._run_git_auth_provisioning", return_value=0),
            patch(f"{_MOD_UPDATE}.subprocess.run", side_effect=FileNotFoundError("drone not found")),
            patch(f"{_MOD_UPDATE}.json_handler", autospec=True),
        ):
            rc = _init_update([str(tmp_path)])
        assert rc == 0

    def test_sync_timeout_degrades_silently(self, tmp_path: Path) -> None:
        """subprocess.TimeoutExpired degrades gracefully."""
        import subprocess as _sp

        with (
            patch(
                "aipass.aipass.apps.handlers.init.bootstrap.update_project",
                return_value={"updated_files": [], "already_current": []},
            ),
            patch(f"{_MOD_UPDATE}._run_git_auth_provisioning", return_value=0),
            patch(f"{_MOD_UPDATE}.subprocess.run", side_effect=_sp.TimeoutExpired(cmd="drone", timeout=30)),
            patch(f"{_MOD_UPDATE}.json_handler", autospec=True),
        ):
            rc = _init_update([str(tmp_path)])
        assert rc == 0

    def test_an_unavailable_trust_registry_is_said_not_skipped(self, tmp_path: Path) -> None:
        """trust_enrolled None (hooks' registry could not be imported) is warned with
        the command that enrolls later; a refusal (False) stays silent as before.

        Mutant: the `trust_enrolled is None` warning arm deleted -> red.
        """
        with (
            patch(
                "aipass.aipass.apps.handlers.init.bootstrap.update_project",
                return_value={"updated_files": [], "already_current": [], "trust_enrolled": None},
            ),
            patch(f"{_MOD_UPDATE}._run_git_auth_provisioning", return_value=0),
            patch(f"{_MOD_UPDATE}.subprocess.run", return_value=MagicMock(returncode=0, stdout="", stderr="")),
            patch(f"{_MOD_UPDATE}.warning") as mock_warning,
            patch(f"{_MOD_UPDATE}.json_handler", autospec=True),
        ):
            rc = _init_update([str(tmp_path)])
        assert rc == 0
        warned = [str(c) for c in mock_warning.call_args_list]
        assert any("aipass trust" in w and "unavailable" in w for w in warned), warned


class TestInitUpdateGitAuth:
    """Tests for git-auth provisioning wired into `aipass init update`."""

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
            patch(f"{_MOD_UPDATE}.success") as mock_success,
            patch(f"{_MOD_UPDATE}.json_handler", autospec=True),
        ):
            rc = _init_update([str(tmp_path)])

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
            patch(f"{_MOD_UPDATE}.success") as mock_success,
            patch(f"{_MOD_UPDATE}.json_handler", autospec=True),
        ):
            rc = _init_update([str(tmp_path)])

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
            patch(f"{_MOD_UPDATE}.success"),
            patch(f"{_MOD_UPDATE}.cli_error") as mock_error,
            patch(f"{_MOD_UPDATE}.json_handler", autospec=True),
        ):
            rc = _init_update([str(tmp_path)])

        assert rc == 1
        assert any('"owner": true' in str(c) for c in mock_error.call_args_list)

    def test_dry_run_plans_the_scaffold_and_writes_nothing(self, tmp_path: Path) -> None:
        """--dry-run touches nothing: the plan is computed with apply=False, no sync-registry.

        The pin is that update_project is CALLED and told not to write, not skipped.
        """
        self._project(tmp_path)
        passport_path = tmp_path / "src" / "demo" / "vera" / ".trinity" / "passport.json"
        before = passport_path.read_text(encoding="utf-8")

        with (
            patch(
                "aipass.aipass.apps.handlers.init.bootstrap.update_project",
                return_value={"updated_files": [], "already_current": [], "pending": False},
            ) as mock_update,
            patch(f"{_MOD_UPDATE}.subprocess.run") as mock_run,
            patch(f"{_MOD_UPDATE}.success") as mock_success,
            patch(f"{_MOD_UPDATE}.json_handler", autospec=True),
        ):
            rc = _init_update([str(tmp_path), "--dry-run"])

        assert rc == 0
        mock_update.assert_called_once()
        assert mock_update.call_args.kwargs["apply"] is False
        mock_run.assert_not_called()
        assert passport_path.read_text(encoding="utf-8") == before
        assert any("would repair" in str(c) for c in mock_success.call_args_list)

    def test_dry_run_exits_2_when_the_scaffold_is_behind(self, tmp_path: Path) -> None:
        """Exit 2 is the "there is a plan to read" signal; 0 means nothing to do.

        A manager (or a script) has to tell those apart without parsing output,
        so the code is the contract, not the text.
        """
        self._project(tmp_path)
        plan = {"updated_files": [], "already_current": [], "pending": True}

        with (
            patch("aipass.aipass.apps.handlers.init.bootstrap.update_project", return_value=plan),
            patch(f"{_MOD_UPDATE}.subprocess.run") as mock_run,
            patch(f"{_MOD_UPDATE}.success"),
            patch(f"{_MOD_UPDATE}.json_handler", autospec=True),
        ):
            rc = _init_update([str(tmp_path), "--dry-run"])

        assert rc == 2
        mock_run.assert_not_called()

    @staticmethod
    def _stamp_behind_scaffold(root: Path) -> Path:
        """A real scaffold under tmp_path whose only drift is the version stamp.

        Built by the real init, never copied from a live project, so the door
        is exercised end to end — the plan is computed by the real handler.
        """
        target = root / "proj"
        target.mkdir()
        init_project(target, project_name="stamp")
        manifest_path = target / ".aipass" / "scaffold_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["aipass_version"] = "0.0.1"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        return target

    @staticmethod
    def _squashed(text: str) -> str:
        """The channel with every whitespace run removed: Rich folds long paths at the width."""
        return "".join(text.split())

    def test_stamp_only_dry_run_says_no_go_is_needed_and_still_exits_2(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The preview names the apply as the next move, not a request.

        Exit stays 2: the stamp IS pending, and 2 keeps meaning "there is a plan".
        Mutant: "so no go is needed" cut to "so no go" reddens this.
        """
        target = self._stamp_behind_scaffold(tmp_path)
        capsys.readouterr()
        with patch(f"{_MOD_UPDATE}._run_git_auth_provisioning", return_value=0):
            rc = _init_update([str(target), "--dry-run"])

        assert rc == 2
        out, _err = capsys.readouterr()
        printed = self._squashed(out)
        assert self._squashed("Stamp only: no file would change, so no go is needed") in printed
        assert self._squashed(f"Run: aipass init update {target}") in printed
        assert self._squashed("Apply needs the owner's or devpulse's go") not in printed

    def test_a_dry_run_prints_each_gitignore_line_the_merge_would_add_brackets_and_all(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        target = tmp_path / "proj"
        target.mkdir()
        init_project(target, project_name="lines")
        (target / ".gitignore").write_text("logs/\n", encoding="utf-8")
        capsys.readouterr()
        with patch(f"{_MOD_UPDATE}._run_git_auth_provisioning", return_value=0):
            rc = _init_update([str(target), "--dry-run"])

        assert rc == 2
        out, _err = capsys.readouterr()
        assert "+ .chroma/" in out
        assert "+ *.py[cod]" in out
        assert "+ logs/" not in out
        assert (target / ".gitignore").read_text(encoding="utf-8") == "logs/\n"

    def test_a_plan_that_writes_a_file_still_asks_for_the_go(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """One file write in the plan and the preview still asks for the go.

        Mutant: "devpulse's go" cut to "devpulse" in the preview line reddens this.
        """
        target = self._stamp_behind_scaffold(tmp_path)
        (target / ".agents" / "skills" / "prep" / "SKILL.md").write_text("# mine\n", encoding="utf-8")
        capsys.readouterr()
        with patch(f"{_MOD_UPDATE}._run_git_auth_provisioning", return_value=0):
            rc = _init_update([str(target), "--dry-run"])

        assert rc == 2
        out, _err = capsys.readouterr()
        printed = self._squashed(out)
        assert self._squashed("Apply needs the owner's or devpulse's go") in printed
        assert self._squashed("no go is needed") not in printed

    def test_json_carries_stamp_only_for_a_managers_agent(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A manager's agent reads the key, never the prose.

        Mutant: the plan's "stamp_only" key renamed reddens this.
        """
        target = self._stamp_behind_scaffold(tmp_path)
        capsys.readouterr()
        with patch(f"{_MOD_UPDATE}._run_git_auth_provisioning", return_value=0):
            rc = _init_update([str(target), "--dry-run", "--json"])

        assert rc == 2
        out, _err = capsys.readouterr()
        emitted = json.loads(out)
        assert emitted["stamp_only"] is True
        assert emitted["pending"] is True

    def test_applying_stamp_only_prints_the_stamp_as_written(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The receipt reports what happened: after apply the stamp is written,
        not pending — the one word that would have been a lie in the receipt.
        Mutant: `state = "pending"` on both branches reddens this."""
        target = self._stamp_behind_scaffold(tmp_path)
        capsys.readouterr()
        with (
            patch(f"{_MOD_UPDATE}._run_git_auth_provisioning", return_value=0),
            patch(f"{_MOD_UPDATE}.subprocess.run", return_value=MagicMock(returncode=0, stdout="", stderr="")),
            patch(f"{_MOD_UPDATE}.success"),
            patch(f"{_MOD_UPDATE}.json_handler", autospec=True),
        ):
            rc = _init_update([str(target)])

        assert rc == 0
        out, _err = capsys.readouterr()
        stamp_lines = [line for line in out.splitlines() if line.strip().startswith("stamp ")]
        assert len(stamp_lines) == 1
        assert stamp_lines[0].rstrip().endswith("written")
        assert "0.0.1 →" in stamp_lines[0]

    def test_json_flag_emits_the_plan_as_parseable_json(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """--json prints the plan document itself, not a rendered table.

        Stdout is exactly ONE JSON document with git-auth provisioning really running:
        its prose goes to stderr, so a manager's agent parsing stdout never meets it.
        Mutant: console.print_json swapped for console.print reddens this.
        Mutant: the --json redirect aimed at sys.stdout instead of sys.stderr reddens this.
        Mutant: the redirect removed -> red at the raw-text assert, before json.loads.
        """
        self._project(tmp_path)
        plan = {
            "project_name": "DEMO",
            "pending": True,
            "files": [{"path": ".aipass/tier0_kernel.md", "action": "update", "reason": "unmodified"}],
            "handlers": [{"name": "testwrite_gate", "action": "add"}],
        }

        with (
            patch("aipass.aipass.apps.handlers.init.bootstrap.update_project", return_value=plan),
            patch(f"{_MOD_UPDATE}.subprocess.run") as mock_run,
            pytest.raises(SystemExit) as exit_info,
        ):
            handle_command("init", ["update", str(tmp_path), "--dry-run", "--json"])

        assert exit_info.value.code == 2
        mock_run.assert_not_called()
        out, err = capsys.readouterr()
        # On the raw text first, so a plan printed to stdout dies at an assert, not in json.loads.
        assert "Git authorization (owner-tier)" not in out
        emitted = json.loads(out)
        assert emitted["files"][0]["action"] == "update"
        assert emitted["handlers"][0]["name"] == "testwrite_gate"
        assert "Git authorization (owner-tier)" in err
        assert "would repair" in err


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
        with patch.multiple(_MOD, warning=MagicMock(), **mocks):
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
        with patch.multiple(_MOD, warning=MagicMock(), **mocks):
            with patch(
                "aipass.aipass.apps.handlers.init.bootstrap.init_project",
                return_value={},
            ):
                result = run_init(non_interactive=True, template=TEMPLATE_AIPASS)
        assert result == 0
        for name in mocks:
            assert mocks[name].called, f"{name} should have been called"

    def test_list_flag_shows_catalog(self, capsys: pytest.CaptureFixture[str]) -> None:
        """aipass init --list shows the catalog (not swallowed into run).

        Mutant: the catalog loop printing nothing reddens this.
        """
        result = handle_command("init", ["--list"])
        assert result is True
        printed, _err = capsys.readouterr()
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

    def test_pip_hints_say_clone(self, tmp_local_json, tools_on_path) -> None:
        """in-product hints say clone/setup.sh, not pip. PATH is an empty directory."""
        tools_on_path()
        with patch(f"{_MOD}.warning") as mock_warn:
            stage_8_smoke_test()
        # Without this floor a stage 8 that never warns passes the loop below vacuously.
        assert mock_warn.call_args_list, "stage 8 emitted no warning - the loop below proves nothing"
        for call in mock_warn.call_args_list:
            msg = call[0][0].lower()
            assert "setup.sh" in msg
            assert "pip" not in msg

    def test_empty_template_stage9_gets_cwd_as_agent_path(self, tmp_local_json) -> None:
        """Empty template sets agent_path='.' so stage 9 hands off from CWD."""
        mocks = self._stage_patches()
        with patch.multiple(_MOD, warning=MagicMock(), **mocks):
            run_init(non_interactive=True, template=TEMPLATE_EMPTY)
        stage_9_call = mocks["stage_9_handoff"].call_args
        assert stage_9_call is not None
        agent_path_arg = stage_9_call[0][2] if len(stage_9_call[0]) > 2 else stage_9_call[1].get("agent_path", "")
        assert agent_path_arg == "."

    def test_non_tty_forces_non_interactive(self, tmp_local_json) -> None:
        """When stdin is not a TTY, run_init auto-forces non_interactive (no crash)."""
        mocks = self._stage_patches()
        with (
            patch.multiple(_MOD, warning=MagicMock(), **mocks),
            patch("sys.stdin") as mock_stdin,
        ):
            mock_stdin.isatty.return_value = False
            rc = run_init(non_interactive=False, template=TEMPLATE_EMPTY)
        assert rc == 0

    def test_aipass_specific_stages_constant(self) -> None:
        """AIPASS_SPECIFIC_STAGES contains exactly {6, 7} — stages 9/10 run for ALL templates."""
        assert AIPASS_SPECIFIC_STAGES == {6, 7}
