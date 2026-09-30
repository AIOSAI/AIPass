# =================== META ====================
# Name: test_diagnostics_audit.py
# Description: Unit tests for the diagnostics_audit module
# Version: 1.2.0
# Created: 2026-03-24
# Modified: 2026-09-29
# =============================================

"""Tests for apps/modules/diagnostics_audit.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(standard) — pyright's own findings; the handler is tested in test_diagnostics.py

import pytest
from unittest.mock import MagicMock, patch

from rich.color import Color
from rich.text import Text

from aipass.seedgo.apps.modules import diagnostics_audit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _console_lines(capsys, function_name: str, *args):
    """Call a diagnostics_audit render function and read back what it printed.

    The oracle is the rendered text on stdout, read through capsys off the
    product's real console: markup is gone, so a line is pinned as a reader
    sees it. conftest pins the console width, so no Rich wrap splits a line.

    Returns:
        (return value of the render function, list of printed lines).
    """
    result = getattr(diagnostics_audit, function_name)(*args)
    return result, capsys.readouterr().out.splitlines()


@pytest.fixture
def recording(monkeypatch):
    """The product's own console, recording every segment it prints with its style.

    No console is put in the product's place: ``record`` is the real console's
    own switch, so the channel capsys reads is unchanged. What the recording
    adds is the style plain text loses (seedgo, fleet green leg 5).

    Returns:
        A callable answering the recorded lines as ``rich.text.Text``, styles kept.
    """
    console = diagnostics_audit.console
    monkeypatch.setattr(console, "record", True)
    console.export_text(clear=True)
    return lambda: [Text.from_ansi(line) for line in console.export_text(styles=True, clear=True).splitlines()]


def colours_of(line: Text, phrase: str) -> set:
    """The colour numbers every character of ``phrase`` carries in ``line``."""
    start = line.plain.index(phrase)
    styles = (line.get_style_at_offset(diagnostics_audit.console, i) for i in range(start, start + len(phrase)))
    return {style.color.number if style.color else None for style in styles}


def colour(name: str) -> set:
    """What :func:`colours_of` answers for a phrase wholly in one named colour."""
    return {Color.parse(name).number}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _mock_infrastructure(monkeypatch):
    """Replace diagnostics_audit's own seams with mocks, at the edge, not by rebuilding the module.

    diagnostics_audit binds ``logger``, ``error`` and ``warning`` at import time
    (module-level names), so patching them directly on the real, already-imported
    module reaches every call without a stand-in for the unit under test. The
    console stays real: tests read what it printed through capsys.
    """
    monkeypatch.setattr(diagnostics_audit, "logger", MagicMock())
    monkeypatch.setattr(diagnostics_audit, "error", MagicMock())
    monkeypatch.setattr(diagnostics_audit, "warning", MagicMock())


# ---------------------------------------------------------------------------
# Tests — handle_command
# ---------------------------------------------------------------------------


def test_handle_command_wrong_command_returns_false():
    """handle_command returns False for unrecognised commands."""
    assert diagnostics_audit.handle_command("wrong_command", []) is False


def test_handle_command_accepts_diagnostics_name():
    """'diagnostics' reaches this module's introspection, not just a True."""
    with patch.object(diagnostics_audit, "print_introspection") as shown:
        assert diagnostics_audit.handle_command("diagnostics", []) is True
    shown.assert_called_once_with()


def test_handle_command_accepts_diagnostics_audit_name():
    """'diagnostics_audit' is the same door, not a near miss returning True."""
    with patch.object(diagnostics_audit, "print_introspection") as shown:
        assert diagnostics_audit.handle_command("diagnostics_audit", []) is True
    shown.assert_called_once_with()


def test_handle_command_no_args_shows_introspection(capsys):
    """No args names the module on the console, rather than erroring quietly.

    Mutant: handle_command's no-args branch skips print_introspection() (pass) — killed.
    """
    assert diagnostics_audit.handle_command("diagnostics", []) is True

    assert "Diagnostics Audit Module" in capsys.readouterr().out.splitlines()


def test_handle_command_help_flag():
    """--help explains, and does not take the unknown-argument door."""
    with (
        patch.object(diagnostics_audit, "print_help") as helped,
        patch.object(diagnostics_audit, "error") as reported,
    ):
        assert diagnostics_audit.handle_command("diagnostics", ["--help"]) is True
    helped.assert_called_once_with()
    assert reported.call_args_list == []


