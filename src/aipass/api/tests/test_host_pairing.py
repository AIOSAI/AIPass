# =================== AIPass ====================
# Name: test_host_pairing.py
# Description: Tests for the pairing door — one-use QR codes a phone trades for its bearer
# Version: 1.4.0
# Created: 2026-10-13
# Modified: 2026-11-06
# =============================================

"""Tests for apps/handlers/host/pairings.py, POST /v1/pair, the host-api pair verb and its extension mode."""

# A file of its own, permitted by @devpulse for DPLAN-0406's leg: the pairing
# store, its route and its verb are one behaviour (the token's hop to the phone)
# that test_host_api.py's commands and test_host_api_routes.py's auth do not own.
# Every test runs on the conftest `store` fixture: the lock directory is tmp_path, the rows sit in the dict store.

# The declared pass — what is NOT tested here, and what covers it instead:
# sentry: no-test-needed(external) — segno's QR encoding itself; render_qr is pinned to its block characters only
# sentry: no-test-needed(constant) — ATTEMPT_LIMIT, ATTEMPT_WINDOW_SECONDS and the TTL bounds' values

import json
from datetime import datetime, timedelta, timezone
from email.message import Message
from pathlib import Path
from typing import Any
from unittest.mock import patch
from urllib.error import HTTPError, URLError

import pytest
from keyring.errors import KeyringLocked

from aipass.api.apps.handlers.host import config as host_config
from aipass.api.apps.handlers.host import fleet as host_fleet
from aipass.api.apps.handlers.host import pairings as host_pairings
from aipass.api.apps.handlers.host import server as host_server
from aipass.api.apps.handlers.host import store as host_store
from aipass.api.apps.handlers.host import tokens as host_tokens
from aipass.api.apps.modules import host_api as host_api_module
from aipass.api.apps.modules.host_api import handle_command
from aipass.api.tests.support_host_api import TAILNET_SHAPED, FakeBaud, agent_row

PATCH_CONFIG_LOGGER = "aipass.api.apps.handlers.host.config.logger"
PATCH_PAIRINGS_LOGGER = "aipass.api.apps.handlers.host.pairings.logger"
PATCH_SERVER_LOGGER = "aipass.api.apps.handlers.host.server.logger"

fastapi_required = pytest.mark.skipif(not host_server.is_available(), reason="the [host] extra is not installed")


@pytest.fixture
def listener() -> Any:
    """The network edge: a server that answers the mint's GET on the bind, recorded."""
    with patch.object(host_pairings.urllib_request, "urlopen") as urlopen:
        yield urlopen


@pytest.fixture
def paired(store: Path, listener: Any) -> Any:
    """A token store in tmp_path, a tailnet-shaped bind stored beside it, a server on it, quiet logs."""
    with patch(PATCH_CONFIG_LOGGER), patch(PATCH_PAIRINGS_LOGGER):
        host_config.save_config({"host": TAILNET_SHAPED, "port": 8787})
        yield store


ENTRY = "host_api/pairings.json"


def _entry() -> Any:
    """The pairing rows' file as written, or None."""
    path = host_store.store_path(host_store.PAIRINGS)
    return path.read_text(encoding="utf-8") if path.exists() else None


def _write_entry(text: str) -> None:
    """Put raw text where the pairing rows live."""
    path = host_store.store_path(host_store.PAIRINGS)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _stored_rows() -> list:
    return json.loads(_entry())["pairings"]


def _expire_every_row() -> None:
    """Move every stored row's expiry an hour into the past: the clock's edge, set in the store."""
    document = json.loads(_entry())
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    for row in document["pairings"]:
        row["expires"] = past
    _write_entry(json.dumps(document))


