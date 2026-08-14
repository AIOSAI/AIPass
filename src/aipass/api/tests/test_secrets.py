# =================== AIPass ====================
# Name: test_secrets.py
# Description: Tests for secrets handler and get_secret_cmd orchestrator
# Version: 1.0.0
# Created: 2026-06-15
# Modified: 2026-06-15
# =============================================

"""Tests for apps/handlers/auth/secrets.py, apps/modules/secrets.py, and api_key.get_secret_cmd.

Tests — handlers/auth/secrets.py (get_secret, list_secrets):
- get_secret: JSON token extraction via _TOKEN_KEYS
- get_secret: as_json returns full parsed dict
- get_secret: raw file fallback returns stripped content
- get_secret: missing provider directory returns None
- get_secret: missing slug file returns None
- get_secret: malformed JSON returns None
- get_secret: unreadable file (OSError) returns None
- get_secret: JSON with no matching token key returns json.dumps of dict
- list_secrets: returns sorted slug names, strips .json extension
- list_secrets: non-existent provider returns empty list
- list_secrets: skips dotfiles, __pycache__, directories

Tests — handlers/auth/secrets.py (set_secret):
- set_secret: writes string value to provider/slug.json
- set_secret: as_json writes JSON-serialized dict
- set_secret: creates provider directory if missing
- set_secret: file has 0o600 permissions (POSIX)
- set_secret: provider dir has 0o700 permissions (POSIX)
- set_secret: overwrites existing secret
- set_secret: round-trip with get_secret returns same value
- set_secret: round-trip with get_secret as_json returns same dict

Tests — modules/secrets.py (in-process door):
- get_secret wraps handler and logs operation
- set_secret wraps handler and logs operation
- list_secrets wraps handler

Tests — api_key.py (get_secret_cmd — hardened, no raw values to stdout):
- get_secret_cmd default prints masked summary only
- get_secret_cmd --out writes to file with 0o600 perms
- get_secret_cmd --out --json writes JSON to file
- get_secret_cmd --list prints slug names
- get_secret_cmd no args calls error()
- get_secret_cmd provider only (no --list) calls error()
- get_secret_cmd only flags calls error()
- get_secret_cmd not found calls error()
- get_secret_cmd --out missing path calls error()
"""

from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from aipass.api.apps.modules.api_key import handle_command as _hc  # noqa: F401 — seedgo test_coverage detection
from aipass.api.apps.modules.secrets import handle_command as _hc2  # noqa: F401 — seedgo test_coverage detection
from aipass.api.apps.handlers.auth.secrets import (
    get_secret,
    set_secret,
    list_secrets,
)
from aipass.api.apps.modules.api_key import get_secret_cmd
from aipass.api.apps.modules import secrets as secrets_module


# Patch targets
PATCH_SECRETS_BASE = "aipass.api.apps.handlers.auth.secrets.SECRETS_BASE"
PATCH_JSON_HANDLER = "aipass.api.apps.handlers.auth.secrets.json_handler"
PATCH_LOGGER = "aipass.api.apps.handlers.auth.secrets.logger"

PATCH_CMD_SECRETS = "aipass.api.apps.modules.api_key.secrets"
PATCH_CMD_ERROR = "aipass.api.apps.modules.api_key.error"
PATCH_CMD_SUCCESS = "aipass.api.apps.modules.api_key.success"
PATCH_CMD_CONSOLE = "aipass.api.apps.modules.api_key.console"
PATCH_CMD_JSON_HANDLER = "aipass.api.apps.modules.api_key.json_handler"

PATCH_MOD_HANDLER = "aipass.api.apps.modules.secrets._handler"
PATCH_MOD_JSON_HANDLER = "aipass.api.apps.modules.secrets.json_handler"


# =============================================
# get_secret
# =============================================


