#!/usr/bin/env python3
# =================== AIPass ====================
# Name: test_help_flag_safety.py
# Description: A help probe must never execute the thing it asks about
# Version: 1.0.0
# Created: 2026-08-13
# Modified: 2026-08-13
# =============================================

"""Regression cover for help_flag_safety (@seedgo 2026-08-13, DPLAN-0291 rule E).

Every prax module gated help at ``args[0]`` only, so a flag anywhere later on
the line was discarded and the subcommand ran instead. The standalone
``__main__`` paths screened ``--help`` but not ``-h``, and ``-h`` survives a
``--``-prefix filter because it carries a single dash. Two of the three had
teeth:

    log_audit.py enforce -h   -> truncated every oversized log
    monitor.py   run -h       -> started a live Mission Control

The rule these pin: a dashed flag counts ANYWHERE, a bare ``help`` counts only
at position 0 (branch names, log filenames and grep patterns are free text).

Modules are imported inside each test — conftest.py installs autouse sys.modules
mocks that must be in place first.
"""

import contextlib
import importlib
import sys
from unittest.mock import patch

import pytest


LOG_AUDIT_PATH = "aipass.prax.apps.modules.log_audit"
LOG_HEALTH_PATH = "aipass.prax.apps.modules.log_health"
MONITOR_PATH = "aipass.prax.apps.modules.monitor"
FLAGS_PATH = "aipass.prax.apps.handlers.cli.help_flags"


def _load(module_path: str):
    """Import (or reimport) a module under the active mocks."""
    sys.modules.pop(module_path, None)
    module = importlib.import_module(module_path)
    return importlib.reload(module)


# The tail positions a flag can hide in, per module. Each pairs the command
# name with args whose FIRST token is a real, destructive subcommand.
DESTRUCTIVE_CASES = [
    ("log-audit", LOG_AUDIT_PATH, ["enforce", "--help"]),
    ("log-audit", LOG_AUDIT_PATH, ["enforce", "-h"]),
    ("log-audit", LOG_AUDIT_PATH, ["sweep", "-h"]),
    ("log-health", LOG_HEALTH_PATH, ["scan", "--help"]),
    ("log-health", LOG_HEALTH_PATH, ["scan", "-h"]),
    ("monitor", MONITOR_PATH, ["run", "--help"]),
    ("monitor", MONITOR_PATH, ["run", "-h"]),
    ("monitor", MONITOR_PATH, ["run", "seedgo,cli", "-h"]),
]


WATCHDOG_PATH = "aipass.prax.apps.handlers.logging.log_watchdog"
RATE_TRACKER_PATH = "aipass.prax.apps.handlers.monitoring.rate_tracker"

# Every entry point that DOES something, per module. A red run of this file
# must not truncate a log or start a monitor to prove the gate is missing —
# the first draft did exactly that and hung the suite on a live Mission
# Control, which is the defect writing its own bug report.
EXECUTION_TARGETS = {
    LOG_AUDIT_PATH: [
        (None, "_run_enforce"),
        (None, "_run_branch_enforce"),
        (None, "_run_sweep"),
        (None, "_display_audit"),
        (WATCHDOG_PATH, "scan_log_files"),
        (WATCHDOG_PATH, "log_health_summary"),
    ],
    LOG_HEALTH_PATH: [
        (None, "_display_rates"),
        (RATE_TRACKER_PATH, "scan_rates"),
        (RATE_TRACKER_PATH, "get_snapshot"),
        (RATE_TRACKER_PATH, "configure"),
    ],
    MONITOR_PATH: [(None, "_dispatch_run")],
}


@contextlib.contextmanager
def _no_execution(mod, module_path):
    """Stub every doing-path in the module under test, and yield the mocks."""
    with contextlib.ExitStack() as stack:
        mocks = {}
        for target_module, name in EXECUTION_TARGETS[module_path]:
            owner = mod if target_module is None else importlib.import_module(target_module)
            mocks[name] = stack.enter_context(patch.object(owner, name))
        yield mocks


