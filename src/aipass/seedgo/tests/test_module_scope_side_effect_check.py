# =================== META ====================
# Name: test_module_scope_side_effect_check.py
# Description: module_scope_side_effect_check — a side effect a test file runs at collection
# Version: 1.0.1
# Created: 2026-09-25
# Modified: 2026-09-25
# =============================================

"""Tests for apps/handlers/aipass_standards/module_scope_side_effect_check.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(shared) — is_bypassed's own matching rules; tests/test_bypass.py
# seedgo: no-test-needed(shared) — writes at test time; tests/test_state_leak_check.py

from pathlib import Path

import pytest

from aipass.seedgo.apps.handlers.aipass_standards import module_scope_side_effect_check as checker

#: The model file for the whole per-item series.
MODEL = Path(__file__).resolve().parent / "test_readme_update.py"


def _verdict(tmp_path, body, name="test_specimen.py"):
    """(score, the one check's message) for a file planted under tests/."""
    tests = tmp_path / "tests"
    tests.mkdir(exist_ok=True)
    path = tests / name
    path.write_text(body, encoding="utf-8")
    result = checker.check_module(str(path))
    return result["score"], result["checks"][0]["message"]


#: @backup's tests/test_cli_routing.py at 7cbe39e5, lines 443, 444 and 457, verbatim.
SPECIMENS = """import sys
from pathlib import Path

_SECRETS_ROOT = str(Path.home() / ".secrets")
_SECRETS_TOUCHED: list[str] | None = None


def _secrets_audit_hook(event, args):
    if _SECRETS_TOUCHED is None:
        return


sys.addaudithook(_secrets_audit_hook)


def _secrets_watch():
    global _SECRETS_TOUCHED
    _SECRETS_TOUCHED = []
"""

#: One planted line per shape, each after the imports it needs.
IMPORTS = "import os\nimport sys\nimport pathlib\nfrom pathlib import Path\nfrom aipass import prax\n\n"
SHAPES = [
    ("audit_hook", "sys.addaudithook(print)"),
    ("host_read", "HOME = Path.home()"),
    ("host_read", "HOME = pathlib.Path.home()"),
    ("host_read", "HOME = os.path.expanduser('~')"),
    ("host_read", "HERE = os.getcwd()"),
    ("host_read", "HERE = Path.cwd()"),
    ("environ_write", "os.environ['X'] = '1'"),
    ("environ_write", "os.environ.setdefault('X', '1')"),
    ("environ_write", "del os.environ['X']"),
    ("environ_write", "os.putenv('X', '1')"),
    ("environ_write", "os.unsetenv('X')"),
    ("sys_modules_write", "sys.modules['x'] = None"),
    ("sys_modules_write", "sys.modules.pop('x', None)"),
    ("sys_modules_write", "del sys.modules['x']"),
    ("sys_path_write", "sys.path.insert(0, 'x')"),
    ("sys_path_write", "sys.path[0] = 'x'"),
    ("sys_path_write", "sys.path = []"),
    ("module_attr_write", "prax.logger = None"),
    ("module_attr_write", "setattr(prax, 'logger', None)"),
    ("cwd_change", "os.chdir('/')"),
]


class TestTheModelFilePasses:
    def test_the_model_file_scores_100(self):
        assert checker.check_module(str(MODEL))["score"] == 100


class TestThePlantedSpecimens:
    def test_backups_three_lines_are_each_convicted_by_shape(self, tmp_path):
        score, message = _verdict(tmp_path, SPECIMENS)
        assert score == 0
        assert 'test_specimen.py:4 host_read: _SECRETS_ROOT = str(Path.home() / ".secrets")' in message
        assert "test_specimen.py:5 global_recorder: _SECRETS_TOUCHED: list[str] | None = None" in message
        assert "test_specimen.py:13 audit_hook: sys.addaudithook(_secrets_audit_hook)" in message
        assert len(message.splitlines()) == 3

    def test_a_finding_carries_its_reason_and_the_cure(self, tmp_path):
        message = _verdict(tmp_path, IMPORTS + "os.chdir('/')\n")[1]
        assert message.endswith(
            "cwd_change: os.chdir('/') - moves the working directory for every test collected after it; "
            "move it into a fixture (monkeypatch / tmp_path) or into the test that needs it"
        )


class TestEveryShapeAtTopLevel:
    @pytest.mark.parametrize(("shape", "line"), SHAPES)
    def test_the_shape_is_convicted_and_named(self, tmp_path, shape, line):
        score, message = _verdict(tmp_path, IMPORTS + line + "\n")
        assert score == 0
        assert f"test_specimen.py:7 {shape}: {line} - " in message

    def test_a_name_imported_from_os_is_followed_to_os(self, tmp_path):
        body = "from os import environ as env, chdir\n\nenv['X'] = '1'\nchdir('/')\n"
        message = _verdict(tmp_path, body)[1]
        assert "test_specimen.py:3 environ_write" in message
        assert "test_specimen.py:4 cwd_change" in message

    def test_a_write_inside_a_top_level_try_is_convicted(self, tmp_path):
        body = IMPORTS + "try:\n    sys.path.append('x')\nexcept ImportError:\n    pass\n"
        assert "test_specimen.py:8 sys_path_write" in _verdict(tmp_path, body)[1]


class TestWhereModuleScopeReaches:
    def test_a_class_body_is_module_scope(self, tmp_path):
        body = IMPORTS + "class TestX:\n    HOME = Path.home()\n"
        assert "test_specimen.py:8 host_read" in _verdict(tmp_path, body)[1]

    def test_a_default_argument_is_module_scope(self, tmp_path):
        body = IMPORTS + "def test_x(home=Path.home()):\n    pass\n"
        assert "test_specimen.py:7 host_read" in _verdict(tmp_path, body)[1]

    def test_a_decorator_on_a_method_is_module_scope(self, tmp_path):
        body = IMPORTS + "import pytest\n\n\nclass TestX:\n    @pytest.mark.skipif(not Path.cwd(), reason='')\n"
        body += "    def test_x(self):\n        pass\n"
        assert "test_specimen.py:11 host_read" in _verdict(tmp_path, body)[1]


class TestWhatIsNotModuleScope:
    def test_the_same_calls_inside_a_test_body_pass(self, tmp_path):
        body = IMPORTS + "def test_x():\n" + "".join(f"    {line}\n" for _, line in SHAPES)
        assert _verdict(tmp_path, body) == (100, "Nothing at module scope outlives the file's own tests")

    def test_a_method_body_and_a_lambda_body_pass(self, tmp_path):
        body = IMPORTS + "HOME = lambda: Path.home()\n\n\nclass TestX:\n    def test_x(self):\n        os.chdir('/')\n"
        assert _verdict(tmp_path, body)[0] == 100

    def test_the_main_guard_is_not_run_at_import(self, tmp_path):
        body = IMPORTS + "if __name__ == '__main__':\n    os.chdir('/')\n    sys.path.insert(0, 'x')\n"
        assert _verdict(tmp_path, body)[0] == 100

    def test_the_main_guards_else_does_run_at_import(self, tmp_path):
        body = IMPORTS + "if __name__ == '__main__':\n    pass\nelse:\n    os.chdir('/')\n"
        assert "test_specimen.py:10 cwd_change" in _verdict(tmp_path, body)[1]

    def test_constants_and_pytestmark_pass(self, tmp_path):
        body = IMPORTS + "import pytest\n\nLIMIT = 3\nNAMES = ('a', 'b')\npytestmark = pytest.mark.slow\n"
        body += "local = object()\nlocal.attr = 1\n"
        assert _verdict(tmp_path, body)[0] == 100

    def test_a_global_only_read_in_a_function_is_no_recorder(self, tmp_path):
        body = "CACHE = None\n\n\ndef test_x():\n    global CACHE\n    assert CACHE is None\n"
        assert _verdict(tmp_path, body)[0] == 100


class TestWhichFilesAreJudged:
    def test_a_conftest_environ_write_is_not_judged(self, tmp_path):
        score, message = _verdict(tmp_path, IMPORTS + "os.environ['AIPASS_TEST_LOG_DIR'] = '/x'\n", "conftest.py")
        assert score == 100
        assert message == "Not judged: conftest.py module scope is the declared once-per-session harness"

    def test_a_helper_module_pytest_does_not_collect_is_not_judged(self, tmp_path):
        score, message = _verdict(tmp_path, IMPORTS + "os.chdir('/')\n", "helpers.py")
        assert (score, message) == (100, "Not judged: pytest does not collect this file as tests")

    def test_a_file_named_with_the_test_suffix_is_judged(self, tmp_path):
        assert _verdict(tmp_path, IMPORTS + "os.chdir('/')\n", "routing_test.py")[0] == 0
