# =================== AIPass ====================
# Name: test_subcommand_help.py
# Description: Tests for subcommand_help_check.py
# Version: 1.0.0
# Created: 2026-07-10
# Modified: 2026-07-10
# =============================================

"""Tests for subcommand_help_check — subcommand --help guard detection."""

from pathlib import Path

import pytest
from unittest.mock import MagicMock


@pytest.fixture(autouse=True)
def _mock_infrastructure(monkeypatch):
    import sys

    mock_logger = MagicMock()
    mock_json_handler = MagicMock()
    mock_json_handler.log_operation = MagicMock(return_value=True)

    prax_mod = MagicMock()
    prax_mod.logger = mock_logger
    monkeypatch.setitem(sys.modules, "aipass.prax", prax_mod)

    json_pkg = MagicMock()
    json_pkg.json_handler = mock_json_handler
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.json", json_pkg)
    json_mod = MagicMock()
    json_mod.log_operation = mock_json_handler.log_operation
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.json.json_handler", json_mod)

    bypass_pkg = MagicMock()
    bypass_ignore = MagicMock()
    bypass_ignore.get_template_ignore_patterns = MagicMock(return_value=[])
    from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed as real_is_bypassed

    bypass_utils = MagicMock()
    bypass_utils.is_bypassed = real_is_bypassed
    bypass_pkg.utils = bypass_utils
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.bypass", bypass_pkg)
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.bypass.ignore_handler", bypass_ignore)
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.bypass.utils", bypass_utils)

    for mod_name in ["aipass.seedgo.apps.handlers.aipass_standards.subcommand_help_check"]:
        monkeypatch.delitem(sys.modules, mod_name, raising=False)


def _entry_file(tmp_path, source):
    """Create a file under an apps/ directory to pass entry-point check."""
    apps_dir = tmp_path / "apps"
    apps_dir.mkdir()
    f = apps_dir / "branch.py"
    f.write_text(source)
    return str(f)


# ============================================================
# Non-entry-point files — skipped
# ============================================================


def test_non_entry_point_skipped(tmp_path):
    f = tmp_path / "handler.py"
    f.write_text("def main(): pass\n")
    from aipass.seedgo.apps.handlers.aipass_standards.subcommand_help_check import check_module

    result = check_module(str(f))
    assert result["passed"] is True
    assert result["score"] == 100


def test_missing_file():
    from aipass.seedgo.apps.handlers.aipass_standards.subcommand_help_check import check_module

    result = check_module("/nonexistent/apps/branch.py")
    assert result["passed"] is False
    assert result["score"] == 0


def test_no_entry_function(tmp_path):
    src = "def helper(): pass\n"
    f = _entry_file(tmp_path, src)
    from aipass.seedgo.apps.handlers.aipass_standards.subcommand_help_check import check_module

    result = check_module(f)
    assert result["passed"] is True
    assert "skipped" in result["checks"][0]["message"]


# ============================================================
# MUST FAIL — top-level --help only, no subcommand guard
# ============================================================


def test_toplevel_only_fails(tmp_path):
    src = """\
import sys
def main():
    args = sys.argv[1:]
    if args[0] in ["--help", "-h"]:
        print_help()
        return 0
    command = args[0]
    remaining = args[1:]
    route_command(command, remaining, modules)
"""
    f = _entry_file(tmp_path, src)
    from aipass.seedgo.apps.handlers.aipass_standards.subcommand_help_check import check_module

    result = check_module(f)
    assert result["passed"] is False
    assert result["score"] == 0
    assert "No subcommand --help guard" in result["checks"][0]["message"]


def test_no_help_at_all_fails(tmp_path):
    src = """\
import sys
def main():
    args = sys.argv[1:]
    command = args[0]
    remaining = args[1:]
    route_command(command, remaining, modules)
"""
    f = _entry_file(tmp_path, src)
    from aipass.seedgo.apps.handlers.aipass_standards.subcommand_help_check import check_module

    result = check_module(f)
    assert result["passed"] is False


# ============================================================
# MUST PASS — explicit subcommand --help guard
# ============================================================


