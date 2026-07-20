# =================== AIPass ====================
# Name: test_context_window.py
# Version: 1.0.0
# Description: Tests for shared context_window module
# Branch: hooks
# Created: 2026-07-20
# Modified: 2026-07-20
# =============================================

"""Tests for apps/modules/context_window.py."""

import json

import pytest


class TestFindBranchDir:
    def test_finds_branch_dir_from_nested_cwd(self, tmp_path):
        from aipass.hooks.apps.modules.context_window import find_branch_dir

        branch_dir = tmp_path / "src" / "aipass" / "widget"
        nested = branch_dir / "apps" / "handlers"
        nested.mkdir(parents=True)

        result = find_branch_dir(str(nested))
        assert result == branch_dir

    def test_falls_back_to_trinity_dir(self, tmp_path):
        from aipass.hooks.apps.modules.context_window import find_branch_dir

        (tmp_path / ".trinity").mkdir()
        result = find_branch_dir(str(tmp_path))
        assert result == tmp_path

    def test_returns_none_when_unresolvable(self, tmp_path):
        from aipass.hooks.apps.modules.context_window import find_branch_dir

        result = find_branch_dir(str(tmp_path))
        assert result is None


class TestReadLatestUsage:
    def test_returns_latest_assistant_usage(self, tmp_path):
        from aipass.hooks.apps.modules.context_window import read_latest_usage

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
        from aipass.hooks.apps.modules.context_window import read_latest_usage

        usage = read_latest_usage(str(tmp_path / "nope.jsonl"))
        assert usage is None

    def test_returns_none_for_empty_path(self):
        from aipass.hooks.apps.modules.context_window import read_latest_usage

        assert read_latest_usage("") is None

    def test_tail_read_skips_earlier_content(self, tmp_path):
        """Only the last ~tail_bytes are read — a partial leading line is tolerated."""
        from aipass.hooks.apps.modules.context_window import read_latest_usage

        transcript = tmp_path / "t.jsonl"
        filler = json.dumps({"type": "assistant", "message": {"usage": {"input_tokens": 1}}}) + "\n"
        target = json.dumps({"type": "assistant", "message": {"usage": {"input_tokens": 99}}})
        transcript.write_text(filler * 2000 + target, encoding="utf-8")

        usage = read_latest_usage(str(transcript), tail_bytes=200)
        assert usage == {"input_tokens": 99}

    def test_ignores_non_assistant_entries_without_usage(self, tmp_path):
        from aipass.hooks.apps.modules.context_window import read_latest_usage

        transcript = tmp_path / "t.jsonl"
        lines = [
            json.dumps({"type": "assistant", "message": {"usage": {"input_tokens": 5}}}),
            json.dumps({"type": "assistant", "message": {}}),
            "not json at all",
        ]
        transcript.write_text("\n".join(lines), encoding="utf-8")

        usage = read_latest_usage(str(transcript))
        assert usage == {"input_tokens": 5}


class TestContextFillTokens:
    def test_sums_all_three_fields(self):
        from aipass.hooks.apps.modules.context_window import context_fill_tokens

        usage = {"input_tokens": 1, "cache_read_input_tokens": 2, "cache_creation_input_tokens": 3}
        assert context_fill_tokens(usage) == 6

    def test_missing_fields_default_to_zero(self):
        from aipass.hooks.apps.modules.context_window import context_fill_tokens

        assert context_fill_tokens({}) == 0


class TestResolveCompactWindow:
    def test_env_var_takes_precedence(self, tmp_path, monkeypatch):
        from aipass.hooks.apps.modules.context_window import resolve_compact_window

        monkeypatch.setenv("CLAUDE_CODE_AUTO_COMPACT_WINDOW", "350000")
        assert resolve_compact_window(str(tmp_path)) == 350000

    def test_reads_branch_settings_when_no_env(self, tmp_path, monkeypatch):
        from aipass.hooks.apps.modules.context_window import resolve_compact_window

        monkeypatch.delenv("CLAUDE_CODE_AUTO_COMPACT_WINDOW", raising=False)
        branch_dir = tmp_path / "src" / "aipass" / "widget"
        claude_dir = branch_dir / ".claude"
        claude_dir.mkdir(parents=True)
        (claude_dir / "settings.local.json").write_text(json.dumps({"autoCompactWindow": 350000}), encoding="utf-8")

        assert resolve_compact_window(str(branch_dir)) == 350000

    def test_defaults_to_200k_when_nothing_found(self, tmp_path, monkeypatch):
        from aipass.hooks.apps.modules.context_window import resolve_compact_window

        monkeypatch.delenv("CLAUDE_CODE_AUTO_COMPACT_WINDOW", raising=False)
        assert resolve_compact_window(str(tmp_path)) == 200_000

    def test_bad_env_value_falls_through(self, tmp_path, monkeypatch):
        from aipass.hooks.apps.modules.context_window import resolve_compact_window

        monkeypatch.setenv("CLAUDE_CODE_AUTO_COMPACT_WINDOW", "not-a-number")
        assert resolve_compact_window(str(tmp_path)) == 200_000


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
