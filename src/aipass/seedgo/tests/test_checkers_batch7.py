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

from aipass.seedgo.apps.handlers.aipass_standards import documentation_check


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


class TestAipassRootIsMatchedAsATokenNotASubstring:
    """`AIPASS_ROOTS.json` is a FILENAME, not the AIPASS_ROOT env var.

    Reported by @memory 2026-08-30: their audit dropped to 99% on
    `DECLARED_ROOTS = "AIPASS_ROOTS.json"` — a machine-managed file that sits
    beside AIPASS_REGISTRY.json because it is the same species. Nothing in that
    tree reads an env var of any name.

    They declined to rename the file to satisfy the grep, and they were right
    to: renaming a thing so a checker stops shouting is drift-by-linting, and
    the name would then have been chosen for a tool rather than a reader. The
    check means a TOKEN and was written as a SUBSTRING, so every present and
    future `AIPASS_ROOT*` collides.
    """

    def _check(self, line):
        from aipass.seedgo.apps.handlers.aipass_standards.imports_check import check_no_aipass_root

        return check_no_aipass_root([line + "\n"], "mod.py", [])

    def test_the_env_var_is_still_caught(self):
        assert not self._check('root = os.environ["AIPASS_ROOT"]')["passed"]

    def test_the_env_var_via_getenv_is_still_caught(self):
        assert not self._check('root = os.getenv("AIPASS_ROOT")')["passed"]

    def test_a_bare_reference_is_still_caught(self):
        assert not self._check("path = AIPASS_ROOT / 'x'")["passed"]

    def test_the_declared_roots_filename_is_NOT_a_violation(self):
        """@memory's exact line."""
        assert self._check('DECLARED_ROOTS = "AIPASS_ROOTS.json"')["passed"]

    def test_a_future_AIPASS_ROOT_MAP_is_not_a_violation_either(self):
        """The report named this one specifically as the next collision."""
        assert self._check('NAME = "AIPASS_ROOT_MAP.json"')["passed"]

    def test_AIPASS_ROOTS_REGISTRY_is_not_a_violation(self):
        assert self._check('NAME = "AIPASS_ROOTS_REGISTRY.json"')["passed"]

    def test_a_LONGER_name_ENDING_in_the_token_is_not_a_violation(self):
        """Prefix-only matching would still convict this one."""
        assert self._check('NAME = "MY_AIPASS_ROOT"')["passed"]

    def test_the_env_var_inside_an_fstring_is_still_caught(self):
        assert not self._check('msg = f"{AIPASS_ROOT}/x"')["passed"]


class TestImportsCheckLineNumbersSurviveDocstringFiltering:
    """A reported line number must name the line in the FILE.

    @memory reported the violation at line 40 when the only occurrence is at
    line 106 — off by 66, which is more than a docstring's worth of slack and
    sends a reader to the wrong place.

    THE CAUSE, and it is bigger than the check they reported: `filter_docstrings`
    `continue`s past docstring lines, COMPACTING the list. Every check that runs
    on `import_lines` then enumerates a shorter list and reports an index into
    it — so `check_no_sys_path`, `check_prax_logger`, `check_import_order` and
    `check_no_bare_imports` all carry the same defect. Blanking the lines
    instead of dropping them keeps every index aligned with the file.
    """

    def test_filter_docstrings_preserves_the_line_count(self):
        from aipass.seedgo.apps.handlers.aipass_standards.imports_check import filter_docstrings

        source = ['"""doc\n', "more doc\n", '"""\n', "import os\n"]
        assert len(filter_docstrings(source)) == len(source)

    def test_the_docstring_body_is_still_neutralised(self):
        """Preserving the line must not un-filter its content."""
        from aipass.seedgo.apps.handlers.aipass_standards.imports_check import filter_docstrings

        out = filter_docstrings(['"""\n', "AIPASS_ROOT lives here\n", '"""\n', "import os\n"])
        assert "AIPASS_ROOT" not in "".join(out)

    def test_a_violation_after_a_docstring_reports_its_REAL_line(self):
        from aipass.seedgo.apps.handlers.aipass_standards.imports_check import (
            check_no_aipass_root,
            filter_docstrings,
        )

        source = ['"""\n', "a\n", "b\n", "c\n", '"""\n', 'x = os.environ["AIPASS_ROOT"]\n']
        result = check_no_aipass_root(filter_docstrings(source), "mod.py", [])
        assert not result["passed"]
        assert "line 6" in result["message"], result["message"]

    def test_the_real_reported_file_now_passes_end_to_end(self):
        """@memory's actual file, through the real entry point."""
        from pathlib import Path

        from aipass.seedgo.apps.handlers.aipass_standards import imports_check

        target = Path(__file__).resolve().parents[2] / "memory" / "apps" / "handlers" / "monitor" / "registry_scope.py"
        if not target.exists():
            import pytest

            pytest.skip("registry_scope.py not on disk")
        rows = imports_check.check_module(str(target))["checks"]
        root_rows = [r for r in rows if r["name"] == "No AIPASS_ROOT"]
        assert root_rows and root_rows[0]["passed"], root_rows


class TestJsonStructureExemptsDeclarationOnlyModules:
    """ "Every module must log operations" is a rule about modules that PERFORM them.

    Raised by @drone 2026-08-31 on drone/apps/handlers/exceptions.py — 86 lines,
    ten exception classes, zero functions. It USED to pass, by carrying
    `log_operation("exceptions_loaded")` at module level. That turned out to be a
    real defect: running at import, it fired during pytest COLLECTION, before any
    fixture existed, so no seam could intercept it. Removing it took the file
    from passing to 0.

    So the check was REWARDING the defect, and both routes to green were worse
    than the violation: put the import-time write back, or add a function to a
    file of pure class definitions purely so there is somewhere to call
    log_operation from — dead code written to satisfy a grep, which
    unused_function would then flag.

    A module that defines no callable code performs no operations, so it has
    nothing to log. The exemption is keyed on that structural fact and nothing
    else: ONE method anywhere, and the module is back in scope.
    """

    def _score(self, source, tmp_path):
        from aipass.seedgo.apps.handlers.aipass_standards import json_structure_check

        # MUST land under apps/handlers or the checker returns not-applicable
        # on the PATH and every assertion below passes for the wrong reason —
        # which is exactly what the first cut of this class did.
        target = tmp_path / "apps" / "handlers" / "routing" / "mod.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source, encoding="utf-8")
        return json_structure_check.check_module(str(target))

    DECLARATIONS_ONLY = '"""Doc."""\n\n\nclass RoutingError(Exception):\n    """Boom."""\n\n\nclass BranchNotFound(RoutingError):\n    pass\n'

    def test_a_module_of_pure_exception_classes_is_not_applicable(self, tmp_path):
        result = self._score(self.DECLARATIONS_ONLY, tmp_path)
        assert result["score"] == 100, result["checks"]

    def test_the_exemption_is_PUBLISHED_not_a_silent_pass(self, tmp_path):
        """A skip nobody can read is indistinguishable from a check that ran."""
        result = self._score(self.DECLARATIONS_ONLY, tmp_path)
        text = " ".join(c["message"] for c in result["checks"]).lower()
        assert "declar" in text or "no operations" in text, result["checks"]

    def test_ONE_method_puts_the_module_back_in_scope(self, tmp_path):
        source = '"""Doc."""\n\n\nclass Thing:\n    def do(self):\n        return 1\n'
        assert self._score(source, tmp_path)["score"] < 100

    def test_a_module_level_function_is_still_in_scope(self, tmp_path):
        source = '"""Doc."""\n\n\ndef work():\n    return 1\n'
        assert self._score(source, tmp_path)["score"] < 100

    def test_a_dataclass_with_no_methods_is_exempt(self, tmp_path):
        source = '"""Doc."""\nfrom dataclasses import dataclass\n\n\n@dataclass\nclass Point:\n    x: int\n'
        assert self._score(source, tmp_path)["score"] == 100

    def test_constants_alone_do_not_earn_the_exemption_back(self, tmp_path):
        """Declarations plus data is still declarations."""
        source = '"""Doc."""\n\nLIMIT = 10\n\n\nclass E(Exception):\n    pass\n'
        assert self._score(source, tmp_path)["score"] == 100

    def test_an_UNPARSEABLE_file_does_not_earn_the_exemption(self, tmp_path):
        """A syntax error is not evidence of purity. Answering "no callable
        code" for a file we could not read hands out the exemption on
        ignorance — and the first cut of these pins let that mutant live."""
        assert self._score('"""Doc."""\n\nclass Broken(\n', tmp_path)["score"] < 100

    def test_the_REAL_drone_file_is_exempt(self, tmp_path):
        from pathlib import Path

        from aipass.seedgo.apps.handlers.aipass_standards import json_structure_check

        target = Path(__file__).resolve().parents[2] / "drone" / "apps" / "handlers" / "exceptions.py"
        if not target.exists():
            import pytest

            pytest.skip("drone exceptions.py not on disk")
        assert json_structure_check.check_module(str(target))["score"] == 100


