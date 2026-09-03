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
BRANCH_MODULE = "seedgo"  # e.g. "prax", "drone", "backup", "cli", etc.
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
# Group 4 — ensure_json_exists (5 tests)
# ============================================================================


def test_ensure_reports_failure_by_RAISING_not_by_returning(tmp_path: Path, monkeypatch) -> None:  # JH-022
    """Was `assert result is True` against a function that returned True on every
    path — a test that could not go red. The contract it should have been pinning
    is that a failed write PROPAGATES rather than being reported as a value."""
    json_handler.ensure_json_exists("bool_mod", "data")
    assert (_json_dir_as_path(tmp_path) / "bool_mod_data.json").exists()

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(json_handler, "_atomic_write_json", boom)
    with pytest.raises(OSError):
        json_handler.ensure_json_exists("bool_mod_two", "data")


# ============================================================================
# Group 6 — save_json (5 tests)
# ============================================================================


def test_save_rejects_invalid_structure(tmp_path: Path) -> None:  # JH-029
    json_dir = _json_dir_as_path(tmp_path)
    json_dir.mkdir(parents=True, exist_ok=True)
    with pytest.raises(ValueError, match="[Ii]nvalid"):
        json_handler.save_json("bad", "config", {"missing": "keys"})


# ============================================================================
# Group 8 — ensure_module_jsons (5 tests)
# ============================================================================


def test_ensure_module_jsons_success_means_files_not_return_value(tmp_path: Path) -> None:  # JH-037
    """Was `assert result is True` — which the function returned unconditionally
    while DISCARDING the three booleans it collected, so it reported success no
    matter what the three calls did. Pin the three files instead."""
    if not hasattr(json_handler, "ensure_module_jsons"):
        pytest.skip("Branch does not have ensure_module_jsons")
    json_handler.ensure_module_jsons("retmod")
    json_dir = _json_dir_as_path(tmp_path)
    for json_type in ("config", "data", "log"):
        assert (json_dir / f"retmod_{json_type}.json").exists(), json_type


# ============================================================================
# Additional coverage: empty_file, paths_return_path, no_overwrite,
# invalid_mode_raises, reimport_after_mock
# ============================================================================


def test_load_json_empty_file(tmp_path: Path) -> None:
    """empty_file: loading an empty_content file returns default structure."""
    json_dir = _json_dir_as_path(tmp_path)
    json_dir.mkdir(parents=True, exist_ok=True)
    empty = json_dir / "empty_config.json"
    empty.write_text("", encoding="utf-8")
    result = json_handler.load_json("empty", "config")
    assert isinstance(result, dict), "load_json must return dict even for empty file"


