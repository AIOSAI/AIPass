"""Tests for the fleet inbox sweep — stale unread mail detection and waking."""

import json
import shutil
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from aipass.daemon.apps.handlers.monitoring.inbox_scanner import (
    DEFAULT_STALE_HOURS,
    SKIP_MANAGER,
    _parse_timestamp,
    find_stale_inboxes,
    scan_branch_inbox,
)
from aipass.daemon.apps.modules import inbox_sweep
from aipass.daemon.apps.modules.inbox_sweep import SKIP_BLOCKLIST


NOW = datetime(2026, 8, 11, 12, 0, 0)

SCANNER = "aipass.daemon.apps.handlers.monitoring.inbox_scanner"


# ── Fixtures ──────────────────────────────────────────


@pytest.fixture
def branch_dir():
    """A temp branch directory with .ai_mail.local/ and .trinity/."""
    root = Path(tempfile.mkdtemp())
    (root / ".ai_mail.local").mkdir(parents=True)
    (root / ".trinity").mkdir(parents=True)
    yield root
    shutil.rmtree(root)


def write_inbox(branch: Path, messages: list) -> None:
    """Write an inbox.json with the given messages."""
    payload = {
        "mailbox": "inbox",
        "total_messages": len(messages),
        "unread_count": sum(1 for m in messages if m.get("status") == "new"),
        "messages": messages,
    }
    (branch / ".ai_mail.local" / "inbox.json").write_text(json.dumps(payload), encoding="utf-8")


def write_passport(branch: Path, citizen_class: str) -> None:
    """Write a minimal passport.json with the given citizen_class."""
    payload = {"identity": {"citizen_class": citizen_class}}
    (branch / ".trinity" / "passport.json").write_text(json.dumps(payload), encoding="utf-8")


def message(hours_ago: float, status: str = "new", subject: str = "A subject") -> dict:
    """Build an inbox message sent `hours_ago` before NOW."""
    sent = NOW - timedelta(hours=hours_ago)
    return {
        "id": f"id{int(hours_ago)}",
        "timestamp": sent.strftime("%Y-%m-%d %H:%M:%S"),
        "from": "@devpulse",
        "subject": subject,
        "status": status,
    }


def entry(owner: str, age: float = 48.0, skip_reason=None, stale_count: int = 1) -> dict:
    """Build a scanner entry dict as the sweep module consumes it."""
    return {
        "owner": owner,
        "branch": owner.lstrip("@"),
        "path": f"/tmp/{owner.lstrip('@')}",
        "unread_total": stale_count,
        "stale_count": stale_count,
        "oldest_age_hours": age,
        "oldest_from": "@devpulse",
        "oldest_subject": "A subject",
        "skip_reason": skip_reason,
    }


# ── _parse_timestamp ──────────────────────────────────


class TestParseTimestamp:
    def test_ai_mail_format(self):
        assert _parse_timestamp("2026-08-11 10:52:55") == datetime(2026, 8, 11, 10, 52, 55)

    def test_iso_format_fallback(self):
        assert _parse_timestamp("2026-08-11T10:52:55") == datetime(2026, 8, 11, 10, 52, 55)

    def test_garbage_returns_none(self):
        assert _parse_timestamp("not a date") is None

    def test_empty_returns_none(self):
        assert _parse_timestamp("") is None


# ── scan_branch_inbox ─────────────────────────────────


