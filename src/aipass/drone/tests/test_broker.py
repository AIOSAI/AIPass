# =================== AIPass ====================
# Name: test_broker.py
# Description: Tests for the drone-broker daemon, identity, and allowlist
# Version: 2.0.0
# Created: 2026-06-09
# Modified: 2026-06-10
# =============================================

"""Tests for the drone-broker daemon (Phase 3 + Phase 6a FPLAN-0250).

Covers: protocol serialization, path resolution (openat2 + walk fallback),
daemon accept/delete/refuse/audit, identity handshake (HMAC), allowlist
policy (identity-scoped), denylist backstop, confused-deputy attacks,
client broker_delete / create_identified_connection, and rm broker routing.
"""

from __future__ import annotations

import sys
import hashlib
import hmac as hmac_mod
import json
import socket
import os
import stat
from pathlib import Path

import pytest

from aipass.drone.apps.handlers.broker.protocol import BrokerRequest, BrokerResponse
from aipass.drone.apps.handlers.broker.path_resolver import resolve_beneath
from aipass.drone.apps.handlers.broker.daemon import BrokerDaemon
from aipass.drone.apps.handlers.broker.client import (
    broker_delete,
    create_identified_connection,
    is_sandboxed,
    BROKER_FD_ENV,
)
from aipass.drone.apps.handlers.json import json_handler

pytestmark = pytest.mark.skipif(
    sys.platform != "linux",
    reason="broker is Linux-only: AF_UNIX sockets + openat2 RESOLVE_BENEATH",
)

json_handler.log_operation("test_broker_load", {})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _recv_response(sock: socket.socket) -> BrokerResponse:
    """Read a single newline-terminated response from a socket."""
    data = b""
    while b"\n" not in data:
        chunk = sock.recv(4096)
        if not chunk:
            break
        data += chunk
    return BrokerResponse.from_bytes(data)


def _send_raw(sock_path: Path, req: BrokerRequest) -> BrokerResponse:
    """Send a request on a fresh (unidentified) connection, return response."""
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.connect(str(sock_path))
    try:
        client.sendall(req.to_bytes())
        return _recv_response(client)
    finally:
        client.close()


def _send_identified(broker: BrokerDaemon, branch: str, req: BrokerRequest) -> BrokerResponse:
    """Connect, identify, send request, return the delete response."""
    sock = create_identified_connection(broker.socket_path, broker._secret_path, branch)
    try:
        sock.sendall(req.to_bytes())
        return _recv_response(sock)
    finally:
        sock.close()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def repo_root(tmp_path: Path) -> Path:
    """Set up a mock repo root with branch directories marked by .trinity/."""
    root = tmp_path / "repo"
    root.mkdir()
    branch = root / "src" / "aipass" / "testbranch"
    branch.mkdir(parents=True)
    (branch / ".trinity").mkdir()
    (branch / "deleteme.txt").write_text("delete me", encoding="utf-8")
    (branch / "subdir").mkdir()
    (branch / "subdir" / "nested.txt").write_text("nested", encoding="utf-8")
    (branch / ".git").mkdir()
    (branch / ".git" / "HEAD").write_text("ref: refs/heads/main", encoding="utf-8")
    sibling = root / "src" / "aipass" / "sibling"
    sibling.mkdir(parents=True)
    (sibling / ".trinity").mkdir()
    (sibling / "important.txt").write_text("don't delete", encoding="utf-8")
    return root


@pytest.fixture()
def broker(tmp_path: Path, repo_root: Path) -> BrokerDaemon:
    """Create a broker instance with a temp socket and audit log."""
    sock_path = tmp_path / "test_broker.sock"
    audit_path = tmp_path / "test_audit.jsonl"
    secret_path = tmp_path / "test_secret"
    return BrokerDaemon(
        repo_root=repo_root,
        socket_path=sock_path,
        audit_path=audit_path,
        secret_path=secret_path,
    )


@pytest.fixture()
def running_broker(broker: BrokerDaemon):
    """Start a broker in background, yield it, stop on teardown."""
    t = broker.start_background()
    yield broker
    broker.stop()
    t.join(timeout=3)


# ---------------------------------------------------------------------------
# Protocol tests
# ---------------------------------------------------------------------------


