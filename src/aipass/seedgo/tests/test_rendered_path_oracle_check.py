# =================== AIPass ====================
# Name: test_rendered_path_oracle_check.py
# Description: rendered_path_oracle_check — a whole path asserted against rendered console output
# Version: 1.0.0
# Created: 2026-10-13
# Modified: 2026-10-13
# =============================================

"""Tests for apps/handlers/aipass_standards/rendered_path_oracle_check.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(shared) — is_bypassed's own matching rules; tests/test_bypass.py
# seedgo: no-test-needed(shared) — applies_to_file's production/tests split; tests/test_applicability.py
# seedgo: no-test-needed(constant) — the prose of WHY and CURE; their presence in the message is asserted

import pytest

from aipass.seedgo.apps.handlers.aipass_standards import rendered_path_oracle_check, skip_dirs
from aipass.seedgo.apps.modules import checklist

#: The specimen, verbatim in shape: @aipass test_aipass_main.py before its cure (PR #787).
SPECIMEN = """
def test_a_crash_whose_log_cannot_be_written(tmp_path, monkeypatch, capsys):
    log_home = tmp_path / "system_logs"
    denied = PermissionError(13, "Permission denied", str(log_home))
    result = main()
    _out, err = capsys.readouterr()
    assert result == 1
    assert f"(this crash could not be written to the log: [Errno 13] Permission denied: '{log_home}')" in err
"""


def _lines(source):
    """Just the convicted assert lines, in order."""
    return [line for line, _name, _path, _hay in rendered_path_oracle_check.scan(source)]


def _test(*body, params="tmp_path, capsys"):
    """One test function wrapped around the given body lines."""
    return f"def test_it({params}):\n" + "".join(f"    {line}\n" for line in body)


def _write(tmp_path, body, name="test_specimen.py"):
    """A file on disk under a tests/ directory, which is what the rule scopes to."""
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir(exist_ok=True)
    path = tests_dir / name
    path.write_text(body, encoding="utf-8")
    return path


class TestTheSpecimenIsConvicted:
    """The exact shape that went red on Windows and macOS CI."""

    def test_the_specimen_is_convicted_on_its_assert_line(self):
        """One finding, on the f-string assert, naming the path and the haystack."""
        assert rendered_path_oracle_check.scan(SPECIMEN) == [
            (8, "test_a_crash_whose_log_cannot_be_written", "log_home", "err")
        ]

    def test_the_specimen_scores_zero_through_check_module(self, tmp_path):
        """And the same answer arrives through the pack's entry point."""
        assert rendered_path_oracle_check.check_module(str(_write(tmp_path, SPECIMEN)))["score"] == 0


class TestEveryPathShapeConvicts:
    """Each needle spelling of a path, against the same captured err."""

    @pytest.mark.parametrize(
        "bind, rendered",
        [
            ("pass", "tmp_path"),
            ("p = tmp_path", "p"),
            ("p = tmp_path / 'a' / 'b'", "p"),
            ("p = tmp_path.joinpath('a')", "p"),
            ("p = (tmp_path / 'a').resolve()", "p"),
            ("p = tmp_path_factory.mktemp('d')", "p"),
            ("p = Path('/x/y')", "p"),
            ("p = pathlib.PurePath('x')", "p"),
            ("p = str(tmp_path / 'a')", "p"),
            ("p = tmp_path / 'a'", "str(p)"),
            ("p = tmp_path / 'a'", "p.parent"),
            ("p = tmp_path / 'a'", "p!r"),
        ],
    )
    def test_a_rendered_path_against_err_convicts(self, bind, rendered):
        """Every spelling the rule names is a path."""
        source = _test(bind, "_out, err = capsys.readouterr()", f"assert f'at {{{rendered}}}' in err")
        assert _lines(source) == [4]


