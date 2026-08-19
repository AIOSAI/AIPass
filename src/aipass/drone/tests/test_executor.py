"""Tests for the subprocess executor module."""

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from aipass.drone.apps.handlers.exceptions import CommandExecutionError
from aipass.drone.apps.handlers.executor import (
    DEFAULT_TIMEOUT,
    TIMEOUT_OVERRIDES,
    execute_command,
    resolve_timeout,
)


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


# ---------------------------------------------------------------------------
# 11. resolve_timeout — policy resolution
# ---------------------------------------------------------------------------


class TestDefaultTimeoutValue:
    """The default is 60s, pinned in every layer that can express it.

    Patrick's ruling 2026-08-13: two known runners finish around 31s and were
    tripping the old 30s default. The wider lesson came the evening before —
    a UserPromptSubmit timeout of 30 silently discarded a hooks context for
    weeks because the real work legitimately took longer (DPLAN-0285).

    Every assertion here names the NUMBER, not the constant. The pre-existing
    tests in TestResolveTimeout compare against DEFAULT_TIMEOUT itself, so they
    stay green at any value — they prove resolution order, not the default.
    """

    def test_default_timeout_is_60(self):
        assert DEFAULT_TIMEOUT == 60

    def test_resolve_returns_60_when_nothing_overrides(self):
        assert resolve_timeout("unknown", "whatever") == 60

    def test_execute_command_signature_default_is_60(self):
        """The signature default must not drift from the constant.

        This layer hardcoded 30 while the constant said 30 — agreeing by
        coincidence, not by reference. Raising the constant alone would have
        left every caller relying on the signature default still at 30.
        """
        import inspect

        sig = inspect.signature(execute_command)
        assert sig.parameters["timeout"].default == 60

    def test_execute_branch_command_signature_default_is_60(self):
        """Same drift hazard one layer up, in router_handler."""
        import inspect

        from aipass.drone.apps.handlers.router_handler import execute_branch_command

        sig = inspect.signature(execute_branch_command)
        assert sig.parameters["timeout"].default == 60

    def test_every_layer_agrees_with_the_constant(self):
        """No layer may express the default as its own literal."""
        import inspect

        from aipass.drone.apps.handlers.router_handler import execute_branch_command

        defaults = {
            "DEFAULT_TIMEOUT": DEFAULT_TIMEOUT,
            "execute_command": inspect.signature(execute_command).parameters["timeout"].default,
            "execute_branch_command": inspect.signature(execute_branch_command).parameters["timeout"].default,
        }
        assert len(set(defaults.values())) == 1, f"layers disagree on the default: {defaults}"

    def test_policy_overrides_are_untouched(self):
        """Raising the default must not have moved any per-command policy."""
        assert TIMEOUT_OVERRIDES["memory"]["process-plans"] == 120
        assert TIMEOUT_OVERRIDES["memory"]["rollover"] == 100
        assert TIMEOUT_OVERRIDES["flow"]["close"] == 90

    def test_policy_below_new_default_still_wins(self):
        """A policy value is a decision, not a floor — it wins even if lower.

        Nothing is below 60 today, but the resolution order must not quietly
        become max(policy, default) as the default rises.
        """
        from aipass.drone.apps.handlers import executor

        original = executor.TIMEOUT_OVERRIDES.get("probe")
        executor.TIMEOUT_OVERRIDES["probe"] = {"quick": 5}
        try:
            assert executor.resolve_timeout("probe", "quick") == 5
        finally:
            if original is None:
                del executor.TIMEOUT_OVERRIDES["probe"]
            else:
                executor.TIMEOUT_OVERRIDES["probe"] = original


class TestResolveTimeout:
    """Timeout resolution: explicit > policy > default."""

    def test_default_timeout(self):
        """Unknown branch+command returns DEFAULT_TIMEOUT."""
        assert resolve_timeout("unknown", "whatever") == DEFAULT_TIMEOUT

    def test_policy_override(self):
        """Known branch+command returns the policy value."""
        for branch, cmds in TIMEOUT_OVERRIDES.items():
            for cmd, expected in cmds.items():
                assert resolve_timeout(branch, cmd) == expected

    def test_explicit_wins_over_policy(self):
        """Explicit timeout overrides the policy map."""
        branch = next(iter(TIMEOUT_OVERRIDES))
        cmd = next(iter(TIMEOUT_OVERRIDES[branch]))
        assert resolve_timeout(branch, cmd, explicit=999) == 999

    def test_explicit_wins_over_default(self):
        """Explicit timeout overrides the default."""
        assert resolve_timeout("unknown", "whatever", explicit=42) == 42

    def test_none_command_returns_default(self):
        """None command (introspection) returns default."""
        assert resolve_timeout("memory", None) == DEFAULT_TIMEOUT

    def test_at_prefix_stripped(self):
        """Leading @ on branch name is stripped before lookup."""
        for branch in TIMEOUT_OVERRIDES:
            cmd = next(iter(TIMEOUT_OVERRIDES[branch]))
            expected = TIMEOUT_OVERRIDES[branch][cmd]
            assert resolve_timeout(f"@{branch}", cmd) == expected


# ---------------------------------------------------------------------------
# 12. Timeout error message includes --timeout hint
# ---------------------------------------------------------------------------


class TestTimeoutErrorMessage:
    """Timeout error tells the caller how to override."""

    def test_timeout_error_includes_override_hint(self, temp_test_dir: Path):
        """The timeout error message mentions --timeout."""
        with pytest.raises(CommandExecutionError, match="--drone-timeout") as exc_info:
            execute_command(
                sys.executable,
                ["-c", "import time; time.sleep(10)"],
                cwd=str(temp_test_dir),
                timeout=1,
            )
        assert "--drone-timeout" in str(exc_info.value)
