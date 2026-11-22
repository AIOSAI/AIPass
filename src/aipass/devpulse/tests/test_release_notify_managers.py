# =================== AIPass ====================
# Name: test_release_notify_managers.py
# Description: Tests for release_notify manager discovery's declared roots
# Version: 1.2.0
# Created: 2026-11-09
# Modified: 2026-11-22
# =============================================

"""Tests for apps/handlers/release_notify/managers.py: declared roots come through memory's door."""

# The declared pass — what is NOT tested here, and what covers it instead:
# sentry: no-test-needed(ruff) — that handlers/release_notify/managers.py parses and imports
# sentry: no-test-needed(covered_elsewhere) — which AIPASS_ROOTS.json rows the door refuses: memory's own tests

import json
from pathlib import Path

from aipass.cli import display
from aipass.devpulse.apps.handlers.release_notify import managers
from aipass.devpulse.apps.modules import release_notify


def test_discover_managers_lists_a_declared_root_through_the_door(monkeypatch, tmp_path):
    """A root declared outside the repo is searched, asked of the door's declared_roots; a home row is not."""
    repo = tmp_path / "repo"
    repo.mkdir()
    ext = tmp_path / "elsewhere" / "vera"
    trinity = ext / "src" / "vera" / ".trinity"
    trinity.mkdir(parents=True)
    (ext / "VERA_REGISTRY.json").write_text(
        json.dumps({"branches": [{"name": "VERA", "email": "@vera", "path": "src/vera"}]}), encoding="utf-8"
    )
    (trinity / "passport.json").write_text(
        json.dumps({"branch_info": {"branch_name": "VERA", "email": "@vera"}, "citizen_class": "manager"}),
        encoding="utf-8",
    )
    # "." is AIPass home itself: the door refuses it, a private parser would walk the whole repo.
    rows = [{"path": str(ext), "status": "active"}, {"path": ".", "status": "active"}]
    (repo / "AIPASS_ROOTS.json").write_text(json.dumps({"roots": rows}), encoding="utf-8")

    asked: list[Path | None] = []
    door = managers.fleet_declared_roots
    monkeypatch.setattr(managers, "fleet_declared_roots", lambda root=None: asked.append(root) or door(root))
    monkeypatch.setattr(managers, "aipass_root", lambda: repo)

    discovery = managers.discover_managers()

    assert asked == [repo]
    assert discovery["roots"] == [str(ext.resolve())]
    assert [entry["address"] for entry in discovery["managers"]] == ["@vera"]


def test_discover_managers_skips_an_unrendered_template_passport(monkeypatch, tmp_path):
    """A template passport ({{name}} placeholders) under a declared root is scaffold, never a recipient."""
    repo = tmp_path / "repo"
    repo.mkdir()
    ext = tmp_path / "elsewhere" / "seedish"
    template_trinity = ext / "src" / "spawn" / "templates" / "manager" / ".trinity"
    template_trinity.mkdir(parents=True)
    (template_trinity / "passport.json").write_text(
        json.dumps({"branch_info": {"branch_name": "{{name}}", "email": "@{{name}}"}, "citizen_class": "manager"}),
        encoding="utf-8",
    )
    rows = [{"path": str(ext), "status": "active"}]
    (repo / "AIPASS_ROOTS.json").write_text(json.dumps({"roots": rows}), encoding="utf-8")
    monkeypatch.setattr(managers, "aipass_root", lambda: repo)

    discovery = managers.discover_managers()

    assert discovery["managers"] == []
    assert any("template passport" in entry["reason"] for entry in discovery["skipped"])


def _stub_notify_edges(monkeypatch, managers, send_result):
    """Hold the command's disk, network and compose edges so only the fan-out's outcome shows."""
    monkeypatch.setattr(release_notify, "discover_managers", lambda: {"managers": managers, "skipped": [], "roots": []})
    monkeypatch.setattr(release_notify, "changelog_headline", lambda *a, **k: [])
    monkeypatch.setattr(release_notify, "load_state", lambda: {"versions": {}})
    monkeypatch.setattr(release_notify, "record_notified", lambda *a, **k: Path("stamp.json"))
    monkeypatch.setattr(release_notify, "post_commons", lambda *a, **k: (True, ""))
    monkeypatch.setattr(release_notify, "send_email", lambda *a, **k: send_result)


def test_release_notify_skips_a_no_mailbox_address_without_failing_the_run(monkeypatch, capsys):
    """ai_mail's no-mailbox refusal reads 'skipped, no mailbox' and leaves the command's exit clean."""
    reason = "exit 1: Failed to deliver: Unknown branch email: @seed (available: 12 branches)"
    _stub_notify_edges(monkeypatch, [{"address": "@seed", "name": "Seed", "passport": "p"}], (False, reason))

    release_notify.handle_command("release-notify", ["v2.8.4"])

    out, _ = capsys.readouterr()
    assert "skipped, no mailbox" in out
    assert not display.command_failed()


def test_release_notify_still_fails_the_run_on_a_real_send_failure(monkeypatch, capsys):
    """A send that failed for any other reason still reads FAILED and still fails the command."""
    _stub_notify_edges(
        monkeypatch, [{"address": "@grow", "name": "Grow", "passport": "p"}], (False, "exit 1: timed out after 120s")
    )

    release_notify.handle_command("release-notify", ["v2.8.4"])

    out, _ = capsys.readouterr()
    assert "FAILED" in out
    assert display.command_failed()