class TestProtocol:
    """Test BrokerRequest/BrokerResponse serialization."""

    def test_request_roundtrip(self) -> None:
        """Request serializes and deserializes correctly."""
        req = BrokerRequest(op="delete", path="foo/bar.txt", request_id="abc123")
        data = req.to_bytes()
        assert data.endswith(b"\n")
        parsed = BrokerRequest.from_bytes(data)
        assert parsed.op == "delete"
        assert parsed.path == "foo/bar.txt"
        assert parsed.request_id == "abc123"

    def test_response_roundtrip(self) -> None:
        """Response serializes and deserializes correctly."""
        resp = BrokerResponse(ok=True, message="Deleted", request_id="abc")
        data = resp.to_bytes()
        parsed = BrokerResponse.from_bytes(data)
        assert parsed.ok is True
        assert parsed.message == "Deleted"

    def test_request_extra_fields(self) -> None:
        """Extra fields survive roundtrip."""
        req = BrokerRequest(op="delete", path="x", extra={"key": "val"})
        parsed = BrokerRequest.from_bytes(req.to_bytes())
        assert parsed.extra == {"key": "val"}

    def test_response_error_code(self) -> None:
        """Error code field survives roundtrip."""
        resp = BrokerResponse(ok=False, message="denied", error_code="DENYLIST")
        parsed = BrokerResponse.from_bytes(resp.to_bytes())
        assert parsed.error_code == "DENYLIST"

    def test_identify_request_roundtrip(self) -> None:
        """Identify request with branch/hmac survives roundtrip."""
        req = BrokerRequest(op="identify", branch="testbranch", hmac="abc123", request_id="id1")
        parsed = BrokerRequest.from_bytes(req.to_bytes())
        assert parsed.op == "identify"
        assert parsed.branch == "testbranch"
        assert parsed.hmac == "abc123"

    def test_delete_request_path_defaults_empty(self) -> None:
        """Delete request path defaults to empty string when missing."""
        data = json.dumps({"op": "delete"}).encode() + b"\n"
        parsed = BrokerRequest.from_bytes(data)
        assert parsed.path == ""
        assert parsed.branch == ""


# ---------------------------------------------------------------------------
# Path resolver tests
# ---------------------------------------------------------------------------


class TestPathResolver:
    """Test resolve_beneath path resolution."""

    def test_resolve_existing_file(self, repo_root: Path) -> None:
        """Resolves a valid file path beneath the base."""
        base = repo_root / "src" / "aipass" / "testbranch"
        result = resolve_beneath(base, "deleteme.txt")
        assert result == (base / "deleteme.txt").resolve()

    def test_resolve_nested(self, repo_root: Path) -> None:
        """Resolves a nested path."""
        base = repo_root / "src" / "aipass" / "testbranch"
        result = resolve_beneath(base, "subdir/nested.txt")
        assert result == (base / "subdir" / "nested.txt").resolve()

    def test_reject_dotdot_escape(self, repo_root: Path) -> None:
        """Refuses paths with .. components."""
        base = repo_root / "src" / "aipass" / "testbranch"
        with pytest.raises(OSError, match="\\.\\."):
            resolve_beneath(base, "../escape.txt")

    def test_reject_dotdot_middle(self, repo_root: Path) -> None:
        """Refuses .. in the middle of a path."""
        base = repo_root / "src" / "aipass" / "testbranch"
        with pytest.raises(OSError, match="\\.\\."):
            resolve_beneath(base, "subdir/../../escape.txt")

    def test_reject_absolute(self, repo_root: Path) -> None:
        """Refuses absolute paths."""
        base = repo_root / "src" / "aipass" / "testbranch"
        with pytest.raises(OSError, match="leading /"):
            resolve_beneath(base, "/etc/passwd")

    def test_reject_symlink(self, repo_root: Path) -> None:
        """Refuses paths through symlinks."""
        base = repo_root / "src" / "aipass" / "testbranch"
        link = base / "link"
        link.symlink_to("/tmp")
        try:
            with pytest.raises(OSError):
                resolve_beneath(base, "link/something")
        finally:
            link.unlink()

    def test_nonexistent_path(self, repo_root: Path) -> None:
        """Raises OSError for nonexistent paths."""
        base = repo_root / "src" / "aipass" / "testbranch"
        with pytest.raises(OSError):
            resolve_beneath(base, "does_not_exist.txt")