class TestScanBranchInbox:
    def test_stale_unread_is_reported(self, branch_dir):
        write_inbox(branch_dir, [message(48)])
        result = scan_branch_inbox(branch_dir, "@test", now=NOW)
        assert result is not None
        assert result["stale_count"] == 1
        assert result["oldest_age_hours"] == 48.0
        assert result["owner"] == "@test"

    def test_fresh_unread_is_ignored(self, branch_dir):
        write_inbox(branch_dir, [message(2)])
        assert scan_branch_inbox(branch_dir, "@test", now=NOW) is None

    def test_opened_mail_is_ignored(self, branch_dir):
        write_inbox(branch_dir, [message(72, status="opened")])
        assert scan_branch_inbox(branch_dir, "@test", now=NOW) is None

    def test_exactly_at_threshold_counts_as_stale(self, branch_dir):
        write_inbox(branch_dir, [message(DEFAULT_STALE_HOURS)])
        assert scan_branch_inbox(branch_dir, "@test", now=NOW) is not None

    def test_oldest_message_drives_the_entry(self, branch_dir):
        write_inbox(branch_dir, [message(30, subject="newer"), message(96, subject="oldest")])
        result = scan_branch_inbox(branch_dir, "@test", now=NOW)
        assert result is not None
        assert result["stale_count"] == 2
        assert result["oldest_subject"] == "oldest"
        assert result["oldest_age_hours"] == 96.0

    def test_mixed_fresh_and_stale_counts_only_stale(self, branch_dir):
        write_inbox(branch_dir, [message(2), message(48)])
        result = scan_branch_inbox(branch_dir, "@test", now=NOW)
        assert result is not None
        assert result["stale_count"] == 1
        assert result["unread_total"] == 2

    def test_custom_threshold(self, branch_dir):
        write_inbox(branch_dir, [message(5)])
        assert scan_branch_inbox(branch_dir, "@test", now=NOW, stale_hours=4) is not None
        assert scan_branch_inbox(branch_dir, "@test", now=NOW, stale_hours=8) is None

    def test_missing_inbox_returns_none(self, branch_dir):
        assert scan_branch_inbox(branch_dir, "@test", now=NOW) is None

    def test_malformed_json_returns_none(self, branch_dir):
        (branch_dir / ".ai_mail.local" / "inbox.json").write_text("{not json", encoding="utf-8")
        assert scan_branch_inbox(branch_dir, "@test", now=NOW) is None

    def test_missing_messages_key_returns_none(self, branch_dir):
        (branch_dir / ".ai_mail.local" / "inbox.json").write_text('{"mailbox": "inbox"}', encoding="utf-8")
        assert scan_branch_inbox(branch_dir, "@test", now=NOW) is None

    def test_unparseable_timestamp_is_skipped_not_fatal(self, branch_dir):
        broken = message(48)
        broken["timestamp"] = "whenever"
        write_inbox(branch_dir, [broken, message(72)])
        result = scan_branch_inbox(branch_dir, "@test", now=NOW)
        assert result is not None
        assert result["stale_count"] == 1

    def test_manager_branch_is_flagged_skip(self, branch_dir):
        write_inbox(branch_dir, [message(48)])
        write_passport(branch_dir, "manager")
        result = scan_branch_inbox(branch_dir, "@boss", now=NOW)
        assert result is not None
        assert result["skip_reason"] == SKIP_MANAGER

    def test_non_manager_branch_is_wakeable(self, branch_dir):
        write_inbox(branch_dir, [message(48)])
        write_passport(branch_dir, "aipass_framework")
        result = scan_branch_inbox(branch_dir, "@test", now=NOW)
        assert result is not None
        assert result["skip_reason"] is None

    def test_missing_passport_is_wakeable(self, branch_dir):
        write_inbox(branch_dir, [message(48)])
        result = scan_branch_inbox(branch_dir, "@test", now=NOW)
        assert result is not None
        assert result["skip_reason"] is None


# ── find_stale_inboxes ────────────────────────────────


class TestFindStaleInboxes:
    def test_sorted_oldest_first(self, branch_dir):
        newer = branch_dir / "newer"
        older = branch_dir / "older"
        for path, hours in ((newer, 30), (older, 100)):
            (path / ".ai_mail.local").mkdir(parents=True)
            write_inbox(path, [message(hours)])

        with patch(f"{SCANNER}.active_branch_map", return_value={"newer": "@newer", "older": "@older"}):
            with patch(f"{SCANNER}.branch_path_for", side_effect=lambda name: branch_dir / name):
                entries = find_stale_inboxes(now=NOW)

        assert [e["owner"] for e in entries] == ["@older", "@newer"]

    def test_empty_registry_returns_empty(self):
        with patch(f"{SCANNER}.active_branch_map", return_value={}):
            assert find_stale_inboxes(now=NOW) == []

    def test_clean_fleet_returns_empty(self, branch_dir):
        (branch_dir / "clean" / ".ai_mail.local").mkdir(parents=True)
        write_inbox(branch_dir / "clean", [message(2)])
        with patch(f"{SCANNER}.active_branch_map", return_value={"clean": "@clean"}):
            with patch(f"{SCANNER}.branch_path_for", side_effect=lambda name: branch_dir / name):
                assert find_stale_inboxes(now=NOW) == []


# ── run_sweep ─────────────────────────────────────────


