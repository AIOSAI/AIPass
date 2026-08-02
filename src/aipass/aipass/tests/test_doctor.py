# =================== AIPass ====================
# Name: test_doctor.py
# Description: Tests for aipass doctor Phase 1
# Version: 1.0.0
# Created: 2026-04-16
# Modified: 2026-04-16
# =============================================

"""Tests for aipass doctor command — Phase 1 (FPLAN-0188)."""

import json
import os
from unittest.mock import MagicMock, patch

import pytest  # pyright: ignore[reportMissingImports]

from aipass.aipass.apps.handlers.system_detect.system_detector import (
    detect_cpu,
    detect_git,
    detect_os,
    detect_python,
    detect_ram,
    detect_shell,
    detect_docker,
    detect_tmux,
    detect_wt,
)
from aipass.aipass.apps.handlers.ui.progress import (
    GLYPH_FAIL,
    GLYPH_PASS,
    GLYPH_WARN,
    activity_spinner,
    format_check,
    make_doctor_progress,
    render_step_header,
)
from aipass.aipass.apps.modules.doctor import handle_command, run_doctor


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def clean_env(monkeypatch):
    """Remove AIPASS_HOME from environment."""
    monkeypatch.delenv("AIPASS_HOME", raising=False)


# =============================================================================
# TestDetectPython
# =============================================================================


class TestDetectPython:
    def test_current_python_ok(self) -> None:
        """Running Python is >=3.9 and reports ok=True."""
        result = detect_python()
        import sys

        assert result["major"] == sys.version_info.major
        assert result["minor"] == sys.version_info.minor
        assert "." in result["version"]
        # Running tests on 3.9+ so ok must be True
        assert result["ok"] is True
        assert result["warning"] is False

    def test_python_38_is_warning(self) -> None:
        """Python 3.8 is marked as warning, not ok."""
        with patch("aipass.aipass.apps.handlers.system_detect.system_detector.sys") as mock_sys:
            mock_sys.version_info = MagicMock(major=3, minor=8, micro=0)
            result = detect_python()
        assert result["ok"] is False
        assert result["warning"] is True

    def test_python_37_is_fail(self) -> None:
        """Python 3.7 is not ok and not warning."""
        with patch("aipass.aipass.apps.handlers.system_detect.system_detector.sys") as mock_sys:
            mock_sys.version_info = MagicMock(major=3, minor=7, micro=0)
            result = detect_python()
        assert result["ok"] is False
        assert result["warning"] is False

    def test_version_string_format(self) -> None:
        """Version string contains two dots (major.minor.micro)."""
        result = detect_python()
        assert result["version"].count(".") == 2


# =============================================================================
# TestDetectGit
# =============================================================================


