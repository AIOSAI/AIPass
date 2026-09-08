# =================== AIPass ====================
# Name: test_cross_os.py
# Description: Tests for cross-OS gap registry parser + doctor/init integration
# Version: 1.0.0
# Created: 2026-07-02
# Modified: 2026-07-02
# =============================================

"""Tests for the cross-OS gap registry (TDPLAN-0011 slice 1).

Covers: parser happy path, platform filtering (win32/darwin/linux),
fail-to-error (missing/malformed doc), _check_cross_os() row shape, the
doctor --cross-os subcommand, and the init stage-2 heads-up wiring.
"""

import contextlib
import platform
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest  # pyright: ignore[reportMissingImports]

from aipass.aipass.apps.handlers.cross_os import (
    CrossOsGap,
    CrossOsGapError,
    PreflightResult,
    RunRecordError,
    build_run_record,
    check_hookstatus,
    check_routing,
    check_versions,
    default_record_path,
    find_e2e_dir,
    find_gap_doc,
    gaps_for_platform,
    generate_run_record,
    load_gaps,
    os_matches,
    parse_gap_registry,
    run_e2e,
)
from aipass.aipass.apps.handlers.cross_os.preflight import E2E_UNRUNNABLE_PREFIX
from aipass.aipass.apps.handlers.ui.progress import GLYPH_FAIL, GLYPH_PASS, GLYPH_WARN
from aipass.aipass.apps.modules.doctor import (
    _check_cross_os,
    _cross_os_gap_rows,
    run_cross_os,
    run_cross_os_record,
)

_HANDLER_MOD = "aipass.aipass.apps.handlers.cross_os.gap_registry"
_PREFLIGHT_MOD = "aipass.aipass.apps.handlers.cross_os.preflight"
_RECORD_MOD = "aipass.aipass.apps.handlers.cross_os.run_record"
_DOCTOR_MOD = "aipass.aipass.apps.modules.doctor"
_INIT_MOD = "aipass.aipass.apps.modules.init_flow"


def _completed(returncode: int = 0, stdout: str = "", stderr: str = "") -> MagicMock:
    """Build a fake subprocess.CompletedProcess for patching subprocess.run."""
    proc = MagicMock()
    proc.returncode = returncode
    proc.stdout = stdout
    proc.stderr = stderr
    return proc


# A minimal but structurally-faithful copy of the registry section.
SAMPLE_DOC = """# Some doc

## Known cross-OS gap registry (living — update as fixed)

Source of truth: DPLAN-0194.

| # | Gap | OS | Symptom | Owner | Status |
|---|-----|----|---------| ------|--------|
| 1 | cp1252 stdout | Win | UnicodeEncodeError on banner | aipass | fixed |
| 7 | linux-only audio player | Win/mac | hook sound silent | hooks | suspected |
| 9 | route masks errors | all | printed as Unknown command | aipass | recommended |

> a trailing footnote that is not a table row

## Run Record

should not be parsed
"""


@pytest.fixture(autouse=True)
def _stub_handler_json():
    """Suppress json_handler.log_operation side effects in the handler."""
    with patch(f"{_HANDLER_MOD}.json_handler", autospec=True) as mock:
        mock.log_operation = MagicMock()
        yield mock


def _write_doc(root: Path, text: str = SAMPLE_DOC) -> Path:
    """Create root/tests/CROSS_OS_TESTING.md with the given text."""
    doc = root / "tests" / "CROSS_OS_TESTING.md"
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text(text, encoding="utf-8")
    return doc


# =============================================================================
# Parser
# =============================================================================


class TestParseGapRegistry:
    def test_happy_path_row_count_and_fields(self) -> None:
        gaps = parse_gap_registry(SAMPLE_DOC)
        assert len(gaps) == 3
        first = gaps[0]
        assert isinstance(first, CrossOsGap)
        assert first.number == "1"
        assert first.gap == "cp1252 stdout"
        assert first.os == "Win"
        assert first.symptom == "UnicodeEncodeError on banner"
        assert first.owner == "aipass"
        assert first.status == "fixed"

    def test_skips_header_separator_and_footnote(self) -> None:
        """Only digit-led data rows are captured; the Run Record section is excluded."""
        gaps = parse_gap_registry(SAMPLE_DOC)
        numbers = [g.number for g in gaps]
        assert numbers == ["1", "7", "9"]

    def test_missing_section_raises(self) -> None:
        with pytest.raises(CrossOsGapError):
            parse_gap_registry("# No registry here\n\njust prose\n")

    def test_section_without_data_rows_raises(self) -> None:
        text = (
            "## Known cross-OS gap registry\n\n| # | Gap | OS | Symptom | Owner | Status |\n|---|---|---|---|---|---|\n"
        )
        with pytest.raises(CrossOsGapError):
            parse_gap_registry(text)


