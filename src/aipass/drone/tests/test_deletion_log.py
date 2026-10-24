# =================== AIPass ====================
# Name: test_deletion_log.py
# Description: Every drone delete, and every refused one, leaves a deletion record
# Version: 1.1.1
# Created: 2026-08-14
# Modified: 2026-10-23
# =============================================

"""Tests for apps/handlers/deletion_log.py, the safe_delete path that writes it, and apps/modules/door_deletion_log.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(stdlib) — json's line encoding of a record; the tests read records back through json
# seedgo: no-test-needed(covered_elsewhere) — the broker daemon's own records, pinned in tests/test_broker.py

import json
import os
import shutil
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from aipass.drone.apps.handlers import deletion_log
from aipass.drone.apps.handlers.router_handler import CallerIdentity
from aipass.drone.apps.handlers.rm_handler import safe_delete
from aipass.drone.apps.modules.door_deletion_log import record_deletion as door_record_deletion

# ``drone rm`` is the only sanctioned delete; refusals are records too (a blocked attempt leaves no other trace).

#: A mode-0 folder only stops a caller the kernel holds to permissions: not on
#: Windows, not as root. ``or`` short-circuits, so geteuid is never read on nt.
_PERMISSIONS_DO_NOT_BIND = sys.platform == "win32" or os.geteuid() == 0
_PERMISSIONS_REASON = "needs POSIX permissions that bind the caller"

#: Windows makes a symlink only with Developer Mode or elevation.
_NO_SYMLINKS = sys.platform == "win32"
_NO_SYMLINKS_REASON = "creating a symlink needs a privilege on Windows"


@pytest.fixture()
def project(tmp_path, monkeypatch):
    """A fake project root the deletion log will resolve into.

    The log path derives from the project root, so chdir into a tmp project redirects it.
    """
    (tmp_path / "AIPASS_REGISTRY.json").write_text("{}", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("AIPASS_BRANCH_NAME", raising=False)
    monkeypatch.delenv("AIPASS_HOME", raising=False)
    return tmp_path


def read_records(project_root: Path) -> list[dict]:
    """Return every record in the project's deletion log, oldest first."""
    log = deletion_log.deletion_log_path()
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]


class TestDeletionIsRecorded:
    def test_successful_delete_writes_a_record(self, project):
        target = project / "build"
        target.mkdir()
        (target / "a.txt").write_text("x", encoding="utf-8")

        safe_delete([str(target)])

        records = read_records(project)
        assert len(records) == 1
        assert records[0]["outcome"] == "deleted"
        assert records[0]["path"] == str(target.resolve())

    def test_refusal_writes_a_record(self, project, monkeypatch):
        """A guard refusal is the only trace that attempt leaves — record it."""
        protected = project / "src" / "aipass" / "api"
        protected.mkdir(parents=True)
        (protected / ".trinity").mkdir()
        mine = project / "src" / "aipass" / "drone"
        mine.mkdir(parents=True)
        (mine / ".trinity").mkdir()
        monkeypatch.chdir(mine)

        safe_delete([str(protected)])

        records = read_records(project)
        assert len(records) == 1
        assert records[0]["outcome"] == "refused"
        assert "sibling branch" in records[0]["reason"]

    def test_containment_refusal_writes_a_record(self, project):
        outside = Path.home() / "definitely-not-deletable-aipass-test"
        safe_delete([str(outside)])

        records = read_records(project)
        assert len(records) == 1
        # Home does not exist as a target: the attempt is still recorded.
        assert records[0]["outcome"] in ("refused", "not_found")

    def test_nonexistent_path_is_still_an_attempt(self, project):
        safe_delete([str(project / "never-existed")])

        records = read_records(project)
        assert len(records) == 1
        assert records[0]["outcome"] == "not_found"

    def test_each_path_gets_its_own_record(self, project):
        one = project / "one.txt"
        two = project / "two.txt"
        one.write_text("1", encoding="utf-8")
        two.write_text("2", encoding="utf-8")

        safe_delete([str(one), str(two)])

        records = read_records(project)
        assert len(records) == 2
        assert {r["path"] for r in records} == {str(one.resolve()), str(two.resolve())}


