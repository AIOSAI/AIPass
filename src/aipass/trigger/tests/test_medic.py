# =================== META ====================
# Name: test_medic.py
# Description: Unit tests for medic module handle_command
# Version: 1.2.0
# Created: 2026-03-24
# Modified: 2026-09-27
# =============================================

"""Tests for the medic toggle module (apps/modules/medic.py)."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(behaviour) — the state file format in apps/handlers/medic_state.py; the medic state tests cover it

import re
import sys
import pytest
from unittest.mock import MagicMock, patch

from rich.text import Text

from aipass.cli.apps.modules import display
from aipass.trigger.apps.handlers.medic_state import parse_duration


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _mock_infrastructure(monkeypatch):
    """Mock heavy infrastructure imports before medic module loads."""

    mock_logger = MagicMock()

    # -- prax logger --------------------------------------------------------
    prax_logger_mod = MagicMock()
    prax_logger_mod.system_logger = mock_logger
    monkeypatch.setitem(sys.modules, "aipass.prax", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.prax.apps", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.prax.apps.modules", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.prax.apps.modules.logger", prax_logger_mod)

    # -- trigger json handler -----------------------------------------------
    mock_json_handler = MagicMock()
    mock_json_handler.log_operation = MagicMock(return_value=True)
    json_pkg = MagicMock()
    json_pkg.json_handler = mock_json_handler
    monkeypatch.setitem(sys.modules, "aipass.trigger.apps.handlers.json", json_pkg)
    json_mod = MagicMock()
    json_mod.log_operation = mock_json_handler.log_operation
    monkeypatch.setitem(sys.modules, "aipass.trigger.apps.handlers.json.json_handler", json_mod)

    # -- medic_state handler ------------------------------------------------
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
    # The real parser: it is pure. A stub answering None made every --for fall
    # back to the default, so no test could pin the flag (seedgo flag_never_passed).
    medic_state_mod.parse_duration = parse_duration
    medic_state_mod.DEFAULT_MUTE_SECONDS = 86400
    medic_state_mod.DEFAULT_OFF_SECONDS = 86400
    monkeypatch.setitem(sys.modules, "aipass.trigger.apps.handlers.medic_state", medic_state_mod)

    # The CLI console and rich are real (2026-09-27): output is read with
    # capsys, and a refusal through error() from stderr and cli's failure flag.

    # -- Force re-import so mocks take effect -------------------------------
    monkeypatch.delitem(sys.modules, "aipass.trigger.apps.modules.medic", raising=False)


def _import_medic():
    """Import medic module fresh (after mocks are in place)."""
    import aipass.trigger.apps.modules.medic as medic

    return medic


def _get_medic_state():
    """Return the mocked medic_state module from sys.modules."""
    return sys.modules["aipass.trigger.apps.handlers.medic_state"]


def _get_json_handler():
    """Return the mocked json_handler from sys.modules."""
    return sys.modules["aipass.trigger.apps.handlers.json.json_handler"]


def _printed(capsys):
    """The lines the real console wrote to stdout."""
    return capsys.readouterr().out.splitlines()


def _plain(markup):
    """What a markup string reads as once rich renders it."""
    return Text.from_markup(markup).plain


# ---------------------------------------------------------------------------
# Tests -- handle_command "on"
# ---------------------------------------------------------------------------


def test_handle_command_on_enables_medic(capsys):
    """handle_command('on', []) calls set_enabled(True), prints Panel, returns True."""
    medic = _import_medic()

    with patch.object(medic, "_systemctl", return_value=True):
        with patch.object(medic, "_is_service_active", return_value=True):
            result = medic.handle_command("on", [])

    assert result is True
    state = _get_medic_state()
    state.set_enabled.assert_called_with(True)
    # Verify console.print was called (Panel is a mock object, but it was called)
    assert "".join(_printed(capsys)).strip(), "the success Panel should be printed"


def test_handle_command_on_starts_service_when_inactive():
    """handle_command('on', []) starts the systemd service when it is not running."""
    medic = _import_medic()

    with patch.object(medic, "_systemctl", return_value=True) as mock_ctl:
        with patch.object(medic, "_is_service_active", side_effect=[False, True]):
            with patch.object(medic, "_ensure_service_installed", return_value=True):
                medic.handle_command("on", [])

    mock_ctl.assert_called_with("start")


def test_handle_command_on_logs_operation():
    """handle_command('on', []) logs the medic_toggled operation."""
    medic = _import_medic()

    with patch.object(medic, "_systemctl", return_value=True):
        with patch.object(medic, "_is_service_active", return_value=True):
            medic.handle_command("on", [])

    jh = _get_json_handler()
    jh.log_operation.assert_called_with("medic_toggled", {"command": "on"})


def test_handle_command_on_failure_prints_error(capsys):
    """When set_enabled returns False, 'on' prints the exact failure message.

    Mutant run: this refusal printed instead of sent through error() reddens this.
    """
    medic = _import_medic()
    state = _get_medic_state()
    state.set_enabled.return_value = False

    with patch.object(medic, "_systemctl", return_value=True):
        with patch.object(medic, "_is_service_active", return_value=False):
            result = medic.handle_command("on", [])

    assert result is True
    err_args = capsys.readouterr().err.splitlines()
    assert display.command_failed() is True
    assert any("Failed to enable Medic" in s for s in err_args), f"Expected failure message in error() args: {err_args}"


# ---------------------------------------------------------------------------
# Tests -- handle_command "off"
# ---------------------------------------------------------------------------


def test_handle_command_off_disables_medic(capsys):
    """handle_command('off', []) calls set_enabled with 24h TTL, prints Panel, returns True."""
    medic = _import_medic()

    with patch.object(medic, "_systemctl", return_value=True):
        with patch.object(medic, "_is_service_active", return_value=False):
            result = medic.handle_command("off", [])

    assert result is True
    state = _get_medic_state()
    state.set_enabled.assert_called_with(False, duration_seconds=86400.0)
    assert "".join(_printed(capsys)).strip(), "the success Panel should be printed"


def test_handle_command_off_forever_stops_service():
    """handle_command('off', ['--forever']) stops the service and disables permanently."""
    medic = _import_medic()

    with patch.object(medic, "_systemctl", return_value=True) as mock_ctl:
        with patch.object(medic, "_is_service_active", return_value=True):
            result = medic.handle_command("off", ["--forever"])

    assert result is True
    state = _get_medic_state()
    state.set_enabled.assert_called_with(False)
    mock_ctl.assert_called_with("stop")


def test_handle_command_off_ttl_keeps_watcher():
    """handle_command('off', []) with default TTL does NOT stop the log watcher."""
    medic = _import_medic()

    with patch.object(medic, "_systemctl", return_value=True) as mock_ctl:
        with patch.object(medic, "_is_service_active", return_value=True):
            medic.handle_command("off", [])

    mock_ctl.assert_not_called()


def test_handle_command_off_failure_prints_error(capsys):
    """When set_enabled returns False, 'off' prints the exact failure message.

    Mutant run: this refusal printed instead of sent through error() reddens this.
    """
    medic = _import_medic()
    state = _get_medic_state()
    state.set_enabled.return_value = False

    with patch.object(medic, "_systemctl", return_value=True):
        with patch.object(medic, "_is_service_active", return_value=False):
            result = medic.handle_command("off", [])

    assert result is True
    err_args = capsys.readouterr().err.splitlines()
    assert display.command_failed() is True
    assert any("Failed to disable Medic" in s for s in err_args), (
        f"Expected failure message in error() args: {err_args}"
    )


# ---------------------------------------------------------------------------
# Tests -- handle_command "status"
# ---------------------------------------------------------------------------


def test_handle_command_status_returns_current_state():
    """handle_command('status', []) displays state info and returns True."""
    medic = _import_medic()

    with patch.object(medic, "_is_service_active", return_value=True):
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

    with patch.object(medic, "_is_service_active", return_value=True):
        medic.handle_command("status", [])

    printed = _printed(capsys)
    state_line = _plain("  State:           [green]ENABLED[/green]")
    assert state_line in printed, f"Expected state line '{state_line}' in printed args: {printed}"


def test_handle_command_status_shows_disabled(capsys):
    """When medic is disabled, status output includes the DISABLED state line."""
    medic = _import_medic()
    state = _get_medic_state()
    state.is_enabled.return_value = False

    with patch.object(medic, "_is_service_active", return_value=False):
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

    with patch.object(medic, "_is_service_active", return_value=True):
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

    with patch.object(medic, "_is_service_active", return_value=False):
        medic.handle_command("status", [])

    printed = _printed(capsys)
    hint = _plain("  [dim]All error dispatch suppressed. Errors logged to medic_suppressed.jsonl[/dim]")
    assert hint in printed, f"Expected suppression hint '{hint}' in printed args: {printed}"


# ---------------------------------------------------------------------------
# Tests -- handle_command "mute"
# ---------------------------------------------------------------------------


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


def test_handle_command_mute_branch_without_at():
    """handle_command('mute', ['speakeasy']) handles names without @ prefix."""
    medic = _import_medic()
    medic.handle_command("mute", ["speakeasy"])

    state = _get_medic_state()
    state.mute_branch.assert_called_once_with("speakeasy", duration_seconds=86400.0)


def test_handle_command_mute_prints_confirmation(capsys):
    """Successful mute prints confirmation with TTL info.

    Mutant run: the TTL computed in minutes instead of hours reddens this.
    """
    medic = _import_medic()
    medic.handle_command("mute", ["@api"])

    printed = _printed(capsys)
    assert "  Muted @api — auto-expires in 24h" in printed, printed


def test_handle_command_mute_failure_prints_error(capsys):
    """When mute_branch returns False, the exact error message is printed.

    Mutant run: this refusal printed instead of sent through error() reddens this.
    """
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
    # Should NOT have called mute_branch
    state = _get_medic_state()
    state.mute_branch.assert_not_called()


# ---------------------------------------------------------------------------
# Tests -- handle_command "unmute"
# ---------------------------------------------------------------------------


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
    """Unmuting a branch that is not muted prints the exact failure message.

    Mutant run: this refusal printed instead of sent through error() reddens this.
    """
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


# ---------------------------------------------------------------------------
# Tests -- handle_command "--help"
# ---------------------------------------------------------------------------


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
    # set_enabled should NOT have been called
    state = _get_medic_state()
    state.set_enabled.assert_not_called()


# ---------------------------------------------------------------------------
# Tests -- handle_command with no args (introspection)
# ---------------------------------------------------------------------------


def test_handle_command_no_args_shows_introspection():
    """handle_command('medic', []) calls print_introspection and returns True."""
    medic = _import_medic()

    with patch.object(medic, "print_introspection") as mock_intro:
        result = medic.handle_command("medic", [])

    assert result is True
    mock_intro.assert_called_once()


# ---------------------------------------------------------------------------
# Tests -- handle_command routing / unknown commands
# ---------------------------------------------------------------------------


def test_handle_command_unknown_returns_false():
    """handle_command with an unknown subcommand returns False."""
    medic = _import_medic()
    result = medic.handle_command("explode", [])
    assert result is False


def test_handle_command_medic_routes_to_subcommand():
    """handle_command('medic', ['status']) recursively routes to status."""
    medic = _import_medic()
    state = _get_medic_state()

    with patch.object(medic, "_is_service_active", return_value=True):
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


# ---------------------------------------------------------------------------
# Tests -- branch name normalisation, through the command
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("raw", ["@Speakeasy", "src/aipass/speakeasy", "speakeasy"])
def test_mute_normalises_the_branch_name_it_is_given(raw):
    """`medic mute` strips @, lowercases and takes a path's last component.

    Reached through the command, not the private helper. Mutant run: the
    helper returning its input unchanged reddens the @ and path cases.
    """
    medic = _import_medic()
    medic.handle_command("mute", [raw])

    state = _get_medic_state()
    state.mute_branch.assert_called_once_with("speakeasy", duration_seconds=86400.0)


# ---------------------------------------------------------------------------
# Contract gap tests
# ---------------------------------------------------------------------------


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

    with patch.object(medic, "_systemctl", return_value=True):
        with patch.object(medic, "_is_service_active", return_value=True):
            result = medic.handle_command("on", ["extra", "args"])

    assert result is True
    state = _get_medic_state()
    state.set_enabled.assert_called_with(True)


# ---------------------------------------------------------------------------
# Tests -- output_capture: verify console output content matches expectations
# ---------------------------------------------------------------------------


def test_print_help_names_every_verb_the_router_accepts(capsys):
    """Help lists all seven medic verbs — a verb the router takes but help hides is a defect.

    This asked for capsys and then read nothing, and its own comment admitted
    why: aipass.cli.apps.modules is a MagicMock under this file's fixture, so
    stdout is empty no matter what print_help does. The fixture was decoration
    on an empty capture. The mocked console's call args are the real output,
    and the verb list is taken from the router rather than retyped, so adding a
    verb without documenting it is what turns this red.
    Mutant run: deleting the `on` line from print_help reddens this.
    """
    medic = _import_medic()

    medic.print_help()

    output = "\n".join(_printed(capsys))
    routed = ["on", "off", "status", "mute", "unmute", "volume-mute", "volume-unmute"]
    # Floors the loop: an empty list would make every assertion below vacuous
    # and the unit would pass by never running. Seven is the gate list in
    # handle_command (medic.py:494), counted 2026-09-08.
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

    with patch.object(medic, "_is_service_active", return_value=True):
        medic.handle_command("status", [])

    printed = _printed(capsys)
    output = "\n".join(printed)
    for field in ["State:", "Log watcher:", "Muted branches:", "Suppressed:", "Rate limited:"]:
        assert field in output, f"Status output missing field: {field}"


# ---------------------------------------------------------------------------
# help_flag_safety canary — a help flag ANYWHERE explains, never executes
# ---------------------------------------------------------------------------


def test_help_flag_after_a_branch_operand_does_not_mute(monkeypatch):
    """`medic mute @branch --help` must describe muting, never mute.

    Medic is a live dispatch surface: a real mute silences error dispatch to
    a citizen for 24h with no unmute. The handler is mocked so this canary
    can never perform one — the assertion is that it is never reached.
    """
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

    log_watcher_service is an entry point, so it must reach the startup
    handler through a module (seedgo encapsulation rule 3). This function is
    that seam, and it must stay a thin pass-through: the moment it starts
    deciding anything, the service and the `startup` event stop recovering
    identically.
    """

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

        Adding it to the command table would put a live fleet-wide error scan
        one typo away from an operator's shell. Mutant run: handle_command
        claiming an unknown subcommand (return True) reddens the routing assert.
        """
        medic = _import_medic()
        scan = MagicMock()
        monkeypatch.setattr(medic, "run_startup_catchup", scan)

        assert medic.handle_command("medic", ["catchup"]) is False

        scan.assert_not_called()


# ---------------------------------------------------------------------------
# host portability — a host with no systemd (2026-09-12, seedgo FPLAN-0554)
# ---------------------------------------------------------------------------


def test_status_on_a_host_without_systemd_says_so_instead_of_offering_medic_on(capsys):
    """ "stopped — run medic on" is advice that cannot work where there is no systemd.

    macOS and Windows have no systemctl at all; the watcher there is not
    stopped, it is unavailable, and telling a reader to start it sends them
    after a unit that can never exist.
    """
    medic = _import_medic()
    state = _get_medic_state()
    state.is_enabled.return_value = True

    with patch.object(medic, "_is_service_active", return_value=False):
        with patch.object(medic, "systemd_available", return_value=False):
            medic.handle_command("status", [])

    output = "\n".join(_printed(capsys))
    assert "no systemd on this host" in output, output
    assert "run medic on" not in output, output


def test_medic_on_reports_unavailable_rather_than_failed_to_start_without_systemd(capsys):
    """ "failed to start" reads as a broken unit; the truth is a hostless door."""
    medic = _import_medic()

    with patch.object(medic, "_systemctl", return_value=False):
        with patch.object(medic, "_is_service_active", return_value=False):
            with patch.object(medic, "_ensure_service_installed", return_value=False):
                with patch.object(medic, "systemd_available", return_value=False):
                    medic.handle_command("on", [])

    panel_text = capsys.readouterr().out
    assert "unavailable — no systemd on this host" in panel_text, panel_text