class TestMintPairing:
    def test_mint_stores_the_codes_hash_and_never_the_code(self, paired: Path) -> None:
        minted = host_api_module.mint_pairing("phone", "operate")

        stored = _entry()
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
        assert _entry() is None

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
        assert _entry() is None

    def test_the_mint_asks_the_bind_itself_whether_a_server_answers(self, paired: Path, listener: Any) -> None:
        host_api_module.mint_pairing("phone")

        assert listener.call_args.args[0] == f"http://{TAILNET_SHAPED}:8787/"

    def test_no_server_on_the_bind_refuses_with_the_two_commands_and_stores_nothing(
        self, paired: Path, listener: Any
    ) -> None:
        """No QR is minted for a dead server: the refusal names the two commands and stores nothing."""
        listener.side_effect = URLError(ConnectionRefusedError(111, "Connection refused"))

        with pytest.raises(host_api_module.PairingError) as raised:
            host_api_module.mint_pairing("phone", "operate")

        lines = str(raised.value).splitlines()
        assert lines[0].startswith(f"No server answers on {TAILNET_SHAPED}:8787")
        assert lines[1:] == ["  drone @api host-api serve --detach", "  drone @api host-api pair phone --scope operate"]
        assert _entry() is None

    def test_a_server_answering_an_error_refuses_and_names_status(self, paired: Path, listener: Any) -> None:
        listener.side_effect = HTTPError(f"http://{TAILNET_SHAPED}:8787/", 503, "Service Unavailable", Message(), None)

        with pytest.raises(host_api_module.PairingError) as raised:
            host_api_module.mint_pairing("phone")

        assert "answers 503" in str(raised.value)
        assert str(raised.value).endswith("drone @api host-api status")
        assert _entry() is None

    def test_the_door_refusal_is_a_token_error(self) -> None:
        assert issubclass(host_api_module.PairingError, host_api_module.TokenError)

    def test_an_unreadable_store_is_an_error_naming_the_store_never_an_empty_list(self, paired: Path) -> None:
        _write_entry("{not json")

        with pytest.raises(host_pairings.PairingError) as raised:
            host_api_module.mint_pairing("phone")
        assert ENTRY in str(raised.value)

    def test_a_store_file_that_cannot_be_read_is_a_pairing_error_naming_the_file(self, paired: Path) -> None:
        # A directory where the file belongs: read_text raises an OSError on every OS.
        host_store.store_path(host_store.PAIRINGS).mkdir(parents=True)

        with pytest.raises(host_pairings.PairingError) as raised:
            host_api_module.mint_pairing("phone")

        assert ENTRY in str(raised.value)
        assert str(paired) not in str(raised.value)

    def test_a_locked_keyring_does_not_stop_a_mint(self, paired: Path, keyring_store: Any) -> None:
        with patch.object(keyring_store, "get_password", side_effect=KeyringLocked("locked")):
            minted = host_api_module.mint_pairing("phone")

        assert [row["id"] for row in _stored_rows()] == [minted["id"]]
        assert keyring_store.entries == {}

    def test_the_rows_rest_in_their_own_file_beside_the_config(self, paired: Path) -> None:
        host_api_module.mint_pairing("phone")

        assert len(_stored_rows()) == 1
        assert sorted(item.name for item in (paired / "host_api").iterdir()) == ["config.json", "pairings.json"]


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
        _write_entry("[]")

        with patch("aipass.api.apps.handlers.host.denials.logger") as log:
            response = client.post("/v1/pair", json={"code": "guess"})

        assert response.status_code == 503
        error = response.json()["error"]
        assert error["code"] == "pairing_unavailable"
        assert "pairings" not in error["message"]
        assert error["ref"] in log.warning.call_args.args
        assert ENTRY in str(log.warning.call_args.args[-1])


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
        assert _entry() is None

    def test_pair_with_no_server_exits_1_and_prints_both_commands(
        self, paired: Path, listener: Any, capsys: pytest.CaptureFixture
    ) -> None:
        listener.side_effect = URLError(ConnectionRefusedError(111, "Connection refused"))

        with pytest.raises(SystemExit) as exit_info:
            handle_command("host-api", ["pair", "phone", "--scope", "operate"])

        assert exit_info.value.code == 1
        _, err = capsys.readouterr()
        assert "drone @api host-api serve --detach" in err
        assert "drone @api host-api pair phone --scope operate" in err
        assert _entry() is None

    def test_pair_refuses_a_ttl_that_is_not_seconds(self, paired: Path, capsys: pytest.CaptureFixture) -> None:
        with pytest.raises(SystemExit):
            handle_command("host-api", ["pair", "phone", "--ttl", "soon"])

        _, err = capsys.readouterr()
        assert "soon" in err
        assert _entry() is None


