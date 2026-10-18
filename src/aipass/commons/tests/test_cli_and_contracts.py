# =================== AIPass ====================
# META DATA HEADER
# Name: test_cli_and_contracts.py - CLI Routing, Contracts, and Infrastructure Tests
# Description: main()'s help/introspection/exit-code routing, route_command, and the json shim's contracts
# Version: 1.3.0
# Created: 2026-03-28
# Modified: 2026-10-17
# Category: commons/tests
#
# CHANGELOG (Max 5 entries):
#   - v1.3.0 (2026-10-11): SIGPIPE pins - an import leaves it alone, the started program sets SIG_DFL
#   - v1.2.0 (2026-10-05): a help flag anywhere after the verb never runs it; help-aware verbs keep their own help
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
import signal
import sqlite3
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

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


def test_help_flag_returns_zero():
    """Passing --help to main() should return 0 and show help."""
    with (
        patch("sys.argv", ["commons", "--help"]),
        patch.object(commons_main, "ensure_database", return_value=True),
        patch.object(commons_main, "discover_modules", return_value=[MagicMock()]),
        patch.object(commons_main, "print_help") as mock_ph,
    ):
        result = main()
        assert result == 0
        mock_ph.assert_called_once()


def test_short_help_flag_returns_zero():
    """Passing '-h' to main() should return 0 and show help."""
    with (
        patch("sys.argv", ["commons", "-h"]),
        patch.object(commons_main, "ensure_database", return_value=True),
        patch.object(commons_main, "discover_modules", return_value=[MagicMock()]),
        patch.object(commons_main, "print_help") as mock_ph,
    ):
        result = main()
        assert result == 0
        mock_ph.assert_called_once()


def test_help_word_returns_zero():
    """Passing 'help' as a command to main() should return 0 and show help."""
    with (
        patch("sys.argv", ["commons", "help"]),
        patch.object(commons_main, "ensure_database", return_value=True),
        patch.object(commons_main, "discover_modules", return_value=[MagicMock()]),
        patch.object(commons_main, "print_help") as mock_ph,
    ):
        result = main()
        assert result == 0
        mock_ph.assert_called_once()


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
    """A help flag on a no-argument verb explains; asking for help must never run the command."""
    with patch.object(module, verb) as ran:
        assert module.handle_command(command, [flag]) is True

    ran.assert_not_called()
    assert headline in capsys.readouterr().out


@pytest.mark.parametrize(
    ("argv", "target"),
    [
        (["prompt", "--help"], "aipass.commons.apps.modules.engagement.generate_prompt"),
        (["prompt", "-h"], "aipass.commons.apps.modules.engagement.generate_prompt"),
        (["comment", "12", "--help"], "aipass.commons.apps.modules.comment.add_comment"),
        (["post", "general", "Title", "-h"], "aipass.commons.apps.modules.post.create_post"),
    ],
)
def test_a_help_flag_on_an_unguarded_verb_prints_general_help_and_never_runs_it(argv, target):
    """A help flag anywhere after the verb explains, never executes: 'prompt --help' must not post a live prompt."""
    with (
        patch("sys.argv", ["commons", *argv]),
        patch.object(commons_main, "ensure_database", return_value=True),
        patch(target) as ran,
        patch.object(commons_main, "print_help") as mock_ph,
    ):
        assert main() == 0

    ran.assert_not_called()
    mock_ph.assert_called_once()


@pytest.mark.parametrize(
    "argv",
    [["catchup", "--help"], ["room", "create", "-h"]],
)
def test_a_help_aware_verb_gets_its_own_help_with_the_args_it_was_given(argv):
    """The help-aware modules explain themselves; the dispatcher hands them the arguments unchanged."""
    module = MagicMock()
    module.handle_command.return_value = True
    with (
        patch("sys.argv", ["commons", *argv]),
        patch.object(commons_main, "ensure_database", return_value=True),
        patch.object(commons_main, "discover_modules", return_value=[module]),
        patch.object(commons_main, "print_help") as mock_ph,
    ):
        assert main() == 0

    module.handle_command.assert_called_once_with(argv[0], argv[1:])
    mock_ph.assert_not_called()


def test_print_help_is_callable():
    """print_help should be a callable function."""
    assert callable(print_help)


def test_print_introspection_is_callable():
    """print_introspection should be callable and accept a modules list."""
    assert callable(print_introspection)
    print_introspection([])


