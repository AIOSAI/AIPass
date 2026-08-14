"""Tests for wire_verify module — provider ↔ project hook wiring checker."""

import json
from unittest.mock import patch

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


class TestExtractBridgeArg:
    def test_filtered_arg(self):
        entry = _provider_entry("UserPromptSubmit:tier0_kernel")
        assert wire_verify._extract_bridge_arg(entry) == "UserPromptSubmit:tier0_kernel"

    def test_unfiltered_arg(self):
        entry = _provider_entry("Stop")
        assert wire_verify._extract_bridge_arg(entry) == "Stop"

    def test_no_bridge_marker(self):
        entry = {"hooks": [{"command": "echo hello"}]}
        assert wire_verify._extract_bridge_arg(entry) is None

    def test_empty_hooks(self):
        assert wire_verify._extract_bridge_arg({"hooks": []}) is None

    def test_no_hooks_key(self):
        assert wire_verify._extract_bridge_arg({}) is None


class TestBuildProviderIndex:
    def test_builds_filtered_index(self):
        provider = {
            "UserPromptSubmit": [
                _provider_entry("UserPromptSubmit:identity_injector"),
                _provider_entry("UserPromptSubmit:branch_prompt"),
            ],
        }
        errors = []
        idx = wire_verify._build_provider_index(provider, errors)
        assert errors == []
        assert idx["UserPromptSubmit"]["filtered"]["identity_injector"] == {"": 1}
        assert idx["UserPromptSubmit"]["filtered"]["branch_prompt"] == {"": 1}
        assert idx["UserPromptSubmit"]["unfiltered"] == 0

    def test_builds_unfiltered_index(self):
        provider = {"Stop": [_provider_entry("Stop")]}
        errors = []
        idx = wire_verify._build_provider_index(provider, errors)
        assert idx["Stop"]["unfiltered"] == 1
        assert idx["Stop"]["filtered"] == {}

    def test_empty_array_errors(self):
        provider = {"SessionStart": []}
        errors = []
        idx = wire_verify._build_provider_index(provider, errors)
        assert len(errors) == 1
        assert "EMPTY" in errors[0]
        assert idx["SessionStart"]["empty"] is True

    def test_duplicate_filtered_counted(self):
        provider = {
            "PreCompact": [
                _provider_entry("PreCompact:pre_compact"),
                _provider_entry("PreCompact:pre_compact"),
            ],
        }
        errors = []
        idx = wire_verify._build_provider_index(provider, errors)
        assert idx["PreCompact"]["filtered"]["pre_compact"] == {"": 2}

    def test_distinct_matchers_not_duplicate(self):
        provider = {
            "PreCompact": [
                _provider_entry("PreCompact:pre_compact", matcher="manual"),
                _provider_entry("PreCompact:pre_compact", matcher="auto"),
            ],
        }
        errors = []
        idx = wire_verify._build_provider_index(provider, errors)
        assert idx["PreCompact"]["filtered"]["pre_compact"] == {"manual": 1, "auto": 1}


