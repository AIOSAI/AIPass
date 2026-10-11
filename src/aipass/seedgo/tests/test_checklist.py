# =================== META ====================
# Name: test_checklist.py
# Description: Unit tests for the checklist module
# Version: 1.3.3
# Created: 2026-03-24
# Modified: 2026-10-10
# =============================================

"""Tests for apps/modules/checklist.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(standard) — each checker's own verdict; every <row>_check.py has its own test file
# seedgo: no-test-needed(stdlib) — argparse's own parsing of the flag list

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from aipass.seedgo.apps.handlers.aipass_standards import skip_dirs
from aipass.seedgo.apps.handlers.audit import branch_audit
from aipass.seedgo.apps.handlers.bypass import bypass_handler
from aipass.seedgo.apps.modules import checklist


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _mock_infrastructure(monkeypatch):
    """Default seams checklist reads, so a test that does not override them
    stays deterministic and never touches the live repo's registry or the
    real checker packs.

    discover_checkers -> {} is the "no checkers discovered" floor most of the
    tests below assert on. get_branch_from_path -> None and load_bypass_rules
    -> [] keep branch/bypass resolution off the live AIPASS_REGISTRY.json
    (template item 17). Tests that need a real branch or real checkers
    override the seam themselves, on the same module object.
    """
    monkeypatch.setattr(checklist, "discover_checkers", lambda pack_path=None: {})
    monkeypatch.setattr(checklist, "get_branch_from_path", lambda file_path: None)
    monkeypatch.setattr(checklist, "load_bypass_rules", lambda branch_path: [])


# ---------------------------------------------------------------------------
# Tests — handle_command
# ---------------------------------------------------------------------------


def test_handle_command_wrong_command_returns_false():
    """handle_command returns False for unrecognised commands."""
    assert checklist.handle_command("wrong_command", []) is False


def test_handle_command_no_args_shows_introspection():
    """No args shows introspection, and does not fall through to help."""
    with (
        patch.object(checklist, "print_introspection") as shown,
        patch.object(checklist, "print_help") as helped,
    ):
        assert checklist.handle_command("checklist", []) is True
    shown.assert_called_once_with()
    assert helped.call_args_list == []


def test_handle_command_help_flag():
    """--help explains and runs nothing."""
    with (
        patch.object(checklist, "print_help") as helped,
        patch.object(checklist, "run_checklist") as ran,
    ):
        assert checklist.handle_command("checklist", ["--help"]) is True
    helped.assert_called_once_with()
    assert ran.call_args_list == []


def test_handle_command_h_flag():
    """A help flag AFTER a file explains the run instead of performing it.

    The cured defect this pins, stated in handle_command itself: `checklist
    <file> --help` used to run the full per-file audit it was being asked to
    describe. Only the position of the flag distinguishes the two, and the
    return value is True either way.
    """
    with (
        patch.object(checklist, "print_help") as helped,
        patch.object(checklist, "run_checklist") as ran,
    ):
        assert checklist.handle_command("checklist", ["some_file.py", "-h"]) is True
    helped.assert_called_once_with()
    assert ran.call_args_list == []


def test_handle_command_help_word():
    """The bare word 'help' reaches the same door as the flags."""
    with (
        patch.object(checklist, "print_help") as helped,
        patch.object(checklist, "run_checklist") as ran,
    ):
        assert checklist.handle_command("checklist", ["help"]) is True
    helped.assert_called_once_with()
    assert ran.call_args_list == []


# ---------------------------------------------------------------------------
# Tests — run_checklist
# ---------------------------------------------------------------------------


def test_run_checklist_file_not_found(tmp_path):
    """run_checklist returns error result for missing file."""
    missing = tmp_path / "nonexistent.py"
    results = checklist.run_checklist(str(missing))
    assert len(results) == 1
    assert results[0]["passed"] is False
    assert results[0]["standard"] == "(error)"
    assert results[0]["detail"] == f"File not found: {missing.resolve()}"


def test_run_checklist_non_python_file(tmp_path):
    """run_checklist skips non-Python files gracefully."""
    txt_file = tmp_path / "readme.txt"
    txt_file.write_text("hello", encoding="utf-8")
    results = checklist.run_checklist(str(txt_file))
    assert len(results) == 1
    assert results[0]["passed"] is True
    assert "not a python" in results[0]["detail"].lower()


def test_run_checklist_python_file_no_checkers(tmp_path, monkeypatch):
    """A Python file with no checkers to run is a failing error row, never a silent pass.

    Mutant: the empty-pack guard (if not checkers) removed in apps/modules/checklist.py — killed.
    """
    # tmp_path sits under the system temp root, which the lane skips as throwaway
    # before it ever loads a pack; neutered so the empty pack is what is measured.
    monkeypatch.setattr(skip_dirs, "_get_temp_roots", lambda: [])
    py_file = tmp_path / "sample.py"
    py_file.write_text("x = 1\n", encoding="utf-8")
    results = checklist.run_checklist(str(py_file))
    # The autouse fixture's pack discovers nothing: one failing error row, never a silent pass.
    assert results == [{"standard": "(error)", "passed": False, "detail": "No checkers discovered"}]


def test_a_door_passes_every_standard_on_the_checklist(tmp_path, monkeypatch):
    """The door shape (DPLAN-0404 leg 1) passes the real pack: no CLI, no introspection, no logic asked.

    A re-export of its own handlers with __all__ seated in memory's modules; the
    seat has no apps/__init__.py and no handlers/, so the guard row is not asked.
    """
    monkeypatch.setattr(skip_dirs, "_get_temp_roots", lambda: [])
    monkeypatch.setattr(checklist, "discover_checkers", branch_audit.discover_checkers)
    door = tmp_path / "aipass" / "memory" / "apps" / "modules" / "door_entry_limits.py"
    door.parent.mkdir(parents=True)
    door.write_text(
        "# =================== AIPass ====================\n"
        "# Name: door_entry_limits.py\n"
        "# Description: Door - memory's entry limits, for other branches\n"
        "# Version: 1.0.0\n"
        "# Created: 2026-10-07\n"
        "# Modified: 2026-10-07\n"
        "# =============================================\n\n"
        '"""Door: memory\'s entry limits, for other branches."""\n\n'
        "from aipass.memory.apps.handlers.json.entry_limits import check_file_budget, load_entry_limits\n\n"
        '__all__ = ["load_entry_limits", "check_file_budget"]\n',
        encoding="utf-8",
    )

    results = checklist.run_checklist(str(door))
    assert [r["standard"] for r in results if not r["passed"]] == []
    assert len(results) == 41  # +2 on 2026-10-10: clear_text_secret_logging, exception_text_in_response

    # The same door with a function in it is a wrong shape: modules FAILS on the
    # checklist, not a tick at 80 (DPLAN-0404, measured on a CLI-shaped door 10-07)
    door.write_text(door.read_text(encoding="utf-8") + "\n\ndef helper():\n    return 1\n", encoding="utf-8")
    assert "modules" in [r["standard"] for r in checklist.run_checklist(str(door)) if not r["passed"]]


