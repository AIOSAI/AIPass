# =================== AIPass ====================
# Name: test_codex_bridge.py
# Version: 2.1.0
# Description: Tests for the Codex bridge: stdin normalization, output envelope, apply_patch mapping
# Branch: hooks
# Layer: tests
# Created: 2026-07-10
# Modified: 2026-10-25
# =============================================

"""Tests for apps/handlers/bridges/codex.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that handlers/bridges/codex.py parses and imports its engine and loader
# seedgo: no-test-needed(documentation) — the Codex protocol notes in the bridge's module docstring
# seedgo: no-test-needed(stdlib) — json.loads and json.dumps round-tripping a payload

import io
import json
import os
import sys

import pytest

from aipass.hooks.apps.handlers.bridges import codex
from aipass.hooks.apps.modules import engine


class Bridge:
    """Runs codex.main() as Codex does: argv event, payload on stdin, one JSON document on stdout."""

    def __init__(self, monkeypatch, capsys) -> None:
        self.received: list[str] = []
        self.sessions: list[str | None] = []
        self.answers: dict[str, tuple[str, int]] = {}
        self.default = ("", 0)
        self._monkeypatch = monkeypatch
        self._capsys = capsys
        # The bridge writes os.environ; monkeypatch owning the variable restores it at teardown.
        monkeypatch.setenv(codex.SESSION_ENV, "launcher-session")
        # The edge: mounting serves the promoted copy from disk; the source tree is already imported here.
        monkeypatch.setattr(codex, "_mount", lambda: "test")
        monkeypatch.setattr(engine, "run_event", self._run_event)

    @property
    def calls(self) -> list[dict]:
        return [json.loads(raw) for raw in self.received]

    def _run_event(self, arg: str, stdin_data: str) -> tuple[str, int]:
        self.received.append(stdin_data)
        self.sessions.append(os.environ.get(codex.SESSION_ENV))
        parsed = json.loads(stdin_data) if stdin_data.strip().startswith("{") else {}
        return self.answers.get(parsed.get("tool_name", ""), self.default)

    def run(self, event: str, payload: dict | str) -> dict:
        stdin = payload if isinstance(payload, str) else json.dumps(payload)
        self._monkeypatch.setattr(sys, "argv", ["codex.py", event])
        self._monkeypatch.setattr(sys, "stdin", io.StringIO(stdin))
        codex.main()
        return json.loads(self._capsys.readouterr().out)


@pytest.fixture
def bridge(monkeypatch, capsys) -> Bridge:
    return Bridge(monkeypatch, capsys)


def _patch_payload(tmp_path, patch: str) -> dict:
    return {"cwd": str(tmp_path), "tool_name": "apply_patch", "tool_input": {"command": patch}}


def _shell(*words: str) -> str:
    return " ".join(words)


class TestNormalizeStdin:
    def test_remaps_input_to_tool_input(self, bridge, tmp_path):
        file_path = str(tmp_path / "x.py")
        bridge.run("PreToolUse", {"tool_name": "Edit", "input": {"file_path": file_path}})
        assert bridge.calls == [{"tool_name": "Edit", "tool_input": {"file_path": file_path}, "provider": "codex"}]

    def test_preserves_existing_tool_input(self, bridge, tmp_path):
        payload = {"tool_name": "Edit", "tool_input": {"file_path": str(tmp_path / "x.py")}}
        bridge.run("PreToolUse", payload)
        assert bridge.calls == [{**payload, "provider": "codex"}]

    def test_no_clobber_when_both_present(self, bridge):
        bridge.run("PreToolUse", {"tool_input": {"a": 1}, "input": {"b": 2}})
        assert bridge.calls == [{"tool_input": {"a": 1}, "input": {"b": 2}, "provider": "codex"}]

    def test_every_payload_names_codex_as_its_provider(self, bridge):
        bridge.run("SessionStart", {"session_id": "s1", "source": "startup"})
        assert bridge.calls == [{"session_id": "s1", "source": "startup", "provider": "codex"}]

    def test_a_provider_the_payload_already_names_is_kept(self, bridge):
        bridge.run("SessionStart", {"session_id": "s1", "provider": "other"})
        assert bridge.calls[0]["provider"] == "other"

    def test_whitespace_stdin_reaches_the_engine_unchanged(self, bridge):
        bridge.run("Stop", "   ")
        assert bridge.received == ["   "]

    def test_invalid_json_reaches_the_engine_unchanged(self, bridge):
        bridge.run("Stop", "not json")
        assert bridge.received == ["not json"]

    def test_non_dict_json_reaches_the_engine_unchanged(self, bridge):
        bridge.run("Stop", "[1, 2, 3]")
        assert json.loads(bridge.received[0]) == [1, 2, 3]


class TestSession:
    def test_the_codex_session_id_replaces_the_launchers_for_the_engine(self, bridge):
        bridge.run("UserPromptSubmit", {"session_id": "codex-123", "prompt": "hi"})
        assert bridge.sessions == ["codex-123"]

    def test_a_payload_without_a_session_leaves_the_variable_alone(self, bridge):
        bridge.run("UserPromptSubmit", {"prompt": "hi"})
        assert bridge.sessions == ["launcher-session"]


class TestWrapOutput:
    def test_block_wraps_as_deny(self, bridge):
        bridge.default = (json.dumps({"decision": "block", "reason": "git write blocked"}), 2)
        result = bridge.run("PreToolUse", {"tool_name": "Bash"})
        hook_output = result["hookSpecificOutput"]
        assert hook_output["hookEventName"] == "PreToolUse"
        assert hook_output["permissionDecision"] == "deny"
        assert hook_output["permissionDecisionReason"] == "git write blocked"
        assert result["systemMessage"] == "git write blocked"

    def test_block_with_no_reason_uses_default(self, bridge):
        bridge.default = (json.dumps({"decision": "block"}), 2)
        result = bridge.run("PreToolUse", {"tool_name": "Bash"})
        assert result["hookSpecificOutput"]["permissionDecisionReason"] == "Blocked by AIPass hook"

    def test_context_injection(self, bridge):
        bridge.default = ("# Identity\nYou are hooks.", 0)
        result = bridge.run("UserPromptSubmit", {"prompt": "hi"})
        hook_output = result["hookSpecificOutput"]
        assert hook_output["hookEventName"] == "UserPromptSubmit"
        assert hook_output["additionalContext"] == "# Identity\nYou are hooks."
        assert "permissionDecision" not in hook_output

    def test_empty_output_returns_empty_object(self, bridge):
        assert bridge.run("PreToolUse", {"tool_name": "Bash"}) == {}

    def test_exit_2_plain_text_on_pretooluse_is_a_deny_not_context(self, bridge):
        bridge.default = ("crash output", 2)
        result = bridge.run("PreToolUse", {"tool_name": "Bash"})
        assert result["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert result["hookSpecificOutput"]["permissionDecisionReason"] == "crash output"

    def test_exit_2_non_decision_json_on_pretooluse_is_a_deny(self, bridge):
        bridge.default = (json.dumps({"something": "else"}), 2)
        result = bridge.run("PreToolUse", {"tool_name": "Bash"})
        assert result["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert "additionalContext" not in result["hookSpecificOutput"]

    def test_a_json_answer_passes_through_as_claudes_protocol(self, bridge):
        answer = {"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": "lint fixed"}}
        bridge.default = (json.dumps(answer), 0)
        assert bridge.run("PostToolUse", {"tool_name": "Bash", "tool_input": {"command": "ls"}}) == answer

    def test_a_block_on_an_unguarded_event_stays_a_block_not_a_deny(self, bridge):
        block = {"decision": "block", "reason": "seat taken"}
        bridge.default = (json.dumps(block), 2)
        assert bridge.run("UserPromptSubmit", {"prompt": "hi"}) == block


class TestApplyPatchMapping:
    def test_each_file_reaches_the_gates_as_the_claude_call_it_amounts_to(self, bridge, tmp_path):
        patch = (
            "*** Begin Patch\n*** Add File: new.py\n+a = 1\n+b = 2\n"
            "*** Update File: old.py\n@@ def f():\n ctx\n-x = 1\n+x = 2\n@@\n-y\n+z\n"
            "*** Delete File: gone.txt\n*** End Patch"
        )
        assert bridge.run("PreToolUse", _patch_payload(tmp_path, patch)) == {}
        assert [(c["tool_name"], c["tool_input"]) for c in bridge.calls] == [
            ("Write", {"file_path": str(tmp_path / "new.py"), "content": "a = 1\nb = 2\n"}),
            (
                "MultiEdit",
                {
                    "file_path": str(tmp_path / "old.py"),
                    "edits": [
                        {"old_string": "ctx\nx = 1", "new_string": "ctx\nx = 2"},
                        {"old_string": "y", "new_string": "z"},
                    ],
                },
            ),
            ("Bash", {"command": _shell("rm", "--", str(tmp_path / "gone.txt"))}),
        ]
        assert all(c["cwd"] == str(tmp_path) for c in bridge.calls)

    def test_a_move_is_judged_as_the_edit_and_a_shell_move_to_its_destination(self, bridge, tmp_path):
        patch = "*** Begin Patch\n*** Update File: a.py\n*** Move to: b.py\n@@\n-1\n+2\n*** End Patch"
        bridge.run("PreToolUse", _patch_payload(tmp_path, patch))
        assert [c["tool_name"] for c in bridge.calls] == ["MultiEdit", "Bash"]
        expected = _shell("mv", "--", str(tmp_path / "a.py"), str(tmp_path / "b.py"))
        assert bridge.calls[1]["tool_input"]["command"] == expected

    def test_the_first_refused_file_denies_the_patch_and_later_files_are_not_run(self, bridge, tmp_path):
        bridge.answers["Write"] = (json.dumps({"decision": "block", "reason": "new test file refused"}), 2)
        patch = "*** Begin Patch\n*** Add File: t.py\n+x\n*** Update File: o.py\n@@\n-1\n+2\n*** End Patch"
        result = bridge.run("PreToolUse", _patch_payload(tmp_path, patch))
        assert result["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert result["hookSpecificOutput"]["permissionDecisionReason"] == "new test file refused"
        assert [c["tool_name"] for c in bridge.calls] == ["Write"]

    def test_a_patch_naming_no_file_is_denied_unjudged(self, bridge, tmp_path):
        result = bridge.run("PreToolUse", _patch_payload(tmp_path, "*** Begin Patch\n*** End Patch"))
        assert result["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert "apply_patch names no file" in result["hookSpecificOutput"]["permissionDecisionReason"]
        assert bridge.received == []

    def test_a_bash_call_reaches_the_engine_unchanged(self, bridge, tmp_path):
        payload = {"cwd": str(tmp_path), "tool_name": "Bash", "tool_input": {"command": "ls"}}
        bridge.run("PreToolUse", payload)
        assert bridge.calls == [{**payload, "provider": "codex"}]

    def test_per_file_contexts_merge_into_one_document(self, bridge, tmp_path):
        bridge.answers["Write"] = ("lint fixed in new.py", 0)
        bridge.answers["MultiEdit"] = ("lint fixed in old.py", 0)
        patch = "*** Begin Patch\n*** Add File: new.py\n+x\n*** Update File: old.py\n@@\n-1\n+2\n*** End Patch"
        result = bridge.run("PostToolUse", _patch_payload(tmp_path, patch))
        assert result["hookSpecificOutput"]["additionalContext"] == "lint fixed in new.py\nlint fixed in old.py"
