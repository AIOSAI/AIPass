"""Tests for seedgo checker sub-functions -- batch 7 (encapsulation, imports, introspection, modules)."""

# =================== META ====================
# Name: test_checkers_batch7.py
# Description: Unit tests for checker sub-functions in encapsulation, imports, introspection, modules
# Version: 1.0.0
# Created: 2026-04-25
# Modified: 2026-04-25
# =============================================

import ast
from typing import List

import pytest
from unittest.mock import MagicMock


def _lines(text: str) -> List[str]:
    """Split text into lines, widening LiteralString to str for pyright."""
    return text.split("\n")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _mock_infrastructure(monkeypatch):
    """Mock heavy infrastructure imports for standards checkers."""
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
    bypass_pkg.ignore_handler = bypass_ignore
    bypass_utils = MagicMock()
    bypass_utils.is_bypassed = MagicMock(return_value=False)
    bypass_pkg.utils = bypass_utils
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.bypass", bypass_pkg)
    monkeypatch.setitem(
        sys.modules,
        "aipass.seedgo.apps.handlers.bypass.ignore_handler",
        bypass_ignore,
    )
    monkeypatch.setitem(
        sys.modules,
        "aipass.seedgo.apps.handlers.bypass.utils",
        bypass_utils,
    )

    # Force re-imports so checkers pick up fresh mocks
    for mod_name in [
        "aipass.seedgo.apps.handlers.aipass_standards.encapsulation_check",
        "aipass.seedgo.apps.handlers.aipass_standards.imports_check",
        "aipass.seedgo.apps.handlers.aipass_standards.introspection_check",
        "aipass.seedgo.apps.handlers.aipass_standards.modules_check",
    ]:
        monkeypatch.delitem(sys.modules, mod_name, raising=False)

    # Clear the handler guard cache between tests
    enc_mod_name = "aipass.seedgo.apps.handlers.aipass_standards.encapsulation_check"
    enc_mod = sys.modules.get(enc_mod_name)
    if enc_mod is not None and hasattr(enc_mod, "_handler_guard_cache"):
        enc_mod._handler_guard_cache.clear()


# ===========================================================================
# 1. encapsulation_check sub-functions
# ===========================================================================


# -- extract_branch_from_import ----------------------------------------------


class TestExtractBranchFromImport:
    """Tests for extract_branch_from_import."""

    def test_branch_dot_apps_handlers(self):
        """Extract branch from 'from flow.apps.handlers...' pattern."""
        from aipass.seedgo.apps.handlers.aipass_standards.encapsulation_check import (
            extract_branch_from_import,
        )

        result = extract_branch_from_import("from flow.apps.handlers.plan.validator import X")
        assert result == "flow"

    def test_aipass_dot_branch_pattern(self):
        """Extract branch from 'from aipass.api.apps.handlers...' pattern."""
        from aipass.seedgo.apps.handlers.aipass_standards.encapsulation_check import (
            extract_branch_from_import,
        )

        result = extract_branch_from_import("from aipass.api.apps.handlers.openrouter import X")
        assert result == "api"

    def test_local_import_returns_none(self):
        """Local import without branch returns None."""
        from aipass.seedgo.apps.handlers.aipass_standards.encapsulation_check import (
            extract_branch_from_import,
        )

        result = extract_branch_from_import("from apps.handlers.json import X")
        assert result is None

    def test_import_statement_form(self):
        """Extract branch from 'import branch.apps.handlers...' pattern."""
        from aipass.seedgo.apps.handlers.aipass_standards.encapsulation_check import (
            extract_branch_from_import,
        )

        result = extract_branch_from_import("import seedgo.apps.handlers.json")
        assert result == "seedgo"


# -- extract_handler_package -------------------------------------------------


class TestExtractHandlerPackage:
    """Tests for extract_handler_package."""

    def test_extracts_json(self):
        """Extract 'json' from handler import path."""
        from aipass.seedgo.apps.handlers.aipass_standards.encapsulation_check import (
            extract_handler_package,
        )

        result = extract_handler_package("from apps.handlers.json.json_handler import X")
        assert result == "json"

    def test_extracts_dashboard(self):
        """Extract 'dashboard' from handler import path."""
        from aipass.seedgo.apps.handlers.aipass_standards.encapsulation_check import (
            extract_handler_package,
        )

        result = extract_handler_package("from apps.handlers.dashboard.refresh import X")
        assert result == "dashboard"

    def test_cross_branch_handler(self):
        """Extract package from cross-branch handler import."""
        from aipass.seedgo.apps.handlers.aipass_standards.encapsulation_check import (
            extract_handler_package,
        )

        result = extract_handler_package("from flow.apps.handlers.plan.validator import X")
        assert result == "plan"

    def test_no_handlers_returns_none(self):
        """Import without apps.handlers returns None."""
        from aipass.seedgo.apps.handlers.aipass_standards.encapsulation_check import (
            extract_handler_package,
        )

        result = extract_handler_package("from apps.modules.audit import run")
        assert result is None


# -- get_file_handler_package ------------------------------------------------


class TestGetFileHandlerPackage:
    """Tests for get_file_handler_package."""

    def test_handler_file_returns_package(self):
        """File in handlers/json/ returns 'json'."""
        from aipass.seedgo.apps.handlers.aipass_standards.encapsulation_check import (
            get_file_handler_package,
        )

        result = get_file_handler_package("/home/x/apps/handlers/json/json_handler.py")
        assert result == "json"

    def test_non_handler_returns_none(self):
        """File in modules/ returns None."""
        from aipass.seedgo.apps.handlers.aipass_standards.encapsulation_check import (
            get_file_handler_package,
        )

        result = get_file_handler_package("/home/x/apps/modules/something.py")
        assert result is None


# -- check_handler_guard -----------------------------------------------------


