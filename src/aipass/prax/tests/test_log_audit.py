# =================== AIPass ====================
# Name: test_log_audit.py
# Description: Unit tests for PRAX log_audit module
# Version: 1.2.0
# Created: 2026-03-24
# Modified: 2026-09-29
# =============================================

"""Tests for apps/modules/log_audit.py."""

# Tests for prax log_audit module command routing, help text, and display formatting.
#
# log_audit and log_watchdog are the real modules, imported at the top; the
# autouse audit_world fixture replaces each edge where log_audit binds it.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(through_the_command) — the sweep route _run_sweep(), covered by tests/test_sweep.py
# seedgo: no-test-needed(help_flag_safety) — -h skipping _run_enforce(), covered by tests/test_help_flag_safety.py
# seedgo: no-test-needed(json_structure) — the log_audit_executed record written through json_handler.log_operation

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from aipass.prax.apps.handlers.cli.arg_gate import UnknownArgument
from aipass.prax.apps.handlers.logging import log_watchdog
from aipass.prax.apps.modules import log_audit

# =============================================
# HELPERS
# =============================================

_WATCHDOG_NAMES = (
    "scan_log_files",
    "log_health_summary",
    "enforce_log_limits",
    "scan_branch_log_files",
    "branch_log_health_summary",
    "enforce_branch_log_limits",
)


@pytest.fixture(autouse=True)
def audit_world(monkeypatch, tmp_path):
    """Every edge of log_audit.py, replaced where log_audit binds it.

    The console is the real one, read through capsys. error and warning are
    recorders; logger and json_handler are recorders, so no line reaches a live
    log or prax_json, and AIPASS_TEST_LOG_DIR points at tmp_path for anything else.
    """
    monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path / "logs"))
    world = SimpleNamespace(error=MagicMock(), warning=MagicMock(), logger=MagicMock(), json_handler=MagicMock())
    for name in ("error", "warning", "logger", "json_handler"):
        monkeypatch.setattr(log_audit, name, getattr(world, name))
    return world


def _ensure_watchdog_mock(monkeypatch):
    """Replace the six log_watchdog functions log_audit imports at call time, on the real module."""
    mock_watchdog = MagicMock()
    mock_watchdog.scan_log_files = MagicMock(
        return_value=[
            {"name": "system.log", "lines": 500, "size_kb": 45, "status": "ok"},
            {"name": "error.log", "lines": 2500, "size_kb": 200, "status": "oversized"},
        ]
    )
    mock_watchdog.log_health_summary = MagicMock(
        return_value={
            "total_files": 2,
            "total_lines": 3000,
            "largest_file": "error.log",
            "largest_lines": 2500,
            "healthy": False,
            "oversized_count": 1,
            "critical_count": 0,
        }
    )
    mock_watchdog.enforce_log_limits = MagicMock(
        return_value=[
            {"name": "error.log", "truncated": True, "original_lines": 2500, "new_lines": 1000},
        ]
    )
    mock_watchdog.scan_branch_log_files = MagicMock(
        return_value=[
            {
                "name": "engine.jsonl",
                "branch": "hooks",
                "lines": 200000,
                "size_kb": 64512.0,
                "size_mb": 63.0,
                "has_rotation": False,
                "status": "critical",
                "path": "/fake/hooks/logs/engine.jsonl",
            },
        ]
    )
    mock_watchdog.branch_log_health_summary = MagicMock(
        return_value={
            "total_files": 5,
            "oversized_count": 1,
            "critical_count": 1,
            "total_size_mb": 95.1,
            "largest_file": "hooks/engine.jsonl",
            "largest_size_mb": 63.0,
            "healthy": False,
        }
    )
    mock_watchdog.enforce_branch_log_limits = MagicMock(
        return_value=[
            {
                "name": "engine.jsonl",
                "branch": "hooks",
                "original_lines": 200000,
                "new_lines": 5001,
                "size_mb": 63.0,
                "truncated": True,
            },
        ]
    )
    for name in _WATCHDOG_NAMES:
        monkeypatch.setattr(log_watchdog, name, getattr(mock_watchdog, name))
    return mock_watchdog


# =============================================
# TESTS
# =============================================


def test_handle_command_help(audit_world, monkeypatch, capsys):
    """--help flag returns True and displays help text."""

    result = log_audit.handle_command("log-audit", ["--help"])
    assert result is True
    assert "log-audit sweep" in capsys.readouterr().out


def test_handle_command_help_h_flag(audit_world, monkeypatch, capsys):
    """-h flag also triggers help with audit-related content."""

    result = log_audit.handle_command("log-audit", ["-h"])
    assert result is True
    calls = capsys.readouterr().out.splitlines()
    assert any("audit" in c.lower() for c in calls)


def test_handle_command_no_args_calls_introspection(audit_world, monkeypatch, capsys):
    """No args prints introspection and returns True."""

    result = log_audit.handle_command("log-audit", [])
    assert result is True
    calls = capsys.readouterr().out.splitlines()
    assert any("Log Audit Module" in c for c in calls)


def test_handle_command_wrong_command(audit_world, monkeypatch, capsys):
    """Wrong command name returns False."""

    result = log_audit.handle_command("not-log-audit", [])
    assert result is False


def test_print_help_runs(audit_world, monkeypatch, capsys):
    """print_help runs without error and includes audit/enforce subcommands."""
    log_audit.print_help()
    calls = capsys.readouterr().out.splitlines()
    assert any("audit" in c.lower() for c in calls)
    assert any("enforce" in c.lower() for c in calls)


