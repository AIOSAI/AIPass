# =================== META ====================
# Name: test_cli_routing.py
# Description: Tests for apps/backup.py's command routing and the help gate every apps/modules/ verb carries
# Version: 2.0.2
# Created: 2026-06-12
# Modified: 2026-09-25
# =============================================

"""Tests for apps/backup.py's command routing and the help gate every apps/modules/ verb carries."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that every file in apps/modules/ parses and carries no unused import
# seedgo: no-test-needed(constant) — the literal text of VERSION, MODULE_NAME and each PRIMARY_COMMAND
# seedgo: no-test-needed(stdlib) — importlib's ability to import a module by dotted name, which discover_modules rides

import sys
from collections.abc import Generator
from contextlib import ExitStack
from io import StringIO
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

# The real console writes to sys.stdout and error()/warning() write to
# sys.stderr, so capsys reads both channels with no console built here;
# conftest.py pins the console widths and clears the command-failed flag.
#
# argv is patched as `patch("sys.argv", ...)`, not `patch.object(sys, "argv",
# ...)`: seedgo's stdlib_patch reads only a patch call's first argument, and
# bare `sys` scores as an unsanctioned stdlib patch. main() reads sys.argv
# itself, so argv is the entry point's input.


#: The five modules whose whole job is routing: one command they own, a help
#: gate, an introspection page.
SIMPLE_MODULES = [
    pytest.param(drive_sync, id="drive_sync"),
    pytest.param(drive_check, id="drive_check"),
    pytest.param(drive_stats, id="drive_stats"),
    pytest.param(drive_clear, id="drive_clear"),
    pytest.param(settings, id="settings"),
]

#: The verb each simple module reaches once an argument gets PAST the help
#: gate. The help tests spy it, so a gate that stops screening fails the test
#: instead of doing the work: 'drive_check foo --help' made a live Drive auth
#: call before the gate screened the whole sequence (proven 2026-08-13).
#: settings is absent on purpose -- its post-gate path raises rather than
#: calling a verb, and a test sees that without a spy.
VERB_AFTER_THE_GATE: dict[ModuleType, str] = {
    drive_sync: "run_drive_sync",
    drive_check: "run_drive_check",
    drive_stats: "run_drive_stats",
    drive_clear: "run_drive_clear",
}

#: The line print_help adds that print_introspection does not, per module, so a
#: help test pins the HELP page and not merely "some page". drive_check and
#: settings are absent because their print_help renders the introspection and
#: nothing else -- there is no extra line to pin, and claiming one would lie.
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
        # Every other discover_modules in this file is a patch target: the
        # routing tests below replace it with [fake_module], which is right for
        # a routing test and leaves the discovery itself unrun. The glob, the
        # leading-underscore skip and the handle_command filter are exercised
        # here and nowhere else.
        discovered = entry.discover_modules()

        found = sorted(module.__name__.split(".")[-1] for module in discovered)
        on_disk = sorted(path.stem for path in entry.MODULES_DIR.glob("*.py") if not path.name.startswith("_"))
        assert found == on_disk, f"discovery and apps/modules/ disagree: {found!r} vs {on_disk!r}"
        # Not decoration: MODULES_DIR pointed somewhere empty would make both
        # sides [] and the equality above pass on nothing. These name modules
        # that must be in the list, and the identity check says the walk
        # imported THE module rather than a throwaway twin of it.
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
        # Silence is the other half of the contract, not decoration: route_command
        # asks every discovered module in turn, so a module that prints while
        # declining speaks over the one that owns the command. That is exactly
        # the display.py regression pinned further down this file.
        assert mod.handle_command("nonexistent", []) is False

        out, err = capsys.readouterr()
        assert out == "" and err == "", f"a decline printed: {out!r} / {err!r}"


class TestPrintHelp:
    """The entry point's curated command reference, read on the channel a user reads."""

    def test_print_help_lists_every_verb_in_commands_and_every_flag_in_options(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """print_help lists every verb as a COMMANDS row and every flag as an OPTIONS row."""
        assert callable(entry.print_help)

        entry.print_help()

        out, err = capsys.readouterr()
        assert err == "", f"the help page wrote to stderr: {err!r}"

        # The page is read by block, not by substring over the whole thing:
        # every verb is also spelled in EXAMPLES, so a whole-page match would
        # pass with the COMMANDS row gone.
        commands = _rows(out.split("COMMANDS:", 1)[1].split("OPTIONS:", 1)[0])
        options = _rows(out.split("OPTIONS:", 1)[1].split("EXAMPLES:", 1)[0])

        # The first word of a row is the thing the row is about. Matching that,
        # rather than "appears anywhere in the block", keeps 'snapshot' from
        # being satisfied by the 'all' row's description of its own stages.
        listed_verbs = [row.split()[0] for row in commands]
        for verb in ("snapshot", "versioned", "all", "register", "status", "settings", "restore"):
            assert verb in listed_verbs, f"COMMANDS block has no row for {verb}"

        # modules/all.py runs drive_sync after versioned, so the row must say
        # the verb uploads.
        all_row = next(row for row in commands if row.split()[0] == "all")
        assert "drive" in all_row.lower(), f"'all' row hides its drive stage: {all_row}"

        # Flags live in the verbs, not the router, so the page has to name them,
        # in OPTIONS, where a reader looks for them.
        documented_flags = [row.split()[0] for row in options]
        for flag in ("--name", "--quiet", "--force", "--project", "--note", "--public"):
            assert flag in documented_flags, f"OPTIONS block has no row for {flag}"

    @pytest.mark.parametrize("mod", SIMPLE_MODULES)
    def test_print_introspection_prints_the_page_when_called_directly(
        self, mod: ModuleType, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """print_introspection, called on its own, prints the module's name and command."""
        # A direct call: the routed tests reach the page through handle_command,
        # so a print_introspection hollowed to `pass` while handle_command
        # printed the page inline would leave them green. The module's __main__
        # entry and print_help reach this function without handle_command.
        mod.print_introspection()

        out, err = capsys.readouterr()
        assert f"{mod.MODULE_NAME} Module" in out
        assert f"Primary command: {mod.PRIMARY_COMMAND}" in out
        assert err == "", f"introspection wrote to stderr: {err!r}"


#: (module, sentinel called right after the help gate, args after the project
#: arg, the ONE call that invocation must produce)
#: Each row builds the module's OWN executing invocation from a tmp_path.
#: A builder rather than a shared "<project> plus extras" shape, because the
#: shape is not shared: drive_check takes no project at all, and assuming it
#: did would make a bare tmp_path read as a normal run (see its row).
#:
#: The fourth column is the argument binding: the expected call is built from
#: the same tmp_path as the args, so a wrong operand, a wrong flag value or a
#: hardcoded project root fails the row.
STANDALONE_ENTRY_MODULES = [
    pytest.param(all_module, "run_snapshot", lambda p: [str(p)], lambda p: call(str(p)), id="all"),
    # drive_check is account-wide and takes NO project: "run" is its only
    # executing route, and it reaches run_drive_check with NO arguments. An
    # unrecognised first arg is refused, never executed.
    pytest.param(drive_check, "run_drive_check", lambda p: ["run"], lambda p: call(), id="drive_check"),
    pytest.param(
        drive_clear,
        "run_drive_clear",
        lambda p: [str(p)],
        # force is a FLAG the row never passes, so False is the claim: a
        # tracker deletion that self-confirms is the regression this pins.
        lambda p: call(str(p), force=False),
        id="drive_clear",
    ),
    pytest.param(drive_stats, "run_drive_stats", lambda p: [str(p)], lambda p: call(str(p)), id="drive_stats"),
    pytest.param(
        drive_sync,
        "run_drive_sync",
        lambda p: [str(p)],
        # The empty defaults are what a plain flagless run must hand the verb.
        # With no flags the --note / --project pair-scan never fires, so this
        # row does not pin it.
        lambda p: call(str(p), project_name="", note="", force=False),
        id="drive_sync",
    ),
    pytest.param(register, "resolve_caller_path", lambda p: [str(p)], lambda p: call(str(p)), id="register"),
    pytest.param(
        restore,
        "run_list_versions",
        lambda p: [str(p), "list", "some_file.py"],
        # args[2] is the FILE. args[1] is the verb, and a module that reads it
        # instead looks up a file literally named "list" on every restore.
        lambda p: call(str(p), "some_file.py"),
        id="restore",
    ),
    pytest.param(share, "run_share", lambda p: [str(p)], lambda p: call(str(p), public=False), id="share"),
    pytest.param(snapshot, "run_snapshot", lambda p: [str(p)], lambda p: call(str(p)), id="snapshot"),
    pytest.param(status, "resolve_caller_path", lambda p: [str(p)], lambda p: call(str(p)), id="status"),
    pytest.param(versioned, "run_versioned", lambda p: [str(p)], lambda p: call(str(p)), id="versioned"),
]

#: Real work that runs AFTER the sentinel and must be neutralised too.
#:
#: Patching the sentinel alone is not enough for 'all': handle_command calls
#: run_snapshot, then run_versioned, then a LIVE run_drive_sync. With only
#: run_snapshot spied, the rest of the production pipeline really executed --
#: the Drive step authenticated through @api and refreshed the machine's real
#: ~/.secrets/aipass/google_creds.json (mkdir + chmod 0700 + a write-mode
#: open + chmod 0600 in api/apps/handlers/google/auth.py:261-265). A write-mode
#: open truncates the file as it opens, so a failure mid-write could corrupt
#: live credentials on any machine that ran this suite. Found 2026-08-30 by
#: @seedgo's audit-tests
#: lane -- the only write any branch made outside the audit copy.
#:
#: run_drive_sync is imported INSIDE all.handle_command, so it has to be
#: patched on its OWN module, not as an attribute of 'all' -- which is why the
#: pairs below name the module the attribute lives on.
DOWNSTREAM_AFTER_SENTINEL: dict[ModuleType, tuple[tuple[ModuleType, str], ...]] = {
    all_module: (
        (all_module, "run_versioned"),
        (drive_sync, "run_drive_sync"),
    ),
}


class TestHelpGateInsideHandleCommand:
    """handle_command itself must screen help flags, not just the router.

    Every one of these modules has a standalone entry --
    'if __name__ == "__main__": handle_command(PRIMARY_COMMAND, sys.argv[1:])'
    -- which never touches the router's normalisation. With only a positional
    gate at args[0], 'python modules/snapshot.py <project> --help' ran a REAL
    snapshot (proven live, 2026-08-13). Reported by @seedgo via help_flag_safety.
    """

    @pytest.mark.parametrize(("mod", "sentinel", "build_args", "build_call"), STANDALONE_ENTRY_MODULES)
    @pytest.mark.parametrize("flag", ["--help", "-h"])
    def test_trailing_help_flag_does_not_execute(
        self, mod: ModuleType, sentinel: str, build_args, build_call, flag: str, tmp_path: Path
    ) -> None:
        """A help flag trailing a module's own real invocation runs nothing."""
        # build_call is the dispatch test's column; a help request must produce
        # NO call at all, so it is the one shape this test never expects.
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
        # The expected call comes off the row, so a wrong operand, a wrong flag
        # value or a hardcoded project root fails here.
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
        target = str(args[0]) if args else ""
        if target.startswith(self.root):
            self.touched.append(f"{event} {target}")


@pytest.fixture(scope="session")
def secrets_audit() -> _SecretsWatch:
    """Install the audit hook once per session; sys.addaudithook can never be undone."""
    watch = _SecretsWatch(str(Path.home() / ".secrets"))
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


class TestNoWriteEscapesToRealSecrets:
    """The 'all' cycle must never reach live credential storage from a test.

    Regression, found 2026-08-30 by @seedgo's audit-tests lane -- the only write
    any branch made outside the audit copy. test_real_invocation_still_dispatches
    patched run_snapshot only, so handle_command fell straight through to a REAL
    run_drive_sync, which authenticated through @api and rewrote
    ~/.secrets/aipass/google_creds.json (auth.py:261-265: mkdir, chmod 0700, a
    write-mode open, chmod 0600). That open truncates the file as it opens, so
    a failure mid-write could corrupt the machine's live Google credentials.

    The audit hook here RECORDS and does not block. Blocking mid-auth pushes the
    Google client into its interactive browser flow, which hangs forever -- a pin
    that hangs teaches nobody anything. The cost of recording is that a genuine
    regression writes the real file once before this test goes red; that is the
    status quo it exists to end, not a new risk it introduces.
    """

    def test_all_stops_at_the_patched_doubles(self, tmp_path: Path) -> None:
        """Every step of the cycle lands on a double, each with the run's own arguments."""
        # Each double stands where a real run would have gone, so each is checked
        # against the arguments the real step takes. The doubles are compared by
        # name as a whole map, so a step added to DOWNSTREAM_AFTER_SENTINEL
        # without an expectation here fails.
        project = str(tmp_path)

        with ExitStack() as stack:
            snap = stack.enter_context(patch.object(all_module, "run_snapshot"))
            doubles = {
                target_attr: stack.enter_context(patch.object(target_mod, target_attr))
                for target_mod, target_attr in DOWNSTREAM_AFTER_SENTINEL[all_module]
            }
            all_module.handle_command(all_module.PRIMARY_COMMAND, [project])

        assert snap.call_args_list == [call(project)]
        assert sorted(doubles) == ["run_drive_sync", "run_versioned"]

        # show_panels is derived from the absence of --quiet, and this run has
        # no flags: True is the claim, not a placeholder.
        assert doubles["run_drive_sync"].call_args_list == [call(project, show_panels=True)]

        # The single-scan rule: versioned is handed the list 'all' already
        # walked, never a path to re-walk. The seed .backupignore that
        # create_backup_dir writes is the one entry a bare project is
        # guaranteed to carry, so it is what proves the list came from the
        # shared scan.
        versioned_call = doubles["run_versioned"].call_args
        assert doubles["run_versioned"].call_count == 1
        assert versioned_call.args == (project,)
        assert (str(tmp_path / ".backupignore"), ".backupignore") in versioned_call.kwargs["pre_scanned"]

    def test_no_write_reaches_real_secret_storage(self, tmp_path: Path, secrets_watch: list[str]) -> None:
        """Running 'all' touches nothing under ~/.secrets."""
        touched = secrets_watch
        with ExitStack() as stack:
            stack.enter_context(patch.object(all_module, "run_snapshot"))
            for target_mod, target_attr in DOWNSTREAM_AFTER_SENTINEL[all_module]:
                stack.enter_context(patch.object(target_mod, target_attr))
            all_module.handle_command(all_module.PRIMARY_COMMAND, [str(tmp_path)])

        assert touched == [], f"test reached real secret storage: {touched}"


class TestStubFailsHonestly:
    """A deferred command must say so, not exit 0 in silence.

    Regression: 'backup settings <project>' logged to file, printed nothing and
    returned success, while print_help and the README advertised it as a
    working command.

    Second regression (refusal sweep 2026-09-07): saying so was not enough.
    The stub printed its warning and returned True, so main() exited 0 --
    measured from the shell, 'backup settings <project>' exited 0 before this
    cure and exits 1 after it. The stub now raises NotImplementedError, which
    route_command catches and main reports as a named failure.
    """

    def test_settings_stub_refuses_and_names_the_reason(self, tmp_path: Path) -> None:
        """The stub raises rather than returning a success the caller believes."""
        with pytest.raises(NotImplementedError) as caught:
            settings.handle_command("settings", [str(tmp_path)])

        # The exact sentence the operator gets, not an either/or over two words.
        assert str(caught.value) == (
            "settings is not implemented — the settings UI is deferred (Phase 3). "
            "Edit .backup/config.json in the project directly for now."
        )

    def test_settings_stub_leaves_the_run_marked_failed(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """main() turns the raise into exit 1, naming the module and the reason on stderr."""
        # The whole point of the sweep row: a refusal that exits 0 is a refusal
        # nobody downstream can see. This drives the REAL entry point, so the
        # route_command handler and main's failure branch are both on the path.
        # The exit code alone does not prove the operator was told WHICH module
        # refused -- route_command's `failure` string is what carries that, and
        # error() puts it on stderr, where drone's piping reads it.
        with patch("sys.argv", ["backup", "settings", str(tmp_path)]):
            code = entry.main()

        assert code == 1
        err = capsys.readouterr().err
        assert "settings failed" in err
        assert "settings is not implemented" in err


class TestRestoreRefusesAMalformedInvocation:
    """A restore invocation that cannot run must fail loudly, not print help and exit 0.

    The 2026-09-22 refusal cure covered ONE shape -- `restore <project> list`
    with no filename. The two shapes below fell through to the same
    `print_help(); return True` tail at restore.py:186-187, so
    `restore <project> file notes.txt` (no output path) and any fat-fingered
    verb answered exactly like `restore --help`: the usage page on stdout and
    exit 0. A script reading the code saw success for a restore that never
    happened.

    Both pins drive the REAL entry point, because the exit code is half the
    defect and handle_command alone cannot show it. Exit 2 -- not 1 -- is the
    claim: 1 is what the router returns for a command nobody handled, and
    returning False here would buy the refusal a second, false line
    ("Unknown command: restore") on top of the true one.
    """

    def test_a_missing_output_path_is_refused_instead_of_exiting_zero(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """`restore <project> file <f>` with no output path printed help and exited 0."""
        with patch("sys.argv", ["backup", "restore", str(tmp_path), "file", "notes.txt"]):
            code = entry.main()

        assert code == 2, f"a restore that never ran exited {code}"

        out, err = capsys.readouterr()
        # The channel is the other half: a refusal on stdout is indistinguishable
        # from the "Restored X to Y" line a pipe is reading for.
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
    """An unrecognised command must reach the 'Unknown command' error.

    Regression: display.py is not a command module (its docstring says it
    always returns False), but handle_command returned True for ANY command
    when args were empty. Discovery order put it first, so 'backup wibble'
    printed the display module's introspection and exited 0.
    """

    def test_display_rejects_foreign_command(self, capsys: pytest.CaptureFixture[str]) -> None:
        """display.handle_command declines a command it does not own, printing nothing."""
        assert display.handle_command("wibble", []) is False

        # Printing nothing IS the regression: the bug was not a wrong return
        # value alone, it was this module's introspection page reaching the
        # operator in place of the unknown-command error.
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
    """A --help anywhere in the args must print help, never run the verb.

    Regression guard: main() used to check only the FIRST arg after the
    command, so 'backup snapshot <project> --help' resolved the project and
    ran a real backup instead of printing help.
    """

    #: PROJECT is a placeholder each test swaps for its own tmp_path: the table
    #: is read at class-body time, before any fixture exists.
    PROJECT = "<project>"
    HELP_ARGV = [
        ["snapshot", PROJECT, "--help"],
        ["versioned", PROJECT, "-h"],
        ["all", PROJECT, "--help"],
        ["drive_clear", PROJECT, "--force", "--help"],
        ["restore", PROJECT, "file", "a.py", "b.py", "--help"],
    ]

    def test_the_help_sweep_still_covers_every_shape_it_was_built_for(self) -> None:
        """HELP_ARGV keeps its five help-flag positions: long, short, behind a flag, behind operands."""
        assert len(self.HELP_ARGV) == 5
        # By name, not by literal: a sweep that dispatches a command no module
        # owns sweeps nothing. The row order is the sweep's shape.
        assert [row[0] for row in self.HELP_ARGV] == [
            snapshot.PRIMARY_COMMAND,
            versioned.PRIMARY_COMMAND,
            all_module.PRIMARY_COMMAND,
            drive_clear.PRIMARY_COMMAND,
            restore.PRIMARY_COMMAND,
        ]
        # Every row must actually carry a help flag, or it sweeps nothing.
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


class TestOutputCapture:
    """A buffer and the capture fixture each hand back the text written to them."""

    def test_stringio_capture(self) -> None:
        """A StringIO buffer returns the text written to it."""
        buf = StringIO()
        buf.write("test output")
        assert "test" in buf.getvalue()

    def test_capsys_available(self, capsys: pytest.CaptureFixture[str]) -> None:
        """capsys fixture available for stdout capture."""
        print("hello from backup test")
        captured = capsys.readouterr()
        assert "hello" in captured.out
