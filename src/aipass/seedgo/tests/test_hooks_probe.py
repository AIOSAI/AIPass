"""Tests for the hook probe scripts and hooks module.

# =================== META ====================
# Name: test_hooks_probe.py
# Description: Tests for hook probe scripts and hooks seedgo module
# Version: 1.0.0
# Created: 2026-04-20
# Modified: 2026-04-20
# =============================================
"""

import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Helpers — probe script loader
# ---------------------------------------------------------------------------


def _find_repo_root() -> Path:
    """Walk up from this file to find the git repo root."""
    current = Path(__file__).resolve().parent
    for parent in (current, *current.parents):
        if (parent / ".git").exists():
            return parent
    return Path(__file__).resolve().parents[4]  # fallback


_PROBES_DIR = _find_repo_root() / ".claude" / "hooks" / "probes"

_PROBE_SCRIPTS = [
    "probe_pre_tool_use.py",
    "probe_post_tool_use.py",
    "probe_user_prompt_submit.py",
    "probe_subagent_stop.py",
    "probe_pre_compact.py",
    "probe_stop.py",
    "probe_notification.py",
]

_EVENT_NAMES = [
    "PreToolUse",
    "PostToolUse",
    "UserPromptSubmit",
    "SubagentStop",
    "PreCompact",
    "Stop",
    "Notification",
]


def _load_probe(script_name: str):
    """Import a probe script by filename via importlib (outside package)."""
    path = _PROBES_DIR / script_name
    if not path.exists():
        pytest.skip(f"Probe script not found: {path}")
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


# ---------------------------------------------------------------------------
# Fixtures — infrastructure mocks for hooks module
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _mock_hooks_infrastructure(monkeypatch):
    """Mock aipass infrastructure imports for hooks module tests."""
    mock_logger = MagicMock()
    mock_console = MagicMock()
    mock_warning = MagicMock()
    mock_json_handler = MagicMock()

    # -- prax ---------------------------------------------------------------
    prax_mod = MagicMock()
    prax_mod.logger = mock_logger
    monkeypatch.setitem(sys.modules, "aipass.prax", prax_mod)

    # -- cli ----------------------------------------------------------------
    cli_mod = MagicMock()
    cli_mod.console = mock_console
    monkeypatch.setitem(sys.modules, "aipass.cli", cli_mod)

    cli_apps = MagicMock()
    monkeypatch.setitem(sys.modules, "aipass.cli.apps", cli_apps)

    cli_modules = MagicMock()
    cli_modules.warning = mock_warning
    monkeypatch.setitem(sys.modules, "aipass.cli.apps.modules", cli_modules)

    # -- seedgo json handler ------------------------------------------------
    json_pkg = MagicMock()
    json_pkg.json_handler = mock_json_handler
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.json", json_pkg)
    json_mod = MagicMock()
    json_mod.log_operation = mock_json_handler.log_operation
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.json.json_handler", json_mod)

    # Force re-import of hooks module
    monkeypatch.delitem(sys.modules, "aipass.seedgo.apps.modules.hooks", raising=False)


