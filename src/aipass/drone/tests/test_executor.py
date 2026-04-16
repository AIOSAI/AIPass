"""Tests for the subprocess executor module."""

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from aipass.drone.apps.handlers.exceptions import CommandExecutionError
from aipass.drone.apps.handlers.executor import execute_command


# ---------------------------------------------------------------------------
# 1. Captured mode — returns stdout/stderr as strings
# ---------------------------------------------------------------------------


class TestCapturedMode:
    """Tests for captured (non-interactive) execution mode."""

    def test_captured_stdout(self, temp_test_dir: Path):
        """Captured mode returns stdout as a decoded string."""
        result = execute_command(
            sys.executable,
            ["-c", "print('hello world')"],
            cwd=str(temp_test_dir),
        )
        assert result.stdout.strip() == "hello world"
        assert result.exit_code == 0

    def test_captured_stderr(self, temp_test_dir: Path):
        """Captured mode returns stderr as a decoded string."""
        result = execute_command(
            sys.executable,
            ["-c", "import sys; sys.stderr.write('err msg\\n')"],
            cwd=str(temp_test_dir),
        )
        assert "err msg" in result.stderr
        assert result.exit_code == 0

    def test_captured_both_streams(self, temp_test_dir: Path):
        """Both stdout and stderr are captured simultaneously."""
        code = "import sys; print('out'); sys.stderr.write('err\\n')"
        result = execute_command(sys.executable, ["-c", code], cwd=str(temp_test_dir))
        assert "out" in result.stdout
        assert "err" in result.stderr


# ---------------------------------------------------------------------------
# 2. Captured mode — timeout enforcement
# ---------------------------------------------------------------------------


class TestTimeout:
    """Timeout enforcement in captured mode."""

    def test_timeout_raises_command_execution_error(self, temp_test_dir: Path):
        """Exceeding the timeout raises CommandExecutionError."""
        with pytest.raises(CommandExecutionError, match="timed out"):
            execute_command(
                sys.executable,
                ["-c", "import time; time.sleep(10)"],
                cwd=str(temp_test_dir),
                timeout=1,
            )

    def test_timeout_chains_original_exception(self, temp_test_dir: Path):
        """CommandExecutionError wraps the original TimeoutExpired."""
        with pytest.raises(CommandExecutionError) as exc_info:
            execute_command(
                sys.executable,
                ["-c", "import time; time.sleep(10)"],
                cwd=str(temp_test_dir),
                timeout=1,
            )
        assert isinstance(exc_info.value.__cause__, subprocess.TimeoutExpired)


# ---------------------------------------------------------------------------
# 3. Interactive mode — no capture
# ---------------------------------------------------------------------------


class TestInteractiveMode:
    """Tests for interactive execution mode."""

    def test_interactive_stdout_is_empty(self, temp_test_dir: Path):
        """Interactive mode does not capture stdout."""
        result = execute_command(
            sys.executable,
            ["-c", "print('hello')"],
            cwd=str(temp_test_dir),
            interactive=True,
        )
        assert result.stdout == ""

    def test_interactive_stderr_is_empty(self, temp_test_dir: Path):
        """Interactive mode does not capture stderr."""
        result = execute_command(
            sys.executable,
            ["-c", "import sys; sys.stderr.write('err\\n')"],
            cwd=str(temp_test_dir),
            interactive=True,
        )
        assert result.stderr == ""

    def test_interactive_exit_code_propagates(self, temp_test_dir: Path):
        """Interactive mode still returns the process exit code."""
        result = execute_command(
            sys.executable,
            ["-c", "raise SystemExit(7)"],
            cwd=str(temp_test_dir),
            interactive=True,
        )
        assert result.exit_code == 7


# ---------------------------------------------------------------------------
# 4. Interactive mode — no timeout
# ---------------------------------------------------------------------------


