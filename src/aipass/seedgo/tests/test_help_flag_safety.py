# =================== AIPass ====================
# Name: test_help_flag_safety.py
# Description: Tests for help_flag_safety_check.py
# Version: 1.0.3
# Created: 2026-08-13
# Modified: 2026-10-24
# =============================================

"""Tests for apps/handlers/aipass_standards/help_flag_safety_check.py."""

# A help flag ANYWHERE must explain, never execute.
# Real-world cases are pinned as inline SHAPES, never read from live fleet files: a test asserting
# "branch X is still broken" goes red when X is fixed. Fleet state is a measurement, never an assertion.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(constant) — APPLIES_TO and AUDIT_SCOPE, the scope the audit reads
# seedgo: no-test-needed(stdlib) — ast.parse's parsing; the product only walks the tree it returns
# seedgo: no-test-needed(standard) — the check_completed record json_handler.log_operation writes

from pathlib import Path

import pytest
from unittest.mock import MagicMock

from aipass.seedgo.apps.handlers.aipass_standards import help_flag_safety_check
from aipass.seedgo.apps.handlers.aipass_standards.help_flag_safety_check import check_module

FLEET = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _mock_infrastructure(monkeypatch):
    """Mock heavy infrastructure the checker reads, at the seam it reads it from.

    ``is_bypassed`` stays real: with no rules it returns ``None`` before touching a filesystem.
    """
    monkeypatch.setattr(help_flag_safety_check, "logger", MagicMock())
    monkeypatch.setattr(help_flag_safety_check, "json_handler", MagicMock(log_operation=MagicMock(return_value=True)))


def _check(path):
    return check_module(str(path))


def _branch(tmp_path, module_src, entry_src=None):
    """Build a fake branch: apps/branch.py + apps/modules/thing.py."""
    apps = tmp_path / "apps"
    modules = apps / "modules"
    modules.mkdir(parents=True)
    (apps / "branch.py").write_text(entry_src or "def main():\n    pass\n", encoding="utf-8")
    mod = modules / "thing.py"
    mod.write_text(module_src, encoding="utf-8")
    return mod


def _fleet_file(rel):
    p = FLEET / rel
    if not p.exists():
        pytest.skip(f"fleet file absent: {rel}")
    return p


VULNERABLE = """\
def handle_command(command, args):
    if not args:
        print_introspection()
        return True
    if args[0] in ("--help", "-h", "help"):
        print_help()
        return True
    target = args[0]
    run_the_thing(target, args[1:])
    return True
"""


def test_catches_args0_only_gate():
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        mod = _branch(Path(td), VULNERABLE)
        result = _check(mod)
    assert result["passed"] is False
    assert result["score"] == 0
    assert result["standard"] == "HELP_FLAG_SAFETY"
    msg = result["checks"][0]["message"]
    assert "args[0]" in msg
    assert "handle_command" in msg


def test_catches_equality_gate(tmp_path):
    src = """\
def handle_command(command, args):
    if args[0] == "--help":
        print_help()
        return True
    name = args[0]
    create(name, args[1])
    return True
"""
    result = _check(_branch(tmp_path, src))
    assert result["passed"] is False
    assert result["score"] == 0


def test_catches_gate_on_renamed_sequence(tmp_path):
    src = """\
def handle_command(command, remaining):
    if remaining and remaining[0] in ["--help", "-h"]:
        print_help()
        return True
    do_work(remaining)
    return True
"""
    result = _check(_branch(tmp_path, src))
    assert result["passed"] is False
    assert "remaining[0]" in result["checks"][0]["message"]


def test_catches_gate_inside_private_delegate(tmp_path):
    src = """\
def handle_command(command, args):
    return _route(args)


def _route(args):
    if args[0] in ("--help", "-h"):
        print_help()
        return True
    target = args[0]
    run(target, args[1:])
    return True
"""
    result = _check(_branch(tmp_path, src))
    assert result["passed"] is False
    assert "_route" in result["checks"][0]["message"]


def test_names_the_value_slot_when_flag_becomes_data(tmp_path):
    src = """\
def handle_command(command, args):
    if args[0] in ("--help", "-h"):
        print_help()
        return True
    if command == "add":
        name = args[0]
        target = args[1]
        register(name, target)
    return True
"""
    result = _check(_branch(tmp_path, src))
    assert result["passed"] is False
    detail = " ".join(c["message"] for c in result["checks"])
    assert "value slot" in detail


