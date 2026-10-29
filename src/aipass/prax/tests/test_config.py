# =================== AIPass ====================
# Name: test_config.py
# Description: Tests for prax config handlers (load + ignore_patterns)
# Version: 1.5.0
# Created: 2026-03-29
# Modified: 2026-10-29
# =============================================

"""Tests for apps/handlers/config/load.py and apps/handlers/config/ignore_patterns.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(stderr_routing) — _warn_routing's warning when a log is routed away, covered by that row

import json
import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from aipass.prax.apps.handlers.config import ignore_patterns as ip_mod
from aipass.prax.apps.handlers.config import load as load_mod
from aipass.prax.apps.handlers.json import json_service


def _patch_load_world(monkeypatch, tmp_path):
    """Point load.py's module-level paths at tmp_path.

    PRAX_ROOT and ECOSYSTEM_ROOT go to tmp_path so directory creation lands there.
    The redirect variable is cleared below so real path resolution runs.
    """
    # The warn-once latches are per process; each test starts with them clear, as a
    # fresh process does.
    monkeypatch.setattr(load_mod, "_config_schema_warned", False)
    monkeypatch.setattr(load_mod, "_bad_level_warned", set())

    prax_root = tmp_path / "prax"
    prax_root.mkdir(exist_ok=True)
    ecosystem_root = prax_root.parent
    prax_json_dir = prax_root / "prax_json"
    prax_json_dir.mkdir(exist_ok=True)

    monkeypatch.setattr(load_mod, "PRAX_ROOT", prax_root)
    monkeypatch.setattr(load_mod, "ECOSYSTEM_ROOT", ecosystem_root)
    monkeypatch.setattr(load_mod, "PRAX_JSON_DIR", prax_json_dir)
    monkeypatch.setattr(load_mod, "PRAX_LOGGER_CONFIG_FILE", prax_json_dir / "prax_logger_config.json")
    monkeypatch.setattr(load_mod, "_system_logs_dir_cache", None)
    # Redirects cleared for real path resolution; the json service, reading the same variable,
    # is held under tmp_path or its records land in the live prax_json.
    json_root = tmp_path / "json_service"
    monkeypatch.setattr(
        json_service.JsonHandle, "json_dir", property(lambda handle: json_root / handle.branch_root.name)
    )
    monkeypatch.delenv("AIPASS_TEST_LOG_DIR", raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    # Suppress sys.modules-based pytest detection so tests can verify prod paths;
    # every consultation is recorded, so a test can show the product asked.
    consulted: list = []
    monkeypatch.setattr(load_mod, "_is_pytest_session", lambda: consulted.append(True) or False)
    # With detection off, the routing warning's direct logger resolves the live prax/logs by branch dir.
    monkeypatch.setattr(load_mod, "_warn_routing", lambda *a: None)
    return consulted


def _patch_ignore_world(monkeypatch, tmp_path):
    """Point ignore_patterns.py's config paths at tmp_path and record its json_handler."""
    monkeypatch.setattr(ip_mod, "json_handler", MagicMock())
    prax_root = tmp_path / "prax"
    prax_root.mkdir(exist_ok=True)
    prax_json_dir = prax_root / "prax_json"
    prax_json_dir.mkdir(exist_ok=True)

    monkeypatch.setattr(ip_mod, "PRAX_JSON_DIR", prax_json_dir)
    monkeypatch.setattr(ip_mod, "PRAX_LOGGER_CONFIG_FILE", prax_json_dir / "prax_logger_config.json")


