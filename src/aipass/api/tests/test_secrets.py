# =================== AIPass ====================
# Name: test_secrets.py
# Description: Tests for the keyring-backed secrets handler, its module door, migrate and get_secret_cmd
# Version: 2.0.0
# Created: 2026-06-15
# Modified: 2026-10-22
# =============================================

"""Tests for apps/handlers/auth/secrets.py, apps/modules/secrets.py, and api_key.get_secret_cmd."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(constant) — SECRETS_BASE's real home location; every test patches it to a temp dir
# seedgo: no-test-needed(covered) — api_key's get_key() and validate_key() commands, tests/test_api_key.py
# seedgo: no-test-needed(hardcoded_key) — that no real token sits in this file; every value is a fixture string

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from unittest.mock import patch, MagicMock

import pytest
from keyring.backend import KeyringBackend
from keyring.backends import chainer, fail, null
from keyring.errors import KeyringLocked, PasswordSetError

from aipass.api.apps.modules.api_key import handle_command as _hc  # noqa: F401 — seedgo test_coverage detection
from aipass.api.apps.modules.secrets import handle_command
from aipass.api.apps.handlers.auth.secrets import (
    SecretsUnavailable,
    get_secret,
    set_secret,
    list_secrets,
)
from aipass.api.apps.modules.api_key import get_secret_cmd
from aipass.api.apps.modules import secrets as secrets_module


PATCH_SECRETS_BASE = "aipass.api.apps.handlers.auth.secrets.SECRETS_BASE"
PATCH_JSON_HANDLER = "aipass.api.apps.handlers.auth.secrets.json_handler"
PATCH_LOGGER = "aipass.api.apps.handlers.auth.secrets.logger"

PATCH_CMD_SECRETS = "aipass.api.apps.modules.api_key.secrets"
PATCH_CMD_ERROR = "aipass.api.apps.modules.api_key.error"
PATCH_CMD_SUCCESS = "aipass.api.apps.modules.api_key.success"
PATCH_CMD_CONSOLE = "aipass.api.apps.modules.api_key.console"
PATCH_CMD_JSON_HANDLER = "aipass.api.apps.modules.api_key.json_handler"
GET_SECRET_USAGE = "Usage: drone @api get-secret <provider/slug> [--json] [--list]"

PATCH_MOD_HANDLER = "aipass.api.apps.modules.secrets._handler"
PATCH_MOD_JSON_HANDLER = "aipass.api.apps.modules.secrets.json_handler"

SERVICE = "aipass"
TG_DOC = {"bot_token": "tg-fixture-token", "chat_id": 42}
RAW_VALUE = "raw-fixture-value"
ENV_KEY = "sk-or-v1-" + "0" * 40
CLIENT_DOC = {"installed": {"client_id": "cid-fixture", "client_secret": "cs-fixture"}}
CREDS_DOC = {"token": "gtok-fixture", "refresh_token": "gref-fixture"}
FIXTURE_VALUES = ("tg-fixture-token", RAW_VALUE, ENV_KEY, "cs-fixture", "gtok-fixture", "gref-fixture")


@pytest.fixture
def quiet() -> Any:
    """The handler's log and operations rows, recorded."""
    # The module's rows too: unpatched, they land in the json seam under tmp_path, which is the store here.
    with patch(PATCH_JSON_HANDLER) as jh, patch(PATCH_LOGGER) as log, patch(PATCH_MOD_JSON_HANDLER):
        yield {"json": jh, "logger": log}


class _LockedKeyring(KeyringBackend):
    """A real-looking backend whose keyring is locked."""

    priority = 1  # type: ignore[assignment]

    def get_password(self, service: str, username: str) -> Any:
        raise KeyringLocked("locked")

    def set_password(self, service: str, username: str, password: str) -> None:
        raise KeyringLocked("locked")

    def delete_password(self, service: str, username: str) -> None:
        raise KeyringLocked("locked")


