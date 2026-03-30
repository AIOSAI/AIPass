# ===================AIPASS====================
# META DATA HEADER
# Name: test_central.py - Central Writer & Dashboard Writer Tests
# Date: 2026-03-29
# Version: 1.0.0
# Category: commons/tests
#
# CHANGELOG (Max 5 entries):
#   - v1.0.0 (2026-03-29): Initial creation — central_writer, dashboard_writer,
#     dashboard_pipeline tests
#
# CODE STANDARDS:
#   - Pytest function style (no unittest classes)
#   - Uses initialized_db fixture from conftest.py for DB isolation
#   - Mocks prax logger, json_handler, file I/O, get_db/close_db
# =============================================

"""
Unit tests for central_writer, dashboard_writer, and dashboard_pipeline.

Covers:
- get_registered_branches: registry file parsing
- aggregate_branch_stats: DB-backed per-branch stat aggregation
- query_top_threads: thread ranking by last comment activity
- build_central_data: data structure assembly
- write_central_file: atomic file write
- update_central: full orchestrator
- write_commons_activity: dashboard section write-through
- update_commons_dashboard: DB query + dashboard push
- update_dashboards_for_event: pipeline coordination
"""

import json
import sqlite3
from unittest.mock import patch, mock_open, MagicMock

import pytest


# =============================================================================
# CENTRAL WRITER — get_registered_branches
# =============================================================================


def test_get_registered_branches_returns_dict() -> None:
    """get_registered_branches should parse registry JSON into a name->path dict."""
    from commons.apps.handlers.central import central_writer

    registry_data = json.dumps({
        "branches": [
            {"name": "SEED", "path": "/projects/seed"},
            {"name": "DRONE", "path": "/projects/drone"},
            {"name": "", "path": "/empty-name"},
        ]
    })

    with patch.object(central_writer, "BRANCH_REGISTRY_PATH", "/fake/AIPASS_REGISTRY.json"), \
         patch("builtins.open", mock_open(read_data=registry_data)):
        result = central_writer.get_registered_branches()

    assert result == {"SEED": "/projects/seed", "DRONE": "/projects/drone"}
    assert "" not in result  # empty name entries are skipped


def test_get_registered_branches_missing_file() -> None:
    """get_registered_branches should raise FileNotFoundError for missing registry."""
    from commons.apps.handlers.central import central_writer

    with patch.object(central_writer, "BRANCH_REGISTRY_PATH", "/fake/missing.json"):
        with pytest.raises(FileNotFoundError):
            central_writer.get_registered_branches()


# =============================================================================
# CENTRAL WRITER — aggregate_branch_stats (DB-backed)
# =============================================================================


@patch("commons.apps.handlers.central.central_writer.json_handler")
@patch("commons.apps.handlers.central.central_writer.logger")
@patch("commons.apps.handlers.central.central_writer._read_last_checked", return_value="1970-01-01T00:00:00Z")
@patch("commons.apps.handlers.central.central_writer.get_registered_branches")
@patch("commons.apps.handlers.central.central_writer.close_db", side_effect=lambda conn: None)
@patch("commons.apps.handlers.central.central_writer.get_db")
def test_aggregate_branch_stats_with_data(
    mock_get_db: MagicMock,
    mock_close: MagicMock,
    mock_branches: MagicMock,
    mock_last_checked: MagicMock,
    mock_logger: MagicMock,
    mock_json: MagicMock,
    initialized_db: sqlite3.Connection,
) -> None:
    """aggregate_branch_stats should return per-branch mention/post/comment counts."""
    mock_get_db.return_value = initialized_db
    mock_branches.return_value = {"ALPHA": "/path/alpha", "BETA": "/path/beta"}

    # Seed agents, a room, posts, comments, and mentions
    initialized_db.execute(
        "INSERT OR IGNORE INTO agents (branch_name, display_name) VALUES (?, ?)",
        ("ALPHA", "Alpha"),
    )
    initialized_db.execute(
        "INSERT OR IGNORE INTO agents (branch_name, display_name) VALUES (?, ?)",
        ("BETA", "Beta"),
    )
    initialized_db.execute(
        "INSERT INTO posts (room_name, author, title, content, comment_count) "
        "VALUES ('general', 'ALPHA', 'Hello', 'World', 1)"
    )
    initialized_db.execute(
        "INSERT INTO comments (post_id, author, content) VALUES (1, 'BETA', 'Nice')"
    )
    initialized_db.execute(
        "INSERT INTO mentions (post_id, mentioned_agent, mentioner_agent, read) "
        "VALUES (1, 'BETA', 'ALPHA', 0)"
    )
    initialized_db.commit()

    from commons.apps.handlers.central.central_writer import aggregate_branch_stats

    stats = aggregate_branch_stats()

    assert "ALPHA" in stats
    assert "BETA" in stats
    assert stats["BETA"]["mentions"] == 1
    assert stats["ALPHA"]["mentions"] == 0
    # Both branches see 1 post and 1 comment since epoch
    assert stats["ALPHA"]["new_posts_since_last_visit"] == 1
    assert stats["BETA"]["new_comments_since_last_visit"] == 1


