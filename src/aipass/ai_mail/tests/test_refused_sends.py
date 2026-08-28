# =================== AIPass ====================
# Name: test_refused_sends.py
# Description: Tests for refused-send bookkeeping and the handled-vs-worked routing contract
# Version: 1.0.0
# Created: 2026-08-12
# Modified: 2026-08-12
# =============================================

"""Tests for refused sends (FPLAN-0400 items B + C).

Two failures, one surface, both found live by @baud sending from
projects/baud into the AIPass repo:

B — the cross-project fence refused the send and the sent record still read
    ``status: "sent"``. The sender took "it's in my sent folder" as proof of
    delivery and had no way to learn the message never went.

C — the refusal printed twice, then "Unknown command: email". The send was
    genuinely running twice: email_send.handle_command ignored its ``command``
    argument, so every command an earlier module declined — including a send
    that module had already run and reported as failed — was executed again
    here. Returning False for "ran and failed" is what sent the router on.

The contract these pin: a handler returns True for "I recognised and ran this
command", never for "it worked". Failure is reported through error(), which
sets the process failure flag main() maps to exit 2.
"""

import json

import pytest
from unittest.mock import MagicMock, patch

from aipass.ai_mail.apps.handlers.email.create import (
    create_email_file,
    mark_sent_record_refused,
)
from aipass.ai_mail.apps.handlers.email.format import format_email_list_item
from aipass.ai_mail.apps.handlers.email.send import send_to_single, send_to_broadcast


# ---- Fixtures ------------------------------------------------------------


@pytest.fixture(autouse=True)
def _silence_send_json_handler():
    """Prevent log_operation from writing real JSON files during tests."""
    with patch("aipass.ai_mail.apps.handlers.email.send.json_handler") as mock_jh:
        mock_jh.log_operation.return_value = True
        yield mock_jh


@pytest.fixture(autouse=True)
def _silence_create_json_handler():
    """Prevent create.py's log_operation from writing real JSON files."""
    with patch("aipass.ai_mail.apps.handlers.email.create.json_handler") as mock_jh:
        mock_jh.log_operation.return_value = True
        yield mock_jh


def _user_info(tmp_path) -> dict:
    """Build a user_info dict whose mailbox lives under tmp_path."""
    return {
        "email_address": "@baud",
        "display_name": "BAUD",
        "mailbox_path": str(tmp_path / ".ai_mail.local"),
        "timestamp_format": "%Y-%m-%d %H:%M:%S",
    }


def _read(email_file) -> dict:
    """Load a sent record from disk."""
    with open(email_file, "r", encoding="utf-8") as f:
        return json.load(f)


REFUSAL = "Cross-project mail refused: @baud (project: baud) cannot send to this branch (project: AIPass)."


# ===========================================================================
# Item B — mark_sent_record_refused
# ===========================================================================


class TestMarkSentRecordRefused:
    """Tests for the sent-record restamp itself."""

    def test_restamps_status_reason_and_time(self, tmp_path):
        """A refused record carries status, reason and a refusal timestamp."""
        email_file = create_email_file("@ai_mail", "Subj", "Body", _user_info(tmp_path))

        assert _read(email_file)["status"] == "sent"
        assert mark_sent_record_refused(email_file, REFUSAL) is True

        record = _read(email_file)
        assert record["status"] == "refused"
        assert record["refused_reason"] == REFUSAL
        assert record["refused_at"]

    def test_preserves_the_rest_of_the_record(self, tmp_path):
        """Restamping keeps id, addresses, subject and body intact.

        The attempt is evidence — a sender who saw an error must still be able
        to cite exactly what they tried to send, and to whom.
        """
        email_file = create_email_file("@ai_mail", "Subj", "Body", _user_info(tmp_path))
        before = _read(email_file)

        mark_sent_record_refused(email_file, REFUSAL)
        after = _read(email_file)

        assert after["id"] == before["id"]
        assert after["from"] == "@baud"
        assert after["to"] == "@ai_mail"
        assert after["subject"] == "Subj"
        assert after["message"] == before["message"]
        assert after["timestamp"] == before["timestamp"]

    def test_missing_file_returns_false_without_raising(self, tmp_path):
        """A record that is not there fails honestly, it does not crash the send."""
        assert mark_sent_record_refused(tmp_path / "nope.json", REFUSAL) is False

    def test_unreadable_record_returns_false_without_raising(self, tmp_path):
        """Corrupt JSON fails honestly rather than taking the send down."""
        broken = tmp_path / "broken.json"
        broken.write_text("{not json", encoding="utf-8")

        assert mark_sent_record_refused(broken, REFUSAL) is False


# ===========================================================================
# Item B — send_to_single / send_to_broadcast bookkeeping
# ===========================================================================