# =============================================================================
# os_matches — platform mapping
# =============================================================================


class TestOsMatches:
    def test_all_matches_every_platform(self) -> None:
        for plat in ("win32", "darwin", "linux", "freebsd"):
            assert os_matches("all", plat) is True

    def test_win_only(self) -> None:
        assert os_matches("Win", "win32") is True
        assert os_matches("Win", "darwin") is False
        assert os_matches("Win", "linux") is False

    def test_win_mac_matches_both(self) -> None:
        assert os_matches("Win/mac", "win32") is True
        assert os_matches("Win/mac", "darwin") is True
        assert os_matches("Win/mac", "linux") is False

    def test_case_insensitive(self) -> None:
        assert os_matches("WIN", "win32") is True
        assert os_matches("ALL", "linux") is True


# =============================================================================
# find_gap_doc + load/filter (end-to-end via a temp doc)
# =============================================================================


class TestFindAndFilter:
    def test_find_gap_doc_walks_up(self, tmp_path) -> None:
        doc = _write_doc(tmp_path)
        nested = tmp_path / "a" / "b" / "c"
        nested.mkdir(parents=True)
        found = find_gap_doc(nested)
        assert found == doc

    def test_find_gap_doc_uses_live_repo_by_default(self) -> None:
        """With no start arg, walks up from the handler file to the real repo doc."""
        doc = find_gap_doc()
        assert doc.name == "CROSS_OS_TESTING.md"
        assert doc.is_file()

    def test_load_gaps_from_temp_doc(self, tmp_path) -> None:
        _write_doc(tmp_path)
        gaps = load_gaps(start=tmp_path)
        assert [g.number for g in gaps] == ["1", "7", "9"]

    def test_filter_linux_only_all_rows(self, tmp_path) -> None:
        _write_doc(tmp_path)
        gaps = gaps_for_platform("linux", start=tmp_path)
        assert [g.number for g in gaps] == ["9"]

    def test_filter_win32_gets_win_and_all(self, tmp_path) -> None:
        _write_doc(tmp_path)
        gaps = gaps_for_platform("win32", start=tmp_path)
        assert [g.number for g in gaps] == ["1", "7", "9"]

    def test_filter_darwin_gets_mac_and_all(self, tmp_path) -> None:
        _write_doc(tmp_path)
        gaps = gaps_for_platform("darwin", start=tmp_path)
        assert [g.number for g in gaps] == ["7", "9"]

    def test_default_platform_uses_sys_platform(self, tmp_path) -> None:
        _write_doc(tmp_path)
        with patch(f"{_HANDLER_MOD}.sys") as mock_sys:
            mock_sys.platform = "win32"
            gaps = gaps_for_platform(start=tmp_path)
        assert [g.number for g in gaps] == ["1", "7", "9"]


# =============================================================================
# Fail-to-error (never silently empty)
# =============================================================================


class TestFailToError:
    def test_missing_doc_raises(self, tmp_path) -> None:
        with pytest.raises(CrossOsGapError):
            gaps_for_platform("linux", start=tmp_path)

    def test_malformed_doc_raises(self, tmp_path) -> None:
        _write_doc(tmp_path, text="# no registry section at all\n")
        with pytest.raises(CrossOsGapError):
            load_gaps(start=tmp_path)


# =============================================================================
# _cross_os_gap_rows — OS-gap cross-reference row shape (slice 1 logic)
# =============================================================================


