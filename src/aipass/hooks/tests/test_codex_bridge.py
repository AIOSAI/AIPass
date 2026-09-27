# =================== AIPass ====================
# Name: test_codex_bridge.py
# Version: 1.0.1
# Description: Tests for the Codex bridge's stdin normalization and output envelope
# Branch: hooks
# Layer: tests
# Created: 2026-07-10
# Modified: 2026-09-27
# =============================================

"""Tests for apps/handlers/bridges/codex.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that handlers/bridges/codex.py parses and imports its engine and loader
# seedgo: no-test-needed(documentation) — the Codex protocol notes in the bridge's module docstring
# seedgo: no-test-needed(stdlib) — json.loads and json.dumps round-tripping a payload

import json

from aipass.hooks.apps.handlers.bridges.codex import _normalize_stdin, _wrap_output


class TestNormalizeStdin:
    def test_remaps_input_to_tool_input(self, tmp_path):
        file_path = str(tmp_path / "x.py")
        stdin = json.dumps({"tool_name": "Edit", "input": {"file_path": file_path}})
        result = json.loads(_normalize_stdin(stdin))
        assert "tool_input" in result
        assert result["tool_input"] == {"file_path": file_path}
        assert "input" not in result

    def test_preserves_existing_tool_input(self, tmp_path):
        file_path = str(tmp_path / "x.py")
        stdin = json.dumps({"tool_name": "Edit", "tool_input": {"file_path": file_path}})
        result = json.loads(_normalize_stdin(stdin))
        assert result["tool_input"] == {"file_path": file_path}

    def test_no_clobber_when_both_present(self):
        stdin = json.dumps({"tool_input": {"a": 1}, "input": {"b": 2}})
        result = json.loads(_normalize_stdin(stdin))
        assert result["tool_input"] == {"a": 1}
        assert "input" in result

    def test_empty_string_passthrough(self):
        assert _normalize_stdin("") == ""
        assert _normalize_stdin("   ") == "   "

    def test_invalid_json_passthrough(self):
        assert _normalize_stdin("not json") == "not json"

    def test_non_dict_json_passthrough(self):
        result = _normalize_stdin("[1, 2, 3]")
        assert json.loads(result) == [1, 2, 3]


class TestWrapOutput:
    def test_block_wraps_as_deny(self):
        block_json = json.dumps({"decision": "block", "reason": "git write blocked"})
        result = json.loads(_wrap_output("PreToolUse", block_json, 2))
        hook_output = result["hookSpecificOutput"]
        assert hook_output["hookEventName"] == "PreToolUse"
        assert hook_output["permissionDecision"] == "deny"
        assert hook_output["permissionDecisionReason"] == "git write blocked"
        assert result["systemMessage"] == "git write blocked"

    def test_block_with_no_reason_uses_default(self):
        block_json = json.dumps({"decision": "block"})
        result = json.loads(_wrap_output("PreToolUse", block_json, 2))
        assert result["hookSpecificOutput"]["permissionDecisionReason"] == "Blocked by AIPass hook"

    def test_context_injection(self):
        result = json.loads(_wrap_output("UserPromptSubmit", "# Identity\nYou are hooks.", 0))
        hook_output = result["hookSpecificOutput"]
        assert hook_output["hookEventName"] == "UserPromptSubmit"
        assert hook_output["additionalContext"] == "# Identity\nYou are hooks."
        assert "permissionDecision" not in hook_output

    def test_empty_output_returns_empty_object(self):
        result = json.loads(_wrap_output("PreToolUse", "", 0))
        assert result == {}

    def test_exit_2_non_block_json_falls_through(self):
        result = json.loads(_wrap_output("PreToolUse", "crash output", 2))
        assert result["hookSpecificOutput"]["additionalContext"] == "crash output"

    def test_exit_2_non_decision_json_falls_through(self):
        non_block = json.dumps({"something": "else"})
        result = json.loads(_wrap_output("PreToolUse", non_block, 2))
        assert "additionalContext" in result["hookSpecificOutput"]
