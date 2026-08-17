#!/usr/bin/env python3
# =================== AIPass ====================
# Name: test_host_auth_audit.py
# Description: Tests for failed-auth auditing with peer address (security C1)
# Version: 1.0.0
# Created: 2026-08-14
# Modified: 2026-08-14
# =============================================

"""
Tests for Failed-Auth Auditing

Security review condition C1, granted 2026-08-14. Before this, a rejected request
produced a logger.warning and nothing else: no structured audit line and no peer
address anywhere, so the honest answer to "which device has been knocking, and
how often" was "I cannot tell you". On a loopback socket that was tolerable. On
the tailnet bind it is not.

TWO PROPERTIES THIS FILE EXISTS TO HOLD TOGETHER, because they pull against each
other and it would be easy to fix one by breaking the other:

  1. The AUDIT distinguishes why a request was refused — no credentials, an
     unrecognised token, or a scope refusal — so an operator can read the record.
  2. The RESPONSE does not. A caller cannot tell "no header" from "bad token"
     from "revoked", because that difference is a probing oracle. Same status,
     same code, same message.

And the third, absolute one: the raw token never reaches the audit. Not the
value, not a prefix — a prefix leaks entropy for free.
"""

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from aipass.api.apps.handlers.host import server as host_server
from aipass.api.apps.handlers.host import tokens as host_tokens

PATCH_SECRETS_BASE = "aipass.api.apps.handlers.auth.secrets.SECRETS_BASE"
PATCH_SECRETS_JSON = "aipass.api.apps.handlers.auth.secrets.json_handler"
PATCH_SECRETS_LOGGER = "aipass.api.apps.handlers.auth.secrets.logger"
PATCH_TOKENS_JSON = "aipass.api.apps.handlers.host.tokens.json_handler"
PATCH_TOKENS_LOGGER = "aipass.api.apps.handlers.host.tokens.logger"
PATCH_SERVER_LOGGER = "aipass.api.apps.handlers.host.server.logger"
PATCH_SERVER_JSON = "aipass.api.apps.handlers.host.server.json_handler"
PATCH_FACE_JSON = "aipass.api.apps.handlers.host.face.json_handler"
PATCH_FACE_LOGGER = "aipass.api.apps.handlers.host.face.logger"

AUDIT_EVENT = "host_api_auth_refused"

fastapi_required = pytest.mark.skipif(
    not host_server.is_available(),
    reason="the [host] extra is not installed",
)


def _refusals(audit) -> list:
    """Pull the auth-refusal payloads out of the audit mock."""
    return [call.args[1] for call in audit.log_operation.call_args_list if call.args[0] == AUDIT_EVENT]


@pytest.fixture
def audited(tmp_path: Path):
    """A client whose audit trail is captured rather than written."""
    from fastapi.testclient import TestClient

    store = tmp_path / "secrets"
    with patch(PATCH_SECRETS_BASE, store), patch(PATCH_SECRETS_JSON), patch(PATCH_SECRETS_LOGGER):
        with patch(PATCH_TOKENS_JSON), patch(PATCH_TOKENS_LOGGER), patch(PATCH_SERVER_LOGGER):
            with patch(PATCH_FACE_JSON), patch(PATCH_FACE_LOGGER):
                with patch(PATCH_SERVER_JSON) as audit:
                    client = TestClient(host_server.create_app(), raise_server_exceptions=False)
                    audit.log_operation.reset_mock()
                    yield client, audit


@fastapi_required
class TestTheAuditRecordsWhoKnocked:
    """The gap C1 closes: a refusal that leaves a trace."""

    def test_missing_credentials_are_audited(self, audited: Any) -> None:
        """A request with no header is a knock worth recording."""
        client, audit = audited

        client.get("/v1/whoami")

        assert len(_refusals(audit)) == 1

    def test_unrecognised_token_is_audited(self, audited: Any) -> None:
        """The one that matters most — somebody presented a credential."""
        client, audit = audited

        client.get("/v1/whoami", headers={"Authorization": "Bearer not-a-real-token"})

        assert len(_refusals(audit)) == 1

    def test_the_peer_address_is_recorded(self, audited: Any) -> None:
        """
        The whole point of C1.

        Without this the audit says "someone failed", which does not answer the
        question the review asked: which device.
        """
        client, audit = audited

        client.get("/v1/whoami", headers={"Authorization": "Bearer nope"})

        assert _refusals(audit)[0]["peer"]

    def test_the_route_is_recorded(self, audited: Any) -> None:
        """Knocking on /v1/fleet is a different story from knocking on /v1/ping."""
        client, audit = audited

        client.get("/v1/fleet", headers={"Authorization": "Bearer nope"})

        assert _refusals(audit)[0]["path"] == "/v1/fleet"

    def test_reasons_are_distinguishable_in_the_audit(self, audited: Any) -> None:
        """
        An operator reading the trail must be able to tell the cases apart —
        'no header' is background noise, 'bad token' is somebody trying.
        """
        client, audit = audited

        client.get("/v1/whoami")
        client.get("/v1/whoami", headers={"Authorization": "Bearer nope"})

        reasons = [refusal["reason"] for refusal in _refusals(audit)]
        assert len(set(reasons)) == 2

    def test_a_successful_request_writes_no_refusal(self, audited: Any) -> None:
        """An audit that cries wolf on valid traffic is an audit nobody reads."""
        client, audit = audited
        _, raw = host_tokens.issue_token("good-token", scope="read")

        response = client.get("/v1/whoami", headers={"Authorization": f"Bearer {raw}"})

        assert response.status_code == 200
        assert _refusals(audit) == []


