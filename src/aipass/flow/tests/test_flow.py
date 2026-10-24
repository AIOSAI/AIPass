# =================== AIPass ====================
# Name: test_flow.py
# Description: Tests for flow.py CLI entry point
# Version: 1.1.1
# Created: 2026-05-12
# Modified: 2026-10-24
# =============================================

"""Tests for apps/flow.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that flow.py parses and imports
# seedgo: no-test-needed(stdlib) — the `if __name__ == "__main__":` guard's sys.exit() and os._exit() calls

import importlib
import signal
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest

from aipass.cli.apps.modules import reset_command_state
from aipass.flow.apps import flow as flow_entry
from aipass.flow.apps.flow import (
    discover_modules,
    main,
    print_help,
    print_introspection,
    print_module_help,
    route_command,
)


_FLOW = "aipass.flow.apps.flow"
_MODULES_PKG = "aipass.flow.apps.modules"


def _stand_in(monkeypatch: pytest.MonkeyPatch, stem: str, module: ModuleType | None) -> str:
    """Put ``module`` where the import system looks for ``<package>.<stem>``.

    None makes the real import raise ModuleNotFoundError; monkeypatch undoes the entry.
    """
    name = f"{_MODULES_PKG}.{stem}"
    monkeypatch.setitem(sys.modules, name, module)
    return name


def _import_refusal(name: str) -> str:
    """Ask the interpreter what importing ``name`` raises, in the test's own hands."""
    with pytest.raises(ModuleNotFoundError) as refused:
        importlib.import_module(name)
    return str(refused.value)


def _make_module(
    name: str,
    *,
    has_handle: bool = True,
    doc: str | None = "Short description line",
) -> ModuleType:
    """Create a fake module object that mimics a flow submodule."""
    mod = ModuleType(f"aipass.flow.apps.modules.{name}")
    mod.__doc__ = doc
    if has_handle:
        mod.handle_command = MagicMock(return_value=False)  # type: ignore[attr-defined]
    return mod


def _make_handling_module(name: str, doc: str | None = "Handles things") -> ModuleType:
    """Create a module whose handle_command returns True (claims the command)."""
    mod = _make_module(name, doc=doc)
    mod.handle_command.return_value = True  # type: ignore[union-attr]
    return mod


