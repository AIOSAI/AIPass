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
    from aipass.trigger.apps.config import atomic_write_json, json_file_lock, migrate_json_file

    config_mod = MagicMock()
    config_mod.TRIGGER_ROOT = Path("/tmp/fake_trigger_root")
    config_mod.TRIGGER_JSON_DIR = Path("/tmp/fake_trigger_root/trigger_json")
    config_mod.atomic_write_json = atomic_write_json
    config_mod.migrate_json_file = migrate_json_file
    # Real lock, not a mock: the write paths hold this lock while read_config
    # runs the migration underneath, and only the real flock proves that
    # nesting does not deadlock the process against itself.
    config_mod.json_file_lock = json_file_lock
    monkeypatch.setitem(sys.modules, "aipass.trigger.apps.config", config_mod)

    # -- Force re-import so mocks take effect -------------------------------
    monkeypatch.delitem(sys.modules, "aipass.trigger.apps.handlers.medic_state", raising=False)


@pytest.fixture
def state_mod(tmp_path, monkeypatch):
    """Import medic_state and point all file path constants to tmp_path."""
    import aipass.trigger.apps.handlers.medic_state as mod

    config_file = tmp_path / "trigger_json" / "medic_state.json"
    suppressed_log = tmp_path / "logs" / "medic_suppressed.jsonl"
    rate_limited_log = tmp_path / "logs" / "rate_limited.jsonl"

    monkeypatch.setattr(mod, "MEDIC_STATE_FILE", config_file)
    monkeypatch.setattr(mod, "LEGACY_MEDIC_STATE_FILE", tmp_path / "trigger_json" / "trigger_config.json")
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
        config_file = state_mod.MEDIC_STATE_FILE
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
        config_file = state_mod.MEDIC_STATE_FILE
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
        config_file = state_mod.MEDIC_STATE_FILE
        assert config_file.exists()
        written = json.loads(config_file.read_text(encoding="utf-8"))
        assert written == data

    def test_write_config_creates_parent_dirs(self, state_mod):
        """write_config creates parent directories when they do not exist."""
        config_file = state_mod.MEDIC_STATE_FILE
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
        config_file = state_mod.MEDIC_STATE_FILE
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_file.write_text(json.dumps({"config": {"medic_enabled": True}}), encoding="utf-8")

        result = state_mod.is_enabled()

        assert result is True

    def test_is_enabled_false_when_disabled(self, state_mod):
        """is_enabled returns False when medic_enabled is False."""
        config_file = state_mod.MEDIC_STATE_FILE
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_file.write_text(json.dumps({"config": {"medic_enabled": False}}), encoding="utf-8")

        result = state_mod.is_enabled()

        assert result is False

    def test_is_enabled_true_when_config_empty(self, state_mod):
        """is_enabled returns True when config has no medic_enabled key."""
        config_file = state_mod.MEDIC_STATE_FILE
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
        config_file = state_mod.MEDIC_STATE_FILE
        data = json.loads(config_file.read_text(encoding="utf-8"))
        assert data["config"]["medic_enabled"] is True

    def test_set_enabled_false(self, state_mod):
        """set_enabled(False) persists medic_enabled=False to disk."""
        result = state_mod.set_enabled(False)

        assert result is True
        config_file = state_mod.MEDIC_STATE_FILE
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
        config_file = state_mod.MEDIC_STATE_FILE
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
        config_file = state_mod.MEDIC_STATE_FILE
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_file.write_text(
            json.dumps({"config": {"muted_branches": ["speakeasy", "api"]}}),
            encoding="utf-8",
        )

        result = state_mod.get_muted_branches()

        assert result == ["speakeasy", "api"]

    def test_normalizes_branch_names(self, state_mod):
        """get_muted_branches normalizes names (strips @, lowercases)."""
        config_file = state_mod.MEDIC_STATE_FILE
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
        """get_suppression_stats parses JSONL lines and returns correct stats."""
        log_file = state_mod.MEDIC_SUPPRESSED_LOG
        log_file.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            '{"ts": "2026-04-01T10:00:00", "reason": "count<2", "branch": "FLOW"}',
            '{"ts": "2026-04-02T11:00:00", "reason": "count<2", "branch": "API"}',
            '{"ts": "2026-04-03T12:00:00", "reason": "count<2", "branch": "DRONE"}',
        ]
        log_file.write_text("\n".join(lines), encoding="utf-8")

        result = state_mod.get_suppression_stats()

        assert result["suppressed_count"] == 3
        assert result["last_suppressed"] == "2026-04-03T12:00:00"

    def test_log_line_without_ts_field(self, state_mod):
        """get_suppression_stats returns 'unknown' when last entry has no ts."""
        log_file = state_mod.MEDIC_SUPPRESSED_LOG
        log_file.parent.mkdir(parents=True, exist_ok=True)
        log_file.write_text('{"reason": "no timestamp"}', encoding="utf-8")

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
        """get_rate_limit_stats parses JSONL lines and returns correct stats."""
        log_file = state_mod.RATE_LIMITED_LOG
        log_file.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            '{"ts": "2026-04-01T08:00:00", "reason": "backoff", "detail": "fp123"}',
            '{"ts": "2026-04-02T09:00:00", "reason": "backoff", "detail": "fp456"}',
        ]
        log_file.write_text("\n".join(lines), encoding="utf-8")

        result = state_mod.get_rate_limit_stats()

        assert result["rate_limited_count"] == 2
        assert result["last_rate_limited"] == "2026-04-02T09:00:00"

    def test_log_line_without_ts_field(self, state_mod):
        """get_rate_limit_stats returns 'unknown' when last entry has no ts."""
        log_file = state_mod.RATE_LIMITED_LOG
        log_file.parent.mkdir(parents=True, exist_ok=True)
        log_file.write_text('{"reason": "no timestamp"}', encoding="utf-8")

        result = state_mod.get_rate_limit_stats()

        assert result["rate_limited_count"] == 1
        assert result["last_rate_limited"] == "unknown"


