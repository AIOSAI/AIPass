# ===================AIPASS====================
# META DATA HEADER
# Name: test_curation.py - Curation Subsystem Tests
# Date: 2026-03-28
# Version: 1.0.0
# Category: commons/tests
#
# CHANGELOG (Max 5 entries):
#   - v1.0.0 (2026-03-28): Initial creation — reactions, pins, trending tests
#
# CODE STANDARDS:
#   - Pytest function style (no unittest classes)
#   - Uses initialized_db fixture from conftest.py for DB isolation
#   - Mocks prax logger and json_handler to avoid side-effect dependencies
# =============================================

"""
Unit tests for the curation subsystem.

Covers:
- reaction_queries: add, remove, get counts, get detailed, summary string
- pin_queries: pin, unpin, get pinned, is_pinned checks
- trending_queries: empty results and engagement-based ranking
"""

import sqlite3
from unittest.mock import patch

import pytest

from commons.apps.handlers.curation.reaction_queries import (
    add_reaction,
    remove_reaction,
    get_reactions,
    get_reactions_detailed,
    get_reaction_summary,
    REACTION_EMOJI,
    VALID_REACTIONS,
)
from commons.apps.handlers.curation.pin_queries import (
    pin_post,
    unpin_post,
    get_pinned_posts,
    is_pinned,
)
from commons.apps.handlers.curation.trending_queries import get_trending_posts


# =============================================================================
# HELPERS
# =============================================================================


def _seed_agent_and_post(conn: sqlite3.Connection) -> int:
    """Insert a test agent and post, return the post ID."""
    conn.execute(
        "INSERT OR IGNORE INTO agents (branch_name, display_name) VALUES (?, ?)",
        ("TEST_BRANCH", "Test"),
    )
    conn.execute(
        "INSERT INTO posts (title, content, room_name, author) "
        "VALUES (?, ?, ?, ?)",
        ("Test Post", "Content", "general", "TEST_BRANCH"),
    )
    conn.commit()
    row = conn.execute("SELECT last_insert_rowid()").fetchone()
    post_id: int = row[0]
    return post_id


def _seed_comment(conn: sqlite3.Connection, post_id: int) -> int:
    """Insert a test comment on a post, return the comment ID."""
    conn.execute(
        "INSERT INTO comments (post_id, author, content) VALUES (?, ?, ?)",
        (post_id, "TEST_BRANCH", "A test comment"),
    )
    conn.commit()
    row = conn.execute("SELECT last_insert_rowid()").fetchone()
    comment_id: int = row[0]
    return comment_id


# =============================================================================
# REACTION QUERIES — add_reaction
# =============================================================================


@patch("commons.apps.handlers.curation.reaction_queries.json_handler")
def test_add_reaction_new_returns_true(
    mock_json: object, initialized_db: object
) -> None:
    """Adding a new reaction to a post should return True."""
    conn: sqlite3.Connection = initialized_db  # type: ignore[assignment]
    post_id = _seed_agent_and_post(conn)

    result = add_reaction(conn, "TEST_BRANCH", "thumbsup", post_id=post_id)
    assert result is True


@patch("commons.apps.handlers.curation.reaction_queries.json_handler")
def test_add_reaction_duplicate_returns_false(
    mock_json: object, initialized_db: object
) -> None:
    """Adding the same reaction a second time should return False."""
    conn: sqlite3.Connection = initialized_db  # type: ignore[assignment]
    post_id = _seed_agent_and_post(conn)

    add_reaction(conn, "TEST_BRANCH", "thumbsup", post_id=post_id)
    result = add_reaction(conn, "TEST_BRANCH", "thumbsup", post_id=post_id)
    assert result is False


@patch("commons.apps.handlers.curation.reaction_queries.json_handler")
def test_add_reaction_invalid_type_returns_false(
    mock_json: object, initialized_db: object
) -> None:
    """An invalid reaction name should be rejected immediately."""
    conn: sqlite3.Connection = initialized_db  # type: ignore[assignment]
    post_id = _seed_agent_and_post(conn)

    result = add_reaction(conn, "TEST_BRANCH", "invalid_emoji", post_id=post_id)
    assert result is False


@patch("commons.apps.handlers.curation.reaction_queries.json_handler")
def test_add_reaction_comment_target(
    mock_json: object, initialized_db: object
) -> None:
    """Reactions can target a comment instead of a post."""
    conn: sqlite3.Connection = initialized_db  # type: ignore[assignment]
    post_id = _seed_agent_and_post(conn)
    comment_id = _seed_comment(conn, post_id)

    result = add_reaction(conn, "TEST_BRANCH", "agree", comment_id=comment_id)
    assert result is True

    # Verify the reaction is stored against the comment, not the post
    counts = get_reactions(conn, comment_id=comment_id)
    assert counts.get("agree") == 1


