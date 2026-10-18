# =================== AIPass ====================
# Name: test_json_durability.py
# Version: 2.0.3
# Description: Torn-write durability tests for hooks' arbitrary-path json module
# Branch: hooks
# Layer: tests
# Created: 2026-08-16
# Modified: 2026-10-17
# =============================================

"""Tests for apps/handlers/json/files.py's torn-write durability."""

# A truncate-in-place write lets concurrent readers see an empty file; these files hold the
# trust registry, where a torn read darks every hook in the project.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(json_handler) — the nine standard json names, pinned by seedgo's cross-branch contract
# seedgo: no-test-needed(stdlib) — os.replace's atomicity and json.dumps' encoding
# seedgo: no-test-needed(documentation) — that read_json_file / write_json_file carry docstrings

import json
import os
import re
import threading
from pathlib import Path

import pytest

from aipass.hooks.apps.handlers.json import files as json_files

MODULE_SOURCE = Path(json_files.__file__)

# open(..., "w") / "a" / "w+" — but NOT os.fdopen(descriptor, "w"), which is the fix itself.
TRUNCATING_OPEN = re.compile(r"(?<!fd)open\(\s*[^)]*?,\s*[\"'][waW+]")
WRITE_TEXT = re.compile(r"\.write_text\(")


class TestAtomicHelper:
    """The mechanism, reached through write_json_file, its one public door."""

    def test_creates_document_that_did_not_exist(self, tmp_path: Path):
        target = tmp_path / "fresh.json"
        json_files.write_json_file(target, {"a": 1})
        assert json.loads(target.read_text(encoding="utf-8")) == {"a": 1}

    def test_replaces_existing_document(self, tmp_path: Path):
        target = tmp_path / "existing.json"
        target.write_text('{"old": true}\n', encoding="utf-8")
        json_files.write_json_file(target, {"new": True})
        assert json.loads(target.read_text(encoding="utf-8")) == {"new": True}

    def test_leaves_no_staged_file_behind(self, tmp_path: Path):
        # Own directory: mock_infrastructure builds the json sandbox under tmp_path.
        directory = tmp_path / "documents"
        directory.mkdir()
        target = directory / "clean.json"
        json_files.write_json_file(target, {"a": 1})
        assert list(directory.glob("*.tmp")) == []
        assert [p.name for p in directory.iterdir()] == ["clean.json"]

    def test_stages_temp_in_target_directory(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Same directory keeps os.replace a same-filesystem rename, so it stays atomic."""
        target = tmp_path / "nested" / "doc.json"
        target.parent.mkdir()
        seen: dict = {}

        def at_the_move(source, destination):
            seen["staged"] = Path(source)
            seen["on_disk"] = Path(source).is_file()
            seen["destination"] = Path(destination)
            os.replace(source, destination)

        # The product's own mover, not tempfile.mkstemp (stdlib_patch).
        monkeypatch.setattr(json_files, "_replace_with_retry", at_the_move)
        json_files.write_json_file(target, {"a": 1})
        assert seen["on_disk"] is True
        assert seen["staged"].parent == target.parent
        assert seen["destination"] == target
        assert json.loads(target.read_text(encoding="utf-8")) == {"a": 1}

    def test_failed_write_leaves_original_intact_and_cleans_temp(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        target = tmp_path / "precious.json"
        target.write_text('{"original": true}\n', encoding="utf-8")

        def boom(*args, **kwargs):
            raise OSError("disk full")

        monkeypatch.setattr(json_files, "_replace_with_retry", boom)
        with pytest.raises(OSError):
            json_files.write_json_file(target, {"replacement": True})

        assert json.loads(target.read_text(encoding="utf-8")) == {"original": True}
        assert list(tmp_path.glob("*.tmp")) == []

    def test_helper_raises_it_does_not_swallow(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """No new silent catch — a failed write must reach the caller."""
        monkeypatch.setattr(json_files, "_replace_with_retry", lambda *a, **k: (_ for _ in ()).throw(OSError("nope")))
        with pytest.raises(OSError, match="nope"):
            json_files.write_json_file(tmp_path / "x.json", {"a": 1})


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
        caught = TRUNCATING_OPEN.search(mutation)
        # The guard must land on the truncating open call itself, not merely somewhere.
        assert caught is not None and caught.start() == mutation.index("open(")

    def test_guard_catches_write_text_mutation(self):
        mutation = 'json_path.write_text(json.dumps(data), encoding="utf-8")'
        caught = WRITE_TEXT.search(mutation)
        assert caught is not None and caught.start() == mutation.index(".write_text(")


class TestContractPreserved:
    """These two RAISE where the fleet service answers None / False.

    An unreadable trust registry must never be mistaken for an empty one.
    """

    def test_write_json_file_returns_none(self, tmp_path: Path):
        target = tmp_path / "a.json"
        assert json_files.write_json_file(target, {"a": 1}) is None
        assert json.loads(target.read_text(encoding="utf-8")) == {"a": 1}

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
    """Concurrent readers never see an unusable document; zero tolerated."""

    def test_two_writers_two_readers_zero_unusable(self, tmp_path: Path):
        target = tmp_path / "trusted_projects.json"
        json_files.write_json_file(target, {"version": 1, "projects": {}})

        stop = threading.Event()
        failures: list = []
        write_failures: list = []
        reads = [0]
        lock = threading.Lock()

        def writer(tag: int) -> None:
            # A writer that dies silently would leave the content assertions passing vacuously.
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
            except Exception as error:  # surfaced through write_failures below
                with lock:
                    write_failures.append(error)

        def reader() -> None:
            local_reads = 0
            local_failures = []
            while not stop.is_set():
                # Yield: on Windows a spinning reader's handle makes os.replace fail (WinError 5)
                # and can starve the writer's bounded retry; Event wait ends with the writers.
                stop.wait(0.001)
                try:
                    raw = target.read_text(encoding="utf-8")
                except PermissionError:
                    # Windows share-mode refusal mid-replace: not an unusable document, not a read.
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
