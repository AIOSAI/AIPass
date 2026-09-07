# =================== AIPass ====================
# Name: test_auto_watchdog.py
# Version: 1.0.0
# Description: Tests for auto_watchdog lifecycle handler
# Branch: hooks
# Created: 2026-05-21
# Modified: 2026-05-21
# =============================================

"""Tests for handlers/lifecycle/auto_watchdog.py."""

import json


class TestAutoWatchdogHandler:
    def test_handle_returns_result_dict(self):
        from aipass.hooks.apps.handlers.lifecycle.auto_watchdog import handle

        result = handle({"tool_name": "Bash", "tool_input": {"command": "ls"}})
        assert isinstance(result, dict)
        assert result["stdout"] == ""
        assert result["exit_code"] == 0

    def test_dispatch_detected(self):
        from aipass.hooks.apps.handlers.lifecycle.auto_watchdog import handle

        result = handle(
            {
                "tool_name": "Bash",
                "tool_input": {"command": 'drone @ai_mail dispatch @hooks "Subject" "Body"'},
            }
        )
        assert result["exit_code"] == 0
        parsed = json.loads(result["stdout"])
        assert "additionalContext" in parsed
        assert "AUTO-WATCHDOG" in parsed["additionalContext"]
        assert "Monitor tool" in parsed["additionalContext"]
        assert "NOT Bash run_in_background" in parsed["additionalContext"]
        assert "drone @devpulse watchdog agent @hooks" in parsed["additionalContext"]

    def test_dispatch_extracts_target(self):
        from aipass.hooks.apps.handlers.lifecycle.auto_watchdog import handle

        result = handle(
            {
                "tool_name": "Bash",
                "tool_input": {"command": 'drone @ai_mail dispatch @spawn "Task" "Do it"'},
            }
        )
        parsed = json.loads(result["stdout"])
        assert "drone @devpulse watchdog agent @spawn" in parsed["additionalContext"]

    def test_dispatch_no_target_fallback(self):
        from aipass.hooks.apps.handlers.lifecycle.auto_watchdog import (
            _extract_target,
        )

        assert _extract_target("drone @ai_mail dispatch") == "@<target>"

    def test_skip_non_bash(self):
        from aipass.hooks.apps.handlers.lifecycle.auto_watchdog import handle

        result = handle(
            {
                "tool_name": "Edit",
                "tool_input": {"command": "drone @ai_mail dispatch @hooks"},
            }
        )
        assert result["stdout"] == ""

    def test_skip_when_watchdog_in_command(self):
        from aipass.hooks.apps.handlers.lifecycle.auto_watchdog import handle

        result = handle(
            {
                "tool_name": "Bash",
                "tool_input": {"command": "drone @ai_mail dispatch @hooks && while [ unread_count ]; do sleep 1; done"},
            }
        )
        assert result["stdout"] == ""

    def test_skip_dispatch_wake_without_target(self):
        from aipass.hooks.apps.handlers.lifecycle.auto_watchdog import handle

        result = handle(
            {
                "tool_name": "Bash",
                "tool_input": {"command": "drone @ai_mail dispatch wake"},
            }
        )
        assert result["stdout"] == ""

    def test_normal_bash_no_dispatch(self):
        from aipass.hooks.apps.handlers.lifecycle.auto_watchdog import handle

        result = handle(
            {
                "tool_name": "Bash",
                "tool_input": {"command": "cd /tmp && ls -la"},
            }
        )
        assert result["stdout"] == ""

    def test_empty_hook_data(self):
        from aipass.hooks.apps.handlers.lifecycle.auto_watchdog import handle

        result = handle({})
        assert result["stdout"] == ""
        assert result["exit_code"] == 0
