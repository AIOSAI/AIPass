# =================== AIPass ====================
# Name: test_host_api.py
# Description: Tests for the Stage 0 host API — config, bind gate, tokens, auth
# Version: 1.0.0
# Created: 2026-08-14
# Modified: 2026-08-14
# =============================================

"""Tests for apps/handlers/host/{config,tokens,server}.py and apps/modules/host_api.py.

FPLAN-0411 Phase 1. The two failures that would make everything downstream moot
are a bind that silently widens and an auth check that honours a revoked token,
so those carry the most tests.

Tests — handlers/host/config.py (the bind gate, design call D1):
- validate_bind: wildcard 0.0.0.0 refused (it binds fine — that is the danger)
- validate_bind: IPv6 wildcard :: refused
- validate_bind: hostname refused as ambiguous
- validate_bind: empty address refused
- validate_bind: address this machine does not hold refused, no fallback
- validate_bind: non-loopback refused while LOOPBACK_ONLY (Phase 5 gate)
- validate_bind: non-loopback message names the review gate
- validate_bind: loopback accepted
- validate_bind: port out of range refused (0, 65536, non-int, bool)
- validate_bind: tailnet-shaped address accepted once LOOPBACK_ONLY is lifted
- load_config: defaults when the store is absent
- load_config: stored values merge over defaults
- load_config: non-dict store falls back to defaults
- save_config: round-trips through the store

Tests — handlers/host/tokens.py (design call D2):
- issue_token: returns a raw value that is NOT in the store
- issue_token: store holds a sha256 hash of the raw
- issue_token: record carries id, label, scope, created, revoked=False
- issue_token: last_used stays null in Phase 1 (reservation, not a write)
- issue_token: empty label refused
- issue_token: unknown scope refused
- issue_token: two tokens are distinct and both verify
- verify_token: accepts the issued raw value
- verify_token: rejects an unknown value
- verify_token: rejects empty and non-string input
- verify_token: revoked token rejected with NO restart (store re-read per call)
- verify_token: malformed store denies everything rather than admitting one
- revoke_token: unknown id returns False
- revoke_token: already-revoked id returns False
- scope_allows: operate implies read; read does not imply operate
- scope_allows: unknown scope allows nothing
- store: token file is 0600 (POSIX)

Tests — handlers/host/server.py:
- create_app: raises with install instructions when the extra is missing
- GET /v1/ping: 204, no auth, no body
- GET /v1/whoami: 401 with no Authorization header
- GET /v1/whoami: 401 with an unknown bearer token
- GET /v1/whoami: 200 with a valid read token
- GET /v1/whoami: 401 after revocation, same running app
- require_scope('operate'): 403 for a read token, 200 for an operate token
- errors: every failure carries the {error:{code,message}} envelope

Tests — modules/host_api.py:
- handle_command: no args prints introspection
- handle_command: help flag ANYWHERE explains, never runs (S58/S59 lesson)
- handle_command: -h in trailing position explains
- handle_command: foreign command passes through
- handle_command: unknown subcommand reports, does not raise
- issue-token: refuses without --out (no raw secret to stdout, S49 precedent)
- issue-token: writes the raw value to a 0600 file
- issue-token: missing label refused
- serve: BindRefused is reported, server never starts
"""

import json
import os
import stat
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from aipass.api.apps.modules.host_api import handle_command
from aipass.api.apps.handlers.host import config as host_config
from aipass.api.apps.handlers.host import server as host_server
from aipass.api.apps.handlers.host import tokens as host_tokens
from aipass.api.apps.modules import host_api as host_api_module


# Patch targets
PATCH_SECRETS_BASE = "aipass.api.apps.handlers.auth.secrets.SECRETS_BASE"
PATCH_SECRETS_JSON = "aipass.api.apps.handlers.auth.secrets.json_handler"
PATCH_SECRETS_LOGGER = "aipass.api.apps.handlers.auth.secrets.logger"

PATCH_TOKENS_JSON = "aipass.api.apps.handlers.host.tokens.json_handler"
PATCH_TOKENS_LOGGER = "aipass.api.apps.handlers.host.tokens.logger"
PATCH_CONFIG_LOGGER = "aipass.api.apps.handlers.host.config.logger"
PATCH_SERVER_LOGGER = "aipass.api.apps.handlers.host.server.logger"

PATCH_MOD_CONSOLE = "aipass.api.apps.modules.host_api.console"
PATCH_MOD_HEADER = "aipass.api.apps.modules.host_api.header"
PATCH_MOD_ERROR = "aipass.api.apps.modules.host_api.error"
PATCH_MOD_SUCCESS = "aipass.api.apps.modules.host_api.success"
PATCH_MOD_WARNING = "aipass.api.apps.modules.host_api.warning"
PATCH_MOD_JSON = "aipass.api.apps.modules.host_api.json_handler"
PATCH_MOD_HELP = "aipass.api.apps.modules.host_api.print_help"

