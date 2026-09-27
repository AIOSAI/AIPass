# =================== AIPass ====================
# Name: test_inbox_sweep.py
# Description: Fleet inbox sweep tests — stale unread mail detection, wake policy and waking
# Version: 1.1.0
# Created: 2026-08-11
# Modified: 2026-09-27
# =============================================

"""Tests for apps/modules/inbox_sweep.py and the handlers/monitoring/inbox_scanner.py it drives."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(external) — wake_branch's own spawn and blocklist file; @ai_mail's dispatch tests
# seedgo: no-test-needed(constant) — MAX_WAKES, WAKE_MODEL and the help and introspection text

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
    find_stale_inboxes,
    scan_branch_inbox,
)
from aipass.daemon.apps.handlers.schedule.discovery import discover_jobs
from aipass.daemon.apps.modules import inbox_sweep
from aipass.daemon.apps.modules.inbox_sweep import SKIP_BLOCKLIST


NOW = datetime(2026, 8, 11, 12, 0, 0)

SCANNER = "aipass.daemon.apps.handlers.monitoring.inbox_scanner"
DISCOVERY = "aipass.daemon.apps.handlers.schedule.discovery"
WAKE = "aipass.ai_mail.apps.handlers.dispatch.wake"


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
        "path": str(Path(tempfile.gettempdir()) / owner.lstrip("@")),
        "unread_total": stale_count,
        "stale_count": stale_count,
        "oldest_age_hours": age,
        "oldest_from": "@devpulse",
        "oldest_subject": "A subject",
        "skip_reason": skip_reason,
    }


# ── message timestamps, through scan_branch_inbox ─────


def oldest_age_beside(branch: Path, timestamp: str) -> float:
    """oldest_age_hours for an unread message stamped `timestamp`, beside one sent 30h before NOW."""
    stamped = message(0)
    stamped["timestamp"] = timestamp
    write_inbox(branch, [stamped, message(30)])
    return scan_branch_inbox(branch, "@test", now=NOW)["oldest_age_hours"]


class TestParseTimestamp:
    def test_ai_mail_format(self, branch_dir):
        assert oldest_age_beside(branch_dir, "2026-08-09 12:00:00") == 48.0

    def test_iso_format_fallback(self, branch_dir):
        """Mutant killed: _parse_timestamp returns None instead of trying datetime.fromisoformat."""
        assert oldest_age_beside(branch_dir, "2026-08-09T12:00:00") == 48.0

    def test_garbage_returns_none(self, branch_dir):
        """Mutant killed: the fromisoformat except (ValueError, TypeError) removed from _parse_timestamp."""
        assert oldest_age_beside(branch_dir, "not a date") == 30.0

    def test_empty_returns_none(self, branch_dir):
        assert oldest_age_beside(branch_dir, "") == 30.0


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
        """Mutant killed: age_hours >= stale_hours narrowed to > in scan_branch_inbox."""
        write_inbox(branch_dir, [message(DEFAULT_STALE_HOURS)])
        result = scan_branch_inbox(branch_dir, "@test", now=NOW)
        assert result["stale_count"] == 1
        assert result["oldest_age_hours"] == float(DEFAULT_STALE_HOURS)

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
        """Mutant killed: scan_branch_inbox compares against DEFAULT_STALE_HOURS, ignoring stale_hours."""
        assert scan_branch_inbox(branch_dir, "@test", now=NOW, stale_hours=4)["stale_count"] == 1
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
        """Mutant killed: _skip_reason returns SKIP_MANAGER for any readable passport."""
        write_passport(branch_dir, "aipass_framework")
        result = scan_branch_inbox(branch_dir, "@test", now=NOW)
        assert {key: result[key] for key in ("owner", "skip_reason")} == {"owner": "@test", "skip_reason": None}

    def test_missing_passport_is_wakeable(self, branch_dir):
        """Mutant killed: _skip_reason returns SKIP_MANAGER when the passport is unreadable."""
        write_inbox(branch_dir, [message(48)])
        result = scan_branch_inbox(branch_dir, "@test", now=NOW)
        assert {key: result[key] for key in ("owner", "skip_reason")} == {"owner": "@test", "skip_reason": None}


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


# ── fleet scope: a citizen is a citizen (FPLAN-0492 ruling 6, todo 188) ──


class TestSweepScopeIsTheWholeFleet:
    """The sweep looks wherever the fleet definition looks — no second registry.

    Ruled 2026-09-07: projects/* citizens must not be invisible to the sweep.
    MEASURED on this machine the same morning: they already are not. The scan
    walks active_branch_map() -> active_citizens() -> @memory's
    fleet.fleet_branches(), which covers src/aipass/*, projects/*/ and the
    federated externals alike — 28 citizens, 18 core + 4 under projects/ + 6
    external, and the 08:48 sweep listed @baud, @finch, @earmark and
    @aipass_site among its stale mailboxes. FPLAN-0460 moved that scope in when
    it deleted daemon's private copy of the registry read.

    These pins exist so the scope cannot silently narrow back to core-only:
    that regression would look like nothing at all until a project citizen sat
    on unread mail for a week.
    """

    FLEET = "aipass.daemon.apps.handlers.schedule.discovery.fleet"

    def test_a_projects_citizen_is_scanned(self, branch_dir):
        resident = branch_dir / "earmark"
        (resident / ".ai_mail.local").mkdir(parents=True)
        write_inbox(resident, [message(48)])

        fake = [{"name": "earmark", "path": resident, "registry": "EARMARK_REGISTRY.json", "email": "@earmark"}]
        with (
            patch(f"{self.FLEET}.fleet_branches", return_value=fake),
            patch(f"{self.FLEET}.declared_residency", return_value="resident"),
        ):
            entries = find_stale_inboxes(now=NOW)

        assert [e["owner"] for e in entries] == ["@earmark"]

    def test_the_scanner_reads_no_registry_of_its_own(self, branch_dir):
        """An empty fleet means an empty sweep — nothing else can add a branch."""
        with patch(f"{self.FLEET}.fleet_branches", return_value=[]):
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

    def test_wakes_each_wakeable_branch_once(self, monkeypatch):
        monkeypatch.setattr(inbox_sweep, "WAKE_STAGGER_SECONDS", 0)
        entries = [entry("@a"), entry("@b")]
        with patch.object(inbox_sweep, "find_stale_inboxes", return_value=entries):
            with patch.object(inbox_sweep, "_wake_owner", return_value=(True, "ok")) as wake:
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

    def test_limit_defers_rest_without_dropping_them(self, monkeypatch):
        monkeypatch.setattr(inbox_sweep, "WAKE_STAGGER_SECONDS", 0)
        entries = [entry(f"@b{i}") for i in range(4)]
        with patch.object(inbox_sweep, "find_stale_inboxes", return_value=entries):
            with patch.object(inbox_sweep, "_wake_owner", return_value=(True, "ok")) as wake:
                results = inbox_sweep.run_sweep(limit=2)
        assert wake.call_count == 2
        assert results["deferred"] == 2
        assert results["deferred_targets"] == ["@b2", "@b3"]

    def test_wake_failure_is_counted_not_fatal(self, monkeypatch):
        monkeypatch.setattr(inbox_sweep, "WAKE_STAGGER_SECONDS", 0)
        entries = [entry("@a"), entry("@b")]
        with patch.object(inbox_sweep, "find_stale_inboxes", return_value=entries):
            with patch.object(inbox_sweep, "_wake_owner", side_effect=[(False, "locked"), (True, "ok")]):
                results = inbox_sweep.run_sweep()
        assert results["woken"] == 1
        assert results["failed"] == 1

    def test_stale_hours_is_passed_through(self):
        with patch.object(inbox_sweep, "find_stale_inboxes", return_value=[]) as find:
            inbox_sweep.run_sweep(stale_hours=72)
        assert find.call_args.kwargs["stale_hours"] == 72


# ── wake policy, through run_sweep ────────────────────


class TestApplyWakePolicy:
    """The blocklist is wake policy — stamped by the module, not the scanner."""

    def test_blocklisted_owner_is_flagged(self):
        """Mutant killed: _apply_wake_policy never stamps SKIP_BLOCKLIST."""
        entries = [entry("@devpulse"), entry("@a")]
        with (
            patch.object(inbox_sweep, "find_stale_inboxes", return_value=entries),
            patch(f"{WAKE}.is_wake_blocked", side_effect=lambda owner: owner == "@devpulse"),
        ):
            results = inbox_sweep.run_sweep(dry_run=True)
        assert results["skipped_targets"] == [f"@devpulse ({SKIP_BLOCKLIST})"]
        assert results["wake_targets"] == ["@a"]

    def test_existing_skip_reason_is_not_overwritten(self):
        """Mutant killed: _apply_wake_policy stamps the blocklist over an existing skip_reason."""
        entries = [entry("@boss", skip_reason=SKIP_MANAGER)]
        with (
            patch.object(inbox_sweep, "find_stale_inboxes", return_value=entries),
            patch(f"{WAKE}.is_wake_blocked", side_effect=lambda owner: owner == "@boss"),
        ):
            results = inbox_sweep.run_sweep(dry_run=True)
        assert results["skipped_targets"] == [f"@boss ({SKIP_MANAGER})"]

    def test_real_blocklist_catches_devpulse(self):
        with patch.object(inbox_sweep, "find_stale_inboxes", return_value=[entry("@devpulse")]):
            results = inbox_sweep.run_sweep(dry_run=True)
        assert results["skipped_targets"] == [f"@devpulse ({SKIP_BLOCKLIST})"]
        assert results["wake_targets"] == []

    def test_blocklisted_branch_is_never_woken(self):
        entries = [entry("@devpulse"), entry("@a")]
        with patch.object(inbox_sweep, "find_stale_inboxes", return_value=entries):
            with patch.object(inbox_sweep, "_wake_owner", return_value=(True, "ok")) as wake:
                results = inbox_sweep.run_sweep()
        assert wake.call_count == 1
        assert wake.call_args.args[0]["owner"] == "@a"
        assert results["skipped_targets"] == [f"@devpulse ({SKIP_BLOCKLIST})"]


# ── waking an owner, through run_sweep ────────────────


class TestWakeOwner:
    def test_wake_uses_daemon_sender_and_light_model(self, capsys):
        """Mutant killed: _wake_owner sends as a sender other than @daemon."""
        status = MagicMock()
        status.summary = "spawned"
        with (
            patch.object(inbox_sweep, "find_stale_inboxes", return_value=[entry("@a")]),
            patch(f"{WAKE}.wake_branch", return_value=(status, True)) as wake_branch,
        ):
            results = inbox_sweep.run_sweep()
        assert results["woken"] == 1
        assert "OK: @a — spawned" in capsys.readouterr().out
        assert wake_branch.call_args.args == ("@a",)
        kwargs = wake_branch.call_args.kwargs
        assert kwargs["sender"] == "@daemon"
        assert kwargs["auto"] is True
        assert kwargs["fresh"] is True
        assert kwargs["model"] == inbox_sweep.WAKE_MODEL
        assert kwargs["wake_back"] is False, "a nudge must never wake @daemon back"

    def test_wake_exception_is_caught(self, capsys):
        """Mutant killed: _wake_owner's except Exception narrowed so the error escapes run_sweep."""
        with (
            patch.object(inbox_sweep, "find_stale_inboxes", return_value=[entry("@a")]),
            patch(f"{WAKE}.wake_branch", side_effect=RuntimeError("boom")),
        ):
            results = inbox_sweep.run_sweep()
        assert (results["woken"], results["failed"]) == (0, 1)
        assert "ERROR: @a — boom" in capsys.readouterr().out

    def test_wake_message_names_the_backlog(self):
        """Mutant killed: _wake_owner passes an empty custom_message."""
        status = MagicMock()
        status.summary = "spawned"
        with (
            patch.object(inbox_sweep, "find_stale_inboxes", return_value=[entry("@a", age=48.0, stale_count=3)]),
            patch(f"{WAKE}.wake_branch", return_value=(status, True)) as wake_branch,
        ):
            inbox_sweep.run_sweep()
        text = wake_branch.call_args.kwargs["custom_message"]
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
        """Mutant killed: "inbox_sweep" dropped from HANDLED_COMMANDS."""
        with patch.object(inbox_sweep, "run_sweep", return_value={}) as sweep:
            assert inbox_sweep.handle_command("inbox_sweep", []) is True
        sweep.assert_called_once_with(dry_run=False, stale_hours=DEFAULT_STALE_HOURS, limit=inbox_sweep.MAX_WAKES)

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
    """Nothing scheduled runs the inbox sweep (DPLAN-0337 R2, 2026-09-10).

    Was: daemon's own schedule.json carries an enabled daily inbox-sweep job.
    The owner deleted it — up to five wakes every morning — and the nightly rounds
    took inbox-to-zero over. The command is a hand tool now, so the pin inverts:
    no job may carry the name, and no job's prompt may run the command.
    """

    def test_no_job_runs_the_sweep(self, tmp_path):
        schedule_file = Path(__file__).resolve().parents[1] / ".daemon" / "schedule.json"
        data = json.loads(schedule_file.read_text(encoding="utf-8"))

        assert data["branch"] == "@daemon"
        assert data["jobs"], "an empty job list would pass every check below vacuously"
        for job in data["jobs"]:
            assert job["id"] != "inbox-sweep"
            assert "inbox-sweep" not in job.get("prompt", "")
        # Every job in the shipped file passes discovery's validation: a temp tree
        # holding only @daemon, its .daemon/ a copy of the real file.
        daemon_dir = tmp_path / "src" / "aipass" / "daemon" / ".daemon"
        daemon_dir.mkdir(parents=True)
        shutil.copy(schedule_file, daemon_dir / "schedule.json")
        registry = {
            "branches": [{"name": "DAEMON", "email": "@daemon", "path": "src/aipass/daemon", "status": "active"}]
        }
        (tmp_path / "AIPASS_REGISTRY.json").write_text(json.dumps(registry), encoding="utf-8")
        with patch(f"{DISCOVERY}._REPO_ROOT", tmp_path):
            discovered = [job["id"] for job in discover_jobs()]
        assert discovered == [job["id"] for job in data["jobs"]]