class TestRunSweep:
    def test_no_stale_mail_wakes_nobody(self):
        with patch.object(inbox_sweep, "find_stale_inboxes", return_value=[]):
            with patch.object(inbox_sweep, "_wake_owner") as wake:
                results = inbox_sweep.run_sweep()
        assert results["stale_branches"] == 0
        assert results["woken"] == 0
        wake.assert_not_called()

    def test_dry_run_wakes_nobody(self):
        with patch.object(inbox_sweep, "find_stale_inboxes", return_value=[entry("@a"), entry("@b")]):
            with patch.object(inbox_sweep, "_wake_owner") as wake:
                results = inbox_sweep.run_sweep(dry_run=True)
        wake.assert_not_called()
        assert results["wakeable"] == 2
        assert results["wake_targets"] == ["@a", "@b"]
        assert results["woken"] == 0

    def test_wakes_each_wakeable_branch_once(self):
        entries = [entry("@a"), entry("@b")]
        with patch.object(inbox_sweep, "find_stale_inboxes", return_value=entries):
            with patch.object(inbox_sweep, "_wake_owner", return_value=(True, "ok")) as wake:
                with patch.object(inbox_sweep.time, "sleep"):
                    results = inbox_sweep.run_sweep()
        assert wake.call_count == 2
        assert results["woken"] == 2
        assert [c.args[0]["owner"] for c in wake.call_args_list] == ["@a", "@b"]

    def test_managers_are_never_woken(self):
        entries = [entry("@boss", skip_reason=SKIP_MANAGER), entry("@a")]
        with patch.object(inbox_sweep, "find_stale_inboxes", return_value=entries):
            with patch.object(inbox_sweep, "_wake_owner", return_value=(True, "ok")) as wake:
                results = inbox_sweep.run_sweep()
        assert wake.call_count == 1
        assert wake.call_args.args[0]["owner"] == "@a"
        assert results["skipped"] == 1
        assert results["skipped_targets"] == ["@boss (manager)"]

    def test_limit_defers_rest_without_dropping_them(self):
        entries = [entry(f"@b{i}") for i in range(4)]
        with patch.object(inbox_sweep, "find_stale_inboxes", return_value=entries):
            with patch.object(inbox_sweep, "_wake_owner", return_value=(True, "ok")) as wake:
                with patch.object(inbox_sweep.time, "sleep"):
                    results = inbox_sweep.run_sweep(limit=2)
        assert wake.call_count == 2
        assert results["deferred"] == 2
        assert results["deferred_targets"] == ["@b2", "@b3"]

    def test_wake_failure_is_counted_not_fatal(self):
        entries = [entry("@a"), entry("@b")]
        with patch.object(inbox_sweep, "find_stale_inboxes", return_value=entries):
            with patch.object(inbox_sweep, "_wake_owner", side_effect=[(False, "locked"), (True, "ok")]):
                with patch.object(inbox_sweep.time, "sleep"):
                    results = inbox_sweep.run_sweep()
        assert results["woken"] == 1
        assert results["failed"] == 1

    def test_stale_hours_is_passed_through(self):
        with patch.object(inbox_sweep, "find_stale_inboxes", return_value=[]) as find:
            inbox_sweep.run_sweep(stale_hours=72)
        assert find.call_args.kwargs["stale_hours"] == 72


# ── _apply_wake_policy ────────────────────────────────


class TestApplyWakePolicy:
    """The blocklist is wake policy — stamped by the module, not the scanner."""

    def test_blocklisted_owner_is_flagged(self):
        entries = [entry("@devpulse"), entry("@a")]
        with patch.dict(
            "sys.modules",
            {
                "aipass.ai_mail.apps.handlers.dispatch.wake": MagicMock(
                    is_wake_blocked=lambda owner: owner == "@devpulse"
                )
            },
        ):
            inbox_sweep._apply_wake_policy(entries)
        assert entries[0]["skip_reason"] == SKIP_BLOCKLIST
        assert entries[1]["skip_reason"] is None

    def test_existing_skip_reason_is_not_overwritten(self):
        entries = [entry("@boss", skip_reason=SKIP_MANAGER)]
        with patch.dict(
            "sys.modules",
            {"aipass.ai_mail.apps.handlers.dispatch.wake": MagicMock(is_wake_blocked=lambda owner: True)},
        ):
            inbox_sweep._apply_wake_policy(entries)
        assert entries[0]["skip_reason"] == SKIP_MANAGER

    def test_real_blocklist_catches_devpulse(self):
        entries = [entry("@devpulse")]
        inbox_sweep._apply_wake_policy(entries)
        assert entries[0]["skip_reason"] == SKIP_BLOCKLIST

    def test_blocklisted_branch_is_never_woken(self):
        entries = [entry("@devpulse"), entry("@a")]
        with patch.object(inbox_sweep, "find_stale_inboxes", return_value=entries):
            with patch.object(inbox_sweep, "_wake_owner", return_value=(True, "ok")) as wake:
                results = inbox_sweep.run_sweep()
        assert wake.call_count == 1
        assert wake.call_args.args[0]["owner"] == "@a"
        assert results["skipped_targets"] == [f"@devpulse ({SKIP_BLOCKLIST})"]


