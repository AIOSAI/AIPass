# =================== AIPass ====================
# Name: test_commons_feed.py
# Description: Tests for the commons live feed handler
# Version: 1.0.0
# Created: 2026-07-21
# Modified: 2026-07-21
# =============================================

"""Tests for apps/handlers/monitoring/commons_feed.py (DPLAN-0257)

Covers:
- connect_readonly: mode=ro connection actually refuses writes
- initial_cursors / fetch_new_events: only-new-row cursor semantics
- fetch_backfill: last-N-events context on start, bounded by cursor
- display formatting: format_event, event_room, _join_body
- FeedState: record/visible room filtering
- _get_commons_db_path: env override
"""

import importlib
import sqlite3

import pytest

feed = importlib.import_module("aipass.prax.apps.handlers.monitoring.commons_feed")


SCHEMA = """
CREATE TABLE rooms (
    name TEXT PRIMARY KEY,
    mood TEXT DEFAULT 'neutral'
);
CREATE TABLE posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    room_name TEXT NOT NULL,
    author TEXT NOT NULL,
    title TEXT NOT NULL,
    content TEXT DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id INTEGER NOT NULL,
    parent_id INTEGER,
    author TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE votes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_name TEXT NOT NULL,
    target_id INTEGER NOT NULL,
    target_type TEXT NOT NULL,
    direction INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE reactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_name TEXT NOT NULL,
    post_id INTEGER,
    comment_id INTEGER,
    reaction TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


@pytest.fixture
def db_path(tmp_path):
    """A throwaway commons.db with the tables the feed queries."""
    path = tmp_path / "commons.db"
    conn = sqlite3.connect(str(path))
    conn.executescript(SCHEMA)
    conn.execute("INSERT INTO rooms (name, mood) VALUES ('general', 'welcoming')")
    conn.commit()
    conn.close()
    return path


def _seed_post(path, room="general", author="alice", title="Hello", content="world", ts="2026-07-21T10:00:00Z"):
    conn = sqlite3.connect(str(path))
    cur = conn.execute(
        "INSERT INTO posts (room_name, author, title, content, created_at) VALUES (?, ?, ?, ?, ?)",
        (room, author, title, content, ts),
    )
    conn.commit()
    post_id = cur.lastrowid
    conn.close()
    return post_id


# =============================================================================
# connect_readonly — write refusal
# =============================================================================


class TestConnectReadonly:
    """The feed's connection must never be able to write to commons.db."""

    def test_read_succeeds(self, db_path):
        """A mode=ro connection can still read existing rows."""
        _seed_post(db_path)
        conn = feed.connect_readonly(db_path)
        try:
            rows = conn.execute("SELECT * FROM posts").fetchall()
            assert len(rows) == 1
        finally:
            conn.close()

    def test_write_attempt_raises_operational_error(self, db_path):
        """INSERT on a mode=ro connection raises instead of succeeding."""
        conn = feed.connect_readonly(db_path)
        try:
            with pytest.raises(sqlite3.OperationalError):
                conn.execute(
                    "INSERT INTO posts (room_name, author, title, created_at) VALUES ('general', 'bob', 'x', 'y')"
                )
        finally:
            conn.close()

    def test_write_attempt_leaves_db_unchanged(self, db_path):
        """A refused DELETE leaves the underlying rows untouched."""
        conn = feed.connect_readonly(db_path)
        try:
            with pytest.raises(sqlite3.OperationalError):
                conn.execute("DELETE FROM posts")
        finally:
            conn.close()

        verify = sqlite3.connect(str(db_path))
        count = verify.execute("SELECT COUNT(*) FROM rooms").fetchone()[0]
        verify.close()
        assert count == 1


# =============================================================================
# Cursor logic — only new rows
# =============================================================================


