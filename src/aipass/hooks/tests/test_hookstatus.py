# =================== AIPass ====================
# Name: test_hookstatus.py
# Version: 1.1.0
# Description: Tests for hookstatus module (drone @hooks status)
# Branch: hooks
# Created: 2026-05-28
# Modified: 2026-11-21
# =============================================

"""Tests for apps/modules/hookstatus.py — read-only hook config viewer."""

# The declared pass — what is NOT tested here, and what covers it instead:
# sentry: no-test-needed(constant) — HELP_COMMANDS and the help screen's fixed lines
# sentry: no-test-needed(constant) — EVENT_TYPES, the fixed order the status table walks

from unittest.mock import patch

import pytest

from aipass.hooks.apps import hooks
from aipass.hooks.apps.modules import hookstatus
from aipass.hooks.apps.modules.hookstatus import handle_command, print_introspection

SAMPLE_CONFIG = {
    "hooks_enabled": True,
    "UserPromptSubmit": {
        "identity_injector": {"enabled": True, "handler": "x.handle", "matcher": ""},
        "branch_prompt": {"enabled": False, "handler": "y.handle", "matcher": ""},
    },
    "PreToolUse": {
        "tool_sound": {"enabled": True, "handler": "z.handle", "matcher": "Bash|Edit"},
        "edit_gate": {"enabled": True, "handler": "w.handle", "matcher": "Edit|Write"},
    },
    "Stop": {
        "stop_sound": {"enabled": False, "handler": "s.handle", "matcher": ""},
    },
}

MASTER_OFF_CONFIG = {
    "hooks_enabled": False,
    "UserPromptSubmit": {
        "identity_injector": {"enabled": True, "handler": "x.handle", "matcher": ""},
    },
}


def _status_of(config: dict) -> None:
    """Render through the door (fleet green leg 8): `status` with find_project_config answering *config*."""
    with patch("aipass.hooks.apps.modules.hookstatus.find_project_config", return_value=config):
        assert handle_command("status", []) is True


class TestHandleCommand:
    """Command routing tests."""

    def test_returns_false_for_unknown_command(self):
        """Non-status commands return False for routing."""

        assert handle_command("unknown", []) is False

    def test_routes_status_command(self, capsys):
        """Status command is handled: the config it found is rendered."""

        with patch(
            "aipass.hooks.apps.modules.hookstatus.find_project_config",
            return_value=SAMPLE_CONFIG,
        ):
            assert handle_command("status", []) is True

        assert "3 enabled / 5 total" in capsys.readouterr().err

    def test_help_flag(self, capsys):
        """--help flag is handled: the help screen prints."""

        assert handle_command("status", ["--help"]) is True
        assert "drone @hooks status --help    Show this help" in capsys.readouterr().err

    def test_help_short_flag(self, capsys):
        """-h flag is handled: the help screen prints."""

        assert handle_command("status", ["-h"]) is True
        assert "drone @hooks status --help    Show this help" in capsys.readouterr().err

    def test_help_word(self, capsys):
        """help subcommand is handled: the help screen prints."""

        assert handle_command("status", ["help"]) is True
        assert "drone @hooks status --help    Show this help" in capsys.readouterr().err


class TestConfigPresent:
    """Tests with a valid config file found."""

    def test_shows_enabled_and_disabled_hooks(self, capsys):
        """Verify mixed enabled/disabled hooks both render."""

        with patch(
            "aipass.hooks.apps.modules.hookstatus.find_project_config",
            return_value=SAMPLE_CONFIG,
        ):
            result = handle_command("status", [])

        assert result is True
        err = capsys.readouterr().err
        assert "identity_injector" in err
        assert "branch_prompt" in err

    def test_counts_enabled_total(self, capsys):
        """Verify footer shows correct enabled/total counts."""

        _status_of(SAMPLE_CONFIG)

        output = capsys.readouterr().err
        assert "3 enabled / 5 total" in output

    def test_shows_matcher(self, capsys):
        """Verify matcher values appear in output."""

        _status_of(SAMPLE_CONFIG)

        output = capsys.readouterr().err
        assert "Bash|Edit" in output

    def test_shows_event_group_headers(self, capsys):
        """Verify event type section headers appear."""

        _status_of(SAMPLE_CONFIG)

        output = capsys.readouterr().err
        assert "UserPromptSubmit" in output
        assert "PreToolUse" in output
        assert "Stop" in output