class TestSendToSingleRefusedBookkeeping:
    """A refused single send must not leave a delivered-looking record."""

    def _send(self, tmp_path, deliver_result):
        """Run send_to_single against the real create/load handlers."""
        from aipass.ai_mail.apps.handlers.email.create import load_email_file

        created = {}

        def _create(*args, **kwargs):
            """Capture the sent record path so the test can read it back."""
            created["path"] = create_email_file(*args, **kwargs)
            return created["path"]

        success, error_msg = send_to_single(
            to_branch="@ai_mail",
            subject="Subj",
            message="Body",
            user_info=_user_info(tmp_path),
            auto_execute=False,
            no_memory_save=False,
            reply_to=None,
            dispatched_to=None,
            create_email_file_fn=_create,
            load_email_file_fn=load_email_file,
            deliver_email_to_branch_fn=MagicMock(return_value=deliver_result),
            on_delivered_callback=MagicMock(),
            log_operation_fn=MagicMock(),
            update_central_fn=MagicMock(),
        )
        return success, error_msg, created["path"]

    def test_refused_delivery_marks_the_record_refused(self, tmp_path):
        """The fence refused, so the sent record says refused — not sent."""
        success, error_msg, path = self._send(tmp_path, (False, REFUSAL))

        assert success is False
        assert error_msg == REFUSAL

        record = _read(path)
        assert record["status"] == "refused"
        assert record["refused_reason"] == REFUSAL

    def test_successful_delivery_leaves_the_record_sent(self, tmp_path):
        """A delivered message keeps status sent and gains no refusal fields."""
        success, _, path = self._send(tmp_path, (True, ""))

        assert success is True
        record = _read(path)
        assert record["status"] == "sent"
        assert "refused_reason" not in record
        assert "refused_at" not in record

    def test_empty_error_message_still_records_a_reason(self, tmp_path):
        """A refusal with no message still records why, not an empty string."""
        _, _, path = self._send(tmp_path, (False, ""))

        assert _read(path)["refused_reason"] == "delivery refused"


class TestSendToBroadcastRefusedBookkeeping:
    """One broadcast record covers N recipients — zero delivered is refused."""

    def _broadcast(self, tmp_path, deliver_results):
        """Run send_to_broadcast with a per-recipient delivery result queue."""
        from aipass.ai_mail.apps.handlers.email.create import load_email_file

        created = {}

        def _create(*args, **kwargs):
            """Capture the sent record path so the test can read it back."""
            created["path"] = create_email_file(*args, **kwargs)
            return created["path"]

        branches = [{"name": f"B{i}", "email": f"@b{i}"} for i in range(len(deliver_results))]
        queue = list(deliver_results)

        def _deliver(email, data, on_delivered=None):
            """Return the next queued delivery outcome."""
            return queue.pop(0)

        ok, success_count, total, results = send_to_broadcast(
            subject="Subj",
            message="Body",
            user_info=_user_info(tmp_path),
            auto_execute=False,
            no_memory_save=False,
            reply_to=None,
            dispatched_to=None,
            branches=branches,
            create_email_file_fn=_create,
            load_email_file_fn=load_email_file,
            deliver_email_to_branch_fn=_deliver,
            log_operation_fn=MagicMock(),
            update_central_fn=MagicMock(),
        )
        return ok, success_count, total, results, created["path"]

    def test_every_recipient_refused_marks_the_record_refused(self, tmp_path):
        """Zero delivered means the record must not claim a delivery."""
        ok, success_count, _, _, path = self._broadcast(tmp_path, [(False, REFUSAL), (False, REFUSAL)])

        assert ok is False
        assert success_count == 0

        record = _read(path)
        assert record["status"] == "refused"
        assert record["refused_reason"] == REFUSAL

    def test_partial_delivery_leaves_the_record_sent(self, tmp_path):
        """One recipient accepted it, so the record is a real send."""
        ok, success_count, _, _, path = self._broadcast(tmp_path, [(False, REFUSAL), (True, "")])

        assert ok is True
        assert success_count == 1
        assert _read(path)["status"] == "sent"


# ===========================================================================
# Item B — the refused record has to be visible
# ===========================================================================


