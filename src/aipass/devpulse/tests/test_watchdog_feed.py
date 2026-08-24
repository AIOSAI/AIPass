# =================== AIPass ====================
# Name: test_watchdog_feed.py
# Description: Tests for the watchdog feed handler (FPLAN-0451 P2 — push replaces poll)
# Version: 1.0.0
# Created: 2026-08-21
# Modified: 2026-08-21
# =============================================

"""Tests for drain_feed — reading completions off @ai_mail's notification feed.

The defect these pin is the one that made this handler a new file rather than a
tweak to wire.py: THE FEED IS NOT APPEND-ONLY. ``notify._trim_feed`` rewrites it
with ``os.replace`` once it passes 400 lines, so the inode changes and every
byte offset and line index goes stale silently. wire.py's cursor is a byte
offset. Reusing it here would either replay the whole file or skip events, with
nothing anywhere saying so — and it would have shipped looking fine, because the
feed only trims once it is full.

``test_survives_a_trim`` is therefore the load-bearing test in this file.

No test touches the real feed: every case passes ``feed_file_path`` explicitly.
"""

import json
import os
from pathlib import Path

import pytest

from aipass.devpulse.apps.handlers.watchdog import feed


def _event(kind: str = "dispatch", source: str = "canary", title: str = "@canary completed", minute: int = 0) -> str:
    """One feed line in the shape notify._build_event writes."""
    return json.dumps(
        {
            "ts": f"2026-08-21T17:{minute:02d}:00.000000-07:00",
            "kind": kind,
            "title": title,
            "body": f"Duration: {minute}s",
            "source": source,
        }
    )


@pytest.fixture(autouse=True)
def _mail_doors(hermetic_mail_doors):
    """TestRepoRoot re-roots through @ai_mail's door; the transplant must not
    depend on this machine's live registry marker (the CI fresh-checkout
    failure, PR #739)."""
    return hermetic_mail_doors


@pytest.fixture
def feed_file(tmp_path: Path) -> Path:
    return tmp_path / "notifications.jsonl"


@pytest.fixture
def cursor(tmp_path: Path) -> Path:
    return tmp_path / "feed_cursor.json"


