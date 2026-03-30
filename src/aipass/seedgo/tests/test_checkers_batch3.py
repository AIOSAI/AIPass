# =================== AIPass ====================
# Name: test_checkers_batch3.py
# Description: Batch 3 tests for 8 seedgo checker handlers
# Version: 1.0.0
# Created: 2026-03-29
# Modified: 2026-03-29
# =============================================

"""
Batch 3 tests for seedgo checker handlers.

Covers: log_structure_check, log_visibility_check, meta_check,
modules_check, permission_flags_check, readme_check, shebang_check,
silent_catch_check.

Each checker gets 3 tests: clean pass, violation caught, bypass respected.
"""

import os
import sys
import textwrap
import pytest
from pathlib import Path
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _mock_infrastructure(monkeypatch):
    """Mock heavy infrastructure imports so checkers load in isolation."""
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
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.json.json_handler", json_mod)

    # Force re-imports of all 8 checkers
    checker_modules = [
        "aipass.seedgo.apps.handlers.aipass_standards.log_structure_check",
        "aipass.seedgo.apps.handlers.aipass_standards.log_visibility_check",
        "aipass.seedgo.apps.handlers.aipass_standards.meta_check",
        "aipass.seedgo.apps.handlers.aipass_standards.modules_check",
        "aipass.seedgo.apps.handlers.aipass_standards.permission_flags_check",
        "aipass.seedgo.apps.handlers.aipass_standards.readme_check",
        "aipass.seedgo.apps.handlers.aipass_standards.shebang_check",
        "aipass.seedgo.apps.handlers.aipass_standards.silent_catch_check",
    ]
    for mod_name in checker_modules:
        monkeypatch.delitem(sys.modules, mod_name, raising=False)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

META_HEADER = textwrap.dedent("""\
    # =================== AIPass ====================
    # Name: {filename}
    # Description: Test file for checker
    # Version: 1.0.0
    # Created: 2026-03-29
    # Modified: 2026-03-29
    # =============================================
""")


def _write_temp_py(tmp_path: Path, name: str, content: str) -> str:
    """Write a .py file inside tmp_path and return its string path."""
    filepath = tmp_path / name
    filepath.write_text(content, encoding="utf-8")
    return str(filepath)


def _write_temp_py_with_meta(tmp_path: Path, name: str, body: str) -> str:
    """Write a .py file with a valid META header prepended."""
    full = META_HEADER.format(filename=name) + body
    return _write_temp_py(tmp_path, name, full)


# ===========================================================================
# 1. log_structure_check
# ===========================================================================

class TestLogStructureCheck:
    """Tests for log_structure_check.check_module."""

    def _import(self):
        from aipass.seedgo.apps.handlers.aipass_standards import log_structure_check
        return log_structure_check

    def test_log_structure_clean_passes(self, tmp_path):
        """Clean file with logs/ directory at branch root scores >= 75."""
        # Create branch-like structure: branch_root/apps/module.py + branch_root/logs/
        branch_root = tmp_path / "mybranch"
        apps_dir = branch_root / "apps"
        apps_dir.mkdir(parents=True)
        logs_dir = branch_root / "logs"
        logs_dir.mkdir()

        content = textwrap.dedent("""\
            import logging
            logger = logging.getLogger(__name__)
            logger.info("clean message")
        """)
        filepath = _write_temp_py(apps_dir, "clean_module.py", content)

        checker = self._import()
        result = checker.check_module(filepath)

        assert result["standard"] == "LOG_STRUCTURE"
        assert result["score"] >= 75
        assert result["passed"] is True

    def test_log_structure_violation_caught(self, tmp_path):
        """File with hardcoded absolute log path triggers a violation."""
        branch_root = tmp_path / "mybranch"
        apps_dir = branch_root / "apps"
        apps_dir.mkdir(parents=True)
        # No logs/ dir -- that alone is a violation
        # Plus hardcoded path
        content = textwrap.dedent("""\
            LOG_FILE = "/home/patrick/myapp.log"
        """)
        filepath = _write_temp_py(apps_dir, "bad_module.py", content)

        checker = self._import()
        result = checker.check_module(filepath)

        assert result["standard"] == "LOG_STRUCTURE"
        assert result["score"] < 100

    def test_log_structure_bypass_respected(self, tmp_path):
        """Bypass rule for log_structure yields score 100."""
        filepath = _write_temp_py(tmp_path, "any.py", "x = 1\n")

        checker = self._import()
        bypass = [{"standard": "log_structure", "file": "any.py"}]
        result = checker.check_module(filepath, bypass_rules=bypass)

        assert result["score"] == 100
        assert result["passed"] is True


