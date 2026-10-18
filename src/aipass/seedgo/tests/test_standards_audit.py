# =================== META ====================
# Name: test_standards_audit.py
# Description: Unit tests for the standards_audit module and the seedgo-audit CI gate
# Version: 1.3.2
# Created: 2026-03-24
# Modified: 2026-10-17
# =============================================

"""Tests for apps/modules/standards_audit.py and the seedgo-audit CI gate."""


# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(standard) — each checker's own verdict; every <row>_check.py has its own test file
# seedgo: no-test-needed(covered) — the audit-tests lane's own run, in tests/test_audit_tests_lane.py

import tempfile

import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path
from typing import cast


#: The real discovery handler: standards_audit's own `discovery` binding is a per-test stand-in (`_mock_infrastructure`).
from aipass.seedgo.apps.handlers.audit import discovery as real_discovery
from aipass.seedgo.apps.handlers.bypass import bypass_handler
from aipass.cli.apps.modules import display
from aipass.cli.apps.modules import warning as real_warning
from aipass.seedgo.apps.handlers.audit_tests import refusal
from aipass.seedgo.apps.handlers.context_standards import startup_budget_check
from aipass.seedgo.apps.modules import CommandRefused, standards_audit
from aipass.seedgo.apps.modules import audit_tests as lane


@pytest.fixture(autouse=True)
def _mock_infrastructure(monkeypatch, tmp_path):
    """Replace the seams standards_audit reads, so tests run fast and without side effects."""
    # The console is NOT replaced: standards_audit prints through aipass.cli's
    # real console, which writes to sys.stdout at print time, so a test reads
    # what the user reads with capsys (width pinned by conftest).
    mock_normalize = MagicMock(side_effect=lambda x: x.lstrip("@").upper())

    mock_discovery = MagicMock()
    # A bare MagicMock answers pack discovery with a truthy, empty-iterating mock that reads as "packs found, none of them",
    # so the return values are spelled out.
    mock_discovery.discover_packs = MagicMock(return_value={"aipass": Path("handlers/aipass_standards")})
    mock_discovery.non_scoring_packs = MagicMock(return_value={"tests_pytest": "execution"})

    monkeypatch.setattr(standards_audit, "logger", MagicMock())
    monkeypatch.setattr(standards_audit, "header", MagicMock())
    monkeypatch.setattr(standards_audit, "error", MagicMock())
    monkeypatch.setattr(standards_audit, "warning", MagicMock())
    monkeypatch.setattr(standards_audit, "json_handler", MagicMock())
    # Rebound, not mutated: the real discovery module is the same object as `real_discovery`, which other tests run for real.
    monkeypatch.setattr(standards_audit, "discovery", mock_discovery)
    monkeypatch.setattr(standards_audit, "discover_branches", MagicMock(return_value=[]))
    monkeypatch.setattr(standards_audit, "_is_branch_private", MagicMock(return_value=False))
    monkeypatch.setattr(standards_audit, "check_internal_access", MagicMock(return_value=True))
    monkeypatch.setattr(standards_audit, "audit_branch_incremental", MagicMock())
    monkeypatch.setattr(standards_audit, "cache_tag", MagicMock())
    monkeypatch.setattr(standards_audit, "print_branch_summary", MagicMock())
    monkeypatch.setattr(standards_audit, "print_system_summary", MagicMock())
    # Keeps every test in this file off the real .seedgo/ artifact on disk.
    monkeypatch.setattr(standards_audit, "write_audit_artifact", MagicMock(return_value=tmp_path / "last_audit.json"))
    monkeypatch.setattr(standards_audit, "load_bypass_rules", MagicMock(return_value=[]))
    monkeypatch.setattr(standards_audit, "normalize_branch_arg", mock_normalize)


def test_handle_command_wrong_command_returns_false():
    """handle_command returns False for unrecognised commands."""
    assert standards_audit.handle_command("not_audit", []) is False


def test_handle_command_accepts_audit_name():
    """'audit' reaches this module's own introspection, not just a True."""
    with patch.object(standards_audit, "_show_audit_introspection") as shown:
        assert standards_audit.handle_command("audit", []) is True
    shown.assert_called_once_with()


