# =================== AIPass ====================
# Name: test_codex_bridge.py
# Version: 2.14.1
# Description: Tests for Codex, OpenCode and Seed bridges: payload mapping, output envelope, apply_patch, fail closed
# Branch: hooks
# Layer: tests
# Created: 2026-07-10
# Modified: 2026-11-22
# =============================================

"""Tests for bridges/codex.py, opencode.py and its plugin, seed.py, and the Claude bridge's safe mode (safe_mode.py)."""

# The declared pass — what is NOT tested here, and what covers it instead:
# sentry: no-test-needed(ruff) — that handlers/bridges/codex.py parses and imports its engine and loader
# sentry: no-test-needed(documentation) — the Codex protocol notes in the bridge's module docstring
# sentry: no-test-needed(generated) — opencode_plugin.ts inside a real OpenCode server: a live run (Node runs it here)
# sentry: no-test-needed(stdlib) — json.loads and json.dumps round-tripping a payload

import hashlib
import hmac
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from aipass.hooks.apps.handlers.bridges import claude, codex, opencode, safe_mode, seed
from aipass.hooks.apps.handlers.json import json_handler
from aipass.hooks.apps.modules import engine
import aipass.prax as prax


def _prax_down(name: str):
    raise ImportError(f"prax is down: {name}")


def _without_prax():
    """Every name read through prax's door raises ImportError, as an unloadable prax does; the door caches nothing."""
    return patch.object(prax, "__getattr__", _prax_down)


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

    def test_an_ask_on_pretooluse_reaches_codex_as_a_deny_with_its_reason(self, bridge):
        reason = "Provider settings: Write on ~/.codex/config.toml"
        ask = {"hookEventName": "PreToolUse", "permissionDecision": "ask", "permissionDecisionReason": reason}
        bridge.default = (json.dumps({"hookSpecificOutput": ask}), 0)
        answer = bridge.run("PreToolUse", {"tool_name": "Bash", "tool_input": {"command": "ls"}})
        assert answer["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert answer["hookSpecificOutput"]["permissionDecisionReason"] == reason
        assert answer["systemMessage"] == reason

    def test_a_block_on_an_unguarded_event_stays_a_block_not_a_deny(self, bridge):
        block = {"decision": "block", "reason": "seat taken"}
        bridge.default = (json.dumps(block), 2)
        assert bridge.run("UserPromptSubmit", {"prompt": "hi"}) == block


class TestEveryCallLeavesATrailEntry:
    """Each codex bridge call appends one entry to its own json trail, an allow as well as a block."""

    BLOCK: tuple[str, int] = (json.dumps({"decision": "block", "reason": "git write blocked"}), 2)

    @pytest.fixture
    def trail(self, tmp_path, monkeypatch) -> Path:
        monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path))
        return tmp_path / "hooks" / "hooks_json" / "codex_log.json"

    def _allow_then_block(self, bridge) -> tuple[dict, dict]:
        allowed = bridge.run("PreToolUse", {"tool_name": "Bash"})
        bridge.default = self.BLOCK
        return allowed, bridge.run("PreToolUse", {"tool_name": "Bash"})

    def test_an_allow_and_a_block_each_write_their_exit_code(self, bridge, trail: Path):
        self._allow_then_block(bridge)
        entries = json.loads(trail.read_text(encoding="utf-8"))
        assert [(entry["operation"], entry["data"]) for entry in entries] == [
            ("bridge", {"event": "PreToolUse", "exit_code": 0}),
            ("bridge", {"event": "PreToolUse", "exit_code": 2}),
        ]

    def test_a_trail_that_cannot_be_written_changes_no_answer(self, bridge, trail: Path):
        with patch.object(json_handler, "log_operation", return_value=False) as logged:
            allowed, blocked = self._allow_then_block(bridge)
        assert allowed == {}
        assert blocked["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert [call.args[0] for call in logged.call_args_list].count("bridge") == 2
        assert not trail.exists()


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

    def test_a_patch_naming_no_file_is_denied_with_a_reason_at_warning_not_as_a_broken_engine(
        self, bridge, monkeypatch, capsys, tmp_path
    ):
        logged: list[tuple[str, str]] = []
        monkeypatch.setattr(codex, "_log", lambda level, message, *args: logged.append((level, message % args)))
        result = bridge.run("PreToolUse", _patch_payload(tmp_path, "*** Begin Patch\n*** End Patch"))
        reason = result["hookSpecificOutput"]["permissionDecisionReason"]
        assert result["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert "apply_patch names no file" in reason
        assert "HOOKS BROKEN" not in reason + capsys.readouterr().err
        assert [level for level, _ in logged] == ["warning"]
        assert "apply_patch names no file" in logged[0][1]
        assert bridge.received == []

    def test_a_patch_naming_no_file_after_the_tool_ran_adds_nothing(self, bridge, tmp_path):
        assert bridge.run("PostToolUse", _patch_payload(tmp_path, "*** Begin Patch\n*** End Patch")) == {}
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


class TestTheBridgeLogsThroughPrax:
    def test_a_log_line_goes_to_prax_and_never_to_stderr(self, bridge, monkeypatch, capsys, tmp_path):
        logged: list[tuple[str, str]] = []

        class _Spy:
            def warning(self, message, *args):
                logged.append(("warning", message % args))

        with patch("aipass.prax.logger", _Spy()):
            result = bridge.run("PreToolUse", _patch_payload(tmp_path, "*** Begin Patch\n*** End Patch"))
        assert result["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert [level for level, _ in logged] == ["warning"]
        assert "apply_patch names no file" in logged[0][1]
        assert capsys.readouterr().err == ""

    def test_with_prax_down_a_log_line_is_a_broken_engine_refused_not_a_stderr_line(
        self, bridge, monkeypatch, capsys, tmp_path
    ):
        monkeypatch.setattr(codex, "BREAK_LOG", str(tmp_path / "bridge.log"))
        with _without_prax():
            result = bridge.run("PreToolUse", _patch_payload(tmp_path, "*** Begin Patch\n*** End Patch"))
        assert result["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert "HOOKS BROKEN" in result["hookSpecificOutput"]["permissionDecisionReason"]
        assert "prax unavailable" not in capsys.readouterr().err


class TestBrokenEngine:
    def test_with_prax_unimportable_a_broken_engine_still_denies_pretooluse(self, monkeypatch, capsys, tmp_path):
        with _without_prax():
            spec = importlib.util.spec_from_file_location("_codex_bridge_fresh", codex.__file__)
            assert spec is not None and spec.loader is not None
            fresh = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(fresh)

            def _engine_gone():
                raise ImportError("engine gone")

            monkeypatch.setattr(fresh, "_mount", _engine_gone)
            monkeypatch.setattr(fresh, "BREAK_LOG", str(tmp_path / "bridge.log"))
            monkeypatch.setattr(sys, "argv", ["codex.py", "PreToolUse"])
            monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"tool_name": "Bash", "tool_input": {}})))
            fresh.main()
        out, err = capsys.readouterr()
        answer = json.loads(out)["hookSpecificOutput"]
        assert answer["permissionDecision"] == "deny"
        assert "HOOKS BROKEN" in answer["permissionDecisionReason"]
        assert "HOOKS BROKEN" in err
        assert "bridges.codex | ERROR" in (tmp_path / "bridge.log").read_text(encoding="utf-8")

    def test_a_suite_run_break_never_lands_in_the_live_bridge_log(self, monkeypatch, capsys):
        live = Path(codex.LIVE_BREAK_LOG)
        before = live.read_bytes() if live.exists() else b""

        def _engine_gone():
            raise ImportError("engine gone")

        monkeypatch.setattr(codex, "_mount", _engine_gone)
        monkeypatch.setattr(sys, "argv", ["codex.py", "PreToolUse"])
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"tool_name": "Bash", "tool_input": {}})))
        codex.main()
        assert "HOOKS BROKEN" in capsys.readouterr().err, "the break must happen for the pin to mean anything"
        assert (live.read_bytes() if live.exists() else b"") == before, "medic reads that log as a real break"