class TestGetSecret:
    """Verifies secret retrieval under various conditions."""

    def test_json_token_extraction(self, tmp_path: Path) -> None:
        """JSON file with a known token key returns the extracted token string."""
        provider_dir = tmp_path / "telegram"
        provider_dir.mkdir()
        secret_file = provider_dir / "bot.json"
        secret_file.write_text(json.dumps({"bot_token": "abc123", "extra": "stuff"}))

        with patch(PATCH_SECRETS_BASE, tmp_path), patch(PATCH_JSON_HANDLER), patch(PATCH_LOGGER):
            result = get_secret("telegram", "bot")

        assert result == "abc123"

    def test_json_token_extraction_searches_keys_in_order(self, tmp_path: Path) -> None:
        """Token extraction tries _TOKEN_KEYS in order; first match wins."""
        provider_dir = tmp_path / "discord"
        provider_dir.mkdir()
        # Has both 'api_key' and 'token'; api_key comes first in _TOKEN_KEYS
        secret_file = provider_dir / "creds.json"
        secret_file.write_text(json.dumps({"token": "second", "api_key": "first"}))

        with patch(PATCH_SECRETS_BASE, tmp_path), patch(PATCH_JSON_HANDLER), patch(PATCH_LOGGER):
            result = get_secret("discord", "creds")

        assert result == "first"

    def test_as_json_returns_full_dict(self, tmp_path: Path) -> None:
        """as_json=True returns the full parsed dictionary."""
        provider_dir = tmp_path / "telegram"
        provider_dir.mkdir()
        data = {"bot_token": "abc123", "webhook_url": "https://example.com"}
        (provider_dir / "bot.json").write_text(json.dumps(data))

        with patch(PATCH_SECRETS_BASE, tmp_path), patch(PATCH_JSON_HANDLER), patch(PATCH_LOGGER):
            result = get_secret("telegram", "bot", as_json=True)

        assert result == data

    def test_raw_file_fallback(self, tmp_path: Path) -> None:
        """When no JSON file exists, falls back to raw file and returns stripped content."""
        provider_dir = tmp_path / "generic"
        provider_dir.mkdir()
        (provider_dir / "api_token").write_text("  raw-secret-value  \n")

        with patch(PATCH_SECRETS_BASE, tmp_path), patch(PATCH_JSON_HANDLER), patch(PATCH_LOGGER):
            result = get_secret("generic", "api_token")

        assert result == "raw-secret-value"

    def test_missing_provider_directory(self, tmp_path: Path) -> None:
        """Non-existent provider directory returns None."""
        with patch(PATCH_SECRETS_BASE, tmp_path), patch(PATCH_JSON_HANDLER), patch(PATCH_LOGGER):
            result = get_secret("nonexistent", "bot")

        assert result is None

    def test_missing_slug_file(self, tmp_path: Path) -> None:
        """Provider exists but slug file does not -- returns None."""
        provider_dir = tmp_path / "telegram"
        provider_dir.mkdir()

        with patch(PATCH_SECRETS_BASE, tmp_path), patch(PATCH_JSON_HANDLER), patch(PATCH_LOGGER):
            result = get_secret("telegram", "missing_slug")

        assert result is None

    def test_malformed_json_returns_none(self, tmp_path: Path) -> None:
        """Malformed JSON file returns None and logs a warning."""
        provider_dir = tmp_path / "telegram"
        provider_dir.mkdir()
        (provider_dir / "bot.json").write_text("{not valid json")

        mock_logger = MagicMock()
        with patch(PATCH_SECRETS_BASE, tmp_path), patch(PATCH_JSON_HANDLER), patch(PATCH_LOGGER, mock_logger):
            result = get_secret("telegram", "bot")

        assert result is None
        mock_logger.warning.assert_called()

    @pytest.mark.skipif(
        sys.platform == "win32",
        reason="chmod(0o000) does not make a file unreadable to its owner on Windows",
    )
    def test_unreadable_file_returns_none(self, tmp_path: Path) -> None:
        """OSError when reading file returns None."""
        provider_dir = tmp_path / "telegram"
        provider_dir.mkdir()
        secret_file = provider_dir / "bot.json"
        secret_file.write_text(json.dumps({"bot_token": "abc"}))
        # Make unreadable
        secret_file.chmod(0o000)

        mock_logger = MagicMock()
        with patch(PATCH_SECRETS_BASE, tmp_path), patch(PATCH_JSON_HANDLER), patch(PATCH_LOGGER, mock_logger):
            result = get_secret("telegram", "bot")

        # Restore permissions for cleanup
        secret_file.chmod(0o644)

        assert result is None

    def test_json_no_matching_token_key(self, tmp_path: Path) -> None:
        """JSON dict with no recognized token key returns json.dumps of the dict."""
        provider_dir = tmp_path / "custom"
        provider_dir.mkdir()
        data = {"username": "admin", "host": "localhost"}
        (provider_dir / "config.json").write_text(json.dumps(data))

        with patch(PATCH_SECRETS_BASE, tmp_path), patch(PATCH_JSON_HANDLER), patch(PATCH_LOGGER):
            result = get_secret("custom", "config")

        assert result == json.dumps(data)

    def test_json_non_dict_value(self, tmp_path: Path) -> None:
        """JSON file containing a non-dict value (e.g., a string) returns str of it."""
        provider_dir = tmp_path / "simple"
        provider_dir.mkdir()
        (provider_dir / "token.json").write_text(json.dumps("plain-string-secret"))

        with patch(PATCH_SECRETS_BASE, tmp_path), patch(PATCH_JSON_HANDLER), patch(PATCH_LOGGER):
            result = get_secret("simple", "token")

        assert result == "plain-string-secret"

    def test_json_preferred_over_raw(self, tmp_path: Path) -> None:
        """When both JSON and raw files exist, JSON takes priority."""
        provider_dir = tmp_path / "dual"
        provider_dir.mkdir()
        (provider_dir / "cred.json").write_text(json.dumps({"api_key": "from-json"}))
        (provider_dir / "cred").write_text("from-raw")

        with patch(PATCH_SECRETS_BASE, tmp_path), patch(PATCH_JSON_HANDLER), patch(PATCH_LOGGER):
            result = get_secret("dual", "cred")

        assert result == "from-json"

    def test_provider_is_file_not_dir(self, tmp_path: Path) -> None:
        """If provider path exists but is a file (not a directory), returns None."""
        (tmp_path / "notadir").write_text("file content")

        with patch(PATCH_SECRETS_BASE, tmp_path), patch(PATCH_JSON_HANDLER), patch(PATCH_LOGGER):
            result = get_secret("notadir", "slug")

        assert result is None


