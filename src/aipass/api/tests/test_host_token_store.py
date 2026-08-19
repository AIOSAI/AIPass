#!/usr/bin/env python3
# =================== AIPass ====================
# Name: test_host_token_store.py
# Description: Tests for token provenance, revocation time and live/dormant telemetry
# Version: 1.0.0
# Created: 2026-08-14
# Modified: 2026-08-14
# =============================================

"""
Tests for the Token Store's Accountability Fields

Devpulse's ruling, granted 2026-08-14 after an operate-scoped token appeared on
this machine and the store could not say who minted it. Three fields:

  minted_by   - best-effort provenance. WHO ran issue-token.
  revoked_at  - when a token stopped working.
  last_used   - whether a live token is actually live, or merely un-revoked.

THE HAZARD THESE TESTS EXIST FOR, and it is not the fields.

`last_used` means a write on EVERY authenticated request, against a JSON file
that issue and revoke also write. Two things could go wrong, and the second one
is the dangerous one:

  1. Two writers race and one update is lost. For telemetry, survivable.
  2. A telemetry write, holding a record list it read BEFORE a revoke landed,
     writes that stale list back — and un-revokes the token. A revoked device
     starts working again because somebody looked at a timestamp.

So the load-bearing test in this file is not "last_used is written". It is
"a concurrent revoke survives a touch". Telemetry must never undo security.

And one more: a truncated store reads as empty, which denies every request. With
per-request writes that window stops being theoretical, so the write is atomic —
a reader sees the old file or the new one, never half of either.
"""

import json
import os
import sys
import threading
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from aipass.api.apps.handlers.host import tokens as host_tokens
from aipass.api.apps.modules import host_api as host_api_module

PATCH_SECRETS_BASE = "aipass.api.apps.handlers.auth.secrets.SECRETS_BASE"
PATCH_SECRETS_JSON = "aipass.api.apps.handlers.auth.secrets.json_handler"
PATCH_SECRETS_LOGGER = "aipass.api.apps.handlers.auth.secrets.logger"
PATCH_TOKENS_JSON = "aipass.api.apps.handlers.host.tokens.json_handler"
PATCH_TOKENS_LOGGER = "aipass.api.apps.handlers.host.tokens.logger"

CALLER_ENV = "AIPASS_CALLER_BRANCH"


@pytest.fixture
def store(tmp_path: Path):
    """Redirect the secrets store to a temp dir for the whole test."""
    with patch(PATCH_SECRETS_BASE, tmp_path), patch(PATCH_SECRETS_JSON), patch(PATCH_SECRETS_LOGGER):
        with patch(PATCH_TOKENS_JSON), patch(PATCH_TOKENS_LOGGER):
            yield tmp_path


@pytest.fixture
def minted_by_baud(store: Path):
    """A store where drone has named the calling branch, as it does in practice."""
    with patch.dict(os.environ, {CALLER_ENV: "baud"}):
        yield store


def _record(token_id: str) -> dict:
    """The stored record for an id, hash and all."""
    return next(record for record in host_tokens.load_tokens() if record.get("id") == token_id)


# ==============================================
# PROVENANCE
# ==============================================


