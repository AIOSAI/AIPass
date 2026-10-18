# =================== AIPass ====================
# Name: test_help_flag_safety.py
# Description: A help probe must never execute the thing it asks about
# Version: 1.1.0
# Created: 2026-08-13
# Modified: 2026-10-17
# =============================================

"""Tests for apps/modules/log_audit.py, log_health.py, monitor.py and apps/handlers/cli/help_flags.py."""

# The rule these pin: a dashed flag (-h included) counts ANYWHERE, a bare ``help``
# only at position 0 (branch names, log filenames and grep patterns are free text).

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(through_the_command) — log_audit.py's enforce and sweep, covered by tests/test_log_audit.py
# seedgo: no-test-needed(through_the_command) — monitor.py's run dispatch, covered by tests/test_monitor_module.py

import contextlib
from unittest.mock import MagicMock, patch

import pytest

from aipass.prax.apps import prax as prax_entry
from aipass.prax.apps.handlers.cli import help_flags
from aipass.prax.apps.handlers.cli.arg_gate import UnknownArgument
from aipass.prax.apps.handlers.logging import log_watchdog
from aipass.prax.apps.handlers.monitoring import rate_tracker
from aipass.prax.apps.modules import log_audit, log_health, monitor


@pytest.fixture
def prax_entry_point(monkeypatch):
    """prax.py with its logger doubled; error() stays real, so refusals are read off stderr."""
    monkeypatch.setattr(prax_entry, "logger", MagicMock())
    return prax_entry


LOG_AUDIT_PATH = "aipass.prax.apps.modules.log_audit"
LOG_HEALTH_PATH = "aipass.prax.apps.modules.log_health"
MONITOR_PATH = "aipass.prax.apps.modules.monitor"
FLAGS_PATH = "aipass.prax.apps.handlers.cli.help_flags"
PRAX_PATH = "aipass.prax.apps.prax"
WATCHDOG_PATH = "aipass.prax.apps.handlers.logging.log_watchdog"
RATE_TRACKER_PATH = "aipass.prax.apps.handlers.monitoring.rate_tracker"

_BOUND = {
    LOG_AUDIT_PATH: log_audit,
    LOG_HEALTH_PATH: log_health,
    MONITOR_PATH: monitor,
    FLAGS_PATH: help_flags,
    PRAX_PATH: prax_entry,
    WATCHDOG_PATH: log_watchdog,
    RATE_TRACKER_PATH: rate_tracker,
}


@pytest.fixture(autouse=True)
def _bound_loggers_doubled(monkeypatch):
    """Each bound module that logs gets a fresh logger double for the test."""
    for module in _BOUND.values():
        if hasattr(module, "logger"):
            monkeypatch.setattr(module, "logger", MagicMock())


def _load(module_path: str):
    """The module bound at the top under this dotted path."""
    return _BOUND[module_path]


# Each case's FIRST arg is a real, destructive subcommand; the flag hides behind it.
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


# Every doing entry point, stubbed so a red run cannot truncate a log or start a
# live monitor (that hangs the suite).
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
            owner = mod if target_module is None else _BOUND[target_module]
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


class TestUnknownArgumentIsRefused:
    """An unknown token FAILS: named, on stderr, non-zero (parse_known_args would swallow it)."""

    def test_an_unknown_top_level_flag_never_reaches_the_self_map(self, prax_entry_point, capsys):
        """The refusal comes first: no self-map, no help, exit 1, token named."""
        mod = prax_entry_point

        with (
            patch("sys.argv", ["prax", "--definitely-not-a-flag"]),
            patch.object(mod, "print_introspection") as self_map,
            patch.object(mod, "print_help") as help_fn,
        ):
            exit_code = mod.main()

        assert exit_code == 1
        self_map.assert_not_called()
        help_fn.assert_not_called()
        refusals = capsys.readouterr().err.splitlines()
        assert any("--definitely-not-a-flag" in call for call in refusals), refusals

    def test_a_near_miss_flag_is_offered_the_one_it_meant(self, prax_entry_point, capsys):
        """A typo gets a pointer, not a lecture."""
        mod = prax_entry_point

        with patch("sys.argv", ["prax", "--verison"]), patch.object(mod, "print_introspection"):
            assert mod.main() == 1

        refusals = capsys.readouterr().err.splitlines()
        assert any("--version" in call for call in refusals), refusals

    def test_a_flag_prax_does_define_still_answers_zero(self):
        """The gate must not over-refuse: --help is prax's own option."""
        mod = _load(PRAX_PATH)

        with patch("sys.argv", ["prax", "--help"]), patch.object(mod, "print_help") as help_fn:
            assert mod.main() == 0

        help_fn.assert_called_once()

    def test_an_unknown_sub_argument_is_refused_by_name_not_reported_handled(self):
        """log-audit raises instead of returning True — True is what became exit 0."""
        mod = _load(LOG_AUDIT_PATH)

        with _no_execution(mod, LOG_AUDIT_PATH), pytest.raises(UnknownArgument) as refusal:
            mod.handle_command("log-audit", ["not_a_real_subarg_xyz"])

        assert refusal.value.verb == "log-audit"
        assert refusal.value.token == "not_a_real_subarg_xyz"

    def test_the_router_turns_a_refused_sub_argument_into_exit_one(self, prax_entry_point, capsys):
        """End to end: exit 1 naming the token, not route_command's "Handler failed" crash path."""
        mod = prax_entry_point

        with patch("sys.argv", ["prax", "log-audit", "not_a_real_subarg_xyz"]):
            assert mod.main() == 1

        rendered = capsys.readouterr().err.splitlines()
        assert any("not_a_real_subarg_xyz" in call for call in rendered), rendered
        assert not any("Handler failed" in call for call in rendered), rendered


class TestACrashedHandlerIsNotAnUnknownCommand:
    def test_a_handler_that_raises_is_reported_as_a_failure_not_an_unknown_command(self, prax_entry_point, capsys):
        """route_command returned False after error(), so a crash also read "Unknown command" (mutant: return False)."""
        mod = prax_entry_point

        def crashing_handler(command, args):
            raise RuntimeError("registry is unreachable")

        with (
            patch.object(mod, "discover_command_modules", return_value=[crashing_handler]),
            patch("sys.argv", ["prax", "status"]),
        ):
            mod.main()

        rendered = capsys.readouterr().err.splitlines()
        assert any("Handler failed: registry is unreachable" in call for call in rendered), rendered
        assert not any("Unknown command" in call for call in rendered), rendered

    def test_discovery_returns_each_command_module_handler_and_skips_logger(self):
        """Mutant: drop the logger.py skip, and the stubbed logger joins the handlers."""
        mod = _load(PRAX_PATH)

        handlers = mod.discover_command_modules()

        assert all(callable(handler) for handler in handlers)
        assert sorted(handler.__module__ for handler in handlers) == [
            "aipass.prax.apps.modules.dashboard",
            "aipass.prax.apps.modules.discover",
            "aipass.prax.apps.modules.log_audit",
            "aipass.prax.apps.modules.log_health",
            "aipass.prax.apps.modules.monitor",
            "aipass.prax.apps.modules.status",
        ]


class TestOwnershipStillComesFirst:
    """The gate sits AFTER the ownership check, or the first module tried answers every --help."""

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
