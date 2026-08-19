# =================== AIPass ====================
# Name: test_auto_fix.py
# Version: 1.0.0
# Description: Tests for auto_fix lifecycle handler
# Branch: hooks
# Created: 2026-05-22
# Modified: 2026-05-22
# =============================================

"""Tests for handlers/lifecycle/auto_fix.py.

NOTE: sound is action-gated via the result "sound" key — it is set to
"auto fix diagnostics" only on the error-surfacing path; clean and skip
paths stay silent (no "sound" key).
"""

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch


class TestAutoFixSkips:
    def test_skip_non_edit_tool(self):
        from aipass.hooks.apps.handlers.lifecycle.auto_fix import handle

        result = handle({"tool_name": "Bash", "tool_input": {"command": "ls"}})
        assert result["stdout"] == ""
        assert result["exit_code"] == 0

    def test_skip_non_code_file_md(self):
        from aipass.hooks.apps.handlers.lifecycle.auto_fix import handle

        result = handle({"tool_name": "Edit", "tool_input": {"file_path": "/tmp/README.md"}})
        assert result["stdout"] == ""
        assert result["exit_code"] == 0

    def test_skip_non_code_file_txt(self):
        from aipass.hooks.apps.handlers.lifecycle.auto_fix import handle

        result = handle({"tool_name": "Write", "tool_input": {"file_path": "/tmp/notes.txt"}})
        assert result["stdout"] == ""
        assert result["exit_code"] == 0

    def test_skip_non_code_file_html(self):
        from aipass.hooks.apps.handlers.lifecycle.auto_fix import handle

        result = handle({"tool_name": "Edit", "tool_input": {"file_path": "/tmp/page.html"}})
        assert result["stdout"] == ""
        assert result["exit_code"] == 0

    def test_empty_hook_data(self):
        from aipass.hooks.apps.handlers.lifecycle.auto_fix import handle

        result = handle({})
        assert result["stdout"] == ""
        assert result["exit_code"] == 0

    def test_missing_file_path(self):
        from aipass.hooks.apps.handlers.lifecycle.auto_fix import handle

        result = handle({"tool_name": "Edit", "tool_input": {}})
        assert result["stdout"] == ""
        assert result["exit_code"] == 0

    def test_skip_unknown_extension(self):
        from aipass.hooks.apps.handlers.lifecycle.auto_fix import handle

        result = handle({"tool_name": "Edit", "tool_input": {"file_path": "/tmp/file.xyz"}})
        assert result["stdout"] == ""
        assert result["exit_code"] == 0
        assert "sound" not in result