class TestTheStoreRemembersWhoMintedIt:
    """
    The gap that cost an investigation round tonight.

    An operate-scoped token appeared, and the honest answer to "who minted this"
    was that the store does not record it. The C1 audit knows precisely who
    FAILS auth; nothing knew who ISSUES.
    """

    def test_the_calling_branch_is_recorded(self, minted_by_baud: Path) -> None:
        """drone names the caller in the child env; this reads it."""
        record, _ = host_tokens.issue_token("phase6-verify", scope="operate")

        assert record["minted_by"] == "baud"

    def test_an_unnamed_caller_is_recorded_as_unknown(self, store: Path) -> None:
        """
        'unknown' rather than a blank or a missing key.

        A field that vanishes when it has nothing to say reads as though nobody
        thought to record it — the same reasoning as the audit's peer address.
        """
        with patch.dict(os.environ, {}, clear=True):
            record, _ = host_tokens.issue_token("hand-rolled", scope="read")

        assert record["minted_by"] == "unknown"

    def test_the_minter_reaches_the_listing(self, minted_by_baud: Path) -> None:
        """A provenance field nobody can read is a field that does not exist."""
        record, _ = host_tokens.issue_token("phase6-verify", scope="operate")

        listed = next(row for row in host_tokens.list_tokens() if row["id"] == record["id"])
        assert listed["minted_by"] == "baud"

    def test_the_minter_is_provenance_and_never_permission(self, store: Path) -> None:
        """
        It records what happened; it never decides what is allowed.

        The value comes from an environment variable the caller's own process
        carries, so trusting it for authorisation would be trusting the caller
        about the caller. Any value issues a token; the value only names it.
        """
        with patch.dict(os.environ, {CALLER_ENV: "definitely-not-a-real-branch"}):
            record, raw = host_tokens.issue_token("odd-caller", scope="operate")

        assert record["minted_by"] == "definitely-not-a-real-branch"
        assert host_tokens.verify_token(raw) is not None

    def test_current_minter_never_raises_on_a_bare_environment(self, store: Path) -> None:
        """
        Best-effort means it answers under every environment, including none.

        Provenance that can throw would turn a bookkeeping field into a reason
        a token cannot be minted. Called directly here, because the callers
        above would hide a raise behind issue_token's own failure.
        """
        with patch.dict(os.environ, {}, clear=True):
            assert host_tokens.current_minter() == host_tokens.UNKNOWN_MINTER

        with patch.dict(os.environ, {CALLER_ENV: "   "}):
            assert host_tokens.current_minter() == host_tokens.UNKNOWN_MINTER

        with patch.dict(os.environ, {CALLER_ENV: "  baud  "}):
            assert host_tokens.current_minter() == "baud"


# ==============================================
# REVOCATION TIME
# ==============================================


class TestRevokedAtWasStoredButNotSurfaced:
    """
    My own correction. I reported `revoked_at` as a missing field; it has been
    written since Phase 1 and was simply not projected by list_tokens().

    I read the projection and called it the store. The fix is one line, and the
    lesson is worth more than the line: check the record, not the view of it.
    """

    def test_revocation_stamps_the_time(self, store: Path) -> None:
        """Written at revoke, as it always was."""
        record, _ = host_tokens.issue_token("pixel-8", scope="read")

        host_tokens.revoke_token(record["id"])

        assert _record(record["id"])["revoked_at"]

    def test_the_stamp_reaches_the_listing(self, store: Path) -> None:
        """The part that was actually missing."""
        record, _ = host_tokens.issue_token("pixel-8", scope="read")
        host_tokens.revoke_token(record["id"])

        listed = next(row for row in host_tokens.list_tokens() if row["id"] == record["id"])
        assert listed["revoked_at"]

    def test_a_live_token_carries_no_revocation_time(self, store: Path) -> None:
        """None, not a placeholder date — an unrevoked token was never revoked."""
        record, _ = host_tokens.issue_token("pixel-8", scope="read")

        listed = next(row for row in host_tokens.list_tokens() if row["id"] == record["id"])
        assert listed["revoked_at"] is None


# ==============================================
# LIVE OR DORMANT
# ==============================================