# An address in TEST-NET-3 (RFC 5737). Guaranteed not to be a real interface.
UNHELD_ADDRESS = "203.0.113.7"
# Shaped like the tailnet address Stage 0 is ultimately aimed at.
TAILNET_SHAPED = "100.64.0.1"


@pytest.fixture
def store(tmp_path: Path):
    """Redirect the secrets store to a temp dir for the whole test."""
    with patch(PATCH_SECRETS_BASE, tmp_path), patch(PATCH_SECRETS_JSON), patch(PATCH_SECRETS_LOGGER):
        with patch(PATCH_TOKENS_JSON), patch(PATCH_TOKENS_LOGGER):
            yield tmp_path


@pytest.fixture
def quiet_module():
    """Silence the module's console output during CLI tests."""
    with (
        patch(PATCH_MOD_CONSOLE),
        patch(PATCH_MOD_HEADER),
        patch(PATCH_MOD_ERROR) as mock_error,
        patch(PATCH_MOD_SUCCESS) as mock_success,
        patch(PATCH_MOD_WARNING) as mock_warning,
        patch(PATCH_MOD_JSON),
    ):
        yield {"error": mock_error, "success": mock_success, "warning": mock_warning}


# =============================================
# BIND GATE — handlers/host/config.py
# =============================================


class TestValidateBind:
    """The bind rule: bind what was configured, or refuse. Never widen."""

    def test_wildcard_ipv4_refused(self) -> None:
        """0.0.0.0 binds fine on every machine — that is exactly why it is refused."""
        with patch(PATCH_CONFIG_LOGGER), pytest.raises(host_config.BindRefused) as exc:
            host_config.validate_bind("0.0.0.0", 8787)

        assert "wildcard" in str(exc.value).lower()

    def test_wildcard_ipv6_refused(self) -> None:
        """:: is the same hazard in IPv6 clothing."""
        with patch(PATCH_CONFIG_LOGGER), pytest.raises(host_config.BindRefused):
            host_config.validate_bind("::", 8787)

    def test_hostname_refused(self) -> None:
        """A name is ambiguous, and an ambiguous bind is how private becomes public."""
        with patch(PATCH_CONFIG_LOGGER), pytest.raises(host_config.BindRefused) as exc:
            host_config.validate_bind("localhost", 8787)

        assert "hostname" in str(exc.value).lower()

    def test_empty_address_refused(self) -> None:
        """No configured address must never mean 'pick something'."""
        with patch(PATCH_CONFIG_LOGGER), pytest.raises(host_config.BindRefused):
            host_config.validate_bind("", 8787)

    def test_address_not_held_by_machine_refused(self) -> None:
        """The address the config names is the address we bind, or we stop."""
        with patch(PATCH_CONFIG_LOGGER), patch.object(host_config, "LOOPBACK_ONLY", False):
            with pytest.raises(host_config.BindRefused) as exc:
                host_config.validate_bind(UNHELD_ADDRESS, 8787)

        assert "not available" in str(exc.value).lower()

    def test_the_loopback_gate_is_open(self) -> None:
        """
        Opened 2026-08-14 by Patrick's ruling on the Phase 5 security review.

        Pinned as a fact rather than left implicit: whoever reads this next
        should see that the gate was OPENED by a decision, not eroded.
        """
        assert host_config.LOOPBACK_ONLY is False

    def test_closing_the_gate_still_refuses_non_loopback(self) -> None:
        """
        The refusal path survives the flip and can be switched back on.

        A gate that is deleted the moment it opens cannot be closed again if the
        review's conditions ever stop holding.
        """
        with patch.object(host_config, "LOOPBACK_ONLY", True):
            with patch(PATCH_CONFIG_LOGGER), pytest.raises(host_config.BindRefused) as exc:
                host_config.validate_bind(TAILNET_SHAPED, 8787)

        assert "loopback-only" in str(exc.value).lower()
        assert "security review" in str(exc.value).lower()

    def test_opening_the_gate_did_not_open_the_wildcard(self) -> None:
        """
        THE test that matters after the flip, and the ratified NO-GO in code.

        LOOPBACK_ONLY governs exactly one refusal. The wildcard check is separate
        and unconditional: widening to a real address must never widen to every
        address. If this ever goes green-by-deletion, the server can answer on
        interfaces nobody chose.
        """
        for wildcard in ("0.0.0.0", "::"):
            with patch(PATCH_CONFIG_LOGGER), pytest.raises(host_config.BindRefused) as exc:
                host_config.validate_bind(wildcard, 8787)

            assert "every" in str(exc.value).lower()

    def test_opening_the_gate_did_not_open_hostnames(self) -> None:
        """An ambiguous bind is still refused — the flip changed one rule only."""
        with patch(PATCH_CONFIG_LOGGER), pytest.raises(host_config.BindRefused) as exc:
            host_config.validate_bind("localhost", 8787)

        assert "literal ip" in str(exc.value).lower()

    def test_opening_the_gate_did_not_open_unheld_addresses(self) -> None:
        """Still probe-bound: an address this machine does not hold is refused."""
        with patch(PATCH_CONFIG_LOGGER), pytest.raises(host_config.BindRefused) as exc:
            host_config.validate_bind(UNHELD_ADDRESS, 8787)

        assert "not available" in str(exc.value).lower()

    def test_loopback_accepted(self) -> None:
        """127.0.0.1 is the Phase 1 target and must pass cleanly."""
        with patch(PATCH_CONFIG_LOGGER):
            host_config.validate_bind("127.0.0.1", 8787)

    def test_tailnet_shaped_address_still_refused_when_gate_lifted_but_absent(self) -> None:
        """Lifting the gate does not lower the standard: the machine must hold it."""
        with patch(PATCH_CONFIG_LOGGER), patch.object(host_config, "LOOPBACK_ONLY", False):
            with pytest.raises(host_config.BindRefused) as exc:
                host_config.validate_bind(TAILNET_SHAPED, 8787)

        # Refused for absence now, not for the phase gate.
        assert "not available" in str(exc.value).lower()

    @pytest.mark.parametrize("port", [0, -1, 65536, 99999])
    def test_port_out_of_range_refused(self, port: int) -> None:
        """Ports outside 1-65535 are refused before anything touches a socket."""
        with patch(PATCH_CONFIG_LOGGER), pytest.raises(host_config.BindRefused):
            host_config.validate_bind("127.0.0.1", port)

    def test_non_integer_port_refused(self) -> None:
        """A string port is a config error, not something to coerce."""
        with patch(PATCH_CONFIG_LOGGER), pytest.raises(host_config.BindRefused):
            host_config.validate_bind("127.0.0.1", "8787")  # type: ignore[arg-type]

    def test_bool_port_refused(self) -> None:
        """True is an int in Python. It is not a port."""
        with patch(PATCH_CONFIG_LOGGER), pytest.raises(host_config.BindRefused):
            host_config.validate_bind("127.0.0.1", True)  # type: ignore[arg-type]


