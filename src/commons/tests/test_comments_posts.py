# ===================AIPASS====================
# META DATA HEADER
# Name: test_comments_posts.py - Comment and Post Operations Tests
# Date: 2026-04-03
# Version: 1.0.0
# Category: commons/tests
#
# CHANGELOG (Max 5 entries):
#   - v1.0.0 (2026-04-03): Initial creation - unit tests for comment_ops and post_ops
#
# CODE STANDARDS:
#   - pytest style with fixtures for database setup
#   - Each test uses a fresh in-memory SQLite DB
#   - Mocks get_db, close_db, get_caller_branch at the source module level
# =============================================

"""
Unit Tests for Comment and Post Operations

Tests the handler functions in comment_ops.py and post_ops.py,
mocking external dependencies (database connections, caller identity)
and verifying return values and side effects.
"""

import sqlite3
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Eagerly import the target modules so they are in sys.modules before
# unittest.mock.patch tries to resolve the dotted attribute paths.
import commons.apps.handlers.comments.comment_ops as _comment_ops_mod  # noqa: F401
import commons.apps.handlers.posts.post_ops as _post_ops_mod  # noqa: F401


# ---------------------------------------------------------------------------
# Schema path
# ---------------------------------------------------------------------------
SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent
    / "apps"
    / "handlers"
    / "database"
    / "schema.sql"
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def db_conn():
    """
    Create a fresh in-memory SQLite database with the full commons schema
    and seed data needed for tests.  Yields the connection, then closes it.
    """
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
    # FTS5 virtual tables can cause issues in memory; strip them for unit tests
    lines = schema_sql.split("\n")
    filtered: list[str] = []
    skip = False
    for line in lines:
        upper = line.strip().upper()
        if upper.startswith("CREATE VIRTUAL TABLE"):
            skip = True
            continue
        if skip:
            if ";" in line:
                skip = False
            continue
        filtered.append(line)
    conn.executescript("\n".join(filtered))

    # Seed the SYSTEM agent (room creator) and default rooms
    conn.execute(
        "INSERT OR IGNORE INTO agents (branch_name, display_name, description) "
        "VALUES (?, ?, ?)",
        ("SYSTEM", "System", "The Commons system account"),
    )
    conn.execute(
        "INSERT OR IGNORE INTO rooms (name, display_name, description, created_by) "
        "VALUES (?, ?, ?, ?)",
        ("general", "General", "Main gathering space", "SYSTEM"),
    )
    conn.execute(
        "INSERT OR IGNORE INTO rooms (name, display_name, description, created_by) "
        "VALUES (?, ?, ?, ?)",
        ("dev", "Dev", "Development discussions", "SYSTEM"),
    )

    # Two test agents
    conn.execute(
        "INSERT OR IGNORE INTO agents (branch_name, display_name) VALUES (?, ?)",
        ("test-branch", "Test Branch"),
    )
    conn.execute(
        "INSERT OR IGNORE INTO agents (branch_name, display_name) VALUES (?, ?)",
        ("other-branch", "Other Branch"),
    )
    conn.commit()

    yield conn
    conn.close()


@pytest.fixture()
def _mock_caller_test_branch():
    """Patch get_caller_branch in BOTH handler modules to return test-branch."""
    caller = {"name": "test-branch", "path": "/mock/test-branch"}
    with (
        patch(
            "commons.apps.handlers.comments.comment_ops.get_caller_branch",
            return_value=caller,
        ),
        patch(
            "commons.apps.handlers.posts.post_ops.get_caller_branch",
            return_value=caller,
        ),
    ):
        yield


@pytest.fixture()
def _mock_caller_other_branch():
    """Patch get_caller_branch in BOTH handler modules to return other-branch."""
    caller = {"name": "other-branch", "path": "/mock/other-branch"}
    with (
        patch(
            "commons.apps.handlers.comments.comment_ops.get_caller_branch",
            return_value=caller,
        ),
        patch(
            "commons.apps.handlers.posts.post_ops.get_caller_branch",
            return_value=caller,
        ),
    ):
        yield


