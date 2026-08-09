# =================== AIPass ====================
# Name: test_create.py
# Description: Tests for email file creation handler
# Version: 1.0.0
# Created: 2026-04-25
# Modified: 2026-04-25
# =============================================

"""Tests for email file creation handler -- create_email_file, load_email_file."""

import json

import pytest
from pathlib import Path
from unittest.mock import MagicMock

import aipass.ai_mail.apps.handlers.email.create as mod


# ---- Fixtures ------------------------------------------------


@pytest.fixture(autouse=True)
def _silence_json_handler(monkeypatch):
    """Prevent log_operation from writing real JSON files during tests."""
    mock_jh = MagicMock()
    mock_jh.log_operation.return_value = True
    monkeypatch.setattr(mod, "json_handler", mock_jh)
    return mock_jh


@pytest.fixture(autouse=True)
def _mock_append_footer(monkeypatch):
    """Replace _get_append_footer so it returns message unchanged."""
    monkeypatch.setattr(mod, "_get_append_footer", lambda: lambda msg: msg)


@pytest.fixture(autouse=True)
def _mock_trigger_sent_purge(monkeypatch):
    """Replace _trigger_sent_purge with a no-op."""
    monkeypatch.setattr(mod, "_trigger_sent_purge", lambda _path: None)


def _make_user_info(tmp_path: Path) -> dict:
    """Build a minimal user_info dict pointing at tmp_path as mailbox."""
    return {
        "email_address": "test@branch",
        "display_name": "Test Branch",
        "timestamp_format": "%Y-%m-%d %H:%M:%S",
        "mailbox_path": str(tmp_path / ".ai_mail.local"),
    }


# ---- create_email_file tests ----------------------------------


def test_create_email_file_returns_path(tmp_path: Path):
    """create_email_file returns a Path inside the sent/ folder."""
    user_info = _make_user_info(tmp_path)

    result = mod.create_email_file(
        to_branch="@admin",
        subject="Hello",
        message="Test body",
        user_info=user_info,
    )

    assert isinstance(result, Path)
    assert result.exists()
    assert result.parent.name == "sent"


def test_create_email_file_json_content(tmp_path: Path):
    """Created file contains correct JSON fields."""
    user_info = _make_user_info(tmp_path)

    result = mod.create_email_file(
        to_branch="@admin",
        subject="Test Subject",
        message="Body text",
        user_info=user_info,
    )

    with open(result, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data["from"] == "test@branch"
    assert data["from_name"] == "Test Branch"
    assert data["to"] == "@admin"
    assert data["subject"] == "Test Subject"
    assert data["message"] == "Body text"
    assert data["status"] == "sent"
    assert "timestamp" in data


def test_create_email_file_has_id(tmp_path: Path):
    """Sent records carry an id so they can be referenced from the sent view.

    Without it `drone @ai_mail sent` renders every outbound message as [????????]
    (format.py falls back to that when `id` is absent) — visible but impossible to
    cite. Only reply-written files had an id; email and dispatch did not.
    """
    user_info = _make_user_info(tmp_path)

    result = mod.create_email_file(
        to_branch="@admin",
        subject="Referenceable",
        message="Body",
        user_info=user_info,
    )

    with open(result, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data.get("id"), "sent record must carry an id"
    assert len(data["id"]) == 8, "id must match the 8-char convention used elsewhere"


def test_create_email_file_ids_are_unique(tmp_path: Path):
    """Two sends in the same second must not collide — filenames are timestamp-based."""
    user_info = _make_user_info(tmp_path)

    ids = set()
    for i in range(3):
        result = mod.create_email_file(
            to_branch="@admin",
            subject=f"Subject {i}",
            message="Body",
            user_info=user_info,
        )
        with open(result, "r", encoding="utf-8") as f:
            ids.add(json.load(f)["id"])

    assert len(ids) == 3


def test_create_email_file_with_reply_to(tmp_path: Path):
    """reply_to field is included when provided."""
    user_info = _make_user_info(tmp_path)

    result = mod.create_email_file(
        to_branch="@worker",
        subject="Task",
        message="Do this",
        user_info=user_info,
        reply_to="@manager",
    )

    with open(result, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data["reply_to"] == "@manager"


def test_create_email_file_with_dispatched_to(tmp_path: Path):
    """dispatched_to field is included when provided."""
    user_info = _make_user_info(tmp_path)

    result = mod.create_email_file(
        to_branch="@worker",
        subject="Reply",
        message="Got it",
        user_info=user_info,
        dispatched_to="@original",
    )

    with open(result, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data["dispatched_to"] == "@original"


def test_create_email_file_no_optional_fields(tmp_path: Path):
    """Without reply_to/dispatched_to, those keys are absent from JSON."""
    user_info = _make_user_info(tmp_path)

    result = mod.create_email_file(
        to_branch="@admin",
        subject="Plain",
        message="Just a message",
        user_info=user_info,
    )

    with open(result, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert "reply_to" not in data
    assert "dispatched_to" not in data


def test_create_email_file_safe_filename(tmp_path: Path):
    """Special characters in subject are replaced in the filename."""
    user_info = _make_user_info(tmp_path)

    result = mod.create_email_file(
        to_branch="@admin",
        subject="Hello/World: Test!",
        message="Body",
        user_info=user_info,
    )

    # Filename should not contain / or : or !
    assert "/" not in result.name.replace("/", "")
    assert ":" not in result.name
    assert "!" not in result.name
    assert result.name.endswith(".json")


def test_create_email_file_creates_sent_dir(tmp_path: Path):
    """sent/ directory is created if it does not exist."""
    user_info = _make_user_info(tmp_path)
    sent_dir = Path(user_info["mailbox_path"]) / "sent"
    assert not sent_dir.exists()

    mod.create_email_file(
        to_branch="@admin",
        subject="First",
        message="Body",
        user_info=user_info,
    )

    assert sent_dir.is_dir()


# ---- load_email_file tests ------------------------------------


def test_load_email_file_valid(tmp_path: Path):
    """load_email_file returns dict for valid JSON file."""
    email_file = tmp_path / "test_email.json"
    data = {"from": "test@branch", "subject": "Hello", "message": "Body"}
    email_file.write_text(json.dumps(data), encoding="utf-8")

    result = mod.load_email_file(email_file)

    assert result is not None
    assert result["from"] == "test@branch"
    assert result["subject"] == "Hello"


def test_load_email_file_missing(tmp_path: Path):
    """load_email_file returns None for nonexistent file."""
    result = mod.load_email_file(tmp_path / "does_not_exist.json")

    assert result is None


def test_load_email_file_invalid_json(tmp_path: Path):
    """load_email_file returns None for invalid JSON content."""
    email_file = tmp_path / "bad.json"
    email_file.write_text("not valid json {{{", encoding="utf-8")

    result = mod.load_email_file(email_file)

    assert result is None
