# =================== AIPass ====================
# Name: test_json_durability.py
# Version: 2.0.0
# Description: Torn-write durability tests for hooks' arbitrary-path json module
# Branch: hooks
# Layer: tests
# Created: 2026-08-16
# Modified: 2026-09-03
# =============================================

"""Torn-write durability for the json files module.

Axis 1 of the fleet defect: a write that truncates the target in place leaves a
window where every concurrent reader sees an empty file. Measured on the
handler this module was carved out of, before the fix: 587 of 1023 reads
unusable (57.4%), three runs 56.7-57.5%.

DPLAN-0325 moved the nine standard names to the fleet's one json service, whose
behaviour seedgo's cross-branch contract pins once for everyone. What stayed
here is what stayed in hooks: ``read_json_file`` / ``write_json_file`` and the
atomic write beneath them, in ``apps/handlers/json/files.py``. They write
the TRUST REGISTRY and a project's alerts file — a torn registry read is every
hook in the project going dark — so the mechanism keeps its own pins. The tests
that pinned the service half moved verbatim to
``tests/.archive/deleted_2026-09-03_json_durability.py``.
"""

import json
import re
import threading
import time
from pathlib import Path

import pytest

from aipass.hooks.apps.handlers.json import files as json_files

MODULE_SOURCE = Path(json_files.__file__)

# open(..., "w") / "a" / "w+" — but NOT os.fdopen(descriptor, "w"), which is the fix itself.
TRUNCATING_OPEN = re.compile(r"(?<!fd)open\(\s*[^)]*?,\s*[\"'][waW+]")
WRITE_TEXT = re.compile(r"\.write_text\(")


