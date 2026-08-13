"""Tests for audit_display and branch_audit — targeting uncovered lines."""

# =================== META ====================
# Name: test_coverage_audit.py
# Description: Unit tests for audit_display.py and branch_audit.py line coverage
# Version: 1.0.0
# Created: 2026-04-26
# Modified: 2026-04-26
# =============================================

# seedgo:bypass standard=architecture reason="test files live in tests/, not apps/"
# seedgo:bypass standard=encapsulation reason="tests import handlers directly for unit testing"

import types

import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _mock_infrastructure(monkeypatch):
    """Mock heavy infrastructure imports for audit_display and branch_audit."""
    import sys

    mock_logger = MagicMock()
    mock_console = MagicMock()
    mock_json_handler = MagicMock()
    mock_json_handler.log_operation = MagicMock(return_value=True)
    from aipass.seedgo.apps.handlers.bypass.ignore_handler import (
        is_seedgo_ignored as real_is_seedgo_ignored,
        load_ignore_entries as real_load_ignore_entries,
    )

    mock_ignore_handler = MagicMock()
    mock_ignore_handler.get_audit_ignore_patterns = MagicMock(return_value=[])
    mock_ignore_handler.is_seedgo_ignored = real_is_seedgo_ignored
    mock_ignore_handler.load_ignore_entries = real_load_ignore_entries
    mock_scan_branch = MagicMock(return_value=None)

    # -- prax ---------------------------------------------------------------
    prax_mod = MagicMock()
    prax_mod.logger = mock_logger
    monkeypatch.setitem(sys.modules, "aipass.prax", prax_mod)

    # -- cli ----------------------------------------------------------------
    cli_mod = MagicMock()
    cli_mod.console = mock_console
    monkeypatch.setitem(sys.modules, "aipass.cli", cli_mod)

    # -- seedgo json handler ------------------------------------------------
    json_pkg = MagicMock()
    json_pkg.json_handler = mock_json_handler
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.json", json_pkg)
    json_mod = MagicMock()
    json_mod.log_operation = mock_json_handler.log_operation
    monkeypatch.setitem(
        sys.modules,
        "aipass.seedgo.apps.handlers.json.json_handler",
        json_mod,
    )

    # -- bypass handler -----------------------------------------------------
    bypass_pkg = MagicMock()
    bypass_pkg.ignore_handler = mock_ignore_handler
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.bypass", bypass_pkg)
    monkeypatch.setitem(
        sys.modules,
        "aipass.seedgo.apps.handlers.bypass.ignore_handler",
        mock_ignore_handler,
    )

    # -- test_map function_scanner ------------------------------------------
    test_map_pkg = MagicMock()
    test_map_pkg.scan_branch = mock_scan_branch
    monkeypatch.setitem(
        sys.modules,
        "aipass.seedgo.apps.handlers.test_map",
        test_map_pkg,
    )
    scanner_mod = MagicMock()
    scanner_mod.scan_branch = mock_scan_branch
    monkeypatch.setitem(
        sys.modules,
        "aipass.seedgo.apps.handlers.test_map.function_scanner",
        scanner_mod,
    )

    # -- audit package (must be a real module with __path__ pointing to the
    #    actual directory so submodule imports like audit.audit_display work)
    audit_pkg = types.ModuleType("aipass.seedgo.apps.handlers.audit")
    audit_pkg.__path__ = [  # type: ignore[attr-defined]
        str(Path(__file__).resolve().parents[1] / "apps" / "handlers" / "audit")
    ]
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.audit", audit_pkg)

    # Force re-imports so modules pick up fresh mocks
    for mod_name in [
        "aipass.seedgo.apps.handlers.audit.audit_display",
        "aipass.seedgo.apps.handlers.audit.branch_audit",
    ]:
        monkeypatch.delitem(sys.modules, mod_name, raising=False)


# ===========================================================================
# AUDIT_DISPLAY TESTS
# ===========================================================================


class TestFormatStandardName:
    """Tests for _format_standard_name."""

    def test_underscore_conversion(self):
        """DEEP_NESTING becomes Deep Nesting."""
        from aipass.seedgo.apps.handlers.audit.audit_display import (
            _format_standard_name,
        )

        assert _format_standard_name("DEEP_NESTING") == "Deep Nesting"

    def test_lowercase_conversion(self):
        """Lowercase deep_nesting becomes Deep Nesting."""
        from aipass.seedgo.apps.handlers.audit.audit_display import (
            _format_standard_name,
        )

        assert _format_standard_name("deep_nesting") == "Deep Nesting"

    def test_single_word(self):
        """Single word gets title-cased."""
        from aipass.seedgo.apps.handlers.audit.audit_display import (
            _format_standard_name,
        )

        assert _format_standard_name("architecture") == "Architecture"


class TestRenderViolations:
    """Tests for _render_violations."""

    def test_basic_violations(self):
        """Basic violations with path, score, and issues rendered."""
        from aipass.seedgo.apps.handlers.audit.audit_display import (
            _render_violations,
        )

        mock_con = MagicMock()
        violations = [
            {
                "path": "/foo/bar.py",
                "score": 60,
                "issues": ["Bad indent", "Long line"],
            },
        ]
        _render_violations("naming", violations, mock_con)
        # header + file line + 2 issue lines = at least 4
        assert mock_con.print.call_count >= 4

    def test_file_key_fallback(self):
        """Falls back to file key when path is missing."""
        from aipass.seedgo.apps.handlers.audit.audit_display import (
            _render_violations,
        )

        mock_con = MagicMock()
        violations = [
            {
                "file": "bar.py",
                "score": 50,
                "issues": ["Something wrong"],
            },
        ]
        _render_violations("naming", violations, mock_con)
        calls = [str(c) for c in mock_con.print.call_args_list]
        assert any("bar.py" in c for c in calls)

    def test_message_fallback_when_no_issues(self):
        """Shows message when issues list is empty."""
        from aipass.seedgo.apps.handlers.audit.audit_display import (
            _render_violations,
        )

        mock_con = MagicMock()
        violations = [
            {
                "path": "/foo.py",
                "score": 0,
                "issues": [],
                "message": "General failure",
            },
        ]
        _render_violations("naming", violations, mock_con)
        calls = [str(c) for c in mock_con.print.call_args_list]
        assert any("General failure" in c for c in calls)

    def test_more_than_five_violations(self):
        """Shows and N more when violations exceed 5."""
        from aipass.seedgo.apps.handlers.audit.audit_display import (
            _render_violations,
        )

        mock_con = MagicMock()
        violations = [{"path": f"/file{i}.py", "score": 10, "issues": []} for i in range(8)]
        _render_violations("naming", violations, mock_con)
        calls = [str(c) for c in mock_con.print.call_args_list]
        assert any("3 more" in c for c in calls)

    def test_exactly_five_violations_no_more(self):
        """No more message when exactly 5 violations."""
        from aipass.seedgo.apps.handlers.audit.audit_display import (
            _render_violations,
        )

        mock_con = MagicMock()
        violations = [{"path": f"/file{i}.py", "score": 10, "issues": []} for i in range(5)]
        _render_violations("naming", violations, mock_con)
        calls = [str(c) for c in mock_con.print.call_args_list]
        assert not any("more" in c for c in calls)

    def test_no_path_no_file_key(self):
        """Both path and file missing returns empty string for path."""
        from aipass.seedgo.apps.handlers.audit.audit_display import (
            _render_violations,
        )

        mock_con = MagicMock()
        violations = [{"score": 0, "issues": ["err"]}]
        _render_violations("naming", violations, mock_con)
        assert mock_con.print.called