class TestCheckHandlerGuard:
    """Tests for check_handler_guard."""

    def test_guard_present_passes(self, tmp_path, monkeypatch):
        """Branch with inspect.stack guard in handlers/__init__.py passes."""
        from aipass.seedgo.apps.handlers.aipass_standards import (
            encapsulation_check,
        )

        encapsulation_check._handler_guard_cache.clear()

        branch = tmp_path / "mybranch"
        handlers_dir = branch / "apps" / "handlers"
        handlers_dir.mkdir(parents=True)
        init_file = handlers_dir / "__init__.py"
        init_file.write_text(
            "import inspect\n"
            "def _guard_branch_access():\n"
            "    frame = inspect.stack()\n"
            "    raise ImportError('blocked')\n",
            encoding="utf-8",
        )

        monkeypatch.setattr(
            encapsulation_check,
            "get_branch_from_path",
            lambda fp: {"name": "mybranch", "path": str(branch)},
        )

        result = encapsulation_check.check_handler_guard(str(handlers_dir / "json" / "handler.py"))
        assert result is not None
        assert result["passed"] is True
        assert "guard present" in result["message"]

    def test_guard_missing_fails(self, tmp_path, monkeypatch):
        """Branch without guard in handlers/__init__.py fails."""
        from aipass.seedgo.apps.handlers.aipass_standards import (
            encapsulation_check,
        )

        encapsulation_check._handler_guard_cache.clear()

        branch = tmp_path / "mybranch"
        handlers_dir = branch / "apps" / "handlers"
        handlers_dir.mkdir(parents=True)
        init_file = handlers_dir / "__init__.py"
        init_file.write_text("# empty init\n", encoding="utf-8")

        monkeypatch.setattr(
            encapsulation_check,
            "get_branch_from_path",
            lambda fp: {"name": "mybranch", "path": str(branch)},
        )

        result = encapsulation_check.check_handler_guard(str(handlers_dir / "json" / "handler.py"))
        assert result is not None
        assert result["passed"] is False

    def test_no_handlers_dir_returns_none(self, tmp_path, monkeypatch):
        """Branch without handlers/ directory returns None."""
        from aipass.seedgo.apps.handlers.aipass_standards import (
            encapsulation_check,
        )

        encapsulation_check._handler_guard_cache.clear()

        branch = tmp_path / "mybranch"
        branch.mkdir(parents=True)

        monkeypatch.setattr(
            encapsulation_check,
            "get_branch_from_path",
            lambda fp: {"name": "mybranch", "path": str(branch)},
        )

        result = encapsulation_check.check_handler_guard(str(branch / "apps" / "x.py"))
        assert result is None


# -- check_cross_branch_imports ----------------------------------------------


class TestCheckCrossBranchImports:
    """Tests for check_cross_branch_imports."""

    def test_no_cross_branch_passes(self):
        """File with no cross-branch handler imports passes."""
        from aipass.seedgo.apps.handlers.aipass_standards.encapsulation_check import (
            check_cross_branch_imports,
        )

        lines = _lines("from apps.handlers.json import json_handler\n")
        result = check_cross_branch_imports(lines, "/seedgo/apps/modules/a.py", "seedgo")
        assert result["passed"] is True

    def test_cross_branch_import_fails(self):
        """Importing another branch's handlers fails."""
        from aipass.seedgo.apps.handlers.aipass_standards.encapsulation_check import (
            check_cross_branch_imports,
        )

        lines = _lines("from flow.apps.handlers.plan.validator import X\n")
        result = check_cross_branch_imports(lines, "/seedgo/apps/modules/a.py", "seedgo")
        assert result["passed"] is False
        assert "flow" in result["message"]

    def test_same_branch_import_passes(self):
        """Importing own branch's handlers passes."""
        from aipass.seedgo.apps.handlers.aipass_standards.encapsulation_check import (
            check_cross_branch_imports,
        )

        lines = _lines("from seedgo.apps.handlers.json import json_handler\n")
        result = check_cross_branch_imports(lines, "/seedgo/apps/modules/a.py", "seedgo")
        assert result["passed"] is True

    def test_import_in_string_ignored(self):
        """Handler import inside a string literal is not flagged."""
        from aipass.seedgo.apps.handlers.aipass_standards.encapsulation_check import (
            check_cross_branch_imports,
        )

        lines = _lines('"from flow.apps.handlers.plan import X"\n')
        result = check_cross_branch_imports(lines, "/seedgo/apps/modules/a.py", "seedgo")
        assert result["passed"] is True


# -- check_cross_package_imports ---------------------------------------------


class TestCheckCrossPackageImports:
    """Tests for check_cross_package_imports."""

    def test_same_package_passes(self):
        """Importing from same handler package passes."""
        from aipass.seedgo.apps.handlers.aipass_standards.encapsulation_check import (
            check_cross_package_imports,
        )

        lines = _lines("from apps.handlers.json.utils import helper\n")
        result = check_cross_package_imports(lines, "/branch/apps/handlers/json/handler.py", "json")
        assert result["passed"] is True

    def test_cross_package_fails(self):
        """Importing from a different handler package fails."""
        from aipass.seedgo.apps.handlers.aipass_standards.encapsulation_check import (
            check_cross_package_imports,
        )

        lines = _lines("from apps.handlers.error.error_handler import X\n")
        result = check_cross_package_imports(
            lines,
            "/branch/apps/handlers/audit/checker.py",
            "audit",
        )
        assert result["passed"] is False
        assert "error" in result["message"]

    def test_allowed_json_handler_passes(self):
        """Importing json_handler (default allowed handler) passes."""
        from aipass.seedgo.apps.handlers.aipass_standards.encapsulation_check import (
            check_cross_package_imports,
        )

        lines = _lines("from apps.handlers.json.json_handler import log_op\n")
        result = check_cross_package_imports(
            lines,
            "/branch/apps/handlers/audit/checker.py",
            "audit",
        )
        assert result["passed"] is True

    def test_relative_import_passes(self):
        """Relative imports within same package pass."""
        from aipass.seedgo.apps.handlers.aipass_standards.encapsulation_check import (
            check_cross_package_imports,
        )

        lines = _lines("from .utils import helper\n")
        result = check_cross_package_imports(lines, "/branch/apps/handlers/json/handler.py", "json")
        assert result["passed"] is True


# -- check_direct_handler_imports --------------------------------------------