# ===========================================================================
# 2. log_visibility_check
# ===========================================================================

class TestLogVisibilityCheck:
    """Tests for log_visibility_check.check_module."""

    def _import(self):
        from aipass.seedgo.apps.handlers.aipass_standards import log_visibility_check
        return log_visibility_check

    def test_log_visibility_clean_passes(self, tmp_path):
        """File with no logging usage passes cleanly."""
        content = textwrap.dedent("""\
            def hello():
                return "world"
        """)
        filepath = _write_temp_py(tmp_path, "clean.py", content)

        checker = self._import()
        result = checker.check_module(filepath)

        assert result["standard"] == "LOG_VISIBILITY"
        assert result["score"] >= 75
        assert result["passed"] is True

    def test_log_visibility_violation_caught(self, tmp_path):
        """File using logging.getLogger without prax import is a violation."""
        content = textwrap.dedent("""\
            import logging
            mylog = logging.getLogger(__name__)
            mylog.info("test")
        """)
        filepath = _write_temp_py(tmp_path, "bad_vis.py", content)

        checker = self._import()
        result = checker.check_module(filepath)

        assert result["standard"] == "LOG_VISIBILITY"
        # Should detect missing prax import
        assert result["score"] < 100

    def test_log_visibility_bypass_respected(self, tmp_path):
        """Bypass rule for log_visibility yields score 100."""
        content = textwrap.dedent("""\
            import logging
            mylog = logging.getLogger(__name__)
        """)
        filepath = _write_temp_py(tmp_path, "bypassed.py", content)

        checker = self._import()
        bypass = [{"standard": "log_visibility", "file": "bypassed.py"}]
        result = checker.check_module(filepath, bypass_rules=bypass)

        assert result["score"] == 100
        assert result["passed"] is True


# ===========================================================================
# 3. meta_check
# ===========================================================================

class TestMetaCheck:
    """Tests for meta_check.check_module."""

    def _import(self):
        from aipass.seedgo.apps.handlers.aipass_standards import meta_check
        return meta_check

    def test_meta_clean_passes(self, tmp_path):
        """File WITH a valid META header passes."""
        content = META_HEADER.format(filename="good_meta.py") + '\nx = 1\n'
        filepath = _write_temp_py(tmp_path, "good_meta.py", content)

        checker = self._import()
        result = checker.check_module(filepath)

        assert result["standard"] == "META"
        assert result["score"] >= 75
        assert result["passed"] is True

    def test_meta_violation_caught(self, tmp_path):
        """File WITHOUT a META header fails."""
        content = textwrap.dedent("""\
            # Just a regular comment
            import os
            x = 1
        """)
        filepath = _write_temp_py(tmp_path, "no_meta.py", content)

        checker = self._import()
        result = checker.check_module(filepath)

        assert result["standard"] == "META"
        assert result["score"] < 100
        # META block presence check should fail
        failed_names = [c["name"] for c in result["checks"] if not c["passed"]]
        assert "META block present" in failed_names

    def test_meta_bypass_respected(self, tmp_path):
        """Bypass rule for meta yields score 100."""
        filepath = _write_temp_py(tmp_path, "skip.py", "x = 1\n")

        checker = self._import()
        bypass = [{"standard": "meta", "file": "skip.py"}]
        result = checker.check_module(filepath, bypass_rules=bypass)

        assert result["score"] == 100
        assert result["passed"] is True


# ===========================================================================
# 4. modules_check
# ===========================================================================

class TestModulesCheck:
    """Tests for modules_check.check_module."""

    def _import(self):
        from aipass.seedgo.apps.handlers.aipass_standards import modules_check
        return modules_check

    def test_modules_clean_passes(self, tmp_path):
        """Module file in apps/modules/ with handle_command passes."""
        modules_dir = tmp_path / "apps" / "modules"
        modules_dir.mkdir(parents=True)

        content = textwrap.dedent("""\
            from typing import List

            def handle_command(command: str, args: List[str]) -> bool:
                if command == "test":
                    return True
                return False

            def print_help():
                print("Help text")

            def print_introspection():
                print("Module info")
        """)
        filepath = _write_temp_py(modules_dir, "good_mod.py", content)
        # The checker needs 'apps/modules/' in the path
        result = self._import().check_module(filepath)

        assert result["standard"] == "MODULES"
        assert result["score"] >= 75
        assert result["passed"] is True

    def test_modules_violation_caught(self, tmp_path):
        """Module file missing handle_command triggers violation."""
        modules_dir = tmp_path / "apps" / "modules"
        modules_dir.mkdir(parents=True)

        # 700 lines to trigger file size violation too
        content = textwrap.dedent("""\
            def do_stuff():
                pass
        """)
        # Also a very large file to hit file-size check
        content += "\n".join(f"line_{i} = {i}" for i in range(650))
        filepath = _write_temp_py(modules_dir, "bad_mod.py", content)

        result = self._import().check_module(filepath)

        assert result["standard"] == "MODULES"
        assert result["score"] < 100

    def test_modules_bypass_respected(self, tmp_path):
        """Bypass rule for modules yields score 100."""
        modules_dir = tmp_path / "apps" / "modules"
        modules_dir.mkdir(parents=True)
        filepath = _write_temp_py(modules_dir, "bypass_mod.py", "x = 1\n")

        bypass = [{"standard": "modules", "file": "bypass_mod.py"}]
        result = self._import().check_module(filepath, bypass_rules=bypass)

        assert result["score"] == 100
        assert result["passed"] is True


