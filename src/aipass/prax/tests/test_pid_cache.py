# =================== AIPass ====================
# Name: test_pid_cache.py
# Description: Tests for the PID cache handler
# Version: 1.0.0
# Created: 2026-07-10
# Modified: 2026-07-10
# =============================================

"""Tests for apps/handlers/monitoring/pid_cache.py"""

import json
import sys
import time
from unittest.mock import MagicMock, patch

_HANDLER_MOCKS = {
    "aipass.prax.apps.handlers.json": MagicMock(),
    "aipass.prax.apps.handlers.json.json_handler": MagicMock(),
}


def _import_pid_cache():
    """Import (or reload) the pid_cache module with handler mocks."""
    fresh = {k: MagicMock() for k in _HANDLER_MOCKS}
    with patch.dict(sys.modules, fresh):
        import importlib

        if "aipass.prax.apps.handlers.monitoring.pid_cache" in sys.modules:
            mod = importlib.reload(sys.modules["aipass.prax.apps.handlers.monitoring.pid_cache"])
        else:
            mod = importlib.import_module("aipass.prax.apps.handlers.monitoring.pid_cache")
        return mod


class TestParseLockPid:
    """Test dispatch lock file parsing for PID cache."""

    def test_no_lock_file_does_nothing(self, tmp_path):
        """Branch entry without a lock file adds nothing to cache."""
        mod = _import_pid_cache()
        new_cache: dict[str, int] = {}
        entry = {"path": str(tmp_path / "somebranch"), "name": "flow"}
        mod.parse_lock_pid(entry, new_cache)
        assert new_cache == {}

    def test_lock_file_with_live_pid_on_linux(self, tmp_path):
        """Lock file with a PID that has a /proc entry adds to cache."""
        mod = _import_pid_cache()
        branch_dir = tmp_path / "mybranch"
        mail_dir = branch_dir / "ai_mail.local"
        mail_dir.mkdir(parents=True)
        lock_data = {"pid": 12345}
        (mail_dir / ".dispatch.lock").write_text(json.dumps(lock_data), encoding="utf-8")

        new_cache: dict[str, int] = {}
        entry = {"path": str(branch_dir), "name": "flow"}

        with (
            patch("sys.platform", "linux"),
            patch("pathlib.Path.exists", side_effect=lambda self=None: True),
        ):
            mod.parse_lock_pid(entry, new_cache)

        assert new_cache.get("FLOW") == 12345

    def test_lock_file_with_zero_pid(self, tmp_path):
        """Lock file with pid=0 skips entry."""
        mod = _import_pid_cache()
        branch_dir = tmp_path / "mybranch"
        mail_dir = branch_dir / "ai_mail.local"
        mail_dir.mkdir(parents=True)
        lock_data = {"pid": 0}
        (mail_dir / ".dispatch.lock").write_text(json.dumps(lock_data), encoding="utf-8")

        new_cache: dict[str, int] = {}
        entry = {"path": str(branch_dir), "name": "flow"}
        mod.parse_lock_pid(entry, new_cache)
        assert new_cache == {}

    def test_lock_file_with_invalid_json(self, tmp_path):
        """Lock file with invalid JSON logs warning and continues."""
        mod = _import_pid_cache()
        branch_dir = tmp_path / "mybranch"
        mail_dir = branch_dir / "ai_mail.local"
        mail_dir.mkdir(parents=True)
        (mail_dir / ".dispatch.lock").write_text("{bad json}", encoding="utf-8")

        new_cache: dict[str, int] = {}
        entry = {"path": str(branch_dir), "name": "flow"}
        mod.parse_lock_pid(entry, new_cache)
        assert new_cache == {}

    def test_lock_file_with_empty_name(self, tmp_path):
        """Branch entry with empty name skips cache update."""
        mod = _import_pid_cache()
        branch_dir = tmp_path / "mybranch"
        mail_dir = branch_dir / "ai_mail.local"
        mail_dir.mkdir(parents=True)
        lock_data = {"pid": 99999}
        (mail_dir / ".dispatch.lock").write_text(json.dumps(lock_data), encoding="utf-8")

        new_cache: dict[str, int] = {}
        entry = {"path": str(branch_dir), "name": ""}

        with (
            patch("sys.platform", "linux"),
            patch("pathlib.Path.exists", return_value=True),
        ):
            mod.parse_lock_pid(entry, new_cache)
        assert new_cache == {}


class TestRefresh:
    """Test PID cache refresh from registry."""

    def test_skips_when_within_ttl(self):
        """Cache refresh is skipped if within TTL window."""
        mod = _import_pid_cache()
        with mod._pid_cache_lock:
            setattr(mod, "_pid_cache_last_refresh", time.time())

        with patch.object(mod, "parse_lock_pid") as mock_parse:
            mod.refresh()
            mock_parse.assert_not_called()

    def test_handles_missing_registry(self, tmp_path):
        """Missing registry file does not crash."""
        mod = _import_pid_cache()
        with mod._pid_cache_lock:
            setattr(mod, "_pid_cache_last_refresh", 0.0)

        mod.refresh(repo_root=tmp_path)

    def test_handles_exception_in_refresh(self, tmp_path):
        """Exception during refresh is caught and logged."""
        mod = _import_pid_cache()
        with mod._pid_cache_lock:
            setattr(mod, "_pid_cache_last_refresh", 0.0)

        registry_file = tmp_path / "AIPASS_REGISTRY.json"
        registry_file.write_text("{corrupt", encoding="utf-8")
        mod.refresh(repo_root=tmp_path)


class TestGetPidForBranch:
    """Test PID lookup for branch names."""

    def test_returns_pid_from_cache(self):
        """Returns PID when branch is in cache."""
        mod = _import_pid_cache()
        with mod._pid_cache_lock:
            mod._pid_cache["FLOW"] = 42

        with patch.object(mod, "refresh"):
            result = mod.get_pid_for_branch("flow")
        assert result == 42

    def test_strips_agent_suffix(self):
        """Branch name ending in ' AGENT' is stripped before lookup."""
        mod = _import_pid_cache()
        with mod._pid_cache_lock:
            mod._pid_cache["FLOW"] = 42

        with patch.object(mod, "refresh"):
            result = mod.get_pid_for_branch("flow agent")
        assert result == 42

    def test_returns_none_when_not_cached(self):
        """Returns None when branch is not in cache."""
        mod = _import_pid_cache()
        with mod._pid_cache_lock:
            mod._pid_cache.clear()

        with patch.object(mod, "refresh"):
            result = mod.get_pid_for_branch("nonexistent")
        assert result is None
