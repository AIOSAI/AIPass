# =================== AIPass ====================
# Name: test_public_surface.py
# Description: Tests for ai_mail's package-level public surface (the feed, register, outstanding and inbox doors)
# Version: 1.3.0
# Created: 2026-08-16
# Modified: 2026-11-16
# =============================================

"""Tests for aipass/ai_mail/__init__.py's public surface: feed_path(), register_path(), outstanding_dispatches()."""

# notify.py imports prax's logger, so the door is a function and FEED_PATH resolves lazily
# through PEP 562 __getattr__; feed_path() is the one construction site for the path.

# The declared pass — what is NOT tested here, and what covers it instead:

import importlib
import json
import subprocess
import sys

from pathlib import Path

import pytest

import aipass.ai_mail as ai_mail
import aipass.ai_mail.apps.handlers.notify as notify
from aipass.ai_mail import feed_path, register_path
from aipass.ai_mail.apps.handlers.dispatch import register
from aipass.ai_mail.apps.handlers.users import verified_caller

_H = "aipass.ai_mail.apps.handlers"
DOOR_HOMES = {
    "is_verified_admin_caller": f"{_H}.users.verified_caller",
    "resolve_verified_caller": f"{_H}.users.verified_caller",
    "wake_branch": f"{_H}.dispatch.wake",
    "is_wake_blocked": f"{_H}.dispatch.wake",
    "resolve_resume_target": f"{_H}.dispatch.session_pointer",
    "write_pointer": f"{_H}.dispatch.session_pointer",
    "read_pointer": f"{_H}.dispatch.session_pointer",
    "mint_session_id": f"{_H}.dispatch.session_pointer",
    "transcript_dir": f"{_H}.dispatch.session_pointer",
    "codex_thread_file": f"{_H}.dispatch.session_pointer",
    "opencode_db": f"{_H}.dispatch.session_pointer",
    "CLAUDE": f"{_H}.dispatch.session_pointer",
    "CODEX": f"{_H}.dispatch.session_pointer",
    "OPENCODE": f"{_H}.dispatch.session_pointer",
    "granted": f"{_H}.dispatch.grant",
    "open_grants": f"{_H}.dispatch.grant",
    "GRANT_KEY": f"{_H}.dispatch.grant",
    "deliver_email_to_branch": f"{_H}.email.delivery",
}


def _clean_probe(code: str) -> str:
    """Run code in a fresh interpreter, where the suite's own imports cannot hide a load."""
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert done.returncode == 0, done.stderr[-600:]
    return done.stdout.strip()


class TestFeedPathDoor:
    """The public surface @api asked for."""

    def test_feed_path_is_importable_from_the_package(self):
        assert callable(feed_path)

    def test_feed_path_matches_the_handler_implementation(self):
        """The door and the implementation must never disagree."""
        assert ai_mail.feed_path() == notify.feed_path()

    def test_feed_path_constant_is_reachable_from_the_package(self):
        """@api asked for the constant by name; keep it working."""
        assert ai_mail.FEED_PATH == notify.FEED_PATH

    def test_the_constant_door_reads_through_instead_of_snapshotting(self, monkeypatch, tmp_path):
        """``ai_mail.FEED_PATH`` must follow a patched ``notify.FEED_PATH``.

        A snapshotting export would hand consumers' tests the live feed.
        """
        redirected = tmp_path / "elsewhere" / "notifications.jsonl"
        monkeypatch.setattr(notify, "FEED_PATH", redirected)

        assert ai_mail.FEED_PATH == redirected

    def test_feed_path_returns_a_path_not_a_string(self):
        """A Path — and an ABSOLUTE one, which is the half nothing else pins."""
        resolved = ai_mail.feed_path()

        assert isinstance(resolved, Path)
        assert resolved.is_absolute(), resolved

    def test_the_feed_lives_where_the_contract_says(self):
        """<repo root>/.aipass/notifications.jsonl — the documented location."""
        resolved = ai_mail.feed_path()
        assert resolved.name == "notifications.jsonl"
        assert resolved.parent.name == ".aipass"

    def test_feed_path_resolves_fresh_at_call_time(self, monkeypatch, tmp_path):
        """A function, not a frozen constant."""
        monkeypatch.setattr(notify, "find_repo_root", lambda: tmp_path)

        assert notify.feed_path() == tmp_path / ".aipass" / "notifications.jsonl"

    def test_the_constant_is_built_by_the_function(self):
        """One construction site — checked where conftest has not redirected it.

        The autouse fixture patches notify.FEED_PATH, so only a clean interpreter sees the import-time value.
        """
        probe = "import aipass.ai_mail.apps.handlers.notify as n; print(int(n.FEED_PATH == n.feed_path()))"
        result = subprocess.run(
            [sys.executable, "-c", probe],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
        )

        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "1"

    def test_unknown_attribute_still_raises_attribute_error(self):
        """PEP 562 __getattr__ must not swallow real typos."""
        with pytest.raises(AttributeError, match="no_such_thing"):
            ai_mail.no_such_thing  # type: ignore[attr-defined]

    def test_the_door_is_advertised_in_dunder_all(self):
        assert "feed_path" in ai_mail.__all__
        assert "FEED_PATH" in ai_mail.__all__


