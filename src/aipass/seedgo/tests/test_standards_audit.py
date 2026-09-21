"""Tests for standards_audit module."""

# =================== META ====================
# Name: test_standards_audit.py
# Description: Unit tests for the standards_audit module and the seedgo-audit CI gate
# Version: 1.2.0
# Created: 2026-03-24
# Modified: 2026-09-15
# =============================================

import time

import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


#: The REAL discovery handler, bound before any fixture replaces it in sys.modules.
from aipass.seedgo.apps.handlers.audit import discovery as real_discovery  # noqa: E402

#: The REAL argv parser, bound the same way and for the opposite reason: it is
#: pure grammar with no infrastructure to mock away, and a MagicMock in its
#: place answers `wants_help` truthily — every audit in this file then prints
#: help and audits nothing, which is exactly what happened when the parser was
#: first split out of the module (2026-09-07).
from aipass.seedgo.apps.handlers.audit import argv as real_argv  # noqa: E402


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
    audit_pkg.argv = real_argv
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

    yield

    # The re-import under mocks minted a NEW module object, and the import
    # system hung it on the parent package as an attribute. monkeypatch
    # restores sys.modules but never recorded that attribute — and records
    # nothing at all when the module had never been imported before this
    # file ran — so the mock-bound corpse outlives the test, and
    # `from ... import standards_audit` in ANOTHER test file hands it back:
    # its console is a MagicMock that prints nowhere (the CI 3.12/gw1 flake
    # where capsys read ''). Scrub both homes here; monkeypatch's own undo
    # then restores the real module wherever one was recorded, and the next
    # from-import rebinds the package attribute to the real thing.
    sys.modules.pop("aipass.seedgo.apps.modules.standards_audit", None)
    _parent = sys.modules.get("aipass.seedgo.apps.modules")
    if _parent is not None and hasattr(_parent, "standards_audit"):
        delattr(_parent, "standards_audit")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_handle_command_wrong_command_returns_false():
    """handle_command returns False for unrecognised commands."""
    from aipass.seedgo.apps.modules.standards_audit import handle_command

    assert handle_command("not_audit", []) is False


def test_handle_command_accepts_audit_name():
    """'audit' reaches this module's own introspection, not just a True."""
    from aipass.seedgo.apps.modules import standards_audit

    with patch.object(standards_audit, "_show_audit_introspection") as shown:
        assert standards_audit.handle_command("audit", []) is True
    shown.assert_called_once_with()


def test_handle_command_accepts_standards_audit_name():
    """'standards_audit' is the same door, not a near miss returning True."""
    from aipass.seedgo.apps.modules import standards_audit

    with patch.object(standards_audit, "_show_audit_introspection") as shown:
        assert standards_audit.handle_command("standards_audit", []) is True
    shown.assert_called_once_with()


def test_handle_command_help_flag():
    """--help explains and audits no branch."""
    from aipass.seedgo.apps.modules import standards_audit

    with (
        patch.object(standards_audit, "print_help") as helped,
        patch.object(standards_audit, "audit_branch_incremental") as audited,
    ):
        assert standards_audit.handle_command("audit", ["--help"]) is True
    helped.assert_called_once_with()
    assert audited.call_args_list == []


def test_handle_command_h_flag():
    """A help flag anywhere in the line answers before anything executes.

    `audit aipass -h` puts the flag past args[0], so only the wider scan in
    handle_command catches it. That scan is the whole point of
    help_flag_safety — "a question must never execute" — and a fleet audit is
    the most expensive thing this branch can be tricked into running. Both
    outcomes return True.
    """
    from aipass.seedgo.apps.modules import standards_audit

    with (
        patch.object(standards_audit, "print_help") as helped,
        patch.object(standards_audit, "audit_branch_incremental") as audited,
    ):
        assert standards_audit.handle_command("audit", ["aipass", "-h"]) is True
    helped.assert_called_once_with()
    assert audited.call_args_list == []


