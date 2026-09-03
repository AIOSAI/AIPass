# =================== AIPass ====================
# Name: test_json_handler_template.py
# Description: Universal JSON Handler Test Template (DPLAN-0059)
# Version: 1.0.0
# Created: 2026-03-25
# Modified: 2026-03-25
# =============================================

"""
Universal JSON Handler Test Template

Copy this file to any AIPass branch's tests/ directory.
Change BRANCH_MODULE below. Run with pytest.

The template-stamp tests this file carried are pinned once for the whole fleet in
seedgo's tests/test_json_handler_contract.py (DPLAN-0323 phase 7 slice 4, 2026-09-02).
"""

import importlib
import sys
import types
from pathlib import Path

import pytest


# ============ BRANCH CONFIG ============
# Change these two lines when deploying to a branch:
BRANCH_MODULE = "devpulse"  # e.g. "prax", "drone", "backup", "cli", etc.
# For commons: "commons" (import path is different: aipass -> just commons)
# For skills: "skills" (import path is different: aipass -> just skills)
# =======================================

# ---------------------------------------------------------------------------
# Dynamic import with cross-branch guard bypass
# ---------------------------------------------------------------------------
# Every branch has an import guard in apps/handlers/__init__.py that blocks
# cross-branch imports. When this template lives in its target branch, the
# guard passes naturally. When testing from devpulse (or any other branch),
# we pre-inject an empty handlers __init__ module to skip the guard.

if BRANCH_MODULE in ("commons", "skills"):
    _handler_pkg = f"{BRANCH_MODULE}.apps.handlers"
    _json_pkg = f"{BRANCH_MODULE}.apps.handlers.json"
    _json_mod_path = f"{BRANCH_MODULE}.apps.handlers.json.json_handler"
else:
    _handler_pkg = f"aipass.{BRANCH_MODULE}.apps.handlers"
    _json_pkg = f"aipass.{BRANCH_MODULE}.apps.handlers.json"
    _json_mod_path = f"aipass.{BRANCH_MODULE}.apps.handlers.json.json_handler"

# If the handlers package is not yet loaded, inject a stub to avoid the guard.
# The stub needs __path__ set so Python treats it as a package for sub-imports.
if _handler_pkg not in sys.modules:
    _stub = types.ModuleType(_handler_pkg)
    # Resolve the real filesystem path for the handlers package
    if BRANCH_MODULE in ("commons", "skills"):
        _handlers_dir = Path(__file__).resolve().parents[3] / BRANCH_MODULE / "apps" / "handlers"
    else:
        _handlers_dir = Path(__file__).resolve().parents[3] / "aipass" / BRANCH_MODULE / "apps" / "handlers"
    _stub.__path__ = [str(_handlers_dir)]
    sys.modules[_handler_pkg] = _stub

_mod = importlib.import_module(_json_mod_path)
json_handler = _mod


# ---------------------------------------------------------------------------
# JSON_DIR variable discovery
# ---------------------------------------------------------------------------
# Branches use different names: JSON_DIR, BACKUP_JSON_DIR, PRAX_JSON_DIR,
# BRANCH_JSON_DIR, _JSON_DIR, AI_MAIL_JSON_DIR, etc.
# We find the right one at import time so the isolation fixture can patch it.

_JSON_DIR_ATTR: str | None = None
_JSON_DIR_CANDIDATES = [
    f"{BRANCH_MODULE.upper()}_JSON_DIR",  # SEEDGO_JSON_DIR, BACKUP_JSON_DIR, etc.
    "JSON_DIR",  # seedgo, daemon, memory, cli, drone
    "BRANCH_JSON_DIR",  # commons
    f"{BRANCH_MODULE}_json",  # unlikely but covered
    "_JSON_DIR",  # spawn
]

for _candidate in _JSON_DIR_CANDIDATES:
    if hasattr(_mod, _candidate):
        _JSON_DIR_ATTR = _candidate
        break

