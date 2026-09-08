"""Tests for plugin_integrity (aipass_proof) and diagnostics_check (diagnostics) coverage."""

# =================== META ====================
# Name: test_coverage_proof_diagnostics.py
# Description: Line-coverage tests for plugin_integrity.py and diagnostics_check.py
# Version: 1.0.0
# Created: 2026-04-26
# Modified: 2026-04-26
# =============================================

import ast
import json
import subprocess

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _mock_infrastructure(monkeypatch):
    """Mock heavy infrastructure imports for proof and diagnostics handlers."""
    import sys

    mock_logger = MagicMock()
    mock_json_handler = MagicMock()
    mock_json_handler.log_operation = MagicMock(return_value=True)

    # -- prax ---------------------------------------------------------------
    prax_mod = MagicMock()
    prax_mod.logger = mock_logger
    monkeypatch.setitem(sys.modules, "aipass.prax", prax_mod)

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
    bypass_ignore = MagicMock()
    bypass_ignore.get_template_ignore_patterns = MagicMock(return_value=[])
    bypass_ignore.get_audit_ignore_patterns = MagicMock(return_value=[])
    bypass_pkg.ignore_handler = bypass_ignore
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.bypass", bypass_pkg)
    monkeypatch.setitem(
        sys.modules,
        "aipass.seedgo.apps.handlers.bypass.ignore_handler",
        bypass_ignore,
    )

    # -- rich.console (diagnostics_check imports Console directly) ----------
    mock_console_cls = MagicMock()
    rich_console_mod = MagicMock()
    rich_console_mod.Console = mock_console_cls
    monkeypatch.setitem(sys.modules, "rich", MagicMock())
    monkeypatch.setitem(sys.modules, "rich.console", rich_console_mod)

    # Force re-imports so modules pick up fresh mocks
    for mod_name in [
        "aipass.seedgo.apps.handlers.aipass_proof.plugin_integrity",
        "aipass.seedgo.apps.handlers.diagnostics.diagnostics_check",
    ]:
        monkeypatch.delitem(sys.modules, mod_name, raising=False)


# ---------------------------------------------------------------------------
# Helper to build typed parent dicts for AST tests
# ---------------------------------------------------------------------------


def _parents(*pairs: tuple[ast.AST, ast.AST]) -> dict[int, ast.AST]:
    """Build a child-id -> parent mapping accepted by plugin_integrity helpers."""
    return {id(child): parent for child, parent in pairs}


# ===========================================================================
# PLUGIN INTEGRITY -- _resolve_target_modules
# ===========================================================================


class TestResolveTargetModules:
    """Tests for _resolve_target_modules."""

    def test_returns_five_modules(self, tmp_path):
        """Target module list always has five entries."""
        from aipass.seedgo.apps.handlers.aipass_proof.plugin_integrity import (
            _resolve_target_modules,
        )

        pack_dir = tmp_path / "apps" / "handlers" / "aipass_standards"
        pack_dir.mkdir(parents=True)
        result = _resolve_target_modules(pack_dir)
        assert len(result) == 5

    def test_labels_correct(self, tmp_path):
        """Target module labels match expected file names."""
        from aipass.seedgo.apps.handlers.aipass_proof.plugin_integrity import (
            _resolve_target_modules,
        )

        pack_dir = tmp_path / "apps" / "handlers" / "aipass_standards"
        pack_dir.mkdir(parents=True)
        result = _resolve_target_modules(pack_dir)
        labels = [m["label"] for m in result]
        assert "standards_audit.py" in labels
        assert "branch_audit.py" in labels
        assert "audit_display.py" in labels
        assert "standards_query.py" in labels
        assert "seedgo.py" in labels

    def test_cosmetic_flag(self, tmp_path):
        """audit_display.py is marked cosmetic; others are not."""
        from aipass.seedgo.apps.handlers.aipass_proof.plugin_integrity import (
            _resolve_target_modules,
        )

        pack_dir = tmp_path / "apps" / "handlers" / "aipass_standards"
        pack_dir.mkdir(parents=True)
        result = _resolve_target_modules(pack_dir)
        cosmetic_map = {m["label"]: m["cosmetic"] for m in result}
        assert cosmetic_map["audit_display.py"] is True
        assert cosmetic_map["standards_audit.py"] is False


# ===========================================================================
# PLUGIN INTEGRITY -- _discover_standard_names
# ===========================================================================


class TestDiscoverStandardNames:
    """Tests for _discover_standard_names."""

    def test_nonexistent_directory(self, tmp_path):
        """Returns empty list for nonexistent directory."""
        from aipass.seedgo.apps.handlers.aipass_proof.plugin_integrity import (
            _discover_standard_names,
        )

        result = _discover_standard_names(tmp_path / "missing")
        assert result == []

    def test_no_check_files(self, tmp_path):
        """Returns empty list when directory has no *_check.py files."""
        from aipass.seedgo.apps.handlers.aipass_proof.plugin_integrity import (
            _discover_standard_names,
        )

        (tmp_path / "readme.py").write_text("pass", encoding="utf-8")
        result = _discover_standard_names(tmp_path)
        assert result == []

    def test_discovers_names(self, tmp_path):
        """Discovers standard names from *_check.py filenames."""
        from aipass.seedgo.apps.handlers.aipass_proof.plugin_integrity import (
            _discover_standard_names,
        )

        (tmp_path / "meta_check.py").write_text("pass", encoding="utf-8")
        (tmp_path / "naming_check.py").write_text("pass", encoding="utf-8")
        (tmp_path / "cli_check.py").write_text("pass", encoding="utf-8")
        result = _discover_standard_names(tmp_path)
        assert sorted(result) == ["cli", "meta", "naming"]


# ===========================================================================
# PLUGIN INTEGRITY -- AST helpers
# ===========================================================================


