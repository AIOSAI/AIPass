"""The completion report — what the finishing agent can honestly say about its run.

FPLAN-0452 P1.

Two of these tests exist because of a specific argument, and they are the ones
to keep if the file ever shrinks:

* ``test_a_mail_written_by_someone_else_during_the_run_is_not_claimed`` is the
  difference between a RECORD and an INFERENCE. An mtime scan of ``sent/``
  attributes by TIME; the stamp attributes by AUTHORSHIP.
* ``test_bg_orphaned_ships_beside_an_empty_email_list`` pins the honesty
  requirement. A run whose background tasks were killed reports zero emails for
  an agent that believed it had replied — without the flag beside it, a reader
  concludes the agent ignored its mail.
"""

import json
import time
from pathlib import Path

import pytest

from aipass.ai_mail.apps.handlers.dispatch import report


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "AIPASS_REGISTRY.json").write_text("{}", encoding="utf-8")
    return tmp_path


@pytest.fixture
def branch(tmp_path):
    """A branch seat with the two directories a report reads."""
    seat = tmp_path / "seat"
    (seat / ".trinity").mkdir(parents=True)
    (seat / ".ai_mail.local" / "sent").mkdir(parents=True)
    return seat


def _write_sent(branch_path, name, **fields):
    record = {"to": "@devpulse", "subject": "s", **fields}
    (branch_path / ".ai_mail.local" / "sent" / f"{name}.json").write_text(json.dumps(record), encoding="utf-8")


class TestEmailsSentIsARecordNotAnInference:
    """Attribution is by authorship. Timing credits whoever happened to write."""

    def test_a_mail_written_by_someone_else_during_the_run_is_not_claimed(self, branch):
        """The whole argument for the stamp, in one test.

        Both files are written inside the run's window, so an mtime scan would
        report BOTH as this agent's work. Only one carries the dispatch id.
        """
        _write_sent(branch, "mine", dispatch_id="abc-123", to="@flow")
        _write_sent(branch, "not_mine", to="@prax")

        sent = report.emails_sent(branch, "abc-123")

        assert [mail["to"] for mail in sent] == ["@flow"]

    def test_a_mail_from_a_different_dispatch_is_not_claimed(self, branch):
        _write_sent(branch, "other_run", dispatch_id="other-999", to="@prax")

        assert report.emails_sent(branch, "abc-123") == []

    def test_replies_are_distinguished_from_sends(self, branch):
        _write_sent(branch, "a_reply", dispatch_id="abc-123", in_reply_to="deadbeef", to="@devpulse")
        _write_sent(branch, "a_send", dispatch_id="abc-123", to="@api")

        kinds = {mail["to"]: mail["kind"] for mail in report.emails_sent(branch, "abc-123")}

        assert kinds == {"@devpulse": "reply", "@api": "send"}

    def test_an_unregistered_run_claims_nothing_rather_than_guessing(self, branch):
        """No id means no attribution — which is the point, not a shortfall."""
        _write_sent(branch, "orphan", to="@flow")

        assert report.emails_sent(branch, None) == []

    def test_an_unreadable_sent_record_costs_only_itself(self, branch):
        (branch / ".ai_mail.local" / "sent" / "torn.json").write_text("{not json", encoding="utf-8")
        _write_sent(branch, "good", dispatch_id="abc-123", to="@flow")

        assert [mail["to"] for mail in report.emails_sent(branch, "abc-123")] == ["@flow"]

    def test_agents_contacted_is_the_deduplicated_recipient_set(self, branch):
        _write_sent(branch, "one", dispatch_id="abc", to="@flow")
        _write_sent(branch, "two", dispatch_id="abc", to="@flow")
        _write_sent(branch, "three", dispatch_id="abc", to="@prax")

        built = report.build_report(
            "abc", "@devpulse", "@ai_mail", branch, time.time(), 12, 0, "completed", [], False, False, "woken"
        )

        assert built["agents_contacted"] == ["@flow", "@prax"]


class TestMemoriesEditedIsAWriteDetector:
    """It answers "was anything written", which is all a timestamp can answer."""

    def test_a_memory_written_after_the_run_started_reads_as_edited(self, branch):
        start = time.time() - 10
        (branch / ".trinity" / "local.json").write_text("{}", encoding="utf-8")

        assert report.memories_edited(branch, start) is True

    def test_a_memory_untouched_since_before_the_run_reads_as_not_edited(self, branch):
        memory = branch / ".trinity" / "local.json"
        memory.write_text("{}", encoding="utf-8")

        assert report.memories_edited(branch, time.time() + 10) is False

    def test_a_seat_with_no_trinity_is_not_edited_rather_than_an_error(self, tmp_path):
        assert report.memories_edited(tmp_path / "nothing", time.time()) is False


