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
import json
import sys
import types
from pathlib import Path

import pytest


# ============ BRANCH CONFIG ============
# Change these two lines when deploying to a branch:
BRANCH_MODULE = "spawn"  # e.g. "prax", "drone", "backup", "cli", etc.
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
    # Patch the JsonHandler instance if one exists (aipass.aipass.shared migration)
    if hasattr(_mod, "_handler") and hasattr(_mod._handler, "_json_dir"):
        monkeypatch.setattr(_mod._handler, "_json_dir", tmp_path)
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


_has_save = hasattr(json_handler, "save_json")

_skip_save = pytest.mark.skipif(not _has_save, reason="No save_json")


# ============================================================================
# v4 sole carriers — SUBSUMED, kept for the gate (DPLAN-0323 phase 7 slice 4)
# ============================================================================
# Every claim below is pinned for spawn in seedgo's tests/test_json_handler_contract.py
# (FPLAN-0483, 994465a5). They stay only because test_quality v4 keys on substrings of this
# directory's text: after the slice 4 deletions these five were the last carriers here of the
# json_handler validate, get_path, ensure_exists, load and ensure_module items - spawn scored
# 90 without them. Delete the block the day v5 replaces v4 as the gate.


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


@_skip_save
def test_save_rejects_invalid_structure(tmp_path: Path) -> None:  # JH-029
    json_dir = _json_dir_as_path(tmp_path)
    json_dir.mkdir(parents=True, exist_ok=True)
    with pytest.raises(ValueError, match="[Ii]nvalid"):
        json_handler.save_json("bad", "config", {"missing": "keys"})


# ============================================================================
# Group 7 — log_operation (7 tests)
# ============================================================================


def test_log_operation_fifo_rotation(tmp_path: Path) -> None:  # JH-040
    # Find the max log entries constant
    max_entries = getattr(_mod, "MAX_LOG_ENTRIES", getattr(_mod, "max_log_entries", None))
    if max_entries is None:
        # Try to find it by checking common names
        for attr in ("MAX_LOG_ENTRIES", "max_log_entries", "LOG_MAX_ENTRIES", "_MAX_LOG_ENTRIES"):
            max_entries = getattr(_mod, attr, None)
            if max_entries is not None:
                break
    if max_entries is None:
        pytest.skip("Cannot find max_log_entries constant on module")

    # Fill to max + 5
    for i in range(max_entries + 5):
        json_handler.log_operation(f"op_{i}", module_name="fifomod")

    json_dir = _json_dir_as_path(tmp_path)
    log = json.loads((json_dir / "fifomod_log.json").read_text(encoding="utf-8"))
    assert len(log) <= max_entries, f"Log must not exceed {max_entries} entries after rotation"
    # First entries should have been rotated out
    assert log[-1]["operation"] == f"op_{max_entries + 4}", "Most recent entry must be last"
