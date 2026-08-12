# =================== AIPass ====================
# Name: test_hooks_track_e.py
# Description: DPLAN-0139 Track E — single-path enforcement tests
# Version: 1.2.0
# Created: 2026-04-21
# Modified: 2026-08-04
# =============================================
"""Tests for DPLAN-0139 Track E — single-path enforcement.

Covers:
  - permissions.py: TRUSTED_CROSS_WRITERS, is_trusted_caller(), identify_caller()
  - drone auth.py: no name-based caller list (owner-tier is earned per-repo, DPLAN-0281)
  - inbox_audit.py: handle_command routing + _scan_inbox validation
  - delivery.py: deliver_to_inbox_file single-path helper
"""

import importlib.util
import json
from pathlib import Path
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_repo_root() -> Path:
    """Walk up from this file to find the git repo root."""
    current = Path(__file__).resolve().parent
    for parent in (current, *current.parents):
        if (parent / ".git").exists():
            return parent
    return Path(__file__).resolve().parents[4]


REPO_ROOT = _find_repo_root()


# ---------------------------------------------------------------------------
# permissions.py
# ---------------------------------------------------------------------------


def test_trusted_cross_writers_contains_expected_members():
    """TRUSTED_CROSS_WRITERS must include devpulse, seedgo, and spawn."""
    from aipass.seedgo.apps.modules.permissions import TRUSTED_CROSS_WRITERS

    assert "devpulse" in TRUSTED_CROSS_WRITERS
    assert "seedgo" in TRUSTED_CROSS_WRITERS
    assert "spawn" in TRUSTED_CROSS_WRITERS


def test_is_trusted_caller_returns_true_for_devpulse():
    """devpulse is a trusted cross-writer."""
    from aipass.seedgo.apps.modules.permissions import is_trusted_caller

    assert is_trusted_caller("devpulse") is True


def test_is_trusted_caller_returns_true_for_seedgo():
    """seedgo is a trusted cross-writer."""
    from aipass.seedgo.apps.modules.permissions import is_trusted_caller

    assert is_trusted_caller("seedgo") is True


def test_is_trusted_caller_returns_true_for_spawn():
    """spawn is a trusted cross-writer."""
    from aipass.seedgo.apps.modules.permissions import is_trusted_caller

    assert is_trusted_caller("spawn") is True


def test_is_trusted_caller_returns_false_for_unknown():
    """Regular branches are not trusted cross-writers."""
    from aipass.seedgo.apps.modules.permissions import is_trusted_caller

    assert is_trusted_caller("flow") is False
    assert is_trusted_caller("memory") is False
    assert is_trusted_caller("random_branch") is False


def test_identify_caller_returns_empty_when_no_passport(tmp_path):
    """identify_caller returns empty string when no passport.json is found."""
    from aipass.seedgo.apps.modules.permissions import identify_caller

    result = identify_caller(str(tmp_path))
    assert result == ""


def test_identify_caller_reads_branch_name_from_passport(tmp_path):
    """identify_caller reads branch_name from branch_info section."""
    from aipass.seedgo.apps.modules.permissions import identify_caller

    trinity = tmp_path / ".trinity"
    trinity.mkdir()
    passport = trinity / "passport.json"
    passport.write_text(json.dumps({"branch_info": {"branch_name": "testbranch"}}), encoding="utf-8")
    result = identify_caller(str(tmp_path))
    assert result == "testbranch"


def test_identify_caller_falls_back_to_identity_name(tmp_path):
    """identify_caller falls back to identity.name when branch_info absent."""
    from aipass.seedgo.apps.modules.permissions import identify_caller

    trinity = tmp_path / ".trinity"
    trinity.mkdir()
    passport = trinity / "passport.json"
    passport.write_text(json.dumps({"identity": {"name": "fallback_branch"}}), encoding="utf-8")
    result = identify_caller(str(tmp_path))
    assert result == "fallback_branch"


# ---------------------------------------------------------------------------
# drone auth.py — no name-based caller list (DPLAN-0281)
# ---------------------------------------------------------------------------


def test_drone_auth_has_no_hardcoded_caller_list():
    """Owner-tier git is earned per-repo, never granted by name (DPLAN-0281).

    The old ALLOWED_CALLERS constant read as though seedgo and spawn held git
    write — they never did; verify_git_access ignored it. Its absence is
    load-bearing: this test failing means someone reintroduced a name-based
    gate, which is exactly the special-casing the Patrick ruling removed.
    """
    from aipass.drone.apps.plugins.devpulse_ops import auth

    assert not hasattr(auth, "ALLOWED_CALLERS")
    for tier in auth.GIT_ACCESS_TIERS.values():
        assert "allowed_callers" not in tier