class TestHelpNeverExecutes:
    """A help probe prints the manual and touches nothing else."""

    @pytest.mark.parametrize("command,module_path,args", DESTRUCTIVE_CASES)
    def test_help_flag_in_any_position_prints_help(self, command, module_path, args):
        mod = _load(module_path)
        with patch.object(mod, "print_help") as help_fn, _no_execution(mod, module_path) as mocks:
            assert mod.handle_command(command, args) is True
        assert help_fn.call_count == 1, f"{command} {args} did not print help"
        ran = [name for name, mock in mocks.items() if mock.call_count]
        assert not ran, f"{command} {args} executed {ran} while asking for help"

    def test_enforce_with_trailing_dash_h_does_not_truncate(self):
        """The live damage: -h survived the --prefix filter and truncated logs."""
        mod = _load(LOG_AUDIT_PATH)
        with patch.object(mod, "print_help"), patch.object(mod, "_run_enforce") as enforce:
            mod.handle_command("log-audit", ["enforce", "-h"])
        assert enforce.call_count == 0

    def test_run_with_trailing_dash_h_does_not_start_a_monitor(self):
        """The other live one: a help probe must never start or stop a monitor."""
        mod = _load(MONITOR_PATH)
        with patch.object(mod, "print_help"), patch.object(mod, "_dispatch_run") as run:
            mod.handle_command("monitor", ["run", "-h"])
        assert run.call_count == 0

    def test_scan_with_trailing_dash_h_does_not_scan(self):
        """Less destructive, same principle: no filesystem sweep, no operation log."""
        mod = _load(LOG_HEALTH_PATH)
        with patch.object(mod, "print_help"), patch.object(mod, "_display_rates") as display:
            mod.handle_command("log-health", ["scan", "-h"])
        assert display.call_count == 0


class TestOwnershipStillComesFirst:
    """The gate sits AFTER the ownership check.

    prax.py tries each module in turn. A help scan at the top of the function
    would make whichever module is tried first answer every `--help`, so
    `drone @prax monitor --help` could be served by log_audit.
    """

    @pytest.mark.parametrize(
        "module_path,foreign", [(LOG_AUDIT_PATH, "monitor"), (MONITOR_PATH, "log-audit"), (LOG_HEALTH_PATH, "monitor")]
    )
    def test_foreign_command_is_declined_even_with_help_flag(self, module_path, foreign):
        mod = _load(module_path)
        with patch.object(mod, "print_help") as help_fn:
            assert mod.handle_command(foreign, ["--help"]) is False
        assert help_fn.call_count == 0, "hijacked another module's help"


class TestFreeTextIsNotAHelpRequest:
    """Position-0 rule: branch names and patterns containing 'help' are content."""

    def test_bare_help_as_a_branch_name_is_not_a_help_request(self):
        mod = _load(MONITOR_PATH)
        with patch.object(mod, "print_help") as help_fn, patch.object(mod, "_dispatch_run") as run:
            mod.handle_command("monitor", ["run", "help"])
        assert help_fn.call_count == 0
        assert run.call_count == 1

    def test_bare_help_at_position_zero_is_a_help_request(self):
        mod = _load(MONITOR_PATH)
        with patch.object(mod, "print_help") as help_fn:
            mod.handle_command("monitor", ["help"])
        assert help_fn.call_count == 1


class TestWantsHelpPredicate:
    """The predicate itself — exact matching, no substrings."""

    def test_empty_args_is_not_help(self):
        flags = _load(FLAGS_PATH)
        assert flags.wants_help([]) is False

    @pytest.mark.parametrize("args", [["--help"], ["-h"], ["help"], ["run", "--help"], ["a", "b", "-h"]])
    def test_help_forms_detected(self, args):
        flags = _load(FLAGS_PATH)
        assert flags.wants_help(args) is True

    @pytest.mark.parametrize("args", [["run"], ["run", "help"], ["--help-me"], ["-hx"], ["helper"]])
    def test_non_help_forms_rejected(self, args):
        flags = _load(FLAGS_PATH)
        assert flags.wants_help(args) is False

    def test_bare_word_opt_in_reads_any_position(self):
        flags = _load(FLAGS_PATH)
        assert flags.wants_help(["run", "help"], allow_bare_word=True) is True

    def test_canary_position_zero_only_gate_misses_the_tail(self):
        """Proof the assertions above can fail: the retired gate is real."""
        args = ["enforce", "-h"]
        assert args[0] not in ("--help", "-h", "help")
