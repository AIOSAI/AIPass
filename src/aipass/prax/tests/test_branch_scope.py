#!/usr/bin/env python3
# =================== AIPass ====================
# Name: test_branch_scope.py
# Description: Tests for launch-time branch scoping of Mission Control
# Version: 1.0.0
# Created: 2026-08-11
# Modified: 2026-08-11
# =============================================

"""Tests for apps/handlers/monitoring/branch_scope.py

`drone @prax monitor run seedgo,cli` has always been documented; until now the
branch list was logged and then ignored, so a scoped run showed everything.
These tests pin the parsing and the matching rules that make it real.

Covers:
- parse_scope(): comma/space lists, flags ignored, 'all' escape, dedup + order
- BranchScope.matches_label(): project prefixes, model tags, SUB/agent/TESTS decorators
- BranchScope.matches_event(): branch, caller and command target attribution
- BranchScope.describe() / unknown_names(): truthful banner text + typo detection
"""

from dataclasses import dataclass
from typing import Optional

import pytest

from aipass.prax.apps.handlers.monitoring.branch_scope import (
    BranchScope,
    label_tokens,
    parse_scope,
)


@dataclass
class _Event:
    """Minimal stand-in for MonitoringEvent (only the fields scoping reads)."""

    branch: str = ""
    caller: Optional[str] = None
    action: str = ""
    event_type: str = "log"


# ---------------------------------------------------------------------------
# parse_scope
# ---------------------------------------------------------------------------


class TestParseScope:
    """Turning raw `monitor run` arguments into a scope."""

    def test_no_args_is_unscoped(self):
        """Bare `monitor run` keeps the all-branches behaviour."""
        scope = parse_scope([])
        assert scope.is_scoped is False

    def test_all_keyword_is_unscoped(self):
        """`run all` is the explicit spelling of everything."""
        assert parse_scope(["all"]).is_scoped is False
        assert parse_scope(["ALL"]).is_scoped is False

    def test_comma_list_yields_each_name(self):
        """The documented `seedgo,cli,flow` form."""
        scope = parse_scope(["seedgo,cli,flow"])
        assert scope.is_scoped is True
        assert scope.names == ("SEEDGO", "CLI", "FLOW")

    def test_separate_words_are_accepted(self):
        """A shell-split list (`run seedgo cli`) works like the comma form."""
        assert parse_scope(["seedgo", "cli"]).names == ("SEEDGO", "CLI")

    def test_trailing_comma_and_spaces_ignored(self):
        """`run seedgo, cli` arrives as ['seedgo,', 'cli'] — no empty names."""
        assert parse_scope(["seedgo,", "cli"]).names == ("SEEDGO", "CLI")

    def test_flags_are_not_branch_names(self):
        """--relay/--logs must never become a scope entry."""
        scope = parse_scope(["--relay", "seedgo", "--logs"])
        assert scope.names == ("SEEDGO",)

    def test_flags_only_is_unscoped(self):
        """`run --relay` is still an all-branches run."""
        assert parse_scope(["--relay"]).is_scoped is False

    def test_all_anywhere_wins(self):
        """A list containing 'all' widens back to everything, not a branch named all."""
        assert parse_scope(["seedgo,all"]).is_scoped is False

    def test_duplicates_deduped_order_preserved(self):
        """Requested order drives the banner text; repeats collapse."""
        assert parse_scope(["flow,seedgo,flow"]).names == ("FLOW", "SEEDGO")


# ---------------------------------------------------------------------------
# label matching
# ---------------------------------------------------------------------------


class TestLabelTokens:
    """Display labels carry more than a branch name — tokens strip the extras."""

    def test_plain_branch(self):
        assert label_tokens("PRAX") == {"PRAX"}

    def test_project_prefix_and_model_tag(self):
        """filesystem_handler appends /model to session labels."""
        assert label_tokens("AIPASS/DEVPULSE/opus") == {"AIPASS", "DEVPULSE", "OPUS"}

    def test_subagent_decorators_dropped(self):
        """'SUB' and ' agent' are decorations, not part of the name."""
        assert label_tokens("AIPASS/DEVPULSE SUB agent") == {"AIPASS", "DEVPULSE"}

    def test_external_project_tests_suffix(self):
        assert label_tokens("AIPL/POLYGLOT TESTS") == {"AIPL", "POLYGLOT"}

    def test_empty_label(self):
        assert label_tokens("") == set()