# =============================================
# list_secrets
# =============================================


class TestListSecrets:
    """Verifies secret listing under various conditions."""

    def test_returns_sorted_slugs(self, tmp_path: Path) -> None:
        """Returns sorted slug names with .json extension stripped."""
        provider_dir = tmp_path / "telegram"
        provider_dir.mkdir()
        (provider_dir / "webhook.json").write_text("{}")
        (provider_dir / "bot.json").write_text("{}")
        (provider_dir / "raw_token").write_text("tok")

        with patch(PATCH_SECRETS_BASE, tmp_path), patch(PATCH_LOGGER):
            result = list_secrets("telegram")

        assert result == ["bot", "raw_token", "webhook"]

    def test_nonexistent_provider_returns_empty(self, tmp_path: Path) -> None:
        """Non-existent provider returns empty list."""
        with patch(PATCH_SECRETS_BASE, tmp_path), patch(PATCH_LOGGER):
            result = list_secrets("nonexistent")

        assert result == []

    def test_skips_dotfiles(self, tmp_path: Path) -> None:
        """Entries starting with '.' are excluded."""
        provider_dir = tmp_path / "provider"
        provider_dir.mkdir()
        (provider_dir / ".hidden").write_text("secret")
        (provider_dir / "visible.json").write_text("{}")

        with patch(PATCH_SECRETS_BASE, tmp_path), patch(PATCH_LOGGER):
            result = list_secrets("provider")

        assert result == ["visible"]

    def test_skips_pycache(self, tmp_path: Path) -> None:
        """__pycache__ directory is excluded."""
        provider_dir = tmp_path / "provider"
        provider_dir.mkdir()
        # __pycache__ as a file (the check is name-based, not type-based for this entry)
        pycache = provider_dir / "__pycache__"
        pycache.mkdir()
        (provider_dir / "real.json").write_text("{}")

        with patch(PATCH_SECRETS_BASE, tmp_path), patch(PATCH_LOGGER):
            result = list_secrets("provider")

        assert result == ["real"]

    def test_skips_directories(self, tmp_path: Path) -> None:
        """Subdirectories (non-files) are excluded."""
        provider_dir = tmp_path / "provider"
        provider_dir.mkdir()
        (provider_dir / "subdir").mkdir()
        (provider_dir / "secret.json").write_text("{}")

        with patch(PATCH_SECRETS_BASE, tmp_path), patch(PATCH_LOGGER):
            result = list_secrets("provider")

        assert result == ["secret"]

    def test_provider_is_file_not_dir(self, tmp_path: Path) -> None:
        """If provider path is a file instead of a directory, returns empty list."""
        (tmp_path / "notadir").write_text("file")

        with patch(PATCH_SECRETS_BASE, tmp_path), patch(PATCH_LOGGER):
            result = list_secrets("notadir")

        assert result == []


