# =================== AIPass ====================
# Name: test_email_module_contacts.py
# Description: Tests for email.py's address book commands - contacts and register
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-17
# =============================================

"""Tests for apps/modules/email.py's address book: handle_contacts and handle_register."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(shared) — register_contact()'s own write: tests/test_contacts.py

import pytest
from unittest.mock import patch

from aipass.ai_mail.apps.modules.email import (
    handle_contacts,
    handle_register,
)
from aipass.ai_mail.tests.support_email_module import _StdoutLines

pytestmark = pytest.mark.usefixtures("email_modules_pinned", "email_json_silenced")


class TestHandleContacts:
    """Tests for email.handle_contacts orchestrator."""

    def test_contacts_displays_branches(self, monkeypatch, capsys: pytest.CaptureFixture[str]):
        """Contacts lists all registered branches."""
        branches = [
            {"email": "@alpha", "name": "ALPHA", "path": "/src/alpha"},
            {"email": "@beta", "name": "BETA", "path": "/src/beta"},
        ]
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email.get_all_branches",
            lambda: branches,
        )
        printed = _StdoutLines(capsys)

        result = handle_contacts([])
        assert result is True
        assert any("2 branches" in p for p in printed)
        alpha_lines = [p for p in printed if "@alpha" in p]
        assert len(alpha_lines) > 0

    def test_contacts_empty(self, monkeypatch):
        """No contacts found prints error."""
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email.get_all_branches",
            lambda: [],
        )
        errors: list[str] = []
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email.error",
            lambda msg: errors.append(msg),
        )

        result = handle_contacts([])
        assert result is True
        assert any("No contacts" in e for e in errors)

    def test_contacts_exception_handled(self, monkeypatch):
        """Exception in get_all_branches is caught and error is shown."""
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email.get_all_branches",
            lambda: (_ for _ in ()).throw(RuntimeError("Registry unavailable")),
        )
        errors: list[str] = []
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email.error",
            lambda msg: errors.append(msg),
        )

        result = handle_contacts([])
        assert result is True
        assert any("Registry unavailable" in e for e in errors)


class TestHandleRegister:
    """Tests for email.handle_register orchestrator."""

    def test_register_too_few_args(self, monkeypatch):
        """Register with < 2 args prints usage error."""
        errors: list[str] = []
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email.error",
            lambda msg: errors.append(msg),
        )

        result = handle_register(["@branch"])
        assert result is True
        assert any("Usage" in e for e in errors)

    def test_register_success(self, monkeypatch, capsys: pytest.CaptureFixture[str]):
        """Successful registration prints green confirmation."""
        printed = _StdoutLines(capsys)

        # register_contact is imported locally inside handle_register,
        # so patch at the handler source module
        with patch(
            "aipass.ai_mail.apps.handlers.email.contacts.register_contact",
            return_value=True,
        ):
            result = handle_register(["@devpulse", "/path/to/inbox"])
        assert result is True
        assert any("Registered" in p and "devpulse" in p for p in printed)

    def test_register_failure(self, monkeypatch):
        """Failed registration prints error."""
        errors: list[str] = []
        monkeypatch.setattr(
            "aipass.ai_mail.apps.modules.email.error",
            lambda msg: errors.append(msg),
        )

        with patch(
            "aipass.ai_mail.apps.handlers.email.contacts.register_contact",
            return_value=False,
        ):
            result = handle_register(["@badstuff", "/path/to/inbox"])
        assert result is True
        assert any("Failed" in e for e in errors)

    def test_register_with_project_arg(self, monkeypatch):
        """Third arg is passed as project name."""
        registered_args: list[tuple] = []

        def _mock_register(name, project, path):
            """Capture register_contact arguments for assertion."""
            registered_args.append((name, project, path))
            return True

        with patch(
            "aipass.ai_mail.apps.handlers.email.contacts.register_contact",
            side_effect=_mock_register,
        ):
            result = handle_register(["@vera", "/path/to/inbox", "VeraStudio"])
        assert result is True
        assert registered_args[0] == ("vera", "VeraStudio", "/path/to/inbox")
