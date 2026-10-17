# =================== AIPass ====================
# Name: test_status_json.py
# Description: Tests for apps/modules/status.py's --json and --sizes, the backup door's status contract
# Version: 1.1.0
# Created: 2026-10-16
# Modified: 2026-10-16
# =============================================

"""Tests for apps/modules/status.py's --json [--sizes], the backup door's status contract."""

# A new file, not a class in an existing one: the existing status tests live in
# test_caller_path.py and test_cli_routing.py, which another worker holds tonight
# (DPLAN-0411); the gate is open for new test files on this build.
#
# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(stdlib) — json.dumps' encoding of the object once it is built

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from aipass.backup.apps import backup as entry
from aipass.backup.apps.handlers.drive import tracker as drive_tracker
from aipass.backup.apps.handlers.state import progress
from aipass.backup.apps.modules import status

NO_RUN = {"last": None, "files": None}


def _store(root: Path, config: dict | None = None, entries: list[dict] | None = None) -> Path:
    """A project with a .backup/ store holding the config and changelog given."""
    store = root / ".backup"
    store.mkdir(parents=True)
    (store / "config.json").write_text(json.dumps(config or {}), encoding="utf-8")
    if entries is not None:
        (store / "changelog.json").write_text(json.dumps({"entries": entries}), encoding="utf-8")
    return store


def _status_json(root: Path, *flags: str, capsys: pytest.CaptureFixture[str]) -> dict:
    """Run status --json through the command and parse stdout as the ONE object it must be."""
    assert status.handle_command("status", [str(root), "--json", *flags]) is True
    out, err = capsys.readouterr()
    assert err == ""
    return json.loads(out)


