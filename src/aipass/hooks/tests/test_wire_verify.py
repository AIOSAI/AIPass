# =================== AIPass ====================
# Name: test_wire_verify.py
# Version: 1.7.0
# Description: Tests for wire_verify module — provider ↔ project hook wiring checker
# Branch: hooks
# Created: 2026-07-09
# Modified: 2026-11-04
# =============================================

"""Tests for apps/modules/wire_verify.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# sentry: no-test-needed(ruff) — that wire_verify.py parses and imports, ruff and collection cover it
# sentry: no-test-needed(documentation) — verify_wiring()'s and handle_command()'s docstrings, the documentation checker
# sentry: no-test-needed(constant) — HELP_COMMANDS' entries and _META_KEYS' members, fixed literals
# sentry: no-test-needed(stdlib) — json.loads' parsing of the settings file, the stdlib's own

import json
from unittest.mock import patch

import pytest

from aipass.hooks.apps.modules import wire_verify

_BRIDGE_CMD = "$AIPASS_HOME/.venv/bin/python3 $AIPASS_HOME/src/aipass/hooks/apps/handlers/bridges/claude.py"


def _provider_entry(event_arg, timeout=None, matcher=None):
    hook = {"type": "command", "command": f"{_BRIDGE_CMD} {event_arg}"}
    if timeout:
        hook["timeout"] = timeout
    entry: dict = {"hooks": [hook]}
    if matcher is not None:
        entry["matcher"] = matcher
    return entry


GOOD_PROVIDER = {
    "UserPromptSubmit": [
        _provider_entry("UserPromptSubmit:identity_injector"),
        _provider_entry("UserPromptSubmit:branch_prompt"),
    ],
    "Stop": [_provider_entry("Stop")],
    "PreToolUse": [_provider_entry("PreToolUse")],
}

GOOD_PROJECT = {
    "hooks_enabled": True,
    "UserPromptSubmit": {
        "identity_injector": {"enabled": True, "handler": "x.handle", "matcher": ""},
        "branch_prompt": {"enabled": True, "handler": "y.handle", "matcher": ""},
    },
    "Stop": {
        "stop_sound": {"enabled": True, "handler": "s.handle", "matcher": ""},
    },
    "PreToolUse": {
        "tool_sound": {"enabled": True, "handler": "t.handle", "matcher": "Bash|Edit"},
    },
}


# The parser, the index and the per-event check are read through verify_wiring's
# result (fleet green leg 9, through the command). The PreToolUse bridge every
# provider below carries keeps the guarded-tools check (R7) quiet, so each result
# holds only what the event under test produced.
_ENABLED = {"enabled": True, "handler": "x.handle"}
_PRETOOL = {"PreToolUse": [_provider_entry("PreToolUse")]}
_PRETOOL_INFO = "PreToolUse: provider-only event (no project config section)"


def _verify(tmp_path, provider: dict, project: dict) -> dict:
    """verify_wiring's answer for `provider` (plus the PreToolUse bridge) against `project`."""
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"hooks": {**_PRETOOL, **provider}}), encoding="utf-8")
    return wire_verify.verify_wiring(provider_path=settings, project_config={"hooks_enabled": True, **project})


_CODEX_PRETOOL = {
    "matcher": "Bash|apply_patch",
    "hooks": [{"type": "command", "command": "python3 bridges/codex.py PreToolUse"}],
}


def _codex_file(tmp_path, *event_args: str, pretool: bool = True):
    """A user-level Codex hooks.json wiring each Event[:hook] through the Codex bridge, with its PreToolUse row."""
    hooks: dict = {"PreToolUse": [_CODEX_PRETOOL]} if pretool else {}
    for arg in event_args:
        entry = _provider_entry(arg)
        entry["hooks"][0]["command"] = entry["hooks"][0]["command"].replace("claude.py", "codex.py")
        hooks.setdefault(arg.split(":", 1)[0], []).append(entry)
    path = tmp_path / "codex_hooks.json"
    path.write_text(json.dumps({"hooks": hooks}), encoding="utf-8")
    return path


def _never_fires(event: str, hook: str) -> str:
    return f"{event}:{hook}: enabled in project config but no provider bridge entry — handler never fires"


