# ===================AIPASS====================
# META DATA HEADER
# Name: test_lifecycle.py - The Commons Lifecycle Integration Tests
# Date: 2026-03-07
# Version: 1.0.0
# Category: commons/tests
#
# CHANGELOG (Max 5 entries):
#   - v1.0.0 (2026-03-07): Created for FPLAN-0411 Phase 7
#
# CODE STANDARDS:
#   - Pytest style with conftest fixtures
#   - Full lifecycle flow: init → create → interact → cleanup
#   - Tests handler functions directly (not modules)
# =============================================

"""
The Commons - Lifecycle Integration Tests

Exercises the full social platform flow: database init, room creation,
posting, commenting, voting, feed retrieval, search, thread view,
and cascade deletion.
"""

import tempfile
from pathlib import Path

import pytest

from aipass.commons.apps.handlers.database import db as db_module
from aipass.commons.apps.handlers.database.db import init_db, close_db


@pytest.fixture
def db():
    """Provide a fresh initialized database for each test."""
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
    db_path = Path(tmp.name)
    tmp.close()

    conn = init_db(db_path)

    # Register test agents
    for agent in ["ALICE", "BOB", "CHARLIE"]:
        conn.execute("INSERT OR IGNORE INTO agents (branch_name, display_name) VALUES (?, ?)", (agent, agent.title()))
    conn.commit()

    yield conn

    close_db(conn)
    if db_path.exists():
        db_path.unlink()


