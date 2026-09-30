# =================== META ====================
# Name: test_seedgo_proof.py
# Description: Unit tests for the seedgo_proof module
# Version: 1.1.0
# Created: 2026-03-24
# Modified: 2026-09-27
# =============================================

"""Tests for apps/modules/seedgo_proof.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(generated) — the Rich Table rows _display_proof_results draws; Rich lays them out
# seedgo: no-test-needed(stdlib) — importlib.util.spec_from_file_location loading a handler by its path

import json
from unittest.mock import MagicMock, patch

import pytest

from aipass.seedgo.apps.modules import seedgo_proof


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _mock_infrastructure(monkeypatch):
    """Replace the header and error seams seedgo_proof reads; the console stays real, read through capsys."""
    mock_header = MagicMock()
    mock_error = MagicMock()

    monkeypatch.setattr(seedgo_proof, "header", mock_header)
    monkeypatch.setattr(seedgo_proof, "error", mock_error)


def _handlers(tmp_path, monkeypatch, target: bool = True):
    """A handlers/ tree the module discovers from: Path(__file__).parent.parent / "handlers"."""
    handlers_dir = tmp_path / "handlers"
    handlers_dir.mkdir()
    if target:
        (handlers_dir / "code_standards").mkdir()
    fake_file = tmp_path / "modules" / "seedgo_proof.py"
    fake_file.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(seedgo_proof, "__file__", str(fake_file))
    return handlers_dir


def _run_json(capsys, pack: str = "code") -> dict:
    """`proof <pack> --json`, the command a user runs, parsed off stdout."""
    capsys.readouterr()
    assert seedgo_proof.handle_command("proof", [pack, "--json"]) is True
    return json.loads(capsys.readouterr().out)


# ---------------------------------------------------------------------------
# Tests — handle_command
# ---------------------------------------------------------------------------


def test_handle_command_wrong_command_returns_false():
    """handle_command returns False for unrecognised commands."""
    assert seedgo_proof.handle_command("wrong_command", []) is False


def test_handle_command_accepts_proof_name():
    """'proof' reaches this module's introspection, not just a True."""
    with patch.object(seedgo_proof, "print_introspection") as shown:
        assert seedgo_proof.handle_command("proof", []) is True
    shown.assert_called_once_with()


def test_handle_command_accepts_seedgo_proof_name():
    """'seedgo_proof' is the same door, not a near miss returning True."""
    with patch.object(seedgo_proof, "print_introspection") as shown:
        assert seedgo_proof.handle_command("seedgo_proof", []) is True
    shown.assert_called_once_with()


def test_handle_command_help_flag():
    """--help explains and runs no pack."""
    with (
        patch.object(seedgo_proof, "print_help") as helped,
        patch.object(seedgo_proof, "_run_proof_pack") as ran,
    ):
        assert seedgo_proof.handle_command("proof", ["--help"]) is True
    helped.assert_called_once_with()
    assert ran.call_args_list == []


def test_handle_command_h_flag():
    """A help flag AFTER a pack name describes the run instead of performing it.

    The cured defect this pins, stated in handle_command itself: `proof aipass
    --help` used to run the pack. Running it and describing it both return
    True, so only the effect separates them — and one of the two is slow.
    """
    with (
        patch.object(seedgo_proof, "print_help") as helped,
        patch.object(seedgo_proof, "_run_proof_pack") as ran,
    ):
        assert seedgo_proof.handle_command("proof", ["aipass", "-h"]) is True
    helped.assert_called_once_with()
    assert ran.call_args_list == []


def test_handle_command_help_word():
    """The bare word 'help' reaches the same door as the flags."""
    with (
        patch.object(seedgo_proof, "print_help") as helped,
        patch.object(seedgo_proof, "_run_proof_pack") as ran,
    ):
        assert seedgo_proof.handle_command("proof", ["help"]) is True
    helped.assert_called_once_with()
    assert ran.call_args_list == []


def test_handle_command_unknown_pack():
    """An unknown pack is named back with the available ones, and nothing runs.

    Was `assert result is True` under a docstring promising an error was
    displayed — and this module returns True on every path, so the test
    passed with _validate_pack's whole error arm deleted.
    """
    with patch.object(seedgo_proof, "_run_proof_pack") as ran:
        assert seedgo_proof.handle_command("proof", ["nonexistent_pack_xyz"]) is True

    assert ran.call_args_list == []
    reported = seedgo_proof.error.call_args_list  # type: ignore[attr-defined]
    assert len(reported) == 1
    assert reported[0].args[0] == "Unknown proof pack: 'nonexistent_pack_xyz'"
    assert "Available packs:" in reported[0].kwargs["suggestion"]


