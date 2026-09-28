# =================== AIPass ====================
# Name: test_auto_fix.py
# Version: 1.2.2
# Description: Tests for auto_fix lifecycle handler
# Branch: hooks
# Created: 2026-05-22
# Modified: 2026-09-28
# =============================================

"""Tests for apps/handlers/lifecycle/auto_fix.py."""

# NOTE: sound is action-gated via the result "sound" key — it is set to
# "auto fix diagnostics" only on the error-surfacing path; clean and skip
# paths stay silent (no "sound" key).

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — ruff's own lint and format verdicts; the tests stub its subprocess at the edge
# seedgo: no-test-needed(documentation) — that auto_fix's functions carry docstrings
# seedgo: no-test-needed(stdlib) — subprocess.run's timeout mechanics; the tests stub it at the edge

import json
import os
import sys
import tempfile
from pathlib import Path, PureWindowsPath
from unittest.mock import MagicMock, patch

import pytest

from aipass.hooks.apps.handlers.lifecycle import auto_fix
from aipass.hooks.apps.handlers.lifecycle.auto_fix import (
    PYTHON_PATTERNS,
    _check_emoji_list,
    _check_line_pattern,
    _check_patterns,
    _check_ruff_format,
    _check_ruff_lint,
    _check_syntax,
    _checklist_marker,
    _run_pyright_check,
    _run_ruff_lint_structured,
    _run_seedgo_checklist,
    handle,
)
from aipass.prax.apps.modules.logger import system_logger
from aipass.seedgo.apps.modules.checklist import FINDING_MARKER


def _kept_redirect() -> dict[str, str]:
    """The json redirect a clear=True wipe must hand back, or the loggers write the live hooks_json."""
    return {"AIPASS_TEST_LOG_DIR": os.environ["AIPASS_TEST_LOG_DIR"]}


# A hook file as this host spells it, and as a native Windows host hands it over:
# the skips compare with forward slashes, so the second is what compass 458 guards.
_HOOK_SPELLINGS = [
    pytest.param(str, id="this-host"),
    pytest.param(lambda path: str(PureWindowsPath(path)), id="windows-form"),
]


# Stand-ins for tests whose subprocess is mocked — nothing here is ever touched
# on disk. Built from the temp dir rather than written as POSIX literals, so they
# hold on every host; the file's other paths are built from tmp_path.
_FAKE_HOME = str(Path(tempfile.gettempdir()) / "fake_aipass_home")
_FAKE_PY = str(Path(tempfile.gettempdir()) / "check.py")


class TestAutoFixSkips:
    def test_skip_non_edit_tool(self):
        result = handle({"tool_name": "Bash", "tool_input": {"command": "ls"}})
        assert result["stdout"] == ""
        assert result["exit_code"] == 0

    def test_skip_non_code_file_md(self, tmp_path):
        result = handle({"tool_name": "Edit", "tool_input": {"file_path": str(tmp_path / "README.md")}})
        assert result["stdout"] == ""
        assert result["exit_code"] == 0

    def test_skip_non_code_file_txt(self, tmp_path):
        result = handle({"tool_name": "Write", "tool_input": {"file_path": str(tmp_path / "notes.txt")}})
        assert result["stdout"] == ""
        assert result["exit_code"] == 0

    def test_skip_non_code_file_html(self, tmp_path):
        result = handle({"tool_name": "Edit", "tool_input": {"file_path": str(tmp_path / "page.html")}})
        assert result["stdout"] == ""
        assert result["exit_code"] == 0

    def test_empty_hook_data(self):
        result = handle({})
        assert result["stdout"] == ""
        assert result["exit_code"] == 0

    def test_missing_file_path(self):
        result = handle({"tool_name": "Edit", "tool_input": {}})
        assert result["stdout"] == ""
        assert result["exit_code"] == 0

    def test_skip_unknown_extension(self, tmp_path):
        result = handle({"tool_name": "Edit", "tool_input": {"file_path": str(tmp_path / "file.xyz")}})
        assert result["stdout"] == ""
        assert result["exit_code"] == 0
        assert "sound" not in result


