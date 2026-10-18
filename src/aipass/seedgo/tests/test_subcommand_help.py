# =================== AIPass ====================
# Name: test_subcommand_help.py
# Description: Tests for subcommand_help_check.py
# Version: 1.1.2
# Created: 2026-07-10
# Modified: 2026-10-17
# =============================================

"""Tests for apps/handlers/aipass_standards/subcommand_help_check.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that subcommand_help_check.py parses and imports

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from aipass.seedgo.apps.handlers.aipass_standards import subcommand_help_check


@pytest.fixture(autouse=True)
def _mock_infrastructure(monkeypatch):
    """Silence the checker's logger and json_handler calls: real seams, no stub."""
    monkeypatch.setattr(subcommand_help_check, "logger", MagicMock())

    mock_json_handler = MagicMock()
    mock_json_handler.log_operation = MagicMock(return_value=True)
    monkeypatch.setattr(subcommand_help_check, "json_handler", mock_json_handler)


def _entry_file(tmp_path, source):
    """Create a file under an apps/ directory to pass entry-point check."""
    apps_dir = tmp_path / "apps"
    apps_dir.mkdir()
    f = apps_dir / "branch.py"
    f.write_text(source, encoding="utf-8")
    return str(f)


def test_non_entry_point_skipped(tmp_path):
    f = tmp_path / "handler.py"
    f.write_text("def main(): pass\n", encoding="utf-8")
    result = subcommand_help_check.check_module(str(f))
    assert result["passed"] is True
    assert result["score"] == 100


def test_missing_file(tmp_path):
    result = subcommand_help_check.check_module(str(tmp_path / "apps" / "branch.py"))
    assert result["passed"] is False
    assert result["score"] == 0


def test_no_entry_function(tmp_path):
    src = "def helper(): pass\n"
    f = _entry_file(tmp_path, src)
    result = subcommand_help_check.check_module(f)
    assert result["passed"] is True
    assert "skipped" in result["checks"][0]["message"]


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
    result = subcommand_help_check.check_module(f)
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
    result = subcommand_help_check.check_module(f)
    assert result["passed"] is False


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
    result = subcommand_help_check.check_module(f)
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
    result = subcommand_help_check.check_module(f)
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
    result = subcommand_help_check.check_module(f)
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
    result = subcommand_help_check.check_module(f)
    assert result["passed"] is True


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
    result = subcommand_help_check.check_module(f)
    assert result["passed"] is True
    assert "parse_known_args" in result["checks"][0]["message"]


def test_handle_command_function_detected(tmp_path):
    src = """\
def handle_command(command, args):
    if args and args[0] in ["--help", "-h"]:
        return False
    route_command(command, args, modules)
"""
    f = _entry_file(tmp_path, src)
    result = subcommand_help_check.check_module(f)
    assert result["passed"] is True


def test_bypassed_file_passes(tmp_path):
    src = "def main(): pass\n"
    f = _entry_file(tmp_path, src)
    bypass_rules = [{"file": f, "standard": "subcommand_help"}]
    result = subcommand_help_check.check_module(f, bypass_rules=bypass_rules)
    assert result["passed"] is True
    assert result["score"] == 100


def test_syntax_error_file(tmp_path):
    src = "def main(\n"
    f = _entry_file(tmp_path, src)
    result = subcommand_help_check.check_module(f)
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
    result = subcommand_help_check.check_module(f)
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
    result = subcommand_help_check.check_module(f)
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
    result = subcommand_help_check.check_module(f)
    assert result["passed"] is True


_AIPASS_ROOT = Path(__file__).resolve().parents[2]


def test_seedgo_entry_passes():
    """seedgo's own entry point carries the subcommand --help guard."""
    result = subcommand_help_check.check_module(str(_AIPASS_ROOT / "seedgo" / "apps" / "seedgo.py"))
    assert result["passed"] is True, f"seedgo should pass: {result['checks']}"


# Rule 2: per-verb help no caller can reach; the defect is in the chain, not at either end.


def _module_file(tmp_path, source, name="git_module.py"):
    """A file under apps/modules/ — where the real specimen lived."""
    mod_dir = tmp_path / "apps" / "modules"
    mod_dir.mkdir(parents=True)
    f = mod_dir / name
    f.write_text(source, encoding="utf-8")
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
    result = subcommand_help_check.check_module(f)
    assert result["passed"] is False
    assert result["score"] == 0
    failed = [c for c in result["checks"] if not c["passed"]]
    assert len(failed) == 1, f"only rule 2 should fail here: {result['checks']}"
    assert failed[0]["name"] == "Per-verb help reachable"
    assert "get_help()" in failed[0]["message"]
    assert "2 verbs" in failed[0]["message"]


