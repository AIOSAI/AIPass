# =================== META ====================
# Name: test_standards_query.py
# Description: Unit tests for the standards_query module
# Version: 1.3.0
# Created: 2026-03-24
# Modified: 2026-10-17
# =============================================

"""Tests for apps/modules/standards_query.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(shared) — what each content file's standards function returns; tests/test_content_functions.py
# seedgo: no-test-needed(shared) — wants_help's own flag grammar; tests/test_help_flags.py
# seedgo: no-test-needed(shared) — json_handler.log_operation's write; tests/test_json_handler_contract.py

import pytest
from unittest.mock import patch

from aipass.seedgo.apps.handlers.aipass_standards.json_structure_check import CUSTOM_CONFIG_GUIDE
from aipass.seedgo.apps.handlers.audit_tests import refusal
from aipass.seedgo.apps.modules import CommandRefused, standards_query
from aipass.seedgo.apps.modules.standards_query import ALIAS_COMMAND, QUERY_COMMAND, handle_command


@pytest.fixture
def two_packs(tmp_path, monkeypatch):
    """Two packs on disk, both defining `dupe` and only b defining `extra`: the only packs the module finds."""
    packs = {}
    for pack_name, stems in (("a_standards", ["dupe"]), ("b_standards", ["dupe", "extra"])):
        pack = tmp_path / pack_name
        pack.mkdir()
        for stem in stems:
            (pack / f"{stem}_content.py").write_text(
                f"def get_{stem}_standards():\n    return 'CONTENT OF {pack_name} {stem}'\n", encoding="utf-8"
            )
        packs[pack_name] = pack
    # The disk edge: the real discovery walks seedgo's own handlers/ directory.
    monkeypatch.setattr(standards_query, "_discover_packs", lambda: packs)
    return packs


def test_handle_command_wrong_command_returns_false():
    """handle_command returns False for unrecognised commands."""
    assert handle_command("wrong_command", []) is False


def test_handle_command_no_args_shows_introspection():
    """No args shows introspection, and does not fall through to help."""
    with (
        patch.object(standards_query, "print_introspection") as shown,
        patch.object(standards_query, "print_help") as helped,
    ):
        assert standards_query.handle_command("standards_query", []) is True
    shown.assert_called_once_with()
    assert helped.call_args_list == []


def test_handle_command_help_flag():
    """--help explains and discovers no packs."""
    with (
        patch.object(standards_query, "print_help") as helped,
        patch.object(standards_query, "_discover_packs") as discovered,
    ):
        assert standards_query.handle_command("standards_query", ["--help"]) is True
    helped.assert_called_once_with()
    assert discovered.call_args_list == []


def test_handle_command_h_flag():
    """A help flag AFTER a pack name explains it, never looks up a standard named '-h'."""
    with (
        patch.object(standards_query, "print_help") as helped,
        patch.object(standards_query, "_discover_packs") as discovered,
    ):
        assert standards_query.handle_command("standards_query", ["aipass_standards", "-h"]) is True
    helped.assert_called_once_with()
    assert discovered.call_args_list == []


def test_handle_command_help_word():
    """The bare word 'help' reaches the same door as the flags."""
    with (
        patch.object(standards_query, "print_help") as helped,
        patch.object(standards_query, "_discover_packs") as discovered,
    ):
        assert standards_query.handle_command("standards_query", ["help"]) is True
    helped.assert_called_once_with()
    assert discovered.call_args_list == []


def test_handle_command_unknown_pack():
    """An unknown pack REFUSES with a non-zero code, it does not return quietly."""
    with pytest.raises(CommandRefused) as refused:
        handle_command("standards_query", ["nonexistent_pack_xyz"])
    assert refused.value.code == refusal.EXIT_UNKNOWN_ARGUMENT
    assert refused.value.token == "nonexistent_pack_xyz"


def test_print_introspection_runs(capsys):
    """print_introspection lists the discovered packs and how to open each one."""
    standards_query.print_introspection()

    lines = capsys.readouterr().out.splitlines()
    assert "standards_query Module" in lines
    assert "Discovered Packs:" in lines
    assert "  handlers/pytest_quality_standards/" in lines
    assert "  drone @seedgo standards_query aipass_standards" in lines


def test_print_help_runs(capsys):
    """print_help documents all three call forms and names its own commands."""
    standards_query.print_help()

    out = capsys.readouterr().out
    assert "Standards Query Module" in out
    assert "COMMANDS:" in out
    assert "  drone @seedgo standards_query aipass_standards architecture" in out
    assert "Commands: standards_query, standard, --help" in out


def test_introspection_finds_the_four_packs_each_mapped_to_its_own_directory(capsys):
    """The bare command names seedgo's four packs and lists each pack's own content files."""
    assert handle_command(QUERY_COMMAND, []) is True

    out = capsys.readouterr().out
    prefix = "drone @seedgo standards_query "
    listed = {line.strip().removeprefix(prefix) for line in out.splitlines() if line.strip().startswith(prefix)}
    assert listed == {
        "aipass_standards",
        "context_standards",
        "pytest_quality_standards",
        "tests_pytest_standards",
    }
    assert "- json_structure_content.py (get_json_structure_standards)" in out


def test_a_pack_with_no_content_files_says_so_and_lists_nothing(tmp_path, monkeypatch, capsys):
    """A pack directory holding no *_content.py is reported empty, not listed."""
    monkeypatch.setattr(standards_query, "_discover_packs", lambda: {"empty_standards": tmp_path})

    assert handle_command(QUERY_COMMAND, ["empty_standards"]) is True

    out, err = capsys.readouterr()
    assert "No content handlers found." in err
    assert "Add *_content.py files to handlers/empty_standards/" in out
    assert "Available Standards" not in out


def test_a_pack_lists_its_content_files_and_nothing_else(tmp_path, monkeypatch, capsys):
    """A pack lists the standards its *_content.py files name, never another .py beside them."""
    (tmp_path / "architecture_content.py").write_text("# fake", encoding="utf-8")
    (tmp_path / "architecture_check.py").write_text("# fake", encoding="utf-8")
    monkeypatch.setattr(standards_query, "_discover_packs", lambda: {"tmp_standards": tmp_path})

    assert handle_command(QUERY_COMMAND, ["tmp_standards"]) is True

    out = capsys.readouterr().out
    assert "Available Standards: (1)" in out
    assert "  architecture\n" in out
    assert "architecture_check" not in out


def test_alias_no_args_lists_all_standards(capsys):
    """`standard` with no args puts real standard names on the console."""
    assert handle_command("standard", []) is True

    out = capsys.readouterr().out
    assert "  json_structure\n" in out
    assert "  architecture\n" in out


def test_alias_shows_content_for_known_standard(capsys):
    """`standard json_structure` resolves the pack itself and prints THAT content."""
    assert handle_command("standard", ["json_structure"]) is True

    out = capsys.readouterr().out
    assert "JSON STRUCTURE STANDARD" in out
    assert "Operational JSON Output" in out


def test_alias_unknown_standard_refuses_with_a_non_zero_code():
    """Unknown standard name is REFUSED, not reported and then called a success."""
    with pytest.raises(CommandRefused) as refused:
        handle_command("standard", ["nonexistent_standard_xyz"])
    assert refused.value.code == refusal.EXIT_UNKNOWN_ARGUMENT
    assert refused.value.token == "nonexistent_standard_xyz"


def test_alias_help_flag():
    """`standard --help` explains the alias and resolves no standard."""
    with (
        patch.object(standards_query, "print_alias_help") as helped,
        patch.object(standards_query, "_resolve_standard") as resolved,
    ):
        assert standards_query.handle_command("standard", ["--help"]) is True
    helped.assert_called_once_with()
    assert resolved.call_args_list == []


def test_print_alias_help_runs(capsys):
    """print_alias_help explains the short form and points back at the long one."""
    standards_query.print_alias_help()

    out = capsys.readouterr().out
    assert "Standard (short alias)" in out
    assert "  drone @seedgo standard json_structure" in out
    assert "  Short form of standards_query <pack> <standard>." in out
    assert "Commands: standard, --help" in out


def test_alias_resolves_a_name_one_pack_defines_to_that_packs_content(two_packs, capsys):
    """`standard extra` finds the one pack that defines it and prints that pack's content."""
    assert handle_command(ALIAS_COMMAND, ["extra"]) is True

    assert "CONTENT OF b_standards extra" in capsys.readouterr().out


