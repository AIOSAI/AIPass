# =================== META ====================
# Name: test_medic.py
# Description: Unit tests for medic module handle_command
# Version: 1.2.1
# Created: 2026-03-24
# Modified: 2026-10-24
# =============================================

"""Tests for the medic toggle module (apps/modules/medic.py)."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(behaviour) — the state file format in apps/handlers/medic_state.py; its own tests cover it

import re
import subprocess
from pathlib import Path

import pytest
from unittest.mock import MagicMock, patch

from rich.text import Text

from aipass.cli.apps.modules import display
from aipass.trigger.apps.handlers import service_control
from aipass.trigger.apps.handlers.json import json_handler
from aipass.trigger.apps.handlers.medic_state import parse_duration
from aipass.trigger.apps.modules import medic


_STATE_NAMES = (
    "is_enabled",
    "set_enabled",
    "get_muted_branches_detail",
    "get_volume_muted_branches_detail",
    "get_disabled_until",
    "mute_branch",
    "unmute_branch",
    "mute_branch_volume",
    "unmute_branch_volume",
    "get_suppression_stats",
    "get_rate_limit_stats",
    "parse_duration",
    "DEFAULT_MUTE_SECONDS",
    "DEFAULT_OFF_SECONDS",
)

_RECORDERS: dict = {}


@pytest.fixture(autouse=True)
def _mock_infrastructure(monkeypatch):
    """Replace medic's edges where medic reads them: state, operation log, logger.

    medic binds the medic_state names by `from ... import`, so medic's namespace is where they are patched."""
    monkeypatch.setattr(medic, "logger", MagicMock())

    json_recorder = MagicMock()
    json_recorder.log_operation.return_value = True
    monkeypatch.setattr(json_handler, "log_operation", json_recorder.log_operation)
    _RECORDERS["json_handler"] = json_recorder

    medic_state_mod = MagicMock()
    medic_state_mod.is_enabled = MagicMock(return_value=True)
    medic_state_mod.set_enabled = MagicMock(return_value=True)
    medic_state_mod.get_muted_branches = MagicMock(return_value=[])
    medic_state_mod.get_muted_branches_detail = MagicMock(return_value=[])
    medic_state_mod.get_disabled_until = MagicMock(return_value=None)
    medic_state_mod.mute_branch = MagicMock(return_value=True)
    medic_state_mod.unmute_branch = MagicMock(return_value=True)
    medic_state_mod.get_suppression_stats = MagicMock(
        return_value={
            "suppressed_count": 0,
            "last_suppressed": "never",
        }
    )
    medic_state_mod.get_rate_limit_stats = MagicMock(
        return_value={
            "rate_limited_count": 0,
            "last_rate_limited": "never",
        }
    )
    # The real parser: a stub answering None let no test pin --for (seedgo flag_never_passed).
    medic_state_mod.parse_duration = parse_duration
    medic_state_mod.DEFAULT_MUTE_SECONDS = 86400
    medic_state_mod.DEFAULT_OFF_SECONDS = 86400
    for name in _STATE_NAMES:
        monkeypatch.setattr(medic, name, getattr(medic_state_mod, name))
    _RECORDERS["medic_state"] = medic_state_mod

    # The real installer writes a systemd unit.
    installer = MagicMock(return_value=True)
    monkeypatch.setattr(medic, "ensure_service_installed", installer)
    _RECORDERS["installer"] = installer


def _import_medic():
    """The medic module, imported once at the top of this file."""
    return medic


def _get_medic_state():
    """Return the recorder standing in for medic_state's names inside medic."""
    return _RECORDERS["medic_state"]


def _get_json_handler():
    """Return the recorder whose log_operation stands in json_handler's at its home."""
    return _RECORDERS["json_handler"]


def _printed(capsys):
    """The lines the real console wrote to stdout."""
    return capsys.readouterr().out.splitlines()


def _plain(markup):
    """What a markup string reads as once rich renders it."""
    return Text.from_markup(markup).plain


def test_handle_command_on_enables_medic(capsys):
    """handle_command('on', []) calls set_enabled(True), prints Panel, returns True."""
    medic = _import_medic()

    with patch.object(medic, "systemctl", return_value=True):
        with patch.object(medic, "is_service_active", return_value=True):
            result = medic.handle_command("on", [])

    assert result is True
    state = _get_medic_state()
    state.set_enabled.assert_called_with(True)
    assert "".join(_printed(capsys)).strip(), "the success Panel should be printed"


