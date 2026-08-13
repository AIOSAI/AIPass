# =================== AIPass ====================
# Name: test_admin_lane.py
# Description: Tests for admin-grant verification + dispatch wiring (FPLAN-0401 Phase 4)
# Version: 1.0.0
# Created: 2026-08-12
# Modified: 2026-08-12
# =============================================

"""Tests for the admin dispatch lane's decision half.

Split by responsibility:
  - what the flag ROUTES -> test_wake.py::TestAdminManagerLane
  - what EARNS the flag  -> here (5-leg verification + dispatch.py wiring)

The signing key lives outside every repo at ~/.aipass/admin_grant.key and does
not exist until Patrick's ceremony. Nothing here creates it: every test that
needs a passing signature builds a throwaway key under tmp_path and hands its
path in explicitly.
"""

import json
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from aipass.ai_mail.apps.handlers.users.verified_caller import verify_admin_caller

MOD = "aipass.ai_mail.apps.modules.dispatch"
_H_WAKE = "aipass.ai_mail.apps.handlers.dispatch.wake"
_H_SEND = "aipass.ai_mail.apps.handlers.email.send"
_H_VERIFIED = "aipass.ai_mail.apps.handlers.users.verified_caller"
_REFERENCE = "aipass.devpulse.apps.handlers.owner.admin_grant"

_KEY_HEX = "a" * 64  # 32 bytes, fixture only — never written outside tmp_path


@pytest.fixture(autouse=True)
def _clear_caller_env(monkeypatch):
    """Every test states its own caller env."""
    monkeypatch.delenv("AIPASS_CALLER_BRANCH", raising=False)
    monkeypatch.delenv("AIPASS_CALLER_CWD", raising=False)


@pytest.fixture
def ceremony(tmp_path):
    """A complete, valid post-ceremony world under tmp_path.

    Returns the paths so a test can break exactly one leg and assert that
    leg's named refusal.
    """
    from aipass.devpulse.apps.handlers.owner.admin_grant import compute_signature

    branch = tmp_path / "src" / "aipass" / "devpulse"
    (branch / "artifacts").mkdir(parents=True)

    registry_path = tmp_path / "AIPASS_REGISTRY.json"
    registry_path.write_text(
        json.dumps({"branches": [{"name": "devpulse", "email": "@devpulse", "path": str(branch), "admin": True}]}),
        encoding="utf-8",
    )

    key_path = tmp_path / "admin_grant.key"
    key_path.write_text(_KEY_HEX, encoding="utf-8")

    cert = {
        "owner": "devpulse",
        "type": "birth_certificate",
        "privileges": {"admin": True, "granted_by": "patrick", "granted": "2026-08-12"},
    }
    cert["signature"] = {"algo": "hmac-sha256", "value": compute_signature(cert, bytes.fromhex(_KEY_HEX))}
    cert_path = branch / "artifacts" / "birth_certificate.json"
    cert_path.write_text(json.dumps(cert), encoding="utf-8")

    return {"key_path": key_path, "registry_path": registry_path, "cert_path": cert_path, "cert": cert}


