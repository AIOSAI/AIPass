# =================== META ====================
# Name: test_coverage_proof_diagnostics.py
# Description: Line-coverage tests for plugin_integrity.py and diagnostics_check.py
# Version: 1.2.1
# Created: 2026-04-26
# Modified: 2026-10-24
# =============================================

"""Tests for apps/handlers/aipass_proof/plugin_integrity.py and apps/handlers/diagnostics/diagnostics_check.py."""

# Coverage tests for the two handlers, reached through their public doors:
# plugin_integrity.scan() and diagnostics_check.check_branch(), check_file(),
# check_directory(), should_ignore_file() and format_summary(). Each synthetic
# source below is written into a scanned target module, so every helper is
# judged by the finding scan() reports for it, not by a direct call.

# The declared pass — what is NOT tested here, and what covers it instead:

import json
import subprocess
import textwrap

from pathlib import Path
from unittest.mock import MagicMock, patch

from aipass.seedgo.apps.handlers.aipass_proof import plugin_integrity
from aipass.seedgo.apps.handlers.aipass_proof.plugin_integrity import scan
from aipass.seedgo.apps.handlers.bypass import ignore_handler as real_ignore_handler
from aipass.seedgo.apps.handlers.diagnostics import diagnostics_check
from aipass.seedgo.apps.handlers.diagnostics.diagnostics_check import (
    check_branch,
    check_directory,
    check_file,
    format_summary,
    should_ignore_file,
)


# ---------------------------------------------------------------------------
# Helpers -- a scanned seedgo tree under tmp_path
# ---------------------------------------------------------------------------


def _pack(tmp_path: Path, names: tuple[str, ...] = ("zz_special",)) -> Path:
    """A standards pack under tmp_path's apps/handlers/, one *_check.py per name."""
    pack_dir = tmp_path / "apps" / "handlers" / "aipass_standards"
    pack_dir.mkdir(parents=True, exist_ok=True)
    for name in names:
        (pack_dir / f"{name}_check.py").write_text("pass", encoding="utf-8")
    return pack_dir


def _module(result: dict, label: str = "standards_audit.py") -> dict:
    """scan()'s result for one target module, by label."""
    return next(m for m in result["modules"] if m["label"] == label)


def _findings(tmp_path: Path, source: str, names: tuple[str, ...] = ("zz_special",)) -> list[dict]:
    """scan()'s findings for a standards_audit.py holding *source*, in a pack of *names*."""
    pack_dir = _pack(tmp_path, names)
    modules_dir = tmp_path / "apps" / "modules"
    modules_dir.mkdir(parents=True, exist_ok=True)
    (modules_dir / "standards_audit.py").write_text(textwrap.dedent(source), encoding="utf-8")
    return _module(plugin_integrity.scan(pack_dir))["findings"]


def _kinds(findings: list[dict]) -> list[str]:
    """The kind of every finding, in order."""
    return [f["kind"] for f in findings]


# ===========================================================================
# PLUGIN INTEGRITY -- the target modules, through scan()
# ===========================================================================


class TestResolveTargetModules:
    """The five target modules scan() reports on."""

    def test_returns_five_modules(self, tmp_path):
        """Target module list always has five entries. Mutant: seedgo.py dropped from the targets in apps/handlers/aipass_proof/plugin_integrity.py — killed."""
        result = plugin_integrity.scan(_pack(tmp_path, ()))
        assert len(result["modules"]) == 5

    def test_labels_correct(self, tmp_path):
        """Target module labels match expected file names. Mutant: seedgo.py dropped from the targets in apps/handlers/aipass_proof/plugin_integrity.py — killed."""
        result = plugin_integrity.scan(_pack(tmp_path, ()))
        labels = [m["label"] for m in result["modules"]]
        assert "standards_audit.py" in labels
        assert "branch_audit.py" in labels
        assert "audit_display.py" in labels
        assert "standards_query.py" in labels
        assert "seedgo.py" in labels

    def test_cosmetic_flag(self, tmp_path):
        """audit_display.py is marked cosmetic; others are not. Mutant: standards_audit.py marked cosmetic in apps/handlers/aipass_proof/plugin_integrity.py — killed."""
        result = plugin_integrity.scan(_pack(tmp_path, ()))
        cosmetic_map = {m["label"]: m["cosmetic_module"] for m in result["modules"]}
        assert cosmetic_map["audit_display.py"] is True
        assert cosmetic_map["standards_audit.py"] is False


# ===========================================================================
# PLUGIN INTEGRITY -- standard name discovery, through scan()
# ===========================================================================