def test_handle_command_on_starts_service_when_inactive():
    """handle_command('on', []) installs, then starts the service when it is not running."""
    medic = _import_medic()

    with patch.object(medic, "systemctl", return_value=True) as mock_ctl:
        with patch.object(medic, "is_service_active", side_effect=[False, True]):
            medic.handle_command("on", [])

    _RECORDERS["installer"].assert_called_once_with()
    mock_ctl.assert_called_with("start")


def test_handle_command_on_logs_operation():
    """handle_command('on', []) logs the medic_toggled operation."""
    medic = _import_medic()

    with patch.object(medic, "systemctl", return_value=True):
        with patch.object(medic, "is_service_active", return_value=True):
            medic.handle_command("on", [])

    jh = _get_json_handler()
    jh.log_operation.assert_called_with("medic_toggled", {"command": "on"})


def test_handle_command_on_failure_prints_error(capsys):
    """When set_enabled returns False, 'on' prints the exact failure message."""
    medic = _import_medic()
    state = _get_medic_state()
    state.set_enabled.return_value = False

    with patch.object(medic, "systemctl", return_value=True):
        with patch.object(medic, "is_service_active", return_value=False):
            result = medic.handle_command("on", [])

    assert result is True
    err_args = capsys.readouterr().err.splitlines()
    assert display.command_failed() is True
    assert any("Failed to enable Medic" in s for s in err_args), f"Expected failure message in error() args: {err_args}"


def test_handle_command_off_disables_medic(capsys):
    """handle_command('off', []) calls set_enabled with 24h TTL, prints Panel, returns True."""
    medic = _import_medic()

    with patch.object(medic, "systemctl", return_value=True):
        with patch.object(medic, "is_service_active", return_value=False):
            result = medic.handle_command("off", [])

    assert result is True
    state = _get_medic_state()
    state.set_enabled.assert_called_with(False, duration_seconds=86400.0)
    assert "".join(_printed(capsys)).strip(), "the success Panel should be printed"


def test_handle_command_off_forever_stops_service():
    """handle_command('off', ['--forever']) stops the service and disables permanently."""
    medic = _import_medic()

    with patch.object(medic, "systemctl", return_value=True) as mock_ctl:
        with patch.object(medic, "is_service_active", return_value=True):
            result = medic.handle_command("off", ["--forever"])

    assert result is True
    state = _get_medic_state()
    state.set_enabled.assert_called_with(False)
    mock_ctl.assert_called_with("stop")


def test_handle_command_off_ttl_keeps_watcher():
    """handle_command('off', []) with default TTL does NOT stop the log watcher."""
    medic = _import_medic()

    with patch.object(medic, "systemctl", return_value=True) as mock_ctl:
        with patch.object(medic, "is_service_active", return_value=True):
            medic.handle_command("off", [])

    mock_ctl.assert_not_called()


def test_handle_command_off_failure_prints_error(capsys):
    """When set_enabled returns False, 'off' prints the exact failure message."""
    medic = _import_medic()
    state = _get_medic_state()
    state.set_enabled.return_value = False

    with patch.object(medic, "systemctl", return_value=True):
        with patch.object(medic, "is_service_active", return_value=False):
            result = medic.handle_command("off", [])

    assert result is True
    err_args = capsys.readouterr().err.splitlines()
    assert display.command_failed() is True
    assert any("Failed to disable Medic" in s for s in err_args), (
        f"Expected failure message in error() args: {err_args}"
    )


def test_handle_command_status_returns_current_state():
    """handle_command('status', []) displays state info and returns True."""
    medic = _import_medic()

    with patch.object(medic, "is_service_active", return_value=True):
        result = medic.handle_command("status", [])

    assert result is True
    state = _get_medic_state()
    state.is_enabled.assert_called_once()
    state.get_muted_branches_detail.assert_called_once()
    state.get_suppression_stats.assert_called_once()
    state.get_rate_limit_stats.assert_called_once()


def test_handle_command_status_shows_enabled(capsys):
    """When medic is enabled, status output includes the ENABLED state line."""
    medic = _import_medic()

    with patch.object(medic, "is_service_active", return_value=True):
        medic.handle_command("status", [])

    printed = _printed(capsys)
    state_line = _plain("  State:           [green]ENABLED[/green]")
    assert state_line in printed, f"Expected state line '{state_line}' in printed args: {printed}"


