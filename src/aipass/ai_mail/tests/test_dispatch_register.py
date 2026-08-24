"""The dispatch register — what was promised, and what a reader can tell from it.

FPLAN-0452 P0.

The register's whole value is that crash detection costs nothing: an entry past
its expected_by with no completion record is a FACT ABOUT A FILE, visible to
anyone who looks, with no process running to discover it. These tests pin the
properties that fact depends on — append-only, never production, honest about
what it cannot parse.
"""

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from aipass.ai_mail.apps.handlers.dispatch import register


@pytest.fixture
def repo(tmp_path):
    """A tmp tree carrying the repo marker, so re-rooting can be honoured."""
    (tmp_path / "AIPASS_REGISTRY.json").write_text("{}", encoding="utf-8")
    return tmp_path


def _lines(repo_root):
    return (repo_root / ".aipass" / register.REGISTER_FILENAME).read_text(encoding="utf-8").strip().splitlines()


class TestWrittenBeforeAnythingSpawns:
    """An entry records a PROMISE, so it must survive a spawn that never happened."""

    def test_open_dispatch_records_every_field_a_reader_needs(self, repo):
        import json

        dispatch_id = register.open_dispatch("@devpulse", "@ai_mail", "Build the register", 7200, repo_root=repo)

        assert dispatch_id, "open_dispatch must return the id it minted"
        record = json.loads(_lines(repo)[0])
        assert record["dispatch_id"] == dispatch_id
        assert record["sender"] == "@devpulse"
        assert record["target"] == "@ai_mail"
        assert record["subject"] == "Build the register"
        assert record["status"] == register.STATUS_OUTSTANDING
        assert record["expected_by"] > record["ts"], "expected_by must be in the future of ts"

    def test_expected_by_comes_from_the_caller_not_a_number_invented_here(self, repo):
        """The spec forbids an invented timeout — expected_seconds is the contract.

        This is what makes "past expected_by" mean the monitor DIED rather than
        "the agent is taking a while": the caller passes dispatch_monitor's own
        HARD_TIMEOUT, which a live monitor can never legitimately overrun.
        """
        import json

        register.open_dispatch("@a", "@b", "s", 60, repo_root=repo)
        record = json.loads(_lines(repo)[0])

        span = datetime.fromisoformat(record["expected_by"]) - datetime.fromisoformat(record["ts"])
        assert abs(span.total_seconds() - 60) < 2

    def test_a_bare_wake_records_an_empty_subject_rather_than_inventing_one(self, repo):
        import json

        register.open_dispatch("@a", "@b", "", 7200, repo_root=repo)

        assert json.loads(_lines(repo)[0])["subject"] == ""


class TestAppendOnly:
    """Closing rewrites nothing. The promise stays visible after it is answered."""

    def test_close_appends_a_second_record_and_leaves_the_first_intact(self, repo):
        import json

        dispatch_id = register.open_dispatch("@devpulse", "@ai_mail", "s", 7200, repo_root=repo)
        assert dispatch_id
        register.close_dispatch(dispatch_id, "completed", "/reports/x.json", repo_root=repo)

        lines = _lines(repo)
        assert len(lines) == 2, "close must APPEND, never rewrite"
        assert json.loads(lines[0])["status"] == register.STATUS_OUTSTANDING, "the promise must survive its answer"
        closing = json.loads(lines[1])
        assert closing["dispatch_id"] == dispatch_id
        assert closing["status"] == "completed"
        assert closing["report_path"] == "/reports/x.json"

    def test_a_closed_dispatch_stops_being_outstanding(self, repo):
        dispatch_id = register.open_dispatch("@a", "@b", "s", 7200, repo_root=repo)
        assert dispatch_id
        assert len(register.outstanding(repo_root=repo)) == 1

        register.close_dispatch(dispatch_id, "completed", repo_root=repo)

        assert register.outstanding(repo_root=repo) == []

    def test_one_dispatch_closing_leaves_the_others_outstanding(self, repo):
        first = register.open_dispatch("@a", "@b", "one", 7200, repo_root=repo)
        assert first
        register.open_dispatch("@a", "@c", "two", 7200, repo_root=repo)

        register.close_dispatch(first, "completed", repo_root=repo)

        still_open = register.outstanding(repo_root=repo)
        assert [e["subject"] for e in still_open] == ["two"]


