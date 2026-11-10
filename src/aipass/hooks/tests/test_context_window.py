# =================== AIPass ====================
# Name: test_context_window.py
# Version: 1.8.0
# Description: Tests for shared context_window module (live status-line window since 1.8.0)
# Branch: hooks
# Created: 2026-07-20
# Modified: 2026-11-10
# =============================================

"""Tests for apps/modules/context_window.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# sentry: no-test-needed(ruff) — that context_window.py parses and imports, ruff and collection cover it
# sentry: no-test-needed(documentation) — print_introspection()'s console text, the introspection standard covers it
# sentry: no-test-needed(constant) — _TAIL_BYTES' value, pinned through the defaults asserted here
# sentry: no-test-needed(stdlib) — json.loads' handling of malformed lines, the stdlib's own

import json

import pytest

from aipass.hooks.apps.modules import context_window
from aipass.hooks.apps.modules.context_window import (
    AUTOCOMPACT_BUFFER,
    compact_threshold,
    context_fill_tokens,
    explicit_window,
    find_branch_dir,
    live_window,
    live_window_path,
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


@pytest.fixture(autouse=True)
def live_dir(tmp_path, monkeypatch):
    """The temp dir the status line's window files live in, moved under tmp_path."""
    monkeypatch.setattr(context_window, "_STATE_DIR", tmp_path)
    return tmp_path


def _path(session_id):
    path = live_window_path(session_id)
    assert path is not None
    return path


def _live(session_id, size):
    """The file the status line writes for a session: its payload's context_window_size."""
    _path(session_id).write_text(json.dumps({"context_window_size": size}), encoding="utf-8")


def _branch_settings(tmp_path, name, data):
    branch_dir = tmp_path / "src" / "aipass" / "widget"
    claude_dir = branch_dir / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    (claude_dir / name).write_text(json.dumps(data), encoding="utf-8")
    return branch_dir


def _codex_rollout(path, total_tokens, window: int | None = 475_000, model="gpt-6.1-sol"):
    """A Codex rollout in the shape 0.164 writes: session_meta, turn_context, the newest token_count."""
    usage = {"input_tokens": total_tokens - 568, "cached_input_tokens": 7680, "output_tokens": 568}
    info: dict[str, object] = {
        "total_token_usage": dict(usage, total_tokens=total_tokens),
        "last_token_usage": dict(usage, total_tokens=total_tokens),
    }
    if window is not None:
        info["model_context_window"] = window
    lines = [
        {"type": "session_meta", "payload": {"id": "s", "cwd": "/x", "source": "cli", "cli_version": "0.164.0"}},
        {"type": "turn_context", "payload": {"cwd": "/x", "model": model, "effort": "medium"}},
        {"type": "event_msg", "payload": {"type": "token_count", "info": info, "rate_limits": {}}},
    ]
    path.write_text("\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8")


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

    def test_a_missing_transcript_at_turn_zero_logs_no_info_line(self, tmp_path, caplog):
        caplog.set_level("DEBUG")
        assert read_latest_usage(str(tmp_path / "nope.jsonl")) is None
        assert not [r for r in caplog.records if r.levelname == "INFO" and "transcript" in r.getMessage()]

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

    def test_a_usage_older_than_the_tail_is_still_found(self, tmp_path):
        """A long tool result after the last assistant turn fills the whole tail."""
        transcript = tmp_path / "t.jsonl"
        target = json.dumps({"type": "assistant", "message": {"usage": {"input_tokens": 7}}}) + "\n"
        tool_result = json.dumps({"type": "user", "message": {"content": "x" * 5000}}) + "\n"
        transcript.write_text(target + tool_result * 3, encoding="utf-8")

        assert read_latest_usage(str(transcript), tail_bytes=200) == {"input_tokens": 7}

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


class TestLiveWindow:
    def test_the_file_sits_beside_the_hook_state_keyed_by_session(self, live_dir):
        assert live_window_path("ses-1") == live_dir / "aipass-cc-window-ses-1.json"

    def test_a_positive_int_size_is_the_window(self):
        _live("ses-1", 1_000_000)
        assert live_window("ses-1") == 1_000_000

    @pytest.mark.parametrize("size", [0, -5, True, 1.5, "200000", None, [200_000]])
    def test_anything_but_a_positive_int_is_unknown(self, size):
        _live("ses-1", size)
        assert live_window("ses-1") is None

    def test_no_file_torn_json_or_a_non_object_is_unknown(self):
        assert live_window("ses-1") is None
        _path("ses-1").write_text("{torn", encoding="utf-8")
        assert live_window("ses-1") is None
        _path("ses-1").write_text("[1000000]", encoding="utf-8")
        assert live_window("ses-1") is None

    @pytest.mark.parametrize("session_id", ["", "../ses-1", "a/b", "ses 1"])
    def test_a_session_id_that_is_not_a_plain_name_reads_nothing(self, session_id, live_dir):
        _live("ses-1", 1_000_000)
        assert live_window_path(session_id) is None
        assert live_window(session_id) is None


