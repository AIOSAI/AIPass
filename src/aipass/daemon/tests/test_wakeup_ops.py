# =================== AIPass ====================
# Name: test_wakeup_ops.py
# Description: Tests for the wakeup_ops facade module
# Version: 1.1.0
# Created: 2026-04-03
# Modified: 2026-09-27
# =============================================

"""Tests for apps/modules/wakeup_ops.py — the wakeup-ops command and its introspection."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that wakeup_ops.py parses and imports
# seedgo: no-test-needed(constant) — the rich.console fallback, which fires only when aipass.cli is absent

from unittest.mock import MagicMock

from aipass.daemon.apps.modules import wakeup_ops
from aipass.daemon.apps.modules.wakeup_ops import handle_command, print_introspection


# =============================================
# handle_command — routing
# =============================================


class TestHandleCommand:
    """Tests for handle_command routing."""

    def test_wrong_command_returns_false(self, capsys):
        assert handle_command("not-wakeup-ops", []) is False
        assert capsys.readouterr().out == ""

    def test_no_args_shows_introspection(self, capsys):
        result = handle_command("wakeup-ops", [])
        assert result is True
        assert "wakeup_ops Module" in capsys.readouterr().out

    def test_help_flag_shows_introspection(self, capsys):
        assert handle_command("wakeup-ops", ["--help"]) is True
        assert "wakeup_ops Module" in capsys.readouterr().out

    def test_h_flag_shows_introspection(self, capsys):
        assert handle_command("wakeup-ops", ["-h"]) is True
        assert "wakeup_ops Module" in capsys.readouterr().out

    def test_help_word_shows_introspection(self, capsys):
        assert handle_command("wakeup-ops", ["help"]) is True
        assert "wakeup_ops Module" in capsys.readouterr().out

    def test_status_arg_shows_info(self, capsys):
        """Mutant killed: the status banner drops "Wakeup Ops"."""
        assert handle_command("wakeup-ops", ["status"]) is True
        assert "Wakeup Ops" in capsys.readouterr().out

    def test_status_calls_log_operation(self, monkeypatch):
        log_operation = MagicMock()
        monkeypatch.setattr(wakeup_ops.json_handler, "log_operation", log_operation)

        handle_command("wakeup-ops", ["status"])
        log_operation.assert_called_once_with("wakeup_ops_status")

    def test_status_prints_notifications_archived(self, capsys):
        handle_command("wakeup-ops", ["status"])
        assert "Notifications" in capsys.readouterr().out


# =============================================
# print_introspection
# =============================================


class TestPrintIntrospection:
    """Tests for print_introspection output."""

    def test_prints_module_header(self, capsys):
        """Mutant killed: the "wakeup_ops Module" header line is not printed."""
        print_introspection()
        assert "wakeup_ops Module" in capsys.readouterr().out
