# =================== AIPass ====================
# Name: test_context_gauge.py
# Version: 1.7.0
# Description: Tests for context_gauge (per-window guard, real window, Codex, OpenCode store) and the grounding receipt
# Branch: hooks
# Created: 2026-07-20
# Modified: 2026-10-28
# =============================================

"""Tests for apps/handlers/prompt/context_gauge.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that handlers/prompt/context_gauge.py parses and imports
# seedgo: no-test-needed(stdlib) — tempfile.gettempdir() choosing the guard directory
# seedgo: no-test-needed(documentation) — the module docstring's account of the trigger

import json
import sqlite3
from contextlib import closing
from unittest.mock import patch

import pytest

from aipass.hooks.apps.handlers.bridges import opencode as opencode_bridge
from aipass.hooks.apps.handlers.lifecycle import compact
from aipass.hooks.apps.handlers.prompt import context_gauge
from aipass.hooks.apps.handlers.prompt.context_gauge import handle
from aipass.hooks.apps.modules import context_window, grounding_receipt

MODULE = "aipass.hooks.apps.handlers.prompt.context_gauge"
CADENCE_MODULE = "aipass.hooks.apps.modules.cadence"


@pytest.fixture(autouse=True)
def no_user_settings(tmp_path, monkeypatch):
    """The user-level settings file moves under tmp_path and stays absent, so no live window leaks in."""
    monkeypatch.setattr(context_window, "user_settings_path", lambda: tmp_path / "home" / "user_settings.json")
    monkeypatch.setattr(context_window, "codex_config_path", lambda: tmp_path / "home" / "codex_config.toml")
    monkeypatch.setattr(
        context_window, "opencode_config_path", lambda: tmp_path / "home" / "opencode" / "opencode.json"
    )
    monkeypatch.delenv("OPENCODE_CONFIG_CONTENT", raising=False)
    monkeypatch.setattr(context_window, "opencode_limit_cache_path", lambda: tmp_path / "home" / "limits.json")


def _write_transcript(path, input_tokens=0, cache_read=0, cache_creation=0, model=""):
    entry = {
        "type": "assistant",
        "message": {
            "model": model,
            "usage": {
                "input_tokens": input_tokens,
                "cache_read_input_tokens": cache_read,
                "cache_creation_input_tokens": cache_creation,
            },
        },
    }
    path.write_text(json.dumps(entry), encoding="utf-8")


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


class TestContextGaugeHandle:
    def test_no_transcript_path_is_a_noop(self):
        result = handle({"session_id": "s1"})
        assert result == {"stdout": "", "exit_code": 0}

    def test_below_nudge_threshold_is_silent(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_AUTO_COMPACT_WINDOW", "200000")
        transcript = tmp_path / "t.jsonl"
        _write_transcript(transcript, cache_read=50_000)

        with patch(f"{MODULE}._GUARD_DIR", tmp_path):
            result = handle({"session_id": "s-below", "transcript_path": str(transcript), "cwd": str(tmp_path)})
        assert result == {"stdout": "", "exit_code": 0}

    def test_fires_nudge_at_80_percent_of_trigger(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_AUTO_COMPACT_WINDOW", "200000")
        transcript = tmp_path / "t.jsonl"
        # trigger = 200000 - 33000 = 167000; 80% of that = 133600
        _write_transcript(transcript, cache_read=145_000)

        with patch(f"{MODULE}._GUARD_DIR", tmp_path):
            result = handle({"session_id": "s-nudge", "transcript_path": str(transcript), "cwd": str(tmp_path)})
        assert result["exit_code"] == 0
        assert "CONTEXT GAUGE" in result["stdout"]
        assert "/prep" in result["stdout"]
        assert "Compact fires soon" not in result["stdout"]
        assert result["sound"] == "context gauge"

    def test_fires_escalate_at_95_percent_of_trigger(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_AUTO_COMPACT_WINDOW", "200000")
        transcript = tmp_path / "t.jsonl"
        # 95% of 167000 trigger = 158650
        _write_transcript(transcript, cache_read=175_000)

        with patch(f"{MODULE}._GUARD_DIR", tmp_path):
            result = handle({"session_id": "s-escalate", "transcript_path": str(transcript), "cwd": str(tmp_path)})
        assert result["exit_code"] == 0
        assert "CONTEXT GAUGE" in result["stdout"]
        assert "Compact fires soon" in result["stdout"]
        assert result["sound"] == "context gauge"

    def test_fires_once_per_threshold_per_session(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_AUTO_COMPACT_WINDOW", "200000")
        transcript = tmp_path / "t.jsonl"
        _write_transcript(transcript, cache_read=145_000)
        hook_data = {"session_id": "s-once", "transcript_path": str(transcript), "cwd": str(tmp_path)}

        with patch(f"{MODULE}._GUARD_DIR", tmp_path):
            first = handle(hook_data)
            second = handle(hook_data)

        assert "CONTEXT GAUGE" in first["stdout"]
        assert second == {"stdout": "", "exit_code": 0}

    def test_different_sessions_fire_independently(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_AUTO_COMPACT_WINDOW", "200000")
        transcript = tmp_path / "t.jsonl"
        _write_transcript(transcript, cache_read=145_000)

        with patch(f"{MODULE}._GUARD_DIR", tmp_path):
            first = handle({"session_id": "s-indep-a", "transcript_path": str(transcript), "cwd": str(tmp_path)})
            second = handle({"session_id": "s-indep-b", "transcript_path": str(transcript), "cwd": str(tmp_path)})

        assert "CONTEXT GAUGE" in first["stdout"]
        assert "CONTEXT GAUGE" in second["stdout"]

    def test_missing_usage_is_a_noop(self, tmp_path):
        transcript = tmp_path / "t.jsonl"
        transcript.write_text(json.dumps({"type": "user", "message": {}}), encoding="utf-8")

        result = handle({"session_id": "s-nousage", "transcript_path": str(transcript), "cwd": str(tmp_path)})
        assert result == {"stdout": "", "exit_code": 0}

    def test_never_raises_on_unexpected_error(self, monkeypatch, tmp_path):
        def _boom(*_args, **_kwargs):
            raise RuntimeError("boom")

        monkeypatch.setattr(context_window, "read_latest_usage", _boom)
        result = context_gauge.handle({"session_id": "s-err", "transcript_path": str(tmp_path / "x.jsonl")})
        assert result == {"stdout": "", "exit_code": 0}


class TestGaugeMeasuresTheRealWindow:
    def test_a_1m_model_at_230k_is_silent(self, tmp_path, monkeypatch):
        monkeypatch.delenv("CLAUDE_CODE_AUTO_COMPACT_WINDOW", raising=False)
        transcript = tmp_path / "t.jsonl"
        _write_transcript(transcript, cache_read=230_000, model="claude-opus-5-5")

        with patch(f"{MODULE}._GUARD_DIR", tmp_path):
            result = handle({"session_id": "s-1m", "transcript_path": str(transcript), "cwd": str(tmp_path)})
        assert result == {"stdout": "", "exit_code": 0}

    def test_a_200k_model_at_230k_escalates(self, tmp_path, monkeypatch):
        monkeypatch.delenv("CLAUDE_CODE_AUTO_COMPACT_WINDOW", raising=False)
        transcript = tmp_path / "t.jsonl"
        _write_transcript(transcript, cache_read=230_000, model="claude-haiku-5-5")

        with patch(f"{MODULE}._GUARD_DIR", tmp_path):
            result = handle({"session_id": "s-200k", "transcript_path": str(transcript), "cwd": str(tmp_path)})
        assert "Compact fires soon" in result["stdout"]
        assert "~230k of 200k context (115%, as the status line counts it); auto-compact at ~167k." in result["stdout"]

    def test_the_printed_percent_is_fill_over_window(self, tmp_path, monkeypatch):
        monkeypatch.delenv("CLAUDE_CODE_AUTO_COMPACT_WINDOW", raising=False)
        transcript = tmp_path / "t.jsonl"
        _write_transcript(transcript, cache_read=150_000, model="claude-haiku-5-5")

        with patch(f"{MODULE}._GUARD_DIR", tmp_path):
            result = handle({"session_id": "s-pct", "transcript_path": str(transcript), "cwd": str(tmp_path)})
        assert result["stdout"].startswith(
            "CONTEXT GAUGE: ~150k of 200k context (75%, as the status line counts it); auto-compact at ~167k. "
        )
        assert "Compact fires soon" not in result["stdout"]

    def test_a_1m_model_nudges_at_80_percent_of_its_own_trigger(self, tmp_path, monkeypatch):
        monkeypatch.delenv("CLAUDE_CODE_AUTO_COMPACT_WINDOW", raising=False)
        transcript = tmp_path / "t.jsonl"
        # trigger = 1000000 - 33000 = 967000; 80% of that = 773600
        _write_transcript(transcript, cache_read=800_000, model="claude-opus-5-5")

        with patch(f"{MODULE}._GUARD_DIR", tmp_path):
            result = handle({"session_id": "s-1m-nudge", "transcript_path": str(transcript), "cwd": str(tmp_path)})
        assert "~800k of 1000k context (80%, as the status line counts it); auto-compact at ~967k." in result["stdout"]
        assert "Compact fires soon" not in result["stdout"]


class TestGaugeGuardIsPerWindow:
    """DPLAN-0347 row 5: the guard follows the context window, not the session.

    A session id outlives every compaction, so the old key let the gauge fire at
    most twice in a session's entire life — and it went silent exactly when the
    next window started filling again. cadence stamps a new window on every
    PreCompact reset; the guard reads that stamp.
    """

    @staticmethod
    def _data(tmp_path):
        transcript = tmp_path / "t.jsonl"
        _write_transcript(transcript, cache_read=145_000)
        return {"session_id": "s-window", "transcript_path": str(transcript), "cwd": str(tmp_path)}

    def test_the_next_window_gets_its_own_nudge(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_AUTO_COMPACT_WINDOW", "200000")
        hook_data = self._data(tmp_path)
        stamps = [None, None, 1_758_000_000.0]
        monkeypatch.setattr(f"{CADENCE_MODULE}.window_opened_at", lambda *_a, **_k: stamps.pop(0))

        with patch(f"{MODULE}._GUARD_DIR", tmp_path):
            first = handle(hook_data)
            repeat = handle(hook_data)
            after_compact = handle(hook_data)

        assert "CONTEXT GAUGE" in first["stdout"]
        assert repeat == {"stdout": "", "exit_code": 0}, "same window, already said"
        assert "CONTEXT GAUGE" in after_compact["stdout"], "a fresh window is a fresh climb"

    def test_an_unreadable_stamp_falls_back_to_one_key_and_warns(self, tmp_path, monkeypatch, caplog):
        monkeypatch.setenv("CLAUDE_CODE_AUTO_COMPACT_WINDOW", "200000")

        def _boom(*_args, **_kwargs):
            raise RuntimeError("no state dir")

        monkeypatch.setattr(f"{CADENCE_MODULE}.window_opened_at", _boom)

        with patch(f"{MODULE}._GUARD_DIR", tmp_path):
            result = handle(self._data(tmp_path))

        assert "CONTEXT GAUGE" in result["stdout"], "the nudge is never lost to its own guard"
        assert "window stamp unreadable" in caplog.text


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


class TestCodexRollout:
    """A Codex rollout: fill, window and compact point from the rollout and Codex's config; the call is $prep."""

    def test_a_codex_rollout_nudges_with_its_own_window_and_point(self, tmp_path):
        rollout = tmp_path / "rollout.jsonl"
        # window 475k is the usable 95% of 500k; Codex compacts at 90% of 500k = 450k; 80% of that = 360k
        _codex_rollout(rollout, total_tokens=380_000)
        hook_data = {
            "session_id": "s-codex",
            "transcript_path": str(rollout),
            "cwd": str(tmp_path),
            "provider": "codex",
        }
        with patch(f"{MODULE}._GUARD_DIR", tmp_path):
            result = handle(hook_data)
        assert result["stdout"].startswith(
            "CONTEXT GAUGE: ~380k of 475k context (80%, as the status line counts it); auto-compact at ~450k. "
        )
        assert "$prep" in result["stdout"]
        assert "/prep" not in result["stdout"]

    def test_codex_config_lowers_the_compact_point(self, tmp_path):
        (tmp_path / "home").mkdir()
        (tmp_path / "home" / "codex_config.toml").write_text(
            "model_auto_compact_token_limit = 400000\n", encoding="utf-8"
        )
        rollout = tmp_path / "rollout.jsonl"
        _codex_rollout(rollout, total_tokens=385_000)
        hook_data = {"session_id": "s-cfg", "transcript_path": str(rollout), "cwd": str(tmp_path), "provider": "codex"}
        with patch(f"{MODULE}._GUARD_DIR", tmp_path):
            result = handle(hook_data)
        assert "auto-compact at ~400k. Compact fires soon." in result["stdout"]
        assert "Run $prep now" in result["stdout"]

    def test_without_a_rollout_window_codex_config_sets_it(self, tmp_path):
        (tmp_path / "home").mkdir()
        (tmp_path / "home" / "codex_config.toml").write_text("model_context_window = 200000\n", encoding="utf-8")
        rollout = tmp_path / "rollout.jsonl"
        _codex_rollout(rollout, total_tokens=150_000, window=None)
        hook_data = {
            "session_id": "s-nowin",
            "transcript_path": str(rollout),
            "cwd": str(tmp_path),
            "provider": "codex",
        }
        with patch(f"{MODULE}._GUARD_DIR", tmp_path):
            result = handle(hook_data)
        assert "~150k of 190k context (79%, as the status line counts it); auto-compact at ~180k." in result["stdout"]