@patch("commons.apps.handlers.curation.reaction_queries.json_handler")
def test_add_reaction_both_targets_returns_false(
    mock_json: object, initialized_db: object
) -> None:
    """Providing both post_id and comment_id should be rejected."""
    conn: sqlite3.Connection = initialized_db  # type: ignore[assignment]
    post_id = _seed_agent_and_post(conn)

    result = add_reaction(conn, "TEST_BRANCH", "agree", post_id=post_id, comment_id=99)
    assert result is False


# =============================================================================
# REACTION QUERIES — remove_reaction
# =============================================================================


@patch("commons.apps.handlers.curation.reaction_queries.json_handler")
def test_remove_reaction_existing_returns_true(
    mock_json: object, initialized_db: object
) -> None:
    """Removing an existing reaction should return True."""
    conn: sqlite3.Connection = initialized_db  # type: ignore[assignment]
    post_id = _seed_agent_and_post(conn)

    add_reaction(conn, "TEST_BRANCH", "celebrate", post_id=post_id)
    result = remove_reaction(conn, "TEST_BRANCH", "celebrate", post_id=post_id)
    assert result is True


def test_remove_reaction_nonexistent_returns_false(initialized_db: object) -> None:
    """Removing a reaction that was never added should return False."""
    conn: sqlite3.Connection = initialized_db  # type: ignore[assignment]
    post_id = _seed_agent_and_post(conn)

    result = remove_reaction(conn, "TEST_BRANCH", "thinking", post_id=post_id)
    assert result is False


# =============================================================================
# REACTION QUERIES — get_reactions / get_reactions_detailed / summary
# =============================================================================


@patch("commons.apps.handlers.curation.reaction_queries.json_handler")
def test_get_reactions_returns_correct_counts(
    mock_json: object, initialized_db: object
) -> None:
    """get_reactions should return accurate per-type counts."""
    conn: sqlite3.Connection = initialized_db  # type: ignore[assignment]
    post_id = _seed_agent_and_post(conn)

    # Second agent
    conn.execute(
        "INSERT OR IGNORE INTO agents (branch_name, display_name) VALUES (?, ?)",
        ("AGENT_B", "Agent B"),
    )
    conn.commit()

    add_reaction(conn, "TEST_BRANCH", "thumbsup", post_id=post_id)
    add_reaction(conn, "AGENT_B", "thumbsup", post_id=post_id)
    add_reaction(conn, "TEST_BRANCH", "thinking", post_id=post_id)

    counts = get_reactions(conn, post_id=post_id)
    assert counts["thumbsup"] == 2
    assert counts["thinking"] == 1
    assert "agree" not in counts


@patch("commons.apps.handlers.curation.reaction_queries.json_handler")
def test_get_reactions_detailed_returns_agent_names(
    mock_json: object, initialized_db: object
) -> None:
    """get_reactions_detailed should map reaction types to agent name lists."""
    conn: sqlite3.Connection = initialized_db  # type: ignore[assignment]
    post_id = _seed_agent_and_post(conn)

    conn.execute(
        "INSERT OR IGNORE INTO agents (branch_name, display_name) VALUES (?, ?)",
        ("AGENT_B", "Agent B"),
    )
    conn.commit()

    add_reaction(conn, "TEST_BRANCH", "agree", post_id=post_id)
    add_reaction(conn, "AGENT_B", "agree", post_id=post_id)

    detailed = get_reactions_detailed(conn, post_id=post_id)
    assert "agree" in detailed
    assert set(detailed["agree"]) == {"TEST_BRANCH", "AGENT_B"}


@patch("commons.apps.handlers.curation.reaction_queries.json_handler")
def test_get_reaction_summary_formatted_string(
    mock_json: object, initialized_db: object
) -> None:
    """get_reaction_summary should return an emoji-count formatted string."""
    conn: sqlite3.Connection = initialized_db  # type: ignore[assignment]
    post_id = _seed_agent_and_post(conn)

    add_reaction(conn, "TEST_BRANCH", "thumbsup", post_id=post_id)
    add_reaction(conn, "TEST_BRANCH", "celebrate", post_id=post_id)

    summary = get_reaction_summary(conn, post_id=post_id)
    assert REACTION_EMOJI["thumbsup"] + "1" in summary
    assert REACTION_EMOJI["celebrate"] + "1" in summary


def test_get_reaction_summary_empty_returns_empty_string(
    initialized_db: object,
) -> None:
    """get_reaction_summary with no reactions should return an empty string."""
    conn: sqlite3.Connection = initialized_db  # type: ignore[assignment]
    post_id = _seed_agent_and_post(conn)

    summary = get_reaction_summary(conn, post_id=post_id)
    assert summary == ""


# =============================================================================
# PIN QUERIES
# =============================================================================


@patch("commons.apps.handlers.curation.pin_queries.json_handler")
def test_pin_post_success(mock_json: object, initialized_db: object) -> None:
    """Pinning an existing post should return True and set pinned=1."""
    conn: sqlite3.Connection = initialized_db  # type: ignore[assignment]
    post_id = _seed_agent_and_post(conn)

    result = pin_post(conn, post_id)
    assert result is True
    assert is_pinned(conn, post_id) is True


