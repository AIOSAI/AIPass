"""The terminal moment's ORDERING, which is the whole of FPLAN-0452 P0's second fix.

These assert positions in source rather than behaviour, deliberately. The defect
was never that a function did the wrong thing — every function here worked. The
defect was the ORDER they ran in, and an ordering is not observable from any
single call. ``main()`` is a 200-line process-lifetime function ending in
``sys.exit``; invoking it to observe the order would mean mocking the spawn, the
retry loop, the bounce and the wake-back, and the mocks would then be what the
test actually pinned.

Every anchor below uses ``.index()``, which RAISES when the anchor is gone. A
rename must break these loudly rather than let them pass on an empty search —
that is the canary lesson from 6be0da57, where a test asserting exit code 2 was
green from the repo root for two months without ever reaching its module.
"""

from pathlib import Path

import pytest

MONITOR = Path(__file__).resolve().parents[1] / "apps" / "handlers" / "dispatch" / "dispatch_monitor.py"


@pytest.fixture
def tail():
    """The terminal moment: everything after the agent process is done."""
    source = MONITOR.read_text(encoding="utf-8")
    return source[source.index("# Log completion to Prax") :]


class TestTheReportOutlivesTheLock:
    """Under r4 the report IS the event, so it must land before the lock goes."""

    def test_the_report_is_written_before_the_lock_is_released(self, tail):
        """The P0 fix, and the reason it stopped being cosmetic.

        Releasing the lock first meant a death in that window left the lock
        GONE and the report UNWRITTEN — "looks complete, reports nothing",
        the worst failure shape available once the report carries the event.
        With the release last, the same death leaves a held lock: visible, and
        already recoverable by the stale-lock path in wake.py.
        """
        assert tail.index("write_report(") < tail.index("_cleanup_own_lock(lock_file)")

    def test_the_register_is_closed_before_the_lock_is_released(self, tail):
        assert tail.index("close_dispatch(") < tail.index("_cleanup_own_lock(lock_file)")

    def test_the_feed_record_is_written_before_the_lock_is_released(self, tail):
        assert tail.index("send_notification(") < tail.index("_cleanup_own_lock(lock_file)")

    def test_the_lock_release_is_the_last_thing_that_happens(self, tail):
        """Nothing may be appended after it without re-opening the hole."""
        after_release = tail[tail.index("_cleanup_own_lock(lock_file)") :]

        assert "write_report(" not in after_release
        assert "send_notification(" not in after_release
        assert "close_dispatch(" not in after_release

    def test_the_wake_back_precedes_the_report_so_wake_result_is_a_known_fact(self, tail):
        """wake_result is IN the report, so the wake-back cannot follow it.

        The alternative — report first, wake after — would either omit the
        field or write the report twice. Holding the lock across the wake-back
        is the accepted cost, and it is small: for the widened window to matter
        the woken sender would have to re-dispatch this branch within the
        milliseconds it takes to write one JSON file, while booting a CLI.
        """
        assert tail.index("_wake_sender(") < tail.index("build_report(")


class TestAFailedReportIsNotRoutine:
    """A lost dispatch record must not look healthy in the log."""

    def test_the_swallowed_info_line_is_gone(self, tail):
        """Red-first anchor: this exact string was the defect.

        ``logger.info("[monitor] Notification feed unavailable")`` sat at the
        quietest level in the file, behind a bare ``except Exception`` — so the
        monitor read as healthy while the record never landed.
        """
        assert 'logger.info("[monitor] Notification feed unavailable")' not in tail

    def test_a_failed_feed_write_warns_and_carries_the_record(self, tail):
        """The escalation: warning level, and the record itself so it is recoverable."""
        handler = tail[tail.index("except Exception as e:") : tail.index("fire_completed(")]

        assert "logger.warning" in handler
        assert "report_path" in handler, "a lost record must name what was lost"

    def test_a_lost_report_is_named_as_lost(self, tail):
        assert "REPORT LOST" in tail

    def test_a_feed_write_returning_false_is_not_ignored(self, tail):
        """send_notification returns False on failure — a bare call drops that."""
        assert "if not send_notification(" in tail


class TestTheDispatchIdDoesNotLeakToChildren:
    """A dispatched agent dispatching another must not lend it its own id."""

    def test_the_inherited_id_is_stripped_before_a_new_one_is_set(self):
        """Otherwise every mail the child sent would count as the parent's work.

        ``spawn_env`` is a copy of this process's environment, so a dispatched
        caller carries a live AIPASS_DISPATCH_ID into it. Same class of leak as
        the AIPASS_CALLER_* strip directly above it in the file.
        """
        source = (MONITOR.parent / "wake.py").read_text(encoding="utf-8")

        strip = source.index('spawn_env.pop("AIPASS_DISPATCH_ID", None)')
        assign = source.index('spawn_env["AIPASS_DISPATCH_ID"] = dispatch_id')
        assert strip < assign, "the strip must precede the assignment or it undoes it"

    def test_the_register_write_precedes_every_spawn_path(self):
        """Evidence written after a successful spawn only records the healthy ones."""
        source = (MONITOR.parent / "wake.py").read_text(encoding="utf-8")

        register_call = source.index("register.open_dispatch(")
        assert register_call < source.index("_spawn_in_systemd_scope(\n")
        assert register_call < source.index("process = subprocess.Popen(")

    def test_expected_by_uses_the_monitors_own_timeout_not_an_invented_one(self):
        source = (MONITOR.parent / "wake.py").read_text(encoding="utf-8")

        assert "expected_seconds=HARD_TIMEOUT" in source