class TestGetSystemLogsDir:
    """Tests for get_system_logs_dir()."""

    def test_returns_path(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        _patch_load_world(monkeypatch, tmp_path)
        monkeypatch.setattr(load_mod, "_find_repo_root", lambda: tmp_path)
        result = load_mod.get_system_logs_dir()
        assert isinstance(result, Path)
        # Which Path: the repo root's system_logs/, by that name.
        assert result.name == "system_logs"

    def test_returns_system_logs_subdir(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        consulted = _patch_load_world(monkeypatch, tmp_path)
        monkeypatch.setattr(load_mod, "_find_repo_root", lambda: tmp_path)
        result = load_mod.get_system_logs_dir()
        assert result == tmp_path / "system_logs"
        # The session detector was asked before the repo's own system_logs was chosen
        assert consulted == [True]

    def test_creates_directory(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        _patch_load_world(monkeypatch, tmp_path)
        monkeypatch.setattr(load_mod, "_find_repo_root", lambda: tmp_path)
        result = load_mod.get_system_logs_dir()
        assert result.exists()
        assert result.is_dir()

    def test_caches_result(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        _patch_load_world(monkeypatch, tmp_path)
        call_count = 0

        def counting_find():
            nonlocal call_count
            call_count += 1
            return tmp_path

        monkeypatch.setattr(load_mod, "_find_repo_root", counting_find)
        load_mod.get_system_logs_dir()
        load_mod.get_system_logs_dir()
        assert call_count == 1, "Should cache after first call"

    def test_an_installed_package_logs_under_the_user_home_never_the_filesystem_root(
        self, mock_prax_infrastructure, monkeypatch, tmp_path
    ):
        """A uv tool install resolved its log home to /system_logs, Errno 13."""
        _patch_load_world(monkeypatch, tmp_path)
        home = tmp_path / "home"
        # Path.home() reads HOME on POSIX and USERPROFILE on Windows.
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.setenv("USERPROFILE", str(home))
        monkeypatch.setattr(load_mod, "_find_repo_root", lambda: Path(tmp_path.anchor))

        result = load_mod.get_system_logs_dir()

        assert result == home / ".aipass" / "system_logs"
        assert result.is_dir()

    # The only route to an unmakeable log home is a permission bit: Windows has
    # none to set, and root writes through it.
    @pytest.mark.skipif(
        os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0),
        reason="needs a POSIX permission bit that binds the writer",
    )
    def test_a_log_home_that_cannot_be_made_raises_every_time_and_is_never_cached(
        self, mock_prax_infrastructure, monkeypatch, tmp_path
    ):
        """A cache set before the failed mkdir handed every later caller a directory never made."""
        _patch_load_world(monkeypatch, tmp_path)
        locked = tmp_path / "locked"
        locked.mkdir()
        monkeypatch.setattr(load_mod, "_find_repo_root", lambda: locked)
        locked.chmod(0o500)
        try:
            with pytest.raises(PermissionError):
                load_mod.get_system_logs_dir()
            with pytest.raises(PermissionError):
                load_mod.get_system_logs_dir()
        finally:
            locked.chmod(0o700)


class TestGetModuleLogsDir:
    """Tests for get_module_logs_dir(module_name)."""

    def test_returns_path(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        _patch_load_world(monkeypatch, tmp_path)
        monkeypatch.setattr(load_mod, "_find_repo_root", lambda: tmp_path)
        result = load_mod.get_module_logs_dir("flow")
        assert isinstance(result, Path)
        # Which Path: no flow/ exists under either root here, so the
        # unknown-module fallback answers system_logs/external/<module>.
        assert result == tmp_path / "system_logs" / "external" / "flow"

    def test_existing_module_under_ecosystem(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        _patch_load_world(monkeypatch, tmp_path)
        module_dir = tmp_path / "flow"
        module_dir.mkdir()
        result = load_mod.get_module_logs_dir("flow")
        assert result == module_dir / "logs"
        assert result.exists()

    def test_fallback_to_src_root(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        _patch_load_world(monkeypatch, tmp_path)
        # ECOSYSTEM_ROOT is tmp_path (parent of prax_root).
        # src_root is ECOSYSTEM_ROOT.parent. Create module there.
        src_root = tmp_path.parent
        alt_dir = src_root / "commons"
        alt_dir.mkdir(exist_ok=True)
        result = load_mod.get_module_logs_dir("commons")
        # Should use the src_root fallback since commons isn't under tmp_path
        assert result.name == "logs"
        assert result.exists()

    def test_a_branch_dir_is_its_own_logs_home_without_a_routing_warning(
        self, mock_prax_infrastructure, monkeypatch, tmp_path
    ):
        _patch_load_world(monkeypatch, tmp_path)
        monkeypatch.setattr(load_mod, "_find_repo_root", lambda: tmp_path)
        # The warning goes to a non-propagating direct logger, out of caplog's reach.
        warned = []
        monkeypatch.setattr(load_mod, "_warn_routing", lambda *a: warned.append(a))
        branch = tmp_path / "projects" / "hark" / "src" / "hark" / "hark"
        result = load_mod.get_module_logs_dir("hark", branch)
        assert result == branch / "logs"
        assert result.is_dir()
        assert not (tmp_path / "system_logs" / "external" / "hark").exists()
        assert warned == []

    def test_unknown_module_routes_to_system_logs_external(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        """Unknown modules must NOT create dirs in ECOSYSTEM_ROOT (log-leak regression)."""
        _patch_load_world(monkeypatch, tmp_path)
        monkeypatch.setattr(load_mod, "_find_repo_root", lambda: tmp_path)
        monkeypatch.delenv("AIPASS_CALLER_CWD", raising=False)
        result = load_mod.get_module_logs_dir("unknown_branch")
        # Must route to system_logs/external/, NOT create src/aipass/unknown_branch/
        assert result == tmp_path / "system_logs" / "external" / "unknown_branch"
        assert result.exists()
        assert result.is_dir()
        assert not (tmp_path / "unknown_branch").exists()

    def test_aipass_caller_cwd_routes_to_caller_project(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        """Regression: AIPASS_CALLER_CWD directs logs to caller project root, not ECOSYSTEM_ROOT."""
        _patch_load_world(monkeypatch, tmp_path)
        monkeypatch.setattr(load_mod, "_find_repo_root", lambda: tmp_path)
        # Set up a mock caller project with a .git marker
        caller_project = tmp_path / "caller_project"
        caller_project.mkdir()
        (caller_project / ".git").mkdir()
        caller_cwd = str(caller_project / "src" / "polyglot")
        monkeypatch.setenv("AIPASS_CALLER_CWD", caller_cwd)
        result = load_mod.get_module_logs_dir("polyglot")
        # Must resolve to caller project's logs/, not ECOSYSTEM_ROOT
        assert result == caller_project / "logs" / "polyglot"
        assert result.exists()
        assert result.is_dir()
        assert not (tmp_path / "polyglot").exists()


class TestPytestCurrentTestRouting:
    """PYTEST_CURRENT_TEST env var routes logs to temp dir, not production."""

    def test_system_logs_routed_to_temp(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        _patch_load_world(monkeypatch, tmp_path)
        monkeypatch.setenv("PYTEST_CURRENT_TEST", "tests/test_foo.py::test_bar (call)")
        result = load_mod.get_system_logs_dir()
        assert "aipass_test_logs" in str(result)
        assert result.name == "system"
        assert result.exists()
        assert not (tmp_path / "system_logs").exists()

    def test_module_logs_routed_to_temp(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        _patch_load_world(monkeypatch, tmp_path)
        monkeypatch.setenv("PYTEST_CURRENT_TEST", "tests/test_foo.py::test_bar (call)")
        (tmp_path / "flow").mkdir()
        result = load_mod.get_module_logs_dir("flow")
        assert "aipass_test_logs" in str(result)
        assert result.name == "flow"
        assert result.exists()
        assert not (tmp_path / "flow" / "logs").exists()

    def test_aipass_test_log_dir_takes_precedence(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        _patch_load_world(monkeypatch, tmp_path)
        override = tmp_path / "custom_test_logs"
        override.mkdir()
        monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(override))
        monkeypatch.setenv("PYTEST_CURRENT_TEST", "tests/test_foo.py::test_bar (call)")
        result = load_mod.get_system_logs_dir()
        assert result == override / "system"

    def test_no_pytest_env_uses_production_path(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        _patch_load_world(monkeypatch, tmp_path)
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.setattr(load_mod, "_find_repo_root", lambda: tmp_path)
        result = load_mod.get_system_logs_dir()
        assert result == tmp_path / "system_logs"


class TestLinesToBytes:
    """Tests for lines_to_bytes(num_lines, avg_line_length)."""

    def test_returns_int(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        _patch_load_world(monkeypatch, tmp_path)
        result = load_mod.lines_to_bytes(100)
        assert isinstance(result, int)
        # Which int: the line budget times the 200-byte default line.
        assert result == 20_000

    def test_default_avg_line_length(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        _patch_load_world(monkeypatch, tmp_path)
        assert load_mod.lines_to_bytes(100) == 100 * 200

    def test_custom_avg_line_length(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        _patch_load_world(monkeypatch, tmp_path)
        assert load_mod.lines_to_bytes(50, avg_line_length=100) == 5000

    def test_zero_lines(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        _patch_load_world(monkeypatch, tmp_path)
        assert load_mod.lines_to_bytes(0) == 0

    def test_one_line(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        _patch_load_world(monkeypatch, tmp_path)
        assert load_mod.lines_to_bytes(1) == 200

    def test_large_value(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        _patch_load_world(monkeypatch, tmp_path)
        assert load_mod.lines_to_bytes(1_000_000) == 1_000_000 * 200


class TestLoadLogConfig:
    """Tests for load_log_config()."""

    def test_returns_dict(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        _patch_load_world(monkeypatch, tmp_path)
        result = load_mod.load_log_config()
        assert isinstance(result, dict)
        # Which dict: exactly the four sections callers index, no more.
        assert set(result) == {"system_logs", "local_logs", "log_format", "date_format"}

    def test_default_keys_present(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        _patch_load_world(monkeypatch, tmp_path)
        result = load_mod.load_log_config()
        assert "system_logs" in result
        assert "local_logs" in result
        assert "log_format" in result
        assert "date_format" in result

    def test_defaults_when_no_config(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        _patch_load_world(monkeypatch, tmp_path)
        result = load_mod.load_log_config()
        assert result["system_logs"]["max_lines"] == 1000
        assert result["local_logs"]["max_lines"] == 250
        assert result["system_logs"]["log_level"] == "INFO"
        assert result["local_logs"]["log_level"] == "INFO"

    def test_loads_from_config_file(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        _patch_load_world(monkeypatch, tmp_path)
        config_file = load_mod.PRAX_LOGGER_CONFIG_FILE
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_data = {
            "config": {
                "system_logs": {"max_lines": 2000, "backup_count": 3, "log_level": "DEBUG"},
                "local_logs": {"max_lines": 500, "backup_count": 2, "log_level": "WARNING"},
                "log_format": "%(message)s",
                "date_format": "%H:%M:%S",
            }
        }
        config_file.write_text(json.dumps(config_data), encoding="utf-8")

        result = load_mod.load_log_config()
        assert result["system_logs"]["max_lines"] == 2000
        assert result["system_logs"]["log_level"] == "DEBUG"
        assert result["local_logs"]["max_lines"] == 500
        assert result["local_logs"]["log_level"] == "WARNING"
        assert result["log_format"] == "%(message)s"
        assert result["date_format"] == "%H:%M:%S"

    def test_falls_back_on_invalid_json(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        _patch_load_world(monkeypatch, tmp_path)
        config_file = load_mod.PRAX_LOGGER_CONFIG_FILE
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_file.write_text("not json at all!", encoding="utf-8")

        result = load_mod.load_log_config()
        assert result["system_logs"]["max_lines"] == 1000
        assert result["local_logs"]["max_lines"] == 250

    def test_partial_config_uses_defaults(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        _patch_load_world(monkeypatch, tmp_path)
        config_file = load_mod.PRAX_LOGGER_CONFIG_FILE
        config_file.parent.mkdir(parents=True, exist_ok=True)
        # Config with only system_logs — local_logs should fall back to default
        config_data = {"config": {"system_logs": {"max_lines": 3000, "backup_count": 5, "log_level": "ERROR"}}}
        config_file.write_text(json.dumps(config_data), encoding="utf-8")

        result = load_mod.load_log_config()
        assert result["system_logs"]["max_lines"] == 3000
        assert result["local_logs"] == load_mod.DEFAULT_LOCAL_LOGS

    def test_a_partial_section_keeps_the_default_keys(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        """A section naming one key still carries the rest: the handler builders index them."""
        _patch_load_world(monkeypatch, tmp_path)
        config_file = load_mod.PRAX_LOGGER_CONFIG_FILE
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_file.write_text(json.dumps({"config": {"system_logs": {"log_level": "DEBUG"}}}), encoding="utf-8")

        result = load_mod.load_log_config()

        assert result["system_logs"] == {**load_mod.DEFAULT_SYSTEM_LOGS, "log_level": "DEBUG"}

    @pytest.mark.parametrize("document", [[], "text", {"config": []}, {"config": {"local_logs": 7}}])
    def test_a_config_that_is_not_an_object_falls_back(self, mock_prax_infrastructure, monkeypatch, tmp_path, document):
        """JSON of the wrong shape reads as the defaults, never an AttributeError."""
        _patch_load_world(monkeypatch, tmp_path)
        config_file = load_mod.PRAX_LOGGER_CONFIG_FILE
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_file.write_text(json.dumps(document), encoding="utf-8")

        result = load_mod.load_log_config()

        assert result["system_logs"] == load_mod.DEFAULT_SYSTEM_LOGS
        assert result["local_logs"] == load_mod.DEFAULT_LOCAL_LOGS

    def test_empty_config_object(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        _patch_load_world(monkeypatch, tmp_path)
        config_file = load_mod.PRAX_LOGGER_CONFIG_FILE
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_file.write_text(json.dumps({}), encoding="utf-8")

        result = load_mod.load_log_config()
        assert result["system_logs"] == load_mod.DEFAULT_SYSTEM_LOGS
        assert result["local_logs"] == load_mod.DEFAULT_LOCAL_LOGS

    def test_log_format_defaults(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        _patch_load_world(monkeypatch, tmp_path)
        result = load_mod.load_log_config()
        assert "asctime" in result["log_format"]
        assert "%Y-%m-%d" in result["date_format"]

    def test_defaults_keep_three_backups(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        # Retained history scales with backup_count, so this number IS the
        # forensic window: 1 -> 3 triples the floor and doubles the ceiling.
        _patch_load_world(monkeypatch, tmp_path)
        assert load_mod.DEFAULT_SYSTEM_LOGS["backup_count"] == 3
        assert load_mod.DEFAULT_LOCAL_LOGS["backup_count"] == 3

    def test_warns_when_config_file_has_no_log_sections(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        _patch_load_world(monkeypatch, tmp_path)
        mock_logger = MagicMock()
        monkeypatch.setattr(load_mod, "logger", mock_logger)
        config_file = load_mod.PRAX_LOGGER_CONFIG_FILE
        config_file.parent.mkdir(parents=True, exist_ok=True)
        # The exact shape the shipped file had: retention keys one level too
        # high, where no reader ever looks.
        config_file.write_text(json.dumps({"config": {"backup_count": 5, "max_log_size_mb": 10}}), encoding="utf-8")

        result = load_mod.load_log_config()

        assert result["system_logs"] == load_mod.DEFAULT_SYSTEM_LOGS
        assert result["local_logs"] == load_mod.DEFAULT_LOCAL_LOGS
        mock_logger.warning.assert_called_once()
        assert mock_logger.warning.call_args[0][2] == "system_logs or local_logs"

    def test_warning_names_only_the_missing_section(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        _patch_load_world(monkeypatch, tmp_path)
        mock_logger = MagicMock()
        monkeypatch.setattr(load_mod, "logger", mock_logger)
        config_file = load_mod.PRAX_LOGGER_CONFIG_FILE
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_data = {"config": {"system_logs": {"max_lines": 3000, "backup_count": 5, "log_level": "ERROR"}}}
        config_file.write_text(json.dumps(config_data), encoding="utf-8")

        load_mod.load_log_config()

        mock_logger.warning.assert_called_once()
        assert mock_logger.warning.call_args[0][2] == "local_logs"

    def test_schema_warning_fires_once_per_process(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        # Every logger init fleet-wide calls this, and prax's own log sits in the
        # directory prax watches — an unguarded warning would feed itself.
        _patch_load_world(monkeypatch, tmp_path)
        mock_logger = MagicMock()
        monkeypatch.setattr(load_mod, "logger", mock_logger)
        config_file = load_mod.PRAX_LOGGER_CONFIG_FILE
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_file.write_text(json.dumps({"config": {}}), encoding="utf-8")

        for _ in range(5):
            load_mod.load_log_config()

        assert mock_logger.warning.call_count == 1

    def test_no_warning_when_both_sections_present(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        _patch_load_world(monkeypatch, tmp_path)
        mock_logger = MagicMock()
        monkeypatch.setattr(load_mod, "logger", mock_logger)
        config_file = load_mod.PRAX_LOGGER_CONFIG_FILE
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_data = {
            "config": {
                "system_logs": {"max_lines": 2000, "backup_count": 4, "log_level": "DEBUG"},
                "local_logs": {"max_lines": 500, "backup_count": 2, "log_level": "WARNING"},
            }
        }
        config_file.write_text(json.dumps(config_data), encoding="utf-8")

        result = load_mod.load_log_config()

        assert result["system_logs"]["backup_count"] == 4
        assert result["local_logs"]["backup_count"] == 2
        mock_logger.warning.assert_not_called()


class TestLoadIgnorePatternsFromConfig:
    """Tests for load_ignore_patterns_from_config()."""

    def test_returns_set(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        _patch_ignore_world(monkeypatch, tmp_path)
        result = ip_mod.load_ignore_patterns_from_config()
        assert type(result) is set
        # Which set: the defaults, and "archive.local" is one of them --
        # the branch-local archive directory prax must never walk into.
        assert "archive.local" in result

    def test_defaults_when_no_config(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        _patch_ignore_world(monkeypatch, tmp_path)
        result = ip_mod.load_ignore_patterns_from_config()
        assert ".git" in result
        assert "__pycache__" in result
        assert ".venv" in result
        assert "node_modules" in result

    def test_defaults_match_module_constant(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        _patch_ignore_world(monkeypatch, tmp_path)
        result = ip_mod.load_ignore_patterns_from_config()
        assert result == ip_mod.DEFAULT_IGNORE_FOLDERS

    def test_loads_custom_patterns(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        _patch_ignore_world(monkeypatch, tmp_path)
        config_file = ip_mod.PRAX_LOGGER_CONFIG_FILE
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_data = {"config": {"ignore_patterns": ["custom_dir", "another_dir", ".hidden"]}}
        config_file.write_text(json.dumps(config_data), encoding="utf-8")

        result = ip_mod.load_ignore_patterns_from_config()
        assert result == {"custom_dir", "another_dir", ".hidden"}

    def test_returns_set_from_list(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        """Config stores patterns as a list; result must be a set."""
        _patch_ignore_world(monkeypatch, tmp_path)
        config_file = ip_mod.PRAX_LOGGER_CONFIG_FILE
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_data = {"config": {"ignore_patterns": ["a", "b", "a"]}}
        config_file.write_text(json.dumps(config_data), encoding="utf-8")

        result = ip_mod.load_ignore_patterns_from_config()
        assert isinstance(result, set)
        assert result == {"a", "b"}

    def test_empty_patterns_falls_back(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        _patch_ignore_world(monkeypatch, tmp_path)
        config_file = ip_mod.PRAX_LOGGER_CONFIG_FILE
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_data = {"config": {"ignore_patterns": []}}
        config_file.write_text(json.dumps(config_data), encoding="utf-8")

        result = ip_mod.load_ignore_patterns_from_config()
        assert result == ip_mod.DEFAULT_IGNORE_FOLDERS

    def test_falls_back_on_invalid_json(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        _patch_ignore_world(monkeypatch, tmp_path)
        config_file = ip_mod.PRAX_LOGGER_CONFIG_FILE
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_file.write_text("{broken json", encoding="utf-8")

        result = ip_mod.load_ignore_patterns_from_config()
        assert result == ip_mod.DEFAULT_IGNORE_FOLDERS

    def test_falls_back_on_missing_config_key(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        _patch_ignore_world(monkeypatch, tmp_path)
        config_file = ip_mod.PRAX_LOGGER_CONFIG_FILE
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_file.write_text(json.dumps({"other_key": True}), encoding="utf-8")

        result = ip_mod.load_ignore_patterns_from_config()
        assert result == ip_mod.DEFAULT_IGNORE_FOLDERS


class TestResolveLogLevel:
    """Tests for resolve_log_level(): a config asking for DEBUG must get DEBUG, not INFO."""

    def test_defaults_to_info_when_nothing_configured(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        _patch_load_world(monkeypatch, tmp_path)
        monkeypatch.delenv(load_mod.LOG_LEVEL_ENV, raising=False)

        assert load_mod.resolve_log_level() == "INFO"
        assert load_mod.resolve_log_level(None) == "INFO"

    def test_honours_configured_level(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        _patch_load_world(monkeypatch, tmp_path)
        monkeypatch.delenv(load_mod.LOG_LEVEL_ENV, raising=False)

        assert load_mod.resolve_log_level("DEBUG") == "DEBUG"
        assert load_mod.resolve_log_level("WARNING") == "WARNING"

    def test_level_name_is_case_insensitive(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        _patch_load_world(monkeypatch, tmp_path)
        monkeypatch.delenv(load_mod.LOG_LEVEL_ENV, raising=False)

        assert load_mod.resolve_log_level("debug") == "DEBUG"
        assert load_mod.resolve_log_level("  Warning  ") == "WARNING"

    def test_env_var_overrides_config(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        _patch_load_world(monkeypatch, tmp_path)
        monkeypatch.setenv(load_mod.LOG_LEVEL_ENV, "DEBUG")

        assert load_mod.resolve_log_level("ERROR") == "DEBUG"

    def test_empty_env_var_is_ignored(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        """An exported-but-empty var must not shadow a real config value."""
        _patch_load_world(monkeypatch, tmp_path)
        monkeypatch.setenv(load_mod.LOG_LEVEL_ENV, "")

        assert load_mod.resolve_log_level("WARNING") == "WARNING"

    def test_numeric_level_passes_through(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        _patch_load_world(monkeypatch, tmp_path)
        monkeypatch.delenv(load_mod.LOG_LEVEL_ENV, raising=False)

        assert load_mod.resolve_log_level(10) == 10

    def test_invalid_value_falls_back_to_default(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        """A typo must not silently pick a level nobody asked for."""
        _patch_load_world(monkeypatch, tmp_path)
        monkeypatch.delenv(load_mod.LOG_LEVEL_ENV, raising=False)

        assert load_mod.resolve_log_level("VERBOSE") == "INFO"

    def test_invalid_value_warns(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        _patch_load_world(monkeypatch, tmp_path)
        monkeypatch.delenv(load_mod.LOG_LEVEL_ENV, raising=False)
        warnings = []
        monkeypatch.setattr(load_mod.logger, "warning", lambda msg, *a: warnings.append(msg % a))

        load_mod.resolve_log_level("LOUD")

        assert len(warnings) == 1
        assert "LOUD" in warnings[0]

    def test_invalid_value_warns_once_per_value(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        """Level resolution runs on every logger init fleet-wide — one typo, one warning."""
        _patch_load_world(monkeypatch, tmp_path)
        monkeypatch.delenv(load_mod.LOG_LEVEL_ENV, raising=False)
        warnings = []
        monkeypatch.setattr(load_mod.logger, "warning", lambda msg, *a: warnings.append(msg % a))

        for _ in range(5):
            load_mod.resolve_log_level("LOUD")

        assert len(warnings) == 1

    def test_bad_env_still_falls_through_to_config(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        _patch_load_world(monkeypatch, tmp_path)
        monkeypatch.setenv(load_mod.LOG_LEVEL_ENV, "NOPE")

        assert load_mod.resolve_log_level("DEBUG") == "DEBUG"


class TestLevelToInt:
    """Tests for level_to_int() — used to pick the permissive tier."""

    def test_converts_level_names(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        _patch_load_world(monkeypatch, tmp_path)

        assert load_mod.level_to_int("DEBUG") == 10
        assert load_mod.level_to_int("INFO") == 20
        assert load_mod.level_to_int("WARNING") == 30

    def test_passes_ints_through(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        _patch_load_world(monkeypatch, tmp_path)

        assert load_mod.level_to_int(10) == 10

    def test_unknown_name_reads_as_info(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        _patch_load_world(monkeypatch, tmp_path)

        assert load_mod.level_to_int("NONSENSE") == 20

    def test_debug_is_more_permissive_than_info(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        """min() over the two tiers must pick DEBUG — the property setup.py relies on."""
        _patch_load_world(monkeypatch, tmp_path)

        assert min(load_mod.level_to_int("DEBUG"), load_mod.level_to_int("INFO")) == 10