class TestLastUsedAnswersLiveOrDormant:
    """
    The question this field exists for is not 'when exactly', it is 'is this
    credential still in use, or has it been sitting there since March'.

    So writes coalesce inside a window. A phone polling the feed every few
    seconds would otherwise rewrite the whole store every few seconds, for a
    field nobody reads at second resolution.
    """

    def test_a_touch_records_the_time(self, store: Path) -> None:
        """The basic claim."""
        record, _ = host_tokens.issue_token("pixel-8", scope="read")

        host_tokens.touch_token(record["id"])

        assert _record(record["id"])["last_used"]

    def test_the_touch_reaches_the_listing(self, store: Path) -> None:
        """An operator asking 'is this one dormant' reads the listing."""
        record, _ = host_tokens.issue_token("pixel-8", scope="read")
        host_tokens.touch_token(record["id"])

        listed = next(row for row in host_tokens.list_tokens() if row["id"] == record["id"])
        assert listed["last_used"]

    def test_a_second_touch_inside_the_window_does_not_rewrite(self, store: Path) -> None:
        """Coalesced. The store is not rewritten once per feed poll."""
        record, _ = host_tokens.issue_token("pixel-8", scope="read")
        host_tokens.touch_token(record["id"])
        first = _record(record["id"])["last_used"]

        host_tokens.touch_token(record["id"])

        assert _record(record["id"])["last_used"] == first

    def test_a_touch_after_the_window_rewrites(self, store: Path) -> None:
        """Coalescing must not become never-updating."""
        record, _ = host_tokens.issue_token("pixel-8", scope="read")
        host_tokens.touch_token(record["id"])
        first = _record(record["id"])["last_used"]

        with patch.object(host_tokens, "LAST_USED_GRANULARITY_SECONDS", 0):
            host_tokens.touch_token(record["id"])

        assert _record(record["id"])["last_used"] != first

    def test_touching_an_unknown_id_changes_nothing(self, store: Path) -> None:
        """No record created, no error raised."""
        host_tokens.issue_token("pixel-8", scope="read")
        before = host_tokens.load_tokens()

        host_tokens.touch_token("not-a-real-id")

        assert host_tokens.load_tokens() == before