def test_handle_command_accepts_standards_audit_name():
    """'standards_audit' is the same door, not a near miss returning True."""
    with patch.object(standards_audit, "_show_audit_introspection") as shown:
        assert standards_audit.handle_command("standards_audit", []) is True
    shown.assert_called_once_with()


def test_handle_command_help_flag():
    """--help explains and audits no branch."""
    with (
        patch.object(standards_audit, "print_help") as helped,
        patch.object(standards_audit, "audit_branch_incremental") as audited,
    ):
        assert standards_audit.handle_command("audit", ["--help"]) is True
    helped.assert_called_once_with()
    assert audited.call_args_list == []


def test_handle_command_h_flag():
    """A help flag anywhere in the line answers before anything executes."""
    with (
        patch.object(standards_audit, "print_help") as helped,
        patch.object(standards_audit, "audit_branch_incremental") as audited,
    ):
        assert standards_audit.handle_command("audit", ["aipass", "-h"]) is True
    helped.assert_called_once_with()
    assert audited.call_args_list == []


def test_handle_command_help_word():
    """The bare word 'help' reaches the same door as the flags."""
    with (
        patch.object(standards_audit, "print_help") as helped,
        patch.object(standards_audit, "audit_branch_incremental") as audited,
    ):
        assert standards_audit.handle_command("audit", ["help"]) is True
    helped.assert_called_once_with()
    assert audited.call_args_list == []


def test_print_introspection_runs(capsys: pytest.CaptureFixture[str]) -> None:
    """print_introspection names the module and both pack lanes."""
    capsys.readouterr()
    result = standards_audit.print_introspection()
    printed = capsys.readouterr().out
    assert result is None
    assert "standards_audit Module" in printed, f"introspection never named the module: {printed!r}"
    assert "Discovered Packs:" in printed, f"introspection never listed the packs: {printed!r}"
    assert "Not scored here (other lanes):" in printed, f"introspection hid the non-scoring packs: {printed!r}"


def test_print_help_runs(capsys: pytest.CaptureFixture[str]) -> None:
    """print_help prints its banner and the honest-score flag."""
    capsys.readouterr()
    result = standards_audit.print_help()
    printed = capsys.readouterr().out
    assert result is None
    assert "Standards Audit Module" in printed, f"help never named the module: {printed!r}"
    assert "audit aipass --no-bypass" in printed, f"help never documented --no-bypass: {printed!r}"


def test_handle_command_unknown_pack():
    """An unknown pack REFUSES with a non-zero code, it does not return quietly."""
    with pytest.raises(CommandRefused) as refused:
        standards_audit.handle_command("audit", ["nonexistent_pack"])
    assert refused.value.code == refusal.EXIT_UNKNOWN_ARGUMENT
    assert refused.value.token == "nonexistent_pack"


def test_discover_packs_returns_dict(tmp_path):
    """Pack discovery finds *_standards dirs holding *_check.py files."""
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
    assert standards_audit.handle_command("invalid_command", []) is False


# What load_bypass_rules() hands back on a normal run. A --no-bypass run must
# audit with [] instead -- never with these.
_LOADED_RULES = [{"file": "apps/flow.py", "standard": "cli", "reason": "legacy"}]


def _wire_branches(monkeypatch, *names):
    """Point the mocked discovery/bypass/audit handlers at fake branches."""
    tmp = tempfile.gettempdir()
    discover = MagicMock(
        return_value=[
            {"name": n, "path": f"{tmp}/{n.lower()}", "entry_file": f"{tmp}/{n.lower()}/apps/{n.lower()}.py"}
            for n in names
        ]
    )
    monkeypatch.setattr(standards_audit, "discover_branches", discover)
    monkeypatch.setattr(standards_audit, "load_bypass_rules", MagicMock(return_value=list(_LOADED_RULES)))
    audit_mock = MagicMock(return_value={"branch": {"name": names[0]}, "scores": {"cli": 100}, "average": 100})
    monkeypatch.setattr(standards_audit, "audit_branch_incremental", audit_mock)
    return audit_mock


def _rules_per_branch(audit_mock):
    """The bypass_rules argument every audited branch was given, in order."""
    return [call.args[1] for call in audit_mock.call_args_list]


