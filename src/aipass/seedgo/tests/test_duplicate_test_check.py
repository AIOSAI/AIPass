# =================== META ====================
# Name: test_duplicate_test_check.py
# Description: duplicate_test_check — crack class B, a test another test already covers
# Version: 1.0.2
# Created: 2026-09-22
# Modified: 2026-09-27
# =============================================

"""Tests for apps/handlers/aipass_standards/duplicate_test_check.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(stdlib) — that ast.dump omits lineno unless asked; CPython's contract
# seedgo: no-test-needed(shared) — is_bypassed's own matching rules; tests/test_bypass.py
# seedgo: no-test-needed(shared) — applies_to_file's production/tests split; tests/test_applicability.py
# seedgo: no-test-needed(constant) — the prose of CURE; the relation and the other test are asserted

from pathlib import Path

import pytest

from aipass.seedgo.apps.handlers.aipass_standards import duplicate_test_check, skip_dirs
from aipass.seedgo.apps.modules import checklist

#: The model file for the whole per-item series. It passes, and it is the
#: shape every planted specimen below is a mutation of.
MODEL = Path(__file__).resolve().parent / "test_readme_update.py"


def _rows(source):
    """(line, name, relation, the other test) for each finding."""
    return duplicate_test_check.scan(source)


def _names(source):
    """Just the convicted test names, in line order."""
    return [name for _line, name, _relation, _other in _rows(source)]


def _relations(source):
    """Just the relations, in line order — CLONE or SUBSUMED."""
    return [relation for _line, _name, relation, _other in _rows(source)]


def _write(tmp_path, body, name="test_specimen.py"):
    """A file on disk under a tests/ directory, which is what the rule scopes to."""
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir(exist_ok=True)
    path = tests_dir / name
    path.write_text(body, encoding="utf-8")
    return path


class TestTheModelFilePasses:
    """The template's own model is the floor: if it fails, the rule is wrong."""

    def test_the_model_file_is_clean(self):
        """tests/test_readme_update.py convicts nothing."""
        assert duplicate_test_check.scan(MODEL.read_text(encoding="utf-8")) == []

    def test_the_model_file_scores_100_through_check_module(self):
        """And the same answer arrives through the pack's entry point."""
        assert duplicate_test_check.check_module(str(MODEL))["score"] == 100


class TestThePlantedSpecimens:
    """One specimen per shape, each taken from a row the reviewers confirmed."""

    def test_a_clone_is_convicted(self):
        """test_dead_cwd_imports.py:828 — 'line-for-line the same assertion as 469'."""
        source = (
            "def test_pseudo_frame_caller_is_allowed(guard):\n"
            "    assert _fence_verdict('<string>', guard) is None\n"
            "def test_the_mint_guard_permits_a_pseudo_frame(guard):\n"
            "    assert _fence_verdict('<string>', guard) is None\n"
        )
        assert _names(source) == ["test_the_mint_guard_permits_a_pseudo_frame"]
        assert _relations(source) == [duplicate_test_check.CLONE]

    def test_a_subsumed_test_is_convicted(self):
        """test_cli_routing.py:250 — 'identical claim to line 163'."""
        source = (
            "def test_introspection_exists(mod):\n"
            "    assert hasattr(mod, 'print_introspection')\n"
            "    assert callable(mod.print_introspection)\n"
            "def test_print_introspection_exists(mod):\n"
            "    assert callable(mod.print_introspection)\n"
        )
        assert _names(source) == ["test_print_introspection_exists"]
        assert _relations(source) == [duplicate_test_check.SUBSUMED]

    def test_two_tests_that_pin_different_things_are_clean(self):
        """The control. Same shape, different constant, nothing convicted."""
        source = "def test_a():\n    assert f('*.log')\ndef test_b():\n    assert f('*.txt')\n"
        assert duplicate_test_check.scan(source) == []


