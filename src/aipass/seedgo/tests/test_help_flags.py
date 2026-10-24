# =================== AIPass ====================
# Name: test_help_flags.py
# Description: Tests for the wants_help predicate and the call sites without a module test file
# Version: 1.1.3
# Created: 2026-08-13
# Modified: 2026-10-24
# =============================================

"""Tests for apps/handlers/cli/help_flags.py and the gates in apps/modules/test_map.py and apps/seedgo.py."""

# A help flag ANYWHERE means explain.
# The module regressions assert against MOCKS of the doing paths (test_map's branch scan,
# seedgo's router): a test proving --help does not run the scan must never let the real scan run.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that help_flags.py parses and imports
# seedgo: no-test-needed(generated) — the help text print_help renders; its gate is what is pinned

from typing import List
from unittest.mock import MagicMock

from aipass.seedgo.apps import seedgo
from aipass.seedgo.apps.handlers.cli import help_flags
from aipass.seedgo.apps.handlers.cli.help_flags import wants_help
from aipass.seedgo.apps.modules import test_map
from aipass.seedgo.apps.handlers.test_map import function_scanner


def _silence_side_effects(monkeypatch, module):
    """Mock a module's operation log so a test writes nothing real; capsys holds the console."""
    monkeypatch.setattr(module, "json_handler", MagicMock(), raising=False)
    monkeypatch.setattr(module, "logger", MagicMock(), raising=False)


def test_dashed_help_in_the_command_slot():
    assert wants_help("--help") is True
    assert wants_help("-h") is True


def test_dashed_help_at_the_first_argument():
    assert wants_help("checklist", ["--help"]) is True
    assert wants_help("checklist", ["-h"]) is True


def test_dashed_help_after_the_operands():
    """The whole point: `checklist apps/modules/checklist.py --help` explains."""
    assert wants_help("checklist", ["apps/modules/checklist.py", "--help"]) is True
    assert wants_help("proof", ["aipass", "--json", "-h"]) is True


def test_dashed_help_at_the_end_of_a_long_line():
    assert wants_help("audit", ["aipass", "@flow", "--full", "--no-bypass", "--help"]) is True


def test_bare_help_at_position_zero():
    assert wants_help("help") is True
    assert wants_help(None, ["help"]) is True


def test_bare_help_later_is_a_value_not_a_question():
    """A pack, a path or a branch may legitimately be called `help`."""
    assert wants_help("checklist", ["help"]) is False
    assert wants_help(None, ["standards_query", "help"]) is False


def test_bare_help_can_be_turned_off():
    """For a module that owns `help` as a real subcommand."""
    assert wants_help("help", bare_help=False) is False
    assert wants_help(None, ["help"], bare_help=False) is False


def test_dashed_forms_still_catch_with_bare_help_off():
    assert wants_help(None, ["help", "--help"], bare_help=False) is True
    assert wants_help("help", ["-h"], bare_help=False) is True


def test_nothing_typed_is_not_a_help_request():
    assert wants_help(None) is False
    assert wants_help(None, []) is False
    assert wants_help("") is False


def test_a_command_that_is_not_help_is_not_help():
    assert wants_help("checklist", ["apps/modules/checklist.py"]) is False


def test_matching_is_exact_not_substring():
    """`--helpful` is a flag some other command may own; it is not a question."""
    assert wants_help("--helpful") is False
    assert wants_help(None, ["--help=json"]) is False
    assert wants_help(None, ["helper"]) is False
    assert wants_help(None, ["-help"]) is False


def test_the_predicate_does_not_mutate_its_arguments():
    args: List[str] = ["aipass", "--help"]
    wants_help("proof", args)
    assert args == ["aipass", "--help"]


def test_tokens_are_published_as_constants():
    assert set(help_flags.DASHED_HELP_TOKENS) == {"--help", "-h"}
    assert help_flags.BARE_HELP_TOKEN == "help"


def test_test_map_help_after_branch_does_not_scan(monkeypatch):
    """`drone @seedgo test_map @flow --help` scanned every function in @flow."""
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
    _silence_side_effects(monkeypatch, test_map)
    monkeypatch.setattr(
        test_map,
        "discover_branches",
        MagicMock(return_value=[{"name": "flow", "path": "/nowhere/flow"}]),
    )
    scan = MagicMock(
        return_value={
            "branch": "flow",
            "total_functions": 0,
            "tested_functions": 0,
            "coverage_pct": 0,
            "files": [],
            "unparsed": [],
        }
    )
    monkeypatch.setattr(test_map, "scan_branch", scan)

    assert test_map.handle_command("test_map", ["@flow"]) is True
    assert scan.call_count == 1