class TestCheckDirectHandlerImports:
    """Tests for check_direct_handler_imports."""

    def test_no_handler_import_passes(self):
        """Entry point without handler imports passes."""
        from aipass.seedgo.apps.handlers.aipass_standards.encapsulation_check import (
            check_direct_handler_imports,
        )

        lines = _lines("from apps.modules.audit import run_audit\n")
        result = check_direct_handler_imports(lines, "/branch/apps/branch.py")
        assert result["passed"] is True

    def test_direct_handler_import_fails(self):
        """Entry point importing handlers directly fails."""
        from aipass.seedgo.apps.handlers.aipass_standards.encapsulation_check import (
            check_direct_handler_imports,
        )

        lines = _lines("from apps.handlers.openrouter.client import get_response\n")
        result = check_direct_handler_imports(lines, "/branch/apps/branch.py")
        assert result["passed"] is False
        assert "Handler imported directly" in result["message"]

    def test_allowed_json_handler_passes(self):
        """Default handlers (json_handler) are allowed from entry points."""
        from aipass.seedgo.apps.handlers.aipass_standards.encapsulation_check import (
            check_direct_handler_imports,
        )

        lines = _lines("from apps.handlers.json.json_handler import log_op\n")
        result = check_direct_handler_imports(lines, "/branch/apps/branch.py")
        assert result["passed"] is True


# ===========================================================================
# 2. imports_check sub-functions
# ===========================================================================


# -- filter_docstrings -------------------------------------------------------


class TestFilterDocstrings:
    """Tests for filter_docstrings."""

    def test_removes_multiline_docstring(self):
        """Multi-line docstring lines are removed."""
        from aipass.seedgo.apps.handlers.aipass_standards.imports_check import (
            filter_docstrings,
        )

        lines = _lines('"""\nThis is a docstring.\n"""\nimport os\n')
        result = filter_docstrings(lines)
        assert any("import os" in ln for ln in result)
        assert not any("docstring" in ln for ln in result)

    def test_removes_single_line_docstring(self):
        """Single-line docstring is removed."""
        from aipass.seedgo.apps.handlers.aipass_standards.imports_check import (
            filter_docstrings,
        )

        lines = _lines('"""Module docstring."""\nimport os\n')
        result = filter_docstrings(lines)
        assert any("import os" in ln for ln in result)
        assert not any("Module docstring" in ln for ln in result)

    def test_preserves_code(self):
        """Non-docstring lines are preserved."""
        from aipass.seedgo.apps.handlers.aipass_standards.imports_check import (
            filter_docstrings,
        )

        lines = _lines("import os\nimport sys\n")
        result = filter_docstrings(lines)
        assert len([ln for ln in result if ln.strip()]) == 2


# -- find_import_section_end -------------------------------------------------


class TestFindImportSectionEnd:
    """Tests for find_import_section_end."""

    def test_finds_def(self):
        """Stops at first def statement."""
        from aipass.seedgo.apps.handlers.aipass_standards.imports_check import (
            find_import_section_end,
        )

        lines = _lines("import os\nimport sys\n\ndef main():\n    pass\n")
        result = find_import_section_end(lines)
        assert result == 3  # index of 'def main():'

    def test_finds_class(self):
        """Stops at first class statement."""
        from aipass.seedgo.apps.handlers.aipass_standards.imports_check import (
            find_import_section_end,
        )

        lines = _lines("import os\n\nclass Foo:\n    pass\n")
        result = find_import_section_end(lines)
        assert result == 2  # index of 'class Foo:'

    def test_no_def_returns_length(self):
        """File with no def/class returns length of lines."""
        from aipass.seedgo.apps.handlers.aipass_standards.imports_check import (
            find_import_section_end,
        )

        lines = _lines("import os\nimport sys\nx = 42\n")
        result = find_import_section_end(lines)
        assert result == len(lines)


# -- check_no_aipass_root ----------------------------------------------------


class TestCheckNoAipassRoot:
    """Tests for check_no_aipass_root."""

    def test_clean_file_passes(self):
        """File without AIPASS_ROOT passes."""
        from aipass.seedgo.apps.handlers.aipass_standards.imports_check import (
            check_no_aipass_root,
        )

        lines = _lines("import os\nfrom aipass.prax import logger\n")
        result = check_no_aipass_root(lines, "/test.py")
        assert result["passed"] is True

    def test_aipass_root_usage_fails(self):
        """File using AIPASS_ROOT fails."""
        from aipass.seedgo.apps.handlers.aipass_standards.imports_check import (
            check_no_aipass_root,
        )

        lines = _lines("root = AIPASS_ROOT / 'config'\n")
        result = check_no_aipass_root(lines, "/test.py")
        assert result["passed"] is False
        assert "AIPASS_ROOT" in result["message"]


# -- check_no_sys_path ------------------------------------------------------


class TestCheckNoSysPath:
    """Tests for check_no_sys_path."""

    def test_clean_file_passes(self):
        """File without sys.path hacking passes."""
        from aipass.seedgo.apps.handlers.aipass_standards.imports_check import (
            check_no_sys_path,
        )

        lines = _lines("import os\nimport sys\n")
        result = check_no_sys_path(lines, "/test.py")
        assert result["passed"] is True

    def test_sys_path_insert_fails(self):
        """File with sys.path.insert fails."""
        from aipass.seedgo.apps.handlers.aipass_standards.imports_check import (
            check_no_sys_path,
        )

        lines = _lines("import sys\nsys.path.insert(0, '/my/path')\n")
        result = check_no_sys_path(lines, "/test.py")
        assert result["passed"] is False
        assert "sys.path" in result["message"]

    def test_sys_path_append_fails(self):
        """File with sys.path.append fails."""
        from aipass.seedgo.apps.handlers.aipass_standards.imports_check import (
            check_no_sys_path,
        )

        lines = _lines("import sys\nsys.path.append('/my/path')\n")
        result = check_no_sys_path(lines, "/test.py")
        assert result["passed"] is False


# -- check_prax_logger -------------------------------------------------------


class TestCheckPraxLogger:
    """Tests for check_prax_logger."""

    def test_prax_import_passes(self):
        """File with from aipass.prax import logger passes."""
        from aipass.seedgo.apps.handlers.aipass_standards.imports_check import (
            check_prax_logger,
        )

        lines = _lines("from aipass.prax import logger\n")
        result = check_prax_logger(lines, "/test.py")
        assert result is not None
        assert result["passed"] is True

    def test_missing_prax_import_fails(self):
        """File without prax logger import fails."""
        from aipass.seedgo.apps.handlers.aipass_standards.imports_check import (
            check_prax_logger,
        )

        lines = _lines("import os\nimport sys\n")
        result = check_prax_logger(lines, "/test.py")
        assert result is not None
        assert result["passed"] is False
        assert "Prax logger" in result["message"]