def test_handle_command_help_word():
    """The bare word 'help' reaches the same door as the flags."""
    from aipass.seedgo.apps.modules import standards_audit

    with (
        patch.object(standards_audit, "print_help") as helped,
        patch.object(standards_audit, "audit_branch_incremental") as audited,
    ):
        assert standards_audit.handle_command("audit", ["help"]) is True
    helped.assert_called_once_with()
    assert audited.call_args_list == []


def test_print_introspection_runs():
    """print_introspection names the module and both pack lanes.

    "console.print OR header was called" is true of a function that prints one
    blank line, so it measured nothing. The three strings here were read off a
    real run (2026-09-07). The third is the one that matters most: this module
    scores STANDARDS packs and must say out loud which discovered packs it is
    NOT scoring, or a reader takes the absence of `tests_pytest` for a missing
    pack rather than another lane.
    """
    import sys
    from aipass.seedgo.apps.modules.standards_audit import print_introspection

    mock_cli = sys.modules["aipass.cli"]
    mock_cli.console.reset_mock()
    mock_cli.header.reset_mock()
    result = print_introspection()
    printed = "\n".join(str(call.args[0]) for call in mock_cli.console.print.call_args_list if call.args)
    assert result is None
    assert "standards_audit Module" in printed, f"introspection never named the module: {printed!r}"
    assert "Discovered Packs:" in printed, f"introspection never listed the packs: {printed!r}"
    assert "Not scored here (other lanes):" in printed, f"introspection hid the non-scoring packs: {printed!r}"


def test_print_help_runs():
    """print_help prints its banner and the honest-score flag.

    Same reason as the introspection test above. `--no-bypass` is pinned rather
    than a decorative line: it is the flag that produces the second number every
    APLAN publishes, and help that stops documenting it is the reason a branch
    reports only its bypassed score.
    """
    import sys
    from aipass.seedgo.apps.modules.standards_audit import print_help

    mock_cli = sys.modules["aipass.cli"]
    mock_cli.console.reset_mock()
    mock_cli.header.reset_mock()
    result = print_help()
    printed = "\n".join(str(call.args[0]) for call in mock_cli.console.print.call_args_list if call.args)
    assert result is None
    assert "Standards Audit Module" in printed, f"help never named the module: {printed!r}"
    assert "audit aipass --no-bypass" in printed, f"help never documented --no-bypass: {printed!r}"


def test_handle_command_unknown_pack():
    """An unknown pack REFUSES with a non-zero code, it does not return quietly.

    This is the defect the 2026-09-07 fleet sweep found on this branch:
    `drone @seedgo audit not_a_real_subarg_xyz` printed the ❌ line and exited
    0, so a script checking $? read it as a clean audit.
    """
    import pytest

    from aipass.seedgo.apps.handlers.audit_tests import refusal
    from aipass.seedgo.apps.modules import CommandRefused
    from aipass.seedgo.apps.modules.standards_audit import handle_command

    with pytest.raises(CommandRefused) as refused:
        handle_command("audit", ["nonexistent_pack"])
    assert refused.value.code == refusal.EXIT_UNKNOWN_ARGUMENT
    assert refused.value.token == "nonexistent_pack"


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


def _refuse(argv: list):
    """Run the audit verb expecting a refusal, and hand back what it carried.

    Since 2026-09-07 a refusal is RAISED, not returned: `handle_command` used
    to answer True on every path and `seedgo.py` turned that into exit 0, so
    the shell could not tell a refusal from an audit. Every test below that
    used to read `handle_command(...) is True` now reads the code instead -
    the same claim, made where it is now load-bearing.
    """
    from aipass.seedgo.apps.modules import CommandRefused
    from aipass.seedgo.apps.modules.standards_audit import handle_command

    with pytest.raises(CommandRefused) as refused:
        handle_command("audit", argv)
    return refused.value