def test_remaining_subscript_guard_passes(tmp_path):
    src = """\
import sys
def main():
    args = sys.argv[1:]
    if args[0] in ["--help", "-h"]:
        print_help()
        return 0
    command = args[0]
    remaining = args[1:]
    if remaining and remaining[0] in ["--help", "-h"]:
        show_subcommand_help(command)
        return 0
    route_command(command, remaining, modules)
"""
    f = _entry_file(tmp_path, src)
    from aipass.seedgo.apps.handlers.aipass_standards.subcommand_help_check import check_module

    result = check_module(f)
    assert result["passed"] is True
    assert result["score"] == 100


def test_remaining_args_variable_passes(tmp_path):
    src = """\
import sys
def main():
    args = sys.argv[1:]
    if args[0] in ["--help", "-h"]:
        print_help()
        return 0
    command = args[0]
    remaining_args = args[1:]
    if remaining_args and remaining_args[0] in ["--help", "-h"]:
        show_subcommand_help(command)
        return 0
    route_command(command, remaining_args, modules)
"""
    f = _entry_file(tmp_path, src)
    from aipass.seedgo.apps.handlers.aipass_standards.subcommand_help_check import check_module

    result = check_module(f)
    assert result["passed"] is True


def test_help_in_remaining_passes(tmp_path):
    src = """\
import sys
def main():
    args = sys.argv[1:]
    command = args[0]
    remaining = args[1:]
    if "--help" in remaining:
        show_help(command)
        return 0
    route_command(command, remaining, modules)
"""
    f = _entry_file(tmp_path, src)
    from aipass.seedgo.apps.handlers.aipass_standards.subcommand_help_check import check_module

    result = check_module(f)
    assert result["passed"] is True


def test_post_dispatch_fallback_passes(tmp_path):
    src = """\
import sys
def main():
    args = sys.argv[1:]
    if args[0] in ["--help", "-h"]:
        print_help()
        return 0
    command = args[0]
    remaining_args = args[1:]
    if route_command(command, remaining_args, modules):
        return 0
    if remaining_args and remaining_args[0] in ["--help", "-h"]:
        print_module_help(command, modules)
        return 0
"""
    f = _entry_file(tmp_path, src)
    from aipass.seedgo.apps.handlers.aipass_standards.subcommand_help_check import check_module

    result = check_module(f)
    assert result["passed"] is True


# ============================================================
# MUST PASS — argparse pattern
# ============================================================


def test_argparse_parse_known_args_passes(tmp_path):
    src = """\
import argparse
def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("command", nargs="?")
    parser.add_argument("--help", "-h", action="store_true", dest="show_help")
    parsed_args, remaining = parser.parse_known_args()
    if parsed_args.show_help:
        all_args = ["--help"] + remaining
    route_command(parsed_args.command, all_args, handlers)
"""
    f = _entry_file(tmp_path, src)
    from aipass.seedgo.apps.handlers.aipass_standards.subcommand_help_check import check_module

    result = check_module(f)
    assert result["passed"] is True
    assert "parse_known_args" in result["checks"][0]["message"]


# ============================================================
# MUST PASS — handle_command function
# ============================================================


def test_handle_command_function_detected(tmp_path):
    src = """\
def handle_command(command, args):
    if args and args[0] in ["--help", "-h"]:
        return False
    route_command(command, args, modules)
"""
    f = _entry_file(tmp_path, src)
    from aipass.seedgo.apps.handlers.aipass_standards.subcommand_help_check import check_module

    result = check_module(f)
    assert result["passed"] is True


# ============================================================
# MUST PASS — bypass
# ============================================================


def test_bypassed_file_passes(tmp_path):
    src = "def main(): pass\n"
    f = _entry_file(tmp_path, src)
    from aipass.seedgo.apps.handlers.aipass_standards.subcommand_help_check import check_module

    bypass_rules = [{"file": f, "standard": "subcommand_help"}]
    result = check_module(f, bypass_rules=bypass_rules)
    assert result["passed"] is True
    assert result["score"] == 100


# ============================================================
# Edge cases
# ============================================================


def test_syntax_error_file(tmp_path):
    src = "def main(\n"
    f = _entry_file(tmp_path, src)
    from aipass.seedgo.apps.handlers.aipass_standards.subcommand_help_check import check_module

    result = check_module(f)
    assert result["passed"] is False
    assert "Syntax error" in result["checks"][0]["message"]


