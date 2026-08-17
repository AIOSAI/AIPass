"""Durability tests for json_handler writes — a reader must never see a torn file.

THE DEFECT (fleet-wide, error 90c9e40d): every write site opened the target with
"w", which TRUNCATES before the new content lands. A concurrent reader in that
window gets an empty file, and this handler answers an unreadable file by
regenerating a fresh template over it — so the race does not merely fail a read,
it destroys the live document.

These tests are written against the OBSERVABLE contract: at every instant, the
file on disk parses as JSON and holds either the old document or the new one.
"""

import json
import threading

import pytest

from aipass.cli.apps.handlers.json import json_handler


@pytest.fixture
def json_dir(tmp_path, monkeypatch):
    """Point the handler at a temp directory — never touch the real cli_json/."""
    target = tmp_path / "cli_json"
    target.mkdir()
    monkeypatch.setattr(json_handler, "JSON_DIR", target)
    return target


class TestAtomicWriteHelper:
    """_atomic_write_json is the single write primitive every site must use."""

    def test_replaces_content(self, json_dir):
        path = json_dir / "thing.json"
        json_handler._atomic_write_json(path, {"v": 1})
        json_handler._atomic_write_json(path, {"v": 2})
        assert json.loads(path.read_text(encoding="utf-8")) == {"v": 2}

    def test_creates_missing_file(self, json_dir):
        path = json_dir / "fresh.json"
        json_handler._atomic_write_json(path, [1, 2, 3])
        assert json.loads(path.read_text(encoding="utf-8")) == [1, 2, 3]

    def test_leaves_no_temp_files_behind(self, json_dir):
        path = json_dir / "clean.json"
        json_handler._atomic_write_json(path, {"v": 1})
        assert list(json_dir.glob("*.tmp")) == []

    def test_failed_write_leaves_original_intact(self, json_dir, monkeypatch):
        """A write that blows up must not truncate the live document."""
        path = json_dir / "keep.json"
        json_handler._atomic_write_json(path, {"v": "original"})

        def exploding_dump(*args, **kwargs):
            raise RuntimeError("serialisation failed")

        monkeypatch.setattr(json_handler.json, "dump", exploding_dump)
        with pytest.raises(RuntimeError):
            json_handler._atomic_write_json(path, {"v": "replacement"})

        assert json.loads(path.read_text(encoding="utf-8")) == {"v": "original"}

    def test_failed_write_cleans_up_temp_file(self, json_dir, monkeypatch):
        """No partial document may survive in the directory the handler globs."""
        path = json_dir / "keep.json"
        json_handler._atomic_write_json(path, {"v": "original"})

        def exploding_dump(*args, **kwargs):
            raise RuntimeError("serialisation failed")

        monkeypatch.setattr(json_handler.json, "dump", exploding_dump)
        with pytest.raises(RuntimeError):
            json_handler._atomic_write_json(path, {"v": "replacement"})

        assert list(json_dir.glob("*.tmp")) == []

    def test_temp_file_staged_in_target_directory(self, json_dir, monkeypatch):
        """Staging elsewhere would make os.replace a cross-device copy, not atomic."""
        seen = {}
        real_mkstemp = json_handler.tempfile.mkstemp

        def recording_mkstemp(*args, **kwargs):
            seen["dir"] = kwargs.get("dir")
            return real_mkstemp(*args, **kwargs)

        monkeypatch.setattr(json_handler.tempfile, "mkstemp", recording_mkstemp)
        json_handler._atomic_write_json(json_dir / "staged.json", {"v": 1})
        assert seen["dir"] == str(json_dir)


class TestWriteSitesAreAtomic:
    """Every write site must route through the helper — including regenerate."""

    def test_save_json_uses_atomic_write(self, json_dir, monkeypatch):
        calls = []
        monkeypatch.setattr(
            json_handler,
            "_atomic_write_json",
            lambda path, data: calls.append(path),
        )
        json_handler.save_json("mod", "log", [{"entry": 1}])
        assert calls == [json_dir / "mod_log.json"]

    def test_regenerate_path_uses_atomic_write(self, json_dir, monkeypatch):
        """ensure_json_exists overwrites LIVE data when it judges a file corrupt."""
        corrupt = json_dir / "mod_config.json"
        corrupt.write_text("{ not json", encoding="utf-8")

        calls = []
        monkeypatch.setattr(
            json_handler,
            "_atomic_write_json",
            lambda path, data: calls.append(path),
        )
        json_handler.ensure_json_exists("mod", "config")
        assert calls == [corrupt]

    def test_no_write_site_truncates_with_mode_w(self, json_dir):
        """Guard: a future edit reintroducing open(..., 'w') re-opens the race."""
        source = json_handler.__file__
        with open(source, "r", encoding="utf-8") as handle:
            body = handle.read()
        offenders = [
            line.strip() for line in body.splitlines() if "open(" in line and '"w"' in line and "fdopen" not in line
        ]
        assert offenders == []


class TestConcurrentReadsStayParseable:
    """The defect as the fleet measured it: readers racing a writer."""

    def test_readers_never_observe_a_torn_document(self, json_dir):
        path = json_dir / "race_log.json"
        json_handler._atomic_write_json(path, [{"entry": 0}])

        stop = threading.Event()
        unparseable = []
        empty = []

        def writer(worker):
            for round_number in range(60):
                if stop.is_set():
                    return
                json_handler.save_json("race", "log", [{"entry": round_number, "worker": worker}] * 40)

        def reader():
            while not stop.is_set():
                try:
                    raw = path.read_text(encoding="utf-8")
                except FileNotFoundError:
                    continue
                if raw == "":
                    empty.append(1)
                    continue
                try:
                    json.loads(raw)
                except json.JSONDecodeError:
                    unparseable.append(raw[:40])

        # save_json writes race_log.json — point the readers at that same file.
        threads = [threading.Thread(target=writer, args=(n,)) for n in range(2)]
        threads += [threading.Thread(target=reader) for _ in range(2)]
        for thread in threads[2:]:
            thread.start()
        for thread in threads[:2]:
            thread.start()
        for thread in threads[:2]:
            thread.join()
        stop.set()
        for thread in threads[2:]:
            thread.join()

        assert unparseable == [], f"{len(unparseable)} torn reads: {unparseable[:3]}"
        assert empty == [], f"{len(empty)} reads saw a truncated (empty) file"
