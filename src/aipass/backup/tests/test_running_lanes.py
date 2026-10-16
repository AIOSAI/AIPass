# =================== AIPass ====================
# Name: test_running_lanes.py
# Description: Tests for the running-lane progress files every lane writes under .backup/running/
# Version: 1.0.0
# Created: 2026-10-16
# Modified: 2026-10-16
# =============================================

"""Tests for apps/handlers/state/progress.py as snapshot, versioned, all and drive_sync drive it."""

# A new file for DPLAN-0412 item 1: the progress file is one behaviour shared by
# four lanes, so it reads as one unit here rather than four slices in four files.
# The reader's side, status --json's "running" list, is pinned in test_status_json.py.
#
# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(stdlib) — os.replace's atomicity; the json service's write_json is the one writer

from __future__ import annotations

import copy
import json
import os
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from aipass.backup.apps import backup as entry
from aipass.backup.apps.handlers.drive import client as drive_client
from aipass.backup.apps.handlers.drive import upload as drive_upload
from aipass.backup.apps.handlers.json import json_handler
from aipass.backup.apps.handlers.state import progress
from aipass.backup.apps.modules import display, drive_sync, snapshot

ENTRY_KEYS = ["verb", "lane", "pid", "started_at", "progress"]
PROGRESS_KEYS = ["done", "total", "failed", "bytes_done", "bytes_total", "current", "updated_at"]


@pytest.fixture(autouse=True)
def quiet_headers(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record the panel titles instead of drawing them."""
    # header() fires @cli's event bus; replaced where display binds it, so nothing fires.
    titles: list[str] = []
    monkeypatch.setattr(display, "header", lambda title, *args, **kwargs: titles.append(title))
    return titles


@pytest.fixture
def writes(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict]]:
    """Every running file written, as (file name, a copy of the document), still written for real."""
    real_write = json_handler.write_json
    seen: list[tuple[str, dict]] = []

    def _record(path, data, *args, **kwargs):
        """Keep a copy of a running-file write, then write it."""
        if Path(path).parent.name == progress.RUNNING_DIRNAME:
            seen.append((Path(path).name, copy.deepcopy(data)))
        return real_write(path, data, *args, **kwargs)

    monkeypatch.setattr(json_handler, "write_json", _record)
    return seen


def _ticking_clock(monkeypatch: pytest.MonkeyPatch, step: float) -> None:
    """A clock that moves ``step`` seconds every time the progress files read it."""
    moments = iter(1_800_000_000.0 + step * n for n in range(100_000))
    monkeypatch.setattr(progress, "now", lambda: next(moments))


def _project(root: Path, files: int = 5, size: int = 10) -> Path:
    """A project of ``files`` files of ``size`` bytes, in two directories; its .backupignore keeps itself out."""
    root.mkdir(parents=True)
    (root / ".backupignore").write_text(".backup/\n.backupignore\n", encoding="utf-8")
    for index in range(files):
        folder = root / ("src" if index % 2 else "docs")
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"f{index}.txt").write_text("x" * size, encoding="utf-8")
    return root


def _main(argv: list[str]) -> int:
    """Run the real entry point with argv."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("sys.argv", ["backup", *argv])
        return entry.main()


class TestTheSnapshotLaneWritesItsProgressFile:
    """A snapshot announces itself in .backup/running/snapshot.json and removes the file when it ends."""

    def test_the_first_write_is_the_contract_entry_with_progress_null_and_later_writes_count_the_files(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, writes: list
    ) -> None:
        root = _project(tmp_path / "proj")
        _ticking_clock(monkeypatch, step=2.0)

        assert _main(["snapshot", str(root)]) == 0

        names = {name for name, _doc in writes}
        assert names == {"snapshot.json"}
        first = writes[0][1]
        assert list(first) == ENTRY_KEYS
        assert first["verb"] == "snapshot" and first["lane"] == "snapshot"
        assert first["pid"] == os.getpid()
        assert datetime.fromisoformat(first["started_at"]).utcoffset() is not None
        assert first["progress"] is None
        last = writes[-1][1]["progress"]
        assert list(last) == PROGRESS_KEYS
        assert last["total"] == 5 and last["done"] == 5 and last["failed"] == 0
        assert last["bytes_done"] == 50 and last["bytes_total"] is None
        assert last["current"] in {"docs/f0.txt", "src/f1.txt", "docs/f2.txt", "src/f3.txt", "docs/f4.txt"}
        assert [doc["progress"]["done"] for _n, doc in writes[1:]] == sorted(
            doc["progress"]["done"] for _n, doc in writes[1:]
        )
        assert not (root / ".backup" / "running" / "snapshot.json").exists()

    def test_a_clock_that_does_not_move_a_second_writes_the_file_once(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, writes: list
    ) -> None:
        root = _project(tmp_path / "proj", files=8)
        monkeypatch.setattr(progress, "now", lambda: 1_800_000_000.0)

        assert _main(["snapshot", str(root)]) == 0

        assert [doc["progress"] for _n, doc in writes] == [None]

    def test_writes_are_at_least_a_second_apart_on_the_lanes_clock(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, writes: list
    ) -> None:
        root = _project(tmp_path / "proj", files=12)
        _ticking_clock(monkeypatch, step=0.4)

        assert _main(["snapshot", str(root)]) == 0

        stamps = [datetime.fromisoformat(doc["progress"]["updated_at"]) for _n, doc in writes[1:]]
        assert len(stamps) >= 2
        assert all((later - earlier).total_seconds() >= 1 for earlier, later in zip(stamps, stamps[1:]))

    def test_a_run_that_raises_still_removes_its_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, writes: list
    ) -> None:
        root = _project(tmp_path / "proj")

        def _broken(*args, **kwargs):
            """A copy engine that dies mid-run."""
            raise RuntimeError("disk gone")

        monkeypatch.setattr(snapshot, "copy_snapshot", _broken)

        with pytest.raises(RuntimeError, match="disk gone"):
            snapshot.run_snapshot(str(root), show_panels=False)

        assert writes, "the lane never announced itself"
        assert not (root / ".backup" / "running" / "snapshot.json").exists()

    def test_a_missing_root_writes_no_running_file_and_scaffolds_nothing(self, tmp_path: Path, writes: list) -> None:
        missing = tmp_path / "gone"

        snapshot.run_snapshot(str(missing), show_panels=False)

        assert writes == []
        assert not missing.exists()