# ---------------------------------------------------------------------------
# Tests — introspection / help
# ---------------------------------------------------------------------------


def test_print_introspection_runs(capsys):
    """print_introspection headers SEEDGO PROOF and lists the proof packs.

    "console.print OR header was called" is not an oracle — it holds for a
    function that prints one blank line and nothing else, and it is what stood
    here while nothing was measured. Both strings were read off a real run
    (2026-09-07): the header is unconditional, and the pack heading is the line
    that only appears when discovery actually found something to list.
    Mutant: the pack heading's markup unclosed in apps/modules/seedgo_proof.py — killed.
    """
    seedgo_proof.header.reset_mock()
    result = seedgo_proof.print_introspection()
    printed = capsys.readouterr().out
    headers = [call.args[0] for call in seedgo_proof.header.call_args_list if call.args]
    assert result is None
    assert headers == ["SEEDGO PROOF"], f"introspection headed itself {headers!r}"
    assert "Available Proof Packs:" in printed, f"introspection never listed the packs: {printed!r}"


def test_print_help_runs(capsys):
    """print_help prints its banner and the handler interface it demands.

    Same reason as the introspection test above. The second string is the one
    piece of help a handler author cannot work without — the signature every
    proof handler must define — so an edit that drops the interface section
    turns this red instead of passing on "something was printed".
    Mutant: the signature line's markup unclosed in apps/modules/seedgo_proof.py — killed.
    """
    result = seedgo_proof.print_help()
    printed = capsys.readouterr().out
    assert result is None
    assert "Seedgo Proof Module" in printed, f"help never named the module: {printed!r}"
    assert "scan(pack_dir: Path) -> dict" in printed, f"help never showed the handler signature: {printed!r}"


# ---------------------------------------------------------------------------
# Tests — discovery helpers
# ---------------------------------------------------------------------------


def test_discover_proof_packs_returns_dict(tmp_path, monkeypatch, capsys):
    """Mutant: a *_proof dir with no handler listed anyway in apps/modules/seedgo_proof.py — killed."""
    # Build: tmp_path/handlers/ with pack subdirectories
    handlers_dir = _handlers(tmp_path, monkeypatch)

    valid_pack = handlers_dir / "code_proof"
    valid_pack.mkdir()
    (valid_pack / "triplet_proof.py").write_text("# handler", encoding="utf-8")

    empty_pack = handlers_dir / "empty_proof"
    empty_pack.mkdir()  # no handler files -- should be skipped

    not_a_pack = handlers_dir / "random_dir"
    not_a_pack.mkdir()  # not *_proof -- should be skipped

    # Reached through `proof` with no pack: the introspection lists what discovery found.
    assert seedgo_proof.handle_command("proof", []) is True
    out = capsys.readouterr().out
    assert "code  (1 proof, target found)" in out, "Should discover 'code' from code_proof/"
    assert "empty" not in out, "Should skip dirs without handler .py files"
    assert "random_dir" not in out, "Should skip non-*_proof dirs"


def test_discover_proof_handlers_empty_dir(tmp_path, monkeypatch, capsys):
    """Mutant: an empty pack dir answered with a handler in apps/modules/seedgo_proof.py — killed."""
    (_handlers(tmp_path, monkeypatch) / "code_proof").mkdir()

    # A *_proof dir whose handler list is empty is no pack at all.
    assert seedgo_proof.handle_command("proof", []) is True
    out = capsys.readouterr().out
    assert "Available Proof Packs:" not in out
    assert "Add handler .py files" in out


def test_discover_proof_handlers_skips_init(tmp_path, monkeypatch, capsys):
    """__init__.py and _prefixed files are not proof handlers.

    Mutant: _prefixed files run as handlers in apps/modules/seedgo_proof.py — killed.
    """
    pack = _handlers(tmp_path, monkeypatch) / "code_proof"
    pack.mkdir()
    (pack / "__init__.py").write_text("", encoding="utf-8")
    (pack / "_private.py").write_text("", encoding="utf-8")
    (pack / "valid_proof.py").write_text("", encoding="utf-8")
    names = list(_run_json(capsys)["results"])
    assert "__init__" not in names
    assert "_private" not in names
    assert "valid_proof" in names


def test_discover_proof_handlers_skips_content_files(tmp_path, monkeypatch, capsys):
    """Mutant: *_content.py run as a handler in apps/modules/seedgo_proof.py — killed."""
    pack = _handlers(tmp_path, monkeypatch) / "code_proof"
    pack.mkdir()
    (pack / "architecture_content.py").write_text("", encoding="utf-8")
    (pack / "real_proof.py").write_text("", encoding="utf-8")
    names = list(_run_json(capsys)["results"])
    assert "architecture_content" not in names
    assert "real_proof" in names