class TestDiscoverStandardNames:
    """The standard names scan() discovers from a pack."""

    def test_nonexistent_directory(self, tmp_path):
        """Returns empty list for nonexistent directory. Mutant: a missing pack answers a name in apps/handlers/aipass_proof/plugin_integrity.py — killed."""
        result = plugin_integrity.scan(tmp_path / "missing")
        assert result["standard_names"] == []

    def test_no_check_files(self, tmp_path):
        """Returns empty list when directory has no *_check.py files. Mutant: every *.py read as a check in apps/handlers/aipass_proof/plugin_integrity.py — killed."""
        pack_dir = _pack(tmp_path, ())
        (pack_dir / "readme.py").write_text("pass", encoding="utf-8")
        result = plugin_integrity.scan(pack_dir)
        assert result["standard_names"] == []

    def test_discovers_names(self, tmp_path):
        """Discovers standard names from *_check.py filenames. Mutant: the _check suffix kept in apps/handlers/aipass_proof/plugin_integrity.py — killed."""
        result = plugin_integrity.scan(_pack(tmp_path, ("meta", "naming", "cli")))
        assert sorted(result["standard_names"]) == ["cli", "meta", "naming"]


# ===========================================================================
# PLUGIN INTEGRITY -- AST helpers, through a finding's context and filters
# ===========================================================================


class TestEnclosingContext:
    """The context a finding names."""

    def test_module_level(self, tmp_path):
        """A module-level literal reads '<module level>'. Mutant: the module-level answer emptied in apps/handlers/aipass_proof/plugin_integrity.py — killed."""
        findings = _findings(tmp_path, 'x = "zz_special"\n')
        assert [f["context"] for f in findings] == ["<module level>"]

    def test_inside_function(self, tmp_path):
        """A literal inside a def names the function. Mutant: the def context spelled without 'def' in apps/handlers/aipass_proof/plugin_integrity.py — killed."""
        findings = _findings(tmp_path, 'def my_func():\n    x = "zz_special"\n')
        assert "def my_func()" in findings[0]["context"]

    def test_inside_class_and_method(self, tmp_path):
        """A literal in a method names class > method. Mutant: the class dropped from the context in apps/handlers/aipass_proof/plugin_integrity.py — killed."""
        source = 'class MyClass:\n    def do_stuff(self):\n        x = "zz_special"\n'
        result = _findings(tmp_path, source)[0]["context"]
        assert "class MyClass" in result
        assert "def do_stuff()" in result

    def test_inside_async_function(self, tmp_path):
        """A literal in an async def names it. Mutant: AsyncFunctionDef not read as a def in apps/handlers/aipass_proof/plugin_integrity.py — killed."""
        findings = _findings(tmp_path, 'async def async_work():\n    x = "zz_special"\n')
        assert "def async_work()" in findings[0]["context"]


class TestIsDocstring:
    """A docstring naming a standard is not a finding."""

    def test_actual_docstring(self, tmp_path):
        """Detects module-level docstring. Mutant: no docstring recognised in apps/handlers/aipass_proof/plugin_integrity.py — killed."""
        assert _findings(tmp_path, '"""zz_special"""\nx = 1\n') == []

    def test_non_docstring(self, tmp_path):
        """Regular string literal is not a docstring. Mutant: every literal read as a docstring in apps/handlers/aipass_proof/plugin_integrity.py — killed."""
        assert _kinds(_findings(tmp_path, 'x = "zz_special"\n')) == ["ast_string_literal"]

    def test_function_docstring(self, tmp_path):
        """Detects function-level docstring. Mutant: no docstring recognised in apps/handlers/aipass_proof/plugin_integrity.py — killed."""
        assert _findings(tmp_path, 'def foo():\n    """zz_special"""\n    pass\n') == []