@pytest.fixture()
def mock_db(db_conn):
    """
    Patch get_db and close_db in both comment_ops and post_ops modules
    so they use the in-memory test connection.
    """
    with (
        patch(
            "commons.apps.handlers.comments.comment_ops.get_db",
            return_value=db_conn,
        ),
        patch(
            "commons.apps.handlers.comments.comment_ops.close_db",
        ),
        patch(
            "commons.apps.handlers.posts.post_ops.get_db",
            return_value=db_conn,
        ),
        patch(
            "commons.apps.handlers.posts.post_ops.close_db",
        ),
        # Suppress FTS sync and profile count increments (tested elsewhere)
        patch(
            "commons.apps.handlers.comments.comment_ops.sync_comment_to_fts",
        ),
        patch(
            "commons.apps.handlers.comments.comment_ops.increment_comment_count",
        ),
        patch(
            "commons.apps.handlers.posts.post_ops.sync_post_to_fts",
        ),
        patch(
            "commons.apps.handlers.posts.post_ops.increment_post_count",
        ),
    ):
        yield db_conn


def _insert_post(conn: sqlite3.Connection, *, author: str = "test-branch",
                 room: str = "general", title: str = "Seed Post",
                 content: str = "Seed content") -> int:
    """Helper: insert a post directly and return its id."""
    cursor = conn.execute(
        "INSERT INTO posts (room_name, author, title, content, post_type) "
        "VALUES (?, ?, ?, ?, ?)",
        (room, author, title, content, "discussion"),
    )
    conn.commit()
    assert cursor.lastrowid is not None
    return cursor.lastrowid


def _insert_comment(conn: sqlite3.Connection, post_id: int, *,
                    author: str = "other-branch",
                    content: str = "A comment",
                    parent_id: int | None = None) -> int:
    """Helper: insert a comment directly and return its id."""
    cursor = conn.execute(
        "INSERT INTO comments (post_id, parent_id, author, content) "
        "VALUES (?, ?, ?, ?)",
        (post_id, parent_id, author, content),
    )
    conn.commit()
    assert cursor.lastrowid is not None
    return cursor.lastrowid


# ===========================================================================
# COMMENT OPS TESTS
# ===========================================================================