class TestRegisterDoor:
    """The second door, asked for by @devpulse."""

    def test_register_path_is_importable_from_the_package(self):
        assert callable(register_path)

    def test_register_path_matches_the_handler_implementation(self):
        assert ai_mail.register_path() == register.register_file()

    def test_the_register_lives_where_the_contract_says(self):
        path = ai_mail.register_path()

        assert path.name == "dispatch_register.jsonl"
        assert path.parent.name == ".aipass"

    def test_register_path_returns_a_path_not_a_string(self):
        """The feed door's own lesson, reused: a Path, and an absolute one."""
        resolved = ai_mail.register_path()

        assert isinstance(resolved, Path)
        assert resolved.is_absolute(), resolved

    def test_register_path_resolves_fresh_at_call_time(self, monkeypatch, tmp_path):
        """A function, not a frozen constant — the feed's own lesson, reused."""
        monkeypatch.setattr(register, "find_repo_root", lambda: tmp_path)

        assert ai_mail.register_path() == tmp_path / ".aipass" / "dispatch_register.jsonl"

    def test_both_doors_are_advertised_in_dunder_all(self):
        assert "register_path" in ai_mail.__all__
        assert "outstanding_dispatches" in ai_mail.__all__


class TestOutstandingDoor:
    """Why the RECONSTRUCTION is exported too, not just the path."""

    def test_a_closed_dispatch_is_not_outstanding_through_the_door(self, tmp_path):
        """The append-only trap, pinned at the public surface.

        A dispatch closes by APPENDING a record; a parser taking the first record per id sees it open forever.
        """
        (tmp_path / "AIPASS_REGISTRY.json").write_text("{}", encoding="utf-8")
        dispatch_id = register.open_dispatch("@devpulse", "@ai_mail", "s", 7200, repo_root=tmp_path)
        assert dispatch_id
        assert len(ai_mail.outstanding_dispatches(tmp_path)) == 1, "anchor: it must be open first"

        register.close_dispatch(dispatch_id, "completed", repo_root=tmp_path)

        assert ai_mail.outstanding_dispatches(tmp_path) == []

    def test_each_entry_carries_the_overdue_verdict(self, tmp_path):
        (tmp_path / "AIPASS_REGISTRY.json").write_text("{}", encoding="utf-8")
        register.open_dispatch("@devpulse", "@ai_mail", "s", 7200, repo_root=tmp_path)

        assert ai_mail.outstanding_dispatches(tmp_path)[0]["overdue"] is False

    def test_a_tree_with_no_registry_marker_still_re_roots(self, monkeypatch, tmp_path):
        """@devpulse's wire raises at arm time if the register cannot be FOUND.

        So a fresh checkout with no marker must not raise, and the return stays rooted at the caller's path.
        """
        orphan = tmp_path / "no-marker"
        orphan.mkdir()
        monkeypatch.setattr(register, "find_repo_root", lambda: orphan)
        target = tmp_path / "elsewhere"

        assert ai_mail.outstanding_dispatches(target) == []
        assert target in register.register_file(repo_root=target).parents


class TestInboxFileDoor:
    """The fourth door, asked for by @devpulse's feedback reply lane: a guest write under ai_mail's lock."""

    def test_a_missing_inbox_is_refused_by_name(self, tmp_path):
        ok, reason, mail_id = ai_mail.post_to_inbox_file(tmp_path / "inbox.json", {"subject": "s"})

        assert (ok, mail_id) == (False, "")
        assert "inbox not found" in reason

    def test_a_message_lands_with_an_id_and_the_unread_count(self, tmp_path):
        inbox = tmp_path / "x" / ".ai_mail.local" / "inbox.json"
        inbox.parent.mkdir(parents=True)
        inbox.write_text('{"messages": []}', encoding="utf-8")
        message = {"from": "@devpulse", "to": "@x", "subject": "s", "message": "m", "status": "new"}

        ok, reason, mail_id = ai_mail.post_to_inbox_file(inbox, message)

        assert (ok, reason) == (True, "")
        stored = json.loads(inbox.read_text(encoding="utf-8"))
        assert [m["id"] for m in stored["messages"]] == [mail_id]
        assert stored["unread_count"] == 1

    def test_the_door_is_advertised_in_dunder_all(self):
        assert "post_to_inbox_file" in ai_mail.__all__


class TestNotificationDoor:
    """The fifth door, asked for by @trigger's CI red lane: one feed event from a foreign branch."""

    def test_an_event_lands_on_the_feed_with_its_kind_source_and_extra(self, monkeypatch, tmp_path):
        feed = tmp_path / "notifications.jsonl"
        monkeypatch.setattr(notify, "FEED_PATH", feed)

        written = ai_mail.send_notification("CI red", "hooks 99", source="ci", kind="system", extra={"run_id": "7"})

        assert written is True
        row = json.loads(feed.read_text(encoding="utf-8").splitlines()[-1])
        assert (row["kind"], row["source"], row["title"], row["run_id"]) == ("system", "ci", "CI red", "7")

    def test_the_door_is_advertised_in_dunder_all(self):
        assert "send_notification" in ai_mail.__all__


