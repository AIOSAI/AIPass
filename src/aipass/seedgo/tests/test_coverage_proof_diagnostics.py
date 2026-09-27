# =================== META ====================
# Name: test_coverage_proof_diagnostics.py
# Description: Line-coverage tests for plugin_integrity.py and diagnostics_check.py
# Version: 1.1.0
# Created: 2026-04-26
# Modified: 2026-09-27
# =============================================

"""Tests for apps/handlers/aipass_proof/plugin_integrity.py and apps/handlers/diagnostics/diagnostics_check.py."""

# Coverage tests for the two handlers, reached through their public doors:
# plugin_integrity.scan() and diagnostics_check.check_branch(), check_file(),
# check_directory(), should_ignore_file() and format_summary(). Each synthetic
# source below is written into a scanned target module, so every helper is
# judged by the finding scan() reports for it, not by a direct call.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(stdlib) — importlib.import_module's loading of a runner module from a path on __path__

import ast
import json
import subprocess
import sys
import textwrap

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from aipass.seedgo.apps.handlers import diagnostics as diagnostics_package
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

    def test_no_parent(self):
        """Node with no parent returns False."""
        # HELD (no public seam): scan() hands _is_display_string only nodes from a
        # parsed module, and every such constant has a parent.
        child = ast.Constant(value="hello")
        assert plugin_integrity._is_display_string(child, {}) is False

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

    def test_no_parent(self):
        """Node with no parent returns False."""
        # HELD (no public seam): scan() hands _is_dict_key_access only nodes from a
        # parsed module, and every such constant has a parent.
        child = ast.Constant(value="key")
        assert plugin_integrity._is_dict_key_access(child, {}) is False

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
        # mutant of the docstring skip reddens this, through scan() or directly.
        f = tmp_path / "docstr.py"
        f.write_text('"""custom_standard is great."""\nx = 1\n', encoding="utf-8")
        result = plugin_integrity._scan_file_ast(f, ["custom_standard"])
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
        # mutant of the comment skip reddens this, through scan() or directly.
        f = tmp_path / "comments.py"
        f.write_text("# check_custom_std(path)\n", encoding="utf-8")
        result = plugin_integrity._scan_file_regex(f, ["custom_std"])
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


# ===========================================================================
# PLUGIN INTEGRITY -- scan (public interface)
# ===========================================================================


class TestPluginIntegrityScan:
    """Tests for the public scan() function."""

    def test_all_modules_missing(self, tmp_path):
        """All target modules missing results in 'missing' status."""

        pack_dir = tmp_path / "apps" / "handlers" / "aipass_standards"
        pack_dir.mkdir(parents=True)
        result = scan(pack_dir)
        assert result["passed"] is True
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


# ---------------------------------------------------------------------------
# Helpers -- check_branch over a handlers/ tree under tmp_path
# ---------------------------------------------------------------------------

_RUNNER_PREFIX = diagnostics_package.__name__ + "."


@pytest.fixture
def handlers_dir(tmp_path, monkeypatch):
    """tmp_path as check_branch's handlers/ and diagnostics/ dirs, and as a branch with an apps/."""
    # A runner written here imports for real, under the diagnostics package's own
    # name, exactly as _run_runner imports it; it leaves sys.modules afterwards.
    monkeypatch.setattr(diagnostics_check, "HANDLERS_DIR", tmp_path)
    monkeypatch.setattr(diagnostics_check, "DIAGNOSTICS_DIR", tmp_path)
    monkeypatch.setattr(diagnostics_package, "__path__", [*diagnostics_package.__path__, str(tmp_path)])
    (tmp_path / "apps").mkdir()
    yield tmp_path
    for name in [
        n
        for n, m in list(sys.modules.items())
        if n.startswith(_RUNNER_PREFIX) and str(getattr(m, "__file__", "")).startswith(str(tmp_path))
    ]:
        del sys.modules[name]


class _Fallback:
    """Stands in for check_directory, the pyright subprocess check_branch falls back to."""

    RESULT = {"total_errors": 0, "total_warnings": 0, "total_files": 42, "results": []}

    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(self, directory: str) -> dict:
        self.calls.append(directory)
        return self.RESULT


def _config(handlers: Path, config: dict, pack: str = "x_standards") -> None:
    """A *_standards pack under *handlers* whose diagnostics.json is *config*."""
    pack_dir = handlers / pack
    pack_dir.mkdir(exist_ok=True)
    (pack_dir / "diagnostics.json").write_text(json.dumps(config), encoding="utf-8")


