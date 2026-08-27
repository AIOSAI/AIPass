"""Tests for the subprocess executor module."""

import subprocess
import sys
import textwrap
import time
from pathlib import Path
from typing import cast
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

# A child that talks forever and never exits on its own. Used wherever the
# question is "does output buy more life", so the ONLY thing that can end it
# is the executor's own kill path.
FOREVER_CHATTER = textwrap.dedent(
    """\
    import sys, time
    while True:
        sys.stdout.write('tick\\n')
        sys.stdout.flush()
        time.sleep(0.05)
    """
)

# An arbitrary env VALUE, deliberately not a POSIX path: this test asserts that
# an override reaches the child, and a real-looking /tmp path would read as a
# platform assumption the test does not actually make.
_OVERRIDE_SENTINEL = "aipass-env-override-sentinel"


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
        """An OSError from spawning the child becomes CommandExecutionError."""
        with patch(
            "aipass.drone.apps.handlers.executor.subprocess.Popen",
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
            "aipass.drone.apps.handlers.executor.subprocess.Popen",
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
            "aipass.drone.apps.handlers.executor.subprocess.Popen",
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

        The executor now owns the process object, so it also owns the orphan.
        """
        spawned = []
        spawn = subprocess.Popen

        def _spy(*args, **kwargs):
            proc = spawn(*args, **kwargs)
            spawned.append(proc)
            return proc

        # Interrupt the FIRST sleep only. `executor.time` is the shared time
        # module, so a blanket side_effect would also interrupt the sleeps
        # inside Popen.wait() — the very reaping under test.
        real_sleep = time.sleep
        fired: list[float] = []

        def _interrupt_once(seconds: float):
            if not fired:
                fired.append(seconds)
                raise KeyboardInterrupt
            return real_sleep(seconds)

        with patch("aipass.drone.apps.handlers.executor.subprocess.Popen", side_effect=_spy):
            with patch("aipass.drone.apps.handlers.executor.time.sleep", side_effect=_interrupt_once):
                with pytest.raises(KeyboardInterrupt):
                    execute_command(
                        sys.executable,
                        ["-c", "import time; time.sleep(30)"],
                        cwd=str(temp_test_dir),
                        timeout=5,
                    )

        assert spawned, "no child was spawned"
        assert spawned[0].poll() is not None, "child outlived the interrupt — orphaned"


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
            env={"HOME": _OVERRIDE_SENTINEL},
        )
        assert result.stdout.strip() == _OVERRIDE_SENTINEL


# ---------------------------------------------------------------------------
# 10. shell=False is always used (security)
# ---------------------------------------------------------------------------


class TestShellSecurity:
    """Verify shell=False is always passed to subprocess.run."""

    def test_captured_mode_shell_false(self, temp_test_dir: Path):
        """Captured mode spawns the child with shell=False.

        `wraps` rather than a stub: the real Popen still runs, so this asserts
        the flag on a call that actually happened end to end.
        """
        with patch(
            "aipass.drone.apps.handlers.executor.subprocess.Popen",
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
    """The default is 600s, pinned in every layer that can express it.

    Patrick's ruling 2026-08-27: *"it is configured wrong — it should not be
    timing out before it completes; processing time is fine, increase the
    allowed timeout so things can actually complete."* Two live kills in one
    morning: a fleet-wide trinity push died at the 60s default mid-alphabet
    (it needs ~5 minutes), and an `@all` mail broadcast was killed AFTER
    delivering all 18 messages.

    The history that got us here: 30 → 60 on 2026-08-13 (two runners finishing
    around 31s), itself echoing a 30s UserPromptSubmit timeout that silently
    discarded a hooks context for weeks (DPLAN-0285). Each raise was measured
    against work that legitimately took longer.

    Every assertion here names the NUMBER, not the constant. The pre-existing
    tests in TestResolveTimeout compare against DEFAULT_TIMEOUT itself, so they
    stay green at any value — they prove resolution order, not the default.
    """

    def test_default_timeout_is_600(self):
        assert DEFAULT_TIMEOUT == 600

    def test_resolve_returns_600_when_nothing_overrides(self):
        assert resolve_timeout("unknown", "whatever") == 600

    def test_execute_command_signature_default_is_600(self):
        """The signature default must not drift from the constant.

        This layer hardcoded 30 while the constant said 30 — agreeing by
        coincidence, not by reference. Raising the constant alone would have
        left every caller relying on the signature default still at 30.
        """
        import inspect

        sig = inspect.signature(execute_command)
        assert sig.parameters["timeout"].default == 600

    def test_execute_branch_command_signature_default_is_600(self):
        """Same drift hazard one layer up, in router_handler."""
        import inspect

        from aipass.drone.apps.handlers.router_handler import execute_branch_command

        sig = inspect.signature(execute_branch_command)
        assert sig.parameters["timeout"].default == 600

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

    def test_policy_table_is_empty(self):
        """The three entries were REMOVED with the 60 → 600 raise, not dropped.

        `memory process-plans` 120, `memory rollover` 100 and `flow close` 90
        were all written to RAISE above the old 60s default. Against a 600s
        base they invert into CAPS: the three commands we know are slow would
        get the LEAST time of anything in the fleet — the exact failure this
        ruling exists to end.

        The mechanism stays (a policy value is a decision, not a floor — see
        test_policy_below_new_default_still_wins). Only the now-harmful data
        is gone.
        """
        assert TIMEOUT_OVERRIDES == {}

    def test_policy_below_new_default_still_wins(self):
        """A policy value is a decision, not a floor — it wins even if lower.

        Nothing is below 60 today, but the resolution order must not quietly
        become max(policy, default) as the default rises.
        """
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

    The shipped table is EMPTY (see test_policy_table_is_empty), so every test
    that iterates it would now pass without executing a single assertion. A
    vacuously-passing test is worse than no test: it reports coverage it does
    not have. These tests exercise the MECHANISM, so they bring their own data.
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


# ---------------------------------------------------------------------------
# 13. Output extends life — the hang guard, not a performance budget
# ---------------------------------------------------------------------------


class TestOutputExtendsLife:
    """Patrick's ruling 2026-08-27: legitimate work completes, hung work dies.

    The shape: generous base + output-extends-life + hard ceiling. Nothing is
    killed before the base. A child still talking when the base expires buys
    another IDLE_GRACE, repeatedly, up to MAX_TIMEOUT. Silence never SHORTENS
    anything — a long quiet computation still gets its full base.
    """

    def test_silent_child_is_not_killed_before_the_base(self, temp_test_dir: Path):
        """A child that says nothing for most of its base still finishes."""
        code = "import time; time.sleep(1.5); print('done')"
        started = time.monotonic()
        result = execute_command(sys.executable, ["-c", code], cwd=str(temp_test_dir), timeout=4)
        assert result.stdout.strip() == "done"
        assert result.exit_code == 0
        assert time.monotonic() - started >= 1.5

    def test_chattering_child_survives_past_its_base(self, temp_test_dir: Path):
        """Output at the deadline buys an extension instead of a kill.

        This is the @ai_mail broadcast case in miniature: real work, still
        producing, killed mid-flight by a clock that measured nothing.
        """
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

        The numbers are chosen so the ceiling is not a whole number of grace
        quanta above the base (base 1 + 2 + 2 would land on 5, the ceiling is
        4). That is the only arrangement in which the final clamp is visible:
        with an evenly-divisible ceiling, an implementation that forgets to
        clamp lands on exactly the same second and the test proves nothing.
        A missing clamp overshoots by up to one full IDLE_GRACE — two minutes
        past a "hard" ceiling in production.
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
        """The ceiling caps EXTENSION, never the base itself.

        A policy or an operator may legitimately ask for more than MAX_TIMEOUT.
        The ceiling must not quietly become a maximum — that would kill work
        earlier than the number that was actually asked for, which is the exact
        failure this whole build exists to end.
        """
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
        """Output OLDER than IDLE_GRACE is not 'recent' — the child still dies.

        The ceiling is lowered too, so a regression that ignores the recency
        window fails in seconds instead of running to MAX_TIMEOUT.
        """
        monkeypatch.setattr(executor, "IDLE_GRACE", 1)
        monkeypatch.setattr(executor, "MAX_TIMEOUT", 6)
        code = "import sys, time; sys.stdout.write('early\\n'); sys.stdout.flush(); time.sleep(30)"
        started = time.monotonic()
        with pytest.raises(CommandExecutionError, match="timed out"):
            execute_command(sys.executable, ["-c", code], cwd=str(temp_test_dir), timeout=3)
        assert time.monotonic() - started < 5

    def test_silence_is_never_treated_as_recent_output(self, temp_test_dir: Path, monkeypatch):
        """A child that never spoke cannot claim to have spoken recently.

        This is the case a timestamp alone gets WRONG. With a base shorter than
        IDLE_GRACE (base 1 < grace 5 here), the silence since start is itself
        inside the recency window — so an implementation that only compares
        `now - last_output_at` hands a mute child an extension it never earned.
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
        """extend_on_output=False means the number is the number.

        This is what an explicit --drone-timeout buys: a deliberate tight cap
        that extension would make unpredictable.
        """
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


# ---------------------------------------------------------------------------
# 14. Partial output survives the kill (the @ai_mail defect)
# ---------------------------------------------------------------------------


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

    Not cosmetic: the error message echoes the command line, so a sentinel
    living in a -c argument would appear in the message whether or not the
    child's output was ever replayed. Every sentinel assertion below would
    pass against the old, output-discarding code. A test that cannot fail is
    not a test.
    """
    path = directory / "child_program.py"
    path.write_text(body, encoding="utf-8")
    return str(path)


class TestPartialOutputReplay:
    """A killed child's output is EVIDENCE. The old path discarded it.

    An @all broadcast delivered all 18 messages and then reported nothing but
    'Command timed out after 60s' — because TimeoutExpired.stdout/.stderr were
    never read. Work that happened must still be visible.
    """

    @pytest.fixture(autouse=True)
    def _tight_guard(self, monkeypatch):
        """These children SPEAK, so they would earn extensions at real values.

        The point here is what the kill REPORTS, not when it lands — so the
        window and the ceiling are shrunk to keep every case a few seconds.
        """
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


# ---------------------------------------------------------------------------
# 15. Both pipes drain concurrently (the classic Popen deadlock)
# ---------------------------------------------------------------------------


class TestConcurrentPipeDraining:
    """Reading one pipe to EOF while the other fills is a deadlock, not a bug
    you find in review. Pinned because the executor now owns the pipes itself.
    """

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


# ---------------------------------------------------------------------------
# 16. The extension constants
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# 17. The stop ladder — terminate, insist, reap, and say so when it fails
# ---------------------------------------------------------------------------


class _FakeProc:
    """A stand-in for Popen that scripts how a child responds to signals.

    A real child that ignores SIGKILL cannot be built portably, and that is
    precisely the branch worth pinning: it is the only one that leaves
    something behind.
    """

    def __init__(self, *, dies_on_terminate: bool, dies_on_kill: bool = True):
        self.pid = 4242
        self._dies_on_terminate = dies_on_terminate
        self._dies_on_kill = dies_on_kill
        self.calls: list[str] = []

    def terminate(self) -> None:
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


def _as_popen(proc: _FakeProc) -> "subprocess.Popen[bytes]":
    """Hand the scripted stand-in to code typed for a real Popen.

    A cast, not a lie: _stop_process touches only terminate/kill/wait/pid, and
    the point of the fake is to script responses a real child cannot give.
    """
    return cast("subprocess.Popen[bytes]", proc)


class TestStopLadder:
    """SIGTERM first, SIGKILL only if needed, reaped either way."""

    def test_a_child_that_dies_on_terminate_is_never_killed(self):
        proc = _FakeProc(dies_on_terminate=True)
        executor._stop_process(_as_popen(proc))
        assert proc.calls == ["terminate", "wait"]

    def test_a_stubborn_child_is_escalated_to_kill_and_reaped(self):
        proc = _FakeProc(dies_on_terminate=False)
        executor._stop_process(_as_popen(proc))
        assert proc.calls == ["terminate", "wait", "kill", "wait"]

    def test_an_unsignalable_child_stops_the_ladder_immediately(self):
        """terminate() raising means there is nothing left to stop."""
        proc = _FakeProc(dies_on_terminate=True)
        proc.terminate = lambda: (_ for _ in ()).throw(ProcessLookupError())  # type: ignore[method-assign]
        executor._stop_process(_as_popen(proc))
        assert proc.calls == []

    def test_an_unreaped_child_is_reported_not_swallowed(self, caplog):
        """A zombie is invisible unless the guard says so."""
        proc = _FakeProc(dies_on_terminate=False, dies_on_kill=False)
        with caplog.at_level("WARNING"):
            executor._stop_process(_as_popen(proc))
        assert any("zombie" in record.getMessage() for record in caplog.records)

    def test_a_cleanly_reaped_child_produces_no_warning(self, caplog):
        proc = _FakeProc(dies_on_terminate=True)
        with caplog.at_level("WARNING"):
            executor._stop_process(_as_popen(proc))
        assert not [r for r in caplog.records if r.levelname == "WARNING"]