def test_rest_variable_passes(tmp_path):
    src = """\
import sys
def main():
    args = sys.argv[1:]
    command = args[0]
    rest = args[1:]
    if rest and rest[0] in ["--help", "-h"]:
        show_help(command)
        return 0
    route_command(command, rest, modules)
"""
    f = _entry_file(tmp_path, src)
    from aipass.seedgo.apps.handlers.aipass_standards.subcommand_help_check import check_module

    result = check_module(f)
    assert result["passed"] is True


def test_cmd_args_variable_passes(tmp_path):
    src = """\
import sys
def main():
    args = sys.argv[1:]
    command = args[0]
    cmd_args = args[1:]
    if cmd_args and cmd_args[0] in ["--help", "-h"]:
        show_help(command)
        return 0
    route_command(command, cmd_args, modules)
"""
    f = _entry_file(tmp_path, src)
    from aipass.seedgo.apps.handlers.aipass_standards.subcommand_help_check import check_module

    result = check_module(f)
    assert result["passed"] is True


def test_name_eq_help_passes(tmp_path):
    src = """\
def main():
    command = args[0]
    remaining = args[1:]
    flag = remaining[0]
    if flag == "--help":
        show_help(command)
        return 0
"""
    f = _entry_file(tmp_path, src)
    from aipass.seedgo.apps.handlers.aipass_standards.subcommand_help_check import check_module

    result = check_module(f)
    assert result["passed"] is True


# ============================================================
# Fleet fixtures — real entry points
# ============================================================

_AIPASS_ROOT = Path(__file__).resolve().parents[2]


def test_commons_entry_passes():
    from aipass.seedgo.apps.handlers.aipass_standards.subcommand_help_check import check_module

    result = check_module(str(_AIPASS_ROOT / "commons" / "apps" / "commons.py"))
    assert result["passed"] is True, f"commons should pass: {result['checks']}"


def test_prax_entry_passes():
    from aipass.seedgo.apps.handlers.aipass_standards.subcommand_help_check import check_module

    result = check_module(str(_AIPASS_ROOT / "prax" / "apps" / "prax.py"))
    assert result["passed"] is True, f"prax should pass: {result['checks']}"


def test_flow_entry_passes():
    from aipass.seedgo.apps.handlers.aipass_standards.subcommand_help_check import check_module

    result = check_module(str(_AIPASS_ROOT / "flow" / "apps" / "flow.py"))
    assert result["passed"] is True, f"flow should pass: {result['checks']}"


def test_seedgo_entry_passes():
    from aipass.seedgo.apps.handlers.aipass_standards.subcommand_help_check import check_module

    result = check_module(str(_AIPASS_ROOT / "seedgo" / "apps" / "seedgo.py"))
    assert result["passed"] is True, f"seedgo should pass: {result['checks']}"


def test_ai_mail_entry_passes():
    from aipass.seedgo.apps.handlers.aipass_standards.subcommand_help_check import check_module

    result = check_module(str(_AIPASS_ROOT / "ai_mail" / "apps" / "ai_mail.py"))
    assert result["passed"] is True, f"ai_mail should pass: {result['checks']}"


# ============================================================
# RULE 2 — per-verb help that no caller can reach (drone fc032265)
#
# Rule 1 scored drone 100 for months while every `drone @git VERB
# --help` returned the top-level index. These rows pin the shape that
# was invisible: the defect is in the chain, not at either end.
# ============================================================


def _module_file(tmp_path, source, name="git_module.py"):
    """A file under apps/modules/ — where the real specimen lived."""
    mod_dir = tmp_path / "apps" / "modules"
    mod_dir.mkdir(parents=True)
    f = mod_dir / name
    f.write_text(source)
    return str(f)


_STRANDED = """\
def get_help(command=None):
    if command == "commit":
        return "git commit <msg>\\n"
    if command == "status":
        return "git status\\n"
    return "the whole page\\n"


def print_help():
    console.print(get_help())


def handle_command(command=None, args=None):
    if wants_help(command, args):
        print_help()
        return 0
"""

