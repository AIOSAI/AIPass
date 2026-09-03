# ===================AIPASS====================
# META DATA HEADER
# Name: test_json_durability.py - Shared JSON Handler Durability Tests
# Date: 2026-08-18
# Version: 1.0.0
# Category: aipass/tests
#
# CHANGELOG (Max 5 entries):
#   - v1.0.0 (2026-08-18): Initial creation — os.replace retry pins (Windows sharing violation)
#
# CODE STANDARDS:
#   - Pytest function style (no unittest classes)
#   - tmp_path for file isolation — JsonHandler takes an injectable json_dir, so
#     nothing here can reach a live branch's *_json/ directory
# =============================================

"""
Durability tests for the shared JSON handler.

This module is not one branch's handler. ``aipass.aipass.shared.json_handler``
is the single write path behind three shims — @spawn, @memory and @aipass all
instantiate ``JsonHandler`` and re-export its functions — so one hole here is
three branches' hole, which is why it is pinned separately from the per-branch
suites.

Two defects meet at the swap. The first is the torn write: opening a live
document with mode "w" truncates it before the new bytes land, so a concurrent
reader sees an empty or partial file — closed by staging to a temp file in the
target's own directory and swapping with os.replace.

The second is Windows-only and was closed on 2026-08-18: os.replace raises
PermissionError while ANY reader holds the target open (no FILE_SHARE_DELETE on
Python's open), and one stuck move starved a whole CI run — 45-minute cancels.
The fix is _replace_with_retry, a bounded retry that converges on the
microsecond-scale handles a reader actually holds and then raises honestly.

The helper's own contract, the public writer's durability and the concurrent
writers race are pinned once for the whole fleet in seedgo's
tests/test_json_handler_contract.py (DPLAN-0323 phase 7, 2026-09-02), the shared
module included. What stays here is the one pin written against the class
itself: write_json routes through the helper.

Linux never raises PermissionError from os.replace on an open file, so the
routing pin spies on the helper instead of waiting for a failure — that spy is
the only cross-platform proof the retry path is on the write site at all.
"""

import os

import pytest

import aipass.aipass.shared.json_handler as json_handler_mod


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def json_dir(tmp_path):
    """A throwaway JSON directory — JsonHandler takes it by injection, no global to patch."""
    target = tmp_path / "shared_json"
    target.mkdir()
    return target


# ---------------------------------------------------------------------------
# The write site routes through the helper
# ---------------------------------------------------------------------------


def test_write_json_routes_through_the_replace_helper(json_dir, monkeypatch):
    """A bare os.replace re-introduces the whole Windows hang, and it reads as harmless."""
    calls = []
    real_replace = os.replace

    def spy(source, destination):
        calls.append((source, destination))
        real_replace(source, destination)

    monkeypatch.setattr(json_handler_mod, "_replace_with_retry", spy)

    assert json_handler_mod.JsonHandler.write_json(json_dir / "routed.json", {"ok": True}) is True

    assert len(calls) == 1, "the write did not go through _replace_with_retry"
