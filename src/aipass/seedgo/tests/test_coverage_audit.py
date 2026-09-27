# =================== META ====================
# Name: test_coverage_audit.py
# Description: Unit tests for audit_display.py and branch_audit.py line coverage
# Version: 1.3.0
# Created: 2026-04-26
# Modified: 2026-09-27
# =============================================

"""Tests for apps/handlers/audit/audit_display.py and apps/handlers/audit/branch_audit.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that audit_display.py and branch_audit.py parse and import
# seedgo: no-test-needed(constant) — _FLEET_STATE_STYLE's colour names and _MAX_NAMED_RERUNS' value

import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from aipass.seedgo.apps.handlers.aipass_standards import skip_dirs
from aipass.seedgo.apps.handlers.audit import audit_display, branch_audit
from aipass.seedgo.apps.handlers.bypass.ignore_handler import (
    audit_ignore_match as real_audit_ignore_match,
    is_seedgo_ignored as real_is_seedgo_ignored,
    load_ignore_entries as real_load_ignore_entries,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _mock_infrastructure(monkeypatch):
    """Patch audit_display's and branch_audit's own seams with mocks.

    audit_display and branch_audit are imported for real at module top, so
    isolation is applied at the edge each one actually reads (its own bound
    name for logger / warning / json_handler / ignore_handler / scan_branch)
    instead of intercepting the packages in sys.modules. The console stays
    real: it writes to stdout at print time, and the render tests read capsys.
    """
    mock_logger = MagicMock()
    mock_json_handler = MagicMock()
    mock_json_handler.log_operation = MagicMock(return_value=True)

    mock_ignore_handler = MagicMock()
    mock_ignore_handler.get_audit_ignore_patterns = MagicMock(return_value=[])
    # The ignore list removes nothing here, as the empty pattern list above says.
    mock_ignore_handler.audit_ignore_match = MagicMock(return_value=None)
    mock_ignore_handler.ignored_tracked_source = MagicMock(return_value=[])
    mock_ignore_handler.is_seedgo_ignored = real_is_seedgo_ignored
    mock_ignore_handler.load_ignore_entries = real_load_ignore_entries
    mock_scan_branch = MagicMock(return_value=None)

    # -- audit_display's own seams --------------------------------------
    monkeypatch.setattr(audit_display, "warning", MagicMock())
    monkeypatch.setattr(audit_display, "json_handler", mock_json_handler)

    # -- branch_audit's own seams ----------------------------------------
    monkeypatch.setattr(branch_audit, "logger", mock_logger)
    monkeypatch.setattr(branch_audit, "json_handler", mock_json_handler)
    monkeypatch.setattr(branch_audit, "ignore_handler", mock_ignore_handler)
    monkeypatch.setattr(branch_audit, "dead_rules", MagicMock())
    monkeypatch.setattr(branch_audit, "inert", MagicMock())
    monkeypatch.setattr(branch_audit, "scan_branch", mock_scan_branch)


# ===========================================================================
# AUDIT_DISPLAY TESTS
# ===========================================================================


def _summary(capsys, scores: dict, results: dict | None = None, **extra) -> str:
    """What print_branch_summary writes to stdout for one branch built from these fields.

    The renderers are reached the way a user reaches them: the branch summary
    hands each one the real console, which writes to stdout at print time, so
    capsys reads what a terminal would show and nothing a mock merely received.
    """
    audit_result = {
        "branch": {"name": "test_branch"},
        "scores": scores,
        "average": 70,
        "files_checked": 0,
        "results": results or {},
        **extra,
    }
    capsys.readouterr()
    audit_display.print_branch_summary(audit_result)
    return capsys.readouterr().out


def _failed_branch_check(name: str) -> str:
    """The issues heading a branch-level finding prints under, for a standard called *name*."""
    return f"{name} issues:"


class TestFormatStandardName:
    """The standard's display name, as a branch-level finding prints it."""

    def test_underscore_conversion(self, capsys):
        """DEEP_NESTING becomes Deep Nesting. Mutant: underscores kept in apps/handlers/audit/audit_display.py — killed."""
        checks = {"DEEP_NESTING": {"checks": [{"passed": False, "message": "nested five deep"}]}}
        out = _summary(capsys, {"DEEP_NESTING": 70}, checks)
        assert _failed_branch_check("Deep Nesting") in out

    def test_lowercase_conversion(self, capsys):
        """Lowercase deep_nesting becomes Deep Nesting. Mutant: underscores kept in apps/handlers/audit/audit_display.py — killed."""
        checks = {"deep_nesting": {"checks": [{"passed": False, "message": "nested five deep"}]}}
        out = _summary(capsys, {"deep_nesting": 70}, checks)
        assert _failed_branch_check("Deep Nesting") in out

    def test_single_word(self, capsys):
        """Single word gets title-cased (naming: architecture has its own renderer). Mutant: .title() dropped in apps/handlers/audit/audit_display.py — killed."""
        checks = {"naming": {"checks": [{"passed": False, "message": "bad name"}]}}
        out = _summary(capsys, {"naming": 70}, checks)
        assert _failed_branch_check("Naming") in out


class TestRenderViolations:
    """A standard's violation list, as the branch summary prints it."""

    @staticmethod
    def _naming(capsys, violations: list) -> str:
        """The summary of a branch whose naming row carries *violations*."""
        return _summary(capsys, {"naming": 60}, naming_violations=violations)

    def test_basic_violations(self, capsys):
        """Basic violations with path, score, and issues rendered. Mutant: only the first issue printed in apps/handlers/audit/audit_display.py — killed."""
        out = self._naming(capsys, [{"path": "/foo/bar.py", "score": 60, "issues": ["Bad indent", "Long line"]}])
        assert "NAMING VIOLATIONS (1 files):" in out
        assert "/foo/bar.py (score: 60%)" in out
        assert "• Bad indent" in out
        assert "• Long line" in out

    def test_file_key_fallback(self, capsys):
        """Falls back to file key when path is missing. Mutant: the file fallback dropped in apps/handlers/audit/audit_display.py — killed."""
        out = self._naming(capsys, [{"file": "bar.py", "score": 50, "issues": ["Something wrong"]}])
        assert "✗ bar.py (score: 50%)" in out

    def test_message_fallback_when_no_issues(self, capsys):
        """Shows message when issues list is empty. Mutant: the message fallback never taken in apps/handlers/audit/audit_display.py — killed."""
        out = self._naming(capsys, [{"path": "/foo.py", "score": 0, "issues": [], "message": "General failure"}])
        assert "• General failure" in out

    def test_more_than_five_violations(self, capsys):
        """Shows and N more when violations exceed 5. Mutant: the cap raised to 8 in apps/handlers/audit/audit_display.py — killed."""
        out = self._naming(capsys, [{"path": f"/file{i}.py", "score": 10, "issues": []} for i in range(8)])
        assert "... and 3 more" in out
        assert "/file5.py" not in out

    def test_exactly_five_violations_no_more(self, capsys):
        """No more message when exactly 5 violations. Mutant: the cap tested with >= in apps/handlers/audit/audit_display.py — killed."""
        out = self._naming(capsys, [{"path": f"/file{i}.py", "score": 10, "issues": []} for i in range(5)])
        assert "/file4.py" in out
        assert "... and" not in out

    def test_no_path_no_file_key(self, capsys):
        """Both path and file missing prints an empty path. Mutant: the empty default replaced in apps/handlers/audit/audit_display.py — killed."""
        out = self._naming(capsys, [{"score": 0, "issues": ["err"]}])
        assert "✗  (score: 0%)" in out
        assert "• err" in out