class TestIsDisplayString:
    """A standard name in display text is not a finding."""

    def test_inside_fstring(self, tmp_path):
        """String inside f-string is display text. Mutant: the f-string acquittal dropped in apps/handlers/aipass_proof/plugin_integrity.py — killed."""
        assert _findings(tmp_path, 'x = f"zz_special{y}"\n') == []

    def test_print_call(self, tmp_path):
        """String passed to console.print() is display text. Mutant: 'print' dropped from the display calls in apps/handlers/aipass_proof/plugin_integrity.py — killed."""
        assert _findings(tmp_path, 'console.print("zz_special")\n') == []

    def test_logger_info_call(self, tmp_path):
        """String passed to logger.info() is display text. Mutant: 'info' dropped from the display calls in apps/handlers/aipass_proof/plugin_integrity.py — killed."""
        assert _findings(tmp_path, 'logger.info("zz_special")\n') == []

    def test_logger_error_call(self, tmp_path):
        """String passed to logger.error() is display text. Mutant: 'error' dropped from the display methods in apps/handlers/aipass_proof/plugin_integrity.py — killed."""
        assert _findings(tmp_path, 'logger.error("zz_special")\n') == []

    def test_logger_warning_call(self, tmp_path):
        """String passed to logger.warning() is display text. Mutant: 'warning' dropped from the display methods in apps/handlers/aipass_proof/plugin_integrity.py — killed."""
        assert _findings(tmp_path, 'logger.warning("zz_special")\n') == []

    def test_logger_debug_call(self, tmp_path):
        """String passed to logger.debug() is display text. Mutant: 'debug' dropped from the display calls in apps/handlers/aipass_proof/plugin_integrity.py — killed."""
        assert _findings(tmp_path, 'logger.debug("zz_special")\n') == []

    def test_header_name_call(self, tmp_path):
        """String passed to header() function call is display text. Mutant: 'header' dropped from the display functions in apps/handlers/aipass_proof/plugin_integrity.py — killed."""
        assert _findings(tmp_path, 'header("zz_special")\n') == []

    def test_error_name_call(self, tmp_path):
        """String passed to error() function call is display text. Mutant: 'error' dropped from the display functions in apps/handlers/aipass_proof/plugin_integrity.py — killed."""
        assert _findings(tmp_path, 'error("zz_special")\n') == []

    def test_warning_name_call(self, tmp_path):
        """String passed to warning() function call is display text. Mutant: 'warning' dropped from the display functions in apps/handlers/aipass_proof/plugin_integrity.py — killed."""
        assert _findings(tmp_path, 'warning("zz_special")\n') == []

    def test_keyword_arg_in_print_call(self, tmp_path):
        """Keyword arg value inside console.print() is display text. Mutant: 'print' dropped from the keyword display calls in apps/handlers/aipass_proof/plugin_integrity.py — killed."""
        assert _findings(tmp_path, 'console.print(style="zz_special")\n') == []

    def test_keyword_arg_in_log_operation(self, tmp_path):
        """Keyword arg value inside .log_operation() is display text. Mutant: 'log_operation' dropped in apps/handlers/aipass_proof/plugin_integrity.py — killed."""
        assert _findings(tmp_path, 'json_handler.log_operation(data="zz_special")\n') == []

    def test_keyword_arg_in_header_call(self, tmp_path):
        """Keyword arg value inside header() call is display text. Mutant: 'header' dropped from the keyword display functions in apps/handlers/aipass_proof/plugin_integrity.py — killed."""
        assert _findings(tmp_path, 'header(title="zz_special")\n') == []

    def test_keyword_arg_in_error_call(self, tmp_path):
        """Keyword arg value inside error() call is display text. Mutant: 'error' dropped from the keyword display functions in apps/handlers/aipass_proof/plugin_integrity.py — killed."""
        assert _findings(tmp_path, 'error(msg="zz_special")\n') == []

    def test_keyword_arg_in_warning_call(self, tmp_path):
        """Keyword arg value inside warning() call is display text. Mutant: 'warning' dropped from the keyword display functions in apps/handlers/aipass_proof/plugin_integrity.py — killed."""
        assert _findings(tmp_path, 'warning(msg="zz_special")\n') == []

    def test_non_display_context(self, tmp_path):
        """String in normal assignment context is not display text. Mutant: every literal read as display text in apps/handlers/aipass_proof/plugin_integrity.py — killed."""
        assert _kinds(_findings(tmp_path, 'label = "zz_special"\n')) == ["ast_string_literal"]

    def test_keyword_arg_in_non_display_call(self, tmp_path):
        """Keyword arg value in a non-display call is not display text. Mutant: every literal read as display text in apps/handlers/aipass_proof/plugin_integrity.py — killed."""
        assert _kinds(_findings(tmp_path, 'do_work(name="zz_special")\n')) == ["ast_string_literal"]


class TestIsDictKeyAccess:
    """A standard name used as a dict key is not a finding."""

    def test_get_call(self, tmp_path):
        """result.get('key') is dict key access. Mutant: .get not read as key access in apps/handlers/aipass_proof/plugin_integrity.py — killed."""
        assert _findings(tmp_path, 'value = result.get("zz_special")\n') == []

    def test_subscript(self, tmp_path):
        """result['key'] is dict key access. Mutant: a subscript not read as key access in apps/handlers/aipass_proof/plugin_integrity.py — killed."""
        assert _findings(tmp_path, 'value = result["zz_special"]\n') == []

    def test_non_get_attribute_call(self, tmp_path):
        """result.append('key') is not dict key access. Mutant: every method call read as key access in apps/handlers/aipass_proof/plugin_integrity.py — killed."""
        assert _kinds(_findings(tmp_path, 'result.append("zz_special")\n')) == ["ast_string_literal"]

    def test_plain_function_call(self, tmp_path):
        """do_work('key') is not dict key access. Mutant: every call read as key access in apps/handlers/aipass_proof/plugin_integrity.py — killed."""
        assert _kinds(_findings(tmp_path, 'do_work("zz_special")\n')) == ["ast_string_literal"]


# ===========================================================================
# PLUGIN INTEGRITY -- the AST scanner, through scan()
# ===========================================================================


