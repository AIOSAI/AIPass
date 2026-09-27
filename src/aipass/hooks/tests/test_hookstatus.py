# =================== AIPass ====================
# Name: test_hookstatus.py
# Version: 1.0.1
# Description: Tests for hookstatus module (drone @hooks status)
# Branch: hooks
# Created: 2026-05-28
# Modified: 2026-09-27
# =============================================

"""Tests for apps/modules/hookstatus.py — read-only hook config viewer."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(constant) — HELP_COMMANDS and the help screen's fixed lines
# seedgo: no-test-needed(constant) — EVENT_TYPES, the fixed order the status table walks

from unittest.mock import patch

import pytest

from aipass.hooks.apps.modules.hookstatus import _render_status, handle_command, print_introspection

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


class TestHandleCommand:
    """Command routing tests."""

    def test_returns_false_for_unknown_command(self):
        """Non-status commands return False for routing."""

        assert handle_command("unknown", []) is False

    def test_routes_status_command(self):
        """Status command is handled and returns True."""

        with patch(
            "aipass.hooks.apps.modules.hookstatus.find_project_config",
            return_value=SAMPLE_CONFIG,
        ):
            assert handle_command("status", []) is True

    def test_help_flag(self):
        """--help flag is handled."""

        assert handle_command("status", ["--help"]) is True

    def test_help_short_flag(self):
        """-h flag is handled."""

        assert handle_command("status", ["-h"]) is True

    def test_help_word(self):
        """help subcommand is handled."""

        assert handle_command("status", ["help"]) is True


class TestConfigPresent:
    """Tests with a valid config file found."""

    def test_shows_enabled_and_disabled_hooks(self):
        """Verify mixed enabled/disabled hooks render without error."""

        with patch(
            "aipass.hooks.apps.modules.hookstatus.find_project_config",
            return_value=SAMPLE_CONFIG,
        ):
            result = handle_command("status", [])

        assert result is True

    def test_counts_enabled_total(self):
        """Verify footer shows correct enabled/total counts."""
        from io import StringIO
        from rich.console import Console

        buf = StringIO()
        test_console = Console(file=buf, force_terminal=False)

        with patch("aipass.hooks.apps.modules.hookstatus.CONSOLE", test_console):
            _render_status(SAMPLE_CONFIG)

        output = buf.getvalue()
        assert "3 enabled / 5 total" in output

    def test_shows_matcher(self):
        """Verify matcher values appear in output."""
        from io import StringIO
        from rich.console import Console

        buf = StringIO()
        test_console = Console(file=buf, force_terminal=False)

        with patch("aipass.hooks.apps.modules.hookstatus.CONSOLE", test_console):
            _render_status(SAMPLE_CONFIG)

        output = buf.getvalue()
        assert "Bash|Edit" in output

    def test_shows_event_group_headers(self):
        """Verify event type section headers appear."""
        from io import StringIO
        from rich.console import Console

        buf = StringIO()
        test_console = Console(file=buf, force_terminal=False)

        with patch("aipass.hooks.apps.modules.hookstatus.CONSOLE", test_console):
            _render_status(SAMPLE_CONFIG)

        output = buf.getvalue()
        assert "UserPromptSubmit" in output
        assert "PreToolUse" in output
        assert "Stop" in output


class TestConfigAbsent:
    """Tests when no config is loaded — for any of the loader's refusals."""

    def test_no_config_shows_message(self):
        """Verify a genuinely missing config still says exactly that."""
        from io import StringIO
        from rich.console import Console

        buf = StringIO()
        test_console = Console(file=buf, force_terminal=False)

        with (
            patch(
                "aipass.hooks.apps.modules.hookstatus.find_project_config",
                return_value=None,
            ),
            patch(
                "aipass.hooks.apps.modules.hookstatus.config_unavailable_reason",
                return_value="No .aipass/hooks.json found — run from an AIPass project directory.",
            ),
            patch("aipass.hooks.apps.modules.hookstatus.CONSOLE", test_console),
        ):
            with pytest.raises(SystemExit) as exit_info:
                handle_command("status", [])

        # Rewritten 2026-09-07 (canary refusal sweep): this asserted `is True`,
        # i.e. exit 0, for a command that rendered no status at all.
        assert exit_info.value.code == 1
        assert "No .aipass/hooks.json found" in buf.getvalue()

    def test_untrusted_config_reports_the_real_refusal(self):
        """Present-but-unenrolled must not be rendered as file-not-found."""
        from io import StringIO
        from rich.console import Console

        buf = StringIO()
        test_console = Console(file=buf, force_terminal=False, width=200)

        with (
            patch(
                "aipass.hooks.apps.modules.hookstatus.find_project_config",
                return_value=None,
            ),
            patch(
                "aipass.hooks.apps.modules.hookstatus.config_unavailable_reason",
                return_value="not enrolled in the trust registry\nFix: aipass trust /proj",
            ),
            patch("aipass.hooks.apps.modules.hookstatus.CONSOLE", test_console),
        ):
            with pytest.raises(SystemExit) as exit_info:
                handle_command("status", [])

        # The loudest row of the five: this reason means NO HOOKS RUN HERE, and
        # it exited 0. That is the shape that hid a live trust break for two
        # hours on 2026-09-07 — every surface said so, none said it in an exit code.
        assert exit_info.value.code == 1
        output = buf.getvalue()
        assert "not enrolled in the trust registry" in output
        assert "aipass trust /proj" in output
        assert "No .aipass/hooks.json found" not in output


class TestMasterSwitchOff:
    """Tests when hooks_enabled is false."""

    def test_master_off_shows_warning(self):
        """Verify master switch OFF renders loud warning."""
        from io import StringIO
        from rich.console import Console

        buf = StringIO()
        test_console = Console(file=buf, force_terminal=False)

        with patch("aipass.hooks.apps.modules.hookstatus.CONSOLE", test_console):
            _render_status(MASTER_OFF_CONFIG)

        output = buf.getvalue()
        assert "OFF" in output
        assert "ALL HOOKS DISABLED" in output

    def test_master_off_still_counts_hooks(self):
        """Verify hook counts still shown even with master OFF."""
        from io import StringIO
        from rich.console import Console

        buf = StringIO()
        test_console = Console(file=buf, force_terminal=False)

        with patch("aipass.hooks.apps.modules.hookstatus.CONSOLE", test_console):
            _render_status(MASTER_OFF_CONFIG)

        output = buf.getvalue()
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
