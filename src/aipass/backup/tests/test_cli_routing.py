# =================== META ====================
# Name: test_cli_routing.py
# Description: Tests for apps/backup.py's command routing and the help gate every apps/modules/ verb carries
# Version: 2.0.9
# Created: 2026-06-12
# Modified: 2026-10-24
# =============================================

"""Tests for apps/backup.py's command routing and the help gate every apps/modules/ verb carries."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that every file in apps/modules/ parses and carries no unused import
# seedgo: no-test-needed(constant) — the literal text of VERSION, MODULE_NAME and each PRIMARY_COMMAND
# seedgo: no-test-needed(stdlib) — importlib's ability to import a module by dotted name, which discover_modules rides

import os
import sys
from collections.abc import Generator
from contextlib import ExitStack
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, call, patch

import pytest

from aipass.backup.apps import backup as entry
from aipass.backup.apps.modules import all as all_module
from aipass.backup.apps.modules import (
    display,
    drive_check,
    drive_clear,
    drive_stats,
    drive_sync,
    register,
    restore,
    settings,
    share,
    snapshot,
    status,
    versioned,
)

# argv is patched as patch("sys.argv", ...), not patch.object(sys, ...): seedgo's stdlib_patch
# reads only the first argument and scores bare `sys` as an unsanctioned stdlib patch.


SIMPLE_MODULES = [
    pytest.param(drive_sync, id="drive_sync"),
    pytest.param(drive_check, id="drive_check"),
    pytest.param(drive_stats, id="drive_stats"),
    pytest.param(drive_clear, id="drive_clear"),
    pytest.param(settings, id="settings"),
]

#: The verb past each help gate, spied so a gate that stops screening fails instead of doing the work.
#: settings is absent: its post-gate path raises rather than calling a verb.
VERB_AFTER_THE_GATE: dict[ModuleType, str] = {
    drive_sync: "run_drive_sync",
    drive_check: "run_drive_check",
    drive_stats: "run_drive_stats",
    drive_clear: "run_drive_clear",
}

#: The line print_help adds over print_introspection; drive_check and settings have none to pin.
HELP_ONLY_LINE: dict[ModuleType, str] = {
    drive_sync: "Usage: drive_sync",
    drive_stats: "Usage: drive_stats",
    drive_clear: "Usage: drive_clear",
}


def _spy_the_verb(mod: ModuleType, monkeypatch: pytest.MonkeyPatch) -> list:
    """Replace the module's post-gate verb with a recorder; return what it records."""
    calls: list = []
    name = VERB_AFTER_THE_GATE.get(mod)
    if name is not None:
        monkeypatch.setattr(mod, name, lambda *a, **k: calls.append((a, k)))
    return calls


def _assert_help_page(mod: ModuleType, out: str, err: str, ran: list) -> None:
    """The help page reached stdout, stderr stayed clean, the verb never ran."""
    assert f"{mod.MODULE_NAME} Module" in out
    assert f"Primary command: {mod.PRIMARY_COMMAND}" in out
    extra = HELP_ONLY_LINE.get(mod)
    if extra is not None:
        assert extra in out, f"help printed the introspection but not the help page: {out!r}"
    assert err == "", f"a help request wrote to stderr: {err!r}"
    assert ran == [], f"the help gate let the verb run: {ran!r}"


def _rows(block: str) -> list[str]:
    """The non-blank lines of one rendered help block, stripped."""
    return [line.strip() for line in block.splitlines() if line.strip()]