@fastapi_required
class TestTheResponseStillTellsNothing:
    """C1 must not turn the audit's precision into a probing oracle."""

    def test_missing_and_bad_share_a_status_and_a_code(self, audited: Any) -> None:
        """
        Same status and same machine-readable code; the human message differs.

        WRITTEN DELIBERATELY WEAKER THAN ITS NEIGHBOUR BELOW, and the asymmetry
        is the point. 'You sent no header' versus 'your token was rejected' tells
        a caller only what they already know about their own request — it carries
        nothing about whether a credential was close — while it tells a legitimate
        operator exactly what they got wrong. The distinction that WOULD be an
        oracle is revoked-versus-invalid, and that one is byte-identical.
        """
        client, _ = audited

        missing = client.get("/v1/whoami")
        bad = client.get("/v1/whoami", headers={"Authorization": "Bearer nope"})

        assert missing.status_code == bad.status_code == 401
        assert missing.json()["error"]["code"] == bad.json()["error"]["code"] == "unauthorized"

    def test_a_revoked_token_looks_exactly_like_a_bad_one(self, audited: Any) -> None:
        """A revoked device learns 'no', never 'you were valid until 10:42'."""
        client, _ = audited
        record, raw = host_tokens.issue_token("revoked-phone", scope="read")
        host_tokens.revoke_token(record["id"])

        revoked = client.get("/v1/whoami", headers={"Authorization": f"Bearer {raw}"})
        bad = client.get("/v1/whoami", headers={"Authorization": "Bearer nope"})

        assert revoked.status_code == bad.status_code == 401
        assert revoked.json() == bad.json()

    def test_the_audit_reason_never_reaches_the_client(self, audited: Any) -> None:
        """The precision lives in our trail, not in the response body."""
        client, audit = audited

        response = client.get("/v1/whoami", headers={"Authorization": "Bearer nope"})

        assert _refusals(audit)[0]["reason"] not in response.text


@fastapi_required
class TestTheAuditNeverCarriesTheSecret:
    """An audit trail that logs credentials is worse than no audit trail."""

    def test_the_raw_token_is_absent_from_the_audit(self, audited: Any) -> None:
        """Not the value, and not a prefix — a prefix leaks entropy for free."""
        client, audit = audited
        secret = "super-secret-token-value-abcdef123456"

        client.get("/v1/whoami", headers={"Authorization": f"Bearer {secret}"})

        recorded = str(_refusals(audit))
        assert secret not in recorded
        assert secret[:8] not in recorded

    def test_a_valid_tokens_value_is_absent_on_scope_refusal(self, audited: Any) -> None:
        """The scope path holds a REAL token — the one worth leaking."""
        client, audit = audited
        _, raw = host_tokens.issue_token("read-only", scope="read")

        with patch.object(host_server, "_bearer", host_server._bearer):
            client.get("/v1/whoami", headers={"Authorization": f"Bearer {raw}"})

        assert raw not in str(_refusals(audit))