class TestExtractBridgeArg:
    def test_filtered_arg(self, tmp_path):
        provider = {"UserPromptSubmit": [_provider_entry("UserPromptSubmit:tier0_kernel")]}
        result = _verify(tmp_path, provider, {"UserPromptSubmit": {"tier0_kernel": _ENABLED}})
        assert result == {"errors": [], "warnings": [], "info": [_PRETOOL_INFO], "ok": True}

    def test_unfiltered_arg(self, tmp_path):
        result = _verify(tmp_path, {"Stop": [_provider_entry("Stop")]}, {"Stop": {"stop_sound": _ENABLED}})
        assert result["info"] == ["Stop: unfiltered bridge, 1 enabled hooks OK", _PRETOOL_INFO]
        assert result["errors"] == []

    @pytest.mark.parametrize(
        "entry",
        [{"hooks": [{"command": "echo hello"}]}, {"hooks": []}, {}],
        ids=["no_bridge_marker", "empty_hooks", "no_hooks_key"],
    )
    def test_an_entry_without_a_bridge_wires_nothing(self, tmp_path, entry):
        result = _verify(tmp_path, {"Stop": [entry]}, {"Stop": {"stop_sound": _ENABLED}})
        assert result["errors"] == [_never_fires("Stop", "stop_sound")]


class TestBuildProviderIndex:
    # test_builds_unfiltered_index is retired: TestExtractBridgeArg::test_unfiltered_arg pins the same answer.

    def test_builds_filtered_index(self, tmp_path):
        provider = {
            "UserPromptSubmit": [
                _provider_entry("UserPromptSubmit:identity_injector"),
                _provider_entry("UserPromptSubmit:branch_prompt"),
            ],
        }
        project = {"UserPromptSubmit": {"identity_injector": _ENABLED, "branch_prompt": _ENABLED}}
        result = _verify(tmp_path, provider, project)
        assert (result["errors"], result["warnings"]) == ([], [])

    def test_empty_array_errors(self, tmp_path):
        result = _verify(tmp_path, {"SessionStart": []}, {"SessionStart": {"cadence_reset": _ENABLED}})
        # One error: an empty array is reported once, and the event is then skipped, not called unwired.
        assert result["errors"] == ["SessionStart: provider entry exists but hooks array is EMPTY — nothing fires"]

    def test_duplicate_filtered_counted(self, tmp_path):
        provider = {"PreCompact": [_provider_entry("PreCompact:pre_compact")] * 2}
        result = _verify(tmp_path, provider, {"PreCompact": {"pre_compact": _ENABLED}})
        assert result["warnings"] == ["PreCompact:pre_compact: 2 duplicate provider entries (matcher=none)"]
        assert result["errors"] == []

    def test_distinct_matchers_not_duplicate(self, tmp_path):
        provider = {
            "PreCompact": [
                _provider_entry("PreCompact:pre_compact", matcher="manual"),
                _provider_entry("PreCompact:pre_compact", matcher="auto"),
                _provider_entry("PreCompact:pre_compact", matcher="auto"),
            ],
        }
        result = _verify(tmp_path, provider, {"PreCompact": {"pre_compact": _ENABLED}})
        assert result["warnings"] == ["PreCompact:pre_compact: 2 duplicate provider entries (matcher=auto)"]


class TestCheckEventWiring:
    # Retired as covered (fleet green leg 9): test_unfiltered_ok by TestExtractBridgeArg::test_unfiltered_arg,
    # test_distinct_matchers_no_warning by TestBuildProviderIndex::test_distinct_matchers_not_duplicate,
    # test_empty_provider_skipped by TestBuildProviderIndex::test_empty_array_errors.

    def test_missing_provider_event(self, tmp_path):
        result = _verify(tmp_path, {}, {"SessionStart": {"cadence_reset": _ENABLED}})
        assert result["errors"] == [
            "SessionStart: 1 enabled handler(s) in project config but NO provider event entry — handlers never fire"
        ]

    def test_missing_per_hook_entry(self, tmp_path):
        provider = {"UserPromptSubmit": [_provider_entry("UserPromptSubmit:identity_injector")]}
        project = {"UserPromptSubmit": {"identity_injector": _ENABLED, "presence_gate": _ENABLED}}
        result = _verify(tmp_path, provider, project)
        assert result["errors"] == [_never_fires("UserPromptSubmit", "presence_gate")]

    def test_duplicate_per_hook_warns(self, tmp_path):
        provider = {"UserPromptSubmit": [_provider_entry("UserPromptSubmit:branch_prompt")] * 3}
        result = _verify(tmp_path, provider, {"UserPromptSubmit": {"branch_prompt": _ENABLED}})
        assert result["warnings"] == ["UserPromptSubmit:branch_prompt: 3 duplicate provider entries (matcher=none)"]

    def test_orphaned_provider_entry(self, tmp_path):
        provider = {"UserPromptSubmit": [_provider_entry("UserPromptSubmit:ghost_hook")]}
        result = _verify(tmp_path, provider, {"UserPromptSubmit": {"real_hook": _ENABLED}})
        assert result["warnings"] == [
            "UserPromptSubmit:ghost_hook: provider entry exists but no handler in project config (orphaned)"
        ]
        assert result["errors"] == [_never_fires("UserPromptSubmit", "real_hook")]

    def test_disabled_hooks_skipped(self, tmp_path):
        project = {"UserPromptSubmit": {"disabled_hook": {"enabled": False, "handler": "x"}}}
        assert _verify(tmp_path, {}, project)["errors"] == []

    def test_duplicate_unfiltered_warns(self, tmp_path):
        result = _verify(tmp_path, {"Stop": [_provider_entry("Stop")] * 3}, {"Stop": {"stop_sound": _ENABLED}})
        assert result["warnings"] == ["Stop: 3 duplicate unfiltered provider entries"]

    def test_provider_wired_false_still_errors(self, tmp_path):
        provider = {"UserPromptSubmit": [_provider_entry("UserPromptSubmit:identity_injector")]}
        project = {
            "UserPromptSubmit": {
                "identity_injector": _ENABLED,
                "presence_gate": {"enabled": True, "handler": "y", "provider_wired": False},
            }
        }
        assert _verify(tmp_path, provider, project)["errors"] == [_never_fires("UserPromptSubmit", "presence_gate")]

    def test_provider_wired_false_no_event_still_errors(self, tmp_path):
        project = {"UserPromptSubmit": {"presence_gate": {"enabled": True, "handler": "y", "provider_wired": False}}}
        assert _verify(tmp_path, {}, project)["errors"] == [
            "UserPromptSubmit: 1 enabled handler(s) in project config but NO provider event entry — handlers never fire"
        ]