class TestCrossOsGapRows:
    def test_gaps_become_warn_preflight_rows(self) -> None:
        fake = [
            CrossOsGap("2", ".venv symlink", "Win", "WinError 1314", "aipass", "untested"),
        ]
        with patch(f"{_DOCTOR_MOD}.gaps_for_platform", return_value=fake):
            results = _cross_os_gap_rows()
        assert len(results) == 1
        row = results[0]
        assert row.glyph == GLYPH_WARN
        assert "gap #2" in row.label
        assert "pre-flight" in row.label
        assert row.detail.startswith("pre-flight:")
        assert "WinError 1314" in row.detail
        assert "aipass" in row.remediation

    def test_no_gaps_emits_single_pass(self) -> None:
        with patch(f"{_DOCTOR_MOD}.gaps_for_platform", return_value=[]):
            results = _cross_os_gap_rows()
        assert len(results) == 1
        assert results[0].glyph == GLYPH_PASS
        assert "no tracked cross-OS gaps" in results[0].detail

    def test_registry_error_emits_warn_not_silent(self) -> None:
        with patch(f"{_DOCTOR_MOD}.gaps_for_platform", side_effect=CrossOsGapError("doc gone")):
            results = _cross_os_gap_rows()
        assert len(results) == 1
        assert results[0].glyph == GLYPH_WARN
        assert "unavailable" in results[0].detail


# =============================================================================
# Pre-flight runners — routing / versions / hookstatus (mocked subprocess)
# =============================================================================


class TestPreflightRunners:
    def test_routing_ok_both_routes_exit_zero(self) -> None:
        with patch(f"{_PREFLIGHT_MOD}.subprocess.run", return_value=_completed(0, "systems ok")):
            result = check_routing()
        assert isinstance(result, PreflightResult)
        assert result.ok is True
        assert "exit 0" in result.detail

    def test_routing_fails_when_route_nonzero(self) -> None:
        # drone systems exits 0, @ai_mail route exits 1.
        with patch(f"{_PREFLIGHT_MOD}.subprocess.run", side_effect=[_completed(0), _completed(1, stderr="boom")]):
            result = check_routing()
        assert result.ok is False
        assert "@ai_mail" in result.detail

    def test_routing_fails_to_error_on_missing_binary(self) -> None:
        with patch(f"{_PREFLIGHT_MOD}.subprocess.run", side_effect=FileNotFoundError("no drone")):
            result = check_routing()
        assert result.ok is False  # never crashes

    def test_versions_ok_captures_strings(self) -> None:
        with patch(
            f"{_PREFLIGHT_MOD}.subprocess.run",
            side_effect=[_completed(0, "drone v1.1.0"), _completed(0, "aipass 0.1.0")],
        ):
            result = check_versions()
        assert result.ok is True
        assert "drone v1.1.0" in result.detail
        assert "aipass 0.1.0" in result.detail

    def test_versions_fail_nonzero(self) -> None:
        with patch(
            f"{_PREFLIGHT_MOD}.subprocess.run",
            side_effect=[_completed(0, "drone v1.1.0"), _completed(1, stderr="nope")],
        ):
            result = check_versions()
        assert result.ok is False

    def test_hookstatus_ok(self) -> None:
        with patch(f"{_PREFLIGHT_MOD}.subprocess.run", return_value=_completed(0, "hook config viewer")):
            result = check_hookstatus()
        assert result.ok is True
        assert "hook config" in result.detail

    def test_hookstatus_fail_to_error_on_timeout(self) -> None:
        import subprocess as _sp

        with patch(f"{_PREFLIGHT_MOD}.subprocess.run", side_effect=_sp.TimeoutExpired(cmd="drone", timeout=1)):
            result = check_hookstatus()
        assert result.ok is False
        assert "timed out" in result.detail


# =============================================================================
# run_e2e — heavy suite runner (mocked subprocess); dir/pytest resolution
# =============================================================================


@pytest.fixture()
def _stub_preflight_json():
    """Suppress json_handler.log_operation side effects in the preflight module."""
    with patch(f"{_PREFLIGHT_MOD}.json_handler", autospec=True) as mock:
        mock.log_operation = MagicMock()
        yield mock