class TestRecordContents:
    REQUIRED = (
        "timestamp",
        "lane",
        "outcome",
        "caller",
        "cwd",
        "requested",
        "path",
        "kind",
        "reason",
    )

    def test_every_required_field_present(self, project):
        target = project / "gone.txt"
        target.write_text("bye", encoding="utf-8")

        safe_delete([str(target)])

        record = read_records(project)[0]
        # Floor before the loop: an emptied REQUIRED would make the loop a silent pass.
        assert len(self.REQUIRED) == 9
        for field in self.REQUIRED:
            assert field in record, f"record is missing {field!r}"

    def test_file_record_carries_its_size(self, project):
        target = project / "sized.txt"
        target.write_text("0123456789", encoding="utf-8")

        safe_delete([str(target)])

        record = read_records(project)[0]
        assert record["kind"] == "file"
        assert record["size_bytes"] == 10

    def test_directory_record_counts_entries_and_bytes(self, project):
        target = project / "tree"
        (target / "nested").mkdir(parents=True)
        (target / "a.txt").write_text("aa", encoding="utf-8")
        (target / "nested" / "b.txt").write_text("bbb", encoding="utf-8")

        safe_delete([str(target)])

        record = read_records(project)[0]
        assert record["kind"] == "directory"
        assert record["entry_count"] == 3  # a.txt, nested/, nested/b.txt
        assert record["size_bytes"] == 5

    def test_measurement_happens_before_the_delete(self, project):
        """Size of a deleted tree is unknowable afterwards — measure first."""
        target = project / "tree"
        target.mkdir()
        (target / "a.txt").write_text("hello", encoding="utf-8")

        safe_delete([str(target)])

        assert not target.exists()
        record = read_records(project)[0]
        assert record["size_bytes"] == 5

    def test_symlink_is_its_own_kind_and_is_not_followed(self, project):
        real = project / "real.txt"
        real.write_text("x" * 100, encoding="utf-8")
        link = project / "link.txt"
        link.symlink_to(real)

        safe_delete([str(link)])

        record = read_records(project)[0]
        assert record["kind"] == "symlink"
        assert real.exists(), "measuring must not follow the link"

    @pytest.mark.skipif(_NO_SYMLINKS, reason=_NO_SYMLINKS_REASON)
    def test_a_symlink_record_names_the_link_and_its_target(self, project):
        real = project.resolve() / "real.txt"
        real.write_text("x", encoding="utf-8")
        link = project.resolve() / "link.txt"
        link.symlink_to(real)

        safe_delete([str(link)])

        record = read_records(project)[0]
        assert (record["path"], record.get("target")) == (str(link), str(real))

    def test_a_plain_delete_writes_no_target_key(self, project):
        target = project / "plain.txt"
        target.write_text("x", encoding="utf-8")

        safe_delete([str(target)])

        assert "target" not in read_records(project)[0]

    def test_requested_keeps_what_the_caller_typed(self, project):
        target = project / "rel.txt"
        target.write_text("x", encoding="utf-8")

        safe_delete(["rel.txt"])

        record = read_records(project)[0]
        assert record["requested"] == "rel.txt"
        assert record["path"] == str(target.resolve())


class TestCallerIdentity:
    def test_unknown_when_nothing_resolves(self, project):
        """No passport, no registry name, no assignment → UNKNOWN.

        A plausible wrong identity names a citizen who did not do it; an honest gap does not.
        """
        target = project / "x.txt"
        target.write_text("x", encoding="utf-8")

        with patch(
            "aipass.drone.apps.handlers.deletion_log.resolve_caller_identity_signal",
            return_value=CallerIdentity(None, None),
        ):
            safe_delete([str(target)])

        assert read_records(project)[0]["caller"] == "unknown"

    def test_identity_comes_from_the_shared_resolver(self, project):
        """Not a fifth resolver — the same one routing and git attribution use."""
        target = project / "x.txt"
        target.write_text("x", encoding="utf-8")

        with patch(
            "aipass.drone.apps.handlers.deletion_log.resolve_caller_identity_signal",
            return_value=CallerIdentity("devpulse", "passport"),
        ) as resolver:
            safe_delete([str(target)])

        assert resolver.called
        assert read_records(project)[0]["caller"] == "devpulse"

    def test_a_project_name_is_refused_as_an_identity(self, project):
        """The record said `aipass` for a deletion @devpulse made.

        The resolver's last resort, the PROJECT, answers WHERE, not WHO: it becomes `unknown`; cwd keeps the location.
        """
        target = project / "x.txt"
        target.write_text("x", encoding="utf-8")

        with patch(
            "aipass.drone.apps.handlers.deletion_log.resolve_caller_identity_signal",
            return_value=CallerIdentity("aipass", "project"),
        ):
            safe_delete([str(target)])

        record = read_records(project)[0]
        assert record["caller"] == "unknown"
        assert record["cwd"], "the location must survive — only the identity claim is refused"

    def test_an_assigned_identity_is_still_honoured(self, project):
        """The fence refuses `project`, not every answer."""
        target = project / "x.txt"
        target.write_text("x", encoding="utf-8")

        with patch(
            "aipass.drone.apps.handlers.deletion_log.resolve_caller_identity_signal",
            return_value=CallerIdentity("commons", "assigned"),
        ):
            safe_delete([str(target)])

        assert read_records(project)[0]["caller"] == "commons"

    def test_passport_walkup_beats_the_directory_name(self, project, monkeypatch):
        """The directory is deliberately NOT named after the branch.

        A dir named 'drone' would let path-shape matching pass; only a real passport read passes here.
        """
        branch = project / "src" / "aipass" / "some-checkout"
        branch.mkdir(parents=True)
        (branch / ".trinity").mkdir()
        (branch / ".trinity" / "passport.json").write_text(
            json.dumps({"branch_info": {"branch_name": "drone"}}), encoding="utf-8"
        )
        monkeypatch.chdir(branch)

        target = branch / "scratch.txt"
        target.write_text("x", encoding="utf-8")
        safe_delete([str(target)])

        assert read_records(project)[0]["caller"] == "drone"


