# =================== AIPass ====================
# Name: test_central_writer.py
# Description: Tests for central_writer -- branch inbox aggregation and central file writing
# Version: 1.0.0
# Created: 2026-04-03
# Modified: 2026-04-03
# =============================================

"""Tests for central_writer -- inbox stats aggregation, central file output."""

import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock

import aipass.ai_mail.apps.handlers.central_writer as mod


# --- Fixtures --------------------------------------------------------


@pytest.fixture(autouse=True)
def _suppress_json_handler(monkeypatch):
    """Prevent json_handler from touching real files."""
    monkeypatch.setattr(mod, "json_handler", MagicMock())


@pytest.fixture(autouse=True)
def _suppress_logger(monkeypatch):
    """Suppress logger output during tests."""
    monkeypatch.setattr(mod, "logger", MagicMock())


# --- extract_branch_name tests ----------------------------------------


def test_extract_branch_name_standard_path():
    """Standard .ai_mail.local path extracts uppercase branch name."""
    inbox = Path("/repo/src/aipass/seedgo/.ai_mail.local/inbox.json")
    assert mod.extract_branch_name(inbox) == "SEEDGO"


def test_extract_branch_name_nested_path():
    """Deeply nested path still extracts the immediate parent of .ai_mail.local."""
    inbox = Path("/repo/src/aipass/deep/nested/drone/.ai_mail.local/inbox.json")
    assert mod.extract_branch_name(inbox) == "DRONE"


def test_extract_branch_name_lowercase_dir():
    """Lowercase directory name is uppercased."""
    inbox = Path("/tmp/prax/.ai_mail.local/inbox.json")
    assert mod.extract_branch_name(inbox) == "PRAX"


# --- read_inbox_stats tests -------------------------------------------


def test_read_inbox_stats_valid_inbox(tmp_path):
    """Returns correct (unread, total) tuple from valid inbox.json."""
    inbox = tmp_path / "inbox.json"
    inbox.write_text(
        json.dumps({"unread_count": 3, "total_messages": 10}),
        encoding="utf-8",
    )
    assert mod.read_inbox_stats(inbox) == (3, 10)


def test_read_inbox_stats_defaults_missing_fields(tmp_path):
    """Defaults to 0 when unread_count or total_messages fields are absent."""
    inbox = tmp_path / "inbox.json"
    inbox.write_text(json.dumps({"other_field": "value"}), encoding="utf-8")
    assert mod.read_inbox_stats(inbox) == (0, 0)


def test_read_inbox_stats_partial_fields(tmp_path):
    """One field present, one absent -- present field used, absent defaults to 0."""
    inbox = tmp_path / "inbox.json"
    inbox.write_text(json.dumps({"unread_count": 7}), encoding="utf-8")
    assert mod.read_inbox_stats(inbox) == (7, 0)


# --- calculate_system_totals tests ------------------------------------


def test_calculate_system_totals_multiple_branches():
    """Correct sums across multiple branches."""
    branch_stats = {
        "SEEDGO": {"unread": 5, "total": 8},
        "DRONE": {"unread": 2, "total": 3},
        "PRAX": {"unread": 0, "total": 4},
    }
    result = mod.calculate_system_totals(branch_stats)
    assert result == {"total_unread": 7, "total_messages": 15}


def test_calculate_system_totals_empty_dict():
    """Empty dict gives zero totals."""
    result = mod.calculate_system_totals({})
    assert result == {"total_unread": 0, "total_messages": 0}


# --- build_central_data tests -----------------------------------------


def test_build_central_data_has_required_keys():
    """Output contains service, last_updated, branch_stats, system_totals."""
    branch_stats = {"SEEDGO": {"unread": 1, "total": 2}}
    result = mod.build_central_data(branch_stats)
    assert set(result.keys()) == {"service", "last_updated", "branch_stats", "system_totals"}


def test_build_central_data_service_is_ai_mail():
    """Service field is 'ai_mail'."""
    result = mod.build_central_data({})
    assert result["service"] == "ai_mail"


def test_build_central_data_includes_totals():
    """system_totals reflects aggregated branch_stats."""
    branch_stats = {
        "A": {"unread": 1, "total": 5},
        "B": {"unread": 3, "total": 7},
    }
    result = mod.build_central_data(branch_stats)
    assert result["system_totals"]["total_unread"] == 4
    assert result["system_totals"]["total_messages"] == 12