def test_discover_proof_handlers_nonexistent_dir(tmp_path):
    """_discover_proof_handlers returns empty list for nonexistent directory."""
    result = seedgo_proof._discover_proof_handlers(tmp_path / "does_not_exist_xyz")
    assert result == []


# ---------------------------------------------------------------------------
# Tests — proof execution helpers
# ---------------------------------------------------------------------------


def test_run_proof_pack_missing_target(tmp_path, monkeypatch, capsys):
    """Mutant: a missing target certified in apps/modules/seedgo_proof.py — killed."""
    pack = _handlers(tmp_path, monkeypatch, target=False) / "code_proof"
    pack.mkdir()
    (pack / "any_proof.py").write_text("", encoding="utf-8")
    result = _run_json(capsys)
    assert result["certified"] is False
    assert "error" in result


def test_load_and_run_proof_missing_scan(tmp_path, monkeypatch, capsys):
    """Mutant: a handler with no scan() not marked not_implemented in apps/modules/seedgo_proof.py — killed."""
    pack = _handlers(tmp_path, monkeypatch) / "code_proof"
    pack.mkdir()
    (pack / "bad_proof.py").write_text("# no scan function\nx = 1\n", encoding="utf-8")
    result = _run_json(capsys)["results"]["bad_proof"]
    assert result["passed"] is False
    assert result.get("not_implemented") is True


def test_load_and_run_proof_working_scan(tmp_path, monkeypatch, capsys):
    """Mutant: scan()'s own result replaced in apps/modules/seedgo_proof.py — killed."""
    pack = _handlers(tmp_path, monkeypatch) / "code_proof"
    pack.mkdir()
    (pack / "good_proof.py").write_text(
        "from pathlib import Path\n"
        "def scan(pack_dir: Path) -> dict:\n"
        '    return {"passed": True, "issues": [], "summary": "All good"}\n',
        encoding="utf-8",
    )
    result = _run_json(capsys)["results"]["good_proof"]
    assert result["passed"] is True
    assert result["summary"] == "All good"


# ---------------------------------------------------------------------------
# Tests — help-flag safety (help_flag_safety: a flag ANYWHERE explains)
# ---------------------------------------------------------------------------


def test_help_after_the_pack_name_does_not_run_the_pack(monkeypatch, tmp_path):
    """`drone @seedgo proof aipass --help` ran the whole proof pack instead of describing it."""
    run = MagicMock()
    monkeypatch.setattr(seedgo_proof, "_run_proof_pack", run)
    monkeypatch.setattr(seedgo_proof, "_validate_pack", MagicMock(return_value=("aipass", tmp_path / "nowhere", False)))
    shown = MagicMock()
    monkeypatch.setattr(seedgo_proof, "print_help", shown)

    assert seedgo_proof.handle_command("proof", ["aipass", "--help"]) is True
    assert run.call_count == 0
    assert shown.call_count == 1


def test_proof_still_runs_without_a_help_flag(monkeypatch, tmp_path):
    """The gate must not swallow the real command. Mutant: display dropped in apps/modules/seedgo_proof.py — killed."""
    run = MagicMock(
        return_value={
            "pack_name": "aipass",
            "results": [],
            "passed": 0,
            "failed": 0,
            "errors": 0,
            "total": 0,
            "certified": True,
        }
    )
    monkeypatch.setattr(seedgo_proof, "_run_proof_pack", run)
    monkeypatch.setattr(seedgo_proof, "_validate_pack", MagicMock(return_value=("aipass", tmp_path / "nowhere", False)))
    shown = MagicMock()
    monkeypatch.setattr(seedgo_proof, "_display_proof_results", shown)
    helped = MagicMock()
    monkeypatch.setattr(seedgo_proof, "print_help", helped)

    assert seedgo_proof.handle_command("proof", ["aipass"]) is True
    assert run.call_count == 1
    shown.assert_called_once_with("aipass", run.return_value)
    helped.assert_not_called()


def test_proof_does_not_answer_for_another_command(monkeypatch):
    """Ownership first: a help flag never makes a module claim a command it does not own.

    Mutant: help answered before ownership in apps/modules/seedgo_proof.py — killed.
    """
    helped = MagicMock()
    monkeypatch.setattr(seedgo_proof, "print_help", helped)

    assert seedgo_proof.handle_command("checklist", ["--help"]) is False
    helped.assert_not_called()