def _write(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class TestFirstLook:
    """A first drain must absorb the backlog, never deliver it as news."""

    def test_first_look_delivers_nothing(self, feed_file, cursor):
        _write(feed_file, [_event(minute=i) for i in range(5)])

        records, state = feed.drain_feed(cursor, feed_file_path=feed_file)

        assert records == []
        assert len(state["seen"]) == 5
        assert state["seeded"] is True

    def test_first_look_can_be_opted_out(self, feed_file, cursor):
        """seed_if_new=False is the honest replay-everything door."""
        _write(feed_file, [_event(minute=i) for i in range(3)])

        records, _ = feed.drain_feed(cursor, feed_file_path=feed_file, seed_if_new=False)

        assert len(records) == 3

    def test_missing_feed_is_not_an_error(self, feed_file, cursor):
        """The feed is created by the first notification anyone sends."""
        records, state = feed.drain_feed(cursor, feed_file_path=feed_file)

        assert records == []
        assert state["seeded"] is False


class TestDelivery:
    def test_new_event_is_delivered_once(self, feed_file, cursor):
        _write(feed_file, [_event(minute=0)])
        feed.drain_feed(cursor, feed_file_path=feed_file)

        _write(feed_file, [_event(minute=0), _event(source="api", title="@api completed", minute=1)])
        records, _ = feed.drain_feed(cursor, feed_file_path=feed_file)

        assert len(records) == 1
        assert records[0]["source"] == "api"

        again, _ = feed.drain_feed(cursor, feed_file_path=feed_file)
        assert again == []

    def test_every_record_carries_a_digest(self, feed_file, cursor):
        """The idempotency key the feed itself does not provide (DPLAN-0314)."""
        _write(feed_file, [_event(minute=0)])
        feed.drain_feed(cursor, feed_file_path=feed_file)
        _write(feed_file, [_event(minute=0), _event(minute=1)])

        records, _ = feed.drain_feed(cursor, feed_file_path=feed_file)

        assert records[0]["digest"]
        assert len(records[0]["digest"]) == 16

    def test_unchanged_feed_reads_nothing(self, feed_file, cursor):
        """The idle path: matching (mtime, size) returns without opening the file."""
        _write(feed_file, [_event(minute=0)])
        feed.drain_feed(cursor, feed_file_path=feed_file)

        feed_file.unlink()  # a read would now raise; the stat gate must short-circuit
        records, _ = feed.drain_feed(cursor, feed_file_path=feed_file)

        assert records == []


class TestKindFilter:
    def test_mail_does_not_wake(self, feed_file, cursor):
        """Every email writes a feed line, including this branch's own."""
        _write(feed_file, [_event(minute=0)])
        feed.drain_feed(cursor, feed_file_path=feed_file)

        _write(feed_file, [_event(minute=0), _event(kind="mail", title="DEVPULSE -> FLOW", minute=1)])
        records, _ = feed.drain_feed(cursor, feed_file_path=feed_file)

        assert records == []

    def test_muted_kind_is_marked_seen_not_deferred(self, feed_file, cursor):
        """A muted line must never resurface later as backlog when kinds widen."""
        _write(feed_file, [_event(minute=0)])
        feed.drain_feed(cursor, feed_file_path=feed_file)
        _write(feed_file, [_event(minute=0), _event(kind="mail", minute=1)])
        feed.drain_feed(cursor, feed_file_path=feed_file)

        records, _ = feed.drain_feed(cursor, kinds=("dispatch", "wake", "mail"), feed_file_path=feed_file)

        assert records == []

    def test_wake_is_in_the_default_set(self, feed_file, cursor):
        _write(feed_file, [_event(minute=0)])
        feed.drain_feed(cursor, feed_file_path=feed_file)

        _write(feed_file, [_event(minute=0), _event(kind="wake", minute=1)])
        records, _ = feed.drain_feed(cursor, feed_file_path=feed_file)

        assert len(records) == 1


class TestTrim:
    """The reason this handler does not reuse wire.py's byte cursor."""

    def test_survives_a_trim(self, feed_file, cursor, tmp_path):
        _write(feed_file, [_event(minute=i) for i in range(6)])
        feed.drain_feed(cursor, feed_file_path=feed_file)

        # notify._trim_feed: keep the newest lines, write a temp, os.replace.
        kept = feed_file.read_text(encoding="utf-8").splitlines()[-2:]
        arrival = _event(source="hooks", title="@hooks completed", minute=20)
        tmp = tmp_path / "trim.tmp"
        tmp.write_text("\n".join([*kept, arrival]) + "\n", encoding="utf-8")
        os.replace(tmp, feed_file)

        records, _ = feed.drain_feed(cursor, feed_file_path=feed_file)

        assert len(records) == 1, "a trim must not replay the retained lines"
        assert records[0]["source"] == "hooks"

    def test_trim_does_not_resurface_retained_lines(self, feed_file, cursor, tmp_path):
        _write(feed_file, [_event(minute=i) for i in range(6)])
        feed.drain_feed(cursor, feed_file_path=feed_file)

        kept = feed_file.read_text(encoding="utf-8").splitlines()[-3:]
        tmp = tmp_path / "trim.tmp"
        tmp.write_text("\n".join(kept) + "\n", encoding="utf-8")
        os.replace(tmp, feed_file)

        records, _ = feed.drain_feed(cursor, feed_file_path=feed_file)

        assert records == []


class TestResilience:
    def test_corrupt_cursor_replays_rather_than_wedging(self, feed_file, cursor):
        """Duplicates over silence — wire.py's doctrine, held here too."""
        _write(feed_file, [_event(minute=0)])
        cursor.write_text("{not json", encoding="utf-8")

        records, state = feed.drain_feed(cursor, feed_file_path=feed_file, seed_if_new=False)

        assert len(records) == 1
        assert state["seeded"] is True

    def test_unparseable_line_is_stepped_over(self, feed_file, cursor):
        """Junk must never wedge delivery at the same position forever."""
        _write(feed_file, ["{ this is not json", _event(minute=1)])

        records, _ = feed.drain_feed(cursor, feed_file_path=feed_file, seed_if_new=False)

        assert len(records) == 1
        assert records[0]["source"] == "canary"

    def test_blank_lines_are_ignored(self, feed_file, cursor):
        feed_file.write_text(_event(minute=0) + "\n\n\n", encoding="utf-8")

        records, _ = feed.drain_feed(cursor, feed_file_path=feed_file, seed_if_new=False)

        assert len(records) == 1

    def test_digest_memory_is_bounded(self, feed_file, cursor):
        """Bounded at the feed's own maximum, so a digest never ages out early."""
        _write(feed_file, [_event(minute=i % 60) + f'{{"n":{i}}}' for i in range(500)])

        _, state = feed.drain_feed(cursor, feed_file_path=feed_file)

        assert len(state["seen"]) == feed.CURSOR_KEEP_DIGESTS


class TestRepoRoot:
    """Pins the defect found wiring this into wire.py (FPLAN-0451).

    The wire honoured an injected ``repo_root`` for its own events file and
    cursor, but the feed source ignored it and resolved through @ai_mail's
    door to the LIVE repo — so two wire tests read production's 216-line feed
    from inside tmp_path. A handler that reaches the real tree when handed a
    fake root is the "tests that fall back to cwd write the live tree" defect
    wearing a different coat.
    """

    def test_re_roots_onto_an_injected_tree(self, tmp_path):
        rerooted = feed.feed_file(tmp_path)

        assert tmp_path in rerooted.parents
        assert rerooted != feed.feed_file()

    def test_keeps_the_shape_the_owner_defines(self, tmp_path):
        """The location is learned from feed_path(), never restated here."""
        live = feed.feed_file()
        rerooted = feed.feed_file(tmp_path)

        assert rerooted.name == live.name
        assert rerooted.parent.name == live.parent.name

    def test_no_root_uses_the_owners_answer_unchanged(self):
        """Reference the PUBLIC door, not notify internals: feed.py consumes
        aipass.ai_mail.feed_path, so that is the answer 'unchanged' means —
        and it is what the hermetic fixture patches, keeping this true off
        the live machine too."""
        from aipass import ai_mail

        assert feed.feed_file() == ai_mail.feed_path()

    def test_drain_honours_repo_root(self, tmp_path, cursor):
        """The end-to-end guarantee: an injected root never reads production."""
        planted = feed.feed_file(tmp_path)
        planted.parent.mkdir(parents=True, exist_ok=True)
        planted.write_text(_event(source="isolated") + "\n", encoding="utf-8")

        records, _ = feed.drain_feed(cursor, repo_root=tmp_path, seed_if_new=False)

        assert len(records) == 1
        assert records[0]["source"] == "isolated"


class TestFormat:
    def test_renders_a_single_line(self):
        line = feed.format_feed_event(
            {"kind": "dispatch", "source": "canary", "title": "@canary completed", "body": "Duration: 42s"}
        )

        assert line == 'DISPATCH @canary title="@canary completed" detail="Duration: 42s"'
        assert "\n" not in line

    def test_multiline_body_is_collapsed(self):
        """One event is one line — a wire line that wraps is two events to a reader."""
        line = feed.format_feed_event({"kind": "mail", "source": "api", "title": "A\nB", "body": "c\n  d"})

        assert "\n" not in line
        assert 'title="A B"' in line

    def test_quotes_are_neutralised(self):
        line = feed.format_feed_event({"kind": "dispatch", "source": "x", "title": 'say "hi"', "body": ""})

        assert '"hi"' not in line
        assert "'hi'" in line

    def test_missing_fields_do_not_raise(self):
        """A malformed event still renders — a formatter that raises kills the wire."""
        assert feed.format_feed_event({}) == '? @? title="?"'
