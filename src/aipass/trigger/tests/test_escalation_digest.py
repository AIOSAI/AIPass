# =================== AIPass ====================
# Name: test_escalation_digest.py
# Description: Tests for the escalation digest: sending, the mail it carries, reporting and the CLI
# Version: 1.0.1
# Created: 2026-10-08
# Modified: 2026-10-24
# =============================================

"""Tests for apps/handlers/escalation.py's digest (send, mail, reporting) and apps/modules/escalation.py."""

# Split from test_escalation.py (oversize_test_file, 2026-10-08): that file keeps
# the signature, the counting and the windows; this one holds what the lane does
# once a signature is due: the send and its failures, the digest mail, what an
# operator sees through get_signatures, get_stats and the CLI, and the trail
# logger the lane writes through.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(covered_elsewhere) — the upsert key the digest carries to ai_mail: test_escalation_upsert.py
# seedgo: no-test-needed(external) — ai_mail delivery of the digest; AIPass tests only its own files

import json
from types import SimpleNamespace
from typing import Any, Dict, List
from unittest.mock import MagicMock

import pytest
from aipass.trigger.apps.config import trail_logger
from aipass.trigger.apps.modules import escalation as escalation_cli
from aipass.trigger.tests.support_escalation import (
    WARNING_EVENT,
    _age_first_seen,
    _age_last_digest,
    _entry,
    _fire_aged_warning,
    _fire_distinct,
    _fire_error,
    _fire_warning,
    _freeze_clock,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def refused(monkeypatch: pytest.MonkeyPatch, lane) -> List[Dict[str, Any]]:
    """A delivery callback that records every attempt and refuses it."""
    attempts: List[Dict[str, Any]] = []

    def _refuse(**kwargs: Any) -> bool:
        attempts.append(kwargs)
        return False

    monkeypatch.setattr(lane, "_send_email", _refuse)
    return attempts


@pytest.fixture
def cli(monkeypatch: pytest.MonkeyPatch, lane) -> SimpleNamespace:
    """The real escalation CLI module; only its operation log is redirected.

    The console is the real one: tests read what it printed with capsys.
    log_operation is replaced because the real one writes into trigger_json/.
    """
    log_operation = MagicMock(return_value=True)
    monkeypatch.setattr(escalation_cli.json_handler, "log_operation", log_operation)
    return SimpleNamespace(module=escalation_cli, log_operation=log_operation)


# ---------------------------------------------------------------------------
# Send failures
# ---------------------------------------------------------------------------


class TestSendFailures:
    """A failed send must leave the signature ready to retry, not silently 'done'."""

    def test_refused_delivery_reports_send_failed(self, lane, refused) -> None:
        """A callback returning False is a failure, not a send."""
        decision = _fire_warning(lane, times=3)

        assert decision["outcome"] == "send_failed"
        assert len(refused) == 1, "the digest was attempted once, at the threshold"

    def test_refused_delivery_does_not_start_the_cooldown(self, lane, refused) -> None:
        """last_digest stays empty and digests_sent stays 0, so nothing is muted by a failure."""
        signature = _fire_warning(lane, times=3)["signature"]

        entry = _entry(lane, signature)
        assert entry["last_digest"] == ""
        assert entry["digests_sent"] == 0

    def test_next_occurrence_retries_after_a_failure(self, monkeypatch, lane, refused) -> None:
        """The window was not reset either, so the very next occurrence tries again."""
        _fire_warning(lane, times=3)
        assert len(refused) == 1

        box: List[Dict[str, Any]] = []

        def _send(**kwargs: Any) -> bool:
            box.append(kwargs)
            return True

        monkeypatch.setattr(lane, "_send_email", _send)

        decision = _fire_warning(lane, times=1)

        assert decision["outcome"] == "sent"
        assert len(box) == 1

    def test_raising_callback_is_contained(self, monkeypatch, lane) -> None:
        """A callback that throws is a send failure, never an exception out of the lane."""

        def _boom(**kwargs: Any) -> bool:
            raise RuntimeError("SMTP down")

        monkeypatch.setattr(lane, "_send_email", _boom)

        decision = _fire_warning(lane, times=3)

        assert decision["outcome"] == "send_failed"
        assert _entry(lane, decision["signature"])["digests_sent"] == 0

    def test_missing_callback_is_contained(self, lane) -> None:
        """No email callback wired (handlers run before the module layer wires one)."""
        decision = _fire_warning(lane, times=3)

        assert decision["outcome"] == "send_failed"
        assert _entry(lane, decision["signature"])["last_digest"] == ""


# ---------------------------------------------------------------------------
# set_send_email_callback
# ---------------------------------------------------------------------------


class TestSendEmailCallback:
    """The module layer wires delivery in; handlers never import modules."""

    def test_wired_callback_receives_the_digest(self, lane) -> None:
        """A callback set through the public setter is the one that sends."""
        box: List[Dict[str, Any]] = []

        def _send(**kwargs: Any) -> bool:
            box.append(kwargs)
            return True

        lane.set_send_email_callback(_send)

        _fire_warning(lane, times=3)

        assert len(box) == 1
        assert box[0]["subject"].startswith("[REPEAT]")

    def test_second_wiring_replaces_the_first(self, lane) -> None:
        """Re-running setup must not leave two deliveries racing."""
        first: List[Dict[str, Any]] = []
        second: List[Dict[str, Any]] = []
        lane.set_send_email_callback(lambda **kwargs: bool(first.append(kwargs)) or True)
        lane.set_send_email_callback(lambda **kwargs: bool(second.append(kwargs)) or True)

        _fire_warning(lane, times=3)

        assert first == []
        assert len(second) == 1


# ---------------------------------------------------------------------------
# Digest email
# ---------------------------------------------------------------------------


class TestDigestEmail:
    """The digest is an EMAIL to a manager, and investigation starts from it alone."""

    def test_goes_to_the_configured_recipient_as_plain_email(self, lane, outbox, cfg) -> None:
        """auto_execute is False: a digest is read, it never wakes anyone."""
        _fire_warning(lane, times=3)

        mail = outbox[0]
        assert mail["to_branch"] == cfg["digest_recipient"]
        assert mail["auto_execute"] is False
        assert mail["from_branch"] == "@trigger"

    def test_subject_names_level_count_branch_and_module(self, lane, outbox) -> None:
        """The subject alone says what repeated, how often and where."""
        _fire_warning(lane, times=3)

        subject = outbox[0]["subject"]
        assert "[REPEAT]" in subject
        assert "WARNING" in subject
        assert "x3" in subject
        assert "@flow" in subject
        assert "watcher" in subject

    def test_body_carries_the_investigation_context(self, lane, outbox) -> None:
        """Signature, count, window, branch, module and log path all travel with the mail."""
        decision = _fire_warning(lane, times=3)

        body = outbox[0]["message"]
        assert decision["signature"] in body
        assert "3 in the last 60 min" in body
        assert "@flow" in body
        assert "watcher" in body
        assert WARNING_EVENT["log_file"] in body
        assert WARNING_EVENT["message"] in body

    def test_body_carries_the_last_sample_lines(self, lane, outbox, cfg) -> None:
        """The last sample_lines raw lines ride along; older ones are dropped."""
        cfg["sample_lines"] = 2
        for index in range(3):
            lane.record_warning(**{**WARNING_EVENT, "raw_line": f"raw line {index}"})

        body = outbox[0]["message"]
        assert "raw line 0" not in body
        assert "raw line 1" in body
        assert "raw line 2" in body

    def test_body_states_the_reason_it_escalated(self, lane, outbox, medic) -> None:
        """The mail explains why medic was not going to handle this."""
        medic.state.get_muted_branches = lambda: ["flow"]

        _fire_error(lane, times=3)

        assert "Why escalated: branch muted" in outbox[0]["message"]

    def test_body_points_at_the_operator_config(self, lane, outbox) -> None:
        """Every digest tells the reader how to tune or silence it."""
        _fire_warning(lane, times=3)

        body = outbox[0]["message"]
        assert "trigger.config.json" in body
        assert "warning_threshold" in body

    def test_a_warning_past_the_age_limit_goes_to_the_branch_that_logged_it(
        self, monkeypatch, lane, outbox, cfg
    ) -> None:
        """24h of repetition into a manager's inbox is a pile. The owner gets it instead."""
        monkeypatch.setattr(lane, "_has_registered_owner", lambda branch: branch == "flow")

        decision = _fire_aged_warning(lane)

        assert decision["outcome"] == "aged_owner_mail"
        assert len(outbox) == 2, "one notice to the owner, one roll-up to the manager"
        notice = outbox[0]
        assert notice["to_branch"] == "@flow"
        assert notice["auto_execute"] is False
        assert notice["upsert_key"] == "escalation:WARNING:flow:watcher"
        assert cfg["digest_recipient"] not in [mail["to_branch"] for mail in outbox[:1]]

    def test_the_aged_notice_opens_a_registry_row_at_warning_level(self, monkeypatch, lane, outbox) -> None:
        """The row is what gives a repeat a lifecycle: suppress, resolve, a count."""
        monkeypatch.setattr(lane, "_has_registered_owner", lambda branch: branch == "flow")
        rows: List[Dict[str, Any]] = []

        def _report(**kwargs: Any) -> Dict[str, Any]:
            rows.append(kwargs)
            return {"fingerprint": "abcdef0123456789", "is_new": True}

        monkeypatch.setattr(lane, "_registry_report", _report)

        signature = _fire_aged_warning(lane)["signature"]

        assert len(rows) == 1
        assert rows[0]["error_type"] == "WARNING"
        assert rows[0]["component"] == "FLOW"
        assert rows[0]["message"] == WARNING_EVENT["message"]
        assert _entry(lane, signature)["registry_fingerprint"] == "abcdef0123456789"

    def test_a_suppressed_row_gets_no_aged_notice(self, monkeypatch, lane, outbox) -> None:
        """The notice tells a benign owner to suppress; once they do, it must stop."""
        monkeypatch.setattr(lane, "_has_registered_owner", lambda branch: branch == "flow")
        monkeypatch.setattr(lane, "_registry_report", lambda **kw: {"fingerprint": "ab" * 8, "status": "suppressed"})

        decision = _fire_aged_warning(lane)

        assert decision["outcome"] == "not_eligible"
        assert outbox == []

    def test_an_unregistered_logging_branch_keeps_the_manager_digest(self, monkeypatch, lane, outbox, cfg) -> None:
        """Never drop the signal: with nobody to mail, the manager keeps hearing it."""
        monkeypatch.setattr(lane, "_has_registered_owner", lambda branch: branch == "memory")

        decision = _fire_aged_warning(lane)

        assert decision["outcome"] == "sent"
        assert [mail["to_branch"] for mail in outbox] == [cfg["digest_recipient"]]

    def test_an_aged_error_is_not_touched_by_the_warning_lane(self, monkeypatch, lane, outbox, cfg, medic) -> None:
        """Errors have medic. This lane is only for warnings, which have nothing."""
        monkeypatch.setattr(lane, "_has_registered_owner", lambda branch: branch == "flow")
        medic.state.get_muted_branches = lambda: ["flow"]

        signature = _fire_error(lane, times=1)["signature"]
        _age_first_seen(lane, signature, 48)
        decision = _fire_error(lane, times=2)

        assert decision["outcome"] == "sent"
        assert [mail["to_branch"] for mail in outbox] == [cfg["digest_recipient"]]

    def test_every_rollup_lands_on_one_manager_thread(self, monkeypatch, lane, outbox, cfg) -> None:
        """The daily roll-up replaces the repeat digests — it must not become them."""
        monkeypatch.setattr(lane, "_has_registered_owner", lambda branch: branch == "flow")

        _fire_aged_warning(lane)
        _fire_aged_warning(lane, message="a second aged condition")

        rollups = [mail for mail in outbox if mail["to_branch"] == cfg["digest_recipient"]]
        assert {mail["upsert_key"] for mail in rollups} == {"escalation:rollup"}
        assert all(mail["auto_execute"] is False for mail in rollups)

    def test_an_unchanged_row_list_is_not_rolled_up_again_inside_the_window(
        self, monkeypatch, lane, outbox, cfg
    ) -> None:
        """Cadence paces the repeats; only a list that GREW is worth a rewrite."""
        monkeypatch.setattr(lane, "_has_registered_owner", lambda branch: branch == "flow")
        signature = _fire_aged_warning(lane)["signature"]
        before = len([mail for mail in outbox if mail["to_branch"] == cfg["digest_recipient"]])

        _age_last_digest(lane, signature, 400)
        _fire_warning(lane, times=3)

        after = [mail for mail in outbox if mail["to_branch"] == cfg["digest_recipient"]]
        assert before == 1
        assert len(after) == 1, "the same row rolled up twice inside the window"

    def test_the_rollup_names_every_open_aged_row(self, monkeypatch, lane, outbox, cfg) -> None:
        """One line per open row is the whole point: the manager sees the shape of it."""
        monkeypatch.setattr(lane, "_has_registered_owner", lambda branch: branch == "flow")

        first = _fire_aged_warning(lane)["signature"]
        second = _fire_aged_warning(lane, message="a second aged condition")["signature"]

        body = [mail for mail in outbox if mail["to_branch"] == cfg["digest_recipient"]][-1]["message"]
        assert first in body
        assert second in body
        assert "@flow/watcher" in body

    def test_a_second_signature_in_the_module_names_the_first(self, lane, outbox) -> None:
        """The lane hands the digest its siblings; the thread body must not forget them."""
        first = _fire_warning(lane, times=3)["signature"]
        _fire_warning(lane, times=3, message="queue consumer stalled")

        assert len(outbox) == 2
        assert first in outbox[1]["message"]
        assert WARNING_EVENT["message"] in outbox[1]["message"]
        assert outbox[1]["subject"].endswith("(2 signatures)")

    def test_siblings_are_matched_on_level_branch_and_module_only(self, lane, outbox) -> None:
        """Another module's or another level's signatures are other threads, never listed."""
        _fire_warning(lane, times=1, module="elsewhere", message="unrelated module warning")
        _fire_error(lane, times=1, module="watcher", message="same module, error level")
        _fire_warning(lane, times=3)

        body = outbox[0]["message"]
        assert "unrelated module warning" not in body
        assert "same module, error level" not in body
        assert "(2 signatures)" not in outbox[0]["subject"]


# ---------------------------------------------------------------------------
# Reporting: get_signatures / get_stats
# ---------------------------------------------------------------------------


class TestReporting:
    """What the CLI and an operator get to see."""

    def test_stats_count_the_rows_the_aged_lane_has_opened(self, monkeypatch, lane, outbox, cfg) -> None:
        """An operator must be able to see how many repeats went to their owners."""
        monkeypatch.setattr(lane, "_has_registered_owner", lambda branch: branch == "flow")
        _fire_aged_warning(lane)

        stats = lane.get_stats()

        assert stats["aged_signatures"] == 1
        assert stats["warning_age_hours"] == cfg["warning_age_hours"]

    def test_signatures_are_returned_most_recent_first(self, lane) -> None:
        """Ordering is by last_seen, newest first."""
        _fire_warning(lane, times=1, message="older warning")
        newest = _fire_warning(lane, times=1, message="newer warning")["signature"]

        rows = lane.get_signatures()
        assert rows[0]["signature"] == newest
        assert len(rows) == 2

    def test_ordering_holds_when_last_seen_ties(self, lane, monkeypatch: pytest.MonkeyPatch) -> None:
        """The Windows CI flake: identical last_seen must still list newest first."""
        _freeze_clock(monkeypatch, lane)
        _fire_warning(lane, times=1, message="older warning")
        newest = _fire_warning(lane, times=1, message="newer warning")["signature"]

        rows = lane.get_signatures()
        assert len({row["last_seen"] for row in rows}) == 1, "clock must be tied for this to test anything"
        assert rows[0]["signature"] == newest

    def test_re_seeing_a_signature_moves_it_to_the_front_on_a_tied_clock(
        self, lane, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Touch order, not creation order, decides the listing.

        The re-seen signature is deliberately the MIDDLE one: if creation order
        still leaked through, the first-created would head the list instead.
        """
        _freeze_clock(monkeypatch, lane)
        _fire_distinct(lane, 0)
        middle = _fire_distinct(lane, 1)["signature"]
        _fire_distinct(lane, 2)
        _fire_distinct(lane, 1)

        assert lane.get_signatures()[0]["signature"] == middle

    def test_signature_rows_carry_the_window_count(self, lane) -> None:
        """A row reports occurrences inside the window as well as lifetime total."""
        _fire_warning(lane, times=2)

        row = lane.get_signatures()[0]
        assert row["window_count"] == 2
        assert row["total_count"] == 2

    def test_level_filter_selects_one_level(self, lane, medic) -> None:
        """list warning shows warnings only, and list error shows errors only."""
        _fire_warning(lane, times=1)
        _fire_error(lane, times=1)

        warnings = lane.get_signatures(level="warning")
        errors = lane.get_signatures(level="ERROR")

        assert [row["level"] for row in warnings] == ["WARNING"]
        assert [row["level"] for row in errors] == ["ERROR"]

    def test_limit_caps_the_listing(self, lane) -> None:
        """The limit argument bounds what the CLI renders."""
        for index in range(5):
            _fire_distinct(lane, index)

        assert len(lane.get_signatures(limit=2)) == 2

    def test_stats_report_config_and_tracking(self, lane, outbox, cfg, medic) -> None:
        """Stats mix the operator's knobs with what the lane is actually holding."""
        _fire_warning(lane, times=3)
        _fire_error(lane, times=1)

        stats = lane.get_stats()
        assert stats["enabled"] is True
        assert stats["digest_recipient"] == cfg["digest_recipient"]
        assert stats["warning_threshold"] == cfg["warning_threshold"]
        assert stats["error_threshold"] == cfg["error_threshold"]
        assert stats["window_minutes"] == cfg["window_minutes"]
        assert stats["cooldown_minutes"] == cfg["cooldown_minutes"]
        assert stats["tracked_signatures"] == 2
        assert stats["tracked_warnings"] == 1
        assert stats["tracked_errors"] == 1
        assert stats["digests_sent"] == 1
        assert stats["signatures_digested"] == 1
        assert stats["email_wired"] is True
        assert stats["state_file"] == str(lane.STATE_FILE)

    def test_stats_report_no_email_wired(self, lane) -> None:
        """An operator can see that this process could not send a digest."""
        assert lane.get_stats()["email_wired"] is False

    def test_stats_on_an_empty_lane(self, lane) -> None:
        """Nothing tracked yet is a clean zero, not a crash."""
        stats = lane.get_stats()
        assert stats["tracked_signatures"] == 0
        assert stats["digests_sent"] == 0


# ---------------------------------------------------------------------------
# modules/escalation.py -- CLI
# ---------------------------------------------------------------------------


class TestCliCommand:
    """The CLI claims its own module name and nothing else."""

    def test_bare_status_is_left_to_core(self, cli) -> None:
        """`drone @trigger status` belongs to core.py — claiming it would hijack it."""
        assert cli.module.handle_command("status", []) is False

    def test_bare_list_is_left_to_core(self, cli) -> None:
        """`list` is core's command too."""
        assert cli.module.handle_command("list", []) is False

    def test_bare_config_is_left_to_core(self, cli) -> None:
        """`config` is core's command too."""
        assert cli.module.handle_command("config", []) is False

    def test_escalation_status_is_handled(self, cli, capsys: pytest.CaptureFixture[str]) -> None:
        """`escalation status` renders and reports as handled."""
        assert cli.module.handle_command("escalation", ["status"]) is True
        assert "Escalation Digest" in capsys.readouterr().out

    def test_escalation_list_is_handled(self, cli, capsys: pytest.CaptureFixture[str]) -> None:
        """`escalation list` renders and reports as handled.

        Mutant killed 2026-09-27: _handle_list(...) in _run_subcommand replaced by pass.
        """
        assert cli.module.handle_command("escalation", ["list"]) is True
        assert "No signatures tracked yet." in capsys.readouterr().out

    def test_escalation_config_is_handled(self, cli, capsys: pytest.CaptureFixture[str]) -> None:
        """`escalation config` renders and reports as handled.

        Mutant killed 2026-09-27: _handle_config(...) in _run_subcommand replaced by pass.
        """
        assert cli.module.handle_command("escalation", ["config"]) is True
        out = capsys.readouterr().out
        assert "Escalation config" in out
        assert "warning_threshold = 3" in out

    def test_no_subcommand_prints_introspection(self, cli, capsys: pytest.CaptureFixture[str]) -> None:
        """A bare `escalation` introspects rather than guessing a subcommand."""
        assert cli.module.handle_command("escalation", []) is True
        assert "escalation Module" in capsys.readouterr().out

    def test_unknown_subcommand_refuses_rather_than_showing_help(self, cli) -> None:
        """`escalation wat` returns False so the entry point can exit non-zero.

        This test used to assert the opposite — an unknown subcommand printed
        help and returned True. Help is what a working command looks like, so
        the refusal exited 0 and never named the token. Returning False routes
        it through the ONE gate in trigger.py, which names the whole invocation
        and exits 1 (the owner's standing ruling, FPLAN-0492).
        """
        assert cli.module.handle_command("escalation", ["wat"]) is False

    def test_help_words_still_reach_help(self, cli, monkeypatch: pytest.MonkeyPatch) -> None:
        """The refusal must not swallow `help` — it is not an unknown subcommand."""
        printed = MagicMock()
        monkeypatch.setattr(cli.module, "print_help", printed)

        assert cli.module.handle_command("escalation", ["help"]) is True
        printed.assert_called_once()

    def test_status_renders_the_configured_recipient(self, cli, cfg, capsys: pytest.CaptureFixture[str]) -> None:
        """Status shows where digests actually go, not a hardcoded address."""
        cli.module.handle_command("escalation", ["status"])

        assert cfg["digest_recipient"] in capsys.readouterr().out

    def test_list_renders_tracked_signatures(self, cli, lane, capsys: pytest.CaptureFixture[str]) -> None:
        """A counted signature shows up in `escalation list`."""
        signature = _fire_warning(lane, times=1)["signature"]

        cli.module.handle_command("escalation", ["list"])

        rendered = capsys.readouterr().out
        assert signature in rendered
        assert WARNING_EVENT["message"] in rendered

    def test_list_filters_by_level(self, cli, lane, medic, capsys: pytest.CaptureFixture[str]) -> None:
        """`escalation list error` hides warning signatures."""
        warning_signature = _fire_warning(lane, times=1)["signature"]
        error_signature = _fire_error(lane, times=1)["signature"]

        cli.module.handle_command("escalation", ["list", "error"])

        rendered = capsys.readouterr().out
        assert error_signature in rendered
        assert warning_signature not in rendered

    def test_command_is_logged(self, cli) -> None:
        """Subcommands are recorded through json_handler like every other module."""
        cli.module.handle_command("escalation", ["status"])

        cli.log_operation.assert_called_once_with("escalation_command", {"command": "status"})


class TestDigestBody:
    """The digest mail is the whole product — investigation starts from it alone."""

    @staticmethod
    def _entry() -> dict:
        return {
            "level": "ERROR",
            "branch": "BACKUP",
            "module": "drive",
            "message": "module 'drive' has no attribute 'client'",
            "first_seen": "2026-08-08T21:00:00",
            "last_seen": "2026-08-08T21:40:00",
            "log_file": "/logs/backup/backup.log",
            "total_count": 47,
            "digests_sent": 2,
            "samples": ["21:39 ERROR drive failed", "21:40 ERROR drive failed"],
        }

    def test_body_carries_everything_an_investigation_needs(self, lane) -> None:
        """Signature, counts, window, branch, module, log path and samples all travel."""
        subject, body = lane.build_digest(
            "abc123def456", self._entry(), 9, 3600, "owner already dispatched", "@devpulse"
        )

        assert subject == "[REPEAT] ERROR x9 @backup / drive"
        for expected in (
            "abc123def456",
            "@backup",
            "drive",
            "9 in the last 60 min",
            "lifetime 47",
            "/logs/backup/backup.log",
            "owner already dispatched",
            "21:40 ERROR drive failed",
        ):
            assert expected in body, f"digest body lost {expected!r}"

    def test_body_says_it_is_mail_not_a_dispatch(self, lane) -> None:
        """The recipient must not read a digest as a task waiting on them."""
        _subject, body = lane.build_digest("sig", self._entry(), 5, 3600, "branch muted", "@devpulse")

        assert "EMAIL, not a dispatch" in body
        assert "nothing was woken" in body

    def test_body_names_the_config_file_to_tune_it(self, lane) -> None:
        """An operator who wants less of this must not have to go hunting."""
        _subject, body = lane.build_digest("sig", self._entry(), 5, 3600, "medic off", "@devpulse")

        assert "trigger_json/custom_config/trigger.config.json" in body

    def test_missing_samples_say_so_rather_than_render_blank(self, lane) -> None:
        """A digest with no captured lines must not look like a digest with empty lines."""
        entry = self._entry()
        entry["samples"] = []

        _subject, body = lane.build_digest("sig", entry, 5, 3600, "no registered owner", "@devpulse")

        assert "(no samples captured)" in body

    def test_the_aged_notice_tells_the_owner_what_it_is_and_how_to_end_it(self, lane) -> None:
        """The owner needs the age, the registry id and both ways out, from the mail alone."""
        entry = {**self._entry(), "level": "WARNING"}

        subject, body = lane.build_aged_notice("abc123def456", entry, 9, 3600, "@backup", [], 26.0, "ff0011223344")

        assert subject == "[REPEAT 26h] WARNING x9 @backup / drive"
        for expected in ("abc123def456", "ff0011223344", "26", "drone @trigger errors suppress", "@backup"):
            assert expected in body, f"aged notice lost {expected!r}"
        assert "EMAIL, not a dispatch" in body

    def test_sibling_signatures_ride_in_the_thread(self, lane) -> None:
        """One thread per subject: the other signatures under it are named in the body."""
        sibling = {**self._entry(), "message": "drive quota exceeded", "total_count": 12}

        subject, body = lane.build_digest(
            "abc123def456", self._entry(), 9, 3600, "medic off", "@devpulse", siblings=[("fff000111222", sibling)]
        )

        assert subject == "[REPEAT] ERROR x9 @backup / drive (2 signatures)"
        assert "fff000111222" in body
        assert "x12" in body
        assert "drive quota exceeded" in body

    def test_sibling_roster_is_capped_and_says_how_many_it_left_out(self, lane) -> None:
        """A module with hundreds of variants must not grow the mail without bound."""
        siblings = [(f"sib{index:09d}", {**self._entry(), "message": f"variant {index}"}) for index in range(25)]

        subject, body = lane.build_digest("abc123def456", self._entry(), 9, 3600, "medic off", "@devpulse", siblings)

        assert subject.endswith("(26 signatures)")
        assert "sib000000000" in body
        assert f"sib{lane.MAX_ROSTER_LINES - 1:09d}" in body
        assert f"sib{lane.MAX_ROSTER_LINES:09d}" not in body
        assert f"and {25 - lane.MAX_ROSTER_LINES} more" in body


class TestTrailLogger:
    """The recursion-safe sidecar every trigger handler logs through."""

    def test_writes_level_message_and_fields(self, tmp_path) -> None:
        """A trail line carries the structured fields the caller passed."""
        path = tmp_path / "trail.jsonl"

        trail_logger(path).warning("state unreadable", signature="abc123", branch="BACKUP")

        line = json.loads(path.read_text(encoding="utf-8").strip())
        assert line["level"] == "WARNING"
        assert line["msg"] == "state unreadable"
        assert line["signature"] == "abc123"
        assert line["branch"] == "BACKUP"

    def test_a_broken_sink_is_counted_never_raised(self, tmp_path, monkeypatch) -> None:
        """A dead trail must not take the error path down with it — it is counted."""
        trail = trail_logger(tmp_path / "trail.jsonl")
        monkeypatch.setattr(
            "aipass.trigger.apps.config._append_jsonl",
            MagicMock(side_effect=OSError("read-only filesystem")),
        )

        trail.error("digest send raised")

        assert trail.dropped == 1

    def test_absent_prax_is_counted_too(self, tmp_path, monkeypatch) -> None:
        """No prax means no sidecar — the loss is still visible as a count."""
        trail = trail_logger(tmp_path / "trail.jsonl")
        monkeypatch.setattr("aipass.trigger.apps.config._append_jsonl", None)

        trail.info("digest sent")

        assert trail.dropped == 1

    def test_dropped_trail_lines_reach_the_operator_in_stats(self, lane, monkeypatch) -> None:
        """A silent sink would be invisible; get_stats() is where it surfaces."""
        monkeypatch.setattr(
            "aipass.trigger.apps.config._append_jsonl",
            MagicMock(side_effect=OSError("disk full")),
        )
        lane.logger.warning("something the trail could not keep")

        assert lane.get_stats()["trail_writes_dropped"] >= 1


# ---------------------------------------------------------------------------
# help_flag_safety canary — a help flag ANYWHERE explains, never executes
# ---------------------------------------------------------------------------


def test_help_flag_after_a_level_operand_does_not_list(monkeypatch: pytest.MonkeyPatch, cli) -> None:
    """`escalation list warning --help` must describe, never run the listing.

    The escalation lane is a live surface — its subcommands read and report
    the operator digest state. The subcommand target is mocked, so a missing
    gate shows up as a call that should not have happened.
    """
    ran = MagicMock()
    monkeypatch.setattr(cli.module, "_handle_list", ran)
    printed = MagicMock()
    monkeypatch.setattr(cli.module, "print_help", printed)

    result = cli.module.handle_command("escalation", ["list", "warning", "--help"])

    assert result is True
    printed.assert_called_once()
    ran.assert_not_called()


def test_short_help_flag_after_subcommand_does_not_run_status(monkeypatch: pytest.MonkeyPatch, cli) -> None:
    """`escalation status extra -h` — same gate, short form, read-only verb."""
    ran = MagicMock()
    monkeypatch.setattr(cli.module, "_handle_status", ran)
    printed = MagicMock()
    monkeypatch.setattr(cli.module, "print_help", printed)

    result = cli.module.handle_command("escalation", ["status", "extra", "-h"])

    assert result is True
    printed.assert_called_once()
    ran.assert_not_called()