def test_passes_membership_scan(tmp_path):
    src = """\
def handle_command(command, args):
    if "--help" in args:
        print_help()
        return True
    target = args[0]
    run(target, args[1:])
    return True
"""
    result = _check(_branch(tmp_path, src))
    assert result["passed"] is True
    assert result["score"] == 100


def test_passes_any_comprehension_scan(tmp_path):
    src = """\
def handle_command(command, args):
    if args and args[0] in ("--help", "-h", "help"):
        print_help()
        return True
    if any(a in ("--help", "-h") for a in args):
        print_help()
        return True
    target = args[0]
    run(target, args[1:])
    return True
"""
    result = _check(_branch(tmp_path, src))
    assert result["passed"] is True


def test_passes_helper_function_scan(tmp_path):
    src = """\
from aipass.memory.apps.handlers.cli.help_flags import wants_help


def handle_command(command, args):
    if wants_help(args, allow_bare_word=True):
        print_help()
        return True
    target = args[0]
    run(target, args[1:])
    return True
"""
    result = _check(_branch(tmp_path, src))
    assert result["passed"] is True


def test_passes_loop_scan(tmp_path):
    src = """\
def handle_command(command, args):
    for token in args:
        if token in ("--help", "-h"):
            print_help()
            return True
    target = args[0]
    run(target, args[1:])
    return True
"""
    result = _check(_branch(tmp_path, src))
    assert result["passed"] is True


def test_passes_argparse_known_args(tmp_path):
    src = """\
import argparse


def handle_command(command, args):
    parser = argparse.ArgumentParser()
    parsed, rest = parser.parse_known_args(args)
    if args[0] in ("--help", "-h"):
        print_help()
        return True
    run(parsed, rest)
    return True
"""
    result = _check(_branch(tmp_path, src))
    assert result["passed"] is True


NORMALISING_ENTRY = """\
import sys


def main():
    args = sys.argv[1:]
    if args[0] in ("--help", "-h", "help"):
        print_help()
        return 0
    command = args[0]
    remaining = args[1:]
    if any(arg in ("--help", "-h") for arg in remaining):
        for module in modules:
            if module.handle_command(command, ["--help"]):
                return 0
        print_help()
        return 0
    return route_command(command, remaining, modules)
"""


def test_passes_when_router_normalises(tmp_path):
    result = _check(_branch(tmp_path, VULNERABLE, entry_src=NORMALISING_ENTRY))
    assert result["passed"] is True
    assert result["score"] == 100
    assert "router" in result["checks"][0]["message"].lower()


def test_fails_when_router_only_checks_position_zero(tmp_path):
    entry = """\
import sys


def main():
    args = sys.argv[1:]
    if args[0] in ("--help", "-h", "help"):
        print_help()
        return 0
    command = args[0]
    remaining = args[1:]
    if remaining and remaining[0] in ("--help", "-h"):
        remaining = ["--help"]
    return route_command(command, remaining, modules)
"""
    result = _check(_branch(tmp_path, VULNERABLE, entry_src=entry))
    assert result["passed"] is False


def test_passes_dispatch_only_command(tmp_path):
    src = """\
def handle_command(command, args):
    if args and args[0] in ("--help", "-h", "help"):
        print_help()
        return True
    if command == "start":
        return _start()
    if command == "status":
        return _status()
    return False
"""
    result = _check(_branch(tmp_path, src))
    assert result["passed"] is True


def test_passes_when_args_only_reach_a_log_sink(tmp_path):
    src = """\
def handle_command(command, args):
    if not args:
        print_introspection()
        return True
    if args[0] in ("--help", "-h", "help"):
        print_introspection()
        return True
    logger.warning("unknown subcommand '%s'", args[0])
    print_introspection()
    return True
"""
    result = _check(_branch(tmp_path, src))
    assert result["passed"] is True


def test_entry_point_not_scored(tmp_path):
    apps = tmp_path / "apps"
    apps.mkdir()
    f = apps / "branch.py"
    f.write_text(
        "import sys\n\n\ndef main():\n"
        '    args = sys.argv[1:]\n    if args[0] in ("--help", "-h"):\n'
        "        print_help()\n        return 0\n    return route_command(args[0], args[1:], modules)\n",
        encoding="utf-8",
    )
    result = _check(f)
    assert result["passed"] is True
    assert result["score"] == 100