class TestAutofixPython:
    @patch("aipass.hooks.apps.handlers.lifecycle.auto_fix._run_seedgo_checklist", return_value=[])
    @patch("aipass.hooks.apps.handlers.lifecycle.auto_fix._run_pyright_check", return_value=[])
    @patch("aipass.hooks.apps.handlers.lifecycle.auto_fix._run_ruff_lint_structured", return_value=[])
    @patch("aipass.hooks.apps.handlers.lifecycle.auto_fix._run_python_checks", return_value=[])
    def test_python_no_errors(self, mock_py, mock_ruff_s, mock_pyright, mock_seedgo, tmp_path):
        result = handle({"tool_name": "Edit", "tool_input": {"file_path": str(tmp_path / "clean.py")}})
        assert result["exit_code"] == 0
        parsed = json.loads(result["stdout"])
        assert parsed["systemMessage"] == "[diagnostics] ok"
        assert "sound" not in result

    @patch("aipass.hooks.apps.handlers.lifecycle.auto_fix._run_seedgo_checklist", return_value=[])
    @patch("aipass.hooks.apps.handlers.lifecycle.auto_fix._run_pyright_check", return_value=[])
    @patch("aipass.hooks.apps.handlers.lifecycle.auto_fix._run_ruff_lint_structured", return_value=[])
    @patch("aipass.hooks.apps.handlers.lifecycle.auto_fix._run_python_checks")
    def test_python_syntax_error(self, mock_py, mock_ruff_s, mock_pyright, mock_seedgo, tmp_path):
        mock_py.return_value = ["SYNTAX: invalid syntax at line 5"]
        result = handle({"tool_name": "Edit", "tool_input": {"file_path": str(tmp_path / "bad.py")}})
        assert result["exit_code"] == 0
        parsed = json.loads(result["stdout"])
        assert "additionalContext" in parsed.get("hookSpecificOutput", {})
        assert "SYNTAX" in parsed["hookSpecificOutput"]["additionalContext"]
        assert "1 error(s)" in parsed["systemMessage"]
        assert result.get("sound") == "auto fix diagnostics"

    @patch("aipass.hooks.apps.handlers.lifecycle.auto_fix._run_seedgo_checklist", return_value=[])
    @patch("aipass.hooks.apps.handlers.lifecycle.auto_fix._run_pyright_check", return_value=[])
    @patch("aipass.hooks.apps.handlers.lifecycle.auto_fix._run_ruff_lint_structured", return_value=[])
    @patch("aipass.hooks.apps.handlers.lifecycle.auto_fix._run_python_checks")
    def test_python_ruff_lint_errors(self, mock_py, mock_ruff_s, mock_pyright, mock_seedgo, tmp_path):
        mock_py.return_value = ["LINT: bad.py:10:1: F401 unused import"]
        result = handle({"tool_name": "Write", "tool_input": {"file_path": str(tmp_path / "bad.py")}})
        parsed = json.loads(result["stdout"])
        assert "LINT" in parsed["hookSpecificOutput"]["additionalContext"]
        assert result.get("sound") == "auto fix diagnostics"

    @patch("aipass.hooks.apps.handlers.lifecycle.auto_fix._run_seedgo_checklist", return_value=[])
    @patch("aipass.hooks.apps.handlers.lifecycle.auto_fix._run_ruff_lint_structured", return_value=[])
    @patch("aipass.hooks.apps.handlers.lifecycle.auto_fix._run_python_checks", return_value=[])
    def test_python_pyright_errors(self, mock_py, mock_ruff_s, mock_seedgo, tmp_path):
        with patch(
            "aipass.hooks.apps.handlers.lifecycle.auto_fix._run_pyright_check",
            return_value=[{"line": 42, "message": "Cannot assign to declared type"}],
        ):
            result = handle({"tool_name": "Edit", "tool_input": {"file_path": str(tmp_path / "typed.py")}})

        parsed = json.loads(result["stdout"])
        assert "TYPE: L42" in parsed["hookSpecificOutput"]["additionalContext"]
        assert result.get("sound") == "auto fix diagnostics"

    @patch("aipass.hooks.apps.handlers.lifecycle.auto_fix._run_pyright_check", return_value=[])
    @patch("aipass.hooks.apps.handlers.lifecycle.auto_fix._run_ruff_lint_structured", return_value=[])
    @patch("aipass.hooks.apps.handlers.lifecycle.auto_fix._run_python_checks", return_value=[])
    def test_seedgo_violations_surfaced(self, mock_py, mock_ruff_s, mock_pyright, tmp_path):
        with patch(
            "aipass.hooks.apps.handlers.lifecycle.auto_fix._run_seedgo_checklist",
            return_value=["missing file header"],
        ):
            result = handle({"tool_name": "Edit", "tool_input": {"file_path": str(tmp_path / "noheader.py")}})

        parsed = json.loads(result["stdout"])
        assert "SEEDGO: missing file header" in parsed["hookSpecificOutput"]["additionalContext"]
        assert result.get("sound") == "auto fix diagnostics"