class TestUnusedFunctionSaysWhatItActuallyMeasured:
    """The check measures "no caller in THIS branch" and said "unused".

    @memory 2026-08-31: `entry_limits.changed_entries()` was reported unused. It
    is called by @hooks at security/edit_gate.py:496 through a dynamic
    importlib import — a cross-branch consumer a same-branch AST scan cannot see
    in principle. Deleting it would disable the entry-cap half of the write gate
    for the whole fleet.

    The danger is precisely that the check is USEFUL: @memory had already acted
    on it correctly once the same night and dropped a genuinely dead helper. An
    agent that trusts it will eventually delete a real cross-branch entry point
    to get a green audit, and the audit will go green.

    They asked for the cheapest of three options and were right about which:
    the measurement is sound, only the WORD overclaims. Same species as this
    pack's AIPASS_ROOT substring bug — the checker stating more than it measured.
    """

    def _report(self, tmp_path, monkeypatch):
        from aipass.seedgo.apps.handlers.aipass_standards import unused_function_check

        # This module's autouse _mock_infrastructure fixture replaces
        # bypass.ignore_handler with a MagicMock, so is_seedgo_ignored() returns
        # a TRUTHY Mock and the collector silently skips every file — the report
        # then reads "No .py files found in branch" and any assertion about the
        # message passes or fails for reasons unrelated to the message. A
        # stand-in more generous than the real function, which is the exact trap
        # @memory described on 2026-08-30. Pinned back to the real answer here.
        monkeypatch.setattr(unused_function_check, "is_seedgo_ignored", lambda *a, **k: False)
        monkeypatch.setattr(unused_function_check, "load_ignore_entries", lambda *a, **k: [])

        # A neutral branch root INSIDE tmp_path: pytest names tmp_path after the
        # test, and the collector's skip set is matched against every path part.
        root = tmp_path / "branchroot"
        pkg = root / "apps" / "handlers"
        pkg.mkdir(parents=True)
        (pkg / "mod.py").write_text("def never_called_here():\n    return 1\n", encoding="utf-8")
        return unused_function_check.check_branch(str(root))

    def test_the_message_does_not_claim_the_function_is_unused(self, tmp_path, monkeypatch):
        report = self._report(tmp_path, monkeypatch)
        blob = str(report).lower()
        assert "no caller in this branch" in blob, report

    def test_the_message_names_the_limit_of_the_scan(self, tmp_path, monkeypatch):
        """A reader must be able to tell that cross-branch callers were not checked."""
        blob = str(self._report(tmp_path, monkeypatch)).lower()
        # NOT an `or` over synonyms: the first cut accepted either phrase, so a
        # mutant deleting the cross-branch clause kept passing on "this branch"
        # alone. Both halves of the disclosure are pinned.
        assert "cross-branch" in blob
        assert "importlib" in blob
        assert "confirm before deleting" in blob


class TestCliCheckAllowsRelayingACapturedSubprocessStream:
    """A router passing a child's bytes through is not "your output, undecorated".

    Raised via @devpulse 2026-08-31 for drone.py, which has eight of these. The
    dispatch guessed they were the `--json` machine surface; they are something
    simpler and better justified — every one is
    `sys.stdout.write(result.stdout)` / `sys.stderr.write(result.stderr)`,
    drone relaying a completed subprocess's captured output verbatim.

    The `cli` rule means "route YOUR OWN output through Rich". Rich would
    interpret markup in, wrap, and re-style bytes drone did not author, which is
    precisely what a router must not do. The checker was grepping a VERB where
    the rule asks an AUTHORSHIP question — the same species as this pack's
    AIPASS_ROOT substring bug and the json_structure and unused_function items
    ruled the same night.

    The exemption is narrow by construction and keyed on the ARGUMENT, so it
    cannot be borrowed: writing a literal, an f-string, or a value you built is
    still a violation. It also requires the streams to CORRESPOND — writing a
    captured stderr to stdout stays red, because that is a real routing bug this
    check should keep catching.
    """

    def _lines(self, source):
        from aipass.seedgo.apps.handlers.aipass_standards import cli_check

        return [i for i, line in enumerate(source.splitlines(), 1) if cli_check._is_raw_write_violation(line)]

    def test_relaying_captured_stdout_attribute_is_allowed(self):
        assert self._lines("        sys.stdout.write(result.stdout)") == []

    def test_relaying_captured_stdout_subscript_is_allowed(self):
        assert self._lines('        sys.stdout.write(result["stdout"])') == []

    def test_relaying_captured_stderr_to_stderr_is_allowed(self):
        assert self._lines("        sys.stderr.write(result.stderr)") == []

    def test_a_literal_is_STILL_a_violation(self):
        assert self._lines('        sys.stdout.write("hello")') != []

    def test_an_fstring_is_STILL_a_violation(self):
        assert self._lines('        sys.stdout.write(f"{count} done")') != []

    def test_a_value_you_built_is_STILL_a_violation(self):
        assert self._lines("        sys.stdout.write(rendered_table)") != []

    def test_CROSSED_streams_stay_a_violation(self):
        """Captured stderr written to stdout is a routing bug, not a relay."""
        assert self._lines("        sys.stdout.write(result.stderr)") != []
        assert self._lines('        sys.stderr.write(result["stdout"])') != []

    def test_a_commented_out_relay_is_not_examined_at_all(self):
        assert self._lines("        # sys.stdout.write(result.stdout)") == []

    def test_a_commented_out_VIOLATION_is_not_flagged(self):
        """The relay case above is inert either way — a mutant that stopped
        stripping comments survived it. This one only passes if comments are
        actually stripped."""
        assert self._lines('        # sys.stdout.write("hello")') == []

    def test_a_trailing_comment_does_not_hide_a_real_violation(self):
        assert self._lines('        sys.stdout.write("hello")  # relay') != []

    def test_the_REAL_drone_entry_point_has_no_raw_write_violations(self):
        from pathlib import Path

        from aipass.seedgo.apps.handlers.aipass_standards import cli_check

        target = Path(__file__).resolve().parents[2] / "drone" / "apps" / "drone.py"
        if not target.exists():
            import pytest

            pytest.skip("drone.py not on disk")
        lines = target.read_text(encoding="utf-8").splitlines()
        assert [i for i, line in enumerate(lines, 1) if cli_check._is_raw_write_violation(line)] == []


class TestJsonStructureExemptsPreLoggingBootstrapModules:
    """The pre-logging bootstrap class @prax reported (2026-08-31).

    A module the logging substrate itself imports cannot import json_handler
    back: log_operation() WRITES, so wiring it there puts a file write on the
    import path of every branch — the ungateable write that fires during pytest
    COLLECTION. Two clauses decide it, both MEASURED here: no aipass import of
    any kind, AND the logging chain's own imports reach the module. Either
    clause alone hands out the exemption far too widely.
    """

    def _universe(self, tmp_path):
        """A miniature src/aipass with a logger that imports one bootstrap module."""
        root = tmp_path / "src" / "aipass"
        prax = root / "prax" / "apps"
        (prax / "modules").mkdir(parents=True)
        (prax / "handlers").mkdir(parents=True)
        (prax / "modules" / "logger.py").write_text(
            "from aipass.prax.apps.handlers.boot import find_root\ndef get_system_logger():\n    return find_root()\n",
            encoding="utf-8",
        )
        return root

    def _check(self, path):
        from aipass.seedgo.apps.handlers.aipass_standards import json_structure_check

        return json_structure_check._is_prelogging_bootstrap(path, path.read_text(encoding="utf-8"))

    def test_a_stdlib_only_module_the_logger_imports_is_exempt(self, tmp_path):
        root = self._universe(tmp_path)
        boot = root / "prax" / "apps" / "handlers" / "boot.py"
        boot.write_text(
            "import logging\nfrom pathlib import Path\n\ndef find_root():\n    return Path(__file__).parent\n",
            encoding="utf-8",
        )
        assert self._check(boot) is True

    def test_the_same_module_loses_the_exemption_the_moment_it_imports_aipass(self, tmp_path):
        root = self._universe(tmp_path)
        boot = root / "prax" / "apps" / "handlers" / "boot.py"
        boot.write_text(
            "from pathlib import Path\n"
            "from aipass.prax.apps.handlers.json import json_handler\n\n"
            "def find_root():\n    return Path(__file__).parent\n",
            encoding="utf-8",
        )
        assert self._check(boot) is False

    def test_an_aipass_import_inside_a_function_still_disqualifies(self, tmp_path):
        """The dependency is taken wherever it is written. A module that can reach
        aipass from inside a function can reach json_handler the same way."""
        root = self._universe(tmp_path)
        boot = root / "prax" / "apps" / "handlers" / "boot.py"
        boot.write_text(
            "from pathlib import Path\n\n"
            "def find_root():\n"
            "    from aipass.prax.apps.handlers.json import json_handler\n"
            "    return Path(__file__).parent\n",
            encoding="utf-8",
        )
        assert self._check(boot) is False

    def test_a_stdlib_only_module_the_chain_never_reaches_is_NOT_exempt(self, tmp_path):
        """Clause 2 is what keeps the exemption from being free — 79 fleet modules
        import nothing from aipass, and only 9 are in the chain."""
        root = self._universe(tmp_path)
        lonely = root / "prax" / "apps" / "handlers" / "lonely.py"
        lonely.write_text(
            "import re\n\ndef parse(text):\n    return re.findall(r'x', text)\n",
            encoding="utf-8",
        )
        assert self._check(lonely) is False

    def test_an_unparseable_file_is_not_exempt(self, tmp_path):
        """_aipass_imports answers [] for a file it could not read, which would
        otherwise read as 'holds no aipass import'. No exemption on ignorance."""
        root = self._universe(tmp_path)
        boot = root / "prax" / "apps" / "handlers" / "boot.py"
        boot.write_text("def find_root(:\n    pass\n", encoding="utf-8")
        assert self._check(boot) is False

    def test_a_file_outside_any_aipass_source_root_is_not_exempt(self, tmp_path):
        loose = tmp_path / "loose.py"
        loose.write_text("import re\n\ndef parse(t):\n    return t\n", encoding="utf-8")
        assert self._check(loose) is False

    def test_the_REAL_prax_repo_root_scores_100(self):
        """The live case that prompted the rule — pinned against the real tree so a
        regression shows up as prax going red again, not as a green unit test."""
        from pathlib import Path

        import pytest

        from aipass.seedgo.apps.handlers.aipass_standards import json_structure_check

        target = Path(__file__).resolve().parents[2] / "prax" / "apps" / "handlers" / "repo_root.py"
        if not target.exists():
            pytest.skip("prax/apps/handlers/repo_root.py not on disk")
        result = json_structure_check.check_module(str(target))
        assert result["score"] == 100
        assert "bootstrap" in result["checks"][0]["message"]

    def test_the_REAL_memory_repo_root_is_NOT_exempt(self):
        """Same filename, same purpose, different position: memory's copy imports
        json_handler and the prax logger, so it is a consumer and stays in scope."""
        from pathlib import Path

        import pytest

        from aipass.seedgo.apps.handlers.aipass_standards import json_structure_check

        target = Path(__file__).resolve().parents[2] / "memory" / "apps" / "handlers" / "repo_root.py"
        if not target.exists():
            pytest.skip("memory/apps/handlers/repo_root.py not on disk")
        assert json_structure_check._is_prelogging_bootstrap(target, target.read_text(encoding="utf-8")) is False