# ---------------------------------------------------------------------------
# Daemon mechanism tests (identified connection)
# ---------------------------------------------------------------------------


class TestBrokerDaemon:
    """Test the broker daemon accept/delete/refuse logic with an identified connection."""

    def test_delete_allowed_file(self, running_broker: BrokerDaemon, repo_root: Path) -> None:
        """Broker deletes an allowed file under the identified branch tree."""
        target = repo_root / "src" / "aipass" / "testbranch" / "deleteme.txt"
        assert target.exists()

        resp = _send_identified(
            running_broker,
            "testbranch",
            BrokerRequest(op="delete", path="deleteme.txt", request_id="t1"),
        )
        assert resp.ok is True
        assert "Deleted" in resp.message
        assert not target.exists()

        audit = running_broker.audit_path.read_text(encoding="utf-8").strip().split("\n")
        last = json.loads(audit[-1])
        assert last["result"] == "DELETED"
        assert last["identity"] == "testbranch"

    def test_delete_nested_file(self, running_broker: BrokerDaemon, repo_root: Path) -> None:
        """Broker deletes a nested file."""
        target = repo_root / "src" / "aipass" / "testbranch" / "subdir" / "nested.txt"
        assert target.exists()

        resp = _send_identified(
            running_broker,
            "testbranch",
            BrokerRequest(op="delete", path="subdir/nested.txt", request_id="t2"),
        )
        assert resp.ok is True
        assert not target.exists()

    def test_refuse_protected_git(self, running_broker: BrokerDaemon, repo_root: Path) -> None:
        """Broker refuses deletion inside .git (denylist backstop)."""
        target = repo_root / "src" / "aipass" / "testbranch" / ".git" / "HEAD"
        assert target.exists()

        resp = _send_identified(
            running_broker,
            "testbranch",
            BrokerRequest(op="delete", path=".git/HEAD", request_id="t3"),
        )
        assert resp.ok is False
        assert resp.error_code == "DENYLIST"
        assert target.exists()

    def test_refuse_dotdot_escape(self, running_broker: BrokerDaemon) -> None:
        """Broker refuses confused-deputy .. escape."""
        resp = _send_identified(
            running_broker,
            "testbranch",
            BrokerRequest(op="delete", path="../../../etc/passwd", request_id="t4"),
        )
        assert resp.ok is False

    def test_refuse_symlink_escape(self, running_broker: BrokerDaemon, repo_root: Path) -> None:
        """Broker refuses confused-deputy symlink escape."""
        base = repo_root / "src" / "aipass" / "testbranch"
        link = base / "evil_link"
        link.symlink_to("/tmp")
        try:
            resp = _send_identified(
                running_broker,
                "testbranch",
                BrokerRequest(op="delete", path="evil_link/target", request_id="t5"),
            )
            assert resp.ok is False
        finally:
            link.unlink()

    def test_refuse_nonexistent(self, running_broker: BrokerDaemon) -> None:
        """Broker refuses deletion of nonexistent paths."""
        resp = _send_identified(
            running_broker,
            "testbranch",
            BrokerRequest(op="delete", path="no_such_file.xyz", request_id="t6"),
        )
        assert resp.ok is False

    def test_refuse_root_delete(self, running_broker: BrokerDaemon) -> None:
        """Broker refuses deleting the base directory itself."""
        resp = _send_identified(
            running_broker,
            "testbranch",
            BrokerRequest(op="delete", path=".", request_id="t7"),
        )
        assert resp.ok is False

    def test_unknown_operation(self, running_broker: BrokerDaemon) -> None:
        """Broker refuses unknown operation types."""
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.connect(str(running_broker.socket_path))
        try:
            bad_req = json.dumps({"op": "chmod", "path": "x"}).encode() + b"\n"
            client.sendall(bad_req)
            resp = _recv_response(client)
            assert resp.ok is False
            assert resp.error_code == "UNKNOWN_OP"
        finally:
            client.close()

    def test_audit_log_written(self, running_broker: BrokerDaemon) -> None:
        """Every request writes an audit entry with identity."""
        _send_identified(
            running_broker,
            "testbranch",
            BrokerRequest(op="delete", path="deleteme.txt", request_id="audit1"),
        )
        assert running_broker.audit_path.exists()
        lines = running_broker.audit_path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) >= 1
        entry = json.loads(lines[-1])
        assert "timestamp" in entry
        assert "identity" in entry

    def test_stop_cleans_socket(self, broker: BrokerDaemon) -> None:
        """Stopping the broker removes the socket file."""
        t = broker.start_background()
        assert broker.socket_path.exists()
        broker.stop()
        t.join(timeout=3)
        assert not broker.socket_path.exists()


