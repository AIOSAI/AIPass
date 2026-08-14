# =================== AIPass ====================
# Name: test_help_flag_safety.py
# Description: Rule E canaries — a help flag anywhere explains, never executes
# Version: 1.0.0
# Created: 2026-08-13
# Modified: 2026-08-13
# =============================================

"""Rule E canaries: a help flag ANYWHERE means explain, never execute.

Every drone module gated help at one fixed slot, so `--help` typed after the
first argument was invisible and the verb ran anyway (DPLAN-0291 round,
help_flag_safety 9/100).

Every test here mocks its dispatch target and asserts it was NEVER CALLED. No
live verb is fired to prove the trap — `rm` deletes files and the git write
paths mutate a repo, so the proof is that the mock stayed untouched, not that
the damage was survivable.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from aipass.drone.apps.handlers.help_flags import wants_help


# ===========================================================================
# 1. The predicate itself
# ===========================================================================


class TestWantsHelp:
    """wants_help() — the whole-sequence question."""

    @pytest.mark.parametrize(
        "command,args",
        [
            ("--help", []),
            ("-h", []),
            ("help", []),
            ("status", ["--help"]),
            ("status", ["-h"]),
            ("commit", ["a message", "--help"]),
            ("route", ["@target", "cmd", "arg", "--help"]),
            ("add", ["name", "target", "cmd", "-h"]),
        ],
    )
    def test_help_anywhere_is_help(self, command: str, args: list[str]) -> None:
        assert wants_help(command, args) is True

    @pytest.mark.parametrize(
        "command,args",
        [
            ("status", []),
            ("commit", ["a message"]),
            ("lookup", ["helper"]),
            ("rm", ["docs/help.md"]),
            ("add", ["name", "--desc=how to get help"]),
        ],
    )
    def test_ordinary_invocations_are_not_help(self, command: str, args: list[str]) -> None:
        assert wants_help(command, args) is False

    def test_bare_help_only_at_position_zero(self) -> None:
        """A later 'help' is a value — a path, a branch, a search term."""
        assert wants_help("help", []) is True
        assert wants_help("lookup", ["help"]) is False
        assert wants_help("rm", ["help"]) is False

    def test_bare_help_opt_out_for_modules_that_own_the_verb(self) -> None:
        """discovery has a real `help <target>` subcommand — it must survive."""
        assert wants_help("help", ["@seedgo"], bare_help=False) is False
        assert wants_help("help", ["@seedgo", "--help"], bare_help=False) is True

    def test_empty_is_not_help(self) -> None:
        assert wants_help(None, None) is False
        assert wants_help(None, []) is False

    def test_substrings_and_lookalikes_do_not_count(self) -> None:
        """Exact match only — --helpful is not --help."""
        assert wants_help("run", ["--helpful"]) is False
        assert wants_help("run", ["help.txt"]) is False
        assert wants_help("run", ["-help"]) is False


# ===========================================================================
# 2. Per-module canaries — target mocked, asserted never called
# ===========================================================================

_M = "aipass.drone.apps.modules"


class TestRmNeverDeletesOnHelp:
    """rm is the one that bites: every token is a PATH.

    `drone rm notes.md --help` deleted notes.md and then tried to delete a file
    literally named `--help`. _safe_delete is mocked — this proves the trap
    without ever putting a real path at risk.
    """

    @pytest.mark.parametrize(
        "command,args",
        [
            ("notes.md", ["--help"]),
            ("notes.md", ["-h"]),
            ("a.txt", ["b.txt", "--help"]),
            ("--help", []),
        ],
    )
    def test_help_never_reaches_safe_delete(self, command: str, args: list[str]) -> None:
        from aipass.drone.apps.modules.rm import handle_command

        with (
            patch(f"{_M}.rm._safe_delete") as delete,
            patch(f"{_M}.rm.print_help") as help_,
        ):
            result = handle_command(command, args)

        delete.assert_not_called()
        help_.assert_called_once()
        assert result is True

    def test_ordinary_delete_still_reaches_the_handler(self) -> None:
        """The trap must not swallow real work."""
        from aipass.drone.apps.modules.rm import handle_command

        with (
            patch(f"{_M}.rm._safe_delete", return_value=[("a.txt", True, "deleted")]) as delete,
            patch(f"{_M}.rm.print_help") as help_,
            patch(f"{_M}.rm.success"),
        ):
            handle_command("a.txt", [])

        delete.assert_called_once_with(["a.txt"])
        help_.assert_not_called()


class TestGitModuleNeverExecutesOnHelp:
    """git_module reaches commit/merge/tag — code-proved, never fired."""

    @pytest.mark.parametrize(
        "command,args",
        [
            ("status", ["--help"]),
            ("log", ["5", "--help"]),
            ("issue", ["list", "--help"]),
            ("commit", ["a message", "--help"]),
        ],
    )
    def test_help_short_circuits_before_auth_and_dispatch(self, command: str, args: list[str]) -> None:
        from aipass.drone.apps.modules.git_module import handle_command

        with (
            patch("aipass.drone.apps.plugins.devpulse_ops.auth.verify_git_access") as auth,
            patch(f"{_M}.git_module.print_help") as help_,
        ):
            result = handle_command(command, args)

        help_.assert_called_once()
        auth.assert_not_called()
        assert result["exit_code"] == 0


class TestConfigNeverSetsOnHelp:
    """config set mutates the registry path — a stray flag must not land it."""

    def test_set_with_trailing_help_does_not_set(self) -> None:
        from aipass.drone.apps.modules.config import handle_command

        with (
            patch(f"{_M}.config.set_registry_path") as setter,
            patch(f"{_M}.config.print_help") as help_,
        ):
            result = handle_command("set", ["/tmp/somewhere", "--help"])

        setter.assert_not_called()
        help_.assert_called_once()
        assert result is True


class TestRouterNeverRoutesOnHelp:
    """router route dispatches an arbitrary command to another branch."""

    def test_route_with_trailing_help_does_not_route(self) -> None:
        from aipass.drone.apps.modules.router import handle_command

        with (
            patch(f"{_M}.router.route_command") as route,
            patch(f"{_M}.router.print_help") as help_,
        ):
            result = handle_command("route", ["@seedgo", "audit", "--help"])

        route.assert_not_called()
        help_.assert_called_once()
        assert result is True


class TestCommandsNeverMutatesOnHelp:
    """commands add/remove writes the shortcut registry."""

    def test_add_with_trailing_help_does_not_add(self) -> None:
        from aipass.drone.apps.modules.commands import handle_command

        with (
            patch(f"{_M}.commands.add") as add,
            patch(f"{_M}.commands.print_help") as help_,
        ):
            result = handle_command("add", ["name", "@target", "cmd", "--help"])

        add.assert_not_called()
        help_.assert_called_once()
        assert result is True


class TestReadOnlyModulesStillHonourRuleE:
    """scan, resolver, registry, module_registry, discovery — read-only, same rule.

    Rule E is not only about damage. A command that explains itself when asked
    is the contract; these are the safe verbs, and they must obey it too.
    """

    def test_scan_does_not_scan(self) -> None:
        from aipass.drone.apps.modules.scan import handle_command

        with (
            patch(f"{_M}.scan.scan") as target,
            patch(f"{_M}.scan.print_help") as help_,
        ):
            result = handle_command(None, ["@seedgo", "--help"])

        target.assert_not_called()
        help_.assert_called_once()
        assert result is True

    def test_resolver_does_not_resolve(self) -> None:
        from aipass.drone.apps.modules.resolver import handle_command

        with (
            patch(f"{_M}.resolver.resolve_branch") as target,
            patch(f"{_M}.resolver.print_help") as help_,
        ):
            result = handle_command("resolve", ["@seedgo", "--help"])

        target.assert_not_called()
        help_.assert_called_once()
        assert result is True

    def test_registry_does_not_look_up(self) -> None:
        from aipass.drone.apps.modules.registry import handle_command

        with (
            patch(f"{_M}.registry.get_branch_by_name") as target,
            patch(f"{_M}.registry.print_help") as help_,
        ):
            result = handle_command("lookup", ["seedgo", "--help"])

        target.assert_not_called()
        help_.assert_called_once()
        assert result is True

    def test_module_registry_does_not_query(self) -> None:
        from aipass.drone.apps.modules.module_registry import handle_command

        with (
            patch(f"{_M}.module_registry.get_module_info") as target,
            patch(f"{_M}.module_registry.print_help") as help_,
        ):
            result = handle_command("info", ["git", "--help"])

        target.assert_not_called()
        help_.assert_called_once()
        assert result is True

    def test_discovery_does_not_discover(self) -> None:
        from aipass.drone.apps.modules.discovery import handle_command

        with (
            patch(f"{_M}.discovery.discover_modules") as target,
            patch(f"{_M}.discovery.print_help") as help_,
        ):
            result = handle_command("modules", ["@seedgo", "--help"])

        target.assert_not_called()
        help_.assert_called_once()
        assert result is True


class TestDiscoveryHelpSubcommandSurvives:
    """discovery owns `help <target>` as a real verb — rule E must not eat it.

    This is the regression the bare-help rule would otherwise cause: a module
    whose legitimate subcommand IS the word help.
    """

    def test_help_target_still_dispatches(self) -> None:
        from aipass.drone.apps.modules.discovery import handle_command

        with (
            patch(f"{_M}.discovery.get_help") as target,
            patch(f"{_M}.discovery.print_help") as help_,
            patch(f"{_M}.discovery.console"),
        ):
            target.return_value.text = "seedgo help text"
            result = handle_command("help", ["@seedgo"])

        target.assert_called_once_with("@seedgo", None)
        help_.assert_not_called()
        assert result is True

    def test_help_target_with_flag_explains_instead(self) -> None:
        """...but a dashed flag alongside it still wins."""
        from aipass.drone.apps.modules.discovery import handle_command

        with (
            patch(f"{_M}.discovery.get_help") as target,
            patch(f"{_M}.discovery.print_help") as help_,
        ):
            result = handle_command("help", ["@seedgo", "--help"])

        target.assert_not_called()
        help_.assert_called_once()
        assert result is True