class TestAutofixPython:
    @patch("aipass.hooks.apps.handlers.lifecycle.auto_fix._run_seedgo_checklist", return_value=[])
    @patch("aipass.hooks.apps.handlers.lifecycle.auto_fix._run_pyright_check", return_value=[])
    @patch("aipass.hooks.apps.handlers.lifecycle.auto_fix._run_ruff_lint_structured", return_value=[])
    @patch("aipass.hooks.apps.handlers.lifecycle.auto_fix._run_python_checks", return_value=[])
    def test_python_no_errors(self, mock_py, mock_ruff_s, mock_pyright, mock_seedgo):
        from aipass.hooks.apps.handlers.lifecycle.auto_fix import handle

        result = handle({"tool_name": "Edit", "tool_input": {"file_path": "/tmp/clean.py"}})
        assert result["exit_code"] == 0
        parsed = json.loads(result["stdout"])
        assert parsed["systemMessage"] == "[diagnostics] ok"
        assert "sound" not in result

    @patch("aipass.hooks.apps.handlers.lifecycle.auto_fix._run_seedgo_checklist", return_value=[])
    @patch("aipass.hooks.apps.handlers.lifecycle.auto_fix._run_pyright_check", return_value=[])
    @patch("aipass.hooks.apps.handlers.lifecycle.auto_fix._run_ruff_lint_structured", return_value=[])
    @patch("aipass.hooks.apps.handlers.lifecycle.auto_fix._run_python_checks")
    def test_python_syntax_error(self, mock_py, mock_ruff_s, mock_pyright, mock_seedgo):
        from aipass.hooks.apps.handlers.lifecycle.auto_fix import handle

        mock_py.return_value = ["SYNTAX: invalid syntax at line 5"]
        result = handle({"tool_name": "Edit", "tool_input": {"file_path": "/tmp/bad.py"}})
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
    def test_python_ruff_lint_errors(self, mock_py, mock_ruff_s, mock_pyright, mock_seedgo):
        from aipass.hooks.apps.handlers.lifecycle.auto_fix import handle

        mock_py.return_value = ["LINT: bad.py:10:1: F401 unused import"]
        result = handle({"tool_name": "Write", "tool_input": {"file_path": "/tmp/bad.py"}})
        parsed = json.loads(result["stdout"])
        assert "LINT" in parsed["hookSpecificOutput"]["additionalContext"]
        assert result.get("sound") == "auto fix diagnostics"

    @patch("aipass.hooks.apps.handlers.lifecycle.auto_fix._run_seedgo_checklist", return_value=[])
    @patch("aipass.hooks.apps.handlers.lifecycle.auto_fix._run_ruff_lint_structured", return_value=[])
    @patch("aipass.hooks.apps.handlers.lifecycle.auto_fix._run_python_checks", return_value=[])
    def test_python_pyright_errors(self, mock_py, mock_ruff_s, mock_seedgo):
        from aipass.hooks.apps.handlers.lifecycle.auto_fix import handle

        with patch(
            "aipass.hooks.apps.handlers.lifecycle.auto_fix._run_pyright_check",
            return_value=[{"line": 42, "message": "Cannot assign to declared type"}],
        ):
            result = handle({"tool_name": "Edit", "tool_input": {"file_path": "/tmp/typed.py"}})

        parsed = json.loads(result["stdout"])
        assert "TYPE: L42" in parsed["hookSpecificOutput"]["additionalContext"]
        assert result.get("sound") == "auto fix diagnostics"

    @patch("aipass.hooks.apps.handlers.lifecycle.auto_fix._run_pyright_check", return_value=[])
    @patch("aipass.hooks.apps.handlers.lifecycle.auto_fix._run_ruff_lint_structured", return_value=[])
    @patch("aipass.hooks.apps.handlers.lifecycle.auto_fix._run_python_checks", return_value=[])
    def test_seedgo_violations_surfaced(self, mock_py, mock_ruff_s, mock_pyright):
        from aipass.hooks.apps.handlers.lifecycle.auto_fix import handle

        with patch(
            "aipass.hooks.apps.handlers.lifecycle.auto_fix._run_seedgo_checklist",
            return_value=["missing file header"],
        ):
            result = handle({"tool_name": "Edit", "tool_input": {"file_path": "/tmp/noheader.py"}})

        parsed = json.loads(result["stdout"])
        assert "SEEDGO: missing file header" in parsed["hookSpecificOutput"]["additionalContext"]
        assert result.get("sound") == "auto fix diagnostics"


