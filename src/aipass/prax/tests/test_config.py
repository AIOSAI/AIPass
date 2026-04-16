# =================== AIPass ====================
# Name: test_config.py
# Description: Tests for prax config handlers (load + ignore_patterns)
# Version: 1.0.0
# Created: 2026-03-29
# Modified: 2026-03-29
# =============================================

"""Tests for prax config handlers — covers load.py functions
(get_system_logs_dir, get_module_logs_dir, lines_to_bytes,
get_debug_prints_enabled, load_log_config) and ignore_patterns.py
(load_ignore_patterns_from_config)."""

import json
import sys
from pathlib import Path


# =============================================
# HELPERS
# =============================================


def _fresh_import_load(monkeypatch, tmp_path):
    """Import load module with a fresh state and patched paths.

    Clears cached module, patches PRAX_ROOT and ECOSYSTEM_ROOT to tmp_path
    so directory creation goes to tmp_path, then reloads.
    """
    # Evict cached modules
    for key in list(sys.modules.keys()):
        if "aipass.prax.apps.handlers.config" in key:
            sys.modules.pop(key, None)

    import aipass.prax.apps.handlers.config.load as load_mod

    # Patch module-level paths to use tmp_path
    prax_root = tmp_path / "prax"
    prax_root.mkdir(exist_ok=True)
    ecosystem_root = prax_root.parent
    prax_json_dir = prax_root / "prax_json"
    prax_json_dir.mkdir(exist_ok=True)

    monkeypatch.setattr(load_mod, "PRAX_ROOT", prax_root)
    monkeypatch.setattr(load_mod, "ECOSYSTEM_ROOT", ecosystem_root)
    monkeypatch.setattr(load_mod, "PRAX_JSON_DIR", prax_json_dir)
    monkeypatch.setattr(load_mod, "PRAX_LOGGER_CONFIG_FILE", prax_json_dir / "prax_logger_config.json")
    # Reset the lazy cache so get_system_logs_dir() re-resolves
    monkeypatch.setattr(load_mod, "_system_logs_dir_cache", None)
    # Clear test log redirect so tests exercise real path resolution
    monkeypatch.delenv("AIPASS_TEST_LOG_DIR", raising=False)

    return load_mod


def _fresh_import_ignore(monkeypatch, tmp_path):
    """Import ignore_patterns module with a fresh state and patched paths."""
    for key in list(sys.modules.keys()):
        if "aipass.prax.apps.handlers.config" in key:
            sys.modules.pop(key, None)

    import aipass.prax.apps.handlers.config.ignore_patterns as ip_mod

    prax_root = tmp_path / "prax"
    prax_root.mkdir(exist_ok=True)
    prax_json_dir = prax_root / "prax_json"
    prax_json_dir.mkdir(exist_ok=True)

    monkeypatch.setattr(ip_mod, "PRAX_JSON_DIR", prax_json_dir)
    monkeypatch.setattr(ip_mod, "PRAX_LOGGER_CONFIG_FILE", prax_json_dir / "prax_logger_config.json")

    return ip_mod


# =============================================
# TESTS: get_system_logs_dir
# =============================================