class TestDetectGit:
    def test_git_found(self) -> None:
        """When git is on PATH, found=True and version is non-empty."""
        with patch(
            "aipass.aipass.apps.handlers.system_detect.system_detector.shutil.which", return_value="/usr/bin/git"
        ):
            with patch("aipass.aipass.apps.handlers.system_detect.system_detector.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(stdout="git version 2.43.0\n", returncode=0)
                result = detect_git()
        assert result["found"] is True
        assert result["version"] == "2.43.0"

    def test_git_not_found(self) -> None:
        """When git is not on PATH, found=False."""
        with patch("aipass.aipass.apps.handlers.system_detect.system_detector.shutil.which", return_value=None):
            result = detect_git()
        assert result["found"] is False
        assert result["version"] == ""

    def test_git_version_parse_failure(self) -> None:
        """If git --version fails, found=True but version is raw output."""
        with patch(
            "aipass.aipass.apps.handlers.system_detect.system_detector.shutil.which", return_value="/usr/bin/git"
        ):
            with patch("aipass.aipass.apps.handlers.system_detect.system_detector.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(stdout="weird\n", returncode=0)
                result = detect_git()
        assert result["found"] is True


# =============================================================================
# TestDetectRam
# =============================================================================


class TestDetectRam:
    def test_high_ram_ok(self) -> None:
        """16 GB RAM reports ok=True, warning=False."""
        with patch("aipass.aipass.apps.handlers.system_detect.system_detector._total_ram_gb", return_value=16.0):
            result = detect_ram()
        assert result["ok"] is True
        assert result["warning"] is False
        assert result["total_gb"] == 16.0

    def test_low_ram_warning(self) -> None:
        """3 GB RAM reports ok=False, warning=True."""
        with patch("aipass.aipass.apps.handlers.system_detect.system_detector._total_ram_gb", return_value=3.0):
            result = detect_ram()
        assert result["ok"] is False
        assert result["warning"] is True

    def test_very_low_ram_fail(self) -> None:
        """1 GB RAM reports both ok=False and warning=False."""
        with patch("aipass.aipass.apps.handlers.system_detect.system_detector._total_ram_gb", return_value=1.0):
            result = detect_ram()
        assert result["ok"] is False
        assert result["warning"] is False

    def test_exactly_four_gb_ok(self) -> None:
        """Exactly 4.0 GB is ok (boundary)."""
        with patch("aipass.aipass.apps.handlers.system_detect.system_detector._total_ram_gb", return_value=4.0):
            result = detect_ram()
        assert result["ok"] is True


# =============================================================================
# TestDetectOS
# =============================================================================


class TestDetectOS:
    def test_returns_os_keys(self) -> None:
        """Result has os_name, release, machine keys."""
        result = detect_os()
        assert "os_name" in result
        assert "release" in result
        assert "machine" in result

    def test_os_name_non_empty(self) -> None:
        """os_name is always non-empty."""
        result = detect_os()
        assert result["os_name"] != ""


# =============================================================================
# TestDetectShell
# =============================================================================


class TestDetectShell:
    def test_shell_from_env(self, monkeypatch) -> None:
        """Shell name extracted from SHELL env var."""
        monkeypatch.setenv("SHELL", "/bin/bash")
        result = detect_shell()
        assert result["name"] == "bash"
        assert result["path"] == "/bin/bash"

    def test_shell_missing_env_and_no_proc_fallback(self, monkeypatch) -> None:
        """Missing SHELL env var and no /proc fallback available returns 'unknown'."""
        monkeypatch.delenv("SHELL", raising=False)
        with patch(
            "aipass.aipass.apps.handlers.system_detect.system_detector._shell_from_parent_proc",
            return_value=None,
        ):
            result = detect_shell()
        assert result["name"] == "unknown"
        assert result["path"] == ""

    def test_shell_missing_env_falls_back_to_proc_comm(self, monkeypatch) -> None:
        """Missing SHELL but a resolvable parent /proc comm name is used instead of 'unknown'."""
        monkeypatch.delenv("SHELL", raising=False)
        with (
            patch(
                "aipass.aipass.apps.handlers.system_detect.system_detector._shell_from_parent_proc",
                return_value="zsh",
            ),
            patch(
                "aipass.aipass.apps.handlers.system_detect.system_detector.shutil.which",
                return_value="/usr/bin/zsh",
            ),
        ):
            result = detect_shell()
        assert result["name"] == "zsh"
        assert result["path"] == "/usr/bin/zsh"

    def test_shell_missing_env_proc_comm_not_on_path(self, monkeypatch) -> None:
        """Parent comm name resolves but isn't found via which — bare name still beats 'unknown'."""
        monkeypatch.delenv("SHELL", raising=False)
        with (
            patch(
                "aipass.aipass.apps.handlers.system_detect.system_detector._shell_from_parent_proc",
                return_value="bash",
            ),
            patch(
                "aipass.aipass.apps.handlers.system_detect.system_detector.shutil.which",
                return_value=None,
            ),
        ):
            result = detect_shell()
        assert result["name"] == "bash"
        assert result["path"] == ""


# =============================================================================
# TestShellFromParentProc
# =============================================================================


"""The three forced-posix tests patch os.name process-wide; on Windows that
makes pathlib dispatch Path() to PosixPath, which any code running inside the
patch window (e.g. the logger call in the OSError branch) trips over with
NotImplementedError. The code path is POSIX-gated anyway — skip on Windows;
test_non_posix_returns_none keeps the Windows-relevant coverage."""
_posix_only = pytest.mark.skipif(os.name == "nt", reason="forces os.name='posix'; breaks pathlib dispatch on Windows")


class TestShellFromParentProc:
    def test_non_posix_returns_none(self, monkeypatch) -> None:
        from aipass.aipass.apps.handlers.system_detect import system_detector

        monkeypatch.setattr(system_detector.os, "name", "nt")
        assert system_detector._shell_from_parent_proc() is None

    @_posix_only
    def test_reads_comm_file(self, monkeypatch, tmp_path) -> None:
        from aipass.aipass.apps.handlers.system_detect import system_detector

        fake_ppid = 424242
        proc_dir = tmp_path / str(fake_ppid)
        proc_dir.mkdir()
        (proc_dir / "comm").write_text("bash\n", encoding="utf-8")

        monkeypatch.setattr(system_detector.os, "name", "posix")
        monkeypatch.setattr(system_detector.os, "getppid", lambda: fake_ppid)

        real_path_cls = system_detector.Path

        def _fake_path(arg, *a, **kw):
            if str(arg) == f"/proc/{fake_ppid}/comm":
                return real_path_cls(proc_dir / "comm")
            return real_path_cls(arg, *a, **kw)

        monkeypatch.setattr(system_detector, "Path", _fake_path)
        assert system_detector._shell_from_parent_proc() == "bash"

    @_posix_only
    def test_missing_comm_file_returns_none(self, monkeypatch, tmp_path) -> None:
        from aipass.aipass.apps.handlers.system_detect import system_detector

        fake_ppid = 999999
        monkeypatch.setattr(system_detector.os, "name", "posix")
        monkeypatch.setattr(system_detector.os, "getppid", lambda: fake_ppid)

        real_path_cls = system_detector.Path

        def _fake_path(arg, *a, **kw):
            if str(arg) == f"/proc/{fake_ppid}/comm":
                return real_path_cls(tmp_path / "nonexistent" / "comm")
            return real_path_cls(arg, *a, **kw)

        monkeypatch.setattr(system_detector, "Path", _fake_path)
        assert system_detector._shell_from_parent_proc() is None

    @_posix_only
    def test_read_oserror_returns_none(self, monkeypatch) -> None:
        from aipass.aipass.apps.handlers.system_detect import system_detector

        monkeypatch.setattr(system_detector.os, "name", "posix")
        monkeypatch.setattr(system_detector.os, "getppid", lambda: 1)

        class _BoomPath:
            def is_file(self):
                return True

            def read_text(self, encoding="utf-8"):
                raise OSError("permission denied")

        monkeypatch.setattr(system_detector, "Path", lambda *a, **kw: _BoomPath())
        assert system_detector._shell_from_parent_proc() is None


# =============================================================================
# TestDetectCpu
# =============================================================================


class TestDetectCpu:
    def test_returns_positive_count(self) -> None:
        """CPU count is a positive integer."""
        result = detect_cpu()
        assert isinstance(result["count"], int)
        assert result["count"] >= 1


# =============================================================================
# TestDetectOptionalTools
# =============================================================================


class TestDetectOptionalTools:
    def test_tmux_found(self) -> None:
        """True when tmux binary is on PATH."""
        with patch(
            "aipass.aipass.apps.handlers.system_detect.system_detector.shutil.which", return_value="/usr/bin/tmux"
        ):
            assert detect_tmux() is True

    def test_tmux_not_found(self) -> None:
        """False when tmux is absent from PATH."""
        with patch("aipass.aipass.apps.handlers.system_detect.system_detector.shutil.which", return_value=None):
            assert detect_tmux() is False

    def test_docker_found(self) -> None:
        """True when docker binary is on PATH."""
        with patch(
            "aipass.aipass.apps.handlers.system_detect.system_detector.shutil.which", return_value="/usr/bin/docker"
        ):
            assert detect_docker() is True

    def test_wt_not_on_linux(self) -> None:
        """False when wt.exe (Windows Terminal) is absent from PATH."""
        with patch("aipass.aipass.apps.handlers.system_detect.system_detector.shutil.which", return_value=None):
            assert detect_wt() is False


# =============================================================================
# TestProgressHelpers
# =============================================================================


class TestProgressHelpers:
    def test_glyph_constants(self) -> None:
        """Glyph constants contain Rich markup colour tags."""
        assert "green" in GLYPH_PASS
        assert "yellow" in GLYPH_WARN
        assert "red" in GLYPH_FAIL

    def test_format_check_pass(self) -> None:
        """format_check with GLYPH_PASS includes label."""
        line = format_check("python", GLYPH_PASS, "3.11.5")
        assert "python" in line
        assert "3.11.5" in line

    def test_format_check_with_remediation(self) -> None:
        """Remediation text is included when provided."""
        line = format_check("git", GLYPH_FAIL, "not found", "Install git")
        assert "Install git" in line

    def test_format_check_no_remediation(self) -> None:
        """No remediation means no extra line."""
        line = format_check("shell", GLYPH_PASS, "bash")
        assert "\n" not in line

    def test_make_doctor_progress_returns_progress(self) -> None:
        """make_doctor_progress returns a Rich Progress instance."""
        from rich.progress import Progress

        prog = make_doctor_progress()
        assert isinstance(prog, Progress)

    def test_render_step_header_shows_step_and_label(self) -> None:
        """Header carries the step counter and the stage label."""
        line = render_step_header(3, 10, "User profile")
        assert "Step 3/10" in line
        assert "User profile" in line

    def test_render_step_header_bar_fills_with_progress(self) -> None:
        """The bar has more filled cells later in the flow, full at the end."""
        early = render_step_header(1, 10, "x", width=18)
        late = render_step_header(10, 10, "x", width=18)
        assert late.count("█") > early.count("█")
        assert late.count("█") == 18

    def test_render_step_header_clamps_out_of_range(self) -> None:
        """current > total and total <= 0 are clamped — no overflow, no div-by-zero."""
        over = render_step_header(15, 10, "x", width=18)
        assert over.count("█") == 18
        zero = render_step_header(0, 0, "x", width=18)
        assert "Step 0/1" in zero

    def test_activity_spinner_yields_progress_and_runs_block(self) -> None:
        """activity_spinner is a context manager yielding a Progress; block runs."""
        from rich.progress import Progress

        ran = []
        with activity_spinner("doing a thing…") as prog:
            assert isinstance(prog, Progress)
            ran.append(True)
        assert ran == [True]


# =============================================================================
# TestDoctorHandleCommand
# =============================================================================


class TestDoctorHandleCommand:
    def test_wrong_command_returns_false(self) -> None:
        """Non-doctor commands are not handled."""
        assert handle_command("help", []) is False
        assert handle_command("init", ["--verbose"]) is False

    def test_no_args_runs_doctor(self) -> None:
        """No args runs run_doctor (returns True when 0 errors)."""
        with patch("aipass.aipass.apps.modules.doctor.run_doctor", return_value=0):
            result = handle_command("doctor", [])
        assert result is True

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
        """When run_doctor returns 0 errors, handle_command returns True."""
        with patch("aipass.aipass.apps.modules.doctor.run_doctor", return_value=0):
            with patch("aipass.aipass.apps.modules.doctor.json_handler"):
                result = handle_command("doctor", ["--check"])
        assert result is True

    def test_doctor_with_errors_raises_system_exit(self) -> None:
        """When run_doctor returns errors, SystemExit(1) is raised."""
        with patch("aipass.aipass.apps.modules.doctor.run_doctor", return_value=2):
            with patch("aipass.aipass.apps.modules.doctor.json_handler"):
                with pytest.raises(SystemExit) as exc_info:
                    handle_command("doctor", ["--check"])
        assert exc_info.value.code == 1

    def test_verbose_flag_passed_to_run_doctor(self) -> None:
        """--verbose flag is forwarded to run_doctor."""
        with patch("aipass.aipass.apps.modules.doctor.run_doctor", return_value=0) as mock_run:
            with patch("aipass.aipass.apps.modules.doctor.json_handler"):
                handle_command("doctor", ["--verbose"])
        mock_run.assert_called_once_with(verbose=True, interactive=True, fix=False)


# =============================================================================
# TestRunDoctor
# =============================================================================


class TestRunDoctor:
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
            patch("aipass.aipass.apps.modules.doctor._check_identity", return_value=[]),
            patch("aipass.aipass.apps.modules.doctor._check_services", return_value=[]),
            patch("aipass.aipass.apps.modules.doctor._check_community", return_value=[]),
            patch("aipass.aipass.apps.modules.doctor._check_structure", return_value=[]),
        ):
            result = run_doctor()
        assert isinstance(result, int)
        assert result == 0

    def test_run_doctor_counts_errors(self) -> None:
        """Error glyphs in results increment error count."""
        from aipass.aipass.apps.modules.doctor import CheckResult

        fail_check = CheckResult("test", GLYPH_FAIL, "bad", "fix it")
        with (
            patch("aipass.aipass.apps.modules.doctor._check_system", return_value=[fail_check]),
            patch("aipass.aipass.apps.modules.doctor._check_identity", return_value=[]),
            patch("aipass.aipass.apps.modules.doctor._check_services", return_value=[]),
            patch("aipass.aipass.apps.modules.doctor._check_community", return_value=[]),
            patch("aipass.aipass.apps.modules.doctor._check_structure", return_value=[]),
        ):
            result = run_doctor()
        assert result == 1

    def test_run_doctor_counts_only_errors_not_warnings(self) -> None:
        """Warning glyphs do not increment error count."""
        from aipass.aipass.apps.modules.doctor import CheckResult

        warn_check = CheckResult("test", GLYPH_WARN, "minor", "")
        with (
            patch("aipass.aipass.apps.modules.doctor._check_system", return_value=[warn_check]),
            patch("aipass.aipass.apps.modules.doctor._check_identity", return_value=[]),
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
        from aipass.aipass.apps.modules.doctor import _check_provider_manifest

        with patch("aipass.aipass.apps.modules.doctor._find_manifest", return_value=None):
            results = _check_provider_manifest()
        assert len(results) == 1
        assert results[0].glyph == GLYPH_WARN
        assert "manifest" in results[0].detail

    def test_manifest_unreadable_returns_warn(self, tmp_path) -> None:
        """Corrupt manifest file → WARN."""
        from aipass.aipass.apps.modules.doctor import _check_provider_manifest

        bad_manifest = tmp_path / ".claude" / "provider_manifest.json"
        bad_manifest.parent.mkdir(parents=True)
        bad_manifest.write_text("not json{{{", encoding="utf-8")
        with patch("aipass.aipass.apps.modules.doctor._find_manifest", return_value=bad_manifest):
            results = _check_provider_manifest()
        assert len(results) == 1
        assert results[0].glyph == GLYPH_WARN
        assert "unreadable" in results[0].detail

    def test_manifest_no_claude_section(self, tmp_path) -> None:
        """Manifest with no cli.claude → WARN."""
        from aipass.aipass.apps.modules.doctor import _check_provider_manifest

        manifest = tmp_path / ".claude" / "provider_manifest.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text(json.dumps({"cli": {}}), encoding="utf-8")
        with patch("aipass.aipass.apps.modules.doctor._find_manifest", return_value=manifest):
            results = _check_provider_manifest()
        assert len(results) == 1
        assert results[0].glyph == GLYPH_WARN

    def test_all_hooks_present(self, tmp_path) -> None:
        """All hook scripts exist → PASS for hooks."""
        from aipass.aipass.apps.modules.doctor import _check_provider_manifest

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
            patch("aipass.aipass.apps.modules.doctor.Path.home", return_value=tmp_path),
        ):
            results = _check_provider_manifest()
        hooks_result = [r for r in results if r.label == "hooks"][0]
        assert hooks_result.glyph == GLYPH_PASS
        assert "2" in hooks_result.detail

    def test_missing_hook_detected(self, tmp_path) -> None:
        """Missing hook command in provider settings → WARN."""
        from aipass.aipass.apps.modules.doctor import _check_provider_manifest

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
            patch("aipass.aipass.apps.modules.doctor.Path.home", return_value=tmp_path),
        ):
            results = _check_provider_manifest()
        hooks_result = [r for r in results if r.label == "hooks"][0]
        assert hooks_result.glyph == GLYPH_WARN
        assert "Stop" in hooks_result.detail

    def test_missing_hook_label_not_double_prefixed(self, tmp_path) -> None:
        """Command already shaped like 'event:label' must not get the event prefixed twice."""
        from aipass.aipass.apps.modules.doctor import _check_provider_manifest

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
            patch("aipass.aipass.apps.modules.doctor.Path.home", return_value=tmp_path),
        ):
            results = _check_provider_manifest()
        hooks_result = [r for r in results if r.label == "hooks"][0]
        assert "UserPromptSubmit:UserPromptSubmit" not in hooks_result.detail
        assert "UserPromptSubmit:presence_gate" in hooks_result.detail

    def test_missing_hook_duplicate_matchers_deduped(self, tmp_path) -> None:
        """Same command missing under two matchers must appear once in the report, not twice."""
        from aipass.aipass.apps.modules.doctor import _check_provider_manifest

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
            patch("aipass.aipass.apps.modules.doctor.Path.home", return_value=tmp_path),
        ):
            results = _check_provider_manifest()
        hooks_result = [r for r in results if r.label == "hooks"][0]
        assert hooks_result.detail.count("PreCompact:pre_compact_prep") == 1

    def test_env_vars_all_present(self, tmp_path) -> None:
        """All manifest env vars present in provider settings → PASS."""
        from aipass.aipass.apps.modules.doctor import _check_provider_manifest

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
            patch("aipass.aipass.apps.modules.doctor.Path.home", return_value=tmp_path),
        ):
            results = _check_provider_manifest()
        env_results = [r for r in results if r.label == "env vars"]
        assert len(env_results) == 1
        assert env_results[0].glyph == GLYPH_PASS

    def test_env_vars_missing(self, tmp_path) -> None:
        """Missing env var → WARN with var name."""
        from aipass.aipass.apps.modules.doctor import _check_provider_manifest

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
            patch("aipass.aipass.apps.modules.doctor.Path.home", return_value=tmp_path),
        ):
            results = _check_provider_manifest()
        env_results = [r for r in results if r.label == "env vars"]
        assert len(env_results) == 1
        assert env_results[0].glyph == GLYPH_WARN
        assert "MISSING_VAR" in env_results[0].detail

    def test_find_manifest_walks_up(self, tmp_path, monkeypatch) -> None:
        """_find_manifest finds manifest by walking up from CWD."""
        from aipass.aipass.apps.modules.doctor import _find_manifest

        manifest = tmp_path / ".claude" / "provider_manifest.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text("{}", encoding="utf-8")
        subdir = tmp_path / "src" / "deep"
        subdir.mkdir(parents=True)
        monkeypatch.chdir(subdir)
        monkeypatch.delenv("AIPASS_HOME", raising=False)
        result = _find_manifest()
        assert result is not None
        assert result == manifest