class TestAutoDetectionAsksAboutThePublicSurface:
    """The auto-detection rule means "a caller should not have to name itself",
    and that is a question about a handler's PUBLISHED functions. It was measured
    by grepping every `def ...(... module_name` in the file, so a private helper
    that resolves a dotted name it was handed — with no caller to detect — was
    convicted on the parameter NAME (found by dogfooding this checker on its own
    tree, 2026-08-31)."""

    def _check(self, content):
        from aipass.seedgo.apps.handlers.aipass_standards import handlers_check

        return handlers_check.check_auto_detection(content)

    def test_a_public_function_taking_module_name_still_needs_auto_detection(self):
        result = self._check("def log_operation(operation, data, module_name=None):\n    pass\n")
        assert result is not None and result["passed"] is False

    def test_a_private_helper_taking_module_name_is_not_the_rules_business(self):
        assert self._check("def _module_file(module_name, source_root):\n    return None\n") is None

    def test_a_keyword_only_module_name_on_a_public_function_still_counts(self):
        result = self._check("def write(data, *, module_name=None):\n    pass\n")
        assert result is not None and result["passed"] is False

    def test_a_public_function_with_auto_detection_passes(self):
        content = (
            "import inspect\n\n"
            "def log_operation(operation, data, module_name=None):\n"
            "    frame = inspect.stack()[1]\n    return frame\n"
        )
        result = self._check(content)
        assert result is not None and result["passed"] is True

    def test_a_file_with_no_module_name_parameter_is_silent(self):
        assert self._check("def check(path):\n    return path\n") is None

    def test_the_word_in_a_docstring_or_a_call_does_not_convict(self):
        """The old text scan keyed on `def name(... module_name`; the AST keys on
        the parameter itself, so prose and call sites cannot trigger it."""
        content = (
            'def resolve(path):\n    """Resolves a module_name for the caller."""\n    return log(module_name=path)\n'
        )
        assert self._check(content) is None

    def test_an_unparseable_file_falls_back_to_the_text_scan(self):
        """A file we could not read is not evidence the parameter is absent."""
        result = self._check("def log_operation(operation, module_name=None):\n    pass\n\ndef broken(:\n")
        assert result is not None and result["passed"] is False


class TestSilentCatchAllowsClassifyingAnExceptionIntoAValue:
    """@spawn's report (2026-08-31): `except FileNotFoundError: return "absent"`
    was flagged as a swallow. It is the opposite — the exception's information
    becomes the return value and the caller asserts on it. A logger call in a
    test helper would route production logging out of a suite, which is what the
    hygiene lane exists to stop, so two standards were pulling opposite ways.

    Two clauses, both measured: a SPECIFIC exception type (bare / Exception says
    only "it failed"), and a body of exactly one `return <constant>`.
    """

    def _lines(self, tmp_path, source):
        from aipass.seedgo.apps.handlers.aipass_standards import silent_catch_check

        target = tmp_path / "probe.py"
        target.write_text(source, encoding="utf-8")
        result = silent_catch_check.check_module(str(target))
        return result["checks"][0]["message"], result["checks"][0]["passed"]

    def test_a_named_exception_returning_a_constant_is_not_a_silent_catch(self, tmp_path):
        source = (
            "def final_state(path):\n"
            "    try:\n        return path.read_text()\n"
            "    except FileNotFoundError:\n        return 'absent'\n"
        )
        _message, passed = self._lines(tmp_path, source)
        assert passed is True

    def test_a_tuple_of_named_exceptions_still_qualifies(self, tmp_path):
        source = (
            "def verdict(run):\n"
            "    try:\n        return run()\n"
            "    except (AssertionError, ValueError):\n        return 'FAILED'\n"
        )
        _message, passed = self._lines(tmp_path, source)
        assert passed is True

    def test_a_dotted_exception_name_qualifies(self, tmp_path):
        """pytest.skip.Exception is the shape @spawn actually catches."""
        source = (
            "import pytest\n\n"
            "def verdict(run):\n"
            "    try:\n        return run()\n"
            "    except pytest.skip.Exception:\n        return 'SKIPPED'\n"
        )
        _message, passed = self._lines(tmp_path, source)
        assert passed is True

    def test_catching_Exception_broadly_keeps_its_finding(self, tmp_path):
        """ "It failed" is not a classification: the type carries no meaning, so
        the caller learns nothing the return value could not have hidden."""
        source = "def f(run):\n    try:\n        return run()\n    except Exception:\n        return False\n"
        _message, passed = self._lines(tmp_path, source)
        assert passed is False

    def test_a_bare_except_keeps_its_finding(self, tmp_path):
        source = "def f(run):\n    try:\n        return run()\n    except:\n        return None\n"
        _message, passed = self._lines(tmp_path, source)
        assert passed is False

    def test_a_named_exception_that_only_passes_keeps_its_finding(self, tmp_path):
        """No value leaves the handler, so nothing was classified."""
        source = "def f(run):\n    try:\n        run()\n    except FileNotFoundError:\n        pass\n"
        _message, passed = self._lines(tmp_path, source)
        assert passed is False

    def test_a_named_exception_that_continues_keeps_its_finding(self, tmp_path):
        source = (
            "def f(items):\n    for i in items:\n        try:\n            i()\n"
            "        except FileNotFoundError:\n            continue\n"
        )
        _message, passed = self._lines(tmp_path, source)
        assert passed is False

    def test_extra_statements_before_the_return_keep_the_finding(self, tmp_path):
        """The shape is a CONVERSION, not a body that happens to end in one —
        work done on the way out is work the finding should still be read for."""
        source = (
            "def f(run, state):\n    try:\n        return run()\n"
            "    except FileNotFoundError:\n        state['seen'] = True\n        return 'absent'\n"
        )
        _message, passed = self._lines(tmp_path, source)
        assert passed is False

    def test_a_computed_return_is_not_a_constant(self, tmp_path):
        source = (
            "def f(run, fallback):\n    try:\n        return run()\n"
            "    except FileNotFoundError:\n        return fallback()\n"
        )
        _message, passed = self._lines(tmp_path, source)
        assert passed is False

    def test_a_return_carrying_the_caught_exception_qualifies(self, tmp_path):
        """`return ("FAILED", str(exc))` carries MORE than a constant does.
        Keying on ast.Constant alone flagged the better version of the pattern —
        found by running the rule against @spawn's real file, not my examples."""
        source = (
            "def verdict(run):\n"
            "    try:\n        return ('PASSED', '')\n"
            "    except AssertionError as exc:\n        return ('FAILED', str(exc))\n"
        )
        _message, passed = self._lines(tmp_path, source)
        assert passed is True

    def test_a_computed_return_that_never_mentions_the_exception_stays_flagged(self, tmp_path):
        """Binding `as exc` is not enough — the value has to carry it."""
        source = (
            "def f(run, fallback):\n    try:\n        return run()\n"
            "    except FileNotFoundError as exc:\n        return fallback()\n"
        )
        _message, passed = self._lines(tmp_path, source)
        assert passed is False

    def test_counting_the_exception_and_continuing_stays_flagged(self, tmp_path):
        """A counter may be asserted on later or may be read by nobody, and this
        checker cannot see which — so the finding stands and the reader rules."""
        source = (
            "def f(items):\n    missing = 0\n    for i in items:\n        try:\n            i()\n"
            "        except FileNotFoundError:\n            missing += 1\n            continue\n    return missing\n"
        )
        _message, passed = self._lines(tmp_path, source)
        assert passed is False


