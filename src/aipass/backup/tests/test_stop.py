# =================== AIPass ====================
# Name: test_stop.py
# Description: Tests for the stop verb and the lane side of a stop: the SIGTERM flag, the stopped line, exit 130
# Version: 1.0.0
# Created: 2026-10-16
# Modified: 2026-10-16
# =============================================

"""Tests for apps/modules/stop.py and the lane side it signals: snapshot, versioned, all and drive_sync stopping."""

# A new file for DPLAN-0412 item 3. A real SIGTERM is never sent here (template
# item 23: no signals in tests): the lane's own installed handler is called the
# way the interpreter would call it, and the other process the stop verb signals
# is a stand-in behind lane_process.open_process, the one seam to the process table.
#
# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(stdlib) — signal.signal installing a handler in the main thread

from __future__ import annotations

import json
import copy
import signal
import threading
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import psutil
import pytest

from aipass.backup.apps import backup as entry
from aipass.backup.apps.handlers.audit import trail
from aipass.backup.apps.handlers.drive import client as drive_client
from aipass.backup.apps.handlers.drive import tracker as drive_tracker
from aipass.backup.apps.handlers.drive import upload as drive_upload
from aipass.backup.apps.handlers.json import json_handler
from aipass.backup.apps.handlers.state import lane_process, progress, stop_flag
from aipass.backup.apps.handlers.state.changelog import load_changelog
from aipass.backup.apps.modules import display, snapshot

SIZE = 1000


