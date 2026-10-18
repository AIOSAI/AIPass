# =================== AIPass ====================
# Name: test_log_audit.py
# Description: Unit tests for PRAX log_audit module
# Version: 1.3.0
# Created: 2026-03-24
# Modified: 2026-10-17
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

import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock

import pytest

from aipass.prax.apps.handlers.cli.arg_gate import UnknownArgument
from aipass.prax.apps.handlers.logging import log_watchdog
from aipass.prax.apps.modules import log_audit

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
    _stood_where_log_audit_looks(log_watchdog)
    return mock_watchdog


def _stood_where_log_audit_looks(module, modules=sys.modules):
    """Fail before the route runs when the stubbed module is not the one log_audit will find.

    log_audit imports the watchdog at call time, by name, through sys.modules. A raw
    pop of that entry in any earlier test would leave the stub on an orphan and send
    enforce or sweep to the real functions over the live system_logs.
    """
    if modules.get(module.__name__) is not module:
        pytest.fail(f"{module.__name__} in sys.modules is not the module the stub stands on")


def test_the_guard_fails_when_sys_modules_holds_another_watchdog():
    """A different object under the watchdog's name stops the test before any route.

    Proven on the test side only, in a modules mapping of its own: no product
    mutant is run here, because the far side truncates and deletes real logs.
    """
    name = log_watchdog.__name__
    with pytest.raises(pytest.fail.Exception, match="not the module the stub stands on"):
        _stood_where_log_audit_looks(log_watchdog, {name: ModuleType(name)})
    with pytest.raises(pytest.fail.Exception, match="not the module the stub stands on"):
        _stood_where_log_audit_looks(log_watchdog, {})
    _stood_where_log_audit_looks(log_watchdog, {name: log_watchdog})


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


_QUIET_SYSTEM = {
    "total_files": 0,
    "total_lines": 0,
    "largest_file": "",
    "largest_lines": 0,
    "healthy": True,
    "oversized_count": 0,
    "critical_count": 0,
}
_QUIET_BRANCH = {
    "total_files": 0,
    "oversized_count": 0,
    "critical_count": 0,
    "total_size_mb": 0,
    "largest_file": "",
    "largest_size_mb": 0,
    "healthy": True,
}


def _audit_through_command(monkeypatch, capsys, files=(), summary=None, branch_files=(), branch_summary=None):
    """Both displays through `log-audit audit`, the read-only route.

    enforce sits stubbed by _ensure_watchdog_mock and must stay uncalled; sweep is
    reachable only from its own subcommand. The side not under test is given a
    quiet, healthy world, so every line and every error() belongs to the other.
    """
    watchdog = _ensure_watchdog_mock(monkeypatch)
    watchdog.scan_log_files.return_value = list(files)
    watchdog.log_health_summary.return_value = summary or _QUIET_SYSTEM
    watchdog.scan_branch_log_files.return_value = list(branch_files)
    watchdog.branch_log_health_summary.return_value = branch_summary or _QUIET_BRANCH
    capsys.readouterr()

    assert log_audit.handle_command("log-audit", ["audit"]) is True

    watchdog.enforce_log_limits.assert_not_called()
    watchdog.enforce_branch_log_limits.assert_not_called()
    return capsys.readouterr().out.splitlines()


def test_display_audit_healthy(audit_world, monkeypatch, capsys):
    """The system display formats a healthy summary correctly."""
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

    calls = _audit_through_command(monkeypatch, capsys, files=files, summary=summary)

    assert "  Status: HEALTHY — all logs within limits" in calls
    assert "  Largest: system.log (200 lines)" in calls
    audit_world.error.assert_not_called()


def test_display_audit_oversized(audit_world, monkeypatch, capsys):
    """The system display shows oversized files when present."""
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

    calls = _audit_through_command(monkeypatch, capsys, files=files, summary=summary)

    assert "Oversized files:" in calls
    assert "  OVERSIZED error.log: 2,500 lines (200 KB)" in calls
    assert "  CRITICAL crash.log: 5,000 lines (400 KB)" in calls
    audit_world.error.assert_called_once_with("Status: 1 oversized, 1 critical")


def test_handle_command_unknown_subcommand(audit_world, monkeypatch, capsys):
    """An unknown subcommand is refused BY NAME; returning True would exit 0 and run `&& next-step`."""
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
    """The branch display shows healthy status when no unbounded files."""
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

    calls = _audit_through_command(monkeypatch, capsys, branch_files=files, branch_summary=summary)

    assert "  Status: HEALTHY — no unbounded files" in calls
    audit_world.error.assert_not_called()


def test_display_branch_audit_critical(audit_world, monkeypatch, capsys):
    """The branch display shows critical unbounded .jsonl files."""
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

    calls = _audit_through_command(monkeypatch, capsys, branch_files=files, branch_summary=summary)

    # The row is the branch, then the file; asserted as its two ends (no path string).
    rows = [c for c in calls if c.startswith("  CRITICAL ")]
    assert len(rows) == 1
    assert rows[0].startswith("  CRITICAL hooks")
    assert rows[0].endswith("engine.jsonl: 63.0 MB, 200,000 lines, unrotated")
    audit_world.error.assert_called_once_with("Status: 1 unbounded, 1 critical")