class TestScanFileAst:
    """What the AST half of scan() reports."""

    def test_clean_file(self, tmp_path):
        """File with no standard name references returns empty."""
        result = _findings(tmp_path, 'x = "hello"\n', ("meta", "naming"))
        assert result == []

    def test_syntax_error_file(self, tmp_path):
        """File with syntax error returns empty and does not crash. Mutant: the SyntaxError re-raised in apps/handlers/aipass_proof/plugin_integrity.py — killed."""
        result = _findings(tmp_path, "def foo(\n", ("meta",))
        assert result == []

    def test_finds_hardcoded_standard_name(self, tmp_path):
        """Detects non-ambiguous standard name as string literal. Mutant: the name-set check inverted in apps/handlers/aipass_proof/plugin_integrity.py — killed."""
        result = _findings(tmp_path, 'x = "custom_standard"\n', ("custom_standard",))
        assert len(result) == 1
        assert result[0]["name"] == "custom_standard"
        assert result[0]["kind"] == "ast_string_literal"

    def test_skips_ambiguous_names(self, tmp_path):
        """Ambiguous standard names are not flagged by AST scanner. Mutant: the ambiguous-name skip dropped in apps/handlers/aipass_proof/plugin_integrity.py — killed."""
        result = _findings(tmp_path, 'x = "meta"\n', ("meta",))
        assert result == []

    def test_skips_docstrings(self, tmp_path):
        """Standard name in docstring is not flagged."""
        # HELD (pins nothing): the docstring is not equal to a standard name, so no
        # mutant of the docstring skip reddens this. Reached through scan(), the
        # same assert as the direct call it replaced (seedgo, fleet green leg 6).
        result = _findings(tmp_path, '"""custom_standard is great."""\nx = 1\n', ("custom_standard",))
        assert result == []

    def test_skips_display_strings(self, tmp_path):
        """Standard name in display call is not flagged. Mutant: the display-string skip dropped in apps/handlers/aipass_proof/plugin_integrity.py — killed."""
        result = _findings(tmp_path, 'import logger\nlogger.info("custom_standard")\n', ("custom_standard",))
        assert result == []

    def test_skips_dict_key_access(self, tmp_path):
        """Standard name as dict key access is not flagged. Mutant: the dict-key skip dropped in apps/handlers/aipass_proof/plugin_integrity.py — killed."""
        result = _findings(tmp_path, 'result = data.get("custom_standard")\n', ("custom_standard",))
        assert result == []

    def test_non_matching_name_not_flagged(self, tmp_path):
        """String literal not matching any standard name is not flagged. Mutant: the name-set check inverted in apps/handlers/aipass_proof/plugin_integrity.py — killed."""
        result = _findings(tmp_path, 'x = "something_else"\n', ("custom_standard",))
        assert result == []


# ===========================================================================
# PLUGIN INTEGRITY -- the regex scanner, through scan()
# ===========================================================================


class TestScanFileRegex:
    """What the regex half of scan() reports."""

    def test_clean_file(self, tmp_path):
        """File with no suspicious patterns returns empty."""
        result = _findings(tmp_path, 'x = "hello"\n', ("meta",))
        assert result == []

    def test_hardcoded_function_call(self, tmp_path):
        """Detects check_<standard>( pattern. Mutant: the check_<standard>( pattern broken in apps/handlers/aipass_proof/plugin_integrity.py — killed."""
        result = _findings(tmp_path, "result = check_custom_std(path)\n", ("custom_std",))
        assert len(result) >= 1
        kinds = _kinds(result)
        assert "hardcoded_function_call" in kinds

    def test_hardcoded_violation_key(self, tmp_path):
        """Detects <standard>_violations pattern. Mutant: the _violations pattern broken in apps/handlers/aipass_proof/plugin_integrity.py — killed."""
        result = _findings(tmp_path, "x = custom_std_violations\n", ("custom_std",))
        assert len(result) >= 1
        kinds = _kinds(result)
        assert "hardcoded_violation_key" in kinds

    def test_hardcoded_branch_condition(self, tmp_path):
        """Detects == 'standard' pattern. Mutant: the == '<standard>' pattern broken in apps/handlers/aipass_proof/plugin_integrity.py — killed."""
        result = _findings(tmp_path, "if name == 'custom_std':\n    pass\n", ("custom_std",))
        assert len(result) >= 1
        kinds = _kinds(result)
        assert "hardcoded_branch" in kinds

    def test_skips_comment_lines(self, tmp_path):
        """Pure comment lines are skipped."""
        # HELD (pins nothing): the inline-comment strip blanks this line too, so no
        # mutant of the comment skip reddens this. Reached through scan(), the same
        # assert as the direct call it replaced (seedgo, fleet green leg 6).
        result = _findings(tmp_path, "# check_custom_std(path)\n", ("custom_std",))
        assert result == []

    def test_skips_docstring_content(self, tmp_path):
        """Content inside triple-quoted docstrings is skipped. Mutant: docstring lines not skipped in apps/handlers/aipass_proof/plugin_integrity.py — killed."""
        result = _findings(tmp_path, '"""\ncheck_custom_std(path)\n"""\npass\n', ("custom_std",))
        assert result == []

    def test_inline_comment_stripped(self, tmp_path):
        """Code before inline comment is still checked. Mutant: the check_<standard>( pattern broken in apps/handlers/aipass_proof/plugin_integrity.py — killed."""
        result = _findings(tmp_path, "result = check_custom_std(path)  # run check\n", ("custom_std",))
        assert len(result) >= 1

    def test_double_quote_branch(self, tmp_path):
        """Detects == 'standard' with double quotes. Mutant: the == '<standard>' pattern broken in apps/handlers/aipass_proof/plugin_integrity.py — killed."""
        result = _findings(tmp_path, 'if name == "custom_std":\n    pass\n', ("custom_std",))
        kinds = _kinds(result)
        assert "hardcoded_branch" in kinds

    def test_single_quote_docstring(self, tmp_path):
        """Single-quote triple docstrings are tracked. Mutant: docstring lines not skipped in apps/handlers/aipass_proof/plugin_integrity.py — killed."""
        result = _findings(tmp_path, "'''\ncheck_custom_std(path)\n'''\npass\n", ("custom_std",))
        assert result == []

    def test_a_one_line_docstring_naming_a_checker_call_is_not_a_finding(self, tmp_path):
        result = _findings(tmp_path, '"""Never check_custom_std(path) here."""\npass\n', ("custom_std",))
        assert result == []

    def test_the_closing_line_of_a_docstring_is_prose(self, tmp_path):
        result = _findings(tmp_path, '"""Opening.\ncheck_custom_std(path) is named here."""\npass\n', ("custom_std",))
        assert result == []

    def test_code_opening_a_triple_quoted_literal_is_read(self, tmp_path):
        source = 'x = custom_std_violations or """\nbody\n"""\n'
        result = _findings(tmp_path, source, ("custom_std",))
        assert [(f["line"], f["kind"]) for f in result] == [(1, "hardcoded_violation_key")]