class TestTheRestrictionOnTheExtras:
    """The whole of B2 is what Y is allowed to add beyond X."""

    def test_a_world_changing_extra_acquits(self):
        """Both reviewers called this @backup pair SOUND, and it nearly convicted.

        The second writes a .backupignore first, so the two tests state
        different PRECONDITIONS — 'no file at all' and 'a file that omits tmp'.
        A superset of statements is not a superset of claims.
        """
        source = (
            "def test_floor_applies_with_no_backupignore(tmp_path):\n"
            "    spec = load_spec(str(tmp_path))\n"
            "    assert is_ignored('a.tmp', spec)\n"
            "def test_floor_applies_when_the_file_never_names_tmp(tmp_path):\n"
            "    (tmp_path / '.backupignore').write_text('*.log\\n', encoding='utf-8')\n"
            "    spec = load_spec(str(tmp_path))\n"
            "    assert is_ignored('a.tmp', spec)\n"
            "    assert is_ignored('app.log', spec)\n"
        )
        assert duplicate_test_check.scan(source) == []

    def test_an_assert_only_extra_convicts(self):
        """An assert reads the world; it does not build a different one."""
        source = (
            "def test_small(tmp_path):\n"
            "    spec = load_spec(str(tmp_path))\n"
            "    assert is_ignored('a.tmp', spec)\n"
            "def test_big(tmp_path):\n"
            "    spec = load_spec(str(tmp_path))\n"
            "    assert is_ignored('a.tmp', spec)\n"
            "    assert is_ignored('b.tmp', spec)\n"
        )
        assert _names(source) == ["test_small"]

    def test_a_call_free_binding_extra_convicts(self):
        """`ignore = project / '.backupignore'` changes nothing and reads nothing."""
        source = (
            "def test_small(project):\n"
            "    assert create_backup_dir(project)\n"
            "def test_big(project):\n"
            "    ignore = project / '.backupignore'\n"
            "    assert create_backup_dir(project)\n"
            "    assert ignore\n"
        )
        assert _names(source) == ["test_small"]

    def test_a_binding_whose_value_calls_acquits(self):
        """`conn = connect(db)` builds the world even though it is an assignment."""
        source = (
            "def test_small(db):\n"
            "    assert rows(db)\n"
            "def test_big(db):\n"
            "    conn = connect(db)\n"
            "    assert rows(db)\n"
            "    assert conn\n"
        )
        assert duplicate_test_check.scan(source) == []

    def test_a_with_block_extra_acquits(self):
        """A `with patch(...)` around the shared asserts is a different world."""
        source = (
            "def test_small():\n"
            "    assert run() is True\n"
            "def test_big():\n"
            "    with patch('aipass.x.y'):\n        pass\n"
            "    assert run() is True\n"
        )
        assert duplicate_test_check.scan(source) == []


class TestConstantsAreKept:
    """Blanking them convicted 345 files with 2,415 hits."""

    def test_a_different_constant_is_a_different_claim(self):
        """'*.log' and '*.txt' say different things about the product."""
        source = (
            "def test_a():\n    lines = ['*.log']\n    assert match(lines, 'x.log')\n"
            "def test_b():\n    lines = ['*.txt']\n    assert match(lines, 'x.txt')\n"
        )
        assert duplicate_test_check.scan(source) == []

    def test_a_different_identifier_is_a_different_claim(self):
        """Two tests calling two product functions are two tests."""
        source = "def test_a():\n    assert load_spec(p)\ndef test_b():\n    assert filter_paths(p)\n"
        assert duplicate_test_check.scan(source) == []


class TestTheDocstringIsDropped:
    """Two tests that differ only in their prose are the same test."""

    def test_different_prose_still_convicts(self):
        """The prose is worth having. It is not a second pin."""
        source = (
            "def test_a():\n    '''One reading.'''\n    assert run() is True\n"
            "def test_b():\n    '''A completely different reading.'''\n    assert run() is True\n"
        )
        assert _names(source) == ["test_b"]

    def test_a_body_that_is_only_a_docstring_is_never_judged(self):
        """An empty test is a different defect and a different checker's."""
        source = "def test_a():\n    '''Nothing yet.'''\ndef test_b():\n    '''Nothing yet either.'''\n"
        assert duplicate_test_check.scan(source) == []