def test_the_space_typo_refuses_and_never_runs_the_standards_audit(monkeypatch):
    """`audit -tests @backup` -- a space where a hyphen belonged.

    The token was dropped, `@backup` was read as the branch, and a cached
    standards audit printed as though it were the execution lane. Twenty
    minutes were spent reading one lane's numbers as another's.
    """
    audit_mock = _wire_branches(monkeypatch, "BACKUP")

    assert _refuse(["-tests", "@backup"]).code == 7
    assert audit_mock.call_count == 0, "the audit ran on a command it had not understood"
    assert _refused_argv()


def test_the_refusal_names_the_token_and_gives_the_working_command(monkeypatch):
    """The owner's ruling: it should have failed AND given the solution."""
    _wire_branches(monkeypatch, "BACKUP")

    _refuse(["-tests", "@backup"])

    assert "'-tests'" in _refusal_text()
    assert "did you mean: drone @seedgo audit tests @backup" in _refusal_text()


def test_the_refusal_exits_non_zero_and_cites_argv(monkeypatch):
    _wire_branches(monkeypatch, "BACKUP")

    refused = _refuse(["-tests", "@backup"])

    assert _refusal_text().startswith("REFUSED: [ARGV]")
    # The code is printed beside the law, and it is not a pass — AND the
    # process leaves with it. Printing "exit code: 7" over an exit 0 was the
    # defect the 2026-09-07 fleet sweep named.
    assert "exit code: 7" in _console_text()
    assert refused.code == 7


def test_an_extra_positional_is_refused_rather_than_ignored(monkeypatch):
    """Pack, then @branch. A third bare word filled no slot and vanished."""
    audit_mock = _wire_branches(monkeypatch, "FLOW")

    assert _refuse(["aipass", "@flow", "@prax", "--no-artifact"]).code == 7
    assert audit_mock.call_count == 0
    assert "'@prax'" in _refusal_text()


