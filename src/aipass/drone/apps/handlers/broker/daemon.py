# =================== AIPass ====================
# Name: daemon.py
# Description: Broker daemon — privileged deleter for sandboxed agents
# Version: 2.1.1
# Created: 2026-06-09
# Modified: 2026-08-31
# =============================================

"""Broker daemon — privileged deleter for sandboxed agents.

A long-lived process that listens on a unix socket, accepts delete requests
from sandboxed ``drone rm`` clients, re-resolves paths via openat2
RESOLVE_BENEATH (never trusting agent-supplied strings), applies
identity-bound allowlist policy, performs the delete, and audit-logs
every attempt.

Identity model (Phase 6a):
    The launcher pre-connects, authenticates with an HMAC derived from a
    per-start secret, declares the branch identity, then passes the
    connected fd to the sandboxed child.  The child inherits an already-
    identified connection.  Connections that never identify get the
    narrowest scope (/tmp only).
"""

from __future__ import annotations

import hashlib
import hmac as hmac_mod
import json
import os
import secrets
import socket
import tempfile
import threading
import time
from pathlib import Path

from aipass.prax import logger
from aipass.drone.apps.handlers.json import json_handler
from aipass.drone.apps.handlers.broker.protocol import BrokerRequest, BrokerResponse
from aipass.drone.apps.handlers.broker.path_resolver import resolve_beneath
from aipass.drone.apps.handlers import deletion_log
from aipass.drone.apps.handlers.router_handler import caller_cwd, registries_in

_DEFAULT_SOCKET_DIR = ".ai_central"
_SOCKET_NAME = "drone_broker.sock"
_AUDIT_LOG_NAME = "drone_broker_audit.jsonl"
_SECRET_NAME = "broker_secret"

_DENYLIST_DIRS = frozenset((".git", ".trinity", ".aipass", ".codex", ".agents"))

_TMP_BASES = (Path(tempfile.gettempdir()),)


def _find_project_root() -> Path | None:
    """Walk up from CWD to find *_REGISTRY.json; return its parent as project root.

    A byte-for-byte twin of ``rm_handler._find_project_root`` and it carried the
    identical unguarded read. Left as two functions rather than merged: the
    broker is a long-lived daemon and the rm lane is a one-shot command, so a
    shared root-finder would couple their lifetimes for the sake of six lines.
    They are pinned together by ``TestTheSweepIsComplete`` instead, which is
    what actually keeps them from drifting apart again.
    """
    cwd = caller_cwd()
    if cwd is not None:
        for parent in [cwd, *cwd.parents]:
            if registries_in(parent):
                return parent.resolve()
    aipass_home = os.environ.get("AIPASS_HOME")
    if aipass_home:
        home = Path(aipass_home)
        if home.is_dir() and registries_in(home):
            return home.resolve()
    return None


def _default_socket_path() -> Path:
    """Return the default broker socket path under the repo root."""
    root = _find_project_root()
    if root is None:
        return Path(tempfile.gettempdir()) / _SOCKET_NAME
    return root / _DEFAULT_SOCKET_DIR / _SOCKET_NAME


def _default_audit_path() -> Path:
    """Return the default audit log path."""
    root = _find_project_root()
    if root is None:
        return Path(tempfile.gettempdir()) / _AUDIT_LOG_NAME
    return root / _DEFAULT_SOCKET_DIR / _AUDIT_LOG_NAME


def _default_secret_path() -> Path:
    """Return the default secret path."""
    root = _find_project_root()
    if root is None:
        return Path(tempfile.gettempdir()) / _SECRET_NAME
    return root / _DEFAULT_SOCKET_DIR / _SECRET_NAME