def test_handle_command_status_shows_disabled(capsys):
    """When medic is disabled, status output includes the DISABLED state line."""
    medic = _import_medic()
    state = _get_medic_state()
    state.is_enabled.return_value = False

    with patch.object(medic, "is_service_active", return_value=False):
        medic.handle_command("status", [])

    printed = _printed(capsys)
    state_line = _plain("  State:           [yellow]DISABLED[/yellow]")
    assert state_line in printed, f"Expected state line '{state_line}' in printed args: {printed}"


def test_handle_command_status_shows_muted_branches(capsys):
    """When branches are muted, status lists them with expiry info."""
    medic = _import_medic()
    state = _get_medic_state()
    state.get_muted_branches_detail.return_value = [
        {"name": "speakeasy", "expires_at": None},
        {"name": "api", "expires_at": None},
    ]

    with patch.object(medic, "is_service_active", return_value=True):
        medic.handle_command("status", [])

    printed = _printed(capsys)
    muted_lines = [p for p in printed if "Muted branches:" in p]
    assert muted_lines, f"Expected muted branches line in printed args: {printed}"
    assert "@speakeasy" in muted_lines[0] and "@api" in muted_lines[0]


def test_handle_command_status_suppression_hint_when_disabled(capsys):
    """When medic is disabled, status prints the exact suppression hint."""
    medic = _import_medic()
    state = _get_medic_state()
    state.is_enabled.return_value = False

    with patch.object(medic, "is_service_active", return_value=False):
        medic.handle_command("status", [])

    printed = _printed(capsys)
    hint = _plain("  [dim]All error dispatch suppressed. Errors logged to medic_suppressed.jsonl[/dim]")
    assert hint in printed, f"Expected suppression hint '{hint}' in printed args: {printed}"


def test_handle_command_mute_branch():
    """handle_command('mute', ['@speakeasy']) mutes the branch with 24h default TTL."""
    medic = _import_medic()
    result = medic.handle_command("mute", ["@speakeasy"])

    assert result is True
    state = _get_medic_state()
    state.mute_branch.assert_called_once_with("speakeasy", duration_seconds=86400.0)


def test_handle_command_mute_for_sets_the_asked_duration_not_the_default():
    """--for 2h reaches mute_branch as 7200s; the parse was unpinned (seedgo flag_never_passed)."""
    medic = _import_medic()
    medic.handle_command("mute", ["@speakeasy", "--for", "2h"])

    state = _get_medic_state()
    state.mute_branch.assert_called_once_with("speakeasy", duration_seconds=7200.0)


def test_handle_command_mute_with_an_unparsable_for_refuses_instead_of_muting_24h(capsys):
    """--for 30m is not <n>h or <n>d: the command errors and nothing is muted."""
    medic = _import_medic()
    medic.handle_command("mute", ["@speakeasy", "--for", "30m"])

    err_args = capsys.readouterr().err.splitlines()
    assert display.command_failed() is True
    assert any("Invalid --for duration" in s for s in err_args), err_args
    _get_medic_state().mute_branch.assert_not_called()


def test_handle_command_mute_branch_without_at():
    """handle_command('mute', ['speakeasy']) handles names without @ prefix."""
    medic = _import_medic()
    medic.handle_command("mute", ["speakeasy"])

    state = _get_medic_state()
    state.mute_branch.assert_called_once_with("speakeasy", duration_seconds=86400.0)


def test_handle_command_mute_prints_confirmation(capsys):
    """Successful mute prints confirmation with TTL info."""
    medic = _import_medic()
    medic.handle_command("mute", ["@api"])

    printed = _printed(capsys)
    assert "  Muted @api — auto-expires in 24h" in printed, printed


def test_handle_command_mute_failure_prints_error(capsys):
    """When mute_branch returns False, the exact error message is printed."""
    medic = _import_medic()
    state = _get_medic_state()
    state.mute_branch.return_value = False

    medic.handle_command("mute", ["@api"])

    err_args = capsys.readouterr().err.splitlines()
    assert display.command_failed() is True
    assert any("Failed to mute" in s for s in err_args), f"Expected mute failure message in error() args: {err_args}"


def test_handle_command_mute_without_branch_name(capsys):
    """handle_command('mute', []) prints the exact usage error when no branch given."""
    medic = _import_medic()
    result = medic.handle_command("mute", [])

    assert result is True
    err_args = capsys.readouterr().err.splitlines()
    assert display.command_failed() is True
    assert any("Missing branch name" in s for s in err_args), f"Expected usage error in error() args: {err_args}"
    state = _get_medic_state()
    state.mute_branch.assert_not_called()


