# =================== AIPass ====================
# Name: test_host_token_store.py
# Description: Tests for token provenance, revocation time and live/dormant telemetry
# Version: 1.1.1
# Created: 2026-08-14
# Modified: 2026-10-24
# =============================================

"""Tests for apps/handlers/host/tokens.py, the token store's accountability fields and its lock."""

# `last_used` is written on every authenticated request to the file revoke writes; a touch
# holding a list read before a revoke would un-revoke the token. Telemetry never undoes security.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(covered) — scope_allows() and resolve_token(), tests/test_host_api.py
# seedgo: no-test-needed(covered) — the failed-auth audit line, tests/test_host_auth_audit.py
# seedgo: no-test-needed(stdlib) — secrets.token_urlsafe's randomness itself

import importlib.util
import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from aipass.api.apps.handlers.host import server as host_server
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


class TestTheStoreRemembersWhoMintedIt:
    """The audit knows who FAILS auth; the store must know who ISSUES."""

    def test_the_calling_branch_is_recorded(self, minted_by_baud: Path) -> None:
        """drone names the caller in the child env; this reads it."""
        record, _ = host_tokens.issue_token("phase6-verify", scope="operate")

        assert record["minted_by"] == "baud"

    def test_an_unnamed_caller_is_recorded_as_unknown(self, store: Path) -> None:
        """'unknown' rather than a blank or a missing key."""
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

        The value is the caller's own env var; trusting it would be trusting the caller about the caller.
        """
        with patch.dict(os.environ, {CALLER_ENV: "definitely-not-a-real-branch"}):
            record, raw = host_tokens.issue_token("odd-caller", scope="operate")

        assert record["minted_by"] == "definitely-not-a-real-branch"
        assert host_tokens.verify_token(raw) is not None

    def test_current_minter_never_raises_on_a_bare_environment(self, store: Path) -> None:
        """
        Best-effort means it answers under every environment, including none.

        Called directly: through issue_token a raise would hide behind issue_token's own failure.
        """
        with patch.dict(os.environ, {}, clear=True):
            assert host_tokens.current_minter() == host_tokens.UNKNOWN_MINTER

        with patch.dict(os.environ, {CALLER_ENV: "   "}):
            assert host_tokens.current_minter() == host_tokens.UNKNOWN_MINTER

        with patch.dict(os.environ, {CALLER_ENV: "  baud  "}):
            assert host_tokens.current_minter() == "baud"


class TestRevokedAtWasStoredButNotSurfaced:
    """`revoked_at` is stored at revoke and must also reach the list_tokens() projection."""

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


class TestLastUsedAnswersLiveOrDormant:
    """The field answers 'still in use or dormant', not 'when exactly', so writes coalesce in a window."""

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

    def test_a_fresh_stamp_the_caller_holds_takes_no_lock(self, store: Path) -> None:
        """Every authenticated request touches: a stamp already inside the window must not lock the store."""
        record, _ = host_tokens.issue_token("pixel-8", scope="read")
        host_tokens.touch_token(record["id"])
        stamp = _record(record["id"])["last_used"]

        with patch.object(host_tokens, "_store_lock") as lock:
            host_tokens.touch_token(record["id"], last_used=stamp)

        lock.assert_not_called()

    def test_a_touch_after_the_window_rewrites(self, store: Path) -> None:
        """Coalescing must not become never-updating."""
        record, _ = host_tokens.issue_token("pixel-8", scope="read")
        host_tokens.touch_token(record["id"])
        first = _record(record["id"])["last_used"]

        with patch.object(host_tokens, "LAST_USED_GRANULARITY_SECONDS", 0):
            host_tokens.touch_token(record["id"])

        assert _record(record["id"])["last_used"] != first

    def test_an_unreadable_stamp_is_rewritten_and_said_without_its_value(self, store: Path) -> None:
        """
        A hand-edited stamp is due, rewritten readable, and named in words only.

        The stamp comes from the credential store and ValueError's text quotes it; neither reaches the log.
        """
        record, _ = host_tokens.issue_token("pixel-8", scope="read")
        records = host_tokens.load_tokens()
        for stored in records:
            stored["last_used"] = "not-a-date"
        host_tokens.save_tokens(records)

        with patch(PATCH_TOKENS_LOGGER) as log:
            host_tokens.touch_token(record["id"])

        assert _record(record["id"])["last_used"] != "not-a-date"
        message, *values = log.warning.call_args.args
        logged = message % tuple(values)
        assert "unreadable last_used stamp, treating as due" in logged
        assert "not-a-date" not in logged

    def test_touching_an_unknown_id_changes_nothing(self, store: Path) -> None:
        """No record created, no error raised."""
        host_tokens.issue_token("pixel-8", scope="read")
        before = host_tokens.load_tokens()

        host_tokens.touch_token("not-a-real-id")

        assert host_tokens.load_tokens() == before


class TestTelemetryNeverUndoesSecurity:
    """The load-bearing class in this file."""

    def test_the_touch_reads_inside_the_lock_not_before_it(self, store: Path) -> None:
        """
        The property that makes a concurrent revoke safe, pinned directly.

        The lock is not re-entrant: forcing a revoke from inside the touch's read deadlocks the harness.
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
        """Real threads, real lock: whichever order they serialise in, the token ends up revoked."""
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
        """Telemetry never fails a request: a busy store means a missing timestamp, not a 500."""
        record, _ = host_tokens.issue_token("pixel-8", scope="read")

        with patch.object(host_tokens, "_store_lock", side_effect=OSError("lock is held")):
            with patch(PATCH_TOKENS_LOGGER) as log:
                host_tokens.touch_token(record["id"])

        assert _record(record["id"])["last_used"] is None
        # Never with the id: it is read out of the credential store (CodeQL clear-text logging).
        message, *values = log.warning.call_args.args
        logged = message % tuple(values)
        assert "could not record last_used for the presented token" in logged
        assert "lock is held" in logged
        assert record["id"] not in logged