class TestRenderArchitectureViolations:
    """Tests for _render_architecture_violations."""

    def test_no_failed_checks(self):
        """Returns early when all checks pass."""
        from aipass.seedgo.apps.handlers.audit.audit_display import (
            _render_architecture_violations,
        )

        mock_con = MagicMock()
        audit_result = {"results": {"architecture": {"checks": [{"passed": True, "name": "Dir: apps"}]}}}
        _render_architecture_violations(audit_result, mock_con)
        assert mock_con.print.call_count == 0

    def test_missing_directories(self):
        """Shows missing directories grouped."""
        from aipass.seedgo.apps.handlers.audit.audit_display import (
            _render_architecture_violations,
        )

        mock_con = MagicMock()
        checks = [
            {"passed": False, "name": "Dir: apps", "message": "x"},
            {
                "passed": False,
                "name": "Directory: tests",
                "message": "x",
            },
        ]
        audit_result = {"results": {"architecture": {"checks": checks}}}
        _render_architecture_violations(audit_result, mock_con)
        calls = [str(c) for c in mock_con.print.call_args_list]
        assert any("ARCHITECTURE VIOLATIONS" in c for c in calls)
        assert any("Missing directories" in c for c in calls)

    def test_missing_files(self):
        """Shows missing files grouped."""
        from aipass.seedgo.apps.handlers.audit.audit_display import (
            _render_architecture_violations,
        )

        mock_con = MagicMock()
        checks = [
            {
                "passed": False,
                "name": "File: README.md",
                "message": "x",
            },
        ]
        audit_result = {"results": {"architecture": {"checks": checks}}}
        _render_architecture_violations(audit_result, mock_con)
        calls = [str(c) for c in mock_con.print.call_args_list]
        assert any("Missing files" in c for c in calls)

    def test_other_failures(self):
        """Shows non-dir, non-file failures."""
        from aipass.seedgo.apps.handlers.audit.audit_display import (
            _render_architecture_violations,
        )

        mock_con = MagicMock()
        checks = [
            {
                "passed": False,
                "name": "Custom check",
                "message": "Something wrong",
            },
        ]
        audit_result = {"results": {"architecture": {"checks": checks}}}
        _render_architecture_violations(audit_result, mock_con)
        calls = [str(c) for c in mock_con.print.call_args_list]
        assert any("Something wrong" in c for c in calls)

    def test_more_than_five_dirs(self):
        """Directories list truncated at 5 with more message."""
        from aipass.seedgo.apps.handlers.audit.audit_display import (
            _render_architecture_violations,
        )

        mock_con = MagicMock()
        checks = [{"passed": False, "name": f"Dir: dir{i}"} for i in range(7)]
        audit_result = {"results": {"architecture": {"checks": checks}}}
        _render_architecture_violations(audit_result, mock_con)
        calls = [str(c) for c in mock_con.print.call_args_list]
        assert any("2 more" in c for c in calls)

    def test_more_than_five_files(self):
        """Files list truncated at 5 with more message."""
        from aipass.seedgo.apps.handlers.audit.audit_display import (
            _render_architecture_violations,
        )

        mock_con = MagicMock()
        checks = [{"passed": False, "name": f"File: file{i}.py"} for i in range(8)]
        audit_result = {"results": {"architecture": {"checks": checks}}}
        _render_architecture_violations(audit_result, mock_con)
        calls = [str(c) for c in mock_con.print.call_args_list]
        assert any("3 more" in c for c in calls)

    def test_empty_results(self):
        """Empty results dict handled gracefully."""
        from aipass.seedgo.apps.handlers.audit.audit_display import (
            _render_architecture_violations,
        )

        mock_con = MagicMock()
        _render_architecture_violations({}, mock_con)
        assert mock_con.print.call_count == 0

    def test_mixed_dirs_files_other(self):
        """Mix of dirs, files, and other failures all render."""
        from aipass.seedgo.apps.handlers.audit.audit_display import (
            _render_architecture_violations,
        )

        mock_con = MagicMock()
        checks = [
            {"passed": False, "name": "Dir: apps"},
            {"passed": False, "name": "File: setup.py"},
            {
                "passed": False,
                "name": "Config check",
                "message": "Missing config",
            },
        ]
        audit_result = {"results": {"architecture": {"checks": checks}}}
        _render_architecture_violations(audit_result, mock_con)
        calls = [str(c) for c in mock_con.print.call_args_list]
        assert any("Missing directories" in c for c in calls)
        assert any("Missing files" in c for c in calls)
        assert any("Missing config" in c for c in calls)


class TestRenderTypeErrors:
    """Tests for _render_type_errors."""

    def test_no_type_errors_no_files_checked(self):
        """No type errors and no files checked produces no output."""
        from aipass.seedgo.apps.handlers.audit.audit_display import (
            _render_type_errors,
        )

        mock_con = MagicMock()
        _render_type_errors({"type_errors": 0, "files_checked": 0}, mock_con)
        assert mock_con.print.call_count == 0

    def test_no_type_errors_with_files_checked(self):
        """No type errors but files checked shows green check."""
        from aipass.seedgo.apps.handlers.audit.audit_display import (
            _render_type_errors,
        )

        mock_con = MagicMock()
        _render_type_errors({"type_errors": 0, "files_checked": 5}, mock_con)
        calls = [str(c) for c in mock_con.print.call_args_list]
        assert any("No type errors" in c for c in calls)

    def test_type_errors_with_diagnostics(self):
        """Type errors render file details and diagnostics."""
        from aipass.seedgo.apps.handlers.audit.audit_display import (
            _render_type_errors,
        )

        mock_con = MagicMock()
        audit_result = {
            "type_errors": 3,
            "type_error_files": [
                {
                    "file": "module.py",
                    "errors": 2,
                    "diagnostics": [
                        {"line": 10, "message": "Type mismatch"},
                        {"line": 20, "message": "Incompatible"},
                    ],
                },
                {
                    "file": "other.py",
                    "errors": 1,
                    "diagnostics": [
                        {"line": 5, "message": "Missing arg"},
                    ],
                },
            ],
            "files_checked": 10,
        }
        _render_type_errors(audit_result, mock_con)
        calls = [str(c) for c in mock_con.print.call_args_list]
        assert any("TYPE ERRORS" in c for c in calls)
        assert any("module.py" in c for c in calls)

    def test_type_error_file_cap_announces_itself(self):
        """A cap that does not announce itself reads as a clean result (@prax, 83190864)."""
        from aipass.seedgo.apps.handlers.audit.audit_display import (
            _render_type_errors,
        )

        mock_con = MagicMock()
        audit_result = {
            "type_errors": 14,
            "type_error_files": [{"file": f"m{n}.py", "errors": 1, "diagnostics": []} for n in range(14)],
            "files_checked": 20,
        }
        _render_type_errors(audit_result, mock_con)
        calls = [str(c) for c in mock_con.print.call_args_list]

        assert any("... and 4 more files" in c for c in calls)

    def test_type_error_diagnostic_cap_announces_itself(self):
        """Per-file diagnostics are capped at 3 — the remainder must be declared."""
        from aipass.seedgo.apps.handlers.audit.audit_display import (
            _render_type_errors,
        )

        mock_con = MagicMock()
        audit_result = {
            "type_errors": 5,
            "type_error_files": [
                {
                    "file": "m.py",
                    "errors": 5,
                    "diagnostics": [{"line": n, "message": f"err {n}"} for n in range(5)],
                }
            ],
            "files_checked": 1,
        }
        _render_type_errors(audit_result, mock_con)
        calls = [str(c) for c in mock_con.print.call_args_list]

        assert any("... and 2 more in this file" in c for c in calls)

    def test_type_error_message_clip_is_marked(self):
        """A clipped message must show it was clipped, not read as the whole error."""
        from aipass.seedgo.apps.handlers.audit.audit_display import (
            _render_type_errors,
        )

        mock_con = MagicMock()
        audit_result = {
            "type_errors": 1,
            "type_error_files": [{"file": "m.py", "errors": 1, "diagnostics": [{"line": 1, "message": "x" * 90}]}],
            "files_checked": 1,
        }
        _render_type_errors(audit_result, mock_con)
        calls = [str(c) for c in mock_con.print.call_args_list]

        assert any("…" in c for c in calls)

    def test_short_type_error_lists_declare_no_cap(self):
        """Negative direction: a genuinely short list must not claim a remainder."""
        from aipass.seedgo.apps.handlers.audit.audit_display import (
            _render_type_errors,
        )

        mock_con = MagicMock()
        audit_result = {
            "type_errors": 1,
            "type_error_files": [{"file": "m.py", "errors": 1, "diagnostics": [{"line": 1, "message": "short"}]}],
            "files_checked": 1,
        }
        _render_type_errors(audit_result, mock_con)
        calls = [str(c) for c in mock_con.print.call_args_list]

        assert not any("more" in c for c in calls)
        assert not any("…" in c for c in calls)

    def test_file_zero_errors_skipped(self):
        """File with 0 errors in type_error_files is skipped."""
        from aipass.seedgo.apps.handlers.audit.audit_display import (
            _render_type_errors,
        )

        mock_con = MagicMock()
        audit_result = {
            "type_errors": 1,
            "type_error_files": [
                {
                    "file": "clean.py",
                    "errors": 0,
                    "diagnostics": [],
                },
                {
                    "file": "bad.py",
                    "errors": 1,
                    "diagnostics": [
                        {"line": 1, "message": "err"},
                    ],
                },
            ],
            "files_checked": 2,
        }
        _render_type_errors(audit_result, mock_con)
        calls = [str(c) for c in mock_con.print.call_args_list]
        assert not any("clean.py" in c for c in calls)
        assert any("bad.py" in c for c in calls)

    def test_empty_audit_result(self):
        """Missing keys handled gracefully."""
        from aipass.seedgo.apps.handlers.audit.audit_display import (
            _render_type_errors,
        )

        mock_con = MagicMock()
        _render_type_errors({}, mock_con)
        assert mock_con.print.call_count == 0