def test_handler_file_not_scored(tmp_path):
    handlers = tmp_path / "apps" / "handlers" / "thing"
    handlers.mkdir(parents=True)
    f = handlers / "ops.py"
    f.write_text(VULNERABLE, encoding="utf-8")
    result = _check(f)
    assert result["passed"] is True
    assert result["score"] == 100


def test_module_without_handle_command_skipped(tmp_path):
    result = _check(_branch(tmp_path, "def helper():\n    return 1\n"))
    assert result["passed"] is True


def test_init_file_skipped(tmp_path):
    apps = tmp_path / "apps" / "modules"
    apps.mkdir(parents=True)
    f = apps / "__init__.py"
    f.write_text(VULNERABLE, encoding="utf-8")
    result = _check(f)
    assert result["passed"] is True


def test_result_shape(tmp_path):
    result = _check(_branch(tmp_path, VULNERABLE))
    assert set(result) >= {"passed", "checks", "score", "standard"}
    assert isinstance(result["checks"], list)
    assert all({"name", "passed", "message"} <= set(c) for c in result["checks"])


def test_missing_file(tmp_path):
    result = _check(tmp_path / "apps" / "modules" / "thing.py")
    assert result["passed"] is False
    assert result["score"] == 0


def test_syntax_error_file(tmp_path):
    result = _check(_branch(tmp_path, "def handle_command(:\n"))
    assert result["passed"] is False
    assert result["score"] == 0


def test_empty_file(tmp_path):
    result = _check(_branch(tmp_path, ""))
    assert result["passed"] is True


def test_bypass_respected(tmp_path):
    mod = _branch(tmp_path, VULNERABLE)
    rules = [{"file": "apps/modules/thing.py", "standard": "help_flag_safety"}]
    result = check_module(str(mod), bypass_rules=rules)
    assert result["passed"] is True
    assert result["score"] == 100


_ROUTER_NORMALISES = (
    "def main(argv):\n"
    "    cmd, *remaining = argv\n"
    "    if any(a in ('--help', '-h') for a in remaining):\n"
    "        return handle_command(cmd, ['--help'])\n"
    "    return handle_command(cmd, remaining)\n"
)

_SAFE_SHAPES = {
    # memory/apps/modules/rollover.py — delegated whole-sequence predicate
    "delegated_predicate": (
        "from aipass.memory.apps.handlers.cli.help_flags import wants_help\n\n"
        "def handle_command(command, args):\n"
        "    if wants_help(args):\n"
        "        print_help()\n"
        "        return True\n"
        "    push(args[0], args[1])\n"
        "    return True\n"
    ),
    # skills/apps/modules/loader.py — inline whole-sequence scan
    "whole_sequence_scan": (
        "def handle_command(command, args):\n"
        "    if any(a in ('--help', '-h') for a in args):\n"
        "        print_help()\n"
        "        return True\n"
        "    load(args[0])\n"
        "    return True\n"
    ),
    # seedgo/apps/modules/diagnostics_audit.py — positional gate; past it is only an error message.
    "gate_then_error_output_only": (
        "def handle_command(command, args):\n"
        "    if command not in ('diagnostics', 'diagnostics_audit'):\n"
        "        return False\n"
        "    if args and args[0] in ('--help', '-h', 'help'):\n"
        "        print_help()\n"
        "        return True\n"
        "    if not args:\n"
        "        print_introspection()\n"
        "        return True\n"
        "    error(f\"Unknown argument: '{args[0]}'\")\n"
        "    warning('This module has no subcommands.')\n"
        "    console.print('Diagnostics runs through the audit pipeline.')\n"
        "    return True\n"
    ),
    # cli/apps/modules/display.py — dispatches on `command`, never reads args; past it only SHOWS text.
    "command_dispatch_display_only": (
        "def handle_command(command, args):\n"
        "    if command not in ('display', 'show'):\n"
        "        return False\n"
        "    if command == 'show':\n"
        "        console.print('nothing to show')\n"
        "        return True\n"
        "    error('unknown display command')\n"
        "    return False\n"
    ),
    # Dispatches on `command` and reaches a work call, but a whole-list scan answers the question first.
    "command_dispatch_but_scans_the_command_line": (
        "import sys\n\n"
        "def handle_command(command, args):\n"
        "    if '--help' in sys.argv:\n"
        "        print_help()\n"
        "        return True\n"
        "    if command == 'demo':\n"
        "        run_demo()\n"
        "        return True\n"
        "    return False\n"
    ),
    # seedgo/apps/modules/permissions.py — positional gate, then `return False`: nothing past it runs.
    "gate_then_declines": (
        "def handle_command(command, args):\n"
        "    if command != 'permissions':\n"
        "        return False\n"
        "    if not args:\n"
        "        print_introspection()\n"
        "        return True\n"
        "    if args[0] in ('--help', '-h', 'help'):\n"
        "        print_introspection()\n"
        "        return True\n"
        "    return False\n"
    ),
}

