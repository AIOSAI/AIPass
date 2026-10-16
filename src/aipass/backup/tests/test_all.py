# =================== AIPass ====================
# Name: test_all.py
# Description: Tests for the all cycle's Drive switch, its Drive step's headroom refusal and the --registered run
# Version: 1.1.0
# Created: 2026-10-16
# Modified: 2026-10-16
# =============================================

"""Tests for apps/modules/all.py: the drive_sync setting it obeys and the --registered run."""

# The help gate, the single-scan hand-off and the secrets watch for 'all' stay
# in test_cli_routing.py, where every verb's routing is pinned together.
#
# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(stdlib) — time.monotonic's clock; the seconds column is pinned by shape only

from __future__ import annotations

import json
import re
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from aipass.backup.apps import backup as entry
from aipass.backup.apps.handlers.audit import trail
from aipass.backup.apps.handlers.drive import client as drive_client
from aipass.backup.apps.handlers.project import registry
from aipass.backup.apps.modules import all as all_module
from aipass.backup.apps.modules import display, drive_sync

# snapshot and versioned run for real against tmp_path projects: they are
# local copies, cheap at this size, and their file counts are what the summary
# reports. Only the Drive step is replaced, by a recorder: conftest's
# sealed_google_edge stands behind it.


@pytest.fixture(autouse=True)
def quiet_headers(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record the panel titles instead of drawing them."""
    # header() fires @cli's event bus; replaced where display binds it, so nothing fires.
    titles: list[str] = []
    monkeypatch.setattr(display, "header", lambda title, *args, **kwargs: titles.append(title))
    return titles


@pytest.fixture
def drive_runs(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record every project root the Drive step is run for, and upload nothing."""
    runs: list[str] = []

    def _record(project_root: str, **kwargs) -> dict:
        """Stand in for run_drive_sync: one uploaded file, no error."""
        runs.append(project_root)
        return {"success": True, "uploaded": 1, "failed": 0, "error": None}

    monkeypatch.setattr(drive_sync, "run_drive_sync", _record)
    return runs


@pytest.fixture
def tmp_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the project registry at a file under tmp_path, never the branch's real one."""
    path = tmp_path / "registry" / "project_registry.json"
    path.parent.mkdir()
    monkeypatch.setattr(registry, "REGISTRY_PATH", path)
    return path


def _project(root: Path, files: int = 2, drive_sync_on: bool | None = None) -> Path:
    """A small project with its store scaffolded and, when asked, a drive_sync setting."""
    root.mkdir(parents=True)
    for index in range(files):
        (root / f"file_{index}.txt").write_text(f"content {index}", encoding="utf-8")
    if drive_sync_on is not None:
        (root / ".backup").mkdir()
        (root / ".backup" / "config.json").write_text(json.dumps({"drive_sync": drive_sync_on}), encoding="utf-8")
    return root


def _trail_rows(operation: str) -> list[dict]:
    """The audit stream's rows for one operation, read off the file the trail wrote."""
    path = trail.log_path()
    if not path.exists():
        return []
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [row for row in rows if row.get("operation") == operation]


def _main(argv: list[str]) -> int:
    """Run the real entry point with argv."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("sys.argv", ["backup", *argv])
        return entry.main()


class TestAllObeysTheDriveSyncSetting:
    """all runs the Drive step only when the project's drive_sync is on."""

    def test_drive_sync_off_skips_the_drive_step_says_so_and_trails_drive_skipped(
        self, tmp_path: Path, drive_runs: list, capsys: pytest.CaptureFixture[str]
    ) -> None:
        project = _project(tmp_path / "proj", drive_sync_on=False)

        assert all_module.handle_command("all", [str(project)]) is True

        assert drive_runs == []
        out = capsys.readouterr().out
        assert out.count("Drive sync off for this project") == 1
        rows = _trail_rows("all_complete")
        assert len(rows) == 1 and rows[0]["drive_skipped"] is True

    def test_a_project_with_no_setting_is_off_by_default(self, tmp_path: Path, drive_runs: list) -> None:
        project = _project(tmp_path / "proj")

        assert all_module.handle_command("all", [str(project)]) is True

        assert drive_runs == []

    def test_drive_sync_on_runs_the_drive_step_once_and_trails_drive_not_skipped(
        self, tmp_path: Path, drive_runs: list, capsys: pytest.CaptureFixture[str]
    ) -> None:
        project = _project(tmp_path / "proj", drive_sync_on=True)

        assert all_module.handle_command("all", [str(project)]) is True

        assert drive_runs == [str(project)]
        assert "Drive sync off" not in capsys.readouterr().out
        rows = _trail_rows("all_complete")
        assert len(rows) == 1 and rows[0]["drive_skipped"] is False

    def test_the_bare_drive_sync_verb_runs_whatever_the_setting_says(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        project = _project(tmp_path / "proj", drive_sync_on=False)
        ran = MagicMock(name="run_drive_sync", return_value={})
        monkeypatch.setattr(drive_sync, "run_drive_sync", ran)

        assert drive_sync.handle_command("drive_sync", [str(project)]) is True

        assert ran.call_count == 1 and ran.call_args.args == (str(project),)


class TestADriveStepThatCannotFit:
    """all's Drive step is run_drive_sync itself, so a run that cannot fit ends all on the refusal sentence."""

    def test_the_refusal_is_alls_last_line_the_local_stores_stand_and_the_exit_is_non_zero(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # The real run_drive_sync runs; only its client is offline, on a full account.
        project = _project(tmp_path / "proj", drive_sync_on=True)
        client = MagicMock(name="DriveClient")
        client.authenticate.return_value = True
        client._api_call.return_value = {"storageQuota": {"usage": "5000", "limit": "5000"}}
        monkeypatch.setattr(drive_client, "DriveClient", MagicMock(return_value=client))

        code = _main(["all", str(project), "--quiet"])

        assert code == 2
        last = capsys.readouterr().out.splitlines()[-1]
        assert re.fullmatch(r"Drive has 0\.0 B free; this run needs \d+\.\d B\. Nothing uploaded\.", last), last
        assert (project / ".backup" / "snapshots" / "file_0.txt").is_file()
        assert (project / ".backup" / "versioned").is_dir()
        client.drive_service.files.assert_not_called()


class TestAllRegistered:
    """all --registered: every registry project in order, one failure never stops the next."""

    def test_every_project_runs_in_registry_order_and_a_failure_does_not_stop_the_next(
        self, tmp_path: Path, tmp_registry: Path, drive_runs: list, capsys: pytest.CaptureFixture[str]
    ) -> None:
        first = _project(tmp_path / "first", files=2, drive_sync_on=True)
        third = _project(tmp_path / "third", files=1)
        registry.register_project("first", str(first))
        registry.register_project("gone", str(tmp_path / "gone"))
        registry.register_project("third", str(third))

        code = _main(["all", "--registered", "--quiet"])

        assert code != 0
        assert drive_runs == [str(first)]
        assert (third / ".backup" / "snapshots" / "file_0.txt").is_file()
        out, err = capsys.readouterr()
        summary = out.rsplit("all --registered", 1)[1].splitlines()
        rows = [line for line in summary if line.startswith(("first", "gone", "third"))]
        assert [row.split()[0] for row in rows] == ["first", "gone", "third"]
        first_row, gone_row, third_row = rows
        assert "snapshot=3 versioned=3 drive=uploaded" in first_row  # two files plus the seed .backupignore
        assert "FAILED" in gone_row and "drive=skipped" in gone_row
        assert "snapshot=2 versioned=2 drive=skipped" in third_row
        assert all(row.rstrip().endswith("s") for row in rows)
        assert "1 of 3 projects failed: gone" in err

    def test_a_clean_run_over_every_project_exits_zero(
        self, tmp_path: Path, tmp_registry: Path, drive_runs: list, capsys: pytest.CaptureFixture[str]
    ) -> None:
        registry.register_project("one", str(_project(tmp_path / "one")))
        registry.register_project("two", str(_project(tmp_path / "two")))

        code = _main(["all", "--registered", "--quiet"])

        assert code == 0
        out, err = capsys.readouterr()
        assert err == ""
        assert out.count("drive=skipped") == 2

    def test_a_project_that_raises_is_reported_and_the_next_one_still_runs(
        self, tmp_path: Path, tmp_registry: Path, drive_runs: list, capsys: pytest.CaptureFixture[str]
    ) -> None:
        broken = _project(tmp_path / "broken")
        (broken / ".backup").mkdir()
        (broken / ".backup" / "config.json").write_text("{not json", encoding="utf-8")
        after = _project(tmp_path / "after")
        registry.register_project("broken", str(broken))
        registry.register_project("after", str(after))

        code = _main(["all", "--registered", "--quiet"])

        assert code != 0
        assert (after / ".backup" / "snapshots" / "file_0.txt").is_file()
        err = capsys.readouterr().err
        assert "broken" in err and "1 of 2 projects failed" in err

    def test_an_empty_registry_is_refused_rather_than_reported_as_a_clean_night(
        self, tmp_registry: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = _main(["all", "--registered"])

        assert code != 0
        assert "No projects registered" in capsys.readouterr().err

    @pytest.mark.parametrize("shape", ["path_after", "path_before", "name_after"])
    def test_a_project_named_beside_registered_is_refused_and_nothing_runs(
        self,
        shape: str,
        tmp_path: Path,
        tmp_registry: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        project = _project(tmp_path / "proj")
        registry.register_project("proj", str(project))
        ran = MagicMock(name="run_snapshot")
        monkeypatch.setattr(all_module, "run_snapshot", ran)
        argv = {
            "path_after": ["all", "--registered", str(project)],
            "path_before": ["all", "@proj", "--registered"],
            "name_after": ["all", "--registered", "@proj"],
        }[shape]

        code = _main(argv)

        assert code != 0
        ran.assert_not_called()
        assert "--registered runs every registered project" in capsys.readouterr().err