class TestRefusedRecordIsVisible:
    """A refused record nobody can see is the same failure wearing a hat."""

    def test_sent_row_marks_a_refused_record(self):
        """The listing row says REFUSED and states the reason."""
        row = format_email_list_item(
            1,
            {
                "id": "abc12345",
                "to": "@ai_mail",
                "timestamp": "2026-08-12 01:19:28",
                "subject": "Subj",
                "message": "Body",
                "status": "refused",
                "refused_reason": REFUSAL,
            },
            show_unread=False,
        )

        assert "REFUSED" in row
        assert "Not delivered:" in row
        assert "Cross-project mail refused" in row

    def test_sent_row_of_a_delivered_record_is_unmarked(self):
        """A delivered record must not pick up a refusal marker."""
        row = format_email_list_item(
            1,
            {
                "id": "abc12345",
                "to": "@ai_mail",
                "timestamp": "2026-08-12 01:19:28",
                "subject": "Subj",
                "message": "Body",
                "status": "sent",
            },
            show_unread=False,
        )

        assert "REFUSED" not in row
        assert "Not delivered:" not in row

    def test_refused_record_missing_a_reason_still_says_so(self):
        """A refused row never renders a blank explanation."""
        row = format_email_list_item(
            1,
            {"id": "abc12345", "to": "@ai_mail", "subject": "Subj", "status": "refused"},
            show_unread=False,
        )

        assert "REFUSED" in row
        assert "no reason recorded" in row

    def test_sent_listing_orders_by_mtime_not_filename(self, tmp_path, monkeypatch):
        """The newest send tops the listing whichever naming scheme wrote it.

        create.py writes "<YYYYMMDD_HHMMSS>_<subject>.json" and reply.py writes
        "<id>.json". In a filename sort every hex id outranks every digit, so a
        mailbox holding 20 replies hid every recent send behind them — including
        the refused records this listing exists to surface.
        """
        import aipass.ai_mail.apps.modules.email as email_mod

        sent = tmp_path / ".ai_mail.local" / "sent"
        sent.mkdir(parents=True)

        old = sent / "ffffffff.json"
        old.write_text(json.dumps({"id": "ffffffff", "to": "@x", "subject": "OLD REPLY"}), encoding="utf-8")
        new = sent / "20260812_011928_refused.json"
        new.write_text(
            json.dumps({"id": "11111111", "to": "@y", "subject": "NEW REFUSAL", "status": "refused"}),
            encoding="utf-8",
        )
        import os

        os.utime(old, (1_000_000, 1_000_000))
        os.utime(new, (2_000_000, 2_000_000))

        printed: list[str] = []
        mock_console = MagicMock()
        mock_console.print = lambda msg="", **kw: printed.append(str(msg))
        monkeypatch.setattr(email_mod, "console", mock_console)
        monkeypatch.setattr(email_mod, "_resolve_branch_path", lambda: tmp_path)

        assert email_mod.handle_sent([]) is True

        body = "\n".join(printed)
        assert body.index("NEW REFUSAL") < body.index("OLD REPLY")


# ===========================================================================
# Item C — one command, one send
# ===========================================================================


class TestEmailSendClaimsOnlyItsOwnCommands:
    """The double send: handle_command used to ignore `command` entirely."""

    @pytest.mark.parametrize("command", ["dispatch", "inbox", "view", "close", "reply", "sent", "contacts"])
    def test_foreign_command_is_declined_without_sending(self, command, monkeypatch):
        """A command this module does not own must not run a send.

        This is the canary for the doubled refusal: `dispatch` reached here
        after dispatch.py had already run and reported it, and a second send
        went out under a command name this module never owned.
        """
        import aipass.ai_mail.apps.modules.email_send as send_mod

        sends: list[list] = []
        monkeypatch.setattr(send_mod, "handle_send", lambda args: sends.append(args))

        assert send_mod.handle_command(command, ["@target", "Subject", "Body"]) is False
        assert sends == []

    @pytest.mark.parametrize("command", ["send", "email"])
    def test_owned_command_routes_to_handle_send(self, command, monkeypatch):
        """send and email are this module's own — they route through."""
        import aipass.ai_mail.apps.modules.email_send as send_mod

        sends: list[list] = []
        monkeypatch.setattr(send_mod, "handle_send", lambda args: sends.append(args) or True)

        assert send_mod.handle_command(command, ["@target", "Subject", "Body"]) is True
        assert sends == [["@target", "Subject", "Body"]]

    def test_foreign_command_with_no_args_does_not_swallow_it(self, monkeypatch):
        """A bare `inbox` must reach the inbox module, not print introspection.

        The no-args branch ran before any command check, so whichever module
        the filesystem happened to hand the router first could answer `inbox`
        with this module's introspection and return True.
        """
        import aipass.ai_mail.apps.modules.email_send as send_mod

        intros: list[int] = []
        monkeypatch.setattr(send_mod, "print_introspection", lambda: intros.append(1))

        assert send_mod.handle_command("inbox", []) is False
        assert intros == []


class TestRecognisedButFailedStaysHandled:
    """Handled means recognised and run — never "it worked"."""

    def test_router_stops_at_the_first_module_that_ran_a_failed_send(self):
        """A failed send is not retried by the next module in the chain.

        route_command walks modules until one returns True. When a failing send
        returned False the walk continued, the next module ran the same send
        again, and the router then declared the command unknown.
        """
        from aipass.ai_mail.apps.ai_mail import route_command

        first = MagicMock()
        first.handle_command = MagicMock(return_value=True)
        second = MagicMock()
        second.handle_command = MagicMock(return_value=True)

        assert route_command("email", ["@target", "S", "B"], [first, second]) is True
        first.handle_command.assert_called_once()
        second.handle_command.assert_not_called()

    def test_exit_code_is_two_for_a_handled_failure(self):
        """A refused send exits 2 (routed but failed), not 1 (unroutable)."""
        from aipass.cli.apps.modules import error, reset_command_state, resolve_exit

        reset_command_state()
        error("Failed to deliver: refused")
        assert resolve_exit(True) == 2
        reset_command_state()