class OpenCodeBridge:
    """Runs opencode.main() as the aipass.ts plugin does: argv event, payload on stdin, one JSON answer on stdout."""

    def __init__(self, monkeypatch, capsys) -> None:
        self.received: list[dict] = []
        self.sessions: list[str | None] = []
        self.answer = ("", 0)
        self.answers: dict[str, tuple[str, int]] = {}
        self._monkeypatch = monkeypatch
        self._capsys = capsys
        monkeypatch.setenv(opencode.SESSION_ENV, "server-session")
        monkeypatch.setattr(opencode, "_mount", lambda: "test")
        monkeypatch.setattr(engine, "run_event", self._run_event)

    def _run_event(self, arg: str, stdin_data: str) -> tuple[str, int]:
        self.received.append(json.loads(stdin_data))
        self.sessions.append(os.environ.get(opencode.SESSION_ENV))
        return self.answers.get(self.received[-1].get("tool_name", ""), self.answer)

    def run(self, event: str, payload: dict) -> dict:
        self._monkeypatch.setattr(sys, "argv", ["opencode.py", event])
        self._monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
        opencode.main()
        return json.loads(self._capsys.readouterr().out)


@pytest.fixture
def oc(monkeypatch, capsys) -> OpenCodeBridge:
    return OpenCodeBridge(monkeypatch, capsys)


class TestOpenCodeToolMap:
    @pytest.mark.parametrize(
        ("tool", "given", "name", "expected"),
        [
            ("shell", {"command": "ls"}, "Bash", {"command": "ls"}),
            (
                "edit",
                {"path": "a.py", "oldString": "x", "newString": "y", "replaceAll": True},
                "Edit",
                {"file_path": "a.py", "old_string": "x", "new_string": "y", "replace_all": True},
            ),
            ("write", {"path": "a.py", "content": "x"}, "Write", {"file_path": "a.py", "content": "x"}),
            ("read", {"path": "a.py", "offset": 1}, "Read", {"file_path": "a.py", "offset": 1}),
            ("grep", {"pattern": "x", "path": "src"}, "Grep", {"pattern": "x", "path": "src"}),
            ("subagent", {"prompt": "go"}, "Task", {"prompt": "go"}),
            ("question", {"text": "ok?"}, "question", {"text": "ok?"}),
        ],
    )
    def test_each_tool_reaches_the_gates_under_its_claude_name_and_keys(self, oc, tool, given, name, expected):
        oc.run("PreToolUse", {"session_id": "s1", "cwd": "/w", "tool": tool, "input": given})
        sent = oc.received[0]
        assert (sent["tool_name"], sent["tool_input"], sent["provider"], sent["cwd"]) == (
            name,
            expected,
            "opencode",
            "/w",
        )
        assert "tool" not in sent and "input" not in sent

    def test_execute_is_refused_and_never_reaches_the_engine(self, oc):
        answer = oc.run("PreToolUse", {"session_id": "s1", "tool": "execute", "input": {"code": "x"}})
        assert answer == {"deny": opencode.UNGATED}
        assert "shell tool" in answer["deny"]
        assert oc.received == []

    def test_a_patch_into_another_branch_is_judged_per_file_and_the_refused_write_denies_it(self, oc, tmp_path):
        oc.answers["Write"] = (json.dumps({"decision": "block", "reason": "Cross-branch write blocked"}), 2)
        other = tmp_path / "other_branch" / "x.md"
        patch = f"*** Begin Patch\n*** Update File: own.md\n@@\n-a\n+b\n*** Add File: {other}\n+probe\n*** End Patch"
        payload = {"session_id": "s1", "cwd": str(tmp_path), "tool": "patch", "input": {"patchText": patch}}
        assert oc.run("PreToolUse", payload) == {"deny": "Cross-branch write blocked"}
        assert [(c["tool_name"], c["tool_input"]["file_path"], c["provider"]) for c in oc.received] == [
            ("MultiEdit", str(tmp_path / "own.md"), "opencode"),
            ("Write", str(other), "opencode"),
        ]

    def test_a_patch_naming_no_file_is_denied_before_the_engine(self, oc):
        payload = {"session_id": "s1", "cwd": "/w", "tool": "patch", "input": {"patchText": "no header here"}}
        assert oc.run("PreToolUse", payload) == {"deny": codex.UNJUDGED}
        assert oc.received == []

    def test_the_opencode_session_id_replaces_the_servers_for_the_engine(self, oc):
        oc.run("UserPromptSubmit:temporal", {"session_id": "ses_1", "prompt": "hi"})
        assert oc.sessions == ["ses_1"]