# =============================================
# get_secret_cmd
# =============================================


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


# =============================================
# get_secret_cmd (hardened — no raw values to stdout)
# =============================================


class TestGetSecretCmd:
    """Verifies the hardened get_secret_cmd (DPLAN-0211: no raw secrets to stdout)."""

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

    @pytest.mark.skipif(sys.platform == "win32", reason="File permission checks are POSIX-only")
    @patch(PATCH_CMD_JSON_HANDLER)
    @patch(PATCH_CMD_SECRETS)
    @patch(PATCH_CMD_SUCCESS)
    def test_out_writes_file_with_0600(self, mock_success, mock_secrets, mock_jh, tmp_path: Path) -> None:
        """--out writes secret value to file with 0o600 permissions."""
        mock_secrets.get_secret.return_value = "secret-token-here"
        out_file = str(tmp_path / "token.txt")

        get_secret_cmd(["telegram/bot", "--out", out_file])

        assert Path(out_file).exists()
        assert Path(out_file).read_text(encoding="utf-8") == "secret-token-here"
        file_mode = stat.S_IMODE(os.stat(out_file).st_mode)
        assert file_mode == 0o600
        msg = mock_success.call_args[0][0]
        assert out_file in msg
        assert "secret-token-here" not in msg

    @pytest.mark.skipif(sys.platform == "win32", reason="File permission checks are POSIX-only")
    @patch(PATCH_CMD_JSON_HANDLER)
    @patch(PATCH_CMD_SECRETS)
    @patch(PATCH_CMD_SUCCESS)
    def test_out_json_writes_json_file(self, mock_success, mock_secrets, mock_jh, tmp_path: Path) -> None:
        """--out --json writes JSON-formatted secret to file."""
        data = {"bot_token": "abc123", "allowed": [1, 2]}
        mock_secrets.get_secret.return_value = data
        out_file = str(tmp_path / "bot.json")

        get_secret_cmd(["telegram/bot", "--out", out_file, "--json"])

        content = Path(out_file).read_text(encoding="utf-8")
        assert json.loads(content) == data
        file_mode = stat.S_IMODE(os.stat(out_file).st_mode)
        assert file_mode == 0o600

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

        mock_error.assert_called_once()
        assert "Usage" in mock_error.call_args[0][0]

    @patch(PATCH_CMD_JSON_HANDLER)
    @patch(PATCH_CMD_ERROR)
    def test_provider_only_without_list_calls_error(self, mock_error, mock_jh) -> None:
        """Single provider name without --list flag calls error() with format message."""
        get_secret_cmd(["telegram"])

        mock_error.assert_called_once()

    @patch(PATCH_CMD_JSON_HANDLER)
    @patch(PATCH_CMD_ERROR)
    def test_only_flags_no_positional_args_calls_error(self, mock_error, mock_jh) -> None:
        """Only flags (no positional args after stripping) calls error()."""
        get_secret_cmd(["--json"])

        mock_error.assert_called_once()
        assert "Usage" in mock_error.call_args[0][0]

    @patch(PATCH_CMD_JSON_HANDLER)
    @patch(PATCH_CMD_SECRETS)
    @patch(PATCH_CMD_ERROR)
    def test_secret_not_found_calls_error(self, mock_error, mock_secrets, mock_jh) -> None:
        """When get_secret returns None, error() is called."""
        mock_secrets.get_secret.return_value = None

        get_secret_cmd(["telegram/bot"])

        mock_error.assert_called_once()
        assert "not found" in mock_error.call_args[0][0].lower()

    @patch(PATCH_CMD_JSON_HANDLER)
    @patch(PATCH_CMD_ERROR)
    def test_out_missing_path_calls_error(self, mock_error, mock_jh) -> None:
        """--out without a file path argument calls error()."""
        get_secret_cmd(["telegram/bot", "--out"])

        mock_error.assert_called_once()
        assert "--out" in mock_error.call_args[0][0]

    @patch(PATCH_CMD_JSON_HANDLER)
    @patch(PATCH_CMD_SECRETS)
    @patch(PATCH_CMD_CONSOLE)
    def test_list_empty_provider(self, mock_console, mock_secrets, mock_jh) -> None:
        """--list with provider that has no secrets prints nothing."""
        mock_secrets.list_secrets.return_value = []

        get_secret_cmd(["empty_provider", "--list"])

        mock_secrets.list_secrets.assert_called_once_with("empty_provider")


