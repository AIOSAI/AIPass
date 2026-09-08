# =================== AIPass ====================
# Name: test_cli_routing.py
# Description: CLI Routing Tests for DAEMON
# Version: 1.0.0
# Created: 2026-03-28
# Modified: 2026-03-28
# =============================================

"""
CLI Routing Tests for DAEMON branch.

Tests daemon.py routing: help flags, introspection, unknown commands,
no-args behavior, and output capture.

Covers 9 tests:
  - help_flag (--help)
  - short_help (-h)
  - help_word ("help")
  - no_args (no arguments)
  - unknown_command
  - print_help
  - print_introspection
  - output_capture
  - version_flag (bonus)
"""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# We import the daemon module and mock json_handler.log_operation to
# prevent real file writes during routing tests.
# ---------------------------------------------------------------------------

from aipass.daemon.apps import daemon as _daemon_mod


@pytest.fixture(autouse=True)
def _mock_log_operation():
    """Prevent json_handler.log_operation from touching real files."""
    with patch.object(_daemon_mod.json_handler, "log_operation", return_value=True):
        yield


# ============================================================================
# CLI Routing Tests
# ============================================================================


def test_help_flag() -> None:
    """--help flag triggers help and returns exit code 0."""
    with patch.object(sys, "argv", ["daemon", "--help"]):
        result = _daemon_mod.main()
    assert result == 0, "daemon --help must return exit code 0"


def test_short_help() -> None:
    """short_help: -h flag triggers help and returns exit code 0."""
    with patch.object(sys, "argv", ["daemon", "-h"]):
        result = _daemon_mod.main()
    assert result == 0, "daemon -h must return exit code 0"


def test_help_word() -> None:
    """help_word: 'help' as command triggers help and returns exit code 0."""
    with patch.object(sys, "argv", ["daemon", "help"]):
        result = _daemon_mod.main()
    assert result == 0, "daemon help must return exit code 0"


def test_no_args() -> None:
    """no_args: running daemon with no arguments shows introspection and returns 0."""
    with patch.object(sys, "argv", ["daemon"]):
        result = _daemon_mod.main()
    assert result == 0, "daemon with no args must return exit code 0"


def test_unknown_command() -> None:
    """unknown_command: unrecognized command returns exit code 1."""
    with patch.object(sys, "argv", ["daemon", "nonexistent_command_xyz"]):
        result = _daemon_mod.main()
    assert result == 1, "Unknown command must return exit code 1"


def test_print_help(capsys: pytest.CaptureFixture[str]) -> None:
    """print_help: produces stdout output without error."""
    modules = _daemon_mod.get_modules()
    _daemon_mod.print_help(modules)
    captured = capsys.readouterr()
    assert len(captured.out) > 0, "print_help() must produce output"
    assert "DAEMON" in captured.out, "print_help output must mention DAEMON"


def test_print_introspection(capsys: pytest.CaptureFixture[str]) -> None:
    """print_introspection: produces stdout output listing modules."""
    modules = _daemon_mod.get_modules()
    _daemon_mod.print_introspection(modules)
    captured = capsys.readouterr()
    assert len(captured.out) > 0, "print_introspection() must produce output"
    assert "DAEMON" in captured.out, "print_introspection output must mention DAEMON"


def test_output_capture(capsys: pytest.CaptureFixture[str]) -> None:
    """output_capture: help flag produces captured output on stdout."""
    with patch.object(sys, "argv", ["daemon", "--help"]):
        _daemon_mod.main()
    captured = capsys.readouterr()
    assert len(captured.out) > 0, "Help output must be capturable on stdout"
    # Was `"USAGE" in out or "daemon" in out.lower()`. Both clauses hold on the
    # real banner, so the `or` bought nothing: either half alone kept the unit
    # green. Measured by running main() under --help — the banner prints the
    # heading, then the literal `USAGE:` line, then the command forms. Pinned
    # to what the code actually emits.
    assert "USAGE:" in captured.out, f"help must print the USAGE: block, got: {captured.out[:200]!r}"
    assert "DAEMON - Branch Management System" in captured.out, "help must print the DAEMON banner heading"


def test_version_flag() -> None:
    """--version flag returns exit code 0."""
    with patch.object(sys, "argv", ["daemon", "--version"]):
        result = _daemon_mod.main()
    assert result == 0, "daemon --version must return exit code 0"


# ============================================================================
# Help-flag safety — a --help ANYWHERE must never execute the verb
#
# The router used to intercept only remaining_args[0], so 'run --dry-run --help'
# fired a scheduler tick and 'inbox-sweep --hours 48 --help' woke real branches
# instead of printing help. Help must never be a side-effecting command.
# ============================================================================


