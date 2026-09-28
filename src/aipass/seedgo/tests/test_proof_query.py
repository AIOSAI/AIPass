# =================== META ====================
# Name: test_proof_query.py
# Description: Unit tests for the proof_query module
# Version: 1.1.0
# Created: 2026-03-24
# Modified: 2026-09-27
# =============================================

"""Tests for apps/modules/proof_query.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(stdlib) — importlib.util.spec_from_file_location's loading of a proof content handler

import pytest
from unittest.mock import MagicMock, patch

from aipass.seedgo.apps.handlers.audit_tests import refusal
from aipass.seedgo.apps.modules import CommandRefused, proof_query
from aipass.seedgo.apps.modules.proof_query import (
    _discover_proof_content,
    handle_command,
    print_help,
    print_introspection,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _mock_infrastructure(monkeypatch):
    """Mock heavy infrastructure imports for proof_query."""
    mock_logger = MagicMock()
    mock_warning = MagicMock()
    mock_error = MagicMock()
    mock_json_handler = MagicMock()

    monkeypatch.setattr(proof_query, "logger", mock_logger)
    monkeypatch.setattr(proof_query, "warning", mock_warning)
    monkeypatch.setattr(proof_query, "error", mock_error)
    monkeypatch.setattr(proof_query, "json_handler", mock_json_handler)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_handle_command_wrong_command_returns_false():
    """handle_command returns False for unrecognised commands."""
    assert handle_command("wrong_command", []) is False


def test_handle_command_no_args_shows_introspection():
    """No args shows introspection, not help and not a pack lookup."""
    with (
        patch.object(proof_query, "print_introspection") as shown,
        patch.object(proof_query, "print_help") as helped,
    ):
        assert proof_query.handle_command("proof_query", []) is True
    shown.assert_called_once_with()
    assert helped.call_args_list == []


def test_handle_command_help_flag():
    """--help explains and looks nothing up."""
    with (
        patch.object(proof_query, "print_help") as helped,
        patch.object(proof_query, "_discover_proof_packs") as discovered,
    ):
        assert proof_query.handle_command("proof_query", ["--help"]) is True
    helped.assert_called_once_with()
    assert discovered.call_args_list == []


def test_handle_command_h_flag():
    """A help flag AFTER a pack name explains it, never looks up a proof named '-h'.

    The cured defect this pins, stated in handle_command itself: `proof_query
    aipass_proof --help` used to look up a proof named '--help'. The return
    value is True on both sides of that bug.
    """
    with (
        patch.object(proof_query, "print_help") as helped,
        patch.object(proof_query, "_discover_proof_packs") as discovered,
    ):
        assert proof_query.handle_command("proof_query", ["aipass_proof", "-h"]) is True
    helped.assert_called_once_with()
    assert discovered.call_args_list == []


def test_handle_command_help_word():
    """The bare word 'help' reaches the same door as the flags."""
    with (
        patch.object(proof_query, "print_help") as helped,
        patch.object(proof_query, "_discover_proof_packs") as discovered,
    ):
        assert proof_query.handle_command("proof_query", ["help"]) is True
    helped.assert_called_once_with()
    assert discovered.call_args_list == []


def test_handle_command_unknown_pack():
    """An unknown pack REFUSES with a non-zero code, it does not return quietly.

    It returned True until 2026-09-07 and `seedgo.py` turned that into exit 0,
    so a script reading the exit code saw a successful query of a pack that
    does not exist (the owner's standing ruling, fleet sweep 2026-09-07).
    """
    with pytest.raises(CommandRefused) as refused:
        handle_command("proof_query", ["nonexistent_pack_xyz"])
    assert refused.value.code == refusal.EXIT_UNKNOWN_ARGUMENT
    assert refused.value.token == "nonexistent_pack_xyz"


def test_print_introspection_runs(capsys):
    """print_introspection prints the module banner and the pack roster.

    "console.print was called" is not an oracle: it holds for a function that prints one blank line,
    and it held while nothing else was measured. The two strings pinned here were read off a real
    run (2026-09-07) and they are the two the introspection contract owes a reader — WHICH module
    answered, and the heading under which its discovered packs are listed.
    Mutant: malformed markup on the roster heading in apps/modules/proof_query.py — killed.
    """
    result = print_introspection()
    printed = capsys.readouterr().out
    assert result is None
    assert "proof_query Module" in printed, f"introspection never named the module: {printed!r}"
    assert "Discovered Proof Packs:" in printed, f"introspection never listed the packs: {printed!r}"


def test_print_help_runs(capsys):
    """print_help prints its banner and the pack+proof usage line.

    Same reason as the introspection test above: `console.print.called` passes for any function that
    prints anything at all. The usage line is the one a reader comes to help FOR — the three-argument
    form that shows one proof's content — so that is what is pinned, read off a real run (2026-09-07).
    Mutant: malformed markup on that usage line in apps/modules/proof_query.py — killed.
    """
    result = print_help()
    printed = capsys.readouterr().out
    assert result is None
    assert "Proof Query Module" in printed, f"help never named the module: {printed!r}"
    assert "proof_query <pack> <proof>" in printed, f"help never showed the pack+proof form: {printed!r}"


def test_discover_proof_packs_returns_dict(tmp_path, monkeypatch, capsys):
    """Only *_proof dirs holding a *_content.py are packs.

    Mutant: a pack admitted without content in apps/modules/proof_query.py — killed.
    """
    # Build: tmp_path/handlers/ with pack subdirectories
    handlers_dir = tmp_path / "handlers"
    handlers_dir.mkdir()

    valid_pack = handlers_dir / "code_proof"
    valid_pack.mkdir()
    (valid_pack / "triplet_content.py").write_text("# content", encoding="utf-8")

    empty_pack = handlers_dir / "empty_proof"
    empty_pack.mkdir()  # no *_content.py files -- should be skipped

    not_a_pack = handlers_dir / "random_dir"
    not_a_pack.mkdir()  # not *_proof -- should be skipped

    # Patch __file__ so Path(__file__).parent.parent / "handlers" -> handlers_dir
    fake_file = tmp_path / "modules" / "proof_query.py"
    fake_file.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(proof_query, "__file__", str(fake_file))

    # code_proof is a pack, and its path is valid_pack: the proof listed is the one written there.
    capsys.readouterr()
    assert proof_query.handle_command("proof_query", ["code_proof"]) is True
    assert "drone @seedgo proof_query code_proof triplet" in capsys.readouterr().out
    for skipped in ("empty_proof", "random_dir"):
        with pytest.raises(CommandRefused) as refused:
            proof_query.handle_command("proof_query", [skipped])
        assert refused.value.token == skipped, f"Should skip {skipped}"


def test_discover_proof_content_empty_dir(tmp_path):
    """_discover_proof_content returns empty dict for a directory with no content files."""
    result = _discover_proof_content(tmp_path)
    assert result == {}


def test_discover_proof_content_finds_content_files(tmp_path, monkeypatch, capsys):
    """A pack's proofs are its *_content.py files, suffix stripped.

    Mutant: the _content suffix kept in apps/modules/proof_query.py — killed.
    """
    pack = tmp_path / "handlers" / "fake_proof"
    pack.mkdir(parents=True)
    (pack / "triplet_content.py").write_text("# fake", encoding="utf-8")
    (pack / "not_a_content.py").write_text("# fake", encoding="utf-8")
    monkeypatch.setattr(proof_query, "__file__", str(tmp_path / "modules" / "proof_query.py"))
    capsys.readouterr()
    assert proof_query.handle_command("proof_query", ["fake_proof"]) is True
    result = [
        line.strip()
        for line in capsys.readouterr().out.splitlines()
        if line.startswith("  ") and " " not in line.strip()
    ]
    assert "triplet" in result
    assert "not_a_content" not in result


# ---------------------------------------------------------------------------
# Tests — help-flag safety (help_flag_safety: a flag ANYWHERE explains)
# ---------------------------------------------------------------------------


def test_help_after_the_pack_name_does_not_query(monkeypatch, tmp_path):
    """`drone @seedgo proof_query aipass_proof --help` looked up a proof named '--help'."""
    monkeypatch.setattr(proof_query, "_discover_proof_packs", MagicMock(return_value={"aipass_proof": tmp_path}))
    show = MagicMock()
    monkeypatch.setattr(proof_query, "_show_proof_content", show)
    shown = MagicMock()
    monkeypatch.setattr(proof_query, "print_help", shown)

    assert proof_query.handle_command("proof_query", ["aipass_proof", "--help"]) is True
    assert show.call_count == 0
    assert shown.call_count == 1


def test_proof_query_still_queries_without_a_help_flag(monkeypatch, tmp_path):
    """The gate must not swallow the real command."""
    monkeypatch.setattr(proof_query, "_discover_proof_packs", MagicMock(return_value={"aipass_proof": tmp_path}))
    show = MagicMock()
    monkeypatch.setattr(proof_query, "_show_proof_content", show)

    assert proof_query.handle_command("proof_query", ["aipass_proof", "triplet"]) is True
    assert show.call_count == 1


def test_proof_query_does_not_answer_for_another_command(monkeypatch):
    """Ownership first: a help flag never makes a module claim a command it does not own."""
    assert proof_query.handle_command("standards_query", ["--help"]) is False