_DEFECTIVE_SHAPES = {
    # flow/apps/modules/create_plan.py — `<loc> <subject> --help` creates a real plan
    "positional_gate_then_consumes": (
        "def handle_command(command, args):\n"
        "    if args[0] in ['--help', '-h', 'help']:\n"
        "        print_help()\n"
        "        return True\n"
        "    create_plan(args[0], args[1])\n"
        "    return True\n"
    ),
    # drone/apps/modules/commands.py — `commands add <n> <t> --help` registers "--help"
    "command_or_first_arg_only": (
        "def handle_command(command, args):\n"
        "    if command in ('--help', '-h') or (args and args[0] in ('--help', '-h')):\n"
        "        print_help()\n"
        "        return True\n"
        "    name = args[0]\n"
        "    target = args[1]\n"
        "    body = args[2]\n"
        "    register(name, target, body)\n"
        "    return True\n"
    ),
    # api/apps/modules/api_key.py — `get-key <provider> --help` printed a real key
    "guarded_first_arg_then_routes": (
        "def handle_command(command, args):\n"
        "    if args and args[0] in ('--help', '-h', 'help'):\n"
        "        print_help()\n"
        "        return True\n"
        "    if command == 'get-key':\n"
        "        get_key(args)\n"
        "    return True\n"
    ),
    # hooks/apps/modules/hook_test.py — `test --verbose --help` fires every hook
    "gate_then_flag_scan_for_data": (
        "def handle_command(command, args):\n"
        "    if args[0] in ('--help', '-h'):\n"
        "        print_help()\n"
        "        return True\n"
        "    verbose = '--verbose' in args\n"
        "    run_test(verbose)\n"
        "    return True\n"
    ),
    # seedgo/apps/modules/inbox_audit.py — `audit inbox-ids --help` runs a repo-wide rglob: args[0] is
    # only COMPARED, never bound, so the flag lands at args[1] where no value-slot probe looks.
    "positional_subcommand_then_work_call": (
        "def handle_command(command, args):\n"
        "    if command == 'inbox_audit':\n"
        "        if not args:\n"
        "            print_introspection()\n"
        "            return True\n"
        "        if args[0] in ('--help', '-h', 'help'):\n"
        "            print_introspection()\n"
        "            return True\n"
        "    if command not in ('audit', 'standards_audit'):\n"
        "        return False\n"
        "    if not args or args[0] != 'inbox-ids':\n"
        "        return False\n"
        "    _run_inbox_id_scan()\n"
        "    return True\n"
    ),
    # cli/apps/modules/display.py — no gate anywhere: the verb is in the COMMAND slot and args is never read.
    "command_dispatch_never_reads_args": (
        "def handle_command(command, args):\n"
        "    if command == 'demo':\n"
        "        run_demo()\n"
        "        return True\n"
        "    return False\n"
    ),
    # flow/apps/modules/registry_monitor.py — `registry scan --help` reached scan_plan_files(), which WRITES.
    "conditional_subcommand_then_mutating_call": (
        "def handle_command(command, args):\n"
        "    if command != 'registry':\n"
        "        return False\n"
        "    if not args:\n"
        "        print_introspection()\n"
        "        return True\n"
        "    if args[0] in ('--help', '-h', 'help'):\n"
        "        print_help()\n"
        "        return True\n"
        "    subcommand = args[0] if args else 'status'\n"
        "    json_handler.log_operation('registry_monitor', {'subcommand': subcommand})\n"
        "    if subcommand in ('scan', 'heal'):\n"
        "        result = scan_plan_files()\n"
        "        console.print(result)\n"
        "    return True\n"
    ),
}