class TestCheckPraxLoggerAcceptsBothBindings:
    """The standard is about ROUTING; both bindings route identically.

    Raised by @memory 2026-08-30: `from aipass.prax import logger` binds the
    logger OBJECT at import and is UNREBINDABLE, so a conftest swapping
    sys.modules cannot reach it and real writes escape into @prax's live state
    directory. Measured here: ONE daemon test under plain pytest made 23 atomic
    writes into the real prax_json/. The module form is rebindable because the
    attribute resolves at CALL time. Rejecting it was this checker enforcing a
    binding style the standard never asked for.
    """

    def _check(self, source: str):
        from aipass.seedgo.apps.handlers.aipass_standards.imports_check import (
            check_prax_logger,
        )

        return check_prax_logger(_lines(source), "/test.py")

    def test_the_rebindable_module_form_passes(self):
        assert self._check("from aipass import prax\n")["passed"] is True

    def test_the_object_form_still_passes(self):
        assert self._check("from aipass.prax import logger\n")["passed"] is True

    def test_prax_inside_a_multi_name_import_counts(self):
        assert self._check("from aipass import cli, prax\n")["passed"] is True

    def test_an_aliased_prax_still_counts(self):
        assert self._check("from aipass import prax as p\n")["passed"] is True

    def test_a_sibling_package_is_not_mistaken_for_prax(self):
        # `from aipass import cli` must NOT satisfy a prax-logging rule.
        assert self._check("from aipass import cli\n")["passed"] is False

    def test_a_name_that_merely_starts_with_prax_is_not_prax(self):
        # Substring matching would accept this; the check splits the import
        # list and compares whole names.
        assert self._check("from aipass import praxis\n")["passed"] is False

    def test_prax_imported_from_somewhere_that_is_not_aipass_does_not_count(self):
        # Found by mutation: deleting the "from aipass import " prefix guard
        # killed no test, so any package exporting a name `prax` would have
        # satisfied an AIPASS logging rule.
        assert self._check("from thirdparty import prax\n")["passed"] is False

    def test_a_commented_out_import_does_not_count(self):
        assert self._check("# from aipass import prax\n")["passed"] is False

    def test_a_commented_out_OBJECT_form_import_does_not_count_either(self):
        # The module form is rejected by the source-package guard even without
        # the comment skip, so only the OBJECT form actually exercises it -
        # found by mutation, the comment-skip mutant survived until this test.
        assert self._check("# from aipass.prax import logger\n")["passed"] is False

    def test_the_failure_message_offers_BOTH_spellings(self):
        message = self._check("import os\n")["message"]
        assert "from aipass.prax import logger" in message
        assert "from aipass import prax" in message


# -- check_handler_independence (imports) ------------------------------------


class TestImportsHandlerIndependence:
    """Tests for imports_check.check_handler_independence."""

    def test_clean_handler_passes(self):
        """Handler without parent module imports passes."""
        from aipass.seedgo.apps.handlers.aipass_standards.imports_check import (
            check_handler_independence,
        )

        lines = _lines("from aipass.prax import logger\n")
        result = check_handler_independence(lines, "/seedgo/apps/handlers/json/handler.py")
        assert result is not None
        assert result["passed"] is True

    def test_parent_module_import_fails(self):
        """Handler importing from parent branch modules fails."""
        from aipass.seedgo.apps.handlers.aipass_standards.imports_check import (
            check_handler_independence,
        )

        lines = _lines("from seedgo.apps.modules.audit import run\n")
        result = check_handler_independence(lines, "/seedgo/apps/handlers/json/handler.py")
        assert result is not None
        assert result["passed"] is False
        assert "parent module" in result["message"]

    def test_infrastructure_import_passes(self):
        """Infrastructure imports (aipass.prax, aipass.cli) are allowed."""
        from aipass.seedgo.apps.handlers.aipass_standards.imports_check import (
            check_handler_independence,
        )

        lines = _lines(
            "from aipass.prax.apps.modules.logger import info\nfrom aipass.cli.apps.modules.display import header\n"
        )
        result = check_handler_independence(lines, "/seedgo/apps/handlers/json/handler.py")
        assert result is not None
        assert result["passed"] is True


# -- check_import_order ------------------------------------------------------


class TestCheckImportOrder:
    """Tests for check_import_order."""

    def test_correct_order_passes(self):
        """Stdlib before aipass imports passes."""
        from aipass.seedgo.apps.handlers.aipass_standards.imports_check import (
            check_import_order,
        )

        lines = _lines("import os\nimport sys\nfrom aipass.prax import logger\n")
        result = check_import_order(lines, "/test.py")
        assert result is not None
        assert result["passed"] is True

    def test_wrong_order_fails(self):
        """Aipass import before stdlib fails."""
        from aipass.seedgo.apps.handlers.aipass_standards.imports_check import (
            check_import_order,
        )

        lines = _lines("from aipass.prax import logger\nimport os\n")
        result = check_import_order(lines, "/test.py")
        assert result is not None
        assert result["passed"] is False
        assert "before stdlib" in result["message"]

    def test_no_imports_returns_none(self):
        """File with no imports returns None."""
        from aipass.seedgo.apps.handlers.aipass_standards.imports_check import (
            check_import_order,
        )

        lines = _lines("x = 42\n")
        result = check_import_order(lines, "/test.py")
        assert result is None


# -- check_no_bare_imports ---------------------------------------------------


class TestCheckNoBareImports:
    """Tests for check_no_bare_imports."""

    def test_proper_namespace_passes(self):
        """Import using aipass.* namespace passes."""
        from aipass.seedgo.apps.handlers.aipass_standards.imports_check import (
            check_no_bare_imports,
        )

        lines = _lines("from aipass.seedgo.apps.handlers.json import json_handler\n")
        result = check_no_bare_imports(lines, "/test.py")
        assert result is not None
        assert result["passed"] is True

    def test_bare_handler_import_fails(self):
        """Bare 'from handlers.X' import fails."""
        from aipass.seedgo.apps.handlers.aipass_standards.imports_check import (
            check_no_bare_imports,
        )

        lines = _lines("from handlers.json import json_handler\n")
        result = check_no_bare_imports(lines, "/test.py")
        assert result is not None
        assert result["passed"] is False
        assert "bare import" in result["message"]

    def test_bare_module_import_fails(self):
        """Bare 'from drone.apps...' without aipass prefix fails."""
        from aipass.seedgo.apps.handlers.aipass_standards.imports_check import (
            check_no_bare_imports,
        )

        lines = _lines("from drone.apps.modules.commander import route\n")
        result = check_no_bare_imports(lines, "/test.py")
        assert result is not None
        assert result["passed"] is False
        assert "missing aipass." in result["message"]

    def test_stdlib_import_passes(self):
        """Standard library imports pass."""
        from aipass.seedgo.apps.handlers.aipass_standards.imports_check import (
            check_no_bare_imports,
        )

        lines = _lines("import os\nfrom pathlib import Path\n")
        result = check_no_bare_imports(lines, "/test.py")
        assert result is not None
        assert result["passed"] is True