# ===========================================================================
# PLUGIN INTEGRITY -- scan (public interface)
# ===========================================================================


class TestPluginIntegrityScan:
    """Tests for the public scan() function."""

    def test_all_modules_missing(self, tmp_path):
        """All target modules missing results in 'missing' status, and a proof that scanned nothing fails."""

        pack_dir = tmp_path / "apps" / "handlers" / "aipass_standards"
        pack_dir.mkdir(parents=True)
        result = scan(pack_dir)
        assert result["passed"] is False
        assert result["missing_count"] == 5
        assert result["flagged_count"] == 0

    def test_clean_module(self, tmp_path):
        """Module with no issues is marked clean."""

        pack_dir = tmp_path / "apps" / "handlers" / "aipass_standards"
        pack_dir.mkdir(parents=True)

        modules_dir = tmp_path / "apps" / "modules"
        modules_dir.mkdir(parents=True)
        (modules_dir / "standards_audit.py").write_text('"""Clean module."""\nx = 1\n', encoding="utf-8")

        result = scan(pack_dir)
        statuses = {m["label"]: m["status"] for m in result["modules"]}
        assert statuses["standards_audit.py"] == "clean"

    def test_cosmetic_module_flagged_as_cosmetic(self, tmp_path):
        """Module in COSMETIC_MODULES with findings is marked cosmetic."""

        pack_dir = tmp_path / "apps" / "handlers" / "aipass_standards"
        pack_dir.mkdir(parents=True)

        (pack_dir / "zz_special_check.py").write_text("pass", encoding="utf-8")

        audit_dir = tmp_path / "apps" / "handlers" / "audit"
        audit_dir.mkdir(parents=True)
        (audit_dir / "audit_display.py").write_text('x = "zz_special"\n', encoding="utf-8")

        result = scan(pack_dir)
        statuses = {m["label"]: m["status"] for m in result["modules"]}
        assert statuses["audit_display.py"] == "cosmetic"
        assert result["cosmetic_count"] >= 1

    def test_flagged_module(self, tmp_path):
        """Non-cosmetic module with findings is flagged and scan fails."""

        pack_dir = tmp_path / "apps" / "handlers" / "aipass_standards"
        pack_dir.mkdir(parents=True)

        (pack_dir / "zz_special_check.py").write_text("pass", encoding="utf-8")

        modules_dir = tmp_path / "apps" / "modules"
        modules_dir.mkdir(parents=True)
        (modules_dir / "standards_audit.py").write_text('x = "zz_special"\n', encoding="utf-8")

        result = scan(pack_dir)
        statuses = {m["label"]: m["status"] for m in result["modules"]}
        assert statuses["standards_audit.py"] == "flagged"
        assert result["flagged_count"] >= 1
        assert result["passed"] is False
        assert "FAILED" in result["summary"]

    def test_deduplication_of_findings(self, tmp_path):
        """Findings from AST and regex are deduplicated."""

        pack_dir = tmp_path / "apps" / "handlers" / "aipass_standards"
        pack_dir.mkdir(parents=True)

        (pack_dir / "zz_special_check.py").write_text("pass", encoding="utf-8")

        modules_dir = tmp_path / "apps" / "modules"
        modules_dir.mkdir(parents=True)
        (modules_dir / "standards_audit.py").write_text("if name == 'zz_special':\n    pass\n", encoding="utf-8")

        result = scan(pack_dir)
        flagged_mod = [m for m in result["modules"] if m["label"] == "standards_audit.py"][0]
        findings = flagged_mod["findings"]
        # Measured: one line yields two findings of different kinds -- dedup must
        # keep both, not collapse them. An empty list here would make the walk
        # below a silent pass, so the floor is the exact count.
        assert len(findings) == 2, f"expected the AST and the regex finding, got {findings}"
        assert {f["kind"] for f in findings} == {"ast_string_literal", "hardcoded_branch"}
        keys: set[tuple[object, ...]] = set()
        for finding in findings:
            key = (finding["line"], finding["name"], finding["kind"])
            assert key not in keys, f"Duplicate finding: {key}"
            keys.add(key)

    def test_summary_with_all_clean(self, tmp_path):
        """Summary string says 'clean' when all modules pass."""

        pack_dir = tmp_path / "apps" / "handlers" / "aipass_standards"
        pack_dir.mkdir(parents=True)

        modules_dir = tmp_path / "apps" / "modules"
        modules_dir.mkdir(parents=True)
        (modules_dir / "standards_audit.py").write_text("x = 1\n", encoding="utf-8")
        (modules_dir / "standards_query.py").write_text("x = 1\n", encoding="utf-8")
        audit_dir = tmp_path / "apps" / "handlers" / "audit"
        audit_dir.mkdir(parents=True)
        (audit_dir / "branch_audit.py").write_text("x = 1\n", encoding="utf-8")
        (audit_dir / "audit_display.py").write_text("x = 1\n", encoding="utf-8")
        entry_point = tmp_path / "apps" / "seedgo.py"
        entry_point.write_text("x = 1\n", encoding="utf-8")

        result = scan(pack_dir)
        assert result["passed"] is True
        assert "clean" in result["summary"].lower()

    def test_issue_kind_labels(self, tmp_path):
        """Issue strings use human-readable kind labels."""

        pack_dir = tmp_path / "apps" / "handlers" / "aipass_standards"
        pack_dir.mkdir(parents=True)

        (pack_dir / "zz_special_check.py").write_text("pass", encoding="utf-8")

        modules_dir = tmp_path / "apps" / "modules"
        modules_dir.mkdir(parents=True)
        (modules_dir / "standards_audit.py").write_text(
            "check_zz_special(path)\nzz_special_violations = []\n",
            encoding="utf-8",
        )

        result = scan(pack_dir)
        issue_text = " ".join(result["issues"])
        # Measured from a real scan: the call site and the violation key each get
        # their own human-readable kind label, so both are pinned.
        assert "hardcoded function call" in issue_text
        assert "hardcoded violation key" in issue_text


