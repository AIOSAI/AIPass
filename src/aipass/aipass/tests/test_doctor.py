# =================== AIPass ====================
# Name: test_doctor.py
# Description: Tests for aipass doctor: the command, the run and the provider checks
# Version: 1.8.0
# Created: 2026-04-16
# Modified: 2026-10-26
# =============================================

"""Tests for apps/modules/doctor.py and apps/modules/_doctor_wire.py: the run and the provider checks."""
# Originally scoped to Phase 1 (FPLAN-0188); grown since. Split 2026-10-08
# (fleet green, oversize_test_file): detection and progress live in
# test_doctor_detection.py, the home and seating rows in test_doctor_home.py.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that every handler module this file imports parses and imports

import io
import json
import os
import re
import subprocess
import sys
from unittest.mock import MagicMock, patch

import pytest  # pyright: ignore[reportMissingImports]

from aipass.aipass.apps.handlers.ui.progress import (
    GLYPH_FAIL,
    GLYPH_PASS,
    GLYPH_WARN,
)
from aipass.aipass.apps.modules import _doctor_wire, doctor
from aipass.aipass.apps.modules._doctor_wire import (
    check_wire_verify,
    merge_manifest_rows,
    reconcile_stale_deny,
)
from aipass.aipass.apps.modules.doctor import (
    CheckResult,
    check_identity,
    check_provider_manifest,
    handle_command,
    run_doctor,
    run_doctor_preflight,
)
from aipass.aipass.tests.support_doctor import _home_at


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def clean_env(monkeypatch):
    """Remove AIPASS_HOME from environment."""
    monkeypatch.delenv("AIPASS_HOME", raising=False)


def _seat_home(tmp_path, monkeypatch, *, venv: bool = True, via: str = "settings"):
    """An install home under tmp_path named by the user's settings.json or the env; returns (home, venv python).

    The user's home is tmp_path/user, entered with _home_at by the caller.
    """
    home = tmp_path / "home"
    home.mkdir()
    venv_python = home / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if venv:
        venv_python.parent.mkdir(parents=True)
        venv_python.write_text("", encoding="utf-8")
    claude = tmp_path / "user" / ".claude"
    claude.mkdir(parents=True)
    monkeypatch.delenv("AIPASS_HOME", raising=False)
    if via == "settings":
        settings = {"env": {"AIPASS_HOME": str(home)}}
        (claude / "settings.json").write_text(json.dumps(settings), encoding="utf-8")
    elif via == "env":
        monkeypatch.setenv("AIPASS_HOME", str(home))
    return home, venv_python


def _doctor_with_only_pytest_collect(monkeypatch, run, args, capsys) -> str:
    """Run `aipass doctor` with every group and row but pytest collect stubbed; returns stdout."""
    mod = "aipass.aipass.apps.modules.doctor"
    for name in ("_check_system", "check_identity", "_check_community", "_check_structure"):
        monkeypatch.setattr(f"{mod}.{name}", lambda: [])
    for name in ("_check_scaffold", "_check_sandbox", "_check_drone_systems", "check_wire_verify"):
        monkeypatch.setattr(f"{mod}.{name}", lambda: [])
    monkeypatch.setattr(f"{mod}.check_admin_lane", lambda: [])
    monkeypatch.setattr(f"{mod}.check_provider_manifest", lambda **_kw: [])
    monkeypatch.setattr(f"{mod}.reconcile_stale_deny", lambda **_kw: [])
    with patch(f"{mod}.json_handler", autospec=True), patch(f"{mod}.subprocess.run", side_effect=run):
        assert handle_command("doctor", args) is True
    return capsys.readouterr().out


class _Stdin(io.StringIO):
    """A real text stream for input() to read, answering isatty() as told."""

    def __init__(self, text: str, tty: bool) -> None:
        super().__init__(text)
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


# =============================================================================
# TestDoctorHandleCommand
# =============================================================================