class TestOpenCodeAnswer:
    @pytest.mark.parametrize(
        ("event", "output", "code", "reason"),
        [
            ("PreToolUse", json.dumps({"decision": "block", "reason": "not yours"}), 2, "not yours"),
            ("PreToolUse", "plain refusal", 2, "plain refusal"),
            ("PreToolUse", "", 2, "Blocked by AIPass hook"),
            (
                "PreToolUse",
                json.dumps({"hookSpecificOutput": {"permissionDecision": "ask", "permissionDecisionReason": "ask me"}}),
                0,
                "ask me",
            ),
            ("UserPromptSubmit:presence_gate", json.dumps({"decision": "block", "reason": "who?"}), 2, "who?"),
        ],
    )
    def test_a_refusal_in_any_form_is_a_deny_carrying_its_reason(self, oc, event, output, code, reason):
        oc.answer = (output, code)
        assert oc.run(event, {"tool": "shell", "input": {"command": "ls"}}) == {"deny": reason}

    @pytest.mark.parametrize(
        ("output", "expected"),
        [
            ("# Kernel\n", {"context": "# Kernel\n"}),
            (json.dumps({"hookSpecificOutput": {"additionalContext": "navmap"}}), {"context": "navmap"}),
            ("", {}),
            ("{}", {}),
        ],
    )
    def test_context_arrives_as_text_and_silence_as_nothing(self, oc, output, expected):
        oc.answer = (output, 0)
        assert oc.run("UserPromptSubmit:temporal", {"session_id": "s1", "prompt": "hi"}) == expected

    @pytest.mark.parametrize(
        ("hook", "key"),
        [
            ("tier0_kernel", "aipass-kernel"),
            ("navmap", "aipass-navmap"),
            ("branch_prompt", "aipass-branch-prompt"),
            ("identity_injector", "aipass-identity"),
        ],
    )
    def test_grounding_text_is_a_keyed_instruction_entry_that_outlives_a_compaction(self, oc, hook, key):
        oc.answer = ("# Kernel\n", 0)
        assert oc.run(f"UserPromptSubmit:{hook}", {"session_id": "s1", "prompt": "hi", "keeps_entries": True}) == {
            "entry": {"key": key, "value": "# Kernel\n"}
        }

    def test_a_plugin_that_does_not_keep_entries_gets_the_grounding_as_text(self, oc):
        oc.answer = ("# Kernel\n", 0)
        assert oc.run("UserPromptSubmit:tier0_kernel", {"session_id": "s1", "prompt": "hi"}) == {
            "context": "# Kernel\n"
        }

    def test_silent_grounding_and_another_events_text_stay_as_they_are(self, oc):
        assert oc.run("UserPromptSubmit:navmap", {"session_id": "s1", "prompt": "hi", "keeps_entries": True}) == {}
        oc.answer = ("pointer note", 0)
        assert oc.run("SessionStart:session_pointer", {"session_id": "s1", "keeps_entries": True}) == {
            "context": "pointer note"
        }
        assert oc.run("UserPromptSubmit:culture", {"session_id": "s1", "keeps_entries": True}) == {
            "context": "pointer note"
        }

    def test_culture_at_session_start_is_the_aipass_culture_entry(self, oc):
        oc.answer = ("# AIPass - Culture\n", 0)
        assert oc.run("SessionStart:culture", {"session_id": "s1", "source": "startup", "keeps_entries": True}) == {
            "entry": {"key": "aipass-culture", "value": "# AIPass - Culture\n"}
        }
        assert oc.run("SessionStart:culture", {"session_id": "s1", "source": "startup"}) == {
            "context": "# AIPass - Culture\n"
        }


class TestMountOrSource:
    def test_a_missing_promoted_copy_serves_the_source_and_says_so_without_prax(self, monkeypatch, capsys, tmp_path):
        """Prax is not on this path: a bad promote and a broken prax can be one event."""
        monkeypatch.delenv("AIPASS_HOOKS_LIVE", raising=False)
        (tmp_path / ".live-current").write_text(".live-gone", encoding="utf-8")
        (tmp_path / "logs").mkdir()
        bridge_file = tmp_path / "apps" / "handlers" / "bridges" / "codex.py"
        with _without_prax():
            spec = importlib.util.spec_from_file_location("_mount_fresh", Path(codex.__file__).with_name("mount.py"))
            assert spec is not None and spec.loader is not None
            mount = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mount)
            assert mount.mount_or_source(str(bridge_file), "codex") == "source (fallback)"
        err = capsys.readouterr().err
        assert "[hooks:codex] promoted copy unusable, serving the source tree:" in err and "missing" in err
        (line,) = (tmp_path / "logs" / "bridge.log").read_text(encoding="utf-8").splitlines()
        assert " | bridges.codex | ERROR | [hooks:codex] promoted copy unusable" in line


class TestOpenCodeBrokenEngine:
    def test_a_broken_engine_denies_pretooluse_records_it_and_answers_nothing_elsewhere(
        self, monkeypatch, capsys, tmp_path
    ):
        def _engine_gone():
            raise ImportError("engine gone")

        monkeypatch.setattr(opencode, "_mount", _engine_gone)
        monkeypatch.setattr(opencode, "BREAK_LOG", str(tmp_path / "bridge.log"))
        for event, expected in (("PreToolUse", True), ("UserPromptSubmit:temporal", False)):
            monkeypatch.setattr(sys, "argv", ["opencode.py", event])
            monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"tool": "shell", "input": {"command": "ls"}})))
            opencode.main()
            out, err = capsys.readouterr()
            assert ("HOOKS BROKEN" in json.loads(out).get("deny", "")) is expected, event
            assert "HOOKS BROKEN" in err
        assert "bridges.opencode | ERROR" in (tmp_path / "bridge.log").read_text(encoding="utf-8")


# Runs opencode_plugin.ts under Node: @opencode/plugin resolves to a stub, Bun.spawn answers by the row's mode.
_PLUGIN_HARNESS = r"""
import { register } from "node:module"
import { mkdirSync, writeFileSync } from "node:fs"
import { join } from "node:path"
import { pathToFileURL } from "node:url"
const [plugin, home] = process.argv.slice(2)
const stub = "data:text/javascript,export const Plugin = { define: (p) => p }"
const resolver = `export async function resolve(s, c, next) {
  return s === "@opencode/plugin" ? { url: "${stub}", shortCircuit: true } : next(s, c)
}`
register("data:text/javascript," + encodeURIComponent(resolver))
const seen = []
const answers = { deny: '{"deny":"x"}', exit1: "", context: '{"context":"lint fixed"}' }
globalThis.Bun = {
  spawn(argv, opts) {
    const mode = argv.at(-1)
    seen.push({ mode, sync: false, payload: JSON.parse(opts.stdin.toString()) })
    const code = mode === "exit1" ? 1 : 0
    return {
      stdout: new Response(answers[mode]).body,
      stderr: new Response(code ? "boom" : "").body,
      exited: Promise.resolve(code),
    }
  },
  spawnSync(argv, opts) {
    seen.push({ mode: argv.at(-1), sync: true, payload: JSON.parse(opts.stdin.toString()) })
    return { exitCode: 0, stdout: Buffer.from("{}"), stderr: Buffer.from("") }
  },
}
const { default: def } = await import(pathToFileURL(plugin).href)
mkdirSync(join(home, ".claude"), { recursive: true })
mkdirSync(join(home, "src", "aipass", "hooks", "logs"), { recursive: true })
process.env.AIPASS_HOME = home
const results = {}
const cases = [
  ["deny", "PreToolUse", "execute.before"],
  ["exit1", "PreToolUse", "execute.before"],
  ["context", "PostToolUse", "execute.after"],
]
for (const [mode, event, hook] of cases) {
  const rows = [{ event, command: `py bridge ${mode}` }]
  writeFileSync(join(home, ".claude", "provider_manifest.json"), JSON.stringify({ cli: { opencode: { hooks: rows } } }))
  const hooks = {}
  const ctx = {
    location: { directory: home },
    session: { hook: async () => {} },
    tool: { hook: async (name, fn) => { hooks[name] = fn } },
    event: { subscribe: async function* () {} },
  }
  const stop = await def.setup(ctx)
  const ev = {
    tool: "shell",
    sessionID: "s1",
    id: "call_1",
    input: { command: "ls" },
    status: "completed",
    result: { content: [{ type: "text", text: "out" }] },
  }
  try {
    await hooks[hook](ev)
    results[mode] = { threw: false, content: ev.result.content }
  } catch (e) {
    results[mode] = { threw: true, message: String(e.message) }
  }
  stop?.()
}
const stopRows = [{ event: "Stop", command: "py bridge stop" }]
writeFileSync(join(home, ".claude", "provider_manifest.json"),
  JSON.stringify({ cli: { opencode: { hooks: stopRows } } }))
const ended = { type: "session.execution.succeeded", data: { sessionID: "s1" } }
const ctx = {
  location: { directory: home },
  session: { hook: async () => {} },
  tool: { hook: async () => {} },
  event: { subscribe: async function* () { yield ended } },
}
const stop = await def.setup(ctx)
await new Promise((resolve) => setTimeout(resolve, 50))
stop?.()
process.stdout.write(JSON.stringify({ results, seen }) + "\n")
"""