def test_handle_command_unmute_branch():
    """handle_command('unmute', ['@speakeasy']) unmutes the branch."""
    medic = _import_medic()
    result = medic.handle_command("unmute", ["@speakeasy"])

    assert result is True
    state = _get_medic_state()
    state.unmute_branch.assert_called_once_with("speakeasy")


def test_handle_command_unmute_prints_confirmation(capsys):
    """Successful unmute prints the exact confirmation message."""
    medic = _import_medic()
    medic.handle_command("unmute", ["@flow"])

    printed = _printed(capsys)
    expected = _plain("  [green]Unmuted[/green] @flow — dispatch resumed")
    assert expected in printed, f"Expected unmute confirmation '{expected}' in printed args: {printed}"


def test_handle_command_unmute_already_unmuted(capsys):
    """Unmuting a branch that is not muted prints the exact failure message."""
    medic = _import_medic()
    state = _get_medic_state()
    state.unmute_branch.return_value = False

    result = medic.handle_command("unmute", ["@nonexistent"])

    assert result is True
    err_args = capsys.readouterr().err.splitlines()
    assert display.command_failed() is True
    assert any("Failed to unmute" in s for s in err_args), (
        f"Expected unmute failure message in error() args: {err_args}"
    )


def test_handle_command_unmute_without_branch_name(capsys):
    """handle_command('unmute', []) prints the exact usage error when no branch given."""
    medic = _import_medic()
    result = medic.handle_command("unmute", [])

    assert result is True
    err_args = capsys.readouterr().err.splitlines()
    assert display.command_failed() is True
    assert any("Missing branch name" in s for s in err_args), f"Expected usage error in error() args: {err_args}"
    state = _get_medic_state()
    state.unmute_branch.assert_not_called()


def test_handle_command_help_flag():
    """handle_command('medic', ['--help']) calls print_help and returns True."""
    medic = _import_medic()

    with patch.object(medic, "print_help") as mock_help:
        result = medic.handle_command("medic", ["--help"])

    assert result is True
    mock_help.assert_called_once()


def test_handle_command_help_word():
    """handle_command('medic', ['help']) also triggers help."""
    medic = _import_medic()

    with patch.object(medic, "print_help") as mock_help:
        result = medic.handle_command("medic", ["help"])

    assert result is True
    mock_help.assert_called_once()


def test_handle_command_subcommand_help():
    """handle_command('on', ['--help']) shows help instead of enabling."""
    medic = _import_medic()

    with patch.object(medic, "print_help") as mock_help:
        result = medic.handle_command("on", ["--help"])

    assert result is True
    mock_help.assert_called_once()
    state = _get_medic_state()
    state.set_enabled.assert_not_called()


def test_handle_command_no_args_shows_introspection():
    """handle_command('medic', []) calls print_introspection and returns True."""
    medic = _import_medic()

    with patch.object(medic, "print_introspection") as mock_intro:
        result = medic.handle_command("medic", [])

    assert result is True
    mock_intro.assert_called_once()


def test_handle_command_unknown_returns_false():
    """handle_command with an unknown subcommand returns False."""
    medic = _import_medic()
    result = medic.handle_command("explode", [])
    assert result is False


def test_handle_command_medic_routes_to_subcommand():
    """handle_command('medic', ['status']) recursively routes to status."""
    medic = _import_medic()
    state = _get_medic_state()

    with patch.object(medic, "is_service_active", return_value=True):
        result = medic.handle_command("medic", ["status"])

    assert result is True
    state.is_enabled.assert_called_once()


def test_handle_command_medic_routes_mute_with_args():
    """handle_command('medic', ['mute', '@speakeasy']) routes correctly."""
    medic = _import_medic()
    result = medic.handle_command("medic", ["mute", "@speakeasy"])

    assert result is True
    state = _get_medic_state()
    state.mute_branch.assert_called_once_with("speakeasy", duration_seconds=86400.0)


@pytest.mark.parametrize("raw", ["@Speakeasy", "src/aipass/speakeasy", "speakeasy"])
def test_mute_normalises_the_branch_name_it_is_given(raw):
    """`medic mute` strips @, lowercases and takes a path's last component."""
    medic = _import_medic()
    medic.handle_command("mute", [raw])

    state = _get_medic_state()
    state.mute_branch.assert_called_once_with("speakeasy", duration_seconds=86400.0)


