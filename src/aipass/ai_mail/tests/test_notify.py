# =================== AIPass ====================
# Name: test_notify.py
# Description: Tests for the notification feed writer
# Version: 2.0.0
# Created: 2026-04-03
# Modified: 2026-08-11
# =============================================

"""Tests for notify module -- JSONL notification feed writer.

Every assertion here reads the real file the writer produced on a tmp_path
feed. The only mocks are json_handler (audit log) and logger (output noise) --
never the write path itself.
"""

import json
import threading
from datetime import datetime
from pathlib import Path

import pytest
from unittest.mock import MagicMock

import aipass.ai_mail.apps.handlers.notify as mod


# --- Fixtures --------------------------------------------------------


@pytest.fixture(autouse=True)
def _suppress_log_operation(monkeypatch):
    """Prevent json_handler.log_operation from touching real files."""
    monkeypatch.setattr(mod, "json_handler", MagicMock())


@pytest.fixture(autouse=True)
def _capture_logger(monkeypatch):
    """Replace the logger so failure paths can be asserted on."""
    fake = MagicMock()
    monkeypatch.setattr(mod, "logger", fake)
    return fake


@pytest.fixture
def feed(tmp_path, monkeypatch):
    """Point the writer at a temp feed file and hand back its path."""
    path = tmp_path / ".aipass" / "notifications.jsonl"
    monkeypatch.setattr(mod, "FEED_PATH", path)
    return path


def _lines(path: Path):
    """Read the feed back as parsed JSON objects."""
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


# --- Contract: what a feed line contains ------------------------------


def test_send_notification_writes_one_line_to_the_feed(feed):
    """A single call appends exactly one line to the feed file."""
    assert mod.send_notification("Title", "Body", "devpulse", "mail") is True

    assert feed.read_text(encoding="utf-8").count("\n") == 1
    assert len(_lines(feed)) == 1


def test_feed_line_carries_the_full_contract_schema(feed):
    """The line has exactly the five contract keys, with the passed values."""
    mod.send_notification("DEVPULSE -> AI_MAIL", "Retire OS toasts", "devpulse", "mail")

    event = _lines(feed)[0]
    assert set(event) == {"ts", "kind", "title", "body", "source"}
    assert event["title"] == "DEVPULSE -> AI_MAIL"
    assert event["body"] == "Retire OS toasts"
    assert event["source"] == "devpulse"
    assert event["kind"] == "mail"


def test_ts_is_iso8601_with_timezone_offset(feed):
    """ts round-trips through datetime.fromisoformat and carries an offset."""
    mod.send_notification("T", "B", "ai_mail", "system")

    parsed = datetime.fromisoformat(_lines(feed)[0]["ts"])
    assert parsed.tzinfo is not None
    assert parsed.utcoffset() is not None


def test_source_strips_leading_at_sign(feed):
    """source is the branch name with no @, whichever form the caller passes."""
    mod.send_notification("T", "B", "@wake_target", "wake")

    assert _lines(feed)[0]["source"] == "wake_target"


def test_defaults_are_ai_mail_and_system(feed):
    """Omitted source/kind default to the documented values."""
    mod.send_notification("T", "B")

    event = _lines(feed)[0]
    assert event["source"] == "ai_mail"
    assert event["kind"] == "system"


@pytest.mark.parametrize("kind", ["mail", "wake", "dispatch", "system"])
def test_all_four_contract_kinds_are_written_verbatim(feed, kind):
    """Each of the four valid kinds survives unchanged."""
    mod.send_notification("T", "B", "ai_mail", kind)

    assert _lines(feed)[0]["kind"] == kind


def test_unknown_kind_is_coerced_to_system_and_logged(feed, _capture_logger):
    """An off-contract kind is recorded as system -- and the swap is named, not silent."""
    mod.send_notification("T", "B", "ai_mail", "explosion")

    assert _lines(feed)[0]["kind"] == "system"
    assert _capture_logger.warning.called
    logged = str(_capture_logger.warning.call_args)
    assert "explosion" in logged


def test_multiline_body_stays_a_single_feed_line(feed):
    """Newlines in the body are JSON-escaped, never a second line."""
    mod.send_notification("T", "line one\nline two\nline three", "ai_mail", "mail")

    assert feed.read_text(encoding="utf-8").count("\n") == 1
    assert _lines(feed)[0]["body"] == "line one\nline two\nline three"


# --- Append-only behaviour -------------------------------------------


def test_appends_preserve_earlier_events_in_order(feed):
    """The feed is append-only: three calls leave three lines, oldest first."""
    for i in range(3):
        mod.send_notification(f"Title {i}", "B", "ai_mail", "system")

    titles = [event["title"] for event in _lines(feed)]
    assert titles == ["Title 0", "Title 1", "Title 2"]