# The plugin started with no AIPASS_HOME: every row would resolve relative to the server's cwd.
_UNSET_HOME_HARNESS = r"""
import { register } from "node:module"
import { pathToFileURL } from "node:url"
const [plugin] = process.argv.slice(2)
const stub = "data:text/javascript,export const Plugin = { define: (p) => p }"
const resolver = `export async function resolve(s, c, next) {
  return s === "@opencode/plugin" ? { url: "${stub}", shortCircuit: true } : next(s, c)
}`
register("data:text/javascript," + encodeURIComponent(resolver))
globalThis.Bun = { spawn() { throw new Error("no row may run") }, spawnSync() { throw new Error("no row may run") } }
const { default: def } = await import(pathToFileURL(plugin).href)
const hooks = {}
await def.setup({
  location: { directory: process.cwd() },
  session: { hook: async () => {} },
  tool: { hook: async (name, fn) => { hooks[name] = fn } },
  event: { subscribe: async function* () {} },
})
let message = ""
try {
  await hooks["execute.before"]({ tool: "shell", sessionID: "s1", id: "c1", input: { command: "ls" } })
} catch (e) {
  message = String(e.message)
}
process.stdout.write(JSON.stringify({ message }) + "\n")
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="the plugin runs under Node; a host without it cannot load it")
class TestOpenCodePlugin:
    def test_with_aipass_home_unset_every_tool_is_refused_and_no_line_lands_elsewhere(self, tmp_path):
        harness = tmp_path / "harness.mjs"
        harness.write_text(_UNSET_HOME_HARNESS, encoding="utf-8")
        stray = tmp_path / "src" / "aipass" / "hooks" / "logs"
        stray.mkdir(parents=True)
        plugin = Path(opencode.__file__).with_name("opencode_plugin.ts")
        env = {k: v for k, v in os.environ.items() if k != "AIPASS_HOME"}
        argv = ["node", "--no-warnings", "--experimental-strip-types", str(harness), str(plugin)]
        done = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", timeout=60, cwd=tmp_path, env=env)
        assert done.returncode == 0, done.stderr
        message = json.loads(done.stdout.splitlines()[-1])["message"]
        assert message.startswith("HOOKS BROKEN") and "AIPASS_HOME is not set" in message
        assert not (stray / "bridge.log").exists(), "a relative path lands the line where medic never reads"
        assert "not in bridge.log: AIPASS_HOME is not set" in done.stderr

    def test_a_deny_or_a_broken_row_throws_before_the_tool_and_a_report_reaches_its_result(self, tmp_path):
        harness = tmp_path / "harness.mjs"
        harness.write_text(_PLUGIN_HARNESS, encoding="utf-8")
        plugin = Path(opencode.__file__).with_name("opencode_plugin.ts")
        argv = [
            "node",
            "--no-warnings",
            "--experimental-strip-types",
            str(harness),
            str(plugin),
            str(tmp_path / "home"),
        ]
        done = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", timeout=60)
        assert done.returncode == 0, done.stderr
        doc = json.loads(done.stdout.splitlines()[-1])
        results = doc["results"]
        assert results["deny"] == {"threw": True, "message": "x"}
        assert results["exit1"]["threw"] is True
        assert (
            results["exit1"]["message"].startswith("HOOKS BROKEN") and "exited 1: boom" in results["exit1"]["message"]
        )
        assert results["context"] == {
            "threw": False,
            "content": [{"type": "text", "text": "out"}, {"type": "text", "text": "lint fixed"}],
        }
        tool_calls = [s for s in doc["seen"] if s["mode"] != "stop"]
        # The memory tripwire pairs a call's PreToolUse snapshot with its PostToolUse check by this id.
        assert [(s["payload"]["tool_use_id"], s["sync"]) for s in tool_calls] == [("call_1", False)] * 3
        # A standalone run exits on idle before an awaited spawn finishes: Stop must run synchronously.
        assert [(s["mode"], s["sync"], s["payload"]["hook_event_name"]) for s in doc["seen"][3:]] == [
            ("stop", True, "Stop")
        ]


class SeedBridge:
    """Runs seed.main() as a Seed head's command row does: argv event, payload on stdin, read stdout, stderr, exit."""

    def __init__(self, monkeypatch, capsys) -> None:
        self.received: list[str] = []
        self.sessions: list[str | None] = []
        self.answer = ("", 0)
        self._monkeypatch = monkeypatch
        self._capsys = capsys
        monkeypatch.setenv(seed.SESSION_ENV, "launcher-session")
        monkeypatch.setattr(seed, "_mount", lambda: "test")
        monkeypatch.setattr(engine, "run_event", self._run_event)

    def _run_event(self, arg: str, stdin_data: str) -> tuple[str, int]:
        self.received.append(stdin_data)
        self.sessions.append(os.environ.get(seed.SESSION_ENV))
        return self.answer

    def run(self, event: str, payload: dict) -> tuple[str, str, int]:
        self._monkeypatch.setattr(sys, "argv", ["seed.py", event])
        self._monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
        code = 0
        try:
            seed.main()
        except SystemExit as exc:
            code = int(exc.code or 0)
        out, err = self._capsys.readouterr()
        return out, err, code


@pytest.fixture
def sd(monkeypatch, capsys) -> SeedBridge:
    return SeedBridge(monkeypatch, capsys)


_SEED_PAYLOAD = {"session_id": "seed-run-1", "cwd": "/agents/a", "provider": "seed", "agent": "a", "prompt": "hi"}