# --- find_all_inbox_files tests ----------------------------------------


def test_find_all_inbox_files_discovers_inboxes(tmp_path, monkeypatch):
    """Finds inbox.json files inside .ai_mail.local directories."""
    monkeypatch.setattr(mod, "_REPO_ROOT", tmp_path)

    # Create two branch inbox structures
    for branch in ("seedgo", "drone"):
        mail_dir = tmp_path / "src" / "aipass" / branch / ".ai_mail.local"
        mail_dir.mkdir(parents=True)
        (mail_dir / "inbox.json").write_text("{}", encoding="utf-8")

    result = mod.find_all_inbox_files()
    assert len(result) == 2
    names = {p.parent.parent.name for p in result}
    assert names == {"seedgo", "drone"}


def test_find_all_inbox_files_skips_archive(tmp_path, monkeypatch):
    """Skips .ai_mail.local dirs inside .archive paths."""
    monkeypatch.setattr(mod, "_REPO_ROOT", tmp_path)

    # Valid inbox
    valid = tmp_path / "branch" / ".ai_mail.local"
    valid.mkdir(parents=True)
    (valid / "inbox.json").write_text("{}", encoding="utf-8")

    # Archived inbox -- should be skipped
    archived = tmp_path / ".archive" / "old" / ".ai_mail.local"
    archived.mkdir(parents=True)
    (archived / "inbox.json").write_text("{}", encoding="utf-8")

    result = mod.find_all_inbox_files()
    assert len(result) == 1


def test_find_all_inbox_files_skips_backup(tmp_path, monkeypatch):
    """Skips .ai_mail.local dirs inside .backup paths."""
    monkeypatch.setattr(mod, "_REPO_ROOT", tmp_path)

    # Valid inbox
    valid = tmp_path / "branch" / ".ai_mail.local"
    valid.mkdir(parents=True)
    (valid / "inbox.json").write_text("{}", encoding="utf-8")

    # Backup inbox -- should be skipped
    backup = tmp_path / ".backup" / "snap" / ".ai_mail.local"
    backup.mkdir(parents=True)
    (backup / "inbox.json").write_text("{}", encoding="utf-8")

    result = mod.find_all_inbox_files()
    assert len(result) == 1


def test_find_all_inbox_files_skips_backups_dir(tmp_path, monkeypatch):
    """Skips .ai_mail.local dirs inside /backups/ paths."""
    monkeypatch.setattr(mod, "_REPO_ROOT", tmp_path)

    valid = tmp_path / "branch" / ".ai_mail.local"
    valid.mkdir(parents=True)
    (valid / "inbox.json").write_text("{}", encoding="utf-8")

    backup = tmp_path / "backups" / "snap" / ".ai_mail.local"
    backup.mkdir(parents=True)
    (backup / "inbox.json").write_text("{}", encoding="utf-8")

    result = mod.find_all_inbox_files()
    assert len(result) == 1


def test_find_all_inbox_files_ignores_dir_without_inbox(tmp_path, monkeypatch):
    """Skips .ai_mail.local dirs that don't contain inbox.json."""
    monkeypatch.setattr(mod, "_REPO_ROOT", tmp_path)

    empty_mail = tmp_path / "branch" / ".ai_mail.local"
    empty_mail.mkdir(parents=True)
    # No inbox.json created

    result = mod.find_all_inbox_files()
    assert len(result) == 0


# --- aggregate_branch_stats tests --------------------------------------


def test_aggregate_branch_stats_multiple_branches(tmp_path, monkeypatch):
    """Aggregates stats from multiple branches, filtering by registry."""
    # Create inbox files
    seedgo_mail = tmp_path / "seedgo" / ".ai_mail.local"
    seedgo_mail.mkdir(parents=True)
    (seedgo_mail / "inbox.json").write_text(
        json.dumps({"unread_count": 2, "total_messages": 5}),
        encoding="utf-8",
    )

    drone_mail = tmp_path / "drone" / ".ai_mail.local"
    drone_mail.mkdir(parents=True)
    (drone_mail / "inbox.json").write_text(
        json.dumps({"unread_count": 1, "total_messages": 3}),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        mod,
        "find_all_inbox_files",
        lambda: [seedgo_mail / "inbox.json", drone_mail / "inbox.json"],
    )
    monkeypatch.setattr(
        mod,
        "get_valid_branch_names",
        lambda: {"SEEDGO", "DRONE"},
    )

    result = mod.aggregate_branch_stats()
    assert result == {
        "SEEDGO": {"unread": 2, "total": 5},
        "DRONE": {"unread": 1, "total": 3},
    }