# ===========================================================================
# 3. introspection_check sub-functions
# ===========================================================================


# -- check_print_introspection_exists ----------------------------------------


class TestCheckPrintIntrospectionExists:
    """Tests for check_print_introspection_exists."""

    def test_function_present_passes(self):
        """File with def print_introspection passes."""
        from aipass.seedgo.apps.handlers.aipass_standards.introspection_check import (
            check_print_introspection_exists,
        )

        content = "def print_introspection():\n    pass\n"
        tree = ast.parse(content)
        result = check_print_introspection_exists(tree, "test.py")
        assert result["passed"] is True

    def test_function_missing_fails(self):
        """File without print_introspection fails."""
        from aipass.seedgo.apps.handlers.aipass_standards.introspection_check import (
            check_print_introspection_exists,
        )

        content = "def main():\n    pass\n"
        tree = ast.parse(content)
        result = check_print_introspection_exists(tree, "test.py")
        assert result["passed"] is False
        assert "Missing" in result["message"]


# -- check_execution_order --------------------------------------------------


class TestCheckExecutionOrder:
    """Tests for check_execution_order."""

    def test_correct_order_passes(self):
        """No-args check before --help check passes."""
        from aipass.seedgo.apps.handlers.aipass_standards.introspection_check import (
            check_execution_order,
        )

        content = (
            "def main():\n"
            "    if not args:\n"
            "        print_introspection()\n"
            "    if '--help' in args:\n"
            "        print_help()\n"
        )
        tree = ast.parse(content)
        result = check_execution_order(tree, content, "test.py")
        assert result is not None
        assert result["passed"] is True

    def test_wrong_order_fails(self):
        """--help check before no-args check fails."""
        from aipass.seedgo.apps.handlers.aipass_standards.introspection_check import (
            check_execution_order,
        )

        content = (
            "def main():\n"
            "    if '--help' in args:\n"
            "        print_help()\n"
            "    if not args:\n"
            "        print_introspection()\n"
        )
        tree = ast.parse(content)
        result = check_execution_order(tree, content, "test.py")
        assert result is not None
        assert result["passed"] is False

    def test_no_main_skips(self):
        """File without main() or __name__ block is skipped."""
        from aipass.seedgo.apps.handlers.aipass_standards.introspection_check import (
            check_execution_order,
        )

        content = "def compute():\n    return 42\n"
        tree = ast.parse(content)
        result = check_execution_order(tree, content, "test.py")
        assert result is not None
        assert result["passed"] is True
        assert "skipped" in result["message"].lower()


# -- check_module_handle_command_gate ----------------------------------------


class TestCheckModuleHandleCommandGate:
    """Tests for check_module_handle_command_gate."""

    def test_gate_present_passes(self):
        """handle_command with no-args gate calling print_introspection passes."""
        from aipass.seedgo.apps.handlers.aipass_standards.introspection_check import (
            check_module_handle_command_gate,
        )

        content = (
            "def handle_command(command, args):\n"
            "    if not args:\n"
            "        print_introspection()\n"
            "        return True\n"
            "    return False\n"
        )
        tree = ast.parse(content)
        result = check_module_handle_command_gate(tree, "test.py")
        assert result is not None
        assert result["passed"] is True

    def test_gate_missing_fails(self):
        """handle_command without no-args gate fails."""
        from aipass.seedgo.apps.handlers.aipass_standards.introspection_check import (
            check_module_handle_command_gate,
        )

        content = "def handle_command(command, args):\n    do_work(args)\n    return True\n"
        tree = ast.parse(content)
        result = check_module_handle_command_gate(tree, "test.py")
        assert result is not None
        assert result["passed"] is False

    def test_no_handle_command_skips(self):
        """File without handle_command is skipped."""
        from aipass.seedgo.apps.handlers.aipass_standards.introspection_check import (
            check_module_handle_command_gate,
        )

        content = "def compute():\n    return 42\n"
        tree = ast.parse(content)
        result = check_module_handle_command_gate(tree, "test.py")
        assert result is not None
        assert result["passed"] is True
        assert "skipped" in result["message"].lower()


# -- check_correct_dispatch -------------------------------------------------


class TestCheckCorrectDispatch:
    """Tests for check_correct_dispatch."""

    def test_correct_dispatch_passes(self):
        """No-args calls introspection and --help calls help passes."""
        from aipass.seedgo.apps.handlers.aipass_standards.introspection_check import (
            check_correct_dispatch,
        )

        content = (
            "def main():\n"
            "    if not args:\n"
            "        print_introspection()\n"
            "    if '--help' in args:\n"
            "        print_help()\n"
        )
        tree = ast.parse(content)
        result = check_correct_dispatch(tree, "test.py")
        assert result is not None
        assert result["passed"] is True

    def test_swapped_dispatch_fails(self):
        """No-args calling print_help instead of print_introspection fails."""
        from aipass.seedgo.apps.handlers.aipass_standards.introspection_check import (
            check_correct_dispatch,
        )

        content = (
            "def main():\n"
            "    if not args:\n"
            "        print_help()\n"
            "    if '--help' in args:\n"
            "        print_introspection()\n"
        )
        tree = ast.parse(content)
        result = check_correct_dispatch(tree, "test.py")
        assert result is not None
        assert result["passed"] is False

    def test_no_main_returns_none(self):
        """File without main function returns None."""
        from aipass.seedgo.apps.handlers.aipass_standards.introspection_check import (
            check_correct_dispatch,
        )

        content = "def compute():\n    return 42\n"
        tree = ast.parse(content)
        result = check_correct_dispatch(tree, "test.py")
        assert result is None


