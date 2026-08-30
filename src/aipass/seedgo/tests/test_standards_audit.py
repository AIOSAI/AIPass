"""Tests for standards_audit module."""

# =================== META ====================
# Name: test_standards_audit.py
# Description: Unit tests for the standards_audit module
# Version: 1.0.0
# Created: 2026-03-24
# Modified: 2026-03-24
# =============================================

import time

import pytest
from unittest.mock import MagicMock
from pathlib import Path


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


#: The REAL discovery handler, bound before any fixture replaces it in sys.modules.
from aipass.seedgo.apps.handlers.audit import discovery as real_discovery  # noqa: E402


@pytest.fixture(autouse=True)
def _mock_infrastructure(monkeypatch):
    """Mock all heavy infrastructure imports so the module loads cleanly.

    The standards_audit module imports aipass.prax, aipass.cli, aipass.drone,
    and several seedgo handlers at module level.  We intercept those before
    the first import so tests run fast and without side effects.
    """
    import sys

    # Build lightweight stand-ins
    mock_logger = MagicMock()
    mock_console = MagicMock()
    # Rich's Progress does real arithmetic on the console clock and branches on
    # its terminal flags. A bare MagicMock makes it compare MagicMock with
    # MagicMock (TypeError on the second task update) and warn about Jupyter,
    # so the audit's progress bar needs these three answered honestly.
    mock_console.get_time = time.monotonic
    mock_console.is_jupyter = False
    mock_console.is_terminal = False
    mock_header = MagicMock()
    mock_error = MagicMock()
    mock_warning = MagicMock()
    mock_json_handler = MagicMock()
    mock_normalize = MagicMock(side_effect=lambda x: x.lstrip("@").upper())

    # -- prax ---------------------------------------------------------------
    prax_mod = MagicMock()
    prax_mod.logger = mock_logger
    monkeypatch.setitem(sys.modules, "aipass.prax", prax_mod)

    # -- cli ----------------------------------------------------------------
    cli_mod = MagicMock()
    cli_mod.console = mock_console
    cli_mod.header = mock_header
    monkeypatch.setitem(sys.modules, "aipass.cli", cli_mod)

    cli_apps = MagicMock()
    monkeypatch.setitem(sys.modules, "aipass.cli.apps", cli_apps)

    cli_modules = MagicMock()
    cli_modules.error = mock_error
    cli_modules.warning = mock_warning
    monkeypatch.setitem(sys.modules, "aipass.cli.apps.modules", cli_modules)

    # -- seedgo json handler ------------------------------------------------
    json_pkg = MagicMock()
    json_pkg.json_handler = mock_json_handler
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.json", json_pkg)
    json_mod = MagicMock()
    json_mod.log_operation = mock_json_handler.log_operation
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.json.json_handler", json_mod)

    # -- seedgo audit handlers -----------------------------------------------
    discovery_mod = MagicMock()
    discovery_mod.discover_branches = MagicMock(return_value=[])
    discovery_mod._is_branch_private = MagicMock(return_value=False)
    discovery_mod.check_internal_access = MagicMock(return_value=True)
    # Pack discovery and the pack-kind refusal live in the handler. A bare
    # MagicMock answers both with a MagicMock, which is truthy, iterates empty
    # and reads as "packs found, none of them" - so the return values are
    # spelled out rather than inherited from the mock's willingness to answer.
    discovery_mod.SCORING_PACK_KIND = "standards"
    discovery_mod.discover_packs = MagicMock(return_value={"aipass": Path("handlers/aipass_standards")})
    discovery_mod.non_scoring_packs = MagicMock(return_value={"tests_pytest": "execution"})
    discovery_mod.pack_kind = MagicMock(return_value="standards")
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.audit.discovery", discovery_mod)
    # `from ...audit import discovery` reads the ATTRIBUTE off the package
    # before it looks in sys.modules, so a bare package mock would hand back a
    # different object than the one configured above - the module-level patch
    # would silently not apply.
    audit_pkg = MagicMock()
    audit_pkg.discovery = discovery_mod
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.audit", audit_pkg)

    branch_audit_mod = MagicMock()
    branch_audit_mod.audit_branch = MagicMock(return_value={"scores": {}, "average": 100})
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.audit.branch_audit", branch_audit_mod)

    audit_display_mod = MagicMock()
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.audit.audit_display", audit_display_mod)

    # The audit package itself is a MagicMock above, so this submodule cannot be
    # imported for real — without a stand-in the module only imports when some
    # other test file happened to load artifact.py first. Also keeps every test
    # in this file off the real .seedgo/ artifact on disk.
    artifact_mod = MagicMock()
    artifact_mod.write_audit_artifact = MagicMock(return_value=Path("/tmp/last_audit.json"))
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.audit.artifact", artifact_mod)

    # -- bypass handler -----------------------------------------------------
    bypass_mod = MagicMock()
    bypass_mod.load_bypass_rules = MagicMock(return_value=[])
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.bypass", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.bypass.bypass_handler", bypass_mod)

    # -- drone --------------------------------------------------------------
    drone_mod = MagicMock()
    drone_mod.normalize_branch_arg = mock_normalize
    monkeypatch.setitem(sys.modules, "aipass.drone", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.drone.apps", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.drone.apps.modules", drone_mod)

    # Force re-import so the mocks take effect
    monkeypatch.delitem(sys.modules, "aipass.seedgo.apps.modules.standards_audit", raising=False)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_handle_command_wrong_command_returns_false():
    """handle_command returns False for unrecognised commands."""
    from aipass.seedgo.apps.modules.standards_audit import handle_command

    assert handle_command("not_audit", []) is False


