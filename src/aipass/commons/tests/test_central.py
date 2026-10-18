# =================== AIPass ====================
# Name: test_central.py
# Description: Tests for the central_writer handler
# Version: 1.2.0
# Created: 2026-03-29
# Modified: 2026-10-17
# =============================================

"""Tests for apps/handlers/central/central_writer.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that central_writer.py parses and imports
# seedgo: no-test-needed(constant) — AI_CENTRAL_DIR and BRANCH_REGISTRY_PATH's literal path segments

import json
import sqlite3
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from aipass.commons.apps.handlers.central import central_writer


def test_get_registered_branches_returns_dict(tmp_path: Path) -> None:
    """get_registered_branches should parse registry JSON into a name->path dict."""
    registry_file = tmp_path / "AIPASS_REGISTRY.json"
    registry_file.write_text(
        json.dumps(
            {
                "branches": [
                    {"name": "SEED", "path": "/projects/seed"},
                    {"name": "DRONE", "path": "/projects/drone"},
                    {"name": "", "path": "/empty-name"},
                ]
            }
        ),
        encoding="utf-8",
    )

    with patch.object(central_writer, "BRANCH_REGISTRY_PATH", str(registry_file)):
        result = central_writer.get_registered_branches()

    assert result == {"SEED": "/projects/seed", "DRONE": "/projects/drone"}
    assert "" not in result  # empty name entries are skipped


def test_get_registered_branches_missing_file() -> None:
    """get_registered_branches should raise FileNotFoundError for missing registry."""
    with patch.object(central_writer, "BRANCH_REGISTRY_PATH", "/fake/missing.json"):
        with pytest.raises(FileNotFoundError):
            central_writer.get_registered_branches()


@patch("aipass.commons.apps.handlers.central.central_writer.json_handler", autospec=True)
@patch("aipass.commons.apps.handlers.central.central_writer._read_last_checked", return_value="1970-01-01T00:00:00Z")
@patch("aipass.commons.apps.handlers.central.central_writer.get_registered_branches")
@patch("aipass.commons.apps.handlers.central.central_writer.close_db", side_effect=lambda conn: None)
@patch("aipass.commons.apps.handlers.central.central_writer.get_db")
def test_aggregate_branch_stats_with_data(
    mock_get_db: MagicMock,
    mock_close: MagicMock,
    mock_branches: MagicMock,
    mock_last_checked: MagicMock,
    mock_json: MagicMock,
    initialized_db: sqlite3.Connection,
) -> None:
    """aggregate_branch_stats should return per-branch mention/post/comment counts."""
    mock_get_db.return_value = initialized_db
    mock_branches.return_value = {"ALPHA": "/path/alpha", "BETA": "/path/beta"}

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
    initialized_db.execute("INSERT INTO comments (post_id, author, content) VALUES (1, 'BETA', 'Nice')")
    initialized_db.execute(
        "INSERT INTO mentions (post_id, mentioned_agent, mentioner_agent, read) VALUES (1, 'BETA', 'ALPHA', 0)"
    )
    initialized_db.commit()

    stats = central_writer.aggregate_branch_stats()

    assert "ALPHA" in stats
    assert "BETA" in stats
    assert stats["BETA"]["mentions"] == 1
    assert stats["ALPHA"]["mentions"] == 0
    assert stats["ALPHA"]["new_posts_since_last_visit"] == 1
    assert stats["BETA"]["new_comments_since_last_visit"] == 1


@patch("aipass.commons.apps.handlers.central.central_writer.json_handler", autospec=True)
@patch("aipass.commons.apps.handlers.central.central_writer.close_db", side_effect=lambda conn: None)
@patch("aipass.commons.apps.handlers.central.central_writer.get_db")
def test_query_top_threads_returns_sorted(
    mock_get_db: MagicMock,
    mock_close: MagicMock,
    mock_json: MagicMock,
    initialized_db: sqlite3.Connection,
) -> None:
    """query_top_threads should return threads sorted by most recent comment."""
    mock_get_db.return_value = initialized_db

    initialized_db.execute("INSERT OR IGNORE INTO agents (branch_name, display_name) VALUES ('A', 'A')")
    initialized_db.execute(
        "INSERT INTO posts (room_name, author, title, comment_count) VALUES ('general', 'A', 'Old Thread', 1)"
    )
    initialized_db.execute(
        "INSERT INTO posts (room_name, author, title, comment_count) VALUES ('general', 'A', 'Hot Thread', 2)"
    )
    initialized_db.execute(
        "INSERT INTO comments (post_id, author, content, created_at) VALUES (1, 'A', 'old', '2026-01-01T00:00:00Z')"
    )
    initialized_db.execute(
        "INSERT INTO comments (post_id, author, content, created_at) VALUES (2, 'A', 'new1', '2026-03-29T00:00:00Z')"
    )
    initialized_db.execute(
        "INSERT INTO comments (post_id, author, content, created_at) VALUES (2, 'A', 'new2', '2026-03-29T12:00:00Z')"
    )
    initialized_db.commit()

    threads = central_writer.query_top_threads()

    assert len(threads) == 2
    assert threads[0]["title"] == "Hot Thread"
    assert threads[0]["room"] == "general"
    assert threads[1]["title"] == "Old Thread"


@patch("aipass.commons.apps.handlers.central.central_writer.json_handler", autospec=True)
@patch("aipass.commons.apps.handlers.central.central_writer.close_db", side_effect=lambda conn: None)
@patch("aipass.commons.apps.handlers.central.central_writer.get_db")
def test_query_top_threads_empty_db(
    mock_get_db: MagicMock,
    mock_close: MagicMock,
    mock_json: MagicMock,
    initialized_db: sqlite3.Connection,
) -> None:
    """query_top_threads should return empty list when no posts have comments."""
    mock_get_db.return_value = initialized_db

    threads = central_writer.query_top_threads()
    assert threads == []


def test_build_central_data_structure() -> None:
    """build_central_data should produce the expected JSON structure."""
    stats = {"SEED": {"mentions": 2, "new_posts_since_last_visit": 5}}
    threads = [{"id": 1, "title": "Hot", "room": "general", "comment_count": 3, "last_activity": "2026-03-29"}]

    result = central_writer.build_central_data(stats, top_threads=threads)

    assert result["service"] == "the_commons"
    assert "last_updated" in result
    assert result["branch_stats"] == stats
    assert result["top_threads"] == threads


def test_build_central_data_defaults_top_threads() -> None:
    """build_central_data should default top_threads to empty list when None."""
    result = central_writer.build_central_data({})
    assert result["top_threads"] == []


def test_write_central_file_atomic_write(tmp_path: Path) -> None:
    """write_central_file should write to .tmp then atomically rename."""
    central_dir = tmp_path / "central"
    central_file = central_dir / "COMMONS.central.json"
    tmp_file = Path(str(central_file) + ".tmp")

    with (
        patch.object(central_writer, "AI_CENTRAL_DIR", str(central_dir)),
        patch.object(central_writer, "CENTRAL_FILE", str(central_file)),
    ):
        data = {"service": "the_commons", "branch_stats": {}}
        central_writer.write_central_file(data)

    assert central_file.exists()
    assert json.loads(central_file.read_text(encoding="utf-8")) == data
    assert not tmp_file.exists()


@patch("aipass.commons.apps.handlers.central.central_writer.json_handler", autospec=True)
@patch("aipass.commons.apps.handlers.central.central_writer.write_central_file")
@patch("aipass.commons.apps.handlers.central.central_writer.build_central_data")
@patch("aipass.commons.apps.handlers.central.central_writer.query_top_threads")
@patch("aipass.commons.apps.handlers.central.central_writer.aggregate_branch_stats")
def test_update_central_orchestrates_full_pipeline(
    mock_stats: MagicMock,
    mock_threads: MagicMock,
    mock_build: MagicMock,
    mock_write: MagicMock,
    mock_json: MagicMock,
) -> None:
    """update_central should call stats, threads, build, and write in order."""
    mock_stats.return_value = {"X": {"mentions": 0}}
    mock_threads.return_value = []
    mock_build.return_value = {"service": "the_commons", "branch_stats": {"X": {"mentions": 0}}}

    result = central_writer.update_central()

    mock_stats.assert_called_once()
    mock_threads.assert_called_once()
    mock_build.assert_called_once_with({"X": {"mentions": 0}}, top_threads=[])
    mock_write.assert_called_once()
    assert result["service"] == "the_commons"
