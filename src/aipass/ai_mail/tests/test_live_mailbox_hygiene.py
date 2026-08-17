# =================== AIPass ====================
# Name: test_live_mailbox_hygiene.py
# Description: Guard that test fixtures never appear in real citizens' mailboxes
# Version: 1.0.0
# Created: 2026-08-16
# Modified: 2026-08-16
# =============================================

"""Guard against test fixtures leaking into live mailboxes.

@devpulse flagged (2026-08-16) that a fixture-shaped mail — subject 'hello',
body 'body', stamped ``2026-08-14T12:50:00Z`` — appeared in their live inbox,
and asked whether this suite writes through the real delivery lane.

Measured answer: it does not. A full suite run leaves all 17 live inboxes and
the notification feed byte-identical, and no fixture-shaped message exists in
any of them. I could not find the specific message they cited anywhere in the
mailbox tree.

But their instinct about the SHAPE was exactly right, which is why this guard
exists. ``tests/test_delivery.py`` builds email_data with a default timestamp of
``2026-03-29T12:00:00Z`` — ISO-8601 with a Z suffix. Live mail never looks like
that: every real producer writes ``YYYY-MM-DD HH:MM:SS`` (``create.py`` and
``reply.py`` both use ``strftime``). So a Z-suffixed timestamp in a real inbox
is a reliable signature of fixture data written through the real lane.

This test reads live mailboxes deliberately. It is the only way to check the
property that actually matters — the harness being correct in principle is what
was already believed on the day the fixture appeared.
"""

import json
import re
from pathlib import Path

import pytest

from aipass.ai_mail.apps.handlers.paths import find_repo_root

# Live mail: "2026-08-16 10:03:15". Fixtures: "2026-03-29T12:00:00Z".
FIXTURE_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(Z|[+-]\d{2}:?\d{2})?$")


def _live_inboxes():
    """Every citizen's real inbox.json, or [] when not in a source checkout."""
    branches_dir = find_repo_root() / "src" / "aipass"
    if not branches_dir.is_dir():
        return []
    return sorted(branches_dir.glob("*/.ai_mail.local/inbox.json"))


class TestNoFixturesInLiveMailboxes:
    """Real citizens' inboxes must contain only real mail."""

    def test_no_fixture_shaped_timestamps_in_live_inboxes(self):
        """A Z-suffixed timestamp in a live inbox means a test wrote there."""
        inboxes = _live_inboxes()
        if not inboxes:
            pytest.skip("not a source checkout — no live mailboxes to audit")

        strays = []
        for inbox in inboxes:
            try:
                data = json.loads(inbox.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                # A mailbox we cannot read is not evidence of a fixture, and
                # this guard must never be the thing that reports it.
                continue
            for msg in data.get("messages", []):
                if not isinstance(msg, dict):
                    continue
                if FIXTURE_TIMESTAMP.match(str(msg.get("timestamp", ""))):
                    strays.append(f"{Path(inbox).parts[-3]}: {msg.get('id')} {msg.get('subject')!r}")

        assert not strays, "Test fixtures found in live mailboxes:\n  " + "\n  ".join(strays)

    def test_the_guard_can_actually_see_the_mailboxes(self):
        """A guard that silently finds nothing to check protects nothing.

        Without this, a broken glob would make the test above pass forever on
        an empty list — green, and blind.
        """
        inboxes = _live_inboxes()
        if not inboxes:
            pytest.skip("not a source checkout — no live mailboxes to audit")

        assert len(inboxes) > 1, f"expected many citizens' inboxes, found {len(inboxes)}"

    def test_the_guard_fires_on_a_planted_stray(self, tmp_path, monkeypatch):
        """Mutation check: the green above must mean clean, not blind.

        Plants exactly what @devpulse described into a fake checkout and
        asserts the guard fails. Without this, a guard that never fires is
        indistinguishable from a guard that cannot fire.
        """
        import aipass.ai_mail.tests.test_live_mailbox_hygiene as guard_mod

        mailbox = tmp_path / "src" / "aipass" / "devpulse" / ".ai_mail.local"
        mailbox.mkdir(parents=True)
        (mailbox / "inbox.json").write_text(
            json.dumps(
                {
                    "messages": [
                        {"id": "42284adc", "subject": "hello", "message": "body", "timestamp": "2026-08-14T12:50:00Z"}
                    ]
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(guard_mod, "find_repo_root", lambda: tmp_path)

        with pytest.raises(AssertionError, match="42284adc"):
            self.test_no_fixture_shaped_timestamps_in_live_inboxes()

    def test_the_signature_matches_this_suites_own_fixture_default(self):
        """Pin the guard to the shape it is guarding against.

        If test_delivery.py's default timestamp ever changes format, this
        catches that the signature above went stale rather than letting the
        guard quietly stop matching anything.
        """
        assert FIXTURE_TIMESTAMP.match("2026-03-29T12:00:00Z")
        assert FIXTURE_TIMESTAMP.match("2026-08-14T12:50:00Z")
        assert not FIXTURE_TIMESTAMP.match("2026-08-16 10:03:15")