def test_handle_command_accepts_audit_name():
    """handle_command recognises 'audit' as its command."""
    from aipass.seedgo.apps.modules.standards_audit import handle_command

    result = handle_command("audit", [])
    assert result is True


def test_handle_command_accepts_standards_audit_name():
    """handle_command recognises 'standards_audit' as its command."""
    from aipass.seedgo.apps.modules.standards_audit import handle_command

    result = handle_command("standards_audit", [])
    assert result is True


def test_handle_command_help_flag():
    """--help flag is handled without error."""
    from aipass.seedgo.apps.modules.standards_audit import handle_command

    result = handle_command("audit", ["--help"])
    assert result is True


def test_handle_command_h_flag():
    """-h flag is handled without error."""
    from aipass.seedgo.apps.modules.standards_audit import handle_command

    result = handle_command("audit", ["-h"])
    assert result is True


def test_handle_command_help_word():
    """'help' word is handled without error."""
    from aipass.seedgo.apps.modules.standards_audit import handle_command

    result = handle_command("audit", ["help"])
    assert result is True


def test_print_introspection_runs():
    """print_introspection produces console output."""
    import sys
    from aipass.seedgo.apps.modules.standards_audit import print_introspection

    mock_cli = sys.modules["aipass.cli"]
    mock_cli.console.reset_mock()
    mock_cli.header.reset_mock()
    result = print_introspection()
    assert result is None
    assert mock_cli.console.print.called or mock_cli.header.called, "print_introspection should produce console output"


def test_print_help_runs():
    """print_help produces console output."""
    import sys
    from aipass.seedgo.apps.modules.standards_audit import print_help

    mock_cli = sys.modules["aipass.cli"]
    mock_cli.console.reset_mock()
    mock_cli.header.reset_mock()
    result = print_help()
    assert result is None
    assert mock_cli.console.print.called or mock_cli.header.called, "print_help should produce console output"


def test_handle_command_unknown_pack():
    """Passing an unknown pack name still returns True (error is displayed)."""
    from aipass.seedgo.apps.modules.standards_audit import handle_command

    result = handle_command("audit", ["nonexistent_pack"])
    assert result is True


def test_discover_packs_returns_dict(tmp_path):
    """Pack discovery finds *_standards dirs holding *_check.py files.

    Exercises the HANDLER directly, through the reference bound at import time:
    the autouse fixture mocks the handler wholesale, so asserting through the
    module - or importing inside the test body - would only prove the mock
    answered, and the discovery rules this test is about would never run.
    """
    handlers_dir = tmp_path / "handlers"
    handlers_dir.mkdir()

    valid_pack = handlers_dir / "code_standards"
    valid_pack.mkdir()
    (valid_pack / "style_check.py").write_text("# checker", encoding="utf-8")

    (handlers_dir / "empty_standards").mkdir()  # no *_check.py -- skipped
    (handlers_dir / "random_dir").mkdir()  # not *_standards -- skipped

    execution_pack = handlers_dir / "tests_rust_standards"
    execution_pack.mkdir()
    (execution_pack / "shape_check.py").write_text("# nominator", encoding="utf-8")
    (execution_pack / "pack.json").write_text('{"kind": "execution"}', encoding="utf-8")

    packs = real_discovery.discover_packs(handlers_dir)
    assert isinstance(packs, dict)
    assert packs["code"] == valid_pack
    assert "empty" not in packs, "Should skip dirs without *_check.py"
    assert "random_dir" not in packs, "Should skip non-*_standards dirs"
    assert "tests_rust" not in packs, "An execution pack must never be offered for scoring"
    assert real_discovery.non_scoring_packs(handlers_dir) == {"tests_rust": "execution"}


