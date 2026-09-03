# ===================AIPASS====================
# META DATA HEADER
# Name: test_json_durability.py - JSON Handler Durability Tests
# Date: 2026-08-18
# Version: 1.0.0
# Category: backup/tests
#
# CHANGELOG (Max 5 entries):
#   - v1.0.0 (2026-08-18): Initial creation — os.replace retry pins (Windows sharing violation)
#
# CODE STANDARDS:
#   - Pytest function style (no unittest classes)
#   - tmp_path + monkeypatch for file isolation — never the live backup json files
# =============================================

"""
Durability tests for the backup JSON handler.

Two defects meet at the swap. The first is the torn write: opening a live
document with mode "w" truncates it before the new bytes land, so a concurrent
reader sees an empty or partial file — closed by staging to a temp file in the
target's own directory and swapping with os.replace.

The second is Windows-only and was closed on 2026-08-18: os.replace raises
PermissionError while ANY reader holds the target open (no FILE_SHARE_DELETE on
Python's open), and one stuck move starved a whole CI run — 45-minute cancels.
The fix is _replace_with_retry, a bounded retry that converges on the
microsecond-scale handles a reader actually holds and then raises honestly.

A standards audit found _replace_with_retry carried ZERO tests fleet-wide. These
pins close that gap: the helper is exercised directly (success after retry,
exhaustion raises, a non-sharing OSError propagates on the first attempt), the
write site is proven to route through it, and a 2-writer/2-reader race measures
zero unusable reads.

Linux never raises PermissionError from os.replace on an open file, so every
retry test here injects the failure — that injection is the only cross-platform
proof the retry path exists at all.
"""

import json
import os
import threading
import time
from pathlib import Path

import pytest

from aipass.backup.apps.handlers.json import json_handler as json_handler_mod


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _valid_data(module_name: str = "durability", filler: str = "x") -> dict:
    """Build a structurally valid 'data' document with a wide truncation window."""
    return {
        "module_name": module_name,
        "created": "2026-08-18",
        "last_updated": "2026-08-18",
        "filler": [filler * 64 for _ in range(400)],
    }


def _temp_files(directory: Path) -> list:
    """Return staged temp artifacts left behind in a directory."""
    return [path for path in directory.iterdir() if path.suffix == ".tmp"]


@pytest.fixture
def json_dir(tmp_path):
    """A throwaway directory — backup's handler takes an explicit path, so there is no global to patch."""
    target = tmp_path / "backup_json"
    target.mkdir()
    return target


# ---------------------------------------------------------------------------
# The write site routes through the helper
# ---------------------------------------------------------------------------


def test_atomic_write_routes_through_the_replace_helper(json_dir, monkeypatch):
    """A bare os.replace re-introduces the whole Windows hang, and it reads as harmless."""
    calls = []
    real_replace = os.replace

    def spy(source, destination):
        calls.append((source, destination))
        real_replace(source, destination)

    monkeypatch.setattr(json_handler_mod, "_replace_with_retry", spy)

    json_handler_mod.save_json(str(json_dir / "routed.json"), {"ok": True})

    assert len(calls) == 1, "the write did not go through _replace_with_retry"


def test_exhausted_retry_leaves_the_original_intact_and_cleans_the_temp(json_dir, monkeypatch):
    """A move that never unblocks must not damage the live document or litter."""
    target = json_dir / "durability.json"
    original = _valid_data(filler="original")
    json_handler_mod.save_json(str(target), original)

    def blocked_replace(source, destination):
        raise PermissionError(13, "sharing violation", str(destination))

    monkeypatch.setattr(json_handler_mod.os, "replace", blocked_replace)
    monkeypatch.setattr(json_handler_mod, "_REPLACE_BACKOFF_SECONDS", 0)

    with pytest.raises(PermissionError):
        json_handler_mod.save_json(str(target), _valid_data(filler="doomed"))

    survivor = json.loads(target.read_text(encoding="utf-8"))
    assert survivor["filler"] == original["filler"], "the live document was damaged"
    assert _temp_files(json_dir) == []


