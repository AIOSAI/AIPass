# =================== AIPass ====================
# Name: test_settings_gate.py
# Version: 1.0.0
# Description: Tests for the provider-settings gate: the decision table, the paths, the Bash shapes, the installers
# Branch: hooks
# Layer: tests
# Created: 2026-10-25
# Modified: 2026-10-25
# =============================================

"""Tests for apps/handlers/security/settings_gate.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that handlers/security/settings_gate.py parses and imports
# seedgo: no-test-needed(constant) — the ASK / DENY_* wording beyond the file, the kind and the @devpulse door
# seedgo: no-test-needed(documentation) — the module docstring's account of why Codex is deny-only

import json
import os
import sys

import pytest

import aipass.hooks.apps.modules.cc_sessions as cc_sessions_mod
from aipass.hooks.apps.handlers.security.settings_gate import handle

INTERACTIVE = ["/home/u/.local/bin/claude", "--resume", "s1"]
HEADLESS = ["/home/u/.local/bin/claude", "--resume", "s1", "-p", "Hi."]


@pytest.fixture
def seat(tmp_path, monkeypatch):
    """A home and an AIPass repo under tmp_path, and the claude process this call runs under (interactive)."""
    home, repo = tmp_path / "home", tmp_path / "repo"
    for folder in (home / ".codex" / "rules", home / ".claude", repo / ".claude", repo / ".codex", repo / "branch"):
        folder.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("AIPASS_HOME", str(repo))
    monkeypatch.delenv("CODEX_HOME", raising=False)
    monkeypatch.delenv("AIPASS_SESSION_TYPE", raising=False)
    argv = {"claude": INTERACTIVE}
    monkeypatch.setattr(cc_sessions_mod, "cli_ancestor", lambda name: argv.get(name))
    return {"home": home, "repo": repo, "cwd": str(repo / "branch"), "argv": argv}


def _write(seat, path, provider=None) -> dict:
    data = {"tool_name": "Write", "tool_input": {"file_path": str(path), "content": "x"}, "cwd": seat["cwd"]}
    if provider:
        data["provider"] = provider
    return handle(data)


def _bash(seat, command, provider=None) -> dict:
    data = {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": seat["cwd"]}
    if provider:
        data["provider"] = provider
    return handle(data)


def _decision(result: dict) -> str:
    """allow, ask or deny, read from the handler's answer as the engine reads it."""
    if result["exit_code"] == 2:
        assert json.loads(result["stdout"])["decision"] == "block"
        return "deny"
    if not result["stdout"]:
        return "allow"
    return json.loads(result["stdout"])["hookSpecificOutput"]["permissionDecision"]


def _reason(result: dict) -> str:
    doc = json.loads(result["stdout"])
    return doc.get("reason") or doc["hookSpecificOutput"]["permissionDecisionReason"]


class TestClaudeInteractive:
    def test_codex_settings_ask_the_owner_naming_the_file_and_the_call(self, seat):
        target = seat["home"] / ".codex" / "config.toml"
        result = _write(seat, target)
        assert _decision(result) == "ask"
        assert str(target) in _reason(result)
        assert "Write" in _reason(result)

    @pytest.mark.parametrize("parts", [(".claude", "provider_manifest.json"), (".codex", "hooks.json")])
    def test_the_repo_wiring_asks_the_owner(self, seat, parts):
        assert _decision(_write(seat, seat["repo"].joinpath(*parts))) == "ask"

    @pytest.mark.parametrize("name", ["settings.json", "settings.local.json"])
    def test_claudes_own_settings_need_no_second_ask(self, seat, name):
        assert _write(seat, seat["home"] / ".claude" / name) == {"stdout": "", "exit_code": 0}

    def test_a_bash_ask_names_the_command(self, seat):
        result = _bash(seat, "echo '# x' >> ~/.codex/config.toml")
        assert _decision(result) == "ask"
        assert "echo '# x' >> ~/.codex/config.toml" in _reason(result)