def test_aggregate_branch_stats_skips_unregistered(tmp_path, monkeypatch):
    """Branches not in registry are excluded from results."""
    rogue_mail = tmp_path / "rogue" / ".ai_mail.local"
    rogue_mail.mkdir(parents=True)
    (rogue_mail / "inbox.json").write_text(
        json.dumps({"unread_count": 9, "total_messages": 20}),
        encoding="utf-8",
    )

    valid_mail = tmp_path / "seedgo" / ".ai_mail.local"
    valid_mail.mkdir(parents=True)
    (valid_mail / "inbox.json").write_text(
        json.dumps({"unread_count": 1, "total_messages": 2}),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        mod,
        "find_all_inbox_files",
        lambda: [rogue_mail / "inbox.json", valid_mail / "inbox.json"],
    )
    monkeypatch.setattr(
        mod,
        "get_valid_branch_names",
        lambda: {"SEEDGO"},  # ROGUE not registered
    )

    result = mod.aggregate_branch_stats()
    assert "ROGUE" not in result
    assert "SEEDGO" in result
    assert result["SEEDGO"] == {"unread": 1, "total": 2}


def test_aggregate_branch_stats_skips_malformed_inbox(tmp_path, monkeypatch):
    """Malformed inbox.json is skipped with a warning, not a crash."""
    bad_mail = tmp_path / "bad" / ".ai_mail.local"
    bad_mail.mkdir(parents=True)
    (bad_mail / "inbox.json").write_text("NOT VALID JSON", encoding="utf-8")

    good_mail = tmp_path / "good" / ".ai_mail.local"
    good_mail.mkdir(parents=True)
    (good_mail / "inbox.json").write_text(
        json.dumps({"unread_count": 1, "total_messages": 1}),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        mod,
        "find_all_inbox_files",
        lambda: [bad_mail / "inbox.json", good_mail / "inbox.json"],
    )
    monkeypatch.setattr(
        mod,
        "get_valid_branch_names",
        lambda: {"BAD", "GOOD"},
    )

    result = mod.aggregate_branch_stats()
    assert "BAD" not in result
    assert "GOOD" in result


# --- write_central_file tests ------------------------------------------


def test_write_central_file_creates_file(tmp_path, monkeypatch):
    """Creates the central file with correct JSON content."""
    central_dir = tmp_path / ".ai_central"
    central_file = central_dir / "AI_MAIL.central.json"

    monkeypatch.setattr(mod, "AI_CENTRAL_DIR", central_dir)
    monkeypatch.setattr(mod, "CENTRAL_FILE", central_file)

    data = {
        "service": "ai_mail",
        "last_updated": "2026-04-03",
        "branch_stats": {"SEEDGO": {"unread": 1, "total": 2}},
        "system_totals": {"total_unread": 1, "total_messages": 2},
    }
    mod.write_central_file(data)

    assert central_file.exists()
    written = json.loads(central_file.read_text(encoding="utf-8"))
    assert written == data


def test_write_central_file_creates_directory(tmp_path, monkeypatch):
    """Creates the AI_CENTRAL directory if it doesn't exist."""
    central_dir = tmp_path / "new_dir" / ".ai_central"
    central_file = central_dir / "AI_MAIL.central.json"

    monkeypatch.setattr(mod, "AI_CENTRAL_DIR", central_dir)
    monkeypatch.setattr(mod, "CENTRAL_FILE", central_file)

    mod.write_central_file({"service": "ai_mail"})

    assert central_dir.exists()
    assert central_file.exists()


def test_write_central_file_overwrites_existing(tmp_path, monkeypatch):
    """Overwrites an existing central file with new data."""
    central_dir = tmp_path / ".ai_central"
    central_dir.mkdir(parents=True)
    central_file = central_dir / "AI_MAIL.central.json"
    central_file.write_text(json.dumps({"old": "data"}), encoding="utf-8")

    monkeypatch.setattr(mod, "AI_CENTRAL_DIR", central_dir)
    monkeypatch.setattr(mod, "CENTRAL_FILE", central_file)

    new_data = {"service": "ai_mail", "new": True}
    mod.write_central_file(new_data)

    written = json.loads(central_file.read_text(encoding="utf-8"))
    assert written == new_data
    assert "old" not in written
