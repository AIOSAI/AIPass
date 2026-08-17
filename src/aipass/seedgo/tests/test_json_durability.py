"""Torn-write durability for json_handler.

Axis 1 of the fleet defect: open(path, "w") truncates the target BEFORE the new
content is written, so every concurrent reader in that window sees an empty or
partial file. Measured on this handler before the fix: 842 of 1075 concurrent
reads unusable (78.3%) — 454 empty, 388 unparseable.

The race is not merely a failed read here. ensure_json_exists() answers an
unreadable document by regenerating the type's blank template over it, so a
reader landing in the truncate window destroys live data on the next call.
"""

# =================== META ====================
# Name: test_json_durability.py
# Description: Torn-write durability tests for the json handler
# Version: 1.0.0
# Created: 2026-08-16
# Modified: 2026-08-16
# =============================================

import json
import os
import re
import threading
from pathlib import Path

import pytest

from aipass.seedgo.apps.handlers.json import json_handler

HANDLER_SOURCE = Path(json_handler.__file__)

# open(..., "w"/"a"/"w+") — but NOT os.fdopen(descriptor, "w"), which is the fix
# itself. Without the lookbehind the guard convicts the helper it is protecting.
TRUNCATING_OPEN = re.compile(r"(?<!fd)open\(\s*[^)]*?,\s*[\"'][waW+]")
WRITE_TEXT = re.compile(r"\.write_text\(")


