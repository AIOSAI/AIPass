# =================== META ====================
# Name: test_ci.py
# Description: Tests for the CI red lane module - poll, reply, verdict, status - and the handlers it drives
# Version: 1.1.1
# Created: 2026-10-23
# Modified: 2026-10-24
# =============================================

"""Tests for apps/modules/ci.py and the handlers/ci/ handlers it drives."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(covered_elsewhere) — medic's gates on the ci_red event, in test_ci_red.py
# seedgo: no-test-needed(external) — drone's ci-cure door, ai_mail mail, wake and feed; AIPass tests its own files
# seedgo: no-test-needed(constant) — the fixed prose seedgo_brief() wraps around the cure

import json
from pathlib import Path

import aipass.ai_mail as ai_mail_pkg
from aipass.trigger.apps.handlers.ci import outbound, replies, triage
from aipass.trigger.apps.modules import ci

AUDIT_LOG = (
    "seedgo-audit\tRun seedgo standards audit\t2026-10-23T05:22:30.1Z        ai_mail: 100%  (81 scored)\n"
    "seedgo-audit\tRun seedgo standards audit\t2026-10-23T05:33:48.3Z FAILED: 1 branch(es) below 100%\n"
    "seedgo-audit\tRun seedgo standards audit\t2026-10-23T05:33:48.3Z   hooks: 99%\n"
    "seedgo-audit\tRun seedgo standards audit\t2026-10-23T05:33:48.3Z       └ logged_fallback: 98%  cadence.py:133\n"
    "seedgo-audit\tRun seedgo standards audit\t2026-10-23T05:33:53.4Z ##[error]Process completed with exit code 1.\n"
)
PYTEST_LOG = (
    "test (3.12)\tRun tests\t2026-10-23T05:30:00.0Z FAILED src/aipass/spawn/tests/test_lifecycle.py::test_x - assert\n"
    "test (3.12)\tRun tests\t2026-10-23T05:30:01.0Z ##[error]Process completed with exit code 1.\n"
)
SETUP_LOG = "build\tSet up job\t2026-10-23T05:30:00.0Z ##[error]runner lost\n"
UNOWNED_LOG = "lint\tRun lint\t2026-10-23T05:30:00.0Z ##[error]Process completed with exit code 1.\n"
OWNER_REPLY = (
    "FILES:\nsrc/aipass/hooks/.seedgo/bypass.json\n"
    "CHANGELOG:\n- **hooks bypass lines re-pinned** (@hooks)\nNOTE:\nThe lines moved; re-pointed."
)


def _changelog(root: Path) -> Path:
    path = root / "CHANGELOG.md"
    text = "# Changelog\n\n## [Unreleased]\n\n### Fixed\n\n- older bullet\n\n## 2026-10-01\n"
    path.write_text(text, encoding="utf-8")
    return path


def _dispatched_hooks_red(ci_lane) -> None:
    ci_lane.add_run("900", created="2026-10-23T05:00:00Z")
    ci_lane.logs["900"] = AUDIT_LOG
    assert ci.handle_command("ci", ["poll"]) is True


def _mute_hooks(ci_lane, muted: bool = True) -> None:
    names = [{"name": "hooks", "expires_at": None}] if muted else []
    state = {"config": {"muted_branches": names}}
    (ci_lane.root / "medic_state.json").write_text(json.dumps(state), encoding="utf-8")


def _reviewing(ci_lane) -> Path:
    _dispatched_hooks_red(ci_lane)
    ci.take_reply("900", "hooks", OWNER_REPLY)
    return _changelog(ci_lane.root)


class TestTriage:
    def test_run_list_rows_are_read_and_other_lines_skipped(self):
        text = "completed\tfailure\tt\tCI\tdev\tpush\t42\t1m\t2026-10-23T05:00:00Z\nnot a row\n"
        rows = triage.parse_run_list(text)
        assert [(r["run_id"], r["conclusion"], r["workflow"]) for r in rows] == [("42", "failure", "CI")]

    def test_newest_per_workflow_counts_dev_only(self):
        rows = triage.parse_run_list(
            "completed\tfailure\tt\tCI\tdev\tpush\t1\t1m\t2026-10-23T01:00:00Z\n"
            "completed\tsuccess\tt\tCI\tdev\tpush\t2\t1m\t2026-10-23T02:00:00Z\n"
            "completed\tfailure\tt\tCI\tmain\tpush\t3\t1m\t2026-10-23T03:00:00Z\n"
        )
        assert {k: v["run_id"] for k, v in triage.newest_per_workflow(rows).items()} == {"CI": "2"}

    def test_an_audit_score_below_100_names_its_branch_and_a_full_score_or_subscore_does_not(self):
        facts = triage.triage_log(AUDIT_LOG)
        assert facts["owners"] == ["hooks"]
        assert facts["step"] == "Run seedgo standards audit"
        assert "  hooks: 99%" in facts["lines"]

    def test_a_failing_test_path_names_its_branch(self):
        assert triage.triage_log(PYTEST_LOG)["owners"] == ["spawn"]

    def test_an_owner_before_the_shown_lines_is_still_named(self):
        noise = "test (3.12)\tRun tests\t2026-10-23T05:31:00.0Z Error: traceback line\n" * triage.MAX_FAILING_LINES
        facts = triage.triage_log(AUDIT_LOG + noise)
        assert facts["owners"] == ["hooks"]
        assert len(facts["lines"]) == triage.MAX_FAILING_LINES

    def test_infra_is_a_cancel_or_a_setup_step_never_a_test_step(self):
        assert triage.is_infra("cancelled", "Run tests") is True
        assert triage.is_infra("failure", "Set up job") is True
        assert triage.is_infra("failure", "Run tests") is False


class TestReplyShapes:
    def test_owner_reply_splits_into_files_changelog_and_note(self):
        reply = replies.parse_owner_reply(OWNER_REPLY)
        assert reply["files"] == ["src/aipass/hooks/.seedgo/bypass.json"]
        assert reply["changelog"] == "- **hooks bypass lines re-pinned** (@hooks)"
        assert reply["note"] == "The lines moved; re-pointed."

    def test_owner_reply_without_files_block_answers_none(self):
        assert replies.parse_owner_reply("NOTE:\nnothing to change")["files"] is None

    def test_verdict_reads_only_a_first_line_in_the_contract_shape(self):
        assert replies.parse_verdict("VERDICT: HELD\nsilences the test") == {
            "verdict": "HELD",
            "body": "silences the test",
        }
        assert replies.parse_verdict("VERDICT: OK\nlesson") == {"verdict": "OK", "body": "lesson"}
        assert replies.parse_verdict("Looks fine\nVERDICT: OK") is None

    def test_changelog_bullet_goes_first_under_unreleased_fixed(self, tmp_path):
        text = _changelog(tmp_path).read_text(encoding="utf-8")
        updated = replies.insert_changelog_bullet(text, "- new") or ""
        assert "### Fixed\n\n- new\n- older bullet" in updated
        assert replies.insert_changelog_bullet("# Changelog\n", "- new") is None


class TestPoll:
    def test_a_new_red_wakes_its_owner_with_the_failing_lines(self, ci_lane):
        _dispatched_hooks_red(ci_lane)
        [mail] = ci_lane.mails
        assert mail["to_branch"] == "@hooks" and mail["auto_execute"] is True
        assert "hooks: 99%" in mail["message"] and "You have no git" in mail["message"]
        assert "https://github.com/AIOSAI/AIPass/actions/runs/900" in mail["message"]
        assert ci_lane.wakes[0][0] == "@hooks" and ci_lane.wakes[0][1]["sender"] == "@trigger"
        assert ci_lane.ledger()["cures"]["900@hooks"]["state"] == "dispatched"
        assert [f["extra"]["state"] for f in ci_lane.feed] == ["red", "dispatched"]
        assert all(f["kind"] == "system" and f["source"] == "ci" for f in ci_lane.feed)

    def test_a_second_poll_does_not_dispatch_the_same_red_again(self, ci_lane):
        _dispatched_hooks_red(ci_lane)
        ci.handle_command("ci", ["poll"])
        assert len(ci_lane.mails) == 1

    def test_an_older_red_is_superseded_by_a_newer_run_and_never_dispatched(self, ci_lane):
        ci_lane.add_run("900", created="2026-10-23T05:00:00Z")
        ci_lane.add_run("901", conclusion="success", created="2026-10-23T06:00:00Z")
        ci.poll()
        assert ci_lane.ledger()["runs"]["900"]["verdict"] == "superseded"
        assert ci_lane.mails == [] and ci_lane.feed == []

    def test_a_queued_cure_of_a_superseded_red_never_wakes(self, ci_lane):
        ci_lane.awake = [{"target": "@flow"}, {"target": "@memory"}]
        _dispatched_hooks_red(ci_lane)
        ci_lane.awake = []
        ci_lane.add_run("901", conclusion="success", created="2026-10-23T06:00:00Z")
        ci.poll()
        assert ci_lane.ledger()["cures"]["900@hooks"]["state"] == "superseded"
        assert ci_lane.mails == []

    def test_a_gated_cure_dispatches_on_the_first_poll_after_the_gate_opens(self, ci_lane):
        _mute_hooks(ci_lane)
        _dispatched_hooks_red(ci_lane)
        ci.poll()
        assert ci_lane.ledger()["cures"]["900@hooks"]["state"] == "gated" and ci_lane.mails == []
        _mute_hooks(ci_lane, muted=False)
        ci.poll()
        assert ci_lane.ledger()["cures"]["900@hooks"]["state"] == "dispatched"
        assert [m["to_branch"] for m in ci_lane.mails] == ["@hooks"]

    def test_a_gated_cure_never_dispatches_twice(self, ci_lane):
        _mute_hooks(ci_lane)
        _dispatched_hooks_red(ci_lane)
        _mute_hooks(ci_lane, muted=False)
        ci.poll()
        ci.poll()
        assert [w[0] for w in ci_lane.wakes] == ["@hooks"]

    def test_a_gated_cure_of_a_superseded_red_closes_without_a_dispatch(self, ci_lane):
        _mute_hooks(ci_lane)
        _dispatched_hooks_red(ci_lane)
        _mute_hooks(ci_lane, muted=False)
        ci_lane.add_run("901", conclusion="success", created="2026-10-23T06:00:00Z")
        ci.poll()
        assert ci_lane.ledger()["cures"]["900@hooks"]["state"] == "superseded"
        assert ci_lane.mails == [] and ci_lane.wakes == []

    def test_a_poll_overlapping_another_reads_and_wakes_a_red_once(self, ci_lane):
        class _Overlap(dict):
            def get(self, key, default=None):
                if not getattr(self, "ran", False):
                    self.ran = True
                    ci.poll()
                return super().get(key, default)

        ci_lane.logs = _Overlap({"900": AUDIT_LOG})
        ci_lane.add_run("900", created="2026-10-23T05:00:00Z")
        ci.poll()
        assert [c for c in ci_lane.calls if c[1:3] == ["run", "view"]] == [
            ["@git", "run", "view", "900", "--log-failed"]
        ]
        assert [m["to_branch"] for m in ci_lane.mails] == ["@hooks"]

    def test_a_claim_left_by_a_dead_poll_is_taken_over(self, ci_lane):
        stale = {"claimed": "2026-01-01T00:00:00Z", "workflow": "CI", "step": "audit", "lines": ["hooks: 99%"]}
        runs = {"900": {"verdict": "triaging", "triaged": True, **stale}}
        cures = {"800@hooks": {"run_id": "800", "owner": "hooks", "state": "dispatching", **stale}}
        (ci_lane.root / "ci_ledger.json").write_text(json.dumps({"runs": runs, "cures": cures}), encoding="utf-8")
        ci_lane.add_run("900", created="2026-10-23T05:00:00Z")
        ci_lane.logs["900"] = AUDIT_LOG
        ci.poll()
        assert {c["run_id"]: c["state"] for c in ci_lane.ledger()["cures"].values()} == {
            "800": "dispatched",
            "900": "dispatched",
        }

    def test_a_first_time_green_sends_nothing(self, ci_lane):
        ci_lane.add_run("901", conclusion="success")
        ci.poll()
        assert ci_lane.ledger()["runs"]["901"]["verdict"] == "green"
        assert ci_lane.mails == [] and ci_lane.feed == []

    def test_an_infra_red_gets_a_feed_event_and_no_dispatch(self, ci_lane):
        ci_lane.add_run("902")
        ci_lane.logs["902"] = SETUP_LOG
        ci.poll()
        assert ci_lane.ledger()["runs"]["902"]["verdict"] == "infra"
        assert ci_lane.mails == [] and ci_lane.wakes == []
        assert [f["extra"]["state"] for f in ci_lane.feed] == ["red"]

    def test_an_unowned_red_mails_devpulse_the_excerpt(self, ci_lane):
        ci_lane.add_run("903")
        ci_lane.logs["903"] = UNOWNED_LOG
        ci.poll()
        [mail] = ci_lane.mails
        assert mail["to_branch"] == "@devpulse" and "Process completed" in mail["message"]
        assert ci_lane.wakes == []
        assert ci_lane.ledger()["runs"]["903"]["verdict"] == "unowned"
        assert ci_lane.feed[-1]["extra"]["state"] == "unowned"

    def test_two_citizens_awake_queues_the_wake_and_the_next_poll_drains_it(self, ci_lane):
        ci_lane.awake = [{"target": "@flow"}, {"target": "@memory"}]
        _dispatched_hooks_red(ci_lane)
        assert ci_lane.ledger()["cures"]["900@hooks"]["state"] == "queued"
        assert ci_lane.mails == []
        ci_lane.awake = [{"target": "@flow", "monitor_alive": False}]
        ci.poll()
        assert ci_lane.ledger()["cures"]["900@hooks"]["state"] == "dispatched"
        assert [m["to_branch"] for m in ci_lane.mails] == ["@hooks"]

    def test_an_unreadable_ledger_fails_the_command(self, ci_lane, capsys):
        (ci_lane.root / "ci_ledger.json").write_text("{torn", encoding="utf-8")
        ci_lane.add_run("901", conclusion="success")
        ci.handle_command("ci", ["poll"])
        _out, err = capsys.readouterr()
        assert "ci ledger unreadable" in err


class TestReply:
    def test_a_reply_with_files_sends_seedgo_the_diff(self, ci_lane):
        _dispatched_hooks_red(ci_lane)
        assert ci.handle_command("ci", ["reply", "900", "@hooks", OWNER_REPLY]) is True
        review = ci_lane.mails[-1]
        assert review["to_branch"] == "@seedgo" and "+cure" in review["message"]
        assert "VERDICT: OK" in review["message"]
        assert ci_lane.ledger()["cures"]["900@hooks"]["state"] == "reviewing"

    def test_a_reply_with_no_files_block_is_held_and_nothing_pushed(self, ci_lane):
        _dispatched_hooks_red(ci_lane)
        ci.take_reply("900", "hooks", "NOTE:\nIt was flaky.")
        held = ci_lane.mails[-1]
        assert held["to_branch"] == "@devpulse" and "no FILES: block" in held["message"]
        assert ci_lane.ledger()["cures"]["900@hooks"]["state"] == "held"
        assert not any(call[1] == "ci-cure" for call in ci_lane.calls)

    def test_a_path_outside_the_owner_tree_is_held(self, ci_lane):
        _dispatched_hooks_red(ci_lane)
        ci.take_reply("900", "hooks", "FILES:\nsrc/aipass/drone/x.py\n")
        assert ci_lane.ledger()["cures"]["900@hooks"]["state"] == "held"
        assert "src/aipass/drone/x.py" in ci_lane.mails[-1]["message"]

    def test_the_review_queues_while_two_citizens_are_awake(self, ci_lane):
        _dispatched_hooks_red(ci_lane)
        ci_lane.awake = [{"target": "@trigger"}, {"target": "@flow"}]
        ci.take_reply("900", "hooks", OWNER_REPLY)
        assert ci_lane.ledger()["cures"]["900@hooks"]["state"] == "review_queued"
        ci_lane.awake = []
        ci.poll()
        assert ci_lane.ledger()["cures"]["900@hooks"]["state"] == "reviewing"
        assert ci_lane.mails[-1]["to_branch"] == "@seedgo"

    def test_a_reply_for_an_unknown_cure_is_refused(self, ci_lane, capsys):
        ci.handle_command("ci", ["reply", "999", "@hooks", OWNER_REPLY])
        _out, err = capsys.readouterr()
        assert "no cure 999@hooks" in err


class TestVerdict:
    def test_ok_appends_the_bullet_and_pushes_through_the_cure_door(self, ci_lane):
        changelog = _reviewing(ci_lane)
        assert ci.take_verdict("900", "hooks", "VERDICT: OK\nchecker learns line pins move") == "pushed"
        [cure_call] = [c for c in ci_lane.calls if c[1] == "ci-cure"]
        assert cure_call[2:4] == ["900", "@hooks"]
        assert cure_call[4] == "fix(hooks): hooks bypass lines re-pinned, run 900"
        assert cure_call[5:] == ["src/aipass/hooks/.seedgo/bypass.json", "CHANGELOG.md"]
        assert "- **hooks bypass lines re-pinned** (@hooks)\n- older bullet" in changelog.read_text(encoding="utf-8")
        cure = ci_lane.ledger()["cures"]["900@hooks"]
        assert cure["state"] == "pushed" and cure["sha"] == "abc1234def"
        assert ci_lane.feed[-1]["extra"]["state"] == "pushed"

    def test_a_refused_door_holds_restores_the_changelog_and_mails_devpulse(self, ci_lane):
        changelog = _reviewing(ci_lane)
        before = changelog.read_text(encoding="utf-8")
        ci_lane.cure_answer = (1, "Unknown git command: ci-cure")
        assert ci.take_verdict("900", "hooks", "VERDICT: OK\nlesson") == "held"
        assert changelog.read_text(encoding="utf-8") == before
        held = ci_lane.mails[-1]
        assert held["to_branch"] == "@devpulse" and "Unknown git command" in held["message"]
        assert "+cure" in held["message"]

    def test_a_commit_whose_push_failed_keeps_the_changelog_and_holds_with_its_sha(self, ci_lane):
        """The door commits before it pushes: restoring then would revert a committed bullet in the tree."""
        changelog = _reviewing(ci_lane)
        ci_lane.cure_answer = (1, "abc1234def\nci-cure committed abc1234def on dev; the push failed: rejected")
        assert ci.take_verdict("900", "hooks", "VERDICT: OK\nlesson") == "held"
        assert "- **hooks bypass lines re-pinned** (@hooks)" in changelog.read_text(encoding="utf-8")
        assert ci_lane.ledger()["cures"]["900@hooks"]["sha"] == "abc1234def"
        assert "abc1234def" in ci_lane.mails[-1]["message"]

    def test_held_mails_devpulse_and_never_calls_the_door(self, ci_lane):
        _reviewing(ci_lane)
        assert ci.take_verdict("900", "hooks", "VERDICT: HELD\nsilences the symptom") == "held"
        assert "silences the symptom" in ci_lane.mails[-1]["message"]
        assert not any(call[1] == "ci-cure" for call in ci_lane.calls)

    def test_a_reply_not_in_the_verdict_shape_changes_nothing(self, ci_lane, capsys):
        _reviewing(ci_lane)
        ci.handle_command("ci", ["verdict", "900", "@hooks", "looks good to me"])
        _out, err = capsys.readouterr()
        assert "VERDICT: OK or VERDICT: HELD" in err
        assert ci_lane.ledger()["cures"]["900@hooks"]["state"] == "reviewing"


class TestProof:
    def test_the_proving_run_gets_one_pushed_note_then_one_green_note(self, ci_lane):
        _reviewing(ci_lane)
        ci.take_verdict("900", "hooks", "VERDICT: OK\nlesson L")
        pushed_at = ci_lane.ledger()["cures"]["900@hooks"]["pushed_at"]
        ci_lane.add_run("950", status="in_progress", conclusion="", created=pushed_at)
        ci.poll()
        note = ci_lane.mails[-1]
        assert note["to_branch"] == "@devpulse" and "run 950 proving it" in note["subject"]
        assert "lesson L" in note["message"]
        ci_lane.runs[-1] = ci_lane.runs[-1].replace("in_progress\t", "completed\tsuccess", 1)
        ci.poll()
        assert "[CI GREEN]" in ci_lane.mails[-1]["subject"]
        assert ci_lane.ledger()["cures"]["900@hooks"]["state"] == "cured"
        count = len(ci_lane.mails)
        ci.poll()
        assert len(ci_lane.mails) == count


class TestCommandSurface:
    def test_help_explains_and_calls_no_drone(self, ci_lane, capsys):
        assert ci.handle_command("ci", ["poll", "--help"]) is True
        out, _err = capsys.readouterr()
        assert "ci reply N @x" in out
        assert ci_lane.calls == []

    def test_status_prints_the_ledger_cures(self, ci_lane, capsys):
        _dispatched_hooks_red(ci_lane)
        capsys.readouterr()
        ci.handle_command("ci", ["status"])
        out, _err = capsys.readouterr()
        assert "run 900 @hooks" in out and "dispatched" in out

    def test_another_module_command_is_not_claimed(self):
        assert ci.handle_command("medic", ["status"]) is False

    def test_the_feed_answers_no_door_when_ai_mail_publishes_none(self, ci_lane, monkeypatch):
        monkeypatch.delattr(ai_mail_pkg, "send_notification")
        assert outbound.feed("red", "t", "b", run_id="1") == "no_door"

    def test_the_ledger_lives_on_its_own_name(self, ci_lane):
        _dispatched_hooks_red(ci_lane)
        assert json.loads((ci_lane.root / "ci_ledger.json").read_text(encoding="utf-8"))["version"] == 1
