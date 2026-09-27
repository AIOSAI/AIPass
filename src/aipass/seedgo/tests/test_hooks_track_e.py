# =================== AIPass ====================
# Name: test_hooks_track_e.py
# Description: DPLAN-0139 Track E — single-path enforcement tests
# Version: 1.3.0
# Created: 2026-04-21
# Modified: 2026-09-27
# =============================================
"""Tests for apps/modules/permissions.py and apps/modules/inbox_audit.py, DPLAN-0139 Track E single-path enforcement."""

# Covers:
#   - permissions.py: TRUSTED_CROSS_WRITERS, is_trusted_caller(), identify_caller()
#   - drone auth.py: no name-based caller list (owner-tier is earned per-repo, DPLAN-0281)
#   - inbox_audit.py: handle_command routing, and the inbox-ids scan's live-inbox and id validation
#   - delivery.py: deliver_to_inbox_file single-path helper

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that modules/permissions.py and modules/inbox_audit.py parse and import
# seedgo: no-test-needed(stdlib) — Path.rglob's walk; the tests choose only the root it starts from

import importlib.util
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from aipass.drone.apps.plugins.devpulse_ops import auth
from aipass.seedgo.apps.modules import inbox_audit, permissions
from aipass.seedgo.apps.modules.inbox_audit import handle_command
from aipass.seedgo.apps.modules.permissions import TRUSTED_CROSS_WRITERS, identify_caller, is_trusted_caller


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
    assert "devpulse" in TRUSTED_CROSS_WRITERS
    assert "seedgo" in TRUSTED_CROSS_WRITERS
    assert "spawn" in TRUSTED_CROSS_WRITERS


def test_is_trusted_caller_returns_true_for_devpulse():
    """devpulse is a trusted cross-writer."""
    assert is_trusted_caller("devpulse") is True


def test_is_trusted_caller_returns_true_for_seedgo():
    """seedgo is a trusted cross-writer."""
    assert is_trusted_caller("seedgo") is True


def test_is_trusted_caller_returns_true_for_spawn():
    """spawn is a trusted cross-writer."""
    assert is_trusted_caller("spawn") is True


def test_is_trusted_caller_returns_false_for_unknown():
    """Regular branches are not trusted cross-writers."""
    assert is_trusted_caller("flow") is False
    assert is_trusted_caller("memory") is False
    assert is_trusted_caller("random_branch") is False


def test_identify_caller_returns_empty_when_no_passport(tmp_path):
    """identify_caller returns empty string when no passport.json is found."""
    result = identify_caller(str(tmp_path))
    assert result == ""


def test_identify_caller_reads_branch_name_from_passport(tmp_path):
    """identify_caller reads branch_name from branch_info section."""
    trinity = tmp_path / ".trinity"
    trinity.mkdir()
    passport = trinity / "passport.json"
    passport.write_text(json.dumps({"branch_info": {"branch_name": "testbranch"}}), encoding="utf-8")
    result = identify_caller(str(tmp_path))
    assert result == "testbranch"


def test_identify_caller_falls_back_to_identity_name(tmp_path):
    """identify_caller falls back to identity.name when branch_info absent."""
    trinity = tmp_path / ".trinity"
    trinity.mkdir()
    passport = trinity / "passport.json"
    passport.write_text(json.dumps({"identity": {"name": "fallback_branch"}}), encoding="utf-8")
    result = identify_caller(str(tmp_path))
    assert result == "fallback_branch"


def test_handle_command_prints_nothing_for_another_modules_command(capsys):
    """A module that does not own the command must not write to the display.

    route_command() calls every module's handle_command in discovery order until
    one returns True, so a module that prints while returning False dumps its
    output above the module that actually answers. permissions used to print on
    ANY no-arg or --help command, which is why the trust list appeared over
    `drone @seedgo standard`.
    """
    assert permissions.handle_command("standard", []) is False
    assert permissions.handle_command("audit", ["--help"]) is False
    assert capsys.readouterr().out == ""