class TestEveryGuardedToolReachesTheBridge:
    """DPLAN-0356 phase 3, R7 (red team, MEDIUM): the live PreToolUse matcher lacked NotebookEdit,
    so the gates that guard it never ran, and verify said nothing."""

    def _errors(self, tmp_path, matcher):
        provider = {**GOOD_PROVIDER, "PreToolUse": [_provider_entry("PreToolUse", matcher=matcher)]}
        settings = tmp_path / "settings.json"
        settings.write_text(json.dumps({"hooks": provider}), encoding="utf-8")
        return wire_verify.verify_wiring(provider_path=settings, project_config=GOOD_PROJECT)["errors"]

    def test_a_matcher_missing_notebookedit_is_an_error_naming_it(self, tmp_path):
        errors = self._errors(tmp_path, "Bash|Edit|MultiEdit|Write|Read|Grep|Glob|WebSearch|WebFetch|Task")
        assert len(errors) == 1 and "NotebookEdit" in errors[0]

    def test_the_corrected_matcher_passes(self, tmp_path):
        assert self._errors(tmp_path, "Bash|Edit|MultiEdit|Write|NotebookEdit|Read|Grep|Glob|Task") == []

    def test_an_empty_or_star_matcher_reaches_every_tool(self, tmp_path):
        assert self._errors(tmp_path, "") == []
        assert self._errors(tmp_path, "*") == []

    def test_no_pretooluse_bridge_at_all_names_every_guarded_tool(self, tmp_path):
        provider = {key: value for key, value in GOOD_PROVIDER.items() if key != "PreToolUse"}
        settings = tmp_path / "settings.json"
        settings.write_text(json.dumps({"hooks": provider}), encoding="utf-8")
        project = {key: value for key, value in GOOD_PROJECT.items() if key != "PreToolUse"}
        errors = wire_verify.verify_wiring(provider_path=settings, project_config=project)["errors"]
        assert {"Bash", "Edit", "MultiEdit", "Write", "NotebookEdit"} <= {e.split()[1] for e in errors}


