# =================== AIPass ====================
# Name: test_notify.py
# Description: Tests for desktop notification handler
# Version: 1.0.0
# Created: 2026-04-03
# Modified: 2026-04-03
# =============================================

"""Tests for notify module -- dbus and notify-send notification paths."""

import subprocess
import pytest
from unittest.mock import MagicMock

import aipass.ai_mail.apps.handlers.notify as mod


# --- Fixtures --------------------------------------------------------


@pytest.fixture(autouse=True)
def _suppress_log_operation(monkeypatch):
    """Prevent json_handler.log_operation from touching real files."""
    monkeypatch.setattr(mod, "json_handler", MagicMock())


@pytest.fixture(autouse=True)
def _suppress_logger(monkeypatch):
    """Suppress logger output during tests."""
    monkeypatch.setattr(mod, "logger", MagicMock())


# --- send_notification tests ------------------------------------------


def test_send_notification_returns_true_when_dbus_succeeds(monkeypatch):
    """Returns True when dbus path succeeds on first try."""
    monkeypatch.setattr(mod, "_send_via_dbus", lambda *a: True)
    monkeypatch.setattr(mod, "_send_via_notify_send", lambda *a: False)

    result = mod.send_notification("Title", "Body", "spawn")
    assert result is True


def test_send_notification_falls_back_to_notify_send(monkeypatch):
    """Falls back to notify-send when dbus fails, returns True on fallback success."""
    monkeypatch.setattr(mod, "_send_via_dbus", lambda *a: False)
    monkeypatch.setattr(mod, "_send_via_notify_send", lambda *a: True)

    result = mod.send_notification("Title", "Body", "spawn")
    assert result is True


def test_send_notification_returns_false_when_both_fail(monkeypatch):
    """Returns False when both dbus and notify-send fail."""
    monkeypatch.setattr(mod, "_send_via_dbus", lambda *a: False)
    monkeypatch.setattr(mod, "_send_via_notify_send", lambda *a: False)

    result = mod.send_notification("Title", "Body", "spawn")
    assert result is False


def test_send_notification_default_source(monkeypatch):
    """Default source parameter is 'ai_mail'."""
    captured = {}

    def fake_dbus(title, body, source, icon):
        captured["source"] = source
        return True

    monkeypatch.setattr(mod, "_send_via_dbus", fake_dbus)

    mod.send_notification("Title", "Body")
    assert captured["source"] == "ai_mail"


# --- _send_via_dbus tests --------------------------------------------


def test_send_via_dbus_constructs_correct_command(monkeypatch):
    """Passes correct arguments to subprocess.run."""
    captured_args = {}

    def fake_run(cmd, **kwargs):
        captured_args["cmd"] = cmd
        captured_args["kwargs"] = kwargs
        result = MagicMock()
        result.returncode = 0
        return result

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    monkeypatch.setattr(mod.shutil, "which", lambda name: "/usr/bin/python3")

    mod._send_via_dbus("Test Title", "Test Body", "drone", "dialog-warning")

    cmd = captured_args["cmd"]
    assert cmd[0] == "/usr/bin/python3"
    assert cmd[1] == "-c"
    assert cmd[2] == mod._DBUS_SCRIPT
    assert cmd[3] == "drone"
    assert cmd[4] == "dialog-warning"
    assert cmd[5] == "Test Title"
    assert cmd[6] == "Test Body"
    assert captured_args["kwargs"]["timeout"] == 5


def test_send_via_dbus_returns_true_on_success(monkeypatch):
    """Returns True when subprocess exits with code 0."""
    mock_result = MagicMock()
    mock_result.returncode = 0
    monkeypatch.setattr(mod.subprocess, "run", lambda *a, **kw: mock_result)
    monkeypatch.setattr(mod.shutil, "which", lambda name: "/usr/bin/python3")

    assert mod._send_via_dbus("T", "B", "s", "i") is True


def test_send_via_dbus_returns_false_on_nonzero_exit(monkeypatch):
    """Returns False when subprocess exits with nonzero code."""
    mock_result = MagicMock()
    mock_result.returncode = 1
    monkeypatch.setattr(mod.subprocess, "run", lambda *a, **kw: mock_result)
    monkeypatch.setattr(mod.shutil, "which", lambda name: "/usr/bin/python3")

    assert mod._send_via_dbus("T", "B", "s", "i") is False


def test_send_via_dbus_returns_false_on_subprocess_error(monkeypatch):
    """Returns False on SubprocessError."""

    def raise_error(*a, **kw):
        raise subprocess.SubprocessError("timeout")

    monkeypatch.setattr(mod.subprocess, "run", raise_error)
    monkeypatch.setattr(mod.shutil, "which", lambda name: "/usr/bin/python3")

    assert mod._send_via_dbus("T", "B", "s", "i") is False


def test_send_via_dbus_returns_false_on_file_not_found(monkeypatch):
    """Returns False when python binary not found."""

    def raise_error(*a, **kw):
        raise FileNotFoundError("python3")

    monkeypatch.setattr(mod.subprocess, "run", raise_error)
    monkeypatch.setattr(mod.shutil, "which", lambda name: None)

    assert mod._send_via_dbus("T", "B", "s", "i") is False


# --- _send_via_notify_send tests --------------------------------------


def test_send_via_notify_send_returns_true_on_success(monkeypatch):
    """Returns True when notify-send succeeds."""
    mock_result = MagicMock()
    mock_result.returncode = 0
    monkeypatch.setattr(mod.subprocess, "run", lambda *a, **kw: mock_result)

    assert mod._send_via_notify_send("Title", "Body", "dialog-information") is True


def test_send_via_notify_send_passes_correct_args(monkeypatch):
    """Passes correct arguments to subprocess.run."""
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return MagicMock(returncode=0)

    monkeypatch.setattr(mod.subprocess, "run", fake_run)

    mod._send_via_notify_send("Hello", "World", "dialog-warning")

    assert captured["cmd"] == ["notify-send", "-i", "dialog-warning", "Hello", "World"]
    assert captured["kwargs"]["capture_output"] is True
    assert captured["kwargs"]["timeout"] == 5


def test_send_via_notify_send_returns_false_on_file_not_found(monkeypatch):
    """Returns False when notify-send is not installed."""

    def raise_error(*a, **kw):
        raise FileNotFoundError("notify-send")

    monkeypatch.setattr(mod.subprocess, "run", raise_error)

    assert mod._send_via_notify_send("T", "B", "i") is False


def test_send_via_notify_send_returns_false_on_subprocess_error(monkeypatch):
    """Returns False on SubprocessError."""

    def raise_error(*a, **kw):
        raise subprocess.SubprocessError("broken pipe")

    monkeypatch.setattr(mod.subprocess, "run", raise_error)

    assert mod._send_via_notify_send("T", "B", "i") is False