# ---------------------------------------------------------------------------
# inbox_audit.py — handle_command routing + _scan_inbox
# ---------------------------------------------------------------------------


def test_inbox_audit_ignores_non_audit_command():
    """handle_command returns False for non-audit command names."""
    from aipass.seedgo.apps.modules.inbox_audit import handle_command

    assert handle_command("standards_query", ["inbox-ids"]) is False
    assert handle_command("checklist", ["inbox-ids"]) is False


def test_inbox_audit_handles_inbox_ids_subcommand():
    """handle_command returns True and runs scan for `audit inbox-ids`."""
    from aipass.seedgo.apps.modules.inbox_audit import handle_command

    with patch("aipass.seedgo.apps.modules.inbox_audit._run_inbox_id_scan", return_value=0):
        result = handle_command("audit", ["inbox-ids"])
    assert result is True


def test_inbox_audit_ignores_other_audit_subcommands():
    """handle_command returns False for audit subcommands other than inbox-ids."""
    from aipass.seedgo.apps.modules.inbox_audit import handle_command

    assert handle_command("audit", ["aipass"]) is False
    assert handle_command("audit", ["flow"]) is False


def test_inbox_audit_scan_detects_bad_id(tmp_path):
    """_scan_inbox flags message ids that are not 8-char lowercase hex."""
    from aipass.seedgo.apps.modules.inbox_audit import _scan_inbox

    inbox = tmp_path / "inbox.json"
    inbox.write_text(
        json.dumps(
            {
                "messages": [
                    {"id": "not-hex!", "subject": "bad", "from": "@test", "status": "new"},
                    {"id": "a1b2c3d4", "subject": "ok", "from": "@test", "status": "new"},
                ]
            }
        ),
        encoding="utf-8",
    )
    violations = _scan_inbox(inbox)
    assert len(violations) == 1
    assert violations[0]["id"] == "not-hex!"


def test_inbox_audit_scan_passes_valid_ids(tmp_path):
    """_scan_inbox returns empty list when all message ids are valid 8-hex."""
    from aipass.seedgo.apps.modules.inbox_audit import _scan_inbox

    inbox = tmp_path / "inbox.json"
    inbox.write_text(
        json.dumps(
            {
                "messages": [
                    {"id": "a1b2c3d4", "subject": "ok1", "from": "@x", "status": "new"},
                    {"id": "deadbeef", "subject": "ok2", "from": "@y", "status": "new"},
                ]
            }
        ),
        encoding="utf-8",
    )
    violations = _scan_inbox(inbox)
    assert violations == []


# ---------------------------------------------------------------------------
# delivery.py — deliver_to_inbox_file single-path helper
# Load by file path to avoid cross-branch package import restriction.
# ---------------------------------------------------------------------------


def _load_delivery():
    """Load ai_mail delivery.py by file path (bypasses cross-branch import check)."""
    delivery_path = REPO_ROOT / "src" / "aipass" / "ai_mail" / "apps" / "handlers" / "email" / "delivery.py"
    if not delivery_path.exists():
        pytest.skip(f"delivery.py not found: {delivery_path}")
    spec = importlib.util.spec_from_file_location("delivery", delivery_path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_deliver_to_inbox_file_returns_false_for_missing_inbox(tmp_path):
    """deliver_to_inbox_file returns (False, error, '') when inbox does not exist."""
    delivery = _load_delivery()
    missing = tmp_path / "inbox.json"
    success, error_msg, reply_id = delivery.deliver_to_inbox_file(
        missing,
        {"from": "@x", "to": "@y", "subject": "s", "message": "m", "timestamp": "t"},
    )
    assert success is False
    assert reply_id == ""


def test_deliver_to_inbox_file_writes_message_and_returns_id(tmp_path):
    """deliver_to_inbox_file writes to inbox and returns the assigned 8-char id."""
    delivery = _load_delivery()
    inbox = tmp_path / "inbox.json"
    inbox.write_text(
        json.dumps({"mailbox": "inbox", "total_messages": 0, "unread_count": 0, "messages": []}),
        encoding="utf-8",
    )
    email_data = {
        "from": "@sender",
        "to": "@recv",
        "subject": "Hello",
        "message": "body",
        "timestamp": "2026-04-21 00:00:00",
    }
    with patch.object(delivery, "_emit_notification_event"):
        success, error_msg, reply_id = delivery.deliver_to_inbox_file(inbox, email_data)

    assert success is True
    assert len(reply_id) == 8
    data = json.loads(inbox.read_text())
    assert len(data["messages"]) == 1
    assert data["messages"][0]["id"] == reply_id