# -- check_content_references ------------------------------------------------


class TestCheckContentReferences:
    """Tests for check_content_references."""

    def test_correct_references_passes(self):
        """Introspection text without python3 references passes."""
        from aipass.seedgo.apps.handlers.aipass_standards.introspection_check import (
            check_content_references,
        )

        content = "def print_introspection():\n    msg = 'Use: drone @mybranch command'\n    return msg\n"
        tree = ast.parse(content)
        result = check_content_references(tree, "test.py")
        assert result is not None
        assert result["passed"] is True

    def test_python3_reference_fails(self):
        """Introspection text referencing python3 fails."""
        from aipass.seedgo.apps.handlers.aipass_standards.introspection_check import (
            check_content_references,
        )

        content = "def print_introspection():\n    msg = 'Run: python3 mybranch.py command'\n    return msg\n"
        tree = ast.parse(content)
        result = check_content_references(tree, "test.py")
        assert result is not None
        assert result["passed"] is False
        assert "python3" in result["message"]

    def test_no_relevant_funcs_returns_none(self):
        """File without print_introspection or print_help returns None."""
        from aipass.seedgo.apps.handlers.aipass_standards.introspection_check import (
            check_content_references,
        )

        content = "def compute():\n    return 42\n"
        tree = ast.parse(content)
        result = check_content_references(tree, "test.py")
        assert result is None


# -- check_module_help_interception ------------------------------------------


class TestCheckModuleHelpInterception:
    """Tests for check_module_help_interception."""

    def test_help_intercepted_passes(self):
        """handle_command that intercepts --help passes."""
        from aipass.seedgo.apps.handlers.aipass_standards.introspection_check import (
            check_module_help_interception,
        )

        content = (
            "def handle_command(command, args):\n"
            "    if '--help' in args:\n"
            "        print_help()\n"
            "        return True\n"
            "    return False\n"
        )
        tree = ast.parse(content)
        result = check_module_help_interception(tree, "test.py")
        assert result is not None
        assert result["passed"] is True

    def test_help_not_intercepted_fails(self):
        """handle_command without --help interception fails."""
        from aipass.seedgo.apps.handlers.aipass_standards.introspection_check import (
            check_module_help_interception,
        )

        content = "def handle_command(command, args):\n    do_work(args)\n    return True\n"
        tree = ast.parse(content)
        result = check_module_help_interception(tree, "test.py")
        assert result is not None
        assert result["passed"] is False
        assert "does not intercept" in result["message"]

    def test_no_handle_command_returns_none(self):
        """File without handle_command returns None."""
        from aipass.seedgo.apps.handlers.aipass_standards.introspection_check import (
            check_module_help_interception,
        )

        content = "def compute():\n    return 42\n"
        tree = ast.parse(content)
        result = check_module_help_interception(tree, "test.py")
        assert result is None

    def test_imported_help_predicate_passes(self):
        """A delegated predicate imported from a handler counts as interception."""
        from aipass.seedgo.apps.handlers.aipass_standards.introspection_check import (
            check_module_help_interception,
        )

        content = (
            "from aipass.memory.apps.handlers.cli.help_flags import wants_help\n"
            "\n"
            "def handle_command(command, args):\n"
            "    if wants_help(args, allow_bare_word=True):\n"
            "        print_help()\n"
            "        return True\n"
            "    return False\n"
        )
        tree = ast.parse(content)
        result = check_module_help_interception(tree, "test.py")
        assert result is not None
        assert result["passed"] is True

    def test_locally_defined_help_predicate_passes(self):
        """A predicate defined in the same file counts as interception."""
        from aipass.seedgo.apps.handlers.aipass_standards.introspection_check import (
            check_module_help_interception,
        )

        content = (
            "def _is_help_request(args):\n"
            "    return bool(args)\n"
            "\n"
            "def handle_command(command, args):\n"
            "    if _is_help_request(args):\n"
            "        print_help()\n"
            "        return True\n"
            "    return False\n"
        )
        tree = ast.parse(content)
        result = check_module_help_interception(tree, "test.py")
        assert result is not None
        assert result["passed"] is True

    def test_non_help_predicate_call_fails(self):
        """An unrelated predicate call is not mistaken for a help guard."""
        from aipass.seedgo.apps.handlers.aipass_standards.introspection_check import (
            check_module_help_interception,
        )

        content = (
            "def should_process(args):\n"
            "    return bool(args)\n"
            "\n"
            "def handle_command(command, args):\n"
            "    if should_process(args):\n"
            "        do_work(args)\n"
            "    return True\n"
        )
        tree = ast.parse(content)
        result = check_module_help_interception(tree, "test.py")
        assert result is not None
        assert result["passed"] is False
        assert "does not intercept" in result["message"]

    def test_helper_substring_name_does_not_pass(self):
        """'helper' merely contains 'help' -- it is not a help predicate."""
        from aipass.seedgo.apps.handlers.aipass_standards.introspection_check import (
            check_module_help_interception,
        )

        content = (
            "def _has_credential_helper(args):\n"
            "    return bool(args)\n"
            "\n"
            "def handle_command(command, args):\n"
            "    if _has_credential_helper(args):\n"
            "        do_work(args)\n"
            "    return True\n"
        )
        tree = ast.parse(content)
        result = check_module_help_interception(tree, "test.py")
        assert result is not None
        assert result["passed"] is False
        assert "does not intercept" in result["message"]

    def test_help_predicate_not_asked_about_args_does_not_pass(self):
        """A help-named predicate applied to something other than the args is no guard."""
        from aipass.seedgo.apps.handlers.aipass_standards.introspection_check import (
            check_module_help_interception,
        )

        content = (
            "def _contains_help_string(node):\n"
            "    return bool(node)\n"
            "\n"
            "def handle_command(command, args):\n"
            "    for node in walk(tree):\n"
            "        if _contains_help_string(node):\n"
            "            record(node)\n"
            "    return True\n"
        )
        tree = ast.parse(content)
        result = check_module_help_interception(tree, "test.py")
        assert result is not None
        assert result["passed"] is False
        assert "does not intercept" in result["message"]

    def test_unresolved_help_predicate_does_not_pass(self):
        """A help-named attribute call on an unknown object does not count."""
        from aipass.seedgo.apps.handlers.aipass_standards.introspection_check import (
            check_module_help_interception,
        )

        content = (
            "def handle_command(command, args):\n"
            "    if ctx.cli.wants_help(args):\n"
            "        print_help()\n"
            "        return True\n"
            "    return False\n"
        )
        tree = ast.parse(content)
        result = check_module_help_interception(tree, "test.py")
        assert result is not None
        assert result["passed"] is False
        assert "does not intercept" in result["message"]


