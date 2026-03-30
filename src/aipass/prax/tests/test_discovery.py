# =================== AIPass ====================
# Name: test_discovery.py
# Description: Unit tests for discovery handlers
# Version: 1.0.0
# Created: 2026-03-29
# Modified: 2026-03-29
# =============================================

"""Unit tests for PRAX discovery handlers.

Tests filtering.should_ignore_path, scanner.scan_directory_safely,
and scanner.discover_python_modules.
"""

import importlib
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# =============================================
# FIXTURES
# =============================================

@pytest.fixture()
def mock_ignore_patterns(monkeypatch):
    """Mock the ignore_patterns config module in sys.modules."""
    mock_mod = MagicMock()
    mock_mod.load_ignore_patterns_from_config = MagicMock(
        return_value={'.git', '__pycache__', '.venv', 'node_modules'}
    )
    monkeypatch.setitem(
        sys.modules,
        "aipass.prax.apps.handlers.config.ignore_patterns",
        mock_mod,
    )
    return mock_mod


@pytest.fixture()
def mock_config_load(monkeypatch, tmp_path):
    """Mock the config.load module with tmp_path-based roots."""
    mock_mod = MagicMock()
    mock_mod.PRAX_ROOT = tmp_path / "prax"
    mock_mod.ECOSYSTEM_ROOT = tmp_path
    mock_mod.get_system_logs_dir = MagicMock(
        return_value=tmp_path / "system_logs"
    )
    mock_mod.get_module_logs_dir = MagicMock(
        return_value=tmp_path / "logs"
    )
    monkeypatch.setitem(
        sys.modules,
        "aipass.prax.apps.handlers.config.load",
        mock_mod,
    )
    return mock_mod


@pytest.fixture()
def filtering_module(mock_ignore_patterns, mock_prax_infrastructure):
    """Import filtering module with all dependencies mocked."""
    mod_name = "aipass.prax.apps.handlers.discovery.filtering"
    if mod_name in sys.modules:
        return importlib.reload(sys.modules[mod_name])
    import aipass.prax.apps.handlers.discovery.filtering as mod
    return mod


@pytest.fixture()
def scanner_module(mock_ignore_patterns, mock_config_load, mock_prax_infrastructure):
    """Import scanner module with all dependencies mocked."""
    # Scanner imports filtering, so ensure filtering is also reloaded
    filt_name = "aipass.prax.apps.handlers.discovery.filtering"
    if filt_name in sys.modules:
        importlib.reload(sys.modules[filt_name])

    mod_name = "aipass.prax.apps.handlers.discovery.scanner"
    if mod_name in sys.modules:
        return importlib.reload(sys.modules[mod_name])
    import aipass.prax.apps.handlers.discovery.scanner as mod
    return mod


# =============================================
# should_ignore_path TESTS
# =============================================

class TestShouldIgnorePath:
    """Tests for filtering.should_ignore_path."""

    def test_returns_bool(self, filtering_module):
        """should_ignore_path must return a bool."""
        result = filtering_module.should_ignore_path(Path("/some/normal/file.py"))
        assert isinstance(result, bool)

    def test_ignores_git_directory(self, filtering_module):
        """.git paths should be ignored."""
        assert filtering_module.should_ignore_path(Path("/repo/.git/objects/ab")) is True

    def test_ignores_pycache(self, filtering_module):
        """__pycache__ paths should be ignored."""
        assert filtering_module.should_ignore_path(Path("/project/__pycache__/mod.pyc")) is True

    def test_ignores_venv(self, filtering_module):
        """.venv paths should be ignored."""
        assert filtering_module.should_ignore_path(Path("/project/.venv/lib/python3/site.py")) is True

    def test_ignores_node_modules(self, filtering_module):
        """node_modules paths should be ignored."""
        assert filtering_module.should_ignore_path(Path("/project/node_modules/pkg/index.js")) is True

    def test_normal_path_not_ignored(self, filtering_module):
        """Regular project paths should not be ignored."""
        assert filtering_module.should_ignore_path(Path("/project/src/module.py")) is False

    def test_root_path_not_ignored(self, filtering_module):
        """A bare root path should not be ignored."""
        assert filtering_module.should_ignore_path(Path("/")) is False

    def test_relative_path(self, filtering_module):
        """Relative paths should also be checked correctly."""
        assert filtering_module.should_ignore_path(Path("src/app/main.py")) is False
        assert filtering_module.should_ignore_path(Path("src/__pycache__/main.pyc")) is True

    def test_deeply_nested_ignored_dir(self, filtering_module):
        """Ignored dir deep in the tree should still be caught."""
        deep = Path("/a/b/c/d/.git/refs/heads/main")
        assert filtering_module.should_ignore_path(deep) is True

    def test_similar_name_not_ignored(self, filtering_module):
        """Directories with names similar to ignored patterns should pass."""
        # 'git_utils' is not '.git'
        assert filtering_module.should_ignore_path(Path("/project/git_utils/helper.py")) is False

    def test_logs_filtered_path(self, filtering_module, mock_prax_infrastructure):
        """When a path is ignored, json_handler.log_operation should be called."""
        filtering_module.should_ignore_path(Path("/repo/.git/config"))
        mocks = mock_prax_infrastructure
        mocks.json_handler.log_operation.assert_called()


# =============================================
# scan_directory_safely TESTS
# =============================================