class TestStatusJsonWithoutAStore:
    """A root with no .backup/ store is an answer, not an error."""

    def test_a_root_with_no_store_answers_registered_false_every_last_null_and_runs_zero(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root = tmp_path / "fresh"
        root.mkdir()

        answer = _status_json(root, capsys=capsys)

        assert answer == {
            "project": "fresh",
            "root": str(root),
            "registered": False,
            "mode": "snapshot",
            "drive_sync": False,
            "runs": 0,
            "lanes": {"snapshot": NO_RUN, "versioned": NO_RUN, "drive_sync": NO_RUN},
            "drive": {"tracked_files": 0},
            "running": [],
        }
        assert not (root / ".backup").exists(), "status wrote a store it was only asked to read"


class TestStatusJsonFromTheStore:
    """Every field comes from the project's own config, changelog and tracker."""

    def test_the_object_reads_each_lanes_last_run_from_the_changelog_and_omits_store_without_sizes(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root = tmp_path / "proj"
        _store(
            root,
            config={"project_name": "AIPass", "backup_mode": "versioned", "drive_sync": True},
            entries=[
                {"timestamp": "2026-08-01T00:00:00+00:00", "mode": "snapshot", "files_copied": 10},
                {"timestamp": "2026-09-28T03:12:00+00:00", "mode": "versioned", "files_copied": 120},
                {"timestamp": "2026-10-16T07:09:50+00:00", "mode": "snapshot", "files_copied": 15414},
            ],
        )
        drive_tracker.save_tracker(str(root), {"_lane": "snapshot", "a.txt": {"drive_id": "1"}, "b.txt": {}})

        answer = _status_json(root, capsys=capsys)

        assert answer == {
            "project": "AIPass",
            "root": str(root),
            "registered": True,
            "mode": "versioned",
            "drive_sync": True,
            "runs": 3,
            "lanes": {
                "snapshot": {"last": "2026-10-16T07:09:50+00:00", "files": 15414},
                "versioned": {"last": "2026-09-28T03:12:00+00:00", "files": 120},
                "drive_sync": NO_RUN,
            },
            "drive": {"tracked_files": 2},
            "running": [],
        }

    def test_sizes_adds_the_bytes_of_both_stores_and_nothing_else(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root = tmp_path / "proj"
        store = _store(root)
        (store / "snapshots" / "src").mkdir(parents=True)
        (store / "snapshots" / "src" / "a.py").write_text("x" * 7, encoding="utf-8")
        (store / "snapshots" / "b.txt").write_text("y" * 5, encoding="utf-8")
        (store / "versioned" / "root" / "b.txt").mkdir(parents=True)
        (store / "versioned" / "root" / "b.txt" / "b.txt").write_text("z" * 11, encoding="utf-8")

        answer = _status_json(root, "--sizes", capsys=capsys)

        assert answer["store"] == {"snapshots_bytes": 12, "versioned_bytes": 11}
        keys = ["project", "root", "registered", "mode", "drive_sync", "runs", "lanes", "store", "drive", "running"]
        assert list(answer) == keys


class TestStatusJsonRefusals:
    """What status --json refuses, and where the refusal goes."""

    def test_an_absent_root_exits_non_zero_with_one_stderr_line_and_no_stdout(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        missing = tmp_path / "gone"

        with patch("sys.argv", ["backup", "status", str(missing), "--json"]):
            code = entry.main()

        out, err = capsys.readouterr()
        assert code != 0
        assert out == ""
        assert len(err.strip().splitlines()) == 1
        assert "Project path is not a directory" in err
        assert missing.name in err

    def test_sizes_without_json_is_refused_and_prints_no_page(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _store(tmp_path / "proj")

        assert status.handle_command("status", [str(tmp_path / "proj"), "--sizes"]) is True

        out, err = capsys.readouterr()
        assert "--sizes is a --json option" in err
        assert "Backup Status" not in out


class TestStatusJsonRunning:
    """ "running" lists the lanes in flight from .backup/running/, [] when none (DPLAN-0412)."""

    def test_a_lane_in_flight_is_listed_in_the_contract_shape_after_drive(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root = tmp_path / "proj"
        _store(root)
        monkeypatch.setattr(progress, "now", lambda: 1_800_000_000.0)
        lane = progress.LaneProgress(str(root), "drive_sync", "drive_sync")
        lane.start()
        lane.plan(15414, bytes_total=3113851289)
        lane.file_done("projects/photos/03.jpg", 325058560)

        try:
            answer = _status_json(root, capsys=capsys)
        finally:
            lane.close()

        assert list(answer)[-2:] == ["drive", "running"]
        assert answer["running"] == [
            {
                "verb": "drive_sync",
                "lane": "drive_sync",
                "pid": os.getpid(),
                "started_at": "2027-01-15T08:00:00+00:00",
                "progress": None,
            }
        ]

    def test_progress_once_a_second_has_passed_carries_the_counts(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root = tmp_path / "proj"
        _store(root)
        moments = iter([1_800_000_000.0, 1_800_000_000.0, 1_800_000_002.0])
        monkeypatch.setattr(progress, "now", lambda: next(moments))
        lane = progress.LaneProgress(str(root), "drive_sync", "drive_sync")
        lane.start()
        lane.plan(15414, bytes_total=3113851289)
        lane.file_done("projects/photos/03.jpg", 325058560)

        try:
            answer = _status_json(root, capsys=capsys)
        finally:
            lane.close()

        assert answer["running"][0]["progress"] == {
            "done": 1,
            "total": 15414,
            "failed": 0,
            "bytes_done": 325058560,
            "bytes_total": 3113851289,
            "current": "projects/photos/03.jpg",
            "updated_at": "2027-01-15T08:00:02+00:00",
        }

    def test_a_stale_file_is_left_out_and_removed_by_the_read(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root = tmp_path / "proj"
        store = _store(root)
        (store / "running").mkdir()
        stale = store / "running" / "snapshot.json"
        entry_doc = {"verb": "snapshot", "lane": "snapshot", "pid": os.getpid()}
        stale.write_text(
            json.dumps({**entry_doc, "started_at": "2001-01-01T00:00:00+00:00", "progress": None}), encoding="utf-8"
        )

        answer = _status_json(root, capsys=capsys)

        assert answer["running"] == []
        assert not stale.exists()

    def test_the_status_page_names_a_running_lane(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        root = tmp_path / "proj"
        _store(root)
        lane = progress.LaneProgress(str(root), "snapshot", "all")
        lane.start()

        try:
            assert status.handle_command("status", [str(root)]) is True
        finally:
            lane.close()

        out = capsys.readouterr().out
        assert f"Running:      snapshot (all, pid {os.getpid()}), scanning" in out


# =============================================
