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
from unittest.mock import MagicMock

import pytest


# =============================================
# FIXTURES
# =============================================


@pytest.fixture()
def mock_ignore_patterns(monkeypatch):
    """Mock the ignore_patterns config module in sys.modules."""
    mock_mod = MagicMock()
    mock_mod.load_ignore_patterns_from_config = MagicMock(return_value={".git", "__pycache__", ".venv", "node_modules"})
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
    mock_mod.get_system_logs_dir = MagicMock(return_value=tmp_path / "system_logs")
    mock_mod.get_module_logs_dir = MagicMock(return_value=tmp_path / "logs")
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
        """should_ignore_path answers True or False, and the answer tracks the path."""
        result = filtering_module.should_ignore_path(Path("/some/normal/file.py"))
        assert isinstance(result, bool)
        # Which bool: False for a path holding no ignored component, True once
        # one of the configured patterns appears in it.
        assert result is False
        assert filtering_module.should_ignore_path(Path("/some/.venv/file.py")) is True
        # Matching is per path COMPONENT, not substring: a directory that merely
        # starts with an ignored name is still walked.
        assert filtering_module.should_ignore_path(Path("/some/node_modules_backup/file.py")) is False

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
            "file_path",
            "relative_path",
            "system_log_file",
            "log_file",
            "discovered_time",
            "size",
            "modified_time",
            "enabled",
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
        """discover_python_modules returns the discovered modules keyed by stem."""
        mock_config_load.ECOSYSTEM_ROOT = tmp_path
        # Reload so the module picks up the patched ECOSYSTEM_ROOT
        scanner_module = importlib.reload(scanner_module)

        (tmp_path / "pkg").mkdir()
        (tmp_path / "pkg" / "gamma.py").write_text("# gamma\n", encoding="utf-8")

        result = scanner_module.discover_python_modules()
        assert isinstance(result, dict)
        # Which dict: keyed by the file stem, valued by the metadata record --
        # the path is stored relative to ECOSYSTEM_ROOT, and it is enabled.
        assert set(result) == {"gamma"}
        assert Path(result["gamma"]["relative_path"]) == Path("pkg/gamma.py")
        assert result["gamma"]["enabled"] is True

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


# =============================================
# scan.run_scan — the registry as a truthful snapshot (DPLAN-0339 step 4)
# =============================================


@pytest.fixture()
def scan_module(monkeypatch):
    """Import scan.py with its three collaborators replaced by doubles.

    run_scan is orchestration: walk, diff, save. Doubling the walk and the
    registry is what lets a test state a tree and read back the arithmetic.
    """
    import aipass.prax.apps.handlers.discovery.scan as scan_mod

    scan_mod = importlib.reload(scan_mod)
    saved = {}

    def fake_save(modules, scan_stats=None):
        saved["modules"] = modules
        saved["scan_stats"] = scan_stats
        return True

    monkeypatch.setattr(scan_mod, "save_module_registry", fake_save)
    monkeypatch.setattr(scan_mod, "json_handler", MagicMock())
    scan_mod._saved = saved
    return scan_mod


def _walk(scan_mod, monkeypatch, before, found):
    monkeypatch.setattr(scan_mod, "load_module_registry", lambda: before)
    monkeypatch.setattr(scan_mod, "discover_python_modules", lambda: found)


