"""Tests for checklist module."""

# =================== META ====================
# Name: test_checklist.py
# Description: Unit tests for the checklist module
# Version: 1.0.0
# Created: 2026-03-24
# Modified: 2026-03-24
# =============================================

import pytest
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _mock_infrastructure(monkeypatch):
    """Mock heavy infrastructure imports for checklist."""
    import sys

    from aipass.seedgo.apps.handlers.bypass.ignore_handler import (
        is_seedgo_ignored as real_is_seedgo_ignored,
        load_ignore_entries as real_load_ignore_entries,
    )

    mock_logger = MagicMock()
    mock_console = MagicMock()
    mock_error = MagicMock()
    mock_json_handler = MagicMock()

    # -- prax ---------------------------------------------------------------
    prax_mod = MagicMock()
    prax_mod.logger = mock_logger
    monkeypatch.setitem(sys.modules, "aipass.prax", prax_mod)

    # -- cli ----------------------------------------------------------------
    cli_mod = MagicMock()
    cli_mod.console = mock_console
    monkeypatch.setitem(sys.modules, "aipass.cli", cli_mod)

    cli_apps = MagicMock()
    monkeypatch.setitem(sys.modules, "aipass.cli.apps", cli_apps)

    cli_modules = MagicMock()
    cli_modules.error = mock_error
    monkeypatch.setitem(sys.modules, "aipass.cli.apps.modules", cli_modules)

    # -- seedgo json handler ------------------------------------------------
    json_pkg = MagicMock()
    json_pkg.json_handler = mock_json_handler
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.json", json_pkg)
    json_mod = MagicMock()
    json_mod.log_operation = mock_json_handler.log_operation
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.json.json_handler", json_mod)

    # -- branch_audit (discover_checkers) ------------------------------------
    audit_pkg = MagicMock()
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.audit", audit_pkg)
    branch_audit_mod = MagicMock()
    branch_audit_mod.discover_checkers = MagicMock(return_value={})
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.audit.branch_audit", branch_audit_mod)

    # -- bypass handler -----------------------------------------------------
    bypass_pkg = MagicMock()
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.bypass", bypass_pkg)
    bypass_mod = MagicMock()
    bypass_mod.get_branch_from_path = MagicMock(return_value=None)
    bypass_mod.load_bypass_rules = MagicMock(return_value=[])
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.bypass.bypass_handler", bypass_mod)

    ignore_mod = MagicMock()
    ignore_mod.is_seedgo_ignored = real_is_seedgo_ignored
    ignore_mod.load_ignore_entries = real_load_ignore_entries
    bypass_pkg.ignore_handler = ignore_mod
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.bypass.ignore_handler", ignore_mod)

    # Force re-import
    monkeypatch.delitem(sys.modules, "aipass.seedgo.apps.modules.checklist", raising=False)


# ---------------------------------------------------------------------------
# Tests — handle_command
# ---------------------------------------------------------------------------


def test_handle_command_wrong_command_returns_false():
    """handle_command returns False for unrecognised commands."""
    from aipass.seedgo.apps.modules.checklist import handle_command

    assert handle_command("wrong_command", []) is False


def test_handle_command_no_args_shows_introspection():
    """No args triggers introspection (returns True)."""
    from aipass.seedgo.apps.modules.checklist import handle_command

    result = handle_command("checklist", [])
    assert result is True


def test_handle_command_help_flag():
    """--help flag is handled without error."""
    from aipass.seedgo.apps.modules.checklist import handle_command

    result = handle_command("checklist", ["--help"])
    assert result is True


def test_handle_command_h_flag():
    """-h flag is handled without error."""
    from aipass.seedgo.apps.modules.checklist import handle_command

    result = handle_command("checklist", ["-h"])
    assert result is True


def test_handle_command_help_word():
    """'help' word is handled without error."""
    from aipass.seedgo.apps.modules.checklist import handle_command

    result = handle_command("checklist", ["help"])
    assert result is True


# ---------------------------------------------------------------------------
# Tests — run_checklist
# ---------------------------------------------------------------------------


def test_run_checklist_file_not_found(tmp_path):
    """run_checklist returns error result for missing file."""
    from aipass.seedgo.apps.modules.checklist import run_checklist

    results = run_checklist(str(tmp_path / "nonexistent.py"))
    assert len(results) == 1
    assert results[0]["passed"] is False
    assert "not found" in results[0]["detail"].lower() or "File not found" in results[0]["detail"]