def test_help_after_flag_does_not_fire_scheduler() -> None:
    """'run --dry-run --help' prints help — it must not run a scheduler tick."""
    with patch.object(_daemon_mod.run, "_run_with_lock") as mock_tick:
        with patch.object(sys, "argv", ["daemon", "run", "--dry-run", "--help"]):
            result = _daemon_mod.main()
    mock_tick.assert_not_called()
    assert result == 0, "help must exit 0"


def test_help_after_value_does_not_sweep_inboxes() -> None:
    """'inbox-sweep --hours 48 --help' prints help — it must not wake branches."""
    with patch.object(_daemon_mod.inbox_sweep, "run_sweep") as mock_sweep:
        with patch.object(sys, "argv", ["daemon", "inbox-sweep", "--hours", "48", "--help"]):
            result = _daemon_mod.main()
    mock_sweep.assert_not_called()
    assert result == 0, "help must exit 0"


def test_help_after_junk_arg_does_not_fire_scheduler() -> None:
    """A stray token before --help must not turn help into a live fire."""
    with patch.object(_daemon_mod.run, "_run_with_lock") as mock_tick:
        with patch.object(sys, "argv", ["daemon", "run", "oops", "--help"]):
            result = _daemon_mod.main()
    mock_tick.assert_not_called()
    assert result == 0, "help must exit 0"


# ============================================================================
# Unknown-argument refusal, every verb (FPLAN-0492 wave 2b)
# ============================================================================

# The gate DECIDES; apps/daemon.py RENDERS. A handler that imported cli
# services failed seedgo's separation rule, so error() is called from the
# router and that is where these tests intercept it.
ROUTER = "aipass.daemon.apps.daemon"

# The effectful seam is patched at every site below that feeds a verb to the real
# router. GATED_VERBS holds install-timer and uninstall-timer, and with the gate
# removed — a red-first run, a mutation run — main() reaches _install()/
# _uninstall() and the real systemctl. conftest's autouse _seal_timer_host_state
# already makes that unreachable, but a guard living one file away is invisible
# both to a reader of these tests and to seedgo's host_state rule, which acquits
# a site only when the seam is patched IN the unit.
#
# Written out in full at each site rather than held in a constant: the rule reads
# the patch target as a literal, and a Name resolves to nothing it can follow.
# The repetition is the point — a unit copied out of this file takes its guard.

# Every verb daemon.py routes, with the flags it actually defines. branch-health
# is absent on purpose: it takes a POSITIONAL and gates it in its own module
# (wave 1), pinned in test_activity_report.py.
GATED_VERBS = [
    "update",
    "queue",
    "rotation",
    "activity",
    "activity-report",
    "activity_report",
    "inbox-sweep",
    "install-timer",
    "uninstall-timer",
    "schedule",
    "actions",
    "run",
]

# The legitimate argument forms, which must keep working. A refusal gate that
# also refuses real flags is a worse bug than the one it cures.
ACCEPTED = [
    pytest.param(["update"], id="update-bare"),
    pytest.param(["queue"], id="queue-bare"),
    pytest.param(["queue", "--json"], id="queue-json"),
    pytest.param(["rotation", "--json"], id="rotation-json"),
    pytest.param(["activity", "--hours", "48"], id="activity-hours"),
    pytest.param(["activity", "-t", "6"], id="activity-hours-short"),
    pytest.param(["activity-report", "--json"], id="report-json"),
    pytest.param(["activity-report", "-j", "--hours", "12"], id="report-json-hours"),
    pytest.param(["inbox-sweep", "--dry-run", "--hours", "48", "--limit", "2"], id="sweep-all-flags"),
    pytest.param(["run", "--dry-run"], id="run-dry"),
    pytest.param(["schedule"], id="schedule-bare"),
    pytest.param(["actions"], id="actions-bare"),
]


