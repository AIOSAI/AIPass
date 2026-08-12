# =================== AIPass ====================
# Name: test_escalation.py
# Description: Tests for the escalation digest lane and its CLI module
# Version: 1.1.0
# Created: 2026-08-08
# Modified: 2026-08-09
# =============================================

"""Tests for handlers/escalation.py — repeat-signature counting, digest gating, and modules/escalation.py."""

import importlib
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Generator, List
from unittest.mock import MagicMock

import pytest
from aipass.trigger.apps.config import trail_logger


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def cfg() -> Dict[str, Any]:
    """Operator settings the lane runs on — tests mutate this dict, never a live file."""
    return {
        "enabled": True,
        "digest_recipient": "@digest-inbox",
        "warning_threshold": 3,
        "error_threshold": 3,
        "window_minutes": 60,
        "cooldown_minutes": 60,
        "sample_lines": 3,
        "max_signatures": 500,
        "escalate_suppressed": False,
        "watch_branch_log_warnings": True,
        "ignore_branches": [],
    }


@pytest.fixture
def lane(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, cfg: Dict[str, Any]):
    """The escalation handler, wired to a tmp state file and the cfg fixture.

    The real file lock and real atomic writes run here on purpose: a mocked
    lock has already hidden a self-deadlock in this branch once.
    """
    from aipass.trigger.apps.handlers import escalation

    monkeypatch.setattr(escalation, "STATE_FILE", tmp_path / "escalation_state.json")
    monkeypatch.setattr(escalation, "logger", trail_logger(tmp_path / "escalation.jsonl"))
    monkeypatch.setattr(escalation, "get_config", lambda: cfg)
    monkeypatch.setattr(escalation, "_send_email", None)
    escalation._config_cache = (0.0, None)
    # Reset on the way OUT too: a test that points BRANCH_REGISTRY_FILE at a tmp
    # registry leaves the compiled pattern behind, and monkeypatch restores the
    # path but not the cache — the next test would sign against a stale citizen
    # list that no longer matches any file on disk.
    escalation._branch_names_cache = (0.0, None)
    yield escalation
    escalation._config_cache = (0.0, None)
    escalation._branch_names_cache = (0.0, None)


@pytest.fixture
def outbox(monkeypatch: pytest.MonkeyPatch, lane) -> List[Dict[str, Any]]:
    """Capture digest emails instead of sending them."""
    box: List[Dict[str, Any]] = []

    def _send(**kwargs: Any) -> bool:
        box.append(kwargs)
        return True

    monkeypatch.setattr(lane, "_send_email", _send)
    return box