class TestRenderTestMap:
    """Tests for _render_test_map."""

    def test_no_test_map(self):
        """No test_map key produces no output."""
        from aipass.seedgo.apps.handlers.audit.audit_display import (
            _render_test_map,
        )

        mock_con = MagicMock()
        _render_test_map({}, mock_con)
        assert mock_con.print.call_count == 0

    def test_test_map_zero_functions(self):
        """test_map with 0 total functions produces no output."""
        from aipass.seedgo.apps.handlers.audit.audit_display import (
            _render_test_map,
        )

        mock_con = MagicMock()
        _render_test_map({"test_map": {"total_functions": 0}}, mock_con)
        assert mock_con.print.call_count == 0

    def test_test_map_with_data(self):
        """test_map with data renders summary."""
        from aipass.seedgo.apps.handlers.audit.audit_display import (
            _render_test_map,
        )

        mock_con = MagicMock()
        _render_test_map(
            {
                "test_map": {
                    "total_functions": 10,
                    "tested_functions": 6,
                    "branch": "seedgo",
                }
            },
            mock_con,
        )
        calls = [str(c) for c in mock_con.print.call_args_list]
        assert any("10 public functions" in c for c in calls)
        assert any("6 tested" in c for c in calls)

    def test_test_map_none(self):
        """test_map explicitly None produces no output."""
        from aipass.seedgo.apps.handlers.audit.audit_display import (
            _render_test_map,
        )

        mock_con = MagicMock()
        _render_test_map({"test_map": None}, mock_con)
        assert mock_con.print.call_count == 0


class TestRenderInfoLines:
    """Tests for _render_info_lines (non-scored signposts)."""

    def test_no_info_lines(self):
        """Missing info_lines key produces no output."""
        from aipass.seedgo.apps.handlers.audit.audit_display import _render_info_lines

        mock_con = MagicMock()
        _render_info_lines({}, mock_con)
        assert mock_con.print.call_count == 0

    def test_empty_message_skipped(self):
        """An entry with an empty message prints nothing."""
        from aipass.seedgo.apps.handlers.audit.audit_display import _render_info_lines

        mock_con = MagicMock()
        _render_info_lines({"info_lines": [{"standard": "json_structure", "message": ""}]}, mock_con)
        assert mock_con.print.call_count == 0

    def test_info_lines_rendered(self):
        """Each info line renders once, dimmed."""
        from aipass.seedgo.apps.handlers.audit.audit_display import _render_info_lines

        mock_con = MagicMock()
        _render_info_lines(
            {
                "info_lines": [
                    {"standard": "json_structure", "message": "custom_config: cadence_config.json"},
                    {"standard": "json_structure", "message": "second line"},
                ]
            },
            mock_con,
        )
        calls = [str(c) for c in mock_con.print.call_args_list]
        assert len(calls) == 2
        assert any("cadence_config.json" in c for c in calls)
        assert all("[dim]" in c for c in calls)

    def test_rendered_at_full_score(self):
        """A 100% branch still shows its info lines (context, not failure)."""
        from aipass.seedgo.apps.handlers.audit import audit_display

        mock_con = MagicMock()
        audit_result = {
            "branch": {"name": "mybranch"},
            "scores": {"naming": 100},
            "average": 100,
            "files_checked": 3,
            "info_lines": [{"standard": "json_structure", "message": "operator file: memory.config.json"}],
        }
        with patch.object(audit_display, "console", mock_con):
            audit_display.print_branch_summary(audit_result)
        calls = [str(c) for c in mock_con.print.call_args_list]
        assert any("memory.config.json" in c for c in calls)


class TestRenderDeprecatedPatterns:
    """Tests for _render_deprecated_patterns."""

    def test_no_patterns(self):
        """Empty deprecated_patterns produces no output."""
        from aipass.seedgo.apps.handlers.audit.audit_display import (
            _render_deprecated_patterns,
        )

        mock_con = MagicMock()
        _render_deprecated_patterns({"deprecated_patterns": []}, mock_con)
        assert mock_con.print.call_count == 0

    def test_with_patterns(self):
        """Deprecated patterns render correctly."""
        from aipass.seedgo.apps.handlers.audit.audit_display import (
            _render_deprecated_patterns,
        )

        mock_con = MagicMock()
        patterns = [
            {
                "path": "/foo/DOCUMENTS",
                "message": "Rename DOCUMENTS/ to docs/",
            },
        ]
        _render_deprecated_patterns({"deprecated_patterns": patterns}, mock_con)
        calls = [str(c) for c in mock_con.print.call_args_list]
        assert any("DEPRECATED PATTERNS" in c for c in calls)
        assert any("DOCUMENTS" in c for c in calls)

    def test_missing_key(self):
        """Missing deprecated_patterns key produces no output."""
        from aipass.seedgo.apps.handlers.audit.audit_display import (
            _render_deprecated_patterns,
        )

        mock_con = MagicMock()
        _render_deprecated_patterns({}, mock_con)
        assert mock_con.print.call_count == 0


class TestPrintIntrospection:
    """Tests for print_introspection."""

    def test_introspection_produces_output(self):
        """print_introspection produces console output."""
        import sys

        from aipass.seedgo.apps.handlers.audit.audit_display import (
            print_introspection,
        )

        mock_cli = sys.modules["aipass.cli"]
        mock_cli.console.reset_mock()
        print_introspection()
        assert mock_cli.console.print.called


class TestPrintBranchSummary:
    """Tests for print_branch_summary."""

    @staticmethod
    def _make_audit_result(
        branch_name: str = "test_branch",
        scores: dict | None = None,
        average: int = 85,
        files_checked: int = 10,
        results: dict | None = None,
        extra: dict | None = None,
    ) -> dict:
        """Build a minimal audit_result dict."""
        out: dict = {
            "branch": {
                "name": branch_name,
                "path": "/fake/path",
            },
            "scores": scores if scores is not None else {"architecture": 90, "naming": 80},
            "average": average,
            "files_checked": files_checked,
            "results": results if results is not None else {},
        }
        if extra:
            out.update(extra)
        return out

    def test_basic_summary(self):
        """Basic summary renders without error."""
        from aipass.seedgo.apps.handlers.audit.audit_display import (
            print_branch_summary,
        )

        result = self._make_audit_result()
        print_branch_summary(result)

    def test_high_scores(self):
        """Scores >= 90 get check icon."""
        from aipass.seedgo.apps.handlers.audit.audit_display import (
            print_branch_summary,
        )

        result = self._make_audit_result(scores={"architecture": 95, "naming": 92}, average=93)
        print_branch_summary(result)

    def test_medium_scores(self):
        """Scores 75-89 get warning icon."""
        from aipass.seedgo.apps.handlers.audit.audit_display import (
            print_branch_summary,
        )

        result = self._make_audit_result(scores={"architecture": 80, "naming": 76}, average=78)
        print_branch_summary(result)

    def test_low_scores(self):
        """Scores < 75 get error icon."""
        from aipass.seedgo.apps.handlers.audit.audit_display import (
            print_branch_summary,
        )

        result = self._make_audit_result(scores={"architecture": 50, "naming": 60}, average=55)
        print_branch_summary(result)

    def test_odd_number_of_scores(self):
        """Odd number of scores renders last one alone."""
        from aipass.seedgo.apps.handlers.audit.audit_display import (
            print_branch_summary,
        )

        result = self._make_audit_result(
            scores={
                "architecture": 90,
                "naming": 80,
                "meta": 70,
            },
            average=80,
        )
        print_branch_summary(result)

    def test_empty_scores(self):
        """Empty scores dict still renders overall."""
        from aipass.seedgo.apps.handlers.audit.audit_display import (
            print_branch_summary,
        )

        result = self._make_audit_result(scores={}, average=0)
        print_branch_summary(result)

    def test_architecture_violations_displayed(self):
        """Architecture score < 100 triggers arch violation render."""
        from aipass.seedgo.apps.handlers.audit.audit_display import (
            print_branch_summary,
        )

        result = self._make_audit_result(
            scores={"architecture": 70},
            average=70,
            results={
                "architecture": {
                    "checks": [
                        {
                            "passed": False,
                            "name": "Dir: apps",
                        }
                    ]
                }
            },
        )
        print_branch_summary(result)

    def test_standard_violations_displayed(self):
        """Standard with violations list gets rendered."""
        from aipass.seedgo.apps.handlers.audit.audit_display import (
            print_branch_summary,
        )

        result = self._make_audit_result(
            scores={"naming": 60},
            average=60,
            extra={
                "naming_violations": [
                    {
                        "path": "/foo.py",
                        "score": 60,
                        "issues": ["Bad name"],
                    },
                ],
            },
        )
        print_branch_summary(result)

    def test_branch_level_failed_checks(self):
        """Failed checks but no violations list renders messages."""
        from aipass.seedgo.apps.handlers.audit.audit_display import (
            print_branch_summary,
        )

        result = self._make_audit_result(
            scores={"dead_code": 70},
            average=70,
            results={
                "dead_code": {
                    "checks": [
                        {
                            "passed": False,
                            "message": "Unused function foo()",
                        },
                        {"passed": True, "message": "OK"},
                    ]
                }
            },
        )
        print_branch_summary(result)

    def test_violations_not_in_scores_rendered(self):
        """Violation lists not in scores are caught defensively."""
        from aipass.seedgo.apps.handlers.audit.audit_display import (
            print_branch_summary,
        )

        result = self._make_audit_result(
            scores={"naming": 100},
            average=100,
        )
        result["extra_violations"] = [
            {
                "path": "/orphan.py",
                "score": 0,
                "issues": ["Orphan violation"],
            },
        ]
        print_branch_summary(result)

    def test_type_errors_rendered(self):
        """Type errors section is rendered."""
        from aipass.seedgo.apps.handlers.audit.audit_display import (
            print_branch_summary,
        )

        result = self._make_audit_result(
            extra={
                "type_errors": 2,
                "type_error_files": [
                    {
                        "file": "bad.py",
                        "errors": 2,
                        "diagnostics": [
                            {"line": 1, "message": "err"},
                        ],
                    },
                ],
            },
        )
        print_branch_summary(result)

    def test_test_map_rendered(self):
        """Test map section is rendered."""
        from aipass.seedgo.apps.handlers.audit.audit_display import (
            print_branch_summary,
        )

        result = self._make_audit_result(
            extra={
                "test_map": {
                    "total_functions": 5,
                    "tested_functions": 3,
                    "branch": "seedgo",
                },
            },
        )
        print_branch_summary(result)

    def test_deprecated_patterns_rendered(self):
        """Deprecated patterns section is rendered."""
        from aipass.seedgo.apps.handlers.audit.audit_display import (
            print_branch_summary,
        )

        result = self._make_audit_result(
            extra={
                "deprecated_patterns": [
                    {
                        "path": "/DOCUMENTS",
                        "message": "Rename to docs/",
                    },
                ],
            },
        )
        print_branch_summary(result)

    def test_system_averages_and_overall(self):
        """system_averages and overall_system_avg args accepted."""
        from aipass.seedgo.apps.handlers.audit.audit_display import (
            print_branch_summary,
        )

        result = self._make_audit_result()
        print_branch_summary(
            result,
            system_averages={"naming": 85},
            overall_system_avg=87,
        )

    def test_score_100_skipped_in_violations(self):
        """Score 100 skips violation rendering for that standard."""
        from aipass.seedgo.apps.handlers.audit.audit_display import (
            print_branch_summary,
        )

        result = self._make_audit_result(
            scores={"naming": 100, "meta": 90},
            average=95,
        )
        print_branch_summary(result)


