# =================== META ====================
# Name: test_no_product_call_check.py
# Description: no_product_call_check — crack class A, a test that reaches no product code
# Version: 1.0.2
# Created: 2026-09-22
# Modified: 2026-09-27
# =============================================

"""Tests for apps/handlers/aipass_standards/no_product_call_check.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(stdlib) — that ast.parse builds the tree it documents
# seedgo: no-test-needed(shared) — is_bypassed's own matching rules; tests/test_bypass.py
# seedgo: no-test-needed(shared) — applies_to_file's production/tests split; tests/test_applicability.py
# seedgo: no-test-needed(constant) — the prose of CURE; the line and name are asserted

from pathlib import Path

import pytest

from aipass.seedgo.apps.handlers.aipass_standards import no_product_call_check, skip_dirs
from aipass.seedgo.apps.modules import checklist

#: The model file for the whole per-item series. It passes, and it is the
#: shape every planted specimen below is a mutation of.
MODEL = Path(__file__).resolve().parent / "test_readme_update.py"

#: The import that makes a name the PRODUCT. Every acquittal below needs one.
IMPORT = "from aipass.seedgo.apps.modules import readme_update\n"


def _lines(source, shared=frozenset()):
    """Just the convicted line numbers, in order."""
    return [line for line, _name in no_product_call_check.scan(source, shared)]


def _names(source, shared=frozenset()):
    """Just the convicted test names, in order."""
    return [name for _line, name in no_product_call_check.scan(source, shared)]


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
        assert no_product_call_check.scan(MODEL.read_text(encoding="utf-8")) == []

    def test_the_model_file_scores_100_through_check_module(self):
        """And the same answer arrives through the pack's entry point."""
        assert no_product_call_check.check_module(str(MODEL))["score"] == 100


class TestThePlantedSpecimens:
    """One mutation of the real model per shape the rule names."""

    def test_a_library_test_is_convicted(self):
        """The @backup shape: pathspec matching a glob, no product symbol."""
        source = IMPORT + (
            "import pathspec\n"
            "def test_negation_re_includes():\n"
            "    spec = pathspec.PathSpec.from_lines('gitignore', ['*.log', '!a.log'])\n"
            "    assert spec.match_file('debug.log')\n"
        )
        assert _names(source) == ["test_negation_re_includes"]

    def test_a_stdlib_round_trip_is_convicted(self):
        """test_cli_routing.py:581 — StringIO returning what was written to it."""
        source = IMPORT + (
            "from io import StringIO\n"
            "def test_stringio_capture():\n"
            "    buf = StringIO()\n"
            "    buf.write('test output')\n"
            "    assert 'test' in buf.getvalue()\n"
        )
        assert _names(source) == ["test_stringio_capture"]

    def test_a_pytest_fixture_round_trip_is_convicted(self):
        """test_cli_routing.py:587 — print, then capsys. That tests pytest."""
        source = IMPORT + (
            "def test_capsys_available(capsys):\n    print('hello')\n    assert 'hello' in capsys.readouterr().out\n"
        )
        assert _names(source) == ["test_capsys_available"]

    def test_a_test_that_calls_the_product_is_clean(self):
        """The control. Same file, one product call, nothing convicted."""
        source = IMPORT + "def test_it():\n    assert readme_update.handle_command('readme', []) is True\n"
        assert no_product_call_check.scan(source) == []


class TestTheLineAndNameAreReported:
    """A finding a reader cannot walk to is not a finding."""

    def test_the_line_is_the_def(self):
        """Not the assert, not the class — the line you put the cursor on."""
        source = IMPORT + "\n\ndef test_nothing():\n    assert 1 == 1\n"
        assert _lines(source) == [4]

    def test_every_hit_is_named(self):
        """Three convicted tests produce three names, in line order."""
        source = IMPORT + (
            "def test_a():\n    assert 1 == 1\ndef test_b():\n    assert 2 == 2\ndef test_c():\n    assert 3 == 3\n"
        )
        assert _names(source) == ["test_a", "test_b", "test_c"]

    def test_a_non_test_function_is_never_judged(self):
        """The unit is a def test_*. A helper that touches nothing is a helper."""
        source = IMPORT + "def helper():\n    assert 1 == 1\n"
        assert no_product_call_check.scan(source) == []


