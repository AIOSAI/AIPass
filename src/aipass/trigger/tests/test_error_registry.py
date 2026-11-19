# =================== AIPass ====================
# Name: test_error_registry.py
# Description: Unit tests for the error_registry handler
# Version: 1.5.0
# Created: 2026-03-24
# Modified: 2026-11-16
# =============================================

"""Tests for apps/handlers/error_registry.py: the dedup engine, circuit breaker and backoff."""

# The declared pass — what is NOT tested here, and what covers it instead:
# sentry: no-test-needed(covered_elsewhere) — the errors command that reads this registry, in tests/test_errors.py
# sentry: no-test-needed(covered_elsewhere) — the dispatch gate on should_dispatch, in tests/test_error_detected.py

import json
import threading
import time
from datetime import datetime
from dataclasses import fields

import pytest
from unittest.mock import MagicMock
from pathlib import Path

# Bound as `er`, the name every test uses, so a reach into a private name
# stays visible to the audit (through_the_command resolves import bindings).
import aipass.trigger.apps.handlers.error_registry as er


@pytest.fixture(autouse=True)
def _registry_on_tmp(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Point every file the registry writes at tmp_path and start each test from a fresh breaker.

    REGISTRY_FILE and CB_STATE_FILE are built off TRIGGER_ROOT at import: the live files unless swapped."""
    json_dir = tmp_path / "trigger_json"
    monkeypatch.setattr(er, "REGISTRY_FILE", json_dir / "error_registry.json")
    monkeypatch.setattr(er, "CB_STATE_FILE", json_dir / "trigger_cb_state.json")
    monkeypatch.setattr(er.json_handler, "log_operation", MagicMock(return_value=True))
    monkeypatch.setattr(er, "logger", MagicMock())


def _import_registry():
    """Return the registry module; the autouse fixture has already put it on tmp_path."""
    return er


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


def test_normalize_strips_timestamps() -> None:
    """normalize_message replaces ISO timestamps with a placeholder."""
    er = _import_registry()
    raw = "Error at 2026-02-13T10:30:45.123456 in process"
    normalized = er.normalize_message(raw)
    assert "2026-02-13" not in normalized
    assert "<timestamp>" in normalized


def test_normalize_strips_paths(tmp_path: Path) -> None:
    """normalize_message replaces absolute paths with a placeholder."""
    er = _import_registry()
    data_file = tmp_path / "project" / "data.json"
    normalized = er.normalize_message(f"Cannot read {data_file}")
    assert str(tmp_path) not in normalized
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


def test_report_creates_new_entry(tmp_path: Path) -> None:
    """report() creates a new registry entry and returns is_new=True."""
    _seed_registry(tmp_path)
    er = _import_registry()

    result = er.report(
        error_type="ImportError",
        message="No module named 'foo'",
        component="FLOW",
        log_path=str(tmp_path / "flow.log"),
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


_T0 = 1_000_000.0


def test_a_closed_breaker_sends(tmp_path: Path) -> None:
    _seed_registry(tmp_path)
    er = _import_registry()

    assert er.dispatch_gate("@a", "fp", "n", now=_T0) == "send"


def _trip(registry, now: float = _T0) -> list:
    """Open the breaker the way production does: ten distinct sends, five to @a and five to @b, at one now."""
    return [registry.dispatch_gate(r, f"fp_{r[1]}{i}", "n", now=now) for r in ("@a", "@b") for i in range(5)]


def test_ten_distinct_sends_in_the_window_trip_and_hold_the_tenth(tmp_path: Path) -> None:
    _seed_registry(tmp_path)
    er = _import_registry()

    assert _trip(er) == ["send"] * 9 + ["tripped"]
    assert er.get_circuit_breaker_status(now=_T0)["state"] == "open"


def test_sends_outside_the_trip_window_do_not_trip_the_breaker(tmp_path: Path) -> None:
    """Nine sends a window ago and one now are one send in the window, not ten."""
    _seed_registry(tmp_path)
    er = _import_registry()
    for r, i in [("@a", i) for i in range(5)] + [("@b", i) for i in range(4)]:
        er.dispatch_gate(r, f"fp_{i}", "n", now=_T0)

    assert er.dispatch_gate("@b", "fp_late", "n", now=_T0 + 61) == "send"
    assert er.get_circuit_breaker_status(now=_T0 + 61)["state"] == "closed"


def test_an_open_breaker_holds_the_mail_until_the_summary_is_sent(tmp_path: Path) -> None:
    _seed_registry(tmp_path)
    er = _import_registry()
    _trip(er)

    assert er.dispatch_gate("@c", "fp_c", "the note", now=_T0) == "tripped"
    er.circuit_breaker_summary_sent()
    assert er.dispatch_gate("@c", "fp_c", "the note", now=_T0) == "held_open"
    assert er.circuit_breaker_held("@c") == {"fp_c": {"note": "the note", "count": 2, "first_held": _T0}}


def test_circuit_breaker_reset_restores_closed(tmp_path: Path) -> None:
    _seed_registry(tmp_path)
    er = _import_registry()
    _trip(er)
    er.circuit_breaker_reset()

    assert er.get_circuit_breaker_status()["state"] == "closed"
    assert er.dispatch_gate("@c", "fp_c", "n", now=_T0) == "send"


def test_circuit_breaker_status_returns_expected_keys(tmp_path: Path) -> None:
    _seed_registry(tmp_path)
    er = _import_registry()

    assert set(er.get_circuit_breaker_status()) == {
        "state",
        "opened_at",
        "cooldown_seconds",
        "recent_send_count",
        "held_count",
        "summary_sent",
        "remaining_seconds",
    }


def test_after_the_cooldown_the_gate_gives_one_probe_then_holds(tmp_path: Path) -> None:
    _seed_registry(tmp_path)
    er = _import_registry()
    _trip(er)
    later = _T0 + 301

    assert er.dispatch_gate("@c", "fp_1", "n", now=later) == "probe"
    assert er.get_circuit_breaker_status(now=later)["state"] == "half_open"
    assert er.dispatch_gate("@c", "fp_2", "n", now=later) == "tripped"


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

    # A clock reading past the 300s window, handed in
    assert er.should_dispatch(fp, now=time.time() + 301) is True


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

    assert er.get_dispatch_count(fp) == 3
    # The third dispatch sets the backoff: one minute short of it, still held
    assert er.should_dispatch(fp, now=time.time() + er.get_backoff_seconds(3) - 60) is False


def test_should_dispatch_false_when_suppressed(tmp_path: Path) -> None:
    """A suppressed fingerprint never dispatches, even with no backoff pending."""
    _seed_registry(tmp_path)
    er = _import_registry()

    result = er.report("ImportError", "cannot import widget", "FLOW")
    fp = result["fingerprint"]

    # Never dispatched -> would be True on backoff alone
    assert er.should_dispatch(fp) is True

    er.update_status(fp, "suppressed", "known noise")
    assert er.should_dispatch(fp) is False


def test_unsuppress_restores_dispatch(tmp_path: Path) -> None:
    """Lifting suppression restores dispatch for the same fingerprint."""
    _seed_registry(tmp_path)
    er = _import_registry()

    fp = er.report("ImportError", "cannot import widget", "FLOW")["fingerprint"]

    er.update_status(fp, "suppressed", "known noise")
    assert er.should_dispatch(fp) is False

    er.update_status(fp, "new")
    assert er.should_dispatch(fp) is True


def test_unsuppress_keeps_existing_backoff(tmp_path: Path) -> None:
    """Unsuppress restores dispatch subject to backoff -- it does not reset to immediate."""
    _seed_registry(tmp_path)
    er = _import_registry()

    fp = er.report("IOError", "disk full", "BACKUP")["fingerprint"]
    er.record_dispatch(fp)

    er.update_status(fp, "suppressed", "quiet for now")
    er.update_status(fp, "new")

    # Backoff from the pre-suppression dispatch still applies
    assert er.should_dispatch(fp) is False

    assert er.should_dispatch(fp, now=time.time() + 301) is True


def test_bookkeeping_continues_while_suppressed(tmp_path: Path) -> None:
    """Occurrences still count and timestamp while suppressed -- a wrong suppress stays auditable."""
    _seed_registry(tmp_path)
    er = _import_registry()

    fp = er.report("IOError", "disk full", "BACKUP")["fingerprint"]
    er.update_status(fp, "suppressed", "known noise")

    seeded = er.get_entry(fp)
    assert seeded is not None
    first_seen = seeded["last_seen"]

    er.report("IOError", "disk full", "BACKUP")
    result = er.report("IOError", "disk full", "BACKUP")

    entry = er.get_entry(fp)
    assert entry is not None
    assert result["count"] == 3
    assert entry["count"] == 3
    assert entry["status"] == "suppressed"
    assert entry["last_seen"] >= first_seen
    assert er.should_dispatch(fp) is False


def test_new_fingerprint_dispatches_while_another_suppressed(tmp_path: Path) -> None:
    """Suppression is per-fingerprint -- an unrelated error still dispatches."""
    _seed_registry(tmp_path)
    er = _import_registry()

    quiet = er.report("ImportError", "cannot import widget", "FLOW")["fingerprint"]
    er.update_status(quiet, "suppressed", "known noise")

    loud = er.report("IOError", "disk full", "BACKUP")["fingerprint"]

    assert er.should_dispatch(quiet) is False
    assert er.should_dispatch(loud) is True


def test_resolved_status_does_not_gate_dispatch(tmp_path: Path) -> None:
    """Only 'suppressed' silences. A resolved error that recurs means the fix did not hold."""
    _seed_registry(tmp_path)
    er = _import_registry()

    fp = er.report("IOError", "disk full", "BACKUP")["fingerprint"]
    er.update_status(fp, "resolved")

    assert er.is_suppressed(fp) is False
    assert er.should_dispatch(fp) is True


def test_is_suppressed_true_only_for_suppressed_status(tmp_path: Path) -> None:
    """is_suppressed tracks the registry status and is False for unknown fingerprints."""
    _seed_registry(tmp_path)
    er = _import_registry()

    fp = er.report("IOError", "disk full", "BACKUP")["fingerprint"]

    assert er.is_suppressed(fp) is False
    er.update_status(fp, "suppressed", "known noise")
    assert er.is_suppressed(fp) is True
    assert er.is_suppressed("never_seen_fingerprint") is False


def test_is_suppressed_raises_on_an_unreadable_registry(tmp_path: Path) -> None:
    """Pins the fail-open default: an unreadable registry answered 'not suppressed' and nobody was told."""
    registry_file = tmp_path / "trigger_json" / "error_registry.json"
    registry_file.parent.mkdir(parents=True, exist_ok=True)
    registry_file.write_text("{invalid json", encoding="utf-8")
    er = _import_registry()

    with pytest.raises(json.JSONDecodeError):
        er.is_suppressed("any_fingerprint")
    with pytest.raises(json.JSONDecodeError):
        er.should_dispatch("any_fingerprint")


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


def test_clear_resolved_removes_old_resolved(tmp_path: Path) -> None:
    """clear_resolved removes resolved entries older than N days."""
    _seed_registry(tmp_path)
    er = _import_registry()

    result = er.report("ImportError", "old error", "FLOW")
    er.update_status(result["fingerprint"], "resolved")

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

    registry_file = tmp_path / "trigger_json" / "error_registry.json"
    data = json.loads(registry_file.read_text(encoding="utf-8"))
    for entry in data["errors"].values():
        entry["last_seen"] = "2025-01-01T00:00:00"
    registry_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

    removed = er.clear_resolved(days=7)
    assert removed == 0


def test_clear_resolved_unreadable_shape_returns_minus_one(tmp_path: Path) -> None:
    """A registry clear_resolved cannot walk answers -1, never the 0 of "nothing to clear"."""
    registry_file = tmp_path / "trigger_json" / "error_registry.json"
    registry_file.parent.mkdir(parents=True, exist_ok=True)
    registry_file.write_text(json.dumps({"errors": [], "metadata": {}}), encoding="utf-8")
    er = _import_registry()

    assert er.clear_resolved(days=7) == -1
    assert json.loads(registry_file.read_text(encoding="utf-8"))["errors"] == []


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


def test_a_line_with_every_rejection_phrase_is_a_new_error_never_suppressed(tmp_path: Path) -> None:
    _seed_registry(tmp_path)
    er = _import_registry()
    phrases = (
        "unknown command, invalid argument, unrecognized, missing required argument, usage:, no such command, "
        "not a valid command, unrecognized option, unknown option, too few arguments, too many arguments"
    )

    first = er.report("ERROR", phrases, "CLI")
    again = er.report("ERROR", phrases, "CLI")

    assert (first["status"], first["suppress_reason"]) == ("new", "")
    assert (again["count"], again["status"], again["suppress_reason"]) == (2, "new", "")


def test_a_usage_line_is_a_normal_error_and_dispatches(tmp_path: Path) -> None:
    """The api 429 row was hidden by its word usage:."""
    _seed_registry(tmp_path)
    er = _import_registry()

    row = er.report("WARNING", "[host_api] usage: oauth/usage answered 429, backing off 60 s", "API")

    assert (row["is_new"], row["status"]) == (True, "new")
    assert er.should_dispatch(row["fingerprint"]) is True


def test_an_old_phrase_suppressed_row_dispatches_on_its_next_occurrence_and_an_operator_suppress_holds(
    tmp_path: Path,
) -> None:
    message = "[host_api] usage: oauth/usage answered 429, backing off 60 s"
    guessed = er.compute_fingerprint("WARNING", er.normalize_message(message), "API")
    chosen = er.compute_fingerprint("ERROR", er.normalize_message("bind refused"), "API")
    base = {"count": 484, "first_seen": "2026-11-07T21:45:00", "last_seen": "2026-11-16T00:23:40"}
    base["status"] = "suppressed"
    _seed_registry(
        tmp_path,
        {
            guessed: {**base, "fingerprint": guessed, "message": message, "suppress_reason": "user_error"},
            chosen: {**base, "fingerprint": chosen, "message": "bind refused", "suppress_reason": "boot race"},
        },
    )

    revived = er.report("WARNING", message, "API")
    held = er.report("ERROR", "bind refused", "API")

    assert (revived["count"], revived["status"], revived["suppress_reason"]) == (485, "new", "user_error")
    assert er.should_dispatch(guessed) is True
    assert (held["status"], er.should_dispatch(chosen)) == ("suppressed", False)


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


def test_load_registry_creates_default_when_file_missing(tmp_path: Path) -> None:
    """A missing registry reads as the empty default: the first report starts it with version 1.0.0."""
    er = _import_registry()
    assert not er.REGISTRY_FILE.exists()

    result = er.report(error_type="TestError", message="the first error ever", component="TRIGGER")

    assert "fingerprint" in result, "report fell to its failure dict"
    saved = json.loads(er.REGISTRY_FILE.read_text(encoding="utf-8"))
    assert list(saved["errors"]) == [result["fingerprint"]]
    assert saved["metadata"]["version"] == "1.0.0"


def test_a_status_change_is_saved_with_a_fresh_stamp(tmp_path: Path) -> None:
    """update_status answers with the save's own result, and the save restamps last_updated."""
    _seed_registry(tmp_path, {"fp_saved": {"fingerprint": "fp_saved", "status": "new"}})
    er = _import_registry()

    assert er.update_status("fp_saved", "investigating") is True

    saved = json.loads(er.REGISTRY_FILE.read_text(encoding="utf-8"))
    assert saved["errors"]["fp_saved"]["status"] == "investigating"
    assert saved["metadata"]["version"] == "1.0.0"
    assert saved["metadata"]["last_updated"] != "2026-01-01T00:00:00", "the save did not restamp the document"


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
    assert "\u2603" in normalized
    assert "\U0001f525" in normalized
    assert "line 99" not in normalized
    assert "line N" in normalized


def test_compute_fingerprint_empty_strings() -> None:
    """compute_fingerprint with all empty strings returns a valid SHA1 hash."""
    er = _import_registry()
    fp = er.compute_fingerprint("", "", "")
    assert isinstance(fp, str)
    assert len(fp) == 40
    fp2 = er.compute_fingerprint("", "", "")
    assert fp == fp2


def test_report_returns_the_whole_entry_not_a_summary_of_it(tmp_path: Path) -> None:
    """report() returns every ErrorEvent field plus is_new — callers read them.

    The except branch's fallback dict passes isinstance(dict) too; the field set is the contract."""
    _seed_registry(tmp_path)
    er = _import_registry()

    result = er.report(
        error_type="ValueError",
        message="test message",
        component="API",
    )

    assert set(result) == {f.name for f in fields(er.ErrorEvent)} | {"is_new"}
    assert result["fingerprint"] == er.compute_fingerprint("ValueError", er.normalize_message("test message"), "API")


class TestEmptyJsonResilience:
    """Verify no crashes when JSON files are empty or corrupt."""

    def test_load_registry_empty_file(self, tmp_path: Path) -> None:
        """An empty registry file reads as the empty default: the report lands as its only entry."""
        registry_dir = tmp_path / "trigger_json"
        registry_dir.mkdir(parents=True, exist_ok=True)
        registry_file = registry_dir / "error_registry.json"
        registry_file.write_text("", encoding="utf-8")

        er = _import_registry()
        result = er.report(error_type="TestError", message="onto an empty file", component="TRIGGER")

        assert "fingerprint" in result, "report fell to its failure dict"
        saved = json.loads(registry_file.read_text(encoding="utf-8"))
        assert list(saved["errors"]) == [result["fingerprint"]]

    @pytest.mark.parametrize("content", ["{invalid json", '{"no_errors_key": 1}', "[]"])
    def test_an_unreadable_registry_raises_from_report_and_is_left_untouched(
        self, tmp_path: Path, content: str
    ) -> None:
        """Pins the silent reset: an unreadable registry read as empty, and report wrote the empty one over it."""
        registry_dir = tmp_path / "trigger_json"
        registry_dir.mkdir(parents=True, exist_ok=True)
        registry_file = registry_dir / "error_registry.json"
        registry_file.write_text(content, encoding="utf-8")

        er = _import_registry()
        with pytest.raises(ValueError):
            er.report(error_type="TestError", message="onto a corrupt file", component="TRIGGER")

        assert registry_file.read_text(encoding="utf-8") == content

    def test_load_circuit_breaker_empty_config(self, tmp_path: Path) -> None:
        """An empty breaker state file reads as a closed breaker with no backoff."""
        config_dir = tmp_path / "trigger_json"
        config_dir.mkdir(parents=True, exist_ok=True)
        # The breaker persists here; any other file would pass without reading anything.
        config_file = config_dir / "trigger_cb_state.json"
        config_file.write_text("", encoding="utf-8")

        er = _import_registry()
        status = er.get_circuit_breaker_status()
        assert status["state"] == "closed"
        assert status["cooldown_seconds"] == 300
        assert er.get_dispatch_count("any_fp") == 0

    def test_an_unreadable_breaker_state_raises_and_is_left_untouched(self, tmp_path: Path) -> None:
        """Pins the default: a torn breaker file read as a closed breaker, so an open one dispatched again."""
        state_file = tmp_path / "trigger_json" / "trigger_cb_state.json"
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text("{torn", encoding="utf-8")

        with pytest.raises(RuntimeError, match=r"circuit breaker state unreadable \(trigger_cb_state\.json\)"):
            er.dispatch_gate("@a", "fp", "n")
        assert state_file.read_text(encoding="utf-8") == "{torn"

    def test_a_breaker_state_that_cannot_be_saved_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Pins the default: a failed save was a warning, and the trip it held was lost on the next read."""
        monkeypatch.setattr(er, "atomic_write_json", MagicMock(side_effect=OSError("disk full")))

        with pytest.raises(RuntimeError, match=r"circuit breaker state unsaved \(trigger_cb_state\.json\).*disk full"):
            er.dispatch_gate("@a", "fp", "n")

    def test_report_with_empty_registry(self, tmp_path: Path) -> None:
        """report() works when registry file is empty (creates fresh)."""
        registry_dir = tmp_path / "trigger_json"
        registry_dir.mkdir(parents=True, exist_ok=True)
        registry_file = registry_dir / "error_registry.json"
        registry_file.write_text("", encoding="utf-8")

        er = _import_registry()
        result = er.report(
            error_type="TestError",
            message="test with empty registry",
            component="TRIGGER",
        )
        assert isinstance(result, dict)
        assert result["is_new"] is True
        assert result["count"] == 1


def test_purge_stale_removes_old_entries(tmp_path: Path) -> None:
    """purge_stale removes entries older than N days regardless of status."""
    _seed_registry(tmp_path)
    er = _import_registry()

    er.report("ImportError", "old error", "FLOW")
    er.report("IOError", "another old error", "BACKUP")

    registry_file = tmp_path / "trigger_json" / "error_registry.json"
    data = json.loads(registry_file.read_text(encoding="utf-8"))
    for entry in data["errors"].values():
        entry["last_seen"] = "2025-01-01T00:00:00"
    registry_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

    removed = er.purge_stale(days=30)
    assert removed == 2

    data_after = json.loads(registry_file.read_text(encoding="utf-8"))
    assert len(data_after["errors"]) == 0


def test_purge_stale_keeps_recent_entries(tmp_path: Path) -> None:
    """purge_stale keeps entries newer than the cutoff."""
    _seed_registry(tmp_path)
    er = _import_registry()

    er.report("ImportError", "recent error", "FLOW")

    # last_seen is set to now by report(), so it should survive a 30-day cutoff
    removed = er.purge_stale(days=30)
    assert removed == 0


def test_purge_stale_ignores_status(tmp_path: Path) -> None:
    """purge_stale removes old entries regardless of status (new, suppressed, etc.)."""
    _seed_registry(tmp_path)
    er = _import_registry()

    er.report("ImportError", "old new error", "FLOW")
    r2 = er.report("IOError", "old suppressed error", "BACKUP")
    er.update_status(r2["fingerprint"], "suppressed", reason="known")

    registry_file = tmp_path / "trigger_json" / "error_registry.json"
    data = json.loads(registry_file.read_text(encoding="utf-8"))
    for entry in data["errors"].values():
        entry["last_seen"] = "2025-01-01T00:00:00"
    registry_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

    removed = er.purge_stale(days=30)
    assert removed == 2


def test_purge_stale_returns_zero_on_empty_registry(tmp_path: Path) -> None:
    """purge_stale returns 0 when registry is empty."""
    _seed_registry(tmp_path)
    er = _import_registry()

    removed = er.purge_stale(days=30)
    assert removed == 0


def test_purge_stale_unreadable_shape_returns_minus_one(tmp_path: Path) -> None:
    """A registry purge_stale cannot walk answers -1, never the 0 of "nothing stale"."""
    registry_file = tmp_path / "trigger_json" / "error_registry.json"
    registry_file.parent.mkdir(parents=True, exist_ok=True)
    registry_file.write_text(json.dumps({"errors": [], "metadata": {}}), encoding="utf-8")
    er = _import_registry()

    assert er.purge_stale(days=30) == -1
    assert json.loads(registry_file.read_text(encoding="utf-8"))["errors"] == []


def test_purge_stale_custom_days(tmp_path: Path) -> None:
    """purge_stale respects custom days parameter."""
    _seed_registry(tmp_path)
    er = _import_registry()

    er.report("ImportError", "semi-old error", "FLOW")

    registry_file = tmp_path / "trigger_json" / "error_registry.json"
    data = json.loads(registry_file.read_text(encoding="utf-8"))
    from datetime import datetime, timedelta

    ten_days_ago = (datetime.now() - timedelta(days=10)).isoformat()
    for entry in data["errors"].values():
        entry["last_seen"] = ten_days_ago
    registry_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

    assert er.purge_stale(days=30) == 0

    assert er.purge_stale(days=7) == 1


def test_a_status_read_after_cooldown_leaves_state_and_file_unchanged(tmp_path: Path) -> None:
    _seed_registry(tmp_path)
    er = _import_registry()
    _trip(er)
    before = er.CB_STATE_FILE.read_bytes()

    status = er.get_circuit_breaker_status(now=_T0 + 10_000)

    assert status["state"] == "open"
    assert er.CB_STATE_FILE.read_bytes() == before


def test_the_gate_holds_one_second_short_of_the_cooldown_without_restamping(tmp_path: Path) -> None:
    _seed_registry(tmp_path)
    er = _import_registry()
    _trip(er)

    assert er.dispatch_gate("@c", "fp_c", "n", now=_T0 + 299) == "tripped"
    status = er.get_circuit_breaker_status(now=_T0 + 299)
    assert status["state"] == "open"
    assert status["opened_at"] == _T0


def test_a_delivered_probe_closes_the_breaker(tmp_path: Path) -> None:
    _seed_registry(tmp_path)
    er = _import_registry()
    _trip(er)
    assert er.dispatch_gate("@c", "fp_probe", "n", now=_T0 + 301) == "probe"

    er.circuit_breaker_delivered("@c", ["fp_probe"])

    status = er.get_circuit_breaker_status(now=_T0 + 301)
    assert status["state"] == "closed"
    assert status["cooldown_seconds"] == 300
    assert status["opened_at"] == 0.0
    assert status["recent_send_count"] == 0


def test_a_delivery_while_open_drops_its_held_row_but_keeps_the_breaker_open(tmp_path: Path) -> None:
    _seed_registry(tmp_path)
    er = _import_registry()
    _trip(er)
    assert list(er.circuit_breaker_held("@b")) == ["fp_b4"]

    er.circuit_breaker_delivered("@b", ["fp_b4"])

    assert er.circuit_breaker_held("@b") == {}
    assert er.get_circuit_breaker_status(now=_T0)["state"] == "open"


def test_status_returns_remaining_seconds(tmp_path: Path) -> None:
    _seed_registry(tmp_path)
    er = _import_registry()
    _trip(er)

    assert er.get_circuit_breaker_status(now=_T0 + 100)["remaining_seconds"] == 200


def test_status_remaining_zero_when_closed(tmp_path: Path) -> None:
    _seed_registry(tmp_path)
    er = _import_registry()

    assert er.get_circuit_breaker_status()["remaining_seconds"] == 0


def test_one_recipient_alone_never_trips_the_fleet(tmp_path: Path) -> None:
    _seed_registry(tmp_path)
    er = _import_registry()

    verdicts = [er.dispatch_gate("@a", f"fp_{i}", "n", now=_T0) for i in range(12)]

    assert verdicts == ["send"] * 5 + ["held_cap"] * 7
    assert er.get_circuit_breaker_status(now=_T0)["state"] == "closed"


def test_a_lost_probe_is_replaced_after_the_base_cooldown(tmp_path: Path) -> None:
    _seed_registry(tmp_path)
    er = _import_registry()
    _trip(er)

    assert er.dispatch_gate("@c", "fp_1", "n", now=_T0 + 301) == "probe"
    assert er.dispatch_gate("@c", "fp_2", "n", now=_T0 + 302) in ("held_open", "tripped")
    assert er.dispatch_gate("@c", "fp_3", "n", now=_T0 + 301 + 300) == "probe"


def test_a_failed_probe_reopens_with_double_cooldown(tmp_path: Path) -> None:
    _seed_registry(tmp_path)
    er = _import_registry()
    _trip(er)
    t = _T0 + 301
    assert er.dispatch_gate("@c", "fp_probe", "n", now=t) == "probe"

    er.circuit_breaker_send_failed(now=t)

    status = er.get_circuit_breaker_status(now=t)
    assert (status["state"], status["cooldown_seconds"], status["opened_at"]) == ("open", 600, t)


def test_a_marked_fault_is_one_row_whatever_its_tail_and_an_unmarked_line_is_its_own_new_row(tmp_path: Path) -> None:
    _seed_registry(tmp_path)
    er = _import_registry()
    marked = "handler error fault[UserPromptSubmit.h.navmap.handle.KeyError@navmap.py]"

    rows = [
        er.report("ERROR", marked + " handle line 7", "hooks"),
        er.report("ERROR", marked + " line 8: 'session_ab'", "hooks"),
        er.report("ERROR", marked + " line 9: unknown command", "hooks"),
    ]
    unmarked = er.report("ERROR", "unknown command x", "hooks")

    assert len({row["fingerprint"] for row in rows}) == 1
    assert (rows[-1]["count"], rows[-1]["status"]) == (3, "new")
    assert unmarked["fingerprint"] != rows[0]["fingerprint"]
    assert (unmarked["status"], unmarked["suppress_reason"]) == ("new", "")


def test_an_unmarked_line_keeps_todays_normalizer() -> None:
    assert er.normalize_message("bad at /a/b.py line 7") == "bad at <path> line N"


def test_get_dispatch_count_unknown_fingerprint_is_zero(tmp_path: Path) -> None:
    """A fingerprint nobody has dispatched reads as 0, never a KeyError.

    The escalation lane calls it on every repeating error; a raise would take the count down."""
    _seed_registry(tmp_path)
    er = _import_registry()

    assert er.get_dispatch_count("never_seen_fingerprint") == 0


def test_get_dispatch_count_increments_with_record_dispatch(tmp_path: Path) -> None:
    """Each recorded dispatch is visible to the next reader."""
    _seed_registry(tmp_path)
    er = _import_registry()

    fp = "escalation_view_fp"
    assert er.get_dispatch_count(fp) == 0

    er.record_dispatch(fp)
    assert er.get_dispatch_count(fp) == 1

    er.record_dispatch(fp)
    assert er.get_dispatch_count(fp) == 2


def test_get_dispatch_count_is_per_fingerprint(tmp_path: Path) -> None:
    """One error's dispatches never make another error look answered."""
    _seed_registry(tmp_path)
    er = _import_registry()

    er.record_dispatch("fp_dispatched")

    assert er.get_dispatch_count("fp_dispatched") == 1
    assert er.get_dispatch_count("fp_untouched") == 0


def test_get_dispatch_count_matches_the_backing_counter(tmp_path: Path) -> None:
    """It is a read-only view: the same number backoff itself uses."""
    _seed_registry(tmp_path)
    er = _import_registry()

    fp = "backing_counter_fp"
    er.record_dispatch(fp)
    er.record_dispatch(fp)

    assert er.get_dispatch_count(fp) == 2
    # Backoff reads the same counter: one minute short of the count-2 backoff, still held
    assert er.should_dispatch(fp, now=time.time() + er.get_backoff_seconds(2) - 60) is False


def test_get_dispatch_count_does_not_mutate_state(tmp_path: Path) -> None:
    """Reading the count must never create an entry for an unknown fingerprint."""
    _seed_registry(tmp_path)
    er = _import_registry()

    er.get_dispatch_count("read_only_fp")

    assert not er.CB_STATE_FILE.exists()


_STALE = "2020-01-01T00:00:00"
_WRITERS = {
    "update_status": (lambda: er.update_status("a" * 40, "resolved"), lambda e: e["a" * 40]["status"] == "resolved"),
    "update_source_fix_status": (
        lambda: er.update_source_fix_status("a" * 40, "fix_requested"),
        lambda e: e["a" * 40]["source_fix_status"] == "fix_requested",
    ),
    "clear_resolved": (lambda: er.clear_resolved(days=7), lambda e: "b" * 40 not in e),
    "purge_stale": (lambda: er.purge_stale(days=30), lambda e: "b" * 40 not in e),
}


class TestRegistryWritersHoldTheLock:
    """Every read-modify-write of the registry holds its lock, as report() does, or a concurrent write is lost."""

    @pytest.mark.parametrize("writer", sorted(_WRITERS))
    def test_a_writer_waits_for_the_lock_and_keeps_a_concurrent_entry(self, tmp_path: Path, writer: str) -> None:
        call, landed = _WRITERS[writer]
        now = datetime.now().isoformat()
        _seed_registry(
            tmp_path,
            {
                "a" * 40: {"fingerprint": "a" * 40, "status": "new", "source_fix_status": "none", "last_seen": now},
                "b" * 40: {"fingerprint": "b" * 40, "status": "resolved", "last_seen": _STALE},
            },
        )
        worker = threading.Thread(target=call)
        with er.json_file_lock(er.REGISTRY_FILE):
            worker.start()
            worker.join(timeout=0.5)
            assert worker.is_alive(), f"{writer} ran while the registry lock was held"
            data = json.loads(er.REGISTRY_FILE.read_text(encoding="utf-8"))
            data["errors"]["c" * 40] = {"fingerprint": "c" * 40, "status": "new", "last_seen": now}
            er.REGISTRY_FILE.write_text(json.dumps(data), encoding="utf-8")
        worker.join(timeout=10)

        errors = json.loads(er.REGISTRY_FILE.read_text(encoding="utf-8"))["errors"]
        assert landed(errors), f"{writer} did not apply its change"
        assert "c" * 40 in errors, f"{writer} wrote back a stale read and lost the concurrent entry"


def _write_other_process_state(breaker_state: str, per_fingerprint: dict) -> None:
    """Stand in for a second process (a CLI reset, a ci poll) writing the shared breaker file."""
    er.CB_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    er.CB_STATE_FILE.write_text(
        json.dumps({"circuit_breaker": {"state": breaker_state, "opened_at": 0.0}, "per_fingerprint": per_fingerprint}),
        encoding="utf-8",
    )


class TestBreakerFileIsTheTruth:
    """Breaker and backoff state live in the file, so every process sees the others' writes."""

    def test_a_dispatch_saved_by_another_process_survives_this_ones_save(self) -> None:
        er.record_dispatch("fp_daemon")
        on_disk = json.loads(er.CB_STATE_FILE.read_text(encoding="utf-8"))["per_fingerprint"]
        _write_other_process_state("closed", {**on_disk, "fp_ci_poll": {"last_dispatch": time.time(), "count": 1}})

        er.record_dispatch("fp_daemon_again")

        assert er.get_dispatch_count("fp_ci_poll") == 1
        assert er.get_dispatch_count("fp_daemon") == 1
        assert er.should_dispatch("fp_ci_poll") is False

    def test_a_reset_by_another_process_reopens_dispatch_here(self) -> None:
        _trip(er)
        assert er.dispatch_gate("@c", "fp_c", "n", now=_T0) == "tripped"

        _write_other_process_state("closed", {})

        assert er.dispatch_gate("@c", "fp_c", "n", now=_T0) == "send"

    def test_reset_closes_the_breaker_and_keeps_backoff(self) -> None:
        er.record_dispatch("fp_backed_off")
        _trip(er)

        er.circuit_breaker_reset()

        assert er.dispatch_gate("@c", "fp_c", "n", now=_T0) == "send"
        assert er.should_dispatch("fp_backed_off") is False

    def test_a_threshold_trip_opens_at_the_handed_in_clock(self) -> None:
        _trip(er, now=_T0)

        assert er.get_circuit_breaker_status(now=_T0)["opened_at"] == _T0


def test_a_prefix_matching_two_rows_finds_neither_but_a_full_fingerprint_still_does(tmp_path: Path) -> None:
    first, second = "ab1" + "0" * 37, "ab2" + "0" * 37
    _seed_registry(
        tmp_path, {first: {"fingerprint": first, "status": "new"}, second: {"fingerprint": second, "status": "new"}}
    )

    assert er.get_entry("ab") is None
    assert er.update_status("ab", "suppressed") is False
    full, prefixed = er.get_entry(second), er.get_entry("ab1")
    assert full is not None and full["fingerprint"] == second
    assert prefixed is not None and prefixed["fingerprint"] == first


def test_purge_keeping_suppressed_drops_stale_rows_but_not_suppressed_ones(tmp_path: Path) -> None:
    stale = "2025-01-01T00:00:00"
    _seed_registry(
        tmp_path,
        {
            "s" * 40: {"fingerprint": "s" * 40, "status": "suppressed", "last_seen": stale},
            "n" * 40: {"fingerprint": "n" * 40, "status": "new", "last_seen": stale},
        },
    )

    assert er.purge_stale(30, keep_suppressed=True) == 1
    assert list(json.loads(er.REGISTRY_FILE.read_text(encoding="utf-8"))["errors"]) == ["s" * 40]