# ===========================================================================
# 5. permission_flags_check
# ===========================================================================

class TestPermissionFlagsCheck:
    """Tests for permission_flags_check.check_module."""

    def _import(self):
        from aipass.seedgo.apps.handlers.aipass_standards import permission_flags_check
        return permission_flags_check

    def test_permission_flags_clean_passes(self, tmp_path):
        """File using the approved flag pattern passes."""
        content = textwrap.dedent("""\
            CMD = "--permission-mode bypassPermissions"
            run(CMD)
        """)
        filepath = _write_temp_py(tmp_path, "clean_perm.py", content)

        checker = self._import()
        result = checker.check_module(filepath)

        assert result["standard"] == "PERMISSION_FLAGS"
        assert result["score"] >= 75
        assert result["passed"] is True

    def test_permission_flags_violation_caught(self, tmp_path):
        """File using dangerously-skip-permissions is caught."""
        content = textwrap.dedent("""\
            CMD = "--dangerously-skip-permissions"
            run(CMD)
        """)
        filepath = _write_temp_py(tmp_path, "bad_perm.py", content)

        checker = self._import()
        result = checker.check_module(filepath)

        assert result["standard"] == "PERMISSION_FLAGS"
        assert result["score"] < 100
        failed_names = [c["name"] for c in result["checks"] if not c["passed"]]
        assert "No dangerous permission flags" in failed_names

    def test_permission_flags_bypass_respected(self, tmp_path):
        """Bypass rule for permission_flags yields score 100."""
        content = textwrap.dedent("""\
            CMD = "--dangerously-skip-permissions"
        """)
        filepath = _write_temp_py(tmp_path, "bypass_perm.py", content)

        checker = self._import()
        bypass = [{"standard": "permission_flags", "file": "bypass_perm.py"}]
        result = checker.check_module(filepath, bypass_rules=bypass)

        assert result["score"] == 100
        assert result["passed"] is True


# ===========================================================================
# 6. readme_check
# ===========================================================================

class TestReadmeCheck:
    """Tests for readme_check.check_module (entry_point scope)."""

    def _import(self):
        from aipass.seedgo.apps.handlers.aipass_standards import readme_check
        return readme_check

    def _make_branch(self, tmp_path: Path) -> tuple[Path, str]:
        """Create a minimal branch structure with README and return (branch_root, entry_path)."""
        branch_root = tmp_path / "mybranch"
        apps_dir = branch_root / "apps"
        apps_dir.mkdir(parents=True)

        readme_content = textwrap.dedent("""\
            # MyBranch

            *Last Updated: 2026-03-29*

            ## Architecture

            Overview of architecture.

            ## Commands

            - `run` - runs stuff
            - `help` - shows help

            ## Integration Points

            - Depends on prax for logging
        """)
        readme_path = branch_root / "README.md"
        readme_path.write_text(readme_content, encoding="utf-8")

        entry = _write_temp_py(apps_dir, "mybranch.py", "# entry\n")
        return branch_root, entry

    def test_readme_clean_passes(self, tmp_path):
        """Branch with complete README passes."""
        _branch_root, entry = self._make_branch(tmp_path)

        checker = self._import()
        result = checker.check_module(entry)

        assert result["standard"] == "README"
        assert result["score"] >= 75
        assert result["passed"] is True

    def test_readme_violation_caught(self, tmp_path):
        """Branch with missing README fails."""
        branch_root = tmp_path / "nobranch"
        apps_dir = branch_root / "apps"
        apps_dir.mkdir(parents=True)
        # No README.md at all
        entry = _write_temp_py(apps_dir, "nobranch.py", "# entry\n")

        checker = self._import()
        result = checker.check_module(entry)

        assert result["standard"] == "README"
        assert result["score"] < 100
        failed_names = [c["name"] for c in result["checks"] if not c["passed"]]
        assert "README exists" in failed_names

    def test_readme_bypass_respected(self, tmp_path):
        """Bypass rule for readme yields score 100."""
        branch_root = tmp_path / "bypassed"
        apps_dir = branch_root / "apps"
        apps_dir.mkdir(parents=True)
        entry = _write_temp_py(apps_dir, "bypassed.py", "# entry\n")

        checker = self._import()
        bypass = [{"standard": "readme", "file": "bypassed.py"}]
        result = checker.check_module(entry, bypass_rules=bypass)

        assert result["score"] == 100
        assert result["passed"] is True