class TestSeedBridge:
    def test_the_payload_reaches_the_engine_unrenamed_under_the_seed_session(self, sd):
        payload = {**_SEED_PAYLOAD, "tool_name": "remember", "tool_input": {"text": "x"}, "tool_use_id": "t1"}
        sd.run("PreToolUse", payload)
        assert [json.loads(raw) for raw in sd.received] == [payload]
        assert sd.sessions == ["seed-run-1"]

    def test_a_payload_naming_no_provider_is_named_seed(self, sd):
        sd.run("Stop", {"session_id": "s"})
        assert json.loads(sd.received[0])["provider"] == "seed"

    def test_a_json_answer_passes_as_is_and_exits_zero(self, sd):
        doc = json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": "ID"}})
        sd.answer = (doc, 0)
        assert sd.run("UserPromptSubmit", _SEED_PAYLOAD) == (doc, "", 0)

    def test_plain_text_becomes_context_on_a_prompt_and_a_message_elsewhere(self, sd):
        sd.answer = ("# Identity", 0)
        out, _, code = sd.run("UserPromptSubmit", _SEED_PAYLOAD)
        assert (json.loads(out)["hookSpecificOutput"]["additionalContext"], code) == ("# Identity", 0)
        out, _, code = sd.run("PostToolUse", _SEED_PAYLOAD)
        assert (json.loads(out), code) == ({"systemMessage": "# Identity"}, 0)

    def test_no_answer_is_empty_stdout(self, sd):
        assert sd.run("Stop", _SEED_PAYLOAD) == ("", "", 0)

    def test_a_block_exits_2_with_its_reason_on_stderr(self, sd):
        block = json.dumps({"decision": "block", "reason": "Raw delete refused"})
        sd.answer = (block, 2)
        assert sd.run("PreToolUse", {**_SEED_PAYLOAD, "tool_name": "Bash"}) == (block, "Raw delete refused\n", 2)


class TestSeedThroughTheRealEngine:
    """A Seed Write from its workspace (in no project) into AIPass was allowed: the bridge exited 0."""

    def test_a_write_into_a_registry_project_exits_2_and_one_into_its_workspace_exits_0(
        self, monkeypatch, capsys, tmp_path
    ):
        real_run_event = engine.run_event
        sd = SeedBridge(monkeypatch, capsys)
        monkeypatch.setattr(engine, "run_event", real_run_event)
        aipass, workspace = tmp_path / "AIPass", tmp_path / "seed_home" / "agents" / "a"
        (aipass / "src" / "aipass" / "devpulse").mkdir(parents=True)
        workspace.mkdir(parents=True)
        rows = [{"name": "devpulse", "path": "src/aipass/devpulse", "owner": True}]
        (aipass / "AIPASS_REGISTRY.json").write_text(json.dumps({"branches": rows}), encoding="utf-8")
        monkeypatch.chdir(workspace)

        def write(target: Path) -> tuple[str, str, int]:
            tool_input = {"file_path": str(target), "content": "x"}
            payload = {**_SEED_PAYLOAD, "cwd": str(workspace), "tool_name": "Write", "tool_input": tool_input}
            return sd.run("PreToolUse", {**payload, "hook_event_name": "PreToolUse", "tool_use_id": "t1"})

        _, err, code = write(aipass / "src" / "aipass" / "devpulse" / "probe.txt")
        assert (code, "a session outside every project cannot write into project 'AIPass'" in err) == (2, True)
        assert write(workspace / "notes.txt")[2] == 0


class TestSeedBrokenEngine:
    def test_a_broken_engine_refuses_pretooluse_with_exit_2_and_records_it(self, sd, monkeypatch, tmp_path):
        def _engine_gone():
            raise ImportError("engine gone")

        monkeypatch.setattr(seed, "_mount", _engine_gone)
        monkeypatch.setattr(seed, "BREAK_LOG", str(tmp_path / "bridge.log"))
        out, err, code = sd.run("PreToolUse", {**_SEED_PAYLOAD, "tool_name": "Bash"})
        assert (out, code) == ("", 2)
        assert err.startswith("HOOKS BROKEN") and "engine gone" in err
        assert "bridges.seed | ERROR" in (tmp_path / "bridge.log").read_text(encoding="utf-8")

    def test_a_broken_engine_answers_nothing_with_exit_0_elsewhere(self, sd, monkeypatch, tmp_path):
        def _engine_gone():
            raise ImportError("engine gone")

        monkeypatch.setattr(seed, "_mount", _engine_gone)
        monkeypatch.setattr(seed, "BREAK_LOG", str(tmp_path / "bridge.log"))
        out, err, code = sd.run("UserPromptSubmit", _SEED_PAYLOAD)
        assert (out, code) == ("", 0)
        assert "HOOKS BROKEN" in err

    def test_a_suite_run_break_never_lands_in_the_live_bridge_log(self, sd, monkeypatch):
        live = Path(seed.LIVE_BREAK_LOG)
        before = live.read_bytes() if live.exists() else b""

        def _engine_gone():
            raise ImportError("engine gone")

        monkeypatch.setattr(seed, "_mount", _engine_gone)
        _, err, _ = sd.run("PreToolUse", _SEED_PAYLOAD)
        assert "HOOKS BROKEN" in err, "the break must happen for the pin to mean anything"
        assert (live.read_bytes() if live.exists() else b"") == before, "medic reads that log as a real break"


class _Unwritable:
    """A break log whose every use raises something that is not an OSError."""

    def __fspath__(self) -> str:
        raise RuntimeError("the record itself broke")

    def __str__(self) -> str:
        return "<unwritable break log>"


class _DeadStream:
    """A stream whose reader has gone: every write is a broken pipe."""

    def write(self, _text: str) -> int:
        raise BrokenPipeError("reader gone")

    def flush(self) -> None:
        raise BrokenPipeError("reader gone")


def _engine_gone():
    raise ImportError("engine gone")


class _Unprintable(Exception):
    """An exception whose message itself raises."""

    def __str__(self) -> str:
        raise RuntimeError("no message")


def _exits_quietly():
    raise SystemExit(0)


def _unprintable():
    raise _Unprintable()


def _not_utf8_stdin() -> io.TextIOWrapper:
    return io.TextIOWrapper(io.BytesIO(b'{"tool": "shell", "tool_name": "Bash", "x": "\xff"}'), encoding="utf-8")


def _denied(module, out: str) -> str:
    """The deny reason in each bridge's answer, or "" when the answer is no deny."""
    doc = json.loads(out)
    if module is codex:
        return doc.get("hookSpecificOutput", {}).get("permissionDecisionReason", "")
    return doc.get("deny", "")