class TestEveryHaystackShapeConvicts:
    """Each spelling of captured console output, against the same path f-string."""

    @pytest.mark.parametrize(
        "capture, haystack",
        [
            ("out, err = capsys.readouterr()", "out"),
            ("out, err = capfd.readouterr()", "err"),
            ("captured = capsys.readouterr()", "captured.out"),
            ("captured = capsys.readouterr()", "captured.err"),
            ("pass", "capsys.readouterr().err"),
            ("err = capsys.readouterr().err", "err"),
            ("captured = capsys.readouterr(); text = captured.out", "text"),
            ("result = CliRunner().invoke(cli, [])", "result.output"),
            ("runner = CliRunner(); result = runner.invoke(cli, [])", "result.stdout"),
            ("result = subprocess.run(['x'], capture_output=True, text=True, encoding='utf-8')", "result.stderr"),
        ],
    )
    def test_a_path_fstring_against_captured_output_convicts(self, capture, haystack):
        """Every haystack the rule names is rendered output."""
        source = _test("p = tmp_path / 'a'", capture, f"assert f'at {{p}}' in {haystack}")
        assert _lines(source) == [4]

    @pytest.mark.parametrize(
        "compare",
        ["f'at {p}' not in err", "f'at {p}' == err", "err == f'at {p}'", "err != f'at {p}'"],
    )
    def test_not_in_and_equality_convict_too(self, compare):
        """The operator does not change what the needle holds."""
        source = _test("p = tmp_path / 'a'", "_out, err = capsys.readouterr()", f"assert {compare}")
        assert _lines(source) == [4]


class TestTheCureIsAcquitted:
    """What the brief calls the cure, and the shapes that never render a path."""

    def test_the_cured_specimen_asserting_the_name_is_acquitted(self):
        """The words without the path, and the path's name: stable on every OS."""
        source = SPECIMEN.replace(
            "assert f\"(this crash could not be written to the log: [Errno 13] Permission denied: '{log_home}')\" in err",
            'assert "Permission denied:" in err\n    assert "system_logs" in err',
        )
        assert _lines(source) == []

    @pytest.mark.parametrize("attr", ["name", "stem", "suffix"])
    def test_a_path_name_stem_or_suffix_is_the_cure(self, attr):
        """Mutant: .name read as a path -> this pin goes red."""
        source = _test("p = tmp_path / 'a.txt'", "_out, err = capsys.readouterr()", f"assert f'at {{p.{attr}}}' in err")
        assert _lines(source) == []

    def test_an_fstring_with_no_path_is_acquitted(self):
        """A rendered count or word is not a path."""
        source = _test("n = 3", "_out, err = capsys.readouterr()", "assert f'{n} files' in err")
        assert _lines(source) == []

    @pytest.mark.parametrize("haystack", ["str(exc.value)", "result", "message"])
    def test_a_path_compared_against_what_nothing_rendered_is_acquitted(self, haystack):
        """Mutant: any haystack accepted -> this pin goes red."""
        source = _test(
            "p = tmp_path / 'a'",
            "result = run(p)",
            "message = result['error']",
            f"assert f'Not a file: {{p}}' in {haystack}",
        )
        assert _lines(source) == []

    def test_a_name_not_bound_in_this_test_is_not_a_path(self):
        """tmp_path that is not this test's parameter is somebody else's name."""
        source = _test("_out, err = capsys.readouterr()", "assert f'at {tmp_path}' in err", params="capsys")
        assert _lines(source) == []


class TestHeldShapesAreNotJudged:
    """Shapes the AST cannot settle in one function, left out rather than guessed."""

    def test_an_fstring_bound_to_a_name_first_is_held(self):
        """msg = f'...{p}' then msg in err needs a flow the rule does not follow."""
        source = _test("p = tmp_path / 'a'", "msg = f'at {p}'", "_out, err = capsys.readouterr()", "assert msg in err")
        assert _lines(source) == []

    def test_a_transformed_haystack_is_held(self):
        """The specimen's own wrap cure collapses whitespace; that value is not followed."""
        source = _test(
            "p = tmp_path / 'a'",
            "_out, err = capsys.readouterr()",
            "said = ' '.join(err.split())",
            "assert f'{p}' in said",
        )
        assert _lines(source) == []


