# =================== AIPass ====================
# Name: test_live_contacts_hygiene.py
# Description: Guard that test/probe fixtures never leak into the live contacts.json
# Version: 1.0.0
# Created: 2026-08-18
# Modified: 2026-08-18
# =============================================

"""Guard against tmp/fixture inbox paths leaking into the live address book.

@devpulse flagged (2026-08-16, e00936b6) that the live .ai_mail.local/contacts.json
carried 6 rows pointing at /tmp paths — 2 from an unisolated pytest run
(deliver_email_to_branch() auto-registers every recipient, and CONTACTS_FILE had
no conftest redirect the way FEED_PATH does) and 4 older ones from disposable
scratchpad sub-agent probes. branch_detection._get_contact_info() then resolved
one of those rows as "verified" identity, serving a dead mailbox in place of a
real one.

Two fixes landed alongside this guard: an autouse conftest fixture that
redirects CONTACTS_FILE for every test (tests/conftest.py), and a staleness
check in _get_contact_info() that refuses to vouch for a contact whose branch
root no longer exists on disk. This test is the live-state tripwire for the
first — companion to test_live_mailbox_hygiene.py's inbox guard.
"""

import json
import tempfile

import pytest

from aipass.ai_mail.apps.handlers.paths import find_repo_root

_TMPDIR = tempfile.gettempdir()


def _live_contacts_file():
    """The real contacts.json on disk, bypassing the autouse CONTACTS_FILE redirect."""
    return find_repo_root() / "src" / "aipass" / "ai_mail" / ".ai_mail.local" / "contacts.json"


def _live_contacts():
    """The live contacts dict, or None when not in a source checkout / unreadable."""
    contacts_file = _live_contacts_file()
    if not contacts_file.is_file():
        return None
    try:
        data = json.loads(contacts_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    contacts = data.get("contacts")
    return contacts if isinstance(contacts, dict) else None


class TestNoTmpPathsInLiveContacts:
    """Real contacts must point at real branch mailboxes, never a tmp scratch dir."""

    def test_no_tmp_inbox_paths_in_live_contacts(self):
        """An inbox path under the system tempdir means a test or probe wrote here."""
        contacts = _live_contacts()
        if contacts is None:
            pytest.skip("not a source checkout — no live contacts.json to audit")

        strays = [
            f"{name}: {info.get('inbox')}"
            for name, info in contacts.items()
            if isinstance(info, dict) and str(info.get("inbox", "")).startswith(_TMPDIR)
        ]

        assert not strays, "tmp-path rows found in live contacts.json:\n  " + "\n  ".join(strays)

    def test_the_guard_can_actually_see_the_contacts(self):
        """A guard reading an empty/missing file would pass forever, blind."""
        contacts = _live_contacts()
        if contacts is None:
            pytest.skip("not a source checkout — no live contacts.json to audit")

        assert len(contacts) > 1, f"expected many registered contacts, found {len(contacts)}"

    def test_the_guard_fires_on_a_planted_stray(self, tmp_path, monkeypatch):
        """Mutation check: green above must mean clean, not blind."""
        import aipass.ai_mail.tests.test_live_contacts_hygiene as guard_mod

        fake_repo = tmp_path / "repo"
        contacts_dir = fake_repo / "src" / "aipass" / "ai_mail" / ".ai_mail.local"
        contacts_dir.mkdir(parents=True)
        (contacts_dir / "contacts.json").write_text(
            json.dumps(
                {
                    "contacts": {
                        "ghost": {
                            "project": "AIPass",
                            "inbox": f"{tempfile.gettempdir()}/pytest-of-x/branches/ghost/.ai_mail.local/inbox.json",
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(guard_mod, "find_repo_root", lambda: fake_repo)

        with pytest.raises(AssertionError, match="ghost"):
            self.test_no_tmp_inbox_paths_in_live_contacts()
