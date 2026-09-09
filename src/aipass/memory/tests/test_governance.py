"""Tests for the surfacing governance module (pure state-in/state-out API)."""

import pytest

from aipass.memory.apps.modules.governance import (
    DEFAULT_CONFIG,
    new_state,
    record_message,
    should_surface,
)


# =============================================================================
# new_state
# =============================================================================


class TestNewState:
    def test_returns_zeroed_state(self):
        state = new_state()
        assert state["surfaces_count"] == 0
        assert state["messages_since_last"] == 0
        assert state["last_surface_time"] == 0.0
        assert state["surfaced_ids"] == []

    def test_returns_independent_copies(self):
        s1 = new_state()
        s2 = new_state()
        s1["surfaced_ids"].append("x")
        assert s2["surfaced_ids"] == []


# =============================================================================
# should_surface — rejection paths
# =============================================================================


class TestShouldSurfaceRejections:
    """Each rejection path tested independently with an otherwise-valid state."""

    @pytest.fixture()
    def ready_state(self):
        """State that passes all checks when config is default."""
        return {
            "surfaces_count": 0,
            "messages_since_last": 20,
            "last_surface_time": 0.0,
            "surfaced_ids": [],
        }

    def test_disabled(self, ready_state):
        ok, reason, st = should_surface("item1", 0.8, ready_state, {"enabled": False}, current_time=1000.0)
        assert ok is False
        assert "disabled" in reason.lower()
        assert st is ready_state

    def test_below_threshold(self, ready_state):
        ok, reason, st = should_surface("item1", 0.1, ready_state, {"threshold": 0.3}, current_time=1000.0)
        assert ok is False
        assert "threshold" in reason.lower()
        assert st is ready_state

    def test_budget_exhausted(self, ready_state):
        ready_state["surfaces_count"] = 5
        ok, reason, st = should_surface("item1", 0.8, ready_state, {"max_surfaces_per_session": 5}, current_time=1000.0)
        assert ok is False
        assert reason == "Session budget exhausted (5/5)"
        assert st is ready_state

    def test_spacing_not_met(self, ready_state):
        ready_state["messages_since_last"] = 3
        ready_state["last_surface_time"] = 1.0
        ok, reason, st = should_surface("item1", 0.8, ready_state, {"min_messages_between": 10}, current_time=1000.0)
        assert ok is False
        assert "spacing" in reason.lower()
        assert st is ready_state

    def test_cooldown_active(self, ready_state):
        ready_state["last_surface_time"] = 900.0
        ok, reason, st = should_surface("item1", 0.8, ready_state, {"cooldown_seconds": 300}, current_time=1000.0)
        assert ok is False
        assert "cooldown" in reason.lower()
        assert st is ready_state

    def test_already_surfaced(self, ready_state):
        ready_state["surfaced_ids"] = ["item1"]
        ok, reason, st = should_surface("item1", 0.8, ready_state, current_time=1000.0)
        assert ok is False
        assert "already" in reason.lower()
        assert st is ready_state


# =============================================================================
# should_surface — happy path
# =============================================================================


class TestShouldSurfaceHappy:
    def test_surfaces_and_returns_updated_state(self):
        state = {
            "surfaces_count": 0,
            "messages_since_last": 15,
            "last_surface_time": 0.0,
            "surfaced_ids": [],
        }
        ok, reason, updated = should_surface("compass-42", 0.75, state, current_time=5000.0)
        assert ok is True
        assert "ready" in reason.lower()
        assert updated["surfaces_count"] == 1
        assert updated["messages_since_last"] == 0
        assert updated["last_surface_time"] == 5000.0
        assert "compass-42" in updated["surfaced_ids"]

    def test_does_not_mutate_input_state(self):
        state = {
            "surfaces_count": 0,
            "messages_since_last": 15,
            "last_surface_time": 0.0,
            "surfaced_ids": [],
        }
        original_ids = state["surfaced_ids"]
        should_surface("item1", 0.8, state, current_time=5000.0)
        assert state["surfaces_count"] == 0
        assert state["surfaced_ids"] is original_ids
        assert len(original_ids) == 0

    def test_threshold_boundary_exact(self):
        state = new_state()
        state["messages_since_last"] = 10
        ok, _, _ = should_surface("x", 0.3, state, {"threshold": 0.3}, current_time=1000.0)
        assert ok is True

    def test_cooldown_expired(self):
        state = {
            "surfaces_count": 0,
            "messages_since_last": 15,
            "last_surface_time": 500.0,
            "surfaced_ids": [],
        }
        ok, _, _ = should_surface("x", 0.8, state, {"cooldown_seconds": 300}, current_time=801.0)
        assert ok is True

    def test_first_surface_ignores_spacing(self):
        """Fresh session: first prompt with high relevance surfaces immediately."""
        state = new_state()
        state["messages_since_last"] = 1
        ok, reason, updated = should_surface("compass-1", 0.8, state, current_time=100.0)
        assert ok is True
        assert "ready" in reason.lower()

        for i in range(9):
            updated = record_message(updated)
            ok, reason, _ = should_surface("compass-2", 0.8, updated, current_time=100.0 + 400 + i)
            assert ok is False
            assert "spacing" in reason.lower()

        updated = record_message(updated)
        ok, _, _ = should_surface("compass-2", 0.8, updated, current_time=600.0)
        assert ok is True


