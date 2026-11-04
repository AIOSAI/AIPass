# =================== AIPass ====================
# Name: test_dispatch_register.py
# Description: Tests for the dispatch register append-only log
# Version: 1.2.0
# Created: 2026-08-22
# Modified: 2026-11-03
# =============================================

"""Tests for apps/handlers/dispatch/register.py: the append-only dispatch register, and the grant its rows carry."""

# An entry past expected_by with no completion is a fact about a file; these pin append-only and honest parsing.

# The declared pass — what is NOT tested here, and what covers it instead:
# sentry: no-test-needed(windows_compat) — monitor_alive()'s Windows OpenProcess leg (_monitor_alive_windows)

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from aipass.ai_mail.apps.handlers.dispatch import grant as grant_mod
from aipass.ai_mail.apps.handlers.dispatch import register, report
from aipass.ai_mail.apps.handlers.notify import jsonl_records


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
    """A pid that certainly does not exist: spawn a process and reap it (pids wrap, so no made-up number)."""
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

    def test_the_row_names_its_provider_claude_unless_told(self, repo):
        import json

        register.open_dispatch("@devpulse", "@canary", "one", 7200, repo_root=repo)
        register.open_dispatch("@devpulse", "@canary", "two", 7200, repo_root=repo, provider="codex")

        assert [json.loads(line)["provider"] for line in _lines(repo)] == ["claude", "codex"]

    def test_expected_by_comes_from_the_caller_not_a_number_invented_here(self, repo):
        """The spec forbids an invented timeout — expected_seconds is the contract.

        The caller passes HARD_TIMEOUT, so "past expected_by" means the monitor died.
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
    """wake_branch(wake_back=False) says so on the row, and ONLY then: absent key means default."""

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

        report_path = str(repo / "reports" / "x.json")
        dispatch_id = register.open_dispatch("@devpulse", "@ai_mail", "s", 7200, repo_root=repo)
        assert dispatch_id
        register.close_dispatch(dispatch_id, "completed", report_path, repo_root=repo)

        lines = _lines(repo)
        assert len(lines) == 2, "close must APPEND, never rewrite"
        assert json.loads(lines[0])["status"] == register.STATUS_OUTSTANDING, "the promise must survive its answer"
        closing = json.loads(lines[1])
        assert closing["dispatch_id"] == dispatch_id
        assert closing["status"] == "completed"
        assert closing["report_path"] == report_path

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
    """Without a pid on the row a dead monitor is invisible until ``expected_by``; with one, next watchdog pass.

    Tri-state: "no pid recorded" (old rows, systemd-scope spawns) is unknown, never dead.
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
        """The distinction the whole tri-state exists for: absence of a pid is not death."""
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
        """A late annotation must not reopen finished work (it would read as open forever)."""
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

    # Win32 codes as documented (STILL_ACTIVE 259, ERROR_INVALID_PARAMETER 87, ERROR_ACCESS_DENIED 5,
    # PROCESS_QUERY_LIMITED_INFORMATION 0x1000), not read from the module: an echo cannot catch a wrong one.
    @pytest.mark.parametrize(
        ("handle", "exit_code", "last_error", "expected"),
        [
            (1, 259, 0, True),
            (1, 0, 0, False),
            (0, None, 87, False),
            (0, None, 5, True),
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

        fake_kernel32 = SimpleNamespace(
            OpenProcess=lambda access, inherit, pid: opened_with.append((access, inherit, pid)) or handle,
            GetExitCodeProcess=_exit_code_into,
            CloseHandle=lambda h: closed.append(h) or 1,
        )
        monkeypatch.setattr(register, "_kernel32", lambda: fake_kernel32)
        monkeypatch.setattr(register, "_last_win32_error", lambda: last_error)
        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.setattr(register.os, "kill", lambda *a: pytest.fail("os.kill must never be reached on win32"))

        assert register.monitor_alive(4242) is expected
        assert opened_with == [(0x1000, False, 4242)]
        assert closed == ([handle] if handle else []), "an opened handle is closed exactly once, an unopened one never"

    def test_on_win32_monitor_alive_asks_the_windows_leg_and_never_signals(self, monkeypatch):
        """Signal 0 is TerminateProcess on Windows — the router must not reach os.kill."""
        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.setattr(register, "_monitor_alive_windows", lambda pid: "windows-leg")
        monkeypatch.setattr(register.os, "kill", lambda *a: pytest.fail("os.kill must never be reached on win32"))

        assert register.monitor_alive(4242) == "windows-leg"


class TestAReplyClosesTheRow:
    """A reply on the dispatch thread is completion evidence and closes the row.

    Matching is by thread, not dispatch stamp: a resumed agent carries a new stamp,
    and a report-first plan can carry the old one before the work is done.
    """

    def test_a_reply_on_the_thread_closes_the_dispatch(self, repo):
        dispatch_id = register.open_dispatch("@devpulse", "@api", "Your brief", 7200, repo_root=repo)
        assert dispatch_id

        closed = register.close_on_reply("@api", "@devpulse", "RE: Your brief", repo_root=repo)

        assert closed == dispatch_id
        assert register.outstanding(repo_root=repo) == []

    def test_the_close_names_the_reply_as_the_reason(self, repo):
        """ "The agent said it was done" and "the monitor saw it exit" are different facts."""
        register.open_dispatch("@devpulse", "@api", "Your brief", 7200, repo_root=repo)

        register.close_on_reply("@api", "@devpulse", "RE: Your brief", repo_root=repo)

        assert json.loads(_lines(repo)[-1])["status"] == register.STATUS_REPLIED

    def test_a_report_first_plan_does_not_close_the_row(self, repo):
        """THE REGRESSION THIS RULE EXISTS TO AVOID: a fresh-subject plan mail is not a completion."""
        register.open_dispatch("@devpulse", "@api", "Your brief - ONE ROOM step 1", 7200, repo_root=repo)

        closed = register.close_on_reply(
            "@api", "@devpulse", "FPLAN-0492 wave 4 - @api PLAN (report-first, before building)", repo_root=repo
        )

        assert closed is None
        assert len(register.outstanding(repo_root=repo)) == 1, "a plan is not a completion"

    def test_a_resumed_agent_still_closes_its_original_row(self, repo):
        """The live case: the completion carried a DIFFERENT dispatch stamp; the thread survives a resume."""
        original = register.open_dispatch("@devpulse", "@api", "Your brief", 7200, repo_root=repo)
        assert original

        closed = register.close_on_reply("@api", "@devpulse", "RE: Your brief", repo_root=repo)

        assert closed == original

    def test_a_third_party_reply_does_not_close_it(self, repo):
        """A dispatch is a promise between two named seats."""
        register.open_dispatch("@devpulse", "@api", "Your brief", 7200, repo_root=repo)

        assert register.close_on_reply("@trigger", "@devpulse", "RE: Your brief", repo_root=repo) is None
        assert len(register.outstanding(repo_root=repo)) == 1

    def test_a_register_that_cannot_be_read_raises_rather_than_matching_nothing(self, repo, monkeypatch):
        """None means "this reply answers no open row"; an unreadable register is not that.

        The caller (_close_dispatch_row_on_reply) logs the raise after delivery, so it never blocks the reply.
        """

        def _unreadable(**kwargs):
            raise OSError("register unreadable")

        monkeypatch.setattr(register, "outstanding", _unreadable)

        with pytest.raises(OSError, match="register unreadable"):
            register.close_on_reply("@api", "@devpulse", "RE: Your brief", repo_root=repo)

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
        """The defect feed.py was fixed for: a test writing production state."""
        live = register.register_file()

        assert register.register_file(repo_root=repo) != live

    def test_re_rooting_works_with_no_registry_marker_anywhere(self, monkeypatch, tmp_path):
        """A FRESH CHECKOUT has no marker — the registry is untracked runtime state.

        The root is carried, not re-hunted for a marker, so a given repo_root never raises.
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


class TestThePublicSeam:
    """AIPASS_DISPATCH_REGISTER re-points the default register, read at every call.

    Consumers (devpulse's hermetic_mail_doors) use it instead of patching the private find_repo_root.
    """

    def test_the_variable_names_the_register_every_rootless_caller_reads(self, monkeypatch, tmp_path):
        chosen = tmp_path / "chosen" / "dispatch_register.jsonl"
        monkeypatch.setenv("AIPASS_DISPATCH_REGISTER", str(chosen))

        dispatch_id = register.open_dispatch("@a", "@b", "s", 7200)

        assert register.register_file() == chosen
        assert [row["dispatch_id"] for row in register.outstanding()] == [dispatch_id]
        assert chosen.exists()

    def test_a_given_root_still_wins_over_the_variable(self, monkeypatch, tmp_path):
        monkeypatch.setenv("AIPASS_DISPATCH_REGISTER", str(tmp_path / "chosen.jsonl"))
        target = tmp_path / "rooted"

        assert register.register_file(repo_root=target) == target / ".aipass" / register.REGISTER_FILENAME

    def test_unset_is_the_repo_root_answer(self, monkeypatch, tmp_path):
        monkeypatch.delenv("AIPASS_DISPATCH_REGISTER", raising=False)
        root = tmp_path / "root"
        monkeypatch.setattr(register, "find_repo_root", lambda: root)

        assert register.register_file() == root / ".aipass" / register.REGISTER_FILENAME


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
        """The honest empty state — no file yet means no promises yet."""
        assert register.outstanding(repo_root=repo) == []

    def test_the_register_is_capped_like_the_feed(self, repo, monkeypatch):
        monkeypatch.setattr(register, "REGISTER_MAX_LINES", 6)
        monkeypatch.setattr(register, "REGISTER_KEEP_LINES", 3)

        for i in range(8):
            register.open_dispatch("@a", f"@b{i}", str(i), 7200, repo_root=repo)

        assert len(_lines(repo)) <= 6


class TestEmptyAndUnreadableAreNotTheSameAnswer:
    """@devpulse's pin: "none outstanding" and "I cannot tell" must not render alike.

    The missing-register half is TestReadingIsForgiving.test_no_register_yet_is_an_empty_state_not_a_failure.
    """

    def test_an_unreadable_register_raises_instead_of_reporting_all_clear(self, repo):
        """A register that exists but cannot be read must never answer "[]".

        Staged as a DIRECTORY (not chmod) so the OSError holds under root too.
        """
        path = repo / ".aipass" / register.REGISTER_FILENAME
        path.parent.mkdir(parents=True, exist_ok=True)
        path.mkdir()

        with pytest.raises(OSError):
            register.outstanding(repo_root=repo)

    def test_the_feed_keeps_the_tolerant_read(self, tmp_path):
        """Strictness is opt-in — a bell that raises at a delivery hook is worse."""
        unreadable = tmp_path / "feed.jsonl"
        unreadable.mkdir()

        assert list(jsonl_records(unreadable)) == []


class TestTheSuiteCannotTouchProduction:
    """The conftest guard, pinned — it was added after the suite wrote 31 phantoms."""

    def test_the_register_under_test_is_never_the_live_one(self):
        """wake_branch registers before it spawns, and the wake tests mock the spawn: phantom OVERDUE rows."""
        live = Path(__file__).resolve().parents[4] / ".aipass" / register.REGISTER_FILENAME

        assert live.name == register.REGISTER_FILENAME, "anchor check: the live path must be real"
        assert register.register_file() != live

    def test_the_reports_directory_under_test_is_never_the_live_one(self):
        live = Path(__file__).resolve().parents[4] / ".aipass" / report.REPORTS_DIRNAME

        assert live.name == report.REPORTS_DIRNAME, "anchor check: the live path must be real"
        assert report.reports_dir() != live


def test_a_reply_closes_the_oldest_open_row_first(repo):
    """Two open rows on one thread: the reply closes the first dispatch, so a re-sent one never leaves it open forever."""
    first = register.open_dispatch("@devpulse", "@api", "Your brief", 7200, repo_root=repo)
    second = register.open_dispatch("@devpulse", "@api", "Your brief", 7200, repo_root=repo)

    closed = register.close_on_reply("@api", "@devpulse", "RE: Your brief", repo_root=repo)

    assert closed == first
    assert [row["dispatch_id"] for row in register.outstanding(repo_root=repo)] == [second]


# --- The grant: one key on the open row, decided at every read ---------------------------------


@pytest.fixture
def seed(tmp_path):
    """A foreign project: two granted shapes, a sibling file, a sibling dir sharing a prefix, and .git."""
    root = tmp_path / "seed"
    for rel in ("src/loop.ts", "src/hooks/a.ts", "src/hooks-other/x.ts", "package.json", ".git/config"):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text("x", encoding="utf-8")
    return root


_VERIFY = "aipass.ai_mail.apps.handlers.users.verified_caller.verify_admin_caller"


@pytest.fixture
def admin(monkeypatch):
    """The seat is @devpulse and its 5-leg check (@devpulse's door, the edge) passes."""
    monkeypatch.setenv("AIPASS_CALLER_BRANCH", "devpulse")
    monkeypatch.setattr(_VERIFY, lambda: (True, "admin grant verified"))


def _grant_on(seed, paths):
    return grant_mod.parse_grant(str(seed), paths, seed.parent / "aipass")


def _live_grant(repo, seed, paths="src/loop.ts,src/hooks"):
    """An open @hooks row carrying a grant, its monitor this live test process."""
    dispatch_id = register.open_dispatch(
        "@devpulse", "@hooks", "Build slice A", 7200, repo_root=repo, grant=_grant_on(seed, paths)
    )
    assert isinstance(dispatch_id, str)
    register.record_monitor_pid(dispatch_id, os.getpid(), repo_root=repo)
    return dispatch_id


class TestAGrantRidesTheOpenRow:
    def test_the_row_carries_the_grant_and_its_granter(self, repo, seed, admin):
        dispatch_id = _live_grant(repo, seed)

        [row] = grant_mod.open_grants(repo_root=repo)
        assert row["dispatch_id"] == dispatch_id
        assert row["grant"] == {
            "root": str(seed.resolve()),
            "files": ["src/loop.ts"],
            "dirs": ["src/hooks"],
            "granted_by": "@devpulse",
        }

    def test_a_writer_the_admin_rail_does_not_verify_is_refused_and_writes_no_row(self, repo, seed, monkeypatch):
        monkeypatch.setenv("AIPASS_CALLER_BRANCH", "devpulse")
        monkeypatch.setattr(_VERIFY, lambda: (False, "leg 3 failed"))

        with pytest.raises(grant_mod.GrantRefused, match="only the verified admin seat"):
            register.open_dispatch("@x", "@hooks", "forged", 7200, repo_root=repo, grant=_grant_on(seed, "src"))

        assert not register.register_file(repo).exists()

    def test_an_overlap_is_refused_under_the_lock_naming_the_first_dispatch_and_a_sibling_is_not(
        self, repo, seed, admin
    ):
        first = _live_grant(repo, seed, "src/hooks")

        with pytest.raises(grant_mod.GrantRefused, match=f"overlaps open dispatch {first}"):
            register.open_dispatch(
                "@devpulse", "@api", "b", 7200, repo_root=repo, grant=_grant_on(seed, "src/hooks/a.ts")
            )
        with pytest.raises(grant_mod.GrantRefused, match=f"overlaps open dispatch {first}"):
            register.open_dispatch("@devpulse", "@api", "b", 7200, repo_root=repo, grant=_grant_on(seed, "src"))
        register.open_dispatch("@devpulse", "@api", "c", 7200, repo_root=repo, grant=_grant_on(seed, "src/hooks-other"))

        assert len(grant_mod.open_grants(repo_root=repo)) == 2

    def test_the_same_monitor_pid_twice_appends_no_second_row(self, repo):
        dispatch_id = register.open_dispatch("@devpulse", "@hooks", "s", 7200, repo_root=repo) or ""

        register.record_monitor_pid(dispatch_id, os.getpid(), repo_root=repo)
        register.record_monitor_pid(dispatch_id, os.getpid(), repo_root=repo)

        assert len(_lines(repo)) == 2


class TestTheDoorDecidesOneWrite:
    def test_a_granted_file_and_a_new_file_under_a_granted_dir_are_allowed(self, repo, seed, admin):
        dispatch_id = _live_grant(repo, seed)

        for target in (seed / "src" / "loop.ts", seed / "src" / "hooks" / "new.ts"):
            decision = grant_mod.granted("hooks", dispatch_id, str(target.resolve()), repo_root=repo)
            assert decision["allowed"] is True, decision
            assert decision["dispatch_id"] == dispatch_id

    def test_a_sibling_outside_the_grant_is_refused_even_sharing_a_prefix(self, repo, seed, admin):
        dispatch_id = _live_grant(repo, seed)

        for target in (
            seed / "package.json",
            seed / "src" / "hooks-other" / "x.ts",
            seed / "src" / "hooks" / ".." / "x",
        ):
            decision = grant_mod.granted("hooks", dispatch_id, str(target), repo_root=repo)
            assert decision["allowed"] is False and "outside" in decision["reason"], target

    def test_only_the_rows_own_dispatch_id_and_target_hold_the_grant(self, repo, seed, admin):
        dispatch_id = _live_grant(repo, seed)
        target = str((seed / "src" / "loop.ts").resolve())

        assert grant_mod.granted("hooks", "another-id", target, repo_root=repo)["allowed"] is False
        assert grant_mod.granted("hooks", None, target, repo_root=repo)["allowed"] is False
        refused = grant_mod.granted("sentry", dispatch_id, target, repo_root=repo)
        assert refused["allowed"] is False and "not sentry" in refused["reason"]

    @pytest.mark.parametrize(
        "end",
        [
            lambda repo, did: register.close_dispatch(did, "completed", repo_root=repo),
            lambda repo, did: register.close_on_reply("@hooks", "@devpulse", "RE: Build slice A", repo_root=repo),
            lambda repo, did: register.close_dispatch(did, "stopped", repo_root=repo),
            lambda repo, did: register.close_dispatch(did, "closed: by hand", repo_root=repo),
        ],
        ids=["monitor-exit", "reply", "stop", "close"],
    )
    def test_every_closer_of_the_row_ends_the_grant(self, repo, seed, admin, end):
        dispatch_id = _live_grant(repo, seed)
        target = str((seed / "src" / "loop.ts").resolve())
        assert grant_mod.granted("hooks", dispatch_id, target, repo_root=repo)["allowed"] is True

        end(repo, dispatch_id)

        decision = grant_mod.granted("hooks", dispatch_id, target, repo_root=repo)
        assert decision["allowed"] is False and "not open" in decision["reason"]

    def test_a_monitor_not_known_alive_or_a_row_past_expected_by_refuses(self, repo, seed, admin):
        target = str((seed / "src" / "loop.ts").resolve())
        unknown = register.open_dispatch(
            "@devpulse", "@hooks", "a", 7200, repo_root=repo, grant=_grant_on(seed, "src/loop.ts")
        )
        dead = register.open_dispatch(
            "@devpulse", "@hooks", "b", 7200, repo_root=repo, grant=_grant_on(seed, "src/hooks")
        )
        assert isinstance(unknown, str) and isinstance(dead, str)
        register.record_monitor_pid(dead, _a_pid_that_is_gone(), repo_root=repo)
        late = datetime.now().astimezone() + timedelta(seconds=7300)

        for did, path in ((unknown, target), (dead, str(seed / "src" / "hooks" / "a.ts"))):
            decision = grant_mod.granted("hooks", did, path, repo_root=repo)
            assert decision["allowed"] is False and decision["reason"].endswith("has no monitor known to be alive")
        register.record_monitor_pid(unknown, os.getpid(), repo_root=repo)
        assert grant_mod.granted("hooks", unknown, target, repo_root=repo)["allowed"] is True
        late_decision = grant_mod.granted("hooks", unknown, target, repo_root=repo, now=late)
        assert late_decision["allowed"] is False and late_decision["reason"].endswith("is past its expected_by")

    def test_a_malformed_grant_is_refused_naming_its_dispatch(self, repo, seed):
        row: dict = {
            "dispatch_id": "bad-1",
            "ts": "2026-11-03T00:00:00+00:00",
            "target": "@hooks",
            "status": "outstanding",
        }
        row.update(grant={"root": str(seed)}, monitor_pid=os.getpid())
        register.register_file(repo).parent.mkdir(parents=True)
        register.register_file(repo).write_text(json.dumps(row) + "\n", encoding="utf-8")

        decision = grant_mod.granted("hooks", "bad-1", str(seed / "src" / "loop.ts"), repo_root=repo)

        assert decision == {
            "allowed": False,
            "dispatch_id": "bad-1",
            "reason": "dispatch bad-1 carries a malformed grant",
        }


class TestAGrantIsValidatedBeforeTheSend:
    def test_files_and_directories_are_told_apart_relative_to_the_resolved_root(self, seed):
        assert _grant_on(seed, " src/loop.ts , src/hooks/ ") == {
            "root": str(seed.resolve()),
            "files": ["src/loop.ts"],
            "dirs": ["src/hooks"],
        }

    @pytest.mark.parametrize(
        "paths, said",
        [
            ("src/../src/loop.ts", "without .."),
            ("src,,src/loop.ts", "''"),
            (".", "root itself"),
            (".git/config", ".git"),
            ("nope.ts", "does not exist"),
        ],
    )
    def test_each_bad_path_is_refused_naming_it(self, seed, paths, said):
        with pytest.raises(grant_mod.GrantRefused, match=re.escape(said)):
            _grant_on(seed, paths)

    def test_an_absolute_path_is_refused(self, seed):
        with pytest.raises(grant_mod.GrantRefused, match="must be relative"):
            _grant_on(seed, str((seed / "src").resolve()))

    @pytest.mark.skipif(sys.platform == "win32", reason="creating a symlink needs privilege on Windows")
    def test_a_symlink_escaping_the_root_is_refused(self, seed, tmp_path):
        (tmp_path / "elsewhere").mkdir()
        (seed / "src" / "out").symlink_to(tmp_path / "elsewhere")

        with pytest.raises(grant_mod.GrantRefused, match="resolves outside"):
            _grant_on(seed, "src/out")

    def test_a_root_that_is_missing_or_holds_the_repo_or_a_flag_alone_is_refused(self, seed):
        with pytest.raises(grant_mod.GrantRefused, match="not a directory"):
            grant_mod.parse_grant(str(seed / "gone"), "src", seed.parent)
        with pytest.raises(grant_mod.GrantRefused, match="overlaps the AIPass repo"):
            grant_mod.parse_grant(str(seed), "src", seed / "src")
        with pytest.raises(grant_mod.GrantRefused, match="go together"):
            grant_mod.parse_grant(str(seed), None, seed.parent)
