# =================== AIPass ====================
# Name: test_host_read_lane_feed.py
# Description: Tests for the read lane's feed cursor and name fence — limits, robustness, branch roots, the seat
# Version: 1.0.1
# Created: 2026-10-08
# Modified: 2026-10-24
# =============================================

"""Tests for apps/handlers/host/feed.py (the cursor) and the name fence in apps/handlers/host/reads.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that feed.py and reads.py parse and import

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from aipass.api.apps.handlers.host import feed as host_feed
from aipass.api.apps.handlers.host import reads as host_reads
from aipass.api.tests.support_host_read_lane import _RegistryBroken, _event, _write_feed

# The patch target stays this file's own constant rather than conftest's:
# seedgo's discarded_patch rule reads a target imported from this branch's
# package as one it judges.
PATCH_FEED_PATH = "aipass.api.apps.handlers.host.feed.feed_path"


class TestFeedCursor:
    """The cursor clamps both ends and never spins."""

    def test_no_cursor_returns_recent_window(self, feed_file: Path) -> None:
        """First contact gets the latest window, not the whole file."""
        _write_feed(feed_file, [_event("2026-08-14T10:00:00"), _event("2026-08-14T11:00:00")])

        result = host_feed.read_feed()

        assert len(result["events"]) == 2
        assert result["cursor"] == "2026-08-14T11:00:00"
        assert result["gap"] is False

    def test_empty_feed_returns_empty_envelope(self, feed_file: Path) -> None:
        """An empty feed is a real state, not an error."""
        feed_file.write_text("", encoding="utf-8")

        result = host_feed.read_feed()

        assert result["events"] == []
        assert result["gap"] is False

    def test_missing_feed_file_reads_as_empty(self, feed_file: Path) -> None:
        """No feed yet is quiet, matching @ai_mail's own doctrine."""
        result = host_feed.read_feed()

        assert result["events"] == []

    def test_cursor_mid_feed_returns_the_remainder(self, feed_file: Path) -> None:
        """The ordinary poll: everything at or after the cursor."""
        _write_feed(
            feed_file,
            [_event("2026-08-14T10:00:00"), _event("2026-08-14T11:00:00"), _event("2026-08-14T12:00:00")],
        )

        result = host_feed.read_feed(since="2026-08-14T11:00:00")

        assert [event["ts"] for event in result["events"]] == ["2026-08-14T11:00:00", "2026-08-14T12:00:00"]

    def test_boundary_event_is_redelivered(self, feed_file: Path) -> None:
        """At-least-once on purpose: two events can share a microsecond, and a
        duplicate is a nuisance where a dropped alert is the whole failure."""
        _write_feed(feed_file, [_event("2026-08-14T10:00:00"), _event("2026-08-14T11:00:00")])

        result = host_feed.read_feed(since="2026-08-14T11:00:00")

        assert [event["ts"] for event in result["events"]] == ["2026-08-14T11:00:00"]

    def test_cursor_older_than_feed_flags_the_gap(self, feed_file: Path) -> None:
        """THE trim case: clamp and TELL the phone, never under-report silently."""
        _write_feed(feed_file, [_event("2026-08-14T11:00:00"), _event("2026-08-14T12:00:00")])

        result = host_feed.read_feed(since="2026-08-14T09:00:00")

        assert result["gap"] is True
        assert result["gap_reason"] == host_feed.GAP_TRIMMED
        assert len(result["events"]) == 2

    def test_an_empty_cursor_reads_as_first_contact(self, feed_file: Path) -> None:
        """`?since=` with nothing after it is no cursor, not one older than every event."""
        _write_feed(feed_file, [_event("2026-08-14T10:00:00"), _event("2026-08-14T11:00:00")])

        result = host_feed.read_feed(since="")

        assert result["gap"] is False
        assert result["cursor"] == "2026-08-14T11:00:00"

    def test_cursor_ahead_of_feed_clamps_and_returns_empty(self, feed_file: Path) -> None:
        """The outage species: ahead of the feed clamps and delivers, never spins."""
        _write_feed(feed_file, [_event("2026-08-14T10:00:00")])

        result = host_feed.read_feed(since="2026-09-01T00:00:00")

        assert result["events"] == []
        assert result["cursor"] == "2026-08-14T10:00:00"
        assert result["gap"] is False

    def test_real_trim_leaves_an_old_cursor_flagged(self, feed_file: Path) -> None:
        """Simulates @ai_mail's actual 400->200 trim: a cursor into the dropped
        half must come back flagged, which a line-offset cursor could not do."""
        original = [_event(f"2026-08-14T10:{minute:02d}:00") for minute in range(60)]
        _write_feed(feed_file, original)
        old_cursor = original[5]["ts"]

        _write_feed(feed_file, original[30:])  # the trim drops the oldest half

        result = host_feed.read_feed(since=old_cursor)

        assert result["gap"] is True
        assert result["gap_reason"] == host_feed.GAP_TRIMMED