class TestInteractiveNoTimeout:
    """Interactive mode must not pass a timeout to subprocess.run."""

    def test_no_timeout_kwarg(self, temp_test_dir: Path):
        """subprocess.run is called without a timeout arg in interactive mode."""
        with patch("aipass.drone.apps.handlers.executor.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
            execute_command(
                sys.executable,
                ["-c", "pass"],
                cwd=str(temp_test_dir),
                interactive=True,
            )
            call_kwargs = mock_run.call_args.kwargs
            assert "timeout" not in call_kwargs


# ---------------------------------------------------------------------------
# 5. FileNotFoundError wraps to CommandExecutionError
# ---------------------------------------------------------------------------


class TestFileNotFoundWrapping:
    """FileNotFoundError from a missing executable wraps correctly."""

    def test_missing_executable_raises(self, temp_test_dir: Path):
        """Non-existent executable raises CommandExecutionError."""
        with pytest.raises(CommandExecutionError, match="Executable not found"):
            execute_command(
                "this_executable_does_not_exist_xyz",
                [],
                cwd=str(temp_test_dir),
            )

    def test_missing_executable_chains_cause(self, temp_test_dir: Path):
        """The original FileNotFoundError is chained."""
        with pytest.raises(CommandExecutionError) as exc_info:
            execute_command(
                "this_executable_does_not_exist_xyz",
                [],
                cwd=str(temp_test_dir),
            )
        assert isinstance(exc_info.value.__cause__, FileNotFoundError)


# ---------------------------------------------------------------------------
# 6. OSError wraps to CommandExecutionError
# ---------------------------------------------------------------------------


class TestOSErrorWrapping:
    """Generic OSError wraps to CommandExecutionError."""

    def test_oserror_wraps(self, temp_test_dir: Path):
        """An OSError from subprocess.run becomes CommandExecutionError."""
        with patch(
            "aipass.drone.apps.handlers.executor.subprocess.run",
            side_effect=OSError("mock OS failure"),
        ):
            with pytest.raises(CommandExecutionError, match="OS error"):
                execute_command(
                    sys.executable,
                    ["-c", "pass"],
                    cwd=str(temp_test_dir),
                )

    def test_oserror_chains_cause(self, temp_test_dir: Path):
        """The original OSError is preserved as __cause__."""
        with patch(
            "aipass.drone.apps.handlers.executor.subprocess.run",
            side_effect=OSError("mock OS failure"),
        ):
            with pytest.raises(CommandExecutionError) as exc_info:
                execute_command(
                    sys.executable,
                    ["-c", "pass"],
                    cwd=str(temp_test_dir),
                )
            assert isinstance(exc_info.value.__cause__, OSError)


# ---------------------------------------------------------------------------
# 7. KeyboardInterrupt in interactive mode returns exit code 130
# ---------------------------------------------------------------------------


class TestKeyboardInterrupt:
    """KeyboardInterrupt handling differs by mode."""

    def test_interactive_returns_130(self, temp_test_dir: Path):
        """Interactive mode catches Ctrl+C and returns exit code 130."""
        with patch(
            "aipass.drone.apps.handlers.executor.subprocess.run",
            side_effect=KeyboardInterrupt,
        ):
            result = execute_command(
                sys.executable,
                ["-c", "pass"],
                cwd=str(temp_test_dir),
                interactive=True,
            )
            assert result.exit_code == 130
            assert result.stdout == ""
            assert result.stderr == ""

    def test_captured_mode_reraises_keyboard_interrupt(self, temp_test_dir: Path):
        """Captured mode does NOT catch KeyboardInterrupt — it propagates."""
        with patch(
            "aipass.drone.apps.handlers.executor.subprocess.run",
            side_effect=KeyboardInterrupt,
        ):
            with pytest.raises(KeyboardInterrupt):
                execute_command(
                    sys.executable,
                    ["-c", "pass"],
                    cwd=str(temp_test_dir),
                    interactive=False,
                )


# ---------------------------------------------------------------------------
# 8. Exit codes propagate correctly
# ---------------------------------------------------------------------------


class TestExitCodes:
    """Exit codes from the subprocess are faithfully returned."""

    def test_exit_code_zero(self, temp_test_dir: Path):
        """Successful command returns exit code 0."""
        result = execute_command(
            sys.executable,
            ["-c", "pass"],
            cwd=str(temp_test_dir),
        )
        assert result.exit_code == 0

    def test_exit_code_one(self, temp_test_dir: Path):
        """Failed command returns exit code 1."""
        result = execute_command(
            sys.executable,
            ["-c", "raise SystemExit(1)"],
            cwd=str(temp_test_dir),
        )
        assert result.exit_code == 1

    def test_exit_code_nonzero_arbitrary(self, temp_test_dir: Path):
        """Arbitrary non-zero exit code propagates."""
        result = execute_command(
            sys.executable,
            ["-c", "raise SystemExit(42)"],
            cwd=str(temp_test_dir),
        )
        assert result.exit_code == 42

    def test_exit_code_syntax_error(self, temp_test_dir: Path):
        """A Python syntax error produces non-zero exit code and stderr output."""
        result = execute_command(
            sys.executable,
            ["-c", "def"],
            cwd=str(temp_test_dir),
        )
        assert result.exit_code != 0
        assert "SyntaxError" in result.stderr


# ---------------------------------------------------------------------------
# 9. Custom env vars are merged with os.environ
# ---------------------------------------------------------------------------


class TestEnvMerging:
    """Custom env dict merges with the process environment."""

    def test_custom_env_var_visible(self, temp_test_dir: Path):
        """A custom env var is available inside the subprocess."""
        result = execute_command(
            sys.executable,
            ["-c", "import os; print(os.environ['AIPASS_TEST_VAR'])"],
            cwd=str(temp_test_dir),
            env={"AIPASS_TEST_VAR": "sentinel_value_123"},
        )
        assert result.stdout.strip() == "sentinel_value_123"

    def test_existing_env_preserved(self, temp_test_dir: Path):
        """Existing environment variables are still present when custom env is set."""
        import os

        expected_path = os.environ.get("PATH", "")
        result = execute_command(
            sys.executable,
            ["-c", "import os; print(os.environ.get('PATH', ''))"],
            cwd=str(temp_test_dir),
            env={"AIPASS_TEST_VAR": "x"},
        )
        assert result.stdout.strip() == expected_path

    def test_no_env_uses_inherited(self, temp_test_dir: Path):
        """When env=None, the subprocess inherits the parent environment."""
        import os

        expected_path = os.environ.get("PATH", "")
        result = execute_command(
            sys.executable,
            ["-c", "import os; print(os.environ.get('PATH', ''))"],
            cwd=str(temp_test_dir),
            env=None,
        )
        assert result.stdout.strip() == expected_path

    def test_custom_env_overrides_existing(self, temp_test_dir: Path):
        """Custom env values override existing environment variables."""
        # We pick a var that definitely exists, then override it
        result = execute_command(
            sys.executable,
            ["-c", "import os; print(os.environ['HOME'])"],
            cwd=str(temp_test_dir),
            env={"HOME": "/tmp/overridden"},
        )
        assert result.stdout.strip() == "/tmp/overridden"


# ---------------------------------------------------------------------------
# 10. shell=False is always used (security)
# ---------------------------------------------------------------------------


class TestShellSecurity:
    """Verify shell=False is always passed to subprocess.run."""

    def test_captured_mode_shell_false(self, temp_test_dir: Path):
        """Captured mode calls subprocess.run with shell=False."""
        with patch("aipass.drone.apps.handlers.executor.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout=b"", stderr=b"")
            execute_command(
                sys.executable,
                ["-c", "pass"],
                cwd=str(temp_test_dir),
            )
            call_kwargs = mock_run.call_args.kwargs
            assert call_kwargs["shell"] is False

    def test_interactive_mode_shell_false(self, temp_test_dir: Path):
        """Interactive mode calls subprocess.run with shell=False."""
        with patch("aipass.drone.apps.handlers.executor.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
            execute_command(
                sys.executable,
                ["-c", "pass"],
                cwd=str(temp_test_dir),
                interactive=True,
            )
            call_kwargs = mock_run.call_args.kwargs
            assert call_kwargs["shell"] is False

    def test_shell_injection_prevented(self, temp_test_dir: Path):
        """Shell metacharacters are NOT interpreted (shell=False)."""
        # If shell=True were used, this would execute `echo pwned` too.
        # With shell=False, the entire string is passed as one arg and
        # Python will fail to parse it — confirming no shell expansion.
        result = execute_command(
            sys.executable,
            ["-c", "import sys; print(sys.argv[1])", "hello; echo pwned"],
            cwd=str(temp_test_dir),
        )
        # The semicolon is treated as literal text, not a shell separator
        assert result.stdout.strip() == "hello; echo pwned"
        assert result.exit_code == 0
