# =================== META ====================
# Name: test_module_scope_side_effect_check.py
# Description: module_scope_side_effect_check — a side effect a test file runs at collection
# Version: 1.1.1
# Created: 2026-09-25
# Modified: 2026-10-11
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


def _verdict_at(tmp_path, body, relative):
    """(score, the one check's message) for a file planted at a path under tmp_path."""
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    result = checker.check_module(str(path))
    return result["score"], result["checks"][0]["message"]


#: @ai_mail's apps/ai_mail.py at e8d3d8a0, lines 31-33, verbatim. Its tests import it at collection, so
#: every xdist worker ran with SIGPIPE at SIG_DFL and one EPIPE killed the worker with no traceback.
SIGPIPE_SPECIMEN = """import signal

# Handle broken pipe gracefully (e.g. output piped to head)
# SIGPIPE does not exist on Windows
if hasattr(signal, "SIGPIPE"):
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)
"""

#: @ai_mail's apps/handlers/dispatch/daemon.py at e8d3d8a0, lines 64-72, verbatim but for the logger line.
DAEMON_SPECIMEN = """import signal

SHUTDOWN = False


def _handle_signal(signum, _frame):
    global SHUTDOWN
    SHUTDOWN = True


signal.signal(signal.SIGTERM, _handle_signal)
signal.signal(signal.SIGINT, _handle_signal)
"""


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
        assert message == ONLY_SIGNALS

    def test_a_helper_module_pytest_does_not_collect_is_not_judged(self, tmp_path):
        score, message = _verdict(tmp_path, IMPORTS + "os.chdir('/')\n", "helpers.py")
        assert (score, message) == (100, ONLY_SIGNALS)

    def test_a_file_named_with_the_test_suffix_is_judged(self, tmp_path):
        assert _verdict(tmp_path, IMPORTS + "os.chdir('/')\n", "routing_test.py")[0] == 0

    def test_a_test_named_product_module_under_apps_is_judged_for_signals_alone(self, tmp_path):
        """@ai_mail's apps/handlers/dispatch/test_token.py:27 was convicted under 1.1.0 by its name."""
        body = "import os\n\nos.environ.setdefault('PYTHONUTF8', '1')\n"
        assert _verdict_at(tmp_path, body, "apps/handlers/test_token.py") == (100, ONLY_SIGNALS)

    def test_the_same_body_in_a_tests_tree_is_convicted(self, tmp_path):
        body = "import os\n\nos.environ.setdefault('PYTHONUTF8', '1')\n"
        score, message = _verdict_at(tmp_path, body, "tests/test_token.py")
        assert score == 0
        assert "test_token.py:3 environ_write: os.environ.setdefault('PYTHONUTF8', '1')" in message

    def test_a_signal_line_in_a_test_named_product_module_is_still_convicted(self, tmp_path):
        body = "import signal\n\nsignal.signal(signal.SIGPIPE, signal.SIG_DFL)\n"
        score, message = _verdict_at(tmp_path, body, "apps/handlers/test_token.py")
        assert score == 0
        assert "test_token.py:3 signal_disposition: signal.signal(signal.SIGPIPE, signal.SIG_DFL)" in message


ONLY_SIGNALS = "Not a collected test file: only signal_disposition is judged here, and nothing sets one"


class TestASignalDispositionIsJudgedEverywhere:
    def test_ai_mails_sigpipe_line_is_convicted_in_a_production_module(self, tmp_path):
        score, message = _verdict_at(tmp_path, SIGPIPE_SPECIMEN, "apps/ai_mail.py")
        assert score == 0
        assert message == (
            "ai_mail.py:6 signal_disposition: signal.signal(signal.SIGPIPE, signal.SIG_DFL) - changes how the "
            "process answers a signal for the rest of its life, and a module a test imports runs it in every "
            'pytest worker at collection; set it where the process starts, under `if __name__ == "__main__":`'
        )

    def test_ai_mails_daemon_handlers_are_convicted_line_by_line(self, tmp_path):
        message = _verdict_at(tmp_path, DAEMON_SPECIMEN, "apps/handlers/dispatch/daemon.py")[1]
        assert [line.split(" - ")[0] for line in message.splitlines()] == [
            "daemon.py:11 signal_disposition: signal.signal(signal.SIGTERM, _handle_signal)",
            "daemon.py:12 signal_disposition: signal.signal(signal.SIGINT, _handle_signal)",
        ]

    @pytest.mark.parametrize("line", ["signal.alarm(5)", "signal.setitimer(signal.ITIMER_REAL, 1.0)"])
    def test_a_timer_that_signals_the_process_is_the_same_shape(self, tmp_path, line):
        score, message = _verdict(tmp_path, f"import signal\n\n{line}\n")
        assert score == 0
        assert f"test_specimen.py:3 signal_disposition: {line} - " in message

    def test_a_name_imported_from_signal_is_followed_to_signal(self, tmp_path):
        body = "from signal import signal as trap, SIGPIPE, SIG_DFL\n\ntrap(SIGPIPE, SIG_DFL)\n"
        assert "flow.py:3 signal_disposition: trap(SIGPIPE, SIG_DFL)" in _verdict_at(tmp_path, body, "apps/flow.py")[1]

    def test_a_conftest_signal_line_is_convicted_and_its_harness_lines_are_not(self, tmp_path):
        body = IMPORTS + "import signal\nos.environ['AIPASS_TEST_LOG_DIR'] = '/x'\nsignal.signal(signal.SIGINT, None)\n"
        score, message = _verdict(tmp_path, body, "conftest.py")
        assert score == 0
        assert [line.split(" - ")[0] for line in message.splitlines()] == [
            "conftest.py:9 signal_disposition: signal.signal(signal.SIGINT, None)"
        ]

    def test_a_production_module_is_judged_for_signals_alone(self, tmp_path):
        body = IMPORTS + "HOME = Path.home()\nsys.path.insert(0, 'x')\nos.chdir('/')\n"
        assert _verdict_at(tmp_path, body, "apps/commons.py") == (100, ONLY_SIGNALS)


class TestWhereASignalLineIsNotModuleScope:
    def test_the_main_guard_and_a_function_body_pass(self, tmp_path):
        body = "import signal\n\n\ndef main():\n    signal.signal(signal.SIGPIPE, signal.SIG_DFL)\n\n\n"
        body += "if __name__ == '__main__':\n    signal.signal(signal.SIGPIPE, signal.SIG_DFL)\n"
        assert _verdict_at(tmp_path, body, "apps/flow.py") == (100, ONLY_SIGNALS)

    def test_reading_a_disposition_changes_nothing_and_passes(self, tmp_path):
        body = "import signal\n\nPREVIOUS = signal.getsignal(signal.SIGPIPE)\n"
        assert _verdict(tmp_path, body)[0] == 100