class TestRenderArchitectureViolations:
    """The architecture row's failed checks, as the branch summary prints them."""

    @staticmethod
    def _architecture(capsys, checks: list | None) -> str:
        """The summary of a branch whose architecture row failed with *checks* (None: no result)."""
        results = {} if checks is None else {"architecture": {"checks": checks}}
        return _summary(capsys, {"architecture": 70}, results)

    def test_no_failed_checks(self, capsys):
        """Returns early when all checks pass. Mutant: the early return removed in apps/handlers/audit/audit_display.py — killed."""
        out = self._architecture(capsys, [{"passed": True, "name": "Dir: apps"}])
        assert "ARCHITECTURE VIOLATIONS" not in out

    def test_missing_directories(self, capsys):
        """Shows missing directories grouped. Mutant: 'Directory:' not grouped as a directory in apps/handlers/audit/audit_display.py — killed."""
        checks = [
            {"passed": False, "name": "Dir: apps", "message": "x"},
            {"passed": False, "name": "Directory: tests", "message": "x"},
        ]
        out = self._architecture(capsys, checks)
        assert "ARCHITECTURE VIOLATIONS (2 missing):" in out
        assert "Missing directories (2):" in out
        assert "✗ apps" in out
        assert "✗ tests" in out

    def test_missing_files(self, capsys):
        """Shows missing files grouped. Mutant: 'File:' checks not grouped in apps/handlers/audit/audit_display.py — killed."""
        out = self._architecture(capsys, [{"passed": False, "name": "File: README.md", "message": "x"}])
        assert "Missing files (1):" in out
        assert "✗ README.md" in out

    def test_other_failures(self, capsys):
        """Shows non-dir, non-file failures. Mutant: other failures never printed in apps/handlers/audit/audit_display.py — killed."""
        out = self._architecture(capsys, [{"passed": False, "name": "Custom check", "message": "Something wrong"}])
        assert "• Something wrong" in out

    def test_more_than_five_dirs(self, capsys):
        """Directories list truncated at 5 with more message. Mutant: the directory cap raised to 7 in apps/handlers/audit/audit_display.py — killed."""
        out = self._architecture(capsys, [{"passed": False, "name": f"Dir: dir{i}"} for i in range(7)])
        assert "... and 2 more" in out
        assert "dir5" not in out

    def test_more_than_five_files(self, capsys):
        """Files list truncated at 5 with more message. Mutant: the file cap raised to 8 in apps/handlers/audit/audit_display.py — killed."""
        out = self._architecture(capsys, [{"passed": False, "name": f"File: file{i}.py"} for i in range(8)])
        assert "... and 3 more" in out
        assert "file5.py" not in out

    def test_empty_results(self, capsys):
        """No architecture result at all prints no violation block. Mutant: the early return removed in apps/handlers/audit/audit_display.py — killed."""
        out = self._architecture(capsys, None)
        assert "ARCHITECTURE VIOLATIONS" not in out

    def test_mixed_dirs_files_other(self, capsys):
        """Mix of dirs, files, and other failures all render. Mutant: other failures never printed in apps/handlers/audit/audit_display.py — killed."""
        checks = [
            {"passed": False, "name": "Dir: apps"},
            {"passed": False, "name": "File: setup.py"},
            {"passed": False, "name": "Config check", "message": "Missing config"},
        ]
        out = self._architecture(capsys, checks)
        assert "Missing directories (1):" in out
        assert "Missing files (1):" in out
        assert "• Missing config" in out


class TestRenderTypeErrors:
    """The type-error block, as the branch summary prints it."""

    def test_no_type_errors_no_files_checked(self, capsys):
        """No type errors and no files checked produces no output. Mutant: the green line printed unconditionally in apps/handlers/audit/audit_display.py — killed."""
        out = _summary(capsys, {"naming": 100}, type_errors=0, files_checked=0)
        assert "TYPE ERRORS" not in out
        assert "No type errors" not in out

    def test_no_type_errors_with_files_checked(self, capsys):
        """No type errors but files checked shows green check. Mutant: the green line gated on > 5 files in apps/handlers/audit/audit_display.py — killed."""
        out = _summary(capsys, {"naming": 100}, type_errors=0, files_checked=5)
        assert "✓ No type errors" in out

    def test_type_errors_with_diagnostics(self, capsys):
        """Type errors render file details and diagnostics. Mutant: no diagnostic lines printed in apps/handlers/audit/audit_display.py — killed."""
        out = _summary(
            capsys,
            {"naming": 100},
            type_errors=3,
            type_error_files=[
                {
                    "file": "module.py",
                    "errors": 2,
                    "diagnostics": [
                        {"line": 10, "message": "Type mismatch"},
                        {"line": 20, "message": "Incompatible"},
                    ],
                },
                {"file": "other.py", "errors": 1, "diagnostics": [{"line": 5, "message": "Missing arg"}]},
            ],
            files_checked=10,
        )
        assert "TYPE ERRORS (3 errors):" in out
        assert "✗ module.py (2 errors)" in out
        assert "L10: Type mismatch" in out
        assert "✗ other.py (1 errors)" in out

    def test_type_error_file_cap_announces_itself(self, capsys):
        """A cap that does not announce itself reads as a clean result (@prax, 83190864). Mutant: the file cap note gated on > 14 in apps/handlers/audit/audit_display.py — killed."""
        out = _summary(
            capsys,
            {"naming": 100},
            type_errors=14,
            type_error_files=[{"file": f"m{n}.py", "errors": 1, "diagnostics": []} for n in range(14)],
            files_checked=20,
        )

        assert "... and 4 more files" in out

    def test_type_error_diagnostic_cap_announces_itself(self, capsys):
        """Per-file diagnostics are capped at 3 — the remainder must be declared. Mutant: the note gated on > 5 in apps/handlers/audit/audit_display.py — killed."""
        out = _summary(
            capsys,
            {"naming": 100},
            type_errors=5,
            type_error_files=[
                {"file": "m.py", "errors": 5, "diagnostics": [{"line": n, "message": f"err {n}"} for n in range(5)]}
            ],
            files_checked=1,
        )

        assert "... and 2 more in this file" in out

    def test_type_error_message_clip_is_marked(self, capsys):
        """A clipped message must show it was clipped. Mutant: the clip unmarked in apps/handlers/audit/audit_display.py — killed."""
        out = _summary(
            capsys,
            {"naming": 100},
            type_errors=1,
            type_error_files=[{"file": "m.py", "errors": 1, "diagnostics": [{"line": 1, "message": "x" * 90}]}],
            files_checked=1,
        )

        assert "L1: " + "x" * 60 + "…" in out

    def test_short_type_error_lists_declare_no_cap(self, capsys):
        """Negative direction: a short list must not claim a remainder. Mutant: every message marked clipped in apps/handlers/audit/audit_display.py — killed."""
        out = _summary(
            capsys,
            {"naming": 100},
            type_errors=1,
            type_error_files=[{"file": "m.py", "errors": 1, "diagnostics": [{"line": 1, "message": "short"}]}],
            files_checked=1,
        )

        assert "L1: short" in out
        assert "... and" not in out
        assert "…" not in out

    def test_file_zero_errors_skipped(self, capsys):
        """File with 0 errors in type_error_files is skipped. Mutant: zero-error files listed in apps/handlers/audit/audit_display.py — killed."""
        out = _summary(
            capsys,
            {"naming": 100},
            type_errors=1,
            type_error_files=[
                {"file": "clean.py", "errors": 0, "diagnostics": []},
                {"file": "bad.py", "errors": 1, "diagnostics": [{"line": 1, "message": "err"}]},
            ],
            files_checked=2,
        )
        assert "clean.py" not in out
        assert "✗ bad.py (1 errors)" in out

    def test_empty_audit_result(self, capsys):
        """Missing type keys handled gracefully. Mutant: the green line printed unconditionally in apps/handlers/audit/audit_display.py — killed."""
        out = _summary(capsys, {"naming": 100})
        assert "TYPE ERRORS" not in out
        assert "No type errors" not in out


class TestRenderTestMap:
    """The custom-test-opportunities line, as the branch summary prints it."""

    def test_no_test_map(self, capsys):
        """No test_map key produces no output. Mutant: a missing map read as one function in apps/handlers/audit/audit_display.py — killed."""
        out = _summary(capsys, {"naming": 100})
        assert "Custom Test Opportunities" not in out

    def test_test_map_zero_functions(self, capsys):
        """test_map with 0 total functions produces no output. Mutant: the zero guard removed in apps/handlers/audit/audit_display.py — killed."""
        out = _summary(capsys, {"naming": 100}, test_map={"total_functions": 0})
        assert "Custom Test Opportunities" not in out

    def test_test_map_with_data(self, capsys):
        """test_map with data renders summary. Mutant: the tested count read as 0 in apps/handlers/audit/audit_display.py — killed."""
        out = _summary(
            capsys, {"naming": 100}, test_map={"total_functions": 10, "tested_functions": 6, "branch": "seedgo"}
        )
        assert "Custom Test Opportunities: 10 public functions, 6 tested. Run: drone @seedgo test_map @seedgo" in out

    def test_test_map_none(self, capsys):
        """test_map explicitly None produces no output. Mutant: a missing map read as one function in apps/handlers/audit/audit_display.py — killed."""
        out = _summary(capsys, {"naming": 100}, test_map=None)
        assert "Custom Test Opportunities" not in out