def _console_text(capsys: pytest.CaptureFixture[str]) -> str:
    """Everything the module printed to stdout since the last read, as one string."""
    return capsys.readouterr().out


def test_no_bypass_after_branch_arg_disables_every_rule(monkeypatch):
    """'audit aipass @flow --no-bypass' audits with an empty rule set."""
    audit_mock = _wire_branches(monkeypatch, "FLOW")
    assert standards_audit.handle_command("audit", ["aipass", "@flow", "--no-bypass", "--no-artifact"]) is True
    assert _rules_per_branch(audit_mock) == [[]]


def test_no_bypass_before_branch_arg_disables_every_rule(monkeypatch):
    """Reverse order — 'audit aipass --no-bypass @flow' must not swallow the flag."""
    audit_mock = _wire_branches(monkeypatch, "FLOW")
    assert standards_audit.handle_command("audit", ["aipass", "--no-bypass", "@flow", "--no-artifact"]) is True
    assert _rules_per_branch(audit_mock) == [[]]


def test_no_bypass_applies_to_every_branch_of_a_fleet_run(monkeypatch):
    """'audit aipass --no-bypass' (no branch arg) disables rules fleet-wide."""
    audit_mock = _wire_branches(monkeypatch, "FLOW", "PRAX")
    assert standards_audit.handle_command("audit", ["aipass", "--no-bypass", "--no-artifact"]) is True
    assert _rules_per_branch(audit_mock) == [[], []]


def test_normal_run_still_applies_the_loaded_bypass_rules(monkeypatch):
    """Control — without the flag the branch's own rules are still passed through."""
    audit_mock = _wire_branches(monkeypatch, "FLOW")
    assert standards_audit.handle_command("audit", ["aipass", "@flow", "--no-artifact"]) is True
    assert _rules_per_branch(audit_mock) == [_LOADED_RULES]


def test_no_bypass_run_announces_itself(monkeypatch, capsys: pytest.CaptureFixture[str]) -> None:
    """A suppressed-rules run says so — no reader may mistake it for a normal one."""
    _wire_branches(monkeypatch, "FLOW")
    standards_audit.handle_command("audit", ["aipass", "@flow", "--no-bypass", "--no-artifact"])
    text = _console_text(capsys).upper()
    assert "BYPASS" in text and "DISABLED" in text, "A --no-bypass run must declare that bypasses are off"


def test_normal_run_makes_no_bypass_claim(monkeypatch, capsys: pytest.CaptureFixture[str]) -> None:
    """Control — the declaration is not printed on a normal run."""
    _wire_branches(monkeypatch, "FLOW")
    standards_audit.handle_command("audit", ["aipass", "@flow", "--no-artifact"])
    assert "BYPASSES DISABLED" not in _console_text(capsys).upper()


def _audit_reading_the_registry(tmp_path, monkeypatch, content):
    """An audit whose branch run reads the registry through the real get_branch_from_path."""
    registry = tmp_path / ("d" * 100) / "AIPASS_REGISTRY.json"
    registry.parent.mkdir()
    registry.write_text(content, encoding="utf-8")
    for console in (display.CONSOLE, display.err_console):
        monkeypatch.setattr(console, "width", 10_000)
    monkeypatch.setattr(bypass_handler, "_find_registry", lambda: registry)
    monkeypatch.setattr(bypass_handler, "UNREADABLE_REGISTRIES", {})
    # The module's autouse stand-in swallows warning(); the note is read off the real one.
    monkeypatch.setattr(standards_audit, "warning", real_warning)
    audit_mock = _wire_branches(monkeypatch, "FLOW")
    answer = audit_mock.return_value

    def _audit(*args, **kwargs):
        bypass_handler.get_branch_from_path(str(tmp_path / "flow" / "apps" / "flow.py"))
        return answer

    audit_mock.side_effect = _audit
    assert standards_audit.handle_command("audit", ["aipass", "@flow", "--no-artifact"]) is True
    return registry


def test_an_unreadable_registry_is_named_once_by_the_audit(tmp_path, monkeypatch, capsys) -> None:
    """Red first: a checker's registry read failed and the audit said nothing (fleet green leg 15)."""
    registry = _audit_reading_the_registry(tmp_path, monkeypatch, "{not json")
    said = capsys.readouterr()
    found = [line for line in (said.out + said.err).splitlines() if "registry unreadable" in line]
    assert len(found) == 1
    assert registry.name in found[0]


