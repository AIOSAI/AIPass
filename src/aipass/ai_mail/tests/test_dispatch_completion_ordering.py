# =================== AIPass ====================
# Name: test_dispatch_completion_ordering.py
# Description: The terminal moment's ordering, FPLAN-0452 P0's second fix
# Version: 1.0.2
# Created: 2026-08-22
# Modified: 2026-10-23
# =============================================

"""Tests for apps/handlers/dispatch/dispatch_monitor.py -- the terminal moment's ordering."""

# These assert source order, not behaviour: the defect was the ORDER of calls, which no
# single call shows. Anchors use .index(), which raises when an anchor is gone, so a rename fails loudly.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(constant) — STARTUP_TIMEOUT and HARD_TIMEOUT's numeric values

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

        Release first, and a death in the window leaves no lock and no report; release last leaves a recoverable held lock.
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
        """wake_result is IN the report, so the wake-back cannot follow it."""
        assert tail.index("wake_sender(") < tail.index("build_report(")


class TestAFailedReportIsNotRoutine:
    """A lost dispatch record must not look healthy in the log."""

    def test_the_swallowed_info_line_is_gone(self, tail):
        """Red-first anchor: this exact string was the defect (a lost record logged at info level)."""
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
        """Otherwise every mail the child sent would count as the parent's work."""
        source = (MONITOR.parent / "wake.py").read_text(encoding="utf-8")

        strip = source.index('spawn_env.pop("AIPASS_DISPATCH_ID", None)')
        assign = source.index('spawn_env["AIPASS_DISPATCH_ID"] = dispatch_id')
        assert strip < assign, "the strip must precede the assignment or it undoes it"

    def test_the_register_write_precedes_every_spawn_path(self):
        """Evidence written after a successful spawn only records the healthy ones."""
        source = (MONITOR.parent / "wake.py").read_text(encoding="utf-8")

        register_call = source.index("register.open_dispatch(")
        assert register_call < source.index("spawn_in_systemd_scope(\n")
        assert register_call < source.index("process = subprocess.Popen(")

    def test_expected_by_uses_the_monitors_own_timeout_not_an_invented_one(self):
        source = (MONITOR.parent / "wake.py").read_text(encoding="utf-8")

        assert "expected_seconds=HARD_TIMEOUT" in source
