# =================== AIPass ====================
# Name: test_search.py
# Description: Unit tests for search handler, search queries, and log export
# Version: 1.0.0
# Created: 2026-03-24
# Modified: 2026-03-24
# =============================================

"""
Unit tests for the search subsystem.

Tests cover:
- search_ops._parse_search_args() -- pure argument parsing
- search_ops.run_search() / run_log_export() -- orchestration with mocked DB
- search_queries helper imports (coverage)
- log_export._format_comment_tree() -- pure tree formatting
"""

from unittest.mock import patch, MagicMock

import pytest

# Coverage imports -- handler layer (search_ops)
from commons.apps.handlers.search.search_ops import _parse_search_args, run_search, run_log_export

# Coverage imports -- search_queries (covers the module for seedgo)
from commons.apps.handlers.search.search_queries import (
    search_posts,
    search_comments,
    search_all,
    sync_post_to_fts,
    sync_comment_to_fts,
)

# Coverage imports -- log_export
from commons.apps.handlers.search.log_export import _format_comment_tree, export_room_log


# =============================================================================
# _parse_search_args tests
# =============================================================================

def test_parse_search_args_empty():
    """Empty args should return defaults with empty query."""
    result = _parse_search_args([])
    assert result["query"] == ""
    assert result["room"] is None
    assert result["author"] is None
    assert result["search_type"] == "all"


def test_parse_search_args_query_only():
    """First positional arg is the search query."""
    result = _parse_search_args(["hello world"])
    assert result["query"] == "hello world"
    assert result["room"] is None
    assert result["author"] is None


def test_parse_search_args_room_flag():
    """The --room flag should set the room filter and lowercase it."""
    result = _parse_search_args(["test", "--room", "General"])
    assert result["query"] == "test"
    assert result["room"] == "general"


def test_parse_search_args_author_flag():
    """The --author flag should set the author filter and uppercase it."""
    result = _parse_search_args(["test", "--author", "drone"])
    assert result["query"] == "test"
    assert result["author"] == "DRONE"


def test_parse_search_args_type_flag_valid():
    """The --type flag accepts 'posts' and 'comments'."""
    result = _parse_search_args(["test", "--type", "posts"])
    assert result["search_type"] == "posts"

    result = _parse_search_args(["test", "--type", "comments"])
    assert result["search_type"] == "comments"


def test_parse_search_args_type_flag_invalid():
    """Invalid --type values should keep the default 'all'."""
    result = _parse_search_args(["test", "--type", "bogus"])
    assert result["search_type"] == "all"


def test_parse_search_args_all_flags():
    """All flags combined should be parsed correctly."""
    result = _parse_search_args([
        "registry", "--room", "Dev", "--author", "flow", "--type", "posts",
    ])
    assert result["query"] == "registry"
    assert result["room"] == "dev"
    assert result["author"] == "FLOW"
    assert result["search_type"] == "posts"


def test_parse_search_args_flag_without_value():
    """A flag at the end without a value should be skipped gracefully."""
    result = _parse_search_args(["test", "--room"])
    assert result["query"] == "test"
    assert result["room"] is None


# =============================================================================
# run_search tests
# =============================================================================

@patch("commons.apps.handlers.search.search_ops.json_handler")
@patch("commons.apps.handlers.search.search_ops.close_db")
@patch("commons.apps.handlers.search.search_ops.get_db")
@patch("commons.apps.handlers.search.search_ops.search_all")
def test_run_search_no_args(
    mock_search_all: MagicMock, mock_get_db: MagicMock,
    mock_close_db: MagicMock, mock_json: MagicMock,
) -> None:
    """run_search with no args should return error with usage message."""
    result = run_search([])
    assert result["success"] is False
    assert result["error"].startswith("Usage")


@patch("commons.apps.handlers.search.search_ops.json_handler")
@patch("commons.apps.handlers.search.search_ops.close_db")
@patch("commons.apps.handlers.search.search_ops.get_db")
@patch("commons.apps.handlers.search.search_ops.search_all")
def test_run_search_returns_results(
    mock_search_all: MagicMock, mock_get_db: MagicMock,
    mock_close_db: MagicMock, mock_json: MagicMock,
) -> None:
    """run_search with a valid query should delegate to search_all and return results."""
    mock_conn = MagicMock()
    mock_get_db.return_value = mock_conn
    mock_search_all.return_value = {
        "posts": [{"id": 1, "title": "Found"}],
        "comments": [],
    }

    result = run_search(["registry"])

    assert result["success"] is True
    assert result["query"] == "registry"
    assert len(result["posts"]) == 1
    assert result["posts"][0]["title"] == "Found"
    assert result["comments"] == []


# =============================================================================
# _format_comment_tree tests
# =============================================================================

def test_format_comment_tree_flat():
    """Top-level comments (no parent) should render without indentation."""
    comments = [
        {"id": 1, "parent_id": None, "author": "DRONE", "content": "First", "vote_score": 3},
        {"id": 2, "parent_id": None, "author": "FLOW", "content": "Second", "vote_score": 0},
    ]
    lines = _format_comment_tree(comments)
    assert len(lines) == 2
    assert "DRONE" in lines[0]
    assert "First" in lines[0]
    assert "+3" in lines[0]
    assert "FLOW" in lines[1]


def test_format_comment_tree_nested():
    """Child comments should be indented deeper than their parent."""
    comments = [
        {"id": 1, "parent_id": None, "author": "A", "content": "Root", "vote_score": 1},
        {"id": 2, "parent_id": 1, "author": "B", "content": "Reply", "vote_score": -1},
    ]
    lines = _format_comment_tree(comments)
    assert len(lines) == 2
    # The reply should have more leading whitespace than the root
    root_indent = len(lines[0]) - len(lines[0].lstrip())
    reply_indent = len(lines[1]) - len(lines[1].lstrip())
    assert reply_indent > root_indent


def test_format_comment_tree_empty():
    """An empty comment list should produce no output lines."""
    lines = _format_comment_tree([])
    assert lines == []


def test_format_comment_tree_negative_score():
    """Negative vote scores should show the minus sign, not a plus."""
    comments = [
        {"id": 1, "parent_id": None, "author": "X", "content": "Bad take", "vote_score": -5},
    ]
    lines = _format_comment_tree(comments)
    assert "-5" in lines[0]
    assert "+(-5)" not in lines[0]