class TestDiscoverModules:
    """Tests for discover_modules()."""

    def test_empty_when_modules_dir_missing(self, tmp_path: Path) -> None:
        """Returns empty list when modules/ directory does not exist."""
        fake_dir = tmp_path / "nonexistent"
        with patch(f"{_FLOW}.MODULES_DIR", fake_dir):
            result = discover_modules()
        assert result == []

    def test_discovers_module_with_handle_command(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Discovers .py files that expose handle_command(): the module the real
        import answers for the name built from the file is the one returned.
        """
        modules_dir = tmp_path / "modules"
        modules_dir.mkdir()
        (modules_dir / "good_mod.py").write_text("# stub", encoding="utf-8")
        fake_module = _make_module("good_mod")
        _stand_in(monkeypatch, "good_mod", fake_module)

        with patch(f"{_FLOW}.MODULES_DIR", modules_dir):
            result = discover_modules()

        assert result == [fake_module]

    def test_skips_module_without_handle_command(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Skips a module the import answers when it lacks handle_command()."""
        modules_dir = tmp_path / "modules"
        modules_dir.mkdir()
        (modules_dir / "no_handle.py").write_text("# stub", encoding="utf-8")
        _stand_in(monkeypatch, "no_handle", _make_module("no_handle", has_handle=False))

        with patch(f"{_FLOW}.MODULES_DIR", modules_dir):
            result = discover_modules()

        assert result == []

    def test_skips_underscore_files(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Ignores files starting with underscore (e.g., __init__.py).

        Each name has an importable module with handle_command, so only the skip keeps them out.
        """
        modules_dir = tmp_path / "modules"
        modules_dir.mkdir()
        (modules_dir / "__init__.py").write_text("# init", encoding="utf-8")
        (modules_dir / "_private.py").write_text("# private", encoding="utf-8")
        _stand_in(monkeypatch, "__init__", _make_module("__init__"))
        _stand_in(monkeypatch, "_private", _make_module("_private"))

        with patch(f"{_FLOW}.MODULES_DIR", modules_dir):
            result = discover_modules()

        assert result == []

    def test_handles_import_error_gracefully(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mock_logger: MagicMock
    ) -> None:
        """Logs the import's own error and continues when a module fails to import."""
        modules_dir = tmp_path / "modules"
        modules_dir.mkdir()
        (modules_dir / "bad_mod.py").write_text("# broken", encoding="utf-8")
        name = _stand_in(monkeypatch, "bad_mod", None)
        refusal = _import_refusal(name)

        with patch(f"{_FLOW}.MODULES_DIR", modules_dir):
            result = discover_modules()

        assert result == []
        logged = [c.args[0] for c in mock_logger.error.call_args_list]
        assert logged == [f"[FLOW] Failed to load module {name}: {refusal}"]

    def test_discovers_multiple_modules(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Discovers all valid modules in the directory, each under its own name."""
        modules_dir = tmp_path / "modules"
        modules_dir.mkdir()
        (modules_dir / "alpha.py").write_text("# stub", encoding="utf-8")
        (modules_dir / "beta.py").write_text("# stub", encoding="utf-8")
        mod_a = _make_module("alpha")
        mod_b = _make_module("beta")
        _stand_in(monkeypatch, "alpha", mod_a)
        _stand_in(monkeypatch, "beta", mod_b)

        with patch(f"{_FLOW}.MODULES_DIR", modules_dir):
            result = discover_modules()

        assert sorted(result, key=lambda m: m.__name__) == [mod_a, mod_b]


class TestRouteCommand:
    """Tests for route_command()."""

    def test_routes_to_handling_module(self) -> None:
        """Returns True when a module handles the command."""
        mod = _make_handling_module("create_plan")
        result = route_command("create", [".", "subject"], [mod])

        assert result is True
        mod.handle_command.assert_called_once_with("create", [".", "subject"])

    def test_returns_false_when_no_module_handles(self) -> None:
        """Returns False when no module claims the command."""
        mod = _make_module("create_plan")  # handle_command returns False
        result = route_command("unknown", [], [mod])

        assert result is False

    def test_handles_broken_pipe_error(self) -> None:
        """Catches BrokenPipeError, returns True, and offers the command to no one else.

        Mutant: the BrokenPipeError branch's `return True` -> `continue` reddens this.
        """
        mod = _make_module("list_plans")
        mod.handle_command.side_effect = BrokenPipeError  # type: ignore[union-attr]
        later = _make_handling_module("list_other")

        result = route_command("list", [], [mod, later])
        assert result is True
        mod.handle_command.assert_called_once_with("list", [])
        later.handle_command.assert_not_called()

    def test_handles_generic_exception(self) -> None:
        """Catches generic exceptions, logs, and continues to next module."""
        bad_mod = _make_module("bad")
        bad_mod.handle_command.side_effect = RuntimeError("kaboom")  # type: ignore[union-attr]

        good_mod = _make_handling_module("good")

        result = route_command("cmd", [], [bad_mod, good_mod])
        assert result is True
        good_mod.handle_command.assert_called_once()

    def test_returns_false_on_empty_modules(self) -> None:
        """Returns False when modules list is empty."""
        result = route_command("anything", [], [])
        assert result is False

    def test_stops_routing_after_first_handler(self) -> None:
        """Stops after the first module claims the command."""
        mod_a = _make_handling_module("first")
        mod_b = _make_module("second")

        result = route_command("cmd", [], [mod_a, mod_b])
        assert result is True
        mod_b.handle_command.assert_not_called()

    def test_all_modules_fail_with_exceptions(self) -> None:
        """Returns False when every module raises an exception."""
        mod = _make_module("failing")
        mod.handle_command.side_effect = ValueError("nope")  # type: ignore[union-attr]

        result = route_command("cmd", [], [mod])
        assert result is False


class TestMain:
    """Tests for main() entry point."""

    def test_returns_1_when_no_modules(self) -> None:
        """Returns 1 and prints error when no modules discovered."""
        with (
            patch(f"{_FLOW}.discover_modules", return_value=[]),
            patch("sys.argv", ["flow"]),
        ):
            result = main()
        assert result == 1

    def test_introspection_on_no_args(self) -> None:
        """Shows introspection when called with no arguments."""
        mod = _make_module("create_plan")

        with (
            patch(f"{_FLOW}.discover_modules", return_value=[mod]),
            patch(f"{_FLOW}.print_introspection") as mock_intro,
            patch("sys.argv", ["flow"]),
        ):
            result = main()

        assert result == 0
        mock_intro.assert_called_once_with([mod])

    def test_version_long_flag(self) -> None:
        """--version prints version and returns 0."""
        mod = _make_module("create_plan")

        with (
            patch(f"{_FLOW}.discover_modules", return_value=[mod]),
            patch("sys.argv", ["flow", "--version"]),
        ):
            result = main()
        assert result == 0

    def test_version_short_flag(self) -> None:
        """-V prints version and returns 0."""
        mod = _make_module("create_plan")

        with (
            patch(f"{_FLOW}.discover_modules", return_value=[mod]),
            patch("sys.argv", ["flow", "-V"]),
        ):
            result = main()
        assert result == 0

    def test_help_long_flag(self) -> None:
        """--help shows help and returns 0."""
        mod = _make_module("create_plan")

        with (
            patch(f"{_FLOW}.discover_modules", return_value=[mod]),
            patch(f"{_FLOW}.print_help") as mock_help,
            patch("sys.argv", ["flow", "--help"]),
        ):
            result = main()

        assert result == 0
        mock_help.assert_called_once()

    def test_help_short_flag(self) -> None:
        """-h shows help and returns 0."""
        mod = _make_module("create_plan")

        with (
            patch(f"{_FLOW}.discover_modules", return_value=[mod]),
            patch(f"{_FLOW}.print_help") as mock_help,
            patch("sys.argv", ["flow", "-h"]),
        ):
            result = main()

        assert result == 0
        mock_help.assert_called_once()

    def test_help_word(self) -> None:
        """'help' word shows help and returns 0."""
        mod = _make_module("create_plan")

        with (
            patch(f"{_FLOW}.discover_modules", return_value=[mod]),
            patch(f"{_FLOW}.print_help") as mock_help,
            patch("sys.argv", ["flow", "help"]),
        ):
            result = main()

        assert result == 0
        mock_help.assert_called_once()

    def test_routes_known_command(self) -> None:
        """Routes a valid command and returns 0."""
        mod = _make_handling_module("create_plan")

        with (
            patch(f"{_FLOW}.discover_modules", return_value=[mod]),
            patch("sys.argv", ["flow", "create", ".", "subject"]),
        ):
            result = main()

        assert result == 0
        mod.handle_command.assert_called_once_with("create", [".", "subject"])

    def test_unknown_command_returns_1(self) -> None:
        """Returns 1 for an unrecognized command."""
        mod = _make_module("create_plan")  # handle_command returns False

        with (
            patch(f"{_FLOW}.discover_modules", return_value=[mod]),
            patch("sys.argv", ["flow", "bogus"]),
        ):
            result = main()

        assert result == 1

    def test_unknown_command_with_help_flag(self) -> None:
        """Unknown command followed by --help still exits 1."""
        mod = _make_module("create_plan")  # handle_command returns False

        with (
            patch(f"{_FLOW}.discover_modules", return_value=[mod]),
            patch(f"{_FLOW}.print_module_help", return_value=False) as mock_mod_help,
            patch("sys.argv", ["flow", "bogus", "--help"]),
        ):
            result = main()

        assert result == 1
        mock_mod_help.assert_called_once_with("bogus", [mod])

    def test_unknown_command_with_short_help_flag(self) -> None:
        """Unknown command followed by -h still exits 1."""
        mod = _make_module("create_plan")  # handle_command returns False

        with (
            patch(f"{_FLOW}.discover_modules", return_value=[mod]),
            patch(f"{_FLOW}.print_module_help", return_value=False) as mock_mod_help,
            patch("sys.argv", ["flow", "bogus", "-h"]),
        ):
            result = main()

        assert result == 1
        mock_mod_help.assert_called_once_with("bogus", [mod])

    def test_command_with_no_extra_args(self) -> None:
        """Routes command with empty remaining args."""
        mod = _make_handling_module("list_plans")

        with (
            patch(f"{_FLOW}.discover_modules", return_value=[mod]),
            patch("sys.argv", ["flow", "list"]),
        ):
            result = main()

        assert result == 0
        mod.handle_command.assert_called_once_with("list", [])

    def test_main_catches_unhandled_exception(self) -> None:
        """main() catches unexpected exceptions from _main_impl and returns 1."""
        with patch(f"{_FLOW}.discover_modules", side_effect=RuntimeError("boom")):
            with patch("sys.argv", ["flow"]):
                result = main()
        assert result == 1


_NO_SIGPIPE = "this platform has no SIGPIPE, and flow.py sets nothing where it is missing"


def _child(code: str, tmp_path: Path) -> subprocess.CompletedProcess[str]:
    """Run ``code`` in a fresh interpreter, the only one whose import of flow.py is still to come."""
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )


@pytest.mark.skipif(not hasattr(signal, "SIGPIPE"), reason=_NO_SIGPIPE)
class TestSigpipeDisposition:
    """Importing flow.py leaves SIGPIPE alone; the started program sets the kernel default (CI 38132534544)."""

    def test_importing_the_entry_leaves_sigpipe_as_the_interpreter_set_it(self, tmp_path: Path) -> None:
        """An import in a pytest worker must not hand the worker a SIGPIPE that kills it silently."""
        code = (
            "import signal\n"
            "before = int(signal.getsignal(signal.SIGPIPE))\n"
            "import aipass.flow.apps.flow\n"
            "print(before, int(signal.getsignal(signal.SIGPIPE)))\n"
        )
        child = _child(code, tmp_path)

        assert child.returncode == 0, child.stderr
        before, after = (int(n) for n in child.stdout.split())
        assert before == int(signal.SIG_IGN)
        assert after == before

    def test_the_started_program_restores_the_kernel_default(self, tmp_path: Path) -> None:
        """Run as a program, flow still ends quietly on a pipe to head: SIGPIPE is SIG_DFL by exit."""
        code = (
            "import atexit, runpy, signal, sys\n"
            "atexit.register(lambda: print('SIGPIPE', int(signal.getsignal(signal.SIGPIPE)), file=sys.stderr))\n"
            "sys.argv = ['flow.py', '--version']\n"
            f"runpy.run_path({flow_entry.__file__!r}, run_name='__main__')\n"
        )
        child = _child(code, tmp_path)

        assert child.returncode == 0, child.stderr
        reported = [line for line in child.stderr.splitlines() if line.startswith("SIGPIPE ")]
        assert reported == [f"SIGPIPE {int(signal.SIG_DFL)}"], child.stderr


class TestPrintIntrospection:
    """Tests for print_introspection()."""

    def test_with_modules(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Displays module names and descriptions."""
        mod = _make_module("create_plan", doc="Create a new plan")
        print_introspection([mod])

        out, _err = capsys.readouterr()
        assert "create_plan" in out
        assert "Create a new plan" in out

    def test_with_empty_modules(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Displays fallback text when no modules discovered."""
        print_introspection([])

        out, _err = capsys.readouterr()
        assert "No modules discovered" in out
        assert "Discovered Modules: 0" in out

    def test_module_without_docstring(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Uses 'No description' when module has no docstring."""
        mod = _make_module("bare_mod", doc=None)
        print_introspection([mod])

        out, _err = capsys.readouterr()
        assert "bare_mod" in out
        assert "No description" in out

    @pytest.mark.parametrize("names", [("alpha",), ("alpha", "beta")])
    def test_every_discovered_module_is_named(self, names, capsys: pytest.CaptureFixture[str]) -> None:
        """One module or several, each one appears in the listing.

        Descriptions never echo the name, so each column must carry its own value; the count floors the loop.
        Mutant: `{len(modules)}` -> `{len(modules) - 1}` in print_introspection reddens this.
        """
        assert len(names) >= 1
        docs = {name: f"purpose text {index}" for index, name in enumerate(names)}

        print_introspection([_make_module(name, doc=docs[name]) for name in names])

        printed, _err = capsys.readouterr()
        assert f"Discovered Modules: {len(names)}" in printed
        for name in names:
            assert name in printed
            assert docs[name] in printed


class TestPrintHelp:
    """Tests for print_help()."""

    def test_with_modules(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Shows formatted help with module listing."""
        mod = _make_module("create_plan", doc="Create a new plan")
        print_help([mod])

        out, _err = capsys.readouterr()
        assert "USAGE:" in out
        assert "AVAILABLE COMMANDS:" in out
        assert "create" in out
        assert "Create a new plan" in out

    def test_with_empty_modules(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Shows help even when no modules are discovered."""
        print_help([])

        out, _err = capsys.readouterr()
        assert "USAGE:" in out
        assert "No modules discovered" in out

    @pytest.mark.parametrize(
        ("module_name", "expected_verb"),
        [("create_plan", "create"), ("templates", "templates")],
    )
    def test_the_help_table_prints_the_verb_that_executes(
        self, module_name, expected_verb, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Only the verb the dispatcher accepts is printed, never the filename."""
        print_help([_make_module(module_name, doc="Any description")])

        printed, _err = capsys.readouterr()
        assert expected_verb in printed
        if module_name != expected_verb:
            assert module_name not in printed

    def test_a_module_owning_several_verbs_declares_them(self, capsys: pytest.CaptureFixture[str]) -> None:
        """COMMAND_VERBS wins over the filename-derived short name."""
        mod = _make_module("template_manager", doc="Template Manager Module")
        mod.__dict__["COMMAND_VERBS"] = ("templates", "register", "unregister", "scan")
        print_help([mod])

        printed, _err = capsys.readouterr()
        assert "templates, register, unregister, scan" in printed
        assert "template_manager" not in printed

    def test_module_without_docstring(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Uses 'No description' for undocumented modules."""
        mod = _make_module("mystery", doc=None)
        print_help([mod])

        out, _err = capsys.readouterr()
        assert "mystery" in out
        assert "No description" in out


class TestPrintModuleHelp:
    """Tests for print_module_help()."""

    def test_exact_match(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Finds module by exact name match, and the header names the module found.

        Mutant: header(f"Flow - {module_name} Command") -> header("Flow - Command") reddens this.
        """
        mod = _make_module("create_plan", doc="Create plans\nMore details here")
        assert print_module_help("create_plan", [mod]) is True

        out, err = capsys.readouterr()
        assert "Create plans" in out
        assert "Unknown command" not in out + err
        assert "Flow - create_plan Command" in out

    def test_no_match(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Shows error for unknown command.

        The diagnostic goes to stderr and the pointer to stdout, so both channels are read.
        """
        mod = _make_module("create_plan")
        assert print_module_help("nonexistent", [mod]) is False

        out, err = capsys.readouterr()
        assert "Unknown command: nonexistent" in err
        assert "Run drone @flow --help for available commands" in out
        reset_command_state()

    def test_module_without_docstring(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Shows 'No documentation available' for undocumented module."""
        mod = _make_module("bare_mod", doc=None)
        print_module_help("bare_mod", [mod])

        out, _err = capsys.readouterr()
        assert "No documentation available" in out

    def test_a_multiline_docstring_is_shown_whole_and_stripped(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Every line reaches the reader, without the leading/trailing blanks.

        Module help strips the whole docstring; the listing shows only its first line.
        """
        mod = _make_module(
            "list_plans",
            doc="\nList plans\n\nShows all plans in the registry.\n",
        )
        print_module_help("list_plans", [mod])

        printed, _err = capsys.readouterr()
        assert "List plans" in printed
        assert "Shows all plans in the registry." in printed
        assert not printed.strip().endswith("\\n")