def test_run_checklist_throwaway_temp_path_skipped(tmp_path, monkeypatch):
    """Files under system temp dirs are skipped."""
    monkeypatch.setattr(skip_dirs, "_get_temp_roots", lambda: [tmp_path])

    tmp_file = tmp_path / "test_throwaway.py"
    tmp_file.write_text("x = 1\n", encoding="utf-8")
    results = checklist.run_checklist(str(tmp_file))
    assert len(results) == 1
    assert results[0]["passed"] is True
    assert results[0]["standard"] == "(skip)"
    assert results[0]["detail"] == "Throwaway path (temp/scratchpad) — skipped"


def test_run_checklist_scratchpad_path_skipped(tmp_path):
    """Files under a scratchpad directory are skipped."""
    scratch_dir = tmp_path / "scratchpad"
    scratch_dir.mkdir()
    f = scratch_dir / "poc.py"
    f.write_text("x = 1\n", encoding="utf-8")
    results = checklist.run_checklist(str(f))
    assert len(results) == 1
    assert results[0]["passed"] is True
    assert results[0]["standard"] == "(skip)"
    assert results[0]["detail"] == "Throwaway path (temp/scratchpad) — skipped"


def test_run_checklist_prototype_flag_skips(tmp_path, monkeypatch, capsys):
    """--prototype skips all standards.

    Mutant: handle_command drops --prototype (prototype = False) in apps/modules/checklist.py — killed.
    """
    monkeypatch.setattr(skip_dirs, "_get_temp_roots", lambda: [])

    f = tmp_path / "poc.py"
    f.write_text("x = 1\n", encoding="utf-8")
    assert checklist.handle_command("checklist", ["--prototype", str(f)]) is True
    shown = capsys.readouterr().out
    # A skip row prints no detail. Without the flag this file reaches the
    # (stubbed, empty) pack and prints an (error) row instead of the skip.
    assert "(skip)" in shown
    assert "(error)" not in shown
    # The row the flag hands back, read from the public function it drives.
    results = checklist.run_checklist(str(f), prototype=True)
    assert len(results) == 1
    assert results[0]["passed"] is True
    assert "prototype" in results[0]["detail"].lower()