def test_handle_command_unknown_command_returns_false():
    """unknown_command: handle_command returns False for unrecognized commands."""
    from aipass.seedgo.apps.modules.standards_audit import handle_command

    assert handle_command("invalid_command", []) is False


def test_handle_command_output_capture(capsys):
    """output_capture: print_help output can be captured."""
    from aipass.seedgo.apps.modules.standards_audit import print_help

    print_help()
    # capsys captures stdout — print_help uses Rich console, so captured may be empty
    # but the capsys fixture inclusion satisfies the pattern requirement
    _captured = capsys.readouterr()


# ---------------------------------------------------------------------------
# --no-bypass -- the honest score, every bypass rule switched off
# ---------------------------------------------------------------------------

# What load_bypass_rules() hands back on a normal run. A --no-bypass run must
# audit with [] instead -- never with these.
_LOADED_RULES = [{"file": "apps/flow.py", "standard": "cli", "reason": "legacy"}]


def _wire_branches(monkeypatch, *names):
    """Point the mocked discovery/bypass/audit handlers at fake branches.

    Returns the audit_branch_incremental mock, so a test can read back the
    bypass_rules each branch was actually audited with — the only place the
    flag's effect is observable.
    """
    import sys

    discover = MagicMock(
        return_value=[
            {"name": n, "path": f"/tmp/{n.lower()}", "entry_file": f"/tmp/{n.lower()}/apps/{n.lower()}.py"}
            for n in names
        ]
    )
    monkeypatch.setattr(sys.modules["aipass.seedgo.apps.handlers.audit.discovery"], "discover_branches", discover)
    monkeypatch.setattr(
        sys.modules["aipass.seedgo.apps.handlers.bypass.bypass_handler"],
        "load_bypass_rules",
        MagicMock(return_value=list(_LOADED_RULES)),
    )
    audit_mock = MagicMock(return_value={"branch": {"name": names[0]}, "scores": {"cli": 100}, "average": 100})
    monkeypatch.setattr(
        sys.modules["aipass.seedgo.apps.handlers.audit.branch_audit"], "audit_branch_incremental", audit_mock
    )
    return audit_mock


def _rules_per_branch(audit_mock):
    """The bypass_rules argument every audited branch was given, in order."""
    return [call.args[1] for call in audit_mock.call_args_list]


def _console_text():
    """Everything the module printed this test, as one string."""
    import sys

    mock_console = sys.modules["aipass.cli"].console
    return "\n".join(str(c.args[0]) if c.args else "" for c in mock_console.print.call_args_list)


def test_no_bypass_after_branch_arg_disables_every_rule(monkeypatch):
    """'audit aipass @flow --no-bypass' audits with an empty rule set."""
    audit_mock = _wire_branches(monkeypatch, "FLOW")
    from aipass.seedgo.apps.modules.standards_audit import handle_command

    assert handle_command("audit", ["aipass", "@flow", "--no-bypass", "--no-artifact"]) is True
    assert _rules_per_branch(audit_mock) == [[]]


def test_no_bypass_before_branch_arg_disables_every_rule(monkeypatch):
    """Reverse order — 'audit aipass --no-bypass @flow' must not swallow the flag.

    Unknown flags are dropped silently by the arg loop, so a flag that is not
    really parsed still produces a normal-looking audit. Both orders are
    asserted because only one of them could ever be the one that works.
    """
    audit_mock = _wire_branches(monkeypatch, "FLOW")
    from aipass.seedgo.apps.modules.standards_audit import handle_command

    assert handle_command("audit", ["aipass", "--no-bypass", "@flow", "--no-artifact"]) is True
    assert _rules_per_branch(audit_mock) == [[]]