def test_the_first_unrecognized_token_is_the_one_reported(monkeypatch):
    """Argv order, so the report names the mistake the caller made first."""
    _wire_branches(monkeypatch, "FLOW")

    _refuse(["aipass", "--first", "--second"])

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
    """The owner's ask: `audit tests @backup`, a plain word where a hyphen was.

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

    forwarded = _forwarded(monkeypatch, ["tests", *argv])
    assert forwarded is not None, "the audit verb never handed the lane anything"
    assert lane._parse(forwarded) == lane._parse(argv)


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

    assert _refuse(["-tests", "@backup"]).code == 7

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

    assert _refuse(["tests", "@backup"]).code == 7

    assert _refused_argv(), "an ambiguous word must refuse, never resolve by preference"
    assert calls == [], "the lane must not be picked silently"
    assert audit_mock.call_count == 0, "the pack must not be picked silently"


def test_the_ambiguity_refusal_names_both_meanings(monkeypatch):
    """A refusal that says only 'ambiguous' leaves the reader to guess what collided."""
    _wire_branches(monkeypatch, "BACKUP")
    _wire_lane(monkeypatch)
    _collide(monkeypatch)

    _refuse(["tests", "@backup"])
    text = _refusal_text() + "\n" + _console_text()

    assert "'tests'" in text
    assert "audit-tests lane" in text, "the execution lane is one of the two meanings"
    assert "standards pack" in text, "the pack is the other"


def test_the_ambiguity_refusal_offers_an_unambiguous_spelling_for_each(monkeypatch):
    """Naming the collision is half the fix; the other half is how to say each one."""
    _wire_branches(monkeypatch, "BACKUP")
    _wire_lane(monkeypatch)
    _collide(monkeypatch)

    _refuse(["tests", "@backup"])
    text = _console_text()

    assert "drone @seedgo audit-tests <target>" in text
    assert "drone @seedgo audit tests_standards" in text


def test_the_ambiguity_refusal_cites_argv_and_its_exit_code(monkeypatch):
    """The existing vocabulary, not a parallel one: same law, same code 7."""
    _wire_branches(monkeypatch, "BACKUP")
    _wire_lane(monkeypatch)
    _collide(monkeypatch)

    refused = _refuse(["tests", "@backup"])

    assert _refusal_text().startswith("REFUSED: [ARGV]")
    assert "exit code: 7" in _console_text()
    assert refused.code == 7, "the printed code and the carried code are one number"


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


# ---------------------------------------------------------------------------
# THE CONTEXT PACK -- `audit context` is the startup-budget fleet table
# ---------------------------------------------------------------------------
#
# The verb strips the `_standards` suffix, so `handlers/context_standards/`
# IS `drone @seedgo audit context`. That is the whole reason the pack carries
# that directory name (DPLAN-0347, seedgo's row 1): one rule that measures six
# files per branch must not drag the 47 rules of aipass_standards over every
# branch's source to answer.

#: This branch's real `handlers/` directory, reached through the real discovery
#: handler bound above -- the autouse fixture replaces the module in sys.modules
#: for every test in this file, so asking for the path through the mock would
#: hand back a MagicMock.
_HANDLERS_DIR = Path(real_discovery.__file__).resolve().parent.parent


def test_the_context_pack_is_discovered_as_the_context_verb():
    """`handlers/context_standards/` must reach the audit as the word `context`.

    Pins the DIRECTORY NAME against the verb, and the manifest's `kind` against
    the lane. A pack that declared `kind: execution` would vanish from the
    scoring audit entirely and `drone @seedgo audit context` would refuse as an
    unknown pack -- the same silent disappearance discover_packs() publishes
    non_scoring_packs() to prevent.
    """
    packs = real_discovery.discover_packs(_HANDLERS_DIR)

    assert "context" in packs, f"the context pack must be offered for scoring; found {sorted(packs)}"
    assert packs["context"].name == "context_standards"
    assert real_discovery.pack_kind(packs["context"]) == real_discovery.SCORING_PACK_KIND
    assert "context" not in real_discovery.non_scoring_packs(_HANDLERS_DIR)


def test_the_context_pack_holds_only_the_startup_budget_checker():
    """One rule, its own pack -- the point of giving it a pack at all.

    `audit context` exists so the startup budget can be asked without running
    the other 47 rules. A second checker landing here without that being the
    intent would make the cheap question expensive again.
    """
    pack = real_discovery.discover_packs(_HANDLERS_DIR)["context"]

    assert [f.name for f in sorted(pack.glob("*_check.py"))] == ["startup_budget_check.py"]


def _wire_context_pack(monkeypatch):
    """Make `context` resolve to this branch's real pack directory."""
    import sys

    packs = {"aipass": Path("handlers/aipass_standards"), "context": _HANDLERS_DIR / "context_standards"}
    monkeypatch.setattr(
        sys.modules["aipass.seedgo.apps.handlers.audit.discovery"], "discover_packs", MagicMock(return_value=packs)
    )
    return packs


def test_audit_context_with_no_branch_audits_every_branch(monkeypatch):
    """`drone @seedgo audit context` is the FLEET table -- no branch argument.

    A pack name with nothing after it must not be read as a missing branch: the
    fleet run is the command the owner asks for, and the table is one row per
    citizen.
    """
    audit_mock = _wire_branches(monkeypatch, "FLOW", "PRAX")
    _wire_context_pack(monkeypatch)
    from aipass.seedgo.apps.modules.standards_audit import handle_command

    assert handle_command("audit", ["context", "--no-artifact"]) is True
    assert audit_mock.call_count == 2, "every discovered branch gets a row"
    assert {call.kwargs["pack_path"].name for call in audit_mock.call_args_list} == {"context_standards"}