class TestAddComment:
    """Tests for comment_ops.add_comment()."""

    @pytest.mark.usefixtures("_mock_caller_test_branch")
    def test_add_comment_success(self, mock_db):
        """add_comment with valid args returns success dict with comment_id."""
        from commons.apps.handlers.comments.comment_ops import add_comment

        post_id = _insert_post(mock_db)
        result = add_comment([str(post_id), "Hello world"])

        assert result["success"] is True
        assert isinstance(result["comment_id"], int)
        assert result["post_id"] == post_id
        assert result["author"] == "test-branch"
        assert result["parent_id"] is None
        assert result["post_title"] == "Seed Post"

    @pytest.mark.usefixtures("_mock_caller_test_branch")
    def test_add_comment_missing_args(self, mock_db):
        """add_comment with fewer than 2 positional args returns error."""
        from commons.apps.handlers.comments.comment_ops import add_comment

        result = add_comment(["1"])
        assert result["success"] is False
        assert "Usage" in result["error"]

    @pytest.mark.usefixtures("_mock_caller_test_branch")
    def test_add_comment_no_args(self, mock_db):
        """add_comment with empty args returns error."""
        from commons.apps.handlers.comments.comment_ops import add_comment

        result = add_comment([])
        assert result["success"] is False
        assert "Usage" in result["error"]

    @pytest.mark.usefixtures("_mock_caller_test_branch")
    def test_add_comment_nonexistent_post(self, mock_db):
        """add_comment on a nonexistent post returns error."""
        from commons.apps.handlers.comments.comment_ops import add_comment

        result = add_comment(["9999", "No such post"])
        assert result["success"] is False
        assert "not found" in result["error"]

    @pytest.mark.usefixtures("_mock_caller_test_branch")
    def test_add_comment_invalid_post_id(self, mock_db):
        """add_comment with non-integer post_id returns error."""
        from commons.apps.handlers.comments.comment_ops import add_comment

        result = add_comment(["abc", "content"])
        assert result["success"] is False
        assert "Invalid post_id" in result["error"]

    @pytest.mark.usefixtures("_mock_caller_test_branch")
    def test_add_comment_duplicate_detection(self, mock_db):
        """add_comment rejects identical content from same author within 5 min."""
        from commons.apps.handlers.comments.comment_ops import add_comment

        post_id = _insert_post(mock_db)
        first = add_comment([str(post_id), "Duplicate text"])
        assert first["success"] is True

        second = add_comment([str(post_id), "Duplicate text"])
        assert second["success"] is False
        assert "Duplicate" in second["error"]

    @pytest.mark.usefixtures("_mock_caller_test_branch")
    def test_add_comment_with_parent(self, mock_db):
        """add_comment with --parent flag creates a nested reply."""
        from commons.apps.handlers.comments.comment_ops import add_comment

        post_id = _insert_post(mock_db)
        parent_result = add_comment([str(post_id), "Parent comment"])
        assert parent_result["success"] is True
        parent_id = parent_result["comment_id"]

        child_result = add_comment([
            str(post_id), "Reply", "--parent", str(parent_id),
        ])
        assert child_result["success"] is True
        assert child_result["parent_id"] == parent_id

    @pytest.mark.usefixtures("_mock_caller_test_branch")
    def test_add_comment_invalid_parent(self, mock_db):
        """add_comment with --parent pointing to nonexistent comment returns error."""
        from commons.apps.handlers.comments.comment_ops import add_comment

        post_id = _insert_post(mock_db)
        result = add_comment([
            str(post_id), "Reply", "--parent", "9999",
        ])
        assert result["success"] is False
        assert "Parent comment" in result["error"]

    @pytest.mark.usefixtures("_mock_caller_test_branch")
    def test_add_comment_invalid_parent_value(self, mock_db):
        """add_comment with non-integer --parent value returns error."""
        from commons.apps.handlers.comments.comment_ops import add_comment

        result = add_comment(["1", "Reply", "--parent", "xyz"])
        assert result["success"] is False
        assert "Invalid --parent" in result["error"]

    @pytest.mark.usefixtures("_mock_caller_test_branch")
    def test_add_comment_updates_comment_count(self, mock_db):
        """add_comment increments the post comment_count."""
        from commons.apps.handlers.comments.comment_ops import add_comment

        post_id = _insert_post(mock_db)

        row_before = mock_db.execute(
            "SELECT comment_count FROM posts WHERE id = ?", (post_id,)
        ).fetchone()
        assert row_before["comment_count"] == 0

        add_comment([str(post_id), "Bump the count"])

        row_after = mock_db.execute(
            "SELECT comment_count FROM posts WHERE id = ?", (post_id,)
        ).fetchone()
        assert row_after["comment_count"] == 1