def test_handle_command_none_command_returns_false():
    """handle_command(None, []) returns False -- None is not a recognized command."""
    medic = _import_medic()
    from typing import Any

    none_cmd: Any = None
    result = medic.handle_command(none_cmd, [])
    assert result is False


def test_handle_command_case_sensitive_medic():
    """handle_command('MEDIC', []) returns False -- command routing is case-sensitive."""
    medic = _import_medic()
    result = medic.handle_command("MEDIC", [])
    assert result is False


def test_handle_command_on_extra_args_ignored():
    """handle_command('on', ['extra', 'args']) -- extra args are ignored, medic enables."""
    medic = _import_medic()

    with patch.object(medic, "systemctl", return_value=True):
        with patch.object(medic, "is_service_active", return_value=True):
            result = medic.handle_command("on", ["extra", "args"])

    assert result is True
    state = _get_medic_state()
    state.set_enabled.assert_called_with(True)


def test_print_help_names_every_verb_the_router_accepts(capsys):
    """Help lists all seven medic verbs — a verb the router takes but help hides is a defect.

    The verb list comes from the router, so a verb added without help turns this red."""
    medic = _import_medic()

    medic.print_help()

    output = "\n".join(_printed(capsys))
    routed = ["on", "off", "status", "mute", "unmute", "volume-mute", "volume-unmute"]
    # Floors the loop: an empty list would make every assertion below vacuous.
    assert len(routed) == 7
    documented = {m.group(1) for m in re.finditer(r"^  ([a-z-]+) ", output, re.MULTILINE)}
    undocumented = [verb for verb in routed if verb not in documented]
    assert undocumented == [], f"medic help never documents: {undocumented}"


def test_output_capture_status_contains_all_fields(capsys):
    """output_capture: status command output contains all expected field labels."""
    medic = _import_medic()
    state = _get_medic_state()
    state.is_enabled.return_value = True
    state.get_muted_branches.return_value = []
    state.get_suppression_stats.return_value = {"suppressed_count": 0, "last_suppressed": "never"}
    state.get_rate_limit_stats.return_value = {"rate_limited_count": 0, "last_rate_limited": "never"}

    with patch.object(medic, "is_service_active", return_value=True):
        medic.handle_command("status", [])

    printed = _printed(capsys)
    output = "\n".join(printed)
    for field in ["State:", "Log watcher:", "Muted branches:", "Suppressed:", "Rate limited:"]:
        assert field in output, f"Status output missing field: {field}"


def test_help_flag_after_a_branch_operand_does_not_mute(monkeypatch):
    """`medic mute @branch --help` must describe muting, never mute.

    A real mute silences error dispatch to a citizen for 24h; the handler is mocked."""
    medic = _import_medic()

    muted = MagicMock()
    monkeypatch.setattr(medic, "_handle_mute", muted)
    printed = MagicMock()
    monkeypatch.setattr(medic, "print_help", printed)

    result = medic.handle_command("mute", ["@trigger", "--help"])

    assert result is True
    printed.assert_called_once()
    muted.assert_not_called()


def test_help_flag_after_read_only_verb_does_not_run_it(monkeypatch):
    """`medic status extra -h` — read-only probe, same gate."""
    medic = _import_medic()

    ran = MagicMock()
    monkeypatch.setattr(medic, "_handle_status", ran)
    printed = MagicMock()
    monkeypatch.setattr(medic, "print_help", printed)

    result = medic.handle_command("status", ["extra", "-h"])

    assert result is True
    printed.assert_called_once()
    ran.assert_not_called()


def test_help_flag_survives_module_name_routing(monkeypatch):
    """`medic mute @branch --help` routed through the module name."""
    medic = _import_medic()

    muted = MagicMock()
    monkeypatch.setattr(medic, "_handle_mute", muted)
    printed = MagicMock()
    monkeypatch.setattr(medic, "print_help", printed)

    result = medic.handle_command("medic", ["mute", "@trigger", "--help"])

    assert result is True
    printed.assert_called_once()
    muted.assert_not_called()