class TestCursorLogic:
    """Cursors should only ever surface rows newer than the snapshot."""

    def test_initial_cursors_snapshot_current_max(self, db_path):
        """initial_cursors captures the current max id per table."""
        _seed_post(db_path)
        _seed_post(db_path, title="Second")
        conn = feed.connect_readonly(db_path)
        try:
            cursors = feed.initial_cursors(conn)
        finally:
            conn.close()
        assert cursors == {"posts": 2, "comments": 0, "votes": 0, "reactions": 0}

    def test_fetch_new_events_empty_when_nothing_past_cursor(self, db_path):
        """No rows inserted since the cursor snapshot means no events."""
        _seed_post(db_path)
        conn = feed.connect_readonly(db_path)
        try:
            cursors = feed.initial_cursors(conn)
            events, new_cursors = feed.fetch_new_events(conn, cursors)
        finally:
            conn.close()
        assert events == []
        assert new_cursors == cursors

    def test_fetch_new_events_returns_only_rows_after_cursor(self, db_path):
        """Rows inserted before the cursor snapshot are excluded."""
        _seed_post(db_path, title="Before cursor")
        conn = feed.connect_readonly(db_path)
        cursors = feed.initial_cursors(conn)

        _seed_post(db_path, title="After cursor", ts="2026-07-21T11:00:00Z")

        events, new_cursors = feed.fetch_new_events(conn, cursors)
        conn.close()

        assert len(events) == 1
        assert events[0]["title"] == "After cursor"
        assert new_cursors["posts"] == 2

    def test_fetch_new_events_advances_cursor_only_for_kinds_with_new_rows(self, db_path):
        """Cursors for tables with no new rows stay put; posts' cursor advances."""
        _seed_post(db_path)
        conn = feed.connect_readonly(db_path)
        cursors = feed.initial_cursors(conn)

        _seed_post(db_path, title="Another", ts="2026-07-21T11:00:00Z")

        _, new_cursors = feed.fetch_new_events(conn, cursors)
        conn.close()

        assert new_cursors["posts"] == 2
        assert new_cursors["comments"] == 0
        assert new_cursors["votes"] == 0
        assert new_cursors["reactions"] == 0


# =============================================================================
# Backfill — startup context
# =============================================================================


class TestFetchBackfill:
    """On start the feed shows recent history for context, bounded by cursor + limit."""

    def test_backfill_returns_events_up_to_limit(self, db_path):
        """Backfill returns only the most recent `limit` events, oldest first."""
        for i in range(15):
            _seed_post(db_path, title=f"Post {i}", ts=f"2026-07-21T10:{i:02d}:00Z")
        conn = feed.connect_readonly(db_path)
        cursors = feed.initial_cursors(conn)
        events = feed.fetch_backfill(conn, cursors, limit=10)
        conn.close()

        assert len(events) == 10
        assert [e["title"] for e in events] == [f"Post {i}" for i in range(5, 15)]

    def test_backfill_respects_cursor_bound(self, db_path):
        """Backfill never includes rows that came in after the cursor snapshot.

        Rows inserted after the cursor is taken belong to the live poll, not
        the startup backfill — including them here would double-emit.
        """
        _seed_post(db_path, title="Old")
        conn = feed.connect_readonly(db_path)
        cursors = feed.initial_cursors(conn)

        _seed_post(db_path, title="New", ts="2026-07-21T12:00:00Z")

        events = feed.fetch_backfill(conn, cursors, limit=10)
        conn.close()

        assert [e["title"] for e in events] == ["Old"]

    def test_backfill_empty_db_returns_empty(self, db_path):
        """An empty database backfills to an empty list, not an error."""
        conn = feed.connect_readonly(db_path)
        cursors = feed.initial_cursors(conn)
        events = feed.fetch_backfill(conn, cursors)
        conn.close()
        assert events == []


# =============================================================================
# Display formatting
# =============================================================================


