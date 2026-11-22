# =================== AIPass ====================
# Name: test_event_handlers.py
# Description: Tests for simple event handler functions, the warning escalation lane and the mute expiry sweep
# Version: 1.2.1
# Created: 2026-04-25
# Modified: 2026-11-21
# =============================================

"""Tests for apps/handlers/events/memory_template_updated.py, warning_logged.py and mute_expiry.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# sentry: no-test-needed(behaviour) — the lane internals in apps/handlers/escalation.py; the escalation tests cover them

import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, cast
from unittest.mock import MagicMock

import pytest
import aipass.ai_mail as ai_mail
from aipass.ai_mail import CLAUDE, CODEX, OPENCODE
from aipass.prax import trail
from aipass.trigger.apps.handlers import escalation, medic_state
from aipass.trigger.apps.handlers.ci import outbound
from aipass.trigger.apps.handlers.events import (
    error_detected,
    memory_template_updated,
    mute_expiry,
    registry,
    runaway_handler,
    warning_logged,
)
from aipass.trigger.apps.modules import core


@pytest.fixture(autouse=True)
def json_log(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """The json_handler each of the two handler modules logs through, as a recorder.
    Replaced where each handler module holds the name, so no handler call reaches the operation log.
    """
    log = MagicMock()
    log.log_operation = MagicMock(return_value=True)
    for handler_module in (memory_template_updated, warning_logged):
        monkeypatch.setattr(handler_module, "json_handler", log)
    return log


class TestHandleMemoryTemplateUpdated:
    """Tests for handle_memory_template_updated from memory_template_updated.py."""

    def test_calls_log_operation(self, json_log: MagicMock) -> None:
        """Logs memory_template_event via json_handler."""
        mod = memory_template_updated

        json_log.log_operation.reset_mock()

        mod.handle_memory_template_updated()

        json_log.log_operation.assert_called_once_with("memory_template_event", {"success": True})

    def test_documented_event_data_is_absorbed_and_never_reaches_the_log(self, json_log: MagicMock) -> None:
        """template_name and updated_by are documented, accepted, and discarded.
        The payload is fixed; the event data is context for a push this handler does not perform.
        """
        mod = memory_template_updated

        mod.handle_memory_template_updated(template_name="local", updated_by="drone")

        json_log.log_operation.assert_called_once_with("memory_template_event", {"success": True})

    def test_returns_none(self) -> None:
        """Handler returns None."""
        mod = memory_template_updated
        result = mod.handle_memory_template_updated()
        assert result is None


class TestHandleWarningLogged:
    """Tests for handle_warning_logged from warning_logged.py."""

    def test_calls_log_operation(self, json_log: MagicMock) -> None:
        """Logs warning_logged_event via json_handler."""
        mod = warning_logged

        json_log.log_operation.reset_mock()

        mod.handle_warning_logged()

        json_log.log_operation.assert_called_once_with("warning_logged_event", {"success": True})

    def test_the_three_discarded_params_are_really_discarded(self, lane) -> None:
        """error_hash, timestamp and level are accepted and then dropped.
        The lane computes its own signature and level, so a caller's `level="critical"` must not relabel a warning.
        """
        mod = warning_logged

        mod.handle_warning_logged(
            branch="flow",
            message="disk almost full",
            error_hash="w1-should-not-travel",
            timestamp="2026-04-25T12:00:00",
            log_file="flow.log",
            module_name="watcher",
            level="critical",
        )

        rows = lane.mod.get_signatures()
        assert len(rows) == 1
        assert rows[0]["level"] == "WARNING", "the caller's level must not relabel the row"
        serialised = json.dumps(rows[0])
        assert "w1-should-not-travel" not in serialised
        assert "2026-04-25T12:00:00" not in serialised

    def test_all_none_records_nothing_and_still_logs(self, lane, json_log: MagicMock) -> None:
        """No branch and no message is not a warning — nothing recorded, still logged.
        A malformed event must not mint a signature keyed on nothing: the lane stays empty and the run is logged.
        escalation._record repeats the branch/message guard, so deleting the handler's copy alone does not red this.
        """
        mod = warning_logged

        mod.handle_warning_logged(
            branch=None,
            message=None,
            error_hash=None,
            timestamp=None,
            log_file=None,
            module_name=None,
            level=None,
        )

        assert lane.mod.get_signatures() == []
        json_log.log_operation.assert_called_once_with("warning_logged_event", {"success": True})

    def test_an_undocumented_kwarg_reaches_neither_the_lane_nor_the_log(self, lane, json_log: MagicMock) -> None:
        """**kwargs absorbs what the contract does not name, and it stops there.
        An unknown key must be accepted without leaking into a signature and splitting one warning into many.
        """
        mod = warning_logged

        mod.handle_warning_logged(
            branch="flow",
            message="disk almost full",
            module_name="watcher",
            extra_field="unexpected-and-unnamed",
        )

        rows = lane.mod.get_signatures()
        assert len(rows) == 1
        assert "unexpected-and-unnamed" not in json.dumps(rows[0])
        json_log.log_operation.assert_called_once_with("warning_logged_event", {"success": True})

    def test_returns_none(self) -> None:
        """Handler returns None."""
        mod = warning_logged
        result = mod.handle_warning_logged()
        assert result is None


@pytest.fixture
def lane(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> SimpleNamespace:
    """The escalation lane on a tmp state file with a known threshold.
    State file, config and digest callback are pinned: operator config never decides an outcome, no digest leaves.
    """
    config: Dict[str, Any] = {
        "enabled": True,
        "digest_recipient": "@digest-inbox",
        "warning_threshold": 2,
        "error_threshold": 2,
        "window_minutes": 60,
        "cooldown_minutes": 60,
        "sample_lines": 3,
        "max_signatures": 500,
        "ignore_branches": [],
    }
    digests: List[Dict[str, Any]] = []

    def _send(**kwargs: Any) -> bool:
        digests.append(kwargs)
        return True

    monkeypatch.setattr(escalation, "STATE_FILE", tmp_path / "escalation_state.json")
    monkeypatch.setattr(escalation, "logger", trail(tmp_path / "logs" / "escalation.jsonl"))
    monkeypatch.setattr(escalation, "get_config", lambda: config)
    monkeypatch.setattr(escalation, "_send_email", _send)
    escalation._config_cache = (0.0, None)
    return SimpleNamespace(mod=escalation, config=config, digests=digests)


class TestWarningLoggedFeedsEscalation:
    """Warnings have no dispatch path anywhere in medic.
    A warning loop has no other way to a human, so the handler's job is feeding the counter, not notifying.
    """

    def test_warning_is_counted(self, lane) -> None:
        """One warning lands in the lane as a WARNING signature."""
        mod = warning_logged

        mod.handle_warning_logged(branch="flow", message="queue depth 91%", module_name="watcher")

        rows = lane.mod.get_signatures()
        assert len(rows) == 1
        assert rows[0]["level"] == "WARNING"
        assert rows[0]["branch"] == "flow"
        assert rows[0]["module"] == "watcher"

    def test_module_name_defaults_to_unknown(self, lane) -> None:
        """A warning with no module still counts, under a named placeholder."""
        mod = warning_logged

        mod.handle_warning_logged(branch="flow", message="queue depth 91%")

        assert lane.mod.get_signatures()[0]["module"] == "unknown"

    def test_context_travels_into_the_lane(self, lane) -> None:
        """Log path and raw line are what make the eventual digest actionable."""
        mod = warning_logged

        mod.handle_warning_logged(
            branch="flow",
            message="queue depth 91%",
            module_name="watcher",
            log_file=str(Path("logs") / "flow.log"),
            raw_line="2026-08-08 | watcher | WARNING | queue depth 91%",
        )

        row = lane.mod.get_signatures()[0]
        assert row["log_file"] == str(Path("logs") / "flow.log")
        assert row["samples"] == ["2026-08-08 | watcher | WARNING | queue depth 91%"]

    def test_repeats_with_variable_paths_share_one_signature(self, lane) -> None:
        """The same warning about different files is one repeating warning."""
        mod = warning_logged

        mod.handle_warning_logged(branch="flow", message="cannot read /home/a/x.json", module_name="watcher")
        mod.handle_warning_logged(branch="flow", message="cannot read /srv/b/y.json", module_name="watcher")

        rows = lane.mod.get_signatures()
        assert len(rows) == 1
        assert rows[0]["total_count"] == 2

    def test_different_branches_do_not_pool(self, lane) -> None:
        """Two branches warning identically are two separate signatures."""
        mod = warning_logged

        mod.handle_warning_logged(branch="flow", message="queue depth 91%", module_name="watcher")
        mod.handle_warning_logged(branch="memory", message="queue depth 91%", module_name="watcher")

        assert len(lane.mod.get_signatures()) == 2

    def test_repeat_crosses_the_threshold_and_emails_once(self, lane) -> None:
        """The point of the lane: repetition reaches a human, exactly once."""
        mod = warning_logged

        for _ in range(2):
            mod.handle_warning_logged(branch="flow", message="queue depth 91%", module_name="watcher")

        assert len(lane.digests) == 1
        assert lane.digests[0]["to_branch"] == "@digest-inbox"
        assert lane.digests[0]["auto_execute"] is False
        assert "queue depth 91%" in lane.digests[0]["message"]

    def test_missing_branch_records_nothing(self, lane) -> None:
        """A warning with nothing to attribute it to is not countable."""
        mod = warning_logged

        mod.handle_warning_logged(branch=None, message="queue depth 91%", module_name="watcher")

        assert lane.mod.get_signatures() == []

    def test_missing_message_records_nothing(self, lane) -> None:
        """There is no signature without a message."""
        mod = warning_logged

        mod.handle_warning_logged(branch="flow", message=None, module_name="watcher")

        assert lane.mod.get_signatures() == []

    def test_event_is_still_logged_when_the_lane_is_off(self, lane, json_log: MagicMock) -> None:
        """Switching the lane off must not change the handler's own contract."""
        mod = warning_logged

        lane.config["enabled"] = False
        json_log.log_operation.reset_mock()

        mod.handle_warning_logged(branch="flow", message="queue depth 91%", module_name="watcher")

        assert lane.mod.get_signatures() == []
        json_log.log_operation.assert_called_once_with("warning_logged_event", {"success": True})


