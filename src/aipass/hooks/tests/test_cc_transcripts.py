# =================== AIPass ====================
# Name: test_cc_transcripts.py
# Version: 1.0.0
# Description: Tests for the CC transcript reader
# Branch: hooks
# Layer: tests
# Created: 2026-08-18
# Modified: 2026-08-18
# =============================================

"""Tests for apps/modules/cc_transcripts.py.

The picker used to enumerate processes and call them chats. On 2026-08-18 that
cost a conversation: Ctrl+C removes the dead chat's session file, so the chat
Patrick wanted was the one thing a PID list could not show, while three bg
leftovers were offered as if they were his.
"""

import json
import os
import re
from pathlib import Path

import pytest

from aipass.hooks.apps.modules import cc_transcripts


def write_transcript(root: Path, cwd: Path, session_id: str, title: str, messages: int, age: float = 0) -> Path:
    directory = root / re.sub(r"[^A-Za-z0-9]", "-", str(cwd.resolve()))
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{session_id}.jsonl"
    lines = []
    if title:
        lines.append(json.dumps({"type": "ai-title", "aiTitle": title, "sessionId": session_id}))
    for i in range(messages):
        lines.append(json.dumps({"type": "user", "message": {"content": f"turn {i}"}}))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if age:
        stamp = path.stat().st_mtime - age
        os.utime(path, (stamp, stamp))
    return path


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    projects = tmp_path / "projects"
    projects.mkdir()
    monkeypatch.setattr(cc_transcripts, "PROJECTS_ROOT", projects)
    return projects


class TestProjectDirFor:
    """CC mangles the cwd into a directory name — verified against the live tree."""

    def test_replaces_every_non_alphanumeric_with_a_dash(self, monkeypatch, tmp_path):
        monkeypatch.setattr(cc_transcripts, "PROJECTS_ROOT", tmp_path)
        got = cc_transcripts.project_dir_for("/home/p/Projects/AIPass/src/aipass/ai_mail")
        assert got.name == "-home-p-Projects-AIPass-src-aipass-ai-mail"

    def test_underscore_becomes_dash_not_underscore(self, monkeypatch, tmp_path):
        """ai_mail is the branch that proves the rule — a naive '/'->'-' misses it."""
        monkeypatch.setattr(cc_transcripts, "PROJECTS_ROOT", tmp_path)
        assert "_" not in cc_transcripts.project_dir_for("/x/ai_mail").name


class TestRecentChats:
    def test_returns_newest_first(self, root, tmp_path):
        cwd = tmp_path / "branch"
        cwd.mkdir()
        write_transcript(root, cwd, "old", "Old chat", 3, age=9000)
        write_transcript(root, cwd, "new", "New chat", 4)
        chats = cc_transcripts.recent_chats(cwd)
        assert [c["session_id"] for c in chats] == ["new", "old"]

    def test_carries_title_and_message_count(self, root, tmp_path):
        cwd = tmp_path / "branch"
        cwd.mkdir()
        write_transcript(root, cwd, "s1", "Context weight investigation", 7)
        chat = cc_transcripts.recent_chats(cwd)[0]
        assert chat["title"] == "Context weight investigation"
        assert chat["messages"] == 7

    def test_tool_results_do_not_inflate_the_count(self, root, tmp_path):
        """User records also carry tool results; counting them raw reported 472
        where the user counts 109."""
        cwd = tmp_path / "branch"
        cwd.mkdir()
        directory = root / re.sub(r"[^A-Za-z0-9]", "-", str(cwd.resolve()))
        directory.mkdir(parents=True)
        lines = [
            json.dumps({"type": "user", "message": {"content": "a real turn"}}),
            json.dumps({"type": "user", "message": {"content": [{"type": "tool_result", "content": "x"}]}}),
            json.dumps({"type": "user", "message": {"content": [{"type": "tool_result", "content": "y"}]}}),
        ]
        (directory / "s1.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
        assert cc_transcripts.recent_chats(cwd)[0]["messages"] == 1

    def test_sidechain_records_are_not_counted(self, root, tmp_path):
        cwd = tmp_path / "branch"
        cwd.mkdir()
        directory = root / re.sub(r"[^A-Za-z0-9]", "-", str(cwd.resolve()))
        directory.mkdir(parents=True)
        lines = [
            json.dumps({"type": "user", "message": {"content": "mine"}}),
            json.dumps({"type": "user", "isSidechain": True, "message": {"content": "a subagent's"}}),
        ]
        (directory / "s1.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
        assert cc_transcripts.recent_chats(cwd)[0]["messages"] == 1

    def test_zero_message_transcript_is_not_a_chat(self, root, tmp_path):
        """A launch that never became a conversation must not be offered as one."""
        cwd = tmp_path / "branch"
        cwd.mkdir()
        write_transcript(root, cwd, "empty", "", 0)
        write_transcript(root, cwd, "real", "Real", 2)
        assert [c["session_id"] for c in cc_transcripts.recent_chats(cwd)] == ["real"]

    def test_limit_bounds_the_work(self, root, tmp_path):
        cwd = tmp_path / "branch"
        cwd.mkdir()
        for i in range(8):
            write_transcript(root, cwd, f"s{i}", f"Chat {i}", 2, age=i * 100)
        assert len(cc_transcripts.recent_chats(cwd, limit=3)) == 3

    def test_missing_directory_is_empty_not_an_error(self, root, tmp_path):
        assert cc_transcripts.recent_chats(tmp_path / "never-used") == []

    def test_unparseable_lines_are_skipped_not_fatal(self, root, tmp_path):
        cwd = tmp_path / "branch"
        cwd.mkdir()
        directory = root / re.sub(r"[^A-Za-z0-9]", "-", str(cwd.resolve()))
        directory.mkdir(parents=True)
        (directory / "s1.jsonl").write_text(
            "not json\n" + json.dumps({"type": "user", "message": {"content": "hi"}}) + "\n",
            encoding="utf-8",
        )
        assert cc_transcripts.recent_chats(cwd)[0]["messages"] == 1

    def test_untitled_chat_still_listed(self, root, tmp_path):
        cwd = tmp_path / "branch"
        cwd.mkdir()
        write_transcript(root, cwd, "s1", "", 3)
        chat = cc_transcripts.recent_chats(cwd)[0]
        assert chat["title"] == "" and chat["messages"] == 3


class TestChatFor:
    """A live seat may hold a chat older than the listed ones."""

    def test_finds_a_chat_outside_the_recent_window(self, root, tmp_path):
        cwd = tmp_path / "branch"
        cwd.mkdir()
        write_transcript(root, cwd, "ancient", "Ancient", 5, age=999999)
        for i in range(6):
            write_transcript(root, cwd, f"s{i}", f"Chat {i}", 2, age=i)
        assert cc_transcripts.chat_for(cwd, "ancient")["title"] == "Ancient"
        assert "ancient" not in {c["session_id"] for c in cc_transcripts.recent_chats(cwd, limit=5)}

    def test_missing_transcript_is_none(self, root, tmp_path):
        cwd = tmp_path / "branch"
        cwd.mkdir()
        assert cc_transcripts.chat_for(cwd, "nope") is None

    def test_empty_session_id_is_none(self, root, tmp_path):
        assert cc_transcripts.chat_for(tmp_path, "") is None