class TestRunE2e:
    def test_find_e2e_dir_locates_live_repo(self) -> None:
        found = find_e2e_dir()
        assert found is not None
        assert found.name == "e2e"
        assert found.is_dir()

    def test_missing_dir_returns_unrunnable_warn(self, _stub_preflight_json) -> None:
        with patch(f"{_PREFLIGHT_MOD}.find_e2e_dir", return_value=None):
            result = run_e2e()
        assert result.ok is False
        assert result.detail.startswith(E2E_UNRUNNABLE_PREFIX)

    def test_passing_suite_ok(self, tmp_path, _stub_preflight_json) -> None:
        e2e_dir = tmp_path / "tests" / "e2e"
        e2e_dir.mkdir(parents=True)
        with (
            patch(f"{_PREFLIGHT_MOD}.find_e2e_dir", return_value=e2e_dir),
            patch(f"{_PREFLIGHT_MOD}.subprocess.run", return_value=_completed(0, "14 passed in 18.15s")),
        ):
            result = run_e2e()
        assert result.ok is True
        assert "14 passed" in result.detail

    def test_failing_suite_not_ok_and_not_unrunnable(self, tmp_path, _stub_preflight_json) -> None:
        e2e_dir = tmp_path / "tests" / "e2e"
        e2e_dir.mkdir(parents=True)
        with (
            patch(f"{_PREFLIGHT_MOD}.find_e2e_dir", return_value=e2e_dir),
            patch(f"{_PREFLIGHT_MOD}.subprocess.run", return_value=_completed(1, "2 failed, 12 passed in 3s")),
        ):
            result = run_e2e()
        assert result.ok is False
        assert not result.detail.startswith(E2E_UNRUNNABLE_PREFIX)
        assert "failed" in result.detail


# =============================================================================
# _check_cross_os — composed group (gap rows + pre-flight rows + optional e2e)
# =============================================================================


class TestCheckCrossOsComposed:
    def _patch_preflight(self, routing=None, versions=None, hookstatus=None):
        """Patch the three light pre-flight runners with given PreflightResults."""
        routing = routing or PreflightResult("routing", True, "ok")
        versions = versions or PreflightResult("versions", True, "drone v1; aipass 0.1")
        hookstatus = hookstatus or PreflightResult("hookstatus", True, "config ok")
        return (
            patch(f"{_DOCTOR_MOD}.gaps_for_platform", return_value=[]),
            patch(f"{_DOCTOR_MOD}.check_routing", return_value=routing),
            patch(f"{_DOCTOR_MOD}.check_versions", return_value=versions),
            patch(f"{_DOCTOR_MOD}.check_hookstatus", return_value=hookstatus),
        )

    def test_preflight_rows_pass_when_ok(self) -> None:
        with contextlib.ExitStack() as stack:
            for p in self._patch_preflight():
                stack.enter_context(p)
            results = _check_cross_os()
        labels = {r.label: r for r in results}
        assert labels["routing (pre-flight)"].glyph == GLYPH_PASS
        assert labels["versions (pre-flight)"].glyph == GLYPH_PASS
        assert labels["hookstatus (pre-flight)"].glyph == GLYPH_PASS
        assert labels["routing (pre-flight)"].detail.startswith("pre-flight:")

    def test_preflight_fail_maps_to_fail_glyph(self) -> None:
        bad = PreflightResult("routing", False, "drone systems -> 1")
        with contextlib.ExitStack() as stack:
            for p in self._patch_preflight(routing=bad):
                stack.enter_context(p)
            results = _check_cross_os()
        row = next(r for r in results if r.label == "routing (pre-flight)")
        assert row.glyph == GLYPH_FAIL
        assert row.remediation  # fail rows carry remediation

    def test_e2e_not_run_by_default(self) -> None:
        with contextlib.ExitStack() as stack:
            for p in self._patch_preflight():
                stack.enter_context(p)
            mock_e2e = stack.enter_context(patch(f"{_DOCTOR_MOD}.run_e2e_preflight"))
            results = _check_cross_os()
        mock_e2e.assert_not_called()
        assert not any("e2e" in r.label for r in results)

    def test_e2e_runs_when_flag_set_and_pass_maps_pass(self) -> None:
        with contextlib.ExitStack() as stack:
            for p in self._patch_preflight():
                stack.enter_context(p)
            mock_e2e = stack.enter_context(
                patch(f"{_DOCTOR_MOD}.run_e2e_preflight", return_value=PreflightResult("e2e", True, "14 passed"))
            )
            results = _check_cross_os(run_e2e=True)
        mock_e2e.assert_called_once()
        row = next(r for r in results if r.label == "e2e suite (pre-flight)")
        assert row.glyph == GLYPH_PASS

    def test_e2e_real_failure_maps_fail(self) -> None:
        with contextlib.ExitStack() as stack:
            for p in self._patch_preflight():
                stack.enter_context(p)
            stack.enter_context(
                patch(
                    f"{_DOCTOR_MOD}.run_e2e_preflight",
                    return_value=PreflightResult("e2e", False, "2 failed, 12 passed"),
                )
            )
            results = _check_cross_os(run_e2e=True)
        row = next(r for r in results if r.label == "e2e suite (pre-flight)")
        assert row.glyph == GLYPH_FAIL

    def test_e2e_unrunnable_maps_warn(self) -> None:
        unrunnable = PreflightResult("e2e", False, f"{E2E_UNRUNNABLE_PREFIX}: e2e dir not found")
        with contextlib.ExitStack() as stack:
            for p in self._patch_preflight():
                stack.enter_context(p)
            stack.enter_context(patch(f"{_DOCTOR_MOD}.run_e2e_preflight", return_value=unrunnable))
            results = _check_cross_os(run_e2e=True)
        row = next(r for r in results if r.label == "e2e suite (pre-flight)")
        assert row.glyph == GLYPH_WARN

    def test_run_cross_os_returns_int_no_errors(self) -> None:
        with contextlib.ExitStack() as stack:
            for p in self._patch_preflight():
                stack.enter_context(p)
            stack.enter_context(patch(f"{_DOCTOR_MOD}.console"))
            rc = run_cross_os()
        assert rc == 0