class TestSilentCatchAllowsAHandlerThatReportsToAStream:
    """@commons' report (2026-08-31): a handler that PRINTS the failure was
    flagged as swallowing it.

    "Silently" is this standard's own word. Their entry point repairs
    sys.path[0] before any cross-branch import — @prax's logger is imported
    after that block, and importing it earlier is exactly what the repair exists
    to make safe — so the only instrument in that window is stderr, and the
    handler used it. The cure the checker demanded could not be written while
    the code already did what the standard asks.

    This is a correction against the definition, not a window exemption: it
    holds anywhere, and the CLI standard keeps asking separately whether the
    stream was the RIGHT instrument. Measured before landing: 1 handler in the
    fleet matches.
    """

    def _passed(self, tmp_path, source):
        from aipass.seedgo.apps.handlers.aipass_standards import silent_catch_check

        target = tmp_path / "probe.py"
        target.write_text(source, encoding="utf-8")
        return silent_catch_check.check_module(str(target))["checks"][0]["passed"]

    def test_a_handler_writing_to_stderr_is_not_silent(self, tmp_path):
        source = (
            "import sys\n\n"
            "try:\n    x = resolve()\n"
            "except OSError as exc:\n    sys.stderr.write(f'cannot resolve: {exc}\\n')\n"
        )
        assert self._passed(tmp_path, source) is True

    def test_a_handler_writing_to_stdout_is_not_silent_either(self, tmp_path):
        """The standard's word is 'silently', not 'stderr'. A report on stdout
        is a worse choice and a separate standard's argument, but it is still
        not silence, and this checker must not decide that question."""
        source = "import sys\n\ntry:\n    go()\nexcept OSError:\n    sys.stdout.write('failed\\n')\n"
        assert self._passed(tmp_path, source) is True

    def test_the_write_must_be_to_a_STREAM_not_any_write_method(self, tmp_path):
        """Negative control on the clause: ``handle.write(...)`` puts the
        failure in a file nobody is watching. Keying on the method name alone
        would have exempted every handler that quietly writes to disk.

        The handler deliberately does NOT bind the exception. A later clause
        (hands_the_exception_on) clears ``handle.write(str(exc))`` on its own
        and separately measured grounds — the object is not dropped — so binding
        it here would test that clause instead of this one and this pin would
        pass while the stream rule rotted underneath it.
        """
        source = "def f(handle):\n    try:\n        go()\n    except OSError:\n        handle.write('failed')\n"
        assert self._passed(tmp_path, source) is False

    def test_a_handler_that_reports_nothing_keeps_its_finding(self, tmp_path):
        source = "try:\n    go()\nexcept OSError:\n    pass\n"
        assert self._passed(tmp_path, source) is False

    def test_the_real_reported_shape_clears(self, tmp_path):
        """@commons' own block, transcribed. The pin the report actually earns."""
        source = (
            "import sys\n"
            "from pathlib import Path\n\n"
            "_script_dirs = [str(Path(__file__).parent)]\n"
            "try:\n    _script_dirs.append(str(Path(__file__).resolve().parent))\n"
            "except OSError as _exc:\n"
            "    sys.stderr.write(f'[commons] Cannot resolve {__file__} ({type(_exc).__name__})\\n')\n"
        )
        assert self._passed(tmp_path, source) is True


class TestCliAllowsARawWriteBeforeTheConsoleExists:
    """@commons' second finding, the same block one line down: the CLI checker
    demanded ``console.print()`` in the window BEFORE the module imports the
    console.

    Unsatisfiable, not merely wrong — and a checker that convicts on an
    unsatisfiable clause teaches branches to take waivers. Two AST clauses, and
    the PAIR is what keeps it narrow: the module must import the console at all,
    and the write must lexically precede that import. Measured across the fleet
    2026-08-31: the pair clears exactly one site; clause 1 alone (a module with
    no console) clears 0 today in this checker's scope and an unbounded number
    of future ones, so it was rejected on the measurement rather than on taste.
    """

    CONSOLE_IMPORT = "from aipass.cli.apps.modules import console\n"

    def _passed(self, tmp_path, source):
        from aipass.seedgo.apps.handlers.aipass_standards import cli_check

        target = tmp_path / "modules" / "probe.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source, encoding="utf-8")
        result = cli_check.check_print_usage(source, source.split("\n"), str(target))
        return result is None or result["passed"]

    def test_a_write_above_the_console_import_is_allowed(self, tmp_path):
        source = "import sys\n\nsys.stderr.write('bootstrap trouble\\n')\n\n" + self.CONSOLE_IMPORT
        assert self._passed(tmp_path, source) is True

    def test_a_write_below_the_console_import_keeps_its_finding(self, tmp_path):
        """The window closes at the import. Everything after it has Rich."""
        source = "import sys\n\n" + self.CONSOLE_IMPORT + "\nsys.stderr.write('late\\n')\n"
        assert self._passed(tmp_path, source) is False

    def test_a_write_on_the_import_line_itself_keeps_its_finding(self, tmp_path):
        """The boundary, pinned because a mutant walked through it.

        ``<`` and ``<=`` differ on exactly one line and both read fine. The
        console exists once that statement has run, so a write sharing the line
        is after it, not before it — the window is STRICTLY prior. Found by a
        surviving mutant, not by reading the code.
        """
        source = "import sys\n\n" + self.CONSOLE_IMPORT.rstrip("\n") + "; sys.stderr.write('same line\\n')\n"
        assert self._passed(tmp_path, source) is False

    def test_a_module_that_never_imports_the_console_keeps_its_finding(self, tmp_path):
        """Clause 1, pinned as a REFUSAL. Dropping it looks like a
        simplification — 'no console, nothing to use' — and it would hand every
        console-less module a blanket pass for raw writes."""
        source = "import sys\n\nsys.stderr.write('no console anywhere in this file\\n')\n"
        assert self._passed(tmp_path, source) is False

    def test_an_unparseable_file_gets_no_window(self, tmp_path):
        """Ignorance is not evidence of a bootstrap: a file the checker cannot
        parse keeps every finding rather than being exempted by the failure."""
        from aipass.seedgo.apps.handlers.aipass_standards import cli_check

        assert cli_check._console_import_line("def broken(:\n") is None

    def test_the_real_reported_shape_clears(self, tmp_path):
        """@commons' entry point, transcribed: the sys.path repair, its stderr
        report, then the cross-branch imports the repair exists to make safe."""
        source = (
            "import sys\n"
            "from pathlib import Path\n\n"
            "_script_dirs = [str(Path(__file__).parent)]\n"
            "try:\n    _script_dirs.append(str(Path(__file__).resolve().parent))\n"
            "except OSError as _exc:\n"
            "    sys.stderr.write('[commons] cannot resolve\\n')\n"
            "for _d in _script_dirs:\n    if _d in sys.path:\n        sys.path.remove(_d)\n\n"
            "from aipass.prax.apps.modules.logger import system_logger as logger  # noqa: E402\n"
            "from aipass.cli.apps.modules import console  # noqa: E402\n"
        )
        assert self._passed(tmp_path, source) is True