_CATALOG = {
    "opencode": {
        "models": {
            "deepseek-v4.1-flash-free": {"limit": {"context": 200_000, "output": 32_000}},
            "big-pickle": {"limit": {"context": 200_000, "input": 160_000, "output": 32_000}},
        }
    }
}


def _opencode_store(path, *messages: tuple[str, str, int, dict], model="deepseek-v4.1-flash-free", catalog=_CATALOG):
    """OpenCode's tables as it writes them: session_message rows (session, type, seq, tokens), each session's
    model in session_v2, and the models.dev catalog in kv (a JSON body inside a JSON value)."""
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("CREATE TABLE session_message (id text, session_id text, type text, seq integer, data text)")
        conn.execute("CREATE TABLE session_v2 (id text, model text)")
        conn.execute("CREATE TABLE kv (key text, value text, time_updated integer)")
        for n, (session, kind, seq, tokens) in enumerate(messages):
            data = json.dumps({"model": {"id": model}, "tokens": tokens})
            conn.execute("INSERT INTO session_message VALUES (?, ?, ?, ?, ?)", (f"m{n}", session, kind, seq, data))
        for session in {m[0] for m in messages}:
            conn.execute(
                "INSERT INTO session_v2 VALUES (?, ?)", (session, json.dumps({"id": model, "providerID": "opencode"}))
            )
        if catalog is not None:
            value = json.dumps({"updatedAt": 1, "body": json.dumps(catalog)})
            conn.execute("INSERT INTO kv VALUES ('models-dev:v2:catalog', ?, 1)", (value,))
        conn.commit()


