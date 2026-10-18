# =================== AIPass ====================
# Name: test_discovery.py
# Description: Unit tests for discovery handlers
# Version: 1.2.0
# Created: 2026-03-29
# Modified: 2026-10-17
# =============================================

"""Tests for apps/handlers/discovery/filtering.py, scanner.py, scan.py and apps/modules/discover.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(through_the_command) — start_file_watcher, stop_file_watcher, covered by tests/test_watcher.py

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from aipass.prax.apps.handlers.discovery import filtering, scan, scanner
from aipass.prax.apps.modules import discover


@pytest.fixture()
def mock_ignore_patterns(monkeypatch):
    """The ignore list, doubled where filtering binds its loader."""
    loader = MagicMock(return_value={".git", "__pycache__", ".venv", "node_modules"})
    monkeypatch.setattr(filtering, "load_ignore_patterns_from_config", loader)
    return loader


@pytest.fixture()
def mock_config_load(monkeypatch, tmp_path):
    """The roots scanner bound from config.load, pointed under tmp_path where scanner holds them."""
    monkeypatch.setattr(scanner, "ECOSYSTEM_ROOT", tmp_path)
    monkeypatch.setattr(scanner, "get_system_logs_dir", lambda: tmp_path / "system_logs")
    monkeypatch.setattr(scanner, "get_module_logs_dir", lambda branch=None: tmp_path / "logs")


@pytest.fixture()
def filtering_module(monkeypatch, mock_ignore_patterns):
    """filtering, with its loader and its json service doubled."""
    monkeypatch.setattr(filtering, "json_handler", MagicMock())
    return filtering


@pytest.fixture()
def scanner_module(monkeypatch, filtering_module, mock_config_load):
    """scanner, walking tmp_path through the real filtering, its json service doubled."""
    monkeypatch.setattr(scanner, "json_handler", MagicMock())
    return scanner


class TestShouldIgnorePath:
    """Tests for filtering.should_ignore_path."""

    def test_returns_bool(self, filtering_module, tmp_path):
        """should_ignore_path answers True or False, and the answer tracks the path."""
        result = filtering_module.should_ignore_path(tmp_path / "some" / "normal" / "file.py")
        assert isinstance(result, bool)
        assert result is False
        assert filtering_module.should_ignore_path(tmp_path / "some" / ".venv" / "file.py") is True
        # Matching is per path COMPONENT, not substring.
        assert filtering_module.should_ignore_path(tmp_path / "some" / "node_modules_backup" / "file.py") is False

    def test_ignores_git_directory(self, filtering_module, tmp_path):
        """.git paths should be ignored."""
        assert filtering_module.should_ignore_path(tmp_path / "repo" / ".git" / "objects" / "ab") is True

    def test_ignores_pycache(self, filtering_module, tmp_path):
        """__pycache__ paths should be ignored."""
        assert filtering_module.should_ignore_path(tmp_path / "project" / "__pycache__" / "mod.pyc") is True

    def test_ignores_venv(self, filtering_module, tmp_path):
        """.venv paths should be ignored."""
        assert (
            filtering_module.should_ignore_path(tmp_path / "project" / ".venv" / "lib" / "python3" / "site.py") is True
        )

    def test_ignores_node_modules(self, filtering_module, tmp_path):
        """node_modules paths should be ignored."""
        assert filtering_module.should_ignore_path(tmp_path / "project" / "node_modules" / "pkg" / "index.js") is True

    def test_normal_path_not_ignored(self, filtering_module, tmp_path):
        """Regular project paths should not be ignored."""
        assert filtering_module.should_ignore_path(tmp_path / "project" / "src" / "module.py") is False

    def test_root_path_not_ignored(self, filtering_module):
        """A bare root path should not be ignored."""
        assert filtering_module.should_ignore_path(Path("/")) is False

    def test_relative_path(self, filtering_module):
        """Relative paths should also be checked correctly."""
        assert filtering_module.should_ignore_path(Path("src/app/main.py")) is False
        assert filtering_module.should_ignore_path(Path("src/__pycache__/main.pyc")) is True

    def test_deeply_nested_ignored_dir(self, filtering_module, tmp_path):
        """Ignored dir deep in the tree should still be caught."""
        deep = tmp_path / "a" / "b" / "c" / "d" / ".git" / "refs" / "heads" / "main"
        assert filtering_module.should_ignore_path(deep) is True

    def test_similar_name_not_ignored(self, filtering_module, tmp_path):
        """Directories with names similar to ignored patterns should pass."""
        assert filtering_module.should_ignore_path(tmp_path / "project" / "git_utils" / "helper.py") is False

    def test_logs_filtered_path(self, filtering_module, tmp_path):
        """When a path is ignored, json_handler.log_operation should be called."""
        ignored = tmp_path / "repo" / ".git" / "config"
        filtering_module.should_ignore_path(ignored)
        filtering_module.json_handler.log_operation.assert_called_once_with(
            "discovery_filtered", {"ignored_path": str(ignored)}
        )


class TestScanDirectorySafely:
    """Tests for scanner.scan_directory_safely."""

    def test_returns_dict_populated_with_py_files(self, scanner_module, tmp_path):
        """Scanning a directory with .py files should populate the dict."""
        py_file = tmp_path / "example.py"
        py_file.write_text("# example", encoding="utf-8")

        modules: dict = {}
        scanner_module.scan_directory_safely(tmp_path, modules)
        assert list(modules) == ["example"]
        assert (modules["example"]["file_path"], modules["example"]["enabled"]) == (str(py_file), True)

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


class TestDiscoverPythonModules:
    """Tests for scanner.discover_python_modules."""

    def test_returns_dict(self, scanner_module, tmp_path):
        """discover_python_modules returns the discovered modules keyed by stem."""
        (tmp_path / "pkg").mkdir()
        (tmp_path / "pkg" / "gamma.py").write_text("# gamma\n", encoding="utf-8")

        result = scanner_module.discover_python_modules()
        assert isinstance(result, dict)
        assert set(result) == {"gamma"}
        assert Path(result["gamma"]["relative_path"]) == Path("pkg/gamma.py")
        assert result["gamma"]["enabled"] is True

    def test_discovers_files_in_ecosystem(self, scanner_module, tmp_path):
        """Should discover .py files placed under ECOSYSTEM_ROOT."""
        (tmp_path / "alpha.py").write_text("# alpha", encoding="utf-8")
        (tmp_path / "beta.py").write_text("# beta", encoding="utf-8")

        result = scanner_module.discover_python_modules()
        assert "alpha" in result
        assert "beta" in result

    def test_empty_ecosystem(self, scanner_module):
        """Empty ecosystem root should return empty dict."""
        result = scanner_module.discover_python_modules()
        assert result == {}

    def test_logs_scan_result(self, scanner_module):
        """discover_python_modules should log the scan result count."""
        scanner_module.discover_python_modules()
        scanner_module.json_handler.log_operation.assert_any_call("modules_scanned", {"modules_found": 0})


@pytest.fixture()
def saved_registry() -> dict:
    """What run_scan handed save_module_registry, recorded by scan_module's double."""
    return {}