class TestVerifyWiring:
    def test_all_good(self, tmp_path):
        settings = tmp_path / "settings.json"
        settings.write_text(json.dumps({"hooks": GOOD_PROVIDER}), encoding="utf-8")
        result = wire_verify.verify_wiring(provider_path=settings, project_config=GOOD_PROJECT)
        assert result["ok"] is True
        assert result["errors"] == []

    def test_empty_provider_array(self, tmp_path):
        provider = {**GOOD_PROVIDER, "SessionStart": []}
        settings = tmp_path / "settings.json"
        settings.write_text(json.dumps({"hooks": provider}), encoding="utf-8")
        project = {
            **GOOD_PROJECT,
            "SessionStart": {
                "cadence_reset": {"enabled": True, "handler": "x"},
            },
        }
        result = wire_verify.verify_wiring(provider_path=settings, project_config=project)
        assert result["ok"] is False
        assert any("EMPTY" in e for e in result["errors"])

    def test_missing_provider_file(self, tmp_path):
        result = wire_verify.verify_wiring(
            provider_path=tmp_path / "nonexistent.json",
            project_config=GOOD_PROJECT,
        )
        assert result["ok"] is False
        assert any("No provider" in e for e in result["errors"])

    def test_no_project_config(self, tmp_path):
        settings = tmp_path / "settings.json"
        settings.write_text(json.dumps({"hooks": GOOD_PROVIDER}), encoding="utf-8")
        with patch.object(wire_verify, "find_project_config", return_value=None):
            result = wire_verify.verify_wiring(provider_path=settings)
        assert result["ok"] is False
        assert any("hooks.json" in e for e in result["errors"])

    def test_missing_per_hook_entry_is_error(self, tmp_path):
        provider = {
            "UserPromptSubmit": [
                _provider_entry("UserPromptSubmit:identity_injector"),
            ],
        }
        settings = tmp_path / "settings.json"
        settings.write_text(json.dumps({"hooks": provider}), encoding="utf-8")
        project = {
            "hooks_enabled": True,
            "UserPromptSubmit": {
                "identity_injector": {"enabled": True, "handler": "x"},
                "presence_gate": {"enabled": True, "handler": "y"},
            },
        }
        result = wire_verify.verify_wiring(provider_path=settings, project_config=project)
        assert result["ok"] is False
        assert any("presence_gate" in e for e in result["errors"])

    def test_provider_wired_false_now_errors(self, tmp_path):
        settings = tmp_path / "settings.json"
        settings.write_text(json.dumps({"hooks": GOOD_PROVIDER}), encoding="utf-8")
        project = {
            **GOOD_PROJECT,
            "UserPromptSubmit": {
                **GOOD_PROJECT["UserPromptSubmit"],
                "presence_gate": {"enabled": True, "handler": "z", "provider_wired": False},
            },
        }
        result = wire_verify.verify_wiring(provider_path=settings, project_config=project)
        assert result["ok"] is False
        assert any("presence_gate" in e for e in result["errors"])

    def test_distinct_matchers_no_dupe_warning(self, tmp_path):
        provider = {
            **GOOD_PROVIDER,
            "PreCompact": [
                _provider_entry("PreCompact:pre_compact", matcher="manual"),
                _provider_entry("PreCompact:pre_compact", matcher="auto"),
            ],
        }
        settings = tmp_path / "settings.json"
        settings.write_text(json.dumps({"hooks": provider}), encoding="utf-8")
        project = {
            **GOOD_PROJECT,
            "PreCompact": {
                "pre_compact": {"enabled": True, "handler": "x"},
            },
        }
        result = wire_verify.verify_wiring(provider_path=settings, project_config=project)
        assert result["ok"] is True
        assert not any("duplicate" in w for w in result["warnings"])

    def test_provider_only_event_info(self, tmp_path):
        provider = {**GOOD_PROVIDER, "CustomEvent": [_provider_entry("CustomEvent")]}
        settings = tmp_path / "settings.json"
        settings.write_text(json.dumps({"hooks": provider}), encoding="utf-8")
        result = wire_verify.verify_wiring(provider_path=settings, project_config=GOOD_PROJECT)
        assert any("provider-only" in i for i in result["info"])

    def test_meta_keys_ignored(self, tmp_path):
        settings = tmp_path / "settings.json"
        settings.write_text(json.dumps({"hooks": GOOD_PROVIDER}), encoding="utf-8")
        project = {**GOOD_PROJECT, "_comment": "test", "hooks_enabled": True}
        result = wire_verify.verify_wiring(provider_path=settings, project_config=project)
        assert result["ok"] is True


class TestReadProviderHooks:
    # Read through verify_wiring (fleet green leg 9). test_missing_file_returns_empty is retired:
    # TestVerifyWiring::test_missing_provider_file pins the same answer.

    def test_reads_file(self, tmp_path):
        settings = tmp_path / "settings.json"
        settings.write_text(json.dumps({"hooks": {"Stop": []}}), encoding="utf-8")
        result = wire_verify.verify_wiring(provider_path=settings, project_config={"hooks_enabled": True})
        assert "Stop: provider entry exists but hooks array is EMPTY — nothing fires" in result["errors"]

    def test_malformed_json_returns_empty(self, tmp_path):
        settings = tmp_path / "settings.json"
        settings.write_text("not json{{{", encoding="utf-8")
        result = wire_verify.verify_wiring(provider_path=settings, project_config=GOOD_PROJECT)
        assert result == {
            "errors": ["No provider hooks found in ~/.claude/settings.json"],
            "warnings": [],
            "info": [],
            "ok": False,
        }