def test_run_checklist_prototype_marker_skips(tmp_path, monkeypatch):
    """In-file '# seedgo: prototype' marker skips all standards."""
    monkeypatch.setattr(skip_dirs, "_get_temp_roots", lambda: [])

    f = tmp_path / "poc.py"
    f.write_text("# seedgo: prototype\nx = 1\n", encoding="utf-8")
    results = checklist.run_checklist(str(f))
    assert len(results) == 1
    assert results[0]["passed"] is True
    assert "prototype" in results[0]["detail"].lower()


def test_run_checklist_seedgo_ignore_skips(tmp_path, monkeypatch):
    """A file under apps/tools/ is skipped via the global .seedgoignore default."""
    monkeypatch.setattr(skip_dirs, "_get_temp_roots", lambda: [])
    monkeypatch.setattr(checklist, "get_branch_from_path", lambda file_path: {"path": str(tmp_path)})
    monkeypatch.setattr(checklist, "load_bypass_rules", lambda branch_path: [])

    tools_dir = tmp_path / "apps" / "tools"
    tools_dir.mkdir(parents=True)
    f = tools_dir / "scratch.py"
    f.write_text("x = 1\n", encoding="utf-8")
    results = checklist.run_checklist(str(f))
    assert len(results) == 1
    assert results[0]["passed"] is True
    assert "seedgoignore" in results[0]["detail"].lower()


def test_run_checklist_normal_file_still_audited(tmp_path, monkeypatch):
    """A normal file without markers/temp path is still fully audited."""
    monkeypatch.setattr(skip_dirs, "_get_temp_roots", lambda: [])

    f = tmp_path / "real_code.py"
    f.write_text("def main(): pass\n", encoding="utf-8")
    results = checklist.run_checklist(str(f))
    # Floor: the audit lane produced exactly one row (the mocked pack discovers
    # no checkers), so the loop below cannot pass over an empty list.
    assert len(results) == 1
    # Should NOT get throwaway/prototype skip
    for r in results:
        detail = r.get("detail", "")
        assert "throwaway" not in detail.lower()
        assert "prototype" not in detail.lower()


# ---------------------------------------------------------------------------
# Tests — print_introspection / print_help
# ---------------------------------------------------------------------------


def test_print_introspection_runs(capsys):
    """The no-args introspection names the packs it discovered.

    Mutant: pack discovery matches no *_standards dir in apps/modules/checklist.py — killed.
    """
    assert checklist.handle_command("checklist", []) is True
    shown = capsys.readouterr().out
    assert "Discovered Packs:" in shown
    assert "aipass" in shown
    assert "No packs found" not in shown


def test_print_help_runs(capsys):
    """--help prints the usage, the --pack line included.

    Mutant: print_help drops its --pack usage line in apps/modules/checklist.py — killed.
    """
    assert checklist.handle_command("checklist", ["--help"]) is True
    shown = capsys.readouterr().out
    assert "USAGE:" in shown
    assert "drone @seedgo checklist --pack" in shown


# ---------------------------------------------------------------------------
# Tests — internal helpers
# ---------------------------------------------------------------------------


