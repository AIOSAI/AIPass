# =================== AIPass ====================
# Name: test_json_handler_contract_durability.py
# Description: json_handler contract, durability clause: public writer, concurrency
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-11-02
# =============================================

"""Tests for every branch's apps/handlers/json/json_handler.py writer."""

# The declared pass — what is NOT tested here, and what covers it instead:
# sentry: no-test-needed(stdlib) — os.replace's own atomicity

import copy
import json
import threading
from pathlib import Path
from typing import Any, Callable

import pytest

from aipass.sentry.tests.support_json_handler_contract import (
    DATA_PAYLOAD,
    TORN_DOCUMENT_OBSERVED,
    implementation,
    parametrized,
    prepared,
    require_one_service,
    required_positionals,
)

pytestmark = pytest.mark.usefixtures("quarantined_document_directories")


def public_writer(branch: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Any, Callable, Path]:
    """A branch's public writer, normalised across both calling conventions."""
    require_one_service(branch)
    module = implementation(branch)
    if required_positionals(module.save_json) == 3:
        module, _ = prepared(branch, tmp_path, monkeypatch)
        document = Path(str(module.get_json_path("durability", "data")))
        return module, lambda payload: module.save_json("durability", "data", payload), document
    document = tmp_path / "durability.json"
    return module, lambda payload: module.save_json(str(document), payload), document


def stray_temps(directory: Path) -> list:
    """Staging files left behind in a document directory."""
    if not directory.is_dir():
        return []
    return sorted(child.name for child in directory.iterdir() if child.suffix != ".json")


#: Writers, and writes each performs. Small on purpose: a torn write fails on its FIRST occurrence,
#: and more threads only add flake surface.
CONCURRENT_WRITERS = 4
WRITES_PER_WRITER = 5

#: Ceiling on sampler loops, so a dead writer cannot hang the run; nothing asserts on elapsed time.
MAX_SAMPLES = 4000

#: Join ceiling: a deadlocked writer fails rather than hangs; nothing passes or fails on duration.
THREAD_JOIN_SECONDS = 60


@pytest.mark.parametrize("branch", parametrized(TORN_DOCUMENT_OBSERVED))
def test_concurrent_writers_never_expose_a_torn_document(branch: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A reader during a write sees the old document or the new one, never half.

    A race that did not race SKIPS with its counters; evidence of a tear is always RED.
    """
    module, save, document = public_writer(branch, tmp_path, monkeypatch)
    save(copy.deepcopy(DATA_PAYLOAD))

    torn: list = []
    failures: list = []
    unreadable: list = []
    writes = {"done": 0}
    sampled = {"count": 0}
    finished = threading.Event()

    def writer(seat: int) -> None:
        for round_number in range(WRITES_PER_WRITER):
            payload = {**copy.deepcopy(DATA_PAYLOAD), "counters": {"seen": seat * 100 + round_number}}
            try:
                save(payload)
                writes["done"] += 1
            except Exception as error:  # recorded and re-reported below
                failures.append(f"writer {seat}: {type(error).__name__}: {error}")

    def sampler() -> None:
        for _ in range(MAX_SAMPLES):
            if finished.is_set():
                return
            try:
                raw = document.read_bytes()
            except (FileNotFoundError, PermissionError) as error:
                # Not swallowed: a read that could not happen is evidence of how thin the race was, so it is
                # counted into the skip message.
                unreadable.append(f"{type(error).__name__}: {error}")
                continue
            sampled["count"] += 1
            if not raw.strip():
                torn.append("empty document observed mid-write")
                continue
            try:
                json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                torn.append(f"unparseable document observed mid-write: {error}")

    watcher = threading.Thread(target=sampler, daemon=True)
    watcher.start()
    writers = [threading.Thread(target=writer, args=(seat,)) for seat in range(CONCURRENT_WRITERS)]
    for thread in writers:
        thread.start()
    for thread in writers:
        thread.join(timeout=THREAD_JOIN_SECONDS)
    finished.set()
    watcher.join(timeout=THREAD_JOIN_SECONDS)
    stuck = [thread.name for thread in writers if thread.is_alive()]

    assert not stuck, f"{branch}: writers never finished: {stuck}"
    assert not torn, f"{branch}: reader observed a torn document — {torn[:3]}"
    assert not failures, f"{branch}: a concurrent write raised — {failures[:3]}"

    final = document.read_bytes()
    assert final.strip(), f"{branch}: the document is empty after the race"
    json.loads(final.decode("utf-8"))
    assert stray_temps(document.parent) == [], f"{branch}: staging files survived the race"

    if sampled["count"] == 0 or writes["done"] == 0:
        pytest.skip(
            f"{branch}: the race did not race — "
            f"{writes['done']} writes completed, {sampled['count']} samples read, "
            f"{len(unreadable)} reads could not happen; "
            f"nothing was observed concurrently, so no tear could have been seen"
        )