class TestCodexOnlyHandlers:
    def _verify(self, tmp_path, codex_path):
        settings = tmp_path / "settings.json"
        provider = {**_PRETOOL, "SessionStart": [_provider_entry("SessionStart:cadence_reset")]}
        settings.write_text(json.dumps({"hooks": provider}), encoding="utf-8")
        project = {"hooks_enabled": True, "SessionStart": {"cadence_reset": _ENABLED, "culture": _ENABLED}}
        return wire_verify.verify_wiring(provider_path=settings, project_config=project, codex_path=codex_path)

    def test_a_handler_wired_only_in_the_codex_file_is_wired_not_an_error(self, tmp_path):
        result = self._verify(tmp_path, _codex_file(tmp_path, "SessionStart:culture"))
        assert result["errors"] == []
        assert "SessionStart:culture: wired for Codex only" in result["info"]

    def test_a_handler_in_neither_provider_still_never_fires(self, tmp_path):
        result = self._verify(tmp_path, _codex_file(tmp_path, "SessionStart:cadence_reset"))
        assert result["errors"] == [_never_fires("SessionStart", "culture")]

    def test_a_claude_bridge_row_in_the_codex_file_does_not_count(self, tmp_path):
        codex_path = tmp_path / "codex_hooks.json"
        claude_row = {"PreToolUse": [_CODEX_PRETOOL], "SessionStart": [_provider_entry("SessionStart:culture")]}
        codex_path.write_text(json.dumps({"hooks": claude_row}), encoding="utf-8")
        assert self._verify(tmp_path, codex_path)["errors"] == [_never_fires("SessionStart", "culture")]

    def test_a_codex_file_whose_pretooluse_misses_a_tool_is_an_error_naming_it(self, tmp_path):
        result = self._verify(tmp_path, _codex_file(tmp_path, "SessionStart:culture", pretool=False))
        assert result["ok"] is False
        assert [e for e in result["errors"] if e.startswith("PreToolUse (Codex): Bash ")]
        assert [e for e in result["errors"] if e.startswith("PreToolUse (Codex): apply_patch ")]

    def test_a_missing_codex_file_is_an_error_naming_the_cure_not_a_skipped_check(self, tmp_path):
        missing = tmp_path / "missing.json"
        result = self._verify(tmp_path, missing)
        assert result["ok"] is False
        (absent,) = [e for e in result["errors"] if str(missing) in e]
        assert "aipass doctor --fix" in absent and "Trust all and continue" in absent


def _manifest(tmp_path, *event_args: str):
    rows = [{"event": a.split(":", 1)[0], "command": f"py $AIPASS_HOME/x/bridges/opencode.py {a}"} for a in event_args]
    rows.append({"event": "SessionStart", "command": f"{_BRIDGE_CMD} SessionStart:cadence_reset"})
    path = tmp_path / "provider_manifest.json"
    path.write_text(json.dumps({"cli": {"opencode": {"hooks": rows}}}), encoding="utf-8")
    return path


class TestOpenCodePlugin:
    def _verify(self, tmp_path, plugin, manifest):
        settings = tmp_path / "settings.json"
        provider = {**_PRETOOL, "SessionStart": [_provider_entry("SessionStart:cadence_reset")]}
        settings.write_text(json.dumps({"hooks": provider}), encoding="utf-8")
        project = {"hooks_enabled": True, "SessionStart": {"cadence_reset": _ENABLED, "culture": _ENABLED}}
        return wire_verify.verify_wiring(
            provider_path=settings, project_config=project, opencode_plugin=plugin, manifest_path=manifest
        )

    def _installed(self, tmp_path):
        plugin = tmp_path / "aipass.ts"
        plugin.write_bytes(wire_verify.OPENCODE_PLUGIN_SOURCE.read_bytes())
        return plugin

    def test_a_handler_wired_only_in_the_opencode_rows_is_wired_not_an_error(self, tmp_path):
        result = self._verify(tmp_path, self._installed(tmp_path), _manifest(tmp_path, "SessionStart:culture"))
        assert result["errors"] == []
        assert "SessionStart:culture: wired for OpenCode only" in result["info"]

    def test_a_claude_row_under_cli_opencode_does_not_count(self, tmp_path):
        result = self._verify(tmp_path, self._installed(tmp_path), _manifest(tmp_path, "Stop"))
        assert result["errors"] == [_never_fires("SessionStart", "culture")]

    def test_a_missing_plugin_is_an_error_naming_the_cure(self, tmp_path):
        missing = tmp_path / "aipass.ts"
        result = self._verify(tmp_path, missing, _manifest(tmp_path, "SessionStart:culture"))
        (absent,) = [e for e in result["errors"] if str(missing) in e]
        assert "runs ungated" in absent and f"cp {wire_verify.OPENCODE_PLUGIN_SOURCE} {missing}" in absent

    def test_a_plugin_that_differs_from_the_branch_copy_is_an_error(self, tmp_path):
        plugin = self._installed(tmp_path)
        plugin.write_text("// edited\n", encoding="utf-8")
        result = self._verify(tmp_path, plugin, _manifest(tmp_path, "SessionStart:culture"))
        assert [e for e in result["errors"] if e.startswith("OpenCode plugin stale") and str(plugin) in e]

    def test_no_opencode_rows_is_an_error(self, tmp_path):
        manifest = tmp_path / "provider_manifest.json"
        manifest.write_text(json.dumps({"cli": {"claude": {"hooks": []}}}), encoding="utf-8")
        result = self._verify(tmp_path, self._installed(tmp_path), manifest)
        assert [e for e in result["errors"] if e.startswith("No cli.opencode rows") and str(manifest) in e]