class TestAutoDetectionNoLongerMandatesTheDeadCwdDefect:
    """@prax's report (2026-08-31): the checker's proof of auto-detection was
    the literal string ``inspect.stack()``, and its failure message said "use
    inspect.stack()".

    That call is the Windows dead-cwd defect the fleet spent this week removing
    — it reaches an unguarded ``os.path.realpath`` in ``inspect.getmodule``, and
    ``ntpath.realpath`` reads ``os.getcwd()`` before checking anything. @prax
    cured their own site and the audit dropped the file to 66% and told them to
    put it back. They renamed a helper instead, which fixed prax and left the
    checker aimed at the next branch to cure — @spawn counted 16 of 18 branches
    still carrying the call.

    Measured before landing: ZERO fleet files passed via the inspect.stack()
    clause, so widening the acceptance changed nobody's score. The harm was
    entirely prospective, which is exactly when a checker is cheapest to fix.
    """

    def _check(self, content):
        from aipass.seedgo.apps.handlers.aipass_standards.handlers_check import (
            check_auto_detection,
        )

        return check_auto_detection(content)

    def test_the_cured_shape_passes_without_a_specially_named_helper(self):
        """@prax's blocking case. sys._getframe answers the same question and
        cannot die on a Windows box with no working directory."""
        content = (
            "import sys\n\n"
            "def log_operation(op, module_name=None):\n"
            "    if module_name is None:\n"
            "        module_name = sys._getframe(1).f_code.co_name\n"
            "    return module_name\n"
        )
        assert self._check(content)["passed"] is True

    def test_inspect_stack_still_counts_as_an_answer(self):
        """Widening, not a ban. Whether inspect.stack() is the RIGHT mechanism
        is @drone's dead-cwd sweep, a different standard; this one only asks
        whether the caller is detected at all. A checker that answered both
        questions would convict a branch mid-migration for the wrong reason."""
        content = (
            "import inspect\n\n"
            "def log_operation(op, module_name=None):\n"
            "    if module_name is None:\n"
            "        module_name = inspect.stack()[1]\n"
            "    return module_name\n"
        )
        assert self._check(content)["passed"] is True

    def test_the_mechanism_must_be_CALLED_not_merely_mentioned(self):
        """The substring hole, closed. A file whose only ``inspect.stack()`` is
        in a docstring was passing — and @drone hit the mirror image the same
        morning, a text BAN convicting the docstring that explained the cure.
        A string rule is too broad and too narrow at once."""
        content = (
            '"""We used to call inspect.stack() here — see the dead-cwd note."""\n'
            "import inspect\n\n"
            "def log_operation(op, module_name=None):\n    return module_name\n"
        )
        assert self._check(content)["passed"] is False

    def test_a_required_module_name_is_not_applicable(self):
        """Nothing to detect: every caller supplies it at every call site, so
        the prescribed frame walk would be dead code. Three @prax files were red
        for this."""
        assert self._check("def run(module_name: str):\n    return module_name\n") is None

    def test_an_optional_module_name_is_still_in_scope(self):
        """Negative control on the clause above — the narrowing must not
        exempt the population the standard is actually about."""
        assert self._check("def run(module_name=None):\n    return module_name\n") is not None

    def test_a_keyword_only_module_name_with_a_default_is_in_scope(self):
        """Boundary: the default lives in kw_defaults, a different list. Reading
        only positional defaults would silently exempt every keyword-only API."""
        assert self._check("def run(*, module_name=None):\n    return module_name\n") is not None

    def test_a_keyword_only_module_name_without_a_default_is_not(self):
        content = "def run(*, module_name: str):\n    return module_name\n"
        assert self._check(content) is None

    def test_the_failure_message_names_the_blind_spot(self):
        """@trigger's events/warning_logged.py carries a ``module_name`` that is
        an event PAYLOAD field — the module that logged a warning — while its
        caller is the event bus. Auto-detecting there would be wrong, and the
        checker reads the NAME and cannot tell them apart. I have no structural
        measure for that, so the finding states what it measured instead of
        carrying a clause I cannot defend."""
        result = self._check("def run(module_name=None):\n    return module_name\n")
        assert "event payload" in result["message"]

    def test_other_frame_walk_spellings_are_accepted_too(self):
        """The standard's question is whether the caller is detected, never
        which library spells it."""
        for call in ("inspect.currentframe()", "traceback.extract_stack()", "inspect.getouterframes(None)"):
            content = f"import inspect, traceback\n\ndef run(module_name=None):\n    x = {call}\n    return x\n"
            assert self._check(content)["passed"] is True, call


class TestAHandlerThatGuardsItsOwnDiagnosticIsNotSilent:
    """@daemon and @canary, 2026-08-31, the same site from two sides.

    The fleet's ratified dead-cwd cure wraps its own diagnostic:

        try:
            logger.debug(...)
        except Exception as inner:
            _retain("logger", inner)

    @daemon's own pin caught their first cut logging from OUTSIDE that try, and
    the world that reaches this code is a machine whose filesystem cannot answer
    a basic question — @prax's logger construction reads the working directory,
    so "the logger is also down" is the SAME world. The literal fix the checker
    demanded was to add a logger call to the handler for a logger failure: the
    defect their pin had just caught, put back to satisfy a score.

    @canary MEASURED the prescription instead of arguing with it — applying it
    verbatim made their branch unimportable.

    Measured before landing: 6 handlers in the fleet match, in 6 branches, and
    every one is this cure's diagnostic guard.
    """

    def _passed(self, tmp_path, source):
        from aipass.seedgo.apps.handlers.aipass_standards import silent_catch_check

        target = tmp_path / "probe.py"
        target.write_text(source, encoding="utf-8")
        return silent_catch_check.check_module(str(target))["checks"][0]["passed"]

    def test_a_pass_guarding_a_logger_call_is_not_silent(self, tmp_path):
        source = "def f(logger, exc):\n    try:\n        logger.debug('failed: %s', exc)\n    except Exception:\n        pass\n"
        assert self._passed(tmp_path, source) is True

    def test_a_pass_guarding_a_stream_report_is_not_silent(self, tmp_path):
        """@canary's shape: the write composes its message with type(exc), and
        counting THAT call as an effect is what made the first cut miss it."""
        source = (
            "import sys\n\n"
            "def f(name, exc, reported):\n"
            "    try:\n"
            "        if name not in reported:\n"
            "            reported.add(name)\n"
            "            sys.stderr.write(f'{name}: {type(exc).__name__}: {exc}\\n')\n"
            "    except OSError:\n        pass\n"
        )
        assert self._passed(tmp_path, source) is True

    def test_a_pass_guarding_REAL_WORK_keeps_its_finding(self, tmp_path):
        """The clause is on what the block DOES, not on the handler being empty.
        A try that computes something and a bare pass is the original defect."""
        source = "def f(path):\n    try:\n        path.unlink()\n    except OSError:\n        pass\n"
        assert self._passed(tmp_path, source) is False

    def test_a_report_STANDING_BESIDE_real_work_does_not_buy_the_exemption(self, tmp_path):
        """The purity clause, pinned because a mutant walked through it.

        Dropping ``all(...)`` and keeping only ``any(...)`` leaves a rule that a
        single log line can buy: wrap anything at all, add a logger call, and
        the handler goes quiet. The block has to be a diagnostic and NOTHING
        else. Found by mutation, not by reading.
        """
        source = (
            "def f(logger, path):\n    try:\n"
            "        logger.debug('about to unlink')\n        path.unlink()\n"
            "    except OSError:\n        pass\n"
        )
        assert self._passed(tmp_path, source) is False

    def test_a_file_handle_write_is_not_a_report(self, tmp_path):
        """The stream qualification, pinned on THIS clause rather than on
        silent_catch's own helper — a mutant that accepted any ``.write``
        survived every other pin, because the sibling clause was tested
        somewhere else and this one had no negative control of its own."""
        source = "def f(handle):\n    try:\n        handle.write('note')\n    except OSError:\n        pass\n"
        assert self._passed(tmp_path, source) is False

    def test_a_block_of_pure_bookkeeping_is_not_a_diagnostic(self, tmp_path):
        """Negative control: bookkeeping may sit BESIDE a report, never stand in
        for one. Without the at-least-one-report clause, every `seen.add(x)`
        wrapped in a try would buy the exemption."""
        source = "def f(seen, x):\n    try:\n        seen.add(x)\n    except OSError:\n        pass\n"
        assert self._passed(tmp_path, source) is False


class TestAHandlerThatHandsTheExceptionOnIsNotSilent:
    """@daemon's second shape, one level out from @spawn's classify-and-return:

        except OSError as exc:
            _record_unresolved(path, exc)
            return path

    Nothing is dropped — the exception becomes an argument to a named function
    that owns reporting it. There the information became a return value, here it
    becomes an argument; in both, the caller decides.

    Measured before landing: 10 handlers match fleet-wide and all 10 were read
    individually — six are this cure delegating to a named reporter, the rest a
    Rich report before sys.exit (@cli), a subprocess writing its error as JSON
    (@memory), a deliberately rate-limited queue warning (@prax) and a retained
    list (@trigger). Zero looked like a swallow.
    """

    def _passed(self, tmp_path, source):
        from aipass.seedgo.apps.handlers.aipass_standards import silent_catch_check

        target = tmp_path / "probe.py"
        target.write_text(source, encoding="utf-8")
        return silent_catch_check.check_module(str(target))["checks"][0]["passed"]

    def test_passing_the_exception_to_a_named_reporter_is_not_silent(self, tmp_path):
        source = (
            "def f(path, record):\n    try:\n        return path.resolve()\n"
            "    except OSError as exc:\n        record(path, exc)\n        return path\n"
        )
        assert self._passed(tmp_path, source) is True

    def test_retaining_the_exception_in_a_list_is_not_silent(self, tmp_path):
        source = "def f(kept):\n    try:\n        go()\n    except OSError as exc:\n        kept.append(str(exc))\n"
        assert self._passed(tmp_path, source) is True

    def test_binding_the_exception_and_ignoring_it_keeps_its_finding(self, tmp_path):
        """The clause is that the object LEAVES. Binding `as exc` and dropping it
        is the defect wearing the exemption's syntax.

        The body calls something unrelated on purpose. ``return None`` would
        have been the obvious probe and it is cleared by a DIFFERENT, older
        clause — a named exception returning a constant is @spawn's
        classify-and-return, ratified before this one — so it would have proved
        nothing about the clause under test. Found by this pin failing.
        """
        source = "def f(cleanup):\n    try:\n        go()\n    except OSError as exc:\n        cleanup()\n"
        assert self._passed(tmp_path, source) is False

    def test_an_unbound_handler_cannot_borrow_the_clause(self, tmp_path):
        """No `as` means no exception object to hand on, however many calls the
        body makes. Without this, `except OSError: cleanup(path)` would pass."""
        source = "def f(path, cleanup):\n    try:\n        go()\n    except OSError:\n        cleanup(path)\n"
        assert self._passed(tmp_path, source) is False