# =============================================================================
# TestHooksJsonCheck
# =============================================================================


class TestHooksJsonCheck:
    """Tests for hooks.json presence check in _check_identity (DPLAN-0190)."""

    def test_hooks_json_present_returns_pass(self, tmp_path) -> None:
        """When .aipass/hooks.json exists, check returns PASS."""
        from aipass.aipass.apps.modules.doctor import _check_identity

        registry = tmp_path / "TEST_REGISTRY.json"
        registry.write_text(json.dumps({"metadata": {"id": "t"}, "branches": []}), encoding="utf-8")
        hooks_dir = tmp_path / ".aipass"
        hooks_dir.mkdir()
        (hooks_dir / "hooks.json").write_text('{"hooks_enabled": true}', encoding="utf-8")

        with patch("aipass.aipass.apps.modules.doctor._find_registry", return_value=registry):
            results = _check_identity()

        hooks_results = [r for r in results if r.label == "hooks.json"]
        assert len(hooks_results) == 1
        assert hooks_results[0].glyph == GLYPH_PASS

    def test_hooks_json_missing_returns_warn(self, tmp_path) -> None:
        """When .aipass/hooks.json is absent, check returns WARN."""
        from aipass.aipass.apps.modules.doctor import _check_identity

        registry = tmp_path / "TEST_REGISTRY.json"
        registry.write_text(json.dumps({"metadata": {"id": "t"}, "branches": []}), encoding="utf-8")

        with patch("aipass.aipass.apps.modules.doctor._find_registry", return_value=registry):
            results = _check_identity()

        hooks_results = [r for r in results if r.label == "hooks.json"]
        assert len(hooks_results) == 1
        assert hooks_results[0].glyph == GLYPH_WARN
        assert "init update" in hooks_results[0].remediation