# =============================================
# set_secret (handler)
# =============================================


class TestSetSecret:
    """Verifies secret writing under various conditions."""

    def test_writes_string_value(self, tmp_path: Path) -> None:
        """Writes a plain string value to provider/slug.json."""
        with patch(PATCH_SECRETS_BASE, tmp_path), patch(PATCH_JSON_HANDLER), patch(PATCH_LOGGER):
            result = set_secret("telegram", "bot", "my-token-value")

        assert result == tmp_path / "telegram" / "bot.json"
        assert json.loads(result.read_text(encoding="utf-8")) == "my-token-value"

    def test_as_json_writes_dict(self, tmp_path: Path) -> None:
        """as_json=True writes JSON-serialized dict."""
        data = {"bot_token": "abc123", "webhook_url": "https://example.com"}

        with patch(PATCH_SECRETS_BASE, tmp_path), patch(PATCH_JSON_HANDLER), patch(PATCH_LOGGER):
            result = set_secret("telegram", "bot", data, as_json=True)

        written = json.loads(result.read_text(encoding="utf-8"))
        assert written == data

    def test_creates_provider_directory(self, tmp_path: Path) -> None:
        """Creates provider directory if it doesn't exist."""
        assert not (tmp_path / "newprovider").exists()

        with patch(PATCH_SECRETS_BASE, tmp_path), patch(PATCH_JSON_HANDLER), patch(PATCH_LOGGER):
            set_secret("newprovider", "cred", "value")

        assert (tmp_path / "newprovider").is_dir()

    @pytest.mark.skipif(sys.platform == "win32", reason="File permission checks are POSIX-only")
    def test_file_has_0600_permissions(self, tmp_path: Path) -> None:
        """Written file has 0o600 permissions."""
        with patch(PATCH_SECRETS_BASE, tmp_path), patch(PATCH_JSON_HANDLER), patch(PATCH_LOGGER):
            result = set_secret("telegram", "bot", "token")

        file_mode = stat.S_IMODE(os.stat(result).st_mode)
        assert file_mode == 0o600

    @pytest.mark.skipif(sys.platform == "win32", reason="File permission checks are POSIX-only")
    def test_provider_dir_has_0700_permissions(self, tmp_path: Path) -> None:
        """Provider directory has 0o700 permissions."""
        with patch(PATCH_SECRETS_BASE, tmp_path), patch(PATCH_JSON_HANDLER), patch(PATCH_LOGGER):
            set_secret("telegram", "bot", "token")

        dir_mode = stat.S_IMODE(os.stat(tmp_path / "telegram").st_mode)
        assert dir_mode == 0o700

    def test_overwrites_existing_secret(self, tmp_path: Path) -> None:
        """Overwrites an existing secret file."""
        with patch(PATCH_SECRETS_BASE, tmp_path), patch(PATCH_JSON_HANDLER), patch(PATCH_LOGGER):
            set_secret("telegram", "bot", "old-value")
            set_secret("telegram", "bot", "new-value")

        content = json.loads((tmp_path / "telegram" / "bot.json").read_text(encoding="utf-8"))
        assert content == "new-value"

    def test_round_trip_string(self, tmp_path: Path) -> None:
        """set_secret then get_secret returns the same string value."""
        with patch(PATCH_SECRETS_BASE, tmp_path), patch(PATCH_JSON_HANDLER), patch(PATCH_LOGGER):
            set_secret("telegram", "bot", "round-trip-token")
            result = get_secret("telegram", "bot")

        assert result == "round-trip-token"

    def test_round_trip_json(self, tmp_path: Path) -> None:
        """set_secret as_json then get_secret as_json returns the same dict."""
        data = {"bot_token": "abc123", "chat_id": 42}

        with patch(PATCH_SECRETS_BASE, tmp_path), patch(PATCH_JSON_HANDLER), patch(PATCH_LOGGER):
            set_secret("telegram", "bot", data, as_json=True)
            result = get_secret("telegram", "bot", as_json=True)

        assert result == data

    def test_logs_operation(self, tmp_path: Path) -> None:
        """set_secret logs the write operation via json_handler."""
        mock_jh = MagicMock()
        with patch(PATCH_SECRETS_BASE, tmp_path), patch(PATCH_JSON_HANDLER, mock_jh), patch(PATCH_LOGGER):
            set_secret("telegram", "bot", "token")

        mock_jh.log_operation.assert_called_once()
        call_args = mock_jh.log_operation.call_args[0]
        assert call_args[0] == "secret_written"
        assert call_args[1]["provider"] == "telegram"
        assert call_args[1]["slug"] == "bot"


