# =================== AIPass ====================
# Name: test_executor.py
# Description: Subprocess executor - capture, stream, timeout and kill paths
# Version: 1.0.3
# Created: 2026-03-14
# Modified: 2026-10-17
# =============================================

"""Tests for apps/handlers/executor.py, the subprocess executor."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(stdlib) — subprocess.Popen and the OS signal delivery beneath the kill path

import subprocess
import sys
import textwrap
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from aipass.drone.apps.handlers import executor
from aipass.drone.apps.handlers.exceptions import CommandExecutionError
from aipass.drone.apps.handlers.executor import (
    DEFAULT_TIMEOUT,
    IDLE_GRACE,
    MAX_TIMEOUT,
    TIMEOUT_OVERRIDES,
    execute_command,
    resolve_timeout,
)
from aipass.drone.apps.handlers.router_handler import execute_branch_command

# Never exits on its own: only the executor's kill path can end it.
FOREVER_CHATTER = textwrap.dedent(
    """\
    import sys, time
    while True:
        sys.stdout.write('tick\\n')
        sys.stdout.flush()
        time.sleep(0.05)
    """
)

# Deliberately not a path: the test makes no platform assumption.
_OVERRIDE_SENTINEL = "aipass-env-override-sentinel"


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
        cause = exc_info.value.__cause__
        assert isinstance(cause, subprocess.TimeoutExpired)
        # The type alone does not say WHICH timeout fired.
        assert cause.timeout == 1
        assert cause.cmd[0] == sys.executable


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


class TestInteractiveNoTimeout:
    """Interactive mode must not pass a timeout to subprocess.run."""

    def test_no_timeout_kwarg(self, temp_test_dir: Path):
        """subprocess.run is called without a timeout arg in interactive mode."""
        with patch("aipass.drone.apps.handlers.executor._run_interactive") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
            execute_command(
                sys.executable,
                ["-c", "pass"],
                cwd=str(temp_test_dir),
                interactive=True,
            )
            call_kwargs = mock_run.call_args.kwargs
            assert "timeout" not in call_kwargs


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
        cause = exc_info.value.__cause__
        assert isinstance(cause, FileNotFoundError)
        # Not cause.filename: Windows leaves it None for a missing executable.
        assert "this_executable_does_not_exist_xyz" in str(exc_info.value)


class TestOSErrorWrapping:
    """Generic OSError wraps to CommandExecutionError."""

    def test_oserror_wraps(self, temp_test_dir: Path):
        """An OSError from spawning the child becomes CommandExecutionError."""
        with patch(
            "aipass.drone.apps.handlers.executor._spawn",
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
            "aipass.drone.apps.handlers.executor._spawn",
            side_effect=OSError("mock OS failure"),
        ):
            with pytest.raises(CommandExecutionError) as exc_info:
                execute_command(
                    sys.executable,
                    ["-c", "pass"],
                    cwd=str(temp_test_dir),
                )
            cause = exc_info.value.__cause__
            assert isinstance(cause, OSError)
            # Only the message tells the raised OSError from a fresh one.
            assert str(cause) == "mock OS failure"


class TestKeyboardInterrupt:
    """KeyboardInterrupt handling differs by mode."""

    def test_interactive_returns_130(self, temp_test_dir: Path):
        """Interactive mode catches Ctrl+C and returns exit code 130."""
        with patch(
            "aipass.drone.apps.handlers.executor._run_interactive",
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
            "aipass.drone.apps.handlers.executor._spawn",
            side_effect=KeyboardInterrupt,
        ):
            with pytest.raises(KeyboardInterrupt):
                execute_command(
                    sys.executable,
                    ["-c", "pass"],
                    cwd=str(temp_test_dir),
                    interactive=False,
                )

    def test_captured_mode_kills_the_child_before_reraising(self, temp_test_dir: Path):
        """Ctrl+C during the wait loop must not leave the child running.

        Mutants: the interrupt handler's _stop_process removed; the loop pausing via time.sleep.
        """
        spawned = []
        spawn = subprocess.Popen

        def _spy(*args, **kwargs):
            proc = spawn(*args, **kwargs)
            spawned.append(proc)
            return proc

        # Patch _poll_pause, not time.sleep, so the reaping in Popen.wait() runs for real.
        with patch("aipass.drone.apps.handlers.executor._spawn", side_effect=_spy):
            with patch("aipass.drone.apps.handlers.executor._poll_pause", side_effect=KeyboardInterrupt):
                with pytest.raises(KeyboardInterrupt):
                    execute_command(
                        sys.executable,
                        ["-c", "import time; time.sleep(30)"],
                        cwd=str(temp_test_dir),
                        timeout=5,
                    )

        assert spawned, "no child was spawned"
        assert spawned[0].poll() is not None, "child outlived the interrupt — orphaned"


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
        result = execute_command(
            sys.executable,
            ["-c", "import os; print(os.environ['HOME'])"],
            cwd=str(temp_test_dir),
            env={"HOME": _OVERRIDE_SENTINEL},
        )
        assert result.stdout.strip() == _OVERRIDE_SENTINEL


class TestShellSecurity:
    """Verify shell=False is always passed to subprocess.run."""

    def test_captured_mode_shell_false(self, temp_test_dir: Path):
        """Captured mode spawns the child with shell=False (wraps, so the real Popen runs)."""
        with patch(
            "aipass.drone.apps.handlers.executor._spawn",
            wraps=subprocess.Popen,
        ) as mock_popen:
            execute_command(
                sys.executable,
                ["-c", "pass"],
                cwd=str(temp_test_dir),
            )
            call_kwargs = mock_popen.call_args.kwargs
            assert call_kwargs["shell"] is False

    def test_interactive_mode_shell_false(self, temp_test_dir: Path):
        """Interactive mode calls subprocess.run with shell=False."""
        with patch("aipass.drone.apps.handlers.executor._run_interactive") as mock_run:
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
        result = execute_command(
            sys.executable,
            ["-c", "import sys; print(sys.argv[1])", "hello; echo pwned"],
            cwd=str(temp_test_dir),
        )
        assert result.stdout.strip() == "hello; echo pwned"
        assert result.exit_code == 0


class TestDefaultTimeoutValue:
    """The default is 600s, pinned in every layer that can express it.

    Assertions name the NUMBER: TestResolveTimeout compares to the constant and passes at any value.
    """

    def test_default_timeout_is_600(self):
        assert DEFAULT_TIMEOUT == 600

    def test_resolve_returns_600_when_nothing_overrides(self):
        assert resolve_timeout("unknown", "whatever") == 600

    def test_execute_command_signature_default_is_600(self):
        """The signature default must not drift from the constant."""
        import inspect

        sig = inspect.signature(execute_command)
        assert sig.parameters["timeout"].default == 600

    def test_execute_branch_command_signature_default_is_600(self):
        """Same drift hazard one layer up, in router_handler."""
        import inspect

        sig = inspect.signature(execute_branch_command)
        assert sig.parameters["timeout"].default == 600

    def test_every_layer_agrees_with_the_constant(self):
        """No layer may express the default as its own literal."""
        import inspect

        defaults = {
            "DEFAULT_TIMEOUT": DEFAULT_TIMEOUT,
            "execute_command": inspect.signature(execute_command).parameters["timeout"].default,
            "execute_branch_command": inspect.signature(execute_branch_command).parameters["timeout"].default,
        }
        assert len(set(defaults.values())) == 1, f"layers disagree on the default: {defaults}"

    def test_policy_table_is_empty(self):
        """The policy table ships empty: a "raise" entry below a 600s base becomes a cap."""
        assert TIMEOUT_OVERRIDES == {}

    def test_policy_below_new_default_still_wins(self):
        """A policy value is a decision, not a floor — it wins even if lower (no max())."""
        original = executor.TIMEOUT_OVERRIDES.get("probe")
        executor.TIMEOUT_OVERRIDES["probe"] = {"quick": 5}
        try:
            assert executor.resolve_timeout("probe", "quick") == 5
        finally:
            if original is None:
                del executor.TIMEOUT_OVERRIDES["probe"]
            else:
                executor.TIMEOUT_OVERRIDES["probe"] = original


@pytest.fixture
def synthetic_policy():
    """Inject one throwaway policy entry, then remove it.

    The shipped table is empty, so tests of the mechanism bring their own data or pass vacuously.
    """
    original = executor.TIMEOUT_OVERRIDES.get("probe")
    executor.TIMEOUT_OVERRIDES["probe"] = {"quick": 5, "slow": 777}
    try:
        yield ("probe", "slow", 777)
    finally:
        if original is None:
            executor.TIMEOUT_OVERRIDES.pop("probe", None)
        else:
            executor.TIMEOUT_OVERRIDES["probe"] = original


class TestResolveTimeout:
    """Timeout resolution: explicit > policy > default."""

    def test_default_timeout(self):
        """Unknown branch+command returns DEFAULT_TIMEOUT."""
        assert resolve_timeout("unknown", "whatever") == DEFAULT_TIMEOUT

    def test_policy_override(self, synthetic_policy):
        """A known branch+command returns the policy value."""
        branch, cmd, expected = synthetic_policy
        assert executor.resolve_timeout(branch, cmd) == expected

    def test_explicit_wins_over_policy(self, synthetic_policy):
        """Explicit timeout overrides the policy map."""
        branch, cmd, _expected = synthetic_policy
        assert executor.resolve_timeout(branch, cmd, explicit=999) == 999

    def test_explicit_wins_over_default(self):
        """Explicit timeout overrides the default."""
        assert resolve_timeout("unknown", "whatever", explicit=42) == 42

    def test_none_command_returns_default(self, synthetic_policy):
        """None command (introspection) returns default, policy or not."""
        branch, _cmd, _expected = synthetic_policy
        assert executor.resolve_timeout(branch, None) == DEFAULT_TIMEOUT

    def test_unknown_command_on_known_branch_returns_default(self, synthetic_policy):
        """A branch with a policy table still defaults for uncovered commands."""
        branch, _cmd, _expected = synthetic_policy
        assert executor.resolve_timeout(branch, "not-in-the-table") == DEFAULT_TIMEOUT

    def test_at_prefix_stripped(self, synthetic_policy):
        """Leading @ on branch name is stripped before lookup."""
        branch, cmd, expected = synthetic_policy
        assert executor.resolve_timeout(f"@{branch}", cmd) == expected

    def test_uppercase_branch_lowered(self, synthetic_policy):
        """Lookup is case-insensitive on the branch name."""
        branch, cmd, expected = synthetic_policy
        assert executor.resolve_timeout(branch.upper(), cmd) == expected


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


class TestOutputExtendsLife:
    """Legitimate work completes, hung work dies: base + output-extends-life + hard ceiling."""

    def test_silent_child_is_not_killed_before_the_base(self, temp_test_dir: Path):
        """A child that says nothing for most of its base still finishes."""
        code = "import time; time.sleep(1.5); print('done')"
        started = time.monotonic()
        result = execute_command(sys.executable, ["-c", code], cwd=str(temp_test_dir), timeout=4)
        assert result.stdout.strip() == "done"
        assert result.exit_code == 0
        assert time.monotonic() - started >= 1.5

    def test_chattering_child_survives_past_its_base(self, temp_test_dir: Path):
        """Output at the deadline buys an extension instead of a kill."""
        code = (
            "import sys, time\n"
            "end = time.time() + 2.5\n"
            "while time.time() < end:\n"
            "    sys.stdout.write('tick\\n')\n"
            "    sys.stdout.flush()\n"
            "    time.sleep(0.1)\n"
            "sys.stdout.write('finished\\n')\n"
        )
        result = execute_command(sys.executable, ["-c", code], cwd=str(temp_test_dir), timeout=1)
        assert "finished" in result.stdout
        assert result.exit_code == 0

    def test_extension_never_exceeds_the_ceiling(self, temp_test_dir: Path, monkeypatch):
        """A forever-chattering child is still killed — AT the ceiling, not past it.

        Ceiling 4 is deliberately not base 1 + whole grace quanta (5): only then is a missing clamp visible.
        """
        monkeypatch.setattr(executor, "IDLE_GRACE", 2)
        monkeypatch.setattr(executor, "MAX_TIMEOUT", 4)
        started = time.monotonic()
        with pytest.raises(CommandExecutionError, match="timed out"):
            execute_command(sys.executable, ["-c", FOREVER_CHATTER], cwd=str(temp_test_dir), timeout=1)
        elapsed = time.monotonic() - started
        assert elapsed >= 3.0, f"killed at {elapsed:.1f}s — extension did not happen"
        assert elapsed < 4.6, f"killed at {elapsed:.1f}s — the ceiling was overshot by an extension"

    def test_a_base_above_the_ceiling_is_still_honoured_in_full(self, temp_test_dir: Path, monkeypatch):
        """The ceiling caps EXTENSION, never the base itself."""
        monkeypatch.setattr(executor, "MAX_TIMEOUT", 1)
        started = time.monotonic()
        with pytest.raises(CommandExecutionError, match="timed out"):
            execute_command(
                sys.executable,
                ["-c", "import time; time.sleep(30)"],
                cwd=str(temp_test_dir),
                timeout=3,
            )
        elapsed = time.monotonic() - started
        assert elapsed >= 2.5, f"killed at {elapsed:.1f}s — the ceiling truncated the base"

    def test_silent_child_that_outruns_its_base_is_killed(self, temp_test_dir: Path):
        """Extension requires RECENT OUTPUT. Silence gets the base and no more."""
        started = time.monotonic()
        with pytest.raises(CommandExecutionError, match="timed out"):
            execute_command(
                sys.executable,
                ["-c", "import time; time.sleep(30)"],
                cwd=str(temp_test_dir),
                timeout=1,
            )
        assert time.monotonic() - started < 8

    def test_stale_output_does_not_buy_an_extension(self, temp_test_dir: Path, monkeypatch):
        """Output OLDER than IDLE_GRACE is not 'recent' — the child still dies."""
        monkeypatch.setattr(executor, "IDLE_GRACE", 1)
        monkeypatch.setattr(executor, "MAX_TIMEOUT", 6)
        code = "import sys, time; sys.stdout.write('early\\n'); sys.stdout.flush(); time.sleep(30)"
        started = time.monotonic()
        with pytest.raises(CommandExecutionError, match="timed out"):
            execute_command(sys.executable, ["-c", code], cwd=str(temp_test_dir), timeout=3)
        assert time.monotonic() - started < 5

    def test_silence_is_never_treated_as_recent_output(self, temp_test_dir: Path, monkeypatch):
        """A child that never spoke cannot claim to have spoken recently.

        Base 1 < grace 5: comparing `now - last_output_at` alone would extend a mute child.
        """
        monkeypatch.setattr(executor, "IDLE_GRACE", 5)
        monkeypatch.setattr(executor, "MAX_TIMEOUT", 6)
        started = time.monotonic()
        with pytest.raises(CommandExecutionError, match="timed out"):
            execute_command(
                sys.executable,
                ["-c", "import time; time.sleep(30)"],
                cwd=str(temp_test_dir),
                timeout=1,
            )
        elapsed = time.monotonic() - started
        assert elapsed < 4, f"a mute child bought {elapsed:.1f}s — silence is not output"

    def test_extend_on_output_false_kills_a_chatterer_at_its_base(self, temp_test_dir: Path):
        """extend_on_output=False (an explicit --drone-timeout) means the number is the number."""
        started = time.monotonic()
        with pytest.raises(CommandExecutionError, match="timed out"):
            execute_command(
                sys.executable,
                ["-c", FOREVER_CHATTER],
                cwd=str(temp_test_dir),
                timeout=1,
                extend_on_output=False,
            )
        assert time.monotonic() - started < 8


SENTINEL_CODE = (
    "import sys, time\n"
    "sys.stdout.write('PARTIAL_OUT_SENTINEL\\n')\n"
    "sys.stdout.flush()\n"
    "sys.stderr.write('PARTIAL_ERR_SENTINEL\\n')\n"
    "sys.stderr.flush()\n"
    "time.sleep(30)\n"
)


def _script(directory: Path, body: str) -> str:
    """Write a child program to a FILE rather than passing it as -c.

    The error message echoes the command line, so a -c sentinel would appear whether or not output was replayed.
    """
    path = directory / "child_program.py"
    path.write_text(body, encoding="utf-8")
    return str(path)


class TestPartialOutputReplay:
    """A killed child's output is evidence and is replayed in the timeout error."""

    @pytest.fixture(autouse=True)
    def _tight_guard(self, monkeypatch):
        """These children SPEAK, so shrink grace and ceiling to keep each kill a few seconds."""
        monkeypatch.setattr(executor, "IDLE_GRACE", 1)
        monkeypatch.setattr(executor, "MAX_TIMEOUT", 6)

    def test_partial_stdout_and_stderr_are_replayed(self, temp_test_dir: Path):
        script = _script(temp_test_dir, SENTINEL_CODE)
        with pytest.raises(CommandExecutionError) as exc_info:
            execute_command(sys.executable, [script], cwd=str(temp_test_dir), timeout=2)
        message = str(exc_info.value)
        assert "PARTIAL_OUT_SENTINEL" in message
        assert "PARTIAL_ERR_SENTINEL" in message
        assert "partial stdout" in message
        assert "partial stderr" in message

    def test_cause_carries_output_and_stderr(self, temp_test_dir: Path):
        """The chained TimeoutExpired carries the bytes, not just the fact."""
        script = _script(temp_test_dir, SENTINEL_CODE)
        with pytest.raises(CommandExecutionError) as exc_info:
            execute_command(sys.executable, [script], cwd=str(temp_test_dir), timeout=2)
        cause = exc_info.value.__cause__
        assert isinstance(cause, subprocess.TimeoutExpired)
        assert cause.output is not None and b"PARTIAL_OUT_SENTINEL" in cause.output
        assert cause.stderr is not None and b"PARTIAL_ERR_SENTINEL" in cause.stderr

    def test_message_states_elapsed_and_the_effective_limit(self, temp_test_dir: Path):
        with pytest.raises(CommandExecutionError) as exc_info:
            execute_command(
                sys.executable,
                ["-c", "import time; time.sleep(30)"],
                cwd=str(temp_test_dir),
                timeout=2,
            )
        message = str(exc_info.value)
        assert "limit" in message
        assert "2" in message
        assert "--drone-timeout" in message

    def test_truncation_is_announced_not_silent(self, temp_test_dir: Path):
        """A silent truncation is the same species of lie this build removes."""
        code = (
            "import sys, time\n"
            "sys.stdout.write('HEAD_SENTINEL' + 'A' * 6000 + 'TAIL_SENTINEL\\n')\n"
            "sys.stdout.flush()\n"
            "time.sleep(30)\n"
        )
        script = _script(temp_test_dir, code)
        with pytest.raises(CommandExecutionError) as exc_info:
            execute_command(sys.executable, [script], cwd=str(temp_test_dir), timeout=2)
        message = str(exc_info.value)
        assert "TAIL_SENTINEL" in message, "the newest output must survive"
        assert "HEAD_SENTINEL" not in message, "oversized output should have been trimmed"
        assert "truncated" in message.lower(), "the trim must be announced"
        assert "4000" in message

    def test_short_output_is_not_marked_truncated(self, temp_test_dir: Path):
        script = _script(temp_test_dir, SENTINEL_CODE)
        with pytest.raises(CommandExecutionError) as exc_info:
            execute_command(sys.executable, [script], cwd=str(temp_test_dir), timeout=2)
        assert "truncated" not in str(exc_info.value).lower()