# ── _wake_owner ───────────────────────────────────────


class TestWakeOwner:
    def test_wake_uses_daemon_sender_and_light_model(self):
        status = MagicMock()
        status.summary = "spawned"
        wake_branch = MagicMock(return_value=(status, True))
        with patch.dict(
            "sys.modules",
            {"aipass.ai_mail.apps.handlers.dispatch.wake": MagicMock(wake_branch=wake_branch)},
        ):
            ok, detail = inbox_sweep._wake_owner(entry("@a"))
        assert ok is True
        assert detail == "spawned"
        kwargs = wake_branch.call_args.kwargs
        assert kwargs["sender"] == "@daemon"
        assert kwargs["auto"] is True
        assert kwargs["fresh"] is True
        assert kwargs["model"] == inbox_sweep.WAKE_MODEL

    def test_wake_exception_is_caught(self):
        wake_branch = MagicMock(side_effect=RuntimeError("boom"))
        with patch.dict(
            "sys.modules",
            {"aipass.ai_mail.apps.handlers.dispatch.wake": MagicMock(wake_branch=wake_branch)},
        ):
            ok, detail = inbox_sweep._wake_owner(entry("@a"))
        assert ok is False
        assert "boom" in detail

    def test_wake_message_names_the_backlog(self):
        text = inbox_sweep._wake_message(entry("@a", age=48.0, stale_count=3))
        assert "3 unread emails" in text
        assert "48h old" in text


# ── CLI routing ───────────────────────────────────────


class TestCliRouting:
    def test_foreign_command_not_handled(self):
        assert inbox_sweep.handle_command("queue", []) is False

    def test_help_flag_prints_help_without_sweeping(self):
        with patch.object(inbox_sweep, "run_sweep") as sweep:
            assert inbox_sweep.handle_command("inbox-sweep", ["--help"]) is True
        sweep.assert_not_called()

    def test_bare_command_runs_sweep(self):
        with patch.object(inbox_sweep, "run_sweep", return_value={}) as sweep:
            assert inbox_sweep.handle_command("inbox-sweep", []) is True
        assert sweep.call_args.kwargs["dry_run"] is False

    def test_underscore_alias_routes(self):
        with patch.object(inbox_sweep, "run_sweep", return_value={}):
            assert inbox_sweep.handle_command("inbox_sweep", []) is True

    def test_flags_are_parsed(self):
        with patch.object(inbox_sweep, "run_sweep", return_value={}) as sweep:
            inbox_sweep.handle_command("inbox-sweep", ["--dry-run", "--hours", "48", "--limit", "2"])
        kwargs = sweep.call_args.kwargs
        assert kwargs == {"dry_run": True, "stale_hours": 48, "limit": 2}

    def test_bad_flag_value_falls_back_to_default(self):
        with patch.object(inbox_sweep, "run_sweep", return_value={}) as sweep:
            inbox_sweep.handle_command("inbox-sweep", ["--hours", "soon"])
        assert sweep.call_args.kwargs["stale_hours"] == DEFAULT_STALE_HOURS

    def test_dangling_flag_falls_back_to_default(self):
        with patch.object(inbox_sweep, "run_sweep", return_value={}) as sweep:
            inbox_sweep.handle_command("inbox-sweep", ["--limit"])
        assert sweep.call_args.kwargs["limit"] == inbox_sweep.MAX_WAKES


# ── Schedule entry ────────────────────────────────────


class TestScheduleEntry:
    """The daemon's own .daemon/schedule.json must survive discovery validation."""

    def test_schedule_file_is_a_valid_job(self):
        from aipass.daemon.apps.handlers.schedule.discovery import _validate_job

        schedule_file = Path(__file__).resolve().parents[1] / ".daemon" / "schedule.json"
        data = json.loads(schedule_file.read_text(encoding="utf-8"))

        assert data["branch"] == "@daemon"
        jobs = [j for j in data["jobs"] if j["id"] == "inbox-sweep"]
        assert len(jobs) == 1

        job = jobs[0]
        assert _validate_job(job, schedule_file) is True
        assert job["enabled"] is True
        assert job["schedule"]["type"] == "daily"
        assert "inbox-sweep" in job["prompt"]