class TestHelpFlags:
    """--help, -h and the bare word 'help' print the page and run nothing."""

    @pytest.mark.parametrize("mod", SIMPLE_MODULES)
    def test_long_help_flag_prints_the_help_page_and_never_runs_the_verb(
        self, mod: ModuleType, capsys: pytest.CaptureFixture[str], monkeypatch
    ) -> None:
        """'--help' prints the module's help page and never reaches the verb."""
        ran = _spy_the_verb(mod, monkeypatch)

        assert mod.handle_command(mod.PRIMARY_COMMAND, ["--help"]) is True

        out, err = capsys.readouterr()
        _assert_help_page(mod, out, err, ran)

    @pytest.mark.parametrize("mod", SIMPLE_MODULES)
    def test_short_help_flag_prints_the_help_page_and_never_runs_the_verb(
        self, mod: ModuleType, capsys: pytest.CaptureFixture[str], monkeypatch
    ) -> None:
        """'-h' prints the module's help page and never reaches the verb."""
        ran = _spy_the_verb(mod, monkeypatch)

        assert mod.handle_command(mod.PRIMARY_COMMAND, ["-h"]) is True

        out, err = capsys.readouterr()
        _assert_help_page(mod, out, err, ran)

    @pytest.mark.parametrize("mod", SIMPLE_MODULES)
    def test_bare_help_word_prints_the_help_page_and_never_runs_the_verb(
        self, mod: ModuleType, capsys: pytest.CaptureFixture[str], monkeypatch
    ) -> None:
        """The bare word 'help' prints the same page the flags print."""
        ran = _spy_the_verb(mod, monkeypatch)

        assert mod.handle_command(mod.PRIMARY_COMMAND, ["help"]) is True

        out, err = capsys.readouterr()
        _assert_help_page(mod, out, err, ran)