class TestEnclosingContext:
    """Tests for _enclosing_context."""

    def test_module_level(self):
        """Returns '<module level>' when no parent function/class."""
        from aipass.seedgo.apps.handlers.aipass_proof.plugin_integrity import (
            _enclosing_context,
        )

        node = ast.Constant(value="x")
        result = _enclosing_context(node, {})
        assert result == "<module level>"

    def test_inside_function(self):
        """Returns function context when inside a def."""
        from aipass.seedgo.apps.handlers.aipass_proof.plugin_integrity import (
            _enclosing_context,
        )

        func_node = ast.FunctionDef(
            name="my_func",
            args=ast.arguments(
                posonlyargs=[],
                args=[],
                kwonlyargs=[],
                kw_defaults=[],
                defaults=[],
            ),
            body=[],
            decorator_list=[],
        )
        child_node = ast.Constant(value="test")
        parents = _parents((child_node, func_node))
        result = _enclosing_context(child_node, parents)
        assert "def my_func()" in result

    def test_inside_class_and_method(self):
        """Returns nested context for class > method."""
        from aipass.seedgo.apps.handlers.aipass_proof.plugin_integrity import (
            _enclosing_context,
        )

        class_node = ast.ClassDef(
            name="MyClass",
            bases=[],
            keywords=[],
            body=[],
            decorator_list=[],
        )
        method_node = ast.FunctionDef(
            name="do_stuff",
            args=ast.arguments(
                posonlyargs=[],
                args=[],
                kwonlyargs=[],
                kw_defaults=[],
                defaults=[],
            ),
            body=[],
            decorator_list=[],
        )
        child_node = ast.Constant(value="x")
        parents = _parents(
            (child_node, method_node),
            (method_node, class_node),
        )
        result = _enclosing_context(child_node, parents)
        assert "class MyClass" in result
        assert "def do_stuff()" in result

    def test_inside_async_function(self):
        """Returns context for async function."""
        from aipass.seedgo.apps.handlers.aipass_proof.plugin_integrity import (
            _enclosing_context,
        )

        async_func = ast.AsyncFunctionDef(
            name="async_work",
            args=ast.arguments(
                posonlyargs=[],
                args=[],
                kwonlyargs=[],
                kw_defaults=[],
                defaults=[],
            ),
            body=[],
            decorator_list=[],
        )
        child = ast.Constant(value="x")
        parents = _parents((child, async_func))
        result = _enclosing_context(child, parents)
        assert "def async_work()" in result


class TestIsDocstring:
    """Tests for _is_docstring."""

    def test_actual_docstring(self):
        """Detects module-level docstring."""
        from aipass.seedgo.apps.handlers.aipass_proof.plugin_integrity import (
            _is_docstring,
        )

        source = '"""This is a docstring."""\nx = 1\n'
        tree = ast.parse(source)
        first_expr = tree.body[0]
        assert isinstance(first_expr, ast.Expr)
        node = first_expr.value
        assert isinstance(node, ast.Constant)
        assert _is_docstring(node, tree) is True

    def test_non_docstring(self):
        """Regular string literal is not a docstring."""
        from aipass.seedgo.apps.handlers.aipass_proof.plugin_integrity import (
            _is_docstring,
        )

        source = 'x = "not a docstring"\n'
        tree = ast.parse(source)
        constants = [n for n in ast.walk(tree) if isinstance(n, ast.Constant) and n.value == "not a docstring"]
        assert len(constants) == 1, f"expected exactly one string constant in the AST, got {constants}"
        assert _is_docstring(constants[0], tree) is False

    def test_function_docstring(self):
        """Detects function-level docstring."""
        from aipass.seedgo.apps.handlers.aipass_proof.plugin_integrity import (
            _is_docstring,
        )

        source = 'def foo():\n    """My doc."""\n    pass\n'
        tree = ast.parse(source)
        func = tree.body[0]
        assert isinstance(func, ast.FunctionDef)
        first_stmt = func.body[0]
        assert isinstance(first_stmt, ast.Expr)
        node = first_stmt.value
        assert isinstance(node, ast.Constant)
        assert _is_docstring(node, tree) is True


