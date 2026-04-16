"""Tests for the bypass handler directory (bypass_handler, ignore_handler)."""

# =================== META ====================
# Name: test_bypass.py
# Description: Unit tests for handlers/bypass/
# Version: 1.0.0
# Created: 2026-03-24
# Modified: 2026-03-24
# =============================================

import json
import pytest
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _mock_infrastructure(monkeypatch):
    """Mock heavy infrastructure imports for bypass handlers."""
    import sys

    mock_logger = MagicMock()
    mock_json_handler = MagicMock()
    mock_json_handler.log_operation = MagicMock(return_value=True)

    # -- prax ---------------------------------------------------------------
    prax_mod = MagicMock()
    prax_mod.logger = mock_logger
    monkeypatch.setitem(sys.modules, "aipass.prax", prax_mod)

    # -- seedgo json handler ------------------------------------------------
    json_pkg = MagicMock()
    json_pkg.json_handler = mock_json_handler
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.json", json_pkg)
    json_mod = MagicMock()
    json_mod.log_operation = mock_json_handler.log_operation
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.json.json_handler", json_mod)

    # Force re-imports
    for mod_name in [
        "aipass.seedgo.apps.handlers.bypass.bypass_handler",
        "aipass.seedgo.apps.handlers.bypass.ignore_handler",
    ]:
        monkeypatch.delitem(sys.modules, mod_name, raising=False)


# ---------------------------------------------------------------------------
# Tests -- bypass_handler.load_bypass_rules
# ---------------------------------------------------------------------------


def test_load_bypass_rules_from_file(tmp_path):
    """load_bypass_rules reads rules from .seedgo/bypass.json."""
    seedgo_dir = tmp_path / ".seedgo"
    seedgo_dir.mkdir()
    bypass_file = seedgo_dir / "bypass.json"
    bypass_data = {
        "metadata": {"version": "1.0.0", "created": "", "description": "test"},
        "bypass": [{"file": "apps/foo.py", "standard": "naming", "reason": "legacy"}],
        "notes": {},
    }
    bypass_file.write_text(json.dumps(bypass_data), encoding="utf-8")

    from aipass.seedgo.apps.handlers.bypass.bypass_handler import load_bypass_rules

    rules = load_bypass_rules(str(tmp_path))
    assert len(rules) == 1
    assert rules[0]["standard"] == "naming"


def test_load_bypass_rules_empty_when_no_rules(tmp_path):
    """load_bypass_rules returns empty list when bypass has no rules."""
    seedgo_dir = tmp_path / ".seedgo"
    seedgo_dir.mkdir()
    bypass_file = seedgo_dir / "bypass.json"
    bypass_data = {
        "metadata": {"version": "1.0.0", "created": "", "description": "test"},
        "bypass": [],
        "notes": {},
    }
    bypass_file.write_text(json.dumps(bypass_data), encoding="utf-8")

    from aipass.seedgo.apps.handlers.bypass.bypass_handler import load_bypass_rules

    rules = load_bypass_rules(str(tmp_path))
    assert rules == []


def test_load_bypass_rules_creates_config_if_missing(tmp_path):
    """load_bypass_rules creates .seedgo/bypass.json if it does not exist."""
    from aipass.seedgo.apps.handlers.bypass.bypass_handler import load_bypass_rules

    rules = load_bypass_rules(str(tmp_path))
    assert isinstance(rules, list)
    # Config should now exist
    assert (tmp_path / ".seedgo" / "bypass.json").exists()


# ---------------------------------------------------------------------------
# Tests -- bypass_handler.is_bypassed
# ---------------------------------------------------------------------------


def test_is_bypassed_matching_rule():
    """is_bypassed returns True when file and standard match a rule."""
    from aipass.seedgo.apps.handlers.bypass.bypass_handler import is_bypassed

    rules = [{"file": "apps/foo.py", "standard": "naming", "reason": "legacy"}]
    result = is_bypassed(
        file_path="/branch/apps/foo.py",
        branch_path="/branch",
        standard="naming",
        line=None,
        bypass_rules=rules,
    )
    assert result is True


def test_is_bypassed_no_match():
    """is_bypassed returns False when no rule matches."""
    from aipass.seedgo.apps.handlers.bypass.bypass_handler import is_bypassed

    rules = [{"file": "apps/foo.py", "standard": "naming", "reason": "legacy"}]
    result = is_bypassed(
        file_path="/branch/apps/bar.py",
        branch_path="/branch",
        standard="naming",
        line=None,
        bypass_rules=rules,
    )
    assert result is False


def test_is_bypassed_line_specific():
    """is_bypassed respects line-specific bypass rules."""
    from aipass.seedgo.apps.handlers.bypass.bypass_handler import is_bypassed

    rules = [{"file": "apps/foo.py", "standard": "cli", "lines": [10, 20], "reason": "circular"}]
    assert is_bypassed("/branch/apps/foo.py", "/branch", "cli", 10, rules) is True
    assert is_bypassed("/branch/apps/foo.py", "/branch", "cli", 99, rules) is False


def test_is_bypassed_empty_rules():
    """is_bypassed returns False with empty rules list."""
    from aipass.seedgo.apps.handlers.bypass.bypass_handler import is_bypassed

    assert is_bypassed("/branch/apps/foo.py", "/branch", "naming", None, []) is False


# ---------------------------------------------------------------------------
# Tests -- bypass_handler.ensure_seedgo_config
# ---------------------------------------------------------------------------


def test_ensure_seedgo_config_creates_dir(tmp_path):
    """ensure_seedgo_config creates .seedgo directory and bypass.json."""
    from aipass.seedgo.apps.handlers.bypass.bypass_handler import ensure_seedgo_config

    result = ensure_seedgo_config(str(tmp_path))
    assert result == tmp_path / ".seedgo" / "bypass.json"
    assert result.exists()


def test_ensure_seedgo_config_idempotent(tmp_path):
    """Calling ensure_seedgo_config twice does not corrupt the file."""
    from aipass.seedgo.apps.handlers.bypass.bypass_handler import ensure_seedgo_config

    ensure_seedgo_config(str(tmp_path))
    ensure_seedgo_config(str(tmp_path))
    bypass_file = tmp_path / ".seedgo" / "bypass.json"
    data = json.loads(bypass_file.read_text(encoding="utf-8"))
    assert "bypass" in data


# ---------------------------------------------------------------------------
# Tests -- ignore_handler
# ---------------------------------------------------------------------------


def test_get_audit_ignore_patterns_returns_list():
    """get_audit_ignore_patterns returns a list of strings."""
    from aipass.seedgo.apps.handlers.bypass.ignore_handler import get_audit_ignore_patterns

    patterns = get_audit_ignore_patterns()
    assert isinstance(patterns, list)
    assert all(isinstance(p, str) for p in patterns)


def test_get_template_ignore_patterns_returns_copy():
    """get_template_ignore_patterns returns a copy (not the original list)."""
    from aipass.seedgo.apps.handlers.bypass.ignore_handler import get_template_ignore_patterns

    a = get_template_ignore_patterns()
    b = get_template_ignore_patterns()
    assert a == b
    a.append("extra")
    assert a != get_template_ignore_patterns()


def test_get_deprecated_patterns_returns_dict():
    """get_deprecated_patterns returns a dict of string keys and string values."""
    from aipass.seedgo.apps.handlers.bypass.ignore_handler import get_deprecated_patterns

    patterns = get_deprecated_patterns()
    assert isinstance(patterns, dict)
    for key, value in patterns.items():
        assert isinstance(key, str)
        assert isinstance(value, str)
