"""Tests for the medic_state handler (apps/handlers/medic_state.py)."""

# =================== META ====================
# Name: test_medic_state.py
# Description: Unit tests for medic_state handler — real file I/O via tmp_path
# Version: 1.0.0
# Created: 2026-04-03
# Modified: 2026-04-03
# =============================================

import json
import sys
import pytest
from pathlib import Path
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _mock_infrastructure(monkeypatch):
    """Mock heavy infrastructure imports before medic_state module loads."""

    mock_logger = MagicMock()

    # -- prax logger --------------------------------------------------------
    prax_logger_mod = MagicMock()
    prax_logger_mod.get_direct_logger = MagicMock(return_value=mock_logger)
    prax_logger_mod.system_logger = mock_logger
    monkeypatch.setitem(sys.modules, "aipass.prax", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.prax.apps", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.prax.apps.modules", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.prax.apps.modules.logger", prax_logger_mod)

    # -- trigger json handler -----------------------------------------------
    mock_json_handler = MagicMock()
    mock_json_handler.log_operation = MagicMock(return_value=True)
    json_pkg = MagicMock()
    json_pkg.json_handler = mock_json_handler
    monkeypatch.setitem(sys.modules, "aipass.trigger.apps.handlers.json", json_pkg)
    json_mod = MagicMock()
    json_mod.log_operation = mock_json_handler.log_operation
    monkeypatch.setitem(sys.modules, "aipass.trigger.apps.handlers.json.json_handler", json_mod)

    # -- trigger config (TRIGGER_ROOT) --------------------------------------
    from aipass.trigger.apps.config import atomic_write_json

    config_mod = MagicMock()
    config_mod.TRIGGER_ROOT = Path("/tmp/fake_trigger_root")
    config_mod.atomic_write_json = atomic_write_json
    monkeypatch.setitem(sys.modules, "aipass.trigger.apps.config", config_mod)

    # -- Force re-import so mocks take effect -------------------------------
    monkeypatch.delitem(sys.modules, "aipass.trigger.apps.handlers.medic_state", raising=False)


@pytest.fixture
def state_mod(tmp_path, monkeypatch):
    """Import medic_state and point all file path constants to tmp_path."""
    import aipass.trigger.apps.handlers.medic_state as mod

    config_file = tmp_path / "trigger_json" / "trigger_config.json"
    suppressed_log = tmp_path / "logs" / "medic_suppressed.log"
    rate_limited_log = tmp_path / "logs" / "rate_limited.log"

    monkeypatch.setattr(mod, "TRIGGER_CONFIG_FILE", config_file)
    monkeypatch.setattr(mod, "MEDIC_SUPPRESSED_LOG", suppressed_log)
    monkeypatch.setattr(mod, "RATE_LIMITED_LOG", rate_limited_log)

    return mod


def _get_json_handler():
    """Return the mocked json_handler."""
    return sys.modules["aipass.trigger.apps.handlers.json"].json_handler


# ---------------------------------------------------------------------------
# Tests -- read_config
# ---------------------------------------------------------------------------


class TestReadConfig:
    """Tests for read_config."""

    def test_read_config_file_exists(self, state_mod):
        """read_config returns parsed dict when file exists."""
        config_file = state_mod.TRIGGER_CONFIG_FILE
        config_file.parent.mkdir(parents=True, exist_ok=True)
        data = {"config": {"medic_enabled": True}, "version": "1.0"}
        config_file.write_text(json.dumps(data), encoding="utf-8")

        result = state_mod.read_config()

        assert result == data
        assert result["config"]["medic_enabled"] is True

    def test_read_config_file_missing_returns_empty(self, state_mod):
        """read_config returns empty dict when file does not exist."""
        result = state_mod.read_config()

        assert result == {}

    def test_read_config_corrupt_file_returns_empty(self, state_mod):
        """read_config returns empty dict when file contains invalid JSON."""
        config_file = state_mod.TRIGGER_CONFIG_FILE
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_file.write_text("not valid json {{{", encoding="utf-8")

        result = state_mod.read_config()

        assert result == {}


# ---------------------------------------------------------------------------
# Tests -- write_config
# ---------------------------------------------------------------------------


class TestWriteConfig:
    """Tests for write_config."""

    def test_write_config_creates_file(self, state_mod):
        """write_config creates the config file with valid JSON."""
        data = {"config": {"medic_enabled": False}}

        result = state_mod.write_config(data)

        assert result is True
        config_file = state_mod.TRIGGER_CONFIG_FILE
        assert config_file.exists()
        written = json.loads(config_file.read_text(encoding="utf-8"))
        assert written == data

    def test_write_config_creates_parent_dirs(self, state_mod):
        """write_config creates parent directories when they do not exist."""
        config_file = state_mod.TRIGGER_CONFIG_FILE
        assert not config_file.parent.exists()

        result = state_mod.write_config({"test": True})

        assert result is True
        assert config_file.parent.exists()


# ---------------------------------------------------------------------------
# Tests -- is_enabled
# ---------------------------------------------------------------------------


class TestIsEnabled:
    """Tests for is_enabled."""

    def test_is_enabled_default_true(self, state_mod):
        """is_enabled returns True when config file is missing (default)."""
        result = state_mod.is_enabled()

        assert result is True

    def test_is_enabled_true_when_set(self, state_mod):
        """is_enabled returns True when medic_enabled is True."""
        config_file = state_mod.TRIGGER_CONFIG_FILE
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_file.write_text(json.dumps({"config": {"medic_enabled": True}}), encoding="utf-8")

        result = state_mod.is_enabled()

        assert result is True

    def test_is_enabled_false_when_disabled(self, state_mod):
        """is_enabled returns False when medic_enabled is False."""
        config_file = state_mod.TRIGGER_CONFIG_FILE
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_file.write_text(json.dumps({"config": {"medic_enabled": False}}), encoding="utf-8")

        result = state_mod.is_enabled()

        assert result is False

    def test_is_enabled_true_when_config_empty(self, state_mod):
        """is_enabled returns True when config has no medic_enabled key."""
        config_file = state_mod.TRIGGER_CONFIG_FILE
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_file.write_text(json.dumps({"config": {}}), encoding="utf-8")

        result = state_mod.is_enabled()

        assert result is True


# ---------------------------------------------------------------------------
# Tests -- set_enabled
# ---------------------------------------------------------------------------


class TestSetEnabled:
    """Tests for set_enabled."""

    def test_set_enabled_true(self, state_mod):
        """set_enabled(True) persists medic_enabled=True to disk."""
        result = state_mod.set_enabled(True)

        assert result is True
        config_file = state_mod.TRIGGER_CONFIG_FILE
        data = json.loads(config_file.read_text(encoding="utf-8"))
        assert data["config"]["medic_enabled"] is True

    def test_set_enabled_false(self, state_mod):
        """set_enabled(False) persists medic_enabled=False to disk."""
        result = state_mod.set_enabled(False)

        assert result is True
        config_file = state_mod.TRIGGER_CONFIG_FILE
        data = json.loads(config_file.read_text(encoding="utf-8"))
        assert data["config"]["medic_enabled"] is False

    def test_set_enabled_toggle_round_trip(self, state_mod):
        """set_enabled toggles correctly across multiple calls."""
        state_mod.set_enabled(False)
        assert state_mod.is_enabled() is False

        state_mod.set_enabled(True)
        assert state_mod.is_enabled() is True

    def test_set_enabled_logs_operation(self, state_mod):
        """set_enabled logs the state_persisted operation via json_handler."""
        state_mod.set_enabled(True)

        jh = _get_json_handler()
        jh.log_operation.assert_called_with("state_persisted", {"key": "medic_enabled", "value": True})

    def test_set_enabled_preserves_existing_config(self, state_mod):
        """set_enabled preserves other config keys when updating."""
        config_file = state_mod.TRIGGER_CONFIG_FILE
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_file.write_text(
            json.dumps({"config": {"medic_enabled": True, "other_key": "keep_me"}}),
            encoding="utf-8",
        )

        state_mod.set_enabled(False)

        data = json.loads(config_file.read_text(encoding="utf-8"))
        assert data["config"]["medic_enabled"] is False
        assert data["config"]["other_key"] == "keep_me"


# ---------------------------------------------------------------------------
# Tests -- _normalize_branch_name
# ---------------------------------------------------------------------------


class TestNormalizeBranchName:
    """Tests for _normalize_branch_name."""

    def test_strips_at_prefix(self, state_mod):
        """_normalize_branch_name strips the @ prefix."""
        assert state_mod._normalize_branch_name("@speakeasy") == "speakeasy"

    def test_extracts_from_path(self, state_mod):
        """_normalize_branch_name extracts the last path component."""
        assert state_mod._normalize_branch_name("src/aipass/flow") == "flow"

    def test_lowercases(self, state_mod):
        """_normalize_branch_name lowercases the result."""
        assert state_mod._normalize_branch_name("@DRONE") == "drone"

    def test_combined_at_and_path(self, state_mod):
        """_normalize_branch_name handles @ with path (strips @, extracts name)."""
        result = state_mod._normalize_branch_name("@src/aipass/Api")
        assert result == "api"

    def test_plain_name(self, state_mod):
        """_normalize_branch_name passes through a plain lowercase name."""
        assert state_mod._normalize_branch_name("trigger") == "trigger"


# ---------------------------------------------------------------------------
# Tests -- get_muted_branches
# ---------------------------------------------------------------------------


class TestGetMutedBranches:
    """Tests for get_muted_branches."""

    def test_empty_list_when_no_config(self, state_mod):
        """get_muted_branches returns empty list when config is missing."""
        result = state_mod.get_muted_branches()

        assert result == []

    def test_returns_populated_list(self, state_mod):
        """get_muted_branches returns the stored muted branch names."""
        config_file = state_mod.TRIGGER_CONFIG_FILE
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_file.write_text(
            json.dumps({"config": {"muted_branches": ["speakeasy", "api"]}}),
            encoding="utf-8",
        )

        result = state_mod.get_muted_branches()

        assert result == ["speakeasy", "api"]

    def test_normalizes_branch_names(self, state_mod):
        """get_muted_branches normalizes names (strips @, lowercases)."""
        config_file = state_mod.TRIGGER_CONFIG_FILE
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_file.write_text(
            json.dumps({"config": {"muted_branches": ["@SPEAKEASY", "@Api"]}}),
            encoding="utf-8",
        )

        result = state_mod.get_muted_branches()

        assert result == ["speakeasy", "api"]


# ---------------------------------------------------------------------------
# Tests -- mute_branch
# ---------------------------------------------------------------------------


class TestMuteBranch:
    """Tests for mute_branch."""

    def test_adds_new_branch(self, state_mod):
        """mute_branch adds a new branch to the muted list."""
        result = state_mod.mute_branch("speakeasy")

        assert result is True
        muted = state_mod.get_muted_branches()
        assert "speakeasy" in muted

    def test_does_not_duplicate(self, state_mod):
        """mute_branch does not add a branch that is already muted."""
        state_mod.mute_branch("speakeasy")
        state_mod.mute_branch("speakeasy")

        muted = state_mod.get_muted_branches()
        assert muted.count("speakeasy") == 1

    def test_handles_at_prefix(self, state_mod):
        """mute_branch correctly handles names with @ prefix."""
        state_mod.mute_branch("@flow")

        muted = state_mod.get_muted_branches()
        assert "flow" in muted

    def test_multiple_branches(self, state_mod):
        """mute_branch can accumulate multiple branches."""
        state_mod.mute_branch("speakeasy")
        state_mod.mute_branch("api")
        state_mod.mute_branch("drone")

        muted = state_mod.get_muted_branches()
        assert set(muted) == {"speakeasy", "api", "drone"}


# ---------------------------------------------------------------------------
# Tests -- unmute_branch
# ---------------------------------------------------------------------------


class TestUnmuteBranch:
    """Tests for unmute_branch."""

    def test_removes_muted_branch(self, state_mod):
        """unmute_branch removes a previously muted branch."""
        state_mod.mute_branch("speakeasy")
        state_mod.mute_branch("api")

        result = state_mod.unmute_branch("speakeasy")

        assert result is True
        muted = state_mod.get_muted_branches()
        assert "speakeasy" not in muted
        assert "api" in muted

    def test_handles_nonexistent_branch(self, state_mod):
        """unmute_branch returns True even when branch is not in muted list."""
        result = state_mod.unmute_branch("nonexistent")

        assert result is True

    def test_handles_at_prefix(self, state_mod):
        """unmute_branch correctly handles names with @ prefix."""
        state_mod.mute_branch("flow")

        result = state_mod.unmute_branch("@flow")

        assert result is True
        muted = state_mod.get_muted_branches()
        assert "flow" not in muted


# ---------------------------------------------------------------------------
# Tests -- get_suppression_stats
# ---------------------------------------------------------------------------


class TestGetSuppressionStats:
    """Tests for get_suppression_stats."""

    def test_no_log_file(self, state_mod):
        """get_suppression_stats returns zeros when log file does not exist."""
        result = state_mod.get_suppression_stats()

        assert result["suppressed_count"] == 0
        assert result["last_suppressed"] == "never"

    def test_empty_log_file(self, state_mod):
        """get_suppression_stats returns zeros when log file is empty."""
        log_file = state_mod.MEDIC_SUPPRESSED_LOG
        log_file.parent.mkdir(parents=True, exist_ok=True)
        log_file.write_text("", encoding="utf-8")

        result = state_mod.get_suppression_stats()

        assert result["suppressed_count"] == 0
        assert result["last_suppressed"] == "never"

    def test_populated_log(self, state_mod):
        """get_suppression_stats parses log lines and returns correct stats."""
        log_file = state_mod.MEDIC_SUPPRESSED_LOG
        log_file.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            "2026-04-01 10:00:00 | ImportError | FLOW",
            "2026-04-02 11:00:00 | TimeoutError | API",
            "2026-04-03 12:00:00 | ValueError | DRONE",
        ]
        log_file.write_text("\n".join(lines), encoding="utf-8")

        result = state_mod.get_suppression_stats()

        assert result["suppressed_count"] == 3
        assert result["last_suppressed"] == "2026-04-03 12:00:00"

    def test_log_line_without_pipe_separator(self, state_mod):
        """get_suppression_stats returns 'unknown' when last line has no pipe."""
        log_file = state_mod.MEDIC_SUPPRESSED_LOG
        log_file.parent.mkdir(parents=True, exist_ok=True)
        log_file.write_text("malformed line without pipe", encoding="utf-8")

        result = state_mod.get_suppression_stats()

        assert result["suppressed_count"] == 1
        assert result["last_suppressed"] == "unknown"