@fastapi_required
class TestPairExtension:
    """`pair extension`: a one-use code and the base URL as plain text, operate scope, loopback allowed, no QR."""

    def test_it_prints_the_code_the_base_url_and_the_expiry_and_no_qr(
        self, client: Any, capsys: pytest.CaptureFixture
    ) -> None:
        with patch(PATCH_CONFIG_LOGGER):
            host_config.save_config({"host": "127.0.0.1", "port": 8787})

        assert handle_command("host-api", ["pair", "extension"]) is True

        out, _ = capsys.readouterr()
        code_line, host_line, expiry_line = out.rstrip("\n").split("\n")
        [row] = _stored_rows()
        assert code_line.startswith("Pairing code: ") and host_line == "Host: http://127.0.0.1:8787"
        assert expiry_line.startswith("Expires ") and "(5 minutes), one use." in expiry_line
        assert "█" not in out
        assert (row["label"], row["scope"]) == ("extension", "operate")
        assert host_tokens.list_tokens() == []

    def test_the_printed_code_redeems_from_an_extension_origin_to_a_working_bearer(
        self, client: Any, capsys: pytest.CaptureFixture
    ) -> None:
        handle_command("host-api", ["pair", "extension", "--scope", "read", "--ttl", "60"])
        out, _ = capsys.readouterr()
        code = out.split("\n")[0].removeprefix("Pairing code: ")

        response = client.post("/v1/pair", json={"code": code}, headers={"Origin": EXTENSION_ORIGIN})

        body = response.json()
        assert (response.status_code, body["label"], body["scope"]) == (200, "extension", "read")
        assert body["token"] not in out
        whoami = client.get("/v1/whoami", headers={"Authorization": f"Bearer {body['token']}"})
        assert whoami.json()["id"] == body["id"]


EXTENSION_ORIGIN = "chrome-extension://abcdefghijklmnopabcdefghijklmnop"


@fastapi_required
class TestAnExtensionOriginIsAnsweredAsAnyOther:
    """No CORS, Origin or Sec-Fetch check stands in the way: an extension page's call answers as one without Origin."""

    def test_a_feed_get_and_a_send_post_answer_alike_with_and_without_the_origin(
        self, client: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setattr(host_fleet, "snapshot_binary", lambda: "baud")
        monkeypatch.setattr(host_fleet, "repo_root", lambda: tmp_path)
        fake = FakeBaud([agent_row()])
        monkeypatch.setattr(host_fleet.subprocess, "run", fake)
        transcript = tmp_path / ".claude" / "projects" / "-srv-aipass-devpulse" / "s-1.jsonl"
        transcript.parent.mkdir(parents=True)
        transcript.write_text(json.dumps({"type": "user", "message": {"content": "hi"}}) + "\n", encoding="utf-8")
        _, raw = host_tokens.issue_token("extension", "operate")
        bearer = {"Authorization": f"Bearer {raw}"}
        extension = {**bearer, "Origin": EXTENSION_ORIGIN, "Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "cors"}

        answers = []
        for headers in (bearer, extension):
            feed = client.get("/v1/agent/AIPASS/devpulse/feed", headers=headers)
            send = client.post("/v1/agent/AIPASS/devpulse/send", json={"text": "go"}, headers=headers)
            answers.append((feed.status_code, feed.json()["lines"], send.status_code, send.json()))

        assert answers[0] == answers[1] == (200, answers[0][1], 200, {"ok": True})
        assert answers[0][1] and fake.payloads()[:2] == fake.payloads()[2:]
        assert "access-control-allow-origin" not in send.headers
