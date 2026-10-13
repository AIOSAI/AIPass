# =================== AIPass ====================
# Name: test_host_pairing.py
# Description: Tests for the pairing door — one-use QR codes a phone trades for its bearer
# Version: 1.0.0
# Created: 2026-10-13
# Modified: 2026-10-13
# =============================================

"""Tests for apps/handlers/host/pairings.py, POST /v1/pair and the host-api pair verb."""

# A file of its own, permitted by @devpulse for DPLAN-0406's leg: the pairing
# store, its route and its verb are one behaviour (the token's hop to the phone)
# that test_host_api.py's commands and test_host_api_routes.py's auth do not own.
# Every test runs on the conftest `store` fixture: the secrets base is tmp_path.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(external) — segno's QR encoding itself; render_qr is pinned to its block characters only
# seedgo: no-test-needed(constant) — ATTEMPT_LIMIT, ATTEMPT_WINDOW_SECONDS and the TTL bounds' values

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from aipass.api.apps.handlers.host import config as host_config
from aipass.api.apps.handlers.host import pairings as host_pairings
from aipass.api.apps.handlers.host import server as host_server
from aipass.api.apps.handlers.host import tokens as host_tokens
from aipass.api.apps.modules import host_api as host_api_module
from aipass.api.apps.modules.host_api import handle_command
from aipass.api.tests.support_host_api import TAILNET_SHAPED

PATCH_CONFIG_LOGGER = "aipass.api.apps.handlers.host.config.logger"
PATCH_PAIRINGS_LOGGER = "aipass.api.apps.handlers.host.pairings.logger"
PATCH_SERVER_LOGGER = "aipass.api.apps.handlers.host.server.logger"

fastapi_required = pytest.mark.skipif(not host_server.is_available(), reason="the [host] extra is not installed")


@pytest.fixture
def paired(store: Path) -> Any:
    """A token store in tmp_path, a tailnet-shaped bind stored beside it, quiet logs."""
    with patch(PATCH_CONFIG_LOGGER), patch(PATCH_PAIRINGS_LOGGER):
        host_config.save_config({"host": TAILNET_SHAPED, "port": 8787})
        yield store


def _stored_rows() -> list:
    return json.loads(host_pairings.store_path().read_text(encoding="utf-8"))["pairings"]


def _expire_every_row() -> None:
    """Move every stored row's expiry an hour into the past: the clock's edge, set in the store."""
    document = json.loads(host_pairings.store_path().read_text(encoding="utf-8"))
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    for row in document["pairings"]:
        row["expires"] = past
    host_pairings.store_path().write_text(json.dumps(document), encoding="utf-8")


class TestMintPairing:
    def test_mint_stores_the_codes_hash_and_never_the_code(self, paired: Path) -> None:
        minted = host_api_module.mint_pairing("phone", "operate")

        stored = host_pairings.store_path().read_text(encoding="utf-8")
        assert minted["code"] not in stored
        [row] = _stored_rows()
        assert row["id"] == minted["id"]
        assert (row["label"], row["scope"], row["used_at"]) == ("phone", "operate", None)
        assert len(row["sha256"]) == 64

    def test_the_url_carries_the_stored_bind_and_the_code_in_the_fragment(self, paired: Path) -> None:
        minted = host_api_module.mint_pairing("phone")

        assert minted["url"] == f"http://{TAILNET_SHAPED}:8787/#pair={minted['code']}"
        life = datetime.fromisoformat(minted["expires_at"]) - datetime.now(timezone.utc)
        assert timedelta(seconds=290) < life <= timedelta(seconds=300)

    def test_a_wildcard_bind_is_refused_and_nothing_is_stored(self, paired: Path) -> None:
        with patch(PATCH_CONFIG_LOGGER):
            host_config.save_config({"host": "0.0.0.0", "port": 8787})

        with pytest.raises(host_api_module.PairingError, match="wildcard"):
            host_api_module.mint_pairing("phone")
        assert not host_pairings.store_path().exists()

    @pytest.mark.parametrize(
        ("label", "scope", "ttl"),
        [
            ("  ", "read", 300),
            ("phone", "admin", 300),
            ("phone", "read", 29),
            ("phone", "read", 901),
            ("phone", "read", True),
        ],
    )
    def test_a_bad_label_scope_or_ttl_is_refused_before_anything_is_stored(
        self, paired: Path, label: str, scope: str, ttl: Any
    ) -> None:
        with pytest.raises(host_pairings.PairingError):
            host_api_module.mint_pairing(label, scope, ttl)
        assert not host_pairings.store_path().exists()

    def test_the_door_refusal_is_a_token_error(self) -> None:
        assert issubclass(host_api_module.PairingError, host_api_module.TokenError)

    def test_an_unreadable_store_is_an_error_naming_the_store_never_an_empty_list(self, paired: Path) -> None:
        host_pairings.store_path().parent.mkdir(parents=True, exist_ok=True)
        host_pairings.store_path().write_text("{not json", encoding="utf-8")

        with pytest.raises(host_pairings.PairingError) as raised:
            host_api_module.mint_pairing("phone")
        assert host_pairings.store_path().name in str(raised.value)