def test_no_args_triggers_introspection():
    """Running main() with no args should call print_introspection and return 0."""
    with (
        patch("sys.argv", ["commons"]),
        patch.object(commons_main, "ensure_database", return_value=True),
        patch.object(commons_main, "discover_modules", return_value=[]),
        patch.object(commons_main, "print_introspection") as mock_pi,
    ):
        result = main()
        assert result == 0
        mock_pi.assert_called_once()


def test_help_preempts_command_routing():
    """--help should be handled before command routing even with a valid command."""
    mock_module = MagicMock()
    mock_module.handle_command.return_value = True
    with (
        patch("sys.argv", ["commons", "--help"]),
        patch.object(commons_main, "ensure_database", return_value=True),
        patch.object(commons_main, "discover_modules", return_value=[mock_module]),
        patch.object(commons_main, "print_help") as mock_ph,
    ):
        result = main()
        assert result == 0
        mock_ph.assert_called_once()
        mock_module.handle_command.assert_not_called()


def test_route_command_returns_true_for_handled():
    """route_command returns True when a module handles the command: the first module that takes it, then stops.

    Mutant killed: loop not stopped after the first module handles it."""
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


def test_route_command_returns_bool():
    """route_command answers its own True, never the module's truthy value: main() feeds it to resolve_exit().

    Mutant killed: route_command passing [] instead of the args it was given."""
    mock_module = MagicMock()
    mock_module.handle_command.return_value = {"handled": True, "rows": 3}
    result = route_command("test", ["x"], [mock_module])
    assert result is True
    mock_module.handle_command.assert_called_once_with("test", ["x"])


def test_main_returns_nonzero_when_a_handled_command_refused(capsys):
    """A module that handled the command but refused must exit 2 (handled-but-failed; 1 is unhandled).

    handle_command() answers *handled*, not *succeeded*, so main() must read cli's refusal flag."""

    def refusing_module(command, args):
        # The real error(), not a hand-set flag: that would pass even if error() stopped marking.
        cli_error("Invalid post_id - must be an integer")
        return True

    mock_module = MagicMock()
    mock_module.handle_command.side_effect = refusing_module
    with (
        patch("sys.argv", ["commons", "thread", "not_a_real_subarg_xyz"]),
        patch.object(commons_main, "ensure_database", return_value=True),
        patch.object(commons_main, "discover_modules", return_value=[mock_module]),
    ):
        assert main() == 2
    assert "Invalid post_id" in capsys.readouterr().err


def test_main_returns_zero_when_a_handled_command_did_not_refuse():
    """The other half of the contract: a clean run still exits 0."""
    mock_module = MagicMock()
    mock_module.handle_command.return_value = True
    with (
        patch("sys.argv", ["commons", "feed"]),
        patch.object(commons_main, "ensure_database", return_value=True),
        patch.object(commons_main, "discover_modules", return_value=[mock_module]),
    ):
        assert main() == 0


def test_cli_error_marks_the_command_failed(capsys):
    """The seam commons relies on: cli's error() marks, main() reads; every commons refusal depends on it.

    Mutant killed: error() rendering on the stdout console instead of err_console."""
    assert command_failed() is False
    cli_error("Invalid post_id - must be an integer")
    assert command_failed() is True
    out, err = capsys.readouterr()
    assert "Invalid post_id" in err
    assert "Invalid post_id" not in out


def test_unknown_command_names_the_whole_invocation():
    """An unknown command exits non-zero and names the whole invocation, not just the first word."""
    mock_module = MagicMock()
    mock_module.handle_command.return_value = False
    with (
        patch("sys.argv", ["commons", "nosuchverb", "nosucharg"]),
        patch.object(commons_main, "ensure_database", return_value=True),
        patch.object(commons_main, "discover_modules", return_value=[mock_module]),
        patch.object(commons_main, "error") as mock_error,
    ):
        assert main() == 1
        assert "nosuchverb nosucharg" in mock_error.call_args[0][0]


def test_ensure_database_answers_false_when_init_db_raises(tmp_path: Path):
    """A failed init must answer False, not propagate - main() refuses on it.

    The success half runs the real init_db, so DB_PATH points at tmp_path: the branch's commons.db is live."""
    with patch("aipass.commons.apps.modules.database.init_db", side_effect=sqlite3.OperationalError("no such table")):
        assert ensure_database() is False

    scratch = tmp_path / "commons.db"
    with patch("aipass.commons.apps.handlers.database.db.DB_PATH", scratch):
        assert ensure_database() is True
    assert scratch.exists()


def test_json_path_returns_path_like():
    """get_json_path answers a real pathlib.Path, like the shared json service everywhere else."""
    result = jh.get_json_path("testmod", "config")
    assert isinstance(result, Path), f"expected a pathlib.Path, got {type(result).__name__}"
    assert result.name.endswith(".json")