class TestPrintSystemSummary:
    """Tests for print_system_summary."""

    @staticmethod
    def _make_result(
        name: str,
        avg: int,
        scores: dict | None = None,
        type_errors: int = 0,
    ) -> dict:
        """Build a minimal system summary result dict."""
        return {
            "branch": {"name": name},
            "average": avg,
            "scores": scores if scores is not None else {"architecture": avg, "naming": avg},
            "type_errors": type_errors,
        }

    def test_empty_results(self):
        """Empty audit_results list handled gracefully."""
        from aipass.seedgo.apps.handlers.audit.audit_display import (
            print_system_summary,
        )

        print_system_summary([])

    def test_all_excellent(self):
        """All branches >= 90 counted as excellent."""
        from aipass.seedgo.apps.handlers.audit.audit_display import (
            print_system_summary,
        )

        results = [
            self._make_result("a", 95),
            self._make_result("b", 92),
        ]
        print_system_summary(results)

    def test_mixed_tiers(self):
        """Branches across all tiers counted correctly."""
        from aipass.seedgo.apps.handlers.audit.audit_display import (
            print_system_summary,
        )

        results = [
            self._make_result("excellent", 95),
            self._make_result("good", 82),
            self._make_result("bad", 60),
        ]
        print_system_summary(results)

    def test_type_errors_in_summary(self):
        """Type errors total rendered."""
        from aipass.seedgo.apps.handlers.audit.audit_display import (
            print_system_summary,
        )

        results = [
            self._make_result("a", 85, type_errors=5),
            self._make_result("b", 90, type_errors=0),
        ]
        print_system_summary(results)

    def test_no_type_errors_green(self):
        """Zero type errors shows green message."""
        from aipass.seedgo.apps.handlers.audit.audit_display import (
            print_system_summary,
        )

        results = [self._make_result("a", 90)]
        print_system_summary(results)

    def test_odd_standard_count(self):
        """Odd number of standards renders last one alone."""
        from aipass.seedgo.apps.handlers.audit.audit_display import (
            print_system_summary,
        )

        results = [
            self._make_result(
                "a",
                80,
                scores={"arch": 80, "naming": 85, "meta": 90},
            ),
        ]
        print_system_summary(results)

    def test_top_improvement_areas(self):
        """Top improvement areas listed with failing branch count."""
        from aipass.seedgo.apps.handlers.audit.audit_display import (
            print_system_summary,
        )

        results = [
            self._make_result("a", 60, scores={"arch": 50, "naming": 70}),
            self._make_result("b", 80, scores={"arch": 90, "naming": 70}),
        ]
        print_system_summary(results)

    def test_standard_averages_icons(self):
        """Standard averages display correct icons for all tiers."""
        from aipass.seedgo.apps.handlers.audit.audit_display import (
            print_system_summary,
        )

        results = [
            self._make_result(
                "a",
                80,
                scores={"high": 95, "mid": 80, "low": 50},
            ),
        ]
        print_system_summary(results)


# ===========================================================================
# BRANCH_AUDIT TESTS
# ===========================================================================


class TestDiscoverCheckers:
    """Tests for discover_checkers."""

    def test_discover_from_path(self, tmp_path):
        """Discovers *_check.py modules with check_module."""
        from aipass.seedgo.apps.handlers.audit.branch_audit import (
            discover_checkers,
        )

        standards_dir = tmp_path / "standards"
        standards_dir.mkdir()
        checker_file = standards_dir / "naming_check.py"
        checker_file.write_text(
            "def check_module(path, bypass_rules=None):\n"
            "    return {\n"
            "        'passed': True, 'score': 100, 'checks': []\n"
            "    }\n",
            encoding="utf-8",
        )
        result = discover_checkers(standards_dir)
        assert "naming" in result

    def test_skip_without_check_functions(self, tmp_path):
        """Skips modules without check_module or check_branch."""
        from aipass.seedgo.apps.handlers.audit.branch_audit import (
            discover_checkers,
        )

        standards_dir = tmp_path / "standards"
        standards_dir.mkdir()
        checker_file = standards_dir / "bad_check.py"
        checker_file.write_text("x = 42\n", encoding="utf-8")
        result = discover_checkers(standards_dir)
        assert "bad" not in result

    def test_skip_failing_load(self, tmp_path):
        """Skips modules that raise during exec_module."""
        from aipass.seedgo.apps.handlers.audit.branch_audit import (
            discover_checkers,
        )

        standards_dir = tmp_path / "standards"
        standards_dir.mkdir()
        checker_file = standards_dir / "broken_check.py"
        checker_file.write_text("raise RuntimeError('broken')\n", encoding="utf-8")
        result = discover_checkers(standards_dir)
        assert "broken" not in result

    def test_empty_directory(self, tmp_path):
        """Empty standards dir returns empty dict."""
        from aipass.seedgo.apps.handlers.audit.branch_audit import (
            discover_checkers,
        )

        standards_dir = tmp_path / "standards"
        standards_dir.mkdir()
        result = discover_checkers(standards_dir)
        assert result == {}

    def test_spec_none_skipped(self, tmp_path):
        """Files where spec_from_file_location returns None skipped."""
        from aipass.seedgo.apps.handlers.audit.branch_audit import (
            discover_checkers,
        )

        standards_dir = tmp_path / "standards"
        standards_dir.mkdir()
        checker_file = standards_dir / "valid_check.py"
        checker_file.write_text(
            "def check_module(path, bypass_rules=None):\n"
            "    return {\n"
            "        'passed': True, 'score': 100, 'checks': []\n"
            "    }\n",
            encoding="utf-8",
        )
        with patch(
            "importlib.util.spec_from_file_location",
            return_value=None,
        ):
            result = discover_checkers(standards_dir)
        assert "valid" not in result

    def test_check_branch_function_discovered(self, tmp_path):
        """Modules with check_branch are discovered."""
        from aipass.seedgo.apps.handlers.audit.branch_audit import (
            discover_checkers,
        )

        standards_dir = tmp_path / "standards"
        standards_dir.mkdir()
        checker_file = standards_dir / "branch_check.py"
        checker_file.write_text(
            "def check_branch(path, bypass_rules=None):\n"
            "    return {\n"
            "        'passed': True, 'score': 100, 'checks': []\n"
            "    }\n",
            encoding="utf-8",
        )
        result = discover_checkers(standards_dir)
        assert "branch" in result