@pytest.fixture
def medic(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Registry + medic state describing an error medic is still handling itself.

    Each of these is reached through a lazy import inside the lane, so the
    modules are pulled in with importlib first: that guarantees the object
    patched here is the same one the lane resolves out of sys.modules.
    """
    error_registry = importlib.import_module("aipass.trigger.apps.handlers.error_registry")
    medic_state = importlib.import_module("aipass.trigger.apps.handlers.medic_state")
    error_detected = importlib.import_module("aipass.trigger.apps.handlers.events.error_detected")

    monkeypatch.setattr(error_registry, "is_suppressed", lambda fingerprint: False)
    monkeypatch.setattr(error_registry, "get_dispatch_count", lambda fingerprint: 0)
    monkeypatch.setattr(medic_state, "is_enabled", lambda: True)
    monkeypatch.setattr(medic_state, "get_muted_branches", lambda: [])
    monkeypatch.setattr(error_detected, "_get_registered_emails", lambda: {"@flow", "@memory"})

    return SimpleNamespace(registry=error_registry, state=medic_state, dispatcher=error_detected)


@pytest.fixture
def cli(monkeypatch: pytest.MonkeyPatch, lane) -> SimpleNamespace:
    """The escalation CLI module with a mocked console and json_handler."""
    mock_json_handler = MagicMock()
    mock_json_handler.log_operation = MagicMock(return_value=True)
    json_pkg = MagicMock()
    json_pkg.json_handler = mock_json_handler
    monkeypatch.setitem(sys.modules, "aipass.trigger.apps.handlers.json", json_pkg)
    monkeypatch.setitem(sys.modules, "aipass.trigger.apps.handlers.json.json_handler", mock_json_handler)

    console = MagicMock()
    cli_modules = MagicMock()
    cli_modules.console = console
    cli_display = MagicMock()
    cli_display.console = console
    monkeypatch.setitem(sys.modules, "aipass.cli", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.cli.apps", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.cli.apps.modules", cli_modules)
    monkeypatch.setitem(sys.modules, "aipass.cli.apps.modules.display", cli_display)

    monkeypatch.delitem(sys.modules, "aipass.trigger.apps.modules.escalation", raising=False)
    module = importlib.import_module("aipass.trigger.apps.modules.escalation")

    return SimpleNamespace(module=module, console=console, log_operation=mock_json_handler.log_operation)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Inert fixture data — nothing ever opens this path, it only rides along in the
# event payload and gets asserted back out. Kept branch-relative and built with
# Path: an absolute /home/... literal is a hardcoded path in any file, tests
# included, and it hardcodes a separator the Windows lane then has to survive.
FLOW_LOG = str(Path("flow") / "logs" / "flow.log")

ERROR_EVENT = {
    "branch": "flow",
    "module": "cfg",
    "message": "connection refused",
    "log_file": FLOW_LOG,
    "fingerprint": "fp-connection-refused",
}

WARNING_EVENT = {
    "branch": "flow",
    "module": "watcher",
    "message": "queue depth at 91%",
    "log_file": FLOW_LOG,
    "raw_line": "2026-08-08 10:00:00.000 | watcher | WARNING | queue depth at 91%",
}


def _fire_error(lane, times: int = 1, **overrides: Any) -> Any:
    """Record *times* identical ERROR occurrences, returning the last decision."""
    payload = {**ERROR_EVENT, **overrides}
    decision = None
    for _ in range(times):
        decision = lane.record_error(**payload)
    return decision


def _fire_warning(lane, times: int = 1, **overrides: Any) -> Any:
    """Record *times* identical WARNING occurrences, returning the last decision."""
    payload = {**WARNING_EVENT, **overrides}
    decision = None
    for _ in range(times):
        decision = lane.record_warning(**payload)
    return decision


# Messages that are genuinely different CONDITIONS, for tests that need N
# separate signatures. Deliberately not "warning number {i}": the lane collapses
# standalone integers so one condition's repeats share a signature, which would
# make every one of these the SAME signature — turning a prune or limit test
# green while it exercises a single row.
DISTINCT_WARNINGS = [
    "disk is filling up",
    "memory is filling up",
    "socket pool exhausted",
    "cache is cold",
    "queue is backed up",
]


def _fire_distinct(lane, index: int) -> Any:
    """Record one occurrence of the *index*-th genuinely distinct warning."""
    return _fire_warning(lane, times=1, message=DISTINCT_WARNINGS[index])


def _freeze_clock(monkeypatch: pytest.MonkeyPatch, lane) -> None:
    """Pin datetime.now() so every last_seen string comes out byte-identical.

    This is the Windows CI clock reproduced deterministically on any platform:
    its granularity is ~15.6ms, so signatures written back-to-back tie on
    last_seen. Ties are what sent both ordering paths — newest-first listing
    and oldest-first pruning — back to dict insertion order, which is creation
    order, not touch order.
    """
    frozen = datetime(2026, 8, 9, 12, 0, 0)
    monkeypatch.setattr(
        lane,
        "datetime",
        SimpleNamespace(now=lambda: frozen, fromisoformat=datetime.fromisoformat),
    )


def _read_state(lane) -> Dict[str, Any]:
    """Read the raw state document off disk."""
    return json.loads(lane.STATE_FILE.read_text(encoding="utf-8"))


def _entry(lane, signature: str) -> Dict[str, Any]:
    """Read one signature's state entry off disk."""
    return _read_state(lane)["signatures"][signature]


def _write_state(lane, state: Dict[str, Any]) -> None:
    """Write the state document back to disk (test-side edit, single process)."""
    lane.STATE_FILE.write_text(json.dumps(state), encoding="utf-8")


def _age_occurrences(lane, signature: str, seconds: float) -> None:
    """Push a signature's recorded occurrences *seconds* into the past."""
    state = _read_state(lane)
    entry = state["signatures"][signature]
    entry["occurrences"] = [ts - seconds for ts in entry["occurrences"]]
    _write_state(lane, state)


def _age_last_digest(lane, signature: str, minutes: float) -> None:
    """Backdate a signature's last digest so its cooldown has elapsed."""
    state = _read_state(lane)
    state["signatures"][signature]["last_digest"] = (datetime.now() - timedelta(minutes=minutes)).isoformat()
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


class TestSignatureFragmentation:
    """One logical event must not mint a signature per repeat.

    The registry normalizer strips what varies between *errors*. Repetition
    needs more: a message differing only by a count, a duration, or a named
    citizen is the same condition happening again. Every case here was measured
    on real state, not imagined — see the module comment above.
    """

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
        """The cache is real: no file read per log line."""
        registry = tmp_path / "AIPASS_REGISTRY.json"
        registry.write_text(json.dumps({"branches": [{"name": "FLOW"}]}), encoding="utf-8")
        monkeypatch.setattr(lane, "BRANCH_REGISTRY_FILE", registry)
        lane._branch_names_cache = (0.0, None)
        lane.compute_signature("WARNING", "prax", "q", "warm the cache")

        registry.unlink()
        assert lane._branch_name_pattern() is not None

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
        monkeypatch.setattr(medic.state, "is_enabled", lambda: False)

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

    def test_suppressed_fingerprint_stays_silent(self, monkeypatch, lane, outbox, medic) -> None:
        """A human called this benign (compass #219) — suppression beats 'already dispatched'."""
        monkeypatch.setattr(medic.registry, "is_suppressed", lambda fingerprint: True)
        monkeypatch.setattr(medic.registry, "get_dispatch_count", lambda fingerprint: 1)

        decision = _fire_error(lane, times=3)

        assert decision["outcome"] == "not_eligible"
        assert outbox == []

    def test_escalate_suppressed_config_lifts_the_silence(self, monkeypatch, lane, outbox, medic, cfg) -> None:
        """Same suppressed error, escalate_suppressed on: the digest goes out."""
        cfg["escalate_suppressed"] = True
        monkeypatch.setattr(medic.registry, "is_suppressed", lambda fingerprint: True)
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

    def test_incomplete_event_is_dropped(self, lane) -> None:
        """A record with no branch, module or message has nothing to key on."""
        assert lane.record_warning(branch="", module="watcher", message="x") is None
        assert lane.record_warning(branch="flow", module="", message="x") is None
        assert lane.record_warning(branch="flow", module="watcher", message="") is None
        assert not lane.STATE_FILE.exists()


# ---------------------------------------------------------------------------
# Send failures
# ---------------------------------------------------------------------------


class TestSendFailures:
    """A failed send must leave the signature ready to retry, not silently 'done'."""

    def test_refused_delivery_reports_send_failed(self, monkeypatch, lane) -> None:
        """A callback returning False is a failure, not a send."""
        monkeypatch.setattr(lane, "_send_email", lambda **kwargs: False)

        decision = _fire_warning(lane, times=3)

        assert decision["outcome"] == "send_failed"

    def test_refused_delivery_does_not_start_the_cooldown(self, monkeypatch, lane) -> None:
        """last_digest stays empty and digests_sent stays 0, so nothing is muted by a failure."""
        monkeypatch.setattr(lane, "_send_email", lambda **kwargs: False)

        signature = _fire_warning(lane, times=3)["signature"]

        entry = _entry(lane, signature)
        assert entry["last_digest"] == ""
        assert entry["digests_sent"] == 0

    def test_next_occurrence_retries_after_a_failure(self, monkeypatch, lane) -> None:
        """The window was not reset either, so the very next occurrence tries again."""
        monkeypatch.setattr(lane, "_send_email", lambda **kwargs: False)
        _fire_warning(lane, times=3)

        box: List[Dict[str, Any]] = []

        def _send(**kwargs: Any) -> bool:
            box.append(kwargs)
            return True

        monkeypatch.setattr(lane, "_send_email", _send)

        decision = _fire_warning(lane, times=1)

        assert decision["outcome"] == "sent"
        assert len(box) == 1

    def test_raising_callback_is_contained(self, monkeypatch, lane) -> None:
        """A callback that throws is a send failure, never an exception out of the lane."""

        def _boom(**kwargs: Any) -> bool:
            raise RuntimeError("SMTP down")

        monkeypatch.setattr(lane, "_send_email", _boom)

        decision = _fire_warning(lane, times=3)

        assert decision["outcome"] == "send_failed"
        assert _entry(lane, decision["signature"])["digests_sent"] == 0

    def test_missing_callback_is_contained(self, lane) -> None:
        """No email callback wired (handlers run before the module layer wires one)."""
        decision = _fire_warning(lane, times=3)

        assert decision["outcome"] == "send_failed"
        assert _entry(lane, decision["signature"])["last_digest"] == ""


# ---------------------------------------------------------------------------
# set_send_email_callback
# ---------------------------------------------------------------------------


class TestSendEmailCallback:
    """The module layer wires delivery in; handlers never import modules."""

    def test_wired_callback_receives_the_digest(self, lane) -> None:
        """A callback set through the public setter is the one that sends."""
        box: List[Dict[str, Any]] = []

        def _send(**kwargs: Any) -> bool:
            box.append(kwargs)
            return True

        lane.set_send_email_callback(_send)

        _fire_warning(lane, times=3)

        assert len(box) == 1
        assert box[0]["subject"].startswith("[REPEAT]")

    def test_second_wiring_replaces_the_first(self, lane) -> None:
        """Re-running setup must not leave two deliveries racing."""
        first: List[Dict[str, Any]] = []
        second: List[Dict[str, Any]] = []
        lane.set_send_email_callback(lambda **kwargs: bool(first.append(kwargs)) or True)
        lane.set_send_email_callback(lambda **kwargs: bool(second.append(kwargs)) or True)

        _fire_warning(lane, times=3)

        assert first == []
        assert len(second) == 1


# ---------------------------------------------------------------------------
# Digest email
# ---------------------------------------------------------------------------


class TestDigestEmail:
    """The digest is an EMAIL to a manager, and investigation starts from it alone."""

    def test_goes_to_the_configured_recipient_as_plain_email(self, lane, outbox, cfg) -> None:
        """auto_execute is False: a digest is read, it never wakes anyone."""
        _fire_warning(lane, times=3)

        mail = outbox[0]
        assert mail["to_branch"] == cfg["digest_recipient"]
        assert mail["auto_execute"] is False
        assert mail["from_branch"] == "@trigger"

    def test_subject_names_level_count_branch_and_module(self, lane, outbox) -> None:
        """The subject alone says what repeated, how often and where."""
        _fire_warning(lane, times=3)

        subject = outbox[0]["subject"]
        assert "[REPEAT]" in subject
        assert "WARNING" in subject
        assert "x3" in subject
        assert "@flow" in subject
        assert "watcher" in subject

    def test_body_carries_the_investigation_context(self, lane, outbox) -> None:
        """Signature, count, window, branch, module and log path all travel with the mail."""
        decision = _fire_warning(lane, times=3)

        body = outbox[0]["message"]
        assert decision["signature"] in body
        assert "3 in the last 60 min" in body
        assert "@flow" in body
        assert "watcher" in body
        assert WARNING_EVENT["log_file"] in body
        assert WARNING_EVENT["message"] in body

    def test_body_carries_the_last_sample_lines(self, lane, outbox, cfg) -> None:
        """The last sample_lines raw lines ride along; older ones are dropped."""
        cfg["sample_lines"] = 2
        for index in range(3):
            lane.record_warning(**{**WARNING_EVENT, "raw_line": f"raw line {index}"})

        body = outbox[0]["message"]
        assert "raw line 0" not in body
        assert "raw line 1" in body
        assert "raw line 2" in body

    def test_body_states_the_reason_it_escalated(self, lane, outbox, medic) -> None:
        """The mail explains why medic was not going to handle this."""
        medic.state.get_muted_branches = lambda: ["flow"]

        _fire_error(lane, times=3)

        assert "Why escalated: branch muted" in outbox[0]["message"]

    def test_body_points_at_the_operator_config(self, lane, outbox) -> None:
        """Every digest tells the reader how to tune or silence it."""
        _fire_warning(lane, times=3)

        body = outbox[0]["message"]
        assert "trigger.config.json" in body
        assert "warning_threshold" in body


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
# Reporting: get_signatures / get_stats
# ---------------------------------------------------------------------------


class TestReporting:
    """What the CLI and an operator get to see."""

    def test_signatures_are_returned_most_recent_first(self, lane) -> None:
        """Ordering is by last_seen, newest first."""
        _fire_warning(lane, times=1, message="older warning")
        newest = _fire_warning(lane, times=1, message="newer warning")["signature"]

        rows = lane.get_signatures()
        assert rows[0]["signature"] == newest
        assert len(rows) == 2

    def test_ordering_holds_when_last_seen_ties(self, lane, monkeypatch: pytest.MonkeyPatch) -> None:
        """The Windows CI flake: identical last_seen must still list newest first."""
        _freeze_clock(monkeypatch, lane)
        _fire_warning(lane, times=1, message="older warning")
        newest = _fire_warning(lane, times=1, message="newer warning")["signature"]

        rows = lane.get_signatures()
        assert len({row["last_seen"] for row in rows}) == 1, "clock must be tied for this to test anything"
        assert rows[0]["signature"] == newest

    def test_re_seeing_a_signature_moves_it_to_the_front_on_a_tied_clock(
        self, lane, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Touch order, not creation order, decides the listing.

        The re-seen signature is deliberately the MIDDLE one: if creation order
        still leaked through, the first-created would head the list instead.
        """
        _freeze_clock(monkeypatch, lane)
        _fire_distinct(lane, 0)
        middle = _fire_distinct(lane, 1)["signature"]
        _fire_distinct(lane, 2)
        _fire_distinct(lane, 1)

        assert lane.get_signatures()[0]["signature"] == middle

    def test_signature_rows_carry_the_window_count(self, lane) -> None:
        """A row reports occurrences inside the window as well as lifetime total."""
        _fire_warning(lane, times=2)

        row = lane.get_signatures()[0]
        assert row["window_count"] == 2
        assert row["total_count"] == 2

    def test_level_filter_selects_one_level(self, lane, medic) -> None:
        """list warning shows warnings only, and list error shows errors only."""
        _fire_warning(lane, times=1)
        _fire_error(lane, times=1)

        warnings = lane.get_signatures(level="warning")
        errors = lane.get_signatures(level="ERROR")

        assert [row["level"] for row in warnings] == ["WARNING"]
        assert [row["level"] for row in errors] == ["ERROR"]

    def test_limit_caps_the_listing(self, lane) -> None:
        """The limit argument bounds what the CLI renders."""
        for index in range(5):
            _fire_distinct(lane, index)

        assert len(lane.get_signatures(limit=2)) == 2

    def test_stats_report_config_and_tracking(self, lane, outbox, cfg, medic) -> None:
        """Stats mix the operator's knobs with what the lane is actually holding."""
        _fire_warning(lane, times=3)
        _fire_error(lane, times=1)

        stats = lane.get_stats()
        assert stats["enabled"] is True
        assert stats["digest_recipient"] == cfg["digest_recipient"]
        assert stats["warning_threshold"] == cfg["warning_threshold"]
        assert stats["error_threshold"] == cfg["error_threshold"]
        assert stats["window_minutes"] == cfg["window_minutes"]
        assert stats["cooldown_minutes"] == cfg["cooldown_minutes"]
        assert stats["tracked_signatures"] == 2
        assert stats["tracked_warnings"] == 1
        assert stats["tracked_errors"] == 1
        assert stats["digests_sent"] == 1
        assert stats["signatures_digested"] == 1
        assert stats["email_wired"] is True
        assert stats["state_file"] == str(lane.STATE_FILE)

    def test_stats_report_no_email_wired(self, lane) -> None:
        """An operator can see that this process could not send a digest."""
        assert lane.get_stats()["email_wired"] is False

    def test_stats_on_an_empty_lane(self, lane) -> None:
        """Nothing tracked yet is a clean zero, not a crash."""
        stats = lane.get_stats()
        assert stats["tracked_signatures"] == 0
        assert stats["digests_sent"] == 0


# ---------------------------------------------------------------------------
# clear_state
# ---------------------------------------------------------------------------


class TestClearState:
    """Counts are archived, never deleted."""

    def test_clear_archives_the_state_file(self, lane) -> None:
        """The file moves into .archive/ and the lane starts fresh."""
        _fire_warning(lane, times=2)

        assert lane.clear_state() is True
        assert not lane.STATE_FILE.exists()
        archived = list((lane.STATE_FILE.parent / ".archive").glob("escalation_state*.json"))
        assert len(archived) == 1
        assert json.loads(archived[0].read_text(encoding="utf-8"))["signatures"]

    def test_clear_with_no_state_is_a_no_op(self, lane) -> None:
        """Clearing an empty lane succeeds without creating anything."""
        assert lane.clear_state() is True
        assert not lane.STATE_FILE.exists()

    def test_counting_resumes_after_a_clear(self, lane) -> None:
        """A cleared lane counts from one again."""
        _fire_warning(lane, times=2)
        lane.clear_state()

        assert _fire_warning(lane, times=1)["count"] == 1


# ---------------------------------------------------------------------------
# get_config read-through
# ---------------------------------------------------------------------------


class TestConfigReadThrough:
    """get_config serves the operator's file, merged over defaults, with a short cache."""

    @pytest.fixture
    def operator_config(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Generator[Path, None, None]:
        """Point the real loader at an operator config file under tmp_path."""
        from aipass.trigger.apps.handlers import escalation
        from aipass.trigger.apps.handlers.json import config_loader

        path = tmp_path / "custom_config" / "trigger.config.json"
        monkeypatch.setattr(config_loader, "CONFIG_PATH", path)
        monkeypatch.setattr(config_loader, "logger", trail_logger(tmp_path / "config_loader.jsonl"))
        monkeypatch.setattr(escalation, "STATE_FILE", tmp_path / "escalation_state.json")
        escalation._config_cache = (0.0, None)
        yield path
        escalation._config_cache = (0.0, None)

    def test_operator_values_win_over_defaults(self, operator_config: Path) -> None:
        """A threshold set in the file is the threshold the lane uses."""
        from aipass.trigger.apps.handlers import escalation

        operator_config.parent.mkdir(parents=True, exist_ok=True)
        operator_config.write_text(json.dumps({"escalation": {"warning_threshold": 99}}), encoding="utf-8")

        cfg = escalation.get_config()
        assert cfg["warning_threshold"] == 99
        assert cfg["digest_recipient"] == "@devpulse"

    def test_missing_file_serves_defaults(self, operator_config: Path) -> None:
        """No file yet: defaults are served and the file is regenerated for the operator."""
        from aipass.trigger.apps.handlers import escalation
        from aipass.trigger.apps.handlers.json import config_loader

        cfg = escalation.get_config()

        assert cfg == config_loader.DEFAULT_CONFIG["escalation"]
        assert operator_config.exists()

    def test_value_is_cached_until_reset(self, operator_config: Path) -> None:
        """The hot path does not re-read the file per log line; clearing the cache does."""
        from aipass.trigger.apps.handlers import escalation

        operator_config.parent.mkdir(parents=True, exist_ok=True)
        operator_config.write_text(json.dumps({"escalation": {"warning_threshold": 99}}), encoding="utf-8")
        assert escalation.get_config()["warning_threshold"] == 99

        operator_config.write_text(json.dumps({"escalation": {"warning_threshold": 7}}), encoding="utf-8")
        assert escalation.get_config()["warning_threshold"] == 99

        escalation._config_cache = (0.0, None)
        assert escalation.get_config()["warning_threshold"] == 7


# ---------------------------------------------------------------------------
# modules/escalation.py -- CLI
# ---------------------------------------------------------------------------


class TestCliCommand:
    """The CLI claims its own module name and nothing else."""

    def test_bare_status_is_left_to_core(self, cli) -> None:
        """`drone @trigger status` belongs to core.py — claiming it would hijack it."""
        assert cli.module.handle_command("status", []) is False

    def test_bare_list_is_left_to_core(self, cli) -> None:
        """`list` is core's command too."""
        assert cli.module.handle_command("list", []) is False

    def test_bare_config_is_left_to_core(self, cli) -> None:
        """`config` is core's command too."""
        assert cli.module.handle_command("config", []) is False

    def test_escalation_status_is_handled(self, cli) -> None:
        """`escalation status` renders and reports as handled."""
        assert cli.module.handle_command("escalation", ["status"]) is True
        assert cli.console.print.called

    def test_escalation_list_is_handled(self, cli) -> None:
        """`escalation list` renders and reports as handled."""
        assert cli.module.handle_command("escalation", ["list"]) is True

    def test_escalation_config_is_handled(self, cli) -> None:
        """`escalation config` renders and reports as handled."""
        assert cli.module.handle_command("escalation", ["config"]) is True

    def test_no_subcommand_prints_introspection(self, cli) -> None:
        """A bare `escalation` introspects rather than guessing a subcommand."""
        assert cli.module.handle_command("escalation", []) is True
        rendered = " ".join(str(call) for call in cli.console.print.call_args_list)
        assert "escalation Module" in rendered

    def test_unknown_subcommand_shows_help(self, cli) -> None:
        """An unknown subcommand falls back to help instead of failing silently."""
        assert cli.module.handle_command("escalation", ["wat"]) is True

    def test_status_renders_the_configured_recipient(self, cli, cfg) -> None:
        """Status shows where digests actually go, not a hardcoded address."""
        cli.module.handle_command("escalation", ["status"])

        rendered = " ".join(str(call) for call in cli.console.print.call_args_list)
        assert cfg["digest_recipient"] in rendered

    def test_list_renders_tracked_signatures(self, cli, lane) -> None:
        """A counted signature shows up in `escalation list`."""
        signature = _fire_warning(lane, times=1)["signature"]

        cli.module.handle_command("escalation", ["list"])

        rendered = " ".join(str(call) for call in cli.console.print.call_args_list)
        assert signature in rendered
        assert WARNING_EVENT["message"] in rendered

    def test_list_filters_by_level(self, cli, lane, medic) -> None:
        """`escalation list error` hides warning signatures."""
        warning_signature = _fire_warning(lane, times=1)["signature"]
        error_signature = _fire_error(lane, times=1)["signature"]

        cli.module.handle_command("escalation", ["list", "error"])

        rendered = " ".join(str(call) for call in cli.console.print.call_args_list)
        assert error_signature in rendered
        assert warning_signature not in rendered

    def test_command_is_logged(self, cli) -> None:
        """Subcommands are recorded through json_handler like every other module."""
        cli.module.handle_command("escalation", ["status"])

        cli.log_operation.assert_called_once_with("escalation_command", {"command": "status"})


class TestDigestBody:
    """The digest mail is the whole product — investigation starts from it alone."""

    @staticmethod
    def _entry() -> dict:
        return {
            "level": "ERROR",
            "branch": "BACKUP",
            "module": "drive",
            "message": "module 'drive' has no attribute 'client'",
            "first_seen": "2026-08-08T21:00:00",
            "last_seen": "2026-08-08T21:40:00",
            "log_file": "/logs/backup/backup.log",
            "total_count": 47,
            "digests_sent": 2,
            "samples": ["21:39 ERROR drive failed", "21:40 ERROR drive failed"],
        }

    def test_body_carries_everything_an_investigation_needs(self, lane) -> None:
        """Signature, counts, window, branch, module, log path and samples all travel."""
        subject, body = lane.build_digest(
            "abc123def456", self._entry(), 9, 3600, "owner already dispatched", "@devpulse"
        )

        assert subject == "[REPEAT] ERROR x9 @backup / drive"
        for expected in (
            "abc123def456",
            "@backup",
            "drive",
            "9 in the last 60 min",
            "lifetime 47",
            "/logs/backup/backup.log",
            "owner already dispatched",
            "21:40 ERROR drive failed",
        ):
            assert expected in body, f"digest body lost {expected!r}"

    def test_body_says_it_is_mail_not_a_dispatch(self, lane) -> None:
        """The recipient must not read a digest as a task waiting on them."""
        _subject, body = lane.build_digest("sig", self._entry(), 5, 3600, "branch muted", "@devpulse")

        assert "EMAIL, not a dispatch" in body
        assert "nothing was woken" in body

    def test_body_names_the_config_file_to_tune_it(self, lane) -> None:
        """An operator who wants less of this must not have to go hunting."""
        _subject, body = lane.build_digest("sig", self._entry(), 5, 3600, "medic off", "@devpulse")

        assert "trigger_json/custom_config/trigger.config.json" in body

    def test_missing_samples_say_so_rather_than_render_blank(self, lane) -> None:
        """A digest with no captured lines must not look like a digest with empty lines."""
        entry = self._entry()
        entry["samples"] = []

        _subject, body = lane.build_digest("sig", entry, 5, 3600, "no registered owner", "@devpulse")

        assert "(no samples captured)" in body


class TestTrailLogger:
    """The recursion-safe sidecar every trigger handler logs through."""

    def test_writes_level_message_and_fields(self, tmp_path) -> None:
        """A trail line carries the structured fields the caller passed."""
        path = tmp_path / "trail.jsonl"

        trail_logger(path).warning("state unreadable", signature="abc123", branch="BACKUP")

        line = json.loads(path.read_text(encoding="utf-8").strip())
        assert line["level"] == "WARNING"
        assert line["msg"] == "state unreadable"
        assert line["signature"] == "abc123"
        assert line["branch"] == "BACKUP"

    def test_a_broken_sink_is_counted_never_raised(self, tmp_path, monkeypatch) -> None:
        """A dead trail must not take the error path down with it — it is counted."""
        trail = trail_logger(tmp_path / "trail.jsonl")
        monkeypatch.setattr(
            "aipass.trigger.apps.config._append_jsonl",
            MagicMock(side_effect=OSError("read-only filesystem")),
        )

        trail.error("digest send raised")

        assert trail.dropped == 1

    def test_absent_prax_is_counted_too(self, tmp_path, monkeypatch) -> None:
        """No prax means no sidecar — the loss is still visible as a count."""
        trail = trail_logger(tmp_path / "trail.jsonl")
        monkeypatch.setattr("aipass.trigger.apps.config._append_jsonl", None)

        trail.info("digest sent")

        assert trail.dropped == 1

    def test_dropped_trail_lines_reach_the_operator_in_stats(self, lane, monkeypatch) -> None:
        """A silent sink would be invisible; get_stats() is where it surfaces."""
        monkeypatch.setattr(
            "aipass.trigger.apps.config._append_jsonl",
            MagicMock(side_effect=OSError("disk full")),
        )
        lane.logger.warning("something the trail could not keep")

        assert lane.get_stats()["trail_writes_dropped"] >= 1