def _requested(branch: Path, monkeypatch) -> list[str]:
    """The runner names check_branch asks for on *branch*, each answered clean."""
    asked: list[str] = []

    def runner(name: str, branch_path: str, bypass_rules: list | None = None) -> dict:
        asked.append(name)
        return {"total_errors": 0, "total_warnings": 0, "total_files": 1, "checks": [], "results": []}

    monkeypatch.setattr(diagnostics_check, "_run_runner", runner)
    check_branch(str(branch))
    return asked


def _through_runner(handlers: Path, monkeypatch, runner: str) -> tuple[dict, _Fallback]:
    """check_branch with only *runner* enabled: its result, and the pyright fallback it may call."""
    _config(handlers, {"runners": {runner: True}})
    fallback = _Fallback()
    monkeypatch.setattr(diagnostics_check, "check_directory", fallback)
    return check_branch(str(handlers)), fallback


# ===========================================================================
# DIAGNOSTICS CHECK -- pack config discovery, through check_branch
# ===========================================================================


class TestDiscoverPackConfigs:
    """Which diagnostics.json files check_branch reads its runners from."""

    def test_no_handlers_dir(self, tmp_path, monkeypatch):
        """No HANDLERS_DIR means no config: only the python fallback runs. Mutant: the missing-dir guard dropped in apps/handlers/diagnostics/diagnostics_check.py — killed."""
        monkeypatch.setattr(diagnostics_check, "HANDLERS_DIR", tmp_path / "nonexistent")
        (tmp_path / "apps").mkdir()
        assert _requested(tmp_path, monkeypatch) == ["python"]

    def test_no_standards_dirs(self, handlers_dir, monkeypatch):
        """A config outside a *_standards dir is not read. Mutant: the _standards name check dropped in apps/handlers/diagnostics/diagnostics_check.py — killed."""
        _config(handlers_dir, {"runners": {"rust": True}}, pack="other_dir")
        assert _requested(handlers_dir, monkeypatch) == ["python"]

    def test_standards_dir_without_config(self, handlers_dir, monkeypatch):
        """A *_standards dir with no diagnostics.json adds no runner. Mutant: any *.json read as the config in apps/handlers/diagnostics/diagnostics_check.py — killed."""
        pack_dir = handlers_dir / "aipass_standards"
        pack_dir.mkdir()
        (pack_dir / "other.json").write_text(json.dumps({"runners": {"rust": True}}), encoding="utf-8")
        assert _requested(handlers_dir, monkeypatch) == ["python"]

    def test_valid_config(self, tmp_path, monkeypatch):
        """Returns config when valid diagnostics.json exists."""
        # HELD (no public seam): check_branch reads only each config's runners, never
        # the pack_name and pack_path this pins.
        monkeypatch.setattr(diagnostics_check, "HANDLERS_DIR", tmp_path)
        std_dir = tmp_path / "aipass_standards"
        std_dir.mkdir()
        config = {"runners": {"python": True}}
        (std_dir / "diagnostics.json").write_text(json.dumps(config), encoding="utf-8")

        result = diagnostics_check._discover_pack_configs()
        assert len(result) == 1
        assert result[0]["pack_name"] == "aipass_standards"
        assert result[0]["config"] == config

    def test_malformed_config_skipped(self, handlers_dir, monkeypatch):
        """Malformed JSON is skipped gracefully. Mutant: JSONDecodeError not caught in apps/handlers/diagnostics/diagnostics_check.py — killed."""
        std_dir = handlers_dir / "test_standards"
        std_dir.mkdir()
        (std_dir / "diagnostics.json").write_text("not json", encoding="utf-8")
        assert _requested(handlers_dir, monkeypatch) == ["python"]

    def test_non_directory_skipped(self, tmp_path, monkeypatch):
        """Files (not directories) in HANDLERS_DIR are skipped."""
        # HELD (pins nothing): a file's diagnostics.json never exists, so no mutant
        # of the is_dir() skip reddens this, through check_branch or directly.
        monkeypatch.setattr(diagnostics_check, "HANDLERS_DIR", tmp_path)
        (tmp_path / "some_standards").write_text("file", encoding="utf-8")
        result = diagnostics_check._discover_pack_configs()
        assert result == []


# ===========================================================================
# DIAGNOSTICS CHECK -- enabled runners, through check_branch
# ===========================================================================