# =============================================================================
# CENTRAL WRITER — query_top_threads (DB-backed)
# =============================================================================


@patch("commons.apps.handlers.central.central_writer.json_handler")
@patch("commons.apps.handlers.central.central_writer.close_db", side_effect=lambda conn: None)
@patch("commons.apps.handlers.central.central_writer.get_db")
def test_query_top_threads_returns_sorted(
    mock_get_db: MagicMock,
    mock_close: MagicMock,
    mock_json: MagicMock,
    initialized_db: sqlite3.Connection,
) -> None:
    """query_top_threads should return threads sorted by most recent comment."""
    mock_get_db.return_value = initialized_db

    initialized_db.execute(
        "INSERT OR IGNORE INTO agents (branch_name, display_name) VALUES ('A', 'A')"
    )
    # Two posts
    initialized_db.execute(
        "INSERT INTO posts (room_name, author, title, comment_count) "
        "VALUES ('general', 'A', 'Old Thread', 1)"
    )
    initialized_db.execute(
        "INSERT INTO posts (room_name, author, title, comment_count) "
        "VALUES ('general', 'A', 'Hot Thread', 2)"
    )
    # Older comment on post 1
    initialized_db.execute(
        "INSERT INTO comments (post_id, author, content, created_at) "
        "VALUES (1, 'A', 'old', '2026-01-01T00:00:00Z')"
    )
    # Newer comments on post 2
    initialized_db.execute(
        "INSERT INTO comments (post_id, author, content, created_at) "
        "VALUES (2, 'A', 'new1', '2026-03-29T00:00:00Z')"
    )
    initialized_db.execute(
        "INSERT INTO comments (post_id, author, content, created_at) "
        "VALUES (2, 'A', 'new2', '2026-03-29T12:00:00Z')"
    )
    initialized_db.commit()

    from commons.apps.handlers.central.central_writer import query_top_threads

    threads = query_top_threads()

    assert len(threads) == 2
    # Most recently active thread should be first
    assert threads[0]["title"] == "Hot Thread"
    assert threads[0]["room"] == "general"
    assert threads[1]["title"] == "Old Thread"


@patch("commons.apps.handlers.central.central_writer.json_handler")
@patch("commons.apps.handlers.central.central_writer.close_db", side_effect=lambda conn: None)
@patch("commons.apps.handlers.central.central_writer.get_db")
def test_query_top_threads_empty_db(
    mock_get_db: MagicMock,
    mock_close: MagicMock,
    mock_json: MagicMock,
    initialized_db: sqlite3.Connection,
) -> None:
    """query_top_threads should return empty list when no posts have comments."""
    mock_get_db.return_value = initialized_db

    from commons.apps.handlers.central.central_writer import query_top_threads

    threads = query_top_threads()
    assert threads == []


# =============================================================================
# CENTRAL WRITER — build_central_data
# =============================================================================


def test_build_central_data_structure() -> None:
    """build_central_data should produce the expected JSON structure."""
    from commons.apps.handlers.central.central_writer import build_central_data

    stats = {"SEED": {"mentions": 2, "new_posts_since_last_visit": 5}}
    threads = [{"id": 1, "title": "Hot", "room": "general", "comment_count": 3, "last_activity": "2026-03-29"}]

    result = build_central_data(stats, top_threads=threads)

    assert result["service"] == "the_commons"
    assert "last_updated" in result
    assert result["branch_stats"] == stats
    assert result["top_threads"] == threads


def test_build_central_data_defaults_top_threads() -> None:
    """build_central_data should default top_threads to empty list when None."""
    from commons.apps.handlers.central.central_writer import build_central_data

    result = build_central_data({})
    assert result["top_threads"] == []


# =============================================================================
# CENTRAL WRITER — write_central_file
# =============================================================================


