# =================== AIPass ====================
# Name: test_coverage_audit_display.py
# Description: audit coverage, render phase: the branch and system summaries audit_display prints
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-08
# =============================================

"""Tests for apps/handlers/audit/audit_display.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that audit_display.py parses and imports
# seedgo: no-test-needed(constant) — _FLEET_STATE_STYLE's colour names and _MAX_NAMED_RERUNS' value

import pytest
from rich.text import Text

from aipass.seedgo.apps.handlers.audit import audit_display

pytestmark = pytest.mark.usefixtures("coverage_audit_seams")


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

    def test_info_lines_rendered(self, capsys, monkeypatch):
        """Each info line renders once and dimmed, through the branch summary a user reaches.

        It called the private renderer on a mocked console (seedgo, fleet green
        leg 5). The dim is read per character off the real console's own recording
        (seedgo, fleet green leg 6). Mutants: the info line printed twice — killed;
        the dim dropped — killed.
        """
        console = audit_display.console
        monkeypatch.setattr(console, "record", True)
        console.export_text(clear=True)
        out = _summary(
            capsys,
            {"naming": 100},
            info_lines=[
                {"standard": "json_structure", "message": "custom_config: cadence_config.json"},
                {"standard": "json_structure", "message": "second line"},
            ],
        )
        lines = out.splitlines()
        assert [line for line in lines if "ⓘ" in line] == ["  ⓘ custom_config: cadence_config.json", "  ⓘ second line"]
        recorded = [Text.from_ansi(line) for line in console.export_text(styles=True, clear=True).splitlines()]
        info = [line for line in recorded if "ⓘ" in line.plain]
        dims = {line.get_style_at_offset(console, i).dim for line in info for i in range(2, len(line.plain))}
        assert dims == {True}

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

    def test_the_branch_name_heads_the_summary(self, capsys):
        """The summary names its branch.

        It also passed system_averages and overall_system_avg, which the product
        never read; both were dropped (seedgo, fleet green leg 8).
        Mutant: the branch name dropped from the header in audit_display.py — killed.
        """
        result = self._make_audit_result()

        rendered = _rendered(capsys, audit_display.print_branch_summary, result)

        assert "test_branch" in rendered, "the branch summary rendered nothing at all"

    def test_no_bypass_label_travels_with_the_branch_score(self, capsys):
        """A --no-bypass summary says so: the score alone reads as a regression.

        Mutant: no_bypass forced False in apps/handlers/audit/audit_display.py — killed.
        """
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