class BrokerDaemon:
    """Out-of-sandbox delete broker with identity-bound allowlist policy.

    Listens on a unix socket, optionally authenticates connections via
    HMAC, then validates delete requests via openat2 path re-resolution,
    identity-scoped allowlist, and a denylist backstop before performing
    ``os.unlink`` / ``shutil.rmtree``.

    Identity scopes:
        None (unidentified): /tmp, /var/tmp only.
        Builder branch: /tmp, /var/tmp, + own tree ($REPO/src/aipass/<branch>/).
        devpulse: /tmp, /var/tmp, + anywhere under $REPO.
        Denylist backstop (.git, .trinity, .aipass, .codex, .agents) always applies.
    """

    def __init__(
        self,
        repo_root: Path | None = None,
        socket_path: Path | None = None,
        audit_path: Path | None = None,
        secret_path: Path | None = None,
    ) -> None:
        """Initialize the broker.

        Args:
            repo_root: Project root directory. Auto-discovered if not set.
            socket_path: Where to bind the unix socket.
            audit_path: Where to write the JSONL audit log.
            secret_path: Where to write the per-start HMAC secret.
        """
        self._repo_root = repo_root.resolve() if repo_root else _find_project_root()
        self.socket_path = socket_path or _default_socket_path()
        self.audit_path = audit_path or _default_audit_path()
        self._secret_path = secret_path or _default_secret_path()
        self._secret: bytes = b""
        self._server: socket.socket | None = None
        self._running = False
        self._listening = threading.Event()
        self._lock = threading.Lock()
        json_handler.log_operation(
            "broker_init",
            {
                "repo_root": str(self._repo_root),
                "socket": str(self.socket_path),
            },
        )

    def _generate_secret(self) -> bytes:
        """Generate a fresh HMAC secret, write to disk with mode 0600."""
        secret = secrets.token_bytes(32)
        self._secret_path.parent.mkdir(parents=True, exist_ok=True)
        self._secret_path.write_bytes(secret)
        self._secret_path.chmod(0o600)
        logger.info("broker: generated secret at %s", self._secret_path)
        return secret

    def _audit(self, entry: dict) -> None:
        """Append a JSON line to the audit log."""
        entry["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.audit_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, separators=(",", ":")) + "\n")

    def _check_denylist(self, resolved: Path) -> str | None:
        """Return a reason string if the resolved path hits the denylist."""
        for part in resolved.parts:
            if part in _DENYLIST_DIRS:
                return f"Protected directory: path is inside {part}/"
        return None

    def _get_allowed_bases(self, identity: str | None) -> list[Path]:
        """Return the allowed base directories for the given identity."""
        bases: list[Path] = list(_TMP_BASES)
        if identity is None or self._repo_root is None:
            return bases
        if identity == "devpulse":
            bases.append(self._repo_root)
            return bases
        branch_dir = self._resolve_branch_dir(identity)
        if branch_dir and branch_dir.is_dir():
            bases.append(branch_dir)
        return bases

    def _resolve_branch_dir(self, identity: str) -> Path | None:
        """Find a branch directory by name via .trinity/ marker walk."""
        if self._repo_root is None:
            return None
        for root, dirs, _files in os.walk(self._repo_root):
            depth = len(Path(root).relative_to(self._repo_root).parts)
            if depth > 3:
                dirs.clear()
                continue
            if Path(root).name == identity and (Path(root) / ".trinity").is_dir():
                return Path(root).resolve()
        return None

    def _handle_identify(self, req: BrokerRequest) -> tuple[BrokerResponse, str | None]:
        """Verify HMAC and bind identity to the connection."""
        audit_entry: dict = {
            "op": "identify",
            "branch": req.branch,
            "request_id": req.request_id,
        }

        if not req.branch or not req.hmac:
            audit_entry.update(result="REFUSED", reason="missing branch or hmac")
            self._audit(audit_entry)
            return BrokerResponse(
                ok=False,
                message="Missing branch or hmac",
                request_id=req.request_id,
                error_code="IDENTIFY_INVALID",
            ), None

        expected = hmac_mod.new(self._secret, req.branch.encode(), hashlib.sha256).hexdigest()
        if not hmac_mod.compare_digest(expected, req.hmac):
            audit_entry.update(result="REFUSED", reason="bad HMAC")
            self._audit(audit_entry)
            return BrokerResponse(
                ok=False,
                message="Authentication failed",
                request_id=req.request_id,
                error_code="IDENTIFY_FAILED",
            ), None

        audit_entry.update(result="IDENTIFIED", identity=req.branch)
        self._audit(audit_entry)
        logger.info("broker: connection identified as %s", req.branch)
        return BrokerResponse(
            ok=True,
            message=f"Identified as {req.branch}",
            request_id=req.request_id,
        ), req.branch

    def _handle_delete(self, req: BrokerRequest, identity: str | None) -> BrokerResponse:
        """Process a single delete request with full re-resolution and identity scoping."""
        import shutil

        audit_entry: dict = {
            "op": req.op,
            "agent_path": req.path,
            "request_id": req.request_id,
            "identity": identity,
        }

        allowed_bases = self._get_allowed_bases(identity)

        for base in allowed_bases:
            agent_path = req.path
            try:
                candidate = Path(agent_path)
                if candidate.is_absolute() and candidate.is_relative_to(base):
                    agent_path = str(candidate.relative_to(base))
            except (ValueError, TypeError) as exc:
                logger.info("broker: path normalization skipped for %s: %s", agent_path, exc)

            try:
                resolved = resolve_beneath(base, agent_path)
            except OSError as exc:
                logger.info("broker: base %s skipped for %s: %s", base, agent_path, exc)
                continue

            # Prevent /tmp base from granting access to repo-scoped paths
            if self._repo_root and base in _TMP_BASES and resolved.is_relative_to(self._repo_root):
                logger.info("broker: %s is under repo root via /tmp — skipping", resolved)
                continue

            if not resolved.is_relative_to(base):
                continue

            deny_reason = self._check_denylist(resolved)
            if deny_reason:
                audit_entry.update(
                    result="REFUSED",
                    reason=deny_reason,
                    resolved=str(resolved),
                    base=str(base),
                )
                self._audit(audit_entry)
                logger.warning("broker: denied delete %s: %s", resolved, deny_reason)
                deletion_log.record_deletion(
                    lane=deletion_log.LANE_BROKER,
                    outcome=deletion_log.OUTCOME_REFUSED,
                    requested=req.path,
                    resolved=resolved,
                    reason=deny_reason,
                    caller=identity,
                )
                return BrokerResponse(
                    ok=False,
                    message=deny_reason,
                    request_id=req.request_id,
                    error_code="DENYLIST",
                )

            if resolved == base:
                reason = f"Refusing to delete root directory itself: {base}"
                audit_entry.update(
                    result="REFUSED",
                    reason=reason,
                    resolved=str(resolved),
                    base=str(base),
                )
                self._audit(audit_entry)
                deletion_log.record_deletion(
                    lane=deletion_log.LANE_BROKER,
                    outcome=deletion_log.OUTCOME_REFUSED,
                    requested=req.path,
                    resolved=resolved,
                    reason=reason,
                    caller=identity,
                )
                return BrokerResponse(
                    ok=False,
                    message=reason,
                    request_id=req.request_id,
                    error_code="ROOT_DELETE",
                )

            # Before the delete, for the same reason rm measures early: a tree
            # cannot be sized once it is gone.
            measurement = deletion_log.measure(resolved)

            try:
                if resolved.is_symlink():
                    resolved.unlink()
                elif resolved.is_dir():
                    shutil.rmtree(resolved)
                else:
                    resolved.unlink()

                audit_entry.update(result="DELETED", resolved=str(resolved), base=str(base))
                self._audit(audit_entry)
                logger.info(
                    "broker: deleted %s (base=%s, identity=%s)",
                    resolved,
                    base,
                    identity,
                )
                deletion_log.record_deletion(
                    lane=deletion_log.LANE_BROKER,
                    outcome=deletion_log.OUTCOME_DELETED,
                    requested=req.path,
                    resolved=resolved,
                    reason=f"Deleted: {resolved}",
                    measurement=measurement,
                    caller=identity,
                )
                return BrokerResponse(
                    ok=True,
                    message=f"Deleted: {resolved}",
                    request_id=req.request_id,
                )
            except OSError as exc:
                audit_entry.update(
                    result="ERROR",
                    reason=str(exc),
                    resolved=str(resolved),
                    base=str(base),
                )
                self._audit(audit_entry)
                logger.error("broker: delete failed %s: %s", resolved, exc)
                deletion_log.record_deletion(
                    lane=deletion_log.LANE_BROKER,
                    outcome=deletion_log.OUTCOME_FAILED,
                    requested=req.path,
                    resolved=resolved,
                    reason=f"Delete failed: {exc}",
                    measurement=measurement,
                    caller=identity,
                )
                return BrokerResponse(
                    ok=False,
                    message=f"Delete failed: {exc}",
                    request_id=req.request_id,
                    error_code="OS_ERROR",
                )

        audit_entry.update(result="REFUSED", reason="Path not under any allowed base for this identity")
        self._audit(audit_entry)
        logger.warning("broker: no allowed base matched for %s (identity=%s)", req.path, identity)
        deletion_log.record_deletion(
            lane=deletion_log.LANE_BROKER,
            outcome=deletion_log.OUTCOME_REFUSED,
            requested=req.path,
            resolved=req.path,
            reason="Path not under any allowed base for this identity",
            caller=identity,
        )
        return BrokerResponse(
            ok=False,
            message=f"Path not permitted for identity '{identity}': {req.path}",
            request_id=req.request_id,
            error_code="NO_BASE",
        )

    def _handle_connection(self, conn: socket.socket) -> None:
        """Read messages in a loop, tracking per-connection identity."""
        identity: str | None = None
        first_message_done = False
        buffer = b""
        try:
            while True:
                while b"\n" not in buffer:
                    chunk = conn.recv(4096)
                    if not chunk:
                        return
                    buffer += chunk

                line, _, buffer = buffer.partition(b"\n")
                if not line.strip():
                    continue

                req = BrokerRequest.from_bytes(line + b"\n")

                if req.op == "identify":
                    if first_message_done:
                        self._audit(
                            {
                                "op": "identify",
                                "branch": req.branch,
                                "identity": identity,
                                "result": "REFUSED",
                                "reason": "identify after first message",
                                "request_id": req.request_id,
                            }
                        )
                        resp = BrokerResponse(
                            ok=False,
                            message="Identify must be the first message",
                            request_id=req.request_id,
                            error_code="IDENTIFY_LATE",
                        )
                    else:
                        resp, identity = self._handle_identify(req)
                    first_message_done = True
                elif req.op == "delete":
                    first_message_done = True
                    resp = self._handle_delete(req, identity)
                else:
                    first_message_done = True
                    resp = BrokerResponse(
                        ok=False,
                        message=f"Unknown operation: {req.op}",
                        request_id=req.request_id,
                        error_code="UNKNOWN_OP",
                    )

                conn.sendall(resp.to_bytes())
        except Exception as exc:
            logger.error("broker: connection error: %s", exc)
            try:
                err = BrokerResponse(ok=False, message=f"Internal error: {exc}", error_code="INTERNAL")
                conn.sendall(err.to_bytes())
            except OSError as send_exc:
                logger.warning("broker: failed to send error response: %s", send_exc)
        finally:
            conn.close()

    def start(self) -> None:
        """Start the broker daemon (blocking). Use ``start_background`` for threaded."""
        self._secret = self._generate_secret()

        self.socket_path.parent.mkdir(parents=True, exist_ok=True)
        if self.socket_path.exists():
            self.socket_path.unlink()

        self._server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server.bind(str(self.socket_path))
        self._server.listen(5)
        self._server.settimeout(1.0)
        self._running = True
        self._listening.set()

        logger.info("broker: listening on %s", self.socket_path)
        json_handler.log_operation("broker_start", {"socket": str(self.socket_path)})

        while self._running:
            try:
                conn, _ = self._server.accept()
                t = threading.Thread(target=self._handle_connection, args=(conn,), daemon=True)
                t.start()
            except socket.timeout:
                logger.info("broker: accept poll tick")
                continue
            except OSError as exc:
                if self._running:
                    logger.error("broker: accept error: %s", exc)
                break

    def start_background(self, timeout: float = 5.0) -> threading.Thread:
        """Start the broker in a background thread, blocking until listening."""
        self._listening.clear()
        t = threading.Thread(target=self.start, daemon=True, name="drone-broker")
        t.start()
        if not self._listening.wait(timeout):
            raise RuntimeError(f"broker failed to start listening within {timeout}s")
        return t

    def stop(self) -> None:
        """Stop the broker daemon."""
        self._running = False
        if self._server:
            try:
                self._server.close()
            except OSError as exc:
                logger.warning("broker: error closing server socket: %s", exc)
        if self.socket_path.exists():
            try:
                self.socket_path.unlink()
            except OSError as exc:
                logger.warning("broker: error removing socket file: %s", exc)
        logger.info("broker: stopped")
        json_handler.log_operation("broker_stop", {})