@pytest.fixture()
def scan_module(monkeypatch, saved_registry):
    """Import scan.py with its three collaborators replaced by doubles."""

    def fake_save(modules, scan_stats=None):
        saved_registry["modules"] = modules
        saved_registry["scan_stats"] = scan_stats
        return True

    monkeypatch.setattr(scan, "save_module_registry", fake_save)
    monkeypatch.setattr(scan, "json_handler", MagicMock())
    monkeypatch.setattr(scan, "logger", MagicMock())
    return scan


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
        assert result["previous_unreadable"] is False

    def test_an_unreadable_registry_is_rebuilt_from_the_walk_and_flagged(self, scan_module, monkeypatch):
        """An unreadable registry (load answers None) is healed from the walk and flagged."""
        _walk(scan_module, monkeypatch, before=None, found={"fresh": {}})

        result = scan_module.run_scan()

        assert result["previous_unreadable"] is True
        assert result["added"] == ["fresh"]
        assert result["saved"] is not False

    def test_saved_registry_is_the_walk_not_a_merge(self, scan_module, saved_registry, monkeypatch):
        """A module whose file is gone leaves the record; the scan never merges."""
        _walk(scan_module, monkeypatch, before={"gone": {"file_path": "/dead.py"}}, found={"live": {}})

        scan_module.run_scan()

        assert "gone" not in saved_registry["modules"]
        assert sorted(saved_registry["modules"]) == ["live"]

    def test_discovered_time_is_carried_over_for_a_known_module(self, scan_module, saved_registry, monkeypatch):
        """discovered_time means FIRST seen: a module on record keeps its original stamp."""
        _walk(
            scan_module,
            monkeypatch,
            before={"old": {"discovered_time": "2026-07-28T02:39:24+00:00"}},
            found={"old": {"discovered_time": "2026-09-12T00:00:00+00:00"}},
        )

        scan_module.run_scan()

        assert saved_registry["modules"]["old"]["discovered_time"] == "2026-07-28T02:39:24+00:00"

    def test_a_new_module_keeps_the_stamp_the_walk_gave_it(self, scan_module, saved_registry, monkeypatch):
        """Nothing to carry over means the walk's own value stands."""
        _walk(scan_module, monkeypatch, before={}, found={"fresh": {"discovered_time": "2026-09-12T00:00:00+00:00"}})

        scan_module.run_scan()

        assert saved_registry["modules"]["fresh"]["discovered_time"] == "2026-09-12T00:00:00+00:00"

    def test_second_scan_of_an_unchanged_tree_reports_nothing(self, scan_module, monkeypatch):
        """Idempotence is what makes this safe to schedule daily."""
        tree = {"a": {}, "b": {}}
        _walk(scan_module, monkeypatch, before=tree, found=dict(tree))

        result = scan_module.run_scan()

        assert result["added"] == []
        assert result["removed"] == []
        assert result["unchanged"] == 2

    def test_scan_stats_go_to_the_registry_for_the_status_line(self, scan_module, saved_registry, monkeypatch):
        """`drone @prax status` reads these; they are counts, never name lists."""
        _walk(scan_module, monkeypatch, before={"gone": {}}, found={"fresh": {}})

        scan_module.run_scan()
        stats = saved_registry["scan_stats"]

        assert stats["added"] == 1
        assert stats["removed"] == 1
        assert stats["total"] == 1
        assert stats["timestamp"]

    def test_a_failed_write_is_reported_not_swallowed(self, scan_module, monkeypatch):
        """The counts describe the walk; `saved` is the only word on the file."""
        _walk(scan_module, monkeypatch, before={}, found={"a": {}})
        handed: list = []
        monkeypatch.setattr(
            scan_module,
            "save_module_registry",
            lambda modules, scan_stats=None: handed.append(sorted(modules)) or False,
        )

        assert scan_module.run_scan()["saved"] is False
        assert handed == [["a"]]


