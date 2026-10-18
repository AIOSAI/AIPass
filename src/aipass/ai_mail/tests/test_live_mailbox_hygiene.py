# =================== AIPass ====================
# Name: test_live_mailbox_hygiene.py
# Description: Guard that test fixtures never appear in real citizens' mailboxes
# Version: 1.0.2
# Created: 2026-08-16
# Modified: 2026-10-17
# =============================================

"""Tests for apps/handlers/paths.py's find_repo_root(), guarding live mailboxes for fixture leakage."""

# Real producers write ``YYYY-MM-DD HH:MM:SS``; test fixtures use ISO-8601 with Z, so a
# Z-suffixed timestamp in a live inbox signals fixture data. Reads live mailboxes deliberately.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(stdlib) — json.JSONDecodeError's contract on a malformed file, not re-verified

import json
import re
from pathlib import Path

import pytest

import aipass.ai_mail.tests.test_live_mailbox_hygiene as guard_mod
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
        unread = []
        for inbox in inboxes:
            try:
                data = json.loads(inbox.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                # Unreadable is not evidence of a fixture: never fails alone, but is named in the text.
                unread.append(f"{Path(inbox).parts[-3]}: {type(exc).__name__}")
                continue
            for msg in data.get("messages", []):
                if not isinstance(msg, dict):
                    continue
                if FIXTURE_TIMESTAMP.match(str(msg.get("timestamp", ""))):
                    strays.append(f"{Path(inbox).parts[-3]}: {msg.get('id')} {msg.get('subject')!r}")

        assert strays == [], (
            "Test fixtures found in live mailboxes:\n  "
            + "\n  ".join(strays)
            + "\nUnread, not checked:\n  "
            + "\n  ".join(unread or ["none"])
        )

    def test_the_guard_can_actually_see_the_mailboxes(self):
        """A guard that silently finds nothing to check protects nothing."""
        inboxes = _live_inboxes()
        if not inboxes:
            pytest.skip("not a source checkout — no live mailboxes to audit")

        assert len(inboxes) > 1, f"expected many citizens' inboxes, found {len(inboxes)}"

    def test_the_guard_fires_on_a_planted_stray(self, tmp_path, monkeypatch):
        """Mutation check: the green above must mean clean, not blind."""
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
        torn = tmp_path / "src" / "aipass" / "seedgo" / ".ai_mail.local"
        torn.mkdir(parents=True)
        (torn / "inbox.json").write_text("{not json", encoding="utf-8")
        monkeypatch.setattr(guard_mod, "find_repo_root", lambda: tmp_path)

        with pytest.raises(AssertionError, match="42284adc") as failure:
            self.test_no_fixture_shaped_timestamps_in_live_inboxes()
        unchecked = str(failure.value).split("Unread, not checked:")[1].split()
        assert unchecked[0] == "seedgo:"

    def test_the_signature_matches_this_suites_own_fixture_default(self):
        """Pin the guard to the shape it is guarding against (test_delivery.py's default)."""
        assert FIXTURE_TIMESTAMP.match("2026-03-29T12:00:00Z")
        assert FIXTURE_TIMESTAMP.match("2026-08-14T12:50:00Z")
        assert not FIXTURE_TIMESTAMP.match("2026-08-16 10:03:15")