class TestCollectPyFiles:
    """Tests for _collect_py_files."""

    def test_no_apps_dir(self, tmp_path):
        """Returns empty list when apps/ does not exist."""
        from aipass.seedgo.apps.handlers.audit.branch_audit import (
            _collect_py_files,
        )

        result = _collect_py_files(tmp_path)
        assert result == []

    def test_collects_py_files(self, tmp_path, monkeypatch):
        """Collects .py from apps/, excluding __init__.py."""
        import sys

        skip_dirs = sys.modules.get("aipass.seedgo.apps.handlers.aipass_standards.skip_dirs")
        if skip_dirs:
            monkeypatch.setattr(skip_dirs, "_get_temp_roots", lambda: [])

        from aipass.seedgo.apps.handlers.audit.branch_audit import (
            _collect_py_files,
        )

        apps_dir = tmp_path / "apps"
        apps_dir.mkdir()
        (apps_dir / "__init__.py").write_text("", encoding="utf-8")
        (apps_dir / "module.py").write_text("pass", encoding="utf-8")
        subdir = apps_dir / "handlers"
        subdir.mkdir()
        (subdir / "handler.py").write_text("pass", encoding="utf-8")
        result = _collect_py_files(tmp_path)
        names = [f["name"] for f in result]
        assert "module.py" in names
        assert "handler.py" in names
        assert "__init__.py" not in names

    def test_collects_init_files_when_requested(self, tmp_path, monkeypatch):
        """include_init=True keeps __init__.py — for import checkers that must not miss them."""
        import sys

        skip_dirs = sys.modules.get("aipass.seedgo.apps.handlers.aipass_standards.skip_dirs")
        if skip_dirs:
            monkeypatch.setattr(skip_dirs, "_get_temp_roots", lambda: [])

        from aipass.seedgo.apps.handlers.audit.branch_audit import (
            _collect_py_files,
        )

        apps_dir = tmp_path / "apps"
        apps_dir.mkdir()
        (apps_dir / "__init__.py").write_text("", encoding="utf-8")
        (apps_dir / "module.py").write_text("pass", encoding="utf-8")
        result = _collect_py_files(tmp_path, include_init=True)
        names = [f["name"] for f in result]
        assert "module.py" in names
        assert "__init__.py" in names

    def test_respects_ignore_patterns(self, tmp_path, monkeypatch):
        """Files matching ignore patterns are excluded."""
        import sys

        skip_dirs = sys.modules.get("aipass.seedgo.apps.handlers.aipass_standards.skip_dirs")
        if skip_dirs:
            monkeypatch.setattr(skip_dirs, "_get_temp_roots", lambda: [])

        # Use a unique pattern that will NOT collide with the pytest tmp_path
        # directory name (which includes the test function name).
        mock_ign = sys.modules["aipass.seedgo.apps.handlers.bypass"].ignore_handler
        mock_ign.get_audit_ignore_patterns.return_value = ["xskip_"]

        from aipass.seedgo.apps.handlers.audit.branch_audit import (
            _collect_py_files,
        )

        apps_dir = tmp_path / "apps"
        apps_dir.mkdir()
        (apps_dir / "module.py").write_text("pass", encoding="utf-8")
        (apps_dir / "xskip_bad.py").write_text("pass", encoding="utf-8")
        result = _collect_py_files(tmp_path)
        names = [f["name"] for f in result]
        assert "module.py" in names
        assert "xskip_bad.py" not in names

    def test_excludes_disabled_files(self, tmp_path, monkeypatch):
        """Files with (disabled) in the name are excluded from collection."""
        import sys

        skip_dirs = sys.modules.get("aipass.seedgo.apps.handlers.aipass_standards.skip_dirs")
        if skip_dirs:
            monkeypatch.setattr(skip_dirs, "_get_temp_roots", lambda: [])

        from aipass.seedgo.apps.handlers.audit.branch_audit import (
            _collect_py_files,
        )

        apps_dir = tmp_path / "apps"
        apps_dir.mkdir()
        (apps_dir / "module.py").write_text("pass", encoding="utf-8")
        (apps_dir / "dashboard_sync(disabled).py").write_text("pass", encoding="utf-8")
        result = _collect_py_files(tmp_path)
        names = [f["name"] for f in result]
        assert "module.py" in names
        assert "dashboard_sync(disabled).py" not in names

    def test_respects_seedgo_ignore_tools_dir(self, tmp_path, monkeypatch):
        """Files under apps/tools/ are excluded via the global .seedgoignore default."""
        import sys

        skip_dirs = sys.modules.get("aipass.seedgo.apps.handlers.aipass_standards.skip_dirs")
        if skip_dirs:
            monkeypatch.setattr(skip_dirs, "_get_temp_roots", lambda: [])

        from aipass.seedgo.apps.handlers.audit.branch_audit import (
            _collect_py_files,
        )

        apps_dir = tmp_path / "apps"
        apps_dir.mkdir()
        (apps_dir / "module.py").write_text("pass", encoding="utf-8")
        tools_dir = apps_dir / "tools"
        tools_dir.mkdir()
        (tools_dir / "scratch.py").write_text("pass", encoding="utf-8")
        result = _collect_py_files(tmp_path)
        names = [f["name"] for f in result]
        assert "module.py" in names
        assert "scratch.py" not in names


class TestExtractBranchLevelViolations:
    """Tests for _extract_branch_level_violations."""

    def test_empty_result(self):
        """Empty dict returns empty list."""
        from aipass.seedgo.apps.handlers.audit.branch_audit import (
            _extract_branch_level_violations,
        )

        assert _extract_branch_level_violations({}) == []

    def test_extracts_violations(self):
        """Extracts violations from checks with list-type keys."""
        from aipass.seedgo.apps.handlers.audit.branch_audit import (
            _extract_branch_level_violations,
        )

        result = {
            "checks": [
                {
                    "name": "unused_check",
                    "passed": False,
                    "message": "Found unused",
                    "unused": [
                        {
                            "file": "/foo.py",
                            "name": "bar",
                            "line": 10,
                        },
                        {
                            "file": "/foo.py",
                            "name": "baz",
                            "line": 20,
                        },
                    ],
                },
            ]
        }
        violations = _extract_branch_level_violations(result)
        assert len(violations) == 1
        assert violations[0]["file"] == "/foo.py"
        assert len(violations[0]["issues"]) == 2

    def test_skips_non_list_keys(self):
        """Skips standard keys (name, passed, message, score)."""
        from aipass.seedgo.apps.handlers.audit.branch_audit import (
            _extract_branch_level_violations,
        )

        result = {
            "checks": [
                {
                    "name": "check",
                    "passed": True,
                    "message": "ok",
                    "score": 100,
                },
            ]
        }
        assert _extract_branch_level_violations(result) == []

    def test_skips_items_without_file_key(self):
        """Skips list items without a file key."""
        from aipass.seedgo.apps.handlers.audit.branch_audit import (
            _extract_branch_level_violations,
        )

        result = {
            "checks": [
                {
                    "name": "check",
                    "passed": False,
                    "message": "err",
                    "items": [{"name": "orphan"}],
                },
            ]
        }
        assert _extract_branch_level_violations(result) == []

    def test_multiple_files(self):
        """Groups violations by file path."""
        from aipass.seedgo.apps.handlers.audit.branch_audit import (
            _extract_branch_level_violations,
        )

        result = {
            "checks": [
                {
                    "name": "dead",
                    "passed": False,
                    "message": "found dead",
                    "dead_functions": [
                        {
                            "file": "/a.py",
                            "name": "f_a",
                            "line": 1,
                        },
                        {
                            "file": "/b.py",
                            "name": "f_b",
                            "line": 2,
                        },
                    ],
                },
            ]
        }
        violations = _extract_branch_level_violations(result)
        assert len(violations) == 2
        files = {v["file"] for v in violations}
        assert "/a.py" in files
        assert "/b.py" in files