class TestRedeemPairing:
    def test_a_live_code_buys_a_token_for_its_label_and_scope_and_writes_no_receipt(self, paired: Path) -> None:
        minted = host_api_module.mint_pairing("phone", "operate")

        redeemed = host_pairings.redeem_pairing(minted["code"])

        assert redeemed is not None
        record = host_tokens.verify_token(redeemed["token"])
        assert record is not None and record["id"] == redeemed["id"]
        assert (redeemed["label"], redeemed["scope"]) == ("phone", "operate")
        assert list(paired.rglob("*.token")) == []

    def test_the_code_is_marked_used_before_the_token_is_minted(self, paired: Path) -> None:
        minted = host_api_module.mint_pairing("phone")
        seen_at_mint: list = []
        real_issue = host_tokens.issue_token

        def recording_issue(label: str, scope: str = "read") -> Any:
            seen_at_mint.extend(row["used_at"] for row in host_pairings.load_pairings())
            return real_issue(label, scope)

        with patch.object(host_tokens, "issue_token", side_effect=recording_issue):
            host_pairings.redeem_pairing(minted["code"])

        assert len(seen_at_mint) == 1 and seen_at_mint[0] is not None

    def test_a_second_redeem_of_the_same_code_is_refused(self, paired: Path) -> None:
        minted = host_api_module.mint_pairing("phone")

        first = host_pairings.redeem_pairing(minted["code"])
        assert first is not None and first["label"] == "phone"
        assert host_pairings.redeem_pairing(minted["code"]) is None
        assert len(host_tokens.list_tokens()) == 1

    def test_an_expired_code_is_refused_and_mints_nothing(self, paired: Path) -> None:
        minted = host_api_module.mint_pairing("phone", ttl_seconds=30)
        _expire_every_row()

        assert host_pairings.redeem_pairing(minted["code"]) is None
        assert host_tokens.list_tokens() == []

    def test_unknown_expired_and_used_codes_get_one_and_the_same_answer(self, paired: Path) -> None:
        window = host_pairings.AttemptWindow()
        used = host_api_module.mint_pairing("phone")["code"]
        host_pairings.redeem_pairing(used)
        expired = host_api_module.mint_pairing("tablet")["code"]
        _expire_every_row()

        answers = [host_pairings.answer_pair({"code": code}, "100.64.0.9", window) for code in ("never", expired, used)]

        assert answers == [(401, {"code": "pairing_refused", "message": host_pairings.REFUSED})] * 3

    def test_a_mint_sweeps_used_and_expired_rows(self, paired: Path) -> None:
        host_pairings.redeem_pairing(host_api_module.mint_pairing("phone")["code"])
        host_api_module.mint_pairing("tablet")
        _expire_every_row()

        kept = host_api_module.mint_pairing("watch")

        assert [row["id"] for row in _stored_rows()] == [kept["id"]]


class TestRenderQr:
    def test_a_url_renders_as_terminal_block_characters_with_no_trailing_newline(self) -> None:
        rendered = host_api_module.render_qr(f"http://{TAILNET_SHAPED}:8787/#pair=abc")

        assert set(rendered) <= {"█", "▀", "▄", " ", "\n"}
        assert "█" in rendered and not rendered.endswith("\n")
        assert len({len(line) for line in rendered.splitlines()}) == 1

    def test_empty_text_is_refused(self) -> None:
        with pytest.raises(host_api_module.PairingError):
            host_api_module.render_qr("  ")