# ---------------------------------------------------------------------------
# Denylist tests
# ---------------------------------------------------------------------------


class TestDenylist:
    """Test that all protected directories are denied even with identity."""

    @pytest.mark.parametrize("dirname", [".git", ".trinity", ".aipass", ".codex", ".agents"])
    def test_protected_dirs_refused(
        self,
        running_broker: BrokerDaemon,
        repo_root: Path,
        dirname: str,
    ) -> None:
        """Each protected directory is refused regardless of identity."""
        branch_dir = repo_root / "src" / "aipass" / "testbranch"
        protected_dir = branch_dir / dirname
        protected_dir.mkdir(exist_ok=True)
        (protected_dir / "file.txt").write_text("protected", encoding="utf-8")

        resp = _send_identified(
            running_broker,
            "testbranch",
            BrokerRequest(
                op="delete",
                path=f"{dirname}/file.txt",
                request_id=f"deny_{dirname}",
            ),
        )
        assert resp.ok is False
        assert resp.error_code == "DENYLIST"
        assert (protected_dir / "file.txt").exists()


# ---------------------------------------------------------------------------
# Identity handshake tests
# ---------------------------------------------------------------------------


class TestIdentity:
    """Test the HMAC-based identity handshake."""

    def test_good_hmac_identifies(self, running_broker: BrokerDaemon) -> None:
        """Valid HMAC produces a successful identify response."""
        secret = running_broker._secret_path.read_bytes()
        mac = hmac_mod.new(secret, b"testbranch", hashlib.sha256).hexdigest()

        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.connect(str(running_broker.socket_path))
        try:
            req = BrokerRequest(
                op="identify",
                branch="testbranch",
                hmac=mac,
                request_id="id1",
            )
            client.sendall(req.to_bytes())
            resp = _recv_response(client)
            assert resp.ok is True
            assert "Identified" in resp.message
        finally:
            client.close()

    def test_bad_hmac_refused(self, running_broker: BrokerDaemon) -> None:
        """Invalid HMAC is refused and audited."""
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.connect(str(running_broker.socket_path))
        try:
            req = BrokerRequest(
                op="identify",
                branch="testbranch",
                hmac="deadbeef",
                request_id="id2",
            )
            client.sendall(req.to_bytes())
            resp = _recv_response(client)
            assert resp.ok is False
            assert resp.error_code == "IDENTIFY_FAILED"

            audit = running_broker.audit_path.read_text(encoding="utf-8").strip().split("\n")
            entry = json.loads(audit[-1])
            assert entry["result"] == "REFUSED"
            assert entry["reason"] == "bad HMAC"
        finally:
            client.close()

    def test_bad_hmac_connection_still_usable(self, running_broker: BrokerDaemon, tmp_path: Path) -> None:
        """After a bad HMAC, connection remains at unidentified scope."""
        tmp_file = tmp_path / "unid_delete.txt"
        tmp_file.write_text("unidentified", encoding="utf-8")

        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.connect(str(running_broker.socket_path))
        try:
            req = BrokerRequest(op="identify", branch="x", hmac="bad", request_id="id3")
            client.sendall(req.to_bytes())
            resp = _recv_response(client)
            assert resp.ok is False

            del_req = BrokerRequest(op="delete", path=str(tmp_file), request_id="id3del")
            client.sendall(del_req.to_bytes())
            del_resp = _recv_response(client)
            assert del_resp.ok is True
            assert not tmp_file.exists()
        finally:
            client.close()

    def test_second_identify_refused(self, running_broker: BrokerDaemon) -> None:
        """A second identify on the same connection is refused."""
        secret = running_broker._secret_path.read_bytes()
        mac = hmac_mod.new(secret, b"testbranch", hashlib.sha256).hexdigest()

        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.connect(str(running_broker.socket_path))
        try:
            req = BrokerRequest(
                op="identify",
                branch="testbranch",
                hmac=mac,
                request_id="first",
            )
            client.sendall(req.to_bytes())
            resp1 = _recv_response(client)
            assert resp1.ok is True

            req2 = BrokerRequest(
                op="identify",
                branch="testbranch",
                hmac=mac,
                request_id="second",
            )
            client.sendall(req2.to_bytes())
            resp2 = _recv_response(client)
            assert resp2.ok is False
            assert resp2.error_code == "IDENTIFY_LATE"
        finally:
            client.close()

    def test_identify_after_delete_refused(self, running_broker: BrokerDaemon, tmp_path: Path) -> None:
        """Identify after a delete (non-first message) is refused."""
        tmp_file = tmp_path / "early_delete.txt"
        tmp_file.write_text("early", encoding="utf-8")

        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.connect(str(running_broker.socket_path))
        try:
            del_req = BrokerRequest(op="delete", path=str(tmp_file), request_id="del_first")
            client.sendall(del_req.to_bytes())
            _recv_response(client)

            secret = running_broker._secret_path.read_bytes()
            mac = hmac_mod.new(secret, b"testbranch", hashlib.sha256).hexdigest()
            id_req = BrokerRequest(
                op="identify",
                branch="testbranch",
                hmac=mac,
                request_id="late_id",
            )
            client.sendall(id_req.to_bytes())
            resp = _recv_response(client)
            assert resp.ok is False
            assert resp.error_code == "IDENTIFY_LATE"
        finally:
            client.close()

    def test_missing_branch_refused(self, running_broker: BrokerDaemon) -> None:
        """Identify without branch field is refused."""
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.connect(str(running_broker.socket_path))
        try:
            req = BrokerRequest(op="identify", branch="", hmac="x", request_id="no_branch")
            client.sendall(req.to_bytes())
            resp = _recv_response(client)
            assert resp.ok is False
            assert resp.error_code == "IDENTIFY_INVALID"
        finally:
            client.close()

    def test_secret_file_0600(self, running_broker: BrokerDaemon) -> None:
        """Secret file is created with mode 0600."""
        if os.name != "posix":
            pytest.skip("POSIX permission check")
        mode = running_broker._secret_path.stat().st_mode
        assert stat.S_IMODE(mode) == 0o600  # noqa: windows_compat

    def test_secret_changes_across_restarts(self, tmp_path: Path, repo_root: Path) -> None:
        """Secret is regenerated on each daemon start."""
        sock1 = tmp_path / "s1.sock"
        sock2 = tmp_path / "s2.sock"
        secret_path = tmp_path / "secret"
        audit = tmp_path / "audit.jsonl"

        d1 = BrokerDaemon(
            repo_root=repo_root,
            socket_path=sock1,
            audit_path=audit,
            secret_path=secret_path,
        )
        t1 = d1.start_background()
        secret1 = secret_path.read_bytes()
        d1.stop()
        t1.join(timeout=3)

        d2 = BrokerDaemon(
            repo_root=repo_root,
            socket_path=sock2,
            audit_path=audit,
            secret_path=secret_path,
        )
        t2 = d2.start_background()
        secret2 = secret_path.read_bytes()
        d2.stop()
        t2.join(timeout=3)

        assert secret1 != secret2