class TestRunAllFiles:
    """Tests for _run_all_files."""

    def test_basic_run(self):
        """Basic run collects scores from passing checks."""
        from aipass.seedgo.apps.handlers.audit.branch_audit import (
            _run_all_files,
        )

        checker = MagicMock()
        checker.check_module = MagicMock(
            return_value={
                "passed": True,
                "score": 90,
                "checks": [
                    {"passed": True, "message": "OK"},
                ],
            }
        )
        checker.FILE_FILTER = None
        files = [{"file": "/foo.py", "name": "foo.py"}]
        violations, scores = _run_all_files(checker, "naming", files, [])
        assert len(scores) == 1
        assert scores[0] == 90

    def test_checker_raises_exception(self):
        """Checker that raises is skipped."""
        from aipass.seedgo.apps.handlers.audit.branch_audit import (
            _run_all_files,
        )

        checker = MagicMock()
        checker.check_module = MagicMock(side_effect=RuntimeError("boom"))
        checker.FILE_FILTER = None
        files = [{"file": "/foo.py", "name": "foo.py"}]
        violations, scores = _run_all_files(checker, "naming", files, [])
        assert violations == []
        assert scores == []

    def test_file_filter(self):
        """FILE_FILTER skips non-matching files."""
        from aipass.seedgo.apps.handlers.audit.branch_audit import (
            _run_all_files,
        )

        checker = MagicMock()
        checker.check_module = MagicMock(
            return_value={
                "passed": True,
                "score": 100,
                "checks": [
                    {"passed": True, "message": "OK"},
                ],
            }
        )
        checker.FILE_FILTER = "handler"
        files = [
            {"file": "/handler.py", "name": "handler.py"},
            {"file": "/module.py", "name": "module.py"},
        ]
        violations, scores = _run_all_files(checker, "naming", files, [])
        assert checker.check_module.call_count == 1

    def test_skipped_checks_excluded(self):
        """Checks with skipped/not applicable excluded."""
        from aipass.seedgo.apps.handlers.audit.branch_audit import (
            _run_all_files,
        )

        checker = MagicMock()
        checker.check_module = MagicMock(
            return_value={
                "passed": True,
                "score": 100,
                "checks": [
                    {
                        "passed": True,
                        "message": "Skipped -- not applicable",
                    }
                ],
            }
        )
        checker.FILE_FILTER = None
        files = [{"file": "/foo.py", "name": "foo.py"}]
        violations, scores = _run_all_files(checker, "naming", files, [])
        assert scores == []

    def test_failing_checks_collected(self):
        """Failing checks collected as violations."""
        from aipass.seedgo.apps.handlers.audit.branch_audit import (
            _run_all_files,
        )

        checker = MagicMock()
        checker.check_module = MagicMock(
            return_value={
                "passed": False,
                "score": 40,
                "checks": [
                    {"passed": False, "message": "Bad naming"},
                    {"passed": True, "message": "OK"},
                ],
            }
        )
        checker.FILE_FILTER = None
        files = [{"file": "/bad.py", "name": "bad.py"}]
        violations, scores = _run_all_files(checker, "naming", files, [])
        assert len(violations) == 1
        assert violations[0]["score"] == 40
        assert "Bad naming" in violations[0]["issues"]


class TestLoadDiagnosticsChecker:
    """Tests for _load_diagnostics_checker."""

    def test_path_not_exists(self):
        """Returns None when diagnostics file does not exist."""
        from aipass.seedgo.apps.handlers.audit.branch_audit import (
            _load_diagnostics_checker,
        )

        with patch("pathlib.Path.exists", return_value=False):
            result = _load_diagnostics_checker()
        assert result is None

    def test_spec_none(self):
        """Returns None when spec_from_file_location is None."""
        from aipass.seedgo.apps.handlers.audit.branch_audit import (
            _load_diagnostics_checker,
        )

        with (
            patch("pathlib.Path.exists", return_value=True),
            patch(
                "importlib.util.spec_from_file_location",
                return_value=None,
            ),
        ):
            result = _load_diagnostics_checker()
        assert result is None

    def test_exec_module_raises(self):
        """Returns None when exec_module raises."""
        from aipass.seedgo.apps.handlers.audit.branch_audit import (
            _load_diagnostics_checker,
        )

        mock_spec = MagicMock()
        mock_spec.loader.exec_module.side_effect = RuntimeError("fail")
        with (
            patch("pathlib.Path.exists", return_value=True),
            patch(
                "importlib.util.spec_from_file_location",
                return_value=mock_spec,
            ),
            patch(
                "importlib.util.module_from_spec",
                return_value=MagicMock(),
            ),
        ):
            result = _load_diagnostics_checker()
        assert result is None

    def test_successful_load(self):
        """Returns module when loading succeeds."""
        from aipass.seedgo.apps.handlers.audit.branch_audit import (
            _load_diagnostics_checker,
        )

        mock_mod = MagicMock()
        mock_spec = MagicMock()
        with (
            patch("pathlib.Path.exists", return_value=True),
            patch(
                "importlib.util.spec_from_file_location",
                return_value=mock_spec,
            ),
            patch(
                "importlib.util.module_from_spec",
                return_value=mock_mod,
            ),
        ):
            result = _load_diagnostics_checker()
        assert result is mock_mod


def _setup_branch(tmp_path: Path) -> tuple:
    """Create minimal branch structure, return (branch_dict, path)."""
    branch_path = tmp_path / "mybranch"
    branch_path.mkdir()
    entry = branch_path / "apps" / "main.py"
    entry.parent.mkdir(parents=True)
    entry.write_text("pass", encoding="utf-8")
    branch = {
        "name": "mybranch",
        "entry_file": str(entry),
        "path": str(branch_path),
    }
    return branch, branch_path


def _make_checker(
    scope: str = "entry_point",
    check_module_result: dict | None = None,
    check_branch_result: dict | None = None,
    has_check_module: bool = True,
    has_check_branch: bool = False,
    has_post: bool = False,
    post_result: tuple | None = None,
    has_info: bool = False,
    info_result: list | None = None,
) -> MagicMock:
    """Build a mock checker with configurable behavior."""
    checker = MagicMock()
    checker.AUDIT_SCOPE = scope
    checker.FILE_FILTER = None
    checker.INCLUDE_INIT_FILES = False

    if has_check_module:
        default_mod = {
            "passed": True,
            "score": 100,
            "checks": [],
        }
        checker.check_module = MagicMock(return_value=check_module_result or default_mod)
    else:
        del checker.check_module

    if has_check_branch:
        default_br = {
            "passed": True,
            "score": 100,
            "checks": [],
        }
        checker.check_branch = MagicMock(return_value=check_branch_result or default_br)
    else:
        del checker.check_branch

    if has_post:
        checker.check_branch_post = MagicMock(return_value=post_result or ([], []))
    else:
        del checker.check_branch_post

    if has_info:
        checker.check_branch_info = MagicMock(return_value=info_result if info_result is not None else [])
    else:
        del checker.check_branch_info

    return checker


