"""
Tests for the drone-compliance seedgo plugin.

Covers:
  - Passes on packages with proper drone_adapter.py
  - Fails on packages missing drone_adapter.py
  - Fails on adapter missing DRONE_MODULE / handle_command / get_help
  - Skips non-target packages
  - Handles syntax errors in adapter files
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from seedgo.plugins.drone_compliance import PLUGIN_NAME, check


class TestDroneCompliancePass:
    """Packages with proper drone adapters should pass."""

    def test_seedgo_adapter_passes(self, tmp_path: Path):
        """seedgo's own drone_adapter.py passes all checks."""
        # Create a fake "seedgo" package with a proper adapter
        pkg = tmp_path / "seedgo"
        pkg.mkdir()
        (pkg / "__init__.py").write_text('"""Seedgo package."""\n')
        (pkg / "drone_adapter.py").write_text(
            textwrap.dedent("""\
            DRONE_MODULE = {"name": "seedgo", "version": "1.0.0", "description": "test"}

            def handle_command(command, args=None):
                return {"stdout": "", "stderr": "", "exit_code": 0}

            def get_help(command=None):
                return "help text"

            def get_introspective():
                return {}
            """)
        )

        result = check(str(pkg / "__init__.py"), config={"target_packages": ["seedgo"]})

        assert result.plugin == PLUGIN_NAME
        assert result.passed is True
        assert result.score == 100

    def test_all_checks_present(self, tmp_path: Path):
        """All checks pass: adapter exists, DRONE_MODULE with keys, handle_command, get_help, get_introspective."""
        pkg = tmp_path / "mymod"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "drone_adapter.py").write_text(
            textwrap.dedent("""\
            DRONE_MODULE = {"name": "mymod", "version": "0.1.0", "description": "test"}

            def handle_command(command, args=None):
                return {}

            def get_help(command=None):
                return ""

            def get_introspective():
                return {}
            """)
        )

        result = check(str(pkg / "__init__.py"), config={"target_packages": ["mymod"]})
        assert result.passed is True
        assert result.score == 100


class TestDroneComplianceFail:
    """Packages missing drone adapter components should fail."""

    def test_missing_adapter_fails(self, tmp_path: Path):
        """Package without drone_adapter.py fails."""
        pkg = tmp_path / "seedgo"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")

        result = check(str(pkg / "__init__.py"), config={"target_packages": ["seedgo"]})

        assert result.passed is False
        assert result.score == 0
        error_names = [c.name for c in result.checks if not c.passed]
        assert "adapter-exists" in error_names

    def test_missing_drone_module_dict(self, tmp_path: Path):
        """Adapter without DRONE_MODULE fails."""
        pkg = tmp_path / "mymod"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "drone_adapter.py").write_text(
            textwrap.dedent("""\
            def handle_command(command, args=None):
                return {}

            def get_help(command=None):
                return ""
            """)
        )

        result = check(str(pkg / "__init__.py"), config={"target_packages": ["mymod"]})
        assert result.passed is False
        failed = [c.name for c in result.checks if not c.passed]
        assert "drone-module-meta" in failed

    def test_missing_handle_command(self, tmp_path: Path):
        """Adapter without handle_command fails."""
        pkg = tmp_path / "mymod"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "drone_adapter.py").write_text(
            textwrap.dedent("""\
            DRONE_MODULE = {"name": "mymod", "version": "1.0.0", "description": "test"}

            def get_help(command=None):
                return ""
            """)
        )

        result = check(str(pkg / "__init__.py"), config={"target_packages": ["mymod"]})
        assert result.passed is False
        failed = [c.name for c in result.checks if not c.passed]
        assert "handle-command" in failed

    def test_missing_get_help_is_warning(self, tmp_path: Path):
        """Adapter without get_help is a warning, not an error — still passes."""
        pkg = tmp_path / "mymod"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "drone_adapter.py").write_text(
            textwrap.dedent("""\
            DRONE_MODULE = {"name": "mymod", "version": "1.0.0", "description": "test"}

            def handle_command(command, args=None):
                return {}
            """)
        )

        result = check(str(pkg / "__init__.py"), config={"target_packages": ["mymod"]})
        # Missing get_help is WARNING severity, not ERROR — should still pass
        assert result.passed is True
        warnings = [c for c in result.checks if not c.passed]
        assert any(c.name == "get-help" for c in warnings)

    def test_missing_drone_module_keys(self, tmp_path: Path):
        """Adapter with DRONE_MODULE but missing required keys fails."""
        pkg = tmp_path / "mymod"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "drone_adapter.py").write_text(
            textwrap.dedent("""\
            DRONE_MODULE = {"name": "mymod"}

            def handle_command(command, args=None):
                return {}

            def get_help(command=None):
                return ""
            """)
        )

        result = check(str(pkg / "__init__.py"), config={"target_packages": ["mymod"]})
        assert result.passed is False
        failed = [c.name for c in result.checks if not c.passed]
        assert "drone-module-keys" in failed

    def test_missing_get_introspective_is_warning(self, tmp_path: Path):
        """Adapter without get_introspective is a warning, not an error — still passes."""
        pkg = tmp_path / "mymod"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "drone_adapter.py").write_text(
            textwrap.dedent("""\
            DRONE_MODULE = {"name": "mymod", "version": "1.0.0", "description": "test"}

            def handle_command(command, args=None):
                return {}

            def get_help(command=None):
                return ""
            """)
        )

        result = check(str(pkg / "__init__.py"), config={"target_packages": ["mymod"]})
        # Missing get_introspective is WARNING severity, not ERROR — should still pass
        assert result.passed is True
        warnings = [c for c in result.checks if not c.passed]
        assert any(c.name == "get-introspective" for c in warnings)


class TestDroneComplianceSkip:
    """Non-target packages should be skipped."""

    def test_non_target_package_skipped(self, tmp_path: Path):
        """Packages not in target_packages are skipped with pass."""
        pkg = tmp_path / "unrelated"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")

        result = check(str(pkg / "__init__.py"), config={"target_packages": ["seedgo"]})
        assert result.passed is True
        assert result.metadata.get("skipped") is True

    def test_file_not_found_passes(self, tmp_path: Path):
        """Non-existent file returns pass (skipped)."""
        result = check(str(tmp_path / "nonexistent" / "__init__.py"))
        assert result.passed is True


class TestDroneComplianceEdgeCases:
    """Edge cases for the compliance check."""

    def test_syntax_error_in_adapter(self, tmp_path: Path):
        """Adapter with syntax error fails gracefully."""
        pkg = tmp_path / "mymod"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "drone_adapter.py").write_text("def broken(:\n")

        result = check(str(pkg / "__init__.py"), config={"target_packages": ["mymod"]})
        assert result.passed is False
        failed = [c.name for c in result.checks if not c.passed]
        assert "adapter-parseable" in failed