class TestHeadless:
    def test_a_print_mode_claude_is_denied_even_its_own_settings(self, seat):
        seat["argv"]["claude"] = HEADLESS
        result = _write(seat, seat["home"] / ".claude" / "settings.json")
        assert _decision(result) == "deny"
        assert "headless" in _reason(result)

    def test_a_dispatched_session_is_denied(self, seat, monkeypatch):
        monkeypatch.setenv("AIPASS_SESSION_TYPE", "dispatched")
        assert _decision(_write(seat, seat["home"] / ".codex" / "config.toml")) == "deny"

    def test_no_claude_process_above_the_call_is_denied(self, seat):
        seat["argv"]["claude"] = None
        assert _decision(_write(seat, seat["repo"] / ".codex" / "hooks.json")) == "deny"


class TestCodexCaller:
    @pytest.mark.parametrize(
        "parts",
        [
            (".codex", "config.toml"),
            (".codex", "work.toml"),
            (".codex", "hooks.json"),
            (".codex", "auth.json"),
            (".codex", "rules", "default.rules"),
            (".claude", "settings.json"),
        ],
    )
    def test_every_top_level_file_is_denied_with_the_devpulse_door(self, seat, parts):
        result = _write(seat, seat["home"].joinpath(*parts), provider="codex")
        assert _decision(result) == "deny"
        assert "Mail @devpulse, who asks Patrick" in _reason(result)
        assert str(seat["home"].joinpath(*parts)) in _reason(result)

    def test_an_interactive_claude_above_does_not_turn_a_codex_deny_into_an_ask(self, seat):
        assert _decision(_write(seat, seat["repo"] / ".claude" / "provider_manifest.json", provider="codex")) == "deny"

    def test_codex_home_is_protected_too(self, seat, tmp_path, monkeypatch):
        (tmp_path / "codex_home").mkdir()
        monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex_home"))
        assert _decision(_write(seat, tmp_path / "codex_home" / "config.toml", provider="codex")) == "deny"


class TestBashShapes:
    @pytest.mark.parametrize(
        "command",
        [
            "echo '# x' >> ~/.codex/config.toml",
            "sed -i 's/a/b/' ~/.codex/config.toml",
            "echo x | tee -a ~/.codex/config.toml",
            "cp new.toml ~/.codex/config.toml",
            "python3 -c \"open('~/.codex/config.toml', 'a').write('x')\"",
            "crudini --set ~/.codex/config.toml model gpt",
        ],
    )
    def test_each_shape_onto_codex_config_is_denied(self, seat, command):
        assert _decision(_bash(seat, command, provider="codex")) == "deny"

    def test_reading_codex_config_is_allowed(self, seat):
        assert _decision(_bash(seat, "cat ~/.codex/config.toml", provider="codex")) == "allow"


class TestUnprotected:
    @pytest.mark.parametrize("provider", [None, "codex"])
    def test_a_branch_settings_local_write_passes_untouched(self, seat, provider):
        target = seat["repo"] / "branch" / ".claude" / "settings.local.json"
        assert _write(seat, target, provider=provider) == {"stdout": "", "exit_code": 0}

    def test_a_codex_session_log_is_not_a_setting(self, seat):
        target = seat["home"] / ".codex" / "sessions" / "rollout.jsonl"
        assert _decision(_write(seat, target, provider="codex")) == "allow"

    def test_a_read_tool_is_never_judged(self, seat):
        data = {"tool_name": "Read", "tool_input": {"file_path": str(seat["home"] / ".codex" / "config.toml")}}
        assert handle(data) == {"stdout": "", "exit_code": 0}


class TestInstallers:
    @pytest.mark.parametrize(
        "command", ["aipass doctor --fix", "bash setup.sh", "python3 src/aipass/aipass/apps/provider_wire.py"]
    )
    def test_an_installer_asks_on_claude_and_is_denied_on_codex(self, seat, command):
        assert _decision(_bash(seat, command)) == "ask"
        assert _decision(_bash(seat, command, provider="codex")) == "deny"

    def test_doctor_without_fix_only_reads(self, seat):
        assert _decision(_bash(seat, "aipass doctor", provider="codex")) == "allow"


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges on Windows")
class TestSymlink:
    def test_a_link_elsewhere_landing_on_codex_config_is_denied(self, seat, tmp_path):
        target = seat["home"] / ".codex" / "config.toml"
        target.write_text("", encoding="utf-8")
        link = tmp_path / "innocent.toml"
        os.symlink(target, link)
        assert _decision(_write(seat, link, provider="codex")) == "deny"