def test_run_checklist_non_python_file(tmp_path):
    """run_checklist skips non-Python files gracefully."""
    from aipass.seedgo.apps.modules.checklist import run_checklist

    txt_file = tmp_path / "readme.txt"
    txt_file.write_text("hello", encoding="utf-8")
    results = run_checklist(str(txt_file))
    assert len(results) == 1
    assert results[0]["passed"] is True
    assert "not a python" in results[0]["detail"].lower()


def test_run_checklist_python_file_no_checkers(tmp_path):
    """run_checklist on a Python file with no applicable checkers returns skip."""
    from aipass.seedgo.apps.modules.checklist import run_checklist

    py_file = tmp_path / "sample.py"
    py_file.write_text("x = 1\n", encoding="utf-8")
    results = run_checklist(str(py_file))
    # With mocked empty checkers, should get either skip or error
    assert len(results) >= 1
    assert isinstance(results[0], dict)


def test_run_checklist_throwaway_temp_path_skipped(tmp_path, monkeypatch):
    """Files under system temp dirs are skipped."""
    import sys

    from aipass.seedgo.apps.modules.checklist import run_checklist

    skip_dirs = sys.modules.get("aipass.seedgo.apps.handlers.aipass_standards.skip_dirs")
    if skip_dirs:
        monkeypatch.setattr(skip_dirs, "_get_temp_roots", lambda: [tmp_path])

    tmp_file = tmp_path / "test_throwaway.py"
    tmp_file.write_text("x = 1\n", encoding="utf-8")
    results = run_checklist(str(tmp_file))
    assert len(results) == 1
    assert results[0]["passed"] is True
    assert "throwaway" in results[0]["detail"].lower() or "temp" in results[0]["detail"].lower()


def test_run_checklist_scratchpad_path_skipped(tmp_path):
    """Files under a scratchpad directory are skipped."""
    from aipass.seedgo.apps.modules.checklist import run_checklist

    scratch_dir = tmp_path / "scratchpad"
    scratch_dir.mkdir()
    f = scratch_dir / "poc.py"
    f.write_text("x = 1\n", encoding="utf-8")
    results = run_checklist(str(f))
    assert len(results) == 1
    assert results[0]["passed"] is True
    assert "throwaway" in results[0]["detail"].lower() or "scratchpad" in results[0]["detail"].lower()


def test_run_checklist_prototype_flag_skips(tmp_path, monkeypatch):
    """prototype=True skips all standards."""
    import sys

    skip_dirs = sys.modules.get("aipass.seedgo.apps.handlers.aipass_standards.skip_dirs")
    if skip_dirs:
        monkeypatch.setattr(skip_dirs, "_get_temp_roots", lambda: [])

    from aipass.seedgo.apps.modules.checklist import run_checklist

    f = tmp_path / "poc.py"
    f.write_text("x = 1\n", encoding="utf-8")
    results = run_checklist(str(f), prototype=True)
    assert len(results) == 1
    assert results[0]["passed"] is True
    assert "prototype" in results[0]["detail"].lower()


def test_run_checklist_prototype_marker_skips(tmp_path, monkeypatch):
    """In-file '# seedgo: prototype' marker skips all standards."""
    import sys

    skip_dirs = sys.modules.get("aipass.seedgo.apps.handlers.aipass_standards.skip_dirs")
    if skip_dirs:
        monkeypatch.setattr(skip_dirs, "_get_temp_roots", lambda: [])

    from aipass.seedgo.apps.modules.checklist import run_checklist

    f = tmp_path / "poc.py"
    f.write_text("# seedgo: prototype\nx = 1\n", encoding="utf-8")
    results = run_checklist(str(f))
    assert len(results) == 1
    assert results[0]["passed"] is True
    assert "prototype" in results[0]["detail"].lower()


def test_run_checklist_seedgo_ignore_skips(tmp_path, monkeypatch):
    """A file under apps/tools/ is skipped via the global .seedgoignore default."""
    import sys

    from aipass.seedgo.apps.handlers.aipass_standards import skip_dirs

    monkeypatch.setattr(skip_dirs, "_get_temp_roots", lambda: [])

    branch_mod = MagicMock()
    branch_mod.get_branch_from_path = MagicMock(return_value={"path": str(tmp_path)})
    branch_mod.load_bypass_rules = MagicMock(return_value=[])
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.bypass.bypass_handler", branch_mod)

    from aipass.seedgo.apps.modules.checklist import run_checklist

    tools_dir = tmp_path / "apps" / "tools"
    tools_dir.mkdir(parents=True)
    f = tools_dir / "scratch.py"
    f.write_text("x = 1\n", encoding="utf-8")
    results = run_checklist(str(f))
    assert len(results) == 1
    assert results[0]["passed"] is True
    assert "seedgoignore" in results[0]["detail"].lower()