class TestAutoFixStateFile:
    @patch("aipass.hooks.apps.handlers.lifecycle.auto_fix._run_seedgo_checklist", return_value=[])
    @patch("aipass.hooks.apps.handlers.lifecycle.auto_fix._run_pyright_check")
    @patch("aipass.hooks.apps.handlers.lifecycle.auto_fix._run_ruff_lint_structured")
    @patch("aipass.hooks.apps.handlers.lifecycle.auto_fix._run_python_checks", return_value=[])
    def test_state_file_written_on_errors(self, mock_py, mock_ruff_s, mock_pyright, mock_seedgo):
        from aipass.hooks.apps.handlers.lifecycle.auto_fix import handle

        mock_ruff_s.return_value = [{"line": 5, "message": "F401: unused import"}]
        mock_pyright.return_value = [{"line": 10, "message": "Type error here"}]

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
            state_path = Path(tf.name)

        try:
            with patch("aipass.hooks.apps.handlers.lifecycle.auto_fix.STATE_FILE", state_path):
                result = handle({"tool_name": "Edit", "tool_input": {"file_path": "/tmp/errors.py"}})

            assert result.get("sound") == "auto fix diagnostics"
            assert state_path.exists()
            state = json.loads(state_path.read_text(encoding="utf-8"))
            assert len(state["errors"]) == 2
            assert state["errors"][0]["line"] == 5
            assert state["errors"][1]["line"] == 10
        finally:
            if state_path.exists():
                state_path.unlink()

    @patch("aipass.hooks.apps.handlers.lifecycle.auto_fix._run_seedgo_checklist", return_value=[])
    @patch("aipass.hooks.apps.handlers.lifecycle.auto_fix._run_pyright_check", return_value=[])
    @patch("aipass.hooks.apps.handlers.lifecycle.auto_fix._run_ruff_lint_structured", return_value=[])
    @patch("aipass.hooks.apps.handlers.lifecycle.auto_fix._run_python_checks", return_value=[])
    def test_state_file_cleared_on_no_errors(self, mock_py, mock_ruff_s, mock_pyright, mock_seedgo):
        from aipass.hooks.apps.handlers.lifecycle.auto_fix import handle

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as tf:
            state_path = Path(tf.name)
            tf.write('{"file": "/tmp/old.py", "errors": [{"line": 1, "message": "old"}]}')

        try:
            with patch("aipass.hooks.apps.handlers.lifecycle.auto_fix.STATE_FILE", state_path):
                result = handle({"tool_name": "Edit", "tool_input": {"file_path": "/tmp/clean.py"}})

            assert "sound" not in result
            assert not state_path.exists()
        finally:
            if state_path.exists():
                state_path.unlink()


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
    def test_check_syntax_error(self, mock_run):
        from aipass.hooks.apps.handlers.lifecycle.auto_fix import _check_syntax

        mock_run.return_value = MagicMock(returncode=1, stderr="SyntaxError: invalid syntax")
        errors = _check_syntax("/tmp/bad.py")
        assert len(errors) == 1
        assert "SYNTAX" in errors[0]

    @patch("subprocess.run")
    def test_check_syntax_clean(self, mock_run):
        from aipass.hooks.apps.handlers.lifecycle.auto_fix import _check_syntax

        mock_run.return_value = MagicMock(returncode=0, stderr="")
        errors = _check_syntax("/tmp/good.py")
        assert errors == []

    @patch("subprocess.run")
    def test_check_ruff_lint_findings(self, mock_run):
        from aipass.hooks.apps.handlers.lifecycle.auto_fix import _check_ruff_lint

        mock_run.return_value = MagicMock(returncode=1, stdout="bad.py:10:1: F401 unused import\n")
        errors = _check_ruff_lint("/tmp/bad.py")
        assert len(errors) == 1
        assert "LINT" in errors[0]
        # bare "ruff" relies on PATH the hook env doesn't have — must go through the venv interpreter
        assert mock_run.call_args[0][0][:3] == [sys.executable, "-m", "ruff"]

    @patch("subprocess.run")
    def test_check_ruff_format_drift(self, mock_run):
        from aipass.hooks.apps.handlers.lifecycle.auto_fix import _check_ruff_format

        mock_run.return_value = MagicMock(returncode=1)
        errors = _check_ruff_format("/tmp/unformatted.py")
        assert len(errors) == 1
        assert "FORMAT" in errors[0]
        assert mock_run.call_args[0][0][:3] == [sys.executable, "-m", "ruff"]

    @patch("subprocess.run")
    def test_run_ruff_lint_structured_returns_dicts(self, mock_run):
        from aipass.hooks.apps.handlers.lifecycle.auto_fix import _run_ruff_lint_structured

        mock_run.return_value = MagicMock(
            returncode=1,
            stdout=json.dumps(
                [
                    {"location": {"row": 5}, "code": "F401", "message": "unused import os"},
                ]
            ),
        )
        errors = _run_ruff_lint_structured("/tmp/lint.py")
        assert len(errors) == 1
        assert errors[0]["line"] == 5
        assert "F401" in errors[0]["message"]
        assert mock_run.call_args[0][0][:3] == [sys.executable, "-m", "ruff"]

    @patch("subprocess.run")
    def test_run_ruff_lint_structured_skips_claude_hooks(self, mock_run):
        from aipass.hooks.apps.handlers.lifecycle.auto_fix import _run_ruff_lint_structured

        errors = _run_ruff_lint_structured("/home/user/.claude/hooks/myhook.py")
        assert errors == []
        mock_run.assert_not_called()

    @patch("subprocess.run")
    def test_run_pyright_check_returns_errors(self, mock_run):
        from aipass.hooks.apps.handlers.lifecycle.auto_fix import _run_pyright_check

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
        errors = _run_pyright_check("/tmp/typed.py")
        assert len(errors) == 1
        assert errors[0]["line"] == 42

    @patch("subprocess.run")
    def test_run_pyright_skips_claude_hooks(self, mock_run):
        from aipass.hooks.apps.handlers.lifecycle.auto_fix import _run_pyright_check

        errors = _run_pyright_check("/home/user/.claude/hooks/myhook.py")
        assert errors == []
        mock_run.assert_not_called()

    @patch("subprocess.run")
    def test_run_seedgo_checklist_returns_violations(self, mock_run):
        from aipass.hooks.apps.handlers.lifecycle.auto_fix import _run_seedgo_checklist

        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="✓ file_header: OK\n✗ missing encoding param\n✗ bad import\n",
        )
        with patch.dict("os.environ", {"AIPASS_HOME": "/home/user/Projects/AIPass"}):
            violations = _run_seedgo_checklist("/tmp/check.py")
        assert len(violations) == 2
        assert "missing encoding param" in violations[0]

    @patch("subprocess.run")
    def test_run_seedgo_skips_claude_hooks(self, mock_run):
        from aipass.hooks.apps.handlers.lifecycle.auto_fix import _run_seedgo_checklist

        violations = _run_seedgo_checklist("/home/user/.claude/hooks/myhook.py")
        assert violations == []
        mock_run.assert_not_called()

    def test_run_seedgo_skips_without_aipass_home(self):
        from aipass.hooks.apps.handlers.lifecycle.auto_fix import _run_seedgo_checklist

        with patch.dict("os.environ", {}, clear=True):
            violations = _run_seedgo_checklist("/tmp/check.py")
        assert violations == []