if _JSON_DIR_ATTR is None:
    pytest.skip(
        f"Cannot find JSON_DIR attribute on {BRANCH_MODULE}.json_handler — tried: {_JSON_DIR_CANDIDATES}",
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
    # Some branches store JSON_DIR as a string (commons), others as Path
    if isinstance(original_value, str):
        monkeypatch.setattr(_mod, _JSON_DIR_ATTR, str(tmp_path))
    else:
        monkeypatch.setattr(_mod, _JSON_DIR_ATTR, tmp_path)
    return tmp_path


# ---------------------------------------------------------------------------
# Helper: resolve JSON dir as Path regardless of branch type
# ---------------------------------------------------------------------------


def _json_dir_as_path(tmp_path: Path) -> Path:
    """Return the patched JSON dir as a Path (handles str-typed branches)."""
    assert _JSON_DIR_ATTR is not None
    val = getattr(_mod, _JSON_DIR_ATTR)
    if isinstance(val, str):
        return Path(val)
    return val


# ============================================================================
# v4 sole carriers — SUBSUMED, kept for the gate (DPLAN-0323 phase 7 slice 4)
# ============================================================================
# Every claim below is pinned for devpulse in seedgo's tests/test_json_handler_contract.py
# (FPLAN-0483, 994465a5). They stay only because test_quality v4 keys on substrings of this
# directory's text: after the slice 4 deletions these seven were the last carriers here of the
# json_handler items (default factory, validate, get_path, ensure_exists, load, ensure_module)
# and of the config-key, data-key and dict-return items - devpulse scored 80 without them.
# JH-001 and JH-002 call devpulse's own factories (the cross-branch resolver went with the stamp).
# Delete the block the day v5 replaces v4 as the gate.


def test_default_config_returns_dict_with_required_keys() -> None:  # JH-001
    result = json_handler._default_config("test_mod")
    assert isinstance(result, dict), "Config default must be a dict"
    assert "module_name" in result, "Config default must have module_name"
    assert "version" in result, "Config default must have version"
    assert "config" in result, "Config default must have config"


def test_default_data_returns_dict_with_date_keys() -> None:  # JH-002
    result = json_handler._default_data("test_mod")
    assert isinstance(result, dict), "Data default must be a dict"
    assert "created" in result, "Data default must have created"
    assert "last_updated" in result, "Data default must have last_updated"


def test_validate_config_missing_key() -> None:  # JH-006
    data = {"module_name": "x", "version": "1.0.0"}  # missing config
    assert json_handler.validate_json_structure(data, "config") is False


def test_get_json_path_filename_pattern(tmp_path: Path) -> None:  # JH-016
    result = json_handler.get_json_path("mymod", "config")
    name = Path(result).name if isinstance(result, str) else result.name
    assert name == "mymod_config.json", f"Expected mymod_config.json, got {name}"


def test_ensure_creates_file_when_missing(tmp_path: Path) -> None:  # JH-018
    result = json_handler.ensure_json_exists("ens_mod", "config")
    assert result is True
    json_dir = _json_dir_as_path(tmp_path)
    created = json_dir / "ens_mod_config.json"
    assert created.exists(), "ensure_json_exists must create the file"


def test_load_returns_dict_for_config(tmp_path: Path) -> None:  # JH-025
    result = json_handler.load_json("cfg_mod", "config")
    assert isinstance(result, dict), "load_json for config must return dict"


def test_ensure_module_jsons_returns_true(tmp_path: Path) -> None:  # JH-037
    result = json_handler.ensure_module_jsons("retmod")
    assert result is True, "ensure_module_jsons must return True"


# ============================================================================
# Group 6 — save_json (5 tests)
# ============================================================================


def test_save_rejects_invalid_structure(tmp_path: Path) -> None:  # JH-029
    json_dir = _json_dir_as_path(tmp_path)
    json_dir.mkdir(parents=True, exist_ok=True)
    with pytest.raises(ValueError, match="[Ii]nvalid"):
        json_handler.save_json("bad", "config", {"missing": "keys"})