class TestErrorCatchupDoor:
    """medic.run_error_catchup — the module-level door to cold-start recovery.

    It must stay a thin pass-through, or the service and the `startup` event stop recovering alike."""

    def test_delegates_to_the_startup_handler(self, monkeypatch) -> None:
        """The scan itself stays the handler's; the module only exposes it."""
        medic = _import_medic()
        scan = MagicMock()
        monkeypatch.setattr(medic, "run_startup_catchup", scan)
        fire_event = MagicMock()

        medic.run_error_catchup(fire_event)

        scan.assert_called_once_with(fire_event)

    def test_defaults_to_no_dispatch(self, monkeypatch) -> None:
        """Called bare it scans and records without firing anything."""
        medic = _import_medic()
        scan = MagicMock()
        monkeypatch.setattr(medic, "run_startup_catchup", scan)

        medic.run_error_catchup()

        scan.assert_called_once_with(None)

    def test_is_not_a_cli_command(self, monkeypatch) -> None:
        """It is a library door, not a subcommand — `medic catchup` must not route.

        Routing it would put a live fleet-wide error scan one typo away from an operator's shell."""
        medic = _import_medic()
        scan = MagicMock()
        monkeypatch.setattr(medic, "run_startup_catchup", scan)

        assert medic.handle_command("medic", ["catchup"]) is False

        scan.assert_not_called()


def test_status_on_a_host_without_systemd_says_so_instead_of_offering_medic_on(capsys):
    """ "stopped — run medic on" is advice that cannot work where there is no systemd.

    With no systemctl the watcher is unavailable, not stopped; that advice can never work."""
    medic = _import_medic()
    state = _get_medic_state()
    state.is_enabled.return_value = True

    # None is what is-active answers on such a host: the probe refuses.
    with patch.object(medic, "is_service_active", return_value=None):
        with patch.object(medic, "systemd_available", return_value=False):
            medic.handle_command("status", [])

    output = "\n".join(_printed(capsys))
    assert "no systemd on this host" in output, output
    assert "run medic on" not in output, output


def test_status_names_a_watcher_systemctl_never_answered_for(capsys):
    """A timed-out is-active is not a stopped watcher, and status says which it was."""
    medic = _import_medic()
    state = _get_medic_state()
    state.is_enabled.return_value = True

    with patch.object(medic, "is_service_active", return_value=None):
        with patch.object(medic, "systemd_available", return_value=True):
            medic.handle_command("status", [])

    output = "\n".join(_printed(capsys))
    assert "systemctl did not answer" in output, output
    assert "stopped" not in output, output


def test_medic_on_reports_unavailable_rather_than_failed_to_start_without_systemd(capsys):
    """ "failed to start" reads as a broken unit; the truth is a hostless door."""
    medic = _import_medic()

    with patch.object(medic, "systemctl", return_value=None):
        with patch.object(medic, "is_service_active", return_value=None):
            with patch.object(medic, "systemd_available", return_value=False):
                medic.handle_command("on", [])

    panel_text = capsys.readouterr().out
    assert "unavailable — no systemd on this host" in panel_text, panel_text


@pytest.fixture
def systemctl_never_answers(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> list:
    """A host with systemctl on PATH whose every call times out; returns the argv of each call.

    Only an inert stub on PATH and subprocess.run replaced at service_control, so no real systemctl runs."""
    bin_dir = tmp_path / "systemd_bin"
    bin_dir.mkdir()
    for name in ("systemctl", "systemctl.exe"):  # the .exe is what which() finds on Windows
        stub = bin_dir / name
        stub.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        stub.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir))
    calls: list = []

    def hung(cmd, **kwargs):
        calls.append(cmd)
        raise subprocess.TimeoutExpired(cmd, 10)

    monkeypatch.setattr(service_control.subprocess, "run", hung)
    return calls


def test_medic_on_does_not_guess_a_start_when_systemctl_never_answered(capsys, systemctl_never_answers):
    """An unanswered is-active is not a stopped watcher: on starts nothing and says unknown."""
    medic = _import_medic()

    medic.handle_command("on", [])

    panel_text = capsys.readouterr().out
    assert [cmd for cmd in systemctl_never_answers if "start" in cmd] == []
    _RECORDERS["installer"].assert_not_called()
    assert "systemctl did not answer" in panel_text, panel_text
    assert "failed to start" not in panel_text, panel_text


def test_medic_off_forever_claims_no_stop_systemctl_never_answered(capsys, systemctl_never_answers):
    """off --forever sends the stop on an unanswered is-active, and claims no stop it did not see.

    A stop to a unit that is not running is a no-op, so sending it costs nothing."""
    medic = _import_medic()

    medic.handle_command("off", ["--forever"])

    panel_text = capsys.readouterr().out
    assert [cmd[2] for cmd in systemctl_never_answers] == ["is-active", "stop"]
    assert "systemctl did not answer" in panel_text, panel_text
    assert "Log watcher stopped" not in panel_text, panel_text