@pytest.mark.parametrize("shape", sorted(_SAFE_SHAPES))
def test_safe_shapes_pass(tmp_path, shape):
    result = _check(_branch(tmp_path, _SAFE_SHAPES[shape]))
    assert result["passed"] is True, result["checks"]
    assert result["score"] == 100


def test_router_normalised_module_passes(tmp_path):
    """backup/aipass/daemon shape: the module is positional-only but unreachable with a stray flag."""
    result = _check(_branch(tmp_path, _DEFECTIVE_SHAPES["positional_gate_then_consumes"], _ROUTER_NORMALISES))
    assert result["passed"] is True, result["checks"]


@pytest.mark.parametrize("shape", sorted(_DEFECTIVE_SHAPES))
def test_defective_shapes_fail(tmp_path, shape):
    result = _check(_branch(tmp_path, _DEFECTIVE_SHAPES[shape]))
    assert result["passed"] is False, result["checks"]
    assert result["score"] == 0


def test_seedgo_is_in_scope_for_its_own_standard():
    """seedgo is not exempt from the standard it owns."""
    modules = FLEET / "seedgo" / "apps" / "modules"
    if not modules.is_dir():
        pytest.skip("fleet file absent: seedgo/apps/modules")
    candidates = [p for p in sorted(modules.glob("*.py")) if p.name != "__init__.py"]
    routing = [p.name for p in candidates if "def handle_command" in p.read_text(encoding="utf-8")]
    scored = [p.name for p in candidates if "not applicable" not in _check(p)["checks"][0]["message"]]
    assert scored == routing, "every seedgo routing module must be scored by seedgo's own standard"


# A work call executing at all is the harm, not only an un-scanned tail flowing into a VALUE SLOT:
# the value-slot rule alone missed more modules than it caught.


def test_names_the_executing_call_when_there_is_no_value_slot(tmp_path):
    """inbox_audit shape: the message must name the call that runs, and its line."""
    result = _check(_branch(tmp_path, _DEFECTIVE_SHAPES["positional_subcommand_then_work_call"]))
    assert result["passed"] is False, result["checks"]
    msg = result["checks"][0]["message"]
    assert "handle_command" in msg
    assert "args[0]" in msg
    assert "inbox-ids" in msg
    assert "_run_inbox_id_scan()" in msg


def test_names_the_mutating_call_behind_a_conditional_binding(tmp_path):
    """registry_monitor shape: the executing call takes no arguments at all."""
    result = _check(_branch(tmp_path, _DEFECTIVE_SHAPES["conditional_subcommand_then_mutating_call"]))
    assert result["passed"] is False, result["checks"]
    msg = result["checks"][0]["message"]
    assert "scan_plan_files()" in msg


def test_work_call_widening_still_honours_the_router_exemption(tmp_path):
    """A normalising router protects the new class exactly as it does the old one."""
    result = _check(_branch(tmp_path, _DEFECTIVE_SHAPES["positional_subcommand_then_work_call"], _ROUTER_NORMALISES))
    assert result["passed"] is True, result["checks"]


def test_work_call_widening_still_honours_a_whole_list_scan(tmp_path):
    """The registry_monitor fix — wants_help(args) — must clear the new rule too."""
    src = _DEFECTIVE_SHAPES["conditional_subcommand_then_mutating_call"].replace(
        "    if args[0] in ('--help', '-h', 'help'):",
        "    if wants_help(args):",
    )
    result = _check(_branch(tmp_path, src))
    assert result["passed"] is True, result["checks"]
    assert result["score"] == 100


# No fixed-position gate exists: handle_command dispatches on `command` and never reads `args`,
# so the router's rewrite to ["--help"] is thrown away and the work call runs.


def test_names_the_command_word_when_args_is_never_read(tmp_path):
    """@cli's shape: the message must name the command word, args, and the call that runs."""
    result = _check(_branch(tmp_path, _DEFECTIVE_SHAPES["command_dispatch_never_reads_args"]))
    assert result["passed"] is False, result["checks"]
    assert result["score"] == 0
    msg = result["checks"][0]["message"]
    assert "handle_command" in msg
    assert "'demo'" in msg
    assert "args" in msg
    assert "run_demo()" in msg


def test_unread_args_arm_survives_a_normalising_router(tmp_path):
    """A router rewriting args to ['--help'] cannot protect a module that never reads args."""
    result = _check(_branch(tmp_path, _DEFECTIVE_SHAPES["command_dispatch_never_reads_args"], _ROUTER_NORMALISES))
    assert result["passed"] is False, result["checks"]
    assert result["score"] == 0