# =============================================================================
# doctor --cross-os subcommand routing
# =============================================================================


class TestDoctorCrossOsCommand:
    def test_cross_os_flag_routes_to_run_cross_os(self) -> None:
        from aipass.aipass.apps.modules.doctor import handle_command

        with (
            patch(f"{_DOCTOR_MOD}.run_cross_os", return_value=0) as mock_run,
            patch(f"{_DOCTOR_MOD}.json_handler", autospec=True),
        ):
            handled = handle_command("doctor", ["--cross-os"])
        assert handled is True
        mock_run.assert_called_once()

    def test_cross_os_does_not_run_full_doctor(self) -> None:
        """The subcommand must not invoke the default full run."""
        from aipass.aipass.apps.modules.doctor import handle_command

        with (
            patch(f"{_DOCTOR_MOD}.run_cross_os", return_value=0),
            patch(f"{_DOCTOR_MOD}.run_doctor") as mock_full,
            patch(f"{_DOCTOR_MOD}.json_handler", autospec=True),
        ):
            handle_command("doctor", ["--cross-os"])
        mock_full.assert_not_called()

    def test_cross_os_alone_stays_light_no_e2e(self) -> None:
        """`--cross-os` without `--e2e` threads run_e2e=False."""
        from aipass.aipass.apps.modules.doctor import handle_command

        with (
            patch(f"{_DOCTOR_MOD}.run_cross_os", return_value=0) as mock_run,
            patch(f"{_DOCTOR_MOD}.json_handler", autospec=True),
        ):
            handle_command("doctor", ["--cross-os"])
        mock_run.assert_called_once_with(run_e2e=False)

    def test_cross_os_with_e2e_flag_threads_run_e2e_true(self) -> None:
        """Both `--cross-os` and `--e2e` present -> run_cross_os(run_e2e=True)."""
        from aipass.aipass.apps.modules.doctor import handle_command

        with (
            patch(f"{_DOCTOR_MOD}.run_cross_os", return_value=0) as mock_run,
            patch(f"{_DOCTOR_MOD}.json_handler", autospec=True),
        ):
            handle_command("doctor", ["--cross-os", "--e2e"])
        mock_run.assert_called_once_with(run_e2e=True)


# =============================================================================
# init stage-2 heads-up wiring
# =============================================================================


class TestInitStage2HeadsUp:
    def test_heads_up_prints_gaps(self) -> None:
        from aipass.aipass.apps.modules.init_flow import _print_os_gap_heads_up

        fake = [CrossOsGap("9", "route masks", "all", "printed as Unknown command", "aipass", "rec")]
        with (
            patch("aipass.aipass.apps.handlers.cross_os.gaps_for_platform", return_value=fake),
            patch(f"{_INIT_MOD}.console") as mock_console,
        ):
            _print_os_gap_heads_up()
        printed = " ".join(str(c.args[0]) for c in mock_console.print.call_args_list if c.args)
        assert "gap #9" in printed
        assert "Unknown command" in printed

    def test_heads_up_no_gaps_prints_nothing(self) -> None:
        from aipass.aipass.apps.modules.init_flow import _print_os_gap_heads_up

        with (
            patch("aipass.aipass.apps.handlers.cross_os.gaps_for_platform", return_value=[]),
            patch(f"{_INIT_MOD}.console") as mock_console,
        ):
            _print_os_gap_heads_up()
        mock_console.print.assert_not_called()

    def test_heads_up_error_warns_and_does_not_crash(self) -> None:
        from aipass.aipass.apps.modules.init_flow import _print_os_gap_heads_up

        with (
            patch(
                "aipass.aipass.apps.handlers.cross_os.gaps_for_platform",
                side_effect=CrossOsGapError("doc missing"),
            ),
            patch(f"{_INIT_MOD}.console"),
            patch(f"{_INIT_MOD}.warning") as mock_warning,
        ):
            _print_os_gap_heads_up()  # must not raise
        mock_warning.assert_called_once()