# ---------------------------------------------------------------------------
# Allowlist policy tests
# ---------------------------------------------------------------------------


class TestAllowlistPolicy:
    """Test identity-scoped allowlist policy."""

    def test_unidentified_tmp_allowed(self, running_broker: BrokerDaemon, tmp_path: Path) -> None:
        """Unidentified connections can delete under /tmp."""
        target = tmp_path / "unid_tmp.txt"
        target.write_text("tmp file", encoding="utf-8")

        resp = _send_raw(
            running_broker.socket_path,
            BrokerRequest(op="delete", path=str(target), request_id="unid_tmp"),
        )
        assert resp.ok is True
        assert not target.exists()

    def test_unidentified_repo_refused(self, running_broker: BrokerDaemon, repo_root: Path) -> None:
        """Unidentified connections cannot delete repo paths."""
        target = repo_root / "src" / "aipass" / "testbranch" / "deleteme.txt"
        assert target.exists()

        resp = _send_raw(
            running_broker.socket_path,
            BrokerRequest(op="delete", path=str(target), request_id="unid_repo"),
        )
        assert resp.ok is False
        assert resp.error_code == "NO_BASE"
        assert target.exists()

    def test_builder_own_tree_allowed(self, running_broker: BrokerDaemon, repo_root: Path) -> None:
        """Builder identity can delete files in its own branch tree."""
        target = repo_root / "src" / "aipass" / "testbranch" / "deleteme.txt"
        assert target.exists()

        resp = _send_identified(
            running_broker,
            "testbranch",
            BrokerRequest(op="delete", path="deleteme.txt", request_id="own_tree"),
        )
        assert resp.ok is True
        assert not target.exists()

    def test_builder_sibling_refused(self, running_broker: BrokerDaemon, repo_root: Path) -> None:
        """Builder identity cannot delete files in a sibling branch tree."""
        target = repo_root / "src" / "aipass" / "sibling" / "important.txt"
        assert target.exists()

        resp = _send_identified(
            running_broker,
            "testbranch",
            BrokerRequest(op="delete", path=str(target), request_id="sibling"),
        )
        assert resp.ok is False
        assert resp.error_code == "NO_BASE"
        assert target.exists()

    def test_devpulse_sibling_allowed(self, running_broker: BrokerDaemon, repo_root: Path) -> None:
        """devpulse identity can delete files in any branch tree."""
        junk = repo_root / "src" / "aipass" / "sibling" / "junk.txt"
        junk.write_text("junk", encoding="utf-8")

        resp = _send_identified(
            running_broker,
            "devpulse",
            BrokerRequest(op="delete", path=str(junk), request_id="dp_sib"),
        )
        assert resp.ok is True
        assert not junk.exists()

    def test_devpulse_denylist_still_blocks(self, running_broker: BrokerDaemon, repo_root: Path) -> None:
        """devpulse cannot delete paths under denylist dirs (backstop)."""
        target = repo_root / "src" / "aipass" / "testbranch" / ".git" / "HEAD"
        assert target.exists()

        resp = _send_identified(
            running_broker,
            "devpulse",
            BrokerRequest(op="delete", path=str(target), request_id="dp_deny"),
        )
        assert resp.ok is False
        assert resp.error_code == "DENYLIST"
        assert target.exists()

    @pytest.mark.parametrize("dirname", [".git", ".trinity"])
    def test_devpulse_denylist_backstop(
        self,
        running_broker: BrokerDaemon,
        repo_root: Path,
        dirname: str,
    ) -> None:
        """devpulse is blocked by denylist backstop on protected dirs."""
        protected = repo_root / dirname
        protected.mkdir(exist_ok=True)
        (protected / "config").write_text("sacred", encoding="utf-8")

        resp = _send_identified(
            running_broker,
            "devpulse",
            BrokerRequest(
                op="delete",
                path=str(protected / "config"),
                request_id=f"dp_deny_{dirname}",
            ),
        )
        assert resp.ok is False
        assert resp.error_code == "DENYLIST"
        assert (protected / "config").exists()

    def test_audit_carries_identity_on_grant(self, running_broker: BrokerDaemon, repo_root: Path) -> None:
        """Audit entries for grants include the identity."""
        _send_identified(
            running_broker,
            "testbranch",
            BrokerRequest(op="delete", path="deleteme.txt", request_id="aud_grant"),
        )
        lines = running_broker.audit_path.read_text(encoding="utf-8").strip().split("\n")
        delete_entries = [json.loads(raw) for raw in lines if json.loads(raw).get("op") == "delete"]
        last = delete_entries[-1]
        assert last["identity"] == "testbranch"
        assert last["result"] == "DELETED"

    def test_audit_carries_identity_on_refusal(self, running_broker: BrokerDaemon, repo_root: Path) -> None:
        """Audit entries for refusals include the identity."""
        _send_identified(
            running_broker,
            "testbranch",
            BrokerRequest(op="delete", path=".git/HEAD", request_id="aud_refuse"),
        )
        lines = running_broker.audit_path.read_text(encoding="utf-8").strip().split("\n")
        delete_entries = [json.loads(raw) for raw in lines if json.loads(raw).get("op") == "delete"]
        last = delete_entries[-1]
        assert last["identity"] == "testbranch"
        assert last["result"] == "REFUSED"

    def test_audit_null_identity_for_unidentified(self, running_broker: BrokerDaemon, tmp_path: Path) -> None:
        """Audit entries for unidentified connections have null identity."""
        target = tmp_path / "aud_unid.txt"
        target.write_text("x", encoding="utf-8")

        _send_raw(
            running_broker.socket_path,
            BrokerRequest(op="delete", path=str(target), request_id="aud_unid"),
        )
        lines = running_broker.audit_path.read_text(encoding="utf-8").strip().split("\n")
        delete_entries = [json.loads(raw) for raw in lines if json.loads(raw).get("op") == "delete"]
        last = delete_entries[-1]
        assert last["identity"] is None


