# =================== AIPass ====================
# Name: test_doctor_detection.py
# Description: Tests for doctor's system detection and progress helpers
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-08
# =============================================

"""Tests for apps/handlers/system_detect/system_detector.py and apps/handlers/ui/progress.py."""
# The detection rows and progress display `aipass doctor` draws on, split out
# of test_doctor.py on 2026-10-08 (fleet green, oversize_test_file).

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that every handler module this file imports parses and imports

import os
import sys
from unittest.mock import MagicMock, patch

import pytest  # pyright: ignore[reportMissingImports]

from aipass.aipass.apps.handlers.system_detect import system_detector
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


def _on_path(directory, name: str):
    """Put an executable stub named ``name`` in ``directory`` for shutil.which to find through PATH."""
    stub = directory / (name if os.name != "nt" or name.endswith(".exe") else f"{name}.exe")
    stub.write_text("", encoding="utf-8")
    stub.chmod(0o755)
    return stub


# =============================================================================
# TestDetectPython
# =============================================================================


class TestDetectPython:
    def test_current_python_ok(self) -> None:
        """Running Python is >=3.9 and reports ok=True."""
        result = detect_python()
        assert result["major"] == sys.version_info.major
        assert result["minor"] == sys.version_info.minor
        assert "." in result["version"]
        # Running tests on 3.9+ so ok must be True
        assert result["ok"] is True
        assert result["warning"] is False

    def test_python_38_is_warning(self) -> None:
        """Python 3.8 is marked as warning, not ok."""
        result = detect_python(MagicMock(major=3, minor=8, micro=0))
        assert result["ok"] is False
        assert result["warning"] is True

    def test_python_37_is_fail(self) -> None:
        """Python 3.7 is not ok and not warning."""
        result = detect_python(MagicMock(major=3, minor=7, micro=0))
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
    def test_git_found(self, tmp_path, monkeypatch) -> None:
        """When git is on PATH, found=True and version is non-empty."""
        _on_path(tmp_path, "git")
        monkeypatch.setenv("PATH", str(tmp_path))
        with patch("aipass.aipass.apps.handlers.system_detect.system_detector.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="git version 2.43.0\n", returncode=0)
            result = detect_git()
        assert result["found"] is True
        assert result["version"] == "2.43.0"

    def test_git_not_found(self, tmp_path, monkeypatch) -> None:
        """When git is not on PATH, found=False."""
        monkeypatch.setenv("PATH", str(tmp_path))
        result = detect_git()
        assert result["found"] is False
        assert result["version"] == ""

    def test_git_version_parse_failure(self, tmp_path, monkeypatch) -> None:
        """If git --version fails, found=True but version is raw output."""
        _on_path(tmp_path, "git")
        monkeypatch.setenv("PATH", str(tmp_path))
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

    def test_shell_missing_env_falls_back_to_proc_comm(self, monkeypatch, tmp_path) -> None:
        """Missing SHELL but a resolvable parent /proc comm name is used instead of 'unknown'.

        Mutant: system_detector `return {"name": name, "path": resolved}` -> `"path": name` -> red.
        """
        monkeypatch.delenv("SHELL", raising=False)
        stub = _on_path(tmp_path, "zsh")
        monkeypatch.setenv("PATH", str(tmp_path))
        with patch(
            "aipass.aipass.apps.handlers.system_detect.system_detector._shell_from_parent_proc",
            return_value="zsh",
        ):
            result = detect_shell()
        assert result["name"] == "zsh"
        assert os.path.samefile(result["path"], stub)

    def test_shell_missing_env_proc_comm_not_on_path(self, monkeypatch, tmp_path) -> None:
        """Parent comm name resolves but isn't found via which — bare name still beats 'unknown'."""
        monkeypatch.delenv("SHELL", raising=False)
        monkeypatch.setenv("PATH", str(tmp_path))
        with patch(
            "aipass.aipass.apps.handlers.system_detect.system_detector._shell_from_parent_proc",
            return_value="bash",
        ):
            result = detect_shell()
        assert result["name"] == "bash"
        assert result["path"] == ""


# =============================================================================
# TestShellFromParentProc
# =============================================================================


class TestShellFromParentProc:
    """The /proc fallback, reached the way doctor reaches it: detect_shell() with SHELL unset.

    The platform and parent pid go in through detect_shell's os_name/getppid
    seams (fleet green leg 5), so os is never replaced process-wide — which is
    what once made these tests skip on Windows (pathlib dispatch followed the
    forced os.name).
    """

    @pytest.fixture(autouse=True)
    def _no_shell_env(self, monkeypatch, tmp_path) -> None:
        monkeypatch.delenv("SHELL", raising=False)
        monkeypatch.setenv("PATH", str(tmp_path))

    def test_non_posix_reports_unknown(self) -> None:
        """Mutant: `if os_name != "posix"` -> `if False` -> red (the real /proc answers on Linux)."""
        assert detect_shell(os_name="nt")["name"] == "unknown"

    def test_reads_comm_file(self, monkeypatch, tmp_path) -> None:
        fake_ppid = 424242
        proc_dir = tmp_path / str(fake_ppid)
        proc_dir.mkdir()
        (proc_dir / "comm").write_text("bash\n", encoding="utf-8")

        real_path_cls = system_detector.Path

        def _fake_path(arg, *a, **kw):
            if str(arg) == f"/proc/{fake_ppid}/comm":
                return real_path_cls(proc_dir / "comm")
            return real_path_cls(arg, *a, **kw)

        monkeypatch.setattr(system_detector, "Path", _fake_path)
        assert detect_shell(os_name="posix", getppid=lambda: fake_ppid) == {"name": "bash", "path": ""}

    def test_missing_comm_file_reports_unknown(self, monkeypatch, tmp_path) -> None:
        fake_ppid = 999999

        real_path_cls = system_detector.Path

        def _fake_path(arg, *a, **kw):
            if str(arg) == f"/proc/{fake_ppid}/comm":
                return real_path_cls(tmp_path / "nonexistent" / "comm")
            return real_path_cls(arg, *a, **kw)

        monkeypatch.setattr(system_detector, "Path", _fake_path)
        assert detect_shell(os_name="posix", getppid=lambda: fake_ppid)["name"] == "unknown"

    def test_read_oserror_reports_unknown(self, monkeypatch) -> None:
        class _BoomPath:
            def is_file(self):
                return True

            def read_text(self, encoding="utf-8"):
                raise OSError("permission denied")

        monkeypatch.setattr(system_detector, "Path", lambda *a, **kw: _BoomPath())
        assert detect_shell(os_name="posix", getppid=lambda: 1)["name"] == "unknown"


# =============================================================================
# TestDetectCpu
# =============================================================================


class TestDetectCpu:
    def test_returns_positive_count(self) -> None:
        """CPU count is a positive integer.
        Mutant `count = os.cpu_count() or 0` -> `count = 1` goes red on any multi-core host."""
        result = detect_cpu()
        assert result["count"] == os.cpu_count()
        assert result["count"] >= 1


# =============================================================================
# TestDetectOptionalTools
# =============================================================================


class TestDetectOptionalTools:
    def test_tmux_found(self, tmp_path, monkeypatch) -> None:
        """True when tmux binary is on PATH."""
        _on_path(tmp_path, "tmux")
        monkeypatch.setenv("PATH", str(tmp_path))
        assert detect_tmux() is True

    def test_tmux_not_found(self, tmp_path, monkeypatch) -> None:
        """False when tmux is absent from PATH."""
        monkeypatch.setenv("PATH", str(tmp_path))
        assert detect_tmux() is False

    def test_docker_found(self, tmp_path, monkeypatch) -> None:
        """True when docker binary is on PATH."""
        _on_path(tmp_path, "docker")
        monkeypatch.setenv("PATH", str(tmp_path))
        assert detect_docker() is True

    def test_wt_not_on_linux(self, tmp_path, monkeypatch) -> None:
        """False when wt.exe (Windows Terminal) is absent from PATH."""
        monkeypatch.setenv("PATH", str(tmp_path))
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
        """The bar is a spinner plus the task description, and it is transient.

        Value pins added 2026-09-08 (v5 assertion_shape): isinstance alone was
        true of any Progress at all, including one with no spinner and one that
        never clears itself off the terminal.
        """
        from rich.progress import Progress, SpinnerColumn, TextColumn

        prog = make_doctor_progress()
        assert isinstance(prog, Progress)
        assert [type(c) for c in prog.columns] == [SpinnerColumn, TextColumn]
        assert prog.live.transient is True

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