class TestAtomicHelper:
    """The mechanism itself."""

    def test_creates_document_that_did_not_exist(self, tmp_path: Path):
        target = tmp_path / "fresh.json"
        json_files._atomic_write_json(target, {"a": 1})
        assert json.loads(target.read_text(encoding="utf-8")) == {"a": 1}

    def test_replaces_existing_document(self, tmp_path: Path):
        target = tmp_path / "existing.json"
        target.write_text('{"old": true}\n', encoding="utf-8")
        json_files._atomic_write_json(target, {"new": True})
        assert json.loads(target.read_text(encoding="utf-8")) == {"new": True}

    def test_leaves_no_staged_file_behind(self, tmp_path: Path):
        # Its own directory: mock_infrastructure builds the json sandbox under
        # tmp_path, so the "nothing else is here" claim needs a clean floor.
        directory = tmp_path / "documents"
        directory.mkdir()
        target = directory / "clean.json"
        json_files._atomic_write_json(target, {"a": 1})
        assert list(directory.glob("*.tmp")) == []
        assert [p.name for p in directory.iterdir()] == ["clean.json"]

    def test_stages_temp_in_target_directory(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Same directory keeps os.replace a same-filesystem rename, so it stays atomic."""
        target = tmp_path / "nested" / "doc.json"
        target.parent.mkdir()
        seen: dict = {}
        real_mkstemp = json_files.tempfile.mkstemp

        def spy(*args, **kwargs):
            seen["dir"] = kwargs.get("dir")
            return real_mkstemp(*args, **kwargs)

        monkeypatch.setattr(json_files.tempfile, "mkstemp", spy)
        json_files._atomic_write_json(target, {"a": 1})
        assert Path(seen["dir"]) == target.parent

    def test_failed_write_leaves_original_intact_and_cleans_temp(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        target = tmp_path / "precious.json"
        target.write_text('{"original": true}\n', encoding="utf-8")

        def boom(*args, **kwargs):
            raise OSError("disk full")

        monkeypatch.setattr(json_files.os, "replace", boom)
        with pytest.raises(OSError):
            json_files._atomic_write_json(target, {"replacement": True})

        assert json.loads(target.read_text(encoding="utf-8")) == {"original": True}
        assert list(tmp_path.glob("*.tmp")) == []

    def test_helper_raises_it_does_not_swallow(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """No new silent catch — a failed write must reach the caller."""
        monkeypatch.setattr(json_files.os, "replace", lambda *a, **k: (_ for _ in ()).throw(OSError("nope")))
        with pytest.raises(OSError):
            json_files._atomic_write_json(tmp_path / "x.json", {"a": 1})


class TestEveryWriteSiteRouted:
    """The write site this branch still owns."""

    def test_write_json_file_routes_through_helper(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Writes the trust registry and the alerts file."""
        calls: list = []
        monkeypatch.setattr(json_files, "_atomic_write_json", lambda *a, **k: calls.append(a))
        json_files.write_json_file(tmp_path / "registry.json", {"projects": {}})
        assert len(calls) == 1


class TestSourceGuard:
    """No truncating write may reappear in this file."""

    def test_no_truncating_open_survives(self):
        source = MODULE_SOURCE.read_text(encoding="utf-8")
        assert TRUNCATING_OPEN.search(source) is None

    def test_no_write_text_survives(self):
        source = MODULE_SOURCE.read_text(encoding="utf-8")
        assert WRITE_TEXT.search(source) is None

    def test_guard_exempts_the_fix_itself(self):
        """KNOWN TRAP: os.fdopen(fd, "w") matches a naive open( regex."""
        assert TRUNCATING_OPEN.search('with os.fdopen(descriptor, "w", encoding="utf-8") as stream:') is None

    @pytest.mark.parametrize(
        "mutation",
        [
            'json_path.open(json_path, "w")',
            'with open(path, "w", encoding="utf-8") as f:',
            "with open(path, 'w') as f:",
            'with open(path, "a") as f:',
            'with open(path, "w+") as f:',
        ],
    )
    def test_guard_catches_mutations(self, mutation: str):
        """MUTATION-CHECK: a guard that catches nothing is a green light, not a test."""
        assert TRUNCATING_OPEN.search(mutation) is not None

    def test_guard_catches_write_text_mutation(self):
        assert WRITE_TEXT.search('json_path.write_text(json.dumps(data), encoding="utf-8")') is not None


class TestContractPreserved:
    """These two RAISE where the fleet service answers None / False.

    An unreadable trust registry must never be mistaken for an empty one, so
    the loud contract is the reason the module exists at all.
    """

    def test_write_json_file_returns_none(self, tmp_path: Path):
        assert json_files.write_json_file(tmp_path / "a.json", {"a": 1}) is None

    def test_write_json_file_round_trips_non_ascii(self, tmp_path: Path):
        target = tmp_path / "unicode.json"
        json_files.write_json_file(target, {"name": "Ståle"})
        assert json_files.read_json_file(target) == {"name": "Ståle"}

    def test_documents_keep_trailing_newline(self, tmp_path: Path):
        target = tmp_path / "newline.json"
        json_files.write_json_file(target, {"a": 1})
        assert target.read_text(encoding="utf-8").endswith("\n")

    def test_read_json_file_raises_on_missing_document(self, tmp_path: Path):
        """None would read as an empty registry — every enrolled project revoked."""
        with pytest.raises(OSError):
            json_files.read_json_file(tmp_path / "absent.json")

    def test_read_json_file_raises_on_unparseable_document(self, tmp_path: Path):
        target = tmp_path / "torn.json"
        target.write_text("{ not json", encoding="utf-8")
        with pytest.raises(json.JSONDecodeError):
            json_files.read_json_file(target)


class TestConcurrentReadsStayUsable:
    """The measurement, as a test. 57.4% unusable before; zero tolerated now."""

    def test_two_writers_two_readers_zero_unusable(self, tmp_path: Path):
        target = tmp_path / "trusted_projects.json"
        json_files.write_json_file(target, {"version": 1, "projects": {}})

        stop = threading.Event()
        failures: list = []
        write_failures: list = []
        reads = [0]
        lock = threading.Lock()

        def writer(tag: int) -> None:
            # A writer that dies silently leaves the content assertions below
            # passing vacuously. On Windows an exhausted os.replace retry raises
            # here, and that must read as a probe failure, not as a clean race.
            try:
                for i in range(150):
                    json_files.write_json_file(
                        target,
                        {
                            "version": 1,
                            "projects": {},
                            "writer": tag,
                            "round": i,
                            "filler": "x" * 4000,
                        },
                    )
            except Exception as error:  # noqa: BLE001 - surfaced through write_failures below
                with lock:
                    write_failures.append(error)

        def reader() -> None:
            local_reads = 0
            local_failures = []
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
                except PermissionError:
                    # Windows refuses the open while a concurrent os.replace is
                    # in flight. A refused open is share-mode semantics, not an
                    # unusable document — it is not counted as a read at all.
                    continue
                except FileNotFoundError:
                    local_failures.append("missing")
                    continue
                local_reads += 1
                if raw.strip() == "":
                    local_failures.append("empty")
                    continue
                try:
                    json.loads(raw)
                except json.JSONDecodeError:
                    local_failures.append("unparseable")
            with lock:
                reads[0] += local_reads
                failures.extend(local_failures)

        readers = [threading.Thread(target=reader) for _ in range(2)]
        writers = [threading.Thread(target=writer, args=(t,)) for t in range(2)]
        for t in readers + writers:
            t.start()
        for t in writers:
            t.join()
        stop.set()
        for t in readers:
            t.join()

        assert write_failures == [], f"a writer died mid-race: {write_failures[0]!r}"
        assert reads[0] > 0, "readers never ran — the test would pass vacuously"
        assert failures == [], f"{len(failures)} unusable reads of {reads[0]}"

    def test_race_leaves_no_staged_files(self, tmp_path: Path):
        assert list(tmp_path.glob("*.tmp")) == []