def test_missing_file_load_json_auto_creates(tmp_path, monkeypatch):
    """Loading JSON for a missing_file should auto-create it, not raise FileNotFoundError.

    Redirected via AIPASS_TEST_LOG_DIR: the service resolves its dir per call, so patching a constant does nothing."""
    monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path / "missing_file_test"))
    ghost_path = jh.get_json_path("ghost", "config")
    assert not ghost_path.exists()

    result = jh.load_json("ghost", "config")
    assert ghost_path.exists()
    assert result is not None and result["module_name"] == "ghost"


def test_empty_file_recovery(tmp_path, monkeypatch):
    """An empty_file should be detected as corrupt and recreated with defaults."""
    monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path / "empty_file_test"))

    # The path is asked of the handler, not spelled here: a literal would drift with the service's layout.
    empty_path = jh.get_json_path("emptymod", "config")
    empty_path.parent.mkdir(parents=True, exist_ok=True)
    empty_path.write_text("", encoding="utf-8")

    result = jh.ensure_json_exists("emptymod", "config")
    assert result is True

    loaded = jh.load_json("emptymod", "config")
    assert loaded is not None
    assert isinstance(loaded, dict)
    assert loaded["module_name"] == "emptymod"


def test_reimport_after_mock_preserves_function():
    """Verify that importlib.reload can reimport a module after mocking."""
    importlib.reload(jh)
    assert callable(jh.load_json)

    # Never restore a pre-reload binding: the reload rebinds all names to one fresh handle, and
    # restoring one leaves two handles, which seedgo's one-handle shim contract catches later in CI.
    assert len({id(getattr(jh, name).__self__) for name in ("load_json", "save_json", "get_json_path")}) == 1, (
        "the reload left this module holding more than one service handle"
    )


def test_discover_modules_returns_every_public_router_in_modules_dir():
    """discover_modules imports each non-underscore file in apps/modules/ and keeps it (run for real, no patch).

    Mutant killed: the `modules.append(module)` line removed - discovery answers []."""
    found = commons_main.discover_modules()

    expected = sorted(p.stem for p in commons_main.MODULES_DIR.glob("*.py") if not p.name.startswith("_"))
    assert [m.__name__.rsplit(".", 1)[-1] for m in found] == expected
    assert all(callable(m.handle_command) for m in found)


_NO_SIGPIPE = "this platform has no SIGPIPE, and commons.py sets nothing where it is missing"


def _child(code: str, tmp_path: Path) -> subprocess.CompletedProcess[str]:
    """Run code in a fresh interpreter: this process imported commons.py at collection."""
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )


@pytest.mark.skipif(not hasattr(signal, "SIGPIPE"), reason=_NO_SIGPIPE)
def test_importing_the_entry_leaves_sigpipe_as_the_interpreter_set_it(tmp_path):
    """An import must not set SIG_DFL: in an xdist worker the first EPIPE would kill it silently."""
    code = (
        "import signal\n"
        "before = int(signal.getsignal(signal.SIGPIPE))\n"
        "import aipass.commons.apps.commons\n"
        "print(before, int(signal.getsignal(signal.SIGPIPE)))\n"
    )
    child = _child(code, tmp_path)

    assert child.returncode == 0, child.stderr
    before, after = (int(n) for n in child.stdout.split())
    assert before == int(signal.SIG_IGN)
    assert after == before


@pytest.mark.skipif(not hasattr(signal, "SIGPIPE"), reason=_NO_SIGPIPE)
def test_the_started_program_restores_the_kernel_default(tmp_path):
    """Run as a program, commons still ends quietly on a pipe to head; the database init is stubbed."""
    code = (
        "import atexit, runpy, signal, sys\n"
        "import aipass.commons.apps.modules.database as database\n"
        "database.init_db = lambda: None\n"
        "database.close_db = lambda conn: None\n"
        "atexit.register(lambda: print('SIGPIPE', int(signal.getsignal(signal.SIGPIPE)), file=sys.stderr))\n"
        "sys.argv = ['commons.py', '--version']\n"
        f"runpy.run_path({commons_main.__file__!r}, run_name='__main__')\n"
    )
    child = _child(code, tmp_path)

    assert child.returncode == 0, child.stderr
    assert f"THE_COMMONS v{commons_main.VERSION}" in child.stdout
    reported = [line for line in child.stderr.splitlines() if line.startswith("SIGPIPE ")]
    assert reported == [f"SIGPIPE {int(signal.SIG_DFL)}"], child.stderr
