# =================== AIPass ====================
# Name: test_cli_routing.py
# Description: CLI Routing Tests for DAEMON
# Version: 1.1.0
# Created: 2026-03-28
# Modified: 2026-10-17
# =============================================

"""Tests for apps/daemon.py — the router: help, introspection, unknown commands, the argument gate."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that apps/daemon.py parses and imports
# seedgo: no-test-needed(constant) — the version literal main() prints for --version

from pathlib import Path
from unittest.mock import call, patch

import pytest

from aipass.cli.apps.modules import error, mark_command_failed

from aipass.daemon.apps import daemon as _daemon_mod


@pytest.fixture(autouse=True)
def _mock_log_operation():
    """Prevent json_handler.log_operation from touching real files."""
    with patch.object(_daemon_mod.json_handler, "log_operation", return_value=True):
        yield


def test_help_flag() -> None:
    """--help flag triggers help and returns exit code 0."""
    with patch("sys.argv", ["daemon", "--help"]):
        result = _daemon_mod.main()
    assert result == 0, "daemon --help must return exit code 0"


def test_short_help() -> None:
    """short_help: -h flag triggers help and returns exit code 0."""
    with patch("sys.argv", ["daemon", "-h"]):
        result = _daemon_mod.main()
    assert result == 0, "daemon -h must return exit code 0"


def test_help_word() -> None:
    """help_word: 'help' as command triggers help and returns exit code 0."""
    with patch("sys.argv", ["daemon", "help"]):
        result = _daemon_mod.main()
    assert result == 0, "daemon help must return exit code 0"


def test_no_args() -> None:
    """no_args: running daemon with no arguments shows introspection and returns 0."""
    with patch("sys.argv", ["daemon"]):
        result = _daemon_mod.main()
    assert result == 0, "daemon with no args must return exit code 0"


def test_unknown_command() -> None:
    """unknown_command: unrecognized command returns exit code 1."""
    with patch("sys.argv", ["daemon", "nonexistent_command_xyz"]):
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
    with patch("sys.argv", ["daemon", "--help"]):
        _daemon_mod.main()
    captured = capsys.readouterr()
    assert len(captured.out) > 0, "Help output must be capturable on stdout"
    assert "USAGE:" in captured.out, f"help must print the USAGE: block, got: {captured.out[:200]!r}"
    assert "DAEMON - Branch Management System" in captured.out, "help must print the DAEMON banner heading"


def test_version_flag() -> None:
    """--version flag returns exit code 0."""
    with patch("sys.argv", ["daemon", "--version"]):
        result = _daemon_mod.main()
    assert result == 0, "daemon --version must return exit code 0"


def _tick_that_reports(message: str | None):
    """A stand-in for run._run_with_lock: says `message` through error() when given, and answers 0."""

    def tick(dry_run: bool = False) -> int:
        if message is not None:
            error(message)
        return 0

    return tick


def test_a_verb_that_reports_through_error_exits_2() -> None:
    """A routed verb that called error() and returned exits 2, not 0 (main must use resolve_exit)."""
    with (
        patch.object(_daemon_mod.run, "_run_with_lock", _tick_that_reports("run: the tick reported a failure")),
        patch("sys.argv", ["daemon", "run"]),
    ):
        assert _daemon_mod.main() == 2


def test_a_failed_flag_left_by_an_earlier_command_is_not_inherited() -> None:
    """A clean verb exits 0 even when an earlier command in the process tripped the flag."""
    mark_command_failed()
    with (
        patch.object(_daemon_mod.run, "_run_with_lock", _tick_that_reports(None)),
        patch("sys.argv", ["daemon", "run"]),
    ):
        assert _daemon_mod.main() == 0


# A --help ANYWHERE in the args must never execute the verb.
def test_help_after_flag_does_not_fire_scheduler() -> None:
    """'run --dry-run --help' prints help — it must not run a scheduler tick."""
    with patch.object(_daemon_mod.run, "_run_with_lock") as mock_tick:
        with patch("sys.argv", ["daemon", "run", "--dry-run", "--help"]):
            result = _daemon_mod.main()
    mock_tick.assert_not_called()
    assert result == 0, "help must exit 0"


def test_help_after_value_does_not_sweep_inboxes() -> None:
    """'inbox-sweep --hours 48 --help' prints help — it must not wake branches."""
    with patch.object(_daemon_mod.inbox_sweep, "run_sweep") as mock_sweep:
        with patch("sys.argv", ["daemon", "inbox-sweep", "--hours", "48", "--help"]):
            result = _daemon_mod.main()
    mock_sweep.assert_not_called()
    assert result == 0, "help must exit 0"


def test_help_after_junk_arg_does_not_fire_scheduler() -> None:
    """A stray token before --help must not turn help into a live fire."""
    with patch.object(_daemon_mod.run, "_run_with_lock") as mock_tick:
        with patch("sys.argv", ["daemon", "run", "oops", "--help"]):
            result = _daemon_mod.main()
    mock_tick.assert_not_called()
    assert result == 0, "help must exit 0"


# The router renders the gate's refusal through error(), so tests intercept it there.
ROUTER = "aipass.daemon.apps.daemon"

# _run_systemctl is patched as a literal at each site: seedgo's host_state rule only acquits
# a seam patched IN the unit, and cannot follow a constant.

# branch-health is absent: it gates its positional itself (test_activity_report.py).
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

# Legitimate forms that must keep working.
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
    """An unknown argument fails with a non-zero exit and a message naming the token, per verb."""

    @pytest.mark.parametrize("verb", GATED_VERBS)
    def test_a_stray_positional_is_refused(self, verb) -> None:
        with patch("aipass.daemon.apps.modules.timer_install._run_systemctl", return_value=True):
            with patch("sys.argv", ["daemon", verb, "not_a_real_subarg_xyz"]):
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
            with patch("sys.argv", ["daemon", verb, "not_a_real_subarg_xyz"]):
                with pytest.raises(SystemExit):
                    _daemon_mod.main()
        printed = str(mock_err.call_args)
        assert "not_a_real_subarg_xyz" in printed, f"{verb} refused without naming the token"
        assert verb in printed, f"{verb} refused without naming itself"

    @pytest.mark.parametrize("verb", ["queue", "rotation", "activity-report", "inbox-sweep", "run"])
    def test_a_typo_in_a_real_flag_is_refused(self, verb) -> None:
        """The case that bites hardest: --jsonn is not --json, and used to be ignored."""
        with patch("sys.argv", ["daemon", verb, "--jsonn"]):
            with pytest.raises(SystemExit) as exc:
                _daemon_mod.main()
        assert exc.value.code == 1

    @pytest.mark.parametrize("argv", ACCEPTED)
    def test_the_real_flags_still_work(self, argv) -> None:
        with patch.object(_daemon_mod.run, "_run_with_lock", return_value=0):
            with patch.object(_daemon_mod.inbox_sweep, "run_sweep", return_value={}):
                with patch("sys.argv", ["daemon", *argv]):
                    result = _daemon_mod.main()
        assert result == 0, f"{argv} is a legitimate form and must not be refused"

    def test_a_value_flag_does_not_refuse_on_its_own_value(self) -> None:
        """`--hours 48` must not read 48 as a stray positional."""
        with patch("sys.argv", ["daemon", "activity", "--hours", "48"]):
            assert _daemon_mod.main() == 0

    @pytest.mark.parametrize("verb", ["install-timer", "uninstall-timer"])
    def test_the_timer_verbs_cannot_reach_live_systemd_without_the_gate(
        self, verb, _seal_timer_host_state, tmp_path
    ) -> None:
        """With the gate no-op'd, the timer verbs run against the sealed seams, never live systemd.

        Asserts both that the verb RAN and that the live host is unchanged; either alone proves nothing.
        """
        live_dir = Path.home() / ".config" / "systemd" / "user"
        units = ("daemon-tick.service", "daemon-tick.timer")
        before = sorted(name for name in units if (live_dir / name).exists())

        # uninstall-timer unlinks only units that exist, so the sealed dir gets both first.
        sealed_dir = tmp_path / "_sealed_unit_dir"
        if verb == "uninstall-timer":
            sealed_dir.mkdir()
            for name in units:
                (sealed_dir / name).write_text("[Unit]\n", encoding="utf-8")

        with (
            patch.object(_daemon_mod.timer_install, "gate", lambda *a, **k: None),
            # Patched at the trigger's home, the object _uninstall imports, so no fire reaches the bus.
            patch("aipass.trigger.apps.modules.core.trigger.fire") as fire,
        ):
            with patch("sys.argv", ["daemon", verb, "not_a_real_subarg_xyz"]):
                result = _daemon_mod.main()

        assert result == 0, f"{verb} with the gate removed should run the verb, not refuse"
        assert _seal_timer_host_state.called, (
            f"{verb} never reached _run_systemctl — this test proves nothing about the seal"
        )

        # The sealed dir changing is what makes the live-dir check a consequence, not a coincidence.
        if verb == "install-timer":
            assert sorted(p.name for p in sealed_dir.iterdir()) == sorted(units), (
                f"install-timer did not write the units into the sealed dir: {list(sealed_dir.iterdir())}"
            )
            fire.assert_not_called()
        else:
            assert list(sealed_dir.iterdir()) == [], f"uninstall-timer left units: {list(sealed_dir.iterdir())}"
            assert fire.call_args_list == [
                call("file_deleted", path=str(sealed_dir / name), source="timer_install") for name in units
            ]

        after = sorted(name for name in units if (live_dir / name).exists())
        assert after == before, f"{verb} changed the live unit files: {before} -> {after}"

    def test_help_outranks_the_gate(self) -> None:
        """A help request is never an unknown argument, and never exits non-zero."""
        # Floor: an empty GATED_VERBS would make the loop a silent pass.
        assert len(GATED_VERBS) == 12, f"the gate covers twelve verbs, this list names {len(GATED_VERBS)}"
        for verb in GATED_VERBS:
            with patch("aipass.daemon.apps.modules.timer_install._run_systemctl", return_value=True):
                with patch("sys.argv", ["daemon", verb, "--help"]):
                    assert _daemon_mod.main() == 0, f"{verb} --help must exit 0"