def test_a_readable_registry_draws_no_audit_note(tmp_path, monkeypatch, capsys) -> None:
    """Control: the same audit over a registry that parses says nothing about it."""
    _audit_reading_the_registry(tmp_path, monkeypatch, '{"branches": []}')
    said = capsys.readouterr()
    assert "registry unreadable" not in said.out + said.err


def test_help_documents_the_no_bypass_flag(capsys: pytest.CaptureFixture[str]) -> None:
    """--help lists --no-bypass — help text must match runtime behaviour."""
    capsys.readouterr()
    standards_audit.print_help()
    assert "--no-bypass" in _console_text(capsys)


def test_help_text_at_prefix_consistency():
    """All help text branch references use @ prefix (DPLAN-0085 fresh-eyes fix)."""
    import re

    branch_root = Path(__file__).resolve().parents[1]
    files_to_check = [
        branch_root / "apps" / "seedgo.py",
        *sorted((branch_root / "apps" / "modules").glob("*.py")),
    ]

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
            if '"' not in line and "'" not in line:
                continue
            match = bare_branch_re.search(line)
            if match:
                violations.append(f"{fpath.name}:{i}: bare '{match.group(1)}' (should be '@{match.group(1)}')")

    assert violations == [], f"Help text has {len(violations)} bare branch references (missing @):\n" + "\n".join(
        violations
    )


def test_artifact_flag_does_not_swallow_a_help_token(monkeypatch):
    """'audit aipass --artifact --help' must explain, not run and write to '--help'."""
    audit_mock = _wire_branches(monkeypatch, "FLOW")
    assert standards_audit.handle_command("audit", ["aipass", "--artifact", "--help"]) is True
    assert audit_mock.call_count == 0


def test_artifact_flag_still_takes_a_real_destination(monkeypatch):
    """Control — a genuine path after --artifact is still consumed as the path."""
    audit_mock = _wire_branches(monkeypatch, "FLOW")
    assert standards_audit.handle_command("audit", ["aipass", "@flow", "--artifact", "out.json"]) is True
    assert audit_mock.call_count == 1


def _refusal_text():
    """Everything the module sent to error() this test, as one string."""
    calls = cast(MagicMock, standards_audit.error).call_args_list
    return "\n".join(str(call.args[0]) if call.args else "" for call in calls)


def _refused_argv() -> bool:
    """True when this run refused under Law ARGV."""
    return "REFUSED: [ARGV]" in _refusal_text()


def _refuse(argv: list):
    """Run the audit verb expecting a refusal, and hand back what it carried."""
    with pytest.raises(CommandRefused) as refused:
        standards_audit.handle_command("audit", argv)
    return refused.value


def test_the_space_typo_refuses_and_never_runs_the_standards_audit(monkeypatch):
    """`audit -tests @backup` -- a space where a hyphen belonged."""
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


def test_the_refusal_exits_non_zero_and_cites_argv(monkeypatch, capsys: pytest.CaptureFixture[str]) -> None:
    _wire_branches(monkeypatch, "BACKUP")

    refused = _refuse(["-tests", "@backup"])

    assert _refusal_text().startswith("REFUSED: [ARGV]")
    # The code is printed beside the law, never as a pass, and the process exits with it.
    assert "exit code: 7" in _console_text(capsys)
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
    assert standards_audit.handle_command("audit", ["-tests", "--help"]) is True
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
    assert standards_audit.handle_command("audit", argv) is True
    assert not _refused_argv(), f"{argv} is documented usage and must not be refused"
    assert audit_mock.call_count == 1, f"{argv} must still audit the branch"


@pytest.mark.parametrize("argv", [[], ["--help"], ["-h"], ["help"], ["aipass", "--show-bypasses"], ["aipass", "-b"]])
def test_every_valid_non_auditing_invocation_still_answers(monkeypatch, argv):
    """The forms that print rather than audit: still no refusal."""
    _wire_branches(monkeypatch, "FLOW")
    assert standards_audit.handle_command("audit", argv) is True
    assert not _refused_argv(), f"{argv} is documented usage and must not be refused"