def test_unread_args_arm_does_not_fire_when_args_is_read_at_all(tmp_path):
    """One touch of args leaves this arm — the gate arms judge the module from there."""
    src = (
        "def handle_command(command, args):\n"
        "    if command == 'demo':\n"
        "        run_demo(args)\n"
        "        return True\n"
        "    return False\n"
    )
    result = _check(_branch(tmp_path, src))
    assert result["passed"] is True, result["checks"]
    assert result["score"] == 100


def test_unread_args_arm_does_not_fire_without_a_command_dispatch(tmp_path):
    """No literal command word means no evidence the user typed a verb at all."""
    src = "def handle_command(command, args):\n    run_demo()\n    return True\n"
    result = _check(_branch(tmp_path, src))
    assert result["passed"] is True, result["checks"]


# The router exemption stands only for a module not reachable with raw argv: a `__main__` calling
# handle_command(CMD, sys.argv[1:]) never touches the router.

_STANDALONE_MAIN = "\n\nif __name__ == '__main__':\n    handle_command('thing', sys.argv[1:])\n"

_POSITIONAL_MODULE = (
    "import sys\n\n"
    "def handle_command(command, args):\n"
    "    if args[0] in ('--help', '-h', 'help'):\n"
    "        print_help()\n"
    "        return True\n"
    "    target = args[0]\n"
    "    run(target, args[1:])\n"
    "    return True\n"
)


def test_standalone_main_defeats_router_exemption(tmp_path):
    """backup/snapshot.py shape: router normalises, but `python thing.py x --help` does not."""
    src = _POSITIONAL_MODULE + _STANDALONE_MAIN
    result = _check(_branch(tmp_path, src, _ROUTER_NORMALISES))
    assert result["passed"] is False, result["checks"]
    assert result["score"] == 0


def test_standalone_main_behind_arg_count_guard_still_defeats_exemption(tmp_path):
    """The `if len(sys.argv) < 2: print_introspection()` preamble every backup module carries."""
    src = _POSITIONAL_MODULE + (
        "\n\nif __name__ == '__main__':\n"
        "    if len(sys.argv) < 2:\n"
        "        print_introspection()\n"
        "        sys.exit(0)\n"
        "    handle_command('thing', sys.argv[1:])\n"
    )
    result = _check(_branch(tmp_path, src, _ROUTER_NORMALISES))
    assert result["passed"] is False, result["checks"]


def test_standalone_main_splitting_argv_defeats_exemption(tmp_path):
    """backup/settings.py shape: handle_command(sys.argv[1], sys.argv[2:])."""
    src = _POSITIONAL_MODULE + "\n\nif __name__ == '__main__':\n    handle_command(sys.argv[1], sys.argv[2:])\n"
    result = _check(_branch(tmp_path, src, _ROUTER_NORMALISES))
    assert result["passed"] is False, result["checks"]


def test_partial_token_screen_does_not_keep_exemption(tmp_path):
    """prax/log_audit.py shape: `__main__` screens '--help' only, so `-h` still executes."""
    src = _POSITIONAL_MODULE + (
        "\n\nif __name__ == '__main__':\n"
        "    if '--help' in sys.argv:\n"
        "        print_help()\n"
        "        sys.exit(0)\n"
        "    rest = [a for a in sys.argv[1:] if not a.startswith('--')]\n"
        "    handle_command('thing', rest)\n"
    )
    result = _check(_branch(tmp_path, src, _ROUTER_NORMALISES))
    assert result["passed"] is False, result["checks"]


def test_argparse_without_add_help_does_not_keep_exemption(tmp_path):
    """prax/monitor.py shape: add_help=False and only '--help' declared, so `-h` passes through."""
    src = _POSITIONAL_MODULE + (
        "\n\nif __name__ == '__main__':\n"
        "    parser = argparse.ArgumentParser(add_help=False)\n"
        "    parser.add_argument('--help', action='store_true')\n"
        "    parser.add_argument('tokens', nargs='*')\n"
        "    parsed, passthrough = parser.parse_known_args()\n"
        "    if parsed.help:\n"
        "        print_help()\n"
        "        sys.exit(0)\n"
        "    handle_command('thing', _run_args(parsed.tokens, passthrough))\n"
    )
    result = _check(_branch(tmp_path, src, _ROUTER_NORMALISES))
    assert result["passed"] is False, result["checks"]


