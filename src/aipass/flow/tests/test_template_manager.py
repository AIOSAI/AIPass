# =================== AIPass ====================
# Name: test_template_manager.py
# Description: Unit tests for apps/modules/template_manager.py
# Version: 1.0.0
# Created: 2026-03-24
# Modified: 2026-09-27
# =============================================

"""Tests for apps/modules/template_manager.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that template_manager.py parses and imports
# seedgo: no-test-needed(constant) — print_introspection's and print_help's literal banner text

import pytest
from unittest.mock import patch

from aipass.flow.apps.modules.template_manager import handle_command

# ---------------------------------------------------------------------------
# Module-level patch targets (patch where used, not where defined)
# ---------------------------------------------------------------------------

_MOD = "aipass.flow.apps.modules.template_manager"


# ---------------------------------------------------------------------------
# _suggest_prefix pure-function tests
# ---------------------------------------------------------------------------


def _scan_suggestion(dir_name: str, capsys: pytest.CaptureFixture[str]) -> str:
    """Run `scan` over one unregistered dir and return what it printed to stdout.

    The suggested prefix is only ever shown to a user as the register command
    `scan` prints, so that line is where these tests read it.
    """
    with (
        patch(f"{_MOD}.scan_unregistered", return_value=[{"dir_name": dir_name, "template_count": 1}]),
        patch(f"{_MOD}.json_handler", spec=True),
    ):
        assert handle_command("scan", []) is True
    out, _err = capsys.readouterr()
    return out


class TestSuggestPrefix:
    """Verify scan suggests the correct prefix for each unregistered dir."""

    def test_testing_gives_tplan(self, capsys: pytest.CaptureFixture[str]):
        """'testing' -> 'TPLAN'.

        Mutant: first_word[0].upper() + "PLAN" -> first_word[0] + "PLAN" reddens this.
        """
        assert "drone @flow register testing TPLAN\n" in _scan_suggestion("testing", capsys)

    def test_skills_plans_gives_splan(self, capsys: pytest.CaptureFixture[str]):
        """'skills_plans' -> 'SPLAN' (first word before underscore).

        Mutant: dir_name.split("_")[0] -> dir_name.split("_")[-1] reddens this.
        """
        assert "drone @flow register skills_plans SPLAN\n" in _scan_suggestion("skills_plans", capsys)

    def test_dev_plans_gives_dplan(self, capsys: pytest.CaptureFixture[str]):
        """'dev_plans' -> 'DPLAN'.

        Mutant: dir_name.split("_")[0] -> dir_name.split("_")[-1] reddens this.
        """
        assert "drone @flow register dev_plans DPLAN\n" in _scan_suggestion("dev_plans", capsys)

    def test_empty_string_returns_xplan(self, capsys: pytest.CaptureFixture[str]):
        """Empty string edge case should return 'XPLAN' fallback.

        Mutant: if first_word else "XPLAN" -> if first_word else "PLAN" reddens this.
        """
        assert "drone @flow register  XPLAN\n" in _scan_suggestion("", capsys)

    def test_single_char_dir(self, capsys: pytest.CaptureFixture[str]):
        """Single character directory name should work.

        Mutant: first_word[0].upper() + "PLAN" -> first_word[0] + "PLAN" reddens this.
        """
        assert "drone @flow register a APLAN\n" in _scan_suggestion("a", capsys)

    def test_uppercase_input(self, capsys: pytest.CaptureFixture[str]):
        """Uppercase input first letter stays uppercase.

        Mutant: first_word[0].upper() + "PLAN" -> first_word[0].lower() + "PLAN" reddens this.
        """
        assert "drone @flow register Flow FPLAN\n" in _scan_suggestion("Flow", capsys)


# ---------------------------------------------------------------------------
# handle_command routing tests
# ---------------------------------------------------------------------------


class TestHandleCommandRouting:
    """Verify handle_command routes to the correct function for each input."""

    def test_no_args_calls_introspection(self):
        """templates with no args shows introspection."""
        with patch(f"{_MOD}.print_introspection") as mock_intro:
            result = handle_command("templates", [])

            mock_intro.assert_called_once()
            assert result is True

    def test_unknown_command_no_args_returns_false(self):
        """Non-template commands with no args are not claimed."""
        result = handle_command("post", [])
        assert result is False

    @pytest.mark.parametrize("verb", ["templates", "register", "unregister", "scan"])
    @pytest.mark.parametrize("help_flag", ["--help", "-h", "help"])
    def test_every_verb_answers_help_before_reading_arguments(self, verb: str, help_flag: str):
        """Help is answered for all four verbs, not just `templates`.

        The gate moved into handle_command (2026-09-07) so one place answers
        help for every verb; this pins the whole surface rather than the one
        verb that used to be covered. Without it, `unregister --help` reaches
        remove_type() with '--help' as the type name.
        """
        with patch(f"{_MOD}.print_help") as mock_help:
            result = handle_command(verb, [help_flag])

            mock_help.assert_called_once()
            assert result is True

    def test_help_does_not_make_this_module_claim_a_command_it_does_not_own(self):
        """A shared gate must stay scoped -- `frobnicate --help` is not ours.

        A gate written as `if wants_help(args)` with no verb check would answer
        help for every command in the fleet and stop routing dead.
        """
        with patch(f"{_MOD}.print_help") as mock_help:
            assert handle_command("frobnicate", ["--help"]) is False
            mock_help.assert_not_called()

    def test_templates_list_loads_registry_and_displays(self):
        """'templates list' should load registry and display types."""
        mock_registry = {"types": {"flow_plans": {"prefix": "FPLAN"}}}

        with (
            patch(f"{_MOD}.load_registry", return_value=mock_registry, autospec=True) as mock_lr,
            patch(f"{_MOD}._display_registered_types") as mock_display,
        ):
            result = handle_command("templates", [])

            mock_lr.assert_called_once()
            mock_display.assert_called_once_with(mock_registry)
            assert result is True

    # ---- register command ----

    def test_register_no_args_shows_error(self, capsys: pytest.CaptureFixture[str]):
        """'register' with insufficient args should show usage error.

        Mutant: [dim]Example: drone @flow register testing TPLAN -> [dim]Example: drone @flow register reddens this.
        """
        with patch(f"{_MOD}.error") as mock_error:
            # Note: empty args triggers introspection gate first,
            # so we pass one arg to get past introspection but still < 2
            result = handle_command("register", ["testing"])

            mock_error.assert_called_once()
            assert mock_error.call_args[0][0].startswith("Usage:")
            assert result is True
        out, _err = capsys.readouterr()
        assert "Example: drone @flow register testing TPLAN" in out

    def test_register_valid_calls_add_type(self, capsys: pytest.CaptureFixture[str]):
        """'register testing TPLAN' should call add_type.

        Mutant: "subject" {prefix.lower()} -> "subject" {prefix} reddens this.
        """
        with (
            patch(f"{_MOD}.add_type", return_value=True) as mock_add,
            patch(f"{_MOD}.success") as mock_success,
            patch(f"{_MOD}.json_handler", spec=True),
        ):
            result = handle_command("register", ["testing", "TPLAN"])

            mock_add.assert_called_once_with("testing", "TPLAN")
            mock_success.assert_called_once()
            assert result is True
        out, _err = capsys.readouterr()
        assert 'Create plans with: drone @flow create . "subject" tplan' in out

    def test_register_add_type_failure(self, capsys: pytest.CaptureFixture[str]):
        """add_type returning False should show error message.

        Mutant: console.print() after the register failure -> console.print(f"Create plans with {prefix}") reddens this.
        """
        with (
            patch(f"{_MOD}.add_type", return_value=False) as mock_add,
            patch(f"{_MOD}.error") as mock_error,
            patch(f"{_MOD}.json_handler", spec=True),
        ):
            result = handle_command("register", ["testing", "TPLAN"])

            mock_add.assert_called_once_with("testing", "TPLAN")
            mock_error.assert_called_once()
            assert mock_error.call_args[0][0].startswith("Failed")
            assert result is True
        out, _err = capsys.readouterr()
        # A failed register must not tell the user how to create plans of the type.
        assert "Create plans with" not in out

    def test_register_invalid_prefix_not_uppercase(self, capsys: pytest.CaptureFixture[str]):
        """Prefix that is not uppercase should be rejected.

        Mutant: "[dim]Convention: first letter -> "[dim]Convention: 1st letter reddens this.
        """
        with patch(f"{_MOD}.error") as mock_error:
            result = handle_command("register", ["testing", "bad"])

            mock_error.assert_called_once()
            assert mock_error.call_args[0][0].startswith("PREFIX")
            assert result is True
        out, _err = capsys.readouterr()
        assert "Convention: first letter of dir + 'PLAN' (e.g., testing -> TPLAN)" in out

    def test_register_invalid_prefix_no_plan_suffix(self, capsys: pytest.CaptureFixture[str]):
        """Prefix that doesn't end with PLAN should be rejected.

        Mutant: "[dim]Convention: first letter -> "[dim]Convention: 1st letter reddens this.
        """
        with patch(f"{_MOD}.error") as mock_error:
            result = handle_command("register", ["testing", "TFIX"])

            mock_error.assert_called_once()
            assert mock_error.call_args[0][0].startswith("PREFIX")
            assert result is True
        out, _err = capsys.readouterr()
        assert "Convention: first letter of dir + 'PLAN' (e.g., testing -> TPLAN)" in out

    # ---- unregister command ----

    def test_unregister_no_args_shows_error(self):
        """'unregister' with no dir arg should show usage error."""
        with patch(f"{_MOD}.error") as mock_error:
            result = handle_command("unregister", [])

            mock_error.assert_called_once()
            assert result is True

    def test_unregister_valid_calls_remove_type(self, capsys: pytest.CaptureFixture[str]):
        """'unregister testing' should call remove_type.

        Mutant: console.print() after the unregister success -> console.print("x") reddens this.
        """
        with (
            patch(f"{_MOD}.remove_type", return_value=True) as mock_rm,
            patch(f"{_MOD}.success") as mock_success,
            patch(f"{_MOD}.json_handler", spec=True),
        ):
            result = handle_command("unregister", ["testing"])

            mock_rm.assert_called_once_with("testing")
            mock_success.assert_called_once_with("Unregistered 'testing'")
            assert result is True
        out, _err = capsys.readouterr()
        # The console adds only a spacer line after the success message.
        assert out == "\n"

    def test_unregister_failure_shows_error(self, capsys: pytest.CaptureFixture[str]):
        """remove_type returning False should show error.

        Mutant: console.print() after the unregister failure -> console.print(dir_name) reddens this.
        """
        with (
            patch(f"{_MOD}.remove_type", return_value=False) as mock_rm,
            patch(f"{_MOD}.error") as mock_error,
            patch(f"{_MOD}.json_handler", spec=True),
        ):
            result = handle_command("unregister", ["testing"])

            mock_rm.assert_called_once_with("testing")
            mock_error.assert_called_once()
            assert mock_error.call_args[0][0].startswith("Failed")
            assert result is True
        out, _err = capsys.readouterr()
        assert out == "\n"

    # ---- scan command ----

    def test_scan_no_unregistered_dirs(self, capsys: pytest.CaptureFixture[str]):
        """scan with all dirs registered should show success message.

        Mutant: console.print("[green]All template directories are registered.[/green]") -> pass reddens this.
        """
        with (
            patch(f"{_MOD}.scan_unregistered", return_value=[]) as mock_scan,
            patch(f"{_MOD}.json_handler", spec=True),
        ):
            result = handle_command("scan", [])

            mock_scan.assert_called_once()
            assert result is True
        out, _err = capsys.readouterr()
        assert "All template directories are registered." in out

    def test_scan_with_unregistered_dirs(self, capsys: pytest.CaptureFixture[str]):
        """scan finding unregistered dirs should list them with suggestions.

        Mutant: ({template_count} template(s)) -> ({dir_name} template(s)) reddens this.
        """
        unregistered = [
            {"dir_name": "testing", "template_count": 2},
            {"dir_name": "skills_plans", "template_count": 1},
        ]

        with (
            patch(f"{_MOD}.scan_unregistered", return_value=unregistered) as mock_scan,
            patch(f"{_MOD}.warning") as mock_warn,
            patch(f"{_MOD}.json_handler", spec=True),
        ):
            result = handle_command("scan", [])

            mock_scan.assert_called_once()
            mock_warn.assert_called_once()
            assert "2" in mock_warn.call_args[0][0]  # "Found 2 unregistered..."
            assert result is True
        out, _err = capsys.readouterr()
        # Should print suggested registration commands
        assert "testing/  (2 template(s))" in out
        assert "drone @flow register testing TPLAN" in out
        assert "skills_plans/  (1 template(s))" in out
        assert "drone @flow register skills_plans SPLAN" in out

    # ---- unknown command ----

    def test_unknown_command_returns_false(self):
        """Unrecognized command should return False."""
        result = handle_command("frobnicate", ["something"])

        assert result is False

    def test_json_handler_called_on_templates_list(self):
        """json_handler.log_operation should be called for templates command."""
        mock_registry = {"types": {}}

        with (
            patch(f"{_MOD}.load_registry", return_value=mock_registry, autospec=True),
            patch(f"{_MOD}._display_registered_types"),
            patch(f"{_MOD}.json_handler", spec=True) as mock_jh,
        ):
            result = handle_command("templates", [])

            assert result is True  # Command was handled
            mock_jh.log_operation.assert_called_once_with(
                "templates_listed",
                {"command": "templates", "args": []},
            )

    def test_json_handler_called_on_scan(self):
        """json_handler.log_operation should be called for scan command."""
        with (
            patch(f"{_MOD}.scan_unregistered", return_value=[]),
            patch(f"{_MOD}.json_handler", spec=True) as mock_jh,
        ):
            result = handle_command("scan", [])

            assert result is True  # Command was handled
            mock_jh.log_operation.assert_called_once_with(
                "templates_scanned",
                {"command": "scan"},
            )