class TestVerifyAdminCaller:
    """The 5-leg check, reached through ai_mail's thin delegation."""

    def test_happy_path_verifies(self, ceremony, monkeypatch):
        """All five legs satisfied — the only shape that passes."""
        monkeypatch.setenv("AIPASS_CALLER_BRANCH", "devpulse")
        ok, reason = verify_admin_caller(key_path=ceremony["key_path"], registry_path=ceremony["registry_path"])
        assert ok is True, reason

    def test_unauthorized_caller_refused_at_leg_one(self, ceremony, monkeypatch):
        """A perfect ceremony grants @seedgo nothing."""
        monkeypatch.setenv("AIPASS_CALLER_BRANCH", "seedgo")
        ok, reason = verify_admin_caller(key_path=ceremony["key_path"], registry_path=ceremony["registry_path"])
        assert ok is False
        assert "leg1" in reason and "seedgo" in reason

    def test_unverifiable_caller_refused(self, ceremony):
        """No caller rail at all — refused, not assumed."""
        ok, reason = verify_admin_caller(key_path=ceremony["key_path"], registry_path=ceremony["registry_path"])
        assert ok is False
        assert "leg1" in reason

    def test_missing_key_is_lane_dark(self, ceremony, monkeypatch):
        """Today's reality until the ceremony: no key, no lane, named reason."""
        monkeypatch.setenv("AIPASS_CALLER_BRANCH", "devpulse")
        ceremony["key_path"].unlink()
        ok, reason = verify_admin_caller(key_path=ceremony["key_path"], registry_path=ceremony["registry_path"])
        assert ok is False
        assert "leg4" in reason and "lane dark" in reason.lower()

    def test_tampered_cert_is_refused(self, ceremony, monkeypatch):
        """One field edited after signing — signature no longer matches."""
        monkeypatch.setenv("AIPASS_CALLER_BRANCH", "devpulse")
        cert = ceremony["cert"]
        cert["privileges"]["granted_by"] = "not-patrick"
        ceremony["cert_path"].write_text(json.dumps(cert), encoding="utf-8")

        ok, reason = verify_admin_caller(key_path=ceremony["key_path"], registry_path=ceremony["registry_path"])
        assert ok is False
        assert "leg4" in reason and "tampered" in reason.lower()

    def test_foreign_key_is_refused(self, ceremony, monkeypatch):
        """An untampered cert signed with someone else's key still fails."""
        monkeypatch.setenv("AIPASS_CALLER_BRANCH", "devpulse")
        ceremony["key_path"].write_text("b" * 64, encoding="utf-8")

        ok, reason = verify_admin_caller(key_path=ceremony["key_path"], registry_path=ceremony["registry_path"])
        assert ok is False
        assert "leg4" in reason

    def test_registry_flag_missing_is_refused(self, ceremony, monkeypatch):
        """Leg 5: a signed cert without the roster flag is an incomplete ceremony."""
        monkeypatch.setenv("AIPASS_CALLER_BRANCH", "devpulse")
        registry = json.loads(ceremony["registry_path"].read_text(encoding="utf-8"))
        del registry["branches"][0]["admin"]
        ceremony["registry_path"].write_text(json.dumps(registry), encoding="utf-8")

        ok, reason = verify_admin_caller(key_path=ceremony["key_path"], registry_path=ceremony["registry_path"])
        assert ok is False
        assert "leg5" in reason

    def test_admin_privilege_absent_is_refused(self, ceremony, monkeypatch):
        """Leg 3: a correctly signed cert that grants nothing grants nothing."""
        from aipass.devpulse.apps.handlers.owner.admin_grant import compute_signature

        monkeypatch.setenv("AIPASS_CALLER_BRANCH", "devpulse")
        cert = {"owner": "devpulse", "type": "birth_certificate", "privileges": {"admin": False}}
        cert["signature"] = {"algo": "hmac-sha256", "value": compute_signature(cert, bytes.fromhex(_KEY_HEX))}
        ceremony["cert_path"].write_text(json.dumps(cert), encoding="utf-8")

        ok, reason = verify_admin_caller(key_path=ceremony["key_path"], registry_path=ceremony["registry_path"])
        assert ok is False
        assert "leg3" in reason

    def test_delegates_to_the_devpulse_reference(self, monkeypatch):
        """One implementation, no drift: the contract is devpulse's to hold."""
        monkeypatch.setenv("AIPASS_CALLER_BRANCH", "devpulse")
        sentinel = (True, "admin grant verified")
        with patch(f"{_REFERENCE}.verify_admin_grant", MagicMock(return_value=sentinel)) as ref:
            assert verify_admin_caller() == sentinel
        ref.assert_called_once()

    def test_import_failure_is_lane_dark_not_a_crash(self, monkeypatch):
        """If the reference cannot be imported the lane closes, fail-closed.

        A dispatch must not die because an optional privilege path is missing.
        """
        monkeypatch.setenv("AIPASS_CALLER_BRANCH", "devpulse")
        import builtins

        real_import = builtins.__import__

        def _boom(name, *args, **kwargs):
            """Import hook that hides the reference implementation."""
            if "admin_grant" in name:
                raise ImportError("simulated missing reference")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _boom)
        ok, reason = verify_admin_caller()
        assert ok is False
        assert "lane dark" in reason.lower()

    def test_real_key_path_is_not_touched_by_this_suite(self):
        """Guard: the ceremony key must not be created by a test run."""
        assert not (Path.home() / ".aipass" / "admin_grant.key").exists(), (
            "a test created the real signing key — fixtures must stay under tmp_path"
        )


