# =================== AIPass ====================
# Name: test_json_durability.py
# Version: 1.0.0
# Description: Torn-write durability tests for the json handler
# Branch: hooks
# Layer: tests
# Created: 2026-08-16
# Modified: 2026-08-16
# =============================================

"""Torn-write durability for json_handler.

Axis 1 of the fleet defect: a write that truncates the target in place leaves a
window where every concurrent reader sees an empty file. Measured on this
handler before the fix: 587 of 1023 reads unusable (57.4%), three runs
56.7-57.5%. ensure_json_exists answers an unreadable file by writing a blank
template over it, so the race does not merely fail a read — it destroys the
document.
"""

import json
import re
import threading
from pathlib import Path

import pytest

from aipass.hooks.apps.handlers.json import json_handler

HANDLER_SOURCE = Path(json_handler.__file__)

# open(..., "w") / "a" / "w+" — but NOT os.fdopen(descriptor, "w"), which is the fix itself.
TRUNCATING_OPEN = re.compile(r"(?<!fd)open\(\s*[^)]*?,\s*[\"'][waW+]")
WRITE_TEXT = re.compile(r"\.write_text\(")


@pytest.fixture
def json_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the handler's JSON_DIR at tmp_path — never the live branch dir."""
    target = tmp_path / "hooks_json"
    target.mkdir()
    monkeypatch.setattr(json_handler, "JSON_DIR", target)
    return target


