# =================== AIPass ====================
# Name: test_registry.py
# Description: Tests for registry driver auto-discovery
# Version: 1.0.0
# Created: 2026-05-12
# Modified: 2026-05-12
# =============================================

"""Tests for registry.py — driver auto-discovery for integrations."""

from unittest.mock import patch

import pytest

from aipass.api.apps.modules.registry import load_drivers, _import_driver


class TestLoadDrivers:
    """Tests for load_drivers() — auto-discovery of integration drivers."""

    def test_no_directory(self, tmp_path):
        """Missing directory returns 0."""
        missing = tmp_path / "nonexistent"
        assert load_drivers(missing) == 0

    def test_empty_directory(self, tmp_path):
        """Empty integrations dir returns 0."""
        integrations = tmp_path / "integrations"
        integrations.mkdir()
        assert load_drivers(integrations) == 0

    def test_directory_with_no_driver_py(self, tmp_path):
        """Project dir without driver.py is skipped."""
        integrations = tmp_path / "integrations"
        project = integrations / "myproject"
        project.mkdir(parents=True)
        (project / "other.py").write_text("x = 1")
        assert load_drivers(integrations) == 0

    def test_loads_valid_driver(self, tmp_path):
        """Valid driver.py with register() hook is loaded."""
        integrations = tmp_path / "integrations"
        project = integrations / "testdriver"
        project.mkdir(parents=True)
        driver = project / "driver.py"
        driver.write_text(
            "def register():\n"
            "    from aipass.api.apps.modules.bridge import register as r\n"
            "    r('test_load', lambda *a: 'ok')\n"
        )

        from aipass.api.apps.modules.bridge import clear, resolve

        clear()
        loaded = load_drivers(integrations)
        assert loaded == 1
        assert resolve("test_load") is not None
        clear()

    def test_skips_broken_driver(self, tmp_path):
        """Driver that raises on import is skipped."""
        integrations = tmp_path / "integrations"
        project = integrations / "broken"
        project.mkdir(parents=True)
        (project / "driver.py").write_text("raise ImportError('boom')")
        assert load_drivers(integrations) == 0

    def test_skips_non_directories(self, tmp_path):
        """Regular files in integrations dir are skipped."""
        integrations = tmp_path / "integrations"
        integrations.mkdir()
        (integrations / "notadir.py").write_text("x = 1")
        assert load_drivers(integrations) == 0

    def test_multiple_drivers(self, tmp_path):
        """Multiple valid drivers all get loaded."""
        integrations = tmp_path / "integrations"
        for name in ["alpha", "beta"]:
            d = integrations / name
            d.mkdir(parents=True)
            (d / "driver.py").write_text(
                f"def register():\n"
                f"    from aipass.api.apps.modules.bridge import register as r\n"
                f"    r('{name}_contract', lambda *a: '{name}')\n"
            )

        from aipass.api.apps.modules.bridge import clear

        clear()
        loaded = load_drivers(integrations)
        assert loaded == 2
        clear()


class TestImportDriver:
    """Tests for _import_driver() — single driver import and registration."""

    def test_import_valid_driver(self, tmp_path):
        """Valid driver.py with register() is imported successfully."""
        project = tmp_path / "proj"
        project.mkdir()
        driver = project / "driver.py"
        driver.write_text("LOADED = True\ndef register(): pass\n")
        _import_driver(driver, "proj")

    def test_driver_without_register_hook(self, tmp_path):
        """Driver without register() is still loaded without error."""
        project = tmp_path / "proj2"
        project.mkdir()
        driver = project / "driver.py"
        driver.write_text("LOADED = True\n")
        _import_driver(driver, "proj2")

    def test_invalid_spec_raises(self, tmp_path):
        """Nonexistent driver path raises ImportError or FileNotFoundError."""
        fake_path = tmp_path / "nonexistent.py"
        with pytest.raises((ImportError, FileNotFoundError)):
            _import_driver(fake_path, "fake")


class TestRegistryHandleCommand:
    """Tests for handle_command() — utility module always returns False."""

    def test_returns_false_for_unknown(self):
        """Unknown command returns False."""
        from aipass.api.apps.modules.registry import handle_command

        assert handle_command("anything", ["stuff"]) is False

    def test_help_stays_silent(self, capsys):
        """A --help probe for another module's command prints nothing here."""
        from aipass.api.apps.modules.registry import handle_command

        assert handle_command("validate", ["--help"]) is False
        assert capsys.readouterr().out == ""

    def test_no_args_stays_silent(self, capsys):
        """Registry owns no commands — it must not prepend its banner to theirs.

        Registry is discovered before google_client, so anything printed here
        leaks into the output of the commands that module owns.
        """
        from aipass.api.apps.modules.registry import handle_command

        assert handle_command("validate", []) is False
        assert capsys.readouterr().out == ""


class TestPrintIntrospection:
    """Tests for print_introspection() — registry status display."""

    @patch("aipass.api.apps.modules.registry.console")
    @patch("aipass.api.apps.modules.registry.header")
    def test_runs_without_error(self, _mock_header, _mock_console):
        """Introspection renders without raising."""
        from aipass.api.apps.modules.registry import print_introspection

        print_introspection()