def test_audit_context_standards_reaches_the_same_pack(monkeypatch):
    """The directory's own name is an unambiguous spelling for its pack."""
    audit_mock = _wire_branches(monkeypatch, "FLOW")
    _wire_context_pack(monkeypatch)
    from aipass.seedgo.apps.modules.standards_audit import handle_command

    assert handle_command("audit", ["context_standards", "@flow", "--no-artifact"]) is True
    assert audit_mock.call_args.kwargs["pack_path"].name == "context_standards"


def test_audit_context_refuses_an_unknown_branch_by_name(monkeypatch):
    """A branch that does not exist REFUSES, names itself, and audits nothing.

    Same contract as `audit aipass @nope`, asserted for the new verb because a
    pack reached through a different code path is a pack whose refusal nobody
    has watched: printing the ❌ line and exiting 0 is the exact defect the
    2026-09-07 fleet sweep found here.
    """
    from aipass.seedgo.apps.handlers.audit_tests import refusal

    audit_mock = _wire_branches(monkeypatch, "FLOW")
    _wire_context_pack(monkeypatch)

    refused = _refuse(["context", "@not_a_branch_xyz", "--no-artifact"])

    assert refused.code == refusal.EXIT_UNKNOWN_ARGUMENT
    assert "NOT_A_BRANCH_XYZ" in str(refused.token)
    assert "not_a_branch_xyz" in _refusal_text().lower(), "the refusal must name the branch it could not find"
    assert audit_mock.call_count == 0, "nothing may be audited once the target is unknown"


# ===========================================================================
# The CI gate script -- .github/scripts/seedgo_audit.py (DPLAN-0347 phase 5)
# ===========================================================================
#
# The script has no importable surface: it is top-level code that audits the
# whole fleet the moment it is imported. So it is pinned the way CI meets it --
# RUN, in a subprocess, against a throwaway tree. That is also the only way to
# prove the ratchet reached the exit code, rather than proving that a line of
# source exists.
#
# The tree is a fixture, never the live fleet: growing a real README to watch a
# gate go red leaves the repo one forgotten restore away from a phantom failure.

CI_GATE = Path(__file__).resolve().parents[4] / ".github" / "scripts" / "seedgo_audit.py"


def _fixture_fleet(root, **branches):
    """A tree shaped like the repo: src/aipass/<branch>/apps plus gated files.

    src/aipass is created even with no branches, because that is the shape the
    script walks: a checkout without it is a broken checkout, not an empty fleet.
    """
    (root / "src" / "aipass").mkdir(parents=True, exist_ok=True)
    for name, files in branches.items():
        (root / "src" / "aipass" / name / "apps").mkdir(parents=True, exist_ok=True)
        for rel, text in files.items():
            path = root / "src" / "aipass" / name / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
    return root


def _run_ci_gate(cwd):
    """Run the CI gate script exactly as the workflow step does."""
    import subprocess
    import sys

    return subprocess.run([sys.executable, str(CI_GATE)], cwd=str(cwd), capture_output=True, text=True, timeout=300)


def test_the_ci_gate_goes_red_when_a_gated_readme_grows_past_its_cap(tmp_path):
    """The whole point: CI fails, and the line says which file, how big, and whose cap.

    Run end to end through the real script, so what is pinned is the exit code
    a workflow step reads -- not a helper somebody could stop calling.
    """
    from aipass.seedgo.apps.handlers.context_standards import startup_budget_check

    cap, reason = startup_budget_check.readme_cap()
    assert cap is not None, f"the shipped pack.json must publish a README cap: {reason}"
    fleet = _fixture_fleet(tmp_path, overgrown={"README.md": "x" * (cap + 1)})

    done = _run_ci_gate(fleet)

    assert done.returncode == 1, done.stdout + done.stderr
    assert "STARTUP RATCHET FAILED" in done.stdout
    assert "src/aipass/overgrown/README.md" in done.stdout, "the file, spelled repo-relative"
    assert f"{cap + 1:,} chars" in done.stdout, "the measurement"
    assert f"cap {cap:,} chars" in done.stdout, "the cap"
    assert "@seedgo" in done.stdout, "the owner"


