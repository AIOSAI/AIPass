# =================== AIPass ====================
# Name: test_env_handler.py
# Description: Tests for .env template creation handler
# Version: 1.0.0
# Created: 2026-05-12
# Modified: 2026-05-12
# =============================================

"""Tests for apps/handlers/auth/env.py -- .env template creation.

Tests:
- create_env_template: openrouter provider, custom provider, no-overwrite,
  file permissions, directory permissions, write failure
"""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from aipass.api.apps.handlers.auth.env import create_env_template


# =============================================
# create_env_template
# =============================================


class TestCreateEnvTemplate:
    """Verifies .env template creation under various conditions."""

    def test_creates_openrouter_template(self, tmp_path: Path) -> None:
        """Default openrouter provider writes a template with the expected key."""
        target = tmp_path / "secrets" / ".env"
        result = create_env_template(provider="openrouter", target_path=target)

        assert result is True
        assert target.exists()
        content = target.read_text(encoding="utf-8")
        assert "OPENROUTER_API_KEY" in content

    def test_creates_custom_provider_template(self, tmp_path: Path) -> None:
        """Custom provider name produces a matching key placeholder."""
        target = tmp_path / "secrets" / ".env"
        result = create_env_template(provider="anthropic", target_path=target)

        assert result is True
        content = target.read_text(encoding="utf-8")
        assert "ANTHROPIC_API_KEY" in content

    def test_does_not_overwrite_existing(self, tmp_path: Path) -> None:
        """Existing file is preserved and function still returns True."""
        target = tmp_path / ".env"
        target.write_text("EXISTING=content\n", encoding="utf-8")

        result = create_env_template(provider="openrouter", target_path=target)

        assert result is True
        assert target.read_text(encoding="utf-8") == "EXISTING=content\n"

    @pytest.mark.skipif(sys.platform == "win32", reason="Windows does not support Unix file permissions")
    def test_file_permissions(self, tmp_path: Path) -> None:
        """Created file has owner-only read/write (0o600)."""
        target = tmp_path / "secrets" / ".env"
        create_env_template(provider="openrouter", target_path=target)

        file_mode = stat.S_IMODE(os.stat(target).st_mode)
        assert file_mode == 0o600

    @pytest.mark.skipif(sys.platform == "win32", reason="Windows does not support Unix file permissions")
    def test_directory_permissions(self, tmp_path: Path) -> None:
        """Parent directory has owner-only access (0o700)."""
        secrets_dir = tmp_path / "secrets"
        target = secrets_dir / ".env"
        create_env_template(provider="openrouter", target_path=target)

        dir_mode = stat.S_IMODE(os.stat(secrets_dir).st_mode)
        assert dir_mode == 0o700

    def test_handles_write_failure(self, tmp_path: Path) -> None:
        """OSError during write returns False."""
        target = tmp_path / "secrets" / ".env"
        with patch("builtins.open", side_effect=OSError("disk full")):
            result = create_env_template(provider="openrouter", target_path=target)

        assert result is False


class TestDiagnoseKeySuggestsRealCommand:
    """The no-key diagnosis is the most-seen error text — it must not dead-end.

    It previously told users to run `drone @api setup`, which has never been a
    command; the real one is `init`.
    """

    def test_missing_key_message_names_init(self) -> None:
        """The suggestion points at a command api.py actually routes."""
        from aipass.api.apps.handlers.auth import keys

        with patch.object(keys, "_read_key_from_secrets", return_value=None):
            message = keys.diagnose_key("openrouter")

        assert "drone @api init" in message
        assert "drone @api setup" not in message
