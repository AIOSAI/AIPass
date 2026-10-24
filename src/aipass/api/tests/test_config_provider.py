# =================== AIPass ====================
# Name: test_config_provider.py
# Description: Tests for provider configuration handler
# Version: 1.0.1
# Created: 2026-04-03
# Modified: 2026-10-24
# =============================================

"""Tests for apps/handlers/config/provider.py, the provider configuration handler."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(constant) — PROVIDER_DEFAULTS is data only; key rules live in auth/keys.py, tests/test_api_key.py
# seedgo: no-test-needed(ruff) — that the handler parses and imports

from aipass.api.apps.handlers.config import provider as config_provider  # noqa: F401 — the import is the check