def test_is_entry_point_detection(tmp_path, monkeypatch):
    """An entry_point row runs on apps/{name}.py files only.

    Mutant: _is_entry_point answers True for any .py under apps/ in apps/modules/checklist.py — killed.
    """
    # Through run_checklist: an entry_point-scoped row runs on apps/{name}.py only.
    monkeypatch.setattr(skip_dirs, "_get_temp_roots", lambda: [])
    entry = SimpleNamespace(AUDIT_SCOPE="entry_point", check_module=lambda path, bypass_rules=None: {"passed": True})
    monkeypatch.setattr(checklist, "discover_checkers", lambda pack_path=None: {"entry": entry})
    apps = tmp_path / "some" / "branch" / "apps"
    (apps / "modules").mkdir(parents=True)
    for target in (apps / "flow.py", apps / "modules" / "helper.py", apps / "readme.txt"):
        target.write_text("x = 1\n", encoding="utf-8")

    def standards(target):
        return [r["standard"] for r in checklist.run_checklist(str(target))]

    assert standards(apps / "flow.py") == ["entry"]
    assert standards(apps / "modules" / "helper.py") == ["(skip)"]
    assert standards(apps / "readme.txt") == ["(skip)"]


def _failure_detail(tmp_path, monkeypatch, checks):
    """The detail run_checklist prints for one failing row carrying these checks."""
    monkeypatch.setattr(skip_dirs, "_get_temp_roots", lambda: [])
    failing = SimpleNamespace(
        AUDIT_SCOPE="all_files", check_module=lambda path, bypass_rules=None: {"passed": False, "checks": checks}
    )
    monkeypatch.setattr(checklist, "discover_checkers", lambda pack_path=None: {"row": failing})
    target = tmp_path / "thing.py"
    target.write_text("x = 1\n", encoding="utf-8")
    [row] = checklist.run_checklist(str(target))
    assert row["standard"] == "row" and row["passed"] is False
    return row["detail"]


def test_format_failure_no_checks(tmp_path, monkeypatch):
    """_format_failure returns fallback when no failed checks present."""
    result = _failure_detail(tmp_path, monkeypatch, [])
    assert "no details" in result.lower()


def test_format_failure_single_failure(tmp_path, monkeypatch):
    """_format_failure returns the message from the first failed check."""
    result = _failure_detail(tmp_path, monkeypatch, [{"passed": False, "message": "Missing docstring"}])
    assert "Missing docstring" in result


def test_format_failure_multiple_failures(tmp_path, monkeypatch):
    """_format_failure indicates additional failures."""
    result = _failure_detail(
        tmp_path,
        monkeypatch,
        [{"passed": False, "message": "Missing docstring"}, {"passed": False, "message": "No type hints"}],
    )
    assert "+1 more" in result


# ---------------------------------------------------------------------------
# Tests — a finding must be countable by a script (FPLAN, @spawn mail)
#
# Every assertion below is made against bytes read back out of the product's
# real console, through capsys. A MagicMock console records the arguments
# -- those were always correct, that is not the defect -- and renders nothing.
# The marker has to survive Rich's markup parser, and only rendered bytes can
# prove that: an unescaped "[FAIL]" is eaten at render time and the recorded
# call argument still looks perfect.
# ---------------------------------------------------------------------------


def _rendered_results(tmp_path, monkeypatch, capsys, messages):
    """handle_command's output on one file, one all_files row per entry of messages.

    A message of True is a passing row; any other value is the message of the
    row's one failing check, and None is how a failing row reaches the terminal
    with no detail (_format_failure hands back the message it was given).
    """

    def row(message):
        failing = {"passed": False, "checks": [{"passed": False, "message": message}]}
        verdict = {"passed": True} if message is True else failing
        return SimpleNamespace(AUDIT_SCOPE="all_files", check_module=lambda path, bypass_rules=None: verdict)

    pack = {name: row(message) for name, message in messages.items()}
    monkeypatch.setattr(skip_dirs, "_get_temp_roots", lambda: [])
    monkeypatch.setattr(checklist, "discover_checkers", lambda pack_path=None: pack)
    target = tmp_path / "thing.py"
    target.write_text("x = 1\n", encoding="utf-8")
    assert checklist.handle_command("checklist", [str(target)]) is True
    return capsys.readouterr().out