class TestMatchesLabel:
    """A scoped monitor shows the named branches and nothing else."""

    def test_exact_branch(self):
        assert BranchScope(["PRAX"]).matches_label("PRAX") is True

    def test_case_insensitive(self):
        assert BranchScope(["prax"]).matches_label("prax") is True

    def test_other_branch_excluded(self):
        assert BranchScope(["PRAX"]).matches_label("SEEDGO") is False

    def test_session_label_with_model_tag(self):
        """`run devpulse` catches DEVPULSE's Claude session events."""
        assert BranchScope(["DEVPULSE"]).matches_label("AIPASS/DEVPULSE/opus") is True

    def test_subagent_label(self):
        assert BranchScope(["DEVPULSE"]).matches_label("AIPASS/DEVPULSE SUB agent") is True

    def test_partial_name_does_not_match(self):
        """Substring matching would put PRAX events in a 'pra' scope — names are whole."""
        assert BranchScope(["PRA"]).matches_label("PRAX") is False

    def test_unknown_label_excluded_when_scoped(self):
        assert BranchScope(["PRAX"]).matches_label("UNKNOWN") is False

    def test_unscoped_matches_everything(self):
        unscoped = BranchScope([])
        assert unscoped.matches_label("ANYTHING") is True
        assert unscoped.matches_label("") is True


class TestMatchesEvent:
    """Command events name a caller and a target — both count as attribution."""

    def test_branch_field(self):
        assert BranchScope(["FLOW"]).matches_event(_Event(branch="FLOW")) is True

    def test_caller_attribution(self):
        """`devpulse → prax` logs under PRAX; a devpulse scope still wants it."""
        event = _Event(branch="PRAX", caller="DEVPULSE", event_type="command", action="executed:PRAX")
        assert BranchScope(["DEVPULSE"]).matches_event(event) is True

    def test_target_attribution(self):
        """seedgo auditing prax shows in a prax scope."""
        event = _Event(branch="SEEDGO", caller="DEVPULSE", event_type="command", action="executed:prax")
        assert BranchScope(["PRAX"]).matches_event(event) is True

    def test_unrelated_command_excluded(self):
        event = _Event(branch="SEEDGO", caller="DEVPULSE", event_type="command", action="executed:CLI")
        assert BranchScope(["PRAX"]).matches_event(event) is False

    def test_plain_action_is_not_a_target(self):
        """A non-command action ('logged') must not be read as attribution."""
        assert BranchScope(["LOGGED"]).matches_event(_Event(branch="SEEDGO", action="logged")) is False

    def test_event_without_caller_attribute(self):
        """Events built without the optional fields must not raise."""

        class _Bare:
            branch = "PRAX"

        assert BranchScope(["PRAX"]).matches_event(_Bare()) is True
        assert BranchScope(["SEEDGO"]).matches_event(_Bare()) is False

    def test_unscoped_matches_every_event(self):
        assert BranchScope([]).matches_event(_Event(branch="WHATEVER")) is True


# ---------------------------------------------------------------------------
# operator-facing description
# ---------------------------------------------------------------------------


class TestDescribeAndUnknown:
    """The banner must be able to name the scope truthfully."""

    def test_describe_unscoped(self):
        assert BranchScope([]).describe() == "all branches"

    def test_describe_scoped_keeps_order(self):
        assert BranchScope(["DEVPULSE", "SEEDGO"]).describe() == "DEVPULSE, SEEDGO"

    def test_unknown_names_flags_typos(self):
        """A misspelled branch would otherwise show an empty screen with no reason."""
        scope = BranchScope(["DEVPULES", "SEEDGO"])
        assert scope.unknown_names({"DEVPULSE", "SEEDGO", "PRAX"}) == ["DEVPULES"]

    def test_unknown_names_empty_when_all_known(self):
        assert BranchScope(["SEEDGO"]).unknown_names({"SEEDGO"}) == []

    def test_unknown_names_without_registry_claims_nothing(self):
        """An empty known-branch set means we could not check — never cry wolf."""
        assert BranchScope(["SEEDGO"]).unknown_names(set()) == []

    @pytest.mark.parametrize("empty", ["", "   ", ","])
    def test_blank_entries_never_become_names(self, empty):
        assert parse_scope([empty]).is_scoped is False