@pytest.fixture
def sweep(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> SimpleNamespace:
    """mute_expiry over a tmp medic_state, a tmp branch with a session pointer, and a mail recorder."""
    monkeypatch.setattr(medic_state, "MEDIC_STATE_FILE", tmp_path / "medic_state.json")
    monkeypatch.setattr(mute_expiry, "json_handler", MagicMock())
    monkeypatch.setattr(mute_expiry, "logger", MagicMock())
    branch = tmp_path / "api"
    (branch / ".ai_mail.local").mkdir(parents=True)
    transcripts = tmp_path / "transcripts"
    transcripts.mkdir()
    monkeypatch.setattr(mute_expiry, "transcript_dir", lambda cwd: transcripts if cwd == str(branch) else None)
    monkeypatch.setattr(mute_expiry, "_branch_paths", lambda: {"api": branch})
    sent: List[Dict[str, Any]] = []
    monkeypatch.setattr(mute_expiry, "_send_email", lambda **mail: sent.append(mail) or True)

    def mute(expires_at: str) -> None:
        medic_state.MEDIC_STATE_FILE.write_text(
            json.dumps({"config": {"muted_branches": [{"name": "api", "expires_at": expires_at}]}}), encoding="utf-8"
        )

    def session(provider: str, age_seconds: float) -> Path:
        pointer = {"session_id": "s1", "provider": provider, "cwd": str(branch)}
        (branch / ".ai_mail.local" / "session.json").write_text(json.dumps(pointer), encoding="utf-8")
        transcript = transcripts / "s1.jsonl"
        transcript.write_text("{}\n", encoding="utf-8")
        stamp = time.time() - age_seconds
        os.utime(transcript, (stamp, stamp))
        return transcript

    return SimpleNamespace(branch=branch, sent=sent, mute=mute, session=session)


def _expired() -> str:
    return (datetime.now() - timedelta(minutes=1)).isoformat()


class TestMuteExpirySweep:
    """medic_mute_sweep: an expired mute mails its holder, unless the holder's session is still writing."""

    def test_idle_branch_gets_the_nudge_with_the_remute_command(self, sweep: SimpleNamespace) -> None:
        """No live session: the mute is dropped and @api gets one mail naming the re-mute command."""
        sweep.mute(_expired())
        sweep.session(CLAUDE, age_seconds=mute_expiry.ACTIVE_WINDOW_SECONDS + 60)

        mute_expiry.handle_medic_mute_sweep()

        assert [m["to_branch"] for m in sweep.sent] == ["@api"]
        assert "drone @trigger medic mute @api" in sweep.sent[0]["message"]
        assert "Still working?" in sweep.sent[0]["message"]
        assert medic_state.get_muted_branches() == []

    def test_live_claude_session_rearms_and_sends_nothing(self, sweep: SimpleNamespace) -> None:
        """A transcript written inside ACTIVE_WINDOW_SECONDS re-arms the mute; no mail goes out."""
        sweep.mute(_expired())
        sweep.session(CLAUDE, age_seconds=30)

        mute_expiry.handle_medic_mute_sweep()

        assert sweep.sent == []
        assert medic_state.get_muted_branches() == ["api"]

    def test_live_codex_session_reads_its_rollout_file(
        self, sweep: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Codex sessions are judged by codex_thread_file(session_id), not the Claude transcript dir."""
        rollout = sweep.session(CODEX, age_seconds=30)
        monkeypatch.setattr(mute_expiry, "codex_thread_file", lambda sid: rollout if sid == "s1" else None)

        assert mute_expiry.session_is_active(sweep.branch) is True

    def test_opencode_has_no_per_branch_signal(self, sweep: SimpleNamespace) -> None:
        """OpenCode keeps one shared store: never judged live, so its holder always gets the mail."""
        sweep.mute(_expired())
        sweep.session(OPENCODE, age_seconds=0)

        mute_expiry.handle_medic_mute_sweep()

        assert [m["to_branch"] for m in sweep.sent] == ["@api"]

    def test_unknown_branch_or_no_pointer_is_not_live(self, sweep: SimpleNamespace) -> None:
        """No path, or no pointer file: not live."""
        assert mute_expiry.session_is_active(None) is False
        assert mute_expiry.session_is_active(sweep.branch) is False

    def test_nothing_expired_reads_no_census_and_sends_nothing(
        self, sweep: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The minute tick is cheap: with no expired mute the fleet census is never read."""
        sweep.mute((datetime.now() + timedelta(hours=1)).isoformat())
        census = MagicMock(return_value={})
        monkeypatch.setattr(mute_expiry, "_branch_paths", census)

        mute_expiry.handle_medic_mute_sweep()

        census.assert_not_called()
        assert sweep.sent == []

    def test_failed_delivery_is_named_in_a_warning(
        self, sweep: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A send that answers False is logged with the branch; the mute is still settled."""
        sweep.mute(_expired())
        monkeypatch.setattr(mute_expiry, "_send_email", lambda **mail: mail["to_branch"] != "@api")

        mute_expiry.handle_medic_mute_sweep()

        cast(MagicMock, mute_expiry.logger).warning.assert_called_once()
        assert "api" in cast(MagicMock, mute_expiry.logger).warning.call_args.args[1]
        assert medic_state.get_muted_branches() == []

    def test_registry_wires_the_sweep_and_its_mail(
        self, sweep: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """setup_handlers puts medic_mute_sweep on the bus, and the sweep's mail leaves through ai_mail's delivery."""
        for module in (error_detected, runaway_handler, escalation, outbound, mute_expiry):
            monkeypatch.setattr(module, "_send_email", None)
        registry_log = MagicMock()
        monkeypatch.setattr(registry, "json_handler", registry_log)
        delivered: List[Any] = []

        def deliver(to_branch: str, email: Dict[str, Any], upsert_key: Any = None) -> tuple:
            delivered.append(email)
            return True, ""

        # Patched at its home: undoing a setattr on the package door would pin the real function there for good.
        monkeypatch.setattr(sys.modules[ai_mail.deliver_email_to_branch.__module__], "deliver_email_to_branch", deliver)
        wired: Dict[str, Any] = {}
        monkeypatch.setattr(core.Trigger, "on", staticmethod(lambda event, handler: wired.setdefault(event, handler)))

        registry.setup_handlers()
        sweep.mute(_expired())
        wired["medic_mute_sweep"]()

        assert wired["medic_mute_sweep"] is mute_expiry.handle_medic_mute_sweep
        assert [(m["to"], m["from"]) for m in delivered] == [("@api", "@trigger")]
        registry_log.log_operation.assert_called_once_with("handlers_registered", {"success": True})