class TestConcurrentPipeDraining:
    """Reading one pipe to EOF while the other fills is a deadlock: both pipes drain concurrently."""

    def test_large_volume_on_both_pipes_does_not_deadlock(self, temp_test_dir: Path):
        code = (
            "import sys\n"
            "sys.stdout.write('o' * 500000)\n"
            "sys.stderr.write('e' * 500000)\n"
            "sys.stdout.flush()\n"
            "sys.stderr.flush()\n"
        )
        result = execute_command(sys.executable, ["-c", code], cwd=str(temp_test_dir), timeout=30)
        assert len(result.stdout) == 500000
        assert len(result.stderr) == 500000
        assert result.exit_code == 0


class TestExtensionConstants:
    """The three numbers of the hang guard, pinned as numbers."""

    def test_idle_grace_is_120(self):
        assert IDLE_GRACE == 120

    def test_max_timeout_is_1800(self):
        assert MAX_TIMEOUT == 1800

    def test_ceiling_is_above_the_default(self):
        """A ceiling below the base would kill work before its own deadline."""
        assert MAX_TIMEOUT > DEFAULT_TIMEOUT

    def test_execute_command_extends_by_default(self):
        import inspect

        sig = inspect.signature(execute_command)
        assert sig.parameters["extend_on_output"].default is True