class TestGetEnabledRunners:
    """Which runners a diagnostics.json enables."""

    # python is check_branch's fallback, so an enabled runner is named rust here:
    # a python-only answer could not tell the config from the fallback.

    def test_simple_bool_format(self, handlers_dir, monkeypatch):
        """Simple bool format: {'rust': true}. Mutant: a false bool read as enabled in apps/handlers/diagnostics/diagnostics_check.py — killed."""
        _config(handlers_dir, {"runners": {"rust": True, "typescript": False}})
        assert _requested(handlers_dir, monkeypatch) == ["rust"]

    def test_detailed_dict_format(self, handlers_dir, monkeypatch):
        """Detailed format: {'rust': {'enabled': true, ...}}. Mutant: every dict read as enabled in apps/handlers/diagnostics/diagnostics_check.py — killed."""
        _config(handlers_dir, {"runners": {"rust": {"enabled": True, "timeout": 60}, "go": {"enabled": False}}})
        assert _requested(handlers_dir, monkeypatch) == ["rust"]

    def test_empty_runners(self, handlers_dir, monkeypatch):
        """Empty runners section enables nothing: only the fallback runs. Mutant: an empty section answers a runner in apps/handlers/diagnostics/diagnostics_check.py — killed."""
        _config(handlers_dir, {"runners": {}})
        assert _requested(handlers_dir, monkeypatch) == ["python"]

    def test_no_runners_key(self, handlers_dir, monkeypatch):
        """Missing 'runners' key enables nothing: only the fallback runs. Mutant: 'runners' read without a default in apps/handlers/diagnostics/diagnostics_check.py — killed."""
        _config(handlers_dir, {})
        assert _requested(handlers_dir, monkeypatch) == ["python"]

    def test_mixed_formats(self, handlers_dir, monkeypatch):
        """Mix of bool and dict format works. Mutant: the dict format never read in apps/handlers/diagnostics/diagnostics_check.py — killed."""
        config = {
            "runners": {
                "python": True,
                "rust": {"enabled": True},
                "go": False,
                "java": {"enabled": False},
            }
        }
        _config(handlers_dir, config)
        result = _requested(handlers_dir, monkeypatch)
        assert "python" in result
        assert "rust" in result
        assert "go" not in result
        assert "java" not in result


# ===========================================================================
# DIAGNOSTICS CHECK -- runner dispatch, through check_branch
# ===========================================================================