class TestIntrospection:
    """No args prints the module's self-map, read off the real console."""

    @pytest.mark.parametrize("mod", SIMPLE_MODULES)
    def test_no_args_prints_the_introspection_page_on_stdout(
        self, mod: ModuleType, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """No args prints the introspection page: the module's name and the command it owns."""
        assert mod.handle_command(mod.PRIMARY_COMMAND, []) is True

        out, err = capsys.readouterr()
        assert f"{mod.MODULE_NAME} Module" in out
        assert f"Primary command: {mod.PRIMARY_COMMAND}" in out
        assert err == "", f"introspection wrote to stderr: {err!r}"

    @pytest.mark.parametrize("mod", SIMPLE_MODULES)
    def test_every_simple_module_carries_a_callable_print_introspection(self, mod: ModuleType) -> None:
        """print_introspection exists and is callable."""
        assert hasattr(mod, "print_introspection")
        assert callable(mod.print_introspection)


class TestModuleDiscovery:
    """The importlib walk under main(), run for real instead of replaced by a list."""

    def test_discovery_imports_the_command_modules_that_exist_in_apps_modules(self) -> None:
        """discover_modules returns the modules on disk, imported -- not a list a patch handed it."""
        # The only test that runs discovery unpatched; every other one replaces it with [fake_module].
        discovered = entry.discover_modules()

        found = sorted(module.__name__.split(".")[-1] for module in discovered)
        # A door publishes names and carries no handle_command: not a command.
        on_disk = sorted(
            path.stem for path in entry.MODULES_DIR.glob("*.py") if not path.name.startswith(("_", "door_"))
        )
        assert found == on_disk, f"discovery and apps/modules/ disagree: {found!r} vs {on_disk!r}"
        assert "door_trail" not in found, "a door reached the router as a command module"
        # An empty MODULES_DIR would pass the equality on []; identity rules out a re-imported twin.
        assert {"drive_sync", "register", "restore", "share"} <= set(found)
        assert drive_sync in discovered and register in discovered
        assert all(callable(module.handle_command) for module in discovered)
        assert "__init__" not in found, "a private file reached the router as a command module"


class TestUnknownCommand:
    """A command a module does not own is declined."""

    @pytest.mark.parametrize("mod", SIMPLE_MODULES)
    def test_a_command_the_module_does_not_own_returns_false(self, mod: ModuleType) -> None:
        """A command the module does not own returns False."""
        assert mod.handle_command("totally_invalid_command_xyz", []) is False


class TestReturnBool:
    """The True/False contract: a claimed command answers, a declined one is silent."""

    @pytest.mark.parametrize("mod", SIMPLE_MODULES)
    def test_an_owned_command_answers_with_exactly_the_introspection_page(
        self, mod: ModuleType, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A command the module owns is claimed and answered with its introspection page, nothing more."""
        assert mod.handle_command(mod.PRIMARY_COMMAND, []) is True
        routed = capsys.readouterr().out

        mod.print_introspection()
        page = capsys.readouterr().out

        assert page.strip(), "print_introspection printed nothing"
        assert routed == page, f"the claimed command answered with another page: {routed!r}"

    @pytest.mark.parametrize("mod", SIMPLE_MODULES)
    def test_a_foreign_command_is_declined_in_silence(
        self, mod: ModuleType, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A command the module does not own is declined in silence."""
        # route_command asks every module in turn: one that prints while declining talks over the owner.
        assert mod.handle_command("nonexistent", []) is False

        out, err = capsys.readouterr()
        assert out == "" and err == "", f"a decline printed: {out!r} / {err!r}"


class TestPrintHelp:
    """The entry point's curated command reference, read on the channel a user reads."""

    def test_print_help_lists_every_verb_in_commands_and_every_flag_in_options(
        self, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """print_help lists every verb as a COMMANDS row and every flag as an OPTIONS row."""
        assert callable(entry.print_help)
        # header() fires @cli's event bus; replaced where the entry point binds it, so nothing fires.
        titles: list[str] = []
        monkeypatch.setattr(entry, "header", lambda title, *args, **kwargs: titles.append(title))

        entry.print_help()

        assert titles == ["BACKUP — project backup & drive sync"]

        out, err = capsys.readouterr()
        assert err == "", f"the help page wrote to stderr: {err!r}"

        # Read by block: every verb is also spelled in EXAMPLES, so a whole-page match passes on nothing.
        commands = _rows(out.split("COMMANDS:", 1)[1].split("OPTIONS:", 1)[0])
        options = _rows(out.split("OPTIONS:", 1)[1].split("EXAMPLES:", 1)[0])

        # First word only: the 'all' row's description also names 'snapshot'.
        listed_verbs = [row.split()[0] for row in commands]
        for mod in (snapshot, versioned, all_module, register, status, settings, restore):
            verb = mod.PRIMARY_COMMAND
            assert verb in listed_verbs, f"COMMANDS block has no row for {verb}"

        all_row = next(row for row in commands if row.split()[0] == "all")
        assert "drive" in all_row.lower(), f"'all' row hides its drive stage: {all_row}"

        settings_row = next(row for row in commands if row.split()[0] == "settings")
        assert "drive_sync" in settings_row and "Not implemented" not in settings_row, settings_row

        documented_flags = [row.split()[0] for row in options]
        for flag in ("--name", "--quiet", "--registered", "--force", "--project", "--note", "--public"):
            assert flag in documented_flags, f"OPTIONS block has no row for {flag}"

    @pytest.mark.parametrize("mod", SIMPLE_MODULES)
    def test_print_introspection_prints_the_page_when_called_directly(
        self, mod: ModuleType, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """print_introspection, called on its own, prints the module's name and command."""
        # Direct: a print_introspection hollowed to `pass` behind an inline handle_command passes the routed tests.
        mod.print_introspection()

        out, err = capsys.readouterr()
        assert f"{mod.MODULE_NAME} Module" in out
        assert f"Primary command: {mod.PRIMARY_COMMAND}" in out
        assert err == "", f"introspection wrote to stderr: {err!r}"


#: (module, sentinel right after the help gate, args builder, the ONE expected call), built from one tmp_path
#: so a wrong operand, flag value or hardcoded root fails the row.
STANDALONE_ENTRY_MODULES = [
    pytest.param(
        all_module,
        "run_snapshot",
        lambda p: [str(p)],
        lambda p: call(
            str(p), verb=all_module.PRIMARY_COMMAND, pre_scanned=[(str(p / ".backupignore"), ".backupignore")]
        ),
        id="all",
    ),
    # drive_check is account-wide: "run" is its only executing route, with no project.
    pytest.param(drive_check, "run_drive_check", lambda p: ["run"], lambda p: call(), id="drive_check"),
    pytest.param(
        drive_clear,
        "run_drive_clear",
        lambda p: [str(p)],
        # The row never passes --force, so False is the claim: a self-confirming clear is the regression.
        lambda p: call(str(p), force=False),
        id="drive_clear",
    ),
    pytest.param(drive_stats, "run_drive_stats", lambda p: [str(p)], lambda p: call(str(p)), id="drive_stats"),
    pytest.param(
        drive_sync,
        "run_drive_sync",
        lambda p: [str(p)],
        lambda p: call(str(p), project_name="", note="", force=False),
        id="drive_sync",
    ),
    pytest.param(register, "resolve_caller_path", lambda p: [str(p)], lambda p: call(str(p)), id="register"),
    pytest.param(
        restore,
        "run_list_versions",
        lambda p: [str(p), "list", "some_file.py"],
        # args[2] is the FILE; reading args[1] looks up a file named "list".
        lambda p: call(str(p), "some_file.py"),
        id="restore",
    ),
    pytest.param(share, "run_share", lambda p: [str(p)], lambda p: call(str(p), public=False), id="share"),
    pytest.param(snapshot, "run_snapshot", lambda p: [str(p)], lambda p: call(str(p)), id="snapshot"),
    pytest.param(status, "resolve_caller_path", lambda p: [str(p)], lambda p: call(str(p)), id="status"),
    pytest.param(versioned, "run_versioned", lambda p: [str(p)], lambda p: call(str(p)), id="versioned"),
]

HELP_GATE_MODULES = [pytest.param(*row.values[:3], id=row.id) for row in STANDALONE_ENTRY_MODULES]

#: Real work after the sentinel, neutralised too: 'all' otherwise runs a LIVE run_drive_sync that
#: rewrites the machine's real google_creds.json. Patched on its own module: all imports it inside handle_command.
DOWNSTREAM_AFTER_SENTINEL: dict[ModuleType, tuple[tuple[ModuleType, str], ...]] = {
    all_module: (
        (all_module, "run_versioned"),
        (drive_sync, "run_drive_sync"),
    ),
}


class TestHelpGateInsideHandleCommand:
    """handle_command itself must screen help flags: each module's __main__ entry bypasses the router."""

    @pytest.mark.parametrize(("mod", "sentinel", "build_args"), HELP_GATE_MODULES)
    @pytest.mark.parametrize("flag", ["--help", "-h"])
    def test_trailing_help_flag_does_not_execute(
        self, mod: ModuleType, sentinel: str, build_args, flag: str, tmp_path: Path
    ) -> None:
        """A help flag trailing a module's own real invocation runs nothing."""
        args = [*build_args(tmp_path), flag]

        with patch.object(mod, sentinel) as spy:
            handled = mod.handle_command(mod.PRIMARY_COMMAND, args)

        assert handled is True
        spy.assert_not_called()

    @pytest.mark.parametrize(("mod", "sentinel", "build_args", "build_call"), STANDALONE_ENTRY_MODULES)
    def test_real_invocation_still_dispatches(
        self, mod: ModuleType, sentinel: str, build_args, build_call, tmp_path: Path
    ) -> None:
        """A normal run reaches the sentinel ONCE, with the arguments the row built."""
        args = build_args(tmp_path)

        with ExitStack() as stack:
            spy = stack.enter_context(patch.object(mod, sentinel))
            for target_mod, target_attr in DOWNSTREAM_AFTER_SENTINEL.get(mod, ()):
                stack.enter_context(patch.object(target_mod, target_attr))
            mod.handle_command(mod.PRIMARY_COMMAND, args)

        assert spy.call_args_list == [build_call(tmp_path)], (
            f"{mod.MODULE_NAME} dispatched {sentinel} as {spy.call_args_list}, not {[build_call(tmp_path)]}"
        )


_WATCHED_EVENTS = ("open", "os.mkdir", "os.chmod", "os.rename", "os.replace")


class _SecretsWatch:
    """Audit-hook recorder of touches under root; inert until touched is a list."""

    def __init__(self, root: str) -> None:
        self.root = root
        self.touched: list[str] | None = None

    def hook(self, event: str, args: tuple) -> None:
        """Record any touch of real secret storage while the watch is armed."""
        if self.touched is None or event not in _WATCHED_EVENTS:
            return
        target = os.path.normcase(os.path.realpath(str(args[0]))) if args else ""
        if target.startswith(self.root):
            self.touched.append(f"{event} {target}")


@pytest.fixture(scope="session")
def secrets_audit() -> _SecretsWatch:
    """Install the audit hook once per session; it can never be undone, so every later test carries it inert."""
    watch = _SecretsWatch(os.path.normcase(os.path.realpath(Path.home() / ".secrets")))
    sys.addaudithook(watch.hook)
    return watch


@pytest.fixture
def secrets_watch(secrets_audit: _SecretsWatch) -> Generator[list[str], None, None]:
    """Arm the session's hook for one test and yield the list it records into."""
    secrets_audit.touched = []
    try:
        yield secrets_audit.touched
    finally:
        secrets_audit.touched = None


def _drive_sync_on(project: Path) -> None:
    """Write a project config with drive_sync on, so 'all' reaches its Drive step."""
    (project / ".backup").mkdir()
    (project / ".backup" / "config.json").write_text('{"drive_sync": true}', encoding="utf-8")


class TestNoWriteEscapesToRealSecrets:
    """The 'all' cycle must never reach live credential storage from a test.

    The audit hook RECORDS and does not block: blocking mid-auth pushes Google into its
    interactive browser flow, which hangs forever.
    """

    def test_all_stops_at_the_patched_doubles(self, tmp_path: Path) -> None:
        """Every step of the cycle lands on a double, each with the run's own arguments."""
        # The doubles are compared as a whole map, so a step added to DOWNSTREAM_AFTER_SENTINEL fails here.
        project = str(tmp_path)
        _drive_sync_on(tmp_path)

        with ExitStack() as stack:
            snap = stack.enter_context(patch.object(all_module, "run_snapshot"))
            doubles = {
                target_attr: stack.enter_context(patch.object(target_mod, target_attr))
                for target_mod, target_attr in DOWNSTREAM_AFTER_SENTINEL[all_module]
            }
            all_module.handle_command(all_module.PRIMARY_COMMAND, [project])

        scanned = doubles["run_versioned"].call_args.kwargs["pre_scanned"]
        # Single-scan rule: snapshot gets the very list versioned does, so the tree is walked once.
        assert snap.call_args_list == [call(project, verb=all_module.PRIMARY_COMMAND, pre_scanned=scanned)]
        assert snap.call_args.kwargs["pre_scanned"] is scanned
        assert sorted(doubles) == ["run_drive_sync", "run_versioned"]

        # show_panels comes from the absence of --quiet: True is the claim, not a placeholder.
        assert doubles["run_drive_sync"].call_args_list == [
            call(project, show_panels=True, verb=all_module.PRIMARY_COMMAND)
        ]

        # Single-scan rule: versioned gets the list 'all' walked; the seed .backupignore proves it.
        versioned_call = doubles["run_versioned"].call_args
        assert doubles["run_versioned"].call_count == 1
        assert versioned_call.args == (project,)
        assert (str(tmp_path / ".backupignore"), ".backupignore") in versioned_call.kwargs["pre_scanned"]

    def test_no_write_reaches_real_secret_storage(self, tmp_path: Path, secrets_watch: list[str]) -> None:
        """Running 'all' touches nothing under ~/.secrets."""
        _drive_sync_on(tmp_path)
        with ExitStack() as stack:
            stack.enter_context(patch.object(all_module, "run_snapshot"))
            for target_mod, target_attr in DOWNSTREAM_AFTER_SENTINEL[all_module]:
                stack.enter_context(patch.object(target_mod, target_attr))
            all_module.handle_command(all_module.PRIMARY_COMMAND, [str(tmp_path)])

        assert secrets_watch == [], f"test reached real secret storage: {secrets_watch}"


class TestStubFailsHonestly:
    """A deferred command must say so, not exit 0 in silence: the stub raises NotImplementedError."""

    def test_settings_stub_refuses_and_names_the_reason(self, tmp_path: Path) -> None:
        """The stub raises rather than returning a success the caller believes."""
        with pytest.raises(NotImplementedError) as caught:
            settings.handle_command("settings", [str(tmp_path)])

        assert str(caught.value) == (
            "settings sets one key today, drive_sync on|off <project_path|@name>; "
            "the settings UI is deferred (Phase 3). Edit .backup/config.json in the project directly for anything else."
        )

    def test_settings_stub_leaves_the_run_marked_failed(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """main() turns the raise into exit 1, naming the module and the reason on stderr."""
        # Through the REAL entry point: the exit code and the named failure on stderr are both the claim.
        with patch("sys.argv", ["backup", "settings", str(tmp_path)]):
            code = entry.main()

        assert code == 1
        err = capsys.readouterr().err
        assert "settings failed" in err
        assert "settings sets one key today" in err


class TestRestoreRefusesAMalformedInvocation:
    """A restore invocation that cannot run must fail loudly, not print help and exit 0.

    Exit 2, not 1: 1 is the router's unhandled-command code, and returning False would add a
    second, false "Unknown command: restore" line.
    """

    def test_a_missing_output_path_is_refused_instead_of_exiting_zero(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """`restore <project> file <f>` with no output path printed help and exited 0."""
        with patch("sys.argv", ["backup", "restore", str(tmp_path), "file", "notes.txt"]):
            code = entry.main()

        assert code == 2, f"a restore that never ran exited {code}"

        out, err = capsys.readouterr()
        # On stdout a refusal is indistinguishable from the "Restored X to Y" line a pipe reads for.
        assert "restore <project> file <file> <out>" in err, f"the missing operand was never named on stderr: {err!r}"
        assert "Unknown command" not in err, f"the refusal returned False and drew a second, false line: {err!r}"
        assert "Usage:" not in out, "the malformed invocation still answered with the help page"
        assert f"{restore.MODULE_NAME} Module" not in out, "the malformed invocation still printed the introspection"

    def test_an_unknown_verb_is_refused_on_stderr_instead_of_answered_with_the_help_page(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Any verb but list/file printed the help page on stdout and exited 0."""
        with patch("sys.argv", ["backup", "restore", str(tmp_path), "lsit", "notes.txt"]):
            code = entry.main()

        assert code == 2, f"an unknown verb exited {code}"

        out, err = capsys.readouterr()
        assert "lsit" in err, f"the refusal never named the verb the user typed: {err!r}"
        assert "Unknown command" not in err, f"the refusal returned False and drew a second, false line: {err!r}"
        assert "restore <project> list <file>" not in out, "an unknown verb still answered with the usage page"
        assert f"{restore.MODULE_NAME} Module" not in out, "an unknown verb still printed the introspection"


class TestUnknownCommandNotSwallowed:
    """An unrecognised command must reach the 'Unknown command' error, not display.py's introspection."""

    def test_display_rejects_foreign_command(self, capsys: pytest.CaptureFixture[str]) -> None:
        """display.handle_command declines a command it does not own, printing nothing."""
        assert display.handle_command("wibble", []) is False

        # Printing nothing IS the claim: display's page once reached the operator in place of the error.
        assert capsys.readouterr().out == ""

    def test_display_rejects_foreign_command_with_help_flag(self, capsys: pytest.CaptureFixture[str]) -> None:
        """A help flag does not make display claim someone else's command."""
        assert display.handle_command("wibble", ["--help"]) is False

        assert capsys.readouterr().out == ""

    def test_entry_point_reports_unknown_command(self, capsys: pytest.CaptureFixture[str]) -> None:
        """main() returns exit code 1 for a command no module handles, and names it."""
        fake_module = MagicMock()
        fake_module.handle_command = MagicMock(return_value=False)

        with (
            patch.object(entry, "discover_modules", return_value=[fake_module]),
            patch("sys.argv", ["backup", "wibble"]),
        ):
            assert entry.main() == 1

        assert "Unknown command: wibble" in capsys.readouterr().err


class TestHelpNeverExecutes:
    """A --help anywhere in the args must print help, never run the verb."""

    #: A placeholder each test swaps for tmp_path: the table is read before any fixture exists.
    PROJECT = "<project>"
    HELP_ARGV = [
        ["snapshot", PROJECT, "--help"],
        ["versioned", PROJECT, "-h"],
        ["all", PROJECT, "--help"],
        ["drive_clear", PROJECT, "--force", "--help"],
        ["restore", PROJECT, "file", "a.py", "b.py", "--help"],
    ]

    def test_the_help_sweep_still_covers_every_shape_it_was_built_for(self) -> None:
        """HELP_ARGV keeps its five rows in order, every one ending in a help flag and exactly one in -h."""
        assert len(self.HELP_ARGV) == 5
        # By name, not literal: a sweep dispatching a command no module owns sweeps nothing.
        assert [row[0] for row in self.HELP_ARGV] == [
            snapshot.PRIMARY_COMMAND,
            versioned.PRIMARY_COMMAND,
            all_module.PRIMARY_COMMAND,
            drive_clear.PRIMARY_COMMAND,
            restore.PRIMARY_COMMAND,
        ]
        assert all(row[-1] in ("--help", "-h") for row in self.HELP_ARGV)
        assert sum(1 for row in self.HELP_ARGV if "-h" in row) == 1

    @pytest.mark.parametrize("argv", HELP_ARGV)
    def test_help_after_project_never_runs_the_verb(self, argv: list[str], tmp_path: Path) -> None:
        """A trailing help flag reaches the module as a help request only."""
        argv = [str(tmp_path) if arg == self.PROJECT else arg for arg in argv]
        fake_module = MagicMock()
        fake_module.handle_command = MagicMock(return_value=True)

        with (
            patch.object(entry, "discover_modules", return_value=[fake_module]),
            patch("sys.argv", ["backup"] + argv),
        ):
            exit_code = entry.main()

        assert exit_code == 0
        forwarded = [dispatched.args[1] for dispatched in fake_module.handle_command.call_args_list]
        for passed_args in forwarded:
            assert passed_args == ["--help"], f"verb was dispatched with real args: {passed_args}"

    def test_help_flag_alone_still_prints_help(self) -> None:
        """The plain 'snapshot --help' form keeps working."""
        fake_module = MagicMock()
        fake_module.handle_command = MagicMock(return_value=True)

        with (
            patch.object(entry, "discover_modules", return_value=[fake_module]),
            patch("sys.argv", ["backup", "snapshot", "--help"]),
        ):
            assert entry.main() == 0

        fake_module.handle_command.assert_called_once_with("snapshot", ["--help"])

    def test_real_run_without_help_still_dispatches(self, tmp_path: Path) -> None:
        """Guard does not block a normal run -- args reach the module intact."""
        project = str(tmp_path)
        fake_module = MagicMock()
        fake_module.handle_command = MagicMock(return_value=True)

        with (
            patch.object(entry, "discover_modules", return_value=[fake_module]),
            patch("sys.argv", ["backup", "snapshot", project]),
        ):
            assert entry.main() == 0

        fake_module.handle_command.assert_called_once_with("snapshot", [project])
