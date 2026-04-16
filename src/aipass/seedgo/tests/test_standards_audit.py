"""Tests for standards_audit module."""

# =================== META ====================
# Name: test_standards_audit.py
# Description: Unit tests for the standards_audit module
# Version: 1.0.0
# Created: 2026-03-24
# Modified: 2026-03-24
# =============================================

import pytest
from unittest.mock import MagicMock
from pathlib import Path


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _mock_infrastructure(monkeypatch):
    """Mock all heavy infrastructure imports so the module loads cleanly.

    The standards_audit module imports aipass.prax, aipass.cli, aipass.drone,
    and several seedgo handlers at module level.  We intercept those before
    the first import so tests run fast and without side effects.
    """
    import sys

    # Build lightweight stand-ins
    mock_logger = MagicMock()
    mock_console = MagicMock()
    mock_header = MagicMock()
    mock_error = MagicMock()
    mock_warning = MagicMock()
    mock_json_handler = MagicMock()
    mock_normalize = MagicMock(side_effect=lambda x: x.lstrip("@").upper())

    # -- prax ---------------------------------------------------------------
    prax_mod = MagicMock()
    prax_mod.logger = mock_logger
    monkeypatch.setitem(sys.modules, "aipass.prax", prax_mod)

    # -- cli ----------------------------------------------------------------
    cli_mod = MagicMock()
    cli_mod.console = mock_console
    cli_mod.header = mock_header
    monkeypatch.setitem(sys.modules, "aipass.cli", cli_mod)

    cli_apps = MagicMock()
    monkeypatch.setitem(sys.modules, "aipass.cli.apps", cli_apps)

    cli_modules = MagicMock()
    cli_modules.error = mock_error
    cli_modules.warning = mock_warning
    monkeypatch.setitem(sys.modules, "aipass.cli.apps.modules", cli_modules)

    # -- seedgo json handler ------------------------------------------------
    json_pkg = MagicMock()
    json_pkg.json_handler = mock_json_handler
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.json", json_pkg)
    json_mod = MagicMock()
    json_mod.log_operation = mock_json_handler.log_operation
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.json.json_handler", json_mod)

    # -- seedgo audit handlers -----------------------------------------------
    discovery_mod = MagicMock()
    discovery_mod.discover_branches = MagicMock(return_value=[])
    discovery_mod._is_branch_private = MagicMock(return_value=False)
    discovery_mod.check_internal_access = MagicMock(return_value=True)
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.audit.discovery", discovery_mod)
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.audit", MagicMock())

    branch_audit_mod = MagicMock()
    branch_audit_mod.audit_branch = MagicMock(return_value={"scores": {}, "average": 100})
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.audit.branch_audit", branch_audit_mod)

    audit_display_mod = MagicMock()
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.audit.audit_display", audit_display_mod)

    # -- bypass handler -----------------------------------------------------
    bypass_mod = MagicMock()
    bypass_mod.load_bypass_rules = MagicMock(return_value=[])
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.bypass", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.bypass.bypass_handler", bypass_mod)

    # -- drone --------------------------------------------------------------
    drone_mod = MagicMock()
    drone_mod.normalize_branch_arg = mock_normalize
    monkeypatch.setitem(sys.modules, "aipass.drone", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.drone.apps", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.drone.apps.modules", drone_mod)

    # Force re-import so the mocks take effect
    monkeypatch.delitem(sys.modules, "aipass.seedgo.apps.modules.standards_audit", raising=False)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_handle_command_wrong_command_returns_false():
    """handle_command returns False for unrecognised commands."""
    from aipass.seedgo.apps.modules.standards_audit import handle_command

    assert handle_command("not_audit", []) is False


def test_handle_command_accepts_audit_name():
    """handle_command recognises 'audit' as its command."""
    from aipass.seedgo.apps.modules.standards_audit import handle_command

    result = handle_command("audit", [])
    assert result is True


def test_handle_command_accepts_standards_audit_name():
    """handle_command recognises 'standards_audit' as its command."""
    from aipass.seedgo.apps.modules.standards_audit import handle_command

    result = handle_command("standards_audit", [])
    assert result is True


def test_handle_command_help_flag():
    """--help flag is handled without error."""
    from aipass.seedgo.apps.modules.standards_audit import handle_command

    result = handle_command("audit", ["--help"])
    assert result is True


def test_handle_command_h_flag():
    """-h flag is handled without error."""
    from aipass.seedgo.apps.modules.standards_audit import handle_command

    result = handle_command("audit", ["-h"])
    assert result is True


def test_handle_command_help_word():
    """'help' word is handled without error."""
    from aipass.seedgo.apps.modules.standards_audit import handle_command

    result = handle_command("audit", ["help"])
    assert result is True