# =============================================================================
# Run Record generator (slice 3) — build_run_record
# =============================================================================


def _line_starting(text: str, prefix: str) -> str:
    """Return the first line in ``text`` starting with ``prefix`` (or "")."""
    for line in text.splitlines():
        if line.startswith(prefix):
            return line
    return ""


class TestBuildRunRecord:
    def _patch(self, stack, gaps=None, routing=None, hooks=None):
        """Patch the record's live inputs (gaps + light pre-flight runners)."""
        gaps = gaps if gaps is not None else []
        routing = routing or PreflightResult("routing", True, "drone systems exit 0; @ai_mail route exit 0")
        hooks = hooks or PreflightResult("hookstatus", True, "hook config viewer")
        stack.enter_context(patch(f"{_RECORD_MOD}.gaps_for_platform", return_value=gaps))
        stack.enter_context(patch(f"{_RECORD_MOD}.check_routing", return_value=routing))
        stack.enter_context(patch(f"{_RECORD_MOD}.check_hookstatus", return_value=hooks))

    def test_env_fields_present_and_filled(self) -> None:
        with contextlib.ExitStack() as stack:
            self._patch(stack)
            text = build_run_record(platform_name="linux")
        for label in ("Machine/VM", "OS + version", "Arch", "Python", "Shell / term", "AIPASS_HOME", "Date :"):
            assert label in text
        # A real, machine-knowable fact is actually filled in (not left blank).
        assert platform.python_version() in text
        assert (platform.machine() or "unknown") in text

    def test_header_marks_machine_preflight_draft(self) -> None:
        with contextlib.ExitStack() as stack:
            self._patch(stack)
            text = build_run_record(platform_name="linux")
        assert "pre-flight DRAFT" in text
        assert "human must complete" in text.lower()

    def test_machine_rows_auto_ticked_pass(self) -> None:
        with contextlib.ExitStack() as stack:
            self._patch(stack)
            text = build_run_record(platform_name="linux")
        phase0 = _line_starting(text, "Phase 0")
        phase4 = _line_starting(text, "Phase 4")
        assert "✅" in phase0 and "machine" in phase0
        assert "✅" in phase4
        assert "drone systems exit 0" in phase4

    def test_routing_fail_marks_fail_glyph(self) -> None:
        bad = PreflightResult("routing", False, "drone systems -> 1")
        with contextlib.ExitStack() as stack:
            self._patch(stack, routing=bad)
            text = build_run_record(platform_name="linux")
        phase4 = _line_starting(text, "Phase 4")
        assert "❌" in phase4
        assert "✅" not in phase4

    def test_human_rows_marked_and_never_auto_ticked(self) -> None:
        """Human-only rows must carry the human marker and NEVER the machine ✅."""
        with contextlib.ExitStack() as stack:
            self._patch(stack)
            text = build_run_record(platform_name="linux")
        for prefix in (
            "Phase 1 clean install",
            "Phase 3 aipass init",
            "Phase 5 daemons",
            "Phase 7 interactive",
            "Per-branch matrix",
        ):
            line = _line_starting(text, prefix)
            assert line, f"missing row: {prefix}"
            assert "— human" in line
            assert "✅" not in line
        # Overall verdict stays human, never a machine tick.
        verdict = _line_starting(text, "Overall verdict")
        assert "— human" in verdict
        assert "✅" not in verdict

    def test_commit_and_tester_left_blank_with_hint(self) -> None:
        with contextlib.ExitStack() as stack:
            self._patch(stack)
            text = build_run_record(platform_name="linux")
        commit = _line_starting(text, "Commit")
        # No value filled — just the hint on how a human fills it.
        assert "drone @git log -1" in commit
        tester = _line_starting(text, "Tester")
        # Tester side is blank; the Date side is machine-filled.
        assert tester.split("Date", 1)[0].replace("Tester", "").strip(" :") == ""

    def test_phase6_hookstatus_machine_sound_human(self) -> None:
        with contextlib.ExitStack() as stack:
            self._patch(stack)
            text = build_run_record(platform_name="linux")
        phase6 = _line_starting(text, "Phase 6")
        assert "✅" in phase6  # hookstatus machine-proved
        assert "sound" in phase6 and "— human" in phase6  # audible cue stays human

    def test_e2e_not_run_marked_by_default(self) -> None:
        with contextlib.ExitStack() as stack:
            self._patch(stack)
            mock_e2e = stack.enter_context(patch(f"{_RECORD_MOD}.run_e2e"))
            text = build_run_record(platform_name="linux", run_heavy_e2e=False)
        mock_e2e.assert_not_called()
        phase2 = _line_starting(text, "Phase 2")
        assert "not run" in phase2
        assert "— human" in phase2
        assert "✅" not in phase2

    def test_e2e_recorded_when_flag_set(self) -> None:
        with contextlib.ExitStack() as stack:
            self._patch(stack)
            mock_e2e = stack.enter_context(
                patch(f"{_RECORD_MOD}.run_e2e", return_value=PreflightResult("e2e", True, "14 passed in 18.15s"))
            )
            text = build_run_record(platform_name="linux", run_heavy_e2e=True)
        mock_e2e.assert_called_once()
        phase2 = _line_starting(text, "Phase 2")
        assert "✅" in phase2
        assert "14 passed" in phase2

    def test_e2e_unrunnable_marked_could_not_run(self) -> None:
        unrunnable = PreflightResult("e2e", False, f"{E2E_UNRUNNABLE_PREFIX}: e2e dir not found")
        with contextlib.ExitStack() as stack:
            self._patch(stack)
            stack.enter_context(patch(f"{_RECORD_MOD}.run_e2e", return_value=unrunnable))
            text = build_run_record(platform_name="linux", run_heavy_e2e=True)
        phase2 = _line_starting(text, "Phase 2")
        assert "could not run" in phase2
        assert "✅" not in phase2

    def test_watch_items_list_platform_gaps(self) -> None:
        fake = [CrossOsGap("9", "route masks", "all", "printed as Unknown command", "aipass", "rec")]
        with contextlib.ExitStack() as stack:
            self._patch(stack, gaps=fake)
            text = build_run_record(platform_name="linux")
        assert "Watch items" in text
        assert "gap #9" in text
        assert "Unknown command" in text

    def test_watch_items_none_tracked_note(self) -> None:
        with contextlib.ExitStack() as stack:
            self._patch(stack, gaps=[])
            text = build_run_record(platform_name="linux")
        assert "none tracked for linux" in text

    def test_watch_items_registry_error_degrades_not_crash(self) -> None:
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch(f"{_RECORD_MOD}.gaps_for_platform", side_effect=CrossOsGapError("doc gone")))
            stack.enter_context(
                patch(f"{_RECORD_MOD}.check_routing", return_value=PreflightResult("routing", True, "ok"))
            )
            stack.enter_context(
                patch(f"{_RECORD_MOD}.check_hookstatus", return_value=PreflightResult("hookstatus", True, "ok"))
            )
            text = build_run_record(platform_name="linux")  # must not raise
        assert "registry unavailable" in text