def _wire_lane(monkeypatch):
    """Stand in for the execution lane and record what it was handed."""
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
    assert standards_audit.handle_command("audit", argv) is True
    return calls[0][1] if calls else None


def test_audit_tests_reaches_the_lane_with_the_target(monkeypatch):
    """The owner's ask: `audit tests @backup`, a plain word where a hyphen was."""
    audit_mock = _wire_branches(monkeypatch, "BACKUP")

    assert _forwarded(monkeypatch, ["tests", "@backup"]) == ["@backup"]
    assert audit_mock.call_count == 0, "the standards engine must never see the execution lane's target"
    assert not _refused_argv()


def test_the_lane_is_claimed_under_its_own_verb_name(monkeypatch):
    """The hand-off names `audit-tests`, so the lane's own refusals stay truthful."""
    calls = _wire_lane(monkeypatch)
    standards_audit.handle_command("audit", ["tests", "@backup"])

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
    """Whatever follows `tests` is handed on untouched, in order."""
    assert _forwarded(monkeypatch, ["tests", *tail]) == tail


def test_the_forwarded_line_parses_exactly_as_the_alias_does(monkeypatch):
    """`audit tests X` and `audit-tests X` reach the lane's parser identically."""
    argv = ["@backup", "--budget", "300", "--prove-refusal"]

    forwarded = _forwarded(monkeypatch, ["tests", *argv])
    assert forwarded is not None, "the audit verb never handed the lane anything"

    parsed: list = []

    def _record_run(argument, options=None):
        """What the lane's parser produced, handed to the runner; nothing is run."""
        parsed.append((argument, options))
        return [], 0

    monkeypatch.setattr(lane.runner, "run", _record_run)
    assert lane.handle_command("audit-tests", forwarded) is True
    assert lane.handle_command("audit-tests", argv) is True
    assert parsed[0][0] == "@backup"
    assert parsed[0] == parsed[1]


def test_the_hyphenated_alias_still_claims_the_lane():
    """`audit-tests` did not stop working when `audit tests` became canonical."""
    assert "audit-tests" in lane.COMMANDS
    assert lane.handle_command("audit-tests", []) is True
    assert lane.handle_command("audit", []) is False, "the lane must not claim the audit verb"


def test_the_lane_word_is_recognised_before_pack_validation(monkeypatch):
    """`tests` is not a pack, and must never be reported as an unknown one."""
    _wire_branches(monkeypatch, "BACKUP")
    cast(MagicMock, standards_audit.error).reset_mock()
    _forwarded(monkeypatch, ["tests", "@backup"])

    assert "Unknown pack" not in _refusal_text()


def test_the_space_typo_now_suggests_the_canonical_two_word_form(monkeypatch):
    """`audit -tests @backup` still refuses -- and points at `audit tests`."""
    audit_mock = _wire_branches(monkeypatch, "BACKUP")

    assert _refuse(["-tests", "@backup"]).code == 7

    assert _refused_argv()
    assert audit_mock.call_count == 0
    assert "did you mean: drone @seedgo audit tests @backup" in _refusal_text()