# ---------------------------------------------------------------------------
# Tests -- parse_duration
# ---------------------------------------------------------------------------


class TestParseDuration:
    """Tests for parse_duration."""

    def test_parse_duration_hours(self, state_mod):
        """parse_duration converts '24h' to 86400.0 seconds."""
        result = state_mod.parse_duration("24h")

        assert result == 86400.0

    def test_parse_duration_days(self, state_mod):
        """parse_duration converts '7d' to 604800.0 seconds."""
        result = state_mod.parse_duration("7d")

        assert result == 604800.0

    def test_parse_duration_invalid(self, state_mod):
        """parse_duration returns None for invalid input."""
        result = state_mod.parse_duration("abc")

        assert result is None


# ---------------------------------------------------------------------------
# Tests -- mute_branch TTL
# ---------------------------------------------------------------------------


class TestMuteBranchTTL:
    """Tests for mute_branch with TTL support."""

    def test_mute_branch_default_permanent(self, state_mod):
        """mute_branch with no duration stores dict with expires_at null."""
        state_mod.mute_branch("api")

        config_file = state_mod.MEDIC_STATE_FILE
        data = json.loads(config_file.read_text(encoding="utf-8"))
        muted = data["config"]["muted_branches"]
        assert len(muted) == 1
        assert muted[0] == {"name": "api", "expires_at": None}

    def test_mute_branch_with_ttl(self, state_mod):
        """mute_branch with duration stores expires_at roughly 1h from now."""
        from datetime import datetime, timedelta

        before = datetime.now()
        state_mod.mute_branch("api", duration_seconds=3600)
        after = datetime.now()

        config_file = state_mod.MEDIC_STATE_FILE
        data = json.loads(config_file.read_text(encoding="utf-8"))
        muted = data["config"]["muted_branches"]
        assert len(muted) == 1
        assert muted[0]["name"] == "api"
        expires = datetime.fromisoformat(muted[0]["expires_at"])
        assert expires >= before + timedelta(seconds=3600)
        assert expires <= after + timedelta(seconds=3600)

    def test_mute_forever_null_expires(self, state_mod):
        """mute_branch with duration_seconds=None stores expires_at as null."""
        state_mod.mute_branch("api", duration_seconds=None)

        config_file = state_mod.MEDIC_STATE_FILE
        data = json.loads(config_file.read_text(encoding="utf-8"))
        muted = data["config"]["muted_branches"]
        assert len(muted) == 1
        assert muted[0]["expires_at"] is None