def test_handle_command_claims_its_own_command_and_renders_the_trust_list(capsys):
    """`permissions` is a real command: it renders and it is claimed.

    Returning False for its own name is what produced "Unknown command:
    permissions" followed by the introspection block — the error and the answer
    for the same input. Asserting on rendered output, not on the return value
    alone, is what catches the block going missing.
    """
    assert permissions.handle_command("permissions", []) is True
    out = capsys.readouterr().out
    assert "TRUSTED_CROSS_WRITERS" in out
    for member in permissions.TRUSTED_CROSS_WRITERS:
        assert member in out

    assert permissions.handle_command("permissions", ["--help"]) is True
    assert "TRUSTED_CROSS_WRITERS" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# drone auth.py — no name-based caller list (DPLAN-0281)
# ---------------------------------------------------------------------------


def test_drone_auth_has_no_hardcoded_caller_list():
    """Owner-tier git is earned per-repo, never granted by name (DPLAN-0281).

    The old ALLOWED_CALLERS constant read as though seedgo and spawn held git
    write — they never did; verify_git_access ignored it. Its absence is
    load-bearing: this test failing means someone reintroduced a name-based
    gate, which is exactly the special-casing the owner ruling removed.
    """
    assert not hasattr(auth, "ALLOWED_CALLERS")
    for tier in auth.GIT_ACCESS_TIERS.values():
        assert "allowed_callers" not in tier


# ---------------------------------------------------------------------------
# inbox_audit.py — handle_command routing and the inbox-ids scan
# ---------------------------------------------------------------------------


def test_inbox_audit_ignores_non_audit_command():
    """handle_command returns False for non-audit command names."""
    assert handle_command("standards_query", ["inbox-ids"]) is False
    assert handle_command("checklist", ["inbox-ids"]) is False


def test_inbox_audit_handles_inbox_ids_subcommand():
    """handle_command returns True and runs scan for `audit inbox-ids`."""
    with patch("aipass.seedgo.apps.modules.inbox_audit._run_inbox_id_scan", return_value=0) as scan:
        result = handle_command("audit", ["inbox-ids"])
    assert result is True
    # The docstring promised the scan RAN; the True alone held whether it did
    # or the subcommand was claimed and dropped.
    assert scan.call_count == 1


def test_inbox_audit_ignores_other_audit_subcommands():
    """handle_command returns False for audit subcommands other than inbox-ids."""
    assert handle_command("audit", ["aipass"]) is False
    assert handle_command("audit", ["flow"]) is False


def _run_inbox_ids(root, monkeypatch, capsys):
    """Run `audit inbox-ids` over `root` as the repo root; return (out, err)."""
    monkeypatch.setattr(inbox_audit, "_find_repo_root", lambda: root)
    assert handle_command("audit", ["inbox-ids"]) is True
    return capsys.readouterr()


def _inbox(path, ids):
    """Write an inbox holding one message per id."""
    path.parent.mkdir(parents=True, exist_ok=True)
    messages = [{"id": i, "subject": f"s{n}", "from": "@test", "status": "new"} for n, i in enumerate(ids)]
    path.write_text(json.dumps({"messages": messages}), encoding="utf-8")


def test_inbox_audit_skips_archived_and_backed_up_inboxes(tmp_path, monkeypatch, capsys):
    """Mutant: _is_live_inbox ignores _DEAD_TREE_DIRS in apps/modules/inbox_audit.py — killed.

    The sweep audits LIVE mail only — a deleted branch's archived inbox is nobody's to fix.
    Live repo shapes this pins: of 109 paths matching .ai_mail.local/inbox.json,
    only 25 are live; 84 sit under .backup/ or .archive/ (deleted-branch snapshots
    and @backup's versioned copies).
    """
    _inbox(tmp_path / "flow" / ".ai_mail.local" / "inbox.json", ["a1b2c3d4"])
    for dead_root in (".backup", ".archive"):
        _inbox(tmp_path / dead_root / "deleted_branches" / "old" / ".ai_mail.local" / "inbox.json", ["not-hex!"])

    out, err = _run_inbox_ids(tmp_path, monkeypatch, capsys)
    assert "Scanning 1 live inbox file(s)" in out
    assert "Skipped 2 archived/backed-up" in out
    assert "not-hex!" not in out
    assert err == ""


