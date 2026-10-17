# =================== AIPass ====================
# Name: test_checkers_batch7_imports.py
# Description: imports_check sub-functions and rulings (split from test_checkers_batch7.py)
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-17
# =============================================

"""Tests for apps/handlers/aipass_standards/imports_check.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that each checker in handlers/aipass_standards/ parses and imports

import pytest

from aipass.seedgo.apps.handlers.aipass_standards import imports_check
from aipass.seedgo.apps.handlers.aipass_standards.imports_check import (
    check_handler_independence,
    check_import_order,
    check_no_aipass_root,
    check_no_bare_imports,
    check_no_sys_path,
    check_prax_logger,
    filter_docstrings,
    find_import_section_end,
)
from aipass.seedgo.tests.support_checkers_batch7 import _lines

pytestmark = pytest.mark.usefixtures("_pin_bypass_log")


class TestFilterDocstrings:
    """Tests for filter_docstrings."""

    def test_removes_multiline_docstring(self):
        """Multi-line docstring lines are removed."""
        lines = _lines('"""\nThis is a docstring.\n"""\nimport os\n')
        result = filter_docstrings(lines)
        assert any("import os" in ln for ln in result)
        assert not any("docstring" in ln for ln in result)

    def test_removes_single_line_docstring(self):
        """Single-line docstring is removed."""
        lines = _lines('"""Module docstring."""\nimport os\n')
        result = filter_docstrings(lines)
        assert any("import os" in ln for ln in result)
        assert not any("Module docstring" in ln for ln in result)

    def test_preserves_code(self):
        """Non-docstring lines are preserved."""
        lines = _lines("import os\nimport sys\n")
        result = filter_docstrings(lines)
        assert len([ln for ln in result if ln.strip()]) == 2


class TestFindImportSectionEnd:
    """Tests for find_import_section_end."""

    def test_finds_def(self):
        """Stops at first def statement."""
        lines = _lines("import os\nimport sys\n\ndef main():\n    pass\n")
        result = find_import_section_end(lines)
        assert result == 3  # index of 'def main():'

    def test_finds_class(self):
        """Stops at first class statement."""
        lines = _lines("import os\n\nclass Foo:\n    pass\n")
        result = find_import_section_end(lines)
        assert result == 2  # index of 'class Foo:'

    def test_no_def_returns_length(self):
        """File with no def/class returns length of lines."""
        lines = _lines("import os\nimport sys\nx = 42\n")
        result = find_import_section_end(lines)
        assert result == len(lines)


class TestCheckNoAipassRoot:
    """Tests for check_no_aipass_root."""

    def test_clean_file_passes(self, tmp_path):
        """File without AIPASS_ROOT passes."""
        lines = _lines("import os\nfrom aipass.prax import logger\n")
        result = check_no_aipass_root(lines, (tmp_path / "test.py").as_posix())
        assert result["passed"] is True

    def test_aipass_root_usage_fails(self, tmp_path):
        """File using AIPASS_ROOT fails."""
        lines = _lines("root = AIPASS_ROOT / 'config'\n")
        result = check_no_aipass_root(lines, (tmp_path / "test.py").as_posix())
        assert result["passed"] is False
        assert "AIPASS_ROOT" in result["message"]


class TestCheckNoSysPath:
    """Tests for check_no_sys_path."""

    def test_clean_file_passes(self, tmp_path):
        """File without sys.path hacking passes."""
        lines = _lines("import os\nimport sys\n")
        result = check_no_sys_path(lines, (tmp_path / "test.py").as_posix())
        assert result["passed"] is True

    def test_sys_path_insert_fails(self, tmp_path):
        """File with sys.path.insert fails."""
        lines = _lines("import sys\nsys.path.insert(0, '/my/path')\n")
        result = check_no_sys_path(lines, (tmp_path / "test.py").as_posix())
        assert result["passed"] is False
        assert "sys.path" in result["message"]

    def test_sys_path_append_fails(self, tmp_path):
        """File with sys.path.append fails."""
        lines = _lines("import sys\nsys.path.append('/my/path')\n")
        result = check_no_sys_path(lines, (tmp_path / "test.py").as_posix())
        assert result["passed"] is False


class TestCheckPraxLogger:
    """Tests for check_prax_logger."""

    def test_prax_import_passes(self, tmp_path):
        """File with from aipass.prax import logger passes."""
        lines = _lines("from aipass.prax import logger\n")
        result = check_prax_logger(lines, (tmp_path / "test.py").as_posix())
        assert result is not None
        assert result["passed"] is True

    def test_missing_prax_import_fails(self, tmp_path):
        """File without prax logger import fails."""
        lines = _lines("import os\nimport sys\n")
        result = check_prax_logger(lines, (tmp_path / "test.py").as_posix())
        assert result is not None
        assert result["passed"] is False
        assert "Prax logger" in result["message"]


class TestCheckPraxLoggerAcceptsBothBindings:
    """The standard is about ROUTING; both bindings route identically."""

    def _check(self, source: str, tmp_path) -> dict:
        result = check_prax_logger(_lines(source), (tmp_path / "test.py").as_posix())
        assert result is not None
        return result

    def test_the_rebindable_module_form_passes(self, tmp_path):
        assert self._check("from aipass import prax\n", tmp_path)["passed"] is True

    def test_the_object_form_still_passes(self, tmp_path):
        assert self._check("from aipass.prax import logger\n", tmp_path)["passed"] is True

    def test_prax_inside_a_multi_name_import_counts(self, tmp_path):
        assert self._check("from aipass import cli, prax\n", tmp_path)["passed"] is True

    def test_an_aliased_prax_still_counts(self, tmp_path):
        assert self._check("from aipass import prax as p\n", tmp_path)["passed"] is True

    def test_a_sibling_package_is_not_mistaken_for_prax(self, tmp_path):
        # `from aipass import cli` must NOT satisfy a prax-logging rule.
        assert self._check("from aipass import cli\n", tmp_path)["passed"] is False

    def test_a_name_that_merely_starts_with_prax_is_not_prax(self, tmp_path):
        # Substring matching would accept this; the check splits the import
        # list and compares whole names.
        assert self._check("from aipass import praxis\n", tmp_path)["passed"] is False

    def test_prax_imported_from_somewhere_that_is_not_aipass_does_not_count(self, tmp_path):
        # Found by mutation: deleting the "from aipass import " prefix guard
        # killed no test, so any package exporting a name `prax` would have
        # satisfied an AIPASS logging rule.
        assert self._check("from thirdparty import prax\n", tmp_path)["passed"] is False

    def test_a_commented_out_import_does_not_count(self, tmp_path):
        assert self._check("# from aipass import prax\n", tmp_path)["passed"] is False

    def test_a_commented_out_object_form_import_does_not_count_either(self, tmp_path):
        # The module form is rejected by the source-package guard even without the comment skip, so only the
        # OBJECT form exercises it.
        assert self._check("# from aipass.prax import logger\n", tmp_path)["passed"] is False

    def test_the_failure_message_offers_both_spellings(self, tmp_path):
        message = self._check("import os\n", tmp_path)["message"]
        assert "from aipass.prax import logger" in message
        assert "from aipass import prax" in message


class TestImportsHandlerIndependence:
    """Tests for imports_check.check_handler_independence."""

    def test_clean_handler_passes(self, tmp_path):
        """Handler without parent module imports passes."""
        lines = _lines("from aipass.prax import logger\n")
        result = check_handler_independence(
            lines, (tmp_path / "seedgo" / "apps" / "handlers" / "json" / "handler.py").as_posix()
        )
        assert result is not None
        assert result["passed"] is True

    def test_parent_module_import_fails(self, tmp_path):
        """Handler importing from parent branch modules fails."""
        lines = _lines("from seedgo.apps.modules.audit import run\n")
        result = check_handler_independence(
            lines, (tmp_path / "seedgo" / "apps" / "handlers" / "json" / "handler.py").as_posix()
        )
        assert result is not None
        assert result["passed"] is False
        assert "parent module" in result["message"]

    def test_infrastructure_import_passes(self, tmp_path):
        """Infrastructure imports (aipass.prax, aipass.cli) are allowed."""
        lines = _lines(
            "from aipass.prax.apps.modules.logger import info\nfrom aipass.cli.apps.modules.display import header\n"
        )
        result = check_handler_independence(
            lines, (tmp_path / "seedgo" / "apps" / "handlers" / "json" / "handler.py").as_posix()
        )
        assert result is not None
        assert result["passed"] is True


class TestCheckImportOrder:
    """Tests for check_import_order."""

    def test_correct_order_passes(self, tmp_path):
        """Stdlib before aipass imports passes."""
        lines = _lines("import os\nimport sys\nfrom aipass.prax import logger\n")
        result = check_import_order(lines, (tmp_path / "test.py").as_posix())
        assert result is not None
        assert result["passed"] is True

    def test_wrong_order_fails(self, tmp_path):
        """Aipass import before stdlib fails."""
        lines = _lines("from aipass.prax import logger\nimport os\n")
        result = check_import_order(lines, (tmp_path / "test.py").as_posix())
        assert result is not None
        assert result["passed"] is False
        assert "before stdlib" in result["message"]

    def test_no_imports_returns_none(self, tmp_path):
        """File with no imports returns None."""
        lines = _lines("x = 42\n")
        result = check_import_order(lines, (tmp_path / "test.py").as_posix())
        assert result is None


class TestCheckNoBareImports:
    """Tests for check_no_bare_imports."""

    def test_proper_namespace_passes(self, tmp_path):
        """Import using aipass.* namespace passes."""
        lines = _lines("from aipass.seedgo.apps.handlers.json import json_handler\n")
        result = check_no_bare_imports(lines, (tmp_path / "test.py").as_posix())
        assert result is not None
        assert result["passed"] is True

    def test_bare_handler_import_fails(self, tmp_path):
        """Bare 'from handlers.X' import fails."""
        lines = _lines("from handlers.json import json_handler\n")
        result = check_no_bare_imports(lines, (tmp_path / "test.py").as_posix())
        assert result is not None
        assert result["passed"] is False
        assert "bare import" in result["message"]

    def test_bare_module_import_fails(self, tmp_path):
        """Bare 'from drone.apps...' without aipass prefix fails."""
        lines = _lines("from drone.apps.modules.commander import route\n")
        result = check_no_bare_imports(lines, (tmp_path / "test.py").as_posix())
        assert result is not None
        assert result["passed"] is False
        assert "missing aipass." in result["message"]

    def test_stdlib_import_passes(self, tmp_path):
        """Standard library imports pass."""
        lines = _lines("import os\nfrom pathlib import Path\n")
        result = check_no_bare_imports(lines, (tmp_path / "test.py").as_posix())
        assert result is not None
        assert result["passed"] is True


class TestAipassRootIsMatchedAsATokenNotASubstring:
    """`AIPASS_ROOTS.json` is a FILENAME, not the AIPASS_ROOT env var."""

    def _check(self, line):
        return check_no_aipass_root([line + "\n"], "mod.py", [])

    def test_the_env_var_is_still_caught(self):
        assert not self._check('root = os.environ["AIPASS_ROOT"]')["passed"]

    def test_the_env_var_via_getenv_is_still_caught(self):
        assert not self._check('root = os.getenv("AIPASS_ROOT")')["passed"]

    def test_a_bare_reference_is_still_caught(self):
        assert not self._check("path = AIPASS_ROOT / 'x'")["passed"]

    def test_the_declared_roots_filename_is_not_a_violation(self):
        """@memory's exact line."""
        assert self._check('DECLARED_ROOTS = "AIPASS_ROOTS.json"')["passed"]

    def test_a_future_aipass_root_map_is_not_a_violation_either(self):
        """The report named this one specifically as the next collision."""
        assert self._check('NAME = "AIPASS_ROOT_MAP.json"')["passed"]

    def test_aipass_roots_registry_is_not_a_violation(self):
        assert self._check('NAME = "AIPASS_ROOTS_REGISTRY.json"')["passed"]

    def test_a_longer_name_ending_in_the_token_is_not_a_violation(self):
        """Prefix-only matching would still convict this one."""
        assert self._check('NAME = "MY_AIPASS_ROOT"')["passed"]

    def test_the_env_var_inside_an_fstring_is_still_caught(self):
        assert not self._check('msg = f"{AIPASS_ROOT}/x"')["passed"]