class TestAutoFixStateFile:
    @patch("aipass.hooks.apps.handlers.lifecycle.auto_fix._run_seedgo_checklist", return_value=[])
    @patch("aipass.hooks.apps.handlers.lifecycle.auto_fix._run_pyright_check")
    @patch("aipass.hooks.apps.handlers.lifecycle.auto_fix._run_ruff_lint_structured")
    @patch("aipass.hooks.apps.handlers.lifecycle.auto_fix._run_python_checks", return_value=[])
    def test_state_file_written_on_errors(self, mock_py, mock_ruff_s, mock_pyright, mock_seedgo, tmp_path):
        mock_ruff_s.return_value = [{"line": 5, "message": "F401: unused import"}]
        mock_pyright.return_value = [{"line": 10, "message": "Type error here"}]

        state_path = tmp_path / ".diagnostics_state.json"

        with patch("aipass.hooks.apps.handlers.lifecycle.auto_fix.STATE_FILE", state_path):
            result = handle({"tool_name": "Edit", "tool_input": {"file_path": str(tmp_path / "errors.py")}})

        assert result.get("sound") == "auto fix diagnostics"
        assert state_path.exists()
        state = json.loads(state_path.read_text(encoding="utf-8"))
        assert len(state["errors"]) == 2
        assert state["errors"][0]["line"] == 5
        assert state["errors"][1]["line"] == 10

    @patch("aipass.hooks.apps.handlers.lifecycle.auto_fix._run_seedgo_checklist", return_value=[])
    @patch("aipass.hooks.apps.handlers.lifecycle.auto_fix._run_pyright_check", return_value=[])
    @patch("aipass.hooks.apps.handlers.lifecycle.auto_fix._run_ruff_lint_structured", return_value=[])
    @patch("aipass.hooks.apps.handlers.lifecycle.auto_fix._run_python_checks", return_value=[])
    def test_state_file_cleared_on_no_errors(self, mock_py, mock_ruff_s, mock_pyright, mock_seedgo, tmp_path):
        state_path = tmp_path / ".diagnostics_state.json"
        state = {"file": str(tmp_path / "old.py"), "errors": [{"line": 1, "message": "old"}]}
        state_path.write_text(json.dumps(state), encoding="utf-8")

        with patch("aipass.hooks.apps.handlers.lifecycle.auto_fix.STATE_FILE", state_path):
            result = handle({"tool_name": "Edit", "tool_input": {"file_path": str(tmp_path / "clean.py")}})

        assert "sound" not in result
        assert not state_path.exists()


class TestAutoFixJson:
    def test_json_valid(self, tmp_path):
        from aipass.hooks.apps.handlers.lifecycle.auto_fix import handle

        json_file = tmp_path / "good.json"
        json_file.write_text('{"key": "value"}', encoding="utf-8")

        result = handle({"tool_name": "Edit", "tool_input": {"file_path": str(json_file)}})
        parsed = json.loads(result["stdout"])
        assert parsed["systemMessage"] == "[diagnostics] ok"
        assert "sound" not in result

    def test_json_invalid_syntax(self, tmp_path):
        from aipass.hooks.apps.handlers.lifecycle.auto_fix import handle

        json_file = tmp_path / "bad.json"
        json_file.write_text('{"key": }', encoding="utf-8")

        result = handle({"tool_name": "Write", "tool_input": {"file_path": str(json_file)}})
        parsed = json.loads(result["stdout"])
        assert "JSON SYNTAX" in parsed["hookSpecificOutput"]["additionalContext"]
        assert result.get("sound") == "auto fix diagnostics"

    def test_json_corruption_detected(self, tmp_path):
        from aipass.hooks.apps.handlers.lifecycle.auto_fix import handle

        json_file = tmp_path / "corrupt.json"
        json_file.write_text('{"data": "\x00bad"}', encoding="utf-8")

        result = handle({"tool_name": "Edit", "tool_input": {"file_path": str(json_file)}})
        parsed = json.loads(result["stdout"])
        assert "EMOJI CORRUPTION" in parsed["hookSpecificOutput"]["additionalContext"]
        assert result.get("sound") == "auto fix diagnostics"