class TestVoteOnContent:
    """Tests for comment_ops.vote_on_content()."""

    @pytest.mark.usefixtures("_mock_caller_other_branch")
    def test_upvote_post(self, mock_db):
        """Upvoting a post returns success with new_score=1."""
        from commons.apps.handlers.comments.comment_ops import vote_on_content

        post_id = _insert_post(mock_db, author="test-branch")
        result = vote_on_content(["post", str(post_id), "up"])

        assert result["success"] is True
        assert result["action"] == "voted"
        assert result["direction"] == "up"
        assert result["target_type"] == "post"
        assert result["target_id"] == post_id
        assert result["new_score"] == 1

    @pytest.mark.usefixtures("_mock_caller_other_branch")
    def test_downvote_post(self, mock_db):
        """Downvoting a post returns success with new_score=-1."""
        from commons.apps.handlers.comments.comment_ops import vote_on_content

        post_id = _insert_post(mock_db, author="test-branch")
        result = vote_on_content(["post", str(post_id), "down"])

        assert result["success"] is True
        assert result["action"] == "voted"
        assert result["direction"] == "down"
        assert result["new_score"] == -1

    @pytest.mark.usefixtures("_mock_caller_other_branch")
    def test_upvote_comment(self, mock_db):
        """Upvoting a comment returns success with new_score=1."""
        from commons.apps.handlers.comments.comment_ops import vote_on_content

        post_id = _insert_post(mock_db, author="test-branch")
        comment_id = _insert_comment(mock_db, post_id, author="test-branch")
        result = vote_on_content(["comment", str(comment_id), "up"])

        assert result["success"] is True
        assert result["target_type"] == "comment"
        assert result["new_score"] == 1

    @pytest.mark.usefixtures("_mock_caller_test_branch")
    def test_self_vote_prevented(self, mock_db):
        """Voting on your own content returns error."""
        from commons.apps.handlers.comments.comment_ops import vote_on_content

        post_id = _insert_post(mock_db, author="test-branch")
        result = vote_on_content(["post", str(post_id), "up"])

        assert result["success"] is False
        assert "Cannot vote on your own content" in result["error"]

    @pytest.mark.usefixtures("_mock_caller_other_branch")
    def test_vote_toggle_off(self, mock_db):
        """Voting same direction twice toggles the vote off."""
        from commons.apps.handlers.comments.comment_ops import vote_on_content

        post_id = _insert_post(mock_db, author="test-branch")
        vote_on_content(["post", str(post_id), "up"])
        result = vote_on_content(["post", str(post_id), "up"])

        assert result["success"] is True
        assert result["action"] == "removed"
        assert result["new_score"] == 0

    @pytest.mark.usefixtures("_mock_caller_other_branch")
    def test_vote_change_direction(self, mock_db):
        """Changing vote direction adjusts score by 2."""
        from commons.apps.handlers.comments.comment_ops import vote_on_content

        post_id = _insert_post(mock_db, author="test-branch")
        vote_on_content(["post", str(post_id), "up"])
        result = vote_on_content(["post", str(post_id), "down"])

        assert result["success"] is True
        assert result["action"] == "changed"
        assert result["new_score"] == -1  # was +1, changed by -2

    @pytest.mark.usefixtures("_mock_caller_other_branch")
    def test_vote_nonexistent_target(self, mock_db):
        """Voting on a nonexistent target returns error."""
        from commons.apps.handlers.comments.comment_ops import vote_on_content

        result = vote_on_content(["post", "9999", "up"])
        assert result["success"] is False
        assert "not found" in result["error"]

    def test_vote_missing_args(self, mock_db):
        """vote_on_content with fewer than 3 args returns error."""
        from commons.apps.handlers.comments.comment_ops import vote_on_content

        result = vote_on_content(["post", "1"])
        assert result["success"] is False
        assert "Usage" in result["error"]

    def test_vote_invalid_target_type(self, mock_db):
        """vote_on_content with bad target_type returns error."""
        from commons.apps.handlers.comments.comment_ops import vote_on_content

        result = vote_on_content(["thread", "1", "up"])
        assert result["success"] is False
        assert "Invalid target type" in result["error"]

    def test_vote_invalid_direction(self, mock_db):
        """vote_on_content with bad direction returns error."""
        from commons.apps.handlers.comments.comment_ops import vote_on_content

        result = vote_on_content(["post", "1", "sideways"])
        assert result["success"] is False
        assert "Invalid direction" in result["error"]


# ===========================================================================
# POST OPS TESTS
# ===========================================================================