class TestTheProjectRow:
    """UserPromptSubmit:project wires a trusted project's own handlers; it is never an orphan."""

    _OWN = {"enabled": True, "handler": "hark.hark.apps.modules.hook_events.record"}

    def _project(self, namespace: str = "hark") -> dict:
        own = {"_handler_namespace": namespace} if namespace else {}
        return {**own, "UserPromptSubmit": {"identity_injector": _ENABLED, "hark_events": self._OWN}}

    def _provider(self, *rows: str) -> dict:
        names = ("UserPromptSubmit:identity_injector", *rows)
        return {"UserPromptSubmit": [_provider_entry(name) for name in names]}

    def test_an_own_handler_is_wired_by_the_project_row(self, tmp_path):
        result = _verify(tmp_path, self._provider("UserPromptSubmit:project"), self._project())
        assert (result["errors"], result["warnings"]) == ([], [])

    def test_an_own_handler_without_the_project_row_never_fires(self, tmp_path):
        result = _verify(tmp_path, self._provider(), self._project())
        assert result["errors"] == [_never_fires("UserPromptSubmit", "hark_events")]

    def test_the_row_does_not_wire_a_handler_outside_the_namespace(self, tmp_path):
        result = _verify(tmp_path, self._provider("UserPromptSubmit:project"), self._project(namespace=""))
        assert result["errors"] == [_never_fires("UserPromptSubmit", "hark_events")]

    def test_the_project_row_is_never_an_orphan(self, tmp_path):
        project = {"UserPromptSubmit": {"identity_injector": _ENABLED}}
        assert _verify(tmp_path, self._provider("UserPromptSubmit:project"), project)["warnings"] == []

    def test_an_own_handler_wired_by_codex_project_row_only(self, tmp_path):
        settings = tmp_path / "settings.json"
        settings.write_text(json.dumps({"hooks": {**_PRETOOL, **self._provider()}}), encoding="utf-8")
        codex = _codex_file(tmp_path, "UserPromptSubmit:project")
        project = {"hooks_enabled": True, **self._project()}
        result = wire_verify.verify_wiring(provider_path=settings, project_config=project, codex_path=codex)
        assert result["errors"] == []
        assert "UserPromptSubmit:hark_events: wired for Codex only" in result["info"]


class TestHandleCommand:
    def test_returns_false_for_non_verify(self):
        assert wire_verify.handle_command("status", []) is False

    def test_routes_verify_with_the_codex_home_hooks_file(self, capsys, tmp_path, monkeypatch):
        monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex_home"))
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
        monkeypatch.setenv("AIPASS_HOME", str(tmp_path / "home"))
        monkeypatch.setenv("SEED_HOME", str(tmp_path / "seed_home"))
        mock_result = {"ok": True, "errors": [], "warnings": [], "info": []}
        with patch.object(wire_verify, "verify_wiring", return_value=mock_result) as mock_verify:
            assert wire_verify.handle_command("verify", []) is True
        mock_verify.assert_called_once_with(
            codex_path=tmp_path / "codex_home" / "hooks.json",
            opencode_plugin=tmp_path / "cfg" / "opencode" / "plugins" / "aipass.ts",
            manifest_path=tmp_path / "home" / ".claude" / "provider_manifest.json",
            seed_path=tmp_path / "seed_home" / "hooks.json",
        )
        err = capsys.readouterr().err
        assert "Wire check passed" in err
        assert "0 errors, 0 warnings" in err

    def test_help_flag(self, capsys):
        with patch.object(wire_verify, "verify_wiring") as mock_verify:
            assert wire_verify.handle_command("verify", ["--help"]) is True
        mock_verify.assert_not_called()
        assert "Exits non-zero on any ERROR finding." in capsys.readouterr().err

    def test_help_word(self, capsys):
        with patch.object(wire_verify, "verify_wiring") as mock_verify:
            assert wire_verify.handle_command("verify", ["help"]) is True
        mock_verify.assert_not_called()
        assert "Exits non-zero on any ERROR finding." in capsys.readouterr().err

    def test_error_findings_exit_non_zero(self):
        """Its own --help promises 'Exits non-zero on any ERROR finding' — keep that promise.

        Returning True routed as handled, and hooks.main() turned that into exit 0,
        so a wiring break printed FAILED and reported success to any caller reading
        the exit code.
        """
        import pytest

        mock_result = {"ok": False, "errors": ["broken wiring"], "warnings": [], "info": []}
        with patch.object(wire_verify, "verify_wiring", return_value=mock_result):
            with pytest.raises(SystemExit) as exc:
                wire_verify.handle_command("verify", [])
        assert exc.value.code != 0

    def test_clean_run_does_not_exit(self, capsys, tmp_path, monkeypatch):
        """The passing path must stay a normal return — only ERROR findings exit."""
        monkeypatch.delenv("CODEX_HOME", raising=False)
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        monkeypatch.setenv("AIPASS_HOME", str(tmp_path / "home"))
        monkeypatch.delenv("SEED_HOME", raising=False)
        mock_result = {"ok": True, "errors": [], "warnings": ["cosmetic"], "info": []}
        with patch.object(wire_verify, "verify_wiring", return_value=mock_result) as mock_verify:
            assert wire_verify.handle_command("verify", []) is True
        mock_verify.assert_called_once_with(
            codex_path=tmp_path / ".codex" / "hooks.json",
            opencode_plugin=tmp_path / ".config" / "opencode" / "plugins" / "aipass.ts",
            manifest_path=tmp_path / "home" / ".claude" / "provider_manifest.json",
            seed_path=tmp_path / ".config" / "seed" / "hooks.json",
        )
        err = capsys.readouterr().err
        assert "Wire check passed" in err
        assert "cosmetic" in err
        assert "0 errors, 1 warnings" in err


