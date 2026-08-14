# =================== AIPass ====================
# Name: test_help_flags.py
# Description: Tests for the wants_help predicate and the call sites without a module test file
# Version: 1.0.0
# Created: 2026-08-13
# Modified: 2026-08-13
# =============================================

"""Tests for handlers/cli/help_flags.py — a help flag ANYWHERE means explain.

Red-first: every assertion below was written and run before the predicate
existed (ModuleNotFoundError), and every module regression here was run
against the args[0]-only gate and watched execute the command it was being
asked to describe.

The module regressions assert against MOCKS of the doing paths — test_map's
branch scan and seedgo's router. A test that proves "--help does not execute
the scan" must never let the real scan run to find out.
"""

from typing import List
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _silence_side_effects(monkeypatch, module):
    """Mock a module's console and operation log so a test writes nothing real."""
    monkeypatch.setattr(module, "console", MagicMock(), raising=False)
    monkeypatch.setattr(module, "json_handler", MagicMock(), raising=False)
    monkeypatch.setattr(module, "logger", MagicMock(), raising=False)


# ---------------------------------------------------------------------------
# The predicate — dashed forms count ANYWHERE
# ---------------------------------------------------------------------------


def test_dashed_help_in_the_command_slot():
    from aipass.seedgo.apps.handlers.cli.help_flags import wants_help

    assert wants_help("--help") is True
    assert wants_help("-h") is True


def test_dashed_help_at_the_first_argument():
    from aipass.seedgo.apps.handlers.cli.help_flags import wants_help

    assert wants_help("checklist", ["--help"]) is True
    assert wants_help("checklist", ["-h"]) is True


def test_dashed_help_after_the_operands():
    """The whole point: `checklist apps/modules/checklist.py --help` explains."""
    from aipass.seedgo.apps.handlers.cli.help_flags import wants_help

    assert wants_help("checklist", ["apps/modules/checklist.py", "--help"]) is True
    assert wants_help("proof", ["aipass", "--json", "-h"]) is True


def test_dashed_help_at_the_end_of_a_long_line():
    from aipass.seedgo.apps.handlers.cli.help_flags import wants_help

    assert wants_help("audit", ["aipass", "@flow", "--full", "--no-bypass", "--help"]) is True


# ---------------------------------------------------------------------------
# The predicate — the bare word counts at position 0 only
# ---------------------------------------------------------------------------


def test_bare_help_at_position_zero():
    from aipass.seedgo.apps.handlers.cli.help_flags import wants_help

    assert wants_help("help") is True
    assert wants_help(None, ["help"]) is True


def test_bare_help_later_is_a_value_not_a_question():
    """A pack, a path or a branch may legitimately be called `help`."""
    from aipass.seedgo.apps.handlers.cli.help_flags import wants_help

    assert wants_help("checklist", ["help"]) is False
    assert wants_help(None, ["standards_query", "help"]) is False


def test_bare_help_can_be_turned_off():
    """For a module that owns `help` as a real subcommand."""
    from aipass.seedgo.apps.handlers.cli.help_flags import wants_help

    assert wants_help("help", bare_help=False) is False
    assert wants_help(None, ["help"], bare_help=False) is False


def test_dashed_forms_still_catch_with_bare_help_off():
    from aipass.seedgo.apps.handlers.cli.help_flags import wants_help

    assert wants_help(None, ["help", "--help"], bare_help=False) is True
    assert wants_help("help", ["-h"], bare_help=False) is True


# ---------------------------------------------------------------------------
# The predicate — no tokens, and no near misses
# ---------------------------------------------------------------------------


def test_nothing_typed_is_not_a_help_request():
    from aipass.seedgo.apps.handlers.cli.help_flags import wants_help

    assert wants_help(None) is False
    assert wants_help(None, []) is False
    assert wants_help("") is False


def test_a_command_that_is_not_help_is_not_help():
    from aipass.seedgo.apps.handlers.cli.help_flags import wants_help

    assert wants_help("checklist", ["apps/modules/checklist.py"]) is False


def test_matching_is_exact_not_substring():
    """`--helpful` is a flag some other command may own; it is not a question."""
    from aipass.seedgo.apps.handlers.cli.help_flags import wants_help

    assert wants_help("--helpful") is False
    assert wants_help(None, ["--help=json"]) is False
    assert wants_help(None, ["helper"]) is False
    assert wants_help(None, ["-help"]) is False


def test_the_predicate_does_not_mutate_its_arguments():
    from aipass.seedgo.apps.handlers.cli.help_flags import wants_help

    args: List[str] = ["aipass", "--help"]
    wants_help("proof", args)
    assert args == ["aipass", "--help"]


