# =================== AIPass ====================
# Name: test_monitoring_memory.py
# Description: Tests for memory health handler
# Version: 1.0.0
# Created: 2026-03-24
# Modified: 2026-03-24
# =============================================

"""Tests for memory health handler -- line counting and health status."""

import pytest
from pathlib import Path
from unittest.mock import patch

from aipass.ai_mail.apps.handlers.monitoring.memory import (
    count_file_lines,
    get_status_from_count,
    should_send_email,
    get_health_info,
    THRESHOLD_GREEN_MAX,
    THRESHOLD_YELLOW_MIN,
    THRESHOLD_YELLOW_MAX,
    THRESHOLD_EMAIL_TRIGGER,
    STATUS_GREEN,
    STATUS_YELLOW,
    STATUS_RED,
)


# ---- Fixtures ------------------------------------------------


@pytest.fixture(autouse=True)
def _silence_json_handler():
    """Prevent log_operation from writing real JSON files during tests."""
    with patch("aipass.ai_mail.apps.handlers.monitoring.memory.json_handler") as mock_jh:
        mock_jh.log_operation.return_value = True
        yield mock_jh


# ---- count_file_lines tests ----------------------------------


def test_count_file_lines_missing(tmp_path):
    """Nonexistent file returns 0."""
    result = count_file_lines(tmp_path / "nonexistent_file.txt")

    assert isinstance(result, int)
    assert result == 0


def test_count_file_lines_empty(tmp_path):
    """Empty file returns 0."""
    empty_file = tmp_path / "empty.txt"
    empty_file.write_text("", encoding="utf-8")

    result = count_file_lines(empty_file)

    assert isinstance(result, int)
    assert result == 0


def test_count_file_lines_content(tmp_path):
    """File with 5 lines returns 5."""
    file_path = tmp_path / "five_lines.txt"
    file_path.write_text("line1\nline2\nline3\nline4\nline5\n", encoding="utf-8")

    result = count_file_lines(file_path)

    assert isinstance(result, int)
    assert result == 5


# ---- get_status_from_count tests -----------------------------


def test_status_green():
    """100 lines is well within green threshold -- returns STATUS_GREEN."""
    assert 100 <= THRESHOLD_GREEN_MAX, "Precondition: 100 must be in green range"

    result = get_status_from_count(100)

    assert isinstance(result, str)
    assert result == STATUS_GREEN


def test_status_yellow():
    """450 lines falls in yellow range -- returns STATUS_YELLOW."""
    assert THRESHOLD_YELLOW_MIN <= 450 <= THRESHOLD_YELLOW_MAX, "Precondition: 450 must be in yellow range"

    result = get_status_from_count(450)

    assert isinstance(result, str)
    assert result == STATUS_YELLOW


def test_status_red():
    """600 lines is in red zone -- returns STATUS_RED."""
    assert 600 > THRESHOLD_YELLOW_MAX, "Precondition: 600 must be above yellow range"

    result = get_status_from_count(600)

    assert isinstance(result, str)
    assert result == STATUS_RED


def test_status_green_at_boundary():
    """Exactly THRESHOLD_GREEN_MAX (400) should still be green."""
    result = get_status_from_count(THRESHOLD_GREEN_MAX)
    assert result == STATUS_GREEN


def test_status_yellow_at_lower_boundary():
    """Exactly THRESHOLD_YELLOW_MIN (401) should be yellow."""
    result = get_status_from_count(THRESHOLD_YELLOW_MIN)
    assert result == STATUS_YELLOW


def test_status_yellow_at_upper_boundary():
    """Exactly THRESHOLD_YELLOW_MAX (550) should still be yellow."""
    result = get_status_from_count(THRESHOLD_YELLOW_MAX)
    assert result == STATUS_YELLOW


def test_status_red_at_boundary():
    """One above THRESHOLD_YELLOW_MAX (551) should be red."""
    result = get_status_from_count(THRESHOLD_YELLOW_MAX + 1)
    assert result == STATUS_RED


def test_status_zero_lines():
    """Zero lines should be green."""
    result = get_status_from_count(0)
    assert result == STATUS_GREEN


# ---- should_send_email tests ---------------------------------


def test_should_send_email_below():
    """500 is below THRESHOLD_EMAIL_TRIGGER (600) -- no email."""
    assert 500 < THRESHOLD_EMAIL_TRIGGER, "Precondition: 500 must be below trigger"

    result = should_send_email(500)

    assert isinstance(result, bool)
    assert result is False


def test_should_send_email_one_below_threshold():
    """599 is one below THRESHOLD_EMAIL_TRIGGER -- no email."""
    result = should_send_email(THRESHOLD_EMAIL_TRIGGER - 1)
    assert isinstance(result, bool)
    assert result is False


def test_should_send_email_at_threshold():
    """Exactly at THRESHOLD_EMAIL_TRIGGER -- email should be sent."""
    result = should_send_email(THRESHOLD_EMAIL_TRIGGER)
    assert isinstance(result, bool)
    assert result is True


def test_should_send_email_above_threshold():
    """Well above THRESHOLD_EMAIL_TRIGGER -- email should be sent."""
    result = should_send_email(THRESHOLD_EMAIL_TRIGGER + 100)
    assert isinstance(result, bool)
    assert result is True


# ---- get_health_info tests -----------------------------------


def test_get_health_info(tmp_path):
    """10-line file returns correct health dict."""
    file_path = tmp_path / "ten_lines.txt"
    lines = "\n".join(f"line {i}" for i in range(1, 11)) + "\n"
    file_path.write_text(lines, encoding="utf-8")

    result = get_health_info(file_path)

    assert isinstance(result, dict)
    # Verify exactly these keys exist -- no more, no fewer
    assert set(result.keys()) == {"line_count", "status", "needs_email", "file_path"}

    # Verify exact values and types
    assert result["line_count"] == 10
    assert isinstance(result["line_count"], int)

    assert result["status"] == STATUS_GREEN
    assert isinstance(result["status"], str)

    assert result["needs_email"] is False
    assert isinstance(result["needs_email"], bool)

    assert result["file_path"] == str(file_path)
