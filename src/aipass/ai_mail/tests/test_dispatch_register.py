"""The dispatch register — what was promised, and what a reader can tell from it.

FPLAN-0452 P0.

The register's whole value is that crash detection costs nothing: an entry past
its expected_by with no completion record is a FACT ABOUT A FILE, visible to
anyone who looks, with no process running to discover it. These tests pin the
properties that fact depends on — append-only, never production, honest about
what it cannot parse.
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from aipass.ai_mail.apps.handlers.dispatch import register


@pytest.fixture
def repo(tmp_path):
    """A tmp tree carrying the repo marker, so re-rooting can be honoured."""
    (tmp_path / "AIPASS_REGISTRY.json").write_text("{}", encoding="utf-8")
    return tmp_path


def _lines(repo_root):
    return (repo_root / ".aipass" / register.REGISTER_FILENAME).read_text(encoding="utf-8").strip().splitlines()


def _only_open_row(repo_root):
    """The single outstanding row, asserted to be single so a fold bug cannot hide."""
    rows = register.outstanding(repo_root=repo_root)
    assert len(rows) == 1, f"expected exactly one open row, got {len(rows)}"
    return rows[0]


def _a_pid_that_is_gone():
    """A pid that certainly does not exist: spawn a process and reap it.

    Not a large made-up number — pids wrap, and a test that assumes 999999 is
    free is a test that fails on a busy box for a reason nobody will believe.
    Waiting on a real child guarantees the pid is dead when we look.
    """
    proc = subprocess.Popen([sys.executable, "-c", ""])
    proc.wait()
    return proc.pid


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


class TestADeclinedWakeBackIsOnTheRow:
    """wake_branch(wake_back=False) — @daemon's scheduled nudges — says so on the
    row, and ONLY then: an absent key means the default, so every default row
    stays byte-identical to the rows written before the option existed."""

    def test_a_declined_wake_back_is_recorded_and_survives_the_pid_annotation(self, repo):
        dispatch_id = register.open_dispatch("@daemon", "@api", "", 7200, repo_root=repo, wake_back=False)

        assert dispatch_id
        assert json.loads(_lines(repo)[0])["wake_back"] is False
        assert register.record_monitor_pid(dispatch_id, os.getpid(), repo_root=repo)
        assert _only_open_row(repo)["wake_back"] is False

    def test_a_default_row_carries_no_wake_back_key(self, repo):
        register.open_dispatch("@devpulse", "@api", "one", 7200, repo_root=repo)
        register.open_dispatch("@devpulse", "@api", "two", 7200, repo_root=repo, wake_back=True)

        rows = [json.loads(line) for line in _lines(repo)]
        assert len(rows) == 2
        assert all("wake_back" not in row for row in rows)


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


class TestTheMonitorPidMakesADeathVisibleEarly:
    """FPLAN-0499 phase 2. Without a pid on the row a dead monitor is invisible
    until ``expected_by`` — HARD_TIMEOUT, two hours. With one, a reader sees the
    process is gone on the next watchdog pass, five minutes.

    The tri-state is the load-bearing part. "No pid recorded" is every row
    written before this landed, plus the systemd-scope spawn path which never
    learns a pid; reporting those as dead would have announced a death for the
    whole backlog the moment it shipped.
    """

    def test_a_row_whose_pid_is_gone_reports_monitor_alive_false(self, repo):
        """The brief's pin: a dead monitor is visible on the row itself."""
        dispatch_id = register.open_dispatch("@devpulse", "@ai_mail", "s", 7200, repo_root=repo)
        assert dispatch_id
        dead_pid = _a_pid_that_is_gone()

        assert register.record_monitor_pid(dispatch_id, dead_pid, repo_root=repo) is True

        row = _only_open_row(repo)
        assert row["monitor_pid"] == dead_pid
        assert row["monitor_alive"] is False, "a vanished monitor must read as dead, not unknown"

    def test_a_live_monitor_reports_alive(self, repo):
        """Our own process stands in for a living monitor — it demonstrably exists."""
        dispatch_id = register.open_dispatch("@devpulse", "@ai_mail", "s", 7200, repo_root=repo)
        assert dispatch_id

        register.record_monitor_pid(dispatch_id, os.getpid(), repo_root=repo)

        assert _only_open_row(repo)["monitor_alive"] is True

    def test_a_row_with_no_pid_is_unknown_not_dead(self, repo):
        """The distinction the whole tri-state exists for.

        Every row written before this feature has no pid. If absence read as
        False, shipping it would have announced a death for each one.
        """
        register.open_dispatch("@devpulse", "@ai_mail", "s", 7200, repo_root=repo)

        row = _only_open_row(repo)
        assert "monitor_pid" not in row
        assert row["monitor_alive"] is None, "an unannotated row cannot be called dead"

    def test_the_annotation_appends_and_leaves_the_promise_intact(self, repo):
        """Append-only is the module's one discipline; the annotation obeys it."""
        dispatch_id = register.open_dispatch("@devpulse", "@ai_mail", "s", 7200, repo_root=repo)
        assert dispatch_id

        register.record_monitor_pid(dispatch_id, os.getpid(), repo_root=repo)

        lines = _lines(repo)
        assert len(lines) == 2, "the annotation is a SECOND record, never a rewrite"
        assert "monitor_pid" not in json.loads(lines[0]), "the original promise is untouched"
        assert json.loads(lines[1])["monitor_pid"] == os.getpid()

    def test_the_annotation_keeps_the_row_open_and_its_fields(self, repo):
        """Annotating must not close the dispatch or lose what it promised."""
        dispatch_id = register.open_dispatch("@devpulse", "@ai_mail", "Build it", 7200, repo_root=repo)
        assert dispatch_id
        before = _only_open_row(repo)

        register.record_monitor_pid(dispatch_id, os.getpid(), repo_root=repo)

        after = _only_open_row(repo)
        assert after["dispatch_id"] == dispatch_id
        assert after["status"] == register.STATUS_OUTSTANDING
        assert after["subject"] == "Build it"
        assert after["expected_by"] == before["expected_by"], "the deadline must not move"

    def test_an_already_closed_dispatch_is_not_resurrected_by_a_late_pid(self, repo):
        """A late annotation must not reopen finished work.

        The monitor writes its completion and exits; an annotation arriving
        after that would otherwise append a fresh `outstanding` record and the
        dispatch would read as open forever.
        """
        dispatch_id = register.open_dispatch("@devpulse", "@ai_mail", "s", 7200, repo_root=repo)
        assert dispatch_id
        register.close_dispatch(dispatch_id, "completed", repo_root=repo)

        assert register.record_monitor_pid(dispatch_id, os.getpid(), repo_root=repo) is False
        assert register.outstanding(repo_root=repo) == []

    def test_an_unknown_dispatch_id_is_refused(self, repo):
        register.open_dispatch("@devpulse", "@ai_mail", "s", 7200, repo_root=repo)

        assert register.record_monitor_pid("no-such-id", os.getpid(), repo_root=repo) is False

    @pytest.mark.parametrize("bad", [0, -1, None, "1234"])
    def test_a_pid_that_is_not_a_positive_int_is_refused(self, repo, bad):
        """A zero pid is what the systemd-scope path carries — it is not a pid."""
        dispatch_id = register.open_dispatch("@devpulse", "@ai_mail", "s", 7200, repo_root=repo)
        assert dispatch_id

        assert register.record_monitor_pid(dispatch_id, bad, repo_root=repo) is False
        assert _only_open_row(repo)["monitor_alive"] is None

    @pytest.mark.parametrize("bad", [0, -1, None, "1234"])
    def test_monitor_alive_cannot_be_told_for_a_non_pid(self, bad):
        assert register.monitor_alive(bad) is None

    # ── The Windows leg, runnable on every platform through a fake kernel32.
    # The Windows matrix on 6d764980 went red on the two liveness pins above:
    # the first cut answered None on win32, so a watchdog there could never
    # see a dead monitor. These pin the mapping of the Win32 answers onto the
    # tri-state without needing the platform.

    @pytest.mark.parametrize(
        ("handle", "exit_code", "last_error", "expected"),
        [
            (1, register._STILL_ACTIVE, 0, True),
            (1, 0, 0, False),
            (0, None, register._ERROR_INVALID_PARAMETER, False),
            (0, None, register._ERROR_ACCESS_DENIED, True),
            (0, None, 6, None),
        ],
        ids=["opened-and-running", "opened-but-exited", "no-such-pid", "exists-not-ours", "other-error-unknown"],
    )
    def test_the_windows_leg_maps_win32_answers_onto_the_tri_state(
        self, monkeypatch, handle, exit_code, last_error, expected
    ):
        closed: list[int] = []
        opened_with: list[tuple] = []

        def _exit_code_into(_h, out):
            out.contents.value = exit_code
            return 1

        # Attributes named as Win32 names them — the probe calls them by these names.
        fake_kernel32 = SimpleNamespace(
            OpenProcess=lambda access, inherit, pid: opened_with.append((access, inherit, pid)) or handle,
            GetExitCodeProcess=_exit_code_into,
            CloseHandle=lambda h: closed.append(h) or 1,
        )
        monkeypatch.setattr(register, "_kernel32", lambda: fake_kernel32)
        monkeypatch.setattr(register, "_last_win32_error", lambda: last_error)

        assert register._monitor_alive_windows(4242) is expected
        assert opened_with == [(register._PROCESS_QUERY_LIMITED_INFORMATION, False, 4242)]
        assert closed == ([handle] if handle else []), "an opened handle is closed exactly once, an unopened one never"

    def test_on_win32_monitor_alive_asks_the_windows_leg_and_never_signals(self, monkeypatch):
        """Signal 0 is TerminateProcess on Windows — the router must not reach os.kill."""
        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.setattr(register, "_monitor_alive_windows", lambda pid: "windows-leg")
        monkeypatch.setattr(register.os, "kill", lambda *a: pytest.fail("os.kill must never be reached on win32"))

        assert register.monitor_alive(4242) == "windows-leg"