def test_run_checklist_normal_file_still_audited(tmp_path, monkeypatch):
    """A normal file without markers/temp path is still fully audited."""
    import sys

    skip_dirs = sys.modules.get("aipass.seedgo.apps.handlers.aipass_standards.skip_dirs")
    if skip_dirs:
        monkeypatch.setattr(skip_dirs, "_get_temp_roots", lambda: [])

    from aipass.seedgo.apps.modules.checklist import run_checklist

    f = tmp_path / "real_code.py"
    f.write_text("def main(): pass\n", encoding="utf-8")
    results = run_checklist(str(f))
    # Should NOT get throwaway/prototype skip
    for r in results:
        detail = r.get("detail", "")
        assert "throwaway" not in detail.lower()
        assert "prototype" not in detail.lower()


# ---------------------------------------------------------------------------
# Tests — print_introspection / print_help
# ---------------------------------------------------------------------------


def test_print_introspection_runs():
    """print_introspection produces console output."""
    import sys
    from aipass.seedgo.apps.modules.checklist import print_introspection

    mock_cli = sys.modules["aipass.cli"]
    mock_cli.console.reset_mock()
    result = print_introspection()
    assert result is None
    assert mock_cli.console.print.called, "print_introspection should produce console output"


def test_print_help_runs():
    """print_help produces console output."""
    import sys
    from aipass.seedgo.apps.modules.checklist import print_help

    mock_cli = sys.modules["aipass.cli"]
    mock_cli.console.reset_mock()
    result = print_help()
    assert result is None
    assert mock_cli.console.print.called, "print_help should produce console output"


# ---------------------------------------------------------------------------
# Tests — internal helpers
# ---------------------------------------------------------------------------


def test_is_entry_point_detection():
    """_is_entry_point correctly identifies apps/{name}.py files."""
    from aipass.seedgo.apps.modules.checklist import _is_entry_point

    assert _is_entry_point("/some/branch/apps/flow.py") is True
    assert _is_entry_point("/some/branch/apps/modules/helper.py") is False
    assert _is_entry_point("/some/branch/apps/readme.txt") is False


def test_format_failure_no_checks():
    """_format_failure returns fallback when no failed checks present."""
    from aipass.seedgo.apps.modules.checklist import _format_failure

    result = _format_failure({"checks": []})
    assert "no details" in result.lower()


def test_format_failure_single_failure():
    """_format_failure returns the message from the first failed check."""
    from aipass.seedgo.apps.modules.checklist import _format_failure

    result = _format_failure(
        {
            "checks": [
                {"passed": False, "message": "Missing docstring"},
            ]
        }
    )
    assert "Missing docstring" in result


def test_format_failure_multiple_failures():
    """_format_failure indicates additional failures."""
    from aipass.seedgo.apps.modules.checklist import _format_failure

    result = _format_failure(
        {
            "checks": [
                {"passed": False, "message": "Missing docstring"},
                {"passed": False, "message": "No type hints"},
            ]
        }
    )
    assert "+1 more" in result


# ---------------------------------------------------------------------------
# Tests — a finding must be countable by a script (FPLAN, @spawn mail)
#
# Every assertion below is made against bytes read back out of a REAL Console.
# The autouse fixture installs a MagicMock console, which records the arguments
# -- those were always correct, that is not the defect -- and renders nothing.
# The marker has to survive Rich's markup parser, and only rendered bytes can
# prove that: an unescaped "[FAIL]" is eaten at render time and the recorded
# call argument still looks perfect.
# ---------------------------------------------------------------------------


def _rendered_results(monkeypatch, results, file_path="/repo/branch/apps/thing.py"):
    """_print_results output as a terminal actually receives it."""
    import io

    from rich.console import Console

    from aipass.seedgo.apps.modules import checklist

    buffer = io.StringIO()
    monkeypatch.setattr(checklist, "console", Console(file=buffer, force_terminal=False, width=300))
    checklist._print_results(results, file_path)
    return buffer.getvalue()


_MIXED_RESULTS = [
    {"standard": "handlers", "passed": False, "detail": "3 functions outside handlers/"},
    {"standard": "cli", "passed": True, "detail": None},
    {"standard": "readme_quality", "passed": False, "detail": None},
]