class TestSeverity:
    def test_record_line_is_info(self, project):
        target = project / "x.txt"
        target.write_text("x", encoding="utf-8")

        with patch("aipass.drone.apps.handlers.deletion_log.logger") as log:
            safe_delete([str(target)])

        assert log.info.called
        assert not log.warning.called
        assert not log.error.called

    def test_refusal_record_line_is_also_info(self, project):
        """The refusal's own WARNING already exists; the RECORD is not an alarm."""
        outside = Path("/etc/passwd")

        with patch("aipass.drone.apps.handlers.deletion_log.logger") as log:
            safe_delete([str(outside)])

        assert log.info.called
        assert not log.error.called


class TestBounded:
    def test_log_rotates_at_the_cap(self, project, monkeypatch):
        monkeypatch.setattr(deletion_log, "_MAX_BYTES", 400)
        for i in range(40):
            target = project / f"f{i}.txt"
            target.write_text("x", encoding="utf-8")
            safe_delete([str(target)])

        live = deletion_log.deletion_log_path()
        assert live.stat().st_size <= 400 + 1024

    def test_rotation_keeps_a_bounded_number_of_files(self, project, monkeypatch):
        """Mutant killed: _rotate_if_needed keeping one generation more than it promises."""
        monkeypatch.setattr(deletion_log, "_MAX_BYTES", 400)
        for i in range(60):
            target = project / f"f{i}.txt"
            target.write_text("x", encoding="utf-8")
            safe_delete([str(target)])

        siblings = deletion_log.deletion_log_path().parent.glob("deletions.jsonl*")
        assert sorted(p.name for p in siblings) == ["deletions.jsonl", "deletions.jsonl.1"]

    def test_huge_tree_measurement_is_capped(self, project, monkeypatch):
        monkeypatch.setattr(deletion_log, "_MEASURE_ENTRY_CAP", 5)
        target = project / "many"
        target.mkdir()
        for i in range(20):
            (target / f"f{i}.txt").write_text("x", encoding="utf-8")

        safe_delete([str(target)])

        record = read_records(project)[0]
        assert record["entry_count"] == 5
        assert record["measured"] == "capped"


# These clear the suite-wide AIPASS_DELETION_LOG isolation on purpose: only they assert the real derivation.