# -- check_introspection_rich_formatting ------------------------------------


class TestCheckIntrospectionRichFormatting:
    """Tests for check_introspection_rich_formatting."""

    def test_styled_introspection_passes(self):
        """print_introspection with Rich markup tags passes."""
        from aipass.seedgo.apps.handlers.aipass_standards.introspection_check import (
            check_introspection_rich_formatting,
        )

        content = (
            "def print_introspection():\n"
            "    console.print('[bold cyan]Flow[/bold cyan] - PLAN Management')\n"
            "    console.print(f'[yellow]Modules:[/yellow] {count}')\n"
        )
        tree = ast.parse(content)
        result = check_introspection_rich_formatting(tree, "test.py")
        assert result is not None
        assert result["passed"] is True
        assert "Rich markup" in result["message"]

    def test_flat_introspection_fails(self):
        """print_introspection with only plain strings fails."""
        from aipass.seedgo.apps.handlers.aipass_standards.introspection_check import (
            check_introspection_rich_formatting,
        )

        content = (
            "def print_introspection():\n"
            "    console.print('spawn Entry Point')\n"
            "    console.print('Branch lifecycle manager')\n"
            "    console.print('Connected Modules:')\n"
        )
        tree = ast.parse(content)
        result = check_introspection_rich_formatting(tree, "test.py")
        assert result is not None
        assert result["passed"] is False
        assert "no Rich markup" in result["message"]

    def test_delegation_to_styled_helper_passes(self):
        """print_introspection delegating to a styled _helper passes."""
        from aipass.seedgo.apps.handlers.aipass_standards.introspection_check import (
            check_introspection_rich_formatting,
        )

        content = (
            "def _show_branch_introspection():\n"
            "    console.print('[bold cyan]Branch[/bold cyan]')\n"
            "    console.print(f'[yellow]Modules:[/yellow]')\n"
            "\n"
            "def print_introspection():\n"
            "    _show_branch_introspection()\n"
        )
        tree = ast.parse(content)
        result = check_introspection_rich_formatting(tree, "test.py")
        assert result is not None
        assert result["passed"] is True
        assert "delegates" in result["message"]

    def test_delegation_to_flat_helper_fails(self):
        """print_introspection delegating to a flat _helper fails."""
        from aipass.seedgo.apps.handlers.aipass_standards.introspection_check import (
            check_introspection_rich_formatting,
        )

        content = (
            "def _show_info():\n"
            "    console.print('Plain text only')\n"
            "    console.print('No formatting here')\n"
            "\n"
            "def print_introspection():\n"
            "    _show_info()\n"
        )
        tree = ast.parse(content)
        result = check_introspection_rich_formatting(tree, "test.py")
        assert result is not None
        assert result["passed"] is False
        assert "no Rich markup" in result["message"]

    def test_no_print_introspection_returns_none(self):
        """File without print_introspection returns None."""
        from aipass.seedgo.apps.handlers.aipass_standards.introspection_check import (
            check_introspection_rich_formatting,
        )

        content = "def compute():\n    return 42\n"
        tree = ast.parse(content)
        result = check_introspection_rich_formatting(tree, "test.py")
        assert result is None

    def test_no_output_returns_none(self):
        """print_introspection that produces no output returns None."""
        from aipass.seedgo.apps.handlers.aipass_standards.introspection_check import (
            check_introspection_rich_formatting,
        )

        content = "def print_introspection():\n    return {'name': 'test'}\n"
        tree = ast.parse(content)
        result = check_introspection_rich_formatting(tree, "test.py")
        assert result is None


# ===========================================================================
# 4. modules_check sub-functions
# ===========================================================================


# -- check_handle_command ----------------------------------------------------


class TestCheckHandleCommand:
    """Tests for check_handle_command."""

    def test_correct_pattern_passes(self):
        """Module with handle_command(command, args) -> bool passes."""
        from aipass.seedgo.apps.handlers.aipass_standards.modules_check import (
            check_handle_command,
        )

        content = "def handle_command(command: str, args: list) -> bool:\n    return True\n"
        result = check_handle_command(content)
        assert result is not None
        assert result["passed"] is True

    def test_missing_handle_command_fails(self):
        """Module without handle_command fails."""
        from aipass.seedgo.apps.handlers.aipass_standards.modules_check import (
            check_handle_command,
        )

        content = "def do_work():\n    return True\n"
        result = check_handle_command(content)
        assert result is not None
        assert result["passed"] is False
        assert "Missing handle_command" in result["message"]

    def test_missing_return_type_fails(self):
        """handle_command without -> bool annotation fails."""
        from aipass.seedgo.apps.handlers.aipass_standards.modules_check import (
            check_handle_command,
        )

        content = "def handle_command(command, args):\n    return True\n"
        result = check_handle_command(content)
        assert result is not None
        assert result["passed"] is False
        assert "missing -> bool" in result["message"]


# -- check_file_size (modules) -----------------------------------------------


class TestModulesCheckFileSize:
    """Tests for modules_check.check_file_size."""

    def test_simple_module_passes(self):
        """Under 150 lines is perfect."""
        from aipass.seedgo.apps.handlers.aipass_standards.modules_check import (
            check_file_size,
        )

        lines: list[str] = ["x"] * 100
        result = check_file_size(lines, "/branch/apps/modules/audit.py")
        assert result["passed"] is True
        assert "simple" in result["message"]

    def test_standard_module_passes(self):
        """150-250 lines is standard."""
        from aipass.seedgo.apps.handlers.aipass_standards.modules_check import (
            check_file_size,
        )

        lines: list[str] = ["x"] * 200
        result = check_file_size(lines, "/branch/apps/modules/audit.py")
        assert result["passed"] is True
        assert "standard" in result["message"]

    def test_oversized_module_fails(self):
        """600+ lines fails."""
        from aipass.seedgo.apps.handlers.aipass_standards.modules_check import (
            check_file_size,
        )

        lines: list[str] = ["x"] * 650
        result = check_file_size(lines, "/branch/apps/modules/audit.py")
        assert result["passed"] is False
        assert "too large" in result["message"]


