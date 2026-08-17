# ===================AIPASS====================
# META DATA HEADER
# Name: test_json_durability.py - JSON Handler Durability Tests
# Date: 2026-08-16
# Version: 1.0.0
# Category: commons/tests
#
# CHANGELOG (Max 5 entries):
#   - v1.0.0 (2026-08-16): Initial creation — torn-write (axis 1) regression suite
#
# CODE STANDARDS:
#   - Pytest function style (no unittest classes)
#   - tmp_path + monkeypatch for file isolation — never the live commons_json/
#   - Mock heavy deps (prax logger)
# =============================================

"""
Durability tests for the commons JSON handler.

Covers the fleet-wide torn-write defect (error 90c9e40d): opening a live
document with mode "w" truncates it before the new bytes land, so a concurrent
reader sees an empty or partial file. In this handler that reader is often
``ensure_json_exists`` itself, which answers an unreadable document by writing
template defaults over it — turning a transient race into permanent data loss.

These tests pin the atomic-write helper, prove every write site routes through
it, guard the source against a truncating ``open`` returning, and measure a
2-writer/2-reader race for zero unusable reads.
"""

import json
import re
import threading
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Mock the prax logger before importing the module under test
import sys

_mock_logger = MagicMock()
_mock_logger_module = MagicMock()
_mock_logger_module.system_logger = _mock_logger

try:
    from aipass.prax.apps.modules.logger import system_logger  # noqa: F401
except ImportError:
    sys.modules.setdefault("aipass.prax", MagicMock())
    sys.modules.setdefault("aipass.prax.apps", MagicMock())
    sys.modules.setdefault("aipass.prax.apps.modules", MagicMock())
    sys.modules.setdefault("aipass.prax.apps.modules.logger", _mock_logger_module)

import aipass.commons.apps.handlers.json.json_handler as json_handler_mod  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _valid_data(module_name: str = "durability", filler: str = "x") -> dict:
    """Build a structurally valid 'data' document with a wide truncation window."""
    return {
        "module_name": module_name,
        "created": "2026-08-16",
        "last_updated": "2026-08-16",
        "filler": [filler * 64 for _ in range(400)],
    }


def _temp_files(directory: Path) -> list:
    """Return staged temp artifacts left behind in a directory."""
    return [path for path in directory.iterdir() if path.suffix == ".tmp"]


@pytest.fixture
def json_dir(tmp_path, monkeypatch):
    """Point the handler at a throwaway JSON directory for the duration of a test."""
    target = tmp_path / "commons_json"
    target.mkdir()
    monkeypatch.setattr(json_handler_mod, "BRANCH_JSON_DIR", str(target))
    return target


# ---------------------------------------------------------------------------
# Atomic write helper
# ---------------------------------------------------------------------------


def test_atomic_helper_exists():
    """The handler exposes an atomic write helper."""
    assert hasattr(json_handler_mod, "_atomic_write_json"), (
        "_atomic_write_json missing — writes still truncate in place"
    )


def test_atomic_write_creates_missing_file(json_dir):
    """Writing to a path that does not exist yet creates it with the given content."""
    target = json_dir / "created.json"

    json_handler_mod._atomic_write_json(target, {"hello": "world"})

    assert json.loads(target.read_text(encoding="utf-8")) == {"hello": "world"}


def test_atomic_write_replaces_existing_content(json_dir):
    """Writing over an existing document fully replaces its content."""
    target = json_dir / "replaced.json"
    target.write_text(json.dumps({"generation": 1}), encoding="utf-8")

    json_handler_mod._atomic_write_json(target, {"generation": 2})

    assert json.loads(target.read_text(encoding="utf-8")) == {"generation": 2}


def test_atomic_write_leaves_no_temp_file(json_dir):
    """A successful write cleans up after itself — the handler globs this directory."""
    target = json_dir / "clean.json"

    json_handler_mod._atomic_write_json(target, {"ok": True})

    assert _temp_files(json_dir) == []


def test_atomic_write_stages_temp_in_target_directory(json_dir, monkeypatch):
    """
    The temp file is staged in the TARGET directory.

    os.replace is only atomic within one filesystem; staging in /tmp would make
    the rename a cross-device copy and reopen the very window being closed.
    """
    seen = {}
    real_mkstemp = json_handler_mod.tempfile.mkstemp

    def spy_mkstemp(*args, **kwargs):
        seen["dir"] = kwargs.get("dir")
        return real_mkstemp(*args, **kwargs)

    monkeypatch.setattr(json_handler_mod.tempfile, "mkstemp", spy_mkstemp)
    target = json_dir / "staged.json"

    json_handler_mod._atomic_write_json(target, {"ok": True})

    assert seen["dir"] is not None, "mkstemp called without an explicit dir"
    assert Path(seen["dir"]).resolve() == json_dir.resolve()