def test_cure_clears_the_verdict(tmp_path):
    """The same module with the verb passed through clears: a checker that cannot tell cure from defect measures nothing."""
    f = _module_file(tmp_path, _CURED)
    result = subcommand_help_check.check_module(f)
    assert result["passed"] is True, f"cured module must clear: {result['checks']}"
    assert result["score"] == 100


def test_printer_with_no_verb_parameter_is_not_a_violation(tmp_path):
    """A printer handed no verb has no per-verb content to reach, so it is not a violation."""
    src = """\
def print_help():
    console.print("the whole page")


def handle_command(command=None, args=None):
    if wants_help(command, args):
        print_help()
        return 0
"""
    f = _module_file(tmp_path, src)
    assert subcommand_help_check.check_module(f)["passed"] is True


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
    assert subcommand_help_check.check_module(f)["passed"] is True


def test_helper_is_not_help(tmp_path):
    """'help' matches as a whole token, so `_local_helpers` is not a help provider."""
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
    assert subcommand_help_check.check_module(f)["passed"] is True


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
    assert subcommand_help_check.check_module(f)["passed"] is True


def test_provider_with_no_call_site_is_left_alone(tmp_path):
    """A provider whose callers live in another module is left alone: this lane cannot read them."""
    src = """\
def get_help(command=None):
    if command == "commit":
        return "git commit <msg>\\n"
    if command == "status":
        return "git status\\n"
    return "the whole page\\n"
"""
    f = _module_file(tmp_path, src)
    assert subcommand_help_check.check_module(f)["passed"] is True


def test_keyword_argument_counts_as_passing_the_verb(tmp_path):
    """`get_help(command=command)` reaches the per-verb branches too."""
    src = _STRANDED.replace("console.print(get_help())", "console.print(get_help(command=command))")
    f = _module_file(tmp_path, src)
    assert subcommand_help_check.check_module(f)["passed"] is True


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
    result = subcommand_help_check.check_module(f)
    assert result["passed"] is False
    assert "get_help()" in result["checks"][-1]["message"]


def test_non_entry_file_no_longer_blanket_passes(tmp_path):
    """A non-entry file is read, never blanket-passed at 100."""
    f = _module_file(tmp_path, _STRANDED)
    result = subcommand_help_check.check_module(f)
    skipped = [c for c in result["checks"] if "Not an entry point" in c["message"]]
    assert skipped, "rule 1 still stands down off the entry point"
    assert result["passed"] is False, "but rule 2 read the file anyway"


# Rule 2 over the branch lane.


def test_check_branch_finds_it_under_apps_modules(tmp_path):
    """check_branch finds a stranded provider under apps/modules/, a file the audit lane hands this checker."""
    branch = tmp_path / "drone"
    _module_file(branch, _STRANDED)
    result = subcommand_help_check.check_branch(str(branch))
    assert result["passed"] is False
    assert result["score"] == 0
    stranded = [c for c in result["checks"] if c["name"] == "Per-verb help reachable"]
    assert stranded and stranded[0]["passed"] is False
    assert "git_module.py" in stranded[0]["message"]


def test_check_branch_passes_a_clean_branch(tmp_path):
    branch = tmp_path / "drone"
    _module_file(branch, _CURED)
    result = subcommand_help_check.check_branch(str(branch))
    assert result["passed"] is True
    assert result["score"] == 100


def test_check_branch_ignores_test_trees(tmp_path):
    """APPLIES_TO = production. A fixture in tests/ is not a CLI."""
    branch = tmp_path / "drone"
    tests_dir = branch / "apps" / "tests"
    tests_dir.mkdir(parents=True)
    (tests_dir / "test_thing.py").write_text(_STRANDED, encoding="utf-8")
    assert subcommand_help_check.check_branch(str(branch))["passed"] is True


def test_collection_membership_is_per_verb_content(tmp_path):
    """`if command in ("commit", "status")` is a per-verb menu too: the collection arm is pinned."""
    src = """\
def get_help(command=None):
    if command in ("commit", "status"):
        return "one of the two\\n"
    return "the whole page\\n"


def print_help():
    console.print(get_help())
"""
    f = _module_file(tmp_path, src)
    result = subcommand_help_check.check_module(f)
    assert result["passed"] is False
    assert "2 verbs" in result["checks"][-1]["message"]


def test_literals_compared_against_another_name_are_not_verbs(tmp_path):
    """Literals compared against a name other than the parameter are not verbs, so an output-format branch holds no menu."""
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
    assert subcommand_help_check.check_module(f)["passed"] is True