class TestTheHonestyRequirements:
    """Never a bare exit 0."""

    def test_bg_orphaned_ships_beside_an_empty_email_list(self, branch):
        """The report says "0 emails" for an agent that believed it had replied.

        Its background tasks — possibly including that reply — were killed at
        the headless ceiling. The flag is what stops a reader concluding the
        agent ignored its mail.
        """
        built = report.build_report(
            "abc", "@devpulse", "@ai_mail", branch, time.time(), 30, 0, "INCOMPLETE", [], True, False, "woken"
        )

        assert built["emails_sent"] == []
        assert built["bg_orphaned"] is True, "an empty email list without this flag reads as a lazy agent"
        assert "max_turns_hit" in built

    def test_every_rule_four_fact_is_present(self, branch):
        built = report.build_report(
            "abc",
            "@devpulse",
            "@ai_mail",
            branch,
            time.time(),
            30,
            0,
            "completed",
            [{"attempt": 1}],
            False,
            False,
            "woken",
        )

        for field in (
            "dispatch_id",
            "sender",
            "target",
            "dispatched_at",
            "duration_s",
            "exit_code",
            "status",
            "attempts",
            "bg_orphaned",
            "max_turns_hit",
            "wake_result",
            "memories_edited",
            "emails_sent",
            "agents_contacted",
        ):
            assert field in built, f"rule-4 report is missing {field}"

    def test_cost_and_tokens_come_from_the_result_json(self, branch):
        built = report.build_report(
            "abc",
            "@d",
            "@a",
            branch,
            time.time(),
            1,
            0,
            "completed",
            [],
            False,
            False,
            "woken",
            result_json={"total_cost_usd": 1.41, "num_turns": 11, "usage": {"output_tokens": 900}, "result": "done"},
        )

        assert built["total_cost_usd"] == 1.41
        assert built["num_turns"] == 11
        assert built["output_tokens"] == 900
        assert built["result_excerpt"] == "done"

    def test_a_missing_result_json_leaves_the_fields_empty_not_invented(self, branch):
        built = report.build_report(
            "abc", "@d", "@a", branch, time.time(), 1, 0, "completed", [], False, False, "woken"
        )

        assert built["total_cost_usd"] is None
        assert built["output_tokens"] is None


class TestTheReportIsDurable:
    """A file that waits, not a message that must be caught."""

    def test_the_report_is_written_under_its_dispatch_id(self, repo, branch):
        built = report.build_report(
            "abc-123", "@d", "@a", branch, time.time(), 1, 0, "completed", [], False, False, "woken"
        )

        path = report.write_report(built, repo_root=repo)

        assert path is not None
        assert json.loads(open(path, encoding="utf-8").read())["dispatch_id"] == "abc-123"

    def test_an_unregistered_run_still_leaves_a_report(self, repo, branch):
        """Losing the attribution must not also lose the evidence of the run."""
        built = report.build_report(None, "@d", "@a", branch, time.time(), 1, 0, "completed", [], False, False, "woken")

        path = report.write_report(built, repo_root=repo)

        assert path is not None and path.endswith("unregistered.json")

    def test_reports_are_pruned_to_a_ceiling(self, repo, monkeypatch):
        monkeypatch.setattr(report, "REPORTS_MAX_FILES", 4)
        monkeypatch.setattr(report, "REPORTS_KEEP_FILES", 2)

        for i in range(7):
            report.write_report({"dispatch_id": f"id-{i}"}, repo_root=repo)

        assert len(list(report.reports_dir(repo_root=repo).glob("*.json"))) <= 4

    def test_re_rooting_never_returns_the_live_reports_directory(self, repo):
        assert report.reports_dir(repo_root=repo) != report.reports_dir()

    def test_re_rooting_works_with_no_registry_marker_anywhere(self, monkeypatch, tmp_path):
        """Same fresh-checkout fix as the register — see its test for the history."""
        orphan = tmp_path / "no-marker"
        orphan.mkdir()
        monkeypatch.setattr(report, "find_repo_root", lambda: orphan)
        target = tmp_path / "elsewhere"

        assert report.reports_dir(repo_root=target) == target / ".aipass" / report.REPORTS_DIRNAME

    def test_a_report_still_writes_with_no_registry_marker_anywhere(self, monkeypatch, tmp_path):
        orphan = tmp_path / "no-marker"
        orphan.mkdir()
        monkeypatch.setattr(report, "find_repo_root", lambda: orphan)
        target = tmp_path / "elsewhere"

        path = report.write_report({"dispatch_id": "x"}, repo_root=target)

        assert path is not None and Path(path).exists()

    def test_an_unwritable_report_returns_none_so_the_caller_can_say_so(self, monkeypatch, tmp_path):
        """A real write failure still reports itself — a FILE where the dir must go."""
        blocker = tmp_path / "blocked"
        blocker.mkdir()
        (blocker / ".aipass").write_text("not a directory", encoding="utf-8")
        monkeypatch.setattr(report, "find_repo_root", lambda: tmp_path / "anywhere")

        assert report.write_report({"dispatch_id": "x"}, repo_root=blocker) is None


class TestTheStamp:
    """One place stamps, so sends and replies cannot drift apart."""

    def test_mail_sent_under_a_dispatch_carries_its_id(self, monkeypatch):
        monkeypatch.setenv(report.DISPATCH_ID_ENV, "abc-123")

        assert report.stamp_dispatch_id({"to": "@x"})["dispatch_id"] == "abc-123"

    def test_mail_sent_outside_a_dispatch_carries_no_stamp(self, monkeypatch):
        """Correct, not a shortfall: it belongs to no dispatch."""
        monkeypatch.delenv(report.DISPATCH_ID_ENV, raising=False)

        assert "dispatch_id" not in report.stamp_dispatch_id({"to": "@x"})

    def test_an_empty_env_value_is_treated_as_no_dispatch(self, monkeypatch):
        monkeypatch.setenv(report.DISPATCH_ID_ENV, "   ")

        assert report.current_dispatch_id() is None


class TestThePush:
    """In-process only, and it must never take the run down with it."""

    def test_a_trigger_failure_is_reported_not_raised(self, monkeypatch):
        """The durable write already happened; a failed push must not undo it."""
        import sys

        monkeypatch.setitem(sys.modules, "aipass.trigger.apps.modules.core", None)

        assert report.fire_completed("abc", "@d", "@a", "/x.json") is False
