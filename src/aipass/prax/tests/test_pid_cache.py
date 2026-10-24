# =================== AIPass ====================
# Name: test_pid_cache.py
# Description: Tests for the PID cache handler
# Version: 1.2.0
# Created: 2026-07-10
# Modified: 2026-10-23
# =============================================

"""Tests for apps/handlers/monitoring/pid_cache.py"""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(json_structure) — refresh's log_operation("pid_cache_refresh") record, covered by that row

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from aipass.prax.apps.handlers.monitoring import pid_cache


@pytest.fixture(autouse=True)
def _pid_cache_fresh(monkeypatch):
    """Double the collaborators where pid_cache binds them and give each test an empty cache."""
    monkeypatch.setattr(pid_cache, "json_handler", MagicMock())
    monkeypatch.setattr(pid_cache, "logger", MagicMock())
    monkeypatch.setattr(pid_cache, "_pid_cache", {})
    monkeypatch.setattr(pid_cache, "_pid_cache_last_refresh", 0.0)


def _import_pid_cache():
    """The pid_cache module, bound at the top of this file."""
    return pid_cache


class TestParseLockPid:
    """Test dispatch lock file parsing for PID cache."""

    def test_no_lock_file_does_nothing(self, tmp_path):
        """Branch entry without a lock file adds nothing to cache."""
        mod = _import_pid_cache()
        new_cache: dict[str, int] = {}
        entry = {"path": str(tmp_path / "somebranch"), "name": "flow"}
        mod.parse_lock_pid(entry, new_cache, tmp_path)
        assert new_cache == {}

    def test_lock_file_with_live_pid_on_linux(self, tmp_path):
        """Lock file with a PID that has a /proc entry adds to cache."""
        mod = _import_pid_cache()
        branch_dir = tmp_path / "mybranch"
        mail_dir = branch_dir / ".ai_mail.local"
        mail_dir.mkdir(parents=True)
        lock_data = {"pid": 12345}
        (mail_dir / ".dispatch.lock").write_text(json.dumps(lock_data), encoding="utf-8")

        new_cache: dict[str, int] = {}
        entry = {"path": str(branch_dir), "name": "flow"}

        real_exists = Path.exists
        with (
            patch("sys.platform", "linux"),
            patch(
                "pathlib.Path.exists",
                autospec=True,
                side_effect=lambda self, **kw: self.name == "12345" or real_exists(self, **kw),
            ),
        ):
            mod.parse_lock_pid(entry, new_cache, tmp_path)

        assert new_cache.get("FLOW") == 12345

    def test_lock_file_with_zero_pid(self, tmp_path):
        """Lock file with pid=0 skips entry."""
        mod = _import_pid_cache()
        branch_dir = tmp_path / "mybranch"
        mail_dir = branch_dir / ".ai_mail.local"
        mail_dir.mkdir(parents=True)
        lock_data = {"pid": 0}
        (mail_dir / ".dispatch.lock").write_text(json.dumps(lock_data), encoding="utf-8")

        new_cache: dict[str, int] = {}
        entry = {"path": str(branch_dir), "name": "flow"}
        mod.parse_lock_pid(entry, new_cache, tmp_path)
        assert new_cache == {}

    def test_lock_file_with_invalid_json(self, tmp_path):
        """Lock file with invalid JSON logs warning and continues."""
        mod = _import_pid_cache()
        branch_dir = tmp_path / "mybranch"
        mail_dir = branch_dir / ".ai_mail.local"
        mail_dir.mkdir(parents=True)
        (mail_dir / ".dispatch.lock").write_text("{bad json}", encoding="utf-8")

        new_cache: dict[str, int] = {}
        entry = {"path": str(branch_dir), "name": "flow"}
        mod.parse_lock_pid(entry, new_cache, tmp_path)
        assert new_cache == {}

    def test_lock_file_with_empty_name(self, tmp_path):
        """Branch entry with empty name skips cache update."""
        mod = _import_pid_cache()
        branch_dir = tmp_path / "mybranch"
        mail_dir = branch_dir / ".ai_mail.local"
        mail_dir.mkdir(parents=True)
        lock_data = {"pid": 99999}
        (mail_dir / ".dispatch.lock").write_text(json.dumps(lock_data), encoding="utf-8")

        new_cache: dict[str, int] = {}
        entry = {"path": str(branch_dir), "name": ""}

        with (
            patch("sys.platform", "linux"),
            patch("pathlib.Path.exists", return_value=True),
        ):
            mod.parse_lock_pid(entry, new_cache, tmp_path)
        assert new_cache == {}