def test_handle_command_h_flag():
    """A help flag AFTER an argument explains instead of rejecting it.

    The cured defect this pins, stated in handle_command itself: `diagnostics
    aipass --help` used to answer "Unknown argument" for a question it can
    answer. Both sides of that bug return True.
    """
    with (
        patch.object(diagnostics_audit, "print_help") as helped,
        patch.object(diagnostics_audit, "error") as reported,
    ):
        assert diagnostics_audit.handle_command("diagnostics", ["aipass", "-h"]) is True
    helped.assert_called_once_with()
    assert reported.call_args_list == []


def test_handle_command_help_word():
    """The bare word 'help' reaches the same door as the flags."""
    with (
        patch.object(diagnostics_audit, "print_help") as helped,
        patch.object(diagnostics_audit, "error") as reported,
    ):
        assert diagnostics_audit.handle_command("diagnostics", ["help"]) is True
    helped.assert_called_once_with()
    assert reported.call_args_list == []


def test_handle_command_unknown_arg(capsys):
    """An unknown argument is named back, with the route that does work.

    Was `assert result is True` under a docstring promising an error was
    displayed gracefully — and this module returns True on every path, so the
    test passed with all six console lines and both channels deleted.

    Mutant: the unknown-argument branch drops its `drone @seedgo audit aipass` line — killed.
    """
    assert diagnostics_audit.handle_command("diagnostics", ["some_unknown_arg"]) is True

    diagnostics_audit.error.assert_called_once_with("Unknown argument: 'some_unknown_arg'")  # type: ignore[attr-defined]
    diagnostics_audit.warning.assert_called_once_with("This module has no subcommands.")  # type: ignore[attr-defined]
    assert "  drone @seedgo audit aipass" in capsys.readouterr().out.splitlines()


# ---------------------------------------------------------------------------
# Tests — introspection / help
# ---------------------------------------------------------------------------


def test_print_introspection_runs(capsys):
    """Introspection names the module, its handler package, and where the work runs.

    The `or mock_cli.header.called` this replaced pinned nothing: introspection
    never calls `header`, so the second clause was dead and the first passed on
    any single print at all.

    Mutant: print_introspection drops its Connected Handlers heading — killed.
    """
    result, lines = _console_lines(capsys, "print_introspection")

    assert result is None
    assert "Diagnostics Audit Module" in lines
    assert "Connected Handlers:" in lines
    assert "  handlers/diagnostics/" in lines
    assert "  Diagnostics checking runs through the audit pipeline:" in lines


def test_print_help_runs(capsys):
    """Help carries all three of its sections, and names pyright as the checker.

    Same escape as introspection above: `header` is never called here either.

    Mutant: print_help's first check line drops (Pylance/pyright) — killed.
    """
    result, lines = _console_lines(capsys, "print_help")

    assert result is None
    assert "COMMANDS:" in lines
    assert "EXAMPLES:" in lines
    assert "WHAT IT CHECKS:" in lines
    assert "  - Type errors (Pylance/pyright)" in lines


# ---------------------------------------------------------------------------
# Tests — display functions
# ---------------------------------------------------------------------------


def test_print_branch_diagnostics_clean(capsys, recording):
    """Zero errors renders the green tick and the file tally, and no top-files block.

    Mutant: zero errors gets the yellow warning sign instead of the tick — killed.
    The colour is read off the real console's recording, since capsys holds
    the plain text only (seedgo, fleet green leg 5). Mutant: the zero case's
    colour "green" -> "yellow", glyph kept — killed.
    """
    result = {
        "branch": "TEST",
        "total_errors": 0,
        "total_warnings": 0,
        "total_files": 5,
        "files_with_errors": 0,
        "results": [],
    }

    _, lines = _console_lines(capsys, "print_branch_diagnostics", result)

    assert "✓ TEST" in lines
    assert "  Files: 5 analyzed, 0 with errors" in lines
    assert "  Errors: 0  Warnings: 0" in lines
    assert "  Top files with errors:" not in lines
    recorded = recording()
    errors_line = next(line for line in recorded if line.plain == "  Errors: 0  Warnings: 0")
    assert colours_of(errors_line, "Errors: 0") == colour("green")
    assert colours_of(next(line for line in recorded if line.plain == "✓ TEST"), "✓") == colour("green")