# =============================================================================
# TestPassportRole
# =============================================================================


class TestPassportRole:
    """Tests for the passport role read in _check_identity (round-2 addendum: identity.role, not top-level)."""

    def _run_with_passport(self, tmp_path, passport_data):
        from aipass.aipass.apps.modules.doctor import _check_identity

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
            return _check_identity()

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
        from aipass.aipass.apps.modules._doctor_wire import reconcile_stale_deny

        with patch("aipass.aipass.apps.handlers.provider_reconcile.Path.home", return_value=tmp_path):
            results = reconcile_stale_deny(fix=False)
        assert results == []

    def test_no_stale_rules_returns_pass(self, tmp_path) -> None:
        """Settings with no stale rm rules returns PASS."""
        from aipass.aipass.apps.modules._doctor_wire import reconcile_stale_deny

        settings = tmp_path / ".claude" / "settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(
            json.dumps({"permissions": {"deny": ["Bash(git push --force*)", "Bash(git reset --hard*)"]}}),
            encoding="utf-8",
        )
        with patch("aipass.aipass.apps.handlers.provider_reconcile.Path.home", return_value=tmp_path):
            results = reconcile_stale_deny(fix=False)
        assert len(results) == 1
        assert results[0][1] == GLYPH_PASS
        assert "no stale" in results[0][2]

    def test_stale_rules_detected_without_fix(self, tmp_path) -> None:
        """Stale rm rules present returns WARN when fix=False."""
        from aipass.aipass.apps.modules._doctor_wire import reconcile_stale_deny

        settings = tmp_path / ".claude" / "settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(
            json.dumps({"permissions": {"deny": ["Bash(rm -rf*)", "Bash(git push --force*)", "Bash(rm -r *)"]}}),
            encoding="utf-8",
        )
        with patch("aipass.aipass.apps.handlers.provider_reconcile.Path.home", return_value=tmp_path):
            results = reconcile_stale_deny(fix=False)
        assert len(results) == 1
        assert results[0][1] == GLYPH_WARN
        assert "rm -rf" in results[0][2]
        assert "rm -r " in results[0][2]

    def test_fix_removes_stale_rules(self, tmp_path) -> None:
        """fix=True removes stale rules and preserves others."""
        from aipass.aipass.apps.modules._doctor_wire import reconcile_stale_deny

        settings = tmp_path / ".claude" / "settings.json"
        settings.parent.mkdir(parents=True)
        original = {
            "permissions": {"deny": ["Bash(rm -rf*)", "Bash(git push --force*)", "Bash(rm -r *)"]},
            "env": {"AIPASS_HOME": "/test"},
        }
        settings.write_text(json.dumps(original), encoding="utf-8")
        with patch("aipass.aipass.apps.handlers.provider_reconcile.Path.home", return_value=tmp_path):
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
        from aipass.aipass.apps.modules._doctor_wire import reconcile_stale_deny

        settings = tmp_path / ".claude" / "settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(
            json.dumps({"permissions": {"deny": ["Bash(rm -rf*)", "Bash(git reset --hard*)"]}}),
            encoding="utf-8",
        )
        with patch("aipass.aipass.apps.handlers.provider_reconcile.Path.home", return_value=tmp_path):
            results = reconcile_stale_deny(fix=True)
        assert len(results) == 1
        assert results[0][1] == GLYPH_PASS
        updated = json.loads(settings.read_text(encoding="utf-8"))
        assert updated["permissions"]["deny"] == ["Bash(git reset --hard*)"]

    def test_fix_idempotent(self, tmp_path) -> None:
        """Running fix twice is safe — second run returns PASS with no stale rules."""
        from aipass.aipass.apps.modules._doctor_wire import reconcile_stale_deny

        settings = tmp_path / ".claude" / "settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(
            json.dumps({"permissions": {"deny": ["Bash(rm -rf*)", "Bash(rm -r *)"]}}),
            encoding="utf-8",
        )
        with patch("aipass.aipass.apps.handlers.provider_reconcile.Path.home", return_value=tmp_path):
            reconcile_stale_deny(fix=True)
            results = reconcile_stale_deny(fix=True)
        assert len(results) == 1
        assert results[0][1] == GLYPH_PASS
        assert "no stale" in results[0][2]

    def test_empty_deny_list_returns_pass(self, tmp_path) -> None:
        """Empty deny list returns PASS."""
        from aipass.aipass.apps.modules._doctor_wire import reconcile_stale_deny

        settings = tmp_path / ".claude" / "settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(json.dumps({"permissions": {"deny": []}}), encoding="utf-8")
        with patch("aipass.aipass.apps.handlers.provider_reconcile.Path.home", return_value=tmp_path):
            results = reconcile_stale_deny(fix=False)
        assert len(results) == 1
        assert results[0][1] == GLYPH_PASS

    def test_no_permissions_key_returns_pass(self, tmp_path) -> None:
        """Settings without permissions key returns PASS."""
        from aipass.aipass.apps.modules._doctor_wire import reconcile_stale_deny

        settings = tmp_path / ".claude" / "settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(json.dumps({"env": {"FOO": "bar"}}), encoding="utf-8")
        with patch("aipass.aipass.apps.handlers.provider_reconcile.Path.home", return_value=tmp_path):
            results = reconcile_stale_deny(fix=False)
        assert len(results) == 1
        assert results[0][1] == GLYPH_PASS