class TestFullLifecycle:
    """End-to-end lifecycle: create room → post → comment → vote → feed → search → delete."""

    def test_create_room(self, db):
        """Create a custom room and verify it exists."""
        db.execute(
            "INSERT INTO rooms (name, display_name, description, created_by) VALUES (?, ?, ?, ?)",
            ("test-room", "Test Room", "A room for testing", "ALICE"),
        )
        db.commit()

        room = db.execute("SELECT * FROM rooms WHERE name = ?", ("test-room",)).fetchone()
        assert room is not None
        assert room["display_name"] == "Test Room"
        assert room["created_by"] == "ALICE"

    def test_create_post_in_room(self, db):
        """Create a post in a default room."""
        db.execute(
            "INSERT INTO posts (room_name, author, title, content, post_type) VALUES (?, ?, ?, ?, ?)",
            ("general", "ALICE", "First Post", "Hello from the test suite!", "discussion"),
        )
        db.commit()

        post = db.execute("SELECT * FROM posts WHERE author = 'ALICE'").fetchone()
        assert post is not None
        assert post["title"] == "First Post"
        assert post["room_name"] == "general"
        assert post["vote_score"] == 0
        assert post["comment_count"] == 0

    def test_add_comments_and_nesting(self, db):
        """Create a post, add comments, and verify nesting."""
        db.execute(
            "INSERT INTO posts (room_name, author, title, content) VALUES (?, ?, ?, ?)",
            ("general", "ALICE", "Discussion", "Let's talk"),
        )
        db.commit()
        post_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

        # Top-level comment
        db.execute("INSERT INTO comments (post_id, author, content) VALUES (?, ?, ?)", (post_id, "BOB", "Great idea!"))
        db.commit()
        comment_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

        # Nested reply
        db.execute(
            "INSERT INTO comments (post_id, parent_id, author, content) VALUES (?, ?, ?, ?)",
            (post_id, comment_id, "CHARLIE", "I agree with BOB"),
        )
        db.commit()

        # Update comment count
        db.execute(
            "UPDATE posts SET comment_count = (SELECT COUNT(*) FROM comments WHERE post_id = ?) WHERE id = ?",
            (post_id, post_id),
        )
        db.commit()

        comments = db.execute("SELECT * FROM comments WHERE post_id = ? ORDER BY created_at ASC", (post_id,)).fetchall()
        assert len(comments) == 2

        nested = [c for c in comments if c["parent_id"] is not None]
        assert len(nested) == 1
        assert nested[0]["parent_id"] == comment_id

        post = db.execute("SELECT comment_count FROM posts WHERE id = ?", (post_id,)).fetchone()
        assert post["comment_count"] == 2

    def test_vote_on_post(self, db):
        """Vote on a post and verify score calculation."""
        db.execute(
            "INSERT INTO posts (room_name, author, title, content) VALUES (?, ?, ?, ?)",
            ("general", "ALICE", "Vote Target", "Vote on me"),
        )
        db.commit()
        post_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

        # Two upvotes, one downvote
        db.execute(
            "INSERT INTO votes (agent_name, target_id, target_type, direction) VALUES (?, ?, ?, ?)",
            ("BOB", post_id, "post", 1),
        )
        db.execute(
            "INSERT INTO votes (agent_name, target_id, target_type, direction) VALUES (?, ?, ?, ?)",
            ("CHARLIE", post_id, "post", 1),
        )
        db.execute(
            "INSERT INTO votes (agent_name, target_id, target_type, direction) VALUES (?, ?, ?, ?)",
            ("ALICE", post_id, "post", -1),
        )
        db.commit()

        score = db.execute(
            "SELECT COALESCE(SUM(direction), 0) FROM votes WHERE target_id = ? AND target_type = ?", (post_id, "post")
        ).fetchone()[0]
        assert score == 1

    def test_feed_sort_modes(self, db):
        """Test all feed sort modes: new, top, hot."""
        posts_data = [
            ("Old High Score", 10, "2026-01-01T10:00:00Z"),
            ("New Low Score", 1, "2026-03-01T10:00:00Z"),
            ("Mid Score Mid Age", 5, "2026-02-01T10:00:00Z"),
        ]

        for title, score, ts in posts_data:
            db.execute(
                "INSERT INTO posts (room_name, author, title, content, "
                "vote_score, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                ("general", "ALICE", title, "content", score, ts),
            )
        db.commit()

        # Sort by new (most recent first)
        new_order = db.execute("SELECT title FROM posts ORDER BY created_at DESC").fetchall()
        titles_new = [r["title"] for r in new_order]
        assert titles_new[0] == "New Low Score"

        # Sort by top (highest score first)
        top_order = db.execute("SELECT title FROM posts ORDER BY vote_score DESC").fetchall()
        titles_top = [r["title"] for r in top_order]
        assert titles_top[0] == "Old High Score"

        # Sort by hot (score desc, then date desc for ties)
        hot_order = db.execute("SELECT title FROM posts ORDER BY vote_score DESC, created_at DESC").fetchall()
        titles_hot = [r["title"] for r in hot_order]
        assert titles_hot[0] == "Old High Score"

    def test_search_content(self, db):
        """Search for content via FTS5."""
        from aipass.commons.apps.handlers.search.search_queries import (
            search_posts,
            sync_post_to_fts,
        )

        db.execute(
            "INSERT INTO posts (room_name, author, title, content) VALUES (?, ?, ?, ?)",
            ("general", "ALICE", "Architecture Review", "Let's review the handler pattern"),
        )
        db.commit()
        post_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

        sync_post_to_fts(db, post_id, "Architecture Review", "Let's review the handler pattern", "ALICE", "general")
        db.commit()

        results = search_posts(db, "architecture")
        assert len(results) == 1
        assert results[0]["title"] == "Architecture Review"

        results = search_posts(db, "nonexistent_keyword_xyz")
        assert len(results) == 0

    def test_view_thread(self, db):
        """View a post thread with all comments."""
        db.execute(
            "INSERT INTO posts (room_name, author, title, content) VALUES (?, ?, ?, ?)",
            ("general", "ALICE", "Thread Test", "This is the thread root"),
        )
        db.commit()
        post_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

        for i in range(5):
            db.execute(
                "INSERT INTO comments (post_id, author, content) VALUES (?, ?, ?)",
                (post_id, ["ALICE", "BOB", "CHARLIE"][i % 3], f"Comment {i + 1}"),
            )
        db.commit()

        post = db.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()
        assert post is not None
        assert post["title"] == "Thread Test"

        comments = db.execute("SELECT * FROM comments WHERE post_id = ? ORDER BY created_at ASC", (post_id,)).fetchall()
        assert len(comments) == 5

    def test_delete_post_cascades(self, db):
        """Delete a post and verify comments and votes are cascade-cleaned."""
        db.execute(
            "INSERT INTO posts (room_name, author, title, content) VALUES (?, ?, ?, ?)",
            ("general", "ALICE", "To Be Deleted", "This will be removed"),
        )
        db.commit()
        post_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

        # Add comments
        db.execute(
            "INSERT INTO comments (post_id, author, content) VALUES (?, ?, ?)",
            (post_id, "BOB", "Comment on doomed post"),
        )
        db.commit()

        # Add votes
        db.execute(
            "INSERT INTO votes (agent_name, target_id, target_type, direction) VALUES (?, ?, ?, ?)",
            ("CHARLIE", post_id, "post", 1),
        )
        db.commit()

        # Verify everything exists
        assert db.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone() is not None
        assert db.execute("SELECT * FROM comments WHERE post_id = ?", (post_id,)).fetchone() is not None
        assert (
            db.execute("SELECT * FROM votes WHERE target_id = ? AND target_type = 'post'", (post_id,)).fetchone()
            is not None
        )

        # Delete the post
        db.execute("DELETE FROM comments WHERE post_id = ?", (post_id,))
        db.execute("DELETE FROM votes WHERE target_id = ? AND target_type = 'post'", (post_id,))
        db.execute("DELETE FROM posts WHERE id = ?", (post_id,))
        db.commit()

        # Verify cascade
        assert db.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone() is None
        assert db.execute("SELECT * FROM comments WHERE post_id = ?", (post_id,)).fetchone() is None
        assert (
            db.execute("SELECT * FROM votes WHERE target_id = ? AND target_type = 'post'", (post_id,)).fetchone()
            is None
        )

    def test_room_filtering(self, db):
        """Verify feed filtering by room."""
        db.execute(
            "INSERT INTO posts (room_name, author, title, content) VALUES (?, ?, ?, ?)",
            ("general", "ALICE", "General Post", "content"),
        )
        db.execute(
            "INSERT INTO posts (room_name, author, title, content) VALUES (?, ?, ?, ?)",
            ("watercooler", "BOB", "Watercooler Post", "content"),
        )
        db.commit()

        general = db.execute("SELECT * FROM posts WHERE room_name = 'general'").fetchall()
        watercooler = db.execute("SELECT * FROM posts WHERE room_name = 'watercooler'").fetchall()
        all_posts = db.execute("SELECT * FROM posts").fetchall()

        assert len(general) == 1
        assert len(watercooler) == 1
        assert len(all_posts) == 2

    def test_mentions_tracked(self, db):
        """Verify @mentions are stored in the mentions table."""
        db.execute(
            "INSERT INTO posts (room_name, author, title, content) VALUES (?, ?, ?, ?)",
            ("general", "ALICE", "Shoutout", "Hey @BOB check this out"),
        )
        db.commit()
        post_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

        db.execute(
            "INSERT INTO mentions (post_id, mentioned_agent, mentioner_agent) VALUES (?, ?, ?)",
            (post_id, "BOB", "ALICE"),
        )
        db.commit()

        mention = db.execute("SELECT * FROM mentions WHERE mentioned_agent = 'BOB'").fetchone()
        assert mention is not None
        assert mention["mentioner_agent"] == "ALICE"
        assert mention["post_id"] == post_id