class TestLogLocation:
    def test_lands_under_the_projects_ai_central(self, project, monkeypatch):
        monkeypatch.delenv("AIPASS_DELETION_LOG", raising=False)
        assert deletion_log.deletion_log_path() == project / ".ai_central" / "deletions.jsonl"

    def test_one_log_per_project_not_per_branch(self, project, monkeypatch):
        """rm runs from whichever branch deletes; a split record is not a record."""
        monkeypatch.delenv("AIPASS_DELETION_LOG", raising=False)
        branch = project / "src" / "aipass" / "drone"
        (branch / ".trinity").mkdir(parents=True)
        monkeypatch.chdir(branch)
        assert deletion_log.deletion_log_path() == project / ".ai_central" / "deletions.jsonl"

    def test_falls_back_to_temp_outside_any_project(self, tmp_path, monkeypatch):
        monkeypatch.delenv("AIPASS_DELETION_LOG", raising=False)
        monkeypatch.delenv("AIPASS_HOME", raising=False)
        monkeypatch.chdir(tmp_path)
        with patch.object(deletion_log, "find_project_root", return_value=None):
            assert deletion_log.deletion_log_path().name == "deletions.jsonl"

    def test_env_override_wins(self, project, monkeypatch, tmp_path):
        elsewhere = tmp_path / "somewhere" / "d.jsonl"
        monkeypatch.setenv("AIPASS_DELETION_LOG", str(elsewhere))
        assert deletion_log.deletion_log_path() == elsewhere

    def test_a_named_project_root_beats_the_cwd_walk(self, project, monkeypatch, tmp_path):
        """A lane that KNOWS its project files the record there, not where it stands.

        The broker is handed ``repo_root`` and can serve a repo it is not standing in; a cwd resolve
        files the record into whichever project the process happens to sit in.
        """
        monkeypatch.delenv("AIPASS_DELETION_LOG", raising=False)
        served = tmp_path / "another_repo"
        served.mkdir()
        assert deletion_log.deletion_log_path(served) == served / ".ai_central" / "deletions.jsonl"
        assert deletion_log.deletion_log_path() == project / ".ai_central" / "deletions.jsonl"

    def test_env_override_outranks_a_named_project_root(self, project, monkeypatch, tmp_path):
        """Two overrides, and the operator's is the outer one.

        Else a lane passing its own root defeats the seam tests and containers relocate the store with.
        """
        elsewhere = tmp_path / "somewhere" / "d.jsonl"
        served = tmp_path / "another_repo"
        served.mkdir()
        monkeypatch.setenv("AIPASS_DELETION_LOG", str(elsewhere))
        assert deletion_log.deletion_log_path(served) == elsewhere

    def test_record_deletion_writes_to_the_named_project(self, project, monkeypatch, tmp_path):
        """The whole point, end to end: the record follows the deletion's repo."""
        monkeypatch.delenv("AIPASS_DELETION_LOG", raising=False)
        served = tmp_path / "another_repo"
        served.mkdir()

        deletion_log.record_deletion(
            lane=deletion_log.LANE_BROKER,
            outcome=deletion_log.OUTCOME_DELETED,
            requested="deleteme.txt",
            resolved=served / "deleteme.txt",
            reason="Deleted",
            caller="testbranch",
            project_root=served,
        )

        assert (served / ".ai_central" / "deletions.jsonl").exists()
        assert not (project / ".ai_central" / "deletions.jsonl").exists()

    def test_override_cannot_silence_the_prax_line(self, project, monkeypatch):
        """Relocating the store must not become a way to erase the event.

        The unwritable target is a FILE where the parent dir must be, so ``_append_record``'s mkdir
        raises inside the tmp project; never reach outside the tree under test for an unwritable path.
        """
        blocked = project / "not_a_directory"
        blocked.write_text("a file where a directory would have to be", encoding="utf-8")
        monkeypatch.setenv("AIPASS_DELETION_LOG", str(blocked / "d.jsonl"))
        target = project / "x.txt"
        target.write_text("x", encoding="utf-8")

        with patch("aipass.drone.apps.handlers.deletion_log.logger") as log:
            safe_delete([str(target)])

        assert log.info.called


class TestAnotherBranchRecordsThroughTheDoor:
    ROW = {
        "lane": "spawn_retire",
        "outcome": "retired",
        "caller": "spawn",
        "requested": "/projects/drivetest",
        "resolved": "/projects/drivetest",
        "target": "/backup/retired_projects/drivetest_1",
        "reason": "Retired with its registry",
    }
    MEASURED = {"kind": "directory", "size_bytes": 1100, "entry_count": 12, "measured": "exact"}

    def test_a_door_row_reads_back_beside_a_drone_rm_row_with_its_fields(self, project):
        gone = project / "gone.txt"
        gone.write_text("x", encoding="utf-8")
        safe_delete([str(gone)])

        door_record_deletion(**self.ROW, measurement=self.MEASURED)

        rm_row, door_row = read_records(project)
        assert door_record_deletion is deletion_log.record_foreign_deletion
        assert set(TestRecordContents.REQUIRED) <= set(rm_row) & set(door_row)
        assert {k: door_row[k] for k in ("lane", "outcome", "caller", "target", "path", "reason")} == {
            "lane": "spawn_retire",
            "outcome": "retired",
            "caller": "spawn",
            "target": "/backup/retired_projects/drivetest_1",
            "path": "/projects/drivetest",
            "reason": "Retired with its registry",
        }
        assert (door_row["size_bytes"], door_row["entry_count"]) == (1100, 12)

    @pytest.mark.parametrize("field", ["lane", "outcome", "caller", "resolved", "target"])
    @pytest.mark.parametrize("empty", ["", "  ", None])
    def test_an_empty_required_field_is_refused_and_writes_no_half_row(self, project, field, empty):
        with pytest.raises(ValueError, match=field):
            door_record_deletion(**{**self.ROW, field: empty})

        assert read_records(project) == []

    def test_a_measurement_not_shaped_like_drones_is_refused(self, project):
        with pytest.raises(ValueError, match="measurement"):
            deletion_log.record_foreign_deletion(**self.ROW, measurement={"size": 1100, "entry_count": 12})

        assert read_records(project) == []