class TestAuditBranch:
    """Tests for audit_branch."""

    def test_basic_audit(self, tmp_path, monkeypatch):
        """Basic audit with one entry-point checker."""
        from aipass.seedgo.apps.handlers.audit import branch_audit

        branch, _ = _setup_branch(tmp_path)
        checker = _make_checker()
        monkeypatch.setattr(
            branch_audit,
            "discover_checkers",
            lambda pack_path=None: {"naming": checker},
        )
        monkeypatch.setattr(
            branch_audit,
            "_load_diagnostics_checker",
            lambda: None,
        )
        monkeypatch.setattr(branch_audit, "scan_branch", lambda p: None)

        result = branch_audit.audit_branch(branch, [])
        assert result["branch"] == branch
        assert "naming" in result["scores"]
        assert result["average"] == 100

    def test_branch_level_checker(self, tmp_path, monkeypatch):
        """Branch-level checker calls check_branch."""
        from aipass.seedgo.apps.handlers.audit import branch_audit

        branch, _ = _setup_branch(tmp_path)
        checker = _make_checker(
            scope="branch_level",
            has_check_module=False,
            has_check_branch=True,
            check_branch_result={
                "passed": True,
                "score": 85,
                "checks": [],
            },
        )
        monkeypatch.setattr(
            branch_audit,
            "discover_checkers",
            lambda pack_path=None: {"dead_code": checker},
        )
        monkeypatch.setattr(
            branch_audit,
            "_load_diagnostics_checker",
            lambda: None,
        )
        monkeypatch.setattr(branch_audit, "scan_branch", lambda p: None)

        result = branch_audit.audit_branch(branch, [])
        assert result["scores"]["dead_code"] == 85

    def test_branch_level_checker_exception(self, tmp_path, monkeypatch):
        """Branch-level checker that raises produces score 0."""
        from aipass.seedgo.apps.handlers.audit import branch_audit

        branch, _ = _setup_branch(tmp_path)
        checker = _make_checker(
            scope="branch_level",
            has_check_module=False,
            has_check_branch=True,
        )
        checker.check_branch.side_effect = RuntimeError("boom")
        monkeypatch.setattr(
            branch_audit,
            "discover_checkers",
            lambda pack_path=None: {"broken": checker},
        )
        monkeypatch.setattr(
            branch_audit,
            "_load_diagnostics_checker",
            lambda: None,
        )
        monkeypatch.setattr(branch_audit, "scan_branch", lambda p: None)

        result = branch_audit.audit_branch(branch, [])
        assert result["scores"]["broken"] == 0
        assert "error" in result["results"]["broken"]

    def test_entry_point_checker_exception(self, tmp_path, monkeypatch):
        """Entry-point checker that raises produces score 0."""
        from aipass.seedgo.apps.handlers.audit import branch_audit

        branch, _ = _setup_branch(tmp_path)
        checker = _make_checker()
        checker.check_module.side_effect = RuntimeError("crash")
        monkeypatch.setattr(
            branch_audit,
            "discover_checkers",
            lambda pack_path=None: {"naming": checker},
        )
        monkeypatch.setattr(
            branch_audit,
            "_load_diagnostics_checker",
            lambda: None,
        )
        monkeypatch.setattr(branch_audit, "scan_branch", lambda p: None)

        result = branch_audit.audit_branch(branch, [])
        assert result["scores"]["naming"] == 0
        assert "error" in result["results"]["naming"]

    def test_all_files_scope(self, tmp_path, monkeypatch):
        """all_files scope runs checker on every file."""
        from aipass.seedgo.apps.handlers.audit import branch_audit

        branch, branch_path = _setup_branch(tmp_path)
        apps_dir = Path(branch_path) / "apps"
        (apps_dir / "other.py").write_text("pass", encoding="utf-8")

        checker = _make_checker(
            scope="all_files",
            check_module_result={
                "passed": True,
                "score": 80,
                "checks": [
                    {"passed": True, "message": "OK"},
                ],
            },
        )
        monkeypatch.setattr(
            branch_audit,
            "discover_checkers",
            lambda pack_path=None: {"naming": checker},
        )
        monkeypatch.setattr(
            branch_audit,
            "_load_diagnostics_checker",
            lambda: None,
        )
        monkeypatch.setattr(branch_audit, "scan_branch", lambda p: None)

        result = branch_audit.audit_branch(branch, [])
        assert result["scores"]["naming"] == 80

    def test_all_files_with_violations(self, tmp_path, monkeypatch):
        """all_files scope with failing checks updates results."""
        from aipass.seedgo.apps.handlers.audit import branch_audit

        branch, branch_path = _setup_branch(tmp_path)
        apps_dir = Path(branch_path) / "apps"
        (apps_dir / "bad.py").write_text("pass", encoding="utf-8")

        def check_side_effect(path, bypass_rules=None):
            """Return different results based on path."""
            if "bad" in path:
                return {
                    "passed": False,
                    "score": 40,
                    "checks": [
                        {
                            "passed": False,
                            "message": "Bad naming",
                        }
                    ],
                }
            return {
                "passed": True,
                "score": 90,
                "checks": [
                    {"passed": True, "message": "OK"},
                ],
            }

        checker = _make_checker(scope="all_files")
        checker.check_module.side_effect = check_side_effect
        monkeypatch.setattr(
            branch_audit,
            "discover_checkers",
            lambda pack_path=None: {"naming": checker},
        )
        monkeypatch.setattr(
            branch_audit,
            "_load_diagnostics_checker",
            lambda: None,
        )
        monkeypatch.setattr(branch_audit, "scan_branch", lambda p: None)

        result = branch_audit.audit_branch(branch, [])
        assert "naming_violations" in result

    def test_all_files_scope_include_init_files_opt_in(self, tmp_path, monkeypatch):
        """Checker with INCLUDE_INIT_FILES=True sees __init__.py; a normal checker does not."""
        from aipass.seedgo.apps.handlers.audit import branch_audit

        branch, branch_path = _setup_branch(tmp_path)
        apps_dir = Path(branch_path) / "apps"
        (apps_dir / "__init__.py").write_text("pass", encoding="utf-8")

        import_checker = _make_checker(scope="all_files")
        import_checker.INCLUDE_INIT_FILES = True
        normal_checker = _make_checker(scope="all_files")

        # tmp_path lives under the system temp dir, which is_throwaway_path
        # filters out wholesale — neutralize that so _collect_py_files sees
        # the fixture's files, same as it would for a real branch on disk.
        monkeypatch.setattr(branch_audit, "is_throwaway_path", lambda path_str: False)
        monkeypatch.setattr(
            branch_audit,
            "discover_checkers",
            lambda pack_path=None: {"handlers": import_checker, "naming": normal_checker},
        )
        monkeypatch.setattr(
            branch_audit,
            "_load_diagnostics_checker",
            lambda: None,
        )
        monkeypatch.setattr(branch_audit, "scan_branch", lambda p: None)

        branch_audit.audit_branch(branch, [])

        import_checked_names = {Path(c.args[0]).name for c in import_checker.check_module.call_args_list}
        normal_checked_names = {Path(c.args[0]).name for c in normal_checker.check_module.call_args_list}
        assert "__init__.py" in import_checked_names
        assert "__init__.py" not in normal_checked_names

    def test_dynamic_post_check(self, tmp_path, monkeypatch):
        """check_branch_post discovered and called."""
        from aipass.seedgo.apps.handlers.audit import branch_audit

        branch, _ = _setup_branch(tmp_path)
        post_violations = [
            {
                "path": "/extra.py",
                "score": 0,
                "issues": ["Extra issue"],
            }
        ]
        checker = _make_checker(
            has_post=True,
            post_result=(post_violations, [50]),
        )
        monkeypatch.setattr(
            branch_audit,
            "discover_checkers",
            lambda pack_path=None: {"naming": checker},
        )
        monkeypatch.setattr(
            branch_audit,
            "_load_diagnostics_checker",
            lambda: None,
        )
        monkeypatch.setattr(branch_audit, "scan_branch", lambda p: None)

        result = branch_audit.audit_branch(branch, [])
        # Post check: (100 + 50) / 2 = 75
        assert result["scores"]["naming"] == 75
        assert len(result["naming_violations"]) == 1

    def test_post_check_raises_exception(self, tmp_path, monkeypatch):
        """check_branch_post that raises is caught."""
        from aipass.seedgo.apps.handlers.audit import branch_audit

        branch, _ = _setup_branch(tmp_path)
        checker = _make_checker(has_post=True)
        checker.check_branch_post.side_effect = RuntimeError("fail")
        monkeypatch.setattr(
            branch_audit,
            "discover_checkers",
            lambda pack_path=None: {"naming": checker},
        )
        monkeypatch.setattr(
            branch_audit,
            "_load_diagnostics_checker",
            lambda: None,
        )
        monkeypatch.setattr(branch_audit, "scan_branch", lambda p: None)

        result = branch_audit.audit_branch(branch, [])
        assert result["scores"]["naming"] == 100

    def test_info_channel_collected_and_never_scored(self, tmp_path, monkeypatch):
        """check_branch_info lines reach output without touching the score."""
        from aipass.seedgo.apps.handlers.audit import branch_audit

        branch, _ = _setup_branch(tmp_path)
        checker = _make_checker(has_info=True, info_result=["custom_config: cadence_config.json"])
        monkeypatch.setattr(
            branch_audit,
            "discover_checkers",
            lambda pack_path=None: {"naming": checker},
        )
        monkeypatch.setattr(branch_audit, "_load_diagnostics_checker", lambda: None)
        monkeypatch.setattr(branch_audit, "scan_branch", lambda p: None)

        result = branch_audit.audit_branch(branch, [])
        assert result["info_lines"] == [{"standard": "naming", "message": "custom_config: cadence_config.json"}]
        assert result["scores"]["naming"] == 100
        assert result["average"] == 100

    def test_info_check_raises_is_caught(self, tmp_path, monkeypatch):
        """check_branch_info that raises leaves the audit intact."""
        from aipass.seedgo.apps.handlers.audit import branch_audit

        branch, _ = _setup_branch(tmp_path)
        checker = _make_checker(has_info=True)
        checker.check_branch_info.side_effect = RuntimeError("fail")
        monkeypatch.setattr(
            branch_audit,
            "discover_checkers",
            lambda pack_path=None: {"naming": checker},
        )
        monkeypatch.setattr(branch_audit, "_load_diagnostics_checker", lambda: None)
        monkeypatch.setattr(branch_audit, "scan_branch", lambda p: None)

        result = branch_audit.audit_branch(branch, [])
        assert result["info_lines"] == []
        assert result["scores"]["naming"] == 100

    def test_checker_without_info_hook_skipped(self, tmp_path, monkeypatch):
        """A checker with no check_branch_info contributes no info lines."""
        from aipass.seedgo.apps.handlers.audit import branch_audit

        branch, _ = _setup_branch(tmp_path)
        monkeypatch.setattr(
            branch_audit,
            "discover_checkers",
            lambda pack_path=None: {"naming": _make_checker()},
        )
        monkeypatch.setattr(branch_audit, "_load_diagnostics_checker", lambda: None)
        monkeypatch.setattr(branch_audit, "scan_branch", lambda p: None)

        assert branch_audit.audit_branch(branch, [])["info_lines"] == []

    def test_diagnostics_checker_added(self, tmp_path, monkeypatch):
        """Diagnostics checker loaded and added."""
        from aipass.seedgo.apps.handlers.audit import branch_audit

        branch, _ = _setup_branch(tmp_path)
        diag_mod = MagicMock()
        diag_mod.check_branch = MagicMock(
            return_value={
                "passed": True,
                "score": 90,
                "checks": [],
                "total_errors": 0,
                "results": [],
            }
        )
        diag_mod.AUDIT_SCOPE = "branch_level"
        del diag_mod.check_module

        monkeypatch.setattr(
            branch_audit,
            "discover_checkers",
            lambda pack_path=None: {},
        )
        monkeypatch.setattr(
            branch_audit,
            "_load_diagnostics_checker",
            lambda: diag_mod,
        )
        monkeypatch.setattr(branch_audit, "scan_branch", lambda p: None)

        result = branch_audit.audit_branch(branch, [])
        assert "diagnostics" in result["scores"]

    def test_deprecated_documents_dir(self, tmp_path, monkeypatch):
        """DOCUMENTS/ directory detected as deprecated."""
        from aipass.seedgo.apps.handlers.audit import branch_audit

        branch, branch_path = _setup_branch(tmp_path)
        (Path(branch_path) / "DOCUMENTS").mkdir()

        monkeypatch.setattr(
            branch_audit,
            "discover_checkers",
            lambda pack_path=None: {},
        )
        monkeypatch.setattr(
            branch_audit,
            "_load_diagnostics_checker",
            lambda: None,
        )
        monkeypatch.setattr(branch_audit, "scan_branch", lambda p: None)

        result = branch_audit.audit_branch(branch, [])
        assert len(result["deprecated_patterns"]) == 1
        dep = result["deprecated_patterns"][0]
        assert dep["old"] == "DOCUMENTS/"

    def test_no_deprecated_without_documents(self, tmp_path, monkeypatch):
        """No deprecated patterns without DOCUMENTS/."""
        from aipass.seedgo.apps.handlers.audit import branch_audit

        branch, _ = _setup_branch(tmp_path)
        monkeypatch.setattr(
            branch_audit,
            "discover_checkers",
            lambda pack_path=None: {},
        )
        monkeypatch.setattr(
            branch_audit,
            "_load_diagnostics_checker",
            lambda: None,
        )
        monkeypatch.setattr(branch_audit, "scan_branch", lambda p: None)

        result = branch_audit.audit_branch(branch, [])
        assert result["deprecated_patterns"] == []

    def test_scan_branch_exception(self, tmp_path, monkeypatch):
        """scan_branch exception caught, test_map is None."""
        from aipass.seedgo.apps.handlers.audit import branch_audit

        branch, _ = _setup_branch(tmp_path)
        monkeypatch.setattr(
            branch_audit,
            "discover_checkers",
            lambda pack_path=None: {},
        )
        monkeypatch.setattr(
            branch_audit,
            "_load_diagnostics_checker",
            lambda: None,
        )
        monkeypatch.setattr(
            branch_audit,
            "scan_branch",
            MagicMock(side_effect=RuntimeError("scan fail")),
        )

        result = branch_audit.audit_branch(branch, [])
        assert result["test_map"] is None

    def test_scan_branch_success(self, tmp_path, monkeypatch):
        """scan_branch success populates test_map."""
        from aipass.seedgo.apps.handlers.audit import branch_audit

        branch, _ = _setup_branch(tmp_path)
        scan_result = {
            "total_functions": 10,
            "tested_functions": 5,
            "branch": "mybranch",
        }
        monkeypatch.setattr(
            branch_audit,
            "discover_checkers",
            lambda pack_path=None: {},
        )
        monkeypatch.setattr(
            branch_audit,
            "_load_diagnostics_checker",
            lambda: None,
        )
        monkeypatch.setattr(
            branch_audit,
            "scan_branch",
            MagicMock(return_value=scan_result),
        )

        result = branch_audit.audit_branch(branch, [])
        assert result["test_map"] == scan_result

    def test_no_checkers_zero_average(self, tmp_path, monkeypatch):
        """No checkers returns average 0."""
        from aipass.seedgo.apps.handlers.audit import branch_audit

        branch, _ = _setup_branch(tmp_path)
        monkeypatch.setattr(
            branch_audit,
            "discover_checkers",
            lambda pack_path=None: {},
        )
        monkeypatch.setattr(
            branch_audit,
            "_load_diagnostics_checker",
            lambda: None,
        )
        monkeypatch.setattr(branch_audit, "scan_branch", lambda p: None)

        result = branch_audit.audit_branch(branch, [])
        assert result["average"] == 0

    def test_implicit_branch_level(self, tmp_path, monkeypatch):
        """Checker without check_module treated as branch-level."""
        from aipass.seedgo.apps.handlers.audit import branch_audit

        branch, _ = _setup_branch(tmp_path)
        checker = _make_checker(
            scope="entry_point",
            has_check_module=False,
            has_check_branch=True,
            check_branch_result={
                "passed": True,
                "score": 75,
                "checks": [],
            },
        )
        monkeypatch.setattr(
            branch_audit,
            "discover_checkers",
            lambda pack_path=None: {"implicit": checker},
        )
        monkeypatch.setattr(
            branch_audit,
            "_load_diagnostics_checker",
            lambda: None,
        )
        monkeypatch.setattr(branch_audit, "scan_branch", lambda p: None)

        result = branch_audit.audit_branch(branch, [])
        assert result["scores"]["implicit"] == 75

    def test_pack_path_forwarded(self, tmp_path, monkeypatch):
        """pack_path argument forwarded to discover_checkers."""
        from aipass.seedgo.apps.handlers.audit import branch_audit

        branch, _ = _setup_branch(tmp_path)
        captured: dict = {}

        def mock_discover(pack_path=None):
            """Capture the pack_path argument."""
            captured["value"] = pack_path
            return {}

        monkeypatch.setattr(branch_audit, "discover_checkers", mock_discover)
        monkeypatch.setattr(
            branch_audit,
            "_load_diagnostics_checker",
            lambda: None,
        )
        monkeypatch.setattr(branch_audit, "scan_branch", lambda p: None)

        pack = tmp_path / "custom_standards"
        branch_audit.audit_branch(branch, [], pack_path=pack)
        assert captured["value"] == pack

    def test_diagnostics_not_duplicated(self, tmp_path, monkeypatch):
        """Existing diagnostics not overwritten by loader."""
        from aipass.seedgo.apps.handlers.audit import branch_audit

        branch, _ = _setup_branch(tmp_path)
        existing = _make_checker(
            scope="branch_level",
            has_check_module=False,
            has_check_branch=True,
            check_branch_result={
                "passed": True,
                "score": 80,
                "checks": [],
                "total_errors": 0,
                "results": [],
            },
        )
        different = MagicMock()

        monkeypatch.setattr(
            branch_audit,
            "discover_checkers",
            lambda pack_path=None: {"diagnostics": existing},
        )
        monkeypatch.setattr(
            branch_audit,
            "_load_diagnostics_checker",
            lambda: different,
        )
        monkeypatch.setattr(branch_audit, "scan_branch", lambda p: None)

        result = branch_audit.audit_branch(branch, [])
        assert result["scores"]["diagnostics"] == 80

    def test_branch_level_violations_extraction(self, tmp_path, monkeypatch):
        """Branch-level results have violations extracted."""
        from aipass.seedgo.apps.handlers.audit import branch_audit

        branch, _ = _setup_branch(tmp_path)
        checker = _make_checker(
            scope="branch_level",
            has_check_module=False,
            has_check_branch=True,
            check_branch_result={
                "passed": False,
                "score": 60,
                "checks": [
                    {
                        "name": "unused_check",
                        "passed": False,
                        "message": "Found unused",
                        "unused": [
                            {
                                "file": "/foo.py",
                                "name": "bar",
                                "line": 10,
                            },
                        ],
                    },
                ],
            },
        )
        monkeypatch.setattr(
            branch_audit,
            "discover_checkers",
            lambda pack_path=None: {"dead_code": checker},
        )
        monkeypatch.setattr(
            branch_audit,
            "_load_diagnostics_checker",
            lambda: None,
        )
        monkeypatch.setattr(branch_audit, "scan_branch", lambda p: None)

        result = branch_audit.audit_branch(branch, [])
        assert len(result["dead_code_violations"]) == 1

    def test_output_diagnostics_fields(self, tmp_path, monkeypatch):
        """Output includes type_errors and type_error_files."""
        from aipass.seedgo.apps.handlers.audit import branch_audit

        branch, _ = _setup_branch(tmp_path)
        diag = _make_checker(
            scope="branch_level",
            has_check_module=False,
            has_check_branch=True,
            check_branch_result={
                "passed": True,
                "score": 90,
                "checks": [],
                "total_errors": 3,
                "results": [{"file": "a.py", "errors": 3}],
            },
        )
        monkeypatch.setattr(
            branch_audit,
            "discover_checkers",
            lambda pack_path=None: {"diagnostics": diag},
        )
        monkeypatch.setattr(
            branch_audit,
            "_load_diagnostics_checker",
            lambda: None,
        )
        monkeypatch.setattr(branch_audit, "scan_branch", lambda p: None)

        result = branch_audit.audit_branch(branch, [])
        assert result["type_errors"] == 3
        assert result["type_error_files"] == [{"file": "a.py", "errors": 3}]

    def test_post_check_empty_scores(self, tmp_path, monkeypatch):
        """Post-check with empty scores does not change score."""
        from aipass.seedgo.apps.handlers.audit import branch_audit

        branch, _ = _setup_branch(tmp_path)
        checker = _make_checker(
            has_post=True,
            post_result=([], []),
        )
        monkeypatch.setattr(
            branch_audit,
            "discover_checkers",
            lambda pack_path=None: {"naming": checker},
        )
        monkeypatch.setattr(
            branch_audit,
            "_load_diagnostics_checker",
            lambda: None,
        )
        monkeypatch.setattr(branch_audit, "scan_branch", lambda p: None)

        result = branch_audit.audit_branch(branch, [])
        assert result["scores"]["naming"] == 100