class TestCrashCoverageWithoutPolling:
    """Overdue is a fact about a file. Nothing runs to produce it."""

    def test_an_entry_past_expected_by_reads_as_overdue(self, repo):
        register.open_dispatch("@devpulse", "@ai_mail", "crashed", 60, repo_root=repo)

        later = datetime.now().astimezone() + timedelta(seconds=120)
        entry = register.outstanding(repo_root=repo, now=later)[0]

        assert entry["overdue"] is True

    def test_an_entry_inside_its_window_is_not_overdue(self, repo):
        register.open_dispatch("@devpulse", "@ai_mail", "running", 7200, repo_root=repo)

        entry = register.outstanding(repo_root=repo)[0]

        assert entry["overdue"] is False

    def test_an_unparseable_expected_by_is_not_evidence_of_a_crash(self, repo, caplog):
        """A timestamp we cannot read is not a crash — it is a timestamp we cannot read."""
        register.open_dispatch("@a", "@b", "s", 7200, repo_root=repo)
        path = repo / ".aipass" / register.REGISTER_FILENAME
        path.write_text(
            path.read_text(encoding="utf-8").replace(datetime.now().astimezone().isoformat()[:4], "not-a-date", 1),
            encoding="utf-8",
        )

        entries = register.outstanding(repo_root=repo)

        assert entries[0]["overdue"] is False


class TestNeverProduction:
    """A caller that asks for a repo_root must never be handed the live register."""

    def test_re_rooting_lands_inside_the_given_tree(self, repo):
        assert register.register_file(repo_root=repo) == repo / ".aipass" / register.REGISTER_FILENAME

    def test_re_rooting_never_returns_the_live_register(self, repo):
        """The defect feed.py was fixed for: a test writing production state.

        A caller who explicitly passed a root and silently got the real file
        would poison the live register from inside a test run.
        """
        live = register.register_file()

        assert register.register_file(repo_root=repo) != live

    def test_re_rooting_works_with_no_registry_marker_anywhere(self, monkeypatch, tmp_path):
        """A FRESH CHECKOUT has no marker — the registry is untracked runtime state.

        This test replaces one that asserted a RuntimeError here, and that
        assertion was pinning the bug rather than the behaviour. The old code
        re-DERIVED the root by walking for a marker file after find_repo_root()
        had already returned one; with no marker on disk the walk found nothing
        and raised for every caller passing repo_root — 26 of @devpulse's tests
        and the CI job on PR 739 (reported by them, 2026-08-23).

        The root is now carried, not hunted, so there is no second answer to
        disagree with the first.
        """
        orphan = tmp_path / "no-marker-above-here"
        orphan.mkdir()
        monkeypatch.setattr(register, "find_repo_root", lambda: orphan)
        target = tmp_path / "elsewhere"

        assert register.register_file(repo_root=target) == target / ".aipass" / register.REGISTER_FILENAME

    def test_writing_works_with_no_registry_marker_anywhere(self, monkeypatch, tmp_path):
        orphan = tmp_path / "no-marker"
        orphan.mkdir()
        monkeypatch.setattr(register, "find_repo_root", lambda: orphan)
        target = tmp_path / "x"

        dispatch_id = register.open_dispatch("@a", "@b", "s", 7200, repo_root=target)

        assert dispatch_id, "a fresh checkout must not stop a dispatch being registered"
        assert (target / ".aipass" / register.REGISTER_FILENAME).exists()

    def test_the_transplant_never_reaches_outside_the_given_root(self, monkeypatch, tmp_path):
        """Structural, not checked: every return is rooted at what the caller passed."""
        orphan = tmp_path / "no-marker-either"
        orphan.mkdir()
        monkeypatch.setattr(register, "find_repo_root", lambda: orphan)
        target = tmp_path / "sandbox"

        result = register.register_file(repo_root=target)

        assert target in result.parents