class _WorkingKeyring(KeyringBackend):
    """A backend that holds whatever it is given."""

    priority = 1  # type: ignore[assignment]

    def __init__(self) -> None:
        super().__init__()
        self.entries: dict = {}

    def get_password(self, service: str, username: str) -> Any:
        return self.entries.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.entries[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        self.entries.pop((service, username), None)


def _plaintext_backend() -> Any:
    """A working backend whose module is keyrings.alt's: the plaintext family."""
    return type("PlaintextKeyring", (_WorkingKeyring,), {"__module__": "keyrings.alt.file"})()


def _empty_chainer() -> Any:
    """A chainer that resolved to no backend at all."""
    return type("ChainerBackend", (chainer.ChainerBackend,), {"backends": []})()


def _plaintext_chainer() -> Any:
    """A chainer whose members include a plaintext backend."""
    return type("ChainerBackend", (chainer.ChainerBackend,), {"backends": [_WorkingKeyring(), _plaintext_backend()]})()


class TestTheKeyringHoldsTheValues:
    def test_a_string_round_trips_through_one_entry_named_provider_slug(
        self, store: Path, keyring_store: Any, quiet: dict
    ) -> None:
        assert set_secret("telegram", "bot", "round-trip-token") == "telegram/bot"

        assert keyring_store.entries[(SERVICE, "telegram/bot")] == "round-trip-token"
        assert get_secret("telegram", "bot") == "round-trip-token"
        assert list(store.iterdir()) == []

    def test_a_json_document_round_trips_and_rests_as_json(self, keyring_store: Any, quiet: dict) -> None:
        set_secret("telegram", "bot", TG_DOC, as_json=True)

        assert json.loads(keyring_store.entries[(SERVICE, "telegram/bot")]) == TG_DOC
        assert get_secret("telegram", "bot", as_json=True) == TG_DOC

    def test_a_json_entry_read_as_a_string_gives_its_token_key(self, quiet: dict) -> None:
        set_secret("discord", "creds", {"token": "second", "api_key": "first"}, as_json=True)

        assert get_secret("discord", "creds") == "first"

    def test_a_json_entry_with_no_token_key_reads_as_its_document(self, quiet: dict) -> None:
        set_secret("custom", "config", {"username": "admin"}, as_json=True)

        assert get_secret("custom", "config") == json.dumps({"username": "admin"})

    def test_a_missing_entry_is_none_and_the_warning_names_no_slug(self, quiet: dict) -> None:
        assert get_secret("telegram", "missing_slug") is None

        message, *values = quiet["logger"].warning.call_args.args
        assert "missing_slug" not in message % tuple(values)

    def test_nothing_is_read_from_a_file_left_in_the_store(self, store: Path, quiet: dict) -> None:
        (store / "telegram").mkdir()
        (store / "telegram" / "bot.json").write_text(json.dumps(TG_DOC), encoding="utf-8")
        (store / "telegram" / "raw").write_text(RAW_VALUE, encoding="utf-8")

        assert get_secret("telegram", "bot") is None
        assert get_secret("telegram", "raw") is None

    def test_list_secrets_works_with_no_file_on_disk(self, store: Path, quiet: dict) -> None:
        set_secret("telegram", "webhook", "w")
        set_secret("telegram", "bot", TG_DOC, as_json=True)
        set_secret("telegram", "bot", TG_DOC, as_json=True)
        set_secret("discord", "creds", "d")

        assert list_secrets("telegram") == ["bot", "webhook"]
        assert list(store.iterdir()) == []

    def test_list_secrets_for_an_unknown_provider_is_empty(self, quiet: dict) -> None:
        assert list_secrets("nonexistent") == []


@pytest.mark.parametrize(
    ("make", "named"),
    [
        (fail.Keyring, "Keyring"),
        (null.Keyring, "Keyring"),
        (_plaintext_backend, "PlaintextKeyring"),
        (_empty_chainer, "ChainerBackend"),
        (_plaintext_chainer, "ChainerBackend"),
        (_LockedKeyring, "_LockedKeyring"),
    ],
    ids=["fail", "null", "keyrings.alt", "empty-chainer", "plaintext-chainer", "locked"],
)
class TestABackendThatCannotHoldASecretRaises:
    def test_get_raises_naming_the_backend(self, store: Path, quiet: dict, make: Any, named: str) -> None:
        with patch("keyring.core._keyring_backend", make()), pytest.raises(SecretsUnavailable) as raised:
            get_secret("telegram", "bot")

        assert named in str(raised.value)
        assert str(store) not in str(raised.value)

    def test_set_raises_and_the_value_is_not_in_the_error(self, quiet: dict, make: Any, named: str) -> None:
        with patch("keyring.core._keyring_backend", make()), pytest.raises(SecretsUnavailable) as raised:
            set_secret("telegram", "bot", RAW_VALUE)

        assert named in str(raised.value)
        assert RAW_VALUE not in str(raised.value)
        assert raised.value.__cause__ is None

    def test_list_raises_never_an_empty_list(self, quiet: dict, make: Any, named: str) -> None:
        with patch("keyring.core._keyring_backend", make()), pytest.raises(SecretsUnavailable) as raised:
            list_secrets("telegram")

        assert named in str(raised.value)


class TestTheOperationsLog:
    def test_get_and_set_rows_carry_provider_and_slug_only(self, quiet: dict) -> None:
        set_secret("telegram", "bot", RAW_VALUE)
        get_secret("telegram", "bot")

        rows = [call.args for call in quiet["json"].log_operation.call_args_list]
        assert [name for name, _ in rows] == ["secret_written", "secret_retrieved"]
        assert all(data == {"provider": "telegram", "slug": "bot"} for _, data in rows)


class TestSecretsModule:
    """Verifies the in-process module door (apps/modules/secrets.py)."""

    def test_get_secret_wraps_handler(self) -> None:
        """Module get_secret delegates to handler and logs the operation."""
        mock_handler = MagicMock()
        mock_handler.get_secret.return_value = "token123"
        mock_jh = MagicMock()

        with patch(PATCH_MOD_HANDLER, mock_handler), patch(PATCH_MOD_JSON_HANDLER, mock_jh):
            result = secrets_module.get_secret("telegram", "bot")

        assert result == "token123"
        mock_handler.get_secret.assert_called_once_with("telegram", "bot", as_json=False)
        mock_jh.log_operation.assert_called_once()

    def test_get_secret_as_json(self) -> None:
        """Module get_secret passes as_json through to handler."""
        mock_handler = MagicMock()
        data = {"bot_token": "abc"}
        mock_handler.get_secret.return_value = data
        mock_jh = MagicMock()

        with patch(PATCH_MOD_HANDLER, mock_handler), patch(PATCH_MOD_JSON_HANDLER, mock_jh):
            result = secrets_module.get_secret("telegram", "bot", as_json=True)

        assert result == data
        mock_handler.get_secret.assert_called_once_with("telegram", "bot", as_json=True)

    def test_set_secret_returns_the_entry_name_and_logs_that_it_wrote(self, quiet: dict) -> None:
        mock_jh = MagicMock()

        with patch(PATCH_MOD_JSON_HANDLER, mock_jh):
            written = secrets_module.set_secret("telegram", "bot", "my-token-value")

        assert written == "telegram/bot"
        operation, data = mock_jh.log_operation.call_args[0]
        assert operation == "secrets_set"
        assert data == {"provider": "telegram", "slug": "bot", "wrote": True}

    def test_get_secret_not_found_logs(self) -> None:
        """Module get_secret logs even when handler returns None."""
        mock_handler = MagicMock()
        mock_handler.get_secret.return_value = None
        mock_jh = MagicMock()

        with patch(PATCH_MOD_HANDLER, mock_handler), patch(PATCH_MOD_JSON_HANDLER, mock_jh):
            result = secrets_module.get_secret("telegram", "missing")

        assert result is None
        log_call = mock_jh.log_operation.call_args
        assert log_call[0][1]["found"] is False

    def test_list_secrets_wraps_handler(self) -> None:
        """Module list_secrets delegates to handler."""
        mock_handler = MagicMock()
        mock_handler.list_secrets.return_value = ["bot", "webhook"]

        with patch(PATCH_MOD_HANDLER, mock_handler):
            result = secrets_module.list_secrets("telegram")

        assert result == ["bot", "webhook"]
        mock_handler.list_secrets.assert_called_once_with("telegram")


class TestGetSecretCmd:
    """Verifies the hardened get_secret_cmd: no raw secrets to stdout, none to a file."""

    @patch(PATCH_CMD_JSON_HANDLER)
    @patch(PATCH_CMD_SECRETS)
    @patch(PATCH_CMD_SUCCESS)
    def test_default_prints_masked_summary(self, mock_success, mock_secrets, mock_jh) -> None:
        """Default (no flags) prints masked summary, never the raw value."""
        mock_secrets.get_secret.return_value = "my-secret-token-value"

        get_secret_cmd(["telegram/bot"])

        mock_secrets.get_secret.assert_called_once_with("telegram", "bot", as_json=False)
        msg = mock_success.call_args[0][0]
        assert "telegram/bot" in msg
        assert "set" in msg
        assert "chars" in msg
        assert "my-secret-token-value" not in msg

    @patch(PATCH_CMD_JSON_HANDLER)
    @patch(PATCH_CMD_SECRETS)
    @patch(PATCH_CMD_ERROR)
    def test_out_is_unknown_and_no_value_reaches_a_file(self, mock_error, mock_secrets, mock_jh, tmp_path) -> None:
        mock_secrets.get_secret.return_value = "secret-token-here"
        out_file = tmp_path / "token.txt"

        get_secret_cmd(["telegram/bot", "--out", str(out_file)])

        mock_error.assert_called_once_with("Unknown option: --out", suggestion=GET_SECRET_USAGE)
        mock_secrets.get_secret.assert_not_called()
        assert list(tmp_path.iterdir()) == []

    def test_the_usage_names_no_file(self) -> None:
        assert "FILE" not in GET_SECRET_USAGE
        assert "--out" not in GET_SECRET_USAGE

    @patch(PATCH_CMD_JSON_HANDLER)
    @patch(PATCH_CMD_SECRETS)
    @patch(PATCH_CMD_ERROR)
    def test_an_unavailable_keyring_is_named_not_reported_missing(self, mock_error, mock_secrets, mock_jh) -> None:
        mock_secrets.SecretsUnavailable = SecretsUnavailable
        mock_secrets.get_secret.side_effect = SecretsUnavailable("The keyring backend X is locked")

        get_secret_cmd(["telegram/bot"])

        mock_error.assert_called_once_with("The keyring backend X is locked")

    @patch(PATCH_CMD_JSON_HANDLER)
    @patch(PATCH_CMD_SECRETS)
    @patch(PATCH_CMD_CONSOLE)
    def test_list_prints_slugs(self, mock_console, mock_secrets, mock_jh) -> None:
        """--list prints slug names via console.print."""
        mock_secrets.list_secrets.return_value = ["bot", "webhook"]

        get_secret_cmd(["telegram", "--list"])

        mock_secrets.list_secrets.assert_called_once_with("telegram")
        calls = [c for c in mock_console.print.call_args_list if c[0][0] in ("bot", "webhook")]
        assert len(calls) == 2

    @patch(PATCH_CMD_JSON_HANDLER)
    @patch(PATCH_CMD_ERROR)
    def test_no_args_calls_error(self, mock_error, mock_jh) -> None:
        """Empty args list calls error() with usage message."""
        get_secret_cmd([])

        mock_error.assert_called_once_with(GET_SECRET_USAGE)

    @patch(PATCH_CMD_JSON_HANDLER)
    @patch(PATCH_CMD_ERROR)
    def test_provider_only_without_list_calls_error(self, mock_error, mock_jh) -> None:
        """Single provider name without --list flag calls error() with format message."""
        get_secret_cmd(["telegram"])

        mock_error.assert_called_once_with("Expected format: <provider>/<slug>  (e.g. telegram/bot)")

    @patch(PATCH_CMD_JSON_HANDLER)
    @patch(PATCH_CMD_ERROR)
    def test_only_flags_no_positional_args_calls_error(self, mock_error, mock_jh) -> None:
        """Only flags (no positional args after stripping) calls error()."""
        get_secret_cmd(["--json"])

        mock_error.assert_called_once_with(GET_SECRET_USAGE)

    @patch(PATCH_CMD_JSON_HANDLER)
    @patch(PATCH_CMD_SECRETS)
    @patch(PATCH_CMD_ERROR)
    def test_secret_not_found_calls_error(self, mock_error, mock_secrets, mock_jh) -> None:
        """When get_secret returns None, error() is called."""
        mock_secrets.get_secret.return_value = None

        get_secret_cmd(["telegram/bot"])

        mock_error.assert_called_once_with("Secret not found: telegram/bot")

    @patch(PATCH_CMD_JSON_HANDLER)
    @patch(PATCH_CMD_SECRETS)
    @patch(PATCH_CMD_CONSOLE)
    def test_list_empty_provider(self, mock_console, mock_secrets, mock_jh) -> None:
        """--list with provider that has no secrets prints nothing."""
        mock_secrets.list_secrets.return_value = []

        get_secret_cmd(["empty_provider", "--list"])

        mock_secrets.list_secrets.assert_called_once_with("empty_provider")


class TestSetSecretModule:
    """Verifies the module-level set_secret wrapper."""

    def test_set_secret_wraps_handler(self) -> None:
        """Module set_secret delegates to handler and logs the operation."""
        mock_handler = MagicMock()
        mock_handler.set_secret.return_value = "telegram/bot"
        mock_jh = MagicMock()

        with patch(PATCH_MOD_HANDLER, mock_handler), patch(PATCH_MOD_JSON_HANDLER, mock_jh):
            result = secrets_module.set_secret("telegram", "bot", "token-val")

        assert result == "telegram/bot"
        mock_handler.set_secret.assert_called_once_with("telegram", "bot", "token-val", as_json=False)
        mock_jh.log_operation.assert_called_once()
        assert mock_jh.log_operation.call_args[0][0] == "secrets_set"

    def test_set_secret_as_json(self) -> None:
        """Module set_secret passes as_json through to handler."""
        mock_handler = MagicMock()
        mock_jh = MagicMock()
        data = {"bot_token": "abc"}

        with patch(PATCH_MOD_HANDLER, mock_handler), patch(PATCH_MOD_JSON_HANDLER, mock_jh):
            secrets_module.set_secret("telegram", "bot", data, as_json=True)

        mock_handler.set_secret.assert_called_once_with("telegram", "bot", data, as_json=True)


class TestSecretsHandleCommand:
    """The secrets module owns `secrets` alone — get-secret routes via api_key."""

    def test_no_args_returns_false_and_is_silent(self, capsys: object) -> None:
        """Claiming a no-arg command would swallow it before api.py can reject it."""
        # secrets is discovered last: True here makes api.py's "Unknown command" branch unreachable.
        assert secrets_module.handle_command("bogus-command", []) is False
        assert capsys.readouterr().out == ""  # type: ignore[union-attr]

    def test_help_flag_returns_false_and_is_silent(self, capsys: object) -> None:
        """A trailing help flag for another module's command is not ours to answer."""
        assert secrets_module.handle_command("bogus-command", ["--help"]) is False
        assert capsys.readouterr().out == ""  # type: ignore[union-attr]

    def test_secrets_help_names_migrate(self, capsys: pytest.CaptureFixture) -> None:
        assert handle_command("secrets", ["--help"]) is True

        assert "secrets migrate [--dry-run]" in capsys.readouterr().out


def _seed_store(base: Path) -> None:
    """A store of the three shapes, plus a Telethon session and a pairing receipt that stay."""
    (base / "telegram").mkdir()
    (base / "telegram" / "bot.json").write_text(json.dumps(TG_DOC), encoding="utf-8")
    (base / "telegram" / "mirror.session").write_text("sqlite-fixture", encoding="utf-8")
    (base / "generic").mkdir()
    (base / "generic" / "api_token").write_text(f"  {RAW_VALUE}\n", encoding="utf-8")
    (base / "host_api").mkdir()
    (base / "host_api" / "pixel.token").write_text("receipt-fixture", encoding="utf-8")
    (base / ".env").write_text(f"# AIPass API Keys\n\nOPENROUTER_API_KEY={ENV_KEY}\n", encoding="utf-8")
    (base / "google_client_secret.json").write_text(json.dumps(CLIENT_DOC), encoding="utf-8")
    (base / "google_creds.json").write_text(json.dumps(CREDS_DOC), encoding="utf-8")


MOVED = {
    "telegram/bot": TG_DOC,
    "generic/api_token": RAW_VALUE,
    "openrouter/api_key": ENV_KEY,
    "google/client_secret": CLIENT_DOC,
    "google/creds": CREDS_DOC,
}


class TestSecretsMigrate:
    def test_the_three_shapes_move_in_and_the_others_stay(
        self, store: Path, keyring_store: Any, quiet: dict, capsys: pytest.CaptureFixture
    ) -> None:
        _seed_store(store)

        assert handle_command("secrets", ["migrate"]) is True

        for name, value in MOVED.items():
            provider, slug = name.split("/")
            assert get_secret(provider, slug, as_json=isinstance(value, dict)) == value
        assert sorted(p.relative_to(store).as_posix() for p in store.rglob("*") if p.is_file()) == [
            "host_api/pixel.token",
            "telegram/mirror.session",
        ]
        out = capsys.readouterr().out
        assert "telegram/mirror.session" in out and "host_api/pixel.token" in out
        assert not any(value in out for value in FIXTURE_VALUES)

    def test_each_file_is_zeroed_before_it_is_unlinked(
        self, store: Path, tmp_path_factory: pytest.TempPathFactory, quiet: dict
    ) -> None:
        # A second hard link outlives the unlink and keeps the inode's last bytes: what the shred left on disk.
        _seed_store(store)
        witnesses = tmp_path_factory.mktemp("witness")
        linked = {}
        for index, name in enumerate(("telegram/bot.json", "generic/api_token", ".env", "google_creds.json")):
            witness = witnesses / str(index)
            os.link(store / name, witness)
            linked[store / name] = (witness, witness.stat().st_size)

        handle_command("secrets", ["migrate"])

        for original, (witness, size) in linked.items():
            assert not original.exists()
            assert witness.read_bytes() == b"\0" * size

    def test_a_failed_write_leaves_the_file_whole_and_says_so(
        self, store: Path, keyring_store: Any, quiet: dict, capsys: pytest.CaptureFixture
    ) -> None:
        (store / "generic").mkdir()
        (store / "generic" / "api_token").write_text(RAW_VALUE, encoding="utf-8")

        with patch.object(keyring_store, "set_password", side_effect=PasswordSetError("refused")):
            handle_command("secrets", ["migrate"])

        assert (store / "generic" / "api_token").read_text(encoding="utf-8") == RAW_VALUE
        _, err = capsys.readouterr()
        assert "PasswordSetError" in err
        assert RAW_VALUE not in err

    def test_dry_run_names_the_backend_and_what_would_move_and_changes_nothing(
        self, store: Path, keyring_store: Any, quiet: dict, capsys: pytest.CaptureFixture
    ) -> None:
        _seed_store(store)
        before = {p: p.read_bytes() for p in store.rglob("*") if p.is_file()}

        handle_command("secrets", ["migrate", "--dry-run"])

        assert keyring_store.entries == {}
        assert {p: p.read_bytes() for p in store.rglob("*") if p.is_file()} == before
        out = capsys.readouterr().out
        assert "DictKeyring" in out
        assert all(name in out for name in MOVED)

    def test_a_second_run_moves_nothing(
        self, store: Path, keyring_store: Any, quiet: dict, capsys: pytest.CaptureFixture
    ) -> None:
        _seed_store(store)
        handle_command("secrets", ["migrate"])
        entries = dict(keyring_store.entries)
        capsys.readouterr()

        handle_command("secrets", ["migrate"])

        assert keyring_store.entries == entries
        assert "Nothing left to move" in capsys.readouterr().out

    def test_the_log_rows_hold_provider_and_slug_and_no_value(self, store: Path, quiet: dict) -> None:
        _seed_store(store)

        handle_command("secrets", ["migrate"])

        rows = [c.args[1] for c in quiet["json"].log_operation.call_args_list if c.args[0] == "secret_migrated"]
        assert sorted(f"{row['provider']}/{row['slug']}" for row in rows) == sorted(MOVED)
        assert all(set(row) == {"provider", "slug"} for row in rows)
        logged = repr(quiet["json"].log_operation.call_args_list) + repr(quiet["logger"].mock_calls)
        assert not any(value in logged for value in FIXTURE_VALUES)
        assert str(store) not in logged

    def test_an_env_holding_other_settings_is_imported_but_kept(
        self, store: Path, keyring_store: Any, quiet: dict, capsys: pytest.CaptureFixture
    ) -> None:
        (store / ".env").write_text(f"OPENROUTER_API_KEY={ENV_KEY}\nBLUESKY_HANDLE=me\n", encoding="utf-8")

        handle_command("secrets", ["migrate"])

        assert get_secret("openrouter", "api_key") == ENV_KEY
        assert (store / ".env").exists()
        assert ".env" in capsys.readouterr().out

    def test_an_unavailable_backend_is_an_error_and_moves_nothing(
        self, store: Path, quiet: dict, capsys: pytest.CaptureFixture
    ) -> None:
        _seed_store(store)

        with patch("keyring.core._keyring_backend", null.Keyring()):
            handle_command("secrets", ["migrate"])

        assert (store / "google_creds.json").exists()
        assert "null" in capsys.readouterr().err.lower()