class TestCompactThreshold:
    def test_threshold_is_window_minus_the_33k_buffer(self):
        assert AUTOCOMPACT_BUFFER == 33_000
        assert compact_threshold(200_000) == 167_000
        assert compact_threshold(1_000_000) == 967_000

    def test_an_unknown_window_has_no_threshold(self):
        assert compact_threshold(None) is None


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
        _live("s", 1_000_000)
        assert resolve_compact_window(str(tmp_path), "s") == 350000

    def test_reads_branch_settings_when_no_env(self, tmp_path, monkeypatch):
        monkeypatch.delenv("CLAUDE_CODE_AUTO_COMPACT_WINDOW", raising=False)
        branch_dir = tmp_path / "src" / "aipass" / "widget"
        claude_dir = branch_dir / ".claude"
        claude_dir.mkdir(parents=True)
        (claude_dir / "settings.local.json").write_text(json.dumps({"autoCompactWindow": 350000}), encoding="utf-8")
        _live("s", 1_000_000)

        assert resolve_compact_window(str(branch_dir), "s") == 350000

    def test_no_live_window_is_unknown_even_under_an_explicit_window(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_AUTO_COMPACT_WINDOW", "350000")
        assert resolve_compact_window(str(tmp_path), "s") is None
        assert resolve_compact_window(str(tmp_path)) is None

    def test_bad_env_value_leaves_the_live_window(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_AUTO_COMPACT_WINDOW", "not-a-number")
        _live("s", 200_000)
        assert resolve_compact_window(str(tmp_path), "s") == 200_000

    def test_a_live_1m_capped_at_350k_compacts_at_317k(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_AUTO_COMPACT_WINDOW", "350000")
        _live("s", 1_000_000)
        window = resolve_compact_window(str(tmp_path), "s")
        assert window == 350_000
        assert compact_threshold(window) == 317_000

    def test_a_window_no_code_knows_is_read_as_the_status_line_reports_it(self, tmp_path, monkeypatch):
        monkeypatch.delenv("CLAUDE_CODE_AUTO_COMPACT_WINDOW", raising=False)
        _live("s", 750_000)
        assert explicit_window(str(tmp_path)) is None
        assert resolve_compact_window(str(tmp_path), "s") == 750_000

    def test_explicit_350k_never_raises_a_live_200k(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_AUTO_COMPACT_WINDOW", "350000")
        _live("s", 200_000)
        assert resolve_compact_window(str(tmp_path), "s") == 200_000

    def test_env_below_100k_is_clamped_up(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_AUTO_COMPACT_WINDOW", "50000")
        _live("s", 1_000_000)
        assert explicit_window(str(tmp_path)) == 100_000
        assert resolve_compact_window(str(tmp_path), "s") == 100_000

    def test_env_above_1m_is_clamped_down(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_AUTO_COMPACT_WINDOW", "5000000")
        assert explicit_window(str(tmp_path)) == 1_000_000

    def test_user_settings_are_read_when_the_branch_sets_none(self, tmp_path, monkeypatch, user_settings):
        monkeypatch.delenv("CLAUDE_CODE_AUTO_COMPACT_WINDOW", raising=False)
        user_settings.parent.mkdir(parents=True)
        user_settings.write_text(json.dumps({"autoCompactWindow": 400000}), encoding="utf-8")
        _live("s", 1_000_000)

        assert resolve_compact_window(str(tmp_path), "s") == 400_000

    def test_branch_auto_falls_through_to_the_user_value(self, tmp_path, monkeypatch, user_settings):
        monkeypatch.delenv("CLAUDE_CODE_AUTO_COMPACT_WINDOW", raising=False)
        branch_dir = _branch_settings(tmp_path, "settings.local.json", {"autoCompactWindow": "auto"})
        user_settings.parent.mkdir(parents=True)
        user_settings.write_text(json.dumps({"autoCompactWindow": 400000}), encoding="utf-8")
        _live("s", 1_000_000)

        assert resolve_compact_window(str(branch_dir), "s") == 400_000

    def test_an_unreadable_branch_file_falls_through_to_the_user_value(self, tmp_path, monkeypatch, user_settings):
        monkeypatch.delenv("CLAUDE_CODE_AUTO_COMPACT_WINDOW", raising=False)
        branch_dir = _branch_settings(tmp_path, "settings.local.json", {})
        (branch_dir / ".claude" / "settings.local.json").write_text("{not json", encoding="utf-8")
        user_settings.parent.mkdir(parents=True)
        user_settings.write_text(json.dumps({"autoCompactWindow": 400000}), encoding="utf-8")
        _live("s", 1_000_000)

        assert resolve_compact_window(str(branch_dir), "s") == 400_000

    def test_branch_settings_json_beats_the_user_value(self, tmp_path, monkeypatch, user_settings):
        monkeypatch.delenv("CLAUDE_CODE_AUTO_COMPACT_WINDOW", raising=False)
        branch_dir = _branch_settings(tmp_path, "settings.json", {"autoCompactWindow": 300000})
        user_settings.parent.mkdir(parents=True)
        user_settings.write_text(json.dumps({"autoCompactWindow": 400000}), encoding="utf-8")
        _live("s", 1_000_000)

        assert resolve_compact_window(str(branch_dir), "s") == 300_000


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


class TestCodexConfigPath:
    """The seam the gauge tests patch, run for real: $CODEX_HOME wins, else ~/.codex."""

    def test_codex_home_holds_the_config(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CODEX_HOME", str(tmp_path))
        assert context_window.codex_config_path() == tmp_path / "config.toml"

    def test_without_codex_home_it_is_under_the_home_dot_codex(self, tmp_path, monkeypatch):
        monkeypatch.delenv("CODEX_HOME", raising=False)
        for name in ("HOME", "USERPROFILE"):  # Path.home() reads HOME on POSIX, USERPROFILE on Windows
            monkeypatch.setenv(name, str(tmp_path))
        assert context_window.codex_config_path() == tmp_path / ".codex" / "config.toml"


class TestCodexRollout:
    """The Codex rollout shape, told from its first line, never from its path."""

    @pytest.fixture(autouse=True)
    def _no_codex_config(self, tmp_path, monkeypatch):
        monkeypatch.setattr(context_window, "codex_config_path", lambda: tmp_path / "codex_config.toml")

    def test_usage_and_model_come_from_token_count_and_turn_context(self, tmp_path):
        rollout = tmp_path / "t.jsonl"
        _codex_rollout(rollout, total_tokens=22_113)
        usage = read_latest_usage(str(rollout))
        assert usage is not None
        assert usage == {
            "input_tokens": 21_545,
            "cached_input_tokens": 7680,
            "output_tokens": 568,
            "total_tokens": 22_113,
        }
        assert context_window.context_fill_tokens(usage) == 22_113

    def test_the_first_line_decides_the_shape(self, tmp_path):
        rollout, claude = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
        _codex_rollout(rollout, total_tokens=1)
        claude.write_text(
            json.dumps({"type": "assistant", "message": {"usage": {"input_tokens": 3}}}), encoding="utf-8"
        )
        assert context_window.transcript_provider(str(rollout)) == "codex"
        assert context_window.transcript_provider(str(claude)) == "claude"
        assert read_latest_usage(str(claude)) == {"input_tokens": 3}

    def test_the_window_is_the_rollouts_and_the_point_is_90_percent_of_the_full_one(self, tmp_path):
        rollout = tmp_path / "t.jsonl"
        _codex_rollout(rollout, total_tokens=1, window=258_400)
        window = context_window.resolve_compact_window(str(tmp_path), "s", str(rollout))
        assert window == 258_400
        assert context_window.compact_threshold(window, "codex") == 244_800
        assert context_window.compact_threshold(200_000) == 167_000

    def test_no_rollout_window_and_no_config_is_unknown(self, tmp_path):
        rollout = tmp_path / "t.jsonl"
        _codex_rollout(rollout, total_tokens=1, window=None)
        assert context_window.resolve_compact_window(str(tmp_path), "s", str(rollout)) is None

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("model_auto_compact_token_limit = 200_000  # trimmed\n", 200_000),
            ('model = "gpt"\n[profiles.x]\nmodel_auto_compact_token_limit = 9\n', 450_000),
            ('model_auto_compact_token_limit = "big"\n', 450_000),
            ("model_auto_compact_token_limit = 0\n", 450_000),
        ],
    )
    def test_the_config_limit_is_one_top_level_positive_int(self, tmp_path, text, expected):
        """Read without tomllib (3.11+): the same answer on every supported Python."""
        (tmp_path / "codex_config.toml").write_text(text, encoding="utf-8")
        assert context_window.compact_threshold(475_000, "codex") == expected

    def test_a_configured_limit_only_lowers_the_point(self, tmp_path):
        (tmp_path / "codex_config.toml").write_text("model_auto_compact_token_limit = 900000\n", encoding="utf-8")
        assert context_window.compact_threshold(475_000, "codex") == 450_000
        (tmp_path / "codex_config.toml").write_text("model_auto_compact_token_limit = 300000\n", encoding="utf-8")
        assert context_window.compact_threshold(475_000, "codex") == 300_000


def _seed_transcript(path):
    """Seed's own transcript.jsonl (src/head/chat/history.ts): one line per published line, who and text."""
    lines = [{"who": "you", "text": "hi", "time": "2026-11-04T10:00:00Z"}, {"who": "a", "text": "hello", "time": "t"}]
    path.write_text("".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8")
    return path


class TestSeedTranscript:
    def test_a_seed_transcript_reads_as_no_usage_without_a_parse(self, tmp_path, monkeypatch):
        parsed: list[str] = []
        monkeypatch.setattr(context_window, "_latest", lambda path, *_: parsed.append(path))
        transcript = str(_seed_transcript(tmp_path / "transcript.jsonl"))
        assert read_latest_usage(transcript, provider="seed") is None
        assert parsed == [], "Seed's lines are not Claude's: nothing may parse them as such"