@pytest.fixture
def client(paired: Path) -> Any:
    """The real app over the tmp_path store."""
    from fastapi.testclient import TestClient

    with patch(PATCH_SERVER_LOGGER):
        yield TestClient(host_server.create_app(), raise_server_exceptions=False)


@fastapi_required
class TestPairRoute:
    def test_a_live_code_is_200_with_a_working_bearer_and_no_auth_header(self, client: Any) -> None:
        code = host_api_module.mint_pairing("phone", "operate")["code"]

        response = client.post("/v1/pair", json={"code": code})

        assert response.status_code == 200
        body = response.json()
        assert (body["label"], body["scope"]) == ("phone", "operate")
        whoami = client.get("/v1/whoami", headers={"Authorization": f"Bearer {body['token']}"})
        assert whoami.json()["id"] == body["id"]

    def test_a_used_code_is_401_with_the_one_sentence(self, client: Any) -> None:
        code = host_api_module.mint_pairing("phone")["code"]
        client.post("/v1/pair", json={"code": code})

        response = client.post("/v1/pair", json={"code": code})

        assert response.status_code == 401
        assert response.json() == {"error": {"code": "pairing_refused", "message": host_pairings.REFUSED}}

    @pytest.mark.parametrize("body", [{}, {"code": 42}, {"code": ""}, ["code"]])
    def test_a_missing_or_non_string_code_is_400(self, client: Any, body: Any) -> None:
        response = client.post("/v1/pair", json=body)

        assert response.status_code == 400
        assert response.json()["error"]["code"] == "invalid_request"

    def test_the_eleventh_attempt_in_a_minute_is_429(self, client: Any) -> None:
        statuses = [client.post("/v1/pair", json={"code": "guess"}).status_code for _ in range(11)]

        assert statuses == [401] * 10 + [429]

    def test_an_unreadable_store_is_503_with_the_fixed_sentence(self, client: Any) -> None:
        host_pairings.store_path().parent.mkdir(parents=True, exist_ok=True)
        host_pairings.store_path().write_text("[]", encoding="utf-8")

        with patch("aipass.api.apps.handlers.host.denials.logger") as log:
            response = client.post("/v1/pair", json={"code": "guess"})

        assert response.status_code == 503
        error = response.json()["error"]
        assert error["code"] == "pairing_unavailable"
        assert "pairings" not in error["message"]
        assert error["ref"] in log.warning.call_args.args
        assert host_pairings.store_path().name in str(log.warning.call_args.args[-1])


class TestPairCommand:
    def test_pair_prints_the_qr_a_blank_line_the_url_and_the_expiry(
        self, paired: Path, capsys: pytest.CaptureFixture
    ) -> None:
        assert handle_command("host-api", ["pair", "phone", "--scope", "operate", "--ttl", "60"]) is True

        out, _ = capsys.readouterr()
        lines = out.rstrip("\n").split("\n")
        [row] = _stored_rows()
        assert lines[-1].startswith("Expires ") and "(1 minute), one use." in lines[-1]
        assert lines[-2].startswith(f"http://{TAILNET_SHAPED}:8787/#pair=")
        assert lines[-3] == ""
        assert "█" in lines[0]
        assert row["scope"] == "operate"

    def test_pair_refuses_a_loopback_bind_with_exit_1_and_mints_nothing(
        self, paired: Path, capsys: pytest.CaptureFixture
    ) -> None:
        with patch(PATCH_CONFIG_LOGGER):
            host_config.save_config({"host": "127.0.0.1", "port": 8787})

        with pytest.raises(SystemExit) as exit_info:
            handle_command("host-api", ["pair", "phone"])

        assert exit_info.value.code == 1
        _, err = capsys.readouterr()
        assert "a phone cannot reach it" in err
        assert not host_pairings.store_path().exists()

    def test_pair_refuses_a_ttl_that_is_not_seconds(self, paired: Path, capsys: pytest.CaptureFixture) -> None:
        with pytest.raises(SystemExit):
            handle_command("host-api", ["pair", "phone", "--ttl", "soon"])

        _, err = capsys.readouterr()
        assert "soon" in err
        assert not host_pairings.store_path().exists()