class TestRecordFailureIsContained:
    def test_delete_still_happens_when_the_store_is_unwritable(self, project):
        target = project / "x.txt"
        target.write_text("x", encoding="utf-8")

        with patch.object(deletion_log, "_append_record", side_effect=OSError("disk full")):
            results = safe_delete([str(target)])

        assert results[0][1] is True
        assert not target.exists()

    def test_store_failure_is_reported_not_swallowed(self, project):
        target = project / "x.txt"
        target.write_text("x", encoding="utf-8")

        with patch.object(deletion_log, "_append_record", side_effect=OSError("disk full")):
            with patch("aipass.drone.apps.handlers.deletion_log.logger") as log:
                safe_delete([str(target)])

        assert log.error.called, "a lost deletion record must be loud"

    @pytest.mark.deletable_cwd
    def test_deleting_the_current_directory_still_reports_success(self, project, monkeypatch):
        """The delete worked. Losing cwd must not turn it into a failure.

        The rmtree leaves no cwd (``Path.cwd()`` raises ENOENT); the record absorbs that, not the result.
        """
        doomed = project / "scratch"
        doomed.mkdir()
        (doomed / "f.txt").write_text("x", encoding="utf-8")
        monkeypatch.chdir(doomed)

        results = safe_delete([str(doomed)])

        assert results[0][1] is True, "the delete succeeded; the result must say so"
        assert not doomed.exists()

    @pytest.mark.deletable_cwd
    def test_deleting_the_current_directory_does_not_raise(self, project, monkeypatch):
        """safe_delete returns per-path results. It must not become a crash.

        A record raising on the success path, then again in the except handler, must not escape.
        """
        doomed = project / "scratch"
        doomed.mkdir()
        monkeypatch.chdir(doomed)

        results = safe_delete([str(doomed)])

        # Mutant killed: the success-path record raising, caught and reported as a failed delete.
        ((path, ok, message),) = results
        assert path == str(doomed)
        assert ok is True, message
        assert message.startswith("Deleted: ")

    @pytest.mark.deletable_cwd
    def test_record_deletion_does_not_raise_when_cwd_is_gone(self, project, monkeypatch):
        """The docstring says 'Never raises'. Two lines read cwd outside its try."""
        doomed = project / "scratch"
        doomed.mkdir()
        monkeypatch.chdir(doomed)
        shutil.rmtree(doomed)

        record = deletion_log.record_deletion(
            lane=deletion_log.LANE_RM,
            outcome=deletion_log.OUTCOME_DELETED,
            requested=str(doomed),
            resolved=doomed,
            reason="Deleted",
        )

        assert record["outcome"] == deletion_log.OUTCOME_DELETED

    @pytest.mark.deletable_cwd
    def test_a_successful_delete_is_never_logged_as_a_failure(self, project, monkeypatch):
        """The log said 'deleted' and 'delete failed' for one path, one second.

        Whoever reads the log next must not have to guess which line is true.
        """
        doomed = project / "scratch"
        doomed.mkdir()
        monkeypatch.chdir(doomed)

        with patch("aipass.drone.apps.handlers.rm_handler.logger") as log:
            safe_delete([str(doomed)])

        failures = [c for c in log.error.call_args_list if "delete failed" in str(c)]
        assert failures == [], f"a delete that succeeded was reported as failed: {failures}"
        # Mutant killed: the success path writing its ledger record as outcome "failed".
        assert [r["outcome"] for r in read_records(project)] == [deletion_log.OUTCOME_DELETED]

    @pytest.mark.deletable_cwd
    def test_the_record_still_lands_when_the_cwd_is_deleted(self, project, monkeypatch):
        """Losing cwd must not cost the durable half of the record.

        The store path walks up from cwd; with cwd gone the env override or tempdir home must still answer.
        """
        # Via deletion_log._temp_dir, so tempfile stays untouched for every other reader in the process.
        home = project / "tmphome"
        home.mkdir()
        monkeypatch.setattr(deletion_log, "_temp_dir", lambda: home)
        monkeypatch.delenv("AIPASS_DELETION_LOG", raising=False)
        doomed = project / "scratch"
        doomed.mkdir()
        monkeypatch.chdir(doomed)

        safe_delete([str(doomed)])

        # No cwd and no AIPASS_HOME: the promised tempdir home is the only place left to answer.
        store = home / "deletions.jsonl"
        assert store.exists(), "the deletion record was lost with the directory"
        record = json.loads(store.read_text(encoding="utf-8").strip().splitlines()[-1])
        assert record["outcome"] == deletion_log.OUTCOME_DELETED
        assert record["cwd"] == deletion_log.NO_CURRENT_DIRECTORY