def test_print_branch_diagnostics_with_errors(capsys, recording):
    """15 errors renders the red cross, and the offending file with its first lines.

    Mutant: ten or more errors gets the yellow warning sign instead of the cross — killed.
    The colour is read off the real console's recording (seedgo, fleet green
    leg 5). Mutant: the ten-or-more case's colour "red" -> "yellow", glyph kept — killed.
    """
    result = {
        "branch": "TEST",
        "total_errors": 15,
        "total_warnings": 3,
        "total_files": 10,
        "files_with_errors": 2,
        "results": [
            {
                "file": "/some/path/test.py",
                "errors": 5,
                "diagnostics": [
                    {"line": 10, "message": "Type mismatch"},
                    {"line": 20, "message": "Undefined variable 'x'"},
                ],
            }
        ],
    }

    _, lines = _console_lines(capsys, "print_branch_diagnostics", result)

    assert "✗ TEST" in lines
    assert "  Files: 10 analyzed, 2 with errors" in lines
    assert "  Errors: 15  Warnings: 3" in lines
    assert "  Top files with errors:" in lines
    assert "    • /some/path/test.py (5 errors)" in lines
    assert "      L10: Type mismatch" in lines
    assert "      L20: Undefined variable 'x'" in lines
    recorded = recording()
    errors_line = next(line for line in recorded if line.plain == "  Errors: 15  Warnings: 3")
    assert colours_of(errors_line, "Errors: 15") == colour("red")
    assert colours_of(next(line for line in recorded if line.plain == "✗ TEST"), "✗") == colour("red")


def test_print_system_summary_empty(capsys):
    """An empty fleet totals to zero everywhere, and lists no branches by error count.

    Mutant: the by-error-count block prints at zero branches with errors (>= 0) — killed.
    """
    _, lines = _console_lines(capsys, "print_system_summary", [])

    assert "SYSTEM DIAGNOSTICS SUMMARY:" in lines
    assert "  Total branches:        0" in lines
    assert "  Clean branches:        0" in lines
    assert "  Total errors:          0" in lines
    assert "BRANCHES BY ERROR COUNT:" not in lines


def test_print_system_summary_with_data(capsys):
    """Two branches: the totals add up, and only the one with errors gets listed.

    Mutant: the by-error-count block lists every branch (if True:) — killed.
    """
    results = [
        {"branch": "FLOW", "total_errors": 0, "total_warnings": 1, "total_files": 5, "files_with_errors": 0},
        {"branch": "CLI", "total_errors": 3, "total_warnings": 0, "total_files": 8, "files_with_errors": 2},
    ]

    _, lines = _console_lines(capsys, "print_system_summary", results)

    assert "  Total branches:        2" in lines
    assert "  Clean branches:        1" in lines
    assert "  Branches with errors:  1" in lines
    assert "  Files analyzed:        13" in lines
    assert "  Total errors:          3" in lines
    assert "  Total warnings:        1" in lines
    assert "BRANCHES BY ERROR COUNT:" in lines
    assert "  CLI                3 errors" in lines
    assert not [line for line in lines if line.startswith("  FLOW")], "clean branches are not listed by error count"


# ---------------------------------------------------------------------------
# Help-flag safety (help_flag_safety: a flag ANYWHERE explains)
# ---------------------------------------------------------------------------


def test_help_after_an_argument_prints_help_not_an_error(monkeypatch):
    """`drone @seedgo diagnostics aipass --help` answered "Unknown argument" instead of explaining."""
    shown = MagicMock()
    monkeypatch.setattr(diagnostics_audit, "print_help", shown)
    complained = MagicMock()
    monkeypatch.setattr(diagnostics_audit, "error", complained)

    assert diagnostics_audit.handle_command("diagnostics", ["aipass", "--help"]) is True
    assert shown.call_count == 1
    assert complained.call_count == 0


def test_unknown_argument_without_a_help_flag_still_errors(monkeypatch):
    """The gate must not swallow the module's fail-loud behaviour."""
    complained = MagicMock()
    monkeypatch.setattr(diagnostics_audit, "error", complained)

    assert diagnostics_audit.handle_command("diagnostics", ["aipass"]) is True
    assert complained.call_count == 1


def test_diagnostics_does_not_answer_for_another_command():
    """Ownership first: a help flag never makes a module claim a command it does not own."""
    assert diagnostics_audit.handle_command("checklist", ["--help"]) is False