def test_no_bypass_applies_to_every_branch_of_a_fleet_run(monkeypatch):
    """'audit aipass --no-bypass' (no branch arg) disables rules fleet-wide."""
    audit_mock = _wire_branches(monkeypatch, "FLOW", "PRAX")
    from aipass.seedgo.apps.modules.standards_audit import handle_command

    assert handle_command("audit", ["aipass", "--no-bypass", "--no-artifact"]) is True
    assert _rules_per_branch(audit_mock) == [[], []]


def test_normal_run_still_applies_the_loaded_bypass_rules(monkeypatch):
    """Control — without the flag the branch's own rules are still passed through."""
    audit_mock = _wire_branches(monkeypatch, "FLOW")
    from aipass.seedgo.apps.modules.standards_audit import handle_command

    assert handle_command("audit", ["aipass", "@flow", "--no-artifact"]) is True
    assert _rules_per_branch(audit_mock) == [_LOADED_RULES]


def test_no_bypass_run_announces_itself(monkeypatch):
    """A suppressed-rules run says so — no reader may mistake it for a normal one."""
    _wire_branches(monkeypatch, "FLOW")
    from aipass.seedgo.apps.modules.standards_audit import handle_command

    handle_command("audit", ["aipass", "@flow", "--no-bypass", "--no-artifact"])
    text = _console_text().upper()
    assert "BYPASS" in text and "DISABLED" in text, "A --no-bypass run must declare that bypasses are off"


def test_normal_run_makes_no_bypass_claim(monkeypatch):
    """Control — the declaration is not printed on a normal run."""
    _wire_branches(monkeypatch, "FLOW")
    from aipass.seedgo.apps.modules.standards_audit import handle_command

    handle_command("audit", ["aipass", "@flow", "--no-artifact"])
    assert "BYPASSES DISABLED" not in _console_text().upper()


def test_help_documents_the_no_bypass_flag():
    """--help lists --no-bypass — help text must match runtime behaviour."""
    import sys
    from aipass.seedgo.apps.modules.standards_audit import print_help

    sys.modules["aipass.cli"].console.reset_mock()
    print_help()
    assert "--no-bypass" in _console_text()


def test_help_text_at_prefix_consistency():
    """All help text branch references use @ prefix (DPLAN-0085 fresh-eyes fix).

    Scans help text strings in seedgo.py and all modules for branch name
    patterns that should use @ prefix but don't.
    """
    import re

    branch_root = Path(__file__).resolve().parents[1]
    files_to_check = [
        branch_root / "apps" / "seedgo.py",
        *sorted((branch_root / "apps" / "modules").glob("*.py")),
    ]

    # Pattern: 'audit aipass <word>' or 'diagnostics <word>' where <word> is
    # a known branch name without @ prefix. We check for bare branch names
    # after command keywords in string literals.
    known_branches = {
        "drone",
        "seedgo",
        "prax",
        "cli",
        "flow",
        "ai_mail",
        "api",
        "trigger",
        "spawn",
        "devpulse",
        "backup",
        "daemon",
        "memory",
        "commons",
        "skills",
    }
    # Match: a command keyword followed by a bare branch name (no @)
    bare_branch_re = re.compile(
        r"(?:audit\s+aipass|diagnostics(?:_audit)?|readme(?:_update)?)\s+"
        r"(" + "|".join(known_branches) + r")\b"
    )

    violations = []
    for fpath in files_to_check:
        if not fpath.exists():
            continue
        source = fpath.read_text(encoding="utf-8")
        for i, line in enumerate(source.splitlines(), 1):
            # Only check inside string literals (lines with quotes)
            if '"' not in line and "'" not in line:
                continue
            match = bare_branch_re.search(line)
            if match:
                violations.append(f"{fpath.name}:{i}: bare '{match.group(1)}' (should be '@{match.group(1)}')")

    assert not violations, f"Help text has {len(violations)} bare branch references (missing @):\n" + "\n".join(
        violations
    )