class TestWhichOneIsTheFinding:
    """A verdict that moves when an unrelated line moves is not a verdict."""

    def test_the_first_by_line_is_the_original(self):
        """Every later copy is the finding, and the original is named."""
        source = "def test_a():\n    assert run()\ndef test_b():\n    assert run()\ndef test_c():\n    assert run()\n"
        assert _names(source) == ["test_b", "test_c"]
        assert [other for _l, _n, _r, other in _rows(source)] == ["test_a", "test_a"]

    def test_a_clone_is_never_also_charged_as_subsumed(self):
        """One defect, one row. Two would print the same test under two names."""
        source = (
            "def test_a():\n    assert run()\n    assert ok()\n"
            "def test_b():\n    assert run()\n    assert ok()\n"
            "def test_c():\n    assert run()\n"
        )
        assert len(_rows(source)) == 2
        assert _relations(source) == [duplicate_test_check.CLONE, duplicate_test_check.SUBSUMED]


class TestTheEntryPoint:
    """check_module's own paths, which scan never sees."""

    def test_a_convicted_file_scores_zero(self, tmp_path):
        """No partial credit: the lane is pass/fail per file."""
        path = _write(tmp_path, "def test_a():\n    assert run()\ndef test_b():\n    assert run()\n")
        assert duplicate_test_check.check_module(str(path))["score"] == 0

    def test_a_missing_file_fails_by_name(self, tmp_path):
        """Not a crash, and not a silent pass."""
        result = duplicate_test_check.check_module(str(tmp_path / "gone.py"))
        assert result["score"] == 0
        assert "File not found" in result["checks"][0]["message"]

    def test_an_unparseable_file_yields_nothing(self, tmp_path):
        """ruff already convicts the syntax error; a second verdict misdirects."""
        path = _write(tmp_path, "def test_it(:\n")
        assert duplicate_test_check.check_module(str(path))["score"] == 100

    def test_the_message_names_the_test_that_already_covers_it(self, tmp_path):
        """A finding that does not say where to look is a chore, not a cure."""
        path = _write(tmp_path, "def test_a():\n    assert run()\ndef test_b():\n    assert run()\n")
        message = duplicate_test_check.check_module(str(path))["checks"][0]["message"]
        assert "test_b" in message
        assert "test_a" in message


class TestEveryHitRidesOnOneCheck:
    """checklist._format_failure prints the FIRST failed check and hides the rest."""

    @pytest.fixture(autouse=True)
    def _let_tmp_path_be_audited(self, monkeypatch):
        """tmp_path lives under a temp root the checklist skips by default."""
        monkeypatch.setattr(skip_dirs, "_get_temp_roots", lambda: [])

    def test_two_hits_arrive_on_a_single_check(self, tmp_path):
        """Two checks would show one test and '(+1 more)'."""
        path = _write(
            tmp_path,
            "def test_a():\n    assert run()\ndef test_b():\n    assert run()\ndef test_c():\n    assert run()\n",
        )
        checks = duplicate_test_check.check_module(str(path))["checks"]
        assert len(checks) == 1
        assert checks[0]["message"].count(duplicate_test_check.CLONE) == 2

    def test_the_command_prints_every_hit(self, tmp_path, capsys):
        """The message survives the formatter the hook actually calls."""
        path = _write(tmp_path, "def test_a():\n    assert run()\ndef test_b():\n    assert run()\n")

        checklist.handle_command("checklist", [str(path)])

        out = capsys.readouterr().out
        assert "[FAIL] — duplicate_test" in out
        assert "test_b" in out


class TestItDeclaresItsScope:
    """The two constants both lanes consult before they run it."""

    def test_it_applies_to_tests_only(self):
        """Production code has no def test_*; running it there is noise."""
        assert duplicate_test_check.APPLIES_TO == "tests"

    def test_it_reports_per_file(self):
        """A verdict about two tests in one file belongs on that file."""
        assert duplicate_test_check.AUDIT_SCOPE == "all_files"


class TestTheBypass:
    """Every checker in the pack answers to .seedgo/bypass.json."""

    @pytest.mark.parametrize("rules", [[{"standard": "duplicate_test"}]])
    def test_a_bypassed_file_passes(self, tmp_path, rules):
        """A deliberate exception is not a violation."""
        path = _write(tmp_path, "def test_a():\n    assert run()\ndef test_b():\n    assert run()\n")
        assert (
            duplicate_test_check.check_module(
                str(path), bypass_rules=[{**rule, "file": str(tmp_path)} for rule in rules]
            )["score"]
            == 100
        )