# ===========================================================================
# DIAGNOSTICS CHECK -- should_ignore_file
# ===========================================================================


class TestShouldIgnoreFile:
    """Tests for should_ignore_file."""

    def test_matching_pattern(self, tmp_path):
        """A root-anchored entry removes its path at the branch root and nowhere deeper."""

        mod = "aipass.seedgo.apps.handlers.diagnostics.diagnostics_check"
        with patch(f"{mod}.audit_ignore_match", real_ignore_handler.audit_ignore_match):
            assert should_ignore_file(str(tmp_path / "backups" / "old.py"), tmp_path) is True
            assert should_ignore_file(str(tmp_path / "apps" / "backups" / "ops.py"), tmp_path) is False

    def test_no_matching_pattern(self, tmp_path):
        """An unanchored entry (.archive/) removes its directory at any depth."""

        mod = "aipass.seedgo.apps.handlers.diagnostics.diagnostics_check"
        with patch(f"{mod}.audit_ignore_match", real_ignore_handler.audit_ignore_match):
            assert should_ignore_file(str(tmp_path / "apps" / "x" / ".archive" / "a.py"), tmp_path) is True
            assert should_ignore_file(str(tmp_path / "apps" / "x" / "archive.py"), tmp_path) is False

    def test_empty_patterns(self, tmp_path, monkeypatch):
        """Empty pattern list means nothing is ignored."""

        monkeypatch.setattr(real_ignore_handler, "AUDIT_IGNORE_PATTERNS", [])
        mod = "aipass.seedgo.apps.handlers.diagnostics.diagnostics_check"
        with patch(f"{mod}.audit_ignore_match", real_ignore_handler.audit_ignore_match):
            assert should_ignore_file(str(tmp_path / "apps" / "__pycache__" / "m.py"), tmp_path) is False


# ===========================================================================
# DIAGNOSTICS CHECK -- check_file
# ===========================================================================