class TestNothingAfterTheBreakLetsTheToolRun:
    """The refusal leaves first; a record that raises, or a payload that cannot be read, never turns it into a run."""

    @pytest.mark.parametrize("module", (codex, opencode), ids=("codex", "opencode"))
    def test_a_record_that_raises_anything_still_denies(self, module, monkeypatch, capsys):
        monkeypatch.setattr(module, "_mount", _engine_gone)
        monkeypatch.setattr(module, "BREAK_LOG", _Unwritable())
        monkeypatch.setattr(sys, "argv", [f"{module.PROVIDER}.py", "PreToolUse"])
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"tool": "shell", "tool_name": "Bash"})))
        module.main()
        out, err = capsys.readouterr()
        assert _denied(module, out).startswith("HOOKS BROKEN")
        assert "the record itself broke" in err

    @pytest.mark.parametrize("module", (codex, opencode), ids=("codex", "opencode"))
    def test_a_payload_that_is_not_utf8_is_denied_not_run(self, module, monkeypatch, capsys, tmp_path):
        monkeypatch.setattr(module, "BREAK_LOG", str(tmp_path / "bridge.log"))
        monkeypatch.setattr(sys, "argv", [f"{module.PROVIDER}.py", "PreToolUse"])
        monkeypatch.setattr(sys, "stdin", _not_utf8_stdin())
        module.main()
        assert "UnicodeDecodeError" in _denied(module, capsys.readouterr().out)

    def test_seed_a_record_that_raises_anything_still_refuses_with_exit_2(self, sd, monkeypatch):
        monkeypatch.setattr(seed, "_mount", _engine_gone)
        monkeypatch.setattr(seed, "BREAK_LOG", _Unwritable())
        out, err, code = sd.run("PreToolUse", {**_SEED_PAYLOAD, "tool_name": "Bash"})
        assert (out, code) == ("", 2)
        assert err.startswith("HOOKS BROKEN") and "the record itself broke" in err

    def test_seed_a_payload_that_is_not_utf8_is_refused_with_exit_2(self, monkeypatch, capsys, tmp_path):
        monkeypatch.setattr(seed, "BREAK_LOG", str(tmp_path / "bridge.log"))
        monkeypatch.setattr(sys, "argv", ["seed.py", "PreToolUse"])
        monkeypatch.setattr(sys, "stdin", _not_utf8_stdin())
        with pytest.raises(SystemExit) as refused:
            seed.main()
        assert refused.value.code == 2
        assert "UnicodeDecodeError" in capsys.readouterr().err

    def test_seed_an_engine_refusal_naming_a_non_utf8_path_still_exits_2(self, sd):
        sd.answer = (f"refused: {os.fsdecode(b'bad' + bytes([255]))}", 2)
        _, err, code = sd.run("PreToolUse", {**_SEED_PAYLOAD, "tool_name": "Bash"})
        assert code == 2
        assert "refused: bad" in err

    @pytest.mark.parametrize("module", (codex, opencode), ids=("codex", "opencode"))
    def test_the_answer_is_out_before_the_record_is_attempted(self, module, monkeypatch, capsys):
        """A record that hangs can then cost a timeout, never the deny."""
        seen: list[str] = []
        monkeypatch.setattr(module, "_mount", _engine_gone)
        monkeypatch.setattr(module, "_record_break", lambda *_: seen.append(capsys.readouterr().out))
        monkeypatch.setattr(sys, "argv", [f"{module.PROVIDER}.py", "PreToolUse"])
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"tool": "shell", "tool_name": "Bash"})))
        module.main()
        assert _denied(module, seen[0]).startswith("HOOKS BROKEN")

    def test_seed_a_stderr_that_cannot_be_written_still_refuses_with_exit_2(self, monkeypatch, capsys, tmp_path):
        monkeypatch.setattr(seed, "_mount", _engine_gone)
        monkeypatch.setattr(seed, "BREAK_LOG", str(tmp_path / "bridge.log"))
        monkeypatch.setattr(sys, "argv", ["seed.py", "PreToolUse"])
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(_SEED_PAYLOAD)))
        monkeypatch.setattr(sys, "stderr", _DeadStream())
        with pytest.raises(SystemExit) as refused:
            seed.main()
        assert refused.value.code == 2

    def test_seed_an_engine_refusal_with_a_dead_stderr_still_exits_2(self, sd, monkeypatch):
        sd.answer = ('{"decision": "block", "reason": "no"}', 2)
        monkeypatch.setattr(sys, "stderr", _DeadStream())
        assert sd.run("PreToolUse", {**_SEED_PAYLOAD, "tool_name": "Bash"})[2] == 2

    @pytest.mark.parametrize("module", (codex, opencode), ids=("codex", "opencode"))
    @pytest.mark.parametrize("breaks", (_exits_quietly, _unprintable), ids=("system_exit_0", "unprintable"))
    def test_any_break_however_it_is_raised_still_denies(self, module, breaks, monkeypatch, capsys, tmp_path):
        """Codex runs the tool on any exit with no deny on stdout (a real run, 2026-11-15): the deny must be written."""
        monkeypatch.setattr(module, "_mount", breaks)
        monkeypatch.setattr(module, "BREAK_LOG", str(tmp_path / "bridge.log"))
        monkeypatch.setattr(sys, "argv", [f"{module.PROVIDER}.py", "PreToolUse"])
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"tool": "shell", "tool_name": "Bash"})))
        module.main()
        assert _denied(module, capsys.readouterr().out).startswith("HOOKS BROKEN")

    @pytest.mark.parametrize("breaks", (_exits_quietly, _unprintable), ids=("system_exit_0", "unprintable"))
    def test_seed_any_break_however_it_is_raised_still_refuses_with_exit_2(self, breaks, monkeypatch, capsys, tmp_path):
        monkeypatch.setattr(seed, "_mount", breaks)
        monkeypatch.setattr(seed, "BREAK_LOG", str(tmp_path / "bridge.log"))
        monkeypatch.setattr(sys, "argv", ["seed.py", "PreToolUse"])
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(_SEED_PAYLOAD)))
        with pytest.raises(SystemExit) as refused:
            seed.main()
        assert refused.value.code == 2


_GIT_ID = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