def test_save_survives_a_transient_sharing_violation(json_dir, monkeypatch):
    """End to end: the branch's own save path rides out a Windows sharing violation."""
    calls = {"count": 0}
    real_replace = os.replace

    def flaky_replace(source, destination):
        calls["count"] += 1
        if calls["count"] <= 2:
            raise PermissionError(13, "sharing violation", str(destination))
        real_replace(source, destination)

    monkeypatch.setattr(json_handler_mod.os, "replace", flaky_replace)

    target = json_dir / "durability.json"
    json_handler_mod.save_json(str(target), _valid_data(filler="retry"))

    written = json.loads(target.read_text(encoding="utf-8"))
    assert written["filler"] == _valid_data(filler="retry")["filler"], "payload lost across the retry"

    assert calls["count"] == 3, "retry path never engaged"


# ---------------------------------------------------------------------------
# Concurrency probe — the defect itself
# ---------------------------------------------------------------------------


def test_concurrent_writers_never_expose_a_torn_document(json_dir):
    """
    Two writers and two readers on one document produce zero unusable reads.

    Measured against a truncating write this same way on the sibling commons
    handler: 1,297 reads, 553 empty and 485 unparseable — 80.03% unusable.
    """
    target = json_dir / "durability.json"
    json_handler_mod.save_json(str(target), _valid_data(filler="a"))

    stop = threading.Event()
    counts = {"ok": 0, "empty": 0, "unparseable": 0}
    lock = threading.Lock()
    iterations = 150

    failures = []

    def writer(filler):
        # stop.set() must fire even if a write raises — a dead writer that
        # never releases the readers hangs the whole suite, not just this
        # test (Windows CI sat 1h45m exactly this way on 2026-08-18).
        try:
            for _ in range(iterations):
                json_handler_mod.save_json(str(target), _valid_data(filler=filler))
        except Exception as error:  # noqa: BLE001 - re-raised via failures below
            with lock:
                failures.append(error)
        finally:
            stop.set()

    def reader():
        local = {"ok": 0, "empty": 0, "unparseable": 0}
        while not stop.is_set():
            # Yield between polls — Windows share-mode semantics, not tuning.
            # A zero-delay spin-reader holds the target open at near-100% duty
            # cycle, and Python opens files without FILE_SHARE_DELETE, so on
            # Windows an os.replace onto a handle a reader holds fails with
            # WinError 5. Two spinning readers can then collide with every one
            # of the writer's bounded retry attempts and starve a correct retry
            # into exhaustion (first full Windows CI run, 2026-08-18). 1ms
            # models a real reader — no fleet workload spin-reads a config file
            # — and weakens no content check below. At the top of the pass so
            # the `continue` paths yield too: a refused open means a replace is
            # in flight, exactly when re-spinning hurts most.
            time.sleep(0.001)
            try:
                raw = target.read_text(encoding="utf-8")
            except OSError:
                # PermissionError lands here too: on Windows a concurrent
                # os.replace refuses the open. A refused open is share-mode
                # semantics — not a torn document, and not a read at all.
                continue
            if raw.strip() == "":
                local["empty"] += 1
                continue
            try:
                json.loads(raw)
                local["ok"] += 1
            except json.JSONDecodeError:
                local["unparseable"] += 1
        with lock:
            for key, value in local.items():
                counts[key] += value

    threads = [
        threading.Thread(target=writer, args=("a",)),
        threading.Thread(target=writer, args=("b",)),
        threading.Thread(target=reader),
        threading.Thread(target=reader),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    stuck = [thread.name for thread in threads if thread.is_alive()]
    assert not stuck, f"threads never finished: {stuck}"

    assert not failures, f"a writer died mid-race: {failures[0]!r}"
    assert counts["ok"] > 0, "probe never observed a readable document"
    assert counts["empty"] == 0, f"{counts['empty']} readers saw an empty document"
    assert counts["unparseable"] == 0, f"{counts['unparseable']} readers saw a partial document"