# ---------------------------------------------------------------------------
# Tests -- get_muted_branches TTL filtering
# ---------------------------------------------------------------------------


class TestGetMutedBranchesTTL:
    """Tests for get_muted_branches with TTL-aware filtering."""

    def test_get_muted_branches_filters_expired(self, state_mod):
        """get_muted_branches excludes dict entries whose expires_at is in the past."""
        from datetime import datetime, timedelta

        expired_ts = (datetime.now() - timedelta(hours=1)).isoformat()
        config_file = state_mod.MEDIC_STATE_FILE
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_file.write_text(
            json.dumps(
                {
                    "config": {
                        "muted_branches": [
                            {"name": "api", "expires_at": expired_ts},
                        ]
                    }
                }
            ),
            encoding="utf-8",
        )

        result = state_mod.get_muted_branches()

        assert result == []

    def test_get_muted_branches_keeps_active(self, state_mod):
        """get_muted_branches includes dict entries whose expires_at is in the future."""
        from datetime import datetime, timedelta

        future_ts = (datetime.now() + timedelta(hours=1)).isoformat()
        config_file = state_mod.MEDIC_STATE_FILE
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_file.write_text(
            json.dumps(
                {
                    "config": {
                        "muted_branches": [
                            {"name": "api", "expires_at": future_ts},
                        ]
                    }
                }
            ),
            encoding="utf-8",
        )

        result = state_mod.get_muted_branches()

        assert result == ["api"]

    def test_get_muted_branches_plain_string_backcompat(self, state_mod):
        """get_muted_branches returns plain string entries as permanent mutes."""
        config_file = state_mod.MEDIC_STATE_FILE
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_file.write_text(
            json.dumps({"config": {"muted_branches": ["speakeasy"]}}),
            encoding="utf-8",
        )

        result = state_mod.get_muted_branches()

        assert result == ["speakeasy"]


# ---------------------------------------------------------------------------
# Tests -- get_muted_branches_detail
# ---------------------------------------------------------------------------


class TestGetMutedBranchesDetail:
    """Tests for get_muted_branches_detail."""

    def test_get_muted_branches_detail_returns_expiry(self, state_mod):
        """get_muted_branches_detail returns dicts with name and expires_at."""
        from datetime import datetime, timedelta

        future_ts = (datetime.now() + timedelta(hours=2)).isoformat()
        config_file = state_mod.MEDIC_STATE_FILE
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_file.write_text(
            json.dumps(
                {
                    "config": {
                        "muted_branches": [
                            {"name": "api", "expires_at": future_ts},
                            "speakeasy",
                        ]
                    }
                }
            ),
            encoding="utf-8",
        )

        result = state_mod.get_muted_branches_detail()

        assert len(result) == 2
        assert result[0] == {"name": "api", "expires_at": future_ts}
        assert result[1] == {"name": "speakeasy", "expires_at": None}


# ---------------------------------------------------------------------------
# Tests -- is_enabled TTL
# ---------------------------------------------------------------------------


class TestIsEnabledTTL:
    """Tests for is_enabled with TTL-based disable."""

    def test_is_enabled_ttl_expired_returns_true(self, state_mod):
        """is_enabled returns True when disabled but medic_disabled_until is in the past."""
        from datetime import datetime, timedelta

        past_ts = (datetime.now() - timedelta(hours=1)).isoformat()
        config_file = state_mod.MEDIC_STATE_FILE
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_file.write_text(
            json.dumps(
                {
                    "config": {
                        "medic_enabled": False,
                        "medic_disabled_until": past_ts,
                    }
                }
            ),
            encoding="utf-8",
        )

        result = state_mod.is_enabled()

        assert result is True

    def test_is_enabled_ttl_active_returns_false(self, state_mod):
        """is_enabled returns False when disabled and medic_disabled_until is in the future."""
        from datetime import datetime, timedelta

        future_ts = (datetime.now() + timedelta(hours=1)).isoformat()
        config_file = state_mod.MEDIC_STATE_FILE
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_file.write_text(
            json.dumps(
                {
                    "config": {
                        "medic_enabled": False,
                        "medic_disabled_until": future_ts,
                    }
                }
            ),
            encoding="utf-8",
        )

        result = state_mod.is_enabled()

        assert result is False

    def test_is_enabled_permanent_off(self, state_mod):
        """is_enabled returns False when permanently disabled (no medic_disabled_until)."""
        config_file = state_mod.MEDIC_STATE_FILE
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_file.write_text(
            json.dumps({"config": {"medic_enabled": False}}),
            encoding="utf-8",
        )

        result = state_mod.is_enabled()

        assert result is False


