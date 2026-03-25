# =================== AIPass ====================
# Name: test_error_registry.py
# Description: Unit tests for the error_registry handler
# Version: 1.0.0
# Created: 2026-03-24
# Modified: 2026-03-24
# =============================================

"""Tests for the error_registry handler -- dedup engine, circuit breaker, backoff."""

import json
import time

import pytest
from unittest.mock import MagicMock
from pathlib import Path


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _mock_infrastructure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Mock heavy infrastructure imports and redirect file paths to tmp_path."""
    import sys

    mock_logger = MagicMock()

    # -- prax logger --------------------------------------------------------
    prax_logger_mod = MagicMock()
    prax_logger_mod.get_direct_logger = MagicMock(return_value=mock_logger)
    monkeypatch.setitem(sys.modules, "aipass.prax", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.prax.apps", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.prax.apps.modules", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.prax.apps.modules.logger", prax_logger_mod)

    # -- trigger json handler -----------------------------------------------
    mock_json_handler = MagicMock()
    mock_json_handler.log_operation = MagicMock(return_value=True)
    json_pkg = MagicMock()
    json_pkg.json_handler = mock_json_handler
    monkeypatch.setitem(sys.modules, "aipass.trigger.apps.handlers.json", json_pkg)
    json_mod = MagicMock()
    json_mod.log_operation = mock_json_handler.log_operation
    monkeypatch.setitem(sys.modules, "aipass.trigger.apps.handlers.json.json_handler", json_mod)

    # -- trigger config (TRIGGER_ROOT) --------------------------------------
    mock_config = MagicMock()
    mock_config.TRIGGER_ROOT = tmp_path
    monkeypatch.setitem(sys.modules, "aipass.trigger.apps.config", mock_config)

    # Force re-import so the module picks up mocked sys.modules
    monkeypatch.delitem(sys.modules, "aipass.trigger.apps.handlers.error_registry", raising=False)


def _import_registry():
    """Import the error_registry module fresh (after mocking)."""
    import aipass.trigger.apps.handlers.error_registry as er
    return er


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _seed_registry(tmp_path: Path, errors: dict | None = None) -> Path:
    """Write a registry JSON file into tmp_path and return its path."""
    registry_dir = tmp_path / "trigger_json"
    registry_dir.mkdir(parents=True, exist_ok=True)
    registry_file = registry_dir / "error_registry.json"
    data = {
        "errors": errors or {},
        "metadata": {"version": "1.0.0", "last_updated": "2026-01-01T00:00:00"},
    }
    registry_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return registry_file


# ===========================================================================
# 1. Error fingerprinting
# ===========================================================================

def test_same_error_produces_same_fingerprint() -> None:
    """Identical inputs always produce the same SHA1 fingerprint."""
    er = _import_registry()
    fp1 = er.compute_fingerprint("ImportError", "no module named foo", "FLOW")
    fp2 = er.compute_fingerprint("ImportError", "no module named foo", "FLOW")
    assert fp1 == fp2
    assert len(fp1) == 40  # Full SHA1 hex digest


def test_different_component_produces_different_fingerprint() -> None:
    """Same error from different components gets a different fingerprint."""
    er = _import_registry()
    fp1 = er.compute_fingerprint("ImportError", "no module named foo", "FLOW")
    fp2 = er.compute_fingerprint("ImportError", "no module named foo", "DRONE")
    assert fp1 != fp2


def test_different_error_type_produces_different_fingerprint() -> None:
    """Different error type with same message gets a different fingerprint."""
    er = _import_registry()
    fp1 = er.compute_fingerprint("ImportError", "no module named foo", "FLOW")
    fp2 = er.compute_fingerprint("ModuleNotFoundError", "no module named foo", "FLOW")
    assert fp1 != fp2


# ===========================================================================
# 2. Message normalization
# ===========================================================================

def test_normalize_strips_timestamps() -> None:
    """normalize_message replaces ISO timestamps with a placeholder."""
    er = _import_registry()
    raw = "Error at 2026-02-13T10:30:45.123456 in process"
    normalized = er.normalize_message(raw)
    assert "2026-02-13" not in normalized
    assert "<timestamp>" in normalized


def test_normalize_strips_paths() -> None:
    """normalize_message replaces absolute paths with a placeholder."""
    er = _import_registry()
    raw = "Cannot read /home/user/project/data.json"
    normalized = er.normalize_message(raw)
    assert "/home/user" not in normalized
    assert "<path>" in normalized


def test_normalize_strips_uuids() -> None:
    """normalize_message replaces UUIDs with a placeholder."""
    er = _import_registry()
    raw = "Session 550e8400-e29b-41d4-a716-446655440000 expired"
    normalized = er.normalize_message(raw)
    assert "550e8400" not in normalized


def test_normalize_strips_line_numbers() -> None:
    """normalize_message replaces 'line 42' with 'line N'."""
    er = _import_registry()
    raw = "SyntaxError at line 42 in module"
    normalized = er.normalize_message(raw)
    assert "line N" in normalized
    assert "line 42" not in normalized


def test_normalize_collapses_whitespace() -> None:
    """normalize_message collapses multiple spaces into one."""
    er = _import_registry()
    raw = "Error   in    module"
    normalized = er.normalize_message(raw)
    assert "  " not in normalized


# ===========================================================================
# 3. Error registration -- report() creates new entry
# ===========================================================================

def test_report_creates_new_entry(tmp_path: Path) -> None:
    """report() creates a new registry entry and returns is_new=True."""
    _seed_registry(tmp_path)
    er = _import_registry()

    result = er.report(
        error_type="ImportError",
        message="No module named 'foo'",
        component="FLOW",
        log_path="/logs/flow.log",
        severity="high",
    )

    assert result["is_new"] is True
    assert result["error_type"] == "ImportError"
    assert result["component"] == "FLOW"
    assert result["severity"] == "high"
    assert result["count"] == 1
    assert result["status"] == "new"
    assert isinstance(result["fingerprint"], str)
    assert len(result["fingerprint"]) == 40  # Full SHA1 hex digest


def test_report_persists_to_disk(tmp_path: Path) -> None:
    """report() writes the entry to the JSON file on disk."""
    registry_file = _seed_registry(tmp_path)
    er = _import_registry()

    er.report(
        error_type="RuntimeError",
        message="unexpected state",
        component="TRIGGER",
    )

    data = json.loads(registry_file.read_text(encoding="utf-8"))
    assert len(data["errors"]) == 1


def test_report_invalid_severity_defaults_to_medium(tmp_path: Path) -> None:
    """report() falls back to 'medium' for unrecognized severity values."""
    _seed_registry(tmp_path)
    er = _import_registry()

    result = er.report(
        error_type="ValueError",
        message="bad input",
        component="API",
        severity="catastrophic",
    )
    assert result["severity"] == "medium"


# ===========================================================================
# 4. Duplicate detection
# ===========================================================================

def test_duplicate_report_increments_count(tmp_path: Path) -> None:
    """Reporting the same error twice increments count and returns is_new=False."""
    _seed_registry(tmp_path)
    er = _import_registry()

    first = er.report("ImportError", "No module named 'bar'", "FLOW")
    assert first["is_new"] is True
    assert first["count"] == 1

    second = er.report("ImportError", "No module named 'bar'", "FLOW")
    assert second["is_new"] is False
    assert second["count"] == 2


def test_duplicate_updates_last_seen(tmp_path: Path) -> None:
    """Duplicate report updates the last_seen timestamp."""
    _seed_registry(tmp_path)
    er = _import_registry()

    first = er.report("IOError", "disk full", "BACKUP")
    second = er.report("IOError", "disk full", "BACKUP")

    assert second["last_seen"] >= first["last_seen"]


def test_different_components_are_not_duplicates(tmp_path: Path) -> None:
    """Same error from different components creates separate entries."""
    _seed_registry(tmp_path)
    er = _import_registry()

    er.report("TimeoutError", "connection timed out", "FLOW")
    er.report("TimeoutError", "connection timed out", "DRONE")

    registry_file = tmp_path / "trigger_json" / "error_registry.json"
    data = json.loads(registry_file.read_text(encoding="utf-8"))
    assert len(data["errors"]) == 2


# ===========================================================================
# 5. resolve / update_status
# ===========================================================================

def test_update_status_resolves_error(tmp_path: Path) -> None:
    """update_status sets status to 'resolved' for an existing entry."""
    _seed_registry(tmp_path)
    er = _import_registry()

    result = er.report("ImportError", "missing module", "FLOW")
    fingerprint = result["fingerprint"]

    success = er.update_status(fingerprint, "resolved")
    assert success is True

    entry = er.get_entry(fingerprint)
    assert entry is not None
    assert entry["status"] == "resolved"


def test_update_status_invalid_status_returns_false(tmp_path: Path) -> None:
    """update_status rejects invalid status values."""
    _seed_registry(tmp_path)
    er = _import_registry()

    result = er.report("ImportError", "missing module", "FLOW")
    fingerprint = result["fingerprint"]

    success = er.update_status(fingerprint, "banana")
    assert success is False


def test_update_status_missing_fingerprint_returns_false(tmp_path: Path) -> None:
    """update_status returns False for a fingerprint not in the registry."""
    _seed_registry(tmp_path)
    er = _import_registry()

    success = er.update_status("nonexistent_fingerprint", "resolved")
    assert success is False


def test_update_status_suppressed_stores_reason(tmp_path: Path) -> None:
    """update_status stores suppress_reason when suppressing."""
    _seed_registry(tmp_path)
    er = _import_registry()

    result = er.report("RuntimeError", "known flaky", "DRONE")
    fingerprint = result["fingerprint"]

    er.update_status(fingerprint, "suppressed", reason="known_flaky")
    entry = er.get_entry(fingerprint)
    assert entry is not None
    assert entry["status"] == "suppressed"
    assert entry["suppress_reason"] == "known_flaky"


# ===========================================================================
# 6. Circuit breaker
# ===========================================================================

def test_circuit_breaker_closed_allows_dispatch(tmp_path: Path) -> None:
    """Circuit breaker in closed state allows dispatch."""
    _seed_registry(tmp_path)
    er = _import_registry()
    er.circuit_breaker_reset()

    assert er.circuit_breaker_allows() is True


def test_circuit_breaker_trips_after_threshold(tmp_path: Path) -> None:
    """Circuit breaker trips to open after recording threshold errors."""
    _seed_registry(tmp_path)
    er = _import_registry()
    er.circuit_breaker_reset()

    # Record enough errors to exceed the default trip_threshold (10)
    for _ in range(11):
        er.circuit_breaker_record_error()

    status = er.get_circuit_breaker_status()
    assert status["state"] == "open"


def test_circuit_breaker_open_blocks_dispatch(tmp_path: Path) -> None:
    """Circuit breaker in open state blocks dispatch."""
    _seed_registry(tmp_path)
    er = _import_registry()
    er.circuit_breaker_reset()
    er.circuit_breaker_trip(reason="test")

    assert er.circuit_breaker_allows() is False


def test_circuit_breaker_reset_restores_closed(tmp_path: Path) -> None:
    """circuit_breaker_reset restores the breaker to closed state."""
    _seed_registry(tmp_path)
    er = _import_registry()
    er.circuit_breaker_trip(reason="test")
    er.circuit_breaker_reset()

    status = er.get_circuit_breaker_status()
    assert status["state"] == "closed"
    assert er.circuit_breaker_allows() is True


def test_circuit_breaker_status_returns_expected_keys(tmp_path: Path) -> None:
    """get_circuit_breaker_status returns a dict with all expected keys."""
    _seed_registry(tmp_path)
    er = _import_registry()
    er.circuit_breaker_reset()

    status = er.get_circuit_breaker_status()
    assert "state" in status
    assert "opened_at" in status
    assert "cooldown_seconds" in status
    assert "recent_error_count" in status
    assert "summary_sent" in status


def test_circuit_breaker_half_open_allows_one_dispatch(tmp_path: Path) -> None:
    """Half-open state allows exactly one probe dispatch then blocks."""
    _seed_registry(tmp_path)
    er = _import_registry()
    er.circuit_breaker_reset()

    # Trip the breaker
    er.circuit_breaker_trip(reason="test")

    # Simulate cooldown expiry by backdating opened_at
    er._circuit_breaker.opened_at = time.time() - er._circuit_breaker.cooldown_seconds - 1

    # First call transitions open -> half_open and allows dispatch
    assert er.circuit_breaker_allows() is True
    assert er._circuit_breaker.state == "half_open"

    # Second call in half_open should be blocked (probe already used)
    assert er.circuit_breaker_allows() is False


def test_circuit_breaker_half_open_error_reopens_with_doubled_cooldown(tmp_path: Path) -> None:
    """Error during half_open re-opens breaker with doubled cooldown."""
    _seed_registry(tmp_path)
    er = _import_registry()
    er.circuit_breaker_reset()

    base_cooldown = er._circuit_breaker.base_cooldown

    # Trip and expire cooldown
    er.circuit_breaker_trip(reason="test")
    er._circuit_breaker.opened_at = time.time() - er._circuit_breaker.cooldown_seconds - 1
    er.circuit_breaker_allows()  # Transition to half_open

    # Record an error during half_open
    er.circuit_breaker_record_error()

    assert er._circuit_breaker.state == "open"
    assert er._circuit_breaker.cooldown_seconds == base_cooldown * 2


# ===========================================================================
# 7. should_dispatch -- per-fingerprint backoff
# ===========================================================================

def test_should_dispatch_true_for_new_fingerprint(tmp_path: Path) -> None:
    """should_dispatch returns True for a never-dispatched fingerprint."""
    _seed_registry(tmp_path)
    er = _import_registry()

    assert er.should_dispatch("brand_new_fingerprint") is True


def test_should_dispatch_false_within_backoff(tmp_path: Path) -> None:
    """should_dispatch returns False when still within backoff window."""
    _seed_registry(tmp_path)
    er = _import_registry()

    fp = "test_fingerprint_abc"
    er.record_dispatch(fp)

    # Immediately after first dispatch, backoff is 300s -- should be False
    assert er.should_dispatch(fp) is False


def test_should_dispatch_true_after_backoff_expires(tmp_path: Path) -> None:
    """should_dispatch returns True once backoff has elapsed."""
    _seed_registry(tmp_path)
    er = _import_registry()

    fp = "test_fingerprint_xyz"
    er.record_dispatch(fp)

    # Backdate the dispatch timestamp past the 300s window
    er._fingerprint_dispatch_times[fp] = [time.time() - 301]

    assert er.should_dispatch(fp) is True


def test_get_backoff_seconds_schedule() -> None:
    """get_backoff_seconds follows the documented backoff schedule."""
    er = _import_registry()
    assert er.get_backoff_seconds(0) == 0
    assert er.get_backoff_seconds(1) == 300
    assert er.get_backoff_seconds(2) == 900
    assert er.get_backoff_seconds(3) == 2700
    assert er.get_backoff_seconds(4) == 7200
    assert er.get_backoff_seconds(10) == 7200


def test_record_dispatch_increments_count(tmp_path: Path) -> None:
    """record_dispatch increments the per-fingerprint dispatch counter."""
    _seed_registry(tmp_path)
    er = _import_registry()

    fp = "dispatch_counter_fp"
    er.record_dispatch(fp)
    er.record_dispatch(fp)
    er.record_dispatch(fp)

    assert er._fingerprint_dispatch_count[fp] == 3
    assert len(er._fingerprint_dispatch_times[fp]) == 3


# ===========================================================================
# 8. list / query
# ===========================================================================

def test_query_returns_all_entries(tmp_path: Path) -> None:
    """query() with no filters returns all entries."""
    _seed_registry(tmp_path)
    er = _import_registry()

    er.report("ImportError", "missing x", "FLOW")
    er.report("IOError", "disk full", "BACKUP")

    results = er.query()
    assert len(results) == 2


def test_query_filters_by_status(tmp_path: Path) -> None:
    """query(status=...) returns only entries with that status."""
    _seed_registry(tmp_path)
    er = _import_registry()

    r1 = er.report("ImportError", "missing x", "FLOW")
    er.report("IOError", "disk full", "BACKUP")

    er.update_status(r1["fingerprint"], "resolved")

    results = er.query(status="resolved")
    assert len(results) == 1
    assert results[0]["status"] == "resolved"


def test_query_filters_by_component(tmp_path: Path) -> None:
    """query(component=...) returns only entries from that component."""
    _seed_registry(tmp_path)
    er = _import_registry()

    er.report("ImportError", "missing x", "FLOW")
    er.report("IOError", "disk full", "BACKUP")

    results = er.query(component="FLOW")
    assert len(results) == 1
    assert results[0]["component"] == "FLOW"


def test_query_filters_by_severity(tmp_path: Path) -> None:
    """query(severity=...) returns only entries with that severity."""
    _seed_registry(tmp_path)
    er = _import_registry()

    er.report("ImportError", "missing x", "FLOW", severity="high")
    er.report("IOError", "disk full", "BACKUP", severity="low")

    results = er.query(severity="high")
    assert len(results) == 1
    assert results[0]["severity"] == "high"


def test_query_respects_limit(tmp_path: Path) -> None:
    """query(limit=N) returns at most N entries."""
    _seed_registry(tmp_path)
    er = _import_registry()

    for i in range(10):
        er.report("Error", f"error number {i}", f"C{i}")

    results = er.query(limit=3)
    assert len(results) == 3


def test_query_empty_registry(tmp_path: Path) -> None:
    """query() on an empty registry returns an empty list."""
    _seed_registry(tmp_path)
    er = _import_registry()

    results = er.query()
    assert results == []


# ===========================================================================
# 9. get_entry / prefix matching
# ===========================================================================

def test_get_entry_exact_match(tmp_path: Path) -> None:
    """get_entry returns the entry for an exact fingerprint."""
    _seed_registry(tmp_path)
    er = _import_registry()

    result = er.report("KeyError", "missing key", "API")
    fingerprint = result["fingerprint"]

    entry = er.get_entry(fingerprint)
    assert entry is not None
    assert entry["fingerprint"] == fingerprint


def test_get_entry_prefix_match(tmp_path: Path) -> None:
    """get_entry matches on a 12-char prefix of the fingerprint."""
    _seed_registry(tmp_path)
    er = _import_registry()

    result = er.report("KeyError", "missing key", "API")
    fingerprint = result["fingerprint"]

    entry = er.get_entry(fingerprint[:12])
    assert entry is not None
    assert entry["fingerprint"] == fingerprint


def test_get_entry_not_found(tmp_path: Path) -> None:
    """get_entry returns None for an unknown fingerprint."""
    _seed_registry(tmp_path)
    er = _import_registry()

    assert er.get_entry("does_not_exist") is None


# ===========================================================================
# 10. clear_resolved
# ===========================================================================

def test_clear_resolved_removes_old_resolved(tmp_path: Path) -> None:
    """clear_resolved removes resolved entries older than N days."""
    _seed_registry(tmp_path)
    er = _import_registry()

    result = er.report("ImportError", "old error", "FLOW")
    er.update_status(result["fingerprint"], "resolved")

    # Backdate last_seen to 30 days ago
    registry_file = tmp_path / "trigger_json" / "error_registry.json"
    data = json.loads(registry_file.read_text(encoding="utf-8"))
    for entry in data["errors"].values():
        entry["last_seen"] = "2025-01-01T00:00:00"
    registry_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

    removed = er.clear_resolved(days=7)
    assert removed == 1

    data_after = json.loads(registry_file.read_text(encoding="utf-8"))
    assert len(data_after["errors"]) == 0


def test_clear_resolved_keeps_recent_resolved(tmp_path: Path) -> None:
    """clear_resolved keeps resolved entries newer than the cutoff."""
    _seed_registry(tmp_path)
    er = _import_registry()

    result = er.report("ImportError", "recent error", "FLOW")
    er.update_status(result["fingerprint"], "resolved")

    # last_seen is set to now by report(), so it should survive a 7-day cutoff
    removed = er.clear_resolved(days=7)
    assert removed == 0


def test_clear_resolved_keeps_non_resolved(tmp_path: Path) -> None:
    """clear_resolved does not remove entries that are not resolved."""
    _seed_registry(tmp_path)
    er = _import_registry()

    er.report("ImportError", "active error", "FLOW")

    # Backdate last_seen
    registry_file = tmp_path / "trigger_json" / "error_registry.json"
    data = json.loads(registry_file.read_text(encoding="utf-8"))
    for entry in data["errors"].values():
        entry["last_seen"] = "2025-01-01T00:00:00"
    registry_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

    removed = er.clear_resolved(days=7)
    assert removed == 0


# ===========================================================================
# 11. get_stats
# ===========================================================================

def test_get_stats_empty_registry(tmp_path: Path) -> None:
    """get_stats on empty registry returns zeroed counters."""
    _seed_registry(tmp_path)
    er = _import_registry()

    stats = er.get_stats()
    assert stats["total"] == 0
    assert stats["by_status"] == {}
    assert stats["by_component"] == {}
    assert stats["by_severity"] == {}


def test_get_stats_counts_correctly(tmp_path: Path) -> None:
    """get_stats returns correct totals and breakdowns."""
    _seed_registry(tmp_path)
    er = _import_registry()

    er.report("ImportError", "missing x", "FLOW", severity="high")
    er.report("IOError", "disk full", "BACKUP", severity="low")
    er.report("TimeoutError", "timed out", "FLOW", severity="high")

    stats = er.get_stats()
    assert stats["total"] == 3
    assert stats["by_component"].get("FLOW") == 2
    assert stats["by_component"].get("BACKUP") == 1
    assert stats["by_severity"].get("high") == 2
    assert stats["by_severity"].get("low") == 1


# ===========================================================================
# 12. update_source_fix_status
# ===========================================================================

def test_update_source_fix_status_valid(tmp_path: Path) -> None:
    """update_source_fix_status sets fix tracking on an existing entry."""
    _seed_registry(tmp_path)
    er = _import_registry()

    result = er.report("ImportError", "missing module", "FLOW")
    fp = result["fingerprint"]

    success = er.update_source_fix_status(fp, "fix_requested")
    assert success is True

    entry = er.get_entry(fp)
    assert entry is not None
    assert entry["source_fix_status"] == "fix_requested"


def test_update_source_fix_status_invalid_status(tmp_path: Path) -> None:
    """update_source_fix_status rejects invalid fix status values."""
    _seed_registry(tmp_path)
    er = _import_registry()

    result = er.report("ImportError", "missing module", "FLOW")
    fp = result["fingerprint"]

    success = er.update_source_fix_status(fp, "all_good")
    assert success is False


def test_update_source_fix_status_missing_fingerprint(tmp_path: Path) -> None:
    """update_source_fix_status returns False for unknown fingerprint."""
    _seed_registry(tmp_path)
    er = _import_registry()

    success = er.update_source_fix_status("nonexistent", "pending_fix")
    assert success is False


# ===========================================================================
# 13. User-error auto-suppression
# ===========================================================================

def test_user_error_auto_suppressed(tmp_path: Path) -> None:
    """Errors matching user-error patterns are auto-suppressed on report."""
    _seed_registry(tmp_path)
    er = _import_registry()

    result = er.report(
        error_type="CommandError",
        message="unknown command: foobar",
        component="CLI",
    )
    assert result["status"] == "suppressed"
    assert result["suppress_reason"] == "user_error"


def test_non_user_error_not_suppressed(tmp_path: Path) -> None:
    """Regular system errors are not auto-suppressed."""
    _seed_registry(tmp_path)
    er = _import_registry()

    result = er.report(
        error_type="ConnectionError",
        message="connection refused to database",
        component="API",
    )
    assert result["status"] == "new"


# ===========================================================================
# 14. Registry I/O edge cases
# ===========================================================================

def test_load_registry_creates_default_when_file_missing(tmp_path: Path) -> None:
    """_load_registry returns a default structure when the file does not exist."""
    er = _import_registry()

    registry = er._load_registry()
    assert "errors" in registry
    assert "metadata" in registry
    assert registry["errors"] == {}
    assert registry["metadata"]["version"] == "1.0.0"
    assert "last_updated" in registry["metadata"]
    assert registry["metadata"]["last_updated"] != ""


def test_save_registry_creates_parent_dirs(tmp_path: Path) -> None:
    """_save_registry creates parent directories if they do not exist."""
    er = _import_registry()

    data = {
        "errors": {},
        "metadata": {"version": "1.0.0", "last_updated": ""},
    }
    result = er._save_registry(data)
    assert result is True
    assert er.REGISTRY_FILE.parent.exists()

    # Verify the saved file contains valid JSON with expected structure
    saved = json.loads(er.REGISTRY_FILE.read_text(encoding="utf-8"))
    assert "errors" in saved
    assert "metadata" in saved
    assert saved["errors"] == {}
    assert saved["metadata"]["version"] == "1.0.0"
    # last_updated is overwritten by _save_registry to current time
    assert saved["metadata"]["last_updated"] != ""


# ===========================================================================
# 15. Contract gap tests
# ===========================================================================

def test_normalize_message_empty_string() -> None:
    """normalize_message('') returns empty string."""
    er = _import_registry()
    result = er.normalize_message("")
    assert result == ""


def test_normalize_message_unicode_and_emoji() -> None:
    """normalize_message preserves unicode and emoji characters."""
    er = _import_registry()
    raw = "Error: \u2603 snowman failed \U0001f525 fire at line 99"
    normalized = er.normalize_message(raw)
    # Emoji and unicode should survive normalization
    assert "\u2603" in normalized
    assert "\U0001f525" in normalized
    # But line number should be stripped
    assert "line 99" not in normalized
    assert "line N" in normalized


def test_compute_fingerprint_empty_strings() -> None:
    """compute_fingerprint with all empty strings returns a valid SHA1 hash."""
    er = _import_registry()
    fp = er.compute_fingerprint("", "", "")
    assert isinstance(fp, str)
    assert len(fp) == 40
    # Deterministic: same inputs always produce same hash
    fp2 = er.compute_fingerprint("", "", "")
    assert fp == fp2


def test_report_return_type_is_dict(tmp_path: Path) -> None:
    """report() always returns a dict."""
    _seed_registry(tmp_path)
    er = _import_registry()

    result = er.report(
        error_type="ValueError",
        message="test message",
        component="API",
    )
    assert isinstance(result, dict)