class TestTelemetryNeverUndoesSecurity:
    """
    The load-bearing class in this file.

    `touch_token` is a read-modify-write on the same file `revoke_token` writes.
    Done carelessly it would let a timestamp update resurrect a revoked device —
    a security property destroyed by a telemetry field. The whole reason the
    Phase 1 reservation said 'not until there is locking'.
    """

    def test_the_touch_reads_inside_the_lock_not_before_it(self, store: Path) -> None:
        """
        The property that makes a concurrent revoke safe, pinned directly.

        A read taken before the lock could be stale by the time it is written
        back — that is the whole resurrection bug. Holding the lock across BOTH
        the read and the write is what removes the window, so this asserts the
        ordering rather than trying to hand-simulate a race.

        My first attempt at this test forced the revoke re-entrantly from inside
        the touch's own read, which deadlocked against a lock that is correctly
        not re-entrant, and then reported the code broken. The harness was wrong;
        the ordering is the thing worth pinning.
        """
        record, _ = host_tokens.issue_token("pixel-8", scope="read")
        real_load = host_tokens.load_tokens
        held_during_read = []

        def watching_load() -> list:
            held_during_read.append(host_tokens.lock_path().exists())
            return real_load()

        host_tokens.load_tokens = watching_load
        try:
            host_tokens.touch_token(record["id"])
        finally:
            host_tokens.load_tokens = real_load

        assert held_during_read == [True]

    def test_a_revoke_racing_a_touch_across_threads_still_wins(self, store: Path) -> None:
        """
        Real threads, real lock, the outcome that matters.

        Whichever order they serialise in, the token must end up revoked: the
        touch re-reads under the lock, so it can never write back a list that
        predates the revoke.
        """
        record, raw = host_tokens.issue_token("pixel-8", scope="read")
        token_id = record["id"]
        barrier = threading.Barrier(2)

        def revoke() -> None:
            barrier.wait()
            host_tokens.revoke_token(token_id)

        def touch() -> None:
            barrier.wait()
            host_tokens.touch_token(token_id)

        threads = [threading.Thread(target=revoke), threading.Thread(target=touch)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        assert _record(token_id)["revoked"] is True
        assert host_tokens.verify_token(raw) is None

    def test_touching_a_revoked_token_does_not_revive_it(self, store: Path) -> None:
        """The simple form of the same rule."""
        record, raw = host_tokens.issue_token("pixel-8", scope="read")
        host_tokens.revoke_token(record["id"])

        host_tokens.touch_token(record["id"])

        assert host_tokens.verify_token(raw) is None

    def test_a_touch_that_cannot_take_the_lock_is_dropped_not_raised(self, store: Path) -> None:
        """
        Telemetry never fails a request.

        If the store is busy, the honest outcome is a missing timestamp — never
        a 500 on a request that was properly authenticated.
        """
        record, _ = host_tokens.issue_token("pixel-8", scope="read")

        with patch.object(host_tokens, "_store_lock", side_effect=OSError("lock is held")):
            host_tokens.touch_token(record["id"])

        assert _record(record["id"])["last_used"] is None


# ==============================================
# THE WRITE ITSELF
# ==============================================


class TestTheStoreIsNeverSeenHalfWritten:
    """
    A truncated store reads as empty, and an empty store denies every request.

    That window existed before tonight but was crossed rarely, by an operator
    running a command. Writing on every authenticated request makes it a
    constant, so the write became atomic: a reader sees the old file or the new
    one, never part of either.
    """

    def test_the_store_is_valid_json_after_a_write(self, store: Path) -> None:
        """The property, stated at its simplest."""
        host_tokens.issue_token("pixel-8", scope="read")

        path = store / "host_api" / "tokens.json"
        assert json.loads(path.read_text(encoding="utf-8"))["tokens"]

    def test_no_temporary_file_is_left_behind(self, store: Path) -> None:
        """An atomic write that litters is an atomic write nobody keeps."""
        host_tokens.issue_token("pixel-8", scope="read")

        leftovers = [item.name for item in (store / "host_api").iterdir() if item.name != "tokens.json"]
        assert leftovers == []

    @pytest.mark.skipif(
        sys.platform == "win32",
        reason="0o600 is a POSIX mode; Windows st_mode carries no owner-only story to assert",
    )
    def test_the_store_file_stays_owner_only(self, store: Path) -> None:
        """
        0o600 survives the rename.

        A temp file created with default permissions and then renamed into place
        would quietly widen a credential store — the atomicity fix undoing the
        permission discipline it was added to protect.
        """
        host_tokens.issue_token("pixel-8", scope="read")

        path = store / "host_api" / "tokens.json"
        assert (path.stat().st_mode & 0o777) == 0o600

    def test_the_version_is_bumped_for_the_new_fields(self, store: Path) -> None:
        """A reader must be able to tell which shape it is holding."""
        host_tokens.issue_token("pixel-8", scope="read")

        path = store / "host_api" / "tokens.json"
        assert json.loads(path.read_text(encoding="utf-8"))["version"] == host_tokens.STORE_VERSION
        assert host_tokens.STORE_VERSION >= 2


class TestOlderRecordsStillWork:
    """
    Version 1 records exist on this machine right now — every token minted
    today. They must keep verifying, listing and revoking with the fields they
    do not have.
    """

    def test_a_version_one_record_still_verifies(self, store: Path) -> None:
        """No minted_by, no revoked_at. Still a valid credential."""
        record, raw = host_tokens.issue_token("legacy", scope="read")
        records = host_tokens.load_tokens()
        for stored in records:
            stored.pop("minted_by", None)
        host_tokens.save_tokens(records)

        assert host_tokens.verify_token(raw) is not None

    def test_a_version_one_record_lists_without_inventing_a_minter(self, store: Path) -> None:
        """
        Absent is not 'unknown' here — it is honestly absent.

        A record minted before the field existed cannot claim its minter was
        unknown; nobody was ever asked. None says that; "unknown" would not.
        """
        record, _ = host_tokens.issue_token("legacy", scope="read")
        records = host_tokens.load_tokens()
        for stored in records:
            stored.pop("minted_by", None)
        host_tokens.save_tokens(records)

        listed = next(row for row in host_tokens.list_tokens() if row["id"] == record["id"])
        assert listed["minted_by"] is None


# ==============================================
# THE REQUEST PATH
# ==============================================


class TestTheServerTouchesOnEveryAuthenticatedRequest:
    """Wiring: the field is worthless if nothing writes it."""

    def test_a_successful_verification_touches_the_token(self, store: Path) -> None:
        """Where 'last_used' actually comes from."""
        from aipass.api.apps.handlers.host import server as host_server

        if not host_server.is_available():
            pytest.skip("the [host] extra is not installed")

        from fastapi.testclient import TestClient

        record, raw = host_tokens.issue_token("pixel-8", scope="read")

        with patch("aipass.api.apps.handlers.host.server.logger"):
            with patch("aipass.api.apps.handlers.host.server.json_handler"):
                with patch("aipass.api.apps.handlers.host.face.json_handler"):
                    with patch("aipass.api.apps.handlers.host.face.logger"):
                        client = TestClient(host_server.create_app(), raise_server_exceptions=False)
                        client.get("/v1/whoami", headers={"Authorization": f"Bearer {raw}"})

        assert _record(record["id"])["last_used"]

    def test_a_refused_request_touches_nothing(self, store: Path) -> None:
        """A rejected token was not used — it was presented and refused."""
        from aipass.api.apps.handlers.host import server as host_server

        if not host_server.is_available():
            pytest.skip("the [host] extra is not installed")

        from fastapi.testclient import TestClient

        record, _ = host_tokens.issue_token("pixel-8", scope="read")

        with patch("aipass.api.apps.handlers.host.server.logger"):
            with patch("aipass.api.apps.handlers.host.server.json_handler"):
                with patch("aipass.api.apps.handlers.host.face.json_handler"):
                    with patch("aipass.api.apps.handlers.host.face.logger"):
                        client = TestClient(host_server.create_app(), raise_server_exceptions=False)
                        client.get("/v1/whoami", headers={"Authorization": "Bearer wrong"})

        assert _record(record["id"])["last_used"] is None


class TestTheTouchIsNotAnOracle:
    """
    `last_used` is written only for a token that verified, so the file never
    grows a record for a value somebody guessed.
    """

    def test_an_unrecognised_token_creates_no_record(self, store: Path) -> None:
        """Probing must not populate the store it is probing."""
        host_tokens.issue_token("pixel-8", scope="read")
        before = len(host_tokens.load_tokens())

        host_tokens.verify_token("not-a-real-token")

        assert len(host_tokens.load_tokens()) == before


class TestTheLockIsRealNotDecorative:
    """A lock that never blocks anything is a comment with a syscall in it."""

    def test_a_writer_takes_the_lock(self, store: Path) -> None:
        """Issue goes through the same gate as everything else that writes."""
        with patch.object(host_tokens, "_store_lock") as lock:
            lock.return_value.__enter__ = lambda _: None
            lock.return_value.__exit__ = lambda *_: False

            host_tokens.issue_token("pixel-8", scope="read")

            assert lock.called

    def test_a_stale_lock_does_not_wedge_the_store_forever(self, store: Path) -> None:
        """
        A process that dies holding the lock must not lock out its successors.

        Bounded staleness beats a permanent outage: the worst case for breaking
        a stale lock is a lost timestamp, and the worst case for honouring one
        forever is a server that can never issue or revoke again.
        """
        lock_path = host_tokens.lock_path()
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path.write_text("dead pid", encoding="utf-8")
        os.utime(lock_path, (0, 0))

        record, _ = host_tokens.issue_token("pixel-8", scope="read")

        assert _record(record["id"])["id"] == record["id"]

    def test_the_lock_file_is_removed_after_a_write(self, store: Path) -> None:
        """Otherwise the first write wedges every write after it."""
        host_tokens.issue_token("pixel-8", scope="read")

        assert not host_tokens.lock_path().exists()

    def test_the_lock_guards_the_store_it_names(self, store: Path) -> None:
        """
        Both paths, side by side — a lock beside a DIFFERENT file guards nothing.

        store_path() is the single place that names the store, so issue, revoke
        and touch cannot drift onto separate files; this asserts the lock is a
        sibling of it rather than an unrelated path that merely exists.
        """
        assert host_tokens.store_path().parent == host_tokens.lock_path().parent
        assert host_tokens.store_path() != host_tokens.lock_path()

        host_tokens.issue_token("pixel-8", scope="read")

        assert host_tokens.store_path().exists()
        assert json.loads(host_tokens.store_path().read_text(encoding="utf-8"))["tokens"]


class TestTheLockSurvivesAFailedWrite(object):
    """A raised exception mid-write must not leave the lock held."""

    def test_a_failing_save_still_releases_the_lock(self, store: Path) -> None:
        """The finally clause, pinned — this is how a store wedges itself."""
        with patch.object(host_tokens, "save_tokens", side_effect=OSError("disk full")):
            with pytest.raises(OSError):
                host_tokens.issue_token("pixel-8", scope="read")

        assert not host_tokens.lock_path().exists()


class TestTheListingSaysWhatTheStoreNowKnows:
    """
    The operator's actual window onto all three fields.

    The ruling came from a question asked at a terminal — an operate token had
    appeared and nobody could say who minted it. Storing the answer in JSON and
    leaving the listing unchanged would have left that question exactly as
    unanswerable at the place it gets asked.
    """

    def _lines(self, printer: Any) -> str:
        """Everything the listing printed, as one searchable blob."""
        return "\n".join(str(call.args[0]) if call.args else "" for call in printer.print.call_args_list)

    def test_the_listing_names_the_minter(self, minted_by_baud: Path) -> None:
        """The exact question that could not be answered on the night."""
        host_tokens.issue_token("phase6-verify", scope="operate")

        with patch.object(host_api_module, "console") as printer, patch.object(host_api_module, "header"):
            host_api_module._cmd_list_tokens()

        assert "minted by baud" in self._lines(printer)

    def test_an_unused_token_says_so_rather_than_showing_a_blank(self, store: Path) -> None:
        """Minted-but-never-presented is a different state from live."""
        host_tokens.issue_token("pixel-8", scope="read")

        with patch.object(host_api_module, "console") as printer, patch.object(host_api_module, "header"):
            host_api_module._cmd_list_tokens()

        assert "never used" in self._lines(printer)

    def test_a_revoked_token_shows_when_it_died(self, store: Path) -> None:
        """Revoked is a state; revoked_at is the thing an incident needs."""
        record, _ = host_tokens.issue_token("pixel-8", scope="read")
        host_tokens.revoke_token(record["id"])

        with patch.object(host_api_module, "console") as printer, patch.object(host_api_module, "header"):
            host_api_module._cmd_list_tokens()

        assert "revoked 20" in self._lines(printer)

    def test_a_used_token_shows_a_readable_time_not_an_iso_blob(self, store: Path) -> None:
        """An operator reads this at a terminal, so microseconds are noise."""
        record, _ = host_tokens.issue_token("pixel-8", scope="read")
        host_tokens.touch_token(record["id"])

        with patch.object(host_api_module, "console") as printer, patch.object(host_api_module, "header"):
            host_api_module._cmd_list_tokens()

        printed = self._lines(printer)
        assert "last used 20" in printed
        assert "never used" not in printed

    def test_an_unparseable_stamp_is_shown_raw_and_never_as_nothing(self) -> None:
        """
        A stamp that renders as an empty string reads as 'absent'.

        Hand-edited stores exist. Showing the odd value is how someone notices;
        showing nothing is how it stays wrong.
        """
        assert host_api_module._stamp("not-a-time") == "not-a-time"
        assert host_api_module._provenance({"minted_by": "", "last_used": None}) == "minted by unknown · never used"


def test_the_reserved_comment_is_gone(store: Any) -> None:
    """
    Phase 1 left a RESERVATION comment saying last_used is never written.

    It is written now, and a stale reservation is worse than no comment: the
    next reader trusts it and stops looking.
    """
    source = Path(host_tokens.__file__).read_text(encoding="utf-8")

    assert "never written in Phase 1" not in source
