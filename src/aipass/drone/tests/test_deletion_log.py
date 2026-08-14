"""Tests for the deletion record — every drone delete leaves a trace.

Patrick's ruling (via DPLAN night round): "if something deletes, there should
be a record of it." ``drone rm`` is the fleet's only sanctioned delete path —
raw recursive rm is gate-blocked — so the record is written where the deleting
happens, not where the CLI is parsed.

Refusals are records too. An attempted delete the guard blocked is exactly the
kind of event worth finding later, and it is the only trace that event leaves.
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from aipass.drone.apps.handlers import deletion_log
from aipass.drone.apps.handlers.rm_handler import safe_delete


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def project(tmp_path, monkeypatch):
    """A fake project root the deletion log will resolve into.

    The log path is derived from the project root the same way the broker's
    audit path is, so chdir-ing into a tmp project is all a test needs to
    redirect it — no env var, no injected path.
    """
    (tmp_path / "AIPASS_REGISTRY.json").write_text("{}")
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


# ---------------------------------------------------------------------------
# The record exists at all
# ---------------------------------------------------------------------------


class TestDeletionIsRecorded:
    def test_successful_delete_writes_a_record(self, project):
        target = project / "build"
        target.mkdir()
        (target / "a.txt").write_text("x")

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
        one.write_text("1")
        two.write_text("2")

        safe_delete([str(one), str(two)])

        records = read_records(project)
        assert len(records) == 2
        assert {r["path"] for r in records} == {str(one.resolve()), str(two.resolve())}


# ---------------------------------------------------------------------------
# What the record has to contain
# ---------------------------------------------------------------------------


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
        target.write_text("bye")

        safe_delete([str(target)])

        record = read_records(project)[0]
        for field in self.REQUIRED:
            assert field in record, f"record is missing {field!r}"

    def test_file_record_carries_its_size(self, project):
        target = project / "sized.txt"
        target.write_text("0123456789")

        safe_delete([str(target)])

        record = read_records(project)[0]
        assert record["kind"] == "file"
        assert record["size_bytes"] == 10

    def test_directory_record_counts_entries_and_bytes(self, project):
        target = project / "tree"
        (target / "nested").mkdir(parents=True)
        (target / "a.txt").write_text("aa")
        (target / "nested" / "b.txt").write_text("bbb")

        safe_delete([str(target)])

        record = read_records(project)[0]
        assert record["kind"] == "directory"
        assert record["entry_count"] == 3  # a.txt, nested/, nested/b.txt
        assert record["size_bytes"] == 5

    def test_measurement_happens_before_the_delete(self, project):
        """Size of a deleted tree is unknowable afterwards — measure first."""
        target = project / "tree"
        target.mkdir()
        (target / "a.txt").write_text("hello")

        safe_delete([str(target)])

        assert not target.exists()
        record = read_records(project)[0]
        assert record["size_bytes"] == 5

    def test_symlink_is_its_own_kind_and_is_not_followed(self, project):
        real = project / "real.txt"
        real.write_text("x" * 100)
        link = project / "link.txt"
        link.symlink_to(real)

        safe_delete([str(link)])

        record = read_records(project)[0]
        assert record["kind"] == "symlink"
        assert real.exists(), "measuring must not follow the link"

    def test_requested_keeps_what_the_caller_typed(self, project):
        target = project / "rel.txt"
        target.write_text("x")

        safe_delete(["rel.txt"])

        record = read_records(project)[0]
        assert record["requested"] == "rel.txt"
        assert record["path"] == str(target.resolve())


# ---------------------------------------------------------------------------
# Caller identity — resolved, never guessed
# ---------------------------------------------------------------------------


class TestCallerIdentity:
    def test_unknown_when_nothing_resolves(self, project):
        """No passport, no registry name, no assignment → UNKNOWN.

        A wrong-but-plausible identity on a deletion record is worse than an
        honest gap: it would name a citizen who did not do it.
        """
        target = project / "x.txt"
        target.write_text("x")

        with patch(
            "aipass.drone.apps.handlers.deletion_log.resolve_caller_identity",
            return_value=None,
        ):
            safe_delete([str(target)])

        assert read_records(project)[0]["caller"] == "unknown"

    def test_identity_comes_from_the_shared_resolver(self, project):
        """Not a fifth resolver — the same one routing and git attribution use."""
        target = project / "x.txt"
        target.write_text("x")

        with patch(
            "aipass.drone.apps.handlers.deletion_log.resolve_caller_identity",
            return_value="devpulse",
        ) as resolver:
            safe_delete([str(target)])

        assert resolver.called
        assert read_records(project)[0]["caller"] == "devpulse"

    def test_passport_walkup_beats_the_directory_name(self, project, monkeypatch):
        """The directory is deliberately NOT named after the branch.

        A first draft of this test put the passport inside a dir called
        'drone' — which path-shape matching answers identically, so it proved
        nothing. The names differ here so only a real passport read can pass.
        """
        branch = project / "src" / "aipass" / "some-checkout"
        branch.mkdir(parents=True)
        (branch / ".trinity").mkdir()
        (branch / ".trinity" / "passport.json").write_text(json.dumps({"branch_info": {"branch_name": "drone"}}))
        monkeypatch.chdir(branch)

        target = branch / "scratch.txt"
        target.write_text("x")
        safe_delete([str(target)])

        assert read_records(project)[0]["caller"] == "drone"


# ---------------------------------------------------------------------------
# Severity — a sanctioned delete is not an alarm (compass #273)
# ---------------------------------------------------------------------------


class TestSeverity:
    def test_record_line_is_info(self, project):
        target = project / "x.txt"
        target.write_text("x")

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


# ---------------------------------------------------------------------------
# Bounded — a delete log must not become the runaway log
# ---------------------------------------------------------------------------


class TestBounded:
    def test_log_rotates_at_the_cap(self, project, monkeypatch):
        monkeypatch.setattr(deletion_log, "_MAX_BYTES", 400)
        for i in range(40):
            target = project / f"f{i}.txt"
            target.write_text("x")
            safe_delete([str(target)])

        live = deletion_log.deletion_log_path()
        assert live.stat().st_size <= 400 + 1024

    def test_rotation_keeps_a_bounded_number_of_files(self, project, monkeypatch):
        monkeypatch.setattr(deletion_log, "_MAX_BYTES", 400)
        for i in range(60):
            target = project / f"f{i}.txt"
            target.write_text("x")
            safe_delete([str(target)])

        siblings = list(deletion_log.deletion_log_path().parent.glob("deletions.jsonl*"))
        assert len(siblings) <= deletion_log._ROTATIONS + 1

    def test_huge_tree_measurement_is_capped(self, project, monkeypatch):
        monkeypatch.setattr(deletion_log, "_MEASURE_ENTRY_CAP", 5)
        target = project / "many"
        target.mkdir()
        for i in range(20):
            (target / f"f{i}.txt").write_text("x")

        safe_delete([str(target)])

        record = read_records(project)[0]
        assert record["entry_count"] == 5
        assert record["measured"] == "capped"


# ---------------------------------------------------------------------------
# Where the log lives
#
# These clear the suite-wide AIPASS_DELETION_LOG isolation on purpose — they
# are the only tests that assert the real derivation, and the autouse fixture
# that keeps every other test off the live log would hide it.
# ---------------------------------------------------------------------------


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
        with patch.object(deletion_log, "_find_project_root", return_value=None):
            assert deletion_log.deletion_log_path().name == "deletions.jsonl"

    def test_env_override_wins(self, project, monkeypatch, tmp_path):
        elsewhere = tmp_path / "somewhere" / "d.jsonl"
        monkeypatch.setenv("AIPASS_DELETION_LOG", str(elsewhere))
        assert deletion_log.deletion_log_path() == elsewhere

    def test_override_cannot_silence_the_prax_line(self, project, monkeypatch):
        """Relocating the store must not become a way to erase the event."""
        monkeypatch.setenv("AIPASS_DELETION_LOG", "/proc/nonexistent/d.jsonl")
        target = project / "x.txt"
        target.write_text("x")

        with patch("aipass.drone.apps.handlers.deletion_log.logger") as log:
            safe_delete([str(target)])

        assert log.info.called


# ---------------------------------------------------------------------------
# The record must not become a new way for rm to fail
# ---------------------------------------------------------------------------


class TestRecordFailureIsContained:
    def test_delete_still_happens_when_the_store_is_unwritable(self, project):
        target = project / "x.txt"
        target.write_text("x")

        with patch.object(deletion_log, "_append_record", side_effect=OSError("disk full")):
            results = safe_delete([str(target)])

        assert results[0][1] is True
        assert not target.exists()

    def test_store_failure_is_reported_not_swallowed(self, project):
        target = project / "x.txt"
        target.write_text("x")

        with patch.object(deletion_log, "_append_record", side_effect=OSError("disk full")):
            with patch("aipass.drone.apps.handlers.deletion_log.logger") as log:
                safe_delete([str(target)])

        assert log.error.called, "a lost deletion record must be loud"