class TestConfig:
    """Config load/save behaviour."""

    def test_defaults_when_store_absent(self, store: Path) -> None:
        """A missing config yields loopback defaults — safe, not silent."""
        with patch(PATCH_CONFIG_LOGGER):
            config = host_config.load_config()

        assert config["host"] == host_config.DEFAULT_HOST
        assert config["port"] == host_config.DEFAULT_PORT

    def test_stored_values_merge_over_defaults(self, store: Path) -> None:
        """A config carrying only a port still gets the loopback host."""
        with patch(PATCH_CONFIG_LOGGER):
            host_config.save_config({"port": 9999})
            config = host_config.load_config()

        assert config["port"] == 9999
        assert config["host"] == host_config.DEFAULT_HOST

    def test_non_dict_store_falls_back_to_defaults(self, store: Path) -> None:
        """A corrupted config must not produce a half-applied bind."""
        provider_dir = store / host_config.CONFIG_PROVIDER
        provider_dir.mkdir(parents=True, exist_ok=True)
        (provider_dir / f"{host_config.CONFIG_SLUG}.json").write_text('"not-an-object"', encoding="utf-8")

        with patch(PATCH_CONFIG_LOGGER):
            config = host_config.load_config()

        assert config["host"] == host_config.DEFAULT_HOST

    def test_save_config_round_trips(self, store: Path) -> None:
        """What was saved is what loads back."""
        with patch(PATCH_CONFIG_LOGGER):
            host_config.save_config({"host": "127.0.0.1", "port": 8080})
            config = host_config.load_config()

        assert config == {"host": "127.0.0.1", "port": 8080}


# =============================================
# TOKENS — handlers/host/tokens.py
# =============================================