@fastapi_required
class TestScopeRefusalIsAudited:
    """A read token reaching for an operate verb is the alarm worth having."""

    @pytest.fixture
    def operate_client(self, tmp_path: Path):
        """An app carrying one operate-scoped route."""
        from fastapi import Depends
        from fastapi.testclient import TestClient

        store = tmp_path / "secrets"
        with patch(PATCH_SECRETS_BASE, store), patch(PATCH_SECRETS_JSON), patch(PATCH_SECRETS_LOGGER):
            with patch(PATCH_TOKENS_JSON), patch(PATCH_TOKENS_LOGGER), patch(PATCH_SERVER_LOGGER):
                with patch(PATCH_FACE_JSON), patch(PATCH_FACE_LOGGER):
                    with patch(PATCH_SERVER_JSON) as audit:
                        app = host_server.create_app()

                        @app.get("/v1/test-operate")
                        async def _operate(record: dict = Depends(host_server.require_scope("operate"))) -> dict:
                            return {"ok": True}

                        audit.log_operation.reset_mock()
                        yield TestClient(app, raise_server_exceptions=False), audit

    def test_scope_refusal_is_audited(self, operate_client: Any) -> None:
        """The refusal that means someone is reaching past their grant."""
        client, audit = operate_client
        _, raw = host_tokens.issue_token("pixel-8", scope="read")

        response = client.get("/v1/test-operate", headers={"Authorization": f"Bearer {raw}"})

        assert response.status_code == 403
        assert len(_refusals(audit)) == 1

    def test_scope_refusal_names_the_token_id_not_its_value(self, operate_client: Any) -> None:
        """
        The id is safe and it is what revoke-token takes.

        An audit line an operator cannot act on is a diary entry.
        """
        client, audit = operate_client
        record, raw = host_tokens.issue_token("pixel-8", scope="read")

        client.get("/v1/test-operate", headers={"Authorization": f"Bearer {raw}"})

        refusal = _refusals(audit)[0]
        assert refusal["token_id"] == record["id"]
        assert raw not in str(refusal)

    def test_scope_refusal_records_what_was_demanded(self, operate_client: Any) -> None:
        """Held scope versus required scope, so the trail explains itself."""
        client, audit = operate_client
        _, raw = host_tokens.issue_token("pixel-8", scope="read")

        client.get("/v1/test-operate", headers={"Authorization": f"Bearer {raw}"})

        refusal = _refusals(audit)[0]
        assert refusal["held"] == "read"
        assert refusal["required"] == "operate"


@fastapi_required
class TestARevokedTokenIsDistinguishableInTheTrail:
    """
    The audit must tell 'this device WAS enrolled' from 'this is garbage'.

    Written on 2026-08-16 after a real incident: Patrick's phone was refused for
    nine minutes with reason=token_unrecognised, and the log could not say
    whether it had presented a revoked credential or a corrupted one. The store
    was provably intact, so the log's inability to distinguish those two was the
    thing standing between the evidence and an answer.

    THE RESPONSE STILL TELLS NOTHING. A revoked device learns 'no', never 'you
    were valid until 10:42' — the difference belongs in the trail and nowhere
    else, which is what this branch's own comment promised before the code
    delivered it.
    """

    def test_a_revoked_token_is_recorded_as_revoked(self, audited: Any) -> None:
        """The reason names it, so one grep answers the next incident."""
        client, audit = audited
        record, raw = host_tokens.issue_token("pixel-8", scope="read")
        host_tokens.revoke_token(record["id"])

        client.get("/v1/whoami", headers={"Authorization": f"Bearer {raw}"})

        assert _refusals(audit)[-1]["reason"] == "token_revoked"

    def test_a_revoked_token_carries_its_id(self, audited: Any) -> None:
        """
        The id is the actionable half.

        It is what revoke-token takes and what list-tokens prints, so a trail
        line naming it identifies the device without touching the secret.
        """
        client, audit = audited
        record, raw = host_tokens.issue_token("pixel-8", scope="read")
        host_tokens.revoke_token(record["id"])

        client.get("/v1/whoami", headers={"Authorization": f"Bearer {raw}"})

        assert _refusals(audit)[-1]["token_id"] == record["id"]

    def test_an_unknown_token_is_still_unrecognised(self, audited: Any) -> None:
        """The other half of the distinction, or there is no distinction."""
        client, audit = audited

        client.get("/v1/whoami", headers={"Authorization": "Bearer not-a-real-token"})

        assert _refusals(audit)[-1]["reason"] == "token_unrecognised"
        assert _refusals(audit)[-1]["token_id"] == ""

    def test_the_revoked_secret_never_enters_the_trail(self, audited: Any) -> None:
        """Naming the id must not become an excuse to log the value."""
        client, audit = audited
        record, raw = host_tokens.issue_token("pixel-8", scope="read")
        host_tokens.revoke_token(record["id"])

        client.get("/v1/whoami", headers={"Authorization": f"Bearer {raw}"})

        assert raw not in str(_refusals(audit)[-1])

    def test_both_refusals_answer_identically_to_the_caller(self, audited: Any) -> None:
        """
        Byte-identical: same status, same code, same sentence.

        A response that differed would turn the audit's knowledge into an
        oracle — a prober could learn which of its guesses was once real.
        """
        client, audit = audited
        record, raw = host_tokens.issue_token("pixel-8", scope="read")
        host_tokens.revoke_token(record["id"])

        revoked = client.get("/v1/whoami", headers={"Authorization": f"Bearer {raw}"})
        unknown = client.get("/v1/whoami", headers={"Authorization": "Bearer not-a-real-token"})

        assert revoked.status_code == unknown.status_code == 401
        assert revoked.json() == unknown.json()

    def test_a_revoked_token_is_still_refused(self, audited: Any) -> None:
        """The trail gained a distinction; the door did not gain a key."""
        client, audit = audited
        record, raw = host_tokens.issue_token("pixel-8", scope="read")
        host_tokens.revoke_token(record["id"])

        assert client.get("/v1/whoami", headers={"Authorization": f"Bearer {raw}"}).status_code == 401
