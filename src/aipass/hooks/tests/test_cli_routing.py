# =================== AIPass ====================
# Name: test_cli_routing.py
# Description: Tests for hooks's entry point routing, help and introspection
# Version: 1.2.3
# Created: 2026-09-03
# Modified: 2026-10-17
# =============================================

"""Tests for apps/hooks.py, the branch's CLI entry point."""

# A refusal that exits 0 reads as success to the shell, so exit codes are pinned.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that hooks.py parses and imports, ruff and collection cover it
# seedgo: no-test-needed(documentation) — the help text's prose beyond its section headers, the documentation checker
# seedgo: no-test-needed(stdlib) — importlib.import_module's submodule resolution, the stdlib's own

import importlib
import os
import re
import sys
from pathlib import Path

import pytest

from aipass.hooks.apps import hooks as branch_entry

_MODULES_PACKAGE = "aipass.hooks.apps.modules"


class _StubModule:
    """Stand-in for a discovered module exposing handle_command()."""

    __name__ = "aipass.hooks.apps.modules.stub"
    __doc__ = "Stub module for routing tests."

    def __init__(self, handled_command="probe"):
        self.handled_command = handled_command
        self.calls = []

    def handle_command(self, command, args):
        self.calls.append((command, list(args)))
        return command == self.handled_command


@pytest.fixture
def stub_module(monkeypatch):
    """Replace module discovery with a single controllable stub."""
    stub = _StubModule()
    monkeypatch.setattr(branch_entry, "discover_modules", lambda: [stub])
    return stub


@pytest.fixture
def entry_logger(monkeypatch):
    """Capture calls made to the ENTRY POINT's logger.

    Not conftest's ``mock_logger``, which patches the engine's logger.
    """
    captured: list = []

    class _CapturingLogger:
        def info(self, *args, **kwargs):
            captured.append(("info", args))

        def warning(self, *args, **kwargs):
            captured.append(("warning", args))

        def error(self, *args, **kwargs):
            captured.append(("error", args))

    monkeypatch.setattr(branch_entry, "logger", _CapturingLogger())
    return captured


def _run(monkeypatch, argv):
    """Invoke main() with a synthetic argv."""
    monkeypatch.setattr(sys, "argv", ["hooks", *argv])
    return branch_entry.main()


def test_print_introspection_renders_identity_and_help_pointer(capsys):
    """print_introspection names the branch and points at --help."""
    branch_entry.print_introspection()

    out = capsys.readouterr().out
    assert "HOOKS" in out
    assert "Discovered Modules:" in out
    assert "--help" in out


def test_print_help_has_usage_and_examples(capsys):
    """print_help carries the two sections the house pattern requires."""
    branch_entry.print_help()

    out = capsys.readouterr().out
    assert "USAGE:" in out
    assert "EXAMPLES:" in out


def test_no_args_triggers_introspection(monkeypatch, capsys):
    """Bare invocation shows the self-map, not help, and exits 0."""
    assert _run(monkeypatch, []) == 0

    out = capsys.readouterr().out
    assert "Discovered Modules:" in out
    assert "USAGE:" not in out


@pytest.mark.parametrize("flag", ["--help", "-h", "help"])
def test_help_flag_preempts_routing(monkeypatch, capsys, flag):
    """All three help spellings show help and exit 0."""
    assert _run(monkeypatch, [flag]) == 0

    assert "USAGE:" in capsys.readouterr().out


@pytest.mark.parametrize("flag", ["--version", "-V"])
def test_version_flag_prints_the_header_version(monkeypatch, capsys, flag):
    """--version reports the branch and the version the FILE claims, then exits 0.

    Read from the header: a hardcoded version only confirms whatever drifted last.
    """
    header = re.search(
        r"^# Version:\s*(\S+)",
        (Path(branch_entry.__file__).read_text(encoding="utf-8")),
        re.MULTILINE,
    )
    assert header is not None, "apps/hooks.py has no '# Version:' header line"

    assert _run(monkeypatch, [flag]) == 0

    out = capsys.readouterr().out
    assert "hooks" in out
    assert header.group(1) in out


def test_route_command_returns_true_for_known_command(stub_module):
    """A handled command returns a real bool True, not a truthy value."""
    result = branch_entry.route_command("probe", [], [stub_module])

    assert isinstance(result, bool)
    assert result is True


