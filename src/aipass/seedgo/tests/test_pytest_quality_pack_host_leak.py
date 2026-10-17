# =================== AIPass ====================
# Name: test_pytest_quality_pack_host_leak.py
# Description: pytest_quality pack, host_leak checker pins (split from test_pytest_quality_pack.py)
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-17
# =============================================

"""Tests for apps/handlers/pytest_quality_standards/host_leak_check.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(constant) — the content page prose, pytest_quality_standards/host_leak_content.py

from pathlib import Path

import pytest

from aipass.seedgo.apps.handlers.pytest_quality_standards import host_leak_check
from aipass.seedgo.tests.support_pytest_quality_pack import _unit, _write


# Every unit here is source text: a real `sys.platform` patch in this file would be the species the rule hunts.


def _leak_rows(source: str) -> list:
    """The host_leak rows over one written-out unit."""
    return host_leak_check.unit_rows(_unit(source))


#: The row this rule was written for: `sys.platform` forced to darwin, the fake `lsof` line built out of `tmp_path`.
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

#: Its portable sibling: the host path is handed to the subject as a value and comes back unchanged.
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
        """THE UNIT COULD NOT PARSE THE LINE THE UNIT ITSELF HAD WRITTEN."""
        rows = _leak_rows(THE_DARWIN_ROW)

        assert len(rows) == 1
        assert rows[0]["species"] == "FAKE_PLATFORM_HOST_TEXT"
        assert rows[0]["oracle"] == "sys.platform"
        assert rows[0]["weave"] == "f-string"

    def test_the_linux_sibling_that_hands_the_path_over_as_a_value_is_clean(self):
        """THE ACQUITTAL IS THE WHOLE RULE, AND IT SITS THREE LINES ABOVE THE DEFECT."""
        assert _leak_rows(THE_LINUX_SIBLING) == []

    def test_the_two_units_differ_only_in_whether_the_path_was_woven(self):
        """ONE FLAGGED, ONE CLEAN, AND THE SOURCE DIFFERS IN THE WEAVE ALONE."""
        flagged = _leak_rows(THE_DARWIN_ROW)
        clean = _leak_rows(THE_LINUX_SIBLING)

        assert bool(flagged) != bool(clean)
        assert "tmp_path" in THE_DARWIN_ROW and "tmp_path" in THE_LINUX_SIBLING
        assert "monkeypatch.setattr" in THE_DARWIN_ROW and "monkeypatch.setattr" in THE_LINUX_SIBLING


class TestTheLiteralIsTheGrammar:
    """An interpolation only claims a shape when a literal claims it."""

    def test_an_interpolation_with_no_literal_beside_it_is_not_a_grammar(self):
        """`f"{target}"` IS `str(target)` SPELLED LONGER."""
        source = """
        def test_the_path_is_echoed(monkeypatch, tmp_path):
            monkeypatch.setattr("sys.platform", "darwin")
            target = str(tmp_path / "project")
            assert echo(f"{target}") == target
        """

        assert _leak_rows(source) == []

    def test_a_literal_beside_the_interpolation_makes_it_a_row(self):
        """THE SAME UNIT, ONE PREFIX ADDED, AND NOW IT CLAIMS A SHAPE."""
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
        """223 UNITS FLEET-WIDE DO EXACTLY THIS, AND EVERY ONE OF THEM IS CORRECT."""
        source = """
        def test_the_log_line_names_the_sandbox(tmp_path):
            target = str(tmp_path / "project")
            assert render(target) == f"cwd={target}"
        """

        assert _leak_rows(source) == []

    def test_a_platform_fake_with_no_woven_text_is_clean(self):
        """FORCING AN ORACLE IS NOT A DEFECT - IT IS HOW A CROSS-OS LANE IS WRITTEN."""
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
        """THE REAL SPELLINGS REACH THE ORACLE THROUGH THE MODULE UNDER TEST."""
        source = f"""
        def test_the_field_is_parsed(monkeypatch, tmp_path):
            {fake}
            target = str(tmp_path / "project")
            assert parse(f"n{{target}}") == target
        """

        assert len(_leak_rows(source)) == 1

    def test_a_decorator_can_carry_the_platform_fake(self):
        """THE FAKE DOES NOT HAVE TO BE IN THE BODY."""
        source = """
        @patch("sys.platform", "darwin")
        def test_the_field_is_parsed(_platform, tmp_path):
            target = str(tmp_path / "project")
            assert parse(f"n{target}") == target
        """

        assert len(_leak_rows(source)) == 1

    def test_a_fake_of_something_that_is_not_a_platform_oracle_is_not_a_fake(self):
        """PATCHING IS NOT THE SPECIES - PATCHING THE PLATFORM IS."""
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
        """THE SPECIES IS THE GLUING, NOT THE OPERATOR THAT DID IT."""
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
        """THE NON-EMPTY TEST EARNS ITS KEEP HERE, NOT ON f-STRINGS."""
        source = """
        def test_the_path_is_echoed(monkeypatch, tmp_path):
            monkeypatch.setattr("sys.platform", "darwin")
            target = str(tmp_path / "project")
            assert echo("" + target) == target
        """

        assert _leak_rows(source) == []

    def test_a_join_on_an_empty_separator_claims_no_shape(self):
        """`"".join(...)` IS CONCATENATION WITH NO GRAMMAR IN IT."""
        source = """
        def test_the_field_is_parsed(monkeypatch, tmp_path):
            monkeypatch.setattr("sys.platform", "darwin")
            target = str(tmp_path / "project")
            assert parse("".join([target])) == target
        """

        assert _leak_rows(source) == []

    def test_a_unit_weaving_twice_is_one_row_not_two(self):
        """ONE UNIT IS ONE PLACE A READER HAS TO GO AND LOOK."""
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
        """THE SANDBOX ANSWER IS NOT RE-DERIVED, AND THIS IS THE PIN THAT SAYS SO."""
        source = """
        def test_the_field_is_parsed(monkeypatch, tmp_path):
            monkeypatch.setattr("sys.platform", "darwin")
            sandbox = tmp_path / "project"
            target = str(sandbox)
            assert parse(f"n{target}") == target
        """

        assert len(_leak_rows(source)) == 1

    def test_a_profile_derived_path_carries_through_a_rebinding(self):
        """THE HOME DIRECTORY IS AS HOST-SHAPED AS THE SANDBOX, AND IS NOT A TEMPDIR."""
        source = """
        def test_the_field_is_parsed(monkeypatch):
            monkeypatch.setattr("sys.platform", "darwin")
            root = Path.home() / "project"
            target = str(root)
            assert parse(f"n{target}") == target
        """

        assert len(_leak_rows(source)) == 1

    def test_a_path_the_test_wrote_down_itself_is_not_the_host(self):
        """THE CURE, AS @ai_mail LANDED IT, MUST READ CLEAN."""
        source = """
        def test_get_pid_cwd_darwin(monkeypatch):
            monkeypatch.setattr("sys.platform", "darwin")
            target = "/private/var/folders/aipass/pytest-project"
            assert parse(f"n{target}") == target
        """

        assert _leak_rows(source) == []


def _host_leak_project(root: Path) -> Path:
    """Three units, one of which leaks the host into its fake world."""
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
        """ZERO ROWS MEANS THE ARM HAS NEVER BEEN OBSERVED CONVICTING."""
        _host_leak_project(tmp_path)

        result = host_leak_check.check_branch(str(tmp_path))

        assert result["score"] == 100
        assert result["measured_score"] == 66
        assert result["scored"] is False
        assert result["advisory"] is True
        assert len(result["violations"]) == 1
        assert any("REPORTING, NOT SCORING" in check["message"] for check in result["checks"])

    def test_the_measured_number_is_the_one_that_moves_when_a_row_lands(self, tmp_path):
        """THE REPORTED 100 MUST NOT BE THE ONLY NUMBER, OR NOTHING IS MEASURABLE."""
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
        """ZERO TESTS MEASURED IS NOT ZERO QUALITY FOUND."""
        _write(tmp_path, "apps/probe.py", "import sys\n\n\ndef on_mac():\n    return sys.platform == 'darwin'\n")

        result = host_leak_check.check_branch(str(tmp_path))

        assert result["not_applicable"] is True
        assert result["passed"] is True
        assert "no test files found" in result["checks"][0]["message"]

    def test_a_project_whose_only_test_file_is_broken_is_not_reported_as_having_no_tests(self, tmp_path):
        """A BROKEN FILE MUST NEVER READ AS AN ABSENT ONE - the ordering pin."""
        _write(tmp_path, "tests/test_broken.py", 'def test_broken(:\n    monkeypatch.setattr("sys.platform", "darwin")')

        result = host_leak_check.check_branch(str(tmp_path))

        assert result["not_applicable"] is True
        assert "no test files found" not in result["checks"][0]["message"]
        assert "unparseable" in result["checks"][0]["message"]
        assert any("broken.py" in check["message"] for check in result["checks"])

    def test_an_unparseable_test_file_is_named_beside_a_measured_result(self, tmp_path):
        """AN UNREAD FILE LEAKS NOTHING, so for this rule silence biases toward clean."""
        _host_leak_project(tmp_path)
        _write(tmp_path, "tests/test_broken.py", 'def test_broken(:\n    monkeypatch.setattr("sys.platform", "darwin")')

        result = host_leak_check.check_branch(str(tmp_path))
        named = [check for check in result["checks"] if check["name"] == "Corpus readable"]

        assert result["measured_score"] == 66
        assert len(named) == 1
        assert "broken.py" in named[0]["message"]
        assert "NOT measured" in named[0]["message"]

    def test_only_twelve_flagged_units_are_named_and_the_rest_are_counted(self, tmp_path):
        """A CHECK MESSAGE PRINTING HUNDREDS OF LINES IS ONE NOBODY READS."""
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