def _tokens(inp=0, out=0, reasoning=0, read=0, write=0) -> dict:
    return {"input": inp, "output": out, "reasoning": reasoning, "cache": {"read": read, "write": write}}


class TestOpenCodeStore:
    """An OpenCode session: the newest assistant message in OpenCode's store, counted as its status line counts it,
    against the compact point OpenCode computes from its catalog and compaction.buffer."""

    def _gauge(self, tmp_path, monkeypatch, *messages, session="ses_1", **store):
        db = tmp_path / "opencode.db"
        _opencode_store(db, *messages, **store)
        monkeypatch.setenv("OPENCODE_DB", str(db))
        with patch(f"{MODULE}._GUARD_DIR", tmp_path):
            return handle({"session_id": session, "cwd": str(tmp_path), "provider": "opencode"})["stdout"]

    def test_output_reasoning_and_cache_count_toward_the_fill_and_the_call_is_slash_prep(self, tmp_path, monkeypatch):
        tokens = _tokens(inp=100_000, out=10_000, reasoning=6_000, read=40_000, write=4_000)
        stdout = self._gauge(tmp_path, monkeypatch, ("ses_1", "assistant", 2, tokens))
        assert stdout.startswith(
            "CONTEXT GAUGE: ~160k of 200k context (80%, as the status line counts it); auto-compact at ~170k."
        )
        assert "/prep" in stdout and "$prep" not in stdout

    def test_input_alone_under_the_threshold_is_silent(self, tmp_path, monkeypatch):
        assert self._gauge(tmp_path, monkeypatch, ("ses_1", "assistant", 2, _tokens(inp=130_000))) == ""

    def test_the_newest_assistant_message_of_this_session_is_the_reading(self, tmp_path, monkeypatch):
        stdout = self._gauge(
            tmp_path,
            monkeypatch,
            ("ses_1", "assistant", 1, _tokens(read=20_000)),
            ("ses_1", "assistant", 5, _tokens(read=140_000)),
            ("ses_1", "user", 6, {}),
            ("ses_2", "assistant", 9, _tokens(read=20_000)),
        )
        assert stdout.startswith("CONTEXT GAUGE: ~140k of 200k context (70%,")

    def test_ninety_five_percent_of_the_compact_point_escalates(self, tmp_path, monkeypatch):
        stdout = self._gauge(tmp_path, monkeypatch, ("ses_1", "assistant", 2, _tokens(read=165_000)))
        assert "Compact fires soon" in stdout

    def test_limit_input_beats_limit_context(self, tmp_path, monkeypatch):
        stdout = self._gauge(
            tmp_path, monkeypatch, ("ses_1", "assistant", 2, _tokens(read=110_000)), model="big-pickle"
        )
        assert stdout.startswith("CONTEXT GAUGE: ~110k of 160k context (69%,") and "auto-compact at ~136k." in stdout

    def test_a_model_the_catalog_lacks_reads_200k(self, tmp_path, monkeypatch):
        stdout = self._gauge(tmp_path, monkeypatch, ("ses_1", "assistant", 2, _tokens(read=140_000)), catalog={})
        assert stdout.startswith("CONTEXT GAUGE: ~140k of 200k context (70%,") and "auto-compact at ~170k." in stdout

    def test_config_content_beats_the_project_file(self, tmp_path, monkeypatch):
        (tmp_path / "opencode.json").write_text('{"compaction": {"buffer": 100000}}', encoding="utf-8")
        monkeypatch.setenv("OPENCODE_CONFIG_CONTENT", '{"compaction": {"buffer": 180000}}')
        stdout = self._gauge(tmp_path, monkeypatch, ("ses_1", "assistant", 2, _tokens(read=17_000)))
        assert "auto-compact at ~20k." in stdout

    def test_the_user_file_sets_the_buffer_when_nothing_nearer_does(self, tmp_path, monkeypatch):
        user = context_window.opencode_config_path()
        user.parent.mkdir(parents=True)
        user.write_text('{"compaction": {"buffer": 50000}}', encoding="utf-8")
        stdout = self._gauge(tmp_path, monkeypatch, ("ses_1", "assistant", 2, _tokens(read=140_000)))
        assert "auto-compact at ~150k." in stdout

    def test_the_project_file_beats_the_user_file(self, tmp_path, monkeypatch):
        (tmp_path / "opencode.json").write_text('{"compaction": {"buffer": 100000}}', encoding="utf-8")
        user = context_window.opencode_config_path()
        user.parent.mkdir(parents=True)
        user.write_text('{"compaction": {"buffer": 50000}}', encoding="utf-8")
        stdout = self._gauge(tmp_path, monkeypatch, ("ses_1", "assistant", 2, _tokens(read=90_000)))
        assert "auto-compact at ~100k." in stdout

    @pytest.mark.parametrize(
        ("limit", "buffer", "point"),
        [
            (200_000, None, 170_000),
            (160_000, None, 136_000),
            (100_000, None, 84_000),
            (20_000, None, 17_000),
            (200_000, 180_000, 20_000),
            (200_000, 200_000, 170_000),
        ],
    )
    def test_compact_point_is_the_buffer_else_fifteen_percent_with_a_16k_floor(self, limit, buffer, point):
        assert context_window.opencode_compact_point(limit, buffer) == point

    def _window(self, tmp_path, monkeypatch, model="big-pickle"):
        db = tmp_path / "opencode.db"
        _opencode_store(db, ("ses_1", "assistant", 2, _tokens(read=1_000)), model=model)
        monkeypatch.setenv("OPENCODE_DB", str(db))
        (tmp_path / "home").mkdir(exist_ok=True)
        return db

    @staticmethod
    def _catalog(db, limit, updated):
        catalog = {"opencode": {"models": {"big-pickle": {"limit": {"context": 200_000, "input": limit}}}}}
        value = json.dumps({"body": json.dumps(catalog)})
        with closing(sqlite3.connect(db)) as conn:
            conn.execute("UPDATE kv SET value = ?, time_updated = ?", (value, updated))
            conn.commit()

    def test_a_read_limit_is_cached_until_the_catalog_row_changes(self, tmp_path, monkeypatch):
        db = self._window(tmp_path, monkeypatch)
        assert context_window.opencode_window("ses_1", str(tmp_path)) == (160_000, 136_000)
        self._catalog(db, 100_000, 1)
        assert context_window.opencode_window("ses_1", str(tmp_path)) == (160_000, 136_000)
        self._catalog(db, 100_000, 2)
        assert context_window.opencode_window("ses_1", str(tmp_path)) == (100_000, 84_000)

    def test_a_cached_limit_older_than_a_day_is_read_again(self, tmp_path, monkeypatch):
        db = self._window(tmp_path, monkeypatch)
        context_window.opencode_window("ses_1", str(tmp_path))
        self._catalog(db, 100_000, 1)
        cache = context_window.opencode_limit_cache_path()
        aged = json.loads(cache.read_text(encoding="utf-8"))
        aged["opencode/big-pickle"]["at"] -= 24 * 60 * 60 + 5
        cache.write_text(json.dumps(aged), encoding="utf-8")
        assert context_window.opencode_window("ses_1", str(tmp_path)) == (100_000, 84_000)

    def test_an_unreadable_cache_reads_the_catalog(self, tmp_path, monkeypatch):
        self._window(tmp_path, monkeypatch)
        context_window.opencode_limit_cache_path().write_text("{torn", encoding="utf-8")
        assert context_window.opencode_window("ses_1", str(tmp_path)) == (160_000, 136_000)

    def test_no_store_or_no_session_row_is_silent(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OPENCODE_DB", str(tmp_path / "absent.db"))
        assert handle({"session_id": "ses_1", "provider": "opencode"})["stdout"] == ""
        assert self._gauge(tmp_path, monkeypatch, ("ses_9", "assistant", 2, _tokens(read=195_000))) == ""


def _instruction_store(path, session, asked, effect, compactions=0):
    """OpenCode's instruction tables: what was put (instruction_entry), the newest epoch's in-effect hashes
    (instruction_state) resolved through instruction_blob, and completed compaction rows. Values are JSON text."""
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("CREATE TABLE session_message (id text, session_id text, type text, seq integer, data text)")
        conn.execute("CREATE TABLE instruction_entry (session_id text, key text, value text, removed integer)")
        conn.execute("CREATE TABLE instruction_state (session_id text, current_values text)")
        conn.execute("CREATE TABLE instruction_blob (hash text, value text)")
        for key, value in asked.items():
            conn.execute("INSERT INTO instruction_entry VALUES (?, ?, ?, 0)", (session, key, json.dumps(value)))
        if "aipass-kernel" not in asked:
            conn.execute("INSERT INTO instruction_entry VALUES (?, 'aipass-kernel', 'null', 1)", (session,))
        hashes = {"core/date": "h-date"}
        for n, (key, value) in enumerate(effect.items()):
            hashes[f"api/{key}"] = f"h{n}"
            conn.execute("INSERT INTO instruction_blob VALUES (?, ?)", (f"h{n}", json.dumps(value)))
        conn.execute("INSERT INTO instruction_state VALUES (?, ?)", (session, json.dumps(hashes)))
        for n in range(compactions):
            conn.execute(
                "INSERT INTO session_message VALUES (?, ?, 'compaction', ?, ?)",
                (f"c{n}", session, n, json.dumps({"status": "completed"})),
            )
        conn.execute(
            "INSERT INTO session_message VALUES ('cr', ?, 'compaction', 99, ?)",
            (session, json.dumps({"status": "running"})),
        )
        conn.commit()


GROUNDED = {key: f"text of {key}" for key in grounding_receipt.REQUIRED}


class TestGroundingReceipt:
    """The receipt at <branch>/.ai_mail.local/grounding.json, written at the prompt, pending at a compaction."""

    @pytest.fixture
    def seat(self, tmp_path, monkeypatch):
        branch = tmp_path / "src" / "aipass" / "canary"
        branch.mkdir(parents=True)
        monkeypatch.setenv("OPENCODE_DB", str(tmp_path / "opencode.db"))
        return branch

    def _prompt(self, seat, provider="opencode", session="ses_1"):
        with patch(f"{MODULE}._GUARD_DIR", seat):
            stdout = handle({"session_id": session, "cwd": str(seat), "provider": provider})["stdout"]
        doc = json.loads((seat / ".ai_mail.local" / "grounding.json").read_text(encoding="utf-8"))
        return stdout, doc

    def test_the_required_set_is_the_bridges_grounding_entries(self):
        assert set(grounding_receipt.REQUIRED) == set(opencode_bridge.GROUNDING.values())

    def test_the_store_carrying_every_entry_reads_verified_at_its_compaction_count(self, seat, tmp_path):
        _instruction_store(tmp_path / "opencode.db", "ses_1", GROUNDED, GROUNDED, compactions=2)
        stdout, doc = self._prompt(seat)
        row = doc["current"]
        assert stdout == ""
        assert (row["status"], row["generation"], row["observation_boundary"]) == ("verified", 2, "opencode_store")
        assert row["expected_digest"] == row["observed_digest"] and len(row["observed_digest"]) == 64
        assert (row["session_id"], row["branch"], row["missing"], row["stale"]) == ("ses_1", "canary", [], [])
        assert row["required_set_revision"] == grounding_receipt.REVISION

    def test_a_lost_or_older_entry_reads_ungrounded_and_the_prompt_names_it_and_its_source(self, seat, tmp_path):
        effect = {key: value for key, value in GROUNDED.items() if key != "aipass-navmap"}
        effect["aipass-kernel"] = "the kernel before the edit"
        _instruction_store(tmp_path / "opencode.db", "ses_1", GROUNDED, effect)
        stdout, doc = self._prompt(seat)
        row = doc["current"]
        assert (row["status"], row["missing"], row["stale"]) == ("ungrounded", ["aipass-navmap"], ["aipass-kernel"])
        assert row["expected_digest"] != row["observed_digest"]
        assert stdout == (
            "GROUNDING RECEIPT: your last model call did not carry aipass-kernel, aipass-navmap. "
            "Re-read: $AIPASS_HOME/.aipass/tier0_kernel.md; $AIPASS_HOME/.aipass/tier1_navmap.md."
        )

    def test_a_session_with_nothing_put_yet_is_pending_and_silent(self, seat, tmp_path):
        _instruction_store(tmp_path / "opencode.db", "ses_1", {}, {})
        stdout, doc = self._prompt(seat)
        assert (stdout, doc["current"]["status"], doc["current"]["missing"]) == ("", "pending", [])

    def test_claude_and_codex_write_unverified_with_nothing_observed(self, seat):
        for provider in ("claude", "codex"):
            stdout, doc = self._prompt(seat, provider=provider)
            row = doc["current"]
            assert stdout == ""
            assert (row["status"], row["observation_boundary"], row["generation"]) == ("unverified", "none", 0)
            assert (row["expected_digest"], row["observed_digest"]) == (None, None)

    def test_a_compaction_sets_pending_one_generation_on_and_the_next_prompt_reads_the_store(self, seat, tmp_path):
        _instruction_store(tmp_path / "opencode.db", "ses_1", GROUNDED, GROUNDED, compactions=1)
        self._prompt(seat)
        compact.handle({"session_id": "ses_1", "cwd": str(seat)})
        doc = json.loads((seat / ".ai_mail.local" / "grounding.json").read_text(encoding="utf-8"))
        assert (doc["current"]["status"], doc["current"]["generation"]) == ("pending", 2)
        assert doc["current"]["observed_digest"] is None
        assert doc["current"]["observation_boundary"] == "opencode_store"
        _, doc = self._prompt(seat)
        assert (doc["current"]["status"], doc["current"]["generation"]) == ("verified", 1)
        assert [old["status"] for old in doc["history"]] == ["pending", "verified"]

    def test_claude_generation_counts_its_compactions(self, seat):
        self._prompt(seat, provider="claude")
        compact.handle({"session_id": "ses_1", "cwd": str(seat)})
        _, doc = self._prompt(seat, provider="claude")
        assert (doc["current"]["status"], doc["current"]["generation"]) == ("unverified", 1)

    def test_history_keeps_changed_rows_only_and_at_most_twenty(self, seat):
        self._prompt(seat, provider="claude")
        _, doc = self._prompt(seat, provider="claude")
        assert doc["history"] == []
        for _ in range(25):
            compact.handle({"session_id": "ses_1", "cwd": str(seat)})
        _, doc = self._prompt(seat, provider="claude")
        assert len(doc["history"]) == grounding_receipt.HISTORY_CAP
        assert doc["history"][0]["generation"] == 25