class TestScanDirectorySafely:
    """Tests for scanner.scan_directory_safely."""

    def test_returns_dict_populated_with_py_files(self, scanner_module, tmp_path):
        """Scanning a directory with .py files should populate the dict."""
        py_file = tmp_path / "example.py"
        py_file.write_text("# example", encoding="utf-8")

        modules: dict = {}
        scanner_module.scan_directory_safely(tmp_path, modules)
        assert "example" in modules
        assert isinstance(modules["example"], dict)

    def test_ignores_non_python_files(self, scanner_module, tmp_path):
        """Non-.py files should not appear in results."""
        (tmp_path / "data.txt").write_text("hello", encoding="utf-8")
        (tmp_path / "config.json").write_text("{}", encoding="utf-8")

        modules: dict = {}
        scanner_module.scan_directory_safely(tmp_path, modules)
        assert len(modules) == 0

    def test_empty_directory(self, scanner_module, tmp_path):
        """Scanning an empty directory should produce no modules."""
        modules: dict = {}
        scanner_module.scan_directory_safely(tmp_path, modules)
        assert modules == {}

    def test_nonexistent_directory(self, scanner_module, tmp_path):
        """Scanning a nonexistent directory should not raise."""
        missing = tmp_path / "does_not_exist"
        modules: dict = {}
        scanner_module.scan_directory_safely(missing, modules)
        assert modules == {}

    def test_recurses_into_subdirectories(self, scanner_module, tmp_path):
        """Should find .py files in nested directories."""
        sub = tmp_path / "pkg" / "sub"
        sub.mkdir(parents=True)
        (sub / "nested.py").write_text("# nested", encoding="utf-8")

        modules: dict = {}
        scanner_module.scan_directory_safely(tmp_path, modules)
        assert "nested" in modules

    def test_skips_ignored_subdirectories(self, scanner_module, tmp_path):
        """Subdirectories matching ignore patterns should be skipped."""
        cache_dir = tmp_path / "__pycache__"
        cache_dir.mkdir()
        (cache_dir / "cached.py").write_text("# cached", encoding="utf-8")

        modules: dict = {}
        scanner_module.scan_directory_safely(tmp_path, modules)
        assert "cached" not in modules

    def test_max_depth_zero_returns_nothing(self, scanner_module, tmp_path):
        """max_depth=0 should immediately return without scanning."""
        (tmp_path / "top.py").write_text("# top", encoding="utf-8")

        modules: dict = {}
        scanner_module.scan_directory_safely(tmp_path, modules, max_depth=0)
        assert modules == {}

    def test_max_depth_one_scans_only_top(self, scanner_module, tmp_path):
        """max_depth=1 should scan the directory but not recurse further."""
        (tmp_path / "top.py").write_text("# top", encoding="utf-8")
        sub = tmp_path / "child"
        sub.mkdir()
        (sub / "deep.py").write_text("# deep", encoding="utf-8")

        modules: dict = {}
        scanner_module.scan_directory_safely(tmp_path, modules, max_depth=1)
        assert "top" in modules
        # child dir is visited but depth decrements to 0, so deep.py is not found
        assert "deep" not in modules

    def test_module_metadata_fields(self, scanner_module, tmp_path):
        """Discovered modules should have all expected metadata keys."""
        py_file = tmp_path / "mymod.py"
        py_file.write_text("x = 1\n", encoding="utf-8")

        modules: dict = {}
        scanner_module.scan_directory_safely(tmp_path, modules)

        assert "mymod" in modules
        meta = modules["mymod"]
        expected_keys = {
            "file_path", "relative_path", "system_log_file",
            "log_file", "discovered_time", "size",
            "modified_time", "enabled",
        }
        assert expected_keys.issubset(meta.keys())
        assert meta["enabled"] is True
        assert meta["size"] > 0

    def test_handles_permission_error_gracefully(self, scanner_module, tmp_path):
        """Permission errors should be caught, not raised."""
        restricted = tmp_path / "restricted"
        restricted.mkdir()
        restricted.chmod(0o000)

        modules: dict = {}
        try:
            scanner_module.scan_directory_safely(restricted, modules)
        finally:
            restricted.chmod(0o755)

        assert modules == {}


# =============================================
# discover_python_modules TESTS
# =============================================

class TestDiscoverPythonModules:
    """Tests for scanner.discover_python_modules."""

    def test_returns_dict(self, scanner_module, tmp_path, mock_config_load):
        """discover_python_modules must return a dict."""
        mock_config_load.ECOSYSTEM_ROOT = tmp_path
        # Reload so the module picks up the patched ECOSYSTEM_ROOT
        scanner_module = importlib.reload(scanner_module)

        result = scanner_module.discover_python_modules()
        assert isinstance(result, dict)

    def test_discovers_files_in_ecosystem(self, scanner_module, tmp_path, mock_config_load):
        """Should discover .py files placed under ECOSYSTEM_ROOT."""
        mock_config_load.ECOSYSTEM_ROOT = tmp_path
        scanner_module = importlib.reload(scanner_module)

        (tmp_path / "alpha.py").write_text("# alpha", encoding="utf-8")
        (tmp_path / "beta.py").write_text("# beta", encoding="utf-8")

        result = scanner_module.discover_python_modules()
        assert "alpha" in result
        assert "beta" in result

    def test_empty_ecosystem(self, scanner_module, tmp_path, mock_config_load):
        """Empty ecosystem root should return empty dict."""
        mock_config_load.ECOSYSTEM_ROOT = tmp_path
        scanner_module = importlib.reload(scanner_module)

        result = scanner_module.discover_python_modules()
        assert result == {}

    def test_logs_scan_result(self, scanner_module, tmp_path, mock_config_load, mock_prax_infrastructure):
        """discover_python_modules should log the scan result count."""
        mock_config_load.ECOSYSTEM_ROOT = tmp_path
        scanner_module = importlib.reload(scanner_module)

        scanner_module.discover_python_modules()
        mocks = mock_prax_infrastructure
        mocks.json_handler.log_operation.assert_called()
