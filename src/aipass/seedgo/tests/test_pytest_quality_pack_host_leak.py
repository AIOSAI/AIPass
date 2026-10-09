# =================== AIPass ====================
# Name: test_pytest_quality_pack_host_leak.py
# Description: pytest_quality pack, host_leak checker pins (split from test_pytest_quality_pack.py)
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-08
# =============================================

"""Tests for apps/handlers/pytest_quality_standards/host_leak_check.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(constant) — the content page prose, pytest_quality_standards/host_leak_content.py

from pathlib import Path

import pytest

from aipass.seedgo.apps.handlers.pytest_quality_standards import host_leak_check
from aipass.seedgo.tests.support_pytest_quality_pack import _unit, _write

# =============================================================================
# HOST LEAK - IS THE FAKE WORLD FAKED ALL THE WAY
# =============================================================================

# NOTHING IN THIS SECTION FAKES A PLATFORM, and the rule under test is why that is
# written down. A pin for a checker about units that force `sys.platform` is the
# one place in this file where a real `monkeypatch.setattr("sys.platform", ...)`
# would read as ordinary setup - and it would also be the exact species the rule
# hunts, written into the pack that hunts it. There is none: every unit below is
# source TEXT handed to the reader, every assertion is about what the CHECKER
# said over that text, and the answer is the same on every runner.


def _leak_rows(source: str) -> list:
    """The host_leak rows over one written-out unit."""
    return host_leak_check.unit_rows(_unit(source))


#: The row this rule was written for, as @ai_mail's unit stood before the cure:
#: `sys.platform` forced to darwin, and the fake `lsof` line the parser reads
#: built out of `tmp_path`. Windows run 35058244702.
THE_DARWIN_ROW = """
def test_get_pid_cwd_darwin(monkeypatch, tmp_path):
    monkeypatch.setattr("sys.platform", "darwin")
    target = str(tmp_path / "project")

    class FakeResult:
        returncode = 0
        stdout = f"p100\\nn{target}\\n"

    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: FakeResult())
    assert _get_pid_cwd("100") == target
"""

#: Its sibling three lines above it in the same file, still in the tree in
#: exactly this shape. Same fake, same binding, portable on every host - the
#: host path is handed to the subject as a VALUE and comes back unchanged.
THE_LINUX_SIBLING = """
def test_get_pid_cwd_linux(monkeypatch, tmp_path):
    monkeypatch.setattr("sys.platform", "linux")
    target = str(tmp_path / "project")
    monkeypatch.setattr(os, "readlink", lambda p: target)
    assert _get_pid_cwd("100") == target