_MIXED_RESULTS = {"handlers": "3 functions outside handlers/", "cli": True, "readme_quality": None}


def test_each_finding_carries_a_greppable_marker(tmp_path, monkeypatch, capsys):
    """@spawn grepped this output for a cross, got zero hits across 18 files, and
    nearly deleted 41 bypass rules on that 'proof'. The marker a script counts
    must be a plain ASCII token that is present once per finding -- not a
    decorative em dash a reader has to guess at.

    Mutant: the detailed failure line drops _FINDING_MARKUP in apps/modules/checklist.py — killed.
    """
    rendered = _rendered_results(tmp_path, monkeypatch, capsys, _MIXED_RESULTS)

    assert rendered.count("[FAIL]") == 2, f"one marker per finding, got: {rendered!r}"
    # The published constant is the contract callers grep for, so it is pinned to
    # the bytes that actually reach a terminal -- not to what was handed to Rich.
    assert checklist.FINDING_MARKER == "[FAIL]"
    assert rendered.count(checklist.FINDING_MARKER) == 2


def test_the_marker_is_not_printed_on_passing_standards(tmp_path, monkeypatch, capsys):
    """The other direction: a count that includes passes is as wrong as zero.

    Mutant: the pass line prints _FINDING_MARKUP before its check mark in apps/modules/checklist.py — killed.
    """
    rendered = _rendered_results(tmp_path, monkeypatch, capsys, _MIXED_RESULTS)

    passing = [line for line in rendered.splitlines() if "cli" in line]
    assert passing and all("[FAIL]" not in line for line in passing), rendered


def test_the_marker_appears_on_a_detail_free_finding(tmp_path, monkeypatch, capsys):
    """Both failure branches emit it -- a finding with no detail still counts.

    Mutant: the detail-free failure line drops _FINDING_MARKUP in apps/modules/checklist.py — killed.
    """
    rendered = _rendered_results(tmp_path, monkeypatch, capsys, {"readme_quality": None})

    assert rendered.count("[FAIL]") == 1, rendered
    assert "  [FAIL] — readme_quality\n" in rendered, rendered


def test_the_human_layout_survives_the_marker(tmp_path, monkeypatch, capsys):
    """The em dash stays: this output is read by people between hook runs.

    Mutant: the detailed failure line trades its em dash for a hyphen in apps/modules/checklist.py — killed.
    """
    rendered = _rendered_results(tmp_path, monkeypatch, capsys, _MIXED_RESULTS)

    assert rendered.count("—") == 2, rendered
    assert "✓ cli" in rendered, rendered
    assert "3 functions outside handlers/" in rendered, rendered


def test_help_documents_the_marker(capsys):
    """A signal scripts are meant to key on is only stable if it is published.

    Mutant: the help's grep line counts '\\[X]' instead of '\\[FAIL]' in apps/modules/checklist.py — killed.
    """
    assert checklist.handle_command("checklist", ["--help"]) is True
    shown = capsys.readouterr().out

    assert "[FAIL]" in shown
    # The published count recipe itself, not only the OUTPUT FORMAT sample row.
    assert "grep -c '[FAIL]'" in shown


# ---------------------------------------------------------------------------
# Help-flag safety (help_flag_safety: a flag ANYWHERE explains)
# ---------------------------------------------------------------------------


def test_help_after_the_file_path_does_not_run_the_checklist(monkeypatch):
    """`drone @seedgo checklist <file> --help` ran a full per-file audit instead of describing one."""
    run = MagicMock()
    monkeypatch.setattr(checklist, "run_checklist", run)
    shown = MagicMock()
    monkeypatch.setattr(checklist, "print_help", shown)

    assert checklist.handle_command("checklist", ["apps/modules/checklist.py", "--help"]) is True
    assert run.call_count == 0
    assert shown.call_count == 1


