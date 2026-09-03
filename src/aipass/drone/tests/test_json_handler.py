# =================== AIPass ====================
# Name: test_json_handler.py
# Description: Universal JSON Handler Test Template (DPLAN-0059)
# Version: 1.0.0
# Created: 2026-03-25
# Modified: 2026-03-27
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
BRANCH_MODULE = "drone"  # e.g. "prax", "drone", "backup", "cli", etc.
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
# Group 6 — save_json (5 tests)
# ============================================================================


def test_save_rejects_invalid_structure(tmp_path: Path) -> None:  # JH-029
    json_dir = _json_dir_as_path(tmp_path)
    json_dir.mkdir(parents=True, exist_ok=True)
    with pytest.raises(ValueError, match="[Ii]nvalid"):
        json_handler.save_json("bad", "config", {"missing": "keys"})


# ============================================================================
# Group 9 — Empty file resilience (4 tests)
# ============================================================================


def test_ensure_regenerates_empty_log_file(tmp_path: Path) -> None:  # JH-044
    """Empty log.json should be regenerated, not crash with JSONDecodeError."""
    json_dir = _json_dir_as_path(tmp_path)
    json_dir.mkdir(parents=True, exist_ok=True)
    target = json_dir / "empty_log.json"
    target.write_text("", encoding="utf-8")

    json_handler.ensure_json_exists("empty", "log")

    data = json.loads(target.read_text(encoding="utf-8"))
    assert isinstance(data, list), "Empty log file must be regenerated to valid list"


def test_ensure_regenerates_empty_config_file(tmp_path: Path) -> None:  # JH-045
    """Empty config.json should be regenerated, not crash."""
    json_dir = _json_dir_as_path(tmp_path)
    json_dir.mkdir(parents=True, exist_ok=True)
    target = json_dir / "empty_config.json"
    target.write_text("", encoding="utf-8")

    json_handler.ensure_json_exists("empty", "config")

    data = json.loads(target.read_text(encoding="utf-8"))
    assert "module_name" in data, "Empty config must be regenerated with correct structure"


def test_load_json_handles_empty_file(tmp_path: Path) -> None:  # JH-046
    """load_json on an empty file should return default, not crash."""
    json_dir = _json_dir_as_path(tmp_path)
    json_dir.mkdir(parents=True, exist_ok=True)
    target = json_dir / "empty2_log.json"
    target.write_text("", encoding="utf-8")

    result = json_handler.load_json("empty2", "log")
    assert isinstance(result, list), "load_json must return default list for empty log"


def test_log_operation_survives_empty_log_file(tmp_path: Path) -> None:  # JH-047
    """log_operation should succeed even if log.json is empty."""
    json_dir = _json_dir_as_path(tmp_path)
    json_dir.mkdir(parents=True, exist_ok=True)
    # Create valid config but empty log
    config_path = json_dir / "recover_config.json"
    config_path.write_text(
        json.dumps(
            {
                "module_name": "recover",
                "version": "1.0.0",
                "config": {"max_log_entries": 100},
                "created": "2026-01-01",
                "last_updated": "2026-01-01",
            }
        ),
        encoding="utf-8",
    )
    log_path = json_dir / "recover_log.json"
    log_path.write_text("", encoding="utf-8")

    result = json_handler.log_operation("test_op", {"key": "val"}, module_name="recover")
    assert result is True, "log_operation must succeed on empty log file"

    data = json.loads(log_path.read_text(encoding="utf-8"))
    assert len(data) == 1, "Should have exactly one log entry after recovery"
    assert data[0]["operation"] == "test_op"


# ===========================================================================
# 9. increment_counter
# ===========================================================================


class TestIncrementCounter:
    """Tests for increment_counter()."""

    def test_increment_creates_counter(self, tmp_path: Path) -> None:
        """Incrementing a non-existent counter creates it at the given amount."""
        json_handler.ensure_module_jsons("incr_test")
        result = json_handler.increment_counter("incr_test", "hits")
        assert result is True
        data = json_handler.load_json("incr_test", "data")
        assert data["hits"] == 1

    def test_increment_adds_to_existing(self, tmp_path: Path) -> None:
        """Incrementing an existing counter adds to its current value."""
        json_handler.ensure_module_jsons("incr_test2")
        json_handler.increment_counter("incr_test2", "hits")
        json_handler.increment_counter("incr_test2", "hits")
        json_handler.increment_counter("incr_test2", "hits", amount=5)
        data = json_handler.load_json("incr_test2", "data")
        assert data["hits"] == 7

    def test_increment_custom_amount(self, tmp_path: Path) -> None:
        """Custom amount parameter is respected."""
        json_handler.ensure_module_jsons("incr_test3")
        result = json_handler.increment_counter("incr_test3", "visits", amount=42)
        assert result is True
        data = json_handler.load_json("incr_test3", "data")
        assert data["visits"] == 42

    def test_increment_returns_false_on_load_failure(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Returns False when data file cannot be loaded."""
        json_handler.ensure_module_jsons("incr_fail")
        monkeypatch.setattr(json_handler, "load_json", lambda *a, **kw: None)
        result = json_handler.increment_counter("incr_fail", "hits")
        assert result is False


# ===========================================================================
# 10. update_data_metrics
# ===========================================================================


class TestUpdateDataMetrics:
    """Tests for update_data_metrics()."""

    def test_update_single_metric(self, tmp_path: Path) -> None:
        """Updating a single metric writes it to the data file."""
        json_handler.ensure_module_jsons("metric_test")
        result = json_handler.update_data_metrics("metric_test", uptime=99.5)
        assert result is True
        data = json_handler.load_json("metric_test", "data")
        assert data["uptime"] == 99.5

    def test_update_multiple_metrics(self, tmp_path: Path) -> None:
        """Multiple keyword arguments are all written."""
        json_handler.ensure_module_jsons("metric_test2")
        json_handler.update_data_metrics("metric_test2", cpu=80, memory=60, disk=45)
        data = json_handler.load_json("metric_test2", "data")
        assert data["cpu"] == 80
        assert data["memory"] == 60
        assert data["disk"] == 45

    def test_update_overwrites_existing(self, tmp_path: Path) -> None:
        """Existing keys are overwritten by new values."""
        json_handler.ensure_module_jsons("metric_test3")
        json_handler.update_data_metrics("metric_test3", score=10)
        json_handler.update_data_metrics("metric_test3", score=20)
        data = json_handler.load_json("metric_test3", "data")
        assert data["score"] == 20

    def test_update_returns_false_on_load_failure(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Returns False when data file cannot be loaded."""
        json_handler.ensure_module_jsons("metric_fail")
        monkeypatch.setattr(json_handler, "load_json", lambda *a, **kw: None)
        result = json_handler.update_data_metrics("metric_fail", x=1)
        assert result is False