class TestImportsCheckLineNumbersSurviveDocstringFiltering:
    """A reported line number must name the line in the FILE."""

    def test_filter_docstrings_preserves_the_line_count(self):
        source = ['"""doc\n', "more doc\n", '"""\n', "import os\n"]
        assert len(filter_docstrings(source)) == len(source)

    def test_the_docstring_body_is_still_neutralised(self):
        """Preserving the line must not un-filter its content."""
        out = filter_docstrings(['"""\n', "AIPASS_ROOT lives here\n", '"""\n', "import os\n"])
        assert "AIPASS_ROOT" not in "".join(out)

    def test_a_violation_after_a_docstring_reports_its_real_line(self):
        source = ['"""\n', "a\n", "b\n", "c\n", '"""\n', 'x = os.environ["AIPASS_ROOT"]\n']
        result = check_no_aipass_root(filter_docstrings(source), "mod.py", [])
        assert not result["passed"]
        assert "line 6" in result["message"], result["message"]

    def test_the_real_reported_file_now_passes_end_to_end(self):
        """@memory's actual file, through the real entry point."""
        from pathlib import Path

        target = Path(__file__).resolve().parents[2] / "memory" / "apps" / "handlers" / "monitor" / "registry_scope.py"
        if not target.exists():
            import pytest

            pytest.skip("registry_scope.py not on disk")
        rows = imports_check.check_module(str(target))["checks"]
        root_rows = [r for r in rows if r["name"] == "No AIPASS_ROOT"]
        assert root_rows and root_rows[0]["passed"], root_rows