@pytest.fixture
def broken_home(tmp_path, monkeypatch):
    """A checkout with one committed prax file, a signed admin seat, and safe_mode pointed at it."""
    repo = tmp_path / "AIPass"
    code = repo / "src" / "aipass" / "prax" / "apps" / "load.py"
    seat = repo / "src" / "aipass" / "devpulse"
    for folder in (code.parent, seat / ".trinity", seat / "artifacts", seat.parent / "flow" / ".trinity"):
        folder.mkdir(parents=True)
    code.write_text("VALUE = 1\n", encoding="utf-8")
    for name, value in _GIT_ID.items():
        monkeypatch.setenv(name, value)
    for args in (["init", "-q"], ["add", "-A"], ["commit", "-q", "-m", "base"]):
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)
    (seat / ".trinity" / "passport.json").write_text("{}", encoding="utf-8")
    (seat.parent / "flow" / ".trinity" / "passport.json").write_text("{}", encoding="utf-8")
    key = tmp_path / "admin_grant.key"
    key.write_text("ab" * 32 + "\n", encoding="utf-8")
    cert = {"owner": "devpulse", "type": "birth_certificate", "privileges": {"admin": True}}
    payload = json.dumps(cert, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    value = hmac.new(bytes.fromhex("ab" * 32), payload, hashlib.sha256).hexdigest()
    signed = {**cert, "signature": {"algo": "hmac-sha256", "value": value}}
    (seat / "artifacts" / "birth_certificate.json").write_text(json.dumps(signed), encoding="utf-8")
    monkeypatch.setattr(safe_mode, "repo_root", lambda: str(repo))
    monkeypatch.setattr(safe_mode, "KEY_PATH", str(key))
    monkeypatch.setattr(safe_mode, "RECOVERY_DIR", str(tmp_path / "recovery"))
    return repo


def _bash(repo: Path, command: str, seat: str = "devpulse", tool: str = "Bash") -> str:
    cwd = str(repo / "src" / "aipass" / seat)
    return json.dumps({"tool_name": tool, "tool_input": {"command": command}, "cwd": cwd})


class TestSafeModeAllowsOneCall:
    """While the engine is broken the admin seat may run safe_mode.py's own command, and nothing else."""

    def test_the_admin_seat_running_the_printed_command_is_let_through(self, broken_home):
        assert safe_mode.allows(_bash(broken_home, f"{safe_mode.INVOKE} diagnose")) is True
        assert safe_mode.allows(_bash(broken_home, f"{safe_mode.INVOKE} park src/aipass/prax/apps")) is True

    @pytest.mark.parametrize(
        "tail",
        ("diagnose; rm -rf x", "diagnose && ls", "park $(pwd)", "park a b", "diagnose\n", "edit x", ""),
        ids=("second_command", "and", "substitution", "two_paths", "newline", "other_verb", "bare"),
    )
    def test_anything_riding_on_the_command_is_refused(self, broken_home, tail):
        assert safe_mode.allows(_bash(broken_home, f"{safe_mode.INVOKE} {tail}")) is False

    def test_another_tool_or_another_command_is_refused(self, broken_home):
        assert safe_mode.allows(_bash(broken_home, f"{safe_mode.INVOKE} diagnose", tool="Edit")) is False
        assert safe_mode.allows(_bash(broken_home, "ls")) is False

    def test_a_seat_with_no_certificate_is_not_let_through(self, broken_home):
        assert safe_mode.allows(_bash(broken_home, f"{safe_mode.INVOKE} diagnose", seat="flow")) is False

    def test_a_missing_signing_key_raises_so_the_bridge_can_say_why(self, broken_home, monkeypatch, tmp_path):
        monkeypatch.setattr(safe_mode, "KEY_PATH", str(tmp_path / "no.key"))
        with pytest.raises(FileNotFoundError):
            safe_mode.allows(_bash(broken_home, f"{safe_mode.INVOKE} diagnose"))

    def test_a_certificate_changed_after_signing_is_refused(self, broken_home):
        cert_path = broken_home / "src" / "aipass" / "devpulse" / "artifacts" / "birth_certificate.json"
        cert = json.loads(cert_path.read_text(encoding="utf-8"))
        cert_path.write_text(json.dumps({**cert, "creator": "someone else"}), encoding="utf-8")
        assert safe_mode.allows(_bash(broken_home, f"{safe_mode.INVOKE} diagnose")) is False

    def test_a_certificate_copied_into_a_branch_outside_this_checkout_is_refused(self, broken_home, tmp_path):
        outside = tmp_path / "elsewhere" / "devpulse"
        shutil.copytree(broken_home / "src" / "aipass" / "devpulse", outside)
        payload = {"tool_name": "Bash", "tool_input": {"command": f"{safe_mode.INVOKE} diagnose"}, "cwd": str(outside)}
        assert safe_mode.allows(json.dumps(payload)) is False

    def test_a_certificate_copied_into_another_branch_of_this_checkout_is_refused(self, broken_home):
        flow = broken_home / "src" / "aipass" / "flow"
        shutil.copytree(broken_home / "src" / "aipass" / "devpulse" / "artifacts", flow / "artifacts")
        assert safe_mode.allows(_bash(broken_home, f"{safe_mode.INVOKE} diagnose", seat="flow")) is False

    def test_rollback_is_let_through_and_takes_no_argument(self, broken_home):
        assert safe_mode.allows(_bash(broken_home, f"{safe_mode.INVOKE} rollback")) is True
        assert safe_mode.allows(_bash(broken_home, f"{safe_mode.INVOKE} rollback .live-x")) is False


class TestSafeModeRollback:
    """rollback serves the promoted copy before the live one, and undoes itself when that is no cure."""

    @pytest.fixture
    def hooks(self, tmp_path, monkeypatch):
        root = tmp_path / "hooks"
        for name in (".live-20260101T000000Z", ".live-20260102T000000Z", ".live-20260103T000000Z"):
            (root / name).mkdir(parents=True)
            (root / name / "__init__.py").write_text("", encoding="utf-8")
        (root / ".live-current").write_text(".live-20260103T000000Z\n", encoding="utf-8")
        monkeypatch.setattr(safe_mode, "hooks_root", lambda: str(root))
        monkeypatch.setattr(safe_mode, "RECOVERY_DIR", str(tmp_path / "recovery"))
        return root

    def _live(self, hooks: Path) -> str:
        return (hooks / ".live-current").read_text(encoding="utf-8").strip()

    def test_the_copy_before_the_live_one_is_served_when_it_cures(self, hooks, monkeypatch):
        answers = iter(["broken", ""])
        monkeypatch.setattr(safe_mode, "engine_error", lambda: next(answers))
        assert safe_mode.rollback() == 0
        assert self._live(hooks) == ".live-20260102T000000Z"
        assert sorted(p.name for p in hooks.glob(".live-2*")) == [f".live-2026010{n}T000000Z" for n in (1, 2, 3)]

    def test_the_pointer_goes_back_when_the_older_copy_is_no_cure(self, hooks, monkeypatch, capsys):
        monkeypatch.setattr(safe_mode, "engine_error", lambda: "still broken")
        assert safe_mode.rollback() == 1
        assert self._live(hooks) == ".live-20260103T000000Z"
        assert "live again, as it was" in capsys.readouterr().out

    def test_rollback_refuses_while_the_engine_runs(self, hooks, monkeypatch):
        monkeypatch.setattr(safe_mode, "engine_error", lambda: "")
        assert safe_mode.rollback() == 2
        assert self._live(hooks) == ".live-20260103T000000Z"

    def test_with_no_older_copy_nothing_changes(self, hooks, monkeypatch):
        (hooks / ".live-current").write_text(".live-20260101T000000Z\n", encoding="utf-8")
        monkeypatch.setattr(safe_mode, "engine_error", lambda: "broken")
        assert safe_mode.rollback() == 1
        assert self._live(hooks) == ".live-20260101T000000Z"


class TestSafeModePark:
    """park moves uncommitted code into a stash while the engine is broken, and refuses everything else."""

    def test_park_refuses_a_path_that_passes_through_a_link(self, broken_home, monkeypatch):
        monkeypatch.setattr(safe_mode, "engine_error", lambda: "broken")
        apps = broken_home / "src" / "aipass" / "flow" / "apps"
        apps.symlink_to(broken_home / "src" / "aipass" / "prax" / "apps")
        code = self._break(broken_home)
        assert safe_mode.park("src/aipass/flow/apps") == 3
        assert code.read_text(encoding="utf-8") == "VALUE = Optional\n"

    def _break(self, repo: Path) -> Path:
        code = repo / "src" / "aipass" / "prax" / "apps" / "load.py"
        code.write_text("VALUE = Optional\n", encoding="utf-8")
        (code.parent / "half_done.py").write_text("x = 1\n", encoding="utf-8")
        return code

    def test_park_puts_the_code_back_and_keeps_the_work(self, broken_home, monkeypatch, capsys, tmp_path):
        code = self._break(broken_home)
        answers = iter(["NameError: name 'Optional' is not defined", ""])
        monkeypatch.setattr(safe_mode, "engine_error", lambda: next(answers))
        assert safe_mode.park("src/aipass/prax/apps") == 0
        assert code.read_text(encoding="utf-8") == "VALUE = 1\n"
        assert not (code.parent / "half_done.py").exists()
        git = ["git", "-C", str(broken_home), "stash"]
        stashes = subprocess.run([*git, "list"], capture_output=True, encoding="utf-8")
        assert "safe mode" in stashes.stdout and "src/aipass/prax/apps" in stashes.stdout
        shown = subprocess.run([*git, "show", "-p", "--include-untracked"], capture_output=True, encoding="utf-8")
        assert "VALUE = Optional" in shown.stdout and "half_done.py" in shown.stdout
        patch_file = next((tmp_path / "recovery").glob("*.patch"))
        assert "+VALUE = Optional" in patch_file.read_text(encoding="utf-8")
        lines = (tmp_path / "recovery" / "log.jsonl").read_text(encoding="utf-8").splitlines()
        log = [json.loads(line) for line in lines]
        assert [(e["verb"], e.get("broken")) for e in log] == [("park", None), ("park-result", False)]
        assert "The hook engine runs again" in capsys.readouterr().out

    def test_park_refuses_while_the_engine_runs_and_moves_nothing(self, broken_home, monkeypatch):
        code = self._break(broken_home)
        monkeypatch.setattr(safe_mode, "engine_error", lambda: "")
        assert safe_mode.park("src/aipass/prax/apps") == 2
        assert code.read_text(encoding="utf-8") == "VALUE = Optional\n"

    @pytest.mark.parametrize(
        "path",
        ("src/aipass/devpulse/.trinity", "src/aipass/prax", "src/aipass/prax/apps/../../devpulse", ".", "/etc"),
        ids=("memory", "whole_branch", "climbs_out", "checkout", "outside"),
    )
    def test_park_refuses_a_path_that_is_not_a_branchs_code(self, broken_home, monkeypatch, path):
        monkeypatch.setattr(safe_mode, "engine_error", lambda: "broken")
        (broken_home / "src" / "aipass" / "devpulse" / ".trinity" / "local.json").write_text("{}", encoding="utf-8")
        assert safe_mode.park(path) == 3
        assert (broken_home / "src" / "aipass" / "devpulse" / ".trinity" / "local.json").exists()

    def test_diagnose_names_the_error_and_the_uncommitted_code(self, broken_home, monkeypatch, capsys):
        self._break(broken_home)
        monkeypatch.setattr(safe_mode, "engine_error", lambda: "NameError: name 'Optional' is not defined")
        assert safe_mode.diagnose() == 1
        out = capsys.readouterr().out
        assert "NameError" in out and "src/aipass/prax/apps/load.py" in out

    def test_diagnose_says_so_when_nothing_is_uncommitted(self, broken_home, monkeypatch, capsys):
        monkeypatch.setattr(safe_mode, "engine_error", lambda: "ImportError: gone")
        assert safe_mode.diagnose() == 1
        out = capsys.readouterr().out
        assert "  none\n" in out and "the break is committed" in out


class TestClaudeBridgeSafeMode:
    """The Claude bridge asks safe mode before it refuses, and any trouble asking is a refusal."""

    def _run(self, monkeypatch, capsys, tmp_path, payload: str, event: str = "PreToolUse") -> tuple[str, str, int]:
        monkeypatch.setattr(claude, "_mount", _engine_gone)
        monkeypatch.setattr(claude, "BREAK_LOG", str(tmp_path / "bridge.log"))
        monkeypatch.setattr(sys, "argv", ["claude.py", event])
        monkeypatch.setattr(sys, "stdin", io.StringIO(payload))
        code = 0
        try:
            claude.main()
        except SystemExit as exit_:
            code = int(exit_.code or 0)
        out, err = capsys.readouterr()
        return out, err, code

    def test_a_call_safe_mode_allows_runs_with_nothing_said(self, monkeypatch, capsys, tmp_path):
        monkeypatch.setattr(claude, "_safe_mode", lambda stdin_data: stdin_data == "the one call")
        assert self._run(monkeypatch, capsys, tmp_path, "the one call") == ("", "", 0)

    def test_a_call_safe_mode_refuses_is_blocked_and_told_where_recovery_is(self, monkeypatch, capsys, tmp_path):
        monkeypatch.setattr(claude, "_safe_mode", lambda stdin_data: stdin_data == "the one call")
        out, err, code = self._run(monkeypatch, capsys, tmp_path, "{}")
        assert (json.loads(out)["decision"], code) == ("block", 2)
        assert err.startswith("HOOKS BROKEN") and "engine gone" in err
        assert f"{safe_mode.INVOKE} diagnose" in err and "playbook_plans/recovery.md" in err

    def test_safe_mode_is_never_asked_outside_a_guarded_event(self, monkeypatch, capsys, tmp_path):
        monkeypatch.setattr(claude, "_safe_mode", lambda stdin_data: pytest.fail("asked"))
        assert self._run(monkeypatch, capsys, tmp_path, "{}", event="UserPromptSubmit")[2] == 0

    @pytest.mark.parametrize(
        "payload", ("not json", "[]", '{"tool_name": "Bash"}', ""), ids=("text", "list", "bare", "empty")
    )
    def test_a_payload_the_real_safe_mode_cannot_judge_is_refused(self, monkeypatch, capsys, tmp_path, payload):
        assert self._run(monkeypatch, capsys, tmp_path, payload)[2] == 2

    def test_a_safe_mode_file_that_cannot_load_is_a_refusal_that_says_so(self, monkeypatch, capsys, tmp_path):
        monkeypatch.setattr(claude, "SAFE_MODE", str(tmp_path / "missing.py"))
        out, err, code = self._run(monkeypatch, capsys, tmp_path, "{}")
        assert (json.loads(out)["decision"], code) == ("block", 2)
        assert "safe mode could not judge this call: FileNotFoundError" in err and "HOOKS BROKEN" in err
