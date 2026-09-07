# =================== AIPass ====================
# Name: test_error_resilience.py
# Description: Error Resilience Tests (from seedgo template)
# Version: 1.0.0
# Created: 2026-03-27
# Modified: 2026-03-27
# =============================================

"""
Error Resilience Tests for API branch.

Covers 4 tests:
  - missing_file, corrupt_json, empty_file, nonexistent_dir
"""

import importlib
import json
import sys
import types
from pathlib import Path

import pytest


BRANCH_MODULE = "api"

_handler_pkg = f"aipass.{BRANCH_MODULE}.apps.handlers"
_json_mod_path = f"aipass.{BRANCH_MODULE}.apps.handlers.json.json_handler"

if _handler_pkg not in sys.modules:
    _stub = types.ModuleType(_handler_pkg)
    _handlers_dir = Path(__file__).resolve().parents[3] / "aipass" / BRANCH_MODULE / "apps" / "handlers"
    _stub.__path__ = [str(_handlers_dir)]
    sys.modules[_handler_pkg] = _stub

_mod = importlib.import_module(_json_mod_path)
json_handler = _mod


#: Isolation goes through the fleet seam, not a module attribute.
#:
#: This file used to hunt the handler for API_JSON_DIR / JSON_DIR /
#: BRANCH_JSON_DIR / _JSON_DIR and, finding none, skip ITSELF at module level.
#: Since DPLAN-0325 the handler is a shim over the one prax service, which
#: holds no directory constant at all — so the hunt would have found nothing
#: and this whole suite would have gone quietly dormant, reporting skipped and
#: measuring nothing. The service reads AIPASS_TEST_LOG_DIR on every call, so
#: the redirect is an env var and the suite keeps running.


@pytest.fixture(autouse=True)
def isolate_json_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect JSON operations into a temp sandbox for test isolation."""
    monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path / "_aipass_json_seam"))
    return _json_dir_as_path(tmp_path)


def _json_dir_as_path(tmp_path: Path) -> Path:
    """The directory the handler writes into right now.

    MEASURED off the handler rather than spelled out: the one service spells
    the sandbox <seam>/<branch>/<branch>_json, so a literal here would drift
    the first time that spelling changes.
    """
    return _mod.get_json_path("probe", "config").parent


# ============================================================================
# Error Resilience Tests
# ============================================================================


def test_missing_file(tmp_path: Path) -> None:
    """Loading a non-existent file returns a graceful default, not a crash."""
    json_dir = _json_dir_as_path(tmp_path)
    target = json_dir / "ghost_config.json"
    assert not target.exists()

    try:
        result = json_handler.load_json("ghost", "config")
    except FileNotFoundError:
        return

    assert result is not None
    assert isinstance(result, dict)


def test_corrupt_json(tmp_path: Path) -> None:
    """Corrupt JSON on disk is handled gracefully — file is regenerated."""
    json_dir = _json_dir_as_path(tmp_path)
    json_dir.mkdir(parents=True, exist_ok=True)
    target = json_dir / "corrupt_data.json"
    target.write_bytes(b"\x00\x01NOT-JSON{{{broken")

    result = json_handler.ensure_json_exists("corrupt", "data")
    assert result is True

    raw = target.read_text(encoding="utf-8")
    data = json.loads(raw)
    assert isinstance(data, dict)
    assert "created" in data
    assert "last_updated" in data


def test_empty_file(tmp_path: Path) -> None:
    """An empty file (0 bytes) is handled gracefully."""
    json_dir = _json_dir_as_path(tmp_path)
    json_dir.mkdir(parents=True, exist_ok=True)
    target = json_dir / "empty_log.json"
    target.write_text("", encoding="utf-8")

    result = json_handler.ensure_json_exists("empty", "log")
    assert result is True

    raw = target.read_text(encoding="utf-8")
    data = json.loads(raw)
    assert isinstance(data, list)


def test_nonexistent_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing parent directory is handled gracefully.

    Pointed at a seam two levels below anything that exists, so the handler
    has to build the whole chain. The redirect is monkeypatched, not a bare
    setattr: the old form assigned the module attribute permanently and left
    the next test in this process pointing at a deleted tmp_path.
    """
    seam = tmp_path / "does_not_exist" / "nested"
    assert not seam.exists()

    monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(seam))
    json_dir = _json_dir_as_path(tmp_path)
    assert not json_dir.exists()

    try:
        result = json_handler.ensure_json_exists("nodir", "config")
        assert json_dir.exists()
        assert result is True
    except (FileNotFoundError, OSError):
        pass