class _FakeProc:
    """A stand-in for Popen that scripts how a child responds to signals.

    A real child that ignores SIGKILL cannot be built portably.
    """

    def __init__(self, *, dies_on_terminate: bool, dies_on_kill: bool = True, unsignalable: bool = False):
        self.pid = 4242
        self.stdout = None
        self.stderr = None
        self.returncode = None
        self._dies_on_terminate = dies_on_terminate
        self._dies_on_kill = dies_on_kill
        self._unsignalable = unsignalable
        self.calls: list[str] = []

    def poll(self) -> None:
        """Still running at every check, so only the hang guard can end it."""
        return None

    def terminate(self) -> None:
        if self._unsignalable:
            raise ProcessLookupError
        self.calls.append("terminate")

    def kill(self) -> None:
        self.calls.append("kill")

    def wait(self, timeout: float | None = None) -> int:
        self.calls.append("wait")
        if "kill" in self.calls:
            if self._dies_on_kill:
                return 0
            raise subprocess.TimeoutExpired(cmd="fake", timeout=timeout or 0)
        if self._dies_on_terminate:
            return 0
        raise subprocess.TimeoutExpired(cmd="fake", timeout=timeout or 0)


def _time_out(proc: _FakeProc, cwd: Path) -> None:
    """Run execute_command on the scripted child with a zero cap, so the hang guard stops it."""
    with (
        patch("aipass.drone.apps.handlers.executor._spawn", return_value=proc),
        pytest.raises(CommandExecutionError, match="timed out"),
    ):
        execute_command("fake", [], cwd=str(cwd), timeout=0, extend_on_output=False)