class TestFormatEvent:
    def test_post_event(self):
        """A post event formats as author + quoted title + content snippet."""
        event = {"kind": "post", "author": "alice", "title": "Hello world", "content": "some content here"}
        line = feed.format_event(event)
        assert line == 'alice posted: "Hello world" — some content here'

    def test_comment_event(self):
        """A comment event formats as author replying to the post's author."""
        event = {"kind": "comment", "author": "bob", "content": "nice one", "post_author": "alice"}
        line = feed.format_event(event)
        assert line == "bob replied to alice: nice one"

    def test_comment_event_missing_post_author(self):
        """A missing post_author falls back to '?' rather than crashing."""
        event = {"kind": "comment", "author": "bob", "content": "nice one", "post_author": None}
        line = feed.format_event(event)
        assert line == "bob replied to ?: nice one"

    def test_vote_event_up(self):
        """A positive direction renders as 'voted up'."""
        event = {"kind": "vote", "agent_name": "bob", "direction": 1, "target_type": "post", "target_id": 5}
        assert feed.format_event(event) == "bob voted up on post #5"

    def test_vote_event_down(self):
        """A negative direction renders as 'voted down'."""
        event = {"kind": "vote", "agent_name": "bob", "direction": -1, "target_type": "comment", "target_id": 7}
        assert feed.format_event(event) == "bob voted down on comment #7"

    def test_reaction_event_on_post(self):
        """A reaction with post_id set targets 'a post'."""
        event = {"kind": "reaction", "agent_name": "carol", "post_id": 3, "comment_id": None, "reaction": "agree"}
        assert feed.format_event(event) == "carol reacted agree to a post"

    def test_reaction_event_on_comment(self):
        """A reaction with comment_id set targets 'a comment'."""
        event = {"kind": "reaction", "agent_name": "carol", "post_id": None, "comment_id": 9, "reaction": "thinking"}
        assert feed.format_event(event) == "carol reacted thinking to a comment"


class TestEventRoom:
    def test_returns_room_name_when_present(self):
        """A populated room_name passes through unchanged."""
        assert feed.event_room({"room_name": "dev"}) == "dev"

    def test_falls_back_to_commons_when_missing(self):
        """A None or absent room_name falls back to 'commons'."""
        assert feed.event_room({"room_name": None}) == "commons"
        assert feed.event_room({}) == "commons"


class TestJoinBody:
    def test_short_body_inlines_with_separator(self):
        """A body that fits stays on the header line, whitespace collapsed."""
        assert feed._join_body("h:", "a   b\n\nc", " ") == "h: a b c"

    def test_long_body_breaks_to_full_multiline_never_truncates(self):
        """A body over the inline limit renders IN FULL on its own lines — no ellipsis."""
        body = "first line " + "x" * 120 + "\nsecond line"
        result = feed._join_body("h:", body, " ")
        assert result.startswith("h:\n")
        assert "x" * 120 in result
        assert result.endswith("second line")
        assert "…" not in result

    def test_empty_body_returns_bare_header(self):
        """None or empty content returns the header alone, no dangling separator."""
        assert feed._join_body("h:", None, " ") == "h:"
        assert feed._join_body("h:", "", " ") == "h:"


# =============================================================================
# FeedState
# =============================================================================


class TestFeedState:
    def test_record_tracks_rooms_agents_and_count(self):
        """record() accumulates distinct rooms, distinct agents, and a running count."""
        state = feed.FeedState()
        state.record({"room_name": "dev", "author": "alice"})
        state.record({"room_name": "dev", "agent_name": "bob"})
        assert state.rooms_seen == {"dev"}
        assert state.agents_seen == {"alice", "bob"}
        assert state.events_count == 2

    def test_visible_true_when_no_filter(self):
        """With no active room filter, every event is visible."""
        state = feed.FeedState()
        assert state.visible({"room_name": "dev"}) is True

    def test_visible_respects_room_filter(self):
        """With an active room filter, only matching-room events are visible."""
        state = feed.FeedState()
        state.room_filter = {"dev"}
        assert state.visible({"room_name": "dev"}) is True
        assert state.visible({"room_name": "general"}) is False


# =============================================================================
# _get_commons_db_path — env override
# =============================================================================


class TestGetCommonsDbPath:
    def test_env_override(self, monkeypatch, tmp_path):
        """AIPASS_COMMONS_DB_PATH overrides the default sibling-branch path."""
        override = tmp_path / "custom.db"
        monkeypatch.setenv("AIPASS_COMMONS_DB_PATH", str(override))
        assert feed._get_commons_db_path() == override

    def test_default_is_sibling_commons_branch(self, monkeypatch):
        """Without an env override, the path resolves to the commons branch's db."""
        monkeypatch.delenv("AIPASS_COMMONS_DB_PATH", raising=False)
        path = feed._get_commons_db_path()
        assert path.parts[-2:] == ("commons", "commons.db")
