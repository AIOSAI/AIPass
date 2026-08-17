# ===================AIPASS====================
# META DATA HEADER
# Name: test_json_durability.py - JSON Write Durability Tests
# Date: 2026-08-16
# Version: 1.0.0
# Category: skills/tests
#
# CHANGELOG (Max 5 entries):
#   - v1.0.0 (2026-08-16): Initial creation - torn-write (axis 1) durability guards
#
# CODE STANDARDS:
#   - Pytest conventions
#   - Temp dir isolation via tmp_path - NEVER the live skills_json/ directory
# =============================================

"""Durability tests for the JSON handler's write path.

Fleet defect 90c9e40d, axis 1: opening a document with "w" truncates it BEFORE
the new bytes land, so any concurrent reader sees an empty or partial file. In
this handler that is worse than a bad read - ensure_json_exists answers an
unreadable document by writing a fresh template over it, converting a torn read
into permanent data loss.

Measured on @skills' own unfixed handler (2 writers + 2 readers, three runs):
86.9% / 90.2% / 91.4% of concurrent reads came back empty or unparseable.
"""

import json
import os
import re
import tempfile
import threading
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch

import pytest

from aipass.skills.apps.handlers.json import json_handler as jh


# =============================================
# HELPERS
# =============================================


@pytest.fixture
def json_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the handler at a throwaway directory, never the live skills_json/."""
    target = tmp_path / "skills_json"
    target.mkdir()
    monkeypatch.setattr(jh, "SKILLS_JSON_DIR", target)
    return target


def _temp_files(directory: Path) -> List[Path]:
    """Return staged temp files left behind in a directory."""
    return [p for p in directory.iterdir() if p.suffix == ".tmp" or ".tmp" in p.name]


def _valid_data_doc() -> Dict[str, Any]:
    """Return a document that passes the 'data' structure validation."""
    return {
        "module_name": "probe",
        "created": "2026-08-16",
        "last_updated": "2026-08-16",
        "operations_total": 7,
    }


def _atomic_write(target: Path, data: Any) -> None:
    """Call the handler's atomic write helper, resolved at call time.

    Resolved dynamically so this suite could be written red-first: before the
    fix landed the helper did not exist and every test naming it failed with
    that sentence, rather than the whole file failing to import.
    """
    writer = getattr(jh, "_atomic_write_json", None)
    assert writer is not None, "json_handler._atomic_write_json does not exist"
    writer(target, data)


# Patch targets as strings - the handler gains these attributes with the fix.
_HELPER_TARGET = f"{jh.__name__}._atomic_write_json"
_MKSTEMP_TARGET = f"{jh.__name__}.tempfile.mkstemp"
_REPLACE_TARGET = f"{jh.__name__}.os.replace"

# Matches open(..., "w"/"a"/"x"/"w+") while tolerating os.fdopen(fd, "w") - the
# staged-descriptor write inside the atomic helper itself.
#
# The alternation allows ONE level of nested parentheses so the argument list of
# open(get_json_path(...), "w") is still scanned. The fleet's original guard used
# [^)]*? here, which stops dead at the inner call's closing paren and reports a
# handler clean while a truncating write sits in it - proved by planting exactly
# that line and watching the guard stay green (2026-08-16). Laziness plus the
# balanced alternation keeps the scan bounded to a single call.
_TRUNCATING_OPEN = re.compile(r"(?<!fd)open\((?:[^()]|\([^()]*\))*?['\"][wax]\+?['\"]")


def _scan_for_truncating_open(source: str) -> List[str]:
    """Find truncating open() calls, including ones split across lines.

    Whitespace is collapsed first so a call formatted over several lines reads
    the same to the guard as a one-liner.
    """
    return _TRUNCATING_OPEN.findall(re.sub(r"\s+", " ", source))


# =============================================
# ATOMIC WRITE HELPER
# =============================================


class TestAtomicWriteHelper:
    """Tests for _atomic_write_json()."""

    def test_creates_file_when_absent(self, tmp_path: Path) -> None:
        """Writing to a path that does not exist creates it with the data."""
        target = tmp_path / "fresh.json"

        _atomic_write(target, {"hello": "world"})

        assert json.loads(target.read_text(encoding="utf-8")) == {"hello": "world"}

    def test_replaces_existing_content(self, tmp_path: Path) -> None:
        """Writing over an existing document swaps its content in place."""
        target = tmp_path / "existing.json"
        target.write_text(json.dumps({"old": True}), encoding="utf-8")

        _atomic_write(target, {"new": True})

        assert json.loads(target.read_text(encoding="utf-8")) == {"new": True}

    def test_leaves_no_temp_file_behind(self, tmp_path: Path) -> None:
        """A successful write cleans up after itself."""
        target = tmp_path / "clean.json"

        _atomic_write(target, {"a": 1})

        assert _temp_files(tmp_path) == []
        assert [p.name for p in tmp_path.iterdir()] == ["clean.json"]

    def test_stages_temp_in_target_directory(self, tmp_path: Path) -> None:
        """The temp file is staged in the TARGET directory.

        os.replace is only atomic within one filesystem. Staging in the system
        temp dir would make the rename a cross-device copy - the exact window
        this fix exists to close.
        """
        target = tmp_path / "staged.json"
        seen: Dict[str, Any] = {}
        real_mkstemp = tempfile.mkstemp

        def _spy(*args: Any, **kwargs: Any) -> Any:
            seen["dir"] = kwargs.get("dir")
            return real_mkstemp(*args, **kwargs)

        with patch(_MKSTEMP_TARGET, side_effect=_spy):
            _atomic_write(target, {"a": 1})

        assert seen["dir"] == str(tmp_path)

    def test_failed_write_leaves_original_intact(self, tmp_path: Path) -> None:
        """A write that blows up mid-serialisation must not damage the original."""
        target = tmp_path / "precious.json"
        original = json.dumps({"precious": "data"})
        target.write_text(original, encoding="utf-8")

        with patch.object(jh.json, "dump", side_effect=OSError("disk full")):
            with pytest.raises(OSError):
                _atomic_write(target, {"replacement": "data"})

        assert target.read_text(encoding="utf-8") == original

    def test_failed_write_cleans_its_temp_file(self, tmp_path: Path) -> None:
        """A failed write does not litter the directory the handler reads from."""
        target = tmp_path / "precious.json"
        target.write_text(json.dumps({"precious": "data"}), encoding="utf-8")

        with patch.object(jh.json, "dump", side_effect=OSError("disk full")):
            with pytest.raises(OSError):
                _atomic_write(target, {"replacement": "data"})

        assert _temp_files(tmp_path) == []
        assert [p.name for p in tmp_path.iterdir()] == ["precious.json"]

    def test_raises_rather_than_silently_failing(self, tmp_path: Path) -> None:
        """The helper raises on failure - no silent catch, callers decide."""
        target = tmp_path / "raises.json"

        with patch(_REPLACE_TARGET, side_effect=OSError("nope")):
            with pytest.raises(OSError):
                _atomic_write(target, {"a": 1})


# =============================================
# WRITE SITE ROUTING
# =============================================


class TestEveryWriteSiteIsRouted:
    """Every path that writes a document must go through the atomic helper."""

    def test_save_json_routes_through_helper(self, json_dir: Path) -> None:
        """save_json writes via _atomic_write_json."""
        with patch(_HELPER_TARGET) as spy:
            jh.save_json("routed", "data", _valid_data_doc())

        assert spy.call_count == 1
        assert spy.call_args[0][0] == json_dir / "routed_data.json"

    def test_ensure_json_exists_routes_through_helper(self, json_dir: Path) -> None:
        """The create-from-template path writes via _atomic_write_json."""
        with patch(_HELPER_TARGET) as spy:
            jh.ensure_json_exists("fresh", "config")

        assert spy.call_count == 1
        assert spy.call_args[0][0] == json_dir / "fresh_config.json"

    def test_regenerate_path_routes_through_helper(self, json_dir: Path) -> None:
        """The regenerate-over-live-data path writes via _atomic_write_json.

        This is the site that turns a torn read into permanent loss: a document
        that reads as corrupt gets a template written over it.
        """
        corrupt = json_dir / "corrupt_data.json"
        corrupt.write_text("{not json", encoding="utf-8")

        with patch(_HELPER_TARGET) as spy:
            jh.ensure_json_exists("corrupt", "data")

        assert spy.call_count == 1
        assert spy.call_args[0][0] == corrupt

    def test_regenerate_of_a_valid_document_writes_nothing(self, json_dir: Path) -> None:
        """A readable, valid document is left alone - no needless rewrite."""
        jh.ensure_json_exists("intact", "data")

        with patch(_HELPER_TARGET) as spy:
            jh.ensure_json_exists("intact", "data")

        spy.assert_not_called()

    def test_no_truncating_open_survives_in_source(self) -> None:
        """No open(..., 'w'/'a') remains in the handler source.

        os.fdopen(descriptor, "w") is the fix itself and is exempted by the
        (?<!fd) lookbehind - see test_source_guard_catches_offenders for the
        mutation check proving the guard still bites.
        """
        source = Path(jh.__file__).read_text(encoding="utf-8")

        offenders = _scan_for_truncating_open(source)

        assert offenders == [], f"truncating open() still in handler: {offenders}"

    def test_source_guard_catches_offenders(self) -> None:
        """Mutation check: the guard's regex still catches what it is for.

        A guard that cannot fail is not a guard. These are the exact forms the
        fix removed, plus the ones it must tolerate.
        """
        assert _scan_for_truncating_open('with open(json_path, "w", encoding="utf-8") as f:')
        assert _scan_for_truncating_open("with open(path, 'w') as f:")
        assert _scan_for_truncating_open('open(target, "a", encoding="utf-8")')
        assert _scan_for_truncating_open('open(target, "w+")')
        assert _scan_for_truncating_open('open(target, "x")')
        # Nested call before the mode - the form that slipped past the fleet's
        # original [^)]*? guard while a real truncating write sat in the file.
        assert _scan_for_truncating_open('with open(get_json_path(name, "log"), "w", encoding="utf-8") as f:')
        # Split across lines, as a formatter would leave a long call
        assert _scan_for_truncating_open('with open(\n    json_path,\n    "w",\n) as f:')
        # The fix itself must NOT trip the guard
        assert not _scan_for_truncating_open('with os.fdopen(descriptor, "w", encoding="utf-8") as stream:')
        # Reads are none of the guard's business
        assert not _scan_for_truncating_open('with open(json_path, "r", encoding="utf-8") as f:')
        assert not _scan_for_truncating_open('with open(get_json_path(name, "log"), "r", encoding="utf-8") as f:')


# =============================================
# CONCURRENCY PROBE
# =============================================


class TestConcurrentReadersSeeWholeDocuments:
    """The measurement that started this: 2 writers + 2 readers, live race."""

    def test_no_torn_reads_under_concurrent_writes(self, json_dir: Path) -> None:
        """Every concurrent read returns a whole, parseable document.

        Unfixed, this same probe scored 86.9% / 90.2% / 91.4% unusable reads on
        @skills' handler across three runs.
        """
        module = "raced"
        jh.ensure_json_exists(module, "data")
        target = jh.get_json_path(module, "data")

        iterations = 80
        stop = threading.Event()
        counts = {"reads": 0, "empty": 0, "unparseable": 0}
        lock = threading.Lock()

        def _writer(seed: int) -> None:
            payload = _valid_data_doc()
            payload["filler"] = [f"entry-{seed}-{i}" * 20 for i in range(200)]
            for _ in range(iterations):
                jh.save_json(module, "data", dict(payload))

        def _reader() -> None:
            while not stop.is_set():
                try:
                    raw = target.read_text(encoding="utf-8")
                except OSError:
                    continue
                with lock:
                    counts["reads"] += 1
                    if raw.strip() == "":
                        counts["empty"] += 1
                        continue
                    try:
                        json.loads(raw)
                    except json.JSONDecodeError:
                        counts["unparseable"] += 1

        readers = [threading.Thread(target=_reader, daemon=True) for _ in range(2)]
        for reader in readers:
            reader.start()

        writers = [threading.Thread(target=_writer, args=(index,)) for index in range(2)]
        for writer in writers:
            writer.start()
        for writer in writers:
            writer.join()

        stop.set()
        for reader in readers:
            reader.join(timeout=5)

        assert counts["reads"] > 0, "probe never read the document - test is not proving anything"
        assert counts["empty"] == 0, f"{counts['empty']} of {counts['reads']} reads saw an empty file"
        assert counts["unparseable"] == 0, f"{counts['unparseable']} of {counts['reads']} reads were unparseable"

    def test_document_survives_the_race_intact(self, json_dir: Path) -> None:
        """After concurrent writing the document is still valid and complete."""
        module = "survivor"
        jh.ensure_json_exists(module, "data")

        def _writer(seed: int) -> None:
            for index in range(40):
                document = _valid_data_doc()
                document["writer"] = seed
                document["index"] = index
                jh.save_json(module, "data", document)

        threads = [threading.Thread(target=_writer, args=(index,)) for index in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        final = json.loads(jh.get_json_path(module, "data").read_text(encoding="utf-8"))
        assert jh.validate_json_structure(final, "data") is True
        assert _temp_files(json_dir) == []


# =============================================
# BEHAVIOUR PRESERVED
# =============================================


class TestExistingBehaviourUnchanged:
    """The fix must not change what the handler does, only how it lands."""

    def test_round_trip_through_save_and_load(self, json_dir: Path) -> None:
        """A saved document loads back identically."""
        document = _valid_data_doc()

        assert jh.save_json("roundtrip", "data", document) is True
        loaded = jh.load_json("roundtrip", "data")

        assert loaded is not None
        assert loaded["operations_total"] == 7

    def test_invalid_structure_still_refused_before_writing(self, json_dir: Path) -> None:
        """Structure validation still rejects bad documents, and writes nothing."""
        assert jh.save_json("bad", "config", {"missing": "fields"}) is False
        assert not (json_dir / "bad_config.json").exists()

    def test_save_json_still_reports_failure_as_false(self, json_dir: Path) -> None:
        """A write that raises is still answered with False, not an exception."""
        with patch(_HELPER_TARGET, side_effect=OSError("disk full")):
            assert jh.save_json("boom", "data", _valid_data_doc()) is False

    def test_ensure_json_exists_still_reports_failure_as_false(self, json_dir: Path) -> None:
        """The create path keeps its bool contract - load_json depends on it."""
        with patch(_HELPER_TARGET, side_effect=OSError("disk full")):
            assert jh.ensure_json_exists("boom", "config") is False

    def test_log_operation_still_appends(self, json_dir: Path) -> None:
        """log_operation writes through the new path and keeps appending."""
        jh.log_operation("first", {"x": 1}, "logger_module")
        jh.log_operation("second", {"x": 2}, "logger_module")

        log = jh.load_json("logger_module", "log")
        assert log is not None
        assert [entry["operation"] for entry in log] == ["first", "second"]

    def test_written_file_keeps_utf8_and_indent(self, json_dir: Path) -> None:
        """Documents stay human-readable: indent 2, unescaped non-ASCII."""
        document = _valid_data_doc()
        document["note"] = "café — ok"

        jh.save_json("formatting", "data", document)
        raw = jh.get_json_path("formatting", "data").read_text(encoding="utf-8")

        assert "café — ok" in raw
        assert '\n  "created"' in raw

    def test_no_temp_files_left_in_json_dir_after_normal_use(self, json_dir: Path) -> None:
        """Ordinary handler use leaves the directory clean."""
        jh.ensure_module_jsons("tidy")
        jh.log_operation("worked", {"ok": True}, "tidy")

        assert _temp_files(json_dir) == []
        assert os.path.isfile(json_dir / "tidy_data.json")