class TestReadingIsForgiving:
    """Concurrent appenders mean a torn line is possible; it must cost one record, not all."""

    def test_a_malformed_line_does_not_cost_the_records_after_it(self, repo):
        register.open_dispatch("@a", "@b", "first", 7200, repo_root=repo)
        path = repo / ".aipass" / register.REGISTER_FILENAME
        with open(path, "a", encoding="utf-8") as f:
            f.write('{"dispatch_id": "torn"\n')
        register.open_dispatch("@a", "@c", "second", 7200, repo_root=repo)

        subjects = {e["subject"] for e in register.outstanding(repo_root=repo)}

        assert subjects == {"first", "second"}

    def test_no_register_yet_is_an_empty_state_not_a_failure(self, repo):
        assert register.outstanding(repo_root=repo) == []

    def test_the_register_is_capped_like_the_feed(self, repo, monkeypatch):
        monkeypatch.setattr(register, "REGISTER_MAX_LINES", 6)
        monkeypatch.setattr(register, "REGISTER_KEEP_LINES", 3)

        for i in range(8):
            register.open_dispatch("@a", f"@b{i}", str(i), 7200, repo_root=repo)

        assert len(_lines(repo)) <= 6


class TestEmptyAndUnreadableAreNotTheSameAnswer:
    """@devpulse's pin: "none outstanding" and "I cannot tell" must not render alike.

    They wrote it against the old re-root raise, which was the WRONG trigger —
    it fired on every fresh checkout, where nothing is actually wrong. Removing
    it was correct and their own later dispatch asked for it. The distinction
    they were protecting is not, and this is where it actually belongs: a
    register that EXISTS and cannot be READ.
    """

    def test_a_missing_register_is_empty_because_nothing_was_registered(self, repo):
        """The honest empty state — no file yet means no promises yet."""
        assert register.outstanding(repo_root=repo) == []

    def test_an_unreadable_register_raises_instead_of_reporting_all_clear(self, repo):
        """A register that exists but cannot be read must never answer "[]".

        Staged as a DIRECTORY at the register's path: it exists, so the
        defined-empty-state check passes, and opening it is an OSError. That is
        the same shape as a permission failure or a bad mount, without a test
        that behaves differently under root.
        """
        path = repo / ".aipass" / register.REGISTER_FILENAME
        path.parent.mkdir(parents=True, exist_ok=True)
        path.mkdir()

        with pytest.raises(OSError):
            register.outstanding(repo_root=repo)

    def test_the_feed_keeps_the_tolerant_read(self, tmp_path):
        """Strictness is opt-in — a bell that raises at a delivery hook is worse."""
        from aipass.ai_mail.apps.handlers.notify import jsonl_records

        unreadable = tmp_path / "feed.jsonl"
        unreadable.mkdir()

        assert list(jsonl_records(unreadable)) == []


class TestTheSuiteCannotTouchProduction:
    """The conftest guard, pinned — it was added after the suite wrote 31 phantoms."""

    def test_the_register_under_test_is_never_the_live_one(self):
        """wake_branch registers before it spawns, and the wake tests mock the spawn.

        The first run of this suite therefore wrote 31 "outstanding" entries into
        the real register, every one of which would have read as OVERDUE two hours
        later — phantom crashes in the one file whose job is to make real crashes
        visible. Third of its kind after FEED_PATH and CONTACTS_FILE.
        """
        live = Path(__file__).resolve().parents[4] / ".aipass" / register.REGISTER_FILENAME

        assert live.name == register.REGISTER_FILENAME, "anchor check: the live path must be real"
        assert register.register_file() != live

    def test_the_reports_directory_under_test_is_never_the_live_one(self):
        from aipass.ai_mail.apps.handlers.dispatch import report

        live = Path(__file__).resolve().parents[4] / ".aipass" / report.REPORTS_DIRNAME

        assert live.name == report.REPORTS_DIRNAME, "anchor check: the live path must be real"
        assert report.reports_dir() != live