# ---------------------------------------------------------------------------
# Tests -- set_enabled with duration
# ---------------------------------------------------------------------------


class TestSetEnabledDuration:
    """Tests for set_enabled with duration_seconds parameter."""

    def test_set_enabled_off_with_duration(self, state_mod):
        """set_enabled(False, duration) stores medic_disabled_until timestamp."""
        from datetime import datetime, timedelta

        before = datetime.now()
        state_mod.set_enabled(False, duration_seconds=86400)
        after = datetime.now()

        config_file = state_mod.MEDIC_STATE_FILE
        data = json.loads(config_file.read_text(encoding="utf-8"))
        assert data["config"]["medic_enabled"] is False
        disabled_until = data["config"]["medic_disabled_until"]
        ts = datetime.fromisoformat(disabled_until)
        assert ts >= before + timedelta(seconds=86400)
        assert ts <= after + timedelta(seconds=86400)

    def test_set_enabled_on_clears_disabled_until(self, state_mod):
        """set_enabled(True) clears any existing medic_disabled_until."""
        # First disable with TTL
        state_mod.set_enabled(False, duration_seconds=3600)
        config_file = state_mod.MEDIC_STATE_FILE
        data = json.loads(config_file.read_text(encoding="utf-8"))
        assert "medic_disabled_until" in data["config"]

        # Then re-enable
        state_mod.set_enabled(True)
        data = json.loads(config_file.read_text(encoding="utf-8"))
        assert data["config"]["medic_enabled"] is True
        assert "medic_disabled_until" not in data["config"]


# ---------------------------------------------------------------------------
# Tests -- get_disabled_until
# ---------------------------------------------------------------------------


class TestGetDisabledUntil:
    """Tests for get_disabled_until."""

    def test_get_disabled_until_returns_timestamp(self, state_mod):
        """get_disabled_until returns the ISO timestamp when set."""
        from datetime import datetime

        state_mod.set_enabled(False, duration_seconds=86400)

        result = state_mod.get_disabled_until()

        assert result is not None
        ts = datetime.fromisoformat(result)
        assert ts > datetime.now()

    def test_get_disabled_until_returns_none(self, state_mod):
        """get_disabled_until returns None when no TTL is set."""
        state_mod.set_enabled(False)

        result = state_mod.get_disabled_until()

        assert result is None


# ---------------------------------------------------------------------------
# Tests -- unmute_branch with dict entries
# ---------------------------------------------------------------------------


class TestUnmuteBranchDict:
    """Tests for unmute_branch handling dict-format entries."""

    def test_unmute_handles_dict_entries(self, state_mod):
        """unmute_branch removes a dict-format mute entry."""
        state_mod.mute_branch("api", duration_seconds=3600)
        assert "api" in state_mod.get_muted_branches()

        result = state_mod.unmute_branch("api")

        assert result is True
        assert "api" not in state_mod.get_muted_branches()

    def test_unmute_handles_mixed_entries(self, state_mod):
        """unmute_branch removes target from list with both string and dict entries."""
        from datetime import datetime, timedelta

        future_ts = (datetime.now() + timedelta(hours=2)).isoformat()
        config_file = state_mod.MEDIC_STATE_FILE
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_file.write_text(
            json.dumps(
                {
                    "config": {
                        "muted_branches": [
                            "speakeasy",
                            {"name": "api", "expires_at": future_ts},
                            {"name": "drone", "expires_at": None},
                        ]
                    }
                }
            ),
            encoding="utf-8",
        )

        state_mod.unmute_branch("api")

        muted = state_mod.get_muted_branches()
        assert "speakeasy" in muted
        assert "api" not in muted
        assert "drone" in muted


# ---------------------------------------------------------------------------
# Tests -- _clean_expired_mutes
# ---------------------------------------------------------------------------