class TestTheRecordSurvivesAnAbsentCwdOnEveryOS:
    """What the deletable-cwd tests above claim, built the portable way.

    Windows refuses deleting the cwd (WINDOWS_CWD_REASON in conftest), so here router_handler's
    ``_working_directory`` seam beneath ``caller_cwd`` raises the real ENOENT instead. Weaker in one
    way: it cannot catch an ``os.getcwd`` read inside C, as ``Path.resolve()`` does.
    """

    @pytest.fixture()
    def no_cwd(self, monkeypatch):
        def gone():
            raise FileNotFoundError(2, "No such file or directory")

        monkeypatch.setattr("aipass.drone.apps.handlers.router_handler._working_directory", gone)
        yield

    def test_record_deletion_does_not_raise(self, no_cwd, tmp_path, monkeypatch):
        """The docstring says "never raises". Two lines read cwd outside its try."""
        monkeypatch.delenv("AIPASS_HOME", raising=False)

        record = deletion_log.record_deletion(
            lane=deletion_log.LANE_RM,
            outcome=deletion_log.OUTCOME_DELETED,
            requested=str(tmp_path / "scratch"),
            resolved=tmp_path / "scratch",
            reason="Deleted",
        )

        assert record["outcome"] == deletion_log.OUTCOME_DELETED
        assert record["cwd"] == deletion_log.NO_CURRENT_DIRECTORY

    def test_the_record_still_lands_somewhere_durable(self, no_cwd, tmp_path, monkeypatch):
        """Losing the cwd must not cost the durable half of the record."""
        home = tmp_path / "tmphome"
        home.mkdir()
        # Via deletion_log._temp_dir, never by replacing tempfile.tempdir for the whole process.
        monkeypatch.setattr(deletion_log, "_temp_dir", lambda: home)
        monkeypatch.delenv("AIPASS_DELETION_LOG", raising=False)
        monkeypatch.delenv("AIPASS_HOME", raising=False)

        deletion_log.record_deletion(
            lane=deletion_log.LANE_RM,
            outcome=deletion_log.OUTCOME_DELETED,
            requested=str(tmp_path / "scratch"),
            resolved=tmp_path / "scratch",
            reason="Deleted",
        )

        store = home / "deletions.jsonl"
        assert store.exists(), "the deletion record had nowhere left to land"
        record = json.loads(store.read_text(encoding="utf-8").strip().splitlines()[-1])
        assert record["outcome"] == deletion_log.OUTCOME_DELETED
        assert record["cwd"] == deletion_log.NO_CURRENT_DIRECTORY


class TestAnUnreadableSubtreeIsNotMeasuredAsExact:
    @pytest.mark.skipif(_PERMISSIONS_DO_NOT_BIND, reason=_PERMISSIONS_REASON)
    def test_a_folder_the_walk_cannot_list_marks_the_measure_partial(self, tmp_path):
        # Through measure(), not safe_delete: rm refuses an unreadable folder before it measures.
        target = tmp_path / "tree"
        (target / "readable").mkdir(parents=True)
        (target / "readable" / "seen.txt").write_text("x", encoding="utf-8")
        locked = target / "locked"
        locked.mkdir()
        (locked / "unseen.txt").write_text("xxxx", encoding="utf-8")
        locked.chmod(0)
        try:
            result = deletion_log.measure(target)
        finally:
            locked.chmod(0o700)
        assert result["measured"] == "partial"
