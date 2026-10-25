# =================== AIPass ====================
# Name: test_wire_verify.py
# Version: 1.2.0
# Description: Tests for wire_verify module — provider ↔ project hook wiring checker
# Branch: hooks
# Created: 2026-07-09
# Modified: 2026-10-25
# =============================================

"""Tests for apps/modules/wire_verify.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that wire_verify.py parses and imports, ruff and collection cover it
# seedgo: no-test-needed(documentation) — verify_wiring()'s and handle_command()'s docstrings, the documentation checker
# seedgo: no-test-needed(constant) — HELP_COMMANDS' entries and _META_KEYS' members, fixed literals
# seedgo: no-test-needed(stdlib) — json.loads' parsing of the settings file, the stdlib's own

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


def _codex_file(tmp_path, *event_args: str):
    """A project .codex/hooks.json wiring each Event[:hook] through the Codex bridge."""
    hooks: dict = {}
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
        claude_row = {"SessionStart": [_provider_entry("SessionStart:culture")]}
        codex_path.write_text(json.dumps({"hooks": claude_row}), encoding="utf-8")
        assert self._verify(tmp_path, codex_path)["errors"] == [_never_fires("SessionStart", "culture")]

    def test_no_codex_file_is_claude_only(self, tmp_path):
        result = self._verify(tmp_path, tmp_path / "missing.json")
        assert result["errors"] == [_never_fires("SessionStart", "culture")]


class TestHandleCommand:
    def test_returns_false_for_non_verify(self):
        assert wire_verify.handle_command("status", []) is False

    def test_routes_verify_with_the_projects_codex_file(self, capsys, tmp_path):
        mock_result = {"ok": True, "errors": [], "warnings": [], "info": []}
        with (
            patch.object(wire_verify, "locate_config", return_value=("AIPASS", tmp_path)),
            patch.object(wire_verify, "verify_wiring", return_value=mock_result) as mock_verify,
        ):
            assert wire_verify.handle_command("verify", []) is True
        mock_verify.assert_called_once_with(codex_path=tmp_path / ".codex" / "hooks.json")
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

    def test_clean_run_does_not_exit(self, capsys):
        """The passing path must stay a normal return — only ERROR findings exit."""
        mock_result = {"ok": True, "errors": [], "warnings": ["cosmetic"], "info": []}
        with (
            patch.object(wire_verify, "locate_config", return_value=("NONE", None)),
            patch.object(wire_verify, "verify_wiring", return_value=mock_result) as mock_verify,
        ):
            assert wire_verify.handle_command("verify", []) is True
        mock_verify.assert_called_once_with(codex_path=None)
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