@pytest.fixture(autouse=True)
def quiet_headers(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record the panel titles instead of drawing them."""
    # header() fires @cli's event bus; replaced where display binds it, so nothing fires.
    titles: list[str] = []
    monkeypatch.setattr(display, "header", lambda title, *args, **kwargs: titles.append(title))
    return titles


def _project(root: Path, files: int = 5) -> Path:
    """A project of ``files`` files of SIZE bytes each; its .backupignore keeps itself out of the count."""
    root.mkdir(parents=True)
    (root / ".backupignore").write_text(".backup/\n.backupignore\n", encoding="utf-8")
    for index in range(files):
        (root / f"f{index}.txt").write_text("x" * SIZE, encoding="utf-8")
    return root


def _main(argv: list[str]) -> int:
    """Run the real entry point with argv."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("sys.argv", ["backup", *argv])
        return entry.main()


def _sigterm() -> None:
    """Deliver SIGTERM the way the interpreter does: call the handler the lane installed."""
    handler = signal.getsignal(signal.SIGTERM)
    assert callable(handler), "no SIGTERM handler installed for the run"
    handler(signal.SIGTERM, None)


def _sigterm_after_files(monkeypatch: pytest.MonkeyPatch, done: int) -> list[dict]:
    """SIGTERM the run as soon as its progress file says ``done`` files are done.

    The lane's clock moves two seconds per read, so every finished file is written.
    """
    moments = iter(1_800_000_000.0 + 2.0 * n for n in range(100_000))
    monkeypatch.setattr(progress, "now", lambda: next(moments))
    real_write = json_handler.write_json
    seen: list[dict] = []

    def _write(path, data, *args, **kwargs):
        """Write for real; the write that reports ``done`` files delivers SIGTERM."""
        answer = real_write(path, data, *args, **kwargs)
        if Path(path).parent.name == progress.RUNNING_DIRNAME:
            seen.append(copy.deepcopy(data))
            if (data.get("progress") or {}).get("done") == done:
                _sigterm()
        return answer

    monkeypatch.setattr(json_handler, "write_json", _write)
    return seen


def _trail_rows(operation: str) -> list[dict]:
    """The audit stream's rows for one operation."""
    path = trail.log_path()
    if not path.exists():
        return []
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [row for row in rows if row.get("operation") == operation]


class TestTheStoppedLine:
    """The last line a stopped lane prints: counts with thousands separators, bytes humanised."""

    def test_the_contract_example_reads_exactly(self) -> None:
        line = stop_flag.stopped_line(1204, 15414, 325058560)

        assert line == "stopped by request: 1,204 of 15,414 files, 310 MB"

    def test_a_fraction_of_a_unit_keeps_its_decimal(self) -> None:
        assert stop_flag.stopped_line(1, 2, 1536) == "stopped by request: 1 of 2 files, 1.5 KB"


class TestASnapshotStopsBetweenFiles:
    """SIGTERM mid-snapshot: the copy stops between files, no record of a completed run, exit 130."""

    def test_the_run_stops_after_the_file_in_flight_says_so_last_and_exits_130(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root = _project(tmp_path / "proj")
        _sigterm_after_files(monkeypatch, done=2)
        before = signal.getsignal(signal.SIGTERM)

        assert _main(["snapshot", str(root)]) == 130

        assert len(list((root / ".backup" / "snapshots").iterdir())) == 2
        assert capsys.readouterr().out.splitlines()[-1] == "stopped by request: 2 of 5 files, 2 KB"
        assert signal.getsignal(signal.SIGTERM) is before
        assert load_changelog(str(root)) == []
        assert not (root / ".backup" / "timestamps.json").exists()
        assert not (root / ".backup" / "running" / "snapshot.json").exists()
        rows = _trail_rows("snapshot_stopped")
        assert len(rows) == 1
        assert rows[0]["done"] == 2 and rows[0]["total"] == 5 and rows[0]["bytes_done"] == 2 * SIZE
        assert rows[0]["verb"] == "snapshot"

    def test_a_run_nobody_stops_exits_0_and_records_itself(self, tmp_path: Path) -> None:
        root = _project(tmp_path / "proj")

        assert _main(["snapshot", str(root)]) == 0

        assert [entry_["mode"] for entry_ in load_changelog(str(root))] == ["snapshot"]
        assert _trail_rows("snapshot_stopped") == []

    def test_a_run_off_the_main_thread_cannot_catch_sigterm_and_still_completes(self, tmp_path: Path) -> None:
        root = _project(tmp_path / "proj")
        results: list = []
        worker = threading.Thread(target=lambda: results.append(snapshot.run_snapshot(str(root), show_panels=False)))

        worker.start()
        worker.join(timeout=60)

        assert len(results) == 1 and results[0].files_copied == 5


class TestAVersionedRunStops:
    """SIGTERM mid-versioned: same rules as snapshot."""

    def test_the_versioned_run_stops_between_files_and_exits_130(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root = _project(tmp_path / "proj", files=4)
        _sigterm_after_files(monkeypatch, done=1)

        assert _main(["versioned", str(root)]) == 130

        assert capsys.readouterr().out.splitlines()[-1] == "stopped by request: 1 of 4 files, 1000 B"
        assert load_changelog(str(root)) == []
        assert len(_trail_rows("versioned_stopped")) == 1


class TestAllStopsTheCurrentSubLaneAndStartsNoOther:
    """Under all, a stop in snapshot leaves versioned and the Drive step unstarted."""

    def test_a_stop_in_snapshot_never_starts_versioned_and_all_exits_130(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root = _project(tmp_path / "proj")
        _sigterm_after_files(monkeypatch, done=3)

        assert _main(["all", str(root), "--quiet"]) == 130

        assert capsys.readouterr().out.splitlines()[-1] == "stopped by request: 3 of 5 files, 2.9 KB"
        assert not (root / ".backup" / "versioned").exists()
        assert _trail_rows("all_complete") == []
        rows = _trail_rows("snapshot_stopped")
        assert len(rows) == 1 and rows[0]["verb"] == "all"


def _drive_project(tmp_path: Path, files: int) -> tuple[Path, Path]:
    """A project whose snapshot store holds ``files`` small files."""
    project = tmp_path / "proj"
    store = project / ".backup" / "snapshots"
    store.mkdir(parents=True)
    for index in range(files):
        (store / f"file_{index:03d}.txt").write_text("x", encoding="utf-8")
    return project, store


class TestADriveRunStops:
    """SIGTERM mid-upload: files not yet started never go, the tracker keeps what went, exit 130."""

    def test_a_stop_after_60_of_120_uploads_sends_no_more_saves_the_tracker_and_exits_130(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        project, _store = _drive_project(tmp_path, files=120)
        instance = MagicMock(name="DriveClient")
        instance.authenticate.return_value = True
        instance.last_error = None
        instance._api_call.return_value = {"storageQuota": {"usage": "0", "limit": str(10**12)}}
        monkeypatch.setattr(drive_client, "DriveClient", MagicMock(return_value=instance))
        sent: list[str] = []

        def _upload(client, local_file, project_name, backup_root, note="", lane_folder=""):
            """Track the file as a real upload would; the 60th delivers SIGTERM."""
            sent.append(local_file.name)
            client.file_tracker[str(local_file.relative_to(backup_root))] = {"drive_id": "id"}
            if len(sent) == 60:
                _sigterm()
            return True

        monkeypatch.setattr(drive_upload, "upload_single_file", _upload)

        assert _main(["drive_sync", str(project)]) == 130

        # Three workers: the files already in flight when the flag rose may finish, nothing after.
        assert 60 <= len(sent) <= 62
        out = capsys.readouterr().out.splitlines()
        assert out[-1].startswith(f"stopped by request: {len(sent)} of 120 files, ")
        saved = json.loads((project / ".backup" / drive_tracker.TRACKER_FILENAME).read_text(encoding="utf-8"))
        assert len(set(saved) - {drive_tracker.LANE_KEY}) == len(sent)
        assert load_changelog(str(project)) == []
        rows = _trail_rows("drive_sync_stopped")
        assert len(rows) == 1 and rows[0]["done"] == len(sent) and rows[0]["total"] == 120

    def test_upload_batch_stopped_part_way_reports_it_and_has_saved_at_least_50_entries(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        project, store = _drive_project(tmp_path, files=120)
        files = sorted(store.iterdir())
        client = MagicMock(name="DriveClient")

        def _upload(client_, local_file, project_name, backup_root, note="", lane_folder=""):
            """Track the file; the 60th raises the stop flag."""
            client_.file_tracker[str(local_file.relative_to(backup_root))] = {"drive_id": "id"}
            if len(client_.file_tracker) == 60:
                _sigterm()
            return True

        monkeypatch.setattr(drive_upload, "upload_single_file", _upload)

        with stop_flag.catch_sigterm():
            result = drive_upload.upload_batch(
                client, files, "proj", store, {}, max_workers=1, project_root=str(project)
            )

        assert result["stopped"] is True
        assert result["uploaded"] == 60 and result["failed"] == 0
        saved = json.loads((project / ".backup" / drive_tracker.TRACKER_FILENAME).read_text(encoding="utf-8"))
        assert len(set(saved) - {drive_tracker.LANE_KEY}) >= 50


class FakeLane:
    """A stand-in for another process in the table: what psutil.Process answers, recorded."""

    def __init__(self, pid: int, cmdline: list[str], created: float, waits: list[str] | None = None) -> None:
        self.pid = pid
        self._cmdline = cmdline
        self._created = created
        self._waits = list(waits or ["gone"])
        self.calls: list[str] = []
        self.timeouts: list[float | None] = []

    def cmdline(self) -> list[str]:
        """The command line the lane was started with."""
        return self._cmdline

    def create_time(self) -> float:
        """When the process started."""
        return self._created

    def status(self) -> str:
        """Running, never a zombie."""
        return psutil.STATUS_RUNNING

    def terminate(self) -> None:
        """Record SIGTERM."""
        self.calls.append("terminate")

    def kill(self) -> None:
        """Record SIGKILL."""
        self.calls.append("kill")

    def wait(self, timeout: float | None = None) -> int:
        """Gone, or still there at the timeout, in the order the test scripted."""
        self.timeouts.append(timeout)
        if self._waits.pop(0) == "timeout":
            raise psutil.TimeoutExpired(timeout or 0)
        return 0


STARTED = "2026-10-16T13:37:08+00:00"
STARTED_EPOCH = datetime.fromisoformat(STARTED).timestamp()


def _running(root: Path, lane: str, pid: int, verb: str | None = None) -> Path:
    """Write a running file the way a lane does."""
    folder = root / ".backup" / "running"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{lane}.json"
    path.write_text(
        json.dumps({"verb": verb or lane, "lane": lane, "pid": pid, "started_at": STARTED, "progress": None}),
        encoding="utf-8",
    )
    return path


def _table(monkeypatch: pytest.MonkeyPatch, *lanes: FakeLane) -> None:
    """The process table holds exactly these processes."""
    by_pid = {lane.pid: lane for lane in lanes}
    monkeypatch.setattr(lane_process, "open_process", lambda pid: by_pid.get(pid))


class TestTheStopVerb:
    """drone @backup stop <root> [lane]: signal what runs for that root, and only that."""

    def test_a_running_snapshot_gets_sigterm_and_one_line_and_the_verb_exits_0(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root = _project(tmp_path / "proj", files=1)
        _running(root, "snapshot", 4242)
        lane = FakeLane(4242, ["python3", "apps/backup.py", "snapshot", str(root)], STARTED_EPOCH - 1)
        _table(monkeypatch, lane)

        assert _main(["stop", str(root)]) == 0

        out, err = capsys.readouterr()
        assert out.splitlines() == ["stopped snapshot (pid 4242)"]
        assert err == ""
        assert lane.calls == ["terminate"]
        assert lane.timeouts == [30]

    def test_a_lane_that_outlives_the_wait_is_killed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root = _project(tmp_path / "proj", files=1)
        _running(root, "drive_sync", 77)
        lane = FakeLane(77, ["python3", "apps/backup.py", "drive_sync", str(root)], STARTED_EPOCH, ["timeout", "gone"])
        _table(monkeypatch, lane)

        assert _main(["stop", str(root)]) == 0

        assert lane.calls == ["terminate", "kill"]
        assert capsys.readouterr().out.splitlines() == ["stopped drive_sync (pid 77)"]

    def test_nothing_running_is_one_line_and_a_non_zero_exit(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root = _project(tmp_path / "proj", files=1)

        assert _main(["stop", str(root)]) != 0

        out, err = capsys.readouterr()
        assert out.splitlines() == ["nothing running for proj"]
        assert err == ""

    def test_the_project_in_the_line_is_the_name_status_reports(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root = _project(tmp_path / "proj", files=1)
        (root / ".backup").mkdir()
        (root / ".backup" / "config.json").write_text(json.dumps({"project_name": "AIPass"}), encoding="utf-8")

        assert _main(["stop", str(root)]) != 0

        assert capsys.readouterr().out.splitlines() == ["nothing running for AIPass"]

    def test_a_named_lane_that_is_not_running_leaves_the_running_one_alone(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root = _project(tmp_path / "proj", files=1)
        _running(root, "snapshot", 4242)
        lane = FakeLane(4242, ["python3", "apps/backup.py", "snapshot", str(root)], STARTED_EPOCH)
        _table(monkeypatch, lane)

        assert _main(["stop", str(root), "drive_sync"]) != 0

        assert capsys.readouterr().out.splitlines() == ["drive_sync is not running for proj"]
        assert lane.calls == []

    def test_naming_all_stops_the_sub_lane_an_all_run_is_in(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root = _project(tmp_path / "proj", files=1)
        _running(root, "versioned", 900, verb="all")
        lane = FakeLane(900, ["python3", "apps/backup.py", "all", str(root), "--quiet"], STARTED_EPOCH)
        _table(monkeypatch, lane)

        assert _main(["stop", str(root), "all"]) == 0

        assert capsys.readouterr().out.splitlines() == ["stopped versioned (pid 900)"]
        assert lane.calls == ["terminate"]

    def test_a_pid_whose_command_line_is_not_a_backup_lane_for_this_root_is_never_signalled(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root = _project(tmp_path / "proj", files=1)
        other = _project(tmp_path / "other", files=1)
        _running(root, "snapshot", 4242)
        lane = FakeLane(4242, ["python3", "apps/backup.py", "snapshot", str(other)], STARTED_EPOCH)
        _table(monkeypatch, lane)

        assert _main(["stop", str(root)]) != 0

        out, err = capsys.readouterr()
        assert lane.calls == []
        assert out == ""
        assert "4242" in err and "not signalled" in err

    def test_an_editor_holding_the_pid_is_never_signalled(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root = _project(tmp_path / "proj", files=1)
        _running(root, "snapshot", 4242)
        lane = FakeLane(4242, ["vim", str(root / "f0.txt"), "snapshot"], STARTED_EPOCH)
        _table(monkeypatch, lane)

        assert _main(["stop", str(root)]) != 0

        assert lane.calls == []

    def test_a_recycled_pid_younger_than_the_lane_is_stale_never_signalled_and_its_file_goes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root = _project(tmp_path / "proj", files=1)
        stale = _running(root, "snapshot", 4242)
        lane = FakeLane(4242, ["python3", "apps/backup.py", "snapshot", str(root)], STARTED_EPOCH + 3600)
        _table(monkeypatch, lane)

        assert _main(["stop", str(root)]) != 0

        assert capsys.readouterr().out.splitlines() == ["nothing running for proj"]
        assert lane.calls == []
        assert not stale.exists()

    def test_a_pid_that_is_gone_is_stale_and_its_file_goes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root = _project(tmp_path / "proj", files=1)
        stale = _running(root, "snapshot", 4242)
        _table(monkeypatch)

        assert _main(["stop", str(root)]) != 0

        assert capsys.readouterr().out.splitlines() == ["nothing running for proj"]
        assert not stale.exists()

    def test_an_unknown_lane_word_is_refused_and_nothing_is_signalled(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root = _project(tmp_path / "proj", files=1)
        _running(root, "snapshot", 4242)
        lane = FakeLane(4242, ["python3", "apps/backup.py", "snapshot", str(root)], STARTED_EPOCH)
        _table(monkeypatch, lane)

        assert _main(["stop", str(root), "snapshots"]) != 0

        out, err = capsys.readouterr()
        assert lane.calls == []
        assert "snapshots" in err

    def test_stop_with_help_anywhere_explains_and_signals_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root = _project(tmp_path / "proj", files=1)
        _running(root, "snapshot", 4242)
        lane = FakeLane(4242, ["python3", "apps/backup.py", "snapshot", str(root)], STARTED_EPOCH)
        _table(monkeypatch, lane)

        assert _main(["stop", str(root), "--help"]) == 0

        assert lane.calls == []
        assert "stop <project_root|@name> [lane]" in capsys.readouterr().out