# -- check_no_direct_file_ops -----------------------------------------------


class TestCheckNoDirectFileOps:
    """Tests for check_no_direct_file_ops."""

    def test_clean_module_passes(self):
        """Module without direct file operations passes."""
        from aipass.seedgo.apps.handlers.aipass_standards.modules_check import (
            check_no_direct_file_ops,
        )

        content = "def do_work():\n    return handler.load_data()\n"
        lines = _lines(content)
        result = check_no_direct_file_ops(content, lines)
        assert result is not None
        assert result["passed"] is True

    def test_open_call_fails(self):
        """Module with bare open() call fails."""
        from aipass.seedgo.apps.handlers.aipass_standards.modules_check import (
            check_no_direct_file_ops,
        )

        content = 'def do_work():\n    f = open("data.json")\n'
        lines = _lines(content)
        result = check_no_direct_file_ops(content, lines)
        assert result is not None
        assert result["passed"] is False
        assert "open" in result["message"]

    def test_json_dump_fails(self):
        """Module with json.dump() call fails."""
        from aipass.seedgo.apps.handlers.aipass_standards.modules_check import (
            check_no_direct_file_ops,
        )

        content = "def save():\n    json.dump(data, fp)\n"
        lines = _lines(content)
        result = check_no_direct_file_ops(content, lines)
        assert result is not None
        assert result["passed"] is False

    def test_import_open_not_flagged(self):
        """Import lines containing 'open' are not flagged."""
        from aipass.seedgo.apps.handlers.aipass_standards.modules_check import (
            check_no_direct_file_ops,
        )

        content = "from pathlib import Path\nimport os\n"
        lines = _lines(content)
        result = check_no_direct_file_ops(content, lines)
        assert result is not None
        assert result["passed"] is True


# -- check_no_business_logic -------------------------------------------------


class TestCheckNoBusinessLogic:
    """Tests for check_no_business_logic."""

    def test_clean_module_passes(self):
        """Module without hardcoded data passes."""
        from aipass.seedgo.apps.handlers.aipass_standards.modules_check import (
            check_no_business_logic,
        )

        content = "CONSTANT = 42\ndef do_work():\n    return True\n"
        lines = _lines(content)
        result = check_no_business_logic(content, lines, "/module.py")
        assert result is not None
        assert result["passed"] is True

    def test_hardcoded_list_fails(self):
        """Module-level hardcoded list fails."""
        from aipass.seedgo.apps.handlers.aipass_standards.modules_check import (
            check_no_business_logic,
        )

        content = 'allowed_types = ["alpha", "beta", "gamma"]\n'
        lines = _lines(content)
        result = check_no_business_logic(content, lines, "/module.py")
        assert result is not None
        assert result["passed"] is False
        assert "hardcoded" in result["message"]

    def test_all_caps_constant_passes(self):
        """ALL_CAPS constant is not flagged."""
        from aipass.seedgo.apps.handlers.aipass_standards.modules_check import (
            check_no_business_logic,
        )

        content = 'ALLOWED = ["alpha", "beta", "gamma"]\n'
        lines = _lines(content)
        result = check_no_business_logic(content, lines, "/module.py")
        assert result is not None
        assert result["passed"] is True

    def test_empty_list_passes(self):
        """Empty list assignment is not flagged."""
        from aipass.seedgo.apps.handlers.aipass_standards.modules_check import (
            check_no_business_logic,
        )

        content = "results = []\n"
        lines = _lines(content)
        result = check_no_business_logic(content, lines, "/module.py")
        assert result is not None
        assert result["passed"] is True


# -- check_thin_orchestration ------------------------------------------------


class TestCheckThinOrchestration:
    """Tests for check_thin_orchestration."""

    def test_thin_module_passes(self):
        """Module with only standard functions passes."""
        from aipass.seedgo.apps.handlers.aipass_standards.modules_check import (
            check_thin_orchestration,
        )

        content = (
            "def handle_command(command, args):\n"
            "    return True\n"
            "def print_help():\n"
            "    pass\n"
            "def print_introspection():\n"
            "    pass\n"
        )
        result = check_thin_orchestration(content, "/module.py")
        assert result is not None
        assert result["passed"] is True

    def test_implementation_function_fails(self):
        """Module with large non-standard function fails."""
        from aipass.seedgo.apps.handlers.aipass_standards.modules_check import (
            check_thin_orchestration,
        )

        # Build a function with > 40 lines (THIN_WRAPPER_MAX_LINES)
        func_body = "\n".join(f"    x{i} = {i}" for i in range(45))
        content = f"def compute_results(data):\n{func_body}\n"
        result = check_thin_orchestration(content, "/module.py")
        assert result is not None
        assert result["passed"] is False
        assert "compute_results" in result["message"]

    def test_private_helper_passes(self):
        """Private helper functions (_prefixed) are allowed."""
        from aipass.seedgo.apps.handlers.aipass_standards.modules_check import (
            check_thin_orchestration,
        )

        func_body = "\n".join(f"    x{i} = {i}" for i in range(45))
        content = f"def _internal_helper():\n{func_body}\n"
        result = check_thin_orchestration(content, "/module.py")
        assert result is not None
        assert result["passed"] is True

    def test_orchestration_prefix_passes(self):
        """Functions with orchestration prefixes (handle_, show_, etc.) pass."""
        from aipass.seedgo.apps.handlers.aipass_standards.modules_check import (
            check_thin_orchestration,
        )

        func_body = "\n".join(f"    x{i} = {i}" for i in range(45))
        content = f"def handle_audit(args):\n{func_body}\n"
        result = check_thin_orchestration(content, "/module.py")
        assert result is not None
        assert result["passed"] is True

    def test_small_function_passes(self):
        """Non-standard function under 40 lines is treated as thin wrapper."""
        from aipass.seedgo.apps.handlers.aipass_standards.modules_check import (
            check_thin_orchestration,
        )

        content = "def compute_results(data):\n    return data\n"
        result = check_thin_orchestration(content, "/module.py")
        assert result is not None
        assert result["passed"] is True
