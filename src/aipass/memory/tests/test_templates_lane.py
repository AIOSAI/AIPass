# =================== AIPass ====================
# Name: test_templates_lane.py
# Description: Pins for the live templates lane — spawn propagation, receipt status, the bump site, and two refusals
# Version: 1.0.0
# Created: 2026-08-27
# Modified: 2026-08-27
# =============================================

"""The templates module, after the pre-`.trinity` lane was retired.

Replaces `test_templates.py` and `test_templates_display.py`, archived with the
handlers they pinned (`.archive/dead_template_lane_20260827/`). Their sixteen
still-passing tests were all help-flag safety and routing; those behaviours are
re-pinned here against the surface that actually exists.

WHAT THIS FILE EXISTS TO PREVENT
--------------------------------
A retired verb that silently does nothing is worse than one that is gone: it
answers, it looks like it worked, and the caller trusts it. `push-templates`
and `diff-templates` spent months confidently reporting on a layout no citizen
uses. So the pins are not "the code is deleted" — they are "the verb ANSWERS,
and what it says is where to go instead."

The bump lane's pins all guard the same edge: a template version bump must heal
the fleet THROUGH the trinity push's gates, never around them. An automatic
fleet-wide rewrite triggered by a version number would be the exact unprompted
write `--confirm` exists to stop, and this branch has already performed one of
those by accident.
"""

from pathlib import Path
from unittest.mock import patch

from aipass.memory.apps.modules import templates
from aipass.memory.apps.handlers.templates import template_bump


_MEMORY_ROOT = Path(__file__).resolve().parents[1]


def _out(capsys) -> str:
    """Everything the module printed, both streams, unwrapped.

    Rich hard-wraps at the terminal width, so a sentence this file asserts on
    can arrive split across two lines. Collapsing whitespace makes these pins
    test the MESSAGE rather than the width of whatever terminal ran them —
    the same hermeticity lesson the fixtures learned in session 146.
    """
    captured = capsys.readouterr()
    return " ".join((captured.out + captured.err).split())


# =============================================================================
# THE TWO REFUSALS
# =============================================================================


class TestRetiredVerbsAnswer:
    """A retired verb routes, refuses, and names its replacement."""

    def test_both_retired_verbs_are_still_routed(self):
        for verb in ("push-templates", "diff-templates"):
            assert templates.handle_command(verb, []) is True
            assert templates.handle_command("templates", [verb]) is True

    def test_push_templates_names_both_live_lanes(self, capsys):
        templates.handle_command("templates", ["push-templates"])
        printed = _out(capsys)

        assert "retired" in printed.lower()
        assert "drone @memory push" in printed
        assert "spawn-templates" in printed

    def test_diff_templates_names_the_dry_run(self, capsys):
        templates.handle_command("templates", ["diff-templates"])
        printed = _out(capsys)

        assert "retired" in printed.lower()
        assert "--dry-run" in printed

    def test_the_refusal_says_where_the_handlers_went(self, capsys):
        """A reader who wants the old code must be able to find it."""
        templates.handle_command("templates", ["push-templates"])

        assert "dead_template_lane_20260827" in _out(capsys)

    def test_a_retired_verb_writes_nothing(self, capsys):
        """The whole point: it used to no-op silently, now it no-ops loudly."""
        with patch.object(templates, "push_to_spawn_templates") as pushed:
            templates.handle_command("templates", ["push-templates", "--dry-run"])
        pushed.assert_not_called()


# =============================================================================
# HELP OUTRANKS EVERYTHING
# =============================================================================


class TestHelpNeverPerforms:
    """Asking about a verb must never run it — the push scar, one module over."""

    def test_bare_templates_introspects(self, capsys):
        assert templates.handle_command("templates", []) is True
        assert "PURPOSE" in _out(capsys)

    def test_help_flag_anywhere_wins_over_a_live_verb(self):
        for args in (["spawn-templates", "--help"], ["--help", "spawn-templates"], ["spawn-templates", "help"]):
            with patch.object(templates, "push_to_spawn_templates") as pushed:
                assert templates.handle_command("templates", args) is True
            pushed.assert_not_called()

    def test_help_flag_anywhere_wins_over_the_bump(self):
        """`bump --confirm --help` must not heal 22 branches."""
        for args in (["bump", "--help"], ["bump", "--confirm", "-h"], ["--help", "bump", "--confirm"]):
            with patch.object(template_bump, "on_bump") as bumped:
                assert templates.handle_command("templates", args) is True
            bumped.assert_not_called()

    def test_top_level_help_prints_usage(self, capsys):
        assert templates.handle_command("--help", []) is True
        assert "USAGE" in _out(capsys)

    def test_an_unknown_subcommand_lists_the_real_ones(self, capsys):
        assert templates.handle_command("templates", ["nonsense"]) is True
        printed = _out(capsys)
        assert "spawn-templates" in printed

    def test_an_unrelated_command_is_not_claimed(self):
        assert templates.handle_command("search", ["anything"]) is False