def test_missing_parent_directory_is_created(tmp_path, monkeypatch):
    """A feed under a directory that does not exist yet still gets written."""
    path = tmp_path / "brand" / "new" / "notifications.jsonl"
    monkeypatch.setattr(mod, "FEED_PATH", path)

    assert mod.send_notification("T", "B") is True
    assert path.exists()


def test_lock_file_lives_beside_the_feed(feed):
    """The advisory lock is a sibling file, not the feed itself."""
    mod.send_notification("T", "B")

    assert (feed.parent / mod.FEED_LOCK_NAME).exists()
    assert len(_lines(feed)) == 1


def test_concurrent_appends_do_not_lose_or_corrupt_lines(feed):
    """8 threads x 20 appends = 160 intact JSON lines, none interleaved."""

    def worker(worker_id):
        for i in range(20):
            mod.send_notification(f"w{worker_id}-{i}", "B", "ai_mail", "system")

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    events = _lines(feed)
    assert len(events) == 160
    assert len({event["title"] for event in events}) == 160


# --- Trim policy ------------------------------------------------------


def test_feed_under_cap_is_never_trimmed(feed, monkeypatch):
    """Below FEED_MAX_LINES every line stays."""
    monkeypatch.setattr(mod, "FEED_MAX_LINES", 5)
    monkeypatch.setattr(mod, "FEED_KEEP_LINES", 2)

    for i in range(5):
        mod.send_notification(f"Title {i}", "B")

    assert len(_lines(feed)) == 5


def test_trim_keeps_the_newest_lines_once_past_the_cap(feed, monkeypatch):
    """Past the cap the feed drops to FEED_KEEP_LINES -- the NEWEST ones."""
    monkeypatch.setattr(mod, "FEED_MAX_LINES", 5)
    monkeypatch.setattr(mod, "FEED_KEEP_LINES", 2)

    for i in range(6):
        mod.send_notification(f"Title {i}", "B")

    titles = [event["title"] for event in _lines(feed)]
    assert titles == ["Title 4", "Title 5"]


def test_trimmed_feed_stays_valid_jsonl(feed, monkeypatch):
    """Every surviving line still parses -- the trim cuts on line boundaries."""
    monkeypatch.setattr(mod, "FEED_MAX_LINES", 3)
    monkeypatch.setattr(mod, "FEED_KEEP_LINES", 2)

    for i in range(10):
        mod.send_notification(f"Title {i}", 'body with, commas and "quotes"')

    events = _lines(feed)
    assert len(events) == 2
    assert all(set(event) == {"ts", "kind", "title", "body", "source"} for event in events)


def test_trim_leaves_no_temp_file_behind(feed, monkeypatch):
    """The .trim staging file is replaced into place, never left on disk."""
    monkeypatch.setattr(mod, "FEED_MAX_LINES", 2)
    monkeypatch.setattr(mod, "FEED_KEEP_LINES", 1)

    for i in range(4):
        mod.send_notification(f"Title {i}", "B")

    assert not (feed.parent / f"{feed.name}.trim").exists()


def test_trim_reports_false_when_feed_is_within_cap(feed):
    """_trim_jsonl returns False when there is nothing to do."""
    mod.send_notification("T", "B")

    assert mod._trim_jsonl(feed, mod.FEED_MAX_LINES, mod.FEED_KEEP_LINES) is False


def test_trim_reports_false_and_logs_when_feed_is_unreadable(tmp_path, _capture_logger):
    """A missing feed is an error the trim states, not a crash it hides."""
    missing = tmp_path / "not_here.jsonl"

    assert mod._trim_jsonl(missing, mod.FEED_MAX_LINES, mod.FEED_KEEP_LINES) is False
    assert _capture_logger.error.called


# --- Fail honest ------------------------------------------------------


def test_write_failure_returns_false_and_logs_error(tmp_path, monkeypatch, _capture_logger):
    """An unwritable feed path fails loudly: False plus a logged error."""
    blocker = tmp_path / "blocker"
    blocker.write_text("i am a file, not a directory", encoding="utf-8")
    monkeypatch.setattr(mod, "FEED_PATH", blocker / "notifications.jsonl")

    assert mod.send_notification("T", "B") is False
    assert _capture_logger.error.called


def test_no_toast_path_survives_anywhere_in_the_module():
    """Retirement pin: no executable dbus / notify-send / subprocess path remains.

    The module docstring still *names* the retired transports, so this scans for
    what would run them -- literals and calls -- not for the words themselves.
    """
    source = Path(mod.__file__).read_text(encoding="utf-8")

    assert '"notify-send"' not in source
    assert "import dbus" not in source
    assert "SessionBus" not in source
    assert "subprocess." not in source
    assert not hasattr(mod, "subprocess")
    assert not hasattr(mod, "shutil")
    assert not hasattr(mod, "_send_via_dbus")
    assert not hasattr(mod, "_send_via_notify_send")
    assert not hasattr(mod, "_DBUS_SCRIPT")
