# =================== AIPass ====================
# Name: test_email.py
# Version: 1.3.0
# Description: Tests for email notification handler
# Branch: hooks
# Created: 2026-05-21
# Modified: 2026-06-09
# =============================================

"""Tests for handlers/notification/email.py."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _isolated_mail_cadence(tmp_path_factory, monkeypatch):
    """Keep the mail-banner cadence loop off the real /tmp state.

    CLAUDE_CODE_SESSION_ID is set whenever this suite runs inside a live Claude
    session, so without this the handler tests would read and overwrite the
    RUNNING session's banner state — flaking on whatever turn it happened to be
    and corrupting a real session's notifications. Each test gets a fresh dir,
    so every test starts as a first sighting.
    """
    import aipass.hooks.apps.modules.cadence as cadence

    monkeypatch.setattr(cadence, "_GUARD_DIR", tmp_path_factory.mktemp("cadence"))
    monkeypatch.setattr(cadence, "_turn", None)
    monkeypatch.setattr(cadence, "_config", None)


class TestEmailHandler:
    """Core handler behavior tests."""

    def test_handle_returns_result_dict(self):
        from aipass.hooks.apps.handlers.notification.email import handle

        with patch(
            "aipass.hooks.apps.handlers.notification.email._find_branch_root",
            return_value=None,
        ):
            result = handle({})

        assert isinstance(result, dict)
        assert result["stdout"] == ""
        assert result["exit_code"] == 0

    def test_handle_returns_notification_when_new_emails(self, tmp_path):
        from aipass.hooks.apps.handlers.notification.email import handle

        inbox_dir = tmp_path / ".ai_mail.local"
        inbox_dir.mkdir()
        inbox_file = inbox_dir / "inbox.json"
        inbox_file.write_text(
            json.dumps({"messages": [{"status": "new", "subject": "test"}]}),
            encoding="utf-8",
        )

        with patch(
            "aipass.hooks.apps.handlers.notification.email._find_branch_root",
            return_value=tmp_path,
        ):
            result = handle({})

        assert "1 new email" in result["stdout"]
        assert "drone @ai_mail inbox" in result["stdout"]
        assert result["exit_code"] == 0

    def test_handle_sets_sound_when_new_emails(self, tmp_path):
        from aipass.hooks.apps.handlers.notification.email import handle

        inbox_dir = tmp_path / ".ai_mail.local"
        inbox_dir.mkdir()
        inbox_file = inbox_dir / "inbox.json"
        inbox_file.write_text(
            json.dumps({"messages": [{"status": "new", "subject": "test"}]}),
            encoding="utf-8",
        )

        with patch(
            "aipass.hooks.apps.handlers.notification.email._find_branch_root",
            return_value=tmp_path,
        ):
            result = handle({})

        assert result["sound"] == "email notification: 1 new email"

    def test_handle_no_sound_when_no_emails(self, tmp_path):
        from aipass.hooks.apps.handlers.notification.email import handle

        inbox_dir = tmp_path / ".ai_mail.local"
        inbox_dir.mkdir()
        inbox_file = inbox_dir / "inbox.json"
        inbox_file.write_text(
            json.dumps({"messages": [{"status": "read"}]}),
            encoding="utf-8",
        )

        with patch(
            "aipass.hooks.apps.handlers.notification.email._find_branch_root",
            return_value=tmp_path,
        ):
            result = handle({})

        assert result.get("sound", "") == ""

    def test_handle_returns_empty_when_no_new_emails(self, tmp_path):
        from aipass.hooks.apps.handlers.notification.email import handle

        inbox_dir = tmp_path / ".ai_mail.local"
        inbox_dir.mkdir()
        inbox_file = inbox_dir / "inbox.json"
        inbox_file.write_text(
            json.dumps({"messages": [{"status": "read", "subject": "old"}]}),
            encoding="utf-8",
        )

        with patch(
            "aipass.hooks.apps.handlers.notification.email._find_branch_root",
            return_value=tmp_path,
        ):
            result = handle({})

        assert result["stdout"] == ""
        assert result["exit_code"] == 0

    def test_handle_plural_for_multiple_emails(self, tmp_path):
        from aipass.hooks.apps.handlers.notification.email import handle

        inbox_dir = tmp_path / ".ai_mail.local"
        inbox_dir.mkdir()
        inbox_file = inbox_dir / "inbox.json"
        inbox_file.write_text(
            json.dumps(
                {
                    "messages": [
                        {"status": "new", "subject": "one"},
                        {"status": "new", "subject": "two"},
                        {"status": "new", "subject": "three"},
                    ]
                }
            ),
            encoding="utf-8",
        )

        with patch(
            "aipass.hooks.apps.handlers.notification.email._find_branch_root",
            return_value=tmp_path,
        ):
            result = handle({})

        assert "3 new emails" in result["stdout"]


class TestCountNewEmails:
    """Inbox counting logic tests."""

    def test_counts_new_status(self, tmp_path):
        from aipass.hooks.apps.handlers.notification.email import _count_new_emails

        inbox_dir = tmp_path / ".ai_mail.local"
        inbox_dir.mkdir()
        inbox_file = inbox_dir / "inbox.json"
        inbox_file.write_text(
            json.dumps(
                {
                    "messages": [
                        {"status": "new"},
                        {"status": "new"},
                        {"status": "read"},
                    ]
                }
            ),
            encoding="utf-8",
        )

        assert _count_new_emails(tmp_path) == 2

    def test_counts_unread_without_status(self, tmp_path):
        from aipass.hooks.apps.handlers.notification.email import _count_new_emails

        inbox_dir = tmp_path / ".ai_mail.local"
        inbox_dir.mkdir()
        inbox_file = inbox_dir / "inbox.json"
        inbox_file.write_text(
            json.dumps({"messages": [{"subject": "no status field"}]}),
            encoding="utf-8",
        )

        assert _count_new_emails(tmp_path) == 1

    def test_skips_read_messages(self, tmp_path):
        from aipass.hooks.apps.handlers.notification.email import _count_new_emails

        inbox_dir = tmp_path / ".ai_mail.local"
        inbox_dir.mkdir()
        inbox_file = inbox_dir / "inbox.json"
        inbox_file.write_text(
            json.dumps({"messages": [{"status": "read"}, {"read": True}]}),
            encoding="utf-8",
        )

        assert _count_new_emails(tmp_path) == 0

    def test_handles_bare_list_format(self, tmp_path):
        from aipass.hooks.apps.handlers.notification.email import _count_new_emails

        inbox_dir = tmp_path / ".ai_mail.local"
        inbox_dir.mkdir()
        inbox_file = inbox_dir / "inbox.json"
        inbox_file.write_text(
            json.dumps([{"status": "new"}, {"status": "read"}]),
            encoding="utf-8",
        )

        assert _count_new_emails(tmp_path) == 1

    def test_falls_back_to_legacy_path(self, tmp_path):
        from aipass.hooks.apps.handlers.notification.email import _count_new_emails

        inbox_dir = tmp_path / "ai_mail.local"
        inbox_dir.mkdir()
        inbox_file = inbox_dir / "inbox.json"
        inbox_file.write_text(
            json.dumps({"messages": [{"status": "new"}]}),
            encoding="utf-8",
        )

        assert _count_new_emails(tmp_path) == 1

    def test_returns_zero_when_no_inbox(self, tmp_path):
        from aipass.hooks.apps.handlers.notification.email import _count_new_emails

        assert _count_new_emails(tmp_path) == 0

    def test_returns_zero_on_corrupt_json(self, tmp_path):
        from aipass.hooks.apps.handlers.notification.email import _count_new_emails

        inbox_dir = tmp_path / ".ai_mail.local"
        inbox_dir.mkdir()
        inbox_file = inbox_dir / "inbox.json"
        inbox_file.write_text("not valid json{{{", encoding="utf-8")

        assert _count_new_emails(tmp_path) == 0


class TestFindBranchRoot:
    """Branch root discovery tests."""

    def test_finds_branch_with_trinity(self, tmp_path):
        from aipass.hooks.apps.handlers.notification.email import _find_branch_root

        trinity = tmp_path / ".trinity"
        trinity.mkdir()
        apps = tmp_path / "apps"
        apps.mkdir()

        with (
            patch(
                "aipass.hooks.apps.handlers.notification.email.Path.cwd",
                return_value=tmp_path,
            ),
            patch(
                "aipass.hooks.apps.handlers.notification.email._find_repo_root",
                return_value=tmp_path.parent,
            ),
        ):
            result = _find_branch_root()

        assert result == tmp_path

    def test_returns_none_when_no_markers(self):
        from aipass.hooks.apps.handlers.notification.email import _find_branch_root

        with (
            patch(
                "aipass.hooks.apps.handlers.notification.email.Path.cwd",
                return_value=Path("/tmp/bare"),
            ),
            patch(
                "aipass.hooks.apps.handlers.notification.email._find_repo_root",
                return_value=None,
            ),
        ):
            result = _find_branch_root()

        assert result is None

    def test_returns_none_at_repo_root(self, tmp_path):
        from aipass.hooks.apps.handlers.notification.email import _find_branch_root

        with (
            patch(
                "aipass.hooks.apps.handlers.notification.email.Path.cwd",
                return_value=tmp_path,
            ),
            patch(
                "aipass.hooks.apps.handlers.notification.email._find_repo_root",
                return_value=tmp_path,
            ),
        ):
            result = _find_branch_root()

        assert result is None


class TestEmailCadenceGate:
    """The banner rides the 5-turn cadence loop instead of firing every turn."""

    def _inbox(self, tmp_path, count):
        inbox_dir = tmp_path / ".ai_mail.local"
        inbox_dir.mkdir(exist_ok=True)
        (inbox_dir / "inbox.json").write_text(
            json.dumps({"messages": [{"status": "new", "subject": f"m{i}"} for i in range(count)]}),
            encoding="utf-8",
        )

    def test_banner_suppressed_when_cadence_says_no(self, tmp_path):
        from aipass.hooks.apps.handlers.notification.email import handle

        self._inbox(tmp_path, 3)
        with (
            patch(
                "aipass.hooks.apps.handlers.notification.email._find_branch_root",
                return_value=tmp_path,
            ),
            patch("aipass.hooks.apps.modules.cadence.should_fire_mail", return_value=False),
        ):
            result = handle({})

        assert result["stdout"] == ""
        assert "sound" not in result

    def test_banner_shown_when_cadence_says_yes(self, tmp_path):
        from aipass.hooks.apps.handlers.notification.email import handle

        self._inbox(tmp_path, 3)
        with (
            patch(
                "aipass.hooks.apps.handlers.notification.email._find_branch_root",
                return_value=tmp_path,
            ),
            patch("aipass.hooks.apps.modules.cadence.should_fire_mail", return_value=True),
        ):
            result = handle({})

        assert "3 new emails" in result["stdout"]

    def test_message_format_unchanged(self, tmp_path):
        """Patrick's spec keeps the wording: count + the three commands."""
        from aipass.hooks.apps.handlers.notification.email import handle

        self._inbox(tmp_path, 1)
        with patch(
            "aipass.hooks.apps.handlers.notification.email._find_branch_root",
            return_value=tmp_path,
        ):
            result = handle({})

        assert result["stdout"] == (
            "You have 1 new email - check with: drone @ai_mail inbox"
            " | then: drone @ai_mail view <id> | close with: drone @ai_mail close <id>"
        )

    def test_zero_mail_is_silent_and_never_asks_cadence_to_speak(self, tmp_path):
        from aipass.hooks.apps.handlers.notification.email import handle

        self._inbox(tmp_path, 0)
        with patch(
            "aipass.hooks.apps.handlers.notification.email._find_branch_root",
            return_value=tmp_path,
        ):
            result = handle({})

        assert result["stdout"] == ""

    def test_zero_count_still_reaches_cadence_to_clear_state(self, tmp_path):
        """The handler must NOT short-circuit at zero — an empty inbox is the signal
        that resets the loop so the next arrival announces on its own turn."""
        from aipass.hooks.apps.handlers.notification.email import handle

        self._inbox(tmp_path, 0)
        with (
            patch(
                "aipass.hooks.apps.handlers.notification.email._find_branch_root",
                return_value=tmp_path,
            ),
            patch("aipass.hooks.apps.modules.cadence.should_fire_mail", return_value=False) as mock_fire,
        ):
            handle({})

        mock_fire.assert_called_once()
        assert mock_fire.call_args[0][0] == 0

    def test_cadence_failure_fails_open(self, tmp_path):
        """A broken cadence must not be able to silently hide someone's mail."""
        from aipass.hooks.apps.handlers.notification.email import handle

        self._inbox(tmp_path, 2)
        with (
            patch(
                "aipass.hooks.apps.handlers.notification.email._find_branch_root",
                return_value=tmp_path,
            ),
            patch(
                "aipass.hooks.apps.modules.cadence.should_fire_mail",
                side_effect=RuntimeError("state file exploded"),
            ),
        ):
            result = handle({})

        assert "2 new emails" in result["stdout"]

    def test_cadence_failure_at_zero_stays_silent(self, tmp_path):
        """Failing open means 'show real mail', not 'invent a banner for none'."""
        from aipass.hooks.apps.handlers.notification.email import handle

        self._inbox(tmp_path, 0)
        with (
            patch(
                "aipass.hooks.apps.handlers.notification.email._find_branch_root",
                return_value=tmp_path,
            ),
            patch(
                "aipass.hooks.apps.modules.cadence.should_fire_mail",
                side_effect=RuntimeError("state file exploded"),
            ),
        ):
            result = handle({})

        assert result["stdout"] == ""