class TestAllWritesEachSubLaneInTurn:
    """Under all, snapshot then versioned each write their own file with verb all and the one pid."""

    def test_each_sub_lane_file_says_verb_all_with_the_same_pid_and_none_is_left_behind(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, writes: list
    ) -> None:
        root = _project(tmp_path / "proj")
        _ticking_clock(monkeypatch, step=2.0)

        assert _main(["all", str(root), "--quiet"]) == 0

        lanes_in_order = []
        for name, _doc in writes:
            if not lanes_in_order or lanes_in_order[-1] != name:
                lanes_in_order.append(name)
        assert lanes_in_order == ["snapshot.json", "versioned.json"]
        assert {doc["verb"] for _n, doc in writes} == {"all"}
        assert {doc["lane"] + ".json" == name for name, doc in writes} == {True}
        assert {doc["pid"] for _n, doc in writes} == {os.getpid()}
        assert list((root / ".backup" / "running").iterdir()) == []


class TestTheDriveLaneWritesItsProgressFile:
    """drive_sync's file carries the planned bytes and store-relative paths."""

    def test_the_drive_file_plans_the_upload_and_names_store_relative_paths(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, writes: list
    ) -> None:
        project = tmp_path / "proj"
        store = project / ".backup" / "snapshots" / "sub"
        store.mkdir(parents=True)
        for name in ("a.txt", "b.txt", "c.txt"):
            (store / name).write_text("y" * 100, encoding="utf-8")
        _ticking_clock(monkeypatch, step=2.0)
        instance = _client(monkeypatch)
        monkeypatch.setattr(drive_upload, "upload_single_file", _fake_upload(instance))

        result = drive_sync.run_drive_sync(str(project), show_panels=False)

        assert result["success"] is True and result["uploaded"] == 3
        assert {name for name, _doc in writes} == {"drive_sync.json"}
        assert writes[0][1]["progress"] is None
        last = writes[-1][1]["progress"]
        assert last["total"] == 3 and last["done"] == 3 and last["bytes_total"] == 300
        assert last["bytes_done"] == 300
        assert last["current"] in {"sub/a.txt", "sub/b.txt", "sub/c.txt"}
        assert not (project / ".backup" / "running" / "drive_sync.json").exists()


def _client(monkeypatch: pytest.MonkeyPatch):
    """A DriveClient stand-in with room on the account; it talks to nobody."""
    instance = MagicMock(name="DriveClient")
    instance.authenticate.return_value = True
    instance.last_error = None
    instance._api_call.return_value = {"storageQuota": {"usage": "0", "limit": str(10**12)}}
    monkeypatch.setattr(drive_client, "DriveClient", MagicMock(return_value=instance))
    return instance


def _fake_upload(instance):
    """An upload_single_file stand-in that tracks every file and succeeds."""

    def _upload(client, local_file, project_name, backup_root, note="", lane_folder=""):
        """Record the file in the tracker the batch shares, as a real upload would."""
        client.file_tracker[str(Path(local_file).relative_to(backup_root))] = {"drive_id": "id"}
        return True

    return _upload


class TestTheReaderDropsStaleFiles:
    """A running file whose process is gone, or whose pid now belongs to a younger process, is stale."""

    def test_a_file_whose_pid_started_after_the_lane_is_not_listed_and_is_removed(self, tmp_path: Path) -> None:
        root = tmp_path / "proj"
        running = root / ".backup" / "running"
        running.mkdir(parents=True)
        stale = running / "snapshot.json"
        stale.write_text(
            json.dumps(
                {
                    "verb": "snapshot",
                    "lane": "snapshot",
                    "pid": os.getpid(),
                    "started_at": "2001-01-01T00:00:00+00:00",
                    "progress": None,
                }
            ),
            encoding="utf-8",
        )

        assert progress.read_running(str(root)) == []
        assert not stale.exists()

    def test_a_file_for_this_live_process_is_listed_as_written(self, tmp_path: Path) -> None:
        root = tmp_path / "proj"
        (root / ".backup").mkdir(parents=True)
        lane = progress.LaneProgress(str(root), "versioned", "all")
        lane.start()
        try:
            listed = progress.read_running(str(root))
        finally:
            lane.close()

        assert len(listed) == 1
        assert listed[0]["verb"] == "all" and listed[0]["lane"] == "versioned"
        assert listed[0]["pid"] == os.getpid() and listed[0]["progress"] is None
        assert progress.read_running(str(root)) == []

    def test_a_root_with_no_store_reads_empty_and_gains_no_directory(self, tmp_path: Path) -> None:
        root = tmp_path / "fresh"
        root.mkdir()

        assert progress.read_running(str(root)) == []
        assert list(root.iterdir()) == []