_CURED = _STRANDED.replace("def print_help():", "def print_help(command=None):").replace(
    "console.print(get_help())", "console.print(get_help(command))"
)


def test_stranded_per_verb_help_convicts(tmp_path):
    """The specimen: 2 verbs behind `command`, and the only call omits it."""
    f = _module_file(tmp_path, _STRANDED)
    from aipass.seedgo.apps.handlers.aipass_standards.subcommand_help_check import check_module

    result = check_module(f)
    assert result["passed"] is False
    assert result["score"] == 0
    failed = [c for c in result["checks"] if not c["passed"]]
    assert len(failed) == 1, f"only rule 2 should fail here: {result['checks']}"
    assert failed[0]["name"] == "Per-verb help reachable"
    assert "get_help()" in failed[0]["message"]
    assert "2 verbs" in failed[0]["message"]


def test_cure_clears_the_verdict(tmp_path):
    """The same module with the verb passed through. A checker that cannot
    tell the cure from the defect measures nothing."""
    f = _module_file(tmp_path, _CURED)
    from aipass.seedgo.apps.handlers.aipass_standards.subcommand_help_check import check_module

    result = check_module(f)
    assert result["passed"] is True, f"cured module must clear: {result['checks']}"
    assert result["score"] == 100


def test_printer_with_no_verb_parameter_is_not_a_violation(tmp_path):
    """125 of the fleet's 129 help dispatch sites hand their printer
    nothing. With no per-verb content to reach, that is the right answer."""
    src = """\
def print_help():
    console.print("the whole page")


def handle_command(command=None, args=None):
    if wants_help(command, args):
        print_help()
        return 0
"""
    f = _module_file(tmp_path, src)
    from aipass.seedgo.apps.handlers.aipass_standards.subcommand_help_check import check_module

    assert check_module(f)["passed"] is True


def test_single_literal_is_not_per_verb_content(tmp_path):
    """One comparison is a guard or an alias, not a menu. _MIN_VERB_LITERALS."""
    src = """\
def get_help(command=None):
    if command == "commit":
        return "git commit <msg>\\n"
    return "the whole page\\n"


def print_help():
    console.print(get_help())
"""
    f = _module_file(tmp_path, src)
    from aipass.seedgo.apps.handlers.aipass_standards.subcommand_help_check import check_module

    assert check_module(f)["passed"] is True


def test_helper_is_not_help(tmp_path):
    """'help' must match as a whole token. An early cut read every
    `_local_helpers` in the tree and its precision was an accident."""
    src = """\
def _local_helpers(kind=None):
    if kind == "alpha":
        return "a"
    if kind == "beta":
        return "b"
    return "z"


def run():
    return _local_helpers()
"""
    f = _module_file(tmp_path, src)
    from aipass.seedgo.apps.handlers.aipass_standards.subcommand_help_check import check_module

    assert check_module(f)["passed"] is True


def test_help_predicate_is_not_a_provider(tmp_path):
    """A predicate hands back a bool; only a provider has text to strand."""
    src = """\
def is_help_flag(token=None):
    if token == "--help":
        return True
    if token == "-h":
        return True
    return False


def run():
    return is_help_flag()
"""
    f = _module_file(tmp_path, src)
    from aipass.seedgo.apps.handlers.aipass_standards.subcommand_help_check import check_module

    assert check_module(f)["passed"] is True


def test_provider_with_no_call_site_is_left_alone(tmp_path):
    """Its callers live in another module. This lane cannot read them, so
    it says nothing rather than guessing either way."""
    src = """\
def get_help(command=None):
    if command == "commit":
        return "git commit <msg>\\n"
    if command == "status":
        return "git status\\n"
    return "the whole page\\n"
"""
    f = _module_file(tmp_path, src)
    from aipass.seedgo.apps.handlers.aipass_standards.subcommand_help_check import check_module

    assert check_module(f)["passed"] is True


def test_keyword_argument_counts_as_passing_the_verb(tmp_path):
    """`get_help(command=command)` reaches the per-verb branches too."""
    src = _STRANDED.replace("console.print(get_help())", "console.print(get_help(command=command))")
    f = _module_file(tmp_path, src)
    from aipass.seedgo.apps.handlers.aipass_standards.subcommand_help_check import check_module

    assert check_module(f)["passed"] is True


