# =================== AIPass ====================
# Name: test_public_surface.py
# Description: Tests for ai_mail's package-level public surface (the feed path door)
# Version: 1.0.0
# Created: 2026-08-16
# Modified: 2026-08-16
# =============================================

"""Tests for the package-level door onto the notification feed (asked by @api).

@api serves the feed to the BAUD phone over /v1/feed and had no clean way to
locate ``notifications.jsonl``. The only route was
``from aipass.ai_mail.apps.handlers.notify import FEED_PATH`` — a reach into
this branch's handlers layer that seedgo correctly flags — so they restated the
path as their own constant instead. That duplicate goes stale the day the feed
moves, and the symptom would be a phone quietly showing no notifications with
no error logged anywhere.

``notify.py`` publishes the path as a contract, so a second reader is inside
the contract. What was missing was a public surface, the way @drone publishes
``get_registry_path()``. This adds one.

Two properties matter here:

Laziness
    ``notify`` imports prax's logger and the JSON handler, so re-exporting it
    eagerly would make ``import aipass.ai_mail`` drag in the logging stack.
    The door is a function, and ``FEED_PATH`` resolves through PEP 562
    ``__getattr__``.

One construction site
    ``feed_path()`` is where the path is built; ``FEED_PATH`` is that
    function's value at import. Duplicating the expression is the exact rot
    @api was trying to avoid, so it must not reappear inside this branch.
"""

import subprocess
import sys
from pathlib import Path

import aipass.ai_mail as ai_mail
import aipass.ai_mail.apps.handlers.notify as notify


class TestFeedPathDoor:
    """The public surface @api asked for."""

    def test_feed_path_is_importable_from_the_package(self):
        from aipass.ai_mail import feed_path

        assert callable(feed_path)

    def test_feed_path_matches_the_handler_implementation(self):
        """The door and the implementation must never disagree."""
        assert ai_mail.feed_path() == notify.feed_path()

    def test_feed_path_constant_is_reachable_from_the_package(self):
        """@api asked for the constant by name; keep it working."""
        assert ai_mail.FEED_PATH == notify.FEED_PATH

    def test_the_constant_door_reads_through_instead_of_snapshotting(self, monkeypatch, tmp_path):
        """``ai_mail.FEED_PATH`` must follow a patched ``notify.FEED_PATH``.

        This branch's own conftest redirects the feed to tmp_path for every
        test, so writes never land in the real ``notifications.jsonl`` BAUD
        renders. @api needs the same escape hatch. Because ``__getattr__``
        imports at access time rather than binding at package import, the door
        sees the patch — a snapshotting export would silently hand their tests
        the live feed and let a suite write into Patrick's bell.
        """
        redirected = tmp_path / "elsewhere" / "notifications.jsonl"
        monkeypatch.setattr(notify, "FEED_PATH", redirected)

        assert ai_mail.FEED_PATH == redirected

    def test_feed_path_returns_a_path_not_a_string(self):
        assert isinstance(ai_mail.feed_path(), Path)

    def test_the_feed_lives_where_the_contract_says(self):
        """<repo root>/.aipass/notifications.jsonl — the documented location."""
        resolved = ai_mail.feed_path()
        assert resolved.name == "notifications.jsonl"
        assert resolved.parent.name == ".aipass"

    def test_feed_path_resolves_fresh_at_call_time(self, monkeypatch, tmp_path):
        """A function, not a frozen constant.

        ``FEED_PATH`` is computed once at import, so a process whose repo root
        resolves differently later — or a test that relocates it — reads a
        stale value. The callable is the honest export.
        """
        monkeypatch.setattr(notify, "find_repo_root", lambda: tmp_path)

        assert notify.feed_path() == tmp_path / ".aipass" / "notifications.jsonl"

    def test_the_constant_is_built_by_the_function(self):
        """One construction site — checked where conftest has not redirected it.

        The autouse feed-isolation fixture patches ``notify.FEED_PATH``, so this
        equality is unobservable in-process. A clean interpreter sees the real
        import-time value and catches a re-inlined ``find_repo_root() / ...``.
        """
        probe = "import aipass.ai_mail.apps.handlers.notify as n; print(int(n.FEED_PATH == n.feed_path()))"
        result = subprocess.run(
            [sys.executable, "-c", probe],
            capture_output=True,
            text=True,
            timeout=60,
        )

        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "1"

    def test_unknown_attribute_still_raises_attribute_error(self):
        """PEP 562 __getattr__ must not swallow real typos."""
        try:
            ai_mail.no_such_thing  # type: ignore[attr-defined]
        except AttributeError:
            return
        raise AssertionError("a missing attribute must still raise AttributeError")

    def test_the_door_is_advertised_in_dunder_all(self):
        assert "feed_path" in ai_mail.__all__
        assert "FEED_PATH" in ai_mail.__all__


class TestImportStaysLight:
    """The reason the door is lazy."""

    def test_importing_the_package_does_not_pull_in_the_logging_stack(self):
        """``import aipass.ai_mail`` must not cost a prax import.

        Consumers like @api import this package to reach one path. If the
        re-export were eager, every one of them would load prax's logger and
        the JSON handler as a side effect. Run in a clean interpreter — an
        in-process check would pass on modules the suite already imported.
        """
        probe = "import sys; import aipass.ai_mail; print(int(any(m.startswith('aipass.prax') for m in sys.modules)))"
        result = subprocess.run(
            [sys.executable, "-c", probe],
            capture_output=True,
            text=True,
            timeout=60,
        )

        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "0", "importing aipass.ai_mail pulled in prax"

    def test_touching_the_door_does_load_it(self):
        """The other half: laziness must not mean broken.

        Same clean interpreter, but call through the door — prax should now be
        loaded, proving the deferred import actually fires rather than the name
        resolving to something hollow.
        """
        probe = (
            "import sys; import aipass.ai_mail as m; p = m.feed_path(); "
            "print(int(any(k.startswith('aipass.prax') for k in sys.modules)), p.name)"
        )
        result = subprocess.run(
            [sys.executable, "-c", probe],
            capture_output=True,
            text=True,
            timeout=60,
        )

        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "1 notifications.jsonl"