class TestCreatePost:
    """Tests for post_ops.create_post()."""

    @pytest.mark.usefixtures("_mock_caller_test_branch")
    def test_create_post_success(self, mock_db):
        """create_post with valid args returns success dict with post_id."""
        from commons.apps.handlers.posts.post_ops import create_post

        result = create_post(["general", "My Title", "Body text"])

        assert result["success"] is True
        assert isinstance(result["post_id"], int)
        assert result["title"] == "My Title"
        assert result["room"] == "general"
        assert result["author"] == "test-branch"
        assert result["post_type"] == "discussion"
        assert isinstance(result["mentions"], list)

    @pytest.mark.usefixtures("_mock_caller_test_branch")
    def test_create_post_missing_args(self, mock_db):
        """create_post with fewer than 3 positional args returns error."""
        from commons.apps.handlers.posts.post_ops import create_post

        result = create_post(["general", "Title only"])
        assert result["success"] is False
        assert "Usage" in result["error"]

    @pytest.mark.usefixtures("_mock_caller_test_branch")
    def test_create_post_no_args(self, mock_db):
        """create_post with empty args returns error."""
        from commons.apps.handlers.posts.post_ops import create_post

        result = create_post([])
        assert result["success"] is False
        assert "Usage" in result["error"]

    @pytest.mark.usefixtures("_mock_caller_test_branch")
    def test_create_post_nonexistent_room(self, mock_db):
        """create_post in a room that does not exist returns error."""
        from commons.apps.handlers.posts.post_ops import create_post

        result = create_post(["nonexistent-room", "Title", "Content"])
        assert result["success"] is False
        assert "not found" in result["error"]

    @pytest.mark.usefixtures("_mock_caller_test_branch")
    def test_create_post_with_type_flag(self, mock_db):
        """create_post with --type flag sets the post_type."""
        from commons.apps.handlers.posts.post_ops import create_post

        result = create_post([
            "general", "Question Title", "Question body",
            "--type", "question",
        ])

        assert result["success"] is True
        assert result["post_type"] == "question"

    @pytest.mark.usefixtures("_mock_caller_test_branch")
    def test_create_post_invalid_type(self, mock_db):
        """create_post with invalid --type value returns error."""
        from commons.apps.handlers.posts.post_ops import create_post

        result = create_post([
            "general", "Title", "Content", "--type", "rant",
        ])
        assert result["success"] is False
        assert "Invalid post type" in result["error"]

    @pytest.mark.usefixtures("_mock_caller_test_branch")
    def test_create_post_room_name_lowered(self, mock_db):
        """create_post lowercases the room name."""
        from commons.apps.handlers.posts.post_ops import create_post

        result = create_post(["GENERAL", "Title", "Content"])
        assert result["success"] is True
        assert result["room"] == "general"

    @pytest.mark.usefixtures("_mock_caller_test_branch")
    def test_create_post_stored_in_db(self, mock_db):
        """create_post actually inserts the row into the posts table."""
        from commons.apps.handlers.posts.post_ops import create_post

        result = create_post(["general", "DB Check", "Verify insert"])
        assert result["success"] is True

        row = mock_db.execute(
            "SELECT * FROM posts WHERE id = ?", (result["post_id"],)
        ).fetchone()
        assert row is not None
        assert row["title"] == "DB Check"
        assert row["content"] == "Verify insert"
        assert row["author"] == "test-branch"
        assert row["room_name"] == "general"


class TestViewThread:
    """Tests for post_ops.view_thread()."""

    @pytest.mark.usefixtures("_mock_caller_test_branch")
    def test_view_thread_success(self, mock_db):
        """view_thread returns post dict and list of comment dicts."""
        from commons.apps.handlers.posts.post_ops import view_thread

        post_id = _insert_post(mock_db)
        _insert_comment(mock_db, post_id, content="Comment A")
        _insert_comment(mock_db, post_id, content="Comment B")

        result = view_thread([str(post_id)])

        assert result["success"] is True
        assert result["post"]["id"] == post_id
        assert result["post"]["title"] == "Seed Post"
        assert len(result["comments"]) == 2
        assert result["comments"][0]["content"] == "Comment A"
        assert result["comments"][1]["content"] == "Comment B"

    @pytest.mark.usefixtures("_mock_caller_test_branch")
    def test_view_thread_no_comments(self, mock_db):
        """view_thread on a post with no comments returns empty list."""
        from commons.apps.handlers.posts.post_ops import view_thread

        post_id = _insert_post(mock_db)
        result = view_thread([str(post_id)])

        assert result["success"] is True
        assert result["comments"] == []

    def test_view_thread_nonexistent(self, mock_db):
        """view_thread on nonexistent post returns error."""
        from commons.apps.handlers.posts.post_ops import view_thread

        result = view_thread(["9999"])
        assert result["success"] is False
        assert "not found" in result["error"]

    def test_view_thread_no_args(self, mock_db):
        """view_thread with no args returns error."""
        from commons.apps.handlers.posts.post_ops import view_thread

        result = view_thread([])
        assert result["success"] is False
        assert "Usage" in result["error"]

    def test_view_thread_invalid_id(self, mock_db):
        """view_thread with non-integer id returns error."""
        from commons.apps.handlers.posts.post_ops import view_thread

        result = view_thread(["abc"])
        assert result["success"] is False
        assert "Invalid post_id" in result["error"]