@patch("commons.apps.handlers.curation.pin_queries.json_handler")
def test_unpin_post_success(mock_json: object, initialized_db: object) -> None:
    """Unpinning a pinned post should return True and set pinned=0."""
    conn: sqlite3.Connection = initialized_db  # type: ignore[assignment]
    post_id = _seed_agent_and_post(conn)

    pin_post(conn, post_id)
    result = unpin_post(conn, post_id)
    assert result is True
    assert is_pinned(conn, post_id) is False


@patch("commons.apps.handlers.curation.pin_queries.json_handler")
def test_get_pinned_posts_returns_only_pinned(
    mock_json: object, initialized_db: object
) -> None:
    """get_pinned_posts should return only posts with pinned=1."""
    conn: sqlite3.Connection = initialized_db  # type: ignore[assignment]
    post_id = _seed_agent_and_post(conn)

    # Before pinning, list should be empty
    pinned = get_pinned_posts(conn)
    assert len(pinned) == 0

    pin_post(conn, post_id)
    pinned = get_pinned_posts(conn)
    assert len(pinned) == 1
    assert pinned[0]["id"] == post_id
    assert pinned[0]["title"] == "Test Post"


@patch("commons.apps.handlers.curation.pin_queries.json_handler")
def test_get_pinned_posts_filters_by_room(
    mock_json: object, initialized_db: object
) -> None:
    """get_pinned_posts with room_name should filter to that room only."""
    conn: sqlite3.Connection = initialized_db  # type: ignore[assignment]
    _seed_agent_and_post(conn)  # post in "general"

    # Create a second post in "dev"
    conn.execute(
        "INSERT INTO posts (title, content, room_name, author) "
        "VALUES (?, ?, ?, ?)",
        ("Dev Post", "Dev content", "dev", "TEST_BRANCH"),
    )
    conn.commit()
    dev_post_id: int = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    # Pin both
    pin_post(conn, 1)
    pin_post(conn, dev_post_id)

    general_pinned = get_pinned_posts(conn, room_name="general")
    assert len(general_pinned) == 1
    assert general_pinned[0]["room_name"] == "general"

    dev_pinned = get_pinned_posts(conn, room_name="dev")
    assert len(dev_pinned) == 1
    assert dev_pinned[0]["room_name"] == "dev"


def test_is_pinned_false_for_unpinned_post(initialized_db: object) -> None:
    """is_pinned should return False for a post that has not been pinned."""
    conn: sqlite3.Connection = initialized_db  # type: ignore[assignment]
    post_id = _seed_agent_and_post(conn)

    assert is_pinned(conn, post_id) is False


def test_is_pinned_false_for_nonexistent_post(initialized_db: object) -> None:
    """is_pinned should return False for a post ID that does not exist."""
    conn: sqlite3.Connection = initialized_db  # type: ignore[assignment]
    assert is_pinned(conn, 99999) is False


# =============================================================================
# TRENDING QUERIES
# =============================================================================


@patch("commons.apps.handlers.curation.trending_queries.json_handler")
def test_get_trending_posts_empty(mock_json: object, initialized_db: object) -> None:
    """get_trending_posts with no engagement data should return an empty list."""
    conn: sqlite3.Connection = initialized_db  # type: ignore[assignment]
    _seed_agent_and_post(conn)

    trending = get_trending_posts(conn, hours=24, min_engagement=1)
    assert trending == []


@patch("commons.apps.handlers.curation.trending_queries.json_handler")
@patch("commons.apps.handlers.curation.reaction_queries.json_handler")
def test_get_trending_posts_with_engagement(
    mock_reaction_json: object,
    mock_trending_json: object,
    initialized_db: object,
) -> None:
    """Posts with enough recent engagement should appear in trending results."""
    conn: sqlite3.Connection = initialized_db  # type: ignore[assignment]
    post_id = _seed_agent_and_post(conn)

    # Add agents for engagement
    for name in ("AGENT_A", "AGENT_B", "AGENT_C"):
        conn.execute(
            "INSERT OR IGNORE INTO agents (branch_name, display_name) VALUES (?, ?)",
            (name, name),
        )
    conn.commit()

    # Add reactions (3 total = meets min_engagement=3)
    add_reaction(conn, "AGENT_A", "thumbsup", post_id=post_id)
    add_reaction(conn, "AGENT_B", "agree", post_id=post_id)
    add_reaction(conn, "AGENT_C", "celebrate", post_id=post_id)

    trending = get_trending_posts(conn, hours=24, min_engagement=3)
    assert len(trending) == 1
    assert trending[0]["id"] == post_id
    assert trending[0]["reaction_count"] == 3
    assert trending[0]["engagement_count"] == 3
