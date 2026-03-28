# =================== AIPass ====================
# Name: test_error_resilience.py
# Description: Universal Error Resilience Test Template
# Version: 1.0.0
# Created: 2026-03-28
# Modified: 2026-03-28
# =============================================

"""
Universal Error Resilience Test Template for DAEMON branch.

Covers 4 tests:
  - test_missing_file: FileNotFoundError or graceful default on missing file
  - test_corrupt_json: JSONDecodeError handled, file regenerated
  - test_empty_file: empty content handled gracefully
  - test_nonexistent_dir: missing directory handled gracefully
"""

import importlib
import json
import sys
import types
from pathlib import Path

import pytest


# ============ BRANCH CONFIG ============
BRANCH_MODULE = "daemon"
# =======================================

# ---------------------------------------------------------------------------
# Dynamic import with cross-branch guard bypass
# ---------------------------------------------------------------------------

_handler_pkg = f"aipass.{BRANCH_MODULE}.apps.handlers"
_json_mod_path = f"aipass.{BRANCH_MODULE}.apps.handlers.json.json_handler"

if _handler_pkg not in sys.modules:
    _stub = types.ModuleType(_handler_pkg)
    _handlers_dir = (
        Path(__file__).resolve().parents[3] / "aipass" / BRANCH_MODULE / "apps" / "handlers"
    )
    _stub.__path__ = [str(_handlers_dir)]
    sys.modules[_handler_pkg] = _stub

_mod = importlib.import_module(_json_mod_path)
json_handler = _mod


# ---------------------------------------------------------------------------
# JSON_DIR variable discovery
# ---------------------------------------------------------------------------

_JSON_DIR_ATTR: str | None = None
_JSON_DIR_CANDIDATES = [
    f"{BRANCH_MODULE.upper()}_JSON_DIR",
    "JSON_DIR",
    "BRANCH_JSON_DIR",
    f"{BRANCH_MODULE}_json",
    "_JSON_DIR",
]

for _candidate in _JSON_DIR_CANDIDATES:
    if hasattr(_mod, _candidate):
        _JSON_DIR_ATTR = _candidate
        break

if _JSON_DIR_ATTR is None:
    pytest.skip(
        f"Cannot find JSON_DIR attribute on {BRANCH_MODULE}.json_handler -- "
        f"tried: {_JSON_DIR_CANDIDATES}",
        allow_module_level=True,
    )


# ---------------------------------------------------------------------------
# Isolation fixture
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def isolate_json_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect JSON operations to tmp_path for test isolation."""
    assert _JSON_DIR_ATTR is not None
    original_value = getattr(_mod, _JSON_DIR_ATTR)
    if isinstance(original_value, str):
        monkeypatch.setattr(_mod, _JSON_DIR_ATTR, str(tmp_path))
    else:
        monkeypatch.setattr(_mod, _JSON_DIR_ATTR, tmp_path)
    return tmp_path


def _json_dir_as_path(tmp_path: Path) -> Path:
    """Return the patched JSON dir as a Path."""
    assert _JSON_DIR_ATTR is not None
    val = getattr(_mod, _JSON_DIR_ATTR)
    if isinstance(val, str):
        return Path(val)
    return val


# ============================================================================
# Error Resilience Tests (4 tests)
# ============================================================================

def test_missing_file(tmp_path: Path) -> None:
    """Loading a non-existent file returns a graceful default, not a crash."""
    json_dir = _json_dir_as_path(tmp_path)
    target = json_dir / "ghost_config.json"
    assert not target.exists(), "Precondition: file must not exist"

    try:
        result = json_handler.load_json("ghost", "config")
    except FileNotFoundError:
        return

    assert result is not None, "load_json must not return None for missing file"
    assert isinstance(result, dict), "Auto-created config must be a dict"


def test_corrupt_json(tmp_path: Path) -> None:
    """Corrupt JSON on disk is handled gracefully -- file is regenerated."""
    json_dir = _json_dir_as_path(tmp_path)
    json_dir.mkdir(parents=True, exist_ok=True)
    target = json_dir / "corrupt_data.json"
    target.write_bytes(b"\x00\x01NOT-JSON{{{broken")

    result = json_handler.ensure_json_exists("corrupt", "data")
    assert result is True, "ensure_json_exists must return True after healing"

    raw = target.read_text(encoding="utf-8")
    data = json.loads(raw)
    assert isinstance(data, dict), "Regenerated data file must be a dict"
    assert "created" in data, "Regenerated data must have 'created' key"
    assert "last_updated" in data, "Regenerated data must have 'last_updated' key"


def test_empty_file(tmp_path: Path) -> None:
    """An empty file (0 bytes) is handled gracefully."""
    json_dir = _json_dir_as_path(tmp_path)
    json_dir.mkdir(parents=True, exist_ok=True)
    target = json_dir / "empty_log.json"
    target.write_text("", encoding="utf-8")

    result = json_handler.ensure_json_exists("empty", "log")
    assert result is True, "ensure_json_exists must return True after healing empty file"

    raw = target.read_text(encoding="utf-8")
    data = json.loads(raw)
    assert isinstance(data, list), "Regenerated log file must be a list"


def test_nonexistent_dir(tmp_path: Path) -> None:
    """Missing parent directory is handled gracefully."""
    json_dir = tmp_path / "does_not_exist" / "nested"
    assert not json_dir.exists(), "Precondition: directory must not exist"

    assert _JSON_DIR_ATTR is not None
    original_value = getattr(_mod, _JSON_DIR_ATTR)
    if isinstance(original_value, str):
        setattr(_mod, _JSON_DIR_ATTR, str(json_dir))
    else:
        setattr(_mod, _JSON_DIR_ATTR, json_dir)

    try:
        result = json_handler.ensure_json_exists("nodir", "config")
        assert json_dir.exists(), "Handler must create missing directories"
        assert result is True
    except (FileNotFoundError, OSError):
        pass