def test_dict_keyed_per_verb_help_convicts(tmp_path):
    """Per-verb content reached by dict lookup is the same species."""
    src = """\
def get_help(command=None):
    pages = {"commit": "git commit\\n", "status": "git status\\n"}
    if command:
        return pages[command]
    return "the whole page\\n"


def print_help():
    console.print(get_help())
"""
    f = _module_file(tmp_path, src)
    from aipass.seedgo.apps.handlers.aipass_standards.subcommand_help_check import check_module

    result = check_module(f)
    assert result["passed"] is False
    assert "get_help()" in result["checks"][-1]["message"]


def test_non_entry_file_no_longer_blanket_passes(tmp_path):
    """The old checker returned 100 for every non-entry file without
    reading it. That blanket pass is how drone scored 100."""
    f = _module_file(tmp_path, _STRANDED)
    from aipass.seedgo.apps.handlers.aipass_standards.subcommand_help_check import check_module

    result = check_module(f)
    skipped = [c for c in result["checks"] if "Not an entry point" in c["message"]]
    assert skipped, "rule 1 still stands down off the entry point"
    assert result["passed"] is False, "but rule 2 read the file anyway"


# ============================================================
# RULE 2 — the branch lane (the corpus rule 1 never had)
# ============================================================


def test_check_branch_finds_it_under_apps_modules(tmp_path):
    """The real specimen lived in apps/modules/git_module.py, a file the
    audit lane never handed this checker."""
    branch = tmp_path / "drone"
    _module_file(branch, _STRANDED)
    from aipass.seedgo.apps.handlers.aipass_standards.subcommand_help_check import check_branch

    result = check_branch(str(branch))
    assert result["passed"] is False
    assert result["score"] == 0
    stranded = [c for c in result["checks"] if c["name"] == "Per-verb help reachable"]
    assert stranded and stranded[0]["passed"] is False
    assert "git_module.py" in stranded[0]["message"]


def test_check_branch_passes_a_clean_branch(tmp_path):
    branch = tmp_path / "drone"
    _module_file(branch, _CURED)
    from aipass.seedgo.apps.handlers.aipass_standards.subcommand_help_check import check_branch

    result = check_branch(str(branch))
    assert result["passed"] is True
    assert result["score"] == 100


def test_check_branch_ignores_test_trees(tmp_path):
    """APPLIES_TO = production. A fixture in tests/ is not a CLI."""
    branch = tmp_path / "drone"
    tests_dir = branch / "apps" / "tests"
    tests_dir.mkdir(parents=True)
    (tests_dir / "test_thing.py").write_text(_STRANDED)
    from aipass.seedgo.apps.handlers.aipass_standards.subcommand_help_check import check_branch

    assert check_branch(str(branch))["passed"] is True


def test_collection_membership_is_per_verb_content(tmp_path):
    """`if command in ("commit", "status")` is a menu too. A mutant that
    dropped the collection arm survived until this row existed."""
    src = """\
def get_help(command=None):
    if command in ("commit", "status"):
        return "one of the two\\n"
    return "the whole page\\n"


def print_help():
    console.print(get_help())
"""
    f = _module_file(tmp_path, src)
    from aipass.seedgo.apps.handlers.aipass_standards.subcommand_help_check import check_module

    result = check_module(f)
    assert result["passed"] is False
    assert "2 verbs" in result["checks"][-1]["message"]


def test_literals_compared_against_another_name_are_not_verbs(tmp_path):
    """The comparison has to be against the PARAMETER. A provider that
    branches on an output format holds no per-verb help, and convicting it
    would be the rule reading any two string literals as a menu."""
    src = """\
def get_help(command=None):
    fmt = "json"
    if fmt == "json":
        return "{}\\n"
    if fmt == "text":
        return "the whole page\\n"
    return "the whole page\\n"


def print_help():
    console.print(get_help())
"""
    f = _module_file(tmp_path, src)
    from aipass.seedgo.apps.handlers.aipass_standards.subcommand_help_check import check_module

    assert check_module(f)["passed"] is True
