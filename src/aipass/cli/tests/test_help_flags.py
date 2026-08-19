"""Tests for the whole-sequence help-flag predicate (help_flag_safety)."""

import pytest

from aipass.cli.apps.handlers.cli.help_flags import wants_help


class TestDashedFlagsAnywhere:
    """A dashed help flag at ANY position means explain, never execute."""

    @pytest.mark.parametrize(
        "args",
        [
            ["--help"],
            ["-h"],
            ["demo", "--help"],
            ["demo", "-h"],
            ["demo", "extra", "--help"],
            ["a", "b", "c", "d", "-h"],
        ],
    )
    def test_dashed_flag_detected(self, args):
        assert wants_help(None, args) is True

    def test_flag_in_command_slot_detected(self):
        assert wants_help("--help", []) is True

    def test_flag_after_command_slot_detected(self):
        """The bug this predicate exists for: flag trails a real subcommand."""
        assert wants_help("display", ["demo", "--help"]) is True


class TestBareHelpWord:
    """Bare `help` counts at position 0 only — later it may be a real value."""

    def test_bare_help_at_position_zero(self):
        assert wants_help(None, ["help"]) is True

    def test_bare_help_later_is_a_value(self):
        assert wants_help(None, ["demo", "help"]) is False

    def test_bare_help_disabled_when_help_is_a_verb(self):
        assert wants_help(None, ["help"], bare_help=False) is False

    def test_dashed_still_catches_when_bare_disabled(self):
        assert wants_help(None, ["help", "--help"], bare_help=False) is True


class TestNonHelpInvocations:
    """Real work must not be mistaken for a question."""

    @pytest.mark.parametrize(
        "args",
        [
            [],
            ["demo"],
            ["show"],
            ["helper"],
            ["--helpful"],
        ],
    )
    def test_not_help(self, args):
        assert wants_help(None, args) is False

    def test_empty_everything(self):
        assert wants_help(None, None) is False

    def test_command_only_no_args(self):
        assert wants_help("display", None) is False

    def test_returns_bool(self):
        """Return-type contract — callers gate on identity (`is True`)."""
        assert isinstance(wants_help(None, ["--help"]), bool)
        assert isinstance(wants_help(None, ["demo"]), bool)