# =============================================
# set_secret (module door)
# =============================================


class TestSetSecretModule:
    """Verifies the module-level set_secret wrapper."""

    def test_set_secret_wraps_handler(self, tmp_path: Path) -> None:
        """Module set_secret delegates to handler and logs the operation."""
        mock_handler = MagicMock()
        mock_handler.set_secret.return_value = tmp_path / "telegram" / "bot.json"
        mock_jh = MagicMock()

        with patch(PATCH_MOD_HANDLER, mock_handler), patch(PATCH_MOD_JSON_HANDLER, mock_jh):
            result = secrets_module.set_secret("telegram", "bot", "token-val")

        assert result == tmp_path / "telegram" / "bot.json"
        mock_handler.set_secret.assert_called_once_with("telegram", "bot", "token-val", as_json=False)
        mock_jh.log_operation.assert_called_once()
        assert mock_jh.log_operation.call_args[0][0] == "secrets_set"

    def test_set_secret_as_json(self) -> None:
        """Module set_secret passes as_json through to handler."""
        mock_handler = MagicMock()
        mock_handler.set_secret.return_value = Path("/fake/path.json")
        mock_jh = MagicMock()
        data = {"bot_token": "abc"}

        with patch(PATCH_MOD_HANDLER, mock_handler), patch(PATCH_MOD_JSON_HANDLER, mock_jh):
            secrets_module.set_secret("telegram", "bot", data, as_json=True)

        mock_handler.set_secret.assert_called_once_with("telegram", "bot", data, as_json=True)


class TestSecretsHandleCommand:
    """The secrets module owns no CLI commands — get-secret routes via api_key."""

    def test_no_args_returns_false_and_is_silent(self, capsys: object) -> None:
        """Claiming a no-arg command would swallow it before api.py can reject it.

        secrets is discovered last, so returning True here makes api.py's
        "Unknown command" branch unreachable for every unknown command.
        """
        assert secrets_module.handle_command("bogus-command", []) is False
        assert capsys.readouterr().out == ""  # type: ignore[union-attr]

    def test_help_flag_returns_false_and_is_silent(self, capsys: object) -> None:
        """A trailing help flag for another module's command is not ours to answer."""
        assert secrets_module.handle_command("bogus-command", ["--help"]) is False
        assert capsys.readouterr().out == ""  # type: ignore[union-attr]