@pytest.fixture()
def discover_module(monkeypatch):
    """discover.py with the json service and the logger doubled; the console is real, read with capsys."""
    monkeypatch.setattr(discover, "json_handler", MagicMock())
    monkeypatch.setattr(discover, "logger", MagicMock())
    return discover


class TestDiscoverCommandGate:
    """A module that does not check the command name answers for every module (and rewrites the registry)."""

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

    def test_run_performs_the_scan(self, discover_module, monkeypatch, capsys):
        """The real console prints the scan's answer; read what reached the terminal."""
        monkeypatch.setattr(
            discover_module,
            "run_scan",
            lambda: {
                "added": ["fresh"],
                "removed": [],
                "unchanged": 3,
                "total": 4,
                "saved": True,
                "previous_unreadable": False,
            },
        )

        assert discover_module.handle_command("discover", ["run"]) is True
        captured = capsys.readouterr()
        assert "  added: fresh" in captured.out.splitlines()
        assert "Registry updated — 4 modules" in captured.out + captured.err
        assert "could not be read" not in captured.out + captured.err

    def test_a_rebuilt_unreadable_registry_is_said_beside_the_counts(self, discover_module, monkeypatch, capsys):
        """After an unreadable registry every module reads as added; the run says why."""
        monkeypatch.setattr(
            discover_module,
            "run_scan",
            lambda: {
                "added": ["a", "b"],
                "removed": [],
                "unchanged": 0,
                "total": 2,
                "saved": True,
                "previous_unreadable": True,
            },
        )

        assert discover_module.handle_command("discover", ["run"]) is True
        captured = capsys.readouterr()
        assert "The previous registry could not be read; it was rebuilt from disk." in captured.out + captured.err

    def test_an_unknown_subcommand_is_refused(self, discover_module, monkeypatch):
        """`discover scna` must not be indistinguishable from `discover`."""
        refused = MagicMock(side_effect=RuntimeError("refused"))
        monkeypatch.setattr(discover_module, "refuse", refused)
        monkeypatch.setattr(discover_module, "run_scan", MagicMock())

        with pytest.raises(RuntimeError):
            discover_module.handle_command("discover", ["scna"])
        refused.assert_called_once()


def _tree(root: Path, *relative: str) -> None:
    """Write one .py file at each relative path under root."""
    for rel in relative:
        path = root.joinpath(*rel.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# module\n", encoding="utf-8")


class TestSandboxesAreNotDiscovered:
    """discover_python_modules never walks into a dropbox or an .archive below its root."""

    def test_a_dropbox_and_an_archive_are_not_discovered_and_the_live_module_is(
        self, scanner_module, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(scanner_module, "ECOSYSTEM_ROOT", tmp_path)
        _tree(tmp_path, "branch/apps/live.py", "branch/dropbox/handed.py", "branch/.archive/old.py")

        result = scanner_module.discover_python_modules()

        assert set(result) == {"live"}

    def test_an_archived_copy_does_not_take_the_live_modules_entry(self, scanner_module, tmp_path, monkeypatch):
        """Keyed by stem, an archived scanner.py walked after the live one used to overwrite it."""
        monkeypatch.setattr(scanner_module, "ECOSYSTEM_ROOT", tmp_path)
        _tree(tmp_path, "branch/apps/scanner.py", "branch/.archive/snapshots/apps/scanner.py")

        result = scanner_module.discover_python_modules()

        assert Path(result["scanner"]["file_path"]) == tmp_path / "branch" / "apps" / "scanner.py"

    def test_a_root_inside_a_directory_named_dropbox_still_finds_its_own_module(
        self, scanner_module, tmp_path, monkeypatch
    ):
        """The names are compared below the root of the walk, never on the whole path."""
        root = tmp_path / "dropbox" / "eco"
        monkeypatch.setattr(scanner_module, "ECOSYSTEM_ROOT", root)
        _tree(root, "branch/apps/live.py")

        result = scanner_module.discover_python_modules()

        assert set(result) == {"live"}