class TestCheckEventWiring:
    def test_unfiltered_ok(self):
        pidx = {"filtered": {}, "unfiltered": 1, "empty": False}
        hooks_group = {"stop_sound": {"enabled": True, "handler": "x"}}
        errors, warnings, info = [], [], []
        wire_verify._check_event_wiring("Stop", hooks_group, pidx, errors, warnings, info)
        assert errors == []
        assert any("unfiltered" in i for i in info)

    def test_missing_provider_event(self):
        hooks_group = {"cadence_reset": {"enabled": True, "handler": "x"}}
        errors, warnings, info = [], [], []
        wire_verify._check_event_wiring("SessionStart", hooks_group, None, errors, warnings, info)
        assert len(errors) == 1
        assert "NO provider event entry" in errors[0]

    def test_missing_per_hook_entry(self):
        pidx = {"filtered": {"identity_injector": {"": 1}}, "unfiltered": 0, "empty": False}
        hooks_group = {
            "identity_injector": {"enabled": True, "handler": "x"},
            "presence_gate": {"enabled": True, "handler": "y"},
        }
        errors, warnings, info = [], [], []
        wire_verify._check_event_wiring("UserPromptSubmit", hooks_group, pidx, errors, warnings, info)
        assert len(errors) == 1
        assert "presence_gate" in errors[0]
        assert "never fires" in errors[0]

    def test_duplicate_per_hook_warns(self):
        pidx = {"filtered": {"pre_compact": {"": 2}}, "unfiltered": 0, "empty": False}
        hooks_group = {"pre_compact": {"enabled": True, "handler": "x"}}
        errors, warnings, info = [], [], []
        wire_verify._check_event_wiring("PreCompact", hooks_group, pidx, errors, warnings, info)
        assert errors == []
        assert len(warnings) == 1
        assert "duplicate" in warnings[0]

    def test_distinct_matchers_no_warning(self):
        pidx = {"filtered": {"pre_compact": {"manual": 1, "auto": 1}}, "unfiltered": 0, "empty": False}
        hooks_group = {"pre_compact": {"enabled": True, "handler": "x"}}
        errors, warnings, info = [], [], []
        wire_verify._check_event_wiring("PreCompact", hooks_group, pidx, errors, warnings, info)
        assert errors == []
        assert warnings == []

    def test_orphaned_provider_entry(self):
        pidx = {"filtered": {"ghost_hook": {"": 1}}, "unfiltered": 0, "empty": False}
        hooks_group = {"real_hook": {"enabled": True, "handler": "x"}}
        errors, warnings, info = [], [], []
        wire_verify._check_event_wiring("UserPromptSubmit", hooks_group, pidx, errors, warnings, info)
        assert any("orphaned" in w for w in warnings)

    def test_disabled_hooks_skipped(self):
        pidx = {"filtered": {}, "unfiltered": 0, "empty": False}
        hooks_group = {"disabled_hook": {"enabled": False, "handler": "x"}}
        errors, warnings, info = [], [], []
        wire_verify._check_event_wiring("UserPromptSubmit", hooks_group, pidx, errors, warnings, info)
        assert errors == []

    def test_empty_provider_skipped(self):
        pidx = {"filtered": {}, "unfiltered": 0, "empty": True}
        hooks_group = {"cadence_reset": {"enabled": True, "handler": "x"}}
        errors, warnings, info = [], [], []
        wire_verify._check_event_wiring("SessionStart", hooks_group, pidx, errors, warnings, info)
        assert errors == []

    def test_duplicate_unfiltered_warns(self):
        pidx = {"filtered": {}, "unfiltered": 3, "empty": False}
        hooks_group = {"stop_sound": {"enabled": True, "handler": "x"}}
        errors, warnings, info = [], [], []
        wire_verify._check_event_wiring("Stop", hooks_group, pidx, errors, warnings, info)
        assert len(warnings) == 1
        assert "duplicate unfiltered" in warnings[0]

    def test_provider_wired_false_still_errors(self):
        pidx = {"filtered": {"identity_injector": {"": 1}}, "unfiltered": 0, "empty": False}
        hooks_group = {
            "identity_injector": {"enabled": True, "handler": "x"},
            "presence_gate": {"enabled": True, "handler": "y", "provider_wired": False},
        }
        errors, warnings, info = [], [], []
        wire_verify._check_event_wiring("UserPromptSubmit", hooks_group, pidx, errors, warnings, info)
        assert any("presence_gate" in e for e in errors)

    def test_provider_wired_false_no_event_still_errors(self):
        hooks_group = {
            "presence_gate": {"enabled": True, "handler": "y", "provider_wired": False},
        }
        errors, warnings, info = [], [], []
        wire_verify._check_event_wiring("UserPromptSubmit", hooks_group, None, errors, warnings, info)
        assert len(errors) == 1
        assert "NO provider event entry" in errors[0]