class TestMailKindDoor:
    """The reader @hooks, @api and BAUD use for a stored message's kind."""

    @pytest.mark.parametrize(
        "message, kind",
        [
            ({"kind": "medic", "subject": "Dispatch complete: x"}, "medic"),
            ({"kind": "job_failed"}, "job_failed"),
            ({"from": "@ai_mail", "subject": "Dispatch complete: @x finished (exit 0)"}, "notice"),
            ({"from": "@daemon", "subject": "Command job started: @s/j"}, "notice"),
            ({"from": "@daemon", "subject": "Command job passed: @s/j"}, "notice"),
            ({"from": "@trigger", "subject": "[REPEAT] ERROR x5"}, "mail"),
            ({"from": "@daemon", "subject": "Command job FAILED: @s/j"}, "mail"),
            ({"kind": "urgent", "subject": "Dispatch complete: x"}, "mail"),
        ],
    )
    def test_a_stored_kind_is_read_as_is_and_a_message_without_one_reads_notice_or_mail(self, message, kind):
        assert ai_mail.mail_kind(message) == kind

    def test_the_door_is_advertised_in_dunder_all(self):
        assert "mail_kind" in ai_mail.__all__


class TestImportStaysLight:
    """The reason the door is lazy."""

    def test_importing_the_package_does_not_pull_in_the_logging_stack(self):
        """``import aipass.ai_mail`` must not cost a prax import.

        Clean interpreter: an in-process check would pass on modules the suite already imported.
        """
        probe = "import sys; import aipass.ai_mail; print(int(any(m.startswith('aipass.prax') for m in sys.modules)))"
        result = subprocess.run(
            [sys.executable, "-c", probe],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
        )

        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "0", "importing aipass.ai_mail pulled in prax"

    def test_the_register_door_is_lazy_too(self):
        """A second door must not undo the first door's reason for existing."""
        probe = (
            "import sys; import aipass.ai_mail as m; p = m.register_path(); "
            "print(int(any(k.startswith('aipass.prax') for k in sys.modules)), p.name)"
        )
        result = subprocess.run(
            [sys.executable, "-c", probe], capture_output=True, text=True, encoding="utf-8", timeout=60
        )

        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "1 dispatch_register.jsonl"

    def test_touching_the_door_does_load_it(self):
        """The other half: laziness must not mean broken."""
        probe = (
            "import sys; import aipass.ai_mail as m; p = m.feed_path(); "
            "print(int(any(k.startswith('aipass.prax') for k in sys.modules)), p.name)"
        )
        result = subprocess.run(
            [sys.executable, "-c", probe],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
        )

        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "1 notifications.jsonl"


class TestTheFrontDoor:
    """The names other branches take from ai_mail, handed out from their real homes."""

    @pytest.mark.parametrize("name, home", DOOR_HOMES.items())
    def test_each_door_name_is_the_same_object_its_home_gives(self, name, home):
        assert getattr(ai_mail, name) is getattr(importlib.import_module(home), name)

    @pytest.mark.parametrize("name", DOOR_HOMES)
    def test_each_door_name_is_advertised_in_dunder_all_and_dir(self, name):
        assert name in ai_mail.__all__
        assert name in dir(ai_mail)

    def test_a_patch_on_the_home_reaches_a_caller_reading_through_the_door(self, monkeypatch):
        """The door never caches: a cached copy would hand a foreign gate the real verdict under a test's patch."""
        assert ai_mail.is_verified_admin_caller is verified_caller.is_verified_admin_caller
        monkeypatch.setattr(verified_caller, "is_verified_admin_caller", lambda *a, **k: "patched")

        assert ai_mail.is_verified_admin_caller() == "patched"

    def test_a_bare_package_import_loads_nothing_under_apps(self):
        probe = (
            "import sys, aipass.ai_mail; print(sorted(m for m in sys.modules if m.startswith('aipass.ai_mail.apps')))"
        )

        assert _clean_probe(probe) == "[]"

    @pytest.mark.parametrize(
        "name, unloaded",
        [
            ("is_verified_admin_caller", ("dispatch.wake", "dispatch.session_pointer", "dispatch.grant")),
            ("write_pointer", ("dispatch.wake", "dispatch.grant", "users.verified_caller")),
            ("granted", ("dispatch.wake", "dispatch.session_pointer", "users.verified_caller")),
        ],
    )
    def test_a_gate_name_loads_its_home_and_not_its_neighbours(self, name, unloaded):
        """Hooks' gates take these on every tool call: the door must not widen what one name costs."""
        probe = (
            f"import sys, aipass.ai_mail as m; m.{name}; "
            f"print([k for k in {[f'{_H}.{u}' for u in unloaded]!r} if k in sys.modules], "
            f"int({DOOR_HOMES[name]!r} in sys.modules), int('aipass.ai_mail.apps.modules' in sys.modules))"
        )

        assert _clean_probe(probe) == "[] 1 0"
