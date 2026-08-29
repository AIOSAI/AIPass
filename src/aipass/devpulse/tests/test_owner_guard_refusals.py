# =================== AIPass ====================
# Name: test_owner_guard_refusals.py
# Description: Pins the refusal-exit contract on the owner-gated modules (FPLAN-0455)
# Version: 1.0.0
# Created: 2026-08-28
# Modified: 2026-08-28
# =============================================

"""Owner-guard refusals must mark the command failed — the exit-0 species pinned.

The 2026-08-22 defect: refusals rendered with ``warning()``, which never calls
``mark_command_failed()``, so ``feedback inbox && next`` and the admin_grant
ceremony verbs reported success to the shell while doing nothing. The fixes
landed with scar docstrings but no pins — these tests are the pins, one per
guarded module, asserting the FAILURE MARK (the code contract) rather than the
wording (the human contract). compass and watchdog carry their own pins in
their own files; these cover the two that had none.
"""

from unittest.mock import patch

import pytest

from aipass.devpulse.apps.handlers.owner import guard as owner_guard
from aipass.devpulse.apps.modules import admin_grant as admin_grant_module
from aipass.devpulse.apps.modules import feedback as feedback_module


@pytest.fixture
def marks(monkeypatch):
    """Collect mark_command_failed() calls; refusals must append, successes must not."""
    from aipass.cli.apps.modules import display as cli_display

    collected: list[int] = []
    monkeypatch.setattr(cli_display, "mark_command_failed", lambda: collected.append(1))
    return collected


@pytest.fixture
def not_the_owner():
    """This seat is not the owner — the guard refuses, an owner address exists."""
    with (
        patch.object(owner_guard, "guard_owner_caller", return_value=False),
        patch.object(owner_guard, "owner_address", return_value="@devpulse"),
    ):
        yield


def test_feedback_owner_refusal_marks_the_command_failed(capsys, marks, not_the_owner):
    assert feedback_module.handle_command("feedback", ["inbox"]) is True
    capsys.readouterr()
    assert marks, "a refused owner gate must mark the command failed, not exit 0"


def test_feedback_help_stays_open_and_unmarked(capsys, marks, not_the_owner):
    """--help is an open verb: no gate consulted, no failure marked."""
    assert feedback_module.handle_command("feedback", ["--help"]) is True
    capsys.readouterr()
    assert marks == []


@pytest.mark.parametrize("verb", ["keygen", "mint"])
def test_admin_grant_ceremony_refusal_marks_the_command_failed(capsys, marks, not_the_owner, verb):
    assert admin_grant_module.handle_command("admin_grant", [verb]) is True
    capsys.readouterr()
    assert marks, f"a refused '{verb}' must mark the command failed, not exit 0"


def test_admin_grant_unknown_verb_marks_the_command_failed(capsys, marks):
    """The unknown-verb refusal ran nothing — chains need the exit code to say so."""
    assert admin_grant_module.handle_command("admin_grant", ["frobnicate"]) is True
    capsys.readouterr()
    assert marks