class TestCheckFile:
    """Tests for check_file."""

    def test_nonexistent_file(self, tmp_path):
        """Nonexistent file returns error dict."""

        result = check_file(str(tmp_path / "missing.py"))
        assert result["errors"] == 0
        assert "error" in result
        assert "not found" in result["error"].lower()

    def test_non_python_file(self, tmp_path):
        """Non-.py file is skipped."""

        f = tmp_path / "data.txt"
        f.write_text("hello", encoding="utf-8")
        result = check_file(str(f))
        assert result["errors"] == 0
        assert "skipped" in result

    def test_successful_pyright_check(self, tmp_path):
        """Pyright with clean output returns zero errors."""

        f = tmp_path / "good.py"
        f.write_text("x = 1\n", encoding="utf-8")

        pyright_out = json.dumps({"generalDiagnostics": [], "summary": {"filesAnalyzed": 1}})
        with patch("aipass.seedgo.apps.handlers.diagnostics.diagnostics_check.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout=pyright_out, stderr="")
            result = check_file(str(f))

        assert result["errors"] == 0
        assert result["warnings"] == 0
        assert result["diagnostics"] == []

    def test_pyright_with_errors(self, tmp_path):
        """Pyright output with errors is parsed correctly."""

        f = tmp_path / "bad.py"
        f.write_text("x: int = 'no'\n", encoding="utf-8")

        diags = [
            {
                "severity": "error",
                "range": {"start": {"line": 0}},
                "message": "Type mismatch",
                "rule": "reportAssignment",
            },
            {
                "severity": "warning",
                "range": {"start": {"line": 1}},
                "message": "Unused var",
                "rule": "reportUnusedVariable",
            },
        ]

        with patch("aipass.seedgo.apps.handlers.diagnostics.diagnostics_check.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                stdout=json.dumps({"generalDiagnostics": diags}),
                stderr="",
            )
            result = check_file(str(f))

        assert result["errors"] == 1
        assert result["warnings"] == 1
        assert len(result["diagnostics"]) == 2
        assert result["diagnostics"][0]["line"] == 1

    def test_pyright_json_decode_error(self, tmp_path):
        """Non-JSON pyright output returns error dict."""

        f = tmp_path / "file.py"
        f.write_text("x = 1\n", encoding="utf-8")

        with patch("aipass.seedgo.apps.handlers.diagnostics.diagnostics_check.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                stdout="not json",
                stderr="something went wrong",
            )
            result = check_file(str(f))

        assert "error" in result

    def test_pyright_timeout(self, tmp_path):
        """Pyright timeout returns timeout error."""

        f = tmp_path / "slow.py"
        f.write_text("x = 1\n", encoding="utf-8")

        with patch("aipass.seedgo.apps.handlers.diagnostics.diagnostics_check.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd="pyright", timeout=30)
            result = check_file(str(f))

        assert "error" in result
        assert "timed out" in result["error"].lower()

    def test_pyright_generic_exception(self, tmp_path):
        """Generic exception during pyright returns error dict."""

        f = tmp_path / "crash.py"
        f.write_text("x = 1\n", encoding="utf-8")

        with patch("aipass.seedgo.apps.handlers.diagnostics.diagnostics_check.subprocess.run") as mock_run:
            mock_run.side_effect = OSError("pyright not found")
            result = check_file(str(f))

        assert "error" in result
        assert "pyright not found" in result["error"]


# ===========================================================================
# DIAGNOSTICS CHECK -- check_directory
# ===========================================================================


class TestCheckDirectory:
    """Tests for check_directory."""

    def test_nonexistent_directory(self, tmp_path):
        """Nonexistent directory returns error."""

        result = check_directory(str(tmp_path / "nonexistent"))
        assert result["total_files"] == 0
        assert "error" in result

    def test_empty_directory(self, tmp_path):
        """Empty directory with no diagnostics returns zero totals."""

        pyright_out = json.dumps({"generalDiagnostics": [], "summary": {"filesAnalyzed": 0}})
        with patch("aipass.seedgo.apps.handlers.diagnostics.diagnostics_check.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout=pyright_out, stderr="")
            result = check_directory(str(tmp_path))

        assert result["total_errors"] == 0
        assert result["total_files"] == 0

    def test_directory_with_errors(self, tmp_path):
        """Directory with pyright errors parses and groups correctly."""

        diags = [
            {
                "file": "/src/a.py",
                "severity": "error",
                "range": {"start": {"line": 5}},
                "message": "Err1",
                "rule": "r1",
            },
            {
                "file": "/src/a.py",
                "severity": "warning",
                "range": {"start": {"line": 10}},
                "message": "Warn1",
                "rule": "r2",
            },
            {
                "file": "/src/b.py",
                "severity": "error",
                "range": {"start": {"line": 1}},
                "message": "Err2",
                "rule": "r3",
            },
        ]

        pyright_out = json.dumps({"generalDiagnostics": diags, "summary": {"filesAnalyzed": 2}})
        with patch("aipass.seedgo.apps.handlers.diagnostics.diagnostics_check.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout=pyright_out, stderr="")
            result = check_directory(str(tmp_path))

        assert result["total_errors"] == 2
        assert result["total_warnings"] == 1
        assert result["files_with_errors"] == 2
        assert result["total_files"] == 2
        assert result["results"][0]["errors"] >= result["results"][1]["errors"]

    def test_directory_ignores_files(self, tmp_path):
        """Pyright's findings in the driver layer are dropped; tracked handlers/integrations/ keeps its."""

        apps = tmp_path / "apps"
        apps.mkdir()
        kept = str(apps / "handlers" / "integrations" / "call.py")
        diags = [
            {
                "file": str(apps / "integrations" / "google" / "driver.py"),
                "severity": "error",
                "range": {"start": {"line": 1}},
                "message": "Err",
                "rule": "r1",
            },
            {
                "file": kept,
                "severity": "error",
                "range": {"start": {"line": 1}},
                "message": "Err",
                "rule": "r2",
            },
        ]

        pyright_out = json.dumps({"generalDiagnostics": diags, "summary": {"filesAnalyzed": 2}})
        mod_prefix = "aipass.seedgo.apps.handlers.diagnostics.diagnostics_check"
        with (
            patch(f"{mod_prefix}.subprocess.run") as mock_run,
            patch(f"{mod_prefix}.audit_ignore_match", real_ignore_handler.audit_ignore_match),
        ):
            mock_run.return_value = MagicMock(stdout=pyright_out, stderr="")
            result = check_directory(str(apps))

        assert result["total_errors"] == 1
        assert [r["file"] for r in result["results"]] == [kept]

    def test_directory_json_decode_error(self, tmp_path):
        """Non-JSON pyright output for directory returns error."""

        with patch("aipass.seedgo.apps.handlers.diagnostics.diagnostics_check.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                stdout="not json at all",
                stderr="",
            )
            result = check_directory(str(tmp_path))

        assert "error" in result
        assert result["total_files"] == 0

    def test_directory_timeout(self, tmp_path):
        """Timeout for directory check returns error."""

        with patch("aipass.seedgo.apps.handlers.diagnostics.diagnostics_check.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd="pyright", timeout=300)
            result = check_directory(str(tmp_path))

        assert "error" in result
        assert "timed out" in result["error"].lower()

    def test_directory_generic_exception(self, tmp_path):
        """Generic exception during directory check returns error."""

        with patch("aipass.seedgo.apps.handlers.diagnostics.diagnostics_check.subprocess.run") as mock_run:
            mock_run.side_effect = RuntimeError("unexpected")
            result = check_directory(str(tmp_path))

        assert "error" in result
        assert "unexpected" in result["error"]


# ===========================================================================
# DIAGNOSTICS CHECK -- check_branch
# ===========================================================================


def _scored(tmp_path: Path, monkeypatch, dir_result: dict) -> dict:
    """check_branch over a branch whose pyright pass (check_directory) reports *dir_result*."""
    (tmp_path / "apps").mkdir()
    seen: list[str] = []
    monkeypatch.setattr(diagnostics_check, "check_directory", lambda d: (seen.append(d), dir_result)[1])
    result = check_branch(str(tmp_path))
    assert seen == [str(tmp_path / "apps")]
    return result


class TestCheckBranch:
    """Tests for check_branch."""

    def test_no_apps_directory(self, tmp_path):
        """Returns passed=True when no apps/ directory exists."""

        result = check_branch(str(tmp_path))
        assert result["passed"] is True
        assert result["score"] == 100
        assert "error" in result

    def test_pyright_errors_become_failed_rows(self, tmp_path, monkeypatch):
        """Each file pyright reports errors in is one failed row, and the errors dock the score."""
        dir_result = {
            "total_errors": 1,
            "total_warnings": 0,
            "total_files": 2,
            "results": [{"file": "a.py", "errors": 1, "warnings": 0, "diagnostics": []}],
        }
        result = _scored(tmp_path, monkeypatch, dir_result)
        assert result["passed"] is False
        assert result["total_errors"] == 1
        assert result["score"] == 95
        assert [c["name"] for c in result["checks"]] == ["Type errors in a.py"]

    def test_no_errors_default_check(self, tmp_path, monkeypatch):
        """Default passing check is added when nothing failed."""
        dir_result = {"total_errors": 0, "total_warnings": 0, "total_files": 10, "results": []}
        result = _scored(tmp_path, monkeypatch, dir_result)
        assert result["passed"] is True
        assert len(result["checks"]) == 1
        assert result["checks"][0]["passed"] is True
        assert "10 files" in result["checks"][0]["message"]

    def test_score_clamped_at_zero(self, tmp_path, monkeypatch):
        """Score does not go below 0 even with many errors."""
        dir_result = {
            "total_errors": 100,
            "total_warnings": 0,
            "total_files": 50,
            "results": [{"file": f"f{i}.py", "errors": 1} for i in range(100)],
        }
        assert _scored(tmp_path, monkeypatch, dir_result)["score"] == 0


# ===========================================================================
# DIAGNOSTICS CHECK -- format_summary
# ===========================================================================


class TestFormatSummary:
    """Tests for format_summary."""

    def test_with_error(self):
        """Returns error message when 'error' key is present."""

        result = format_summary({"error": "Something broke"})
        assert result == "Error: Something broke"

    def test_normal_summary(self):
        """Returns formatted summary for normal results."""

        results = {
            "total_files": 10,
            "files_with_errors": 2,
            "total_errors": 5,
            "total_warnings": 3,
        }
        summary = format_summary(results)
        assert "Files analyzed: 10" in summary
        assert "Files with errors: 2" in summary
        assert "Total errors: 5" in summary
        assert "Total warnings: 3" in summary

    def test_empty_error_string(self):
        """Empty error string returns normal summary."""

        results = {
            "error": "",
            "total_files": 0,
            "files_with_errors": 0,
            "total_errors": 0,
            "total_warnings": 0,
        }
        summary = format_summary(results)
        assert "Files analyzed: 0" in summary