class TestTheFiveWaysToNameTheProduct:
    """Each row of the rule's table, one test, because each cost a cut."""

    def test_an_import_binding_acquits(self):
        """The obvious half, and the only one the first cut had."""
        source = IMPORT + "def test_it():\n    assert readme_update is not None\n"
        assert no_product_call_check.scan(source) == []

    def test_a_module_level_constant_acquits(self):
        """SIMPLE_MODULES = [...] is how a parametrized test reaches the product.

        The import is three screens up and the test body never names it — the
        first cut convicted all 14 of @backup's parametrized routing tests.
        """
        source = IMPORT + (
            "import pytest\n"
            "SIMPLE_MODULES = [readme_update]\n"
            "@pytest.mark.parametrize('mod', SIMPLE_MODULES)\n"
            "def test_help_flag(mod):\n"
            "    assert mod.handle_command('x', ['--help']) is True\n"
        )
        assert no_product_call_check.scan(source) == []

    def test_a_constant_two_levels_deep_acquits(self):
        """The fixed point, not one pass: PAIRS -> MODULES -> the import."""
        source = IMPORT + (
            "MODULES = [readme_update]\nPAIRS = [(m, 'x') for m in MODULES]\ndef test_it():\n    assert PAIRS\n"
        )
        assert no_product_call_check.scan(source) == []

    def test_a_dotted_string_acquits(self):
        """import_module and mock.patch take the product by NAME, not by binding."""
        source = (
            "import importlib\n"
            "def test_it():\n"
            "    mod = importlib.import_module('aipass.seedgo.apps.modules.readme_update')\n"
            "    assert mod is not None\n"
        )
        assert no_product_call_check.scan(source) == []

    def test_a_probe_source_acquits(self):
        """A multi-line literal a subprocess runs is product code, written down."""
        source = (
            "import subprocess, sys, textwrap\n"
            "PROBE = textwrap.dedent('''\n    import aipass.seedgo\n    print('ok')\n    ''')\n"
            "def test_it():\n"
            "    assert subprocess.run([sys.executable, '-c', PROBE]).returncode == 0\n"
        )
        assert no_product_call_check.scan(source) == []

    def test_a_file_rooted_path_acquits(self):
        """GUARD_FILE = ROOT / 'apps' / ... — reading the guard is testing the guard."""
        source = (
            "from pathlib import Path\n"
            "GUARD = Path(__file__).resolve().parents[1] / 'apps' / 'handlers' / '__init__.py'\n"
            "def test_it():\n"
            "    assert 'inspect.stack()' in GUARD.read_text(encoding='utf-8')\n"
        )
        assert no_product_call_check.scan(source) == []

    def test_a_string_that_merely_contains_the_word_does_not_acquit(self):
        """'the aipass way' is prose. Only a dotted path or a source literal counts."""
        source = "def test_it():\n    assert 'the aipass way'.startswith('the')\n"
        assert _names(source) == ["test_it"]


class TestTheOwnApparatusAcquittal:
    """A control for the file's own detector is a meta-test, not a library test."""

    def test_a_same_file_helper_acquits(self):
        """@backup has nine of these and the reviewers flagged none of them."""
        source = (
            "def _inspect_stack_calls(src):\n    return []\n"
            "def test_a_docstring_mention_is_not_a_call():\n"
            '    assert _inspect_stack_calls(\'"""inspect.stack()"""\') == []\n'
        )
        assert no_product_call_check.scan(source) == []

    def test_a_same_file_fixture_acquits(self):
        """Requested by name in the signature, defined in this file."""
        source = (
            "import pytest\n"
            "@pytest.fixture\ndef guard():\n    return object()\n"
            "def test_it(guard):\n    assert guard is not None\n"
        )
        assert no_product_call_check.scan(source) == []

    def test_a_conftest_fixture_acquits(self):
        """The branch's shared apparatus, handed in as the names it defines."""
        source = "def test_it(tmp_repo):\n    assert tmp_repo\n"
        assert _names(source) == ["test_it"]
        assert no_product_call_check.scan(source, frozenset({"tmp_repo"})) == []

    def test_a_pytest_builtin_fixture_does_not_acquit(self):
        """tmp_path is not apparatus anybody in this repo wrote."""
        source = "def test_it(tmp_path):\n    assert tmp_path.exists()\n"
        assert _names(source) == ["test_it"]

    def test_mutually_recursive_helpers_terminate(self):
        """Without `seen`, @hooks' conftest recursed until the interpreter stopped."""
        source = "def a():\n    return b()\ndef b():\n    return a()\ndef test_it():\n    assert 1 == 1\n"
        assert _names(source) == ["test_it"]


class TestTheClassAcquittal:
    """A unittest method reaches the product through self.conn, which setUp built."""

    def test_a_method_of_a_reaching_class_is_acquitted(self):
        """@commons' test_commons.py was 67 hits before the class was consulted."""
        source = IMPORT + (
            "import unittest\n"
            "class TestIt(unittest.TestCase):\n"
            "    def setUp(self):\n        self.mod = readme_update\n"
            "    def test_raw(self):\n        self.assertTrue(True)\n"
        )
        assert no_product_call_check.scan(source) == []

    def test_a_method_of_a_class_that_reaches_nothing_is_convicted(self):
        """And those 29 that survive in @commons are real: raw SQL, no product."""
        source = (
            "import sqlite3, unittest\n"
            "class TestIt(unittest.TestCase):\n"
            "    def setUp(self):\n        self.conn = sqlite3.connect(':memory:')\n"
            "    def test_insert(self):\n"
            "        self.conn.execute('CREATE TABLE t (a)')\n"
            "        self.assertTrue(True)\n"
        )
        assert _names(source) == ["test_insert"]


