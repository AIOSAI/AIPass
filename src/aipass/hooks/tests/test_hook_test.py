"""Tests for the portable hook test runner (modules/hook_test.py)."""

from unittest.mock import patch

from aipass.hooks.apps.modules import hook_test

_MOD = "aipass.hooks.apps.modules.hook_test"


class TestRunTest:
    def test_no_config_returns_error(self):
        with (
            patch(f"{_MOD}.find_project_config", return_value=None),
            patch(
                f"{_MOD}.config_unavailable_reason",
                return_value="No .aipass/hooks.json found — run from an AIPass project directory.",
            ),
        ):
            result = hook_test.run_test()
        assert "error" in result
        assert "hooks.json" in result["error"]

    def test_no_config_error_reports_the_real_refusal(self):
        """Not-enrolled must not be reported as file-not-found — the CLI echoes
        whatever the loader says refused it, verbatim."""
        truth = "/proj/.aipass/hooks.json exists, but this project is not enrolled...\nFix: aipass trust /proj"
        with (
            patch(f"{_MOD}.find_project_config", return_value=None),
            patch(f"{_MOD}.config_unavailable_reason", return_value=truth),
        ):
            result = hook_test.run_test()
        assert result["error"] == truth
        assert "No .aipass/hooks.json found" not in result["error"]

    def test_hooks_disabled_returns_error(self):
        with patch(f"{_MOD}.find_project_config", return_value={"hooks_enabled": False}):
            result = hook_test.run_test()
        assert "error" in result
        assert "hooks_enabled" in result["error"]

    def test_fires_enabled_hooks(self):
        config = {
            "hooks_enabled": True,
            "PreToolUse": {
                "test_hook": {
                    "enabled": True,
                    "handler": "aipass.hooks.apps.handlers.security.git_gate.handle",
                    "matcher": "Bash|Edit",
                },
            },
        }
        with patch(f"{_MOD}.find_project_config", return_value=config):
            result = hook_test.run_test()
        assert "PreToolUse" in result
        assert len(result["PreToolUse"]) == 1
        assert result["PreToolUse"][0]["hook"] == "test_hook"

    def test_skips_non_dict_entries(self):
        config = {
            "hooks_enabled": True,
            "_comment": "template config",
        }
        with patch(f"{_MOD}.find_project_config", return_value=config):
            result = hook_test.run_test()
        assert result == {}

    def test_skips_hooks_without_handler(self):
        config = {
            "hooks_enabled": True,
            "PreToolUse": {
                "empty_hook": {"enabled": True},
            },
        }
        with patch(f"{_MOD}.find_project_config", return_value=config):
            result = hook_test.run_test()
        assert result == {}

    def test_reports_crashed_hooks(self):
        config = {
            "hooks_enabled": True,
            "PreToolUse": {
                "bad_hook": {
                    "enabled": True,
                    "handler": "nonexistent.module.handle",
                    "matcher": "",
                },
            },
        }
        with patch(f"{_MOD}.find_project_config", return_value=config):
            result = hook_test.run_test()
        assert "PreToolUse" in result
        assert result["PreToolUse"][0]["status"] in ("crashed", "fired (empty output)")


class TestPrintResults:
    def test_error_result_prints(self):
        with patch.object(hook_test.CONSOLE, "print") as mock_print:
            hook_test.print_results({"error": "No config found"})
        mock_print.assert_called_once()

    def test_normal_results_print_summary(self):
        results = {
            "PreToolUse": [
                {"hook": "git_gate", "status": "fired", "elapsed_ms": 5.0},
                {"hook": "rm_gate", "status": "blocked", "elapsed_ms": 3.0},
            ],
        }
        calls = []
        with patch.object(hook_test.CONSOLE, "print", side_effect=lambda x="": calls.append(x)):
            hook_test.print_results(results)
        summary = [c for c in calls if "Summary" in str(c)]
        assert len(summary) == 1
        assert "1 fired" in summary[0]
        assert "1 blocked" in summary[0]


class TestHandleCommand:
    def test_rejects_non_test_command(self):
        assert hook_test.handle_command("status", []) is False

    def test_no_args_shows_introspection(self):
        with patch.object(hook_test, "print_introspection") as mock_intro:
            result = hook_test.handle_command("test", [])
        assert result is True
        mock_intro.assert_called_once()

    def test_runs_test_with_run_arg(self):
        with (
            patch.object(hook_test, "run_test", return_value={}) as mock_run,
            patch.object(hook_test, "print_results"),
            patch.object(hook_test.CONSOLE, "print"),
        ):
            result = hook_test.handle_command("test", ["run"])
        assert result is True
        mock_run.assert_called_once()