# ---------------------------------------------------------------------------
# Tests — probe scripts: happy-path stdin
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("script_name,event_name", list(zip(_PROBE_SCRIPTS, _EVENT_NAMES)))
def test_probe_happy_path(script_name, event_name, tmp_path, monkeypatch):
    """Each probe writes a correctly-shaped entry to last_ping.jsonl."""
    import io

    log_file = tmp_path / "last_ping.jsonl"
    probe = _load_probe(script_name)
    monkeypatch.setattr(probe, "_LOG_FILE", log_file)

    payload = json.dumps(
        {
            "tool_name": "Read",
            "cwd": "/tmp/test_cwd",
            "session_id": "test-session-123",
        }
    )

    monkeypatch.setattr("sys.stdin", io.StringIO(payload))
    probe.main()

    assert log_file.exists(), f"{script_name} did not create log file"
    lines = [ln for ln in log_file.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 1, f"Expected 1 entry, got {len(lines)}"

    entry = json.loads(lines[0])
    assert entry["event"] == event_name
    assert entry["tool"] == "Read"
    assert entry["cwd"] == "/tmp/test_cwd"
    assert "timestamp" in entry
    assert "script_elapsed_ms" in entry
    assert isinstance(entry["script_elapsed_ms"], float)
    assert "agent_id" in entry
    assert "cli_version" in entry
    assert "env_has_claude_project_dir" in entry
    assert "env_has_aipass_home" in entry


@pytest.mark.parametrize("script_name,event_name", list(zip(_PROBE_SCRIPTS, _EVENT_NAMES)))
def test_probe_appends_not_overwrites(script_name, event_name, tmp_path, monkeypatch):
    """Each probe appends to an existing log file instead of overwriting."""
    import io

    log_file = tmp_path / "last_ping.jsonl"
    existing = json.dumps(
        {
            "event": "existing",
            "tool": "",
            "cwd": "/",
            "agent_id": "x",
            "timestamp": "2026-01-01T00:00:00Z",
            "script_elapsed_ms": 0.1,
            "cli_version": "0",
            "env_has_claude_project_dir": False,
            "env_has_aipass_home": False,
        }
    )
    log_file.write_text(existing + "\n", encoding="utf-8")

    probe = _load_probe(script_name)
    monkeypatch.setattr(probe, "_LOG_FILE", log_file)

    monkeypatch.setattr("sys.stdin", io.StringIO("{}"))
    probe.main()

    lines = [ln for ln in log_file.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 2, "Probe should append, not overwrite"
    assert json.loads(lines[0])["event"] == "existing"
    assert json.loads(lines[1])["event"] == event_name


# ---------------------------------------------------------------------------
# Tests — probe scripts: malformed stdin
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("script_name,event_name", list(zip(_PROBE_SCRIPTS, _EVENT_NAMES)))
def test_probe_malformed_stdin_exits_cleanly(script_name, event_name, tmp_path, monkeypatch):
    """Each probe handles malformed stdin without raising an exception."""
    import io

    log_file = tmp_path / "last_ping.jsonl"
    probe = _load_probe(script_name)
    monkeypatch.setattr(probe, "_LOG_FILE", log_file)
    monkeypatch.setattr("sys.stdin", io.StringIO("not json at all !!!"))

    # main() returns normally on parse failure — no exception should propagate.
    # sys.exit(0) is only called from the __main__ block, not from main() itself.
    probe.main()  # must not raise


@pytest.mark.parametrize("script_name,event_name", list(zip(_PROBE_SCRIPTS, _EVENT_NAMES)))
def test_probe_empty_stdin_exits_cleanly(script_name, event_name, tmp_path, monkeypatch):
    """Each probe handles empty stdin without raising an exception."""
    import io

    log_file = tmp_path / "last_ping.jsonl"
    probe = _load_probe(script_name)
    monkeypatch.setattr(probe, "_LOG_FILE", log_file)
    monkeypatch.setattr("sys.stdin", io.StringIO(""))

    probe.main()  # must not raise


# ---------------------------------------------------------------------------
# Tests — probe env var extraction
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("script_name,event_name", list(zip(_PROBE_SCRIPTS, _EVENT_NAMES)))
def test_probe_reads_session_id_from_env(script_name, event_name, tmp_path, monkeypatch):
    """Probe picks up CLAUDE_CODE_SESSION_ID from environment."""
    import io

    log_file = tmp_path / "last_ping.jsonl"
    probe = _load_probe(script_name)
    monkeypatch.setattr(probe, "_LOG_FILE", log_file)
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sess-env-test-999")
    monkeypatch.delenv("CLAUDE_SESSION_ID", raising=False)

    monkeypatch.setattr("sys.stdin", io.StringIO("{}"))
    probe.main()

    lines = [ln for ln in log_file.read_text(encoding="utf-8").splitlines() if ln.strip()]
    entry = json.loads(lines[0])
    assert entry["agent_id"] == "sess-env-test-999"


@pytest.mark.parametrize("script_name,event_name", list(zip(_PROBE_SCRIPTS, _EVENT_NAMES)))
def test_probe_falls_back_to_claude_session_id(script_name, event_name, tmp_path, monkeypatch):
    """Probe falls back to CLAUDE_SESSION_ID when CLAUDE_CODE_SESSION_ID is absent."""
    import io

    log_file = tmp_path / "last_ping.jsonl"
    probe = _load_probe(script_name)
    monkeypatch.setattr(probe, "_LOG_FILE", log_file)
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    monkeypatch.setenv("CLAUDE_SESSION_ID", "fallback-session-42")

    monkeypatch.setattr("sys.stdin", io.StringIO("{}"))
    probe.main()

    lines = [ln for ln in log_file.read_text(encoding="utf-8").splitlines() if ln.strip()]
    entry = json.loads(lines[0])
    assert entry["agent_id"] == "fallback-session-42"


@pytest.mark.parametrize("script_name,event_name", list(zip(_PROBE_SCRIPTS, _EVENT_NAMES)))
def test_probe_unknown_agent_id_when_no_env(script_name, event_name, tmp_path, monkeypatch):
    """Probe uses 'unknown' when no session env vars are set."""
    import io

    log_file = tmp_path / "last_ping.jsonl"
    probe = _load_probe(script_name)
    monkeypatch.setattr(probe, "_LOG_FILE", log_file)
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    monkeypatch.delenv("CLAUDE_SESSION_ID", raising=False)

    monkeypatch.setattr("sys.stdin", io.StringIO("{}"))
    probe.main()

    lines = [ln for ln in log_file.read_text(encoding="utf-8").splitlines() if ln.strip()]
    entry = json.loads(lines[0])
    assert entry["agent_id"] == "unknown"


@pytest.mark.parametrize("script_name,event_name", list(zip(_PROBE_SCRIPTS, _EVENT_NAMES)))
def test_probe_env_has_aipass_home(script_name, event_name, tmp_path, monkeypatch):
    """Probe records env_has_aipass_home correctly."""
    import io

    log_file = tmp_path / "last_ping.jsonl"
    probe = _load_probe(script_name)
    monkeypatch.setattr(probe, "_LOG_FILE", log_file)
    monkeypatch.setenv("AIPASS_HOME", "/home/user/Projects/AIPass")

    monkeypatch.setattr("sys.stdin", io.StringIO("{}"))
    probe.main()

    lines = [ln for ln in log_file.read_text(encoding="utf-8").splitlines() if ln.strip()]
    entry = json.loads(lines[0])
    assert entry["env_has_aipass_home"] is True


# ---------------------------------------------------------------------------
# Tests — hooks module: handle_command routing
# ---------------------------------------------------------------------------


def test_handle_command_wrong_command_returns_false():
    """handle_command returns False for unrecognised commands."""
    from aipass.seedgo.apps.modules.hooks import handle_command

    assert handle_command("wrong_command", []) is False


def test_handle_command_no_args_calls_introspection():
    """No args triggers introspection (returns True)."""
    from aipass.seedgo.apps.modules.hooks import handle_command

    result = handle_command("hooks", [])
    assert result is True


def test_handle_command_help_flag():
    """--help flag is handled without error."""
    from aipass.seedgo.apps.modules.hooks import handle_command

    result = handle_command("hooks", ["--help"])
    assert result is True


def test_handle_command_probe_no_flags():
    """hooks probe with no extra flags calls display (returns True)."""
    from aipass.seedgo.apps.modules.hooks import handle_command

    result = handle_command("hooks", ["probe"])
    assert result is True


def test_handle_command_unknown_subcommand():
    """Unknown subcommand falls back to introspection (returns True)."""
    from aipass.seedgo.apps.modules.hooks import handle_command

    result = handle_command("hooks", ["nonexistent_subcommand"])
    assert result is True


# ---------------------------------------------------------------------------
# Tests — hooks module: probe display with mock data
# ---------------------------------------------------------------------------


def test_probe_display_renders_table(tmp_path):
    """_cmd_probe_display renders a Rich table without error given sample data."""
    entries = [
        {
            "event": "PreToolUse",
            "tool": "Bash",
            "cwd": "/tmp/test",
            "agent_id": "sess-abc",
            "timestamp": "2026-04-20T12:00:00.000Z",
            "script_elapsed_ms": 2.1,
            "cli_version": "1.0.0",
            "env_has_claude_project_dir": True,
            "env_has_aipass_home": False,
        },
        {
            "event": "PostToolUse",
            "tool": "Read",
            "cwd": "/tmp/test",
            "agent_id": "sess-abc",
            "timestamp": "2026-04-20T12:00:01.000Z",
            "script_elapsed_ms": 1.5,
            "cli_version": "1.0.0",
            "env_has_claude_project_dir": True,
            "env_has_aipass_home": True,
        },
    ]
    log_file = tmp_path / "last_ping.jsonl"
    with open(log_file, "w", encoding="utf-8") as fh:
        for e in entries:
            fh.write(json.dumps(e) + "\n")

    from aipass.seedgo.apps.modules.hooks import _cmd_probe_display

    _cmd_probe_display(log_path=log_file)


def test_probe_display_empty_log(tmp_path):
    """_cmd_probe_display handles missing log file gracefully."""
    from aipass.seedgo.apps.modules.hooks import _cmd_probe_display

    missing = tmp_path / "no_such_file.jsonl"
    _cmd_probe_display(log_path=missing)


def test_read_entries_skips_bad_lines(tmp_path):
    """_read_entries skips malformed lines and returns valid ones."""
    log_file = tmp_path / "last_ping.jsonl"
    good = json.dumps(
        {
            "event": "Stop",
            "tool": "",
            "cwd": "/",
            "agent_id": "x",
            "timestamp": "2026-04-20T00:00:00Z",
            "script_elapsed_ms": 1.0,
            "cli_version": "1",
            "env_has_claude_project_dir": False,
            "env_has_aipass_home": False,
        }
    )
    log_file.write_text(f"not json\n{good}\nalso not json\n", encoding="utf-8")

    from aipass.seedgo.apps.modules.hooks import _read_entries

    entries = _read_entries(log_path=log_file)
    assert len(entries) == 1
    assert entries[0]["event"] == "Stop"


def test_truncate_helper():
    """_truncate shortens long strings correctly."""
    from aipass.seedgo.apps.modules.hooks import _truncate

    assert _truncate("short", 20) == "short"
    assert _truncate("a" * 30, 10) == "a" * 7 + "..."
    assert len(_truncate("x" * 50, 15)) == 15


def test_entry_ts_parses_z_suffix():
    """_entry_ts handles ISO 8601 Z-suffix timestamps."""
    from aipass.seedgo.apps.modules.hooks import _entry_ts

    ts = _entry_ts({"timestamp": "2026-04-20T12:00:00.000000Z"})
    assert ts > 0


def test_entry_ts_returns_zero_on_bad_input():
    """_entry_ts returns 0.0 for unparseable timestamps."""
    from aipass.seedgo.apps.modules.hooks import _entry_ts

    assert _entry_ts({"timestamp": "not-a-date"}) == 0.0
    assert _entry_ts({}) == 0.0


# ---------------------------------------------------------------------------
# Tests — matrix builder
# ---------------------------------------------------------------------------


def test_build_matrix_rows_groups_correctly():
    """_build_matrix_rows groups entries by event and counts correctly."""
    entries = [
        {
            "event": "Stop",
            "env_has_claude_project_dir": True,
            "env_has_aipass_home": False,
            "agent_id": "a",
        },
        {
            "event": "Stop",
            "env_has_claude_project_dir": False,
            "env_has_aipass_home": False,
            "agent_id": "b",
        },
        {
            "event": "PreToolUse",
            "env_has_claude_project_dir": True,
            "env_has_aipass_home": True,
            "agent_id": "a",
        },
    ]

    from aipass.seedgo.apps.modules.hooks_probe import _build_matrix_rows

    rows, groups = _build_matrix_rows(entries)
    assert len(rows) == 2
    stop_row = next(r for r in rows if r["event"] == "Stop")
    assert stop_row["count"] == 2
    assert stop_row["project_dir_true"] == 1
    assert stop_row["project_dir_false"] == 1
    assert stop_row["unique_agents"] == 2


def test_probe_matrix_writes_report(tmp_path):
    """_cmd_probe_matrix creates the markdown report given sample data."""
    from aipass.seedgo.apps.modules.hooks_probe import _write_matrix_report

    entries = [
        {
            "event": "Stop",
            "tool": "",
            "cwd": "/tmp",
            "agent_id": "sess-1",
            "timestamp": "2026-04-20T10:00:00Z",
            "script_elapsed_ms": 1.2,
            "cli_version": "1.0",
            "env_has_claude_project_dir": False,
            "env_has_aipass_home": True,
        }
    ]
    matrix_rows = [
        {
            "event": "Stop",
            "count": 1,
            "project_dir_true": 0,
            "project_dir_false": 1,
            "aipass_home_true": 1,
            "aipass_home_false": 0,
            "unique_agents": 1,
        }
    ]
    report_path = tmp_path / "Q12_findings_2026-04-20.md"
    _write_matrix_report(report_path, matrix_rows, entries)

    assert report_path.exists()
    content = report_path.read_text(encoding="utf-8")
    assert "Stop" in content
    assert "Q12 Findings" in content