# =============================================================================
# THE LIVE LANES
# =============================================================================


class TestSpawnPropagationSurvives:
    """The half that always worked, under its own name at last."""

    def test_the_verb_runs_the_spawn_pusher(self):
        with patch.object(templates, "push_to_spawn_templates", return_value={"success": True}) as pushed:
            templates.handle_command("templates", ["spawn-templates", "--dry-run"])
        pushed.assert_called_once_with(dry_run=True)

    def test_without_the_flag_it_is_a_real_write(self):
        with patch.object(templates, "push_to_spawn_templates", return_value={"success": True}) as pushed:
            templates.handle_command("templates", ["spawn-templates"])
        pushed.assert_called_once_with(dry_run=False)

    def test_a_crash_is_reported_not_raised(self, capsys):
        with patch.object(templates, "push_to_spawn_templates", side_effect=RuntimeError("boom")):
            assert templates.handle_command("templates", ["spawn-templates"]) is True
        assert "boom" in _out(capsys)

    def test_a_handler_failure_prints_its_errors(self, capsys):
        failed = {"success": False, "errors": ["spawn templates unreadable"]}
        with patch.object(templates, "push_to_spawn_templates", return_value=failed):
            templates.handle_command("templates", ["spawn-templates"])
        assert "unreadable" in _out(capsys)


class TestStatusReadsTheLiveReceipts:
    """The old status read a push log only the retired lane could ever move."""

    def test_status_reports_the_gold_version_and_the_branches(self, capsys):
        templates.handle_command("templates", ["template-status"])
        printed = _out(capsys)

        assert "Gold source" in printed
        assert "Branches" in printed

    def test_status_names_the_bump_state(self, capsys):
        templates.handle_command("templates", ["template-status"])
        assert "ledger" in _out(capsys).lower()

    def test_receipt_status_lists_every_fleet_branch(self):
        from aipass.memory.apps.handlers.monitor import registry_scope

        status = template_bump.receipt_status()

        assert len(status["branches"]) == len(registry_scope.fleet_branches())

    def test_a_branch_with_no_receipt_is_listed_not_omitted(self):
        """Absent is an answer. A missing branch reads as a clean one."""
        rows = template_bump.receipt_status()["branches"]

        assert all("carries" in row for row in rows)
        assert all(row["current"] is False for row in rows if row["carries"] is None)


class TestTheBumpVerb:
    """The CLI over the bump site. The gates live in the handler; this is the door."""

    def test_bump_defaults_to_a_dry_run(self):
        with patch.object(template_bump, "on_bump", return_value={"pending": False, "reason": "x"}) as bumped:
            templates.handle_command("templates", ["bump"])
        bumped.assert_called_once_with(confirm=False)

    def test_confirm_is_the_only_way_to_execute(self):
        with patch.object(template_bump, "on_bump", return_value={"pending": False, "reason": "x"}) as bumped:
            templates.handle_command("templates", ["bump", "--confirm"])
        bumped.assert_called_once_with(confirm=True)

    def test_no_pending_bump_says_so_and_stops(self, capsys):
        with patch.object(template_bump, "on_bump", return_value={"pending": False, "reason": "already current"}):
            templates.handle_command("templates", ["bump"])
        assert "already current" in _out(capsys)

    def test_a_dry_run_tells_the_operator_how_to_finish(self, capsys):
        outcome = {
            "pending": True,
            "was": {"local": "2.0.0"},
            "now": {"local": "3.0.0"},
            "reason": "moved",
            "push": {"success": True, "dry_run": True, "scope": 0, "branches": [], "errors": []},
            "stamped": False,
        }
        with patch.object(template_bump, "on_bump", return_value=outcome):
            templates.handle_command("templates", ["bump"])

        assert "--confirm" in _out(capsys)

    def test_an_unstamped_confirm_is_reported_as_a_failure(self, capsys):
        """Silence here would read as a healed fleet that is still stale."""
        outcome = {
            "pending": True,
            "was": None,
            "now": {"local": "3.0.0"},
            "reason": "no ledger",
            "push": {"success": False, "dry_run": False, "scope": 1, "branches": [], "errors": ["refused"]},
            "stamped": False,
        }
        with patch.object(template_bump, "on_bump", return_value=outcome):
            templates.handle_command("templates", ["bump", "--confirm"])

        printed = _out(capsys)
        assert "NOT stamped" in printed
        assert "still on the old version" in printed

    def test_a_crash_is_reported_not_raised(self, capsys):
        with patch.object(template_bump, "on_bump", side_effect=RuntimeError("bus down")):
            assert templates.handle_command("templates", ["bump"]) is True
        assert "bus down" in _out(capsys)