class TestIsDisplayString:
    """Tests for _is_display_string."""

    def test_inside_fstring(self):
        """String inside f-string is display text."""
        from aipass.seedgo.apps.handlers.aipass_proof.plugin_integrity import (
            _is_display_string,
        )

        child = ast.Constant(value="hello")
        fstring = ast.JoinedStr(values=[child])
        assert _is_display_string(child, _parents((child, fstring))) is True

    def test_no_parent(self):
        """Node with no parent returns False."""
        from aipass.seedgo.apps.handlers.aipass_proof.plugin_integrity import (
            _is_display_string,
        )

        child = ast.Constant(value="hello")
        assert _is_display_string(child, {}) is False

    def test_print_call(self):
        """String passed to console.print() is display text."""
        from aipass.seedgo.apps.handlers.aipass_proof.plugin_integrity import (
            _is_display_string,
        )

        child = ast.Constant(value="hello")
        func = ast.Attribute(
            value=ast.Name(id="console", ctx=ast.Load()),
            attr="print",
            ctx=ast.Load(),
        )
        call = ast.Call(func=func, args=[child], keywords=[])
        assert _is_display_string(child, _parents((child, call))) is True

    def test_logger_info_call(self):
        """String passed to logger.info() is display text."""
        from aipass.seedgo.apps.handlers.aipass_proof.plugin_integrity import (
            _is_display_string,
        )

        child = ast.Constant(value="hello")
        func = ast.Attribute(
            value=ast.Name(id="logger", ctx=ast.Load()),
            attr="info",
            ctx=ast.Load(),
        )
        call = ast.Call(func=func, args=[child], keywords=[])
        assert _is_display_string(child, _parents((child, call))) is True

    def test_logger_error_call(self):
        """String passed to logger.error() is display text."""
        from aipass.seedgo.apps.handlers.aipass_proof.plugin_integrity import (
            _is_display_string,
        )

        child = ast.Constant(value="hello")
        func = ast.Attribute(
            value=ast.Name(id="logger", ctx=ast.Load()),
            attr="error",
            ctx=ast.Load(),
        )
        call = ast.Call(func=func, args=[child], keywords=[])
        assert _is_display_string(child, _parents((child, call))) is True

    def test_logger_warning_call(self):
        """String passed to logger.warning() is display text."""
        from aipass.seedgo.apps.handlers.aipass_proof.plugin_integrity import (
            _is_display_string,
        )

        child = ast.Constant(value="hello")
        func = ast.Attribute(
            value=ast.Name(id="logger", ctx=ast.Load()),
            attr="warning",
            ctx=ast.Load(),
        )
        call = ast.Call(func=func, args=[child], keywords=[])
        assert _is_display_string(child, _parents((child, call))) is True

    def test_logger_debug_call(self):
        """String passed to logger.debug() is display text."""
        from aipass.seedgo.apps.handlers.aipass_proof.plugin_integrity import (
            _is_display_string,
        )

        child = ast.Constant(value="hello")
        func = ast.Attribute(
            value=ast.Name(id="logger", ctx=ast.Load()),
            attr="debug",
            ctx=ast.Load(),
        )
        call = ast.Call(func=func, args=[child], keywords=[])
        assert _is_display_string(child, _parents((child, call))) is True

    def test_header_name_call(self):
        """String passed to header() function call is display text."""
        from aipass.seedgo.apps.handlers.aipass_proof.plugin_integrity import (
            _is_display_string,
        )

        child = ast.Constant(value="hello")
        func = ast.Name(id="header", ctx=ast.Load())
        call = ast.Call(func=func, args=[child], keywords=[])
        assert _is_display_string(child, _parents((child, call))) is True

    def test_error_name_call(self):
        """String passed to error() function call is display text."""
        from aipass.seedgo.apps.handlers.aipass_proof.plugin_integrity import (
            _is_display_string,
        )

        child = ast.Constant(value="hello")
        func = ast.Name(id="error", ctx=ast.Load())
        call = ast.Call(func=func, args=[child], keywords=[])
        assert _is_display_string(child, _parents((child, call))) is True

    def test_warning_name_call(self):
        """String passed to warning() function call is display text."""
        from aipass.seedgo.apps.handlers.aipass_proof.plugin_integrity import (
            _is_display_string,
        )

        child = ast.Constant(value="hello")
        func = ast.Name(id="warning", ctx=ast.Load())
        call = ast.Call(func=func, args=[child], keywords=[])
        assert _is_display_string(child, _parents((child, call))) is True

    def test_keyword_arg_in_print_call(self):
        """Keyword arg value inside console.print() is display text."""
        from aipass.seedgo.apps.handlers.aipass_proof.plugin_integrity import (
            _is_display_string,
        )

        child = ast.Constant(value="hello")
        kw = ast.keyword(arg="style", value=child)
        func = ast.Attribute(
            value=ast.Name(id="console", ctx=ast.Load()),
            attr="print",
            ctx=ast.Load(),
        )
        call = ast.Call(func=func, args=[], keywords=[kw])
        parents = _parents((child, kw), (kw, call))
        assert _is_display_string(child, parents) is True

    def test_keyword_arg_in_log_operation(self):
        """Keyword arg value inside .log_operation() is display text."""
        from aipass.seedgo.apps.handlers.aipass_proof.plugin_integrity import (
            _is_display_string,
        )

        child = ast.Constant(value="hello")
        kw = ast.keyword(arg="data", value=child)
        func = ast.Attribute(
            value=ast.Name(id="json_handler", ctx=ast.Load()),
            attr="log_operation",
            ctx=ast.Load(),
        )
        call = ast.Call(func=func, args=[], keywords=[kw])
        parents = _parents((child, kw), (kw, call))
        assert _is_display_string(child, parents) is True

    def test_keyword_arg_in_header_call(self):
        """Keyword arg value inside header() call is display text."""
        from aipass.seedgo.apps.handlers.aipass_proof.plugin_integrity import (
            _is_display_string,
        )

        child = ast.Constant(value="hello")
        kw = ast.keyword(arg="title", value=child)
        func = ast.Name(id="header", ctx=ast.Load())
        call = ast.Call(func=func, args=[], keywords=[kw])
        parents = _parents((child, kw), (kw, call))
        assert _is_display_string(child, parents) is True

    def test_keyword_arg_in_error_call(self):
        """Keyword arg value inside error() call is display text."""
        from aipass.seedgo.apps.handlers.aipass_proof.plugin_integrity import (
            _is_display_string,
        )

        child = ast.Constant(value="hello")
        kw = ast.keyword(arg="msg", value=child)
        func = ast.Name(id="error", ctx=ast.Load())
        call = ast.Call(func=func, args=[], keywords=[kw])
        parents = _parents((child, kw), (kw, call))
        assert _is_display_string(child, parents) is True

    def test_keyword_arg_in_warning_call(self):
        """Keyword arg value inside warning() call is display text."""
        from aipass.seedgo.apps.handlers.aipass_proof.plugin_integrity import (
            _is_display_string,
        )

        child = ast.Constant(value="hello")
        kw = ast.keyword(arg="msg", value=child)
        func = ast.Name(id="warning", ctx=ast.Load())
        call = ast.Call(func=func, args=[], keywords=[kw])
        parents = _parents((child, kw), (kw, call))
        assert _is_display_string(child, parents) is True

    def test_non_display_context(self):
        """String in normal assignment context is not display text."""
        from aipass.seedgo.apps.handlers.aipass_proof.plugin_integrity import (
            _is_display_string,
        )

        child = ast.Constant(value="hello")
        assign = ast.Assign(
            targets=[ast.Name(id="x", ctx=ast.Store())],
            value=child,
        )
        assert _is_display_string(child, _parents((child, assign))) is False

    def test_keyword_arg_in_non_display_call(self):
        """Keyword arg value in a non-display call is not display text."""
        from aipass.seedgo.apps.handlers.aipass_proof.plugin_integrity import (
            _is_display_string,
        )

        child = ast.Constant(value="hello")
        kw = ast.keyword(arg="name", value=child)
        func = ast.Name(id="do_work", ctx=ast.Load())
        call = ast.Call(func=func, args=[], keywords=[kw])
        parents = _parents((child, kw), (kw, call))
        assert _is_display_string(child, parents) is False


