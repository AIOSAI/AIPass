# ===================AIPASS====================
# META DATA HEADER
# Name: tests/conftest.py
# Date: 2025-11-08
# Version: 1.2.0
# Category: ai_mail/tests
#
# CHANGELOG (Max 5 entries):
#   - v1.2.0 (2026-08-11): Autouse feed isolation — tests never touch the real notifications.jsonl
#   - v1.1.0 (2026-03-27): Added mock_logger, mock_json_handler fixtures
#   - v1.0.0 (2025-11-08): Initial implementation - Shared pytest fixtures
#
# CODE STANDARDS:
#   - Error handling: Use error handler system (apps/handlers/error/)
# =============================================

"""Shared pytest fixtures for ai_mail tests"""

import os
import tempfile

# Redirect prax logs to temp directory during tests
# Must be set before any prax imports to catch logger initialization
if "AIPASS_TEST_LOG_DIR" not in os.environ:
    os.environ["AIPASS_TEST_LOG_DIR"] = tempfile.mkdtemp(prefix="aipass_test_logs_")

import pytest
import shutil
from pathlib import Path
from typing import Generator
from unittest.mock import MagicMock


@pytest.fixture(autouse=True)
def _isolate_notification_feed(tmp_path, monkeypatch):
    """Point the notification feed at tmp_path for EVERY test.

    Call sites in delivery, wake, dispatch_monitor and daemon write a feed line
    as a side effect. Without this guard a test run appends fake dispatch events
    to the real .aipass/notifications.jsonl that BAUD renders — the toast era
    hid that leak because a toast vanishes; a feed line does not.
    """
    import aipass.ai_mail.apps.handlers.notify as notify_mod

    monkeypatch.setattr(notify_mod, "FEED_PATH", tmp_path / "feed" / "notifications.jsonl")


@pytest.fixture(autouse=True)
def _no_real_mail_from_tests(monkeypatch):
    """Refuse any test that shells out to `drone @ai_mail send` (or dispatch).

    Earned the hard way on 2026-08-21: two tests exercising the manager wake-back
    called subprocess.run without mocking it, and BOTH delivered real mail into
    @devpulse's live inbox. The identity fence did not stop them — this suite runs
    inside a dispatched agent whose shell carries AIPASS_BRANCH_NAME, so drone
    stamped source=assigned and the send was, correctly, allowed.

    Same class as the notification-feed and contacts guards above: a test that
    writes into a citizen's real state. Mail is the worst of the three, because a
    delivered message asks a human to read it. Tests that mean to exercise the
    send path mock subprocess.run themselves, which overrides this.
    """
    import subprocess

    real_run = subprocess.run

    def _guarded(cmd, *args, **kwargs):
        if isinstance(cmd, (list, tuple)) and len(cmd) >= 3:
            argv = [str(c) for c in cmd[:3]]
            if argv[0].endswith("drone") and argv[1] == "@ai_mail" and argv[2] in ("send", "email", "dispatch"):
                raise AssertionError(
                    f"test tried to deliver REAL mail: {' '.join(str(c) for c in cmd[:4])} — "
                    "mock subprocess.run in this test"
                )
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", _guarded)


@pytest.fixture(autouse=True)
def _strip_ambient_identity_source(monkeypatch):
    """Clear AIPASS_CALLER_IDENTITY_SOURCE for EVERY test.

    This var is a CREDENTIAL: "assigned" or "passport" lets the identity fence
    accept a caller standing outside any branch. A dispatched agent's own shell
    carries it (this suite was first run under one holding source=passport), so
    an ambient value silently DISABLES the fence inside tests that never mention
    it — two fence tests passed while asserting the opposite of what they meant.

    Stripped globally rather than per-fixture: the leak defeats a security-shaped
    check, and the next test written would have to remember on its own. Tests that
    need a value set it themselves; monkeypatch.setenv in the body wins over this.
    """
    monkeypatch.delenv("AIPASS_CALLER_IDENTITY_SOURCE", raising=False)


@pytest.fixture(autouse=True)
def _isolate_contacts_file(tmp_path, monkeypatch):
    """Point CONTACTS_FILE at tmp_path for EVERY test.

    deliver_email_to_branch() auto-registers every recipient (and cross-project
    sender) in the address book as a side effect. Without this guard a test run
    upserts real rows into the live .ai_mail.local/contacts.json — 6 tmp/pytest
    and scratchpad-probe rows leaked in this way and were then trusted as
    "verified" identity by branch_detection's contact lookup, serving a fixture
    mailbox in place of a real one (found live, 2026-08-16, @devpulse).
    """
    import aipass.ai_mail.apps.handlers.email.contacts as contacts_mod

    monkeypatch.setattr(contacts_mod, "CONTACTS_FILE", tmp_path / "contacts" / "contacts.json")


@pytest.fixture
def temp_test_dir() -> Generator[Path, None, None]:
    """Creates temporary directory for testing, cleans up after"""
    test_dir = Path(tempfile.mkdtemp())
    yield test_dir
    if test_dir.exists():
        shutil.rmtree(test_dir)


@pytest.fixture
def sample_test_data() -> dict:
    """Provides sample test data

    Customize this fixture for your module's needs
    """
    return {"test_key": "test_value", "sample_data": "example"}


@pytest.fixture
def mock_logger(monkeypatch):
    """Mock the prax logger to prevent real log I/O during tests."""
    mock_log = MagicMock()
    return mock_log


@pytest.fixture
def mock_json_handler(monkeypatch):
    """Mock json_handler to prevent real JSON file operations during tests."""
    mock_json = MagicMock()
    mock_json.log_operation.return_value = True
    mock_json.ensure_module_jsons.return_value = True
    mock_json.load_json.return_value = None
    mock_json.save_json.return_value = True
    return mock_json