# ===========================================================================
# 7. shebang_check
# ===========================================================================

class TestShebangCheck:
    """Tests for shebang_check.check_module."""

    def _import(self):
        from aipass.seedgo.apps.handlers.aipass_standards import shebang_check
        return shebang_check

    def test_shebang_clean_passes(self, tmp_path):
        """File WITHOUT a shebang passes."""
        content = textwrap.dedent("""\
            # Normal Python file
            import os
            print("hello")
        """)
        filepath = _write_temp_py(tmp_path, "clean_shebang.py", content)

        checker = self._import()
        result = checker.check_module(filepath)

        assert result["standard"] == "SHEBANG"
        assert result["score"] == 100
        assert result["passed"] is True

    def test_shebang_violation_caught(self, tmp_path):
        """File WITH a shebang line is caught."""
        content = "#!/usr/bin/env python3\nimport os\nprint('hello')\n"
        filepath = _write_temp_py(tmp_path, "bad_shebang.py", content)

        checker = self._import()
        result = checker.check_module(filepath)

        assert result["standard"] == "SHEBANG"
        assert result["score"] == 0
        assert result["passed"] is False
        assert any("shebang" in c["message"].lower() for c in result["checks"])

    def test_shebang_bypass_respected(self, tmp_path):
        """Bypass rule for shebang yields score 100."""
        content = "#!/usr/bin/env python3\nimport os\n"
        filepath = _write_temp_py(tmp_path, "bypass_shebang.py", content)

        checker = self._import()
        bypass = [{"standard": "shebang", "file": "bypass_shebang.py"}]
        result = checker.check_module(filepath, bypass_rules=bypass)

        assert result["score"] == 100
        assert result["passed"] is True


# ===========================================================================
# 8. silent_catch_check
# ===========================================================================

class TestSilentCatchCheck:
    """Tests for silent_catch_check.check_module."""

    def _import(self):
        from aipass.seedgo.apps.handlers.aipass_standards import silent_catch_check
        return silent_catch_check

    def test_silent_catch_clean_passes(self, tmp_path):
        """File with properly logged except blocks passes."""
        content = textwrap.dedent("""\
            import logging
            logger = logging.getLogger(__name__)

            def safe_op():
                try:
                    x = 1 / 0
                except ZeroDivisionError:
                    logger.error("division by zero")

            def safe_reraise():
                try:
                    x = int("abc")
                except ValueError:
                    raise
        """)
        filepath = _write_temp_py(tmp_path, "clean_catch.py", content)

        checker = self._import()
        result = checker.check_module(filepath)

        assert result["standard"] == "SILENT_CATCH"
        assert result["score"] >= 75
        assert result["passed"] is True

    def test_silent_catch_violation_caught(self, tmp_path):
        """File with silent except block (no log, no raise) is caught."""
        content = textwrap.dedent("""\
            def bad_op():
                try:
                    x = 1 / 0
                except Exception:
                    pass

            def also_bad():
                try:
                    y = int("abc")
                except ValueError:
                    x = 42
        """)
        filepath = _write_temp_py(tmp_path, "bad_catch.py", content)

        checker = self._import()
        result = checker.check_module(filepath)

        assert result["standard"] == "SILENT_CATCH"
        assert result["score"] < 100
        assert result["passed"] is False
        # Should mention silent catch in the message
        assert any("silent" in c["message"].lower() for c in result["checks"])

    def test_silent_catch_bypass_respected(self, tmp_path):
        """Bypass rule for silent_catch yields score 100."""
        content = textwrap.dedent("""\
            def bad_op():
                try:
                    x = 1 / 0
                except Exception:
                    pass
        """)
        filepath = _write_temp_py(tmp_path, "bypass_catch.py", content)

        checker = self._import()
        bypass = [{"standard": "silent_catch", "file": "bypass_catch.py"}]
        result = checker.check_module(filepath, bypass_rules=bypass)

        assert result["score"] == 100
        assert result["passed"] is True