def test_tokens_are_published_as_constants():
    from aipass.seedgo.apps.handlers.cli import help_flags

    assert set(help_flags.DASHED_HELP_TOKENS) == {"--help", "-h"}
    assert help_flags.BARE_HELP_TOKEN == "help"


# ---------------------------------------------------------------------------
# test_map — `test_map @branch --help` must not scan the branch
# ---------------------------------------------------------------------------


def test_test_map_help_after_branch_does_not_scan(monkeypatch):
    """`drone @seedgo test_map @flow --help` scanned every function in @flow."""
    from aipass.seedgo.apps.modules import test_map

    _silence_side_effects(monkeypatch, test_map)
    scan = MagicMock()
    monkeypatch.setattr(test_map, "scan_branch", scan)
    monkeypatch.setattr(test_map, "discover_branches", MagicMock(return_value=[]))
    help_shown = MagicMock()
    monkeypatch.setattr(test_map, "print_help", help_shown)

    assert test_map.handle_command("test_map", ["@flow", "--help"]) is True
    assert scan.call_count == 0
    assert help_shown.call_count == 1


def test_test_map_still_scans_without_a_help_flag(monkeypatch):
    """The gate must not swallow the real command."""
    from aipass.seedgo.apps.modules import test_map

    _silence_side_effects(monkeypatch, test_map)
    monkeypatch.setattr(test_map, "print_help", MagicMock())
    monkeypatch.setattr(
        test_map,
        "discover_branches",
        MagicMock(return_value=[{"name": "flow", "path": "/nowhere/flow"}]),
    )
    scan = MagicMock(return_value={"total_functions": 0, "tested_functions": 0, "coverage_pct": 0, "files": []})
    monkeypatch.setattr(test_map, "scan_branch", scan)
    monkeypatch.setattr(test_map, "_display_coverage_map", MagicMock())

    assert test_map.handle_command("test_map", ["@flow"]) is True
    assert scan.call_count == 1


def test_test_map_does_not_answer_for_another_command(monkeypatch):
    """Ownership first: a help flag never makes a module claim a command it does not own."""
    from aipass.seedgo.apps.modules import test_map

    _silence_side_effects(monkeypatch, test_map)
    monkeypatch.setattr(test_map, "print_help", MagicMock())

    assert test_map.handle_command("checklist", ["--help"]) is False


# ---------------------------------------------------------------------------
# seedgo.py — the entry router
# ---------------------------------------------------------------------------


def test_entry_router_intercepts_a_trailing_help_flag(monkeypatch):
    """`seedgo checklist some/file.py --help` reached route_command and ran the audit."""
    from aipass.seedgo.apps import seedgo

    _silence_side_effects(monkeypatch, seedgo)
    module = MagicMock()
    module.handle_command = MagicMock(return_value=True)
    monkeypatch.setattr(seedgo, "discover_modules", MagicMock(return_value=[module]))
    routed = MagicMock(return_value=True)
    monkeypatch.setattr(seedgo, "route_command", routed)
    monkeypatch.setattr(seedgo.sys, "argv", ["seedgo", "checklist", "apps/modules/checklist.py", "--help"])

    assert seedgo.main() == 0
    assert routed.call_count == 0
    module.handle_command.assert_called_once_with("checklist", ["--help"])


def test_entry_router_still_routes_a_real_command(monkeypatch):
    from aipass.seedgo.apps import seedgo

    _silence_side_effects(monkeypatch, seedgo)
    monkeypatch.setattr(seedgo, "discover_modules", MagicMock(return_value=[]))
    routed = MagicMock(return_value=True)
    monkeypatch.setattr(seedgo, "route_command", routed)
    monkeypatch.setattr(seedgo.sys, "argv", ["seedgo", "checklist", "apps/modules/checklist.py"])

    assert seedgo.main() == 0
    routed.assert_called_once_with("checklist", ["apps/modules/checklist.py"], [])


def test_entry_router_top_level_help_is_unchanged(monkeypatch):
    """`seedgo --help` still prints the branch help, not a module's."""
    from aipass.seedgo.apps import seedgo

    _silence_side_effects(monkeypatch, seedgo)
    monkeypatch.setattr(seedgo, "discover_modules", MagicMock(return_value=[]))
    monkeypatch.setattr(seedgo, "route_command", MagicMock(return_value=True))
    printed = MagicMock()
    monkeypatch.setattr(seedgo, "print_help", printed)
    monkeypatch.setattr(seedgo.sys, "argv", ["seedgo", "--help"])

    assert seedgo.main() == 0
    assert printed.call_count == 1