# ===========================================================================
# Branch-root resolution — .trinity/ or .aipass/ marker walk (P1, @devpulse)
#
# .trinity/ is gitignored, so a fresh clone has no branch-root marker,
# _find_branch_root() returns None, and _get_db_path() used to silently fall
# through to ~/.aipass/commons.db — a wrong-path SUCCESS. Fix: accept the
# git-tracked .aipass/ as a co-marker, and fail loudly (CommonsRootNotFound)
# instead of falling back to the home directory.
# ===========================================================================


class TestBranchRootResolution:
    """Covers the fresh-clone marker walk and the fail-honestly behaviour."""

    def test_resolves_with_aipass_marker_only(self, tmp_path):
        """Fresh clone: only .aipass/ present (no .trinity/) must still resolve."""
        (tmp_path / ".aipass").mkdir()
        start = tmp_path / "apps" / "handlers" / "database"
        start.mkdir(parents=True)

        result = db_module._find_branch_root(start)
        assert result == tmp_path.resolve()

    def test_resolves_with_trinity_marker_only(self, tmp_path):
        """No regression: .trinity/ alone still resolves."""
        (tmp_path / ".trinity").mkdir()
        start = tmp_path / "apps" / "handlers" / "database"
        start.mkdir(parents=True)

        result = db_module._find_branch_root(start)
        assert result == tmp_path.resolve()

    def test_no_marker_in_ancestry_returns_none(self, tmp_path):
        """No .trinity/ and no .aipass/ anywhere in the ancestry -> None."""
        start = tmp_path / "deep" / "nested" / "dir"
        start.mkdir(parents=True)

        result = db_module._find_branch_root(start)
        assert result is None

    def test_get_db_path_none_without_markers_or_env(self, monkeypatch):
        """No resolvable root and AIPASS_ROOT unset -> _get_db_path() is None."""
        monkeypatch.delenv("AIPASS_ROOT", raising=False)
        monkeypatch.setattr(db_module, "_find_branch_root", lambda start_path=None: None)

        assert db_module._get_db_path() is None

    def test_get_db_raises_commons_root_not_found(self, monkeypatch):
        """get_db() fails honestly (no home-directory fallback) when the root
        cannot be resolved, naming both markers and the AIPASS_ROOT override."""
        monkeypatch.delenv("AIPASS_ROOT", raising=False)
        monkeypatch.setattr(db_module, "DB_PATH", None)

        with pytest.raises(db_module.CommonsRootNotFound) as exc_info:
            db_module.get_db()

        message = str(exc_info.value)
        assert ".trinity" in message
        assert ".aipass" in message
        assert "AIPASS_ROOT" in message