def test_each_finding_carries_a_greppable_marker(monkeypatch):
    """@spawn grepped this output for a cross, got zero hits across 18 files, and
    nearly deleted 41 bypass rules on that 'proof'. The marker a script counts
    must be a plain ASCII token that is present once per finding -- not a
    decorative em dash a reader has to guess at.
    """
    from aipass.seedgo.apps.modules import checklist

    rendered = _rendered_results(monkeypatch, _MIXED_RESULTS)

    assert rendered.count("[FAIL]") == 2, f"one marker per finding, got: {rendered!r}"
    # The published constant is the contract callers grep for, so it is pinned to
    # the bytes that actually reach a terminal -- not to what was handed to Rich.
    assert checklist.FINDING_MARKER == "[FAIL]"
    assert rendered.count(checklist.FINDING_MARKER) == 2


def test_the_marker_is_not_printed_on_passing_standards(monkeypatch):
    """The other direction: a count that includes passes is as wrong as zero."""
    rendered = _rendered_results(monkeypatch, _MIXED_RESULTS)

    passing = [line for line in rendered.splitlines() if "cli" in line]
    assert passing and all("[FAIL]" not in line for line in passing), rendered


def test_the_marker_appears_on_a_detail_free_finding(monkeypatch):
    """Both failure branches emit it -- a finding with no detail still counts."""
    rendered = _rendered_results(monkeypatch, [{"standard": "readme_quality", "passed": False, "detail": None}])

    assert rendered.count("[FAIL]") == 1, rendered


def test_the_human_layout_survives_the_marker(monkeypatch):
    """The em dash stays: this output is read by people between hook runs."""
    rendered = _rendered_results(monkeypatch, _MIXED_RESULTS)

    assert rendered.count("—") == 2, rendered
    assert "✓ cli" in rendered, rendered
    assert "3 functions outside handlers/" in rendered, rendered


def test_help_documents_the_marker(monkeypatch):
    """A signal scripts are meant to key on is only stable if it is published."""
    import io

    from rich.console import Console

    from aipass.seedgo.apps.modules import checklist

    buffer = io.StringIO()
    monkeypatch.setattr(checklist, "console", Console(file=buffer, force_terminal=False, width=300))
    checklist.print_help()

    assert "[FAIL]" in buffer.getvalue()


# ---------------------------------------------------------------------------
# Help-flag safety (help_flag_safety: a flag ANYWHERE explains)
# ---------------------------------------------------------------------------


def test_help_after_the_file_path_does_not_run_the_checklist(monkeypatch):
    """`drone @seedgo checklist <file> --help` ran a full per-file audit instead of describing one."""
    from aipass.seedgo.apps.modules import checklist

    run = MagicMock()
    monkeypatch.setattr(checklist, "run_checklist", run)
    monkeypatch.setattr(checklist, "_print_results", MagicMock())
    shown = MagicMock()
    monkeypatch.setattr(checklist, "print_help", shown)

    assert checklist.handle_command("checklist", ["apps/modules/checklist.py", "--help"]) is True
    assert run.call_count == 0
    assert shown.call_count == 1


def test_help_after_a_pack_flag_does_not_run_the_checklist(monkeypatch):
    """The flag can trail any operand — `checklist --pack aipass <file> -h` is still a question."""
    from aipass.seedgo.apps.modules import checklist

    run = MagicMock()
    monkeypatch.setattr(checklist, "run_checklist", run)
    monkeypatch.setattr(checklist, "_print_results", MagicMock())
    shown = MagicMock()
    monkeypatch.setattr(checklist, "print_help", shown)

    assert checklist.handle_command("checklist", ["--pack", "aipass", "apps/modules/checklist.py", "-h"]) is True
    assert run.call_count == 0
    assert shown.call_count == 1


def test_checklist_still_runs_without_a_help_flag(monkeypatch, tmp_path):
    """The gate must not swallow the real command."""
    from aipass.seedgo.apps.modules import checklist

    target = tmp_path / "thing.py"
    target.write_text("x = 1\n", encoding="utf-8")
    run = MagicMock(return_value=[])
    monkeypatch.setattr(checklist, "run_checklist", run)
    monkeypatch.setattr(checklist, "_print_results", MagicMock())
    monkeypatch.setattr(checklist, "print_help", MagicMock())

    assert checklist.handle_command("checklist", [str(target)]) is True
    assert run.call_count == 1


def test_checklist_does_not_answer_for_another_command(monkeypatch):
    """Ownership first: a help flag never makes a module claim a command it does not own."""
    from aipass.seedgo.apps.modules import checklist

    monkeypatch.setattr(checklist, "print_help", MagicMock())

    assert checklist.handle_command("audit", ["--help"]) is False