class TestTheRowsRestInTheKeyring:
    """The token rows are one JSON entry, host_api/tokens; the directory keeps only the lock and receipts."""

    def test_the_rows_are_one_json_entry_after_a_write(self, store: Path, keyring_store: Any) -> None:
        host_tokens.issue_token("pixel-8", scope="read")

        assert json.loads(keyring_store.entries[("aipass", "host_api/tokens")])["tokens"]

    def test_no_file_is_left_in_the_directory_by_a_write(self, store: Path) -> None:
        host_tokens.issue_token("pixel-8", scope="read")

        assert [item.name for item in (store / "host_api").iterdir()] == []

    def test_the_version_is_bumped_for_the_new_fields(self, store: Path, keyring_store: Any) -> None:
        """A reader must be able to tell which shape it is holding."""
        host_tokens.issue_token("pixel-8", scope="read")

        stored = json.loads(keyring_store.entries[("aipass", "host_api/tokens")])
        assert stored["version"] == host_tokens.STORE_VERSION
        assert host_tokens.STORE_VERSION >= 2


class TestOlderRecordsStillWork:
    """Version 1 records must keep verifying, listing and revoking without the new fields."""

    def test_a_version_one_record_still_verifies(self, store: Path) -> None:
        """No minted_by, no revoked_at. Still a valid credential."""
        record, raw = host_tokens.issue_token("legacy", scope="read")
        records = host_tokens.load_tokens()
        for stored in records:
            stored.pop("minted_by", None)
        host_tokens.save_tokens(records)

        verified = host_tokens.verify_token(raw)
        assert verified is not None
        assert verified["id"] == record["id"]

    def test_a_version_one_record_lists_without_inventing_a_minter(self, store: Path) -> None:
        """Absent is not 'unknown' here — it is honestly absent."""
        record, _ = host_tokens.issue_token("legacy", scope="read")
        records = host_tokens.load_tokens()
        for stored in records:
            stored.pop("minted_by", None)
        host_tokens.save_tokens(records)

        listed = next(row for row in host_tokens.list_tokens() if row["id"] == record["id"])
        assert listed["minted_by"] is None