def test_print_introspection_runs(audit_world, monkeypatch, capsys):
    """print_introspection runs without error."""
    log_audit.print_introspection()
    calls = capsys.readouterr().out.splitlines()
    assert any("Connected Handlers" in c for c in calls)


def test_display_audit_healthy(audit_world, monkeypatch, capsys):
    """_display_audit formats healthy summary correctly."""
    files = [{"name": "system.log", "lines": 200, "size_kb": 10, "status": "ok"}]
    summary = {
        "total_files": 1,
        "total_lines": 200,
        "largest_file": "system.log",
        "largest_lines": 200,
        "healthy": True,
        "oversized_count": 0,
        "critical_count": 0,
    }

    log_audit._display_audit(files, summary)
    calls = capsys.readouterr().out.splitlines()
    assert any("HEALTHY" in c for c in calls)
    assert any("system.log" in c for c in calls)


def test_display_audit_oversized(audit_world, monkeypatch, capsys):
    """_display_audit shows oversized files when present."""
    files = [
        {"name": "system.log", "lines": 500, "size_kb": 45, "status": "ok"},
        {"name": "error.log", "lines": 2500, "size_kb": 200, "status": "oversized"},
        {"name": "crash.log", "lines": 5000, "size_kb": 400, "status": "critical"},
    ]
    summary = {
        "total_files": 3,
        "total_lines": 8000,
        "largest_file": "crash.log",
        "largest_lines": 5000,
        "healthy": False,
        "oversized_count": 1,
        "critical_count": 1,
    }

    log_audit._display_audit(files, summary)
    calls = capsys.readouterr().out.splitlines()
    # Should show oversized section
    assert any("Oversized files" in c for c in calls)
    # File names appear in output
    assert any("error.log" in c for c in calls)
    assert any("crash.log" in c for c in calls)
    # error() called for unhealthy status
    audit_world.error.assert_called()


def test_handle_command_unknown_subcommand(audit_world, monkeypatch, capsys):
    """An unknown subcommand is refused BY NAME instead of reporting itself handled.

    It used to print the right words and return True, which prax.py turns into
    exit 0 — so `drone @prax log-audit typo && next-step` ran next-step
    (@devpulse's fleet CLI sweep, 2026-09-07).
    """
    _ensure_watchdog_mock(monkeypatch)

    with pytest.raises(UnknownArgument) as refusal:
        log_audit.handle_command("log-audit", ["bogus"])

    assert refusal.value.verb == "log-audit"
    assert refusal.value.token == "bogus"
    assert "bogus" in str(refusal.value)


def test_handle_command_audit_subcommand(audit_world, monkeypatch, capsys):
    """'audit' subcommand calls scan_log_files and log_health_summary."""
    mock_watchdog = _ensure_watchdog_mock(monkeypatch)

    result = log_audit.handle_command("log-audit", ["audit"])
    assert result is True
    mock_watchdog.scan_log_files.assert_called_once()
    mock_watchdog.log_health_summary.assert_called_once()
    mock_watchdog.scan_branch_log_files.assert_called_once()
    mock_watchdog.branch_log_health_summary.assert_called_once()


def test_handle_command_enforce_calls_branch_enforce(audit_world, monkeypatch, capsys):
    """'enforce' subcommand calls both system and branch enforcement."""
    mock_watchdog = _ensure_watchdog_mock(monkeypatch)

    result = log_audit.handle_command("log-audit", ["enforce"])
    assert result is True
    mock_watchdog.enforce_log_limits.assert_called_once()
    mock_watchdog.enforce_branch_log_limits.assert_called_once()


def test_display_branch_audit_healthy(audit_world, monkeypatch, capsys):
    """_display_branch_audit shows healthy status when no unbounded files."""
    files = [
        {
            "name": "client.log",
            "branch": "backup",
            "lines": 200,
            "size_kb": 40.0,
            "size_mb": 0.04,
            "has_rotation": True,
            "status": "ok",
        },
    ]
    summary = {
        "total_files": 1,
        "oversized_count": 0,
        "critical_count": 0,
        "total_size_mb": 0.04,
        "largest_file": "backup/client.log",
        "largest_size_mb": 0.04,
        "healthy": True,
    }

    log_audit._display_branch_audit(files, summary)
    calls = capsys.readouterr().out.splitlines()
    assert any("HEALTHY" in c for c in calls)


def test_display_branch_audit_critical(audit_world, monkeypatch, capsys):
    """_display_branch_audit shows critical unbounded .jsonl files."""
    files = [
        {
            "name": "engine.jsonl",
            "branch": "hooks",
            "lines": 200000,
            "size_kb": 64512.0,
            "size_mb": 63.0,
            "has_rotation": False,
            "status": "critical",
            "path": "/fake/hooks/logs/engine.jsonl",
        },
    ]
    summary = {
        "total_files": 1,
        "oversized_count": 1,
        "critical_count": 1,
        "total_size_mb": 63.0,
        "largest_file": "hooks/engine.jsonl",
        "largest_size_mb": 63.0,
        "healthy": False,
    }

    log_audit._display_branch_audit(files, summary)
    calls = capsys.readouterr().out.splitlines()
    assert any("engine.jsonl" in c for c in calls)
    assert any("hooks" in c for c in calls)
    assert any("unrotated" in c for c in calls)
    audit_world.error.assert_called()
