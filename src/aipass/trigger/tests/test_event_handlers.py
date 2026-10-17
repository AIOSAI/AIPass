# =================== AIPass ====================
# Name: test_event_handlers.py
# Description: Tests for simple event handler functions and the warning escalation lane
# Version: 1.1.0
# Created: 2026-04-25
# Modified: 2026-10-17
# =============================================

"""Tests for apps/handlers/events/memory_template_updated.py and warning_logged.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(behaviour) — the lane internals in apps/handlers/escalation.py; the escalation tests cover them

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List
from unittest.mock import MagicMock

import pytest
from aipass.trigger.apps.config import trail_logger
from aipass.trigger.apps.handlers import escalation
from aipass.trigger.apps.handlers.events import memory_template_updated, warning_logged


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
    monkeypatch.setattr(escalation, "logger", trail_logger(tmp_path / "escalation.jsonl"))
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
