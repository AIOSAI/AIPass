# =================== AIPass ====================
# Name: test_watchdog_module.py
# Description: Tests for the watchdog module router
# Version: 1.0.0
# Created: 2026-04-14
# Modified: 2026-04-14
# =============================================

"""Tests for the watchdog module router (Phase 1, FPLAN-0186)."""

import sys
from unittest.mock import patch

import pytest

from aipass.devpulse.apps.modules import watchdog as wd_mod


@pytest.fixture(autouse=True)
def _bypass_caller_guard():
    """Force _guard_caller to always pass so tests don't depend on cwd."""
    with patch.object(wd_mod, "_guard_caller", return_value=True):
        yield


def test_handle_command_rejects_unrelated_command():
    """Router returns False for commands that aren't 'watchdog'."""
    assert wd_mod.handle_command("feedback", []) is False


def test_handle_command_no_args_shows_introspection(capsys):
    """No args -> module introspection (mentions 'watchdog')."""
    result = wd_mod.handle_command("watchdog", [])
    assert result is True
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "watchdog" in combined.lower()


def test_handle_command_help_flag(capsys):
    """--help prints HELP_TEXT."""
    result = wd_mod.handle_command("watchdog", ["--help"])
    assert result is True
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "Usage" in combined or "usage" in combined.lower()


def test_handle_command_unknown_subcommand(capsys):
    """Unknown subcommand returns clean error message."""
    result = wd_mod.handle_command("watchdog", ["bogus"])
    assert result is True
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "bogus" in combined.lower() or "unknown" in combined.lower()


def _fake_registry_module(active=None, kill_result=None, kill_all_result=None):
    """Build a fake watchdog.registry module for router-level tests."""
    fake = type(sys)("fake_registry_mod")
    fake.calls = []

    def list_active(storage_path=None, prune_stale=True):
        """Fake registry list_active — returns the preset active list."""
        fake.calls.append(("list_active", prune_stale))
        return list(active or [])

    def kill_watch(handle, storage_path=None):
        """Fake registry kill_watch — returns the preset result."""
        fake.calls.append(("kill_watch", handle))
        return kill_result or {
            "handle": handle,
            "killed": True,
            "was_alive": True,
            "reason": "fake kill",
        }

    def kill_all(storage_path=None):
        """Fake registry kill_all — returns the preset result list."""
        fake.calls.append(("kill_all",))
        return list(kill_all_result or [])

    fake.list_active = list_active
    fake.kill_watch = kill_watch
    fake.kill_all = kill_all
    return fake


def _fake_timer_module_with_format():
    """Minimal fake timer module exposing ``format_human``."""
    fake = type(sys)("fake_timer_mod_fmt")
    fake.format_human = lambda seconds: f"{seconds}s"
    return fake


def _patch_registry_imports(fake_registry, fake_timer=None):
    """Patch importlib.import_module to return the right fake per module path."""
    timer = fake_timer or _fake_timer_module_with_format()

    def fake_import(name):
        """Patched ``importlib.import_module`` — routes to fake registry/timer."""
        if name.endswith(".registry"):
            return fake_registry
        if name.endswith(".timer"):
            return timer
        raise ImportError(f"unexpected import in test: {name}")

    return patch("importlib.import_module", side_effect=fake_import)


def test_cancel_requires_handle(capsys):
    """`cancel` with no args prints usage."""
    result = wd_mod.handle_command("watchdog", ["cancel"])
    assert result is True
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "usage" in combined.lower() or "cancel" in combined.lower()


def test_cancel_handle_routes_to_registry(capsys):
    """`cancel <handle>` calls registry.kill_watch and prints the result."""
    fake = _fake_registry_module(
        kill_result={
            "handle": "agent-abc123",
            "killed": True,
            "was_alive": True,
            "reason": "SIGTERM — pid 1234 exited in 0.1s",
        }
    )
    with _patch_registry_imports(fake):
        result = wd_mod.handle_command("watchdog", ["cancel", "agent-abc123"])
    assert result is True
    assert ("kill_watch", "agent-abc123") in fake.calls
    combined = capsys.readouterr().out
    assert "agent-abc123" in combined
    assert "KILLED" in combined


def test_cancel_all_routes_to_registry(capsys):
    """`cancel --all` calls registry.kill_all and prints every result line."""
    fake = _fake_registry_module(
        kill_all_result=[
            {"handle": "timer-111111", "killed": True, "was_alive": True, "reason": "ok"},
            {"handle": "schedule-222222", "killed": True, "was_alive": True, "reason": "ok"},
        ]
    )
    with _patch_registry_imports(fake):
        result = wd_mod.handle_command("watchdog", ["cancel", "--all"])
    assert result is True
    assert ("kill_all",) in fake.calls
    out = capsys.readouterr().out
    assert "timer-111111" in out
    assert "schedule-222222" in out


def test_cancel_all_empty(capsys):
    """`cancel --all` with nothing active reports 'no active watches to cancel'."""
    fake = _fake_registry_module(kill_all_result=[])
    with _patch_registry_imports(fake):
        wd_mod.handle_command("watchdog", ["cancel", "--all"])
    out = capsys.readouterr().out.lower()
    assert "no active watches" in out