class TestTheEntryPoint:
    """check_module's own paths, which scan never sees."""

    def test_the_conftest_is_never_judged(self, tmp_path):
        """It holds no tests, and it is what the tests are acquitted through."""
        path = _write(tmp_path, "def test_it():\n    assert 1 == 1\n", name="conftest.py")
        result = no_product_call_check.check_module(str(path))
        assert result["score"] == 100
        assert "conftest carries no tests" in result["checks"][0]["message"]

    def test_a_convicted_file_scores_zero(self, tmp_path):
        """No partial credit: the lane is pass/fail per file."""
        path = _write(tmp_path, "def test_it():\n    assert 1 == 1\n")
        assert no_product_call_check.check_module(str(path))["score"] == 0

    def test_a_missing_file_fails_by_name(self, tmp_path):
        """Not a crash, and not a silent pass."""
        result = no_product_call_check.check_module(str(tmp_path / "gone.py"))
        assert result["score"] == 0
        assert "File not found" in result["checks"][0]["message"]

    def test_an_unparseable_file_yields_nothing(self, tmp_path):
        """ruff already convicts the syntax error; a second verdict misdirects."""
        path = _write(tmp_path, "def test_it(:\n")
        assert no_product_call_check.check_module(str(path))["score"] == 100

    def test_the_conftest_is_read_from_the_file_s_own_directory(self, tmp_path):
        """The acquittal has to find the real conftest, not a guessed one."""
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "conftest.py").write_text(
            "import pytest\n@pytest.fixture\ndef tmp_repo():\n    return 1\n", encoding="utf-8"
        )
        path = _write(tmp_path, "def test_it(tmp_repo):\n    assert tmp_repo\n")
        no_product_call_check.shared_fixtures.cache_clear()
        assert no_product_call_check.check_module(str(path))["score"] == 100

    def test_a_missing_conftest_is_an_empty_set_not_a_crash(self, tmp_path):
        """Most directories under tests/ have no conftest of their own."""
        no_product_call_check.shared_fixtures.cache_clear()
        assert no_product_call_check.shared_fixtures(str(tmp_path / "nope.py")) == frozenset()


class TestEveryHitRidesOnOneCheck:
    """checklist._format_failure prints the FIRST failed check and hides the rest."""

    def test_three_hits_arrive_on_a_single_check(self, tmp_path):
        """Three checks would show one test and '(+2 more)'."""
        path = _write(
            tmp_path,
            "def test_a():\n    assert 1 == 1\ndef test_b():\n    assert 2 == 2\ndef test_c():\n    assert 3 == 3\n",
        )
        checks = no_product_call_check.check_module(str(path))["checks"]
        assert len(checks) == 1
        assert checks[0]["message"].count("reaches no aipass code") == 3

    @pytest.fixture(autouse=True)
    def _let_tmp_path_be_audited(self, monkeypatch):
        """tmp_path lives under a temp root the checklist skips by default."""
        monkeypatch.setattr(skip_dirs, "_get_temp_roots", lambda: [])

    def test_the_command_prints_every_hit(self, tmp_path, capsys):
        """The message survives the formatter the hook actually calls."""
        path = _write(tmp_path, "def test_a():\n    assert 1 == 1\ndef test_b():\n    assert 2 == 2\n")

        checklist.handle_command("checklist", [str(path)])

        out = capsys.readouterr().out
        assert "[FAIL] — no_product_call" in out
        assert "test_a" in out
        assert "test_b" in out


class TestItDeclaresItsScope:
    """The two constants both lanes consult before they run it."""

    def test_it_applies_to_tests_only(self):
        """Production code has no def test_*; running it there is noise."""
        assert no_product_call_check.APPLIES_TO == "tests"

    def test_it_reports_per_file(self):
        """A verdict about one test belongs on the file that holds it."""
        assert no_product_call_check.AUDIT_SCOPE == "all_files"


class TestTheBypass:
    """Every checker in the pack answers to .seedgo/bypass.json."""

    @pytest.mark.parametrize("rules", [[{"standard": "no_product_call"}]])
    def test_a_bypassed_file_passes(self, tmp_path, rules):
        """A deliberate exception is not a violation."""
        path = _write(tmp_path, "def test_it():\n    assert 1 == 1\n")
        assert (
            no_product_call_check.check_module(
                str(path), bypass_rules=[{**rule, "file": str(tmp_path)} for rule in rules]
            )["score"]
            == 100
        )