@pytest.fixture
def json_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the handler's JSON_DIR at tmp_path — never the live branch dir."""
    target = tmp_path / "seedgo_json"
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
        assert [p.name for p in tmp_path.iterdir()] == ["clean.json"]

    def test_stages_the_temp_file_in_the_target_directory(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """os.replace is only atomic within one filesystem — the temp must be a sibling.

        Staging in /tmp would make the fix silently non-atomic the moment a
        branch lives on a different mount than the system temp dir.
        """
        target = tmp_path / "sibling.json"
        seen: list[str] = []
        real_mkstemp = json_handler.tempfile.mkstemp

        def recording_mkstemp(*args, **kwargs):
            seen.append(str(kwargs.get("dir")))
            return real_mkstemp(*args, **kwargs)

        monkeypatch.setattr(json_handler.tempfile, "mkstemp", recording_mkstemp)
        json_handler._atomic_write_json(target, {"a": 1})
        assert seen == [str(tmp_path)]

    def test_failed_write_leaves_the_original_intact_and_cleans_the_temp(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """A write that dies mid-flight must not damage what is already there."""
        target = tmp_path / "survivor.json"
        target.write_text('{"live": "data"}\n', encoding="utf-8")

        def exploding_dump(*args, **kwargs):
            raise OSError("disk full")

        monkeypatch.setattr(json_handler.json, "dump", exploding_dump)

        with pytest.raises(OSError):
            json_handler._atomic_write_json(target, {"replacement": True})

        assert json.loads(target.read_text(encoding="utf-8")) == {"live": "data"}
        assert [p.name for p in tmp_path.iterdir()] == ["survivor.json"]

    def test_helper_raises_rather_than_returning_false(self, tmp_path: Path):
        """No new silent catch — a write that cannot happen must be loud."""
        missing_dir = tmp_path / "does_not_exist"
        with pytest.raises(OSError):
            json_handler._atomic_write_json(missing_dir / "x.json", {"a": 1})


class TestEveryWriteSiteIsRouted:
    """Both writers in this handler must go through the helper."""

    def test_save_json_routes_through_the_helper(self, json_dir: Path, monkeypatch: pytest.MonkeyPatch):
        calls: list[Path] = []
        monkeypatch.setattr(json_handler, "_atomic_write_json", lambda p, d: calls.append(p))
        json_handler.save_json("m", "log", [{"a": 1}])
        assert calls == [json_dir / "m_log.json"]

    def test_ensure_json_exists_routes_through_the_helper(self, json_dir: Path, monkeypatch: pytest.MonkeyPatch):
        """The regenerate path is the DATA-LOSS site, not merely another writer."""
        calls: list[Path] = []
        monkeypatch.setattr(json_handler, "_atomic_write_json", lambda p, d: calls.append(p))
        json_handler.ensure_json_exists("m", "config")
        assert calls == [json_dir / "m_config.json"]

    def test_regenerating_over_a_corrupt_document_routes_through_the_helper(
        self, json_dir: Path, monkeypatch: pytest.MonkeyPatch
    ):
        corrupt = json_dir / "m_data.json"
        corrupt.write_text("{not json", encoding="utf-8")
        calls: list[Path] = []
        monkeypatch.setattr(json_handler, "_atomic_write_json", lambda p, d: calls.append(p))
        json_handler.ensure_json_exists("m", "data")
        assert calls == [corrupt]


class TestSourceGuard:
    """No truncating write may reappear in this file."""

    def test_no_truncating_open_in_handler_source(self):
        source = HANDLER_SOURCE.read_text(encoding="utf-8")
        offenders = [
            line.strip()
            for line in source.splitlines()
            if TRUNCATING_OPEN.search(line) and not line.strip().startswith("#")
        ]
        assert offenders == []

    def test_no_write_text_in_handler_source(self):
        source = HANDLER_SOURCE.read_text(encoding="utf-8")
        offenders = [
            line.strip() for line in source.splitlines() if WRITE_TEXT.search(line) and not line.strip().startswith("#")
        ]
        assert offenders == []

    def test_guard_does_not_convict_the_fix_itself(self):
        """KNOWN TRAP: os.fdopen(fd, "w") matches a naive open( regex."""
        assert TRUNCATING_OPEN.search('with os.fdopen(descriptor, "w", encoding="utf-8") as stream:') is None

    @pytest.mark.parametrize(
        "line",
        [
            'with open(json_path, "w", encoding="utf-8") as f:',
            "with open(json_path, 'w') as f:",
            'with open(path, "a") as f:',
            'with open(path, "w+") as f:',
            'open(target, "W")',
        ],
    )
    def test_guard_still_catches_real_truncating_writes(self, line: str):
        """MUTATION CHECK: the (?<!fd) exemption must not blind the guard."""
        assert TRUNCATING_OPEN.search(line) is not None

    def test_guard_still_catches_write_text(self):
        assert WRITE_TEXT.search('json_path.write_text(json.dumps(data), encoding="utf-8")') is not None


class TestContractPreserved:
    """The mechanism changed; this handler's published contract did not."""

    def test_save_json_still_returns_true(self, json_dir: Path):
        assert json_handler.save_json("m", "log", [{"a": 1}]) is True

    def test_save_json_still_raises_on_invalid_structure(self, json_dir: Path):
        with pytest.raises(ValueError):
            json_handler.save_json("m", "config", {"missing": "keys"})

    def test_save_json_still_stamps_last_updated_on_data(self, json_dir: Path):
        json_handler.ensure_json_exists("m", "data")
        payload = json_handler.load_json("m", "data")
        assert payload is not None
        payload["last_updated"] = "1999-01-01"
        json_handler.save_json("m", "data", payload)
        reloaded = json_handler.load_json("m", "data")
        assert reloaded is not None
        assert reloaded["last_updated"] != "1999-01-01"

    def test_ensure_json_exists_still_returns_true(self, json_dir: Path):
        assert json_handler.ensure_json_exists("m", "config") is True

    def test_round_trip_still_works(self, json_dir: Path):
        json_handler.save_json("m", "log", [{"entry": "one"}])
        assert json_handler.load_json("m", "log") == [{"entry": "one"}]

    def test_log_operation_still_rotates(self, json_dir: Path):
        json_handler.ensure_module_jsons("m")
        config = json_handler.load_json("m", "config")
        assert config is not None
        config["config"]["max_log_entries"] = 3
        json_handler.save_json("m", "config", config)
        for i in range(6):
            json_handler.log_operation(f"op{i}", module_name="m")
        log = json_handler.load_json("m", "log")
        assert log is not None
        assert len(log) == 3
        assert log[-1]["operation"] == "op5"


class TestConcurrentReadersSeeAWholeDocument:
    """The measurement that motivated the fix, run as an assertion."""

    def test_two_writers_two_readers_zero_unusable(self, json_dir: Path):
        json_handler.ensure_json_exists("race", "data")
        target = json_handler.get_json_path("race", "data")

        empty = 0
        unparseable = 0
        total = 0
        lock = threading.Lock()
        stop = threading.Event()

        def write(tag: str) -> None:
            for i in range(150):
                json_handler.save_json(
                    "race",
                    "data",
                    {
                        "module_name": "race",
                        "created": "2026-08-16",
                        "last_updated": "2026-08-16",
                        "writer": tag,
                        "n": i,
                        # Padding widens the truncate->write window the way a
                        # real audit document (hundreds of violations) does.
                        "padding": ["x" * 120 for _ in range(80)],
                    },
                )

        def read() -> None:
            nonlocal empty, unparseable, total
            while not stop.is_set():
                try:
                    content = target.read_text(encoding="utf-8")
                except (FileNotFoundError, OSError):
                    continue
                with lock:
                    total += 1
                    if not content.strip():
                        empty += 1
                    else:
                        try:
                            json.loads(content)
                        except json.JSONDecodeError:
                            unparseable += 1

        readers = [threading.Thread(target=read, daemon=True) for _ in range(2)]
        writers = [threading.Thread(target=write, args=(f"w{i}",)) for i in range(2)]
        for t in readers:
            t.start()
        for t in writers:
            t.start()
        for t in writers:
            t.join()
        stop.set()
        for t in readers:
            t.join(timeout=5)

        assert total > 0, "readers never observed the document — harness proves nothing"
        assert empty == 0, f"{empty} of {total} reads saw a truncated document"
        assert unparseable == 0, f"{unparseable} of {total} reads saw a partial document"

    def test_no_staged_temp_files_survive_the_race(self, json_dir: Path):
        json_handler.ensure_json_exists("race", "data")
        for i in range(20):
            json_handler.save_json("race", "data", {"module_name": "race", "created": "x", "last_updated": "x", "n": i})
        assert sorted(p.name for p in json_dir.iterdir()) == ["race_data.json"]


class TestLiveDocumentsStillParse:
    """A fix that lands on a real branch must not orphan what is already there."""

    def test_every_live_seedgo_json_document_parses(self):
        live_dir = json_handler.JSON_DIR
        if not live_dir.exists():
            pytest.skip("no live json dir on this checkout")
        for document in live_dir.glob("*.json"):
            with open(document, "r", encoding="utf-8") as handle:
                json.load(handle)

    def test_no_orphaned_temp_files_from_this_handler_in_the_live_dir(self):
        """Scoped to THIS handler's staging prefix, and here is why.

        The helper stages as "<document-stem><random>.tmp"; incremental_cache
        writes its own atomic temps into the same directory with the stdlib
        default "tmp<random>.tmp" prefix. A blanket *.tmp assertion convicts
        that unrelated writer — and it currently does: a 4.3MB truncated
        tmp2ay2d070.tmp dated 2026-08-14 06:35 is sitting there, ending
        mid-token, from a save_cache killed between write and os.replace (its
        cleanup lives in `except Exception`, which a hard kill never runs).
        Left in place and reported rather than swept, per the never-delete
        rule. Author unknown — no session of mine records it.
        """
        live_dir = json_handler.JSON_DIR
        if not live_dir.exists():
            pytest.skip("no live json dir on this checkout")
        document_stems = {p.stem for p in live_dir.glob("*.json")}
        ours = [p.name for p in live_dir.glob("*.tmp") if any(p.name.startswith(s) for s in document_stems)]
        assert ours == []


class TestHelperUsesTheAtomicPrimitives:
    """Pin the mechanism, not just its effect — os.replace is the whole fix."""

    def test_uses_os_replace(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        target = tmp_path / "pinned.json"
        calls: list[tuple] = []
        real_replace = os.replace

        def recording_replace(src, dst):
            calls.append((src, dst))
            return real_replace(src, dst)

        monkeypatch.setattr(json_handler.os, "replace", recording_replace)
        json_handler._atomic_write_json(target, {"a": 1})
        assert len(calls) == 1
        assert calls[0][1] == str(target)
