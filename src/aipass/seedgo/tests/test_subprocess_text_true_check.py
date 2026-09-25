# =================== META ====================
# Name: test_subprocess_text_true_check.py
# Description: subprocess_text_true_check — a text-mode subprocess call in a test that names no encoding
# Version: 1.0.0
# Created: 2026-09-25
# Modified: 2026-09-25
# =============================================

"""Tests for apps/handlers/aipass_standards/subprocess_text_true_check.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(shared) — is_bypassed's own matching rules; tests/test_bypass.py
# seedgo: no-test-needed(shared) — file reads and writes without an encoding; tests/test_named_encoding_check.py

from pathlib import Path

import pytest

from aipass.seedgo.apps.handlers.aipass_standards import subprocess_text_true_check as checker


def _verdict(tmp_path, body, name="test_specimen.py"):
    """(score, the one check's message) for a file planted under tests/."""
    tests = tmp_path / "tests"
    tests.mkdir(exist_ok=True)
    path = tests / name
    path.write_text(body, encoding="utf-8")
    result = checker.check_module(str(path))
    return result["score"], result["checks"][0]["message"]


#: The model file for the whole per-item series.
MODEL = Path(__file__).resolve().parent / "test_readme_update.py"

#: @backup's tests/test_dead_cwd_imports.py: the four calls reported at 7b51d118 lines 224, 706,
#: 797 and 852 (each the `text=True` line), verbatim as on disk 2026-09-25 at 212, 608, 698 and
#: 726 (backup's cure swapped --rcfile=/dev/null for a temp rcfile), enclosing defs cut down.
SPECIMENS = """import os
import subprocess
import sys


def _run_probe(world: str, targets: list[str] | None = None) -> dict:
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            _PROBE,
            world,
            json.dumps(targets if targets is not None else PROBE_MODULES),
            json.dumps(PRELOAD),
        ],
        capture_output=True,
        text=True,
        timeout=180,
    )


def _run() -> dict:
    proc = subprocess.run(
        [sys.executable, "-c", _NONE_BRANCH_PROBE],
        capture_output=True,
        text=True,
        timeout=60,
    )


def _coverage_run(tmp_path, cwd):
    run = subprocess.run(
        [
            sys.executable,
            "-m",
            "coverage",
            "run",
            f"--rcfile={rcfile}",
            f"--source={SOURCE_TREE}",
            "-m",
            "pytest",
            *selected,
            "-q",
            "-p",
            "no:cacheprovider",
        ],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
    )


def test_report(tmp_path):
    report = subprocess.run(
        [sys.executable, "-m", "coverage", "report", f"--rcfile={rcfile}"],
        cwd=BRANCH_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
    )
"""

#: The four `text=True` lines of SPECIMENS, in order.
SPECIMEN_LINES = (17, 26, 50, 61)

#: Every call the rule judges, each with the flag the fleet does not use yet.
JUDGED = ["run", "Popen", "check_output", "check_call", "call"]


class TestTheModelFilePasses:
    def test_the_model_file_scores_100(self):
        assert checker.check_module(str(MODEL))["score"] == 100


class TestThePlantedSpecimens:
    def test_backups_four_calls_are_each_convicted_on_the_text_line(self, tmp_path):
        score, message = _verdict(tmp_path, SPECIMENS)
        assert score == 0
        assert [line.split(" ")[0] for line in message.splitlines()] == [
            f"test_specimen.py:{line}" for line in SPECIMEN_LINES
        ]

    def test_a_finding_names_the_call_the_flag_the_reason_and_the_cure(self, tmp_path):
        message = _verdict(tmp_path, "import subprocess\nsubprocess.run(['x'], text=True)\n")[1]
        assert message == (
            "test_specimen.py:2 subprocess.run(text=True) without encoding - decodes with the locale "
            'encoding, cp1252 on Windows; pass encoding="utf-8" (and errors= if the child may print '
            "bytes that are not utf-8)"
        )

    def test_the_cured_specimens_pass(self, tmp_path):
        cured = SPECIMENS.replace("text=True,", 'text=True,\n        encoding="utf-8",')
        assert _verdict(tmp_path, cured) == (100, "Every text-mode subprocess call names an encoding")


class TestTheShape:
    @pytest.mark.parametrize("call", JUDGED)
    @pytest.mark.parametrize("flag", ["text", "universal_newlines"])
    def test_every_call_and_both_flags_are_convicted(self, tmp_path, call, flag):
        body = f"import subprocess\n\n\ndef test_x():\n    subprocess.{call}(['x'], {flag}=True)\n"
        score, message = _verdict(tmp_path, body)
        assert score == 0
        assert message.startswith(f"test_specimen.py:5 subprocess.{call}({flag}=True) without encoding")

    def test_errors_alone_is_not_a_cure(self, tmp_path):
        body = "import subprocess\nsubprocess.run(['x'], text=True, errors='replace')\n"
        assert _verdict(tmp_path, body)[0] == 0

    def test_encoding_none_is_the_locale_again(self, tmp_path):
        body = "import subprocess\nsubprocess.run(['x'], text=True, encoding=None)\n"
        assert _verdict(tmp_path, body)[0] == 0

    def test_every_hit_in_a_file_is_on_one_check(self, tmp_path):
        body = "import subprocess\nsubprocess.run(['a'], text=True)\nsubprocess.Popen(['b'], text=True)\n"
        message = _verdict(tmp_path, body)[1]
        assert len(message.splitlines()) == 2


class TestAliasesAreFollowed:
    def test_import_subprocess_as_an_alias(self, tmp_path):
        body = "import subprocess as sp\nsp.run(['x'], text=True)\n"
        assert "test_specimen.py:2 subprocess.run(text=True)" in _verdict(tmp_path, body)[1]

    def test_from_subprocess_import_a_name(self, tmp_path):
        body = "from subprocess import run, Popen as P\nrun(['x'], text=True)\nP(['x'], text=True)\n"
        message = _verdict(tmp_path, body)[1]
        assert "test_specimen.py:2 subprocess.run(text=True)" in message
        assert "test_specimen.py:3 subprocess.Popen(text=True)" in message

    def test_an_alias_imported_inside_a_function(self, tmp_path):
        body = "def test_x():\n    import subprocess as _sp\n    _sp.check_output(['x'], text=True)\n"
        assert "test_specimen.py:3 subprocess.check_output(text=True)" in _verdict(tmp_path, body)[1]


class TestWhatPasses:
    def test_encoding_named_passes(self, tmp_path):
        body = "import subprocess\nsubprocess.run(['x'], capture_output=True, text=True, encoding='utf-8')\n"
        assert _verdict(tmp_path, body)[0] == 100

    def test_encoding_alone_passes(self, tmp_path):
        body = "import subprocess\nsubprocess.run(['x'], capture_output=True, encoding='utf-8')\n"
        assert _verdict(tmp_path, body)[0] == 100

    @pytest.mark.parametrize("args", ["capture_output=True", "text=False", "universal_newlines=False"])
    def test_bytes_mode_passes(self, tmp_path, args):
        body = f"import subprocess\nsubprocess.run(['x'], {args})\n"
        assert _verdict(tmp_path, body)[0] == 100

    def test_a_flag_that_is_not_a_literal_is_not_judged(self, tmp_path):
        body = "import subprocess\nmode = True\nsubprocess.run(['x'], text=mode)\n"
        assert _verdict(tmp_path, body)[0] == 100

    def test_a_kwargs_splat_is_not_judged(self, tmp_path):
        body = "import subprocess\nsubprocess.run(['x'], text=True, **opts)\n"
        assert _verdict(tmp_path, body)[0] == 100

    def test_a_mock_assertion_is_not_a_subprocess_call(self, tmp_path):
        body = "import subprocess\nmock_run.assert_called_once_with(['x'], text=True)\n"
        assert _verdict(tmp_path, body)[0] == 100

    def test_a_run_that_is_not_subprocess_is_not_judged(self, tmp_path):
        body = "import asyncio\nfrom mylib import run\nrun(['x'], text=True)\nasyncio.run(main(), text=True)\n"
        assert _verdict(tmp_path, body)[0] == 100

    def test_the_call_inside_a_string_is_not_convicted(self, tmp_path):
        body = "import subprocess\nSOURCE = \"subprocess.run(['x'], text=True)\"\n"
        assert _verdict(tmp_path, body)[0] == 100


class TestTheEdges:
    def test_a_missing_file_scores_0(self, tmp_path):
        result = checker.check_module(str(tmp_path / "tests" / "test_gone.py"))
        assert (result["score"], result["passed"]) == (0, False)

    def test_an_unparseable_file_is_not_judged(self, tmp_path):
        score, message = _verdict(tmp_path, "def test_x(:\n    subprocess.run(['x'], text=True)\n")
        assert (score, message) == (100, "Not judged: the file does not parse (ruff convicts that)")

    def test_a_bypass_for_the_standard_passes_the_file(self, tmp_path):
        path = tmp_path / "tests" / "test_specimen.py"
        path.parent.mkdir()
        path.write_text("import subprocess\nsubprocess.run(['x'], text=True)\n", encoding="utf-8")
        rules = [{"file": str(path), "standard": "subprocess_text_true"}]
        assert checker.check_module(str(path), bypass_rules=rules)["score"] == 100

    def test_a_bypass_for_one_line_clears_that_line_only(self, tmp_path):
        path = tmp_path / "tests" / "test_specimen.py"
        path.parent.mkdir()
        path.write_text(
            "import subprocess\nsubprocess.run(['a'], text=True)\nsubprocess.run(['b'], text=True)\n", encoding="utf-8"
        )
        rules = [{"file": str(path), "standard": "subprocess_text_true", "lines": [2]}]
        message = checker.check_module(str(path), bypass_rules=rules)["checks"][0]["message"]
        assert message.startswith("test_specimen.py:3 ")
        assert len(message.splitlines()) == 1

    def test_the_standard_is_declared_tests_only(self):
        assert (checker.APPLIES_TO, checker.AUDIT_SCOPE) == ("tests", "all_files")