class TestRunRunner:
    """A runner that does not answer sends check_branch to its pyright fallback."""

    def test_runner_not_found(self, handlers_dir, monkeypatch):
        """A missing runner file falls back. Mutant: a missing runner answered in apps/handlers/diagnostics/diagnostics_check.py — killed."""
        _, fallback = _through_runner(handlers_dir, monkeypatch, "nonexistent")
        assert fallback.calls == [str(handlers_dir / "apps")]

    def test_runner_empty_file(self, handlers_dir, monkeypatch):
        """An empty (0 bytes) runner file falls back. Mutant: an empty runner answered in apps/handlers/diagnostics/diagnostics_check.py — killed."""
        (handlers_dir / "empty_diagnostics.py").write_text("", encoding="utf-8")
        _, fallback = _through_runner(handlers_dir, monkeypatch, "empty")
        assert fallback.calls == [str(handlers_dir / "apps")]

    def test_runner_whitespace_only(self, handlers_dir, monkeypatch):
        """A whitespace-only runner file falls back. Mutant: a blank runner answered in apps/handlers/diagnostics/diagnostics_check.py — killed."""
        (handlers_dir / "blank_diagnostics.py").write_text("   \n\n  \n", encoding="utf-8")
        _, fallback = _through_runner(handlers_dir, monkeypatch, "blank")
        assert fallback.calls == [str(handlers_dir / "apps")]

    def test_runner_import_failure(self, handlers_dir, monkeypatch):
        """A runner module that fails to import falls back. Mutant: an import failure answered in apps/handlers/diagnostics/diagnostics_check.py — killed."""
        (handlers_dir / "broken_diagnostics.py").write_text("import nonexistent_module_xyz\n", encoding="utf-8")
        _, fallback = _through_runner(handlers_dir, monkeypatch, "broken")
        assert fallback.calls == [str(handlers_dir / "apps")]

    def test_runner_no_check_branch(self, handlers_dir, monkeypatch):
        """A runner module with no check_branch falls back. Mutant: a runner without check_branch answered in apps/handlers/diagnostics/diagnostics_check.py — killed."""
        (handlers_dir / "nofunc_diagnostics.py").write_text("x = 1\n", encoding="utf-8")
        _, fallback = _through_runner(handlers_dir, monkeypatch, "nofunc")
        assert fallback.calls == [str(handlers_dir / "apps")]

    def test_runner_check_branch_raises(self, handlers_dir, monkeypatch):
        """A runner whose check_branch raises falls back. Mutant: a raising runner answered in apps/handlers/diagnostics/diagnostics_check.py — killed."""
        (handlers_dir / "crashing_diagnostics.py").write_text(
            "def check_branch(b, bypass_rules=None):\n    raise RuntimeError('boom')\n",
            encoding="utf-8",
        )
        _, fallback = _through_runner(handlers_dir, monkeypatch, "crashing")
        assert fallback.calls == [str(handlers_dir / "apps")]

    def test_runner_success(self, handlers_dir, monkeypatch):
        """A runner that answers is merged and pyright never runs. Mutant: the runner's answer dropped in apps/handlers/diagnostics/diagnostics_check.py — killed."""
        (handlers_dir / "good_diagnostics.py").write_text(
            "def check_branch(b, bypass_rules=None):\n"
            "    return {'total_errors': 3, 'total_warnings': 0, 'total_files': 7, 'checks': [], 'results': []}\n",
            encoding="utf-8",
        )
        result, fallback = _through_runner(handlers_dir, monkeypatch, "good")
        assert (result["total_errors"], result["total_files"]) == (3, 7)
        assert fallback.calls == []

    def test_runner_typo_variant(self, handlers_dir, monkeypatch):
        """Falls back to *_diognostics.py typo variant. Mutant: the typo variant not tried in apps/handlers/diagnostics/diagnostics_check.py — killed."""
        (handlers_dir / "legacy_diognostics.py").write_text(
            "def check_branch(b, bypass_rules=None):\n"
            "    return {'total_errors': 0, 'total_warnings': 0, 'total_files': 5, 'checks': [], 'results': []}\n",
            encoding="utf-8",
        )
        result, fallback = _through_runner(handlers_dir, monkeypatch, "legacy")
        assert result["total_files"] == 5
        assert fallback.calls == []

    def test_runner_ioerror_on_read(self, handlers_dir, monkeypatch):
        """A runner file that cannot be read falls back. Mutant: a read error answered in apps/handlers/diagnostics/diagnostics_check.py — killed."""
        # A directory under the runner's file name is a real read failure on every
        # OS: POSIX raises IsADirectoryError, Windows PermissionError (or stats it
        # at size 0, which falls back one check earlier).
        (handlers_dir / "ioerr_diagnostics.py").mkdir()
        _, fallback = _through_runner(handlers_dir, monkeypatch, "ioerr")
        assert fallback.calls == [str(handlers_dir / "apps")]


# ===========================================================================
# DIAGNOSTICS CHECK -- check_branch
# ===========================================================================