class TestAtomicHelper:
    """The mechanism itself."""

    def test_creates_document_that_did_not_exist(self, tmp_path: Path):
        target = tmp_path / "fresh.json"
        json_handler._atomic_write_json(target, {"a": 1})
        assert json.loads(target.read_text(encoding="utf-8")) == {"a": 1}

    def test_replaces_existing_document(self, tmp_path: Path):
        target = tmp_path / "existing.json"
        target.write_text('{"old": true}\n', encoding="utf-8")
        json_handler._atomic_write_json(target, {"new": True})
        assert json.loads(target.read_text(encoding="utf-8")) == {"new": True}

    def test_leaves_no_staged_file_behind(self, tmp_path: Path):
        target = tmp_path / "clean.json"
        json_handler._atomic_write_json(target, {"a": 1})
        assert list(tmp_path.glob("*.tmp")) == []
        assert [p.name for p in tmp_path.iterdir()] == ["clean.json"]

    def test_stages_temp_in_target_directory(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Same directory keeps os.replace a same-filesystem rename, so it stays atomic."""
        target = tmp_path / "nested" / "doc.json"
        target.parent.mkdir()
        seen: dict = {}
        real_mkstemp = json_handler.tempfile.mkstemp

        def spy(*args, **kwargs):
            seen["dir"] = kwargs.get("dir")
            return real_mkstemp(*args, **kwargs)

        monkeypatch.setattr(json_handler.tempfile, "mkstemp", spy)
        json_handler._atomic_write_json(target, {"a": 1})
        assert Path(seen["dir"]) == target.parent

    def test_failed_write_leaves_original_intact_and_cleans_temp(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        target = tmp_path / "precious.json"
        target.write_text('{"original": true}\n', encoding="utf-8")

        def boom(*args, **kwargs):
            raise OSError("disk full")

        monkeypatch.setattr(json_handler.os, "replace", boom)
        with pytest.raises(OSError):
            json_handler._atomic_write_json(target, {"replacement": True})

        assert json.loads(target.read_text(encoding="utf-8")) == {"original": True}
        assert list(tmp_path.glob("*.tmp")) == []

    def test_helper_raises_it_does_not_swallow(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """No new silent catch — a failed write must reach the caller."""
        monkeypatch.setattr(json_handler.os, "replace", lambda *a, **k: (_ for _ in ()).throw(OSError("nope")))
        with pytest.raises(OSError):
            json_handler._atomic_write_json(tmp_path / "x.json", {"a": 1})


class TestEveryWriteSiteRouted:
    """All three sites — the dispatch named two."""

    def test_save_json_routes_through_helper(self, json_dir: Path, monkeypatch: pytest.MonkeyPatch):
        calls: list = []
        monkeypatch.setattr(json_handler, "_atomic_write_json", lambda *a, **k: calls.append(a))
        json_handler.save_json("m", "log", [{"x": 1}])
        assert len(calls) == 1

    def test_ensure_json_exists_regenerate_routes_through_helper(self, json_dir: Path, monkeypatch: pytest.MonkeyPatch):
        """The data-loss site: it overwrites an unreadable document with a template."""
        calls: list = []
        monkeypatch.setattr(json_handler, "_atomic_write_json", lambda *a, **k: calls.append(a))
        json_handler.ensure_json_exists("m", "config")
        assert len(calls) == 1

    def test_write_json_file_routes_through_helper(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Third site — writes the trust registry and the alerts file."""
        calls: list = []
        monkeypatch.setattr(json_handler, "_atomic_write_json", lambda *a, **k: calls.append(a))
        json_handler.write_json_file(tmp_path / "registry.json", {"projects": {}})
        assert len(calls) == 1

    def test_regenerate_over_corrupt_document_is_atomic(self, json_dir: Path):
        """Corrupt in, template out, and the document parses at every point after."""
        path = json_handler.get_json_path("m", "config")
        path.write_text("{ not json", encoding="utf-8")
        json_handler.ensure_json_exists("m", "config")
        assert json.loads(path.read_text(encoding="utf-8"))["module_name"] == "m"
        assert list(json_dir.glob("*.tmp")) == []


class TestSourceGuard:
    """No truncating write may reappear in this file."""

    def test_no_truncating_open_survives(self):
        source = HANDLER_SOURCE.read_text(encoding="utf-8")
        assert TRUNCATING_OPEN.search(source) is None

    def test_no_write_text_survives(self):
        source = HANDLER_SOURCE.read_text(encoding="utf-8")
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
    """The reference is the mechanism, not the contract. This branch RAISES."""

    def test_save_json_returns_true(self, json_dir: Path):
        assert json_handler.save_json("m", "log", [{"x": 1}]) is True

    def test_save_json_raises_on_invalid_structure(self, json_dir: Path):
        """Mine raises where @api returns False — preserved deliberately."""
        with pytest.raises(ValueError):
            json_handler.save_json("m", "config", {"missing": "keys"})

    def test_ensure_json_exists_returns_true(self, json_dir: Path):
        assert json_handler.ensure_json_exists("m", "data") is True

    def test_write_json_file_returns_none(self, tmp_path: Path):
        assert json_handler.write_json_file(tmp_path / "a.json", {"a": 1}) is None

    def test_round_trip_through_public_api(self, json_dir: Path):
        json_handler.save_json("m", "log", [{"entry": 1}])
        assert json_handler.load_json("m", "log") == [{"entry": 1}]

    def test_documents_keep_trailing_newline(self, json_dir: Path):
        json_handler.save_json("m", "log", [{"x": 1}])
        assert json_handler.get_json_path("m", "log").read_text(encoding="utf-8").endswith("\n")

    def test_write_json_file_round_trips_non_ascii(self, tmp_path: Path):
        target = tmp_path / "unicode.json"
        json_handler.write_json_file(target, {"name": "Ståle"})
        assert json_handler.read_json_file(target) == {"name": "Ståle"}


class TestConcurrentReadsStayUsable:
    """The measurement, as a test. 57.4% unusable before; zero tolerated now."""

    def test_two_writers_two_readers_zero_unusable(self, json_dir: Path):
        module = "racer"
        json_handler.ensure_json_exists(module, "data")
        target = json_handler.get_json_path(module, "data")

        stop = threading.Event()
        failures: list = []
        reads = [0]
        lock = threading.Lock()

        def writer(tag: int) -> None:
            for i in range(150):
                json_handler.save_json(
                    module,
                    "data",
                    {
                        "module_name": module,
                        "created": "2026-08-16",
                        "last_updated": "2026-08-16",
                        "writer": tag,
                        "round": i,
                        "filler": "x" * 4000,
                    },
                )

        def reader() -> None:
            local_reads = 0
            local_failures = []
            while not stop.is_set():
                try:
                    raw = target.read_text(encoding="utf-8")
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

        assert reads[0] > 0, "readers never ran — the test would pass vacuously"
        assert failures == [], f"{len(failures)} unusable reads of {reads[0]}"

    def test_race_leaves_no_staged_files(self, json_dir: Path):
        assert list(json_dir.glob("*.tmp")) == []