"""


class TestTheRowItWasWrittenFor:
    """The Windows red of 2026-09-15, and the acquittal that sits beside it."""

    def test_the_darwin_row_that_wove_tmp_path_into_its_fake_lsof_line_is_flagged(self):
        """THE UNIT COULD NOT PARSE THE LINE THE UNIT ITSELF HAD WRITTEN.

        `_get_pid_cwd_darwin` accepts one grammar - `line.startswith("n/")`. On the
        Windows runner `tmp_path` renders `C:\\Users\\...`, the `n/` prefix never
        appeared, the parser answered None, and the assertion read None against a
        path (run 35058244702). Losing the f-string arm loses the only row this
        rule exists for. Mutation caught: `_fstring_weave` returning `""`
        unconditionally.
        """
        rows = _leak_rows(THE_DARWIN_ROW)

        assert len(rows) == 1
        assert rows[0]["species"] == "FAKE_PLATFORM_HOST_TEXT"
        assert rows[0]["oracle"] == "sys.platform"
        assert rows[0]["weave"] == "f-string"

    def test_the_linux_sibling_that_hands_the_path_over_as_a_value_is_clean(self):
        """THE ACQUITTAL IS THE WHOLE RULE, AND IT SITS THREE LINES ABOVE THE DEFECT.

        Same oracle faked, same `str(tmp_path / "project")` bound. It is portable
        because production returns what it was given, in whatever spelling the host
        uses. A rule that convicted this one would report 23 correct tests fleet-wide
        to catch one defect. Mutation caught: `unit_rows` dropping its
        `if not sites: return []` guard, which flags every platform fake that
        touches a sandbox.
        """
        assert _leak_rows(THE_LINUX_SIBLING) == []

    def test_the_two_units_differ_only_in_whether_the_path_was_woven(self):
        """ONE FLAGGED, ONE CLEAN, AND THE SOURCE DIFFERS IN THE WEAVE ALONE.

        Both fake an oracle, both bind `str(tmp_path / "project")`, both assert the
        subject's answer against it. Pinning the pair together is what stops a later
        edit from "fixing" one of them by widening the arm until both are rows, or
        narrowing it until neither is. Mutation caught: `unit_rows` returning `[]`
        unconditionally, which makes both answers equal.
        """
        flagged = _leak_rows(THE_DARWIN_ROW)
        clean = _leak_rows(THE_LINUX_SIBLING)

        assert bool(flagged) != bool(clean)
        assert "tmp_path" in THE_DARWIN_ROW and "tmp_path" in THE_LINUX_SIBLING
        assert "monkeypatch.setattr" in THE_DARWIN_ROW and "monkeypatch.setattr" in THE_LINUX_SIBLING


class TestTheLiteralIsTheGrammar:
    """An interpolation only claims a shape when a literal claims it."""

    def test_an_interpolation_with_no_literal_beside_it_is_not_a_grammar(self):
        """`f"{target}"` IS `str(target)` SPELLED LONGER.

        It carries no protocol, no separator and no prefix, so there is nothing for
        the other runner to disagree with. Counting it would turn every
        stringification of a sandbox path under a platform fake into a row.
        Mutation caught: `_has_text_literal` dropping its `and part.value`, which
        lets the empty literal an f-string always carries satisfy the arm.
        """
        source = """
        def test_the_path_is_echoed(monkeypatch, tmp_path):
            monkeypatch.setattr("sys.platform", "darwin")
            target = str(tmp_path / "project")
            assert echo(f"{target}") == target
        """

        assert _leak_rows(source) == []

    def test_a_literal_beside_the_interpolation_makes_it_a_row(self):
        """THE SAME UNIT, ONE PREFIX ADDED, AND NOW IT CLAIMS A SHAPE.

        `n` is the `lsof -Fn` field tag, and it is the half of the string that only
        makes sense on POSIX. Read beside the pin above, this is the arm's entire
        boundary. Mutation caught: `_has_text_literal` returning `False`
        unconditionally.
        """
        source = """
        def test_the_path_is_parsed(monkeypatch, tmp_path):
            monkeypatch.setattr("sys.platform", "darwin")
            target = str(tmp_path / "project")
            assert parse(f"n{target}") == target
        """

        rows = _leak_rows(source)

        assert len(rows) == 1
        assert rows[0]["weave"] == "f-string"


class TestBothHalvesAreRequired:
    """Each half is harmless alone; measured, only the pair is the species."""

    def test_text_woven_from_the_host_with_no_platform_fake_is_clean(self):
        """223 UNITS FLEET-WIDE DO EXACTLY THIS, AND EVERY ONE OF THEM IS CORRECT.

        A unit that never claims to be elsewhere is describing the machine it is
        really on, and the text it builds is its own. Flagging this is the measured
        difference between a rule with zero rows and a rule with 223. Mutation
        caught: `unit_rows` dropping its `if not fakes: return []` guard.
        """
        source = """
        def test_the_log_line_names_the_sandbox(tmp_path):
            target = str(tmp_path / "project")
            assert render(target) == f"cwd={target}"
        """

        assert _leak_rows(source) == []

    def test_a_platform_fake_with_no_woven_text_is_clean(self):
        """FORCING AN ORACLE IS NOT A DEFECT - IT IS HOW A CROSS-OS LANE IS WRITTEN.

        A unit that fakes darwin and then manufactures its whole fixture is the CURE
        this rule teaches, so an arm that could flag it would be teaching a rewrite
        into something it also flags. Mutation caught: `unit_rows` returning a row
        as soon as `bound` is non-empty, without consulting `weave_sites`.
        """
        source = """
        def test_the_parser_reads_the_lsof_field(monkeypatch, tmp_path):
            monkeypatch.setattr("sys.platform", "darwin")
            target = "/private/var/folders/aipass/pytest-project"
            (tmp_path / "unused").mkdir()
            assert parse(f"n{target}") == target
        """

        assert _leak_rows(source) == []


class TestTheFakeIsReadInEverySpellingThatShipped:
    """Every spelling below is a real one from the corpus, not a hypothetical."""

    @pytest.mark.parametrize(
        "fake",
        [
            'monkeypatch.setattr("sys.platform", "darwin")',
            'monkeypatch.setattr(sys, "platform", "darwin")',
            'monkeypatch.setattr(wire.sys, "platform", "darwin")',
            'patch("aipass.pkg.handlers.provider_wire.os.name", "nt").start()',
            'monkeypatch.setattr("platform.system", lambda: "Darwin")',
            'monkeypatch.setattr(mod.os, "name", "nt")',
        ],
    )
    def test_the_oracle_is_matched_as_a_suffix_so_a_module_prefixed_fake_counts(self, fake):
        """THE REAL SPELLINGS REACH THE ORACLE THROUGH THE MODULE UNDER TEST.

        @aipass writes `...provider_wire.os.name` and @devpulse writes
        `wire.sys.platform`; a reader keyed on the bare dotted name sees neither, and
        `SHALLOW_SANDBOX` measured 0 rows before the same class of alias fix.
        Mutation caught: `_names_an_oracle` dropping its `text.endswith` arm, which
        takes the module-prefixed spellings back to clean.
        """
        source = f"""
        def test_the_field_is_parsed(monkeypatch, tmp_path):
            {fake}
            target = str(tmp_path / "project")
            assert parse(f"n{{target}}") == target
        """

        assert len(_leak_rows(source)) == 1

    def test_a_decorator_can_carry_the_platform_fake(self):
        """THE FAKE DOES NOT HAVE TO BE IN THE BODY.

        `@patch("sys.platform", "darwin")` above the def is the same claim spelled
        one line higher, and a reader walking only the body would call the unit
        clean. It is read with no special case, because `decorator_list` is a field
        of the FunctionDef and `ast.walk` descends into it - an explicit second pass
        over the decorators was measured, killed no mutant, and was deleted.
        Mutation caught: `_faking_calls` walking `unit_node.body` instead of
        `unit_node`.
        """
        source = """
        @patch("sys.platform", "darwin")
        def test_the_field_is_parsed(_platform, tmp_path):
            target = str(tmp_path / "project")
            assert parse(f"n{target}") == target
        """

        assert len(_leak_rows(source)) == 1

    def test_a_fake_of_something_that_is_not_a_platform_oracle_is_not_a_fake(self):
        """PATCHING IS NOT THE SPECIES - PATCHING THE PLATFORM IS.

        Half this corpus patches something, and a rule that read any patch as a
        claim about the host would be back at 223 rows. Mutation caught:
        `_names_an_oracle` returning `True` unconditionally.
        """
        source = """
        def test_the_field_is_parsed(monkeypatch, tmp_path):
            monkeypatch.setattr("subprocess.run", _fake_run)
            target = str(tmp_path / "project")
            assert parse(f"n{target}") == target
        """

        assert _leak_rows(source) == []


class TestTheWeaveIsReadInEverySpelling:
    """Four ways to glue a host path to a literal, one species."""

    @pytest.mark.parametrize(
        ("expression", "spelling"),
        [
            ('f"n{target}"', "f-string"),
            ('"n" + target', "concat"),
            ('"n%s" % target', "percent"),
            ('"\\n".join(["p100", target])', "str.join"),
        ],
    )
    def test_every_glue_that_carries_a_literal_is_the_same_weave(self, expression, spelling):
        """THE SPECIES IS THE GLUING, NOT THE OPERATOR THAT DID IT.

        An arm that read only f-strings would be cured by rewriting the row as a
        concatenation, which changes nothing about what the other runner sees.
        Mutation caught: `_binop_weave` returning `""` unconditionally, which takes
        the concat and percent cases back to clean.
        """
        source = f"""
        def test_the_field_is_parsed(monkeypatch, tmp_path):
            monkeypatch.setattr("sys.platform", "darwin")
            target = str(tmp_path / "project")
            assert parse({expression}) == target
        """

        rows = _leak_rows(source)

        assert len(rows) == 1
        assert rows[0]["weave"] == spelling

    def test_a_concatenation_whose_literal_half_is_empty_claims_no_shape(self):
        """THE NON-EMPTY TEST EARNS ITS KEEP HERE, NOT ON f-STRINGS.

        CPython gives `f"{target}"` a `JoinedStr` holding one `FormattedValue`
        and no `Constant` at all, so the f-string arm is clean with or without the
        guard - measured, by a mutant that dropped it and killed nothing. It is
        `"" + target` that needs it: a concatenation whose literal half asserts no
        separator, no prefix and no line ending. Mutation caught:
        `_has_text_literal` dropping its `and part.value`.
        """
        source = """
        def test_the_path_is_echoed(monkeypatch, tmp_path):
            monkeypatch.setattr("sys.platform", "darwin")
            target = str(tmp_path / "project")
            assert echo("" + target) == target
        """

        assert _leak_rows(source) == []

    def test_a_join_on_an_empty_separator_claims_no_shape(self):
        """`"".join(...)` IS CONCATENATION WITH NO GRAMMAR IN IT.

        The separator is the literal, and an empty separator asserts nothing about
        line endings or path shape. Mutation caught: `_join_weave` dropping its
        `not func.value.value` guard.
        """
        source = """
        def test_the_field_is_parsed(monkeypatch, tmp_path):
            monkeypatch.setattr("sys.platform", "darwin")
            target = str(tmp_path / "project")
            assert parse("".join([target])) == target
        """

        assert _leak_rows(source) == []

    def test_a_unit_weaving_twice_is_one_row_not_two(self):
        """ONE UNIT IS ONE PLACE A READER HAS TO GO AND LOOK.

        Counting findings instead of units is how a score goes negative and how a
        report becomes unreadable - the pack's dedupe commitment, applied here at
        the point the row is built. Mutation caught: `unit_rows` returning one row
        per entry in `sites` instead of one row per unit.
        """
        source = """
        def test_two_fields_are_parsed(monkeypatch, tmp_path):
            monkeypatch.setattr("sys.platform", "darwin")
            target = str(tmp_path / "project")
            assert parse(f"n{target}") == target
            assert parse("n" + target) == target
        """

        assert len(_leak_rows(source)) == 1


class TestWhereTheHostPathCameFrom:
    """The sandbox half is delegated; the profile half is grown here."""

    def test_a_sandbox_path_carries_through_the_bindings_the_pack_already_reads(self):
        """THE SANDBOX ANSWER IS NOT RE-DERIVED, AND THIS IS THE PIN THAT SAYS SO.

        `platform_oracle_check.sandbox_names` is this pack's single answer to "which
        names hold a path under a temporary directory", and it resolves the two hops
        here - `tmp_path / "project"` into `Path`, then `str(...)` into `target`. A
        second, independently drifting copy in this rule is the duplication the
        campaign exists to kill. Mutation caught: `host_names` seeding from an empty
        set instead of `platform_oracle_check.sandbox_names(unit.node)`.
        """
        source = """
        def test_the_field_is_parsed(monkeypatch, tmp_path):
            monkeypatch.setattr("sys.platform", "darwin")
            sandbox = tmp_path / "project"
            target = str(sandbox)
            assert parse(f"n{target}") == target
        """

        assert len(_leak_rows(source)) == 1

    def test_a_profile_derived_path_carries_through_a_rebinding(self):
        """THE HOME DIRECTORY IS AS HOST-SHAPED AS THE SANDBOX, AND IS NOT A TEMPDIR.

        `sandbox_names` models temporary directories and does not model the profile,
        so the growth loop in `host_names` is what carries `Path.home()` through a
        second binding. Losing it makes every probe-derived weave read as clean.
        Mutation caught: `host_names` returning its seed set without running the
        `while changed` loop.
        """
        source = """
        def test_the_field_is_parsed(monkeypatch):
            monkeypatch.setattr("sys.platform", "darwin")
            root = Path.home() / "project"
            target = str(root)
            assert parse(f"n{target}") == target
        """

        assert len(_leak_rows(source)) == 1

    def test_a_path_the_test_wrote_down_itself_is_not_the_host(self):
        """THE CURE, AS @ai_mail LANDED IT, MUST READ CLEAN.

        A synthetic POSIX literal is DATA the parser reads, not a directory the host
        has to own, and it renders identically on every runner. A rule that still
        flagged the cured unit would have no fix to teach. Mutation caught:
        `_mentions` returning `True` unconditionally.
        """
        source = """
        def test_get_pid_cwd_darwin(monkeypatch):
            monkeypatch.setattr("sys.platform", "darwin")
            target = "/private/var/folders/aipass/pytest-project"
            assert parse(f"n{target}") == target
        """

        assert _leak_rows(source) == []


def _host_leak_project(root: Path) -> Path:
    """Three units, one of which leaks the host into its fake world.

    The two clean ones are clean for two DIFFERENT reasons - a synthetic literal,
    and a sandbox path handed over as a value - so losing either acquittal moves
    the measured number off 66.
    """
    return _write(
        root,
        "tests/test_wake.py",
        """
        def test_get_pid_cwd_darwin_cured(monkeypatch):
            monkeypatch.setattr("sys.platform", "darwin")
            target = "/private/var/folders/aipass/pytest-project"
            assert parse(f"n{target}") == target


        def test_get_pid_cwd_linux(monkeypatch, tmp_path):
            monkeypatch.setattr("sys.platform", "linux")
            target = str(tmp_path / "project")
            monkeypatch.setattr(os, "readlink", lambda p: target)
            assert read_cwd("100") == target


        def test_get_pid_cwd_darwin(monkeypatch, tmp_path):
            monkeypatch.setattr("sys.platform", "darwin")
            target = str(tmp_path / "project")
            assert parse(f"n{target}") == target
        """,
    )


class TestHostLeakBranchCheck:
    """What the branch lane reports, and what it refuses to report."""

    def test_the_rule_nominates_and_reports_one_hundred_while_scored_is_false(self, tmp_path):
        """ZERO ROWS MEANS THE ARM HAS NEVER BEEN OBSERVED CONVICTING.

        It measured 0 across 18 branches and 18,997 units, so its precision against
        a live positive is unmeasured - one reconstructed unit proves the arm fires,
        not that it is calibrated. Reporting 100 with the findings attached is what
        lets that measurement happen; reporting 100 and dropping the measured number
        would make the fallback indistinguishable from a rule that found nothing.
        Mutation caught: `"score": measured_score if SCORED else 100` becoming
        `"score": measured_score`.
        """
        _host_leak_project(tmp_path)

        result = host_leak_check.check_branch(str(tmp_path))

        assert result["score"] == 100
        assert result["measured_score"] == 66
        assert result["scored"] is False
        assert result["advisory"] is True
        assert len(result["violations"]) == 1
        assert any("REPORTING, NOT SCORING" in check["message"] for check in result["checks"])

    def test_the_measured_number_is_the_one_that_moves_when_a_row_lands(self, tmp_path):
        """THE REPORTED 100 MUST NOT BE THE ONLY NUMBER, OR NOTHING IS MEASURABLE.

        A shadow rule whose measured number is pinned to its reported one publishes
        nothing a calibration could read. Mutation caught: `measured_score` being
        assigned `100` rather than computed from `flagged`.
        """
        _write(
            tmp_path,
            "tests/test_clean.py",
            """
            def test_the_parser_reads_a_synthetic_line(monkeypatch):
                monkeypatch.setattr("sys.platform", "darwin")
                assert parse("n/private/var/x") == "/private/var/x"
            """,
        )

        clean = host_leak_check.check_branch(str(tmp_path))
        _host_leak_project(tmp_path)
        leaky = host_leak_check.check_branch(str(tmp_path))

        assert clean["measured_score"] == 100
        assert leaky["measured_score"] < clean["measured_score"]
        assert clean["score"] == leaky["score"] == 100

    def test_a_project_with_no_test_files_is_not_applicable_not_zero_quality(self, tmp_path):
        """ZERO TESTS MEASURED IS NOT ZERO QUALITY FOUND.

        Production that forces a platform is not a test that does, and a project with
        no tests has nothing this rule can read. Losing the early return here does
        not print a wrong number, it divides by zero. Mutation caught:
        `"not_applicable": True,` becoming `"not_applicable": False,`.
        """
        _write(tmp_path, "apps/probe.py", "import sys\n\n\ndef on_mac():\n    return sys.platform == 'darwin'\n")

        result = host_leak_check.check_branch(str(tmp_path))

        assert result["not_applicable"] is True
        assert result["passed"] is True
        assert "no test files found" in result["checks"][0]["message"]

    def test_a_project_whose_only_test_file_is_broken_is_not_reported_as_having_no_tests(self, tmp_path):
        """A BROKEN FILE MUST NEVER READ AS AN ABSENT ONE - the ordering pin.

        An unparseable file contributes no units, so it cannot lower a measured
        number, and silence about it reads as clean. Mutation caught: the `measured`
        ternary's `if not scanned.unparseable` becoming `if True`, which makes the
        two cases indistinguishable.
        """
        _write(tmp_path, "tests/test_broken.py", 'def test_broken(:\n    monkeypatch.setattr("sys.platform", "darwin")')

        result = host_leak_check.check_branch(str(tmp_path))

        assert result["not_applicable"] is True
        assert "no test files found" not in result["checks"][0]["message"]
        assert "unparseable" in result["checks"][0]["message"]
        assert any("broken.py" in check["message"] for check in result["checks"])

    def test_an_unparseable_test_file_is_named_beside_a_measured_result(self, tmp_path):
        """AN UNREAD FILE LEAKS NOTHING, so for this rule silence biases toward clean.

        The measured path has to append the unreadable line deliberately; dropping it
        leaves a healthy number and no hint a file was never read. That is the hole
        this pack's third disposition exists to close. Mutation caught:
        `checks.extend(unreadable)` becoming `checks.extend([])`.
        """
        _host_leak_project(tmp_path)
        _write(tmp_path, "tests/test_broken.py", 'def test_broken(:\n    monkeypatch.setattr("sys.platform", "darwin")')

        result = host_leak_check.check_branch(str(tmp_path))
        named = [check for check in result["checks"] if check["name"] == "Corpus readable"]

        assert result["measured_score"] == 66
        assert len(named) == 1
        assert "broken.py" in named[0]["message"]
        assert "NOT measured" in named[0]["message"]

    def test_only_twelve_flagged_units_are_named_and_the_rest_are_counted(self, tmp_path):
        """A CHECK MESSAGE PRINTING HUNDREDS OF LINES IS ONE NOBODY READS.

        Fourteen leaking units, twelve named, and the remainder stated as a number
        rather than dropped; the violations list itself is never truncated. Mutation
        caught: `MAX_REPORTED: int = 12` becoming `MAX_REPORTED: int = 24`.
        """
        units = "\n\n\n".join(
            f"def test_leak_{index:02d}(monkeypatch, tmp_path):\n"
            f'    monkeypatch.setattr("sys.platform", "darwin")\n'
            f'    target = str(tmp_path / "p{index:02d}")\n'
            f'    assert parse(f"n{{target}}") == target'
            for index in range(14)
        )
        _write(tmp_path, "tests/test_many_leaks.py", units)

        result = host_leak_check.check_branch(str(tmp_path))
        message = result["checks"][0]["message"]

        assert len(result["violations"]) == 14
        assert message.count("::test_leak_") == 12
        assert message.endswith("(+2 more)")