class TestCheckWireVerify:
    """Tests for check_wire_verify() — hooks wire_verify guard."""

    def test_pass_on_zero_exit(self) -> None:
        """Exit 0 from drone @hooks verify produces a PASS row."""
        from aipass.aipass.apps.modules._doctor_wire import check_wire_verify

        fake = MagicMock(returncode=0, stdout="✓ Wire check passed\n\n0 errors, 0 warnings\n")
        with patch("aipass.aipass.apps.modules._doctor_wire.subprocess.run", return_value=fake):
            results = check_wire_verify()
        assert len(results) == 1
        assert results[0].label == "wire verify"
        assert results[0].glyph == "[green]✓[/green]"

    def test_fail_on_nonzero_exit(self) -> None:
        """Non-zero exit from drone @hooks verify produces a FAIL row."""
        from aipass.aipass.apps.modules._doctor_wire import check_wire_verify

        fake = MagicMock(returncode=1, stdout="ERROR empty array\n2 errors, 0 warnings\n")
        with patch("aipass.aipass.apps.modules._doctor_wire.subprocess.run", return_value=fake):
            results = check_wire_verify()
        assert len(results) == 1
        assert results[0].glyph == "[red]✗[/red]"
        assert "errors" in results[0].detail

    def test_warn_on_drone_not_found(self) -> None:
        """FileNotFoundError (drone missing) produces a WARN row."""
        from aipass.aipass.apps.modules._doctor_wire import check_wire_verify

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

        from aipass.aipass.apps.modules._doctor_wire import check_wire_verify

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
    def _args() -> dict:
        return {
            "manifest_path": MagicMock(),
            "missing_hooks": ["some_hook"],
            "missing_env": [],
            "missing_deny": [],
            "missing_ask": [],
        }

    def test_non_tty_stdin_skips_prompt_and_declines(self) -> None:
        """Non-tty stdin must NOT call input() — it declines and warns instead."""
        from aipass.aipass.apps.modules import _doctor_wire

        with (
            patch.object(_doctor_wire.sys, "stdin") as mock_stdin,
            patch("builtins.input") as mock_input,
            patch.object(_doctor_wire, "_print_manual_wire_warning") as mock_warn,
        ):
            mock_stdin.isatty.return_value = False
            result = _doctor_wire._prompt_auto_wire(**self._args())

        assert result is False
        mock_input.assert_not_called()
        mock_warn.assert_called_once()

    def test_tty_stdin_prompts_and_respects_decline(self) -> None:
        """Tty stdin still prompts; a 'n' answer declines."""
        from aipass.aipass.apps.modules import _doctor_wire

        with (
            patch.object(_doctor_wire.sys, "stdin") as mock_stdin,
            patch("builtins.input", return_value="n") as mock_input,
            patch.object(_doctor_wire, "_print_manual_wire_warning"),
        ):
            mock_stdin.isatty.return_value = True
            result = _doctor_wire._prompt_auto_wire(**self._args())

        assert result is False
        mock_input.assert_called_once()

    def test_tty_stdin_accepts_and_wires(self) -> None:
        """Tty stdin with a 'y' answer runs the wire and returns True."""
        from aipass.aipass.apps.modules import _doctor_wire

        with (
            patch.object(_doctor_wire.sys, "stdin") as mock_stdin,
            patch("builtins.input", return_value="y"),
            patch.object(_doctor_wire, "_auto_wire_provider", return_value=["wired hook"]) as mock_wire,
        ):
            mock_stdin.isatty.return_value = True
            result = _doctor_wire._prompt_auto_wire(**self._args())

        assert result is True
        mock_wire.assert_called_once()


