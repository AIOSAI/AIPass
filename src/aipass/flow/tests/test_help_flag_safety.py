"""Tests for whole-sequence help detection (DPLAN-0291 rule E).

The contract: a help flag ANYWHERE in the argument sequence means explain and
do nothing else. Flow's verbs mutate plans -- `close FPLAN-0042 --help` used to
CLOSE FPLAN-0042 -- so every canary here asserts two things together:
help was printed AND the destructive target was never called.

Free-text safety is asserted alongside it: a plan subject containing the word
"help" must stay a subject.
"""

from unittest.mock import patch

import pytest

from aipass.flow.apps.handlers.cli.help_flags import wants_help


# ═══════════════════════════════════════════════════════════
# 1. wants_help predicate
# ═══════════════════════════════════════════════════════════


class TestWantsHelpPredicate:
    @pytest.mark.parametrize("args", [["--help"], ["-h"], ["help"]])
    def test_help_at_position_zero(self, args):
        assert wants_help(args) is True

    @pytest.mark.parametrize(
        "args",
        [
            ["FPLAN-0042", "--help"],
            ["FPLAN-0042", "-h"],
            [".", "Some subject", "--help"],
            ["--all", "--dry-run", "--help"],
        ],
    )
    def test_dashed_help_anywhere_is_caught(self, args):
        assert wants_help(args) is True

    def test_bare_help_only_counts_at_position_zero(self):
        # A plan subject that is exactly the word "help" must stay a subject.
        assert wants_help([".", "help"]) is False

    @pytest.mark.parametrize(
        "args",
        [
            [".", "Fix the help system"],
            [".", "help the user onboard"],
            [".", "Rewrite --help output"],
            ["FPLAN-0042"],
            ["open"],
        ],
    )
    def test_free_text_subjects_are_not_help_requests(self, args):
        assert wants_help(args) is False

    def test_empty_and_none(self):
        assert wants_help([]) is False
        assert wants_help(None) is False

    def test_bare_help_disabled(self):
        assert wants_help(["help"], bare_help=False) is False
        assert wants_help(["help", "--help"], bare_help=False) is True


# ═══════════════════════════════════════════════════════════
# 2. close -- a help probe must never close a plan
# ═══════════════════════════════════════════════════════════

_CLOSE = "aipass.flow.apps.modules.close_plan"


class TestCloseHelpSafety:
    @pytest.mark.parametrize(
        "args",
        [["FPLAN-0042", "--help"], ["FPLAN-0042", "-h"], ["--all", "--help"]],
    )
    def test_help_after_plan_number_never_closes(self, args):
        from aipass.flow.apps.modules import close_plan as mod

        with patch(f"{_CLOSE}.close_plan") as target, patch(f"{_CLOSE}.print_help") as help_fn:
            handled = mod.handle_command("close", args)

        assert handled is True
        help_fn.assert_called_once()
        target.assert_not_called()

    def test_normal_close_still_reaches_the_verb(self):
        from aipass.flow.apps.modules import close_plan as mod

        with patch(f"{_CLOSE}.close_plan") as target, patch(f"{_CLOSE}.print_help") as help_fn:
            mod.handle_command("close", ["FPLAN-0042"])

        help_fn.assert_not_called()
        target.assert_called_once()

    def test_foreign_command_is_not_claimed(self):
        """Ownership check runs BEFORE the help gate -- a module must never
        hijack another module's --help (routers try modules in turn)."""
        from aipass.flow.apps.modules import close_plan as mod

        with patch(f"{_CLOSE}.print_help") as help_fn:
            handled = mod.handle_command("list", ["--help"])

        assert handled is False
        help_fn.assert_not_called()


# ═══════════════════════════════════════════════════════════
# 3. create -- a help probe must never create a plan
# ═══════════════════════════════════════════════════════════

_CREATE = "aipass.flow.apps.modules.create_plan"


class TestCreateHelpSafety:
    @pytest.mark.parametrize(
        "args",
        [[".", "Some subject", "--help"], [".", "-h"], [".", "Subject", "dplan", "--help"]],
    )
    def test_help_after_location_never_creates(self, args):
        from aipass.flow.apps.modules import create_plan as mod

        with patch(f"{_CREATE}.create_plan") as target, patch(f"{_CREATE}.print_help") as help_fn:
            handled = mod.handle_command("create", args)

        assert handled is True
        help_fn.assert_called_once()
        target.assert_not_called()

    def test_subject_containing_help_still_creates(self):
        """Free text: 'help' inside a subject is a subject, not a request."""
        from aipass.flow.apps.modules import create_plan as mod

        with (
            patch(f"{_CREATE}.create_plan", return_value=(True, 1, ".", "default", None)) as target,
            patch(f"{_CREATE}.print_help") as help_fn,
        ):
            mod.handle_command("create", [".", "Fix the help system"])

        help_fn.assert_not_called()
        target.assert_called_once()

    def test_foreign_command_is_not_claimed(self):
        from aipass.flow.apps.modules import create_plan as mod

        with patch(f"{_CREATE}.print_help") as help_fn:
            handled = mod.handle_command("close", ["--help"])

        assert handled is False
        help_fn.assert_not_called()


# ═══════════════════════════════════════════════════════════
# 4. restore -- a help probe must never restore a plan
# ═══════════════════════════════════════════════════════════

_RESTORE = "aipass.flow.apps.modules.restore_plan"