# find_spec, not host_server.is_available(): the skip reads the machine, not the code under
# test, so a broken is_available() cannot turn these into silent skips (seedgo self_skip).
fastapi_installed = pytest.mark.skipif(
    importlib.util.find_spec("fastapi") is None,
    reason="the [host] extra is not installed",
)


@fastapi_installed
class TestTheServerTouchesOnEveryAuthenticatedRequest:
    """Wiring: the field is worthless if nothing writes it."""

    def test_a_successful_verification_touches_the_token(self, store: Path) -> None:
        """Where 'last_used' actually comes from."""
        from fastapi.testclient import TestClient

        record, raw = host_tokens.issue_token("pixel-8", scope="read")

        with patch("aipass.api.apps.handlers.host.server.logger", autospec=True):
            with patch("aipass.api.apps.handlers.host.server.json_handler", autospec=True):
                with patch("aipass.api.apps.handlers.host.face.json_handler", autospec=True):
                    with patch("aipass.api.apps.handlers.host.face.logger", autospec=True):
                        client = TestClient(host_server.create_app(), raise_server_exceptions=False)
                        client.get("/v1/whoami", headers={"Authorization": f"Bearer {raw}"})

        assert _record(record["id"])["last_used"]

    def test_a_refused_request_touches_nothing(self, store: Path) -> None:
        """A rejected token was not used — it was presented and refused."""
        from fastapi.testclient import TestClient

        record, _ = host_tokens.issue_token("pixel-8", scope="read")

        with patch("aipass.api.apps.handlers.host.server.logger", autospec=True):
            with patch("aipass.api.apps.handlers.host.server.json_handler", autospec=True):
                with patch("aipass.api.apps.handlers.host.face.json_handler", autospec=True):
                    with patch("aipass.api.apps.handlers.host.face.logger", autospec=True):
                        client = TestClient(host_server.create_app(), raise_server_exceptions=False)
                        client.get("/v1/whoami", headers={"Authorization": "Bearer wrong"})

        assert _record(record["id"])["last_used"] is None


