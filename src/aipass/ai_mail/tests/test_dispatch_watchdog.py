# =================== AIPass ====================
# Name: test_dispatch_watchdog.py
# Description: Tests for watchdog auto-spawn in dispatch pipeline
# Version: 1.0.0
# Created: 2026-04-19
# Modified: 2026-04-19
# =============================================

"""Tests for _spawn_watchdog() — watchdog auto-spawn in dispatch pipeline."""

import json
from unittest.mock import patch, MagicMock
import pytest
from pathlib import Path

import aipass.ai_mail.apps.modules.dispatch as dispatch_mod


# Retrieve private function via module attribute access
_spawn_watchdog = getattr(dispatch_mod, "_spawn_watchdog")

_POPEN_PATH = "aipass.ai_mail.apps.modules.dispatch.subprocess.Popen"


@pytest.fixture(autouse=True)
def _suppress_log_operation(monkeypatch):
    """Prevent json_handler.log_operation from touching real files."""
    monkeypatch.setattr(
        "aipass.ai_mail.apps.modules.dispatch.json_handler.log_operation",
        lambda *a, **kw: None,
    )


class TestSpawnWatchdog:
    """Tests for _spawn_watchdog() — registry lookup + detached Popen."""

    def test_spawns_with_devpulse_cwd(self, tmp_path):
        """_spawn_watchdog sets cwd=devpulse_path when spawning."""
        devpulse_path = tmp_path / "devpulse"
        devpulse_path.mkdir()
        registry_file = tmp_path / "AIPASS_REGISTRY.json"
        registry_file.write_text(
            json.dumps({"branches": [{"name": "DEVPULSE", "email": "@devpulse", "path": str(devpulse_path)}]}),
            encoding="utf-8",
        )

        fake_proc = MagicMock()
        fake_proc.pid = 42

        with patch(_POPEN_PATH, return_value=fake_proc) as mock_popen:
            result = _spawn_watchdog("@drone", tmp_path)

        assert result is True
        mock_popen.assert_called_once()
        call_kwargs = mock_popen.call_args
        assert call_kwargs[0][0] == ["drone", "@devpulse", "watchdog", "agent", "@drone"]
        assert call_kwargs[1]["cwd"] == str(devpulse_path)
        assert call_kwargs[1]["start_new_session"] is True

    def test_returns_false_when_devpulse_not_in_registry(self, tmp_path):
        """Returns False when devpulse not found in registry."""
        registry_file = tmp_path / "AIPASS_REGISTRY.json"
        registry_file.write_text(
            json.dumps({"branches": [{"name": "DRONE", "email": "@drone", "path": str(tmp_path / "drone")}]}),
            encoding="utf-8",
        )

        result = _spawn_watchdog("@drone", tmp_path)
        assert result is False

    def test_returns_false_when_registry_missing(self, tmp_path):
        """Returns False when AIPASS_REGISTRY.json does not exist."""
        result = _spawn_watchdog("@drone", tmp_path)
        assert result is False

    def test_returns_false_when_devpulse_path_missing(self, tmp_path):
        """Returns False when devpulse path from registry does not exist on disk."""
        registry_file = tmp_path / "AIPASS_REGISTRY.json"
        registry_file.write_text(
            json.dumps(
                {"branches": [{"name": "DEVPULSE", "email": "@devpulse", "path": str(tmp_path / "nonexistent")}]}
            ),
            encoding="utf-8",
        )

        result = _spawn_watchdog("@drone", tmp_path)
        assert result is False

    def test_returns_false_when_drone_not_found(self, tmp_path):
        """Returns False when 'drone' binary not on PATH (FileNotFoundError)."""
        devpulse_path = tmp_path / "devpulse"
        devpulse_path.mkdir()
        registry_file = tmp_path / "AIPASS_REGISTRY.json"
        registry_file.write_text(
            json.dumps({"branches": [{"name": "DEVPULSE", "email": "@devpulse", "path": str(devpulse_path)}]}),
            encoding="utf-8",
        )

        with patch(_POPEN_PATH, side_effect=FileNotFoundError("drone not found")):
            result = _spawn_watchdog("@drone", tmp_path)

        assert result is False

    def test_resolves_relative_path_in_registry(self, tmp_path):
        """Resolves relative devpulse path relative to repo_root."""
        devpulse_path = tmp_path / "src" / "devpulse"
        devpulse_path.mkdir(parents=True)
        registry_file = tmp_path / "AIPASS_REGISTRY.json"
        registry_file.write_text(
            json.dumps({"branches": [{"name": "DEVPULSE", "email": "@devpulse", "path": "src/devpulse"}]}),
            encoding="utf-8",
        )

        fake_proc = MagicMock()
        fake_proc.pid = 99

        with patch(_POPEN_PATH, return_value=fake_proc) as mock_popen:
            result = _spawn_watchdog("@flow", tmp_path)

        assert result is True
        assert mock_popen.call_args[1]["cwd"] == str(devpulse_path)