# ---------------------------------------------------------------------------
# _check_global_aipass_home tests (#688)
# ---------------------------------------------------------------------------


class TestCheckGlobalAipassHome:
    """Tests for _check_global_aipass_home doctor check."""

    def test_nonexistent_path_is_error(self, tmp_path):
        """AIPASS_HOME pointing to a nonexistent path is flagged as error."""
        from aipass.aipass.apps.modules.doctor import _check_global_aipass_home

        settings = tmp_path / ".claude" / "settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(
            json.dumps({"env": {"AIPASS_HOME": str(tmp_path / "gone")}}),
            encoding="utf-8",
        )
        with patch("aipass.aipass.apps.modules.doctor.Path.home", return_value=tmp_path):
            results = _check_global_aipass_home()
        fails = [r for r in results if "does not exist" in r.detail]
        assert len(fails) == 1

    def test_throwaway_path_is_error(self, tmp_path):
        """AIPASS_HOME pointing to a temp path is flagged as error."""
        from aipass.aipass.apps.modules.doctor import _check_global_aipass_home

        settings = tmp_path / ".claude" / "settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(
            json.dumps({"env": {"AIPASS_HOME": str(tmp_path)}}),
            encoding="utf-8",
        )
        with patch("aipass.aipass.apps.modules.doctor.Path.home", return_value=tmp_path):
            results = _check_global_aipass_home()
        fails = [r for r in results if "throwaway" in r.detail]
        assert len(fails) == 1

    def test_valid_path_passes(self, tmp_path):
        """AIPASS_HOME pointing to a real, non-temp path passes."""
        from aipass.aipass.apps.modules.doctor import _check_global_aipass_home, GLYPH_PASS

        real_home = tmp_path / "AIPass"
        real_home.mkdir()
        settings = tmp_path / ".claude" / "settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(
            json.dumps({"env": {"AIPASS_HOME": str(real_home)}}),
            encoding="utf-8",
        )
        with (
            patch("aipass.aipass.apps.modules.doctor.Path.home", return_value=tmp_path),
            patch(
                "aipass.aipass.apps.handlers.init.bootstrap.is_throwaway_path",
                return_value=False,
            ),
        ):
            results = _check_global_aipass_home()
        assert any(r.glyph == GLYPH_PASS for r in results)

    def test_no_settings_file_is_noop(self, tmp_path):
        """Missing ~/.claude/settings.json produces no results."""
        from aipass.aipass.apps.modules.doctor import _check_global_aipass_home

        with patch("aipass.aipass.apps.modules.doctor.Path.home", return_value=tmp_path):
            results = _check_global_aipass_home()
        assert results == []