class TestErrorHandlingSharesTheDiagnosticGuardClause:
    """Two checkers, one question, one implementation — @canary's point that a
    single discriminator clears both findings. Shared rather than copied so the
    two cannot drift into disagreeing about the same handler.
    """

    def _passed(self, tmp_path, source):
        from aipass.seedgo.apps.handlers.aipass_standards import error_handling_check

        target = tmp_path / "probe.py"
        target.write_text(source, encoding="utf-8")
        return error_handling_check.check_module(str(target))["checks"][0]["passed"]

    def test_a_pass_guarding_a_report_is_not_a_silent_failure(self, tmp_path):
        source = "def f(logger, exc):\n    try:\n        logger.debug('x', exc)\n    except Exception:\n        pass\n"
        assert self._passed(tmp_path, source) is True

    def test_a_pass_over_real_work_is_still_a_silent_failure(self, tmp_path):
        source = "def f(path):\n    try:\n        path.unlink()\n    except OSError:\n        pass\n"
        assert self._passed(tmp_path, source) is False


class TestTheBootstrapChainSeesRelativeImports:
    """@canary's json_structure finding, and it was a hole in an exemption I
    ratified the night before.

    Clause 2 of the pre-logging bootstrap exemption asks whether the logging
    substrate's own imports REACH a module. The walk only followed absolute
    ``aipass.*`` imports, and @canary's json_handler reaches its stdlib-only
    helper with ``from ..paths import module_file`` — so a module that IS
    beneath the logging system was invisible to the walk and got told to import
    it. A relative import is a STATIC fact, unlike the importlib hops the walk
    deliberately cannot see, so resolving it moves the set toward correct in the
    direction the walk's own docstring already asks for.
    """

    def _resolve(self, module, level, package):
        from aipass.seedgo.apps.handlers.aipass_standards import json_structure_check

        return json_structure_check._resolve_relative(module, level, package)

    def test_a_sibling_import_resolves(self):
        assert self._resolve("paths", 2, "aipass.canary.apps.handlers.json") == "aipass.canary.apps.handlers.paths"

    def test_a_same_package_import_resolves(self):
        assert self._resolve("utils", 1, "aipass.canary.apps.handlers") == "aipass.canary.apps.handlers.utils"

    def test_a_bare_from_dot_import_resolves_to_the_package(self):
        assert self._resolve(None, 1, "aipass.canary.apps.handlers") == "aipass.canary.apps.handlers"

    def test_no_package_means_no_resolution(self):
        """Negative control: guessing an absolute name for a file we cannot
        place would put fabricated members into the chain, and the chain hands
        out exemptions. Coming up SHORT is the safe direction."""
        assert self._resolve("paths", 2, None) is None

    def test_climbing_past_the_root_answers_None(self):
        assert self._resolve("x", 9, "aipass.canary") is None

    def test_an_absolute_import_is_untouched_by_the_resolver(self):
        assert self._resolve("aipass.prax", 0, "aipass.canary.apps") is None

    def test_the_walk_reaches_a_relatively_imported_bootstrap_module(self, tmp_path):
        """End to end on the real tree: @canary's helper is in the chain now."""
        from pathlib import Path

        from aipass.seedgo.apps.handlers.aipass_standards import json_structure_check

        # parents[2] is src/aipass — parents[3] is src, and the wrong one made
        # this skip instead of run. A skip reports its own defeat as a pass,
        # which is the whole reason the branch is asserted rather than guessed.
        aipass_root = Path(__file__).resolve().parents[2]
        assert aipass_root.name == "aipass", aipass_root
        target = aipass_root / "canary" / "apps" / "handlers" / "paths.py"
        if not target.exists():
            import pytest

            pytest.skip(f"canary's paths.py is not on this machine ({target})")
        assert json_structure_check._is_prelogging_bootstrap(target, target.read_text(encoding="utf-8")) is True


class TestEncapsulationDerivesItsInfrastructureAllowList:
    """@daemon, 2026-08-31: two adjacent lines in their entry point, the
    json_handler import passing and the module_root import scoring the file 66%.

    Both are same-branch handler imports by the branch's own entry point, and
    the handlers guard itself permits exactly this — it blocks CROSS-branch
    imports. The checker exempted json_handler by NAME rather than by the
    property that makes it fine.

    The property: if json_handler may be imported anywhere, so may anything
    json_handler itself imports, because that module is BENEATH json_handler in
    the branch's own import order. Measured 2026-08-31: 8 of 9 branches carrying
    the dead-cwd cure have their json_handler importing it, so the derived set
    finds it without anyone naming a file.
    """

    def _names(self, branch_root):
        from aipass.seedgo.apps.handlers.aipass_standards import encapsulation_check

        encapsulation_check._infrastructure_handlers.cache_clear()
        return encapsulation_check._infrastructure_handlers(str(branch_root))

    def test_a_handler_the_branchs_json_handler_imports_is_infrastructure(self, tmp_path):
        branch = tmp_path / "mybranch"
        handlers = branch / "apps" / "handlers"
        (handlers / "json").mkdir(parents=True)
        (handlers / "module_root.py").write_text("def module_file(f):\n    return f\n", encoding="utf-8")
        (handlers / "json" / "json_handler.py").write_text(
            "from aipass.mybranch.apps.handlers.module_root import module_file\n", encoding="utf-8"
        )
        assert "module_root" in self._names(branch)

    def test_a_relatively_imported_one_counts_the_same(self, tmp_path):
        """@canary spells theirs ``from ..paths import module_file``. A rule that
        saw only absolute imports would exempt eight branches and not the ninth."""
        branch = tmp_path / "mybranch"
        handlers = branch / "apps" / "handlers"
        (handlers / "json").mkdir(parents=True)
        (handlers / "paths.py").write_text("def module_file(f):\n    return f\n", encoding="utf-8")
        (handlers / "json" / "json_handler.py").write_text("from ..paths import module_file\n", encoding="utf-8")
        assert "paths" in self._names(branch)

    def test_a_handler_json_handler_does_not_import_is_not_infrastructure(self, tmp_path):
        """Negative control: the set is DERIVED, not a longer allow-list. A
        domain handler stays behind its module entry point."""
        branch = tmp_path / "mybranch"
        handlers = branch / "apps" / "handlers"
        (handlers / "json").mkdir(parents=True)
        (handlers / "openrouter.py").write_text("def get_response():\n    return None\n", encoding="utf-8")
        (handlers / "json" / "json_handler.py").write_text("import json\n", encoding="utf-8")
        assert "openrouter" not in self._names(branch)

    def test_a_name_that_is_not_a_file_is_not_admitted(self, tmp_path):
        """The imported NAME must resolve to a real handler module. Without that,
        `from ..paths import module_file` would admit `module_file` too — a
        function name standing in for a module."""
        branch = tmp_path / "mybranch"
        handlers = branch / "apps" / "handlers"
        (handlers / "json").mkdir(parents=True)
        (handlers / "paths.py").write_text("def module_file(f):\n    return f\n", encoding="utf-8")
        (handlers / "json" / "json_handler.py").write_text("from ..paths import module_file\n", encoding="utf-8")
        assert "module_file" not in self._names(branch)

    def test_an_unreadable_json_handler_grants_nothing(self, tmp_path):
        """Ignorance is not evidence: a branch whose json_handler cannot be
        parsed keeps the ordinary rule rather than being exempted by the
        failure."""
        branch = tmp_path / "mybranch"
        handlers = branch / "apps" / "handlers"
        (handlers / "json").mkdir(parents=True)
        (handlers / "json" / "json_handler.py").write_text("def broken(:\n", encoding="utf-8")
        assert self._names(branch) == frozenset()


# ---------------------------------------------------------------------------
# cli: handler separation reads the STREAM, not the spelling
# ---------------------------------------------------------------------------