class TestUnknownArgumentIsRefused:
    """Patrick's standing ruling, pinned per verb.

    An unknown command OR ARGUMENT fails with a non-zero exit and a message
    naming the token. Before wave 2b these twelve surfaces accepted a trailing
    argument and silently ignored it, so `drone @daemon queue not_a_verb`
    rendered the queue and exited 0 — a caller's `&&` reads that as the queue it
    asked for, and a typo'd flag (`--jsonn`) reads as success while doing
    something else. Quieter than branch-health's EXIT-0-ON-FAILURE, same defect.
    """

    @pytest.mark.parametrize("verb", GATED_VERBS)
    def test_a_stray_positional_is_refused(self, verb) -> None:
        with patch("aipass.daemon.apps.modules.timer_install._run_systemctl", return_value=True):
            with patch.object(sys, "argv", ["daemon", verb, "not_a_real_subarg_xyz"]):
                with pytest.raises(SystemExit) as exc:
                    _daemon_mod.main()
        assert exc.value.code == 1, f"{verb} accepted a stray positional"

    @pytest.mark.parametrize("verb", GATED_VERBS)
    def test_the_refusal_names_the_token(self, verb) -> None:
        """A refusal that does not name the token leaves a long command line a guess."""
        with (
            patch("aipass.daemon.apps.modules.timer_install._run_systemctl", return_value=True),
            patch(f"{ROUTER}.error") as mock_err,
        ):
            with patch.object(sys, "argv", ["daemon", verb, "not_a_real_subarg_xyz"]):
                with pytest.raises(SystemExit):
                    _daemon_mod.main()
        printed = str(mock_err.call_args)
        assert "not_a_real_subarg_xyz" in printed, f"{verb} refused without naming the token"
        assert verb in printed, f"{verb} refused without naming itself"

    @pytest.mark.parametrize("verb", ["queue", "rotation", "activity-report", "inbox-sweep", "run"])
    def test_a_typo_in_a_real_flag_is_refused(self, verb) -> None:
        """The case that bites hardest: --jsonn is not --json, and used to be ignored."""
        with patch.object(sys, "argv", ["daemon", verb, "--jsonn"]):
            with pytest.raises(SystemExit) as exc:
                _daemon_mod.main()
        assert exc.value.code == 1

    @pytest.mark.parametrize("argv", ACCEPTED)
    def test_the_real_flags_still_work(self, argv) -> None:
        with patch.object(_daemon_mod.run, "_run_with_lock", return_value=0):
            with patch.object(_daemon_mod.inbox_sweep, "run_sweep", return_value={}):
                with patch.object(sys, "argv", ["daemon", *argv]):
                    result = _daemon_mod.main()
        assert result == 0, f"{argv} is a legitimate form and must not be refused"

    def test_a_value_flag_does_not_refuse_on_its_own_value(self) -> None:
        """`--hours 48` must not read 48 as a stray positional.

        The mutation this guards: dropping the two-step skip in
        unknown_argument() refuses every value flag ever passed.
        """
        with patch.object(sys, "argv", ["daemon", "activity", "--hours", "48"]):
            assert _daemon_mod.main() == 0

    @pytest.mark.parametrize("verb", ["install-timer", "uninstall-timer"])
    def test_the_timer_verbs_cannot_reach_live_systemd_without_the_gate(self, verb, _seal_timer_host_state) -> None:
        """The two rows that took the scheduler down on 2026-09-07, run in the world that did it.

        The gate is patched to a no-op here — the exact mutation world, and the
        exact state of this file during a red-first run — so _install() and
        _uninstall() really execute. What must hold is that they execute
        against the sealed seams and not the user's systemd.

        This asserts in BOTH directions on purpose. Live host state unchanged is
        half the claim; the other half is that the verb actually RAN, because a
        world where nothing fires would satisfy the first half while proving
        nothing at all. The sealed systemctl having been called is what
        distinguishes "it could not touch the host" from "it never got there".
        """
        live_dir = Path.home() / ".config" / "systemd" / "user"
        units = ("daemon-tick.service", "daemon-tick.timer")
        before = sorted(name for name in units if (live_dir / name).exists())

        with patch.object(_daemon_mod.timer_install, "gate", lambda *a, **k: None):
            with patch.object(sys, "argv", ["daemon", verb, "not_a_real_subarg_xyz"]):
                result = _daemon_mod.main()

        assert result == 0, f"{verb} with the gate removed should run the verb, not refuse"
        assert _seal_timer_host_state.called, (
            f"{verb} never reached _run_systemctl — this test proves nothing about the seal"
        )

        # Where the file operations actually landed. install-timer copies both
        # units in, uninstall-timer unlinks whatever is there — against the
        # SEALED directory. The seam is a module constant, so the same code
        # would perform the same operations on whatever it points at; this is
        # what makes the live-dir assertion below a consequence of the seal
        # rather than a coincidence.
        sealed_dir = _daemon_mod.timer_install._UNIT_DIR
        assert sealed_dir != live_dir, "the seal is not in place — _UNIT_DIR is the live directory"
        if verb == "install-timer":
            assert sorted(p.name for p in sealed_dir.iterdir()) == sorted(units), (
                f"install-timer did not write the units into the sealed dir: {list(sealed_dir.iterdir())}"
            )

        after = sorted(name for name in units if (live_dir / name).exists())
        assert after == before, f"{verb} changed the live unit files: {before} -> {after}"

    def test_help_outranks_the_gate(self) -> None:
        """A help request is never an unknown argument, and never exits non-zero."""
        # The floor. An empty GATED_VERBS would make the loop below a silent
        # pass: twelve is what wave 2b landed, counted from the list above.
        assert len(GATED_VERBS) == 12, f"the gate covers twelve verbs, this list names {len(GATED_VERBS)}"
        for verb in GATED_VERBS:
            with patch("aipass.daemon.apps.modules.timer_install._run_systemctl", return_value=True):
                with patch.object(sys, "argv", ["daemon", verb, "--help"]):
                    assert _daemon_mod.main() == 0, f"{verb} --help must exit 0"
