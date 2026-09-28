# =================== AIPass ====================
# Name: test_registry.py
# Description: Tests for registry driver auto-discovery
# Version: 1.0.0
# Created: 2026-05-12
# Modified: 2026-09-28
# =============================================

"""Tests for apps/modules/registry.py, driver auto-discovery for integrations."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(covered) — bridge's list_contracts() and call routing, tests/test_integrations.py
# seedgo: no-test-needed(stdlib) — importlib.util.spec_from_file_location's own loading of a file as a module

import sys

from aipass.api.apps.modules.bridge import clear, resolve
from aipass.api.apps.modules.registry import handle_command, load_drivers, print_introspection


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
        (project / "other.py").write_text("x = 1", encoding="utf-8")
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
            "    r('test_load', lambda *a: 'ok')\n",
            encoding="utf-8",
        )

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
        (project / "driver.py").write_text("raise ImportError('boom')", encoding="utf-8")
        assert load_drivers(integrations) == 0

    def test_skips_non_directories(self, tmp_path):
        """Regular files in integrations dir are skipped."""
        integrations = tmp_path / "integrations"
        integrations.mkdir()
        (integrations / "notadir.py").write_text("x = 1", encoding="utf-8")
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
                f"    r('{name}_contract', lambda *a: '{name}')\n",
                encoding="utf-8",
            )

        clear()
        loaded = load_drivers(integrations)
        assert loaded == 2
        clear()


class TestImportDriver:
    """Single driver import and registration, reached through load_drivers()."""

    def test_import_valid_driver(self, tmp_path):
        """
        A driver with register() is loaded AND its hook is called.

        The call stood alone before 2026-09-07 — no assertion at all, so an
        _import_driver that silently skipped the register() hook passed. The
        hook is the entire point of a driver: without it the module is loaded
        and registers nothing, which looks identical from the outside.
        """
        project = tmp_path / "integrations" / "proj"
        project.mkdir(parents=True)
        driver = project / "driver.py"
        driver.write_text(
            "LOADED = True\nREGISTERED = False\ndef register():\n    global REGISTERED\n    REGISTERED = True\n",
            encoding="utf-8",
        )

        assert load_drivers(tmp_path / "integrations") == 1

        # The namespaced key is the contract: two projects named driver.py
        # must not overwrite each other in sys.modules.
        loaded = sys.modules["_aipass_integration_proj"]
        assert loaded.LOADED is True, "the driver module was never executed"
        assert loaded.REGISTERED is True, "the driver was loaded but its register() hook never ran"

    def test_driver_without_register_hook(self, tmp_path):
        """
        No register() is not an error — the module still loads.

        Also a bare call. What is worth pinning is that the absence of the
        hook does not abort the import partway: a driver may register at
        module level instead, so its top-level code has to have run.
        """
        project = tmp_path / "integrations" / "proj2"
        project.mkdir(parents=True)
        driver = project / "driver.py"
        driver.write_text("LOADED = True\n", encoding="utf-8")

        assert load_drivers(tmp_path / "integrations") == 1

        assert sys.modules["_aipass_integration_proj2"].LOADED is True, (
            "a driver with no register() hook was not executed"
        )

    def test_unloadable_driver_is_skipped_not_counted(self, tmp_path, monkeypatch):
        """A driver.py that cannot be loaded (here a directory) is skipped and not counted."""
        (tmp_path / "integrations" / "fake" / "driver.py").mkdir(parents=True)
        # The failed load leaves its half-built module in sys.modules; the name is
        # entered through monkeypatch so teardown removes it (api, fleet green leg 3).
        monkeypatch.setitem(sys.modules, "_aipass_integration_fake", None)

        assert load_drivers(tmp_path / "integrations") == 0
        assert sys.modules["_aipass_integration_fake"] is not None, "the load was attempted, not skipped by name"


class TestRegistryHandleCommand:
    """Tests for handle_command() — utility module always returns False."""

    def test_returns_false_for_unknown(self):
        """Unknown command returns False."""
        assert handle_command("anything", ["stuff"]) is False

    def test_help_stays_silent(self, capsys):
        """A --help probe for another module's command prints nothing here."""
        assert handle_command("validate", ["--help"]) is False
        assert capsys.readouterr().out == ""

    def test_no_args_stays_silent(self, capsys):
        """Registry owns no commands — it must not prepend its banner to theirs.

        Registry is discovered before google_client, so anything printed here
        leaks into the output of the commands that module owns.
        """
        assert handle_command("validate", []) is False
        assert capsys.readouterr().out == ""


class TestPrintIntrospection:
    """Tests for print_introspection() — registry status display."""

    def test_introspection_reports_where_it_looks_for_drivers(self, capsys):
        """
        The self-map names the directory it scans and whether it has loaded.

        A bare call with no assertion until 2026-09-07. This module's whole
        job is auto-discovery, so the two facts an operator opens the self-map
        for are WHERE it looks and WHETHER it has run — an introspection that
        stopped printing either still "rendered without raising".
        """
        print_introspection()

        printed = capsys.readouterr().out

        assert "integrations" in printed, "the self-map no longer says where it scans for drivers"
        assert "Loaded:" in printed, "the self-map no longer says whether discovery has run"