class TestDeletePost:
    """Tests for post_ops.delete_post()."""

    @pytest.mark.usefixtures("_mock_caller_test_branch")
    def test_delete_own_post(self, mock_db):
        """delete_post on your own post succeeds and removes the row."""
        from commons.apps.handlers.posts.post_ops import delete_post

        post_id = _insert_post(mock_db, author="test-branch")
        result = delete_post([str(post_id)])

        assert result["success"] is True
        assert result["post_id"] == post_id
        assert result["author"] == "test-branch"
        assert result["title"] == "Seed Post"

        row = mock_db.execute(
            "SELECT id FROM posts WHERE id = ?", (post_id,)
        ).fetchone()
        assert row is None

    @pytest.mark.usefixtures("_mock_caller_other_branch")
    def test_delete_other_post_fails(self, mock_db):
        """delete_post on someone else's post returns permission error."""
        from commons.apps.handlers.posts.post_ops import delete_post

        post_id = _insert_post(mock_db, author="test-branch")
        result = delete_post([str(post_id)])

        assert result["success"] is False
        assert "Permission denied" in result["error"]
        assert "test-branch" in result["error"]

    @pytest.mark.usefixtures("_mock_caller_test_branch")
    def test_delete_nonexistent_post(self, mock_db):
        """delete_post on nonexistent post returns error."""
        from commons.apps.handlers.posts.post_ops import delete_post

        result = delete_post(["9999"])
        assert result["success"] is False
        assert "not found" in result["error"]

    def test_delete_no_args(self, mock_db):
        """delete_post with no args returns error."""
        from commons.apps.handlers.posts.post_ops import delete_post

        result = delete_post([])
        assert result["success"] is False
        assert "Usage" in result["error"]

    def test_delete_invalid_id(self, mock_db):
        """delete_post with non-integer id returns error."""
        from commons.apps.handlers.posts.post_ops import delete_post

        result = delete_post(["xyz"])
        assert result["success"] is False
        assert "Invalid post_id" in result["error"]

    @pytest.mark.usefixtures("_mock_caller_test_branch")
    def test_delete_cascades_comments_and_votes(self, mock_db):
        """delete_post cascade-deletes comments and votes on the post."""
        from commons.apps.handlers.posts.post_ops import delete_post

        post_id = _insert_post(mock_db, author="test-branch")
        comment_id = _insert_comment(mock_db, post_id, author="other-branch")

        # Add a vote on the post
        mock_db.execute(
            "INSERT INTO votes (agent_name, target_id, target_type, direction) "
            "VALUES (?, ?, ?, ?)",
            ("other-branch", post_id, "post", 1),
        )
        # Add a vote on the comment
        mock_db.execute(
            "INSERT INTO votes (agent_name, target_id, target_type, direction) "
            "VALUES (?, ?, ?, ?)",
            ("test-branch", comment_id, "comment", 1),
        )
        mock_db.commit()

        result = delete_post([str(post_id)])
        assert result["success"] is True

        # Verify cascade: comments gone
        comments = mock_db.execute(
            "SELECT id FROM comments WHERE post_id = ?", (post_id,)
        ).fetchall()
        assert len(comments) == 0

        # Verify cascade: votes on post gone
        post_votes = mock_db.execute(
            "SELECT id FROM votes WHERE target_type = 'post' AND target_id = ?",
            (post_id,),
        ).fetchall()
        assert len(post_votes) == 0

        # Verify cascade: votes on comment gone
        comment_votes = mock_db.execute(
            "SELECT id FROM votes WHERE target_type = 'comment' AND target_id = ?",
            (comment_id,),
        ).fetchall()
        assert len(comment_votes) == 0
