# =================== AIPass ====================
# Name: test_checkers_batch7_introspection.py
# Description: introspection_check sub-functions (split from test_checkers_batch7.py)
# Version: 1.0.1
# Created: 2026-10-08
# Modified: 2026-10-24
# =============================================

"""Tests for apps/handlers/aipass_standards/introspection_check.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that each checker in handlers/aipass_standards/ parses and imports
# seedgo: no-test-needed(stdlib) — ast.parse's parsing; the checkers only walk the tree it returns

import ast

import pytest

from aipass.seedgo.apps.handlers.aipass_standards.introspection_check import (
    check_content_references,
    check_correct_dispatch,
    check_execution_order,
    check_introspection_rich_formatting,
    check_module_handle_command_gate,
    check_module_help_interception,
    check_print_introspection_exists,
)

pytestmark = pytest.mark.usefixtures("_pin_bypass_log")


# ===========================================================================
# 3. introspection_check sub-functions
# ===========================================================================


# -- check_print_introspection_exists ----------------------------------------


class TestCheckPrintIntrospectionExists:
    """Tests for check_print_introspection_exists."""

    def test_function_present_passes(self):
        """File with def print_introspection passes."""
        content = "def print_introspection():\n    pass\n"
        tree = ast.parse(content)
        result = check_print_introspection_exists(tree, "test.py")
        assert result["passed"] is True

    def test_function_missing_fails(self):
        """File without print_introspection fails."""
        content = "def main():\n    pass\n"
        tree = ast.parse(content)
        result = check_print_introspection_exists(tree, "test.py")
        assert result["passed"] is False
        assert "Missing" in result["message"]


# -- check_execution_order --------------------------------------------------


class TestCheckExecutionOrder:
    """Tests for check_execution_order."""

    def test_correct_order_passes(self):
        """No-args check before --help check passes."""
        content = (
            "def main():\n"
            "    if not args:\n"
            "        print_introspection()\n"
            "    if '--help' in args:\n"
            "        print_help()\n"
        )
        tree = ast.parse(content)
        result = check_execution_order(tree, "test.py")
        assert result is not None
        assert result["passed"] is True

    def test_wrong_order_fails(self):
        """--help check before no-args check fails."""
        content = (
            "def main():\n"
            "    if '--help' in args:\n"
            "        print_help()\n"
            "    if not args:\n"
            "        print_introspection()\n"
        )
        tree = ast.parse(content)
        result = check_execution_order(tree, "test.py")
        assert result is not None
        assert result["passed"] is False

    def test_no_main_skips(self):
        """File without main() or __name__ block is skipped."""
        content = "def compute():\n    return 42\n"
        tree = ast.parse(content)
        result = check_execution_order(tree, "test.py")
        assert result is not None
        assert result["passed"] is True
        assert "skipped" in result["message"].lower()


# -- check_module_handle_command_gate ----------------------------------------


class TestCheckModuleHandleCommandGate:
    """Tests for check_module_handle_command_gate."""

    def test_gate_present_passes(self):
        """handle_command with no-args gate calling print_introspection passes."""
        content = (
            "def handle_command(command, args):\n"
            "    if not args:\n"
            "        print_introspection()\n"
            "        return True\n"
            "    return False\n"
        )
        tree = ast.parse(content)
        result = check_module_handle_command_gate(tree, "test.py")
        assert result is not None
        assert result["passed"] is True

    def test_gate_missing_fails(self):
        """handle_command without no-args gate fails."""
        content = "def handle_command(command, args):\n    do_work(args)\n    return True\n"
        tree = ast.parse(content)
        result = check_module_handle_command_gate(tree, "test.py")
        assert result is not None
        assert result["passed"] is False

    def test_a_has_arguments_test_is_no_no_args_gate(self):
        content = (
            "def handle_command(command, args):\n"
            "    if len(args) > 0:\n"
            "        print_introspection()\n"
            "        return True\n"
            "    return False\n"
        )
        result = check_module_handle_command_gate(ast.parse(content), "test.py")
        assert result is not None
        assert result["passed"] is False

    def test_no_handle_command_skips(self):
        """File without handle_command is skipped."""
        content = "def compute():\n    return 42\n"
        tree = ast.parse(content)
        result = check_module_handle_command_gate(tree, "test.py")
        assert result is not None
        assert result["passed"] is True
        assert "skipped" in result["message"].lower()


# -- check_correct_dispatch -------------------------------------------------


class TestCheckCorrectDispatch:
    """Tests for check_correct_dispatch."""

    def test_correct_dispatch_passes(self):
        """No-args calls introspection and --help calls help passes."""
        content = (
            "def main():\n"
            "    if not args:\n"
            "        print_introspection()\n"
            "    if '--help' in args:\n"
            "        print_help()\n"
        )
        tree = ast.parse(content)
        result = check_correct_dispatch(tree, "test.py")
        assert result is not None
        assert result["passed"] is True

    def test_swapped_dispatch_fails(self):
        """No-args calling print_help instead of print_introspection fails."""
        content = (
            "def main():\n"
            "    if not args:\n"
            "        print_help()\n"
            "    if '--help' in args:\n"
            "        print_introspection()\n"
        )
        tree = ast.parse(content)
        result = check_correct_dispatch(tree, "test.py")
        assert result is not None
        assert result["passed"] is False

    def test_no_main_returns_none(self):
        """File without main function returns None."""
        content = "def compute():\n    return 42\n"
        tree = ast.parse(content)
        result = check_correct_dispatch(tree, "test.py")
        assert result is None


# -- check_content_references ------------------------------------------------


class TestCheckContentReferences:
    """Tests for check_content_references."""

    def test_correct_references_passes(self):
        """Introspection text without python3 references passes."""
        content = "def print_introspection():\n    msg = 'Use: drone @mybranch command'\n    return msg\n"
        tree = ast.parse(content)
        result = check_content_references(tree, "test.py")
        assert result is not None
        assert result["passed"] is True

    def test_python3_reference_fails(self):
        """Introspection text referencing python3 fails."""
        content = "def print_introspection():\n    msg = 'Run: python3 mybranch.py command'\n    return msg\n"
        tree = ast.parse(content)
        result = check_content_references(tree, "test.py")
        assert result is not None
        assert result["passed"] is False
        assert "python3" in result["message"]

    def test_no_relevant_funcs_returns_none(self):
        """File without print_introspection or print_help returns None."""
        content = "def compute():\n    return 42\n"
        tree = ast.parse(content)
        result = check_content_references(tree, "test.py")
        assert result is None


# -- check_module_help_interception ------------------------------------------


class TestCheckModuleHelpInterception:
    """Tests for check_module_help_interception."""

    def test_help_intercepted_passes(self):
        """handle_command that intercepts --help passes."""
        content = (
            "def handle_command(command, args):\n"
            "    if '--help' in args:\n"
            "        print_help()\n"
            "        return True\n"
            "    return False\n"
        )
        tree = ast.parse(content)
        result = check_module_help_interception(tree, "test.py")
        assert result is not None
        assert result["passed"] is True

    def test_help_not_intercepted_fails(self):
        """handle_command without --help interception fails."""
        content = "def handle_command(command, args):\n    do_work(args)\n    return True\n"
        tree = ast.parse(content)
        result = check_module_help_interception(tree, "test.py")
        assert result is not None
        assert result["passed"] is False
        assert "does not intercept" in result["message"]

    def test_no_handle_command_returns_none(self):
        """File without handle_command returns None."""
        content = "def compute():\n    return 42\n"
        tree = ast.parse(content)
        result = check_module_help_interception(tree, "test.py")
        assert result is None

    def test_imported_help_predicate_passes(self):
        """A delegated predicate imported from a handler counts as interception."""
        content = (
            "from aipass.memory.apps.handlers.cli.help_flags import wants_help\n"
            "\n"
            "def handle_command(command, args):\n"
            "    if wants_help(args, allow_bare_word=True):\n"
            "        print_help()\n"
            "        return True\n"
            "    return False\n"
        )
        tree = ast.parse(content)
        result = check_module_help_interception(tree, "test.py")
        assert result is not None
        assert result["passed"] is True

    def test_locally_defined_help_predicate_passes(self):
        """A predicate defined in the same file counts as interception."""
        content = (
            "def _is_help_request(args):\n"
            "    return bool(args)\n"
            "\n"
            "def handle_command(command, args):\n"
            "    if _is_help_request(args):\n"
            "        print_help()\n"
            "        return True\n"
            "    return False\n"
        )
        tree = ast.parse(content)
        result = check_module_help_interception(tree, "test.py")
        assert result is not None
        assert result["passed"] is True

    def test_non_help_predicate_call_fails(self):
        """An unrelated predicate call is not mistaken for a help guard."""
        content = (
            "def should_process(args):\n"
            "    return bool(args)\n"
            "\n"
            "def handle_command(command, args):\n"
            "    if should_process(args):\n"
            "        do_work(args)\n"
            "    return True\n"
        )
        tree = ast.parse(content)
        result = check_module_help_interception(tree, "test.py")
        assert result is not None
        assert result["passed"] is False
        assert "does not intercept" in result["message"]

    def test_helper_substring_name_does_not_pass(self):
        """'helper' merely contains 'help' -- it is not a help predicate."""
        content = (
            "def _has_credential_helper(args):\n"
            "    return bool(args)\n"
            "\n"
            "def handle_command(command, args):\n"
            "    if _has_credential_helper(args):\n"
            "        do_work(args)\n"
            "    return True\n"
        )
        tree = ast.parse(content)
        result = check_module_help_interception(tree, "test.py")
        assert result is not None
        assert result["passed"] is False
        assert "does not intercept" in result["message"]

    def test_help_predicate_not_asked_about_args_does_not_pass(self):
        """A help-named predicate applied to something other than the args is no guard."""
        content = (
            "def _contains_help_string(node):\n"
            "    return bool(node)\n"
            "\n"
            "def handle_command(command, args):\n"
            "    for node in walk(tree):\n"
            "        if _contains_help_string(node):\n"
            "            record(node)\n"
            "    return True\n"
        )
        tree = ast.parse(content)
        result = check_module_help_interception(tree, "test.py")
        assert result is not None
        assert result["passed"] is False
        assert "does not intercept" in result["message"]

    def test_unresolved_help_predicate_does_not_pass(self):
        """A help-named attribute call on an unknown object does not count."""
        content = (
            "def handle_command(command, args):\n"
            "    if ctx.cli.wants_help(args):\n"
            "        print_help()\n"
            "        return True\n"
            "    return False\n"
        )
        tree = ast.parse(content)
        result = check_module_help_interception(tree, "test.py")
        assert result is not None
        assert result["passed"] is False
        assert "does not intercept" in result["message"]


# -- check_introspection_rich_formatting ------------------------------------


class TestCheckIntrospectionRichFormatting:
    """Tests for check_introspection_rich_formatting."""

    def test_styled_introspection_passes(self):
        """print_introspection with Rich markup tags passes."""
        content = (
            "def print_introspection():\n"
            "    console.print('[bold cyan]Flow[/bold cyan] - PLAN Management')\n"
            "    console.print(f'[yellow]Modules:[/yellow] {count}')\n"
        )
        tree = ast.parse(content)
        result = check_introspection_rich_formatting(tree, "test.py")
        assert result is not None
        assert result["passed"] is True
        assert "Rich markup" in result["message"]

    def test_flat_introspection_fails(self):
        """print_introspection with only plain strings fails."""
        content = (
            "def print_introspection():\n"
            "    console.print('spawn Entry Point')\n"
            "    console.print('Branch lifecycle manager')\n"
            "    console.print('Connected Modules:')\n"
        )
        tree = ast.parse(content)
        result = check_introspection_rich_formatting(tree, "test.py")
        assert result is not None
        assert result["passed"] is False
        assert "no Rich markup" in result["message"]

    def test_delegation_to_styled_helper_passes(self):
        """print_introspection delegating to a styled _helper passes."""
        content = (
            "def _show_branch_introspection():\n"
            "    console.print('[bold cyan]Branch[/bold cyan]')\n"
            "    console.print(f'[yellow]Modules:[/yellow]')\n"
            "\n"
            "def print_introspection():\n"
            "    _show_branch_introspection()\n"
        )
        tree = ast.parse(content)
        result = check_introspection_rich_formatting(tree, "test.py")
        assert result is not None
        assert result["passed"] is True
        assert "delegates" in result["message"]

    def test_delegation_to_flat_helper_fails(self):
        """print_introspection delegating to a flat _helper fails."""
        content = (
            "def _show_info():\n"
            "    console.print('Plain text only')\n"
            "    console.print('No formatting here')\n"
            "\n"
            "def print_introspection():\n"
            "    _show_info()\n"
        )
        tree = ast.parse(content)
        result = check_introspection_rich_formatting(tree, "test.py")
        assert result is not None
        assert result["passed"] is False
        assert "no Rich markup" in result["message"]

    def test_no_print_introspection_returns_none(self):
        """File without print_introspection returns None."""
        content = "def compute():\n    return 42\n"
        tree = ast.parse(content)
        result = check_introspection_rich_formatting(tree, "test.py")
        assert result is None

    def test_no_output_returns_none(self):
        """print_introspection that produces no output returns None."""
        content = "def print_introspection():\n    return {'name': 'test'}\n"
        tree = ast.parse(content)
        result = check_introspection_rich_formatting(tree, "test.py")
        assert result is None
