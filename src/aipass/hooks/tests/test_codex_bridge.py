# =================== AIPass ====================
# Name: test_codex_bridge.py
# Version: 2.8.0
# Description: Tests for the Codex and OpenCode bridges: payload mapping, output envelope, apply_patch, fail closed
# Branch: hooks
# Layer: tests
# Created: 2026-07-10
# Modified: 2026-10-28
# =============================================

"""Tests for apps/handlers/bridges/codex.py, apps/handlers/bridges/opencode.py and its plugin, opencode_plugin.ts."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that handlers/bridges/codex.py parses and imports its engine and loader
# seedgo: no-test-needed(documentation) — the Codex protocol notes in the bridge's module docstring
# seedgo: no-test-needed(generated) — opencode_plugin.ts inside a real OpenCode server: a live run (Node runs it here)
# seedgo: no-test-needed(stdlib) — json.loads and json.dumps round-tripping a payload

import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from aipass.hooks.apps.handlers.bridges import codex, opencode
from aipass.hooks.apps.modules import engine
from aipass.prax.apps.modules import logger as prax_logger


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


class TestBrokenEngine:
    def test_with_prax_unimportable_a_broken_engine_still_denies_pretooluse(self, monkeypatch, capsys, tmp_path):
        monkeypatch.delattr(prax_logger, "system_logger")
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
    def test_a_missing_promoted_copy_serves_the_source_and_says_so_with_prax_down(self, monkeypatch, capsys, tmp_path):
        monkeypatch.delenv("AIPASS_HOOKS_LIVE", raising=False)
        monkeypatch.delattr(prax_logger, "system_logger")
        spec = importlib.util.spec_from_file_location("_mount_fresh", Path(codex.__file__).with_name("mount.py"))
        assert spec is not None and spec.loader is not None
        mount = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mount)
        (tmp_path / ".live-current").write_text(".live-gone", encoding="utf-8")
        bridge_file = tmp_path / "apps" / "handlers" / "bridges" / "codex.py"
        assert mount.mount_or_source(str(bridge_file), "codex") == "source (fallback)"
        err = capsys.readouterr().err
        assert "[HOOKS:codex] promoted copy unusable, serving the source tree:" in err
        assert "missing" in err and "prax unavailable" in err


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
writeFileSync(join(home, ".claude", "provider_manifest.json"), JSON.stringify({ cli: { opencode: { hooks: stopRows } } }))
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


@pytest.mark.skipif(shutil.which("node") is None, reason="the plugin runs under Node; a host without it cannot load it")
class TestOpenCodePlugin:
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