class TestConfigAbsent:
    """Tests when no config is loaded — for any of the loader's refusals."""

    def test_no_config_shows_message(self, capsys):
        """Verify a genuinely missing config still says exactly that."""

        with (
            patch(
                "aipass.hooks.apps.modules.hookstatus.find_project_config",
                return_value=None,
            ),
            patch(
                "aipass.hooks.apps.modules.hookstatus.config_unavailable_reason",
                return_value="No .aipass/hooks.json found — run from an AIPass project directory.",
            ),
        ):
            with pytest.raises(SystemExit) as exit_info:
                handle_command("status", [])

        # Rewritten 2026-09-07 (canary refusal sweep): this asserted `is True`,
        # i.e. exit 0, for a command that rendered no status at all.
        assert exit_info.value.code == 1
        assert "No .aipass/hooks.json found" in capsys.readouterr().err

    def test_untrusted_config_reports_the_real_refusal(self, capsys):
        """Present-but-unenrolled must not be rendered as file-not-found."""

        with (
            patch(
                "aipass.hooks.apps.modules.hookstatus.find_project_config",
                return_value=None,
            ),
            patch(
                "aipass.hooks.apps.modules.hookstatus.config_unavailable_reason",
                return_value="not enrolled in the trust registry\nFix: aipass trust /proj",
            ),
        ):
            with pytest.raises(SystemExit) as exit_info:
                handle_command("status", [])

        # The loudest row of the five: this reason means NO HOOKS RUN HERE, and
        # it exited 0. That is the shape that hid a live trust break for two
        # hours on 2026-09-07 — every surface said so, none said it in an exit code.
        assert exit_info.value.code == 1
        output = capsys.readouterr().err
        assert "not enrolled in the trust registry" in output
        assert "aipass trust /proj" in output
        assert "No .aipass/hooks.json found" not in output


class TestMasterSwitchOff:
    """Tests when hooks_enabled is false."""

    def test_master_off_shows_warning(self, capsys):
        """Verify master switch OFF renders loud warning.

        Plain text loses the bold red that tells OFF from the bold green ON;
        the words that differ ("OFF", "the gates still run" — DPLAN-0356 R1c) are what is pinned.
        """

        _status_of(MASTER_OFF_CONFIG)

        output = capsys.readouterr().err
        assert "OFF" in output
        assert "the gates still run" in output

    def test_master_off_still_counts_hooks(self, capsys):
        """Verify hook counts still shown even with master OFF."""

        _status_of(MASTER_OFF_CONFIG)

        output = capsys.readouterr().err
        assert "1 enabled / 1 total" in output


class TestPrintIntrospection:
    """Module introspection tests."""

    def test_prints_without_error(self, capsys):
        """Introspection names the module and what it is.

        "Runs without raising" was the whole test and it asserted nothing, so
        an introspection that printed nothing at all was green.
        """

        print_introspection()

        assert "hookstatus — Read-only hook config viewer" in capsys.readouterr().err


class TestBareHooksSaysTheConfigIsUnreadable:
    """Chaos finding: with .aipass/hooks.json zero bytes, bare drone @hooks exited 0 with its module list alone."""

    @pytest.fixture
    def broken_home(self, tmp_path):
        (tmp_path / ".aipass").mkdir()
        (tmp_path / ".aipass" / "hooks.json").write_text("", encoding="utf-8")
        with patch("aipass.hooks.apps.handlers.config.loader.aipass_home", return_value=tmp_path):
            yield tmp_path / ".aipass" / "hooks.json"

    def test_bare_hooks_names_the_unreadable_config(self, broken_home, capsys):
        hooks.print_introspection()

        captured = capsys.readouterr()
        said = " ".join((captured.err + captured.out).split())
        assert "HOOKS CONFIG UNREADABLE" in said and str(broken_home) in said
        assert "Discovered Modules" in said, "the map still prints"

    def test_a_readable_config_adds_no_line(self, tmp_path, capsys):
        (tmp_path / ".aipass").mkdir()
        (tmp_path / ".aipass" / "hooks.json").write_text("{}", encoding="utf-8")
        with patch("aipass.hooks.apps.handlers.config.loader.aipass_home", return_value=tmp_path):
            hookstatus.print_config_break()

        assert capsys.readouterr().err == ""