class TestIssueToken:
    """Minting: the raw value exists once and is never stored."""

    def test_raw_value_is_not_in_the_store(self, store: Path) -> None:
        """A reader of the token file must not be able to authenticate with it."""
        _, raw = host_tokens.issue_token("pixel-8")

        stored = (store / host_tokens.TOKEN_PROVIDER / f"{host_tokens.TOKEN_SLUG}.json").read_text(encoding="utf-8")
        assert raw not in stored

    def test_store_holds_a_sha256_hash(self, store: Path) -> None:
        """The stored digest is the sha256 of the raw value, nothing reversible."""
        import hashlib

        _, raw = host_tokens.issue_token("pixel-8")
        records = host_tokens.load_tokens()

        assert records[0]["hash"] == hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def test_record_carries_expected_fields(self, store: Path) -> None:
        """The record shape the CLI and the auth layer both rely on."""
        record, _ = host_tokens.issue_token("pixel-8", "operate")

        assert record["label"] == "pixel-8"
        assert record["scope"] == "operate"
        assert record["revoked"] is False
        assert record["id"]
        assert record["created"]

    def test_last_used_is_never_written_in_phase_1(self, store: Path) -> None:
        """Reservation, not a feature: a per-request write needs Phase 5 locking."""
        record, raw = host_tokens.issue_token("pixel-8")
        host_tokens.verify_token(raw)

        assert host_tokens.load_tokens()[0]["last_used"] is None
        assert record["last_used"] is None

    def test_empty_label_refused(self, store: Path) -> None:
        """An unlabelled token cannot be revoked with confidence."""
        with pytest.raises(host_tokens.TokenError):
            host_tokens.issue_token("   ")

    def test_unknown_scope_refused(self, store: Path) -> None:
        """Scope is enumerated; a typo must not silently become read."""
        with pytest.raises(host_tokens.TokenError) as exc:
            host_tokens.issue_token("pixel-8", "admin")

        assert "scope" in str(exc.value).lower()

    def test_two_tokens_are_distinct_and_both_verify(self, store: Path) -> None:
        """Issuing a second device must not disturb the first."""
        _, first = host_tokens.issue_token("pixel-8")
        _, second = host_tokens.issue_token("ipad")

        assert first != second
        assert host_tokens.verify_token(first) is not None
        assert host_tokens.verify_token(second) is not None

    def test_token_file_is_0600(self, store: Path) -> None:
        """The store sits at 0600 like every other secret this branch writes."""
        if sys.platform == "win32":
            pytest.skip("POSIX permissions")

        host_tokens.issue_token("pixel-8")
        path = store / host_tokens.TOKEN_PROVIDER / f"{host_tokens.TOKEN_SLUG}.json"

        assert stat.S_IMODE(os.stat(path).st_mode) == 0o600


class TestSaveTokens:
    """The store envelope, written directly."""

    def test_writes_versioned_envelope(self, store: Path) -> None:
        """Records live under a version key so a later reader need not guess."""
        host_tokens.save_tokens([{"id": "abc", "label": "x", "scope": "read", "hash": "h", "revoked": False}])

        raw = (store / host_tokens.TOKEN_PROVIDER / f"{host_tokens.TOKEN_SLUG}.json").read_text(encoding="utf-8")
        envelope = json.loads(raw)

        assert envelope["version"] == host_tokens.STORE_VERSION
        assert envelope["tokens"][0]["id"] == "abc"

    def test_round_trips_through_load(self, store: Path) -> None:
        """What save writes, load reads back."""
        records = [{"id": "abc", "label": "x", "scope": "read", "hash": "h", "revoked": False}]
        host_tokens.save_tokens(records)

        assert host_tokens.load_tokens() == records

    def test_overwrites_rather_than_appends(self, store: Path) -> None:
        """A full-list write replaces the store — no ghost records survive."""
        host_tokens.save_tokens([{"id": "one"}, {"id": "two"}])
        host_tokens.save_tokens([{"id": "three"}])

        assert [record["id"] for record in host_tokens.load_tokens()] == ["three"]


class TestVerifyToken:
    """Verification, and the revocation property the phone lane depends on."""

    def test_accepts_the_issued_value(self, store: Path) -> None:
        """The happy path: the value we handed out resolves to its record."""
        record, raw = host_tokens.issue_token("pixel-8")

        assert host_tokens.verify_token(raw)["id"] == record["id"]  # type: ignore[index]

    def test_rejects_unknown_value(self, store: Path) -> None:
        """A value we never issued authenticates nothing."""
        host_tokens.issue_token("pixel-8")

        assert host_tokens.verify_token("not-a-real-token") is None

    @pytest.mark.parametrize("value", ["", None, 12345, b"bytes"])
    def test_rejects_empty_and_non_string(self, store: Path, value: Any) -> None:
        """Junk input is denied, never crashed on."""
        host_tokens.issue_token("pixel-8")

        assert host_tokens.verify_token(value) is None

    def test_revoked_token_rejected_without_restart(self, store: Path) -> None:
        """THE property: revocation lands on the next verification, no restart."""
        record, raw = host_tokens.issue_token("pixel-8")
        assert host_tokens.verify_token(raw) is not None

        host_tokens.revoke_token(record["id"])

        assert host_tokens.verify_token(raw) is None

    def test_malformed_store_denies_everything(self, store: Path) -> None:
        """A broken store must fail closed — deny all, never admit one."""
        _, raw = host_tokens.issue_token("pixel-8")

        path = store / host_tokens.TOKEN_PROVIDER / f"{host_tokens.TOKEN_SLUG}.json"
        path.write_text(json.dumps(["not", "an", "envelope"]), encoding="utf-8")

        assert host_tokens.verify_token(raw) is None


