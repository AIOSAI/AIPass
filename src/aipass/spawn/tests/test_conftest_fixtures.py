"""Pins that spawn's own mocking fixtures reach the code they claim to mock.

A fixture that mocks nothing is worse than no fixture: it passes, it looks like
coverage, and it lets the real object keep working — in this case writing into
@prax's live state directory from inside a test run.

MEASURED by @memory, reproduced across the fleet by @seedgo (2026-08-30):
`patch("aipass.prax.logger")` — the spelling spawn and four other branches
used — never reached a single consumer. `file_ops` binds the logger OBJECT into
its own globals at import (`from aipass.prax.apps.modules.logger import
system_logger as logger`), and `aipass/prax/__init__.py` copies it once more one
level up, so a patch at or above `aipass.prax` is always upstream of a copy
already taken. Under all four techniques the fleet was using, the consumer's
logger was still a live SystemLogger.

The rule: THE LAST DOT MUST BE RESOLVED AT CALL TIME. These are identity pins,
not behaviour pins, because identity is the thing that silently broke.
"""

from unittest.mock import Mock, patch

import aipass.spawn.apps.handlers.file_ops as file_ops


class TestMockLoggerReachesItsConsumer:
    """`mock_logger` must be the object `file_ops` calls, not a distant cousin."""

    def test_fixture_replaces_the_consumer_binding(self, mock_logger):
        """Object identity — the only check that would have caught the old spelling."""
        assert file_ops.logger is mock_logger

    def test_the_replacement_is_actually_a_mock(self, mock_logger):
        assert isinstance(file_ops.logger, Mock)

    def test_calls_through_the_consumer_are_recorded(self, mock_logger):
        file_ops.logger.info("probe")

        mock_logger.info.assert_called_once_with("probe")

    def test_patching_the_prax_package_would_reach_nothing(self):
        """The retired spelling, pinned as the failure it was.

        Kept as an executable record rather than a comment: if some future
        refactor makes `aipass.prax.logger` the live binding again, this goes red
        and says so, instead of leaving a stale warning in a docstring.
        """
        before = file_ops.logger

        with patch("aipass.prax.logger") as upstream:
            assert file_ops.logger is before, "the old spelling now reaches — update the fixture note"
            assert file_ops.logger is not upstream


class TestMockJsonHandlerReachesItsConsumer:
    """`mock_json_handler` already patches at the call site — pin that it stays there."""

    def test_fixture_replaces_the_call_site(self, mock_json_handler):
        assert file_ops.json_handler.log_operation is mock_json_handler

    def test_the_patched_call_is_recorded(self, mock_json_handler):
        file_ops.json_handler.log_operation("probe")

        mock_json_handler.assert_called_once_with("probe")


class TestIsolateSpawnJsonActuallyRedirects:
    """`_isolate_spawn_json` is autouse — every test in the suite depends on it.

    It used to patch `json_handler._JSON_DIR` and the singleton's `_json_dir`.
    Since DPLAN-0325 there is no singleton and no private attribute: the shim
    binds prax's json service, which recomputes its directory from
    AIPASS_TEST_LOG_DIR on every call. The old pin only asserted the attribute
    EXISTED, so it would have gone green against a redirect that redirected
    nothing. These measure where a write actually lands.
    """

    def test_the_handlers_directory_is_the_one_the_fixture_returns(self, _isolate_spawn_json):
        """Identity between what the fixture promises and what the shim does."""
        from aipass.spawn.apps.handlers.json import json_handler

        assert json_handler.get_json_path("probe", "config").parent == _isolate_spawn_json

    def test_a_write_lands_in_the_sandbox_and_not_in_the_branch(self, _isolate_spawn_json):
        """The failure this guard exists for: a real file in spawn/spawn_json/."""
        from aipass.spawn.apps.handlers.json import json_handler

        assert json_handler.ensure_json_exists("probe", "config") is True
        assert (_isolate_spawn_json / "probe_config.json").exists()
        assert _isolate_spawn_json != json_handler.get_json_path.__self__.branch_root / "spawn_json"