class TestRefresh:
    """Test PID cache refresh from registry."""

    def test_skips_when_within_ttl(self, tmp_path, monkeypatch):
        """Cache refresh is skipped if within TTL window.

        The registry lists a branch, so only the TTL stands between the call and
        a scan: without it the guard could be gone and the test still pass.
        """
        mod = _import_pid_cache()
        (tmp_path / "AIPASS_REGISTRY.json").write_text(json.dumps({"branches": [{"name": "flow"}]}), encoding="utf-8")
        with mod._pid_cache_lock:
            monkeypatch.setattr(mod, "_pid_cache_last_refresh", time.time())

        with patch.object(mod, "parse_lock_pid") as mock_parse:
            mod.refresh(repo_root=tmp_path)
            mock_parse.assert_not_called()

    def test_a_scan_replaces_the_cache_rather_than_adding_to_it(self, tmp_path):
        """A branch whose lock is gone must drop out of the mapping on the next scan."""
        mod = _import_pid_cache()
        mod._pid_cache["STALE"] = 4242
        (tmp_path / "AIPASS_REGISTRY.json").write_text(json.dumps({"branches": []}), encoding="utf-8")

        mod.refresh(repo_root=tmp_path)

        assert mod._pid_cache == {}

    def test_handles_missing_registry(self, tmp_path, monkeypatch):
        """No registry means refresh returns early — quietly, and without scanning.

        Absent is not broken: no lock file is parsed, the cache the monitor is
        already attributing events with is left alone, and nothing is logged,
        because a repo root with no registry is a normal state and not a
        failure to report.
        """
        mod = _import_pid_cache()
        with mod._pid_cache_lock:
            monkeypatch.setattr(mod, "_pid_cache_last_refresh", 0.0)
            mod._pid_cache.clear()
            mod._pid_cache["FLOW"] = 4242

        with patch.object(mod, "parse_lock_pid") as mock_parse, patch.object(mod, "logger") as log:
            assert mod.refresh(repo_root=tmp_path) is None

        mock_parse.assert_not_called()
        log.info.assert_not_called()
        assert mod._pid_cache == {"FLOW": 4242}

    def test_handles_exception_in_refresh(self, tmp_path, monkeypatch):
        """A corrupt registry is caught, reported, and costs no cached PID.

        The scan is abandoned mid-flight, so the guarantee that matters is that
        the previously cached mapping survives: a half-read registry must not
        leave the monitor attributing events to nobody.
        """
        mod = _import_pid_cache()
        with mod._pid_cache_lock:
            monkeypatch.setattr(mod, "_pid_cache_last_refresh", 0.0)
            mod._pid_cache.clear()
            mod._pid_cache["FLOW"] = 4242

        registry_file = tmp_path / "AIPASS_REGISTRY.json"
        registry_file.write_text("{corrupt", encoding="utf-8")

        with patch.object(mod, "logger") as log:
            assert mod.refresh(repo_root=tmp_path) is None

        assert mod._pid_cache == {"FLOW": 4242}
        assert log.info.call_args.args[0] == "[pid_cache] Refresh failed: %s"


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


class TestDefaultRoot:
    """refresh() with no argument finds the real repo root and its repo-relative registry paths."""

    def test_default_root_resolves_relative_branch_paths(self, tmp_path, monkeypatch):
        """Registry path "src/aipass/flow" joins the repo root, never the cwd; the lock is ai_mail's real shape."""
        mod = _import_pid_cache()
        monkeypatch.setattr(mod, "find_repo_root", lambda: tmp_path)
        monkeypatch.chdir(tmp_path.parent)
        mail_dir = tmp_path / "src" / "aipass" / "flow" / ".ai_mail.local"
        mail_dir.mkdir(parents=True)
        (mail_dir / ".dispatch.lock").write_text(
            json.dumps({"pid": 12345, "timestamp": "2026-10-23T10:00:00", "branch": "flow"}), encoding="utf-8"
        )
        (tmp_path / "AIPASS_REGISTRY.json").write_text(
            json.dumps({"branches": [{"name": "flow", "path": "src/aipass/flow"}]}), encoding="utf-8"
        )
        real_exists = Path.exists
        with (
            patch("sys.platform", "linux"),
            patch(
                "pathlib.Path.exists",
                autospec=True,
                side_effect=lambda self, **kw: self.name == "12345" or real_exists(self, **kw),
            ),
        ):
            mod.refresh()
        assert mod._pid_cache == {"FLOW": 12345}