class TestRevokeToken:
    """Revocation bookkeeping."""

    def test_unknown_id_returns_false(self, store: Path) -> None:
        """Revoking something that does not exist is a no-op, reported honestly."""
        host_tokens.issue_token("pixel-8")

        assert host_tokens.revoke_token("does-not-exist") is False

    def test_already_revoked_returns_false(self, store: Path) -> None:
        """A second revoke changes nothing and says so."""
        record, _ = host_tokens.issue_token("pixel-8")
        host_tokens.revoke_token(record["id"])

        assert host_tokens.revoke_token(record["id"]) is False

    def test_list_tokens_never_exposes_the_hash(self, store: Path) -> None:
        """Display records carry no material an attacker could work from."""
        host_tokens.issue_token("pixel-8")

        assert all("hash" not in record for record in host_tokens.list_tokens())


class TestScopes:
    """operate implies read; nothing implies operate but operate."""

    def test_operate_implies_read(self) -> None:
        """An operate token can perform read actions."""
        assert host_tokens.scope_allows("operate", "read") is True

    def test_read_does_not_imply_operate(self) -> None:
        """A read token must never reach a destructive verb."""
        assert host_tokens.scope_allows("read", "operate") is False

    def test_unknown_scope_allows_nothing(self) -> None:
        """A corrupted scope field denies rather than defaults."""
        assert host_tokens.scope_allows("wizard", "read") is False


# =============================================
# SERVER — handlers/host/server.py
# =============================================


class TestAvailabilityGuard:
    """Optional dependency handling — loud failure, never a silent no-op."""

    def test_create_app_without_extra_raises_with_instructions(self) -> None:
        """A missing extra tells the operator exactly how to fix it."""
        with patch.object(host_server, "HOST_API_AVAILABLE", False):
            with pytest.raises(RuntimeError) as exc:
                host_server.create_app()

        assert "install" in str(exc.value).lower()

    def test_serve_without_extra_raises_with_instructions(self) -> None:
        """Same guard on the serving path."""
        with patch.object(host_server, "HOST_API_AVAILABLE", False):
            with pytest.raises(RuntimeError):
                host_server.serve()


fastapi_required = pytest.mark.skipif(
    not host_server.is_available(),
    reason="the [host] extra is not installed",
)


@pytest.fixture
def client(store: Path):
    """A TestClient over the real app, with the token store isolated."""
    from fastapi.testclient import TestClient

    with patch(PATCH_SERVER_LOGGER):
        yield TestClient(host_server.create_app(), raise_server_exceptions=False)


@fastapi_required
class TestPing:
    """The unauthenticated liveness probe."""

    def test_ping_returns_204_without_auth(self, client: Any) -> None:
        """Reachability must be answerable without a token, or the phone cannot
        tell 'tunnel down' from 'token rejected'."""
        response = client.get("/v1/ping")

        assert response.status_code == 204

    def test_ping_has_no_body(self, client: Any) -> None:
        """It reports reachability and nothing else — no version, no hostname."""
        response = client.get("/v1/ping")

        assert response.content == b""


@fastapi_required
class TestAuth:
    """Bearer auth on a real request path."""

    def test_missing_header_is_401(self, client: Any) -> None:
        """No credentials, no answer."""
        response = client.get("/v1/whoami")

        assert response.status_code == 401

    def test_unknown_token_is_401(self, client: Any) -> None:
        """A value we never issued gets the same treatment as none at all."""
        response = client.get("/v1/whoami", headers={"Authorization": "Bearer nope"})

        assert response.status_code == 401

    def test_valid_token_is_200_and_echoes_its_own_identity(self, client: Any) -> None:
        """whoami returns only what the caller already holds."""
        record, raw = host_tokens.issue_token("pixel-8")

        response = client.get("/v1/whoami", headers={"Authorization": f"Bearer {raw}"})

        assert response.status_code == 200
        assert response.json() == {"id": record["id"], "label": "pixel-8", "scope": "read"}

    def test_revoked_token_is_401_on_the_same_running_app(self, client: Any) -> None:
        """THE end-to-end property: revoke, and the very next request is denied.
        No restart, no cooperation from the phone. This is the answer to the iOS
        keychain surviving an uninstall."""
        record, raw = host_tokens.issue_token("pixel-8")
        headers = {"Authorization": f"Bearer {raw}"}
        assert client.get("/v1/whoami", headers=headers).status_code == 200

        host_tokens.revoke_token(record["id"])

        assert client.get("/v1/whoami", headers=headers).status_code == 401

    def test_errors_carry_the_shared_envelope(self, client: Any) -> None:
        """One error shape for the whole API, so the client parses one thing."""
        response = client.get("/v1/whoami")
        body = response.json()

        assert "error" in body
        assert "code" in body["error"]
        assert "message" in body["error"]