class TestRestoreHelpSafety:
    @pytest.mark.parametrize("args", [["FPLAN-0042", "--help"], ["FPLAN-0042", "-h"]])
    def test_help_after_plan_number_never_restores(self, args):
        from aipass.flow.apps.modules import restore_plan as mod

        with patch(f"{_RESTORE}.restore_plan") as target, patch(f"{_RESTORE}.print_help") as help_fn:
            handled = mod.handle_command("restore", args)

        assert handled is True
        help_fn.assert_called_once()
        target.assert_not_called()

    def test_foreign_command_is_not_claimed(self):
        from aipass.flow.apps.modules import restore_plan as mod

        with patch(f"{_RESTORE}.print_help") as help_fn:
            handled = mod.handle_command("close", ["--help"])

        assert handled is False
        help_fn.assert_not_called()


# ═══════════════════════════════════════════════════════════
# 5. aggregate -- a help probe must never aggregate
# ═══════════════════════════════════════════════════════════

_AGG = "aipass.flow.apps.modules.aggregate_central"


class TestAggregateHelpSafety:
    @pytest.mark.parametrize("args", [["--heal", "--help"], ["--no-heal", "-h"]])
    def test_help_after_flag_never_aggregates(self, args):
        from aipass.flow.apps.modules import aggregate_central as mod

        with patch(f"{_AGG}.aggregate_central") as target, patch(f"{_AGG}.print_help") as help_fn:
            handled = mod.handle_command("aggregate", args)

        assert handled is True
        help_fn.assert_called_once()
        target.assert_not_called()

    def test_foreign_command_is_not_claimed(self):
        from aipass.flow.apps.modules import aggregate_central as mod

        with patch(f"{_AGG}.print_help") as help_fn:
            handled = mod.handle_command("close", ["--help"])

        assert handled is False
        help_fn.assert_not_called()


# ═══════════════════════════════════════════════════════════
# 6. template_manager -- register/unregister mutate the registry
# ═══════════════════════════════════════════════════════════

_TPL = "aipass.flow.apps.modules.template_manager"


class TestTemplateManagerHelpSafety:
    def test_register_help_never_registers(self):
        from aipass.flow.apps.modules import template_manager as mod

        with patch(f"{_TPL}.add_type") as target, patch(f"{_TPL}.print_help") as help_fn:
            handled = mod.handle_command("register", ["audit_test", "--help"])

        assert handled is True
        help_fn.assert_called_once()
        target.assert_not_called()

    def test_unregister_help_never_unregisters(self):
        from aipass.flow.apps.modules import template_manager as mod

        with patch(f"{_TPL}.remove_type") as target, patch(f"{_TPL}.print_help") as help_fn:
            handled = mod.handle_command("unregister", ["--help"])

        assert handled is True
        help_fn.assert_called_once()
        target.assert_not_called()

    def test_templates_help_anywhere(self):
        from aipass.flow.apps.modules import template_manager as mod

        with patch(f"{_TPL}.load_registry") as target, patch(f"{_TPL}.print_help") as help_fn:
            handled = mod.handle_command("templates", ["verbose", "--help"])

        assert handled is True
        help_fn.assert_called_once()
        target.assert_not_called()

    def test_scan_help_never_scans(self):
        from aipass.flow.apps.modules import template_manager as mod

        with patch(f"{_TPL}.scan_unregistered") as target, patch(f"{_TPL}.print_help") as help_fn:
            handled = mod.handle_command("scan", ["--help"])

        assert handled is True
        help_fn.assert_called_once()
        target.assert_not_called()

    def test_foreign_command_is_not_claimed(self):
        from aipass.flow.apps.modules import template_manager as mod

        with patch(f"{_TPL}.print_help") as help_fn:
            handled = mod.handle_command("close", ["--help"])

        assert handled is False
        help_fn.assert_not_called()


# ═══════════════════════════════════════════════════════════
# 7. Modules seedgo did NOT flag, same shape, two of them mutate
#
# help_flag_safety named 5 modules. These three carried the identical
# args[0]-only gate: `registry scan` heals the registry and `post` archives
# and vectorises closed plans, so both mutate state on a help probe.
# ═══════════════════════════════════════════════════════════

_LIST = "aipass.flow.apps.modules.list_plans"
_REG = "aipass.flow.apps.modules.registry_monitor"
_POST = "aipass.flow.apps.modules.post_close_runner"


class TestUnflaggedModulesHelpSafety:
    def test_list_help_after_filter_never_lists(self):
        from aipass.flow.apps.modules import list_plans as mod

        with patch(f"{_LIST}.list_plans") as target, patch(f"{_LIST}.print_help") as help_fn:
            handled = mod.handle_command("list", ["open", "--help"])

        assert handled is True
        help_fn.assert_called_once()
        target.assert_not_called()

    def test_registry_scan_help_never_heals(self):
        """`registry scan --help` reached scan_plan_files(), which WRITES."""
        from aipass.flow.apps.modules import registry_monitor as mod

        with patch(f"{_REG}.scan_plan_files") as target, patch(f"{_REG}.print_help") as help_fn:
            handled = mod.handle_command("registry", ["scan", "--help"])

        assert handled is True
        help_fn.assert_called_once()
        target.assert_not_called()

    def test_post_help_never_processes(self):
        from aipass.flow.apps.modules import post_close_runner as mod

        with patch(f"{_POST}.acquire_lock") as target, patch(f"{_POST}.print_help") as help_fn:
            handled = mod.handle_command("post", ["--force", "--help"])

        assert handled is True
        help_fn.assert_called_once()
        target.assert_not_called()

    def test_normal_registry_status_still_works(self):
        from aipass.flow.apps.modules import registry_monitor as mod

        with patch(f"{_REG}.print_help") as help_fn:
            handled = mod.handle_command("registry", ["status"])

        assert handled is True
        help_fn.assert_not_called()