def test_help_after_a_pack_flag_does_not_run_the_checklist(monkeypatch):
    """The flag can trail any operand — `checklist --pack aipass <file> -h` is still a question."""
    run = MagicMock()
    monkeypatch.setattr(checklist, "run_checklist", run)
    shown = MagicMock()
    monkeypatch.setattr(checklist, "print_help", shown)

    assert checklist.handle_command("checklist", ["--pack", "aipass", "apps/modules/checklist.py", "-h"]) is True
    assert run.call_count == 0
    assert shown.call_count == 1


def test_checklist_still_runs_without_a_help_flag(monkeypatch, tmp_path):
    """The gate must not swallow the real command."""
    target = tmp_path / "thing.py"
    target.write_text("x = 1\n", encoding="utf-8")
    run = MagicMock(return_value=[])
    monkeypatch.setattr(checklist, "run_checklist", run)

    assert checklist.handle_command("checklist", [str(target)]) is True
    assert run.call_count == 1


def test_checklist_does_not_answer_for_another_command():
    """Ownership first: a help flag never makes a module claim a command it does not own."""
    assert checklist.handle_command("audit", ["--help"]) is False


# ---------------------------------------------------------------------------
# Branch-level rows the checklist cannot judge are named, not silently dropped
#
# backup's conftest printed "All 37 standards passed" here while the audit
# convicted it under unused_conftest_fixture -- a branch_level checker with no
# check_module(), which this lane skips by design. The skip stays; the silence
# does not.
# ---------------------------------------------------------------------------


def _fake_pack():
    """A pack with one per-file row and branch-level rows of every applicability."""

    def _passes(path, bypass_rules=None):
        return {"passed": True, "checks": []}

    def _branch(path, bypass_rules=None):
        return {"passed": True, "checks": []}

    return {
        "per_file": SimpleNamespace(AUDIT_SCOPE="all_files", check_module=_passes),
        "unused_conftest_fixture": SimpleNamespace(
            AUDIT_SCOPE="branch_level", APPLIES_TO="tests", check_branch=_branch
        ),
        "dead_code": SimpleNamespace(AUDIT_SCOPE="branch_level", APPLIES_TO="production", check_branch=_branch),
        "template": SimpleNamespace(AUDIT_SCOPE="branch_level", check_branch=_branch),
        "ruff": SimpleNamespace(AUDIT_SCOPE="branch_level", check_module=_passes, check_branch=_branch),
        "cli_flags": SimpleNamespace(AUDIT_SCOPE="entry_point", APPLIES_TO="production", check_module=_passes),
    }


def _write(tmp_path, rel):
    target = tmp_path / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("x = 1\n", encoding="utf-8")
    return target


def test_a_test_file_names_its_tests_only_branch_rows(tmp_path, monkeypatch):
    """The conftest case: unused_conftest_fixture applies and was not judged here."""
    monkeypatch.setattr(checklist, "discover_checkers", lambda pack: _fake_pack())
    conftest = _write(tmp_path, "branch/tests/conftest.py")

    assert checklist.not_judged_here(str(conftest)) == ["template", "unused_conftest_fixture"]


def test_a_production_file_does_not_name_tests_only_rows(tmp_path, monkeypatch):
    """Applicability gates the list: a module never hears about a conftest standard."""
    monkeypatch.setattr(checklist, "discover_checkers", lambda pack: _fake_pack())
    module = _write(tmp_path, "branch/apps/modules/thing.py")

    assert checklist.not_judged_here(str(module)) == ["dead_code", "template"]


def test_rows_the_checklist_does_run_are_not_named(tmp_path, monkeypatch):
    """ruff is branch_level but has check_module(), so it is judged here; entry_point rows are never listed."""
    monkeypatch.setattr(checklist, "discover_checkers", lambda pack: _fake_pack())
    entry = _write(tmp_path, "branch/apps/branch.py")

    named = checklist.not_judged_here(str(entry))
    assert "ruff" not in named and "cli_flags" not in named and "per_file" not in named
    assert named == ["dead_code", "template"]


