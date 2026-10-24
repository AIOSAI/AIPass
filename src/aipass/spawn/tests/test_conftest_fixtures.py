# =================== AIPass ====================
# Name: test_conftest_fixtures.py
# Description: Pins that spawn's own mocking fixtures reach the code they claim to mock
# Version: 1.0.2
# Created: 2026-08-30
# Modified: 2026-10-24
# =============================================

"""Tests that tests/conftest.py's mocking fixtures actually reach apps/handlers/file_ops.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that apps/handlers/file_ops.py and apps/handlers/json/json_handler.py parse and import
# seedgo: no-test-needed(documentation) — docstrings on the conftest fixtures themselves

import shutil
from pathlib import Path
from unittest.mock import Mock, patch

import aipass.spawn.apps.handlers.file_ops as file_ops
from aipass.cli.apps.modules import display
from aipass.spawn.apps.handlers.json import json_handler
from aipass.trigger.apps.modules import core as trigger_core
from aipass.spawn.tests import conftest as spawn_conftest

# file_ops binds the logger object at import, so a patch at or above aipass.prax never reaches it:
# patch the consumer's own name. Identity pins, because identity is what silently broke.


class TestMockLoggerReachesItsConsumer:
    """`mock_logger` must be the object `file_ops` calls, not a distant cousin."""

    def test_fixture_replaces_the_consumer_binding(self, mock_logger):
        """Object identity — the only check that would have caught the old spelling."""
        assert file_ops.logger is mock_logger

    def test_the_replacement_is_actually_a_mock(self, mock_logger):
        """A RECORDING double, not merely an object of the right class."""
        assert isinstance(file_ops.logger, Mock)

        file_ops.logger.warning("template registry missing: %s", "citizen")

        mock_logger.warning.assert_called_once_with("template registry missing: %s", "citizen")
        assert mock_logger.error.call_count == 0

    def test_patching_the_prax_package_would_reach_nothing(self):
        """The retired spelling, pinned as the failure it was; red if it ever reaches again."""
        before = file_ops.logger

        with patch("aipass.prax.logger") as upstream:
            assert file_ops.logger is before, "the old spelling now reaches — update the fixture note"
            assert file_ops.logger is not upstream


class TestMockJsonHandlerReachesItsConsumer:
    """`mock_json_handler` already patches at the call site — pin that it stays there."""

    def test_fixture_replaces_the_call_site(self, mock_json_handler):
        assert file_ops.json_handler.log_operation is mock_json_handler


def _copy_of_the_templates(tmp_path: Path) -> Path:
    """The shipped template tree, copied under a directory named dropbox.

    So a skip reading the whole path would hide the copy; templates/.archive is untracked, so planted."""
    root = tmp_path / "dropbox" / "templates"
    shutil.copytree(spawn_conftest._shipped_templates_root(), root, ignore=shutil.ignore_patterns("__pycache__"))
    (root / ".archive").mkdir(exist_ok=True)
    (root / ".archive" / "old.md").write_text("retired", encoding="utf-8")
    (root / "citizen" / "__pycache__").mkdir()
    (root / "citizen" / "__pycache__" / "stale.pyc").write_bytes(b"\x00")
    return root


_TEMPLATE_DROPBOX_README = Path("citizen") / "dropbox" / "README.md"
_TEMPLATE_ARCHIVE_README = Path("citizen") / ".archive" / "README.md"


class TestTemplateWalksWatchTheTemplate:
    """The shipped-template guards watch all of templates/citizen and skip the real archive.

    templates/citizen/dropbox and .archive are shipped content, so watched; only templates/.archive is skipped."""

    def test_the_per_test_guard_catches_a_write_to_the_template_dropbox(self, tmp_path):
        """Ran red while the prune named dropbox: the write was not seen."""
        root = _copy_of_the_templates(tmp_path)
        before = spawn_conftest._template_tree_stats(root)

        with (root / _TEMPLATE_DROPBOX_README).open("a", encoding="utf-8") as readme:
            readme.write("\nwritten by a test\n")
        (root / ".archive" / "old.md").write_text("rewritten under the real archive", encoding="utf-8")
        after = spawn_conftest._template_tree_stats(root)

        touched = {name for name in set(before) | set(after) if before.get(name) != after.get(name)}
        assert touched == {str(_TEMPLATE_DROPBOX_README)}
        assert str(_TEMPLATE_ARCHIVE_README) in after
        assert not any(Path(name).parts[0] == ".archive" or "__pycache__" in Path(name).parts for name in after)

    def test_the_session_net_holds_the_template_dropbox_and_not_the_real_archive(self, tmp_path):
        """Ran red while the filter named dropbox and .archive at any depth."""
        root = _copy_of_the_templates(tmp_path)

        snapshot = set(spawn_conftest._template_snapshot(root))

        assert {root / _TEMPLATE_DROPBOX_README, root / _TEMPLATE_ARCHIVE_README} <= snapshot
        assert root / ".archive" / "old.md" not in snapshot
        assert root / "citizen" / "__pycache__" / "stale.pyc" not in snapshot


class TestTheHeaderNeverReachesTheRealBus:
    """cli's header fires no event, so spawn's tests need no stand-in bus."""

    def test_the_real_header_fires_nothing_on_the_real_bus(self, monkeypatch):
        """Ran red with header() firing cli_header_displayed again (one call on the real bus)."""
        real_fire = Mock()
        monkeypatch.setattr(trigger_core.Trigger, "fire", real_fire)

        display.header("Probe Title")

        assert real_fire.call_count == 0


class TestIsolateSpawnJsonActuallyRedirects:
    """`_isolate_spawn_json` is autouse — every test in the suite depends on it.

    Measures where a write lands: an attribute-exists pin passes a redirect that redirects nothing."""

    def test_the_handlers_directory_is_the_one_the_fixture_returns(self, _isolate_spawn_json):
        """Identity between what the fixture promises and what the shim does."""

        assert json_handler.get_json_path("probe", "config").parent == _isolate_spawn_json

    def test_a_write_lands_in_the_sandbox_and_not_in_the_branch(self, _isolate_spawn_json):
        """The failure this guard exists for: a real file in spawn/spawn_json/."""

        assert json_handler.ensure_json_exists("probe", "config") is True
        assert (_isolate_spawn_json / "probe_config.json").exists()
        assert _isolate_spawn_json != json_handler.get_json_path.__self__.branch_root / "spawn_json"
