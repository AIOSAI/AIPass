# =================== AIPass ====================
# Name: test_conftest_fixtures.py
# Description: Pins that spawn's own mocking fixtures reach the code they claim to mock
# Version: 1.0.1
# Created: 2026-08-30
# Modified: 2026-09-29
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

# A fixture that mocks nothing is worse than no fixture: it passes, it looks
# like coverage, and it lets the real object keep working — in this case
# writing into @prax's live state directory from inside a test run.
#
# MEASURED by @memory, reproduced across the fleet by @seedgo (2026-08-30):
# `patch("aipass.prax.logger")` — the spelling spawn and four other branches
# used — never reached a single consumer. `file_ops` binds the logger OBJECT
# into its own globals at import (`from aipass.prax.apps.modules.logger import
# system_logger as logger`), and `aipass/prax/__init__.py` copies it once more
# one level up, so a patch at or above `aipass.prax` is always upstream of a
# copy already taken. Under all four techniques the fleet was using, the
# consumer's logger was still a live SystemLogger.
#
# The rule: THE LAST DOT MUST BE RESOLVED AT CALL TIME. These are identity
# pins, not behaviour pins, because identity is the thing that silently broke.


class TestMockLoggerReachesItsConsumer:
    """`mock_logger` must be the object `file_ops` calls, not a distant cousin."""

    def test_fixture_replaces_the_consumer_binding(self, mock_logger):
        """Object identity — the only check that would have caught the old spelling."""
        assert file_ops.logger is mock_logger

    def test_the_replacement_is_actually_a_mock(self, mock_logger):
        """A RECORDING double, not merely an object of the right class.

        isinstance alone passed for any Mock at all, including one nothing ever
        reaches. What the fixture is FOR is that a call made through the
        consumer's binding lands on the object the test holds, so the call is
        made and read back.
        """
        assert isinstance(file_ops.logger, Mock)

        file_ops.logger.warning("template registry missing: %s", "citizen")

        mock_logger.warning.assert_called_once_with("template registry missing: %s", "citizen")
        assert mock_logger.error.call_count == 0

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


def _copy_of_the_templates(tmp_path: Path) -> Path:
    """The shipped template tree, copied under a directory named dropbox.

    The parent is named dropbox so a skip that read the whole path, and not the
    parts under the root of the walk, would hide the whole copy. The real
    archive gets one planted file, since templates/.archive is untracked and a
    fresh checkout has none.
    """
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

    The rule is the owner of the project's, 09-27 20:42, in paraphrase: a
    dropbox is ignored by all, nothing looks into it and no process runs out of
    it, a sandbox like .archive. templates/citizen/dropbox and
    templates/citizen/.archive are not such places: they are the templates of
    them, shipped content copied into every newborn, so they are watched.
    templates/.archive is a real archive. Which walks skip and by which names is
    spawn's decision (DPLAN-0354 leg 4): templates/.archive at the root of the
    walk, and __pycache__ anywhere. The runner cannot serve conftest, so these
    pins stand on red first alone.
    """

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
    """cli's header fires cli_header_displayed; under spawn's tests it lands on a recorder.

    The bus probe (2026-09-27) counted 12 real fires from spawn's suite, every one
    cli_header_displayed from display.header(). The autouse fixture closes all of
    them at once and no test can forget it (spawn's decision, DPLAN-0354 leg 3).
    """

    def test_the_real_header_fires_into_the_recorder_only(self, cli_trigger_bus, monkeypatch):
        """Ran red before the fixture existed (fixture not found)."""
        real_fire = Mock()
        monkeypatch.setattr(trigger_core.Trigger, "fire", real_fire)

        display.header("Probe Title")

        assert cli_trigger_bus.fired == [("cli_header_displayed", {"title": "Probe Title"})]
        assert real_fire.call_count == 0


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

        assert json_handler.get_json_path("probe", "config").parent == _isolate_spawn_json

    def test_a_write_lands_in_the_sandbox_and_not_in_the_branch(self, _isolate_spawn_json):
        """The failure this guard exists for: a real file in spawn/spawn_json/."""

        assert json_handler.ensure_json_exists("probe", "config") is True
        assert (_isolate_spawn_json / "probe_config.json").exists()
        assert _isolate_spawn_json != json_handler.get_json_path.__self__.branch_root / "spawn_json"