class TestIsDictKeyAccess:
    """Tests for _is_dict_key_access."""

    def test_get_call(self):
        """result.get('key') is dict key access."""
        from aipass.seedgo.apps.handlers.aipass_proof.plugin_integrity import (
            _is_dict_key_access,
        )

        child = ast.Constant(value="key")
        func = ast.Attribute(
            value=ast.Name(id="result", ctx=ast.Load()),
            attr="get",
            ctx=ast.Load(),
        )
        call = ast.Call(func=func, args=[child], keywords=[])
        assert _is_dict_key_access(child, _parents((child, call))) is True

    def test_subscript(self):
        """result['key'] is dict key access."""
        from aipass.seedgo.apps.handlers.aipass_proof.plugin_integrity import (
            _is_dict_key_access,
        )

        child = ast.Constant(value="key")
        subscript = ast.Subscript(
            value=ast.Name(id="result", ctx=ast.Load()),
            slice=child,
            ctx=ast.Load(),
        )
        assert _is_dict_key_access(child, _parents((child, subscript))) is True

    def test_no_parent(self):
        """Node with no parent returns False."""
        from aipass.seedgo.apps.handlers.aipass_proof.plugin_integrity import (
            _is_dict_key_access,
        )

        child = ast.Constant(value="key")
        assert _is_dict_key_access(child, {}) is False

    def test_non_get_attribute_call(self):
        """result.append('key') is not dict key access."""
        from aipass.seedgo.apps.handlers.aipass_proof.plugin_integrity import (
            _is_dict_key_access,
        )

        child = ast.Constant(value="key")
        func = ast.Attribute(
            value=ast.Name(id="result", ctx=ast.Load()),
            attr="append",
            ctx=ast.Load(),
        )
        call = ast.Call(func=func, args=[child], keywords=[])
        assert _is_dict_key_access(child, _parents((child, call))) is False

    def test_plain_function_call(self):
        """do_work('key') is not dict key access."""
        from aipass.seedgo.apps.handlers.aipass_proof.plugin_integrity import (
            _is_dict_key_access,
        )

        child = ast.Constant(value="key")
        func = ast.Name(id="do_work", ctx=ast.Load())
        call = ast.Call(func=func, args=[child], keywords=[])
        assert _is_dict_key_access(child, _parents((child, call))) is False


# ===========================================================================
# PLUGIN INTEGRITY -- _scan_file_ast
# ===========================================================================


class TestScanFileAst:
    """Tests for _scan_file_ast."""

    def test_clean_file(self, tmp_path):
        """File with no standard name references returns empty."""
        from aipass.seedgo.apps.handlers.aipass_proof.plugin_integrity import (
            _scan_file_ast,
        )

        f = tmp_path / "clean.py"
        f.write_text('x = "hello"\n', encoding="utf-8")
        result = _scan_file_ast(f, ["meta", "naming"])
        assert result == []

    def test_syntax_error_file(self, tmp_path):
        """File with syntax error returns empty and does not crash."""
        from aipass.seedgo.apps.handlers.aipass_proof.plugin_integrity import (
            _scan_file_ast,
        )

        f = tmp_path / "broken.py"
        f.write_text("def foo(\n", encoding="utf-8")
        result = _scan_file_ast(f, ["meta"])
        assert result == []

    def test_finds_hardcoded_standard_name(self, tmp_path):
        """Detects non-ambiguous standard name as string literal."""
        from aipass.seedgo.apps.handlers.aipass_proof.plugin_integrity import (
            _scan_file_ast,
        )

        f = tmp_path / "hardcoded.py"
        f.write_text('x = "custom_standard"\n', encoding="utf-8")
        result = _scan_file_ast(f, ["custom_standard"])
        assert len(result) == 1
        assert result[0]["name"] == "custom_standard"
        assert result[0]["kind"] == "ast_string_literal"

    def test_skips_ambiguous_names(self, tmp_path):
        """Ambiguous standard names are not flagged by AST scanner."""
        from aipass.seedgo.apps.handlers.aipass_proof.plugin_integrity import (
            _scan_file_ast,
        )

        f = tmp_path / "ambiguous.py"
        f.write_text('x = "meta"\n', encoding="utf-8")
        result = _scan_file_ast(f, ["meta"])
        assert result == []

    def test_skips_docstrings(self, tmp_path):
        """Standard name in docstring is not flagged."""
        from aipass.seedgo.apps.handlers.aipass_proof.plugin_integrity import (
            _scan_file_ast,
        )

        f = tmp_path / "docstr.py"
        f.write_text('"""custom_standard is great."""\nx = 1\n', encoding="utf-8")
        result = _scan_file_ast(f, ["custom_standard"])
        assert result == []

    def test_skips_display_strings(self, tmp_path):
        """Standard name in display call is not flagged."""
        from aipass.seedgo.apps.handlers.aipass_proof.plugin_integrity import (
            _scan_file_ast,
        )

        f = tmp_path / "display.py"
        f.write_text(
            'import logger\nlogger.info("custom_standard")\n',
            encoding="utf-8",
        )
        result = _scan_file_ast(f, ["custom_standard"])
        assert result == []

    def test_skips_dict_key_access(self, tmp_path):
        """Standard name as dict key access is not flagged."""
        from aipass.seedgo.apps.handlers.aipass_proof.plugin_integrity import (
            _scan_file_ast,
        )

        f = tmp_path / "dictkey.py"
        f.write_text('result = data.get("custom_standard")\n', encoding="utf-8")
        result = _scan_file_ast(f, ["custom_standard"])
        assert result == []

    def test_non_matching_name_not_flagged(self, tmp_path):
        """String literal not matching any standard name is not flagged."""
        from aipass.seedgo.apps.handlers.aipass_proof.plugin_integrity import (
            _scan_file_ast,
        )

        f = tmp_path / "other.py"
        f.write_text('x = "something_else"\n', encoding="utf-8")
        result = _scan_file_ast(f, ["custom_standard"])
        assert result == []


# ===========================================================================
# PLUGIN INTEGRITY -- _scan_file_regex
# ===========================================================================