class TestCheckBranch:
    """Tests for check_branch."""

    def test_no_apps_directory(self, tmp_path):
        """Returns passed=True when no apps/ directory exists."""

        result = check_branch(str(tmp_path))
        assert result["passed"] is True
        assert result["score"] == 100
        assert "error" in result

    def test_with_runner_configs(self, tmp_path, monkeypatch):
        """Uses runner configs when packs are discovered."""

        apps_dir = tmp_path / "apps"
        apps_dir.mkdir()

        monkeypatch.setattr(
            diagnostics_check,
            "_discover_pack_configs",
            lambda: [
                {
                    "pack_name": "test_standards",
                    "pack_path": tmp_path,
                    "config": {"runners": {"python": True}},
                }
            ],
        )

        runner_result = {
            "total_errors": 2,
            "total_warnings": 1,
            "total_files": 5,
            "checks": [
                {
                    "name": "Type errors in a.py",
                    "passed": False,
                    "message": "2 errors",
                }
            ],
            "results": [{"file": "a.py", "errors": 2}],
        }
        monkeypatch.setattr(
            diagnostics_check,
            "_run_runner",
            lambda name, bp, bypass_rules=None: runner_result,
        )

        result = diagnostics_check.check_branch(str(tmp_path))
        assert result["passed"] is False
        assert result["total_errors"] == 2
        assert result["total_warnings"] == 1
        assert result["total_files"] == 5
        assert result["score"] == 90

    def test_fallback_to_python_runner(self, tmp_path, monkeypatch):
        """Falls back to 'python' runner when no configs found."""

        apps_dir = tmp_path / "apps"
        apps_dir.mkdir()

        monkeypatch.setattr(diagnostics_check, "_discover_pack_configs", lambda: [])

        runner_result = {
            "total_errors": 0,
            "total_warnings": 0,
            "total_files": 3,
            "checks": [{"name": "Type check", "passed": True, "message": "OK"}],
            "results": [],
        }
        monkeypatch.setattr(
            diagnostics_check,
            "_run_runner",
            lambda name, bp, bypass_rules=None: runner_result,
        )

        result = diagnostics_check.check_branch(str(tmp_path))
        assert result["passed"] is True
        assert result["score"] == 100

    def test_no_runner_executed_fallback_to_pyright(self, tmp_path, monkeypatch):
        """Falls back to direct pyright check when no runner executes. Mutant: the fallback runner renamed in apps/handlers/diagnostics/diagnostics_check.py — killed."""

        apps_dir = tmp_path / "apps"
        apps_dir.mkdir()

        monkeypatch.setattr(diagnostics_check, "_discover_pack_configs", lambda: [])
        asked: list[str] = []

        def runner(name: str, branch_path: str, bypass_rules: list | None = None) -> None:
            asked.append(name)

        monkeypatch.setattr(diagnostics_check, "_run_runner", runner)

        dir_result = {
            "total_errors": 1,
            "total_warnings": 0,
            "total_files": 2,
            "results": [
                {
                    "file": "a.py",
                    "errors": 1,
                    "warnings": 0,
                    "diagnostics": [],
                },
            ],
        }
        monkeypatch.setattr(diagnostics_check, "check_directory", lambda d: dir_result)

        result = diagnostics_check.check_branch(str(tmp_path))
        assert result["passed"] is False
        assert result["total_errors"] == 1
        assert any("Type errors" in c["name"] for c in result["checks"])
        assert asked == ["python"]

    def test_no_errors_default_check(self, tmp_path, monkeypatch):
        """Default passing check is added when nothing failed."""

        apps_dir = tmp_path / "apps"
        apps_dir.mkdir()

        monkeypatch.setattr(diagnostics_check, "_discover_pack_configs", lambda: [])

        runner_result = {
            "total_errors": 0,
            "total_warnings": 0,
            "total_files": 10,
            "checks": [],
            "results": [],
        }
        monkeypatch.setattr(
            diagnostics_check,
            "_run_runner",
            lambda name, bp, bypass_rules=None: runner_result,
        )

        result = diagnostics_check.check_branch(str(tmp_path))
        assert result["passed"] is True
        assert len(result["checks"]) == 1
        assert result["checks"][0]["passed"] is True
        assert "10 files" in result["checks"][0]["message"]

    def test_score_clamped_at_zero(self, tmp_path, monkeypatch):
        """Score does not go below 0 even with many errors."""

        apps_dir = tmp_path / "apps"
        apps_dir.mkdir()

        monkeypatch.setattr(diagnostics_check, "_discover_pack_configs", lambda: [])

        runner_result = {
            "total_errors": 100,
            "total_warnings": 0,
            "total_files": 50,
            "checks": [
                {
                    "name": "errors",
                    "passed": False,
                    "message": "100 errors",
                }
            ],
            "results": [{"file": f"f{i}.py", "errors": 1} for i in range(100)],
        }
        monkeypatch.setattr(
            diagnostics_check,
            "_run_runner",
            lambda name, bp, bypass_rules=None: runner_result,
        )

        result = diagnostics_check.check_branch(str(tmp_path))
        assert result["score"] == 0

    def test_multiple_runners_deduplicated(self, tmp_path, monkeypatch):
        """Duplicate runner names across packs are deduplicated."""

        apps_dir = tmp_path / "apps"
        apps_dir.mkdir()

        monkeypatch.setattr(
            diagnostics_check,
            "_discover_pack_configs",
            lambda: [
                {
                    "pack_name": "a_standards",
                    "pack_path": tmp_path,
                    "config": {"runners": {"python": True}},
                },
                {
                    "pack_name": "b_standards",
                    "pack_path": tmp_path,
                    "config": {"runners": {"python": True}},
                },
            ],
        )

        call_count = 0

        def _mock_run_runner(
            name: str,
            bp: str,
            bypass_rules: list | None = None,
        ) -> dict:
            """Track runner invocations and return clean result."""
            nonlocal call_count
            call_count += 1
            return {
                "total_errors": 0,
                "total_warnings": 0,
                "total_files": 1,
                "checks": [],
                "results": [],
            }

        monkeypatch.setattr(diagnostics_check, "_run_runner", _mock_run_runner)

        result = diagnostics_check.check_branch(str(tmp_path))
        assert call_count == 1
        assert result["passed"] is True


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