class TestTheVerdict:
    """What check_module returns, and what it says."""

    def test_a_clean_file_scores_100(self, tmp_path):
        """No rendered path, no finding."""
        path = _write(tmp_path, _test("_out, err = capsys.readouterr()", "assert 'ok' in err"))
        assert rendered_path_oracle_check.check_module(str(path))["score"] == 100

    def test_a_missing_file_fails_by_name(self, tmp_path):
        """Not a crash, and not a silent pass."""
        result = rendered_path_oracle_check.check_module(str(tmp_path / "gone.py"))
        assert result["score"] == 0
        assert "File not found" in result["checks"][0]["message"]

    def test_an_unparseable_file_yields_nothing(self, tmp_path):
        """ruff already convicts the syntax error; a second verdict misdirects."""
        path = _write(tmp_path, "def test_it(:\n")
        assert rendered_path_oracle_check.check_module(str(path))["score"] == 100

    def test_the_message_names_the_line_both_fragilities_and_the_cure(self, tmp_path):
        """A finding that does not say what to do is a chore, not a cure."""
        message = rendered_path_oracle_check.check_module(str(_write(tmp_path, SPECIMEN)))["checks"][0]["message"]
        assert "test_specimen.py:8 test_a_crash_whose_log_cannot_be_written" in message
        assert "WRAP" in message
        assert "REPR" in message
        assert rendered_path_oracle_check.CURE in message

    def test_two_offending_asserts_are_two_findings_on_one_check(self, tmp_path):
        """One violation per assert; checklist._format_failure shows only the first check."""
        body = _test(
            "p = tmp_path / 'a'", "out, err = capsys.readouterr()", "assert f'{p}' in out", "assert f'{p}' in err"
        )
        checks = rendered_path_oracle_check.check_module(str(_write(tmp_path, body)))["checks"]
        assert len(checks) == 1
        assert checks[0]["message"].count("test_specimen.py:") == 2


class TestTheCommandPrintsTheHit:
    """The message survives the formatter the hook actually calls."""

    @pytest.fixture(autouse=True)
    def _let_tmp_path_be_audited(self, monkeypatch):
        """tmp_path lives under a temp root the checklist skips by default."""
        monkeypatch.setattr(skip_dirs, "_get_temp_roots", lambda: [])

    def test_the_checklist_fails_the_specimen_by_name(self, tmp_path, capsys):
        """drone @seedgo checklist on the specimen names this standard."""
        checklist.handle_command("checklist", [str(_write(tmp_path, SPECIMEN))])

        out = capsys.readouterr().out
        assert "[FAIL] — rendered_path_oracle" in out
        assert "test_a_crash_whose_log_cannot_be_written" in out


class TestItDeclaresItsScope:
    """The three constants the lanes consult before they run it."""

    def test_it_applies_to_tests_only(self):
        """Production code has no def test_*; running it there is noise."""
        assert rendered_path_oracle_check.APPLIES_TO == "tests"

    def test_it_reports_per_file(self):
        """A verdict about an assert belongs on the file that holds it."""
        assert rendered_path_oracle_check.AUDIT_SCOPE == "all_files"

    def test_it_lands_advisory_while_the_fleet_carries_convictions(self):
        """Nine asserts outside the specimen convicted on arrival; no branch's average may move."""
        assert rendered_path_oracle_check.ADVISORY is True


class TestTheBypass:
    """Every checker in the pack answers to .seedgo/bypass.json."""

    def test_a_bypassed_file_passes(self, tmp_path):
        """A deliberate exception is not a violation."""
        path = _write(tmp_path, SPECIMEN)
        rules = [{"standard": "rendered_path_oracle", "file": str(tmp_path)}]
        assert rendered_path_oracle_check.check_module(str(path), bypass_rules=rules)["score"] == 100

    def test_a_rule_without_a_standard_does_not_silence_a_failing_check(self, tmp_path):
        """A blank is a blank (owner, 2026-09-25)."""
        path = _write(tmp_path, SPECIMEN)
        assert rendered_path_oracle_check.check_module(str(path), bypass_rules=[{"file": str(tmp_path)}])["score"] == 0