def _wake_spy(calls: list):
    """wake_branch stand-in recording the admin flag it was handed."""
    mock_status = MagicMock()
    mock_status.format.return_value = "OK"

    def mock_wake(branch, msg=None, fresh=False, sender="@devpulse", model=None, **kwargs):
        """Track the admin keyword reaching wake_branch."""
        calls.append({"branch": branch, "sender": sender, "admin": kwargs.get("admin")})
        return (mock_status, True)

    return mock_wake


def _send_patches(overrides: dict) -> ExitStack:
    """Default patch set for _orchestrate_dispatch_send (mirrors test_dispatch_module)."""
    defaults = {
        f"{_H_SEND}.resolve_sender_info": MagicMock(return_value={"email_address": "@devpulse"}),
        "aipass.ai_mail.apps.handlers.email.header.prepend_dispatch_header": MagicMock(return_value="body"),
        f"{_H_SEND}.send_to_single": MagicMock(return_value=(True, None)),
        "aipass.ai_mail.apps.handlers.email.error_dispatch.on_email_delivered": MagicMock(),
        "aipass.ai_mail.apps.handlers.users.user.get_current_user": MagicMock(return_value={"name": "t"}),
        "aipass.ai_mail.apps.handlers.registry.read.get_branch_by_email": MagicMock(return_value={}),
        "aipass.ai_mail.apps.handlers.central_writer.update_central": MagicMock(),
        "aipass.ai_mail.apps.handlers.email.create.create_email_file": MagicMock(),
        "aipass.ai_mail.apps.handlers.email.create.load_email_file": MagicMock(),
        "aipass.ai_mail.apps.handlers.email.delivery.deliver_email_to_branch": MagicMock(),
        "aipass.ai_mail.apps.handlers.email.error_dispatch.dispatch_send_error": MagicMock(),
        "aipass.trigger.apps.modules.core.trigger": MagicMock(),
    }
    defaults.update(overrides)
    stack = ExitStack()
    for target, mock_obj in defaults.items():
        stack.enter_context(patch(target, mock_obj))
    return stack