def _rendered_command(monkeypatch, capsys, target, pack=None):
    """handle_command's output on target, read off the product's console at width 60."""
    # tmp_path sits under the system temp root, which the lane skips as throwaway;
    # exempt this target only, and leave the real gate in place for anything else.
    real_gate = checklist.is_throwaway_path
    exempt = str(target.resolve())
    monkeypatch.setattr(checklist, "is_throwaway_path", lambda path: path != exempt and real_gate(path))
    chosen = pack if pack is not None else _fake_pack()
    monkeypatch.setattr(checklist, "discover_checkers", lambda pack_path: chosen)
    # Narrower than the not-judged line, so only soft_wrap keeps it one line.
    monkeypatch.setattr(checklist.console, "width", 60)
    assert checklist.handle_command("checklist", [str(target)]) is True
    return capsys.readouterr().out


def test_the_not_judged_line_leaves_the_count_alone(tmp_path, monkeypatch, capsys):
    """Through the command: one unwrapped line, after the summary, and the pass count is unchanged.

    Mutant: _print_not_judged drops soft_wrap=True in apps/modules/checklist.py — killed.
    """
    rendered = _rendered_command(monkeypatch, capsys, _write(tmp_path, "branch/tests/conftest.py"))
    lines = rendered.splitlines()

    # per_file + ruff ran; the two branch-only rows were named, not counted.
    assert "All 2 standards passed" in lines
    not_judged = [line for line in lines if line.startswith("Not judged here")]
    assert not_judged == [
        "Not judged here (branch-level, run by `drone @seedgo audit`): template, unused_conftest_fixture"
    ]
    assert lines.index(not_judged[0]) > lines.index("All 2 standards passed")
    assert "[FAIL]" not in rendered


def test_the_not_judged_line_is_fenced_off_from_the_last_finding(tmp_path, monkeypatch, capsys):
    """hooks' auto_fix rejoins a finding's wrapped detail until a blank line, so one must come first.

    Mutant: _print_not_judged drops its leading blank console.print() in apps/modules/checklist.py — killed.
    """
    pack = _fake_pack()
    pack["per_file"] = SimpleNamespace(
        AUDIT_SCOPE="all_files",
        check_module=lambda path, bypass_rules=None: {
            "passed": False,
            "checks": [{"passed": False, "message": "bad"}],
        },
    )
    target = _write(tmp_path, "branch/tests/conftest.py")
    rendered = _rendered_command(monkeypatch, capsys, target, pack)
    lines = rendered.splitlines()

    at = next(i for i, line in enumerate(lines) if line.startswith("Not judged here"))
    assert lines[at - 1] == ""
    assert rendered.count("[FAIL]") == 1


# ---------------------------------------------------------------------------
# Inert bypass rules (fleet green leg 13): a lines rule against a checker that
# passes no line closes nothing; the checklist names it, and changes no verdict.
# The scope map is the real one, read from the checker sources: todo passes no
# line, cli does.
# ---------------------------------------------------------------------------


def _with_rules(tmp_path, monkeypatch, capsys, rules, passing=True):
    """handle_command's output and run_checklist's results on thing.py, one todo row and one cli row."""
    verdict = {"passed": True} if passing else {"passed": False, "checks": [{"passed": False, "message": "bad"}]}
    row = SimpleNamespace(AUDIT_SCOPE="all_files", check_module=lambda path, bypass_rules=None: verdict)
    monkeypatch.setattr(skip_dirs, "_get_temp_roots", lambda: [])
    monkeypatch.setattr(checklist, "discover_checkers", lambda pack_path=None: {"todo": row, "cli": row})
    monkeypatch.setattr(checklist, "get_branch_from_path", lambda file_path: {"path": str(tmp_path)})
    monkeypatch.setattr(checklist, "load_bypass_rules", lambda branch_path: rules)
    target = tmp_path / "thing.py"
    target.write_text("x = 1\n", encoding="utf-8")
    results = checklist.run_checklist(str(target))
    assert checklist.handle_command("checklist", [str(target)]) is True
    return capsys.readouterr().out, {r["standard"]: r for r in results}