class TestGetSystemLogsDir:
    """Tests for get_system_logs_dir()."""

    def test_returns_path(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        load_mod = _fresh_import_load(monkeypatch, tmp_path)
        # Patch _find_repo_root to return tmp_path
        monkeypatch.setattr(load_mod, "_find_repo_root", lambda: tmp_path)
        result = load_mod.get_system_logs_dir()
        assert isinstance(result, Path)

    def test_returns_system_logs_subdir(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        load_mod = _fresh_import_load(monkeypatch, tmp_path)
        monkeypatch.setattr(load_mod, "_find_repo_root", lambda: tmp_path)
        result = load_mod.get_system_logs_dir()
        assert result == tmp_path / "system_logs"

    def test_creates_directory(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        load_mod = _fresh_import_load(monkeypatch, tmp_path)
        monkeypatch.setattr(load_mod, "_find_repo_root", lambda: tmp_path)
        result = load_mod.get_system_logs_dir()
        assert result.exists()
        assert result.is_dir()

    def test_caches_result(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        load_mod = _fresh_import_load(monkeypatch, tmp_path)
        call_count = 0

        def counting_find():
            nonlocal call_count
            call_count += 1
            return tmp_path

        monkeypatch.setattr(load_mod, "_find_repo_root", counting_find)
        load_mod.get_system_logs_dir()
        load_mod.get_system_logs_dir()
        assert call_count == 1, "Should cache after first call"


# =============================================
# TESTS: get_module_logs_dir
# =============================================


class TestGetModuleLogsDir:
    """Tests for get_module_logs_dir(module_name)."""

    def test_returns_path(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        load_mod = _fresh_import_load(monkeypatch, tmp_path)
        result = load_mod.get_module_logs_dir("flow")
        assert isinstance(result, Path)

    def test_existing_module_under_ecosystem(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        load_mod = _fresh_import_load(monkeypatch, tmp_path)
        # Create the module directory so the first branch is taken
        module_dir = tmp_path / "flow"
        module_dir.mkdir()
        result = load_mod.get_module_logs_dir("flow")
        assert result == module_dir / "logs"
        assert result.exists()

    def test_fallback_to_src_root(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        load_mod = _fresh_import_load(monkeypatch, tmp_path)
        # ECOSYSTEM_ROOT is tmp_path (parent of prax_root).
        # src_root is ECOSYSTEM_ROOT.parent. Create module there.
        src_root = tmp_path.parent
        alt_dir = src_root / "commons"
        alt_dir.mkdir(exist_ok=True)
        result = load_mod.get_module_logs_dir("commons")
        # Should use the src_root fallback since commons isn't under tmp_path
        assert result.name == "logs"
        assert result.exists()

    def test_unknown_module_routes_to_system_logs_external(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        """Unknown modules must NOT create dirs in ECOSYSTEM_ROOT (log-leak regression)."""
        load_mod = _fresh_import_load(monkeypatch, tmp_path)
        monkeypatch.setattr(load_mod, "_find_repo_root", lambda: tmp_path)
        monkeypatch.delenv("AIPASS_CALLER_CWD", raising=False)
        result = load_mod.get_module_logs_dir("unknown_branch")
        # Must route to system_logs/external/, NOT create src/aipass/unknown_branch/
        assert result == tmp_path / "system_logs" / "external" / "unknown_branch"
        assert result.exists()
        assert result.is_dir()
        # Verify ECOSYSTEM_ROOT is not polluted
        assert not (tmp_path / "unknown_branch").exists()

    def test_aipass_caller_cwd_routes_to_caller_project(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        """Regression: AIPASS_CALLER_CWD directs logs to caller project root, not ECOSYSTEM_ROOT."""
        load_mod = _fresh_import_load(monkeypatch, tmp_path)
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
        # ECOSYSTEM_ROOT must not be polluted
        assert not (tmp_path / "polyglot").exists()


# =============================================
# TESTS: lines_to_bytes
# =============================================


class TestLinesToBytes:
    """Tests for lines_to_bytes(num_lines, avg_line_length)."""

    def test_returns_int(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        load_mod = _fresh_import_load(monkeypatch, tmp_path)
        result = load_mod.lines_to_bytes(100)
        assert isinstance(result, int)

    def test_default_avg_line_length(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        load_mod = _fresh_import_load(monkeypatch, tmp_path)
        assert load_mod.lines_to_bytes(100) == 100 * 200

    def test_custom_avg_line_length(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        load_mod = _fresh_import_load(monkeypatch, tmp_path)
        assert load_mod.lines_to_bytes(50, avg_line_length=100) == 5000

    def test_zero_lines(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        load_mod = _fresh_import_load(monkeypatch, tmp_path)
        assert load_mod.lines_to_bytes(0) == 0

    def test_one_line(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        load_mod = _fresh_import_load(monkeypatch, tmp_path)
        assert load_mod.lines_to_bytes(1) == 200

    def test_large_value(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        load_mod = _fresh_import_load(monkeypatch, tmp_path)
        assert load_mod.lines_to_bytes(1_000_000) == 1_000_000 * 200


# =============================================
# TESTS: get_debug_prints_enabled
# =============================================


class TestGetDebugPrintsEnabled:
    """Tests for get_debug_prints_enabled()."""

    def test_returns_bool(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        load_mod = _fresh_import_load(monkeypatch, tmp_path)
        result = load_mod.get_debug_prints_enabled()
        assert isinstance(result, bool)

    def test_false_when_config_missing(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        load_mod = _fresh_import_load(monkeypatch, tmp_path)
        # No config file exists
        assert load_mod.get_debug_prints_enabled() is False

    def test_true_when_enabled_in_config(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        load_mod = _fresh_import_load(monkeypatch, tmp_path)
        config_file = load_mod.PRAX_LOGGER_CONFIG_FILE
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_file.write_text(json.dumps({"config": {"debug_prints_enabled": True}}), encoding="utf-8")
        assert load_mod.get_debug_prints_enabled() is True

    def test_false_when_disabled_in_config(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        load_mod = _fresh_import_load(monkeypatch, tmp_path)
        config_file = load_mod.PRAX_LOGGER_CONFIG_FILE
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_file.write_text(json.dumps({"config": {"debug_prints_enabled": False}}), encoding="utf-8")
        assert load_mod.get_debug_prints_enabled() is False

    def test_false_when_key_missing(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        load_mod = _fresh_import_load(monkeypatch, tmp_path)
        config_file = load_mod.PRAX_LOGGER_CONFIG_FILE
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_file.write_text(json.dumps({"config": {}}), encoding="utf-8")
        assert load_mod.get_debug_prints_enabled() is False

    def test_false_on_invalid_json(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        load_mod = _fresh_import_load(monkeypatch, tmp_path)
        config_file = load_mod.PRAX_LOGGER_CONFIG_FILE
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_file.write_text("{{not valid json", encoding="utf-8")
        assert load_mod.get_debug_prints_enabled() is False

    def test_false_on_empty_config_object(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        load_mod = _fresh_import_load(monkeypatch, tmp_path)
        config_file = load_mod.PRAX_LOGGER_CONFIG_FILE
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_file.write_text(json.dumps({}), encoding="utf-8")
        assert load_mod.get_debug_prints_enabled() is False


# =============================================
# TESTS: load_log_config
# =============================================


class TestLoadLogConfig:
    """Tests for load_log_config()."""

    def test_returns_dict(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        load_mod = _fresh_import_load(monkeypatch, tmp_path)
        result = load_mod.load_log_config()
        assert isinstance(result, dict)

    def test_default_keys_present(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        load_mod = _fresh_import_load(monkeypatch, tmp_path)
        result = load_mod.load_log_config()
        assert "system_logs" in result
        assert "local_logs" in result
        assert "log_format" in result
        assert "date_format" in result

    def test_defaults_when_no_config(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        load_mod = _fresh_import_load(monkeypatch, tmp_path)
        result = load_mod.load_log_config()
        assert result["system_logs"]["max_lines"] == 1000
        assert result["local_logs"]["max_lines"] == 250
        assert result["system_logs"]["log_level"] == "INFO"
        assert result["local_logs"]["log_level"] == "INFO"

    def test_loads_from_config_file(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        load_mod = _fresh_import_load(monkeypatch, tmp_path)
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
        load_mod = _fresh_import_load(monkeypatch, tmp_path)
        config_file = load_mod.PRAX_LOGGER_CONFIG_FILE
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_file.write_text("not json at all!", encoding="utf-8")

        result = load_mod.load_log_config()
        # Should fall back to defaults
        assert result["system_logs"]["max_lines"] == 1000
        assert result["local_logs"]["max_lines"] == 250

    def test_partial_config_uses_defaults(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        load_mod = _fresh_import_load(monkeypatch, tmp_path)
        config_file = load_mod.PRAX_LOGGER_CONFIG_FILE
        config_file.parent.mkdir(parents=True, exist_ok=True)
        # Config with only system_logs — local_logs should fall back to default
        config_data = {"config": {"system_logs": {"max_lines": 3000, "backup_count": 5, "log_level": "ERROR"}}}
        config_file.write_text(json.dumps(config_data), encoding="utf-8")

        result = load_mod.load_log_config()
        assert result["system_logs"]["max_lines"] == 3000
        assert result["local_logs"] == load_mod.DEFAULT_LOCAL_LOGS

    def test_empty_config_object(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        load_mod = _fresh_import_load(monkeypatch, tmp_path)
        config_file = load_mod.PRAX_LOGGER_CONFIG_FILE
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_file.write_text(json.dumps({}), encoding="utf-8")

        result = load_mod.load_log_config()
        assert result["system_logs"] == load_mod.DEFAULT_SYSTEM_LOGS
        assert result["local_logs"] == load_mod.DEFAULT_LOCAL_LOGS

    def test_log_format_defaults(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        load_mod = _fresh_import_load(monkeypatch, tmp_path)
        result = load_mod.load_log_config()
        assert "asctime" in result["log_format"]
        assert "%Y-%m-%d" in result["date_format"]


# =============================================
# TESTS: load_ignore_patterns_from_config
# =============================================


class TestLoadIgnorePatternsFromConfig:
    """Tests for load_ignore_patterns_from_config()."""

    def test_returns_set(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        ip_mod = _fresh_import_ignore(monkeypatch, tmp_path)
        result = ip_mod.load_ignore_patterns_from_config()
        assert isinstance(result, set)

    def test_defaults_when_no_config(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        ip_mod = _fresh_import_ignore(monkeypatch, tmp_path)
        result = ip_mod.load_ignore_patterns_from_config()
        assert ".git" in result
        assert "__pycache__" in result
        assert ".venv" in result
        assert "node_modules" in result

    def test_defaults_match_module_constant(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        ip_mod = _fresh_import_ignore(monkeypatch, tmp_path)
        result = ip_mod.load_ignore_patterns_from_config()
        assert result == ip_mod.DEFAULT_IGNORE_FOLDERS

    def test_loads_custom_patterns(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        ip_mod = _fresh_import_ignore(monkeypatch, tmp_path)
        config_file = ip_mod.PRAX_LOGGER_CONFIG_FILE
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_data = {"config": {"ignore_patterns": ["custom_dir", "another_dir", ".hidden"]}}
        config_file.write_text(json.dumps(config_data), encoding="utf-8")

        result = ip_mod.load_ignore_patterns_from_config()
        assert result == {"custom_dir", "another_dir", ".hidden"}

    def test_returns_set_from_list(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        """Config stores patterns as a list; result must be a set."""
        ip_mod = _fresh_import_ignore(monkeypatch, tmp_path)
        config_file = ip_mod.PRAX_LOGGER_CONFIG_FILE
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_data = {"config": {"ignore_patterns": ["a", "b", "a"]}}
        config_file.write_text(json.dumps(config_data), encoding="utf-8")

        result = ip_mod.load_ignore_patterns_from_config()
        assert isinstance(result, set)
        assert result == {"a", "b"}

    def test_empty_patterns_falls_back(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        ip_mod = _fresh_import_ignore(monkeypatch, tmp_path)
        config_file = ip_mod.PRAX_LOGGER_CONFIG_FILE
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_data = {"config": {"ignore_patterns": []}}
        config_file.write_text(json.dumps(config_data), encoding="utf-8")

        result = ip_mod.load_ignore_patterns_from_config()
        assert result == ip_mod.DEFAULT_IGNORE_FOLDERS

    def test_falls_back_on_invalid_json(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        ip_mod = _fresh_import_ignore(monkeypatch, tmp_path)
        config_file = ip_mod.PRAX_LOGGER_CONFIG_FILE
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_file.write_text("{broken json", encoding="utf-8")

        result = ip_mod.load_ignore_patterns_from_config()
        assert result == ip_mod.DEFAULT_IGNORE_FOLDERS

    def test_falls_back_on_missing_config_key(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        ip_mod = _fresh_import_ignore(monkeypatch, tmp_path)
        config_file = ip_mod.PRAX_LOGGER_CONFIG_FILE
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_file.write_text(json.dumps({"other_key": True}), encoding="utf-8")

        result = ip_mod.load_ignore_patterns_from_config()
        assert result == ip_mod.DEFAULT_IGNORE_FOLDERS