class TestScanFileRegex:
    """Tests for _scan_file_regex."""

    def test_clean_file(self, tmp_path):
        """File with no suspicious patterns returns empty."""
        from aipass.seedgo.apps.handlers.aipass_proof.plugin_integrity import (
            _scan_file_regex,
        )

        f = tmp_path / "clean.py"
        f.write_text('x = "hello"\n', encoding="utf-8")
        result = _scan_file_regex(f, ["meta"])
        assert result == []

    def test_hardcoded_function_call(self, tmp_path):
        """Detects check_<standard>( pattern."""
        from aipass.seedgo.apps.handlers.aipass_proof.plugin_integrity import (
            _scan_file_regex,
        )

        f = tmp_path / "func_call.py"
        f.write_text("result = check_custom_std(path)\n", encoding="utf-8")
        result = _scan_file_regex(f, ["custom_std"])
        assert len(result) >= 1
        kinds = [r["kind"] for r in result]
        assert "hardcoded_function_call" in kinds

    def test_hardcoded_violation_key(self, tmp_path):
        """Detects <standard>_violations pattern."""
        from aipass.seedgo.apps.handlers.aipass_proof.plugin_integrity import (
            _scan_file_regex,
        )

        f = tmp_path / "viol_key.py"
        f.write_text("x = custom_std_violations\n", encoding="utf-8")
        result = _scan_file_regex(f, ["custom_std"])
        assert len(result) >= 1
        kinds = [r["kind"] for r in result]
        assert "hardcoded_violation_key" in kinds

    def test_hardcoded_branch_condition(self, tmp_path):
        """Detects == 'standard' pattern."""
        from aipass.seedgo.apps.handlers.aipass_proof.plugin_integrity import (
            _scan_file_regex,
        )

        f = tmp_path / "branch_cond.py"
        f.write_text("if name == 'custom_std':\n    pass\n", encoding="utf-8")
        result = _scan_file_regex(f, ["custom_std"])
        assert len(result) >= 1
        kinds = [r["kind"] for r in result]
        assert "hardcoded_branch" in kinds

    def test_skips_comment_lines(self, tmp_path):
        """Pure comment lines are skipped."""
        from aipass.seedgo.apps.handlers.aipass_proof.plugin_integrity import (
            _scan_file_regex,
        )

        f = tmp_path / "comments.py"
        f.write_text("# check_custom_std(path)\n", encoding="utf-8")
        result = _scan_file_regex(f, ["custom_std"])
        assert result == []

    def test_skips_docstring_content(self, tmp_path):
        """Content inside triple-quoted docstrings is skipped."""
        from aipass.seedgo.apps.handlers.aipass_proof.plugin_integrity import (
            _scan_file_regex,
        )

        f = tmp_path / "docstr.py"
        f.write_text(
            '"""\ncheck_custom_std(path)\n"""\npass\n',
            encoding="utf-8",
        )
        result = _scan_file_regex(f, ["custom_std"])
        assert result == []

    def test_inline_comment_stripped(self, tmp_path):
        """Code before inline comment is still checked."""
        from aipass.seedgo.apps.handlers.aipass_proof.plugin_integrity import (
            _scan_file_regex,
        )

        f = tmp_path / "inline.py"
        f.write_text(
            "result = check_custom_std(path)  # run check\n",
            encoding="utf-8",
        )
        result = _scan_file_regex(f, ["custom_std"])
        assert len(result) >= 1

    def test_double_quote_branch(self, tmp_path):
        """Detects == 'standard' with double quotes."""
        from aipass.seedgo.apps.handlers.aipass_proof.plugin_integrity import (
            _scan_file_regex,
        )

        f = tmp_path / "dquote.py"
        f.write_text('if name == "custom_std":\n    pass\n', encoding="utf-8")
        result = _scan_file_regex(f, ["custom_std"])
        kinds = [r["kind"] for r in result]
        assert "hardcoded_branch" in kinds

    def test_single_quote_docstring(self, tmp_path):
        """Single-quote triple docstrings are tracked."""
        from aipass.seedgo.apps.handlers.aipass_proof.plugin_integrity import (
            _scan_file_regex,
        )

        f = tmp_path / "squote_doc.py"
        f.write_text(
            "'''\ncheck_custom_std(path)\n'''\npass\n",
            encoding="utf-8",
        )
        result = _scan_file_regex(f, ["custom_std"])
        assert result == []


# ===========================================================================
# PLUGIN INTEGRITY -- scan (public interface)
# ===========================================================================


class TestPluginIntegrityScan:
    """Tests for the public scan() function."""

    def test_all_modules_missing(self, tmp_path):
        """All target modules missing results in 'missing' status."""
        from aipass.seedgo.apps.handlers.aipass_proof.plugin_integrity import (
            scan,
        )

        pack_dir = tmp_path / "apps" / "handlers" / "aipass_standards"
        pack_dir.mkdir(parents=True)
        result = scan(pack_dir)
        assert result["passed"] is True
        assert result["missing_count"] == 5
        assert result["flagged_count"] == 0

    def test_clean_module(self, tmp_path):
        """Module with no issues is marked clean."""
        from aipass.seedgo.apps.handlers.aipass_proof.plugin_integrity import (
            scan,
        )

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
        from aipass.seedgo.apps.handlers.aipass_proof.plugin_integrity import (
            scan,
        )

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
        from aipass.seedgo.apps.handlers.aipass_proof.plugin_integrity import (
            scan,
        )

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
        from aipass.seedgo.apps.handlers.aipass_proof.plugin_integrity import (
            scan,
        )

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
        from aipass.seedgo.apps.handlers.aipass_proof.plugin_integrity import (
            scan,
        )

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
        from aipass.seedgo.apps.handlers.aipass_proof.plugin_integrity import (
            scan,
        )

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

    def test_matching_pattern(self):
        """File matching a pattern is ignored."""
        from aipass.seedgo.apps.handlers.diagnostics.diagnostics_check import (
            should_ignore_file,
        )

        assert should_ignore_file("/home/user/venv/lib/file.py", ["venv"]) is True

    def test_no_matching_pattern(self):
        """File not matching any pattern is not ignored."""
        from aipass.seedgo.apps.handlers.diagnostics.diagnostics_check import (
            should_ignore_file,
        )

        result = should_ignore_file("/home/user/src/file.py", ["venv", "node_modules"])
        assert result is False

    def test_empty_patterns(self):
        """Empty pattern list means nothing is ignored."""
        from aipass.seedgo.apps.handlers.diagnostics.diagnostics_check import (
            should_ignore_file,
        )

        assert should_ignore_file("/any/file.py", []) is False