# ---------------------------------------------------------------------------
# _check_owner_seating / _fix_owner_seating tests (DPLAN-0239 P3+P5)
# ---------------------------------------------------------------------------


class TestCheckOwnerSeating:
    """Tests for owner/identity detection via sync-registry --check."""

    def test_clean_owner_returns_pass(self):
        from aipass.aipass.apps.modules.doctor import _check_owner_seating

        check_json = json.dumps({"clean": True, "owner": "vera", "owner_uid": "8fb38c96-abcd", "issues": []})
        mock_proc = MagicMock(returncode=0, stdout=check_json, stderr="")
        with patch("aipass.aipass.apps.modules.doctor.subprocess.run", return_value=mock_proc):
            results = _check_owner_seating()
        assert len(results) == 1
        assert results[0].glyph == GLYPH_PASS
        assert "@vera" in results[0].detail
        assert "8fb38c96" in results[0].detail

    def test_unseated_owner_returns_errors(self):
        from aipass.aipass.apps.modules.doctor import _check_owner_seating

        check_json = json.dumps(
            {
                "clean": False,
                "owner": None,
                "owner_uid": "",
                "issues": [
                    {"flag": "no_owner", "detail": "No owner:true in registry"},
                    {"flag": "metadata_id_missing", "detail": "metadata.id absent"},
                ],
            }
        )
        mock_proc = MagicMock(returncode=1, stdout=check_json, stderr="")
        with patch("aipass.aipass.apps.modules.doctor.subprocess.run", return_value=mock_proc):
            results = _check_owner_seating()
        assert len(results) == 2
        assert all(r.glyph == GLYPH_FAIL for r in results)
        assert results[0].label == "owner/no_owner"

    def test_issue_with_branch_field(self):
        from aipass.aipass.apps.modules.doctor import _check_owner_seating

        check_json = json.dumps(
            {
                "clean": False,
                "owner": "vera",
                "owner_uid": "8fb38c96",
                "issues": [
                    {"flag": "entry_rid_stale", "detail": "stale rid", "branch": "vera"},
                ],
            }
        )
        mock_proc = MagicMock(returncode=1, stdout=check_json, stderr="")
        with patch("aipass.aipass.apps.modules.doctor.subprocess.run", return_value=mock_proc):
            results = _check_owner_seating()
        assert len(results) == 1
        assert results[0].glyph == GLYPH_FAIL
        assert results[0].label == "owner/entry_rid_stale"

    def test_drone_not_found_returns_warn(self):
        from aipass.aipass.apps.modules.doctor import _check_owner_seating

        with patch(
            "aipass.aipass.apps.modules.doctor.subprocess.run",
            side_effect=FileNotFoundError("drone"),
        ):
            results = _check_owner_seating()
        assert len(results) == 1
        assert results[0].glyph == GLYPH_WARN
        assert "drone" in results[0].detail

    def test_timeout_returns_warn(self):
        import subprocess as _sp

        from aipass.aipass.apps.modules.doctor import _check_owner_seating

        with patch(
            "aipass.aipass.apps.modules.doctor.subprocess.run",
            side_effect=_sp.TimeoutExpired("drone", 30),
        ):
            results = _check_owner_seating()
        assert len(results) == 1
        assert results[0].glyph == GLYPH_WARN

    def test_non_json_output_returns_warn(self):
        from aipass.aipass.apps.modules.doctor import _check_owner_seating

        mock_proc = MagicMock(returncode=1, stdout="not json at all", stderr="")
        with patch("aipass.aipass.apps.modules.doctor.subprocess.run", return_value=mock_proc):
            results = _check_owner_seating()
        assert len(results) == 1
        assert results[0].glyph == GLYPH_WARN

    def test_empty_stdout_exit_zero(self):
        from aipass.aipass.apps.modules.doctor import _check_owner_seating

        mock_proc = MagicMock(returncode=0, stdout="", stderr="")
        with patch("aipass.aipass.apps.modules.doctor.subprocess.run", return_value=mock_proc):
            results = _check_owner_seating()
        assert len(results) == 1
        assert results[0].glyph == GLYPH_PASS