def test_alias_unknown_name_is_refused_and_lists_the_names_it_knows(two_packs, capsys):
    """A name no pack defines is refused, and the landing list shows what does exist."""
    with pytest.raises(CommandRefused) as refused:
        handle_command(ALIAS_COMMAND, ["nope"])
    assert refused.value.code == refusal.EXIT_UNKNOWN_ARGUMENT

    out, err = capsys.readouterr()
    assert "Unknown standard: 'nope'" in err
    assert "Available Standards: (2)" in out
    assert "CONTENT OF" not in out


def test_alias_landing_lists_each_name_once_across_every_pack(two_packs, capsys):
    """The landing counts a name two packs define once, and still lists the second pack's own names."""
    assert handle_command(ALIAS_COMMAND, []) is True

    out = capsys.readouterr().out
    assert "Available Standards: (2)" in out
    assert out.count("  dupe\n") == 1
    assert "  extra\n" in out
    assert "  drone @seedgo standard dupe" in out


def test_alias_ambiguous_name_refuses_to_guess(two_packs, capsys):
    """Two packs defining one name → error + explicit form, no content loaded."""
    with pytest.raises(CommandRefused) as refused:
        handle_command(ALIAS_COMMAND, ["dupe"])
    assert refused.value.code == 7, "refusing to guess is a refusal, and a refusal is not exit 0"

    out, err = capsys.readouterr()
    assert "Ambiguous standard: 'dupe' is defined in 2 packs" in err
    assert "  drone @seedgo standards_query a_standards dupe" in out
    assert "  drone @seedgo standards_query b_standards dupe" in out
    assert "CONTENT OF" not in out