def test_standalone_main_flagged_even_without_a_router(tmp_path):
    """No exemption to withdraw — the module was already reported and must stay reported."""
    src = _POSITIONAL_MODULE + _STANDALONE_MAIN
    result = _check(_branch(tmp_path, src))
    assert result["passed"] is False, result["checks"]


def test_main_delegate_that_normalises_keeps_exemption(tmp_path):
    """prax/dashboard.py shape: main() scans argv for both dashed forms before delegating."""
    src = _POSITIONAL_MODULE + (
        "\n\ndef main():\n"
        "    argv = sys.argv[1:]\n"
        "    if '--help' in argv or '-h' in argv:\n"
        "        print_help()\n"
        "        return\n"
        "    handle_command(argv[0], argv[1:])\n"
        "\n\nif __name__ == '__main__':\n"
        "    main()\n"
    )
    result = _check(_branch(tmp_path, src, _ROUTER_NORMALISES))
    assert result["passed"] is True, result["checks"]
    assert result["score"] == 100


def test_main_delegate_that_never_routes_keeps_exemption(tmp_path):
    """daemon/activity_report.py shape: main() is its own program, handle_command is unreachable."""
    src = _POSITIONAL_MODULE + (
        "\n\ndef main():\n"
        "    parser = argparse.ArgumentParser()\n"
        "    parser.add_argument('--hours', type=float, default=24)\n"
        "    parsed = parser.parse_args()\n"
        "    console.print(build_report(parsed.hours))\n"
        "\n\nif __name__ == '__main__':\n"
        "    main()\n"
    )
    result = _check(_branch(tmp_path, src, _ROUTER_NORMALISES))
    assert result["passed"] is True, result["checks"]


def test_module_without_main_block_keeps_exemption(tmp_path):
    """The original exemption case: the router is genuinely the only way in."""
    result = _check(_branch(tmp_path, _POSITIONAL_MODULE, _ROUTER_NORMALISES))
    assert result["passed"] is True, result["checks"]


def test_standalone_main_with_literal_help_list_keeps_exemption(tmp_path):
    """`handle_command(CMD, ['--help'])` is a normalised list, not raw argv."""
    src = _POSITIONAL_MODULE + (
        "\n\nif __name__ == '__main__':\n"
        "    if any(a in ('--help', '-h') for a in sys.argv):\n"
        "        handle_command('thing', ['--help'])\n"
        "        sys.exit(0)\n"
        "    handle_command('thing', sys.argv[1:])\n"
    )
    result = _check(_branch(tmp_path, src, _ROUTER_NORMALISES))
    assert result["passed"] is True, result["checks"]


def test_module_with_own_scan_and_standalone_main_still_passes(tmp_path):
    """The narrowing withdraws an exemption; it never overrides a real whole-list scan."""
    src = (
        "import sys\n\n"
        "def handle_command(command, args):\n"
        "    if any(a in ('--help', '-h') for a in args):\n"
        "        print_help()\n"
        "        return True\n"
        "    run(args[0], args[1:])\n"
        "    return True\n"
    ) + _STANDALONE_MAIN
    result = _check(_branch(tmp_path, src, _ROUTER_NORMALISES))
    assert result["passed"] is True, result["checks"]
    assert result["score"] == 100


def test_a_help_word_in_an_unrelated_constant_is_no_scan_of_the_args(tmp_path):
    src = (
        'SUBS = ["help", "run"]\n\n'
        "def handle_command(command, args):\n"
        '    if "help" in SUBS:\n'
        "        pass\n"
        '    if args and args[0] in ("--help", "-h"):\n'
        "        print_help()\n"
        "        return True\n"
        "    do_work(args)\n"
        "    return True\n"
    )
    assert _check(_branch(tmp_path, src))["passed"] is False


def test_unpacking_the_args_puts_the_flag_in_a_value_slot(tmp_path):
    src = (
        "def handle_command(command, args):\n"
        '    if args and args[0] == "--help":\n'
        "        print_help()\n"
        "        return True\n"
        "    target, *rest = args\n"
        "    deploy(target)\n"
        "    return True\n"
    )
    result = _check(_branch(tmp_path, src))
    assert result["passed"] is False
    assert "'target' value slot" in result["checks"][0]["message"]