class TestFeedLimits:
    """Caps are enforced and reported."""

    def test_limit_caps_window_and_reports_more(self, feed_file: Path) -> None:
        """No silent caps — a truncated window says so."""
        _write_feed(feed_file, [_event(f"2026-08-14T10:{minute:02d}:00") for minute in range(10)])

        result = host_feed.read_feed(since="2026-08-14T10:00:00", limit=3)

        assert len(result["events"]) == 3
        assert result["more"] is True

    def test_more_is_false_when_window_is_complete(self, feed_file: Path) -> None:
        """The ordinary case does not cry wolf."""
        _write_feed(feed_file, [_event("2026-08-14T10:00:00")])

        result = host_feed.read_feed(since="2026-08-14T10:00:00", limit=10)

        assert result["more"] is False

    def test_limit_is_clamped_to_max(self, feed_file: Path) -> None:
        """A caller cannot ask for the world."""
        _write_feed(feed_file, [_event(f"2026-08-14T10:{minute:02d}:00") for minute in range(5)])

        result = host_feed.read_feed(limit=99999)

        assert len(result["events"]) == 5

    def test_zero_limit_is_raised_to_one(self, feed_file: Path) -> None:
        """A zero limit would poll forever returning nothing."""
        _write_feed(feed_file, [_event("2026-08-14T10:00:00")])

        result = host_feed.read_feed(limit=0)

        assert len(result["events"]) == 1


class TestFeedRobustness:
    """Malformed input is skipped, real failure is reported."""

    def test_malformed_lines_are_skipped(self, feed_file: Path) -> None:
        """One bad line must not blind the phone to the good ones."""
        feed_file.write_text(
            json.dumps(_event("2026-08-14T10:00:00")) + "\nnot json\n" + json.dumps(_event("2026-08-14T11:00:00")),
            encoding="utf-8",
        )

        result = host_feed.read_feed()

        assert len(result["events"]) == 2

    def test_lines_without_ts_are_skipped(self, feed_file: Path) -> None:
        """The cursor IS the ts — an event without one cannot be positioned."""
        feed_file.write_text(
            json.dumps({"kind": "mail", "title": "no ts"}) + "\n" + json.dumps(_event("2026-08-14T10:00:00")),
            encoding="utf-8",
        )

        result = host_feed.read_feed()

        assert len(result["events"]) == 1

    def test_file_order_is_preserved(self, feed_file: Path) -> None:
        """Never re-sorted: a sort would shuffle same-ts events and make the
        cursor non-monotonic."""
        _write_feed(feed_file, [_event("2026-08-14T12:00:00"), _event("2026-08-14T10:00:00")])

        result = host_feed.read_feed()

        assert [event["ts"] for event in result["events"]] == ["2026-08-14T12:00:00", "2026-08-14T10:00:00"]

    def test_unreadable_feed_raises_rather_than_faking_empty(self, feed_file: Path) -> None:
        """
        Fail honest: an unreadable feed is not 'no notifications'.
        """
        with patch(PATCH_FEED_PATH, return_value=feed_file.parent):
            with pytest.raises(host_feed.FeedUnavailable):
                host_feed.read_feed()


