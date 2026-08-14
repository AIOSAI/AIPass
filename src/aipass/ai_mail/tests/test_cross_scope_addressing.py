# =================== AIPass ====================
# Name: test_cross_scope_addressing.py
# Description: Tests that an out-of-scope address is refused honestly, not reported as unknown
# Version: 1.0.0
# Created: 2026-08-14
# Modified: 2026-08-14
# =============================================

"""Tests for honest refusal of hosted-project addresses (found by @api, 2026-08-14).

@api tried to mail ``@baud`` from ``src/aipass/api`` and got
``Unknown branch email: @baud (available: 17 branches)``. That message is
false: @baud is a registered citizen of the hosted project ``projects/baud``,
reachable by @devpulse's admin lane. The refusal is *correct* — fleet-to-project
initiation is walled by Patrick's ruling, replies only (DPLAN-0288) — but the
stated reason was not, so @api spent the next five minutes hunting an addressing
bug that did not exist and left two stray ping mails in @baud's inbox.

Mail has two walls in this direction and they disagreed about honesty. The
inner wall, ``_check_cross_project_boundary``, already names both projects and
says "cross-project mail refused". The outer wall, address resolution, said the
address does not exist. A caller who trips the outer wall never learns there
was a policy at all.

These tests pin the contract: **explain the wall, do not deny the address** —
and, critically, explaining must not open it. The diagnostic reads the project
registries to describe the failure and must never add them to the resolution
map, or the refusal it is describing would stop happening.
"""

import json
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest

import aipass.ai_mail.apps.handlers.email.delivery as delivery_mod
from aipass.ai_mail.apps.handlers.email.delivery import deliver_email_to_branch


# ---- Fixtures ------------------------------------------------


@pytest.fixture(autouse=True)
def _silence_json_handler():
    with patch("aipass.ai_mail.apps.handlers.email.delivery.json_handler") as mock_jh:
        mock_jh.log_operation.return_value = True
        yield mock_jh


@pytest.fixture(autouse=True)
def _silence_notifications():
    with patch.object(delivery_mod, "_emit_notification_event"):
        yield


@pytest.fixture(autouse=True)
def _not_admin():
    """The grant is dark by default; pin it so these never depend on a key."""
    with patch(
        "aipass.ai_mail.apps.handlers.users.verified_caller.is_verified_admin_caller",
        return_value=False,
    ):
        yield


@pytest.fixture
def repo_root(tmp_path, monkeypatch):
    monkeypatch.setattr(delivery_mod, "_REPO_ROOT", tmp_path)
    return tmp_path


@pytest.fixture
def noop_inbox_lock(monkeypatch):
    @contextmanager
    def _noop_lock(path):
        yield

    monkeypatch.setattr(delivery_mod, "_get_inbox_lock", lambda: _noop_lock)


@pytest.fixture
def hosted_baud(repo_root):
    """A hosted project registry exactly like projects/baud/BAUD_REGISTRY.json."""
    project = repo_root / "projects" / "baud"
    branch_dir = project / "src" / "baud" / "baud"
    branch_dir.mkdir(parents=True)
    (project / "BAUD_REGISTRY.json").write_text(
        json.dumps(
            {
                "metadata": {"project": "BAUD"},
                "branches": [{"name": "BAUD", "path": "src/baud/baud", "email": "@baud", "status": "active"}],
            }
        ),
        encoding="utf-8",
    )
    return project


def _email_data():
    return {
        "from": "@api",
        "from_name": "API",
        "to": "@baud",
        "subject": "hello",
        "message": "body",
        "timestamp": "2026-08-14T12:50:00Z",
    }


# ---- The contract --------------------------------------------


def test_hosted_project_address_is_explained_not_denied(repo_root, hosted_baud, noop_inbox_lock):
    """The exact case @api hit: @baud exists, so the refusal must not say it doesn't."""
    with patch.object(delivery_mod, "get_all_branches", return_value=[]):
        success, error = deliver_email_to_branch("@baud", _email_data())

    assert success is False
    assert "Unknown branch email" not in error, "the address exists — denying it sent @api debugging"
    assert "@baud" in error
    assert "baud" in error, "name the project the citizen belongs to"


def test_the_refusal_states_the_policy_and_the_way_through(repo_root, hosted_baud, noop_inbox_lock):
    """A wall that explains itself has to say what IS allowed."""
    with patch.object(delivery_mod, "get_all_branches", return_value=[]):
        _, error = deliver_email_to_branch("@baud", _email_data())

    lowered = error.lower()
    assert "repl" in lowered, "replies are the sanctioned channel — say so"
    assert "admin" in lowered or "devpulse" in lowered, "name who may initiate"


def test_explaining_the_wall_does_not_open_it(repo_root, hosted_baud, noop_inbox_lock):
    """The whole risk of this fix: the diagnostic must not widen resolution."""
    with patch.object(delivery_mod, "get_all_branches", return_value=[]):
        success, _ = deliver_email_to_branch("@baud", _email_data())

    assert success is False
    inbox = hosted_baud / "src" / "baud" / "baud" / ".ai_mail.local" / "inbox.json"
    assert not inbox.exists(), "delivery must not reach the hosted branch's mailbox"


def test_a_genuinely_unknown_address_still_reports_unknown(repo_root, noop_inbox_lock):
    """The honest message for a real typo is still 'unknown'."""
    with patch.object(delivery_mod, "get_all_branches", return_value=[]):
        success, error = deliver_email_to_branch("@nosuchbranch", _email_data())

    assert success is False
    assert "Unknown branch email" in error
    assert "@nosuchbranch" in error


def test_a_typo_is_not_mistaken_for_a_hosted_citizen(repo_root, hosted_baud, noop_inbox_lock):
    """Matching is exact — '@bau' is a typo, not the hosted project."""
    with patch.object(delivery_mod, "get_all_branches", return_value=[]):
        _, error = deliver_email_to_branch("@bau", _email_data())

    assert "Unknown branch email" in error


def test_an_unreadable_project_registry_falls_back_to_the_plain_message(repo_root, noop_inbox_lock):
    """A broken registry must not turn a refusal into a crash."""
    project = repo_root / "projects" / "broken"
    project.mkdir(parents=True)
    (project / "BROKEN_REGISTRY.json").write_text("{not json", encoding="utf-8")

    with patch.object(delivery_mod, "get_all_branches", return_value=[]):
        success, error = deliver_email_to_branch("@whoever", _email_data())

    assert success is False
    assert "Unknown branch email" in error


def test_no_projects_tree_at_all_is_not_an_error(repo_root, noop_inbox_lock):
    """Most installs have no projects/ directory."""
    with patch.object(delivery_mod, "get_all_branches", return_value=[]):
        success, error = deliver_email_to_branch("@whoever", _email_data())

    assert success is False
    assert "Unknown branch email" in error


def test_a_fleet_branch_still_resolves_normally(repo_root, hosted_baud, noop_inbox_lock):
    """The diagnostic sits on the failure path only — success is untouched."""
    branch_dir = repo_root / "src" / "aipass" / "devpulse"
    branch_dir.mkdir(parents=True)

    with patch.object(
        delivery_mod,
        "get_all_branches",
        return_value=[{"email": "@devpulse", "path": str(branch_dir)}],
    ):
        success, _ = deliver_email_to_branch("@devpulse", _email_data())

    assert success is True
    assert (Path(branch_dir) / ".ai_mail.local" / "inbox.json").exists()