class TestTheTouchIsNotAnOracle:
    """`last_used` is written only for a token that verified, never for a guessed value."""

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
        """A process that dies holding the lock must not lock out its successors."""
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

    def test_the_lock_sits_in_the_directory_and_no_store_file_is_named(self, store: Path) -> None:
        assert host_tokens.lock_path() == store / "host_api" / "tokens.lock"
        assert not hasattr(host_tokens, "store_path")
        assert not hasattr(host_tokens, "write_private_json")

    def test_a_lock_being_deleted_is_waited_for_and_the_revoke_lands(self, store: Path) -> None:
        """
        CI 35192484222, Windows: the answer that killed a revoke.

        An exclusive create on a delete-pending lock answers ACCESS DENIED on Windows, not FILE EXISTS.
        """
        record, raw = host_tokens.issue_token("pixel-8", scope="read")
        lock_file = str(host_tokens.lock_path())
        real_open = os.open
        lock_attempts = []

        def delete_pending_once(path: Any, flags: int, mode: int = 0o777, **kwargs: Any) -> int:
            if path == lock_file:
                lock_attempts.append(flags)
                if len(lock_attempts) == 1:
                    raise PermissionError(13, "Permission denied", path)
            return real_open(path, flags, mode, **kwargs)

        with patch.object(host_tokens.os, "open", new=delete_pending_once):
            assert host_tokens.revoke_token(record["id"]) is True

        assert len(lock_attempts) == 2
        assert _record(record["id"])["revoked"] is True
        assert host_tokens.verify_token(raw) is None
        assert not host_tokens.lock_path().exists()

    def test_a_held_lock_fails_issue_at_the_deadline(self, store: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """
        A fresh lock another writer holds (FILE EXISTS) is waited for, then refused.

        elapsed >= wait with the poll below the wait says the loop polled more than once.
        """
        wait = 0.1
        monkeypatch.setattr(host_tokens, "LOCK_WAIT_SECONDS", wait)
        monkeypatch.setattr(host_tokens, "LOCK_POLL_SECONDS", 0.01)
        lock = host_tokens.lock_path()
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.write_bytes(b"")

        started = time.monotonic()
        with pytest.raises(OSError) as raised:
            host_tokens.issue_token("pixel-8", scope="read")
        elapsed = time.monotonic() - started

        assert elapsed >= wait
        assert str(raised.value) == f"Token store lock held longer than {wait}s at {lock}"
        assert raised.value.__cause__ is None
        assert lock.exists(), "a fresh lock held by another writer was broken"

    def test_an_access_denial_that_never_clears_still_fails_at_the_deadline(
        self, store: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        Waiting out a delete is not forgiving a permissions problem.

        The host is probed first: root and Windows create in a read-only directory anyway.
        """
        wait = 0.1
        monkeypatch.setattr(host_tokens, "LOCK_WAIT_SECONDS", wait)
        monkeypatch.setattr(host_tokens, "LOCK_POLL_SECONDS", 0.01)
        lock = host_tokens.lock_path()
        lock.parent.mkdir(parents=True, exist_ok=True)
        mode = lock.parent.stat().st_mode
        lock.parent.chmod(0o500)
        try:
            probe = lock.parent / "probe.lock"
            host_refusals: list = []
            try:
                os.close(os.open(str(probe), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600))
            except PermissionError as refusal:
                host_refusals.append(refusal)
            else:
                probe.unlink()

            started = time.monotonic()
            if host_refusals:
                host_refusal = host_refusals[0]
                with pytest.raises(OSError) as raised:
                    host_tokens.issue_token("pixel-8", scope="read")
                elapsed = time.monotonic() - started
                assert elapsed >= wait
                assert str(raised.value).startswith(f"Token store lock at {lock} still denied access after {wait}s: ")
                assert type(raised.value.__cause__) is type(host_refusal)
            else:
                record, _raw = host_tokens.issue_token("pixel-8", scope="read")
                assert _record(record["id"])["revoked"] is False
        finally:
            lock.parent.chmod(mode)

    def test_a_lock_that_cannot_be_removed_is_said_out_loud(self, store: Path) -> None:
        """
        A release refused by the platform has not found the lock already gone.

        POSIX unlinks a held file, so a directory takes the lock's place; Windows keeps a handle open.
        """
        lock = host_tokens.lock_path()
        refusals: list = []
        held: list = []

        def save_and_wedge(*args: Any, **kwargs: Any) -> None:
            try:
                os.unlink(str(lock))
            except PermissionError as refusal:
                refusals.append(refusal)
                held.append(open(lock, "rb"))
            else:
                lock.mkdir()

        try:
            with patch.object(host_tokens, "save_tokens", side_effect=save_and_wedge):
                with patch(PATCH_TOKENS_LOGGER) as log:
                    host_tokens.issue_token("pixel-8", scope="read")
        finally:
            for handle in held:
                handle.close()
            if lock.is_dir():
                lock.rmdir()

        assert len(held) == len(refusals), "every refused unlink kept its handle open past the release"
        assert log.warning.call_count == 1
        message, *values = log.warning.call_args.args
        # The lock's path stays off the line (seedgo clear_text_secret_logging).
        assert "token store lock" in message
        assert len(values) == 1
        assert isinstance(values[0], OSError)

    def test_a_lock_already_gone_at_release_stays_quiet(self, store: Path) -> None:
        """
        The ordinary outcome of a stale-lock break racing a release: debug, not a warning.

        Windows cannot unlink a held file, so there the release removes the lock quietly instead.
        """
        lock = host_tokens.lock_path()
        refusals: list = []

        def save_and_break_the_lock(*args: Any, **kwargs: Any) -> None:
            try:
                os.unlink(str(lock))
            except PermissionError as refusal:
                refusals.append(refusal)

        with patch.object(host_tokens, "save_tokens", side_effect=save_and_break_the_lock):
            with patch(PATCH_TOKENS_LOGGER) as log:
                host_tokens.issue_token("pixel-8", scope="read")

        assert log.warning.call_count == 0
        assert log.debug.call_count == (0 if refusals else 1)
        assert not lock.exists()


class TestTheLockSurvivesAFailedWrite(object):
    """A raised exception mid-write must not leave the lock held."""

    def test_a_failing_save_still_releases_the_lock(self, store: Path) -> None:
        """The finally clause, pinned — this is how a store wedges itself."""
        with patch.object(host_tokens, "save_tokens", side_effect=OSError("disk full")):
            with pytest.raises(OSError):
                host_tokens.issue_token("pixel-8", scope="read")

        assert not host_tokens.lock_path().exists()


class TestTheListingSaysWhatTheStoreNowKnows:
    """The operator's actual window onto all three fields."""

    def _listing(self, capsys: pytest.CaptureFixture) -> str:
        """Run the operator's own command and return what it printed."""
        assert host_api_module.handle_command("host-api", ["list-tokens"]) is True
        out, _ = capsys.readouterr()
        return out

    def test_the_listing_names_the_minter(self, minted_by_baud: Path, capsys: pytest.CaptureFixture) -> None:
        """The exact question that could not be answered on the night."""
        host_tokens.issue_token("phase6-verify", scope="operate")
        capsys.readouterr()

        assert "minted by baud" in self._listing(capsys)

    def test_an_unused_token_says_so_rather_than_showing_a_blank(
        self, store: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """Minted-but-never-presented is a different state from live."""
        host_tokens.issue_token("pixel-8", scope="read")
        capsys.readouterr()

        assert "never used" in self._listing(capsys)

    def test_a_revoked_token_shows_when_it_died(self, store: Path, capsys: pytest.CaptureFixture) -> None:
        """Revoked is a state; revoked_at is the thing an incident needs."""
        record, _ = host_tokens.issue_token("pixel-8", scope="read")
        host_tokens.revoke_token(record["id"])
        capsys.readouterr()

        assert "revoked 20" in self._listing(capsys)

    def test_a_used_token_shows_a_readable_time_not_an_iso_blob(
        self, store: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """An operator reads this at a terminal, so microseconds are noise."""
        record, _ = host_tokens.issue_token("pixel-8", scope="read")
        host_tokens.touch_token(record["id"])
        capsys.readouterr()

        printed = self._listing(capsys)
        assert "last used 20" in printed
        assert "never used" not in printed

    @pytest.mark.parametrize(
        ("stamp", "provenance"),
        [
            ("not-a-time", "minted by unknown · last used not-a-time"),
            (None, "minted by unknown · never used"),
            ("2026-09-28T05:41:07.123456", "minted by unknown · last used 2026-09-28 05:41"),
        ],
        ids=["hand-edited", "never-presented", "presented"],
    )
    def test_an_unparseable_stamp_is_shown_raw_and_never_as_nothing(
        self, store: Path, capsys: pytest.CaptureFixture, stamp: str | None, provenance: str
    ) -> None:
        """A stamp that renders as an empty string reads as 'absent'."""
        host_tokens.issue_token("one-token", scope="read")
        records = host_tokens.load_tokens()
        for stored in records:
            stored["minted_by"] = ""
            stored["last_used"] = stamp
        host_tokens.save_tokens(records)
        capsys.readouterr()

        # Whole lines, not a substring: a substring passes a provenance line with anything around it.
        lines = {line.strip() for line in self._listing(capsys).splitlines()}
        assert provenance in lines

    def test_an_unparseable_stamp_is_logged_without_its_value(self, store: Path, capsys: pytest.CaptureFixture) -> None:
        """The listing shows the odd stamp to the operator; the log line only names it."""
        host_tokens.issue_token("one-token", scope="read")
        records = host_tokens.load_tokens()
        for stored in records:
            stored["last_used"] = "not-a-date"
        host_tokens.save_tokens(records)
        capsys.readouterr()

        with patch.object(host_api_module, "logger") as log:
            listing = self._listing(capsys)

        assert "last used not-a-date" in listing
        message, *values = log.warning.call_args.args
        logged = message % tuple(values)
        assert "unreadable timestamp in the token store" in logged
        assert "not-a-date" not in logged


def test_the_reserved_comment_is_gone(store: Any) -> None:
    """Phase 1 left a RESERVATION comment saying last_used is never written."""
    source = Path(host_tokens.__file__).read_text(encoding="utf-8")

    assert "never written in Phase 1" not in source


class TestTheReceiptHasAHomeAndTheLabelIsFenced:
    """
    Where a raw token lands when the caller does not choose.

    The label becomes a filename, the one place it could reach somewhere it should not.
    """

    def test_the_receipt_sits_beside_the_lock(self, store: Path) -> None:
        """The receipt is the one value written to disk on purpose, in the same 0700 directory as the lock."""
        receipt = host_tokens.receipt_path("pixel-8")

        assert receipt == (store / "host_api" / "pixel-8.token").resolve()
        assert receipt.parent == host_tokens.lock_path().parent.resolve()

    def test_a_label_carrying_a_separator_is_refused(self, store: Path) -> None:
        """A label is a NAME. This is the one function that makes it a path."""
        with pytest.raises(host_tokens.TokenError) as refusal:
            host_tokens.receipt_path("phones/pixel-8")

        assert "path" in str(refusal.value)

    def test_a_traversing_label_is_refused(self, store: Path) -> None:
        """The obvious escape, named rather than sanitised into something else."""
        with pytest.raises(host_tokens.TokenError):
            host_tokens.receipt_path("../../pixel-8")

    def test_an_absolute_label_is_refused(self, store: Path) -> None:
        """A label that is already a path does not get to become one."""
        with pytest.raises(host_tokens.TokenError):
            host_tokens.receipt_path("/etc/pixel-8")

    def test_a_hidden_label_is_refused(self, store: Path) -> None:
        """A secret nobody can see is a secret nobody rotates."""
        with pytest.raises(host_tokens.TokenError) as refusal:
            host_tokens.receipt_path(".pixel-8")

        assert "hidden" in str(refusal.value)

    def test_a_bare_dot_is_refused(self, store: Path) -> None:
        """'.' survives Path().name and would name the directory itself."""
        with pytest.raises(host_tokens.TokenError):
            host_tokens.receipt_path(".")

    def test_an_empty_label_is_refused_in_the_stores_own_words(self, store: Path) -> None:
        """The same sentence issue_token uses — one rule, stated once."""
        with pytest.raises(host_tokens.TokenError) as refusal:
            host_tokens.receipt_path("   ")

        assert "label is required" in str(refusal.value)

    def test_an_ordinary_label_with_spaces_still_works(self, store: Path) -> None:
        """The fence refuses what is DANGEROUS, not what is untidy."""
        receipt = host_tokens.receipt_path("Someone's old phone")

        assert receipt.name == "Someone's old phone.token"
        assert receipt.parent == (store / "host_api").resolve()

    @pytest.mark.skipif(sys.platform == "win32", reason="symlink creation needs privilege on Windows")
    def test_a_receipt_path_that_symlinks_out_of_the_store_is_refused(self, store: Path) -> None:
        """The second gate, and the case that proves it is not decoration.

        "pixel-8" is a good name; the escape is a symlink at the receipt's path, seen only after resolving.
        """
        provider_dir = store / "host_api"
        provider_dir.mkdir(parents=True, exist_ok=True)
        (provider_dir / "pixel-8.token").symlink_to(store.parent / "elsewhere.token")

        with pytest.raises(host_tokens.TokenError) as refusal:
            host_tokens.receipt_path("pixel-8")

        assert "outside" in str(refusal.value)

    def test_the_label_is_stripped_the_way_the_record_strips_it(self, store: Path) -> None:
        """The receipt and the record must agree on what the label IS."""
        record, _raw = host_tokens.issue_token("  pixel-8  ")

        assert host_tokens.receipt_path("  pixel-8  ").name == f"{record['label']}.token"
