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

import errno
import importlib
import json
import sys
import threading
import types
from pathlib import Path
from typing import Any, List
from unittest.mock import MagicMock

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


# ============================================================================
# A create cannot bury an entry — the cross-process axis (@trigger, 2026-08-19)
# ============================================================================


class TestCreatingADocumentNeverOverwritesOne:
    """
    The third door, found on @trigger's tree and reported to mine.

    Their Linux CI lost 1 of 100 concurrent appends overnight, and it was not
    the reader-mid-write species or the two-writers species already pinned
    above. `ensure_json_exists` implemented "create if missing" as a REPLACING
    write: two callers both find the document absent, both stage an empty
    template, and the slower one's template lands on top of whatever was
    written in between. No corruption, no refused read, no unusual timing —
    just two callers starting near each other with the file not yet there,
    which is the normal shape of a module's first log call.

    THIS BRANCH HAD HALF THE GUARD. `ensure_module_jsons` is called from
    INSIDE log_operation's document lock, which closes the race between two
    threads. But `_document_lock` is a threading.Lock and every `drone @api`
    invocation is its own process, so across processes the create was wide
    open — and load_json reaches ensure_json_exists with no lock at all.

    The cure needs no lock, which is why it is worth having while the
    cross-process axis still waits on a fleet ruling: stage to a temp file and
    os.link it into place. Create-or-fail — a caller who loses writes NOTHING —
    and a linked file is complete the instant it appears, so there is no empty
    window for a reader to read as corruption.
    """

    def test_a_staged_create_does_not_bury_an_entry_written_meanwhile(
        self,
        isolate_json_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The race, run deterministically rather than hoped for.

        The interleaving is forced at the seam where it really happens: one
        caller has OBSERVED the document absent and is building its template
        when a second caller creates the document and appends a real entry.
        Against a replacing create, the first caller's empty template lands on
        top and the entry is gone. Reproduced this way against the unfixed
        handler before the fix was written.
        """
        staged = threading.Event()
        appended = threading.Event()
        real_default = json_handler._create_default

        def _pause_between_observing_and_writing(json_type: str, module_name: str) -> Any:
            template = real_default(json_type, module_name)
            if json_type == "log" and not staged.is_set():
                staged.set()
                # Hold here: the document is absent as far as this caller knows,
                # and its write has not happened yet. This is the whole window.
                assert appended.wait(timeout=10)
            return template

        monkeypatch.setattr(json_handler, "_create_default", _pause_between_observing_and_writing)

        loser: List[Any] = []

        def _slow_creator() -> None:
            loser.append(json_handler.ensure_json_exists("racer", "log"))

        creator = threading.Thread(target=_slow_creator)
        creator.start()
        try:
            assert staged.wait(timeout=10), "the slow creator never reached the window"

            # The other caller, standing in for another process: it creates the
            # document and writes a real entry while the first is still staging.
            monkeypatch.setattr(json_handler, "_create_default", real_default)
            assert json_handler.log_operation("kept", {"n": 1}, "racer") is True
        finally:
            appended.set()
            creator.join(timeout=10)

        entries = json.loads((isolate_json_dir / "racer_log.json").read_text(encoding="utf-8"))

        assert loser == [True], "the losing create reported failure to a caller that did nothing wrong"
        assert [entry["operation"] for entry in entries] == ["kept"], (
            "the entry was buried by a create that arrived after it"
        )

    def test_the_loser_of_a_create_writes_nothing_at_all(
        self,
        isolate_json_dir: Path,
    ) -> None:
        """Create-or-fail, asked of the helper directly.

        The distinction that matters: losing is not an error. A caller who
        loses the race got what it wanted — the document exists — so it must
        neither raise nor overwrite.
        """
        target = isolate_json_dir / "already_there.json"

        assert json_handler.atomic_create_json(target, {"first": True}) is True
        assert json_handler.atomic_create_json(target, {"second": True}) is False

        assert json.loads(target.read_text(encoding="utf-8")) == {"first": True}

    def test_a_created_document_is_complete_the_instant_it_appears(
        self,
        isolate_json_dir: Path,
    ) -> None:
        """No empty window. A reader sees the whole document or no file.

        The reason this is a link rather than a truncate-and-write: this
        handler answers an unreadable document by regenerating a template over
        it, so an empty window is not a transient read failure, it is data
        loss one recovery later.
        """
        target = isolate_json_dir / "complete.json"
        payload = {"module_name": "x", "version": "1.0.0", "config": {"enabled": True}}

        seen: List[Any] = []
        stop = threading.Event()

        def _watch() -> None:
            while not stop.is_set():
                if target.exists():
                    try:
                        seen.append(json.loads(target.read_text(encoding="utf-8")))
                    except (ValueError, OSError):
                        seen.append("UNREADABLE")
                    return

        watcher = threading.Thread(target=_watch)
        watcher.start()
        try:
            json_handler.atomic_create_json(target, payload)
        finally:
            stop.set()
            watcher.join(timeout=10)

        assert "UNREADABLE" not in seen
        assert seen in ([payload], []), f"a reader saw something other than the finished document: {seen}"

    def test_no_temp_file_is_left_behind(self, isolate_json_dir: Path) -> None:
        """The link leaves a SECOND name for the same bytes — unlink it.

        Missed, this directory fills with temp files that the handler's own
        glob-and-read paths would then find.
        """
        target = isolate_json_dir / "tidy.json"

        json_handler.atomic_create_json(target, {"a": 1})
        json_handler.atomic_create_json(target, {"b": 2})

        assert sorted(path.name for path in isolate_json_dir.iterdir()) == ["tidy.json"]

    def test_a_link_less_filesystem_degrades_and_says_so(
        self,
        isolate_json_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Degrade, never fail — and never silently.

        A filesystem with no hard links still needs a working handler. It gets
        the old replacing write and a log line saying the guarantee is reduced,
        because a weaker guarantee nobody was told about is the one that gets
        relied on.
        """
        warned: List[str] = []
        monkeypatch.setattr(json_handler.logger, "warning", lambda *a, **k: warned.append(str(a)))
        monkeypatch.setattr(
            json_handler.os,
            "link",
            MagicMock(side_effect=OSError(errno.EPERM, "hard links not supported")),
        )

        target = isolate_json_dir / "no_links.json"

        assert json_handler.atomic_create_json(target, {"a": 1}) is True
        assert json.loads(target.read_text(encoding="utf-8")) == {"a": 1}
        assert warned, "the filesystem degraded the guarantee and nothing said so"

    def test_the_branch_follows_what_was_observed_not_a_second_look(
        self,
        isolate_json_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """@trigger's own first fix was wrong this way, and said so.

        Choosing create-vs-regenerate with a SECOND exists() check is the same
        check-then-act one line lower: the racing writer creates the file
        inside that window, the branch takes the overwrite path, and the entry
        dies exactly as before.

        So this watches WHICH WRITER RAN, not what ended up on disk. The first
        version of this test read the file afterwards and passed against the
        unfixed handler — both writers leave the same empty template, so the
        bytes cannot tell them apart. Every look after the first is forced to
        answer "present", which is precisely what a racing writer would make
        the world say.
        """
        target = isolate_json_dir / "observed_log.json"
        looks: List[str] = []
        real_exists = Path.exists

        def _counted_exists(self: Path) -> bool:
            if self == target:
                looks.append("looked")
                # Every look after the first says "present" — a second check
                # would see the racing writer's file and switch branches.
                if len(looks) > 1:
                    return True
            return real_exists(self)

        monkeypatch.setattr(Path, "exists", _counted_exists)

        used: List[str] = []
        real_create = json_handler.atomic_create_json
        real_replace = json_handler._atomic_write_json

        def _spy_create(path: Path, data: Any) -> bool:
            used.append("create-or-fail")
            return real_create(path, data)

        def _spy_replace(path: Path, data: Any) -> None:
            used.append("replacing-write")
            return real_replace(path, data)

        monkeypatch.setattr(json_handler, "atomic_create_json", _spy_create)
        monkeypatch.setattr(json_handler, "_atomic_write_json", _spy_replace)

        json_handler.ensure_json_exists("observed", "log")

        assert looks, "the seam moved — this test is no longer watching the decision"
        assert used == ["create-or-fail"], (
            f"a second look changed the branch after the document was observed absent: {used}"
        )
        assert json.loads(target.read_text(encoding="utf-8")) == []

    def test_an_unreadable_document_is_still_regenerated_over(
        self,
        isolate_json_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The converse, without which the fix above is half a repair.

        Create-or-fail is right for a document that is ABSENT and wrong for one
        that is PRESENT and unusable — a corrupt file would win the link race
        against its own replacement and stay corrupt forever. Two different
        writes live in one function; this pins the other one.
        """
        target = isolate_json_dir / "corrupt_config.json"
        target.write_text("{ this is not json", encoding="utf-8")

        used: List[str] = []
        real_replace = json_handler._atomic_write_json

        def _spy_replace(path: Path, data: Any) -> None:
            used.append("replacing-write")
            return real_replace(path, data)

        monkeypatch.setattr(json_handler, "atomic_create_json", MagicMock(name="must-not-be-used"))
        monkeypatch.setattr(json_handler, "_atomic_write_json", _spy_replace)

        assert json_handler.ensure_json_exists("corrupt", "config") is True

        assert used == ["replacing-write"], f"the corrupt document was not replaced: {used}"
        assert json_handler.atomic_create_json.call_count == 0, (
            "create-or-fail was used on a document that exists — it would lose to the corruption"
        )
        assert json.loads(target.read_text(encoding="utf-8"))["module_name"] == "corrupt"