# =============================================================================
# State isolation — two independent states do not bleed
# =============================================================================


class TestStateIsolation:
    def test_two_states_independent(self):
        s1 = new_state()
        s1["messages_since_last"] = 20
        s2 = new_state()
        s2["messages_since_last"] = 20

        ok1, _, s1_updated = should_surface("a", 0.8, s1, current_time=1000.0)
        ok2, _, s2_updated = should_surface("b", 0.9, s2, current_time=2000.0)

        assert ok1 is True
        assert ok2 is True
        assert s1_updated["surfaced_ids"] == ["a"]
        assert s2_updated["surfaced_ids"] == ["b"]
        assert s1_updated["last_surface_time"] == 1000.0
        assert s2_updated["last_surface_time"] == 2000.0

    def test_chained_surfaces_accumulate(self):
        state = new_state()
        state["messages_since_last"] = 20

        ok, _, state = should_surface("a", 0.8, state, current_time=1000.0)
        assert ok is True
        assert state["surfaces_count"] == 1

        state["messages_since_last"] = 20
        ok, _, state = should_surface("b", 0.7, state, current_time=2000.0)
        assert ok is True
        assert state["surfaces_count"] == 2
        assert state["surfaced_ids"] == ["a", "b"]


# =============================================================================
# record_message
# =============================================================================


class TestRecordMessage:
    def test_increments_counter(self):
        state = new_state()
        updated = record_message(state)
        assert updated["messages_since_last"] == 1

    def test_does_not_mutate_input(self):
        state = new_state()
        record_message(state)
        assert state["messages_since_last"] == 0

    def test_preserves_other_fields(self):
        state = {
            "surfaces_count": 3,
            "messages_since_last": 5,
            "last_surface_time": 100.0,
            "surfaced_ids": ["x"],
        }
        updated = record_message(state)
        assert updated["surfaces_count"] == 3
        assert updated["messages_since_last"] == 6
        assert updated["last_surface_time"] == 100.0
        assert updated["surfaced_ids"] == ["x"]


# =============================================================================
# Config merging
# =============================================================================


class TestConfigMerging:
    def test_none_config_uses_defaults(self):
        state = new_state()
        state["messages_since_last"] = 20
        ok, _, _ = should_surface("x", 0.8, state, None, current_time=1000.0)
        assert ok is True

    def test_partial_config_merges_with_defaults(self):
        state = new_state()
        state["messages_since_last"] = 20
        ok, reason, _ = should_surface("x", 0.25, state, {"threshold": 0.5}, current_time=1000.0)
        assert ok is False
        assert "threshold" in reason.lower()

    def test_default_config_values_match(self):
        assert DEFAULT_CONFIG["threshold"] == 0.3
        assert DEFAULT_CONFIG["max_surfaces_per_session"] == 5
        assert DEFAULT_CONFIG["min_messages_between"] == 10
        assert DEFAULT_CONFIG["cooldown_seconds"] == 300


# ===========================================================================
# The exit seam — a refusal that exits 0 is half a refusal
# ===========================================================================


class TestTheUnknownSubcommandRefusalReachesTheExitCode:
    """The fleet refusal sweep, 2026-09-07: `governance <bogus>` exited 0.

    Printed through `warning()`, which marks nothing, so the entry point's
    `resolve_exit(True)` read a clean command and returned 0 — a caller asking
    whether the verb existed was told yes. Same sentence, through `error()`.
    """

    def test_an_unknown_subcommand_exits_two(self, capsys):
        from aipass.cli.apps.modules import reset_command_state, resolve_exit
        from aipass.memory.apps.modules import governance as governance_module

        reset_command_state()
        assert governance_module.handle_command("governance", ["nonsense"]) is True
        assert resolve_exit(True) == 2, "governance refused an unknown subcommand but would exit 0"
        captured = capsys.readouterr()
        assert "nonsense" in captured.out + captured.err

    def test_the_bare_verb_still_exits_zero(self, capsys):
        """The other half: introspection is not a refusal and must stay 0."""
        from aipass.cli.apps.modules import reset_command_state, resolve_exit
        from aipass.memory.apps.modules import governance as governance_module

        reset_command_state()
        assert governance_module.handle_command("governance", []) is True
        assert resolve_exit(True) == 0, "bare governance is introspection, not a failure"
        # Read the capture: exit 0 alone cannot tell introspection from silence.
        captured = capsys.readouterr()
        assert "governance Module" in captured.out
        assert "should_surface" in captured.out