def test_a_lines_rule_on_a_checker_that_passes_no_line_is_named(tmp_path, monkeypatch, capsys):
    """Red first: the rule sat in bypass.json and the checklist said nothing at all.

    Mutants in apps/handlers/bypass/inert.py and apps/modules/checklist.py, each
    killed at an assert here or below: inert_notes returns []; the standard match
    is dropped; the result never carries the notes.
    """
    rules = [{"file": "thing.py", "standard": "todo", "lines": [3], "reason": "r"}]
    rendered, results = _with_rules(tmp_path, monkeypatch, capsys, rules)

    note = "bypass rule 'lines' [3] closes nothing: this checker passes no line, so only a file-wide rule bypasses it"
    assert results["todo"].get("bypass_notes") == [note]
    assert results["todo"]["passed"] is True
    assert results["cli"].get("bypass_notes") is None, "the todo rule is no note on the cli row"
    assert f"inert bypass — todo: {note}" in rendered
    assert "All 2 standards passed" in rendered
    assert "[FAIL]" not in rendered


def test_a_rule_the_checker_can_honour_is_not_named(tmp_path, monkeypatch, capsys):
    """Controls: a lines rule on cli (which passes a line), a file-wide todo rule, and
    a lines todo rule for another file each draw no note."""
    rules = [
        {"file": "thing.py", "standard": "cli", "lines": [3], "reason": "r"},
        {"file": "thing.py", "standard": "todo", "reason": "r"},
        {"file": "other.py", "standard": "todo", "lines": [3], "reason": "r"},
    ]
    rendered, results = _with_rules(tmp_path, monkeypatch, capsys, rules)

    assert "bypass_notes" not in results["todo"]
    assert "bypass_notes" not in results["cli"]
    assert "inert bypass" not in rendered


def test_the_inert_note_is_fenced_off_from_the_last_finding(tmp_path, monkeypatch, capsys):
    """hooks' auto_fix rejoins a finding's wrapped detail until a blank line, so a note
    after a finding is fenced by one and never read as part of it."""
    rules = [{"file": "thing.py", "standard": "todo", "lines": [3], "reason": "r"}]
    rendered, _ = _with_rules(tmp_path, monkeypatch, capsys, rules, passing=False)
    lines = rendered.splitlines()

    found = [i for i, line in enumerate(lines) if "inert bypass" in line]
    assert len(found) == 1, rendered
    at = found[0]
    assert lines[at - 1] == ""
    assert lines[at - 2].endswith("[FAIL] — todo: bad")
    assert rendered.count("[FAIL]") == 2


# ---------------------------------------------------------------------------
# An unreadable registry (fleet green leg 15, devpulse's ruling): no raise, the
# verdicts stay as they are, and the checklist says it once after them.
# ---------------------------------------------------------------------------


def _unreadable_registry(tmp_path, monkeypatch):
    """A registry file that is not JSON, found by the real get_branch_from_path."""
    registry = tmp_path / "AIPASS_REGISTRY.json"
    registry.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(bypass_handler, "_find_registry", lambda: registry)
    monkeypatch.setattr(bypass_handler, "UNREADABLE_REGISTRIES", {})
    # The module's autouse stand-in answers None without reading; this lane needs the real read.
    monkeypatch.setattr(checklist, "get_branch_from_path", bypass_handler.get_branch_from_path)
    return registry


def test_an_unreadable_registry_is_named_once_after_the_verdicts(tmp_path, monkeypatch, capsys):
    """Red first: the registry failed, every bypass rule went unread, and the checklist said nothing."""
    registry = _unreadable_registry(tmp_path, monkeypatch)
    rendered = _rendered_command(monkeypatch, capsys, _write(tmp_path, "branch/tests/conftest.py"))
    lines = rendered.splitlines()

    found = [i for i, line in enumerate(lines) if "registry unreadable" in line]
    assert len(found) == 1, rendered
    assert registry.name in lines[found[0]]
    assert lines[found[0] - 1] == ""
    assert found[0] > lines.index("All 2 standards passed")
    assert "[FAIL]" not in rendered


def test_a_readable_registry_draws_no_note(tmp_path, monkeypatch, capsys):
    """Control: the same run over a registry that parses says nothing about it."""
    registry = _unreadable_registry(tmp_path, monkeypatch)
    registry.write_text('{"branches": []}', encoding="utf-8")
    rendered = _rendered_command(monkeypatch, capsys, _write(tmp_path, "branch/tests/conftest.py"))

    assert "registry unreadable" not in rendered
    assert "All 2 standards passed" in rendered.splitlines()