def test_alias_does_not_swallow_other_commands():
    """The alias must not claim commands owned by other modules."""
    assert handle_command("audit", ["aipass"]) is False
    assert handle_command("checklist", ["some_file.py"]) is False


def test_custom_config_guide_pointer_actually_resolves(capsys):
    """The guide command embedded in audit output must be a real, working command."""
    command_text = CUSTOM_CONFIG_GUIDE.split("Guide:", 1)[-1].strip()
    tokens = [str(token) for token in command_text.split()]
    assert tokens[:2] == ["drone", "@seedgo"], f"Pointer is not a drone command: {command_text}"

    command, args = tokens[2], tokens[3:]
    assert command in (QUERY_COMMAND, ALIAS_COMMAND), f"Pointer cites unknown command '{command}'"

    assert handle_command(command, args) is True, f"Pointer does not resolve: {command_text}"
    assert args[-1].replace("_", " ").upper() + " STANDARD" in capsys.readouterr().out


def test_help_after_the_pack_name_does_not_display_content(capsys):
    """`drone @seedgo standards_query aipass_standards --help` looked up a standard named '--help'."""
    assert handle_command(QUERY_COMMAND, ["aipass_standards", "--help"]) is True

    out = capsys.readouterr().out
    assert "Standards Query Module" in out
    assert "STANDARDS IN AIPASS_STANDARDS" not in out


def test_standards_query_still_displays_content_without_a_help_flag(capsys):
    """The gate must not swallow the real command."""
    assert handle_command(QUERY_COMMAND, ["aipass_standards", "json_structure"]) is True

    out = capsys.readouterr().out
    assert "JSON STRUCTURE STANDARD" in out
    assert "Standards Query Module" not in out


def test_alias_help_after_the_standard_name_does_not_display_content(capsys):
    """`drone @seedgo standard cli --help` printed the whole standard instead of the alias help."""
    assert handle_command(ALIAS_COMMAND, ["json_structure", "--help"]) is True

    out = capsys.readouterr().out
    assert "Standard (short alias)" in out
    assert "JSON STRUCTURE STANDARD" not in out


def test_alias_still_displays_content_without_a_help_flag(capsys):
    """The gate must not swallow the real command."""
    assert handle_command(ALIAS_COMMAND, ["json_structure"]) is True

    out = capsys.readouterr().out
    assert "JSON STRUCTURE STANDARD" in out
    assert "Standard (short alias)" not in out


def test_standards_query_does_not_answer_for_another_command(capsys):
    """Ownership first: a help flag never makes a module claim a command it does not own."""
    assert handle_command("proof_query", ["--help"]) is False

    assert capsys.readouterr().out == ""
