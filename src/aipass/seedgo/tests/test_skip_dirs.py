# =================== AIPass ====================
# Name: test_skip_dirs.py
# Description: Unit tests for skip_dirs (is_throwaway_path routine-case logging regression)
# Version: 1.0.2
# Created: 2026-07-27
# Modified: 2026-09-27
# =============================================

"""Tests for apps/handlers/aipass_standards/skip_dirs.py's is_throwaway_path."""

# Regression coverage for the runaway-log bug (@trigger dispatch 98833403):
# is_throwaway_path used to logger.info() every time a path was NOT under a temp
# dir -- the routine outcome for ~100% of files during a branch audit walk,
# flooding system_logs/seedgo_skip_dirs.log at hundreds of lines/min.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(constant) — is_disabled_file's DISABLED_FILE_MARKER substring check
# seedgo: no-test-needed(ruff) — that is_prototype_file and SOURCE_SKIP_DIRS parse and import (unexercised here)

from unittest.mock import MagicMock

import pytest

from aipass.seedgo.apps.handlers.aipass_standards import skip_dirs


@pytest.fixture(autouse=True)
def _mock_infrastructure(monkeypatch):
    """Patch skip_dirs' logger seam directly, at the edge."""
    mock_logger = MagicMock()
    monkeypatch.setattr(skip_dirs, "logger", mock_logger)
    return mock_logger


def test_throwaway_path_under_temp_root_true(tmp_path):
    scratch = tmp_path / "scratch.py"
    scratch.write_text("pass", encoding="utf-8")

    assert skip_dirs.is_throwaway_path(str(scratch)) is True


def test_throwaway_path_outside_temp_root_false_no_log(tmp_path, monkeypatch, _mock_infrastructure):
    """Routine non-match (the common case) returns False and never logs."""
    monkeypatch.setattr(skip_dirs, "_get_temp_roots", lambda: [tmp_path / "not-this-one"])
    real_file = tmp_path / "src" / "module.py"
    real_file.parent.mkdir(parents=True)
    real_file.write_text("pass", encoding="utf-8")

    assert skip_dirs.is_throwaway_path(str(real_file)) is False
    _mock_infrastructure.info.assert_not_called()


def test_throwaway_path_scratchpad_true(tmp_path):
    scratchpad_dir = tmp_path / "scratchpad"
    scratchpad_dir.mkdir()
    fp = scratchpad_dir / "notes.py"
    fp.write_text("pass", encoding="utf-8")

    assert skip_dirs.is_throwaway_path(str(fp)) is True