class TestAReplyClosesTheRow:
    """FPLAN-0499 phase 2, and the incident that shaped it.

    At 17:15 on 2026-09-07 the watchdog announced DEAD for @api's dispatch
    641dddbb because the row hit its two-hour expected_by — while @api had
    replied on that thread at 16:45 and its work was landed. The reply was the
    completion evidence and nothing read it.

    MATCHING IS BY THREAD, NOT BY THE AGENT'S DISPATCH STAMP. The same incident
    is why: @api's stamped id sat on its 15:16 report-first PLAN, sent before
    the work was done, while the real completion at 16:45 carried a different
    stamp because the agent had been resumed under a new dispatch id. The stamp
    would have closed the row early and still missed the completion.
    """

    def test_a_reply_on_the_thread_closes_the_dispatch(self, repo):
        dispatch_id = register.open_dispatch("@devpulse", "@api", "Your brief", 7200, repo_root=repo)
        assert dispatch_id

        closed = register.close_on_reply("@api", "@devpulse", "RE: Your brief", repo_root=repo)

        assert closed == dispatch_id
        assert register.outstanding(repo_root=repo) == []

    def test_the_close_names_the_reply_as_the_reason(self, repo):
        """ "The agent said it was done" and "the monitor saw it exit" are
        different facts, and a reader that cannot tell them apart cannot spot a
        dispatch that reported but never terminated."""
        register.open_dispatch("@devpulse", "@api", "Your brief", 7200, repo_root=repo)

        register.close_on_reply("@api", "@devpulse", "RE: Your brief", repo_root=repo)

        assert json.loads(_lines(repo)[-1])["status"] == register.STATUS_REPLIED

    def test_a_report_first_plan_does_not_close_the_row(self, repo):
        """THE REGRESSION THIS RULE EXISTS TO AVOID.

        @api's plan mail was a fresh subject, not a reply on the brief's thread.
        Closing on it would stop the watchdog watching a dispatch whose work has
        not started — which is worse than the false DEAD it replaces.
        """
        register.open_dispatch("@devpulse", "@api", "Your brief - ONE ROOM step 1", 7200, repo_root=repo)

        closed = register.close_on_reply(
            "@api", "@devpulse", "FPLAN-0492 wave 4 - @api PLAN (report-first, before building)", repo_root=repo
        )

        assert closed is None
        assert len(register.outstanding(repo_root=repo)) == 1, "a plan is not a completion"

    def test_a_resumed_agent_still_closes_its_original_row(self, repo):
        """The live case: the completion carried a DIFFERENT dispatch stamp.

        The thread is the only link that survives a resume, which is exactly why
        the stamp cannot be the matcher.
        """
        original = register.open_dispatch("@devpulse", "@api", "Your brief", 7200, repo_root=repo)
        assert original

        closed = register.close_on_reply("@api", "@devpulse", "RE: Your brief", repo_root=repo)

        assert closed == original

    def test_a_third_party_reply_does_not_close_it(self, repo):
        """A dispatch is a promise between two named seats."""
        register.open_dispatch("@devpulse", "@api", "Your brief", 7200, repo_root=repo)

        assert register.close_on_reply("@trigger", "@devpulse", "RE: Your brief", repo_root=repo) is None
        assert len(register.outstanding(repo_root=repo)) == 1

    def test_a_reply_to_someone_else_does_not_close_it(self, repo):
        """Answering a third party says nothing to the seat that promised it."""
        register.open_dispatch("@devpulse", "@api", "Your brief", 7200, repo_root=repo)

        assert register.close_on_reply("@api", "@trigger", "RE: Your brief", repo_root=repo) is None
        assert len(register.outstanding(repo_root=repo)) == 1

    def test_a_different_thread_does_not_close_it(self, repo):
        register.open_dispatch("@devpulse", "@api", "Your brief", 7200, repo_root=repo)

        assert register.close_on_reply("@api", "@devpulse", "RE: something else", repo_root=repo) is None
        assert len(register.outstanding(repo_root=repo)) == 1

    def test_a_bare_wake_has_no_thread_to_reply_on(self, repo):
        """An empty subject can never be matched — stated, not silently missing."""
        register.open_dispatch("@trigger", "@api", "", 7200, repo_root=repo)

        assert register.close_on_reply("@api", "@trigger", "RE: ", repo_root=repo) is None
        assert len(register.outstanding(repo_root=repo)) == 1

    def test_closing_appends_and_leaves_the_promise_readable(self, repo):
        register.open_dispatch("@devpulse", "@api", "Your brief", 7200, repo_root=repo)

        register.close_on_reply("@api", "@devpulse", "RE: Your brief", repo_root=repo)

        lines = _lines(repo)
        assert len(lines) == 2
        assert json.loads(lines[0])["status"] == register.STATUS_OUTSTANDING, "the promise stays in the file"

    def test_a_second_reply_closes_nothing(self, repo):
        """Idempotent: the row is already closed, so there is nothing to close."""
        register.open_dispatch("@devpulse", "@api", "Your brief", 7200, repo_root=repo)
        register.close_on_reply("@api", "@devpulse", "RE: Your brief", repo_root=repo)

        assert register.close_on_reply("@api", "@devpulse", "RE: Your brief", repo_root=repo) is None

    def test_only_the_matching_thread_closes(self, repo):
        """Two dispatches to the same target: the subject decides which ends."""
        first = register.open_dispatch("@devpulse", "@api", "one", 7200, repo_root=repo)
        second = register.open_dispatch("@devpulse", "@api", "two", 7200, repo_root=repo)
        assert first and second

        register.close_on_reply("@api", "@devpulse", "RE: one", repo_root=repo)

        assert [r["dispatch_id"] for r in register.outstanding(repo_root=repo)] == [second]

    @pytest.mark.parametrize(
        "subject,expected",
        [
            ("RE: Your brief", "your brief"),
            ("RE: RE: Your brief", "your brief"),
            ("  re:   Your brief  ", "your brief"),
            ("Your brief", "your brief"),
            ("", ""),
        ],
    )
    def test_thread_subject_strips_every_re_marker(self, subject, expected):
        """A reply to a reply stacks the prefix; one strip would split the thread."""
        assert register.thread_subject(subject) == expected


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