def _collide(monkeypatch):
    """Make a scoring pack named `tests` resolve, so the word means two things."""
    monkeypatch.setattr(
        standards_audit.discovery,
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


def test_the_ambiguity_refusal_names_both_meanings(monkeypatch, capsys: pytest.CaptureFixture[str]) -> None:
    """A refusal that says only 'ambiguous' leaves the reader to guess what collided."""
    _wire_branches(monkeypatch, "BACKUP")
    _wire_lane(monkeypatch)
    _collide(monkeypatch)

    _refuse(["tests", "@backup"])
    text = _refusal_text() + "\n" + _console_text(capsys)

    assert "'tests'" in text
    assert "audit-tests lane" in text, "the execution lane is one of the two meanings"
    assert "standards pack" in text, "the pack is the other"


def test_the_ambiguity_refusal_offers_an_unambiguous_spelling_for_each(
    monkeypatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Naming the collision is half the fix; the other half is how to say each one."""
    _wire_branches(monkeypatch, "BACKUP")
    _wire_lane(monkeypatch)
    _collide(monkeypatch)

    _refuse(["tests", "@backup"])
    text = _console_text(capsys)

    assert "drone @seedgo audit-tests <target>" in text
    assert "drone @seedgo audit tests_standards" in text


def test_the_ambiguity_refusal_cites_argv_and_its_exit_code(monkeypatch, capsys: pytest.CaptureFixture[str]) -> None:
    """The existing vocabulary, not a parallel one: same law, same code 7."""
    _wire_branches(monkeypatch, "BACKUP")
    _wire_lane(monkeypatch)
    _collide(monkeypatch)

    refused = _refuse(["tests", "@backup"])

    assert _refusal_text().startswith("REFUSED: [ARGV]")
    assert "exit code: 7" in _console_text(capsys)
    assert refused.code == 7, "the printed code and the carried code are one number"


def test_a_pack_named_tests_is_still_reachable_by_its_directory_name(monkeypatch):
    """The advice the refusal prints has to work, or it is not advice."""
    audit_mock = _wire_branches(monkeypatch, "FLOW")
    calls = _wire_lane(monkeypatch)
    _collide(monkeypatch)
    assert standards_audit.handle_command("audit", ["tests_standards", "@flow", "--no-artifact"]) is True

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
    assert standards_audit.handle_command("audit", argv) is True
    assert calls == [], f"{argv} is a standards audit and must never reach the execution lane"
    assert not _refused_argv(), f"{argv} is documented usage and must not be refused"
    assert audit_mock.call_count == 1, f"{argv} must still audit the branch"


@pytest.mark.parametrize("argv", [[], ["--help"], ["-h"], ["help"], ["aipass", "--show-bypasses"], ["aipass", "-b"]])
def test_the_lane_word_leaves_every_printing_invocation_alone(monkeypatch, argv):
    """The forms that print rather than audit: still no lane, still no refusal."""
    _wire_branches(monkeypatch, "FLOW")
    calls = _wire_lane(monkeypatch)
    assert standards_audit.handle_command("audit", argv) is True
    assert calls == []
    assert not _refused_argv()


# The verb strips `_standards`, so handlers/context_standards/ IS `audit context`: six files per branch, not the aipass rules.

#: This branch's real handlers/ dir via the real discovery: the per-test stand-in would hand back a MagicMock.
_HANDLERS_DIR = Path(real_discovery.__file__).resolve().parent.parent


def test_the_context_pack_is_discovered_as_the_context_verb():
    """`handlers/context_standards/` must reach the audit as the word `context`."""
    packs = real_discovery.discover_packs(_HANDLERS_DIR)

    assert "context" in packs, f"the context pack must be offered for scoring; found {sorted(packs)}"
    assert packs["context"].name == "context_standards"
    assert real_discovery.pack_kind(packs["context"]) == real_discovery.SCORING_PACK_KIND
    assert "context" not in real_discovery.non_scoring_packs(_HANDLERS_DIR)


def test_the_context_pack_holds_only_the_startup_budget_checker():
    """One rule, its own pack -- the point of giving it a pack at all."""
    pack = real_discovery.discover_packs(_HANDLERS_DIR)["context"]

    assert [f.name for f in sorted(pack.glob("*_check.py"))] == ["startup_budget_check.py"]


def _wire_context_pack(monkeypatch):
    """Make `context` resolve to this branch's real pack directory."""
    packs = {"aipass": Path("handlers/aipass_standards"), "context": _HANDLERS_DIR / "context_standards"}
    monkeypatch.setattr(standards_audit.discovery, "discover_packs", MagicMock(return_value=packs))
    return packs


def test_audit_context_with_no_branch_audits_every_branch(monkeypatch):
    """`drone @seedgo audit context` is the FLEET table -- no branch argument."""
    audit_mock = _wire_branches(monkeypatch, "FLOW", "PRAX")
    _wire_context_pack(monkeypatch)
    assert standards_audit.handle_command("audit", ["context", "--no-artifact"]) is True
    assert audit_mock.call_count == 2, "every discovered branch gets a row"
    assert {call.kwargs["pack_path"].name for call in audit_mock.call_args_list} == {"context_standards"}


def test_audit_context_standards_reaches_the_same_pack(monkeypatch):
    """The directory's own name is an unambiguous spelling for its pack."""
    audit_mock = _wire_branches(monkeypatch, "FLOW")
    _wire_context_pack(monkeypatch)
    assert standards_audit.handle_command("audit", ["context_standards", "@flow", "--no-artifact"]) is True
    assert audit_mock.call_args.kwargs["pack_path"].name == "context_standards"


def test_audit_context_refuses_an_unknown_branch_by_name(monkeypatch):
    """A branch that does not exist REFUSES, names itself, and audits nothing."""
    audit_mock = _wire_branches(monkeypatch, "FLOW")
    _wire_context_pack(monkeypatch)

    refused = _refuse(["context", "@not_a_branch_xyz", "--no-artifact"])

    assert refused.code == refusal.EXIT_UNKNOWN_ARGUMENT
    assert "NOT_A_BRANCH_XYZ" in str(refused.token)
    assert "not_a_branch_xyz" in _refusal_text().lower(), "the refusal must name the branch it could not find"
    assert audit_mock.call_count == 0, "nothing may be audited once the target is unknown"


# The CI gate script has no importable surface (it audits on import), so it runs in a subprocess against a fixture tree,
# never the live fleet.

CI_GATE = Path(__file__).resolve().parents[4] / ".github" / "scripts" / "seedgo_audit.py"


def _fixture_fleet(root, **branches):
    """A tree shaped like the repo: src/aipass/<branch>/apps plus gated files."""
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

    return subprocess.run(
        [sys.executable, str(CI_GATE)],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=300,
    )


def test_the_ci_gate_goes_red_when_a_gated_readme_grows_past_its_cap(tmp_path):
    """The whole point: CI fails, and the line says which file, how big, and whose cap."""
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
    """A red ratchet stops the job before pyright walks eighteen branches."""
    fleet = _fixture_fleet(tmp_path, overgrown={"README.md": "x" * 100000})

    done = _run_ci_gate(fleet)

    assert done.returncode == 1
    assert "TRIPWIRE" not in done.stdout, "the audit never ran"
    assert "branches pass" not in done.stdout


def test_the_ci_gate_reaches_the_audit_when_the_ratchet_is_green(tmp_path):
    """Under cap, the job carries on to the standards audit, exactly as before."""
    done = _run_ci_gate(_fixture_fleet(tmp_path))

    assert done.returncode == 0, done.stdout + done.stderr
    assert "STARTUP RATCHET FAILED" not in done.stdout
    assert "All 0 branches pass" in done.stdout, "the audit's own verdict line"


def test_the_name_ratchet_is_advisory_so_its_red_never_fails_the_job(tmp_path):
    """DPLAN-0350 lands advisory: a red name ratchet prints and the job carries on."""
    done = _run_ci_gate(_fixture_fleet(tmp_path))

    assert "NAME RATCHET" in done.stdout and "advisory" in done.stdout, done.stdout
    assert "git ls-files" in done.stdout, "the red says why"
    assert done.returncode == 0, done.stdout + done.stderr
    assert "All 0 branches pass" in done.stdout, "the audit ran after the advisory red"


def test_the_ci_gate_keeps_its_tripwire_and_its_hundred_percent_threshold():
    """The ratchet was added BESIDE the existing gates, never instead of them."""
    import re

    source = CI_GATE.read_text(encoding="utf-8")

    assert re.search(r"^EXPECTED_STANDARDS = \d+", source, re.M), "the pack-count tripwire must still be declared"
    assert re.search(r"^THRESHOLD = 100\b", source, re.M), "every branch is still held at 100"
    assert "len(consulted) != EXPECTED_STANDARDS" in source, "the tripwire must still be compared"
    assert "avg < THRESHOLD" in source, "the per-branch threshold must still be compared"


def test_the_ci_gate_holds_no_cap_of_its_own(tmp_path):
    """No number lives in .github/. The gate reads the owner's config at run time."""
    import ast

    literals = {
        node.value
        for node in ast.walk(ast.parse(CI_GATE.read_text(encoding="utf-8")))
        if isinstance(node, ast.Constant) and isinstance(node.value, int) and not isinstance(node.value, bool)
    }

    assert literals.isdisjoint({10000, 9000, 6000, 15000, 25000}), f"a cap was copied into the CI script: {literals}"