def test_status_reports_no_active_watches(capsys):
    """status reports 'no active watches' when the registry is empty."""
    fake = _fake_registry_module(active=[])
    with _patch_registry_imports(fake):
        result = wd_mod.handle_command("watchdog", ["status"])
    assert result is True
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "no active watches" in combined.lower()


def test_status_prints_active_watches(capsys):
    """status prints every active watch with handle + type + pid."""
    active = [
        {
            "handle": "agent-abc123",
            "type": "agent",
            "pid": 4321,
            "started_epoch": 1000.0,
            "elapsed_seconds": 134,
            "metadata": {"agent_id": "@drone", "timeout_seconds": 1800},
        },
        {
            "handle": "schedule-def456",
            "type": "schedule",
            "pid": 4322,
            "started_epoch": 2000.0,
            "elapsed_seconds": 45,
            "metadata": {"scheduled_for": "02:00:00", "command": "drone @git status"},
        },
    ]
    fake = _fake_registry_module(active=active)
    with _patch_registry_imports(fake):
        result = wd_mod.handle_command("watchdog", ["status"])
    assert result is True
    out = capsys.readouterr().out
    assert "agent-abc123" in out
    assert "schedule-def456" in out
    assert "@drone" in out
    assert "2 active" in out or "2 active watch" in out


def test_list_routes_to_status(capsys):
    """`list` is an alias — same output as `status`."""
    fake = _fake_registry_module(active=[])
    with _patch_registry_imports(fake):
        result = wd_mod.handle_command("watchdog", ["list"])
    assert result is True
    out = capsys.readouterr().out.lower()
    assert "watchdog status" in out or "no active watches" in out


def test_agent_subcommand_requires_id(capsys):
    """`agent` with no id prints usage."""
    result = wd_mod.handle_command("watchdog", ["agent"])
    assert result is True
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "usage" in combined.lower() or "watchdog agent" in combined.lower()


def test_agent_subcommand_invokes_handler(capsys):
    """`agent <id>` lazily imports and invokes watch_agent."""
    fake_result = {
        "woke": True,
        "reason": "fake clean exit",
        "elapsed": 5,
        "agent_state": "completed",
        "exit_code": 0,
        "agent_id": "@drone",
    }
    fake_module = type(sys)("fake_agent_mod")
    fake_module.watch_agent = lambda agent_id, timeout_seconds=1800: fake_result

    with patch("importlib.import_module", return_value=fake_module):
        result = wd_mod.handle_command("watchdog", ["agent", "@drone"])

    assert result is True
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "completed" in combined
    assert "@drone" in combined


def test_agent_subcommand_parses_timeout_flag():
    """--timeout flag is parsed and passed to the handler."""
    captured_args = {}

    def fake_watch_agent(agent_id, timeout_seconds=1800):
        """Fake agent watcher that records its arguments."""
        captured_args["agent_id"] = agent_id
        captured_args["timeout"] = timeout_seconds
        return {
            "woke": True,
            "reason": "fake",
            "elapsed": 1,
            "agent_state": "completed",
            "exit_code": 0,
            "agent_id": agent_id,
        }

    fake_module = type(sys)("fake_agent_mod")
    fake_module.watch_agent = fake_watch_agent

    with patch("importlib.import_module", return_value=fake_module):
        wd_mod.handle_command("watchdog", ["agent", "@flow", "--timeout", "60"])

    assert captured_args == {"agent_id": "@flow", "timeout": 60}


def test_agent_subcommand_invalid_timeout(capsys):
    """Invalid --timeout value reports a clean error."""
    result = wd_mod.handle_command("watchdog", ["agent", "@flow", "--timeout", "notanumber"])
    assert result is True
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "invalid" in combined.lower() or "--timeout" in combined.lower()


def test_agent_subcommand_default_timeout_is_600():
    """Without an explicit --timeout, the module passes 600s (FPLAN-0189)."""
    captured_args = {}

    def fake_watch_agent(agent_id, timeout_seconds=9999):
        """Fake watcher — records the timeout the module passed in."""
        captured_args["timeout"] = timeout_seconds
        return {
            "woke": True,
            "reason": "fake",
            "elapsed": 1,
            "agent_state": "completed",
            "exit_code": 0,
            "agent_id": agent_id,
        }

    fake_module = type(sys)("fake_agent_mod")
    fake_module.watch_agent = fake_watch_agent

    with patch("importlib.import_module", return_value=fake_module):
        wd_mod.handle_command("watchdog", ["agent", "@flow"])

    assert captured_args["timeout"] == 600


def test_agent_subcommand_emits_next_action_breadcrumb(capsys):
    """On exit, the CLI prints a 'Next: drone @ai_mail dispatch' breadcrumb (FPLAN-0189)."""
    fake_result = {
        "woke": True,
        "reason": "fake clean exit",
        "elapsed": 5,
        "agent_state": "completed",
        "exit_code": 0,
        "agent_id": "@drone",
    }
    fake_module = type(sys)("fake_agent_mod")
    fake_module.watch_agent = lambda agent_id, timeout_seconds=600: fake_result

    with patch("importlib.import_module", return_value=fake_module):
        wd_mod.handle_command("watchdog", ["agent", "@drone"])

    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "Next: drone @ai_mail dispatch @drone" in combined
    assert "state=completed" in combined
