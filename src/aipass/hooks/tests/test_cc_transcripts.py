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


class TestManglingRule:
    """The rule, not the platform string.

    A CI run on Windows read `D--home-p-...` where this test had hardcoded
    `-home-p-...` — because Path.resolve() prepends a drive letter there, not
    because the mangling differs. The rule below is transcribed from the
    shipping CLI (2.1.228) and cross-checked against its own JavaScript:

        dpo(e) = e.replace(/[^a-zA-Z0-9]/g, "-")
        gv(e)  = dpo(e).length <= 200 ? dpo(e) : dpo(e).slice(0,200) + "-" + hash(e)
        hash(e): t = 0; per UTF-16 unit c: t = (t<<5) - t + c | 0 -> abs(t).toString(36)

    These vectors are the CLI's own answers, so they hold on every platform.
    """

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("/home/patrick/Projects/AIPass/src/aipass/hooks", "-home-patrick-Projects-AIPass-src-aipass-hooks"),
            # A Windows path: the colon and both backslashes are just
            # non-alphanumerics. There is NO drive-letter special case.
            ("C:\\Users\\p\\ai_mail", "C--Users-p-ai-mail"),
            ("", ""),
            ("/tmp/é–ø/x", "-tmp-----x"),
            # Non-BMP: JS sees a SURROGATE PAIR and writes TWO dashes.
            ("/a/\U0001d518nicode/b", "-a---nicode-b"),
        ],
    )
    def test_matches_the_cli(self, raw: str, expected: str):
        assert cc_transcripts._mangle(raw) == expected

    def test_underscore_becomes_dash(self):
        """ai_mail is the branch that proves it — a naive '/'->'-' misses it."""
        assert "_" not in cc_transcripts._mangle("/x/ai_mail")

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("/home/patrick/Projects/AIPass/src/aipass/hooks", "tmdi4s"),
            ("C:\\Users\\p\\ai_mail", "htazyh"),
            ("", "0"),
            ("/tmp/é–ø/x", "cac2i8"),
            ("/a/\U0001d518nicode/b", "u24wth"),
            ("/x/" + "deep/" * 60 + "branch", "z99g94"),
        ],
    )
    def test_hash_matches_the_cli(self, raw: str, expected: str):
        """Int32 wraparound and base36 — a near-miss sends us to a directory
        CC never created, and we would report 'no chats' instead of failing."""
        assert cc_transcripts._cc_path_hash(raw) == expected


class TestProjectDirFor:
    def test_mangles_the_resolved_path(self, monkeypatch, tmp_path):
        """Exercised against a real path so it holds on any platform."""
        monkeypatch.setattr(cc_transcripts, "PROJECTS_ROOT", tmp_path)
        target = tmp_path / "Projects" / "AIPass" / "ai_mail"
        target.mkdir(parents=True)
        got = cc_transcripts.project_dir_for(target)
        assert got.name == cc_transcripts._mangle(str(target.resolve()))
        assert got.parent == tmp_path

    def test_every_character_maps_one_to_one(self, monkeypatch, tmp_path):
        """No run-collapsing: '/a//b' and '/a/b' are different directories."""
        monkeypatch.setattr(cc_transcripts, "PROJECTS_ROOT", tmp_path)
        target = tmp_path / "a_b" / "c-d"
        target.mkdir(parents=True)
        resolved = str(target.resolve())
        name = cc_transcripts.project_dir_for(target).name
        assert len(name) == len(resolved.encode("utf-16-le")) // 2
        for got, src in zip(name, resolved):
            assert got == (src if ("0" <= src <= "9" or "A" <= src <= "Z" or "a" <= src <= "z") else "-")

    def test_long_path_is_truncated_and_hashed(self, monkeypatch, tmp_path):
        """Over 200 chars CC truncates and appends a hash — without this we
        would look in a directory that does not exist and report no chats."""
        monkeypatch.setattr(cc_transcripts, "PROJECTS_ROOT", tmp_path)
        raw = "/x/" + "deep/" * 60 + "branch"
        name = cc_transcripts.project_dir_for(raw).name
        assert len(name) > cc_transcripts._NAME_LIMIT
        assert name.endswith("-" + cc_transcripts._cc_path_hash(str(Path(raw).resolve())))
        assert name[: cc_transcripts._NAME_LIMIT] == cc_transcripts._mangle(str(Path(raw).resolve()))[:200]

    def test_short_path_is_not_hashed(self, monkeypatch, tmp_path):
        monkeypatch.setattr(cc_transcripts, "PROJECTS_ROOT", tmp_path)
        target = tmp_path / "short"
        target.mkdir()
        assert cc_transcripts.project_dir_for(target).name == cc_transcripts._mangle(str(target.resolve()))


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