class TestRenderInfoLines:
    """Tests for _render_info_lines (non-scored signposts)."""

    def test_no_info_lines(self, capsys):
        """Missing info_lines key produces no output. Mutant: a default info line in apps/handlers/audit/audit_display.py — killed."""
        out = _summary(capsys, {"naming": 100})
        assert "ⓘ" not in out

    def test_empty_message_skipped(self, capsys):
        """An entry with an empty message prints nothing. Mutant: the empty-message guard removed in apps/handlers/audit/audit_display.py — killed."""
        out = _summary(capsys, {"naming": 100}, info_lines=[{"standard": "json_structure", "message": ""}])
        assert "ⓘ" not in out

    def test_info_lines_rendered(self):
        """Each info line renders once, dimmed."""
        mock_con = MagicMock()
        audit_display._render_info_lines(
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

    def test_rendered_at_full_score(self, capsys):
        """A 100% branch still shows its info lines. Mutant: info lines gated on avg < 100 in apps/handlers/audit/audit_display.py — killed."""
        audit_result = {
            "branch": {"name": "mybranch"},
            "scores": {"naming": 100},
            "average": 100,
            "files_checked": 3,
            "info_lines": [{"standard": "json_structure", "message": "operator file: memory.config.json"}],
        }
        audit_display.print_branch_summary(audit_result)
        assert "ⓘ operator file: memory.config.json" in capsys.readouterr().out


class TestRenderDeprecatedPatterns:
    """The deprecated-patterns block, as the branch summary prints it."""

    def test_no_patterns(self, capsys):
        """Empty deprecated_patterns produces no output. Mutant: the empty guard removed in apps/handlers/audit/audit_display.py — killed."""
        out = _summary(capsys, {"naming": 100}, deprecated_patterns=[])
        assert "DEPRECATED PATTERNS" not in out

    def test_with_patterns(self, capsys):
        """Deprecated patterns render correctly. Mutant: the message line blanked in apps/handlers/audit/audit_display.py — killed."""
        patterns = [{"path": "/foo/DOCUMENTS", "message": "Rename DOCUMENTS/ to docs/"}]
        out = _summary(capsys, {"naming": 100}, deprecated_patterns=patterns)
        assert "DEPRECATED PATTERNS (1):" in out
        assert "⚠ /foo/DOCUMENTS" in out
        assert "→ Rename DOCUMENTS/ to docs/" in out

    def test_missing_key(self, capsys):
        """Missing deprecated_patterns key produces no output. Mutant: the empty guard removed in apps/handlers/audit/audit_display.py — killed."""
        out = _summary(capsys, {"naming": 100})
        assert "DEPRECATED PATTERNS" not in out


def _rendered(capsys, render, *args, **kwargs) -> str:
    """Everything *render* wrote to stdout while it ran, as one string.

    Calling a renderer and asserting nothing pins only that it did not raise,
    so a renderer that printed NOTHING AT ALL passed (no_oracle, 2026-09-07).
    The console is the real one, so stdout is where a render is observable.
    Drained first, so each assertion reads its own render.
    """
    capsys.readouterr()
    render(*args, **kwargs)
    return capsys.readouterr().out


class TestPrintIntrospection:
    """Tests for print_introspection."""

    def test_introspection_produces_output(self, capsys):
        """print_introspection names the module and its public API. Mutant: the title line blanked in apps/handlers/audit/audit_display.py — killed."""
        out = _rendered(capsys, audit_display.print_introspection)
        assert "audit_display Module" in out
        assert "print_branch_summary(" in out


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

    def test_basic_summary(self, capsys):
        """The summary renders for every score tier, and for a standard at 100.

        MERGED 2026-09-07 (FPLAN-0496, the DPLAN-0323 contested band). Four
        further rows called this same renderer with different numbers and
        asserted nothing: ``test_high_scores``, ``test_medium_scores``,
        ``test_low_scores`` and ``test_score_100_skipped_in_violations``. The
        icon each named in its docstring is a literal string choice no row
        checked, and a standard at 100 only skips a render branch. What the
        five rows really pinned together was "none of these shapes crashes the
        renderer", so the inputs move here and the claim is made once.

        Mutation-checked at the merge: a renderer that raises on any one of
        these tiers reds this test.
        Mutant: the branch name dropped from the header in apps/handlers/audit/audit_display.py — killed.
        """
        for scores, average in (
            ({"architecture": 90, "naming": 80}, 85),  # the baseline fixture
            ({"architecture": 95, "naming": 92}, 93),  # >= 90
            ({"architecture": 80, "naming": 76}, 78),  # 75-89
            ({"architecture": 50, "naming": 60}, 55),  # < 75
            ({"naming": 100, "meta": 90}, 95),  # a 100 skips its violation render
        ):
            rendered = _rendered(
                capsys, audit_display.print_branch_summary, self._make_audit_result(scores=scores, average=average)
            )

            assert "test_branch" in rendered, f"the branch was not named at {average}"
            assert str(average) in rendered, f"the overall {average} was not rendered"

    def test_the_header_states_what_it_measured_not_only_how_much(self, capsys):
        """The count is scoped out loud, because the corpus is not the branch.

        ``_collect_py_files`` walks ``apps/**/*.py`` and nothing else, so a bare
        "N files checked" beside a 100 invites the reader to conclude the branch
        is clean when a third of its Python was never opened. This asserts the
        SCOPE WORDS, not the number: a header that keeps the count and drops the
        qualifier is exactly the overclaim, and it would pass a count-only pin.
        Mutant: the corpus detail dropped from the header in apps/handlers/audit/audit_display.py — killed.
        """
        rendered = _rendered(capsys, audit_display.print_branch_summary, self._make_audit_result(files_checked=171))
        assert "171 files measured" in rendered
        assert "apps/ plus tests/" in rendered
        assert "test_*.py and conftest.py" in rendered

    def test_the_scope_words_are_not_hardcoded_around_the_count(self, capsys):
        """Negative control on the pin above: the number still has to be real.

        A header that printed the qualifier with a constant would satisfy every
        assertion above while reporting the wrong corpus size.
        Mutant: the corpus size defaulted to 171 in apps/handlers/audit/audit_display.py — killed.
        """
        rendered = _rendered(capsys, audit_display.print_branch_summary, self._make_audit_result(files_checked=3))
        assert "3 files measured" in rendered

    def test_post_check_crash_prints_even_at_a_perfect_score(self, capsys):
        """A crashed post-check reaches the CONSOLE on a branch scoring 100.

        Not red before the fix — audit_display already had the catch-all lane
        this leans on — but the fix depends on it: the crash deliberately
        leaves the file-lane score alone, so the standard usually still reads
        100, and the score-driven renderer skips every standard at 100. The
        catch-all violation lane is the only thing that prints it, so it is
        pinned here rather than assumed.
        Mutant: the catch-all lane reads no violations in apps/handlers/audit/audit_display.py — killed.
        """
        detail = (
            "log_structure post-check crashed on branch test_branch (TypeError: check_branch_post() "
            "got an unexpected keyword argument 'bypass_rules') — the branch's log_structure score "
            "of 100 comes from the file lane only and does NOT include this check"
        )
        result = self._make_audit_result(
            scores={"log_structure": 100},
            average=100,
            extra={
                "log_structure_violations": [
                    {"file": "log_structure post-check", "path": "/fake/path", "score": 100, "issues": [detail]}
                ]
            },
        )
        printed = _rendered(capsys, audit_display.print_branch_summary, result)

        assert "post-check crashed" in printed, "a 100 that excludes a check must say so on screen"
        assert "TypeError" in printed

    def test_odd_number_of_scores(self, capsys):
        """Odd number of scores renders last one alone. Mutant: the unpaired last score not printed in apps/handlers/audit/audit_display.py — killed."""
        result = self._make_audit_result(
            scores={
                "architecture": 90,
                "naming": 80,
                "meta": 70,
            },
            average=80,
        )

        rendered = _rendered(capsys, audit_display.print_branch_summary, result)

        # The third standard is the one a two-per-row renderer drops.
        assert "Meta" in rendered, "the odd standard was not rendered at all"

    def test_empty_scores(self, capsys):
        """Empty scores dict still renders overall. Mutant: Overall printed only when scores exist in apps/handlers/audit/audit_display.py — killed."""
        result = self._make_audit_result(scores={}, average=0)

        rendered = _rendered(capsys, audit_display.print_branch_summary, result)

        assert "Overall" in rendered, "a branch with no scores still owes an Overall line"

    def test_architecture_violations_displayed(self, capsys):
        """Architecture score < 100 triggers arch violation render. Mutant: the architecture renderer not called in apps/handlers/audit/audit_display.py — killed."""
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

        rendered = _rendered(capsys, audit_display.print_branch_summary, result)

        # The renderer strips the "Dir: " prefix and groups the failure under a
        # heading, so the check's own name is not what reaches the screen.
        assert "Missing directories" in rendered, "the failed check got no heading"
        assert "✗ apps" in rendered, "the directory that failed was not named"

    def test_standard_violations_displayed(self, capsys):
        """Standard with violations list gets rendered. Mutant: the scored violation list marked rendered but not printed in apps/handlers/audit/audit_display.py — killed."""
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

        rendered = _rendered(capsys, audit_display.print_branch_summary, result)

        assert "Bad name" in rendered, "the violation's own issue text was not rendered"

    def test_branch_level_failed_checks(self, capsys):
        """Failed checks but no violations list renders messages. Mutant: passing checks kept as findings in apps/handlers/audit/audit_display.py — killed."""
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

        rendered = _rendered(capsys, audit_display.print_branch_summary, result)

        assert "Unused function foo()" in rendered, "a failed check with no violations list went unrendered"
        assert "OK" not in rendered, "a PASSING check must not be rendered as a finding"

    def test_violations_not_in_scores_rendered(self, capsys):
        """Violation lists not in scores are caught defensively. Mutant: the catch-all lane reads no violations in apps/handlers/audit/audit_display.py — killed."""
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

        rendered = _rendered(capsys, audit_display.print_branch_summary, result)

        assert "Orphan violation" in rendered, "a violation list with no matching score was silently dropped"

    def test_type_errors_rendered(self, capsys):
        """Type errors section is rendered. Mutant: the type-error renderer not called in apps/handlers/audit/audit_display.py — killed."""
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

        rendered = _rendered(capsys, audit_display.print_branch_summary, result)

        assert "bad.py" in rendered, "the file carrying the type errors was not named"

    def test_test_map_rendered(self, capsys):
        """Test map section is rendered. Mutant: the test-map renderer not called in apps/handlers/audit/audit_display.py — killed."""
        result = self._make_audit_result(
            extra={
                "test_map": {
                    "total_functions": 5,
                    "tested_functions": 3,
                    "branch": "seedgo",
                },
            },
        )

        rendered = _rendered(capsys, audit_display.print_branch_summary, result)

        assert "5 public functions, 3 tested" in rendered, "the test-map counts were not rendered"

    def test_deprecated_patterns_rendered(self, capsys):
        """Deprecated patterns section is rendered. Mutant: the deprecated-pattern renderer not called in apps/handlers/audit/audit_display.py — killed."""
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

        rendered = _rendered(capsys, audit_display.print_branch_summary, result)

        assert "Rename to docs/" in rendered, "the deprecated-pattern message was not rendered"

    def test_system_averages_and_overall(self, capsys):
        """system_averages and overall_system_avg args accepted. Mutant: the branch name dropped from the header in apps/handlers/audit/audit_display.py — killed."""
        result = self._make_audit_result()

        rendered = _rendered(
            capsys,
            audit_display.print_branch_summary,
            result,
            system_averages={"naming": 85},
            overall_system_avg=87,
        )

        assert "test_branch" in rendered, "the branch summary rendered nothing at all"

    def test_no_bypass_label_travels_with_the_branch_score(self, capsys):
        """A --no-bypass summary says so. Mutant: no_bypass forced False in apps/handlers/audit/audit_display.py — killed."""
        printed = _rendered(
            capsys, audit_display.print_branch_summary, self._make_audit_result(), no_bypass=True
        ).upper()
        assert "BYPASSES DISABLED" in printed

    def test_normal_branch_summary_makes_no_bypass_claim(self, capsys):
        """Control: the label only when bypasses were disabled. Mutant: no_bypass forced True in apps/handlers/audit/audit_display.py — killed."""
        printed = _rendered(capsys, audit_display.print_branch_summary, self._make_audit_result()).upper()
        assert "BYPASSES DISABLED" not in printed


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

    @staticmethod
    def _rendered_lines(capsys, results: list, **kwargs) -> list:
        """Every line print_system_summary wrote to stdout, in order.

        The console is the real one and conftest pins its width at 200, so no
        pinned line here is long enough to be split by a wrap.
        """
        return _rendered(capsys, audit_display.print_system_summary, results, **kwargs).splitlines()

    def test_empty_results(self, capsys):
        """An empty fleet divides by no branches: zeros throughout, no improvement areas. Mutant: improvement areas always headed in apps/handlers/audit/audit_display.py — killed."""
        lines = self._rendered_lines(capsys, [])

        assert "  Total branches:        0" in lines
        assert "  Average compliance:    0%" in lines
        assert "  Type errors:           0" in lines
        assert "STANDARD AVERAGES:" in lines
        assert "TOP IMPROVEMENT AREAS:" not in lines

    def test_mixed_tiers(self, capsys):
        """A fleet spanning all three tiers renders, and so does an all-excellent one.

        MERGED 2026-09-07 (FPLAN-0496, the DPLAN-0323 contested band).
        ``test_all_excellent`` built a two-branch list at 95 and 92 and
        asserted nothing; the counting it named in its docstring is never
        checked, and the excellent branch below already walks that arm. Its
        input moves here so the all-one-tier shape is still executed rather
        than assumed to be covered.

        FPLAN-0509: it asserted nothing, so "renders" was the whole claim. Both
        lists now pin the tier counts they were chosen to exercise. Re-mutated:
        widening `excellent` to `average >= 96` reds it.
        Mutant: excellent read as average >= 96 in apps/handlers/audit/audit_display.py — killed.
        """
        cases = [
            (
                [
                    self._make_result("excellent", 95),
                    self._make_result("good", 82),
                    self._make_result("bad", 60),
                ],
                [
                    "  Total branches:        3",
                    "  Average compliance:    79%",
                    "  Branches ≥90%:         1",
                    "  Branches 75-89%:       1",
                    "  Branches <75%:         1",
                ],
            ),
            (
                [
                    self._make_result("a", 95),
                    self._make_result("b", 92),
                ],
                [
                    "  Total branches:        2",
                    "  Average compliance:    93%",
                    "  Branches ≥90%:         2",
                    "  Branches 75-89%:       0",
                    "  Branches <75%:         0",
                ],
            ),
        ]
        assert len(cases) == 2, "both the spread fleet and the merged all-excellent one must run"

        for results, expected in cases:
            lines = self._rendered_lines(capsys, results)
            for line in expected:
                assert line in lines, f"{line!r} missing from {lines!r}"

    def test_type_errors_in_summary(self, capsys):
        """The type-error total is the fleet sum, with the branches carrying it. Mutant: every branch counted as carrying errors in apps/handlers/audit/audit_display.py — killed."""
        lines = self._rendered_lines(
            capsys,
            [
                self._make_result("a", 85, type_errors=5),
                self._make_result("b", 90, type_errors=0),
            ],
        )

        assert "  Type errors:           5 (1 branches)" in lines

    def test_no_type_errors_green(self, capsys):
        """A clean fleet prints the bare zero, without the branch count. Mutant: the zero total takes the counted arm in apps/handlers/audit/audit_display.py — killed."""
        lines = self._rendered_lines(capsys, [self._make_result("a", 90)])

        assert "  Type errors:           0" in lines
        assert not [line for line in lines if line.startswith("  Type errors:") and "branches)" in line]

    def test_odd_standard_count(self, capsys):
        """An odd standard count renders the last one alone, at any tier of averages.

        MERGED 2026-09-07 (FPLAN-0496, the DPLAN-0323 contested band).
        ``test_standard_averages_icons`` was this same single-result shape with
        three standards at 95/80/50; the per-tier icons it named are literal
        string choices that cannot crash and were never asserted. Its scores
        move here, so the three-tier spread is still rendered.

        FPLAN-0509: the icons the merge note called "never asserted" are asserted
        here now, alongside the odd-one-out row. Re-mutated: stepping the pairing
        loop by 3 reds it, and so does moving the ✅ threshold to `>= 91`.
        Mutant: the pairing loop stepped by 3 in apps/handlers/audit/audit_display.py — killed.
        """
        cases = [
            (
                {"arch": 80, "naming": 85, "meta": 90},
                [
                    "  Arch             80% ⚠️    Meta             90% ✅",
                    "  Naming           85% ⚠️",
                ],
            ),
            (
                {"high": 95, "mid": 80, "low": 50},
                [
                    "  High             95% ✅    Low              50% ❌",
                    "  Mid              80% ⚠️",
                ],
            ),
        ]
        assert len(cases) == 2, "both the plain spread and the merged three-tier icon set must run"

        for scores, expected in cases:
            lines = self._rendered_lines(capsys, [self._make_result("a", 80, scores=scores)])
            paired, alone = expected
            assert paired in lines, f"{paired!r} missing from {lines!r}"
            assert alone in lines, f"the odd third standard did not render alone: {lines!r}"

    def test_top_improvement_areas(self, capsys):
        """The three worst standards are ranked, each with its own <75% branch count. Mutant: the count read as < 60 in apps/handlers/audit/audit_display.py — killed."""
        lines = self._rendered_lines(
            capsys,
            [
                self._make_result("a", 60, scores={"arch": 50, "naming": 70}),
                self._make_result("b", 80, scores={"arch": 90, "naming": 70}),
            ],
        )

        assert "TOP IMPROVEMENT AREAS:" in lines
        assert "  1. Arch            (avg: 70%, 1 branches <75%)" in lines
        assert "  2. Naming          (avg: 70%, 2 branches <75%)" in lines

    def test_no_bypass_label_travels_with_the_fleet_average(self, capsys):
        """The summary block carries the label itself. Mutant: no_bypass forced False in apps/handlers/audit/audit_display.py — killed."""
        printed = _rendered(
            capsys, audit_display.print_system_summary, [self._make_result("a", 95)], no_bypass=True
        ).upper()
        assert "BYPASSES DISABLED" in printed

    def test_normal_system_summary_makes_no_bypass_claim(self, capsys):
        """Control: a normal fleet summary carries no such label. Mutant: no_bypass forced True in apps/handlers/audit/audit_display.py — killed."""
        printed = _rendered(capsys, audit_display.print_system_summary, [self._make_result("a", 95)]).upper()
        assert "BYPASSES DISABLED" not in printed


# ===========================================================================
# BRANCH_AUDIT TESTS
# ===========================================================================


class TestDiscoverCheckers:
    """Tests for discover_checkers."""

    def test_discover_from_path(self, tmp_path):
        """Discovers *_check.py modules with check_module."""
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
        result = branch_audit.discover_checkers(standards_dir)
        assert "naming" in result

    def test_skip_without_check_functions(self, tmp_path):
        """Skips modules without check_module or check_branch."""
        standards_dir = tmp_path / "standards"
        standards_dir.mkdir()
        checker_file = standards_dir / "bad_check.py"
        checker_file.write_text("x = 42\n", encoding="utf-8")
        result = branch_audit.discover_checkers(standards_dir)
        assert "bad" not in result

    def test_skip_failing_load(self, tmp_path):
        """Skips modules that raise during exec_module."""
        standards_dir = tmp_path / "standards"
        standards_dir.mkdir()
        checker_file = standards_dir / "broken_check.py"
        checker_file.write_text("raise RuntimeError('broken')\n", encoding="utf-8")
        result = branch_audit.discover_checkers(standards_dir)
        assert "broken" not in result

    def test_empty_directory(self, tmp_path):
        """Empty standards dir returns empty dict."""
        standards_dir = tmp_path / "standards"
        standards_dir.mkdir()
        result = branch_audit.discover_checkers(standards_dir)
        assert result == {}

    def test_spec_none_skipped(self, tmp_path):
        """Files where spec_from_file_location returns None skipped."""
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
            result = branch_audit.discover_checkers(standards_dir)
        assert "valid" not in result

    def test_check_branch_function_discovered(self, tmp_path):
        """Modules with check_branch are discovered."""
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
        result = branch_audit.discover_checkers(standards_dir)
        assert "branch" in result


def _recording_checker(answer=None, scope: str = "all_files", include_init: bool = False) -> types.SimpleNamespace:
    """A per-file checker that records the NAME of every file it is handed.

    *answer* maps a file name to the result dict; the default passes everything
    at 100. ``seen`` is the record the corpus tests read.
    """
    seen: list = []

    def check_module(module_path, bypass_rules=None):
        name = Path(module_path).name
        seen.append(name)
        if answer is not None:
            return answer(name)
        return {"passed": True, "score": 100, "checks": [{"passed": True, "message": "OK"}]}

    return types.SimpleNamespace(
        AUDIT_SCOPE=scope, FILE_FILTER=None, INCLUDE_INIT_FILES=include_init, check_module=check_module, seen=seen
    )


def _audit_corpus(monkeypatch, root: Path, checkers: dict, files=()) -> dict:
    """audit_branch over a branch at *root* holding *files*, judged by *checkers*.

    The entry file is ``entry.py`` at the branch root, never written and outside
    apps/, so a file under apps/ reaches a checker only through the corpus.
    tmp_path lies under the system temp root, which is_throwaway_path drops
    wholesale; emptying the root list lets the real predicate judge each file.
    The diagnostics loader would run pyright over the branch; it is silenced
    here, and its own lane is pinned by test_diagnostics_checker_added.
    """
    monkeypatch.setattr(skip_dirs, "_get_temp_roots", lambda: [])
    monkeypatch.setattr(branch_audit, "discover_checkers", lambda pack_path=None: checkers)
    monkeypatch.setattr(branch_audit, "_load_diagnostics_checker", lambda: None)
    for rel in files:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text("pass", encoding="utf-8")
    branch = {"name": "corpus", "entry_file": str(root / "entry.py"), "path": str(root)}
    return branch_audit.audit_branch(branch, [])


def _checked(checker: types.SimpleNamespace) -> set:
    """The corpus file names a recording checker was handed, the entry file left out."""
    return set(checker.seen) - {"entry.py"}


class TestCollectPyFiles:
    """The corpus audit_branch walks: what reaches an all_files checker."""

    def test_no_apps_dir(self, tmp_path, monkeypatch):
        """No apps/ means an empty corpus, whatever sits at the root. Mutant: apps_dir read as the branch root in apps/handlers/audit/branch_audit.py — killed."""
        checker = _recording_checker()
        result = _audit_corpus(monkeypatch, tmp_path, {"naming": checker}, files=("setup.py",))
        assert result["files_checked"] == 0
        assert _checked(checker) == set()

    def test_collects_py_files(self, tmp_path, monkeypatch):
        """Collects .py from apps/, excluding __init__.py. Mutant: __init__.py always collected in apps/handlers/audit/branch_audit.py — killed."""
        checker = _recording_checker()
        files = ("apps/__init__.py", "apps/module.py", "apps/handlers/handler.py")
        _audit_corpus(monkeypatch, tmp_path, {"naming": checker}, files=files)
        names = _checked(checker)
        assert "module.py" in names
        assert "handler.py" in names
        assert "__init__.py" not in names

    def test_collects_init_files_when_requested(self, tmp_path, monkeypatch):
        """INCLUDE_INIT_FILES keeps __init__.py, for import checkers. Mutant: the init walk asked for no inits in apps/handlers/audit/branch_audit.py — killed."""
        checker = _recording_checker(include_init=True)
        _audit_corpus(monkeypatch, tmp_path, {"handlers": checker}, files=("apps/__init__.py", "apps/module.py"))
        names = _checked(checker)
        assert "module.py" in names
        assert "__init__.py" in names

    def test_respects_ignore_patterns(self, tmp_path, monkeypatch):
        """Files matching ignore patterns are excluded. Mutant: the ignore match discarded in apps/handlers/audit/branch_audit.py — killed."""
        # The real matcher over branch-relative paths: the tmp_path name cannot collide.
        monkeypatch.setattr(branch_audit.ignore_handler, "audit_ignore_match", real_audit_ignore_match)
        checker = _recording_checker()
        files = ("apps/module.py", "apps/integrations/google/driver.py", "apps/handlers/integrations/call.py")
        _audit_corpus(monkeypatch, tmp_path, {"naming": checker}, files=files)
        assert sorted(_checked(checker)) == ["call.py", "module.py"]

    def test_excludes_disabled_files(self, tmp_path, monkeypatch):
        """Files with (disabled) in the name are excluded. Mutant: the disabled-name test dropped in apps/handlers/audit/branch_audit.py — killed."""
        checker = _recording_checker()
        files = ("apps/module.py", "apps/dashboard_sync(disabled).py")
        _audit_corpus(monkeypatch, tmp_path, {"naming": checker}, files=files)
        names = _checked(checker)
        assert "module.py" in names
        assert "dashboard_sync(disabled).py" not in names

    def test_respects_seedgo_ignore_tools_dir(self, tmp_path, monkeypatch):
        """Files under apps/tools/ are excluded via the global .seedgoignore default. Mutant: .seedgoignore not consulted in apps/handlers/audit/branch_audit.py — killed."""
        checker = _recording_checker()
        _audit_corpus(monkeypatch, tmp_path, {"naming": checker}, files=("apps/module.py", "apps/tools/scratch.py"))
        names = _checked(checker)
        assert "module.py" in names
        assert "scratch.py" not in names


def _branch_level(result: dict) -> types.SimpleNamespace:
    """A branch-level checker whose whole-branch answer is *result*."""
    return types.SimpleNamespace(AUDIT_SCOPE="branch_level", check_branch=lambda branch_path, bypass_rules=None: result)


class TestExtractBranchLevelViolations:
    """A branch-level result's per-file findings, as audit_branch reports them."""

    def test_empty_result(self, tmp_path, monkeypatch):
        """Empty result reports no violations and no crash. Mutant: checks read without a default in apps/handlers/audit/branch_audit.py — killed."""
        result = _audit_corpus(monkeypatch, tmp_path, {"dead_code": _branch_level({})})
        assert result["dead_code_violations"] == []
        assert "error" not in result["results"]["dead_code"]

    def test_extracts_violations(self, tmp_path, monkeypatch):
        """Extracts violations from checks with list-type keys. Mutant: each file keeps only its last finding in apps/handlers/audit/branch_audit.py — killed."""
        found = {
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
        violations = _audit_corpus(monkeypatch, tmp_path, {"dead_code": _branch_level(found)})["dead_code_violations"]
        assert len(violations) == 1
        assert violations[0]["file"] == "/foo.py"
        assert len(violations[0]["issues"]) == 2

    def test_skips_non_list_keys(self, tmp_path, monkeypatch):
        """Skips standard keys (name, passed, message, score). Mutant: no key skipped in apps/handlers/audit/branch_audit.py — killed."""
        found = {
            "checks": [
                {
                    "name": "check",
                    "passed": True,
                    "message": "ok",
                    "score": 100,
                },
            ]
        }
        result = _audit_corpus(monkeypatch, tmp_path, {"dead_code": _branch_level(found)})
        assert result["dead_code_violations"] == []
        assert "error" not in result["results"]["dead_code"]

    def test_skips_items_without_file_key(self, tmp_path, monkeypatch):
        """Skips list items without a file key. Mutant: the file-key guard dropped in apps/handlers/audit/branch_audit.py — killed."""
        found = {
            "checks": [
                {
                    "name": "check",
                    "passed": False,
                    "message": "err",
                    "items": [{"name": "orphan"}],
                },
            ]
        }
        result = _audit_corpus(monkeypatch, tmp_path, {"dead_code": _branch_level(found)})
        assert result["dead_code_violations"] == []
        assert "error" not in result["results"]["dead_code"]

    def test_multiple_files(self, tmp_path, monkeypatch):
        """Groups violations by file path. Mutant: every finding grouped under one file in apps/handlers/audit/branch_audit.py — killed."""
        found = {
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
        violations = _audit_corpus(monkeypatch, tmp_path, {"dead_code": _branch_level(found)})["dead_code_violations"]
        assert len(violations) == 2
        files = {v["file"] for v in violations}
        assert "/a.py" in files
        assert "/b.py" in files


class TestRunAllFiles:
    """The all_files lane of audit_branch: every corpus file through one checker."""

    def test_basic_run(self, tmp_path, monkeypatch):
        """Basic run collects scores from passing checks. Mutant: each file's score recorded as 0 in apps/handlers/audit/branch_audit.py — killed."""
        checker = _recording_checker(
            lambda name: {"passed": True, "score": 90, "checks": [{"passed": True, "message": "OK"}]}
        )
        result = _audit_corpus(monkeypatch, tmp_path, {"naming": checker}, files=("apps/foo.py",))
        assert "foo.py" in _checked(checker)
        assert result["scores"]["naming"] == 90

    def test_checker_raises_exception(self, tmp_path, monkeypatch):
        """Checker that raises is skipped. Mutant: the per-file catch narrowed to KeyError in apps/handlers/audit/branch_audit.py — killed."""

        def boom(name):
            raise RuntimeError("boom")

        result = _audit_corpus(monkeypatch, tmp_path, {"naming": _recording_checker(boom)}, files=("apps/foo.py",))
        assert result["naming_violations"] == []
        assert result["scores"]["naming"] == 0

    def test_file_filter(self, tmp_path, monkeypatch):
        """FILE_FILTER skips non-matching files. Mutant: FILE_FILTER ignored in apps/handlers/audit/branch_audit.py — killed."""
        checker = _recording_checker()
        checker.FILE_FILTER = "handler"
        _audit_corpus(monkeypatch, tmp_path, {"naming": checker}, files=("apps/handler.py", "apps/module.py"))
        assert _checked(checker) == {"handler.py"}

    def test_a_declined_check_is_excluded_and_named(self, tmp_path, monkeypatch):
        """A file stands down on the declined field, never on its message's words. Mutant: declined files averaged in apps/handlers/audit/branch_audit.py — killed."""

        def answer(name):
            if name == "foo.py":
                return {
                    "passed": True,
                    "score": 100,
                    "checks": [{"passed": True, "declined": True, "message": "Not a naming target"}],
                }
            return {"passed": True, "score": 40, "checks": [{"passed": True, "message": "fine"}]}

        result = _audit_corpus(
            monkeypatch, tmp_path, {"naming": _recording_checker(answer)}, files=("apps/foo.py", "apps/bar.py")
        )
        assert result["scores"]["naming"] == 40
        assert result["declined"] == {"naming": ["apps/foo.py"]}

    def test_failing_checks_collected(self, tmp_path, monkeypatch):
        """Failing checks collected as violations. Mutant: failures kept only above score 50 in apps/handlers/audit/branch_audit.py — killed."""

        def answer(name):
            return {
                "passed": False,
                "score": 40,
                "checks": [
                    {"passed": False, "message": "Bad naming"},
                    {"passed": True, "message": "OK"},
                ],
            }

        result = _audit_corpus(monkeypatch, tmp_path, {"naming": _recording_checker(answer)}, files=("apps/bad.py",))
        violations = [v for v in result["naming_violations"] if v["file"] == "bad.py"]
        assert len(violations) == 1
        assert violations[0]["score"] == 40
        assert "Bad naming" in violations[0]["issues"]


class TestLoadDiagnosticsChecker:
    """Tests for _load_diagnostics_checker."""

    def test_path_not_exists(self):
        """Returns None when diagnostics file does not exist."""
        with patch("pathlib.Path.exists", return_value=False):
            result = branch_audit._load_diagnostics_checker()
        assert result is None

    def test_spec_none(self):
        """Returns None when spec_from_file_location is None."""
        with (
            patch("pathlib.Path.exists", return_value=True),
            patch(
                "importlib.util.spec_from_file_location",
                return_value=None,
            ),
        ):
            result = branch_audit._load_diagnostics_checker()
        assert result is None

    def test_exec_module_raises(self):
        """Returns None when exec_module raises."""
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
            result = branch_audit._load_diagnostics_checker()
        assert result is None

    def test_successful_load(self):
        """Returns module when loading succeeds."""
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
            result = branch_audit._load_diagnostics_checker()
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


def _real_module_checker(**hooks) -> types.SimpleNamespace:
    """A checker whose surface is REAL functions rather than MagicMocks.

    A MagicMock answers to any call signature, so a mock-based test can never
    pin the pipeline's actual calling convention: check_branch_post was called
    with bypass_rules= against an implementation that took one positional
    argument, and every mock in this file kept passing while the standard was
    dead in production. Contract tests use this instead.
    """
    checker = types.SimpleNamespace(
        AUDIT_SCOPE="entry_point",
        FILE_FILTER=None,
        INCLUDE_INIT_FILES=False,
        check_module=lambda module_path, bypass_rules=None: {"passed": True, "score": 100, "checks": []},
    )
    for name, fn in hooks.items():
        setattr(checker, name, fn)
    return checker


class TestAuditBranch:
    """Tests for audit_branch."""

    @pytest.fixture(autouse=True)
    def _no_diagnostics(self, monkeypatch):
        """The real diagnostics loader runs pyright over the branch; silenced here.

        Its lane is pinned by test_diagnostics_checker_added and
        test_diagnostics_not_duplicated, which install a loader that answers.
        scan_branch is already silenced by the module's autouse fixture.
        """
        monkeypatch.setattr(branch_audit, "_load_diagnostics_checker", lambda: None)

    def test_basic_audit(self, tmp_path, monkeypatch):
        """Basic audit with one entry-point checker."""
        branch, _ = _setup_branch(tmp_path)
        checker = _make_checker()
        monkeypatch.setattr(
            branch_audit,
            "discover_checkers",
            lambda pack_path=None: {"naming": checker},
        )

        result = branch_audit.audit_branch(branch, [])
        assert result["branch"] == branch
        assert "naming" in result["scores"]
        assert result["average"] == 100

    def test_branch_level_checker(self, tmp_path, monkeypatch):
        """Branch-level checker calls check_branch."""
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

        result = branch_audit.audit_branch(branch, [])
        assert result["scores"]["dead_code"] == 85

    def test_branch_level_checker_exception(self, tmp_path, monkeypatch):
        """Branch-level checker that raises produces score 0."""
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

        result = branch_audit.audit_branch(branch, [])
        assert result["scores"]["broken"] == 0
        assert "error" in result["results"]["broken"]

    def test_entry_point_checker_exception(self, tmp_path, monkeypatch):
        """Entry-point checker that raises produces score 0."""
        branch, _ = _setup_branch(tmp_path)
        checker = _make_checker()
        checker.check_module.side_effect = RuntimeError("crash")
        monkeypatch.setattr(
            branch_audit,
            "discover_checkers",
            lambda pack_path=None: {"naming": checker},
        )

        result = branch_audit.audit_branch(branch, [])
        assert result["scores"]["naming"] == 0
        assert "error" in result["results"]["naming"]

    def test_all_files_scope(self, tmp_path, monkeypatch):
        """all_files scope runs checker on every file."""
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

        result = branch_audit.audit_branch(branch, [])
        assert result["scores"]["naming"] == 80

    def test_all_files_with_violations(self, tmp_path, monkeypatch):
        """all_files scope with failing checks updates results."""
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

        result = branch_audit.audit_branch(branch, [])
        assert "naming_violations" in result

    def test_all_files_scope_include_init_files_opt_in(self, tmp_path, monkeypatch):
        """Checker with INCLUDE_INIT_FILES=True sees __init__.py; a normal checker does not."""
        branch, branch_path = _setup_branch(tmp_path)
        apps_dir = Path(branch_path) / "apps"
        (apps_dir / "__init__.py").write_text("pass", encoding="utf-8")

        import_checker = _make_checker(scope="all_files")
        import_checker.INCLUDE_INIT_FILES = True
        normal_checker = _make_checker(scope="all_files")

        # tmp_path lives under the system temp dir, which is_throwaway_path
        # filters out wholesale — empty its root list so the real predicate
        # sees the fixture's files, same as it would for a real branch on disk.
        monkeypatch.setattr(skip_dirs, "_get_temp_roots", lambda: [])
        monkeypatch.setattr(
            branch_audit,
            "discover_checkers",
            lambda pack_path=None: {"handlers": import_checker, "naming": normal_checker},
        )

        branch_audit.audit_branch(branch, [])

        import_checked_names = {Path(c.args[0]).name for c in import_checker.check_module.call_args_list}
        normal_checked_names = {Path(c.args[0]).name for c in normal_checker.check_module.call_args_list}
        assert "__init__.py" in import_checked_names
        assert "__init__.py" not in normal_checked_names

    def test_dynamic_post_check(self, tmp_path, monkeypatch):
        """check_branch_post discovered and called."""
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

        result = branch_audit.audit_branch(branch, [])
        # Post check: (100 + 50) / 2 = 75
        assert result["scores"]["naming"] == 75
        assert len(result["naming_violations"]) == 1

    def test_post_check_raises_exception(self, tmp_path, monkeypatch):
        """check_branch_post that raises is caught."""
        branch, _ = _setup_branch(tmp_path)
        checker = _make_checker(has_post=True)
        checker.check_branch_post.side_effect = RuntimeError("fail")
        monkeypatch.setattr(
            branch_audit,
            "discover_checkers",
            lambda pack_path=None: {"naming": checker},
        )

        result = branch_audit.audit_branch(branch, [])
        assert result["scores"]["naming"] == 100

    def test_post_check_crash_is_attributable_in_output(self, tmp_path, monkeypatch):
        """A crashed post-check reaches the audit OUTPUT, naming checker, branch and error.

        The lane used to swallow the exception into logger.info(): every audit
        printed a clean score while a piece of the measurement had not run at
        all, and nothing in the output said so. A failure only a log knows
        about is indistinguishable from a success — that is what this pins.
        """
        branch, _ = _setup_branch(tmp_path)
        checker = _make_checker(has_post=True)
        checker.check_branch_post.side_effect = RuntimeError("boom")
        monkeypatch.setattr(branch_audit, "discover_checkers", lambda pack_path=None: {"naming": checker})

        result = branch_audit.audit_branch(branch, [])

        crashes = [v for v in result["naming_violations"] if "post-check" in v.get("message", "").lower()]
        assert crashes, "a crashed post-check must surface in the audit output, not only in a log line"
        message = crashes[0]["message"]
        assert "naming" in message, "which checker crashed"
        assert "mybranch" in message, "on which branch"
        assert "RuntimeError" in message and "boom" in message, "with which error"
        failed_checks = [c for c in result["results"]["naming"].get("checks", []) if not c.get("passed", True)]
        assert any("post-check" in c.get("message", "").lower() for c in failed_checks), (
            "same doctrine as the branch-level lane: the number arrives with its reason attached"
        )

    def test_post_check_contract_real_signature_is_invoked(self, tmp_path, monkeypatch):
        """The pipeline's actual calling convention, pinned with a REAL function.

        Every existing post-check test uses a MagicMock, which accepts any
        signature — so none of them could ever catch the mismatch that killed
        this lane in production. A real function object can.
        """
        branch, branch_path = _setup_branch(tmp_path)
        seen: list = []

        def check_branch_post(branch_path, bypass_rules=None):
            seen.append((branch_path, bypass_rules))
            return ([{"path": "/extra.py", "score": 0, "issues": ["Extra issue"]}], [50])

        checker = _real_module_checker(check_branch_post=check_branch_post)
        monkeypatch.setattr(branch_audit, "discover_checkers", lambda pack_path=None: {"naming": checker})

        result = branch_audit.audit_branch(branch, ["some-rule"])

        assert seen == [(str(branch_path), ["some-rule"])], "branch path positionally, bypass_rules by keyword"
        assert result["scores"]["naming"] == 75, "(100 + 50) / 2 — the post score blends"
        assert len(result["naming_violations"]) == 1

    def test_post_check_wrong_signature_fails_loudly(self, tmp_path, monkeypatch):
        """The live defect reproduced: a post-check that does not accept bypass_rules.

        log_structure_check shipped exactly this signature for months. The
        pipeline raised TypeError on every branch on every run and the bare
        except turned it into silence — the standard simply stopped running
        and no audit ever said so.
        """
        branch, _ = _setup_branch(tmp_path)

        def check_branch_post(branch_path):  # the pre-fix log_structure signature
            return ([], [50])

        checker = _real_module_checker(check_branch_post=check_branch_post)
        monkeypatch.setattr(branch_audit, "discover_checkers", lambda pack_path=None: {"naming": checker})

        result = branch_audit.audit_branch(branch, [])

        crashes = [v for v in result["naming_violations"] if "post-check" in v.get("message", "").lower()]
        assert crashes, "a signature mismatch must be loud — it means the standard did not run"
        assert "TypeError" in crashes[0]["message"]
        assert "bypass_rules" in crashes[0]["message"], "the report must name the argument that did not fit"
        assert result["scores"]["naming"] == 100, "a checker's own crash must not invent a number for the branch"

    def test_info_channel_collected_and_never_scored(self, tmp_path, monkeypatch):
        """check_branch_info lines reach output without touching the score."""
        branch, _ = _setup_branch(tmp_path)
        checker = _make_checker(has_info=True, info_result=["custom_config: cadence_config.json"])
        monkeypatch.setattr(
            branch_audit,
            "discover_checkers",
            lambda pack_path=None: {"naming": checker},
        )

        result = branch_audit.audit_branch(branch, [])
        assert result["info_lines"] == [{"standard": "naming", "message": "custom_config: cadence_config.json"}]
        assert result["scores"]["naming"] == 100
        assert result["average"] == 100

    def test_info_check_raises_is_caught(self, tmp_path, monkeypatch):
        """check_branch_info that raises leaves the audit intact."""
        branch, _ = _setup_branch(tmp_path)
        checker = _make_checker(has_info=True)
        checker.check_branch_info.side_effect = RuntimeError("fail")
        monkeypatch.setattr(
            branch_audit,
            "discover_checkers",
            lambda pack_path=None: {"naming": checker},
        )

        result = branch_audit.audit_branch(branch, [])
        assert result["info_lines"] == []
        assert result["scores"]["naming"] == 100

    def test_observe_lane_runs_with_bypass_rules_and_records(self, tmp_path, monkeypatch):
        """check_branch_observe runs on every audit and its readings reach the output.

        Driven by a REAL function, so the signature the pipeline uses is
        pinned by execution rather than by a mock that accepts anything.
        """
        branch, branch_path = _setup_branch(tmp_path)
        seen: list = []

        def check_branch_observe(branch_path, bypass_rules=None):
            seen.append((branch_path, bypass_rules))
            return [{"standard": "naming", "would_be_score": 50, "observed_at": "2026-08-14T00:00:00"}]

        checker = _real_module_checker(check_branch_observe=check_branch_observe)
        monkeypatch.setattr(branch_audit, "discover_checkers", lambda pack_path=None: {"naming": checker})

        result = branch_audit.audit_branch(branch, ["some-rule"])

        assert seen == [(str(branch_path), ["some-rule"])]
        assert result["observations"] == [
            {"standard": "naming", "would_be_score": 50, "observed_at": "2026-08-14T00:00:00"}
        ]

    def test_observe_lane_moves_no_score(self, tmp_path, monkeypatch):
        """Same branch, audited with and without the observe lane — identical numbers.

        This observation was de-scored because it reads live log files, so a
        branch's number moved with no code change. Observe mode is only
        honest if the lane's presence is invisible to every score.
        """
        branch, _ = _setup_branch(tmp_path)

        without = _real_module_checker()
        monkeypatch.setattr(branch_audit, "discover_checkers", lambda pack_path=None: {"log_structure": without})
        baseline = branch_audit.audit_branch(branch, [])

        def check_branch_observe(branch_path, bypass_rules=None):
            return [{"standard": "log_structure", "would_be_score": 50, "local_logs": 3, "system_logs": 0}]

        with_lane = _real_module_checker(check_branch_observe=check_branch_observe)
        monkeypatch.setattr(branch_audit, "discover_checkers", lambda pack_path=None: {"log_structure": with_lane})
        observed = branch_audit.audit_branch(branch, [])

        assert observed["observations"], "the lane really ran — otherwise this proves nothing"
        assert observed["scores"] == baseline["scores"]
        assert observed["scores"]["log_structure"] == baseline["scores"]["log_structure"]
        assert observed["average"] == baseline["average"]
        assert observed["log_structure_violations"] == baseline["log_structure_violations"]

    def test_observe_lane_crash_is_attributable_and_still_scoreless(self, tmp_path, monkeypatch):
        """A broken observe lane says so — and still cannot touch a score."""
        branch, _ = _setup_branch(tmp_path)

        def check_branch_observe(branch_path, bypass_rules=None):
            raise RuntimeError("observe boom")

        checker = _real_module_checker(check_branch_observe=check_branch_observe)
        monkeypatch.setattr(branch_audit, "discover_checkers", lambda pack_path=None: {"naming": checker})

        result = branch_audit.audit_branch(branch, [])

        errors = [o for o in result["observations"] if o.get("error")]
        assert errors, "a crashed observe lane must be visible in the reading, not silently absent"
        assert errors[0]["standard"] == "naming"
        assert "RuntimeError" in errors[0]["error"] and "observe boom" in errors[0]["error"]
        assert result["scores"]["naming"] == 100
        assert result["average"] == 100

    def test_checker_without_info_hook_skipped(self, tmp_path, monkeypatch):
        """A checker with no check_branch_info contributes no info lines."""
        branch, _ = _setup_branch(tmp_path)
        monkeypatch.setattr(
            branch_audit,
            "discover_checkers",
            lambda pack_path=None: {"naming": _make_checker()},
        )

        assert branch_audit.audit_branch(branch, [])["info_lines"] == []

    def test_diagnostics_checker_added(self, tmp_path, monkeypatch):
        """Diagnostics checker loaded and added."""
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

        result = branch_audit.audit_branch(branch, [])
        assert "diagnostics" in result["scores"]

    def test_deprecated_documents_dir(self, tmp_path, monkeypatch):
        """DOCUMENTS/ directory detected as deprecated."""
        branch, branch_path = _setup_branch(tmp_path)
        (Path(branch_path) / "DOCUMENTS").mkdir()

        monkeypatch.setattr(
            branch_audit,
            "discover_checkers",
            lambda pack_path=None: {},
        )

        result = branch_audit.audit_branch(branch, [])
        assert len(result["deprecated_patterns"]) == 1
        dep = result["deprecated_patterns"][0]
        assert dep["old"] == "DOCUMENTS/"

    def test_no_deprecated_without_documents(self, tmp_path, monkeypatch):
        """No deprecated patterns without DOCUMENTS/."""
        branch, _ = _setup_branch(tmp_path)
        monkeypatch.setattr(
            branch_audit,
            "discover_checkers",
            lambda pack_path=None: {},
        )

        result = branch_audit.audit_branch(branch, [])
        assert result["deprecated_patterns"] == []

    def test_scan_branch_exception(self, tmp_path, monkeypatch):
        """scan_branch exception caught, test_map is None."""
        branch, _ = _setup_branch(tmp_path)
        monkeypatch.setattr(
            branch_audit,
            "discover_checkers",
            lambda pack_path=None: {},
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
            "scan_branch",
            MagicMock(return_value=scan_result),
        )

        result = branch_audit.audit_branch(branch, [])
        assert result["test_map"] == scan_result

    def test_no_checkers_zero_average(self, tmp_path, monkeypatch):
        """No checkers returns average 0."""
        branch, _ = _setup_branch(tmp_path)
        monkeypatch.setattr(
            branch_audit,
            "discover_checkers",
            lambda pack_path=None: {},
        )

        result = branch_audit.audit_branch(branch, [])
        assert result["average"] == 0

    def test_implicit_branch_level(self, tmp_path, monkeypatch):
        """Checker without check_module treated as branch-level."""
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

        result = branch_audit.audit_branch(branch, [])
        assert result["scores"]["implicit"] == 75

    def test_pack_path_forwarded(self, tmp_path, monkeypatch):
        """pack_path argument forwarded to discover_checkers."""
        branch, _ = _setup_branch(tmp_path)
        captured: dict = {}

        def mock_discover(pack_path=None):
            """Capture the pack_path argument."""
            captured["value"] = pack_path
            return {}

        monkeypatch.setattr(branch_audit, "discover_checkers", mock_discover)

        pack = tmp_path / "custom_standards"
        branch_audit.audit_branch(branch, [], pack_path=pack)
        assert captured["value"] == pack

    def test_diagnostics_not_duplicated(self, tmp_path, monkeypatch):
        """Existing diagnostics not overwritten by loader."""
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

        result = branch_audit.audit_branch(branch, [])
        assert result["scores"]["diagnostics"] == 80

    def test_branch_level_violations_extraction(self, tmp_path, monkeypatch):
        """Branch-level results have violations extracted."""
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

        result = branch_audit.audit_branch(branch, [])
        assert len(result["dead_code_violations"]) == 1

    def test_output_diagnostics_fields(self, tmp_path, monkeypatch):
        """Output includes type_errors and type_error_files."""
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

        result = branch_audit.audit_branch(branch, [])
        assert result["type_errors"] == 3
        assert result["type_error_files"] == [{"file": "a.py", "errors": 3}]

    def test_post_check_empty_scores(self, tmp_path, monkeypatch):
        """Post-check with empty scores does not change score."""
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

        result = branch_audit.audit_branch(branch, [])
        assert result["scores"]["naming"] == 100
