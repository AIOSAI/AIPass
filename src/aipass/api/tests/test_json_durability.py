# =================== AIPass ====================
# Name: test_json_durability.py
# Description: JSON Handler Durability Tests — writes that survive readers
# Version: 1.0.0
# Created: 2026-08-16
# Modified: 2026-08-16
# =============================================

"""
JSON Handler Durability Tests.

These guard the two ways a shared JSON document is lost rather than saved,
both reproduced against the unfixed handler before any of this was written
(error 90c9e40d, 38 occurrences since 2026-06-12):

    A READER CAUGHT MID-WRITE saw an empty file, because a write that opens
    the target with "w" truncates it before a single byte of the new content
    lands. Measured on the real handler: 8,279 of 36,129 concurrent reads
    came back unparseable, and the handler's own recovery path then wrote a
    fresh TEMPLATE over the live document — the corruption cured itself by
    deleting the data.

    TWO WRITERS APPENDING lost each other's entries, because log_operation
    reads the whole log, appends one entry, and writes the whole log back.
    Measured below the rotation cap: 4 threads asking for 80 entries left 4
    on disk.

Kept in this branch's own file rather than test_json_handler.py, which is a
seedgo universal template that gets re-synced.
"""

import importlib
import json
import sys
import threading
import types
from pathlib import Path
from typing import Any, List

import pytest


# ---------------------------------------------------------------------------
# Import the handler the way the template does — the handlers package guard
# refuses a cross-branch import, so the package is stubbed to its own path.
# ---------------------------------------------------------------------------

_HANDLER_PKG = "aipass.api.apps.handlers"
_MODULE_PATH = "aipass.api.apps.handlers.json.json_handler"

if _HANDLER_PKG not in sys.modules:
    _stub = types.ModuleType(_HANDLER_PKG)
    _handlers_dir = Path(__file__).resolve().parents[3] / "aipass" / "api" / "apps" / "handlers"
    _stub.__path__ = [str(_handlers_dir)]
    sys.modules[_HANDLER_PKG] = _stub

json_handler = importlib.import_module(_MODULE_PATH)


@pytest.fixture(autouse=True)
def isolate_json_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Every write in this file lands in tmp_path, never in api_json/."""
    monkeypatch.setattr(json_handler, "API_JSON_DIR", tmp_path)
    return tmp_path


@pytest.fixture(autouse=True)
def quiet(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Silence the handler's own logger.

    Not cosmetic: these tests deliberately drive the failure paths, and a real
    logger would write the exact ERROR line @trigger watches for into the
    branch log — a passing suite must not raise an incident.
    """
    monkeypatch.setattr(json_handler.logger, "warning", lambda *a, **k: None)
    monkeypatch.setattr(json_handler.logger, "error", lambda *a, **k: None)


# ============================================================================
# A reader is never handed a half-written document
# ============================================================================


class TestAWriteIsAllOrNothing:
    """
    The target file must never exist in a state no reader can parse.

    A truncated document is worse than a stale one: stale data is still data,
    while an unparseable file sends the handler down its regenerate path,
    which replaces the live document with an empty template.
    """

    def test_a_reader_during_the_write_still_sees_the_previous_document(self, tmp_path: Path) -> None:
        """
        Mid-write, the file on disk still holds the OLD content.

        This is the reported bug in one assertion. The read happens from
        inside json.dump, which is precisely the window a concurrent reader
        hits — under a truncating write it comes back empty.
        """
        json_handler.save_json("racy", "log", [{"entry": "first"}])
        target = json_handler.get_json_path("racy", "log")

        observed: List[Any] = []
        real_dump = json_handler.json.dump

        def dump_and_peek(data: Any, stream: Any, **kwargs: Any) -> None:
            observed.append(target.read_bytes())
            real_dump(data, stream, **kwargs)

        json_handler.json.dump = dump_and_peek
        try:
            json_handler.save_json("racy", "log", [{"entry": "second"}])
        finally:
            json_handler.json.dump = real_dump

        assert observed, "json.dump was never called — the probe missed the write"
        assert json.loads(observed[0].decode("utf-8")) == [{"entry": "first"}]

    def test_a_write_that_dies_mid_dump_leaves_the_previous_document_intact(self, tmp_path: Path) -> None:
        """
        A crash during serialization must not destroy what was already saved.

        With a truncating write the file is already empty by the time the
        error is raised, so a process killed at the wrong instant takes the
        document with it. The old content is the correct survivor.
        """
        json_handler.save_json("crashy", "log", [{"entry": "survivor"}])
        target = json_handler.get_json_path("crashy", "log")

        real_dump = json_handler.json.dump

        def dump_then_die(data: Any, stream: Any, **kwargs: Any) -> None:
            raise RuntimeError("serialization died halfway")

        json_handler.json.dump = dump_then_die
        try:
            saved = json_handler.save_json("crashy", "log", [{"entry": "replacement"}])
        finally:
            json_handler.json.dump = real_dump

        assert saved is False, "a write that raised must report failure, never True"
        assert json.loads(target.read_text(encoding="utf-8")) == [{"entry": "survivor"}]

    def test_a_successful_write_leaves_no_scratch_file_behind(self, tmp_path: Path) -> None:
        """
        Writing through a temp file is an implementation detail, not litter.

        A stray .tmp beside every document would be read by anything that
        globs the directory, and would grow one file per write forever.
        """
        json_handler.save_json("tidy", "log", [{"entry": "one"}])
        json_handler.save_json("tidy", "log", [{"entry": "two"}])

        leftovers = [p.name for p in tmp_path.iterdir() if p.suffix == ".tmp"]
        assert leftovers == []

    def test_a_failed_write_cleans_up_its_scratch_file(self, tmp_path: Path) -> None:
        """
        The failure path tidies up too.

        Otherwise every failed write leaves a partial file in the directory
        the handler itself reads from.
        """
        json_handler.save_json("tidy_fail", "log", [{"entry": "one"}])

        real_dump = json_handler.json.dump

        def dump_then_die(data: Any, stream: Any, **kwargs: Any) -> None:
            raise RuntimeError("serialization died halfway")

        json_handler.json.dump = dump_then_die
        try:
            json_handler.save_json("tidy_fail", "log", [{"entry": "two"}])
        finally:
            json_handler.json.dump = real_dump

        leftovers = [p.name for p in tmp_path.iterdir() if p.suffix == ".tmp"]
        assert leftovers == []

    def test_the_template_write_is_atomic_too(self, tmp_path: Path) -> None:
        """
        First creation goes through the same door.

        ensure_json_exists writes the default template, and it runs on the
        SAME files the server is reading — the regenerate path is exactly
        where the reported corruption cascaded from.
        """
        real_dump = json_handler.json.dump
        observed: List[bool] = []

        def dump_and_peek(data: Any, stream: Any, **kwargs: Any) -> None:
            observed.append(json_handler.get_json_path("fresh", "log").exists())
            real_dump(data, stream, **kwargs)

        json_handler.json.dump = dump_and_peek
        try:
            json_handler.ensure_json_exists("fresh", "log")
        finally:
            json_handler.json.dump = real_dump

        assert observed == [False], "the target existed mid-dump — the template was written in place"
        assert json.loads(json_handler.get_json_path("fresh", "log").read_text(encoding="utf-8")) == []