# ===========================================================================
# DIAGNOSTICS CHECK -- check_file
# ===========================================================================


class TestCheckFile:
    """Tests for check_file."""

    def test_nonexistent_file(self, tmp_path):
        """Nonexistent file returns error dict."""
        from aipass.seedgo.apps.handlers.diagnostics.diagnostics_check import (
            check_file,
        )

        result = check_file(str(tmp_path / "missing.py"))
        assert result["errors"] == 0
        assert "error" in result
        assert "not found" in result["error"].lower()

    def test_non_python_file(self, tmp_path):
        """Non-.py file is skipped."""
        from aipass.seedgo.apps.handlers.diagnostics.diagnostics_check import (
            check_file,
        )

        f = tmp_path / "data.txt"
        f.write_text("hello", encoding="utf-8")
        result = check_file(str(f))
        assert result["errors"] == 0
        assert "skipped" in result

    def test_successful_pyright_check(self, tmp_path):
        """Pyright with clean output returns zero errors."""
        from aipass.seedgo.apps.handlers.diagnostics.diagnostics_check import (
            check_file,
        )

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
        from aipass.seedgo.apps.handlers.diagnostics.diagnostics_check import (
            check_file,
        )

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
        from aipass.seedgo.apps.handlers.diagnostics.diagnostics_check import (
            check_file,
        )

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
        from aipass.seedgo.apps.handlers.diagnostics.diagnostics_check import (
            check_file,
        )

        f = tmp_path / "slow.py"
        f.write_text("x = 1\n", encoding="utf-8")

        with patch("aipass.seedgo.apps.handlers.diagnostics.diagnostics_check.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd="pyright", timeout=30)
            result = check_file(str(f))

        assert "error" in result
        assert "timed out" in result["error"].lower()

    def test_pyright_generic_exception(self, tmp_path):
        """Generic exception during pyright returns error dict."""
        from aipass.seedgo.apps.handlers.diagnostics.diagnostics_check import (
            check_file,
        )

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
        from aipass.seedgo.apps.handlers.diagnostics.diagnostics_check import (
            check_directory,
        )

        result = check_directory(str(tmp_path / "nonexistent"))
        assert result["total_files"] == 0
        assert "error" in result

    def test_empty_directory(self, tmp_path):
        """Empty directory with no diagnostics returns zero totals."""
        from aipass.seedgo.apps.handlers.diagnostics.diagnostics_check import (
            check_directory,
        )

        pyright_out = json.dumps({"generalDiagnostics": [], "summary": {"filesAnalyzed": 0}})
        with patch("aipass.seedgo.apps.handlers.diagnostics.diagnostics_check.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout=pyright_out, stderr="")
            result = check_directory(str(tmp_path))

        assert result["total_errors"] == 0
        assert result["total_files"] == 0

    def test_directory_with_errors(self, tmp_path):
        """Directory with pyright errors parses and groups correctly."""
        from aipass.seedgo.apps.handlers.diagnostics.diagnostics_check import (
            check_directory,
        )

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
        """Files matching ignore patterns are skipped."""
        from aipass.seedgo.apps.handlers.diagnostics.diagnostics_check import (
            check_directory,
        )

        diags = [
            {
                "file": "/src/venv/lib/bad.py",
                "severity": "error",
                "range": {"start": {"line": 1}},
                "message": "Err",
                "rule": "r1",
            },
            {
                "file": "/src/good.py",
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
            patch(f"{mod_prefix}.get_audit_ignore_patterns") as mock_ignore,
        ):
            mock_ignore.return_value = ["venv"]
            mock_run.return_value = MagicMock(stdout=pyright_out, stderr="")
            result = check_directory(str(tmp_path))

        assert result["total_errors"] == 1
        assert len(result["results"]) == 1

    def test_directory_json_decode_error(self, tmp_path):
        """Non-JSON pyright output for directory returns error."""
        from aipass.seedgo.apps.handlers.diagnostics.diagnostics_check import (
            check_directory,
        )

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
        from aipass.seedgo.apps.handlers.diagnostics.diagnostics_check import (
            check_directory,
        )

        with patch("aipass.seedgo.apps.handlers.diagnostics.diagnostics_check.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd="pyright", timeout=300)
            result = check_directory(str(tmp_path))

        assert "error" in result
        assert "timed out" in result["error"].lower()

    def test_directory_generic_exception(self, tmp_path):
        """Generic exception during directory check returns error."""
        from aipass.seedgo.apps.handlers.diagnostics.diagnostics_check import (
            check_directory,
        )

        with patch("aipass.seedgo.apps.handlers.diagnostics.diagnostics_check.subprocess.run") as mock_run:
            mock_run.side_effect = RuntimeError("unexpected")
            result = check_directory(str(tmp_path))

        assert "error" in result
        assert "unexpected" in result["error"]


# ===========================================================================
# DIAGNOSTICS CHECK -- _discover_pack_configs
# ===========================================================================


class TestDiscoverPackConfigs:
    """Tests for _discover_pack_configs."""

    def test_no_handlers_dir(self, monkeypatch):
        """Returns empty when HANDLERS_DIR does not exist."""
        from aipass.seedgo.apps.handlers.diagnostics import diagnostics_check

        monkeypatch.setattr(diagnostics_check, "HANDLERS_DIR", Path("/nonexistent/dir"))
        result = diagnostics_check._discover_pack_configs()
        assert result == []

    def test_no_standards_dirs(self, tmp_path, monkeypatch):
        """Returns empty when no *_standards directories exist."""
        from aipass.seedgo.apps.handlers.diagnostics import diagnostics_check

        monkeypatch.setattr(diagnostics_check, "HANDLERS_DIR", tmp_path)
        (tmp_path / "other_dir").mkdir()
        result = diagnostics_check._discover_pack_configs()
        assert result == []

    def test_standards_dir_without_config(self, tmp_path, monkeypatch):
        """Returns empty when *_standards dir has no diagnostics.json."""
        from aipass.seedgo.apps.handlers.diagnostics import diagnostics_check

        monkeypatch.setattr(diagnostics_check, "HANDLERS_DIR", tmp_path)
        (tmp_path / "aipass_standards").mkdir()
        result = diagnostics_check._discover_pack_configs()
        assert result == []

    def test_valid_config(self, tmp_path, monkeypatch):
        """Returns config when valid diagnostics.json exists."""
        from aipass.seedgo.apps.handlers.diagnostics import diagnostics_check

        monkeypatch.setattr(diagnostics_check, "HANDLERS_DIR", tmp_path)
        std_dir = tmp_path / "aipass_standards"
        std_dir.mkdir()
        config = {"runners": {"python": True}}
        (std_dir / "diagnostics.json").write_text(json.dumps(config), encoding="utf-8")

        result = diagnostics_check._discover_pack_configs()
        assert len(result) == 1
        assert result[0]["pack_name"] == "aipass_standards"
        assert result[0]["config"] == config

    def test_malformed_config_skipped(self, tmp_path, monkeypatch):
        """Malformed JSON is skipped gracefully."""
        from aipass.seedgo.apps.handlers.diagnostics import diagnostics_check

        monkeypatch.setattr(diagnostics_check, "HANDLERS_DIR", tmp_path)
        std_dir = tmp_path / "test_standards"
        std_dir.mkdir()
        (std_dir / "diagnostics.json").write_text("not json", encoding="utf-8")

        result = diagnostics_check._discover_pack_configs()
        assert result == []

    def test_non_directory_skipped(self, tmp_path, monkeypatch):
        """Files (not directories) in HANDLERS_DIR are skipped."""
        from aipass.seedgo.apps.handlers.diagnostics import diagnostics_check

        monkeypatch.setattr(diagnostics_check, "HANDLERS_DIR", tmp_path)
        (tmp_path / "some_standards").write_text("file", encoding="utf-8")
        result = diagnostics_check._discover_pack_configs()
        assert result == []


# ===========================================================================
# DIAGNOSTICS CHECK -- _get_enabled_runners_from_config
# ===========================================================================


class TestGetEnabledRunners:
    """Tests for _get_enabled_runners_from_config."""

    def test_simple_bool_format(self):
        """Simple bool format: {'python': true}."""
        from aipass.seedgo.apps.handlers.diagnostics.diagnostics_check import (
            _get_enabled_runners_from_config,
        )

        config = {"runners": {"python": True, "typescript": False}}
        result = _get_enabled_runners_from_config(config)
        assert result == ["python"]

    def test_detailed_dict_format(self):
        """Detailed format: {'python': {'enabled': true, ...}}."""
        from aipass.seedgo.apps.handlers.diagnostics.diagnostics_check import (
            _get_enabled_runners_from_config,
        )

        config = {
            "runners": {
                "python": {"enabled": True, "timeout": 60},
                "rust": {"enabled": False},
            }
        }
        result = _get_enabled_runners_from_config(config)
        assert result == ["python"]

    def test_empty_runners(self):
        """Empty runners section returns empty list."""
        from aipass.seedgo.apps.handlers.diagnostics.diagnostics_check import (
            _get_enabled_runners_from_config,
        )

        result = _get_enabled_runners_from_config({"runners": {}})
        assert result == []

    def test_no_runners_key(self):
        """Missing 'runners' key returns empty list."""
        from aipass.seedgo.apps.handlers.diagnostics.diagnostics_check import (
            _get_enabled_runners_from_config,
        )

        result = _get_enabled_runners_from_config({})
        assert result == []

    def test_mixed_formats(self):
        """Mix of bool and dict format works."""
        from aipass.seedgo.apps.handlers.diagnostics.diagnostics_check import (
            _get_enabled_runners_from_config,
        )

        config = {
            "runners": {
                "python": True,
                "rust": {"enabled": True},
                "go": False,
                "java": {"enabled": False},
            }
        }
        result = _get_enabled_runners_from_config(config)
        assert "python" in result
        assert "rust" in result
        assert "go" not in result
        assert "java" not in result


# ===========================================================================
# DIAGNOSTICS CHECK -- _run_runner
# ===========================================================================


class TestRunRunner:
    """Tests for _run_runner."""

    def test_runner_not_found(self, tmp_path, monkeypatch):
        """Returns None when runner file does not exist."""
        from aipass.seedgo.apps.handlers.diagnostics import diagnostics_check

        monkeypatch.setattr(diagnostics_check, "DIAGNOSTICS_DIR", tmp_path)
        result = diagnostics_check._run_runner("nonexistent", "/branch")
        assert result is None

    def test_runner_empty_file(self, tmp_path, monkeypatch):
        """Returns None when runner file is empty (0 bytes)."""
        from aipass.seedgo.apps.handlers.diagnostics import diagnostics_check

        monkeypatch.setattr(diagnostics_check, "DIAGNOSTICS_DIR", tmp_path)
        (tmp_path / "empty_diagnostics.py").write_text("", encoding="utf-8")
        result = diagnostics_check._run_runner("empty", "/branch")
        assert result is None

    def test_runner_whitespace_only(self, tmp_path, monkeypatch):
        """Returns None when runner file is whitespace only."""
        from aipass.seedgo.apps.handlers.diagnostics import diagnostics_check

        monkeypatch.setattr(diagnostics_check, "DIAGNOSTICS_DIR", tmp_path)
        (tmp_path / "blank_diagnostics.py").write_text("   \n\n  \n", encoding="utf-8")
        result = diagnostics_check._run_runner("blank", "/branch")
        assert result is None

    def test_runner_import_failure(self, tmp_path, monkeypatch):
        """Returns None when runner module fails to import."""
        from aipass.seedgo.apps.handlers.diagnostics import diagnostics_check

        monkeypatch.setattr(diagnostics_check, "DIAGNOSTICS_DIR", tmp_path)
        (tmp_path / "broken_diagnostics.py").write_text("import nonexistent_module_xyz\n", encoding="utf-8")

        with patch.object(
            diagnostics_check.importlib,
            "import_module",
            side_effect=ImportError("no module"),
        ):
            result = diagnostics_check._run_runner("broken", "/branch")

        assert result is None

    def test_runner_no_check_branch(self, tmp_path, monkeypatch):
        """Returns None when runner module has no check_branch function."""
        from aipass.seedgo.apps.handlers.diagnostics import diagnostics_check

        monkeypatch.setattr(diagnostics_check, "DIAGNOSTICS_DIR", tmp_path)
        (tmp_path / "nofunc_diagnostics.py").write_text("x = 1\n", encoding="utf-8")

        mock_module = MagicMock(spec=[])
        with patch.object(
            diagnostics_check.importlib,
            "import_module",
            return_value=mock_module,
        ):
            result = diagnostics_check._run_runner("nofunc", "/branch")

        assert result is None

    def test_runner_check_branch_raises(self, tmp_path, monkeypatch):
        """Returns None when check_branch raises an exception."""
        from aipass.seedgo.apps.handlers.diagnostics import diagnostics_check

        monkeypatch.setattr(diagnostics_check, "DIAGNOSTICS_DIR", tmp_path)
        (tmp_path / "crashing_diagnostics.py").write_text(
            "def check_branch(b, bypass_rules=None):\n    raise RuntimeError('boom')\n",
            encoding="utf-8",
        )

        mock_module = MagicMock()
        mock_module.check_branch = MagicMock(side_effect=RuntimeError("boom"))
        with patch.object(
            diagnostics_check.importlib,
            "import_module",
            return_value=mock_module,
        ):
            result = diagnostics_check._run_runner("crashing", "/branch")

        assert result is None

    def test_runner_success(self, tmp_path, monkeypatch):
        """Returns result when runner executes successfully."""
        from aipass.seedgo.apps.handlers.diagnostics import diagnostics_check

        monkeypatch.setattr(diagnostics_check, "DIAGNOSTICS_DIR", tmp_path)
        (tmp_path / "good_diagnostics.py").write_text(
            "def check_branch(b, bypass_rules=None):\n    return {}\n",
            encoding="utf-8",
        )

        expected = {"total_errors": 0, "checks": []}
        mock_module = MagicMock()
        mock_module.check_branch = MagicMock(return_value=expected)
        with patch.object(
            diagnostics_check.importlib,
            "import_module",
            return_value=mock_module,
        ):
            result = diagnostics_check._run_runner("good", "/branch")

        assert result == expected

    def test_runner_typo_variant(self, tmp_path, monkeypatch):
        """Falls back to *_diognostics.py typo variant."""
        from aipass.seedgo.apps.handlers.diagnostics import diagnostics_check

        monkeypatch.setattr(diagnostics_check, "DIAGNOSTICS_DIR", tmp_path)
        (tmp_path / "legacy_diognostics.py").write_text(
            "def check_branch(b, bypass_rules=None):\n    return {}\n",
            encoding="utf-8",
        )

        expected = {"total_errors": 0}
        mock_module = MagicMock()
        mock_module.check_branch = MagicMock(return_value=expected)
        with patch.object(
            diagnostics_check.importlib,
            "import_module",
            return_value=mock_module,
        ):
            result = diagnostics_check._run_runner("legacy", "/branch")

        assert result == expected

    def test_runner_ioerror_on_read(self, tmp_path, monkeypatch):
        """Returns None when runner file cannot be read."""
        from aipass.seedgo.apps.handlers.diagnostics import diagnostics_check

        monkeypatch.setattr(diagnostics_check, "DIAGNOSTICS_DIR", tmp_path)
        runner_file = tmp_path / "ioerr_diagnostics.py"
        runner_file.write_text("content\n", encoding="utf-8")

        with patch.object(Path, "read_text", side_effect=IOError("read error")):
            result = diagnostics_check._run_runner("ioerr", "/branch")

        assert result is None


# ===========================================================================
# DIAGNOSTICS CHECK -- check_branch
# ===========================================================================


class TestCheckBranch:
    """Tests for check_branch."""

    def test_no_apps_directory(self, tmp_path):
        """Returns passed=True when no apps/ directory exists."""
        from aipass.seedgo.apps.handlers.diagnostics.diagnostics_check import (
            check_branch,
        )

        result = check_branch(str(tmp_path))
        assert result["passed"] is True
        assert result["score"] == 100
        assert "error" in result

    def test_with_runner_configs(self, tmp_path, monkeypatch):
        """Uses runner configs when packs are discovered."""
        from aipass.seedgo.apps.handlers.diagnostics import diagnostics_check

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
        from aipass.seedgo.apps.handlers.diagnostics import diagnostics_check

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
        """Falls back to direct pyright check when no runner executes."""
        from aipass.seedgo.apps.handlers.diagnostics import diagnostics_check

        apps_dir = tmp_path / "apps"
        apps_dir.mkdir()

        monkeypatch.setattr(diagnostics_check, "_discover_pack_configs", lambda: [])
        monkeypatch.setattr(
            diagnostics_check,
            "_run_runner",
            lambda name, bp, bypass_rules=None: None,
        )

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

    def test_no_errors_default_check(self, tmp_path, monkeypatch):
        """Default passing check is added when nothing failed."""
        from aipass.seedgo.apps.handlers.diagnostics import diagnostics_check

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
        from aipass.seedgo.apps.handlers.diagnostics import diagnostics_check

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
        from aipass.seedgo.apps.handlers.diagnostics import diagnostics_check

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
        from aipass.seedgo.apps.handlers.diagnostics.diagnostics_check import (
            format_summary,
        )

        result = format_summary({"error": "Something broke"})
        assert result == "Error: Something broke"

    def test_normal_summary(self):
        """Returns formatted summary for normal results."""
        from aipass.seedgo.apps.handlers.diagnostics.diagnostics_check import (
            format_summary,
        )

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
        from aipass.seedgo.apps.handlers.diagnostics.diagnostics_check import (
            format_summary,
        )

        results = {
            "error": "",
            "total_files": 0,
            "files_with_errors": 0,
            "total_errors": 0,
            "total_warnings": 0,
        }
        summary = format_summary(results)
        assert "Files analyzed: 0" in summary