class TestDoctorHandleCommand:
    def test_wrong_command_returns_false(self) -> None:
        """Non-doctor commands are not handled."""
        assert handle_command("help", []) is False
        assert handle_command("init", ["--verbose"]) is False

    def test_no_args_runs_doctor(self) -> None:
        """No args runs run_doctor (returns True when 0 errors).

        Mutant: run_doctor call replaced by error_count = 0 -> red.
        """
        with patch("aipass.aipass.apps.modules.doctor.run_doctor", return_value=0) as run:
            result = handle_command("doctor", [])
        assert result is True
        run.assert_called_once_with(verbose=False, interactive=True, fix=False, yes=False)

    def test_info_flag_calls_introspection(self) -> None:
        """--info flag triggers print_introspection (returns True)."""
        with patch("aipass.aipass.apps.modules.doctor.print_introspection") as mock_intro:
            result = handle_command("doctor", ["--info"])
        assert result is True
        mock_intro.assert_called_once()

    def test_help_flag_calls_print_help(self) -> None:
        """--help flag triggers print_help (returns True)."""
        with patch("aipass.aipass.apps.modules.doctor.print_help") as mock_help:
            result = handle_command("doctor", ["--help"])
        assert result is True
        mock_help.assert_called_once()

    def test_h_flag_calls_print_help(self) -> None:
        """-h flag triggers print_help."""
        with patch("aipass.aipass.apps.modules.doctor.print_help") as mock_help:
            result = handle_command("doctor", ["-h"])
        assert result is True
        mock_help.assert_called_once()

    def test_doctor_no_errors_returns_true(self) -> None:
        """When run_doctor returns 0 errors, handle_command returns True.

        Mutant: doctor_run log_operation dropped -> red.
        """
        with patch("aipass.aipass.apps.modules.doctor.run_doctor", return_value=0):
            with patch("aipass.aipass.apps.modules.doctor.json_handler", autospec=True) as jh:
                result = handle_command("doctor", ["--check"])
        assert result is True
        jh.log_operation.assert_called_once_with("doctor_run", {"error_count": 0, "fix": False})

    def test_doctor_with_errors_raises_system_exit(self) -> None:
        """When run_doctor returns errors, SystemExit(1) is raised."""
        with patch("aipass.aipass.apps.modules.doctor.run_doctor", return_value=2):
            with patch("aipass.aipass.apps.modules.doctor.json_handler", autospec=True):
                with pytest.raises(SystemExit) as exc_info:
                    handle_command("doctor", ["--check"])
        assert exc_info.value.code == 1

    def test_verbose_flag_passed_to_run_doctor(self) -> None:
        """--verbose flag is forwarded to run_doctor."""
        with patch("aipass.aipass.apps.modules.doctor.run_doctor", return_value=0) as mock_run:
            with patch("aipass.aipass.apps.modules.doctor.json_handler", autospec=True):
                handle_command("doctor", ["--verbose"])
        mock_run.assert_called_once_with(verbose=True, interactive=True, fix=False, yes=False)

    @pytest.mark.parametrize(("args", "shown"), [(["--verbose"], True), ([], False)])
    def test_verbose_shows_pytest_collect_errors(
        self, args: list[str], shown: bool, tmp_path, monkeypatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """--verbose prints the collect errors behind 'collection issues'; the plain run does not.

        The home's venv python is a stub file the runner swaps for this interpreter, so a real
        pytest collects a src/aipass/ that is not under the tmp home and prints its own ERROR line.
        Mutant: `... if verbose)` -> `... if False)` (verbose ignored again) -> red.
        Mutant: `"--collect-only", "-q"]` -> `"-q"]` (pytest handed a real run) -> red.
        """
        home, home_python = _seat_home(tmp_path, monkeypatch)
        calls: list[list[str]] = []
        real_run = subprocess.run  # bound now: the patch replaces subprocess.run itself

        def run(argv, **kwargs):
            calls.append(argv)
            real = [sys.executable, *argv[1:]] if argv[0] == str(home_python) else argv
            return real_run(real, **kwargs)

        with _home_at(tmp_path / "user"):
            out = _doctor_with_only_pytest_collect(monkeypatch, run, args, capsys)
        assert "collection issues" in out
        assert ("file or directory not found" in out) is shown
        assert [str(home_python), "-m", "pytest", "src/aipass/", "--collect-only", "-q"] in calls

    def test_unreadable_updateignore_is_one_scaffold_row(self, tmp_path, monkeypatch, capsys) -> None:
        """An .updateignore that is there but cannot be read: doctor says so in one Scaffold row.

        read_ignore raises for it now (the update refuses); without the catch in the
        Scaffold group, `aipass doctor` would end in a traceback. The file is a directory,
        which no platform reads as text. Every other group is stubbed and the registry
        found is a tmp project, so nothing reads live state.
        Mutant: the catch returns no row and goes on with no patterns -> red at the row assert.
        (With the catch removed the raise escapes the command: red, but not at an assert.)
        """
        project = tmp_path / "proj"
        project.mkdir()
        registry = project / "PROJ_REGISTRY.json"
        registry.write_text("{}", encoding="utf-8")
        (project / ".updateignore").mkdir()
        mod = "aipass.aipass.apps.modules.doctor"
        for name in ("_check_system", "check_identity", "_check_community", "_check_structure", "_check_sandbox"):
            monkeypatch.setattr(f"{mod}.{name}", lambda: [])
        monkeypatch.setattr(f"{mod}._check_services", lambda **_kw: [])
        monkeypatch.setattr(f"{mod}.check_provider_manifest", lambda **_kw: [])
        monkeypatch.setattr(f"{mod}._find_registry", lambda: registry)
        with patch(f"{mod}.json_handler", autospec=True):
            assert handle_command("doctor", []) is True
        out = capsys.readouterr().out
        assert ".updateignore" in out
        assert "is there but cannot be read" in out
        assert "scaffold manifest" not in out  # one row: the drift report is not guessed without the claims


class TestPytestCollect:
    """The pytest collect row runs the install home's venv python at the home, never sys.executable."""

    @pytest.mark.parametrize("via", ["settings", "env"])
    def test_runs_the_home_venv_python_with_cwd_at_the_home(self, via, tmp_path, monkeypatch, capsys) -> None:
        """On the pipx route sys.executable has no pytest and no src/ beside it: the pipx 2.8.22 false warn.

        Mutant: argv[0] `str(python)` -> `sys.executable` -> red. Mutant: `cwd=str(home)` -> `cwd=None` -> red.
        Mutant: the env fallback `or os.environ.get(...)` dropped -> red on via=env.
        """
        home, home_python = _seat_home(tmp_path, monkeypatch, via=via)
        calls: list[tuple[list[str], object]] = []

        def run(argv, **kwargs):
            calls.append((argv, kwargs.get("cwd")))
            return subprocess.CompletedProcess(argv, 0, "tests/test_a.py::test_one\n", "")

        with _home_at(tmp_path / "user"):
            out = _doctor_with_only_pytest_collect(monkeypatch, run, [], capsys)
        assert calls == [([str(home_python), "-m", "pytest", "src/aipass/", "--collect-only", "-q"], str(home))]
        assert "1 tests collected" in out

    def test_a_home_without_a_venv_says_so_and_runs_nothing(self, tmp_path, monkeypatch, capsys) -> None:
        """Mutant: the `.is_file()` guard removed -> red (the runner is called, the row says collection issues)."""
        home, _ = _seat_home(tmp_path, monkeypatch, venv=False)
        calls: list[list[str]] = []

        def run(argv, **kwargs):
            calls.append(argv)
            raise FileNotFoundError(argv[0])

        with _home_at(tmp_path / "user"):
            out = _doctor_with_only_pytest_collect(monkeypatch, run, [], capsys)
        assert calls == []
        assert f"no venv at home ({home})" in " ".join(out.split())
        assert "collection issues" not in out

    def test_no_home_set_says_so_and_runs_nothing(self, tmp_path, monkeypatch, capsys) -> None:
        """Mutant: the not-set return removed -> red (Path('') runs, the row never names the cause)."""
        _seat_home(tmp_path, monkeypatch, via="none")
        calls: list[list[str]] = []

        def run(argv, **kwargs):
            calls.append(argv)
            return subprocess.CompletedProcess(argv, 1, "", "")

        with _home_at(tmp_path / "user"):
            out = _doctor_with_only_pytest_collect(monkeypatch, run, [], capsys)
        assert calls == []
        assert "AIPASS_HOME not set" in out

    def test_a_home_venv_without_pytest_is_named_not_collection_issues(self, tmp_path, monkeypatch, capsys) -> None:
        """Mutant: the `No module named pytest` arm removed -> red."""
        _seat_home(tmp_path, monkeypatch)

        def run(argv, **kwargs):
            return subprocess.CompletedProcess(argv, 1, "", f"{argv[0]}: No module named pytest\n")

        with _home_at(tmp_path / "user"):
            out = _doctor_with_only_pytest_collect(monkeypatch, run, [], capsys)
        assert "pytest not installed in the home venv" in out
        assert "collection issues" not in out


class TestClaudeCodeRow:
    """The System group's claude code row: Claude Code reads AGENTS.md from v2.1.277."""

    def _system_out(self, tmp_path, monkeypatch, capsys, stdout: str | None) -> str:
        mod = "aipass.aipass.apps.modules.doctor"
        for name in ("check_identity", "_check_community", "_check_structure", "_check_scaffold", "_check_sandbox"):
            monkeypatch.setattr(f"{mod}.{name}", lambda: [])
        monkeypatch.setattr(f"{mod}._check_services", lambda **_kw: [])
        monkeypatch.setattr(f"{mod}.check_admin_lane", lambda: [])
        monkeypatch.setattr(f"{mod}.check_provider_manifest", lambda **_kw: [])
        # git sits beside claude so the System group carries no FAIL row and doctor exits 0.
        for name in ("git", "claude") if stdout is not None else ("git",):
            stub = tmp_path / (f"{name}.exe" if os.name == "nt" else name)
            stub.write_text("", encoding="utf-8")
            stub.chmod(0o755)
        monkeypatch.setenv("PATH", str(tmp_path))

        def run(argv, **kwargs):
            if argv[1:] == ["--version"] and "git" in os.path.basename(argv[0]):
                return subprocess.CompletedProcess(argv, 0, "git version 2.43.0\n", "")
            return subprocess.CompletedProcess(argv, 0, stdout, "")

        detector = "aipass.aipass.apps.handlers.system_detect.system_detector.subprocess.run"
        with patch(f"{mod}.json_handler", autospec=True), patch(detector, side_effect=run):
            handle_command("doctor", [])
        return " ".join(capsys.readouterr().out.split())

    @pytest.mark.parametrize("version", ["2.1.277", "2.1.1000", "3.0.0"])
    def test_at_or_past_2_1_277_passes(self, version, tmp_path, monkeypatch, capsys) -> None:
        """Mutant: the tuple compare done on the version string -> red on 2.1.1000 ("2.1.1000" < "2.1.277")."""
        out = self._system_out(tmp_path, monkeypatch, capsys, f"{version} (Claude Code)\n")
        assert f"✓ claude code {version}" in out
        assert "reads AGENTS.md" not in out

    def test_below_2_1_277_warns_naming_agents_md(self, tmp_path, monkeypatch, capsys) -> None:
        out = self._system_out(tmp_path, monkeypatch, capsys, "2.1.276 (Claude Code)\n")
        assert "! claude code 2.1.276 Claude Code reads AGENTS.md from v2.1.277" in out

    def test_not_on_path_is_a_plain_row(self, tmp_path, monkeypatch, capsys) -> None:
        out = self._system_out(tmp_path, monkeypatch, capsys, None)
        assert "✓ claude code not on PATH" in out

    def test_unparseable_output_warns(self, tmp_path, monkeypatch, capsys) -> None:
        out = self._system_out(tmp_path, monkeypatch, capsys, "Claude Code\n")
        assert "! claude code version unreadable: 'Claude Code'" in out


# =============================================================================
# TestRunDoctor
# =============================================================================


class TestRunDoctor:
    @pytest.fixture(autouse=True)
    def sandbox_group_stays_offline(self):
        """No test in this class runs a real binary through doctor's Sandbox group.

        run_doctor() runs all seven groups; these tests patch five of them, so Sandbox
        used to reach the machine — `npm root -g` and the node resolver, which write
        ~/.npm/_logs/<ts>-debug-0.log on the real HOME (reported by @devpulse, mail
        df3763d4). Every probe in that group goes through sandbox_checker's own
        shutil.which / subprocess.run, so stubbing both there answers what doctor reads
        (nothing found) and a subprocess call is now a test failure, not a stray log.
        """
        module = "aipass.aipass.apps.handlers.sandbox_check.sandbox_checker"
        with (
            patch(f"{module}.shutil.which", return_value=None),
            patch(f"{module}.subprocess.run", side_effect=AssertionError("doctor ran a real binary in a unit test")),
        ):
            yield

    def _mock_all_checks(self, mock_system, mock_identity, mock_services, mock_community):
        """Set all group mocks to return empty lists (no errors)."""
        mock_system.return_value = []
        mock_identity.return_value = []
        mock_services.return_value = []
        mock_community.return_value = []

    def test_run_doctor_returns_int(self) -> None:
        """run_doctor returns an integer error count."""
        with (
            patch("aipass.aipass.apps.modules.doctor._check_system", return_value=[]),
            patch("aipass.aipass.apps.modules.doctor.check_identity", return_value=[]),
            patch("aipass.aipass.apps.modules.doctor._check_services", return_value=[]),
            patch("aipass.aipass.apps.modules.doctor._check_community", return_value=[]),
            patch("aipass.aipass.apps.modules.doctor._check_structure", return_value=[]),
        ):
            result = run_doctor()
        assert isinstance(result, int)
        assert result == 0

    def test_run_doctor_counts_errors(self) -> None:
        """Error glyphs in results increment error count."""
        fail_check = CheckResult("test", GLYPH_FAIL, "bad", "fix it")
        with (
            patch("aipass.aipass.apps.modules.doctor._check_system", return_value=[fail_check]),
            patch("aipass.aipass.apps.modules.doctor.check_identity", return_value=[]),
            patch("aipass.aipass.apps.modules.doctor._check_services", return_value=[]),
            patch("aipass.aipass.apps.modules.doctor._check_community", return_value=[]),
            patch("aipass.aipass.apps.modules.doctor._check_structure", return_value=[]),
        ):
            result = run_doctor()
        assert result == 1

    def test_run_doctor_counts_only_errors_not_warnings(self) -> None:
        """Warning glyphs do not increment error count."""
        warn_check = CheckResult("test", GLYPH_WARN, "minor", "")
        with (
            patch("aipass.aipass.apps.modules.doctor._check_system", return_value=[warn_check]),
            patch("aipass.aipass.apps.modules.doctor.check_identity", return_value=[]),
            patch("aipass.aipass.apps.modules.doctor._check_services", return_value=[]),
            patch("aipass.aipass.apps.modules.doctor._check_community", return_value=[]),
            patch("aipass.aipass.apps.modules.doctor._check_structure", return_value=[]),
        ):
            result = run_doctor()
        assert result == 0


# =============================================================================
# TestProviderManifest
# =============================================================================


class TestProviderManifest:
    """Tests for manifest-driven provider checks (DPLAN-0168)."""

    def test_manifest_not_found_returns_warn(self) -> None:
        """Missing manifest → single WARN result."""
        with patch("aipass.aipass.apps.modules.doctor._find_manifest", return_value=None):
            results = check_provider_manifest()
        assert len(results) == 1
        assert results[0].glyph == GLYPH_WARN
        assert "manifest" in results[0].detail

    def test_manifest_unreadable_returns_warn(self, tmp_path) -> None:
        """Corrupt manifest file → WARN."""
        bad_manifest = tmp_path / ".claude" / "provider_manifest.json"
        bad_manifest.parent.mkdir(parents=True)
        bad_manifest.write_text("not json{{{", encoding="utf-8")
        with patch("aipass.aipass.apps.modules.doctor._find_manifest", return_value=bad_manifest):
            results = check_provider_manifest()
        assert len(results) == 1
        assert results[0].glyph == GLYPH_WARN
        assert "unreadable" in results[0].detail

    def test_manifest_no_claude_section(self, tmp_path) -> None:
        """Manifest with no cli.claude → WARN."""
        manifest = tmp_path / ".claude" / "provider_manifest.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text(json.dumps({"cli": {}}), encoding="utf-8")
        with patch("aipass.aipass.apps.modules.doctor._find_manifest", return_value=manifest):
            results = check_provider_manifest()
        assert len(results) == 1
        assert results[0].glyph == GLYPH_WARN

    def test_all_hooks_present(self, tmp_path) -> None:
        """All hook scripts exist → PASS for hooks."""
        manifest = tmp_path / ".claude" / "provider_manifest.json"
        manifest.parent.mkdir(parents=True)
        cmd_a = "$AIPASS_HOME/bin/hook-bridge Stop"
        cmd_b = "$AIPASS_HOME/bin/hook-bridge Notification"
        manifest.write_text(
            json.dumps(
                {
                    "cli": {
                        "claude": {
                            "hooks": [
                                {"command": cmd_a, "event": "Stop"},
                                {"command": cmd_b, "event": "Notification"},
                            ]
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        provider_settings = tmp_path / ".claude" / "settings.json"
        provider_settings.write_text(
            json.dumps(
                {
                    "hooks": {
                        "Stop": [{"hooks": [{"type": "command", "command": cmd_a}]}],
                        "Notification": [{"hooks": [{"type": "command", "command": cmd_b}]}],
                    }
                }
            ),
            encoding="utf-8",
        )
        with (
            patch("aipass.aipass.apps.modules.doctor._find_manifest", return_value=manifest),
            _home_at(tmp_path),
        ):
            results = check_provider_manifest()
        hooks_result = [r for r in results if r.label == "hooks"][0]
        assert hooks_result.glyph == GLYPH_PASS
        assert "2" in hooks_result.detail

    def test_missing_hook_detected(self, tmp_path) -> None:
        """Missing hook command in provider settings → WARN."""
        manifest = tmp_path / ".claude" / "provider_manifest.json"
        manifest.parent.mkdir(parents=True)
        cmd = "$AIPASS_HOME/bin/hook-bridge Stop"
        manifest.write_text(
            json.dumps(
                {
                    "cli": {
                        "claude": {
                            "hooks": [
                                {"command": cmd, "event": "Stop"},
                            ]
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        provider_settings = tmp_path / ".claude" / "settings.json"
        provider_settings.write_text(json.dumps({"hooks": {}}), encoding="utf-8")
        with (
            patch("aipass.aipass.apps.modules.doctor._find_manifest", return_value=manifest),
            _home_at(tmp_path),
        ):
            results = check_provider_manifest()
        hooks_result = [r for r in results if r.label == "hooks"][0]
        assert hooks_result.glyph == GLYPH_WARN
        assert "Stop" in hooks_result.detail

    def test_windows_scripts_path_command_recognized_as_wired(self, tmp_path) -> None:
        """A Scripts-path (Windows-transformed) hook entry must not be flagged missing against
        the POSIX-canonical manifest — write (platform_bridge_command) and verify must agree
        (DPLAN-0234 Strand C)."""
        posix_cmd = "$AIPASS_HOME/.venv/bin/python3 $AIPASS_HOME/bridges/claude.py Stop"
        manifest = tmp_path / ".claude" / "provider_manifest.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text(
            json.dumps({"cli": {"claude": {"hooks": [{"command": posix_cmd, "event": "Stop"}]}}}),
            encoding="utf-8",
        )
        windows_cmd = "$AIPASS_HOME/.venv/Scripts/python.exe $AIPASS_HOME/bridges/claude.py Stop"
        provider_settings = tmp_path / ".claude" / "settings.json"
        provider_settings.write_text(
            json.dumps({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": windows_cmd}]}]}}),
            encoding="utf-8",
        )
        with patch("aipass.aipass.apps.modules.doctor._find_manifest", return_value=manifest):
            results = check_provider_manifest(settings_path=provider_settings, os_name="nt")
        hooks_result = [r for r in results if r.label == "hooks"][0]
        assert hooks_result.glyph == GLYPH_PASS
        assert "1" in hooks_result.detail
        assert "missing" not in hooks_result.detail

    def test_missing_hook_label_not_double_prefixed(self, tmp_path) -> None:
        """Command already shaped like 'event:label' must not get the event prefixed twice."""
        manifest = tmp_path / ".claude" / "provider_manifest.json"
        manifest.parent.mkdir(parents=True)
        cmd = "$AIPASS_HOME/bin/hook-bridge.py UserPromptSubmit:presence_gate"
        manifest.write_text(
            json.dumps({"cli": {"claude": {"hooks": [{"command": cmd, "event": "UserPromptSubmit"}]}}}),
            encoding="utf-8",
        )
        provider_settings = tmp_path / ".claude" / "settings.json"
        provider_settings.write_text(json.dumps({"hooks": {}}), encoding="utf-8")
        with (
            patch("aipass.aipass.apps.modules.doctor._find_manifest", return_value=manifest),
            _home_at(tmp_path),
        ):
            results = check_provider_manifest()
        hooks_result = [r for r in results if r.label == "hooks"][0]
        assert "UserPromptSubmit:UserPromptSubmit" not in hooks_result.detail
        assert "UserPromptSubmit:presence_gate" in hooks_result.detail

    def test_missing_hook_duplicate_matchers_deduped(self, tmp_path) -> None:
        """Same command missing under two matchers must appear once in the report, not twice."""
        manifest = tmp_path / ".claude" / "provider_manifest.json"
        manifest.parent.mkdir(parents=True)
        cmd = "$AIPASS_HOME/bin/hook-bridge PreCompact:pre_compact_prep"
        manifest.write_text(
            json.dumps(
                {
                    "cli": {
                        "claude": {
                            "hooks": [
                                {"command": cmd, "event": "PreCompact", "matcher": "manual"},
                                {"command": cmd, "event": "PreCompact", "matcher": "auto"},
                            ]
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        provider_settings = tmp_path / ".claude" / "settings.json"
        provider_settings.write_text(json.dumps({"hooks": {}}), encoding="utf-8")
        with (
            patch("aipass.aipass.apps.modules.doctor._find_manifest", return_value=manifest),
            _home_at(tmp_path),
        ):
            results = check_provider_manifest()
        hooks_result = [r for r in results if r.label == "hooks"][0]
        assert hooks_result.detail.count("PreCompact:pre_compact_prep") == 1

    def test_a_hook_whose_name_only_prefixes_another_is_still_missing(self, tmp_path) -> None:
        """pre_compact is missing even though pre_compact_rollover (a longer name) is wired."""
        manifest = tmp_path / ".claude" / "provider_manifest.json"
        manifest.parent.mkdir(parents=True)
        cmd = "$AIPASS_HOME/bin/hook-bridge PreCompact:pre_compact"
        manifest.write_text(
            json.dumps({"cli": {"claude": {"hooks": [{"command": cmd, "event": "PreCompact"}]}}}),
            encoding="utf-8",
        )
        provider_settings = tmp_path / ".claude" / "settings.json"
        wired = {"hooks": [{"type": "command", "command": cmd + "_rollover"}]}
        provider_settings.write_text(json.dumps({"hooks": {"PreCompact": [wired]}}), encoding="utf-8")
        with patch("aipass.aipass.apps.modules.doctor._find_manifest", return_value=manifest):
            results = check_provider_manifest(settings_path=provider_settings)
        hooks_result = [r for r in results if r.label == "hooks"][0]
        assert hooks_result.glyph == GLYPH_WARN
        assert "PreCompact:pre_compact" in hooks_result.detail

    def test_env_vars_all_present(self, tmp_path) -> None:
        """All manifest env vars present in provider settings → PASS."""
        manifest = tmp_path / ".claude" / "provider_manifest.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text(
            json.dumps({"cli": {"claude": {"hooks": [], "env": {"FOO": "1", "BAR": "2"}}}}),
            encoding="utf-8",
        )
        provider_settings = tmp_path / ".claude" / "settings.json"
        provider_settings.write_text(
            json.dumps({"env": {"FOO": "1", "BAR": "2", "OTHER": "3"}}),
            encoding="utf-8",
        )
        with (
            patch("aipass.aipass.apps.modules.doctor._find_manifest", return_value=manifest),
            _home_at(tmp_path),
        ):
            results = check_provider_manifest()
        env_results = [r for r in results if r.label == "env vars"]
        assert len(env_results) == 1
        assert env_results[0].glyph == GLYPH_PASS

    def test_env_vars_missing(self, tmp_path) -> None:
        """Missing env var → WARN with var name."""
        manifest = tmp_path / ".claude" / "provider_manifest.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text(
            json.dumps({"cli": {"claude": {"hooks": [], "env": {"MISSING_VAR": "1"}}}}),
            encoding="utf-8",
        )
        provider_settings = tmp_path / ".claude" / "settings.json"
        provider_settings.write_text(json.dumps({"env": {}}), encoding="utf-8")
        with (
            patch("aipass.aipass.apps.modules.doctor._find_manifest", return_value=manifest),
            _home_at(tmp_path),
        ):
            results = check_provider_manifest()
        env_results = [r for r in results if r.label == "env vars"]
        assert len(env_results) == 1
        assert env_results[0].glyph == GLYPH_WARN
        assert "MISSING_VAR" in env_results[0].detail

    def test_find_manifest_walks_up(self, tmp_path, monkeypatch) -> None:
        """_find_manifest finds manifest by walking up from CWD.

        Reached through check_provider_manifest (leg 6), handed a scratch settings file and
        a scratch HOME (the walk's AIPASS_HOME fallback reads the settings under the home),
        so no pass reads the live one: the manifest found holds no claude section, so the
        row says that and never "manifest not found".
        Mutant: the walk-up reads the start directory only (no parents) -> red at the row assert.
        """
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
        manifest = tmp_path / ".claude" / "provider_manifest.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text("{}", encoding="utf-8")
        subdir = tmp_path / "src" / "deep"
        subdir.mkdir(parents=True)
        monkeypatch.chdir(subdir)
        monkeypatch.delenv("AIPASS_HOME", raising=False)
        rows = check_provider_manifest(settings_path=tmp_path / "handed" / "settings.json")
        assert [(r.label, r.detail) for r in rows] == [("hooks", "manifest has no claude section")]


# =============================================================================
# SETTINGS SCALAR SLOT — doctor's diff row per manifest key (DPLAN-0347)
# =============================================================================


class TestProviderSettingsScalars:
    """doctor reads the PERSONAL settings file and names each manifest settings key.

    Every test runs against a scratch HOME (tmp_path): the real ~/.claude/settings.json
    of this machine is never read or written by the suite.
    """

    @staticmethod
    def _scratch(tmp_path, wanted: dict, provider: dict | None):
        """A scratch HOME: manifest with the settings slot, optional provider settings file."""
        manifest = tmp_path / ".claude" / "provider_manifest.json"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(
            json.dumps({"cli": {"claude": {"hooks": [], "settings": wanted}}}),
            encoding="utf-8",
        )
        if provider is not None:
            (tmp_path / ".claude" / "settings.json").write_text(json.dumps(provider), encoding="utf-8")
        return manifest

    @staticmethod
    def _run(manifest, tmp_path, **kwargs):
        with (
            patch("aipass.aipass.apps.modules.doctor._find_manifest", return_value=manifest),
            _home_at(tmp_path),
        ):
            return check_provider_manifest(**kwargs)

    def test_missing_key_is_named_with_the_cure_command(self, tmp_path) -> None:
        """The regression DPLAN-0347 exists for: doctor must NAME the absent key, not stay silent."""
        manifest = self._scratch(tmp_path, {"includeGitInstructions": False}, {"env": {}})

        results = self._run(manifest, tmp_path)

        row = [r for r in results if r.label == "includeGitInstructions"][0]
        assert row.glyph == GLYPH_WARN
        assert row.detail == "manifest wants false, provider has MISSING"
        assert row.remediation == "Run: aipass doctor --fix"

    def test_key_set_to_the_wanted_value_passes(self, tmp_path) -> None:
        """Once the wire verb has set it, doctor reads it back as wanted."""
        manifest = self._scratch(tmp_path, {"includeGitInstructions": False}, {"includeGitInstructions": False})

        results = self._run(manifest, tmp_path)

        row = [r for r in results if r.label == "includeGitInstructions"][0]
        assert row.glyph == GLYPH_PASS
        assert row.remediation == ""

    def test_different_value_is_reported_never_wired_over(self, tmp_path) -> None:
        """A value the user set themselves wins: reported, and it must not trigger auto-wire."""
        manifest = self._scratch(tmp_path, {"includeGitInstructions": False}, {"includeGitInstructions": True})

        settings = tmp_path / ".claude" / "settings.json"
        original = settings.read_bytes()

        results = self._run(manifest, tmp_path)
        with _home_at(tmp_path):
            rows = _doctor_wire.fix_provider_settings(manifest, yes=True)

        row = [r for r in results if r.label == "includeGitInstructions"][0]
        assert row.glyph == GLYPH_WARN
        assert row.detail == "manifest wants false, provider has true"
        assert "Your value stands" in row.remediation
        assert "aipass doctor --fix" in row.remediation
        assert rows == []
        assert settings.read_bytes() == original
        assert not (tmp_path / ".claude" / ".backup").exists()

    def test_missing_key_alone_still_triggers_the_fix_wire(self, tmp_path) -> None:
        """A settable gap is the one thing that still makes --fix --yes write the wire."""
        manifest = self._scratch(tmp_path, {"includeGitInstructions": False}, {"env": {}})

        with _home_at(tmp_path):
            rows = _doctor_wire.fix_provider_settings(manifest, yes=True)

        written = json.loads((tmp_path / ".claude" / "settings.json").read_text(encoding="utf-8"))
        assert rows == []
        assert written["includeGitInstructions"] is False

    def test_the_pass_after_a_wire_reads_the_handed_file_on_the_handed_platform(self, tmp_path) -> None:
        """After a wire, the re-read keeps settings_path and os_name: it never falls back to the home.

        The settings file lives outside HOME and HOME is an empty scratch dir, so a
        re-read that drops either seam finds no key and no Windows hook, and says so.
        Both wires are stubbed where doctor resolves them; the stub writes what a wire
        would into the handed file, and is asserted called before the re-read is read.
        Red first (leg 6): the re-read handed on neither -> row WARN, not PASS.
        Mutant: the re-read drops settings_path -> red at the rows assert.
        Mutant: the re-read drops os_name -> red at the rows assert.
        Mutant: check_settings_scalars not handed settings_path -> red at the rows assert.
        """
        posix_cmd = "$AIPASS_HOME/.venv/bin/python3 $AIPASS_HOME/bridges/claude.py Stop"
        windows_cmd = "$AIPASS_HOME/.venv/Scripts/python.exe $AIPASS_HOME/bridges/claude.py Stop"
        manifest = tmp_path / "project" / ".claude" / "provider_manifest.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text(
            json.dumps(
                {
                    "cli": {
                        "claude": {
                            "hooks": [{"command": posix_cmd, "event": "Stop"}],
                            "settings": {"includeGitInstructions": False},
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        settings = tmp_path / "handed" / "settings.json"
        settings.parent.mkdir()
        wired = {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": windows_cmd}]}]}}
        settings.write_text(json.dumps(wired), encoding="utf-8")
        empty_home = tmp_path / "home"
        empty_home.mkdir()

        def _wire(*_args, **_kwargs):
            settings.write_text(json.dumps({**wired, "includeGitInstructions": False}), encoding="utf-8")
            return True

        with (
            patch("aipass.aipass.apps.modules.doctor._find_manifest", return_value=manifest),
            patch("aipass.aipass.apps.modules.doctor.prompt_auto_wire", side_effect=_wire) as prompt_wire,
            _home_at(empty_home),
        ):
            results = check_provider_manifest(interactive=True, settings_path=settings, os_name="nt")

        assert prompt_wire.call_count == 1
        assert prompt_wire.call_args.kwargs["settings_path"] == settings
        rows = {r.label: r.glyph for r in results if r.label in ("hooks", "includeGitInstructions")}
        assert rows == {"hooks": GLYPH_PASS, "includeGitInstructions": GLYPH_PASS}

    def test_settings_row_from_an_earlier_pass_is_replaced_not_duplicated(self) -> None:
        """--fix/interactive re-runs the manifest check; the first pass's key row must not survive."""
        first = [
            CheckResult("drone", GLYPH_PASS, "18 citizens", ""),
            CheckResult("hooks", GLYPH_WARN, "1 hook(s) missing", ""),
            CheckResult("includeGitInstructions", GLYPH_WARN, "manifest wants false, provider has MISSING", ""),
        ]
        fresh = [
            CheckResult("hooks", GLYPH_PASS, "28 provider hooks wired", ""),
            CheckResult("includeGitInstructions", GLYPH_PASS, "false as wanted", ""),
        ]

        merged = merge_manifest_rows(first, fresh)

        assert [r.label for r in merged] == ["drone", "hooks", "includeGitInstructions"]
        assert [r.glyph for r in merged if r.label == "includeGitInstructions"] == [GLYPH_PASS]

    def test_manifest_without_the_slot_adds_no_rows(self, tmp_path) -> None:
        """No settings slot → no settings rows. Older manifests keep working unchanged."""
        manifest = tmp_path / ".claude" / "provider_manifest.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text(json.dumps({"cli": {"claude": {"hooks": []}}}), encoding="utf-8")
        (tmp_path / ".claude" / "settings.json").write_text(json.dumps({"env": {}}), encoding="utf-8")

        results = self._run(manifest, tmp_path)

        assert [r.label for r in results] == ["hooks"]


# =============================================================================
# TestHooksJsonCheck
# =============================================================================


class TestHooksJsonCheck:
    """Tests for hooks.json presence check in check_identity (DPLAN-0190)."""

    def test_hooks_json_present_returns_pass(self, tmp_path) -> None:
        """When .aipass/hooks.json exists, check returns PASS."""
        registry = tmp_path / "TEST_REGISTRY.json"
        registry.write_text(json.dumps({"metadata": {"id": "t"}, "branches": []}), encoding="utf-8")
        hooks_dir = tmp_path / ".aipass"
        hooks_dir.mkdir()
        (hooks_dir / "hooks.json").write_text('{"hooks_enabled": true}', encoding="utf-8")

        with patch("aipass.aipass.apps.modules.doctor._find_registry", return_value=registry):
            results = check_identity()

        hooks_results = [r for r in results if r.label == "hooks.json"]
        assert len(hooks_results) == 1
        assert hooks_results[0].glyph == GLYPH_PASS

    def test_hooks_json_missing_returns_warn(self, tmp_path) -> None:
        """When .aipass/hooks.json is absent, check returns WARN."""
        registry = tmp_path / "TEST_REGISTRY.json"
        registry.write_text(json.dumps({"metadata": {"id": "t"}, "branches": []}), encoding="utf-8")

        with patch("aipass.aipass.apps.modules.doctor._find_registry", return_value=registry):
            results = check_identity()

        hooks_results = [r for r in results if r.label == "hooks.json"]
        assert len(hooks_results) == 1
        assert hooks_results[0].glyph == GLYPH_WARN
        assert "init update" in hooks_results[0].remediation


class TestCodexHooksRow:
    """The codex hooks row: .codex/hooks.json measured against cli.codex, and --fix writing it."""

    _BRIDGE = "$AIPASS_HOME/.venv/bin/python3 $AIPASS_HOME/src/aipass/hooks/apps/handlers/bridges/codex.py"

    def _world(self, tmp_path, rows: list, settings: dict | None = None):
        manifest = tmp_path / "repo" / ".claude" / "provider_manifest.json"
        manifest.parent.mkdir(parents=True)
        claude = {"hooks": [], "settings": settings or {}}
        manifest.write_text(json.dumps({"cli": {"claude": claude, "codex": {"hooks": rows}}}), encoding="utf-8")
        home = tmp_path / "home"
        (home / ".claude").mkdir(parents=True)
        return manifest, home

    def _rows(self, manifest, home) -> list:
        with patch("aipass.aipass.apps.modules.doctor._find_manifest", return_value=manifest), _home_at(home):
            return [r for r in check_provider_manifest() if r.label == "codex hooks"]

    def test_a_missing_codex_file_warns_and_fix_yes_writes_it_until_the_row_passes(self, tmp_path) -> None:
        rows = [{"command": f"{self._BRIDGE} Stop", "event": "Stop"}]
        manifest, home = self._world(tmp_path, rows)
        codex = tmp_path / "repo" / ".codex" / "hooks.json"

        (before,) = self._rows(manifest, home)
        with _home_at(home):
            fixed = _doctor_wire.fix_provider_settings(manifest, yes=True)
        (after,) = self._rows(manifest, home)

        assert before.glyph == GLYPH_WARN
        assert before.detail == f"{codex} missing, wanted by cli.codex (1 hooks)"
        assert before.remediation == "Run: aipass doctor --fix"
        assert fixed == []
        written = json.loads(codex.read_text(encoding="utf-8"))
        assert written == {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": f"{self._BRIDGE} Stop"}]}]}}
        assert after.glyph == GLYPH_PASS
        assert after.detail == "1 Codex hooks match cli.codex"

    def test_a_manifest_without_codex_rows_shows_no_codex_row(self, tmp_path) -> None:
        manifest, home = self._world(tmp_path, [])

        assert self._rows(manifest, home) == []

    def test_the_fix_json_plan_diffs_each_file_once_and_writes_nothing_without_yes(self, tmp_path) -> None:
        rows = [{"command": f"{self._BRIDGE} Stop", "event": "Stop"}]
        manifest, home = self._world(tmp_path, rows, {"includeGitInstructions": False})
        codex = tmp_path / "repo" / ".codex" / "hooks.json"

        with _home_at(home):
            report = _doctor_wire.settings_fix_report(manifest)

        heads = [line for line in report["diff"] if line.startswith("--- ")]
        assert heads == [f"--- {(home / '.claude' / 'settings.json').resolve()} (now)", f"--- {codex.resolve()} (now)"]
        assert f"Write 1 Codex hook(s) from cli.codex into {codex.resolve()}" in report["planned"]
        assert report["applied"] is False
        assert not codex.exists()


class TestCodexCliRows:
    """Codex's binary, login, model and config pins: read-only rows, a fake codex, never the real one."""

    _PINS = (
        "include_collaboration_mode_instructions = false\n[features]\nmemories = false\n"
        "collaboration_modes = false\n[tools.experimental_request_user_input]\nenabled = false\n"
    )
    _CATALOG = {"models": [{"slug": "gpt-a", "visibility": "list"}, {"slug": "gpt-h", "visibility": "hide"}]}

    def _rows(self, monkeypatch, config: str | None, login_rc: int = 0) -> list:
        answers = {
            "--version": (0, "codex-cli 0.164.0\n"),
            "login": (login_rc, "Logged in using ChatGPT\n" if login_rc == 0 else "Not logged in\n"),
            "debug": (0, json.dumps(self._CATALOG)),
        }

        def run(args, **_kw):
            rc, out = answers[args[1]]
            return subprocess.CompletedProcess(args, rc, out, "")

        monkeypatch.setattr(_doctor_wire, "_codex_which", lambda name: "/usr/bin/codex")
        monkeypatch.setattr(_doctor_wire, "_codex_run", run)
        path = self._config_path
        if config is not None:
            path.write_text(config, encoding="utf-8")
        return [(r.label, r.glyph, r.detail, r.remediation) for r in _doctor_wire.check_codex_cli(path)]

    @pytest.fixture(autouse=True)
    def _at(self, tmp_path) -> None:
        self._config_path = tmp_path / "config.toml"

    def test_a_wired_codex_passes_every_row(self, monkeypatch) -> None:
        rows = self._rows(monkeypatch, 'model = "gpt-a"\n' + self._PINS)

        assert rows == [
            ("codex binary", GLYPH_PASS, "codex-cli 0.164.0", ""),
            ("codex login", GLYPH_PASS, "Logged in using ChatGPT", ""),
            ("codex model", GLYPH_PASS, "gpt-a in this login's catalog", ""),
            ("codex pins", GLYPH_PASS, "4 config pins set", ""),
        ]

    def test_no_codex_on_path_is_one_pass_row_and_nothing_runs(self, tmp_path) -> None:
        assert _doctor_wire.check_codex_cli(tmp_path / "config.toml") == [
            ("codex binary", GLYPH_PASS, "not on PATH — Codex is optional, rows skipped", "")
        ]

    def test_a_logged_out_codex_warns_with_the_login_command(self, monkeypatch) -> None:
        rows = self._rows(monkeypatch, self._PINS, login_rc=1)

        assert ("codex login", GLYPH_WARN, "Not logged in", "Run: codex login") in rows
        assert ("codex model", GLYPH_PASS, "none set — Codex's default", "") in rows

    def test_a_model_outside_the_catalog_warns_naming_the_listed_ones(self, monkeypatch) -> None:
        rows = self._rows(monkeypatch, 'model = "gpt-gone"\n' + self._PINS)

        fix = f"Set model in {self._config_path} by hand to one of: gpt-a"
        assert ("codex model", GLYPH_WARN, "gpt-gone not in this login's catalog", fix) in rows

    def test_each_missing_or_wrong_pin_is_one_warn_naming_the_line_to_add(self, monkeypatch) -> None:
        rows = self._rows(monkeypatch, "[features]\nmemories = true\n")

        path = self._config_path
        assert [r[1:] for r in rows if r[0] == "codex pins"] == [
            (GLYPH_WARN, "features.memories is true", f"Add to {path} under [features]: memories = false"),
            (
                GLYPH_WARN,
                "include_collaboration_mode_instructions missing",
                f"Add to {path} above the first [table]: include_collaboration_mode_instructions = false",
            ),
            (
                GLYPH_WARN,
                "features.collaboration_modes missing",
                f"Add to {path} under [features]: collaboration_modes = false",
            ),
            (
                GLYPH_WARN,
                "tools.experimental_request_user_input.enabled missing",
                f"Add to {path} under [tools.experimental_request_user_input]: enabled = false",
            ),
        ]

    def test_a_missing_config_warns_on_model_and_pins(self, monkeypatch) -> None:
        rows = self._rows(monkeypatch, None)

        missing = f"{self._config_path} missing"
        assert rows[2:] == [("codex model", GLYPH_WARN, missing, ""), ("codex pins", GLYPH_WARN, missing, "")]

    def test_doctor_shows_the_codex_rows_after_codex_hooks_and_fix_never_writes_config(
        self, tmp_path, monkeypatch
    ) -> None:
        world = TestCodexHooksRow()
        rows = [{"command": f"{world._BRIDGE} Stop", "event": "Stop"}]
        manifest, home = world._world(tmp_path, rows)
        monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex"))
        config = tmp_path / "codex" / "config.toml"
        config.parent.mkdir()
        config.write_text("[features]\nmemories = true\n", encoding="utf-8")
        with patch("aipass.aipass.apps.modules.doctor._find_manifest", return_value=manifest), _home_at(home):
            labels = [r.label for r in check_provider_manifest() if r.label.startswith("codex")]
            _doctor_wire.fix_provider_settings(manifest, yes=True)

        assert labels == ["codex hooks", "codex binary"]
        assert config.read_text(encoding="utf-8") == "[features]\nmemories = true\n"


# =============================================================================
# TestPassportRole
# =============================================================================


class TestPassportRole:
    """Tests for the passport role read in check_identity (round-2 addendum: identity.role, not top-level)."""

    def _run_with_passport(self, tmp_path, passport_data):
        registry = tmp_path / "TEST_REGISTRY.json"
        registry.write_text(json.dumps({"metadata": {"id": "t"}, "branches": []}), encoding="utf-8")
        trinity = tmp_path / ".trinity"
        trinity.mkdir()
        (trinity / "passport.json").write_text(json.dumps(passport_data), encoding="utf-8")

        with (
            patch("aipass.aipass.apps.modules.doctor._find_registry", return_value=registry),
            patch("aipass.aipass.apps.modules.doctor._BRANCH_ROOT", tmp_path),
            patch("aipass.aipass.apps.modules.doctor._check_owner_seating", return_value=[]),
        ):
            return check_identity()

    def test_nested_identity_role_read(self, tmp_path) -> None:
        """Role nested under identity.role is read correctly, not reported as unknown."""
        results = self._run_with_passport(tmp_path, {"identity": {"role": "citizen"}})

        passport_results = [r for r in results if r.label == "passport"]
        assert len(passport_results) == 1
        assert passport_results[0].glyph == GLYPH_PASS
        assert passport_results[0].detail == "role: citizen"

    def test_missing_identity_role_defaults_unknown(self, tmp_path) -> None:
        """A passport with no identity.role at all still defaults to 'unknown'."""
        results = self._run_with_passport(tmp_path, {"identity": {}})

        passport_results = [r for r in results if r.label == "passport"]
        assert passport_results[0].detail == "role: unknown"

    def test_top_level_role_is_ignored(self, tmp_path) -> None:
        """A stray top-level 'role' key (wrong schema) must not be read — only identity.role counts."""
        results = self._run_with_passport(tmp_path, {"role": "wrong-schema-value", "identity": {}})

        passport_results = [r for r in results if r.label == "passport"]
        assert passport_results[0].detail == "role: unknown"


# =============================================================================
# TestReconcileStaleDeny
# =============================================================================


class TestReconcileStaleDeny:
    """Tests for stale rm deny rule migration (DPLAN-0192 Phase 2)."""

    def test_no_settings_file_returns_empty(self, tmp_path) -> None:
        """Missing settings.json returns no results."""
        with _home_at(tmp_path):
            results = reconcile_stale_deny(fix=False)
        assert results == []

    def test_no_stale_rules_returns_pass(self, tmp_path) -> None:
        """Settings with no stale rm rules returns PASS."""
        settings = tmp_path / ".claude" / "settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(
            json.dumps({"permissions": {"deny": ["Bash(git push --force*)", "Bash(git reset --hard*)"]}}),
            encoding="utf-8",
        )
        with _home_at(tmp_path):
            results = reconcile_stale_deny(fix=False)
        assert len(results) == 1
        assert results[0][1] == GLYPH_PASS
        assert "no stale" in results[0][2]

    def test_stale_rules_detected_without_fix(self, tmp_path) -> None:
        """Stale rm rules present returns WARN when fix=False."""
        settings = tmp_path / ".claude" / "settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(
            json.dumps({"permissions": {"deny": ["Bash(rm -rf*)", "Bash(git push --force*)", "Bash(rm -r *)"]}}),
            encoding="utf-8",
        )
        with _home_at(tmp_path):
            results = reconcile_stale_deny(fix=False)
        assert len(results) == 1
        assert results[0][1] == GLYPH_WARN
        assert "rm -rf" in results[0][2]
        assert "rm -r " in results[0][2]

    def test_fix_removes_stale_rules(self, tmp_path) -> None:
        """fix=True removes stale rules and preserves others."""
        settings = tmp_path / ".claude" / "settings.json"
        settings.parent.mkdir(parents=True)
        original = {
            "permissions": {"deny": ["Bash(rm -rf*)", "Bash(git push --force*)", "Bash(rm -r *)"]},
            "env": {"AIPASS_HOME": "/test"},
        }
        settings.write_text(json.dumps(original), encoding="utf-8")
        with _home_at(tmp_path):
            results = reconcile_stale_deny(fix=True)
        assert len(results) == 1
        assert results[0][1] == GLYPH_PASS
        assert "removed" in results[0][2]
        updated = json.loads(settings.read_text(encoding="utf-8"))
        assert "Bash(rm -rf*)" not in updated["permissions"]["deny"]
        assert "Bash(rm -r *)" not in updated["permissions"]["deny"]
        assert "Bash(git push --force*)" in updated["permissions"]["deny"]
        assert updated["env"]["AIPASS_HOME"] == "/test"

    def test_fix_single_stale_rule(self, tmp_path) -> None:
        """fix=True works when only one of two stale rules is present."""
        settings = tmp_path / ".claude" / "settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(
            json.dumps({"permissions": {"deny": ["Bash(rm -rf*)", "Bash(git reset --hard*)"]}}),
            encoding="utf-8",
        )
        with _home_at(tmp_path):
            results = reconcile_stale_deny(fix=True)
        assert len(results) == 1
        assert results[0][1] == GLYPH_PASS
        updated = json.loads(settings.read_text(encoding="utf-8"))
        assert updated["permissions"]["deny"] == ["Bash(git reset --hard*)"]

    def test_fix_idempotent(self, tmp_path) -> None:
        """Running fix twice is safe — second run returns PASS with no stale rules."""
        settings = tmp_path / ".claude" / "settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(
            json.dumps({"permissions": {"deny": ["Bash(rm -rf*)", "Bash(rm -r *)"]}}),
            encoding="utf-8",
        )
        with _home_at(tmp_path):
            reconcile_stale_deny(fix=True)
            results = reconcile_stale_deny(fix=True)
        assert len(results) == 1
        assert results[0][1] == GLYPH_PASS
        assert "no stale" in results[0][2]

    def test_empty_deny_list_returns_pass(self, tmp_path) -> None:
        """Empty deny list returns PASS."""
        settings = tmp_path / ".claude" / "settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(json.dumps({"permissions": {"deny": []}}), encoding="utf-8")
        with _home_at(tmp_path):
            results = reconcile_stale_deny(fix=False)
        assert len(results) == 1
        assert results[0][1] == GLYPH_PASS

    def test_no_permissions_key_returns_pass(self, tmp_path) -> None:
        """Settings without permissions key returns PASS."""
        settings = tmp_path / ".claude" / "settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(json.dumps({"env": {"FOO": "bar"}}), encoding="utf-8")
        with _home_at(tmp_path):
            results = reconcile_stale_deny(fix=False)
        assert len(results) == 1
        assert results[0][1] == GLYPH_PASS


class TestCheckWireVerify:
    """Tests for check_wire_verify() — hooks wire_verify guard."""

    def test_pass_on_zero_exit(self) -> None:
        """Exit 0 from drone @hooks verify produces a PASS row."""
        fake = MagicMock(returncode=0, stdout="✓ Wire check passed\n\n0 errors, 0 warnings\n")
        with patch("aipass.aipass.apps.modules._doctor_wire.subprocess.run", return_value=fake):
            results = check_wire_verify()
        assert len(results) == 1
        assert results[0].label == "wire verify"
        assert results[0].glyph == "[green]✓[/green]"

    def test_fail_on_nonzero_exit(self) -> None:
        """Non-zero exit from drone @hooks verify produces a FAIL row."""
        fake = MagicMock(returncode=1, stdout="ERROR empty array\n2 errors, 0 warnings\n")
        with patch("aipass.aipass.apps.modules._doctor_wire.subprocess.run", return_value=fake):
            results = check_wire_verify()
        assert len(results) == 1
        assert results[0].glyph == "[red]✗[/red]"
        assert "errors" in results[0].detail

    def test_warn_on_drone_not_found(self) -> None:
        """FileNotFoundError (drone missing) produces a WARN row."""
        with patch(
            "aipass.aipass.apps.modules._doctor_wire.subprocess.run",
            side_effect=FileNotFoundError("drone"),
        ):
            results = check_wire_verify()
        assert len(results) == 1
        assert results[0].glyph == "[yellow]![/yellow]"

    def test_warn_on_timeout(self) -> None:
        """TimeoutExpired produces a WARN row."""
        import subprocess as sp

        with patch(
            "aipass.aipass.apps.modules._doctor_wire.subprocess.run",
            side_effect=sp.TimeoutExpired(cmd="drone", timeout=10),
        ):
            results = check_wire_verify()
        assert len(results) == 1
        assert results[0].glyph == "[yellow]![/yellow]"
        assert "timed out" in results[0].detail


# =============================================================================
# prompt_auto_wire — non-interactive stdin guard (issue #663)
# =============================================================================


class TestPromptAutoWireIsatty:
    """Guard: non-tty stdin must not block on input() (#663)."""

    @staticmethod
    def _args(tmp_path) -> dict:
        manifest = tmp_path / "provider_manifest.json"
        manifest.write_text(
            json.dumps({"cli": {"claude": {"hooks": [], "settings": {"includeGitInstructions": False}}}}),
            encoding="utf-8",
        )
        settings = tmp_path / ".claude" / "settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(json.dumps({"env": {}}), encoding="utf-8")
        return {
            "manifest_path": manifest,
            "missing_hooks": [],
            "missing_env": [],
            "missing_deny": [],
            "missing_ask": [],
            "missing_settings": ["includeGitInstructions"],
            "settings_path": settings,
        }

    def test_non_tty_stdin_skips_prompt_and_declines(self, tmp_path) -> None:
        """Non-tty stdin must NOT call input() — it declines and warns instead.
        Mutant `if not sys.stdin.isatty():` -> `if False:` reads the line and goes red."""
        stdin = _Stdin("n\n", tty=False)
        with (
            patch("sys.stdin", stdin),
            patch.object(_doctor_wire, "_print_manual_wire_warning") as mock_warn,
            _home_at(tmp_path),
        ):
            result = _doctor_wire._prompt_auto_wire(**self._args(tmp_path))

        assert result is False
        assert stdin.read() == "n\n"
        mock_warn.assert_called_once()

    def test_tty_stdin_prompts_and_respects_decline(self, tmp_path) -> None:
        """Tty stdin still prompts; a 'n' answer declines and writes nothing.
        Mutant `answer = input(...)` -> `answer = "n"` leaves stdin unread and goes red."""
        args = self._args(tmp_path)
        original = args["settings_path"].read_bytes()
        stdin = _Stdin("n\nleft\n", tty=True)
        with (
            patch("sys.stdin", stdin),
            patch.object(_doctor_wire, "_print_manual_wire_warning"),
            _home_at(tmp_path),
        ):
            result = _doctor_wire._prompt_auto_wire(**args)

        assert result is False
        assert stdin.read() == "left\n"
        assert args["settings_path"].read_bytes() == original

    def test_tty_stdin_accepts_and_wires(self, tmp_path) -> None:
        """Tty stdin with a 'y' answer writes the wire and its receipt carries the tty consent."""
        args = self._args(tmp_path)
        with patch("sys.stdin", _Stdin("y\n", tty=True)), _home_at(tmp_path):
            result = _doctor_wire._prompt_auto_wire(**args)

        written = json.loads(args["settings_path"].read_text(encoding="utf-8"))
        receipts = tmp_path / ".claude" / ".backup" / "settings" / "receipts.jsonl"
        (line,) = receipts.read_text(encoding="utf-8").splitlines()
        assert result is True
        assert written["includeGitInstructions"] is False
        assert json.loads(line)["summary"][0] == "consent: y (tty)"


class TestPreflightWireDoor:
    """The install tail's doctor preflight wires the settings file under the install door (FPLAN-0645)."""

    def test_the_preflight_backs_up_under_the_install_door_and_prints_both_paths(
        self, tmp_path, monkeypatch, capsys
    ) -> None:
        # Every group but the provider wire is stubbed and HOME is tmp_path: no live state is read or written.
        mod = "aipass.aipass.apps.modules.doctor"
        stubbed = ("_check_system", "check_identity", "_check_community", "_check_structure", "_check_scaffold")
        for name in (*stubbed, "_check_sandbox", "check_wire_verify", "_fix_owner_seating"):
            monkeypatch.setattr(f"{mod}.{name}", lambda: [])
        monkeypatch.setattr(f"{mod}._check_services", lambda **_kw: [])
        manifest = tmp_path / ".claude" / "provider_manifest.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text(
            json.dumps({"cli": {"claude": {"hooks": [], "settings": {"includeGitInstructions": False}}}}),
            encoding="utf-8",
        )
        (tmp_path / ".claude" / "settings.json").write_text(json.dumps({"env": {}}), encoding="utf-8")
        monkeypatch.setattr(f"{mod}._find_manifest", lambda: manifest)

        with _home_at(tmp_path):
            run_doctor_preflight()

        folder = tmp_path / ".claude" / ".backup" / "settings"
        lines = (folder / "receipts.jsonl").read_text(encoding="utf-8").splitlines()
        assert [json.loads(line)["door"] for line in lines] == ["install"]
        (backup,) = [p for p in folder.iterdir() if p.name != "receipts.jsonl"]
        assert backup.name.endswith(".install")
        # Rich may wrap a long tmp path: compare with all whitespace collapsed.
        out = "".join(capsys.readouterr().out.split())
        assert "".join(f"Backed up settings to {backup}".split()) in out
        assert "".join(f"Receipt: {folder / 'receipts.jsonl'}".split()) in out


class TestDoctorFixAsks:
    """doctor --fix shows the settings plan and asks once; --yes and install never ask (FPLAN-0646)."""

    @staticmethod
    def _world(tmp_path, monkeypatch) -> "tuple":
        # Every group but the provider wire is stubbed and HOME is tmp_path: no live state is read or written.
        mod = "aipass.aipass.apps.modules.doctor"
        stubbed = ("_check_system", "check_identity", "_check_community", "_check_structure", "_check_scaffold")
        for name in (*stubbed, "_check_sandbox", "check_wire_verify", "_fix_owner_seating"):
            monkeypatch.setattr(f"{mod}.{name}", lambda: [])
        monkeypatch.setattr(f"{mod}._check_services", lambda **_kw: [])
        claude = tmp_path / ".claude"
        claude.mkdir()
        manifest = claude / "provider_manifest.json"
        manifest.write_text(
            json.dumps({"cli": {"claude": {"hooks": [], "permissions": {"deny": ["Edit(~/.claude/**)"]}}}}),
            encoding="utf-8",
        )
        settings = claude / "settings.json"
        settings.write_text(json.dumps({"permissions": {"deny": ["Bash(rm -r *)"]}}), encoding="utf-8")
        monkeypatch.setattr(f"{mod}._find_manifest", lambda: manifest)
        return settings, settings.read_bytes(), claude / ".backup" / "settings"

    @staticmethod
    def _groups_via_run_doctor(**kwargs) -> dict:
        """The groups run_doctor would print, caught at the printer."""
        printed: dict = {}

        def record(groups: dict) -> tuple[int, int, int]:
            printed.update(groups)
            return 0, 0, 0

        with patch("aipass.aipass.apps.modules.doctor._print_doctor_groups", side_effect=record):
            run_doctor(**kwargs)
        return printed

    @staticmethod
    def _consents(folder) -> list:
        lines = (folder / "receipts.jsonl").read_text(encoding="utf-8").splitlines()
        return [json.loads(line)["summary"][0] for line in lines]

    def test_a_tty_no_answer_writes_nothing(self, tmp_path, monkeypatch, capsys) -> None:
        """Answer n: the file is byte-identical, no backup folder, and doctor says nothing changed.
        Mutant: apply the plans before the answer -> the file changes and goes red."""
        settings, original, _folder = self._world(tmp_path, monkeypatch)
        with patch("sys.stdin", _Stdin("n\n", tty=True)), _home_at(tmp_path):
            run_doctor(fix=True, interactive=True)

        out = " ".join(capsys.readouterr().out.split())
        assert settings.read_bytes() == original
        assert not (tmp_path / ".claude" / ".backup").exists()
        assert " ".join(_doctor_wire.NOTHING_CHANGED.split()) in out

    def test_b_tty_yes_answer_writes_with_a_tty_receipt(self, tmp_path, monkeypatch) -> None:
        """Answer y: both plans land, each backed up, each receipt carrying the tty consent."""
        settings, original, folder = self._world(tmp_path, monkeypatch)
        with patch("sys.stdin", _Stdin("y\n", tty=True)), _home_at(tmp_path):
            run_doctor(fix=True, interactive=True)

        deny = json.loads(settings.read_text(encoding="utf-8"))["permissions"]["deny"]
        assert settings.read_bytes() != original
        assert deny == ["Edit(~/.claude/**)"]
        assert self._consents(folder) == ["consent: y (tty)", "consent: y (tty)"]
        assert len([p for p in folder.iterdir() if p.name != "receipts.jsonl"]) == 2

    def test_c_no_tty_without_yes_writes_nothing(self, tmp_path, monkeypatch, capsys) -> None:
        """No tty, no --yes: nothing written, the row names the --yes command.
        Mutant `if not sys.stdin.isatty():` -> `if False:` reads the answer, writes, and goes red."""
        settings, original, _folder = self._world(tmp_path, monkeypatch)
        with patch("sys.stdin", _Stdin("y\n", tty=False)), _home_at(tmp_path):
            run_doctor(fix=True, interactive=True)

        out = " ".join(capsys.readouterr().out.split())
        assert settings.read_bytes() == original
        assert not (tmp_path / ".claude" / ".backup").exists()
        assert " ".join(_doctor_wire.NOT_APPLIED_NO_TTY.split()) in out

    def test_d_yes_without_tty_writes_without_asking(self, tmp_path, monkeypatch, capsys) -> None:
        """--yes with no tty: written, no question printed, the receipt carries --yes."""
        settings, original, folder = self._world(tmp_path, monkeypatch)
        with patch("sys.stdin", _Stdin("", tty=False)), _home_at(tmp_path):
            handle_command("doctor", ["--fix", "--yes"])

        out = capsys.readouterr().out
        assert settings.read_bytes() != original
        assert "Apply these" not in out
        assert "Planned changes" not in out
        assert self._consents(folder) == ["consent: --yes", "consent: --yes"]

    def test_e_the_plan_shows_a_unified_diff(self, tmp_path, monkeypatch, capsys) -> None:
        """The shown plan carries the removed stale rule and the added manifest rule as diff lines."""
        self._world(tmp_path, monkeypatch)
        with patch("sys.stdin", _Stdin("n\n", tty=True)), _home_at(tmp_path):
            run_doctor(fix=True, interactive=True)

        lines = capsys.readouterr().out.splitlines()
        assert any(re.match(r'-\s+"Bash\(rm -r \*\)"', line) for line in lines)
        assert any(re.match(r'\+\s+"Edit\(~/\.claude/\*\*\)"', line) for line in lines)

    def test_f_the_install_preflight_never_asks(self, tmp_path, monkeypatch, capsys) -> None:
        """Install with no tty writes without the question; the receipts carry the install consent.
        Mutant: ask inside the install door -> no tty means nothing written, red."""
        settings, original, folder = self._world(tmp_path, monkeypatch)
        with patch("sys.stdin", _Stdin("", tty=False)), _home_at(tmp_path):
            run_doctor_preflight()

        assert settings.read_bytes() != original
        assert "Apply these" not in capsys.readouterr().out
        assert self._consents(folder) == ["consent: install", "consent: install"]

    def test_g_an_unparseable_settings_file_is_a_fail_row_and_stays_byte_identical(self, tmp_path, monkeypatch) -> None:
        """A JSON typo in the settings file refuses the plan; the row FAILs and nothing is written."""
        settings, _original, _folder = self._world(tmp_path, monkeypatch)
        settings.write_text('{"permissions": {},}', encoding="utf-8")
        broken = settings.read_bytes()
        with patch("sys.stdin", _Stdin("", tty=False)), _home_at(tmp_path):
            groups = self._groups_via_run_doctor(fix=True, yes=True)

        (row,) = [r for r in groups["Services"] if r.label == _doctor_wire.SETTINGS_FIX_LABEL]
        assert row.glyph == GLYPH_FAIL
        assert "unreadable" in row.detail
        assert settings.read_bytes() == broken

    def test_h_an_owner_fix_that_exits_zero_shows_the_recheck(self, tmp_path, monkeypatch) -> None:
        """sync-registry --fix exits 0 but the seat is still broken: the recheck's FAIL row shows, not a tick."""
        self._world(tmp_path, monkeypatch)
        still = CheckResult("owner/unseated", GLYPH_FAIL, "still unseated", "")
        monkeypatch.setattr(doctor, "_fix_owner_seating", lambda: [CheckResult("owner fix", GLYPH_PASS, "ok", "")])
        monkeypatch.setattr(doctor, "_check_owner_seating", lambda: [still])
        with patch("sys.stdin", _Stdin("", tty=False)), _home_at(tmp_path):
            groups = self._groups_via_run_doctor(fix=True, yes=True)

        assert groups["Identity"] == [still]