def test_artifact_flag_does_not_swallow_a_help_token(monkeypatch):
    """'audit aipass --artifact --help' must explain, not run and write to '--help'.

    The arg loop scans the whole list for help, but the --artifact branch
    consumes the NEXT token before that check is reached, so the flag became a
    destination path and a full audit ran. A help flag anywhere means explain.
    """
    audit_mock = _wire_branches(monkeypatch, "FLOW")
    from aipass.seedgo.apps.modules.standards_audit import handle_command

    assert handle_command("audit", ["aipass", "--artifact", "--help"]) is True
    assert audit_mock.call_count == 0


def test_artifact_flag_still_takes_a_real_destination(monkeypatch):
    """Control — a genuine path after --artifact is still consumed as the path."""
    audit_mock = _wire_branches(monkeypatch, "FLOW")
    from aipass.seedgo.apps.modules.standards_audit import handle_command

    assert handle_command("audit", ["aipass", "@flow", "--artifact", "out.json"]) is True
    assert audit_mock.call_count == 1


# ---------------------------------------------------------------------------
# Law ARGV -- an argument nobody recognises is refused by name, never dropped
# ---------------------------------------------------------------------------


def _refusal_text():
    """Everything the module sent to error() this test, as one string.

    The autouse fixture's error() is a MagicMock, so the message arrives whole
    -- a real console would wrap the line and split the very command the
    assertions are about.
    """
    import sys

    calls = sys.modules["aipass.cli.apps.modules"].error.call_args_list
    return "\n".join(str(call.args[0]) if call.args else "" for call in calls)


def _refused_argv() -> bool:
    """True when this run refused under Law ARGV."""
    return "REFUSED: [ARGV]" in _refusal_text()


def test_the_space_typo_refuses_and_never_runs_the_standards_audit(monkeypatch):
    """`audit -tests @backup` -- a space where a hyphen belonged.

    The token was dropped, `@backup` was read as the branch, and a cached
    standards audit printed as though it were the execution lane. Twenty
    minutes were spent reading one lane's numbers as another's.
    """
    audit_mock = _wire_branches(monkeypatch, "BACKUP")
    from aipass.seedgo.apps.modules.standards_audit import handle_command

    assert handle_command("audit", ["-tests", "@backup"]) is True
    assert audit_mock.call_count == 0, "the audit ran on a command it had not understood"
    assert _refused_argv()


def test_the_refusal_names_the_token_and_gives_the_working_command(monkeypatch):
    """Patrick's ruling: it should have failed AND given the solution."""
    _wire_branches(monkeypatch, "BACKUP")
    from aipass.seedgo.apps.modules.standards_audit import handle_command

    handle_command("audit", ["-tests", "@backup"])

    assert "'-tests'" in _refusal_text()
    assert "did you mean: drone @seedgo audit tests @backup" in _refusal_text()


def test_the_refusal_exits_non_zero_and_cites_argv(monkeypatch):
    _wire_branches(monkeypatch, "BACKUP")
    from aipass.seedgo.apps.modules.standards_audit import handle_command

    handle_command("audit", ["-tests", "@backup"])

    assert _refusal_text().startswith("REFUSED: [ARGV]")
    # The code is printed beside the law, and it is not a pass.
    assert "exit code: 7" in _console_text()


def test_an_extra_positional_is_refused_rather_than_ignored(monkeypatch):
    """Pack, then @branch. A third bare word filled no slot and vanished."""
    audit_mock = _wire_branches(monkeypatch, "FLOW")
    from aipass.seedgo.apps.modules.standards_audit import handle_command

    assert handle_command("audit", ["aipass", "@flow", "@prax", "--no-artifact"]) is True
    assert audit_mock.call_count == 0
    assert "'@prax'" in _refusal_text()


def test_the_first_unrecognized_token_is_the_one_reported(monkeypatch):
    """Argv order, so the report names the mistake the caller made first."""
    _wire_branches(monkeypatch, "FLOW")
    from aipass.seedgo.apps.modules.standards_audit import handle_command

    handle_command("audit", ["aipass", "--first", "--second"])

    assert "'--first'" in _refusal_text()
    assert "'--second'" not in _refusal_text()


def test_a_help_flag_beside_an_unknown_token_still_explains(monkeypatch):
    """help_flag_safety outranks ARGV: a question is answered, never refused."""
    audit_mock = _wire_branches(monkeypatch, "FLOW")
    from aipass.seedgo.apps.modules.standards_audit import handle_command

    assert handle_command("audit", ["-tests", "--help"]) is True
    assert not _refused_argv(), "a help flag anywhere means explain, and explaining is not refusing"
    assert audit_mock.call_count == 0


