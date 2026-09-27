# ===================AIPASS====================
# META DATA HEADER
# Name: test_cli_and_contracts.py - CLI Routing, Contracts, and Infrastructure Tests
# Description: main()'s help/introspection/exit-code routing, route_command, and the json shim's contracts
# Version: 1.1.0
# Created: 2026-03-28
# Modified: 2026-09-27
# Category: commons/tests
#
# CHANGELOG (Max 5 entries):
#   - v1.1.0 (2026-09-27): fleet green - file top, product imports hoisted, capsys over err_console,
#     router effects asserted, stdlib-only StringIO test retired
#   - v1.0.0 (2026-03-28): Initial creation — covers seedgo test_quality gaps
#
# CODE STANDARDS:
#   - Pytest function style (no unittest classes)
#   - Mocks heavy deps (prax logger, database)
# =============================================

"""Tests for apps/commons.py (main, route_command) and apps/handlers/json/json_handler.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(constant) — print_help's and print_introspection's display strings

import importlib
import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Mock infrastructure before importing commons modules
# ---------------------------------------------------------------------------

_mock_logger = MagicMock()
_mock_logger_module = MagicMock()
_mock_logger_module.system_logger = _mock_logger

try:
    from aipass.prax.apps.modules.logger import system_logger  # noqa: F401
except ImportError:
    sys.modules.setdefault("aipass.prax", MagicMock())
    sys.modules.setdefault("aipass.prax.apps", MagicMock())
    sys.modules.setdefault("aipass.prax.apps.modules", MagicMock())
    sys.modules.setdefault("aipass.prax.apps.modules.logger", _mock_logger_module)

try:
    from aipass.cli.apps.modules import console  # noqa: F401
except ImportError:
    _mock_cli = MagicMock()
    _mock_cli.console = MagicMock()
    _mock_cli.header = MagicMock()
    _mock_cli.error = MagicMock()
    _mock_cli.warning = MagicMock()
    sys.modules.setdefault("aipass.cli", MagicMock())
    sys.modules.setdefault("aipass.cli.apps", MagicMock())
    sys.modules.setdefault("aipass.cli.apps.modules", _mock_cli)

import aipass.commons.apps.commons as commons_main
from aipass.commons.apps.commons import (
    main,
    print_help,
    print_introspection,
    route_command,
    ensure_database,
)
from aipass.cli.apps.modules.display import error as cli_error, command_failed
import aipass.commons.apps.handlers.json.json_handler as jh
from aipass.commons.apps.modules import catchup as catchup_module
from aipass.commons.apps.modules import commons_identity as identity_module
from aipass.commons.apps.modules import digest as digest_module
from aipass.commons.apps.modules import explore as explore_module


# ===========================================================================
# CLI Routing: --help flag
# ===========================================================================


def test_help_flag_returns_zero():
    """Passing --help to main() should return 0 and show help."""
    with (
        patch.object(sys, "argv", ["commons", "--help"]),
        patch.object(commons_main, "ensure_database", return_value=True),
        patch.object(commons_main, "discover_modules", return_value=[MagicMock()]),
        patch.object(commons_main, "print_help") as mock_ph,
    ):
        result = main()
        assert result == 0
        mock_ph.assert_called_once()


# ===========================================================================
# CLI Routing: -h short help flag
# ===========================================================================


def test_short_help_flag_returns_zero():
    """Passing '-h' to main() should return 0 and show help."""
    with (
        patch.object(sys, "argv", ["commons", "-h"]),
        patch.object(commons_main, "ensure_database", return_value=True),
        patch.object(commons_main, "discover_modules", return_value=[MagicMock()]),
        patch.object(commons_main, "print_help") as mock_ph,
    ):
        result = main()
        assert result == 0
        mock_ph.assert_called_once()


# ===========================================================================
# CLI Routing: "help" word
# ===========================================================================


def test_help_word_returns_zero():
    """Passing 'help' as a command to main() should return 0 and show help."""
    with (
        patch.object(sys, "argv", ["commons", "help"]),
        patch.object(commons_main, "ensure_database", return_value=True),
        patch.object(commons_main, "discover_modules", return_value=[MagicMock()]),
        patch.object(commons_main, "print_help") as mock_ph,
    ):
        result = main()
        assert result == 0
        mock_ph.assert_called_once()


# ===========================================================================
# Module routing: a help flag on a verb that takes no arguments
# ===========================================================================


@pytest.mark.parametrize("flag", ["--help", "-h"])
@pytest.mark.parametrize(
    ("module", "command", "verb", "headline"),
    [
        (catchup_module, "catchup", "run_catchup", "Catchup orchestration"),
        (digest_module, "digest", "show_digest", "Thin router for community digest workflows"),
        (explore_module, "explore", "explore_rooms", "secret room exploration"),
        (explore_module, "secrets", "list_secrets", "secret room exploration"),
        (identity_module, "whoami", "get_caller_branch", "Branch identity detection"),
    ],
)
def test_a_help_flag_prints_the_module_help_and_never_runs_the_verb(module, command, verb, headline, flag, capsys):
    """Until 2026-09-27 these five ignored their arguments, so asking for help ran the command."""
    with patch.object(module, verb) as ran:
        assert module.handle_command(command, [flag]) is True

    ran.assert_not_called()
    assert headline in capsys.readouterr().out


# ===========================================================================
# CLI Routing: print_help callable
# ===========================================================================


def test_print_help_is_callable():
    """print_help should be a callable function."""
    assert callable(print_help)


# ===========================================================================
# CLI Routing: print_introspection callable
# ===========================================================================


def test_print_introspection_is_callable():
    """print_introspection should be callable and accept a modules list."""
    assert callable(print_introspection)
    # Should not raise when called with an empty list
    print_introspection([])


# ===========================================================================
# CLI Routing: no_args triggers print_introspection
# ===========================================================================


def test_no_args_triggers_introspection():
    """Running main() with no args should call print_introspection and return 0."""
    with (
        patch.object(sys, "argv", ["commons"]),
        patch.object(commons_main, "ensure_database", return_value=True),
        patch.object(commons_main, "discover_modules", return_value=[]),
        patch.object(commons_main, "print_introspection") as mock_pi,
    ):
        result = main()
        assert result == 0
        mock_pi.assert_called_once()


# ===========================================================================
# Success/Failure Paths: help preempts command routing (--help)
# ===========================================================================


def test_help_preempts_command_routing():
    """--help should be handled before command routing even with a valid command."""
    mock_module = MagicMock()
    mock_module.handle_command.return_value = True
    with (
        patch.object(sys, "argv", ["commons", "--help"]),
        patch.object(commons_main, "ensure_database", return_value=True),
        patch.object(commons_main, "discover_modules", return_value=[mock_module]),
        patch.object(commons_main, "print_help") as mock_ph,
    ):
        result = main()
        assert result == 0
        mock_ph.assert_called_once()
        mock_module.handle_command.assert_not_called()


# ===========================================================================
# Success/Failure Paths: known routes return True, unknown return False
# ===========================================================================


def test_route_command_returns_true_for_handled():
    """route_command hands the command to the first module that takes it, then stops (mutant: loop not stopped)."""
    mock_module = MagicMock()
    mock_module.handle_command.return_value = True
    later_module = MagicMock()
    result = route_command("feed", ["--room", "general"], [mock_module, later_module])
    assert result is True
    mock_module.handle_command.assert_called_once_with("feed", ["--room", "general"])
    later_module.handle_command.assert_not_called()


def test_route_command_returns_false_for_unhandled():
    """route_command should return False when no module handles the command."""
    mock_module = MagicMock()
    mock_module.handle_command.return_value = False
    result = route_command("nonexistent_command", [], [mock_module])
    assert result is False


# ===========================================================================
# Return Type Contracts: command_returns_bool
# ===========================================================================


def test_route_command_returns_bool():
    """route_command answers its own True, never the module's truthy value.

    handle_command may return anything truthy - a dict of results, a status
    string. route_command's contract is bool, and main() feeds that straight to
    resolve_exit(). An isinstance check cannot catch a regression here because a
    passed-through dict would fail it too loudly to reach production; what this
    pins is that the value is the literal True and not the payload.
    Mutant killed: route_command passing [] instead of the args it was given.
    """
    mock_module = MagicMock()
    mock_module.handle_command.return_value = {"handled": True, "rows": 3}
    result = route_command("test", ["x"], [mock_module])
    assert result is True
    mock_module.handle_command.assert_called_once_with("test", ["x"])


# ===========================================================================
# Exit Status: a printed refusal exits non-zero (the owner's ruling 2026-09-07)
# ===========================================================================


def test_main_returns_nonzero_when_a_handled_command_refused(capsys):
    """A module that handled the command but refused must exit non-zero.

    The defect this pins: handle_command() answers *handled*, not *succeeded*,
    so a refusal returned True and main() turned that into exit 0 -
    `thread not_a_real_subarg_xyz` printed "Invalid post_id" and reported
    success to the shell that called it. 2 is the fleet's code for
    handled-but-failed (cli's resolve_exit), 1 is reserved for unhandled.
    Mutant killed: error() rendering on the stdout console instead of err_console.
    """

    def refusing_module(command, args):
        # What post.py does with a non-integer post_id: print through cli's
        # error(), which marks the command failed, then report it as handled.
        # Driven through the real error() on purpose - setting the flag by hand
        # would still pass if error() stopped marking, the exact regression.
        cli_error("Invalid post_id - must be an integer")
        return True

    mock_module = MagicMock()
    mock_module.handle_command.side_effect = refusing_module
    with (
        patch.object(sys, "argv", ["commons", "thread", "not_a_real_subarg_xyz"]),
        patch.object(commons_main, "ensure_database", return_value=True),
        patch.object(commons_main, "discover_modules", return_value=[mock_module]),
    ):
        assert main() == 2
    assert "Invalid post_id" in capsys.readouterr().err


def test_main_returns_zero_when_a_handled_command_did_not_refuse():
    """The other half of the contract: a clean run still exits 0.

    Without this, a seam that simply always returned 1 would satisfy the test
    above and break every successful command in the fleet.
    """
    mock_module = MagicMock()
    mock_module.handle_command.return_value = True
    with (
        patch.object(sys, "argv", ["commons", "feed"]),
        patch.object(commons_main, "ensure_database", return_value=True),
        patch.object(commons_main, "discover_modules", return_value=[mock_module]),
    ):
        assert main() == 0


def test_cli_error_marks_the_command_failed(capsys):
    """The seam commons relies on: cli's error() marks, main() reads.

    Commons owns no refusal machinery of its own - all 62 of its error() call
    sites reach cli's renderer, which sets the flag resolve_exit() consults. If
    that ever stopped marking, every one of them would silently return to exit
    0, which is why this branch's suite pins someone else's function.
    Mutant killed: error() rendering on the stdout console instead of err_console.
    """
    assert command_failed() is False
    cli_error("Invalid post_id - must be an integer")
    assert command_failed() is True
    out, err = capsys.readouterr()
    assert "Invalid post_id" in err
    assert "Invalid post_id" not in out


def test_unknown_command_names_the_whole_invocation():
    """An unknown command exits non-zero and names what was actually typed.

    Reporting only the first word hid the token that failed: `thread bogus`
    used to be reported as "Unknown command: thread", naming a command that
    plainly exists.
    """
    mock_module = MagicMock()
    mock_module.handle_command.return_value = False
    with (
        patch.object(sys, "argv", ["commons", "nosuchverb", "nosucharg"]),
        patch.object(commons_main, "ensure_database", return_value=True),
        patch.object(commons_main, "discover_modules", return_value=[mock_module]),
        patch.object(commons_main, "error") as mock_error,
    ):
        assert main() == 1
        assert "nosuchverb nosucharg" in mock_error.call_args[0][0]


def test_ensure_database_answers_false_when_init_db_raises(tmp_path: Path):
    """A failed init must answer False, not propagate - main() refuses on it.

    ensure_database catches broadly and returns a verdict; if that except ever
    stops answering False, main() reads a None as falsey by luck rather than by
    contract, and a re-raise would crash the CLI instead of printing the
    refusal. Both halves are pinned here: the failure verdict and the success
    verdict on the same real function. The success half runs the real init_db,
    so DB_PATH is pointed at tmp_path first - the branch's commons.db is live.
    """
    with patch("aipass.commons.apps.modules.database.init_db", side_effect=sqlite3.OperationalError("no such table")):
        assert ensure_database() is False

    scratch = tmp_path / "commons.db"
    with patch("aipass.commons.apps.handlers.database.db.DB_PATH", scratch):
        assert ensure_database() is True
    assert scratch.exists()


# ===========================================================================
# Return Type Contracts: paths_return_path
# ===========================================================================


def test_json_path_returns_path_like():
    """get_json_path answers a real pathlib.Path.

    It used to answer a str built by os.path.join, and this test asserted
    ``result.endswith(".json")`` — which only a str can do. That was commons
    diverging from the other seventeen branches, and seedgo's contract carried
    it as a named strict xfail (GET_JSON_PATH_TYPE). The shim (DPLAN-0325)
    binds the one service, which answers a Path, so a caller doing
    ``.parent`` or ``/`` works here now like it does everywhere else.
    """
    result = jh.get_json_path("testmod", "config")
    assert isinstance(result, Path), f"expected a pathlib.Path, got {type(result).__name__}"
    assert result.name.endswith(".json")


# ===========================================================================
# Error Resilience: missing_file (FileNotFoundError handling)
# ===========================================================================


def test_missing_file_load_json_auto_creates(tmp_path, monkeypatch):
    """Loading JSON for a missing_file should auto-create it, not raise FileNotFoundError.

    Redirected through the fleet seam rather than by patching a module
    constant: the shim holds no BRANCH_JSON_DIR, because the one service
    (DPLAN-0325) resolves the directory on every call from AIPASS_TEST_LOG_DIR.
    Patching an attribute would silently do nothing.
    Mutant killed: load_json answering defaults without writing the file.
    """
    monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path / "missing_file_test"))
    ghost_path = jh.get_json_path("ghost", "config")
    assert not ghost_path.exists()

    result = jh.load_json("ghost", "config")
    assert ghost_path.exists()
    assert result is not None and result["module_name"] == "ghost"


# ===========================================================================
# Error Resilience: empty_file handling
# ===========================================================================


def test_empty_file_recovery(tmp_path, monkeypatch):
    """An empty_file should be detected as corrupt and recreated with defaults."""
    monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path / "empty_file_test"))

    # Create the directory and an empty_content file. The sandbox is MEASURED
    # off the handler rather than spelled out here: the one service spells it
    # <seam>/<branch>/<branch>_json, so a literal would drift the first time
    # that changes.
    empty_path = jh.get_json_path("emptymod", "config")
    empty_path.parent.mkdir(parents=True, exist_ok=True)
    empty_path.write_text("", encoding="utf-8")

    result = jh.ensure_json_exists("emptymod", "config")
    assert result is True

    loaded = jh.load_json("emptymod", "config")
    assert loaded is not None
    assert isinstance(loaded, dict)
    assert loaded["module_name"] == "emptymod"


# ===========================================================================
# Infrastructure Mocking: reimport_after_mock (importlib.reload)
# ===========================================================================


def test_reimport_after_mock_preserves_function():
    """Verify that importlib.reload can reimport a module after mocking.

    Asserts on a PUBLIC name now. It used to reach for ``_get_default``, a
    private factory the old handler owned; the shim binds the one service and
    has no private surface at all, so the reload claim has to be made about
    something the shim actually publishes. ``load_json`` is one of its nine
    names and is rebound by the reload exactly as the factory was.
    """
    # reload() the module and confirm it still works
    importlib.reload(jh)
    assert callable(jh.load_json)

    # Deliberately NOT restoring a pre-reload binding here. The old version of
    # this test saved and re-assigned `_get_default`, a private symbol nothing
    # else looked at. Doing the same to a shim name is a leak: the reload
    # rebinds all nine names to a FRESH handle over the one service, so putting
    # one name back to the pre-reload object leaves the module holding two
    # handles at once. Caught by seedgo's contract
    # (test_a_migrated_shim_binds_one_handle_rooted_at_its_own_branch) and only
    # in the composed CI run, where this suite executes before that check in
    # the same process. The reload already leaves a consistent module; the
    # restore was the side effect it claimed to prevent.
    assert len({id(getattr(jh, name).__self__) for name in ("load_json", "save_json", "get_json_path")}) == 1, (
        "the reload left this module holding more than one service handle"
    )


def test_discover_modules_returns_every_public_router_in_modules_dir():
    """discover_modules imports each non-underscore file in apps/modules/ and keeps it.

    Every other test replaces discover_modules with a patch; this one runs it
    for real against the shipped modules directory (imports only, no writes).
    Mutant killed: the `modules.append(module)` line removed - discovery answers [].
    """
    found = commons_main.discover_modules()

    expected = sorted(p.stem for p in commons_main.MODULES_DIR.glob("*.py") if not p.name.startswith("_"))
    assert [m.__name__.rsplit(".", 1)[-1] for m in found] == expected
    assert all(callable(m.handle_command) for m in found)
