"""Tests for the hook-sounds plugin — mute/unmute hook notification sounds."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from aipass.drone.apps.plugins.hook_sounds.hook_sounds_plugin import (
    handle_command,
    is_muted,
    mute,
    unmute,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """Redirect MUTE_FLAG to a temp path so tests don't touch /tmp."""
    flag = tmp_path / "aipass-hooks-muted"
    monkeypatch.setattr(
        "aipass.drone.apps.plugins.hook_sounds.hook_sounds_plugin.MUTE_FLAG",
        flag,
    )
    with patch("aipass.drone.apps.plugins.hook_sounds.hook_sounds_plugin.json_handler"):
        yield flag


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------


class TestMute:
    def test_mute_creates_flag(self, _isolate):
        flag = _isolate
        assert not flag.exists()
        mute()
        assert flag.exists()

    def test_mute_returns_true(self, _isolate):
        assert mute() is True

    def test_mute_idempotent(self, _isolate):
        flag = _isolate
        mute()
        mute()
        assert flag.exists()


class TestUnmute:
    def test_unmute_removes_flag(self, _isolate):
        flag = _isolate
        flag.touch()
        unmute()
        assert not flag.exists()

    def test_unmute_returns_true(self, _isolate):
        assert unmute() is True

    def test_unmute_no_flag_no_error(self, _isolate):
        flag = _isolate
        assert not flag.exists()
        unmute()
        assert not flag.exists()


class TestIsMuted:
    def test_not_muted_by_default(self, _isolate):
        assert is_muted() is False

    def test_muted_after_mute(self, _isolate):
        mute()
        assert is_muted() is True

    def test_not_muted_after_unmute(self, _isolate):
        mute()
        unmute()
        assert is_muted() is False


# ---------------------------------------------------------------------------
# handle_command routing
# ---------------------------------------------------------------------------


class TestHandleCommand:
    def test_off_mutes(self, _isolate, capsys):
        result = handle_command("off")
        assert result is True
        assert _isolate.exists()
        assert "MUTED" in capsys.readouterr().out

    def test_on_unmutes(self, _isolate, capsys):
        _isolate.touch()
        result = handle_command("on")
        assert result is True
        assert not _isolate.exists()
        assert "ACTIVE" in capsys.readouterr().out

    def test_no_command_shows_active(self, _isolate, capsys):
        result = handle_command(None)
        assert result is True
        assert "ACTIVE" in capsys.readouterr().out

    def test_no_command_shows_muted(self, _isolate, capsys):
        _isolate.touch()
        result = handle_command(None)
        assert result is True
        out = capsys.readouterr().out
        assert "MUTED" in out

    def test_off_then_on_roundtrip(self, _isolate, capsys):
        handle_command("off")
        assert _isolate.exists()
        handle_command("on")
        assert not _isolate.exists()
