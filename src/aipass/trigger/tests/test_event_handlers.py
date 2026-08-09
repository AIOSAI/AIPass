# =================== AIPass ====================
# Name: test_event_handlers.py
# Description: Tests for simple event handler functions and the warning escalation lane
# Version: 1.1.0
# Created: 2026-04-25
# Modified: 2026-08-08
# =============================================

"""Tests for cli, memory_template_updated, and warning_logged event handlers."""

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List
from unittest.mock import MagicMock

import pytest
from aipass.trigger.apps.config import trail_logger


@pytest.fixture(autouse=True)
def _mock_infrastructure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Mock heavy infrastructure imports for all six handler modules."""
    from aipass.trigger.apps.config import atomic_write_json, migrate_json_file

    mock_config = MagicMock()
    mock_config.TRIGGER_ROOT = tmp_path
    mock_config.AIPASS_PKG_ROOT = tmp_path / "aipass"
    mock_config.atomic_write_json = atomic_write_json
    mock_config.TRIGGER_JSON_DIR = tmp_path / "trigger_json"
    mock_config.migrate_json_file = migrate_json_file
    monkeypatch.setitem(sys.modules, "aipass.trigger.apps.config", mock_config)

    mock_json_handler = MagicMock()
    mock_json_handler.log_operation = MagicMock(return_value=True)
    json_pkg = MagicMock()
    json_pkg.json_handler = mock_json_handler
    monkeypatch.setitem(sys.modules, "aipass.trigger.apps.handlers.json", json_pkg)
    monkeypatch.setitem(
        sys.modules,
        "aipass.trigger.apps.handlers.json.json_handler",
        mock_json_handler,
    )

    for mod_name in (
        "aipass.trigger.apps.handlers.events.cli",
        "aipass.trigger.apps.handlers.events.memory_template_updated",
        "aipass.trigger.apps.handlers.events.warning_logged",
    ):
        monkeypatch.delitem(sys.modules, mod_name, raising=False)


def _import_cli():
    """Import cli handler module fresh after mocking."""
    import aipass.trigger.apps.handlers.events.cli as m

    return m


def _import_memory_template_updated():
    """Import memory_template_updated handler module fresh after mocking."""
    import aipass.trigger.apps.handlers.events.memory_template_updated as m

    return m


def _import_warning_logged():
    """Import warning_logged handler module fresh after mocking."""
    import aipass.trigger.apps.handlers.events.warning_logged as m

    return m


# ---------------------------------------------------------------------------
# cli.py -- handle_cli_header_displayed
# ---------------------------------------------------------------------------


class TestHandleCliHeaderDisplayed:
    """Tests for handle_cli_header_displayed from cli.py."""

    def test_calls_log_operation(self) -> None:
        """Logs cli_event via json_handler."""
        mod = _import_cli()
        from aipass.trigger.apps.handlers.json import json_handler

        json_handler.log_operation.reset_mock()  # type: ignore[union-attr]

        mod.handle_cli_header_displayed()

        json_handler.log_operation.assert_called_once_with(  # type: ignore[union-attr]
            "cli_event", {"success": True}
        )

    def test_accepts_arbitrary_kwargs(self) -> None:
        """Does not crash when extra kwargs are passed."""
        mod = _import_cli()
        mod.handle_cli_header_displayed(foo="bar", baz=42)

    def test_returns_none(self) -> None:
        """Handler returns None (handlers must not return values)."""
        mod = _import_cli()
        result = mod.handle_cli_header_displayed()
        assert result is None


# ---------------------------------------------------------------------------
# memory_template_updated.py -- handle_memory_template_updated
# ---------------------------------------------------------------------------


class TestHandleMemoryTemplateUpdated:
    """Tests for handle_memory_template_updated from memory_template_updated.py."""

    def test_calls_log_operation(self) -> None:
        """Logs memory_template_event via json_handler."""
        mod = _import_memory_template_updated()
        from aipass.trigger.apps.handlers.json import json_handler

        json_handler.log_operation.reset_mock()  # type: ignore[union-attr]

        mod.handle_memory_template_updated()

        json_handler.log_operation.assert_called_once_with(  # type: ignore[union-attr]
            "memory_template_event", {"success": True}
        )

    def test_accepts_kwargs(self) -> None:
        """Does not crash when event data kwargs are passed."""
        mod = _import_memory_template_updated()
        mod.handle_memory_template_updated(template_name="local", updated_by="drone")

    def test_returns_none(self) -> None:
        """Handler returns None."""
        mod = _import_memory_template_updated()
        result = mod.handle_memory_template_updated()
        assert result is None


# ---------------------------------------------------------------------------
# warning_logged.py -- handle_warning_logged
# ---------------------------------------------------------------------------


class TestHandleWarningLogged:
    """Tests for handle_warning_logged from warning_logged.py."""

    def test_calls_log_operation(self) -> None:
        """Logs warning_logged_event via json_handler."""
        mod = _import_warning_logged()
        from aipass.trigger.apps.handlers.json import json_handler

        json_handler.log_operation.reset_mock()  # type: ignore[union-attr]

        mod.handle_warning_logged()

        json_handler.log_operation.assert_called_once_with(  # type: ignore[union-attr]
            "warning_logged_event", {"success": True}
        )

    def test_accepts_all_named_params(self) -> None:
        """Accepts all documented event parameters without error."""
        mod = _import_warning_logged()
        mod.handle_warning_logged(
            branch="flow",
            message="disk almost full",
            error_hash="w1",
            timestamp="2026-04-25T12:00:00",
            log_file="flow.log",
            module_name="watcher",
            level="warning",
        )

    def test_does_not_crash_with_none_params(self) -> None:
        """Handles None for every named parameter gracefully."""
        mod = _import_warning_logged()
        mod.handle_warning_logged(
            branch=None,
            message=None,
            error_hash=None,
            timestamp=None,
            log_file=None,
            module_name=None,
            level=None,
        )

    def test_accepts_extra_kwargs(self) -> None:
        """Accepts unexpected kwargs via **kwargs."""
        mod = _import_warning_logged()
        mod.handle_warning_logged(extra_field="unexpected")

    def test_returns_none(self) -> None:
        """Handler returns None."""
        mod = _import_warning_logged()
        result = mod.handle_warning_logged()
        assert result is None


# ---------------------------------------------------------------------------
# warning_logged.py -- escalation lane (DPLAN-0283 WS-A)
# ---------------------------------------------------------------------------


@pytest.fixture
def lane(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> SimpleNamespace:
    """The escalation lane on a tmp state file with a known threshold.

    handle_warning_logged records into the real lane module, so the state file,
    the config and the digest callback are pinned here — the operator's config
    never decides a test outcome, and no digest can leave the process.
    """
    from aipass.trigger.apps.handlers import escalation

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

    Before this lane a warning loop was invisible to humans forever, so the
    handler's real job is feeding the counter — not notifying anyone.
    """

    def test_warning_is_counted(self, lane) -> None:
        """One warning lands in the lane as a WARNING signature."""
        mod = _import_warning_logged()

        mod.handle_warning_logged(branch="flow", message="queue depth 91%", module_name="watcher")

        rows = lane.mod.get_signatures()
        assert len(rows) == 1
        assert rows[0]["level"] == "WARNING"
        assert rows[0]["branch"] == "flow"
        assert rows[0]["module"] == "watcher"

    def test_module_name_defaults_to_unknown(self, lane) -> None:
        """A warning with no module still counts, under a named placeholder."""
        mod = _import_warning_logged()

        mod.handle_warning_logged(branch="flow", message="queue depth 91%")

        assert lane.mod.get_signatures()[0]["module"] == "unknown"

    def test_context_travels_into_the_lane(self, lane) -> None:
        """Log path and raw line are what make the eventual digest actionable."""
        mod = _import_warning_logged()

        mod.handle_warning_logged(
            branch="flow",
            message="queue depth 91%",
            module_name="watcher",
            log_file="/logs/flow.log",
            raw_line="2026-08-08 | watcher | WARNING | queue depth 91%",
        )

        row = lane.mod.get_signatures()[0]
        assert row["log_file"] == "/logs/flow.log"
        assert row["samples"] == ["2026-08-08 | watcher | WARNING | queue depth 91%"]

    def test_repeats_with_variable_paths_share_one_signature(self, lane) -> None:
        """The same warning about different files is one repeating warning."""
        mod = _import_warning_logged()

        mod.handle_warning_logged(branch="flow", message="cannot read /home/a/x.json", module_name="watcher")
        mod.handle_warning_logged(branch="flow", message="cannot read /srv/b/y.json", module_name="watcher")

        rows = lane.mod.get_signatures()
        assert len(rows) == 1
        assert rows[0]["total_count"] == 2

    def test_different_branches_do_not_pool(self, lane) -> None:
        """Two branches warning identically are two separate signatures."""
        mod = _import_warning_logged()

        mod.handle_warning_logged(branch="flow", message="queue depth 91%", module_name="watcher")
        mod.handle_warning_logged(branch="memory", message="queue depth 91%", module_name="watcher")

        assert len(lane.mod.get_signatures()) == 2

    def test_repeat_crosses_the_threshold_and_emails_once(self, lane) -> None:
        """The point of the lane: repetition reaches a human, exactly once."""
        mod = _import_warning_logged()

        for _ in range(2):
            mod.handle_warning_logged(branch="flow", message="queue depth 91%", module_name="watcher")

        assert len(lane.digests) == 1
        assert lane.digests[0]["to_branch"] == "@digest-inbox"
        assert lane.digests[0]["auto_execute"] is False
        assert "queue depth 91%" in lane.digests[0]["message"]

    def test_missing_branch_records_nothing(self, lane) -> None:
        """A warning with nothing to attribute it to is not countable."""
        mod = _import_warning_logged()

        mod.handle_warning_logged(branch=None, message="queue depth 91%", module_name="watcher")

        assert lane.mod.get_signatures() == []

    def test_missing_message_records_nothing(self, lane) -> None:
        """There is no signature without a message."""
        mod = _import_warning_logged()

        mod.handle_warning_logged(branch="flow", message=None, module_name="watcher")

        assert lane.mod.get_signatures() == []

    def test_event_is_still_logged_when_the_lane_is_off(self, lane) -> None:
        """Switching the lane off must not change the handler's own contract."""
        mod = _import_warning_logged()
        from aipass.trigger.apps.handlers.json import json_handler

        lane.config["enabled"] = False
        json_handler.log_operation.reset_mock()  # type: ignore[union-attr]

        mod.handle_warning_logged(branch="flow", message="queue depth 91%", module_name="watcher")

        assert lane.mod.get_signatures() == []
        json_handler.log_operation.assert_called_once_with(  # type: ignore[union-attr]
            "warning_logged_event", {"success": True}
        )