class TestStopLadder:
    """SIGTERM first, SIGKILL only if needed, reaped either way — through execute_command's timeout."""

    def test_a_child_that_dies_on_terminate_is_never_killed(self, tmp_path: Path):
        """Mutant: the return after the terminate wait removed."""
        proc = _FakeProc(dies_on_terminate=True)
        _time_out(proc, tmp_path)
        assert proc.calls == ["terminate", "wait"]

    def test_a_stubborn_child_is_escalated_to_kill_and_reaped(self, tmp_path: Path):
        """Mutant: proc.kill() skipped."""
        proc = _FakeProc(dies_on_terminate=False)
        _time_out(proc, tmp_path)
        assert proc.calls == ["terminate", "wait", "kill", "wait"]

    def test_an_unsignalable_child_stops_the_ladder_immediately(self, tmp_path: Path):
        """terminate() raising means there is nothing left to stop (mutant: its return removed)."""
        proc = _FakeProc(dies_on_terminate=True, unsignalable=True)
        _time_out(proc, tmp_path)
        assert proc.calls == []

    def test_an_unreaped_child_is_reported_not_swallowed(self, caplog, tmp_path: Path):
        """A zombie is invisible unless the guard says so (mutant: the zombie line logged at debug)."""
        proc = _FakeProc(dies_on_terminate=False, dies_on_kill=False)
        with caplog.at_level("WARNING"):
            _time_out(proc, tmp_path)
        assert any("zombie" in record.getMessage() for record in caplog.records)

    def test_a_cleanly_reaped_child_produces_no_warning(self, caplog, tmp_path: Path):
        """Mutant: a warning logged on the clean terminate path."""
        proc = _FakeProc(dies_on_terminate=True)
        with caplog.at_level("WARNING"):
            _time_out(proc, tmp_path)
        assert not [r for r in caplog.records if r.levelname == "WARNING"]