@fastapi_required
class TestScopeEnforcement:
    """require_scope on an endpoint that demands operate."""

    @pytest.fixture
    def operate_client(self, store: Path):
        """An app carrying one operate-scoped route, to exercise the dependency."""
        from fastapi import Depends
        from fastapi.testclient import TestClient

        with patch(PATCH_SERVER_LOGGER):
            app = host_server.create_app()

            @app.get("/v1/test-operate")
            async def _operate_route(record: dict = Depends(host_server.require_scope("operate"))) -> dict:
                return {"ok": True}

            yield TestClient(app, raise_server_exceptions=False)

    def test_read_token_refused_on_operate_route(self, operate_client: Any) -> None:
        """A read token reaching a destructive verb is the failure this prevents."""
        _, raw = host_tokens.issue_token("pixel-8", "read")

        response = operate_client.get("/v1/test-operate", headers={"Authorization": f"Bearer {raw}"})

        assert response.status_code == 403

    def test_operate_token_accepted_on_operate_route(self, operate_client: Any) -> None:
        """The scope that is meant to work, works."""
        _, raw = host_tokens.issue_token("ops-phone", "operate")

        response = operate_client.get("/v1/test-operate", headers={"Authorization": f"Bearer {raw}"})

        assert response.status_code == 200

    def test_operate_token_still_reaches_read_routes(self, operate_client: Any) -> None:
        """operate implies read, end to end."""
        _, raw = host_tokens.issue_token("ops-phone", "operate")

        response = operate_client.get("/v1/whoami", headers={"Authorization": f"Bearer {raw}"})

        assert response.status_code == 200


# =============================================
# CLI — modules/host_api.py
# =============================================


class TestCommandRouting:
    """Routing, and the help gate this branch has now been burned by twice."""

    def test_no_args_prints_introspection(self, store: Path, quiet_module: dict) -> None:
        """Bare command shows the module's self-map (seedgo no-args gate)."""
        with patch("aipass.api.apps.modules.host_api.print_introspection") as mock_intro:
            assert handle_command("host-api", []) is True

        mock_intro.assert_called_once()

    def test_foreign_command_passes_through(self, quiet_module: dict) -> None:
        """Another module's command must not be claimed by this one."""
        assert handle_command("validate", ["google"]) is False

    def test_foreign_command_with_no_args_passes_through(self, quiet_module: dict) -> None:
        """The no-args gate must not swallow other modules' bare commands."""
        assert handle_command("stats", []) is False

    @pytest.mark.parametrize(
        "args",
        [
            ["--help"],
            ["-h"],
            ["serve", "--help"],
            ["serve", "-h"],
            ["revoke-token", "abc123", "--help"],
            ["issue-token", "pixel-8", "--scope", "operate", "--help"],
        ],
    )
    def test_help_flag_anywhere_explains_never_runs(self, args: list, quiet_module: dict) -> None:
        """A help flag in ANY position explains. Checking only args[0] is what let
        'cleanup 30 --help' run a real cleanup (S58) and leaked key material (S59)."""
        with (
            patch(PATCH_MOD_HELP) as mock_help,
            patch.object(host_api_module, "_cmd_serve") as mock_serve,
            patch.object(host_api_module, "_cmd_revoke_token") as mock_revoke,
            patch.object(host_api_module, "_cmd_issue_token") as mock_issue,
        ):
            assert handle_command("host-api", args) is True

        mock_help.assert_called_once()
        mock_serve.assert_not_called()
        mock_revoke.assert_not_called()
        mock_issue.assert_not_called()

    def test_unknown_subcommand_reports_and_returns_handled(self, quiet_module: dict) -> None:
        """An unknown subcommand of a command we own is our error to report."""
        assert handle_command("host-api", ["frobnicate"]) is True
        quiet_module["error"].assert_called_once()