class TestRenderResults:
    def test_renders_pass(self, capsys):
        """A pass prints the check glyph and the word passed on the real console (stderr).

        The product paints the headline green on a pass and red on a failure; plain
        text loses that colour, so the glyph that differs (✓ against ✗) is pinned.
        Proof the pin bites: a mutant that swaps the pass line's ✓ for ✗.
        """
        passed = {"ok": True, "errors": [], "warnings": [], "info": ["x"]}
        with patch.object(wire_verify, "verify_wiring", return_value=passed):
            assert wire_verify.handle_command("verify", []) is True
        err = capsys.readouterr().err
        assert "✓ Wire check passed" in err
        assert "✗" not in err
        assert "OK     x" in err

    def test_renders_fail(self, capsys):
        """A failure prints the cross glyph, FAILED, and the error under the ERROR word.

        Plain text loses the red of the headline and of the ERROR tag; the cross
        glyph (✗ against ✓) and the word ERROR are what still tell it from a pass.
        Proof the pin bites: a mutant that swaps the fail line's ✗ for ✓.
        """
        failed = {"ok": False, "errors": ["bad"], "warnings": [], "info": []}
        with patch.object(wire_verify, "verify_wiring", return_value=failed), pytest.raises(SystemExit):
            wire_verify.handle_command("verify", [])
        err = capsys.readouterr().err
        assert "✗ Wire check FAILED" in err
        assert "✓" not in err
        assert "ERROR  bad" in err


class TestPrintIntrospection:
    def test_runs_without_error(self, capsys):
        """Introspection names the module and what it checks.

        Was a bare call with no oracle: nothing printed would have passed.
        """
        wire_verify.print_introspection()

        assert "wire_verify — Provider ↔ project hook wiring checker" in capsys.readouterr().err


