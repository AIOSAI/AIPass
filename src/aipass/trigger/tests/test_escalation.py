# =================== AIPass ====================
# Name: test_escalation.py
# Description: Tests for the escalation lane's signature, counting, windows, gates and state file
# Version: 1.2.0
# Created: 2026-08-08
# Modified: 2026-10-08
# =============================================

"""Tests for apps/handlers/escalation.py — the repeat signature, counting, windows, gates and state file."""

# The digest itself (send, mail, reporting) and apps/modules/escalation.py, the
# CLI, live in test_escalation_digest.py since the oversize_test_file split
# (2026-10-08). The lane fixtures are in conftest.py; the event payloads and the
# fire/read helpers both files share are in support_escalation.py.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(external) — ai_mail delivery of the digest; AIPass tests only its own files

import json
from pathlib import Path
from typing import Any, Dict, Generator

import pytest
from aipass.trigger.apps.config import trail_logger
from aipass.trigger.apps.handlers import escalation
from aipass.trigger.apps.handlers.json import config_loader
from aipass.trigger.tests.support_escalation import (
    ERROR_EVENT,
    WARNING_EVENT,
    _age_last_digest,
    _entry,
    _fire_aged_warning,
    _fire_distinct,
    _fire_error,
    _fire_warning,
    _freeze_clock,
    _read_state,
    _write_state,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _age_occurrences(lane, signature: str, seconds: float) -> None:
    """Push a signature's recorded occurrences *seconds* into the past."""
    state = _read_state(lane)
    entry = state["signatures"][signature]
    entry["occurrences"] = [ts - seconds for ts in entry["occurrences"]]
    _write_state(lane, state)


# ---------------------------------------------------------------------------
# compute_signature
# ---------------------------------------------------------------------------


class TestComputeSignature:
    """Signature stability — the same failure must collapse to one signature.

    Variable data (paths, line numbers, timestamps) is what makes a repeating
    failure look like a hundred unique ones; identity fields (level, branch,
    module) are what keeps two unrelated failures apart.
    """

    def test_different_absolute_paths_share_a_signature(self, lane) -> None:
        """The same failure reported against different paths is one signature."""
        first = lane.compute_signature("ERROR", "flow", "cfg", "cannot open /home/a/src/thing.json")
        second = lane.compute_signature("ERROR", "flow", "cfg", "cannot open /srv/deploy/other.json")
        assert first == second

    def test_different_line_numbers_share_a_signature(self, lane) -> None:
        """A shifting line number does not fork the signature."""
        first = lane.compute_signature("ERROR", "flow", "cfg", "KeyError at line 42")
        second = lane.compute_signature("ERROR", "flow", "cfg", "KeyError at line 907")
        assert first == second

    def test_different_timestamps_share_a_signature(self, lane) -> None:
        """An embedded timestamp does not fork the signature."""
        first = lane.compute_signature("ERROR", "flow", "cfg", "sync failed at 2026-08-08 10:00:00")
        second = lane.compute_signature("ERROR", "flow", "cfg", "sync failed at 2026-08-08 23:14:07")
        assert first == second

    def test_different_module_is_a_different_signature(self, lane) -> None:
        """The same text from another module is a different failure."""
        first = lane.compute_signature("ERROR", "flow", "cfg", "connection refused")
        second = lane.compute_signature("ERROR", "flow", "watcher", "connection refused")
        assert first != second

    def test_different_branch_is_a_different_signature(self, lane) -> None:
        """The same text from another branch is a different failure."""
        first = lane.compute_signature("ERROR", "flow", "cfg", "connection refused")
        second = lane.compute_signature("ERROR", "memory", "cfg", "connection refused")
        assert first != second

    def test_different_level_is_a_different_signature(self, lane) -> None:
        """A warning and an error with identical text count separately."""
        warning = lane.compute_signature("WARNING", "flow", "cfg", "connection refused")
        error = lane.compute_signature("ERROR", "flow", "cfg", "connection refused")
        assert warning != error

    def test_branch_case_does_not_fork_the_signature(self, lane) -> None:
        """'FLOW' and 'flow' are the same citizen, so the same signature."""
        upper = lane.compute_signature("ERROR", "FLOW", "cfg", "connection refused")
        lower = lane.compute_signature("ERROR", "flow", "cfg", "connection refused")
        assert upper == lower

    def test_signature_is_twelve_hex_chars(self, lane) -> None:
        """Signatures are short enough to paste and long enough not to collide."""
        signature = lane.compute_signature("ERROR", "flow", "cfg", "connection refused")
        assert len(signature) == 12
        assert all(char in "0123456789abcdef" for char in signature)


# The two variants @devpulse pinned from the 2026-08-11 storm: one logical event
# (prax live-monitor queue full during seedgo's fleet audit) that minted 112
# separate signatures and mailed 17 digests. They differ by a count and by the
# citizen named in the tail — nothing else.
PRAX_QUEUE_A = (
    "[event_queue] The live monitor display queue is full — 20 events were skipped from the "
    "terminal monitor view since the last report (latest: log from SEEDGO). Nothing is lost: "
    "the on-disk logs are complete."
)
PRAX_QUEUE_B = (
    "[event_queue] The live monitor display queue is full — 37 events were skipped from the "
    "terminal monitor view since the last report (latest: log from PRAX). Nothing is lost: "
    "the on-disk logs are complete."
)


# The four @devpulse diffed out of their inbox on the evening of 2026-08-11,
# copied verbatim from the live state file. Same warning family as the pair
# above, arriving in a costume the first fix was never measured against: the
# count sits mid-sentence and the source is a slash-compound carrying a citizen
# name AND a model name. The last two differ ONLY by the count.
PRAX_QUEUE_LOG_DAEMON = (
    "[event_queue] The live monitor display queue is full — 5 events were skipped from the "
    "terminal monitor view since the last report (latest: log from DAEMON). Nothing is lost: "
    "the on-disk logs are complete."
)
PRAX_QUEUE_AGENT_SEEDGO = (
    "[event_queue] The live monitor display queue is full — 8 events were skipped from the "
    "terminal monitor view since the last report (latest: agent from AIPASS/SEEDGO/opus). "
    "Nothing is lost: the on-disk logs are complete."
)
PRAX_QUEUE_AGENT_FABLE = (
    "[event_queue] The live monitor display queue is full — 11 events were skipped from the "
    "terminal monitor view since the last report (latest: agent from AIPASS/DEVPULSE/claude-fable-5). "
    "Nothing is lost: the on-disk logs are complete."
)
PRAX_QUEUE_AGENT_FABLE_OTHER_COUNT = PRAX_QUEUE_AGENT_FABLE.replace("11 events", "10 events")


class TestSignatureFragmentation:
    """One logical event must not mint a signature per repeat.

    The registry normalizer strips what varies between *errors*. Repetition
    needs more: a message differing only by a count, a duration, or a named
    citizen is the same condition happening again. Every case here was measured
    on real state, not imagined — see the module comment above.
    """

    @pytest.fixture(autouse=True)
    def pinned_registry(self, lane, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """Every citizen the corpus names, pinned to a fixture registry.

        AIPASS_REGISTRY.json is runtime state, not tracked source — a bare CI
        checkout has none, name collapse silently skips, and the collapse
        assertions fork while the same tests pass on any dev machine where
        _find_repo_root() walks up into the live tree. The world a test needs
        must be the world it builds.
        """
        registry = tmp_path / "AIPASS_REGISTRY.json"
        names = ("SEEDGO", "PRAX", "DRONE", "DEVPULSE", "DAEMON", "HOOKS", "AIPASS", "FLOW")
        registry.write_text(json.dumps({"branches": [{"name": n} for n in names]}), encoding="utf-8")
        monkeypatch.setattr(lane, "BRANCH_REGISTRY_FILE", registry)
        lane._branch_names_cache = (0.0, None)

    def test_the_pinned_prax_pair_is_one_signature(self, lane) -> None:
        """The exact pair @devpulse reported. Both variants, one signature."""
        first = lane.compute_signature("WARNING", "prax", "direct_prax_event_queue", PRAX_QUEUE_A)
        second = lane.compute_signature("WARNING", "prax", "direct_prax_event_queue", PRAX_QUEUE_B)
        assert first == second

    def test_small_counts_do_not_fork_the_signature(self, lane) -> None:
        """1-2 digit numbers passed straight through the old 3+ digit rule."""
        first = lane.compute_signature("WARNING", "prax", "queue", "20 events were skipped")
        second = lane.compute_signature("WARNING", "prax", "queue", "37 events were skipped")
        assert first == second

    def test_the_hundred_boundary_does_not_fork_the_signature(self, lane) -> None:
        """The regression that hides behind a mismatched placeholder.

        The registry pass rewrites 3+ digit numbers to <id> before this lane
        runs. Collapse the smaller ones to any OTHER token and 99 and 101 stop
        matching — one condition, two signatures, split on a round number.
        """
        small = lane.compute_signature("WARNING", "prax", "queue", "99 events were skipped")
        large = lane.compute_signature("WARNING", "prax", "queue", "101 events were skipped")
        assert small == large

    def test_durations_do_not_fork_the_signature(self, lane) -> None:
        """There is no word boundary inside '1237ms' — 76 real signatures came of it."""
        first = lane.compute_signature("WARNING", "hooks", "gate", "PreToolUse BLOCKED by pre_edit_gate (1237ms)")
        second = lane.compute_signature("WARNING", "hooks", "gate", "PreToolUse BLOCKED by pre_edit_gate (2247ms)")
        assert first == second

    def test_named_citizen_does_not_fork_the_signature(self, lane) -> None:
        """A branch NAMED in the text is a detail; the OWNING branch is the identity."""
        first = lane.compute_signature("WARNING", "prax", "queue", "queue full (latest: log from SEEDGO)")
        second = lane.compute_signature("WARNING", "prax", "queue", "queue full (latest: log from DRONE)")
        assert first == second

    def test_at_handle_does_not_fork_the_signature(self, lane) -> None:
        """@handles collapse even for citizens absent from the registry."""
        first = lane.compute_signature("WARNING", "hooks", "gate", "@vera .trinity/local.json over budget")
        second = lane.compute_signature("WARNING", "hooks", "gate", "@nobody .trinity/local.json over budget")
        assert first == second

    def test_the_slash_compound_source_token_is_one_signature(self, lane) -> None:
        """@devpulse's 2026-08-11 evening counterexample, verbatim from their inbox.

        Four signatures they diffed by hand. The varying tokens are a mid-sentence
        count (5/8/10/11) and a compound source token that carries an uppercase
        citizen name AND a model name inside a slash-path shape. Pinned because a
        counterexample is only answered once; a test answers it forever.
        """
        signatures = {
            lane.compute_signature("WARNING", "prax", "direct_prax_event_queue", message)
            for message in (PRAX_QUEUE_AGENT_SEEDGO, PRAX_QUEUE_AGENT_FABLE, PRAX_QUEUE_AGENT_FABLE_OTHER_COUNT)
        }
        assert len(signatures) == 1

    def test_a_model_name_carrying_a_digit_does_not_fork_the_signature(self, lane) -> None:
        """'opus' vs 'claude-fable-5' — the trailing digit must not mint a second row."""
        first = lane.compute_signature("WARNING", "prax", "queue", "latest: agent from AIPASS/SEEDGO/opus")
        second = lane.compute_signature("WARNING", "prax", "queue", "latest: agent from AIPASS/DEVPULSE/claude-fable-5")
        assert first == second

    def test_the_source_kind_still_separates_signatures(self, lane) -> None:
        """The counterpart guard: 'log from' and 'agent from' are different conditions.

        @devpulse ruled the residual source kinds are MEANING, not fragmentation.
        This pins that ruling so a future widening cannot quietly erase it.
        """
        as_log = lane.compute_signature("WARNING", "prax", "direct_prax_event_queue", PRAX_QUEUE_LOG_DAEMON)
        as_agent = lane.compute_signature("WARNING", "prax", "direct_prax_event_queue", PRAX_QUEUE_AGENT_SEEDGO)
        assert as_log != as_agent

    def test_owning_branch_still_separates_signatures(self, lane) -> None:
        """Collapsing names in the TEXT must not collapse the branch field itself."""
        first = lane.compute_signature("WARNING", "prax", "queue", "queue full (latest: log from SEEDGO)")
        second = lane.compute_signature("WARNING", "seedgo", "queue", "queue full (latest: log from SEEDGO)")
        assert first != second

    def test_genuinely_different_conditions_stay_apart(self, lane) -> None:
        """The guard against over-collapsing: different words, different signatures."""
        first = lane.compute_signature("ERROR", "flow", "cfg", "connection refused after 5 tries")
        second = lane.compute_signature("ERROR", "flow", "cfg", "permission denied after 5 tries")
        assert first != second

    def test_registry_unreadable_still_collapses_numbers(self, lane, monkeypatch, tmp_path) -> None:
        """Fail soft: no registry means no name collapse, never a dead lane."""
        monkeypatch.setattr(lane, "BRANCH_REGISTRY_FILE", tmp_path / "gone.json")
        lane._branch_names_cache = (0.0, None)

        first = lane.compute_signature("WARNING", "prax", "queue", "20 events were skipped")
        second = lane.compute_signature("WARNING", "prax", "queue", "37 events were skipped")
        assert first == second

    def test_registry_names_are_reread_after_the_ttl(self, lane, monkeypatch, tmp_path) -> None:
        """A newly spawned citizen collapses without restarting the watcher.

        Freshness is time-bounded, not mtime-bounded: on this filesystem two
        writes moments apart report the same st_mtime AND st_mtime_ns, so an
        mtime check can tie and never re-read at all. Expiring the stamp is
        what a watcher crossing the TTL does.
        """
        registry = tmp_path / "AIPASS_REGISTRY.json"
        registry.write_text(json.dumps({"branches": [{"name": "FLOW"}]}), encoding="utf-8")
        monkeypatch.setattr(lane, "BRANCH_REGISTRY_FILE", registry)
        lane._branch_names_cache = (0.0, None)

        before = lane.compute_signature("WARNING", "prax", "q", "saw NEWBIE")
        registry.write_text(json.dumps({"branches": [{"name": "FLOW"}, {"name": "NEWBIE"}]}), encoding="utf-8")
        lane._branch_names_cache = (0.0, None)  # TTL elapsed
        after = lane.compute_signature("WARNING", "prax", "q", "saw NEWBIE")

        assert before != after
        assert after == lane.compute_signature("WARNING", "prax", "q", "saw FLOW")

    def test_names_are_not_reread_inside_the_ttl(self, lane, monkeypatch, tmp_path) -> None:
        """The cache is real: no file read per log line.

        Mutant killed 2026-09-27: the TTL early return in _branch_name_pattern made unconditional-false.
        """
        registry = tmp_path / "AIPASS_REGISTRY.json"
        registry.write_text(json.dumps({"branches": [{"name": "FLOW"}]}), encoding="utf-8")
        monkeypatch.setattr(lane, "BRANCH_REGISTRY_FILE", registry)
        lane._branch_names_cache = (0.0, None)
        warm = lane.compute_signature("WARNING", "prax", "q", "saw FLOW")

        registry.unlink()
        # Re-read, the missing registry would stop FLOW collapsing and move the signature.
        assert lane.compute_signature("WARNING", "prax", "q", "saw FLOW") == warm

    def test_missing_registry_is_cached_not_reread(self, lane, monkeypatch, tmp_path) -> None:
        """A missing registry is an answer worth caching, not IO to repeat forever."""
        monkeypatch.setattr(lane, "BRANCH_REGISTRY_FILE", tmp_path / "gone.json")
        lane._branch_names_cache = (0.0, None)

        assert lane._branch_name_pattern() is None
        stamped_at, _ = lane._branch_names_cache
        assert stamped_at > 0


# ---------------------------------------------------------------------------
# Counting and threshold
# ---------------------------------------------------------------------------


class TestCountingAndThreshold:
    """Counting is unconditional; only the digest is gated by the threshold."""

    def test_below_threshold_counts_without_emailing(self, lane, outbox) -> None:
        """Two of a three-threshold signature: counted, nobody mailed."""
        decision = _fire_warning(lane, times=2)

        assert decision["outcome"] == "counted"
        assert decision["count"] == 2
        assert outbox == []

    def test_threshold_sends_exactly_one_digest(self, lane, outbox) -> None:
        """The occurrence that crosses the threshold sends one digest, not one per occurrence."""
        decision = _fire_warning(lane, times=3)

        assert decision["outcome"] == "sent"
        assert len(outbox) == 1

    def test_window_resets_after_a_send(self, lane, outbox) -> None:
        """After a digest the window restarts, so the next occurrence counts as the first."""
        signature = _fire_warning(lane, times=3)["signature"]
        assert len(outbox) == 1

        decision = _fire_warning(lane, times=1)

        assert decision["count"] == 1
        assert decision["outcome"] == "counted"
        assert len(_entry(lane, signature)["occurrences"]) == 1

    def test_lifetime_count_survives_the_window_reset(self, lane, outbox) -> None:
        """total_count is lifetime bookkeeping and never resets with the window."""
        signature = _fire_warning(lane, times=3)["signature"]
        _fire_warning(lane, times=2)

        assert _entry(lane, signature)["total_count"] == 5

    def test_state_records_the_occurrence_details(self, lane) -> None:
        """One occurrence lands in the state file with everything the digest needs."""
        signature = _fire_warning(lane, times=1)["signature"]

        entry = _entry(lane, signature)
        assert entry["level"] == "WARNING"
        assert entry["branch"] == "flow"
        assert entry["module"] == "watcher"
        assert entry["log_file"] == WARNING_EVENT["log_file"]
        assert entry["samples"] == [WARNING_EVENT["raw_line"]]
        assert entry["first_seen"]
        assert entry["last_seen"]

    def test_separate_signatures_count_separately(self, lane, outbox) -> None:
        """Two different messages never pool their counts into one digest."""
        _fire_warning(lane, times=2)
        _fire_warning(lane, times=2, message="disk 94% full")

        assert outbox == []
        assert len(_read_state(lane)["signatures"]) == 2

    def test_error_threshold_is_read_separately_from_warning_threshold(self, monkeypatch, lane, outbox, medic, cfg):
        """An ERROR uses error_threshold, not warning_threshold."""
        cfg["error_threshold"] = 2
        cfg["warning_threshold"] = 10
        monkeypatch.setattr(medic.registry, "get_dispatch_count", lambda fingerprint: 1)

        decision = _fire_error(lane, times=2)

        assert decision["outcome"] == "sent"
        assert len(outbox) == 1


# ---------------------------------------------------------------------------
# Window trimming
# ---------------------------------------------------------------------------


class TestWindowTrimming:
    """Occurrences older than window_minutes stop counting toward the threshold."""

    def test_old_occurrences_do_not_count(self, lane, outbox) -> None:
        """Two hours of silence resets a 60-minute window: the next hit is #1 again."""
        signature = _fire_warning(lane, times=2)["signature"]
        _age_occurrences(lane, signature, seconds=2 * 3600)

        decision = _fire_warning(lane, times=1)

        assert decision["count"] == 1
        assert decision["outcome"] == "counted"
        assert outbox == []

    def test_fresh_occurrences_still_reach_the_threshold(self, lane, outbox) -> None:
        """Positive control: without the ageing, the same third occurrence sends."""
        _fire_warning(lane, times=2)

        decision = _fire_warning(lane, times=1)

        assert decision["outcome"] == "sent"
        assert len(outbox) == 1

    def test_trimmed_occurrences_are_dropped_from_state(self, lane) -> None:
        """The state file does not accumulate occurrences forever."""
        signature = _fire_warning(lane, times=2)["signature"]
        _age_occurrences(lane, signature, seconds=2 * 3600)
        _fire_warning(lane, times=1)

        assert len(_entry(lane, signature)["occurrences"]) == 1
        assert _entry(lane, signature)["total_count"] == 3


# ---------------------------------------------------------------------------
# Cooldown
# ---------------------------------------------------------------------------


class TestCooldown:
    """A per-signature cooldown keeps repeat noise out of the mailbox."""

    def test_second_crossing_inside_cooldown_is_held(self, lane, outbox) -> None:
        """Crossing the threshold again during the cooldown sends nothing."""
        _fire_warning(lane, times=3)
        assert len(outbox) == 1

        decision = _fire_warning(lane, times=3)

        assert decision["outcome"] == "cooldown"
        assert len(outbox) == 1

    def test_sends_again_once_the_cooldown_has_elapsed(self, lane, outbox) -> None:
        """Past the cooldown the same signature escalates again."""
        signature = _fire_warning(lane, times=3)["signature"]
        _fire_warning(lane, times=3)
        _age_last_digest(lane, signature, minutes=120)

        decision = _fire_warning(lane, times=1)

        assert decision["outcome"] == "sent"
        assert len(outbox) == 2
        assert _entry(lane, signature)["digests_sent"] == 2

    def test_cooldown_does_not_stop_the_counting(self, lane, outbox) -> None:
        """Held by cooldown still means counted — the audit trail stays complete."""
        signature = _fire_warning(lane, times=3)["signature"]
        _fire_warning(lane, times=3)

        assert _entry(lane, signature)["total_count"] == 6

    def test_unparseable_last_digest_does_not_silence_the_lane(self, lane, outbox) -> None:
        """A corrupt cooldown stamp fails open — silence is the worse failure."""
        signature = _fire_warning(lane, times=2)["signature"]
        state = _read_state(lane)
        state["signatures"][signature]["last_digest"] = "not-a-timestamp"
        _write_state(lane, state)

        decision = _fire_warning(lane, times=1)

        assert decision["outcome"] == "sent"
        assert len(outbox) == 1


# ---------------------------------------------------------------------------
# Error eligibility
# ---------------------------------------------------------------------------


class TestErrorEligibility:
    """Which repeating ERRORs the human still needs to hear about.

    Eligible means medic is NOT going to wake the owner about this right now.
    """

    def test_muted_branch_still_counts_and_still_escalates(self, monkeypatch, lane, outbox, medic) -> None:
        """THE MUTE RULE: a mute stops the dispatch, never the count and never the digest."""
        monkeypatch.setattr(medic.state, "get_muted_branches", lambda: ["flow"])

        decision = _fire_error(lane, times=3)

        assert decision["outcome"] == "sent"
        assert len(outbox) == 1
        assert "muted" in outbox[0]["message"]
        assert _entry(lane, decision["signature"])["total_count"] == 3

    def test_mute_matching_is_case_insensitive(self, monkeypatch, lane, outbox, medic) -> None:
        """'FLOW' muted and 'flow' erroring are the same branch."""
        monkeypatch.setattr(medic.state, "get_muted_branches", lambda: ["FLOW"])

        decision = _fire_error(lane, times=3)

        assert decision["outcome"] == "sent"
        assert "muted" in outbox[0]["message"]

    def test_medic_off_escalates(self, monkeypatch, lane, outbox, medic) -> None:
        """With medic off nothing dispatches, so repetition must reach the human."""
        medic.switches["medic_enabled"] = False

        decision = _fire_error(lane, times=3)

        assert decision["outcome"] == "sent"
        assert "medic off" in outbox[0]["message"]

    def test_already_dispatched_error_escalates(self, monkeypatch, lane, outbox, medic) -> None:
        """The owner was told and it is still happening — that is the whole point of the lane."""
        monkeypatch.setattr(medic.registry, "get_dispatch_count", lambda fingerprint: 1)

        decision = _fire_error(lane, times=3)

        assert decision["outcome"] == "sent"
        assert "dispatched" in outbox[0]["message"]

    def test_pending_owner_dispatch_is_not_escalated(self, lane, outbox, medic) -> None:
        """Medic has not had its turn yet: no digest, the lane is not a second medic."""
        decision = _fire_error(lane, times=3)

        assert decision["outcome"] == "not_eligible"
        assert outbox == []
        assert _entry(lane, decision["signature"])["total_count"] == 3

    def test_unregistered_branch_escalates(self, monkeypatch, lane, outbox, medic) -> None:
        """No registered owner means medic cannot dispatch this anywhere."""
        monkeypatch.setattr(medic.dispatcher, "_get_registered_emails", lambda: {"@memory"})

        decision = _fire_error(lane, times=3)

        assert decision["outcome"] == "sent"
        assert "no registered owner" in outbox[0]["message"]

    def test_an_unreadable_branch_registry_manufactures_no_digest(self, lane, outbox, medic) -> None:
        """A registry the check cannot read is not a registry with nobody in it.

        _has_registered_owner documents True when the check itself failed. The
        lookup used to swallow the read failure and answer an empty set, so every
        branch read as unregistered and the lane mailed 'no registered owner'.
        Red first on that code (outcome 'sent').
        Mutant 2026-09-28: the lookup's re-raise put back to return set() reddens this.
        """
        medic.branch_registry.write_text("{not json", encoding="utf-8")

        decision = _fire_error(lane, times=3)

        assert decision["outcome"] == "not_eligible"
        assert outbox == []

    def test_suppressed_fingerprint_stays_silent(self, monkeypatch, lane, outbox, medic) -> None:
        """A human called this benign (compass #219) — suppression beats 'already dispatched'.

        Mutant killed 2026-09-27: is_suppressed(fingerprint) -> is_suppressed("") in _is_error_eligible.
        """
        medic.suppressed.add(ERROR_EVENT["fingerprint"])
        monkeypatch.setattr(medic.registry, "get_dispatch_count", lambda fingerprint: 1)

        decision = _fire_error(lane, times=3)

        assert decision["outcome"] == "not_eligible"
        assert outbox == []

    def test_escalate_suppressed_config_lifts_the_silence(self, monkeypatch, lane, outbox, medic, cfg) -> None:
        """Same suppressed error, escalate_suppressed on: the digest goes out."""
        cfg["escalate_suppressed"] = True
        medic.suppressed.add(ERROR_EVENT["fingerprint"])
        monkeypatch.setattr(medic.registry, "get_dispatch_count", lambda fingerprint: 1)

        decision = _fire_error(lane, times=3)

        assert decision["outcome"] == "sent"
        assert len(outbox) == 1

    def test_warnings_never_consult_the_dispatch_gates(self, lane, outbox, medic) -> None:
        """Warnings have no dispatch path at all, so repetition alone escalates them."""
        decision = _fire_warning(lane, times=3)

        assert decision["outcome"] == "sent"
        assert "no dispatch path" in outbox[0]["message"]


# ---------------------------------------------------------------------------
# Config gates
# ---------------------------------------------------------------------------


class TestConfigGates:
    """The operator's master switches, checked before anything is written."""

    def test_disabled_lane_records_nothing(self, lane, outbox, cfg) -> None:
        """enabled=False: no decision, no state file, no email."""
        cfg["enabled"] = False

        assert _fire_warning(lane, times=5) is None
        assert not lane.STATE_FILE.exists()
        assert outbox == []

    def test_enabled_lane_records(self, lane, outbox, cfg) -> None:
        """Positive control: the same input with enabled=True does write state."""
        decision = _fire_warning(lane, times=1)

        assert decision["outcome"] == "counted"
        assert lane.STATE_FILE.exists()

    def test_warning_age_hours_zero_keeps_every_repeat_on_the_manager_digest(
        self, monkeypatch, lane, outbox, cfg
    ) -> None:
        """The aged lane is an operator setting, and 0 is the old behaviour intact."""
        monkeypatch.setattr(lane, "_has_registered_owner", lambda branch: branch == "flow")
        cfg["warning_age_hours"] = 0

        decision = _fire_aged_warning(lane)

        assert decision["outcome"] == "sent"
        assert [mail["to_branch"] for mail in outbox] == [cfg["digest_recipient"]]

    def test_an_unreadable_first_seen_keeps_the_manager_digest(self, monkeypatch, lane, outbox, cfg) -> None:
        """A stamp this lane cannot read must not silently retire the signal."""
        monkeypatch.setattr(lane, "_has_registered_owner", lambda branch: branch == "flow")
        signature = _fire_warning(lane, times=1)["signature"]
        state = _read_state(lane)
        state["signatures"][signature]["first_seen"] = "not a timestamp"
        _write_state(lane, state)

        decision = _fire_warning(lane, times=2)

        assert decision["outcome"] == "sent"
        assert [mail["to_branch"] for mail in outbox] == [cfg["digest_recipient"]]

    def test_ignored_branch_records_nothing(self, lane, outbox, cfg) -> None:
        """A deliberately ignored branch is silent, count and all."""
        cfg["ignore_branches"] = ["flow"]

        assert _fire_warning(lane, times=5) is None
        assert not lane.STATE_FILE.exists()

    def test_ignore_branches_is_case_insensitive(self, lane, cfg) -> None:
        """Ignoring 'FLOW' silences 'flow'."""
        cfg["ignore_branches"] = ["FLOW"]

        assert _fire_warning(lane, times=1) is None

    def test_other_branches_still_count_while_one_is_ignored(self, lane, cfg) -> None:
        """Ignoring one branch does not switch the lane off for everyone."""
        cfg["ignore_branches"] = ["flow"]

        decision = _fire_warning(lane, times=1, branch="memory")

        assert decision["outcome"] == "counted"

    def test_a_failed_record_is_told_apart_from_a_switched_off_lane(self, monkeypatch, lane) -> None:
        """None means the lane chose not to count; a crash inside it answers record_failed."""

        def _unreadable() -> Dict[str, Any]:
            raise OSError("config unreadable")

        monkeypatch.setattr(lane, "get_config", _unreadable)

        assert _fire_warning(lane, times=1) == {"signature": "", "count": 0, "outcome": "record_failed"}

    def test_incomplete_event_is_dropped(self, lane) -> None:
        """A record with no branch, module or message has nothing to key on."""
        assert lane.record_warning(branch="", module="watcher", message="x") is None
        assert lane.record_warning(branch="flow", module="", message="x") is None
        assert lane.record_warning(branch="flow", module="watcher", message="") is None
        assert not lane.STATE_FILE.exists()


# ---------------------------------------------------------------------------
# State file resilience
# ---------------------------------------------------------------------------


class TestStateFileResilience:
    """The lane must survive its own state file, whatever shape it is in."""

    def test_unreadable_state_starts_empty(self, lane) -> None:
        """Garbage on disk is replaced by a fresh count, not an exception."""
        lane.STATE_FILE.write_text("{ this is not json", encoding="utf-8")

        decision = _fire_warning(lane, times=1)

        assert decision["count"] == 1
        assert _read_state(lane)["signatures"]

    def test_wrong_shape_state_starts_empty(self, lane) -> None:
        """A JSON list where an object belongs is treated as no state at all."""
        lane.STATE_FILE.write_text("[1, 2, 3]", encoding="utf-8")

        decision = _fire_warning(lane, times=1)

        assert decision["count"] == 1

    def test_missing_signatures_key_starts_empty(self, lane) -> None:
        """A dict without a signatures map is the wrong shape too."""
        lane.STATE_FILE.write_text('{"signatures": "nope"}', encoding="utf-8")

        assert _fire_warning(lane, times=1)["count"] == 1

    def test_listing_an_unreadable_state_returns_nothing(self, lane) -> None:
        """get_signatures never raises on a broken file."""
        lane.STATE_FILE.write_text("{ this is not json", encoding="utf-8")

        assert lane.get_signatures() == []


# ---------------------------------------------------------------------------
# Pruning
# ---------------------------------------------------------------------------


class TestPruning:
    """max_signatures bounds the state file, dropping the least recently seen."""

    def test_least_recently_seen_signatures_are_dropped(self, lane, cfg) -> None:
        """Five signatures into a cap of three keeps the three most recent."""
        cfg["max_signatures"] = 3
        signatures = [_fire_distinct(lane, i)["signature"] for i in range(5)]

        stored = _read_state(lane)["signatures"]
        assert len(stored) == 3
        assert signatures[0] not in stored
        assert signatures[1] not in stored
        assert set(signatures[2:]) == set(stored)

    def test_a_refreshed_signature_survives_the_prune(self, lane, cfg) -> None:
        """Re-seeing an old signature makes it recent again, so it is kept."""
        cfg["max_signatures"] = 2
        oldest = _fire_distinct(lane, 0)["signature"]
        _fire_distinct(lane, 1)
        _fire_distinct(lane, 0)
        _fire_distinct(lane, 2)

        assert oldest in _read_state(lane)["signatures"]

    def test_a_refreshed_signature_survives_a_tied_prune(self, lane, cfg, monkeypatch: pytest.MonkeyPatch) -> None:
        """Re-seeing a signature protects it even when last_seen cannot record that.

        Creation order is A, B, C; touch order puts A last. On a tied clock the
        pre-fix code pruned by creation order and dropped the entry that had
        just been re-seen.
        """
        cfg["max_signatures"] = 3
        _freeze_clock(monkeypatch, lane)
        first = _fire_distinct(lane, 0)["signature"]
        second = _fire_distinct(lane, 1)["signature"]
        _fire_distinct(lane, 2)
        _fire_distinct(lane, 0)
        _fire_distinct(lane, 3)

        stored = _read_state(lane)["signatures"]
        assert first in stored, "the re-seen signature is the newest, not the oldest"
        assert second not in stored


# ---------------------------------------------------------------------------
# get_config read-through
# ---------------------------------------------------------------------------


class TestConfigReadThrough:
    """get_config serves the operator's file, merged over defaults, with a short cache."""

    @pytest.fixture
    def operator_config(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Generator[Path, None, None]:
        """Point the real loader at an operator config file under tmp_path."""
        path = tmp_path / "custom_config" / "trigger.config.json"
        monkeypatch.setattr(config_loader, "CONFIG_PATH", path)
        monkeypatch.setattr(config_loader, "logger", trail_logger(tmp_path / "config_loader.jsonl"))
        monkeypatch.setattr(escalation, "STATE_FILE", tmp_path / "escalation_state.json")
        escalation._config_cache = (0.0, None)
        yield path
        escalation._config_cache = (0.0, None)

    def test_operator_values_win_over_defaults(self, operator_config: Path) -> None:
        """A threshold set in the file is the threshold the lane uses."""
        operator_config.parent.mkdir(parents=True, exist_ok=True)
        operator_config.write_text(json.dumps({"escalation": {"warning_threshold": 99}}), encoding="utf-8")

        cfg = escalation.get_config()
        assert cfg["warning_threshold"] == 99
        assert cfg["digest_recipient"] == "@devpulse"

    def test_missing_file_serves_defaults(self, operator_config: Path) -> None:
        """No file yet: defaults are served and the file is regenerated for the operator."""
        cfg = escalation.get_config()

        assert cfg == config_loader.DEFAULT_CONFIG["escalation"]
        assert operator_config.exists()

    def test_value_is_cached_until_reset(self, operator_config: Path) -> None:
        """The hot path does not re-read the file per log line; clearing the cache does."""
        operator_config.parent.mkdir(parents=True, exist_ok=True)
        operator_config.write_text(json.dumps({"escalation": {"warning_threshold": 99}}), encoding="utf-8")
        assert escalation.get_config()["warning_threshold"] == 99

        operator_config.write_text(json.dumps({"escalation": {"warning_threshold": 7}}), encoding="utf-8")
        assert escalation.get_config()["warning_threshold"] == 99

        escalation._config_cache = (0.0, None)
        assert escalation.get_config()["warning_threshold"] == 7