@patch("commons.apps.handlers.central.central_writer.os.replace")
@patch("commons.apps.handlers.central.central_writer.os.makedirs")
@patch("builtins.open", new_callable=mock_open)
def test_write_central_file_atomic_write(
    mock_file: MagicMock,
    mock_makedirs: MagicMock,
    mock_replace: MagicMock,
) -> None:
    """write_central_file should write to .tmp then atomically rename."""
    from commons.apps.handlers.central.central_writer import write_central_file, CENTRAL_FILE

    data = {"service": "the_commons", "branch_stats": {}}
    write_central_file(data)

    mock_makedirs.assert_called_once()
    # Should write to tmp file
    mock_file.assert_called_once_with(CENTRAL_FILE + ".tmp", "w", encoding="utf-8")
    # Should atomically replace
    mock_replace.assert_called_once_with(CENTRAL_FILE + ".tmp", CENTRAL_FILE)


# =============================================================================
# CENTRAL WRITER — update_central (orchestrator)
# =============================================================================


@patch("commons.apps.handlers.central.central_writer.json_handler")
@patch("commons.apps.handlers.central.central_writer.logger")
@patch("commons.apps.handlers.central.central_writer.write_central_file")
@patch("commons.apps.handlers.central.central_writer.build_central_data")
@patch("commons.apps.handlers.central.central_writer.query_top_threads")
@patch("commons.apps.handlers.central.central_writer.aggregate_branch_stats")
def test_update_central_orchestrates_full_pipeline(
    mock_stats: MagicMock,
    mock_threads: MagicMock,
    mock_build: MagicMock,
    mock_write: MagicMock,
    mock_logger: MagicMock,
    mock_json: MagicMock,
) -> None:
    """update_central should call stats, threads, build, and write in order."""
    from commons.apps.handlers.central.central_writer import update_central

    mock_stats.return_value = {"X": {"mentions": 0}}
    mock_threads.return_value = []
    mock_build.return_value = {"service": "the_commons", "branch_stats": {"X": {"mentions": 0}}}

    result = update_central()

    mock_stats.assert_called_once()
    mock_threads.assert_called_once()
    mock_build.assert_called_once_with({"X": {"mentions": 0}}, top_threads=[])
    mock_write.assert_called_once()
    assert result["service"] == "the_commons"


# =============================================================================
# DASHBOARD WRITER — write_commons_activity
# =============================================================================


@patch("commons.apps.handlers.dashboard.dashboard_writer.json_handler")
@patch("commons.apps.handlers.dashboard.dashboard_writer.logger")
@patch("commons.apps.handlers.dashboard.dashboard_writer._get_write_section")
@patch("commons.apps.handlers.dashboard.dashboard_writer._find_branch_path")
def test_write_commons_activity_success(
    mock_find: MagicMock,
    mock_ws: MagicMock,
    mock_logger: MagicMock,
    mock_json: MagicMock,
) -> None:
    """write_commons_activity should call write_section with correct args on success."""
    mock_find.return_value = "/projects/seed"
    mock_write_section = MagicMock(return_value=True)
    mock_ws.return_value = mock_write_section

    from commons.apps.handlers.dashboard.dashboard_writer import write_commons_activity

    activity = {"managed_by": "the_commons", "mentions": 3}
    result = write_commons_activity("SEED", activity)

    assert result is True
    mock_write_section.assert_called_once_with("/projects/seed", "commons_activity", activity)


@patch("commons.apps.handlers.dashboard.dashboard_writer.logger")
@patch("commons.apps.handlers.dashboard.dashboard_writer._find_branch_path")
def test_write_commons_activity_branch_not_found(
    mock_find: MagicMock,
    mock_logger: MagicMock,
) -> None:
    """write_commons_activity should return False when branch path is not found."""
    mock_find.return_value = None

    from commons.apps.handlers.dashboard.dashboard_writer import write_commons_activity

    result = write_commons_activity("MISSING", {"mentions": 0})
    assert result is False


# =============================================================================
# DASHBOARD WRITER — update_commons_dashboard
# =============================================================================