def test_the_ratchet_runs_before_the_audit_and_short_circuits_it(tmp_path):
    """A red ratchet stops the job before pyright walks eighteen branches.

    An over-cap README is self-diagnosing; spending the audit's minutes on a run
    that is already red buys nothing. The pin is that no audit output reached
    the log at all -- neither a branch row nor the pack-count tripwire.
    """
    fleet = _fixture_fleet(tmp_path, overgrown={"README.md": "x" * 100000})

    done = _run_ci_gate(fleet)

    assert done.returncode == 1
    assert "TRIPWIRE" not in done.stdout, "the audit never ran"
    assert "branches pass" not in done.stdout


def test_the_ci_gate_reaches_the_audit_when_the_ratchet_is_green(tmp_path):
    """Under cap, the job carries on to the standards audit, exactly as before.

    An empty fleet is the cleanest way to say it: nothing to gate, nothing to
    audit, and the script's own closing line proves control flowed past the
    ratchet rather than exiting at it.
    """
    done = _run_ci_gate(_fixture_fleet(tmp_path))

    assert done.returncode == 0, done.stdout + done.stderr
    assert "STARTUP RATCHET FAILED" not in done.stdout
    assert "All 0 branches pass" in done.stdout, "the audit's own verdict line"


def test_the_name_ratchet_is_advisory_so_its_red_never_fails_the_job(tmp_path):
    """DPLAN-0350 lands advisory: a red name ratchet prints and the job carries on.

    The fixture tree is not a git checkout, so the name ratchet cannot list
    what is tracked and is red -- the honest verdict. The pin is that the red
    reached the log AND the audit's own verdict line still followed it with a
    zero exit. When @devpulse flips NAME_RATCHET_GATES, this is the test that
    moves with it.
    """
    done = _run_ci_gate(_fixture_fleet(tmp_path))

    assert "NAME RATCHET" in done.stdout and "advisory" in done.stdout, done.stdout
    assert "git ls-files" in done.stdout, "the red says why"
    assert done.returncode == 0, done.stdout + done.stderr
    assert "All 0 branches pass" in done.stdout, "the audit ran after the advisory red"


def test_the_ci_gate_keeps_its_tripwire_and_its_hundred_percent_threshold():
    """The ratchet was added BESIDE the existing gates, never instead of them.

    EXPECTED_STANDARDS catches a standard leaving the audit silently, and
    THRESHOLD holds every branch at 100. What is pinned is that both are still
    DECLARED and still COMPARED -- not the pack count itself, which moves by
    hand every time a standard is added or retired and would make this a false
    red in somebody else's lane.
    """
    import re

    source = CI_GATE.read_text(encoding="utf-8")

    assert re.search(r"^EXPECTED_STANDARDS = \d+", source, re.M), "the pack-count tripwire must still be declared"
    assert re.search(r"^THRESHOLD = 100\b", source, re.M), "every branch is still held at 100"
    assert "len(consulted) != EXPECTED_STANDARDS" in source, "the tripwire must still be compared"
    assert "avg < THRESHOLD" in source, "the per-branch threshold must still be compared"


def test_the_ci_gate_holds_no_cap_of_its_own(tmp_path):
    """No number lives in .github/. The gate reads the owner's config at run time.

    A constant here would be a third copy of a cap -- unreachable from the
    owner, unmoved by a diet, and green long after the ruling changed.
    """
    import ast

    literals = {
        node.value
        for node in ast.walk(ast.parse(CI_GATE.read_text(encoding="utf-8")))
        if isinstance(node, ast.Constant) and isinstance(node.value, int) and not isinstance(node.value, bool)
    }

    assert literals.isdisjoint({10000, 9000, 6000, 15000, 25000}), f"a cap was copied into the CI script: {literals}"