class TestCleanExpiredMutes:
    """Tests for _clean_expired_mutes."""

    def test_clean_expired_mutes_removes_old(self, state_mod):
        """_clean_expired_mutes removes expired dict entries, keeps strings and active dicts."""
        from datetime import datetime, timedelta

        expired_ts = (datetime.now() - timedelta(hours=1)).isoformat()
        future_ts = (datetime.now() + timedelta(hours=1)).isoformat()

        data = {
            "config": {
                "muted_branches": [
                    "speakeasy",
                    {"name": "api", "expires_at": expired_ts},
                    {"name": "drone", "expires_at": future_ts},
                    {"name": "flow", "expires_at": None},
                ]
            }
        }

        state_mod._clean_expired_mutes(data)

        remaining = data["config"]["muted_branches"]
        names = []
        for entry in remaining:
            if isinstance(entry, str):
                names.append(entry)
            else:
                names.append(entry["name"])
        assert "speakeasy" in names
        assert "api" not in names
        assert "drone" in names
        assert "flow" in names
        assert len(remaining) == 3


# ---------------------------------------------------------------------------
# Tests -- write_config cleans expired mutes
# ---------------------------------------------------------------------------


class TestWriteConfigCleansMutes:
    """Tests for write_config calling _clean_expired_mutes."""

    def test_write_config_cleans_expired_mutes(self, state_mod):
        """write_config removes expired mute entries before persisting."""
        from datetime import datetime, timedelta

        expired_ts = (datetime.now() - timedelta(hours=1)).isoformat()
        future_ts = (datetime.now() + timedelta(hours=1)).isoformat()

        data = {
            "config": {
                "muted_branches": [
                    {"name": "api", "expires_at": expired_ts},
                    {"name": "drone", "expires_at": future_ts},
                ]
            }
        }

        state_mod.write_config(data)

        config_file = state_mod.MEDIC_STATE_FILE
        written = json.loads(config_file.read_text(encoding="utf-8"))
        muted = written["config"]["muted_branches"]
        assert len(muted) == 1
        assert muted[0]["name"] == "drone"

    def test_write_config_cleans_expired_volume_mutes(self, state_mod):
        """write_config expires volume mutes too, not just content mutes."""
        from datetime import datetime, timedelta

        expired_ts = (datetime.now() - timedelta(hours=1)).isoformat()
        future_ts = (datetime.now() + timedelta(hours=1)).isoformat()

        data = {
            "config": {
                "volume_muted_branches": [
                    {"name": "api", "expires_at": expired_ts},
                    {"name": "drone", "expires_at": future_ts},
                ]
            }
        }

        state_mod.write_config(data)

        config_file = state_mod.MEDIC_STATE_FILE
        written = json.loads(config_file.read_text(encoding="utf-8"))
        muted = written["config"]["volume_muted_branches"]
        assert len(muted) == 1
        assert muted[0]["name"] == "drone"


# ---------------------------------------------------------------------------
# Tests -- volume mutes are an independent class from content mutes
# ---------------------------------------------------------------------------