@patch("commons.apps.handlers.dashboard.dashboard_writer.json_handler")
@patch("commons.apps.handlers.dashboard.dashboard_writer.logger")
@patch("commons.apps.handlers.dashboard.dashboard_writer._get_write_section")
@patch("commons.apps.handlers.dashboard.dashboard_writer._read_last_checked", return_value="1970-01-01T00:00:00Z")
@patch("commons.apps.handlers.dashboard.dashboard_writer._find_branch_path")
@patch("commons.apps.handlers.dashboard.dashboard_writer.close_db", side_effect=lambda conn: None)
@patch("commons.apps.handlers.dashboard.dashboard_writer.get_db")
def test_update_commons_dashboard_queries_db(
    mock_get_db: MagicMock,
    mock_close: MagicMock,
    mock_find: MagicMock,
    mock_last_checked: MagicMock,
    mock_ws: MagicMock,
    mock_logger: MagicMock,
    mock_json: MagicMock,
    initialized_db: sqlite3.Connection,
) -> None:
    """update_commons_dashboard should query DB for counts and push to dashboard."""
    mock_get_db.return_value = initialized_db
    mock_find.return_value = "/projects/seed"
    mock_write_section = MagicMock(return_value=True)
    mock_ws.return_value = mock_write_section

    # Seed data
    initialized_db.execute(
        "INSERT OR IGNORE INTO agents (branch_name, display_name) VALUES ('SEED', 'Seed')"
    )
    initialized_db.execute(
        "INSERT OR IGNORE INTO agents (branch_name, display_name) VALUES ('OTHER', 'Other')"
    )
    initialized_db.execute(
        "INSERT INTO posts (room_name, author, title) VALUES ('general', 'OTHER', 'Hey')"
    )
    initialized_db.execute(
        "INSERT INTO mentions (post_id, mentioned_agent, mentioner_agent, read) "
        "VALUES (1, 'SEED', 'OTHER', 0)"
    )
    initialized_db.commit()

    from commons.apps.handlers.dashboard.dashboard_writer import update_commons_dashboard

    result = update_commons_dashboard("SEED")

    assert result is True
    # Verify write_section was called with section data containing real counts
    call_args = mock_write_section.call_args
    section_data = call_args[0][2]
    assert section_data["managed_by"] == "the_commons"
    assert section_data["mentions"] == 1
    assert section_data["new_posts_since_last_visit"] == 1


# =============================================================================
# DASHBOARD PIPELINE — update_dashboards_for_event
# =============================================================================


@patch("commons.apps.handlers.notifications.dashboard_pipeline.json_handler")
@patch("commons.apps.handlers.notifications.dashboard_pipeline.logger")
@patch("commons.apps.handlers.notifications.dashboard_pipeline.update_central")
@patch("commons.apps.handlers.notifications.dashboard_pipeline.update_commons_dashboard")
@patch("commons.apps.handlers.notifications.dashboard_pipeline._collect_branches_to_update")
def test_update_dashboards_for_event_calls_pipeline(
    mock_collect: MagicMock,
    mock_update_dash: MagicMock,
    mock_update_central: MagicMock,
    mock_logger: MagicMock,
    mock_json: MagicMock,
) -> None:
    """update_dashboards_for_event should update each collected branch and central."""
    mock_collect.return_value = ["SEED", "DRONE"]
    mock_update_dash.return_value = True

    from commons.apps.handlers.notifications.dashboard_pipeline import update_dashboards_for_event

    count = update_dashboards_for_event("new_post", {"room_name": "general", "author": "FLOW"})

    assert count == 2
    assert mock_update_dash.call_count == 2
    mock_update_central.assert_called_once()


@patch("commons.apps.handlers.notifications.dashboard_pipeline.json_handler")
@patch("commons.apps.handlers.notifications.dashboard_pipeline.logger")
@patch("commons.apps.handlers.notifications.dashboard_pipeline.update_central")
@patch("commons.apps.handlers.notifications.dashboard_pipeline.update_commons_dashboard")
@patch("commons.apps.handlers.notifications.dashboard_pipeline._collect_branches_to_update")
def test_update_dashboards_for_event_handles_partial_failure(
    mock_collect: MagicMock,
    mock_update_dash: MagicMock,
    mock_update_central: MagicMock,
    mock_logger: MagicMock,
    mock_json: MagicMock,
) -> None:
    """Pipeline should continue updating remaining branches when one fails."""
    mock_collect.return_value = ["GOOD", "BAD", "ALSO_GOOD"]
    mock_update_dash.side_effect = [True, False, True]

    from commons.apps.handlers.notifications.dashboard_pipeline import update_dashboards_for_event

    count = update_dashboards_for_event("new_comment", {"room_name": "dev", "author": "X"})

    assert count == 2  # Only the two successful ones
    assert mock_update_dash.call_count == 3