class TestRunScan:
    """A scan replaces the registry; it does not merge into it."""

    def test_counts_added_removed_and_unchanged(self, scan_module, monkeypatch):
        """The three counts are the set arithmetic of before against found."""
        _walk(
            scan_module,
            monkeypatch,
            before={"kept": {}, "gone": {}},
            found={"kept": {}, "fresh": {}},
        )

        result = scan_module.run_scan()

        assert result["added"] == ["fresh"]
        assert result["removed"] == ["gone"]
        assert result["unchanged"] == 1
        assert result["total"] == 2

    def test_saved_registry_is_the_walk_not_a_merge(self, scan_module, monkeypatch):
        """The defect this cures: a module whose file is gone stayed on record
        forever, because the incremental path only ever added."""
        _walk(scan_module, monkeypatch, before={"gone": {"file_path": "/dead.py"}}, found={"live": {}})

        scan_module.run_scan()

        assert "gone" not in scan_module._saved["modules"]
        assert sorted(scan_module._saved["modules"]) == ["live"]

    def test_discovered_time_is_carried_over_for_a_known_module(self, scan_module, monkeypatch):
        """discovered_time means FIRST seen. A scan is not a rediscovery, so a
        module already on record keeps its original stamp."""
        _walk(
            scan_module,
            monkeypatch,
            before={"old": {"discovered_time": "2026-07-28T02:39:24+00:00"}},
            found={"old": {"discovered_time": "2026-09-12T00:00:00+00:00"}},
        )

        scan_module.run_scan()

        assert scan_module._saved["modules"]["old"]["discovered_time"] == "2026-07-28T02:39:24+00:00"

    def test_a_new_module_keeps_the_stamp_the_walk_gave_it(self, scan_module, monkeypatch):
        """Nothing to carry over means the walk's own value stands."""
        _walk(scan_module, monkeypatch, before={}, found={"fresh": {"discovered_time": "2026-09-12T00:00:00+00:00"}})

        scan_module.run_scan()

        assert scan_module._saved["modules"]["fresh"]["discovered_time"] == "2026-09-12T00:00:00+00:00"

    def test_second_scan_of_an_unchanged_tree_reports_nothing(self, scan_module, monkeypatch):
        """Idempotence is what makes this safe to schedule daily."""
        tree = {"a": {}, "b": {}}
        _walk(scan_module, monkeypatch, before=tree, found=dict(tree))

        result = scan_module.run_scan()

        assert result["added"] == []
        assert result["removed"] == []
        assert result["unchanged"] == 2

    def test_scan_stats_go_to_the_registry_for_the_status_line(self, scan_module, monkeypatch):
        """`drone @prax status` reads these; they are counts, never name lists."""
        _walk(scan_module, monkeypatch, before={"gone": {}}, found={"fresh": {}})

        scan_module.run_scan()
        stats = scan_module._saved["scan_stats"]

        assert stats["added"] == 1
        assert stats["removed"] == 1
        assert stats["total"] == 1
        assert stats["timestamp"]

    def test_a_failed_write_is_reported_not_swallowed(self, scan_module, monkeypatch):
        """The counts describe the walk; `saved` is the only word on the file."""
        _walk(scan_module, monkeypatch, before={}, found={"a": {}})
        monkeypatch.setattr(scan_module, "save_module_registry", lambda modules, scan_stats=None: False)

        assert scan_module.run_scan()["saved"] is False


# =============================================
# The discover module's command gate (DPLAN-0339 step 4)
# =============================================


@pytest.fixture()
def discover_module(monkeypatch):
    """Import discover.py with the scan and the console doubled."""
    import aipass.prax.apps.modules.discover as discover_mod

    discover_mod = importlib.reload(discover_mod)
    monkeypatch.setattr(discover_mod, "console", MagicMock())
    monkeypatch.setattr(discover_mod, "success", MagicMock())
    monkeypatch.setattr(discover_mod, "error", MagicMock())
    monkeypatch.setattr(discover_mod, "json_handler", MagicMock())
    monkeypatch.setattr(discover_mod, "logger", MagicMock())
    return discover_mod


class TestDiscoverCommandGate:
    """A module that does not check the command name answers for every module.

    Found live during the build: without the guard, `discover` sorted first in
    the entry point's glob and ran a full registry rewrite when someone typed
    `drone @prax status`.
    """

    def test_another_modules_command_is_declined(self, discover_module, monkeypatch):
        scanned = MagicMock()
        monkeypatch.setattr(discover_module, "run_scan", scanned)

        assert discover_module.handle_command("status", []) is False
        scanned.assert_not_called()

    def test_no_args_shows_introspection_and_scans_nothing(self, discover_module, monkeypatch):
        """A bare word must not rewrite the registry."""
        scanned = MagicMock()
        monkeypatch.setattr(discover_module, "run_scan", scanned)

        assert discover_module.handle_command("discover", []) is True
        scanned.assert_not_called()

    def test_run_performs_the_scan(self, discover_module, monkeypatch):
        monkeypatch.setattr(
            discover_module,
            "run_scan",
            lambda: {"added": [], "removed": [], "unchanged": 3, "total": 3, "saved": True},
        )

        assert discover_module.handle_command("discover", ["run"]) is True

    def test_an_unknown_subcommand_is_refused(self, discover_module, monkeypatch):
        """`discover scna` must not be indistinguishable from `discover`."""
        refused = MagicMock(side_effect=RuntimeError("refused"))
        monkeypatch.setattr(discover_module, "refuse", refused)
        monkeypatch.setattr(discover_module, "run_scan", MagicMock())

        with pytest.raises(RuntimeError):
            discover_module.handle_command("discover", ["scna"])
        refused.assert_called_once()