class TestHandlerSeparationJudgesTheStreamNotTheSpelling:
    """@flow, 2026-08-31: the cross-branch import fence scored 0 for two
    ``print(..., file=sys.stderr)`` lines behind an ``AIPASS_DEBUG_GUARD``
    env var, with the message "use logger instead" — in the one file in the
    branch that runs before any logger exists.

    Their argument was about the bootstrap window. The measurement found
    something plainer and worse: the checker ALREADY PASSES the identical
    effect written the other way. ``sys.stderr.write(msg)`` in a handler scores
    100 (@skills' module_paths.py, measured); ``print(msg, file=sys.stderr)``
    scores 0. Same stream, same bytes, same window — 100 points of difference
    decided by which spelling the author reached for.

    Handler separation exists so a handler does not DISPLAY. Display is stdout,
    the channel a router's output travels on; stderr is where a diagnostic goes
    precisely so it does not pollute that channel. So the fix is not a new
    exemption — it is the rule finally saying what it already meant on one of
    its two spellings.

    MEASURED before landing: 351 print lines across the fleet's handlers, 12 of
    them stderr-directed. Exactly six files change verdict, and all six are the
    same fence block (@ai_mail, @cli, @flow, @memory, @prax, @trigger).

    The other two stderr-directed prints live in @ai_mail's wake.py and
    @skills' telegram notifier, and BOTH files scored 100 before this clause
    and after it — every print in them, stderr-directed or not, sits inside an
    ``if __name__ == "__main__":`` block that handler separation has always
    excluded. Corrected here because the first measurement called them
    "partial" from the raw regex without asking the checker: a proxy count is
    not a verdict count, which is the mistake this class exists to stop me
    repeating.
    """

    def _sep(self, content):
        from aipass.seedgo.apps.handlers.aipass_standards.cli_check import check_handler_separation

        return check_handler_separation(content)

    def test_a_stderr_directed_print_is_a_diagnostic_not_display(self):
        content = (
            "import os\n"
            "import sys\n"
            "\n"
            "def _guard(caller_file, import_line):\n"
            "    if os.environ.get('AIPASS_DEBUG_GUARD'):\n"
            "        print(f'[GUARD DEBUG] caller_file = {caller_file}', file=sys.stderr)\n"
            "        print(f'[GUARD DEBUG] import_line = {import_line}', file=sys.stderr)\n"
        )
        assert self._sep(content)["passed"] is True

    def test_a_bare_print_keeps_its_finding(self):
        """Negative control. Without this the clause would read as "prints are
        fine in handlers now", which is the opposite of the ruling."""
        result = self._sep("def show(x):\n    print(x)\n")
        assert result["passed"] is False
        assert "[2]" in result["message"]

    def test_an_explicitly_stdout_directed_print_keeps_its_finding(self):
        """The discriminator is the STREAM. Naming stdout out loud is still
        display — arguably more so, since the author chose it."""
        assert self._sep("import sys\n\ndef show(x):\n    print(x, file=sys.stdout)\n")["passed"] is False

    def test_a_print_to_some_other_file_handle_keeps_its_finding(self):
        """A write to a handle nobody is watching is not a diagnostic. Same
        clause @commons' silent_catch ruling needed this morning: ``.write``
        reports only when the thing written to is a standard stream."""
        assert self._sep("def dump(x, fh):\n    print(x, file=fh)\n")["passed"] is False

    def test_only_the_file_keyword_directs_a_stream(self):
        """Mutation control (M3, survived the first run). Loosening the keyword
        check to accept ``sep`` exempted ``print(x, sep=sys.stderr)`` — a call
        that still writes every byte to stdout. Contrived code, but the clause
        must key on the argument that actually chooses the stream."""
        assert self._sep("import sys\n\ndef show(x):\n    print(x, sep=sys.stderr)\n")["passed"] is False

    def test_a_file_holding_both_keeps_the_finding_and_names_only_the_display_lines(self):
        """The exempted line must not shift the reported line numbers, or the
        finding sends its owner to the wrong place. Synthetic rather than
        borrowed from the fleet: the two live files that hold both kinds put
        every print inside a ``__main__`` block, so neither would exercise
        this."""
        content = (
            "import sys\n"
            "\n"
            "def report(x):\n"
            "    print('to the user', x)\n"
            "    print('diagnostic', file=sys.stderr)\n"
            "    print('also to the user', x)\n"
        )
        result = self._sep(content)
        assert result["passed"] is False
        assert "[4, 6]" in result["message"]

    def test_an_unparseable_file_keeps_every_print_finding(self):
        """Ignorance is not evidence. A file whose AST cannot be built has no
        stderr-directed prints PROVEN, so none are exempted — the same
        direction json_structure's bootstrap clause errs in."""
        result = self._sep("import sys\ndef broken(:\n    print('x', file=sys.stderr)\n")
        assert result["passed"] is False

    def test_the_two_real_fleet_files_now_agree(self):
        """End-to-end against the live tree, because the whole finding was that
        two spellings of one effect disagreed by 100 points. Asserts the files
        exist rather than skipping: a vacuous skip here would report the
        agreement it never checked."""
        from pathlib import Path

        from aipass.seedgo.apps.handlers.aipass_standards import cli_check

        aipass_root = Path(__file__).resolve().parents[2]
        assert aipass_root.name == "aipass", aipass_root
        stream_write = aipass_root / "skills" / "apps" / "handlers" / "module_paths.py"
        stream_print = aipass_root / "flow" / "apps" / "handlers" / "__init__.py"
        assert stream_write.exists() and stream_print.exists()

        written = cli_check.check_module(str(stream_write))
        printed = cli_check.check_module(str(stream_print))
        assert written["score"] == 100
        assert printed["score"] == written["score"], [c["message"] for c in printed["checks"] if not c["passed"]]


class TestTheCliRulingsAreQueryableNotJustEnforced:
    """@commons, 2026-08-31: "it currently lives in a docstring nobody queries,
    and I only found the wall by hitting it. A branch reading the standard first
    would have saved this whole exchange."

    A checker that enforces a rule the published standard does not state makes
    every branch discover it by failing. These pins hold the two cli rulings in
    the queryable content, and each asserts the CONCRETE spelling a reader needs
    rather than a topic word, so trimming the example out fails here.
    """

    def _content(self):
        from aipass.seedgo.apps.handlers.aipass_standards.cli_content import get_cli_standards

        return get_cli_standards()

    def test_the_pre_console_window_is_published_with_its_boundary(self):
        content = self._content()
        assert "pre-console bootstrap window" in content
        assert "STRICTLY prior" in content

    def test_the_stream_ruling_is_published_with_both_spellings(self):
        content = self._content()
        assert "print(msg, file=sys.stderr)" in content
        assert "sys.stderr.write(msg)" in content
        assert "print(msg, file=sys.stdout)" in content

    def test_the_published_rule_and_the_checker_agree(self):
        """The point of publishing is that a branch reading it gets the same
        answer the audit gives. Runs the checker over the exact snippets the
        standard shows, so the two cannot drift apart silently."""
        from aipass.seedgo.apps.handlers.aipass_standards.cli_check import check_handler_separation

        allowed = "import sys\n\ndef f(msg):\n    print(msg, file=sys.stderr)\n"
        refused = "import sys\n\ndef f(msg):\n    print(msg, file=sys.stdout)\n"
        assert check_handler_separation(allowed)["passed"] is True
        assert check_handler_separation(refused)["passed"] is False


class TestTheEmptyAnswerIsAConstantWhateverItsType:
    """Caught by dogfooding: my own new cli_check helper scored 0 on
    silent_catch for ``except SyntaxError: return set()``.

    The classify-and-return clause reads ``ast.Constant``, which in Python
    covers scalars and nothing else. So ``return ""`` was allowed and
    ``return []`` was flagged — two spellings of one idea, "this function found
    nothing", separated by which type the function happens to return. A
    function whose contract is a list has no other way to say it, and
    ``set()`` and ``frozenset()`` have no literal spelling at all.

    Same species as the stream ruling three hours earlier in this file: the
    verdict was being decided by the spelling rather than by what the code
    does. EMPTY only — a handler returning ``[1, 2]`` is fabricating an answer,
    not reporting an absence, and keeps its finding.

    MEASURED before landing: 16 handlers across the fleet match, every one of
    them ``return []``, ``return {}`` or ``return set()``.
    """

    def _judge(self, body):
        import ast

        from aipass.seedgo.apps.handlers.aipass_standards import silent_catch_check

        source = f"def f(c):\n    try:\n        return parse(c)\n    except SyntaxError:\n        {body}\n"
        tree = ast.parse(source)
        flagged = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Try):
                for handler in node.handlers:
                    flagged += silent_catch_check._judge_handler(handler, node, "x.py")
        return bool(flagged)

    @pytest.mark.parametrize("body", ["return []", "return {}", "return ()", "return set()", "return frozenset()"])
    def test_an_empty_container_is_the_same_answer_as_an_empty_string(self, body):
        assert self._judge(body) is False, body

    def test_the_scalar_spellings_still_pass(self):
        """Control: the clause this widens must keep working."""
        assert self._judge('return ""') is False
        assert self._judge("return 0") is False

    @pytest.mark.parametrize("body", ["return [1, 2]", "return {'a': 1}", "return {'x'}"])
    def test_a_NON_empty_literal_keeps_its_finding(self, body):
        """The boundary, and the reason the clause is not just "any literal": a
        handler that invents content is not reporting an absence."""
        assert self._judge(body) is True, body

    @pytest.mark.parametrize("body", ["return list(c)", "return dict(a=1)", "return set(c)"])
    def test_a_builtin_called_WITH_arguments_keeps_its_finding(self, body):
        """Negative control for the call form. ``set()`` is the empty set;
        ``set(c)`` is a computed answer wearing the same name."""
        assert self._judge(body) is True, body

    def test_a_computed_return_still_keeps_its_finding(self):
        assert self._judge("return compute(c)") is True

    @pytest.mark.parametrize("body", ["return compute()", "return build_default()", "return Path()"])
    def test_a_zero_ARGUMENT_call_to_anything_else_keeps_its_finding(self, body):
        """Mutation control (M4, survived the first run). Dropping the builtin
        name check exempted every no-argument call — a computed fallback that
        happens to take no arguments is still computed, and ``Path()`` is not an
        absence. The clause is the NAME and the emptiness together."""
        assert self._judge(body) is True, body

    def test_a_broad_except_gains_nothing_from_this(self):
        """The specific-exception clause is what makes the returned value
        meaningful. ``except Exception`` learns the caller nothing, so an empty
        list from it is still a swallow."""
        import ast

        from aipass.seedgo.apps.handlers.aipass_standards import silent_catch_check

        source = "def f(c):\n    try:\n        return parse(c)\n    except Exception:\n        return []\n"
        tree = ast.parse(source)
        flagged = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Try):
                for handler in node.handlers:
                    flagged += silent_catch_check._judge_handler(handler, node, "x.py")
        assert flagged

    def test_my_own_helper_is_the_case_that_found_this(self):
        """End-to-end on the live file, because dogfooding is what surfaced it
        and a synthetic-only pin would not have."""
        from pathlib import Path

        from aipass.seedgo.apps.handlers.aipass_standards import silent_catch_check

        target = Path(__file__).resolve().parents[1] / "apps" / "handlers" / "aipass_standards" / "cli_check.py"
        assert target.exists(), target
        assert "_stderr_directed_print_lines" in target.read_text(encoding="utf-8")
        assert silent_catch_check.check_module(str(target))["score"] == 100

    def test_the_empty_answer_ruling_is_published_too(self):
        """@commons' point, applied to my own new clause the same day: a rule
        that lives only in the checker makes every branch discover it by
        failing."""
        from aipass.seedgo.apps.handlers.aipass_standards.silent_catch_content import get_silent_catch_standards

        content = get_silent_catch_standards()
        assert "EMPTY ANSWER" in content
        assert "return set()" in content
        assert "return set(c)" in content