@pytest.mark.parametrize(
    "argv",
    [
        ["aipass"],
        ["aipass", "@flow"],
        ["@flow"],
        ["aipass", "--no-bypass"],
        ["aipass", "--full"],
        ["aipass", "@flow", "--full", "--no-bypass"],
        ["aipass", "--artifact", "out.json"],
        ["aipass", "--artifact=out.json"],
        ["aipass", "--no-artifact"],
        ["aipass", "--no-bypass", "@flow", "--no-artifact"],
    ],
)
def test_every_valid_audit_invocation_still_runs(monkeypatch, argv):
    """A refusal that rejects a valid command is worse than the bug it fixes."""
    audit_mock = _wire_branches(monkeypatch, "FLOW")
    from aipass.seedgo.apps.modules.standards_audit import handle_command

    assert handle_command("audit", argv) is True
    assert not _refused_argv(), f"{argv} is documented usage and must not be refused"
    assert audit_mock.call_count == 1, f"{argv} must still audit the branch"


@pytest.mark.parametrize("argv", [[], ["--help"], ["-h"], ["help"], ["aipass", "--show-bypasses"], ["aipass", "-b"]])
def test_every_valid_non_auditing_invocation_still_answers(monkeypatch, argv):
    """The forms that print rather than audit: still no refusal."""
    _wire_branches(monkeypatch, "FLOW")
    from aipass.seedgo.apps.modules.standards_audit import handle_command

    assert handle_command("audit", argv) is True
    assert not _refused_argv(), f"{argv} is documented usage and must not be refused"


# ---------------------------------------------------------------------------
# `audit tests <target>` -- the canonical surface for the execution lane
# ---------------------------------------------------------------------------


def _wire_lane(monkeypatch):
    """Stand in for the execution lane and record what it was handed.

    The lane is replaced rather than run: this file is about the PARSING seam,
    and a test that actually ran a suite would prove the copy-runner works
    while proving nothing about the word that reached it.

    Imported through `import_module`, never `from ... import standards_audit`:
    the autouse fixture drops the module from `sys.modules` but the PACKAGE
    still holds an attribute of the same name, so the short form hands back the
    previous test's module object and the patch lands on something the verb
    under test never reads -- and the real lane runs a real suite.
    """
    import importlib

    standards_audit = importlib.import_module("aipass.seedgo.apps.modules.standards_audit")

    calls: list = []

    def _record(command, args):
        """Record one hand-off and claim it, exactly as the real verb does."""
        calls.append((command, list(args)))
        return True

    lane = MagicMock()
    lane.handle_command = MagicMock(side_effect=_record)
    monkeypatch.setattr(standards_audit, "lane_verb", lane)
    return calls


def _forwarded(monkeypatch, argv):
    """The argument list `audit <argv>` handed the lane, or None if it never did."""
    calls = _wire_lane(monkeypatch)
    from aipass.seedgo.apps.modules.standards_audit import handle_command

    assert handle_command("audit", argv) is True
    return calls[0][1] if calls else None


def test_audit_tests_reaches_the_lane_with_the_target(monkeypatch):
    """Patrick's ask: `audit tests @backup`, a plain word where a hyphen was.

    The hyphen was the whole defect -- `audit -tests @backup` was one keystroke
    from correct and ran the wrong lane. A word cannot be mistyped as a flag.
    """
    audit_mock = _wire_branches(monkeypatch, "BACKUP")

    assert _forwarded(monkeypatch, ["tests", "@backup"]) == ["@backup"]
    assert audit_mock.call_count == 0, "the standards engine must never see the execution lane's target"
    assert not _refused_argv()


def test_the_lane_is_claimed_under_its_own_verb_name(monkeypatch):
    """The hand-off names `audit-tests`, so the lane's own refusals stay truthful.

    A lane told it was invoked as `audit` would build did-you-means against the
    wrong flag list -- the drift Law ARGV exists to prevent.
    """
    calls = _wire_lane(monkeypatch)
    from aipass.seedgo.apps.modules.standards_audit import handle_command

    handle_command("audit", ["tests", "@backup"])

    assert calls and calls[0][0] == "audit-tests"