class TestSeedWiring:
    """A Seed head's hooks.json: install writes one seed.py row per event, verify reads them, remove takes them out."""

    def _verify(self, tmp_path, seed_path):
        settings = tmp_path / "settings.json"
        settings.write_text(json.dumps({"hooks": _PRETOOL}), encoding="utf-8")
        return wire_verify.verify_wiring(provider_path=settings, project_config={}, seed_path=seed_path)

    def _bridged(self, path) -> dict:
        table = json.loads(path.read_text(encoding="utf-8"))
        ours = {event: f"seed.py {event}" for event in table}
        return {event: [r for r in rows if r.get("command", "").endswith(ours[event])] for event, rows in table.items()}

    def test_install_twice_leaves_one_row_per_event_and_keeps_every_other_row(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SEED_HOME", str(tmp_path / "seed"))
        own = {"Stop": [{"builtin": "temporal"}], "Custom": [{"command": "echo hi"}]}
        (tmp_path / "seed").mkdir()
        (tmp_path / "seed" / "hooks.json").write_text(json.dumps(own), encoding="utf-8")
        wire_verify.seed_install()
        path = wire_verify.seed_install()
        assert path == tmp_path / "seed" / "hooks.json"
        bridged = self._bridged(path)
        assert {event: len(bridged.get(event, [])) for event in wire_verify.SEED_EVENTS} == dict.fromkeys(
            wire_verify.SEED_EVENTS, 1
        )
        (row,) = bridged["PreToolUse"]
        assert row["command"].split()[-2:] == [str(wire_verify.SEED_BRIDGE), "PreToolUse"]
        table = json.loads(path.read_text(encoding="utf-8"))
        assert table["Stop"][0] == {"builtin": "temporal"} and table["Custom"] == [{"command": "echo hi"}]

    def test_remove_leaves_no_bridge_row_and_every_other_row(self, tmp_path):
        path = tmp_path / "hooks.json"
        path.write_text(json.dumps({"Stop": [{"builtin": "temporal"}]}), encoding="utf-8")
        wire_verify.seed_install(path)
        wire_verify.seed_install(path, remove=True)
        assert json.loads(path.read_text(encoding="utf-8")) == {"Stop": [{"builtin": "temporal"}]}

    def test_a_file_seed_would_refuse_is_never_overwritten(self, tmp_path):
        path = tmp_path / "hooks.json"
        path.write_text(json.dumps({"Stop": {"command": "x"}}), encoding="utf-8")
        with pytest.raises(ValueError):
            wire_verify.seed_install(path)
        assert json.loads(path.read_text(encoding="utf-8")) == {"Stop": {"command": "x"}}

    def test_verify_reports_an_installed_seed_wiring(self, tmp_path):
        path = wire_verify.seed_install(tmp_path / "hooks.json")
        result = self._verify(tmp_path, path)
        assert result["errors"] == [] and result["ok"]
        assert f"Seed: 6 of 6 events bridged in {path}" in result["info"]

    def test_verify_names_a_missing_event_as_an_error_with_the_cure(self, tmp_path):
        path = wire_verify.seed_install(tmp_path / "hooks.json")
        table = json.loads(path.read_text(encoding="utf-8"))
        del table["PreToolUse"]
        path.write_text(json.dumps(table), encoding="utf-8")
        result = self._verify(tmp_path, path)
        assert result["errors"] == [f"Seed PreToolUse: no seed.py row in {path}. Fix: drone @hooks seed install"]

    def test_verify_warns_on_a_duplicate_bridge_row(self, tmp_path):
        path = wire_verify.seed_install(tmp_path / "hooks.json")
        table = json.loads(path.read_text(encoding="utf-8"))
        table["Stop"].append(dict(table["Stop"][0]))
        path.write_text(json.dumps(table), encoding="utf-8")
        assert [w for w in self._verify(tmp_path, path)["warnings"] if w.startswith("Seed Stop: 2 seed.py rows")]

    def test_no_seed_file_or_no_bridge_row_is_a_head_not_wired_not_an_error(self, tmp_path):
        (tmp_path / "hooks.json").write_text(json.dumps({"Stop": [{"builtin": "temporal"}]}), encoding="utf-8")
        for path in (tmp_path / "absent.json", tmp_path / "hooks.json"):
            result = self._verify(tmp_path, path)
            assert result["errors"] == []
            assert f"Seed: no AIPass rows in {path} (drone @hooks seed install wires them)" in result["info"]

    def test_a_malformed_seed_file_is_an_error(self, tmp_path):
        path = tmp_path / "hooks.json"
        path.write_text("[]", encoding="utf-8")
        (error,) = self._verify(tmp_path, path)["errors"]
        assert error.startswith("Seed hooks file unreadable") and "will not start" in error

    def test_the_seed_command_installs_and_removes_in_the_seed_home(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("SEED_HOME", str(tmp_path))
        assert wire_verify.handle_command("seed", ["install"]) is True
        assert self._bridged(tmp_path / "hooks.json")["Stop"]
        assert wire_verify.handle_command("seed", ["remove"]) is True
        assert json.loads((tmp_path / "hooks.json").read_text(encoding="utf-8")) == {}
        assert wire_verify.handle_command("seed", []) is True
        assert "drone @hooks seed install" in capsys.readouterr().err

    def test_a_seed_row_the_shell_cannot_split_is_an_error_and_blocks_install(self, tmp_path):
        path = tmp_path / "hooks.json"
        broken = {"Stop": [{"command": "python 'bridges/seed.py Stop"}]}
        path.write_text(json.dumps(broken), encoding="utf-8")
        (error,) = self._verify(tmp_path, path)["errors"]
        assert error.startswith(f"Seed hooks file {path}: a seed.py row the shell cannot split")
        with pytest.raises(ValueError):
            wire_verify.seed_install(path)
        assert json.loads(path.read_text(encoding="utf-8")) == broken