class TestRetiredLoggerDebugRule:
    """logger.debug() is supported by prax's SystemLogger — the rule is retired.

    The rule told the fleet the opposite of what @seedgo teaches, on the same
    line of code, for as long as both existed. These pin the retirement so it
    cannot be re-added by reflex.
    """

    def test_logger_debug_rule_is_gone_from_the_pattern_table(self):
        from aipass.hooks.apps.handlers.lifecycle.auto_fix import PYTHON_PATTERNS

        assert "logger_debug" not in PYTHON_PATTERNS

    def test_no_pattern_rule_targets_logger_debug(self):
        from aipass.hooks.apps.handlers.lifecycle.auto_fix import PYTHON_PATTERNS

        assert not [c for c in PYTHON_PATTERNS.values() if "logger.debug" in c["pattern"]]

    def test_a_file_calling_logger_debug_reports_no_violation(self, temp_test_dir):
        from aipass.hooks.apps.handlers.lifecycle.auto_fix import _check_patterns

        target = temp_test_dir / "uses_debug.py"
        target.write_text('logger.debug("hello")\n', encoding="utf-8")

        assert _check_patterns(str(target)) == []

    def test_prax_system_logger_really_has_debug(self):
        """The premise the retirement rests on — asserted, not assumed."""
        from aipass.prax.apps.modules.logger import system_logger

        assert callable(getattr(system_logger, "debug", None))


class TestAutoFixPatterns:
    def test_check_line_pattern_matches(self):
        from aipass.hooks.apps.handlers.lifecycle.auto_fix import _check_line_pattern

        assert _check_line_pattern("    logger.debug(msg)", "logger.debug(") is True

    def test_check_line_pattern_skips_comments(self):
        from aipass.hooks.apps.handlers.lifecycle.auto_fix import _check_line_pattern

        assert _check_line_pattern("    # logger.debug(msg)", "logger.debug(") is False

    def test_check_line_pattern_skips_strings(self):
        from aipass.hooks.apps.handlers.lifecycle.auto_fix import _check_line_pattern

        assert _check_line_pattern('    msg = "logger.debug(test)"', "logger.debug(") is False

    def test_check_emoji_list_clean(self):
        from aipass.hooks.apps.handlers.lifecycle.auto_fix import _check_emoji_list

        assert _check_emoji_list(["hello", "world"], "emojis") is None

    def test_check_emoji_list_suspicious(self):
        from aipass.hooks.apps.handlers.lifecycle.auto_fix import _check_emoji_list

        result = _check_emoji_list(["a"], "emojis")
        assert result is not None
        assert "EMOJI CORRUPTION" in result