# ---------------------------------------------------------------------------
# Client tests
# ---------------------------------------------------------------------------


class TestClient:
    """Test the broker client (sandboxed drone rm path)."""

    def test_is_sandboxed_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Not sandboxed when env var is absent."""
        monkeypatch.delenv(BROKER_FD_ENV, raising=False)
        assert is_sandboxed() is False

    def test_is_sandboxed_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Sandboxed when env var is present."""
        monkeypatch.setenv(BROKER_FD_ENV, "3")
        assert is_sandboxed() is True

    def test_broker_delete_no_fd(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """broker_delete fails gracefully without fd."""
        monkeypatch.delenv(BROKER_FD_ENV, raising=False)
        ok, msg = broker_delete("/tmp/test")
        assert ok is False
        assert "not set" in msg

    def test_broker_delete_via_socket(
        self,
        running_broker: BrokerDaemon,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """broker_delete sends request over a real socket fd (unidentified, /tmp)."""
        target = tmp_path / "client_delete.txt"
        target.write_text("delete me", encoding="utf-8")

        client_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client_sock.connect(str(running_broker.socket_path))
        fd = client_sock.fileno()
        monkeypatch.setenv(BROKER_FD_ENV, str(fd))

        ok, msg = broker_delete(str(target))
        assert ok is True
        assert "Deleted" in msg
        assert not target.exists()

        client_sock.close()

    def test_create_identified_connection(self, running_broker: BrokerDaemon) -> None:
        """create_identified_connection returns an authenticated socket."""
        sock = create_identified_connection(
            running_broker.socket_path,
            running_broker._secret_path,
            "testbranch",
        )
        try:
            assert sock.fileno() >= 0
        finally:
            sock.close()

    def test_create_identified_connection_bad_secret(self, running_broker: BrokerDaemon, tmp_path: Path) -> None:
        """create_identified_connection raises on bad secret."""
        bad_secret = tmp_path / "bad_secret"
        bad_secret.write_bytes(b"wrong" * 8)

        with pytest.raises(RuntimeError, match="identify failed"):
            create_identified_connection(running_broker.socket_path, bad_secret, "testbranch")


# ---------------------------------------------------------------------------
# rm_handler integration tests
# ---------------------------------------------------------------------------


class TestRmBrokerRouting:
    """Test that rm module routes through broker when sandboxed."""

    def test_unsandboxed_uses_direct(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """Without AIPASS_BROKER_FD, rm uses direct delete."""
        monkeypatch.delenv(BROKER_FD_ENV, raising=False)
        target = tmp_path / "direct_delete.txt"
        target.write_text("test", encoding="utf-8")

        from aipass.drone.apps.modules.rm import safe_delete

        results = safe_delete([str(target)])
        assert results[0][1] is True
        assert not target.exists()

    def test_sandboxed_uses_broker(
        self,
        running_broker: BrokerDaemon,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """With AIPASS_BROKER_FD, rm routes through broker (unidentified, /tmp)."""
        target = tmp_path / "broker_rm.txt"
        target.write_text("delete me", encoding="utf-8")

        client_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client_sock.connect(str(running_broker.socket_path))
        monkeypatch.setenv(BROKER_FD_ENV, str(client_sock.fileno()))

        from aipass.drone.apps.modules.rm import safe_delete

        results = safe_delete([str(target)])
        assert results[0][1] is True
        assert not target.exists()

        client_sock.close()


# ---------------------------------------------------------------------------
# The broker is drone's OTHER delete lane — it feeds the same deletion record
#
# Patrick's ruling was "if something deletes, there should be a record of it",
# not "if drone rm deletes". The broker performs its own rmtree/unlink, so a
# record wired only into rm_handler would have a hole exactly the size of the
# sandboxed lane. Its protocol audit log stays as it was: that records requests
# and error codes, this records deletions, and they are not the same question.
# ---------------------------------------------------------------------------


class TestBrokerFeedsDeletionRecord:
    @staticmethod
    def _records() -> list[dict]:
        from aipass.drone.apps.handlers import deletion_log

        log = deletion_log.deletion_log_path()
        if not log.exists():
            return []
        return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]

    def test_broker_delete_is_recorded(self, running_broker: BrokerDaemon, repo_root: Path) -> None:
        target = repo_root / "src" / "aipass" / "testbranch" / "deleteme.txt"
        resp = _send_identified(
            running_broker,
            "testbranch",
            BrokerRequest(op="delete", path="deleteme.txt", request_id="rec1"),
        )
        assert resp.ok is True
        assert not target.exists()

        deletions = [r for r in self._records() if r["outcome"] == "deleted"]
        assert len(deletions) == 1
        assert deletions[0]["lane"] == "broker"
        assert deletions[0]["path"] == str(target.resolve())

    def test_broker_record_names_the_authenticated_requester(
        self, running_broker: BrokerDaemon, repo_root: Path
    ) -> None:
        """Not the daemon's cwd — the broker deletes on someone else's behalf."""
        _send_identified(
            running_broker,
            "testbranch",
            BrokerRequest(op="delete", path="deleteme.txt", request_id="rec2"),
        )

        deletions = [r for r in self._records() if r["outcome"] == "deleted"]
        assert deletions[0]["caller"] == "testbranch"

    def test_broker_measures_before_deleting(self, running_broker: BrokerDaemon, repo_root: Path) -> None:
        target = repo_root / "src" / "aipass" / "testbranch" / "deleteme.txt"
        expected = target.stat().st_size

        _send_identified(
            running_broker,
            "testbranch",
            BrokerRequest(op="delete", path="deleteme.txt", request_id="rec3"),
        )

        deletions = [r for r in self._records() if r["outcome"] == "deleted"]
        assert deletions[0]["kind"] == "file"
        assert deletions[0]["size_bytes"] == expected

    def test_broker_denylist_refusal_is_recorded(self, running_broker: BrokerDaemon, repo_root: Path) -> None:
        resp = _send_identified(
            running_broker,
            "testbranch",
            BrokerRequest(op="delete", path=".trinity", request_id="rec4"),
        )
        assert resp.ok is False

        refusals = [r for r in self._records() if r["outcome"] == "refused"]
        assert refusals, "a blocked broker delete left no record"
        assert refusals[-1]["lane"] == "broker"
        assert refusals[-1]["caller"] == "testbranch"

    def test_broker_out_of_scope_refusal_is_recorded(self, running_broker: BrokerDaemon, repo_root: Path) -> None:
        """Sibling branch: allowed for nobody but devpulse, and still recorded."""
        resp = _send_identified(
            running_broker,
            "testbranch",
            BrokerRequest(
                op="delete",
                path=str(repo_root / "src" / "aipass" / "sibling" / "important.txt"),
                request_id="rec5",
            ),
        )
        assert resp.ok is False

        refusals = [r for r in self._records() if r["outcome"] == "refused"]
        assert refusals, "an out-of-scope broker delete left no record"
        assert refusals[-1]["caller"] == "testbranch"