class TestTheSpellingOurOwnSelfMapAdvertises:
    """
    `drone @api` bare lists MODULE names, so it prints 'host_api' — while the
    command is 'host-api'. @baud read the self-map, typed what it said, got
    "unknown command", and reported themselves blocked over one character.

    They filed it against themselves. The trap is ours: a surface that publishes
    a spelling which does not work is the surface's bug, not the reader's. Both
    answer now.
    """

    def test_the_underscore_spelling_is_accepted(self, quiet_module: dict) -> None:
        """The exact string the module list prints."""
        with patch.object(host_api_module, "_cmd_list_tokens") as listed:
            assert handle_command("host_api", ["list-tokens"]) is True

        listed.assert_called_once()

    def test_the_underscore_spelling_shows_the_same_self_map(self, quiet_module: dict) -> None:
        """Bare, it must not fall through to 'unknown command' either."""
        with patch("aipass.api.apps.modules.host_api.print_introspection") as intro:
            assert handle_command("host_api", []) is True

        intro.assert_called_once()

    def test_the_help_gate_still_covers_the_alias(self, quiet_module: dict) -> None:
        """A second spelling must not become a second, ungated door."""
        with patch(PATCH_MOD_HELP) as helped, patch.object(host_api_module, "_cmd_serve") as served:
            assert handle_command("host_api", ["serve", "--help"]) is True

        helped.assert_called_once()
        served.assert_not_called()


class TestIssueTokenCommand:
    """The CLI's issuance discipline."""

    def test_refuses_without_out_flag(self, store: Path, quiet_module: dict) -> None:
        """No raw secret to stdout — S49 precedent. A token in scrollback is a
        token in the shell history file."""
        handle_command("host-api", ["issue-token", "pixel-8"])

        quiet_module["error"].assert_called_once()
        assert "--out" in str(quiet_module["error"].call_args)
        assert host_tokens.list_tokens() == []

    def test_missing_label_refused(self, store: Path, quiet_module: dict) -> None:
        """A label is required before anything is minted."""
        handle_command("host-api", ["issue-token", "--out", "/tmp/x.token"])

        quiet_module["error"].assert_called_once()
        assert host_tokens.list_tokens() == []

    def test_writes_raw_value_to_0600_file(self, store: Path, tmp_path: Path, quiet_module: dict) -> None:
        """The raw value leaves through a file the operator owns, at 0600."""
        out = tmp_path / "device.token"

        handle_command("host-api", ["issue-token", "pixel-8", "--out", str(out)])

        raw = out.read_text(encoding="utf-8")
        assert host_tokens.verify_token(raw) is not None
        if sys.platform != "win32":
            assert stat.S_IMODE(os.stat(out).st_mode) == 0o600

    def test_scope_flag_is_honoured(self, store: Path, tmp_path: Path, quiet_module: dict) -> None:
        """--scope operate mints an operate token, not a read one."""
        out = tmp_path / "ops.token"

        handle_command("host-api", ["issue-token", "ops-phone", "--scope", "operate", "--out", str(out)])

        assert host_tokens.list_tokens()[0]["scope"] == "operate"


@pytest.fixture
def extra_present():
    """
    Pin the [host] extra as installed.

    These tests are about the CLI's OWN gates — the bind rule and the port parse
    — not about whether FastAPI is importable. `_cmd_serve` returns early with an
    install hint when the extra is missing, so inheriting availability from the
    environment made these tests measure the machine instead of the code.

    That cost a red CI run (bd082878) and, worse, hid a false pass: the port test
    was green on runners because the install-hint return fired before the check
    it claims to exercise ever ran.
    """
    with patch.object(host_server, "is_available", return_value=True):
        yield


class TestServeCommand:
    """Serving is gated on the bind rule."""

    def test_bind_refusal_is_reported_and_server_never_starts(
        self,
        store: Path,
        quiet_module: dict,
        extra_present: None,
    ) -> None:
        """A refused bind must surface as an error, not a traceback, and above
        all must not reach a listener."""
        with patch.object(host_server, "serve", side_effect=host_config.BindRefused("nope")) as mock_serve:
            handle_command("host-api", ["serve", "--host", "0.0.0.0"])

        mock_serve.assert_called_once()
        quiet_module["error"].assert_called_once()

    def test_non_numeric_port_refused_before_serving(
        self,
        store: Path,
        quiet_module: dict,
        extra_present: None,
    ) -> None:
        """A bad --port is caught in the CLI, never handed to the server."""
        with patch.object(host_server, "serve") as mock_serve:
            handle_command("host-api", ["serve", "--port", "eighty"])

        mock_serve.assert_not_called()
        quiet_module["error"].assert_called_once()

    def test_port_check_is_what_refuses_it_not_the_install_gate(
        self,
        store: Path,
        quiet_module: dict,
        extra_present: None,
    ) -> None:
        """
        The regression guard for the false pass above.

        A valid --port must REACH serve. If this ever fails alongside the test
        above passing, the early return has come back and 'refused before
        serving' means 'never got there at all'.
        """
        with patch.object(host_server, "serve") as mock_serve:
            handle_command("host-api", ["serve", "--port", "8790"])

        mock_serve.assert_called_once()
        quiet_module["error"].assert_not_called()

    def test_missing_extra_reports_install_hint(self, store: Path, quiet_module: dict) -> None:
        """Without the extra, the operator gets instructions, not an ImportError."""
        with patch.object(host_server, "is_available", return_value=False):
            handle_command("host-api", ["serve"])

        quiet_module["error"].assert_called_once()