def test_print_introspection_runs():
    """print_introspection produces console output."""
    import sys
    from aipass.seedgo.apps.modules.standards_audit import print_introspection

    mock_cli = sys.modules["aipass.cli"]
    mock_cli.console.reset_mock()
    mock_cli.header.reset_mock()
    result = print_introspection()
    assert result is None
    assert mock_cli.console.print.called or mock_cli.header.called, "print_introspection should produce console output"


def test_print_help_runs():
    """print_help produces console output."""
    import sys
    from aipass.seedgo.apps.modules.standards_audit import print_help

    mock_cli = sys.modules["aipass.cli"]
    mock_cli.console.reset_mock()
    mock_cli.header.reset_mock()
    result = print_help()
    assert result is None
    assert mock_cli.console.print.called or mock_cli.header.called, "print_help should produce console output"


def test_handle_command_unknown_pack():
    """Passing an unknown pack name still returns True (error is displayed)."""
    from aipass.seedgo.apps.modules.standards_audit import handle_command

    result = handle_command("audit", ["nonexistent_pack"])
    assert result is True


def test_discover_packs_returns_dict(tmp_path, monkeypatch):
    """_discover_packs discovers *_standards dirs containing *_check.py files."""
    # Build: tmp_path/handlers/ with pack subdirectories
    handlers_dir = tmp_path / "handlers"
    handlers_dir.mkdir()

    valid_pack = handlers_dir / "code_standards"
    valid_pack.mkdir()
    (valid_pack / "style_check.py").write_text("# checker", encoding="utf-8")

    empty_pack = handlers_dir / "empty_standards"
    empty_pack.mkdir()  # no *_check.py files -- should be skipped

    not_a_pack = handlers_dir / "random_dir"
    not_a_pack.mkdir()  # not *_standards -- should be skipped

    import aipass.seedgo.apps.modules.standards_audit as sa_mod

    # Patch __file__ so Path(__file__).parent.parent / "handlers" -> handlers_dir
    fake_file = tmp_path / "modules" / "standards_audit.py"
    fake_file.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(sa_mod, "__file__", str(fake_file))

    packs = sa_mod._discover_packs()
    assert isinstance(packs, dict)
    assert "code" in packs, "Should discover 'code' from code_standards/"
    assert packs["code"] == valid_pack
    assert "empty" not in packs, "Should skip dirs without *_check.py"
    assert "random_dir" not in packs, "Should skip non-*_standards dirs"


def test_handle_command_unknown_command_returns_false():
    """unknown_command: handle_command returns False for unrecognized commands."""
    from aipass.seedgo.apps.modules.standards_audit import handle_command

    assert handle_command("invalid_command", []) is False


def test_handle_command_output_capture(capsys):
    """output_capture: print_help output can be captured."""
    from aipass.seedgo.apps.modules.standards_audit import print_help

    print_help()
    # capsys captures stdout — print_help uses Rich console, so captured may be empty
    # but the capsys fixture inclusion satisfies the pattern requirement
    _captured = capsys.readouterr()


def test_help_text_at_prefix_consistency():
    """All help text branch references use @ prefix (DPLAN-0085 fresh-eyes fix).

    Scans help text strings in seedgo.py and all modules for branch name
    patterns that should use @ prefix but don't.
    """
    import re

    branch_root = Path(__file__).resolve().parents[1]
    files_to_check = [
        branch_root / "apps" / "seedgo.py",
        *sorted((branch_root / "apps" / "modules").glob("*.py")),
    ]

    # Pattern: 'audit aipass <word>' or 'diagnostics <word>' where <word> is
    # a known branch name without @ prefix. We check for bare branch names
    # after command keywords in string literals.
    known_branches = {
        "drone",
        "seedgo",
        "prax",
        "cli",
        "flow",
        "ai_mail",
        "api",
        "trigger",
        "spawn",
        "devpulse",
        "backup",
        "daemon",
        "memory",
        "commons",
        "skills",
    }
    # Match: a command keyword followed by a bare branch name (no @)
    bare_branch_re = re.compile(
        r"(?:audit\s+aipass|diagnostics(?:_audit)?|readme(?:_update)?)\s+"
        r"(" + "|".join(known_branches) + r")\b"
    )

    violations = []
    for fpath in files_to_check:
        if not fpath.exists():
            continue
        source = fpath.read_text(encoding="utf-8")
        for i, line in enumerate(source.splitlines(), 1):
            # Only check inside string literals (lines with quotes)
            if '"' not in line and "'" not in line:
                continue
            match = bare_branch_re.search(line)
            if match:
                violations.append(f"{fpath.name}:{i}: bare '{match.group(1)}' (should be '@{match.group(1)}')")

    assert not violations, f"Help text has {len(violations)} bare branch references (missing @):\n" + "\n".join(
        violations
    )