def test_inbox_audit_skips_a_directory_named_inbox_json(tmp_path, monkeypatch, capsys):
    """Mutant: _is_live_inbox answers True for a directory in apps/modules/inbox_audit.py — killed.

    @backup versions a file into a DIRECTORY of the same name — 47 exist on disk.
    read_text() on one raises IsADirectoryError, which the scanner logged as a
    warning per path. 44 of the 47 sit under .ai_mail.local/ and so matched the
    sweep's glob: 44 warnings per run, for a condition no branch can act on. It
    is not an unreadable inbox, it is not an inbox.
    """
    as_dir = tmp_path / "branch" / ".ai_mail.local" / "inbox.json"
    as_dir.mkdir(parents=True)
    (as_dir / "inbox.json").write_text("{}", encoding="utf-8")

    out, _err = _run_inbox_ids(tmp_path, monkeypatch, capsys)
    assert "Scanning 0 live inbox file(s)" in out
    assert "Skipped 1 archived/backed-up" in out


def test_inbox_audit_scan_detects_bad_id(tmp_path, monkeypatch, capsys):
    """Mutant: the id pattern accepts any 8 characters in apps/modules/inbox_audit.py — killed."""
    _inbox(tmp_path / "flow" / ".ai_mail.local" / "inbox.json", ["not-hex!", "a1b2c3d4"])

    out, err = _run_inbox_ids(tmp_path, monkeypatch, capsys)
    assert "Found 1 id violation(s)" in err
    assert "id='not-hex!'" in out
    assert "id='a1b2c3d4'" not in out


def test_inbox_audit_scan_passes_valid_ids(tmp_path, monkeypatch, capsys):
    """Mutant: every id is flagged in apps/modules/inbox_audit.py — killed."""
    _inbox(tmp_path / "flow" / ".ai_mail.local" / "inbox.json", ["a1b2c3d4", "deadbeef"])

    out, err = _run_inbox_ids(tmp_path, monkeypatch, capsys)
    assert "All message ids are valid 8-char hex strings." in out
    assert err == ""


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
    data = json.loads(inbox.read_text(encoding="utf-8"))
    assert len(data["messages"]) == 1
    assert data["messages"][0]["id"] == reply_id


# ---------------------------------------------------------------------------
# Help-flag safety — help_flag_safety: a flag ANYWHERE explains, never executes
# ---------------------------------------------------------------------------


def test_inbox_ids_help_does_not_run_the_repo_wide_scan():
    """`drone @seedgo audit inbox-ids --help` walked every inbox in the repo.

    args[0] was "inbox-ids", so the module's help gate never looked at the flag
    behind it and _run_inbox_id_scan() rglob'd the whole repo root. Asserted
    against a MOCK of the scan: a test that proves a scan did not run must
    never run it to find out.
    """
    with (
        patch.object(inbox_audit, "_run_inbox_id_scan") as scan,
        patch.object(inbox_audit, "print_introspection") as shown,
    ):
        assert inbox_audit.handle_command("audit", ["inbox-ids", "--help"]) is True

    assert scan.call_count == 0
    assert shown.call_count == 1


def test_inbox_ids_still_scans_without_a_help_flag():
    """The gate must not swallow the real subcommand."""
    with patch.object(inbox_audit, "_run_inbox_id_scan", return_value=0) as scan:
        assert inbox_audit.handle_command("audit", ["inbox-ids"]) is True

    assert scan.call_count == 1


def test_inbox_audit_help_flag_does_not_claim_another_audit_subcommand():
    """Ownership first: `audit aipass --help` belongs to standards_audit, not here."""
    with patch.object(inbox_audit, "_run_inbox_id_scan") as scan:
        assert inbox_audit.handle_command("audit", ["aipass", "--help"]) is False

    assert scan.call_count == 0


def test_permissions_help_after_an_argument_explains():
    """`drone @seedgo permissions list --help` fell through to "Unknown command"."""
    with patch.object(permissions, "print_introspection") as shown:
        assert permissions.handle_command("permissions", ["list", "--help"]) is True

    assert shown.call_count == 1


def test_permissions_does_not_answer_for_another_command():
    """Ownership first: a help flag never makes a module claim a command it does not own."""
    with patch.object(permissions, "print_introspection") as shown:
        assert permissions.handle_command("checklist", ["--help"]) is False

    assert shown.call_count == 0