# ---------------------------------------------------------------------------
# Tests -- get_rate_limit_stats
# ---------------------------------------------------------------------------


class TestGetRateLimitStats:
    """Tests for get_rate_limit_stats."""

    def test_no_log_file(self, state_mod):
        """get_rate_limit_stats returns zeros when log file does not exist."""
        result = state_mod.get_rate_limit_stats()

        assert result["rate_limited_count"] == 0
        assert result["last_rate_limited"] == "never"

    def test_empty_log_file(self, state_mod):
        """get_rate_limit_stats returns zeros when log file is empty."""
        log_file = state_mod.RATE_LIMITED_LOG
        log_file.parent.mkdir(parents=True, exist_ok=True)
        log_file.write_text("", encoding="utf-8")

        result = state_mod.get_rate_limit_stats()

        assert result["rate_limited_count"] == 0
        assert result["last_rate_limited"] == "never"

    def test_populated_log(self, state_mod):
        """get_rate_limit_stats parses log lines and returns correct stats."""
        log_file = state_mod.RATE_LIMITED_LOG
        log_file.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            "2026-04-01 08:00:00 | ImportError | fp123",
            "2026-04-02 09:00:00 | TimeoutError | fp456",
        ]
        log_file.write_text("\n".join(lines), encoding="utf-8")

        result = state_mod.get_rate_limit_stats()

        assert result["rate_limited_count"] == 2
        assert result["last_rate_limited"] == "2026-04-02 09:00:00"

    def test_log_line_without_pipe_separator(self, state_mod):
        """get_rate_limit_stats returns 'unknown' when last line has no pipe."""
        log_file = state_mod.RATE_LIMITED_LOG
        log_file.parent.mkdir(parents=True, exist_ok=True)
        log_file.write_text("malformed line", encoding="utf-8")

        result = state_mod.get_rate_limit_stats()

        assert result["rate_limited_count"] == 1
        assert result["last_rate_limited"] == "unknown"