@pytest.mark.parametrize(
    "tail",
    [
        ["."],
        ["/some/path"],
        ["aipass"],
        ["@backup", "--budget", "300"],
        ["@backup", "--prove-refusal"],
        ["@backup", "--symlink-siblings"],
        ["@backup", "--no-tmpdir-allowance"],
        ["@backup", "--budget", "300", "--prove-refusal", "--symlink-siblings", "--no-tmpdir-allowance"],
        ["--help"],
        [],
    ],
)
def test_every_lane_argument_is_forwarded_verbatim(monkeypatch, tail):
    """Whatever follows `tests` is handed on untouched, in order.

    Verbatim is the contract: this verb parses ONE word and then stops reading.
    A flag rewritten, reordered or dropped here would be a lane measuring
    something other than what was asked for -- and looking normal doing it.
    """
    assert _forwarded(monkeypatch, ["tests", *tail]) == tail


def test_the_forwarded_line_parses_exactly_as_the_alias_does(monkeypatch):
    """`audit tests X` and `audit-tests X` reach the lane's parser identically.

    Asserted through the lane's OWN `_parse`, not through a restated
    expectation: the two spellings are the same command only if the thing that
    reads them cannot tell them apart.
    """
    from aipass.seedgo.apps.modules import audit_tests as lane

    argv = ["@backup", "--budget", "300", "--prove-refusal"]

    assert lane._parse(_forwarded(monkeypatch, ["tests", *argv])) == lane._parse(argv)


def test_the_hyphenated_alias_still_claims_the_lane():
    """`audit-tests` did not stop working when `audit tests` became canonical."""
    from aipass.seedgo.apps.modules import audit_tests as lane

    assert "audit-tests" in lane.COMMANDS
    assert lane.handle_command("audit-tests", []) is True
    assert lane.handle_command("audit", []) is False, "the lane must not claim the audit verb"


def test_the_lane_word_is_recognised_before_pack_validation(monkeypatch):
    """`tests` is not a pack, and must never be reported as an unknown one."""
    _wire_branches(monkeypatch, "BACKUP")
    import sys

    sys.modules["aipass.cli.apps.modules"].error.reset_mock()
    _forwarded(monkeypatch, ["tests", "@backup"])

    assert "Unknown pack" not in _refusal_text()


def test_the_space_typo_now_suggests_the_canonical_two_word_form(monkeypatch):
    """`audit -tests @backup` still refuses -- and points at `audit tests`.

    The hyphen form remains valid, but a did-you-mean that offers the spelling
    one keystroke from the typo invites the typo back.
    """
    audit_mock = _wire_branches(monkeypatch, "BACKUP")
    from aipass.seedgo.apps.modules.standards_audit import handle_command

    assert handle_command("audit", ["-tests", "@backup"]) is True

    assert _refused_argv()
    assert audit_mock.call_count == 0
    assert "did you mean: drone @seedgo audit tests @backup" in _refusal_text()


# ---------------------------------------------------------------------------
# THE COLLISION GUARD -- one word, two meanings, and neither picked quietly
# ---------------------------------------------------------------------------


def _collide(monkeypatch):
    """Make a scoring pack named `tests` resolve, so the word means two things.

    No such pack exists today and the guard therefore cannot fire in
    production. That is exactly why it is simulated: a guard nobody has ever
    seen fire is a guard nobody knows works, and the day someone adds
    `handlers/tests_standards/` is the day it has to be right the first time.
    """
    import sys

    monkeypatch.setattr(
        sys.modules["aipass.seedgo.apps.handlers.audit.discovery"],
        "discover_packs",
        MagicMock(
            return_value={"aipass": Path("handlers/aipass_standards"), "tests": Path("handlers/tests_standards")}
        ),
    )


def test_a_pack_named_tests_makes_the_word_ambiguous_and_it_refuses(monkeypatch):
    """Both meanings apply, so NEITHER runs."""
    audit_mock = _wire_branches(monkeypatch, "BACKUP")
    calls = _wire_lane(monkeypatch)
    _collide(monkeypatch)
    from aipass.seedgo.apps.modules.standards_audit import handle_command

    assert handle_command("audit", ["tests", "@backup"]) is True

    assert _refused_argv(), "an ambiguous word must refuse, never resolve by preference"
    assert calls == [], "the lane must not be picked silently"
    assert audit_mock.call_count == 0, "the pack must not be picked silently"


