# =================== AIPass ====================
# Name: test_conftest_fixtures.py
# Description: The autouse fixtures must actually reach what they claim to mock
# Version: 1.0.0
# Created: 2026-08-31
# Modified: 2026-08-31
# =============================================

"""A mock that reaches nothing passes every test that does not assert on it.

``mock_logger`` patched ``aipass.prax.apps.modules.logger.system_logger`` — the
SOURCE attribute — while every flow module does
``from ... import system_logger as logger`` at import time and holds its own
binding. Patching upstream of a binding already taken reaches nothing, and it
reached nothing for as long as the fixture existed. Nothing failed, because a
mock nobody asserts on is indistinguishable from a mock that works.

@seedgo published the technique next to the standard after @prax ruled
(``drone @seedgo standard imports``). @spawn's note is the one worth keeping:
the correct technique already existed in their tree at one call site, written
before any of this came up — it just was not in the shared fixture. The right
answer existed in the fleet and nobody had written it down.

These tests are the writing-down. They assert the fixture's REACH, not its
existence, so the next upstream/downstream mix-up is a red test rather than a
silent hole.
"""

import sys

import pytest

import aipass.flow.apps.handlers.registry.load_registry as load_registry_module


class TestMockLoggerReachesTheConsumersBinding:
    """The fixture must replace what flow modules actually call."""

    def test_a_consumer_module_sees_the_mock(self, mock_logger):
        """The binding a handler resolves at call time IS the mock."""
        assert load_registry_module.logger is mock_logger, (
            "the autouse mock_logger did not reach a consumer's own binding — "
            "it is patching upstream of an import that already happened"
        )

    def test_calling_the_consumers_logger_records_on_the_mock(self, mock_logger):
        """Reach is not enough: the call has to land."""
        load_registry_module.logger.warning("probe")

        mock_logger.warning.assert_called_once_with("probe")

    def test_every_imported_flow_module_with_a_logger_is_covered(self, mock_logger):
        """No module keeps a live logger while the fixture claims containment.

        Walks ``sys.modules`` rather than a written list, for the same reason
        the dead-cwd pin does: the species is a fix landing on some of N
        identical paths, and a hand-written list is one more place for N to be
        undercounted.
        """
        missed = [
            name
            for name, module in sys.modules.items()
            if name.startswith("aipass.flow.apps")
            and getattr(module, "logger", None) is not None
            and module.logger is not mock_logger
        ]

        assert missed == [], f"modules still holding a live logger: {missed}"

    def test_the_source_attribute_is_patched_too(self, mock_logger):
        """A module imported LATER in a test must bind the mock, not the real one."""
        import aipass.prax.apps.modules.logger as prax_logger

        assert prax_logger.system_logger is mock_logger


class TestTheOptOutIsRealAndNarrow:
    """``real_logger`` exists because caplog reads the real logging module."""

    @pytest.mark.real_logger
    def test_marked_tests_keep_the_real_logger(self):
        """The marker must genuinely restore the real object, not a second mock."""
        from unittest.mock import MagicMock

        assert not isinstance(load_registry_module.logger, MagicMock), (
            "the real_logger marker did not restore the real logger — a caplog assertion under it would be vacuous"
        )

    def test_unmarked_tests_still_get_the_mock(self, mock_logger):
        """Negative control: the opt-out must not leak to its neighbours."""
        assert load_registry_module.logger is mock_logger