# ============================================================================
# Two writers appending do not overwrite each other
# ============================================================================


class TestConcurrentAppendsKeepEveryEntry:
    """
    log_operation is a read-modify-write, so two callers can read the same
    document, each append one entry, and each write back a version missing
    the other's. The live host API serves requests on a thread pool and logs
    on every one of them, which makes this the ordinary case here rather than
    an exotic one.
    """

    def test_four_threads_appending_lose_nothing(self, tmp_path: Path) -> None:
        """
        Every entry asked for is on disk afterwards.

        Deliberately below the 100-entry rotation cap: above it the handler
        drops old entries BY DESIGN, and a test that cannot tell rotation
        from loss proves nothing.
        """
        writers, each = 4, 20
        json_handler.ensure_module_jsons("busy")

        def append(tag: int) -> None:
            for index in range(each):
                json_handler.log_operation("tick", {"who": tag, "i": index}, module_name="busy")

        threads = [threading.Thread(target=append, args=(tag,)) for tag in range(writers)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        entries = json.loads(json_handler.get_json_path("busy", "log").read_text(encoding="utf-8"))
        assert len(entries) == writers * each

    def test_rotation_still_trims_to_the_cap(self, tmp_path: Path) -> None:
        """
        Keeping every entry must not mean keeping them forever.

        The guard above would also pass if serialization stopped rotating, so
        this pins the other side: past the cap, the oldest entries go.
        """
        json_handler.ensure_module_jsons("rotating")
        for index in range(120):
            json_handler.log_operation("tick", {"i": index}, module_name="rotating")

        entries = json.loads(json_handler.get_json_path("rotating", "log").read_text(encoding="utf-8"))
        assert len(entries) == 100
        assert entries[-1]["data"]["i"] == 119

    def test_two_files_do_not_wait_on_each_other(self, tmp_path: Path) -> None:
        """
        The serialization is per document, not one global gate.

        Every module in this branch logs through this handler, including the
        request path of a live server: a single global lock would serialize
        unrelated modules behind whichever one is slowest to write.
        """
        json_handler.ensure_module_jsons("first")
        json_handler.ensure_module_jsons("second")

        held = threading.Event()
        release = threading.Event()

        def slow_writer() -> None:
            real_dump = json_handler.json.dump

            def dump_and_hold(data: Any, stream: Any, **kwargs: Any) -> None:
                real_dump(data, stream, **kwargs)
                # Only the 'slow' append is held. The shim is global, so a
                # blanket hold would stall the very writer this test is timing
                # and pass for the wrong reason. Keyed on the entry rather than
                # the stream: an atomic write dumps into a temp file opened by
                # descriptor, whose .name is a number, not a path.
                if isinstance(data, list) and data and data[-1].get("operation") == "slow":
                    held.set()
                    release.wait(timeout=5)

            json_handler.json.dump = dump_and_hold
            try:
                json_handler.log_operation("slow", module_name="first")
            finally:
                json_handler.json.dump = real_dump

        blocker = threading.Thread(target=slow_writer)
        blocker.start()
        assert held.wait(timeout=5), "the slow writer never reached its write"

        # The other document must be writable while the first one is held.
        done = threading.Event()

        def other_writer() -> None:
            json_handler.log_operation("quick", module_name="second")
            done.set()

        runner = threading.Thread(target=other_writer)
        runner.start()
        overtook = done.wait(timeout=5)

        release.set()
        blocker.join(timeout=5)
        runner.join(timeout=5)

        assert overtook, "a write to 'second' waited on a write to 'first'"
