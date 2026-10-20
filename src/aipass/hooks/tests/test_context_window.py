# =================== AIPass ====================
# Name: test_context_window.py
# Version: 1.1.0
# Description: Tests for shared context_window module (model-aware window since 1.1.0)
# Branch: hooks
# Created: 2026-07-20
# Modified: 2026-10-19
# =============================================

"""Tests for apps/modules/context_window.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that context_window.py parses and imports, ruff and collection cover it
# seedgo: no-test-needed(documentation) — print_introspection()'s console text, the introspection standard covers it
# seedgo: no-test-needed(constant) — _DEFAULT_WINDOW and _TAIL_BYTES' values, pinned through the defaults asserted here
# seedgo: no-test-needed(constant) — NATIVE_1M_MODELS' membership, pinned through the ids model_window is asserted on
# seedgo: no-test-needed(stdlib) — json.loads' handling of malformed lines, the stdlib's own

import json

import pytest

from aipass.hooks.apps.modules import context_window
from aipass.hooks.apps.modules.context_window import (
    AUTOCOMPACT_BUFFER,
    compact_threshold,
    context_fill_tokens,
    explicit_window,
    find_branch_dir,
    model_window,
    read_latest_model,
    read_latest_usage,
    resolve_compact_window,
    user_settings_path,
)


@pytest.fixture(autouse=True)
def user_settings(tmp_path, monkeypatch):
    """The user-level Claude Code settings file, moved under tmp_path; absent until a test writes it."""
    path = tmp_path / "home" / "user_settings.json"
    monkeypatch.setattr(context_window, "user_settings_path", lambda: path)
    return path


def _branch_settings(tmp_path, name, data):
    branch_dir = tmp_path / "src" / "aipass" / "widget"
    claude_dir = branch_dir / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    (claude_dir / name).write_text(json.dumps(data), encoding="utf-8")
    return branch_dir


class TestFindBranchDir:
    def test_finds_branch_dir_from_nested_cwd(self, tmp_path):
        branch_dir = tmp_path / "src" / "aipass" / "widget"
        nested = branch_dir / "apps" / "handlers"
        nested.mkdir(parents=True)

        result = find_branch_dir(str(nested))
        assert result == branch_dir

    def test_falls_back_to_trinity_dir(self, tmp_path):
        (tmp_path / ".trinity").mkdir()
        result = find_branch_dir(str(tmp_path))
        assert result == tmp_path

    def test_returns_none_when_unresolvable(self, tmp_path):
        result = find_branch_dir(str(tmp_path))
        assert result is None


class TestReadLatestUsage:
    def test_returns_latest_assistant_usage(self, tmp_path):
        transcript = tmp_path / "t.jsonl"
        lines = [
            json.dumps(
                {"type": "assistant", "message": {"usage": {"input_tokens": 1, "cache_read_input_tokens": 100}}}
            ),
            json.dumps({"type": "user", "message": {}}),
            json.dumps(
                {"type": "assistant", "message": {"usage": {"input_tokens": 2, "cache_read_input_tokens": 200}}}
            ),
        ]
        transcript.write_text("\n".join(lines), encoding="utf-8")

        usage = read_latest_usage(str(transcript))
        assert usage == {"input_tokens": 2, "cache_read_input_tokens": 200}

    def test_returns_none_for_missing_file(self, tmp_path):
        usage = read_latest_usage(str(tmp_path / "nope.jsonl"))
        assert usage is None

    def test_returns_none_for_empty_path(self):
        assert read_latest_usage("") is None

    def test_tail_read_skips_earlier_content(self, tmp_path):
        """Only the last ~tail_bytes are read — a partial leading line is tolerated."""
        transcript = tmp_path / "t.jsonl"
        filler = json.dumps({"type": "assistant", "message": {"usage": {"input_tokens": 1}}}) + "\n"
        target = json.dumps({"type": "assistant", "message": {"usage": {"input_tokens": 99}}})
        transcript.write_text(filler * 2000 + target, encoding="utf-8")

        usage = read_latest_usage(str(transcript), tail_bytes=200)
        assert usage == {"input_tokens": 99}

    def test_ignores_non_assistant_entries_without_usage(self, tmp_path):
        transcript = tmp_path / "t.jsonl"
        lines = [
            json.dumps({"type": "assistant", "message": {"usage": {"input_tokens": 5}}}),
            json.dumps({"type": "assistant", "message": {}}),
            "not json at all",
        ]
        transcript.write_text("\n".join(lines), encoding="utf-8")

        usage = read_latest_usage(str(transcript))
        assert usage == {"input_tokens": 5}


class TestReadLatestModel:
    def test_returns_the_latest_assistant_lines_model(self, tmp_path):
        transcript = tmp_path / "t.jsonl"
        lines = [
            json.dumps({"type": "assistant", "message": {"model": "claude-haiku-5-5", "usage": {}}}),
            json.dumps({"type": "user", "message": {"model": "not-this"}}),
            json.dumps({"type": "assistant", "message": {"model": "claude-opus-5-5", "usage": {}}}),
        ]
        transcript.write_text("\n".join(lines), encoding="utf-8")

        assert read_latest_model(str(transcript)) == "claude-opus-5-5"

    def test_returns_empty_when_no_assistant_line(self, tmp_path):
        transcript = tmp_path / "t.jsonl"
        transcript.write_text(json.dumps({"type": "user", "message": {}}), encoding="utf-8")

        assert read_latest_model(str(transcript)) == ""
        assert read_latest_model("") == ""


class TestModelWindow:
    @pytest.mark.parametrize(
        ("model_id", "expected"),
        [
            ("claude-opus-5-5", 1_000_000),
            ("claude-opus-5-5-20261001", 1_000_000),
            ("claude-haiku-5-5", 200_000),
            ("claude-sonnet-4-6[1m]", 1_000_000),
            ("claude-sonnet-4-6[1M]", 1_000_000),
            ("claude-opus-4-5-20251101", 200_000),
            ("", 200_000),
        ],
    )
    def test_window_follows_the_model_id(self, model_id, expected):
        assert model_window(model_id) == expected


class TestCompactThreshold:
    def test_threshold_is_window_minus_the_33k_buffer(self):
        assert AUTOCOMPACT_BUFFER == 33_000
        assert compact_threshold(200_000) == 167_000
        assert compact_threshold(1_000_000) == 967_000


class TestUserSettingsPath:
    def test_the_user_file_is_read_under_home_at_call_time(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
        assert user_settings_path() == tmp_path / ".claude" / "settings.json"


class TestContextFillTokens:
    def test_sums_all_three_fields(self):
        usage = {"input_tokens": 1, "cache_read_input_tokens": 2, "cache_creation_input_tokens": 3}
        assert context_fill_tokens(usage) == 6

    def test_missing_fields_default_to_zero(self):
        assert context_fill_tokens({}) == 0


class TestResolveCompactWindow:
    def test_env_var_takes_precedence(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_AUTO_COMPACT_WINDOW", "350000")
        assert resolve_compact_window(str(tmp_path)) == 350000

    def test_reads_branch_settings_when_no_env(self, tmp_path, monkeypatch):
        monkeypatch.delenv("CLAUDE_CODE_AUTO_COMPACT_WINDOW", raising=False)
        branch_dir = tmp_path / "src" / "aipass" / "widget"
        claude_dir = branch_dir / ".claude"
        claude_dir.mkdir(parents=True)
        (claude_dir / "settings.local.json").write_text(json.dumps({"autoCompactWindow": 350000}), encoding="utf-8")

        assert resolve_compact_window(str(branch_dir)) == 350000

    def test_defaults_to_200k_when_nothing_found(self, tmp_path, monkeypatch):
        monkeypatch.delenv("CLAUDE_CODE_AUTO_COMPACT_WINDOW", raising=False)
        assert resolve_compact_window(str(tmp_path)) == 200_000

    def test_bad_env_value_falls_through(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_AUTO_COMPACT_WINDOW", "not-a-number")
        assert resolve_compact_window(str(tmp_path)) == 200_000

    def test_a_1m_model_with_nothing_explicit_gets_1m(self, tmp_path, monkeypatch):
        monkeypatch.delenv("CLAUDE_CODE_AUTO_COMPACT_WINDOW", raising=False)
        assert explicit_window(str(tmp_path)) is None
        assert resolve_compact_window(str(tmp_path), "claude-opus-5-5") == 1_000_000

    def test_explicit_350k_caps_a_1m_model(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_AUTO_COMPACT_WINDOW", "350000")
        assert resolve_compact_window(str(tmp_path), "claude-opus-5-5") == 350_000

    def test_explicit_350k_never_raises_a_200k_model(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_AUTO_COMPACT_WINDOW", "350000")
        assert resolve_compact_window(str(tmp_path), "claude-haiku-5-5") == 200_000

    def test_env_below_100k_is_clamped_up(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_AUTO_COMPACT_WINDOW", "50000")
        assert explicit_window(str(tmp_path)) == 100_000
        assert resolve_compact_window(str(tmp_path), "claude-opus-5-5") == 100_000

    def test_env_above_1m_is_clamped_down(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_AUTO_COMPACT_WINDOW", "5000000")
        assert explicit_window(str(tmp_path)) == 1_000_000

    def test_user_settings_are_read_when_the_branch_sets_none(self, tmp_path, monkeypatch, user_settings):
        monkeypatch.delenv("CLAUDE_CODE_AUTO_COMPACT_WINDOW", raising=False)
        user_settings.parent.mkdir(parents=True)
        user_settings.write_text(json.dumps({"autoCompactWindow": 400000}), encoding="utf-8")

        assert resolve_compact_window(str(tmp_path), "claude-opus-5-5") == 400_000

    def test_branch_auto_falls_through_to_the_user_value(self, tmp_path, monkeypatch, user_settings):
        monkeypatch.delenv("CLAUDE_CODE_AUTO_COMPACT_WINDOW", raising=False)
        branch_dir = _branch_settings(tmp_path, "settings.local.json", {"autoCompactWindow": "auto"})
        user_settings.parent.mkdir(parents=True)
        user_settings.write_text(json.dumps({"autoCompactWindow": 400000}), encoding="utf-8")

        assert resolve_compact_window(str(branch_dir), "claude-opus-5-5") == 400_000

    def test_an_unreadable_branch_file_falls_through_to_the_user_value(self, tmp_path, monkeypatch, user_settings):
        monkeypatch.delenv("CLAUDE_CODE_AUTO_COMPACT_WINDOW", raising=False)
        branch_dir = _branch_settings(tmp_path, "settings.local.json", {})
        (branch_dir / ".claude" / "settings.local.json").write_text("{not json", encoding="utf-8")
        user_settings.parent.mkdir(parents=True)
        user_settings.write_text(json.dumps({"autoCompactWindow": 400000}), encoding="utf-8")

        assert resolve_compact_window(str(branch_dir), "claude-opus-5-5") == 400_000

    def test_branch_settings_json_beats_the_user_value(self, tmp_path, monkeypatch, user_settings):
        monkeypatch.delenv("CLAUDE_CODE_AUTO_COMPACT_WINDOW", raising=False)
        branch_dir = _branch_settings(tmp_path, "settings.json", {"autoCompactWindow": 300000})
        user_settings.parent.mkdir(parents=True)
        user_settings.write_text(json.dumps({"autoCompactWindow": 400000}), encoding="utf-8")

        assert resolve_compact_window(str(branch_dir), "claude-opus-5-5") == 300_000


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