def test_route_command_returns_false_for_unknown_command(stub_module):
    """An unhandled command returns False so main() can refuse."""
    result = branch_entry.route_command("nonexistent", [], [stub_module])

    assert result is False


def test_route_command_survives_a_raising_module(entry_logger):
    """One exploding module must not take the router down with it."""

    class _Exploding:
        __name__ = "exploding"

        def handle_command(self, command, args):
            raise RuntimeError("boom")

    result = branch_entry.route_command("probe", [], [_Exploding()])

    assert result is False
    assert any(level == "error" for level, _ in entry_logger)


def test_known_command_exits_zero(monkeypatch, stub_module):
    """A routed command reports success."""
    assert _run(monkeypatch, ["probe"]) == 0
    assert stub_module.calls == [("probe", [])]


def test_unknown_command_exits_nonzero(monkeypatch, stub_module, capsys):
    """An unrecognized command is a refusal - and a refusal must not exit 0."""
    result = _run(monkeypatch, ["invalid_command"])

    captured = capsys.readouterr()

    assert result == 1
    # A refusal goes to stderr so redirecting stdout cannot swallow it.
    assert "Unknown command" in captured.err
    assert "Unknown command" not in captured.out


def test_subcommand_help_does_not_execute_the_command(monkeypatch, stub_module):
    """`hooks probe --help` asks the module for help; it never runs bare."""
    assert _run(monkeypatch, ["probe", "--help"]) == 0

    assert stub_module.calls == [("probe", ["--help"])]


def test_subcommand_help_on_unknown_command_exits_nonzero(monkeypatch, stub_module, capsys):
    """Asking for help on a command that does not exist is still a refusal."""
    result = _run(monkeypatch, ["nonexistent", "--help"])

    captured = capsys.readouterr()

    assert result == 1
    assert "Unknown command" in captured.err
    assert "Unknown command" not in captured.out


def test_branch_name_is_set_at_import_time(monkeypatch):
    """The entry point stamps AIPASS_BRANCH_NAME before prax resolves a branch.

    reload re-executes the body; the already-imported module would pass with the line deleted.
    """
    monkeypatch.delenv("AIPASS_BRANCH_NAME", raising=False)

    reloaded = importlib.reload(branch_entry)

    assert os.environ["AIPASS_BRANCH_NAME"] == "hooks"
    assert reloaded.discover_modules is not None


class TestDiscoverySkipsRetiredModules:
    """`(disabled)` in the filename must actually retire the module.

    import_module loads "presence(disabled)" as cleanly as "presence"; discovery must skip it by name.
    """

    def _modules_dir(self, monkeypatch, tmp_path):
        monkeypatch.setattr(branch_entry, "MODULES_DIR", tmp_path)
        return tmp_path

    @staticmethod
    def _stand_in(monkeypatch, stem, module):
        """Serve `module` from sys.modules under the name discovery computes for `stem`.

        import_module returns a sys.modules entry first, so an unskipped retired stem comes back as this.
        """
        monkeypatch.setitem(sys.modules, f"{_MODULES_PACKAGE}.{stem}", module)

    def test_a_disabled_module_is_never_imported(self, monkeypatch, tmp_path):
        self._modules_dir(monkeypatch, tmp_path)
        (tmp_path / "presence(disabled).py").write_text("raise AssertionError('imported')\n", encoding="utf-8")
        self._stand_in(monkeypatch, "presence(disabled)", _StubModule())

        assert branch_entry.discover_modules() == []

    def test_a_live_module_beside_it_still_loads(self, monkeypatch, tmp_path):
        self._modules_dir(monkeypatch, tmp_path)
        (tmp_path / "presence(disabled).py").write_text("", encoding="utf-8")
        (tmp_path / "sessions.py").write_text("", encoding="utf-8")
        stub = _StubModule()
        self._stand_in(monkeypatch, "sessions", stub)
        self._stand_in(monkeypatch, "presence(disabled)", _StubModule())

        assert branch_entry.discover_modules() == [stub]

    def test_the_mark_is_matched_anywhere_in_the_name(self, monkeypatch, tmp_path):
        # "presence(disabled)_v2" is the same retirement as a suffix mark.
        self._modules_dir(monkeypatch, tmp_path)
        (tmp_path / "presence(disabled)_v2.py").write_text("", encoding="utf-8")
        self._stand_in(monkeypatch, "presence(disabled)_v2", _StubModule())

        assert branch_entry.discover_modules() == []