class TestFunctionDocstringsReadTheSourceNotTheStrings:
    """Caught by dogfooding: my own new nominator scored 50 on documentation
    for ``test_every_found_item_is_valid`` — a function that does not exist. It
    is three lines of a CODE EXAMPLE inside the module docstring.

    ``check_function_docstrings`` was a line scan: ``stripped.startswith("def ")``
    over the raw file, so any ``def`` inside a string literal was read as a real
    function. Every branch that built a subprocess world this week embedded
    Python in a string and got flagged for it — @api, @canary, @skills and two
    of my own files.

    The same scan had the mirror defect: it never matched ``async def`` at all,
    so an undocumented async function was invisible. ``find_import_section_end``
    in the same pack has handled ``async def`` since it was written.

    AST reads what Python reads. MEASURED before landing: 1841 files, 7 verdicts
    change — 5 false positives cleared, 2 genuine misses found, both of them
    async. Scope is unchanged on purpose: nested functions still count, because
    narrowing that would be a 40-file amnesty and a different decision.
    """

    def _check(self, source):
        from aipass.seedgo.apps.handlers.aipass_standards.documentation_check import check_function_docstrings

        return check_function_docstrings(source, source.split("\n"))

    def test_a_def_inside_a_docstring_is_not_a_function(self):
        """The exact shape that flagged my own nominator: a code example whose
        next `def`-or-`class` sentinel arrives before the docstring closes."""
        source = (
            '"""Module.\n'
            "\n"
            '    @pytest.mark.parametrize("item", collect())\n'
            "    def test_every_found_item_is_valid(item):\n"
            '        assert item["ok"]\n'
            '"""\n'
            "\n"
            "def real_one(x):\n"
            '    """Documented."""\n'
            "    return x\n"
        )
        # The fixture must PARSE, or this exercises the SyntaxError fallback and
        # proves nothing about the AST path. Caught while writing it: the first
        # version left the module docstring unterminated and went red for that.
        import ast

        ast.parse(source)
        result = self._check(source)
        assert result["passed"] is True, result["message"]

    def test_a_def_inside_a_string_constant_is_not_a_function(self):
        """The dead-cwd worlds' shape: a whole module built as a string and fed
        to a child. @canary, @api and @skills all carry one."""
        source = (
            'WORLD = """\nimport os\ndef realpath(p, *a, **k):\n    return p\n\ndef helper(q):\n    return q\n"""\n'
        )
        result = self._check(source)
        assert result["passed"] is True, result["message"]

    def test_a_real_undocumented_function_still_fails(self):
        """Negative control. Without this the fix reads as "documentation is
        optional now"."""
        result = self._check("def visible(x):\n    return x\n")
        assert result["passed"] is False
        assert "visible" in result["message"]

    def test_an_undocumented_ASYNC_function_is_finally_seen(self):
        """The line scan matched 'def ' and never 'async def', so @skills'
        telethon_auth.main has been invisible for as long as it has existed."""
        result = self._check("async def main() -> None:\n    return None\n")
        assert result["passed"] is False
        assert "main" in result["message"]

    def test_a_documented_async_function_passes(self):
        assert self._check('async def main() -> None:\n    """Does a thing."""\n')["passed"] is True

    def test_a_private_function_is_still_exempt(self):
        assert self._check("def _hidden(x):\n    return x\n")["passed"] is True

    def test_an_unparseable_file_keeps_the_line_scans_answer(self):
        """Ignorance is not evidence. A file whose AST cannot be built has not
        been PROVEN to document everything, so it falls back rather than being
        exempted by the failure — the direction json_structure's bootstrap
        clause errs in."""
        result = self._check("def visible(:\n    return 1\n")
        assert result["passed"] is False

    def test_the_reported_line_is_the_def_not_an_index(self):
        """@memory was sent to line 40 for a violation at line 106 once. The
        line in the message must be the line in the file."""
        source = "\n\n\n\n\ndef visible(x):\n    return x\n"
        assert "line 6" in self._check(source)["message"]


class TestModuleDocstringReadsThePositionNotTheSpelling:
    """The sibling defect, found the same way: by auditing a file of my own.

    ``check_module_docstring`` was a line scan for a line STARTING with a triple
    quote in the first 30. That is wrong in both directions, and both were
    measured across 1,845 files before the rule changed:

      - an r-prefixed module docstring does not start with a quote character, so
        the scan reported MISSING on a file that has one (this checker's own
        ``posix_literal_check.py``, scored 50 for a docstring it carries);
      - any triple-quoted string in the first 30 lines was credited to the
        module - a class docstring, a function docstring on a short file, a
        string sitting after an import where Python discards it. Seven files
        fleet-wide, and that is the direction that matters: a false negative
        gets believed.

    Blast radius measured with the real checker before the change: 8 verdicts
    move across 1,560 files. Six from 100 to 50 (@skills 5, @ai_mail 1), one
    from 50 to 0 (@hooks), one from 50 to 100 (mine). Owners mailed - reported,
    never edited.
    """

    def test_an_r_prefixed_docstring_is_a_docstring(self):
        """The false negative that started it."""
        source = 'r"""Raw module docstring."""\n\n\ndef f():\n    pass\n'
        result = documentation_check.check_module_docstring(source.split("\n"))
        assert result["passed"] is True

    @pytest.mark.parametrize("prefix", ["r", "R", "u", "b", "rb", "f"])
    def test_every_string_prefix_python_accepts_is_accepted_here(self, prefix):
        """A literal table over the prefixes, so this one cannot vanish. b and
        rb are not docstrings to ``ast.get_docstring`` and f-strings are not
        constants at all - the point of the row is that the ANSWER is Python's,
        whatever it is, rather than a guess made by looking at the first
        character."""
        source = prefix + '"""Text."""\n'
        expected = ast.get_docstring(ast.parse(source)) is not None
        result = documentation_check.check_module_docstring(source.split("\n"))
        assert result["passed"] is expected

    def test_a_string_after_an_import_is_NOT_a_module_docstring(self):
        """@ai_mail's header.py, reduced. Python evaluates and discards it;
        ``help()`` shows nothing. A reader sees documentation, which is exactly
        why the scan agreed with the reader and not with the interpreter."""
        source = 'import os\n\n"""Looks like documentation."""\n'
        result = documentation_check.check_module_docstring(source.split("\n"))
        assert result["passed"] is False

    def test_a_function_docstring_is_not_credited_to_the_module(self):
        """@skills' registry.py, reduced - five files of theirs scored 100 on
        the strength of the first function's docstring."""
        source = 'from pathlib import Path\n\n\ndef f():\n    """Real, and not the module\'s."""\n'
        result = documentation_check.check_module_docstring(source.split("\n"))
        assert result["passed"] is False

    def test_a_class_docstring_is_not_credited_to_the_module(self):
        """@hooks' test_live_config_timeouts.py, reduced."""
        source = 'import json\n\n\nclass TestX:\n    """A class docstring."""\n'
        result = documentation_check.check_module_docstring(source.split("\n"))
        assert result["passed"] is False

    def test_a_real_module_docstring_still_passes(self):
        """The positive control. A rule that failed everything would satisfy
        every negative pin above and teach nothing."""
        source = '"""The module docstring."""\n\n\ndef f():\n    pass\n'
        result = documentation_check.check_module_docstring(source.split("\n"))
        assert result["passed"] is True

    def test_a_docstring_after_the_AIPass_header_still_passes(self):
        """Every file in the fleet opens with a comment banner. If the AST arm
        had been wrong about comments, 1,677 files would have gone red at once -
        which is the kind of blast radius worth pinning rather than assuming."""
        source = "# === AIPass ===\n# Name: x.py\n# ===\n\n" + '"""Doc."""\n'
        result = documentation_check.check_module_docstring(source.split("\n"))
        assert result["passed"] is True

    def test_an_unparseable_file_falls_back_and_SAYS_SO(self):
        """The fallback must not read as a verdict from the real arm. My own
        round-2 sentence: an exemption bought with a SyntaxError is an exemption
        granted on ignorance."""
        source = '"""Doc."""\n\ndef broken(\n'
        with pytest.raises(SyntaxError):
            ast.parse(source)
        result = documentation_check.check_module_docstring(source.split("\n"))
        assert result["passed"] is True
        assert "does not parse" in result["message"]

    def test_the_unparseable_fallback_can_still_FAIL(self):
        """The negative control for the control. A fallback that always passes
        would make every unparseable file clean, which is the exemption-on-
        ignorance shape one level down."""
        source = "import os\n\ndef broken(\n"
        result = documentation_check.check_module_docstring(source.split("\n"))
        assert result["passed"] is False
        assert "does not parse" in result["message"]