def test_test_map_names_a_source_file_that_does_not_parse(tmp_path, monkeypatch, capsys):
    """Red first: a file with a syntax error read as a file with no functions, unsaid."""
    _silence_side_effects(monkeypatch, test_map)
    _silence_side_effects(monkeypatch, function_scanner)
    handlers = tmp_path / "flow" / "apps" / "handlers"
    handlers.mkdir(parents=True)
    (handlers / "broken.py").write_text("def mapped(:\n", encoding="utf-8")
    (handlers / "fine.py").write_text("def mapped():\n    return 1\n", encoding="utf-8")
    monkeypatch.setattr(
        test_map,
        "discover_branches",
        MagicMock(return_value=[{"name": "flow", "path": str(tmp_path / "flow")}]),
    )

    assert test_map.handle_command("test_map", ["@flow"]) is True
    said = capsys.readouterr()
    lines = [line for line in (said.out + said.err).splitlines() if "does not parse" in line]
    assert len(lines) == 1
    assert "broken.py" in lines[0]


def test_test_map_does_not_answer_for_another_command(monkeypatch):
    """Ownership first: a help flag never makes a module claim a command it does not own."""
    _silence_side_effects(monkeypatch, test_map)

    assert test_map.handle_command("checklist", ["--help"]) is False


def test_entry_router_intercepts_a_trailing_help_flag(monkeypatch):
    """`seedgo checklist some/file.py --help` reached route_command and ran the audit."""
    _silence_side_effects(monkeypatch, seedgo)
    module = MagicMock()
    module.handle_command = MagicMock(return_value=True)
    monkeypatch.setattr(seedgo, "discover_modules", MagicMock(return_value=[module]))
    routed = MagicMock(return_value=True)
    monkeypatch.setattr(seedgo, "route_command", routed)
    monkeypatch.setattr("sys.argv", ["seedgo", "checklist", "apps/modules/checklist.py", "--help"])

    assert seedgo.main() == 0
    assert routed.call_count == 0
    module.handle_command.assert_called_once_with("checklist", ["--help"])


def test_entry_router_still_routes_a_real_command(monkeypatch):
    _silence_side_effects(monkeypatch, seedgo)
    monkeypatch.setattr(seedgo, "discover_modules", MagicMock(return_value=[]))
    routed = MagicMock(return_value=True)
    monkeypatch.setattr(seedgo, "route_command", routed)
    monkeypatch.setattr("sys.argv", ["seedgo", "checklist", "apps/modules/checklist.py"])

    assert seedgo.main() == 0
    routed.assert_called_once_with("checklist", ["apps/modules/checklist.py"], [])


def test_entry_router_top_level_help_is_unchanged(monkeypatch):
    """`seedgo --help` still prints the branch help, not a module's."""
    _silence_side_effects(monkeypatch, seedgo)
    monkeypatch.setattr(seedgo, "discover_modules", MagicMock(return_value=[]))
    monkeypatch.setattr(seedgo, "route_command", MagicMock(return_value=True))
    printed = MagicMock()
    monkeypatch.setattr(seedgo, "print_help", printed)
    monkeypatch.setattr("sys.argv", ["seedgo", "--help"])

    assert seedgo.main() == 0
    assert printed.call_count == 1


def test_test_map_counts_a_function_tested_only_by_its_whole_name(tmp_path, monkeypatch):
    """`build` is not tested by a test that only names `rebuild`."""
    _silence_side_effects(monkeypatch, function_scanner)
    (tmp_path / "apps" / "handlers").mkdir(parents=True)
    (tmp_path / "apps" / "handlers" / "ops.py").write_text(
        "def build():\n    pass\n\ndef rebuild():\n    pass\n", encoding="utf-8"
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_ops.py").write_text("from apps.ops import rebuild\nrebuild()\n", encoding="utf-8")

    tested = {f["name"]: f["tested"] for f in function_scanner.scan_branch(str(tmp_path))["files"][0]["functions"]}

    assert tested == {"build": False, "rebuild": True}