class TestAutoFixSubprocessChecks:
    @patch("subprocess.run")
    def test_check_syntax_error(self, mock_run, tmp_path):
        mock_run.return_value = MagicMock(returncode=1, stderr="SyntaxError: invalid syntax")
        errors = _check_syntax(str(tmp_path / "bad.py"))
        assert len(errors) == 1
        assert "SYNTAX" in errors[0]

    @patch("subprocess.run")
    def test_check_syntax_clean(self, mock_run, tmp_path):
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        errors = _check_syntax(str(tmp_path / "good.py"))
        assert errors == []

    @patch("subprocess.run")
    def test_check_ruff_lint_findings(self, mock_run, tmp_path):
        mock_run.return_value = MagicMock(returncode=1, stdout="bad.py:10:1: F401 unused import\n")
        errors = _check_ruff_lint(str(tmp_path / "bad.py"))
        assert len(errors) == 1
        assert "LINT" in errors[0]
        # bare "ruff" relies on PATH the hook env doesn't have — must go through the venv interpreter
        assert mock_run.call_args[0][0][:3] == [sys.executable, "-m", "ruff"]

    @patch("subprocess.run")
    def test_check_ruff_format_drift(self, mock_run, tmp_path):
        mock_run.return_value = MagicMock(returncode=1)
        errors = _check_ruff_format(str(tmp_path / "unformatted.py"))
        assert len(errors) == 1
        assert "FORMAT" in errors[0]
        assert mock_run.call_args[0][0][:3] == [sys.executable, "-m", "ruff"]

    @patch("subprocess.run")
    def test_run_ruff_lint_structured_returns_dicts(self, mock_run, tmp_path):
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout=json.dumps(
                [
                    {"location": {"row": 5}, "code": "F401", "message": "unused import os"},
                ]
            ),
        )
        errors = _run_ruff_lint_structured(str(tmp_path / "lint.py"))
        assert len(errors) == 1
        assert errors[0]["line"] == 5
        assert "F401" in errors[0]["message"]
        assert mock_run.call_args[0][0][:3] == [sys.executable, "-m", "ruff"]

    @pytest.mark.parametrize("spell", _HOOK_SPELLINGS)
    @patch("subprocess.run")
    def test_run_ruff_lint_structured_skips_claude_hooks(self, mock_run, tmp_path, spell):
        errors = _run_ruff_lint_structured(spell(tmp_path / ".claude" / "hooks" / "myhook.py"))
        assert errors == []
        mock_run.assert_not_called()

    @patch("subprocess.run")
    def test_run_pyright_check_returns_errors(self, mock_run, tmp_path):
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout=json.dumps(
                {
                    "generalDiagnostics": [
                        {
                            "severity": "error",
                            "range": {"start": {"line": 42}},
                            "message": "Cannot assign type",
                        },
                        {
                            "severity": "warning",
                            "range": {"start": {"line": 10}},
                            "message": "This is a warning",
                        },
                    ],
                }
            ),
        )
        errors = _run_pyright_check(str(tmp_path / "typed.py"))
        assert len(errors) == 1
        assert errors[0]["line"] == 42

    @pytest.mark.parametrize("spell", _HOOK_SPELLINGS)
    @patch("subprocess.run")
    def test_run_pyright_skips_claude_hooks(self, mock_run, tmp_path, spell):
        errors = _run_pyright_check(spell(tmp_path / ".claude" / "hooks" / "myhook.py"))
        assert errors == []
        mock_run.assert_not_called()

    @patch("subprocess.run")
    def test_run_seedgo_checklist_returns_violations(self, mock_run):
        """REVERSED 2026-08-30. This test pinned a marker nobody printed.

        It fed the parser a cross and asserted two findings came back, and it
        passed for months while the live path returned [] on every file — the
        fixture was the only place the cross still existed. @seedgo reported the
        drift (checklist emits ``[FAIL]``); the output below is copied from a
        real run against a violating file.
        """
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=(
                "probe.py\n"
                "  ✓ cli\n"
                "  [FAIL] — debug_print: 1 bare print() call(s) on lines 5\n"
                "  ✓ imports\n"
                "  [FAIL] — hardcoded_path: 1 hardcoded path(s): L6: POSIX home path\n"
            ),
        )
        with patch.dict("os.environ", {"AIPASS_HOME": _FAKE_HOME}):
            violations = _run_seedgo_checklist(_FAKE_PY)
        assert len(violations) == 2
        assert "debug_print" in violations[0]
        assert "hardcoded_path" in violations[1]

    @patch("subprocess.run")
    def test_the_dead_cross_marker_finds_nothing(self, mock_run):
        """The old fixture, run against the fixed reader: zero findings.

        Kept as the negative twin so the reader can never quietly drift back.
        """
        mock_run.return_value = MagicMock(returncode=0, stdout="✗ missing encoding param\n✗ bad import\n")
        with patch.dict("os.environ", {"AIPASS_HOME": _FAKE_HOME}):
            assert _run_seedgo_checklist(_FAKE_PY) == []

    @patch("subprocess.run")
    def test_a_nonzero_exit_no_longer_discards_the_findings(self, mock_run):
        """The exit code carries nothing; stdout is the entire signal.

        checklist does not sys.exit on a standards failure — measured live
        2026-08-30, eight findings and returncode 0. Dropping output on a
        non-zero code was the same drift pre-armed for the day it does.
        """
        mock_run.return_value = MagicMock(returncode=1, stdout="  [FAIL] — meta: Missing META block\n")
        with patch.dict("os.environ", {"AIPASS_HOME": _FAKE_HOME}):
            violations = _run_seedgo_checklist(_FAKE_PY)
        assert len(violations) == 1
        assert "meta" in violations[0]

    @patch("subprocess.run")
    def test_a_wrapped_detail_is_rejoined_not_truncated(self, mock_run):
        """Rich wraps at the console width; the reason must survive the fold."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=(
                "  [FAIL] — architecture: File not in standard 3-layer structure (apps/, \n"
                "apps/modules/, apps/handlers/)\n"
                "  ✓ cli\n"
            ),
        )
        with patch.dict("os.environ", {"AIPASS_HOME": _FAKE_HOME}):
            violations = _run_seedgo_checklist(_FAKE_PY)
        assert len(violations) == 1
        assert violations[0].endswith("apps/handlers/)")

    def test_the_marker_is_read_from_seedgo_not_restated_here(self):
        """One definition. The next marker change cannot silently disagree."""
        assert _checklist_marker() == FINDING_MARKER

    def test_an_unreadable_seedgo_falls_back_loudly(self):
        with patch.object(auto_fix.importlib, "import_module", side_effect=ImportError("no seedgo")):
            with patch.object(auto_fix.logger, "warning") as warned:
                marker = auto_fix._checklist_marker()
        assert marker == auto_fix._CHECKLIST_MARKER_FALLBACK
        warned.assert_called_once()

    def test_a_seedgo_publishing_no_marker_falls_back_loudly(self):
        with patch.object(auto_fix.importlib, "import_module", return_value=object()):
            with patch.object(auto_fix.logger, "warning") as warned:
                marker = auto_fix._checklist_marker()
        assert marker == auto_fix._CHECKLIST_MARKER_FALLBACK
        warned.assert_called_once()

    @pytest.mark.parametrize("spell", _HOOK_SPELLINGS)
    @patch("subprocess.run")
    def test_run_seedgo_skips_claude_hooks(self, mock_run, tmp_path, spell):
        # AIPASS_HOME set, so the skip is what answers and not the missing home.
        home = {**_kept_redirect(), "AIPASS_HOME": str(tmp_path)}
        with patch.dict("os.environ", home, clear=True):
            violations = _run_seedgo_checklist(spell(tmp_path / ".claude" / "hooks" / "myhook.py"))
        assert violations == []
        mock_run.assert_not_called()

    def test_run_seedgo_skips_without_aipass_home(self, tmp_path):
        with patch.dict("os.environ", _kept_redirect(), clear=True):
            violations = _run_seedgo_checklist(str(tmp_path / "check.py"))
        assert violations == []


class TestRetiredLoggerDebugRule:
    """logger.debug() is supported by prax's SystemLogger — the rule is retired.

    The rule told the fleet the opposite of what @seedgo teaches, on the same
    line of code, for as long as both existed. These pin the retirement so it
    cannot be re-added by reflex.
    """

    def test_logger_debug_rule_is_gone_from_the_pattern_table(self):
        assert "logger_debug" not in PYTHON_PATTERNS

    def test_no_pattern_rule_targets_logger_debug(self):
        assert not [c for c in PYTHON_PATTERNS.values() if "logger.debug" in c["pattern"]]

    def test_a_file_calling_logger_debug_reports_no_violation(self, temp_test_dir):
        target = temp_test_dir / "uses_debug.py"
        target.write_text('logger.debug("hello")\n', encoding="utf-8")

        assert _check_patterns(str(target)) == []

    def test_prax_system_logger_really_has_debug(self):
        """The premise the retirement rests on — asserted, not assumed."""
        assert callable(getattr(system_logger, "debug", None))


class TestAutoFixPatterns:
    def test_check_line_pattern_matches(self):
        assert _check_line_pattern("    logger.debug(msg)", "logger.debug(") is True

    def test_check_line_pattern_skips_comments(self):
        assert _check_line_pattern("    # logger.debug(msg)", "logger.debug(") is False

    def test_check_line_pattern_skips_strings(self):
        assert _check_line_pattern('    msg = "logger.debug(test)"', "logger.debug(") is False

    def test_check_emoji_list_clean(self):
        assert _check_emoji_list(["hello", "world"], "emojis") is None

    def test_check_emoji_list_suspicious(self):
        result = _check_emoji_list(["a"], "emojis")
        assert result is not None
        assert "EMOJI CORRUPTION" in result


class TestOpenPatternWordBoundary:
    """`open(` is a substring of `Popen(` — reported by @drone, 2026-08-27.

    Every Edit to drone/apps/handlers/executor.py returned "open() without
    encoding='utf-8'". That file contains no open() call at all; the only match
    was `subprocess.Popen(`. It fired six times across six unrelated edits.

    Why this is worth fixing rather than tolerating: the advisory says "Fix
    these errors now. Do not skip or defer." Popen takes no encoding argument
    in byte mode, so the only two moves available to the agent were to ignore a
    hook that claims an error, or to damage working code to satisfy it. A check
    that cries wolf on correct code trains agents to ignore it, and it will be
    ignored on the day it is right.
    """

    def test_popen_alone_does_not_fire(self, tmp_path):
        from aipass.hooks.apps.handlers.lifecycle.auto_fix import _check_patterns

        target = tmp_path / "executor_like.py"
        target.write_text(
            "import subprocess\n"
            "def run(cmd):\n"
            "    proc = subprocess.Popen(cmd, bufsize=0)\n"
            "    return proc.communicate()\n",
            encoding="utf-8",
        )
        assert _check_patterns(str(target)) == []

    def test_other_open_suffixed_calls_do_not_fire(self, tmp_path):
        """fdopen, os.popen and reopen are all longer names, not open()."""
        from aipass.hooks.apps.handlers.lifecycle.auto_fix import _check_patterns

        target = tmp_path / "suffixed.py"
        target.write_text(
            "import os\ndef f(fd):\n    a = os.fdopen(fd)\n    b = os.popen('ls')\n    return a, b\n",
            encoding="utf-8",
        )
        assert _check_patterns(str(target)) == []

    def test_real_open_without_encoding_still_fires(self, tmp_path):
        """The rule must keep working — this is the case it exists for."""
        from aipass.hooks.apps.handlers.lifecycle.auto_fix import _check_patterns

        target = tmp_path / "bare_open.py"
        target.write_text("def f(p):\n    return open(p).read()\n", encoding="utf-8")
        errors = _check_patterns(str(target))
        assert any("encoding" in e for e in errors)

    def test_attribute_open_without_encoding_still_fires(self, tmp_path):
        """io.open( / os.open( are real open calls — the dot is a boundary."""
        from aipass.hooks.apps.handlers.lifecycle.auto_fix import _check_patterns

        target = tmp_path / "attr_open.py"
        target.write_text("import io\ndef f(p):\n    return io.open(p).read()\n", encoding="utf-8")
        errors = _check_patterns(str(target))
        assert any("encoding" in e for e in errors)

    def test_open_with_encoding_does_not_fire(self, tmp_path):
        from aipass.hooks.apps.handlers.lifecycle.auto_fix import _check_patterns

        target = tmp_path / "good_open.py"
        target.write_text("def f(p):\n    return open(p, encoding='utf-8').read()\n", encoding="utf-8")
        assert _check_patterns(str(target)) == []

    def test_against_the_reporters_real_file(self, tmp_path):
        """@drone offered executor.py as the fixture; it is a good one.

        Skips rather than fails if the file moves — a cross-branch path is
        evidence, not a dependency this suite may hold hostage.
        """
        import pytest

        from aipass.hooks.apps.handlers.lifecycle.auto_fix import _check_patterns

        executor = Path(__file__).resolve().parents[2] / "drone" / "apps" / "handlers" / "executor.py"
        if not executor.is_file():
            pytest.skip("drone/apps/handlers/executor.py not present")

        errors = _check_patterns(str(executor))
        assert not any("encoding" in e for e in errors), f"false positive still fires: {errors}"