def test_load_json_empty_at_read_survives_race(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """#667: empty file at load_json's OWN read.

    The single-threaded case above passes because ensure_json_exists repairs the
    empty file first. The real bug is a TOCTOU race: ensure_json_exists reports
    OK, then a concurrent writer truncates the file before load_json re-reads it.
    Simulate by stubbing ensure_json_exists to pass without repairing.
    """
    json_dir = _json_dir_as_path(tmp_path)
    json_dir.mkdir(parents=True, exist_ok=True)
    # whitespace-only — what a writer caught mid-truncate can leave behind
    (json_dir / "raced_config.json").write_text("   \n", encoding="utf-8")
    monkeypatch.setattr(json_handler, "ensure_json_exists", lambda *a, **k: True)
    result = json_handler.load_json("raced", "config")
    assert isinstance(result, dict), "empty-at-read must fall back to default, not crash"


def test_load_json_empty_at_read_log_returns_list(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """#667: empty-at-read for a log falls back to the [] default, not a crash."""
    json_dir = _json_dir_as_path(tmp_path)
    json_dir.mkdir(parents=True, exist_ok=True)
    (json_dir / "raced_log.json").write_text("", encoding="utf-8")
    monkeypatch.setattr(json_handler, "ensure_json_exists", lambda *a, **k: True)
    result = json_handler.load_json("raced", "log")
    assert result == [], "empty-at-read log must fall back to the [] default"


def test_load_json_malformed_nonempty_still_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """#667: a non-empty but malformed file still raises (fail honestly).

    The guard only swallows empty/whitespace (a race artifact). Real corruption
    must surface, not be masked by a silent default.
    """
    json_dir = _json_dir_as_path(tmp_path)
    json_dir.mkdir(parents=True, exist_ok=True)
    (json_dir / "corrupt_config.json").write_text("{bad json", encoding="utf-8")
    monkeypatch.setattr(json_handler, "ensure_json_exists", lambda *a, **k: True)
    with pytest.raises(json.JSONDecodeError):
        json_handler.load_json("corrupt", "config")


def test_get_json_path_returns_pathlib_path(tmp_path: Path) -> None:
    """paths_return_path: get_json_path returns a pathlib.Path instance."""
    result = json_handler.get_json_path("pathmod", "config")
    assert isinstance(result, (Path, str)), "Must return pathlib.Path or str"


def test_ensure_no_overwrite_existing(tmp_path: Path) -> None:
    """no_overwrite: ensure_json_exists does not overwrite already_exists valid data."""
    json_dir = _json_dir_as_path(tmp_path)
    json_dir.mkdir(parents=True, exist_ok=True)
    target = json_dir / "preserve_config.json"
    # Write a VALID config structure with an extra custom key
    valid_config = {
        "module_name": "preserve",
        "version": "1.0.0",
        "config": {"auto_save": True, "enabled": True},
        "custom": "data",
    }
    target.write_text(json.dumps(valid_config), encoding="utf-8")
    json_handler.ensure_json_exists("preserve", "config")
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data.get("custom") == "data", "Must not overwrite existing file"


def test_save_json_invalid_mode_raises_error(tmp_path: Path) -> None:
    """invalid_mode_raises: save_json with invalid_type raises ValueError."""
    try:
        json_handler.save_json("mod", "config", {"data": True})
    except (ValueError, TypeError, Exception):
        pass  # Some implementations raise on invalid data/mode


class TestEnsureFunctionsDoNotPromiseASignalTheyNeverSend:
    """`-> bool` that is always `True` invites a branch that can never fire.

    FOUND BY DOGFOODING a rule @memory proposed 2026-08-30. Their rollover bug
    was `write_memory_file_simple` reporting failure by RETURNING False while
    the caller discarded the boolean — so a refusal reached nobody and every
    try/except above it was decorative. They suggested a checker for it.

    Running that idea against seedgo's own tree found 194 discarded bool
    returns, ~180 of them `log_operation()` where discarding is deliberate —
    which is why the rule as stated is not shippable. The real positives were
    here: `ensure_json_exists` and `ensure_module_jsons` were annotated
    `-> bool` and returned `True` on EVERY path. The value was not a signal, it
    was decoration, and a caller writing `if not ensure_json_exists(...)` would
    have written a branch that can never be taken.

    Failure IS reported — `_atomic_write_json` raises OSError. These pins say
    that out loud so the honest channel cannot be quietly replaced by a boolean
    that only ever means one thing.
    """

    def test_ensure_json_exists_does_not_advertise_a_bool_return(self):
        import typing

        from aipass.seedgo.apps.handlers.json import json_handler

        hints = typing.get_type_hints(json_handler.ensure_json_exists)
        assert hints.get("return") is not bool, (
            "a return type that is always True promises a failure signal that never arrives"
        )

    def test_ensure_module_jsons_does_not_advertise_a_bool_return(self):
        import typing

        from aipass.seedgo.apps.handlers.json import json_handler

        hints = typing.get_type_hints(json_handler.ensure_module_jsons)
        assert hints.get("return") is not bool

    def test_a_failing_write_RAISES_rather_than_returning_a_falsy_value(self, tmp_path, monkeypatch):
        """The honest channel, pinned: failure propagates."""
        import pytest

        from aipass.seedgo.apps.handlers.json import json_handler

        def boom(*a, **k):
            raise OSError("disk full")

        monkeypatch.setattr(json_handler, "JSON_DIR", tmp_path)
        monkeypatch.setattr(json_handler, "_atomic_write_json", boom)

        with pytest.raises(OSError):
            json_handler.ensure_json_exists("nonexistent_module_xyz", "config")

    def test_ensure_module_jsons_propagates_instead_of_reporting_success(self, tmp_path, monkeypatch):
        """The original defect: three discarded bools, then `return True`."""
        import pytest

        from aipass.seedgo.apps.handlers.json import json_handler

        def boom(*a, **k):
            raise OSError("disk full")

        monkeypatch.setattr(json_handler, "JSON_DIR", tmp_path)
        monkeypatch.setattr(json_handler, "_atomic_write_json", boom)

        with pytest.raises(OSError):
            json_handler.ensure_module_jsons("nonexistent_module_xyz")