class TestFixOwnerSeating:
    """Tests for owner/identity repair via sync-registry --fix."""

    def test_fix_success_returns_pass(self):
        from aipass.aipass.apps.modules.doctor import _fix_owner_seating

        mock_proc = MagicMock(returncode=0, stdout="", stderr="")
        with patch("aipass.aipass.apps.modules.doctor.subprocess.run", return_value=mock_proc):
            results = _fix_owner_seating()
        assert len(results) == 1
        assert results[0].glyph == GLYPH_PASS
        assert "reconciled" in results[0].detail

    def test_fix_failure_returns_fail(self):
        from aipass.aipass.apps.modules.doctor import _fix_owner_seating

        mock_proc = MagicMock(returncode=1, stdout="", stderr="owner conflict")
        with patch("aipass.aipass.apps.modules.doctor.subprocess.run", return_value=mock_proc):
            results = _fix_owner_seating()
        assert len(results) == 1
        assert results[0].glyph == GLYPH_FAIL

    def test_fix_drone_not_found(self):
        from aipass.aipass.apps.modules.doctor import _fix_owner_seating

        with patch(
            "aipass.aipass.apps.modules.doctor.subprocess.run",
            side_effect=FileNotFoundError("drone"),
        ):
            results = _fix_owner_seating()
        assert len(results) == 1
        assert results[0].glyph == GLYPH_WARN

    def test_fix_timeout(self):
        import subprocess as _sp

        from aipass.aipass.apps.modules.doctor import _fix_owner_seating

        with patch(
            "aipass.aipass.apps.modules.doctor.subprocess.run",
            side_effect=_sp.TimeoutExpired("drone", 60),
        ):
            results = _fix_owner_seating()
        assert len(results) == 1
        assert results[0].glyph == GLYPH_WARN


# =============================================================================
# TestRunDoctorPreflight
# =============================================================================


class TestRunDoctorPreflight:
    """Tests for run_doctor_preflight — doctor-before-hello (round-2 addendum 2)."""

    def test_returns_error_count_and_empty_items_when_hooks_wired(self) -> None:
        from aipass.aipass.apps.modules.doctor import CheckResult, run_doctor_preflight

        groups = {
            "System": [],
            "Identity": [],
            "Services": [CheckResult("hooks", GLYPH_PASS, "9 provider hooks wired", "")],
            "Community": [],
            "Structure": [],
            "Sandbox": [],
        }
        with patch("aipass.aipass.apps.modules.doctor._compute_doctor_groups", return_value=groups):
            error_count, hook_action_items = run_doctor_preflight()
        assert error_count == 0
        assert hook_action_items == []

    def test_still_broken_hooks_surfaced_as_action_items(self) -> None:
        from aipass.aipass.apps.modules.doctor import CheckResult, run_doctor_preflight

        groups = {
            "Services": [
                CheckResult("hooks", GLYPH_WARN, "2 hook(s) missing from provider settings: Stop, Notification", ""),
                CheckResult("wire verify", GLYPH_FAIL, "verify failed", ""),
            ],
        }
        with patch("aipass.aipass.apps.modules.doctor._compute_doctor_groups", return_value=groups):
            _error_count, hook_action_items = run_doctor_preflight()
        assert any("hooks:" in item for item in hook_action_items)
        assert any("wire verify:" in item for item in hook_action_items)

    def test_passing_checks_excluded_from_action_items(self) -> None:
        from aipass.aipass.apps.modules.doctor import CheckResult, run_doctor_preflight

        groups = {"Services": [CheckResult("hooks", GLYPH_PASS, "9 provider hooks wired", "")]}
        with patch("aipass.aipass.apps.modules.doctor._compute_doctor_groups", return_value=groups):
            _error_count, hook_action_items = run_doctor_preflight()
        assert hook_action_items == []

    def test_fix_true_passed_through_to_compute_groups(self) -> None:
        from aipass.aipass.apps.modules.doctor import run_doctor_preflight

        with patch("aipass.aipass.apps.modules.doctor._compute_doctor_groups", return_value={}) as mock_compute:
            run_doctor_preflight(fix=True)
        mock_compute.assert_called_once_with(fix=True)

    def test_error_count_reflects_fail_glyphs(self) -> None:
        from aipass.aipass.apps.modules.doctor import CheckResult, run_doctor_preflight

        groups = {"System": [CheckResult("test", GLYPH_FAIL, "bad", "")]}
        with patch("aipass.aipass.apps.modules.doctor._compute_doctor_groups", return_value=groups):
            error_count, _hook_action_items = run_doctor_preflight()
        assert error_count == 1