def test_failed_write_leaves_original_intact_and_cleans_temp(json_dir, monkeypatch):
    """A write that blows up mid-flight must not damage the live document."""
    target = json_dir / "survivor.json"
    original = {"generation": "original"}
    target.write_text(json.dumps(original), encoding="utf-8")

    def exploding_dump(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(json_handler_mod.json, "dump", exploding_dump)

    with pytest.raises(OSError):
        json_handler_mod._atomic_write_json(target, {"generation": "doomed"})

    assert json.loads(target.read_text(encoding="utf-8")) == original
    assert _temp_files(json_dir) == []


# ---------------------------------------------------------------------------
# Write sites routed through the helper
# ---------------------------------------------------------------------------


def test_save_json_routes_through_atomic_helper(json_dir, monkeypatch):
    """save_json writes atomically."""
    calls = []
    monkeypatch.setattr(
        json_handler_mod,
        "_atomic_write_json",
        lambda target, data: calls.append(Path(target)),
    )

    json_handler_mod.save_json("durability", "data", _valid_data())

    assert len(calls) == 1
    assert calls[0].name == "durability_data.json"


def test_ensure_json_exists_regenerate_routes_through_atomic_helper(json_dir, monkeypatch):
    """
    The regenerate path writes atomically.

    This is the site that converts a torn read into permanent data loss: it
    overwrites a live document with template defaults.
    """
    corrupt = json_dir / "durability_data.json"
    corrupt.write_text("{ this is not json", encoding="utf-8")

    calls = []
    monkeypatch.setattr(
        json_handler_mod,
        "_atomic_write_json",
        lambda target, data: calls.append(Path(target)),
    )

    json_handler_mod.ensure_json_exists("durability", "data")

    assert len(calls) == 1
    assert calls[0].name == "durability_data.json"


def test_ensure_json_exists_creates_missing_file_atomically(json_dir, monkeypatch):
    """Creating a brand-new document also goes through the helper."""
    calls = []
    monkeypatch.setattr(
        json_handler_mod,
        "_atomic_write_json",
        lambda target, data: calls.append(Path(target)),
    )

    json_handler_mod.ensure_json_exists("fresh", "config")

    assert len(calls) == 1
    assert calls[0].name == "fresh_config.json"


# ---------------------------------------------------------------------------
# Source guard
# ---------------------------------------------------------------------------


def test_no_truncating_open_survives_in_source():
    """
    No write-mode open() on a path remains in the handler.

    A guard, not a style rule: one re-introduced open(path, "w") restores the
    whole defect, and it reads as harmless in review. os.fdopen is exempt — it
    wraps a descriptor tempfile.mkstemp already created privately, so there is
    no live document to truncate.
    """
    source = Path(json_handler_mod.__file__).read_text(encoding="utf-8")
    offenders = re.findall(r"(?<!fd)open\([^)]*[\"'][wa]\+?[bt]?[\"']", source)

    assert offenders == [], f"truncating open() found in handler source: {offenders}"


# ---------------------------------------------------------------------------
# Concurrency probe — the defect itself
# ---------------------------------------------------------------------------


def test_concurrent_writers_never_expose_a_torn_document(json_dir):
    """
    Two writers and two readers on one document produce zero unusable reads.

    Measured against the unfixed handler this same way: 1,297 reads, 553 empty
    and 485 unparseable — 80.03% unusable.
    """
    module_name = "durability"
    target = Path(json_handler_mod.get_json_path(module_name, "data"))
    json_handler_mod.save_json(module_name, "data", _valid_data(filler="a"))

    stop = threading.Event()
    counts = {"ok": 0, "empty": 0, "unparseable": 0}
    lock = threading.Lock()
    iterations = 150

    def writer(filler):
        for _ in range(iterations):
            json_handler_mod.save_json(module_name, "data", _valid_data(filler=filler))
        stop.set()

    def reader():
        local = {"ok": 0, "empty": 0, "unparseable": 0}
        while not stop.is_set():
            try:
                raw = target.read_text(encoding="utf-8")
            except OSError:
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
        thread.join()

    assert counts["ok"] > 0, "probe never observed a readable document"
    assert counts["empty"] == 0, f"{counts['empty']} readers saw an empty document"
    assert counts["unparseable"] == 0, f"{counts['unparseable']} readers saw a partial document"