class TestVolumeMutes:
    """Volume mutes write their own list and never touch the content list."""

    def test_volume_mute_writes_separate_key(self, state_mod):
        """mute_branch_volume stores under volume_muted_branches."""
        state_mod.mute_branch_volume("api")

        data = json.loads(state_mod.MEDIC_STATE_FILE.read_text(encoding="utf-8"))
        assert data["config"]["volume_muted_branches"] == [{"name": "api", "expires_at": None}]
        assert not data["config"].get("muted_branches")

    def test_content_mute_does_not_volume_mute(self, state_mod):
        """mute_branch leaves the volume list untouched."""
        state_mod.mute_branch("api")

        assert state_mod.get_muted_branches() == ["api"]
        assert state_mod.get_volume_muted_branches() == []

    def test_volume_mute_does_not_content_mute(self, state_mod):
        """mute_branch_volume leaves the content list untouched."""
        state_mod.mute_branch_volume("api")

        assert state_mod.get_volume_muted_branches() == ["api"]
        assert state_mod.get_muted_branches() == []

    def test_volume_mute_with_ttl(self, state_mod):
        """mute_branch_volume honours a TTL like the content mute does."""
        from datetime import datetime, timedelta

        before = datetime.now()
        state_mod.mute_branch_volume("api", duration_seconds=3600)
        after = datetime.now()

        data = json.loads(state_mod.MEDIC_STATE_FILE.read_text(encoding="utf-8"))
        entry = data["config"]["volume_muted_branches"][0]
        expires = datetime.fromisoformat(entry["expires_at"])
        assert expires >= before + timedelta(seconds=3600)
        assert expires <= after + timedelta(seconds=3600)

    def test_volume_unmute_removes_entry(self, state_mod):
        """unmute_branch_volume clears the branch from the volume list."""
        state_mod.mute_branch_volume("api")
        assert state_mod.get_volume_muted_branches() == ["api"]

        state_mod.unmute_branch_volume("api")
        assert state_mod.get_volume_muted_branches() == []

    def test_volume_unmute_leaves_content_mute_intact(self, state_mod):
        """Volume-unmuting a branch does not lift its content mute."""
        state_mod.mute_branch("api")
        state_mod.mute_branch_volume("api")

        state_mod.unmute_branch_volume("api")

        assert state_mod.get_volume_muted_branches() == []
        assert state_mod.get_muted_branches() == ["api"]

    def test_volume_muted_detail_reports_expiry(self, state_mod):
        """get_volume_muted_branches_detail exposes name and expires_at."""
        state_mod.mute_branch_volume("api", duration_seconds=3600)

        detail = state_mod.get_volume_muted_branches_detail()
        assert len(detail) == 1
        assert detail[0]["name"] == "api"
        assert detail[0]["expires_at"] is not None

    def test_volume_mute_filters_expired_on_read(self, state_mod):
        """An expired volume mute is not reported as active."""
        from datetime import datetime, timedelta

        expired_ts = (datetime.now() - timedelta(hours=1)).isoformat()
        state_mod.MEDIC_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        state_mod.MEDIC_STATE_FILE.write_text(
            json.dumps({"config": {"volume_muted_branches": [{"name": "api", "expires_at": expired_ts}]}}),
            encoding="utf-8",
        )

        assert state_mod.get_volume_muted_branches() == []


class TestLegacyPathMigration:
    """Live state moves off the trio-owned trigger_config.json name."""

    def test_read_config_migrates_legacy_file(self, state_mod, tmp_path) -> None:
        """First read finds the legacy file, moves it, and returns its contents."""
        legacy = state_mod.LEGACY_MEDIC_STATE_FILE
        legacy.parent.mkdir(parents=True, exist_ok=True)
        legacy.write_text(
            json.dumps({"config": {"medic_enabled": True, "muted_branches": ["flow", "api"]}}),
            encoding="utf-8",
        )

        data = state_mod.read_config()

        assert data["config"]["muted_branches"] == ["flow", "api"]
        assert state_mod.MEDIC_STATE_FILE.exists()
        assert not legacy.exists()

    def test_mutes_survive_migration(self, state_mod) -> None:
        """get_muted_branches reads through the migration — no mute is lost."""
        legacy = state_mod.LEGACY_MEDIC_STATE_FILE
        legacy.parent.mkdir(parents=True, exist_ok=True)
        legacy.write_text(
            json.dumps(
                {
                    "config": {
                        "muted_branches": [
                            {"name": "flow", "expires_at": None},
                            {"name": "api", "expires_at": None},
                        ]
                    }
                }
            ),
            encoding="utf-8",
        )

        assert sorted(state_mod.get_muted_branches()) == ["api", "flow"]

    def test_write_after_migration_targets_new_file(self, state_mod) -> None:
        """A mute written post-migration lands in medic_state.json, not the legacy name."""
        legacy = state_mod.LEGACY_MEDIC_STATE_FILE
        legacy.parent.mkdir(parents=True, exist_ok=True)
        legacy.write_text(json.dumps({"config": {"muted_branches": []}}), encoding="utf-8")

        assert state_mod.mute_branch("@seedgo") is True

        data = json.loads(state_mod.MEDIC_STATE_FILE.read_text(encoding="utf-8"))
        assert [e["name"] for e in data["config"]["muted_branches"]] == ["seedgo"]
        assert not legacy.exists()