class TestFence:
    """A remote caller must never choose what gets read.

    read_file has refusals of its own, so each case pins the gate's message, not only the type.
    """

    def test_absolute_path_refused(self, fake_repo: dict) -> None:
        """An absolute name is the exact thing the fence exists to reject."""
        with pytest.raises(host_reads.ReadRefused) as exc:
            host_reads.read_file("demo", "/etc/passwd")

        assert str(exc.value) == "File must be relative to the root, not an absolute path"

    def test_a_nul_byte_is_refused_not_a_crash(self, fake_repo: dict) -> None:
        """realpath raises ValueError on a NUL, which would surface as a raw 500."""
        with pytest.raises(host_reads.ReadRefused) as exc:
            host_reads.read_file("demo", "hello\x00.txt")

        assert str(exc.value) == "File name may not contain a NUL byte"

    def test_parent_traversal_refused(self, fake_repo: dict) -> None:
        """'..' never survives, checked before the filesystem is touched."""
        with pytest.raises(host_reads.ReadRefused) as exc:
            host_reads.read_file("demo", "../../secret.txt")

        assert str(exc.value) == "File name may not contain '..'"

    def test_nested_traversal_refused(self, fake_repo: dict) -> None:
        """A '..' buried mid-path is the same attack with better manners."""
        with pytest.raises(host_reads.ReadRefused) as exc:
            host_reads.read_file("demo", "nested/../../secret.txt")

        assert str(exc.value) == "File name may not contain '..'"

    def test_symlink_escape_refused(self, fake_repo: dict) -> None:
        """The post-resolution check — the only gate that sees a symlink out."""
        if sys.platform == "win32":
            pytest.skip("POSIX symlinks")

        link = fake_repo["branch"] / "escape.txt"
        link.symlink_to(fake_repo["root"] / "secret.txt")

        with pytest.raises(host_reads.ReadRefused) as exc:
            host_reads.read_file("demo", "escape.txt")

        assert str(exc.value) == "File resolves outside the root"

    def test_symlink_into_a_sibling_sharing_the_prefix_refused(self, fake_repo: dict) -> None:
        """demo-evil starts with demo's path as a string; only the separator in the guard tells them apart."""
        if sys.platform == "win32":
            pytest.skip("POSIX symlinks")

        sibling = fake_repo["branch"].parent / (fake_repo["branch"].name + "-evil")
        sibling.mkdir()
        (sibling / "secret.txt").write_text("do not read me", encoding="utf-8")
        (fake_repo["branch"] / "escape.txt").symlink_to(sibling / "secret.txt")

        with pytest.raises(host_reads.ReadRefused) as exc:
            host_reads.read_file("demo", "escape.txt")

        assert str(exc.value) == "File resolves outside the root"

    def test_the_root_itself_lists_as_the_floor(self, fake_repo: dict) -> None:
        """'.' names the floor, the one candidate equal to the root rather than under it."""
        result = host_reads.list_dir("demo", ".")

        assert "hello.txt" in [entry["name"] for entry in result["entries"]]

    def test_empty_name_refused(self, fake_repo: dict) -> None:
        """An empty name is a bug, not a directory listing."""
        with pytest.raises(host_reads.ReadRefused) as exc:
            host_reads.read_file("demo", "   ")

        assert str(exc.value) == "A file name is required"

    def test_missing_file_refused(self, fake_repo: dict) -> None:
        """A name that resolves nowhere is refused, not returned empty."""
        with pytest.raises(host_reads.ReadRefused) as exc:
            host_reads.read_file("demo", "nope.txt")

        assert str(exc.value) == "No such file: 'nope.txt'"

    def test_legitimate_nested_file_accepted(self, fake_repo: dict) -> None:
        """Ordinary reads still work — the fence is not a wall."""
        result = host_reads.read_file("demo", "nested/deep.txt")

        assert result["content"] == "deep"


class TestResolveBranchRoot:
    """Branch names resolve through the registry, never from caller input."""

    def test_known_branch_resolves(self, fake_repo: dict) -> None:
        """The registry is the catalog; this handler only reads it."""
        assert host_reads.resolve_branch_root("demo") == fake_repo["branch"].resolve()

    def test_email_form_resolves(self, fake_repo: dict) -> None:
        """'@demo' is how the rest of the system addresses a citizen."""
        assert host_reads.resolve_branch_root("@demo") == fake_repo["branch"].resolve()

    def test_unknown_branch_refused(self, fake_repo: dict) -> None:
        """An unregistered name reaches no filesystem at all."""
        with pytest.raises(host_reads.ReadRefused):
            host_reads.resolve_branch_root("ghost")

    def test_empty_branch_refused(self, fake_repo: dict) -> None:
        """No branch means no read."""
        with pytest.raises(host_reads.ReadRefused):
            host_reads.resolve_branch_root("")

    def test_broken_registry_raises_unavailable_not_refused(self, fake_repo: dict) -> None:
        """A corrupt catalog must NOT read as 'unknown branch' — that would send
        an operator hunting for a typo while the real fault is the registry."""
        fake_repo["drone"].get_branch_info.side_effect = _RegistryBroken("corrupt")

        with pytest.raises(host_reads.ReadUnavailable):
            host_reads.resolve_branch_root("demo")

    def test_registry_path_that_does_not_exist_raises_unavailable(self, fake_repo: dict) -> None:
        """A registry pointing at a vanished directory is our problem to report."""
        fake_repo["drone"].get_branch_info.side_effect = None
        fake_repo["drone"].get_branch_info.return_value = {"name": "DEMO", "path": "/nope/not/here"}

        with pytest.raises(host_reads.ReadUnavailable):
            host_reads.resolve_branch_root("demo")


class TestSeating:
    """The server serves exactly one project and says which."""

    def test_repo_root_is_the_registry_parent(self, fake_repo: dict) -> None:
        """Root comes from drone's own resolution, not a guess."""
        assert host_reads.repo_root() == fake_repo["root"]

    def test_seated_project_is_the_root_name(self, fake_repo: dict) -> None:
        """The name a client must match on the project parameter."""
        assert host_reads.seated_project() == "FakeRepo"