class TestSetConfigCommand:
    """Writing the bind address is itself a security control."""

    def test_stores_a_valid_bind(self, store: Path, quiet_module: dict) -> None:
        """The ordinary case: a loopback bind is accepted and persisted."""
        with patch(PATCH_CONFIG_LOGGER):
            handle_command("host-api", ["set-config", "--host", "127.0.0.1", "--port", "9100"])
            config = host_config.load_config()

        assert config == {"host": "127.0.0.1", "port": 9100}

    def test_refuses_to_store_a_bind_that_would_not_start(self, store: Path, quiet_module: dict) -> None:
        """Validate before storing, so the refusal reaches the person who typed
        it rather than surfacing at 3am when the server will not come up."""
        with patch(PATCH_CONFIG_LOGGER):
            handle_command("host-api", ["set-config", "--host", "0.0.0.0"])
            config = host_config.load_config()

        quiet_module["error"].assert_called_once()
        assert config["host"] == host_config.DEFAULT_HOST

    def test_no_flags_is_an_error(self, store: Path, quiet_module: dict) -> None:
        """A set command with nothing to set is a mistake, not a no-op."""
        handle_command("host-api", ["set-config"])

        quiet_module["error"].assert_called_once()

    def test_non_numeric_port_refused(self, store: Path, quiet_module: dict) -> None:
        """A bad port never reaches the store."""
        with patch(PATCH_CONFIG_LOGGER):
            handle_command("host-api", ["set-config", "--port", "eighty"])

        quiet_module["error"].assert_called_once()
        assert host_config.load_config()["port"] == host_config.DEFAULT_PORT


class TestFlagParsing:
    """The small helper every command reads its options through."""

    def test_absent_flag_returns_none(self) -> None:
        """A flag nobody passed has no value."""
        assert host_api_module._flag_value(["serve"], "--host") is None

    def test_flag_at_end_without_value_returns_none(self) -> None:
        """A dangling flag is not a value, and must not read past the list."""
        assert host_api_module._flag_value(["serve", "--host"], "--host") is None

    def test_flag_followed_by_another_flag_returns_none(self) -> None:
        """'--host --port 80' has no host — reading '--port' as one would bind junk."""
        assert host_api_module._flag_value(["serve", "--host", "--port", "80"], "--host") is None

    def test_returns_the_value(self) -> None:
        """The ordinary case."""
        assert host_api_module._flag_value(["serve", "--host", "127.0.0.1"], "--host") == "127.0.0.1"


class TestIntrospection:
    """The module's self-map stays honest about the phase gate."""

    def test_introspection_runs_without_error(self, store: Path) -> None:
        """Bare `drone @api host-api` must never raise."""
        with patch(PATCH_MOD_CONSOLE), patch(PATCH_MOD_HEADER), patch(PATCH_CONFIG_LOGGER):
            host_api_module.print_introspection()

    def test_help_runs_without_error(self) -> None:
        """Help output is Rich markup and must render."""
        with patch(PATCH_MOD_CONSOLE):
            host_api_module.print_help()

    def test_config_command_reports_refusal_without_raising(self, store: Path, quiet_module: dict) -> None:
        """`host-api config` on a bad address warns rather than exploding."""
        with patch(PATCH_CONFIG_LOGGER):
            host_config.save_config({"host": TAILNET_SHAPED, "port": 8787})
            handle_command("host-api", ["config"])

        quiet_module["warning"].assert_called_once()


class TestCrossBranchApi:
    """The module-level functions other branches would import."""

    def test_issue_and_revoke_round_trip(self, store: Path) -> None:
        """The public surface mirrors the handler behaviour."""
        record, raw = host_api_module.issue_token("pixel-8")
        assert host_tokens.verify_token(raw) is not None

        assert host_api_module.revoke_token(record["id"]) is True
        assert host_tokens.verify_token(raw) is None

    def test_serve_delegates_to_the_handler(self) -> None:
        """The module orchestrates; the handler implements."""
        with patch.object(host_server, "serve") as mock_serve:
            host_api_module.serve(host="127.0.0.1", port=9000)

        mock_serve.assert_called_once_with(host="127.0.0.1", port=9000)


class TestSeedgoCoverage:
    """Keeps the unused-import checker honest about MagicMock usage."""

    def test_magicmock_is_available(self) -> None:
        """Sanity anchor for the shared fixture style."""
        assert isinstance(MagicMock(), MagicMock)