class TestDispatchSendAdminWiring:
    """dispatch.py decides admin (it holds the caller env) and threads a bool."""

    @pytest.fixture(autouse=True)
    def _quiet(self, monkeypatch):
        """Silence module output; tests that read it install their own console."""
        monkeypatch.setattr(f"{MOD}.console", MagicMock())
        monkeypatch.setattr(f"{MOD}.error", lambda msg: None)

    def test_verified_admin_threads_admin_true(self, monkeypatch):
        """The lane opens only on a verified grant."""
        monkeypatch.setenv("AIPASS_CALLER_BRANCH", "devpulse")
        calls: list = []
        with _send_patches(
            {
                f"{_H_WAKE}.wake_branch": MagicMock(side_effect=_wake_spy(calls)),
                f"{_H_VERIFIED}.verify_admin_caller": MagicMock(return_value=(True, "admin grant verified")),
            }
        ):
            from aipass.ai_mail.apps.modules.dispatch import _orchestrate_dispatch_send

            _orchestrate_dispatch_send(["@target", "Subject", "Body"])

        assert len(calls) == 1
        assert calls[0]["admin"] is True

    def test_unverified_caller_threads_admin_false(self, monkeypatch):
        """Every other citizen's dispatch is byte-identical to before."""
        monkeypatch.setenv("AIPASS_CALLER_BRANCH", "seedgo")
        calls: list = []
        with _send_patches({f"{_H_WAKE}.wake_branch": MagicMock(side_effect=_wake_spy(calls))}):
            from aipass.ai_mail.apps.modules.dispatch import _orchestrate_dispatch_send

            _orchestrate_dispatch_send(["@target", "Subject", "Body"])

        assert len(calls) == 1
        assert calls[0]["admin"] is False

    def test_no_caller_rail_threads_admin_false(self):
        """Unverifiable callers get the closed lane, no exception."""
        calls: list = []
        with _send_patches({f"{_H_WAKE}.wake_branch": MagicMock(side_effect=_wake_spy(calls))}):
            from aipass.ai_mail.apps.modules.dispatch import _orchestrate_dispatch_send

            _orchestrate_dispatch_send(["@target", "Subject", "Body"])

        assert calls[0]["admin"] is False

    def test_non_holder_caller_never_runs_the_verifier(self, monkeypatch):
        """No file I/O, no key read, for callers who cannot hold the grant."""
        monkeypatch.setenv("AIPASS_CALLER_BRANCH", "seedgo")
        verifier = MagicMock(return_value=(False, "leg1 caller"))
        calls: list = []
        with _send_patches(
            {
                f"{_H_WAKE}.wake_branch": MagicMock(side_effect=_wake_spy(calls)),
                f"{_H_VERIFIED}.verify_admin_caller": verifier,
            }
        ):
            from aipass.ai_mail.apps.modules.dispatch import _orchestrate_dispatch_send

            _orchestrate_dispatch_send(["@target", "Subject", "Body"])

        verifier.assert_not_called()

    def test_lane_dark_reason_is_reported_to_the_holder(self, monkeypatch):
        """Pre-ceremony devpulse must SEE why the lane did not open."""
        monkeypatch.setenv("AIPASS_CALLER_BRANCH", "devpulse")
        printed: list[str] = []
        console = MagicMock()
        console.print = lambda msg="", **kw: printed.append(str(msg))
        monkeypatch.setattr(f"{MOD}.console", console)

        calls: list = []
        with _send_patches(
            {
                f"{_H_WAKE}.wake_branch": MagicMock(side_effect=_wake_spy(calls)),
                f"{_H_VERIFIED}.verify_admin_caller": MagicMock(
                    return_value=(False, "leg4 signature: no signing key — lane dark until ceremony")
                ),
            }
        ):
            from aipass.ai_mail.apps.modules.dispatch import _orchestrate_dispatch_send

            _orchestrate_dispatch_send(["@target", "Subject", "Body"])

        assert calls[0]["admin"] is False
        assert any("lane dark" in line.lower() for line in printed), printed

    def test_dispatch_survives_a_verifier_that_raises(self, monkeypatch):
        """A privilege path that explodes must not take the mail down with it."""
        monkeypatch.setenv("AIPASS_CALLER_BRANCH", "devpulse")

        def _boom(*a, **kw):
            """Verifier that fails unexpectedly."""
            raise RuntimeError("unreadable registry")

        calls: list = []
        with _send_patches(
            {
                f"{_H_WAKE}.wake_branch": MagicMock(side_effect=_wake_spy(calls)),
                f"{_H_VERIFIED}.verify_admin_caller": MagicMock(side_effect=_boom),
            }
        ):
            from aipass.ai_mail.apps.modules.dispatch import _orchestrate_dispatch_send

            result = _orchestrate_dispatch_send(["@target", "Subject", "Body"])

        assert result is True
        assert len(calls) == 1
        assert calls[0]["admin"] is False

    def test_todays_reality_no_key_means_no_admin(self, monkeypatch):
        """End to end with the REAL verifier pre-ceremony: lane stays shut."""
        monkeypatch.setenv("AIPASS_CALLER_BRANCH", "devpulse")
        calls: list = []
        with _send_patches({f"{_H_WAKE}.wake_branch": MagicMock(side_effect=_wake_spy(calls))}):
            from aipass.ai_mail.apps.modules.dispatch import _orchestrate_dispatch_send

            _orchestrate_dispatch_send(["@target", "Subject", "Body"])

        assert calls[0]["admin"] is False