class TestVerifyWiring:
    def test_all_good(self, tmp_path):
        settings = tmp_path / "settings.json"
        settings.write_text(json.dumps({"hooks": GOOD_PROVIDER}))
        result = wire_verify.verify_wiring(provider_path=settings, project_config=GOOD_PROJECT)
        assert result["ok"] is True
        assert result["errors"] == []

    def test_empty_provider_array(self, tmp_path):
        provider = {**GOOD_PROVIDER, "SessionStart": []}
        settings = tmp_path / "settings.json"
        settings.write_text(json.dumps({"hooks": provider}))
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
        settings.write_text(json.dumps({"hooks": GOOD_PROVIDER}))
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
        settings.write_text(json.dumps({"hooks": provider}))
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
        settings.write_text(json.dumps({"hooks": GOOD_PROVIDER}))
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
        settings.write_text(json.dumps({"hooks": provider}))
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
        settings.write_text(json.dumps({"hooks": provider}))
        result = wire_verify.verify_wiring(provider_path=settings, project_config=GOOD_PROJECT)
        assert any("provider-only" in i for i in result["info"])

    def test_meta_keys_ignored(self, tmp_path):
        settings = tmp_path / "settings.json"
        settings.write_text(json.dumps({"hooks": GOOD_PROVIDER}))
        project = {**GOOD_PROJECT, "_comment": "test", "hooks_enabled": True}
        result = wire_verify.verify_wiring(provider_path=settings, project_config=project)
        assert result["ok"] is True


class TestReadProviderHooks:
    def test_reads_file(self, tmp_path):
        settings = tmp_path / "settings.json"
        settings.write_text(json.dumps({"hooks": {"Stop": []}}))
        result = wire_verify._read_provider_hooks(settings)
        assert "Stop" in result

    def test_missing_file_returns_empty(self, tmp_path):
        result = wire_verify._read_provider_hooks(tmp_path / "missing.json")
        assert result == {}

    def test_malformed_json_returns_empty(self, tmp_path):
        settings = tmp_path / "settings.json"
        settings.write_text("not json{{{")
        result = wire_verify._read_provider_hooks(settings)
        assert result == {}


class TestHandleCommand:
    def test_returns_false_for_non_verify(self):
        assert wire_verify.handle_command("status", []) is False

    def test_routes_verify(self):
        mock_result = {"ok": True, "errors": [], "warnings": [], "info": []}
        with patch.object(wire_verify, "verify_wiring", return_value=mock_result):
            assert wire_verify.handle_command("verify", []) is True

    def test_help_flag(self):
        assert wire_verify.handle_command("verify", ["--help"]) is True

    def test_help_word(self):
        assert wire_verify.handle_command("verify", ["help"]) is True

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

    def test_clean_run_does_not_exit(self):
        """The passing path must stay a normal return — only ERROR findings exit."""
        mock_result = {"ok": True, "errors": [], "warnings": ["cosmetic"], "info": []}
        with patch.object(wire_verify, "verify_wiring", return_value=mock_result):
            assert wire_verify.handle_command("verify", []) is True


class TestRenderResults:
    def test_renders_pass(self):
        from io import StringIO

        from rich.console import Console

        buf = StringIO()
        test_console = Console(file=buf, force_terminal=False)
        with patch.object(wire_verify, "CONSOLE", test_console):
            wire_verify._render_results({"ok": True, "errors": [], "warnings": [], "info": ["x"]})
        output = buf.getvalue()
        assert "passed" in output

    def test_renders_fail(self):
        from io import StringIO

        from rich.console import Console

        buf = StringIO()
        test_console = Console(file=buf, force_terminal=False)
        with patch.object(wire_verify, "CONSOLE", test_console):
            wire_verify._render_results({"ok": False, "errors": ["bad"], "warnings": [], "info": []})
        output = buf.getvalue()
        assert "FAILED" in output
        assert "bad" in output


class TestPrintIntrospection:
    def test_runs_without_error(self):
        wire_verify.print_introspection()