# =============================================================================
# Run Record generator (slice 3) — generate_run_record (file writing)
# =============================================================================


class TestGenerateRunRecord:
    def _patch(self, stack):
        """Patch live inputs + json_handler side effect for the writing path."""
        stack.enter_context(patch(f"{_RECORD_MOD}.gaps_for_platform", return_value=[]))
        stack.enter_context(patch(f"{_RECORD_MOD}.check_routing", return_value=PreflightResult("routing", True, "ok")))
        stack.enter_context(
            patch(f"{_RECORD_MOD}.check_hookstatus", return_value=PreflightResult("hookstatus", True, "ok"))
        )
        stack.enter_context(patch(f"{_RECORD_MOD}.json_handler", autospec=True))

    def test_writes_to_given_path(self, tmp_path) -> None:
        target = tmp_path / "rr.txt"
        with contextlib.ExitStack() as stack:
            self._patch(stack)
            written = generate_run_record(str(target))
        assert written == target
        assert target.is_file()
        assert "AIPass Cross-OS Run Record" in target.read_text(encoding="utf-8")

    def test_creates_missing_parent_dirs(self, tmp_path) -> None:
        target = tmp_path / "nested" / "deep" / "rr.txt"
        with contextlib.ExitStack() as stack:
            self._patch(stack)
            written = generate_run_record(str(target))
        assert written.is_file()

    def test_default_path_in_cwd_when_none(self, tmp_path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        with contextlib.ExitStack() as stack:
            self._patch(stack)
            written = generate_run_record(None)
        assert written.parent == tmp_path
        assert written.name.startswith("aipass-crossos-record-")
        assert written.is_file()

    def test_default_record_path_helper_uses_cwd(self, tmp_path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        path = default_record_path()
        assert path.parent == tmp_path
        assert path.name.startswith("aipass-crossos-record-")

    def test_write_error_raises_run_record_error(self, tmp_path) -> None:
        # Target an existing directory → write_text raises OSError → RunRecordError.
        target = tmp_path / "adir"
        target.mkdir()
        with contextlib.ExitStack() as stack:
            self._patch(stack)
            with pytest.raises(RunRecordError):
                generate_run_record(str(target))


# =============================================================================
# doctor --cross-os --record subcommand routing + thin wrapper
# =============================================================================


class TestDoctorCrossOsRecordCommand:
    def test_record_flag_routes_to_run_cross_os_record(self) -> None:
        from aipass.aipass.apps.modules.doctor import handle_command

        with (
            patch(f"{_DOCTOR_MOD}.run_cross_os_record", return_value=0) as mock_rec,
            patch(f"{_DOCTOR_MOD}.run_cross_os") as mock_plain,
            patch(f"{_DOCTOR_MOD}.json_handler", autospec=True),
        ):
            handled = handle_command("doctor", ["--cross-os", "--record", "record.txt"])
        assert handled is True
        mock_rec.assert_called_once_with("record.txt", run_e2e=False)
        mock_plain.assert_not_called()  # record path does not also run the plain group

    def test_record_default_path_when_no_value(self) -> None:
        from aipass.aipass.apps.modules.doctor import handle_command

        with (
            patch(f"{_DOCTOR_MOD}.run_cross_os_record", return_value=0) as mock_rec,
            patch(f"{_DOCTOR_MOD}.json_handler", autospec=True),
        ):
            handle_command("doctor", ["--cross-os", "--record"])
        mock_rec.assert_called_once_with(None, run_e2e=False)

    def test_record_with_e2e_threads_run_e2e_true(self) -> None:
        from aipass.aipass.apps.modules.doctor import handle_command

        with (
            patch(f"{_DOCTOR_MOD}.run_cross_os_record", return_value=0) as mock_rec,
            patch(f"{_DOCTOR_MOD}.json_handler", autospec=True),
        ):
            handle_command("doctor", ["--cross-os", "--record", "--e2e"])
        # --e2e after --record is a flag, not the path -> path None, e2e threaded True.
        mock_rec.assert_called_once_with(None, run_e2e=True)

    def test_record_write_failure_exits_nonzero(self) -> None:
        from aipass.aipass.apps.modules.doctor import handle_command

        with (
            patch(f"{_DOCTOR_MOD}.run_cross_os_record", return_value=1),
            patch(f"{_DOCTOR_MOD}.json_handler", autospec=True),
        ):
            with pytest.raises(SystemExit):
                handle_command("doctor", ["--cross-os", "--record", "record.txt"])

    def test_run_cross_os_record_returns_zero_on_success(self) -> None:
        with (
            patch(f"{_DOCTOR_MOD}.generate_run_record", return_value=Path("record.txt")),
            patch(f"{_DOCTOR_MOD}.console"),
        ):
            assert run_cross_os_record("record.txt") == 0

    def test_run_cross_os_record_returns_one_on_write_error(self) -> None:
        with (
            patch(f"{_DOCTOR_MOD}.generate_run_record", side_effect=RunRecordError("disk full")),
            patch(f"{_DOCTOR_MOD}.console"),
        ):
            assert run_cross_os_record("record.txt") == 1