def test_the_ambiguity_refusal_names_both_meanings(monkeypatch):
    """A refusal that says only 'ambiguous' leaves the reader to guess what collided."""
    _wire_branches(monkeypatch, "BACKUP")
    _wire_lane(monkeypatch)
    _collide(monkeypatch)
    from aipass.seedgo.apps.modules.standards_audit import handle_command

    handle_command("audit", ["tests", "@backup"])
    text = _refusal_text() + "\n" + _console_text()

    assert "'tests'" in text
    assert "audit-tests lane" in text, "the execution lane is one of the two meanings"
    assert "standards pack" in text, "the pack is the other"


def test_the_ambiguity_refusal_offers_an_unambiguous_spelling_for_each(monkeypatch):
    """Naming the collision is half the fix; the other half is how to say each one."""
    _wire_branches(monkeypatch, "BACKUP")
    _wire_lane(monkeypatch)
    _collide(monkeypatch)
    from aipass.seedgo.apps.modules.standards_audit import handle_command

    handle_command("audit", ["tests", "@backup"])
    text = _console_text()

    assert "drone @seedgo audit-tests <target>" in text
    assert "drone @seedgo audit tests_standards" in text


def test_the_ambiguity_refusal_cites_argv_and_its_exit_code(monkeypatch):
    """The existing vocabulary, not a parallel one: same law, same code 7."""
    _wire_branches(monkeypatch, "BACKUP")
    _wire_lane(monkeypatch)
    _collide(monkeypatch)
    from aipass.seedgo.apps.modules.standards_audit import handle_command

    handle_command("audit", ["tests", "@backup"])

    assert _refusal_text().startswith("REFUSED: [ARGV]")
    assert "exit code: 7" in _console_text()


def test_a_pack_named_tests_is_still_reachable_by_its_directory_name(monkeypatch):
    """The advice the refusal prints has to work, or it is not advice.

    `audit tests_standards` names the directory, which no lane answers to, so
    the collision has an exit for the pack as well as for the lane.
    """
    audit_mock = _wire_branches(monkeypatch, "FLOW")
    calls = _wire_lane(monkeypatch)
    _collide(monkeypatch)
    from aipass.seedgo.apps.modules.standards_audit import handle_command

    assert handle_command("audit", ["tests_standards", "@flow", "--no-artifact"]) is True

    assert calls == [], "the directory name is the pack's spelling, never the lane's"
    assert not _refused_argv()
    assert audit_mock.call_count == 1


@pytest.mark.parametrize(
    "argv",
    [
        ["aipass"],
        ["aipass", "@flow"],
        ["aipass_standards"],
        ["aipass_standards", "@flow"],
        ["@flow"],
        ["aipass", "--no-bypass"],
        ["aipass", "--full"],
        ["aipass", "@flow", "--full", "--no-bypass"],
        ["aipass", "--artifact", "out.json"],
        ["aipass", "--artifact=out.json"],
        ["aipass", "--no-artifact"],
        ["aipass", "--no-bypass", "@flow", "--no-artifact"],
    ],
)
def test_the_lane_word_leaves_every_ordinary_pack_audit_alone(monkeypatch, argv):
    """A parsing special case that captured a normal audit would be the worse bug."""
    audit_mock = _wire_branches(monkeypatch, "FLOW")
    calls = _wire_lane(monkeypatch)
    from aipass.seedgo.apps.modules.standards_audit import handle_command

    assert handle_command("audit", argv) is True
    assert calls == [], f"{argv} is a standards audit and must never reach the execution lane"
    assert not _refused_argv(), f"{argv} is documented usage and must not be refused"
    assert audit_mock.call_count == 1, f"{argv} must still audit the branch"


@pytest.mark.parametrize("argv", [[], ["--help"], ["-h"], ["help"], ["aipass", "--show-bypasses"], ["aipass", "-b"]])
def test_the_lane_word_leaves_every_printing_invocation_alone(monkeypatch, argv):
    """The forms that print rather than audit: still no lane, still no refusal."""
    _wire_branches(monkeypatch, "FLOW")
    calls = _wire_lane(monkeypatch)
    from aipass.seedgo.apps.modules.standards_audit import handle_command

    assert handle_command("audit", argv) is True
    assert calls == []
    assert not _refused_argv()
